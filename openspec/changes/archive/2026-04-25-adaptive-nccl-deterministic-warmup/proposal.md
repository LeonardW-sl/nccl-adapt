## Why

NCCL 当前已有 profiler plugin 和 tuner plugin 的基础接口，但两者尚未形成闭环：profiler 可以观测通信性能，tuner 可以影响后续 collective 的算法、协议和 channel 选择。为了在一天内交付可对比实验，需要将目标收敛为“基于确定性 warmup schedule 的后续 collective 自适应调优”，避免引入跨 rank 动态决策不一致的风险。

## What Changes

- 新增一个 adaptive NCCL plugin 方案，使用同一动态库同时导出 profiler 与 tuner plugin symbol。
- profiler 侧采集 collective 类型、message size、sequence number、已选 algorithm/protocol/channels、执行时间和带宽指标。
- tuner 侧在 `getCollInfo` 中读取一致性的策略状态，修改 NCCL cost table 和可选 `nChannels`，影响后续 collective。
- 策略选择采用确定性 warmup schedule：所有 rank 按相同的 collective sequence 和 size-bin 试探候选策略，避免各 rank 独立切换。
- 性能统计用于记录、对比和最终选择；选择规则必须保证所有 rank 对同一 key 得到相同策略。
- 交付 baseline、profiler-only、static tuner、adaptive tuner 四组 allreduce 实验对比。
- 不修改 NCCL core 源码；实现范围限制在 `nccl/plugins` 及实验脚本/文档。

## Capabilities

### New Capabilities

- `adaptive-nccl-tuning`: 基于 NCCL profiler/tuner plugin 的确定性 warmup 自适应通信策略选择能力，覆盖监控、策略状态、候选试探、后续 collective 调优和实验对比。

### Modified Capabilities

无。

## Impact

- 影响 `nccl/plugins/profiler`、`nccl/plugins/tuner` 或新增组合 plugin 目录。
- 依赖 NCCL profiler API v5/v6 和 tuner API v5；首版以 tuner v5 为控制面，profiler v5 为稳妥观测面，可按目标 NCCL 版本导出 v6 fallback。
- 需要实验 wrapper 配置 `NCCL_PROFILER_PLUGIN`、`NCCL_TUNER_PLUGIN`、`NCCL_DEBUG` 和 benchmark 参数。
- 不改变 NCCL ABI、不改 `src/enqueue.cc` 等 core 文件。
