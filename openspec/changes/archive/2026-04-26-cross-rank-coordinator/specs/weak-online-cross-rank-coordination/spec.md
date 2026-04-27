## ADDED Requirements

### Requirement: Shared committed policy publication per communicator-domain
The system SHALL publish one shared committed policy for each weak-online communicator-domain, rather than allowing each rank process to commit its own local policy independently.

#### Scenario: Representative publishes one committed policy
- **WHEN** a communicator-domain has received enough valid window summaries for a collective key
- **THEN** the coordinator SHALL publish exactly one committed policy record for that communicator-domain and key
- **AND** all ranks in that communicator-domain SHALL treat that record as the only valid committed policy source for subsequent activation

#### Scenario: Different communicators publish independently
- **WHEN** two different communicators observe the same collective key shape
- **THEN** each communicator-domain SHALL maintain an independent committed policy publication record
- **AND** the system SHALL NOT require one communicator to reuse another communicator's published policy

#### Scenario: First-version representative is fixed communicator rank0
- **WHEN** the first version assigns publication ownership for a communicator-domain
- **THEN** communicator rank0 SHALL act as the only representative writer for the shared committed policy record
- **AND** non-representative ranks SHALL remain limited to summary submission

### Requirement: Shared coordinator state is host-visible and process-shared
The system SHALL store communicator-domain coordinator publication state in process-shared host-visible state that all local rank processes can read directly, and SHALL NOT require GPU object sharing to exchange coordinator metadata.

#### Scenario: Local ranks read one shared published record
- **WHEN** multiple local rank processes belong to the same communicator-domain
- **THEN** they SHALL read the same published committed policy record from shared host-side coordinator state
- **AND** they SHALL NOT require per-rank private committed policy copies to determine activation

#### Scenario: Coordinator metadata does not require CUDA IPC objects
- **WHEN** the system exchanges coordinator metadata across local rank processes
- **THEN** it SHALL use host-side process-shared state for that metadata
- **AND** it SHALL NOT require CUDA IPC handles for device memory or CUDA events to publish the committed policy record

### Requirement: Shared coordinator state is bound to communicator lifecycle
The system SHALL bind shared coordinator state to the lifetime of a specific communicator-domain instance, and SHALL prevent stale state from an earlier communicator instance from being reused as active policy state for a later communicator.

#### Scenario: New communicator instance does not reuse stale publication
- **WHEN** a communicator-domain is created after an earlier communicator with the same collective shapes has already been finalized
- **THEN** the new communicator-domain SHALL start with fresh coordinator publication state for its own lifetime
- **AND** it SHALL NOT treat stale shared state from the earlier communicator instance as an active committed policy

#### Scenario: Finalized communicator stops publishing active state
- **WHEN** a communicator-domain is finalized
- **THEN** its shared coordinator state SHALL become invalid for future activation decisions
- **AND** later readers SHALL NOT activate policies from that finalized communicator instance

### Requirement: Rank-local observation submits summaries only
The system SHALL restrict non-coordinator ranks to submitting observation summaries, and SHALL NOT allow rank-local observation state to directly publish a new committed policy.

#### Scenario: Local rank submits summary
- **WHEN** a non-representative rank completes a warmup or recheck window
- **THEN** that rank SHALL publish only its window summary inputs to the communicator-domain coordinator state
- **AND** it SHALL NOT directly replace the committed policy for that key

#### Scenario: Local better result cannot directly switch policy
- **WHEN** one rank observes a locally better challenger candidate before the communicator-domain coordinator has published a newer shared policy
- **THEN** that rank SHALL continue using the currently published policy or default fallback
- **AND** it SHALL NOT directly activate the challenger candidate for later collectives

### Requirement: Published policy and activation boundary are separate
The system SHALL separate committed policy publication from committed policy activation.

#### Scenario: Published policy contains effective boundary
- **WHEN** the coordinator publishes a new committed policy for a communicator-domain key
- **THEN** the published record SHALL include both the committed policy version and an activation boundary that all ranks can evaluate consistently

