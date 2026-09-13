# Grok Build 工具调用容错机制调研报告

> 调研对象：xAI 开源编码 Agent「Grok Build」（Rust）
> 调研日期：2026-07-20
> 核心问题：**大模型调用工具时，系统如何判断"调错了"，以及如何挽回？**
> 所有代码引用均为本仓库（浅克隆于 2026-07-17）内的真实路径与行号。

---

## 0. 一句话总结

Grok 的哲学是 **"宽进 + 回喂自愈"（tolerant-in, feed-back-to-heal）**：

- **判错**：分层检测，从"参数是坏 JSON"到"模型嘴上说做了实际没做"，每层有独立的判据；
- **挽回**：几乎从不代替模型做决定，而是**把错误现场（含模型自己的原始输出）作为 tool_result 回喂进对话历史，让模型自己修**；
- **硬防线极少**：只有 max_turns（子 agent 轮数上限，直接终止）和 doom-loop 重采样预算（超了就照单全收）。工具报错**不会**累计成"错 N 次就杀会话"——他们明确移除了错误连击计数（见 `tool_calls.rs:2233` 注释："error-count streaks were removed"）。

判错与挽回的全景表：

| 层   | 错误类型                  | 判错手段                               | 挽回手段                                           | 代码位置                                                 |
| --- | --------------------- | ---------------------------------- | ---------------------------------------------- | ---------------------------------------------------- |
| 1   | 参数为空字符串               | trim 后为空                           | 把""静默归一化为规范json格式 `{}`，不算错                     | `tool_input_parsing.rs:39`                           |
| 1   | 多个 JSON 对象拼接          | StreamDeserializer 解析出 ≥2 个对象      | 挑最匹配的一个执行 + system-reminder 教育                 | `tool_input_parsing.rs:1`、`tool_calls.rs:2086`       |
| 1   | 参数是坏 JSON / 缺字段 / 类型错 | serde 解析失败                         | 回显原始参数 + JSON 错误位置，让模型改 typo；历史里消毒为 `{}` 防 400 | `tool_dispatch.rs:379`、`conversation.rs:1658`        |
| 2   | 调了不存在的工具              | 工具注册表查无此名                          | `Tool not found: X` 回喂，turn 继续                 | `registry/types.rs:1350`                             |
| 2   | MCP 工具还没初始化好          | MCP state 未 initialized            | 回喂 "Use search_tool to find available tools"   | `tool_calls.rs:803`                                  |
| 2   | 把原生工具塞进 use_tool      | 名字命中原生工具集合                         | 定向纠正错误："call it directly"（线上评测：86% 救回）         | `use_tool/mod.rs:346`                                |
| 3   | 工具执行失败                | 工具返回 Err 或输出带 error 标记             | `Tool \`X\` failed: {err}` 回喂，turn 继续          | `tool_calls.rs:2237`                                 |
| 3   | 401 / MCP 掉授权         | 错误分类器识别                            | 自动刷新 token 重试一次，模型无感                           | `tool_calls.rs:499-515`                              |
| 4   | 生成层死循环（doom loop）     | 服务端 SSE 信号 `tail_repetition`       | 中途掐断流、丢弃本次、重采样（预算 2 次，超了照单全收）                  | `sampler/src/doom_loop.rs`、`request_task.rs:118-237` |
| 4   | 空响应                   | 流结束但无内容无工具调用                       | 按重试策略重采样                                       | `request_task.rs:179`                                |
| 4   | 空头支票 / 假完工            | 空闲 10s 后独立分类器审计"claim vs evidence" | 注入 system-reminder nudge 点名纠正                  | `laziness_classifier.rs`、`laziness.rs`               |
| 5   | 无限工具循环                | 轮数计数                               | max_turns 硬终止（不回喂，直接结束 turn）                   | `turn.rs:2289`                                       |

以下逐层展开，每层附**全量上下文示例**（即完整还原对话历史里模型实际看到的消息序列）。

---

## 1. 第一层：参数层面的"调错了"——先尽量救，救不了再回喂

