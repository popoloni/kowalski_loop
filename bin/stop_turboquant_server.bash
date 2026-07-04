#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ -f "env/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "env/bin/activate"
fi

PORT="8787"
NAME="TurboQuant"
WATCHDOG_PATTERN="llmstack\\.cli serve --watchdog"
WATCHDOG_PID_FILE="logs/inference_watchdog.pid"
BACKEND_PATTERN="turboquant-serve|env/bin/dflash serve| dflash serve"

watchdog_pids="$(pgrep -f "${WATCHDOG_PATTERN}" || true)"
if [[ -n "${watchdog_pids}" ]]; then
  echo "Stopping ${NAME} watchdog (PID: ${watchdog_pids//$'\n'/, })..."
  kill ${watchdog_pids} || true
  for _ in {1..5}; do
    sleep 1
    still="$(pgrep -f "${WATCHDOG_PATTERN}" || true)"
    if [[ -z "${still}" ]]; then
      break
    fi
  done
  still="$(pgrep -f "${WATCHDOG_PATTERN}" || true)"
  if [[ -n "${still}" ]]; then
    echo "Watchdog did not stop gracefully; forcing shutdown (PID: ${still//$'\n'/, })..."
    kill -9 ${still} || true
  fi
fi
rm -f "${WATCHDOG_PID_FILE}"

pids="$(lsof -ti tcp:${PORT} || true)"
if [[ -z "${pids}" ]]; then
  backend_pids="$(pgrep -f "${BACKEND_PATTERN}" || true)"
  if [[ -z "${backend_pids}" ]]; then
    echo "${NAME} is not running on port ${PORT}."
    exit 0
  fi
  echo "Stopping ${NAME} backend process (PID: ${backend_pids//$'\n'/, })..."
  kill ${backend_pids} || true
  sleep 1
  backend_pids="$(pgrep -f "${BACKEND_PATTERN}" || true)"
  if [[ -n "${backend_pids}" ]]; then
    echo "${NAME} backend did not stop gracefully; forcing shutdown (PID: ${backend_pids//$'\n'/, })..."
    kill -9 ${backend_pids} || true
  fi
  echo "${NAME} stopped."
  exit 0
fi

echo "Stopping ${NAME} on port ${PORT} (PID: ${pids//$'\n'/, })..."
kill ${pids} || true

for _ in {1..10}; do
  sleep 1
  if [[ -z "$(lsof -ti tcp:${PORT} || true)" ]]; then
    echo "${NAME} stopped."
    exit 0
  fi
done

pids="$(lsof -ti tcp:${PORT} || true)"
if [[ -n "${pids}" ]]; then
  echo "${NAME} did not stop gracefully; forcing shutdown (PID: ${pids//$'\n'/, })..."
  kill -9 ${pids} || true
fi

echo "${NAME} stopped."
