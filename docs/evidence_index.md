# 报告证据索引

| 报告项目 | 原始结果 | 解释 |
| --- | --- | --- |
| 图1 数值近似 | results/numerical_benchmarks.csv | 单次数值基准与MC标准误 |
| 图2 全场景风险 | results/simulation_metrics.csv | 252条含验证和测试，126条测试条件共享场景路径 |
| 图3 成本风险 | results/simulation_metrics.csv | S1测试，预算依据验证样本 |
| 图4 配对比较 | results/simulation_comparisons.csv | 21项比较，每项8192条配对路径，仅S1/5bps主要比较 |
| 图5 历史预测 | results/historical_forecasts.csv | 10752行含训练期拟合值，图中只取测试 |
| 图6 预测损失 | results/historical_summary.json | 每货币1281个测试目标 |
| 图7 块长敏感性 | results/historical_summary.json | 2000次移动块重采样，逐项区间 |
| 图8 历史对冲 | results/historical_episodes.csv | 4536个策略费用记录不等于4536独立样本，每货币测试60段 |
| 并行基准 | results/parallel_benchmark.json | 200万终端路径，100万独立反变量pair；三次重复只用于计时 |
| 示例账本 | results/simulation_ledger.csv 和 historical_ledger.csv | 逐事件记录不是额外独立路径 |
| 数据来源 | data/source_manifest.json | 官方源、加工说明、许可和内容hash |
| 软件验证 | results/validation.json 和 browser_validation.json | 本地软件测试与真实浏览器交互验证 |
| 交叉核验 | results/artifact_audit.json | 协议、CSV、JSON、SQL与账务一致性 |
| 能力并集 | docs/competency_union.json | 10项目18维，保留部分和外部证据 |

所有图由 `scripts/build_figures.py` 从正式结果生成。报告的统计数字来自相同冻结版本；改变实验后，应重新生成图表与报告并复核结论文字。图表和结论不能只更新其中一个。
