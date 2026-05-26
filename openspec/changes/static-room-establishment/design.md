## Scope

本 change 只回答一个前置问题：

```text
在更像样的 static search surface 上，
是否存在真实 static room？
```

这里的 `static room` 分为两层：

- `communication room`
  - candidate 能否让 collective 本身更快
- `workload room`
  - 该收益能否在固定 microstep / workload-level signal 上成立

## Entry Criteria

本 change 默认从当前项目级总纲继承方向：

- 北极星目标仍然是 `same-key phase shift-aware online correction`
- 但本 change 不直接证明 switching
- 它只负责建立是否存在可被切换利用的静态收益空间

本 change 的 proving surface 固定为：

- topology group: `numa1-4gpu`
- collective: `allreduce`
- same-socket 4-GPU / single-node regime

本 change 内不做：

- `numa0-4gpu`
- `cross-8gpu`
- phase-shift drift family
- `weak-online payoff` 验证

## Controlled Candidate Surface

本 change 不把 candidate surface 写死为“当前代码已经枚举的 candidate
列表”，而把它定义为：

```text
deterministic fixed-candidate families
that can be replayed under the same static regime
```

### Axis Types

本 change 必须把被实验的轴分为三类，而不是混写为一个泛化 `surface`。

#### A. Controlled Axes

允许进入本 change 主比较的受控轴：

- fixed candidate identity
- message size
- size bucket

#### B. Observed-Only Axes

这些字段必须被记录，但在 `surface v1` 中不视为主动搜索轴：

- selected algorithm
- selected protocol
- selected channel count
- path signature stability

#### C. Excluded Axes

这些轴在本 change 中明确排除：

- topology change
- world-size change
- same-key phase variant
- interference intensity change
- online switching policy behavior

### Current Surface Realization

当前代码中的固定 candidate 只是 `surface v1` 的一个 realization，而不是
本 change 的上界。

当前 allreduce realization 至少包括：

- `default`
- `ring/simple`
- `tree/simple`
- `ring/ll128`

未来若增加更多 deterministic fixed candidates，仍属于同一 change
内的 `surface v1 expansion`，不需要重定义本 change 的问题边界。

### Two-Stage Expansion

本 change 的 candidate surface 默认采用两段式：

#### Stage 1: Screening

目的：

- 用较少 size 点快速筛选更宽的 fixed candidate family

输出：

- shortlist candidates
- exclusion reasons

#### Stage 2: Confirmation

目的：

- 只对 shortlist candidates 跑完整 size / replicate / dual-layer judgment

输出：

- regime-level room map
- promotion pack

## Static Workload Harness

本 change 不再把 pure communication smoke 当作 workload room 的充分代理。

同时，本 change 也不直接用完整训练 step 作为第一版 proving harness，
因为那会引入过多与 static room 无关的外层变量。

因此本 change 固定使用：

```text
tail-anchored static microstep harness
```

### Purpose

目标是在同一 run family 内同时读取：

- target collective-local signal
- microstep-level outer-loop signal

### Why This Harness

选择该 harness 的原因：

- pure communication smoke 只能说明 collective-local 行为
- 完整训练 step 变量过多，不适合作为 static room 的第一层 proving surface
- static microstep 既包含真实 GPU compute，又保留可解释边界

### Fixed Structure

固定结构如下：

```text
microstep start
  -> fixed compute preamble
  -> target collective
  -> fixed compute epilogue
  -> explicit end boundary
microstep end
```

可视化：

```text
[ compute preamble ][ target collective ][ compute epilogue ][ boundary ]
^                                                               ^
microstep start                                            microstep end
```

### Execution Geometry

为了避免 harness 退化成“纯串行求和”或“不可解释的 host 噪声”，第一版
`tail-anchored static microstep` 应固定为一个可解释的静态执行几何。

推荐几何：

```text
1. blocking compute preamble
2. fixed overlap slab + target collective
3. fixed compute epilogue
4. explicit join boundary
```

可视化：

```text
compute stream:
  [ blocking preamble ][ overlap slab ]------wait------[ epilogue ]

comm stream:
                      [ target collective ]-------------done

control stream:
  start ---------------------------------------------------- end
```

解释：

- `blocking preamble`
  - 先建立一个稳定、固定的计算前置段
- `overlap slab`
  - 在不改变 static regime 的前提下，引入固定的 compute/comm coexistence
- `target collective`
  - 在固定位置启动，不允许在 A 中变成 early/late family
- `epilogue`
  - 在 collective 与 overlap slab 都完成之后，提供固定的尾部计算段
- `explicit join boundary`
  - 用于定义 `microstep end`

这不是 `same-key phase shift`，因为：

- overlap 几何本身在 A 中保持固定
- 不比较 early/late
- 不比较 interference 强弱

它只是一个固定的 static workload shape。

### Preferred Kernel Family

本 change 的 compute preamble / epilogue 不应使用：

- random sleep
- CPU-side wait
- 过短的 pointwise kernels
- 混杂多种难以解释的 kernel family

第一版推荐使用单一、可重复的 dense GPU compute family：

- 优先：dense GEMM / matmul
  - 例如 cuBLAS-backed GEMM
  - 或 framework-backed `matmul` / linear block

选择 dense GEMM / matmul 的原因：

- 更接近训练期常见的 GPU compute 负载
- duration 与 occupancy 更稳定
- 更容易通过矩阵形状调节运行时间
- 比纯 pointwise / elementwise kernels 更不容易被 launch jitter 主导

### Confirmation Promotion Gate