#### Scenario: Activation boundary uses explicit lag beyond publication
- **WHEN** the coordinator publishes a committed policy at a publication boundary for a communicator-domain key
- **THEN** the activation boundary SHALL be strictly later than that publication boundary
- **AND** the first version SHALL define that boundary using an explicit activation lag rather than treating publication as immediate activation

#### Scenario: First-version activation lag defaults to two domain calls
- **WHEN** the first version computes `effective_call_index` from `published_call_index`
- **THEN** it SHALL use an explicit activation lag with a default value of `2`
- **AND** it SHALL NOT use an activation lag smaller than `2` by default

#### Scenario: Policy not active before effective boundary
- **WHEN** a rank reads a newer published committed policy whose activation boundary has not yet been reached
- **THEN** that rank SHALL continue using the previously active committed policy or default fallback
- **AND** it SHALL NOT activate the newer policy early

#### Scenario: All ranks activate after the same boundary
- **WHEN** multiple ranks in the same communicator-domain observe that a published policy has reached its activation boundary
- **THEN** those ranks SHALL become eligible to activate the same committed policy version
- **AND** the system SHALL NOT allow some ranks to treat the policy as active while other ranks still treat it as unpublished for the same boundary

### Requirement: Reader sees a self-consistent publication snapshot
The system SHALL ensure that a tuner reader either observes a self-consistent published policy snapshot or falls back conservatively, rather than activating a partially updated record.

#### Scenario: Reader detects incomplete publication update
- **WHEN** a rank reads communicator-domain published state while the representative is in the middle of updating that record
- **THEN** the rank SHALL reject that incomplete snapshot for activation purposes
- **AND** it SHALL continue using the last active policy or default fallback

#### Scenario: Reader activates only from a complete record
- **WHEN** a rank activates a newer communicator-domain committed policy
- **THEN** that activation SHALL be based on one complete published policy record
- **AND** it SHALL NOT combine fields from different publication versions into one activation decision

#### Scenario: First-version publication flips active record after full write
- **WHEN** the first-version representative publishes a newer committed policy record
- **THEN** it SHALL write that policy into an inactive published-record buffer before making it visible to readers
- **AND** it SHALL expose the newer policy to readers only by flipping the active published-record selection after the write is complete

### Requirement: Activation uses a domain-scoped eligibility clock
The system SHALL evaluate activation against a domain-scoped local call index that serves as a conservative eligibility clock, not as proof of instantaneous global synchronization.

#### Scenario: Local rank becomes eligible only after domain boundary
- **WHEN** a rank reads a complete published committed policy for a communicator-domain key
- **THEN** that rank SHALL use the local call index for that same publication domain to decide whether the activation boundary has been reached
- **AND** it SHALL NOT use an unrelated communicator-global clock to activate that policy

#### Scenario: Eligibility clock does not imply global simultaneity
- **WHEN** multiple ranks independently evaluate the same published activation boundary
- **THEN** the system SHALL treat the domain-scoped local call index only as a local eligibility test
- **AND** it SHALL NOT require that index alone to prove all ranks observed the activation boundary at the same instant

### Requirement: First-version activation domain matches communicator plus exact key
The system SHALL scope first-version shared publication and activation to the same communicator-domain used for committed-policy publication, using communicator plus exact tuning key as the minimum honest domain.

#### Scenario: Exact key defines first-version activation domain
- **WHEN** a committed policy is published for a communicator and tuning key
- **THEN** the activation boundary for that policy SHALL be evaluated within that same communicator plus exact key domain
- **AND** collectives with different keys SHALL NOT advance that policy's activation clock

#### Scenario: Broader canonicalized domains are not assumed by default
- **WHEN** multiple exact keys appear related but have not been proven equivalent for applicability and activation safety
- **THEN** the first version SHALL keep them in separate publication and activation domains
- **AND** it SHALL NOT merge them into a broader key-class by default

