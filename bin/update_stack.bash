#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_DIR="${ROOT_DIR}/env"
HEADROOM_ENV_DIR="${HOME}/headroom-env"

DRY_RUN="0"
if [[ "${1:-}" == "--dry-run" ]]; then
	DRY_RUN="1"
fi

run() {
	if [[ "${DRY_RUN}" == "1" ]]; then
		echo "[dry-run] $*"
	else
		echo "+ $*"
		"$@"
	fi
}

has_cmd() {
	command -v "$1" >/dev/null 2>&1
}

echo "⬆️  Refreshing local AI stack (npm + Python env + headroom env)..."
if [[ "${DRY_RUN}" == "1" ]]; then
	echo "🧪 Dry-run mode enabled: no real updates will be performed."
fi

echo "\n📦 NPM global tools"
if has_cmd npm; then
	run npm i -g @anthropic-ai/claude-code@latest
	run npm i -g @musistudio/claude-code-router@latest
else
	echo "⚠️  npm not found: skipping Claude Code / ccr update"
fi

echo "\n🐍 Workspace Python env (${ENV_DIR})"
if [[ -x "${ENV_DIR}/bin/python" ]]; then
	run "${ENV_DIR}/bin/python" -m pip install -U pip setuptools wheel
	# Core local inference/runtime packages used by this workspace.
	run "${ENV_DIR}/bin/python" -m pip install -U dflash-mlx mlx-lm transformers rich psutil httpx
	run "${ENV_DIR}/bin/python" "${ROOT_DIR}/bin/patch_dflash_mlx.py"
else
	echo "⚠️  Workspace env not found at ${ENV_DIR}: skipping Python package refresh"
fi

echo "\n🗜️  Headroom env (${HEADROOM_ENV_DIR})"
if [[ -x "${HEADROOM_ENV_DIR}/bin/python" ]]; then
	run "${HEADROOM_ENV_DIR}/bin/python" -m pip install -U pip setuptools wheel
	# Headroom package name can vary by installation source; keep best-effort update.
	if [[ "${DRY_RUN}" == "1" ]]; then
		echo "[dry-run] ${HEADROOM_ENV_DIR}/bin/python -m pip install -U headroom"
	else
		if ! "${HEADROOM_ENV_DIR}/bin/python" -m pip install -U headroom; then
			echo "⚠️  Could not update package 'headroom' (custom install is possible); continuing"
		fi
	fi
else
	echo "⚠️  Headroom env not found at ${HEADROOM_ENV_DIR}: skipping headroom refresh"
fi

echo "\n🔄 Router restart"
if has_cmd ccr; then
	run ccr restart
else
	echo "⚠️  ccr not found: skipping restart"
fi

echo "\n✅ Refresh script completed. Installed versions:"
if has_cmd claude; then
	claude --version || true
else
	echo "  (claude not found)"
fi

if has_cmd ccr; then
	ccr -v 2>/dev/null || ccr version 2>/dev/null || echo "  (ccr version unknown)"
else
	echo "  (ccr not found)"
fi

if [[ -x "${ENV_DIR}/bin/python" ]]; then
	"${ENV_DIR}/bin/python" -c "import sys; print('workspace python:', sys.version.split()[0])" || true
fi

if [[ -x "${HEADROOM_ENV_DIR}/bin/headroom" ]]; then
	"${HEADROOM_ENV_DIR}/bin/headroom" --version 2>/dev/null || echo "headroom: version unavailable"
fi