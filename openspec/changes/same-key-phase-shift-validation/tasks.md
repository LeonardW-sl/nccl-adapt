## 1. Entry Selection

- [ ] 1.1 从 `static-room-establishment` 中筛选 `workload-confirmed static win` regime
- [ ] 1.2 为每个晋级 regime 固定 same-key 定义与对照地板
- [ ] 1.3 明确哪些 regime 不满足进入条件，并记录原因

## 2. Phase-Shift Harness

- [ ] 2.1 固定 `compute-overlap` family 的最小三臂模板
- [ ] 2.2 固定 `comm-interference` family 的最小三臂模板
- [ ] 2.3 明确每个 family 中唯一允许变化的主变量
- [ ] 2.4 将 phase interpretation signal 纳入统一记录 schema

## 3. Winner Validation

- [ ] 3.1 对每个 regime 比较 `control` 与 drift variant 的 best non-switching winner
- [ ] 3.2 判断是否存在 stable winner flip
- [ ] 3.3 输出 `no stable winner change` 或 `same-key phase-shift room established`

## 4. Exit Summary

- [ ] 4.1 生成 drift family 级别摘要
- [ ] 4.2 生成 stable flip 摘要
- [ ] 4.3 生成可晋级到 `weak-online-payoff-validation` 的 regime 列表
- [ ] 4.4 若未观察到 stable flip，显式写出 switching room 尚未证明
