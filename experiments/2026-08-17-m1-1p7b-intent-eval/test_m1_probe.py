# -*- coding: utf-8 -*-
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import m1_probe
from m1_probe import (build_messages, evaluate_one, is_direct, load_completed,
                      normalize_label, parse_gate_stats, rewrite_in_sample_order)


def _logprobs(top1=0.99, second=0.005, token=" f"):
    return {
        "content": [{
            "token": token,
            "logprob": math.log(top1),
            "top_logprobs": [
                {"token": token, "logprob": math.log(top1)},
                {"token": " m", "logprob": math.log(second)},
                {"token": " g", "logprob": math.log(0.003)},
            ],
        }]
    }


def _sample(label="f"):
    return {
        "sample_id": f"{label}-00001-deadbeef",
        "source_file": f"{label}.jsonl",
        "source_line": 1,
        "label": label,
        "rounds": 2,
        "rounds_bucket": "2",
        "ctx": None,
        "hard_pair": "f/m",
        "history": [["user", "现在声音怎么样"], ["assistant", "当前音量是60"]],
        "text": "声音大一点",
        "asr_noise": False,
        "src": "gen",
        "stratum": "noise=false|rounds=2|hard=true",
    }


def test_normalize_label_rejects_non_single_label_output():
    """Catches accepting explanations or punctuation as an a-m class."""
    assert normalize_label(" A\n") == "a"
    assert normalize_label("m") == "m"
    assert normalize_label("a because") is None
    assert normalize_label("?") is None
    assert normalize_label("") is None
    assert normalize_label(None) is None


def test_parse_gate_stats_uses_raw_first_token_probabilities():
    """Catches renormalizing top5 or reading the wrong token position."""
    top1, margin, top = parse_gate_stats(_logprobs())
    assert math.isclose(top1, 0.99, rel_tol=1e-9)
    assert math.isclose(margin, 0.985, rel_tol=1e-9)
    assert [item["token"] for item in top] == [" f", " m", " g"]
    assert math.isclose(top[1]["prob"], 0.005, rel_tol=1e-9)
    assert parse_gate_stats(None) == (None, None, [])
    assert parse_gate_stats({"content": []}) == (None, None, [])


def test_is_direct_uses_strict_production_thresholds():
    """Catches >= replacing production's strict > comparisons."""
    threshold = 0.98055846
    assert is_direct(True, threshold + 1e-8, 0.1)
    assert not is_direct(True, threshold, 0.1)
    assert not is_direct(True, 0.99, 0.0)
    assert not is_direct(False, 0.99, 0.1)
    assert not is_direct(True, None, 0.1)


def test_build_messages_preserves_history_and_does_not_leak_metadata():
    """Catches dropping context or sending label/hard-pair metadata to 1.7B."""
    row = _sample()
    messages = build_messages(row, "生产分类提示词")
    assert messages == [
        {"role": "system", "content": "生产分类提示词"},
        {"role": "user", "content": "现在声音怎么样"},
        {"role": "assistant", "content": "当前音量是60"},
        {"role": "user", "content": "声音大一点"},
    ]
    serialized = json.dumps(messages, ensure_ascii=False)
    assert "f/m" not in serialized
    assert "f.jsonl" not in serialized
    assert "deadbeef" not in serialized


def test_evaluate_one_records_correct_direct_prediction():
    """Catches losing raw output, confidence, latency, or gate decisions."""
    row = _sample()
    calls = []

    def classify(messages):
        calls.append(messages)
        return SimpleNamespace(content=" f\n", logprobs=_logprobs(), latency_ms=123)

    result = evaluate_one(row, classify_func=classify, system_prompt="生产分类提示词")
    assert len(calls) == 1
    assert result["sample_id"] == row["sample_id"]
    assert result["truth"] == "f"
    assert result["raw_output"] == " f\n"
    assert result["prediction"] == "f"
    assert result["valid_label"] is True
    assert result["correct"] is True
    assert result["direct"] is True
    assert result["dangerous_misroute"] is False
    assert result["model_latency_ms"] == 123
    assert result["exception_type"] is None


def test_evaluate_one_marks_high_confidence_wrong_label_as_dangerous():
    """Catches a high-confidence f→m error being hidden as an ordinary miss."""
    row = _sample("f")

    def classify(_messages):
        return SimpleNamespace(content="m", logprobs=_logprobs(token=" m"), latency_ms=80)

    result = evaluate_one(row, classify_func=classify, system_prompt="生产分类提示词")
    assert result["prediction"] == "m"
    assert result["correct"] is False
    assert result["direct"] is True
    assert result["dangerous_misroute"] is True


def test_evaluate_one_records_exception_without_retrying():
    """Catches silent retries masking a failed model call."""
    row = _sample()
    attempts = 0

    def classify(_messages):
        nonlocal attempts
        attempts += 1
        raise TimeoutError("endpoint timed out")

    result = evaluate_one(row, classify_func=classify, system_prompt="生产分类提示词")
    assert attempts == 1
    assert result["prediction"] is None
    assert result["direct"] is False
    assert result["exception_type"] == "TimeoutError"
    assert "timed out" in result["exception_message"]


def test_checkpoint_loader_and_rewrite_follow_sample_order(tmp_path):
    """Catches duplicated calls or result order drifting after resume."""
    output = tmp_path / "results.jsonl"
    output.write_text(
        json.dumps({"sample_id": "b-2", "prediction": "b"}) + "\n" +
        json.dumps({"sample_id": "a-1", "prediction": "a"}) + "\n",
        encoding="utf-8")
    completed = load_completed(output)
    assert set(completed) == {"a-1", "b-2"}

    sample = [{"sample_id": "a-1"}, {"sample_id": "b-2"}]
    rewrite_in_sample_order(output, sample, completed)
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [row["sample_id"] for row in rows] == ["a-1", "b-2"]


def test_cli_imports_dada_from_isolation_parent(tmp_path):
    """Catches launching eval/m1_probe.py without its isolation root on sys.path."""
    root = tmp_path / "isolation"
    eval_dir = root / "eval"
    prompts_dir = root / "dada" / "infra" / "prompts"
    eval_dir.mkdir(parents=True)
    prompts_dir.mkdir(parents=True)
    for package in (root / "dada", root / "dada" / "infra", prompts_dir):
        (package / "__init__.py").write_text("", encoding="utf-8")
    (root / "dada" / "infra" / "llm.py").write_text(
        "def classify_1p7b(messages):\n    raise AssertionError('empty sample must not call model')\n",
        encoding="utf-8")
    (prompts_dir / "branch_prompts.py").write_text(
        "M1_CLASSIFIER_SYSTEM = 'production prompt'\n", encoding="utf-8")
    shutil.copy2(Path(m1_probe.__file__), eval_dir / "m1_probe.py")
    (eval_dir / "empty.jsonl").write_text("", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(eval_dir / "m1_probe.py"),
         "--input", str(eval_dir / "empty.jsonl"),
         "--output", str(eval_dir / "results.jsonl")],
        cwd=root, text=True, capture_output=True, check=False)

    assert completed.returncode == 0, completed.stderr
    assert (eval_dir / "results.jsonl").read_text(encoding="utf-8") == ""
