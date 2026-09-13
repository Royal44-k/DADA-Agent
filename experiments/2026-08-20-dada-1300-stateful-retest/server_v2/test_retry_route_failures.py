# -*- coding: utf-8 -*-
import unittest

import retry_route_failures as retry


class RetryRouteFailuresTests(unittest.TestCase):
    def test_retry_input_contains_only_infrastructure_failures_in_source_order(self):
        source = [{"sample_id": "a"}, {"sample_id": "b"}, {"sample_id": "c"}]
        results = [
            {"sample_id": "a", "route_ok": True, "exception_type": None, "correct": True},
            {"sample_id": "b", "route_ok": False, "exception_type": None, "correct": False},
            {"sample_id": "c", "route_ok": True, "exception_type": None, "correct": False},
        ]
        selected = retry.select_retry_rows(source, results)
        self.assertEqual(["b"], [row["sample_id"] for row in selected])

    def test_merge_replaces_only_route_failure_and_preserves_first_attempt(self):
        initial = [
            {"sample_id": "a", "route_ok": False, "exception_type": None,
             "correct": False, "prediction": None, "wall_latency_ms": 100},
            {"sample_id": "b", "route_ok": True, "exception_type": None,
             "correct": False, "prediction": "m", "wall_latency_ms": 20},
        ]
        retry_rows = [
            {"sample_id": "a", "route_ok": True, "exception_type": None,
             "correct": True, "prediction": "a", "wall_latency_ms": 30},
        ]
        merged, audit = retry.merge_results(initial, retry_rows)
        self.assertTrue(merged[0]["correct"])
        self.assertTrue(merged[0]["infra_retry"]["attempted"])
        self.assertFalse(merged[0]["infra_retry"]["first_route_ok"])
        self.assertEqual("m", merged[1]["prediction"])
        self.assertEqual(1, audit["retried"])
        self.assertEqual(1, audit["recovered"])

    def test_merge_rejects_retrying_an_ordinary_classification_error(self):
        initial = [{"sample_id": "x", "route_ok": True, "exception_type": None,
                    "correct": False, "prediction": "m"}]
        with self.assertRaisesRegex(ValueError, "retry IDs"):
            retry.merge_results(initial, [{"sample_id": "x", "route_ok": True,
                                           "correct": True, "prediction": "a"}])


if __name__ == "__main__":
    unittest.main()
