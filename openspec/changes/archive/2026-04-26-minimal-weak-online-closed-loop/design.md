## Context

当前 `nccl-adapt` 已经进入两个相邻但不同的方向：

- `final steady path`：目标是把 profiler 从最终性能热路径移开，让 tuner-only 与 steady policy 能接近 baseline。
- `weak-online closed loop`：目标是在不恢复常驻 profiler 重开销的前提下，允许系统对场景漂移做低频、受控、rank-consistent 的策略更新。

本 change 只覆盖第二个方向，并且明确限定为最小闭环。它不是“每个 collective 都在线调参”的强在线系统，而是“steady-first、窗口化观测、低频切换”的控制架构。

当前实现中的主要限制包括：

- tuner 热路径仍然通过全局 phase 轮转候选，而不是读取已发布 steady policy。
- profiler 与 tuner 共享进程内 `PolicyStore`，适合行为验证，不适合弱在线最小控制环。
- 现有设计没有热路径外的协调语义，因此无法安全表达“基于窗口摘要切换、同时保持 rank 一致”。

同时，NCCL collective、group ordering、stream 语义要求所有参与 ranks 的调用顺序和通信策略保持兼容，因此任何在线切换都必须避免由单 rank 的本地异步统计直接驱动。

## Goals / Non-Goals

**Goals:**

- 定义最小 weak-online 闭环，使系统能够在 `steady` 运行期间做低频复查和低频切换。
- 将 `communicator` 定义为第一版 policy domain，保证 collective 层面的策略一致性边界清晰。
- 将 tuner 热路径收敛为“只读 committed policy + availability 检查 + fallback/default”。
- 定义 `warmup -> steady -> recheck` 状态机，以及 `epoch`、`window_id`、`recheck_after` 的职责边界。
- 定义 coordinator 的最小职责边界，使其只接收窗口级摘要、裁决切换、发布 committed policy。
- 定义最小 `window summary` 模型，使观测路径只保留窗口聚合摘要，而不是全量 raw event。
- 明确 coverage 不完整、摘要过期、候选不可用时的 hold/fallback 规则。

**Non-Goals:**

- 不在本 change 中实现高频每-collective 在线调参。
- 不在本 change 中实现 per-node、hierarchical 或多 domain policy 控制。
- 不在本 change 中实现复杂多节点控制协议、服务端控制面或外部数据库。
- 不在本 change 中实现 learned policy、LLM 在线决策或训练数据平台。
- 不在本 change 中实现分位数、置信区间、复杂 bandit 或强化学习策略。
- 不在本 change 中处理 communicator grow/shrink 或成员动态变更。

## Decisions

### 1. 第一版 `policy domain` 固定为 `communicator`

选择：同一个 NCCL communicator 上参与同一 collective 的所有 ranks 共享同一个 committed policy、同一个 `epoch` 和同一组 recheck 节奏。

理由：collective 的一致性边界天然是 communicator。若第一版将 domain 下探到 per-node 或 per-process，会立即引入“同一 collective 是否允许不同 domain 使用不同策略”的兼容性问题，复杂度过高。

替代方案：按 node、process 或 topology shard 建立多个 domain。该方案未来可能更灵活，但需要额外协调协议与兼容性证明，不适合作为最小 weak-online change。

### 2. 状态机采用 `warmup -> steady -> recheck`

选择：每个 `key` 进入系统时先执行短 warmup 观测窗口；一旦形成 committed policy，则进入长 steady 区间；steady 到期或检测到条件触发时，进入短 recheck 窗口。

状态机形态：

```text
unknown
  -> warmup(window_id=0)
  -> steady(epoch=N, candidate=C, recheck_after=M)
  -> recheck(window_id=k, observed_epoch=N)
  -> steady(epoch=N or N+1)
```

理由：这能保证系统大多数时间停留在 steady，只有极少数窗口承担观测成本，符合“weak-online 明显低于 profiler-only、略高于 final steady”的预算目标。

替代方案：持续 phase rotation。该方案更接近行为验证原型，但会持续引入较差候选与额外观测成本，不符合 weak-online 目标。

