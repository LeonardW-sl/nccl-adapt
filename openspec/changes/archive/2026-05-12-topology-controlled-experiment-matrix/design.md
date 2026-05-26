## Context

最新协议实验已经把 adaptive NCCL 的验证拆成 correctness、mode-comparison、policy-quality 和 state-granularity 四类问题。但当前结果仍有一个未分离变量：机器拓扑。

当前服务器拓扑摘要：

- 8 张 NVIDIA GeForce RTX 5090。
- GPU0-3 在 NUMA0，CPU affinity 为 `0-31,64-95`。
- GPU4-7 在 NUMA1，CPU affinity 为 `32-63,96-127`。
- GPU0-3 组内互联为 `NODE`。
- GPU4-7 组内互联为 `NODE`。
- GPU0-3 到 GPU4-7 跨组互联为 `SYS`。
- NIC `mlx5_0` 位于 NUMA1，靠近 GPU4-7。
- PCIe link 当前均为 Gen5 x16。

因此，8 卡实验天然混合了两类路径：

```text
4-card same-socket path
  GPU0..3 or GPU4..7
  └─ PCIe within one NUMA node

8-card cross-socket path
  GPU0..3 <-> GPU4..7
  └─ PCIe + CPU socket interconnect
```

如果不控制 placement，插件机制开销、PyTorch/NCCL 运行噪声、CPU 调度、NUMA 内存分配和跨 socket 通信会混在一起。

## Goals / Non-Goals

**Goals:**

- 建立 `GPU0-3`、`GPU4-7`、`GPU0-7` 三组拓扑 placement 的最小实验矩阵。
- 让每个实验结果目录能说明它跑在哪些 GPU、绑定了哪些 CPU、属于哪个 NUMA group、是否跨 socket。
- 先用 baseline-only 判断纯 NCCL/PyTorch allreduce 是否已经存在 topology-sensitive 波动。
- 再逐层加入 profiler-only、final-steady 和 weak-online，定位额外波动从哪一层开始出现。
- 用 phase-aware weak-online 统计判断 recheck spike 是否主要出现在跨 socket placement。
- 用 topology 分层 size sweep 判断 `4-8 MiB` bucket honesty 风险是否可复现。

**Non-Goals:**

- 不改 adaptive 插件算法。
- 不改 size bucket 计算。
- 不把 topology 写入 policy key。
- 不把 `mlx5_0`/RDMA path 纳入正式变量；当前 torch allreduce 仍以单机路径为主，NIC locality 只作为元数据记录。

## Experiment Matrix

### Topology groups

| Group | CUDA devices | CPU affinity | Interpretation |
| --- | --- | --- | --- |
| `numa0-4gpu` | `0,1,2,3` | `0-31,64-95` | 单 socket / NUMA0 内 4 卡 |
| `numa1-4gpu` | `4,5,6,7` | `32-63,96-127` | 单 socket / NUMA1 内 4 卡，靠近 NIC |
| `cross-8gpu` | `0,1,2,3,4,5,6,7` | `0-127` 或显式双 NUMA | 跨 socket 8 卡 |

### Mode matrix

每个 topology group 至少运行：

- `baseline`
- `profiler-only`
- `final-steady`
- `weak-online`

每组都应使用相同 message size、warmup、measure iters、adaptive 参数和 replicate/order 策略，除非某个 group 因 GPU 数不同需要记录 `NPROC_PER_NODE` 差异。

### Size sweep matrix

每个 topology group 至少运行：

- `SIZE_SWEEP_MBS=5,6,7`
- `SWEEP_MODE=weak-online`
- 固定 adaptive 参数、replicate 数和 mode order 策略

目标不是证明哪个 size 更快，而是比较同一 bucket 内 candidate trajectory 是否按 topology group 稳定分叉。

## Container Runtime Contract

本 change 的拓扑受控实验应继续使用历史实验镜像：

```text
nvcr.io/nvidia/pytorch:26.03-py3
```

基础启动参数沿用历史成功路径：

```bash
docker run --rm --gpus all \
  --ipc=host \
  --ulimit memlock=-1 \
  --ulimit stack=67108864 \
  -v /home/wsl/projects/nccl-adapt:/workspace/nccl-adapt \
  -w /workspace/nccl-adapt \
  nvcr.io/nvidia/pytorch:26.03-py3 bash
```

实验仍以 `torchrun` 驱动 `torch_allreduce_smoke.py` 为主。历史上容器内 `all_reduce_perf` 在当前环境即使 baseline `-g 1` 也触发 `Cuda failure 101 'invalid device ordinal'`，因此除非单独证明该问题已消失，否则不得把 `all_reduce_perf` 与 torchrun 结果混作同一实验序列。

每个 topology-controlled 实验批次必须记录容器内运行时信息：

- Docker image tag、image id，若可用则记录 repo digest。
- `python -c` 输出的 PyTorch、CUDA 可用性和 `torch.version.cuda`。
- 容器内 NCCL 库解析路径，例如 `ldconfig -p | grep libnccl` 或 `ldd` 到 PyTorch NCCL 依赖的等价信息。
- `ldd --version`，用于记录 glibc 版本。
- `ldd /workspace/nccl-adapt/nccl/plugins/adaptive/libnccl-adaptive.so`。
- `readelf -d` 或等价方式记录插件 `NEEDED` 动态库。
- `nm -D --defined-only` 或等价方式确认 `ncclProfiler_v5` 和 `ncclTunerPlugin_v5` 导出。

