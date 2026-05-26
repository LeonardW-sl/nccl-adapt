#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd "${SCRIPT_DIR}/../../.." && pwd)
ANALYZER="${SCRIPT_DIR}/analyze_experiment_results.py"
IDLE_CHECK="${SCRIPT_DIR}/check_server_idle.sh"

CONTAINER_IMAGE="${CONTAINER_IMAGE:-nvcr.io/nvidia/pytorch:26.03-py3}"
CONTAINER_WORKDIR="/workspace/nccl-adapt"
CONTAINER_PLUGIN_DIR="${CONTAINER_WORKDIR}/nccl/plugins/adaptive"
EXPECTED_PLUGIN_PATH="${CONTAINER_PLUGIN_DIR}/libnccl-adaptive.so"
RUN_LABEL="${RUN_LABEL:-$(date +%F)-numa1-mechanism-cost-decomposition}"
RESULT_ROOT="${RESULT_ROOT:-${SCRIPT_DIR}/experiments/numa1-mechanism-cost-decomposition/${RUN_LABEL}}"
CONTAINER_RESULT_ROOT="${CONTAINER_PLUGIN_DIR}/experiments/numa1-mechanism-cost-decomposition/${RUN_LABEL}"

REPLICATES="${REPLICATES:-3}"
MODE_ORDER_STRATEGY="${MODE_ORDER_STRATEGY:-rotate}"
MODE_ORDER_SEED="${MODE_ORDER_SEED:-20260512}"
PRIMARY_MODE_SEQUENCE="${PRIMARY_MODE_SEQUENCE:-baseline,profiler-only,static-replay,final-steady}"
PRIMARY_STATIC_REPLAY_CANDIDATE="${PRIMARY_STATIC_REPLAY_CANDIDATE:-ring/simple}"
MODE_MESSAGE_MB="${MODE_MESSAGE_MB:-8}"
MODE_WARMUP_ITERS="${MODE_WARMUP_ITERS:-4}"
MODE_MEASURE_ITERS="${MODE_MEASURE_ITERS:-192}"

NCCL_DEBUG_VALUE="${NCCL_DEBUG_VALUE:-INFO}"
NCCL_DEBUG_SUBSYS_VALUE="${NCCL_DEBUG_SUBSYS_VALUE:-INIT,TUNING,COLL}"
NCCL_CUMEM_HOST_ENABLE_VALUE="${NCCL_CUMEM_HOST_ENABLE_VALUE:-0}"
NCCL_ADAPTIVE_WARMUP_SAMPLES_PER_CANDIDATE_VALUE="${NCCL_ADAPTIVE_WARMUP_SAMPLES_PER_CANDIDATE_VALUE:-1}"
NCCL_ADAPTIVE_RECHECK_SAMPLES_PER_CANDIDATE_VALUE="${NCCL_ADAPTIVE_RECHECK_SAMPLES_PER_CANDIDATE_VALUE:-1}"
NCCL_ADAPTIVE_MIN_SAMPLES_VALUE="${NCCL_ADAPTIVE_MIN_SAMPLES_VALUE:-1}"
NCCL_ADAPTIVE_SWITCH_THRESHOLD_PCT_VALUE="${NCCL_ADAPTIVE_SWITCH_THRESHOLD_PCT_VALUE:-2.0}"
NCCL_ADAPTIVE_ACTIVATION_LAG_VALUE="${NCCL_ADAPTIVE_ACTIVATION_LAG_VALUE:-2}"
NIC_INFINIBAND_DEVICE="${NIC_INFINIBAND_DEVICE:-mlx5_0}"

CONTAINER_IMAGE_ID=""
CONTAINER_IMAGE_DIGEST=""
ALIGNMENT_STATUS="pending"
LEARNED_CANDIDATE=""
CANDIDATE_ALIGNED_REPLAY_CANDIDATE=""
CANDIDATE_ALIGNED_REPLAY_DIR=""

group_cuda_visible_devices() {
  case "$1" in
    numa1-4gpu) printf '4,5,6,7' ;;
    *)
      echo "unknown topology group: $1" >&2
      exit 1
      ;;
  esac
}

