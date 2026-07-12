#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_DIR="${ROOT_DIR}/env"
PYTHON_BIN="${ENV_DIR}/bin/python"
PROJECT_DIR="${ROOT_DIR}/local-coding-agent-evals"

usage() {
	cat <<'EOF'
Usage: bin/plot_llmstack_comparison.bash [args]

Behavior:
1) Reuse an author-provided comparison plotting script if one is present.
2) Otherwise, fallback to local-coding-agent-evals/plot_llmstack_comparison.py.

Fallback args are passed through to plot_llmstack_comparison.py, for example:
  --results-root local-coding-agent-evals/results
  --output local-coding-agent-evals/results/llmstack_comparison.png
  --title "LLMStack Comparison"
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
	usage
	exit 0
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
	echo "error: Python env not found: ${PYTHON_BIN}" >&2
	exit 1
fi

if [[ ! -d "${PROJECT_DIR}" ]]; then
	echo "error: project dir not found: ${PROJECT_DIR}" >&2
	exit 1
fi

source "${ENV_DIR}/bin/activate"

CANDIDATES=(
	"${PROJECT_DIR}/plot_comparison.py"
	"${PROJECT_DIR}/scripts/plot_comparison.py"
	"${PROJECT_DIR}/scripts/plot_results.py"
	"${PROJECT_DIR}/speed-memory-benchmark/plot_results.py"
	"${PROJECT_DIR}/hard-tool-reasoning-benchmark/plot_results.py"
)

for script in "${CANDIDATES[@]}"; do
	if [[ -f "${script}" ]]; then
		echo "Using author script: ${script}"
		exec "${PYTHON_BIN}" "${script}" "$@"
	fi
done

FALLBACK_SCRIPT="${PROJECT_DIR}/plot_llmstack_comparison.py"
if [[ ! -f "${FALLBACK_SCRIPT}" ]]; then
	echo "error: fallback script missing: ${FALLBACK_SCRIPT}" >&2
	exit 1
fi

echo "No author plotting script found. Using fallback: ${FALLBACK_SCRIPT}"
exec "${PYTHON_BIN}" "${FALLBACK_SCRIPT}" "$@"
