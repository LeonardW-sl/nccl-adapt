## Context

本 change 面向 `nccl-adapt` 中已有的 NCCL plugin 示例。仓库已有 profiler/inspector plugin，可以通过 `ncclProfileColl` 与 `ncclProfileKernelCh` 观测 collective 元数据和执行时间；也已有 tuner plugin 示例，可以在 `getCollInfo` 中修改 NCCL cost table，从而影响后续 collective 的 algorithm/protocol/channel 选择。

NCCL 的选择时机决定了调优只能影响后续 collective。一次 collective 的 profiler 结果产生时，该 collective 的算法和协议已经确定。因此本设计不追求“当前 collective 即时重写”，而是构建一个闭环：观测 collective N，更新策略状态，tuner 在 collective N+1 或后续匹配 key 的 collective 中使用策略。

主要约束是 rank 一致性。NCCL collective 要求参与 ranks 对通信策略保持兼容，不能让 rank0 和 rank1 独立基于本地性能随机选择不同 algorithm/protocol。因此策略选择采用确定性 warmup schedule：所有 rank 基于相同 key、相同 sequence 规则得到相同候选策略；性能统计用于记录、分析和最终稳定选择，但不能引入 per-rank 非确定性切换。

## Goals / Non-Goals

**Goals:**

- 在不修改 NCCL core 源码的前提下，实现 profiler 与 tuner 的闭环设计。
- 通过同一 plugin 动态库导出 profiler 和 tuner symbol，降低数据通路复杂度。
- 使用确定性 warmup schedule，让所有 rank 对相同 collective key 选择相同候选策略。
- 采集 allreduce 等 collective 的 latency、algbw、busbw、algorithm、protocol、channels、sequence 和 size-bin。
- 支持 baseline、profiler-only、static tuner、adaptive tuner 四组实验对比。
- 首版以单节点多 GPU allreduce 为主要交付场景，并保留多节点扩展边界。

**Non-Goals:**

- 不修改 `src/enqueue.cc`、调度器、transport 或 NCCL core ABI。
- 不在首版实现强化学习、复杂 bandit、跨节点控制服务或在线全局协商。
- 不承诺修改已经 enqueue 的当前 collective。
- 不保证所有 topology、所有 collective、所有 message size 都优于 NCCL 默认策略。

## Decisions

### 1. 只修改 plugin 与实验脚本，不修改 NCCL core

选择：实现范围限制在 `nccl/plugins` 新增或组合 plugin，以及实验 wrapper、配置和文档。

理由：NCCL tuner API 已在 core 的 algorithm selection 前调用，profiler API 已能记录 collective 和 kernel channel 事件。使用插件即可完成“观测后影响后续 collective”的目标，同时保持 baseline 可信：同一 NCCL core，仅通过 env 切换 plugin。

替代方案：修改 NCCL core，在 `ncclGetAlgoInfo` 或 enqueue 路径加入自定义逻辑。该方案能力更强，但一天内风险过高，且 baseline 对比会混入 core patch 影响。

### 2. 单一 adaptive plugin 同时导出 profiler 和 tuner symbol

选择：构建一个 `libnccl-adaptive.so`，同时导出 `ncclProfiler_v5` 或 v6 fallback 以及 `ncclTunerPlugin_v5`。

理由：profiler 和 tuner 在同一进程内可通过 plugin 内的共享 `PolicyStore` 交换状态，避免文件轮询或外部服务。NCCL 可通过 `NCCL_PROFILER_PLUGIN` 和 `NCCL_TUNER_PLUGIN` 同时指向该动态库。

替代方案：profiler 与 tuner 分成两个 `.so`，通过文件、socket 或 shared memory 通信。该方案模块边界清晰，但一天内会增加同步、部署和故障排查成本。

### 3. PolicyStore 使用确定性 key 和 schedule

选择：策略 key 至少包含 collective type、size-bin、nRanks、nNodes，可扩展包含 regBuff、numPipeOps。每个 key 维护固定候选列表、warmup 阶段、样本统计和当前策略。

候选示例：

```text
allreduce,size-bin=1MB-16MB:
  default
  ring/simple/channels=default
  tree/simple/channels=default
  ring/ll128/channels=default
```

选择函数必须只依赖所有 rank 可一致获得的输入，例如 key、collective sequence number、固定配置和稳定阶段标记。首版避免基于本 rank 即时性能直接切换。

替代方案：每个 rank 独立根据本地 algbw 最大值选择策略。该方案可能更“自适应”，但会产生 rank 不一致风险。

### 4. profiler 统计与 tuner 决策解耦

选择：profiler 负责记录样本并更新统计；tuner 负责读取已确定策略。统计更新可以用于实验报告和阶段结束后的策略固化，但在 warmup 过程中不直接导致单个 rank 独立切换。