group_nproc_per_node() {
  case "$1" in
    numa1-4gpu) printf '4' ;;
    *)
      echo "unknown topology group: $1" >&2
      exit 1
      ;;
  esac
}

group_cpu_affinity() {
  case "$1" in
    numa1-4gpu) printf '32-63,96-127' ;;
    *)
      echo "unknown topology group: $1" >&2
      exit 1
      ;;
  esac
}

group_numa_nodes() {
  case "$1" in
    numa1-4gpu) printf '1' ;;
    *)
      echo "unknown topology group: $1" >&2
      exit 1
      ;;
  esac
}

sanitize_candidate_name() {
  printf '%s' "$1" | tr '/ ' '__'
}

prepare_result_root() {
  if [[ -d "${RESULT_ROOT}" ]] && find "${RESULT_ROOT}" -mindepth 1 -print -quit | grep -q .; then
    echo "result root already exists and is not empty: ${RESULT_ROOT}" >&2
    echo "set RUN_LABEL or RESULT_ROOT to a fresh path before rerunning" >&2
    exit 1
  fi
  mkdir -p "${RESULT_ROOT}/host" "${RESULT_ROOT}/container"
}

record_host_topology() {
  nvidia-smi -L > "${RESULT_ROOT}/host/gpu-list.txt"
  nvidia-smi topo -m > "${RESULT_ROOT}/host/nvidia-smi-topo.txt"
  nvidia-smi --query-gpu=index,pci.bus_id,pcie.link.gen.current,pcie.link.width.current --format=csv \
    > "${RESULT_ROOT}/host/gpu-inventory.csv"
  numactl -H > "${RESULT_ROOT}/host/numactl-H.txt"
  lspci -Dnn | grep -i -E 'mellanox|ethernet|infiniband|network' \
    > "${RESULT_ROOT}/host/lspci-network.txt" || true
  ibdev2netdev > "${RESULT_ROOT}/host/ibdev2netdev.txt" 2>&1 || true

  if [[ -d "/sys/class/infiniband/${NIC_INFINIBAND_DEVICE}/device" ]]; then
    {
      echo "infiniband_device=${NIC_INFINIBAND_DEVICE}"
      echo "pci_bus_id=$(basename "$(readlink -f "/sys/class/infiniband/${NIC_INFINIBAND_DEVICE}/device")")"
      echo "numa_node=$(cat "/sys/class/infiniband/${NIC_INFINIBAND_DEVICE}/device/numa_node")"
      echo "local_cpulist=$(cat "/sys/class/infiniband/${NIC_INFINIBAND_DEVICE}/device/local_cpulist")"
      echo "net_devices=$(ls "/sys/class/infiniband/${NIC_INFINIBAND_DEVICE}/device/net" | paste -sd, -)"
    } > "${RESULT_ROOT}/host/nic-locality.txt"
  else
    {
      echo "infiniband_device=${NIC_INFINIBAND_DEVICE}"
      echo "status=missing"
    } > "${RESULT_ROOT}/host/nic-locality.txt"
  fi
}

ensure_container_image() {
  if ! docker image inspect "${CONTAINER_IMAGE}" >/dev/null 2>&1; then
    docker pull "${CONTAINER_IMAGE}"
  fi
  docker image inspect "${CONTAINER_IMAGE}" > "${RESULT_ROOT}/host/docker-image-inspect.json"
  CONTAINER_IMAGE_ID=$(python3 - "${RESULT_ROOT}/host/docker-image-inspect.json" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    payload = json.load(handle)
item = payload[0] if payload else {}
print(item.get("Id", ""))
PY
)
  CONTAINER_IMAGE_DIGEST=$(python3 - "${RESULT_ROOT}/host/docker-image-inspect.json" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    payload = json.load(handle)
item = payload[0] if payload else {}
digests = item.get("RepoDigests") or []
print(digests[0] if digests else "")
PY
)
}

