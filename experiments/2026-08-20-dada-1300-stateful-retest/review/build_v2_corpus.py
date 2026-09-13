# -*- coding: utf-8 -*-
"""Apply audited revisions to the corrected 1300-row corpus without touching raw files."""
import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path


ALLOWED = {"model_error_keep", "label_fix", "text_rewrite", "label_and_text_fix"}


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_decisions(source, results, decisions):
    by_id = {row["sample_id"]: row for row in source}
    if len(by_id) != len(source):
        raise ValueError("source sample_id is not unique")
    failures = {row["sample_id"] for row in results if not row.get("correct")}
    decision_ids = [item["sample_id"] for item in decisions]
    if len(set(decision_ids)) != len(decision_ids):
        raise ValueError("duplicate decision sample_id")
    if set(decision_ids) != failures:
        raise ValueError(f"decision/failure mismatch missing={sorted(failures-set(decision_ids))} extra={sorted(set(decision_ids)-failures)}")
    label_changes = text_changes = kept = 0
    for item in decisions:
        row = by_id[item["sample_id"]]
        if item.get("disposition") not in ALLOWED:
            raise ValueError(f"invalid disposition: {item}")
        if row["label"] != item.get("before_label") or row["text"] != item.get("before_text"):
            raise ValueError(f"before-state mismatch: {item['sample_id']}")
        changes_label = "new_label" in item
        changes_text = "new_text" in item
        if changes_label:
            if item["new_label"] not in set("abcdefghijklm") or item["new_label"] == row["label"]:
                raise ValueError(f"invalid new label: {item['sample_id']}")
            label_changes += 1
        if changes_text:
            if not isinstance(item["new_text"], str) or not item["new_text"].strip() or item["new_text"] == row["text"]:
                raise ValueError(f"invalid new text: {item['sample_id']}")
            text_changes += 1
        expected = {
            "model_error_keep": (False, False),
            "label_fix": (True, False),
            "text_rewrite": (False, True),
            "label_and_text_fix": (True, True),
        }[item["disposition"]]
        if (changes_label, changes_text) != expected:
            raise ValueError(f"disposition/change mismatch: {item['sample_id']}")
        if item["disposition"] == "model_error_keep":
            kept += 1
        if not item.get("rationale") or not item.get("production_guide"):
            raise ValueError(f"missing audit rationale: {item['sample_id']}")
    return {
        "reviewed_failures": len(decisions),
        "label_changes": label_changes,
        "text_changes": text_changes,
        "semantic_changes": sum(item["disposition"] != "model_error_keep" for item in decisions),
        "model_error_kept": kept,
    }


def _stratum(row):
    return (
        f"noise={'true' if row.get('asr_noise') else 'false'}|"
        f"rounds={row.get('rounds_bucket', row.get('rounds'))}|"
        f"hard={'true' if bool(row.get('hard_pair')) else 'false'}"
    )


def build(input_path, results_path, decisions_path, output_path, audit_path):
    source = load_jsonl(input_path)
    results = load_jsonl(results_path)
    decisions = json.loads(Path(decisions_path).read_text(encoding="utf-8"))
    stats = validate_decisions(source, results, decisions)
    by_decision = {item["sample_id"]: item for item in decisions}
    result_by_id = {row["sample_id"]: row for row in results}
    revised = []
    changes = []
    for original in source:
        row = copy.deepcopy(original)
        item = by_decision.get(row["sample_id"])
        if item:
            previous_label, previous_text = row["label"], row["text"]
            previous_asr = bool(row.get("asr_noise"))
            if "new_label" in item:
                row["label"] = item["new_label"]
            if "new_text" in item:
                row["text"] = item["new_text"]
                row["asr_noise"] = bool(item.get("new_asr_noise", False))
            row["stratum"] = _stratum(row)
            row["audit_v2"] = {
                "review_date": "2026-08-20",
                "review_scope": "previous_full_route_34_failures",
                "disposition": item["disposition"],
                "previous_label": previous_label,
                "previous_text": previous_text,
                "previous_asr_noise": previous_asr,
                "label_revised": row["label"] != previous_label,
                "text_rewritten": row["text"] != previous_text,
                "rationale": item["rationale"],
                "production_guide": item["production_guide"],
                "previous_final_prediction": result_by_id[row["sample_id"]].get("prediction"),
                "previous_m3_used": bool(result_by_id[row["sample_id"]].get("m3_used")),
            }
            changes.append({
                "sample_id": row["sample_id"],
                "disposition": item["disposition"],
                "before_label": previous_label,
                "after_label": row["label"],
                "before_text": previous_text,
                "after_text": row["text"],
                "rationale": item["rationale"],
            })
        revised.append(row)

    output_path, audit_path = Path(output_path), Path(audit_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in revised),
        encoding="utf-8",
    )
    unresolved = [item["sample_id"] for item in decisions if item["disposition"] not in ALLOWED]
    audit = {
        **stats,
        "unresolved": unresolved,
        "input_rows": len(source),
        "output_rows": len(revised),
        "input_sha256": file_sha256(input_path),
        "output_sha256": file_sha256(output_path),
        "label_distribution_before": dict(sorted(Counter(row["label"] for row in source).items())),
        "label_distribution_after": dict(sorted(Counter(row["label"] for row in revised).items())),
        "changes": changes,
    }
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--previous-results", required=True, type=Path)
    parser.add_argument("--decisions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    args = parser.parse_args()
    audit = build(args.input, args.previous_results, args.decisions, args.output, args.audit)
    print(json.dumps({key: audit[key] for key in (
        "reviewed_failures", "label_changes", "text_changes", "semantic_changes",
        "model_error_kept", "output_rows", "output_sha256")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
