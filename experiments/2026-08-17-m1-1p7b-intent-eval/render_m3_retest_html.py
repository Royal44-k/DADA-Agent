# -*- coding: utf-8 -*-
"""Render the 2026-08-18 M3 full-flow retest report and failure dataset."""
import argparse
import html
import json
from collections import Counter, defaultdict
from pathlib import Path


REPORT_FILENAME = "哒哒Agent-M3机制完善后完整流程复测报告-2026-08-18.html"
FAILURE_FILENAME = "哒哒Agent-M3机制完善后失败测试集-272条-2026-08-18.html"

BRANCH_NAMES = {
    "a": "新建提醒",
    "b": "修改/取消/完成提醒",
    "c": "查询提醒",
    "d": "增删改记忆",
    "e": "查询记忆",
    "f": "调整音量",
    "g": "调整亮度",
    "h": "查询天气",
    "i": "查询时间日期",
    "j": "产品/知识查询",
    "k": "晚安",
    "l": "再见",
    "m": "闲聊/其他",
}

ERROR_NAMES = {
    "route_failure": "M3路由失败",
    "m3_introduced": "M3新增误判",
    "m3_unresolved": "M3未纠正",
    "m1_direct": "M1高置信直错",
}

ERROR_ORDER = {
    "route_failure": 0,
    "m3_introduced": 1,
    "m3_unresolved": 2,
    "m1_direct": 3,
}

PRODUCTION_HASHES = {
    "dada/mechanisms/m1_gate.py": "fccb34c386c86a75e56191ceb6139deb37a355f56520bea0e0c292ff2bce8b8c",
    "dada/mechanisms/m3_tool_panel.py": "177af9e74815bd2d44268837717bebc4ee66c31a8b3b2b07e56b7d93291bc4b2",
    "dada/infra/llm.py": "1403e95eb8a8eb8e5b8820de3c82c39aa12efff31a428f3276ae2f8ab0f48075",
    "dada/infra/prompts/branch_prompts.py": "6f47917cb15696f33098591cba2c44ec89a8a1a6975446c1179353c4d5d5e53b",
}

RESULT_SHA256 = "12626dca31bff691bb5662f1826bb97900c2ca6e5f5e4a4060910530fa3fd392"


def h(value):
    return html.escape("" if value is None else str(value), quote=True)


def load_rows(path):
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def percent(numerator, denominator, digits=2):
    return f"{100 * numerator / denominator:.{digits}f}%" if denominator else "—"


def classify_error(row):
    if row.get("correct"):
        return None
    if not row.get("route_ok"):
        return "route_failure"
    if row.get("m1_direct"):
        return "m1_direct"
    if row.get("m3_used") and row.get("m1_correct"):
        return "m3_introduced"
    if row.get("m3_used") and not row.get("m1_correct"):
        return "m3_unresolved"
    raise ValueError(f"无法归类的失败样本: {row.get('sample_id')}")


