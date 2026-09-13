# -*- coding: utf-8 -*-
"""按生产 M1→M3 链路评测最终分支路由。"""
import argparse
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

from m1_probe import (_safe_exception_message, is_direct, load_completed,
                      normalize_label, parse_gate_stats, rewrite_in_sample_order)


LABEL_MAP = {
    "a": "reminder_write", "b": "reminder_modify", "c": "reminder_query",
    "d": "memory_write", "e": "memory_query", "f": "volume_adjust",
    "g": "brightness_adjust", "h": "weather_query", "i": "time_query",
    "j": "knowledge_query", "k": "goodnight", "l": "farewell",
    "m": "chitchat",
}
REVERSE_LABEL_MAP = {value: key for key, value in LABEL_MAP.items()}


def production_route(row, messages, llm_module=None, gate_module=None,
                     task_db_module=None, conn=None):
    if llm_module is None or gate_module is None or task_db_module is None:
        from dada.infra import llm as production_llm
        from dada.infra.db import task as production_task_db
        from dada.mechanisms import m1_gate as production_gate
        llm_module = llm_module or production_llm
        gate_module = gate_module or production_gate
        task_db_module = task_db_module or production_task_db
    conn = conn or SimpleNamespace(dada_user_id="m1-m3-route-eval")
    original_classifier = llm_module.classify_1p7b
    original_list_active = task_db_module.list_active_tasks
    captured = {}
    calls = None

    def capture_classifier(classifier_messages, **kwargs):
        reply = original_classifier(classifier_messages, **kwargs)
        captured["reply"] = reply
        return reply

    llm_module.classify_1p7b = capture_classifier
    task_db_module.list_active_tasks = lambda _user_id: [{
        "task_id": 1, "content": "隔离评测占位提醒",
        "recurrence_type": "once", "next_trigger_time": "2099-01-01 09:00:00",
        "next_instance": None,
    }]
    llm_module.start_turn_recording()
    try:
        result = gate_module.m1_classify(conn, row["text"], messages)
        calls = llm_module.drain_turn_recording()
        return {"result": result, "m1_reply": captured.get("reply"),
                "calls": calls or []}
    finally:
        if calls is None:
            llm_module.drain_turn_recording()
        llm_module.classify_1p7b = original_classifier
        task_db_module.list_active_tasks = original_list_active


def build_flow_messages(row, system_prompt="classifier", history_turns=4):
    history = row.get("history") or []
    messages = []
    for item in history:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("history项必须是[role, content]")
        role, content = item
        if role not in ("user", "assistant") or not isinstance(content, str):
            raise ValueError("history role/content非法")
        messages.append({"role": role, "content": content})
    if not isinstance(row.get("text"), str):
        raise ValueError("text必须是字符串")
    keep = max(0, int(history_turns)) * 2
    if keep:
        messages = messages[-keep:]
    else:
        messages = []
    return ([{"role": "system", "content": system_prompt}] + messages
            + [{"role": "user", "content": row["text"]}])


