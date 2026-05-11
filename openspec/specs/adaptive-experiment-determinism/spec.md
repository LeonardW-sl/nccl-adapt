# adaptive-experiment-determinism Specification

## Purpose
Define a deterministic, interpretation-safe experiment protocol for evaluating adaptive NCCL behavior across correctness, mechanism cost, policy quality, and state-granularity studies.

## Requirements
### Requirement: Layered adaptive experiment protocol
系统 SHALL 将自适应 NCCL 实验拆分为机制正确性、机制成本、策略质量和状态颗粒度四类判别实验，并要求每类实验只为对应结论提供证据。

#### Scenario: Correctness experiment is isolated from performance claims
- **WHEN** 运行机制正确性实验
- **THEN** 结果 SHALL 以 publish、observed-publish、activate、fallback 和 rank 一致性事件为主要证据
- **AND** 该实验 SHALL NOT 直接作为策略收益结论的依据

#### Scenario: Cost experiment is isolated from policy-quality claims
- **WHEN** 运行机制成本实验
- **THEN** 结果 SHALL 主要比较 baseline、profiler-only、final-steady 和 weak-online 的 host-side 开销
- **AND** 该实验 SHALL NOT 单独用于断言 learned candidate 本身优于 baseline

### Requirement: Repeated runs and run-order control
系统 SHALL 将 replicate 与 run order 视为实验协议的一部分，并在 mode comparison 与 size sweep 实验中控制顺序偏差。

#### Scenario: Mode comparison uses replicates
- **WHEN** 执行 mode comparison 实验
- **THEN** 协议 SHALL 要求同一实验条件运行多个 replicate
- **AND** 每个 replicate SHALL 记录唯一的 replicate 标识

#### Scenario: Mode order is not fixed across all replicates
- **WHEN** 执行多个 replicate
- **THEN** baseline、profiler-only、final-steady 和 weak-online 的运行顺序 SHALL 轮换或显式随机化
- **AND** 协议 SHALL NOT 假定固定顺序不会影响结果

### Requirement: Segment-aware weak-online analysis
系统 SHALL 对 weak-online 实验结果进行阶段化解释，而不是只保留整体平均值。

#### Scenario: Weak-online results distinguish execution phases
- **WHEN** 记录 weak-online 实验结果
- **THEN** 结果 SHALL 能区分至少 warmup、steady active policy 和 recheck window 三类阶段
- **AND** 结果解释 SHALL 说明 observed latency 来自哪个阶段

#### Scenario: Tail-sensitive statistics are available
- **WHEN** 输出 weak-online 或 mode comparison 的统计结果
- **THEN** 结果 SHALL 至少支持 median、p95 和 max 等对尾延迟敏感的指标
- **AND** SHALL NOT 仅以单个 overall mean 代表全部性能行为

### Requirement: State-granularity evaluation uses size sweep
系统 SHALL 使用专门的 size sweep 实验评估同一状态 bucket 内的 candidate 分歧，而不是只依赖少量混合日志示例。

#### Scenario: Sweep sizes within one bucket
- **WHEN** 评估某个 size bucket 的 honesty
- **THEN** 协议 SHALL 固定 `nRanks`、`nNodes`、mode 和 adaptive 参数
- **AND** SHALL 仅改变落在该 bucket 内的多个 message size

#### Scenario: Candidate trajectory is recorded per size
- **WHEN** size sweep 实验完成
- **THEN** 结果 SHALL 为每个 message size 记录多个 epoch 或窗口上的 candidate trajectory
- **AND** SHALL 支持比较不同 size 在 replicate 之间是否表现出稳定分层

### Requirement: Experiment metadata is part of the result contract
系统 SHALL 将实验元数据视为结果的一部分，以保证结果可追溯和可比较。

#### Scenario: Adaptive control parameters are captured
- **WHEN** 保存实验结果目录
- **THEN** 元数据 SHALL 包含 adaptive 控制参数，包括 warmup、recheck、switch threshold 和 activation lag

#### Scenario: Execution context is captured
- **WHEN** 保存实验结果目录
- **THEN** 元数据 SHALL 包含 workload 参数、关键 NCCL 环境、replicate id 和 run order
- **AND** 结果消费者 SHALL 能仅凭结果目录重建实验条件
