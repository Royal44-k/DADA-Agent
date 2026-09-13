# -*- coding: utf-8 -*-
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import aggregate_full_router
import render_full_router_report
from aggregate_full_router import build_full_summary
from render_full_router_report import generate_full_report


def _rows():
    return [
        {
            "sample_id": "a1", "truth": "a",
            "m1_prediction": "a", "m1_correct": True, "m1_direct": True,
            "prediction": "a", "correct": True, "valid_label": True,
            "route_ok": True, "m3_used": False, "m3_tags": [],
            "m3_changed": False, "m3_corrected": False, "m3_worsened": False,
            "exception_type": None, "asr_noise": False, "rounds_bucket": "1",
            "hard_pair": None, "m1_latency_ms": 10, "m3_latency_ms": None,
            "wall_latency_ms": 12, "model_call_count": 1,
            "model_calls": [{"model_tier": "1.7b", "latency_ms": 10}],
            "text": "新建提醒",
        },
        {
            "sample_id": "a2", "truth": "a",
            "m1_prediction": "b", "m1_correct": False, "m1_direct": False,
            "prediction": "a", "correct": True, "valid_label": True,
            "route_ok": True, "m3_used": True,
            "m3_tags": ["m3", "m3_disputed"],
            "m3_changed": True, "m3_corrected": True, "m3_worsened": False,
            "exception_type": None, "asr_noise": True, "rounds_bucket": "2",
            "hard_pair": "a/b", "m1_latency_ms": 20, "m3_latency_ms": 80,
            "wall_latency_ms": 105, "model_call_count": 2,
            "model_calls": [
                {"model_tier": "1.7b", "latency_ms": 20},
                {"model_tier": "9b", "latency_ms": 80},
            ],
            "text": "提醒我",
        },
        {
            "sample_id": "b1", "truth": "b",
            "m1_prediction": "b", "m1_correct": True, "m1_direct": False,
            "prediction": "a", "correct": False, "valid_label": True,
            "route_ok": True, "m3_used": True,
            "m3_tags": ["m3", "m3_disputed", "m3_no_tool_retry"],
            "m3_changed": True, "m3_corrected": False, "m3_worsened": True,
            "exception_type": None, "asr_noise": False, "rounds_bucket": "3",
            "hard_pair": "a/b", "m1_latency_ms": 30, "m3_latency_ms": 120,
            "wall_latency_ms": 155, "model_call_count": 3,
            "model_calls": [
                {"model_tier": "1.7b", "latency_ms": 30},
                {"model_tier": "9b", "latency_ms": 50},
                {"model_tier": "9b", "latency_ms": 70},
            ],
            "text": "改提醒",
        },
        {
            "sample_id": "b2", "truth": "b",
            "m1_prediction": "a", "m1_correct": False, "m1_direct": False,
            "prediction": None, "correct": False, "valid_label": False,
            "route_ok": False, "m3_used": False, "m3_tags": [],
            "m3_changed": False, "m3_corrected": False, "m3_worsened": False,
            "exception_type": None, "asr_noise": True, "rounds_bucket": "4+",
            "hard_pair": None, "m1_latency_ms": 40, "m3_latency_ms": None,
            "wall_latency_ms": 45, "model_call_count": 1,
            "model_calls": [{"model_tier": "1.7b", "latency_ms": 40}],
            "text": "取消它",
        },
    ]


def test_build_full_summary_scores_final_and_initial_labels_separately():
    """Catches reporting M1 initial accuracy as complete-flow accuracy."""
    summary = build_full_summary(_rows(), labels=("a", "b"))
    assert summary["final"]["total"] == 4
    assert summary["final"]["correct"] == 2
    assert summary["final"]["accuracy"] == 0.5
    assert summary["m1_initial"]["correct"] == 2
    assert summary["m1_initial"]["accuracy"] == 0.5
    assert summary["final"]["confusion_matrix"] == {
        "a": {"a": 2, "b": 0},
        "b": {"a": 1, "b": 0},
    }
    assert summary["m1_initial"]["confusion_matrix"] == {
        "a": {"a": 1, "b": 1},
        "b": {"a": 1, "b": 1},
    }


def test_build_full_summary_exposes_m3_corrections_worsening_and_net_delta():
    """Catches presenting M3 handoff as automatically beneficial."""
    m3 = build_full_summary(_rows(), labels=("a", "b"))["m3"]
    assert m3["used"] == 2
    assert m3["handoff_rate"] == 0.5
    assert m3["initial_correct"] == 1
    assert m3["final_correct"] == 1
    assert m3["corrected"] == 1
    assert m3["worsened"] == 1
    assert m3["net_correct_delta"] == 0
    assert m3["changed"] == 2
    assert m3["tag_counts"] == {
        "m3": 2, "m3_disputed": 2, "m3_no_tool_retry": 1,
    }


