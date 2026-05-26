# Prove Or Falsify Switching Value Evidence

## Scope

本 evidence 只用于记录下列三层结论的实验结构与最终结果：

- `headroom map`
- `static envelope summary`
- `drift challenge summary`

当前文件为模板版本：

- 不预写任何实验结果
- 不默认 `weak-online` 会赢
- 允许记录负结论，例如 `no proven headroom` 或 `static envelope sufficient`

## Result Roots

### Phase 1: Same-Key Headroom

- Batch A root:
  - `nccl/plugins/adaptive/experiments/switching-value/phase1/<run-label>/phase1/batch-a/`
- Batch B root:
  - `nccl/plugins/adaptive/experiments/switching-value/phase1/<run-label>/phase1/batch-b/`
- Aggregate summary:
  - `nccl/plugins/adaptive/experiments/switching-value/phase1/<run-label>/phase1-summary.json`
  - `nccl/plugins/adaptive/experiments/switching-value/phase1/<run-label>/headroom-map.md`

### Phase 2: Static Envelope Search

- Result root:
  - `nccl/plugins/adaptive/experiments/switching-value/phase2/<run-label>/`
- Aggregate summary:
  - `nccl/plugins/adaptive/experiments/switching-value/phase2/<run-label>/static-envelope-summary.json`

### Phase 3: Drift Challenge

- Result root:
  - `nccl/plugins/adaptive/experiments/switching-value/phase3/<run-label>/`
- Aggregate summary:
  - `nccl/plugins/adaptive/experiments/switching-value/phase3/<run-label>/drift-challenge-summary.json`

## Runtime And Experiment Contract

### Shared Runtime Metadata

- Host snapshots:
  - `host/gpu-list.txt`
  - `host/gpu-inventory.csv`
  - `host/nvidia-smi-topo.txt`
  - `host/numactl-H.txt`
  - `host/nic-locality.txt`
  - `host/server-idle-check.txt`
- Container runtime:
  - image tag: `nvcr.io/nvidia/pytorch:26.03-py3`
  - image id: recorded per run in `host/docker-image-inspect.json`
  - repo digest: recorded when available in `host/docker-image-inspect.json`
  - launch args: recorded in `container/launch-command.txt`
  - workdir: `/workspace/nccl-adapt`
- Expected plugin path:
  - `/workspace/nccl-adapt/nccl/plugins/adaptive/libnccl-adaptive.so`

### Phase 1 Runner

- Script:
  - `nccl/plugins/adaptive/run_switching_value_phase1.sh`
- Generated manifest:
  - `phase1-manifest.json`
- Generated per-size artifacts:
  - `phase1/<batch>/<topology>/<size>/summary.json`
  - `phase1/<batch>/<topology>/<size>/judgment.md`

### Phase 1 Fixed Contract

- topology group:
  - Batch A: `numa1-4gpu`
  - Batch B: `cross-8gpu`
- collective:
  - `allreduce`
- communicator:
  - single communicator-domain
- world size:
  - same-socket 4 GPU for Batch A
- modes:
  - `baseline`
  - `static-replay`
  - `final-steady`
  - `weak-online`
- warmup / measure:
  - `4 / 192`
- replicates:
  - `3`
- size set:
  - `4 MiB`
  - `8 MiB`
  - `16 MiB`
  - `32 MiB`
  - `64 MiB`
  - `128 MiB`
  - `256 MiB`

### Phase 1 Run Manifest Template

Phase 1 的每个结果目录应同时满足两件事：

- 从目录名本身可以看出 `batch / topology / size / mode / replicate`
- 从 manifest 表本身可以回溯到汇总文件与判定位置

推荐目录命名骨架：

```text
phase1/<batch>/<topology>/<size>/<mode>/replicate-<n>/
```

推荐字段约定：

- `<batch>`
  - `batch-a`
  - `batch-b`
- `<topology>`
  - `numa1-4gpu`
  - `cross-8gpu`
  - `numa0-4gpu`
