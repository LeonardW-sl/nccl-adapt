## Why

`same-socket-steady-tuner-isolation` 已经把问题压到一个更清晰的边界：

- `numa1-4gpu` 的长窗口结果基本收敛：`profiler-only 0.440 ms -> final-steady 0.454 ms`
- `numa0-4gpu` 仍保留明显 post-activation gap：`profiler-only 0.598 ms -> final-steady post-activation 0.953 ms`
- 两侧都激活到相同 candidate：`ring/simple`
- `weak-online` recheck 已经被前一轮 change 单独隔离，不是这次 same-socket jump 的主因

这意味着下一步不该继续先追 `numa0` 异常，而应该先在更干净的 `numa1-4gpu` 上回答一个更基础的问题：

`final-steady` 的剩余成本到底是：

- profiler / completion 观察路径本身
- 固定 candidate 覆盖 NCCL 默认选择后的 candidate 效果
- 还是 dynamic coordinator / publish / activate / steady active-policy 机制本身

当前证据还缺一刀：没有同拓扑、同 workload、同长窗口条件下的 `static-replay` 对照，也没有把 `selectedAlgo` / `selectedProto` 暴露到结果契约里。因此现在还不能把 `final-steady - profiler-only` 直接解释为“steady 机制税”。

## What Changes

- 新增一个只针对 `numa1-4gpu` 的机制成本分解 change。
- 在相同 topology、相同容器、相同 workload、相同长窗口条件下比较：
  - `baseline`
  - `profiler-only`
  - `static-replay`
  - `final-steady`
- 将 `static-replay` 固定到 `numa1` 当前 learned candidate；若 rerun 学到不同 candidate，则显式对齐 static replay candidate 后再比较。
- 扩展结果契约，暴露 candidate 对齐情况，以及 plugin-enabled 运行里的 `selectedAlgo` / `selectedProto` / `nChannels`。
- 用 `final-steady post-activation` 对 `static-replay` 做残差比较，判断 dynamic 机制税是否已经足够小。
- 将 H100 验证定义为后续 gate：只有当 `numa1` 上的机制成本分解足够清晰时，才建议开 H100 follow-up change。

## Non-Goals

- 不在本 change 中解释 `numa0-4gpu` 为什么异常。
- 不在本 change 中继续跑 `cross-8gpu` 或 `weak-online`。
- 不在本 change 中修改 adaptive policy 算法、candidate 集合、switch threshold、activation lag 或 key 设计。
- 不在本 change 中直接执行 H100 验证；这里只定义是否“值得继续”的门槛。
- 不把 `final-steady - profiler-only` 直接当成机制税结论；本 change 的目标正是替换这种过粗解释。

## Capabilities

### New Capabilities

- `numa1-mechanism-cost-decomposition`: 定义一个只针对 `numa1-4gpu` 的 candidate-aligned 成本分解实验，用于区分 profiler 观察税、fixed-candidate 效果和 dynamic coordinator / activation 机制税。

## Impact

- 影响 `nccl/plugins/adaptive/run_torch_modes.sh` 或配套实验包装方式，用于支持 `numa1-4gpu` 上的 `baseline/profiler-only/static-replay/final-steady` 长窗口矩阵。
- 影响 `nccl/plugins/adaptive/adaptive_plugin.cc` 与 `analyze_experiment_results.py` 的观测契约，需要把 plugin-enabled 运行的 `selectedAlgo` / `selectedProto` / `nChannels` 和 candidate 对齐信息暴露出来。
- 影响 evidence 的解释方式：主要对比将从 `final-steady - profiler-only` 切换为 `final-steady post-activation - static-replay`。
- 影响是否开 H100 follow-up change：只有当 `numa1` 上的残差已经足够清晰，跨平台验证才有意义。
