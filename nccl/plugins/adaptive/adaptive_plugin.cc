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
#include <fcntl.h>
#include <memory>
#include <mutex>
#include <string>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
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

constexpr uint64_t kCoordinatorMagic = 0x4144505449564551ULL;
constexpr uint32_t kCoordinatorVersion = 1;
constexpr size_t kSharedPublishedBuffers = 2;
constexpr size_t kMaxSharedCandidates = 4;
constexpr size_t kCandidateNameBytes = 32;

enum class AdaptiveMode {
  kWeakOnline,
  kFinalSteady,
  kStatic,
  kDisabled,
};

enum CandidateId : int32_t {
  kCandidateDefault = 0,
  kCandidateRingSimple = 1,
  kCandidateTreeSimple = 2,
  kCandidateRingLl128 = 3,
  kCandidateUnknown = -1,
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

struct DomainKey {
  uint64_t commId = 0;
  PolicyKey key{};

  bool operator==(const DomainKey& other) const {
    return commId == other.commId && key == other.key;
  }
};

struct DomainKeyHash {
  size_t operator()(const DomainKey& value) const {
    size_t seed = static_cast<size_t>(value.commId);
    seed ^= PolicyKeyHash{}(value.key) + 0x9e3779b97f4a7c15ULL + (seed << 6) + (seed >> 2);
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
  uint64_t commId = 0;
  uint64_t sequence = 0;
  uint64_t phase = 0;
  uint64_t epoch = 0;
  uint64_t windowId = 0;
  bool sampledWindow = false;
  bool unavailable = false;
  int startedKernelChannels = 0;
  int stoppedKernelChannels = 0;
  bool partialKernelCoverage = false;
  bool usedHostStopFallback = false;
  std::string candidate;
  std::string selectedAlgo;
  std::string selectedProto;
  int selectedChannels = 0;
  double latencyUs = 0.0;
  double algbwGbps = 0.0;
  double busbwGbps = 0.0;
};

struct WindowSummary {
  PolicyKey key{};
  uint64_t commId = 0;
  uint64_t observedEpoch = 0;
  uint64_t windowId = 0;
  std::string candidate;
  uint64_t sampleCount = 0;
  double latencySumUs = 0.0;
  double bwSum = 0.0;
  bool unavailable = false;
  bool complete = false;
};

struct PendingPlan {
  CandidateSpec candidate{};
  uint64_t epoch = 0;
  uint64_t windowId = 0;
  uint64_t callIndex = 0;
  bool sampledWindow = false;
  bool unavailable = false;
};

struct SelectionPlan {
  CandidateSpec candidate{};
  uint64_t epoch = 0;
  uint64_t windowId = 0;
  uint64_t callIndex = 0;
  bool sampledWindow = false;
  bool unavailable = false;
};

struct ActivatedPolicy {
  CandidateSpec candidate{};
  uint64_t epoch = 0;
  uint64_t recheckAfter = 0;
  bool valid = false;
};

struct ObservationWindow {
  bool active = false;
  bool warmup = false;
  PolicyKey key{};
  uint64_t observedEpoch = 0;
  uint64_t windowId = 0;
  std::vector<CandidateSpec> schedule;
  size_t nextScheduleIndex = 0;
  size_t inflightSamples = 0;
  std::unordered_map<std::string, WindowSummary> summaries;
};

struct SharedCandidate {
  int32_t id = kCandidateUnknown;
  int32_t algorithm = NCCL_ALGO_UNDEF;
  int32_t protocol = NCCL_PROTO_UNDEF;
  int32_t channels = 0;
  uint8_t overrideChannels = 0;
  char name[kCandidateNameBytes]{};
};

struct SharedCandidateSummary {
  SharedCandidate candidate{};
  uint64_t sampleCount = 0;
  double latencySumUs = 0.0;
  double bwSum = 0.0;
  uint8_t unavailable = 0;
  uint8_t complete = 0;
};

struct SharedPublishedRecord {
  std::atomic<uint32_t> sequence{0};
  uint64_t generation = 0;
  uint64_t epoch = 0;
  SharedCandidate candidate{};
  uint64_t recheckAfter = 0;
  uint64_t publishedCallIndex = 0;
  uint64_t effectiveCallIndex = 0;
  uint8_t valid = 0;
};

struct SharedSummarySlot {
  std::atomic<uint32_t> sequence{0};
  uint64_t generation = 0;
  uint64_t observedEpoch = 0;
  uint64_t windowId = 0;
  uint32_t rank = 0;
  uint32_t candidateCount = 0;
  uint8_t ready = 0;
  SharedCandidateSummary summaries[kMaxSharedCandidates]{};
};

struct SharedCoordinatorHeader {
  uint64_t magic = 0;
  uint32_t version = 0;
  std::atomic<uint32_t> valid{0};
  uint64_t commId = 0;
  uint64_t generation = 0;
  uint32_t nRanks = 0;
  uint32_t nNodes = 0;
  uint32_t activationLag = 0;
  std::atomic<uint32_t> activePublishedIndex{0};
};

struct SharedPublishedSnapshot {
  uint64_t generation = 0;
  uint64_t epoch = 0;
  CandidateSpec candidate{};
  uint64_t recheckAfter = 0;
  uint64_t publishedCallIndex = 0;
  uint64_t effectiveCallIndex = 0;
  bool valid = false;
};

struct SharedSummarySnapshot {
  uint64_t generation = 0;
  uint64_t observedEpoch = 0;
  uint64_t windowId = 0;
  uint32_t rank = 0;
  uint32_t candidateCount = 0;
  bool ready = false;
  std::array<SharedCandidateSummary, kMaxSharedCandidates> summaries{};
};

struct SharedCoordinatorHandle {
  int fd = -1;
  size_t size = 0;
  SharedCoordinatorHeader* header = nullptr;
  std::string shmName;
  bool representative = false;
};

struct PolicyEntry {
  uint64_t nextCallIndex = 0;
  uint64_t nextWindowId = 0;
  uint64_t lastPublishedEpoch = 0;
  uint64_t lastPlannedCallIndex = 0;
  uint64_t callsUntilRecheck = 0;
  uint64_t pendingObservedEpoch = 0;
  uint64_t pendingWindowId = 0;
  bool pendingPublication = false;
  bool pendingActivation = false;
  std::deque<PendingPlan> pendingPlans;
  std::unordered_map<std::string, bool> suspectUnavailable;
  ActivatedPolicy active;
  ObservationWindow window;
  std::shared_ptr<SharedCoordinatorHandle> coordinator;
};

struct CommunicatorRuntime {
  int refCount = 0;
  int rank = -1;
  int nRanks = 0;
  int nNodes = 0;
  ncclDebugLogger_t logfn = nullptr;
  std::unordered_map<PolicyKey, std::shared_ptr<SharedCoordinatorHandle>, PolicyKeyHash> coordinators;
};

struct TunerContext {
  uint64_t commId = 0;
  int rank = -1;
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
  uint64_t commId = 0;
  uint64_t sequence = 0;
  uint64_t phase = 0;
  uint64_t epoch = 0;
  uint64_t windowId = 0;
  bool sampledWindow = false;
  bool unavailable = false;
  std::string phaseCandidate;
  std::string func;
  std::string datatype;
  std::string algo;
  std::string proto;
  size_t nBytes = 0;
  int nChannels = 0;
  uint64_t startUsec = 0;
  uint64_t hostStopUsec = 0;
  uint64_t firstKernelStartUsec = 0;
  uint64_t lastKernelStopUsec = 0;
  uint64_t firstKernelTimer = 0;
  uint64_t lastKernelTimer = 0;
  int startedKernelChannels = 0;
  int stoppedKernelChannels = 0;
  bool hostStopped = false;
  bool completionRecorded = false;
  bool planAttached = false;
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
  if (value == nullptr || strcmp(value, "adaptive") == 0 || strcmp(value, "weak-online") == 0) {
    return AdaptiveMode::kWeakOnline;
  }
  if (strcmp(value, "steady") == 0 || strcmp(value, "final-steady") == 0) {
    return AdaptiveMode::kFinalSteady;
  }
  if (strcmp(value, "static") == 0) return AdaptiveMode::kStatic;
  if (strcmp(value, "disabled") == 0 || strcmp(value, "off") == 0) return AdaptiveMode::kDisabled;
  return AdaptiveMode::kWeakOnline;
}

const char* modeName(AdaptiveMode mode) {
  switch (mode) {
    case AdaptiveMode::kFinalSteady: return "final-steady";
    case AdaptiveMode::kStatic: return "static";
    case AdaptiveMode::kDisabled: return "disabled";
    case AdaptiveMode::kWeakOnline: return "weak-online";
  }
  return "weak-online";
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

CandidateId candidateIdForSpec(const CandidateSpec& candidate) {
  if (candidate.name == nullptr) return kCandidateUnknown;
  if (strcmp(candidate.name, kDefaultCandidate.name) == 0) return kCandidateDefault;
  if (strcmp(candidate.name, kRingSimpleCandidate.name) == 0) return kCandidateRingSimple;
  if (strcmp(candidate.name, kTreeSimpleCandidate.name) == 0) return kCandidateTreeSimple;
  if (strcmp(candidate.name, kRingLl128Candidate.name) == 0) return kCandidateRingLl128;
  return kCandidateUnknown;
}

CandidateSpec candidateSpecForId(int32_t id) {
  switch (id) {
    case kCandidateDefault: return kDefaultCandidate;
    case kCandidateRingSimple: return kRingSimpleCandidate;
    case kCandidateTreeSimple: return kTreeSimpleCandidate;
    case kCandidateRingLl128: return kRingLl128Candidate;
    default: return kDefaultCandidate;
  }
}

void storeCandidate(SharedCandidate* dst, const CandidateSpec& candidate) {
  if (dst == nullptr) return;
  dst->id = candidateIdForSpec(candidate);
  dst->algorithm = candidate.algorithm;
  dst->protocol = candidate.protocol;
  dst->channels = candidate.channels;
  dst->overrideChannels = candidate.overrideChannels ? 1 : 0;
  snprintf(dst->name, sizeof(dst->name), "%s", candidate.name != nullptr ? candidate.name : "");
}

CandidateSpec loadCandidate(const SharedCandidate& src) {
  CandidateSpec candidate = candidateSpecForId(src.id);
  candidate.algorithm = src.algorithm;
  candidate.protocol = src.protocol;
  candidate.channels = src.channels;
  candidate.overrideChannels = src.overrideChannels != 0;
  return candidate;
}

size_t coordinatorSize(uint32_t nRanks) {
  return sizeof(SharedCoordinatorHeader) +
      sizeof(SharedPublishedRecord) * kSharedPublishedBuffers +
      sizeof(SharedSummarySlot) * nRanks;
}

SharedPublishedRecord* publishedRecords(SharedCoordinatorHeader* header) {
  return reinterpret_cast<SharedPublishedRecord*>(header + 1);
}

SharedSummarySlot* summarySlots(SharedCoordinatorHeader* header) {
  return reinterpret_cast<SharedSummarySlot*>(publishedRecords(header) + kSharedPublishedBuffers);
}

int parseRankEnv() {
  const char* value = getenv("RANK");
  if (value == nullptr || *value == '\0') return -1;
  char* end = nullptr;
  long parsed = strtol(value, &end, 10);
  return (end != value) ? static_cast<int>(parsed) : -1;
}

std::string coordinatorName(uint64_t commId, const PolicyKey& key) {
  char buffer[ADAPTIVE_MAX_TEXT];
  snprintf(buffer, sizeof(buffer), "/nccl-adapt-%" PRIu64 "-%08x-%" PRIu64 "-%" PRIu64 "-%d-%d",
      commId, key.collType, key.sizeBinLower, key.sizeBinUpper, key.nRanks, key.nNodes);
  return std::string(buffer);
}

bool snapshotPublishedRecord(SharedPublishedRecord* record, SharedPublishedSnapshot* out) {
  if (record == nullptr || out == nullptr) return false;
  SharedPublishedSnapshot snapshot;
  const uint32_t seq0 = record->sequence.load(std::memory_order_acquire);
  if ((seq0 & 1U) != 0) return false;
  snapshot.generation = record->generation;
  snapshot.epoch = record->epoch;
  snapshot.candidate = loadCandidate(record->candidate);
  snapshot.recheckAfter = record->recheckAfter;
  snapshot.publishedCallIndex = record->publishedCallIndex;
  snapshot.effectiveCallIndex = record->effectiveCallIndex;
  snapshot.valid = record->valid != 0;
  const uint32_t seq1 = record->sequence.load(std::memory_order_acquire);
  if (seq0 != seq1 || (seq1 & 1U) != 0) return false;
  *out = snapshot;
  return true;
}

bool snapshotSummarySlot(SharedSummarySlot* slot, SharedSummarySnapshot* out) {
  if (slot == nullptr || out == nullptr) return false;
  SharedSummarySnapshot snapshot;
  const uint32_t seq0 = slot->sequence.load(std::memory_order_acquire);
  if ((seq0 & 1U) != 0) return false;
  snapshot.generation = slot->generation;
  snapshot.observedEpoch = slot->observedEpoch;
  snapshot.windowId = slot->windowId;
  snapshot.rank = slot->rank;
  snapshot.candidateCount = slot->candidateCount;
  snapshot.ready = slot->ready != 0;
  for (size_t i = 0; i < kMaxSharedCandidates; ++i) snapshot.summaries[i] = slot->summaries[i];
  const uint32_t seq1 = slot->sequence.load(std::memory_order_acquire);
  if (seq0 != seq1 || (seq1 & 1U) != 0) return false;
  *out = snapshot;
  return true;
}

void closeCoordinatorHandle(std::shared_ptr<SharedCoordinatorHandle> handle) {
  if (!handle) return;
  if (handle->header != nullptr) {
    munmap(handle->header, handle->size);
    handle->header = nullptr;
  }
  if (handle->fd >= 0) {
    close(handle->fd);
    handle->fd = -1;
  }
}

class PolicyStore {
 public:
  static PolicyStore& instance() {
    static PolicyStore store;
    return store;
  }

  void registerProfiler(uint64_t commId, int rank, int nRanks, int nNodes, ncclDebugLogger_t logfn) {
    std::lock_guard<std::mutex> lock(mutex_);
    CommunicatorRuntime& runtime = communicators_[commId];
    runtime.refCount += 1;
    runtime.rank = rank;
    runtime.nRanks = nRanks;
    runtime.nNodes = nNodes;
    runtime.logfn = logfn;
  }

  void registerTuner(uint64_t commId, int rank, int nRanks, int nNodes, ncclDebugLogger_t logfn) {
    std::lock_guard<std::mutex> lock(mutex_);
    CommunicatorRuntime& runtime = communicators_[commId];
    runtime.refCount += 1;
    if (rank >= 0) runtime.rank = rank;
    runtime.nRanks = nRanks;
    runtime.nNodes = nNodes;
    runtime.logfn = logfn;
  }

  void unregisterCommunicator(uint64_t commId) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = communicators_.find(commId);
    if (it == communicators_.end()) return;
    if (it->second.refCount > 0) it->second.refCount -= 1;
    if (it->second.refCount != 0) return;

    for (auto& pair : it->second.coordinators) {
      const std::shared_ptr<SharedCoordinatorHandle>& handle = pair.second;
      if (handle && handle->header != nullptr && handle->representative) {
        handle->header->valid.store(0, std::memory_order_release);
        shm_unlink(handle->shmName.c_str());
      }
      closeCoordinatorHandle(handle);
    }
    communicators_.erase(it);

    for (auto entryIt = entries_.begin(); entryIt != entries_.end();) {
      if (entryIt->first.commId == commId) {
        closeCoordinatorHandle(entryIt->second.coordinator);
        entryIt = entries_.erase(entryIt);
      } else {
        ++entryIt;
      }
    }
  }

  bool tryPlanSelection(uint64_t commId, const PolicyKey& key, SelectionPlan* planOut) {
    if (!mutex_.try_lock()) return false;
    PolicyEntry& entry = entries_[DomainKey{commId, key}];
    SelectionPlan plan = planSelectionLocked(commId, key, entry);
    if (plan.candidate.name == nullptr) {
      plan.candidate = kDefaultCandidate;
    }
    entry.pendingPlans.push_back(PendingPlan{
        plan.candidate, plan.epoch, plan.windowId, plan.callIndex, plan.sampledWindow, plan.unavailable});
    if (logCompletion_) {
      auto runtimeIt = communicators_.find(commId);
      ncclDebugLogger_t logfn = runtimeIt != communicators_.end() ? runtimeIt->second.logfn : nullptr;
      char keyText[ADAPTIVE_MAX_TEXT];
      keyToText(key, keyText, sizeof(keyText));
      ADAPTIVE_LOG(logfn, NCCL_LOG_INFO, NCCL_TUNING,
          "ADAPTIVE/completion enqueue comm=%" PRIu64 " key=%s phase=%" PRIu64 " sampled=%d queue_depth=%zu candidate=%s",
          commId, keyText, plan.callIndex, plan.sampledWindow ? 1 : 0, entry.pendingPlans.size(),
          plan.candidate.name != nullptr ? plan.candidate.name : kDefaultCandidate.name);
    }
    mutex_.unlock();
    if (planOut != nullptr) *planOut = plan;
    return true;
  }

  bool attachProfilerPlan(uint64_t commId, const PolicyKey& key, CollHandle* coll) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = entries_.find(DomainKey{commId, key});
    auto runtimeIt = communicators_.find(commId);
    ncclDebugLogger_t logfn = runtimeIt != communicators_.end() ? runtimeIt->second.logfn : nullptr;
    if (it == entries_.end() || it->second.pendingPlans.empty() || coll == nullptr) {
      if (logCompletion_ && coll != nullptr) {
        char keyText[ADAPTIVE_MAX_TEXT];
        keyToText(key, keyText, sizeof(keyText));
        ADAPTIVE_LOG(logfn, NCCL_LOG_INFO, NCCL_TUNING,
            "ADAPTIVE/completion attach-miss comm=%" PRIu64 " key=%s seq=%" PRIu64,
            commId, keyText, coll->sequence);
      }
      return false;
    }
    PendingPlan plan = it->second.pendingPlans.front();
    it->second.pendingPlans.pop_front();
    coll->phase = plan.callIndex;
    coll->epoch = plan.epoch;
    coll->windowId = plan.windowId;
    coll->sampledWindow = plan.sampledWindow;
    coll->unavailable = plan.unavailable;
    coll->phaseCandidate = plan.candidate.name != nullptr ? plan.candidate.name : kDefaultCandidate.name;
    coll->planAttached = true;
    if (logCompletion_) {
      char keyText[ADAPTIVE_MAX_TEXT];
      keyToText(key, keyText, sizeof(keyText));
      ADAPTIVE_LOG(logfn, NCCL_LOG_INFO, NCCL_TUNING,
          "ADAPTIVE/completion attach comm=%" PRIu64 " key=%s seq=%" PRIu64 " phase=%" PRIu64
          " sampled=%d queue_remaining=%zu candidate=%s",
          commId, keyText, coll->sequence, coll->phase, coll->sampledWindow ? 1 : 0,
          it->second.pendingPlans.size(), coll->phaseCandidate.c_str());
    }
    return true;
  }

