#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <all_reduce_perf> <plugin-dir> [extra benchmark args...]" >&2
  exit 1
fi

BENCH_BIN=$1
PLUGIN_DIR=$2
shift 2

PLUGIN_SO="${PLUGIN_DIR}/libnccl-adaptive.so"
RESULT_DIR="${RESULT_DIR:-${PLUGIN_DIR}/results}"
mkdir -p "${RESULT_DIR}"

record_env() {
  local mode=$1
  {
    echo "date=$(date -Iseconds)"
    echo "mode=${mode}"
    echo "hostname=$(hostname)"
    echo "pwd=$(pwd)"
    echo "NCCL_DEBUG=${NCCL_DEBUG:-}"
    echo "NCCL_DEBUG_SUBSYS=${NCCL_DEBUG_SUBSYS:-}"
    echo "NCCL_CUMEM_HOST_ENABLE=${NCCL_CUMEM_HOST_ENABLE:-}"
    echo "memlock=$(ulimit -l)"
    df -h /dev/shm || true
  } > "${RESULT_DIR}/${mode}.env"
}

run_mode() {
  local mode=$1
  shift
  echo "== ${mode} =="
  record_env "${mode}"
  "$BENCH_BIN" "$@" 2>&1 | tee "${RESULT_DIR}/${mode}.log"
}

COMMON_ARGS=("$@")

unset NCCL_PROFILER_PLUGIN NCCL_TUNER_PLUGIN NCCL_ADAPTIVE_MODE NCCL_ADAPTIVE_STATIC_CANDIDATE
run_mode baseline "${COMMON_ARGS[@]}"

export NCCL_PROFILER_PLUGIN="${PLUGIN_SO}"
unset NCCL_TUNER_PLUGIN NCCL_ADAPTIVE_MODE NCCL_ADAPTIVE_STATIC_CANDIDATE
run_mode profiler-only "${COMMON_ARGS[@]}"

export NCCL_PROFILER_PLUGIN="${PLUGIN_SO}"
export NCCL_TUNER_PLUGIN="${PLUGIN_SO}"
export NCCL_ADAPTIVE_MODE=static
export NCCL_ADAPTIVE_STATIC_CANDIDATE="${NCCL_ADAPTIVE_STATIC_CANDIDATE:-ring/simple}"
run_mode static-tuner "${COMMON_ARGS[@]}"

export NCCL_PROFILER_PLUGIN="${PLUGIN_SO}"
export NCCL_TUNER_PLUGIN="${PLUGIN_SO}"
export NCCL_ADAPTIVE_MODE=adaptive
unset NCCL_ADAPTIVE_STATIC_CANDIDATE
run_mode adaptive-tuner "${COMMON_ARGS[@]}"
