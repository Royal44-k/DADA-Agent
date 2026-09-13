# -*- coding: utf-8 -*-
"""Render a self-contained HTML report for the 1300-row stateful router retest."""
import argparse
import html
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


LABEL_NAMES = {
    "a": "新建提醒", "b": "修改提醒", "c": "查询提醒", "d": "写入记忆",
    "e": "查询记忆", "f": "调节音量", "g": "调节亮度", "h": "查询天气",
    "i": "查询时间", "j": "知识问答", "k": "晚安", "l": "再见", "m": "闲聊",
}
TARGET = 0.97


def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def pct(value):
    return f"{value * 100:.2f}%"


def percentile(values, fraction):
    clean = sorted(float(value) for value in values if isinstance(value, (int, float)))
    if not clean:
        return None
    index = max(0, min(len(clean) - 1, math.ceil(len(clean) * fraction) - 1))
    value = clean[index]
    return int(value) if value.is_integer() else round(value, 3)


def summarize(rows):
    total = len(rows)
    correct = sum(bool(row.get("correct")) for row in rows)
    m1_correct = sum(bool(row.get("m1_correct")) for row in rows)
    m3_rows = [row for row in rows if row.get("m3_used")]
    failures = [row for row in rows if not row.get("correct")]
    per_label = {}
    for label in LABEL_NAMES:
        group = [row for row in rows if row.get("truth") == label]
        hits = sum(bool(row.get("correct")) for row in group)
        per_label[label] = {
            "total": len(group), "correct": hits,
            "accuracy": hits / len(group) if group else 0,
            "m3_used": sum(bool(row.get("m3_used")) for row in group),
            "errors": len(group) - hits,
        }
    confusion = Counter(
        (row.get("truth"), row.get("prediction") or "∅")
        for row in failures
    )
    attribution = Counter()
    for row in failures:
        if not row.get("route_ok") or row.get("exception_type"):
            attribution["route_failure"] += 1
        elif row.get("m3_used"):
            if row.get("m1_correct"):
                attribution["m3_worsened"] += 1
            else:
                attribution["m3_failed_to_correct"] += 1
        elif row.get("m1_direct"):
            attribution["m1_direct_error"] += 1
        else:
            attribution["m1_non_m3_error"] += 1
    latencies = [row.get("wall_latency_ms") for row in rows]
    return {
        "total": total,
        "correct": correct,
        "errors": total - correct,
        "accuracy": correct / total if total else 0,
        "target": TARGET,
        "target_met": bool(total and correct / total >= TARGET),
        "m1_correct": m1_correct,
        "m1_accuracy": m1_correct / total if total else 0,
        "m3_used": len(m3_rows),
        "m3_entry_rate": len(m3_rows) / total if total else 0,
        "m3_corrected": sum(bool(row.get("m3_corrected")) for row in rows),
        "m3_worsened": sum(bool(row.get("m3_worsened")) for row in rows),
        "route_failures": sum(
            bool(row.get("exception_type")) or not row.get("route_ok") for row in rows
        ),
        "per_label": per_label,
        "confusion": [
            {"truth": truth, "prediction": prediction, "count": count}
            for (truth, prediction), count in confusion.most_common()
        ],
        "error_attribution": {
            key: attribution[key] for key in (
                "m1_direct_error", "m1_non_m3_error", "m3_worsened",
                "m3_failed_to_correct", "route_failure"
            )
        },
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "max": percentile(latencies, 1.0),
        },
    }


