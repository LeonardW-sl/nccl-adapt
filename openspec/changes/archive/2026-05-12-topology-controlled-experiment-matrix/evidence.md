# Topology-Controlled Adaptive Experiment Evidence

## Result Root

- Root directory: `nccl/plugins/adaptive/experiments/topology-controlled/2026-05-11-topology-controlled`
- Matrix manifest: `nccl/plugins/adaptive/experiments/topology-controlled/2026-05-11-topology-controlled/matrix-manifest.json`
- Aggregate summary: `nccl/plugins/adaptive/experiments/topology-controlled/2026-05-11-topology-controlled/topology-summary.json`

## Topology And Runtime Metadata

- Host topology snapshots:
  - `host/nvidia-smi-topo.txt`
  - `host/gpu-inventory.csv`
  - `host/numactl-H.txt`
  - `host/nic-locality.txt`
  - `host/server-idle-check.txt`
- Container runtime:
  - image tag: `nvcr.io/nvidia/pytorch:26.03-py3`
  - image id: `sha256:3c90e38f5ec51e51d1c73bd7eb3d83674a254f451147c5cadc4344314258a112`
  - repo digest: `nvcr.io/nvidia/pytorch@sha256:3c90e38f5ec51e51d1c73bd7eb3d83674a254f451147c5cadc4344314258a112`
  - launch args: `container/launch-command.txt`
  - workdir: `container/workdir.txt`
- Plugin link checks:
  - `container/ldd-version.txt`
  - `container/ldd-libnccl-adaptive.txt`
  - `container/readelf-libnccl-adaptive.txt`
  - `container/nm-libnccl-adaptive.txt`

## Experiment Parameters

- Replicates: `3`
- Mode-comparison message size: `8 MiB`
- Warmup / measure iters: `4 / 72`
- Mode-comparison `NCCL_ADAPTIVE_RECHECK_AFTER`: `64`
- Size-sweep `NCCL_ADAPTIVE_RECHECK_AFTER`: `8`
- Recheck-shift variants: `32`, `64`
- Groups:
  - `numa0-4gpu`: `CUDA_VISIBLE_DEVICES=0,1,2,3`, `NPROC_PER_NODE=4`, `CPU=0-31,64-95`
  - `numa1-4gpu`: `CUDA_VISIBLE_DEVICES=4,5,6,7`, `NPROC_PER_NODE=4`, `CPU=32-63,96-127`
  - `cross-8gpu`: `CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7`, `NPROC_PER_NODE=8`, `CPU=0-127`

## Key Findings

### 1. Baseline Smoke Separates Topology Noise From Plugin Cost

Smoke-only baseline averages:

| Group | Avg | p95 | Max |
| --- | ---: | ---: | ---: |
| `numa0-4gpu` | 0.415 ms | 0.419 ms | 0.419 ms |
| `numa1-4gpu` | 0.436 ms | 0.462 ms | 0.462 ms |
| `cross-8gpu` | 0.512 ms | 0.522 ms | 0.522 ms |

Interpretation:

- Same-socket 4-GPU baselines are stable enough to serve as a measurement floor.
- `cross-8gpu` is slower even before the plugin loads, so cross-socket topology is a real independent variable.

### 2. Mode Comparison Preserves Expected Layering, But Topology Magnifies Cost

Full 8 MiB mode-comparison averages:

| Group | `baseline` | `profiler-only` | `final-steady` | `weak-online` |
| --- | ---: | ---: | ---: | ---: |
| `numa0-4gpu` | 0.420 ms | 0.603 ms | 1.031 ms | 1.032 ms |
| `numa1-4gpu` | 0.411 ms | 0.468 ms | 0.486 ms | 0.481 ms |
| `cross-8gpu` | 0.581 ms | 0.900 ms | 1.445 ms | 1.460 ms |

Interpretation:

- `cross-8gpu` shows the largest pure baseline cost and the largest tuning-mode cost.
- `numa1-4gpu` is the cheapest placement across all four modes.
- `weak-online` steady-vs-`final-steady` deltas remain small:
  - `numa0-4gpu`: `-0.002 ms`
  - `numa1-4gpu`: `-0.005 ms`
  - `cross-8gpu`: `-0.029 ms`
- The meaningful extra `weak-online` cost is therefore tied to recheck windows, not to the steady path.

### 3. NCCL Runtime Loads The Expected Plugin Path

- `topology-summary.json` reports expected-path matches for every plugin-enabled mode:
  - `profiler-only`: profiler path match = `true`
  - `final-steady`: profiler path match = `true`, tuner path match = `true`
  - `weak-online`: profiler path match = `true`, tuner path match = `true`
- Expected path:
  - `/workspace/nccl-adapt/nccl/plugins/adaptive/libnccl-adaptive.so`

### 4. Recheck Spike Moves With `NCCL_ADAPTIVE_RECHECK_AFTER`

`cross-8gpu` recheck-shift results:

| Variant | First recheck step | Recheck phase avg |
| --- | ---: | ---: |
| `recheck-after-64` | 68 | 1.474 ms |
| `recheck-after-32` | 36 | 1.513 ms |

Interpretation:

- The first recheck window moves from step `68` to step `36` when `NCCL_ADAPTIVE_RECHECK_AFTER` changes from `64` to `32`.
- This supports attributing the visible weak-online spike window to the recheck schedule rather than to a fixed topology artifact.

### 5. Topology-Controlled Size Sweep Does Not Reproduce Bucket Divergence

All three topology groups were rerun with `SIZE_SWEEP_MBS=5,6,7` and `NCCL_ADAPTIVE_RECHECK_AFTER=8`.

Observed candidate sets:

| Group | 5 MB | 6 MB | 7 MB |
| --- | --- | --- | --- |
| `numa0-4gpu` | `ring/simple` | `ring/simple` | `ring/simple` |
| `numa1-4gpu` | `ring/simple` | `ring/simple` | `ring/simple` |
| `cross-8gpu` | `ring/simple` | `ring/simple` | `ring/simple` |

Interpretation:

- `topology-summary.json` concludes `size_bucket_conclusion = no-stable-divergence`.
- The branch currently has no reproduced evidence for either topology-sensitive bucket divergence or same-socket bucket divergence.
- The historical bucket-honesty observation remains historical only; this change does not justify a follow-up bucket-refinement change.

## Next-Step Judgment

Current evidence supports the following ordering of likely causes:

1. Environment/topology is real and measurable: `cross-8gpu` is consistently slower than same-socket placements even in pure baseline.
2. Profiler host-path loading is not the main blocker: NCCL runtime consistently loads the expected mounted plugin path.
3. Weak-online recheck behavior is the main remaining mechanism-level source of extra spikes: changing `NCCL_ADAPTIVE_RECHECK_AFTER` moves the recheck window.
4. Size bucket design is not currently implicated: the topology-controlled rerun does not reproduce candidate divergence in the `4-8 MiB` bucket.
