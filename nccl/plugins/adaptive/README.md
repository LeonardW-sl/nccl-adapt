# Adaptive NCCL Plugin

## 中文补丁记录

### 2026-04-26

- 将原始实验数据统一归档到 `nccl/plugins/adaptive/experiments/`，按实验问题分类，不再继续累积顶层 `results-*` 目录。
- OpenSpec change 目录改为只保留 `evidence.md` 摘要索引；原始日志与环境快照不再塞进 change 目录。
- `run_torch_modes.sh` 与 `run_allreduce_modes.sh` 的默认输出目录改到 `experiments/mode-comparison/` 下的日期目录。
- README 中的实验引用路径已同步切到 `experiments/`。

### 2026-04-25

- 建立 adaptive NCCL plugin 的最小 profiler+tuner 闭环与基础实验脚本。

## 实验数据归档

- 原始实验数据入口：`nccl/plugins/adaptive/experiments/README.md`
- 当前 OpenSpec 证据索引：
  - `openspec/changes/minimal-weak-online-closed-loop/evidence.md`
  - `openspec/changes/cross-rank-coordinator/evidence.md`
  - `openspec/changes/experiment-determinism-spec/evidence.md`

This directory contains a standalone `libnccl-adaptive.so` that exports both:

- `ncclProfiler_v5`
- `ncclTunerPlugin_v5`

The implementation stays inside `nccl/plugins` and does not modify NCCL core source files.
The adaptive plugin is self-contained: the minimal NCCL profiler API headers it
needs are vendored under `include/nccl/`.

## Behavior

- The tuner and profiler share an in-process `PolicyStore`, while communicator-domain publication state is shared across local rank processes through POSIX shared memory keyed by `commId + collective key`.
- The policy key uses collective type, size bin, `nRanks`, and `nNodes`.
- Allreduce candidates are deterministic and ordered as:
  - `default`
  - `ring/simple`
  - `tree/simple`
  - `ring/ll128`
- Weak-online mode uses `warmup -> steady -> recheck` windows. Outside a sampling window, the tuner only reads the latest shared committed policy that has crossed its activation boundary.
- The tuner path uses non-blocking `try_lock` access. On contention or invalid/unavailable candidates it falls back to NCCL defaults immediately.
- The profiler path records collective metadata on `ncclProfileColl`, completion timing on `ncclProfileKernelCh`, and window-level summary inputs for weak-online adjudication.
- Profiler completion now closes sampled records at host-side coll stop even when kernel-channel coverage is partial; when no kernel callback arrives, it falls back conservatively to host-stop timing instead of dropping the sampled record.
- Callback paths avoid file I/O, network I/O, sleeps, and CUDA stream synchronization.
- The first-version representative is fixed to communicator rank 0, and only that writer publishes shared committed policy records.
- Shared publication records are host-side only; the coordinator does not use CUDA IPC objects or request/response transport in `getCollInfo`.
- Published policy and activation are separated by an explicit `effective_call_index` with configurable `NCCL_ADAPTIVE_ACTIVATION_LAG` and a default minimum of `2`.

## Current Status - 2026-04-26

This branch now includes the first-version single-node cross-rank coordinator
for `weak-online` and `final-steady`.

- Shared committed policy publication is communicator-domain scoped to
  `commId + collType + size bucket + nRanks + nNodes`.
- Rank-local window completion now submits per-rank summaries to shared
  coordinator slots; communicator rank 0 aggregates and publishes one shared
  committed policy record for the domain.
- Runtime acceptance for `final-steady` and `weak-online` now includes fresh
  2-rank and 8-rank torch smoke plus 8-rank overhead re-measurement in the
  containerized PyTorch/NCCL environment described below.

## Build

```bash
cd nccl/plugins/adaptive
make
```

## Load Examples

Adaptive mode:

```bash
export NCCL_PROFILER_PLUGIN=$PWD/libnccl-adaptive.so
export NCCL_TUNER_PLUGIN=$PWD/libnccl-adaptive.so
export NCCL_ADAPTIVE_MODE=weak-online
```

Final steady mode:

```bash
export NCCL_PROFILER_PLUGIN=$PWD/libnccl-adaptive.so
export NCCL_TUNER_PLUGIN=$PWD/libnccl-adaptive.so
export NCCL_ADAPTIVE_MODE=final-steady
```

Profiler-only mode:

```bash
export NCCL_PROFILER_PLUGIN=$PWD/libnccl-adaptive.so
unset NCCL_TUNER_PLUGIN
```

Static tuner mode:

```bash
export NCCL_PROFILER_PLUGIN=$PWD/libnccl-adaptive.so
export NCCL_TUNER_PLUGIN=$PWD/libnccl-adaptive.so
export NCCL_ADAPTIVE_MODE=static
export NCCL_ADAPTIVE_STATIC_CANDIDATE=ring/simple
```

Disabled baseline:

```bash
unset NCCL_PROFILER_PLUGIN
unset NCCL_TUNER_PLUGIN
```

## Experiment Protocol

`run_torch_modes.sh` is now the primary harness for adaptive experiment work. It treats experiment type, replicate id, and run order as part of the result contract instead of ad hoc shell state.

### Result Layout

- Every invocation writes a `manifest.json` at the experiment root.
- Each concrete run lives under `replicate-XX/run-YY-<mode>/`.
- Each run directory contains:
  - `env.txt`: raw environment snapshot
  - `metadata.json`: experiment type, replicate id, run order, message size, size bucket, and replay candidate
  - `stdout.log`: raw torchrun output
  - `summary.json`: parsed latency summary with `median`, `p95`, `max`, and phase-aware breakdowns
  - `trajectory.json`: parsed coordinator publish/activate trajectory when diagnostics are enabled
- `mode-comparison`, `correctness`, and `policy-quality` runs additionally emit `comparison-summary.json`.
- `state-granularity` runs additionally emit `candidate-trajectories.json`.

### Experiment Types

- `EXPERIMENT_TYPE=mode-comparison`
  - Purpose: isolate mechanism cost across `baseline`, `profiler-only`, `final-steady`, and `weak-online`.
  - Required inputs: `REPLICATES>=3`, `MODE_ORDER_STRATEGY=rotate|random|fixed`, stable workload parameters, and one message size per batch.
  - Required outputs: per-run summaries plus an aggregate `comparison-summary.json` containing per-mode `median`, `p95`, `max`, and phase averages.
- `EXPERIMENT_TYPE=correctness`
  - Purpose: validate publish, observed-publish, activate, fallback, and cross-rank consistency without turning those runs into policy-win claims.
  - Recommended modes: `MODE_SEQUENCE=final-steady,weak-online`.
  - Required outputs: coordinator trajectory logs and run summaries; conclusions should cite activation boundaries, not throughput deltas.
- `EXPERIMENT_TYPE=policy-quality`
  - Purpose: validate a learned candidate independently through static replay.
  - Required inputs: `STATIC_REPLAY_CANDIDATE=<candidate>` and a fixed workload.
  - Default modes: `baseline,static-replay`.
  - Required outputs: aggregate comparison against baseline and the replay candidate recorded in `metadata.json`.
- `EXPERIMENT_TYPE=state-granularity`
  - Purpose: test whether one size bucket is honest enough for shared policy publication.
  - Required inputs: fixed `NNODES`, `NPROC_PER_NODE`, adaptive parameters, `SWEEP_MODE` (normally `weak-online`), and `SIZE_SWEEP_MBS=<comma-separated sizes>` limited to one bucket.
  - Required outputs: `candidate-trajectories.json` with per-size publish/activate trajectories across replicates.

### Harness Controls

- `REPLICATES`: number of replicates, default `3`
- `MODE_ORDER_STRATEGY=rotate|random|fixed`: order control for both mode matrices and size sweeps
- `MODE_SEQUENCE`: explicit mode list override
- `SIZE_SWEEP_MBS`: required for `state-granularity`
- `STATIC_REPLAY_CANDIDATE`: required signal for `policy-quality`
- `RUN_LABEL`: directory suffix under `experiments/<category>/`

Example mode comparison:

```bash
cd nccl/plugins/adaptive
REPLICATES=4 MODE_ORDER_STRATEGY=rotate \
ADAPTIVE_MESSAGE_MB=8 ADAPTIVE_MEASURE_ITERS=64 \
./run_torch_modes.sh "$PWD"
```

Example state-granularity sweep:

```bash
cd nccl/plugins/adaptive
EXPERIMENT_TYPE=state-granularity REPLICATES=3 \
SIZE_SWEEP_MBS=5,6,7 SWEEP_MODE=weak-online \
NCCL_ADAPTIVE_RECHECK_AFTER=8 ADAPTIVE_MEASURE_ITERS=72 \
./run_torch_modes.sh "$PWD"
```

## Suggested Allreduce Benchmark Parameters

Use repeated message sizes and enough iterations to cover the deterministic warmup and optional recheck windows. A reasonable starting point with `all_reduce_perf` is:

```bash
./build/all_reduce_perf -b 1K -e 256M -f 2 -g 8 -n 100 -w 20
```

- `-n 100` leaves enough post-warmup iterations after the initial window and later rechecks.
- `-w 20` gives NCCL startup and communicator warmup time before measurements.
- `-f 2` covers repeated powers-of-two size bins that map cleanly onto the plugin policy key.

## Weak-Online Controls

- `NCCL_ADAPTIVE_MODE=weak-online|final-steady|static|disabled`
- `NCCL_ADAPTIVE_WARMUP_SAMPLES_PER_CANDIDATE`: warmup samples per candidate, default `1`
- `NCCL_ADAPTIVE_RECHECK_SAMPLES_PER_CANDIDATE`: recheck samples per candidate, default `1`
- `NCCL_ADAPTIVE_RECHECK_AFTER`: steady calls between rechecks, default `64`
- `NCCL_ADAPTIVE_MIN_SAMPLES`: minimum samples required before considering a candidate, default `1`
- `NCCL_ADAPTIVE_SWITCH_THRESHOLD_PCT`: minimum latency improvement percentage required to switch, default `2.0`
- `NCCL_ADAPTIVE_ACTIVATION_LAG`: activation lag added to `published_call_index`, default `2`, minimum `2`

## Diagnostics

Recommended run metadata to capture alongside benchmark output:

- `NCCL_DEBUG`
- `NCCL_DEBUG_SUBSYS`
- `NCCL_CUMEM_HOST_ENABLE`
- `/dev/shm` size
- `ulimit -l`

Optional adaptive-plugin diagnostics:

- `NCCL_ADAPTIVE_LOG_COORDINATOR=1`: shared summary / publish / activate state transitions
- `NCCL_ADAPTIVE_LOG_COMPLETION=1`: tuner enqueue, profiler attach, and sampled completion closure diagnostics

Container prerequisites for reproducible NCCL runs:

- `--shm-size=1g`
- `--ulimit memlock=-1`

If NCCL reports shared-memory or cuMem host allocation issues, retry with:

```bash
export NCCL_CUMEM_HOST_ENABLE=0
```

## Updated Result Boundaries - 2026-04-26

All current-revision runs below used:

- Host build of `nccl/plugins/adaptive/libnccl-adaptive.so`
- Container `nvcr.io/nvidia/pytorch:26.03-py3` with the repository bind-mounted at `/workspace/nccl-adapt`
- `--ipc=host`, `--ulimit memlock=-1`, `--ulimit stack=67108864`
- `NCCL_CUMEM_HOST_ENABLE=0`
- 8 MiB allreduce messages over torch distributed unless the section explicitly says otherwise

### 1. Mechanism Correctness

- `final-steady` 2-rank torch smoke now completes without `SIGSEGV`.
- Warmup sampled records `seq=0..3` close successfully even when profiler kernel coverage is zero and the plugin falls back to host-stop timing.
- `final-steady` and `weak-online` 8-rank torch smoke both show communicator-domain publish/activate consistency instead of rank-local divergence.
- Reference logs:
  - `experiments/cross-rank-coordination/2026-04-26-2rank-debug2/final-steady-2rank-debug2.log`
  - `experiments/cross-rank-coordination/2026-04-26-8rank-consistency-validation/final-steady.log`
  - `experiments/cross-rank-coordination/2026-04-26-8rank-consistency-validation/weak-online.log`