def compute_metrics(old_rows, new_rows):
    if len(old_rows) != 1300 or len(new_rows) != 1300:
        raise ValueError("新旧结果必须各有1300条")
    old_by_id = {row["sample_id"]: row for row in old_rows}
    new_by_id = {row["sample_id"]: row for row in new_rows}
    if len(old_by_id) != 1300 or old_by_id.keys() != new_by_id.keys():
        raise ValueError("新旧样本ID不唯一或不一致")

    old_correct = sum(bool(row.get("correct")) for row in old_rows)
    new_correct = sum(bool(row.get("correct")) for row in new_rows)
    failures = [row for row in new_rows if not row.get("correct")]
    error_counts = Counter(classify_error(row) for row in failures)
    attempts = [row for row in new_rows if not row.get("m1_direct")]
    successful_m3 = [row for row in new_rows if row.get("m3_used")]
    route_failures = [row for row in new_rows if not row.get("route_ok")]

    migration = Counter()
    fixed_by_truth = Counter()
    regressed_by_truth = Counter()
    for sample_id, new_row in new_by_id.items():
        old_row = old_by_id[sample_id]
        if old_row.get("correct") and new_row.get("correct"):
            migration["both_correct"] += 1
        elif not old_row.get("correct") and new_row.get("correct"):
            migration["fixed"] += 1
            fixed_by_truth[new_row["truth"]] += 1
        elif old_row.get("correct") and not new_row.get("correct"):
            migration["regressed"] += 1
            regressed_by_truth[new_row["truth"]] += 1
        else:
            migration["both_wrong"] += 1

    per_branch = []
    for label, name in BRANCH_NAMES.items():
        old_subset = [row for row in old_rows if row.get("truth") == label]
        new_subset = [row for row in new_rows if row.get("truth") == label]
        old_branch_correct = sum(bool(row.get("correct")) for row in old_subset)
        new_branch_correct = sum(bool(row.get("correct")) for row in new_subset)
        per_branch.append({
            "label": label,
            "name": name,
            "support": len(new_subset),
            "old_correct": old_branch_correct,
            "new_correct": new_branch_correct,
            "delta": new_branch_correct - old_branch_correct,
            "attempts": sum(not row.get("m1_direct") for row in new_subset),
            "m3_success": sum(bool(row.get("m3_used")) for row in new_subset),
            "route_failures": sum(not row.get("route_ok") for row in new_subset),
            "corrected": sum(bool(row.get("m3_corrected")) for row in new_subset),
            "worsened": sum(bool(row.get("m3_worsened")) for row in new_subset),
            "fixed": fixed_by_truth[label],
            "regressed": regressed_by_truth[label],
        })

    def grouped_attempts(key_func):
        groups = defaultdict(list)
        for row in new_rows:
            groups[str(key_func(row))].append(row)
        output = []
        sort_key = {"1": 1, "2": 2, "3": 3, "4+": 4}
        for key in sorted(groups, key=lambda value: sort_key.get(value, value)):
            subset = groups[key]
            group_attempts = [row for row in subset if not row.get("m1_direct")]
            group_failures = [row for row in group_attempts if not row.get("route_ok")]
            output.append({
                "key": key,
                "total": len(subset),
                "attempts": len(group_attempts),
                "success": sum(bool(row.get("m3_used")) for row in group_attempts),
                "failures": len(group_failures),
            })
        return output

    metrics = {
        "old_correct": old_correct,
        "old_errors": len(old_rows) - old_correct,
        "new_correct": new_correct,
        "new_errors": len(new_rows) - new_correct,
        "old_accuracy": old_correct / len(old_rows),
        "new_accuracy": new_correct / len(new_rows),
        "accuracy_delta_pp": 100 * (new_correct - old_correct) / len(new_rows),
        "old_m1_correct": sum(bool(row.get("m1_correct")) for row in old_rows),
        "new_m1_correct": sum(bool(row.get("m1_correct")) for row in new_rows),
        "attempts": len(attempts),
        "m3_success": len(successful_m3),
        "route_failures": len(route_failures),
        "m3_corrected": sum(bool(row.get("m3_corrected")) for row in new_rows),
        "m3_worsened": sum(bool(row.get("m3_worsened")) for row in new_rows),
        "m3_success_initial_correct": sum(bool(row.get("m1_correct")) for row in successful_m3),
        "m3_success_final_correct": sum(bool(row.get("correct")) for row in successful_m3),
        "failure_initial_correct": sum(bool(row.get("m1_correct")) for row in route_failures),
        "failure_initial_wrong": sum(not row.get("m1_correct") for row in route_failures),
        "error_counts": error_counts,
        "migration": migration,
        "per_branch": per_branch,
        "rounds": grouped_attempts(lambda row: row.get("rounds_bucket") or "unknown"),
        "asr": grouped_attempts(lambda row: "有ASR噪声" if row.get("asr_noise") else "无ASR噪声"),
        "tag_counts": Counter(
            tag for row in successful_m3 for tag in (row.get("m3_tags") or [])
        ),
        "failures": failures,
    }
    if error_counts != Counter({
        "route_failure": 245,
        "m3_introduced": 15,
        "m3_unresolved": 6,
        "m1_direct": 6,
    }):
        raise ValueError(f"失败分类与已验收结果不一致: {error_counts}")
    if migration != Counter({
        "both_correct": 1023,
        "both_wrong": 123,
        "regressed": 149,
        "fixed": 5,
    }):
        raise ValueError(f"新旧迁移与已验收结果不一致: {migration}")
    return metrics


