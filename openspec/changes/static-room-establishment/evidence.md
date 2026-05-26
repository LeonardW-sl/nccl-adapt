# Static Room Establishment Evidence

## Bounded Claim

- Claim:
  - 第一层产出当前受控范围内的固定方案空间图，而不是承诺一定出现正例。
- Bound:
  - 结论只绑定到 `numa1-4gpu`、`allreduce`、单机四进程、当前已实现固定候选集合，以及本次冻结的小步测量口径。
- Controlled surface version:
  - `surface-v1-current`

## Pre-Run Judgment Contract

- Primary judgment:
  - 相对干净默认对照的净收益。
- Default communication-positive threshold:
  - `2.0%`
- Default workload-positive threshold:
  - `2.0%`
- Replicate vote:
  - 至少三次重复中的两次同方向。
- Aggregation rule:
  - 每个 arm 先按 replicate 汇总出该 replicate 的主指标均值。
  - aggregate 改善率使用所有 comparable replicates 的主指标均值再求整体改善率。
  - communication 主指标为 `collective_device_elapsed_ms`。
  - workload 主指标为 `microstep_time_ms`。
  - 只有 aggregate 改善达到阈值且 replicate vote 达到 `2/3` 时，才允许记为正向。
- Positive promotion rule:
  - 只有 `workload-confirmed static win` 可以进入下一层阶段变化验证。
- Negative wording:
  - 若没有正例，必须写成 `no proven room on current controlled surface version`。
- Baseline path rule:
  - 默认对照组只作为耗时地板，不声明实际通信路径。
- Diagnostic path rule:
  - 只观察组只能作为路径和观察开销诊断，不替代主判定。
- Confirmation promotion gate:
  - 只有 `calibration_mode=confirmation-full` 且 compute family 为 GEMM / matmul 的结果，才允许产出可晋级的 `workload-confirmed static win`。
- Pointwise promotion policy:
  - pointwise / 逐元素小步结果只能作为 sanity、debug 或 screening 辅助。
  - 若 confirmation 阶段仍使用 pointwise / 逐元素小步，必须记录 `harness sensitivity warning`。
  - pointwise / 逐元素小步不得进入 promotion pack。
- Screening size set:
  - `1 MiB`
  - `4 MiB`
  - `16 MiB`
- Confirmation size set:
  - `1 MiB`
  - `2 MiB`
  - `4 MiB`
  - `8 MiB`
  - `16 MiB`
  - `32 MiB`
  - `64 MiB`
- Confirmation replicate count:
  - `3`
- Candidate set for current surface realization:
  - `baseline`
  - `profiler-only`
  - `ring/simple`
  - `tree/simple`
  - `ring/ll128`
- GEMM dtype priority:
  - 首选 `bfloat16`；不可用时使用 `float16`。
- GEMM shape ladder:
  - `2048`
  - `3072`
  - `4096`
  - `5120`
  - `6144`
  - `7168`
  - `8192`
- GEMM repeat derivation:
  - `R_block = max(1, ceil((1.0 * L_coll_base_ms) / L_unit_gemm_ms))`
  - `R_overlap = max(1, ceil((1.0 * L_coll_base_ms) / L_unit_gemm_ms))`
  - `R_epi = max(1, ceil((0.5 * L_coll_base_ms) / L_unit_gemm_ms))`
- Calibration freeze rule:
  - `dtype`、base GEMM shape、`L_unit_gemm_ms`、`R_block`、`R_overlap`、`R_epi` 在同一 regime 的所有 candidate arms 与 replicates 之间冻结。
  - 允许 per-regime calibration，不允许 per-candidate calibration。

## Surface Statement

### Surface V1 Boundary

- Surface version:
  - `surface-v1-current`
- Topology group:
  - `numa1-4gpu`
- Collective:
  - `allreduce`
- Process shape:
  - single-node, four local ranks
- Placement:
  - same-socket 4-GPU placement, `CUDA_VISIBLE_DEVICES=4,5,6,7`
  - CPU affinity `32-63,96-127`
  - NUMA node `1`
