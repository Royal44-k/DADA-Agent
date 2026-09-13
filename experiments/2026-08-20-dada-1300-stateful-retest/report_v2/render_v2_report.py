# -*- coding: utf-8 -*-
"""Render the v2 corpus review and production-route retest as static HTML."""
import argparse
import html
import json
import math
from collections import Counter
from pathlib import Path


LABEL_NAMES = {
    "a": "新建提醒", "b": "修改提醒", "c": "查询提醒", "d": "写入记忆",
    "e": "查询记忆", "f": "调节音量", "g": "调节亮度", "h": "查询天气",
    "i": "查询时间", "j": "产品知识", "k": "晚安", "l": "再见", "m": "闲聊",
}
TARGET = .97


def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def pct(value):
    return f"{value * 100:.2f}%"


def percentile(values, fraction):
    clean = sorted(float(value) for value in values if isinstance(value, (int, float)))
    if not clean:
        return None
    value = clean[max(0, min(len(clean) - 1, math.ceil(len(clean) * fraction) - 1))]
    return int(value) if value.is_integer() else round(value, 3)


def summarize(rows, previous):
    total = len(rows)
    correct = sum(bool(row.get("correct")) for row in rows)
    errors = total - correct
    m3_corrected = sum(bool(row.get("m3_corrected")) for row in rows)
    m3_worsened = sum(bool(row.get("m3_worsened")) for row in rows)
    accuracy = correct / total if total else 0
    per_label = {}
    for label in LABEL_NAMES:
        group = [row for row in rows if row.get("truth") == label]
        hits = sum(bool(row.get("correct")) for row in group)
        per_label[label] = {
            "total": len(group), "correct": hits, "errors": len(group) - hits,
            "accuracy": hits / len(group) if group else 0,
            "m3_used": sum(bool(row.get("m3_used")) for row in group),
        }
    failures = [row for row in rows if not row.get("correct")]
    confusion = Counter((row.get("truth"), row.get("prediction") or "∅") for row in failures)
    attribution = Counter()
    for row in failures:
        if row.get("exception_type") or not row.get("route_ok"):
            attribution["route_failure"] += 1
        elif row.get("m3_used") and row.get("m1_correct"):
            attribution["m3_worsened"] += 1
        elif row.get("m3_used"):
            attribution["m3_failed_to_correct"] += 1
        elif row.get("m1_direct"):
            attribution["m1_direct_error"] += 1
        else:
            attribution["other"] += 1
    latencies = [row.get("wall_latency_ms") for row in rows]
    return {
        "total": total, "correct": correct, "errors": errors, "accuracy": accuracy,
        "target_met": bool(total and accuracy >= TARGET),
        "previous_accuracy": float(previous.get("accuracy", 0)),
        "previous_correct": int(previous.get("correct", 0)),
        "previous_errors": int(previous.get("errors", 0)),
        "accuracy_delta_pp": (accuracy - float(previous.get("accuracy", 0))) * 100,
        "correct_delta": correct - int(previous.get("correct", 0)),
        "m1_correct": sum(bool(row.get("m1_correct")) for row in rows),
        "m3_used": sum(bool(row.get("m3_used")) for row in rows),
        "m3_corrected": m3_corrected, "m3_worsened": m3_worsened,
        "m3_net_gain": m3_corrected - m3_worsened,
        "route_failures": sum(bool(row.get("exception_type")) or not row.get("route_ok") for row in rows),
        "infra_retried": sum(bool(row.get("infra_retry", {}).get("attempted")) for row in rows),
        "per_label": per_label,
        "confusion": [{"truth": a, "prediction": b, "count": count}
                      for (a, b), count in confusion.most_common()],
        "error_attribution": {key: attribution[key] for key in (
            "m1_direct_error", "m3_worsened", "m3_failed_to_correct", "route_failure", "other")},
        "latency_ms": {"p50": percentile(latencies, .5),
                       "p95": percentile(latencies, .95),
                       "max": percentile(latencies, 1)},
    }


