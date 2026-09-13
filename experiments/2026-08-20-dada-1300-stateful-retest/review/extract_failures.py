# -*- coding: utf-8 -*-
"""Print complete evidence for each final routing failure."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.results.read_text(encoding="utf-8").splitlines() if line.strip()]
    failures = [row for row in rows if not row.get("correct")]
    print(f"failures={len(failures)}")
    for index, row in enumerate(failures, 1):
        print(
            f"\n[{index:02d}] {row['sample_id']} "
            f"src={row.get('source_file')}:{row.get('source_line')} "
            f"truth={row.get('truth')} m1={row.get('m1_prediction')} "
            f"final={row.get('prediction')} m3={row.get('m3_used')}\n"
            f"text={row.get('text')}\n"
            f"history={json.dumps(row.get('history'), ensure_ascii=False)}\n"
            f"src={row.get('src')}\n"
            f"tags={json.dumps(row.get('m3_tags'), ensure_ascii=False)}"
        )


if __name__ == "__main__":
    main()