container_base_args() {
  printf '%s\0' \
    docker run --rm --gpus all \
    --user "$(id -u):$(id -g)" \
    --ipc=host \
    --ulimit memlock=-1 \
    --ulimit stack=67108864 \
    -v "${PROJECT_ROOT}:${CONTAINER_WORKDIR}" \
    -w "${CONTAINER_WORKDIR}"
}

record_container_runtime() {
  local launch_args_text
  launch_args_text="--rm --gpus all --user $(id -u):$(id -g) --ipc=host --ulimit memlock=-1 --ulimit stack=67108864 -v ${PROJECT_ROOT}:${CONTAINER_WORKDIR} -w ${CONTAINER_WORKDIR}"
  printf '%s\n' "${launch_args_text}" > "${RESULT_ROOT}/container/launch-command.txt"

  local -a docker_cmd
  mapfile -d '' -t docker_cmd < <(container_base_args)
  docker_cmd+=("${CONTAINER_IMAGE}" bash -lc "$(cat <<EOF
set -euo pipefail
mkdir -p "${CONTAINER_RESULT_ROOT}/container"
pwd > "${CONTAINER_RESULT_ROOT}/container/workdir.txt"
python3 - <<'PY' > "${CONTAINER_RESULT_ROOT}/container/torch-runtime.json"
import json
import torch

payload = {
    "torch_version": torch.__version__,
    "cuda_available": bool(torch.cuda.is_available()),
    "cuda_device_count": int(torch.cuda.device_count()),
    "torch_cuda_version": torch.version.cuda,
}
print(json.dumps(payload, indent=2, sort_keys=True))
PY
ldconfig -p | grep libnccl > "${CONTAINER_RESULT_ROOT}/container/ldconfig-nccl.txt" || true
getconf GNU_LIBC_VERSION > "${CONTAINER_RESULT_ROOT}/container/glibc-version.txt" || true
EOF
)")
  "${docker_cmd[@]}"
}

