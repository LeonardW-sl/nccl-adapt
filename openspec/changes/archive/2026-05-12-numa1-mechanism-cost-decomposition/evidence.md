# NUMA1 Mechanism Cost Decomposition Evidence

## Result Root

- Root directory:
  - `nccl/plugins/adaptive/experiments/numa1-mechanism-cost-decomposition/2026-05-12-numa1-mechanism-cost-decomposition`
- Matrix manifest:
  - `nccl/plugins/adaptive/experiments/numa1-mechanism-cost-decomposition/2026-05-12-numa1-mechanism-cost-decomposition/matrix-manifest.json`
- Aggregate summary:
  - `nccl/plugins/adaptive/experiments/numa1-mechanism-cost-decomposition/2026-05-12-numa1-mechanism-cost-decomposition/numa1-mechanism-summary.json`
- Primary mode comparison:
  - `nccl/plugins/adaptive/experiments/numa1-mechanism-cost-decomposition/2026-05-12-numa1-mechanism-cost-decomposition/mode-comparison/numa1-4gpu/comparison-summary.json`
- Candidate-aligned replay:
  - not emitted in this batch, because `final-steady` remained aligned to the default replay candidate `ring/simple`

## Runtime And Placement Metadata

- Host snapshots:
  - `host/nvidia-smi-topo.txt`
  - `host/gpu-inventory.csv`
  - `host/gpu-list.txt`
  - `host/ibdev2netdev.txt`
  - `host/lspci-network.txt`
  - `host/nic-locality.txt`
  - `host/numactl-H.txt`
  - `host/server-idle-check.txt`
- Container runtime:
  - image tag: `nvcr.io/nvidia/pytorch:26.03-py3`
  - image id: `sha256:3c90e38f5ec51e51d1c73bd7eb3d83674a254f451147c5cadc4344314258a112`
  - repo digest: `nvcr.io/nvidia/pytorch@sha256:3c90e38f5ec51e51d1c73bd7eb3d83674a254f451147c5cadc4344314258a112`
  - launch args: `container/launch-command.txt`
  - workdir: `container/workdir.txt`
  - runtime snapshots: `container/torch-runtime.json`, `container/ldconfig-nccl.txt`, `container/glibc-version.txt`
- Expected plugin path:
  - `/workspace/nccl-adapt/nccl/plugins/adaptive/libnccl-adaptive.so`
- Placement:
  - `numa1-4gpu`: `CUDA_VISIBLE_DEVICES=4,5,6,7`, `NPROC_PER_NODE=4`, `CPU=32-63,96-127`, `NUMA=1`

## Experiment Parameters

- Replicates: `3`
- Modes: `baseline`, `profiler-only`, `static-replay`, `final-steady`
- Message size: `8 MiB`
- Warmup / measure iters: `4 / 192`
- Mode order: `rotate`, seed `20260512`
- Default static replay candidate: `ring/simple`
- `NCCL_ADAPTIVE_WARMUP_SAMPLES_PER_CANDIDATE=1`
- `NCCL_ADAPTIVE_RECHECK_SAMPLES_PER_CANDIDATE=1`
- `NCCL_ADAPTIVE_MIN_SAMPLES=1`
- `NCCL_ADAPTIVE_SWITCH_THRESHOLD_PCT=2.0`
- `NCCL_ADAPTIVE_ACTIVATION_LAG=2`
- `NCCL_ADAPTIVE_LOG_COORDINATOR=1`
- `NCCL_ADAPTIVE_LOG_COMPLETION=1`

## Key Findings

### 1. `static-replay` and `final-steady` stayed candidate-aligned without a supplemental replay

| Item | Value |
| --- | --- |
| Requested static replay candidate | `ring/simple` |
| Learned `final-steady` candidate | `ring/simple` |
| Alignment status | `aligned` |
| Supplemental replay needed | `no` |

Interpretation:

- The rerun did not drift away from `ring/simple`, so the main matrix already satisfies the candidate-alignment precondition.
- This means `final-steady post-activation - static-replay` can be read directly as the dynamic residual for this `numa1-4gpu` workload.

### 2. The three-way decomposition is clean and numerically small on `numa1-4gpu`

| Metric | Mean latency |
| --- | ---: |
| `baseline` | `0.431 ms` |
| `profiler-only` (`callback-only`) | `0.443 ms` |
| `static-replay` | `0.434 ms` |
| `final-steady` overall | `0.464 ms` |
| `final-steady` pre-activation | `0.525 ms` |
| `final-steady` post-activation | `0.462 ms` |

Primary decomposition deltas:

- `profiler-only - baseline = +0.012 ms`
- `static-replay - profiler-only = -0.009 ms`
- `final-steady post-activation - static-replay = +0.028 ms`

Interpretation:

- The profiler / observation tax is present but small.
- Replaying the learned fixed candidate is slightly better than `profiler-only`, so the fixed-candidate effect is not the source of the remaining gap.
- The residual dynamic cost on the clean `numa1-4gpu` surface is modest: `+0.028 ms` post-activation above aligned `static-replay`.
- The front half is still measurably higher than the post-activation segment (`0.525 ms` vs `0.462 ms`), but even after removing it the remaining dynamic residual is already much smaller than the `numa0` jump isolated by the previous change.

### 3. Candidate and selected path observability are now explicit in result artifacts

Main allreduce-path observations from the parsed result contract:

| Mode / slice | Candidate set | `selectedAlgo` | `selectedProto` | `nChannels` |
| --- | --- | --- | --- | --- |
| `static-replay` `allreduce-attached` | `ring/simple` | `RING` | `SIMPLE` | dominant `4`, plus a small number of `1`-channel tiny control collectives |
| `final-steady` `allreduce-post-activation` | `ring/simple` | `RING` | `SIMPLE` | `4` |

Interpretation:

- After the candidate-alignment filter is applied, both `static-replay` and post-activation `final-steady` point at the same high-level path: `ring/simple`.
- The parsed `selectedAlgo` / `selectedProto` view also agrees: both sides are `RING/SIMPLE`.
- For the main 8 MiB allreduce workload, the observed steady-path channel count stays on the 4-channel path; the small `1`-channel cases in `static-replay` come from tiny attached control collectives near teardown, not from the primary long-window allreduce body.
- NCCL logs confirm that profiler/tuner-enabled runs loaded the expected mounted plugin path from `/workspace/nccl-adapt/nccl/plugins/adaptive/libnccl-adaptive.so`.

### 4. Boundary and H100 follow-up gate

`go / no-go` decision: `go`

Reasoning:

- `numa1-4gpu` now has a clean candidate-aligned decomposition.
- The fixed-candidate effect is isolated separately from the dynamic residual.
- The remaining post-activation dynamic residual is small enough (`+0.028 ms`) that an H100 follow-up can meaningfully ask whether the same mechanism shape persists on a different platform.

Boundary:

- This change does **not** explain the abnormal `numa0-4gpu` behavior.
- This change does **not** prove that H100 will show the same residual size, candidate, or selected path.
- The only claim supported here is narrower:
  - on the current `numa1-4gpu` clean reference surface, `final-steady` and `static-replay` stay candidate-aligned on `ring/simple`, and the remaining post-activation dynamic residual is small.
