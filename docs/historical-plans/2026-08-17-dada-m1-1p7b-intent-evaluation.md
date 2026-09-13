# 哒哒 Agent M1 / 1.7B 十三分支意图评测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从 raw 的 a～m 十三个 JSONL 文件分层抽取各 100 条，在服务器现有 1.7B 模型上完成 1300 条真实分类调用，并输出逐条证据、统计汇总和单文件 HTML 报告。

**Architecture:** 本地只编写标准库 Python 评测工具；服务器用 production rsync 副本建立隔离运行目录，raw 全量上传到隔离输入目录后固定种子分层抽样。探针直接调用 `llm.classify_1p7b`，不进入 M3；汇总器同时计算原始分类与生产 M1 阈值门控指标。所有结果下载到本地报告目录，最后重新核验生产哈希与 Agent PID。

**Tech Stack:** Python 3.10.12、Python 标准库、pytest、现有 `dada.infra.llm` OpenAI/v1 客户端、PowerShell OpenSSH、HTML/CSS。

## Global Constraints

- raw 的 `label` 是唯一标准答案，不人工改标。
- 正确映射是 `l=再见`；流程图中的 `i=再见` 不参与判分。
- 每个标签恰好 100 条，共 1300 条；固定随机种子 `20260817`。
- 分层字段是 `asr_noise`、`rounds` 桶（1/2/3/4+）和 `hard_pair` 是否存在。
- 必须原样携带 raw `history`；不得向模型泄漏 label、文件名或分层元数据。
- 只允许写 `/home/number/dada-runtime/asr-api-test-env/xiaozhi-server-m1-intent-eval-20260817/` 和本地 `D:\Codex-chat\2026-08-17-m1-1p7b-intent-eval\`。
- 不修改、不重启生产 Agent 或 1.7B 服务；日志不得包含密钥或 Authorization header。
- 生产阈值使用 `top1 > 0.98055846`、`margin > 0.0` 的严格不等式。

---

### Task 1: 分层抽样器与可复现性测试

**Files:**
- Create: `D:\Codex-chat\2026-08-17-m1-1p7b-intent-eval\sample_builder.py`
- Create: `D:\Codex-chat\2026-08-17-m1-1p7b-intent-eval\test_sample_builder.py`

**Interfaces:**
- Consumes: `raw_dir: pathlib.Path`，其中包含 a.jsonl～m.jsonl。
- Produces: `build_sample(raw_dir, per_label=100, seed=20260817) -> list[dict]` 和 `write_sample(rows, output_jsonl, manifest_json)`。

- [ ] **Step 1: 写抽样器失败测试**

测试构造 a～m 的小型临时 JSONL，断言每标签数量、固定种子重复输出一致、完整记录去重、来源行号存在、history 不丢失、标签与文件名不符时报错。

- [ ] **Step 2: 在服务器临时目录运行测试并确认失败**

Run: `python3 -m pytest -q test_sample_builder.py`

Expected: FAIL，提示 `sample_builder` 或 `build_sample` 尚不存在。

- [ ] **Step 3: 实现抽样器**

实现函数：

```python
def rounds_bucket(value: int) -> str: ...
def stratum_key(row: dict) -> tuple[bool, str, bool]: ...
def allocate_largest_remainder(counts: dict, total: int) -> dict: ...
def build_sample(raw_dir: Path, per_label: int = 100,
                 seed: int = 20260817) -> list[dict]: ...
def write_sample(rows: list[dict], output_jsonl: Path,
                 manifest_json: Path) -> None: ...