### 3. `epoch`、`window_id`、`recheck_after` 职责明确分离

选择：

- `epoch`：当前 committed policy 的版本号，只在 coordinator 发布新 steady policy 时递增。
- `window_id`：某次 warmup/recheck 观测窗口编号，用于区分不同观察回合。
- `recheck_after`：steady 期间的调度提示，表示下一次允许重新打开观测窗口的事件间隔。

理由：若三者混用，系统容易把旧窗口摘要误用于新策略版本，或把调度计数误当成策略版本。

替代方案：仅使用单一 phase counter。该方案实现简单，但无法清晰表达“当前生效策略版本”和“正在评估的观察窗口”。

### 4. tuner 热路径只读 committed policy，不参与规划窗口

选择：`getCollInfo` 不再负责推进全局 phase、选择试探 candidate 或等待统计更新。其职责收敛为：

```text
make key
  -> read committed policy for key
  -> validate candidate availability
  -> apply selected candidate or default fallback
```

理由：NCCL tuner 路径必须无阻塞、低开销。弱在线设计中，窗口调度、摘要聚合和切换裁决都应发生在热路径外。

替代方案：让 `getCollInfo` 继续推进观测窗口或执行切换判断。该方案会把控制逻辑重新带回热路径，不利于控制 overhead。

### 5. coordinator 只看窗口级摘要，不看 raw event

选择：coordinator 的最小职责是：

- 接收某个 communicator-domain、某个 `key`、某个 `window_id` 的聚合摘要
- 判断是否维持旧 steady、发布新 steady、或回到 default
- 发布新的 committed policy（含 `epoch`、candidate、`recheck_after`）

它不负责：

- per-collective 决策
- 保存全量 raw records
- 热路径等待或热路径同步

理由：coordinator 是低频裁决者，不应退化成高频采集器或日志系统。

替代方案：coordinator 收集每个 rank 的每次 event 详情。该方案会显著扩大数据面和协调负担，不符合最小闭环目标。

### 6. `window summary` 第一版只保留最小聚合字段

选择：窗口摘要最小字段集合为：

- `key`
- `observed_epoch`
- `window_id`
- `candidate`
- `sample_count`
- `latency_sum_us`
- `bw_sum`
- `unavailable`

理由：第一版弱在线只需要判断“是否有足够稳定的优势切换到另一个 candidate”，不需要复杂统计。`sum + count` 足以计算均值，并保持实现简单。

替代方案：加入分位数、方差、全 rank 分布或全量 raw event。该方案可能对后续 learned policy 有价值，但会让第一版过大。

### 7. 切换决策必须同时满足三类门槛

选择：coordinator 只有在以下条件同时满足时才允许切换：

- 样本足够：窗口内相关 candidate 达到最小样本数
- 优势足够：新 candidate 相比当前 steady 超过阈值
- 优势持续：优势在整个窗口中持续存在，而非单次抖动

若任一条件不满足，则保持旧 steady。

理由：弱在线系统应偏向保守，避免因噪声造成抖动式频繁切换。

替代方案：只要观察到更优样本就立即切换。该方案响应快，但容易因为测量噪声导致 oscillation。

### 8. coverage 不完整时默认 hold，而不是猜测切换

选择：

- 如果当前已有 committed steady policy，而本次窗口 coverage 不完整，则保持旧 steady。
- 如果当前还没有 committed policy，且 warmup 数据不足，则回 `default` 或保守策略。
- 如果窗口摘要迟到且 `observed_epoch` 已过期，则不允许其驱动切换。

理由：在 collective 系统中，“保持旧 steady”比“半数参与者切换、半数未切换”安全得多。

替代方案：基于部分摘要做推断切换。该方案可能更灵活，但第一版风险过高。

### 9. 候选不可用只影响本地应用，不直接触发热路径切换

选择：某次 `getCollInfo` 发现 candidate 在当前 cost table 中不可用时：