run_batch() {
  local relative_result_dir=$1
  local topology_group=$2
  local mode_sequence=$3
  local static_replay_candidate=$4
  local cuda_visible_devices nproc_per_node cpu_affinity numa_nodes batch_label
  cuda_visible_devices=$(group_cuda_visible_devices "${topology_group}")
  nproc_per_node=$(group_nproc_per_node "${topology_group}")
  cpu_affinity=$(group_cpu_affinity "${topology_group}")
  numa_nodes=$(group_numa_nodes "${topology_group}")
  batch_label="${RUN_LABEL}-$(echo "${relative_result_dir}" | tr '/' '-')"

  mkdir -p "${RESULT_ROOT}/${relative_result_dir}"

  local -a docker_cmd
  mapfile -d '' -t docker_cmd < <(container_base_args)
  docker_cmd+=(
    -e "RESULT_DIR=${CONTAINER_RESULT_ROOT}/${relative_result_dir}"
    -e "RUN_LABEL=${batch_label}"
    -e "EXPERIMENT_TYPE=mode-comparison"
    -e "REPLICATES=${REPLICATES}"
    -e "MODE_ORDER_STRATEGY=${MODE_ORDER_STRATEGY}"
    -e "MODE_ORDER_SEED=${MODE_ORDER_SEED}"
    -e "MODE_SEQUENCE=${mode_sequence}"
    -e "STATIC_REPLAY_CANDIDATE=${static_replay_candidate}"
    -e "ADAPTIVE_MESSAGE_MB=${MODE_MESSAGE_MB}"
    -e "ADAPTIVE_WARMUP_ITERS=${MODE_WARMUP_ITERS}"
    -e "ADAPTIVE_MEASURE_ITERS=${MODE_MEASURE_ITERS}"
    -e "NCCL_DEBUG=${NCCL_DEBUG_VALUE}"
    -e "NCCL_DEBUG_SUBSYS=${NCCL_DEBUG_SUBSYS_VALUE}"
    -e "NCCL_CUMEM_HOST_ENABLE=${NCCL_CUMEM_HOST_ENABLE_VALUE}"
    -e "NCCL_ADAPTIVE_WARMUP_SAMPLES_PER_CANDIDATE=${NCCL_ADAPTIVE_WARMUP_SAMPLES_PER_CANDIDATE_VALUE}"
    -e "NCCL_ADAPTIVE_RECHECK_SAMPLES_PER_CANDIDATE=${NCCL_ADAPTIVE_RECHECK_SAMPLES_PER_CANDIDATE_VALUE}"
    -e "NCCL_ADAPTIVE_MIN_SAMPLES=${NCCL_ADAPTIVE_MIN_SAMPLES_VALUE}"
    -e "NCCL_ADAPTIVE_SWITCH_THRESHOLD_PCT=${NCCL_ADAPTIVE_SWITCH_THRESHOLD_PCT_VALUE}"
    -e "NCCL_ADAPTIVE_ACTIVATION_LAG=${NCCL_ADAPTIVE_ACTIVATION_LAG_VALUE}"
    -e "NCCL_ADAPTIVE_LOG_COORDINATOR=1"
    -e "NCCL_ADAPTIVE_LOG_COMPLETION=1"
    -e "CUDA_VISIBLE_DEVICES=${cuda_visible_devices}"
    -e "NPROC_PER_NODE=${nproc_per_node}"
    -e "TOPOLOGY_GROUP=${topology_group}"
    -e "TOPOLOGY_CPU_AFFINITY=${cpu_affinity}"
    -e "TOPOLOGY_NUMA_NODES=${numa_nodes}"
    -e "TOPOLOGY_CROSS_SOCKET=false"
    -e "CONTAINER_IMAGE_TAG=${CONTAINER_IMAGE}"
    -e "CONTAINER_IMAGE_ID=${CONTAINER_IMAGE_ID}"
    -e "CONTAINER_IMAGE_DIGEST=${CONTAINER_IMAGE_DIGEST}"
    -e "CONTAINER_WORKDIR=${CONTAINER_WORKDIR}"
    -e "CONTAINER_LAUNCH_ARGS=--rm --gpus all --user $(id -u):$(id -g) --ipc=host --ulimit memlock=-1 --ulimit stack=67108864 -v ${PROJECT_ROOT}:${CONTAINER_WORKDIR} -w ${CONTAINER_WORKDIR}"
  )
  docker_cmd+=("${CONTAINER_IMAGE}" bash -lc "${CONTAINER_PLUGIN_DIR}/run_torch_modes.sh ${CONTAINER_PLUGIN_DIR}")
  "${docker_cmd[@]}"
}

