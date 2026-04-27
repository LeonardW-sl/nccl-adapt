## MODIFIED Requirements

### Requirement: Tuner affects subsequent collectives
The system SHALL use tuner decisions only to influence collectives selected after profiler observations or weak-online coordinator updates have produced a committed policy for the matching collective key.

#### Scenario: Tune future matching collective from committed policy
- **WHEN** a later collective matches a key with a committed weak-online or steady policy
- **THEN** the tuner SHALL use that committed policy to modify the cost table or channel count for the later collective

#### Scenario: Do not mutate current collective
- **WHEN** a collective has already been selected or enqueued
- **THEN** the system SHALL NOT attempt to change that collective's algorithm, protocol, or channels

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
The system SHALL use local performance statistics only as input to weak-online summaries and coordinator decisions, without allowing any rank to switch committed policy independently.

#### Scenario: Record local samples for summaries
- **WHEN** profiler or observer completion data is available for a sampled weak-online event
- **THEN** the system SHALL update local window-level summary inputs for the matching key and candidate

#### Scenario: Avoid local direct switching
- **WHEN** one rank locally observes a better candidate before other ranks or before the coordinator has published a newer policy
- **THEN** that rank SHALL NOT independently switch the committed policy for subsequent collectives

### Requirement: Safe tuner fallback
The tuner SHALL preserve NCCL default behavior when no valid committed adaptive policy applies, and SHALL prefer default behavior over speculative or unavailable switching.

#### Scenario: No committed policy
- **WHEN** `getCollInfo` is called for a collective key without a committed weak-online or steady policy
- **THEN** the tuner SHALL leave NCCL's default selection available

#### Scenario: Unsupported committed candidate
- **WHEN** the committed candidate for a collective key is marked unavailable in NCCL's cost table
- **THEN** the tuner SHALL NOT force that candidate
- **AND** the tuner SHALL fall back to default behavior for that call while preserving weak-online safety rules

### Requirement: Non-blocking tuner hot path
The tuner SHALL keep weak-online control logic out of NCCL's algorithm-selection hot path, and SHALL use committed-policy reads rather than hot-path coordination.

#### Scenario: Hot path reads committed policy only
- **WHEN** `getCollInfo` executes in weak-online mode
- **THEN** the tuner SHALL read the latest committed policy for the key, validate candidate availability, and apply or fall back
- **AND** it SHALL NOT perform observation-window adjudication in the hot path

#### Scenario: No coordinator wait in tuner callback
- **WHEN** a newer weak-online policy has not yet been published by the coordinator
- **THEN** the tuner SHALL continue with the latest committed policy or default behavior
- **AND** it SHALL NOT wait for coordinator output, remote ranks, or out-of-band control completion

#### Scenario: No hot-path heavyweight work in steady-first mode
- **WHEN** `getCollInfo` executes for a key outside an active observation window
- **THEN** the tuner SHALL avoid per-call candidate construction, per-call summary recomputation, and hot-path diagnostic logging by default

### Requirement: Experiment comparison modes
The system SHALL provide a reproducible way to compare baseline, profiler-only, final steady, and weak-online modes for NCCL allreduce experiments.

#### Scenario: Final steady experiment
- **WHEN** the benchmark runs with a committed steady policy and without weak-online recheck windows
- **THEN** the result SHALL capture low-overhead steady-state policy performance

#### Scenario: Weak-online experiment
- **WHEN** the benchmark runs in weak-online mode with bounded warmup and recheck windows
- **THEN** the result SHALL capture low-frequency observation overhead, committed policy switching behavior, and final performance relative to baseline and final steady
