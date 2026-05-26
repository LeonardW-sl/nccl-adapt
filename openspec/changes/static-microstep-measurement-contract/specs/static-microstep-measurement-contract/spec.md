## ADDED Requirements

### Requirement: 测量约定不得输出收益结论
第一项变更 MUST 只建立测量约定，不得声明固定策略收益是否成立。

#### Scenario: 生成测量就绪总结
- **WHEN** 第一项变更产出退出文档
- **THEN** 退出文档必须只给出 `ready`、`partial` 或 `blocked` 之一作为测量约定状态
- **AND** 退出文档不得包含 `communication-only win`
- **AND** 退出文档不得包含 `workload-confirmed static win`
- **AND** 退出文档不得包含 `no proven room`

#### Scenario: 测量约定尚未冻结
- **WHEN** 小步边界、核心指标或固定策略路径验证仍未完成
- **THEN** 结论必须写成 `measurement-layer unresolved`
- **AND** 下游不得把该状态解释为固定策略收益不存在

### Requirement: 最小验证对象必须固定
第一项变更的第一版验证对象 MUST 固定为单一低歧义场景。

#### Scenario: 运行第一版验证
- **WHEN** 第一版测量约定验证运行
- **THEN** 验证对象必须是 `numa1-4gpu:allreduce:8MiB:r4n1`
- **AND** 固定策略组的第一版请求路径必须是 `ring/simple`
- **AND** 验证不得扩展到多消息尺寸矩阵
- **AND** 验证不得扩展到多候选策略筛选
- **AND** 验证不得扩展到其他拓扑

### Requirement: 默认对照组必须保持路径不可观测
默认对照组 MUST 只作为耗时参照，不得声称默认策略的实际通信路径已被观测。

#### Scenario: 汇总默认对照组结果
- **WHEN** 结果文档汇总默认对照组
- **THEN** 默认对照组的路径字段必须写成 `unobservable`、`null` 或等价安全哨兵
- **AND** 结果文档不得写出默认对照组实际走了某条路径
- **AND** 若需要解释默认策略路径，必须使用只观察组的诊断结果

### Requirement: 固定策略组必须验证请求路径与实际路径
固定策略组 MUST 记录实验请求的通信路径和观察到的实际通信路径，并给出明确关系。

#### Scenario: 汇总固定策略组路径
- **WHEN** 固定策略组请求 `ring/simple`
- **THEN** 结果必须记录请求路径
- **AND** 结果必须记录实际路径
- **AND** 结果必须给出请求路径与实际路径关系
- **AND** 关系值必须是 `matched`、`matched-with-channel-drift`、`fallback-to-default`、`unavailable`、`partial-observation` 或 `unknown` 之一

#### Scenario: 路径观察不完整
- **WHEN** 请求路径与实际路径关系为 `partial-observation` 或 `unknown`
- **THEN** 结果可以保留耗时读数
- **AND** 测量约定状态不得直接写成 `ready`

### Requirement: 尾部锚定小步必须定义明确边界
尾部锚定小步 MUST 固定小步开始、目标通信开始、目标通信结束和小步结束的设备事件含义。

#### Scenario: 记录小步边界
- **WHEN** 测量一个小步
- **THEN** 结果必须能表达小步开始事件
- **AND** 结果必须能表达目标通信开始事件
- **AND** 结果必须能表达目标通信结束事件
- **AND** 结果必须能表达小步结束事件
- **AND** 不得用未绑定小步边界的全局同步替代小步结束事件

#### Scenario: 三条设备流无法稳定表达
- **WHEN** 第一版只能近似表达控制流、计算流和通信流
- **THEN** 结果必须把该限制写入失败或缺口原因
- **AND** 测量约定状态不得直接写成 `ready`

### Requirement: 核心时间指标必须同时产出
第一项变更 MUST 在同一组运行结果中同时产出通信局部指标和小步整体指标。

#### Scenario: 汇总核心时间指标
- **WHEN** 汇总默认对照组或固定策略组
- **THEN** 结果必须承载通信本身耗时 `collective_device_elapsed_ms`
- **AND** 结果必须承载设备侧小步耗时 `microstep_device_elapsed_ms`
- **AND** 结果必须承载主机侧小步耗时 `microstep_time_ms`
- **AND** 结果必须承载尾部剩余耗时 `boundary_tail_ms`
- **AND** 结果必须承载尾部锚定窗口 `boundary_anchor_window_ms`

### Requirement: 只观察组必须保持诊断属性
只观察组 MUST 只用于诊断默认策略和观察开销，不得成为最小完成门槛。

#### Scenario: 只观察组未运行
- **WHEN** 默认对照组和固定策略组都已满足核心测量约定
- **AND** 本次验证没有声明必须解释默认策略路径
- **THEN** 只观察组未运行不得单独阻塞测量约定状态

#### Scenario: 只观察组运行
- **WHEN** 只观察组被纳入验证
- **THEN** 结果可以记录默认策略诊断
- **AND** 结果可以记录观察开销
- **AND** 结果不得把只观察组结果升级成固定策略收益结论

### Requirement: 下游只能消费已就绪的测量约定
第二项变更 MUST 依赖第一项变更的测量约定状态，不能重新定义测量失败时的负结论。

#### Scenario: 测量约定就绪
- **WHEN** 第一项变更的测量约定状态为 `ready`
- **THEN** 第二项变更可以在继承该测量约定后进行固定策略收益判断

#### Scenario: 测量约定未就绪
- **WHEN** 第一项变更的测量约定状态为 `partial` 或 `blocked`
- **THEN** 第二项变更不得输出 `no proven room`
- **AND** 第二项变更必须先写成 `measurement-layer unresolved`