  void recordCompletion(const CompletedRecord& record) {
    std::lock_guard<std::mutex> lock(mutex_);
    PolicyEntry& entry = entries_[DomainKey{record.commId, record.key}];
    updateWindowSummaryLocked(entry, record);
  }

  void tryMarkUnavailable(uint64_t commId, const PolicyKey& key, const char* candidateName) {
    if (candidateName == nullptr) return;
    if (!mutex_.try_lock()) return;
    PolicyEntry& entry = entries_[DomainKey{commId, key}];
    entry.suspectUnavailable[candidateName] = true;
    if (entry.window.active) {
      WindowSummary& summary = entry.window.summaries[candidateName];
      if (summary.candidate.empty()) {
        summary.key = key;
        summary.commId = commId;
        summary.observedEpoch = entry.window.observedEpoch;
        summary.windowId = entry.window.windowId;
        summary.candidate = candidateName;
      }
      summary.unavailable = true;
      summary.complete = true;
    }
    mutex_.unlock();
  }

  void dumpRecords(ncclDebugLogger_t logfn) {
    (void)logfn;
  }

  AdaptiveMode mode() const { return mode_; }
  const CandidateSpec& staticCandidate() const { return staticCandidate_; }
  bool logDecisions() const { return logDecisions_; }
  bool logCoordinator() const { return logCoordinator_; }
  bool logCompletion() const { return logCompletion_; }

