# -*- coding: utf-8 -*-
import math
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import full_router_probe
import m1_probe

from full_router_probe import build_flow_messages, evaluate_route, production_route


INTERNAL = {
    "a": "reminder_write", "b": "reminder_modify", "c": "reminder_query",
    "d": "memory_write", "e": "memory_query", "f": "volume_adjust",
    "g": "brightness_adjust", "h": "weather_query", "i": "time_query",
    "j": "knowledge_query", "k": "goodnight", "l": "farewell",
    "m": "chitchat",
}


def _logprobs(top1=0.99, second=0.005, token=" f"):
    return {
        "content": [{
            "token": token,
            "logprob": math.log(top1),
            "top_logprobs": [
                {"token": token, "logprob": math.log(top1)},
                {"token": " m", "logprob": math.log(second)},
            ],
        }]
    }


def _row(label="f"):
    history = []
    for index in range(1, 6):
        history.extend([
            ["user", f"旧问题{index}"],
            ["assistant", f"旧回答{index}"],
        ])
    return {
        "sample_id": f"{label}-00001-deadbeef",
        "source_file": f"{label}.jsonl",
        "source_line": 1,
        "label": label,
        "rounds": 6,
        "rounds_bucket": "4+",
        "hard_pair": "f/m",
        "history": history,
        "text": "声音大一点",
        "asr_noise": False,
        "src": "gen",
        "stratum": "noise=false|rounds=4+|hard=true",
    }


def _route_reply(final_char, m1_char="f", top1=0.99, second=0.005,
                 tags=None, calls=None):
    data = {"label": INTERNAL[final_char], "confidence": top1}
    if tags is not None:
        data.update({"m3_tags": list(tags), "prefill": None})
    return {
        "result": SimpleNamespace(ok=True, data=data, speech=None),
        "m1_reply": SimpleNamespace(
            content=m1_char,
            logprobs=_logprobs(top1=top1, second=second, token=" " + m1_char),
            latency_ms=12,
        ),
        "calls": calls or [
            {"model_tier": "1.7b", "content": m1_char, "latency_ms": 12},
        ],
    }


def test_build_flow_messages_applies_production_four_turn_window():
    """Catches sending all raw history instead of M7's latest four turns."""
    messages = build_flow_messages(_row(), system_prompt="classifier", history_turns=4)
    assert messages == [
        {"role": "system", "content": "classifier"},
        {"role": "user", "content": "旧问题2"},
        {"role": "assistant", "content": "旧回答2"},
        {"role": "user", "content": "旧问题3"},
        {"role": "assistant", "content": "旧回答3"},
        {"role": "user", "content": "旧问题4"},
        {"role": "assistant", "content": "旧回答4"},
        {"role": "user", "content": "旧问题5"},
        {"role": "assistant", "content": "旧回答5"},
        {"role": "user", "content": "声音大一点"},
    ]


def test_evaluate_route_records_high_confidence_m1_as_final_direct_route():
    """Catches labelling an M1-direct result as an M3 result or losing final label."""
    row = _row("f")
    result = evaluate_route(row, route_func=lambda *_: _route_reply("f"))
    assert result["m1_prediction"] == "f"
    assert result["m1_direct"] is True
    assert result["m3_used"] is False
    assert result["prediction"] == "f"
    assert result["correct"] is True
    assert result["route_ok"] is True
    assert result["model_call_count"] == 1


def test_evaluate_route_uses_m3_final_label_and_marks_correction():
    """Catches scoring the M1 initial label instead of M3's final routed label."""
    row = _row("f")
    reply = _route_reply(
        "f", m1_char="m", top1=0.70, second=0.20,
        tags=["m3", "m3_disputed"],
        calls=[
            {"model_tier": "1.7b", "content": "m", "latency_ms": 11},
            {"model_tier": "9b", "content": "[tool_calls] volume_adjust", "latency_ms": 90},
        ],
    )
    result = evaluate_route(row, route_func=lambda *_: reply)
    assert result["m1_prediction"] == "m"
    assert result["m1_correct"] is False
    assert result["m1_direct"] is False
    assert result["m3_used"] is True
    assert result["m3_tags"] == ["m3", "m3_disputed"]
    assert result["prediction"] == "f"
    assert result["correct"] is True
    assert result["m3_changed"] is True
    assert result["m3_corrected"] is True
    assert result["m3_worsened"] is False
    assert result["model_call_count"] == 2
    assert result["m3_latency_ms"] == 90


