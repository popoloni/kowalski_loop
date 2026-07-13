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
3) After plotting, regenerate the agent-pack markdown report via
	llmstack/tools/agent_pack_report.py.

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

PLOT_SCRIPT=""

for script in "${CANDIDATES[@]}"; do
	if [[ -f "${script}" ]]; then
		PLOT_SCRIPT="${script}"
		echo "Using author script: ${script}"
		break
	fi
done

if [[ -z "${PLOT_SCRIPT}" ]]; then
	FALLBACK_SCRIPT="${PROJECT_DIR}/plot_llmstack_comparison.py"
	if [[ ! -f "${FALLBACK_SCRIPT}" ]]; then
		echo "error: fallback script missing: ${FALLBACK_SCRIPT}" >&2
		exit 1
	fi

	PLOT_SCRIPT="${FALLBACK_SCRIPT}"
	echo "No author plotting script found. Using fallback: ${FALLBACK_SCRIPT}"
fi

"${PYTHON_BIN}" "${PLOT_SCRIPT}" "$@"

AGENT_PACK_REPORT_SCRIPT="${ROOT_DIR}/llmstack/tools/agent_pack_report.py"
if [[ ! -f "${AGENT_PACK_REPORT_SCRIPT}" ]]; then
	echo "error: agent-pack report script missing: ${AGENT_PACK_REPORT_SCRIPT}" >&2
	exit 1
fi

echo "Regenerating agent-pack markdown report: ${AGENT_PACK_REPORT_SCRIPT}"
exec "${PYTHON_BIN}" "${AGENT_PACK_REPORT_SCRIPT}"
