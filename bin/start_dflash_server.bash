#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
if [ -f "env/bin/activate" ]; then
  source env/bin/activate
fi
exec python -m llmstack.cli serve "$@"