调用入口是 `prepare_tool_call`（`crates/codegen/xai-grok-shell/src/session/acp_session_impl/tool_calls.rs:742`）。模型发来的 `function.arguments` 是一个字符串，处理管线是：

```
arguments 字符串
  │
  ├─ ①空/纯空白？ → 归一化为 "{}"（零参数工具常见，不算错误）
  │
  ├─ ②serde_json 解析成功？ → 进入类型化解析 try_parse
  │
  ├─ ③解析失败但是"多个 JSON 对象拼接"？ → 挑出最匹配的一个执行，
  │     执行结果后面追加 system-reminder 教育模型下次分开调
  │
  ├─ ④彻底失败 → 包成 {"raw": "<原文>"} 继续走 try_parse（必然失败）
  │     → 触发"回喂自愈"：错误 + 原始参数 + JSON 错误坐标 全部塞进 tool_result
  │
  └─ ⑤类型化解析 try_parse（serde 反序列化成该工具的输入结构体）
        失败（缺字段/类型错/未知工具）→ 同④回喂
```

### 1.1 空参数：静默救回，不惊动模型

`tool_input_parsing.rs:39`——零参数 MCP 工具（如 `get_me`）模型经常发 `""` 而不是 `"{}"`，直接归一化，不产生任何错误：

```rust
pub fn normalize_empty_arguments(arguments: &str) -> &str {
    if arguments.trim().is_empty() { "{}" } else { arguments }
}
```

**设计点**：不是所有"格式不对"都值得教育模型。零成本能确定意图的，直接修，省一轮往返。

### 1.2 拼接 JSON：执行一个 + 教育剩下的

模型有时想批量操作，把 N 个调用的参数拼在一次调用里：
`{"target_file":"a.java"}{"target_file":"b.java"}{"target_file":"c.java"}`

**判错**（`tool_input_parsing.rs:1`）：整体解析失败后，用 `serde_json::StreamDeserializer` 流式解析——它能正确处理嵌套大括号（不是幼稚的按 `}{` 切分），解析出 ≥2 个完整对象才认定是拼接。

**挽回分两步**（`tool_calls.rs:829-861`）：

1. **挑最匹配的执行**：逐个对象尝试 `try_parse`（用该工具的真实输入 schema 校验），第一个能通过校验的当选；都不行就用第一个。
2. **执行成功后，在 tool_result 末尾追加教育**（`tool_calls.rs:2086`）。

**全量上下文示例**（对话历史中模型实际看到的序列）：

```jsonc
// ── 模型输出（assistant turn）──
{
  "role": "assistant",
  "tool_calls": [{
    "id": "call_123",
    "function": {
      "name": "read_file",
      "arguments": "{\"target_file\":\"a.java\"}{\"target_file\":\"b.java\"}{\"target_file\":\"c.java\"}"
    }
  }]
}

// ── 系统回喂（tool_result，只执行了 a.java 的读取）──
{
  "role": "tool",
  "tool_call_id": "call_123",
  "content": "1  package com.example;\n2  public class A {\n...（a.java 的正常读取结果）...\n\n<system-reminder>\nIMPORTANT: Your tool call contained 3 concatenated JSON objects, but only the best-matching one was executed. The remaining 2 were ignored. You MUST use separate tool calls (one per operation) instead of concatenating multiple JSON objects in a single call's arguments. Make 2 individual tool calls for the remaining operations.\n</system-reminder>"
}

// ── 模型下一轮：补发两个独立调用 ──
{
  "role": "assistant",
  "tool_calls": [
    { "id": "call_124", "function": { "name": "read_file", "arguments": "{\"target_file\":\"b.java\"}" } },
    { "id": "call_125", "function": { "name": "read_file", "arguments": "{\"target_file\":\"c.java\"}" } }
  ]
}
```

**设计点**：不是全盘拒绝（模型的工作白干、还得整轮重来），也不是全部执行（顺序/副作用不可控），而是**救一个 + 明确告知剩下几个没执行 + 给出精确的补救指令**（"Make 2 individual tool calls"，连数字都算好）。