confirmation 阶段的可晋级结果必须来自经过校准的 GEMM / matmul
microstep。

具体规则：

- `workload-confirmed static win` 只允许由 `calibration_mode =
  confirmation-full` 的 GEMM / matmul harness 产出
- 逐元素 / pointwise microstep 只允许用于 sanity、debug 或 screening 辅助
- 若 pointwise microstep 观察到正向信号：
  - 可以记录为 screening signal 或 harness sensitivity note
  - 不得直接产出 `workload-confirmed static win`
  - 不得进入 promotion pack
- 若 confirmation 阶段因为实现限制仍使用 pointwise microstep：
  - 必须记录 `harness sensitivity warning`
  - final judgment 只能作为 bounded exploratory result
  - 不能作为 `same-key-phase-shift-validation` 的入口依据

该门槛的目的不是否认 pointwise 结果的诊断价值，而是防止把过轻的
measurement shape 外推成训练形态下的 workload room。

### Preferred DType Contract

第一版推荐固定以下 dtype 优先级：

1. `bfloat16`
2. `float16`

不推荐第一版直接使用：

- `float32`
- `int8`
- 混合 dtype family

原因：

- `bfloat16` / `float16` 更贴近现代训练期主流 dense compute 形态
- 更容易稳定打到 Tensor Core 路径
- `float32` 更容易把 harness 变成与训练期常态偏离的 compute regime
- `int8` 会引入额外的量化/反量化语义，不利于把 A 保持为最小 static proving surface

一旦某个 harness version 选定 dtype，该 dtype 在同一 change 版本内应保持固定。

### Base GEMM Shape Family

第一版建议使用单一、离散的 square-ish GEMM shape ladder，而不是在每个
regime 内自由选择任意矩阵形状。

推荐 shape ladder：

- `2048 x 2048 x 2048`
- `3072 x 3072 x 3072`
- `4096 x 4096 x 4096`
- `5120 x 5120 x 5120`
- `6144 x 6144 x 6144`
- `7168 x 7168 x 7168`
- `8192 x 8192 x 8192`

约束：

- `M = N = K = D`
- `D` 应保持为 Tensor Core 友好的对齐粒度
  - 推荐为 `128` 的整数倍

选择 square-ish family 的原因：

- 解释最直接
- 更易比较不同 regime 的 calibration 结果
- 避免矩阵长宽比本身成为隐藏变量

### Memory And Allocation Contract

为避免 allocator noise 干扰 microstep：

- GEMM 输入 / 输出 tensor 应在测量前一次性分配
- 同一 regime 内重复复用相同 tensor buffer
- 不允许在每个 microstep 内重新分配工作 tensor
- 不允许把 shape 初始化、随机数据生成、host-to-device copy 混入
  `microstep start`

若某个 shape 在当前设备 / dtype 下超出可接受内存预算：

- 应退回到下一个较小的离散 shape
- 而不是切到另一种 kernel family

### Kernel-Type Contract

#### Compute Preamble

`compute preamble` 建议由同一 kernel family 的两个子段组成：

1. `blocking preamble`
2. `overlap slab`

二者都应使用相同的 dense GEMM / matmul family，只允许：

- 固定矩阵 shape
- 固定 dtype
- 固定 repeat count

不允许：

- 在 candidate 之间切换 kernel family
- 在 replicate 之间切换 shape
- 在 regime 内用不同的 compute shape 伪造“workload room”

#### Compute Epilogue

`compute epilogue` 也应使用相同的 dense GEMM / matmul family。

原因：

- 这样 boundary 附近的工作形态更可解释
- 能避免“前段是 GEMM、尾段是完全不同 kernel family”造成的额外解释自由度

第一版建议：

- `epilogue` 总时长小于 `blocking preamble + overlap slab`
- 但不能短到只剩 launch noise

### Relative Duration Targets

为了让 collective 对 outer-loop signal 既非完全隐藏，也非完全裸露，
建议使用相对时长而不是绝对毫秒写死。

以 `baseline` 下目标 collective 的 steady latency 为参考：

- `blocking preamble`
  - 目标总时长约为 `0.5x - 1.5x` target collective latency
- `overlap slab`
  - 目标总时长约为 `0.5x - 1.5x` target collective latency
- `epilogue`
  - 目标总时长约为 `0.25x - 0.75x` target collective latency

意图：

- `blocking preamble` 提供稳定前置计算背景
- `overlap slab` 让 collective 有固定的静态 compute coexistence
- `epilogue` 让目标 collective 接近尾部，但又不完全等于 boundary

## Calibration Rules

第一版 harness 不应通过人工手调每个 regime 的 compute 工作量。

应按 target collective 的 baseline steady latency 机械标定：

```text
baseline collective latency
  -> choose base GEMM shape
  -> measure unit GEMM latency
  -> derive repeats for each microstep segment
```

### Calibration Input

对每个 confirmation-level regime，先取得：

- `L_coll_base_ms`
  - 该 regime 下 `baseline` target collective 的 steady latency

该值作为整个 microstep compute geometry 的唯一时间标尺。

### Calibration Warmup

在正式测量前，GEMM calibration 至少应：

- 预分配所有 compute tensor
- 执行若干次非记录 warmup
- 只在 warmup 之后测量 unit GEMM latency

目的：

- 避免首次 launch、lazy init、allocator、autotune 初始化污染 calibration

### Unit-GEMM Shape Selection Rule

记：

- `L_unit_gemm_ms(D)`
  - shape `D x D x D` 在选定 dtype 下的 warmed single-GEMM latency

