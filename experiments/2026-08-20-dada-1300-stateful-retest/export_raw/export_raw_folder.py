import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Dict, List


LABELS = tuple("abcdefghijklm")
EXPORT_FIELDS = (
    "label",
    "rounds",
    "ctx",
    "hard_pair",
    "history",
    "text",
    "asr_noise",
    "src",
)


def _read_source(source: Path) -> List[dict]:
    rows = []
    sample_ids = set()

    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            missing = [field for field in EXPORT_FIELDS if field not in row]
            if missing:
                raise ValueError(f"第 {line_number} 行缺少字段：{missing}")
            if row["label"] not in LABELS:
                raise ValueError(f"第 {line_number} 行标签无效：{row['label']!r}")

            sample_id = row.get("sample_id")
            if sample_id is not None:
                if sample_id in sample_ids:
                    raise ValueError(f"sample_id 重复：{sample_id}")
                sample_ids.add(sample_id)
            rows.append(row)

    if len(rows) != 1300:
        raise ValueError(f"源测试集应为 1300 条，实际为 {len(rows)} 条")
    return rows


def export_raw_folder(source: Path, output: Path) -> Dict[str, object]:
    source = Path(source)
    output = Path(output)
    rows = _read_source(source)

    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"输出目录非空，拒绝覆盖：{output}")
    output.mkdir(parents=True, exist_ok=True)

    grouped = {label: [] for label in LABELS}
    for row in rows:
        grouped[row["label"]].append(
            {field: row[field] for field in EXPORT_FIELDS}
        )

    for label in LABELS:
        destination = output / f"{label}.jsonl"
        with destination.open("w", encoding="utf-8", newline="\n") as handle:
            for row in grouped[label]:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    counts = dict(Counter(row["label"] for row in rows))
    return {"total": len(rows), "counts": counts, "output": str(output)}


def main() -> None:
    parser = argparse.ArgumentParser(description="将最终修订测试集导出为 raw 兼容目录")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    summary = export_raw_folder(args.source, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
