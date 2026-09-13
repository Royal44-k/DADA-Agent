# -*- coding: utf-8 -*-
"""直接调用生产 1.7B 分类接口，记录原始分类与 M1 门控指标。"""
import argparse
import json
import math
import os
import re
import sys
import time
from pathlib import Path


LABELS = set("abcdefghijklm")
TOP1_THRESHOLD = 0.98055846
MARGIN_THRESHOLD = 0.0
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def normalize_label(content):
    if not isinstance(content, str):
        return None
    value = content.strip().lower()
    return value if len(value) == 1 and value in LABELS else None


def parse_gate_stats(logprobs):
    try:
        position = logprobs["content"][0]
        top1 = math.exp(float(position["logprob"]))
        raw_top = position.get("top_logprobs") or []
        top = [{"token": item.get("token"),
                "logprob": float(item["logprob"]),
                "prob": math.exp(float(item["logprob"]))}
               for item in raw_top]
        second = top[1]["prob"] if len(top) > 1 else 0.0
        return top1, top1 - second, top
    except (KeyError, IndexError, TypeError, ValueError, OverflowError):
        return None, None, []


def is_direct(valid, top1, margin, threshold=TOP1_THRESHOLD,
              margin_threshold=MARGIN_THRESHOLD):
    return bool(valid and top1 is not None and margin is not None
                and top1 > threshold and margin > margin_threshold)


def build_messages(row, system_prompt):
    messages = [{"role": "system", "content": system_prompt}]
    for item in row.get("history") or []:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("history项必须是[role, content]")
        role, content = item
        if role not in ("user", "assistant") or not isinstance(content, str):
            raise ValueError("history role/content非法")
        messages.append({"role": role, "content": content})
    if not isinstance(row.get("text"), str):
        raise ValueError("text必须是字符串")
    messages.append({"role": "user", "content": row["text"]})
    return messages


def _safe_exception_message(exc):
    message = str(exc)[:300]
    message = re.sub(r"(?i)(authorization|api[_-]?key|token)\s*[:=]\s*\S+",
                     r"\1=[REDACTED]", message)
    return message


def evaluate_one(row, classify_func=None, system_prompt=None):
    if classify_func is None or system_prompt is None:
        from dada.infra import llm
        from dada.infra.prompts import branch_prompts
        classify_func = classify_func or llm.classify_1p7b
        system_prompt = system_prompt or branch_prompts.M1_CLASSIFIER_SYSTEM

    base = {
        key: row.get(key) for key in (
            "sample_id", "source_file", "source_line", "rounds", "rounds_bucket",
            "asr_noise", "hard_pair", "stratum", "history", "text", "src")
    }
    base["truth"] = row.get("label")
    base.update({
        "raw_output": None, "prediction": None, "valid_label": False,
        "top1": None, "margin": None, "top5": [],
        "model_latency_ms": None, "wall_latency_ms": None,
        "correct": False, "direct": False, "dangerous_misroute": False,
        "exception_type": None, "exception_message": None,
    })
    try:
        messages = build_messages(row, system_prompt)
        started = time.perf_counter()
        reply = classify_func(messages)
        wall_ms = (time.perf_counter() - started) * 1000
        raw = getattr(reply, "content", None)
        prediction = normalize_label(raw)
        top1, margin, top5 = parse_gate_stats(getattr(reply, "logprobs", None))
        valid = prediction is not None
        direct = is_direct(valid, top1, margin)
        correct = valid and prediction == row.get("label")
        base.update({
            "raw_output": raw, "prediction": prediction, "valid_label": valid,
            "top1": top1, "margin": margin, "top5": top5,
            "model_latency_ms": getattr(reply, "latency_ms", None),
            "wall_latency_ms": round(wall_ms, 3), "correct": correct,
            "direct": direct, "dangerous_misroute": bool(direct and not correct),
        })
    except Exception as exc:
        base["exception_type"] = type(exc).__name__
        base["exception_message"] = _safe_exception_message(exc)
    return base


def load_completed(path):
    path = Path(path)
    if not path.exists():
        return {}
    completed = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        sample_id = row.get("sample_id")
        if not sample_id:
            raise ValueError(f"结果第{line_number}行缺sample_id")
        if sample_id in completed:
            raise ValueError(f"结果包含重复sample_id:{sample_id}")
        completed[sample_id] = row
    return completed


def rewrite_in_sample_order(path, sample, completed):
    path = Path(path)
    missing = [row["sample_id"] for row in sample if row["sample_id"] not in completed]
    if missing:
        raise ValueError(f"仍缺{len(missing)}条结果")
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        for item in sample:
            stream.write(json.dumps(completed[item["sample_id"]], ensure_ascii=False) + "\n")
    os.replace(temp, path)


def _read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _select_sample(rows, smoke_one_per_label=False, limit=0):
    if smoke_one_per_label:
        selected, seen = [], set()
        for row in rows:
            if row["label"] not in seen:
                selected.append(row)
                seen.add(row["label"])
        return selected
    return rows[:limit] if limit else rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--progress-every", type=int, default=100)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--smoke-one-per-label", action="store_true")
    parser.add_argument("--fail-rate-stop", type=float, default=0.01)
    args = parser.parse_args()

    sample = _select_sample(_read_jsonl(args.input), args.smoke_one_per_label, args.limit)
    if len({row["sample_id"] for row in sample}) != len(sample):
        raise ValueError("抽样集sample_id不唯一")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    completed = load_completed(args.output)
    completed = {key: value for key, value in completed.items()
                 if key in {row["sample_id"] for row in sample}}

    from dada.infra import llm
    from dada.infra.prompts import branch_prompts
    pending = [row for row in sample if row["sample_id"] not in completed]
    failures = sum(bool(row.get("exception_type")) for row in completed.values())
    for index, row in enumerate(pending, 1):
        result = evaluate_one(row, llm.classify_1p7b,
                              branch_prompts.M1_CLASSIFIER_SYSTEM)
        completed[row["sample_id"]] = result
        failures += bool(result.get("exception_type"))
        with args.output.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(result, ensure_ascii=False) + "\n")
            if index % args.checkpoint_every == 0:
                stream.flush()
                os.fsync(stream.fileno())
        done = len(completed)
        if done % args.progress_every == 0 or done == len(sample):
            print(json.dumps({"done": done, "total": len(sample),
                              "correct": sum(bool(item.get("correct")) for item in completed.values()),
                              "failures": failures}, ensure_ascii=False), flush=True)
        if done >= 100 and failures / done > args.fail_rate_stop:
            raise RuntimeError(f"调用失败率{failures / done:.2%}超过阈值{args.fail_rate_stop:.2%}")
    rewrite_in_sample_order(args.output, sample, completed)


if __name__ == "__main__":
    main()
