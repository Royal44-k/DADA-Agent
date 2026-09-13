# -*- coding: utf-8 -*-
import json
import unittest

from fixture_state import EVAL_USER_ID, ensure_fixtures, verify_fixtures


class FixtureStateTests(unittest.TestCase):
    def test_fixture_creation_is_idempotent_and_keeps_bce_available(self):
        first = ensure_fixtures(EVAL_USER_ID)
        second = ensure_fixtures(EVAL_USER_ID)
        state = verify_fixtures(EVAL_USER_ID)

        self.assertEqual(2026082001, EVAL_USER_ID)
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertEqual(first["memory_id"], second["memory_id"])
        self.assertEqual(1, state["fixture_task_count"])
        self.assertEqual(1, state["fixture_memory_count"])
        self.assertGreaterEqual(state["active_task_count"], 1)
        self.assertGreaterEqual(state["active_memory_count"], 1)
        self.assertEqual([], state["narrow_absent"])
        self.assertEqual([], state["narrow_facts"])
        json.dumps(state, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
