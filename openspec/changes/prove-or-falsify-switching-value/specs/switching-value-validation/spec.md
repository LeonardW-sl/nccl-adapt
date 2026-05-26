## ADDED Requirements

### Requirement: Switching value is validated in three layers
系统 SHALL 将 `switching value` 的判断拆分为 `headroom`、`static envelope` 和 `drift value` 三层，而不是默认把 `weak-online` 当作最终目标。

#### Scenario: Three-layer decision order is fixed
- **WHEN** 一个 change 或 evidence 试图声明 `switching value`
- **THEN** 它 SHALL 先判断是否存在 `best static candidate > baseline` 的 headroom
- **AND** SHALL 再判断该收益是否已可由 `best piecewise-static policy` 解释
- **AND** 只有在静态包络仍解释不足时，才允许继续判断 run-time drift 是否证明 switching 仍有额外价值

#### Scenario: Comparison ladder is explicit
- **WHEN** 结果需要比较 adaptive 方案
- **THEN** 结果 SHALL 按 `baseline -> best static candidate -> best piecewise-static policy -> final-steady -> weak-online` 的顺序解释
- **AND** SHALL NOT 只用 `baseline -> weak-online` 的两臂比较替代这一阶梯

### Requirement: Same-key switching means future correction
系统 SHALL 将当前 adaptive switching 解释为对未来重复 collective 的纠正，而不是对单次 in-flight collective 的中途改写。

#### Scenario: Same key is a repeated collective domain
- **WHEN** 系统判断两个 collective 是否属于同一个 policy key
- **THEN** `same key` SHALL 由 `commId + collType + size bucket + nRanks + nNodes` 共同定义
- **AND** 该 key SHALL 表示重复命中的 collective 域，而不是一次 in-flight collective 实例

#### Scenario: No in-flight mutation claim is preserved
- **WHEN** evidence 或 spec 解释 current switching behavior
- **THEN** 它 SHALL 说明 policy publish 只影响后续匹配 collective
- **AND** SHALL NOT 把 switching 描述为“单次 collective 运行到一半时被改写”

### Requirement: Positive evidence and falsification boundaries are explicit
系统 SHALL 同时定义正向证据门槛与负结论边界，允许 `switching value` 被证伪。

#### Scenario: Positive evidence threshold is fixed
- **WHEN** 一个 regime 被写成 `headroom-positive` 或 `switching value established`
- **THEN** aggregate latency delta SHALL 至少达到 `2.0%`
- **AND** 默认 `3` 个 replicate 中至少 `2` 个 replicate SHALL 保持同方向改善

#### Scenario: Stable flip requires repeated winner change
- **WHEN** 结果试图声明存在 `stable candidate / policy flip`
- **THEN** winner 变化 SHALL 在至少 `2/3` replicate 中重复出现
- **AND** drift variant 下的新 winner 相对 control winner 的优势 SHALL 至少达到 `2.0%`

#### Scenario: No-drift advantage blocks drift-only claims
- **WHEN** no-drift 对照下已经存在与 drift 下同等级的优势
- **THEN** 结果 SHALL 回退审视 `static envelope` 解释
- **AND** SHALL NOT 直接把该优势记作 drift-driven `switching value`

#### Scenario: Negative conclusions are first-class outputs
- **WHEN** 实验没有满足正向 switching 证据门槛
- **THEN** evidence SHALL 允许输出 `no proven headroom`、`static envelope sufficient` 或 `drift not strong enough to justify switching`
- **AND** SHALL NOT 默认继续把 `weak-online` 表述成最终应当获胜的目标