#### Scenario: First-version exact key uses only jointly visible domain fields
- **WHEN** the first version defines the tuning key used for shared publication and activation
- **THEN** that key SHALL be composed only from fields that both the profiler path and the tuner hot path can compute consistently
- **AND** it SHALL NOT depend on observation-only fields that the activation reader cannot reconstruct reliably

### Requirement: First-version policy domain separates identity from observation
The system SHALL distinguish between fields that define the first-version policy domain identity and fields that are retained only for observation, diagnostics, or later refinement.

#### Scenario: Policy domain identity uses stable shared fields
- **WHEN** the system computes the first-version publication and activation domain
- **THEN** it SHALL include communicator identity, collective type, size bucket, rank count, and node count
- **AND** those fields SHALL be sufficient to select the shared publication record for activation

#### Scenario: Observation-only fields do not fragment activation domain
- **WHEN** the system records additional collective metadata such as datatype, count decomposition, reduce-op metadata, root metadata, `numPipeOps`, or `regBuff`
- **THEN** it MAY retain those fields for observation or future refinement
- **AND** it SHALL NOT require them to define the first-version activation domain by default

#### Scenario: Candidate state does not define domain identity
- **WHEN** the system records candidate choice or runtime status such as algorithm, protocol, channels, availability, `epoch`, `windowId`, `callIndex`, or sequence number
- **THEN** those fields SHALL describe publication state, candidate state, or runtime progress
- **AND** they SHALL NOT redefine which communicator-domain key a committed policy belongs to

### Requirement: First-version size dimension prefers honest buckets over raw-byte exact matching
The system SHALL use a size-bucketed message-size dimension for first-version publication and activation domains, rather than requiring raw-byte exact matching by default.

#### Scenario: Size bucket keeps activation domain convergent
- **WHEN** the first version groups collectives for shared publication and activation
- **THEN** it SHALL use a size bucket that both profiler and tuner can compute consistently
- **AND** it SHALL prefer a bucketed size dimension over raw-byte exact matching when raw matching would make the activation domain too sparse to converge

#### Scenario: Raw-byte exact size is not assumed by default
- **WHEN** two collectives differ slightly in raw byte count but still map to the same first-version size bucket
- **THEN** the system MAY treat them as belonging to the same first-version activation domain
- **AND** it SHALL NOT require raw-byte equality as a prerequisite for shared publication unless a later refinement explicitly narrows the bucket design

#### Scenario: First-version size bucket uses deterministic power-of-two partition
- **WHEN** the first version computes the size dimension for a publication and activation domain
- **THEN** it SHALL use a deterministic power-of-two bucket partition
- **AND** later refinements SHALL narrow that partition only when repeated within-bucket policy disagreement shows that the current bucket is no longer honest enough

#### Scenario: Repeated lower-upper disagreement triggers deterministic sub-bucket refinement
- **WHEN** validation shows that the lower and upper sub-ranges of one power-of-two bucket prefer different committed candidates across at least two recheck cycles
- **THEN** a later refinement SHALL split that bucket into two deterministic sub-buckets
- **AND** it SHALL prefer that deterministic sub-bucket refinement over falling back to raw-byte exact matching by default

### Requirement: Conservative hold on incomplete or stale coordinator inputs
The system SHALL prefer retaining the current shared committed policy over publishing a speculative or stale replacement.

#### Scenario: Incomplete summary coverage holds current policy
- **WHEN** the communicator-domain coordinator has not yet received the required summary coverage for a key and window
- **THEN** it SHALL retain the current published committed policy if one exists

#### Scenario: Stale observation cannot republish
- **WHEN** a summary or proposal arrives for an older `epoch` or observation round after a newer committed policy has already been published
- **THEN** the coordinator SHALL ignore that stale input for publication purposes
- **AND** it SHALL preserve the newer published policy
