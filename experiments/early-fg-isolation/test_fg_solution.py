# -*- coding: utf-8 -*-
from types import SimpleNamespace

import pytest

from dada.agent.branches import _device_common as dc
from dada.agent.branches import brightness_adjust, volume_adjust
from dada.infra import speech
from dada.infra.tools import mcp_device
from dada.mechanisms import m2_extract as m2mod
from dada.mechanisms import m2_validators as mv
from dada.mechanisms.m2_extract import M2Ctx


def _ctx(label, text):
    return SimpleNamespace(user_text=text, intent_label=label,
                           intent_confidence=0.99, turn_id="iso",
                           user_id=7, device_id="iso-dev")


def _mech(data):
    return SimpleNamespace(ok=True, data=data, speech=None)


@pytest.fixture
def rig(monkeypatch):
    state = {"volume": 60, "brightness": 60}
    rec = SimpleNamespace(state=state, say=[], volume=[], brightness=[], apply=True)

    def status(_conn):
        return {
            "audio_speaker": {"volume": state["volume"], "muted": False},
            "screen": {"brightness": state["brightness"]},
        }

    def set_volume(_conn, value):
        rec.volume.append(value)
        if rec.apply:
            state["volume"] = value

    def set_brightness(_conn, value):
        rec.brightness.append(value)
        if rec.apply:
            state["brightness"] = value

    monkeypatch.setattr(mcp_device, "get_device_status", status)
    monkeypatch.setattr(mcp_device, "set_volume", set_volume)
    monkeypatch.setattr(mcp_device, "set_brightness", set_brightness)
    monkeypatch.setattr(speech, "say", lambda _conn, text: rec.say.append(text))
    monkeypatch.setattr(dc.time, "sleep", lambda _delay: None)

    def m2_ok(_conn, messages, params, ctx=None):
        text = messages[-1]["content"]
        current = ctx.extra["current_value"]
        expected = dc._intent_from_text(text, current)
        assert expected is not None
        action, target = expected
        direction = {"increase": ">", "decrease": "<", "keep": "="}[action]
        return _mech({"target_value": target, "direction": direction,
                      "target_evidence": text})

    monkeypatch.setattr(m2mod, "m2_extract", m2_ok)
    return rec


def test_nested_status_extraction():
    status = {"audio_speaker": {"volume": 37}, "screen": {"brightness": 64}}
    assert dc._current_value(status, "volume") == 37
    assert dc._current_value(status, "brightness") == 64


def test_flat_status_backward_compatible():
    assert dc._current_value({"volume": 40}, "volume") == 40
    assert dc._current_value({"brightness": 70}, "brightness") == 70


def test_missing_current_fails_closed():
    v = mv.v_setting("target_value")
    err = v({"target_value": 55, "direction": "<"}, M2Ctx(extra={}))
    assert err and "未读取到设备当前值" in err


def test_relative_volume_fixed_step_and_readback(rig):
    r = volume_adjust.handle(SimpleNamespace(), _ctx("volume_adjust", "再降低点音量"))
    assert rig.volume == [55]
    assert rig.state["volume"] == 55
    assert r.spoken_text == "好的，音量改为55了"


def test_relative_brightness_fixed_step_and_readback(rig):
    r = brightness_adjust.handle(SimpleNamespace(), _ctx("brightness_adjust", "再降低点亮度"))
    assert rig.brightness == [55]
    assert rig.state["brightness"] == 55
    assert r.spoken_text == "好的，亮度改为55了"


def test_explicit_target(rig):
    r = volume_adjust.handle(SimpleNamespace(), _ctx("volume_adjust", "把音量调到40"))
    assert rig.volume == [40]
    assert r.spoken_text == "好的，音量改为40了"


def test_explicit_delta(rig):
    r = brightness_adjust.handle(SimpleNamespace(), _ctx("brightness_adjust", "亮度降低20个百分点"))
    assert rig.brightness == [40]
    assert r.spoken_text == "好的，亮度改为40了"


def test_no_apply_not_reported_as_success(rig):
    rig.apply = False
    r = volume_adjust.handle(SimpleNamespace(), _ctx("volume_adjust", "再降低点音量"))
    assert rig.volume == [55]
    assert rig.state["volume"] == 60
    assert "没有变化" in r.spoken_text
    assert "改为55" not in r.spoken_text


@pytest.mark.parametrize("text", [
    "我还没决定调高还是调低",
    "把音量同时调到30和90",
    "调一下音量",
    "不要调低音量",
])
def test_ambiguous_conflicting_or_negated_asks_without_setting(rig, text):
    r = volume_adjust.handle(SimpleNamespace(), _ctx("volume_adjust", text))
    assert rig.volume == []
    assert r.spoken_text == "你想要我声音更大还是更小呢？"


def test_lower_boundary_keeps_without_setter(rig):
    rig.state["volume"] = 0
    r = volume_adjust.handle(SimpleNamespace(), _ctx("volume_adjust", "再降低点音量"))
    assert rig.volume == []
    assert "现在就是0" in r.spoken_text


def test_upper_boundary_keeps_without_setter(rig):
    rig.state["brightness"] = 100
    r = brightness_adjust.handle(SimpleNamespace(), _ctx("brightness_adjust", "再调亮点"))
    assert rig.brightness == []
    assert "现在就是100" in r.spoken_text


def test_missing_status_stops_before_m2_and_setter(rig, monkeypatch):
    monkeypatch.setattr(mcp_device, "get_device_status", lambda _conn: {})
    r = volume_adjust.handle(SimpleNamespace(), _ctx("volume_adjust", "再降低点音量"))
    assert rig.volume == []
    assert "没读取到设备状态" in r.spoken_text
