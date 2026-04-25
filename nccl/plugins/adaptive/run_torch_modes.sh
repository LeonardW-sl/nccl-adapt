#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <plugin-dir> [torchrun args...]" >&2
  exit 1
fi

PLUGIN_DIR=$1
shift

PLUGIN_SO="${PLUGIN_DIR}/libnccl-adaptive.so"
RESULT_DIR="${RESULT_DIR:-${PLUGIN_DIR}/results-torch}"
NNODES="${NNODES:-1}"
NPROC_PER_NODE="${NPROC_PER_NODE:-8}"
MASTER_ADDR="${MASTER_ADDR:-127.0.0.1}"
MASTER_PORT="${MASTER_PORT:-29500}"
mkdir -p "${RESULT_DIR}"

record_env() {
  local mode=$1
  {
    echo "date=$(date -Iseconds)"
    echo "mode=${mode}"
    echo "hostname=$(hostname)"
    echo "pwd=$(pwd)"
    echo "NNODES=${NNODES}"
    echo "NPROC_PER_NODE=${NPROC_PER_NODE}"
    echo "MASTER_ADDR=${MASTER_ADDR}"
    echo "MASTER_PORT=${MASTER_PORT}"
    echo "NCCL_DEBUG=${NCCL_DEBUG:-}"
    echo "NCCL_DEBUG_SUBSYS=${NCCL_DEBUG_SUBSYS:-}"
    echo "NCCL_CUMEM_HOST_ENABLE=${NCCL_CUMEM_HOST_ENABLE:-}"
    echo "ADAPTIVE_MESSAGE_MB=${ADAPTIVE_MESSAGE_MB:-}"
    echo "ADAPTIVE_WARMUP_ITERS=${ADAPTIVE_WARMUP_ITERS:-}"
    echo "ADAPTIVE_MEASURE_ITERS=${ADAPTIVE_MEASURE_ITERS:-}"
    echo "memlock=$(ulimit -l)"
    df -h /dev/shm || true
  } > "${RESULT_DIR}/${mode}.env"
}

run_mode() {
  local mode=$1
  shift
  echo "== ${mode} =="
  record_env "${mode}"
  torchrun \
    --nnodes="${NNODES}" \
    --nproc-per-node="${NPROC_PER_NODE}" \
    --master-addr="${MASTER_ADDR}" \
    --master-port="${MASTER_PORT}" \
    "${PLUGIN_DIR}/torch_allreduce_smoke.py" "$@" 2>&1 | tee "${RESULT_DIR}/${mode}.log"
}

unset NCCL_PROFILER_PLUGIN NCCL_TUNER_PLUGIN NCCL_ADAPTIVE_MODE NCCL_ADAPTIVE_STATIC_CANDIDATE
run_mode baseline "$@"

export NCCL_PROFILER_PLUGIN="${PLUGIN_SO}"
unset NCCL_TUNER_PLUGIN NCCL_ADAPTIVE_MODE NCCL_ADAPTIVE_STATIC_CANDIDATE
run_mode profiler-only "$@"

export NCCL_PROFILER_PLUGIN="${PLUGIN_SO}"
export NCCL_TUNER_PLUGIN="${PLUGIN_SO}"
export NCCL_ADAPTIVE_MODE=static
export NCCL_ADAPTIVE_STATIC_CANDIDATE="${NCCL_ADAPTIVE_STATIC_CANDIDATE:-ring/simple}"
run_mode static-tuner "$@"

export NCCL_PROFILER_PLUGIN="${PLUGIN_SO}"
export NCCL_TUNER_PLUGIN="${PLUGIN_SO}"
export NCCL_ADAPTIVE_MODE=adaptive
unset NCCL_ADAPTIVE_STATIC_CANDIDATE
run_mode adaptive-tuner "$@"
