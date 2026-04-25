## ADDED Requirements

### Requirement: Plugin-only adaptive tuning
The system SHALL implement adaptive NCCL communication tuning without modifying NCCL core source files.

#### Scenario: Enable adaptive tuning through plugins
- **WHEN** the user sets `NCCL_PROFILER_PLUGIN` and `NCCL_TUNER_PLUGIN` to the adaptive plugin library
- **THEN** NCCL SHALL load the profiler and tuner plugin interfaces without requiring changes to NCCL core source files

#### Scenario: Disable adaptive tuning
- **WHEN** the user unsets the adaptive plugin environment variables
- **THEN** NCCL SHALL run with its default algorithm selection behavior

### Requirement: Profiler observes collective performance
The system SHALL record enough profiler data to evaluate NCCL collective performance and the strategy used for each observed collective.

#### Scenario: Record collective metadata
- **WHEN** NCCL starts a collective event
- **THEN** the profiler SHALL record the collective type, sequence number, message size, rank metadata, selected algorithm, selected protocol, and channel count when available

#### Scenario: Record completion metrics
- **WHEN** NCCL reports kernel channel completion for a collective
- **THEN** the profiler SHALL record execution time and derived bandwidth metrics for that collective

### Requirement: Tuner affects subsequent collectives
The system SHALL use tuner decisions only to influence collectives selected after profiler observations have updated strategy state.

#### Scenario: Tune future matching collective
- **WHEN** profiler data has been recorded for a collective key and a later collective has the same key
- **THEN** the tuner SHALL use the current policy for that key to modify the cost table or channel count for the later collective

#### Scenario: Do not mutate current collective
- **WHEN** a collective has already been selected or enqueued
- **THEN** the system SHALL NOT attempt to change that collective's algorithm, protocol, or channels

### Requirement: Deterministic warmup schedule
The system SHALL use a deterministic warmup schedule so all ranks choose the same candidate strategy for the same collective key and sequence phase.

#### Scenario: Rank-consistent candidate selection
- **WHEN** multiple ranks evaluate the same collective key during warmup
- **THEN** each rank SHALL select the same candidate strategy based on deterministic inputs such as collective key, size-bin, fixed candidate order, and sequence phase

#### Scenario: Candidate trial rotation
- **WHEN** warmup is active for a collective key
- **THEN** the tuner SHALL rotate through configured candidate strategies according to the deterministic schedule

### Requirement: Performance statistics do not introduce rank divergence
The system SHALL use performance statistics for reporting and stable policy selection without allowing per-rank asynchronous observations to produce inconsistent immediate tuner choices.

#### Scenario: Record local samples
- **WHEN** profiler completion data is available on a rank
- **THEN** the system SHALL update local statistics for the matching collective key and candidate strategy

#### Scenario: Avoid per-rank immediate switching
- **WHEN** one rank observes a better local candidate before another rank
- **THEN** that rank SHALL NOT independently switch to a different immediate strategy outside the deterministic schedule

### Requirement: Safe tuner fallback
The tuner SHALL preserve NCCL default behavior when no valid adaptive policy applies.

#### Scenario: No matching policy
- **WHEN** `getCollInfo` is called for a collective key without a configured or selected policy
- **THEN** the tuner SHALL leave NCCL's default selection available

#### Scenario: Unsupported algorithm protocol pair
- **WHEN** a candidate algorithm/protocol pair is marked unavailable in NCCL's cost table
- **THEN** the tuner SHALL NOT force that pair and SHALL fall back to another valid policy or default behavior

### Requirement: Non-blocking tuner hot path
The tuner SHALL avoid introducing blocking waits or heavyweight work in NCCL's algorithm selection path.

#### Scenario: Policy read cannot block
- **WHEN** `getCollInfo` needs to read adaptive policy state
- **THEN** the tuner SHALL use bounded non-blocking access or immediately fall back to default behavior

#### Scenario: No synchronization in tuner callback
- **WHEN** `getCollInfo` is executing
- **THEN** the tuner SHALL NOT perform file I/O, network I/O, CUDA stream synchronization, CUDA event synchronization, sleep, or wait for other ranks

#### Scenario: Contended policy state
- **WHEN** policy state is temporarily locked or unavailable
- **THEN** the tuner SHALL preserve NCCL's default cost table behavior rather than waiting

### Requirement: Lightweight profiler callback path
The profiler SHALL keep NCCL profiler callbacks lightweight and bounded so monitoring does not become the communication bottleneck.

#### Scenario: Record event in callback
- **WHEN** profiler `startEvent`, `stopEvent`, or `recordEventState` is called
- **THEN** the profiler SHALL only perform bounded metadata capture, timestamp/statistic updates, or ring-buffer writes

#### Scenario: Defer heavy output work
- **WHEN** JSON, text, or summary output is needed
- **THEN** the profiler SHALL defer that work outside the hot callback path

#### Scenario: Allocation pressure
- **WHEN** profiler events arrive at high frequency
- **THEN** the profiler SHALL use bounded storage or graceful event dropping rather than unbounded allocation

### Requirement: NCCL shared-memory environment diagnostics
The experiment harness SHALL make NCCL shared-memory and pinned-memory prerequisites visible for reproducible debugging.

#### Scenario: Container shared memory check
- **WHEN** experiments run in a container
- **THEN** the harness or documentation SHALL record that `/dev/shm` size and memlock limits must be sufficient for NCCL

#### Scenario: cuMem host allocation fallback
- **WHEN** NCCL initialization or communication indicates shared-memory or cuMem host allocation failures
- **THEN** the troubleshooting guidance SHALL include using `NCCL_CUMEM_HOST_ENABLE=0` as a diagnostic fallback

#### Scenario: Debug environment capture
- **WHEN** benchmark results are collected
- **THEN** the run metadata SHALL include relevant NCCL debug and environment settings used for the run

### Requirement: CUDA stream and group semantics safety
The adaptive plugin SHALL respect NCCL's asynchronous stream and group semantics.

#### Scenario: Grouped collective enqueue
- **WHEN** collectives are issued inside `ncclGroupStart` and `ncclGroupEnd`
- **THEN** the plugin SHALL NOT assume a collective API callback means GPU execution has completed

#### Scenario: Completion timing source
- **WHEN** execution timing is needed for a collective
- **THEN** the profiler SHALL use NCCL profiler completion signals such as kernel channel events rather than synchronizing user streams

#### Scenario: Multi-stream group behavior
- **WHEN** a NCCL group uses multiple CUDA streams
- **THEN** the adaptive plugin SHALL NOT add stream synchronization that changes NCCL's existing stream dependency behavior

### Requirement: Experiment comparison modes
The system SHALL provide a reproducible way to compare baseline, profiler-only, static tuner, and adaptive tuner modes for NCCL allreduce experiments.

#### Scenario: Baseline experiment
- **WHEN** the benchmark runs with adaptive plugins disabled
- **THEN** the result SHALL capture default NCCL performance for the configured allreduce workload

#### Scenario: Profiler-only experiment
- **WHEN** the benchmark runs with the profiler enabled and tuner disabled
- **THEN** the result SHALL capture profiler overhead relative to baseline

#### Scenario: Static tuner experiment
- **WHEN** the benchmark runs with a fixed tuner strategy
- **THEN** the result SHALL capture performance for that fixed algorithm/protocol/channel policy

#### Scenario: Adaptive tuner experiment
- **WHEN** the benchmark runs with profiler and tuner enabled
- **THEN** the result SHALL capture warmup decisions, selected policies, and performance metrics for comparison against baseline
