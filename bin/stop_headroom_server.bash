#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ -f "env/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "env/bin/activate"
fi

PORT="8789"
NAME="Headroom"

pids="$(lsof -ti tcp:${PORT} || true)"
if [[ -z "${pids}" ]]; then
  echo "${NAME} is not running on port ${PORT}."
else
  echo "Stopping ${NAME} on port ${PORT} (PID: ${pids//$'\n'/, })..."
  kill ${pids} || true
fi

# Safety net for stale processes that may not expose the port immediately.
pkill -f "headroom proxy" >/dev/null 2>&1 || true

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