第一版建议先设一个目标单位时长：

```text
L_unit_target_ms = 0.5 * L_coll_base_ms
```

然后从离散 shape ladder 中选择满足下列优先规则的 shape：

1. 首选最小的 `D`
   - 使 `L_unit_gemm_ms(D)` 落入：
     `0.35x - 0.75x` `L_coll_base_ms`
2. 若没有 shape 落入该区间
   - 选择使 `|L_unit_gemm_ms(D) - L_unit_target_ms|` 最小的 shape
3. 若较大 shape 触发内存预算问题
   - 回退到最近的可用较小 shape

这样做的意图是：

- 让单次 GEMM 足够长，不被 launch jitter 主导
- 又不要长到只靠 `repeat=1` 就把整个 microstep 完全压成 compute-bound

### Segment Target Durations

在选定 base shape 后，对每个 regime 固定以下目标段时长：

- `L_block_target_ms = 1.0 * L_coll_base_ms`
- `L_overlap_target_ms = 1.0 * L_coll_base_ms`
- `L_epi_target_ms = 0.5 * L_coll_base_ms`

这对应前文的相对区间中心值。

### Repeat Derivation Rule

记：

- `R_block`
- `R_overlap`
- `R_epi`

第一版推荐使用：

```text
R_block   = max(1, ceil(L_block_target_ms   / L_unit_gemm_ms))
R_overlap = max(1, ceil(L_overlap_target_ms / L_unit_gemm_ms))
R_epi     = max(1, ceil(L_epi_target_ms     / L_unit_gemm_ms))
```

### Preferred Repeat Range

为了避免 harness 落到“shape 太小，全靠大量 repeat 拼时长”的极端，
第一版建议：

- 优选让每个 segment 的 repeat 落在 `1 - 4`
- 若 `R_overlap` 或 `R_block` 超过 `8`
  - 应优先尝试更大的 base shape
- 若最大的可用 shape 仍需要很高 repeat
  - 允许保留高 repeat
  - 但必须在 evidence 中记录为 harness sensitivity warning

### Regime-Local Freeze Rule

一旦某个 regime 的以下参数完成 calibration：

- dtype
- base GEMM shape
- `R_block`
- `R_overlap`
- `R_epi`

这些参数在该 regime 的所有 candidate arms 与 replicate 中都必须冻结。

允许 per-regime calibration。
不允许 per-candidate calibration。

### Screening-Stage Calibration Simplification

为了降低 screening 阶段成本，允许采用简化规则：

- 固定一个全局默认 dtype
- 固定一个全局默认 base shape
- 共享一个 screening-stage warmed unit GEMM latency
- 只按 regime 的 `L_coll_base_ms` 调整 segment repeats

但 confirmation 阶段应回到完整 calibration 规则。

### Stage-Specific Default Policy

#### Screening Defaults

screening 阶段默认使用：

- `calibration_mode = screening-simplified`
- 单一 `screening_dtype`
- 单一 `screening_base_shape`
- 单一 `screening_unit_gemm_ms`

推荐口径：

1. 先固定一组全局 screening default
2. 对 reduced size set 中的每个 regime 测 `baseline` collective latency
3. 仅根据该 regime 的 `L_coll_base_ms` 推导：
   - `R_block`
   - `R_overlap`
   - `R_epi`

screening 的目的不是给每个 regime 找最优 compute shape，而是：

- 快速识别 candidate 是否大致存在 dual-layer signal
- 保持不同 candidate 间的比较地板稳定

#### Confirmation Defaults

confirmation 阶段默认使用：

- `calibration_mode = confirmation-full`
- 固定 change-level dtype
- per-regime base shape selection
- per-regime warmed unit GEMM latency
- per-regime segment repeat derivation

confirmation 的目的不是最小化 calibration 成本，而是：

- 让每个 regime 的 microstep 几何都围绕该 regime 的 collective latency
  标尺被重新对齐
- 让 outer-loop judgment 更可信

### Example Interpretation

若某个 regime 的 baseline collective latency 为：

```text
L_coll_base_ms = 0.80 ms
```

且选中的 warmed unit GEMM latency 为：

```text
L_unit_gemm_ms = 0.42 ms
```

则推荐：

- `L_block_target_ms = 0.80 ms`
- `L_overlap_target_ms = 0.80 ms`
- `L_epi_target_ms = 0.40 ms`

得到：

- `R_block = ceil(0.80 / 0.42) = 2`
- `R_overlap = ceil(0.80 / 0.42) = 2`
- `R_epi = ceil(0.40 / 0.42) = 1`

这会产生一个：

- 前置计算约 `0.84 ms`
- overlap 计算约 `0.84 ms`
- epilogue 约 `0.42 ms`

的固定 static microstep geometry。

## Matrix Manifest Contract

本 change 需要一份显式的 `matrix-manifest` 契约，而不是只把字段散落在
summary schema 中。

该 manifest 的角色是：

- 固定本批实验矩阵的 proving 边界
- 记录每个 regime 的 calibration 冻结状态
- 记录每个 candidate arm 的计划与结果指针
- 提供后续 room judgment 的统一读取入口

第一版建议使用：

```text
one manifest per batch stage
```

即：

- screening 有 screening manifest
- confirmation 有 confirmation manifest

### Manifest Header Fields

manifest 顶层至少应包含：

- `manifest_version`
- `change_name`
- `surface_version`
- `batch_stage`
- `harness_name`
- `harness_version`
- `calibration_mode`
- `generated_at_utc`
- `result_root`
- `topology_group`
- `collective_type`
- `nRanks`
- `nNodes`
- `notes`

