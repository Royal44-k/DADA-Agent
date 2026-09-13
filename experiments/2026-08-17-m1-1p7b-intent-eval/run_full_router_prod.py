# -*- coding: utf-8 -*-
"""Run the isolated full-router evaluator against the production code tree."""
from pathlib import Path

import full_router_probe
from prod_eval_bootstrap import activate_production_path


PRODUCTION_ROOT = Path(
    "/home/number/dada-runtime/asr-api-test-env/xiaozhi-server"
)


activate_production_path(PRODUCTION_ROOT)

from dada.mechanisms import m3_tool_panel  # noqa: E402


if __name__ == "__main__":
    print(f"PRODUCTION_M3={Path(m3_tool_panel.__file__).resolve()}", flush=True)
    full_router_probe.main()
