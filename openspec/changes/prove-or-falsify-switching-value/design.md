## Context

当前仓库已经分别回答了这些局部问题：

- `weak-online` / `final-steady` 能安全运行
- communicator-domain 的共享发布与激活边界是可用的
- `numa1-4gpu` 是当前更干净的参考面
- `weak-online` 的额外 spike 主要与 recheck 相关

但还没有回答更上位的问题：

```text
run-time switching 本身是否有独立价值？
```

本 change 不默认回答“有”。它的任务是把这个问题变成一个允许被证伪的实验框架。

## Core Model

### 1. `same key` 的含义

这里的 `same key` 不是“一次 collective 实例”，而是重复命中的策略域。当前实现里，它由：

- `commId`
- `collType`
- `size bucket`
- `nRanks`
- `nNodes`

共同定义。

因此：

```text
same key
= 后续很多次高度相似的 collective
```

而不是：

```text
同一次 collective 的中途状态
```

### 2. 当前 switching 的含义

当前系统不会对 in-flight collective 中途改写策略。它的时序是：

```text
call t
  -> collective runs
  -> profiler 在完成后得到结果
  -> coordinator 可能发布新 policy
  -> call t+1, t+2, ... 才可能激活该 policy
```

所以这里讨论的 switching value 是：

```text
对未来重复 collective 的纠正价值
```

不是：

```text
对已经开始传输的 collective 做即时修补
```

## Decision Framework

本 change 强制按三层判断：

```text
Layer A: headroom
  是否存在优于 baseline 的 candidate / policy

Layer B: static envelope
  该收益能否被静态规则解释

Layer C: drift value
  若静态规则不够，run-time switching 是否还有额外价值
```

只有 `Layer A` 和 `Layer B` 都给出继续深入的理由时，`Layer C` 才值得投资。

### Comparison Ladder

本 change 固定使用以下比较顺序：

```text
baseline
  -> best static candidate
  -> best piecewise-static policy
  -> final-steady
  -> weak-online
```

解释规则：

- `best static candidate > baseline`
  - 说明 candidate headroom 存在
- `best piecewise-static policy > best static candidate`
  - 说明收益部分来自静态分段
- `final-steady ≈ best piecewise-static policy`
  - 说明“一次学习后冻结”已经足够
- `weak-online > final-steady` 且 `weak-online > best piecewise-static policy`
  - 才构成 switching value 的正证据

### Static First

若收益已经可由静态变量解释，例如：

- size bucket
- topology group
- `nRanks`
- `nNodes`

则本 change 优先接受：

```text
piecewise-static policy
```

而不是继续引入更复杂的 run-time switching。

## Phase 1: Same-Key Headroom

Phase 1 的目标只回答两件事：

```text
1. 是否存在可复现的 headroom
2. 这种 headroom 会不会只出现在小/中等 size
```

### Batch A: Clean-Surface Size Sweep

第一批 regime 固定为：

- topology group: `numa1-4gpu`
- collective: `allreduce`
- communicator: 固定单一 communicator-domain
- world size: 固定当前 same-socket 4-GPU 配置
- modes:
  - `baseline`
  - `static-replay`
  - `final-steady`
  - `weak-online`
- window:
  - 先沿用当前 long-window 口径：`warmup=4`、`measure=192`
- replicates:
  - 先固定为 `3`

第一批 size 集合固定为：

- `4 MiB`
- `8 MiB`
- `16 MiB`
- `32 MiB`
- `64 MiB`
- `128 MiB`
- `256 MiB`

这组点的作用是：

- 保留现有 `8 MiB` 锚点，便于与已有证据对齐
- 向更大 size 扩展，检验“收益是否只是小/中等 size 现象”

### Candidate Alignment Rule

`static-replay` 不能只做一次全局固定重放。Phase 1 必须按 size 做 candidate 对齐：

- 默认以当前最常见 learned candidate 作为起点
- 若某个 size 上 `final-steady` 学到不同 candidate
  - 则该 size 必须补做 candidate-aligned replay
  - 否则不得用于 headroom 判断

### Batch B: Topology Promotion

只有在 `Batch A` 中被判定为 `headroom-positive` 的 size，才进入 topology promotion：

- primary target: `cross-8gpu`
- optional boundary: `numa0-4gpu`

其目的不是重跑所有点，而是回答：

```text
同一个 size 的 headroom
是 clean surface 特有，
还是在更复杂 topology 上仍然存在
```

### Headroom Judgment

Phase 1 的判定规则如下：

