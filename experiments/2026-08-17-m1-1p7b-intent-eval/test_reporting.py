# -*- coding: utf-8 -*-
import json
import math

from aggregate_results import (build_summary, classification_metrics,
                               confusion_matrix, gate_metrics, percentile,
                               threshold_sweep, wilson)
from render_report import generate_report


def _rows():
    return [
        {"sample_id": "a1", "truth": "a", "prediction": "a", "correct": True,
         "valid_label": True, "direct": True, "dangerous_misroute": False,
         "exception_type": None, "asr_noise": False, "rounds_bucket": "1",
         "hard_pair": None, "model_latency_ms": 10, "top1": .99,
         "margin": .98, "text": "正确a"},
        {"sample_id": "a2", "truth": "a", "prediction": "b", "correct": False,
         "valid_label": True, "direct": True, "dangerous_misroute": True,
         "exception_type": None, "asr_noise": True, "rounds_bucket": "2",
         "hard_pair": "a/b", "model_latency_ms": 20, "top1": .995,
         "margin": .99, "text": "<script>错误</script>"},
        {"sample_id": "b1", "truth": "b", "prediction": "b", "correct": True,
         "valid_label": True, "direct": False, "dangerous_misroute": False,
         "exception_type": None, "asr_noise": False, "rounds_bucket": "3",
         "hard_pair": "a/b", "model_latency_ms": 30, "top1": .8,
         "margin": .6, "text": "正确b"},
        {"sample_id": "b2", "truth": "b", "prediction": None, "correct": False,
         "valid_label": False, "direct": False, "dangerous_misroute": False,
         "exception_type": "TimeoutError", "asr_noise": True, "rounds_bucket": "4+",
         "hard_pair": None, "model_latency_ms": None, "wall_latency_ms": 40,
         "top1": None, "margin": None, "text": "超时"},
    ]


def test_confusion_and_classification_metrics_use_hand_checked_counts():
    """Catches wrong axes, excluding failures, or macro averaging mistakes."""
    rows = _rows()
    matrix = confusion_matrix(rows, labels=("a", "b"))
    assert matrix == {"a": {"a": 1, "b": 1}, "b": {"a": 0, "b": 1}}

    metrics = classification_metrics(rows, labels=("a", "b"))
    assert metrics["total"] == 4
    assert metrics["correct"] == 2
    assert metrics["accuracy"] == 0.5
    assert math.isclose(metrics["per_label"]["a"]["precision"], 1.0)
    assert math.isclose(metrics["per_label"]["a"]["recall"], 0.5)
    assert math.isclose(metrics["per_label"]["a"]["f1"], 2 / 3)
    assert math.isclose(metrics["per_label"]["b"]["precision"], 0.5)
    assert math.isclose(metrics["per_label"]["b"]["recall"], 0.5)
    assert math.isclose(metrics["per_label"]["b"]["f1"], 0.5)
    assert metrics["per_label"]["a"]["direct"] == 2
    assert metrics["per_label"]["a"]["direct_correct"] == 1
    assert metrics["per_label"]["a"]["dangerous"] == 1
    assert metrics["per_label"]["a"]["direct_accuracy"] == 0.5
    assert metrics["per_label"]["b"]["direct"] == 0
    assert metrics["per_label"]["b"]["direct_accuracy"] is None
    assert math.isclose(metrics["macro_f1"], (2 / 3 + 0.5) / 2)


def test_gate_metrics_separate_coverage_accuracy_and_danger():
    """Catches calling low-confidence misses wrong direct routes."""
    metrics = gate_metrics(_rows())
    assert metrics["call_success"] == 3
    assert metrics["call_failures"] == 1
    assert metrics["direct"] == 2
    assert metrics["direct_correct"] == 1
    assert metrics["dangerous_misroutes"] == 1
    assert math.isclose(metrics["coverage"], 2 / 3)
    assert metrics["direct_accuracy"] == 0.5
    assert math.isclose(metrics["dangerous_rate"], 1 / 3)
    assert metrics["m3_handoff"] == 1


def test_threshold_sweep_exposes_coverage_and_risk_tradeoff():
    """Catches a threshold recommendation that ignores dangerous routes."""
    sweep = threshold_sweep(_rows(), thresholds=(0.98, 0.997))
    assert sweep[0] == {
        "threshold": 0.98, "direct": 2, "coverage": 2 / 3,
        "direct_correct": 1, "dangerous": 1, "direct_accuracy": 0.5,
        "dangerous_rate": 1 / 3,
    }
    assert sweep[1] == {
        "threshold": 0.997, "direct": 0, "coverage": 0.0,
        "direct_correct": 0, "dangerous": 0, "direct_accuracy": None,
        "dangerous_rate": 0.0,
    }


def test_wilson_and_percentile_are_numerically_stable():
    """Catches optimistic intervals or wrong percentile indexing."""
    low, high = wilson(5, 10)
    assert math.isclose(low, 0.236593, rel_tol=1e-5)
    assert math.isclose(high, 0.763407, rel_tol=1e-5)
    assert percentile([10, 20, 30, 40], 0.5) == 25
    assert percentile([10, 20, 30, 40], 0.95) == 38.5
    assert percentile([], 0.95) is None


def test_build_summary_includes_strata_latency_and_top_confusion():
    """Catches omitting the analyses required by the evaluation design."""
    summary = build_summary(_rows(), labels=("a", "b"))
    assert summary["classification"]["accuracy"] == 0.5
    assert summary["gate"]["dangerous_misroutes"] == 1
    assert summary["strata"]["asr_noise"]["true"]["total"] == 2
    assert summary["strata"]["rounds"]["4+"]["total"] == 1
    assert summary["latency_ms"]["p50"] == 25
    assert summary["latency_ms"]["p95"] == 38.5
    assert summary["top_confusions"][0]["truth"] == "a"
    assert summary["top_confusions"][0]["prediction"] == "b"


def test_generate_report_is_standalone_escaped_and_contains_required_sections():
    """Catches missing evidence sections, external assets, or raw HTML injection."""
    rows = _rows()
    summary = build_summary(rows, labels=("a", "b"))
    manifest = {"total": 4, "seed": 20260817, "per_label": 2,
                "label_counts": {"a": 2, "b": 2}}
    before = {"python": "3.10.12", "agent_pid": "123410",
              "hashes": {"flow.py": "abc"}}
    after = {"python": "3.10.12", "agent_pid": "123410",
             "hashes": {"flow.py": "abc"}}

    html = generate_report(summary, rows, manifest, before, after,
                           labels=("a", "b"))

    assert html.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in html
    assert "M1 / 1.7B" in html
    assert "混淆矩阵" in html
    assert "危险误路由率" in html
    assert "ASR" in html and "多轮" in html and "hard_pair" in html
    assert "生产完整性" in html
    assert "建议与优先级" in html
    assert "按分支门控" in html
    assert "&lt;script&gt;错误&lt;/script&gt;" in html
    assert "<script>错误</script>" not in html
    assert "https://" not in html and "http://" not in html
    assert html.rstrip().endswith("</html>")
