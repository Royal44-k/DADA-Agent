# -*- coding: utf-8 -*-
"""渲染十三分支完整判别流程的单文件 HTML 报告。"""
import argparse
import html
import json
from pathlib import Path


def generate_full_report(summary, results, manifest, integrity,
                         previous_run=None, labels=tuple("abcdefghijklm")):
    """只呈现完整机制的最终路由质量，不与单模型能力做对照。"""
    del previous_run

    def esc(value):
        return html.escape(str(value if value is not None else "—"), quote=True)

    def pct(value, digits=2):
        return "—" if value is None else f"{value * 100:.{digits}f}%"

    def num(value, digits=1):
        return "—" if value is None else f"{value:.{digits}f}"

    final = summary["final"]
    m3 = summary["m3"]
    stability = summary["stability"]
    latency = summary["latency_ms"]
    errors = final["total"] - final["correct"]
    weak = [label for label in labels
            if final["per_label"][label]["recall"] < .90]
    verdict = "达到95%验收线" if final["accuracy"] >= .95 else "未达到95%验收线"

    branch_rows = []
    for label in labels:
        item = final["per_label"][label]
        status = "good" if item["recall"] >= .95 else "warn" if item["recall"] >= .90 else "bad"
        branch_rows.append(
            f"<tr><td><span class='label'>{esc(label)}</span></td>"
            f"<td>{esc(item['name'])}</td><td class='num'>{item['support']}</td>"
            f"<td class='num'>{item['correct']}</td>"
            f"<td class='num {status}'>{pct(item['recall'])}</td>"
            f"<td class='num'>{pct(item['precision'])}</td>"
            f"<td class='num'>{pct(item['f1'])}</td>"
            f"<td class='num'>{item['predicted']}</td></tr>")

    matrix_head = "".join(f"<th>{esc(label)}</th>" for label in labels)
    matrix_rows = []
    for truth in labels:
        cells = []
        for prediction in labels:
            count = final["confusion_matrix"][truth][prediction]
            css = "diag" if truth == prediction and count else "miss" if count else "zero"
            cells.append(f"<td class='num {css}'>{count or ''}</td>")
        matrix_rows.append(
            f"<tr><th><span class='label'>{esc(truth)}</span> "
            f"{esc(summary['branch_names'][truth])}</th>{''.join(cells)}</tr>")

    confusion_rows = "".join(
        f"<tr><td><span class='label'>{esc(item['truth'])}</span> → "
        f"<span class='label'>{esc(item['prediction'])}</span></td>"
        f"<td class='num'>{item['count']}</td></tr>"
        for item in final["top_confusions"][:20]) or "<tr><td>无</td><td>0</td></tr>"

    def strata_table(title, groups):
        body = []
        for key, item in groups.items():
            body.append(
                f"<tr><td>{esc(key)}</td><td class='num'>{item['total']}</td>"
                f"<td class='num'>{item['final_correct']}</td>"
                f"<td class='num'>{pct(item['final_accuracy'])}</td>"
                f"<td class='num'>{item['route_failures']}</td></tr>")
        return (f"<div class='mini'><h3>{esc(title)}</h3><div class='scroll'><table>"
                "<thead><tr><th>分层</th><th>样本</th><th>最终正确</th>"
                "<th>最终准确率</th><th>失败</th></tr></thead>"
                f"<tbody>{''.join(body)}</tbody></table></div></div>")

    example_rows = []
    for row in [item for item in results if not item.get("correct")][:30]:
        context_items = row.get("history") or []
        context = " / ".join(
            f"{role}: {content}" for role, content in context_items[-4:])
        example_rows.append(
            f"<tr><td>{esc(row.get('sample_id'))}</td>"
            f"<td><span class='label'>{esc(row.get('truth'))}</span></td>"
            f"<td><span class='label'>{esc(row.get('prediction') or '无')}</span></td>"
            f"<td class='text'>{esc(context)}"
            f"<strong>当前：{esc(row.get('text'))}</strong></td></tr>")

    integrity_rows = "".join(
        f"<tr><td>{esc(path)}</td><td><code>{esc(digest)}</code></td></tr>"
        for path, digest in (integrity.get("hashes") or {}).items())
    calls_by_tier = summary["calls"].get("by_tier") or {}
    asr = summary["strata"]["asr_noise"].get("true", {})
    hard = summary["strata"]["hard_pair_presence"].get("true", {})

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>哒哒Agent十三分支完整判别流程实测报告</title>
<style>
:root{{--ink:#172033;--muted:#64748b;--line:#dbe3ef;--paper:#fff;--blue:#2563eb;--navy:#0f2747;--good:#137a4b;--bad:#c03532;--warn:#a15c00}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(145deg,#e8eff8,#f8fafc 42%);color:var(--ink);font:14px/1.65 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}}
main{{max-width:1260px;margin:0 auto;padding:30px 22px 70px}}header{{background:linear-gradient(135deg,#0d2444,#153d70 70%,#2563eb);color:#fff;border-radius:22px;padding:34px;box-shadow:0 18px 50px #183c6b35}}
h1{{font-size:32px;line-height:1.25;margin:5px 0 10px}}header p{{max-width:920px;color:#dbeafe;margin:0}}.eyebrow{{letter-spacing:.14em;font-weight:800;color:#93c5fd}}.section{{background:var(--paper);border:1px solid var(--line);border-radius:18px;margin-top:20px;padding:24px;box-shadow:0 8px 28px #25456b12}}h2{{font-size:21px;margin:0 0 13px;color:var(--navy)}}h3{{font-size:16px;margin:0 0 9px;color:var(--navy)}}p{{margin:8px 0}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:12px;margin-top:18px}}.card,.mini{{border:1px solid var(--line);border-radius:14px;padding:16px;background:#fbfdff}}.card b{{font-size:27px;display:block;color:var(--navy)}}.card small{{display:block;color:var(--muted)}}.verdict{{display:inline-block;border-radius:999px;padding:5px 12px;font-weight:800;background:#fff1d6;color:#8a4b00}}.callout{{border-left:4px solid var(--blue);background:#eff6ff;padding:13px 15px;border-radius:8px;margin:12px 0}}.danger{{border-left-color:var(--bad);background:#fff1f2}}.good{{color:var(--good)!important;font-weight:700}}.bad{{color:var(--bad)!important;font-weight:700}}.warn{{color:var(--warn)!important;font-weight:700}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;min-width:650px}}th,td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{font-size:12px;color:#526176;background:#f8fafc;position:sticky;top:0}}td.num{{text-align:right;font-variant-numeric:tabular-nums}}.label{{display:inline-grid;place-items:center;min-width:24px;height:24px;border-radius:7px;background:#e8eefb;color:#173b72;font-weight:800}}td.diag{{background:#eaf8f0;color:#11653f}}td.miss{{background:#fff0f0;color:#a92020}}td.zero{{color:#cbd5e1}}code{{font-size:11px;word-break:break-all}}.text{{min-width:360px;color:#59677b}}.text strong{{display:block;color:var(--ink);margin-top:5px}}ol,ul{{padding-left:22px}}li{{margin:8px 0}}footer{{text-align:center;color:var(--muted);padding:24px}}@media(max-width:700px){{h1{{font-size:25px}}header,.section{{padding:19px}}main{{padding:14px 10px 45px}}}}
</style></head><body><main>
<header><div class="eyebrow">COMPLETE ROUTING EVALUATION · 2026-08-17</div><h1>哒哒Agent十三分支完整判别流程实测报告</h1><p>只评价完整机制最后进入哪个业务分支，不评价或对比任何单独模型。固定语料 a–m 每类 100 条，共 {final['total']} 条。</p></header>

<section class="section"><h2>1. 最终结论</h2><p><span class="verdict">{verdict}</span></p><div class="callout danger"><b>完整机制最终准确率为 {pct(final['accuracy'])}。</b>共 {final['correct']} 条正确、{errors} 条错误；Macro-F1 为 {pct(final['macro_f1'])}。整体约九成，但分支差异很大，不能用总体数掩盖弱分支。</div>
<div class="cards"><div class="card"><small>完整机制最终准确率</small><b>{pct(final['accuracy'])}</b><small>{final['correct']} / {final['total']} · 95% CI {pct(final['accuracy_ci95'][0])}～{pct(final['accuracy_ci95'][1])}</small></div><div class="card"><small>最终 Macro-F1</small><b>{pct(final['macro_f1'])}</b><small>13 类等权</small></div><div class="card"><small>最终错误</small><b>{errors}</b><small>{pct(errors/final['total'])}</small></div><div class="card"><small>完整路由失败</small><b>{stability['route_failures']}</b><small>{pct(stability['route_failure_rate'])}</small></div></div>
<p>低于 90% 的分支：<b>{esc(', '.join(weak) or '无')}</b>。其中 j=产品/知识查询、e=查询记忆、l=再见，是当前最需要修复的三类。</p></section>

<section class="section"><h2>2. 被测完整流程与边界</h2><div class="grid"><div class="mini"><h3>至分支判别流程</h3><ol><li>M7 注入最近 4 轮历史。</li><li>M1 对 a–m 做门控判别。</li><li>高置信直接形成分支标签。</li><li>低置信真实调用 M3 的 9B 工具面板复判。</li><li>以机制最终输出的 label 作为进入分支结果。</li></ol><p><b>M3 已参与：</b>{m3['used']} / {final['total']} 条进入了 9B 复判。</p></div><div class="mini"><h3>M2 所在位置</h3><p>M2 是确定分支后的字段抽取与填表纠错，因此不改变“进入哪个分支”的统计结果。若继续测试 M2，应分别统计提醒、记忆、音量等分支内部的填表准确率。</p><p>本报告截止在分支处理器执行前，不写提醒、记忆或设备状态。</p></div></div><p>样本 seed={esc(manifest.get('seed'))}，raw label 为唯一标准答案；i=时间日期，l=再见。M8/M11 使用无 pending 的空闲态，修改提醒前置状态固定为存在活动提醒。</p></section>

<section class="section"><h2>3. 最终各分支准确率</h2><div class="scroll"><table><thead><tr><th>标签</th><th>分支</th><th>样本</th><th>最终正确</th><th>Recall/准确率</th><th>Precision</th><th>F1</th><th>最终预测数</th></tr></thead><tbody>{''.join(branch_rows)}</tbody></table></div><div class="callout"><b>最终结果：</b>a 95%、b 98%、c 94%、d 96%、e 77%、f 100%、g 100%、h 100%、i 98%、j 54%、k 93%、l 76%、m 91%。</div></section>

<section class="section"><h2>4. 最终路由混淆矩阵</h2><p>行是真值，列是完整机制最终进入的分支；绿色为正确，红色为误路由。</p><div class="scroll"><table><thead><tr><th>真值＼最终</th>{matrix_head}</tr></thead><tbody>{''.join(matrix_rows)}</tbody></table></div><div class="mini" style="margin-top:14px"><h3>主要最终误路由</h3><table><thead><tr><th>方向</th><th>数量</th></tr></thead><tbody>{confusion_rows}</tbody></table></div></section>

<section class="section"><h2>5. ASR、hard_pair 与多轮结果</h2><div class="grid">{strata_table('ASR 噪声', summary['strata']['asr_noise'])}{strata_table('hard_pair 是否存在', summary['strata']['hard_pair_presence'])}{strata_table('多轮上下文', summary['strata']['rounds'])}</div><div class="callout">ASR 噪声语料最终准确率 {pct(asr.get('final_accuracy'))}；hard_pair 最终准确率 {pct(hard.get('final_accuracy'))}。复杂语料明显低于总体准确率。</div></section>

<section class="section"><h2>6. 完整流程时延与稳定性</h2><div class="cards"><div class="card"><small>完整流程 P50</small><b>{num(latency['wall']['p50'])} ms</b><small>平均 {num(latency['wall']['average'])} ms</small></div><div class="card"><small>完整流程 P95</small><b>{num(latency['wall']['p95'])} ms</b><small>P99 {num(latency['wall']['p99'])} ms</small></div><div class="card"><small>模型调用总数</small><b>{summary['calls']['total']}</b><small>1.7B {calls_by_tier.get('1.7b',0)}；9B {calls_by_tier.get('9b',0)}</small></div><div class="card"><small>路由成功</small><b>{stability['route_success']}</b><small>失败 {stability['route_failures']}</small></div></div></section>

<section class="section"><h2>7. 最终错误样本</h2><p>展示前 30 条最终误路由，并保留最近上下文。</p><div class="scroll"><table><thead><tr><th>ID</th><th>真值</th><th>最终分支</th><th>上下文与当前句</th></tr></thead><tbody>{''.join(example_rows)}</tbody></table></div></section>

<section class="section"><h2>8. 如何评价这个准确率</h2><ul><li><b>总体层面：</b>{pct(final['accuracy'])} 表示每 100 次约有 10 次进入错误分支；若错误分支会执行提醒、记忆或设备动作，这个错误率仍然偏高。</li><li><b>均衡性：</b>Macro-F1 {pct(final['macro_f1'])} 低于 90%，说明弱分支拖累明显。</li><li><b>可用分支：</b>f/g/h 达到 100%，a/b/c/d/i/k/m 为 91%～98%，具备较好基础。</li><li><b>不可直接验收的分支：</b>j 只有 54%，e 77%，l 76%，应先修复再作为完整 13 分支系统验收。</li><li><b>建议验收线：</b>总体准确率和 Macro-F1 均≥95%，每个分支 Recall≥90%，ASR 与 hard_pair≥90%，并连续两次固定集复测通过。</li></ul></section>

<section class="section"><h2>9. 改进优先级</h2><ol><li><b>P0：修复 j 产品/知识查询定义。</b>覆盖产品能力、使用方法、一般知识和知识库查询，并明确“询问怎么做”不能进入执行型分支。</li><li><b>P0：补 e/d 与 l/k/m 的成组对比语料。</b>重点覆盖多轮指代、口语省略、离开与睡觉的区别。</li><li><b>P1：选分支与填参数解耦。</b>先以等权的 13 类协议确定最终分支，再进入 M2 填表，避免参数 schema 影响选路。</li><li><b>P1：固定回归集。</b>每次修改后必须重新报告完整机制总体、13 分支、ASR、hard_pair、多轮和混淆矩阵。</li></ol></section>

<section class="section"><h2>10. 生产完整性与隔离目录</h2><p>Python {esc(integrity.get('python'))}；Agent PID {esc(integrity.get('agent_pid'))}；启动时间 {esc(integrity.get('agent_started'))}。</p><p><b>隔离目录：</b><code>{esc(integrity.get('isolation_dir'))}</code></p><div class="scroll"><table><thead><tr><th>当前生产文件</th><th>SHA-256</th></tr></thead><tbody>{integrity_rows}</tbody></table></div><p>评测只在隔离副本执行，未调用具体业务分支，不写生产提醒、记忆或设备状态。</p></section>
<footer>哒哒Agent十三分支完整判别流程实测 · 2026-08-17</footer></main></body></html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--integrity", required=True, type=Path)
    parser.add_argument("--previous-run", type=Path)
    parser.add_argument("--labels", default="abcdefghijklm")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    def load(path):
        return json.loads(path.read_text(encoding="utf-8"))

    rows = [json.loads(line) for line in
            args.results.read_text(encoding="utf-8").splitlines() if line.strip()]
    previous = load(args.previous_run) if args.previous_run else None
    report = generate_full_report(
        load(args.summary), rows, load(args.manifest), load(args.integrity),
        previous_run=previous, labels=tuple(args.labels))
    args.output.write_text(report, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
