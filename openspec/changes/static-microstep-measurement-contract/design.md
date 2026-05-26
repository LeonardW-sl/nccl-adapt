## Scope

本 change 只建立 measurement layer，不建立 static room claim。

它回答的问题是：

```text
我们是否已经有一套可解释、可观测、可复用的
static microstep measurement contract，
供后续 static-room-establishment 使用？
```

它不回答：

```text
static room 是否已经存在？
```

## 中文阅读约定

本文档涉及脚本模式名和结果字段名时，仍保留原始拼写，便于和代码、
日志、JSON 对齐。但解释问题时，优先使用下面的中文含义：

| 原始名字 | 中文名字 | 含义 |
| --- | --- | --- |
| `measurement contract` | 测量约定 | 规定怎么测、测什么、结果长什么样、什么情况算测量可用 |
| `baseline` | 默认对照组 | 不加载观察器和调参器，只作为原始耗时参照 |
| `fixed-static` | 固定策略组 | 明确要求走一条非默认通信路径，并检查实际是否走到 |
| `profiler-only` | 只观察组 | 只打开观察器，不改变通信策略，用于诊断默认策略和观察开销 |
| `tail-anchored static microstep` | 尾部锚定小步 | 一个固定小工作单元，把目标通信放在可解释的尾部边界里 |
| `requested path` | 请求路径 | 实验要求通信走的路径 |
| `observed path` | 实际路径 | 观察器记录到通信实际走的路径 |
| `readiness summary` | 测量就绪总结 | 说明这套测量约定是否已经能交给下游使用 |

核心阅读原则：

- 第一项变更只是在立“尺子”，不是在证明“收益”。
- 第二项变更才用这把尺子判断是否存在固定策略收益。
- 如果第一项失败，结论是“测量层未解决”，不是“没有证明收益”。

## Naming

本 change 采用：

```text
static-microstep-measurement-contract
```

原因：

- `static`
  - 它服务于 downstream 的 static room 验证
- `microstep`
  - 它的核心 proving object 是 tail-anchored static microstep harness
- `measurement-contract`
  - 它冻结的是 arm semantics、boundary、schema、manifest 和 interpretation
  - 它不声称 room 已被建立

若将名字写成 `static-room-*`，会继续模糊 measurement layer 与 room claim。

## Why This Must Be A Separate Change

这里真正变化的不是工作量，而是主张类型。

`static-room-establishment` 当前同时承担了两层含义：

1. measurement layer 该如何定义
2. room 是否在该 layer 上成立

这种耦合会让负结论失去解释力。

当结果为负时，至少存在两种不同解释：

- `no proven room under an already-stable measurement contract`
- `measurement contract itself is still unsettled`

如果这两者不拆开，那么后续任何 `no proven room` 都会带着歧义。

这在当前仓库里已经是现实问题，而不是抽象担忧：

- 现有 `phase1-summary.json` 已经输出 `no proven headroom`
- 但当前主 harness 仍是 pure communication smoke
- 当前 baseline 也没有 selected-path observability

因此，新的前置 change 必须先冻结 measurement contract，
再允许 `static-room-establishment` 去做 room judgment。

## Current Reality

### A. Baseline Is Not Path-Observable

当前 `baseline` 的真实语义是：

- profiler off
- tuner off
- 纯 NCCL 默认策略

它的优点：

- observation tax 最低
- 适合作为纯 latency reference

它的限制：

- 没有 selected-path observability
- 不能直接回答默认策略到底选了什么 path

因此，本 change 禁止把 `baseline` 误写成“可观测默认路径”。

### B. Profiler-Only Already Supports Default-Path Diagnostics

当前 `profiler-only` 的真实语义是：

- profiler on
- tuner off
- 仍然走 NCCL default strategy

它已经可以记录：

- `candidate`
- `selectedAlgo`
- `selectedProto`
- `nChannels`
- attach / fallback / partial coverage diagnostics

因此，本 change 不需要把它提升成核心主判据，
但应该把它保留为：

```text
可选诊断臂
```

也就是说：

