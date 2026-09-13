# -*- coding: utf-8 -*-
"""Keep isolated evaluation helpers while importing Dada from production."""
import sys
from pathlib import Path


def activate_production_path(project_root):
    loaded = [
        name for name in sys.modules
        if name == "dada" or name.startswith("dada.")
    ]
    if loaded:
        raise RuntimeError(
            "activate_production_path must run before importing dada modules"
        )
    root = str(Path(project_root).resolve())
    sys.path[:] = [entry for entry in sys.path if entry != root]
    sys.path.insert(0, root)
    return root