def _styles():
    return """
    :root{--bg:#071018;--panel:#0d1924;--line:#203344;--text:#e8f0f6;
      --muted:#8ca2b4;--cyan:#42d7e7;--green:#61e294;--amber:#ffbd59;
      --red:#ff6874;--ink:#061015}*{box-sizing:border-box}body{margin:0;background:var(--bg);
      color:var(--text);font:15px/1.62 Inter,"Segoe UI","Microsoft YaHei",sans-serif}
    main{max-width:1180px;margin:auto;padding:44px 28px 72px}a{color:var(--cyan)}
    .eyebrow{font:700 12px/1.2 Consolas,monospace;letter-spacing:.16em;color:var(--cyan)}
    h1{font-size:38px;line-height:1.15;margin:12px 0 8px}h2{font-size:22px;margin:38px 0 14px}
    .lede,.muted{color:var(--muted)}.verdict{margin:26px 0;padding:18px 20px;border-left:4px solid var(--green);
      background:#0a171d}.verdict.fail{border-color:var(--red)}
    .kpis{display:grid;grid-template-columns:repeat(5,1fr);border:1px solid var(--line);margin:24px 0}
    .kpi{padding:18px;border-right:1px solid var(--line)}.kpi:last-child{border:0}
    .kpi b{display:block;font:700 27px/1.2 Consolas,monospace}.kpi span{color:var(--muted);font-size:12px}
    .flow{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;gap:12px;align-items:center;margin:18px 0}
    .node{background:var(--panel);border:1px solid var(--line);padding:16px}.arrow{color:var(--amber);font-size:24px}
    .rail{display:grid;grid-template-columns:repeat(13,1fr);gap:4px}.branch{min-width:0;padding:12px 4px;
      text-align:center;background:var(--panel);border-top:4px solid var(--green)}.branch.warn{border-color:var(--amber)}
    .branch.bad{border-color:var(--red)}.branch b{display:block;font:700 15px Consolas,monospace}
    .branch small{font-size:10px;color:var(--muted);white-space:nowrap}.branch em{font:700 11px Consolas,monospace;font-style:normal}
    table{width:100%;border-collapse:collapse;background:var(--panel)}th,td{padding:10px 12px;
      border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{font-size:12px;color:var(--muted)}
    td.num{font-family:Consolas,monospace}.pass{color:var(--green)}.failtxt{color:var(--red)}
    code{font-family:Consolas,monospace;color:#b8e8ef}.evidence{border:1px solid var(--line);padding:16px 18px}
    .evidence dl{display:grid;grid-template-columns:220px 1fr;gap:6px 16px;margin:0}.evidence dt{color:var(--muted)}
    .evidence dd{margin:0;font-family:Consolas,monospace;overflow-wrap:anywhere}.foot{margin-top:36px;color:var(--muted);font-size:12px}
    .failure-row td:nth-child(2){max-width:460px}.tag{display:inline-block;border:1px solid var(--line);padding:1px 6px;margin:1px;font-size:11px}
    @media(max-width:850px){.kpis{grid-template-columns:1fr 1fr}.kpi{border-bottom:1px solid var(--line)}
      .flow{grid-template-columns:1fr}.arrow{transform:rotate(90deg);text-align:center}.rail{grid-template-columns:repeat(4,1fr)}
      .evidence dl{grid-template-columns:1fr}.wide{overflow:auto}h1{font-size:30px}}
    """


def _branch_table(summary):
    body = []
    for label, name in LABEL_NAMES.items():
        item = summary["per_label"][label]
        cls = "pass" if item["accuracy"] >= TARGET else "failtxt"
        body.append(
            f"<tr><td class='num'>{label}</td><td>{esc(name)}</td>"
            f"<td class='num'>{item['total']}</td><td class='num'>{item['correct']}</td>"
            f"<td class='num {cls}'>{pct(item['accuracy'])}</td>"
            f"<td class='num'>{item['m3_used']}</td><td class='num'>{item['errors']}</td></tr>"
        )
    return "".join(body)


def _branch_rail(summary):
    cells = []
    for label, name in LABEL_NAMES.items():
        item = summary["per_label"][label]
        cls = "" if item["accuracy"] >= TARGET else ("warn" if item["accuracy"] >= .90 else "bad")
        cells.append(
            f"<div class='branch {cls}' title='{esc(name)}'>"
            f"<b>{label}</b><small>{esc(name)}</small><em>{pct(item['accuracy'])}</em></div>"
        )
    return "".join(cells)


