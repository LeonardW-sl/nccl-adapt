#ifndef NCCL_ADAPTIVE_TUNER_COMPAT_H_
#define NCCL_ADAPTIVE_TUNER_COMPAT_H_

#include <stdint.h>
#include <stdlib.h>

typedef enum {
  ncclFuncBroadcast = 0,
  ncclFuncReduce = 1,
  ncclFuncAllGather = 2,
  ncclFuncReduceScatter = 3,
  ncclFuncAllReduce = 4,
  ncclFuncSendRecv = 5,
  ncclFuncSend = 6,
  ncclFuncRecv = 7,
  ncclNumFuncs = 8
} ncclFunc_t;

#define NCCL_NUM_ALGORITHMS 7
#define NCCL_ALGO_UNDEF -1
#define NCCL_ALGO_TREE 0
#define NCCL_ALGO_RING 1
#define NCCL_ALGO_COLLNET_DIRECT 2
#define NCCL_ALGO_COLLNET_CHAIN 3
#define NCCL_ALGO_NVLS 4
#define NCCL_ALGO_NVLS_TREE 5
#define NCCL_ALGO_PAT 6

#define NCCL_NUM_PROTOCOLS 3
#define NCCL_PROTO_UNDEF -1
#define NCCL_PROTO_LL 0
#define NCCL_PROTO_LL128 1
#define NCCL_PROTO_SIMPLE 2

#define NCCL_ALGO_PROTO_IGNORE -1.0

#define NCCL_HW_NVLINK 0
#define NCCL_HW_PCI 1
#define NCCL_HW_NET 2
#define NCCL_NUM_HW_LINKS 3

#define NCCL_VOLTA_COMPCAP_IDX 0
#define NCCL_AMPERE_COMPCAP_IDX 1
#define NCCL_HOPPER_COMPCAP_IDX 2
#define NCCL_BLACKWELL_COMPCAP_IDX 3
#define NCCL_NUM_COMPCAPS 4

#define NCCL_TUNING_SCALE_1NODE 0
#define NCCL_TUNING_SCALE_2NODES 1
#define NCCL_TUNING_SCALE_4NODES 2
#define NCCL_NUM_TUNING_SCALES 3

typedef struct {
  int nNvlDomains;
  int minRanksPerNvlDomain;
  int maxRanksPerNvlDomain;
} ncclNvlDomainInfo_v5_t;

typedef struct {
  double baseLatencies[NCCL_NUM_ALGORITHMS][NCCL_NUM_PROTOCOLS];
  double hwLatencies[NCCL_NUM_HW_LINKS][NCCL_NUM_ALGORITHMS][NCCL_NUM_PROTOCOLS];
  double llMaxBws[NCCL_NUM_COMPCAPS][NCCL_NUM_TUNING_SCALES];
  double perChMaxRingLL128Bws[NCCL_NUM_COMPCAPS][NCCL_NUM_TUNING_SCALES];
  double perChMaxTreeLL128Bws[NCCL_NUM_COMPCAPS][NCCL_NUM_TUNING_SCALES];
  double perChMaxTreeBws[NCCL_NUM_COMPCAPS][NCCL_NUM_TUNING_SCALES];
} ncclTunerConstants_v5_t;

typedef struct {
  const char* name;
  ncclResult_t (*init)(void** ctx, uint64_t commId, size_t nRanks, size_t nNodes,
      ncclDebugLogger_t logFunction, ncclNvlDomainInfo_v5_t* nvlDomainInfo,
      ncclTunerConstants_v5_t* constants);
  ncclResult_t (*getCollInfo)(void* context, ncclFunc_t collType, size_t nBytes,
      int numPipeOps, float** collCostTable, int numAlgo, int numProto,
      int regBuff, int* nChannels);
  ncclResult_t (*finalize)(void* context);
} ncclTuner_v5_t;

#endif
