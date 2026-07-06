#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${ROOT_DIR}/env/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "ERROR: Python env not found at ${PYTHON_BIN}"
  echo "Create/restore the workspace env before running this script."
  exit 1
fi

run() {
  echo "+ $*"
  "$@"
}

echo "Refreshing charts and metrics docs from current logs..."

echo ""
echo "[1/7] Savings charts"
run "${PYTHON_BIN}" "${ROOT_DIR}/llmstack/tools/plot_savings.py"

echo ""
echo "[2/7] Savings metrics table in SAVINGS.md"
run "${PYTHON_BIN}" "${ROOT_DIR}/llmstack/tools/savings_metrics.py" --update-savings-md

echo ""
echo "[3/6] DFlash metrics blocks in DFLASH.md"
run "${PYTHON_BIN}" "${ROOT_DIR}/llmstack/tools/dflash_metrics.py" --update-dflash-md

echo ""
echo "[4/6] Headroom charts"
run "${PYTHON_BIN}" "${ROOT_DIR}/llmstack/tools/plot_headroom.py"

echo ""
echo "[5/6] Headroom metrics blocks in HEADROOM.md"
run "${PYTHON_BIN}" "${ROOT_DIR}/llmstack/tools/headroom_metrics.py" --update-headroom-md

echo ""
echo "[6/7] Timings aggregate charts"
run "${PYTHON_BIN}" "${ROOT_DIR}/llmstack/tools/plot_timings.py"

echo ""
echo "[7/7] Qwen A/B and crash-risk report"
run "${PYTHON_BIN}" "${ROOT_DIR}/llmstack/tools/llm_comparison_metrics.py" --update-md

echo ""
echo "Done. Updated outputs include:"
echo "- docs/img/savings/*"
echo "- docs/img/headroom/*"
echo "- docs/img/* and docs/img/sessions/* (timings plots)"
echo "- SAVINGS.md"
echo "- DFLASH.md"
echo "- HEADROOM.md"
echo "- LLM_COMPARISON.md"