COMMON_CSS = r"""
:root{--ink:#172033;--muted:#64748b;--line:#dbe3ef;--paper:#fff;--bg:#eef3f8;--blue:#2563eb;--navy:#0f2747;--good:#137a4b;--bad:#c03532;--warn:#a15c00;--violet:#6d28d9}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:linear-gradient(145deg,#e8eff8,#f8fafc 42%);color:var(--ink);font:14px/1.65 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
main{max-width:1320px;margin:0 auto;padding:30px 22px 70px}header{background:linear-gradient(135deg,#0d2444,#153d70 68%,#2563eb);color:#fff;border-radius:22px;padding:34px;box-shadow:0 18px 50px #183c6b35;position:relative;overflow:hidden}header:after{content:"";position:absolute;width:290px;height:290px;border-radius:50%;right:-80px;top:-150px;background:#60a5fa26}
h1{font-size:32px;line-height:1.25;margin:5px 0 10px;position:relative}header p{max-width:970px;color:#dbeafe;margin:0;position:relative}.eyebrow{letter-spacing:.14em;text-transform:uppercase;font-weight:800;color:#93c5fd}.topnav{display:flex;flex-wrap:wrap;gap:9px;margin-top:20px;position:relative}.topnav a{color:#fff;text-decoration:none;border:1px solid #ffffff55;background:#ffffff12;border-radius:999px;padding:7px 13px;font-weight:700}.topnav a:hover{background:#ffffff25}
.section{background:var(--paper);border:1px solid var(--line);border-radius:18px;margin-top:20px;padding:24px;box-shadow:0 8px 28px #25456b12}h2{font-size:21px;margin:0 0 13px;color:var(--navy)}h3{font-size:16px;margin:0 0 9px;color:var(--navy)}p{margin:8px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:12px;margin-top:18px}.card,.mini{border:1px solid var(--line);border-radius:14px;padding:16px;background:#fbfdff}.card b{font-size:27px;display:block;color:var(--navy)}.card small,.num small{display:block;color:var(--muted)}.verdict{display:inline-block;border-radius:999px;padding:5px 12px;font-weight:800;background:#fee2e2;color:#991b1b}.callout{border-left:4px solid var(--blue);background:#eff6ff;padding:13px 15px;border-radius:8px;margin:12px 0}.danger{border-left-color:var(--bad);background:#fff1f2}.warning{border-left-color:#f59e0b;background:#fffbeb}.good{color:var(--good)!important;font-weight:700}.bad{color:var(--bad)!important;font-weight:700}.muted{color:var(--muted)}
.scroll{overflow:auto}table{border-collapse:collapse;width:100%;min-width:680px}th,td{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{font-size:12px;color:#526176;background:#f8fafc;position:sticky;top:0;z-index:1}td.num{text-align:right;font-variant-numeric:tabular-nums}.label{display:inline-grid;place-items:center;min-width:24px;height:24px;border-radius:7px;background:#e8eefb;color:#173b72;font-weight:800}code{font-size:11px;word-break:break-all}ol,ul{padding-left:22px}li{margin:7px 0}.flow{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;align-items:stretch}.flow .node{border:1px solid var(--line);border-radius:13px;padding:14px;background:#f8fafc;position:relative}.flow .node b{font-size:20px;display:block;color:var(--navy)}.flow .node.bad-node{background:#fff1f2;border-color:#fecdd3}.flow .node.good-node{background:#ecfdf5;border-color:#bbf7d0}footer{text-align:center;color:var(--muted);padding:24px}
@media(max-width:800px){h1{font-size:25px}header,.section{padding:19px}main{padding:14px 10px 45px}.flow{grid-template-columns:1fr 1fr}}@media(max-width:480px){.flow{grid-template-columns:1fr}}
"""


def branch_rows_html(metrics):
    rows = []
    for item in metrics["per_branch"]:
        delta_class = "good" if item["delta"] > 0 else "bad" if item["delta"] < 0 else "muted"
        rows.append(
            "<tr>"
            f"<td><span class='label'>{h(item['label'])}</span></td>"
            f"<td>{h(item['name'])}</td>"
            f"<td class='num'>{item['old_correct']}<small>{percent(item['old_correct'], item['support'])}</small></td>"
            f"<td class='num'>{item['new_correct']}<small>{percent(item['new_correct'], item['support'])}</small></td>"
            f"<td class='num {delta_class}'>{item['delta']:+d}</td>"
            f"<td class='num'>{item['attempts']}</td>"
            f"<td class='num'>{item['m3_success']}</td>"
            f"<td class='num bad'>{item['route_failures']}</td>"
            f"<td class='num good'>{item['fixed']}</td>"
            f"<td class='num bad'>{item['regressed']}</td>"
            "</tr>"
        )
    return "".join(rows)


def slice_rows_html(items):
    return "".join(
        "<tr>"
        f"<td>{h(item['key'])}</td>"
        f"<td class='num'>{item['total']}</td>"
        f"<td class='num'>{item['attempts']}</td>"
        f"<td class='num'>{item['success']}</td>"
        f"<td class='num bad'>{item['failures']}</td>"
        f"<td class='num'>{percent(item['failures'], item['attempts'])}</td>"
        "</tr>"
        for item in items
    )


