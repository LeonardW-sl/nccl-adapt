## 1. 拓扑与元数据基线

- [x] 1.1 记录当前服务器拓扑快照：`nvidia-smi topo -m`、GPU bus ID、PCIe link state、`numactl -H`、NIC NUMA locality
- [x] 1.2 定义 topology group 命名与参数约定：`numa0-4gpu`、`numa1-4gpu`、`cross-8gpu`
- [x] 1.3 明确每个 topology group 的 `CUDA_VISIBLE_DEVICES`、`NPROC_PER_NODE` 和 CPU affinity 记录方式
- [x] 1.4 扩展实验结果 metadata 约定，确保 topology group、placement、NUMA/PCIe/NIC 信息能随结果归档
- [x] 1.5 固定实验容器为 `nvcr.io/nvidia/pytorch:26.03-py3`，并记录 Docker image id/digest、启动参数和容器内工作目录
- [x] 1.6 在容器内记录插件动态链接与导出符号检查：`ldd libnccl-adaptive.so`、`ldd --version`、`readelf -d`、`nm -D`

## 2. 拓扑受控 mode comparison

- [x] 2.1 先跑 baseline-only topology smoke，比较 4 卡同 socket 与 8 卡跨 socket 的纯 NCCL/PyTorch 波动
- [x] 2.2 对每个 topology group 运行 `baseline`、`profiler-only`、`final-steady`、`weak-online`
- [x] 2.3 保持 replicate、run order、message size、warmup/measure iters 和 adaptive 参数一致
- [x] 2.4 确认 NCCL 日志中 profiler/tuner plugin 实际加载路径为 `/workspace/nccl-adapt/nccl/plugins/adaptive/libnccl-adaptive.so`
- [x] 2.5 按 topology group 聚合 median、p95、max、phase stats 和 replicate 间波动

## 3. Recheck spike 定位

- [x] 3.1 对每个 topology group 输出 weak-online warmup、steady、recheck 分段统计
- [x] 3.2 比较 `final-steady` 与 `weak-online` 的 steady 段差异，避免把 recheck spike 混入 steady 成本
- [x] 3.3 至少对一个 topology group 调整 `NCCL_ADAPTIVE_RECHECK_AFTER`，确认 spike 位置是否随 recheck 周期移动

## 4. Size bucket honesty 复验

- [x] 4.1 对每个 topology group 运行 `SIZE_SWEEP_MBS=5,6,7` 的 weak-online size sweep
- [x] 4.2 输出每个 size 的 candidate trajectory，并按 topology group 比较 candidate 是否稳定分叉
- [x] 4.3 若只在 `cross-8gpu` 分叉，将结论限定为 topology-sensitive bucket honesty 风险
- [x] 4.4 若同 socket groups 也稳定分叉，再提出后续 bucket refinement change

## 5. 文档与结论边界

- [x] 5.1 更新 evidence，索引 topology-controlled 实验目录和关键结论
- [x] 5.2 更新 README 实验章节，区分历史 bucket honesty 观察、新协议 rerun 和拓扑受控 rerun
- [x] 5.3 给出下一步判定：环境/拓扑问题、profiler host path 问题、weak-online recheck 问题，或 size bucket 设计问题