- 若某个 size 上，candidate-aligned `best static candidate` 不能稳定优于 `baseline`
  - 标记为 `no proven headroom`
- 若某个 size 上，candidate-aligned `best static candidate` 明显优于 `baseline`
  - 标记为 `headroom-positive`
- 若 `weak-online` 优于 `baseline`，但不优于最佳非切换方案
  - 仍不得记作 switching value 正证据

本 change 特别关注以下两类结果：

- `4/8/16/32/64 MiB` 有 headroom，但 `128/256 MiB` 没有
  - 解释为 size-local headroom
- `numa1-4gpu` 有 headroom，但 `cross-8gpu` 没有
  - 解释为 topology-sensitive headroom

## Phase 2: Static Envelope Search

只有在 headroom 已被证明的前提下，才继续做静态包络搜索。

至少扩展：

- size buckets
- topology groups
- world sizes

目标是构造：

```text
best piecewise-static policy
```

若此时主要收益已经可以由静态表解释，则本 change 应接受结论：

```text
static envelope sufficient
```

## Phase 3: Drift Challenge

只有当：

- headroom 已存在
- 且静态包络仍解释不足

才进入 drift challenge。

第一版 drift challenge 在本 change 中先敲定为两类：

### Drift Family A: 背景计算 + overlap phase shift

目标：

- 在不改变静态 key 的前提下，引入训练期常见的计算侧干扰
- 观察同一个 communication regime 在 overlap 相位变化前后，最佳 policy 是否发生稳定变化

第一版口径：

- 以背景计算作为主扰动
- 以 overlap phase shift 作为同一家族的子变量
- 最小实验形态固定为三臂：
  - `control`: no-drift
  - `compute-overlap-early`
  - `compute-overlap-late`

最小可接受实现口径：

- 三个变体必须保持相同静态 key：
  - 相同 communicator-domain
  - 相同 collective type
  - 相同 message size / size bucket
  - 相同 topology group
  - 相同 `nRanks / nNodes`
- `compute-overlap-early` 与 `compute-overlap-late` 必须使用同一种背景计算负载
- 二者允许变化的主变量只应是计算相对于目标 collective 的启动相位
- 不得同时改变 message size、topology、candidate 集合或 world size
- 不接受用随机 sleep 或 CPU 侧阻塞替代背景计算，因为那会把 drift 从 compute/overlap 问题变成 host noise 问题

判别意图：

- 若 `early` 与 `late` 的差异成立，则更接近“overlap phase 在变”
- 若三臂结果都等价，则该 key 在当前计算侧扰动下不支持 switching 价值叙事

理由：

- 它最贴近真实训练中的 communication/compute overlap
- 它改变的是运行时拥塞与重叠关系，而不是静态拓扑或 size 定义
- 若 switching value 存在，这一类最有希望先暴露出来

### Drift Family B: 背景通信干扰

目标：

- 在静态 key 保持不变时，引入额外 communication pressure
- 观察目标 collective 的最佳 policy 是否因共享链路竞争而发生稳定变化

第一版口径：

- 目标 workload 保持原 key 不变
- 额外通信作为 sidecar interference 注入
- 最小实验形态固定为三臂：
  - `control`: no-drift
  - `low-comm-interference`
  - `high-comm-interference`

最小可接受实现口径：

- 三个变体必须保持相同静态 key：
  - 相同 communicator-domain
  - 相同 collective type
  - 相同 message size / size bucket
  - 相同 topology group
  - 相同 `nRanks / nNodes`
- `low-comm-interference` 与 `high-comm-interference` 必须使用同一种 sidecar communication family
- 二者允许变化的主变量只应是干扰强度
  - 例如更高的干扰 duty、更多 sidecar 次数，或更大的 sidecar message size
- `low` 与 `high` 不应同时更换多个强度旋钮，否则强弱差异将不可解释
- 不接受引入不同 topology、不同 communicator 规模或不同测量窗口长度来伪造 `low/high`

判别意图：

- 若 `high` 明显恶化而 `low` 变化较小，则说明该 key 对 communication contention 敏感
- 若 `weak-online` 只在 `high` 下受益，则应把收益限定为 contention-sensitive switching value

理由：

- 它比纯 CPU 噪声或随机 sleep 更直接作用于 communication path
- 它能更直接检验 switching 是否对 communication-side contention 敏感

### Diagnostic Probe: `recheck_after`

`recheck_after` 在本 change 中继续只作为诊断探针使用：

