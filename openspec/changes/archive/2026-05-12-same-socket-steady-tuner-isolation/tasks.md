## 1. Matrix Definition

- [x] 1.1 定义 same-socket steady-tuner isolation 的结果目录、manifest 字段和运行参数，限定为 `numa0-4gpu` / `numa1-4gpu`
- [x] 1.2 固定 `profiler-only` / `final-steady` 两模式以及与 topology-controlled rerun 一致的容器与 adaptive 参数
- [x] 1.3 将测量窗口拉长到能摊薄前段 warmup / publish / activate 成本的长度，并把该长度写入 metadata contract

## 2. Diagnostics And Analysis

- [x] 2.1 确保 `final-steady` 运行保留 coordinator 与 completion trace，并可定位 first publish / first activate / activated candidate
- [x] 2.2 扩展分析输出，使 `final-steady` 至少生成 overall、pre-activation、post-activation 三类统计
- [x] 2.3 对 `profiler-only` 保留 callback-only 对照统计，避免把它误当成 activate-aware 模式

## 3. Same-Socket Execution

- [x] 3.1 运行 `numa0-4gpu` 的 `profiler-only` / `final-steady` 长测诊断批次
- [x] 3.2 运行 `numa1-4gpu` 的 `profiler-only` / `final-steady` 长测诊断批次
- [x] 3.3 聚合 same-socket steady-tuner jump、激活边界、candidate 和 `wait-summary` / completion diagnostics

## 4. Evidence And Conclusion Boundary

- [x] 4.1 更新 change-local evidence，索引 same-socket steady-tuner isolation 目录与关键结论
- [x] 4.2 更新 README，明确 `topology-controlled` 结论与 `same-socket steady-tuner isolation` 结论的边界
- [x] 4.3 给出下一步判定：steady tuner / coordinator 路径、warmup/publish/activate 前段污染，或 socket-local placement / affinity 差异