write_matrix_manifest() {
  RESULT_ROOT="${RESULT_ROOT}" \
  RUN_LABEL="${RUN_LABEL}" \
  CONTAINER_IMAGE="${CONTAINER_IMAGE}" \
  CONTAINER_IMAGE_ID="${CONTAINER_IMAGE_ID}" \
  CONTAINER_IMAGE_DIGEST="${CONTAINER_IMAGE_DIGEST}" \
  PRIMARY_MODE_SEQUENCE="${PRIMARY_MODE_SEQUENCE}" \
  PRIMARY_STATIC_REPLAY_CANDIDATE="${PRIMARY_STATIC_REPLAY_CANDIDATE}" \
  MODE_MESSAGE_MB="${MODE_MESSAGE_MB}" \
  MODE_WARMUP_ITERS="${MODE_WARMUP_ITERS}" \
  MODE_MEASURE_ITERS="${MODE_MEASURE_ITERS}" \
  MODE_ORDER_STRATEGY="${MODE_ORDER_STRATEGY}" \
  MODE_ORDER_SEED="${MODE_ORDER_SEED}" \
  REPLICATES="${REPLICATES}" \
  EXPECTED_PLUGIN_PATH="${EXPECTED_PLUGIN_PATH}" \
  NCCL_ADAPTIVE_WARMUP_SAMPLES_PER_CANDIDATE_VALUE="${NCCL_ADAPTIVE_WARMUP_SAMPLES_PER_CANDIDATE_VALUE}" \
  NCCL_ADAPTIVE_RECHECK_SAMPLES_PER_CANDIDATE_VALUE="${NCCL_ADAPTIVE_RECHECK_SAMPLES_PER_CANDIDATE_VALUE}" \
  NCCL_ADAPTIVE_MIN_SAMPLES_VALUE="${NCCL_ADAPTIVE_MIN_SAMPLES_VALUE}" \
  NCCL_ADAPTIVE_SWITCH_THRESHOLD_PCT_VALUE="${NCCL_ADAPTIVE_SWITCH_THRESHOLD_PCT_VALUE}" \
  NCCL_ADAPTIVE_ACTIVATION_LAG_VALUE="${NCCL_ADAPTIVE_ACTIVATION_LAG_VALUE}" \
  ALIGNMENT_STATUS="${ALIGNMENT_STATUS}" \
  LEARNED_CANDIDATE="${LEARNED_CANDIDATE}" \
  CANDIDATE_ALIGNED_REPLAY_CANDIDATE="${CANDIDATE_ALIGNED_REPLAY_CANDIDATE}" \
  CANDIDATE_ALIGNED_REPLAY_DIR="${CANDIDATE_ALIGNED_REPLAY_DIR}" \
  python3 - <<'PY'
import json
import os

payload = {
    "run_label": os.environ["RUN_LABEL"],
    "expected_plugin_path": os.environ["EXPECTED_PLUGIN_PATH"],
    "container_image": {
        "tag": os.environ["CONTAINER_IMAGE"],
        "id": os.environ["CONTAINER_IMAGE_ID"],
        "digest": os.environ["CONTAINER_IMAGE_DIGEST"],
    },
    "host_metadata": {
        "gpu_list": "host/gpu-list.txt",
        "gpu_inventory": "host/gpu-inventory.csv",
        "nvidia_smi_topo": "host/nvidia-smi-topo.txt",
        "numactl_h": "host/numactl-H.txt",
        "nic_locality": "host/nic-locality.txt",
        "lspci_network": "host/lspci-network.txt",
        "ibdev2netdev": "host/ibdev2netdev.txt",
        "server_idle_check": "host/server-idle-check.txt",
        "docker_image_inspect": "host/docker-image-inspect.json",
    },
    "container_metadata": {
        "launch_command": "container/launch-command.txt",
        "workdir": "container/workdir.txt",
        "torch_runtime": "container/torch-runtime.json",
        "ldconfig_nccl": "container/ldconfig-nccl.txt",
        "glibc_version": "container/glibc-version.txt",
    },
    "parameters": {
        "replicates": int(os.environ["REPLICATES"]),
        "mode_sequence": os.environ["PRIMARY_MODE_SEQUENCE"],
        "mode_message_mb": int(os.environ["MODE_MESSAGE_MB"]),
        "mode_warmup_iters": int(os.environ["MODE_WARMUP_ITERS"]),
        "mode_measure_iters": int(os.environ["MODE_MEASURE_ITERS"]),
        "mode_order_strategy": os.environ["MODE_ORDER_STRATEGY"],
        "mode_order_seed": int(os.environ["MODE_ORDER_SEED"]),
        "container_image_tag": os.environ["CONTAINER_IMAGE"],
        "static_replay_candidate": os.environ["PRIMARY_STATIC_REPLAY_CANDIDATE"],
        "candidate_alignment_policy": "default-primary-replay-then-rerun-if-final-steady-drifts",
        "adaptive_warmup_samples_per_candidate": int(os.environ["NCCL_ADAPTIVE_WARMUP_SAMPLES_PER_CANDIDATE_VALUE"]),
        "adaptive_recheck_samples_per_candidate": int(os.environ["NCCL_ADAPTIVE_RECHECK_SAMPLES_PER_CANDIDATE_VALUE"]),
        "adaptive_min_samples": int(os.environ["NCCL_ADAPTIVE_MIN_SAMPLES_VALUE"]),
        "adaptive_switch_threshold_pct": float(os.environ["NCCL_ADAPTIVE_SWITCH_THRESHOLD_PCT_VALUE"]),
        "adaptive_activation_lag": int(os.environ["NCCL_ADAPTIVE_ACTIVATION_LAG_VALUE"]),
        "log_coordinator": True,
        "log_completion": True,
    },
    "candidate_alignment": {
        "status": os.environ["ALIGNMENT_STATUS"],
        "final_steady_learned_candidate": os.environ["LEARNED_CANDIDATE"],
        "candidate_aligned_replay_candidate": os.environ["CANDIDATE_ALIGNED_REPLAY_CANDIDATE"],
    },
    "groups": {
        "numa1-4gpu": {
            "cuda_visible_devices": "4,5,6,7",
            "nproc_per_node": 4,
            "cpu_affinity": "32-63,96-127",
            "numa_nodes": "1",
            "cross_socket": False,
            "mode_comparison_dir": "mode-comparison/numa1-4gpu",
        },
    },
}

candidate_aligned_replay_dir = os.environ["CANDIDATE_ALIGNED_REPLAY_DIR"]
if candidate_aligned_replay_dir:
    payload["candidate_aligned_replay"] = {
        "result_dir": candidate_aligned_replay_dir,
        "mode_sequence": "static-replay",
        "static_replay_candidate": os.environ["CANDIDATE_ALIGNED_REPLAY_CANDIDATE"],
    }

with open(os.path.join(os.environ["RESULT_ROOT"], "matrix-manifest.json"), "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
}

read_alignment_state() {
  local comparison_summary=$1
  local requested_candidate=$2
  python3 - "${comparison_summary}" "${requested_candidate}" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    payload = json.load(handle)
requested = sys.argv[2]
final_steady = payload.get("modes", {}).get("final-steady", {})
candidates = sorted({str(item) for item in final_steady.get("activated_candidates", []) if item})
if not candidates:
    print("unknown")
    print("")
elif len(candidates) != 1:
    print("drift")
    print(",".join(candidates))
elif candidates[0] == requested:
    print("aligned")
    print(candidates[0])
else:
    print("mismatch")
    print(candidates[0])
PY
}

main() {
  prepare_result_root

  if ! "${IDLE_CHECK}" > "${RESULT_ROOT}/host/server-idle-check.txt"; then
    echo "server is busy; refusing to start experiments" >&2
    cat "${RESULT_ROOT}/host/server-idle-check.txt" >&2
    exit 2
  fi

  record_host_topology
  make -C "${SCRIPT_DIR}"
  ensure_container_image
  record_container_runtime
  write_matrix_manifest

  run_batch "mode-comparison/numa1-4gpu" "numa1-4gpu" "${PRIMARY_MODE_SEQUENCE}" "${PRIMARY_STATIC_REPLAY_CANDIDATE}"

  local comparison_summary="${RESULT_ROOT}/mode-comparison/numa1-4gpu/comparison-summary.json"
  mapfile -t alignment_info < <(read_alignment_state "${comparison_summary}" "${PRIMARY_STATIC_REPLAY_CANDIDATE}")
  ALIGNMENT_STATUS="${alignment_info[0]:-unknown}"
  LEARNED_CANDIDATE="${alignment_info[1]:-}"

  if [[ "${ALIGNMENT_STATUS}" == "mismatch" && -n "${LEARNED_CANDIDATE}" && "${LEARNED_CANDIDATE}" != *","* ]]; then
    CANDIDATE_ALIGNED_REPLAY_CANDIDATE="${LEARNED_CANDIDATE}"
    CANDIDATE_ALIGNED_REPLAY_DIR="candidate-aligned-replay/numa1-4gpu/$(sanitize_candidate_name "${LEARNED_CANDIDATE}")"
    run_batch "${CANDIDATE_ALIGNED_REPLAY_DIR}" "numa1-4gpu" "static-replay" "${LEARNED_CANDIDATE}"
    ALIGNMENT_STATUS="aligned-via-supplemental-replay"
  fi

  write_matrix_manifest
  python3 "${ANALYZER}" aggregate-numa1-mechanism-decomposition \
    --manifest "${RESULT_ROOT}/matrix-manifest.json" \
    --output "${RESULT_ROOT}/numa1-mechanism-summary.json"
}

main "$@"