这些字段的作用是：

- 确认该 manifest 属于哪一版 proving contract
- 防止后续把不同 batch stage 或不同 harness version 的结果误混

### Stage-Level Calibration Defaults

manifest 顶层应记录当前 batch stage 的全局 calibration 默认值。

screening 阶段至少应记录：

- `screening_dtype`
- `screening_base_shape`
- `screening_unit_gemm_ms`
- `screening_block_target_ratio`
- `screening_overlap_target_ratio`
- `screening_epilogue_target_ratio`
- `screening_repeat_rule`

confirmation 阶段若使用 change-level固定默认值，也应记录：

- `preferred_dtype`
- `shape_ladder`
- `unit_target_ratio`
- `block_target_ratio`
- `overlap_target_ratio`
- `epilogue_target_ratio`
- `repeat_rule`

### Regime Identity Fields

manifest 的 `regimes[]` 中，每个 regime entry 至少应包含：

- `regime_id`
- `stage_regime_status`
  - 例如 `planned` / `shortlisted` / `confirmed` / `excluded`
- `communicator_domain`
- `collective_type`
- `message_bytes`
- `message_mb`
- `size_bucket_lower`
- `size_bucket_upper`
- `topology_group`
- `nRanks`
- `nNodes`
- `cross_socket`
- `replicate_count`
- `summary_root`

这些字段的作用是：

- 让 regime 成为后续 A/B/C 共享的稳定单位
- 让 same-key 入口与静态 proving surface 一致

### Harness Calibration Fields

每个 `regime` entry 至少应包含：

- `calibration_mode`
- `preferred_dtype`
- `base_gemm_shape`
- `unit_gemm_latency_ms`
- `block_target_ms`
- `overlap_target_ms`
- `epilogue_target_ms`
- `R_block`
- `R_overlap`
- `R_epi`
- `calibration_warmup_iters`
- `tensor_reuse_policy`
- `calibration_warning`

screening 与 confirmation 的差异应通过这些字段显式体现：

- screening
  - `base_gemm_shape` 可以是 stage-shared value
  - `unit_gemm_latency_ms` 可以是 stage-shared value
- confirmation
  - `base_gemm_shape` 通常是 per-regime value
  - `unit_gemm_latency_ms` 通常是 per-regime value

### Candidate-Arm Fields

每个 `regime` entry 中的 `arms[]` 至少应包含：

- `arm_id`
- `arm_name`
- `arm_kind`
  - 例如 `baseline` / `profiler-only` / `fixed-static`
- `requested_candidate`
- `requested_algorithm`
- `requested_protocol`
- `requested_channel_policy`
- `candidate_source`
- `planned_in_stage`
- `availability_expected`
- `run_root`
- `summary_artifact`
- `trajectory_artifact`

补充结果字段：

- `candidate_available`
- `observed_dominant_path`
- `path_relation_to_baseline`
- `host_fallback_count`
- `unavailable_count`

### Boundary Event Fields

每个 `regime` entry 至少应包含 boundary contract：

- `stream_geometry`
- `launch_order_version`
- `boundary_name`
- `start_event_name`
- `collective_start_event_name`
- `collective_done_event_name`
- `overlap_done_event_name`
- `epilogue_done_event_name`
- `end_event_name`
- `microstep_time_definition`
- `boundary_tail_definition`
- `boundary_anchor_window_definition`
- `transfer_ratio_definition`

若结果文件允许按 arm 汇总 boundary 数值，则每个 `arm` 还应补充：

- `microstep_time_ms`
- `microstep_device_elapsed_ms`
- `boundary_tail_ms`
- `boundary_anchor_window_ms`
- `boundary_anchor_ratio`

### Judgment Summary Fields

每个 `arm` 的 summary 字段至少应包含：

- `communication_delta_vs_baseline_pct`
- `workload_delta_vs_baseline_pct`
- `transfer_ratio`
- `communication_replicate_vote`
- `workload_replicate_vote`
- `communication_judgment`
- `workload_judgment`
- `anomaly_flags`
- `failure_reason`

每个 `regime` 的 summary 字段至少应包含：

- `best_candidate`
- `contender_set`
- `regime_final_judgment`
- `promotion_status`
- `promotion_reason`
- `bounded_conclusion`

### Manifest Reading Rule

后续任何读取 `Change A` room map 的消费者，应优先读取：

1. `manifest header`
2. `regime identity`
3. `harness calibration fields`
4. `candidate-arm fields`
5. `judgment summary fields`

只有这样，后续才不会把：

- 不同 calibration mode
- 不同 harness geometry
- 不同 surface version

误读为同一种证据。

### JSON-Like Manifest Skeleton

为了让后续实现几乎可以直接照着落，第一版建议把 manifest 组织为：

```text
manifest
  -> header
  -> stage_calibration_defaults
  -> regimes[]
       -> calibration
       -> boundary_contract
       -> arms[]
            -> artifacts
            -> boundary_metrics
            -> judgment_summary
       -> regime_summary
```

确认阶段的 JSON-like skeleton 示例：