- Comparison style:
  - deterministic fixed-candidate replay against a clean `baseline` floor
- Out-of-scope for this surface:
  - `numa0-4gpu`
  - `cross-8gpu`
  - same-key phase variants
  - online switching policy behavior
  - weak-online payoff claims

### Controlled Axes

- fixed candidate identity
- message size
- size bucket

### Observed-Only Axes

- selected algorithm
- selected protocol
- selected channel count
- path signature stability
- host fallback / parser quality diagnostics

### Excluded Axes

- topology change
- world-size change
- same-key phase variant
- interference intensity change
- online switching policy behavior

### Current Realization

- Current implemented fixed candidates:
  - `ring/simple`
  - `tree/simple`
  - `ring/ll128`
- Current diagnostic arm:
  - `profiler-only`
- Current baseline arm:
  - `baseline`
- Surface interpretation:
  - 若本轮没有扩展更多固定候选方案，所有结论必须绑定到当前已实现候选集合。

### Screening Candidate Plan

- Screening candidate family:
  - deterministic fixed non-default candidates replayable under the same static regime.
- Current screening candidates:
  - `ring/simple`
  - `tree/simple`
  - `ring/ll128`
- Excluded from current screening realization:
  - dynamic `final-steady` learned candidates, because they are policy outputs rather than fixed candidate identities.
  - `weak-online`, because it introduces online switching behavior.
  - topology- or world-size-specific variants outside `numa1-4gpu`.
- Future deterministic fixed candidates can be added inside this surface without redefining the proving boundary, but must be recorded with candidate source, availability, and exclusion reason.

## Harness Definition

- Harness name:
  - `tail-anchored-static-microstep`
- Harness version:
  - `v1`
- Stream geometry:
  - `control_stream`: records start/end boundary events only.
  - `compute_stream`: runs blocking preamble, overlap slab, and epilogue compute.
  - `comm_stream`: runs the target `allreduce`.
- Launch order:
  - `control_stream` records `microstep_start_event`.
  - `compute_stream` waits for `microstep_start_event`, runs blocking preamble, then records `blocking_preamble_done_event`.
  - `comm_stream` waits for `blocking_preamble_done_event`, records `collective_start_event`, launches target `allreduce`, then records `collective_done_event`.
  - `compute_stream` launches the fixed overlap slab after the blocking preamble, then records `overlap_slab_done_event`.
  - `compute_stream` waits for both `collective_done_event` and `overlap_slab_done_event`, runs epilogue compute, then records `epilogue_done_event`.
  - `control_stream` waits for `epilogue_done_event`, then records `microstep_end_event`.
- Boundary definition:
  - `microstep_time_ms` is host wall time from immediately after `microstep_start_event` is recorded until the host wait on `microstep_end_event` completes.
  - `microstep_device_elapsed_ms` is CUDA event elapsed time from `microstep_start_event` to `microstep_end_event`.
  - `boundary_tail_ms` is CUDA event elapsed time from `collective_done_event` to `microstep_end_event`.
  - `boundary_anchor_window_ms` is CUDA event elapsed time from `collective_start_event` to `microstep_end_event`.
- Fixed compute preamble:
  - blocking dense GEMM / matmul segment with frozen dtype, base shape, and `R_block`.
- Fixed overlap slab:
  - dense GEMM / matmul segment with the same dtype and base shape, repeated `R_overlap` times.
- Target collective:
  - one `allreduce` on the measurement tensor, launched at a fixed point after `blocking_preamble_done_event`.
- Fixed compute epilogue:
  - dense GEMM / matmul segment with the same dtype and base shape, repeated `R_epi` times after both the collective and overlap slab complete.
- Preferred kernel family:
  - confirmation 阶段使用固定形状 dense GEMM / matmul。
  - pointwise / 逐元素 compute 只允许作为 screening、sanity 或 debug 辅助。
- Preferred dtype:
  - 首选 `bfloat16`；不可用时使用 `float16`。
- Base GEMM shape ladder:
  - `2048`、`3072`、`4096`、`5120`、`6144`、`7168`、`8192`
- Selected base GEMM shape:
  - per-regime confirmation calibration 后冻结。
