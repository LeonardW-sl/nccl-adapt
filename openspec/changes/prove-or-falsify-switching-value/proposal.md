## Why

当前 `nccl-adapt` 已经把 adaptive NCCL 的若干局部问题拆清：

- communicator-domain 一致发布与安全激活已经建立
- `weak-online` 的 recheck spike 已经能够被阶段化识别
- `numa1-4gpu` clean surface 上的 steady mechanism tax 已经被压到较小范围

但项目仍缺一个更上位、也更关键的问题定义：

```text
switching 本身到底有没有独立价值？
```

目前证据并不支持默认回答“有”：

- 在当前最干净的 `numa1-4gpu + 8 MiB` 结果中，`static-replay` 尚未稳定优于 `baseline`
- `weak-online` 的额外成本已知主要来自 recheck，而不是 steady path
- 新协议 rerun 也没有复现历史 `5/6/7 MiB` bucket 内的稳定 candidate 分叉

这意味着下一步不应默认假设 “weak-online 最终应该赢 baseline”，而应把总目标收敛为：

```text
证明或证伪 switching value
```

也就是回答三个层级的问题：

1. 是否存在 honest 的 policy headroom，说明切换前至少有值得争取的收益空间。
2. 如果存在 headroom，这个收益能否被 size/topology 等静态规则解释，而不需要 run-time switching。
3. 只有当静态规则不够、且 run 内 drift 真实存在时，weak-online switching 才有独立价值。

## What Changes

- 新增一个 umbrella change，把后续实验与结论统一组织成 “prove or falsify switching value” 的判别框架，而不是继续以 “优化 weak-online” 为默认叙事。
- 将总问题拆成三个必须分层验证的假设：
  - `headroom hypothesis`: 在某个 honest workload/topology/size 区间内，存在优于 `baseline` 的 candidate 或 policy。
  - `static-envelope hypothesis`: 上述收益可被静态可见变量解释，例如 size bucket、topology group、world size，而不需要 run-time switching。
  - `drift-value hypothesis`: 只有当 run 内 drift 足以让 “best static policy” 失效时，switching 才能带来额外收益。
- 定义新的比较基线顺序：
  - `baseline`
  - `best static candidate`
  - `best piecewise-static policy`
  - `final-steady`
  - `weak-online`
- 明确 `weak-online` 的价值不能只对比 `baseline` 判断，而必须对比 “当前可得到的最佳非切换方案” 判断。
- 将 falsification 也视为成功结果：如果证据表明收益主要来自静态分段 policy，或根本不存在稳定 headroom，本 change SHALL 允许得出 “switching currently has no proven value” 的结论。
- 将后续实验优先级重排为：
  - 先做 headroom map
  - 再做 static envelope
  - 最后才做 drift / switching value validation

## Non-Goals

- 不在本 change 中默认承诺 `weak-online` 会赢 `baseline`。
- 不在 headroom 尚未证明前，优先投入更复杂的 coordinator、recheck 或 online learning 机制。
- 不把单个 `8 MiB` 点位、单个 topology group 或单轮历史 bucket 现象直接外推为总目标结论。
- 不把机制成本实验与策略收益实验重新混为一谈。
- 不在本 change 中直接实现新的 adaptive policy 算法；本 change 首先定义判别问题与结果边界。

## Capabilities

### New Capabilities

- `switching-value-validation`: 定义一个以证明或证伪 switching value 为目标的总体验证框架，要求分别验证 headroom、静态可解释性和 run-time drift 价值。

### Modified Capabilities

- `adaptive-nccl-tuning`: 后续关于 `weak-online` 的收益声明 SHALL 对比最佳非切换基线，而不是只对比 `baseline`。
- `adaptive-experiment-determinism`: 后续实验协议 SHALL 允许把 “未证明 switching value” 作为有效结论，而不是只允许输出正向收益叙事。

## Impact

- 影响后续 OpenSpec change 的叙事顺序：新的机制或调参 change 需要先说明自己是在服务 `headroom`、`static envelope` 还是 `drift-value` 哪一层。
- 影响实验矩阵设计：后续主比较将从 “baseline vs weak-online” 扩展为 “baseline vs best static vs best piecewise-static vs switching”。
- 影响结果解释方式：`weak-online` 若优于 `baseline` 但不优于最佳非切换方案，不再能被表述为 switching value 已被证明。
- 影响后续是否值得继续投资更复杂 online control：只有当 `drift-value hypothesis` 获得支持时，这类投入才有明确目标。