def review_outcomes(rows, audit):
    by_id = {row.get("sample_id"): row for row in rows}
    outcomes = {}
    for disposition in ("label_fix", "text_rewrite", "label_and_text_fix", "model_error_keep"):
        items = [item for item in audit.get("changes", [])
                 if item.get("disposition") == disposition]
        correct = sum(bool(by_id.get(item.get("sample_id"), {}).get("correct")) for item in items)
        outcomes[disposition] = {
            "total": len(items), "correct": correct, "errors": len(items) - correct,
        }
    return outcomes


def styles():
    return """
    :root{--paper:#eef5f7;--sheet:#f9fcfd;--ink:#12212b;--muted:#607581;--rule:#b8cbd2;
      --blue:#2457d6;--teal:#087f8c;--red:#d1495b;--amber:#b76b00;--white:#fff}
    *{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);
      font:15px/1.65 "Microsoft YaHei UI","PingFang SC",sans-serif}main{max-width:1180px;margin:auto;padding:42px 28px 76px}
    a{color:var(--blue);text-underline-offset:3px}.folio{font:700 11px/1.3 Consolas,monospace;color:var(--teal);letter-spacing:.15em}
    h1{font-size:42px;line-height:1.12;letter-spacing:-.04em;margin:12px 0 10px;max-width:900px}h2{font-size:22px;margin:40px 0 14px}
    h3{font-size:16px;margin:0}.lede{color:var(--muted);max-width:850px}.verdict{display:grid;grid-template-columns:1.5fr 1fr;
      border-top:4px solid var(--teal);border-bottom:1px solid var(--rule);margin:28px 0;background:var(--sheet)}
    .verdict>div{padding:20px}.verdict>div+div{border-left:1px solid var(--rule)}.big{font:800 48px/1 Consolas,monospace;color:var(--teal)}
    .delta{font:700 19px Consolas,monospace;color:var(--blue)}.fail{color:var(--red)}.muted{color:var(--muted)}
    .ledger{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid var(--rule);background:var(--sheet)}
    .ledger>div{padding:16px;border-right:1px solid var(--rule)}.ledger>div:last-child{border:0}.ledger b{display:block;font:800 25px Consolas,monospace}
    .flow{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;gap:12px;align-items:center}.node{border:1px solid var(--rule);background:var(--sheet);padding:16px}
    .arrow{font:800 24px Consolas;color:var(--blue)}.tape{display:grid;grid-template-columns:repeat(13,1fr);gap:3px;background:var(--ink);padding:7px}
    .punch{min-width:0;text-align:center;background:var(--sheet);padding:10px 3px;border-bottom:5px solid var(--teal)}.punch.warn{border-color:var(--amber)}
    .punch.bad{border-color:var(--red)}.punch b,.punch em{display:block;font:800 13px Consolas,monospace;font-style:normal}.punch small{font-size:9px;color:var(--muted)}
    table{width:100%;border-collapse:collapse;background:var(--sheet)}th,td{padding:10px 12px;border-bottom:1px solid var(--rule);text-align:left;vertical-align:top}
    th{font-size:11px;letter-spacing:.05em;color:var(--muted)}td.num{font-family:Consolas,monospace}.wide{overflow:auto}
    .proof{display:grid;grid-template-columns:1fr 1fr;gap:0;border:1px solid var(--rule);margin:10px 0;background:var(--sheet)}
    .proof>div{padding:14px}.proof>div+div{border-left:1px solid var(--rule)}.before{color:#812d39;text-decoration:line-through;text-decoration-thickness:1px}
    .after{color:#174bb9}.chip{display:inline-block;padding:1px 6px;border:1px solid currentColor;font:700 10px Consolas,monospace;margin-right:5px}
    .evidence{border:1px solid var(--rule);background:var(--sheet);padding:18px}.evidence dl{display:grid;grid-template-columns:210px 1fr;gap:5px 14px;margin:0}
    .evidence dt{color:var(--muted)}.evidence dd{margin:0;font-family:Consolas,monospace;overflow-wrap:anywhere}.foot{color:var(--muted);font-size:12px;margin-top:34px}
    @media(max-width:820px){h1{font-size:32px}.verdict,.proof{grid-template-columns:1fr}.verdict>div+div,.proof>div+div{border-left:0;border-top:1px solid var(--rule)}
      .ledger{grid-template-columns:1fr 1fr}.ledger>div{border-bottom:1px solid var(--rule)}.flow{grid-template-columns:1fr}.arrow{text-align:center;transform:rotate(90deg)}
      .tape{grid-template-columns:repeat(4,1fr)}.evidence dl{grid-template-columns:1fr}}
    """


