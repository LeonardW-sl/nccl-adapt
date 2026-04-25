#include "nccl_profiler_compat.h"
#include "nccl_tuner_compat.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cinttypes>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#define ADAPTIVE_PLUGIN_NAME "Adaptive"
#define ADAPTIVE_MAX_TEXT 128
#define __hidden __attribute__((visibility("hidden")))

#define ADAPTIVE_LOG(LOGFN, LEVEL, FLAGS, FMT, ...) \
  do { \
    if ((LOGFN) != nullptr) { \
      (LOGFN)((LEVEL), (FLAGS), __FILE__, __LINE__, (FMT), ##__VA_ARGS__); \
    } \
  } while (0)

namespace {

enum class AdaptiveMode {
  kAdaptive,
  kStatic,
  kDisabled,
};

struct CandidateSpec {
  const char* name;
  int algorithm;
  int protocol;
  int channels;
  bool overrideChannels;
};

struct SizeBin {
  uint64_t lower;
  uint64_t upper;
};

struct PolicyKey {
  int collType;
  uint64_t sizeBinLower;
  uint64_t sizeBinUpper;
  int nRanks;
  int nNodes;

  bool operator==(const PolicyKey& other) const {
    return collType == other.collType &&
        sizeBinLower == other.sizeBinLower &&
        sizeBinUpper == other.sizeBinUpper &&
        nRanks == other.nRanks &&
        nNodes == other.nNodes;
  }
};

struct PolicyKeyHash {
  size_t operator()(const PolicyKey& key) const {
    size_t seed = static_cast<size_t>(key.collType);
    seed ^= static_cast<size_t>(key.sizeBinLower + 0x9e3779b97f4a7c15ULL + (seed << 6) + (seed >> 2));
    seed ^= static_cast<size_t>(key.sizeBinUpper + 0x9e3779b97f4a7c15ULL + (seed << 6) + (seed >> 2));
    seed ^= static_cast<size_t>(key.nRanks + 0x9e3779b9 + (seed << 6) + (seed >> 2));
    seed ^= static_cast<size_t>(key.nNodes + 0x9e3779b9 + (seed << 6) + (seed >> 2));
    return seed;
  }
};

struct CandidateStats {
  uint64_t samples = 0;
  double totalLatencyUs = 0.0;
  double totalAlgBwGbps = 0.0;
  double totalBusBwGbps = 0.0;
};

struct CompletedRecord {
  std::string mode;
  PolicyKey key;
  uint64_t sequence = 0;
  uint64_t phase = 0;
  std::string candidate;
  std::string selectedAlgo;
  std::string selectedProto;
  int selectedChannels = 0;
  double latencyUs = 0.0;
  double algbwGbps = 0.0;
  double busbwGbps = 0.0;
};

struct PolicyEntry {
  uint64_t tunerPhase = 0;
  uint64_t profilerPhase = 0;
  std::unordered_map<std::string, CandidateStats> stats;
  std::deque<CompletedRecord> records;
  uint64_t droppedRecords = 0;
};

struct TunerContext {
  uint64_t commId = 0;
  int nRanks = 0;
  int nNodes = 0;
  ncclDebugLogger_t logfn = nullptr;
};

struct ProfilerContext {
  uint64_t commId = 0;
  int rank = 0;
  int nRanks = 0;
  int nNodes = 0;
  ncclDebugLogger_t logfn = nullptr;
};

struct CollHandle {
  uint64_t type = ncclProfileColl;
  std::atomic<int> refs{1};
  std::mutex mutex;
  ProfilerContext* context = nullptr;
  PolicyKey key{};
  uint64_t sequence = 0;
  uint64_t phase = 0;
  std::string phaseCandidate;
  std::string func;
  std::string datatype;
  std::string algo;
  std::string proto;
  size_t nBytes = 0;
  int nChannels = 0;
  uint64_t startUsec = 0;
  uint64_t firstKernelStartUsec = 0;
  uint64_t lastKernelStopUsec = 0;
  uint64_t firstKernelTimer = 0;
  uint64_t lastKernelTimer = 0;
  int startedKernelChannels = 0;
  int stoppedKernelChannels = 0;
  bool hostStopped = false;
  bool completionRecorded = false;
};

struct KernelHandle {
  uint64_t type = ncclProfileKernelCh;
  CollHandle* coll = nullptr;
  uint8_t channelId = 0;
  uint64_t startTimer = 0;
  uint64_t stopTimer = 0;
  uint64_t startUsec = 0;
};

constexpr CandidateSpec kDefaultCandidate{"default", NCCL_ALGO_UNDEF, NCCL_PROTO_UNDEF, 0, false};
constexpr CandidateSpec kRingSimpleCandidate{"ring/simple", NCCL_ALGO_RING, NCCL_PROTO_SIMPLE, 0, false};
constexpr CandidateSpec kTreeSimpleCandidate{"tree/simple", NCCL_ALGO_TREE, NCCL_PROTO_SIMPLE, 0, false};
constexpr CandidateSpec kRingLl128Candidate{"ring/ll128", NCCL_ALGO_RING, NCCL_PROTO_LL128, 0, false};

uint64_t nowUsec() {
  using namespace std::chrono;
  return duration_cast<microseconds>(steady_clock::now().time_since_epoch()).count();
}

size_t dtypeSize(const char* datatype) {
  if (datatype == nullptr) return 0;
  if (strcmp(datatype, "ncclInt8") == 0 || strcmp(datatype, "ncclChar") == 0 || strcmp(datatype, "ncclUint8") == 0) return 1;
  if (strcmp(datatype, "ncclInt32") == 0 || strcmp(datatype, "ncclInt") == 0 || strcmp(datatype, "ncclUint32") == 0 || strcmp(datatype, "ncclFloat32") == 0 || strcmp(datatype, "ncclFloat") == 0) return 4;
  if (strcmp(datatype, "ncclInt64") == 0 || strcmp(datatype, "ncclUint64") == 0 || strcmp(datatype, "ncclFloat64") == 0 || strcmp(datatype, "ncclDouble") == 0) return 8;
  if (strcmp(datatype, "ncclFloat16") == 0 || strcmp(datatype, "ncclHalf") == 0 || strcmp(datatype, "ncclBfloat16") == 0) return 2;
  if (strcmp(datatype, "ncclFloat8e4m3") == 0 || strcmp(datatype, "ncclFloat8e5m2") == 0) return 1;
  return 0;
}

const char* collTypeName(int collType) {
  switch (collType) {
    case ncclFuncBroadcast: return "broadcast";
    case ncclFuncReduce: return "reduce";
    case ncclFuncAllGather: return "allgather";
    case ncclFuncReduceScatter: return "reducescatter";
    case ncclFuncAllReduce: return "allreduce";
    default: return "unknown";
  }
}

SizeBin sizeBinForBytes(size_t nBytes) {
  uint64_t lower = 1;
  uint64_t upper = 1;
  while (upper < nBytes && upper < (1ULL << 62)) {
    lower = upper;
    upper <<= 1;
  }
  if (nBytes <= 1) {
    lower = 1;
    upper = 1;
  }
  return SizeBin{lower, upper};
}

void keyToText(const PolicyKey& key, char* buffer, size_t bufferSize) {
  snprintf(buffer, bufferSize, "%s:%" PRIu64 "-%" PRIu64 ":r%d:n%d",
      collTypeName(key.collType), key.sizeBinLower, key.sizeBinUpper, key.nRanks, key.nNodes);
}

double safeBandwidthGbps(size_t bytes, double latencyUs) {
  if (latencyUs <= 0.0) return 0.0;
  return (static_cast<double>(bytes) / 1.0e9) / (latencyUs / 1.0e6);
}

double busBandwidthGbps(int collType, int nRanks, double algbwGbps) {
  if (collType == ncclFuncAllReduce && nRanks > 1) {
    return algbwGbps * (2.0 * (nRanks - 1) / static_cast<double>(nRanks));
  }
  if ((collType == ncclFuncReduceScatter || collType == ncclFuncAllGather) && nRanks > 1) {
    return algbwGbps * ((nRanks - 1) / static_cast<double>(nRanks));
  }
  return algbwGbps;
}

AdaptiveMode parseMode(const char* value) {
  if (value == nullptr || strcmp(value, "adaptive") == 0) return AdaptiveMode::kAdaptive;
  if (strcmp(value, "static") == 0) return AdaptiveMode::kStatic;
  if (strcmp(value, "disabled") == 0 || strcmp(value, "off") == 0) return AdaptiveMode::kDisabled;
  return AdaptiveMode::kAdaptive;
}

const char* modeName(AdaptiveMode mode) {
  switch (mode) {
    case AdaptiveMode::kStatic: return "static";
    case AdaptiveMode::kDisabled: return "disabled";
    case AdaptiveMode::kAdaptive: return "adaptive";
  }
  return "adaptive";
}

CandidateSpec parseStaticCandidate(const char* value) {
  if (value == nullptr || strcmp(value, "default") == 0) return kDefaultCandidate;
  if (strcmp(value, "ring/simple") == 0) return kRingSimpleCandidate;
  if (strcmp(value, "tree/simple") == 0) return kTreeSimpleCandidate;
  if (strcmp(value, "ring/ll128") == 0) return kRingLl128Candidate;
  return kDefaultCandidate;
}

std::vector<CandidateSpec> candidatesForCollType(int collType) {
  if (collType == ncclFuncAllReduce) {
    return {kDefaultCandidate, kRingSimpleCandidate, kTreeSimpleCandidate, kRingLl128Candidate};
  }
  return {kDefaultCandidate};
}

class PolicyStore {
 public:
  static PolicyStore& instance() {
    static PolicyStore store;
    return store;
  }

  CandidateSpec planSelection(const PolicyKey& key, bool tunerPath, uint64_t* phaseOut) {
    std::lock_guard<std::mutex> lock(mutex_);
    PolicyEntry& entry = entries_[key];
    uint64_t& phaseCounter = tunerPath ? entry.tunerPhase : entry.profilerPhase;
    const uint64_t phase = phaseCounter++;
    if (phaseOut != nullptr) *phaseOut = phase;
    return candidateForPhase(key.collType, phase);
  }

  bool tryPlanSelection(const PolicyKey& key, CandidateSpec* candidateOut, uint64_t* phaseOut) {
    if (!mutex_.try_lock()) return false;
    PolicyEntry& entry = entries_[key];
    const uint64_t phase = entry.tunerPhase++;
    CandidateSpec candidate = candidateForPhase(key.collType, phase);
    mutex_.unlock();
    if (candidateOut != nullptr) *candidateOut = candidate;
    if (phaseOut != nullptr) *phaseOut = phase;
    return true;
  }

  void recordCompletion(const CompletedRecord& record) {
    std::lock_guard<std::mutex> lock(mutex_);
    PolicyEntry& entry = entries_[record.key];
    CandidateStats& stats = entry.stats[record.candidate];
    stats.samples += 1;
    stats.totalLatencyUs += record.latencyUs;
    stats.totalAlgBwGbps += record.algbwGbps;
    stats.totalBusBwGbps += record.busbwGbps;
    if (entry.records.size() >= maxRecords_) {
      entry.records.pop_front();
      entry.droppedRecords += 1;
    }
    entry.records.push_back(record);
  }

  void dumpRecords(ncclDebugLogger_t logfn) {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto& it : entries_) {
      PolicyEntry& entry = it.second;
      char keyText[ADAPTIVE_MAX_TEXT];
      keyToText(it.first, keyText, sizeof(keyText));
      if (entry.droppedRecords != 0) {
        ADAPTIVE_LOG(logfn, NCCL_LOG_INFO, NCCL_TUNING,
            "ADAPTIVE/records key=%s dropped=%" PRIu64, keyText, entry.droppedRecords);
      }
      for (const CompletedRecord& record : entry.records) {
        ADAPTIVE_LOG(logfn, NCCL_LOG_INFO, NCCL_TUNING,
            "ADAPTIVE/record mode=%s key=%s seq=%" PRIu64 " phase=%" PRIu64 " candidate=%s selected=%s/%s channels=%d latency_us=%.3f algbw_gbps=%.3f busbw_gbps=%.3f",
            record.mode.c_str(), keyText, record.sequence, record.phase, record.candidate.c_str(),
            record.selectedAlgo.c_str(), record.selectedProto.c_str(), record.selectedChannels,
            record.latencyUs, record.algbwGbps, record.busbwGbps);
      }
      entry.records.clear();
      entry.droppedRecords = 0;
    }
  }

  AdaptiveMode mode() const { return mode_; }
  const CandidateSpec& staticCandidate() const { return staticCandidate_; }
  bool logDecisions() const { return logDecisions_; }

 private:
  PolicyStore() {
    mode_ = parseMode(getenv("NCCL_ADAPTIVE_MODE"));
    staticCandidate_ = parseStaticCandidate(getenv("NCCL_ADAPTIVE_STATIC_CANDIDATE"));
    logDecisions_ = getenv("NCCL_ADAPTIVE_LOG_DECISIONS") == nullptr || strcmp(getenv("NCCL_ADAPTIVE_LOG_DECISIONS"), "0") != 0;
    const char* maxRecords = getenv("NCCL_ADAPTIVE_MAX_RECORDS");
    if (maxRecords != nullptr) {
      unsigned long parsed = strtoul(maxRecords, nullptr, 10);
      if (parsed > 0) maxRecords_ = static_cast<size_t>(parsed);
    }
  }

  CandidateSpec candidateForPhase(int collType, uint64_t phase) const {
    if (mode_ == AdaptiveMode::kDisabled) return kDefaultCandidate;
    if (mode_ == AdaptiveMode::kStatic) return staticCandidate_;
    std::vector<CandidateSpec> candidates = candidatesForCollType(collType);
    return candidates[phase % candidates.size()];
  }

  mutable std::mutex mutex_;
  std::unordered_map<PolicyKey, PolicyEntry, PolicyKeyHash> entries_;
  AdaptiveMode mode_ = AdaptiveMode::kAdaptive;
  CandidateSpec staticCandidate_ = kDefaultCandidate;
  bool logDecisions_ = true;
  size_t maxRecords_ = 256;
};

std::atomic<int> gProfilerContexts{0};

PolicyKey makeKey(int collType, size_t nBytes, int nRanks, int nNodes) {
  const SizeBin bin = sizeBinForBytes(nBytes);
  return PolicyKey{collType, bin.lower, bin.upper, nRanks, nNodes};
}

void retain(CollHandle* coll) {
  coll->refs.fetch_add(1, std::memory_order_relaxed);
}

void release(CollHandle* coll) {
  if (coll->refs.fetch_sub(1, std::memory_order_acq_rel) == 1) {
    delete coll;
  }
}

float* candidateCost(const CandidateSpec& candidate, float** collCostTable, int numAlgo, int numProto) {
  if (candidate.algorithm < 0 || candidate.protocol < 0) return nullptr;
  if (candidate.algorithm >= numAlgo || candidate.protocol >= numProto) return nullptr;
  if (collCostTable == nullptr) return nullptr;
  // NCCL passes a contiguous float[numAlgo][numProto] buffer cast to float**.
  // Do not index it as float**; that would interpret float data as row pointers.
  auto* table = reinterpret_cast<float*>(collCostTable);
  return &table[candidate.algorithm * numProto + candidate.protocol];
}

bool candidateAvailable(const CandidateSpec& candidate, float** collCostTable, int numAlgo, int numProto) {
  if (candidate.algorithm < 0 || candidate.protocol < 0) return true;
  float* cost = candidateCost(candidate, collCostTable, numAlgo, numProto);
  return cost != nullptr && *cost != NCCL_ALGO_PROTO_IGNORE;
}

void maybeRecordCompletion(CollHandle* coll) {
  CompletedRecord record;
  bool ready = false;
  {
    std::lock_guard<std::mutex> lock(coll->mutex);
    const bool kernelsComplete = (coll->nChannels == 0) ||
        (coll->startedKernelChannels == coll->nChannels && coll->stoppedKernelChannels == coll->nChannels);
    if (coll->completionRecorded || !kernelsComplete) return;
    coll->completionRecorded = true;
    const uint64_t startUsec = coll->firstKernelStartUsec != 0 ? coll->firstKernelStartUsec : coll->startUsec;
    const uint64_t stopUsec = coll->lastKernelStopUsec != 0 ? coll->lastKernelStopUsec : nowUsec();
    const double latencyUs = stopUsec > startUsec ? static_cast<double>(stopUsec - startUsec) : 0.0;
    const double algbwGbps = safeBandwidthGbps(coll->nBytes, latencyUs);
    record.mode = modeName(PolicyStore::instance().mode());
    record.key = coll->key;
    record.sequence = coll->sequence;
    record.phase = coll->phase;
    record.candidate = coll->phaseCandidate;
    record.selectedAlgo = coll->algo;
    record.selectedProto = coll->proto;
    record.selectedChannels = coll->nChannels;
    record.latencyUs = latencyUs;
    record.algbwGbps = algbwGbps;
    record.busbwGbps = busBandwidthGbps(coll->key.collType, coll->key.nRanks, algbwGbps);
    ready = true;
  }
  if (ready) {
    PolicyStore::instance().recordCompletion(record);
  }
}

}  // namespace