 private:
  PolicyStore() {
    mode_ = parseMode(getenv("NCCL_ADAPTIVE_MODE"));
    staticCandidate_ = parseStaticCandidate(getenv("NCCL_ADAPTIVE_STATIC_CANDIDATE"));
    logDecisions_ = getenv("NCCL_ADAPTIVE_LOG_DECISIONS") != nullptr &&
        strcmp(getenv("NCCL_ADAPTIVE_LOG_DECISIONS"), "0") != 0;
    logCoordinator_ = getenv("NCCL_ADAPTIVE_LOG_COORDINATOR") != nullptr &&
        strcmp(getenv("NCCL_ADAPTIVE_LOG_COORDINATOR"), "0") != 0;
    logCompletion_ = getenv("NCCL_ADAPTIVE_LOG_COMPLETION") != nullptr &&
        strcmp(getenv("NCCL_ADAPTIVE_LOG_COMPLETION"), "0") != 0;
    warmupSamplesPerCandidate_ = parseU64Env("NCCL_ADAPTIVE_WARMUP_SAMPLES_PER_CANDIDATE", 1);
    recheckSamplesPerCandidate_ = parseU64Env("NCCL_ADAPTIVE_RECHECK_SAMPLES_PER_CANDIDATE", 1);
    recheckAfter_ = parseU64Env("NCCL_ADAPTIVE_RECHECK_AFTER", 64);
    minSamples_ = parseU64Env("NCCL_ADAPTIVE_MIN_SAMPLES", 1);
    switchThresholdPct_ = parseDoubleEnv("NCCL_ADAPTIVE_SWITCH_THRESHOLD_PCT", 2.0);
    activationLag_ = std::max<uint64_t>(2, parseU64Env("NCCL_ADAPTIVE_ACTIVATION_LAG", 2));
    const char* maxRecords = getenv("NCCL_ADAPTIVE_MAX_RECORDS");
    if (maxRecords != nullptr) {
      unsigned long parsed = strtoul(maxRecords, nullptr, 10);
      if (parsed > 0) maxRecords_ = static_cast<size_t>(parsed);
    }
  }