- `<size>`
  - `4m`
  - `8m`
  - `16m`
  - `32m`
  - `64m`
  - `128m`
  - `256m`
- `<mode>`
  - `baseline`
  - `static-replay`
  - `final-steady`
  - `weak-online`
- `<n>`
  - `1`
  - `2`
  - `3`

若某个 size 需要补跑 candidate-aligned replay，应在同一 mode 下追加一个显式标签，而不是覆盖原目录：

```text
phase1/batch-a/numa1-4gpu/8m/static-replay/aligned-ring-simple/replicate-1/
```

建议在每个 size 目录下同时保留一个聚合入口：

```text
phase1/<batch>/<topology>/<size>/summary.json
phase1/<batch>/<topology>/<size>/judgment.md
```

其中：

- `summary.json`
  - 面向脚本聚合
- `judgment.md`
  - 面向人工解释
  - 记录该 size 是否满足 `headroom-positive`
  - 记录是否触发了 candidate-aligned replay

### Phase 1 Manifest Table

| Batch | Topology | Size | Mode | Replicate | Result directory | Summary artifact | Notes |
| --- | --- | --- | --- | ---: | --- | --- | --- |
| `batch-a` | `numa1-4gpu` | `4m` | `baseline` | `1` | `TBD` | `TBD` | `TBD` |
| `batch-a` | `numa1-4gpu` | `4m` | `baseline` | `2` | `TBD` | `TBD` | `TBD` |
| `batch-a` | `numa1-4gpu` | `4m` | `baseline` | `3` | `TBD` | `TBD` | `TBD` |

填表规则：

- 每一行只对应一个实际 run
- `Result directory` 必须指向原始结果根
- `Summary artifact` 必须指向该 run 可被聚合读取的单一文件
- 若该 run 属于 candidate-aligned replay，`Notes` 必须显式写出对齐 candidate 名称
- `Batch B` 只有在对应 size 被 `Batch A` 晋级后才允许填入

### Judgment Thresholds

- Positive-evidence delta threshold:
  - `2.0%`
- Replicate contract:
  - `3` replicates by default
- Positive-evidence vote rule:
  - at least `2/3` replicates must keep the same improvement direction
- Stable flip vote rule:
  - winner change must repeat in at least `2/3` replicates
- Headroom-positive rule:
  - candidate-aligned `best static candidate` must beat `baseline` by at least `2.0%`
  - and pass the `2/3` replicate vote
- Static-envelope-sufficient rule:
  - residual gain of `weak-online` over `best piecewise-static policy` is below `2.0%`
  - or fails the `2/3` replicate vote
- Switching-value-established rule:
  - stable flip observed
  - `weak-online` beats the best non-switching alternative by at least `2.0%`
  - and passes the `2/3` replicate vote
  - and the advantage is explicitly distinguished from the no-drift control

## Phase 1: Headroom Map

### Batch A Results

| Size | Baseline | Best static candidate | Static delta vs baseline | Candidate-aligned replay needed | Final-steady | Weak-online | Replicate vote | Headroom judgment |
| --- | ---: | ---: | ---: | --- | ---: | ---: | --- | --- |
| `4 MiB` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |
| `8 MiB` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |
| `16 MiB` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |
| `32 MiB` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |
| `64 MiB` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |
| `128 MiB` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |
| `256 MiB` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |

### Batch A Interpretation

- `TBD`

### Batch B Promotion Set

- Sizes promoted from Batch A:
  - `TBD`

### Batch B Results

| Size | Topology group | Baseline | Best static candidate | Static delta vs baseline | Final-steady | Weak-online | Replicate vote | Topology headroom judgment |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `TBD` | `cross-8gpu` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |

### Headroom Summary

- Headroom-positive regimes:
  - `TBD`
- No-proven-headroom regimes:
  - `TBD`
- Size-local headroom pattern:
  - `TBD`
- Topology-sensitive headroom pattern:
  - `TBD`

## Phase 2: Static Envelope Summary

### Phase 2 Run Manifest Template

Phase 2 的结果目录需要能回答两件事：

