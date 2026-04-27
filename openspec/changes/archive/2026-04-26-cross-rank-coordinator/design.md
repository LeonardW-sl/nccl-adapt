## Context

当前代码已经具备以下前提：

- weak-online 的 `warmup -> steady -> recheck` 状态机骨架已存在
- tuner 热路径已经收敛为“读 policy -> 校验 availability -> 应用或 fallback”
- profiler/observer 路径已经具备窗口摘要与保守裁决逻辑

最近的回归也暴露了一个更细的实现约束：

- sampled window 若依赖“必须观测到全部 `nChannels` kernel callback 才算完成”，则在 profiler 只拿到部分 kernel coverage 时会直接丢失该 sampled collective
- 一旦 warmup sampled collectives 被静默丢失，window summary 永远无法闭合，代表 rank 也就不会进入 shared publication / activation 链路

因此第一版不只是要避免 rank divergence，也要保证 profiler completion 对 partial / zero kernel coverage 保持保守但可闭合的记账语义。

但真正阻止多 rank 稳定运行的地方很集中：

- 当前 committed policy 仍由每个 rank 进程内独立裁决
- 这些本地裁决的发布时间不同，导致某些 rank 已经开始读取新 policy，另一些 rank 仍停留在旧 policy
- NCCL collective 要求 communicator 内策略兼容，一旦跨 rank 激活边界错位，就会出现 hang、rank 分叉或 `SIGSEGV`

所以这个 change 的核心不是“发明一个更聪明的 policy”，而是建立一个足够保守的 communicator-domain 共享发布协议。

可以把目标抽象成下面这条链路：

```text
local rank samples
  -> submit window summaries
  -> one communicator-domain coordinator adjudicates
  -> publish one shared committed policy
  -> all ranks apply it after the same effective call boundary
```

第一版更具体的形态收敛为：

```text
per-rank process
  profiler completion
    -> write summary slot in shared host state

representative rank
  -> scan shared summary slots
  -> publish one committed policy record
     {epoch, candidate, published_call_index, effective_call_index}

all ranks
  getCollInfo
    -> read published record from shared host state
    -> if not yet effective: hold old policy
    -> else: activate new policy
```

## Goals / Non-Goals

**Goals:**

- 为同一个 communicator-domain 提供一份共享的 committed policy，而不是每个 rank 一份本地 committed policy。
- 明确 rank-local summary submission 与 shared policy publication 的职责边界。
- 定义 `published` 与 `effective` 的最小状态模型，使 policy 可以先发布、后生效。
- 让 tuner 在不引入阻塞等待的前提下，读取共享发布结果并在统一边界激活。
- 将 `final-steady` 和 `weak-online` 的多 rank 验收重新建立在 communicator 一致性之上。

**Non-Goals:**

- 不在本 change 中引入多节点外部服务集群、数据库或复杂控制平面。
- 不在本 change 中引入 per-node / hierarchical coordinator。
- 不在本 change 中扩大候选集合、切换算法或统计模型。
- 不在本 change 中解决 communicator grow/shrink、rank failure recovery 或复杂 fault tolerance。

## Decisions

### 1. 第一版 coordinator 只解决单机多进程 communicator-domain

选择：先把 cross-rank coordinator 限定在单机多进程、同一 communicator 的共享发布问题。

理由：当前 blocker 已经在单机 2-rank / 8-rank 复现。先解决这个最小闭环，才能重新获得 `final-steady` / `weak-online` 的可信验收基础。

替代方案：直接做多节点 coordinator。该方案会立刻引入网络容错、代表选举和远端可见性问题，不适合当前 follow-up。

### 2. communicator-domain 采用“一份共享发布记录 + 每 rank 摘要槽位”的模型

选择：每个 communicator-domain 维护一份共享 committed policy 发布记录，并为各 rank 保留独立摘要/提案槽位。

共享记录至少包括：

- `epoch`
- `candidate`
- `recheck_after`
- `published_call_index`
- `effective_call_index`
- `valid`

每 rank 摘要槽位至少包括：

- `window_id`
- `observed_epoch`
- `candidate`
- `sample_count`
- `latency_sum_us`
- `bw_sum`
- `unavailable`
- `complete`

