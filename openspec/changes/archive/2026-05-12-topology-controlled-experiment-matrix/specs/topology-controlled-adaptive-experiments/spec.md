## ADDED Requirements

### Requirement: Topology-controlled experiment groups
系统 SHALL 支持按单机 GPU/NUMA 拓扑分组执行自适应 NCCL 实验，以分离同 socket 通信、跨 socket 通信和插件机制开销。

#### Scenario: Same-socket GPU groups are explicit
- **WHEN** 执行拓扑受控实验
- **THEN** 实验协议 SHALL 至少定义 `numa0-4gpu` 和 `numa1-4gpu` 两个同 socket 4 GPU placement
- **AND** 每个 placement SHALL 记录对应的 GPU id、CPU affinity 和 NUMA node

#### Scenario: Cross-socket GPU group is explicit
- **WHEN** 执行 8 GPU 实验
- **THEN** 实验协议 SHALL 将 `GPU0-7` 标记为 `cross-8gpu`
- **AND** 结果 SHALL 明确记录该 placement 包含跨 socket `SYS` 路径

### Requirement: Topology metadata is part of the result contract
系统 SHALL 将拓扑、NUMA、PCIe 和 NIC locality 元数据作为 topology-controlled 实验结果的一部分。

#### Scenario: GPU and PCIe metadata are captured
- **WHEN** 保存 topology-controlled 实验结果目录
- **THEN** 元数据 SHALL 包含 `CUDA_VISIBLE_DEVICES`、GPU PCIe bus IDs、PCIe link generation 和 link width
- **AND** 结果消费者 SHALL 能从结果目录判断实验是否跨 NUMA socket

#### Scenario: CPU and NUMA metadata are captured
- **WHEN** 保存 topology-controlled 实验结果目录
- **THEN** 元数据 SHALL 包含 CPU affinity、NUMA node 信息和 `numactl -H` 或等价快照
- **AND** 实验解释 SHALL 区分未绑定、单 NUMA 绑定和跨 NUMA 绑定

#### Scenario: NIC locality is captured
- **WHEN** 服务器存在 RDMA 或 InfiniBand NIC
- **THEN** 元数据 SHALL 记录至少一个相关 NIC 的 PCIe device、NUMA node 和 local CPU list
- **AND** 单机实验 SHALL NOT 将 NIC locality 解释为性能主因，除非实验路径实际使用 NIC

### Requirement: Container runtime and plugin link metadata are captured
系统 SHALL 固定或显式记录 topology-controlled 实验的容器运行时，并在容器内验证 adaptive plugin 的动态链接状态和 NCCL runtime 加载路径。

#### Scenario: Historical container image is the default
- **WHEN** 执行 topology-controlled 实验
- **THEN** 默认容器镜像 SHALL 为 `nvcr.io/nvidia/pytorch:26.03-py3`
- **AND** 结果元数据 SHALL 记录 Docker image tag、image id，若可用则记录 repo digest

#### Scenario: Container launch contract is captured
- **WHEN** 启动实验容器
- **THEN** 元数据 SHALL 记录容器启动参数，至少包括 GPU 暴露方式、`--ipc=host`、`memlock`、`stack` ulimit、bind mount 和容器内工作目录
- **AND** 结果 SHALL 区分历史镜像结果和任何替代镜像结果

#### Scenario: Plugin dynamic dependencies are captured inside the container
- **WHEN** 保存 topology-controlled 实验结果目录
- **THEN** 元数据 SHALL 包含容器内 `ldd /workspace/nccl-adapt/nccl/plugins/adaptive/libnccl-adaptive.so` 和 `ldd --version` 输出
- **AND** 元数据 SHALL 包含插件 `NEEDED` 动态库检查，证明插件依赖可由当前容器解析

