# Phase Shift Framing Note

## Purpose

This note records the clarified project target from the current explore.

The target is now explicit:

- the long-term goal is not generic adaptive tuning
- the long-term goal is an online plugin that can respond to `phase shift`
  inside the same static communication regime

This note does not change the formal spec text yet.
It captures the intended interpretation layer for future changes.

Primary context:

- [proposal.md](/home/wsl/projects/nccl-adapt/openspec/changes/prove-or-falsify-switching-value/proposal.md:21)
- [design.md](/home/wsl/projects/nccl-adapt/openspec/changes/prove-or-falsify-switching-value/design.md:232)
- [headroom-map.md](/home/wsl/projects/nccl-adapt/nccl/plugins/adaptive/experiments/switching-value/phase1/2026-05-13-switching-value-phase1/headroom-map.md:1)

## Core Position

`static strategy value` and `switching value` are separate questions, but they
are not unrelated.

The correct dependency is:

```text
static headroom
  -> static envelope
    -> same-key phase shift
      -> switching value
```

Meaning:

1. First prove that some non-default policy can matter at all.
2. Then ask whether static variables already explain that value.
3. Only then ask whether the best policy changes inside the same static key
   because runtime phase changes.
4. Only that last case creates independent switching value.

So the clarified target is:

```text
phase-shift-aware online correction
```

not:

```text
online switching for its own sake
```

## What `Phase Shift` Means Here

`phase shift` does not mean:

- a different message size
- a different topology group
- a different world size
- a different communicator-domain

Those are static regime changes.

`phase shift` means:

- the static key stays the same
- but the runtime position of the target collective relative to surrounding
  compute or communication changes
- and that shift changes overlap or resource pressure enough that the true best
  policy may also change

Current same-key interpretation remains:

```text
commId + collType + size bucket + nRanks + nNodes
```

Inside one such key, `phase shift` is a runtime phenomenon.

## Visual Model

### Static difference

```text
Regime A
  size = 8 MiB
  topology = numa1-4gpu

Regime B
  size = 32 MiB
  topology = cross-8gpu

These are not phase shifts.
These are static regime changes.
```

### Phase difference inside one static key

```text
same key
same size
same topology
same nRanks
same nNodes

control
compute: [==========]
comm:       [----]
tail:          small

phase-late
compute: [=====]
comm:         [----]
tail:             larger
```

The collective itself is "the same kind of thing."
Its position in the end-to-end critical path is different.

That is the target phenomenon.

## Related Terms

### Overlap

`overlap` means how much communication is hidden by compute.

Two collectives with the same raw latency may have different workload impact:

```text
case 1
compute: [==========]
comm:       [----]
step end: [==========]

case 2
compute: [=====]
comm:         [----]
step end: [===========]
```

In case 1, communication is mostly hidden.
In case 2, communication is exposed on the tail.

### Contention

`contention` means the target collective is competing for resources.

The competition can come from:

- communication-side pressure
  - NVLink / PCIe / NIC / copy engine usage
- compute-side pressure
  - SM occupancy
  - memory bandwidth
  - kernel scheduling overlap
- runtime-side pressure
  - launch timing
  - synchronization timing

Contention is one of the main mechanisms through which phase shift can matter.

### Phase Shift

`phase shift` is the runtime change in where the target collective sits relative
to those competing activities.

A phase shift matters only if it changes one or both of:

- exposed communication
- contention shape

## Why Static Headroom Still Comes First

The final goal is phase-shift-aware online switching.
But the prerequisite is still static headroom.

Reason:

```text
If no candidate can beat default anywhere,
then there is nothing meaningful to switch to.
```

So the clarified logic is:

- static headroom is not the final goal
- static headroom is the entry ticket

The current Phase 1 negative result should therefore be read narrowly:

```text
current candidate space + current pure-comm smoke
did not prove static headroom
```

It should not be over-read as:

```text
static value does not exist
```

## Why Current Evidence Is Not Enough For The Final Goal

The current branch still uses:

- a narrow candidate set
- pure allreduce smoke
- communication-local measurement as the main winner signal

Anchors:

- [adaptive_plugin.cc](/home/wsl/projects/nccl-adapt/nccl/plugins/adaptive/adaptive_plugin.cc:455)
- [torch_allreduce_smoke.py](/home/wsl/projects/nccl-adapt/nccl/plugins/adaptive/torch_allreduce_smoke.py:89)

