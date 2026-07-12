#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_DIR="${ROOT_DIR}/env"
PYTHON_BIN="${ENV_DIR}/bin/python"
RESULTS_ROOT="${ROOT_DIR}/local-coding-agent-evals/results"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_DIR="${RESULTS_ROOT}/llmstack-matrix-${TIMESTAMP}"
SURFACE="headroom"
INCLUDE_AGENT_PACK="0"
EXTRA_ARGS=()

usage() {
	cat <<'EOF'
Usage: bin/launch_llmstack_evals.bash [options] [matrix-runner args]

Activates the workspace environment and launches the llmstack eval matrix.
By default it runs speed-memory plus hard-reasoning across all configured
model/backend pairs and writes results to local-coding-agent-evals/results.

Wrapper options:
  --surface {headroom|inference}  Chat surface to use. Default: headroom.
  --output-dir PATH               Override the timestamped results directory.
  --include-agent-pack            Also run the agent-problem-pack runner.
  -h, --help                      Show this help text.

Any other arguments are passed through to run_llmstack_eval_matrix.py, for example:
  --include-model dflash-ornith35b-moe
  --backend dflash
  --skip-speed
  --skip-reasoning
  --no-bypass-permissions
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--surface)
			if [[ $# -lt 2 ]]; then
				echo "error: --surface requires a value" >&2
				exit 1
			fi
			SURFACE="$2"
			shift 2
			;;
		--output-dir)
			if [[ $# -lt 2 ]]; then
				echo "error: --output-dir requires a value" >&2
				exit 1
			fi
			OUTPUT_DIR="$2"
			shift 2
			;;
		--include-agent-pack)
			INCLUDE_AGENT_PACK="1"
			shift
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			EXTRA_ARGS+=("$1")
			shift
			;;
	esac
done

if [[ ! -f "${ENV_DIR}/bin/activate" || ! -x "${PYTHON_BIN}" ]]; then
	echo "error: workspace Python environment not found at ${ENV_DIR}" >&2
	exit 1
fi

mkdir -p "${RESULTS_ROOT}"

source "${ENV_DIR}/bin/activate"

COMMAND=(
	"${PYTHON_BIN}"
	"${ROOT_DIR}/local-coding-agent-evals/run_llmstack_eval_matrix.py"
	"--surface" "${SURFACE}"
	"--output-dir" "${OUTPUT_DIR}"
)

if [[ "${INCLUDE_AGENT_PACK}" == "1" ]]; then
	COMMAND+=("--include-agent-pack")
fi

COMMAND+=("${EXTRA_ARGS[@]}")

echo "Using Python: ${PYTHON_BIN}"
echo "Results dir: ${OUTPUT_DIR}"
echo "Surface: ${SURFACE}"
if [[ "${INCLUDE_AGENT_PACK}" == "1" ]]; then
	echo "Agent pack: enabled"
else
	echo "Agent pack: disabled"
fi

cd "${ROOT_DIR}"
exec "${COMMAND[@]}"