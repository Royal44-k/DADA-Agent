import importlib
import json
import tempfile
import unittest
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


class Rerun2ReportTests(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module("render_m3_rerun2_html")
        self.baseline = BASE_DIR / "results-m1-m3-current-1300.jsonl"
        self.failed_retest = BASE_DIR / "results-m1-m3-newm3-current-1300-20260818.jsonl"
        self.current = BASE_DIR / "results-m1-m3-rerun2-1300-20260818.jsonl"

    def test_metrics_close_against_hand_checked_counts(self):
        metrics = self.mod.compute_metrics(
            self.baseline, self.failed_retest, self.current
        )

        self.assertEqual(metrics["total"], 1300)
        self.assertEqual(metrics["current_correct"], 1191)
        self.assertEqual(metrics["current_errors"], 109)
        self.assertAlmostEqual(metrics["current_accuracy"], 0.9161538461538462)
        self.assertEqual(metrics["m3_attempts"], 285)
        self.assertEqual(metrics["m3_success"], 285)
        self.assertEqual(metrics["route_failures"], 0)
        self.assertEqual(metrics["m3_corrected"], 8)
        self.assertEqual(metrics["m3_worsened"], 74)
        self.assertEqual(
            metrics["error_counts"],
            {
                "route_failure": 0,
                "m3_introduced": 74,
                "m3_unresolved": 29,
                "m1_direct": 6,
            },
        )
        self.assertEqual(
            {k: v["correct"] for k, v in metrics["branches"].items()},
            {
                "a": 95, "b": 98, "c": 96, "d": 95, "e": 79,
                "f": 100, "g": 100, "h": 100, "i": 98, "j": 72,
                "k": 92, "l": 74, "m": 92,
            },
        )

    def test_comparison_uses_same_1300_sample_ids(self):
        metrics = self.mod.compute_metrics(
            self.baseline, self.failed_retest, self.current
        )

        self.assertEqual(metrics["baseline_correct"], 1172)
        self.assertEqual(metrics["failed_retest_correct"], 1028)
        self.assertEqual(metrics["delta_vs_baseline"], 19)
        self.assertEqual(metrics["delta_vs_failed_retest"], 163)
        self.assertEqual(
            metrics["matched_vs_baseline"],
            {"both_correct": 1160, "fixed": 31, "regressed": 12, "both_wrong": 97},
        )

    def test_generate_writes_self_contained_report_and_failure_appendix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path, failures_path = self.mod.generate(
                self.baseline, self.failed_retest, self.current, Path(temp_dir)
            )
            report = report_path.read_text(encoding="utf-8")
            failures = failures_path.read_text(encoding="utf-8")

        self.assertIn("data-current-correct=\"1191\"", report)
        self.assertIn("91.62%", report)
        self.assertIn("M3复判净影响", report)
        self.assertIn("109条最终错误", report)
        self.assertEqual(failures.count("class='failure-row'"), 109)
        self.assertIn("data-failure-count=\"109\"", failures)
        self.assertNotIn("Context size has been exceeded", report)


if __name__ == "__main__":
    unittest.main()