### 1.3 坏 JSON / 缺字段：回显现场，让模型改 typo 而不是重写全文

这是"回喂自愈"最核心的一段。`build_tool_parse_error_message`（`tool_dispatch.rs:379`）构造的错误消息**刻意包含三样东西**（源码注释原文说明了理由）：

1. **错误描述**——模型知道*什么*失败了；
2. **模型自己发的原始参数**（截断到 2000 字节，`MAX_ARGS_IN_ERROR`，`tool_dispatch.rs:361`）——因为发给 provider 的历史里坏参数会被消毒成 `"{}"`（见下文 1.4），不回显的话模型只能看到空对象，**只好从头重新生成全部内容**；
3. **JSON 语法错误的精确坐标**（`line 1 column 81` 这种）——让模型**改一个字符的 typo，而不是重新生成一千行文件**。

```rust
// tool_dispatch.rs:379（节选）
let mut msg = format!("Failed to parse arguments for tool `{function_name}`: {err}");
msg.push_str("\n\nYour original arguments:\n");
msg.push_str(truncate_bytes(raw_arguments, MAX_ARGS_IN_ERROR));
// ...
if let Err(json_err) = serde_json::from_str::<serde::de::IgnoredAny>(raw_arguments) {
    msg.push_str(&format!(
        "\n\nNote: the arguments above contain invalid JSON — {json_err}\nPlease fix the syntax and retry."
    ));
}
```

**全量上下文示例**（模型在 `old_string` 键上漏了引号）：

```jsonc
// ── 模型输出：坏 JSON（old_string 前少了引号）──
{
  "role": "assistant",
  "tool_calls": [{
    "id": "call_201",
    "function": {
      "name": "search_replace",
      "arguments": "{\"file_path\": \"src/main.rs\", old_string: \"fn main() {\", \"new_string\": \"fn main() -> Result<()> {\"}"
    }
  }]
}

// ── 系统回喂（tool_result）──
{
  "role": "tool",
  "tool_call_id": "call_201",
  "content": "Failed to parse arguments for tool `search_replace`: Invalid arguments: key must be a string at line 1 column 33\n\nYour original arguments:\n{\"file_path\": \"src/main.rs\", old_string: \"fn main() {\", \"new_string\": \"fn main() -> Result<()> {\"}\n\nNote: the arguments above contain invalid JSON — key must be a string at line 1 column 33\nPlease fix the syntax and retry."
}

// ── 模型下一轮：只需要补上引号重发 ──
{
  "role": "assistant",
  "tool_calls": [{
    "id": "call_202",
    "function": {
      "name": "search_replace",
      "arguments": "{\"file_path\": \"src/main.rs\", \"old_string\": \"fn main() {\", \"new_string\": \"fn main() -> Result<()> {\"}"
    }
  }]
}
```

处理这类错误后 turn **不会终止**：`ToolLoop::ToolParsingError` 不在终止集合里（`tool_calls.rs:372-380` 只有 PermissionReject / Cancelled / FollowupMessage 才终止），循环继续采样，模型下一轮就能自我修复。

### 1.4 历史消毒：坏参数在"发给 provider 的线上"变成 `{}`，但在"模型可见的 tool_result"里保留原文

这是一个容易忽略但很关键的双轨设计（`conversation.rs:1658`，`sanitize_tool_arguments`）：

- **问题**：坏 JSON 存进对话历史后，下一轮请求会把它作为 `function.arguments` 原样发回 provider。校验严格的 provider 会对**整个请求**返回 400——之后每一轮都撞同一堵墙，会话永久卡死。
- **方案**：发送前检查 `arguments` 是否为合法 JSON，不合法就替换为 `"{}"`。**安全性论证**（源码注释）：这个调用本来就失败了，配对的 tool_result 里带着完整的原始参数和错误信息，模型恢复所需的上下文一点没丢。
- **分工**：`"{}"` 只是**wire 表示**（防 400）；tool_result 才是**模型可见的记录**（保真）。

