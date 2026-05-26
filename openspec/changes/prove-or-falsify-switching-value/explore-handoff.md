# Prove Or Falsify Switching Value Explore Handoff

## Purpose

This note records the current explore consensus without changing the formal
proposal or spec language yet.

It is intentionally narrower than a design decision:

- it records what direction currently looks reasonable
- it preserves one unresolved branch on question framing
- it does not claim that switching value has already been established

## Current Branch Reading

The active change already moved the project away from:

- "make `weak-online` win by default"

and toward:

- "prove or falsify switching value"

That reframing still looks correct.

Primary anchors:

- [proposal.md](/home/wsl/projects/nccl-adapt/openspec/changes/prove-or-falsify-switching-value/proposal.md:21)
- [headroom-map.md](/home/wsl/projects/nccl-adapt/nccl/plugins/adaptive/experiments/switching-value/phase1/2026-05-13-switching-value-phase1/headroom-map.md:1)

At the moment, the strongest fresh signal is:

- Phase 1 did not produce any `headroom-positive` size on the clean
  `numa1-4gpu` surface
- therefore no size was promoted to Batch B

This does not prove that online correction is never useful.
It does mean the branch should not pretend that current pure-communication
evidence already supports switching value.

## Provisional Direction Agreement

The following points are currently accepted as the working direction for the
next stage of exploration.

### 1. Close the current change honestly

Do not keep narrating the branch as if `weak-online` is expected to win soon.

If the current evidence continues to say:

- no proven headroom
- or static envelope sufficient
- or drift not strong enough

then that should be written down explicitly.

### 2. Reconcile measurement before investing in more mechanism work

Before adding more online control complexity, first explain the mismatch between:

- the earlier clean-surface `numa1` decomposition
- the later Phase 1 size sweep behavior

The immediate concern is not "invent a better policy."
The immediate concern is "make sure the evidence contract is internally
consistent enough to trust small deltas."

### 3. Start a workload-aware drift harness only after question framing is explicit

A new explore/change can still be worthwhile, but only if it is clear that the
target question is no longer "does the current pure-comm smoke prove switching
value?"

If the target shifts to training-like runtime drift, then the harness should
follow the already-written Phase 3 shape:

- compute-overlap drift family
- communication-interference drift family
- no-drift control

Anchors:

- [design.md](/home/wsl/projects/nccl-adapt/openspec/changes/prove-or-falsify-switching-value/design.md:232)

### 4. Use dual-layer reward in evidence before runtime integration

Do not let communication-local metrics alone decide the project narrative.

Use two layers:

- inner-loop communication signal
  - collective latency
  - algorithmic or bus bandwidth
  - winner stability
- outer-loop workload signal
  - step time
  - microstep time
  - or another explicit throughput-adjacent boundary

At first, this can remain an evidence-layer judgment rule rather than a runtime
control rule.

### 5. Only wire outer-loop reward into runtime after stable drift evidence exists

The project should not rush into a heavier online controller.

First show that:

- a drift family really changes the best non-switching winner
- that winner change is stable
- and `weak-online` beats the best non-switching alternative under that drift

Only then does it make sense to promote workload-aware reward into runtime
decision logic.

## Unresolved Branch: What Question Are We Actually Trying To Answer?

This is the one point that remains intentionally open.

There are two materially different questions:

### Question A

```text
Does the current NCCL adaptive plugin, as currently built and evaluated on
pure allreduce smoke, already prove that switching has value?
```

If this is the question, the current direction is conservative:

- stay inside the existing evidence contract
- finish the falsification ladder honestly
- accept a negative or limited result if the evidence keeps pointing there

Under this framing, the next best action is not a new algorithm.
It is disciplined closure.

### Question B

```text
Can a low-overhead NCCL-local correction layer be useful in a more realistic
training-like regime where compute/communication overlap or contention drifts
over time?
```

If this is the question, then the current pure-comm smoke harness is no longer
sufficient as the main proving ground.

Under this framing, the next best action is:

- preserve the plugin as the inner loop
- add a workload-aware harness
- evaluate switching under drift families that keep the static key fixed

The project target changes from:

- "beat baseline on allreduce smoke"

to:

- "show that low-overhead online correction becomes useful when runtime drift
  changes the true best policy"

## Why This Framing Split Matters

Without this split, the branch risks mixing two incompatible narratives:

### Narrative 1

- The current plugin should already win on pure communication smoke.

### Narrative 2

- The current plugin is mainly valuable when overlap or contention changes over
  time in a workload that pure communication smoke does not represent.

Both narratives cannot be the primary target at the same time.

If Narrative 1 is primary, then current negative Phase 1 evidence is highly
material and should push the branch toward closure.

If Narrative 2 is primary, then current negative Phase 1 evidence is still
useful, but it mainly says:

- pure communication smoke is not where switching value is showing up
- therefore the project needs a different proving surface

## Recommended Immediate Explore Questions

Before starting a new change, answer these explicitly:

1. Is the goal to finish the current falsification question on pure-comm
   evidence, or to pivot the project target toward workload-aware drift?
2. If pivoting, what outer-loop metric is the minimum acceptable workload
   signal:
   `step time`, `microstep time`, or another fixed boundary?
3. Which drift family should be the first serious proving surface:
   compute-overlap or communication-interference?
4. What result would count as success for the next change:
   `stable flip observed`, `weak-online beats best non-switching`, or only
   `worth building the outer loop`?

## One-Sentence Handoff

The branch should currently assume that pure-communication evidence has not yet
proven switching value, and the next decision is not "which policy to build"
but "which question the project is actually trying to answer next."