```json
{
  "manifest_version": "1",
  "change_name": "static-room-establishment",
  "surface_version": "v1",
  "batch_stage": "confirmation",
  "harness_name": "tail-anchored-static-microstep",
  "harness_version": "v1",
  "calibration_mode": "confirmation-full",
  "generated_at_utc": "2026-05-13T00:00:00Z",
  "result_root": "experiments/static-room-establishment/2026-05-13-confirmation",
  "topology_group": "numa1-4gpu",
  "collective_type": "allreduce",
  "nRanks": 4,
  "nNodes": 1,
  "notes": [
    "numa1-4gpu only",
    "same-socket 4-GPU confirmation batch"
  ],
  "stage_calibration_defaults": {
    "preferred_dtype": "bfloat16",
    "shape_ladder": [2048, 3072, 4096, 5120, 6144, 7168, 8192],
    "unit_target_ratio": 0.5,
    "block_target_ratio": 1.0,
    "overlap_target_ratio": 1.0,
    "epilogue_target_ratio": 0.5,
    "repeat_rule": "ceil(target_ms / unit_gemm_latency_ms)",
    "tensor_reuse_policy": "preallocate-and-reuse"
  },
  "regimes": [
    {
      "regime_id": "numa1-4gpu/allreduce/8m/r4n1",
      "stage_regime_status": "confirmed",
      "communicator_domain": "comm-domain-0001",
      "collective_type": "allreduce",
      "message_bytes": 8388608,
      "message_mb": 8,
      "size_bucket_lower": 4194304,
      "size_bucket_upper": 8388608,
      "topology_group": "numa1-4gpu",
      "nRanks": 4,
      "nNodes": 1,
      "cross_socket": false,
      "replicate_count": 3,
      "summary_root": "phase-confirmation/numa1-4gpu/8m",
      "calibration": {
        "calibration_mode": "confirmation-full",
        "preferred_dtype": "bfloat16",
        "base_gemm_shape": 4096,
        "unit_gemm_latency_ms": 0.42,
        "block_target_ms": 0.80,
        "overlap_target_ms": 0.80,
        "epilogue_target_ms": 0.40,
        "R_block": 2,
        "R_overlap": 2,
        "R_epi": 1,
        "calibration_warmup_iters": 8,
        "tensor_reuse_policy": "preallocate-and-reuse",
        "calibration_warning": null
      },
      "boundary_contract": {
        "stream_geometry": {
          "compute_stream": "compute_stream",
          "comm_stream": "comm_stream",
          "control_stream": "control_stream"
        },
        "launch_order_version": "v1",
        "boundary_name": "microstep-join-boundary",
        "start_event_name": "microstep_start_event",
        "collective_start_event_name": "collective_start_event",
        "collective_done_event_name": "collective_done_event",
        "overlap_done_event_name": "overlap_slab_done_event",
        "epilogue_done_event_name": "epilogue_done_event",
        "end_event_name": "microstep_end_event",
        "microstep_time_definition": "host wait on microstep_end_event minus host timestamp after microstep_start_event",
        "boundary_tail_definition": "elapsed(collective_done_event, microstep_end_event)",
        "boundary_anchor_window_definition": "elapsed(collective_start_event, microstep_end_event)",
        "transfer_ratio_definition": "workload_delta_vs_baseline_pct / communication_delta_vs_baseline_pct"
      },
      "arms": [
        {
          "arm_id": "baseline",
          "arm_name": "baseline",
          "arm_kind": "baseline",
          "requested_candidate": "default",
          "requested_algorithm": null,
          "requested_protocol": null,
          "requested_channel_policy": null,
          "candidate_source": "nccl-default",
          "planned_in_stage": true,
          "availability_expected": true,
          "artifacts": {
            "run_root": "phase-confirmation/numa1-4gpu/8m/baseline",
            "summary_artifact": "comparison-summary.json",
            "trajectory_artifact": "trajectory.json"
          },
          "candidate_available": true,
          "observed_dominant_path": "RING/SIMPLE/4ch",
          "path_relation_to_baseline": "self",
          "host_fallback_count": 0,
          "unavailable_count": 0,
          "boundary_metrics": {
            "microstep_time_ms": 2.41,
            "microstep_device_elapsed_ms": 2.36,
            "boundary_tail_ms": 0.59,
            "boundary_anchor_window_ms": 1.34,
            "boundary_anchor_ratio": 0.60
          },
          "judgment_summary": {
            "communication_delta_vs_baseline_pct": 0.0,
            "workload_delta_vs_baseline_pct": 0.0,
            "transfer_ratio": 1.0,
            "communication_replicate_vote": "baseline-reference",
            "workload_replicate_vote": "baseline-reference",
            "communication_judgment": "baseline-floor",
            "workload_judgment": "baseline-floor",
            "anomaly_flags": [],
            "failure_reason": null
          }
        },
        {
          "arm_id": "profiler-only",
          "arm_name": "profiler-only",
          "arm_kind": "profiler-only",
          "requested_candidate": "default",
          "requested_algorithm": null,
          "requested_protocol": null,
          "requested_channel_policy": null,
          "candidate_source": "profiler-diagnostic",
          "planned_in_stage": true,
          "availability_expected": true,
          "artifacts": {
            "run_root": "phase-confirmation/numa1-4gpu/8m/profiler-only",
            "summary_artifact": "comparison-summary.json",
            "trajectory_artifact": "trajectory.json"
          },
          "candidate_available": true,
          "observed_dominant_path": "RING/SIMPLE/4ch",
          "path_relation_to_baseline": "same-dominant-path",
          "host_fallback_count": 12,
          "unavailable_count": 0,
          "boundary_metrics": {
            "microstep_time_ms": 2.45,
            "microstep_device_elapsed_ms": 2.39,
            "boundary_tail_ms": 0.61,
            "boundary_anchor_window_ms": 1.36,
            "boundary_anchor_ratio": 0.59
          },
          "judgment_summary": {
            "communication_delta_vs_baseline_pct": -0.8,
            "workload_delta_vs_baseline_pct": -1.4,
            "transfer_ratio": 1.75,
            "communication_replicate_vote": "1/3 improved",
            "workload_replicate_vote": "0/3 improved",
            "communication_judgment": "diagnostic-only",
            "workload_judgment": "diagnostic-only",
            "anomaly_flags": [],
            "failure_reason": "observation-tax-reference"
          }
        },
        {
          "arm_id": "static-ring-simple",
          "arm_name": "static:ring/simple",
          "arm_kind": "fixed-static",
          "requested_candidate": "ring/simple",
          "requested_algorithm": "RING",
          "requested_protocol": "SIMPLE",
          "requested_channel_policy": "default-channel-policy",
          "candidate_source": "surface-v1-realization",
          "planned_in_stage": true,
          "availability_expected": true,
          "artifacts": {
            "run_root": "phase-confirmation/numa1-4gpu/8m/static-ring-simple",
            "summary_artifact": "comparison-summary.json",
            "trajectory_artifact": "trajectory.json"
          },
          "candidate_available": true,
          "observed_dominant_path": "RING/SIMPLE/4ch",
          "path_relation_to_baseline": "same-dominant-path",
          "host_fallback_count": 8,
          "unavailable_count": 0,
          "boundary_metrics": {
            "microstep_time_ms": 2.38,
            "microstep_device_elapsed_ms": 2.33,
            "boundary_tail_ms": 0.55,
            "boundary_anchor_window_ms": 1.29,
            "boundary_anchor_ratio": 0.58
          },
          "judgment_summary": {
            "communication_delta_vs_baseline_pct": 3.2,
            "workload_delta_vs_baseline_pct": 1.3,
            "transfer_ratio": 0.41,
            "communication_replicate_vote": "3/3 improved",
            "workload_replicate_vote": "2/3 improved",
            "communication_judgment": "communication-positive",
            "workload_judgment": "workload-positive",
            "anomaly_flags": [],
            "failure_reason": null
          }
        }
      ],
      "regime_summary": {
        "best_candidate": "ring/simple",
        "contender_set": ["ring/simple", "tree/simple"],
        "regime_final_judgment": "workload-confirmed static win",
        "promotion_status": "eligible",
        "promotion_reason": "confirmed dual-layer positive signal on current controlled surface version",
        "bounded_conclusion": "workload-confirmed static win on surface-v1 confirmation regime numa1-4gpu/allreduce/8m/r4n1"
      }
    }
  ]
}
```

