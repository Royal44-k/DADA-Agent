# -*- coding: utf-8 -*-
import json
from pathlib import Path

import pytest

from sample_builder import build_sample, write_sample


LABELS = "abcdefghijklm"


def _row(label, index, *, rounds=1, noise=False, hard_pair=None):
    history = []
    for turn in range(rounds - 1):
        history.extend([
            ["user", f"{label}-历史用户-{index}-{turn}"],
            ["assistant", f"{label}-历史助手-{index}-{turn}"],
        ])
    return {
        "label": label,
        "rounds": rounds,
        "ctx": None,
        "hard_pair": hard_pair,
        "history": history,
        "text": f"{label}-当前语句-{index}",
        "asr_noise": noise,
        "src": "gen",
    }


def _write_raw(raw_dir: Path, count_per_label=120):
    raw_dir.mkdir()
    for label in LABELS:
        rows = []
        for index in range(count_per_label):
            if index < 60:
                rows.append(_row(label, index, rounds=1, noise=False))
            elif index < 90:
                rows.append(_row(label, index, rounds=2, noise=False,
                                 hard_pair=f"{label}/m"))
            elif index < 110:
                rows.append(_row(label, index, rounds=3, noise=True))
            else:
                rows.append(_row(label, index, rounds=4, noise=True,
                                 hard_pair=f"{label}/m"))
        with (raw_dir / f"{label}.jsonl").open("w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_build_sample_is_balanced_stratified_and_reproducible(tmp_path):
    """Catches wrong quotas, unstable RNG, lost history, or missing traceability."""
    raw_dir = tmp_path / "raw"
    _write_raw(raw_dir)

    first = build_sample(raw_dir, per_label=100, seed=20260817)
    second = build_sample(raw_dir, per_label=100, seed=20260817)

    assert first == second
    assert len(first) == 1300
    assert len({row["sample_id"] for row in first}) == 1300
    for label in LABELS:
        selected = [row for row in first if row["label"] == label]
        assert len(selected) == 100
        strata = {}
        for row in selected:
            key = (row["asr_noise"], row["rounds_bucket"], bool(row["hard_pair"]))
            strata[key] = strata.get(key, 0) + 1
            assert row["source_file"] == f"{label}.jsonl"
            assert row["source_line"] >= 1
            assert row["history"] == _row(
                label, int(row["text"].rsplit("-", 1)[1]),
                rounds=row["rounds"], noise=row["asr_noise"],
                hard_pair=row["hard_pair"])["history"]
        assert strata == {
            (False, "1", False): 50,
            (False, "2", True): 25,
            (True, "3", False): 17,
            (True, "4+", True): 8,
        }


def test_build_sample_rejects_label_that_disagrees_with_file(tmp_path):
    """Catches silently accepting a wrong ground-truth source file."""
    raw_dir = tmp_path / "raw"
    _write_raw(raw_dir, count_per_label=12)
    path = raw_dir / "f.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[3]["label"] = "g"
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                            for row in rows), encoding="utf-8")

    with pytest.raises(ValueError, match="f.jsonl.*第4行.*label"):
        build_sample(raw_dir, per_label=10, seed=1)


def test_build_sample_deduplicates_identical_json_records(tmp_path):
    """Catches an exact duplicate consuming two evaluation slots."""
    raw_dir = tmp_path / "raw"
    _write_raw(raw_dir, count_per_label=12)
    for label in LABELS:
        path = raw_dir / f"{label}.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(lines + [lines[0]]) + "\n", encoding="utf-8")

    rows = build_sample(raw_dir, per_label=10, seed=9)
    fingerprints = {
        json.dumps({key: value for key, value in row.items()
                    if key not in {"source_file", "source_line", "sample_id",
                                   "rounds_bucket", "stratum"}},
                   ensure_ascii=False, sort_keys=True)
        for row in rows
    }
    assert len(fingerprints) == len(rows)


def test_write_sample_emits_jsonl_and_manifest(tmp_path):
    """Catches a manifest that cannot prove counts and seed."""
    raw_dir = tmp_path / "raw"
    _write_raw(raw_dir, count_per_label=12)
    rows = build_sample(raw_dir, per_label=10, seed=20260817)
    output = tmp_path / "sample.jsonl"
    manifest = tmp_path / "manifest.json"

    write_sample(rows, output, manifest, seed=20260817, per_label=10)

    written = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    meta = json.loads(manifest.read_text(encoding="utf-8"))
    assert written == rows
    assert meta["total"] == 130
    assert meta["seed"] == 20260817
    assert meta["per_label"] == 10
    assert meta["label_counts"] == {label: 10 for label in LABELS}