- 这个 run 属于哪一个静态规则候选
- 这个 run 在哪一个具体 regime 上验证该规则

推荐目录命名骨架：

```text
phase2/<rule-scope>/<rule-id>/<topology>/<size>/<mode-or-policy>/replicate-<n>/
```

推荐字段约定：

- `<rule-scope>`
  - `size-topology`
  - `size-topology-world`
- `<rule-id>`
  - `single-static`
  - `piecewise-static-v1`
  - `piecewise-static-v2`
- `<topology>`
  - `numa1-4gpu`
  - `cross-8gpu`
  - `numa0-4gpu`
- `<size>`
  - `4m`
  - `8m`
  - `16m`
  - `32m`
  - `64m`
  - `128m`
  - `256m`
- `<mode-or-policy>`
  - `baseline`
  - `single-static`
  - `piecewise-static`
  - `final-steady`
  - `weak-online`
- `<n>`
  - `1`
  - `2`
  - `3`

建议在每个 rule candidate 根下保留两个聚合入口：

```text
phase2/<rule-scope>/<rule-id>/summary.json
phase2/<rule-scope>/<rule-id>/judgment.md
```

其中：

- `summary.json`
  - 面向脚本聚合
  - 汇总该 rule candidate 覆盖的所有 regimes
- `judgment.md`
  - 面向人工解释
  - 记录该 rule 是否进入最终 `piecewise-static policy`
  - 记录 residual gain 是否仍需进入 `Phase 3`

### Phase 2 Manifest Table

| Rule scope | Rule id | Topology | Size | Mode or policy | Replicate | Result directory | Summary artifact | Notes |
| --- | --- | --- | --- | --- | ---: | --- | --- | --- |
| `size-topology` | `piecewise-static-v1` | `numa1-4gpu` | `8m` | `piecewise-static` | `1` | `TBD` | `TBD` | `TBD` |
| `size-topology` | `piecewise-static-v1` | `numa1-4gpu` | `8m` | `piecewise-static` | `2` | `TBD` | `TBD` | `TBD` |
| `size-topology` | `piecewise-static-v1` | `numa1-4gpu` | `8m` | `piecewise-static` | `3` | `TBD` | `TBD` | `TBD` |

填表规则：

- 每一行只对应一个实际 run
- `Rule id` 必须与 `Piecewise-Static Rule Candidates` 表中的候选名一致
- `Mode or policy` 必须显式区分 `single-static` 与 `piecewise-static`
- `Summary artifact` 必须可被统一聚合脚本读取
- 若某条 rule 只覆盖 `Phase 1` 晋级的一部分 regimes，`Notes` 必须写明覆盖边界

### Per-Regime Static Candidate Summary

| Regime | Baseline avg | Best static candidate | Static avg | Static delta vs baseline | Final-steady avg | Final-steady delta vs static | Weak-online avg | Weak-online delta vs piecewise-static | Included in Phase 2 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |

### Piecewise-Static Rule Candidates

| Rule scope | Rule expression | Covered regimes | Piecewise-static avg | Piecewise-static delta vs baseline | Piecewise-static delta vs single static | Included in final policy |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |

### Piecewise-Static Policy Draft

```text
TBD
```

### Static Envelope Judgment

- Best piecewise-static policy:
  - `TBD`
- Does static envelope explain most observed gain?
  - `TBD`
- Residual gain left unexplained by static envelope:
  - `TBD`
- Conclusion:
  - `TBD`

## Phase 3: Drift Challenge Summary

### Phase 3 Run Manifest Template

Phase 3 的结果目录需要能回答三件事：

- 这个 run 属于哪一个 drift family
- 它是 control、轻扰动还是强扰动
- 若比较了 `recheck_after`，当前 run 使用的是哪个设置

推荐目录命名骨架：

```text
phase3/<drift-family>/<variant>/<topology>/<size>/<mode>/recheck-<k>/replicate-<n>/
```

推荐字段约定：

- `<drift-family>`
  - `compute-overlap`
  - `comm-interference`
