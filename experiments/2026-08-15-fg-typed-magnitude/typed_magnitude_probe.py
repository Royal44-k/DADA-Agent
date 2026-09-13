# -*- coding: utf-8 -*-
"""V100 9B：方向 + 结构化幅度(type/value) + 原文依据全面评测。"""
import json
import os
import statistics
import time
import unicodedata
from dataclasses import asdict, dataclass

from dada.infra import llm


FUZZY_STEPS = {"大": 15, "中": 10, "小": 5}
DIRECTIONS = ("调大", "调小", "不变")
MAGNITUDE_TYPES = ("模糊幅度", "明确变化量", "明确目标值", "极值")


TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "typed_device_adjust",
        "description": (
            "抽取音量或亮度调节的方向、结构化幅度和用户原文依据。"
            "不要把目标值和变化量混淆。"),
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string", "enum": list(DIRECTIONS),
                    "description": (
                        "用户想让数值升高填调大，降低填调小；明确保持、不调整，"
                        "或明确目标值等于当前值时填不变。")},
                "magnitude": {
                    "description": "幅度类型与值必须选择同一个分支，禁止交叉填写。",
                    "anyOf": [
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["模糊幅度"]},
                                "value": {"type": "string", "enum": ["大", "中", "小"]},
                            },
                            "required": ["type", "value"],
                        },
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["明确变化量"]},
                                "value": {"type": "integer", "minimum": 0, "maximum": 100},
                            },
                            "required": ["type", "value"],
                        },
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["明确目标值"]},
                                "value": {"type": "integer", "minimum": 0, "maximum": 100},
                            },
                            "required": ["type", "value"],
                        },
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["极值"]},
                                "value": {"type": "integer", "enum": [0, 100]},
                            },
                            "required": ["type", "value"],
                        },
                    ],
                },
                "adjustment_evidence": {
                    "type": "string",
                    "description": (
                        "当前用户原话中同时支持方向、幅度类型和值的最短完整片段，"
                        "必须逐字节选，不许改写，不许引用设备状态注入。"),
                },
            },
            "required": ["direction", "magnitude", "adjustment_evidence"],
        },
    },
}


SYSTEM_PROMPT = """你是设备调节参数抽取器。对当前用户原话只调用指定工具并严格遵守：
1. direction：想提高数值=调大，想降低数值=调小；明确保持/别动/不用调=不变。
2. magnitude.type：
   - 模糊幅度：没有具体数字，value只能填汉字“大/中/小”，绝不能填数字。大幅/大幅度/很多/明显/强烈/大大=大；没有程度词的普通调高调低、一些/些/适当=中；稍微/一点/一点点/一点儿/轻微/略微/小幅=小。
   - “一些/些”不是“一点”，必须填中；“大幅/很多/明显”不是目标百分比，必须填汉字大，不能填80或100。
   - 普通中幅对照：声音调大一些=调大+中，声音调小一些=调小+中，把声音开大=调大+中，把声音关小=调小+中。这里的“大/小”是方向，不是幅度。
   - 程度词优先于方向形容词：声音大一点=调大+小，声音小一点=调小+小，屏幕亮一点=调大+小，屏幕暗一点=调小+小。“大/小/亮/暗”在这些短语里只决定方向，“一点”决定小幅；不要因为出现“大”就把幅度填大。
   - 明确变化量：提高、降低、增加、减少、加、减了多少；value填变化量。
   - 明确目标值：调到、设为、设置成、改成某值；value填目标值。一半=50，百分之八十=80。
   - 极值：最大/最高/最亮/拉满填100；最小/最低/最暗/静音/归零填0。
3. 明确目标值和极值要与系统提供的当前值做数值比较：目标更高=调大，更低=调小，相等=不变。例如当前60，设为一半(50)或三十(30)都填调小，设为80填调大，设为60填不变。
4. 明确保持不变统一填 direction=不变、type=明确变化量、value=0。
5. 模糊相对指令即使当前已到边界，direction仍按用户原话的意图填写，代码负责截断。
6. adjustment_evidence必须逐字来自最后一条用户原话，不能引用当前设备状态。
7. 如果原话只是查询、描述，或者方向含糊、互相冲突，不要调用工具，直接说明需要澄清。"""


