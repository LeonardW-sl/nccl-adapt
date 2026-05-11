## MODIFIED Requirements

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
