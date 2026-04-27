## Why

当前自适应 NCCL 插件已经能够完成跨 rank 的共享发布、延迟激活和弱在线重检，但现有实验设计仍把机制正确性、机制开销和策略收益混在同一组跑数里，导致结果解释不稳定。现在需要把实验协议正式化，使后续关于状态颗粒度、重检开销和策略质量的结论建立在可复现、可判别、可比较的前提上。

## What Changes

- 新增一套面向自适应 NCCL 插件的实验确定性规范，明确实验分层、重复运行、顺序控制、分段统计和结果判定要求。
- 为状态颗粒度评估引入专门的 size-sweep / candidate-trajectory 实验协议，避免继续用混合 workload 日志替代判别实验。
- 收紧现有 mode-comparison 实验要求，区分机制正确性、机制成本和策略质量，避免单个 overall mean 同时承担多个结论。
- 规范实验元数据采集范围，要求记录 adaptive 控制参数、运行顺序、重复编号和环境约束，提升结果可追溯性。

## Capabilities

### New Capabilities
- `adaptive-experiment-determinism`: 定义自适应 NCCL 实验的确定性协议，包括重复运行、顺序轮换、分段统计、状态颗粒度扫点和结论边界。

### Modified Capabilities
- `adaptive-nccl-tuning`: 收紧现有实验比较要求，使 baseline、profiler-only、static、adaptive 模式的比较必须遵循更明确的实验分层与结果解释规则。

## Impact

- 影响 `nccl/plugins/adaptive/README.md` 中的实验章节组织与结论表述。
- 影响 `nccl/plugins/adaptive/run_torch_modes.sh`、`torch_allreduce_smoke.py` 及相关结果目录的实验协议设计。
- 影响后续对状态颗粒度、bucket honesty 和 weak-online 开销的验证方法，但不直接改变当前插件算法动作空间。
