# -*- coding: utf-8 -*-
"""Collect immutable evidence that the stateful production route is testable."""
import argparse
import hashlib
import json
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from fixture_state import EVAL_USER_ID, ensure_fixtures, verify_fixtures


PRODUCTION_ROOT = Path("/home/number/dada-runtime/asr-api-test-env/xiaozhi-server")
PRODUCTION_FILES = {
    "m1_gate": PRODUCTION_ROOT / "dada/mechanisms/m1_gate.py",
    "m3_tool_panel": PRODUCTION_ROOT / "dada/mechanisms/m3_tool_panel.py",
    "branch_prompts": PRODUCTION_ROOT / "dada/infra/prompts/branch_prompts.py",
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tcp_check(host, port, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"ok": True, "host": host, "port": port}
    except OSError as exc:
        return {"ok": False, "host": host, "port": port,
                "error": f"{type(exc).__name__}: {exc}"}


def http_check(host, port):
    attempts = []
    for endpoint in ("/health", "/v1/models"):
        url = f"http://{host}:{port}{endpoint}"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                body = response.read(300).decode("utf-8", errors="replace")
                item = {"ok": 200 <= response.status < 300, "url": url,
                        "status": response.status, "body_prefix": body}
                attempts.append(item)
                if item["ok"]:
                    return {"ok": True, "attempts": attempts}
        except (OSError, urllib.error.URLError) as exc:
            attempts.append({"ok": False, "url": url,
                             "error": f"{type(exc).__name__}: {exc}"})
    return {"ok": False, "attempts": attempts}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    ensure_fixtures(EVAL_USER_ID)
    state = verify_fixtures(EVAL_USER_ID)
    from dada.mechanisms import m3_tool_panel
    available = sorted(
        tool["function"]["name"]
        for tool in m3_tool_panel._build_tools(set(state["narrow_absent"]))
    )
    checks = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "eval_user_id": EVAL_USER_ID,
        "input": {"path": str(args.input), "sha256": sha256(args.input)},
        "fixture_state": state,
        "available_tools": available,
        "required_stateful_tools": {
            name: name in available
            for name in ("reminder_modify", "reminder_query", "memory_query")
        },
        "agent_ports": [tcp_check("127.0.0.1", port) for port in (8010, 8013)],
        "model_endpoints": {
            "1.7b": http_check("192.168.5.37", 45200),
            "9b": http_check("192.168.5.37", 45201),
        },
        "production_sha256": {
            name: sha256(path) for name, path in PRODUCTION_FILES.items()
        },
    }
    args.output.write_text(
        json.dumps(checks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(checks, ensure_ascii=False))

    required = list(checks["required_stateful_tools"].values())
    healthy = (
        state["fixture_task_count"] == 1
        and state["fixture_memory_count"] == 1
        and all(required)
        and all(item["ok"] for item in checks["agent_ports"])
        and all(item["ok"] for item in checks["model_endpoints"].values())
    )
    if not healthy:
        raise SystemExit("preflight failed; see output JSON")


if __name__ == "__main__":
    main()
