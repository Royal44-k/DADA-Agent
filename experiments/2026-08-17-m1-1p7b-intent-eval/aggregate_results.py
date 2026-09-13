# -*- coding: utf-8 -*-
"""聚合 1.7B 十三分类结果与 M1 门控指标。"""
import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


LABELS = tuple("abcdefghijklm")
BRANCH_NAMES = {
    "a": "新建提醒", "b": "修改/取消/完成提醒", "c": "查询提醒",
    "d": "增删改记忆", "e": "查询记忆", "f": "调整音量",
    "g": "调整亮度", "h": "查询天气", "i": "查询时间日期",
    "j": "产品/知识查询", "k": "晚安", "l": "再见", "m": "闲聊/其他",
}


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def wilson(successes, total, z=1.959963984540054):
    if total <= 0:
        return None, None
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, center - half), min(1.0, center + half)


def percentile(values, p):
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * p
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    fraction = position - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


def confusion_matrix(rows, labels=LABELS):
    matrix = {truth: {prediction: 0 for prediction in labels} for truth in labels}
    for row in rows:
        truth, prediction = row.get("truth"), row.get("prediction")
        if truth in matrix and prediction in matrix[truth]:
            matrix[truth][prediction] += 1
    return matrix


def classification_metrics(rows, labels=LABELS):
    total = len(rows)
    correct = sum(bool(row.get("correct")) for row in rows)
    per_label = {}
    f1_values = []
    for label in labels:
        support = sum(row.get("truth") == label for row in rows)
        predicted = sum(row.get("prediction") == label for row in rows)
        true_positive = sum(row.get("truth") == label and row.get("prediction") == label
                            for row in rows)
        direct = sum(row.get("truth") == label and bool(row.get("direct")) for row in rows)
        direct_correct = sum(row.get("truth") == label and bool(row.get("direct"))
                             and bool(row.get("correct")) for row in rows)
        dangerous = direct - direct_correct
        precision = _ratio(true_positive, predicted) or 0.0
        recall = _ratio(true_positive, support) or 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        low, high = wilson(true_positive, support)
        per_label[label] = {
            "name": BRANCH_NAMES.get(label, label), "support": support,
            "predicted": predicted, "correct": true_positive,
            "precision": precision, "recall": recall, "f1": f1,
            "recall_ci95": [low, high],
            "direct": direct, "direct_coverage": _ratio(direct, support),
            "direct_correct": direct_correct,
            "direct_accuracy": _ratio(direct_correct, direct),
            "dangerous": dangerous,
        }
        f1_values.append(f1)
    low, high = wilson(correct, total)
    return {
        "total": total, "correct": correct, "accuracy": _ratio(correct, total),
        "accuracy_ci95": [low, high],
        "macro_f1": sum(f1_values) / len(f1_values) if f1_values else None,
        "valid_labels": sum(bool(row.get("valid_label")) for row in rows),
        "invalid_labels": sum(not row.get("valid_label") and not row.get("exception_type")
                              for row in rows),
        "per_label": per_label,
    }


def gate_metrics(rows):
    call_success = sum(not row.get("exception_type") for row in rows)
    call_failures = len(rows) - call_success
    direct = sum(bool(row.get("direct")) for row in rows)
    direct_correct = sum(bool(row.get("direct")) and bool(row.get("correct")) for row in rows)
    dangerous = sum(bool(row.get("dangerous_misroute")) for row in rows)
    return {
        "total": len(rows), "call_success": call_success,
        "call_failures": call_failures,
        "call_failure_rate": _ratio(call_failures, len(rows)),
        "direct": direct, "direct_correct": direct_correct,
        "coverage": _ratio(direct, call_success),
        "direct_accuracy": _ratio(direct_correct, direct),
        "dangerous_misroutes": dangerous,
        "dangerous_rate": _ratio(dangerous, call_success),
        "m3_handoff": call_success - direct,
        "m3_handoff_rate": _ratio(call_success - direct, call_success),
    }