def render(rows, preflight, main_path, failures_path, report_date):
    summary = summarize(rows)
    main_path, failures_path = Path(main_path), Path(failures_path)
    main_path.parent.mkdir(parents=True, exist_ok=True)
    failures_path.parent.mkdir(parents=True, exist_ok=True)
    verdict_class = "" if summary["target_met"] else " fail"
    verdict_text = (
        f"通过验收：最终准确率 {pct(summary['accuracy'])}，达到 ≥97% 目标。"
        if summary["target_met"] else
        f"未通过验收：最终准确率 {pct(summary['accuracy'])}，低于 ≥97% 目标。"
    )
    state = preflight.get("fixture_state", {})
    hashes = preflight.get("production_sha256", {})
    attribution = summary["error_attribution"]
    confusions = "".join(
        f"<tr><td class='num'>{esc(item['truth'])}</td><td class='num'>{esc(item['prediction'])}</td>"
        f"<td class='num'>{item['count']}</td></tr>" for item in summary["confusion"][:12]
    ) or "<tr><td colspan='3'>无最终误判</td></tr>"
    main_html = f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>哒哒Agent 1300条状态化路由复测报告</title>
<style>{_styles()}</style></head><body><main>
<div class='eyebrow'>DADA AGENT / PRODUCTION ROUTE AUDIT / {esc(report_date)}</div>
<h1>修订版 1300 条语料<br>M1 → M3 完整路由实测</h1>
<p class='lede'>真实调用生产 1.7B 初判与 9B M3 复判；使用数据库中的有效 task / memory 状态，未伪造查询结果，未修改或重启生产服务。</p>
<div class='verdict{verdict_class}'><strong>{esc(verdict_text)}</strong><br>
共 {summary['total']} 条，正确 {summary['correct']} 条，最终错误 {summary['errors']} 条，链路故障 {summary['route_failures']} 条。</div>
<section class='kpis'><div class='kpi'><b>{pct(summary['accuracy'])}</b><span>最终准确率</span></div>
<div class='kpi'><b>{summary['correct']}/{summary['total']}</b><span>最终正确</span></div>
<div class='kpi'><b>{summary['m3_used']}</b><span>进入 M3 · {pct(summary['m3_entry_rate'])}</span></div>
<div class='kpi'><b>{summary['m3_corrected']}</b><span>M3 纠正</span></div>
<div class='kpi'><b>{summary['m3_worsened']}</b><span>M3 恶化</span></div></section>

<h2>完整链路表现</h2><div class='flow'>
<div class='node'><b>1.7B / M1</b><br><span class='muted'>初判正确 {summary['m1_correct']}/{summary['total']} · {pct(summary['m1_accuracy'])}</span></div>
<div class='arrow'>→</div><div class='node'><b>门控与 9B / M3</b><br><span class='muted'>复判 {summary['m3_used']} · 纠正 {summary['m3_corrected']} · 恶化 {summary['m3_worsened']}</span></div>
<div class='arrow'>→</div><div class='node'><b>最终分支</b><br><span class='muted'>正确 {summary['correct']} · 错误 {summary['errors']} · 故障 {summary['route_failures']}</span></div></div>
<p>最终错误归因：M1 高置信直进错误 <b>{attribution['m1_direct_error']}</b>；M1 未进入 M3 错误 <b>{attribution['m1_non_m3_error']}</b>；
M3 将原本正确结果改错 <b>{attribution['m3_worsened']}</b>；M3 未纠正初判错误 <b>{attribution['m3_failed_to_correct']}</b>；链路故障 <b>{attribution['route_failure']}</b>。</p>

<h2>13 分支验收轨</h2><div class='rail'>{_branch_rail(summary)}</div>
<div class='wide'><table><thead><tr><th>标签</th><th>分支</th><th>样本</th><th>正确</th><th>准确率</th><th>进入M3</th><th>错误</th></tr></thead>
<tbody>{_branch_table(summary)}</tbody></table></div>

<h2>主要混淆方向</h2><div class='wide'><table><thead><tr><th>正确标签</th><th>最终预测</th><th>次数</th></tr></thead><tbody>{confusions}</tbody></table></div>
<p><a href='{esc(failures_path.name)}'>打开全部 {summary['errors']} 条失败测试集 →</a></p>

<h2>时延与运行完整性</h2><div class='kpis'>
<div class='kpi'><b>{esc(summary['latency_ms']['p50'])}</b><span>端到端 P50 ms</span></div>
<div class='kpi'><b>{esc(summary['latency_ms']['p95'])}</b><span>端到端 P95 ms</span></div>
<div class='kpi'><b>{esc(summary['latency_ms']['max'])}</b><span>端到端最大 ms</span></div>
<div class='kpi'><b>{summary['route_failures']}</b><span>模型/路由故障</span></div>
<div class='kpi'><b>{'PASS' if summary['total'] == 1300 else 'CHECK'}</b><span>结果行数</span></div></div>