def render_report(metrics):
    e = metrics["error_counts"]
    m = metrics["migration"]
    hash_rows = "".join(
        f"<tr><td>{h(path)}</td><td><code>{digest}</code></td></tr>"
        for path, digest in PRODUCTION_HASHES.items()
    )
    report = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>哒哒Agent M3机制完善后完整流程复测报告</title><style>{COMMON_CSS}</style></head><body>
<main id="report" data-total="1300" data-old-correct="{metrics['old_correct']}" data-new-correct="{metrics['new_correct']}" data-final-errors="{metrics['new_errors']}" data-route-failures="{metrics['route_failures']}">
<header><div class="eyebrow">FULL-FLOW SERVER RETEST · 2026-08-18</div><h1>哒哒Agent M3机制完善后完整流程复测报告</h1><p>同一批1300条固定语料，完整执行M1高置信门控与M3真实9B复判；以raw label作为标准答案，统计最终进入a–m业务分支的结果。</p><nav class="topnav"><a href="#{'verdict'}">结论</a><a href="#branches">分支结果</a><a href="#root-cause">失败根因</a><a href="{h(FAILURE_FILENAME)}">打开272条失败测试集</a></nav></header>

<section class="section" id="verdict"><h2>1. 结论先行</h2><p><span class="verdict">不通过</span></p>
<div class="callout danger"><b>新版M3没有形成端到端优化。</b>完整流程准确率从{percent(metrics['old_correct'],1300)}下降到{percent(metrics['new_correct'],1300)}，减少{abs(metrics['accuracy_delta_pp']):.2f}个百分点。核心原因不是M1初判退化，而是287次M3交接中有245次没有返回最终分支。</div>
<div class="cards"><div class="card"><small>新版最终准确率</small><b>{percent(metrics['new_correct'],1300)}</b><small>{metrics['new_correct']} / 1300</small></div><div class="card"><small>旧版最终准确率</small><b>{percent(metrics['old_correct'],1300)}</b><small>{metrics['old_correct']} / 1300</small></div><div class="card"><small>新版最终错误</small><b>{metrics['new_errors']}</b><small>较旧版增加 {metrics['new_errors']-metrics['old_errors']}</small></div><div class="card"><small>M3交接 / 成功</small><b>{metrics['attempts']} / {metrics['m3_success']}</b><small>成功返回率 {percent(metrics['m3_success'],metrics['attempts'])}</small></div><div class="card"><small>M3路由失败</small><b>{metrics['route_failures']}</b><small>占交接 {percent(metrics['route_failures'],metrics['attempts'])}</small></div><div class="card"><small>M3纠正 / 引错</small><b>{metrics['m3_corrected']} / {metrics['m3_worsened']}</b><small>仅统计成功返回的42条</small></div></div></section>

<section class="section"><h2>2. 测试范围与口径</h2><div class="grid"><div class="mini"><h3>固定输入</h3><ul><li>13个分支a–m，每分支100条，共1300条。</li><li>与2026-08-17旧版结果使用相同sample_id和raw label。</li><li>包含ASR噪声、hard_pair和1/2/3/4+轮上下文。</li><li>流程内M1初判仅用于归因，不作为独立模型能力对比。</li></ul></div><div class="mini"><h3>真实链路</h3><ol><li>1.7B输出标签与首token logprob。</li><li>高置信直接进入M1标签。</li><li>低置信共287条，真实调用新版9B M3工具面板。</li><li>以M3后的最终标签和raw label比较；没有最终标签计为路由失败。</li></ol></div><div class="mini"><h3>隔离边界</h3><ul><li>只运行到最终分支判别，不执行提醒、记忆或设备动作。</li><li>生产代码只读加载，结果写入服务器隔离评测目录。</li><li>Agent进程未重启；生产文件测试前后哈希一致。</li><li>本地交付逐条结果SHA-256：<code>{RESULT_SHA256}</code></li></ul></div></div></section>

