## 1. 实验协议与元数据

- [x] 1.1 梳理当前 `run_torch_modes.sh` 与结果目录约定，定义 replicate、run order 和实验类型的统一命名规则
- [x] 1.2 扩展结果元数据采集范围，确保记录 adaptive 控制参数、workload 参数、关键 NCCL 环境、replicate id 和 run order
- [x] 1.3 明确 mode comparison、correctness、policy-quality、state-granularity 四类实验的输入参数与输出约定

## 2. Harness 与统计输出

- [x] 2.1 调整 `run_torch_modes.sh`，使 mode comparison 支持多个 replicate 和顺序轮换或显式随机化
- [x] 2.2 调整 `torch_allreduce_smoke.py` 或配套分析输出，使 weak-online 结果能够区分 warmup、steady 和 recheck 阶段
- [x] 2.3 为 mode comparison 增加更稳健的统计口径，至少支持 median、p95、max 和分段解释
- [x] 2.4 定义 static replay 实验入口或执行方式，使 learned candidate 能被独立验证

## 3. 状态颗粒度实验与文档

- [x] 3.1 设计并实现同一 size bucket 内的 size sweep 实验协议，固定除 message size 外的其他变量
- [x] 3.2 为 size sweep 输出 candidate trajectory 结果格式，支持跨 replicate 比较不同 size 的候选分层
- [x] 3.3 重写 `nccl/plugins/adaptive/README.md` 的实验章节，按机制正确性、机制成本、策略质量和状态颗粒度分层叙述
- [x] 3.4 用一组更新后的结果验证新协议可以支持更明确的结论边界，并记录已知限制
