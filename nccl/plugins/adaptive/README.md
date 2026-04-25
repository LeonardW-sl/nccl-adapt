# Adaptive NCCL Plugin

This directory contains a standalone `libnccl-adaptive.so` that exports both:

- `ncclProfiler_v5`
- `ncclTunerPlugin_v5`

The implementation stays inside `nccl/plugins` and does not modify NCCL core source files.

## Behavior

- The tuner and profiler share an in-process `PolicyStore`.
- The policy key uses collective type, size bin, `nRanks`, and `nNodes`.
- Allreduce candidates are deterministic and ordered as:
  - `default`
  - `ring/simple`
  - `tree/simple`
  - `ring/ll128`
- The tuner path uses non-blocking `try_lock` access. On contention or invalid candidates it falls back to NCCL defaults immediately.
- The profiler path records collective metadata on `ncclProfileColl` and completion timing on `ncclProfileKernelCh`.
- Callback paths avoid file I/O, network I/O, sleeps, and CUDA stream synchronization.
- Cross-process policy sharing is intentionally out of scope for the first implementation.

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
export NCCL_ADAPTIVE_MODE=adaptive
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

## Suggested Allreduce Benchmark Parameters

Use repeated message sizes and enough iterations to cover the deterministic warmup rotation. A reasonable starting point with `all_reduce_perf` is:

```bash
./build/all_reduce_perf -b 1K -e 256M -f 2 -g 8 -n 100 -w 20
```

- `-n 100` leaves enough post-warmup iterations after the four-candidate rotation.
- `-w 20` gives NCCL startup and communicator warmup time before measurements.
- `-f 2` covers repeated powers-of-two size bins that map cleanly onto the plugin policy key.

## Diagnostics

Recommended run metadata to capture alongside benchmark output:

- `NCCL_DEBUG`
- `NCCL_DEBUG_SUBSYS`
- `NCCL_CUMEM_HOST_ENABLE`
- `/dev/shm` size
- `ulimit -l`

Container prerequisites for reproducible NCCL runs:

- `--shm-size=1g`
- `--ulimit memlock=-1`

If NCCL reports shared-memory or cuMem host allocation issues, retry with:

```bash
export NCCL_CUMEM_HOST_ENABLE=0
```

## Runtime Verification - 2026-04-25

All runs below used `nvcr.io/nvidia/pytorch:26.03-py3`, 8 visible GPUs,
`torchrun --nproc-per-node=8`, 8 MiB allreduce messages, 4 warmup iterations,
and 8 measured iterations. Logs and environment captures are in
`results-torch-20260425/`.

| Mode | Plugins | Strategy | Mean avg latency | Over baseline |
| --- | --- | --- | ---: | ---: |
| baseline | none | NCCL default, observed RING/SIMPLE | 0.591 ms | 1.00x |
| profiler-only | profiler | observe only, no tuner mutation | 4.528 ms | 7.66x |
| static-tuner | profiler+tuner | fixed `ring/simple`, observed RING/SIMPLE | 2.518 ms | 4.26x |
| adaptive-tuner | profiler+tuner | deterministic warmup rotation | 2.069 ms | 3.50x |

Adaptive mode emitted rank-consistent decisions for the same key:

```text
phase=0 candidate=default
phase=1 candidate=ring/simple
phase=2 candidate=tree/simple
phase=3 candidate=ring/ll128
phase=4 candidate=default
```

Representative profiler records for `allreduce:4194304-8388608:r8:n1` include
the selected algorithm/protocol, channel count, latency, algbw, and busbw:

```text
mode=adaptive seq=8  candidate=default     selected=RING/SIMPLE channels=4 latency_us=1654 algbw_gbps=5.072 busbw_gbps=8.875
mode=adaptive seq=9  candidate=ring/simple selected=RING/SIMPLE channels=4 latency_us=1755 algbw_gbps=4.780 busbw_gbps=8.365
mode=adaptive seq=10 candidate=tree/simple selected=TREE/SIMPLE channels=4 latency_us=1526 algbw_gbps=5.497 busbw_gbps=9.620
mode=adaptive seq=11 candidate=ring/ll128  selected=RING/SIMPLE channels=4 latency_us=2563 algbw_gbps=3.273 busbw_gbps=5.728
```

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

- These results are single-node only; multi-node coordination remains out of
  scope for this first implementation.
- The short torch smoke is intended to validate behavior, not establish final
  performance. `NCCL_DEBUG=INFO` and profiler logging add visible overhead.
- `all_reduce_perf` in the tested container still fails independently with
  `Cuda failure 101 'invalid device ordinal'`, so torch distributed remains the
  active benchmark path.
- No shared-memory, memlock, or cuMem host allocation failure was observed with
  the run settings above.