def test_build_full_summary_reports_per_branch_delta_failures_and_calls():
    """Catches hiding which branch lost accuracy or whether the route completed."""
    summary = build_full_summary(_rows(), labels=("a", "b"))
    a = summary["per_label"]["a"]
    b = summary["per_label"]["b"]
    assert (a["support"], a["m1_correct"], a["final_correct"], a["delta_correct"]) == (2, 1, 2, 1)
    assert (b["support"], b["m1_correct"], b["final_correct"], b["delta_correct"]) == (2, 1, 0, -1)
    assert a["m3_corrected"] == 1 and a["m3_worsened"] == 0
    assert b["m3_corrected"] == 0 and b["m3_worsened"] == 1
    assert summary["stability"]["route_failures"] == 1
    assert summary["stability"]["route_failure_rate"] == 0.25
    assert summary["calls"]["total"] == 7
    assert summary["calls"]["by_tier"] == {"1.7b": 4, "9b": 3}
    assert math.isclose(summary["latency_ms"]["m1"]["p50"], 25)
    assert math.isclose(summary["latency_ms"]["m3"]["p50"], 100)


def test_build_full_summary_keeps_asr_rounds_and_hard_pair_slices():
    """Catches losing required robustness slices in the corrected report."""
    strata = build_full_summary(_rows(), labels=("a", "b"))["strata"]
    assert strata["asr_noise"]["true"]["total"] == 2
    assert strata["asr_noise"]["true"]["final_correct"] == 1
    assert strata["rounds"]["4+"]["route_failures"] == 1
    assert strata["hard_pair_presence"]["true"]["m3_used"] == 2


def test_aggregate_cli_writes_summary_file(tmp_path):
    """Catches an aggregator that computes metrics but cannot produce the report artifact."""
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    for module in (aggregate_full_router,):
        shutil.copy2(Path(module.__file__), eval_dir / Path(module.__file__).name)
    shutil.copy2(Path(__file__).with_name("aggregate_results.py"),
                 eval_dir / "aggregate_results.py")
    results = eval_dir / "results.jsonl"
    results.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in _rows()),
        encoding="utf-8")
    output = eval_dir / "summary.json"

    completed = subprocess.run(
        [sys.executable, str(eval_dir / "aggregate_full_router.py"),
         "--input", str(results), "--output", str(output), "--labels", "ab"],
        cwd=tmp_path, text=True, capture_output=True, check=False)

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(output.read_text(encoding="utf-8"))
    assert summary["final"]["correct"] == 2
    assert summary["m3"]["corrected"] == 1


def test_full_report_only_presents_complete_flow_final_metrics():
    """Catches comparing the complete-flow result with standalone M1 capability."""
    rows = _rows()
    rows[2]["text"] = "<script>改提醒</script>"
    summary = build_full_summary(rows, labels=("a", "b"))
    manifest = {"total": 4, "per_label": 2, "seed": 20260817,
                "label_counts": {"a": 2, "b": 2}}
    integrity = {
        "python": "3.10.12", "agent_pid": "2490379",
        "agent_started": "2026-08-17 15:51:37 +0800",
        "hashes": {"dada/mechanisms/m1_gate.py": "abc",
                   "dada/mechanisms/m3_tool_panel.py": "def"},
        "isolation_dir": "/tmp/isolation",
    }
    previous = {"final_accuracy": 0.49, "m1_accuracy": 0.51,
                "corrected": 1, "worsened": 2}

    report = generate_full_report(
        summary, rows, manifest, integrity, previous_run=previous,
        labels=("a", "b"))

    assert report.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in report
    assert "十三分支完整判别流程" in report
    assert "M3 已参与" in report
    assert "完整机制最终准确率" in report
    assert "最终路由" in report
    assert "M1 初判" not in report
    assert "更新前快照" not in report
    assert "M3 纠正" not in report and "M3 劣化" not in report
    assert "混淆矩阵" in report
    assert "ASR" in report and "hard_pair" in report and "多轮" in report
    assert "生产完整性" in report and "隔离目录" in report
    assert "&lt;script&gt;改提醒&lt;/script&gt;" in report
    assert "<script>改提醒</script>" not in report
    assert "https://" not in report and "http://" not in report
    assert report.rstrip().endswith("</html>")


def test_render_cli_writes_html_artifact(tmp_path):
    """Catches a verified renderer that cannot generate the deliverable file."""
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    shutil.copy2(Path(render_full_router_report.__file__),
                 eval_dir / "render_full_router_report.py")
    rows = _rows()
    files = {
        "summary.json": build_full_summary(rows, labels=("a", "b")),
        "manifest.json": {"total": 4, "per_label": 2, "seed": 20260817},
        "integrity.json": {"python": "3.10.12", "hashes": {},
                           "isolation_dir": "/tmp/isolation"},
        "previous.json": {"final_accuracy": 0.49, "m1_accuracy": 0.51,
                          "corrected": 1, "worsened": 2},
    }
    for name, payload in files.items():
        (eval_dir / name).write_text(json.dumps(payload, ensure_ascii=False),
                                     encoding="utf-8")
    (eval_dir / "results.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8")
    output = eval_dir / "report.html"

    completed = subprocess.run(
        [sys.executable, str(eval_dir / "render_full_router_report.py"),
         "--summary", str(eval_dir / "summary.json"),
         "--results", str(eval_dir / "results.jsonl"),
         "--manifest", str(eval_dir / "manifest.json"),
         "--integrity", str(eval_dir / "integrity.json"),
         "--previous-run", str(eval_dir / "previous.json"),
         "--labels", "ab", "--output", str(output)],
        cwd=tmp_path, text=True, capture_output=True, check=False)

    assert completed.returncode == 0, completed.stderr
    html = output.read_text(encoding="utf-8")
    assert "十三分支完整判别流程" in html
    assert "M1 初判" not in html