- 当问题被收窄成“fixed strategy 是否稳定快于 baseline”时
- `baseline` path 不是必答题
- `profiler-only` 只在需要解释默认策略大概在干什么时才启用

### C. Current Harness Is Still A Smoke Harness

当前 harness 仍然是：

```text
float32 all_reduce + synchronize
```

它只提供 iteration latency。

它还没有提供：

- `microstep_time_ms`
- `microstep_device_elapsed_ms`
- `boundary_tail_ms`
- 显式 GPU-event join boundary
- 可解释的 compute / comm / join geometry

因此，它不足以承担 future room map 的 workload-level contract。

### D. Requested / Observed Path Recording Is Not Greenfield

当 profiler 打开时，现有 plugin 已经能记录：

- requested candidate
- observed selected algorithm / protocol / channel count

所以本 change 的目标不是“发明 observability”，
而是把已有能力收敛成稳定 contract。

### E. Ambiguous Negative Conclusions Are The Main Risk

如果 measurement layer 与 room claim 不拆开，
则最终负结论无法区分：

- room genuinely not proven
- path observability still incomplete
- boundary semantics still not frozen
- outer-loop metric still not trustworthy

因此，本 change 的 primary risk model 不是“少做一点实验”，
而是“过早用未冻结 measurement layer 做 room judgment”。

## Arms

本 change 将 arms 分成两类：

- 核心 arms
- 可选诊断 arm

当前脚本中的 mode 名称只是 realization label，
不是 contract 名称本身。

中文分组如下：

| 中文组别 | 对应 contract 名称 | 当前脚本模式 | 是否阻塞本 change 完成 |
| --- | --- | --- | --- |
| 默认对照组 | `baseline` | `baseline` | 是 |
| 固定策略组 | `fixed-static` | `static-replay` | 是 |
| 只观察组 | `profiler-only` | `profiler-only` | 否，除非本次验证明确要求解释默认路径 |
 
判断边界：

- 默认对照组只作为耗时参照，不能解释默认策略实际路径。
- 固定策略组负责验证“请求路径与实际路径”。
- 只观察组只能补充诊断信息，不应升级成核心通过条件。

### 1. `baseline`（core）

定义：

- profiler off
- tuner off
- 不请求 non-default candidate
- 使用纯 NCCL 默认策略

角色：

- latency reference arm
- pure baseline for:
  - communication-local elapsed time
  - microstep-level elapsed time

它必须输出：

- communication-local timing
- microstep-level timing
- boundary metrics

它不得声称：

- selected path observable
- default path signature known

因此在 schema 中：

- path fields 必须为 `null`、`unobservable` 或等价显式状态
- 不能伪造 `path_relation_to_baseline`

### 2. `fixed-static`（core）

定义：

- profiler on
- tuner on
- 请求 deterministic fixed candidate
- 不进行 online switching

current realization 可以使用 `static-replay`，
但 contract 名称统一为 `fixed-static`。

角色：

- requested vs observed path contract validation arm
- non-default static path replay arm

它必须输出：

- requested candidate
- requested algorithm / protocol / channel policy
- observed path
- availability / fallback / mismatch diagnostics
- communication-local timing
- microstep-level timing

在本 change 中，它的职责不是证明 room，
而是证明 contract 至少可以稳定表达：

- “我请求了什么”
- “实际观测到了什么”
- “这个 non-default arm 的性能是否可与 baseline 做同口径比较”

### 3. `profiler-only`（diagnostic-only）

定义：

- profiler on
- tuner off
- 仍然走默认策略

角色：

- 可选诊断臂
- 默认策略行为解释代理
- observation tax 估计来源

它可以输出：

- selected-path observability
- completion diagnostics
- profiler tax 读数

但它不是本 change 的核心 proving obligation。

也就是说：

- 没有它，本 change 仍然可以成立
- 只有在需要解释默认策略行为时，才应强制读取它

## Reference Rules

本 change 的主 reference 只有一条：

### Performance Reference Arm

latency delta 的 reference arm 固定为：

```text
baseline
```

适用字段：

- communication-local delta
- microstep-level delta

### Requested-Vs-Observed Rule

对 non-default 主比较，真正必须成立的是：

