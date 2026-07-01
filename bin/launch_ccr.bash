#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
if [ -f "env/bin/activate" ]; then
  source env/bin/activate
fi

# Force local model: clear cloud keys
unset ANTHROPIC_AUTH_TOKEN
unset ANTHROPIC_API_KEY

exec python -m llmstack.cli interactive "$@"
