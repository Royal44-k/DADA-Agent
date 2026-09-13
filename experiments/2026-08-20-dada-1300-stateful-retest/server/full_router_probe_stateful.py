# -*- coding: utf-8 -*-
"""用真实数据库状态复测生产 M1→M3 最终分支路由。"""
import os
from types import SimpleNamespace

from full_router_probe_base import (
    LABEL_MAP,
    REVERSE_LABEL_MAP,
    build_flow_messages,
    evaluate_route as _evaluate_route,
    main,
)
from m1_probe import rewrite_in_sample_order


DEFAULT_EVAL_USER_ID = 2026082001


def eval_user_id():
    raw = os.environ.get("DADA_EVAL_USER_ID", str(DEFAULT_EVAL_USER_ID))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("DADA_EVAL_USER_ID 必须是正整数") from exc
    if value <= 0:
        raise ValueError("DADA_EVAL_USER_ID 必须是正整数")
    return value


def production_route(row, messages, llm_module=None, gate_module=None,
                     task_db_module=None, conn=None):
    """调用真实生产门控；不替换 task/memory 查询，不伪造用户状态。"""
    if llm_module is None or gate_module is None:
        from dada.infra import llm as production_llm
        from dada.mechanisms import m1_gate as production_gate
        llm_module = llm_module or production_llm
        gate_module = gate_module or production_gate

    # 参数保留用于兼容测试注入，但生产路径绝不读写或 monkeypatch 数据库模块。
    del task_db_module
    conn = conn or SimpleNamespace(dada_user_id=eval_user_id())
    if not isinstance(conn.dada_user_id, int) or conn.dada_user_id <= 0:
        raise ValueError("DADA_EVAL_USER_ID 必须是正整数")

    original_classifier = llm_module.classify_1p7b
    captured = {}
    calls = None

    def capture_classifier(classifier_messages, **kwargs):
        reply = original_classifier(classifier_messages, **kwargs)
        captured["reply"] = reply
        return reply

    llm_module.classify_1p7b = capture_classifier
    llm_module.start_turn_recording()
    try:
        result = gate_module.m1_classify(conn, row["text"], messages)
        calls = llm_module.drain_turn_recording()
        return {
            "result": result,
            "m1_reply": captured.get("reply"),
            "calls": calls or [],
        }
    finally:
        if calls is None:
            llm_module.drain_turn_recording()
        llm_module.classify_1p7b = original_classifier


def evaluate_route(row):
    return _evaluate_route(row, route_func=production_route)


if __name__ == "__main__":
    main()
