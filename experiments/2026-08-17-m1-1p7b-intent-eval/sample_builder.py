# -*- coding: utf-8 -*-
"""对 raw/a.jsonl～m.jsonl 做固定种子的比例分层抽样。"""
import argparse
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path


LABELS = "abcdefghijklm"


def rounds_bucket(value):
    value = int(value)
    return str(value) if value in (1, 2, 3) else "4+"


def stratum_key(row):
    return bool(row.get("asr_noise")), rounds_bucket(row.get("rounds", 1)), bool(row.get("hard_pair"))


def allocate_largest_remainder(counts, total):
    available = sum(counts.values())
    if total > available:
        raise ValueError(f"抽样数{total}超过可用唯一记录数{available}")
    if not counts:
        return {}
    exact = {key: counts[key] * total / available for key in counts}
    allocation = {key: min(counts[key], math.floor(exact[key])) for key in counts}

    if total >= len(counts):
        for key in counts:
            if allocation[key] == 0:
                allocation[key] = 1
    while sum(allocation.values()) > total:
        candidates = [key for key in counts if allocation[key] > 1]
        key = min(candidates, key=lambda item: (exact[item] - math.floor(exact[item]), str(item)))
        allocation[key] -= 1
    while sum(allocation.values()) < total:
        candidates = [key for key in counts if allocation[key] < counts[key]]
        key = max(candidates, key=lambda item: (exact[item] - allocation[item], str(item)))
        allocation[key] += 1
    return allocation


def _fingerprint(row):
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_sample(raw_dir, per_label=100, seed=20260817):
    raw_dir = Path(raw_dir)
    output = []
    for label in LABELS:
        path = raw_dir / f"{label}.jsonl"
        if not path.is_file():
            raise FileNotFoundError(path)
        unique = {}
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("label") != label:
                raise ValueError(f"{path.name}第{line_number}行label应为{label}，实际为{row.get('label')}")
            fingerprint = _fingerprint(row)
            if fingerprint in unique:
                continue
            enriched = dict(row)
            enriched["source_file"] = path.name
            enriched["source_line"] = line_number
            enriched["rounds_bucket"] = rounds_bucket(row.get("rounds", 1))
            key = stratum_key(row)
            enriched["stratum"] = (
                f"noise={str(key[0]).lower()}|rounds={key[1]}|hard={str(key[2]).lower()}")
            digest = hashlib.sha256(
                f"{path.name}:{line_number}:{fingerprint}".encode("utf-8")).hexdigest()[:12]
            enriched["sample_id"] = f"{label}-{line_number:05d}-{digest}"
            unique[fingerprint] = enriched

        strata = defaultdict(list)
        for row in unique.values():
            strata[stratum_key(row)].append(row)
        allocation = allocate_largest_remainder(
            {key: len(rows) for key, rows in strata.items()}, per_label)
        selected = []
        for key in sorted(strata, key=str):
            rows = list(strata[key])
            random.Random(f"{seed}:{label}:{key}").shuffle(rows)
            selected.extend(rows[:allocation[key]])
        random.Random(f"{seed}:{label}:final").shuffle(selected)
        output.extend(selected)
    return output


def write_sample(rows, output_jsonl, manifest_json, seed=20260817, per_label=100):
    output_jsonl = Path(output_jsonl)
    manifest_json = Path(manifest_json)
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with output_jsonl.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    label_counts = Counter(row["label"] for row in rows)
    stratum_counts = Counter(f"{row['label']}|{row['stratum']}" for row in rows)
    manifest = {
        "seed": seed,
        "per_label": per_label,
        "total": len(rows),
        "label_counts": {label: label_counts[label] for label in LABELS},
        "stratum_counts": dict(sorted(stratum_counts.items())),
        "sample_ids_sha256": hashlib.sha256(
            "\n".join(row["sample_id"] for row in rows).encode("utf-8")).hexdigest(),
    }
    manifest_json.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--per-label", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260817)
    args = parser.parse_args()
    rows = build_sample(args.raw_dir, args.per_label, args.seed)
    write_sample(rows, args.output, args.manifest, args.seed, args.per_label)
    print(json.dumps({"total": len(rows), "labels": dict(Counter(row["label"] for row in rows))},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