补充规则：

- screening manifest 允许把 `stage_calibration_defaults` 作为主 calibration
  来源，并让各 regime 仅覆盖：
  - `L_coll_base_ms`
  - `R_block`
  - `R_overlap`
  - `R_epi`
- confirmation manifest 应优先把 calibration 冻结值写在各自的
  `regime.calibration` 中
- 所有 `arms[]` 的 artifact 指针都应保持相对同一 `result_root` 可解析
  的稳定路径

## Boundary Definition

本 change 的 `microstep` 必须使用显式 GPU-event join boundary，而不是
模糊的“某次 torch op 之后就算结束”。

### Boundary Streams

建议固定三类 stream：

- `compute_stream`
- `comm_stream`
- `control_stream`

其中：

- `compute_stream`
  - 承载 preamble / overlap slab / epilogue compute
- `comm_stream`
  - 承载 target collective
- `control_stream`
  - 只用于记录 start / end boundary，不承载业务 kernel

### Start Boundary

`microstep start` 定义为：

- warmup 完成后
- 本次测量 microstep 的第一个 GPU work launch 之前
- 在 `control_stream` 上记录的 `microstep_start_event`

要求：

- 该 start event 必须位于所有被测 GPU work 之前
- start boundary 不得混入 tensor allocation、shape 初始化或数据装载

### End Boundary

`microstep end` 定义为：

- `epilogue_done_event` 之后
- `control_stream` 明确等待所有 microstep 内的必须完成事件
- 再记录 `microstep_end_event`

host 侧只允许在 `microstep_end_event` 上等待，
而不允许用未定义的全局同步替代 boundary。

### Event Contract

第一版建议最少记录这些 event：

- `microstep_start_event`
- `blocking_preamble_done_event`
- `collective_start_event`
- `collective_done_event`
- `overlap_slab_done_event`
- `epilogue_done_event`
- `microstep_end_event`

即使第一版摘要不全部对外暴露，原始结果也应允许重建这些边界。

## Fixed Launch Order

第一版建议固定如下 launch / wait 顺序：

1. 在 `control_stream` 记录 `microstep_start_event`
2. `compute_stream` 等待 `microstep_start_event`
3. 在 `compute_stream` 上发射 `blocking preamble`
4. 记录 `blocking_preamble_done_event`
5. `comm_stream` 等待 `blocking_preamble_done_event`
6. 在 `compute_stream` 上发射固定 `overlap slab`
7. 在 `comm_stream` 上发射 target collective，并记录：
   - `collective_start_event`
   - `collective_done_event`
8. 在 `compute_stream` 上记录 `overlap_slab_done_event`
9. `compute_stream` 等待：
   - `collective_done_event`
   - `overlap_slab_done_event`
10. 在 `compute_stream` 上发射固定 `epilogue`
11. 记录 `epilogue_done_event`
12. `control_stream` 等待 `epilogue_done_event`
13. 记录 `microstep_end_event`

这个顺序的意图是：

