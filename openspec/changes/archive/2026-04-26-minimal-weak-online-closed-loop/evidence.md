# Evidence Index

本 change 只保留证据摘要索引；原始日志、环境快照和对照输出统一存放在 `nccl/plugins/adaptive/experiments/`。

## 对应实验问题

- 模式对照：
  - `nccl/plugins/adaptive/experiments/mode-comparison/2026-04-25-initial-single-node-matrix`
  - `nccl/plugins/adaptive/experiments/mode-comparison/2026-04-26-single-node-refresh`
- 开销量化：
  - `nccl/plugins/adaptive/experiments/overhead/2026-04-26-rerun-compare-short`
  - `nccl/plugins/adaptive/experiments/overhead/2026-04-26-rerun-compare-long64`
  - `nccl/plugins/adaptive/experiments/overhead/2026-04-26-cross-rank-short-smoke`
- size bucket honesty：
  - `nccl/plugins/adaptive/experiments/bucket-honesty/2026-04-26-5mb-vs-7mb`

## 摘要结论

- `weak-online` 最小闭环已恢复为可运行、可量化模式。
- 当前单机 8-rank 长跑复测中，开销排序为 `baseline < profiler-only < final-steady < weak-online`。
- `4-8 MiB` 共享 bucket 在 `5 MiB` 与 `7 MiB` 上连续出现不同 committed candidate，说明该 bucket 还不够 honest。