理由：这能把“谁提交观测”和“谁发布 committed policy”分离开。rank 负责提交自己的窗口结果，coordinator 负责汇总后只发布一份共享结论。

替代方案：让所有 rank 都可以直接写 committed policy。该方案正是当前失败来源。

补充约束：

- 第一版 activation / publication domain 与 policy domain 保持同构，按 `communicator + exact key` 建模。
- 第一版不使用 communicator-global activation clock，也不提前引入 `key-class` / canonicalized domain 合并。
- 后续只有在证明多个 exact key 的 applicability、rank participation 和 drift pattern 足够一致时，才允许升级到更粗的 canonicalized domain。
- 这里的 `exact key` 指第一版可由 profiler 路径与 tuner 热路径共同稳定计算的 tuning key，而不是任意观测字段的逐位完全相等。

第一版字段分层收敛为：

```text
policy domain identity
  = commId
  + collType
  + size bucket
  + nRanks
  + nNodes

observation annotations
  = datatype
  + count decomposition
  + reduce op / root
  + numPipeOps / regBuff

candidate or result state
  = algo / proto / nChannels
  + unavailable / suspect
  + epoch / windowId / callIndex / seq
```

其中：

- `policy domain identity` 参与 shared publication 与 activation boundary。
- `observation annotations` 可以用于观测、诊断和后续 domain refinement，但第一版不进入 activation domain。
- `candidate or result state` 只描述“当前选了什么”或“当前处于哪个时间阶段”，不能反向定义 policy domain。

理由：

- 进入 activation domain 的字段必须同时满足：profiler 与 tuner 两条路径都能稳定计算、显著影响 policy applicability、且不会把 domain 碎到几乎不可收敛。
- 当前代码路径里，`collType + size bucket + nRanks + nNodes` 满足这一条件；`datatype`、`reduce op`、`root` 等字段尚不满足“热路径稳定可得”的前提。

### 3. 采用单一 representative 发布 committed policy，其余 ranks 只提交摘要

选择：为每个 communicator-domain 选定一个 representative rank 负责读取所有 rank 的摘要槽位并发布 committed policy；其他 ranks 只能提交摘要，不能提交新 committed policy。第一版将 representative 固定为 communicator rank0，不做 leader election 或 failover。

理由：只要存在多个 writer 写 committed policy，就必须解决竞争与覆盖顺序。第一版用单 writer 可以显著降低复杂度。

替代方案：

- 多 writer + compare-and-swap。该方案看似无锁，但仍然难以定义跨 rank 的统一激活边界。
- 动态 leader election / helper process。该方案适合更远期控制面，不适合作为当前 single-host first version 的前提。

### 4. 第一版使用 POSIX shared memory 承载共享 coordinator state

选择：第一版 communicator-domain shared state 使用 POSIX shared memory 或等价的单机 process-shared host memory 承载；UDS 不进入 tuner hot path。

理由：

- 当前要共享的是 host-side coordinator metadata，而不是 CUDA device pointer、CUDA event 或 GPU-resident state。
- tuner hot path 需要本地、固定成本、无 request/response 的读取路径；若每次 collective 前都经由 UDS 与 representative 往返，即使逻辑正确，也会把 transport 抖动重新带回热路径。
- `representative + shared memory` 可以自然表达“单 writer 发布、一致 reader 读取”的模型；而 `representative + UDS` 更像控制面/RPC 模型，不直接解决统一激活边界问题。

替代方案：用 UDS 作为唯一 coordinator transport。该方案适合 debug 或将来的独立 helper process，但不适合作为第一版 hot-path publication 机制。

### 5. coordinator 只共享 host metadata，不共享 CUDA objects

选择：cross-rank coordinator 第一版只共享 host-side published policy 和 summary metadata；它 SHALL NOT 依赖 CUDA IPC 来共享 device memory、CUDA event 或其他 GPU object。

理由：

- coordinator 要解决的是 policy publication 与 activation，而不是跨进程共享 GPU 数据。
- 引入 CUDA IPC 会把生命周期、句柄传递和设备可见性复杂度不必要地带入第一版。
- 现有 crash 发生在 collective policy 一致性边界，而不是设备对象跨进程共享缺失。

替代方案：使用 CUDA IPC / VMM 承载 coordinator state。该方案对当前问题过重，且偏离最小 host-side control-plane 目标。

