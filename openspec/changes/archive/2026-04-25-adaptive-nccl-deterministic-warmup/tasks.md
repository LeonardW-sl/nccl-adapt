## 1. Plugin Structure

- [x] 1.1 Choose the adaptive plugin location under `nccl/plugins` and keep NCCL core source files unchanged
- [x] 1.2 Add build files to produce `libnccl-adaptive.so`
- [x] 1.3 Export `ncclTunerPlugin_v5` from the adaptive plugin
- [x] 1.4 Export profiler symbol support using the existing inspector/profiler API surface
- [x] 1.5 Add plugin load documentation for `NCCL_PROFILER_PLUGIN` and `NCCL_TUNER_PLUGIN`

## 2. Shared Policy State

- [x] 2.1 Define the policy key using collective type, size-bin, nRanks, and nNodes
- [x] 2.2 Define candidate strategies for allreduce warmup, including default, ring/simple, tree/simple, and ring/ll128 where available
- [x] 2.3 Implement in-process `PolicyStore` shared by profiler and tuner callbacks
- [x] 2.4 Add locking or atomic access around `PolicyStore` updates and reads
- [x] 2.5 Add fallback behavior for missing keys, unavailable candidates, and disabled adaptive mode
- [x] 2.6 Ensure tuner policy reads use non-blocking or bounded access with immediate fallback
- [x] 2.7 Keep cross-process shared memory, mmap, socket, or database coordination out of the first implementation path

## 3. Profiler Path

- [x] 3.1 Capture collective metadata from `ncclProfileColl` events
- [x] 3.2 Capture kernel completion timing from `ncclProfileKernelCh` events
- [x] 3.3 Compute latency and bandwidth metrics per completed collective
- [x] 3.4 Associate observed metrics with the policy key and candidate active for that sequence phase
- [x] 3.5 Emit compact JSON or log records containing mode, key, sequence, candidate, selected algo/proto/channels, and metrics
- [x] 3.6 Keep profiler callbacks free of blocking waits, stream synchronization, and heavy formatting
- [x] 3.7 Use bounded event storage or graceful event dropping under high event rate

## 4. Tuner Path

- [x] 4.1 Map `getCollInfo` inputs to the same policy key used by profiler recording
- [x] 4.2 Implement deterministic warmup candidate selection based on key and sequence phase
- [x] 4.3 Modify the cost table only when the selected algorithm/protocol entry is not `NCCL_ALGO_PROTO_IGNORE`
- [x] 4.4 Preserve NCCL default behavior for the `default` candidate and invalid candidates
- [x] 4.5 Override `nChannels` only when the selected policy explicitly specifies channels
- [x] 4.6 Verify `getCollInfo` performs no file I/O, network I/O, sleep, CUDA synchronization, or rank waiting

## 5. Rank Consistency

- [x] 5.1 Ensure warmup selection does not depend on local asynchronous profiler completion order
- [x] 5.2 Ensure all ranks derive the same candidate for the same key and phase
- [x] 5.3 Add diagnostic logging that shows key, phase, and candidate per rank
- [x] 5.4 Document that multi-node online coordination is out of scope for the first implementation

## 6. Experiment Harness

- [x] 6.1 Provide a baseline run mode with adaptive plugins disabled
- [x] 6.2 Provide a profiler-only run mode with tuner disabled
- [x] 6.3 Provide a static tuner run mode with a fixed candidate
- [x] 6.4 Provide an adaptive run mode with profiler and tuner enabled
- [x] 6.5 Run or document allreduce benchmark parameters for repeated message sizes and enough iterations to cover warmup
- [x] 6.6 Record `/dev/shm`, memlock, `NCCL_CUMEM_HOST_ENABLE`, and NCCL debug settings used for each run
- [x] 6.7 Document container launch prerequisites such as `--shm-size=1g` and `--ulimit memlock=-1`

## 7. Verification

- [x] 7.1 Build the adaptive plugin successfully
- [x] 7.2 Verify NCCL loads the profiler and tuner plugin symbols
- [x] 7.3 Verify tuner decisions affect later collectives but do not attempt to mutate already selected collectives
- [x] 7.4 Verify profiler-only overhead relative to baseline
- [x] 7.5 Verify adaptive mode emits warmup decisions and performance metrics
- [x] 7.6 Verify no NCCL core source files were modified
- [x] 7.7 Verify the adaptive plugin does not synchronize user CUDA streams in callbacks
- [x] 7.8 Verify fallback behavior when policy state is unavailable or contended

## 8. Reporting

- [x] 8.1 Summarize baseline, profiler-only, static tuner, and adaptive tuner results
- [x] 8.2 Include selected strategy, latency, algbw, busbw, and overhead in the comparison
- [x] 8.3 Record known limitations and next steps for multi-node coordination or broader collective coverage
- [x] 8.4 Include observed shared-memory, memlock, or cuMem host allocation issues if they occur during experiments
