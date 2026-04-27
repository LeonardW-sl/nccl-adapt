## Why

当前 adaptive NCCL 插件正在收敛低开销 final steady path，但该路径主要适用于稳定重复 workload，不能在运行过程中以受控方式对场景漂移做低频自适应。对于后续大模型训练与推理场景，需要一个比常驻 profiler 更轻、比纯 static/steady 更灵活的最小 weak-online 闭环。

本 change 的目标不是引入高频在线调参，也不是直接做 learned policy，而是定义一个最小控制环：

- `communicator` 级一致 policy domain
- 短 warmup、长 steady、偶发 recheck 的窗口化观测
- 热路径外协调、热路径内只读 committed policy
- 只有在样本足够、优势持续且超过阈值时才切换

## What Changes

- 新增 minimal weak-online closed loop 的 OpenSpec 范围定义。
- 将 `communicator` 明确定义为第一版 policy domain。
- 为每个 `key` 定义 `warmup -> steady -> recheck` 状态机。
- 定义 `epoch`、`window_id`、`recheck_after` 的职责边界。
- 定义最小 `window summary` 字段集合，用于窗口级汇总与裁决。
- 定义 coordinator 的最小职责边界：只接收窗口摘要、裁决切换与发布 committed policy，不参与热路径决策。
- 定义 coverage 不完整、摘要过期、候选不可用时的 hold/fallback 规则。

## Capabilities

### New Capabilities

- `weak-online-adaptive-control`: 支持 communicator-domain 的窗口化低频观测与 steady-first 在线策略更新。

### Modified Capabilities

- `adaptive-nccl-tuning`: 后续可增加 weak-online 模式下的状态机、coordinator 接口与 benchmark 对照要求。

## Non-Goals

- 不在本 change 中实现 per-node 或 hierarchical policy domain。
- 不在本 change 中实现复杂多节点协调协议或外部控制服务集群。
- 不在本 change 中实现 learned policy、LLM 直接在线决策或训练数据平台。
- 不在本 change 中保留全量 raw profiler records、复杂统计量或高频每-collective 切换。
- 不在本 change 中处理 communicator grow/shrink 等动态成员变更。

## Impact

- 影响 adaptive NCCL 插件后续的策略状态机、观测摘要模型与实验矩阵设计。
- 需要新增或修改 OpenSpec design/tasks/spec，以表达 weak-online 最小闭环的约束与验收。
- 与 `improve-adaptive-nccl-performance` 分离，避免将 final steady path 优化与 weak-online 控制架构混入同一个 change。

## Closure Update - 2026-04-26

本 change 原先暂停在“缺少 cross-rank shared coordinator”这一前提上。该前提现已由 `cross-rank-coordinator` 子 change 补齐，因此本 change 的最小 weak-online 闭环已经完成。

闭环结果：

- weak-online 保留了本 change 定义的最小状态机、窗口摘要、热路径只读化和保守切换门槛。
- communicator-domain 的 shared committed policy 发布、统一激活边界和 rank0 representative 聚合裁决由 `cross-rank-coordinator` 子 change 提供。
- `final-steady` / `weak-online` 的 2-rank、8-rank smoke 以及 overhead 复测已经重新建立在 communicator 内一致发布的基础上。

验收说明：

- 5.4 现在由“per-rank summary submission + representative-only publication”满足。
- 6.4 现在由共享 published policy 和显式 `effective_call_index` 激活边界满足。
- 6.3 已记录当前实测 overhead；结果说明 weak-online 已恢复为可运行、可量化模式，但其开销分布与最初预期区间并不完全一致，因此验收记录以实际测量结果为准。
