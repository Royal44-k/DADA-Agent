# -*- coding: utf-8 -*-
"""在不修改生产代码的前提下加载生产 Dada 包并运行状态版评测器。"""
import os

from prod_eval_bootstrap import activate_production_path


PRODUCTION_ROOT = "/home/number/dada-runtime/asr-api-test-env/xiaozhi-server"


def main():
    activate_production_path(PRODUCTION_ROOT)
    import full_router_probe_base
    import full_router_probe_stateful

    # 基线模块的 main 会按其全局 evaluate_route 调用；只替换评测入口，不改生产包。
    full_router_probe_base.evaluate_route = full_router_probe_stateful.evaluate_route
    print({
        "production_root": PRODUCTION_ROOT,
        "eval_user_id": int(os.environ.get("DADA_EVAL_USER_ID", "2026082001")),
        "state_mode": "real_database",
    }, flush=True)
    full_router_probe_base.main()


if __name__ == "__main__":
    main()
