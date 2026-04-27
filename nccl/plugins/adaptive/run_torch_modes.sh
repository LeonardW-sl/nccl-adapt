#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <plugin-dir> [torchrun args...]" >&2
  exit 1
fi

PLUGIN_DIR=$1
shift

PLUGIN_SO="${PLUGIN_DIR}/libnccl-adaptive.so"
ANALYZER="${PLUGIN_DIR}/analyze_experiment_results.py"
NNODES="${NNODES:-1}"
NPROC_PER_NODE="${NPROC_PER_NODE:-8}"
MASTER_ADDR="${MASTER_ADDR:-127.0.0.1}"
MASTER_PORT="${MASTER_PORT:-29500}"
EXPERIMENT_TYPE="${EXPERIMENT_TYPE:-mode-comparison}"
REPLICATES="${REPLICATES:-3}"
MODE_ORDER_STRATEGY="${MODE_ORDER_STRATEGY:-rotate}"
MODE_ORDER_SEED="${MODE_ORDER_SEED:-20260426}"
RUN_LABEL="${RUN_LABEL:-$(date +%F)-torch-${EXPERIMENT_TYPE}}"
STATIC_REPLAY_CANDIDATE="${STATIC_REPLAY_CANDIDATE:-ring/simple}"
SIZE_SWEEP_MBS="${SIZE_SWEEP_MBS:-}"
SWEEP_MODE="${SWEEP_MODE:-weak-online}"
COMMON_ARGS=("$@")

default_category_for_type() {
  case "$1" in
    mode-comparison) echo "mode-comparison" ;;
    correctness) echo "correctness" ;;
    policy-quality) echo "policy-quality" ;;
    state-granularity) echo "state-granularity" ;;
    *)
      echo "unknown EXPERIMENT_TYPE: $1" >&2
      exit 1
      ;;
  esac
}

RESULT_CATEGORY="$(default_category_for_type "${EXPERIMENT_TYPE}")"
RESULT_DIR="${RESULT_DIR:-${PLUGIN_DIR}/experiments/${RESULT_CATEGORY}/${RUN_LABEL}}"
mkdir -p "${RESULT_DIR}"

candidate_count() {
  echo "${ADAPTIVE_CANDIDATE_COUNT:-4}"
}

split_csv() {
  local raw=$1
  IFS=',' read -r -a SPLIT_RESULT <<<"${raw}"
}

join_csv() {
  local -n values_ref=$1
  local joined=""
  local value
  for value in "${values_ref[@]}"; do
    if [[ -n "${joined}" ]]; then
      joined+=","
    fi
    joined+="${value}"
  done
  printf '%s' "${joined}"
}

default_modes_for_type() {
  case "$1" in
    mode-comparison) echo "baseline,profiler-only,final-steady,weak-online" ;;
    correctness) echo "final-steady,weak-online" ;;
    policy-quality) echo "baseline,static-replay" ;;
    state-granularity) echo "${SWEEP_MODE}" ;;
  esac
}

MODE_SEQUENCE="${MODE_SEQUENCE:-$(default_modes_for_type "${EXPERIMENT_TYPE}")}"
split_csv "${MODE_SEQUENCE}"
BASE_MODES=("${SPLIT_RESULT[@]}")
if [[ ${#BASE_MODES[@]} -eq 0 ]]; then
  echo "MODE_SEQUENCE must not be empty" >&2
  exit 1
fi

if [[ "${EXPERIMENT_TYPE}" == "state-granularity" && -z "${SIZE_SWEEP_MBS}" ]]; then
  echo "SIZE_SWEEP_MBS is required for EXPERIMENT_TYPE=state-granularity" >&2
  exit 1
fi

bucket_text_for_message_mb() {
  local message_mb=$1
  python3 - "${message_mb}" <<'PY'
import math
import sys

message_mb = max(1, int(sys.argv[1]))
upper = 1
while upper < message_mb:
    upper *= 2
lower = max(1, upper // 2)
print(f"{lower}-{upper}MiB")
PY
}

mode_env_name() {
  case "$1" in
    baseline) echo "disabled" ;;
    profiler-only) echo "disabled" ;;
    final-steady) echo "final-steady" ;;
    weak-online) echo "weak-online" ;;
    static-replay) echo "static" ;;
    *)
      echo "unknown mode: $1" >&2
      exit 1
      ;;
  esac
}

