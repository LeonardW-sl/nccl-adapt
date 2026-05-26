## 1. 问题定义与结果契约

- [x] 1.1 明确 `same key` 的判定口径：`commId + collType + size bucket + nRanks + nNodes` 表示重复 collective 域，而不是单次 in-flight collective 实例
- [x] 1.2 将 `future correction, not in-flight mutation` 写入 change-local evidence 或后续 spec，避免把 switching 误解为单次 collective 中途改写
- [x] 1.3 定义本 change 的统一比较阶梯：`baseline -> best static candidate -> best piecewise-static policy -> final-steady -> weak-online`
- [x] 1.4 明确 falsification 也是有效结果：允许输出 `no headroom`、`static envelope sufficient`、`drift not strong enough`
- [x] 1.5 将机制阈值与证据阈值分离写清：`NCCL_ADAPTIVE_SWITCH_THRESHOLD_PCT` 属于 coordinator 行为阈值，不等于实验结论自动成立
- [x] 1.6 固定第一版正向证据门槛：aggregate latency delta 至少 `2.0%`，且 `3` 个 replicate 中至少 `2` 个 replicate 同方向
- [x] 1.7 定义 `stable candidate / policy flip` 的口径：winner 变化必须在至少 `2/3` replicate 中重复，并相对 control winner 达到 `2.0%` 优势
- [x] 1.8 定义 no-drift 与 drift-driven advantage 的区分规则：若 no-drift 下已存在同等级优势，则不得直接记作 drift-driven switching value

## 2. Phase 1: Same-Key Headroom

- [x] 2.1 固定 `Batch A` clean-surface regime：`numa1-4gpu`、`allreduce`、单一 communicator-domain、same-socket 4 GPU world、`warmup=4`、`measure=192`、`replicates=3`
- [x] 2.2 按固定 size 集合运行 `Batch A`：`4/8/16/32/64/128/256 MiB`
- [x] 2.3 对 `Batch A` 每个 size 比较 `baseline`、`static-replay`、`final-steady`、`weak-online`
- [x] 2.4 对 `Batch A` 每个 size 检查 `final-steady` learned candidate；若与 replay candidate 不同，则补跑 candidate-aligned `static-replay`
- [ ] 2.5 对 `Batch A` 每个 size 输出 headroom 判定：`no proven headroom` 或 `headroom-positive`
- [ ] 2.6 仅将 `headroom-positive` 的 size 晋级到 `Batch B`
- [x] 2.7 固定 `Batch B` topology promotion：对晋级 size 至少运行 `cross-8gpu`；`numa0-4gpu` 只作为 anomaly boundary，可记录但不作为第一批主证明面
- [ ] 2.8 输出 `Batch B` 结论，判断 headroom 是 clean-surface 特有，还是在更复杂 topology 上仍然存在
- [x] 2.9 固定 `Phase 1` run manifest 口径：每个 run 必须记录 `batch / topology / size / mode / replicate / result_dir / summary artifact`

## 3. Phase 2: Static Envelope Search

- [ ] 3.1 仅选择 `Phase 1` 中被标记为 `headroom-positive` 的 size 进入 `Phase 2`
- [ ] 3.2 对每个晋级 size，先在当前 clean reference 面整理 `best static candidate`，并记录 candidate 是否随 size 改变
- [ ] 3.3 对每个晋级 size，合并 `Batch B` 的 topology 结果，至少比较 `numa1-4gpu` 与 `cross-8gpu`，判断最佳 candidate 是否随 topology 改变
- [ ] 3.4 以 `size bucket + topology group` 为第一版静态规则表达，写出 `best piecewise-static policy` 草案
- [ ] 3.5 用该草案回看 `Phase 1` 已完成 regime，比较：
  - 单一最佳 static candidate
  - `best piecewise-static policy`
  - `final-steady`
- [ ] 3.6 若主要收益已被 `size bucket + topology group` 解释，则输出 `static envelope sufficient`
- [x] 3.7 只有在 `size bucket + topology group` 仍解释不足时，才继续补 world-size 维度；若需要补 world-size，必须显式列出新增 regime 和原因
- [ ] 3.8 输出 `Phase 2` 结论，明确哪些 regime 已可由静态表解释，哪些 regime 仍保留为 drift challenge 入口
- [x] 3.9 固定 `Phase 2` run manifest 口径：每个 run 必须记录 `rule_scope / rule_id / topology / size / mode_or_policy / replicate / result_dir / summary artifact`

## 4. Phase 3: Drift Challenge

- [ ] 4.1 仅选择 `Phase 2` 中被标记为“静态包络仍解释不足”的 regime 进入 `Phase 3`
- [x] 4.2 为每个晋级 regime 固定一个 no-drift 对照批次，作为 drift challenge 的比较地板
- [x] 4.3 固定第一类 drift family 的最小三臂模板：`control`、`compute-overlap-early`、`compute-overlap-late`
- [x] 4.4 固定第二类 drift family 的最小三臂模板：`control`、`low-comm-interference`、`high-comm-interference`
- [x] 4.5 为计算 drift family 写出最小实现契约：`early/late` 只允许改变背景计算相对于目标 collective 的启动相位，不得同时改变静态 key 或计算负载家族
- [x] 4.6 为通信 drift family 写出最小实现契约：`low/high` 只允许改变干扰强度，不得同时更换多个强度旋钮或改变静态 key
- [x] 4.7 对每个 drift challenge regime，固定比较：
  - `best piecewise-static policy`
  - `final-steady`
  - `weak-online`
- [x] 4.8 将 `recheck_after` 仅作为诊断探针使用，至少比较一个“较短”和一个“较长”的 recheck 设置；调整该值时，其他 drift family 变量保持不变
- [ ] 4.9 对每个 drift challenge regime 输出两类判据：
  - 是否观察到稳定 candidate / policy flip
  - `weak-online` 是否稳定优于最佳非切换方案
- [x] 4.10 只有当两类判据同时成立，且满足 `2.0%` + `2/3 replicate` 的正向证据门槛时，才输出正向 switching value 证据
- [ ] 4.11 若某个 drift family 只在扰动下出现优势，需显式记录其 family 名称与触发边界
- [x] 4.12 若 no-drift 对照下已存在同等级优势，则回退审视 `Phase 2` 静态解释，不得直接记作 drift-driven switching value
- [ ] 4.13 若未观察到稳定 flip，或 `weak-online` 仍无额外收益，则输出 `drift not strong enough to justify switching`
- [x] 4.14 固定 `Phase 3` run manifest 口径：每个 run 必须记录 `drift_family / variant / topology / size / mode / recheck_setting / replicate / result_dir / summary artifact`

## 5. Evidence 与结论边界

- [ ] 5.1 生成一份 headroom map，明确哪些 regime 有 headroom，哪些没有
- [ ] 5.2 生成一份 static envelope summary，明确最佳非切换方案是否已足够解释收益
- [ ] 5.3 生成一份 drift challenge summary，明确是否存在同一静态 key 下的稳定 policy flip
- [x] 5.4 在 change-local evidence 中明确区分三类结论：`headroom established`、`static envelope sufficient`、`switching value established`
- [x] 5.5 若最终没有证明 switching value，显式写出负结论，而不是继续默认把 `weak-online` 视为最终目标
