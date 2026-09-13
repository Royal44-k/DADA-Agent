# 复现与完整性

## 可直接做的离线核验

解压ZIP或克隆仓库后运行：

```bash
python tools/verify_archive.py
```

脚本使用Python标准库，不联网。检查132份源资产SHA-256、归档校验表、JSON/JSONL格式、Python语法、三轮原标签路由结果、8月20日初次/重试后结果、修订导出条数与音量/亮度日志统计。

原文件中的`artifact-hashes.sha256`等记录描述历史实验产物；本次归档有效校验清单以根目录`SHA256SUMS.txt`和`ASSET_MANIFEST.json`为准。ZIP自身校验值在`downloads/SHA256SUMS.txt`，也可使用PowerShell的`Get-FileHash -Algorithm SHA256`核对。

## 用保留的逐条结果重建汇总

在仓库根目录执行：

```bash
python experiments/2026-08-17-m1-1p7b-intent-eval/aggregate_full_router.py --input experiments/2026-08-17-m1-1p7b-intent-eval/results-m1-m3-rerun2-1300-20260818.jsonl --output /tmp/dada-summary-recomputed.json
```

Windows请将`--output`改为可写的临时路径。该命令只重算已有结果，不重新调用模型。

## 服务器重新测试需要的内容

- 相应历史版本的生产`dada`代码、提示词、M1门控和M3实现。
- 匹配的1.7B/9B模型服务、模型权重、上下文限制、解码参数和依赖环境。
- 对有状态评测，需相应数据库fixture和专用测试用户；先审阅fixture代码的写入范围。
- 8月20日评测依赖`full_router_probe_base.py`，该服务器独立副本当前未找到。仓库收录8月17日的`full_router_probe.py`供参考，但未经哈希比对，不能宣称两者相同。
- 某些历史脚本包含原工作区、生产目录或报告路径的绝对路径，需在隔离副本中适配。

`prod_eval_bootstrap.py`及入口脚本保留了将生产代码目录置前的处理，用于避免隔离评测器错误导入旧版M3。不要将普通`full_router_probe.py`的直接运行自动等同于加载了当时的生产版本。

本次资产核验不会导入生产`dada`包，不验证模型服务当前是否可用，也不把历史实验脚本的语法通过等同于服务器复测通过。

原流程图HTML使用diagrams.net的在线查看器脚本，查看该流程图需要网络；实验报告本身可作为本地HTML打开。历史HTML中的服务器路径和部分文件链接保留原样，归档内导航以README和CATALOG为准。