<h2>可复核证据</h2><div class='evidence'><dl>
<dt>报告日期</dt><dd>{esc(report_date)}</dd><dt>专用测试用户</dt><dd>{esc(preflight.get('eval_user_id'))}</dd>
<dt>有效 task / memory</dt><dd>{esc(state.get('fixture_task_count'))} / {esc(state.get('fixture_memory_count'))}</dd>
<dt>被状态裁剪的工具</dt><dd>{esc(state.get('narrow_absent', []))}</dd>
<dt>修订语料 SHA-256</dt><dd>{esc(preflight.get('input', {}).get('sha256'))}</dd>
<dt>m1_gate.py SHA-256</dt><dd>{esc(hashes.get('m1_gate'))}</dd>
<dt>m3_tool_panel.py SHA-256</dt><dd>{esc(hashes.get('m3_tool_panel'))}</dd>
<dt>branch_prompts.py SHA-256</dt><dd>{esc(hashes.get('branch_prompts'))}</dd>
</dl></div>
<p class='foot'>口径：每条语料只按修订后标签与生产完整路由的最终分支比较；进入 M3 的结果已计入最终准确率。97% 是验收阈值，不参与样本筛选或结果修饰。</p>
</main></body></html>"""

    failure_rows = []
    for row in rows:
        if row.get("correct"):
            continue
        tags = "".join(f"<span class='tag'>{esc(tag)}</span>" for tag in row.get("m3_tags") or [])
        history = json.dumps(row.get("history") or [], ensure_ascii=False)
        failure_rows.append(
            f"<tr class='failure-row'><td class='num'>{esc(row.get('sample_id'))}</td>"
            f"<td>{esc(row.get('text'))}<br><small class='muted'>history: {esc(history)}</small></td>"
            f"<td class='num'>{esc(row.get('truth'))}</td><td class='num'>{esc(row.get('m1_prediction'))}</td>"
            f"<td>{'是' if row.get('m3_used') else '否'} {tags}</td><td class='num failtxt'>{esc(row.get('prediction') or '∅')}</td>"
            f"<td>{esc(row.get('exception_type') or '')} {esc(row.get('exception_message') or '')}</td></tr>"
        )
    failure_html = f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>失败测试集</title><style>{_styles()}</style></head><body><main>
<div class='eyebrow'>FAILURE LEDGER / {esc(report_date)}</div><h1>失败测试集 · {summary['errors']} 条</h1>
<p class='lede'>这是最终分支误判的完整明细。M1 初判、M3 是否介入、最终预测与异常信息均保留，便于继续修复。</p>
<p><a href='{esc(main_path.name)}'>← 返回主报告</a></p><div class='wide'><table><thead><tr>
<th>sample_id</th><th>用户表达 / 历史</th><th>标准</th><th>M1</th><th>M3</th><th>最终</th><th>异常</th></tr></thead>
<tbody>{''.join(failure_rows) if failure_rows else '<tr><td colspan="7">无失败样本</td></tr>'}</tbody></table></div>
<p class='foot'>分支释义：{'；'.join(f'{key}={value}' for key, value in LABEL_NAMES.items())}</p></main></body></html>"""
    main_path.write_text(main_html, encoding="utf-8")
    failures_path.write_text(failure_html, encoding="utf-8")
    return summary


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--preflight", required=True, type=Path)
    parser.add_argument("--main-html", required=True, type=Path)
    parser.add_argument("--failures-html", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--date", default="2026-08-20")
    parser.add_argument("--expected-count", type=int, default=1300)
    args = parser.parse_args()
    rows = load_jsonl(args.results)
    if len(rows) != args.expected_count:
        raise ValueError(f"结果行数 {len(rows)} != 期望 {args.expected_count}")
    if len({row.get('sample_id') for row in rows}) != len(rows):
        raise ValueError("结果 sample_id 不唯一")
    preflight = json.loads(args.preflight.read_text(encoding="utf-8"))
    summary = render(rows, preflight, args.main_html, args.failures_html, args.date)
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
