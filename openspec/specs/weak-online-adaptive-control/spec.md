# weak-online-adaptive-control Specification

## Purpose
Define the first weak-online adaptive control loop for communicator-domain policy selection, bounded observation windows, and conservative coordinator-driven switching.

## Requirements
### Requirement: Communicator-domain weak-online control
The system SHALL define the first weak-online policy domain as a single NCCL communicator, and SHALL require all ranks in that communicator to use the same committed adaptive policy for the same collective key.

#### Scenario: Shared committed policy within a communicator
- **WHEN** multiple ranks participate in the same collective through the same communicator and evaluate the same weak-online collective key
- **THEN** the system SHALL treat those ranks as one policy domain
- **AND** the system SHALL publish and apply one shared committed policy for that key within that communicator

#### Scenario: Communicator identity bounds policy consistency
- **WHEN** the same collective shape appears in a different communicator
- **THEN** the system SHALL allow that communicator to maintain an independent weak-online policy state
- **AND** the system SHALL NOT require policy decisions to be shared across communicators

### Requirement: Windowed observation lifecycle
The system SHALL evaluate weak-online policy updates through bounded observation windows rather than perpetual candidate rotation.

#### Scenario: Warmup then steady
- **WHEN** a weak-online collective key is first observed within a communicator domain
- **THEN** the system SHALL open a bounded warmup window for that key
- **AND** after warmup the system SHALL enter a steady period with a committed policy or default fallback

#### Scenario: Recheck after steady interval
- **WHEN** a key has remained in steady state for its configured recheck interval
- **THEN** the system SHALL open a bounded recheck window
- **AND** the system SHALL avoid continuous candidate rotation outside warmup or recheck windows

### Requirement: Versioned policy and observation state
The system SHALL separate committed policy versioning from observation-window tracking.

#### Scenario: Epoch identifies committed policy version
- **WHEN** the coordinator publishes a new committed policy for a collective key
- **THEN** the system SHALL assign or advance a policy `epoch` for that key
- **AND** subsequent hot-path reads SHALL use the committed policy associated with that epoch

#### Scenario: Window identifier tracks one observation round
- **WHEN** the system opens a warmup or recheck window for a collective key
- **THEN** the system SHALL assign a `window_id` to that observation round
- **AND** the system SHALL use that `window_id` to distinguish summaries from different observation rounds

#### Scenario: Recheck interval does not change committed version
- **WHEN** the system schedules the next recheck for a steady policy
- **THEN** it SHALL track that schedule separately from the committed policy `epoch`
- **AND** advancing the recheck schedule alone SHALL NOT imply a policy version change

### Requirement: Minimal window summary
The system SHALL summarize weak-online observations as bounded window-level aggregates rather than as full raw per-event logs.

#### Scenario: Window summary fields
- **WHEN** the observer reports a completed weak-online window
- **THEN** the summary SHALL include at least the collective `key`, `observed_epoch`, `window_id`, `candidate`, `sample_count`, aggregated latency, aggregated bandwidth, and candidate unavailability information

#### Scenario: No raw-event dependency for switching
- **WHEN** the coordinator decides whether to keep or switch a committed policy
- **THEN** it SHALL rely on window-level summaries rather than requiring full raw event histories

### Requirement: External coordinator adjudicates switching
The system SHALL perform weak-online switch decisions through a hot-path-external coordinator that consumes window summaries and publishes committed policies.

#### Scenario: Coordinator publishes committed policy
- **WHEN** the coordinator has enough valid summary data for a collective key
- **THEN** it SHALL publish either a retained committed policy or a new committed policy for that key
- **AND** the published result SHALL include the next committed candidate and policy `epoch`

#### Scenario: Hot path does not wait for coordinator
- **WHEN** the tuner hot path evaluates a collective while the coordinator has not yet produced a newer policy
- **THEN** the tuner SHALL continue using the latest committed policy or default fallback
- **AND** the hot path SHALL NOT block waiting for coordinator output

### Requirement: Conservative switching gates
The system SHALL switch weak-online policies only when evidence is sufficient, stable, and materially better than the current steady policy.

#### Scenario: Switch only with sufficient evidence
- **WHEN** a challenger candidate does not have enough samples, does not sustain its advantage, or does not exceed the configured switch threshold
- **THEN** the coordinator SHALL keep the existing committed steady policy

#### Scenario: Switch with sufficient stable advantage
- **WHEN** a challenger candidate has sufficient samples, maintains an advantage across the window, and exceeds the configured switch threshold
- **THEN** the coordinator SHALL be allowed to publish that candidate as the next committed steady policy

### Requirement: Conservative hold and fallback behavior
The system SHALL prefer holding the previous committed policy or falling back to default behavior over speculative switching.

#### Scenario: Incomplete coverage holds steady policy
- **WHEN** a weak-online observation window does not provide the required summary coverage for a committed policy decision
- **THEN** the coordinator SHALL retain the previous committed steady policy if one exists

#### Scenario: No committed policy falls back to default
- **WHEN** a key has not yet produced enough valid data to commit a policy
- **THEN** the system SHALL preserve default NCCL behavior or an explicitly configured default fallback for that key

#### Scenario: Stale summaries cannot drive new switching
- **WHEN** a window summary arrives for an older observed epoch after a newer committed policy has already been published
- **THEN** the system SHALL NOT use that stale summary to change the newer committed policy
