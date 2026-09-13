# 最终测试集：1300 条、a–m 十三分支

[下载测试集-1300.zip](../downloads/测试集-1300.zip) · [在线查看 JSONL](../datasets/corrected-v3-1300/) · [返回会话资产总览](SESSION_ASSETS.md)

此版本是 2026-08-20 最终修订的 v3。ZIP 解压后的顶层文件夹名为 `测试集-1300`，只包含 `a.jsonl` 至 `m.jsonl`，不会混入说明文件。各文件按修订后的 `label` 分组；改标后每类数量不再恰好为 100。

| 分支 | a | b | c | d | e | f | g | h | i | j | k | l | m | 总数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 条数 | 113 | 111 | 98 | 101 | 89 | 110 | 101 | 102 | 101 | 84 | 101 | 87 | 102 | 1300 |

编码为 UTF-8，每行一个 JSON 对象，字段及顺序与当时参考的 raw 格式一致：

```text
label, rounds, ctx, hard_pair, history, text, asr_noise, src
```

`label` 为标准答案；`history` 保留历史对话，`text` 为当前输入。`rounds`、`ctx`、`hard_pair`、`asr_noise`、`src` 保留源语料的轮次、上下文、易混淆对、ASR 标记和来源信息。使用时需要连同上下文读取，尤其不能只抽出当前短句来评估多轮意图。

导出没有重新改写这些字段，也没有把 `sample_id` 等审计字段混入 raw 兼容文件。需要逐条 ID 和修订追溯时，使用[带元数据的 v3 合并文件](../experiments/2026-08-20-dada-1300-stateful-retest/sample-1300-corrected-v3-2026-08-20.jsonl)。该文件 SHA-256：

```text
b083e97e0829955bcaa588773f28feaf62350e481285d5d24e6d278e76abf75c
```

最终语料包与当前工作区 `测试集-1300` 逐字节一致，同时按最终标签与 v3 源文件逐条比较八字段及分支内顺序。它不是最初 raw 的全量备份，也没有仅因重新打包而新增模型实测记录。98.69% 的数字属于复用 v2 输出的标签重算，具体见[结果口径](RESULTS_AND_CAVEATS.md)。

有状态路由测试需准备对应的 task 和 memory 内容，否则空表门控会改变 b/c/e 的分支可达性。数据状态设置参考[8月20日实验目录](../experiments/2026-08-20-dada-1300-stateful-retest/)，执行条件参考[复现说明](REPRODUCIBILITY.md)。
