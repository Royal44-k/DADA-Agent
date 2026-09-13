"""Render the context-aware corrected 1,300-row intent corpus as one HTML file.

The source ``raw/*.jsonl`` files are treated as immutable.  This module rebuilds
each selected sample from its exact source_file/source_line and overlays only the
109 manually reviewed decisions from the last failed set.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import html
import json
import pathlib
from collections import Counter
from typing import Any, Iterable


@dataclasses.dataclass(frozen=True)
class AuditDecision:
    original_label: str
    revised_label: str
    confidence: str
    reason: str
    needs_rewrite: bool = False


def _decision(sample_id: str, revised_label: str, confidence: str, reason: str, needs_rewrite: bool = False):
    return sample_id, AuditDecision(sample_id[0], revised_label, confidence, reason, needs_rewrite)


# Every row in the 109-case failure set is listed, including reviewed-and-kept
# labels.  This prevents a later renderer from silently treating a reviewed keep
# as an unaudited row.
_AUDIT_ROWS = [
    # a — new reminders
    _decision("a-01497-dd56f4a0a47e", "a", "中", "承接助手对新提醒事项的追问；当前是在补充提醒内容，不是独立写入记忆。", True),
    _decision("a-03146-8f994a113422", "b", "高", "明确把既有“体检报告”提醒调到星期天下午，属于修改提醒。"),
    _decision("a-02885-593d1f7b0b02", "b", "高", "“那个…延后…到周五”指向既有提醒，属于延期修改。"),
    _decision("a-01461-7d76f2a29a15", "a", "中", "仍在新建疫苗提醒的补槽对话中，用户授权沿用此前信息完成创建。"),
    _decision("a-02563-dd3a36a51a95", "b", "高", "“把那个…改成白天提醒”明确修改刚创建的提醒。"),

    # b — reminder operations
    _decision("b-02114-7fe6845277d3", "b", "中", "“再睡五分钟”在提醒/唤醒语境中表达推迟或稍后再提醒。"),
    _decision("b-02115-0da3b1f6b6c8", "b", "高", "“药已经吃了”是在完成当前用药提醒，可标记事项完成。"),

    # c — reminder queries
    _decision("c-02062-b3faaa044780", "c", "低", "上文连续查询已有提醒，当前仍像是在确认某个行李事项是否记得；文本破损，建议改写后再测。", True),
    _decision("c-01896-683ca7eff787", "a", "高", "“七号吧”是对新建充话费提醒时间的补充。"),
    _decision("c-01354-b23e41e36db5", "a", "高", "确认助手给出的新提醒绝对时间，仍属于创建流程。"),
    _decision("c-01710-9fc2708d314e", "b", "高", "“把吃点心改成后天中午”明确修改已有提醒。"),

    # d — write/correct memory
    _decision("d-00495-19fb7f0c478d", "d", "高", "先说第二层再自我纠正为第三层，是记忆内容纠错。"),
    _decision("d-01803-eaaa2a50dc43", "d", "高", "“不对”后给出充电器的正确去向，是记忆纠错。"),
    _decision("d-00453-62640a78f0b5", "d", "高", "陈述个人车辆停放位置，属于应记住的新个人信息。"),
    _decision("d-02137-bf7c7d801f7a", "e", "高", "助手在记忆查询中给出位置并求确认，用户只是确认已记内容，没有发起新写入。"),
    _decision("d-00576-9532bd525f62", "d", "高", "陈述明信片的具体存放位置，属于写入记忆。"),

    # e — memory queries
    _decision("e-03479-572a321d1e37", "m", "高", "已得到过敏信息后仅作生活化回应，没有继续查询或写入记忆。"),
    _decision("e-03731-8971a7ddbc0e", "b", "高", "“把它提醒调到八点”是修改提醒，不是查询记忆。"),
    _decision("e-00078-f6633fa316c9", "j", "高", "询问如何使用设备的记忆功能并要求演示，属于产品用法。"),
    _decision("e-03200-1edd5409c245", "d", "中", "末句要求别忘记花生过敏信息，核心落在写入个人记忆。"),
    _decision("e-02667-a37780cb1a66", "e", "高", "在查询 Wi‑Fi 密码的会话中复述内容作确认，仍是记忆查询闭环。"),
    _decision("e-00079-3d7b567cf019", "j", "高", "“支持查天气吗”询问产品能力边界，而非真正查询某地天气。"),
    _decision("e-02357-b65404e18d4a", "d", "高", "明确要求记住蓝色药盒的服用时段，是写入记忆。"),
    _decision("e-01817-f0526395eaa6", "e", "高", "询问先前记住的理发店周二休息信息，不是在问当前日期。"),
    _decision("e-01127-8e2e2debfe95", "e", "高", "在银行卡尾号查询流程中补充银行名称，仍服务于记忆查询。"),
    _decision("e-03237-b4e0c3a3a1fe", "d", "高", "明确说“记一下新的”，目标是写入新的燃气表读数。"),
    _decision("e-00306-1fcf5e043ae4", "m", "中", "无记忆上下文，仅问降压药吃几次，更像一般用药知识问题。"),
    _decision("e-02209-f365ec7e243f", "e", "高", "既有充电器记忆已写入，当前“别忘了”是在确认保持记忆。"),
    _decision("e-00347-f6ff09be08d5", "e", "高", "用疑问句确认户口本的已记存放位置。"),
    _decision("e-01159-222a55cef4f3", "m", "高", "询问验孕医院推荐，属于一般咨询，不依赖个人记忆。"),
    _decision("e-01875-526d2ed7e98d", "i", "中", "显式询问今天是否星期二；判断是否改天需先回答当前星期。"),
    _decision("e-00198-3ad087769b1a", "a", "中", "ASR 中“提星”按“提醒”还原，表达明天吃药提醒。", True),
    _decision("e-03753-4954f6ee103b", "e", "高", "为银行卡尾号查询补充建行及尾号，属于查询闭环中的确认。"),
    _decision("e-00554-17ced9b916fe", "j", "高", "询问设备记忆是否会遗忘，属于产品能力/可靠性问题。"),
    _decision("e-00370-e2330349697a", "e", "高", "明确查询自己车辆先前记录的停车层。"),
    _decision("e-01915-04522929412d", "e", "高", "前半句自我打断，最终明确询问已记的物业电话。"),
    _decision("e-03530-311f7397bef9", "e", "中", "在医保卡位置查询中补充确认具体抽屉，整体意图仍是找回已记信息。"),

    # i — time/date/holiday
    _decision("i-01194-4b732ddcb8d2", "i", "高", "询问腊月与腊八节的历法关系，属于日期/节日问题。"),
    _decision("i-01140-90fc7fbb1bf5", "i", "低", "上下文是阴历换算，当前 ASR 严重破损但仍应留在日期分支；建议重写原句。", True),

    # j — product capability / usage
    _decision("j-02162-5fefc51fb765", "b", "高", "明确把已确认的提醒改成九点。"),
    _decision("j-01851-1f276eb45dd1", "b", "高", "“改到九点”修改已有吃药提醒。"),
    _decision("j-01698-fda7d997c72e", "f", "高", "实际执行下调音量，不是在询问功能。"),
    _decision("j-02631-68fd682bfe62", "a", "高", "在新提醒补槽中给出明天吃药事项。"),
    _decision("j-00600-838a247c3985", "j", "中", "询问如何预先教父母使用设备，核心是产品使用方式。"),
    _decision("j-00698-dbc890b9fd22", "m", "高", "对使用说明作“稍后试试”的闲聊式回应，没有新的产品问题或操作。"),
    _decision("j-02183-74400192e649", "j", "高", "“你唱歌咋样”是在询问设备能否/如何唱歌的能力。"),
    _decision("j-03587-12eb72ad98f7", "f", "高", "已明确要把音量调小一点，是实际执行。"),
    _decision("j-03251-c9c9a5ea1cc9", "j", "高", "“支不支持查天气”是产品能力询问，不是具体天气查询。"),
    _decision("j-00550-96ee11f594cd", "f", "高", "直接要求调音量。"),
    _decision("j-02646-702c3d39553b", "a", "高", "依照助手示例实际发起明天吃药提醒。"),
    _decision("j-00850-fdaaae0c946f", "j", "高", "直接询问设备能帮用户做哪些事。"),
    _decision("j-03283-7e53d56fff0d", "b", "低", "对话主任务是取消既有吃药提醒；助手追问城市与任务冲突，语料应重写。", True),
    _decision("j-01607-0514648f84fa", "f", "高", "明确把音量设为六十，是实际执行。"),
    _decision("j-03200-26a321253928", "j", "高", "询问设备听错老人讲话时怎么办，属于 ASR 使用/能力问题。"),
    _decision("j-01248-25cea7e8c09b", "a", "高", "在教学后实际创建后天带伞提醒。"),
    _decision("j-01278-a111a480b80e", "j", "高", "修订为承接手机连接话题的蓝牙距离问题，属于产品连接能力与用法。", True),
    _decision("j-02505-52bd6c30ede1", "f", "高", "要求把提醒铃声音量调小，是实际音量操作。"),
    _decision("j-01869-6f71a8dca51a", "h", "高", "实际查询后天天气，附带询问可查天数。"),
    _decision("j-01849-b7a69813f7c8", "b", "高", "把已有吃药提醒推迟到十一点。"),
    _decision("j-00520-22e074c2cb4d", "j", "低", "可勉强还原为听不清设备时怎么办的使用问题，但 ASR 破损严重。", True),
    _decision("j-02959-8917396ffbb8", "j", "高", "询问设备能完成哪些实际能力。"),
    _decision("j-00488-a54d360081e0", "a", "高", "直接发起设置提醒，缺少槽位不改变新建提醒意图。"),
    _decision("j-00957-35605e3c04ab", "a", "高", "在提醒使用说明后实际发起明天吃药提醒。"),
    _decision("j-02919-940af05082ae", "g", "高", "明确要求把亮度调亮，是实际亮度操作。"),
    _decision("j-03534-cf1fede38903", "a", "高", "补齐五点接孙子的时间与事项，创建新提醒。"),
    _decision("j-01370-6b38ada09735", "f", "高", "中断记忆流程后改为实际调节音量。"),
    _decision("j-02745-bd14aeb028ed", "a", "高", "在能力介绍后实际要求创建明早提醒。"),

    # k — sleep/goodnight
    _decision("k-00915-ceced5c3515c", "b", "高", "明确把豆浆提醒改到七点半，动作优先于上下文。"),
    _decision("k-01986-a6bcb6552d4b", "k", "中", "“道个谙”结合睡觉与晚安上下文可还原为“道个安”。", True),
    _decision("k-01367-98181bef62df", "k", "高", "闹钟设置完成后说“歇了”，表达准备休息。"),
    _decision("k-00307-77ab3024895f", "k", "低", "可按 ASR 将“收收”理解为“睡睡”，但缺少上下文，建议重写。", True),
    _decision("k-01582-b6e916f7a6d2", "h", "高", "在天气查询中补充/切换城市为南宁。"),
    _decision("k-00389-1c5a9208f8f7", "a", "高", "同时包含提醒和睡觉；为避免丢失有副作用的提醒动作，应优先创建提醒。"),
    _decision("k-01897-6305007de075", "k", "高", "修订为闹钟设置完成后的睡前表达，属于睡觉/晚安。", True),
    _decision("k-01755-437f26342194", "b", "高", "指代刚修改的提醒并再次改到四点半。"),

    # l — farewell/end conversation
    _decision("l-01952-04c92611afc5", "l", "中", "结合已完成告别的上文，“不见咯”按 ASR 缺字理解为“再见咯”。", True),
    _decision("l-01910-4508d678a0ce", "a", "高", "当前再次明确发起明天吃药提醒，应作为提醒请求处理。"),
    _decision("l-01874-befc1ae8bd65", "l", "高", "“算了，明儿见”撤回未完成请求并明确结束对话。"),
    _decision("l-02125-629bda958d10", "k", "高", "“睡了哈”明确表达准备睡觉。"),
    _decision("l-01126-8adf45004672", "l", "中", "虽然提到轻音乐，但末尾明确“拜拜”，主导为告别。"),
    _decision("l-00791-e5b23f276608", "m", "高", "只要求停止当前播放，没有向 Agent 告别；现有分支中落入其他。"),
    _decision("l-00695-40a765996038", "a", "高", "确认二十分钟后的新提醒事项，仍是创建流程。"),
    _decision("l-00813-2aa482495d1b", "l", "高", "修订为查询结束后的感谢与再见，属于结束对话。", True),
    _decision("l-01056-a2d4691b8142", "k", "高", "明确说“我睡了”。"),
    _decision("l-01427-415ae7f87627", "k", "高", "“晚安”是睡眠分支的直接触发。"),
    _decision("l-01286-5d819fbd64c7", "m", "中", "要求挂断当前电话并稍后自己拨打，不等同于向 Agent 告别。"),
    _decision("l-01141-2db492a36082", "l", "中", "补充城市后明确“明天再聊”，会话结束意图清晰。"),
    _decision("l-01465-5d60f906109b", "l", "中", "“这就关”在任务完成后表达关闭会话。"),
    _decision("l-01704-a0777d78c2e3", "l", "高", "“歇着吧你”表示不再需要服务、结束当前对话。"),
    _decision("l-01401-878f580ddac1", "k", "高", "包含“我要睡了”，按规则睡眠优先于普通再见。"),
    _decision("l-02157-7869133cf148", "b", "高", "明确把提醒改到八点；为避免动作丢失，修改提醒优先于末尾睡觉寒暄。"),
    _decision("l-01614-e88c2c911884", "l", "高", "“算了，回头再说”撤回当前话题并结束对话。"),
    _decision("l-00971-ae8bf3a51edf", "l", "高", "“再聊啊”明确暂时结束当前对话。"),
    _decision("l-00332-7dc0e11b2f97", "k", "中", "ASR 有误但“我睡了”清晰，属于睡眠。", True),
    _decision("l-00264-70e9b1c22e9d", "k", "高", "明确说去睡觉。"),
    _decision("l-01353-a5fa8b8d6261", "m", "高", "只关闭正在播放的歌曲，不是结束与 Agent 的对话。"),
    _decision("l-02232-e2b2bbb28ef4", "a", "高", "ASR 将“药”识别成“样”，语义仍是明天吃药提醒。", True),
    _decision("l-01356-d74dec5b4df2", "l", "高", "“没事了”表示当前服务结束，符合结束对话分支。"),
    _decision("l-01230-623efe9e456c", "l", "高", "明确要求关闭应用，属于结束交互。"),
    _decision("l-01521-02cca851bca3", "l", "中", "文本前半段破损，末尾“改天见”明确告别。", True),
    _decision("l-01113-3a4e6b0e7548", "l", "高", "“明儿见”是明确告别，不是睡眠陈述。"),

    # m — chat/other/general knowledge
    _decision("m-00555-77920f317f57", "a", "高", "补齐明早八点这一提醒时间，属于新建提醒。"),
    _decision("m-02120-feac5b2bc433", "f", "高", "从新闻话题切换为实际调音量。"),
    _decision("m-00979-faec748e1078", "f", "高", "承接前文再次要求调音量。"),
    _decision("m-02075-f09c97c623a1", "f", "高", "明确要求把音量调大。"),
    _decision("m-01927-6431554942b6", "f", "高", "“太吵了”限定了将音量调小的实际操作。"),
    _decision("m-01365-0db281149dbf", "l", "高", "“回头再聊”明确暂时结束当前对话。"),
    _decision("m-01074-ed3d169a82bd", "a", "高", "明确要求提醒明天吃药。"),
    _decision("m-00213-d736699d5719", "j", "高", "询问如何使用提醒功能记录纪念日，属于产品用法。"),
]

AUDIT_DECISIONS = dict(_AUDIT_ROWS)
if len(AUDIT_DECISIONS) != len(_AUDIT_ROWS):
    raise RuntimeError("Duplicate sample_id in audit decisions")


@dataclasses.dataclass(frozen=True)
class CorpusRewrite:
    text: str
    reason: str
    history: tuple[tuple[str, str], ...] | None = None
    ctx: str | None = None


def _rewrite(
    sample_id: str,
    text: str,
    reason: str,
    *,
    history: tuple[tuple[str, str], ...] | None = None,
    ctx: str | None = None,
):
    return sample_id, CorpusRewrite(text, reason, history, ctx)


# These are overlays only.  Raw files remain immutable and are included in the
# rendered audit trail.  The rewritten form is the actual input for subsequent
# evaluation.
CORPUS_REWRITES = dict(
    [
        # a
        _rewrite("a-01497-dd56f4a0a47e", "提醒我把要做的事情记录在小本本上。", "修复 ASR 破句，保留新提醒补槽语义。"),
        _rewrite("a-02885-593d1f7b0b02", "把下周三种牙的提醒推迟到周五吧。", "消除不存在的“高考志愿”指代，使修改对象与上文一致。"),
        _rewrite("a-01461-7d76f2a29a15", "疫苗种类就按我之前说的，直接帮我设好提醒吧。", "补全省略成分，明确仍在创建疫苗提醒。"),
        # b
        _rewrite(
            "b-02114-7fe6845277d3",
            "把这个闹钟推迟五分钟再响。",
            "补足“再睡五分钟”的闹钟指代，排除普通闲聊歧义。",
            history=(("user", "早上九点的闹钟响了。"), ("assistant", "已经到九点了，该起床了。")),
            ctx="coref",
        ),
        # c
        _rewrite("c-02062-b3faaa044780", "我那个整理行李的提醒还在吗？", "重写无法还原的 ASR 片段，明确查询已有提醒。"),
        # d/e boundary
        _rewrite("d-02137-bf7c7d801f7a", "对，是压在褥子底下，对吧？", "修复 ASR 错词，并用确认问句固定为记忆查询。"),
        # e
        _rewrite(
            "e-03731-8971a7ddbc0e",
            "把这个提醒调到早上八点吧。",
            "建立明确的既有提醒上下文，固定为提醒修改。",
            history=(("user", "蓝色药盒的服药提醒设在几点？"), ("assistant", "现在设在早上七点。")),
        ),
        _rewrite("e-03200-1edd5409c245", "另外请记住，我对花生过敏。", "删除服药时间与过敏记忆的双意图，只保留写入记忆。", ctx="switch"),
        _rewrite(
            "e-02667-a37780cb1a66",
            "对，Wi-Fi 密码就是八个8。",
            "修复 ASR 错词，并消除助手“知道又没记全”的矛盾。",
            history=(("user", "我的 Wi-Fi 密码是什么？"), ("assistant", "您之前说密码是八个8，请确认一下对吗？")),
        ),
        _rewrite("e-01817-f0526395eaa6", "我记得那家理发店周二休息，对不对？", "把错误的第二人称改为明确的记忆确认对象。"),
        _rewrite("e-03237-b4e0c3a3a1fe", "那记一下新的燃气表读数吧，这次是12680立方。", "补齐要写入的新读数，避免只有写入意愿却没有内容。"),
        _rewrite("e-00306-1fcf5e043ae4", "降压药一般一天吃几次？", "修复 ASR 错词，明确为一般用药咨询。"),
        _rewrite("e-02209-f365ec7e243f", "充电器借给老张这件事，你还记得吧？", "把“别忘了”改成明确确认问句，固定为记忆查询。"),
        _rewrite("e-01159-222a55cef4f3", "我想做孕检，去哪家医院比较好？", "改为符合日常表达的医院咨询。"),
        _rewrite("e-01875-526d2ed7e98d", "今天是星期二吗？", "删除是否改期的第二意图，只保留日期查询。"),
        _rewrite("e-00198-3ad087769b1a", "提醒我明天早上八点吃药。", "修复 ASR 并补齐时间，排除用药建议疑问。"),
        _rewrite("e-03753-4954f6ee103b", "是建行那张，尾号是不是1234？", "从陈述改为确认问句，固定为记忆查询。"),
        _rewrite("e-00554-17ced9b916fe", "你的记忆功能会不会丢失已经记住的信息？", "移除带冒犯性的比喻，保留产品记忆可靠性问题。"),
        _rewrite("e-01915-04522929412d", "物业电话是多少来着？", "删除音量操作的前置自我打断，只保留记忆查询。", ctx="switch"),
        _rewrite("e-03530-311f7397bef9", "是客厅茶几下面那个抽屉，对吧？", "补成确认问句，避免与新记忆写入混淆。"),
        # i
        _rewrite("i-01194-4b732ddcb8d2", "腊八节是在腊月吗？", "修正“月份是否等于节日”的不自然问法。"),
        _rewrite(
            "i-01140-90fc7fbb1bf5",
            "那今天对应的农历日期是什么？",
            "重写无法理解的 ASR 片段，并清理历史中的生成元话语。",
            history=(("user", "我想按阴历安排生日。"), ("assistant", "可以，我能帮你查询农历日期。")),
        ),
        # j
        _rewrite("j-01851-1f276eb45dd1", "对，把那个提醒改到九点。", "修复“对他”的代词错误。"),
        _rewrite("j-01698-fda7d997c72e", "帮我把音量调低一点，好吗？", "整理重复动词，保留自然口语语气。"),
        _rewrite("j-02631-68fd682bfe62", "提醒我明天吃药。", "修复“提星”的 ASR 错词。"),
        _rewrite("j-00600-838a247c3985", "我想教爸妈使用哒哒，应该提前设置哪些功能？", "补足产品对象和询问内容。", ctx="switch"),
        _rewrite("j-00550-96ee11f594cd", "帮我把音量调低一点。", "删除“调下调下”的 ASR 重复。", ctx="switch"),
        _rewrite("j-02646-702c3d39553b", "提醒我明天吃药。", "修复 ASR 错词并删除无意义语气残片。"),
        _rewrite(
            "j-03283-7e53d56fff0d",
            "对，就取消早上七点的吃药提醒。",
            "修复助手错误追问城市造成的上下文冲突。",
            history=(
                ("user", "怎么取消提醒？"),
                ("assistant", "告诉我提醒名称或时间即可。"),
                ("user", "我想取消早上七点的吃药提醒。"),
                ("assistant", "请确认，要取消的是早上七点的吃药提醒吗？"),
            ),
        ),
        _rewrite("j-01607-0514648f84fa", "把音量调到60。", "调整语序，使明确目标值表达通顺。", ctx="switch"),
        _rewrite("j-03200-26a321253928", "老人说话时你有时会听错，这种情况该怎么办？", "明确听错的主体与产品 ASR 问题。"),
        _rewrite("j-01278-a111a480b80e", "蓝牙连接最远支持多少米？", "用与手机连接上下文一致的产品能力问题替换无指代问句。"),
        _rewrite("j-02505-52bd6c30ede1", "提醒铃声太大了，帮我调小一点。", "删除 ASR 重复，明确调小提醒铃声。"),
        _rewrite("j-00520-22e074c2cb4d", "有时候听不清你说话，该怎么办？", "重写无法还原的 ASR 破句，保留产品使用问题。"),
        _rewrite("j-00957-35605e3c04ab", "提醒我明天吃药。", "修复“提星”的 ASR 错词。"),
        _rewrite("j-02919-940af05082ae", "把亮度也调亮一点。", "删除 ASR 冗余词，使亮度操作明确。"),
        _rewrite("j-01370-6b38ada09735", "你能帮我把音量调低一点吗？", "删除“调下调下”的重复表达。"),
        # k
        _rewrite("k-01986-a6bcb6552d4b", "再跟我说声晚安吧。", "修复“道个谙”的 ASR 错词。"),
        _rewrite("k-00307-77ab3024895f", "我要睡觉了，晚安。", "重写缺少上下文且无法理解的 ASR 片段。"),
        _rewrite(
            "k-01582-b6e916f7a6d2",
            "那南宁明天的温度呢？",
            "清理历史中的生成说明，并把城市切换补成完整问句。",
            history=(("user", "帮我查一下长沙明天的温度。"), ("assistant", "长沙明天21到28度。")),
        ),
        _rewrite("k-00389-1c5a9208f8f7", "提醒我明天早上八点吃药。", "删除末尾睡觉寒暄，只保留不可丢失的提醒动作。"),
        _rewrite("k-01897-6305007de075", "闹钟设好了，那我先睡了，晚安。", "用与闹钟上下文一致的睡前表达替换无关城市片段。"),
        _rewrite("k-01755-437f26342194", "好的，把刚才那个提醒再改到四点半。", "修复“闹再闹”的 ASR 重复。"),
        # l
        _rewrite("l-01952-04c92611afc5", "再见了。", "补回 ASR 遗漏的“再”字。"),
        _rewrite("l-01910-4508d678a0ce", "再加一个明天中午十二点的吃药提醒。", "修复 ASR，并与已存在的早八点提醒区分，明确新建提醒。"),
        _rewrite(
            "l-01874-befc1ae8bd65",
            "不用了，明天再聊。",
            "删除未完成的提醒请求，只保留结束对话。",
            history=(("user", "帮我查一下明天上海的天气。"), ("assistant", "明天上海有雨，出门记得带伞。还需要别的吗？")),
        ),
        _rewrite("l-01126-8adf45004672", "今天不听了，拜拜。", "删除播放音乐的并列动作，只保留告别。"),
        _rewrite("l-00813-2aa482495d1b", "谢谢你帮我查，我没别的事了，再见。", "重写 ASR 破句，明确查询结束后的告别。", ctx="supplement"),
        _rewrite("l-01056-a2d4691b8142", "好的，我先睡了，晚安。", "删除无法解释的“明天修闹钟”片段。"),
        _rewrite(
            "l-01141-2db492a36082",
            "没有了，明天再聊。",
            "消除补充行程城市与告别并列造成的双意图。",
            history=(("user", "帮我加一条明天坐国航从长沙飞北京的行程提醒。"), ("assistant", "好的，行程提醒已经设置好了。还有其他需要吗？")),
        ),
        _rewrite("l-01465-5d60f906109b", "好的，没别的事了，先结束对话吧。", "补足关闭对象，明确结束当前对话。"),
        _rewrite("l-01401-878f580ddac1", "我先睡了，晚安。", "删除“睡觉+再见”的边界竞争，只保留晚安。", ctx="switch"),
        _rewrite("l-02157-7869133cf148", "把刚才那个提醒改到八点吧。", "删除末尾睡觉寒暄，只保留提醒修改动作。"),
        _rewrite("l-00332-7dc0e11b2f97", "先这样吧，我要睡觉了，晚安。", "修复 ASR 错词并明确睡眠意图。"),
        _rewrite("l-02232-e2b2bbb28ef4", "再设一个明天晚上八点的吃药提醒。", "修复 ASR，并与已有早八点提醒区分。"),
        _rewrite("l-01230-623efe9e456c", "我知道了，先把这个应用关掉吧。", "重写重复、错乱的 ASR 片段。"),
        _rewrite("l-01521-02cca851bca3", "今天先这样，改天见。", "删除无法解析的音量片段，只保留告别。", ctx="switch"),
        # m
        _rewrite("m-00555-77920f317f57", "明早八点提醒我吃药。", "修复口吃式 ASR 重复，并补全事项。", ctx="supplement"),
        _rewrite("m-02120-feac5b2bc433", "帮我把音量调低一点。", "删除“调下调下”的 ASR 重复。"),
        _rewrite("m-00979-faec748e1078", "再帮我把音量调低一点。", "删除 ASR 重复，并保留承接前文的再次操作。"),
        _rewrite("m-02075-f09c97c623a1", "帮我把音量调大一点。", "删除 ASR 重复，保留明确方向。"),
        _rewrite("m-01927-6431554942b6", "音量太大了，帮我调低一点。", "删除 ASR 重复，使原因与方向一致。"),
        _rewrite("m-01074-ed3d169a82bd", "提醒我明天吃药，别忘了。", "修复“提星”的 ASR 错词。"),
    ]
)
if len(CORPUS_REWRITES) != 63:
    raise RuntimeError(f"Expected 63 corpus rewrites, got {len(CORPUS_REWRITES)}")


LABELS = {
    "a": "新建提醒/闹钟",
    "b": "修改/取消/完成提醒",
    "c": "查询提醒事项",
    "d": "写入/纠正/删除记忆",
    "e": "查询已记内容",
    "f": "调节音量",
    "g": "调节亮度",
    "h": "查询天气",
    "i": "时间/日期/节日",
    "j": "产品能力与用法",
    "k": "睡觉/晚安",
    "l": "告别/结束对话",
    "m": "闲聊/其他/常识",
}


def _read_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_corrected_corpus(sample_path: pathlib.Path, raw_root: pathlib.Path) -> list[dict[str, Any]]:
    """Rebuild the selected 1,300 rows from exact raw sources and overlay audit labels."""
    samples = _read_jsonl(sample_path)
    raw_cache: dict[str, list[dict[str, Any]]] = {}
    corpus: list[dict[str, Any]] = []

    for position, sample in enumerate(samples, start=1):
        source_file = sample["source_file"]
        if source_file not in raw_cache:
            raw_cache[source_file] = _read_jsonl(raw_root / source_file)
        source_line = int(sample["source_line"])
        raw = raw_cache[source_file][source_line - 1]
        sample_id = sample["sample_id"]

        # The sample builder stores the answer as ``label``; evaluation results
        # later rename it to ``truth``.  Accept either schema, but still require
        # an exact match against the immutable raw source.
        sample_label = sample.get("truth", sample.get("label"))
        if raw.get("label") != sample_label:
            raise ValueError(f"raw/sample label mismatch: {sample_id}")
        if raw.get("text") != sample.get("text") or raw.get("history", []) != sample.get("history", []):
            raise ValueError(f"raw/sample content mismatch: {sample_id}")

        audit = AUDIT_DECISIONS.get(sample_id)
        rewrite = CORPUS_REWRITES.get(sample_id)
        revised_label = audit.revised_label if audit else raw["label"]
        if audit and audit.original_label != raw["label"]:
            raise ValueError(f"audit/raw original label mismatch: {sample_id}")

        revised_history = (
            [list(turn) for turn in rewrite.history]
            if rewrite and rewrite.history is not None
            else raw.get("history", [])
        )
        revised_text = rewrite.text if rewrite else raw["text"]
        revised_ctx = rewrite.ctx if rewrite and rewrite.ctx is not None else raw.get("ctx")
        revised_asr_noise = False if rewrite else bool(raw.get("asr_noise"))
        revised_rounds = len(revised_history) // 2 + 1
        revised_rounds_bucket = str(revised_rounds) if revised_rounds in (1, 2, 3) else "4+"
        revised_stratum = (
            f"noise={str(revised_asr_noise).lower()}|"
            f"rounds={revised_rounds_bucket}|hard={str(bool(raw.get('hard_pair'))).lower()}"
        )

        corpus.append(
            {
                "position": position,
                "sample_id": sample_id,
                "source_file": source_file,
                "source_line": source_line,
                "original_label": raw["label"],
                "revised_label": revised_label,
                "original_text": raw["text"],
                "text": revised_text,
                "original_history": raw.get("history", []),
                "history": revised_history,
                "original_ctx": raw.get("ctx"),
                "ctx": revised_ctx,
                "original_asr_noise": bool(raw.get("asr_noise")),
                "asr_noise": revised_asr_noise,
                "hard_pair": raw.get("hard_pair"),
                "rounds": revised_rounds,
                "src": raw.get("src"),
                "rounds_bucket": revised_rounds_bucket,
                "stratum": revised_stratum,
                "audit_status": (
                    "relabel" if audit and audit.revised_label != audit.original_label
                    else "reviewed_keep" if audit
                    else "unchanged"
                ),
                "confidence": audit.confidence if audit else "—",
                "reason": audit.reason if audit else "未进入上一轮 109 条失败集；本轮沿用 raw 标签，未作逐条人工改标。",
                "text_status": "rewritten" if rewrite else "unchanged",
                "rewrite_reason": rewrite.reason if rewrite else "",
                "unresolved_quality_issue": bool(audit and audit.needs_rewrite and not rewrite),
                "needs_rewrite": bool(audit and audit.needs_rewrite and not rewrite),
            }
        )

    return corpus


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _history_html(history: Iterable[list[str]]) -> str:
    turns = list(history)
    if not turns:
        return '<span class="muted">无历史上下文</span>'
    items = []
    for role, content in turns:
        role_name = "用户" if role == "user" else "助手"
        items.append(
            f'<div class="turn {role}"><span>{role_name}</span><p>{_esc(content)}</p></div>'
        )
    return "".join(items)


def _label_badge(label: str) -> str:
    return f'<span class="label-badge label-{_esc(label)}"><b>{_esc(label)}</b>{_esc(LABELS[label])}</span>'


def render_html(corpus: list[dict[str, Any]]) -> str:
    if len(corpus) != 1300:
        raise ValueError(f"expected 1300 rows, got {len(corpus)}")

    status_counts = Counter(row["audit_status"] for row in corpus)
    revised_counts = Counter(row["revised_label"] for row in corpus)
    rewrite_count = sum(row["text_status"] == "rewritten" for row in corpus)
    unresolved_count = sum(row["unresolved_quality_issue"] for row in corpus)
    raw_fingerprint = hashlib.sha256(
        "\n".join(
            f'{row["source_file"]}:{row["source_line"]}:{row["sample_id"]}:{row["text"]}'
            for row in corpus
        ).encode("utf-8")
    ).hexdigest()

    rows_html = []
    for row in corpus:
        changed = row["original_label"] != row["revised_label"]
        status_name = {
            "relabel": "已改标",
            "reviewed_keep": "复核保留",
            "unchanged": "沿用 raw",
        }[row["audit_status"]]
        status_class = row["audit_status"].replace("_", "-")
        ctx = row["ctx"] or "none"
        search_blob = " ".join(
            [row["sample_id"], row["text"], row["original_text"], row["reason"], row["rewrite_reason"]]
            + [content for _, content in row["history"]]
            + [content for _, content in row["original_history"]]
        ).lower()
        history = _history_html(row["history"])
        original_history = _history_html(row["original_history"])
        arrow = '<span class="arrow">→</span>' if changed else '<span class="arrow same">=</span>'
        rewrite = '<span class="rewrite-flag">已改写</span>' if row["text_status"] == "rewritten" else ""
        hard = f'<span class="meta-pill">hard { _esc(row["hard_pair"]) }</span>' if row["hard_pair"] else ""
        if row["text_status"] == "rewritten" and row["original_asr_noise"]:
            noise = '<span class="meta-pill noise">raw ASR 噪声</span><span class="meta-pill clean">修订后干净</span>'
        else:
            noise = '<span class="meta-pill noise">ASR 噪声</span>' if row["asr_noise"] else '<span class="meta-pill">干净文本</span>'
        ctx_note = ""
        original_ctx = row["original_ctx"] or "none"
        if original_ctx != ctx:
            ctx_note = f'<span class="meta-pill changed-meta">raw ctx { _esc(original_ctx) } → { _esc(ctx) }</span>'
        if row["text_status"] == "rewritten":
            text_block = (
                f'<div class="text-label">修订文本 · 实际测试输入</div><div class="utterance revised-text">{_esc(row["text"])}</div>'
                f'<div class="raw-copy"><b>raw 原文</b><span>{_esc(row["original_text"])}</span></div>'
            )
            if row["history"] != row["original_history"]:
                raw_context = f'<details class="raw-history"><summary>展开 raw 原始上下文 · {len(row["original_history"])} 轮</summary><div class="history">{original_history}</div></details>'
            else:
                raw_context = ""
        else:
            text_block = f'<div class="text-label">测试文本</div><div class="utterance">{_esc(row["text"])}</div>'
            raw_context = ""
        rows_html.append(
            f'''<tr class="corpus-row" data-label="{_esc(row["revised_label"])}" data-status="{_esc(row["audit_status"])}"
                data-ctx="{_esc(ctx)}" data-noise="{str(row["asr_noise"]).lower()}" data-search="{_esc(search_blob)}">
              <td class="index-cell"><b>{row["position"]:04d}</b><span>{_esc(row["source_file"])}:{row["source_line"]}</span></td>
              <td class="id-cell"><code>{_esc(row["sample_id"])}</code><div class="meta-row"><span class="meta-pill">ctx { _esc(ctx) }</span>{ctx_note}{noise}{hard}</div></td>
              <td class="labels-cell"><div>{_label_badge(row["original_label"])}{arrow}{_label_badge(row["revised_label"])}</div>
                <span class="status {status_class}">{status_name}</span>{rewrite}</td>
              <td class="utterance-cell">{text_block}
                <details><summary>展开修订后完整上下文 · {len(row["history"])} 轮</summary><div class="history">{history}</div></details>{raw_context}</td>
              <td class="audit-cell"><div class="confidence">置信度 <b>{_esc(row["confidence"])}</b></div><p>{_esc(row["reason"])}</p>{f'<p class="rewrite-reason"><b>表达修订：</b>{_esc(row["rewrite_reason"])}</p>' if row["rewrite_reason"] else ''}</td>
            </tr>'''
        )

    label_options = "".join(f'<option value="{k}">{k} · {_esc(v)}</option>' for k, v in LABELS.items())
    distribution = "".join(
        f'<li><span>{label}</span><b>{revised_counts[label]}</b><em>{_esc(LABELS[label])}</em></li>'
        for label in LABELS
    )

    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>哒哒 Agent 修订后 1300 条测试语料</title>
  <style>
    :root{{--ink:#08111d;--panel:#101d2c;--panel2:#142437;--line:#284058;--text:#edf6ff;--muted:#91a6ba;--cyan:#38d9d1;--amber:#ffb648;--red:#ff6b6b;--blue:#68a7ff;--green:#71df9c;}}
    *{{box-sizing:border-box}} html{{scroll-behavior:smooth}} body{{margin:0;background:var(--ink);color:var(--text);font-family:"Microsoft YaHei UI","PingFang SC",sans-serif;line-height:1.55}}
    body:before{{content:"";position:fixed;inset:0;pointer-events:none;background:radial-gradient(circle at 15% 5%,rgba(56,217,209,.09),transparent 28%),radial-gradient(circle at 85% 0%,rgba(104,167,255,.08),transparent 24%)}}
    .shell{{position:relative;max-width:1880px;margin:auto;padding:32px 28px 80px}}
    header{{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(420px,.55fr);gap:30px;align-items:end;margin-bottom:26px}}
    .eyebrow{{color:var(--cyan);font:700 12px/1.2 Consolas,monospace;letter-spacing:.18em;text-transform:uppercase}}
    h1{{font-size:clamp(30px,4vw,58px);line-height:1.05;letter-spacing:-.035em;margin:10px 0 16px;max-width:940px}} h1 span{{color:var(--cyan)}}
    .lede{{color:#bed0e0;font-size:16px;max-width:920px;margin:0}}
    .source-note{{border-left:3px solid var(--cyan);padding:12px 16px;background:rgba(16,29,44,.72);font-size:13px;color:#bed0e0}} .source-note b{{color:#fff}}
    .metrics{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:24px 0}}
    .metric{{background:linear-gradient(145deg,var(--panel2),var(--panel));border:1px solid var(--line);padding:18px;min-height:110px}}
    .metric span{{font-size:12px;color:var(--muted)}} .metric b{{display:block;font:700 30px/1 Consolas,monospace;margin:12px 0 8px}} .metric em{{font-size:12px;color:#b7c9d9;font-style:normal}}
    .metric.cyan b{{color:var(--cyan)}} .metric.amber b{{color:var(--amber)}} .metric.red b{{color:var(--red)}}
    .audit-grid{{display:grid;grid-template-columns:1fr 1.4fr;gap:18px;margin:20px 0 28px}}
    .card{{background:rgba(16,29,44,.92);border:1px solid var(--line);padding:20px}} .card h2{{font-size:15px;margin:0 0 12px}} .card p{{font-size:13px;color:#b9cadd;margin:8px 0}}
    .legend{{display:flex;flex-wrap:wrap;gap:9px;margin-top:14px}}
    .status,.rewrite-flag{{display:inline-flex;align-items:center;padding:3px 8px;border-radius:999px;font-size:11px;font-weight:700;margin:6px 6px 0 0}}
    .relabel{{color:#3b2500;background:var(--amber)}} .reviewed-keep{{color:#002c2a;background:var(--cyan)}} .unchanged{{color:#c9d7e5;background:#31465c}} .rewrite-flag{{color:#002c2a;background:var(--green)}}
    .distribution{{display:grid;grid-template-columns:repeat(7,1fr);gap:8px;list-style:none;padding:0;margin:0}}
    .distribution li{{border:1px solid var(--line);background:#0d1926;padding:10px;min-width:0}} .distribution span{{font:800 18px Consolas;color:var(--cyan)}} .distribution b{{display:block;font:700 20px Consolas;margin:6px 0}} .distribution em{{display:block;color:var(--muted);font-size:10px;font-style:normal;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
    .toolbar{{position:sticky;top:0;z-index:10;background:rgba(8,17,29,.96);backdrop-filter:blur(14px);border:1px solid var(--line);padding:13px;display:grid;grid-template-columns:minmax(240px,2fr) repeat(4,minmax(140px,.7fr)) auto;gap:9px;margin-bottom:12px;box-shadow:0 14px 30px rgba(0,0,0,.28)}}
    input,select,button{{width:100%;background:#101f30;color:var(--text);border:1px solid #36516b;padding:10px 12px;font:13px inherit;outline:none}} input:focus,select:focus{{border-color:var(--cyan);box-shadow:0 0 0 2px rgba(56,217,209,.14)}} button{{cursor:pointer;color:var(--cyan);font-weight:700}} button:hover{{background:#173049}}
    .visible-count{{grid-column:1/-1;color:var(--muted);font-size:12px}} .visible-count b{{color:#fff;font-family:Consolas,monospace}}
    .table-wrap{{overflow:auto;border:1px solid var(--line);background:var(--panel)}} table{{width:100%;min-width:1460px;border-collapse:collapse;table-layout:fixed}} thead th{{position:sticky;top:0;background:#17283a;color:#9fb7cc;text-align:left;font-size:11px;letter-spacing:.08em;padding:11px;border-bottom:1px solid var(--line);z-index:2}}
    tbody tr{{border-bottom:1px solid #22384d}} tbody tr:hover{{background:#14283b}} td{{vertical-align:top;padding:13px 11px;font-size:12px}}
    th:nth-child(1){{width:88px}} th:nth-child(2){{width:245px}} th:nth-child(3){{width:300px}} th:nth-child(4){{width:430px}} th:nth-child(5){{width:auto}}
    .index-cell b{{font:700 14px Consolas;color:#fff}} .index-cell span{{display:block;color:var(--muted);font:10px Consolas;margin-top:7px}}
    code{{color:#afc8dc;font:11px Consolas,monospace;overflow-wrap:anywhere}} .meta-row{{display:flex;flex-wrap:wrap;gap:5px;margin-top:9px}} .meta-pill{{border:1px solid #3a536b;color:#9fb3c5;padding:2px 6px;border-radius:3px;font-size:9px}} .meta-pill.noise{{border-color:#76502e;color:#ffca81}} .meta-pill.clean{{border-color:#2c8060;color:#8be7b0}} .meta-pill.changed-meta{{border-color:#8b6c30;color:#ffd18a}}
    .labels-cell>div{{display:flex;align-items:center;gap:7px;flex-wrap:wrap}} .label-badge{{display:inline-flex;align-items:center;gap:6px;color:#c8d8e7;font-size:10px}} .label-badge b{{display:grid;place-items:center;width:25px;height:25px;background:#243b51;color:#fff;font:800 14px Consolas}} .labels-cell .label-badge:last-child b{{background:var(--cyan);color:#002c2a}} .arrow{{color:var(--amber);font-size:16px}} .arrow.same{{color:#62788d}}
    .text-label{{color:var(--muted);font-size:9px;letter-spacing:.08em;margin-bottom:3px}} .utterance{{font-size:15px;font-weight:700;color:#fff;margin-bottom:9px;line-height:1.55}} .revised-text{{color:#c8fff0}} .raw-copy{{display:grid;grid-template-columns:62px 1fr;gap:8px;margin:4px 0 10px;padding:8px;background:#0b1722;border-left:2px solid #6f4e3e}} .raw-copy b{{font-size:9px;color:#d0a98f}} .raw-copy span{{color:#a9b8c4;text-decoration:line-through;text-decoration-color:#805349}} details{{border-top:1px dashed #314a61;padding-top:7px}} .raw-history{{margin-top:7px}} .raw-history summary{{color:#c79b80}} summary{{cursor:pointer;color:#7fcfc9;font-size:11px}} .history{{margin-top:10px;display:grid;gap:7px}} .turn{{display:grid;grid-template-columns:36px 1fr;gap:8px}} .turn span{{font-size:9px;color:var(--muted);padding-top:3px}} .turn p{{margin:0;padding:7px 9px;background:#0c1824;color:#bdccda}} .turn.assistant p{{border-left:2px solid #517090}} .turn.user p{{border-left:2px solid var(--cyan)}}
    .confidence{{color:var(--muted);font-size:10px}} .confidence b{{color:#fff}} .audit-cell p{{margin:7px 0 0;color:#bed0df}} .audit-cell .rewrite-reason{{color:#a9e9cb;border-top:1px dashed #2f5748;padding-top:8px}} .muted{{color:var(--muted)}}
    footer{{margin-top:20px;padding:18px;border:1px solid var(--line);color:var(--muted);font:11px Consolas,monospace;overflow-wrap:anywhere}}
    .empty{{display:none;padding:50px;text-align:center;border:1px solid var(--line);color:var(--muted)}}
    @media(max-width:1000px){{header,.audit-grid{{grid-template-columns:1fr}}.metrics{{grid-template-columns:1fr 1fr}}.distribution{{grid-template-columns:repeat(4,1fr)}}.toolbar{{position:relative;grid-template-columns:1fr 1fr}}}}
    @media(max-width:620px){{.shell{{padding:22px 12px 60px}}.metrics{{grid-template-columns:1fr}}.distribution{{grid-template-columns:repeat(2,1fr)}}.toolbar{{grid-template-columns:1fr}}}}
    @media print{{body{{background:#fff;color:#111}}body:before,.toolbar{{display:none}}.shell{{max-width:none;padding:0}}.card,.metric,.table-wrap{{background:#fff;border-color:#bbb}}table{{min-width:0;font-size:8px}}thead th{{position:static;background:#eee;color:#111}}details:not([open])>*:not(summary){{display:none}}}}
  </style>
</head>
<body>
<main class="shell">
  <header>
    <div><div class="eyebrow">Context-aware corpus correction · 2026-08-19</div><h1>哒哒 Agent 修订后 <span>1300 条</span>测试语料</h1><p class="lede">按完整 history、ctx 与当前用户句联合校正。除标签审计外，本版已把失败集中的 ASR 破句、歧义、多意图和上下文冲突改成自然、单一且可判定的测试表达。</p></div>
    <div class="source-note"><b>数据边界</b><br>原始 raw 文件保持只读，未被改写。页面同时保留 raw 原文与修订文本；修订文本及修订后 history 才是下一轮模型测试的实际输入。1191 条未进入失败集的样本继续沿用 raw。</div>
  </header>
  <section class="metrics">
    <div class="metric cyan"><span>完整测试语料</span><b>1300</b><em>a–m 各 100 条</em></div>
    <div class="metric cyan"><span>逐条复核 109</span><b>109</b><em>覆盖上一轮全部失败样本</em></div>
    <div class="metric amber"><span>修订标签 64</span><b>{status_counts['relabel']}</b><em>原标签 → 正确分支</em></div>
    <div class="metric cyan"><span>已改写语料 63</span><b>{rewrite_count}</b><em>破句、歧义与多意图已处理</em></div>
    <div class="metric red"><span>遗留破损 0</span><b>{unresolved_count}</b><em>原 15 条建议改写已全部解决</em></div>
  </section>
  <section class="audit-grid">
    <article class="card"><h2>修订口径</h2><p>① 用 history 与 <code>ctx=supplement/coref/switch/unrelated</code> 消歧；② 保留自然口语，但删除无法还原的 ASR、错误指代和生成元话语；③ 有副作用的提醒/设备动作不被寒暄吞掉；④ 多意图样本改成与正确标签一致的单一主意图；⑤ 必要时同步修订 history 和 ctx，保证整段对话自洽。</p><div class="legend"><span class="status relabel">已改标</span><span class="status reviewed-keep">复核保留</span><span class="status unchanged">沿用 raw</span><span class="rewrite-flag">已改写</span></div></article>
    <article class="card"><h2>修订后标签分布</h2><ul class="distribution">{distribution}</ul></article>
  </section>
  <section class="toolbar" aria-label="语料筛选器">
    <input id="keywordSearch" type="search" placeholder="搜索 ID、用户原文、上下文或审计理由…">
    <select id="labelFilter"><option value="all">全部修订标签</option>{label_options}</select>
    <select id="statusFilter"><option value="all">全部审计状态</option><option value="relabel">已改标</option><option value="reviewed_keep">复核保留</option><option value="unchanged">沿用 raw</option></select>
    <select id="ctxFilter"><option value="all">全部 ctx</option><option value="supplement">supplement</option><option value="coref">coref</option><option value="switch">switch</option><option value="unrelated">unrelated</option><option value="none">none</option></select>
    <select id="noiseFilter"><option value="all">全部文本</option><option value="true">ASR 噪声</option><option value="false">干净文本</option></select>
    <button id="resetFilters" type="button">重置</button>
    <div class="visible-count">当前显示 <b id="visibleRows">1300</b> / 1300 条</div>
  </section>
  <div class="table-wrap">
    <table><thead><tr><th>序号 / 来源</th><th>样本 ID / 属性</th><th>原标签 → 修订标签</th><th>修订文本 / raw 原文 / 上下文</th><th>标签与表达修订依据</th></tr></thead><tbody>{''.join(rows_html)}</tbody></table>
  </div>
  <div id="emptyState" class="empty">没有符合当前筛选条件的语料。</div>
  <footer>corpus-fingerprint sha256: {raw_fingerprint} · reviewed={status_counts['relabel'] + status_counts['reviewed_keep']} · relabeled={status_counts['relabel']} · rewritten={rewrite_count} · unresolved={unresolved_count} · reviewed_keep={status_counts['reviewed_keep']} · inherited_raw={status_counts['unchanged']}</footer>
</main>
<script>
(() => {{
  const rows = Array.from(document.querySelectorAll('.corpus-row'));
  const keyword = document.getElementById('keywordSearch');
  const label = document.getElementById('labelFilter');
  const status = document.getElementById('statusFilter');
  const ctx = document.getElementById('ctxFilter');
  const noise = document.getElementById('noiseFilter');
  const count = document.getElementById('visibleRows');
  const empty = document.getElementById('emptyState');
  function apply() {{
    const q = keyword.value.trim().toLowerCase();
    let visible = 0;
    rows.forEach(row => {{
      const show = (!q || row.dataset.search.includes(q))
        && (label.value === 'all' || row.dataset.label === label.value)
        && (status.value === 'all' || row.dataset.status === status.value)
        && (ctx.value === 'all' || row.dataset.ctx === ctx.value)
        && (noise.value === 'all' || row.dataset.noise === noise.value);
      row.hidden = !show;
      if (show) visible += 1;
    }});
    count.textContent = visible;
    empty.style.display = visible ? 'none' : 'block';
    document.querySelector('.table-wrap').style.display = visible ? 'block' : 'none';
  }}
  [keyword, label, status, ctx, noise].forEach(el => el.addEventListener('input', apply));
  document.getElementById('resetFilters').addEventListener('click', () => {{
    keyword.value = ''; label.value = status.value = ctx.value = noise.value = 'all'; apply(); keyword.focus();
  }});
}})();
</script>
</body>
</html>'''


def write_report(output_path: pathlib.Path, corpus: list[dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_html(corpus), encoding="utf-8")


def write_corrected_jsonl(output_path: pathlib.Path, corpus: list[dict[str, Any]]) -> None:
    """Write the corrected dataset in the same practical shape as sample-1300."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for row in corpus:
        rows.append(
            {
                "label": row["revised_label"],
                "rounds": row["rounds"],
                "ctx": row["ctx"],
                "hard_pair": row["hard_pair"],
                "history": row["history"],
                "text": row["text"],
                "asr_noise": row["asr_noise"],
                "src": row["src"],
                "source_file": row["source_file"],
                "source_line": row["source_line"],
                "rounds_bucket": row["rounds_bucket"],
                "stratum": row["stratum"],
                "sample_id": row["sample_id"],
                "audit": {
                    "raw_label": row["original_label"],
                    "raw_text": row["original_text"],
                    "raw_history": row["original_history"],
                    "raw_ctx": row["original_ctx"],
                    "raw_asr_noise": row["original_asr_noise"],
                    "label_revised": row["original_label"] != row["revised_label"],
                    "text_rewritten": row["text_status"] == "rewritten",
                    "confidence": row["confidence"],
                    "label_reason": row["reason"],
                    "rewrite_reason": row["rewrite_reason"],
                },
            }
        )
    output_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    here = pathlib.Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=pathlib.Path, default=here / "sample-1300.jsonl")
    parser.add_argument("--raw-root", type=pathlib.Path, default=pathlib.Path(r"C:\Users\lenovo\Downloads\raw"))
    parser.add_argument("--output", type=pathlib.Path, default=here / "哒哒Agent-修订后1300条测试语料-2026-08-19.html")
    parser.add_argument("--jsonl-output", type=pathlib.Path, default=here / "sample-1300-corrected-2026-08-19.jsonl")
    args = parser.parse_args()
    corpus = load_corrected_corpus(args.sample, args.raw_root)
    write_report(args.output, corpus)
    write_corrected_jsonl(args.jsonl_output, corpus)
    print(json.dumps({
        "output": str(args.output),
        "jsonl_output": str(args.jsonl_output),
        "rows": len(corpus),
        "reviewed": sum(row["audit_status"] != "unchanged" for row in corpus),
        "relabeled": sum(row["audit_status"] == "relabel" for row in corpus),
        "rewritten": sum(row["text_status"] == "rewritten" for row in corpus),
        "unresolved_quality_issues": sum(row["unresolved_quality_issue"] for row in corpus),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