def evaluate_route(row, route_func=None):
    base = {
        key: row.get(key) for key in (
            "sample_id", "source_file", "source_line", "rounds", "rounds_bucket",
            "asr_noise", "hard_pair", "stratum", "history", "text", "src")
    }
    base.update({
        "truth": row.get("label"),
        "m1_raw_output": None, "m1_prediction": None, "m1_valid_label": False,
        "m1_top1": None, "m1_margin": None, "m1_top5": [],
        "m1_direct": False, "m1_correct": False,
        "prediction": None, "valid_label": False, "correct": False,
        "route_ok": False, "m3_used": False, "m3_tags": [],
        "m3_changed": False, "m3_corrected": False, "m3_worsened": False,
        "model_call_count": 0, "model_calls": [],
        "m1_latency_ms": None, "m3_latency_ms": None, "wall_latency_ms": None,
        "exception_type": None, "exception_message": None,
    })
    try:
        messages = build_flow_messages(row)
        route_func = route_func or production_route
        started = time.perf_counter()
        route = route_func(row, messages)
        base["wall_latency_ms"] = round((time.perf_counter() - started) * 1000, 3)

        m1_reply = route.get("m1_reply")
        raw = getattr(m1_reply, "content", None)
        m1_prediction = normalize_label(raw)
        top1, margin, top5 = parse_gate_stats(getattr(m1_reply, "logprobs", None))
        m1_valid = m1_prediction is not None
        m1_direct = is_direct(m1_valid, top1, margin)
        m1_correct = bool(m1_valid and m1_prediction == row.get("label"))

        calls = []
        for call in route.get("calls") or []:
            calls.append({key: call.get(key) for key in
                          ("model_tier", "content", "latency_ms")})
        m3_latency = sum(
            float(call["latency_ms"]) for call in calls
            if call.get("model_tier") == "9b"
            and isinstance(call.get("latency_ms"), (int, float)))
        result = route.get("result")
        route_ok = bool(result is not None and getattr(result, "ok", False))
        data = getattr(result, "data", None) or {}
        tags = list(data.get("m3_tags") or [])
        m3_used = "m3_tags" in data
        prediction = REVERSE_LABEL_MAP.get(data.get("label")) if route_ok else None
        valid = prediction is not None
        correct = bool(valid and prediction == row.get("label"))
        changed = bool(m3_used and m1_prediction is not None and valid
                       and m1_prediction != prediction)

        base.update({
            "m1_raw_output": raw, "m1_prediction": m1_prediction,
            "m1_valid_label": m1_valid, "m1_top1": top1,
            "m1_margin": margin, "m1_top5": top5,
            "m1_direct": m1_direct, "m1_correct": m1_correct,
            "prediction": prediction, "valid_label": valid,
            "correct": correct, "route_ok": route_ok,
            "m3_used": m3_used, "m3_tags": tags,
            "m3_changed": changed,
            "m3_corrected": bool(m3_used and not m1_correct and correct),
            "m3_worsened": bool(m3_used and m1_correct and not correct),
            "model_call_count": len(calls), "model_calls": calls,
            "m1_latency_ms": getattr(m1_reply, "latency_ms", None),
            "m3_latency_ms": m3_latency if m3_used else None,
        })
    except Exception as exc:
        base["exception_type"] = type(exc).__name__
        base["exception_message"] = _safe_exception_message(exc)
    return base


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--progress-every", type=int, default=50)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--fail-rate-stop", type=float, default=0.01)
    args = parser.parse_args()

    rows = [json.loads(line) for line in
            args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    sample = rows[:args.limit] if args.limit else rows
    if len({row["sample_id"] for row in sample}) != len(sample):
        raise ValueError("抽样集sample_id不唯一")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.touch(exist_ok=True)
    wanted = {row["sample_id"] for row in sample}
    completed = {key: value for key, value in load_completed(args.output).items()
                 if key in wanted}
    pending = [row for row in sample if row["sample_id"] not in completed]
    failures = sum(
        bool(item.get("exception_type")) or not item.get("route_ok")
        for item in completed.values())

    for index, row in enumerate(pending, 1):
        result = evaluate_route(row)
        completed[row["sample_id"]] = result
        failures += bool(result.get("exception_type")) or not result.get("route_ok")
        with args.output.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(result, ensure_ascii=False) + "\n")
            if index % args.checkpoint_every == 0:
                stream.flush()
                os.fsync(stream.fileno())
        done = len(completed)
        if done % args.progress_every == 0 or done == len(sample):
            print(json.dumps({
                "done": done, "total": len(sample),
                "final_correct": sum(bool(item.get("correct"))
                                     for item in completed.values()),
                "m3_used": sum(bool(item.get("m3_used"))
                               for item in completed.values()),
                "m3_corrected": sum(bool(item.get("m3_corrected"))
                                    for item in completed.values()),
                "m3_worsened": sum(bool(item.get("m3_worsened"))
                                   for item in completed.values()),
                "failures": failures,
            }, ensure_ascii=False), flush=True)
        if done >= 100 and failures / done > args.fail_rate_stop:
            raise RuntimeError(
                f"完整路由失败率{failures / done:.2%}超过阈值{args.fail_rate_stop:.2%}")
    rewrite_in_sample_order(args.output, sample, completed)


if __name__ == "__main__":
    main()
