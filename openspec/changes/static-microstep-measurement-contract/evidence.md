# Static Microstep Measurement Contract Evidence

## 中文说明

本文档是“测量就绪总结”的填写模板，并记录本次 anchor microstep 结果。

它只回答：

```text
这套测量约定是否已经能稳定使用？
```

它不回答：

```text
固定策略是否有收益？
```

因此本文档不得写入：

- `communication-only win`
- `workload-confirmed static win`
- `no proven room`

如果测量约定未冻结，结论必须写成：

```text
measurement-layer unresolved
```

## 总体结论

- 测量约定状态：
  - `ready`
- 中文结论：
  - 当前最小场景的测量约定已经就绪，可作为下游收益判断的测量输入。
- 是否允许下游 `static-room-establishment` 消费：
  - 允许，但仅限继承本测量约定后再做 room judgment。
- 未就绪时的结论写法：
  - `measurement-layer unresolved`
- 本次结果目录：
  - `nccl/plugins/adaptive/experiments/static-microstep-measurement-contract/2026-05-17-anchor-microstep-v1`
- 本次运行时间：
  - `2026-05-17`

允许的测量约定状态：

| 字段值 | 中文结论 | 含义 |
| --- | --- | --- |
| `ready` | 测量就绪 | 核心测量字段、默认对照组、固定策略组、路径验证都可用 |
| `partial` | 部分就绪 | 核心耗时可用，但诊断或路径验证仍有缺口 |
| `blocked` | 测量阻塞 | 核心测量字段或核心对照无法可信产出 |

## 最小验证对象

- 拓扑：
  - `numa1-4gpu`
- 通信类型：
  - `allreduce`
- 消息大小：
  - `8 MiB`
- 单机进程形状：
  - `r4n1`
- 第一版固定策略：
  - `ring/simple`
- 验证对象编号：
  - `numa1-4gpu:allreduce:8MiB:r4n1`

## 三组实验

| 中文组别 | 脚本模式 | 是否核心 | 结果 |
| --- | --- | --- | --- |
| 默认对照组 | `baseline` | 是 | 完成 3 replicates；小步主机耗时均值 `0.540 ms` |
| 固定策略组 | `static-replay` | 是 | 完成 3 replicates；小步主机耗时均值 `0.561 ms` |
| 只观察组 | `profiler-only` | 否 | 完成 3 replicates；小步主机耗时均值 `0.566 ms` |

### 默认对照组

- 是否产出通信本身耗时：
  - 是。通信设备耗时均值 `0.460 ms`。
- 是否产出设备侧小步耗时：
  - 是。设备侧小步耗时均值 `0.536 ms`。
- 是否产出主机侧小步耗时：
  - 是。主机侧小步耗时均值 `0.540 ms`。
- 是否产出尾部剩余耗时：
  - 是。尾部剩余耗时均值 `0.008 ms`。
- 路径字段：
  - `unobservable`
- 备注：
  - 默认对照组不得声称默认策略实际路径。
  - 本次 baseline 保持 profiler off / tuner off，符合路径不可观测约束。
  - 尾部锚定窗口均值 `0.468 ms`。

### 固定策略组

- 请求路径：
  - `ring/simple`
- 实际路径：
  - dominant observed path 为 `RING/SIMPLE/4ch`。
- 请求路径与实际路径关系：
  - `matched-with-channel-drift`
- 是否产出通信本身耗时：
  - 是。通信设备耗时均值 `0.485 ms`。
- 是否产出设备侧小步耗时：
  - 是。设备侧小步耗时均值 `0.560 ms`。
- 是否产出主机侧小步耗时：
  - 是。主机侧小步耗时均值 `0.561 ms`。
- 是否产出尾部剩余耗时：
  - 是。尾部剩余耗时均值 `0.008 ms`。
- 是否可与默认对照组同口径比较：
  - 是。同一 tail-anchored static microstep harness 下可比较。