### 6. policy 生效边界必须显式编码为 `effective_call_index`

选择：coordinator 发布 policy 时，不只发布“新 candidate 是谁”，还必须发布“从哪个统一 call boundary 开始生效”。

原因在于 tuner 接口里没有直接可用的 collective sequence number，但当前代码已经有按 key/domain 递增的 deterministic `call_index`。第一版应当把它视为 domain-scoped local eligibility clock，而不是全局同步证明。因此最小安全模型应当是：

```text
publish at call_index = P
effective at call_index = E
where E > P
```

第一版更具体地收敛为：

```text
effective_call_index = published_call_index + activation_lag
where activation_lag is explicit and configurable
```

并进一步固定为：

```text
first-version default activation_lag = 2
first-version activation_lag SHALL NOT be smaller than 2
```

然后所有 ranks 只在以下条件同时成立时才允许激活新 policy：

```text
reader sees one complete publication snapshot
AND local domain_call_index >= effective_call_index
```

理由：这能把“裁决完成”和“允许热路径使用”分成两个阶段，避免某些 rank 提前一两个 collective 切换。

替代方案：

- 发布即生效。该方案正是当前多 rank crash 的根本风险。
- `E = P + 1` 的固定单步延迟。该方案对局部 call drift 过于激进，不适合作为第一版默认模型。
- 直接等待更复杂的稳定窗口边界。该方案更保守，但会显著增加第一版状态机复杂度。

补充理由：

- `P + 2` 为 shared publication 留出了一个完整的 matching-call slack，使所有 ranks 有机会在真正激活前看见同一份完整 publication。
- 相比 `P + 3` 或更大的固定 lag，`P + 2` 对 sparse domain 的响应更快，更符合 weak-online 第一版“先恢复安全、再保留基本响应性”的目标。

### 7. tuner hot path 只允许 direct read，不允许 coordinator round-trip

选择：tuner 在 `getCollInfo` 中只允许 direct read 当前 communicator-domain 的 published policy record；它不能在每次 collective 前向 representative 发起 coordinator round-trip。

理由：

- NCCL collective 和 group ordering 要求各 rank 提交顺序一致，hot path 中的 CPU-side 往返会放大进程间抖动。
- “不阻塞等待”还不够；第一版更保守的边界应该是“热路径不依赖任何 request/response transport”。
- 这与当前架构目标一致：协调发生在热路径外，热路径只读已发布结果。

替代方案：hot path 遇到未知状态时向 representative 发起 UDS 查询。该方案会引入 transport 抖动、故障传播和额外可变延迟。

### 8. coordinator 不可用或覆盖不完整时，一律 hold 当前共享 committed policy

选择：

- 若已有共享 committed policy，则 hold 当前 policy
- 若尚无有效共享 committed policy，则回 default
- 若观察结果的 `epoch` / `window_id` 已过期，则丢弃其对发布路径的影响

### 9. sampled completion 以 host stop 为闭合边界，允许 partial kernel coverage

选择：

- sampled collective 的 completion 以 host-side coll stop 作为“允许最终记账”的必要边界
- 若 profiler 已观测到部分 kernel-channel callback，则只要求“已观测到的 kernel 全部 stop”后即可提交本地 completion
- 若一个 collective 完全没有 kernel-channel callback，则退化为 host-stop timing 记账，而不是静默丢弃该 sampled collective

理由：

- 当前 cross-rank coordinator 的 publication 依赖 warmup / recheck sampled collectives 全部进入 window summary。
- 如果 profiler 因 channel callback coverage 不完整而丢掉 sampled collective，影响不是单个 latency 样本变粗，而是整个 communicator-domain 的 summary / publication 状态机不再前进。
- 对第一版而言，“保守但可闭合的 sampled record”比“等待理想的完整 kernel coverage”更重要，因为 publication safety 已经由 representative aggregation、activation lag 和 hold/default 规则兜底。

替代方案：

- 继续要求 `started == stopped == nChannels`。该方案在 profiler coverage 不完整时会永久丢失 sampled record，不适合作为 cross-rank publication 的前提。
- 没有 kernel callback 就完全跳过记账。该方案会让 warmup / recheck window 在部分环境里永远无法收敛。

理由：在 collective 系统中，保守地“不切换”远比“半数 rank 切换”安全。