- 保持 target collective 在每次 microstep 中的固定位置
- 保持固定的 overlap 几何
- 让 end boundary 始终代表“这次 microstep 真正完成”

### Allowed To Vary

在本 change 中，允许变化的主变量只有：

- fixed static candidate
- target message size
- replicate id

### Not Allowed To Vary

在本 change 中，下列因素必须保持固定：

- compute preamble shape
- target collective position
- compute epilogue shape
- end boundary definition
- topology group
- world size
- interference level
- phase variant
- stream geometry
- launch order
- boundary event placement

### Why Serial-Only Is Not Enough

若 harness 只是：

```text
compute -> collective -> compute
```

且全部在单 stream 串行执行，那么 collective-local gain 会过于容易直接转成
microstep gain。

那样会使：

- `communication-only win`
- `step-positive / comm-nonpositive anomaly`

都难以被真实暴露。

因此第一版 harness 应保留一个固定的 `overlap slab`，但不允许把它变成
可变 phase family。

## Regime Plan

### Stage 1: Screening Regimes

screening 阶段建议只使用少量 size 点，例如：

- `1 MiB`
- `4 MiB`
- `16 MiB`

其作用是：

- 尽量扩 fixed candidate family
- 降低矩阵成本
- 快速识别哪些 candidates 值得进入 confirmation

### Stage 2: Confirmation Regimes

confirmation 阶段建议使用更完整 size 集：

- `1 MiB`
- `2 MiB`
- `4 MiB`
- `8 MiB`
- `16 MiB`
- `32 MiB`
- `64 MiB`

默认 replicate 口径：

- `3`

默认正向证据阈值：

- aggregate 改善达到 `2.0%`
- 且至少 `2/3` replicate 同方向

## Mandatory Arms

本 change 的主比较对象应是 deterministic fixed-candidate arms，而不是
`final-steady` / `weak-online`。

confirmation 阶段的最低主比较臂应包含：

- `baseline`
- `profiler-only`
- 每个 shortlisted fixed static candidate

补充说明：

- `profiler-only` 的作用是识别 observation tax
- `final-steady` / `weak-online` 可以作为 continuity diagnostics
- 但不应作为 `static room` 主判定的核心 arms

## Evaluation Model

### Layer A: Communication-Room Probe

目标：

- 在同一 static regime 下比较 `baseline` 与 fixed non-default candidates

主要指标：

- target collective steady latency
- algorithmic bandwidth
- bus bandwidth
- selected path observability

### Layer B: Workload-Room Confirmation

目标：

- 检查 communication-side win 是否仍能在 static microstep 边界上成立

主要指标：

- `microstep_time_ms`
- boundary tail proxy
- workload-level judgment boundary

### Primary Outer-Loop Metric

`microstep_time_ms` 的推荐定义是：

- host-side wall time
- 起点为 `microstep_start_event` 之后立刻开始的测量窗口
- 终点为 host 对 `microstep_end_event` 完成等待的时刻

补充记录：

- `microstep_device_elapsed_ms`
  - 即 `microstep_start_event -> microstep_end_event` 的 device elapsed time

解释：

- host-side wall time 更接近 workload 感知到的 step / microstep 完成时间
- device elapsed time 则用于分离 host launch jitter

二者若长期显著背离，应视为 harness 质量警报。

### Required Classification

每个 confirmation 级 regime 最终都必须被分类为：

- `no proven communication room`
- `communication-only win`
- `workload-confirmed static win`

## Judgment Rules

### Candidate-Level Communication Judgment

某个 non-default candidate 只有在下列条件同时成立时，才允许记为
`communication-positive`：

- 相对 `baseline` 的 target collective 主指标改善达到 `2.0%`
- 至少 `2/3` replicate 保持同方向改善
- candidate 在该 regime 下可用

主判据：

- target collective steady latency

辅判据：

- `algbw`
- `busbw`
- observed selected path signature

否则记为：

```text
communication not proven
```

### Candidate-Level Workload Judgment

某个 candidate 只有在已经 `communication-positive` 的前提下，才允许进入
workload room 正向判断。

若该 candidate 同时满足：

- `microstep_time_ms` 相对 `baseline` 改善达到 `2.0%`
- 至少 `2/3` replicate 保持同方向改善

则记为：

```text
workload-positive
```

若通信侧赢，但 workload-level signal 不赢，则记为：

```text
communication-only win
```

### Regime-Level Final Classification

对同一 regime：

- 若没有任何 candidate 满足 `communication-positive`
  - 该 regime 记为：
    `no proven communication room`
- 若至少一个 candidate 满足 `communication-positive`，但没有 candidate
  满足 `workload-positive`
  - 该 regime 记为：
    `communication-only win`
- 若至少一个 candidate 同时满足 `communication-positive` 与
  `workload-positive`
  - 该 regime 记为：
    `workload-confirmed static win`

### Availability And Path Rules

必须显式记录并解释：

- candidate unavailable
- requested candidate 与 observed path 不一致
- path-equivalent to baseline
- host-fallback-heavy observations

这些现象必须进入 failure / interpretation 字段，而不能被无声合并进均值。

### Workload Anomaly Flag

若出现：

- collective-local 不赢
- 但 `microstep_time_ms` 赢

则不把它升级为主分类的第四类，而是记录为：

```text
step-positive / comm-nonpositive anomaly
```

这类结果说明：

- target collective-local latency 不是 workload outcome 的充分解释
- 但当前证据还不足以把它记成标准 `communication room` 正例

## Boundary Tail Proxy Definition

