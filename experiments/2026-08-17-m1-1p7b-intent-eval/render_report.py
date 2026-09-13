# -*- coding: utf-8 -*-
"""将 M1 / 1.7B 评测结果渲染为无外部依赖的单文件 HTML。"""
import argparse
import html
import json
from pathlib import Path


LABELS = tuple("abcdefghijklm")


def _pct(value, digits=2):
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _num(value, digits=1):
    return "—" if value is None else f"{value:.{digits}f}"


def _e(value):
    return html.escape(str(value if value is not None else "—"), quote=True)


def _stratum_table(title, groups):
    rows = []
    for key, item in groups.items():
        rows.append(
            f"<tr><td>{_e(key)}</td><td class='num'>{item['correct']} / {item['total']}</td>"
            f"<td class='num'>{_pct(item['accuracy'])}</td><td class='num'>{_pct(item['direct_rate'])}</td>"
            f"<td class='num'>{item['dangerous']}</td></tr>")
    return (f"<div class='mini'><h3>{_e(title)}</h3><div class='scroll'><table><thead><tr>"
            "<th>分层</th><th>正确</th><th>准确率</th><th>直进率</th><th>危险误路由</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div></div>")


def generate_report(summary, results, manifest, before, after, labels=LABELS):
    classification = summary["classification"]
    gate = summary["gate"]
    latency = summary["latency_ms"]
    macro_f1 = classification["macro_f1"]
    classification_status = ("通过" if macro_f1 is not None and macro_f1 >= .95 else
                             "有条件通过" if macro_f1 is not None and macro_f1 >= .90 else "不通过")
    gate_pass = (gate["direct_accuracy"] is not None and gate["direct_accuracy"] >= .995
                 and gate["dangerous_rate"] is not None and gate["dangerous_rate"] <= .001)
    overall = "通过" if classification_status == "通过" and gate_pass else "有条件通过" if classification_status != "不通过" else "不通过"
    verdict_class = "pass" if overall == "通过" else "warn" if overall == "有条件通过" else "fail"

    branch_rows = []
    for label in labels:
        item = classification["per_label"][label]
        branch_rows.append(
            f"<tr><td><span class='label'>{_e(label)}</span></td><td>{_e(item['name'])}</td>"
            f"<td class='num'>{item['correct']} / {item['support']}</td>"
            f"<td class='num'>{_pct(item['precision'])}</td><td class='num'>{_pct(item['recall'])}</td>"
            f"<td class='num'>{_pct(item['f1'])}</td><td class='num'>{item['direct']} / {item['support']}</td>"
            f"<td class='num'>{_pct(item['direct_accuracy'])}</td><td class='num'>{item['dangerous']}</td></tr>")

    matrix_head = "".join(f"<th>{_e(label)}</th>" for label in labels)
    matrix_rows = []
    for truth in labels:
        cells = []
        for prediction in labels:
            value = summary["confusion_matrix"][truth][prediction]
            cls = "diag" if truth == prediction else "miss" if value else ""
            cells.append(f"<td class='num {cls}'>{value}</td>")
        matrix_rows.append(f"<tr><th>{_e(truth)}</th>{''.join(cells)}</tr>")

    top_confusions = summary.get("top_confusions") or []
    confusion_rows = "".join(
        f"<tr><td>{_e(item['truth'])} → {_e(item['prediction'])}</td><td class='num'>{item['count']}</td></tr>"
        for item in top_confusions[:15]) or "<tr><td colspan='2'>无有效标签间的误判</td></tr>"

    sweep_rows = "".join(
        f"<tr><td class='num'>{item['threshold']:.8f}</td><td class='num'>{item['direct']}</td>"
        f"<td class='num'>{_pct(item['coverage'])}</td><td class='num'>{_pct(item['direct_accuracy'])}</td>"
        f"<td class='num'>{item['dangerous']}</td><td class='num'>{_pct(item['dangerous_rate'],3)}</td></tr>"
        for item in summary.get("threshold_sweep", []))

    errors = [row for row in results if not row.get("correct")]
    errors.sort(key=lambda row: (not bool(row.get("dangerous_misroute")),
                                 -(row.get("top1") or -1), row.get("sample_id") or ""))
    error_rows = []
    for row in errors[:30]:
        error_rows.append(
            "<tr>"
            f"<td>{_e(row.get('sample_id'))}</td><td>{_e(row.get('truth'))}</td>"
            f"<td>{_e(row.get('prediction') or row.get('exception_type') or '无效输出')}</td>"
            f"<td>{_e(row.get('text'))}</td><td class='num'>{_pct(row.get('top1'), 3)}</td>"
            f"<td>{'是' if row.get('dangerous_misroute') else '否'}</td></tr>")
    if not error_rows:
        error_rows.append("<tr><td colspan='6'>本批无错误样本</td></tr>")

    before_hashes = before.get("hashes") or {}
    after_hashes = after.get("hashes") or {}
    integrity_rows = []
    for path in sorted(set(before_hashes) | set(after_hashes)):
        same = before_hashes.get(path) == after_hashes.get(path) and before_hashes.get(path) is not None
        integrity_rows.append(
            f"<tr><td>{_e(path)}</td><td><code>{_e((before_hashes.get(path) or '')[:16])}…</code></td>"
            f"<td><span class='tag {'pass' if same else 'fail'}'>{'一致' if same else '不一致'}</span></td></tr>")
    process_same = before.get("agent_pid") == after.get("agent_pid")
    weakest_label = min(labels, key=lambda label: classification["per_label"][label]["recall"])
    weakest = classification["per_label"][weakest_label]
    danger_labels = [label for label in labels
                     if classification["per_label"][label].get("dangerous", 0) > 0]
    safe_labels = [label for label in labels if label not in danger_labels]

    strata = summary["strata"]
    html_doc = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>哒哒 Agent M1 / 1.7B 十三分支意图分类实测报告</title>
