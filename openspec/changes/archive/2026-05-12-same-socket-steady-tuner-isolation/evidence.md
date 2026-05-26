# Same-Socket Steady-Tuner Isolation Evidence

## Result Root

- Root directory: `nccl/plugins/adaptive/experiments/same-socket-steady-tuner-isolation/2026-05-12-same-socket-steady-tuner-isolation-long192`
- Matrix manifest: `nccl/plugins/adaptive/experiments/same-socket-steady-tuner-isolation/2026-05-12-same-socket-steady-tuner-isolation-long192/matrix-manifest.json`
- Aggregate summary: `nccl/plugins/adaptive/experiments/same-socket-steady-tuner-isolation/2026-05-12-same-socket-steady-tuner-isolation-long192/same-socket-summary.json`
- Per-group comparisons:
  - `nccl/plugins/adaptive/experiments/same-socket-steady-tuner-isolation/2026-05-12-same-socket-steady-tuner-isolation-long192/mode-comparison/numa0-4gpu/comparison-summary.json`
  - `nccl/plugins/adaptive/experiments/same-socket-steady-tuner-isolation/2026-05-12-same-socket-steady-tuner-isolation-long192/mode-comparison/numa1-4gpu/comparison-summary.json`

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
- Same-socket groups:
  - `numa0-4gpu`: `CUDA_VISIBLE_DEVICES=0,1,2,3`, `NPROC_PER_NODE=4`, `CPU=0-31,64-95`
  - `numa1-4gpu`: `CUDA_VISIBLE_DEVICES=4,5,6,7`, `NPROC_PER_NODE=4`, `CPU=32-63,96-127`

## Experiment Parameters

- Replicates: `3`
- Modes: `profiler-only`, `final-steady`
- Message size: `8 MiB`
- Warmup / measure iters: `4 / 192`
- Mode order: `rotate`, seed `20260512`
- `NCCL_ADAPTIVE_WARMUP_SAMPLES_PER_CANDIDATE=1`
- `NCCL_ADAPTIVE_RECHECK_SAMPLES_PER_CANDIDATE=1`
- `NCCL_ADAPTIVE_MIN_SAMPLES=1`
- `NCCL_ADAPTIVE_SWITCH_THRESHOLD_PCT=2.0`
- `NCCL_ADAPTIVE_ACTIVATION_LAG=2`
- `NCCL_ADAPTIVE_LOG_COORDINATOR=1`
- `NCCL_ADAPTIVE_LOG_COMPLETION=1`

## Key Findings

### 1. The long-window same-socket rerun keeps a large jump only on `numa0-4gpu`

| Group | `profiler-only` avg | `profiler-only` callback-only | `final-steady` avg | `pre-activation` avg | `post-activation` avg | `post - profiler` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `numa0-4gpu` | 0.598 ms | 0.588 ms | 0.961 ms | 0.991 ms | 0.953 ms | 0.365 ms |
| `numa1-4gpu` | 0.440 ms | 0.433 ms | 0.454 ms | 0.452 ms | 0.445 ms | 0.012 ms |

Interpretation:

- `numa0-4gpu` still shows a large `profiler-only -> final-steady` jump even after the activation boundary.
- `numa1-4gpu` mostly converges once the same long measurement window is used.
- The same-socket asymmetry from the topology-controlled rerun is therefore reproduced, but it is not symmetric across both sockets.

### 2. Both groups publish and activate the same candidate at the same early boundary

| Group | Activated candidate | First publish effective call | First activate call | `wait-summary` total | sampled completion total | host fallback total | unavailable total |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `numa0-4gpu` | `ring/simple` | 5.0 | 6.0 | 3 | 57 | 1948 | 12 |
| `numa1-4gpu` | `ring/simple` | 5.0 | 5.667 | 2 | 54 | 1940 | 12 |

Interpretation:

- Candidate identity and activation timing do not explain the `numa0` vs `numa1` split: both groups publish `ring/simple` and activate around step `6`.
- Coordinator and completion traces were preserved for the `final-steady` batch, including aggregate `wait-summary` and sampled-completion counts.
- NCCL logs in both groups confirm runtime loading from the expected mounted plugin path for both profiler and tuner.

### 3. Front-half amortization alone is not enough to explain `numa0-4gpu`

- `numa0-4gpu` pre-activation is higher than post-activation (`0.991 ms` vs `0.953 ms`), so the front half is part of the cost.
- But the remaining post-activation segment is still `0.365 ms` above `profiler-only`.
- The branch therefore does not support a pure "warmup / publish / activate front-half pollution only" explanation for `numa0-4gpu`.

## Next-Step Judgment

1. `weak-online` recheck is not the explanation for the remaining jump in this change, because the batch excludes `weak-online` entirely.
2. The large persistent `numa0-4gpu` delta points more strongly at the steady tuner / coordinator path or its placement-local interaction than at generic early-window amortization.
3. Because only `numa0-4gpu` remains abnormal while `numa1-4gpu` mostly converges, socket-local placement, affinity, or representative-rank locality should remain an active explanation boundary for the next change.
