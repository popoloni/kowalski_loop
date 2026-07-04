#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ -f "env/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "env/bin/activate"
fi

mkdir -p logs

WATCHDOG_PATTERN="llmstack\\.cli serve --watchdog"
WATCHDOG_PID_FILE="logs/inference_watchdog.pid"

if [[ -f "${WATCHDOG_PID_FILE}" ]]; then
  existing_pid="$(tr -d '[:space:]' < "${WATCHDOG_PID_FILE}")"
  if [[ -n "${existing_pid}" ]] && ps -p "${existing_pid}" >/dev/null 2>&1; then
    cmdline="$(ps -ww -p "${existing_pid}" -o command= || true)"
    if [[ "${cmdline}" == *"llmstack.cli serve --watchdog"* ]]; then
      echo "Inference watchdog is already running (PID ${existing_pid})."
      exit 0
    fi
  fi
  rm -f "${WATCHDOG_PID_FILE}"
fi

if pgrep -f "${WATCHDOG_PATTERN}" >/dev/null 2>&1; then
  echo "Inference watchdog is already running (detected via process scan)."
  exit 0
fi

PYTHONUNBUFFERED=1 nohup python -m llmstack.cli serve --watchdog "$@" >> logs/dflash_watchdog.log 2>&1 &
WATCHDOG_PID=$!

echo "Started DFlash watchdog (PID ${WATCHDOG_PID})."
echo "Logs: logs/dflash_watchdog.log"