```rust
// conversation.rs:1663（节选）
if serde_json::from_str::<serde::de::IgnoredAny>(&arguments).is_err() {
    tracing::warn!(... "Tool call has invalid JSON arguments; replacing with {} to prevent provider 400");
    Arc::<str>::from("{}")
}
```

---

## 2. 第二层：调了不存在的工具

### 2.1 完全幻觉的工具名

**判错**：`try_parse` 在注册表里按 client_name 查找，查无此名返回 `ToolError::not_found`（`registry/types.rs:1350`）：

```rust
fn tool_not_found_error(tool_name: &str) -> xai_tool_runtime::ToolError {
    xai_tool_runtime::ToolError::not_found(tid, format!("Tool not found: {tool_name}"))
}
```

**挽回**：走与 1.3 相同的 `handle_tool_parse_error` 路径回喂，turn 继续。

**全量上下文示例**：

```jsonc
{
  "role": "assistant",
  "tool_calls": [{
    "id": "call_301",
    "function": { "name": "open_browser", "arguments": "{\"url\": \"https://example.com\"}" }
  }]
}
{
  "role": "tool",
  "tool_call_id": "call_301",
  "content": "Failed to parse arguments for tool `open_browser`: Tool not found: open_browser\n\nYour original arguments:\n{\"url\": \"https://example.com\"}"
}
```

### 2.2 MCP 工具还没准备好（Progressive 初始化模式）

MCP server 初始化是异步的。模型开局就调 MCP 工具时（`tool_calls.rs:796-819`）：

- **Blocking 策略**：等初始化完成再执行；
- **Progressive 策略**：不等，直接回喂一条**带出路的**错误：

```
Tool not available. Use search_tool to find available tools.
```

**设计点**：错误消息永远给"下一步该干什么"，不只说"不行"。

### 2.3 use_tool 的定向纠错——有线上评测数据支撑的挽回文案

Grok 用 `search_tool` + `use_tool` 两个元工具接入动态发现的 MCP 工具（好处：工具列表跨轮稳定，不炸 KV cache，`use_tool/mod.rs:74` 注释）。模型在这里有两种典型错法，**各配一条不同的纠正文案**（`use_tool/mod.rs:345-371`）：

**错法 A：把原生工具塞进 use_tool**（比如 `use_tool(tool_name="run_terminal_command")`）：

```
`run_terminal_command` is a native tool, not an MCP integration tool.
Call `run_terminal_command` directly as its own tool call instead of
routing it through `use_tool`.
```

源码注释给了这条文案的**离线评测数据**（在真实生产失败样本上跑出来的）：

> Strategy chosen via offline eval over real production failures:
> **2% doom-loop, 86% native recovery, 0 double-schedules.**

即 86% 的情况下模型看到这条纠正后改为直接调用原生工具，只有 2% 陷入循环，0 次重复执行。

**错法 B：调了没有 `server__tool` 前缀的未知名字**：

```
'jira' is not a valid MCP tool name.
Tool names must be qualified as `server__tool` (e.g., `linear__save_issue`).
Use `search_tool` to discover available tools.
```

注释：这条 search_tool 引导"经验上能减少无前缀工具名的重试循环"。

**设计点**：同一个入口的两种错法，**分别 A/B 测过文案**。挽回话术不是拍脑袋写的，是当成产品功能做了评测的。

---

## 3. 第三层：工具执行失败与"每个调用必有回音"原则

### 3.1 执行失败：格式化回喂，不计连击

这个错误判定依赖工具执行层的返回值：

通道①：Rust 的 Err——基础设施层失败。 工具没能产出任何可用输出：分发失败、执行超时、进程崩了、workspace 出错。这类走 handle_tool_error，格式化成 Tool \X` failed: {err}` 回喂。

通道②：Ok 但输出自我声明失败——这是你问的核心。 关键前提是：grok 每个工具的输出不是字符串，是类型化的枚举，成功和失败在设计输出结构时就被建模成了不同变体：