理由：这样可以解释为“确定性试探 + 一致性选择”，实验结果可复现，也能避免 callback 时序差异导致策略发散。

替代方案：每次 profiler 完成后立即让 tuner 使用最新本地最优。该方案响应快，但更容易因异步完成顺序不同导致不同 rank 选择不同候选。

### 5. tuner 热路径必须无阻塞

选择：`getCollInfo` 中只允许 O(1) 查表、原子读、try-lock 成功后的短临界区和 cost table 修改。任何状态不可用时立即 fallback default。

理由：`getCollInfo` 处于 NCCL algorithm selection 路径。若在这里等待 profiler、文件、其他 rank、CUDA stream/event 或网络服务，会把调参逻辑变成新的 collective 等待点，甚至导致 rank 间相互等待。

替代方案：tuner 等待全局策略或等待 profiler 样本到齐后再返回。该方案理论上能使用更完整信息，但破坏 NCCL 热路径的低延迟和确定性，不适合首版。

### 6. profiler callback 只做有界记录

选择：profiler `startEvent`、`stopEvent`、`recordEventState` 只做元数据复制、timestamp/stat 更新、bounded ring buffer 写入或 dump flag 设置；JSON 格式化、文件输出和汇总分析放到后台线程或 finalize/report 阶段。

理由：profiler callback 可能在 NCCL 关键路径、proxy progress 相关路径或高频事件路径中执行。阻塞锁、频繁 malloc、同步 CUDA API 或文件写入会污染被测通信性能。

替代方案：在 callback 内直接输出完整 JSON 或实时聚合全局统计。该方案实现直观，但 profiler-only overhead 会很高，且可能改变 NCCL 等待行为。

### 7. 不使用跨进程共享状态作为首版决策依赖

选择：首版每个进程维护本地 `PolicyStore`，策略候选由确定性 schedule 推导，性能统计只用于记录和报告。单节点共享内存、mmap、SQLite、socket 或 rank0 控制面不作为首版 tuner 决策依赖。

理由：跨进程共享状态会引入初始化顺序、锁竞争、崩溃残留、清理、false sharing 和跨 rank 等待问题。确定性 schedule 可以在不共享决策状态的情况下保证各 rank 一致。

替代方案：使用 POSIX shared memory 或 mmap 让本机 ranks 共享统计。该方案适合第二阶段做全局聚合，但不适合一天内的低风险交付。

### 8. 尊重 NCCL stream/group 语义

选择：plugin 不调用 `cudaStreamSynchronize` 或 `cudaEventSynchronize` 来判断 collective 完成；完成时间来源优先使用 NCCL profiler 的 `KernelCh` 事件和已有 inspector 计时机制。

理由：NCCL collective 调用是异步 enqueue，group 内调用甚至可能在 `ncclGroupEnd` 前尚未真正 enqueue。plugin 若主动同步用户 stream，会改变应用的 stream dependency 和等待行为。

替代方案：在 profiler callback 中同步 stream 得到更直观的端到端时间。该方案会严重干扰被测 workload，并可能在 group/nonblocking communicator 场景下违反 NCCL 使用语义。

### 9. 版本选择以 tuner v5 和 profiler v5 为首版稳定面

选择：tuner 使用 `ncclTunerPlugin_v5`。profiler 首版可以基于 inspector 的 v5 实现；若目标 NCCL 支持 v6，则可额外导出 v6，但 allreduce 闭环不依赖 CE-specific v6 字段。

理由：tuner example 已提供 v5，profiler inspector 已提供 v5；这满足 allreduce 观测与调参。v6 主要扩展 CE collective 事件，对首日 allreduce 交付不是必要条件。

## Risks / Trade-offs

- [Risk] 多 rank 策略不一致导致 collective hang 或错误 → Mitigation: 策略选择只依赖确定性 schedule；首版默认单节点；禁止 per-rank 独立即时最优切换。
- [Risk] profiler overhead 影响性能数据 → Mitigation: 增加 profiler-only 实验组，单独量化观测开销；采样和日志输出默认保持轻量。
- [Risk] 某些 algorithm/protocol 在当前 topology 被 NCCL 标为 `NCCL_ALGO_PROTO_IGNORE` → Mitigation: tuner 只在 cost table 条目可用时设置低 cost，否则回退 NCCL 默认。
- [Risk] adaptive 策略不优于 baseline → Mitigation: 报告中明确展示候选、样本数和指标；允许 fallback default；目标是闭环和可对比，不承诺全场景收益。
- [Risk] 多节点共享策略复杂 → Mitigation: 首版不实现跨节点控制面；多节点作为后续扩展，需要 rank0 广播、共享文件系统或 sidecar 服务。
- [Risk] tuner 等待共享策略状态导致 NCCL 选择路径卡住 → Mitigation: 只允许非阻塞 policy read，失败立即 fallback default。
- [Risk] profiler callback 中的锁、I/O 或 malloc 污染通信性能 → Mitigation: callback 只做有界记录，重工作移到后台或实验后处理。
- [Risk] 容器 `/dev/shm`、memlock 或 cuMem host 配置导致 NCCL init/通信失败 → Mitigation: 实验文档记录 `--shm-size`、`memlock`、`NCCL_CUMEM_HOST_ENABLE=0` 等诊断项。
- [Risk] plugin 同步 CUDA stream 改变 NCCL group/stream 行为 → Mitigation: 不在 plugin callback 中同步用户 stream，以 NCCL profiler completion 信号作为计时依据。

