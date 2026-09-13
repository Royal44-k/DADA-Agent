# -*- coding: utf-8 -*-
"""Idempotent database fixtures for the 2026-08-20 stateful router retest."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PRODUCTION_ROOT = Path(
    "/home/number/dada-runtime/asr-api-test-env/xiaozhi-server"
)
EVAL_USER_ID = 2026082001
TASK_CONTENT = "Codex复测提醒：2026年8月21日上午9点复查路由结果"
MEMORY_CONTENT = "Codex复测记忆：车辆停在B2层测试车位"

if str(PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(PRODUCTION_ROOT))

from dada.infra.db import base  # noqa: E402
from dada.infra.db import memory as memory_db  # noqa: E402
from dada.infra.db import task as task_db  # noqa: E402
from dada.mechanisms import m3_tool_panel  # noqa: E402


def _fixture_task_rows(user_id: int):
    return base.query(
        "SELECT id FROM agent_task WHERE user_id=%s AND content=%s "
        "AND status='active' ORDER BY id",
        (int(user_id), TASK_CONTENT),
    )


def _fixture_memory_rows(user_id: int):
    return base.query(
        "SELECT id FROM agent_memory WHERE user_id=%s AND content=%s "
        "AND importance>0 ORDER BY id",
        (int(user_id), MEMORY_CONTENT),
    )


def ensure_fixtures(user_id: int = EVAL_USER_ID):
    """Create exactly one active task and memory for the dedicated test user."""
    user_id = int(user_id)
    task_rows = _fixture_task_rows(user_id)
    if not task_rows:
        task = task_db.insert_task(
            user_id,
            {
                "task_type": "reminder",
                "content": TASK_CONTENT,
                "original_text": TASK_CONTENT,
                "recurrence_type": "once",
                "materialize_mode": "llm",
                "next_trigger_time": "2099-08-21 09:00:00",
                "status": "active",
                "context": {"fixture": True, "batch": "intent-eval-20260820"},
            },
        )
        task_id = int(task["id"])
    else:
        task_id = int(task_rows[0]["id"])

    memory_rows = _fixture_memory_rows(user_id)
    if not memory_rows:
        memory = memory_db.insert_memory(
            user_id,
            {
                "category": "fact",
                "content": MEMORY_CONTENT,
                "keywords": "Codex,复测,车辆,B2,测试车位",
                "importance": 5,
                "access_count": 1,
                "source": "explicit",
                "original_text": MEMORY_CONTENT,
                "source_session_id": "intent-eval-20260820",
                "vector_synced": 1,
            },
        )
        memory_id = int(memory["id"])
    else:
        memory_id = int(memory_rows[0]["id"])

    return {"user_id": user_id, "task_id": task_id, "memory_id": memory_id}


def verify_fixtures(user_id: int = EVAL_USER_ID):
    user_id = int(user_id)
    fixture_tasks = _fixture_task_rows(user_id)
    fixture_memories = _fixture_memory_rows(user_id)
    absent, facts = m3_tool_panel._narrow_state(user_id)
    return {
        "user_id": user_id,
        "fixture_task_count": len(fixture_tasks),
        "fixture_memory_count": len(fixture_memories),
        "task_id": int(fixture_tasks[0]["id"]) if fixture_tasks else None,
        "memory_id": int(fixture_memories[0]["id"]) if fixture_memories else None,
        "active_task_count": len(task_db.list_active_tasks(user_id)),
        "active_memory_count": int(memory_db.count_active(user_id)),
        "narrow_absent": sorted(absent),
        "narrow_facts": list(facts),
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def main():
    ensure_fixtures(EVAL_USER_ID)
    state = verify_fixtures(EVAL_USER_ID)
    Path("fixture-state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
    main()