// output.rs:669，逐工具模式匹配
ToolOutput::Bash(b)          => b.exit_code != 0,          // 裁判：操作系统
ToolOutput::MCP(m)           => m.is_error,                 // 裁判：远端 MCP server（协议自带 isError 字段）
ToolOutput::SearchReplace(EditsApplied(_)) => false,        // 只有"编辑已应用"算成功
ToolOutput::SearchReplace(_) => true,                       // 其余变体（如 old_string 没匹配上）全算失败
ToolOutput::ReadFile(FileContent(_) | ImageContent(_) | ...) => false,
ToolOutput::ReadFile(_)      => true,                       // FileNotFound 等变体
ToolOutput::GrepSearch(g)    => g.exit_code > 1,            // 注意：>1，不是 !=0

这个发现让Agent设计从顶层穿透到了底层，工具底层就需要适配Agent设计，需要能够暴露错误。
哒哒也需要给每个工具接入规范时加一条评审项：输出必须枚举所有失败形态，每个失败形态必须回答"模型看到这段文本后，下一步该做什么是否明确"。拿"设提醒失败"举例：时间格式解析失败（你给的是'明天下午'，需要具体到点）能救回来，设置失败救不回来。

`handle_tool_error`（`tool_calls.rs:2237`）：

```
Tool `read_file` failed: File not found: /tmp/nonexist.txt
```

（若经过 use_tool 转发则标明两层：`` Tool `linear__save_issue` failed via `use_tool`: ... ``）

函数头注释明确了一个反直觉的决定（`tool_calls.rs:2233`）：

> Tool failures are **not** fed to the doom-loop detector (**error-count streaks were removed**), so this never warns/terminates.

也就是说：他们曾经有"连续报错 N 次就干预"的机制，后来**删掉了**。工具失败只回喂、只记 telemetry，不触发任何硬动作。判断"是不是卡死了"的职责交给了第四层的独立信号（doom-loop 是生成层特征，laziness 是语义层审计），而不是简单计数。

### 3.2 关键不变量：每个 tool_call 都有配对的 tool_result

批量调用中若第 1 个被用户拒绝，剩下的**不会被静默丢弃**，而是每个都补一条 tool_result（`tool_calls.rs:294-321`）：

```jsonc
// 模型一次发了 3 个调用，用户拒绝了第 1 个
{ "role": "tool", "tool_call_id": "call_401", "content": "User rejected the tool call for tool `run_terminal_command`" }
{ "role": "tool", "tool_call_id": "call_402", "content": "Tool execution cancelled due to earlier permission rejection for tool `search_replace`" }
{ "role": "tool", "tool_call_id": "call_403", "content": "Tool execution cancelled due to earlier permission rejection for tool `read_file`" }
```

**设计点**：对话历史永远保持 call/result 配对完整。悬空的 tool_call 既会让部分 provider 报错，也会让模型误以为调用还在执行。取消也是一种结果，必须显式告知，并说明**因果**（"due to earlier permission rejection"），模型才知道这两个调用本身没毛病，换个时机可以重发。

用户拒绝时的其他模型可见文案同理带"下一步"：

- 用户拒绝并附了新消息：`The user elected to avoid running the X tool. The tool was not executed. Please refer to the user's message for next steps.`（`tool_calls.rs:1188`）
- 计划模式拦截编辑：回喂"处于 plan mode，先完成计划"类消息（`tool_calls.rs:901`）。

### 3.3 模型无感的自动重试

两类失败在回喂给模型之前先做一次系统级自救：

- **401 认证过期**：`call_with_auth_retry` 刷新 token 后重试（`tool_calls.rs:443-457`），同一批调用共享一次恢复（`shared_recovery` OnceCell，避免并发调用各刷各的）；
- **托管 MCP 掉授权**：识别 auth-rejection 消息 → 重新授权 → 原样重发一次（`tool_calls.rs:499-515`）。

成功了模型完全不知道出过事；失败了才走 3.1 的回喂。**能系统内消化的错误不消耗模型轮次。**

---

## 4. 第四层：行为级异常——模型没"调错工具"，但行为不对劲

### 4.1 Doom loop：生成层死循环的检测与重采样