ordered_values_for_replicate() {
  local replicate_id=$1
  shift
  local values=("$@")
  case "${MODE_ORDER_STRATEGY}" in
    fixed)
      printf '%s\n' "${values[@]}"
      ;;
    rotate)
      python3 - "${replicate_id}" "${values[@]}" <<'PY'
import sys

replicate_id = int(sys.argv[1])
values = sys.argv[2:]
if not values:
    raise SystemExit(0)
offset = (replicate_id - 1) % len(values)
ordered = values[offset:] + values[:offset]
for value in ordered:
    print(value)
PY
      ;;
    random)
      python3 - "${MODE_ORDER_SEED}" "${replicate_id}" "${values[@]}" <<'PY'
import random
import sys

seed = sys.argv[1]
replicate_id = sys.argv[2]
values = sys.argv[3:]
rng = random.Random(f"{seed}:{replicate_id}")
rng.shuffle(values)
for value in values:
    print(value)
PY
      ;;
    *)
      echo "unsupported MODE_ORDER_STRATEGY: ${MODE_ORDER_STRATEGY}" >&2
      exit 1
      ;;
  esac
}

record_env() {
  local run_dir=$1
  local mode=$2
  {
    echo "date=$(date -Iseconds)"
    echo "experiment_type=${EXPERIMENT_TYPE}"
    echo "mode=${mode}"
    echo "hostname=$(hostname)"
    echo "pwd=$(pwd)"
    echo "NNODES=${NNODES}"
    echo "NPROC_PER_NODE=${NPROC_PER_NODE}"
    echo "MASTER_ADDR=${MASTER_ADDR}"
    echo "MASTER_PORT=${MASTER_PORT}"
    echo "ADAPTIVE_MESSAGE_MB=${ADAPTIVE_MESSAGE_MB:-}"
    echo "ADAPTIVE_WARMUP_ITERS=${ADAPTIVE_WARMUP_ITERS:-}"
    echo "ADAPTIVE_MEASURE_ITERS=${ADAPTIVE_MEASURE_ITERS:-}"
    echo "NCCL_DEBUG=${NCCL_DEBUG:-}"
    echo "NCCL_DEBUG_SUBSYS=${NCCL_DEBUG_SUBSYS:-}"
    echo "NCCL_CUMEM_HOST_ENABLE=${NCCL_CUMEM_HOST_ENABLE:-}"
    echo "NCCL_ADAPTIVE_MODE=${NCCL_ADAPTIVE_MODE:-}"
    echo "NCCL_ADAPTIVE_STATIC_CANDIDATE=${NCCL_ADAPTIVE_STATIC_CANDIDATE:-}"
    echo "NCCL_ADAPTIVE_WARMUP_SAMPLES_PER_CANDIDATE=${NCCL_ADAPTIVE_WARMUP_SAMPLES_PER_CANDIDATE:-}"
    echo "NCCL_ADAPTIVE_RECHECK_SAMPLES_PER_CANDIDATE=${NCCL_ADAPTIVE_RECHECK_SAMPLES_PER_CANDIDATE:-}"
    echo "NCCL_ADAPTIVE_RECHECK_AFTER=${NCCL_ADAPTIVE_RECHECK_AFTER:-}"
    echo "NCCL_ADAPTIVE_MIN_SAMPLES=${NCCL_ADAPTIVE_MIN_SAMPLES:-}"
    echo "NCCL_ADAPTIVE_SWITCH_THRESHOLD_PCT=${NCCL_ADAPTIVE_SWITCH_THRESHOLD_PCT:-}"
    echo "NCCL_ADAPTIVE_ACTIVATION_LAG=${NCCL_ADAPTIVE_ACTIVATION_LAG:-}"
    echo "NCCL_ADAPTIVE_LOG_COORDINATOR=${NCCL_ADAPTIVE_LOG_COORDINATOR:-}"
    echo "NCCL_ADAPTIVE_LOG_COMPLETION=${NCCL_ADAPTIVE_LOG_COMPLETION:-}"
    echo "memlock=$(ulimit -l)"
    df -h /dev/shm || true
  } > "${run_dir}/env.txt"
}

