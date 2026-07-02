# local-llm-workspace

A local stack for running a quantized LLM (Qwen3-27B, Qwen3-35B or Gemma4-12B) on Apple Silicon via **DFlash/TurboQuant/MLX** inference backend, with a compression proxy (**Headroom**), a Claude Code router (**ccr**), and an unattended supervisor (**Ralph**) driving **Claude Code** agent.

---

## ⚡ Quick Intro

This workspace lets you run **Claude Code locally** on your Mac in two ways:

### **1️⃣ Interactive Mode** (Development)
Start an inference backend + Headroom, then open Claude Code interactively.  
The `bin/start_*_server.bash` scripts hand off server processes to run in the background, so you do **not** need dedicated long-running terminals just to keep inference/Headroom alive.  
Separate terminals are mainly useful for the interactive Claude Code session and optional dashboard monitoring. **Perfect for exploring, prototyping, and debugging.**

```bash
# Terminal 1
bash bin/start_dflash_server.bash
bash bin/start_headroom_server.bash
# (interactive)
bash bin/launch_ccr.bash

# Terminal 2
bash bin/launch_dashboard.bash
```

→ See **[Mode 1: Standalone Interactive](#mode-1-standalone-interactive-development)** for details.

### **2️⃣ Autonomous Mode** (Ralph Orchestrator)
Write a plan (list of tasks), then Ralph automatically:
- Decomposes complex goals into atomic steps
- Routes each task to Claude Code (multi-turn agent)
- Verifies every change (syntax, markers, smoke tests, git checkpoints)
- Resumes on timeout or failure
- Commits only verified work

```bash
# Terminal 1
# Edit llmstack_config.json, create your plan, then:
bash bin/launch_ralph.bash

# Terminal 2
bash bin/launch_dashboard.bash
```

→ See **[Mode 2: Autonomous Orchestration](#mode-2-autonomous-orchestration-ralph-loop)** for details.

### **Choose Your Mode:**

| Need | Mode | Command |
|------|------|---------|
| Explore & debug interactively | **Interactive (attended)** | `bin/launch_ccr.bash`, `python -m llmstack.cli interactive` |
| Automate a build plan with verification | **Ralph (unattended)** | `bin/launch_ralph.bash`, `python -m llmstack.cli run` |

To monitor real-time metrics: `bin/launch_dashboard.bash`, `python -m llmstack.cli dashboard` in another terminal window.

---

## Architecture

```
Claude Code  →  ccr (Claude Code Router)  →  Headroom proxy :8789  →  Inference server :8787 (DFlash/MLX/TurboQuant)  →  Apple GPU
```

| Component | Port | Description |
|---|---|---|
| Ralph Supervisor (opt) | — | Python orchestrator that starts the servers, warms the cache, and runs tasks in a loop inside Claude Code |
| Claude Code | - | Anthropic agentic coding assistant |
| Claude Code Router (ccr) | — | Routes Claude Code requests to Headroom instead of Anthropic cloud |
| Headroom proxy | `8789` | Proxy that compresses context in a code-aware manner before sending to DFlash |
| Inference server (DFlash/MLX/TurboQuant) | `8787` | OpenAI-compatible local inference endpoint selected from model registry |

---

## Prerequisites

- macOS with Apple Silicon (MLX requires Metal)
- [Claude Code](https://docs.anthropic.com/claude-code) (`claude`) installed globally via npm
- [Claude Code Router](https://github.com/musistudio/claude-code-router) (`ccr`) installed globally via npm
- [Headroom](https://github.com/musistudio/headroom) installed in `~/headroom-env/`
- Python virtualenv in `./env/` with `dflash-mlx` and dependencies (already included)

---

## File Structure

| File | Description |
|---|---|
| **Standalone Launchers** | |
| `bin/start_dflash_server.bash` | Starts inference via `python -m llmstack.cli serve [model_name]` (DFlash model by default). Inference binds to `127.0.0.1:8787` and is managed in background by the service layer. |
| `bin/start_mlx_server.bash` | Starts inference on backend type `mlx` (default model: `mlx-gemma4-12b`, override with first arg). Binds to `127.0.0.1:8787`. |
| `bin/start_turboquant_server.bash` | Starts inference on backend type `turboquant` (default model: `turboquant-qwen35b-moe`, override with first arg). Binds to `127.0.0.1:8787`. |
| `bin/start_headroom_server.bash` | Starts only the Headroom proxy on `127.0.0.1:8789` (upstream `:8787`, logs to `logs/headroom_traffic.jsonl`). Managed in background by the service layer. |
| `bin/stop_dflash_server.bash` | Stops whichever inference process is bound to port `8787` (graceful stop with force-kill fallback). |
| `bin/stop_mlx_server.bash` | Stops whichever inference process is bound to port `8787` (graceful stop with force-kill fallback). |
| `bin/stop_turboquant_server.bash` | Stops whichever inference process is bound to port `8787` (graceful stop with force-kill fallback). |
| `bin/stop_headroom_server.bash` | Stops Headroom on port `8789` (graceful stop with force-kill fallback, plus stale-process safety net). |
| `bin/launch_ccr.bash` | **Interactive Claude Code** — starts `ccr code` with `acceptEdits` by default, pre-trusted folders, optimized system prompt. Changes to project folder (`dev_root` from config). Reads config from `llmstack_config.json`. |
| `bin/launch_dashboard.bash` | Launches the terminal monitoring dashboard (TPS, cache %, memory, requests). Requires DFlash + Headroom running. |
| **Autonomous Mode** | |
| `bin/launch_ralph.bash` | **Main entry point** — thin shell wrapper around `python -m llmstack.cli run`. Starts the stack and runs Ralph orchestrator. |
| `llmstack/core/supervisor.py` | Core orchestrator used by `llmstack.cli run` to execute the autonomous loop. |
| **Configuration & Utilities** | |
| `llmstack_config.json` | Central configuration file for Ralph (timeouts, permissions, gates, model params). Used by all launchers. |
| `llmstack/tools/build_plan.py` | Generates task plans for Ralph (decomposes project goal into atomic, verifiable tasks). |
| `llmstack/tools/log_cleaner.py` | Filters HTTP access-log lines from `logs/dflash_server.log` → creates `logs/server_pulito.log`. |
| `llmstack/tools/dflash_dashboard.py` | Terminal dashboard implementation launched by `bin/launch_dashboard.bash`. |
| `llmstack/tools/plot_timings.py` | Generates article charts from `logs/dflash_timings.csv` into `docs/img/`. |
| `bin/update_stack.bash` | Updates `claude` and `ccr` to the latest version via npm. |
| `docs/commit_history.txt` | Text log of manual/project commit notes and migration checkpoints. |
| **Projects & Environment** | |
| `pacman_clone/` | Sample project managed by Ralph (Pac-Man game in HTML/JS). Contains `.claude/` subfolder for plans. |
| `env/` | Python virtualenv with dflash-mlx, mlx-lm, rich, psutil, and other dependencies. |

---

## How to Run

### Mode 1: Standalone Interactive (Development)

Use this to **manually code** with full Claude Code privileges, no automation.

#### 1a. Start the infrastructure (one-time setup)

From your current terminal (or separate terminals if you prefer):
```bash
cd ~/local-llm-workspace
bash bin/start_dflash_server.bash
```
Waits for model to load (~5–10 min on first run), then leaves the inference server managed in the background on `:8787`. Output → `logs/dflash_server.log`.

Then start Headroom:
```bash
cd ~/local-llm-workspace
bash bin/start_headroom_server.bash
```
Starts compression proxy on `:8789` (upstream `:8787`) and leaves it managed in the background. Output → `logs/headroom.log` + `logs/headroom_traffic.jsonl`.

#### 1b. Start interactive Claude Code

In **Terminal 3**:
```bash
cd ~/local-llm-workspace
bash bin/launch_ccr.bash
```

You now have an **interactive session** with:
- ✅ Cloud keys cleared (local-only mode)
- ✅ Permission mode defaults to `acceptEdits` (override with `interactive_permission_mode` in config)
- ✅ Working directory set to `dev_root` from config
- ✅ Pre-trusted folders (no approval dialogs)
- ✅ Optimized system prompt (atomic tasks)
- ✅ Timeouts from `llmstack_config.json`
- ✅ Max turns from `llmstack_config.json`

Ask Claude Code to create/edit files in your project directory without approval. Changes are **not tracked** by Ralph (no git automation here).

#### 1c. Monitor in real time (optional)

In **Terminal 4**:
```bash
bash bin/launch_dashboard.bash
```

Displays live metrics: TPS, cache hits, memory, recent requests.

#### 1d. Stop infrastructure

```bash
bash bin/stop_headroom_server.bash
bash bin/stop_dflash_server.bash
```

---

### Mode 2: Autonomous Orchestration (Ralph Loop)

Use this to **automatically decompose a goal into tasks and execute them** with full verification gates.

#### 2a. Prepare your project folder

Create a new project folder or use an existing one (default: `./pacman_clone`):

```bash
mkdir -p my_project
cd my_project
# (optional) Initialize git
git init
```

#### 2b. Write or generate a task plan

**Option A: Auto-generate a plan** (guided)

```bash
cd ~/local-llm-workspace
source env/bin/activate
python3 -m llmstack.tools.build_plan "Build a Tic-Tac-Toe game in HTML/JS"
```

The model will:
1. Decompose the goal into atomic tasks (board creation, game logic, UI, etc.)
2. Assign executors (agent for complex, direct for simple files)
3. Define verification gates (syntax checks, feature markers, smoke tests)
4. Print the full plan to stdout

Review it, tweak any task if needed, then continue.

**Option B: Write a plan manually** (advanced)

Create a file at `my_project/.claude/plans/my_plan.json`:

```bash
mkdir -p my_project/.claude/plans
cat > my_project/.claude/plans/my_plan.json <<'EOF'
{
  "tasks": [
    {
      "id": "task_01",
      "prompt": "Create the game board with a 3x3 grid in HTML...",
      "file": "index.html",
      "mode": "direct",
      "verify": "node -e \"require('fs').readFileSync('index.html')\" && echo OK",
      "expect": ["<div id=\"board\">"],
      "status": "pending"
    },
    {
      "id": "task_02",
      "prompt": "Implement game logic: X/O placement, win detection...",
      "file": "game.js",
      "mode": "agent",
      "context": ["index.html"],
      "verify": "node --check game.js",
      "expect": ["checkWin", "placeMarker"],
      "require_change": true,
      "smoke": [
        "const g = require('./game.js');",
        "console.log(g.checkWin ? '✓ game logic loaded' : '✗ missing checkWin');"
      ],
      "status": "pending"
    }
  ]
}
EOF
Edit `llmstack_config.json`:

```json
{
  "dev_root": "./my_project",
  "plan_file": "./my_project/.claude/plans/my_plan.json",
  "permission_mode": "acceptEdits",
  "max_turns": 150,
  "timeout_seconds": 3600,
  "max_retries": 3,
  "max_resumes": 8,
  "require_change": true,
  "wiring_check": false,
  "review_enabled": false
}
```

#### 2d. Start the autonomous loop

```bash
cd ~/local-llm-workspace
bash bin/launch_ralph.bash
```

Alternatively:

```bash
cd ~/local-llm-workspace
python -m llmstack.cli run
```

Ralph will:
1. Start DFlash server (loads model into RAM)
2. Start Headroom proxy
3. Patch CCR timeout and pretrust the project folder
4. Warm the prefix cache (dummy agentic request)
5. **Execute each task** in sequence:
   - Route to Claude Code (agent or direct, with `permission_mode` from config)
  - Auto-approve edits (and common filesystem operations) when `"permission_mode": "acceptEdits"`
   - Apply 6-layer verification gates
   - Commit verified changes to git
   - Resume or retry on failure
6. Print final status

**Expected output**:
```
🤖 Booting Ralph Unattended Agent System...
⏱️  Timeout centralized: 3600s applied to env + CCR config.json.
✅ DFlash ONLINE & HEALTHY
🗜️  Headroom proxy on :8789 → dflash :8787...
🔄 Restarting Claude Code Router daemon...
🚀 Handing over control to Ralph Orchestrator...
⏳ Waiting for model to load into RAM...
✅ Server online and healthy.
📦 Git ready (last verified state protected).
🔥 Warming the agentic prefix cache...
📋 [Ralph] Loaded 2 tasks.

▶️  [Ralph] Task task_01 — attempt 1 (direct)
✍️  [Ralph] Direct-generating index.html...
📝 [Ralph] Wrote index.html (1235 bytes).
✅ [Ralph] Task task_01 COMPLETE & verified.

▶️  [Ralph] Task task_02 — attempt 1 (agent, turns=150)
⚙️  [Ralph] Running Task task_02 (agentic, turns=150) in /Users/enricopapalini/local-llm-workspace/my_project
✅ [Ralph] Task task_02 COMPLETE & verified.

🎉 [Ralph] All tasks verified and committed!
```

---

### Optional: Other Utilities

#### Generate a new plan interactively

```bash
source env/bin/activate
python3 -m llmstack.tools.build_plan "Implement a 2D physics engine"
```

#### Monitor logs

Real-time dashboard:
```bash
bash bin/launch_dashboard.bash
```

Clean logs (remove HTTP access lines):
```bash
source env/bin/activate
python3 -m llmstack.tools.log_cleaner
```

Generate timing charts for docs (writes `docs/img/*.png`):
```bash
source env/bin/activate
python3 -m llmstack.tools.plot_timings
```

#### Update Claude Code & ccr

```bash
bash bin/update_stack.bash
```

---

## Ralph Configuration (`llmstack_config.json`)

Complete reference of all available parameters:

```json
{
  "dev_root": "./pacman_clone",
  "plan_file": "./pacman_clone/.claude/plans/pacman_plan.json",
  "log_dir": "./logs",
  "dflash_log": "./logs/dflash_server.log",
  "headroom_log": "./logs/headroom.log",
  "headroom_traffic_log": "./logs/headroom_traffic.jsonl",
  "timings_csv": "./logs/dflash_timings.csv",
  "permission_mode": "acceptEdits",
  "max_turns": 100,
  "timeout_seconds": 3600,
  "warmup_timeout_seconds": 120,
  "max_retries": 3,
  "max_resumes": 8,
  "agent_format_retries": 2,
  "allow_already_done_if_verified": true,
  "size_threshold_bytes": 12000,
  "debug_log": "./logs/ralph_debug.log",
  "debug_max_chars": 0,
  "agent_tools": ["Read", "Edit"],
  "require_change": true,
  "wiring_check": true,
  "review_enabled": false,
  "verification_plugins": {
    "python_lint": {
      "command": "ruff check {file}",
      "when": "task",
      "languages": [".py"],
      "on_failure": "fail",
      "enabled": true
    },
    "suite": {
      "command": "pytest -x",
      "when": "plan_complete",
      "on_failure": "fail",
      "enabled": true
    }
  },
  "loop_mode": "plan",
  "continuous_queue_file": "task_queue.json",
  "continuous_poll_seconds": 2,
  "watch_root": ".",
  "watch_queue_file": "task_queue.json",
  "watch_poll_seconds": 2,
  "watch_debounce_seconds": 0.5,
  "thinking_mode": "off",
  "supervised_approval_mode": "console"
}
```

### Core Parameters

| Parameter | Type | Default | Possible Values | Description |
|---|---|---|---|---|
| **`dev_root`** | string | `"."` | Any valid directory path (relative or absolute) | Root directory where Claude Code operates. All file modifications and git operations are relative to this path. Example: `"./pacman_clone"`, `"."`, `"/absolute/path"` |
| **`plan_file`** | string | `"plan.json"` | Any valid file path inside `dev_root` | Path to the JSON file containing the task list to execute sequentially. Loaded fresh on each run. Example: `"plan.json"`, `".claude/plans/main.json"` |
| **`permission_mode`** | string | `"acceptEdits"` | `"default"` &#124; `"acceptEdits"` &#124; `"plan"` &#124; `"auto"` &#124; `"dontAsk"` &#124; `"bypassPermissions"` | Claude Code permission mode for autonomous task execution. `acceptEdits` is recommended for local unattended development. |
| **`agent_tools`** | array | `["Read", "Edit"]` | Any combination of: `"Read"`, `"Edit"`, `"Write"`, `"Bash"`, `"Glob"`, `"Grep"`, `"WebFetch"`, `"Task"` | Tools available to the Claude Code agent. Typically `["Read", "Edit"]` for safety. Add `"Bash"` for script execution. |

### Timeout & Retry Parameters

| Parameter | Type | Default | Possible Values | Description |
|---|---|---|---|---|
| **`timeout_seconds`** | integer | `1800` | `60` to `7200` (1 min – 2 hours) | **Master timeout** for ALL operations (agent task, direct generation, ccr calls). Converted to milliseconds for `API_TIMEOUT_MS` and `CLAUDE_STREAM_IDLE_TIMEOUT_MS` environment variables. If a task takes longer than this, it returns `TIMEOUT`. Recommended: `1800` (30 min) to `3600` (1 hour). |
| **`warmup_timeout_seconds`** | integer | `120` | `10` to `600` | Timeout for the pre-run cache warm-up request. If warm-up hangs/fails, Ralph logs and continues to the task loop instead of blocking startup for the full task timeout. |
| **`max_turns`** | integer | `150` | `10` to `1000` | Maximum number of agent turns (back-and-forth between Ralph and Claude Code) for a single task. If hit, the task returns `AGENT_ERROR` and may be resumed. Higher values allow more refinement but increase runtime. |
| **`max_retries`** | integer | `3` | `1` to `10` | Hard retry limit for a task. After this many failures (no valid progress), the task is abandoned and Ralph halts. `1` = no retries; `3-5` = balanced; higher = very lenient. |
| **`max_resumes`** | integer | `8` | `0` to `20` | Resume limit: if a task times out or errors but has valid progress (WIP commit), it can be resumed up to this many times before giving up. `0` = disable resumption; `8-10` = reasonable for development. |
| **`agent_format_retries`** | integer | `2` | `0` to `10` | Extra retries for agent runs when the provider returns transport/format errors (for example `content block is not a text block`). Ralph adds a stricter format-safety directive on each retry. |
| **`allow_already_done_if_verified`** | boolean | `false` | `true` &#124; `false` | If enabled, agent tasks can complete with `RalphStatus: already_done` **only** when all deterministic gates pass with `require_change` temporarily skipped for that task attempt. Useful for idempotent reruns after partial failures. |

### Thresholds & Logging

| Parameter | Type | Default | Possible Values | Description |
|---|---|---|---|---|
| **`size_threshold_bytes`** | integer | `12000` | `1000` to `100000` | File size threshold (bytes) for executor selection. Files **larger** than this use the **agent** executor (multi-turn refinement). Files **smaller or equal** use **direct** executor (one-shot generation). Default `12000` ≈ 12KB. Lower = more direct mode; higher = more agent mode. |
| **`debug_log`** | string | `"./logs/ralph_debug.log"` | Any file path, or `""` / `null` to disable | Path to the debug log. Records agentic input/output, direct generation rounds, and verification details. Set to empty string `""` or `null` to disable debug logging. Example: `"./logs/ralph_debug.log"`, `"./logs/custom_debug.log"`, `""` |
| **`debug_max_chars`** | integer | `0` | `0` to `1000000` | Maximum characters to include in each debug log entry. `0` = unlimited (log everything). Helps manage log size for large outputs. Example: `0` (unlimited), `10000` (10KB per entry), `50000` (50KB per entry) |

### Verification & Quality Gates

| Parameter | Type | Default | Possible Values | Description |
|---|---|---|---|---|
| **`require_change`** | boolean | `true` | `true` &#124; `false` | **Change gate**: Enabled (`true`) — task **must** modify its declared `file` or it fails (prevents no-ops). Disabled (`false`) — Ralph skips this check and allows unchanged files. Recommended: `true` for safety. |
| **`wiring_check`** | boolean | `true` | `true` &#124; `false` | **Wiring gate**: Enabled (`true`) — every `*.js` file must be referenced in `index.html`, and every referenced file must exist (catches orphan/unused JS). Disabled (`false`) — Ralph skips wiring validation. Recommended: `true` for frontend projects, `false` for non-web. |
| **`review_enabled`** | boolean | `false` | `true` &#124; `false` | **LLM review gate** (soft, optional): Enabled (`true`) — the weak model critiques the diff against the task spec. **Not blocking** (deterministic gates are the real protection); mostly informational. Disabled (`false`) — skips review. Recommended: `false` unless extra scrutiny needed. |

### Pluggable Gate Parameters

The built-in gates remain the default path. `verification_plugins` lets you append extra shell-based checks without changing Ralph's code.

| Parameter | Type | Default | Possible Values | Description |
|---|---|---|---|---|
| **`verification_plugins`** | object | `{}` | map of plugin name → plugin definition | Additional verification hooks. Empty object means the feature is effectively disabled and current behavior is unchanged. |

Each plugin definition supports:

| Field | Type | Default | Possible Values | Description |
|---|---|---|---|---|
| **`command`** | string | — | Any shell command | Required. Runs from `dev_root`. Supports `{file}`, `{dev_root}`, and `{plan_file}` interpolation. |
| **`when`** | string | `"task"` | `"task"` &#124; `"plan_complete"` | `task` runs after a task's built-in deterministic checks and smoke test. `plan_complete` runs once after the whole plan finishes. |
| **`languages`** | array[string] | `[]` | extensions like `".py"`, `".ts"` | Optional file-extension filter for task-level plugins. |
| **`files`** | array[string] | `[]` | shell-style patterns like `"src/*.py"` | Optional task file filter using `fnmatch` patterns. |
| **`on_failure`** | string | `"fail"` | `"fail"` &#124; `"warn"` | `fail` blocks verification and feeds stderr/stdout into smart retry. `warn` logs the failure and continues. |
| **`enabled`** | boolean | `true` | `true` &#124; `false` | Allows shipping plugins in config while toggling them on/off explicitly. |

### Thinking Mode

`thinking_mode` controls whether Claude Code stays in the current no-thinking posture or uses more reasoning on agentic tasks.

| Parameter | Type | Default | Possible Values | Description |
|---|---|---|---|---|
| **`thinking_mode`** | string | `"off"` | `"off"` &#124; `"auto"` &#124; `"on"` | Global default for agentic tasks. `off` keeps the current behavior, `auto` enables adaptive thinking while keeping full thinking off, and `on` enables both. Per-task overrides win. |

Task-level override:
- Add `"thinking_mode": "auto"` or `"on"` to a task to override the global default.
- The chosen mode is visible in the agent debug log for each attempt.
- The mode only affects agentic execution; direct-generation tasks keep their current behavior.

### Loop Mode Parameters

These control **how** Ralph selects and runs tasks. See [Loop Modes](#loop-modes) for a full walkthrough.

| Parameter | Type | Default | Possible Values | Description |
|---|---|---|---|---|
| **`loop_mode`** | string | `"plan"` | `"plan"` &#124; `"continuous"` &#124; `"watch"` &#124; `"supervised"` | Selects the loop strategy. `plan` = run a fixed plan once (classic behavior). `continuous` = poll a queue file for new tasks. `watch` = auto-enqueue fix tasks when `.py` files change. `supervised` = ask for console approval before each task. |
| **`continuous_queue_file`** | string | `"task_queue.json"` | Any file path (relative to CWD) | **Continuous mode only.** Queue file that Ralph polls. Tasks appended here (list or `{"tasks": [...]}`) are picked up on the next poll. Invalid JSON is tolerated (Ralph warns and waits). |
| **`continuous_poll_seconds`** | number | `2` | `0.1` to `60` | **Continuous mode only.** Seconds between queue re-reads while idle. |
| **`watch_root`** | string | `"."` | Any directory path (relative to CWD) | **Watch mode only.** Directory tree monitored for `.py` changes. |
| **`watch_queue_file`** | string | `"task_queue.json"` | Any file path (relative to CWD) | **Watch mode only.** File where auto-generated fix tasks are written (also honored if you append tasks manually). |
| **`watch_poll_seconds`** | number | `2` | `0.1` to `60` | **Watch mode only.** Seconds between filesystem re-scans (mtime fallback in addition to OS events). |
| **`watch_debounce_seconds`** | number | `0.5` | `0` to `10` | **Watch mode only.** Coalescing window so rapid successive saves of the same file enqueue only one task. |
| **`supervised_approval_mode`** | string | `"console"` | `"console"` | **Supervised mode only.** Approval channel. Currently `console` (interactive prompt in the terminal). Telegram approval is planned for a later phase. |

### Permission Modes Explained

The `permission_mode` setting controls how Claude Code approves tool calls during autonomous execution:

| Mode | Behavior | Use Case |
|------|------|------|
| **`default`** | Reads run without prompts; edits and non-read-only commands prompt. | Highest oversight |
| **`acceptEdits`** | Auto-approves edits + common filesystem operations in scope. | Recommended default |
| **`plan`** | Planning/research mode; no source edits until mode changes. | Analyze first |
| **`auto`** | Auto-approves with classifier safety checks. | Long autonomous runs |
| **`dontAsk`** | Denies prompt-requiring calls unless pre-approved by allow rules / allowed tools. | Locked-down CI |
| **`bypassPermissions`** | Skips prompts except explicit ask rules/circuit breakers. | Isolated sandboxes only |

**Current defaults:**
- **Interactive mode** (`bin/launch_ccr.bash`): Uses `acceptEdits` by default, configurable via `interactive_permission_mode`
- **Ralph mode** (`bin/launch_ralph.bash`): Uses `permission_mode` from `llmstack_config.json` (default: `acceptEdits`)

#### How Quality Gates Work

Ralph applies a **verification pipeline** to every completed task:

1. **Shell verify** — Runs the task's `verify` command (e.g., `node --check`). Catches syntax errors.
2. **Feature markers** — Checks that all strings in `expect` appear in the task's `file`. Ensures declared features are present.
3. **Change gate** (controlled by `require_change`) — Verifies that the task actually modified `file`. Rejects no-ops.
4. **Already-done override** (controlled by `allow_already_done_if_verified`) — for agent tasks only, if the agent reports `RalphStatus: already_done`, Ralph re-runs deterministic gates with `require_change=false` for that attempt. Task completes only if verification still passes.
5. **Format fallback (per-task strategy)** — if an agent task repeatedly fails with provider formatting errors, set `"on_format_error": "direct_context_fallback"` in that task to regenerate `file + context` with direct mode and then run standard verification.
6. **Wiring check** (controlled by `wiring_check`) — Verifies no orphan JS and all referenced files exist.
7. **Behavioral smoke** — Runs the task's `smoke` code (Node.js assertions). Catches runtime bugs.
8. **Pluggable task plugins** (controlled by `verification_plugins`) — Runs extra shell-based checks filtered by task file / extension. Failing `fail` plugins feed stderr/stdout into smart retry.
9. **Thinking mode** (controlled by `thinking_mode`) — Controls whether the agent runs with thinking disabled, adaptive, or fully on.
10. **Optional LLM review** (controlled by `review_enabled`) — Optional diff critique (disabled by default).
11. **Plan-complete plugins** — After all tasks finish, Ralph runs any `verification_plugins` with `"when": "plan_complete"` exactly once.

If any gate fails, the task is rolled back and retried.

### Pluggable Verification Plugins

Use this when built-in `verify` / `expect` / `smoke` are not enough and you want reusable checks in config instead of repeating them in every task.

Example:

```json
{
  "verification_plugins": {
    "python_lint": {
      "command": "ruff check {file}",
      "when": "task",
      "languages": [".py"],
      "on_failure": "fail"
    },
    "ts_typecheck": {
      "command": "npx tsc --noEmit",
      "when": "task",
      "files": ["src/*.ts", "src/*.tsx"],
      "on_failure": "warn"
    },
    "suite": {
      "command": "pytest -x",
      "when": "plan_complete",
      "on_failure": "fail"
    }
  }
}
```

Task-level control:
- Set `verification_plugins` on a task to run only a named subset.
- Set `disable_plugins` on a task to suppress named plugins.

Example task:

```json
{
  "id": "task_07",
  "prompt": "Refactor the parser without changing behavior.",
  "file": "parser.py",
  "verification_plugins": ["python_lint"],
  "disable_plugins": ["suite"]
}
```

Notes:
- Plugin commands run from `dev_root`.
- Plugin config is validated at startup; invalid definitions fail fast.
- `plan_complete` plugins do **not** run after every task. They run once after the plan finishes.
- `warn` plugins are informational; `fail` plugins become part of the retry loop.

---

---

## Quick Start Guide

### In 60 Seconds: Interactive Mode

```bash
# Start inference backend on :8787 (runs in background after startup)
bash bin/start_dflash_server.bash
# (or: bash bin/start_mlx_server.bash / bash bin/start_turboquant_server.bash)

# Start Headroom on :8789 (runs in background after startup)
bash bin/start_headroom_server.bash

# Start Claude Code interactive session (this terminal is interactive)
bash bin/launch_ccr.bash
```

### In 5 Minutes: Autonomous Mode (Ralph)

```bash
# 1. Prepare your project
mkdir my_project
cd my_project
git init

# 2. Create a task plan
cat > my_project/.claude/plans/plan.json <<'EOF'
{
  "tasks": [
    {
      "id": "task_01",
      "prompt": "Create index.html with a button that says 'Click me'",
      "file": "index.html",
      "expect": ["Click me"]
    },
    {
      "id": "task_02",
      "prompt": "Add JavaScript to log 'Button clicked' when clicked",
      "file": "script.js",
      "context": ["index.html"],
      "verify": "node --check script.js"
    }
  ]
}
EOF

# 3. Update Ralph config
# (edit llmstack_config.json: set dev_root to "./my_project" and plan_file path)

# 4. Run Ralph
bash bin/launch_ralph.bash
```

### Bootstrap a New Workspace

Use the interactive wizard when you want a minimal starter config and an optional first plan:

```bash
python -m llmstack.cli init
```

The wizard asks for:
- `dev_root`
- project type
- goal
- model/backend preference
- whether to generate a starter plan immediately

It writes a compact `llmstack_config.json` with stable keys only, derives a starter plan path under `./.claude/plans/`, and optionally calls `build_plan.py` for the provided goal. The generated config records `project_type`, a `project_template` block (`name`, `language`, `description`, `starter_layout`, `plan_name`), and the chosen `project_goal` alongside the usual `dev_root`, `active_model`, `plan_file`, `loop_mode`, `permission_mode`, `thinking_mode`, and `verification_plugins` keys.

Useful flag:
- `--force` overwrites an existing `llmstack_config.json`. It works both interactively and combined with the scriptable flags (e.g. `llmstack init --force --non-interactive ...`).

Scriptable mode:
- `--non-interactive` skips prompts and uses defaults or the values you pass.
- `--dev-root`, `--project-type`, `--goal`, and `--model` let you pin the generated config.
- `--bootstrap-plan` or `--no-bootstrap-plan` control whether a starter plan is generated.

Supported starter templates:
- `python` creates a Python-oriented config with `pyproject.toml`, `src/`, and `tests/` in the template metadata.
- `js` creates a JavaScript-oriented config with `package.json`, `src/`, and `tests/`.
- `generic` keeps the template language-agnostic.

---

## Model Configuration

- Model/backend selection is **registry-driven** from `llmstack_config.json` (`active_model` + `models` map), loaded by `llmstack/models/registry.py`.
- The active model resolves to a backend type and target model; supported backend types are:
  - `dflash`
  - `mlx`
  - `turboquant`
- All inference backends serve on `127.0.0.1:8787`; Headroom serves on `127.0.0.1:8789`.

### Model selection commands

```bash
# Show configured models and current active model
python -m llmstack.cli model list

# Switch active model (persists active_model in llmstack_config.json)
python -m llmstack.cli model use mlx-gemma4-12b

# Optional recommender
python -m llmstack.cli model recommend --use agentic
python -m llmstack.cli model recommend --use decode --apply
```

When `model use`/`recommend --apply` runs, llmstack syncs CCR and, if inference is already running on `:8787`, swaps it to the selected target model.

### Serving a specific model/backend

`python -m llmstack.cli serve [model_name]` accepts an optional model name. If provided and present in the registry, it updates `active_model`, syncs CCR, and serves that backend/model.

Examples:

```bash
# Start default DFlash wrapper behavior (or pass a DFlash model name)
bash bin/start_dflash_server.bash

# Wrapper default is mlx-gemma4-12b unless you pass a model name
bash bin/start_mlx_server.bash
bash bin/start_mlx_server.bash mlx-gemma4-12b

# Wrapper default is turboquant-qwen35b-moe unless overridden
bash bin/start_turboquant_server.bash
bash bin/start_turboquant_server.bash turboquant-qwen35b-moe
```

### CCR multi-model routing behavior

`llmstack/services/ccr_service.py` renders CCR config from the full model registry (multi-provider/multi-model), and routes:

- `default`
- `background`
- `think`
- `longContext`
- `webSearch`

to the currently active `<provider>,<target>` pair, with provider endpoints pinned to local Headroom (`http://127.0.0.1:8789/v1/chat/completions`).

### End-to-end switching examples

```bash
# Switch active model/backend first
python -m llmstack.cli model use turboquant-qwen35b-moe

# Then run interactive mode
bash bin/launch_ccr.bash
```

```bash
# Switch to MLX model/backend
python -m llmstack.cli model use mlx-gemma4-12b

# Then run autonomous Ralph mode
bash bin/launch_ralph.bash
```

---

## Task Schema (plan JSON)

Each task in the plan file has this structure:

```json
{
  "id": "task_01",
  "prompt": "Create a game board grid...",
  "file": "game.js",
  "mode": "agent",
  "context": ["index.html", "style.css"],
  "verify": "node --check game.js",
  "expect": ["createBoard", "renderBoard"],
  "require_change": true,
  "verification_plugins": ["python_lint"],
  "disable_plugins": ["suite"],
  "thinking_mode": "auto",
  "smoke": [
    "const fs=require('fs'); ...",
    "console.log('✓ smoke OK');"
  ],
  "status": "pending"
}
```

### Complete Field Reference

| Field | Type | Required | Description | Example |
|---|---|---|---|---|
| **`id`** | string | ✓ | Unique task identifier (prefix with `task_` for clarity). | `"task_01"`, `"task_setup"` |
| **`prompt`** | string | ✓ | Task description sent to Claude Code. Be specific about requirements, input/output format, and expected behavior. | `"Create a game board with functions createBoard() and renderBoard()"` |
| **`file`** | string | — | Primary output file for this task (relative path from `dev_root`). If omitted, Ralph treats it as a setup/config task. | `"game.js"`, `"src/utils.ts"`, `"index.html"` |
| **`mode`** | string | — | Execution mode. Default: `"agent"`. | `"agent"` = multi-turn refinement; `"direct"` = one-shot file generation |
| **`context`** | array[string] | — | Read-only reference files passed to Claude Code. Use for existing code that the task depends on. Ralph reads these files and passes them to the prompt. | `["index.html", "style.css", "utils.js"]` |
| **`strategy`** | string | — | Hints Ralph's executor selection logic. | `"edit"` → prefer **agent** (multi-turn edits); `"rewrite"` → prefer **direct** (one-shot generation) |
| **`verify`** | string | — | Shell command to check syntax/correctness after execution. Must exit 0 on success. If it fails, the task is rolled back and retried. Ralph runs this from `dev_root`. | `"node --check game.js"` |
| **`expect`** | array[string] | — | Feature markers: strings that **must** appear in `file` after execution (case-insensitive). Useful for verifying functions, classes, or keywords were created. | `["function createBoard", "const BOARD_SIZE"]` |
| **`require_change`** | boolean | — | Override global `require_change` config for this task. If `true`, the task **must** modify `file` or it fails (prevents no-ops). | `true` = fail if no change; `false` = allow no-op |
| **`verification_plugins`** | array[string] | — | Optional allow-list of plugin names to run for this task. If omitted, all matching enabled task-level plugins may run. | `["python_lint"]`, `["ruff", "unit_smoke"]` |
| **`disable_plugins`** | array[string] | — | Optional deny-list of plugin names to suppress for this task, even if they match globally. | `["suite"]`, `["python_lint"]` |
| **`thinking_mode`** | string | — | Optional per-task override for agentic reasoning. `off` keeps current behavior, `auto` enables adaptive thinking, `on` enables full thinking. | `"off"`, `"auto"`, `"on"` |
| **`smoke`** | array[string] or string | — | **Behavioral smoke test**: Node.js code to assert runtime behavior. Runs via `node -e` from `dev_root`. Nothing is written to the repo. Use to verify logic, APIs, or side effects. | `["const g=require('./game.js'); console.log(g.checkWin ? '✓' : '✗');"]` |
| **`priority`** | integer | — | Task priority for ordering (higher runs first). Non-numeric/missing values default to `0`. Ties keep the original plan order (stable). Honored by all loop modes. | `10` (urgent); `0` (default); `-1` (defer) |
| **`status`** | string | — | Execution status used for resume tracking. Ralph updates this after each run. Loop modes also use `"skipped"` (skipped by supervisor or already done). | `"pending"` (not started); `"completed"` (finished); `"skipped"` (skipped); `"failed"` (rolled back) |
| **`max_tokens`** | integer | — | Override default token limit (8192) for this task's responses. Use higher for large files, lower for quick tasks. | `4096`, `16384` |
| **`tools`** | array[string] | — | Explicitly set tools available to Claude Code for this task. If omitted, uses config's `agent_tools`. | `["Read", "Edit", "Write"]` |
| **`permission_mode`** | string | — | Override global `permission_mode` for this task. | `"default"`, `"acceptEdits"`, `"plan"`, `"auto"`, `"dontAsk"`, `"bypassPermissions"` |

### How to Write a Plan Manually

#### 1. Basic Structure

```json
{
  "tasks": [
    { "id": "...", "prompt": "...", ... },
    { "id": "...", "prompt": "...", ... }
  ]
}
```

#### 2. Minimal Task (direct generation)

```json
{
  "id": "task_01",
  "prompt": "Create a simple HTML page with a heading and a button.",
  "file": "index.html"
}
```

Ralph will:
- Use the default `mode` = `"agent"`
- No context files
- No verification (unless you add `verify`/`expect`/`smoke`)

#### 3. Task with Verification

```json
{
  "id": "task_02",
  "prompt": "Write a function isEven(n) that returns true if n is even.",
  "file": "utils.js",
  "verify": "node --check utils.js",
  "expect": ["function isEven", "return n % 2"],
  "smoke": [
    "const {isEven} = require('./utils.js');",
    "console.assert(isEven(2) === true, 'isEven(2) failed');",
    "console.assert(isEven(3) === false, 'isEven(3) failed');",
    "console.log('✓ isEven tests passed');"
  ]
}
```

Ralph will:
1. **Verify syntax** (`node --check`)
2. **Check markers** (`expect`)
3. **Run smoke test** (assertions)
4. **Commit** only if all pass; **rollback** if any fail

#### 4. Task with Context (editing existing file)

```json
{
  "id": "task_03",
  "prompt": "The UI needs a score display. Add a scoreDisplay() function to game.js that updates the HTML.",
  "file": "game.js",
  "context": ["index.html"],
  "mode": "agent",
  "verify": "node --check game.js",
  "expect": ["scoreDisplay", "innerHTML"],
  "require_change": true
}
```

Ralph will:
- Read `index.html` and include it in the prompt (for reference)
- Run Claude Code in **agent mode** (multi-turn, so it can refine)
- Require that `game.js` be **modified** (not left as-is)
- Verify the function exists and uses DOM manipulation

#### 5. Chaining Tasks (context from previous)

```json
{
  "id": "task_04",
  "prompt": "Integrate the score display into the game loop. Call scoreDisplay() after each move.",
  "file": "game.js",
  "context": ["game.js"],
  "mode": "agent",
  "verify": "node --check game.js",
  "expect": ["scoreDisplay()"],
  "require_change": true,
  "smoke": [
    "const code = require('fs').readFileSync('game.js', 'utf8');",
    "console.assert(code.includes('scoreDisplay()'), 'scoreDisplay() not called');",
    "console.log('✓ scoreDisplay integrated');"
  ]
}
```

#### 6. Direct Mode (one-shot, large file)

```json
{
  "id": "task_05",
  "prompt": "Create a complete AI player. Implement minimax algorithm to calculate best move.",
  "file": "ai.js",
  "mode": "direct",
  "context": ["game.js"],
  "verify": "node --check ai.js",
  "expect": ["minimax", "calculateBestMove"],
  "smoke": [
    "const ai = require('./ai.js');",
    "const result = ai.calculateBestMove([0, 1, 2, null, null, null, null, null, null]);",
    "console.log(`Best move: ${result}; Type: ${typeof result}`);",
    "console.assert(typeof result === 'number', 'calculateBestMove must return a number');"
  ]
}
```

Ralph will:
- Use **direct mode** (one-shot generation, not multi-turn)
- Generate the complete `ai.js` file in one response
- No multi-turn refinement (faster, but less iterative)

---

---

## Advanced: Executor Selection

Ralph chooses between **two executors** for each task:

### **Agent Mode** (default)

- Multi-turn conversation with Claude Code
- Suitable for: complex logic, refactoring, multi-file coordination
- Slower but iterative — Claude Code can ask for clarification, refine, and retry
- Used when:
  - `mode == "agent"` (explicit), or
  - `strategy == "edit"`, or
  - `file` is large (> `size_threshold_bytes`), or
  - No `mode` specified (default)

### **Direct Mode**

- One-shot file generation
- Suitable for: new files, templates, self-contained implementations
- Faster but no multi-turn refinement
- Used when:
  - `mode == "direct"` (explicit), or
  - `strategy == "rewrite"`, or
  - `file` is small (< `size_threshold_bytes`)

### Example Selection Logic

```json
{
  "id": "task_A",
  "file": "index.html",
  "mode": "direct"
  // → Uses DIRECT (explicit)
}

{
  "id": "task_B",
  "file": "game_logic.js",
  "context": ["utils.js"],
  "mode": "agent"
  // → Uses AGENT (explicit)
}

{
  "id": "task_C",
  "file": "big_lib.ts",
  "strategy": "rewrite"
  // → Uses DIRECT (strategy hint + likely large file)
}

{
  "id": "task_D",
  "prompt": "Fix the collision detection..."
  // → Uses AGENT (default; multi-turn refinement for complex logic)
}
```

---

### Verification Gates Explained

Ralph applies **6 layers** to every task after execution:

```
Task executed
    ↓
1. Shell verify (syntax)  ← does `verify` command succeed?
    ↓
2. Feature markers       ← do all `expect` strings appear in file?
    ↓
3. Change gate          ← was `file` actually modified?
    ↓
4. Wiring check         ← any orphan/missing JS files?
    ↓
5. Smoke test           ← does `smoke` code pass?
    ↓
6. LLM review (optional) ← does weak model approve the diff?
    ↓
[✓ Pass → Commit] or [✗ Fail → Rollback & Retry]
```

### Editing a Plan Mid-Run

If a task fails and you want to **modify the plan** before resuming:

1. **Stop Ralph** (Ctrl+C)
2. **Edit** the plan file (e.g., fix the `prompt`, add more context)
3. **Keep the same `id`** and `status` (don't change or Ralph will re-run everything)
4. **Re-run** `bash bin/launch_ralph.bash` — Ralph will resume from where it left off

Example:
```json
{
  "id": "task_02",
  "prompt": "ORIGINAL: Write a function isEven...",  ← failed
  "status": "pending"  ← Ralph will retry
}
```

↓ Edit to:

```json
{
  "id": "task_02",
  "prompt": "FIXED: Write a function isEven(n) that checks if n is divisible by 2. Add proper error handling.",  ← improved prompt
  "status": "pending"  ← Ralph will retry with new prompt
}
```

---

## Loop Modes

By default Ralph runs a fixed plan once, top to bottom (`plan` mode). The `loop_mode`
config key lets you switch the **task-selection strategy** without changing anything
else about verification, executors, or gates. All four modes share the same task
schema, the same 6-layer verification pipeline, and the same git checkpointing.

| Mode | When to use | Task source | Stops when |
|------|-------------|-------------|-----------|
| **`plan`** | One-off builds from a written plan (classic behavior). | `plan_file` | All tasks completed/skipped |
| **`continuous`** | Long-running worker: drop tasks into a queue file and Ralph keeps draining it. | `continuous_queue_file` (polled) | You stop it (Ctrl+C) |
| **`watch`** | Guardrail while you code: auto-fix `.py` files as you save them. | Filesystem events under `watch_root` | You stop it (Ctrl+C) |
| **`supervised`** | Human-in-the-loop: approve/skip each task before it runs. | `plan_file` | All tasks resolved, or you quit at a prompt |

Select a mode in `llmstack_config.json`:

```json
{ "loop_mode": "continuous" }
```

### Task Priority (all modes)

Add an integer `priority` to any task to reorder execution — **higher runs first**.
Missing or non-numeric priorities default to `0`, and ties preserve the original
order in the file (stable sort). This works in every loop mode.

```json
{
  "tasks": [
    { "id": "t1", "prompt": "Nice-to-have refactor", "file": "a.py", "priority": 0 },
    { "id": "t2", "prompt": "Critical hotfix",        "file": "b.py", "priority": 10 },
    { "id": "t3", "prompt": "Cleanup",                "file": "c.py", "priority": -5 }
  ]
}
```
Execution order above: `t2` (10) → `t1` (0) → `t3` (-5).

### Smart Retry (all modes)

When a task fails its `verify` command (or another deterministic gate), Ralph captures
the failure detail (stderr/stdout, missing markers, etc.) and injects it into the
**next retry prompt** — so the model sees *why* it failed and can correct itself.
No configuration is required; it applies automatically within the existing
`max_retries` / `max_resumes` budget. The injected feedback is truncated to keep the
prompt focused.

### 1. Continuous Mode

Ralph runs your plan, then **keeps watching** `continuous_queue_file`. Append new
tasks (as a JSON list or a `{"tasks": [...]}` object) and they are picked up on the
next poll — no restart needed. Completed tasks have their `status` written back to the
queue file, so you can inspect progress externally.

```json
{
  "loop_mode": "continuous",
  "continuous_queue_file": "task_queue.json",
  "continuous_poll_seconds": 2
}
```

Then run Ralph and feed it tasks from another terminal:

```bash
# Terminal 1
bash bin/launch_ralph.bash

# Terminal 2 — append a task to the queue at any time
cat > my_project/task_queue.json <<'EOF'
{ "tasks": [
  { "id": "q1", "prompt": "Add a health-check endpoint", "file": "server.py",
    "verify": "python -m py_compile server.py" }
] }
EOF
```

Notes:
- The queue file path is **relative to the current working directory** (typically
  `dev_root`), matching `plan_file` behavior.
- Invalid JSON is tolerated: Ralph prints a warning and keeps waiting for a valid file,
  so a half-written save won't crash the loop.
- Ralph reloads the queue only when the file's modification time changes, so polling is
  cheap.

### 2. Watch Mode

Ralph monitors `watch_root` for changes to `.py` files and **auto-enqueues a fix task**
for each edited file. Each generated task verifies with `py_compile`, so a syntax error
you just introduced gets flagged (and repaired) immediately.

```json
{
  "loop_mode": "watch",
  "watch_root": ".",
  "watch_queue_file": "task_queue.json",
  "watch_poll_seconds": 2,
  "watch_debounce_seconds": 0.5
}
```

```bash
bash bin/launch_ralph.bash
# ...now edit any .py under watch_root and save; Ralph reacts automatically.
```

Behavior:
- Uses OS filesystem events **plus** an mtime-based scan fallback (more reliable on
  macOS, where some editors write via atomic-rename).
- **Debounced**: several rapid saves of the same file collapse into a single task.
- **Ignored automatically**: non-`.py` files, the queue file itself, and anything under
  `.git`, `node_modules`, `env`, `__pycache__`, `logs`, and `old`.
- You can still append tasks to `watch_queue_file` manually — they're processed too.
- Requires the `watchdog` package (already in the project venv).

### 3. Supervised Mode

Ralph pauses before each task and shows a preview (id, priority, file, label, prompt),
then waits for your decision at the console.

```json
{
  "loop_mode": "supervised",
  "supervised_approval_mode": "console"
}
```

At each prompt (`Approve task? [a]pprove / [s]kip / [q]uit:`):

| Input | Aliases | Effect |
|-------|---------|--------|
| **approve** | `a`, `approve`, `y`, `yes` | Run the task through the normal pipeline. |
| **skip** | `s`, `skip`, `n`, `no` | Mark the task `skipped`, persist it, move on. |
| **quit** | `q`, `quit`, `stop` | Stop the services and end the run cleanly. |

Priority ordering still applies, so higher-priority tasks are presented first.

---

## Execution Flow

1. **Startup** (`bin/launch_ralph.bash`):
  - Activate virtualenv
  - Launch the Python CLI wrapper
  - Execute `python3 -m llmstack.cli run`

2. **Orchestrator** (`llmstack.cli run`):
  - **Service startup**: `ServiceStack` boots DFlash, Headroom, patches CCR, and pretrusts `dev_root`
  - **Server boot**: DFlash (`:8787`) loads model into RAM (~5–10 min on first run)
  - **Cache warm-up**: Run a dummy agentic request to populate prefix cache
  - **Task loop**: For each pending task:
     - Choose executor (agent or direct)
     - Execute task (with retries/resumes)
     - Apply 6-layer verification
     - Commit to git if verified
     - Mark complete or halt on failure

3. **Verification Gates** (applied after task execution):
   - **Layer 1**: Shell verify (syntax check)
   - **Layer 2**: Feature markers (string presence)
   - **Layer 3**: Change gate (file modification required?)
   - **Layer 4**: Wiring check (orphan JS? missing refs?)
   - **Layer 5**: Behavioral smoke (runtime assertions)
   - **Layer 6**: LLM review (optional critique)

4. **On Failure**:
  - **TIMEOUT** or **AGENT_ERROR** with valid progress → **resume** (up to `max_resumes`)
  - **FORMAT_ERROR** (provider/transport formatting) → internal agent retry with stricter format directive (up to `agent_format_retries`)
    - If task has `"on_format_error": "direct_context_fallback"`, Ralph falls back to direct generation on `file + context`, then applies standard verification gates
  - **ALREADY_DONE** + `allow_already_done_if_verified=true` → verify with `require_change=false` for that attempt; if gates pass, task is marked complete
   - **VERIFY_FAILED** or no progress → **retry** (up to `max_retries`)
   - After max attempts → **halt** and print WIP state

---

## Logs

| File | Description |
|---|---|
| `logs/dflash_server.log` | Raw DFlash server output (includes HTTP access logs). |
| `logs/ralph_debug.log` | Detailed task execution log (agentic input/output, direct generation rounds, gate results). Controlled by `debug_log` config. |
| `logs/dflash_timings.csv` | CSV with request-level metrics (timestamp, tokens, latency, cache hits). |
| `.claude/` (gitignored) | Plans, logs, and behavioral smoke sources (not part of the repository). |

---

## Troubleshooting

### DFlash server won't start
- Ensure MLX is compatible (Apple Silicon + macOS 12.2+)
- Check memory: `free -h` (need ~16 GB available for 27B model)
- Restart: `bash bin/launch_ralph.bash`

### Claude Code timeout
- Increase `timeout_seconds` in `llmstack_config.json`
- Check network: ensure Headroom (`8789`) is reachable

### Task verification fails
- Enable `debug_log` and review detailed gate output
- Check `expect` markers match actual code
- Run `smoke` tests locally: `node -e "..."`

### Git state corrupted
- Ralph automatically resets to the last checkpoint on error
- Manual fix: `cd ./pacman_clone && git reset --hard HEAD`

---

## References

- [MLX Documentation](https://github.com/ml-explore/mlx)
- [Claude Code Documentation](https://docs.anthropic.com/claude-code)
- [DFlash Speculative Decoding - Article](https://arxiv.org/abs/2602.06036)
- [TurboQuant: Online Vector Quantization with Near-optimal Distortion Rate - Article](https://arxiv.org/abs/2504.19874)
- [Dflash Server](https://github.com/z-lab/dflash)
- [TurboQuant MLX](https://github.com/arozanov/turboquant-mlx)
- [TurboQuant MLX full](https://github.com/matt-k-wong/turboquant-mlx-full)
- [TurboQuant Plus](https://github.com/TheTom/turboquant_plus)
- [Headroom Compression](https://github.com/headroomlabs-ai/headroom)