- `<variant>`
  - `control`
  - `compute-overlap-early`
  - `compute-overlap-late`
  - `low-comm-interference`
  - `high-comm-interference`
- `<topology>`
  - `numa1-4gpu`
  - `cross-8gpu`
  - `numa0-4gpu`
- `<size>`
  - `4m`
  - `8m`
  - `16m`
  - `32m`
  - `64m`
  - `128m`
  - `256m`
- `<mode>`
  - `piecewise-static`
  - `final-steady`
  - `weak-online`
- `<k>`
  - `default`
  - `short`
  - `long`
  - 或具体数值标签，例如 `32`、`64`
- `<n>`
  - `1`
  - `2`
  - `3`

若某个 run 不比较 `recheck_after`，也保留该目录层，并固定写成：

```text
recheck-default
```

建议在每个 drift variant 根下保留两个聚合入口：

```text
phase3/<drift-family>/<variant>/summary.json
phase3/<drift-family>/<variant>/judgment.md
```

其中：

- `summary.json`
  - 面向脚本聚合
  - 汇总同一 drift variant 下的所有模式与 replicate
- `judgment.md`
  - 面向人工解释
  - 记录是否观察到 `stable flip`
  - 记录是否满足 `switching value established`
  - 记录触发边界是否仅在扰动下出现

### Phase 3 Manifest Table

| Drift family | Variant | Topology | Size | Mode | Recheck setting | Replicate | Result directory | Summary artifact | Notes |
| --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- |
| `compute-overlap` | `control` | `numa1-4gpu` | `8m` | `weak-online` | `default` | `1` | `TBD` | `TBD` | `TBD` |
| `compute-overlap` | `control` | `numa1-4gpu` | `8m` | `weak-online` | `default` | `2` | `TBD` | `TBD` | `TBD` |
| `compute-overlap` | `control` | `numa1-4gpu` | `8m` | `weak-online` | `default` | `3` | `TBD` | `TBD` | `TBD` |

填表规则：

- 每一行只对应一个实际 run
- `Variant` 必须属于当前 drift family 的合法子变体
- `Mode` 必须限制在 `piecewise-static / final-steady / weak-online`
- `Recheck setting` 只在 `weak-online` 上构成实质差异，但目录层对所有 mode 保持一致
- 若某个 run 用于诊断 `recheck_after`，`Notes` 必须显式写出与哪一个 control 或对照设置配对

### Drift Challenge Setup

| Regime | Drift family | Variant set | No-drift control present | Fixed static regime | Best non-switching policy before drift | Recheck settings compared | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |

### Drift Challenge Results

| Regime | Control winner | Drift winner | Best non-switching avg under drift | Final-steady avg | Weak-online avg | Weak-online delta vs best non-switching | Replicate vote | Stable candidate / policy flip observed | First stable flip boundary | Switching-value judgment |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |

### Drift / No-Drift Comparison

| Regime | Best non-switching avg no-drift | Best non-switching avg drift | Weak-online avg no-drift | Weak-online avg drift | Drift-sensitive advantage only under perturbation |
| --- | ---: | ---: | ---: | ---: | --- |
| `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |

### Drift Interpretation

- `TBD`

## Falsification And Boundary

### F1. No Headroom

- Regimes that satisfy `no proven headroom`:
  - `TBD`

### F2. Static Envelope Is Enough

- Regimes where static envelope is sufficient:
  - `TBD`

### F3. Drift Not Strong Enough

- Regimes where run-time drift did not justify switching:
  - `TBD`

### Positive Switching Value

- Regimes where `weak-online > best non-switching alternative`:
  - `TBD`

### Explicit Boundary

- This change does **not** claim:
  - `TBD`
- This change does support:
  - `TBD`

## Next-Step Judgment

- Should the project continue investing in switching-oriented mechanisms?
  - `TBD`
- Should the project prefer piecewise-static policy for the currently proven regimes?
  - `TBD`
- Follow-up change recommendation:
  - `TBD`