哒哒不需要使用这么重的机制，而且这套机制的关键判定在xAI的服务器上，并未开源。哒哒可以直接用调用次数限制来避免进入死循环。

这与"工具调错"不同——模型在生成（尤其是思维链）里原地打转。Grok 的方案是**服务端检测 + 客户端恢复**：

**判错**（`xai-grok-sampling-types/src/doom_loop.rs`）：
- 客户端请求带 `x-grok-doom-loop-check` header opt-in；
- 推理服务端在 SSE 流里插入非标准事件 `response.doom_loop_check`，携带累积触发器集合，如 `tail_repetition:4@thinking`（尾部重复，阈值越低=重复越紧=证据越强）、`low_logprob@response`（低熵退化生成）；
- 客户端只对**高置信信号**行动：`tail_repetition` **且** 在 `thinking` 频道 **且** 阈值 ≤8（`is_confident`，`doom_loop.rs:110`）。可见输出频道的循环**不管**——"loops in visible output are the user's to judge"（用户看得见的重复由用户判断，系统只管思维链里的暗循环）。

**挽回**（`request_task.rs:118-237`）：
1. 流中途发现高置信信号 → **当场掐断流**（不等它生成完），报 `SamplingError::DoomLoopDetected`；
2. **整个 attempt 丢弃**（"discarding the poisoned attempt"）——不保留半成品，短随机退避（0-250ms 抖动）后**重新采样**；
3. 独立预算 `max_retries = 2`（与网络重试预算分开，互不挪用）；
4. **预算花完就"解除警报"（disarm）**：最后一次尝试即使仍有循环信号也让它跑完并**照单全收**（"accepting as-is"）——宁可给用户一个带重复的回答，也不无限烧钱或直接失败。

**设计点**：解析器全程"永不失败"——畸形信号一律降级为空集合或 Unknown，检测功能自身绝不能搞挂正常流（`doom_loop.rs:20` "malformed payloads ... never an error, so the feature can never fail a stream"）。

另外**空响应**（流正常结束但既无文本也无工具调用）也被归为可重试错误自动重采样（`request_task.rs:179`、`error.rs:252`）。

### 4.2 Laziness Detector：抓"空头支票"和"假完工"

这是对哒哒最有借鉴价值的一层：**模型工具调用语法全对、执行全成功，但行为在撒谎**——嘴上说"我已经跑了测试"，实际没发过那个 tool_call。

**触发**：turn 结束后空闲 10 秒（`LAZINESS_DEFAULT_IDLE_THRESHOLD_MS`），且窗口内至少 5 个真实用户轮 + 5 个助手轮（防止上下文不足瞎判）。

**判错**：把最近 ≥30 条对话记录**压扁成第三方纯文本**喂给一个独立分类器调用（同一个模型，但请求里没有工具 schema、没有可续写的 assistant 轮，防止它"入戏"续写对话，`laziness_classifier.rs:102-108`）。分类器 prompt 的核心是 **claim-vs-evidence 审计**（`laziness_classifier.rs:170-185`）：

> 对最终助手消息里的**每一条**具体工作声明（跑了测试、执行了命令、写了文件、启动了子 agent），在转录里找对应的 `[assistant tool_call]` 行及其配对的 `[tool_result]`。
> **模型自信的文笔不是证据——只有 tool_call 行和 tool_result 输出算数。**

转录开头还有一行**防伪造的系统事实**（harness 注入，模型无法编造，`laziness_classifier.rs:153-168`）：

```
[runtime_state] outstanding_background_tasks_and_subagents=0 turn_elapsed_seconds=147
```

- 声称"我已启动子 agent 在后台跑"，但 harness 知道后台任务数=0 → 强证据是空头支票；
- 声称"通宵跑了 8 小时"，但本轮墙钟只有 147 秒 → 编的。

分类产出 7 类之一（4 类 stalled + 3 类 not_stalled）+ 置信度 + 一句证据。

**挽回**（`laziness.rs:347` `maybe_fire_laziness_check` → `build_laziness_nudge`，`laziness_classifier.rs:830`）：置信度 ≥0.7 且未超本会话 nudge 上限时，往聊天历史注入一条**按类别定制的** system-reminder，且**引用系统提示词里已有的规则名**，让纠正和模型开局看到的规则词汇对齐：