@dataclass(frozen=True)
class Case:
    case_id: str
    group: str
    kind: str
    text: str
    current: int
    direction: str
    magnitude_type: str
    magnitude_value: object


def build_cases():
    cases = []

    def add(group, kind, direction, magnitude_type, value, texts, current=60):
        for text in texts:
            cases.append(Case(
                case_id=f"C{len(cases) + 1:03d}", group=group, kind=kind,
                text=text, current=current, direction=direction,
                magnitude_type=magnitude_type, magnitude_value=value))

    add("模糊-小", "音量", "调大", "模糊幅度", "小", [
        "声音再大一点", "稍微调高一点音量", "音量轻微增加一点",
        "把声音开大一点点", "声音大一点", "音量略微提高",
        "声音稍稍大点", "帮我把音量小幅调高",
    ])
    add("模糊-小", "音量", "调小", "模糊幅度", "小", [
        "再降低点音量", "声音小一点", "稍微把音量调低",
        "音量轻微减少一点", "把声音关小一点点", "音量略微降低",
        "声音稍稍小点", "帮我把音量小幅调低",
    ])
    add("模糊-小", "亮度", "调大", "模糊幅度", "小", [
        "屏幕稍微亮一点", "亮度提高一点点", "屏幕亮一点",
        "把亮度轻微调高", "屏幕略微亮些", "亮度稍稍高点",
        "小幅提高屏幕亮度", "屏幕再亮一点儿",
    ])
    add("模糊-小", "亮度", "调小", "模糊幅度", "小", [
        "屏幕暗一点", "亮度稍微降低一点", "把屏幕调暗一点点",
        "亮度轻微调低", "屏幕略微暗些", "亮度稍稍低点",
        "小幅降低屏幕亮度", "屏幕再暗一点儿",
    ])

    add("模糊-中", "音量", "调大", "模糊幅度", "中", [
        "把音量调高", "声音调大一些", "音量适当提高",
        "声音增加一些", "把声音开大", "音量调得高些",
    ])
    add("模糊-中", "音量", "调小", "模糊幅度", "中", [
        "把音量调低", "声音调小一些", "音量适当降低",
        "声音减少一些", "把声音关小", "音量调得低些",
    ])
    add("模糊-中", "亮度", "调大", "模糊幅度", "中", [
        "把亮度调高", "屏幕调亮一些", "亮度适当提高",
        "屏幕增加一些亮度", "把屏幕调亮", "亮度调得高些",
    ])
    add("模糊-中", "亮度", "调小", "模糊幅度", "中", [
        "把亮度调低", "屏幕调暗一些", "亮度适当降低",
        "屏幕减少一些亮度", "把屏幕调暗", "亮度调得低些",
    ])

    add("模糊-大", "音量", "调大", "模糊幅度", "大", [
        "声音大幅调高", "音量提高很多", "声音明显开大",
        "大大提高音量", "强烈增加音量", "把音量大幅度调高",
    ])
    add("模糊-大", "音量", "调小", "模糊幅度", "大", [
        "音量大幅降低", "声音调低很多", "声音明显关小",
        "大大降低音量", "强烈减少音量", "把音量大幅度调低",
    ])
    add("模糊-大", "亮度", "调大", "模糊幅度", "大", [
        "屏幕大幅调亮", "亮度提高很多", "屏幕明显变亮",
        "大大提高亮度", "强烈增加屏幕亮度", "把亮度大幅度调高",
    ])
    add("模糊-大", "亮度", "调小", "模糊幅度", "大", [
        "亮度大幅降低", "屏幕调暗很多", "屏幕明显变暗",
        "大大降低亮度", "强烈减少屏幕亮度", "把亮度大幅度调低",
    ])

    for value, zh in ((5, "五"), (10, "十"), (15, "十五")):
        add("明确变化量", "音量", "调大", "明确变化量", value, [
            f"音量提高{value}", f"把声音增加{zh}格",
        ])
        add("明确变化量", "音量", "调小", "明确变化量", value, [
            f"音量降低{value}", f"把声音减少{zh}格",
        ])
        add("明确变化量", "亮度", "调大", "明确变化量", value, [
            f"亮度提高{value}个百分点", f"把屏幕亮度增加{zh}",
        ])
        add("明确变化量", "亮度", "调小", "明确变化量", value, [
            f"亮度降低{value}个百分点", f"把屏幕亮度减少{zh}",
        ])

    add("明确目标值", "音量", "调小", "明确目标值", 40,
        ["把音量调到40", "音量设置为四十"])
    add("明确目标值", "音量", "调大", "明确目标值", 80,
        ["音量设为80", "把声音开到百分之八十"])
    add("明确目标值", "音量", "调小", "明确目标值", 50,
        ["把声音改成50", "音量设为一半"])
    add("明确目标值", "音量", "不变", "明确目标值", 60,
        ["音量调到60", "声音保持在百分之六十"])
    add("明确目标值", "亮度", "调小", "明确目标值", 30,
        ["把亮度调到30", "屏幕亮度设置为三十"])
    add("明确目标值", "亮度", "调大", "明确目标值", 90,
        ["亮度设为90", "把屏幕开到百分之九十"])
    add("明确目标值", "亮度", "调小", "明确目标值", 50,
        ["把屏幕亮度改成50", "亮度设为一半"])
    add("明确目标值", "亮度", "不变", "明确目标值", 60,
        ["亮度调到60", "屏幕保持在百分之六十"])

    add("极值", "音量", "调大", "极值", 100,
        ["音量开到最大", "把声音拉满", "音量调到最高"])
    add("极值", "音量", "调小", "极值", 0,
        ["静音", "把音量归零", "声音开到最小"])
    add("极值", "亮度", "调大", "极值", 100,
        ["屏幕调到最亮", "把亮度拉满", "亮度调到最高"])
    add("极值", "亮度", "调小", "极值", 0,
        ["屏幕调到最暗", "把亮度归零", "亮度调到最低"])

    add("不变", "音量", "不变", "明确变化量", 0, [
        "音量保持不变", "不要改变音量", "声音就保持这样", "不用调声音",
    ])
    add("不变", "亮度", "不变", "明确变化量", 0, [
        "亮度保持不变", "屏幕亮度别变", "就保持现在的亮度", "不用调屏幕",
    ])

    add("语境", "音量", "调小", "模糊幅度", "小", [
        "太吵了，声音小一点", "这声音有点震耳，稍微降低一点",
    ])
    add("语境", "音量", "调大", "模糊幅度", "大", [
        "完全听不清，把声音调大很多", "声音太小了，大幅提高音量",
    ])
    add("语境", "亮度", "调大", "模糊幅度", "小", [
        "看不清，屏幕亮一点", "画面太暗了，稍微提高亮度",
    ])
    add("语境", "亮度", "调小", "模糊幅度", "中", [
        "有点刺眼，把屏幕调暗一些", "屏幕太亮，适当降低亮度",
    ])

    add("边界", "音量", "调大", "模糊幅度", "大", ["声音大幅调高"], current=100)
    add("边界", "音量", "调小", "模糊幅度", "小", ["声音再小一点"], current=0)
    add("边界", "亮度", "调大", "模糊幅度", "小", ["屏幕再亮一点"], current=100)
    add("边界", "亮度", "调小", "模糊幅度", "大", ["屏幕大幅调暗"], current=0)
    return cases


