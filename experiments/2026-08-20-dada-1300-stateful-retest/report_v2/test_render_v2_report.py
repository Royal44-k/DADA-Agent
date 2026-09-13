# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

import render_v2_report as report


class V2ReportTests(unittest.TestCase):
    def test_review_outcomes_separate_repairs_from_kept_model_errors(self):
        rows = [
            {"sample_id": "label", "correct": True},
            {"sample_id": "rewrite", "correct": True},
            {"sample_id": "keep", "correct": False},
        ]
        audit = {"changes": [
            {"sample_id": "label", "disposition": "label_fix"},
            {"sample_id": "rewrite", "disposition": "text_rewrite"},
            {"sample_id": "keep", "disposition": "model_error_keep"},
        ]}
        outcomes = report.review_outcomes(rows, audit)
        self.assertEqual({"total": 1, "correct": 1, "errors": 0}, outcomes["label_fix"])
        self.assertEqual({"total": 1, "correct": 1, "errors": 0}, outcomes["text_rewrite"])
        self.assertEqual({"total": 1, "correct": 0, "errors": 1}, outcomes["model_error_keep"])

    def test_compare_reports_accuracy_delta_and_m3_net_effect(self):
        rows = [
            {"sample_id": "1", "truth": "a", "prediction": "a", "correct": True,
             "m1_correct": True, "m1_direct": True, "m3_used": False,
             "m3_corrected": False, "m3_worsened": False, "route_ok": True,
             "wall_latency_ms": 10},
            {"sample_id": "2", "truth": "b", "prediction": "b", "correct": True,
             "m1_correct": False, "m1_direct": False, "m3_used": True,
             "m3_corrected": True, "m3_worsened": False, "route_ok": True,
             "wall_latency_ms": 20},
            {"sample_id": "3", "truth": "c", "prediction": "m", "correct": False,
             "m1_correct": True, "m1_direct": False, "m3_used": True,
             "m3_corrected": False, "m3_worsened": True, "route_ok": True,
             "wall_latency_ms": 30},
        ]
        previous = {"accuracy": 0.50, "correct": 2, "errors": 2, "total": 4}
        summary = report.summarize(rows, previous)
        self.assertAlmostEqual(2 / 3, summary["accuracy"])
        self.assertAlmostEqual((2 / 3 - .5) * 100, summary["accuracy_delta_pp"])
        self.assertEqual(0, summary["m3_net_gain"])

    def test_render_creates_main_failures_and_revision_ledger(self):
        rows = [{"sample_id": "x", "truth": "l", "prediction": "m", "correct": False,
                 "m1_prediction": "l", "m1_correct": True, "m1_direct": False,
                 "m3_used": True, "m3_corrected": False, "m3_worsened": True,
                 "m3_tags": ["m3"], "route_ok": True, "wall_latency_ms": 12,
                 "text": "我先走了", "history": []}]
        previous = {"accuracy": .90, "correct": 9, "errors": 1, "total": 10}
        preflight = {"eval_user_id": 2026082001, "input": {"sha256": "abc"},
                     "fixture_state": {"fixture_task_count": 1, "fixture_memory_count": 1,
                                       "narrow_absent": []},
                     "production_sha256": {"m1_gate": "m1", "m3_tool_panel": "m3"}}
        audit = {"reviewed_failures": 34, "label_changes": 2, "text_changes": 15,
                 "semantic_changes": 17, "model_error_kept": 17,
                 "changes": [{"sample_id": "x", "disposition": "text_rewrite",
                              "before_label": "l", "after_label": "l",
                              "before_text": "歇着吧你", "after_text": "你歇着吧，我先走了。",
                              "rationale": "消除闲聊歧义"}]}
        with tempfile.TemporaryDirectory() as tmp:
            main = Path(tmp) / "main.html"
            failures = Path(tmp) / "failures.html"
            revisions = Path(tmp) / "revisions.html"
            report.render(rows, previous, preflight, audit, main, failures, revisions, "2026-08-20")
            main_text = main.read_text(encoding="utf-8")
            failure_text = failures.read_text(encoding="utf-8")
            revision_text = revisions.read_text(encoding="utf-8")
        self.assertIn("2 条改标", main_text)
        self.assertIn("15 条改写", main_text)
        self.assertIn("我先走了", failure_text)
        self.assertIn("歇着吧你", revision_text)
        self.assertIn("你歇着吧，我先走了。", revision_text)
        self.assertNotIn("<script src=", main_text)


if __name__ == "__main__":
    unittest.main()
