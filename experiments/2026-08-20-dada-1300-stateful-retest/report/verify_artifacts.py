# -*- coding: utf-8 -*-
"""Independent integrity checks for the stateful router retest artifacts."""
import argparse
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            values = dict(attrs)
            if values.get("href"):
                self.hrefs.append(values["href"])


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--preflight", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--main-html", required=True, type=Path)
    parser.add_argument("--failures-html", required=True, type=Path)
    args = parser.parse_args()

    source = load_jsonl(args.input)
    results = load_jsonl(args.results)
    preflight = json.loads(args.preflight.read_text(encoding="utf-8"))
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    assert len(source) == 1300, len(source)
    assert len(results) == 1300, len(results)
    source_ids = [row["sample_id"] for row in source]
    result_ids = [row["sample_id"] for row in results]
    assert len(set(source_ids)) == 1300
    assert result_ids == source_ids, "result order/sample IDs differ from corrected corpus"
    expected_labels = {row["sample_id"]: row["label"] for row in source}
    assert all(row["truth"] == expected_labels[row["sample_id"]] for row in results)
    assert all(bool(row["correct"]) == (row.get("prediction") == row["truth"]) for row in results)
    assert sha256(args.input) == preflight["input"]["sha256"]

    correct = sum(bool(row["correct"]) for row in results)
    errors = len(results) - correct
    m3_used = sum(bool(row["m3_used"]) for row in results)
    route_failures = sum(bool(row.get("exception_type")) or not row.get("route_ok") for row in results)
    assert correct == 1266
    assert errors == 34
    assert m3_used == 265
    assert route_failures == 0
    assert summary["total"] == 1300
    assert summary["correct"] == correct
    assert summary["errors"] == errors
    assert abs(summary["accuracy"] - correct / 1300) < 1e-12
    assert summary["target_met"] is True

    main_text = args.main_html.read_text(encoding="utf-8")
    failure_text = args.failures_html.read_text(encoding="utf-8")
    assert "97.38%" in main_text
    assert "1266/1300" in main_text
    assert failure_text.count("class='failure-row'") == 34
    assert "<script src=" not in main_text and "<script src=" not in failure_text
    for page, text in ((args.main_html, main_text), (args.failures_html, failure_text)):
        links = LinkParser()
        links.feed(text)
        for href in links.hrefs:
            assert not href.startswith(("http://", "https://")), href
            assert (page.parent / href).exists(), f"broken local link: {href}"

    result = {
        "status": "PASS",
        "input_rows": len(source),
        "result_rows": len(results),
        "ordered_id_match": True,
        "truth_label_match": True,
        "correct": correct,
        "errors": errors,
        "accuracy": correct / len(results),
        "m3_used": m3_used,
        "route_failures": route_failures,
        "failure_rows_in_html": 34,
        "input_sha256": sha256(args.input),
        "results_sha256": sha256(args.results),
        "main_html_sha256": sha256(args.main_html),
        "failures_html_sha256": sha256(args.failures_html),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
