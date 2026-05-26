## Why

当前自适应 NCCL 插件已经具备 weak-online、final-steady、profiler-only、static replay 和分层实验协议，但最新实验仍显示明显的 replicate 间波动：`baseline` 与 `profiler-only` 的相对顺序不稳定，`final-steady` 与 `weak-online` 的开销排序也不稳定。与此同时，历史 `4-8 MiB` size bucket candidate 分叉没有在新协议 rerun 中复现。

这台 8x RTX 5090 服务器的拓扑是双 socket `4+4`：GPU0-3 位于 NUMA0，GPU4-7 位于 NUMA1，跨组通信显示为 `SYS`，需要穿过 CPU socket 间互联；NIC `mlx5_0` 位于 NUMA1。现阶段必须先把拓扑变量从算法变量中分离出来，否则无法判断 overhead 波动、recheck spike 和 bucket honesty 风险到底来自插件机制、NCCL/PyTorch 测量噪声，还是来自跨 NUMA PCIe/UPI 路径。

## What Changes

- 新增拓扑受控实验矩阵，明确比较 `GPU0-3`、`GPU4-7` 和 `GPU0-7` 三类 placement。
- 将 CPU/NUMA affinity、GPU PCIe topology、NIC locality、PCIe link state 和运行 placement 记录为实验元数据。
- 固定沿用历史容器镜像 `nvcr.io/nvidia/pytorch:26.03-py3`，并记录容器 image id/digest、PyTorch/NCCL/CUDA 版本和插件动态链接检查结果。
- 按 topology group 分层重跑 baseline、profiler-only、final-steady、weak-online，用于定位 overhead 波动来源。
- 按 topology group 重跑 weak-online phase 统计，用于判断 recheck spike 是否主要由跨 NUMA 路径放大。
- 按 topology group 重跑 `5/6/7 MiB` size sweep，用于判断 size bucket honesty 分叉是否可复现且是否与跨 NUMA placement 相关。

## Non-Goals

- 不修改 adaptive policy 算法、candidate 集合、switch threshold 或 activation 机制。
- 不在本 change 中引入 topology-aware policy key。
- 不在本 change 中拆分 size bucket 或实现 midpoint sub-bucket refinement。
- 不扩展到 multi-node；本 change 只处理当前单机 `4+4` PCIe/NUMA 拓扑。
- 不把实验结果预设为插件问题或硬件问题；本 change 的目标是可判别定位。

## Capabilities

### New Capabilities

- `topology-controlled-adaptive-experiments`: 定义单机 `4+4` GPU/NUMA 服务器上的拓扑受控自适应 NCCL 实验矩阵、元数据契约和结果判定边界。

## Impact

- 影响 `nccl/plugins/adaptive/run_torch_modes.sh` 或配套运行方式，用于支持 topology group / CUDA device placement / CPU affinity 的显式记录和控制。
- 影响 `nccl/plugins/adaptive/analyze_experiment_results.py` 或后续分析方式，用于按 topology group 聚合 comparison、phase 和 size sweep 结果。
- 影响实验 metadata 采集范围，要求记录 Docker image、容器内 `ldd libnccl-adaptive.so`、`ldd --version`、插件导出符号和 NCCL 实际加载日志。
- 影响 `nccl/plugins/adaptive/README.md` 的实验章节，使历史 bucket honesty 结论与新拓扑受控结果分开叙述。
- 影响后续是否提出 topology-aware key、bucket refinement 或 recheck 策略优化，但本 change 本身不实施这些算法改动。
