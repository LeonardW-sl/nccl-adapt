## MODIFIED Requirements

### Requirement: Layered adaptive experiment protocol
系统 SHALL 将自适应 NCCL 实验拆分为分层、可证伪的协议，按 `Phase 1 headroom -> Phase 2 static envelope -> Phase 3 drift challenge` 的顺序推进。

#### Scenario: Phase 1 fixes the clean-surface headroom contract
- **WHEN** 执行 switching-value 的第一阶段实验
- **THEN** `Batch A` SHALL 固定在 `numa1-4gpu`、`allreduce`、单一 communicator-domain、same-socket 4 GPU world 下运行
- **AND** SHALL 固定比较 `baseline`、`static-replay`、`final-steady` 和 `weak-online`
- **AND** SHALL 固定 `warmup=4`、`measure=192`、`replicates=3`
- **AND** SHALL 固定 size 集合为 `4/8/16/32/64/128/256 MiB`

#### Scenario: Candidate-aligned replay is required for honest headroom judgment
- **WHEN** `final-steady` 在某个 size 学到的 candidate 与当前 replay candidate 不同
- **THEN** 该 size SHALL 补跑 candidate-aligned `static-replay`
- **AND** 在补跑完成前，该 size SHALL NOT 被用来做最终 headroom judgment

#### Scenario: Only headroom-positive sizes promote to topology comparison
- **WHEN** `Batch A` 的某个 size 满足 `headroom-positive`
- **THEN** 该 size SHALL 晋级到 `Batch B`
- **AND** `Batch B` SHALL 至少比较 `cross-8gpu`
- **AND** `numa0-4gpu` 若运行，只 SHALL 作为 anomaly boundary 记录，而不是第一批主证明面

#### Scenario: Phase 1 manifests are explicit
- **WHEN** 保存 `Phase 1` 结果
- **THEN** 每个 run SHALL 记录 `batch / topology / size / mode / replicate / result_dir / summary artifact`
- **AND** 结果目录 SHALL 允许回溯 candidate-aligned replay 是否被触发

### Requirement: Static-envelope search is gated by proven headroom
系统 SHALL 只在 headroom 已被证明后进入静态包络搜索，并显式记录静态规则是否足够解释收益。

#### Scenario: Phase 2 starts from promoted regimes only
- **WHEN** 进入 `Phase 2`
- **THEN** 输入 SHALL 限制为 `Phase 1` 中被标记为 `headroom-positive` 的 regimes
- **AND** 结果 SHALL 先整理 `best static candidate` 是否随 size 或 topology 改变

#### Scenario: Phase 2 rule expression starts with size plus topology
- **WHEN** 写出第一版 `best piecewise-static policy`
- **THEN** 规则表达 SHALL 先从 `size bucket + topology group` 开始
- **AND** 只有当该静态包络仍解释不足时，才允许继续补 world-size 维度

#### Scenario: Phase 2 manifests are explicit
- **WHEN** 保存 `Phase 2` 结果
- **THEN** 每个 run SHALL 记录 `rule_scope / rule_id / topology / size / mode_or_policy / replicate / result_dir / summary artifact`
- **AND** 结果 SHALL 明确哪些 regimes 已可由静态表解释，哪些 regimes 仍保留为 drift challenge 入口

### Requirement: Drift challenge isolates drift families and keeps recheck diagnostic-only
系统 SHALL 在 `Phase 3` 中把 drift family 与 recheck 调参分开，只有当静态包络仍解释不足时才允许进入 drift challenge。

#### Scenario: Phase 3 starts only after static envelope is insufficient
- **WHEN** 一个 regime 进入 `Phase 3`
- **THEN** 它 SHALL 已被 `Phase 2` 标记为“静态包络仍解释不足”
- **AND** 它 SHALL 同时保留一个 no-drift control 作为比较地板

#### Scenario: Compute-overlap drift family has a fixed three-arm template
- **WHEN** 运行计算侧 drift challenge
- **THEN** 最小实验模板 SHALL 固定为 `control`、`compute-overlap-early` 和 `compute-overlap-late`
- **AND** `early/late` 只 SHALL 改变背景计算相对于目标 collective 的启动相位
- **AND** SHALL NOT 同时改变静态 key 或计算负载家族

#### Scenario: Communication-interference drift family has a fixed three-arm template
- **WHEN** 运行通信侧 drift challenge
- **THEN** 最小实验模板 SHALL 固定为 `control`、`low-comm-interference` 和 `high-comm-interference`
- **AND** `low/high` 只 SHALL 改变干扰强度
- **AND** SHALL NOT 同时更换多个强度旋钮或改变静态 key

#### Scenario: Recheck remains a diagnostic probe
- **WHEN** 比较 `recheck_after`
- **THEN** 该变量 SHALL 只作为诊断探针使用
- **AND** 至少一个较短与一个较长设置 SHALL 在其他 drift 变量保持不变的前提下比较
- **AND** `recheck_after` SHALL NOT 单独构成 switching value 证据

#### Scenario: Phase 3 manifests and judgments are explicit
- **WHEN** 保存 `Phase 3` 结果
- **THEN** 每个 run SHALL 记录 `drift_family / variant / topology / size / mode / recheck_setting / replicate / result_dir / summary artifact`
- **AND** 结果 SHALL 同时判断是否观察到 `stable candidate / policy flip`
- **AND** 结果 SHALL 判断 `weak-online` 是否稳定优于最佳非切换方案