- Warmed unit GEMM latency:
  - per-regime confirmation calibration 后记录为 `unit_gemm_latency_ms`。
- Relative duration targets:
  - 前置计算约 `1.0x` 默认通信耗时；重叠计算约 `1.0x` 默认通信耗时；尾部计算约 `0.5x` 默认通信耗时。
- Segment repeats:
  - `R_block = max(1, ceil((1.0 * L_coll_base_ms) / L_unit_gemm_ms))`
  - `R_overlap = max(1, ceil((1.0 * L_coll_base_ms) / L_unit_gemm_ms))`
  - `R_epi = max(1, ceil((0.5 * L_coll_base_ms) / L_unit_gemm_ms))`
- Screening calibration mode:
  - `screening-simplified`
  - one stage-level dtype, base GEMM shape, and warmed unit GEMM latency.
  - per-regime repeats still derive from that regime's `baseline` `collective_device_elapsed_ms`.
- Confirmation calibration mode:
  - `confirmation-full`
  - per-regime dtype availability check, shape selection, warmed unit GEMM latency, and repeat derivation.
  - calibration values freeze across all candidate arms and all replicates for that regime.
- Allowed-to-vary fields:
  - 固定候选方案、消息大小、重复编号。
- Fixed fields:
  - 拓扑、进程形状、通信类型、小步边界、计算形态、候选方案内的计算校准参数。

### Harness Sensitivity Rule

- 若 confirmation 阶段仍使用轻量逐元素计算，而不是固定形状矩阵计算：
  - 必须记录 `harness sensitivity warning`
  - 不得把该结果外推成训练形态下的强结论
  - 不得产出可晋级的 `workload-confirmed static win`
  - 不得进入 `same-key-phase-shift-validation` 的 promotion pack

## Matrix Manifest

### Manifest Header

- `manifest_version`:
  - `1`
- `change_name`:
  - `static-room-establishment`
- `surface_version`:
  - `surface-v1-current`
- `batch_stage`:
  - `screening` or `confirmation`
- `harness_name`:
  - `tail-anchored-static-microstep`
- `harness_version`:
  - `v1`
- `calibration_mode`:
  - `screening-simplified` or `confirmation-full`
- `generated_at_utc`:
  - generated per batch in UTC.
- `result_root`:
  - `experiments/static-room-establishment/<RUN_LABEL>/<stage>`
- `topology_group`:
  - `numa1-4gpu`
- `collective_type`:
  - `allreduce`
- `nRanks`:
  - `4`
- `nNodes`:
  - `1`
- `notes`:
  - stage-local notes, including exclusions and any harness sensitivity warning.

### Stage-Level Calibration Defaults

- Screening:
  - `screening_dtype`
  - `screening_base_shape`
  - `screening_unit_gemm_ms`
  - `screening_block_target_ratio = 1.0`
  - `screening_overlap_target_ratio = 1.0`
  - `screening_epilogue_target_ratio = 0.5`
  - `screening_repeat_rule = ceil(target_ms / unit_gemm_latency_ms)`
- Confirmation:
  - `preferred_dtype = bfloat16`
  - `fallback_dtype = float16`
  - `shape_ladder = [2048, 3072, 4096, 5120, 6144, 7168, 8192]`
  - `unit_target_ratio = 0.5`
  - `block_target_ratio = 1.0`
  - `overlap_target_ratio = 1.0`
  - `epilogue_target_ratio = 0.5`
  - `repeat_rule = ceil(target_ms / unit_gemm_latency_ms)`
  - `tensor_reuse_policy = preallocate-and-reuse`

### Required Regime Fields

- `regime_id`
- `stage_regime_status`
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
- `calibration`
- `boundary_contract`
- `arms`
- `regime_summary`

### Required Arm Fields

- `arm_id`
- `arm_name`
- `arm_kind`
- `requested_candidate`
- `requested_algorithm`
- `requested_protocol`
- `requested_channel_policy`
- `candidate_source`
- `planned_in_stage`
- `availability_expected`
- `artifacts`
- `candidate_available`
- `observed_dominant_path`
- `path_relation_to_baseline`
- `host_fallback_count`
- `unavailable_count`
- `boundary_metrics`
- `judgment_summary`