  static uint64_t parseU64Env(const char* name, uint64_t defaultValue) {
    const char* value = getenv(name);
    if (value == nullptr || *value == '\0') return defaultValue;
    char* end = nullptr;
    const unsigned long long parsed = strtoull(value, &end, 10);
    return (end != value) ? static_cast<uint64_t>(parsed) : defaultValue;
  }

  static double parseDoubleEnv(const char* name, double defaultValue) {
    const char* value = getenv(name);
    if (value == nullptr || *value == '\0') return defaultValue;
    char* end = nullptr;
    const double parsed = strtod(value, &end);
    return (end != value) ? parsed : defaultValue;
  }

  CandidateSpec candidateForPhase(int collType, uint64_t phase) const {
    if (mode_ == AdaptiveMode::kDisabled) return kDefaultCandidate;
    if (mode_ == AdaptiveMode::kStatic) return staticCandidate_;
    std::vector<CandidateSpec> candidates = candidatesForCollType(collType);
    return candidates[phase % candidates.size()];
  }

  std::vector<CandidateSpec> windowScheduleForKey(const PolicyKey& key, bool warmup) const {
    const uint64_t repeats = warmup ? warmupSamplesPerCandidate_ : recheckSamplesPerCandidate_;
    std::vector<CandidateSpec> schedule;
    for (const CandidateSpec& candidate : candidatesForCollType(key.collType)) {
      for (uint64_t i = 0; i < std::max<uint64_t>(1, repeats); ++i) {
        schedule.push_back(candidate);
      }
    }
    return schedule;
  }

  void openWindowLocked(const PolicyKey& key, PolicyEntry& entry, bool warmup) {
    entry.window = ObservationWindow{};
    entry.window.active = true;
    entry.window.warmup = warmup;
    entry.window.key = key;
    entry.window.observedEpoch = entry.active.valid ? entry.active.epoch : 0;
    entry.window.windowId = entry.nextWindowId++;
    entry.window.schedule = windowScheduleForKey(key, warmup);
  }

  std::shared_ptr<SharedCoordinatorHandle> ensureCoordinatorLocked(uint64_t commId, const PolicyKey& key, PolicyEntry* entry) {
    auto runtimeIt = communicators_.find(commId);
    if (runtimeIt == communicators_.end()) return nullptr;
    CommunicatorRuntime& runtime = runtimeIt->second;
    auto cached = runtime.coordinators.find(key);
    if (cached != runtime.coordinators.end()) {
      if (entry != nullptr) entry->coordinator = cached->second;
      return cached->second;
    }

    auto handle = std::make_shared<SharedCoordinatorHandle>();
    handle->representative = runtime.rank == 0;
    handle->shmName = coordinatorName(commId, key);
    handle->size = coordinatorSize(static_cast<uint32_t>(runtime.nRanks));
    const int openFlags = handle->representative ? (O_CREAT | O_RDWR) : O_RDWR;
    handle->fd = shm_open(handle->shmName.c_str(), openFlags, 0600);
    if (handle->fd < 0) return nullptr;
    if (handle->representative && ftruncate(handle->fd, static_cast<off_t>(handle->size)) != 0) {
      closeCoordinatorHandle(handle);
      return nullptr;
    }
    void* mapped = mmap(nullptr, handle->size, PROT_READ | PROT_WRITE, MAP_SHARED, handle->fd, 0);
    if (mapped == MAP_FAILED) {
      closeCoordinatorHandle(handle);
      return nullptr;
    }
    handle->header = static_cast<SharedCoordinatorHeader*>(mapped);

    if (handle->representative) {
      const bool needsInit = handle->header->magic != kCoordinatorMagic ||
          handle->header->version != kCoordinatorVersion ||
          handle->header->commId != commId ||
          handle->header->nRanks != static_cast<uint32_t>(runtime.nRanks) ||
          handle->header->nNodes != static_cast<uint32_t>(runtime.nNodes) ||
          handle->header->valid.load(std::memory_order_acquire) == 0;
      if (needsInit) {
        char* bytes = reinterpret_cast<char*>(handle->header);
        std::fill(bytes, bytes + handle->size, 0);
        handle->header->magic = kCoordinatorMagic;
        handle->header->version = kCoordinatorVersion;
        handle->header->commId = commId;
        handle->header->generation = nowUsec();
        handle->header->nRanks = static_cast<uint32_t>(runtime.nRanks);
        handle->header->nNodes = static_cast<uint32_t>(runtime.nNodes);
        handle->header->activationLag = static_cast<uint32_t>(activationLag_);
        handle->header->activePublishedIndex.store(0, std::memory_order_release);
        handle->header->valid.store(1, std::memory_order_release);
      }
    } else {
      if (handle->header->magic != kCoordinatorMagic ||
          handle->header->version != kCoordinatorVersion ||
          handle->header->commId != commId ||
          handle->header->valid.load(std::memory_order_acquire) == 0) {
        closeCoordinatorHandle(handle);
        return nullptr;
      }
    }

    runtime.coordinators.emplace(key, handle);
    if (entry != nullptr) entry->coordinator = handle;
    return handle;
  }

