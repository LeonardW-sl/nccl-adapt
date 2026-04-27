# Evidence Index

本 change 只保留证据摘要索引；原始日志、环境快照和 debug 输出统一存放在 `nccl/plugins/adaptive/experiments/`。

## 对应实验问题

- 2-rank debug：
  - `nccl/plugins/adaptive/experiments/cross-rank-coordination/2026-04-26-2rank-debug`
  - `nccl/plugins/adaptive/experiments/cross-rank-coordination/2026-04-26-2rank-debug2`
- communicator-domain 修复后矩阵：
  - `nccl/plugins/adaptive/experiments/cross-rank-coordination/2026-04-26-shared-policy-fixed-matrix`
- 8-rank 一致性验证：
  - `nccl/plugins/adaptive/experiments/cross-rank-coordination/2026-04-26-8rank-initial-matrix`
  - `nccl/plugins/adaptive/experiments/cross-rank-coordination/2026-04-26-8rank-consistency-validation`
- 回归轨迹：
  - `nccl/plugins/adaptive/experiments/cross-rank-coordination/2026-04-26-rerun-regression-trace`

## 摘要结论

- `final-steady` 的 2-rank warmup 后切换已不再触发 `SIGSEGV`。
- `final-steady` 与 `weak-online` 的 8-rank torch smoke 已验证 communicator 内 policy 激活一致。
- 当前 cross-rank 发布路径以 rank0 representative 聚合和显式 `effective_call_index` 激活边界为核心约束。
