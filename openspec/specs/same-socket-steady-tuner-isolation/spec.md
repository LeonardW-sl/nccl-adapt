# same-socket-steady-tuner-isolation Specification

## Purpose
TBD - created by archiving change same-socket-steady-tuner-isolation. Update Purpose after archive.
## Requirements
### Requirement: Same-socket steady-tuner isolation matrix
系统 SHALL 支持一个只针对 same-socket placement 的 steady-tuner 诊断矩阵，用于隔离 `profiler-only` 与 `final-steady` 的差异，而不混入跨 socket 或 recheck 变量。

#### Scenario: Only same-socket topology groups are included
- **WHEN** 执行 same-socket steady-tuner isolation 实验
- **THEN** 实验 SHALL 只包含 `numa0-4gpu` 与 `numa1-4gpu`
- **AND** SHALL NOT 把 `cross-8gpu` 作为该 change 的主诊断矩阵一部分

#### Scenario: Only profiler-only and final-steady modes are compared
- **WHEN** 执行 same-socket steady-tuner isolation 实验
- **THEN** 实验 SHALL 至少比较 `profiler-only` 与 `final-steady`
- **AND** SHALL NOT 依赖 `weak-online` 结果来判断 steady tuner 成本

### Requirement: Runtime contract stays aligned with topology-controlled rerun
系统 SHALL 在 same-socket steady-tuner isolation 中沿用 topology-controlled rerun 的核心运行时契约，只延长测量窗口，不引入新的算法变量。

#### Scenario: Container and adaptive parameters remain fixed
- **WHEN** 执行 same-socket steady-tuner isolation 实验
- **THEN** 容器镜像 SHALL 继续使用 `nvcr.io/nvidia/pytorch:26.03-py3`
- **AND** message size、candidate 集合、activation lag、switch threshold 与 topology-controlled rerun SHALL 保持一致

#### Scenario: Longer measurement window amortizes front-half cost
- **WHEN** 执行 same-socket steady-tuner isolation 实验
- **THEN** 结果契约 SHALL 使用长于 topology-controlled mode-comparison 的测量窗口
- **AND** 该窗口 SHALL 足以把 warmup / publish / activate 前段成本与 post-activation steady 成本区分开

### Requirement: Final-steady diagnostics expose activation boundary
系统 SHALL 为 same-socket steady-tuner isolation 保留足够的诊断信息，以分离 `final-steady` 的 pre-activation 与 post-activation 成本。

#### Scenario: Coordinator and completion traces are captured
- **WHEN** 运行 `final-steady` 诊断批次
- **THEN** 结果 SHALL 保留 coordinator trace 与 completion trace
- **AND** 结果消费者 SHALL 能识别 first publish、first activate、activated candidate 和 `wait-summary` 事件

#### Scenario: Final-steady summaries are segmented around activation
- **WHEN** 分析 `final-steady` 结果
- **THEN** 结果 SHALL 至少区分 overall、pre-activation 和 post-activation 统计
- **AND** SHALL NOT 只用单个 overall mean 来代表 steady tuner 成本

### Requirement: Same-socket conclusions are bounded by reproduced evidence
系统 SHALL 用 same-socket steady-tuner isolation 的结果来限定后续判断边界，而不是把所有 `final-steady` 成本都直接归因于 tuner。

#### Scenario: Same-socket jump persists
- **WHEN** `numa0-4gpu` 或 `numa1-4gpu` 在长测中仍稳定显示 `final-steady` 高于 `profiler-only`
- **THEN** 结论 SHALL 优先指向 steady tuner / coordinator 路径或其 same-socket placement interaction
- **AND** SHALL NOT 把该现象主要归因于 `weak-online` recheck

#### Scenario: Front-half cost dominates
- **WHEN** `final-steady` 的额外成本主要集中在 pre-activation 段而非 post-activation 段
- **THEN** 结论 SHALL 将重点放在 warmup / publish / activate 前段污染
- **AND** SHALL NOT 直接声称 steady active-candidate path 本身昂贵

#### Scenario: Only one same-socket group is abnormal
- **WHEN** 只有 `numa0-4gpu` 或只有 `numa1-4gpu` 稳定表现出显著 jump
- **THEN** 结论 SHALL 保留 socket-local placement、affinity 或 representative-rank locality 的解释
- **AND** SHALL NOT 把该差异直接外推为所有 topology group 的通用 tuner 成本

