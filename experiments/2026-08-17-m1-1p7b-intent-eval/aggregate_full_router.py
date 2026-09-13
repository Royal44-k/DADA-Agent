# -*- coding: utf-8 -*-
"""聚合生产 M1→M3 完整最终路由评测结果。"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from aggregate_results import BRANCH_NAMES, percentile, wilson


def build_full_summary(rows, labels=tuple("abcdefghijklm")):
    rows = list(rows)

    def ratio(numerator, denominator):
        return numerator / denominator if denominator else None

    def classification(prediction_key, correct_key):
        matrix = {truth: {prediction: 0 for prediction in labels}
                  for truth in labels}
        for row in rows:
            truth, prediction = row.get("truth"), row.get(prediction_key)
            if truth in matrix and prediction in matrix[truth]:
                matrix[truth][prediction] += 1
        per_label = {}
        f1s = []
        for label in labels:
            support = sum(row.get("truth") == label for row in rows)
            predicted = sum(row.get(prediction_key) == label for row in rows)
            true_positive = sum(
                row.get("truth") == label and row.get(prediction_key) == label
                for row in rows)
            precision = ratio(true_positive, predicted) or 0.0
            recall = ratio(true_positive, support) or 0.0
            f1 = (2 * precision * recall / (precision + recall)
                  if precision + recall else 0.0)
            low, high = wilson(true_positive, support)
            per_label[label] = {
                "name": BRANCH_NAMES.get(label, label), "support": support,
                "predicted": predicted, "correct": true_positive,
                "precision": precision, "recall": recall, "f1": f1,
                "recall_ci95": [low, high],
            }
            f1s.append(f1)
        correct = sum(bool(row.get(correct_key)) for row in rows)
        low, high = wilson(correct, len(rows))
        confusions = Counter(
            (row.get("truth"), row.get(prediction_key)) for row in rows
            if row.get("truth") in labels and row.get(prediction_key) in labels
            and row.get("truth") != row.get(prediction_key))
        return {
            "total": len(rows), "correct": correct,
            "accuracy": ratio(correct, len(rows)),
            "accuracy_ci95": [low, high],
            "macro_f1": sum(f1s) / len(f1s) if f1s else None,
            "valid_labels": sum(row.get(prediction_key) in labels for row in rows),
            "per_label": per_label, "confusion_matrix": matrix,
            "top_confusions": [
                {"truth": truth, "prediction": prediction, "count": count}
                for (truth, prediction), count in sorted(
                    confusions.items(), key=lambda item: (-item[1], item[0]))
            ],
        }

    final = classification("prediction", "correct")
    initial = classification("m1_prediction", "m1_correct")
    m3_rows = [row for row in rows if row.get("m3_used")]
    tag_counts = Counter(tag for row in m3_rows for tag in (row.get("m3_tags") or []))
    corrected = sum(bool(row.get("m3_corrected")) for row in m3_rows)
    worsened = sum(bool(row.get("m3_worsened")) for row in m3_rows)
    m3_initial_correct = sum(bool(row.get("m1_correct")) for row in m3_rows)
    m3_final_correct = sum(bool(row.get("correct")) for row in m3_rows)
    transitions = Counter(
        (row.get("m1_prediction") or "invalid", row.get("prediction") or "invalid")
        for row in m3_rows if row.get("m1_prediction") != row.get("prediction"))

    per_label = {}
    for label in labels:
        subset = [row for row in rows if row.get("truth") == label]
        m1_correct = sum(bool(row.get("m1_correct")) for row in subset)
        final_correct = sum(bool(row.get("correct")) for row in subset)
        used = sum(bool(row.get("m3_used")) for row in subset)
        per_label[label] = {
            "name": BRANCH_NAMES.get(label, label), "support": len(subset),
            "m1_correct": m1_correct,
            "m1_accuracy": ratio(m1_correct, len(subset)),
            "final_correct": final_correct,
            "final_accuracy": ratio(final_correct, len(subset)),
            "delta_correct": final_correct - m1_correct,
            "delta_accuracy": ratio(final_correct - m1_correct, len(subset)),
            "m3_used": used, "m3_rate": ratio(used, len(subset)),
            "m3_corrected": sum(bool(row.get("m3_corrected")) for row in subset),
            "m3_worsened": sum(bool(row.get("m3_worsened")) for row in subset),
        }

    def slice_summary(subset):
        total = len(subset)
        m1_correct = sum(bool(row.get("m1_correct")) for row in subset)
        final_correct = sum(bool(row.get("correct")) for row in subset)
        failures = sum(bool(row.get("exception_type")) or not row.get("route_ok")
                       for row in subset)
        return {
            "total": total, "m1_correct": m1_correct,
            "m1_accuracy": ratio(m1_correct, total),
            "final_correct": final_correct,
            "final_accuracy": ratio(final_correct, total),
            "delta_correct": final_correct - m1_correct,
            "m3_used": sum(bool(row.get("m3_used")) for row in subset),
            "m3_corrected": sum(bool(row.get("m3_corrected")) for row in subset),
            "m3_worsened": sum(bool(row.get("m3_worsened")) for row in subset),
            "route_failures": failures,
        }

    def grouped(key_func):
        groups = defaultdict(list)
        for row in rows:
            groups[str(key_func(row))].append(row)
        return {key: slice_summary(groups[key]) for key in sorted(groups)}

    def latency_summary(values):
        values = [float(value) for value in values if isinstance(value, (int, float))]
        return {
            "count": len(values),
            "average": sum(values) / len(values) if values else None,
            "p50": percentile(values, .50), "p95": percentile(values, .95),
            "p99": percentile(values, .99), "max": max(values) if values else None,
        }

    call_tiers = Counter()
    for row in rows:
        for call in row.get("model_calls") or []:
            call_tiers[call.get("model_tier") or "unknown"] += 1
    call_total = sum(int(row.get("model_call_count") or 0) for row in rows)
    failures = sum(bool(row.get("exception_type")) or not row.get("route_ok")
                   for row in rows)
    return {
        "labels": list(labels),
        "branch_names": {label: BRANCH_NAMES.get(label, label) for label in labels},
        "final": final, "m1_initial": initial,
        "m3": {
            "used": len(m3_rows), "handoff_rate": ratio(len(m3_rows), len(rows)),
            "initial_correct": m3_initial_correct,
            "initial_accuracy": ratio(m3_initial_correct, len(m3_rows)),
            "final_correct": m3_final_correct,
            "final_accuracy": ratio(m3_final_correct, len(m3_rows)),
            "corrected": corrected, "worsened": worsened,
            "net_correct_delta": m3_final_correct - m3_initial_correct,
            "changed": sum(bool(row.get("m3_changed")) for row in m3_rows),
            "unchanged": sum(not row.get("m3_changed") for row in m3_rows),
            "tag_counts": dict(sorted(tag_counts.items())),
            "transitions": [
                {"from": source, "to": target, "count": count}
                for (source, target), count in sorted(
                    transitions.items(), key=lambda item: (-item[1], item[0]))
            ],
        },
        "per_label": per_label,
        "strata": {
            "asr_noise": grouped(lambda row: str(bool(row.get("asr_noise"))).lower()),
            "rounds": grouped(lambda row: row.get("rounds_bucket") or "unknown"),
            "hard_pair_presence": grouped(
                lambda row: "true" if row.get("hard_pair") else "false"),
            "hard_pair": grouped(lambda row: row.get("hard_pair") or "none"),
        },
        "stability": {
            "route_success": len(rows) - failures, "route_failures": failures,
            "route_failure_rate": ratio(failures, len(rows)),
            "invalid_final_labels": sum(row.get("prediction") not in labels for row in rows),
        },
        "calls": {"total": call_total, "by_tier": dict(sorted(call_tiers.items()))},
        "latency_ms": {
            "wall": latency_summary(row.get("wall_latency_ms") for row in rows),
            "m1": latency_summary(row.get("m1_latency_ms") for row in rows),
            "m3": latency_summary(row.get("m3_latency_ms") for row in m3_rows),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--labels", default="abcdefghijklm")
    args = parser.parse_args()
    rows = [json.loads(line) for line in
            args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    summary = build_full_summary(rows, labels=tuple(args.labels))
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print(json.dumps({
        "total": summary["final"]["total"],
        "m1_accuracy": summary["m1_initial"]["accuracy"],
        "final_accuracy": summary["final"]["accuracy"],
        "m3_used": summary["m3"]["used"],
        "m3_corrected": summary["m3"]["corrected"],
        "m3_worsened": summary["m3"]["worsened"],
        "route_failures": summary["stability"]["route_failures"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
