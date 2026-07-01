#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ -f "env/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "env/bin/activate"
fi

# Default TurboQuant model (override by passing a model name as first argument).
MODEL="${1:-turboquant-qwen35b-moe}"

# Switching to a TurboQuant model updates active_model + CCR for a coherent pipeline,
# then starts the inference server on port 8787.
exec python -m llmstack.cli serve "${MODEL}"
