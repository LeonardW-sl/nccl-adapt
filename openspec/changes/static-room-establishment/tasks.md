## 0. Decision Freeze

- [x] 0.1 将第一层目标固定为“产出有边界的固定方案空间图”，而不是承诺一定证明正例
- [x] 0.2 将第一版结论绑定到 `surface-v1-current` 和当前已实现候选集合
- [x] 0.3 明确确认阶段首选经过校准的矩阵计算小步；若仍使用轻量逐元素计算，必须记录敏感性警告
- [x] 0.4 明确默认对照组只作为耗时地板，不强行解释默认路径
- [x] 0.5 明确第一层主判定是相对干净默认对照的净收益
- [x] 0.6 明确判赢阈值、重复投票和晋级规则必须在实验前冻结

## 1. Measurement And Schema

- [x] 1.1 固定 `surface v1` 的边界：`numa1-4gpu`、`allreduce`、same-socket 4-GPU / single-node
- [x] 1.2 固定 `tail-anchored static microstep` harness 的 stream geometry、launch order 与 boundary 定义
- [x] 1.3 固定 compute preamble / overlap slab / epilogue 的 kernel family 与相对时长口径
- [x] 1.4 固定 GEMM calibration 规则：dtype 优先级、shape ladder、unit-GEMM 选择与 repeat 推导
- [x] 1.5 固定 screening 简化 calibration 与 confirmation 完整 calibration 的默认口径
- [x] 1.6 固定本 change 的 `matrix-manifest` 契约：header、regime、arms、boundary、judgment 字段
- [x] 1.7 固定本 change 的统一 summary schema 与 `evidence.md` 模板
- [x] 1.8 明确 communication-local 与 microstep-level 指标必须在同一 run family 内同时记录
- [x] 1.9 明确 candidate availability、path-equivalence、replicate vote 与负结论绑定规则
- [x] 1.10 固定 confirmation promotion gate：只有 `confirmation-full` 的 GEMM / matmul 小步结果才能产出 `workload-confirmed static win`
- [x] 1.11 明确 pointwise / 逐元素小步只能作为 sanity、debug 或 screening 辅助；若用于 confirmation，必须记录 `harness sensitivity warning`，且不得进入 promotion pack
- [x] 1.12 固定 analyzer / summary 的双层判定输入：communication 主指标使用 `collective_device_elapsed_ms`，workload 主指标使用 `microstep_time_ms`

## 2. Controlled Candidate Surface

- [x] 2.1 定义 `controlled axes`、`observed-only axes` 与 `excluded axes`
- [x] 2.2 清点 `surface v1` 当前 realization 中可用的 fixed candidate families
- [x] 2.3 明确 screening 阶段允许探索的更宽 fixed candidate family
- [x] 2.4 记录哪些 candidates 进入 screening、哪些被排除，以及原因

## 3. Screening Stage

- [x] 3.1 固定 screening 的 reduced size set
- [x] 3.2 运行 `baseline`、`profiler-only` 与 screening fixed candidates
- [x] 3.3 同步读取 collective-local、`microstep_time_ms` 与 `boundary_tail_ms`
- [x] 3.4 输出 screening manifest、shortlist candidates 与 exclusion reasons

## 4. Confirmation Stage

- [x] 4.1 固定 confirmation 的 full size set 与 replicate 口径
- [x] 4.2 实现或接入 GEMM-based compute slab，替换 confirmation 阶段的逐元素 compute slab
- [x] 4.3 实现 dtype 选择：首选 `bfloat16`，不可用时退到 `float16`
- [x] 4.4 对每个 confirmation regime 先测 `baseline` 的 `collective_device_elapsed_ms`
- [x] 4.5 按 shape ladder 选择 base GEMM shape，并记录 warmed unit-GEMM latency
- [x] 4.6 推导并冻结 `R_block`、`R_overlap`、`R_epi`
- [x] 4.7 确保同一 regime 的所有 candidate arms 与 replicates 复用同一套 dtype、shape 和 repeats
- [x] 4.8 对 shortlisted candidates 运行 `baseline`、`profiler-only` 与 fixed static comparisons
- [x] 4.9 输出 candidate-level `communication-positive` judgment
- [x] 4.10 输出 candidate-level `workload-positive` judgment；若 harness 不是 `confirmation-full` GEMM / matmul，不得输出可晋级的 workload-positive
- [x] 4.11 输出 regime-level三分类：
  - `no proven communication room`
  - `communication-only win`
  - `workload-confirmed static win`
- [x] 4.12 输出 confirmation manifest，并记录 calibration freeze 与 boundary contract
- [x] 4.13 记录 `step-positive / comm-nonpositive anomaly`、harness sensitivity warning 与 failure reasons

## 5. Exit Summary

- [x] 5.1 生成一份 `surface v1 statement`
- [x] 5.2 生成一份 screening 摘要与 shortlist
- [x] 5.3 生成一份 candidate-level judgment 摘要
- [x] 5.4 生成一份 regime-level judgment 摘要
- [x] 5.5 生成一份可晋级到 `same-key-phase-shift-validation` 的 promotion pack
- [x] 5.6 若未证明 static room，显式写出
  `no proven room on current controlled surface version`
