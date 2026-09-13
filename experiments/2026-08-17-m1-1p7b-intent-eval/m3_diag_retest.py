# -*- coding: utf-8 -*-
"""Isolated diagnostic entry point for the 2026-08-18 M3 retest."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import full_router_probe
from prod_eval_bootstrap import activate_production_path


SAMPLE_PATH = Path(
    "/home/number/dada-runtime/asr-api-test-env/"
    "xiaozhi-server-m1-intent-eval-20260817/eval/"
    "smoke-full-router-13.jsonl"
)
PRODUCTION_ROOT = Path(
    "/home/number/dada-runtime/asr-api-test-env/xiaozhi-server"
)


activate_production_path(PRODUCTION_ROOT)

from dada.infra import llm  # noqa: E402
from dada.mechanisms import m3_tool_panel as m3  # noqa: E402


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else "e"
    rows = [
        json.loads(line)
        for line in SAMPLE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    row = next(item for item in rows if item["label"] == label)
    original_post = llm.requests.post

    def traced_post(*args, **kwargs):
        response = original_post(*args, **kwargs)
        print(
            "HTTP_DIAG "
            f"status={response.status_code} "
            f"body={response.text[:2000]!r}",
            file=sys.stderr,
            flush=True,
        )
        return response

    llm.requests.post = traced_post
    m3.task_db.list_active_tasks = lambda _user_id: [{"task_id": 1}]
    result = m3.m3_select(
        SimpleNamespace(dada_user_id="m3-retest-diag"),
        "m3-retest-diag",
        full_router_probe.build_flow_messages(row),
    )
    print(result)


if __name__ == "__main__":
    main()
