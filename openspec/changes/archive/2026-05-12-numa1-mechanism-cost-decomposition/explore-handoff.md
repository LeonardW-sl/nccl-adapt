# NUMA1 Mechanism Decomposition Explore Handoff

## Purpose

This note is a handoff for the next fresh conversation.

The immediate goal is **not** H100 migration.
The real goal is still:

- make `weak-online` materially effective
- understand whether the current blocker is policy quality, recheck cost, or some placement-local artifact

This change was only meant to answer one narrower question first:

- on the clean `numa1-4gpu` surface, how much of `final-steady` cost comes from
  - profiler / observation overhead
  - fixed-candidate replay effect
  - dynamic steady-path mechanism residual

## What This Change Established

Primary artifacts:

- [evidence.md](/home/wsl/projects/nccl-adapt/openspec/changes/numa1-mechanism-cost-decomposition/evidence.md:1)
- [numa1-mechanism-summary.json](/home/wsl/projects/nccl-adapt/nccl/plugins/adaptive/experiments/numa1-mechanism-cost-decomposition/2026-05-12-numa1-mechanism-cost-decomposition/numa1-mechanism-summary.json:1)
- [comparison-summary.json](/home/wsl/projects/nccl-adapt/nccl/plugins/adaptive/experiments/numa1-mechanism-cost-decomposition/2026-05-12-numa1-mechanism-cost-decomposition/mode-comparison/numa1-4gpu/comparison-summary.json:1)

The clean conclusions are:

1. `final-steady` stayed candidate-aligned with `static-replay`.
   - learned candidate: `ring/simple`
   - requested replay candidate: `ring/simple`
   - no supplemental aligned replay was needed

2. The post-activation `final-steady` path and the replay path agree at the algorithm/protocol level.
   - post-activation `final-steady`: `RING/SIMPLE`, 4 channels
   - `static-replay`: `RING/SIMPLE`, mostly 4 channels

3. The decomposition on `numa1-4gpu` is numerically small.
   - `baseline = 0.431 ms`
   - `profiler-only = 0.447 ms`
   - `static-replay = 0.434 ms`
   - `final-steady overall = 0.469 ms`
   - `final-steady post-activation = 0.462 ms`

4. The decomposition deltas are:
   - `profiler-only - baseline = +0.012 ms`
   - `static-replay - profiler-only = -0.009 ms`
   - `final-steady post-activation - static-replay = +0.028 ms`

## Why `final-steady` Did Not Beat `baseline`

This is the most important interpretation point.

What the data says is:

- the learned candidate itself did **not** beat `baseline` on this workload
  - `baseline = 0.431 ms`
  - `static-replay = 0.434 ms`
  - so fixed `ring/simple` replay is basically flat to slightly worse than NCCL default here

- on top of that, the plugin adds extra cost
  - observation tax: about `+0.012 ms`
  - dynamic post-activation residual: about `+0.028 ms`

So the current picture is:

```text
baseline
  + small profiler tax
  + small dynamic steady-path residual
  + no positive replay gain on this workload
≈ final-steady still worse than baseline
```

This means:

- the failure to beat `baseline` is **not** mainly telling us "dynamic steady mechanism is disastrously expensive"
- it is telling us:
  - NCCL default is already strong on this `numa1` workload
  - replaying `ring/simple` does not produce enough benefit to offset plugin overhead

## Stability And Noise Check

The data is good enough for **mechanism-shape** conclusions, but not for strong claims on tiny deltas.

### Stable enough to trust

- `final-steady` activated `ring/simple` in all 3 replicates
- `first_activate_call` stayed at `6`
- `final-steady post-activation` stayed on `RING/SIMPLE`
- `static-replay` stayed on `ring/simple`
- `final-steady post-activation - static-replay` stayed positive in all replicates:
  - replicate 1: `+0.043 ms`
  - replicate 2: `+0.010 ms`
  - replicate 3: `+0.030 ms`

