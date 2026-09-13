import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from export_raw_folder import EXPORT_FIELDS, LABELS, export_raw_folder


SOURCE = Path(__file__).parents[1] / "sample-1300-corrected-v3-2026-08-20.jsonl"
EXPECTED_COUNTS = {
    "a": 113,
    "b": 111,
    "c": 98,
    "d": 101,
    "e": 89,
    "f": 110,
    "g": 101,
    "h": 102,
    "i": 101,
    "j": 84,
    "k": 101,
    "l": 87,
    "m": 102,
}


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class ExportRawFolderTests(unittest.TestCase):
    def test_export_matches_raw_layout_and_final_v3_content(self):
        source_rows = read_jsonl(SOURCE)

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "测试集-1300"
            summary = export_raw_folder(SOURCE, output)

            self.assertEqual(
                sorted(path.name for path in output.iterdir()),
                [f"{label}.jsonl" for label in LABELS],
            )
            self.assertEqual(EXPORT_FIELDS, (
                "label", "rounds", "ctx", "hard_pair",
                "history", "text", "asr_noise", "src",
            ))

            exported_count = 0
            exported_counts = Counter()
            for label in LABELS:
                rows = read_jsonl(output / f"{label}.jsonl")
                expected_rows = [
                    {field: row[field] for field in EXPORT_FIELDS}
                    for row in source_rows
                    if row["label"] == label
                ]

                self.assertEqual(rows, expected_rows)
                self.assertTrue(all(list(row.keys()) == list(EXPORT_FIELDS) for row in rows))
                self.assertTrue(all(row["label"] == label for row in rows))
                exported_count += len(rows)
                exported_counts[label] += len(rows)

            self.assertEqual(exported_count, 1300)
            self.assertEqual(dict(exported_counts), EXPECTED_COUNTS)
            self.assertEqual(summary["total"], 1300)
            self.assertEqual(summary["counts"], EXPECTED_COUNTS)

    def test_refuses_to_overwrite_nonempty_output_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "测试集-1300"
            output.mkdir()
            (output / "keep.txt").write_text("do not overwrite", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                export_raw_folder(SOURCE, output)


if __name__ == "__main__":
    unittest.main()
