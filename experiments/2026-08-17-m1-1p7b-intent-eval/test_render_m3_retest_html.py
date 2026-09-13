# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

try:
    from render_m3_retest_html import (
        FAILURE_FILENAME,
        REPORT_FILENAME,
        generate,
    )
except ImportError as exc:
    raise AssertionError("M3 retest HTML generator is missing") from exc


ROOT = Path(__file__).resolve().parent
OLD_PATH = ROOT / "results-m1-m3-current-1300.jsonl"
NEW_PATH = ROOT / "results-m1-m3-newm3-current-1300-20260818.jsonl"


class ArtifactParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []
        self.failure_rows = []
        self.main_attrs = {}
        self.select_id = None
        self.options = {}
        self.text_parts = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        element_id = values.get("id")
        if element_id:
            self.ids.add(element_id)
        if tag == "a" and values.get("href"):
            self.links.append(values["href"])
        if tag == "main" and element_id:
            self.main_attrs[element_id] = values
        if tag == "tr" and "failure-row" in values.get("class", "").split():
            self.failure_rows.append(values)
        if tag == "select":
            self.select_id = element_id
            if element_id:
                self.options.setdefault(element_id, [])
        if tag == "option" and self.select_id:
            self.options[self.select_id].append(values.get("value", ""))

    def handle_endtag(self, tag):
        if tag == "select":
            self.select_id = None

    def handle_data(self, data):
        if data.strip():
            self.text_parts.append(data.strip())

    @property
    def text(self):
        return " ".join(self.text_parts)


def parse(path):
    parser = ArtifactParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def load_rows(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class M3RetestHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.output_dir = Path(cls.temp_dir.name)
        report, failures = generate(OLD_PATH, NEW_PATH, cls.output_dir)
        cls.report_path = Path(report)
        cls.failures_path = Path(failures)
        cls.report = parse(cls.report_path)
        cls.failures = parse(cls.failures_path)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_generates_the_two_named_html_artifacts(self):
        self.assertEqual(self.report_path.name, REPORT_FILENAME)
        self.assertEqual(self.failures_path.name, FAILURE_FILENAME)
        self.assertTrue(self.report_path.is_file())
        self.assertTrue(self.failures_path.is_file())

    def test_failure_dataset_matches_every_final_error_exactly_once(self):
        expected_ids = {
            row["sample_id"]
            for row in load_rows(NEW_PATH)
            if not row["correct"]
        }
        actual_ids = [row["data-sample-id"] for row in self.failures.failure_rows]
        self.assertEqual(len(actual_ids), 272)
        self.assertEqual(len(set(actual_ids)), 272)
        self.assertEqual(set(actual_ids), expected_ids)

    def test_failure_taxonomy_and_branch_totals_are_complete(self):
        error_counts = Counter(
            row["data-error-type"] for row in self.failures.failure_rows
        )
        self.assertEqual(error_counts, {
            "route_failure": 245,
            "m3_introduced": 15,
            "m3_unresolved": 6,
            "m1_direct": 6,
        })
        truth_counts = Counter(row["data-truth"] for row in self.failures.failure_rows)
        self.assertEqual(truth_counts, {
            "a": 18, "b": 16, "c": 9, "d": 17, "e": 40,
            "f": 10, "g": 1, "h": 2, "i": 13, "j": 43,
            "k": 66, "l": 27, "m": 10,
        })

    def test_report_exposes_the_verified_metrics(self):
        attrs = self.report.main_attrs["report"]
        self.assertEqual(attrs["data-total"], "1300")
        self.assertEqual(attrs["data-old-correct"], "1172")
        self.assertEqual(attrs["data-new-correct"], "1028")
        self.assertEqual(attrs["data-final-errors"], "272")
        self.assertEqual(attrs["data-route-failures"], "245")
        self.assertIn("Context size has been exceeded", self.report.text)
        self.assertIn("不通过", self.report.text)

    def test_failure_page_has_filters_and_mutual_navigation(self):
        self.assertTrue({
            "filter-search", "filter-branch", "filter-error-type",
            "filter-path", "reset-filters", "visible-count",
        }.issubset(self.failures.ids))
        self.assertEqual(
            set(self.failures.options["filter-branch"]),
            {"all", *list("abcdefghijklm")},
        )
        self.assertEqual(
            set(self.failures.options["filter-error-type"]),
            {"all", "route_failure", "m3_introduced", "m3_unresolved", "m1_direct"},
        )
        self.assertIn(FAILURE_FILENAME, self.report.links)
        self.assertIn(REPORT_FILENAME, self.failures.links)


if __name__ == "__main__":
    unittest.main(verbosity=2)
