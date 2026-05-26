## Why

项目的真正目标不是 generic adaptive tuning，而是：

```text
same-key phase shift-aware online correction
```

只有当下面这件事成立时，switching 才有独立价值：

```text
在同一个 static key 内，
runtime phase shift 改变了真实 best winner
```

因此在 static room 已被建立之后，需要一个单独 change 来验证：

- phase shift 是否真的存在可观测 room
- 这个 room 是否足以让 best non-switching winner 翻转

## Goal

本 change 的目标是验证：

```text
same-key phase-shift room
```

输出必须明确区分：

- `no stable winner change`
- `same-key phase-shift room established`

## What Changes

- 新增一个专门验证 same-key phase shift 的 change。
- 固定 phase shift 只允许发生在同一个 static key 内。
- 固定 drift family：
  - `compute-overlap`
  - `comm-interference`
- 要求比较对象首先是 best non-switching winners，而不是直接默认比较 `weak-online`
- 要求结果说明 phase variant 是否让 winner 稳定翻转

## Completion Conditions

本 change 只有在下列至少一项成立时才算完成：

1. 明确输出：
   - `no stable winner change`
   - 说明当前已验证的 same-key drift 还不足以支持 switching room
2. 明确输出：
   - `same-key phase-shift room established`
   - 说明至少一个 static key 下存在稳定 winner flip

补充完成条件：

- 结果必须说明 drift family 与 variant
- 结果必须说明 winner 变化是否跨 replicate 稳定
- 结果必须说明后续 `weak-online-payoff-validation` 应使用哪些 regime

## Non-Goals

- 不在本 change 中证明当前 `weak-online` 已经回本
- 不在本 change 中直接重写 `weak-online` 策略
- 不把 static regime 变化误写成 phase shift

## Impact

- 为后续 `weak-online-payoff-validation` 提供真实 phase-shift regime
- 将项目从 “静态收益存在” 推进到 “同 key 下 winner 会不会翻转”
- 明确 switching room 是否真实存在
