## Context

`topology-controlled-experiment-matrix` 已经回答了三个问题：

- `cross-8gpu` 跨 socket 路径是真实环境变量，baseline 本身就更慢
- `weak-online` 的 spike 会随 `NCCL_ADAPTIVE_RECHECK_AFTER` 迁移，因此 recheck 是真实机制变量
- 当前 branch 没有复现实验支持 `4-8 MiB` bucket divergence

但 `profiler-only -> final-steady` 的 steady-tuner jump 还没有被单独解释，尤其是 same-socket 不对称：

- `numa0-4gpu`: `0.603 ms -> 1.031 ms`
- `numa1-4gpu`: `0.468 ms -> 0.486 ms`

这一现象说明下一步不该继续以 `cross-8gpu` 为主样本。`cross-8gpu` 适合证明拓扑和 recheck 的放大效应，但不适合隔离 steady tuner 成本，因为它天然混入跨 socket 路径。

本 change 的目标是把问题压缩成一个更小的实验：

```text
same-socket steady-tuner isolation

numa0-4gpu      ┐
                ├─ compare profiler-only vs final-steady
numa1-4gpu      ┘

exclude:
  - cross-8gpu
  - weak-online
  - size sweep
```

约束：

- 固定容器为 `nvcr.io/nvidia/pytorch:26.03-py3`
- 固定 message size、candidate 参数、activation lag、switch threshold
- 只延长测量窗口，避免把前段 warmup / publish / activate 污染误判成 steady 成本

## Goals / Non-Goals

**Goals:**

- 在 same-socket 条件下复验 `profiler-only -> final-steady` 的额外成本是否稳定存在
- 分离 `final-steady` 的前段 warmup/publish/activate 成本与 post-activation steady 成本
- 判断 `numa0-4gpu` / `numa1-4gpu` 的差异是否可复现，并且差异主要落在：
  - callback-only profiler 路径
  - sampled warmup window
  - shared coordinator aggregate / publish / activate
  - post-activation steady active-candidate path
- 产出足够明确的证据，让后续 change 可以决定是继续查 coordinator 路径，还是查 placement / affinity 局部环境

**Non-Goals:**

- 不重新分析 `cross-8gpu` 的跨 socket 放大效应
- 不包含 `weak-online`，因为本 change 不研究 recheck
- 不修改 adaptive 算法、candidate 集合、switch threshold、activation lag 或 key 设计
- 不重新打开 size bucket honesty / bucket refinement 方向
- 不在本 change 中直接做性能修复；它是定位 steady tuner 成本来源的诊断 change

## Decisions

### 1. 只保留 same-socket groups

本 change 只运行 `numa0-4gpu` 与 `numa1-4gpu`。

原因：

- `cross-8gpu` 已经证明跨 socket 会放大 baseline 和 tuner 成本
- 当前问题不是“拓扑会不会放大”，而是“去掉跨 socket 之后 steady tuner 成本还剩多少”

替代方案：

- 继续保留 `cross-8gpu` 一起跑
  - 不采用，因为会重新把问题拉回到 mixed topology

### 2. 只比较 `profiler-only` 与 `final-steady`

`profiler-only` 代表 callback-only 成本，`final-steady` 代表 callback + warmup + publish/activate + steady tuner 成本。

原因：

- `baseline` 的噪声下界已经在上一个 change 中测过
- `weak-online` 会重新混入 recheck 变量
- 当前最需要解释的就是 `profiler-only -> final-steady` 的跳变

替代方案：

- 跑完整四模式矩阵
  - 不采用，因为会扩大实验面并弱化诊断焦点

### 3. 拉长测量窗口，而不是改算法参数

诊断批次应保持已有 adaptive 参数不变，只把测量窗口拉长；建议保守固定为：

- `REPLICATES=3`
- `MODE_MESSAGE_MB=8`
- `MODE_WARMUP_ITERS=4`
- `MODE_MEASURE_ITERS=192`
- `MODE_ORDER_STRATEGY=rotate`

原因：

- 192 次测量足以让前段 warmup / publish / activate 只占较小比例
- 保持其余参数不变，才能把差异归因于路径而不是配置漂移

替代方案：

- 同时调 `activationLag`、`switchThresholdPct`、`minSamples`
  - 不采用，因为那会把诊断变成参数搜索

### 4. 用 analyzer 侧分段，而不是修改 benchmark 语义

当前 `torch_allreduce_smoke.py` 对非 `weak-online` 模式只输出统一的 `steady` phase；但 `final-steady` 的 publish / activate 边界已经能通过 coordinator 日志解析出来。

因此本 change 优先在分析侧做分段：

- 从 `stdout.log` / `trajectory.json` 识别 `publish` 与 `activate`
- 用第一次 `activate` 的 call/step 作为边界
- 生成至少两段统计：
  - pre-activation
  - post-activation

必要时还可保留 warmup sampled window 片段作为第三段。

原因：

- 不必更改 benchmark workload 语义
- 可以复用现有日志与 `trajectory.json`
- 直接围绕“第一次 activate 前后”回答 steady-tuner 成本问题

替代方案：

- 在 benchmark 里新增 `final-steady` phase 标签
  - 作为后备方案，但不是首选，因为会扩大 harness 改动面

### 5. completion / coordinator trace 必须成为结果契约

诊断批次不仅要看 aggregate latency，还必须保留：

- `NCCL_ADAPTIVE_LOG_COORDINATOR=1`
- `NCCL_ADAPTIVE_LOG_COMPLETION=1`

并输出至少以下诊断维度：

- first publish call
- first activate call
- activated candidate
- 是否出现 `wait-summary`
- sampled completion 是否出现 partial/fallback/unavailable

原因：

- 否则只能看到“final-steady 比 profiler-only 高”，看不到高在哪个机制段

## Risks / Trade-offs

- [192 次测量让实验更长] → 使用 3 replicates 的最小 same-socket 矩阵，不扩大到 `cross-8gpu`
- [analyzer 分段依赖日志完整性] → 继续使用已修复的嵌入式 JSON/插件路径解析，并把 activate/publish 事件写入 change-local evidence
- [first activate 边界可能不能完全代表 steady 成本] → 同时保留 overall、pre-activation、post-activation 三类统计，避免单一切分误导
- [`numa0` / `numa1` 差异可能来自局部系统状态] → 保持 CPU affinity、容器、run-order 和 adaptive 参数一致，并在 evidence 中记录异常 replicate
- [profiler-only 没有 activate 事件] → 将它作为 callback-only 对照，不强行套用 final-steady 的分段语义

## Migration Plan

这是实验与分析 change，不涉及生产部署或数据迁移。

实施顺序应为：

1. 定义 same-socket 诊断批次的 manifest / result contract
2. 补齐 analyzer 对 final-steady pre/post-activation 的分段
3. 运行 `numa0-4gpu` / `numa1-4gpu` 的 `profiler-only` / `final-steady`
4. 更新 evidence 与 README，明确下一步归因方向

回滚策略：

- 若 analyzer 分段结果不可靠，可以退回到只保留原始日志和 aggregate summary，不把分段结论写入 README

## Open Questions

- 如果 `numa0-4gpu` 与 `numa1-4gpu` 激活到同一 candidate，但 `final-steady` jump 仍显著不同，下一步是否要单独检查 representative rank / shm coordinator locality
- 如果 post-activation steady 段几乎不贵，而 pre-activation 很贵，是否需要单独新增一个“publish/activate front-half amortization” change，而不是直接怀疑 steady tuner 本身
