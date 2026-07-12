#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LAUNCHER="${ROOT_DIR}/bin/launch_llmstack_evals.bash"

usage() {
	cat <<'EOF'
Usage: bin/launch_llmstack_agent_pack_matrix.bash [run_llmstack_eval_matrix args]

Alias wrapper for agent-problem-pack matrix runs across llmstack model/backend pairs.
It always enables:
  --include-agent-pack --skip-speed --skip-reasoning

Any additional args are forwarded to run_llmstack_eval_matrix.py via
bin/launch_llmstack_evals.bash (for example: --backend dflash, --include-model ...,
--surface headroom, --output-dir ...).
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
	usage
	exit 0
fi

if [[ ! -x "${LAUNCHER}" ]]; then
	echo "error: launcher not found or not executable: ${LAUNCHER}" >&2
	exit 1
fi

exec bash "${LAUNCHER}" \
	--include-agent-pack \
	--skip-speed \
	--skip-reasoning \
	"$@"