That is enough for:

- mechanism validation
- safety validation
- initial static headroom probing

That is not enough for the final project claim:

- "the plugin can respond to phase shift"

because pure communication smoke does not create meaningful compute/communication
phase structure.

## Correct Decision Ladder

Future work should follow this ladder:

### Layer 1: Static Headroom

Question:

```text
Does a non-default candidate ever beat default on a controlled regime?
```

Needed because:

- no headroom means no switching story

### Layer 2: Static Envelope

Question:

```text
Can the best policy already be explained by static variables such as
size/topology/world-size?
```

Needed because:

- if a piecewise-static table is enough, switching still has no independent
  value

### Layer 3: Same-Key Phase Shift

Question:

```text
Inside one static key, does phase change alter the best non-switching winner?
```

Needed because:

- this is the actual entry point for switching value

### Layer 4: Online Switching Value

Question:

```text
When the winner changes inside one static key, does weak-online beat the best
non-switching alternative?
```

Only this layer proves the intended long-term target.

## What Future Experiments Must Record

The final goal is phase-shift-aware behavior, so future experiments must record
more than raw collective latency.

### A. Static Regime Identity

Each run must still record:

- communicator-domain identity
- collective type
- message size
- size bucket
- topology group
- `nRanks`
- `nNodes`
- mode
- candidate or policy used
- replicate id

Without this, same-key claims are not trustworthy.

### B. Phase Variant Identity

Each drift run must explicitly record:

- drift family
  - `compute-overlap`
  - `comm-interference`
- variant
  - `control`
  - `compute-overlap-early`
  - `compute-overlap-late`
  - `low-comm-interference`
  - `high-comm-interference`
- what single variable is allowed to differ
  - overlap start position
  - or interference intensity

This is necessary to prevent "phase shift" from collapsing into uncontrolled
noise.

### C. Inner-Loop Communication Signal

Record the NCCL-local signal:

- collective latency
- phase-local latency
- algorithmic bandwidth
- bus bandwidth
- selected algorithm
- selected protocol
- channel count
- winner stability across replicates
- publish and activate trajectory

This remains the plugin's natural inner-loop observability surface.

### D. Outer-Loop Workload Signal

Record a workload-level boundary signal for the same run:

- step time
- microstep time
- exposed communication proxy
- tail segment timing near step end

This is required because phase-shift value is fundamentally about workload
impact, not just isolated communication speed.

### E. Phase Interpretation Signal

For each run, record enough structure to say why a phase variant is different:

- whether the collective moved earlier or later relative to background compute
- whether exposed tail increased or decreased
- whether sidecar communication intensity increased or decreased
- whether the same candidate remained best or a different candidate took over

Without this, `phase shift` becomes a label rather than an explained phenomenon.

### F. Winner Hierarchy

Each summary should report, in order:

- `baseline`
- best static candidate
- best piecewise-static policy
- best non-switching policy under the current drift variant
- `final-steady`
- `weak-online`

This prevents accidental over-claiming from a two-arm comparison.

## Minimum Success Conditions For The Final Goal

The intended long-term claim is not:

```text
weak-online beats baseline somewhere
```

The intended long-term claim is:

```text
inside the same static key,
phase shift changes the true best policy,
and weak-online captures that change better than the best non-switching
alternative
```

That implies three minimum conditions:

1. Static headroom exists somewhere relevant.
2. Static variables alone do not fully explain the winner.
3. Same-key phase variants produce a stable winner change that weak-online can
   exploit.

## Current Practical Interpretation

For this branch, the most objective current reading is:

- the final target is phase-shift-aware online correction
- static value is a prerequisite, not the final story
- current Phase 1 evidence is still useful, but only as an initial static
  screen
- the current negative result should push the branch toward:
  - better static search surface
  - then explicit same-key phase-shift experiments

## Recommended Next Documentation Move

If the branch keeps this direction, the next formal documentation change should
do one of these:

1. Add a short design subsection that defines `phase shift` as a same-key
   runtime phenomenon.
2. Add an evidence contract subsection that requires both NCCL-local and
   workload-level signals for future drift runs.
3. Add a new explore or proposal note for expanding the static search surface
   before serious switching claims.

## One-Sentence Summary

The clarified project target is an online plugin that adapts to same-key phase
shift, and the correct path is to treat static headroom as a prerequisite layer
rather than as the final objective.