替代方案：局部推进、部分切换或本地猜测提交。这些方案都会重新引入 rank divergence。

### 9. `call_index` 只作为本地激活资格时钟，不作为全局同步证明

选择：第一版 shared publication 模型中，`call_index` 只用于判断“本 rank 是否已经越过某个 activation boundary”，不用于证明所有 ranks 已瞬时同步到同一绝对点。

理由：

- `call_index` 本质上是本地、单调、低成本的 domain 进度时钟，适合热路径资格判断。
- 它并不能单独证明所有 ranks 在完全相同的时间观察到了完全相同的 collective 边界。
- 把它降格为 eligibility clock，可以让第一版在不引入更重同步协议的前提下保持保守安全。

替代方案：把 `call_index` 视为 communicator-domain 的全局同步证据。该方案会高估本地计数器的语义，放大局部 drift 风险。

### 10. 第一版优先使用 honest size bucket，而不是 raw-byte exact match

选择：第一版 policy domain 使用 size bucket 作为 message-size 维度，而不是使用 raw `nBytes` 的逐值精确匹配。

理由：

- raw-byte exact match 会让 activation domain 过度碎片化，导致 activation clock 稀疏、窗口覆盖不足、系统长期停留在 hold / warmup。
- 当前实现已经在 profiler 与 tuner 两条路径上稳定计算 size bucket，因此它比额外引入更细粒度字段更诚实。
- 第一版更重要的是“不要把热路径拿不到的字段伪装成 domain identity”，而不是追求观测上的最细分辨率。

替代方案：

- 使用 raw `nBytes` exact match。该方案更细，但很容易让 publication / activation domain 失去收敛性。
- 直接把更复杂的 shape / datatype / op 维度一起并入第一版 domain。该方案会让 domain 身份与当前接口可见性脱节。

第一版进一步固定为 deterministic power-of-two size bucket。

理由：

- 它已经在现有 profiler / tuner 路径里稳定存在。
- 对 first-version shared coordinator 来说，size bucket 的首要职责是提供一个既 honest 又可收敛的 activation domain，而不是逼近每个 raw-byte 点的最优策略。
- 在当前候选空间和 change 目标下，power-of-two bucket 更像一个可接受的 first honest partition。

### 11. shared publication 采用 double-buffer record flip，而不是 seqlock

选择：第一版 shared publication 使用固定大小的双缓冲 published-policy record。writer 始终写入 inactive buffer，完成后再以原子方式翻转 active buffer index；reader 只读取当前 active buffer。

理由：

- 第一版是单 writer、多 reader，double-buffer 足以表达“先写完整记录、后切 active 指针”的 publication 语义。
- 相比 seqlock，double-buffer 更直观，更容易在 spec 和实现里定义“reader 只能从一份完整 record 激活”。
- published policy record 很小，双份存储成本可以接受。

替代方案：

- seqlock-style publication。可行，但 reader 需要围绕 odd/even sequence 重试，概念和实现都更绕。
- coarse mutex around hot-path reads。该方案把锁竞争重新带回 tuner 热路径，不接受。

## Evolution Conditions

以下条件定义了哪些点可以在 first version 之后继续演进：

### A. 何时把 `activation_lag` 从默认值 `2` 提高

仅当验证表明在 `activation_lag = 2` 时仍持续出现“publication 已完成但某些 rank 在下一次允许激活前未稳定观察到该 publication”的现象，才提高默认 lag。

更具体地说，需要同时满足：

- shared publication 机制已正确实现；
- 2-rank / 8-rank communicator smoke 仍观察到与 activation boundary 相关的不稳定；
- 问题归因于 call drift / visibility slack 不足，而不是 stale state、reader consistency 或 representative lifecycle 错误。

### B. 何时把 representative 从固定 rank0 演进成更复杂模型

仅当固定 rank0 明确成为生命周期或可用性瓶颈时，才考虑 leader metadata、helper process 或其他 representative 选择机制。

第一版不因为“未来可能更优雅”而提前引入代表选举。

### C. 何时把 power-of-two size bucket 细化

仅当验证证明同一个 power-of-two bucket 内存在可复现、持续的 policy disagreement 时，才允许细化 bucket。

