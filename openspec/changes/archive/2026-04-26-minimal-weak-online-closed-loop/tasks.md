> Reconciliation note (2026-04-26)
>
> 本文件已按当前代码与 README 重新对账。
> 已有一版 `weak-online` communicator-domain 原型落地，但仍有若干任务仅达到“部分实现”或“已有 smoke、尚未完全验收”的状态，因此保留未勾选。

## 1. Spec 边界收敛

- [x] 1.1 为 `weak-online-adaptive-control` 新建 capability spec，定义 communicator-domain、windowed observation、external coordinator 和 steady-first switching 的 requirement
- [x] 1.2 为 `adaptive-nccl-tuning` 补充 delta spec，明确 weak-online 模式与 final steady path 的关系，以及 hold/fallback 行为
- [x] 1.3 明确第一版 non-goals：不支持 per-node domain、多节点复杂协调、learned policy、全量 raw profiler 持久化

## 2. 状态模型与策略存储

- [x] 2.1 为每个 `key` 定义最小状态结构，区分 committed policy、active window 和候选可用性信息
- [x] 2.2 落实 `epoch`、`window_id`、`recheck_after` 的读写规则，避免旧窗口摘要污染新版本 policy
- [x] 2.3 将 `policy domain` 固定为 `communicator`，并明确其与 `key`、rank 集合和策略一致性的关系
- [x] 2.4 定义无 committed policy、coverage 不完整、摘要过期时的默认 hold/default 行为

## 3. 热路径只读化

- [x] 3.1 将 tuner 热路径收敛为“读 committed policy -> 校验 candidate availability -> 应用或 fallback”
- [x] 3.2 移除或绕开当前基于全局 phase 的持续候选轮转逻辑，确保 weak-online 模式下不再由 `getCollInfo` 规划窗口
- [x] 3.3 确保 candidate 不可用时仅影响当次调用，并将 suspect/unavailable 信息留给窗口裁决路径处理
- [x] 3.4 验证热路径在 weak-online 模式下不等待 coordinator、不依赖 profiler 实时结果、不执行重日志输出

## 4. 窗口化观测与摘要

- [x] 4.1 实现 `warmup -> steady -> recheck` 的窗口调度规则，确保大多数命中停留在 steady
- [x] 4.2 定义最小 `window summary` 字段：`key`、`observed_epoch`、`window_id`、`candidate`、`sample_count`、`latency_sum_us`、`bw_sum`、`unavailable`
- [x] 4.3 将 profiler/observer 路径收敛为窗口级聚合摘要，而不是长期保存全量 raw event
- [x] 4.4 确保未命中采样窗口的事件走近似 no-op 路径，避免把 diagnostic 开销重新带回 weak-online 模式

## 5. Coordinator 最小闭环

- [x] 5.1 定义 coordinator 输入输出契约：接收 communicator-domain 的窗口摘要，发布 committed policy(`epoch`、candidate、`recheck_after`)
- [x] 5.2 实现切换门槛：样本足够、优势持续、超过阈值才允许从当前 steady 切换
- [x] 5.3 实现 incomplete coverage、stale summary、unavailable candidate 时的裁决规则，默认保持旧 steady 或回 default
- [x] 5.4 确保本地 rank 只能提交建议摘要，不能基于本地异步统计直接切换 policy

## 6. 模式与实验验证

- [x] 6.1 为 weak-online 模式补充最小配置项，区分 warmup 长度、recheck 周期、切换阈值和是否启用窗口观测
- [x] 6.2 增加最小对照实验矩阵：`baseline`、`profiler-only`、`final-steady`、`weak-online`
- [x] 6.3 量化 weak-online 相对 `profiler-only` 和 `final-steady` 的 overhead，验证其位于“明显低于 profiler-only、略高于 final steady”的目标区间
- [x] 6.4 验证同一 communicator 内 policy 切换保持一致，且数据不足、迟到摘要、候选不可用时不会导致 hang 或 rank 分叉
