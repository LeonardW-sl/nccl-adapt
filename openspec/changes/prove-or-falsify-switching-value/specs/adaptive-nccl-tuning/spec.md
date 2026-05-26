## MODIFIED Requirements

### Requirement: Tuner affects subsequent collectives
The system SHALL use tuner decisions only to influence collectives selected after profiler observations or communicator-domain coordinator updates have produced a shared committed policy for the matching collective key, and only after that policy has reached its activation boundary.

#### Scenario: Same-key switching remains future-directed
- **WHEN** the tuner activates or publishes a newer policy for a matching collective key
- **THEN** that policy SHALL only affect later collectives in the same repeated key domain
- **AND** it SHALL NOT be interpreted as mutating an already in-flight collective

### Requirement: Experiment comparison modes
The system SHALL provide a reproducible and interpretation-safe way to compare baseline, profiler-only, static tuner, and adaptive tuner modes for NCCL allreduce experiments.

#### Scenario: Weak-online claims compare against the best non-switching alternative
- **WHEN** an experiment or evidence claims that `weak-online` proves switching value
- **THEN** the claim SHALL compare `weak-online` against the best available non-switching alternative, including `best static candidate`, `best piecewise-static policy`, and `final-steady` when applicable
- **AND** `weak-online > baseline` alone SHALL NOT be sufficient to establish switching value
