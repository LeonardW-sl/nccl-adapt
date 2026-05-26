## 1. NUMA1 Matrix Definition

- [x] 1.1 定义 `numa1-4gpu` 专用结果目录、manifest 字段和长窗口参数，固定为 `baseline` / `profiler-only` / `static-replay` / `final-steady`
- [x] 1.2 固定与 same-socket long-window 一致的 workload、container、CPU affinity 和 adaptive 参数，只在 `numa1-4gpu` 上执行
- [x] 1.3 定义 static replay candidate 对齐规则：默认使用当前 `ring/simple`，若 rerun learned candidate 变化，则显式记录并重放对齐 candidate

## 2. Observability And Analysis

- [x] 2.1 将 plugin-enabled 运行的 `selectedAlgo` / `selectedProto` / `nChannels` 与 candidate 信息暴露到可解析结果契约
- [x] 2.2 扩展分析输出，明确给出 `profiler-only - baseline`、`static-replay - profiler-only`、`final-steady post-activation - static-replay` 三类分解差值
- [x] 2.3 在聚合结果中输出 candidate 对齐状态，避免把 candidate mismatch 误写成 dynamic 机制税

## 3. NUMA1 Mechanism Decomposition Execution

- [x] 3.1 运行 `numa1-4gpu` 的 `baseline` / `profiler-only` / `static-replay` / `final-steady` 长窗口诊断批次
- [x] 3.2 验证 `final-steady` 的 learned candidate 与 `static-replay` 是否对齐；若不对齐，补跑 candidate-aligned replay
- [x] 3.3 输出 `numa1` 上的三段分解结论：`profiler-only - baseline`、`static-replay - profiler-only`、`final-steady post-activation - static-replay`

## 4. Evidence Boundary And H100 Gate

- [x] 4.1 更新 change-local evidence，索引 `numa1` 分解结果与 candidate/algo/proto 观测
- [x] 4.2 在 change-local evidence 中明确结论边界：`numa1` 机制结论不自动外推到 `numa0` 或 H100
- [x] 4.3 输出明确的 H100 follow-up `go / no-go` 判定；若为 `no-go`，列出仍阻塞迁移的证据缺口
