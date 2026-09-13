# DADA-Agent · 技术验证与实验资产归档

本仓库整理哒哒 Agent 工作流程、M2 填参验证、音量/亮度调节、M1→M3 十三分支路由评测，以及后续语料标签审校资料。归档日期：**2026-09-13**。

收录 **132 份已有资产**，包括 **15 份 HTML、51 份 Python 文件、29 份 JSONL**，另有日志、补丁、汇总指标和审校文档。保留原有文件内容与实验目录结构，并通过 SHA-256 核验。归档操作没有重新调用模型或重跑服务器测试。

## Agent Server Core Design 专题

新增 [Grok / DeepSeek Harness / Pi Agent 架构研究归档](research/agent-server-core-design/README.md)：三套源码快照（11,223 个文件）、3 份 HTML 深度分析报告、12 张预览图、原始调研笔记、许可证及完整性核验。

- [三套架构对照与业务处理摘要](research/agent-server-core-design/docs/COMPARISON.md)
- [专题资产目录与源码下载](research/agent-server-core-design/CATALOG.md)
- [报告与预览图合集](research/agent-server-core-design/downloads/reports-and-previews.zip)

本专题独立归档。上方 132 份资产统计及下方历史清单、校验表和完整 ZIP 仍对应原有 DADA 技术验证批次，不包含本专题；专题有独立来源与 SHA-256 清单。既有实验结论保持不变。

## 下载与导航

- [本轮会话资产总览：主题、版本与最终语料](docs/SESSION_ASSETS.md)
- [本轮完整资产包（含最新整理说明）](downloads/Technique-DADA-assets-2026-09-13.zip)
- [最终测试集-1300.zip](downloads/测试集-1300.zip) · [格式与分支条数说明](docs/TESTSET_1300.md)
- [完整 ZIP 资产包](downloads/DADA-Agent-assets-2026-09-13.zip)
- [全部文件目录](CATALOG.md)
- [文件来源、字节数及 SHA-256](ASSET_MANIFEST.json)
- [完整性验证说明](docs/REPRODUCIBILITY.md)
- [口径修订与历史结论解释](docs/RESULTS_AND_CAVEATS.md)
- [M2 字段验证与 M3 改进讨论整理](docs/M2_M3_DESIGN_NOTES.md)
- [归档范围与缺失资料](docs/ARCHIVE_SCOPE.md)

GitHub 文件页默认展示 HTML 源码。下载 ZIP 后可直接用浏览器打开 HTML；也可在解压目录运行 `python -m http.server 8000`，访问 `http://localhost:8000/`。

## 建议阅读顺序

| 资料 | 内容 |
| --- | --- |
| [哒哒 Agent 流程图](reference/哒哒Agent流程图.html) | 原始技术底座与工作流程；流程图中“再见”的字母瑕疵应按 **l** 理解 |
| [音量/亮度三段式参数报告](experiments/2026-08-15-fg-typed-magnitude/M2-F分支音量亮度三段式参数-9B实测报告-2026-08-15.html) | 方向、幅度类型/数值、原文依据；152 例 × 3 轮，核心评测 455/456；另列模糊边界用例 |
| [8月18日 M3 复测报告](experiments/2026-08-17-m1-1p7b-intent-eval/哒哒Agent-M3再次完善后完整流程复测报告-2026-08-18.html) | 原始标签口径下 1191/1300，91.62%；须结合后续审校解释 |
| [109条失败样本标签审计](experiments/2026-08-17-m1-1p7b-intent-eval/raw语料库-109条失败样本标签审计与纠正-2026-08-19.md) | 73 条建议改标；复用既有输出可条件性重算为 97.00%，不是模型重测 |
| [8月20日有状态路由复测 v2](experiments/2026-08-20-dada-1300-stateful-retest/哒哒Agent-修订版1300条生产完整路由复测报告-v2-2026-08-20.html) | 修订语料、真实数据库状态；含 2 条基础设施失败各一次重试后的 1280/1300，98.46% |
| [修订版 v3 分支语料](datasets/corrected-v3-1300/) | a–m 共 13 个 JSONL、合计 1300 条；不是最初全量 raw 语料库 |

## 结果时间线：必须保留标签和重试口径

| 日期/版本 | 正确/总数 | 准确率 | 口径 |
| --- | ---: | ---: | --- |
| 2026-08-17 稳定基线 | 1172/1300 | 90.15% | 原始标签；M1→M3 最终路由 |
| 2026-08-18 首次新 M3 | 1028/1300 | 79.08% | 原始标签；245 条路由失败 |
| 2026-08-18 再次完善 | 1191/1300 | 91.62% | 原始标签；285 次 M3 成功返回 |
| 2026-08-19 标签审校重算 | 1261/1300 | 97.00% | 只审校原失败 109 条，假设其余标签正确；复用既有输出 |
| 2026-08-20 有状态首轮 | 1266/1300 | 97.38% | 修订语料与真实数据库状态 |
| 2026-08-20 v2 首次完整运行 | 1278/1300 | 98.31% | 尚未替换两条基础设施失败结果 |
| 2026-08-20 v2 重试后 | 1280/1300 | 98.46% | 两条基础设施失败各重试一次；普通分类错误未重试 |
| 2026-08-20 v3 标签重算 | 1283/1300 | 98.69% | 复用 v2 输出、仅改标签的条件性计算；没有 v3 模型重测 |

**这些数字不能直接解释为单次代码修改的准确率提升。** 标签、文本、状态设置和重试口径发生过变化。后续标签审计也意味着不能直接把原标签下的 74 条“M3 引错”全部解释为真实语义错误。原报告保留原样，补充解释见 [口径说明](docs/RESULTS_AND_CAVEATS.md)。

## 目录结构

```text
reference/                       原始流程图
docs/                            归档说明、讨论整理、历史评测计划
experiments/
  early-fg-isolation/             早期设备调节方案与隔离补丁
  2026-08-15-fg-typed-magnitude/   类型化幅度方案、日志与报告
  2026-08-17-m1-1p7b-intent-eval/  原始抽样、M1/M3结果、标签审计
  2026-08-20-dada-1300-stateful-retest/
                                 状态版复测、v2重试、v3标签审校
datasets/corrected-v3-1300/        修订语料a–m导出
tools/verify_archive.py           离线核验脚本
downloads/                       ZIP包及校验值
```

## 离线核验

```bash
python tools/verify_archive.py
```

验证归档文件哈希、JSON/JSONL 格式、Python 语法、核心实验计数和修订数据条数。核验不连接服务器，不执行实验脚本中的数据库操作。Python 3.10+ 可运行归档核验脚本。

本仓库是研究与评测资产，不包含完整生产 Agent、模型权重、服务器私钥或有效 API 凭据。原实验脚本仍依赖对应生产代码、模型服务和环境；服务器重跑的依赖缺口见 [复现说明](docs/REPRODUCIBILITY.md)。