### Required Judgment Fields

- `communication_delta_vs_baseline_pct`
- `workload_delta_vs_baseline_pct`
- `transfer_ratio`
- `communication_replicate_vote`
- `workload_replicate_vote`
- `communication_judgment`
- `workload_judgment`
- `anomaly_flags`
- `failure_reason`
- `best_candidate`
- `contender_set`
- `regime_final_judgment`
- `promotion_status`
- `promotion_reason`
- `bounded_conclusion`

### JSON-Like Skeleton

```json
{
  "manifest_version": "1",
  "batch_stage": "confirmation",
  "harness_name": "tail-anchored-static-microstep",
  "calibration_mode": "confirmation-full",
  "stage_calibration_defaults": {
    "preferred_dtype": "bfloat16",
    "shape_ladder": [2048, 3072, 4096, 5120, 6144, 7168, 8192]
  },
  "regimes": [
    {
      "regime_id": "numa1-4gpu/allreduce/8m/r4n1",
      "message_mb": 8,
      "replicate_count": 3,
      "calibration": {
        "base_gemm_shape": 4096,
        "unit_gemm_latency_ms": 0.42,
        "R_block": 2,
        "R_overlap": 2,
        "R_epi": 1
      },
      "boundary_contract": {
        "boundary_name": "microstep-join-boundary",
        "start_event_name": "microstep_start_event",
        "collective_done_event_name": "collective_done_event",
        "end_event_name": "microstep_end_event"
      },
      "arms": [
        {
          "arm_id": "baseline",
          "arm_kind": "baseline",
          "requested_candidate": "default",
          "artifacts": {
            "run_root": "phase-confirmation/numa1-4gpu/8m/baseline",
            "summary_artifact": "comparison-summary.json",
            "trajectory_artifact": "trajectory.json"
          },
          "boundary_metrics": {
            "microstep_time_ms": 2.41,
            "boundary_tail_ms": 0.59
          },
          "judgment_summary": {
            "communication_delta_vs_baseline_pct": 0.0,
            "workload_delta_vs_baseline_pct": 0.0,
            "communication_judgment": "baseline-floor",
            "workload_judgment": "baseline-floor"
          }
        },
        {
          "arm_id": "static-ring-simple",
          "arm_kind": "fixed-static",
          "requested_candidate": "ring/simple",
          "artifacts": {
            "run_root": "phase-confirmation/numa1-4gpu/8m/static-ring-simple",
            "summary_artifact": "comparison-summary.json",
            "trajectory_artifact": "trajectory.json"
          },
          "boundary_metrics": {
            "microstep_time_ms": 2.38,
            "boundary_tail_ms": 0.55
          },
          "judgment_summary": {
            "communication_delta_vs_baseline_pct": 3.2,
            "workload_delta_vs_baseline_pct": 1.3,
            "communication_judgment": "communication-positive",
            "workload_judgment": "workload-positive"
          }
        }
      ],
      "regime_summary": {
        "best_candidate": "ring/simple",
        "regime_final_judgment": "workload-confirmed static win",
        "promotion_status": "eligible"
      }
    }
  ]
}
```

### Screening Stage

- Regimes:
  - `numa1-4gpu/allreduce/1m/r4n1`
  - `numa1-4gpu/allreduce/4m/r4n1`
  - `numa1-4gpu/allreduce/16m/r4n1`
- Candidate set:
  - `baseline`
  - `profiler-only`
  - `ring/simple`
  - `tree/simple`
  - `ring/ll128`
- Replicates:
  - `3`
- Batch stage:
  - `screening`
- Calibration mode:
  - `screening-simplified`
- Shortlist rule:
  - candidate enters confirmation when it is available and shows either `communication-positive` evidence or an interpretable near-threshold dual-layer signal on at least one screening regime.
- Exclusion reason rule:
  - each candidate not entering confirmation must record one of `candidate-unavailable`, `no-communication-signal`, `path-observability-insufficient`, `host-fallback-heavy`, or `screening-run-missing`.

