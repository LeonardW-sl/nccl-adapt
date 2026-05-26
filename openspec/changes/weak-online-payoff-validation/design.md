## Scope

本 change 只回答：

```text
当前 weak-online 能否在已验证的 phase-shift regime 上回本？
```

这里的 “回本” 指：

- 前期采样、warmup、recheck 等代价
- 是否被后期更优策略带来的收益覆盖

## Entry Criteria

只有来自 `same-key-phase-shift-validation` 的 validated regime 才能进入本 change。

原因：

- 如果 winner flip 尚未证明，则 payoff 评估没有真实目标面

## Comparison Ladder

本 change 的主比较对象不是 `baseline`，而是：

- best non-switching alternative
- `final-steady`
- `weak-online`

其中 primary question 是：

```text
weak-online > best non-switching alternative ?
```

## Payoff Model

本 change 必须显式区分：

- early cost
  - warmup sampling cost
  - recheck cost
- later gain
  - post-learning advantage
  - phase-sensitive advantage

### Negative Outcome

若 early cost 未被 later gain 覆盖，输出：

```text
sampling loss not recovered
```

### Positive Outcome

若在至少一个 validated regime 上，later gain 稳定覆盖 early cost，输出：

```text
weak-online payoff established
```

## Required Signals

### Inner-Loop

- publish / activate trajectory
- candidate history
- sampled-window cost
- steady-window cost
- recheck-window cost

### Outer-Loop

- step time 或 microstep time
- cumulative payoff boundary
- payback call index 或 payback window

## Diagnostic Outputs

即使未回本，本 change 也必须给出原因分类，至少包括：

- `room exists but current strategy too costly`
- `winner flip exists but weak-online does not capture it reliably`
- `phase-sensitive gain too small to offset sampling loss`

## Completion Conditions

本 change 完成时必须产出：

1. 每个 validated regime 的 payback 摘要
2. `sampling loss not recovered` 或 `weak-online payoff established` 结论
3. 一份后续策略改写输入摘要
   - 指出问题更像 cost 侧、timing 侧，还是 winner capture 侧

## Exit Artifact

本 change 的 exit artifact 应至少回答：

- 当前 `weak-online` 是否回本
- 如果未回本，主要卡在什么层
- 后续策略重写应优先优化哪一侧