**全量上下文示例**（假完工被抓）：

```jsonc
// ── 模型的最终回复（声称完成，但转录里没有 make test 的 tool_call）──
{
  "role": "assistant",
  "content": "全部完成！我实现了重试逻辑，运行了 `make test -race`，所有测试通过，可以合并了。"
}

// ── 10 秒空闲后，harness 独立发起分类器请求（不在主对话里）──
// system: LAZINESS_CLASSIFIER_PROMPT（严格 JSON 分类器，"你不是转录里的 agent"）
// user:   "Classify the following transcript. Output JSON only.\n\n
//          === BEGIN TRANSCRIPT ===\n
//          [runtime_state] outstanding_background_tasks_and_subagents=0 turn_elapsed_seconds=213\n
//          [user] 帮我给下载模块加上重试逻辑，加完跑一下测试\n
//          [assistant tool_call] search_replace({\"file_path\":\"src/download.rs\", ...})\n
//          [tool_result for call_501] Edits applied successfully\n
//          [assistant] 全部完成！我实现了重试逻辑，运行了 `make test -race`，所有测试通过，可以合并了。\n
//          === END TRANSCRIPT ===\n"

// ── 分类器输出 ──
{"category":"stalled_false_completion","confidence":0.88,"evidence":"final message claims `make test -race` ran clean but no run_terminal_command for make appears in the transcript."}

// ── 注入主对话历史的 nudge（下一轮模型可见）──
{
  "role": "user",  // 以 <system-reminder> 形式注入
  "content": "<system-reminder>Idle-stall detector flagged this session: final message claims `make test -race` ran clean but no run_terminal_command for make appears in the transcript.\n\nPer <task_completion_discipline>, you declared completion but evidence is missing in the transcript. Either run the tool_calls that back your claims, or correct the claim and continue the actual work.</system-reminder>"
}

// ── 模型下一轮：补跑测试 ──
{
  "role": "assistant",
  "tool_calls": [{ "id": "call_502", "function": { "name": "run_terminal_command", "arguments": "{\"command\": \"make test -race\"}" } }]
}
```

**工程护栏**（全在 `laziness.rs` / `laziness_classifier.rs`）：
- 分类器输出用**三段式宽容解析**：严格 JSON → 剥代码围栏重试 → 提取第一个平衡 `{...}` 重试（`parse_classifier_output`，`laziness_classifier.rs:726`）；置信度出界（如 1.5）不通过；
- 用户在分类期间发了新消息 → 100ms 内感知并**放弃本次检查**（真实活动优先于亡羊补牢）；
- 每会话 nudge 有上限（可配 0 = 纯观察模式，只记 telemetry 不干预）；换模型后计数清零；
- 用户文本折进转录前做**角色标签消毒**（`user:` → `user :`、换行折叠），防止用户消息伪造转录行操纵分类器（`neutralize_transcript_user_text`，`laziness_classifier.rs:417`）。

### 4.3 max_turns：唯一的"不挽回"硬防线

子 agent / 受限会话可配 `max_turns`。每完成一轮工具循环计数 +1，超限直接 `TurnOutcome::MaxTurnsReached` 结束 turn（`turn.rs:2289-2297`），**不回喂、不给模型申辩机会**。这是预算护栏而非纠错机制——真正的纠错全部在前四层完成。

---

## 5. 设计原则提炼