```

每条输出附加 `source_file`、`source_line`、`sample_id`、`rounds_bucket` 和 `stratum`；层内随机对象使用 `random.Random(f"{seed}:{label}:{stratum}")`，不依赖进程全局随机状态。

- [ ] **Step 4: 运行测试并确认通过**

Run: `python3 -m pytest -q test_sample_builder.py`

Expected: 全部 PASS。

### Task 2: 1.7B 探针、logprobs 与门控测试

**Files:**
- Create: `D:\Codex-chat\2026-08-17-m1-1p7b-intent-eval\m1_probe.py`
- Create: `D:\Codex-chat\2026-08-17-m1-1p7b-intent-eval\test_m1_probe.py`

**Interfaces:**
- Consumes: `sample-1300.jsonl` 与 production copy 的 `dada.infra.llm`、`branch_prompts.M1_CLASSIFIER_SYSTEM`。
- Produces: `results-1300.jsonl`，每输入样本恰好一行。

- [ ] **Step 1: 写纯函数失败测试**

覆盖 `normalize_label`、OpenAI logprobs 首 token 解析、top1 与 margin 计算、严格阈值边界、history 二元数组转 messages、空响应与无效字符。

- [ ] **Step 2: 运行测试并确认失败**

Run: `python3 -m pytest -q test_m1_probe.py`

Expected: FAIL，提示待测函数不存在。

- [ ] **Step 3: 实现探针**

实现：

```python
def normalize_label(content: str | None) -> str | None: ...
def parse_gate_stats(logprobs: dict | None) -> tuple[float | None, float | None, list[dict]]: ...
def is_direct(valid: bool, top1: float | None, margin: float | None,
              threshold: float = 0.98055846, margin_threshold: float = 0.0) -> bool: ...
