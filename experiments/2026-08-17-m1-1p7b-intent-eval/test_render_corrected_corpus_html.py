import json
import pathlib
import tempfile
import unittest

import render_corrected_corpus_html as report


HERE = pathlib.Path(__file__).resolve().parent
SAMPLE_PATH = HERE / "sample-1300.jsonl"
RESULT_PATH = HERE / "results-m1-m3-rerun2-1300-20260818.jsonl"
RAW_ROOT = pathlib.Path(r"C:\Users\lenovo\Downloads\raw")


class CorrectedCorpusTests(unittest.TestCase):
    def test_audit_covers_every_failed_case_once(self):
        failures = {
            json.loads(line)["sample_id"]
            for line in RESULT_PATH.read_text(encoding="utf-8").splitlines()
            if not json.loads(line)["correct"]
        }
        self.assertEqual(109, len(failures))
        self.assertEqual(failures, set(report.AUDIT_DECISIONS))
        self.assertEqual(64, sum(d.revised_label != d.original_label for d in report.AUDIT_DECISIONS.values()))

    def test_context_sensitive_boundary_decisions_are_locked(self):
        expected = {
            # Reminder/memory boundaries.
            "a-01497-dd56f4a0a47e": "a",
            "a-03146-8f994a113422": "b",
            "d-02137-bf7c7d801f7a": "e",
            "e-02667-a37780cb1a66": "e",
            "e-03237-b4e0c3a3a1fe": "d",
            "e-00306-1fcf5e043ae4": "m",
            "e-00554-17ced9b916fe": "j",
            # Product capability versus actual execution.
            "j-03251-c9c9a5ea1cc9": "j",
            "j-03587-12eb72ad98f7": "f",
            "j-01869-6f71a8dca51a": "h",
            "j-01278-a111a480b80e": "j",
            # Action must not be swallowed by a trailing sleep/farewell phrase.
            "k-00389-1c5a9208f8f7": "a",
            "k-01897-6305007de075": "k",
            "l-02157-7869133cf148": "b",
            # Pure sleep and farewell stay distinct.
            "l-02125-629bda958d10": "k",
            "l-00813-2aa482495d1b": "l",
            "m-01365-0db281149dbf": "l",
        }
        for sample_id, label in expected.items():
            with self.subTest(sample_id=sample_id):
                self.assertEqual(label, report.AUDIT_DECISIONS[sample_id].revised_label)

    def test_corpus_is_rebuilt_from_exact_raw_source_context(self):
        corpus = report.load_corrected_corpus(SAMPLE_PATH, RAW_ROOT)
        self.assertEqual(1300, len(corpus))
        self.assertEqual(1300, len({row["sample_id"] for row in corpus}))
        self.assertEqual(100, sum(row["original_label"] == "a" for row in corpus))
        self.assertEqual(100, sum(row["original_label"] == "m" for row in corpus))

        target = next(row for row in corpus if row["sample_id"] == "a-01497-dd56f4a0a47e")
        raw = json.loads((RAW_ROOT / target["source_file"]).read_text(encoding="utf-8").splitlines()[target["source_line"] - 1])
        self.assertEqual(raw["text"], target["original_text"])
        self.assertNotEqual(raw["text"], target["text"])
        self.assertEqual(raw["history"], target["original_history"])
        self.assertEqual(raw["ctx"], target["ctx"])
        self.assertEqual("reviewed_keep", target["audit_status"])
        self.assertEqual("rewritten", target["text_status"])

        revised = next(row for row in corpus if row["sample_id"] == "l-02157-7869133cf148")
        self.assertEqual("l", revised["original_label"])
        self.assertEqual("b", revised["revised_label"])
        self.assertEqual("relabel", revised["audit_status"])

    def test_rewrites_resolve_every_flagged_quality_issue_and_are_context_coherent(self):
        self.assertEqual(63, len(report.CORPUS_REWRITES))
        self.assertTrue(set(report.CORPUS_REWRITES) <= set(report.AUDIT_DECISIONS))
        originally_flagged = {
            sample_id for sample_id, decision in report.AUDIT_DECISIONS.items() if decision.needs_rewrite
        }
        self.assertTrue(originally_flagged <= set(report.CORPUS_REWRITES))

        corpus = report.load_corrected_corpus(SAMPLE_PATH, RAW_ROOT)
        rewritten = {row["sample_id"]: row for row in corpus if row["text_status"] == "rewritten"}
        self.assertEqual(63, len(rewritten))
        self.assertEqual(0, sum(row["unresolved_quality_issue"] for row in corpus))

        # These fixtures catch the key failure modes: broken ASR, an invalid
        # assistant follow-up, and a side-effecting request mixed with sleep.
        self.assertEqual("提醒我明天早上八点吃药。", rewritten["e-00198-3ad087769b1a"]["text"])
        self.assertEqual("对，就取消早上七点的吃药提醒。", rewritten["j-03283-7e53d56fff0d"]["text"])
        self.assertEqual(
            "请确认，要取消的是早上七点的吃药提醒吗？",
            rewritten["j-03283-7e53d56fff0d"]["history"][-1][1],
        )
        self.assertEqual("把刚才那个提醒改到八点吧。", rewritten["l-02157-7869133cf148"]["text"])

    def test_html_contains_all_rows_filters_and_audit_legend(self):
        corpus = report.load_corrected_corpus(SAMPLE_PATH, RAW_ROOT)
        html = report.render_html(corpus)
        self.assertEqual(1300, html.count('class="corpus-row"'))
        self.assertIn('id="keywordSearch"', html)
        self.assertIn('id="labelFilter"', html)
        self.assertIn('id="statusFilter"', html)
        self.assertIn('id="ctxFilter"', html)
        self.assertIn("逐条复核 109", html)
        self.assertIn("修订标签 64", html)
        self.assertIn("已改写语料 63", html)
        self.assertIn("遗留破损 0", html)
        self.assertIn("raw 原文", html)
        self.assertIn("修订文本", html)
        self.assertIn("原始 raw 文件保持只读，未被改写", html)

    def test_write_report_creates_self_contained_utf8_html(self):
        corpus = report.load_corrected_corpus(SAMPLE_PATH, RAW_ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / "corpus.html"
            report.write_report(output, corpus)
            data = output.read_text(encoding="utf-8")
            self.assertTrue(data.startswith("<!doctype html>"))
            self.assertNotIn("https://", data)
            self.assertIn("哒哒 Agent 修订后 1300 条测试语料", data)

    def test_corrected_jsonl_is_directly_reusable_for_the_next_evaluation(self):
        corpus = report.load_corrected_corpus(SAMPLE_PATH, RAW_ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / "sample-1300-corrected.jsonl"
            report.write_corrected_jsonl(output, corpus)
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(1300, len(rows))
        self.assertEqual(1300, len({row["sample_id"] for row in rows}))
        changed = next(row for row in rows if row["sample_id"] == "j-03283-7e53d56fff0d")
        self.assertEqual("b", changed["label"])
        self.assertEqual("对，就取消早上七点的吃药提醒。", changed["text"])
        self.assertEqual("长沙的，就记得那个了。", changed["audit"]["raw_text"])
        self.assertTrue(changed["audit"]["text_rewritten"])

    def test_rewritten_rows_recompute_round_and_stratum_metadata(self):
        corpus = report.load_corrected_corpus(SAMPLE_PATH, RAW_ROOT)
        for row in corpus:
            with self.subTest(sample_id=row["sample_id"]):
                expected_rounds = len(row["history"]) // 2 + 1
                expected_bucket = str(expected_rounds) if expected_rounds in (1, 2, 3) else "4+"
                expected_stratum = (
                    f"noise={str(row['asr_noise']).lower()}|"
                    f"rounds={expected_bucket}|hard={str(bool(row['hard_pair'])).lower()}"
                )
                self.assertEqual(expected_rounds, row["rounds"])
                self.assertEqual(expected_bucket, row["rounds_bucket"])
                self.assertEqual(expected_stratum, row["stratum"])


if __name__ == "__main__":
    unittest.main()