#### Scenario: Plugin exported symbols are verified
- **WHEN** 保存 topology-controlled 实验结果目录
- **THEN** 元数据 SHALL 确认 `libnccl-adaptive.so` 导出 `ncclProfiler_v5` 和 `ncclTunerPlugin_v5`
- **AND** 该检查 SHALL 说明插件通过 NCCL runtime `dlopen` 接入，而不是要求插件直接链接 `libnccl.so`

#### Scenario: NCCL runtime load path is recorded
- **WHEN** 运行 profiler-only、final-steady、weak-online 或 static replay 模式
- **THEN** 结果 SHALL 保留 NCCL 日志中 external profiler/tuner plugin 的实际加载路径
- **AND** 该路径 SHALL 指向本次挂载仓库中的 `libnccl-adaptive.so`

### Requirement: Topology matrix isolates overhead sources
系统 SHALL 使用拓扑分组的 mode comparison 来定位 overhead 波动来源，而不是直接把所有波动归因于 adaptive 插件。

#### Scenario: Baseline-only topology smoke precedes plugin conclusions
- **WHEN** baseline 在同 socket 4 GPU placement 中已经显示高波动
- **THEN** 实验结论 SHALL 优先指向测量环境、系统负载、CPU/NUMA 绑定或 NCCL/PyTorch 路径
- **AND** SHALL NOT 直接将该波动归因于 profiler 或 tuner

#### Scenario: Cross-socket instability is interpreted separately
- **WHEN** 同 socket baseline 稳定但 `cross-8gpu` baseline 不稳定
- **THEN** 实验结论 SHALL 将跨 socket topology 作为主要候选解释
- **AND** 后续 profiler/tuner overhead 判断 SHALL 与该 baseline topology noise 分开表述

#### Scenario: Plugin layers are added incrementally
- **WHEN** baseline topology smoke 完成后
- **THEN** 实验矩阵 SHALL 逐层比较 `profiler-only`、`final-steady` 和 `weak-online`
- **AND** 结果 SHALL 说明波动从哪一层开始显著增加

### Requirement: Recheck spike is evaluated by topology group
系统 SHALL 按 topology group 解释 weak-online recheck spike，区分 steady 成本和 recheck window 成本。

#### Scenario: Weak-online phases are compared per topology
- **WHEN** 分析 weak-online 结果
- **THEN** 结果 SHALL 按 topology group 输出 warmup、steady 和 recheck 的 phase-aware statistics
- **AND** SHALL NOT 用单个 overall mean 代表 weak-online 在所有阶段的成本

#### Scenario: Recheck period movement validates spike attribution
- **WHEN** 调整 `NCCL_ADAPTIVE_RECHECK_AFTER`
- **THEN** 如果 latency spike 随 recheck 周期移动，实验 SHALL 将该 spike 归因于 recheck window 或其交互路径
- **AND** 如果 spike 不随 recheck 周期移动，实验 SHALL 保留系统噪声或 topology noise 的解释

### Requirement: Size bucket honesty is revalidated under topology control
系统 SHALL 在 topology group 维度复验同一 size bucket 内 candidate trajectory 是否稳定分叉。

#### Scenario: Size sweep runs in each topology group
- **WHEN** 评估 `4-8 MiB` bucket honesty
- **THEN** 实验 SHALL 在 `numa0-4gpu`、`numa1-4gpu` 和 `cross-8gpu` 中分别运行 `5/6/7 MiB` size sweep
- **AND** 除 topology placement 和必要的 world size 差异外，adaptive 参数 SHALL 保持一致

#### Scenario: Cross-only divergence is scoped narrowly
- **WHEN** candidate 分叉只在 `cross-8gpu` 中稳定出现
- **THEN** 结论 SHALL 表述为 topology-sensitive bucket honesty 风险
- **AND** SHALL NOT 直接要求全局 size bucket refinement

#### Scenario: Same-socket divergence can justify later bucket refinement
- **WHEN** candidate 分叉在同 socket topology groups 中也稳定复现
- **THEN** 实验 SHALL 允许提出后续 bucket refinement change
- **AND** 当前 change SHALL 只记录证据和结论边界，不直接修改 bucket 算法
