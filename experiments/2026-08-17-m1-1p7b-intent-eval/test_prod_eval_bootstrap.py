# -*- coding: utf-8 -*-
"""Catch accidental imports from the stale 2026-08-17 evaluation tree."""
from pathlib import Path

import full_router_probe  # noqa: F401 - reproduces its m1_probe path mutation

try:
    from prod_eval_bootstrap import activate_production_path
except ImportError as exc:
    raise AssertionError("production evaluation bootstrap is missing") from exc


PRODUCTION_ROOT = Path(
    "/home/number/dada-runtime/asr-api-test-env/xiaozhi-server"
)


activate_production_path(PRODUCTION_ROOT)

from dada.mechanisms import m3_tool_panel  # noqa: E402


actual = Path(m3_tool_panel.__file__).resolve()
expected = (PRODUCTION_ROOT / "dada/mechanisms/m3_tool_panel.py").resolve()
assert actual == expected, f"loaded stale M3: {actual}; expected: {expected}"
print(f"PASS production M3 import: {actual}")
