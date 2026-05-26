## Why

当前分支里被混在一起的，其实是两种不同类型的主张：

1. `measurement capability` 是否已经建立并且口径稳定
2. 在该 measurement layer 之上，`static room` 是否被证明存在

这不是“代码量多一点”的问题，而是“结论类型变了”的问题。

当前仓库里的现实说明 measurement layer 还没有被单独冻结：

- `baseline` 不加载 profiler / tuner，因此没有 selected-path observability
- 当前 `profiler-only` 仍然走 NCCL 默认策略，但已经能记录
  `candidate / selectedAlgo / selectedProto / nChannels`
- 当前 harness 仍是 `float32 all_reduce + synchronize` smoke，只输出
  iteration latency
- 当前结果还没有：
  - `microstep_time_ms`
  - `microstep_device_elapsed_ms`
  - `boundary_tail_ms`
  - 明确的 GPU-event join boundary
- 现有 plugin 在 profiler 打开时已经能记录 requested / observed path，
  所以“默认路径可观测”不是从零开始

如果继续把 measurement contract 和 static room claim 写在同一个 change 里，
那么负结论会长期不清楚：

```text
到底是 no proven room，
还是 measurement layer 还没站稳？
```

因此需要一个更前置、更窄的 change，先把 measurement layer 单独立住。

## Goal

本 change 只建立：

- `tail-anchored static microstep harness`
- `baseline / fixed-static` 两类核心 arm 语义
- `profiler-only` 诊断 arm 语义（可选）
- communication-local 与 microstep-level 的统一 measurement contract
- 结果 schema / matrix-manifest contract
- `static-room-establishment` 的下游依赖边界

本 change 的完成不等于 static room 已成立。

为降低阅读歧义，本 change 后续统一采用中文语义描述：

- `measurement contract` 解释为“测量约定”
- `baseline` 解释为“默认对照组”
- `fixed-static` 解释为“固定策略组”
- `profiler-only` 解释为“只观察组”
- `tail-anchored static microstep` 解释为“尾部锚定小步”
- `requested vs observed path` 解释为“请求路径与实际路径”
- `readiness summary` 解释为“测量就绪总结”

代码字段名、脚本模式名和 JSON 字段名仍保留原拼写，但文档解释必须先给中文含义。

当前 realization 与 semantic arm 的映射固定为：

| 当前脚本模式 | 本 change 的 semantic arm | 中文含义 |
| --- | --- | --- |
| `baseline` | `baseline` | 默认对照组 |
| `static-replay` | `fixed-static` | 固定策略组 |
| `profiler-only` | `diagnostic-profiler` | 只观察组 |

本 change 的最小核心判据只要求回答三件事：

- `baseline` 的性能值
- non-default `fixed-static` arm 的性能值
- non-default arm 的 requested candidate 是否真的跑到了对应 observed path

`baseline` 到底走了什么 path，不再是本 change 的必答题。

补充边界：

- 本 change 只验证“一把尺子能不能用”，不判断“有没有收益”。
- 本 change 若失败，只能输出 `measurement-layer unresolved`，不能输出
  `no proven room`。
- 本 change 的完成产物应是“测量就绪总结”，不是“收益图”或“固定收益结论”。

## Anchor Boundaries

本 change 的最小 proving surface 固定为一个极窄 anchor regime：

- topology group: `numa1-4gpu`
- collective: `allreduce`
- message size: `8 MiB`
- world shape: `r4n1`
- current preferred fixed-static realization: `ring/simple`

中文解释：

- 只看一号处理器域上的四张 GPU。
- 只看单机四进程。
- 只看 8 MiB 的 allreduce。
- 只用 `ring/simple` 作为第一条非默认固定策略，用来验证“请求路径与实际路径”能否表达清楚。

这里的 contract 定义可以写得比这个 regime 更一般，
但第一版 proving obligation 只绑定到这个 anchor regime。

本 change 明确排除：

- static room proving
- `communication-only win` 结论
- `workload-confirmed static win` 结论
- screening / confirmation 的 room map
- same-key phase shift
- weak-online payoff
- 多 topology / 多 size 的宽矩阵扩展

## What Changes

- 新增一个 measurement-only change：
  `static-microstep-measurement-contract`
- 将 arm 分为：
  - 核心 arm
    - `baseline`
    - `fixed-static`
  - 可选诊断 arm
    - `profiler-only`
- 明确 `profiler-only` 只在需要解释默认策略大概在干什么时才进入主读取口径
- 固定 `tail-anchored static microstep` 的 stream geometry、boundary events、
  launch order 与 outer-loop metrics
- 定义 unified schema：
  - communication-local signal
  - microstep-level signal
  - non-default arm 的 requested vs observed path
  - optional default-path diagnostics
- 明确 `static-room-establishment` 应作为该 contract 的消费者，
  而不是继续同时承担 measurement contract 与 room judgment

## Completion Conditions

本 change 完成时，至少要产出：

1. 一份 arm semantics contract
   - `baseline`
   - `fixed-static`
   - `profiler-only`（diagnostic-only）
2. 一份 harness contract
   - 明确 GPU-event join boundary
   - 明确 `microstep_time_ms`
   - 明确 `microstep_device_elapsed_ms`
   - 明确 `boundary_tail_ms`
3. 一份 schema / manifest contract
   - 明确 core required fields 与 optional diagnostic fields
   - 明确 communication-local 与 microstep-level 字段
4. 一份 anchor regime proving statement
   - `numa1-4gpu`
   - `allreduce`
   - `8 MiB`
   - `r4n1`
5. 一份 downstream dependency statement
   - `static-room-establishment` 只能在该 contract 之上做 room judgment

补充完成条件：

- 本 change 的 exit artifact 不得输出
  `communication-only win`
- 本 change 的 exit artifact 不得输出
  `workload-confirmed static win`
- 如果 anchor validation 没有完成，结论必须写成 measurement-layer unresolved，
  而不是 `no proven room`

## Non-Goals

- 不在本 change 中证明 static room 已存在
- 不在本 change 中输出最终实验结论
- 不在本 change 中推广到 same-key phase shift
- 不在本 change 中比较 weak-online payoff
- 不在本 change 中把多 size / 多 topology room map 做完
- 不在本 change 中重写应用功能代码

## Impact

- 把负结论从 “room 不存在” 与 “measurement 还未冻结” 之间解缠
- 把 baseline path 从主判据中降级，避免 measurement contract 一开始就被不必要的问题拖复杂
- 让当前已有 profiler observability 作为诊断能力被继承，而不是强行变成核心 proving obligation
- 让 `static-room-establishment` 回到它真正该回答的问题：
  在既定 measurement contract 之上，room 是否被证明存在
