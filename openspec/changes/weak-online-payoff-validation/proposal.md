## Why

`weak-online` 的价值不应被过早证明。

在 room 尚未证明之前，`weak-online` 的失败是模糊的：

- 可能是策略不好
- 可能是采样税太高
- 也可能是根本没有 room 可利用

因此只有在：

- static room 已证明
- same-key phase-shift room 已证明

之后，才值得进入这一步：

```text
当前 weak-online 能不能回本？
```

## Goal

本 change 的目标是验证：

```text
weak-online payoff
```

也就是：

- 前期 sampling cost 能否被后期策略优势补回

## What Changes

- 新增一个专门验证 `weak-online payoff` 的 change。
- 固定比较对象为：
  - `weak-online`
  - 当前已知 best non-switching alternative
- 要求结果不能只比较整体均值，还要比较前期损耗、后期优势与 payback 边界。
- 要求本 change 的结果为后续策略改写提供明确诊断输入。

## Completion Conditions

本 change 只有在下列至少一项成立时才算完成：

1. 明确输出：
   - `sampling loss not recovered`
   - 说明当前 `weak-online` 尚未形成 payoff
2. 明确输出：
   - `weak-online payoff established`
   - 说明至少一个 validated phase-shift regime 上，后期优势足以覆盖前期损耗

补充完成条件：

- 结果必须明确比较对象是 best non-switching alternative，而不是只对比 `baseline`
- 结果必须明确 payback 的时间边界或调用边界
- 结果必须为后续策略改写提供原因分类

## Non-Goals

- 不在本 change 中重新证明 static room
- 不在本 change 中重新证明 same-key phase-shift room
- 不在本 change 中直接完成下一版 `weak-online` 策略重写

## Impact

- 为下一版 `weak-online` 策略改写提供定量目标
- 将项目从 “room exists” 推进到 “online policy can monetize the room”
- 防止策略重写在没有 payoff 证据时盲目复杂化