- `fixed-static` 请求了什么
- `fixed-static` 实际跑到了什么
- 这个 arm 的性能是否稳定快于 `baseline`

因此 requested / observed 一致性检查只强制绑定到：

```text
fixed-static
```

而不强制绑定到 `baseline`。

### Optional Diagnostic Rule

若运行 `profiler-only`，则允许额外记录：

- 默认策略大概走了什么 path
- profiler 税有多大

但这只属于解释层，不属于最小主判据。

### Forbidden Ambiguity

本 change 禁止使用含糊字段：

- `path_relation_to_baseline`

原因：

- baseline 本身不可观测

最小 contract 下，应优先替代为：

- `requested_vs_observed_relation`
- `latency_relation_to_baseline`

若运行了诊断臂，才允许补充：

- `path_relation_to_profiled_default`

这样可以避免把 baseline 性能 reference 与默认路径解释问题绑死在一起。

## Minimal Proving Surface

本 change 的 proving surface 必须先收窄到一个 anchor regime。

### Anchor Regime V1

- topology group: `numa1-4gpu`
- collective: `allreduce`
- message size: `8 MiB`
- `nRanks=4`
- `nNodes=1`
- shorthand: `r4n1`

推荐 regime id：

```text
numa1-4gpu:allreduce:8MiB:r4n1
```

### Why So Narrow

这是 measurement contract change，不是 room map change。

它的 first obligation 不是回答：

```text
哪些 size 有 room？
```

而是回答：

```text
在一个低歧义 regime 里，
contract 能否被完整、稳定地表达？
```

因此第一版不应该一开始就铺成 size matrix。

### Fixed Candidate For Anchor Validation

第一版 anchor validation 至少需要一个 deterministic fixed candidate。

当前 preferred realization：

- `ring/simple`

原因：

- 当前代码已经支持
- 当前结果中已有 requested / observed path 的先验
- 它足够验证 contract 是否能表达 fixed-static arm

### 第一版边界

第一版只允许验证一个最小对象：

```text
一号处理器域四张 GPU
  + 单机四进程
  + 8 MiB allreduce
  + 默认对照组
  + 固定策略组 ring/simple
  + 可选只观察组
```

第一版必须排除：

- 多消息尺寸矩阵
- 多候选策略筛选
- 其他处理器域或跨处理器域拓扑
- 固定策略收益结论
- 在线切换收益结论
- 完整训练步收益结论

如果第一版需要额外运行 `profiler-only`，它的作用只限于解释默认策略和估计观察开销。
它不改变本 change 的核心问题：

```text
默认对照组和固定策略组，是否能在同一测量约定下稳定产出可比结果？
```

## Tail-Anchored Static Microstep Harness

### Purpose

本 harness 的任务不是拟真完整训练 step，
而是在一个固定、可解释的 outer-loop geometry 中同时读取：

- communication-local signal
- microstep-level signal

### Fixed Structure

固定结构：

```text
microstep start
  -> fixed compute preamble
  -> target collective
  -> fixed overlap slab
  -> fixed compute epilogue
  -> explicit join boundary
microstep end
```

第一版必须是：

```text
tail-anchored static microstep
```

其核心不是“做很多 compute”，
而是“把 target collective 放进一个可解释的尾部边界几何中”。

中文结构固定为：

```text
小步开始
  -> 固定前置计算
  -> 目标通信
  -> 固定重叠计算
  -> 固定尾部计算
  -> 明确结束边界
小步结束
```

第一版必须在实现前明确一件事：

- 若能够真实使用三条设备流，则以三条设备流作为正式测量约定。
- 若只能在 PyTorch 层表达近似结构，则结果必须标记为“测量层未解决”或“部分就绪”，
  不得直接交给 `static-room-establishment` 当作已冻结测量约定。

### Stream Geometry

第一版固定三类 stream：

- `control_stream`
- `compute_stream`
- `comm_stream`

职责：

- `control_stream`
  - 只负责 start / end boundary events
- `compute_stream`
  - 承载 preamble / overlap slab / epilogue
- `comm_stream`
  - 承载 target collective

### Boundary Events