def build_messages(row: dict, system_prompt: str) -> list[dict]: ...
def evaluate_one(row: dict) -> dict: ...
```

`evaluate_one` 直接调用 `llm.classify_1p7b(messages)`，记录原始输出、预测、top1、margin、top5、latency、correct、direct、dangerous_misroute 和 exception。异常不重试。

- [ ] **Step 4: 测试断点续跑**

结果写入前检查既有 `sample_id`；重启时跳过已完成样本，最终按抽样文件顺序重排并验证 1300 个唯一 ID。

- [ ] **Step 5: 运行测试并确认通过**

Run: `python3 -m pytest -q test_m1_probe.py`

Expected: 全部 PASS。

### Task 3: 汇总器与 HTML 报告测试

**Files:**
- Create: `D:\Codex-chat\2026-08-17-m1-1p7b-intent-eval\aggregate_results.py`
- Create: `D:\Codex-chat\2026-08-17-m1-1p7b-intent-eval\render_report.py`
- Create: `D:\Codex-chat\2026-08-17-m1-1p7b-intent-eval\test_reporting.py`

**Interfaces:**
- Consumes: `results-1300.jsonl`、抽样 manifest 和生产完整性 JSON。
- Produces: `summary.json` 与 `哒哒Agent-M1-1.7B十三分支意图分类实测报告-2026-08-17.html`。

- [ ] **Step 1: 写指标失败测试**

使用小型混淆样本，断言 accuracy、macro-F1、per-label precision/recall/F1、13×13 confusion、直进覆盖率、直进准确率、危险误路由率、Wilson 区间、P50/P95/P99。

- [ ] **Step 2: 实现汇总器**

实现：

```python
def confusion_matrix(rows, labels=tuple("abcdefghijklm")) -> dict: ...
def classification_metrics(rows, labels=tuple("abcdefghijklm")) -> dict: ...
def gate_metrics(rows) -> dict: ...
def stratum_metrics(rows) -> dict: ...
def wilson(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]: ...
def percentile(values: list[float], p: float) -> float | None: ...
```

- [ ] **Step 3: 实现无外部依赖 HTML 报告**

报告内嵌 CSS，不加载 CDN；包含总体结论、M1/M3流程、抽样、KPI、十三分支表、混淆矩阵、分层分析、错误样本、时延、验收矩阵和生产完整性。

- [ ] **Step 4: 运行报告测试并确认通过**

Run: `python3 -m pytest -q test_reporting.py`

Expected: 全部 PASS，且 HTML 包含 UTF-8、1300、a～m、混淆矩阵、危险误路由率和结束标签。

### Task 4: 建立服务器隔离目录并锁定生产基线

**Files:**
- Create on server: `/home/number/dada-runtime/asr-api-test-env/xiaozhi-server-m1-intent-eval-20260817/`
- Create on server: `production-before.json`

**Interfaces:**
- Consumes: production root `/home/number/dada-runtime/asr-api-test-env/xiaozhi-server/`。
- Produces: rsync 隔离副本、测试脚本和 raw 输入目录。

- [ ] **Step 1: 记录 Python、进程、端口与关键文件哈希**

对设计文档列出的五个文件执行 SHA-256，记录 production Agent PID；只读取配置中的非敏感阈值和模型名，不打印 URL token。

- [ ] **Step 2: 创建并核对隔离目标绝对路径**

验证目标严格等于 `/home/number/dada-runtime/asr-api-test-env/xiaozhi-server-m1-intent-eval-20260817`，再使用 `rsync -a` 从 production root 复制；不删除既有目录，如存在则先只读检查内容并复用。

- [ ] **Step 3: 上传评测脚本和 raw**

把本地 5 个 Python 文件、3 个测试文件及整个 raw 目录上传到隔离目录下的 `eval/`；不得上传 SSH 私钥。

### Task 5: 测试脚本与生成 1300 条固定样本

- [ ] **Step 1: 在隔离目录运行全部 pytest**

Run: `python3 -m pytest -q eval/test_sample_builder.py eval/test_m1_probe.py eval/test_reporting.py`

Expected: 全部 PASS。

- [ ] **Step 2: 生成抽样集**

Run: `python3 eval/sample_builder.py --raw-dir eval/raw --output eval/sample-1300.jsonl --manifest eval/sample-manifest.json --per-label 100 --seed 20260817`

- [ ] **Step 3: 验证抽样清单**

断言 1300 行、a～m 各 100、样本 ID 唯一、来源行号存在、标签与文件名一致；输出各分层抽样前后比例差异。

### Task 6: 真实调用 1.7B 并监控质量

- [ ] **Step 1: 运行 13 条冒烟测试**

每分支取 1 条，验证模型返回、logprobs 结构、延迟和结果落盘；冒烟结果单独存放，不计入正式成绩。

- [ ] **Step 2: 执行 1300 条正式测试**

Run: `python3 eval/m1_probe.py --input eval/sample-1300.jsonl --output eval/results-1300.jsonl --checkpoint-every 10`

每 100 条输出一次进度；若调用失败率超过 1%，停止并诊断。保持生产 Agent 运行，不启动隔离 Agent。

- [ ] **Step 3: 验证正式日志完整性**

断言结果正好 1300 行、sample_id 唯一且覆盖抽样集、没有泄漏 label 到 messages、每条有 latency 或 exception。

### Task 7: 汇总分析与报告生成

- [ ] **Step 1: 生成 summary.json**

Run: `python3 eval/aggregate_results.py --input eval/results-1300.jsonl --output eval/summary.json`

- [ ] **Step 2: 复核关键指标**

人工用独立计数核对总正确数、每标签正确数、direct 总数和 dangerous_misroute 总数；与 summary 一致才继续。

- [ ] **Step 3: 记录测试后生产基线**

重新计算五个 SHA-256、Agent PID 和 Python 版本，写 `production-after.json`；逐项与 before 比较。

- [ ] **Step 4: 生成 HTML**

Run: `python3 eval/render_report.py --summary eval/summary.json --results eval/results-1300.jsonl --manifest eval/sample-manifest.json --integrity-before production-before.json --integrity-after production-after.json --output eval/哒哒Agent-M1-1.7B十三分支意图分类实测报告-2026-08-17.html`

### Task 8: 下载证据并完成交付验证

- [ ] **Step 1: 下载正式产物**

下载 sample、manifest、results、summary、HTML、测试输出和生产 before/after JSON 到 `D:\Codex-chat\2026-08-17-m1-1p7b-intent-eval\`。

- [ ] **Step 2: 做 HTML 静态完整性检查**

检查 UTF-8、无替换字符、section/table 标签数量相等、核心计数与 summary 一致、无 `Authorization`、`api_key` 或私钥内容。

- [ ] **Step 3: 最终验证**

运行 superpowers:verification-before-completion，逐项核对用户要求、正式日志、指标、报告、隔离目录和生产未改动证据后再宣布完成。

## 执行方式

当前任务采用 **Inline Execution**：在本会话使用 `superpowers:executing-plans` 按上述任务执行并在关键节点汇报。`D:\Codex-chat` 当前不是 Git 工作树，因此不创建提交；以脚本 SHA-256、正式日志和生产 before/after 哈希作为变更与复现证据。