推荐的 first refinement 是把一个 power-of-two bucket 拆成两个 deterministic sub-buckets，而不是直接退化为 raw-byte exact match。

触发条件收敛为：

- 同一 power-of-two bucket 的 lower/upper sub-range 都积累了足够 summary coverage；
- 两个 sub-range 在至少两个 recheck 周期里持续偏向不同 committed candidates，且差异超过现有切换门槛；
- 该差异在 2-rank / 8-rank 验证中可复现，而不是单次噪声。

2026-04-26 的 8-rank weak-online 验证已经满足这一触发条件：

- `5 MiB` 与 `7 MiB` 都映射到同一个 `4-8 MiB` power-of-two bucket；
- 在 `NCCL_ADAPTIVE_RECHECK_AFTER=8`、`warmup_iters=4`、`measure_iters=72` 的运行中，两个 sub-range 在至少两个 recheck 周期里发布了不同 committed candidates；
- `5 MiB` 的 publish 序列为 `ring/simple -> tree/simple -> ring/simple -> default -> default -> tree/simple`；
- `7 MiB` 的 publish 序列为 `ring/simple -> default -> default -> default -> default -> ring/simple`。

因此，推荐的下一步演进不再是继续保留当前单一 power-of-two bucket，而是把每个 power-of-two bucket 按中点拆成两个 deterministic sub-buckets。对 `4-8 MiB` 而言，推荐的 first refinement 是：

- lower sub-bucket: `[4 MiB, 6 MiB)`
- upper sub-bucket: `[6 MiB, 8 MiB]`

### D. 何时把 double-buffer publication 升级成其他 reader-consistency 机制

仅当 published record 明显变大、active-record flip 无法维持简单读路径，或 validation 证明 double-buffer 无法稳定提供完整快照时，才考虑更复杂的 seqlock 或其他 publication 机制。

## Risks / Trade-offs

- [Risk] shared memory / IPC 生命周期和 communicator 生命周期错位 -> Mitigation: 让 coordinator state 绑定 communicator init/finalize，并加入 generation / validity 字段避免复用脏状态。
- [Risk] representative 成为单点 -> Mitigation: 第一版接受单点模型，但将其限制为单机最小闭环；异常时回 hold/default。
- [Risk] `effective_call_index` 仍可能因为局部 call drift 使用错误 -> Mitigation: 仅在 deterministic window schedule 和 communicator-domain 同步调用假设下启用；若 drift 被检测到则 hold。
- [Risk] exact key domain 过碎，导致 activation clock 稀疏、收敛偏慢 -> Mitigation: 第一版先接受保守行为；后续若数据证明多个 exact key 可安全合并，再考虑 canonicalized key-class。
- [Risk] 当前 size bucket 仍可能过粗，使同一 bucket 内不同消息规模共享了不够相近的 policy -> Mitigation: 第一版先保持 bucket honest 且可收敛；后续再根据验证结果细化 bucket 设计或引入受控 canonicalization。
- [Risk] 共享状态读写把开销重新带回热路径 -> Mitigation: 热路径只读固定大小的 published policy 记录，不做聚合、不做等待。
- [Risk] 单机方案未来不易扩展到多节点 -> Mitigation: 在数据模型上保留 representative / shared publication 语义，后续只替换 transport 层。

## Migration Plan

1. 在现有 weak-online 骨架上引入 communicator-domain 的共享 coordinator state，但先不改变策略判据。
2. 将本地 committed policy 发布逻辑替换为“rank-local summary submission + representative publish”。
3. 在 tuner 侧改为读取共享 published policy，并只在 `effective_call_index` 之后生效。
4. 先恢复 `final-steady` 的 2-rank / 8-rank 稳定性，再继续恢复 `weak-online` 的多 rank 验收。
5. 若新 coordinator 路径不稳定，可通过关闭对应模式回退到 `static` 或 baseline。

## Open Questions

- 如果某个 rank 的摘要槽位长期未完成，是否需要单独的 timeout / suspect 标记，还是直接按 incomplete coverage hold？
- shared memory header 是否还需要额外的 generation / checksum 字段辅助 stale-state 检测，还是 `generation + valid + active-buffer index` 已足够？
- incomplete coverage 的 hold 行为是否需要区分“短暂未齐”和“长期 suspect rank”两种情况？