`boundary tail proxy` 不应是模糊术语，第一版应至少固定一个主定义和一个
派生解释量。

### Primary Tail Proxy

定义：

```text
boundary_tail_ms
  = elapsed(collective_done_event, microstep_end_event)
```

含义：

- 目标 collective 完成之后，到整个 microstep 边界结束之间，
  还剩多少必经工作

解释：

- `boundary_tail_ms` 越小
  - target collective 越接近 microstep 尾部
- `boundary_tail_ms` 越大
  - collective 的一部分收益越可能被后续工作稀释

### Secondary Anchoring Proxy

定义：

```text
boundary_anchor_window_ms
  = elapsed(collective_start_event, microstep_end_event)
```

含义：

- 从 target collective 开始，到 microstep 真正结束，这段尾部窗口有多长

解释：

- 若该窗口主要由 collective 构成，则 collective 更像 boundary-dominant
  对象
- 若该窗口大部分是 collective 之后的工作，则 collective-local gain
  更可能被部分隐藏

### Derived Anchoring Ratio

可派生记录：

```text
boundary_anchor_ratio
  = target_collective_latency_ms
    / boundary_anchor_window_ms
```

读法：

- 越接近 `1.0`
  - collective 越接近边界主导项
- 越明显小于 `1.0`
  - collective 后仍有较多固定尾部工作

### Transfer Interpretation Metric

跨 arm 总结时，建议派生：

```text
transfer_ratio
  = microstep_delta_vs_baseline
    / collective_delta_vs_baseline
```

用途：

- 解释 collective gain 有多少真正转移到 outer loop

读法：

- 接近 `1`
  - collective gain 大部分转成 microstep gain
- 明显小于 `1`
  - 存在隐藏或稀释
- 小于等于 `0`
  - 可能是 `communication-only win`
    或 `step-positive / comm-nonpositive anomaly`

## Unified Recording Schema

本 change 的实验必须至少记录：

### Static Regime

- `change_name`
- `surface_version`
- `batch_stage`
- `harness_name`
- harness dtype
- base GEMM shape
- unit GEMM latency
- `R_block`
- `R_overlap`
- `R_epi`
- communicator-domain
- collective type
- message size bytes / MiB
- size bucket lower / upper
- topology group
- `nRanks`
- `nNodes`
- cross-socket
- replicate id

### Arm And Candidate

- arm name
- arm kind
- requested candidate
- requested algorithm
- requested protocol
- requested channel policy
- candidate source
- candidate available
- availability reason

### Inner-Loop Communication Signal

- target collective latency
- algorithmic bandwidth
- bus bandwidth
- selected algorithm
- selected protocol
- channel count
- dominant path signature
- parsable record count
- host fallback count
- unavailable count

### Outer-Loop Workload Signal

- microstep time
- microstep device elapsed time
- boundary tail proxy
- boundary anchor window
- boundary anchor ratio
- explicit boundary name
- boundary start event
- boundary end event
- collective start event
- collective done event
- blocking preamble done event
- overlap slab done event
- epilogue done event
- target collective position label
- workload-level judgment boundary

### Forward-Compatible Phase Fields

即使在本 change 中恒为空，也应保留字段位：

- drift family
- phase variant
- control variable
- interference intensity

### Summary And Judgment

- delta vs `baseline` on communication signal
- delta vs `baseline` on workload signal
- transfer ratio
- replicate vote on communication signal
- replicate vote on workload signal
- path relation to baseline
- communication judgment
- workload judgment
- anomaly flags
- failure reason
- best candidate in regime
- contender set
- eligible for `same-key-phase-shift-validation`

## Matrix-Manifest Field Mapping

为了避免 `matrix-manifest` 与 summary schema 漂移，第一版建议建立一个
固定映射：

- regime identity fields
  -> 归入 manifest `regimes[]`
- harness calibration fields
  -> 归入 manifest `regimes[]`
- candidate-arm fields
  -> 归入 manifest `regimes[].arms[]`
- boundary event fields
  -> 归入 manifest `regimes[]` 与 `regimes[].arms[]`
- judgment summary fields
  -> 归入 manifest `regimes[].arms[]` 与 `regimes[]`

也就是说：

```text
manifest
  -> regime
    -> arms
```

应成为本 change 默认的数据组织形态。

## Completion Conditions

本 change 完成时必须产出：

1. 一份 `surface v1 statement`
2. 一份 screening 摘要
3. 一份 confirmation 级 candidate judgment 摘要
4. 一份 confirmation 级 regime judgment 摘要
5. 一份可晋级到 phase-shift validation 的 promotion pack
6. 一份 bounded negative conclusion
7. 一份 `evidence.md`

## Exit Artifact

本 change 的 exit artifact 应至少回答：

- 哪些 candidate 在哪些 regime 上有 `communication-positive`
- 哪些 regime 只有 `communication-only win`
- 哪些 regime 有 `workload-confirmed static win`
- 哪些 regime 可以进入 `same-key-phase-shift-validation`
- 每个晋级 regime 的 static comparison floor 是什么
- 哪些负结论只适用于 `current controlled surface version`

## Promotion Contract To Change B

只有满足下列条件的 regime 才允许晋级到
`same-key-phase-shift-validation`：

- 该 regime 被判为 `workload-confirmed static win`
- 其 same-key tuple 可被固定表达
- 其 static comparison floor 已明确
- 其 contender set 已明确

promotion pack 至少应包含：

- same-key tuple
- best confirmed static candidate
- contender set
- workload-level supporting signal
- bounded conclusion text
