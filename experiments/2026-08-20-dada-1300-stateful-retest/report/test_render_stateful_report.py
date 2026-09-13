# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

import render_stateful_report as report


class ReportTests(unittest.TestCase):
    def test_summary_attributes_final_errors_to_m1_or_m3(self):
        rows = [
            {"sample_id": "1", "truth": "a", "prediction": "a", "correct": True,
             "m1_prediction": "a", "m1_correct": True, "m1_direct": True,
             "m3_used": False, "m3_corrected": False, "m3_worsened": False,
             "route_ok": True, "wall_latency_ms": 10},
            {"sample_id": "2", "truth": "b", "prediction": "b", "correct": True,
             "m1_prediction": "c", "m1_correct": False, "m1_direct": False,
             "m3_used": True, "m3_corrected": True, "m3_worsened": False,
             "route_ok": True, "wall_latency_ms": 20},
            {"sample_id": "3", "truth": "c", "prediction": "b", "correct": False,
             "m1_prediction": "c", "m1_correct": True, "m1_direct": False,
             "m3_used": True, "m3_corrected": False, "m3_worsened": True,
             "route_ok": True, "wall_latency_ms": 30},
            {"sample_id": "4", "truth": "d", "prediction": "a", "correct": False,
             "m1_prediction": "a", "m1_correct": False, "m1_direct": False,
             "m3_used": True, "m3_corrected": False, "m3_worsened": False,
             "route_ok": True, "wall_latency_ms": 40},
            {"sample_id": "5", "truth": "e", "prediction": "a", "correct": False,
             "m1_prediction": "a", "m1_correct": False, "m1_direct": True,
             "m3_used": False, "m3_corrected": False, "m3_worsened": False,
             "route_ok": True, "wall_latency_ms": 50},
        ]
        summary = report.summarize(rows)
        self.assertEqual(5, summary["total"])
        self.assertEqual(2, summary["correct"])
        self.assertEqual(3, summary["m3_used"])
        self.assertEqual(1, summary["m3_corrected"])
        self.assertEqual(1, summary["m3_worsened"])
        self.assertEqual(1, summary["error_attribution"]["m1_direct_error"])
        self.assertEqual(1, summary["error_attribution"]["m3_worsened"])
        self.assertEqual(1, summary["error_attribution"]["m3_failed_to_correct"])
        self.assertEqual(30, summary["latency_ms"]["p50"])

    def test_render_writes_main_and_failure_html(self):
        rows = [{"sample_id": "x", "truth": "a", "prediction": "m",
                 "correct": False, "m1_prediction": "m", "m1_correct": False,
                 "m1_direct": True, "m3_used": False, "m3_corrected": False,
                 "m3_worsened": False, "route_ok": True, "wall_latency_ms": 12,
                 "text": "提醒我", "history": [], "m3_tags": []}]
        preflight = {"eval_user_id": 2026082001,
                     "input": {"sha256": "abc"},
                     "fixture_state": {"fixture_task_count": 1,
                                       "fixture_memory_count": 1,
                                       "narrow_absent": []},
                     "production_sha256": {"m1_gate": "m1", "m3_tool_panel": "m3"}}
        with tempfile.TemporaryDirectory() as tmp:
            main = Path(tmp) / "main.html"
            failures = Path(tmp) / "failures.html"
            report.render(rows, preflight, main, failures, "2026-08-20")
            main_text = main.read_text(encoding="utf-8")
            failure_text = failures.read_text(encoding="utf-8")
        self.assertIn("M1 → M3", main_text)
        self.assertIn("97%", main_text)
        self.assertIn("提醒我", failure_text)
        self.assertNotIn("<script src=", main_text)


if __name__ == "__main__":
    unittest.main()
