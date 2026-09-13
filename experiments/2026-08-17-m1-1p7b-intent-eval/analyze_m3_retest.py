# -*- coding: utf-8 -*-
"""Compare the 2026-08-18 M3 retest with the 2026-08-17 baseline."""
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(r"D:\Codex-chat\2026-08-17-m1-1p7b-intent-eval")
OLD_PATH = ROOT / "results-m1-m3-current-1300.jsonl"
NEW_PATH = ROOT / "results-m1-m3-newm3-current-1300-20260818.jsonl"
BRANCH_NAMES = {
    "a": "新建提醒", "b": "修改提醒", "c": "查询提醒",
    "d": "写入记忆", "e": "查询记忆", "f": "音量调节",
    "g": "亮度调节", "h": "天气查询", "i": "时间查询",
    "j": "产品知识", "k": "晚安", "l": "再见", "m": "闲聊",
}


def load(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def pct(numerator, denominator):
    return round(100 * numerator / denominator, 4) if denominator else None


def metrics(rows):
    attempts = [row for row in rows if not row.get("m1_direct")]
    successful_m3 = [row for row in rows if row.get("m3_used")]
    failures = [row for row in rows if not row.get("route_ok")]
    final_errors = [row for row in rows if not row.get("correct")]
    direct_errors = [
        row for row in final_errors
        if row.get("m1_direct") and row.get("route_ok")
    ]
    m3_introduced = [
        row for row in final_errors
        if row.get("m3_used") and row.get("m1_correct")
    ]
    m3_unresolved = [
        row for row in final_errors
        if row.get("m3_used") and not row.get("m1_correct")
    ]
    failure_initial_correct = [row for row in failures if row.get("m1_correct")]
    failure_initial_wrong = [row for row in failures if not row.get("m1_correct")]
    result = {
        "total": len(rows),
        "m1_correct": sum(bool(row.get("m1_correct")) for row in rows),
        "m1_wrong": sum(not row.get("m1_correct") for row in rows),
        "final_correct": sum(bool(row.get("correct")) for row in rows),
        "final_errors": len(final_errors),
        "final_accuracy": pct(sum(bool(row.get("correct")) for row in rows), len(rows)),
        "m3_attempts": len(attempts),
        "m3_successful_returns": len(successful_m3),
        "m3_route_failures": len(failures),
        "m3_corrected": sum(bool(row.get("m3_corrected")) for row in rows),
        "m3_worsened": sum(bool(row.get("m3_worsened")) for row in rows),
        "successful_m3_initial_correct": sum(bool(row.get("m1_correct")) for row in successful_m3),
        "successful_m3_final_correct": sum(bool(row.get("correct")) for row in successful_m3),
        "direct_errors": len(direct_errors),
        "m3_introduced_errors": len(m3_introduced),
        "m3_unresolved_errors": len(m3_unresolved),
        "failure_initial_correct": len(failure_initial_correct),
        "failure_initial_wrong": len(failure_initial_wrong),
        "failure_only_1p7b_call": sum(
            row.get("model_call_count") == 1
            and all(call.get("model_tier") == "1.7b" for call in row.get("model_calls") or [])
            for row in failures
        ),
    }
    assert (
        result["direct_errors"]
        + result["m3_introduced_errors"]
        + result["m3_unresolved_errors"]
        + result["m3_route_failures"]
        == result["final_errors"]
    ), result
    return result


def grouped_attempts(rows, key_func):
    grouped = defaultdict(list)
    for row in rows:
        grouped[str(key_func(row))].append(row)
    output = {}
    for key in sorted(grouped):
        subset = grouped[key]
        attempts = [row for row in subset if not row.get("m1_direct")]
        failures = [row for row in attempts if not row.get("route_ok")]
        output[key] = {
            "total": len(subset),
            "attempts": len(attempts),
            "successful_returns": sum(bool(row.get("m3_used")) for row in attempts),
            "route_failures": len(failures),
            "failure_rate_among_attempts": pct(len(failures), len(attempts)),
        }
    return output


def main():
    old_rows = load(OLD_PATH)
    new_rows = load(NEW_PATH)
    assert len(old_rows) == len(new_rows) == 1300
    old_by_id = {row["sample_id"]: row for row in old_rows}
    new_by_id = {row["sample_id"]: row for row in new_rows}
    assert len(old_by_id) == len(new_by_id) == 1300
    assert old_by_id.keys() == new_by_id.keys()

    old_metrics = metrics(old_rows)
    new_metrics = metrics(new_rows)
    assert old_metrics["final_errors"] == 128
    assert new_metrics["final_errors"] == 272
    assert new_metrics["m3_attempts"] == 287
    assert new_metrics["m3_successful_returns"] + new_metrics["m3_route_failures"] == 287

    migration = Counter()
    fixed_by_truth = Counter()
    regressed_by_truth = Counter()
    for sample_id, old in old_by_id.items():
        new = new_by_id[sample_id]
        if old.get("correct") and new.get("correct"):
            key = "both_correct"
        elif not old.get("correct") and new.get("correct"):
            key = "fixed"
            fixed_by_truth[new["truth"]] += 1
        elif old.get("correct") and not new.get("correct"):
            key = "regressed"
            regressed_by_truth[new["truth"]] += 1
        else:
            key = "both_wrong"
        migration[key] += 1
    assert sum(migration.values()) == 1300
    assert migration["regressed"] - migration["fixed"] == 144

    per_branch = []
    for label in BRANCH_NAMES:
        old_subset = [row for row in old_rows if row.get("truth") == label]
        new_subset = [row for row in new_rows if row.get("truth") == label]
        per_branch.append({
            "label": label,
            "name": BRANCH_NAMES[label],
            "support": len(new_subset),
            "old_correct": sum(bool(row.get("correct")) for row in old_subset),
            "new_correct": sum(bool(row.get("correct")) for row in new_subset),
            "delta_correct": (
                sum(bool(row.get("correct")) for row in new_subset)
                - sum(bool(row.get("correct")) for row in old_subset)
            ),
            "new_m3_attempts": sum(not row.get("m1_direct") for row in new_subset),
            "new_m3_successful": sum(bool(row.get("m3_used")) for row in new_subset),
            "new_route_failures": sum(not row.get("route_ok") for row in new_subset),
            "new_m3_corrected": sum(bool(row.get("m3_corrected")) for row in new_subset),
            "new_m3_worsened": sum(bool(row.get("m3_worsened")) for row in new_subset),
            "fixed": fixed_by_truth[label],
            "regressed": regressed_by_truth[label],
        })

    tags = Counter(
        tag for row in new_rows for tag in (row.get("m3_tags") or [])
    )
    old_error_new_status = Counter()
    for row in old_rows:
        if row.get("correct"):
            continue
        new = new_by_id[row["sample_id"]]
        if new.get("correct"):
            old_error_new_status["fixed"] += 1
        elif not new.get("route_ok"):
            old_error_new_status["now_route_failure"] += 1
        elif new.get("m1_direct"):
            old_error_new_status["still_direct_wrong"] += 1
        elif new.get("m3_used") and new.get("m1_correct"):
            old_error_new_status["still_wrong_m3_introduced"] += 1
        elif new.get("m3_used"):
            old_error_new_status["still_wrong_m3_unresolved"] += 1
        else:
            old_error_new_status["still_wrong_other"] += 1

    output = {
        "old": old_metrics,
        "new": new_metrics,
        "delta": {
            "final_correct": new_metrics["final_correct"] - old_metrics["final_correct"],
            "final_errors": new_metrics["final_errors"] - old_metrics["final_errors"],
            "accuracy_percentage_points": round(
                new_metrics["final_accuracy"] - old_metrics["final_accuracy"], 4
            ),
            "m3_corrected": new_metrics["m3_corrected"] - old_metrics["m3_corrected"],
            "m3_worsened": new_metrics["m3_worsened"] - old_metrics["m3_worsened"],
        },
        "migration": dict(migration),
        "old_error_new_status": dict(old_error_new_status),
        "per_branch": per_branch,
        "new_attempts_by_rounds": grouped_attempts(
            new_rows, lambda row: row.get("rounds_bucket") or "unknown"
        ),
        "new_attempts_by_asr_noise": grouped_attempts(
            new_rows, lambda row: bool(row.get("asr_noise"))
        ),
        "new_m3_tags": dict(tags),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
