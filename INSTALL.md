# INSTALL.md

Detailed installation guide for a full local Kowalski Loop environment on macOS Apple Silicon, including:
- local runtime and CLI tools
- model artifacts (target + draft where required)
- inference server on `127.0.0.1:8787`
- Headroom proxy on `127.0.0.1:8789`
- Claude Code Router / interactive client

This guide is designed to be safe for systems that are already running.
Commands are organized to avoid stopping or overwriting an existing working setup unless explicitly requested.

## 0. Safety First (Non-Destructive Checks)

Run these checks before installing or changing anything:

```bash
cd ~/local-llm-workspace

# Toolchain visibility
for x in python3 node npm claude ccr hf; do
  command -v "$x" >/dev/null 2>&1 && echo "OK $x: $(command -v "$x")" || echo "MISSING $x"
done

# Project Python and CLI availability
test -x env/bin/python && echo "OK env/bin/python" || echo "MISSING env/bin/python"
env/bin/python -m llmstack.cli --help | head -n 8

# Health endpoints (read-only checks)
curl -fsS --max-time 2 http://127.0.0.1:8787/health && echo "OK inference"
curl -fsS --max-time 2 http://127.0.0.1:8789/health && echo "OK headroom"
```

If both health endpoints are already up, do not restart services unless you need to switch backend/model.

## 1. System Prerequisites

Install base dependencies (once per machine):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install python node@20
brew update
brew reinstall node@20
brew link --overwrite node@20
node --version
```

Install Claude Code and CCR globally:

```bash
npm config set allow-scripts=@anthropic-ai/claude-code --location=user
npm install -g @anthropic-ai/claude-code
npm install -g @musistudio/claude-code-router
```

## 2. Workspace Setup

If the workspace already exists, skip `mkdir` and `git clone`.

```bash
mkdir -p ~/local-llm-workspace
cd ~/local-llm-workspace

# Optional, only for fresh clone
# git clone <your-repo-url> .
```

Create or reuse the virtual environment:

```bash
test -d env || python3 -m venv env
source env/bin/activate
python -m pip install -U pip setuptools wheel
```

Install runtime packages used by the stack:

```bash
# DFlash backend
pip install -U dflash-mlx

# TurboQuant backend (optional but recommended if you want all three backend options)
pip install -U turboquant-mlx-full

# HF CLI for model downloads
test -x "$(command -v hf)" || pip install -U "huggingface_hub[cli]"
```

Apply the compatibility patch used by this workspace:

```bash
cd ~/local-llm-workspace
source env/bin/activate
python bin/patch_dflash_mlx.py
```

## 2b. Update Existing Installation (Recommended)

For already-installed environments, use the workspace update script instead of repeating section 2:

```bash
cd ~/local-llm-workspace
bash bin/update_stack.bash --dry-run
bash bin/update_stack.bash
```

What this script refreshes:
- global npm tools (`@anthropic-ai/claude-code`, `@musistudio/claude-code-router`)
- workspace Python packages (`dflash-mlx`, `turboquant-mlx-full`, `mlx-lm`, `transformers`, `rich`, `psutil`, `httpx`, `huggingface_hub[cli]`)
- local DFlash compatibility patch (`bin/patch_dflash_mlx.py`)
- headroom environment (best-effort)
- router restart (`ccr restart`)

Note: the real (non dry-run) run restarts the CCR router daemon. Run `--dry-run` first, and avoid the real run while an interactive/autonomous session is in progress.

This section is coherent with section 2: the same core runtime dependencies are installed there and refreshed here for maintenance.

## 3. Authenticate for Model Downloads

You must authenticate before downloading gated model artifacts:

```bash
cd ~/local-llm-workspace
source env/bin/activate
hf auth login
```

Use a token with read access to the model repos you configure.

## 4. Configure llmstack_config.json

Use your `llmstack_config.json` as source of truth for active model and registry.

Minimum keys required for deterministic backend selection:
- `active_model`
- `models` map with per-model entries
- each model entry needs `type` and `target`
- DFlash entries should include `draft`

Example shape:

```json
{
  "active_model": "dflash-qwen35b-moe",
  "models": {
    "dflash-qwen35b-moe": {
      "type": "dflash",
      "target": "mlx-community/Qwen3.6-35B-A3B-4bit",
      "draft": "z-lab/Qwen3.6-35B-A3B-DFlash"
    },
    "mlx-gemma4-12b": {
      "type": "mlx",
      "target": "mlx-community/gemma-4-12b-coder-fable5-composer2.5-4bit"
    },
    "turboquant-qwen35b-moe": {
      "type": "turboquant",
      "target": "manjunathshiva/Qwen3.6-35B-A3B-tq3-g32"
    }
  }
}
```

## 5. Install Model Artifacts (Target + Draft)

No model weights are distributed in this repository.
You must download all model artifacts referenced by your config.

List all required repos from `llmstack_config.json`:

```bash
cd ~/local-llm-workspace
source env/bin/activate