def branch_tape(summary):
    cells=[]
    for label,name in LABEL_NAMES.items():
        item=summary["per_label"][label]
        cls="" if item["accuracy"]>=TARGET else ("warn" if item["accuracy"]>=.9 else "bad")
        cells.append(f"<div class='punch {cls}'><b>{label}</b><small>{esc(name)}</small><em>{pct(item['accuracy'])}</em></div>")
    return "".join(cells)


def render(rows, previous, preflight, audit, main_path, failures_path, revisions_path, report_date):
    summary=summarize(rows,previous)
    outcomes=review_outcomes(rows,audit)
    main_path,failures_path,revisions_path=map(Path,(main_path,failures_path,revisions_path))
    for path in (main_path,failures_path,revisions_path): path.parent.mkdir(parents=True,exist_ok=True)
    verdict="通过" if summary["target_met"] else "未通过"
    delta_sign="+" if summary["accuracy_delta_pp"]>=0 else ""
    attr=summary["error_attribution"]
    branch_rows="".join(
        f"<tr><td class='num'>{label}</td><td>{esc(name)}</td><td class='num'>{v['total']}</td><td class='num'>{v['correct']}</td>"
        f"<td class='num'>{pct(v['accuracy'])}</td><td class='num'>{v['m3_used']}</td><td class='num'>{v['errors']}</td></tr>"
        for label,name in LABEL_NAMES.items() for v in [summary["per_label"][label]])
    confusion="".join(f"<tr><td class='num'>{esc(x['truth'])}</td><td class='num'>{esc(x['prediction'])}</td><td class='num'>{x['count']}</td></tr>"
                      for x in summary["confusion"][:12]) or "<tr><td colspan='3'>无误判</td></tr>"
    state=preflight.get("fixture_state",{}); hashes=preflight.get("production_sha256",{})
    main_html=f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>哒哒Agent 1300条v2语料生产复测报告</title><style>{styles()}</style></head><body><main>
<div class='folio'>DADA / CORPUS PROOF 02 / {esc(report_date)}</div><h1>34 条失败语料重审后<br>1300 条生产完整路由复测</h1>
<p class='lede'>这是一份“语料证据—模型判别—最终分支”的复核账本。只纠正标签错误和破损/歧义表达；仍然成立的模型难例原样保留。生产代码未因追求指标而调整。</p>
<section class='verdict'><div><span class='folio'>FINAL ACCURACY</span><div class='big'>{pct(summary['accuracy'])}</div>
<p><b>{verdict} ≥97% 验收</b> · {summary['correct']}/{summary['total']} 正确 · {summary['errors']} 错误 · {summary['route_failures']} 最终链路故障</p></div>
<div><span class='folio'>VERSUS PREVIOUS RUN</span><p class='delta'>{delta_sign}{summary['accuracy_delta_pp']:.2f} 个百分点</p>
<p>上一轮 {pct(summary['previous_accuracy'])}（{summary['previous_correct']}/{previous.get('total',1300)}）；本轮净增加 {summary['correct_delta']} 条正确。</p></div></section>
<section class='ledger'><div><b>{audit['reviewed_failures']}</b><span>失败语料逐条复核</span></div><div><b>{audit['label_changes']}</b><span>2 条改标</span></div>
<div><b>{audit['text_changes']}</b><span>15 条改写</span></div><div><b>{audit['model_error_kept']}</b><span>真实模型难例保留</span></div></section>

