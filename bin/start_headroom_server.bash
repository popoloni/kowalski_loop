#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ -f "env/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "env/bin/activate"
fi

mkdir -p logs

PORT="8789"
HEALTH_URL="http://127.0.0.1:${PORT}/health"
LOCK_DIR="logs/.headroom-start.lock"
MAX_RETRIES="${HEADROOM_START_RETRIES:-3}"

is_headroom_healthy() {
  curl -fsS -m 2 "${HEALTH_URL}" >/dev/null 2>&1
}

if is_headroom_healthy; then
  echo "Headroom is already healthy on port ${PORT}."
  exit 0
fi

if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
  echo "Another headroom start is already in progress."
  exit 0
fi
trap 'rmdir "${LOCK_DIR}" >/dev/null 2>&1 || true' EXIT

for ((attempt=1; attempt<=MAX_RETRIES; attempt++)); do
  if pgrep -f "headroom proxy" >/dev/null 2>&1; then
    echo "Found stale headroom process; stopping before retry ${attempt}/${MAX_RETRIES}..."
    pkill -f "headroom proxy" >/dev/null 2>&1 || true
    sleep 1
  fi

  echo "Starting headroom (attempt ${attempt}/${MAX_RETRIES})..."
  if python -m llmstack.cli proxy "$@"; then
    if is_headroom_healthy; then
      echo "Headroom started and healthy on port ${PORT}."
      exit 0
    fi
  fi

  if (( attempt < MAX_RETRIES )); then
    backoff=$((attempt * 2))
    echo "Headroom still unhealthy after attempt ${attempt}; retrying in ${backoff}s..."
    sleep "${backoff}"
  fi
done

echo "Headroom failed to become healthy after ${MAX_RETRIES} attempts."
exit 1