BOUNDARY_TEXTS = [
    ("音量", "调一下音量"), ("音量", "你觉得现在声音怎么样"),
    ("音量", "声音小吗"), ("音量", "我还没决定调高还是调低"),
    ("音量", "音量先提高再降低"), ("音量", "声音大点还是小点好"),
    ("音量", "音量是60"), ("音量", "帮我处理一下声音"),
    ("亮度", "调一下屏幕"), ("亮度", "你觉得屏幕亮不亮"),
    ("亮度", "屏幕有点暗"), ("亮度", "我还没决定调亮还是调暗"),
    ("亮度", "亮度先调高再调低"), ("亮度", "亮一点还是暗一点好"),
    ("亮度", "现在亮度是多少"), ("亮度", "帮我处理一下屏幕"),
]


def norm(value):
    value = unicodedata.normalize("NFKC", value or "")
    return "".join(ch for ch in value if not ch.isspace() and
                   unicodedata.category(ch)[0] not in ("P", "S"))


def target_from_fields(current, direction, magnitude_type, magnitude_value):
    if direction == "不变":
        return current
    if magnitude_type == "模糊幅度":
        delta = FUZZY_STEPS[magnitude_value]
        value = current + delta if direction == "调大" else current - delta
    elif magnitude_type == "明确变化量":
        value = current + magnitude_value if direction == "调大" else current - magnitude_value
    else:
        value = magnitude_value
    return max(0, min(100, int(value)))