Suggested regime fields:

- `regime_id`
- `message_bytes`
- `message_mb`
- `size_bucket_lower`
- `size_bucket_upper`
- `replicate_count`
- `calibration_mode`
- `preferred_dtype`
- `base_gemm_shape`
- `unit_gemm_latency_ms`
- `R_block`
- `R_overlap`
- `R_epi`

### Screening Execution Result

- Run label:
  - `2026-05-18-screening`
- Result root:
  - `nccl/plugins/adaptive/experiments/static-room-establishment/2026-05-18-screening`
- Summary artifacts:
  - `nccl/plugins/adaptive/experiments/static-room-establishment/2026-05-18-screening/screening-manifest.json`
  - `nccl/plugins/adaptive/experiments/static-room-establishment/2026-05-18-screening/screening-summary.json`
- Artifact count:
  - `45` per-run `summary.json` files
  - `12` `comparison-summary.json` files
  - `15` screening summary rows
- Metric completeness:
  - all screening rows include `collective_device_elapsed_ms`, `microstep_time_ms`, and `boundary_tail_ms`
- Harness sensitivity note:
  - this screening batch used the current pointwise `tail-anchored-microstep` implementation as an auxiliary screening signal.
  - it can shortlist candidates for confirmation, but it cannot produce a promotion-eligible `workload-confirmed static win`.

Static candidate screening table:

| Regime | Candidate | Target available | Collective ms | Comm delta | Comm vote | Microstep ms | Workload delta | Workload vote | Screening judgment |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: | --- | --- |
| `1 MiB` | `ring/simple` | yes | `0.180` | `-9.091%` | `1/3` | `0.316` | `-6.397%` | `1/3` | `no-communication-signal` |
| `1 MiB` | `tree/simple` | yes | `0.314` | `-90.303%` | `0/3` | `0.454` | `-52.862%` | `0/3` | `no-communication-signal` |
| `1 MiB` | `ring/ll128` | no | `0.266` | `-61.212%` | `1/3` | `0.422` | `-42.088%` | `1/3` | `candidate-unavailable` |
| `4 MiB` | `ring/simple` | yes | `0.335` | `3.179%` | `2/3` | `0.468` | `5.071%` | `2/3` | `screening-shortlist signal` |
| `4 MiB` | `tree/simple` | yes | `0.489` | `-41.329%` | `0/3` | `0.627` | `-27.181%` | `0/3` | `no-communication-signal` |
| `4 MiB` | `ring/ll128` | no | `0.263` | `23.988%` | `2/3` | `0.387` | `21.501%` | `3/3` | `candidate-unavailable` |
| `16 MiB` | `ring/simple` | yes | `0.959` | `-11.902%` | `1/3` | `1.103` | `-8.563%` | `1/3` | `no-communication-signal` |
| `16 MiB` | `tree/simple` | yes | `1.252` | `-46.091%` | `0/3` | `1.384` | `-36.220%` | `0/3` | `no-communication-signal` |
| `16 MiB` | `ring/ll128` | no | `0.910` | `-6.184%` | `1/3` | `1.052` | `-3.543%` | `1/3` | `candidate-unavailable` |

Screening shortlist:

- `ring/simple`
  - Reason: available fixed candidate with communication-positive and workload-positive screening signal at `4 MiB`.

Screening exclusions:

- `tree/simple`
  - Reason: `no-communication-signal`; target allreduce was available, but no regime reached the `2.0%` / `2-of-3` communication-positive gate.
- `ring/ll128`
  - Reason: `candidate-unavailable`; target allreduce records fell back from requested `LL128` to observed `RING/SIMPLE` in all screening regimes.

### Confirmation Stage

- Regimes:
  - `numa1-4gpu/allreduce/1m/r4n1`
  - `numa1-4gpu/allreduce/2m/r4n1`
  - `numa1-4gpu/allreduce/4m/r4n1`
  - `numa1-4gpu/allreduce/8m/r4n1`
  - `numa1-4gpu/allreduce/16m/r4n1`
  - `numa1-4gpu/allreduce/32m/r4n1`
  - `numa1-4gpu/allreduce/64m/r4n1`
