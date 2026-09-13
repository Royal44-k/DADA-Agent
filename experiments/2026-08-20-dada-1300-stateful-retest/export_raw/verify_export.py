import hashlib
import json
from collections import Counter
from pathlib import Path


SOURCE = Path(r"D:\Codex-chat\2026-08-20-dada-1300-stateful-retest\sample-1300-corrected-v3-2026-08-20.jsonl")
OUTPUT = Path(r"D:\Codex-chat\测试集-1300")
LABELS = tuple("abcdefghijklm")
FIELDS = ("label", "rounds", "ctx", "hard_pair", "history", "text", "asr_noise", "src")


def read_jsonl(path):
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith("\n"):
                raise AssertionError(f"{path.name}:{line_number} 缺少行尾换行")
            rows.append(json.loads(line))
    return rows


source_rows = read_jsonl(SOURCE)
actual_files = sorted(path.name for path in OUTPUT.iterdir() if path.is_file())
expected_files = [f"{label}.jsonl" for label in LABELS]
assert actual_files == expected_files, (actual_files, expected_files)

counts = Counter()
hashes = {}
for label in LABELS:
    path = OUTPUT / f"{label}.jsonl"
    rows = read_jsonl(path)
    expected = [
        {field: row[field] for field in FIELDS}
        for row in source_rows
        if row["label"] == label
    ]
    assert rows == expected, f"{label}.jsonl 与最终 v3 内容不一致"
    assert all(tuple(row) == FIELDS for row in rows), f"{label}.jsonl 字段或顺序不一致"
    assert all(row["label"] == label for row in rows), f"{label}.jsonl 存在错放标签"
    counts[label] = len(rows)
    hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()

assert len(source_rows) == 1300
assert sum(counts.values()) == 1300

print("VERIFY_OK")
print("files=13 total=1300 schema=raw-compatible content=matches-v3")
print("counts=" + " ".join(f"{label}:{counts[label]}" for label in LABELS))
for filename in expected_files:
    print(f"sha256 {filename} {hashes[filename]}")