def expected_target(case):
    return target_from_fields(case.current, case.direction,
                              case.magnitude_type, case.magnitude_value)


def validate_fields(fields, source, current):
    if not isinstance(fields, dict):
        return False, "参数不是对象", None
    direction = fields.get("direction")
    magnitude = fields.get("magnitude")
    evidence = fields.get("adjustment_evidence")
    if direction not in DIRECTIONS:
        return False, "方向枚举非法", None
    if not isinstance(magnitude, dict):
        return False, "幅度不是对象", None
    magnitude_type = magnitude.get("type")
    value = magnitude.get("value")
    if magnitude_type not in MAGNITUDE_TYPES:
        return False, "幅度类型非法", None
    if magnitude_type == "模糊幅度":
        if value not in FUZZY_STEPS:
            return False, "模糊幅度值必须是大中小", None
    else:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            return False, "明确数值必须是0到100整数", None
        if magnitude_type == "极值" and value not in (0, 100):
            return False, "极值只能是0或100", None
    if direction == "不变" and magnitude_type == "明确变化量" and value != 0:
        return False, "不变的变化量必须是0", None
    if magnitude_type == "模糊幅度" and direction == "不变":
        return False, "模糊幅度不能与不变组合", None
    if magnitude_type == "明确变化量":
        if value == 0 and direction != "不变":
            return False, "零变化量的方向必须是不变", None
        if value > 0 and direction == "不变":
            return False, "非零变化量不能与不变组合", None
    if magnitude_type in ("明确目标值", "极值"):
        expected_direction = ("调大" if value > current else
                              "调小" if value < current else "不变")
        if direction != expected_direction:
            return False, "方向与当前值和目标值不一致", None
    if not isinstance(evidence, str) or not norm(evidence) or norm(evidence) not in norm(source):
        return False, "依据不在当前用户原话中", None
    try:
        target = target_from_fields(current, direction, magnitude_type, value)
    except (KeyError, TypeError, ValueError):
        return False, "无法计算目标值", None
    return True, None, target


def extract_tool_call(reply):
    call = next((item for item in (reply.tool_calls or [])
                 if item.get("function", {}).get("name") == "typed_device_adjust"), None)
    if call is None:
        return None, "未调用工具"
    try:
        fields = json.loads(call["function"].get("arguments") or "")
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"参数JSON解析失败:{exc}"
    return fields, None


def call_model(kind, text, current, forced=True):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"当前{kind}数值为{current}。这只是系统状态，不是用户原文依据。"},
        {"role": "user", "content": text},
    ]
    kwargs = {"tools": [TOOL_SCHEMA],
              "tool_choice": ({"type": "function",
                               "function": {"name": "typed_device_adjust"}}
                              if forced else "auto")}
    started = time.perf_counter()
    reply = llm.chat_9b(messages, **kwargs)
    elapsed_ms = (time.perf_counter() - started) * 1000
    fields, error = extract_tool_call(reply)
    return fields, error, elapsed_ms, reply.content or ""