## Migration Plan

1. 保持当前 NCCL core 不变。
2. 新增 adaptive plugin，并通过环境变量启用。
3. 对照运行 baseline、profiler-only、static tuner、adaptive tuner。
4. 若 plugin 加载失败或指标异常，清除 `NCCL_PROFILER_PLUGIN` 和 `NCCL_TUNER_PLUGIN` 即可回滚到 NCCL 默认行为。

## Validation Plan Using Available Container

### Confirmed Environment Facts

- 已有可用容器镜像：`nvcr.io/nvidia/pytorch:26.03-py3`
- 容器内 PyTorch 已动态链接系统 NCCL：`libnccl.so.2 => /lib/x86_64-linux-gnu/libnccl.so.2`
- 当前驱动/容器组合已能通过 `docker run --gpus all` 启动测试并删除容器了，请你按照需要构建合适的容器运行实验对比
- 容器内是否已有 `all_reduce_perf` 待确认；如果没有，计划在容器内构建 `nccl-tests` 来获取该 benchmark

### Planned Next Steps

1. 在宿主仓库中构建 `nccl/plugins/adaptive/libnccl-adaptive.so`
2. 以 bind mount 方式把仓库挂载进上述容器，统一在容器内执行验证，避免宿主与容器 NCCL 版本或动态库路径不一致
3. 使用带共享内存和 memlock 参数的容器启动方式进行实验：

```bash
docker run --rm --gpus all \
  --ipc=host \
  --ulimit memlock=-1 \
  --ulimit stack=67108864 \
  -v /home/wsl/projects/nccl-adapt:/workspace/nccl-adapt \
  -w /workspace/nccl-adapt \
  nvcr.io/nvidia/pytorch:26.03-py3 bash
```

4. 在容器内优先确认是否已有 `all_reduce_perf`
   - 若已有，直接用于 baseline / profiler-only / static tuner / adaptive tuner 四组实验
   - 若没有，优先在容器内构建 `nccl-tests`
   - 若不希望引入 `nccl-tests` 构建，则退回到 `torch.distributed` microbenchmark，但这会降低与 NCCL 原生对比的一致性
5. 先做最小 smoke test，只验证 NCCL 能成功 `dlopen` 同一个 `.so` 中的 `ncclProfiler_v5` 与 `ncclTunerPlugin_v5`
6. 在 smoke test 成功后执行四组模式：
   - baseline：不设置 adaptive plugin
   - profiler-only：仅设置 `NCCL_PROFILER_PLUGIN`
   - static tuner：设置 profiler+tuner，并固定 `NCCL_ADAPTIVE_STATIC_CANDIDATE`
   - adaptive tuner：设置 profiler+tuner，并启用 `NCCL_ADAPTIVE_MODE=adaptive`
7. 每组实验固定记录：
   - benchmark 命令行
   - `NCCL_DEBUG`
   - `NCCL_DEBUG_SUBSYS`
   - `NCCL_CUMEM_HOST_ENABLE`
   - `/dev/shm` 容量
   - `ulimit -l`
   - plugin 输出的 candidate/key/phase 日志
8. 验证任务完成条件：
   - 7.2：日志中确认 profiler/tuner 插件都被成功加载
   - 7.3：后续 collective 的决策日志出现 phase 递进，且当前已开始的 collective 不被回写
   - 7.4：profiler-only 与 baseline 有可量化 overhead
   - 7.5：adaptive 模式输出 warmup decision 和 latency/algbw/busbw 指标
   - 7.7：代码审查加运行日志共同证明 callback 中没有 `cudaStreamSynchronize` / `cudaEventSynchronize`
   - 7.8：通过关闭 adaptive、制造候选不可用或让策略读取竞争失败来观察 default fallback
9. 最后输出 8.1-8.4 的实验报告，比较四组模式并记录限制项

### Inputs Still Needed From Reviewer

为了继续执行，审阅阶段只需要你确认或提供下面几项最小信息：