第一版最少需要这些 event：

- `microstep_start_event`
- `blocking_preamble_done_event`
- `collective_start_event`
- `collective_done_event`
- `overlap_slab_done_event`
- `epilogue_done_event`
- `microstep_end_event`

### Launch Order

推荐固定如下顺序：

1. `control_stream` 记录 `microstep_start_event`
2. `compute_stream` 等待 `microstep_start_event`
3. `compute_stream` 发射 blocking preamble
4. 记录 `blocking_preamble_done_event`
5. `comm_stream` 等待 `blocking_preamble_done_event`
6. `compute_stream` 发射固定 overlap slab
7. `comm_stream` 发射 target collective，并记录：
   - `collective_start_event`
   - `collective_done_event`
8. `compute_stream` 记录 `overlap_slab_done_event`
9. `compute_stream` 等待：
   - `collective_done_event`
   - `overlap_slab_done_event`
10. `compute_stream` 发射 fixed epilogue
11. 记录 `epilogue_done_event`
12. `control_stream` 等待 `epilogue_done_event`
13. `control_stream` 记录 `microstep_end_event`

### Boundary Definitions

`microstep start` 定义为：

- warmup 后
- 第一个被测 GPU work launch 之前
- 在 `control_stream` 上记录的 `microstep_start_event`

`microstep end` 定义为：

- 所有 microstep 必经工作完成之后
- `control_stream` 等待完成后记录的 `microstep_end_event`

host 侧只允许等待：

- `microstep_end_event`

不得用：

- 全局 `torch.cuda.synchronize()`
- 未绑定 boundary 的模糊 host sync

### Communication-Local Metrics

本 change 将 communication-local signal 正式纳入 harness contract。

第一版至少记录：

- `collective_device_elapsed_ms`
  - `elapsed(collective_start_event, collective_done_event)`
- `collective_algbw_gbps`
- `collective_busbw_gbps`

对 profiler-enabled arms，允许补充：

- profiler-derived collective latency
- selected path observability

但 contract 的最低 communication-local timing 不应只依赖 profiler。

### Microstep-Level Metrics

第一版 outer-loop metrics 至少包括：

- `microstep_time_ms`
  - host-side wall time
  - 从记录完 `microstep_start_event` 之后开始
  - 到 host 等待 `microstep_end_event` 完成为止
- `microstep_device_elapsed_ms`
  - `elapsed(microstep_start_event, microstep_end_event)`
- `boundary_tail_ms`
  - `elapsed(collective_done_event, microstep_end_event)`
- `boundary_anchor_window_ms`
  - `elapsed(collective_start_event, microstep_end_event)`

可选派生量：

- `boundary_anchor_ratio`
- `transfer_ratio`

### 指标主次

第一版的指标解释顺序固定为：

| 中文指标 | 字段名 | 角色 |
| --- | --- | --- |
| 通信本身耗时 | `collective_device_elapsed_ms` | 通信局部主指标 |
| 设备侧小步耗时 | `microstep_device_elapsed_ms` | 小步整体主指标 |
| 主机侧小步耗时 | `microstep_time_ms` | 辅助指标，用于观察主机侧等待和外层开销 |
| 尾部剩余耗时 | `boundary_tail_ms` | 解释目标通信结束后还剩多少必经工作 |
| 尾部锚定窗口 | `boundary_anchor_window_ms` | 解释目标通信开始到小步结束的窗口长度 |

本 change 只要求这些字段能稳定产出并且含义清楚。
它不使用这些字段判断固定策略是否有收益。

### Boundary Interpretation

`boundary_tail_ms` 的含义：

- collective 完成后，到 microstep 真正结束之间还剩多少必经工作

它是 tail anchoring 的核心解释量。

本 change 只要求把它定义清楚并稳定记录，
不要求在本 change 中用它证明 room。

### Allowed To Vary

在 anchor validation 内，只允许变化：

- arm identity
- replicate id

### Not Allowed To Vary

在 anchor validation 内，不允许变化：

- topology group
- collective type
- message size
- stream geometry
- launch order
- boundary event placement
- compute preamble family
- overlap slab family
- epilogue family

