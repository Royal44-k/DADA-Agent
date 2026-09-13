# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

import build_v2_corpus as corpus


ROOT = Path(r"D:\Codex-chat")
INPUT = ROOT / "2026-08-17-m1-1p7b-intent-eval" / "sample-1300-corrected-2026-08-19.jsonl"
RESULTS = ROOT / "2026-08-20-dada-1300-stateful-retest" / "artifacts" / "results-full-1300.jsonl"
DECISIONS = ROOT / "2026-08-20-dada-1300-stateful-retest" / "review" / "revisions_v2.json"


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class V2CorpusTests(unittest.TestCase):
    def test_decisions_cover_all_34_failures_with_expected_change_budget(self):
        source = load_jsonl(INPUT)
        results = load_jsonl(RESULTS)
        decisions = json.loads(DECISIONS.read_text(encoding="utf-8"))
        audit = corpus.validate_decisions(source, results, decisions)
        self.assertEqual(34, audit["reviewed_failures"])
        self.assertEqual(2, audit["label_changes"])
        self.assertEqual(15, audit["text_changes"])
        self.assertEqual(17, audit["semantic_changes"])
        self.assertEqual(17, audit["model_error_kept"])

    def test_build_preserves_order_and_changes_only_authorized_fields(self):
        source = load_jsonl(INPUT)
        results = load_jsonl(RESULTS)
        decisions = json.loads(DECISIONS.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "v2.jsonl"
            audit_path = Path(tmp) / "audit.json"
            corpus.build(INPUT, RESULTS, DECISIONS, output, audit_path)
            revised = load_jsonl(output)
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        self.assertEqual(1300, len(revised))
        self.assertEqual([row["sample_id"] for row in source],
                         [row["sample_id"] for row in revised])
        self.assertEqual(1300, len({row["sample_id"] for row in revised}))
        self.assertEqual(17, audit["semantic_changes"])
        self.assertEqual([], audit["unresolved"])
        decision_ids = {item["sample_id"] for item in decisions}
        for before, after in zip(source, revised):
            if before["sample_id"] not in decision_ids:
                self.assertEqual(before, after)
            else:
                self.assertIn("audit_v2", after)

    def test_known_label_fixes_follow_production_branch_definitions(self):
        source = load_jsonl(INPUT)
        results = load_jsonl(RESULTS)
        decisions = json.loads(DECISIONS.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "v2.jsonl"
            corpus.build(INPUT, RESULTS, DECISIONS, output, Path(tmp) / "audit.json")
            by_id = {row["sample_id"]: row for row in load_jsonl(output)}
        self.assertEqual("c", by_id["i-00059-9885a5750efa"]["label"])
        self.assertEqual("i", by_id["k-00324-25241ee6d94a"]["label"])
        self.assertEqual("j", by_id["j-02183-74400192e649"]["label"])
        self.assertEqual("e", by_id["e-02667-a37780cb1a66"]["label"])


if __name__ == "__main__":
    unittest.main()