  bool readPublishedLocked(std::shared_ptr<SharedCoordinatorHandle> handle, SharedPublishedSnapshot* out) {
    if (!handle || handle->header == nullptr || out == nullptr) return false;
    if (handle->header->valid.load(std::memory_order_acquire) == 0) return false;
    const uint32_t index0 = handle->header->activePublishedIndex.load(std::memory_order_acquire);
    SharedPublishedRecord* records = publishedRecords(handle->header);
    if (index0 >= kSharedPublishedBuffers) return false;
    SharedPublishedSnapshot snapshot;
    if (!snapshotPublishedRecord(&records[index0], &snapshot)) return false;
    const uint32_t index1 = handle->header->activePublishedIndex.load(std::memory_order_acquire);
    if (index0 != index1) return false;
    if (snapshot.generation != handle->header->generation) return false;
    *out = snapshot;
    return true;
  }

  void refreshActivePolicyLocked(uint64_t commId, const PolicyKey& key, PolicyEntry& entry, uint64_t callIndex) {
    std::shared_ptr<SharedCoordinatorHandle> handle = ensureCoordinatorLocked(commId, key, &entry);
    SharedPublishedSnapshot snapshot;
    if (!readPublishedLocked(handle, &snapshot) || !snapshot.valid) return;
    auto runtimeIt = communicators_.find(commId);
    ncclDebugLogger_t logfn = runtimeIt != communicators_.end() ? runtimeIt->second.logfn : nullptr;
    const uint64_t previousPublishedEpoch = entry.lastPublishedEpoch;
    entry.lastPublishedEpoch = std::max(entry.lastPublishedEpoch, snapshot.epoch);
    if (snapshot.epoch > previousPublishedEpoch) {
      entry.pendingPublication = false;
      if (!entry.active.valid || snapshot.epoch > entry.active.epoch) {
        entry.pendingActivation = true;
        if (logCoordinator_) {
          char keyText[ADAPTIVE_MAX_TEXT];
          keyToText(key, keyText, sizeof(keyText));
          ADAPTIVE_LOG(logfn, NCCL_LOG_INFO, NCCL_TUNING,
              "ADAPTIVE/coordinator observed-publish comm=%" PRIu64 " key=%s epoch=%" PRIu64
              " effective_call=%" PRIu64 " call=%" PRIu64 " candidate=%s",
              commId, keyText, snapshot.epoch, snapshot.effectiveCallIndex, callIndex,
              snapshot.candidate.name != nullptr ? snapshot.candidate.name : kDefaultCandidate.name);
        }
      }
    }
    if ((!entry.active.valid || snapshot.epoch > entry.active.epoch) && callIndex >= snapshot.effectiveCallIndex) {
      entry.active.candidate = snapshot.candidate;
      entry.active.epoch = snapshot.epoch;
      entry.active.recheckAfter = snapshot.recheckAfter;
      entry.active.valid = true;
      entry.callsUntilRecheck = snapshot.recheckAfter;
      entry.pendingObservedEpoch = 0;
      entry.pendingWindowId = 0;
      entry.pendingPublication = false;
      entry.pendingActivation = false;
      entry.suspectUnavailable.clear();
      if (logCoordinator_) {
        char keyText[ADAPTIVE_MAX_TEXT];
        keyToText(key, keyText, sizeof(keyText));
        ADAPTIVE_LOG(logfn, NCCL_LOG_INFO, NCCL_TUNING,
            "ADAPTIVE/coordinator activate comm=%" PRIu64 " key=%s epoch=%" PRIu64
            " call=%" PRIu64 " candidate=%s recheck_after=%" PRIu64,
            commId, keyText, entry.active.epoch, callIndex,
            entry.active.candidate.name != nullptr ? entry.active.candidate.name : kDefaultCandidate.name,
            entry.active.recheckAfter);
      }
    }
  }

  bool tryPublishPendingLocked(uint64_t commId, const PolicyKey& key, PolicyEntry& entry) {
    if (!entry.pendingPublication) return false;
    std::shared_ptr<SharedCoordinatorHandle> handle = ensureCoordinatorLocked(commId, key, &entry);
    if (!handle || !handle->representative) return false;
    return aggregateAndPublishLocked(commId, key, entry, entry.pendingObservedEpoch, entry.pendingWindowId);
  }

  SelectionPlan planSelectionLocked(uint64_t commId, const PolicyKey& key, PolicyEntry& entry) {
    SelectionPlan plan;
    plan.callIndex = entry.nextCallIndex++;
    entry.lastPlannedCallIndex = plan.callIndex;

    if (mode_ == AdaptiveMode::kDisabled) return plan;
    if (mode_ == AdaptiveMode::kStatic) {
      plan.candidate = staticCandidate_;
      return plan;
    }

    tryPublishPendingLocked(commId, key, entry);
    refreshActivePolicyLocked(commId, key, entry, plan.callIndex);

    if (entry.window.active && entry.window.nextScheduleIndex < entry.window.schedule.size()) {
      plan.candidate = entry.window.schedule[entry.window.nextScheduleIndex++];
      plan.epoch = entry.window.observedEpoch;
      plan.windowId = entry.window.windowId;
      plan.sampledWindow = true;
      plan.unavailable = entry.suspectUnavailable[plan.candidate.name];
      entry.window.inflightSamples += 1;
      return plan;
    }

    if (entry.window.active || entry.pendingPublication || entry.pendingActivation) {
      if (entry.active.valid) {
        plan.candidate = entry.active.candidate;
        plan.epoch = entry.active.epoch;
        plan.unavailable = entry.suspectUnavailable[plan.candidate.name];
      }
      return plan;
    }

    if (!entry.active.valid && !entry.window.active) {
      openWindowLocked(key, entry, true);
      plan.candidate = entry.window.schedule[entry.window.nextScheduleIndex++];
      plan.epoch = entry.window.observedEpoch;
      plan.windowId = entry.window.windowId;
      plan.sampledWindow = true;
      plan.unavailable = entry.suspectUnavailable[plan.candidate.name];
      entry.window.inflightSamples += 1;
      return plan;
    }

    if (mode_ == AdaptiveMode::kWeakOnline && entry.active.valid && !entry.window.active) {
      if (entry.callsUntilRecheck == 0) {
        openWindowLocked(key, entry, false);
        plan.candidate = entry.window.schedule[entry.window.nextScheduleIndex++];
        plan.epoch = entry.window.observedEpoch;
        plan.windowId = entry.window.windowId;
        plan.sampledWindow = true;
        plan.unavailable = entry.suspectUnavailable[plan.candidate.name];
        entry.window.inflightSamples += 1;
        return plan;
      }
      entry.callsUntilRecheck -= 1;
    }

    if (entry.active.valid) {
      plan.candidate = entry.active.candidate;
      plan.epoch = entry.active.epoch;
      plan.unavailable = entry.suspectUnavailable[plan.candidate.name];
      return plan;
    }

    return plan;
  }