write_json_file() {
  local output_path=$1
  shift
  python3 - "${output_path}" "$@" <<'PY'
import json
import sys

output_path = sys.argv[1]
pairs = sys.argv[2:]
payload = {}
for pair in pairs:
    key, value = pair.split("=", 1)
    if value.isdigit():
        payload[key] = int(value)
    elif value in {"true", "false"}:
        payload[key] = value == "true"
    else:
        payload[key] = value
with open(output_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
}

write_manifest() {
  local modes_csv sizes_csv
  modes_csv=$(join_csv BASE_MODES)
  sizes_csv="${SIZE_SWEEP_MBS}"
  write_json_file "${RESULT_DIR}/manifest.json" \
    "experiment_type=${EXPERIMENT_TYPE}" \
    "result_category=${RESULT_CATEGORY}" \
    "run_label=${RUN_LABEL}" \
    "replicates=${REPLICATES}" \
    "mode_order_strategy=${MODE_ORDER_STRATEGY}" \
    "mode_order_seed=${MODE_ORDER_SEED}" \
    "mode_sequence=${modes_csv}" \
    "size_sweep_mbs=${sizes_csv}" \
    "sweep_mode=${SWEEP_MODE}" \
    "nnodes=${NNODES}" \
    "nproc_per_node=${NPROC_PER_NODE}" \
    "master_addr=${MASTER_ADDR}" \
    "master_port=${MASTER_PORT}" \
    "static_replay_candidate=${STATIC_REPLAY_CANDIDATE}"
}

run_mode() {
  local replicate_id=$1
  local run_order=$2
  local mode=$3
  local message_mb=$4
  shift 4

  local mode_env size_bucket run_dir log_path metadata_path
  mode_env=$(mode_env_name "${mode}")
  size_bucket=$(bucket_text_for_message_mb "${message_mb}")
  run_dir="${RESULT_DIR}/replicate-$(printf '%02d' "${replicate_id}")/run-$(printf '%02d' "${run_order}")-${mode}"
  mkdir -p "${run_dir}"
  log_path="${run_dir}/stdout.log"
  metadata_path="${run_dir}/metadata.json"

  export ADAPTIVE_MESSAGE_MB="${message_mb}"
  export ADAPTIVE_EXPERIMENT_TYPE="${EXPERIMENT_TYPE}"
  export ADAPTIVE_EXPERIMENT_MODE_NAME="${mode}"
  export ADAPTIVE_REPLICATE_ID="${replicate_id}"
  export ADAPTIVE_RUN_ORDER="${run_order}"
  export ADAPTIVE_SIZE_BUCKET="${size_bucket}"
  export ADAPTIVE_CANDIDATE_COUNT="$(candidate_count)"

  unset NCCL_PROFILER_PLUGIN NCCL_TUNER_PLUGIN NCCL_ADAPTIVE_MODE NCCL_ADAPTIVE_STATIC_CANDIDATE
  unset NCCL_ADAPTIVE_RECHECK_AFTER

  case "${mode}" in
    baseline)
      ;;
    profiler-only)
      export NCCL_PROFILER_PLUGIN="${PLUGIN_SO}"
      ;;
    final-steady)
      export NCCL_PROFILER_PLUGIN="${PLUGIN_SO}"
      export NCCL_TUNER_PLUGIN="${PLUGIN_SO}"
      export NCCL_ADAPTIVE_MODE="final-steady"
      export NCCL_ADAPTIVE_RECHECK_AFTER=0
      ;;
    weak-online)
      export NCCL_PROFILER_PLUGIN="${PLUGIN_SO}"
      export NCCL_TUNER_PLUGIN="${PLUGIN_SO}"
      export NCCL_ADAPTIVE_MODE="weak-online"
      ;;
    static-replay)
      export NCCL_PROFILER_PLUGIN="${PLUGIN_SO}"
      export NCCL_TUNER_PLUGIN="${PLUGIN_SO}"
      export NCCL_ADAPTIVE_MODE="static"
      export NCCL_ADAPTIVE_STATIC_CANDIDATE="${STATIC_REPLAY_CANDIDATE}"
      ;;
  esac

  if [[ "${EXPERIMENT_TYPE}" == "state-granularity" && -z "${NCCL_ADAPTIVE_LOG_COORDINATOR:-}" ]]; then
    export NCCL_ADAPTIVE_LOG_COORDINATOR=1
  fi

  record_env "${run_dir}" "${mode}"
  write_json_file "${metadata_path}" \
    "experiment_type=${EXPERIMENT_TYPE}" \
    "mode=${mode}" \
    "mode_env=${mode_env}" \
    "replicate_id=${replicate_id}" \
    "run_order=${run_order}" \
    "message_mb=${message_mb}" \
    "size_bucket=${size_bucket}" \
    "nnodes=${NNODES}" \
    "nproc_per_node=${NPROC_PER_NODE}" \
    "static_replay_candidate=${STATIC_REPLAY_CANDIDATE}" \
    "torch_args=${COMMON_ARGS[*]}"

  echo "== replicate ${replicate_id} run ${run_order}: ${mode} (${message_mb} MiB) =="
  torchrun \
    --nnodes="${NNODES}" \
    --nproc-per-node="${NPROC_PER_NODE}" \
    --master-addr="${MASTER_ADDR}" \
    --master-port="${MASTER_PORT}" \
    "${PLUGIN_DIR}/torch_allreduce_smoke.py" \
    "${COMMON_ARGS[@]}" 2>&1 | tee "${log_path}"

  python3 "${ANALYZER}" summarize-run \
    --log "${log_path}" \
    --metadata "${metadata_path}" \
    --output "${run_dir}/summary.json" \
    --trajectory-output "${run_dir}/trajectory.json"
}

