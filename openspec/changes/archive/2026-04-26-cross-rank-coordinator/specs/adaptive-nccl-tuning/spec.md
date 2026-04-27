## MODIFIED Requirements

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