- Candidate set:
  - `baseline`
  - `profiler-only`
  - shortlisted fixed static candidates from screening
- Replicates:
  - `3`
- Batch stage:
  - `confirmation`
- Calibration mode:
  - `confirmation-full`
- Promotion gate:
  - only confirmation runs with `calibration_mode=confirmation-full` and dense GEMM / matmul compute family can produce an eligible `workload-confirmed static win`.
- Confirmation artifacts:
  - `nccl/plugins/adaptive/experiments/static-room-establishment/2026-05-18-confirmation-calibration/confirmation-calibration.json`
  - `nccl/plugins/adaptive/experiments/static-room-establishment/2026-05-18-confirmation-full/confirmation-manifest.json`
  - `nccl/plugins/adaptive/experiments/static-room-establishment/2026-05-18-confirmation-full/confirmation-summary.json`
  - `nccl/plugins/adaptive/experiments/static-room-establishment/2026-05-18-confirmation-full/promotion-pack.json`
- Artifact count:
  - `21` baseline calibration `summary.json` files and `7` baseline calibration `comparison-summary.json` files
  - `63` confirmation-full `summary.json` files and `7` confirmation-full `comparison-summary.json` files
  - `21` confirmation summary rows

Confirmation calibration freeze:

| Regime | Baseline collective ms | Dtype | GEMM shape | Unit GEMM ms | Repeats `block/overlap/epi` | Selection rule |
| --- | ---: | --- | ---: | ---: | --- | --- |
| `1 MiB` | `0.176` | `bfloat16` | `2048` | `0.097602` | `2/2/1` | `smallest-shape-in-0.35x-0.75x-window` |
| `2 MiB` | `0.216` | `bfloat16` | `2048` | `0.097602` | `3/3/2` | `smallest-shape-in-0.35x-0.75x-window` |
| `4 MiB` | `0.323` | `bfloat16` | `2048` | `0.097602` | `4/4/2` | `nearest-to-0.5x-target` |
| `8 MiB` | `0.539` | `bfloat16` | `3072` | `0.256752` | `3/3/2` | `smallest-shape-in-0.35x-0.75x-window` |
| `16 MiB` | `1.136` | `bfloat16` | `4096` | `0.616035` | `2/2/1` | `smallest-shape-in-0.35x-0.75x-window` |
| `32 MiB` | `2.755` | `bfloat16` | `5120` | `1.124301` | `3/3/2` | `smallest-shape-in-0.35x-0.75x-window` |
| `64 MiB` | `5.519` | `bfloat16` | `6144` | `1.975560` | `3/3/2` | `smallest-shape-in-0.35x-0.75x-window` |

Suggested arm fields:

- `arm_id`
- `arm_name`
- `arm_kind`
- `requested_candidate`
- `requested_algorithm`
- `requested_protocol`
- `candidate_available`
- `observed_dominant_path`
- `summary_artifact`
- `trajectory_artifact`

Suggested boundary fields:

- `boundary_name`
- `start_event_name`
- `collective_start_event_name`
- `collective_done_event_name`
- `overlap_done_event_name`
- `epilogue_done_event_name`
- `end_event_name`
- `microstep_time_definition`
- `boundary_tail_definition`

Suggested judgment fields:

- `communication_delta_vs_baseline_pct`
- `workload_delta_vs_baseline_pct`
- `transfer_ratio`
- `communication_replicate_vote`
- `workload_replicate_vote`
- `communication_judgment`
- `workload_judgment`
- `regime_final_judgment`
- `promotion_status`

## Measurement Validity Checks

- Candidate availability:
  - `candidate_available=true` requires zero unavailable fallbacks for the requested fixed candidate in comparable allreduce records.
  - unavailable fixed candidates remain in the manifest with `candidate_available=false` and do not qualify for `communication-positive`.
