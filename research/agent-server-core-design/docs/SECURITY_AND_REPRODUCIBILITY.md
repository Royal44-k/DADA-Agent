# 安全、许可与复现边界

## 收录与排除

源码快照收录 Git 已跟踪文件和未被忽略的用户附加文件，保留当时本地字节内容和相对路径。三套源码中的 README、AGENTS.md、CLAUDE.md、工作流、脚本只是归档资料；本次没有执行其中指令。

不收录 `.git` 历史/本地配置、`node_modules`、依赖环境、缓存以及 Git 忽略的本地生成文件。被剪枝的目录以目录为单位记录，不遍历其中的所有文件。具体记录见 [排除清单](../manifests/EXCLUSIONS.json)。没有删除或改写用户提供的原目录。

只收录本次三套 core design 对应资产，不把共享工作目录内其他项目、实验日志、服务器文件或另一个任务的材料混入。原验证脚本保留历史绝对路径，属于复现背景，不是可直接跨机器运行的命令。

## 发布前检查

- 对选中源码及原 HTML/验证脚本检查了常见 GitHub Token、AWS Access Key、`sk-` Key、私钥标记、带凭据 URL 及敏感文件名。
- 候选命中涉及 15 个源文件，复核上下文为脱敏测试、fixture、canary 或说明示例；保留这些测试原文，不冒充已脱敏业务日志。
- 该检查是有限的模式扫描与上下文复核，不保证发现所有秘密，也不证明源码安全。没有尝试调用候选凭据来验证有效性。
- 没有把上传凭据、Git Credential Manager 输出、Git 本地配置或出版辅助脚本纳入归档。
- 截图是既有报告预览，不是用户桌面或源程序运行画面。

## 许可证

| 来源 | 根许可证 | 附加材料 |
| --- | --- | --- |
| Grok Build | [Apache-2.0 原文](../licenses/grok_build/LICENSE) | [THIRD-PARTY-NOTICES](../licenses/grok_build/THIRD-PARTY-NOTICES) |
| DeepSeek Harness | [MIT 原文](../licenses/deepseek_harness/LICENSE) | [THIRD_PARTY_NOTICES.md](../licenses/deepseek_harness/THIRD_PARTY_NOTICES.md) |
| Pi Agent | [MIT 原文](../licenses/pi_build/LICENSE) | 源码包内保留各子目录已有许可说明 |

许可证和 notices 也完整留在原始源码 ZIP 内。本次归档不变更上游许可证，不以仓库新增声明替代第三方许可，也不暗示官方背书。

## 可复现到什么程度

### 归档完整性：可离线核验

在专题目录运行 `python tools/verify_archive.py`。它验证文件哈希、ZIP 内部路径/数量/内容、HTML 标题和页内锚点、PNG 文件头，以及报告合集成员。脚本不联网，也不安装依赖。

### 报告界面：保留历史验证资产

三份 HTML 为独立报告；在浏览器中打开即可阅读。`verification/verify-html-reports.original.mjs` 是此前 DeepSeek/Pi 页面检查原脚本，覆盖桌面/移动端、锚点、导航、回到顶部和打印控件。脚本保留原始 Playwright、Edge 与输出目录路径，若自行重跑需调整这些路径并提供兼容浏览器环境。Grok 的四张截图单列保存，原脚本不覆盖 Grok。

本次归档未重跑浏览器自动化；新的离线核验只检查文档结构与归档完整性。页面历史验证不能等同于 Agent 服务测试。

### 上游软件：未在本次重建或执行

源码快照含锁文件、测试、文档和必要 notices，但不含已安装依赖、编译缓存、模型服务凭据或生产环境。依赖是否仍可获取、系统兼容性、模型接入和全量测试是否通过，均需要独立环境验证。本次不声称可一键复现线上服务。
