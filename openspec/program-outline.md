# OpenSpec Program Outline

## Purpose

This is the authoritative project-wide outline for `nccl-adapt`.

Use this page as the first recovery point when we need to know:

- the real north-star goal
- the staged proof order
- what each layer is trying to establish
- current overall progress
- why `weak-online` is not the first thing to prove

All future changes should align with this page unless they explicitly state why
they are deviating.

## North Star

The final goal is:

```text
build an online NCCL plugin that can respond to same-key phase shift
```

Meaning:

- the static key stays the same
- but runtime phase changes alter overlap or contention
- and the true best policy may change inside that same static regime

The final target is not:

- "make `weak-online` win as early as possible"
- "beat baseline on pure communication smoke at any cost"
- "prove switching before proving there is anything worth switching to"

## Three Rooms

The project should explicitly reason about three different kinds of room.

### Room 1: Communication Room

Question:

```text
Can some non-default candidate make the collective itself faster?
```

Primary signals:

- collective latency
- algorithmic bandwidth
- bus bandwidth
- selected algorithm or protocol
- channel count

### Room 2: Workload Room

Question:

```text
Does that communication-side improvement survive at the workload level,
instead of only making the collective look faster in isolation?
```

Primary signals:

- step time
- microstep time
- exposed tail
- workload throughput-adjacent boundaries

### Room 3: Switching Room

Question:

```text
Inside one static key, does runtime phase shift change the true best policy,
and can online switching capture that change better than the best
non-switching alternative?
```

Primary signals:

- stable winner change across phase variants
- same-key drift evidence
- `weak-online` versus the best non-switching policy under drift

## Program Ladder

The correct project order is:

```text
measurement fidelity
  -> communication room
    -> workload room
      -> switching room
        -> weak-online payoff
```

### Layer 0: Measurement Fidelity

Goal:

- trust the evidence before chasing small gains

Must answer:

- are nearby experiment batches internally consistent
- are comparisons aligned to the same candidate and same regime
- are we reading real signal rather than protocol drift or logging artifacts

### Layer 1: Static Communication Headroom

Goal:

- prove that some non-default policy can matter in a controlled regime

Key question:

```text
Is there a candidate that can beat NCCL default on the chosen surface?
```

Important caution:

- a negative result here only means
  `no proven headroom on the current search surface`
- it does not mean static value is impossible in general

### Layer 2: Workload-Level Validation

Goal:

- prevent a communication-local win from being misread as a real optimization

Key question:

```text
Does the candidate that wins on collective metrics also help the step?
```

Required output classes:

- `communication-only win`
- `workload-confirmed win`
- `no workload-confirmed gain`

### Layer 3: Same-Key Phase-Shift Validation

Goal:

- test the actual long-term target

Key question:

```text
Inside one static key, does phase shift change the best non-switching winner?
```

Primary drift families:

- `compute-overlap`
- `comm-interference`

Primary variants:

- `control`
- `compute-overlap-early`
- `compute-overlap-late`
- `low-comm-interference`
- `high-comm-interference`

If no stable winner change appears here, switching value is not yet proven.

### Layer 4: Weak-Online Payoff Validation

Goal:

- only after the room is proven, ask whether `weak-online` can exploit it

Key question:

```text
Can weak-online recover enough later gain to offset its earlier sampling cost?
```

This is intentionally late in the ladder.

## Why Weak-Online Is Not First

The current agreed order is:

```text
first prove room
then improve weak-online to capture that room
```

Reason:

- if room is not proven, weak-online failure is ambiguous
- if room is proven first, weak-online redesign gets a concrete target
- this prevents the branch from compensating for missing evidence with
  increasingly complex strategy logic

## Required Recording Contract

Future experiment batches should record enough information to support all room
judgments.

### Static Regime Fields

Must record:

- communicator-domain
- collective type
- message size
- size bucket
- topology group
- `nRanks`
- `nNodes`
- mode
- candidate or policy
- replicate id

### Phase Fields

Must record:

- drift family
- variant
- what single variable was changed
- whether the collective moved earlier or later
- whether interference intensity increased or decreased

### Inner-Loop Signal

Must record:

- collective latency
- algorithmic bandwidth
- bus bandwidth
- selected algorithm
- selected protocol
- channel count
- publish or activate trajectory
- winner stability across replicates

### Outer-Loop Signal

Must record:

- step time or microstep time
- exposed tail proxy
- end-of-step timing boundary
- any workload-level success metric used for adjudication

### Summary Hierarchy

Each summary should explicitly report:

- `baseline`
- best static candidate
- best piecewise-static policy
- best non-switching policy under the current phase variant
- `final-steady`
- `weak-online`

## Current Progress Snapshot

### Overall Position

The branch has already clarified the final target:

- not generic adaptive tuning
- but same-key phase-shift-aware online correction

### Current Active Change

Active umbrella change:

- `prove-or-falsify-switching-value`

Its role is to organize the staged proof order:

- headroom
- static envelope
- drift value

### What Is Already Established

- the plugin-only NCCL profiler+tuner path exists
- communicator-domain shared publication and activation boundaries exist
- `numa1-4gpu` is currently the preferred clean reference surface
- recheck spikes are identifiable as a mechanism phenomenon

### What Is Not Yet Proven

- stable static headroom on the current search surface
- workload-confirmed room
- same-key winner flip under phase shift
- weak-online payoff that recovers its sampling cost

### Current Most Important Reading

The latest Phase 1 result should currently be read narrowly as:

```text
current candidate space + current pure-comm smoke
did not prove static headroom
```

It should not be over-read as:

```text
static value does not exist
```

### Current Operational Priority

The current priority should be:

1. keep the final goal fixed on phase shift
2. do not rush to claim switching value
3. do not rush to optimize weak-online policy logic
4. first prove where the room actually is

## Project Milestones

### M0. Stabilize The Evidence Contract

Completion condition:

- nearby batches are comparable without ad hoc interpretation

### M1. Expand Static Search Surface

Completion condition:

- either `no proven communication room`
- or `communication room established`

### M2. Confirm Workload Room

Completion condition:

- each candidate is classified as:
  - `communication-only win`
  - `workload-confirmed win`
  - `no confirmed gain`

### M3. Validate Same-Key Phase Shift

Completion condition:

- either `no stable winner change`
- or `same-key phase-shift room established`

### M4. Evaluate Weak-Online Payback

Completion condition:

- either `sampling loss not recovered`
- or `weak-online payoff established`

## Planned Change Sequence

The current intended change sequence is:

1. `static-room-establishment`
   - establish `communication room` and `workload room`
2. `same-key-phase-shift-validation`
   - establish whether same-key phase shift creates `switching room`
3. `weak-online-payoff-validation`
   - validate whether current `weak-online` can recover its sampling cost

These changes are intentionally staged.
They should not be collapsed back into one oversized proof task unless there is
an explicit reason to do so.

## Update Rule

When a new change materially alters project-level understanding, update this
page with:

- the new project-wide interpretation
- what milestone moved
- what is still not proven

Do not force every future change to rediscover the whole branch history from
scratch.

## One-Page Recovery

```text
Goal:
  same-key phase-shift-aware online NCCL plugin

Order:
  measurement fidelity
  -> communication room
  -> workload room
  -> switching room
  -> weak-online payoff

Principle:
  first prove the room
  then prove switching can exploit it
  then redesign weak-online so early sampling cost is paid back by later gain
```