So these conclusions are safe:

- candidate alignment is real
- post-activation path identity is stable
- there is still a small positive dynamic residual after activation

### Too noisy to over-interpret

Replicate-level averages:

- `baseline`: `[0.407, 0.427, 0.460]`
- `profiler-only`: `[0.461, 0.409, 0.472]`
- `static-replay`: `[0.434, 0.429, 0.439]`
- `final-steady`: `[0.480, 0.447, 0.479]`

Variation:

- `baseline` CV: about `5.1%`
- `profiler-only` CV: about `6.1%`
- `static-replay` CV: about `0.9%`
- `final-steady` CV: about `3.3%`

Two small deltas flip sign across replicates:

- `profiler-only - baseline`
  - `+0.054`, `-0.018`, `+0.012`
- `static-replay - profiler-only`
  - `-0.027`, `+0.020`, `-0.033`

So these are **not** strong conclusions:

- the precise size of profiler tax
- whether replay is microscopically better or worse than profiler-only on this workload

Tail behavior:

- per-run `max` often reaches about `2.9 ms` to `3.6 ms`
- but `p95` remains much lower, around the sub-`0.5 ms` range

Interpretation:

- there are sparse outliers
- they can distort very small mean differences
- they do **not** invalidate the candidate/path correctness conclusions

## What This Change Did Not Solve

This change did **not** answer:

1. why `numa0-4gpu` is still abnormal
2. whether `weak-online` produces real policy wins
3. whether recheck cost is worth paying
4. whether any learned candidate can actually beat NCCL default on the target workload
5. whether H100 should be prioritized right now

## Current Confusions To Carry Forward

These are the real open questions for the next explore:

1. If `ring/simple` replay does not beat `baseline` on clean `numa1`, what is the actual expected win path for `weak-online`?

2. Is `weak-online` only valuable when:
   - the workload/topology changes over time
   - the best candidate is not the NCCL default
   - recheck can discover a better non-default path often enough to offset its own cost

3. On `numa1-4gpu`, can `weak-online` at least satisfy the weaker target:
   - steady segment close to `final-steady` or `static-replay`
   - only recheck windows pay extra cost
   - no large unexplained steady residual

4. If `weak-online` still loses badly, is the problem:
   - recheck window too expensive
   - policy never finds a candidate better than default
   - switching logic not producing useful moves
   - measurement noise hiding real small gains

5. Should future effort focus on:
   - making `weak-online` cheap
   - proving a candidate can beat default on some controlled workload first
   - or explaining `numa0` before claiming broader effectiveness

## Recommended Next Explore

Do **not** start from H100.

Start with a narrow `weak-online` effectiveness explore on the same clean `numa1-4gpu` surface.

Recommended scope:

- topology: only `numa1-4gpu`
- workload: same 8 MiB torch allreduce path first
- compare:
  - `baseline`
  - `static-replay`
  - `final-steady`
  - `weak-online`

Primary questions:

1. Is `weak-online steady` close to `final-steady steady`?
2. How large is `weak-online recheck - weak-online steady`?
3. Does `weak-online` ever publish a candidate that is materially better than default on this workload?
4. If not, is the branch currently paying recheck tax without policy gain?

Recommended metrics:

- `weak-online steady - final-steady post-activation`
- `weak-online recheck - weak-online steady`
- candidate trajectory across rechecks
- whether published candidate differs from `ring/simple` or default
- replicate-to-replicate sign stability, not just pooled mean

Metrics to de-emphasize:

- tiny `baseline` vs `profiler-only` differences under `0.02 ms`
- any H100 go/no-go framing

## One-Sentence Handoff

The key takeaway from this change is:

- on clean `numa1-4gpu`, `final-steady` is not failing because of a huge post-activation dynamic mechanism tax; it is failing to beat `baseline` because replayed `ring/simple` itself does not beat NCCL default here, while the plugin still adds a small but real overhead.