def test_evaluate_route_marks_when_m3_worsens_a_low_confidence_correct_m1():
    """Catches hiding a correct low-confidence M1 label changed to a wrong M3 label."""
    row = _row("f")
    reply = _route_reply(
        "m", m1_char="f", top1=0.70, second=0.20,
        tags=["m3", "m3_disputed"],
        calls=[
            {"model_tier": "1.7b", "content": "f", "latency_ms": 10},
            {"model_tier": "9b", "content": "[tool_calls] chitchat", "latency_ms": 80},
        ],
    )
    result = evaluate_route(row, route_func=lambda *_: reply)
    assert result["m1_correct"] is True
    assert result["m3_used"] is True
    assert result["prediction"] == "m"
    assert result["correct"] is False
    assert result["m3_worsened"] is True
    assert result["m3_corrected"] is False


def test_evaluate_route_counts_unsuccessful_production_route_as_failure():
    """Catches a swallowed M3 exception being treated as a valid chitchat route."""
    row = _row("f")
    reply = _route_reply("f", m1_char="m", top1=0.7, second=0.2)
    reply["result"] = SimpleNamespace(ok=False, data=None, speech="我刚才走神了")
    result = evaluate_route(row, route_func=lambda *_: reply)
    assert result["route_ok"] is False
    assert result["prediction"] is None
    assert result["correct"] is False
    assert result["exception_type"] is None


def test_evaluate_route_records_external_exception_without_fabricating_label():
    """Catches an endpoint exception being converted into a normal final route."""
    row = _row("f")

    def broken(*_args):
        raise TimeoutError("endpoint timed out")

    result = evaluate_route(row, route_func=broken)
    assert result["route_ok"] is False
    assert result["prediction"] is None
    assert result["correct"] is False
    assert result["exception_type"] == "TimeoutError"
    assert "timed out" in result["exception_message"]


def test_production_route_captures_m1_and_restores_isolation_patches():
    """Catches losing the M1 initial label or leaking test fixtures between samples."""
    m1_reply = SimpleNamespace(
        content="f", logprobs=_logprobs(), latency_ms=14,
        tool_calls=None, model_tier="1.7b")
    calls = [{"model_tier": "1.7b", "content": "f", "latency_ms": 14}]

    class FakeLLM:
        def __init__(self):
            self.classify_1p7b = lambda _messages: m1_reply
            self.started = False

        def start_turn_recording(self):
            self.started = True

        def drain_turn_recording(self):
            return list(calls)

    class FakeTaskDB:
        @staticmethod
        def list_active_tasks(_user_id):
            return []

    llm = FakeLLM()
    task_db = FakeTaskDB()
    original_classifier = llm.classify_1p7b
    original_list = task_db.list_active_tasks

    class FakeGate:
        @staticmethod
        def m1_classify(_conn, _text, messages):
            reply = llm.classify_1p7b(messages)
            assert reply is m1_reply
            assert task_db.list_active_tasks("eval-user")
            return SimpleNamespace(
                ok=True,
                data={"label": "volume_adjust", "confidence": 0.99},
                speech=None,
            )

    row = _row("f")
    messages = build_flow_messages(row)
    routed = production_route(
        row, messages, llm_module=llm, gate_module=FakeGate,
        task_db_module=task_db,
        conn=SimpleNamespace(dada_user_id="eval-user"),
    )
    assert routed["result"].data["label"] == "volume_adjust"
    assert routed["m1_reply"] is m1_reply
    assert routed["calls"] == calls
    assert llm.started is True
    assert llm.classify_1p7b is original_classifier
    assert task_db.list_active_tasks == original_list


def test_cli_handles_empty_sample_without_importing_production_models(tmp_path):
    """Catches a CLI that cannot start in isolation or calls models for no rows."""
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    shutil.copy2(Path(full_router_probe.__file__), eval_dir / "full_router_probe.py")
    shutil.copy2(Path(m1_probe.__file__), eval_dir / "m1_probe.py")
    sample = eval_dir / "empty.jsonl"
    output = eval_dir / "results.jsonl"
    sample.write_text("", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(eval_dir / "full_router_probe.py"),
         "--input", str(sample), "--output", str(output)],
        cwd=tmp_path, text=True, capture_output=True, check=False)

    assert completed.returncode == 0, completed.stderr
    assert output.read_text(encoding="utf-8") == ""
