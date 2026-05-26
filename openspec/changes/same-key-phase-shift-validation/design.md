## Scope

本 change 只回答：

```text
在同一个 static key 内，
phase shift 会不会改变 true best non-switching winner？
```

这是最终 switching value 的前一层，而不是最终 payback 证明层。

## Entry Criteria

只有来自 `static-room-establishment` 的 `workload-confirmed static win` regime 才能进入本 change。

原因：

- 如果 static room 尚未证明，则 winner flip 没有坚实比较地板

## Same-Key Requirement

本 change 中的各变体必须保持：

- 相同 communicator-domain
- 相同 collective type
- 相同 message size / size bucket
- 相同 topology group
- 相同 `nRanks`
- 相同 `nNodes`

允许变化的是：

- collectives 相对背景 compute 的时序位置
- 或 sidecar communication 的干扰强度

## Drift Families

### Family A: Compute-Overlap

变体：

- `control`
- `compute-overlap-early`
- `compute-overlap-late`

约束：

- 只允许改变背景 compute 相对目标 collective 的启动相位
- 不允许同时改变 message size、topology、world-size 或 candidate surface

### Family B: Communication-Interference

变体：

- `control`
- `low-comm-interference`
- `high-comm-interference`

约束：

- 只允许改变 sidecar communication 的干扰强度
- 不允许同时更换多个强度旋钮

## Judgment Model

本 change 的核心比较对象是：

- best non-switching winner under `control`
- best non-switching winner under drift variant

### Negative Outcome

若 winner 不稳定翻转，输出：

```text
no stable winner change
```

### Positive Outcome

若在同一个 static key 下，winner 在至少一个 drift family 中稳定翻转，输出：

```text
same-key phase-shift room established
```

## Required Signals

### Inner-Loop

- collective latency
- algorithmic bandwidth
- bus bandwidth
- selected algorithm
- selected protocol
- channel count

### Outer-Loop

- step time 或 microstep time
- exposed tail proxy
- phase interpretation boundary

### Phase Interpretation

必须记录：

- collective 是更早还是更晚进入 critical path
- exposed tail 是上升还是下降
- interference 强度是如何变化的

## Completion Conditions

本 change 完成时必须产出：

1. 每个 drift family 的 winner comparison
2. 一份 stable flip 摘要
3. 一份可晋级到 `weak-online-payoff-validation` 的 regime 列表
4. 一份负结论列表
   - 说明哪些 regime 没有观察到 stable winner change

## Exit Artifact

本 change 的 exit artifact 应至少回答：

- 哪些 static key 在 phase shift 下没有 stable flip
- 哪些 static key 在 phase shift 下出现 stable flip
- 后续 `weak-online` 应该在哪些 regime 上尝试 payback 验证
