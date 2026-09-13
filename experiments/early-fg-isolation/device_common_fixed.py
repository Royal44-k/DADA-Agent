# 4.6/4.7 共用实现（同构分支靠公共函数，不互相 import）
import json
import re
import time

from dada.agent.flow import TurnResult
from dada.infra import speech
from dada.infra.tools import mcp_device
from dada.mechanisms import m2_extract as m2
from dada.mechanisms import m2_validators as mv
from dada.mechanisms import m7_history
from dada.mechanisms.m2_extract import M2Ctx, M2Params
from dada.infra.prompts import branch_prompts as bp
from dada.infra.prompts import speeches as sp

EXIT_SPEECH = sp.EXIT_MISHEARD
VERIFY_FAILED_SPEECH = "调节指令已经发出，但设备状态没有变化，请再试一下"
STATUS_FAILED_SPEECH = "暂时没读取到设备状态，请稍后再试"
DEFAULT_RELATIVE_STEP = 5

_NUMBER_RE = re.compile(r"(?<!\d)(100|[1-9]?\d)(?!\d)")
_UP_WORDS = (
    "调高", "提高", "增大", "增加", "加大", "大一点", "大点",
    "高一点", "高点", "亮一点", "亮点", "调亮", "更亮", "更大",
)
_DOWN_WORDS = (
    "调低", "降低", "减小", "减少", "小一点", "小点", "低一点",
    "低点", "暗一点", "暗点", "调暗", "更暗", "更小",
)
_ABSOLUTE_MARKERS = ("调到", "设到", "设置到", "设置为", "改到", "改成", "开到")
_NEGATIONS = ("别", "不要", "不用", "无需", "不需要", "先不")


def _current_value(status, status_key):
    """读取真实设备嵌套协议，同时兼容旧平铺测试协议。"""
    if not isinstance(status, dict):
        return None
    if status_key == "volume":
        nested = status.get("audio_speaker") or {}
        value = nested.get("volume") if isinstance(nested, dict) else None
    elif status_key == "brightness":
        nested = status.get("screen") or {}
        value = nested.get("brightness") if isinstance(nested, dict) else None
    else:
        value = None
    if value is None:
        value = status.get(status_key)
    if isinstance(value, bool):
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= 100 else None


def _contains_negated_action(text):
    for neg in _NEGATIONS:
        for action in _UP_WORDS + _DOWN_WORDS:
            if neg + action in text or neg + "再" + action in text:
                return True
    return False


def _intent_from_text(text, current):
    """代码判定可确定意图；返回(action, target)。None 表示需要追问。"""
    text = text or ""
    if _contains_negated_action(text):
        return None

    numbers = [int(x) for x in _NUMBER_RE.findall(text)]
    has_up = any(w in text for w in _UP_WORDS)
    has_down = any(w in text for w in _DOWN_WORDS)
    if has_up and has_down:
        return None
    if len(set(numbers)) > 1:
        return None

    number = numbers[0] if numbers else None
    is_absolute = number is not None and any(w in text for w in _ABSOLUTE_MARKERS)
    if is_absolute:
        target = number
        action = "keep" if target == current else (
            "increase" if target > current else "decrease")
        return action, target

    if has_up:
        delta = number if number is not None else DEFAULT_RELATIVE_STEP
        target = min(100, current + delta)
        return ("keep" if target == current else "increase"), target
    if has_down:
        delta = number if number is not None else DEFAULT_RELATIVE_STEP
        target = max(0, current - delta)
        return ("keep" if target == current else "decrease"), target
    return None


def _verify_applied(conn, status_key, target):
    """设置后回读；允许设备短暂异步生效。返回(成功, 最后读值)。"""
    actual = None
    for delay in (0.10, 0.30, 0.60):
        time.sleep(delay)
        actual = _current_value(mcp_device.get_device_status(conn), status_key)
        if actual == target:
            return True, actual
    return False, actual


def adjust(conn, ctx, *, status_key, setter_name, unit_word, ask_speech, rejudge):
    try:
        status = mcp_device.get_device_status(conn)  # 相对调节必须有真实基准
    except Exception:
        speech.say(conn, STATUS_FAILED_SPEECH)
        return TurnResult(spoken_text=STATUS_FAILED_SPEECH)
    current = _current_value(status, status_key)
    if current is None:
        speech.say(conn, STATUS_FAILED_SPEECH)
        return TurnResult(spoken_text=STATUS_FAILED_SPEECH)

    deterministic = _intent_from_text(ctx.user_text, current)
    if deterministic is None:
        speech.say(conn, ask_speech)
        return TurnResult(spoken_text=ask_speech)
    expected_action, expected_target = deterministic

    inject = (f"当前设备状态：{json.dumps(status, ensure_ascii=False)}\n"
              f"请依当前{unit_word}折算用户的相对表述，输出 0-100 绝对值。")
    messages = m7_history.m7_build_messages(conn, f"{ctx.intent_label} 抽取") + [
        {"role": "user", "content": inject},
        {"role": "user", "content": ctx.user_text}]
    # 层2依据核对源只装真实用户轮；设备状态注入严禁混入。
    sources = tuple(m["content"] for m in messages
                    if m["role"] == "user" and m["content"] != inject)

    params = M2Params(
        intent_label=ctx.intent_label,
        required_fields=["target_value", "direction", "target_evidence"],
        extra_validators=[mv.v_setting("target_value")],
        rejudge_protocol=rejudge,
        expected_format=bp.FMT_DEVICE,
        ask_speech=ask_speech,
    )
    m2ctx = M2Ctx(sources=sources, extra={"current_value": current})
    r = m2.m2_extract(conn, messages, params, ctx=m2ctx)
    if not r.ok:
        speech.say(conn, r.speech)
        return TurnResult(spoken_text=r.speech)

    # 9B负责语义方向和原文依据；可确定算术由代码执行，避免“一点”步长漂移。
    model_direction = r.data.get("direction")
    expected_direction = {"increase": ">", "decrease": "<", "keep": "="}[
        expected_action]
    if model_direction != expected_direction:
        speech.say(conn, ask_speech)
        return TurnResult(spoken_text=ask_speech)
    value = expected_target

    if expected_action == "keep":
        spoken = sp.TPL_DEVICE_KEPT.format(unit=unit_word, value=value)
        speech.say(conn, spoken)
        return TurnResult(spoken_text=spoken, action_tags=[ctx.intent_label])

    try:
        getattr(mcp_device, setter_name)(conn, value)
    except Exception:
        speech.say(conn, EXIT_SPEECH)
        return TurnResult(spoken_text=EXIT_SPEECH)

    try:
        applied, actual = _verify_applied(conn, status_key, value)
    except Exception:
        applied, actual = False, None
    if not applied:
        print(f"DEVICE_SETTING_NOT_APPLIED kind={status_key} before={current} "
              f"target={value} actual={actual}")
        speech.say(conn, VERIFY_FAILED_SPEECH)
        return TurnResult(spoken_text=VERIFY_FAILED_SPEECH)

    spoken = sp.TPL_DEVICE_DONE.format(unit=unit_word, value=value)
    speech.say(conn, spoken)
    return TurnResult(spoken_text=spoken, action_tags=[ctx.intent_label])
