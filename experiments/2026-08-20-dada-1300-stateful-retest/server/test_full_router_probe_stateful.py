# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import full_router_probe_stateful as probe


class FakeReply:
    content = "a"
    logprobs = []
    latency_ms = 1


class FakeLlm:
    def __init__(self):
        self.calls = []

    def classify_1p7b(self, messages, **kwargs):
        self.calls.append(messages)
        return FakeReply()

    def start_turn_recording(self):
        return None

    def drain_turn_recording(self):
        return [{"model_tier": "1.7b", "content": "a", "latency_ms": 1}]


class FakeGate:
    def __init__(self, llm):
        self.llm = llm
        self.user_ids = []

    def m1_classify(self, conn, text, messages):
        self.user_ids.append(conn.dada_user_id)
        self.llm.classify_1p7b(messages)
        return SimpleNamespace(ok=True, data={"label": "reminder_write"})


class FakeTaskDb:
    def __init__(self):
        self.calls = 0

    def list_active_tasks(self, user_id):
        self.calls += 1
        return []


class StatefulProbeTests(unittest.TestCase):
    def test_production_route_uses_numeric_fixture_user_without_task_monkeypatch(self):
        llm = FakeLlm()
        gate = FakeGate(llm)
        task_db = FakeTaskDb()
        original = task_db.list_active_tasks
        with patch.dict(os.environ, {"DADA_EVAL_USER_ID": "2026082001"}):
            routed = probe.production_route(
                {"text": "提醒我明天吃药"},
                [{"role": "user", "content": "提醒我明天吃药"}],
                llm_module=llm,
                gate_module=gate,
                task_db_module=task_db,
            )
        self.assertTrue(routed["result"].ok)
        self.assertEqual([2026082001], gate.user_ids)
        self.assertEqual(0, task_db.calls)
        self.assertEqual(original, task_db.list_active_tasks)

    def test_invalid_fixture_user_id_is_rejected_before_model_call(self):
        llm = FakeLlm()
        gate = FakeGate(llm)
        with patch.dict(os.environ, {"DADA_EVAL_USER_ID": "not-a-number"}):
            with self.assertRaisesRegex(ValueError, "DADA_EVAL_USER_ID"):
                probe.production_route(
                    {"text": "你好"}, [{"role": "user", "content": "你好"}],
                    llm_module=llm, gate_module=gate,
                    task_db_module=FakeTaskDb(),
                )
        self.assertEqual([], llm.calls)

    def test_main_preserves_corrected_input_order_when_resuming(self):
        rows = [
            {"sample_id": "a-00001-aaaaaaaaaaaa", "label": "a", "text": "第一条", "history": []},
            {"sample_id": "m-00002-bbbbbbbbbbbb", "label": "m", "text": "第二条", "history": []},
        ]
        completed = {
            rows[1]["sample_id"]: {"sample_id": rows[1]["sample_id"], "correct": True},
            rows[0]["sample_id"]: {"sample_id": rows[0]["sample_id"], "correct": True},
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "results.jsonl"
            probe.rewrite_in_sample_order(output, rows, completed)
            ids = [json.loads(line)["sample_id"] for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["sample_id"] for row in rows], ids)


if __name__ == "__main__":
    unittest.main()