- 观察摘要：
  - `candidate_set=["ring/simple"]`
  - `selectedAlgo_set=["RING"]`
  - `selectedProto_set=["SIMPLE"]`
  - `nChannels_set=[1,4]`
  - 主 8 MiB allreduce 记录以 `4ch` 为 dominant path；`1ch` 来自小控制 collective。
  - 尾部锚定窗口均值 `0.493 ms`。

请求路径与实际路径关系只允许：

| 字段值 | 中文解释 |
| --- | --- |
| `matched` | 请求路径和实际路径一致 |
| `matched-with-channel-drift` | 算法和协议一致，但通道数不同 |
| `fallback-to-default` | 没有走到请求路径，回到默认行为 |
| `unavailable` | 请求路径在当前场景不可用 |
| `partial-observation` | 观察记录不完整，不能确认 |
| `unknown` | 信息不足，无法判断 |

### 只观察组

- 是否运行：
  - 是。
- 默认策略诊断：
  - `candidate_set=["default"]`，`selectedAlgo_set=["RING"]`，`selectedProto_set=["LL","SIMPLE"]`。
- 观察开销：
  - 小步主机耗时均值：只观察组 `0.566 ms`，默认对照组 `0.540 ms`。
- 是否影响核心结论：
  - 否。它只作为诊断读数，不升级成核心通过条件。

只观察组是诊断组，不是最小完成门槛。

## 小步边界

- 是否真实表达三条设备流：
  - 是。使用控制流、计算流、通信流三类设备流。
- 是否固定小步开始事件：
  - 是。`microstep_start_event`。
- 是否固定目标通信开始事件：
  - 是。`collective_start_event`。
- 是否固定目标通信结束事件：
  - 是。`collective_done_event`。
- 是否固定小步结束事件：
  - 是。`microstep_end_event`。
- 是否避免使用未绑定边界的全局同步作为结束边界：
  - 是。测量结束等待绑定到 `microstep_end_event`。

## 指标就绪

| 中文指标 | 字段名 | 状态 | 备注 |
| --- | --- | --- | --- |
| 通信本身耗时 | `collective_device_elapsed_ms` | `ready` | baseline `0.460 ms`；fixed-static `0.485 ms` |
| 设备侧小步耗时 | `microstep_device_elapsed_ms` | `ready` | baseline `0.536 ms`；fixed-static `0.560 ms` |
| 主机侧小步耗时 | `microstep_time_ms` | `ready` | baseline `0.540 ms`；fixed-static `0.561 ms` |
| 尾部剩余耗时 | `boundary_tail_ms` | `ready` | baseline `0.008 ms`；fixed-static `0.008 ms` |
| 尾部锚定窗口 | `boundary_anchor_window_ms` | `ready` | baseline `0.468 ms`；fixed-static `0.493 ms` |

## 就绪检查

- 通信局部信号是否就绪：
  - 是。
- 小步整体信号是否就绪：
  - 是。
- 默认对照组是否就绪：
  - 是。
- 固定策略组是否就绪：
  - 是。
- 请求路径与实际路径验证是否就绪：
  - 是。`ring/simple` 路径可观测为 `RING/SIMPLE`，主 8 MiB collective dominant 为 `4ch`。
- 默认路径诊断是否就绪：
  - 是，作为 optional diagnostic。
- 失败或缺口原因：
  - 无核心阻塞项。
  - 注意：本总结只说明测量约定就绪，不说明固定策略收益成立或不成立。

## 下游交接

- `static-room-establishment` 是否可以开始收益判断：
  - 可以，但必须继承本 change 的测量约定。
- 下游必须继承的内容：
  - 默认对照组语义
  - 固定策略组语义
  - 只观察组诊断语义
  - 小步边界
  - 指标字段
  - 请求路径与实际路径判定
- 下游不得重新定义的内容：
  - 默认对照组是否可观测
  - 小步结束边界
  - 测量失败时的负结论写法