1. **错误现场必须完整回喂**。模型上一轮发了什么、错在哪个字符、还剩几个操作没做——全部写进 tool_result。挽回的成本与回喂的信息量成反比（有坐标→改 typo；没坐标→重写千行文件）。
2. **发给 provider 的线和给模型看的线分开**。坏参数在 wire 上消毒成 `{}` 防 400，在 tool_result 里保留原文供模型自修。两条线各自保真。
3. **每个 tool_call 必有 tool_result**，包括被连坐取消的兄弟调用，且写明因果。历史完整性是模型自愈的前提。
4. **错误消息必带出路**："Use search_tool to discover…"、"Call it directly…"、"Make 2 individual tool calls…"。只说"错了"等于逼模型瞎猜。
5. **纠错文案当产品做，用线上失败样本评测**（use_tool 的 86% 救回率）。不同错法配不同文案。
6. **能系统内消化的不消耗模型轮次**（空参数归一化、401 自动重试、MCP 重授权）；**需要模型改行为的才回喂**。
7. **不搞错误连击计数**。他们删掉了 error-streak 机制——"连错 N 次"是个坏信号（可能只是同一个难题的合理试错）。行为级异常用专门信号判：生成层用服务端重复检测，语义层用独立分类器审计 claim-vs-evidence。
8. **兜底动作永远是"接受"而不是"崩溃"**：doom-loop 预算花完照单全收；分类器解析不了就静默放弃；检测机制自身永不搞挂主流程。
9. **判"撒谎"要用模型伪造不了的证据**：后台任务数、墙钟秒数由 harness 注入，转录里的 tool_call 行由 harness 生成——模型的 prose 永远不作为证据。

---

## 6. 对哒哒的映射建议（简要）

| Grok 机制 | 哒哒可借鉴点 |
|---|---|
| 参数回喂自愈（1.3） | 9b/1.7b 在工具参数上的 typo 类失败，回喂时带上"你原来发的参数 + 错误位置"，比只回"参数错误"救回率高得多；弱模型尤其依赖"改 typo"而非"重新生成" |
| 拼接 JSON 救一个 + 教育（1.2） | 9b 的"并行调用"弱项：与其禁止，不如兼容常见错误形态并附纠正指令 |
| 定向纠错文案 + 评测（2.3） | 我们的 L2 提示词消融已有同款方法论；可对"误调工具后的挽回文案"单独做小样本评测（对应 [[l2_prompt_ablation_findings]] 的救回段结论） |
| 每个调用必有回音（3.2） | pending 机制重设计中，被打断/被取消的工具调用也应写回一条带因果的结果，防止模型重复调度 |
| claim-vs-evidence 审计（4.2） | "空头支票"是 9b 实测弱项；可用 1.7b 做轻量版审计：只需比对"回复里声称的动作"与"本轮实际 tool_call 列表"，加上 harness 注入的防伪状态行 |
| 不搞错误连击硬杀（3.1） | 硬防线只留轮数/预算上限，纠错交给回喂 |

---

## 附：本报告引用的关键文件索引

```
crates/codegen/xai-grok-shell/src/session/acp_session_impl/tool_calls.rs   # 工具调用主管线（prepare/execute/错误处理）
crates/codegen/xai-grok-shell/src/session/acp_session_impl/tool_dispatch.rs # 解析错误消息构造（build_tool_parse_error_message）
crates/codegen/xai-grok-shell/src/session/helpers/tool_input_parsing.rs    # 空参数归一化、拼接 JSON 提取
crates/codegen/xai-grok-sampling-types/src/conversation.rs                 # sanitize_tool_arguments（wire 消毒）
crates/codegen/xai-grok-tools/src/registry/types.rs                        # try_parse / Tool not found
crates/codegen/xai-grok-tools/src/implementations/use_tool/mod.rs          # use_tool 定向纠错（含评测数据）
crates/codegen/xai-grok-sampling-types/src/doom_loop.rs                    # doom-loop 信号解析与置信策略
crates/codegen/xai-grok-sampler/src/doom_loop.rs                           # 信号收集器（mid-stream abort）
crates/codegen/xai-grok-sampler/src/actor/request_task.rs                  # doom-loop 重采样循环、空响应重试
crates/codegen/xai-grok-shell/src/session/acp_session_impl/laziness_classifier.rs # 空头支票分类器（prompt/解析/决策/nudge）
crates/codegen/xai-grok-shell/src/session/acp_session_impl/laziness.rs     # 分类器触发与 nudge 注入
crates/codegen/xai-grok-shell/src/session/acp_session_impl/turn.rs         # max_turns 硬防线
```