- 目标是否明确限定为单机实验；如果不是，需要先把多机从本次验证范围中排除
- 机器上的 GPU 数量，以及是否直接按全部 GPU 跑
- 容器内是否已经有 `all_reduce_perf`；如果没有，是否接受我在容器内构建 `nccl-tests`
- 是否允许直接把当前仓库目录挂载到容器内执行验证
- 你希望优先验证的消息规模范围；若无偏好，先按 `1K -> 256M, factor=2, warmup=20, iters=100`

### Reviewer Decision Defaults

如果你不额外指定，后续执行默认采用以下假设：

- 场景仅限单机多 GPU
- 优先使用 `all_reduce_perf`
- 若容器内缺少 `all_reduce_perf`，则在容器内构建 `nccl-tests`
- 使用全部可见 GPU
- 容器运行参数固定包含 `--ipc=host --ulimit memlock=-1 --ulimit stack=67108864`

## Runtime Verification Findings

### Confirmed Working Paths

- 在 `nvcr.io/nvidia/pytorch:26.03-py3` 中，`torch.cuda.device_count()` 可见 8 张 GPU，普通 `torch.cuda` 张量运算正常
- 8 进程 `torchrun` + `backend=nccl` baseline allreduce 可成功完成，说明当前容器、驱动和 NCCL 基线链路可用
- baseline 8 卡 8MB allreduce smoke test 已得到稳定汇总输出，可作为后续 overhead 对照组
- profiler-only 模式可完成 allreduce，并在退出时输出 adaptive profiler 记录，说明 profiler callback 路径可运行
- 运行时日志已确认 NCCL 成功加载：
  - external profiler plugin `libnccl-adaptive.so`
  - external tuner plugin `libnccl-adaptive.so`
  - `TUNER/Plugin: Using Adaptive (v5)`
  - `PROFILER/Plugin: Loaded Adaptive (v5)`

### Observed Blockers

- 容器自带 `/usr/local/bin/all_reduce_perf`，但该二进制在当前环境下即使 baseline `-g 1` 也会触发 `Cuda failure 101 'invalid device ordinal'`
- 因此本次 runtime verification 已切换到 `torchrun` 驱动的 NCCL allreduce smoke test 作为执行路径
- 一旦同时启用 profiler+tuner：
  - `NCCL_PROFILER_PLUGIN=/workspace/nccl-adapt/nccl/plugins/adaptive/libnccl-adaptive.so`
  - `NCCL_TUNER_PLUGIN=/workspace/nccl-adapt/nccl/plugins/adaptive/libnccl-adaptive.so`
  - `torchrun --nproc-per-node=8 ./torch_allreduce_smoke.py`
  - 多个 rank 会在第一轮 8MB allreduce 附近发生 `SIGSEGV`
- 该崩溃在以下两种模式下都可复现：
  - `NCCL_ADAPTIVE_MODE=adaptive`
  - `NCCL_ADAPTIVE_MODE=static` 且 `NCCL_ADAPTIVE_STATIC_CANDIDATE=tree/simple`
- 因此当前 blocker 不是“plugin 未加载”，而是“tuner 路径启用后存在运行时崩溃”

### Evidence Captured

- baseline 成功路径：8 卡 `torchrun` 输出了每轮 iteration JSON 和最终 summary JSON
- profiler-only 成功路径：退出时输出 `ADAPTIVE/record ...` 与 `Closing profiler plugin Adaptive`
- adaptive / static-tuner 失败路径：日志中已确认成功加载 tuner plugin，并出现 `ADAPTIVE/decision ...`，随后发生多 rank `SIGSEGV`
- 关键日志文件位于：
  - `/home/wsl/projects/nccl-adapt/nccl/plugins/adaptive/runtime-logs/adaptive.log`
  - `/home/wsl/projects/nccl-adapt/nccl/plugins/adaptive/runtime-logs/static-tree.log`

### Immediate Next Debug Direction

下一个实现回合应优先收敛 tuner 崩溃，而不是继续扩大实验矩阵。建议顺序：

1. 先把 8 卡 `torchrun` baseline / profiler-only 路径固定为回归基线
2. 用最小输入保持 `tuner` 启用，但减少 profiler 侧复杂度，定位是否为 profiler+tuner 共享状态交互导致
3. 检查 `getCollInfo` 返回路径、candidate 应用逻辑以及 profiler/tuner 共享对象生命周期
4. 在 tuner 打开但强制 default candidate 的条件下复现，判断问题是否来自“仅加载 tuner”还是“修改 cost table”

## Open Questions

- 首版是否只支持 allreduce，还是同时纳入 broadcast/reduce-scatter/all-gather 的候选表？
- 实验环境是否已有可用 `all_reduce_perf`，还是用 torch/distributed microbenchmark 作为替代？
- 最终策略选择是否在一次进程生命周期内进入 exploit 阶段，还是仅输出离线推荐配置用于下一次运行？
