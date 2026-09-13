# -*- coding: utf-8 -*-
"""Select the first corrected example of each a-m label, preserving label order."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    first = {}
    for line in args.input.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        first.setdefault(row["label"], row)
    expected = list("abcdefghijklm")
    missing = [label for label in expected if label not in first]
    if missing:
        raise ValueError(f"missing labels: {missing}")
    args.output.write_text(
        "".join(json.dumps(first[label], ensure_ascii=False) + "\n" for label in expected),
        encoding="utf-8",
    )
    print(json.dumps({"count": 13, "labels": expected}, ensure_ascii=False))


if __name__ == "__main__":
    main()
