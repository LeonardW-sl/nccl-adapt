# adaptive-nccl-tuning Specification

## Purpose
Define the adaptive NCCL plugin behavior for profiler-driven tuning, weak-online control, and communicator-domain shared policy activation without modifying NCCL core source files.
## Requirements
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
The system SHALL use tuner decisions only to influence collectives selected after profiler observations or communicator-domain coordinator updates have produced a shared committed policy for the matching collective key, and only after that policy has reached its activation boundary.

#### Scenario: Tune future matching collective from shared committed policy
- **WHEN** a later collective matches a key with a shared committed policy published for its communicator-domain and that policy has reached its activation boundary
- **THEN** the tuner SHALL use that shared committed policy to modify the cost table or channel count for the later collective

#### Scenario: Do not mutate current collective
- **WHEN** a collective has already been selected or enqueued
- **THEN** the system SHALL NOT attempt to change that collective's algorithm, protocol, or channels

#### Scenario: Activation evaluates same policy domain
- **WHEN** the tuner evaluates whether a newer shared committed policy is active
- **THEN** it SHALL compare the activation boundary against the local call index for that same communicator plus matching key domain
- **AND** it SHALL NOT use collectives from other keys to advance that policy's activation decision

#### Scenario: Hot path reconstructs domain only from stable fields
- **WHEN** `getCollInfo` reconstructs the policy domain for shared publication lookup
- **THEN** it SHALL use only the stable first-version identity fields available on the tuner path
- **AND** it SHALL NOT depend on observation-only metadata that is unavailable or ambiguous on the hot path

### Requirement: Deterministic warmup schedule
The system SHALL use a deterministic warmup schedule to keep ranks aligned during warmup and recheck windows, and SHALL stop continuous rotation once a committed steady policy exists.

#### Scenario: Rank-consistent candidate selection in windows
- **WHEN** multiple ranks in the same communicator-domain evaluate the same collective key during warmup or recheck
- **THEN** each rank SHALL select the same candidate schedule based on deterministic inputs such as collective key, fixed candidate order, window phase, and configured window rules

#### Scenario: Stop continuous rotation in steady state
- **WHEN** a committed steady policy exists for a collective key
- **THEN** the tuner SHALL stop perpetual candidate rotation for that key
- **AND** collectives outside observation windows SHALL use the committed policy or default fallback

### Requirement: Performance statistics do not introduce rank divergence
The system SHALL use local performance statistics only as input to communicator-domain summary submission and coordinator publication, without allowing any rank to activate a newly committed policy independently.

#### Scenario: Record local samples for shared publication
- **WHEN** profiler or observer completion data is available for a sampled weak-online event
- **THEN** the system SHALL update local window-level summary inputs for the matching key and candidate
- **AND** it SHALL submit those inputs to the communicator-domain coordinator path rather than directly publishing a new committed policy

#### Scenario: Avoid local direct activation
- **WHEN** one rank locally observes a better candidate before other ranks or before the communicator-domain coordinator has published and activated a newer shared policy
- **THEN** that rank SHALL NOT independently activate the newer committed policy for subsequent collectives

#### Scenario: Partial profiler kernel coverage still closes the sampled record
- **WHEN** the profiler sees host-side collective completion but only a subset of expected kernel-channel callbacks for that collective
- **THEN** the system SHALL still finalize one conservative local completion record for the attached sampled plan once the observed kernel callbacks have drained
- **AND** it SHALL use that record only as communicator-domain summary input rather than treating the missing kernel callbacks as a reason to skip summary submission entirely

#### Scenario: Zero kernel coverage falls back to host-stop timing
- **WHEN** the profiler receives no kernel-channel callbacks for a collective but does observe host-side collective stop
- **THEN** the system SHALL fall back to host-stop timing for that local completion record
- **AND** it SHALL prefer submitting a conservative summary input over silently dropping the sampled collective from the communicator-domain publication pipeline

### Requirement: Safe tuner fallback
The tuner SHALL preserve NCCL default behavior or the previously active shared committed policy when no valid active shared policy applies, and SHALL prefer hold/default behavior over speculative or early activation.

#### Scenario: Shared policy not yet active
- **WHEN** `getCollInfo` sees a newer published communicator-domain policy whose activation boundary has not yet been reached
- **THEN** the tuner SHALL continue using the previously active policy or default NCCL behavior for that call

#### Scenario: Unsupported published candidate
- **WHEN** the active shared committed candidate for a collective key is marked unavailable in NCCL's cost table
- **THEN** the tuner SHALL NOT force that candidate
- **AND** the tuner SHALL fall back to default behavior for that call while preserving communicator-domain coordinator safety rules

### Requirement: Non-blocking tuner hot path
The tuner SHALL keep cross-rank coordinator transport out of NCCL's algorithm-selection hot path, and SHALL use direct reads of published communicator-domain state rather than per-collective coordinator round-trips.

#### Scenario: Hot path reads published state directly
- **WHEN** `getCollInfo` executes for a communicator-domain key
- **THEN** the tuner SHALL read the currently published policy state directly from local process-visible coordinator state
- **AND** it SHALL NOT require a per-call request/response exchange with the coordinator representative

#### Scenario: Coordinator transport failure does not block hot path
- **WHEN** the representative or out-of-band coordinator transport is unavailable while a collective is being selected
- **THEN** the tuner SHALL continue using the last active shared policy or default fallback
- **AND** it SHALL NOT block waiting for coordinator transport recovery

#### Scenario: Hot path treats call index as eligibility clock
- **WHEN** `getCollInfo` checks whether a complete published policy can become active
- **THEN** it SHALL treat the local domain-scoped call index only as an activation eligibility clock
- **AND** it SHALL NOT assume that local index alone proves instantaneous cross-rank synchronization

#### Scenario: No synchronization in tuner callback
- **WHEN** `getCollInfo` is executing
- **THEN** the tuner SHALL NOT perform file I/O, network I/O, CUDA stream synchronization, CUDA event synchronization, sleep, or wait for other ranks

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
The system SHALL provide a reproducible and interpretation-safe way to compare baseline, profiler-only, static tuner, and adaptive tuner modes for NCCL allreduce experiments.

#### Scenario: Baseline experiment
- **WHEN** the benchmark runs with adaptive plugins disabled
- **THEN** the result SHALL capture default NCCL performance for the configured allreduce workload
- **AND** the run SHALL record enough metadata to compare that result against other replicates and mode orders

#### Scenario: Profiler-only experiment
- **WHEN** the benchmark runs with the profiler enabled and tuner disabled
- **THEN** the result SHALL capture profiler overhead relative to baseline
- **AND** the comparison SHALL be made within an experiment protocol that controls replicate count and mode order

#### Scenario: Static tuner experiment
- **WHEN** the benchmark runs with a fixed tuner strategy
- **THEN** the result SHALL capture performance for that fixed algorithm/protocol/channel policy
- **AND** the experiment protocol SHALL allow that result to be used to validate a candidate discovered by adaptive learning

#### Scenario: Adaptive tuner experiment
- **WHEN** the benchmark runs with profiler and tuner enabled
- **THEN** the result SHALL capture warmup decisions, selected policies, and performance metrics for comparison against baseline
- **AND** the result SHALL distinguish mechanism-cost evidence from policy-quality evidence rather than collapsing both into one undifferentiated conclusion

#### Scenario: Weak-online comparison reports segmented behavior
- **WHEN** the adaptive tuner runs in weak-online mode
- **THEN** the reported results SHALL distinguish steady-state behavior from recheck-window behavior
- **AND** the comparison SHALL NOT rely solely on a single overall mean to characterize weak-online overhead