  void updateWindowSummaryLocked(PolicyEntry& entry, const CompletedRecord& record) {
    if (!record.sampledWindow || !entry.window.active) return;
    if (record.windowId != entry.window.windowId || record.epoch != entry.window.observedEpoch) return;

    WindowSummary& summary = entry.window.summaries[record.candidate];
    if (summary.candidate.empty()) {
      summary.key = record.key;
      summary.commId = record.commId;
      summary.observedEpoch = record.epoch;
      summary.windowId = record.windowId;
      summary.candidate = record.candidate;
    }
    if (record.unavailable) {
      summary.unavailable = true;
    } else {
      summary.sampleCount += 1;
      summary.latencySumUs += record.latencyUs;
      summary.bwSum += record.busbwGbps;
    }
    summary.complete = true;

    if (entry.window.inflightSamples > 0) entry.window.inflightSamples -= 1;
    const bool scheduledAll = entry.window.nextScheduleIndex >= entry.window.schedule.size();
    if (scheduledAll && entry.window.inflightSamples == 0) {
      finalizeWindowLocked(record.commId, record.key, entry);
    }
  }

  bool writeSummarySlotLocked(std::shared_ptr<SharedCoordinatorHandle> handle, int rank, const ObservationWindow& window) {
    if (!handle || handle->header == nullptr || handle->header->valid.load(std::memory_order_acquire) == 0) return false;
    if (rank < 0 || rank >= static_cast<int>(handle->header->nRanks)) return false;
    SharedSummarySlot* slot = &summarySlots(handle->header)[rank];
    uint32_t seq = slot->sequence.load(std::memory_order_relaxed);
    slot->sequence.store(seq + 1, std::memory_order_release);
    slot->generation = handle->header->generation;
    slot->observedEpoch = window.observedEpoch;
    slot->windowId = window.windowId;
    slot->rank = static_cast<uint32_t>(rank);
    std::vector<CandidateSpec> candidates = candidatesForCollType(window.key.collType);
    slot->candidateCount = static_cast<uint32_t>(std::min(candidates.size(), kMaxSharedCandidates));
    slot->ready = 1;
    for (size_t i = 0; i < kMaxSharedCandidates; ++i) {
      SharedCandidateSummary summary{};
      if (i < candidates.size()) {
        storeCandidate(&summary.candidate, candidates[i]);
        auto it = window.summaries.find(candidates[i].name);
        if (it != window.summaries.end()) {
          summary.sampleCount = it->second.sampleCount;
          summary.latencySumUs = it->second.latencySumUs;
          summary.bwSum = it->second.bwSum;
          summary.unavailable = it->second.unavailable ? 1 : 0;
          summary.complete = it->second.complete ? 1 : 0;
        }
      }
      slot->summaries[i] = summary;
    }
    slot->sequence.store(seq + 2, std::memory_order_release);
    return true;
  }

  void publishSharedPolicyLocked(std::shared_ptr<SharedCoordinatorHandle> handle, PolicyEntry& entry,
      const CandidateSpec& candidate) {
    if (!handle || handle->header == nullptr) return;
    SharedPublishedRecord* records = publishedRecords(handle->header);
    const uint32_t activeIndex = handle->header->activePublishedIndex.load(std::memory_order_acquire);
    const uint32_t nextIndex = (activeIndex + 1) % kSharedPublishedBuffers;
    SharedPublishedRecord* record = &records[nextIndex];
    const uint32_t seq = record->sequence.load(std::memory_order_relaxed);
    record->sequence.store(seq + 1, std::memory_order_release);
    record->generation = handle->header->generation;
    record->epoch = std::max(entry.lastPublishedEpoch, entry.active.epoch) + 1;
    storeCandidate(&record->candidate, candidate);
    record->recheckAfter = recheckAfter_;
    record->publishedCallIndex = entry.lastPlannedCallIndex;
    record->effectiveCallIndex = entry.lastPlannedCallIndex + activationLag_;
    record->valid = 1;
    record->sequence.store(seq + 2, std::memory_order_release);
    handle->header->activePublishedIndex.store(nextIndex, std::memory_order_release);
    entry.lastPublishedEpoch = record->epoch;
  }

  void clearSummarySlotsLocked(std::shared_ptr<SharedCoordinatorHandle> handle, uint64_t observedEpoch, uint64_t windowId) {
    if (!handle || handle->header == nullptr) return;
    SharedSummarySlot* slots = summarySlots(handle->header);
    for (uint32_t rank = 0; rank < handle->header->nRanks; ++rank) {
      SharedSummarySnapshot snapshot;
      if (!snapshotSummarySlot(&slots[rank], &snapshot)) continue;
      if (!snapshot.ready || snapshot.generation != handle->header->generation ||
          snapshot.observedEpoch != observedEpoch || snapshot.windowId != windowId) {
        continue;
      }
      uint32_t seq = slots[rank].sequence.load(std::memory_order_relaxed);
      slots[rank].sequence.store(seq + 1, std::memory_order_release);
      slots[rank].ready = 0;
      slots[rank].sequence.store(seq + 2, std::memory_order_release);
    }
  }