extern "C" {

__hidden ncclResult_t adaptiveProfilerInit(void** context, uint64_t commId, int* eActivationMask,
    const char* commName, int nNodes, int nranks, int rank, ncclDebugLogger_t logfn) {
  (void)commName;
  auto* profilerContext = new ProfilerContext();
  profilerContext->commId = commId;
  profilerContext->rank = rank;
  profilerContext->nRanks = nranks;
  profilerContext->nNodes = nNodes;
  profilerContext->logfn = logfn;
  *context = profilerContext;
  *eActivationMask = ncclProfileColl | ncclProfileKernelCh;
  gProfilerContexts.fetch_add(1, std::memory_order_relaxed);
  ADAPTIVE_LOG(logfn, NCCL_LOG_INFO, NCCL_PROFILE,
      "ADAPTIVE/profiler init comm=%" PRIu64 " rank=%d nranks=%d nnodes=%d mode=%s",
      commId, rank, nranks, nNodes, modeName(PolicyStore::instance().mode()));
  return ncclSuccess;
}

__hidden ncclResult_t adaptiveProfilerStartEvent(void* context, void** eHandle,
    ncclProfilerEventDescr_t* eDescr) {
  if (context == nullptr || eHandle == nullptr || eDescr == nullptr) return ncclSuccess;
  *eHandle = nullptr;
  auto* profilerContext = static_cast<ProfilerContext*>(context);
  if (eDescr->type == ncclProfileColl) {
    auto* coll = new CollHandle();
    coll->context = profilerContext;
    coll->sequence = eDescr->coll.seqNumber;
    coll->func = eDescr->coll.func != nullptr ? eDescr->coll.func : "";
    coll->datatype = eDescr->coll.datatype != nullptr ? eDescr->coll.datatype : "";
    coll->algo = eDescr->coll.algo != nullptr ? eDescr->coll.algo : "";
    coll->proto = eDescr->coll.proto != nullptr ? eDescr->coll.proto : "";
    coll->nChannels = eDescr->coll.nChannels;
    coll->nBytes = dtypeSize(eDescr->coll.datatype) * eDescr->coll.count;
    coll->startUsec = nowUsec();
    coll->key = makeKey(ncclFuncAllReduce, coll->nBytes, profilerContext->nRanks, profilerContext->nNodes);
    coll->key.collType = ncclFuncAllReduce;
    if (strcmp(coll->func.c_str(), "Broadcast") == 0) coll->key.collType = ncclFuncBroadcast;
    if (strcmp(coll->func.c_str(), "Reduce") == 0) coll->key.collType = ncclFuncReduce;
    if (strcmp(coll->func.c_str(), "AllGather") == 0) coll->key.collType = ncclFuncAllGather;
    if (strcmp(coll->func.c_str(), "ReduceScatter") == 0) coll->key.collType = ncclFuncReduceScatter;
    CandidateSpec candidate = PolicyStore::instance().planSelection(coll->key, false, &coll->phase);
    coll->phaseCandidate = candidate.name;
    *eHandle = coll;
    return ncclSuccess;
  }

  if (eDescr->type == ncclProfileKernelCh && eDescr->parentObj != nullptr) {
    auto* coll = static_cast<CollHandle*>(eDescr->parentObj);
    auto* kernel = new KernelHandle();
    kernel->coll = coll;
    kernel->channelId = eDescr->kernelCh.channelId;
    kernel->startTimer = eDescr->kernelCh.pTimer;
    kernel->startUsec = nowUsec();
    retain(coll);
    {
      std::lock_guard<std::mutex> lock(coll->mutex);
      coll->startedKernelChannels += 1;
      if (coll->firstKernelStartUsec == 0 || kernel->startUsec < coll->firstKernelStartUsec) {
        coll->firstKernelStartUsec = kernel->startUsec;
      }
      if (coll->firstKernelTimer == 0 || kernel->startTimer < coll->firstKernelTimer) {
        coll->firstKernelTimer = kernel->startTimer;
      }
    }
    *eHandle = kernel;
  }
  return ncclSuccess;
}

__hidden ncclResult_t adaptiveProfilerStopEvent(void* eHandle) {
  if (eHandle == nullptr) return ncclSuccess;
  uint64_t type = *static_cast<uint64_t*>(eHandle);
  if (type == ncclProfileColl) {
    auto* coll = static_cast<CollHandle*>(eHandle);
    {
      std::lock_guard<std::mutex> lock(coll->mutex);
      coll->hostStopped = true;
    }
    maybeRecordCompletion(coll);
    release(coll);
    return ncclSuccess;
  }

  if (type == ncclProfileKernelCh) {
    auto* kernel = static_cast<KernelHandle*>(eHandle);
    CollHandle* coll = kernel->coll;
    {
      std::lock_guard<std::mutex> lock(coll->mutex);
      coll->stoppedKernelChannels += 1;
      const uint64_t stopUsec = nowUsec();
      coll->lastKernelStopUsec = std::max(coll->lastKernelStopUsec, stopUsec);
      coll->lastKernelTimer = std::max(coll->lastKernelTimer, kernel->stopTimer);
    }
    maybeRecordCompletion(coll);
    release(coll);
    delete kernel;
  }
  return ncclSuccess;
}

__hidden ncclResult_t adaptiveProfilerRecordEventState(void* eHandle,
    ncclProfilerEventState_t eState, ncclProfilerEventStateArgs_t* eStateArgs) {
  if (eHandle == nullptr || eStateArgs == nullptr) return ncclSuccess;
  uint64_t type = *static_cast<uint64_t*>(eHandle);
  if (type == ncclProfileKernelCh && eState == ncclProfilerKernelChStop) {
    auto* kernel = static_cast<KernelHandle*>(eHandle);
    kernel->stopTimer = eStateArgs->kernelCh.pTimer;
  }
  return ncclSuccess;
}

__hidden ncclResult_t adaptiveProfilerFinalize(void* context) {
  auto* profilerContext = static_cast<ProfilerContext*>(context);
  if (profilerContext != nullptr && gProfilerContexts.fetch_sub(1, std::memory_order_acq_rel) == 1) {
    PolicyStore::instance().dumpRecords(profilerContext->logfn);
  }
  delete profilerContext;
  return ncclSuccess;
}

__hidden ncclResult_t adaptiveTunerInit(void** context, uint64_t commId, size_t nRanks,
    size_t nNodes, ncclDebugLogger_t logfn, ncclNvlDomainInfo_v5_t* nvlDomainInfo,
    ncclTunerConstants_v5_t* constants) {
  (void)nvlDomainInfo;
  (void)constants;
  auto* tunerContext = new TunerContext();
  tunerContext->commId = commId;
  tunerContext->nRanks = static_cast<int>(nRanks);
  tunerContext->nNodes = static_cast<int>(nNodes);
  tunerContext->logfn = logfn;
  *context = tunerContext;
  ADAPTIVE_LOG(logfn, NCCL_LOG_INFO, NCCL_TUNING,
      "ADAPTIVE/tuner init comm=%" PRIu64 " nranks=%zu nnodes=%zu mode=%s",
      commId, nRanks, nNodes, modeName(PolicyStore::instance().mode()));
  return ncclSuccess;
}

__hidden ncclResult_t adaptiveTunerGetCollInfo(void* context, ncclFunc_t collType, size_t nBytes,
    int numPipeOps, float** collCostTable, int numAlgo, int numProto, int regBuff, int* nChannels) {
  (void)numPipeOps;
  (void)regBuff;
  auto* tunerContext = static_cast<TunerContext*>(context);
  if (tunerContext == nullptr || collCostTable == nullptr || nChannels == nullptr) return ncclSuccess;

  const PolicyKey key = makeKey(collType, nBytes, tunerContext->nRanks, tunerContext->nNodes);
  CandidateSpec candidate = kDefaultCandidate;
  uint64_t phase = 0;
  if (!PolicyStore::instance().tryPlanSelection(key, &candidate, &phase)) {
    ADAPTIVE_LOG(tunerContext->logfn, NCCL_LOG_INFO, NCCL_TUNING,
        "ADAPTIVE/tuner fallback=contended key=%s", collTypeName(collType));
    return ncclSuccess;
  }

  if (PolicyStore::instance().mode() == AdaptiveMode::kDisabled) {
    return ncclSuccess;
  }

  if (candidate.algorithm >= 0 && candidate.protocol >= 0) {
    if (!candidateAvailable(candidate, collCostTable, numAlgo, numProto)) {
      ADAPTIVE_LOG(tunerContext->logfn, NCCL_LOG_INFO, NCCL_TUNING,
          "ADAPTIVE/tuner fallback=unavailable candidate=%s coll=%s bytes=%zu",
          candidate.name, collTypeName(collType), nBytes);
      return ncclSuccess;
    }
    float* cost = candidateCost(candidate, collCostTable, numAlgo, numProto);
    if (cost == nullptr) return ncclSuccess;
    *cost = 0.0f;
  }

  if (candidate.overrideChannels) {
    *nChannels = candidate.channels;
  }

  if (PolicyStore::instance().logDecisions()) {
    char keyText[ADAPTIVE_MAX_TEXT];
    keyToText(key, keyText, sizeof(keyText));
    ADAPTIVE_LOG(tunerContext->logfn, NCCL_LOG_INFO, NCCL_TUNING,
        "ADAPTIVE/decision key=%s phase=%" PRIu64 " candidate=%s rankset=%d/%d",
        keyText, phase, candidate.name, tunerContext->nRanks, tunerContext->nNodes);
  }

  return ncclSuccess;
}

__hidden ncclResult_t adaptiveTunerFinalize(void* context) {
  delete static_cast<TunerContext*>(context);
  return ncclSuccess;
}

__attribute__((visibility("default"))) ncclProfiler_t ncclProfiler_v5 = {
  ADAPTIVE_PLUGIN_NAME,
  adaptiveProfilerInit,
  adaptiveProfilerStartEvent,
  adaptiveProfilerStopEvent,
  adaptiveProfilerRecordEventState,
  adaptiveProfilerFinalize,
};

__attribute__((visibility("default"))) ncclTuner_v5_t ncclTunerPlugin_v5 = {
  ADAPTIVE_PLUGIN_NAME,
  adaptiveTunerInit,
  adaptiveTunerGetCollInfo,
  adaptiveTunerFinalize,
};

}  // extern "C"
