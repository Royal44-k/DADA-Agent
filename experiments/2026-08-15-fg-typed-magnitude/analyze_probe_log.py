# -*- coding: utf-8 -*-
"""汇总typed_magnitude_probe逐条日志中的失败模式。"""
import json
import sys
from collections import Counter, defaultdict


def main(path):
    rows = []
    boundary = []
    summary = None
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line.startswith("SUMMARY "):
                summary = json.loads(line[len("SUMMARY "):])
            elif line.startswith("BOUNDARY "):
                boundary.append(json.loads(line[len("BOUNDARY "):]))
            elif line.startswith("{"):
                rows.append(json.loads(line))

    print("SUMMARY", json.dumps(summary, ensure_ascii=False))
    failures = [row for row in rows if not row["all_ok"]]
    print("FAILURES", len(failures))
    value_confusion = Counter(
        (str(row["magnitude_value"]), str(row["actual_magnitude_value"]))
        for row in failures if not row["value_ok"])
    print("VALUE_CONFUSION", json.dumps(
        [[list(key), count] for key, count in value_confusion.items()],
        ensure_ascii=False))
    direction_confusion = Counter(
        (row["direction"], row["actual_direction"])
        for row in failures if not row["direction_ok"])
    print("DIRECTION_CONFUSION", json.dumps(
        [[list(key), count] for key, count in direction_confusion.items()],
        ensure_ascii=False))
    print("ERRORS", json.dumps(Counter(row["error"] for row in failures),
                                ensure_ascii=False))
    by_case = defaultdict(list)
    for row in failures:
        by_case[row["case_id"]].append(row)
    for case_id, sample in by_case.items():
        first = sample[0]
        outputs = Counter((row["actual_direction"], row["actual_magnitude_type"],
                           str(row["actual_magnitude_value"]), row["error"])
                          for row in sample)
        print("FAILED_CASE " + json.dumps({
            "case_id": case_id, "group": first["group"], "text": first["text"],
            "expected": [first["direction"], first["magnitude_type"],
                         first["magnitude_value"]],
            "failed_repeats": len(sample),
            "outputs": [[list(key), count] for key, count in outputs.items()],
        }, ensure_ascii=False))
    for row in boundary:
        if row["tool_called"]:
            print("BOUNDARY_CALLED " + json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
