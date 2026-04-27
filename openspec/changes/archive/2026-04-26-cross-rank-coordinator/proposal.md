## Why

`minimal-weak-online-closed-loop` 已经把 weak-online 的最小状态机、窗口摘要和热路径只读化骨架落进代码，但它仍然使用每个 rank 进程内独立的 `PolicyStore` 做 committed policy 裁决。实际多 rank torch smoke 显示：`baseline`、`profiler-only`、`static` 可运行，而 `final-steady` 在 warmup 后切到本地 committed policy 时复现 `SIGSEGV`。这说明当前真正缺的不是更多调参逻辑，而是 communicator-domain 的 cross-rank committed policy 发布与安全激活边界。

现在单开一个子 change，是为了把这个 blocker 从母 change 里剥离出来，单独收敛成一个可验证的 coordinator 问题，而不是继续把“弱在线策略骨架”和“跨 rank 一致性发布”混在一起推进。

## What Changes

- 新增 communicator-domain 的最小 `cross-rank coordinator` 范围定义，专门负责共享 committed policy 的发布与读取。
- 定义 rank-local summary submission 与 shared committed policy publication 的边界：本地 rank 只提交摘要，不直接提交新 policy。
- 定义 published policy 的最小字段集合，以及 `published` 与 `effective` 的职责分离，避免 policy 在不同 rank 上提前或错位生效。
- 定义 communicator-domain 的安全激活边界，使所有 ranks 在相同 call boundary 之后读取相同 committed policy。
- 定义 coordinator 不可用、coverage 不完整、发布过期时的 hold/default 行为。
- 将 benchmark 与验收重点收敛为 `final-steady` / `weak-online` 的多 rank 一致性与稳定性，而不是继续扩大策略空间。

## Capabilities

### New Capabilities

- `weak-online-cross-rank-coordination`: 为 communicator-domain 提供共享 committed policy 发布、读取与安全激活边界。

### Modified Capabilities

- `adaptive-nccl-tuning`: tuner 对后续 collective 的影响不再基于本地 committed policy，而是基于 communicator-domain 的共享发布结果与统一激活边界。

## Impact

- 影响 `nccl/plugins/adaptive/adaptive_plugin.cc` 中的策略状态、profiler/tuner 协调路径和 communicator 生命周期管理。
- 可能引入进程间共享状态机制，例如 `/dev/shm`、POSIX shared memory、process-shared primitives 或等价的单机 IPC。
- 影响 `run_torch_modes.sh`、验证脚本和 README 中对 `final-steady` / `weak-online` 的验收口径。
- 与母 change `minimal-weak-online-closed-loop` 形成前后衔接：母 change 保留状态机骨架，本 change 专门补齐 cross-rank 发布与激活。
