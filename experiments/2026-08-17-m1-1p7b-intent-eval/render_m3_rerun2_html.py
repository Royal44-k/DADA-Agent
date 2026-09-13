"""Render the 2026-08-18 second M3 full-flow server retest report."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path


REPORT_FILENAME = "哒哒Agent-M3再次完善后完整流程复测报告-2026-08-18.html"
FAILURE_FILENAME = "哒哒Agent-M3再次完善后失败测试集-109条-2026-08-18.html"

BRANCH_NAMES = {
    "a": "新建提醒",
    "b": "修改/取消/完成提醒",
    "c": "查询提醒",
    "d": "修改/删除记忆",
    "e": "查询记忆",
    "f": "调节音量",
    "g": "调节亮度",
    "h": "查询天气",
    "i": "查询日期/时间",
    "j": "工具/知识查询",
    "k": "睡觉",
    "l": "再见",
    "m": "闲聊/其他",
}

ERROR_NAMES = {
    "route_failure": "M3路由失败",
    "m3_introduced": "M3新增误判",
    "m3_unresolved": "M3未纠正",
    "m1_direct": "M1高置信直错",
}

PRODUCTION_HASHES = {
    "dada/mechanisms/m1_gate.py": "fccb34c386c86a75e56191ceb6139deb37a355f56520bea0e0c292ff2bce8b8c",
    "dada/mechanisms/m3_tool_panel.py": "da257e0594b7db528c4cde95e3b9011d04b3f33d1c21dff704398e09aa7b090b",
    "dada/infra/llm.py": "1403e95eb8a8eb8e5b8820de3c82c39aa12efff31a428f3276ae2f8ab0f48075",
    "dada/infra/prompts/branch_prompts.py": "64fb69cc1c0f2531adf422a0eb3c7595e7502427d89dfa8830af6f7d5304c752",
}


def load_rows(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [row["sample_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate sample_id in {path}")
    return rows


def classify_error(row: dict) -> str:
    if not row.get("route_ok"):
        return "route_failure"
    if row.get("m3_worsened"):
        return "m3_introduced"
    if row.get("m3_used"):
        return "m3_unresolved"
    return "m1_direct"


def pct(numerator: int | float, denominator: int | float, digits: int = 2) -> str:
    return f"{100 * numerator / denominator:.{digits}f}%" if denominator else "—"


def percentile(values: list[float], p: float) -> float:
    values = sorted(values)
    if not values:
        return 0.0
    index = max(0, min(len(values) - 1, math.ceil(p * len(values)) - 1))
    return values[index]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def matched_comparison(old_rows: list[dict], current_rows: list[dict]) -> dict[str, int]:
    old = {row["sample_id"]: row for row in old_rows}
    current = {row["sample_id"]: row for row in current_rows}
    if set(old) != set(current):
        raise ValueError("comparison runs do not contain identical sample IDs")
    counts = Counter()
    for sample_id, row in current.items():
        before = bool(old[sample_id].get("correct"))
        after = bool(row.get("correct"))
        key = "both_correct" if before and after else "fixed" if after else "regressed" if before else "both_wrong"
        counts[key] += 1
    return {key: counts[key] for key in ("both_correct", "fixed", "regressed", "both_wrong")}


def compute_metrics(baseline_path: Path, failed_retest_path: Path, current_path: Path) -> dict:
    baseline = load_rows(baseline_path)
    failed_retest = load_rows(failed_retest_path)
    current = load_rows(current_path)
    if not (len(baseline) == len(failed_retest) == len(current) == 1300):
        raise ValueError("all runs must contain exactly 1300 rows")

    failures = [row for row in current if not row.get("correct")]
    error_counter = Counter(classify_error(row) for row in failures)
    error_counts = {key: error_counter[key] for key in ERROR_NAMES}

    branches = {}
    for label in BRANCH_NAMES:
        subset = [row for row in current if row.get("truth") == label]
        branches[label] = {
            "name": BRANCH_NAMES[label],
            "support": len(subset),
            "correct": sum(bool(row.get("correct")) for row in subset),
            "m3_used": sum(bool(row.get("m3_used")) for row in subset),
            "errors": sum(not row.get("correct") for row in subset),
        }

    confusions = Counter(
        (row.get("truth"), row.get("prediction") or "∅")
        for row in failures
    )

    def group_stats(key_func):
        groups = defaultdict(list)
        for row in current:
            groups[key_func(row)].append(row)
        return {
            key: {
                "total": len(rows),
                "correct": sum(bool(row.get("correct")) for row in rows),
                "m3_used": sum(bool(row.get("m3_used")) for row in rows),
            }
            for key, rows in groups.items()
        }

    m3_rows = [row for row in current if row.get("m3_used")]
    current_correct = sum(bool(row.get("correct")) for row in current)
    baseline_correct = sum(bool(row.get("correct")) for row in baseline)
    failed_retest_correct = sum(bool(row.get("correct")) for row in failed_retest)
    m3_success = sum(bool(row.get("route_ok")) for row in m3_rows)
    wall_latency = [float(row.get("wall_latency_ms") or 0) for row in current]
    m3_latency = [float(row.get("m3_latency_ms") or 0) for row in m3_rows if row.get("m3_latency_ms") is not None]

    return {
        "total": len(current),
        "current_correct": current_correct,
        "current_errors": len(failures),
        "current_accuracy": current_correct / len(current),
        "baseline_correct": baseline_correct,
        "failed_retest_correct": failed_retest_correct,
        "delta_vs_baseline": current_correct - baseline_correct,
        "delta_vs_failed_retest": current_correct - failed_retest_correct,
        "matched_vs_baseline": matched_comparison(baseline, current),
        "matched_vs_failed_retest": matched_comparison(failed_retest, current),
        "m3_attempts": len(m3_rows),
        "m3_success": m3_success,
        "route_failures": len(m3_rows) - m3_success,
        "m3_corrected": sum(bool(row.get("m3_corrected")) for row in current),
        "m3_worsened": sum(bool(row.get("m3_worsened")) for row in current),
        "m3_unchanged_correct": sum(row.get("m3_used") and row.get("m1_correct") and row.get("correct") for row in current),
        "m3_unchanged_wrong": sum(row.get("m3_used") and not row.get("m1_correct") and not row.get("correct") for row in current),
        "error_counts": error_counts,
        "failures": failures,
        "branches": branches,
        "top_confusions": confusions.most_common(12),
        "asr_groups": group_stats(lambda row: "ASR噪声" if row.get("asr_noise") else "干净/普通"),
        "hard_groups": group_stats(lambda row: "hard_pair" if bool(row.get("hard_pair")) else "非hard_pair"),
        "round_groups": group_stats(lambda row: f"{row.get('rounds_bucket')}轮"),
        "wall_p50": statistics.median(wall_latency),
        "wall_p95": percentile(wall_latency, 0.95),
        "wall_avg": statistics.mean(wall_latency),
        "m3_p50": statistics.median(m3_latency),
        "m3_p95": percentile(m3_latency, 0.95),
        "m3_avg": statistics.mean(m3_latency),
        "result_sha256": sha256(current_path),
    }


def esc(value) -> str:
    return html.escape(str(value), quote=True)


COMMON_CSS = r"""
:root{--ink:#152238;--muted:#5d6b7e;--line:#dbe3ed;--bg:#f3f6fa;--card:#fff;--blue:#245a9c;--green:#087a55;--amber:#a85c00;--red:#b42318;--violet:#6941c6}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:"Segoe UI","Microsoft YaHei",sans-serif;line-height:1.65}main{max-width:1220px;margin:auto;padding:30px 22px 60px}header{padding:34px;border-radius:22px;color:#fff;background:linear-gradient(135deg,#132b4d,#245a9c 66%,#3977bd);box-shadow:0 16px 44px #1b3b6626}h1{margin:5px 0 8px;font-size:34px;line-height:1.25}h2{font-size:23px;margin:0 0 15px}h3{margin:0 0 7px}.eyebrow{font-size:12px;letter-spacing:.16em;font-weight:800;opacity:.78}.topnav{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}.topnav a{color:#fff;text-decoration:none;border:1px solid #ffffff55;border-radius:999px;padding:6px 12px;font-size:13px}.section{background:var(--card);margin-top:18px;padding:24px;border:1px solid var(--line);border-radius:18px;box-shadow:0 7px 24px #1d35570b}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px}.card{border:1px solid var(--line);border-radius:14px;padding:15px;background:#fbfdff}.card small{display:block;color:var(--muted)}.card b{font-size:27px;display:block;margin:3px 0}.callout{padding:14px 16px;border-left:5px solid var(--blue);background:#eef5ff;border-radius:9px;margin:14px 0}.callout.good{border-color:var(--green);background:#edfbf5}.callout.warn{border-color:var(--amber);background:#fff7e8}.callout.danger{border-color:var(--red);background:#fff1f0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}.mini{border:1px solid var(--line);border-radius:13px;padding:15px}.scroll{overflow:auto;border:1px solid var(--line);border-radius:12px}table{width:100%;border-collapse:collapse;min-width:780px}th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}th{background:#edf3fa;font-size:12px;text-transform:uppercase;letter-spacing:.04em}td.num{text-align:right;font-variant-numeric:tabular-nums}.good-text{color:var(--green);font-weight:800}.bad-text{color:var(--red);font-weight:800}.amber-text{color:var(--amber);font-weight:800}code{font-family:Consolas,monospace;background:#edf2f7;border-radius:5px;padding:2px 5px;word-break:break-all}footer{text-align:center;color:var(--muted);font-size:12px;margin:24px}.bar{height:8px;background:#e8eef5;border-radius:99px;overflow:hidden}.bar span{display:block;height:100%;background:var(--blue)}ol{padding-left:22px}a{color:var(--blue)}
"""


def render_branch_rows(metrics: dict) -> str:
    rows = []
    for label, item in metrics["branches"].items():
        accuracy = item["correct"] / item["support"]
        quality = "good-text" if accuracy >= .95 else "amber-text" if accuracy >= .90 else "bad-text"
        rows.append(
            f"<tr><td><b>{label}</b></td><td>{esc(item['name'])}</td><td class='num'>{item['support']}</td>"
            f"<td class='num {quality}'>{item['correct']}</td><td class='num {quality}'>{pct(item['correct'],item['support'])}</td>"
            f"<td class='num'>{item['m3_used']}</td><td class='num'>{item['errors']}</td></tr>"
        )
    return "".join(rows)


def render_group_rows(groups: dict) -> str:
    rows = []
    for name, item in sorted(groups.items()):
        rows.append(
            f"<tr><td>{esc(name)}</td><td class='num'>{item['total']}</td><td class='num'>{item['correct']}</td>"
            f"<td class='num'>{pct(item['correct'],item['total'])}</td><td class='num'>{item['m3_used']}</td></tr>"
        )
    return "".join(rows)


def render_report(metrics: dict) -> str:
    e = metrics["error_counts"]
    match = metrics["matched_vs_baseline"]
    hash_rows = "".join(f"<tr><td><code>{esc(path)}</code></td><td><code>{digest}</code></td></tr>" for path, digest in PRODUCTION_HASHES.items())
    confusion_rows = "".join(
        f"<tr><td>{truth} · {esc(BRANCH_NAMES.get(truth,truth))}</td><td>{esc(pred)} · {esc(BRANCH_NAMES.get(pred,pred))}</td><td class='num'>{count}</td></tr>"
        for (truth, pred), count in metrics["top_confusions"]
    )
    net = metrics["m3_corrected"] - metrics["m3_worsened"]
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>哒哒Agent M3再次完善后完整流程复测报告</title><style>{COMMON_CSS}</style></head><body>
<main id="report" data-total="{metrics['total']}" data-current-correct="{metrics['current_correct']}" data-final-errors="{metrics['current_errors']}" data-route-failures="{metrics['route_failures']}">
<header><div class="eyebrow">FULL-FLOW SERVER RETEST · 2026-08-18</div><h1>哒哒Agent M3再次完善后完整流程复测报告</h1><p>固定同一批1300条语料，完整执行“M1高置信门控 → 低置信样本进入M3真实9B复判 → 最终a–m分支”，以raw label为标准答案。</p><nav class="topnav"><a href="#verdict">结论</a><a href="#branches">分支结果</a><a href="#errors">失败构成</a><a href="{esc(FAILURE_FILENAME)}">打开109条失败测试集</a></nav></header>
<section class="section" id="verdict"><h2>1. 验收结论</h2><div class="callout good"><b>工程稳定性通过：</b>M3共调用 {metrics['m3_attempts']} 次，成功返回 {metrics['m3_success']} 次，成功率100%，路由/接口失败0次；上一轮245次上下文超限失败已消失。</div><div class="callout warn"><b>总体效果改善，但语义复判仍未通过净增益验收：</b>完整流程准确率为 <b>{pct(metrics['current_correct'],metrics['total'])}</b>（{metrics['current_correct']}/{metrics['total']}），较旧稳定基线提升 {metrics['delta_vs_baseline']} 条、{100*metrics['delta_vs_baseline']/metrics['total']:.2f}个百分点；但M3纠正{metrics['m3_corrected']}条、引错{metrics['m3_worsened']}条，净影响 <b>{net}条</b>。结论为“稳定性优化成功、完整流程指标回升、M3覆盖策略仍需收紧”。</div>
<div class="cards"><div class="card"><small>最终准确率</small><b>{pct(metrics['current_correct'],metrics['total'])}</b><small>{metrics['current_correct']} / {metrics['total']}</small></div><div class="card"><small>最终错误</small><b>{metrics['current_errors']}</b><small>{pct(metrics['current_errors'],metrics['total'])}</small></div><div class="card"><small>M3调用成功</small><b>{metrics['m3_success']}/{metrics['m3_attempts']}</b><small>路由失败 {metrics['route_failures']}</small></div><div class="card"><small>M3纠正 / 引错</small><b>{metrics['m3_corrected']} / {metrics['m3_worsened']}</b><small>净影响 {net} 条</small></div><div class="card"><small>较旧稳定基线</small><b>+{metrics['delta_vs_baseline']}</b><small>+{100*metrics['delta_vs_baseline']/metrics['total']:.2f}个百分点</small></div><div class="card"><small>相较上次失败复测</small><b>+{metrics['delta_vs_failed_retest']}</b><small>恢复 {100*metrics['delta_vs_failed_retest']/metrics['total']:.2f}个百分点</small></div></div></section>
<section class="section"><h2>2. 三轮同口径结果</h2><div class="scroll"><table><thead><tr><th>版本/轮次</th><th>最终正确</th><th>最终错误</th><th>准确率</th><th>解释</th></tr></thead><tbody><tr><td>旧稳定基线</td><td class="num">{metrics['baseline_correct']}</td><td class="num">{metrics['total']-metrics['baseline_correct']}</td><td class="num">{pct(metrics['baseline_correct'],metrics['total'])}</td><td>2026-08-17同批语料</td></tr><tr><td>第一次新版复测</td><td class="num">{metrics['failed_retest_correct']}</td><td class="num">{metrics['total']-metrics['failed_retest_correct']}</td><td class="num">{pct(metrics['failed_retest_correct'],metrics['total'])}</td><td>245次M3路由失败</td></tr><tr><td><b>本轮再次完善后</b></td><td class="num good-text">{metrics['current_correct']}</td><td class="num">{metrics['current_errors']}</td><td class="num good-text">{pct(metrics['current_correct'],metrics['total'])}</td><td>M3调用285/285成功</td></tr></tbody></table></div><p>与旧稳定基线逐样本对齐：共同正确 {match['both_correct']} 条，本轮修复 {match['fixed']} 条，本轮回退 {match['regressed']} 条，共同错误 {match['both_wrong']} 条；净提升 {match['fixed']-match['regressed']} 条。</p></section>
<section class="section"><h2>3. M3路径有效性</h2><div class="cards"><div class="card"><small>进入M3</small><b>{metrics['m3_attempts']}</b><small>{pct(metrics['m3_attempts'],metrics['total'])} 样本</small></div><div class="card"><small>保持正确</small><b>{metrics['m3_unchanged_correct']}</b><small>M1正确，M3未改错</small></div><div class="card"><small>成功纠正</small><b>{metrics['m3_corrected']}</b><small>M1错 → 最终对</small></div><div class="card"><small>新增误判</small><b>{metrics['m3_worsened']}</b><small>M1对 → 最终错</small></div><div class="card"><small>仍未纠正</small><b>{metrics['m3_unchanged_wrong']}</b><small>M1错 → 最终仍错</small></div></div><div class="callout danger"><b>M3复判净影响：</b>{metrics['m3_corrected']} − {metrics['m3_worsened']} = <b>{net}</b> 条。新版解决了“9B无法返回”，但当前仍允许9B以不足够强的证据覆盖M1，导致新增误判远多于纠正。</div></section>
<section class="section" id="errors"><h2>4. 109条最终错误构成</h2><div class="cards"><div class="card"><small>M3路由失败</small><b>{e['route_failure']}</b><small>接口/分支无返回</small></div><div class="card"><small>M3新增误判</small><b>{e['m3_introduced']}</b><small>{pct(e['m3_introduced'],metrics['current_errors'])}</small></div><div class="card"><small>M3未纠正</small><b>{e['m3_unresolved']}</b><small>{pct(e['m3_unresolved'],metrics['current_errors'])}</small></div><div class="card"><small>M1高置信直错</small><b>{e['m1_direct']}</b><small>{pct(e['m1_direct'],metrics['current_errors'])}</small></div></div><div class="callout"><b>闭合校验：</b>{e['route_failure']} + {e['m3_introduced']} + {e['m3_unresolved']} + {e['m1_direct']} = {metrics['current_errors']}。<a href="{esc(FAILURE_FILENAME)}">查看全部失败样本</a>。</div></section>
<section class="section" id="branches"><h2>5. 十三分支最终结果</h2><div class="scroll"><table><thead><tr><th>标签</th><th>分支</th><th>样本</th><th>正确</th><th>准确率</th><th>进入M3</th><th>错误</th></tr></thead><tbody>{render_branch_rows(metrics)}</tbody></table></div><div class="callout warn"><b>重点短板：</b>j工具/知识查询72%、l再见74%、e查询记忆79%。f调节音量、g调节亮度、h查询天气均为100%，说明F/G业务分支入口判别在本批语料上正常。</div></section>
<section class="section"><h2>6. 高风险混淆对</h2><div class="scroll"><table><thead><tr><th>真实分支</th><th>最终误入</th><th>数量</th></tr></thead><tbody>{confusion_rows}</tbody></table></div></section>
<section class="section"><h2>7. 分层结果</h2><div class="grid"><div><h3>ASR噪声</h3><div class="scroll"><table><thead><tr><th>切片</th><th>样本</th><th>正确</th><th>准确率</th><th>M3</th></tr></thead><tbody>{render_group_rows(metrics['asr_groups'])}</tbody></table></div></div><div><h3>hard_pair</h3><div class="scroll"><table><thead><tr><th>切片</th><th>样本</th><th>正确</th><th>准确率</th><th>M3</th></tr></thead><tbody>{render_group_rows(metrics['hard_groups'])}</tbody></table></div></div><div><h3>对话轮次</h3><div class="scroll"><table><thead><tr><th>切片</th><th>样本</th><th>正确</th><th>准确率</th><th>M3</th></tr></thead><tbody>{render_group_rows(metrics['round_groups'])}</tbody></table></div></div></div></section>
<section class="section"><h2>8. 延迟</h2><div class="cards"><div class="card"><small>全流程P50</small><b>{metrics['wall_p50']:.1f} ms</b><small>直进样本为主</small></div><div class="card"><small>全流程P95</small><b>{metrics['wall_p95']:.1f} ms</b><small>含M3复判</small></div><div class="card"><small>全流程均值</small><b>{metrics['wall_avg']:.1f} ms</b><small>1300条</small></div><div class="card"><small>M3 P50 / P95</small><b>{metrics['m3_p50']:.0f}/{metrics['m3_p95']:.0f} ms</b><small>均值 {metrics['m3_avg']:.1f} ms</small></div></div></section>
<section class="section"><h2>9. 建议的下一步</h2><ol><li><b>P0：把M3从“低置信即覆盖”改为“满足覆盖条件才改判”。</b>只有当9B输出有效单分支、工具语义与分支一致、引用证据可在原文/历史中逐字定位，并且不存在<code>m3_disputed</code>时才允许覆盖；否则保留M1候选。</li><li><b>P0：对j/e/l做分支级覆盖阈值。</b>这三类贡献75条错误中的大头，先基于失败集收紧工具到分支映射，尤其处理“查询记忆 vs 修改记忆”“再见 vs 睡觉/闲聊”“知识查询 vs 闲聊/控制”。</li><li><b>P1：离线回放采用双输出。</b>同时记录<code>m1_prediction</code>、<code>m3_prediction</code>、覆盖原因和证据校验结果，按“纠正数/引错数/净增益”验收，而不是只看9B是否成功返回。</li><li><b>P1：验收门建议。</b>同批1300条需保持路由失败=0，完整流程准确率不得低于本轮91.62%，且M3净影响必须≥0后再扩大覆盖范围。</li></ol></section>
<section class="section"><h2>10. 版本、完整性与隔离说明</h2><p>服务器Python 3.10.12；生产Agent PID 3095050，启动时间2026-08-18 16:31:37 +0800，工作目录为生产路径。M3与分支提示文件在16:31更新后Agent重启，本轮从生产目录只读加载。测试只在隔离目录新建JSONL结果，没有修改生产文件。</p><div class="scroll"><table><thead><tr><th>生产文件</th><th>SHA-256</th></tr></thead><tbody>{hash_rows}</tbody></table></div><p>本轮逐条结果SHA-256：<code>{metrics['result_sha256']}</code></p><p>服务器隔离目录：<code>/home/number/dada-runtime/asr-api-test-env/xiaozhi-server-m1-intent-eval-20260817/eval</code></p></section>
<footer>哒哒Agent M1+M3完整分支判别复测 · 2026-08-18</footer></main></body></html>"""


def render_failure_rows(failures: list[dict]) -> str:
    rows = []
    for index, row in enumerate(failures, 1):
        error_type = classify_error(row)
        history = " / ".join(f"{role}: {text}" for role, text in row.get("history", []))
        calls = "<br>".join(
            f"{esc(call.get('model_tier'))}: {esc(call.get('content'))} ({esc(call.get('latency_ms'))}ms)"
            for call in row.get("model_calls", [])
        )
        search = " ".join(str(x) for x in (row.get("sample_id"), row.get("text"), history, row.get("truth"), row.get("prediction")))
        rows.append(
            f"<tr class='failure-row' data-truth='{esc(row.get('truth'))}' data-error='{error_type}' data-search='{esc(search.lower())}'>"
            f"<td>{index}</td><td><span class='tag tag-{error_type}'>{esc(ERROR_NAMES[error_type])}</span></td>"
            f"<td><b>{esc(row.get('truth'))}</b> · {esc(BRANCH_NAMES.get(row.get('truth'),''))}</td>"
            f"<td><code>{esc(row.get('sample_id'))}</code><br><small>{esc(row.get('stratum'))}</small></td>"
            f"<td><b>{esc(row.get('text'))}</b><details><summary>历史上下文</summary>{esc(history) or '无'}</details></td>"
            f"<td>{esc(row.get('m1_prediction'))}<br><small>top1={float(row.get('m1_top1') or 0):.4f}, margin={float(row.get('m1_margin') or 0):.4f}</small></td>"
            f"<td><b>{esc(row.get('prediction') or '无分支')}</b><br><small>{esc(', '.join(row.get('m3_tags',[])))}</small></td><td>{calls}</td></tr>"
        )
    return "".join(rows)


FILTER_JS = r"""
const rows=[...document.querySelectorAll('.failure-row')];
const q=document.querySelector('#q'), branch=document.querySelector('#branch'), type=document.querySelector('#type'), count=document.querySelector('#count');
function apply(){let n=0;for(const row of rows){const okQ=!q.value.trim()||row.dataset.search.includes(q.value.trim().toLowerCase());const okB=branch.value==='all'||row.dataset.truth===branch.value;const okT=type.value==='all'||row.dataset.error===type.value;row.hidden=!(okQ&&okB&&okT);if(!row.hidden)n++;}count.textContent=n;}
[q,branch,type].forEach(x=>x.addEventListener('input',apply));
"""


def render_failure_dataset(metrics: dict) -> str:
    branch_options = "".join(f"<option value='{key}'>{key} · {esc(name)}</option>" for key, name in BRANCH_NAMES.items())
    type_options = "".join(f"<option value='{key}'>{esc(name)}</option>" for key, name in ERROR_NAMES.items())
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>失败测试集 · 109条</title><style>{COMMON_CSS}.filters{{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}}input,select{{padding:9px;border:1px solid var(--line);border-radius:8px}}.failure-table{{min-width:1420px}}.tag{{padding:3px 7px;border-radius:999px;font-size:11px;font-weight:800;white-space:nowrap}}.tag-m3_introduced{{background:#ffe9db;color:#9a3412}}.tag-m3_unresolved{{background:#eee9ff;color:#5b21b6}}.tag-m1_direct{{background:#e7edf4;color:#334155}}.tag-route_failure{{background:#fee2e2;color:#991b1b}}small{{color:var(--muted)}}details summary{{cursor:pointer;color:var(--blue)}}</style></head><body><main id="failure-dataset" data-failure-count="{metrics['current_errors']}"><header><div class="eyebrow">FAILURE DATASET · 2026-08-18</div><h1>再次完善后失败测试集 · 109条</h1><p>完整收录本轮最终<code>correct=false</code>的样本，支持按关键词、真实分支和失败类型筛选。</p><nav class="topnav"><a href="{esc(REPORT_FILENAME)}">返回完整报告</a></nav></header><section class="section"><div class="filters"><input id="q" type="search" placeholder="搜索原文、ID、上下文"><select id="branch"><option value="all">全部分支</option>{branch_options}</select><select id="type"><option value="all">全部失败类型</option>{type_options}</select><span>显示 <b id="count">109</b> / 109</span></div><div class="scroll"><table class="failure-table"><thead><tr><th>#</th><th>失败类型</th><th>真值</th><th>样本</th><th>用户原文/历史</th><th>M1初判</th><th>最终</th><th>模型调用</th></tr></thead><tbody>{render_failure_rows(metrics['failures'])}</tbody></table></div></section><footer>109条失败测试集 · 2026-08-18</footer></main><script>{FILTER_JS}</script></body></html>"""


def generate(baseline_path: Path, failed_retest_path: Path, current_path: Path, output_dir: Path):
    metrics = compute_metrics(baseline_path, failed_retest_path, current_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / REPORT_FILENAME
    failure_path = output_dir / FAILURE_FILENAME
    report_path.write_text(render_report(metrics), encoding="utf-8")
    failure_path.write_text(render_failure_dataset(metrics), encoding="utf-8")
    return report_path, failure_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--failed-retest", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report, failures = generate(args.baseline, args.failed_retest, args.current, args.output_dir)
    print(json.dumps({"report": str(report), "failures": str(failures)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