- 当次调用立即 fallback 到 NCCL default
- 将该候选标记为当前 key 的 suspect/unavailable 输入，留待后续窗口裁决
- 不在热路径中等待 coordinator 发布新结果

理由：不可用候选是安全性问题，应优先保证当前 collective 可继续进行；但策略切换仍应通过窗口裁决路径完成。

替代方案：在热路径中立即全局改写 committed policy。该方案会把控制面重新拉进热路径。

## Risks / Trade-offs

- [Risk] communicator-domain 过于保守，可能掩盖 node 局部差异 -> Mitigation: 明确将 hierarchical domain 留作后续 change，不在第一版追求局部最优。
- [Risk] 窗口太短导致误判，窗口太长导致响应迟钝 -> Mitigation: 先将窗口长度作为显式配置，并在 benchmark 中单独量化不同窗口参数的 overhead 与收益。
- [Risk] external coordinator 引入额外复杂度 -> Mitigation: 第一版只定义最小职责边界，不在本 change 中引入复杂服务架构。
- [Risk] 只使用窗口均值可能忽略抖动与尾部特征 -> Mitigation: 第一版优先证明最小闭环成立，复杂统计作为后续扩展。
- [Risk] coverage 不完整时长期 hold，导致弱在线几乎不切换 -> Mitigation: 将 hold 视为正确的保守行为；若后续证明过于保守，再单独引入更丰富的聚合机制。
- [Risk] 迟到摘要污染新版本策略 -> Mitigation: coordinator 严格按 `observed_epoch + window_id` 匹配，过期摘要只用于诊断。

## Migration Plan

1. 保持现有 final steady path change 与 weak-online change 分离。
2. 在 OpenSpec 中先固化 weak-online 的最小架构语义，再决定实现顺序。
3. 后续实现时优先确保 tuner 热路径可以只读 committed policy。
4. 在 weak-online 模式不可用或 coordinator 未就绪时，系统应退回 final steady 或 default 行为。
5. 若 weak-online 模式导致异常，可通过关闭相关模式开关回退到已有 steady/final path。

## Open Questions

- communicator-domain 的聚合摘要由谁生成最合适：rank0、进程内代表，还是更显式的 domain aggregator？
- 第一版 `bw_sum` 应优先使用 `algbw` 还是 `busbw`，还是只用 `latency_sum_us` 做主判据？
- recheck 的触发是否只依赖固定 `recheck_after`，还是允许加入有限的 drift signal？
- warmup 与 recheck 是否允许测试不同候选子集，还是必须共享相同候选顺序？
- 第一版 weak-online benchmark 是否只覆盖单节点 allreduce，还是同时覆盖至少一个 allgather / reducescatter 场景？

## Closure Boundary - 2026-04-26

本 change 原先停在“本地 rank 独立裁决 committed policy 不满足 communicator 一致性”这一缺口。该缺口现已由 `cross-rank-coordinator` 子 change 补齐，因此这里记录最终闭环状态。

### 已完成闭环

- tuner 热路径保持为 committed policy 读取、availability 检查和 fallback/default。
- `warmup -> steady -> recheck`、`epoch`、`window_id`、`recheck_after`、最小 `window summary` 和保守切换门槛继续作为 weak-online 的控制骨架。
- communicator-domain shared coordinator 现在负责接收 per-rank summary、由 rank0 representative 聚合裁决并发布唯一 shared committed policy。
- published policy 与 activation boundary 通过显式 `effective_call_index` 分离，避免新 policy 在 communicator 内错位激活。

### 最终验证口径

- `final-steady` 2-rank smoke 已恢复，不再在 warmup 后切换阶段触发 `SIGSEGV`。
- `final-steady` 与 `weak-online` 的 8-rank torch smoke 已验证 communicator 内 policy 激活一致。
- `baseline`、`profiler-only`、`final-steady`、`weak-online` 的 overhead 已重新量化并写入当前 README/验证记录。

### 结论

`minimal-weak-online-closed-loop` 现在不再只是单进程行为骨架，而是依赖 `cross-rank-coordinator` 提供的共享发布路径完成了 communicator-domain 的最小弱在线闭环。