<h2>34 条审校样本的复测去向</h2><section class='ledger'>
<div><b>{outcomes['label_fix']['correct']}/{outcomes['label_fix']['total']}</b><span>改标后正确</span></div>
<div><b>{outcomes['text_rewrite']['correct']}/{outcomes['text_rewrite']['total']}</b><span>改写后正确</span></div>
<div><b>{outcomes['model_error_keep']['correct']}/{outcomes['model_error_keep']['total']}</b><span>原样难例正确</span></div>
<div><b>{outcomes['model_error_keep']['errors']}</b><span>原样难例仍失败</span></div></section>
<p class='muted'>标签和表达修订共 17 条，其中 {outcomes['label_fix']['correct'] + outcomes['text_rewrite']['correct']}/{outcomes['label_fix']['total'] + outcomes['text_rewrite']['total']} 复测正确；原样保留的 17 条中仍有 {outcomes['model_error_keep']['errors']} 条失败，作为后续模型优化的核心失败集。</p>

<h2>M1 → M3 完整机制</h2><div class='flow'><div class='node'><h3>1.7B 初判</h3><span class='muted'>正确 {summary['m1_correct']}/{summary['total']}</span></div><div class='arrow'>→</div>
<div class='node'><h3>9B M3 复判</h3><span class='muted'>进入 {summary['m3_used']} · 纠正 {summary['m3_corrected']} · 恶化 {summary['m3_worsened']} · 净增益 {summary['m3_net_gain']}</span></div>
<div class='arrow'>→</div><div class='node'><h3>最终分支</h3><span class='muted'>正确 {summary['correct']} · 错误 {summary['errors']} · 基础设施重试 {summary['infra_retried']}</span></div></div>
<p>最终错误归因：M1 高置信直进 {attr['m1_direct_error']}；M3 将正确初判改错 {attr['m3_worsened']}；M3 未纠正初判 {attr['m3_failed_to_correct']}；其他 {attr['other']}；链路故障 {attr['route_failure']}。</p>

<h2>13 分支检验带</h2><div class='tape'>{branch_tape(summary)}</div><div class='wide'><table><thead><tr><th>标签</th><th>分支</th><th>样本</th><th>正确</th><th>准确率</th><th>进入M3</th><th>错误</th></tr></thead><tbody>{branch_rows}</tbody></table></div>
<h2>主要混淆</h2><div class='wide'><table><thead><tr><th>标准标签</th><th>最终预测</th><th>次数</th></tr></thead><tbody>{confusion}</tbody></table></div>
<p><a href='{esc(failures_path.name)}'>打开本轮全部失败样本 →</a>　<a href='{esc(revisions_path.name)}'>打开 34 条语料审校账本 →</a></p>