<section class="section"><h2>3. M3路径：进入不等于成功返回</h2><div class="flow"><div class="node"><small>M1低置信交接</small><b>{metrics['attempts']}</b><span>全部尝试进入M3</span></div><div class="node good-node"><small>M3成功返回</small><b>{metrics['m3_success']}</b><span>{percent(metrics['m3_success'],metrics['attempts'])}</span></div><div class="node bad-node"><small>M3路由失败</small><b>{metrics['route_failures']}</b><span>{percent(metrics['route_failures'],metrics['attempts'])}</span></div><div class="node bad-node"><small>M3路径最终正确</small><b>{metrics['m3_success_final_correct']}</b><span>占287条 {percent(metrics['m3_success_final_correct'],metrics['attempts'])}</span></div></div>
<div class="grid" style="margin-top:14px"><div class="mini"><h3>失败前的M1状态</h3><p>245条路由失败中，M1原本正确 <b>{metrics['failure_initial_correct']}</b> 条，M1原本错误 <b>{metrics['failure_initial_wrong']}</b> 条。异常路径直接丢失了大量原本可用的初判结果。</p></div><div class="mini"><h3>成功返回的42条</h3><p>M3前正确 {metrics['m3_success_initial_correct']} 条，M3后正确 {metrics['m3_success_final_correct']} 条；纠正 {metrics['m3_corrected']} 条、引错 {metrics['m3_worsened']} 条，净减少 {metrics['m3_success_initial_correct']-metrics['m3_success_final_correct']} 条正确结果。</p></div><div class="mini"><h3>证据机制实际触发</h3><p>成功返回样本的标签：<code>m3={metrics['tag_counts'].get('m3',0)}</code>、<code>m3_disputed={metrics['tag_counts'].get('m3_disputed',0)}</code>、<code>m3_ev_reject={metrics['tag_counts'].get('m3_ev_reject',0)}</code>。多数请求在证据校验发挥作用前已经失败。</p></div></div></section>

<section class="section"><h2>4. 272条最终错误构成</h2><div class="cards"><div class="card"><small>M3路由失败</small><b>{e['route_failure']}</b><small>{percent(e['route_failure'],metrics['new_errors'])}</small></div><div class="card"><small>M3新增误判</small><b>{e['m3_introduced']}</b><small>M1正确但M3改错</small></div><div class="card"><small>M3未纠正</small><b>{e['m3_unresolved']}</b><small>M1、M3均错误</small></div><div class="card"><small>M1高置信直错</small><b>{e['m1_direct']}</b><small>未进入M3</small></div></div><div class="callout"><b>闭合校验：</b>{e['route_failure']} + {e['m3_introduced']} + {e['m3_unresolved']} + {e['m1_direct']} = {metrics['new_errors']}。<a href="{h(FAILURE_FILENAME)}">查看全部失败测试集</a></div></section>

<section class="section"><h2>5. 旧128条错误与新增回归</h2><div class="cards"><div class="card"><small>旧错被修复</small><b>{m['fixed']}</b><small>j 4条、k 1条</small></div><div class="card"><small>旧错仍错误</small><b>{m['both_wrong']}</b><small>128 - 5</small></div><div class="card"><small>新增回归</small><b>{m['regressed']}</b><small>旧版正确、新版错误</small></div><div class="card"><small>净增错误</small><b>{m['regressed']-m['fixed']}</b><small>149 - 5</small></div></div><div class="callout danger">新版修复5条旧错误，却新增149条回归；修复与回归之比为1 : {m['regressed']/m['fixed']:.1f}。</div></section>

<section class="section" id="branches"><h2>6. 13分支新旧结果</h2><div class="scroll"><table><thead><tr><th>标签</th><th>分支</th><th>旧版正确</th><th>新版正确</th><th>净变化</th><th>M3交接</th><th>M3成功</th><th>路由失败</th><th>修复</th><th>新增回归</th></tr></thead><tbody>{branch_rows_html(metrics)}</tbody></table></div><div class="callout danger"><b>最严重退化：</b>k晚安从93%降至34%，64条路由失败；e查询记忆35条失败，j产品知识32条失败。只有j分支净增加3条正确，但总体仍只有57%。</div></section>

<section class="section"><h2>7. 多轮与ASR切片</h2><div class="grid"><div class="mini"><h3>按上下文轮数</h3><div class="scroll"><table><thead><tr><th>轮数</th><th>样本</th><th>M3交接</th><th>成功</th><th>失败</th><th>交接失败率</th></tr></thead><tbody>{slice_rows_html(metrics['rounds'])}</tbody></table></div></div><div class="mini"><h3>按ASR噪声</h3><div class="scroll"><table><thead><tr><th>切片</th><th>样本</th><th>M3交接</th><th>成功</th><th>失败</th><th>交接失败率</th></tr></thead><tbody>{slice_rows_html(metrics['asr'])}</tbody></table></div></div></div><p class="muted">失败在所有轮数切片均大量出现，说明不是只对极长历史敏感；13工具Schema自身已占用较大的上下文预算。</p></section>