## Result Schema And Manifest Contract

本 change 需要的是 measurement contract summary，
不是 room map summary。

### Batch Manifest Shape

第一版建议：

```text
one manifest per contract-validation batch
```

manifest 顶层至少包含：

- `manifest_version`
- `change_name`
- `contract_version`
- `batch_stage`
  - 推荐：`anchor-validation`
- `harness_name`
- `harness_version`
- `arm_taxonomy_version`
- `latency_reference_arm`
  - `baseline`
- `diagnostic_arms_optional`
  - 例如 `profiler-only`
- `generated_at_utc`
- `result_root`
- `notes`

### Proving Regime Fields

manifest 顶层还应显式记录 proving regime：

- `topology_group`
- `collective_type`
- `message_bytes`
- `message_mb`
- `nRanks`
- `nNodes`
- `cross_socket`
- `proving_regime_id`

### Regime Entry

`regimes[]` 中每个 entry 至少包含：

- `regime_id`
- `regime_status`
  - `planned`
  - `validated`
  - `contract-incomplete`
- `summary_root`
- `stream_geometry`
- `launch_order_version`
- `boundary_contract`

### Boundary Contract Fields

每个 regime entry 至少包含：

- `start_event_name`
- `collective_start_event_name`
- `collective_done_event_name`
- `overlap_done_event_name`
- `epilogue_done_event_name`
- `end_event_name`
- `microstep_time_definition`
- `microstep_device_elapsed_definition`
- `collective_device_elapsed_definition`
- `boundary_tail_definition`
- `boundary_anchor_window_definition`

### Arm Fields

每个 `arms[]` entry 至少包含：

- `arm_id`
- `arm_name`
- `arm_kind`
  - `baseline`
  - `fixed-static`
  - `diagnostic-profiler`
- `realization_label`
  - 例如 `baseline` / `profiler-only` / `static-replay`
- `profiler_enabled`
- `tuner_enabled`
- `requested_candidate`
- `requested_algorithm`
- `requested_protocol`
- `requested_channel_policy`
- `run_root`
- `summary_artifact`

### Measurement Fields

每个 arm 必须可承载：

- `collective_device_elapsed_ms`
- `collective_algbw_gbps`
- `collective_busbw_gbps`
- `microstep_time_ms`
- `microstep_device_elapsed_ms`
- `boundary_tail_ms`
- `boundary_anchor_window_ms`

### Observability Fields

对 `fixed-static`，必须可承载：

- `observed_candidate_set`
- `observed_selected_algo_set`
- `observed_selected_proto_set`
- `observed_nchannels_set`
- `observed_dominant_path`
- `host_fallback_count`
- `partial_record_count`
- `unavailable_count`

对 `diagnostic-profiler`，这些字段若存在则应同样可承载，
但不构成本 change 的最小完成门槛。

对 `baseline`，这些字段必须显式标为：

- `unobservable`
- `null`
- 或等价的 contract-safe sentinel

中文结论必须写清楚：

```text
默认对照组路径不可观测。
```

不得写成：

```text
默认对照组实际走了某某路径。
```

如果需要解释默认策略大概走了什么路径，只能使用只观察组的诊断结果。

### Requested Vs Observed Fields

`fixed-static` arm 至少应记录：

- `requested_path_signature`
- `observed_dominant_path`
- `requested_vs_observed_relation`

建议 `requested_vs_observed_relation` taxonomy：

- `matched`
- `matched-with-channel-drift`
- `fallback-to-default`
- `unavailable`
- `partial-observation`
- `unknown`

中文判定如下：

| 判定 | 含义 |
| --- | --- |
| `matched` | 请求路径和实际路径一致 |
| `matched-with-channel-drift` | 算法和协议一致，但通道数不同 |
| `fallback-to-default` | 没有走到请求路径，回到默认行为 |
| `unavailable` | 请求路径在当前场景不可用 |
| `partial-observation` | 观察记录不完整，不能确认 |
| `unknown` | 信息不足，无法判断 |