- Requested candidate vs observed path consistency:
  - `requested_candidate` is the fixed replay request.
  - `observed_dominant_path` is read from profiler completion diagnostics.
  - `path_relation_to_baseline` must be one of `self`, `same-dominant-path`, `path-equivalent to baseline diagnostic`, `different-observed-path`, `unobserved`, or `not-applicable`.
  - path equivalence is interpretation only and never replaces the latency judgment against clean `baseline`.
- Replicate comparability:
  - comparable replicates must share topology group, message size, harness version, calibration mode, dtype, base GEMM shape, and segment repeats within each regime.
  - confirmation judgments require at least three comparable replicates and at least two same-direction replicate votes.
- Host fallback / parsing quality:
  - `host_fallback_count` and `parsable_record_count` are reported per arm.
  - host-fallback-heavy or parser-poor arms must carry a failure or interpretation reason and cannot be silently pooled into a positive judgment.

## Summary Schema

- Communication primary metric:
  - `collective_device_elapsed_ms`
- Workload primary metric:
  - `microstep_time_ms`
- Required summary artifacts:
  - `screening-manifest.json`
  - `screening-summary.json`
  - `confirmation-manifest.json`
  - `confirmation-summary.json`
  - `promotion-pack.json`
- Summary rows must include:
  - `change_name`
  - `surface_version`
  - `batch_stage`
  - `regime_id`
  - `arm_id`
  - `arm_kind`
  - `requested_candidate`
  - `candidate_available`
  - `observed_dominant_path`
  - `path_relation_to_baseline`
  - `collective_device_elapsed_ms`
  - `microstep_time_ms`
  - `boundary_tail_ms`
  - `boundary_anchor_window_ms`
  - `boundary_anchor_ratio`
  - `communication_delta_vs_baseline_pct`
  - `workload_delta_vs_baseline_pct`
  - `communication_replicate_vote`
  - `workload_replicate_vote`
  - `communication_judgment`
  - `workload_judgment`
  - `regime_final_judgment`
  - `promotion_status`
  - `failure_reason`

## Communication-Room Findings

| Regime | Candidate | Requested path | Observed dominant path | Comm delta vs `baseline` | Replicate vote | Judgment | Notes |
| --- | --- | --- | --- | ---: | --- | --- | --- |
| `1 MiB` | `ring/simple` | `RING/SIMPLE` | `RING/SIMPLE`, 4 channels | `16.889%` | `2/3` | `communication-positive` | target available; host fallback observed |
| `2 MiB` | `ring/simple` | `RING/SIMPLE` | `RING/SIMPLE`, 4 channels | `0.332%` | `1/3` | `communication-nonpositive` | below threshold |
| `4 MiB` | `ring/simple` | `RING/SIMPLE` | `RING/SIMPLE`, 4 channels | `0.287%` | `2/3` | `communication-nonpositive` | below threshold |
| `8 MiB` | `ring/simple` | `RING/SIMPLE` | `RING/SIMPLE`, 4 channels | `-0.136%` | `2/3` | `communication-nonpositive` | below threshold |
| `16 MiB` | `ring/simple` | `RING/SIMPLE` | `RING/SIMPLE`, 4 channels | `-2.906%` | `0/3` | `communication-nonpositive` | slower than baseline |
| `32 MiB` | `ring/simple` | `RING/SIMPLE` | `RING/SIMPLE`, 4 channels | `-3.581%` | `0/3` | `communication-nonpositive` | slower than baseline |
| `64 MiB` | `ring/simple` | `RING/SIMPLE` | `RING/SIMPLE`, 4 channels | `-1.281%` | `1/3` | `communication-nonpositive` | slower than baseline |

## Workload-Room Findings

