## Why

项目的长期目标是：

```text
same-key phase shift-aware online NCCL plugin
```

但在证明 switching value 之前，必须先证明更基础的一层：

```text
是否存在可被利用的 static room
```

这里的 `static room` 不是最终目标，而是前提层。

当前分支已经有一个重要的负信号：

- 在当前窄 candidate surface 与当前 pure-communication smoke 上，尚未证明稳定 headroom

但这个结果只能被保守解释为：

```text
current search surface did not prove static room
```

而不能直接解释为：

```text
static value does not exist
```

因此需要一个单独 change，把下面两件事作为同一前置验证层一起处理：

1. 在干净、受控的 static surface 上寻找 `communication room`
2. 在同一批 regime 上立即验证这些收益是否能转化为真实 `workload room`

## Goal

本 change 的目标是在 `numa1-4gpu` clean reference surface 上建立
`static room`，并将每个确认完成的 regime 明确分类为：

- `no proven communication room`
- `communication-only win`
- `workload-confirmed static win`

补充目标：

- 结论必须绑定到 `current controlled surface version`
- `communication room` 与 `workload room` 必须来自同一 regime、同一
  candidate、同一 run family 的双层读数
- 后续 `same-key-phase-shift-validation` 只能从
  `workload-confirmed static win` regime 中选入口

## Surface V1 Boundaries

本 change 的第一版受控 proving surface 固定为：

- topology group: `numa1-4gpu`
- collective: `allreduce`
- world size: 当前 same-socket 4-GPU / single-node 配置
- comparison style: deterministic fixed-candidate replay

本 change 中的 `controlled candidate axis` 不应被当前实现中已经枚举的
candidate 个数绑定。

应以更一般的方式定义为：

```text
any deterministic fixed non-default candidate family
that can be replayed under the same static regime
```

当前代码中的 candidate 只是 `surface v1` 的一个 realization，而不是本
change 的上界。

`surface v1` 内允许采用两段式扩展：

1. screening
   - 用较少 size 点快速筛更多 fixed candidates
2. confirmation
   - 只对 shortlist candidates 跑完整 regime 与 replicate 口径

本 change 明确排除：

- `numa0-4gpu`
- `cross-8gpu`
- same-key phase shift 变体
- `weak-online payoff` 证明
- 把 `final-steady` / `weak-online` 作为 static room 的主比较对象

## What Changes

- 新增一个以 `static room establishment` 为目标的 change。
- 明确 `communication room` 与 `workload room` 属于同一个前置验证层。
- 固定 `numa1-4gpu` 作为本 change 的唯一 proving surface。
- 要求 static candidate 评估在同一 run family 内同时记录：
  - collective-local 指标
  - microstep / workload-level 指标
- 引入 `tail-anchored static microstep` harness，避免继续把 pure
  communication smoke 误当作 workload room 的充分证据。
- 要求采用两段式 surface 扩展：
  - screening
  - confirmation
- 要求结果不能只输出 “某 candidate 更快”，而要输出 regime 级静态收益分类结论。
- 要求结果显式记录：
  - controlled surface version
  - candidate availability
  - requested candidate 与 observed selected path 的关系
- 要求后续 phase-shift change 只能从 `workload-confirmed static win`
  的 regime 中选择入口，并继承该 regime 的 static comparison floor。

## Completion Conditions

本 change 完成时不以“出现某个正例”为条件，而以“完成一版 bounded
room map”为条件。

至少必须产出：

1. 一份 `surface v1 statement`
   - 说明受控轴、观察轴、排除轴
   - 说明当前 realization 与排除原因
2. 一份 screening 摘要
   - 说明哪些 fixed candidates 进入 confirmation
   - 哪些 candidates 被排除，以及原因
3. 一份 confirmation 级 regime judgment 表
   - 每个 regime 必须被判为：
     - `no proven communication room`
     - `communication-only win`
     - `workload-confirmed static win`
4. 一份 promotion pack
   - 明确哪些 regime 可以进入 `same-key-phase-shift-validation`
   - 并给出它们的 static comparison floor 与 contender set
5. 一份 bounded negative conclusion
   - 当未观察到正例时，必须明确写成：
     `no proven room on current controlled surface version`

补充完成条件：

- 结果必须包含 candidate 分类，而不是只有 pooled latency 表
- 结果必须说明 `baseline` 与 non-default candidate 的关系
- 结果必须说明 requested candidate 与 observed path 的关系
- 结果必须说明哪些 regime 可以晋级到 phase-shift validation
- 结果必须说明哪些 regime 虽然有 collective-level 正信号，但未转化为
  workload-level room
- 结果不得把当前 surface 的负结论外推成“static value 不存在”

## Non-Goals

- 不在本 change 中证明 same-key phase shift 已存在
- 不在本 change 中证明 `weak-online` 已经回本
- 不在本 change 中直接重写 `weak-online` 策略
- 不把单纯 communication-local 的提升自动记作最终项目成功
- 不把 pure communication smoke 继续当作 workload room 的充分代理
- 不在本 change 中直接证明完整训练 step 的最终收益
- 不要求本 change 穷尽所有可能的 static candidate family

## Impact

- 为后续 `same-key-phase-shift-validation` 提供候选 regime
- 将项目从 “纯 smoke 两臂比较” 推进到 “双层 static room map”
- 为后续 `weak-online` 策略改写提供真实目标面，而不是抽象调参
- 为后续 candidate surface 扩展保留统一 evidence contract，而不是每次重启实验口径