该检查的目的不是把插件链接到 NCCL；插件应保持 NCCL runtime `dlopen` 模式。检查目标是证明容器内可以解析插件依赖，并且 NCCL 日志实际加载的是挂载路径下的 `libnccl-adaptive.so`。

## Decisions

### 1. 先控制 placement，再讨论算法改动

不直接实现 topology-aware key 或 sub-bucket refinement。原因是当前最新协议没有复现历史 bucket 分叉，贸然改 key 会把未定位的系统噪声固化成算法复杂度。

### 2. 将 4 卡同 socket 作为噪声下界

`numa0-4gpu` 和 `numa1-4gpu` 的 baseline 结果用于估计同 socket 下纯 NCCL/PyTorch 的波动。如果 4 卡同 socket 也高度不稳定，应先查测量方式、CPU binding、系统负载或 profiler/tuner host path。

### 3. 将 8 卡跨 socket 作为放大器

`cross-8gpu` 用于观察跨 socket 路径是否系统性放大 p95/max、recheck spike 或 candidate 分叉。如果只有 8 卡出现问题，后续设计应优先考虑 topology/rank-domain 层面的解释。

### 4. 结果解释按判别树进行

```text
baseline 4-card unstable
  => 先处理测量环境或系统噪声

baseline 4-card stable, baseline 8-card unstable
  => 拓扑/跨 socket 是主要变量

baseline stable, profiler-only unstable
  => profiler callback 或 host timing 路径是主要变量

profiler-only stable, final-steady unstable
  => tuner steady path 或 shared coordinator read/activation 是主要变量

final-steady stable, weak-online unstable
  => recheck window / summary aggregation / candidate sampling 是主要变量

size sweep only diverges in cross-8gpu
  => bucket honesty 风险可能与拓扑域耦合

size sweep diverges in same-socket groups too
  => bucket 本身可能过粗，后续再考虑 sub-bucket refinement
```

### 5. 固定历史容器，避免混入 runtime 版本变量

本轮实验优先固定 `nvcr.io/nvidia/pytorch:26.03-py3`，因为历史 2026-04-26 结果来自该镜像，且日志已证明 NCCL 能通过环境变量加载挂载路径下的 adaptive profiler/tuner plugin。若必须替换镜像，替换后的结果必须与 `26.03-py3` 结果分开归档和解释，不得直接合并聚合。

## Metadata Contract

每个 topology-controlled run 至少记录：

- `topology_group`
- `cuda_visible_devices`
- `nproc_per_node`
- `cpu_affinity`
- `numa_nodes`
- `cross_socket=true|false`
- `nvidia-smi topo -m` snapshot 或其路径
- GPU PCIe bus IDs 和 PCIe link state
- NIC locality，至少记录 `mlx5_0` 的 NUMA node
- `numactl -H` snapshot 或其路径
- Docker image tag、image id/digest、容器启动参数和容器内工作目录
- PyTorch、CUDA、NCCL 和 glibc 版本
- 容器内 `ldd libnccl-adaptive.so` 与 `ldd --version` 输出
- 插件 `NEEDED` 动态库和 `ncclProfiler_v5` / `ncclTunerPlugin_v5` 导出符号检查
- NCCL 日志中 profiler/tuner plugin 实际加载路径
- adaptive 控制参数
- replicate id 与 run order

## Risks / Trade-offs

- [4 卡与 8 卡 world size 不同] → 4 卡不是 8 卡的直接性能替代，只作为 topology/noise 下界；结论必须避免把 4 卡吞吐直接外推到 8 卡。
- [CPU affinity 控制可能改变 PyTorch torchrun 行为] → 先记录和最小化控制；如果使用 `numactl`，必须把绑定方式写入 metadata。
- [历史镜像本地可能不存在] → 需要先拉取 `nvcr.io/nvidia/pytorch:26.03-py3` 或明确记录镜像替代；替代镜像结果不能和历史镜像结果直接合并。
- [插件由宿主构建但在容器内加载] → 必须记录容器内动态链接检查，避免 glibc/libstdc++ 版本差异被误判为 NCCL 或插件行为差异。
- [NIC locality 可能暂时不参与单机 allreduce] → 仍记录它，因为后续 multi-node 或 RDMA path 会受影响。
- [实验成本增加] → 先采用 3 replicate 的最小矩阵，只有在结果不稳定时再扩展 replicate。

## Open Questions

- `cross-8gpu` 是否应显式绑定全部 CPU，还是分别尝试 interleave/localalloc 策略。
- 是否需要把 GPU order 固定为 `0,1,2,3,4,5,6,7` 与反序 `4,5,6,7,0,1,2,3` 对照，以判断 NCCL ring 构造是否受 rank order 影响。
- 是否需要在本 change 内增加一个只跑 `baseline` 的快速 topology smoke，作为完整矩阵前置门槛。
