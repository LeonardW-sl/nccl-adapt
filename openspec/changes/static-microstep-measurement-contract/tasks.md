## 1. Scope And Dependency

- [x] 1.1 固定本 change 的主张类型：measurement contract，而不是 static room claim
- [x] 1.2 在 proposal / design 中明确写出当前负结论歧义：
  - `no proven room`
  - vs `measurement-layer unresolved`
- [x] 1.3 明确 `static-room-establishment` 应作为本 change 的 downstream consumer
- [x] 1.4 记录 current realization 与 semantic arm 的映射：
  - `baseline`
  - `static-replay -> fixed-static`
  - `profiler-only -> diagnostic-profiler`
- [x] 1.5 增加中文名词解释，明确：
  - 默认对照组
  - 固定策略组
  - 只观察组
  - 尾部锚定小步
  - 请求路径与实际路径
  - 测量就绪总结
- [x] 1.6 明确本 change 若失败，只能写成
  `measurement-layer unresolved`，不得写成 `no proven room`

## 2. Arm Semantics

- [x] 2.1 冻结 `baseline` 的语义：
  - profiler off
  - tuner off
  - pure NCCL default strategy
  - path-unobservable latency reference
- [x] 2.2 冻结 `fixed-static` 的语义：
  - profiler on
  - tuner on
  - deterministic requested candidate replay
- [x] 2.3 冻结 `profiler-only` 的诊断语义：
  - profiler on
  - tuner off
  - default-path diagnostics only
- [x] 2.4 固定 `latency_reference_arm=baseline`
- [x] 2.5 定义 requested vs observed relation taxonomy
- [x] 2.6 定义 `profiler-only` 何时进入主读取口径
- [x] 2.7 禁止继续使用含糊字段 `path_relation_to_baseline`

## 3. Anchor Regime

- [x] 3.1 固定最小 proving surface：
  - `numa1-4gpu`
  - `allreduce`
  - `8 MiB`
  - `r4n1`
- [x] 3.2 记录该 anchor regime 的 regime id 命名规则
- [x] 3.3 固定第一版 preferred fixed-static candidate
  - `ring/simple`
- [x] 3.4 明确 anchor regime 的职责是 contract validation，而不是 room proving
- [x] 3.5 明确第一版不扩展到多消息尺寸、多候选策略、其他拓扑或收益判断

## 4. Tail-Anchored Static Microstep Harness

- [x] 4.1 固定 `control_stream` / `compute_stream` / `comm_stream` 三类 stream geometry
- [x] 4.2 固定 boundary events：
  - `microstep_start_event`
  - `collective_start_event`
  - `collective_done_event`
  - `microstep_end_event`
- [x] 4.3 固定 preamble / overlap slab / epilogue 的 launch order
- [x] 4.4 固定 explicit GPU-event join boundary 规则
- [x] 4.5 明确禁止用未绑定 boundary 的全局同步替代 end boundary
- [x] 4.6 定义 communication-local 指标：
  - `collective_device_elapsed_ms`
  - `collective_algbw_gbps`
  - `collective_busbw_gbps`
- [x] 4.7 定义 microstep-level 指标：
  - `microstep_time_ms`
  - `microstep_device_elapsed_ms`
  - `boundary_tail_ms`
  - `boundary_anchor_window_ms`
- [x] 4.8 定义哪些变量允许变化、哪些变量必须冻结
- [x] 4.9 明确第一版是否能真实表达三条设备流；若只能近似表达，结果不得标记为 `ready`
- [x] 4.10 固定指标主次：
  - 通信本身耗时是通信局部主指标
  - 设备侧小步耗时是小步整体主指标
  - 主机侧小步耗时是辅助指标
  - 尾部剩余耗时只作边界解释

## 5. Result Schema And Manifest

- [x] 5.1 定义 `anchor-validation` batch manifest 顶层字段
- [x] 5.2 定义 regime identity 字段
- [x] 5.3 定义 boundary contract 字段
- [x] 5.4 定义 `fixed-static` 的 requested-path 字段
- [x] 5.5 定义 `fixed-static` 的 observed-path 字段
- [x] 5.6 定义每个 arm 的 communication-local measurement 字段
- [x] 5.7 定义每个 arm 的 microstep-level measurement 字段
- [x] 5.8 定义 baseline path-unobservable 的显式 sentinel 表达
- [x] 5.9 定义 readiness summary 字段：
  - `communication_signal_ready`
  - `microstep_signal_ready`
  - `baseline_reference_ready`
  - `fixed_static_comparison_ready`
  - `requested_vs_observed_ready`
  - `default_path_diagnostic_ready`
  - `measurement_contract_status`
- [x] 5.10 定义 failure / blockage reason 字段
- [x] 5.11 提供一份 JSON-like skeleton，作为 downstream consumer 的读取 contract
- [x] 5.12 明确默认对照组的路径字段必须写成 `unobservable`、`null` 或等价安全哨兵
- [x] 5.13 明确固定策略组的请求路径与实际路径判定：
  - `matched`
  - `matched-with-channel-drift`
  - `fallback-to-default`
  - `unavailable`
  - `partial-observation`
  - `unknown`
- [x] 5.14 明确 `partial-observation` 或 `unknown` 不得直接产出 `measurement_contract_status=ready`

## 6. Minimal Validation Surface

- [x] 6.1 设计一组最小 arm matrix：
  - `baseline`
  - `fixed-static`
- [x] 6.1.1 记录 `profiler-only` 作为 optional diagnostic arm
- [x] 6.2 明确 `baseline` 必须能输出 communication-local 与 microstep-level timing
- [x] 6.3 明确 `fixed-static` 必须能输出 requested vs observed path
- [x] 6.4 明确 `fixed-static` 的性能值必须能与 `baseline` 做同口径比较
- [x] 6.5 若运行 `profiler-only`，将 observation tax 作为独立诊断读数
- [x] 6.6 明确该 validation 只验证 contract completeness，不验证 room

## 7. Downstream Handoff

- [x] 7.1 写清 `static-room-establishment` 将继承哪些 contract
- [x] 7.2 写清 `static-room-establishment` 不应再重新定义哪些 measurement semantics
- [x] 7.3 写清 downstream change 何时才允许输出 room judgment
- [x] 7.4 写清 measurement contract 未冻结时的负结论写法：
  - `measurement-layer unresolved`
- [x] 7.5 写清本 change 的 exit artifact 应是 measurement readiness summary，
  而不是 room map
- [x] 7.6 明确本 change 的 exit artifact 不得出现：
  - `communication-only win`
  - `workload-confirmed static win`
  - `no proven room`

## 8. Exit Artifact Template

- [x] 8.1 提供中文“测量就绪总结”模板
- [x] 8.2 模板只允许三种总体状态：
  - `ready`
  - `partial`
  - `blocked`
- [x] 8.3 模板必须列出核心通过条件、缺口原因和下游是否可消费
