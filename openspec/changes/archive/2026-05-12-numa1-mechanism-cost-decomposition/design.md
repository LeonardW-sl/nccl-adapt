## Context

当前分歧不在“有没有异常”，而在“异常该怎样被科学拆解”。

已有证据：

- `topology-controlled-experiment-matrix`
  - 证明 `cross-8gpu` baseline 更慢，拓扑是真实变量
  - 证明 `weak-online` spike 跟 `NCCL_ADAPTIVE_RECHECK_AFTER` 一起移动
- `same-socket-steady-tuner-isolation`
  - 证明 `numa1-4gpu` 在长窗口下几乎收敛到 `profiler-only`
  - 证明 `numa0-4gpu` 的 post-activation gap 仍显著存在
  - 证明两侧都激活到相同 candidate：`ring/simple`

因此下一步最有价值的不是继续追 `numa0`，而是在 `numa1` 上先得到一张干净的机制分解图：

```text
baseline
   │
   ├─ Δobs = profiler-only - baseline
   ▼
profiler-only
   │
   ├─ Δfixed = static-replay - profiler-only
   ▼
static-replay(candidate-aligned)
   │
   ├─ Δdynamic = final-steady(post-activation) - static-replay
   ▼
final-steady(post-activation)
```

这张图比直接看 `final-steady - profiler-only` 更有解释力，因为它把“固定 candidate 的效果”和“dynamic coordinator / publish / activate 机制”拆开了。

## Goals / Non-Goals

**Goals:**

- 在 `numa1-4gpu` 上建立 candidate-aligned 的四模式长窗口矩阵：
  - `baseline`
  - `profiler-only`
  - `static-replay`
  - `final-steady`
- 暴露足够的观测信息，让 `static-replay` 与 `final-steady` 的比较不再依赖猜测：
  - activated candidate
  - static replay candidate
  - `selectedAlgo`
  - `selectedProto`
  - `nChannels`
- 用 `post-activation` 对 `static-replay` 做比较，避免把 warmup / publish / activate 前段污染误写成 steady 机制税。
- 给出是否值得继续开 H100 follow-up change 的明确 gate。

**Non-Goals:**

- 不解释 `numa0-4gpu` 的 placement-local 异常来源。
- 不把本 change 扩展成完整拓扑矩阵或 H100 执行 change。
- 不重新打开 `weak-online` / recheck / size bucket honesty 方向。
- 不做性能修复，只做机制归因。

## Decisions

### 1. 只在 `numa1-4gpu` 上做第一轮机制分解

本 change 的主实验面只保留 `numa1-4gpu`。

原因：

- 当前 same-socket 证据已经显示 `numa1` 是更干净的参考面
- `numa0` 混入明显 placement-local 异常，会污染第一轮机制归因
- 若连 `numa1` 都拆不干净，继续追 `numa0` 只会放大歧义

替代方案：

- 同时把 `numa0` 也纳入四模式矩阵
  - 暂不采用，因为那会把“机制归因”和“异常平台归因”再次混在一起

### 2. 加入 `static-replay`，替换粗糙的二段比较

`run_torch_modes.sh` 已经定义了 `static-replay`：

- 它加载 profiler+tuner
- 但 `NCCL_ADAPTIVE_MODE=static`
- `planSelectionLocked()` 在 static 模式下直接返回 `staticCandidate_`
- 不进入 `tryPublishPendingLocked`、`refreshActivePolicyLocked`、sampling window、shared coordinator publish/activate

因此：

- `profiler-only - baseline`
  - 近似隔离 profiler / completion / host observation 税
- `static-replay - profiler-only`
  - 近似隔离 fixed candidate 覆盖默认选择的效果
  - 外加 static tuner direct-path 的最小成本
- `final-steady post-activation - static-replay`
  - 才是 dynamic 机制残差最接近的观测量

这比 `final-steady - profiler-only` 更科学，因为后者混入了 fixed-candidate 效果。

### 3. `static-replay` 必须与 `final-steady` 的 learned candidate 对齐

当前 same-socket evidence 里，`numa1` 激活的是 `ring/simple`。本 change 默认以它作为 replay candidate。

但为了避免把 candidate mismatch 当成机制税，结果判定必须满足：

- 若 `final-steady` 在 rerun 中仍激活 `ring/simple`
  - 则 `static-replay(ring/simple)` 与 `final-steady` 可直接比较
- 若 `final-steady` 激活到别的 candidate
  - 则必须显式记录 mismatch
  - 并用 candidate-aligned replay 重新比较

否则：

```text
final-steady - static-replay
```

就不再是纯机制残差，而混入 candidate 差异。

### 4. 观测契约必须补齐 `selectedAlgo` / `selectedProto`

当前插件内部已经在 `CompletedRecord` 中持有：

- `selectedAlgo`
- `selectedProto`
- `selectedChannels`

但现有 completion 诊断日志没有把它们输出，分析脚本也没有消费它们。

这导致当前 evidence 可以回答：

- publish/activate 是否发生
- candidate 是谁
- 有无 `wait-summary` / fallback

但还不能回答：

- `static-replay` 和 `final-steady` 在 candidate 相同的前提下，底层选中的 algo/proto/channel 是否一致

因此本 change 把它们提升为结果契约的一部分。

### 5. H100 不是本 change 的执行目标，而是 follow-up gate

本 change 结束时应给出一个明确 gate：

- 如果 `numa1` 上 `final-steady post-activation ≈ static-replay`
  - 说明 dynamic 机制残差已经很小
  - 可以合理开 H100 follow-up change 做跨平台验证
- 如果两者差距仍明显
  - 说明 `numa1` 上机制本身还没被讲清
  - H100 验证应暂缓，先补本地机制归因

这样可以避免在 H100 上重复搬运尚未拆干净的问题。

## Risks / Trade-offs

- [`static-replay` 仍带最小 tuner direct-path 税]
  - 接受这个现实，因为它已经显著比 dynamic coordinator 路径更接近“固定 candidate”的对照面
- [`final-steady` learned candidate 可能漂移]
  - 通过 candidate 对齐 gate 显式处理，不把 mismatch 结果写成机制结论
- [baseline 没有 plugin，无法用同一链路记录 algo/proto]
  - 接受 baseline 只作为无-plugin 地板，不要求它承载 candidate 解释
- [`numa1` 上结论未必能直接外推到 H100]
  - 因此 H100 被定义为 follow-up gate，而不是本 change 的自动延伸

## Migration Plan

这是实验与证据 change，不涉及生产部署或数据迁移。

推荐执行顺序：

1. 定义 `numa1-4gpu` 四模式长窗口契约
2. 补齐 `selectedAlgo` / `selectedProto` / `nChannels` 的可观测性
3. 运行 candidate-aligned 的 `baseline/profiler-only/static-replay/final-steady`
4. 生成 decomposition summary
5. 根据残差是否足够小，决定是否开 H100 follow-up change

## Open Questions

- `baseline` 若不能稳定暴露 algo/proto，是否需要单独依赖 NCCL 原生日志做旁证，还是只把它保留为 latency 地板
- `static-replay` 与 `final-steady` 若 candidate 相同但 algo/proto 不同，是否说明底层 NCCL 路径仍存在不可忽略的 runtime 选择差异
- H100 follow-up change 的最小矩阵是否也应只保留单一 clean topology，而不是一开始扩成完整机内矩阵
