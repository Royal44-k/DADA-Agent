"""Offline archive verification; never imports production Agent modules."""
from __future__ import annotations

import ast
import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def check(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    manifest = json.loads((ROOT / "ASSET_MANIFEST.json").read_text(encoding="utf-8"))
    check(manifest["source_assets"] == 132, "Expected 132 source assets")
    counts = Counter()
    for entry in manifest["files"]:
        path = ROOT / entry["path"]
        data = path.read_bytes()
        check(len(data) == entry["bytes"], f"Length mismatch: {entry['path']}")
        check(hashlib.sha256(data).hexdigest() == entry["sha256"], f"SHA256 mismatch: {entry['path']}")
        counts[path.suffix] += 1
        if path.suffix == ".py":
            ast.parse(data.decode("utf-8-sig"), filename=entry["path"])
        elif path.suffix == ".json":
            json.loads(data.decode("utf-8-sig"))
        elif path.suffix == ".jsonl":
            read_rows(path)
    sums = ROOT / "SHA256SUMS.txt"
    if sums.exists():
        for line in sums.read_text(encoding="utf-8").splitlines():
            expected, relative = line.split("  ", 1)
            check(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, f"Archive checksum mismatch: {relative}")

    m1 = ROOT / "experiments/2026-08-17-m1-1p7b-intent-eval"
    expected_runs = {
        "results-m1-m3-current-1300.jsonl": 1172,
        "results-m1-m3-newm3-current-1300-20260818.jsonl": 1028,
        "results-m1-m3-rerun2-1300-20260818.jsonl": 1191,
    }
    sample_ids = {row["sample_id"] for row in read_rows(m1 / "sample-1300.jsonl")}
    for filename, expected in expected_runs.items():
        rows = read_rows(m1 / filename)
        check(len(rows) == 1300 and len({r["sample_id"] for r in rows}) == 1300, f"Run rows/unique IDs: {filename}")
        check({r["sample_id"] for r in rows} == sample_ids, f"Sample IDs differ: {filename}")
        check(sum(bool(r["correct"]) for r in rows) == expected, f"Run count: {filename}")
    rows = read_rows(m1 / "results-m1-m3-rerun2-1300-20260818.jsonl")
    check(sum(bool(r["m3_used"]) for r in rows) == 285, "M3 attempts mismatch")
    check(sum(bool(r["m3_corrected"]) for r in rows) == 8, "M3 corrected mismatch")
    check(sum(bool(r["m3_worsened"]) for r in rows) == 74, "M3 worsened mismatch")
    check(all(r["route_ok"] for r in rows), "Unexpected route failure in August 18 rerun")

    stateful = ROOT / "experiments/2026-08-20-dada-1300-stateful-retest"
    for filename, correct in [("results-full-v2-1300.jsonl", 1278), ("results-full-v2-1300-final.jsonl", 1280)]:
        records = read_rows(stateful / "artifacts_v2" / filename)
        check(len(records) == 1300 and sum(bool(r["correct"]) for r in records) == correct, f"Stateful count: {filename}")
    retry = json.loads((stateful / "artifacts_v2/infra-retry-audit-v2.json").read_text(encoding="utf-8"))
    check(retry["retried"] == 2 and retry["recovered"] == 2 and retry["ordinary_classification_errors_retried"] == 0, "Retry policy mismatch")
    exported = []
    for label in "abcdefghijklm":
        records = read_rows(ROOT / f"datasets/corrected-v3-1300/{label}.jsonl")
        check(all(r["label"] == label for r in records), f"Wrong exported label: {label}")
        exported.extend(records)
    check(len(exported) == 1300, "Export size mismatch")
    audited = read_rows(stateful / "sample-1300-corrected-v3-2026-08-20.jsonl")
    check(Counter(r["label"] for r in exported) == Counter(r["label"] for r in audited), "v3 label distribution mismatch")
    log = (ROOT / "experiments/2026-08-15-fg-typed-magnitude/typed-full-v3.log").read_text(encoding="utf-8")
    result = json.loads(next(line[8:] for line in reversed(log.splitlines()) if line.startswith("SUMMARY ")))
    check(result["calls"] == 456 and result["all_pass"] == 455, "FG results mismatch")
    archive = ROOT / "downloads/DADA-Agent-assets-2026-09-13.zip"
    if archive.exists():
        expected_zip = (ROOT / "downloads/SHA256SUMS.txt").read_text(encoding="utf-8").split()[0]
        check(hashlib.sha256(archive.read_bytes()).hexdigest() == expected_zip, "ZIP SHA256 mismatch")
        with zipfile.ZipFile(archive) as packed:
            check(packed.testzip() is None, "ZIP CRC failure")
    print(json.dumps({"status": "PASS", "source_assets": manifest["source_assets"], "extensions": dict(counts), "same_label_run_correct": expected_runs, "stateful_v2_after_retry": "1280/1300", "fg_core_pass": "455/456", "export_rows": len(exported)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
