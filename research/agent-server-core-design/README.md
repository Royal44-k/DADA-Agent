# Agent Server Core Design · 三套架构研究资产

本专题归档用户提供的 **Grok Build、DeepSeek Harness、Pi Agent** 三套源码材料，以及本次分析形成的 HTML 报告、预览图和验证资产。分析日期为 **2026-08-19**，归档日期为 **2026-09-13**；归档没有重新研究上游最新版本，也没有运行模型服务或上游测试套件。

## 先读报告

| 项目 | 报告 | 核心设计主线 | 原始源码快照 |
| --- | --- | --- | --- |
| Grok Build | [HTML 分析报告](reports/grok-core-design-analysis.html) | Actor 状态所有权、连接与会话解耦、流式采样、工具事务与权限边界 | [下载 grok_build.zip](sources/grok_build.zip) |
| DeepSeek Harness | [HTML 分析报告](reports/deepseek-harness-core-design-analysis.html) | Cordis 可逆插件树、模型可见日志、请求重建、能力组合与受控工具执行 | [下载 deepseek_harness.zip](sources/deepseek_harness.zip) |
| Pi Agent | [HTML 分析报告](reports/pi-agent-core-design-analysis.html) | 精简 Agent 循环、请求边界修复、JSONL 会话树、产品层恢复与扩展 | [下载 pi_build.zip](sources/pi_build.zip) |

GitHub 文件页展示 HTML 源码，不直接渲染网页。下载单份 HTML 后可用浏览器打开；也可下载 [报告与预览图合集](downloads/reports-and-previews.zip) 后离线阅读。三份报告保持原始字节内容，截图同样保留原样。

## 阅读导航

- [三套架构对照与业务处理摘要](docs/COMPARISON.md)
- [来源、版本、文件数量与归档规则](docs/PROVENANCE.md)
- [安全、许可证与复现边界](docs/SECURITY_AND_REPRODUCIBILITY.md)
- [资产目录](CATALOG.md)
- [预览图目录](previews/README.md)
- [原始中文调研笔记](source-notes/README.md)
- [文件级归档清单](ASSET_MANIFEST.json) · [SHA-256 校验表](SHA256SUMS.txt)

## 目录结构

```text
reports/            3 份原始 HTML 分析报告
previews/           12 张桌面/移动端截图
sources/            3 个源码 ZIP，内部保留完整相对路径
source-notes/       从源目录单独提取的 2 份中文调研笔记
licenses/           上游 LICENSE / THIRD-PARTY-NOTICES 原文副本
manifests/          每个源码文件的大小、SHA-256、Git 跟踪标识；排除项
docs/               架构对照、来源说明、安全与复现说明
verification/       原始验证脚本（保留其历史环境路径）
tools/              可移植的离线归档完整性核验脚本
downloads/          三份报告及截图合集
```

## 完整性核验

在本专题目录下运行（Python 3.10+，仅使用标准库）：

```bash
python tools/verify_archive.py
```

脚本核对归档文件 SHA-256、三个源码 ZIP 的每个成员及其数量、报告标题/页内锚点、报告合集和 PNG 文件头。不执行源代码、插件、Agent 指令文件或模型请求，也不需要 API Key。此核验不等于功能测试或全面安全审计。

## 重要口径

1. 三套材料是本地提供的特定快照，不代表当前线上产品或官方最新版本。
2. Grok 的本地 Git 提交与 `SOURCE_REV` 指向的 monorepo 提交是两种不同标识，详见来源说明，不能相互替代。
3. Pi 报告区分当前 `AgentSession` 产品路径与演进中的 `AgentHarness`，不将迁移计划当成已上线能力。
4. 源码、测试和许可证原文保留；附带文档中的操作指令只是研究对象，不是本次归档任务指令。源码保存在 ZIP 中，避免把上游工作流或指令文件安装到本仓库根目录。
5. 现有 DADA 评测资产仍保留在仓库原目录；本专题没有改写既有实验结论。仓库根目录的历史清单与 ZIP 仍只描述其原有批次。