<section class="section" id="root-cause"><h2>8. 失败根因</h2><ol><li><b>9B端点上下文只有8192 token。</b>客户端还设置<code>max_tokens=1024</code>，输入可用预算进一步收紧。</li><li><b>新版工具面板明显膨胀。</b>13工具Schema从7808字符增至10690字符（+36.9%），UTF-8字节数从11292增至16644（+47.4%）；系统提示从164增至255字符。</li><li><b>直接复现的HTTP响应：</b><code>500 Server Error — Context size has been exceeded.</code>。245条失败均发生在低置信M3交接路径，244条只记录到1.7B调用，另1条第一轮9B返回后第二轮失败。</li><li><b>M1吞掉M3异常。</b><code>except Exception</code>直接返回<code>ok=False</code>，没有保留原M1标签，也没有把HTTP错误类型写入逐条结果，最终表现为无分支路由。</li></ol><div class="callout warning"><b>判断：</b><code>intent_evidence</code>方向本身尚未得到充分验收。多数请求在工具选择或证据校验完成前就失败，不能用“引错从87降到15”证明语义纠错变好。</div></section>

<section class="section"><h2>9. 推荐整改方案</h2><ol><li><b>P0：拆成两阶段。</b>第一阶段只让9B输出“最终分支＋逐字依据”，使用轻量枚举或13个空Schema工具；确定分支后，第二阶段只加载该分支表单Schema。</li><li><b>P0：增加token预检。</b>调用9B前通过tokenize计算模板后的完整输入，预留输出预算；超限时裁剪历史或切换轻量面板。</li><li><b>P0：异常必须回退。</b>M3超时、HTTP 500、上下文溢出时保留M1标签，并记录<code>m3_context_overflow</code>或<code>m3_http_error</code>，不能返回无最终分支。</li><li><b>P1：缩短M3输入。</b>证据只允许引用真实用户轮；优先保留当前用户句和解决指代所需的最少历史，不携带无关助手文本。</li><li><b>重新验收：</b>同一1300条中路由失败必须为0，最终准确率高于90.15%，M3纠正数大于引错数，旧错修复数大于新增回归数。</li></ol></section>

