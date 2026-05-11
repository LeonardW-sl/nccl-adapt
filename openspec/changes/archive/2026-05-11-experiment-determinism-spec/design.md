## Context

当前 `nccl/plugins/adaptive` 已经具备 weak-online / final-steady / profiler-only / baseline 等多种运行模式，也已经通过日志验证了共享发布、延迟激活和 rank 一致性等关键机制。但现有实验协议仍存在三个交叉问题：

- 机制正确性、机制成本和策略收益在同一组实验里被同时解释。
- 单次运行和固定 mode 顺序会引入顺序效应与偶发 spike，削弱结果确定性。
- 结果统计主要依赖 overall mean，无法区分 steady 段退化、recheck spike 和状态颗粒度失真。

本设计的目标不是改变 adaptive 插件的候选动作空间，而是把实验方法本身标准化，使后续对状态颗粒度和 bucket honesty 的判断具备更高确定性。

## Goals / Non-Goals

**Goals:**

- 定义一套分层实验协议，分别回答机制正确性、机制成本、策略质量和状态颗粒度四类问题。
- 要求 mode comparison 实验具备重复运行、顺序轮换和更完整的元数据记录能力。
- 要求 weak-online 实验对 warmup、steady、recheck 段进行可区分的统计与解释。
- 为 size-bucket honesty 建立专门的 size sweep / candidate trajectory 判别实验。

**Non-Goals:**

- 不在本变更中修改 adaptive 插件的候选集合、切换阈值算法或共享内存协调机制。
- 不在本变更中解决 multi-node 协调问题。
- 不强制本次变更立即实现新的分析脚本或自动化可视化；本变更优先定义 spec 和实施边界。

## Decisions

### 1. 将实验拆分为四类判别实验，而不是继续扩展单一 mode-comparison 跑法

选择将实验明确拆为：

- 机制正确性实验：验证 publish / observed-publish / activate / fallback 行为是否符合预期。
- 机制成本实验：评估 baseline、profiler-only、final-steady、weak-online 的 host-side 开销。
- 策略质量实验：使用 learned candidate 的 static replay 验证候选策略本身是否值得采用。
- 状态颗粒度实验：针对同一 size bucket 内不同 message size 做 sweep，观察 candidate trajectory 是否分叉。

原因是这四类问题对统计口径和结果解释的要求不同。继续把它们压到一个 overall mean 表中，会让结论失真。

备选方案：

- 保持现有单一实验入口，只在 README 中增加解释。
  不采用，因为这只能改善表述，不能降低实验本身的解释不确定性。

### 2. 将“重复运行 + 顺序轮换”视为实验协议的一部分

设计要求 mode comparison 和 size sweep 都使用 replicate 概念，并显式记录 replicate id 与运行顺序。不同 replicate 之间需要轮换 mode 顺序，而不是固定始终按 `baseline -> profiler-only -> final-steady -> weak-online` 执行。

原因是当前 workload 明显存在偶发尖峰和热态效应，固定顺序会把顺序偏差误写成模式差异。

备选方案：

- 仅增加单次运行的测量长度。
  不采用，因为更长的单次运行可以降低采样噪声，但不能消除 run-order bias。

### 3. 将 weak-online 结果按阶段解释，而不是只保留整体平均值

设计要求 weak-online 的结果至少区分：

- 初始 warmup / 首次激活前
- steady active policy
- recheck window 附近

并要求结果能够支持 `median`、`p95`、`max` 以及 steady / recheck 分段解释。

原因是 weak-online 的开销结构天然由 steady 段与 recheck spike 共同组成。只保留 overall mean 无法判断问题到底来自常态退化还是周期性重检。

备选方案：

- 继续只输出 `min/avg/max`。
  不采用，因为这不足以支撑对 tail behavior 和 recheck 开销的解释。

### 4. 将状态颗粒度验证设计为独立 size sweep 实验

状态颗粒度实验单独固定 `nRanks`、`nNodes`、mode 和 adaptive 参数，只 sweep 同一 bucket 内的多个 message size，输出每个 size 在多个 epoch 和 replicate 下的 candidate trajectory。

原因是 bucket honesty 的核心证据不是单次均值，而是“相邻 size 是否持续偏向不同 candidate”。trajectory 比 overall latency 更直接反映状态域是否过粗。

备选方案：

- 继续用少数两个 size 的对照日志说明问题。
  不采用，因为这种证据可以提示问题，但很难形成足够稳定的判别标准。

### 5. 将实验元数据视为结果契约的一部分

设计要求实验结果目录必须记录：

- adaptive 控制参数
- replicate id
- run order
- workload 参数
- 关键 NCCL 环境
- 容器和运行环境约束

原因是实验设计的确定性不仅来自运行本身，也来自结果的可追溯性。

## Risks / Trade-offs

- [实验协议更复杂] → 通过分层实验矩阵降低一次性解释负担，每类实验只回答一个问题。
- [重复运行增加成本] → 先要求最小可接受 replicate 数，再根据需要扩展，不强制一次引入重型自动化。
- [spec 先行但实现滞后] → 在 tasks 中把文档、harness、结果口径拆开，允许分阶段落地。
- [host-side 统计仍不能直接证明底层 kernel 优劣] → 明确把策略质量实验与机制成本实验分开，避免错误结论外推。

## Migration Plan

- 先更新 OpenSpec，明确新的实验协议和现有 capability 的修改边界。
- 再按 tasks 拆分实现：结果元数据、mode comparison、size sweep、README 叙事重构。
- 若实现后发现某些统计口径无法稳定取得，可回退到“保留现有 harness，但按 spec 增补元数据和分段解释”的最小方案。

## Open Questions

- 每类实验的最小 replicate 数应在 spec 中写为固定值，还是写为“至少 N 次”的下界。
- weak-online 的 recheck-window 标记最终由 harness 显式输出，还是由离线日志解析推导。
- 策略质量实验是否需要把 static replay 纳入正式 harness，还是允许先通过手工实验执行。
