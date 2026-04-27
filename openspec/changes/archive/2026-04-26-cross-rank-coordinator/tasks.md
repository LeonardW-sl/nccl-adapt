## 1. Coordinator Model

- [x] 1.1 定义 communicator-domain 共享 coordinator state 的最小数据模型，区分 published policy、activation boundary 和 per-rank summary slots，并明确 publication / activation domain 先绑定到 `communicator + exact key`
- [x] 1.2 固定第一版 representative 为 communicator rank0，并明确 communicator init/finalize 与 shared state 生命周期的绑定关系
- [x] 1.3 为 shared committed policy 定义最小字段：`epoch`、candidate、`recheck_after`、`published_call_index`、`effective_call_index`、`valid`
- [x] 1.4 选择第一版 process-shared host-state 机制，并实现 POSIX shared memory 或等价单机共享内存承载的 coordinator header / slots
- [x] 1.5 为 shared coordinator state 加入 communicator generation / validity 与 reader snapshot 完整性机制，采用 double-buffer published-record flip 避免 stale state 或 torn read 误激活
- [x] 1.6 固定第一版 policy domain identity 字段集合：`commId + collType + size bucket + nRanks + nNodes`，并把其余字段分层到 observation / candidate state

## 2. Summary Submission And Publication

- [x] 2.1 将 rank-local window completion 路径改为提交摘要到 shared coordinator state，而不是本地直接提交 committed policy
- [x] 2.2 实现 representative 对 per-rank summary slots 的聚合与裁决，只允许单 writer 发布 communicator-domain shared committed policy
- [x] 2.3 实现 incomplete coverage、stale epoch/window、coordinator unavailable 时的 hold/default 行为
- [x] 2.4 保证 coordinator metadata 只共享 host-side state，不引入 CUDA IPC device/event sharing 作为第一版前提

## 3. Hot Path Activation

- [x] 3.1 让 tuner 热路径读取 communicator-domain 的 shared committed policy，而不是读取本地 committed policy
- [x] 3.2 实现 `published` 与 `effective` 分离，确保新 policy 只在统一 `effective_call_index` 之后生效，并将 `effective_call_index` 定义为显式、可配置且默认值为 `2` 的 activation lag 边界
- [x] 3.3 保持热路径非阻塞：共享 policy 读取失败、未激活或 candidate 不可用时立即 hold/fallback
- [x] 3.4 确保 `getCollInfo` 不通过 UDS 或其他 request/response transport 向 representative 发起 per-call coordinator 查询
- [x] 3.5 明确 `call_index` 只作为 domain-scoped local eligibility clock，不作为跨 rank 瞬时同步证明
- [x] 3.6 确保热路径仅用第一版稳定 identity 字段重建 policy domain，不依赖 `datatype`、`root/op` 等 observation-only 元数据

## 4. Validation

- [x] 4.1 恢复 `final-steady` 的 2-rank torch smoke，并验证 warmup 后切换不再导致 `SIGSEGV`
- [x] 4.2 恢复 `final-steady` 和 `weak-online` 的 8-rank torch smoke，并验证 communicator 内 policy 激活保持一致
- [x] 4.3 重新量化 `baseline`、`profiler-only`、`final-steady`、`weak-online` 的 overhead，并更新 README/验证记录
- [x] 4.4 评估当前 power-of-two size bucket 是否对 activation domain 足够 honest；若 lower/upper sub-range 在至少两个 recheck 周期里持续偏向不同 committed candidates，则提出双子桶 refinement
