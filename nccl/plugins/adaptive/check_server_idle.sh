#!/usr/bin/env bash
set -euo pipefail

trim() {
  local value=$1
  value=${value#"${value%%[![:space:]]*}"}
  value=${value%"${value##*[![:space:]]}"}
  printf '%s' "${value}"
}

join_by() {
  local delimiter=$1
  shift || true
  local joined=""
  local item
  for item in "$@"; do
    if [[ -n "${joined}" ]]; then
      joined+="${delimiter}"
    fi
    joined+="${item}"
  done
  printf '%s' "${joined}"
}

CURRENT_USER=$(id -un)
TIMESTAMP=$(date -Iseconds)
POLICY="${SERVER_IDLE_POLICY:-compute-only}"

mapfile -t LOGGED_IN_USERS < <(who | awk '{print $1}' | sort -u)
OTHER_USERS=()
if [[ ${#LOGGED_IN_USERS[@]} -gt 0 ]]; then
  for user_name in "${LOGGED_IN_USERS[@]}"; do
    if [[ -n "${user_name}" && "${user_name}" != "${CURRENT_USER}" ]]; then
      OTHER_USERS+=("${user_name}")
    fi
  done
fi

GPU_PROCESSES=()
if command -v nvidia-smi >/dev/null 2>&1; then
  while IFS= read -r raw_line; do
    [[ -z "${raw_line// /}" ]] && continue
    IFS=',' read -r raw_pid raw_process raw_gpu_uuid raw_used_memory <<<"${raw_line}"
    pid=$(trim "${raw_pid}")
    process_name=$(trim "${raw_process}")
    gpu_uuid=$(trim "${raw_gpu_uuid}")
    used_memory=$(trim "${raw_used_memory}")
    owner=$(ps -o user= -p "${pid}" 2>/dev/null | xargs || true)
    if [[ -z "${owner}" ]]; then
      owner="unknown"
    fi
    GPU_PROCESSES+=("${pid}:${owner}:${process_name}:${gpu_uuid}:${used_memory}MiB")
  done < <(
    nvidia-smi --query-compute-apps=pid,process_name,gpu_uuid,used_gpu_memory \
      --format=csv,noheader,nounits 2>/dev/null || true
  )
fi

STATUS="idle"
REASONS=()
if [[ "${POLICY}" == "strict-users-and-gpu" && ${#OTHER_USERS[@]} -gt 0 ]]; then
  STATUS="busy"
  REASONS+=("other-users-logged-in")
fi
if [[ ${#GPU_PROCESSES[@]} -gt 0 ]]; then
  STATUS="busy"
  REASONS+=("gpu-compute-processes-detected")
fi

echo "timestamp=${TIMESTAMP}"
echo "current_user=${CURRENT_USER}"
echo "logged_in_users=$(join_by "," "${LOGGED_IN_USERS[@]}")"
echo "other_users=$(join_by "," "${OTHER_USERS[@]}")"
echo "gpu_process_count=${#GPU_PROCESSES[@]}"
echo "gpu_processes=$(join_by ";" "${GPU_PROCESSES[@]}")"
echo "policy=${POLICY}"
echo "status=${STATUS}"
echo "reasons=$(join_by "," "${REASONS[@]}")"

if [[ "${STATUS}" != "idle" ]]; then
  exit 2
fi
