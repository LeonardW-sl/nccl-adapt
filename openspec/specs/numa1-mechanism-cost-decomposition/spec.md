# numa1-mechanism-cost-decomposition Specification

## Purpose
TBD - created by archiving change numa1-mechanism-cost-decomposition. Update Purpose after archive.
## Requirements
### Requirement: NUMA1-only mechanism decomposition matrix
系统 SHALL 支持一个只针对 `numa1-4gpu` 的长窗口机制分解矩阵，用于把 profiler 观察税、fixed-candidate 效果和 dynamic final-steady 机制残差拆开。

#### Scenario: Only NUMA1 placement is used for the primary matrix
- **WHEN** 执行 `numa1` 机制成本分解实验
- **THEN** 主实验矩阵 SHALL 只包含 `numa1-4gpu`
- **AND** SHALL NOT 依赖 `numa0-4gpu` 或 `cross-8gpu` 结果来判断机制成本是否已拆清

#### Scenario: Four aligned modes are compared
- **WHEN** 执行 `numa1` 机制成本分解实验
- **THEN** 结果 SHALL 至少比较 `baseline`、`profiler-only`、`static-replay` 和 `final-steady`
- **AND** SHALL 使用与 same-socket long-window 一致的 workload、container 和长测窗口

### Requirement: Static replay must be candidate-aligned
系统 SHALL 保证 `static-replay` 与 `final-steady` 的比较具备 candidate 对齐前提，否则不得把残差解释为 dynamic 机制税。

#### Scenario: Learned candidate stays stable
- **WHEN** `final-steady` 在 `numa1` rerun 中激活到当前预期 candidate
- **THEN** `static-replay` SHALL 使用同一 candidate
- **AND** `final-steady post-activation - static-replay` MAY 作为 dynamic 机制残差的主比较量

#### Scenario: Learned candidate drifts
- **WHEN** `final-steady` 在 `numa1` rerun 中激活到不同 candidate
- **THEN** 结果 SHALL 显式记录 candidate mismatch
- **AND** SHALL NOT 直接把未对齐的 `final-steady - static-replay` 残差写成机制结论

### Requirement: Plugin-enabled runs expose algorithm/protocol observability
系统 SHALL 为 plugin-enabled 运行保留足够的观测信息，以验证 `static-replay` 与 `final-steady` 是否在 candidate 对齐后仍存在底层路径差异。

#### Scenario: Selected path is captured in result artifacts
- **WHEN** 运行 `profiler-only`、`static-replay` 或 `final-steady`
- **THEN** 结果消费者 SHALL 能读取 candidate、`selectedAlgo`、`selectedProto` 和 `nChannels`
- **AND** 这些字段 SHALL 进入可解析的结果契约，而不只存在于进程内状态

#### Scenario: Dynamic diagnostics retain activation boundary
- **WHEN** 运行 `final-steady`
- **THEN** 结果 SHALL 保留 first publish、first activate、activated candidate 和 `wait-summary` / completion diagnostics
- **AND** SHALL 至少区分 overall、pre-activation 和 post-activation 统计

### Requirement: Mechanism conclusions are based on decomposed comparisons
系统 SHALL 用分解后的比较量来表述机制成本，而不是把 `final-steady - profiler-only` 直接当成 steady 机制税。

#### Scenario: Profiler tax is isolated
- **WHEN** 对 `numa1` 矩阵做结果解读
- **THEN** `profiler-only - baseline` SHALL 作为 profiler / observation tax 的主比较量

#### Scenario: Fixed-candidate effect is isolated
- **WHEN** 对 `numa1` 矩阵做结果解读
- **THEN** `static-replay - profiler-only` SHALL 作为 fixed-candidate effect 的主比较量
- **AND** SHALL NOT 把该差值误写成 dynamic coordinator 成本

#### Scenario: Dynamic residual is isolated
- **WHEN** `static-replay` 与 `final-steady` candidate 对齐
- **THEN** `final-steady post-activation - static-replay` SHALL 作为 dynamic mechanism residual 的主比较量
- **AND** SHALL 优先使用 post-activation，而不是 overall，来避免 front-half 污染

### Requirement: NUMA1 conclusions gate H100 follow-up
系统 SHALL 用 `numa1` 分解结果来决定是否值得继续开 H100 follow-up change，而不是自动把当前结论外推到新平台。

#### Scenario: NUMA1 residual is small and well-explained
- **WHEN** `numa1` 上的 candidate 对齐和分解残差已经足够清晰
- **THEN** 结论 MAY 建议继续开 H100 follow-up change 做跨平台验证

#### Scenario: NUMA1 residual remains ambiguous
- **WHEN** `numa1` 上的残差仍混有 candidate mismatch 或未解释的 dynamic 成本
- **THEN** 结论 SHALL 优先要求先补本地机制归因
- **AND** SHALL NOT 把 H100 迁移当成默认下一步