def main():
    cases = build_cases()
    limit = int(os.environ.get("TYPED_LIMIT", "0"))
    repeats = int(os.environ.get("TYPED_REPEATS", "3"))
    selected_groups = {item.strip() for item in
                       os.environ.get("TYPED_GROUPS", "").split(",") if item.strip()}
    selected_ids = {item.strip() for item in
                    os.environ.get("TYPED_CASE_IDS", "").split(",") if item.strip()}
    if selected_groups:
        cases = [case for case in cases if case.group in selected_groups]
    if selected_ids:
        cases = [case for case in cases if case.case_id in selected_ids]
    if limit:
        cases = cases[:limit]
    rows = []
    for case in cases:
        for repeat in range(1, repeats + 1):
            fields, call_error, latency, content = call_model(
                case.kind, case.text, case.current, forced=True)
            valid, validation_error, actual_target = validate_fields(
                fields, case.text, case.current) if fields is not None else (
                    False, call_error, None)
            magnitude = fields.get("magnitude", {}) if isinstance(fields, dict) else {}
            direction_ok = isinstance(fields, dict) and fields.get("direction") == case.direction
            type_ok = magnitude.get("type") == case.magnitude_type
            value_ok = magnitude.get("value") == case.magnitude_value
            evidence = fields.get("adjustment_evidence") if isinstance(fields, dict) else None
            evidence_ok = bool(evidence) and norm(evidence) in norm(case.text)
            target_ok = actual_target == expected_target(case)
            row = {
                **asdict(case), "repeat": repeat,
                "actual_direction": fields.get("direction") if isinstance(fields, dict) else None,
                "actual_magnitude_type": magnitude.get("type"),
                "actual_magnitude_value": magnitude.get("value"),
                "evidence": evidence, "schema_valid": valid,
                "direction_ok": direction_ok, "type_ok": type_ok,
                "value_ok": value_ok, "evidence_ok": evidence_ok,
                "expected_target": expected_target(case), "actual_target": actual_target,
                "target_ok": target_ok,
                "all_ok": all((valid, direction_ok, type_ok, value_ok,
                               evidence_ok, target_ok)),
                "error": call_error or validation_error,
                "latency_ms": round(latency, 1), "content": content[:120],
            }
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)

    boundary_rows = []
    if not limit:
        for index, (kind, text) in enumerate(BOUNDARY_TEXTS, 1):
            for mode, forced in (("自动", False), ("强制", True)):
                fields, error, latency, content = call_model(kind, text, 60, forced=forced)
                row = {
                    "case_id": f"B{index:02d}", "kind": kind, "text": text,
                    "mode": mode, "tool_called": fields is not None,
                    "safe_abstain": fields is None,
                    "fields": fields, "error": error,
                    "content": content[:160], "latency_ms": round(latency, 1),
                }
                boundary_rows.append(row)
                print("BOUNDARY " + json.dumps(row, ensure_ascii=False), flush=True)

    total = len(rows)
    latencies = [row["latency_ms"] for row in rows]
    semantic_stable = 0
    evidence_stable = 0
    for case in cases:
        sample = [row for row in rows if row["case_id"] == case.case_id]
        semantics = {(row["actual_direction"], row["actual_magnitude_type"],
                      json.dumps(row["actual_magnitude_value"], ensure_ascii=False))
                     for row in sample}
        evidences = {row["evidence"] for row in sample}
        semantic_stable += len(semantics) == 1
        evidence_stable += len(evidences) == 1
    groups = {}
    for group in sorted({case.group for case in cases}):
        sample = [row for row in rows if row["group"] == group]
        groups[group] = {
            "calls": len(sample), "passed": sum(row["all_ok"] for row in sample),
            "rate": round(100 * sum(row["all_ok"] for row in sample) / len(sample), 2),
        }
    auto_rows = [row for row in boundary_rows if row["mode"] == "自动"]
    forced_rows = [row for row in boundary_rows if row["mode"] == "强制"]
    summary = {
        "cases": len(cases), "repeats": repeats, "calls": total,
        "schema_pass": sum(row["schema_valid"] for row in rows),
        "direction_pass": sum(row["direction_ok"] for row in rows),
        "type_pass": sum(row["type_ok"] for row in rows),
        "value_pass": sum(row["value_ok"] for row in rows),
        "evidence_pass": sum(row["evidence_ok"] for row in rows),
        "target_pass": sum(row["target_ok"] for row in rows),
        "all_pass": sum(row["all_ok"] for row in rows),
        "all_pass_rate": round(100 * sum(row["all_ok"] for row in rows) / total, 2),
        "semantic_stable_cases": semantic_stable,
        "semantic_stability_rate": round(100 * semantic_stable / len(cases), 2),
        "evidence_stable_cases": evidence_stable,
        "evidence_stability_rate": round(100 * evidence_stable / len(cases), 2),
        "avg_ms": round(statistics.mean(latencies), 1),
        "p95_ms": sorted(latencies)[max(0, int(total * .95) - 1)],
        "max_ms": max(latencies), "groups": groups,
        "boundary_auto_abstain": sum(row["safe_abstain"] for row in auto_rows),
        "boundary_auto_total": len(auto_rows),
        "boundary_forced_abstain": sum(row["safe_abstain"] for row in forced_rows),
        "boundary_forced_total": len(forced_rows),
    }
    print("SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