固定策略组只有在请求路径与实际路径至少达到可解释状态时，
才算完成本 change 的路径验证责任。若结果是 `partial-observation` 或
`unknown`，本 change 可以记录性能值，但测量就绪状态不能直接写成 `ready`。

若运行 `diagnostic-profiler`，允许补充：

- `path_relation_to_profiled_default`

建议其 taxonomy：

- `same-dominant-path`
- `different-dominant-path`
- `unknown`

### Delta Rules

本 change 允许记录 delta，但禁止把 delta 升级成 room judgment。

允许的 delta：

- `communication_delta_vs_baseline_pct`
- `microstep_delta_vs_baseline_pct`

若运行 `diagnostic-profiler`，允许补充：

- `profiler_tax_vs_baseline_pct`

禁止的 regime 级字段：

- `regime_final_judgment = communication-only win`
- `regime_final_judgment = workload-confirmed static win`

在本 change 中，这些结论还没有资格出现。

中文禁止口径：

- 不得写“通信层收益成立”。
- 不得写“小步层收益成立”。
- 不得写“没有证明收益”。
- 不得把某个固定策略更快解释为本 change 的成功结论。

允许写：

- 默认对照组耗时是多少。
- 固定策略组耗时是多少。
- 固定策略组相对默认对照组快或慢多少。
- 请求路径与实际路径是否一致。
- 测量约定是否已经就绪。

### Contract Readiness Fields

本 change 的 regime summary 应改为 readiness summary，而不是 room summary。

每个 regime entry 至少包含：

- `communication_signal_ready`
- `microstep_signal_ready`
- `baseline_reference_ready`
- `fixed_static_comparison_ready`
- `requested_vs_observed_ready`
- `default_path_diagnostic_ready`
- `measurement_contract_status`
  - `ready`
  - `partial`
  - `blocked`
- `failure_reasons`

中文结论只允许三类：

| 字段值 | 中文结论 | 含义 |
| --- | --- | --- |
| `ready` | 测量就绪 | 核心测量字段、默认对照组、固定策略组、路径验证都可用 |
| `partial` | 部分就绪 | 核心耗时可用，但诊断或路径验证仍有缺口 |
| `blocked` | 测量阻塞 | 核心测量字段或核心对照无法可信产出 |

如果状态不是 `ready`，下游 `static-room-establishment` 不得输出
`no proven room`。它必须先继承这里的状态，写成：

```text
measurement-layer unresolved
```

### JSON-Like Skeleton

```json
{
  "change_name": "static-microstep-measurement-contract",
  "contract_version": "v1",
  "batch_stage": "anchor-validation",
  "latency_reference_arm": "baseline",
  "diagnostic_arms_optional": ["profiler-only"],
  "proving_regime_id": "numa1-4gpu:allreduce:8MiB:r4n1",
  "regimes": [
    {
      "regime_id": "numa1-4gpu:allreduce:8MiB:r4n1",
      "regime_status": "validated",
      "boundary_contract": {
        "start_event_name": "microstep_start_event",
        "collective_start_event_name": "collective_start_event",
        "collective_done_event_name": "collective_done_event",
        "end_event_name": "microstep_end_event",
        "microstep_time_definition": "host wait on microstep_end_event",
        "microstep_device_elapsed_definition": "elapsed(start,end)",
        "collective_device_elapsed_definition": "elapsed(collective_start,collective_done)",
        "boundary_tail_definition": "elapsed(collective_done,end)"
      },
      "arms": [
        {
          "arm_id": "baseline",
          "arm_kind": "baseline",
          "realization_label": "baseline",
          "profiler_enabled": false,
          "tuner_enabled": false,
          "requested_candidate": "default",
          "observed_dominant_path": null,
          "measurements": {
            "collective_device_elapsed_ms": 0.0,
            "microstep_time_ms": 0.0,
            "microstep_device_elapsed_ms": 0.0,
            "boundary_tail_ms": 0.0
          }
        },
        {
          "arm_id": "profiler-only",
          "arm_kind": "diagnostic-profiler",
          "realization_label": "profiler-only",
          "profiler_enabled": true,
          "tuner_enabled": false,
          "requested_candidate": "default",
          "observed_dominant_path": "RING/SIMPLE/4ch"
        },
        {
          "arm_id": "fixed-static-ring-simple",
          "arm_kind": "fixed-static",
          "realization_label": "static-replay",
          "profiler_enabled": true,
          "tuner_enabled": true,
          "requested_candidate": "ring/simple",
          "observed_dominant_path": "RING/SIMPLE/4ch",
          "requested_vs_observed_relation": "matched"
        }
      ],
      "summary": {
        "communication_signal_ready": true,
        "microstep_signal_ready": true,
        "baseline_reference_ready": true,
        "fixed_static_comparison_ready": true,
        "requested_vs_observed_ready": true,
        "default_path_diagnostic_ready": true,
        "measurement_contract_status": "ready",
        "failure_reasons": []
      }
    }
  ]
}
```