  bool aggregateAndPublishLocked(uint64_t commId, const PolicyKey& key, PolicyEntry& entry,
      uint64_t observedEpoch, uint64_t windowId) {
    std::shared_ptr<SharedCoordinatorHandle> handle = ensureCoordinatorLocked(commId, key, &entry);
    if (!handle || !handle->representative || handle->header == nullptr) return false;
    auto runtimeIt = communicators_.find(commId);
    ncclDebugLogger_t logfn = runtimeIt != communicators_.end() ? runtimeIt->second.logfn : nullptr;
    std::vector<CandidateSpec> candidates = candidatesForCollType(key.collType);
    std::array<uint64_t, kMaxSharedCandidates> sampleCounts{};
    std::array<double, kMaxSharedCandidates> latencySums{};
    std::array<bool, kMaxSharedCandidates> unavailable{};
    std::array<bool, kMaxSharedCandidates> complete{};
    SharedSummarySlot* slots = summarySlots(handle->header);

    for (uint32_t rank = 0; rank < handle->header->nRanks; ++rank) {
      SharedSummarySnapshot snapshot;
      if (!snapshotSummarySlot(&slots[rank], &snapshot) || !snapshot.ready ||
          snapshot.generation != handle->header->generation ||
          snapshot.observedEpoch != observedEpoch || snapshot.windowId != windowId) {
        if (logCoordinator_) {
          char keyText[ADAPTIVE_MAX_TEXT];
          keyToText(key, keyText, sizeof(keyText));
          ADAPTIVE_LOG(logfn, NCCL_LOG_INFO, NCCL_TUNING,
              "ADAPTIVE/coordinator wait-summary comm=%" PRIu64 " key=%s observed_epoch=%" PRIu64
              " window=%" PRIu64 " missing_rank=%u",
              commId, keyText, observedEpoch, windowId, rank);
        }
        return false;
      }
      for (size_t i = 0; i < candidates.size() && i < kMaxSharedCandidates; ++i) {
        const SharedCandidateSummary& summary = snapshot.summaries[i];
        sampleCounts[i] += summary.sampleCount;
        latencySums[i] += summary.latencySumUs;
        unavailable[i] = unavailable[i] || summary.unavailable != 0;
        complete[i] = complete[i] || summary.complete != 0;
      }
    }

    CandidateSpec currentCandidate = entry.active.valid ? entry.active.candidate : kDefaultCandidate;
    CandidateSpec nextCandidate = currentCandidate;
    bool foundBest = false;
    double bestLatency = 0.0;
    const uint64_t requiredSamples = minSamples_ * handle->header->nRanks;
    const uint64_t sustainedSamplesPerRank = std::max<uint64_t>(2, minSamples_);
    const uint64_t sustainedSamples = sustainedSamplesPerRank * handle->header->nRanks;
    for (size_t i = 0; i < candidates.size() && i < kMaxSharedCandidates; ++i) {
      if (unavailable[i] || !complete[i] || sampleCounts[i] < requiredSamples) continue;
      const double avgLatency = latencySums[i] / static_cast<double>(sampleCounts[i]);
      if (!foundBest || avgLatency < bestLatency) {
        foundBest = true;
        bestLatency = avgLatency;
        nextCandidate = candidates[i];
      }
    }

    if (entry.active.valid) {
      double currentLatency = 0.0;
      bool currentCovered = false;
      for (size_t i = 0; i < candidates.size() && i < kMaxSharedCandidates; ++i) {
        if (strcmp(candidates[i].name, currentCandidate.name) == 0) {
          currentCovered = complete[i] && sampleCounts[i] >= requiredSamples;
          currentLatency = currentCovered ? (latencySums[i] / static_cast<double>(sampleCounts[i])) : 0.0;
          if (unavailable[i]) {
            if (!foundBest) nextCandidate = kDefaultCandidate;
          } else if (foundBest && currentCovered && strcmp(nextCandidate.name, currentCandidate.name) != 0) {
            const double improvementPct = currentLatency > 0.0 ?
                ((currentLatency - bestLatency) / currentLatency) * 100.0 : 0.0;
            bool nextCovered = false;
            for (size_t j = 0; j < candidates.size() && j < kMaxSharedCandidates; ++j) {
              if (strcmp(candidates[j].name, nextCandidate.name) == 0) {
                nextCovered = complete[j] && sampleCounts[j] >= sustainedSamples;
                break;
              }
            }
            const bool sustainedAdvantage =
                currentCovered && sampleCounts[i] >= sustainedSamples && nextCovered;
            if (improvementPct < switchThresholdPct_ || !sustainedAdvantage) nextCandidate = currentCandidate;
          } else if (!foundBest) {
            nextCandidate = currentCandidate;
          }
          break;
        }
      }
    } else if (!foundBest) {
      nextCandidate = kDefaultCandidate;
    }

    publishSharedPolicyLocked(handle, entry, nextCandidate);
    if (logCoordinator_) {
      char keyText[ADAPTIVE_MAX_TEXT];
      keyToText(key, keyText, sizeof(keyText));
      ADAPTIVE_LOG(logfn, NCCL_LOG_INFO, NCCL_TUNING,
          "ADAPTIVE/coordinator publish comm=%" PRIu64 " key=%s observed_epoch=%" PRIu64
          " window=%" PRIu64 " next_epoch=%" PRIu64 " candidate=%s effective_call=%" PRIu64,
          commId, keyText, observedEpoch, windowId, entry.lastPublishedEpoch,
          nextCandidate.name != nullptr ? nextCandidate.name : kDefaultCandidate.name,
          entry.lastPlannedCallIndex + activationLag_);
    }
    clearSummarySlotsLocked(handle, observedEpoch, windowId);
    entry.pendingPublication = false;
    entry.pendingActivation = true;
    return true;
  }

  void finalizeWindowLocked(uint64_t commId, const PolicyKey& key, PolicyEntry& entry) {
    const ObservationWindow window = entry.window;
    entry.window = ObservationWindow{};
    entry.suspectUnavailable.clear();

    std::shared_ptr<SharedCoordinatorHandle> handle = ensureCoordinatorLocked(commId, key, &entry);
    auto runtimeIt = communicators_.find(commId);
    if (!handle || runtimeIt == communicators_.end()) {
      if (entry.active.valid) entry.callsUntilRecheck = recheckAfter_;
      return;
    }
    ncclDebugLogger_t logfn = runtimeIt->second.logfn;

    if (!writeSummarySlotLocked(handle, runtimeIt->second.rank, window)) {
      if (entry.active.valid) entry.callsUntilRecheck = recheckAfter_;
      return;
    }
    if (logCoordinator_) {
      char keyText[ADAPTIVE_MAX_TEXT];
      keyToText(key, keyText, sizeof(keyText));
      ADAPTIVE_LOG(logfn, NCCL_LOG_INFO, NCCL_TUNING,
          "ADAPTIVE/coordinator summary-ready comm=%" PRIu64 " key=%s rank=%d observed_epoch=%" PRIu64
          " window=%" PRIu64 " representative=%d",
          commId, keyText, runtimeIt->second.rank, window.observedEpoch, window.windowId,
          handle->representative ? 1 : 0);
    }

    entry.pendingObservedEpoch = window.observedEpoch;
    entry.pendingWindowId = window.windowId;
    entry.pendingPublication = true;
    entry.pendingActivation = false;
    tryPublishPendingLocked(commId, key, entry);
  }