run_matrix() {
  local replicate_id run_order ordered_csv
  for ((replicate_id = 1; replicate_id <= REPLICATES; ++replicate_id)); do
    mapfile -t ORDERED_MODES < <(ordered_values_for_replicate "${replicate_id}" "${BASE_MODES[@]}")
    run_order=1
    local mode
    for mode in "${ORDERED_MODES[@]}"; do
      run_mode "${replicate_id}" "${run_order}" "${mode}" "${ADAPTIVE_MESSAGE_MB:-8}"
      run_order=$((run_order + 1))
    done
  done
}

run_size_sweep() {
  local replicate_id run_order
  split_csv "${SIZE_SWEEP_MBS}"
  BASE_SIZES=("${SPLIT_RESULT[@]}")
  for ((replicate_id = 1; replicate_id <= REPLICATES; ++replicate_id)); do
    mapfile -t ORDERED_SIZES < <(ordered_values_for_replicate "${replicate_id}" "${BASE_SIZES[@]}")
    run_order=1
    local size_mb
    for size_mb in "${ORDERED_SIZES[@]}"; do
      run_mode "${replicate_id}" "${run_order}" "${SWEEP_MODE}" "${size_mb}"
      run_order=$((run_order + 1))
    done
  done
}

write_manifest

case "${EXPERIMENT_TYPE}" in
  mode-comparison|correctness|policy-quality)
    run_matrix
    python3 "${ANALYZER}" aggregate-mode-comparison \
      --result-dir "${RESULT_DIR}" \
      --experiment-type "${EXPERIMENT_TYPE}" \
      --output "${RESULT_DIR}/comparison-summary.json"
    ;;
  state-granularity)
    run_size_sweep
    python3 "${ANALYZER}" aggregate-size-sweep \
      --result-dir "${RESULT_DIR}" \
      --experiment-type "${EXPERIMENT_TYPE}" \
      --output "${RESULT_DIR}/candidate-trajectories.json"
    ;;
esac
