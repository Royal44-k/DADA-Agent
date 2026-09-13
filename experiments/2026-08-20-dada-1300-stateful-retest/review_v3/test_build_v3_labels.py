# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

import build_v3_labels as v3


ROOT = Path(r"D:\Codex-chat\2026-08-20-dada-1300-stateful-retest")
INPUT = ROOT / "sample-1300-corrected-v2-2026-08-20.jsonl"
RESULTS = ROOT / "artifacts_v2" / "results-full-v2-1300-final.jsonl"


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class V3LabelPatchTests(unittest.TestCase):
    def test_user_requested_labels_are_applied_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "v3.jsonl"
            audit = Path(tmp) / "audit.json"
            result = v3.build(INPUT, RESULTS, output, audit)
            rows = {row["sample_id"]: row for row in load_jsonl(output)}
        self.assertEqual("m", rows["b-02115-0da3b1f6b6c8"]["label"])
        self.assertEqual("m", rows["d-00495-19fb7f0c478d"]["label"])
        self.assertEqual("a", rows["j-02646-702c3d39553b"]["label"])
        self.assertEqual("m", rows["l-01230-623efe9e456c"]["label"])
        self.assertEqual("l", rows["m-01365-0db281149dbf"]["label"])
        self.assertEqual(3, result["actual_label_changes"])
        self.assertEqual(2, result["already_matching_confirmations"])

    def test_order_text_and_unrequested_rows_are_preserved(self):
        before = load_jsonl(INPUT)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "v3.jsonl"
            v3.build(INPUT, RESULTS, output, Path(tmp) / "audit.json")
            after = load_jsonl(output)
        self.assertEqual(1300, len(after))
        self.assertEqual([row["sample_id"] for row in before], [row["sample_id"] for row in after])
        self.assertEqual([row["text"] for row in before], [row["text"] for row in after])
        requested = set(v3.REQUESTED_LABELS)
        for old, new in zip(before, after):
            if old["sample_id"] not in requested:
                self.assertEqual(old, new)

    def test_fixed_output_counterfactual_accuracy_is_1283_of_1300(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "v3.jsonl"
            result = v3.build(INPUT, RESULTS, output, Path(tmp) / "audit.json")
        theory = result["fixed_output_counterfactual"]
        self.assertEqual(1280, theory["before_correct"])
        self.assertEqual(1283, theory["after_correct"])
        self.assertEqual(3, theory["newly_correct"])
        self.assertEqual(0, theory["newly_wrong"])
        self.assertAlmostEqual(1283 / 1300, theory["after_accuracy"])


if __name__ == "__main__":
    unittest.main()
