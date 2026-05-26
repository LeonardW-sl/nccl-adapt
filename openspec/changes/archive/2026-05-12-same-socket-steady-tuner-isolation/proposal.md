## Why

`topology-controlled-experiment-matrix` 已经把问题缩到两个层面：

- `cross-8gpu` 的跨 socket 路径是真实环境变量，baseline 本身就更慢
- `weak-online` 的周期性 spike 会随 `NCCL_ADAPTIVE_RECHECK_AFTER` 移动，因此 recheck 是真实机制变量

但还有一个关键问题没有被单独回答：

在去掉 recheck 之后，`final-steady` 相比 `profiler-only` 的额外成本，到底是不是 steady tuner / coordinator 路径本身带来的，而且这种成本是否在 same-socket 条件下也成立。

当前最值得解释的现象不是 `cross-8gpu`，而是 same-socket 不对称：

- `numa0-4gpu`: `profiler-only 0.603 ms -> final-steady 1.031 ms`
- `numa1-4gpu`: `profiler-only 0.468 ms -> final-steady 0.486 ms`

这说明下一步不该再用 `cross-8gpu` 当主诊断样本，而应该在 same-socket 条件下隔离 steady tuner 成本，判断问题究竟来自：

- warmup sampling / publish / activate 前段污染
- steady tuner / shared coordinator 路径本身
- socket-local placement / affinity 差异

## What Changes

- 新增一个 same-socket steady-tuner isolation 实验 change，只比较 `numa0-4gpu` 与 `numa1-4gpu`
- 实验只运行 `profiler-only` 和 `final-steady`，不运行 `weak-online`
- 固定 workload、container、adaptive 参数与 topology-controlled 批次一致，只把测量窗口拉长，用于把 warmup / publish / activate 的前段成本与 steady 段分开
- 打开 coordinator / completion 诊断日志，用于判断 `final-steady` 的额外成本主要落在：
  - sampled warmup window
  - `wait-summary` / aggregate / publish
  - activate 之后的 steady active-candidate path
- 结果将直接回答：`profiler-only -> final-steady` 的跳变是否在 same-socket 下仍然稳定存在，以及 `numa0` / `numa1` 的差异是否可复现

## Non-Goals

- 不在本 change 中修改 adaptive policy 算法、candidate 集合、switch threshold 或 activation 机制
- 不在本 change 中继续分析 `cross-8gpu` 的跨 socket 放大效应
- 不在本 change 中重新打开 bucket honesty / sub-bucket refinement 方向
- 不在本 change 中实现新的 topology-aware key、bucket refinement 或 recheck 策略优化
- 不把本 change 扩展为性能修复；它首先是定位 steady tuner 成本来源的诊断 change

## Capabilities

### New Capabilities

- `same-socket-steady-tuner-isolation`: 定义一个只针对 same-socket placement 的 steady-tuner 隔离实验，用于区分 profiler 成本、steady tuner 成本以及 warmup/publish/activate 前段成本

## Impact

- 影响实验运行方式：需要一个只跑 `profiler-only` / `final-steady` 的 same-socket 诊断批次
- 影响实验结果分析：需要按 `numa0-4gpu` / `numa1-4gpu` 对比 steady-tuner jump，并结合 coordinator/completion trace 解读
- 影响后续方向判断：
  - 如果 same-socket 下 `final-steady` 仍显著高于 `profiler-only`，问题重点将转向 steady tuner / coordinator 路径
  - 如果长测后 jump 明显收敛，问题重点将转向 warmup / publish / activate 前段污染
  - 如果只有 `numa0-4gpu` 异常，问题重点将转向 same-socket placement / affinity / representative-rank 局部环境差异
