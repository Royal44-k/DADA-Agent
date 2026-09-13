# -*- coding: utf-8 -*-
"""Apply the five user-directed v3 label decisions and calculate a fixed-output forecast."""
import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path


REQUESTED_LABELS = {
    "b-02115-0da3b1f6b6c8": "m",
    "d-00495-19fb7f0c478d": "m",
    "j-02646-702c3d39553b": "a",
    "l-01230-623efe9e456c": "m",
    "m-01365-0db281149dbf": "l",
}


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(input_path, results_path, output_path, audit_path):
    source = load_jsonl(input_path)
    results = load_jsonl(results_path)
    source_by_id = {row["sample_id"]: row for row in source}
    result_by_id = {row["sample_id"]: row for row in results}
    if len(source) != 1300 or len(source_by_id) != 1300:
        raise ValueError("input corpus must contain 1300 unique sample IDs")
    if set(REQUESTED_LABELS) - set(source_by_id):
        raise ValueError(f"requested IDs missing: {sorted(set(REQUESTED_LABELS)-set(source_by_id))}")
    if set(source_by_id) != set(result_by_id):
        raise ValueError("result IDs do not match corpus IDs")

    revised = []
    changes = []
    actual_changes = confirmations = 0
    for original in source:
        row = copy.deepcopy(original)
        requested = REQUESTED_LABELS.get(row["sample_id"])
        if requested is not None:
            before = row["label"]
            changed = before != requested
            if changed:
                actual_changes += 1
            else:
                confirmations += 1
            row["label"] = requested
            row["audit_v3"] = {
                "review_date": "2026-08-20",
                "source": "user_directed_label_revision",
                "previous_label": before,
                "requested_label": requested,
                "label_revised": changed,
                "text_rewritten": False,
            }
            changes.append({
                "sample_id": row["sample_id"],
                "before_label": before,
                "after_label": requested,
                "changed": changed,
                "text": row["text"],
                "previous_prediction": result_by_id[row["sample_id"]].get("prediction"),
            })
        revised.append(row)

    new_truth = {row["sample_id"]: row["label"] for row in revised}
    before_correct_ids = {row["sample_id"] for row in results if row.get("correct")}
    after_correct_ids = {
        row["sample_id"] for row in results
        if row.get("route_ok") and row.get("prediction") == new_truth[row["sample_id"]]
    }
    theory = {
        "assumption": "reuse v2 model outputs; change ground-truth labels only",
        "total": len(results),
        "before_correct": len(before_correct_ids),
        "before_accuracy": len(before_correct_ids) / len(results),
        "after_correct": len(after_correct_ids),
        "after_accuracy": len(after_correct_ids) / len(results),
        "newly_correct": len(after_correct_ids - before_correct_ids),
        "newly_wrong": len(before_correct_ids - after_correct_ids),
        "newly_correct_ids": sorted(after_correct_ids - before_correct_ids),
        "newly_wrong_ids": sorted(before_correct_ids - after_correct_ids),
    }

    output_path, audit_path = Path(output_path), Path(audit_path)
    output_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in revised),
        encoding="utf-8",
    )
    audit = {
        "requested_decisions": len(REQUESTED_LABELS),
        "actual_label_changes": actual_changes,
        "already_matching_confirmations": confirmations,
        "text_changes": 0,
        "input_rows": len(source),
        "output_rows": len(revised),
        "input_sha256": sha256(input_path),
        "output_sha256": sha256(output_path),
        "label_distribution_before": dict(sorted(Counter(row["label"] for row in source).items())),
        "label_distribution_after": dict(sorted(Counter(row["label"] for row in revised).items())),
        "changes": changes,
        "fixed_output_counterfactual": theory,
    }
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    args = parser.parse_args()
    audit = build(args.input, args.results, args.output, args.audit)
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