<section class="section"><h2>10. 生产完整性与复现材料</h2><p>生产Agent PID 2904190，启动时间2026-08-18 11:27:38 +0800；测试前后进程未重启。生产目录只读加载，测试输出位于隔离目录<code>/home/number/dada-runtime/asr-api-test-env/xiaozhi-server-m1-intent-eval-20260817/eval</code>。</p><div class="scroll"><table><thead><tr><th>生产文件</th><th>SHA-256</th></tr></thead><tbody>{hash_rows}</tbody></table></div><p>本地交付包含本报告、272条失败测试集、新旧逐条JSONL、汇总JSON、生成器和自动化验收测试。</p></section>
<footer>哒哒Agent M3机制完善后完整流程复测 · 2026-08-18</footer></main></body></html>"""
    return report


def format_history(row):
    history = row.get("history") or []
    if not history:
        return "<span class='muted'>无历史上下文</span>"
    parts = []
    for role, content in history:
        role_name = "用户" if role == "user" else "助手"
        parts.append(f"<div class='turn'><b>{role_name}</b><span>{h(content)}</span></div>")
    return "".join(parts)


def format_calls(row):
    calls = row.get("model_calls") or []
    if not calls:
        return "无调用记录"
    return "<br>".join(
        f"<b>{h(call.get('model_tier'))}</b> · {h(call.get('content'))} · {h(call.get('latency_ms'))}ms"
        for call in calls
    )


def render_failure_rows(failures):
    rows = []
    sorted_rows = sorted(
        failures,
        key=lambda row: (ERROR_ORDER[classify_error(row)], row.get("truth", ""), row["sample_id"]),
    )
    for index, row in enumerate(sorted_rows, 1):
        error_type = classify_error(row)
        if error_type == "route_failure":
            path = "m3_failure"
            final_value = "无最终分支"
        elif error_type in ("m3_introduced", "m3_unresolved"):
            path = "m3_success"
            final_value = row.get("prediction") or "无效"
        else:
            path = "m1_direct"
            final_value = row.get("prediction") or "无效"
        confidence = row.get("m1_top1")
        confidence_text = f"{confidence:.4f}" if isinstance(confidence, (int, float)) else "—"
        search_blob = " ".join(
            str(value) for value in (
                row.get("sample_id"), row.get("truth"), row.get("text"),
                row.get("m1_prediction"), row.get("prediction"),
                ERROR_NAMES[error_type], BRANCH_NAMES.get(row.get("truth"), ""),
                json.dumps(row.get("history") or [], ensure_ascii=False),
            ) if value is not None
        ).lower()
        tags = ", ".join(row.get("m3_tags") or []) or "—"
        badges = [f"{row.get('rounds_bucket') or row.get('rounds')}轮"]
        if row.get("asr_noise"):
            badges.append("ASR噪声")
        if row.get("hard_pair"):
            badges.append(f"hard_pair:{row.get('hard_pair')}")
        badge_html = "".join(f"<span class='meta-badge'>{h(item)}</span>" for item in badges)
        rows.append(
            f"<tr class='failure-row' data-sample-id='{h(row['sample_id'])}' data-error-type='{error_type}' data-truth='{h(row.get('truth'))}' data-path='{path}' data-search='{h(search_blob)}'>"
            f"<td class='num'>{index}</td>"
            f"<td><span class='type type-{error_type}'>{h(ERROR_NAMES[error_type])}</span></td>"
            f"<td><span class='label'>{h(row.get('truth'))}</span><small>{h(BRANCH_NAMES.get(row.get('truth')))}</small></td>"
            f"<td><code>{h(row['sample_id'])}</code><div class='badges'>{badge_html}</div></td>"
            f"<td><div class='utterance'>{h(row.get('text'))}</div><details><summary>查看历史上下文</summary>{format_history(row)}</details></td>"
            f"<td><b>{h(row.get('m1_prediction') or '无效')}</b><small>top1 {confidence_text}</small><small>{'高置信直进' if row.get('m1_direct') else '低置信交M3'}</small></td>"
            f"<td><b>{h(final_value)}</b><small>route_ok={str(bool(row.get('route_ok'))).lower()}</small><small>tags: {h(tags)}</small></td>"
            f"<td><details><summary>{row.get('model_call_count') or 0}次模型调用</summary><div class='calls'>{format_calls(row)}</div></details></td>"
            "</tr>"
        )
    return "".join(rows)


FAILURE_CSS = COMMON_CSS + r"""
.filterbar{position:sticky;top:0;z-index:20;background:#ffffffee;backdrop-filter:blur(12px);border:1px solid var(--line);border-radius:16px;padding:13px;margin-top:18px;box-shadow:0 10px 28px #25456b1c}.filters{display:grid;grid-template-columns:minmax(230px,2fr) repeat(3,minmax(145px,1fr)) auto;gap:9px}.filters input,.filters select,.filters button{width:100%;border:1px solid #cbd5e1;border-radius:10px;background:#fff;color:var(--ink);padding:10px 11px;font:inherit}.filters button{background:var(--navy);color:#fff;border-color:var(--navy);cursor:pointer;font-weight:700}.filter-status{display:flex;justify-content:space-between;gap:12px;margin-top:8px;color:var(--muted)}
.failure-table{min-width:1280px}.failure-table th:nth-child(5){min-width:370px}.failure-row small{display:block;color:var(--muted);margin-top:2px}.type{display:inline-block;border-radius:999px;padding:4px 9px;font-size:12px;font-weight:800;white-space:nowrap}.type-route_failure{background:#fee2e2;color:#991b1b}.type-m3_introduced{background:#ffedd5;color:#9a3412}.type-m3_unresolved{background:#ede9fe;color:#5b21b6}.type-m1_direct{background:#e2e8f0;color:#334155}.utterance{font-size:15px;font-weight:650;color:var(--ink);margin-bottom:6px}.badges{display:flex;gap:4px;flex-wrap:wrap;margin-top:7px}.meta-badge{font-size:11px;background:#eef2ff;color:#3730a3;border-radius:999px;padding:2px 7px}details{margin-top:5px}summary{cursor:pointer;color:#315c91;font-size:12px;font-weight:700}.turn{display:grid;grid-template-columns:38px 1fr;gap:7px;margin:6px 0;padding:6px 8px;border-left:2px solid #dbeafe;background:#f8fafc}.turn b{font-size:11px;color:#475569}.calls{margin-top:6px;min-width:210px;font-size:12px}.no-results{padding:38px;text-align:center;color:var(--muted);display:none}
@media(max-width:1000px){.filters{grid-template-columns:1fr 1fr}.filters input{grid-column:1/-1}}@media(max-width:600px){.filters{grid-template-columns:1fr}.filters input{grid-column:auto}.filter-status{display:block}}
"""


FILTER_SCRIPT = r"""
(function(){
  const rows=[...document.querySelectorAll('.failure-row')];
  const search=document.getElementById('filter-search');
  const branch=document.getElementById('filter-branch');
  const errorType=document.getElementById('filter-error-type');
  const path=document.getElementById('filter-path');
  const visible=document.getElementById('visible-count');
  const empty=document.getElementById('no-results');
  function applyFilters(){
    const q=search.value.trim().toLowerCase(); let count=0;
    rows.forEach(row=>{
      const show=(branch.value==='all'||row.dataset.truth===branch.value)
        &&(errorType.value==='all'||row.dataset.errorType===errorType.value)
        &&(path.value==='all'||row.dataset.path===path.value)
        &&(!q||(row.dataset.search||'').includes(q));
      row.hidden=!show; if(show) count++;
    });
    visible.textContent=String(count); empty.style.display=count?'none':'block';
  }
  [search,branch,errorType,path].forEach(el=>el.addEventListener(el===search?'input':'change',applyFilters));
  document.getElementById('reset-filters').addEventListener('click',()=>{
    search.value=''; branch.value='all'; errorType.value='all'; path.value='all'; applyFilters(); search.focus();
  });
  applyFilters();
})();
"""


def render_failure_dataset(metrics):
    branch_options = "".join(
        f"<option value='{label}'>{label} · {h(name)}</option>"
        for label, name in BRANCH_NAMES.items()
    )
    e = metrics["error_counts"]
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>哒哒Agent M3机制完善后失败测试集 · 272条</title><style>{FAILURE_CSS}</style></head><body>
<main id="failure-dataset" data-failure-count="{metrics['new_errors']}"><header><div class="eyebrow">FAILURE DATASET · 2026-08-18</div><h1>M3机制完善后失败测试集 · 272条</h1><p>完整收录新版M1+M3流程的所有最终失败样本。支持按真实分支、失败类型、路径状态和关键词组合筛选；默认展示全部272条。</p><nav class="topnav"><a href="{h(REPORT_FILENAME)}">返回完整测试报告</a><a href="#failure-table">跳到测试集</a></nav></header>
<section class="section"><h2>失败集构成</h2><div class="cards"><div class="card"><small>M3路由失败</small><b>{e['route_failure']}</b><small>没有最终分支</small></div><div class="card"><small>M3新增误判</small><b>{e['m3_introduced']}</b><small>M1正确、M3改错</small></div><div class="card"><small>M3未纠正</small><b>{e['m3_unresolved']}</b><small>M1与M3均错误</small></div><div class="card"><small>M1高置信直错</small><b>{e['m1_direct']}</b><small>未进入M3</small></div></div><div class="callout"><b>数据口径：</b>只包含<code>correct=false</code>的最终路由结果；样本ID去重后272条，与逐条JSONL完全一致。</div></section>
<div class="filterbar"><div class="filters"><input id="filter-search" type="search" placeholder="搜索ID、用户原文、上下文、标签……" aria-label="搜索失败样本"><select id="filter-branch" aria-label="按真实分支筛选"><option value="all">全部真实分支</option>{branch_options}</select><select id="filter-error-type" aria-label="按失败类型筛选"><option value="all">全部失败类型</option><option value="route_failure">M3路由失败</option><option value="m3_introduced">M3新增误判</option><option value="m3_unresolved">M3未纠正</option><option value="m1_direct">M1高置信直错</option></select><select id="filter-path" aria-label="按路径筛选"><option value="all">全部路径</option><option value="m3_failure">M3调用失败</option><option value="m3_success">M3成功返回但错误</option><option value="m1_direct">M1高置信直进</option></select><button id="reset-filters" type="button">重置筛选</button></div><div class="filter-status"><span>当前显示 <b id="visible-count">272</b> / 272 条</span><span>点击“查看历史上下文”或“模型调用”展开详情</span></div></div>
<section class="section" id="failure-table"><div class="scroll"><table class="failure-table"><thead><tr><th>#</th><th>失败类型</th><th>真值分支</th><th>样本与切片</th><th>用户原文与历史</th><th>M1初判</th><th>最终结果</th><th>调用记录</th></tr></thead><tbody>{render_failure_rows(metrics['failures'])}</tbody></table><div class="no-results" id="no-results">没有匹配当前筛选条件的失败样本。</div></div></section>
<footer>哒哒Agent M3机制完善后失败测试集 · 272条 · 2026-08-18</footer></main><script>{FILTER_SCRIPT}</script></body></html>"""


def generate(old_path, new_path, output_dir):
    old_rows = load_rows(old_path)
    new_rows = load_rows(new_path)
    metrics = compute_metrics(old_rows, new_rows)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / REPORT_FILENAME
    failure_path = output_dir / FAILURE_FILENAME
    report_path.write_text(render_report(metrics), encoding="utf-8")
    failure_path.write_text(render_failure_dataset(metrics), encoding="utf-8")
    return report_path, failure_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report, failures = generate(args.old, args.new, args.output_dir)
    print(json.dumps({
        "report": str(report),
        "failures": str(failures),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