## Exit Artifact

本 change 的 exit artifact 应该是：

```text
measurement contract validation summary
```

而不是：

```text
static room map
```

它至少要回答：

- `baseline` 是否仍然是纯 latency reference
- `fixed-static` 是否能稳定表达 requested vs observed path
- `fixed-static` 是否能与 `baseline` 做稳定同口径比较
- tail-anchored static microstep boundary 是否已经冻结
- communication-local 与 microstep-level signal 是否能在同一 run family 中共存
- 若运行了 `profiler-only`，默认策略大概在干什么，以及 profiler 税有多大

## Dependency Contract For `static-room-establishment`

`static-room-establishment` 在逻辑上应改为依赖本 change。

### What It Inherits

它必须继承：

- `baseline / fixed-static` core arm semantics
- `profiler-only` optional diagnostic semantics
- `baseline` 作为唯一性能 reference 的规则
- tail-anchored static microstep harness definition
- boundary event contract
- result schema / manifest contract

### What It May Add

在依赖本 change 之后，它可以新增：

- screening / confirmation matrix
- multi-size regime expansion
- candidate shortlist logic
- room judgments：
  - `no proven communication room`
  - `communication-only win`
  - `workload-confirmed static win`

### What It Must Not Re-Own

它不应再重新定义：

- baseline 是否可观测
- microstep boundary 是什么
- requested vs observed taxonomy
- room negative conclusion 与 measurement failure 的边界

若 downstream 需要默认路径解释，
可以消费 `profiler-only` diagnostics，
但不应把它重新抬升成 room judgment 的前置硬门槛。

### Negative Conclusion Rule

如果本 change 的 contract readiness 尚未完成，
downstream change 不得把结果写成：

```text
no proven room
```

而必须先写成：

```text
measurement-layer unresolved
```

只有 measurement contract 已冻结后，
`static-room-establishment` 才有资格把负结论解释为 room-side negative。

## Non-Goals

- 不在本 change 中证明 static room
- 不在本 change 中决定 shortlist candidate family
- 不在本 change 中铺开 same-key phase shift
- 不在本 change 中评估 weak-online payoff
- 不在本 change 中进入完整训练 step proving

## Completion Conditions

本 change 完成时至少满足：

1. `baseline` 被明确标记为 path-unobservable latency reference
2. `fixed-static` 被明确标记为 requested-vs-observed validation arm
3. `profiler-only` 被明确降级为 optional diagnostic arm
4. tail-anchored static microstep harness 的 boundary、stream geometry、launch order 被冻结
5. communication-local 与 microstep-level 字段被统一纳入 schema
6. exit artifact 使用 readiness status，而不是 room judgment
7. `static-room-establishment` 的下游依赖边界被明确写出

补充完成条件：

8. 文档必须用中文解释默认对照组、固定策略组、只观察组的作用。
9. anchor validation 必须固定为 `numa1-4gpu:allreduce:8MiB:r4n1`。
10. 固定策略组第一版只要求验证 `ring/simple` 这一条请求路径。
11. 只观察组不得成为最小完成门槛，除非本次验证明确声明需要默认路径诊断。
12. 若三条设备流或明确结束边界无法稳定表达，结论必须写成
    `measurement-layer unresolved`。
13. 结果不得出现 `communication-only win`、`workload-confirmed static win`
    或 `no proven room`。