def threshold_sweep(rows, thresholds=(0.98055846, 0.99, 0.995, 0.999, 0.9999, 0.99999)):
    call_success = sum(not row.get("exception_type") for row in rows)
    output = []
    for threshold in thresholds:
        direct_rows = [row for row in rows
                       if row.get("valid_label") and row.get("top1") is not None
                       and row.get("margin") is not None
                       and row["top1"] > threshold and row["margin"] > 0.0]
        direct_correct = sum(bool(row.get("correct")) for row in direct_rows)
        dangerous = len(direct_rows) - direct_correct
        output.append({
            "threshold": threshold, "direct": len(direct_rows),
            "coverage": _ratio(len(direct_rows), call_success) or 0.0,
            "direct_correct": direct_correct, "dangerous": dangerous,
            "direct_accuracy": _ratio(direct_correct, len(direct_rows)),
            "dangerous_rate": _ratio(dangerous, call_success) or 0.0,
        })
    return output


def _group_summary(rows):
    total = len(rows)
    correct = sum(bool(row.get("correct")) for row in rows)
    direct = sum(bool(row.get("direct")) for row in rows)
    dangerous = sum(bool(row.get("dangerous_misroute")) for row in rows)
    return {"total": total, "correct": correct, "accuracy": _ratio(correct, total),
            "direct": direct, "direct_rate": _ratio(direct, total),
            "dangerous": dangerous}


def _group_by(rows, key_func):
    grouped = defaultdict(list)
    for row in rows:
        grouped[str(key_func(row))].append(row)
    return {key: _group_summary(grouped[key]) for key in sorted(grouped)}


def stratum_metrics(rows):
    return {
        "asr_noise": _group_by(rows, lambda row: str(bool(row.get("asr_noise"))).lower()),
        "rounds": _group_by(rows, lambda row: row.get("rounds_bucket") or "unknown"),
        "hard_pair_presence": _group_by(
            rows, lambda row: "true" if row.get("hard_pair") else "false"),
        "hard_pair": _group_by(rows, lambda row: row.get("hard_pair") or "none"),
    }


def build_summary(rows, labels=LABELS):
    classification = classification_metrics(rows, labels)
    gate = gate_metrics(rows)
    matrix = confusion_matrix(rows, labels)
    confusion_counts = Counter(
        (row.get("truth"), row.get("prediction")) for row in rows
        if row.get("truth") in labels and row.get("prediction") in labels
        and row.get("truth") != row.get("prediction"))
    top_confusions = [
        {"truth": truth, "prediction": prediction, "count": count}
        for (truth, prediction), count in sorted(
            confusion_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    latency = []
    for row in rows:
        value = row.get("model_latency_ms")
        if not isinstance(value, (int, float)):
            value = row.get("wall_latency_ms")
        if isinstance(value, (int, float)):
            latency.append(float(value))
    latency_summary = {
        "count": len(latency),
        "average": sum(latency) / len(latency) if latency else None,
        "p50": percentile(latency, .50), "p95": percentile(latency, .95),
        "p99": percentile(latency, .99), "max": max(latency) if latency else None,
    }
    return {
        "labels": list(labels), "branch_names": {label: BRANCH_NAMES.get(label, label)
                                                  for label in labels},
        "classification": classification, "gate": gate,
        "threshold_sweep": threshold_sweep(rows),
        "confusion_matrix": matrix, "top_confusions": top_confusions,
        "strata": stratum_metrics(rows), "latency_ms": latency_summary,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    summary = build_summary(rows)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "total": summary["classification"]["total"],
        "accuracy": summary["classification"]["accuracy"],
        "macro_f1": summary["classification"]["macro_f1"],
        "direct_coverage": summary["gate"]["coverage"],
        "direct_accuracy": summary["gate"]["direct_accuracy"],
        "dangerous_misroutes": summary["gate"]["dangerous_misroutes"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