  mutable std::mutex mutex_;
  std::unordered_map<DomainKey, PolicyEntry, DomainKeyHash> entries_;
  std::unordered_map<uint64_t, CommunicatorRuntime> communicators_;
  AdaptiveMode mode_ = AdaptiveMode::kWeakOnline;
  CandidateSpec staticCandidate_ = kDefaultCandidate;
  bool logDecisions_ = true;
  bool logCoordinator_ = false;
  bool logCompletion_ = false;
  size_t maxRecords_ = 256;
  uint64_t warmupSamplesPerCandidate_ = 1;
  uint64_t recheckSamplesPerCandidate_ = 1;
  uint64_t recheckAfter_ = 64;
  uint64_t minSamples_ = 1;
  uint64_t activationLag_ = 2;
  double switchThresholdPct_ = 2.0;
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
  bool shouldRecord = false;
  {
    std::lock_guard<std::mutex> lock(coll->mutex);
    const bool observedAllStartedKernelsStopped = coll->startedKernelChannels == coll->stoppedKernelChannels;
    if (coll->completionRecorded || !coll->hostStopped) return;
    if (coll->startedKernelChannels > 0 && !observedAllStartedKernelsStopped) return;
    coll->completionRecorded = true;
    const bool usedHostStopFallback = coll->lastKernelStopUsec == 0;
    const bool partialKernelCoverage = coll->startedKernelChannels > 0 && coll->startedKernelChannels < coll->nChannels;
    const uint64_t startUsec = coll->firstKernelStartUsec != 0 ? coll->firstKernelStartUsec : coll->startUsec;
    const uint64_t stopUsec = coll->lastKernelStopUsec != 0 ?
        coll->lastKernelStopUsec :
        (coll->hostStopUsec != 0 ? coll->hostStopUsec : nowUsec());
    const double latencyUs = stopUsec > startUsec ? static_cast<double>(stopUsec - startUsec) : 0.0;
    const double algbwGbps = safeBandwidthGbps(coll->nBytes, latencyUs);
    record.mode = modeName(PolicyStore::instance().mode());
    record.key = coll->key;
    record.commId = coll->commId;
    record.sequence = coll->sequence;
    record.phase = coll->phase;
    record.epoch = coll->epoch;
    record.windowId = coll->windowId;
    record.sampledWindow = coll->sampledWindow;
    record.unavailable = coll->unavailable;
    record.startedKernelChannels = coll->startedKernelChannels;
    record.stoppedKernelChannels = coll->stoppedKernelChannels;
    record.partialKernelCoverage = partialKernelCoverage;
    record.usedHostStopFallback = usedHostStopFallback;
    record.candidate = coll->phaseCandidate;
    record.selectedAlgo = coll->algo;
    record.selectedProto = coll->proto;
    record.selectedChannels = coll->nChannels;
    record.latencyUs = latencyUs;
    record.algbwGbps = algbwGbps;
    record.busbwGbps = busBandwidthGbps(coll->key.collType, coll->key.nRanks, algbwGbps);
    shouldRecord = coll->sampledWindow || coll->unavailable;
    if (PolicyStore::instance().logCompletion()) {
      char keyText[ADAPTIVE_MAX_TEXT];
      keyToText(coll->key, keyText, sizeof(keyText));
      ADAPTIVE_LOG(coll->context != nullptr ? coll->context->logfn : nullptr, NCCL_LOG_INFO, NCCL_TUNING,
          "ADAPTIVE/completion record-ready comm=%" PRIu64 " key=%s seq=%" PRIu64 " phase=%" PRIu64
          " attached=%d sampled=%d started=%d stopped=%d nchannels=%d partial=%d host_fallback=%d",
          coll->commId, keyText, coll->sequence, coll->phase, coll->planAttached ? 1 : 0,
          coll->sampledWindow ? 1 : 0, coll->startedKernelChannels, coll->stoppedKernelChannels,
          coll->nChannels, partialKernelCoverage ? 1 : 0, usedHostStopFallback ? 1 : 0);
    }
    ready = true;
  }
  if (ready && shouldRecord) {
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
  PolicyStore::instance().registerProfiler(commId, rank, nranks, nNodes, logfn);
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
    coll->commId = profilerContext->commId;
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
    PolicyStore::instance().attachProfilerPlan(profilerContext->commId, coll->key, coll);
    if (coll->phaseCandidate.empty()) coll->phaseCandidate = kDefaultCandidate.name;
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
      coll->hostStopUsec = nowUsec();
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
  if (profilerContext != nullptr) {
    if (gProfilerContexts.fetch_sub(1, std::memory_order_acq_rel) == 1) {
      PolicyStore::instance().dumpRecords(profilerContext->logfn);
    }
    PolicyStore::instance().unregisterCommunicator(profilerContext->commId);
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
  tunerContext->rank = parseRankEnv();
  tunerContext->nRanks = static_cast<int>(nRanks);
  tunerContext->nNodes = static_cast<int>(nNodes);
  tunerContext->logfn = logfn;
  *context = tunerContext;
  PolicyStore::instance().registerTuner(commId, tunerContext->rank, tunerContext->nRanks, tunerContext->nNodes, logfn);
  ADAPTIVE_LOG(logfn, NCCL_LOG_INFO, NCCL_TUNING,
      "ADAPTIVE/tuner init comm=%" PRIu64 " rank=%d nranks=%zu nnodes=%zu mode=%s",
      commId, tunerContext->rank, nRanks, nNodes, modeName(PolicyStore::instance().mode()));
  return ncclSuccess;
}

__hidden ncclResult_t adaptiveTunerGetCollInfo(void* context, ncclFunc_t collType, size_t nBytes,
    int numPipeOps, float** collCostTable, int numAlgo, int numProto, int regBuff, int* nChannels) {
  (void)numPipeOps;
  (void)regBuff;
  auto* tunerContext = static_cast<TunerContext*>(context);
  if (tunerContext == nullptr || collCostTable == nullptr || nChannels == nullptr) return ncclSuccess;

  const PolicyKey key = makeKey(collType, nBytes, tunerContext->nRanks, tunerContext->nNodes);
  SelectionPlan plan;
  if (!PolicyStore::instance().tryPlanSelection(tunerContext->commId, key, &plan)) {
    ADAPTIVE_LOG(tunerContext->logfn, NCCL_LOG_INFO, NCCL_TUNING,
        "ADAPTIVE/tuner fallback=contended key=%s", collTypeName(collType));
    return ncclSuccess;
  }

  if (PolicyStore::instance().mode() == AdaptiveMode::kDisabled) {
    return ncclSuccess;
  }

  const CandidateSpec candidate = plan.candidate.name != nullptr ? plan.candidate : kDefaultCandidate;
  if (candidate.algorithm >= 0 && candidate.protocol >= 0) {
    if (!candidateAvailable(candidate, collCostTable, numAlgo, numProto)) {
      PolicyStore::instance().tryMarkUnavailable(tunerContext->commId, key, candidate.name);
      ADAPTIVE_LOG(tunerContext->logfn, NCCL_LOG_INFO, NCCL_TUNING,
          "ADAPTIVE/tuner fallback=unavailable candidate=%s coll=%s bytes=%zu epoch=%" PRIu64 " window=%" PRIu64,
          candidate.name, collTypeName(collType), nBytes, plan.epoch, plan.windowId);
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
        "ADAPTIVE/decision comm=%" PRIu64 " key=%s phase=%" PRIu64 " epoch=%" PRIu64 " window=%" PRIu64 " sampled=%d candidate=%s rankset=%d/%d",
        tunerContext->commId, keyText, plan.callIndex, plan.epoch, plan.windowId, plan.sampledWindow ? 1 : 0,
        candidate.name, tunerContext->nRanks, tunerContext->nNodes);
  }

  return ncclSuccess;
}

__hidden ncclResult_t adaptiveTunerFinalize(void* context) {
  auto* tunerContext = static_cast<TunerContext*>(context);
  if (tunerContext != nullptr) {
    PolicyStore::instance().unregisterCommunicator(tunerContext->commId);
  }
  delete tunerContext;
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