<h2>时延与可复核证据</h2><section class='ledger'><div><b>{esc(summary['latency_ms']['p50'])}</b><span>P50 ms</span></div><div><b>{esc(summary['latency_ms']['p95'])}</b><span>P95 ms</span></div>
<div><b>{esc(summary['latency_ms']['max'])}</b><span>最大 ms</span></div><div><b>{summary['route_failures']}</b><span>最终链路故障</span></div></section>
<div class='evidence'><dl><dt>专用测试用户</dt><dd>{esc(preflight.get('eval_user_id'))}</dd><dt>task / memory</dt><dd>{esc(state.get('fixture_task_count'))} / {esc(state.get('fixture_memory_count'))}</dd>
<dt>被状态裁剪的工具</dt><dd>{esc(state.get('narrow_absent',[]))}</dd><dt>v2 语料 SHA-256</dt><dd>{esc(preflight.get('input',{}).get('sha256'))}</dd>
<dt>m1_gate.py</dt><dd>{esc(hashes.get('m1_gate'))}</dd><dt>m3_tool_panel.py</dt><dd>{esc(hashes.get('m3_tool_panel'))}</dd><dt>branch_prompts.py</dt><dd>{esc(hashes.get('branch_prompts'))}</dd></dl></div>
<p class='foot'>口径：使用修订后的全部 1300 条样本和真实数据库状态，完整调用生产 M1→M3；仅基础设施 route_ok=false 可按固定策略重试一次，普通分类错误不得重试。</p>
</main></body></html>"""

    failure_rows=[]
    for row in rows:
        if row.get("correct"): continue
        tags=" ".join(f"<span class='chip'>{esc(tag)}</span>" for tag in row.get("m3_tags") or [])
        failure_rows.append(f"<tr><td class='num'>{esc(row.get('sample_id'))}</td><td>{esc(row.get('text'))}<br><small>{esc(json.dumps(row.get('history') or [],ensure_ascii=False))}</small></td>"
                            f"<td class='num'>{esc(row.get('truth'))}</td><td class='num'>{esc(row.get('m1_prediction'))}</td><td>{'是' if row.get('m3_used') else '否'} {tags}</td>"
                            f"<td class='num fail'>{esc(row.get('prediction') or '∅')}</td><td>{esc(row.get('exception_type') or row.get('exception_message') or '')}</td></tr>")
    failures_html=f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>v2失败集</title><style>{styles()}</style></head><body><main>
<div class='folio'>FAILURE TAPE / {esc(report_date)}</div><h1>本轮失败样本 · {summary['errors']} 条</h1><p><a href='{esc(main_path.name)}'>← 返回主报告</a></p><div class='wide'><table><thead><tr><th>ID</th><th>文本/历史</th><th>标准</th><th>M1</th><th>M3</th><th>最终</th><th>异常</th></tr></thead>
<tbody>{''.join(failure_rows) if failure_rows else '<tr><td colspan="7">无失败样本</td></tr>'}</tbody></table></div></main></body></html>"""

    proofs=[]
    names={"label_fix":"标签纠正","text_rewrite":"文本修复","label_and_text_fix":"标签+文本","model_error_keep":"原样保留"}
    for item in audit.get("changes",[]):
        changed=item["disposition"]!="model_error_keep"
        proofs.append(f"<article class='proof'><div><span class='chip'>{esc(names.get(item['disposition'],item['disposition']))}</span><b>{esc(item['sample_id'])}</b>"
                      f"<p class='before'>{esc(item['before_label'])} · {esc(item['before_text'])}</p></div><div><span class='folio'>{'REVISED' if changed else 'MODEL ERROR KEPT'}</span>"
                      f"<p class='after'>{esc(item['after_label'])} · {esc(item['after_text'])}</p><small>{esc(item['rationale'])}</small></div></article>")
    revisions_html=f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>34条语料审校账本</title><style>{styles()}</style></head><body><main>
<div class='folio'>CORPUS PROOF LEDGER / {esc(report_date)}</div><h1>34 条失败语料<br>标签与表达审校账本</h1><p class='lede'>红色为上一版，蓝色为审校结论。原样保留表示标签和表达均成立，失败应归于模型而不是语料。</p>
<p><a href='{esc(main_path.name)}'>← 返回主报告</a></p>{''.join(proofs)}</main></body></html>"""
    main_path.write_text(main_html,encoding="utf-8"); failures_path.write_text(failures_html,encoding="utf-8"); revisions_path.write_text(revisions_html,encoding="utf-8")
    return summary


def load_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--results",required=True,type=Path); parser.add_argument("--previous-summary",required=True,type=Path)
    parser.add_argument("--preflight",required=True,type=Path); parser.add_argument("--revision-audit",required=True,type=Path); parser.add_argument("--main-html",required=True,type=Path)
    parser.add_argument("--failures-html",required=True,type=Path); parser.add_argument("--revisions-html",required=True,type=Path); parser.add_argument("--summary",required=True,type=Path)
    parser.add_argument("--date",default="2026-08-20"); parser.add_argument("--expected-count",type=int,default=1300); args=parser.parse_args()
    rows=load_jsonl(args.results)
    if len(rows)!=args.expected_count or len({r.get('sample_id') for r in rows})!=len(rows): raise ValueError("result count or IDs invalid")
    previous=json.loads(args.previous_summary.read_text(encoding="utf-8")); preflight=json.loads(args.preflight.read_text(encoding="utf-8")); audit=json.loads(args.revision_audit.read_text(encoding="utf-8"))
    summary=render(rows,previous,preflight,audit,args.main_html,args.failures_html,args.revisions_html,args.date)
    args.summary.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps(summary,ensure_ascii=False))


if __name__=="__main__": main()