- 它可以帮助判断 phase change 是否与 weak-online 的 recheck 机制对齐
- 但它本身不被视为独立 drift family
- 也不能单独构成 switching value 证据
- 调整 `recheck_after` 时，其他 drift family 变量应保持不变

这里要验证的不是“能不能频繁切”，而是：

```text
在低频 reconsideration 下，
最优策略是否会在同一静态 key 下稳定翻转
```

若 `weak-online` 仍不优于最佳非切换方案，则 switching value 不成立。

## Judgment Thresholds

本 change 显式区分两类阈值：

- 机制阈值
  - 当前实现中的 `NCCL_ADAPTIVE_SWITCH_THRESHOLD_PCT`
  - 默认值为 `2.0`
  - 它决定 coordinator 是否愿意切换 candidate
- 证据阈值
  - 本 change 用来决定何时允许把结果写成 `headroom-positive`、`static envelope sufficient` 或 `switching value established`
  - 第一版同样固定为 `2.0%`，便于和现有机制阈值对齐

本 change 的默认 replicate 口径为 `3`。除非后续有单独 change 改写，否则正向结论至少需要满足：

- aggregate latency delta 达到 `2.0%`
- 且 `3` 个 replicate 中至少 `2` 个 replicate 同方向

小于 `2.0%` 的变化可以记录，但不得直接升级为正向叙事。

### Headroom-Positive

某个 regime 只有在下列条件同时成立时，才允许标记为 `headroom-positive`：

- candidate-aligned `best static candidate` 相对 `baseline` 的 aggregate 改善达到 `2.0%`
- 至少 `2/3` replicate 保持同方向改善

否则统一记为：

```text
no proven headroom
```

### Static Envelope Sufficient

某个 regime 只有在下列任一条件成立时，才允许标记为 `static envelope sufficient`：

- `best piecewise-static policy` 已解释主要收益，且 `weak-online` 相对该静态包络的 residual gain 小于 `2.0%`
- 或 `weak-online` 虽然均值更高，但未满足 `2.0%` + `2/3 replicate` 的正向证据门槛

这条规则的核心不是要求静态表必须完全等于 `weak-online`，而是要求：

```text
剩余优势不足以证明 switching 本身有独立价值
```

### Stable Candidate / Policy Flip

`stable flip` 不是指单次窗口里的瞬时波动，而是指：

- 在同一个静态 key 下
- `control` 与至少一个 drift variant 的最佳非切换选择不同
- 且这种 winner 差异在至少 `2/3` replicate 中重复出现
- 同时该 variant 下的新 winner 相对 control winner 的优势达到 `2.0%`

若只是单个 replicate 偶发换 winner，或优势低于 `2.0%`，只能记为噪声或未证实漂移。

### Switching Value Established

某个 drift regime 只有在下列条件同时成立时，才允许输出正向 switching value 证据：

- 已观察到 `stable candidate / policy flip`
- `weak-online` 相对最佳非切换方案的 aggregate 改善达到 `2.0%`
- 至少 `2/3` replicate 保持同方向改善
- 该优势需要在 no-drift 对照中被明确区分
  - 若 no-drift 下也已经存在同样强的优势，则应回退审视 `Phase 2` 的静态解释，而不是直接记作 drift-driven switching value

否则统一进入以下负结论之一：

- `static envelope sufficient`
- `drift not strong enough to justify switching`

## Falsification Rules

本 change 明确把下列结果视为有效成功结论：

### F1. No Headroom

若 `best static candidate` 也不能稳定优于 `baseline`，则：

```text
no proven headroom on this regime
```

### F2. Static Envelope Is Enough

若 `best piecewise-static policy` 已经解释了主要收益，且 `weak-online` 没有稳定优于它，则：

```text
switching value not proven;
static envelope sufficient
```

### F3. Drift Not Strong Enough

若 drift challenge 下没有稳定 candidate flip，或 `weak-online` 仍无额外收益，则：

```text
run-time drift not yet shown to justify switching
```

## Result Contract

本 change 期望后续 evidence 至少输出三类结果：

- `headroom map`
  - 哪些 regime 有 headroom，哪些没有
- `static envelope summary`
  - 最佳非切换方案是否已经足够
- `drift challenge summary`
  - 是否存在同一静态 key 下的稳定 policy flip

## Open Questions

- `best piecewise-static policy` 的第一版表达是否只依赖 `size bucket + topology group`
- drift challenge 中最有代表性的背景干扰是通信、计算，还是二者重叠
- 若默认 `weak-online` 参数没有产生真实 re-switch，应如何严格区分“参数不足以证明 switching”与“switching 本身无价值”