### 2. Mechanism Cost

Primary 8-rank overhead re-measurement (`warmup_iters=4`, `measure_iters=64`):

| Mode | Mean per-rank avg latency | Relative to baseline |
| --- | ---: | ---: |
| `baseline` | 0.492 ms | 1.000x |
| `profiler-only` | 0.504 ms | 1.024x |
| `final-steady` | 0.540 ms | 1.098x |
| `weak-online` | 0.612 ms | 1.244x |

- This longer run restores the expected ordering `baseline < profiler-only < final-steady < weak-online`.
- The shorter smoke (`measure_iters=12`) remains supplementary only because fixed-order short runs can still mislead on overhead magnitude.
- Reference logs:
  - `experiments/overhead/2026-04-26-rerun-compare-long64/baseline.log`
  - `experiments/overhead/2026-04-26-rerun-compare-long64/profiler-only.log`
  - `experiments/overhead/2026-04-26-rerun-compare-long64/final-steady.log`
  - `experiments/overhead/2026-04-26-rerun-compare-long64/weak-online.log`
  - `experiments/overhead/2026-04-26-cross-rank-short-smoke/baseline.log`
  - `experiments/overhead/2026-04-26-cross-rank-short-smoke/profiler-only.log`
  - `experiments/overhead/2026-04-26-cross-rank-short-smoke/final-steady.log`
  - `experiments/overhead/2026-04-26-cross-rank-short-smoke/weak-online.log`

### 3. Policy Quality

- The protocol now treats learned-policy validation as `policy-quality`, separate from weak-online overhead measurement.
- The current branch provides a static replay entrypoint through `EXPERIMENT_TYPE=policy-quality` and `STATIC_REPLAY_CANDIDATE=<candidate>`.
- Existing 2026-04-26 data is still dominated by correctness and cost evidence; no claim here says the learned candidate is globally better than baseline without a dedicated replay batch.

### 4. State Granularity

- `5 MiB` and `7 MiB` both map to the same `4-8 MiB` bucket in the current keying scheme.
- `5 MiB` publishes `epoch=2 -> tree/simple` and `epoch=3 -> ring/simple`.
- `7 MiB` publishes `epoch=2 -> default` and `epoch=3 -> default`.
- Repeated lower-vs-upper disagreement across at least two recheck cycles means the current `4-8 MiB` bucket is not honest enough for a shared activation domain.
- Reference logs:
  - `experiments/bucket-honesty/2026-04-26-5mb-vs-7mb/weak-online-5mb.log`
  - `experiments/bucket-honesty/2026-04-26-5mb-vs-7mb/weak-online-7mb.log`
  - `experiments/bucket-honesty/2026-04-26-5mb-vs-7mb/weak-online-5mb-long.log`
  - `experiments/bucket-honesty/2026-04-26-5mb-vs-7mb/weak-online-7mb-long.log`

### Patch Addendum - 2026-04-26 17:33 CST

The four sections above are preserved as a historical record of earlier
2026-04-26 batches. The fresh protocol rerun collected for
`experiment-determinism-spec` lives under:

- `experiments/correctness/2026-04-26-protocol-correctness`
- `experiments/mode-comparison/2026-04-26-protocol-mode-comparison`
- `experiments/policy-quality/2026-04-26-protocol-policy-quality`
- `experiments/state-granularity/2026-04-26-protocol-state-granularity`

When the fresh protocol rerun conflicts with the historical section above, the
fresh rerun is the current source of truth for this branch revision.

#### Patch 1. Mechanism Correctness

- Confirmed again. In the fresh correctness batch, both `final-steady` and
  `weak-online` publish `ring/simple` at `effective_call=6` and activate it at
  `call=6` across the 8-rank communicator domain.
- This part does not contradict the historical section above; it strengthens it
  with change-local evidence in the new protocol directory.

#### Patch 2. Mechanism Cost

Fresh rotated 3-replicate mode comparison (`warmup_iters=4`, `measure_iters=64`):