<style>
:root{{--ink:#13233a;--muted:#667085;--paper:#f4f7fb;--card:#fff;--line:#dfe6ef;--blue:#315efb;--green:#12835b;--amber:#b76b00;--red:#c43e50;}}
*{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(180deg,#f8faff,#f3f6fa);color:var(--ink);font:15px/1.65 "Segoe UI","Microsoft YaHei",sans-serif}}
.shell{{width:min(1200px,calc(100% - 36px));margin:auto}} header{{padding:54px 0 28px}} h1{{font-size:clamp(30px,4vw,50px);line-height:1.15;margin:8px 0}} h2{{font-size:23px;margin:0 0 15px}} h3{{font-size:16px;margin:0 0 10px}} p{{margin:7px 0}} .sub{{color:var(--muted);font-size:17px;max-width:920px}}
.eyebrow{{color:var(--blue);font-size:12px;font-weight:800;letter-spacing:.08em}} .meta{{display:flex;gap:9px;flex-wrap:wrap;margin-top:18px}} .pill{{background:#fff;border:1px solid var(--line);padding:6px 10px;border-radius:99px;color:#526178;font-size:12px}}
.verdict{{display:grid;grid-template-columns:180px 1fr;gap:22px;align-items:center;background:#fff;border:1px solid var(--line);border-radius:18px;padding:23px;box-shadow:0 12px 32px #172b4d12;margin-bottom:20px}} .verdict .mark{{border-radius:13px;padding:18px;text-align:center;font-size:24px;font-weight:800}} .mark.pass{{background:#e9f8f2;color:var(--green)}} .mark.warn{{background:#fff4df;color:var(--amber)}} .mark.fail{{background:#fff0f2;color:var(--red)}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:13px;margin-bottom:20px}} .kpi,.section,.mini{{background:var(--card);border:1px solid var(--line);border-radius:16px;box-shadow:0 10px 28px #172b4d0c}} .kpi{{padding:19px}} .kpi b{{font-size:29px;display:block}} .kpi span{{color:var(--muted);font-size:12px}}
.section{{padding:26px;margin-bottom:20px}} .grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}} .mini{{padding:17px;box-shadow:none}} .scroll{{overflow:auto}} table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border-bottom:1px solid var(--line);padding:9px 10px;text-align:left;vertical-align:top}} th{{background:#f7f9fc;color:#526178;font-size:12px}} .num{{text-align:right;font-variant-numeric:tabular-nums}} .label{{display:inline-grid;place-items:center;width:25px;height:25px;border-radius:7px;background:#edf2ff;color:var(--blue);font-weight:800}} .diag{{background:#eaf8f2;color:var(--green);font-weight:800}} .miss{{background:#fff0f2;color:var(--red);font-weight:700}}
.tag{{display:inline-block;border-radius:99px;padding:2px 8px;font-size:12px;font-weight:700}} .tag.pass{{color:var(--green);background:#e9f8f2}} .tag.fail{{color:var(--red);background:#fff0f2}} .tag.warn{{color:var(--amber);background:#fff4df}} code{{font-family:Consolas,monospace}} .callout{{border-left:4px solid var(--blue);background:#edf2ff;padding:13px 15px;border-radius:8px;margin:13px 0}} footer{{padding:10px 0 45px;color:var(--muted);font-size:12px}}
@media(max-width:850px){{.kpis{{grid-template-columns:1fr 1fr}}.grid{{grid-template-columns:1fr}}.verdict{{grid-template-columns:1fr}}}} @media(max-width:520px){{.kpis{{grid-template-columns:1fr}}.shell{{width:calc(100% - 22px)}}.section{{padding:18px}}}}
@media print{{body{{background:#fff}}.kpi,.section,.mini,.verdict{{box-shadow:none;break-inside:avoid}}}}
</style></head><body><main class="shell">
<header><div class="eyebrow">DADA AGENT · M1 ROUTER · V100 1.7B</div><h1>十三分支意图分类服务器实测报告</h1>
<p class="sub">基于 raw a～m 语料的固定种子分层抽样，独立测量 1.7B 原始分类能力与生产 M1 高置信门控安全性。</p>
<div class="meta"><span class="pill">报告日期 2026-08-17</span><span class="pill">随机种子 {_e(manifest.get('seed'))}</span><span class="pill">样本 {_e(manifest.get('total'))}</span><span class="pill">每分支 {_e(manifest.get('per_label'))}</span></div></header>
<section class="verdict"><div class="mark {verdict_class}">{overall}</div><div><h2>分类能力：{classification_status}；M1门控：{'通过' if gate_pass else '不通过'}</h2><p>1.7B 准确率 <b>{_pct(classification['accuracy'])}</b>，macro-F1 <b>{_pct(macro_f1)}</b>；高置信直进覆盖率 <b>{_pct(gate['coverage'])}</b>，直进准确率 <b>{_pct(gate['direct_accuracy'])}</b>，危险误路由率 <b>{_pct(gate['dangerous_rate'],3)}</b>。</p></div></section>
<section class="kpis"><article class="kpi"><span>原始准确率</span><b>{_pct(classification['accuracy'])}</b><span>{classification['correct']} / {classification['total']}</span></article><article class="kpi"><span>Macro-F1</span><b>{_pct(macro_f1)}</b><span>十三分支等权平均</span></article><article class="kpi"><span>M1直进准确率</span><b>{_pct(gate['direct_accuracy'])}</b><span>{gate['direct_correct']} / {gate['direct']}</span></article><article class="kpi"><span>危险误路由</span><b>{gate['dangerous_misroutes']}</b><span>{_pct(gate['dangerous_rate'],3)} / 成功调用</span></article></section>

<section class="section"><h2>1. 工作流程与测试边界</h2><div class="callout">用户输入 → M7短期历史 → <b>1.7B输出a～m与logprobs</b> → top1与margin满足阈值则M1直进；否则交M3/9B工具面板。本报告直接调用1.7B，不让M3掩盖初判错误，但离线复现生产门控。</div><p>真值直接采用 raw 的 label。流程图中的“i=再见”为绘图瑕疵，本报告按生产代码使用 <b>l=再见</b>、<b>i=查询时间日期</b>。</p></section>

<section class="section"><h2>2. 抽样与调用口径</h2><p>每分支固定抽样 {_e(manifest.get('per_label'))} 条，分层键为 ASR 噪声、轮次（1/2/3/4+）和 hard_pair 是否存在；固定种子 {_e(manifest.get('seed'))}。多轮 history 原样送入生产分类提示词，label、来源文件和分层字段不进入模型。</p><p>有效标签 {classification['valid_labels']}，无效输出 {classification['invalid_labels']}，调用失败 {gate['call_failures']}；生产严格门槛为 top1 &gt; 0.98055846 且 margin &gt; 0。</p></section>

<section class="section"><h2>3. 十三个分支成绩</h2><div class="scroll"><table><thead><tr><th>标签</th><th>分支</th><th>正确</th><th>Precision</th><th>Recall</th><th>F1</th><th>M1直进</th><th>直进准确率</th><th>危险</th></tr></thead><tbody>{''.join(branch_rows)}</tbody></table></div></section>

<section class="section"><h2>4. 13×13 混淆矩阵</h2><p>行是真值，列是1.7B预测；绿色为对角线，红色为误判。</p><div class="scroll"><table><thead><tr><th>真值＼预测</th>{matrix_head}</tr></thead><tbody>{''.join(matrix_rows)}</tbody></table></div><div class="mini" style="margin-top:14px"><h3>主要混淆方向</h3><table><thead><tr><th>方向</th><th>数量</th></tr></thead><tbody>{confusion_rows}</tbody></table></div></section>

<section class="section"><h2>5. ASR、多轮与 hard_pair 分层</h2><div class="grid">{_stratum_table('ASR 噪声', strata['asr_noise'])}{_stratum_table('多轮上下文', strata['rounds'])}{_stratum_table('hard_pair 是否存在', strata['hard_pair_presence'])}{_stratum_table('hard_pair 组合', strata['hard_pair'])}</div></section>

<section class="section"><h2>6. M1 门控与时延</h2><div class="grid"><div class="mini"><h3>门控</h3><p>成功调用：{gate['call_success']}；M1直进：{gate['direct']}（{_pct(gate['coverage'])}）；转M3：{gate['m3_handoff']}（{_pct(gate['m3_handoff_rate'])}）。</p><p>直进正确：{gate['direct_correct']}；危险误路由：{gate['dangerous_misroutes']}。</p></div><div class="mini"><h3>模型调用时延（ms）</h3><p>平均 {_num(latency['average'])} · P50 {_num(latency['p50'])} · P95 {_num(latency['p95'])} · P99 {_num(latency['p99'])} · 最大 {_num(latency['max'])}</p></div></div><h3 style="margin-top:18px">Top1阈值扫描</h3><p>只改变top1阈值，margin仍严格大于0；用于观察覆盖率与高置信风险的权衡。</p><div class="scroll"><table><thead><tr><th>Top1阈值</th><th>直进数</th><th>覆盖率</th><th>直进准确率</th><th>危险数</th><th>危险率</th></tr></thead><tbody>{sweep_rows}</tbody></table></div></section>

<section class="section"><h2>7. 错误样本</h2><div class="callout">按已确认口径，raw label 是唯一真值，报告不会人工改标。若某些不一致样本的当前句和上下文在语义上明显更接近模型预测（例如产品查询语料中出现直接设备指令），仍计为模型错误，但应在调整阈值或重训前优先复核语料。</div><p>优先展示高置信危险误路由，再按top1降序；最多30条。所有用户文本均做HTML转义。</p><div class="scroll"><table><thead><tr><th>ID</th><th>真值</th><th>预测/异常</th><th>用户文本</th><th>top1</th><th>危险</th></tr></thead><tbody>{''.join(error_rows)}</tbody></table></div></section>

<section class="section"><h2>8. 验收结论</h2><table><thead><tr><th>项目</th><th>门槛</th><th>结果</th></tr></thead><tbody><tr><td>原始分类能力</td><td>macro-F1 ≥95%通过；90%～95%有条件通过</td><td><span class="tag {'pass' if classification_status=='通过' else 'warn' if classification_status=='有条件通过' else 'fail'}">{classification_status}</span></td></tr><tr><td>M1门控安全</td><td>直进准确率≥99.5%，危险误路由率≤0.1%</td><td><span class="tag {'pass' if gate_pass else 'fail'}">{'通过' if gate_pass else '不通过'}</span></td></tr><tr><td>调用稳定性</td><td>失败率≤1%</td><td><span class="tag {'pass' if (gate['call_failure_rate'] or 0)<=.01 else 'fail'}">{_pct(gate['call_failure_rate'])}</span></td></tr></tbody></table></section>

<section class="section"><h2>9. 建议与优先级</h2><ol><li><b>先复核高置信不一致语料：</b>按raw口径，危险样本集中标签为 {_e(', '.join(danger_labels) or '无')}。在修改阈值或重训前，逐条核对当前句、history与标签定义，避免用疑似错标校准门控。</li><li><b>采用按分支门控：</b>本批无高置信误路由的标签为 {_e(', '.join(safe_labels) or '无')}，不必跟随风险分支一刀切抬高阈值；风险分支可暂时全部转M3，或单独标定阈值与hard_pair规则。</li><li><b>优先增强最弱分支：</b>{_e(weakest_label)}（{_e(weakest['name'])}）Recall为 {_pct(weakest['recall'])}。结合主要混淆方向补充对比语料，而不是只追加同义改写。</li><li><b>保留噪声和多轮回归：</b>ASR噪声、2轮上下文与hard_pair应继续作为固定回归切片；每次重训必须同时报告总体与切片指标。</li><li><b>谨慎使用全局阈值：</b>阈值扫描仅用于安全权衡。覆盖率大幅下降时，系统成本会转移到M3/9B；优先做语料审计和分支化门控。</li></ol></section>

<section class="section"><h2>10. 生产完整性</h2><p>测试前后 Agent PID：{_e(before.get('agent_pid'))} → {_e(after.get('agent_pid'))}（{'一致' if process_same else '变化'}）；Python：{_e(before.get('python'))} → {_e(after.get('python'))}。</p><div class="scroll"><table><thead><tr><th>文件</th><th>测试前SHA-256</th><th>状态</th></tr></thead><tbody>{''.join(integrity_rows)}</tbody></table></div></section>
<footer>隔离评测目录不启动Agent、不改生产文件；逐条结果、固定抽样集与manifest随报告一并交付。</footer>
</main></body></html>"""
    return html_doc


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--integrity-before", required=True, type=Path)
    parser.add_argument("--integrity-after", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    results = [json.loads(line) for line in args.results.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    report = generate_report(_load(args.summary), results, _load(args.manifest),
                             _load(args.integrity_before), _load(args.integrity_after))
    args.output.write_text(report, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
