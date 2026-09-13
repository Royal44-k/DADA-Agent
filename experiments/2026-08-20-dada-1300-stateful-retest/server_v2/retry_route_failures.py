# -*- coding: utf-8 -*-
"""Retry only infrastructure route failures once; never retry classification errors."""
import argparse
import json
from pathlib import Path


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path, rows):
    Path(path).write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def is_infra_failure(row):
    return bool(row.get("exception_type")) or not bool(row.get("route_ok"))


def select_retry_rows(source, initial_results):
    failure_ids = {row["sample_id"] for row in initial_results if is_infra_failure(row)}
    by_source = {row["sample_id"] for row in source}
    if not failure_ids <= by_source:
        raise ValueError(f"missing source IDs: {sorted(failure_ids - by_source)}")
    return [row for row in source if row["sample_id"] in failure_ids]


def merge_results(initial_results, retry_results):
    failure_ids = {row["sample_id"] for row in initial_results if is_infra_failure(row)}
    retry_ids = [row["sample_id"] for row in retry_results]
    if len(retry_ids) != len(set(retry_ids)) or set(retry_ids) != failure_ids:
        raise ValueError(
            f"retry IDs must equal infrastructure failure IDs; "
            f"expected={sorted(failure_ids)} actual={sorted(set(retry_ids))}"
        )
    retry_by_id = {row["sample_id"]: row for row in retry_results}
    merged = []
    recovered = 0
    for first in initial_results:
        if first["sample_id"] not in failure_ids:
            merged.append(first)
            continue
        second = dict(retry_by_id[first["sample_id"]])
        second["infra_retry"] = {
            "attempted": True,
            "policy": "route_ok_false_or_exception_only_once",
            "first_route_ok": bool(first.get("route_ok")),
            "first_exception_type": first.get("exception_type"),
            "first_exception_message": first.get("exception_message"),
            "first_prediction": first.get("prediction"),
            "first_wall_latency_ms": first.get("wall_latency_ms"),
            "retry_route_ok": bool(second.get("route_ok")),
            "retry_exception_type": second.get("exception_type"),
        }
        if not is_infra_failure(second):
            recovered += 1
        merged.append(second)
    audit = {
        "policy": "only infrastructure route failures are retried exactly once",
        "initial_rows": len(initial_results),
        "retried": len(failure_ids),
        "recovered": recovered,
        "still_failed": len(failure_ids) - recovered,
        "retry_sample_ids": sorted(failure_ids),
        "ordinary_classification_errors_retried": 0,
    }
    return merged, audit


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    select = sub.add_parser("select")
    select.add_argument("--source", required=True, type=Path)
    select.add_argument("--initial-results", required=True, type=Path)
    select.add_argument("--retry-input", required=True, type=Path)
    merge = sub.add_parser("merge")
    merge.add_argument("--initial-results", required=True, type=Path)
    merge.add_argument("--retry-results", required=True, type=Path)
    merge.add_argument("--output", required=True, type=Path)
    merge.add_argument("--audit", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "select":
        rows = select_retry_rows(load_jsonl(args.source), load_jsonl(args.initial_results))
        write_jsonl(args.retry_input, rows)
        print(json.dumps({"retry_count": len(rows),
                          "sample_ids": [row["sample_id"] for row in rows]}, ensure_ascii=False))
    else:
        rows, audit = merge_results(load_jsonl(args.initial_results), load_jsonl(args.retry_results))
        write_jsonl(args.output, rows)
        args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