env/bin/python - <<'PY' > /tmp/llmstack_model_repos.txt
import json
from pathlib import Path
cfg = json.loads(Path('llmstack_config.json').read_text())
repos = []
for spec in (cfg.get('models') or {}).values():
    t = spec.get('target')
    d = spec.get('draft')
    if isinstance(t, str) and t.strip():
        repos.append(t.strip())
    if isinstance(d, str) and d.strip():
        repos.append(d.strip())
for repo in sorted(dict.fromkeys(repos)):
    print(repo)
PY

cat /tmp/llmstack_model_repos.txt
```

Download all listed repos:

```bash
cd ~/local-llm-workspace
source env/bin/activate

while IFS= read -r repo; do
  [ -n "$repo" ] || continue
  echo "Downloading $repo"
  hf download "$repo"
done < /tmp/llmstack_model_repos.txt
```

Notes:
- For DFlash, both `target` and `draft` are required.
- If a repo is gated, you must accept its license on Hugging Face first.
- Pre-downloading drafts avoids first-run startup timeout.

## 6. Start the Three Services

Use separate terminals.

Terminal 1: inference backend (choose one)

```bash
cd ~/local-llm-workspace
bash bin/start_dflash_server.bash
# or
# bash bin/start_mlx_server.bash
# bash bin/start_turboquant_server.bash
```

Terminal 2: Headroom proxy

```bash
cd ~/local-llm-workspace
bash bin/start_headroom_server.bash
```

Terminal 3: interactive local Claude route (CCR flow via llmstack interactive)

```bash
cd ~/local-llm-workspace
bash bin/launch_ccr.bash
```

Optional Terminal 4: dashboard

```bash
cd ~/local-llm-workspace
bash bin/launch_dashboard.bash
```

## 7. Verify End-to-End Health

Read-only service checks:

```bash
curl -fsS http://127.0.0.1:8787/health
curl -fsS http://127.0.0.1:8789/health
```

Verify model registry resolution and active model:

```bash
cd ~/local-llm-workspace
env/bin/python -m llmstack.cli model list
```

Optional diagnostic summary:

```bash
cd ~/local-llm-workspace
env/bin/python -m llmstack.cli doctor
```

## 8. Run Autonomous Kowalski Loop (Optional)

```bash
cd ~/local-llm-workspace
bash bin/launch_kowalski.bash
```

This uses `dev_root`, `plan_file`, and `permission_mode` from `llmstack_config.json`.

## 9. Stop Services Cleanly

```bash
cd ~/local-llm-workspace
bash bin/stop_headroom_server.bash
bash bin/stop_dflash_server.bash

# If MLX or TurboQuant was used as inference backend:
# bash bin/stop_mlx_server.bash
# bash bin/stop_turboquant_server.bash
```

## 10. Troubleshooting Quick Guide

Inference healthy but Headroom down:
- restart only Headroom (`bash bin/start_headroom_server.bash`)

Model load fails on first run:
- verify HF login
- verify license access
- pre-download missing draft/target with `hf download <repo>`

Unexpected cloud routing:
- use `bash bin/launch_ccr.bash` (it unsets Anthropic keys before interactive mode)

High instability under load:
- set `backend_stability_profile` to `stable` or `safest`
- reduce max context and concurrency

## Source References

Commands and flow in this guide were aligned with:
- `README.md`
- `docs/medium_article_01_install.md`
- wrapper scripts in `bin/`