| Mode | Fresh mean per-rank avg latency | Fresh p95 | Note |
| --- | ---: | ---: | --- |
| `baseline` | 8.867 ms | 20.029 ms | Historical absolute value not reproduced |
| `profiler-only` | 8.483 ms | 13.676 ms | Slightly below `baseline` in this rerun |
| `final-steady` | 16.931 ms | 26.319 ms | Clearly above non-tuning modes |
| `weak-online` | 15.120 ms | 23.845 ms | Clearly above non-tuning modes |

- Contradiction with the historical section above: the strict total ordering
  `baseline < profiler-only < final-steady < weak-online` is not stable in the
  fresh rotated rerun.
- What remains stable is narrower: `final-steady` and `weak-online` are both
  materially more expensive than `baseline` / `profiler-only` on this workload.
- The fresh batch therefore supports a "tuning modes are costly here" claim,
  but not a stronger claim about a fixed ordering between `baseline` and
  `profiler-only`, or between `final-steady` and `weak-online`.

#### Patch 3. Policy Quality

- Contradiction with the historical section above: there is now a dedicated
  replay batch, so "no dedicated replay evidence yet" is no longer true.
- The fresh `policy-quality` rerun replays the candidate learned in the fresh
  correctness batch, `ring/simple`, and shows:
  - `baseline`: `16.446 ms` mean per-rank avg, `19.805 ms` p95
  - `static-replay`: `14.524 ms` mean per-rank avg, `19.181 ms` p95
- The narrow claim supported by this rerun is workload-local: on this 8 MiB
  torch-distributed workload, replaying the learned `ring/simple` candidate
  beats the measured `baseline` aggregate.
- This is still not evidence that the learned policy is globally superior
  across workloads or topologies.

#### Patch 4. State Granularity

- Direct contradiction with the historical section above: the fresh
  `state-granularity` rerun does not reproduce the earlier `5 MiB` vs `7 MiB`
  divergence claim.
- In the fresh rerun, `5MB`, `6MB`, and `7MB` all publish only
  `ring/simple` in `candidate-trajectories.json`.
- Fresh aggregate means remain different by size (`12.094 ms`, `14.429 ms`,
  `13.044 ms` respectively), but candidate identity stayed aligned under the
  current settings.
- The stronger "the current `4-8 MiB` bucket is not honest enough" statement
  should therefore be treated as a historical, non-reproduced observation
  rather than a current conclusion for this branch.

The tuner-enabled SIGSEGV root cause was invalid cost-table indexing. NCCL passes
a contiguous `float[numAlgo][numProto]` buffer cast as `float**`; treating it as
an actual pointer-to-pointer dereferenced float data as row pointers. The tuner
now treats the argument as contiguous storage before reading or writing
candidate costs.

Fallback verification:

- `NCCL_ADAPTIVE_MODE=disabled` with the tuner loaded completed a 2-rank smoke
  run and preserved the observed default RING/SIMPLE selection.
- Contended policy access uses `try_lock`; if the lock is unavailable, the tuner
  returns `ncclSuccess` without mutating the cost table.
- Invalid static candidates parse to `default`.

Environment diagnostics captured with each run:

- `/dev/shm`: 252 GiB available, 303 MiB used during the run.
- `memlock`: unlimited.
- `NCCL_CUMEM_HOST_ENABLE=0`.
- `NCCL_DEBUG=INFO`, `NCCL_DEBUG_SUBSYS=INIT,TUNING,COLL`.

Known limitations and next steps:

- These results are single-node only; multi-node coordination remains out of scope for this first implementation.
- The short torch smoke validates correctness and activation consistency, not final performance stability across workloads.
- The coordinator is single-node, rank-0-representative, and window-summary driven; there is still no external cross-rank control service in this revision.
- `weak-online` overhead still contains recheck-window spikes, so segmented interpretation is required even after adding `median`, `p95`, and `max`.
- Current size-bucket evaluation shows that the shared `4-8 MiB` bucket is too coarse for weak-online policy publication; a deterministic midpoint sub-bucket refinement is the recommended next evolution.
- `all_reduce_perf` in the tested container still fails independently with `Cuda failure 101 'invalid device ordinal'`, so torch distributed remains the active benchmark path.
- No shared-memory, memlock, or cuMem host allocation failure was observed with the run settings above.