| Regime | Candidate | `microstep_time_ms` delta vs `baseline` | `boundary_tail_ms` | `boundary_anchor_ratio` | `transfer_ratio` | Replicate vote | Judgment | Notes |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| `1 MiB` | `ring/simple` | `8.808%` | `0.120` | `0.581` | `0.522` | `2/3` | `workload-positive` | confirmation-full GEMM; promotion eligible |
| `2 MiB` | `ring/simple` | `1.624%` | `0.228` | `0.621` | `4.892` | `2/3` | `workload-nonpositive` | below threshold and communication-nonpositive |
| `4 MiB` | `ring/simple` | `0.692%` | `0.246` | `0.590` | `2.411` | `2/3` | `workload-nonpositive` | below threshold and communication-nonpositive |
| `8 MiB` | `ring/simple` | `0.193%` | `0.546` | `0.620` | `-1.419` | `2/3` | `workload-nonpositive` | below threshold and communication-nonpositive |
| `16 MiB` | `ring/simple` | `-1.421%` | `0.616` | `0.649` | `0.489` | `0/3` | `workload-nonpositive` | slower than baseline |
| `32 MiB` | `ring/simple` | `-1.432%` | `2.233` | `0.642` | `0.400` | `0/3` | `workload-nonpositive` | slower than baseline |
| `64 MiB` | `ring/simple` | `-0.539%` | `3.914` | `0.657` | `0.421` | `1/3` | `workload-nonpositive` | slower than baseline |

## Regime-Level Judgments

| Regime | Best candidate | Final judgment | Bounded conclusion | Anomaly flags |
| --- | --- | --- | --- | --- |
| `1 MiB` | `ring/simple` | `workload-confirmed static win` | confirmation-full GEMM win on `surface-v1-current` | `target-host-fallback-observed` |
| `2 MiB` | none | `no proven communication room` | no available fixed candidate met communication-positive gate | `target-host-fallback-observed` |
| `4 MiB` | none | `no proven communication room` | no available fixed candidate met communication-positive gate | `target-host-fallback-observed` |
| `8 MiB` | none | `no proven communication room` | no available fixed candidate met communication-positive gate | `target-host-fallback-observed` |
| `16 MiB` | none | `no proven communication room` | no available fixed candidate met communication-positive gate | `target-host-fallback-observed` |
| `32 MiB` | none | `no proven communication room` | no available fixed candidate met communication-positive gate | `target-host-fallback-observed` |
| `64 MiB` | none | `no proven communication room` | no available fixed candidate met communication-positive gate | `target-host-fallback-observed` |

Required final judgments:

- `no proven communication room`
- `communication-only win`
- `workload-confirmed static win`

## Promotion Pack To `same-key-phase-shift-validation`

| Regime | Same-key tuple | Best static floor | Contender set | Promotion status | Reason |
| --- | --- | --- | --- | --- | --- |
| `1 MiB` | `numa1-4gpu/allreduce/1m/r4n1` | `ring/simple` | `ring/simple` | `eligible` | confirmation-full GEMM result met communication and workload gates |

Promotion artifact:

- `nccl/plugins/adaptive/experiments/static-room-establishment/2026-05-18-confirmation-full/promotion-pack.json`

## Negative Conclusions Bound To Surface

- Global negative conclusion:
  - not applicable, because `1 MiB` is classified as `workload-confirmed static win`.
- Non-winning regimes:
  - `2 MiB`, `4 MiB`, `8 MiB`, `16 MiB`, `32 MiB`, and `64 MiB` remain `no proven communication room` under the current controlled surface version.
- If a future run has no confirmation regime classified as `workload-confirmed static win`, the exit summary must state:
  - `no proven room on current controlled surface version`
- The negative conclusion is limited to:
  - `surface-v1-current`
  - `numa1-4gpu`
  - `allreduce`
  - single-node four-rank same-socket placement
  - the candidate set and harness contract recorded in this evidence file.

## Surface Expansion Backlog

- Candidates not yet tested:
  - no additional deterministic fixed candidate family has been implemented in the current plugin beyond `ring/simple`, `tree/simple`, and `ring/ll128`.
- Candidates excluded from `surface v1`:
  - `final-steady`: dynamic policy output, not a fixed candidate arm.
  - `weak-online`: online switching behavior, out of scope for static room.
  - topology variants outside `numa1-4gpu`: excluded by surface boundary.
- Open measurement questions:
  - whether the 1 MiB positive result remains stable under same-key phase-shift validation.
  - whether additional deterministic fixed candidates can produce room outside the 1 MiB regime.
  - whether host-fallback-heavy completion diagnostics can be reduced without losing requested-vs-observed path evidence.
