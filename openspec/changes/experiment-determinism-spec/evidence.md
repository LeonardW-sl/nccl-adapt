# Evidence Index

本 change 现在只索引本次按新协议重新产出的实验目录；不再引用旧的 `2026-04-26` 历史实验批次。

## 新协议实验目录

- 机制正确性：
  - `nccl/plugins/adaptive/experiments/correctness/2026-04-26-protocol-correctness`
- 机制成本：
  - `nccl/plugins/adaptive/experiments/mode-comparison/2026-04-26-protocol-mode-comparison`
- 策略质量：
  - `nccl/plugins/adaptive/experiments/policy-quality/2026-04-26-protocol-policy-quality`
- 状态颗粒度：
  - `nccl/plugins/adaptive/experiments/state-granularity/2026-04-26-protocol-state-granularity`

## 结果文件约定

- 每个实验根目录都包含 `manifest.json`。
- `correctness` / `mode-comparison` / `policy-quality` 包含 `comparison-summary.json`。
- `state-granularity` 包含 `candidate-trajectories.json`。
- 每个具体 run 目录包含 `env.txt`、`metadata.json`、`stdout.log`、`summary.json`、`trajectory.json`。

## 本轮摘要结论

- 机制正确性：
  - 本轮 `correctness` 批次中，`final-steady` 与 `weak-online` 都在 `call=6` 激活了同一个 `ring/simple` policy。
  - `trajectory.json` 已记录 publish / activate 事件，可直接复核 communicator-domain 一致激活。
- 机制成本：
  - 本轮 `mode-comparison` 的 3 个 replicate 已按 `rotate` 顺序轮换完成。
  - 聚合结果中 `weak-online` 与 `final-steady` 明显高于 `baseline` / `profiler-only`，但 `baseline` 与 `profiler-only` 的相对顺序仍不稳定，说明当前单机结果仍存在较大 run-to-run 波动。
- 策略质量：
  - 使用本轮 `correctness` 中实际 publish 的 `ring/simple` 作为 `STATIC_REPLAY_CANDIDATE`。
  - `policy-quality` 聚合结果中，`static-replay` 的聚合均值低于 `baseline`，说明这轮 replay 对当前 workload 有正向收益信号。
- 状态颗粒度：
  - 本轮在同一 `4-8MiB` bucket 内对 `5/6/7 MiB` 做了 3 个 replicate 的 size sweep。
  - 新的 `candidate-trajectories.json` 显示三个 size 在本轮都只发布 `ring/simple`，没有复现此前历史实验中的稳定 candidate 分叉。
  - 因此，本轮新协议数据**没有**复现“4-8 MiB bucket 不 honest”的旧结论；这一点应与历史批次明确区分。

## 已知限制

- 所有结果仍是单机 `torch distributed` 路径；多机不在本次范围内。
- 本轮 `mode-comparison` 和 `policy-quality` 都显示出明显的 replicate 间波动，现阶段更适合解读为“趋势信号”而不是最终定量结论。
- `state-granularity` 的新结果与旧历史批次不一致，说明 bucket 分层结论当前对运行条件较敏感，后续应继续扩展 replicate 数或收紧环境控制。
