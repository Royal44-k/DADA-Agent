# 哒哒 Agent M1 / 1.7B 十三分支意图评测设计

## 目标

使用 `C:\Users\lenovo\Downloads\raw\a.jsonl` 至 `m.jsonl` 作为带标签语料库，在服务器现有 1.7B 模型上执行可复现的十三分类评测。每个分支抽取 100 条，共 1300 条，最终输出逐条日志、聚合指标与单文件 HTML 报告。

## 真值与标签映射

raw 记录的 `label` 是唯一标准答案，不进行人工改标。流程图中的“i=再见”是已确认的绘图瑕疵；正式映射以 raw 和生产代码为准：

| 标签 | 生产分支 | 语义 |
|---|---|---|
| a | reminder_write | 新建提醒 |
| b | reminder_modify | 修改、取消或完成提醒 |
| c | reminder_query | 查询提醒、任务或日程 |
| d | memory_write | 增加、修正或删除记忆 |
| e | memory_query | 查询记忆 |
| f | volume_adjust | 调整音量 |
| g | brightness_adjust | 调整亮度 |
| h | weather_query | 查询天气 |
| i | time_query | 查询时间、日期、农历或宜忌 |
| j | knowledge_query | 产品功能或知识查询 |
| k | goodnight | 晚安、准备睡觉 |
| l | farewell | 再见、离开 |
| m | chitchat | 闲聊、情感、超纲或其他 |

## 已核对的生产链路

生产代码先由 `m7_build_messages` 拼入短期历史，再由 `m1_gate.m1_classify` 把 system 替换成 `branch_prompts.M1_CLASSIFIER_SYSTEM`，调用 `llm.classify_1p7b(messages, logprobs=True, top_logprobs=5)`。首 token 输出经 `strip().lower()` 归一化为 a～m。

M1 直进条件为严格不等式：

- `top1 > 0.98055846`
- `margin > 0.0`
- 输出字符属于 a～m

不满足条件的生产请求进入 M3 / 9B 工具面板。为测量 1.7B 自身能力，正式测试直接调用 `classify_1p7b`，不触发 M3；但离线按相同阈值计算 M1 直进指标。

## 分层抽样

对每个标签独立抽取 100 条，随机种子固定为 `20260817`。分层键为：

1. `asr_noise`：false / true；
2. `rounds`：1、2、3、4+；
3. `hard_pair` 是否存在。

在每个标签内按上述交叉分层，以最大余数法按原始占比分配 100 个名额；非空小层在名额允许时至少保留 1 条。层内使用固定种子洗牌。完整 JSON 行重复项只保留一条；相同 `text` 但 `history` 不同视为不同上下文样本，可以同时入选。

抽样后必须验证：

- 每个标签恰好 100 条；
- 共 1300 条；
- 每条 `label` 与来源文件名一致；
- 选中记录无完整重复；
- 抽样清单包含来源文件和原始行号，能够追溯。

## 模型输入与输出

每条 raw 记录转换为：

1. system：服务器生产 `M1_CLASSIFIER_SYSTEM`；
2. history：把 raw 的 `[role, content]` 二元数组按原顺序转成 OpenAI messages；
3. user：当前记录的 `text`。

不得把标准答案、文件名、hard_pair、asr_noise 或其他元数据发送给模型。`ctx` 不进入提示词。

逐条记录字段：来源文件、原始行号、真值、轮次、噪声标记、hard_pair、history、text、模型原始输出、归一化预测、有效标签、top1、margin、top5、延迟、是否预测正确、是否满足 M1 直进条件、是否为高置信误路由、错误信息。

模型调用发生异常或空响应时只记录失败，不静默重试；另统计传输失败率，避免重试掩盖服务稳定性。若整体调用失败超过 1%，暂停测试并先诊断服务或脚本。

## 指标

### 1.7B 原始分类能力

- 总体准确率与 macro-F1；
- 每分支 precision、recall、F1、正确数 / 100；
- 13×13 混淆矩阵；
- 无效输出率；
- 各真值分支最常见误判去向。

### M1 门控安全性

- 高置信直进覆盖率：满足生产阈值的样本数 / 有效调用数；
- 高置信直进准确率：满足阈值且预测正确 / 满足阈值；
- 危险误路由率：满足阈值但预测错误 / 有效调用数；
- 误路由中的 top1、margin 与分支分布；
- 低置信转 M3 比例。

### 分层与性能

- 干净语料与 ASR 噪声准确率；
- 单轮、2轮、3轮、4+轮准确率；
- hard_pair 与普通样本准确率；
- 各 hard_pair 的定向混淆；
- 平均、P50、P95、P99、最大延迟与吞吐。

置信区间使用 Wilson 95% 区间。报告明确区分“1.7B 预测错误”和“生产 M1 会不会高置信直进”；低置信错误不会被描述为已经进入错误业务分支，因为生产链路会转交 M3。

## 执行隔离

服务器新增隔离目录：

`/home/number/dada-runtime/asr-api-test-env/xiaozhi-server-m1-intent-eval-20260817/`

隔离目录只包含测试脚本、固定抽样集、日志和汇总，不覆盖生产文件，不启动或重启 Agent。脚本通过现有生产 Python 环境和配置访问已经运行的 1.7B 服务。

测试前后分别计算下列生产关键文件 SHA-256 并比较：

- `dada/mechanisms/m1_gate.py`
- `dada/infra/llm.py`
- `dada/infra/prompts/branch_prompts.py`
- `dada/agent/flow.py`
- `data/.config.yaml`

同时记录生产 Agent PID、1.7B 服务端点健康状态和 Python 版本。日志不得输出密钥、Authorization header 或完整配置。

## 报告结构

HTML 报告至少包含：

1. 执行摘要与总体结论；
2. 哒哒 Agent M1→M3 路由关系；
3. raw 语料与分层抽样方法；
4. 总体准确率、macro-F1、门控覆盖率和危险误路由率；
5. 十三个分支逐项成绩；
6. 混淆矩阵；
7. ASR、多轮、hard_pair 与延迟分析；
8. 典型错误样本及置信度；
9. 是否达到上线要求及改进建议；
10. 服务器隔离性、生产哈希和本地证据路径。

报告与正式逐条日志保存在本地 `D:\Codex-chat\2026-08-17-m1-1p7b-intent-eval\`，报告为 UTF-8、无外部网络依赖的单文件 HTML。

## 验收口径

本次报告采用以下分级，不预设模型一定通过：

- 原始 macro-F1 ≥ 95%：分类能力通过；90%～95%：有条件通过；< 90%：不通过。
- 高置信直进准确率 ≥ 99.5% 且危险误路由率 ≤ 0.1%：M1 门控安全性通过。
- 无效输出率 ≤ 0.1%，调用失败率 ≤ 1%。
- ASR 噪声、多轮或 hard_pair 任一核心分层低于总体准确率 10 个百分点以上，单列为上线风险，即使总体成绩通过。

这些阈值只用于本批工程验收；报告同时呈现原始计数，便于后续调整业务阈值。
