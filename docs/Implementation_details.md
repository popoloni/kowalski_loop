
# Implementation details

Here is the complete, consolidated implementation. The core change: **self-contained file tasks now run in `direct` mode** (one small request straight to dflash — no agent loop, no 33k context, no OOM), while the agent path is kept only as a fallback. I've also applied the **12 GB prefix-cache** fix that prevents the Metal OOM crash.

---

### 1. `~/local-llm-workspace/llmstack_config.json`

```json
{
  "dev_root": "./pacman_clone",
  "plan_file": "./pacman_clone/.claude/plans/pacman_plan.json",
  "permission_mode": "acceptEdits",
  "max_turns": 40,
  "task_timeout": 1800,
  "max_retries": 3
}
```

---

### 2. `~/.claude-code-router/config.json`

Points at Headroom (`:8789`), re-adds `NON_INTERACTIVE_MODE` + `API_TIMEOUT_MS`, and keeps `max_tokens` at 8192 so the **agentic fallback** isn't truncated mid-Write (direct mode doesn't use this).

```json
{
  "LOG": true,
  "HOST": "127.0.0.1",
  "NON_INTERACTIVE_MODE": true,
  "API_TIMEOUT_MS": 1200000,
  "Providers": [
    {
      "name": "dflash",
      "api_base_url": "http://127.0.0.1:8789/v1/chat/completions",
      "api_key": "dflash-local",
      "timeout": 1200000,
      "models": ["mlx-community/Qwen3.6-27B-4bit"],
      "transformer": {
        "use": [ ["maxtoken", { "max_tokens": 8192 }], "enhancetool" ],
        "context_window": 32000,
        "system_prompt_caching": true
      }
    }
  ],
  "Router": {
    "default": "dflash,mlx-community/Qwen3.6-27B-4bit",
    "background": "dflash,mlx-community/Qwen3.6-27B-4bit",
    "think": "dflash,mlx-community/Qwen3.6-27B-4bit",
    "longContext": "dflash,mlx-community/Qwen3.6-27B-4bit",
    "longContextThreshold": 30000,
    "webSearch": "dflash,mlx-community/Qwen3.6-27B-4bit"
  }
}
```

---

### 3. `~/local-llm-workspace/pacman_clone/.claude/settings.local.json`

(Used only by the agentic fallback / warm-up.)

```json
{
  "permissions": {
    "allow": ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "LS"]
  }
}
```

---

### 4. `~/local-llm-workspace/pacman_clone/.claude/plans/pacman_plan.json`

Tasks 9–22 now carry `mode: "direct"`, a primary `file`, and the `context` files to read. Direct mode regenerates **one file per task** — for modify tasks the target file is in `context` so the model preserves and extends it.

```json
{
  "project": "Pacman Clone",
  "tasks": [
    { "id": "1", "phase": "Phase 1: Foundation", "status": "completed",
      "prompt": "Set up the HTML skeleton — Create index.html with a <canvas> or grid-based <div> container for the game board, score display, lives counter, and a start/restart button. Link style.css and all JS files.",
      "verify": "test -f index.html && grep -q \"style.css\" index.html && grep -q \"game.js\" index.html" },
    { "id": "2", "phase": "Phase 1: Foundation", "status": "completed",
      "prompt": "Create the CSS base — Define the dark background, center the game board, style the score/lives UI, and set up the grid layout for the map cells. Match the classic arcade aesthetic (black background, blue walls).",
      "verify": "test -f style.css && test -s style.css" },
    { "id": "3", "phase": "Phase 1: Foundation", "status": "completed",
      "prompt": "Define the map data structure — Create map.js with a 2D array representing the original Pacman layout: walls, dots, power pellets, ghost house, and Pacman's starting position. Use numeric codes (0=empty, 1=wall, 2=dot, 3=power pellet, 4=ghost house).",
      "verify": "test -f map.js && node --check map.js" },
    { "id": "4", "phase": "Phase 2: Rendering", "status": "completed",
      "prompt": "Render the static map — Write a function in map.js that reads the 2D array and draws the grid on the canvas (or populates divs). Walls are blue rectangles, dots are small circles, power pellets are larger blinking circles.",
      "verify": "node --check map.js" },
    { "id": "5", "phase": "Phase 2: Rendering", "status": "completed",
      "prompt": "Build the game loop — Create game.js with a requestAnimationFrame-based game loop that calls update and render functions each frame. Include game states: idle, playing, paused, game-over, level-complete.",
      "verify": "test -f game.js && node --check game.js && grep -q \"requestAnimationFrame\" game.js" },
    { "id": "6", "phase": "Phase 3: Pacman", "status": "completed",
      "prompt": "Implement Pacman movement — In pacman.js, handle keyboard input (arrow keys) to set a direction buffer. Move Pacman cell-by-cell along the grid, respecting walls. Support direction queuing.",
      "verify": "test -f pacman.js && node --check pacman.js" },
    { "id": "7", "phase": "Phase 3: Pacman", "status": "completed",
      "prompt": "Add Pacman animation — Animate the mouth opening and closing while moving. Render Pacman as a yellow circle with a wedge cut out, oscillating the wedge angle each frame.",
      "verify": "node --check pacman.js" },
    { "id": "8", "phase": "Phase 3: Pacman", "status": "completed",
      "prompt": "Implement dot and power pellet eating — When Pacman overlaps a dot, remove it and add 10 points. Power pellet: add 50 points and trigger 'frightened' mode for all ghosts.",
      "verify": "node --check pacman.js && node --check game.js" },

    { "id": "9", "phase": "Phase 4: Ghosts", "status": "pending",
      "mode": "direct", "file": "ghosts.js", "context": ["map.js"],
      "prompt": "Create ghosts.js for a Pacman clone: define four ghosts (Blinky red, Pinky pink, Inky cyan, Clyde orange) as objects/classes with grid positions in the ghost house and a draw(ctx) method. Each ghost has its own movement-logic stub.",
      "verify": "test -f ghosts.js && node --check ghosts.js" },
    { "id": "10", "phase": "Phase 4: Ghosts", "status": "pending",
      "mode": "direct", "file": "ghosts.js", "context": ["ghosts.js", "map.js"],
      "prompt": "Add scatter mode to the ghosts: each ghost moves toward a different corner of the map, following the grid and choosing the direction that minimizes distance to its target corner at each intersection.",
      "verify": "node --check ghosts.js" },
    { "id": "11", "phase": "Phase 4: Ghosts", "status": "pending",
      "mode": "direct", "file": "ghosts.js", "context": ["ghosts.js", "map.js", "pacman.js"],
      "prompt": "Add chase mode targeting: Blinky targets Pacman's current tile; Pinky targets 4 tiles ahead of Pacman; Inky uses Blinky's and Pacman's positions; Clyde chases when far, scatters when close.",
      "verify": "node --check ghosts.js" },
    { "id": "12", "phase": "Phase 4: Ghosts", "status": "pending",
      "mode": "direct", "file": "ghosts.js", "context": ["ghosts.js", "game.js"],
      "prompt": "Add scatter/chase mode timing inside ghosts.js: toggle modes on a timer (scatter 7s, chase 20s, scatter 7s, chase 20s, chase 5s, chase forever), exposing an update(dt) the game loop can call.",
      "verify": "node --check ghosts.js && node --check game.js" },
    { "id": "13", "phase": "Phase 4: Ghosts", "status": "pending",
      "mode": "direct", "file": "ghosts.js", "context": ["ghosts.js", "pacman.js"],
      "prompt": "Add frightened mode: when triggered, ghosts turn blue and move randomly for ~7s with a flashing effect near the end. Expose a setFrightened() and an isFrightened flag; eaten frightened ghosts score 200/400/800/1600.",
      "verify": "node --check ghosts.js && node --check pacman.js" },
    { "id": "14", "phase": "Phase 4: Ghosts", "status": "pending",
      "mode": "direct", "file": "ghosts.js", "context": ["ghosts.js"],
      "prompt": "Add eye-return behavior: after a ghost is eaten, render only its floating eyes and route them back to the ghost house to revive the body.",
      "verify": "node --check ghosts.js" },
    { "id": "15", "phase": "Phase 5: Game Mechanics", "status": "pending",
      "mode": "direct", "file": "game.js", "context": ["game.js", "ghosts.js", "pacman.js"],
      "prompt": "Add collision detection in game.js: each frame, if Pacman overlaps a ghost, eat it if frightened, otherwise lose a life / end the game.",
      "verify": "node --check game.js && node --check ghosts.js" },
    { "id": "16", "phase": "Phase 5: Game Mechanics", "status": "pending",
      "mode": "direct", "file": "game.js", "context": ["game.js", "pacman.js"],
      "prompt": "Add lives and scoring in game.js: start with 3 lives, flash and reset positions on death, display current score and high score, and award a level-complete bonus.",
      "verify": "node --check game.js" },
    { "id": "17", "phase": "Phase 5: Game Mechanics", "status": "pending",
      "mode": "direct", "file": "game.js", "context": ["game.js", "map.js"],
      "prompt": "Add level progression in game.js: when all dots are cleared, reset the map, increase ghost speed, reduce frightened duration; after level 5 use power-pellet-only bonus rounds.",
      "verify": "node --check game.js && node --check map.js" },
    { "id": "18", "phase": "Phase 5: Game Mechanics", "status": "pending",
      "mode": "direct", "file": "ghosts.js", "context": ["ghosts.js"],
      "prompt": "Add ghost-house exit timing: ghosts leave one at a time with staggered delays and bounce inside the house before exiting.",
      "verify": "node --check ghosts.js" },
    { "id": "19", "phase": "Phase 6: Polish", "status": "pending",
      "mode": "direct", "file": "pacman.js", "context": ["pacman.js", "map.js"],
      "prompt": "Add tunnel handling in pacman.js: when Pacman exits one side of the map through a tunnel row, wrap to the opposite side.",
      "verify": "for f in *.js; do node --check \"$f\" || exit 1; done" },
    { "id": "20", "phase": "Phase 6: Polish", "status": "pending",
      "mode": "direct", "file": "game.js", "context": ["game.js"],
      "prompt": "Add Web Audio API sound effects in game.js: beeps for eating dots, power pellets, eating a ghost, death, and level complete, with a mute toggle.",
      "verify": "for f in *.js; do node --check \"$f\" || exit 1; done" },
    { "id": "21", "phase": "Phase 6: Polish", "status": "pending",
      "mode": "direct", "file": "game.js", "context": ["game.js"],
      "prompt": "Add canvas-drawn start and game-over screens in game.js: a 'PRESS START' prompt, and on game over show the final score and a restart control.",
      "verify": "node --check game.js && test -f index.html" },
    { "id": "22", "phase": "Phase 6: Polish", "status": "pending",
      "mode": "direct", "file": "game.js", "context": ["game.js", "ghosts.js"],
      "prompt": "Add visual polish in game.js: a 'READY!' text before each level, a score popup when a ghost is eaten, and timing tweaks to match the arcade feel.",
      "verify": "for f in *.js; do node --check \"$f\" || exit 1; done" }
  ]
}
```

---

### 5. `~/local-llm-workspace/ralph_loop.py`

Adds `run_direct_task`, dispatches on `mode`, fixes the **OOM** (12 GB cache + snapshot cap), skips the wasteful warm-up when no agentic tasks remain, and removes the duplicate import.

```python
import subprocess
import threading
import time
import json
import urllib.request
import os
import signal
import sys

# Long-request timeouts so Claude Code waits for slow local generations (agentic fallback).
os.environ.update({
    "API_TIMEOUT_MS": "1800000",
    "CLAUDE_STREAM_IDLE_TIMEOUT_MS": "1800000",
    "CLAUDE_ENABLE_BYTE_WATCHDOG": "0",
    "CLAUDE_ENABLE_STREAM_WATCHDOG": "0",
})
print(f"⏱️  [Ralph] API_TIMEOUT_MS={os.environ['API_TIMEOUT_MS']} forced.")

# ---------------- CONFIG ----------------
def load_config():
    cfg = {
        "dev_root": ".", "plan_file": "plan.json",
        "permission_mode": "acceptEdits", "max_turns": 40,
        "task_timeout": 1800, "max_retries": 3,
    }
    if os.path.exists("llmstack_config.json"):
        with open("llmstack_config.json") as f:
            cfg.update(json.load(f))
        print(f"🔧 [Ralph] Config loaded: Root='{cfg['dev_root']}', Plan='{cfg['plan_file']}'")
    else:
        print("⚠️ [Ralph] No llmstack_config.json found, using defaults.")
    return cfg

CONFIG     = load_config()
DEV_ROOT   = os.path.abspath(CONFIG["dev_root"])
PLAN_FILE  = CONFIG["plan_file"]
HEALTH_URL = "http://127.0.0.1:8787/v1/models"
DIRECT_URL = "http://127.0.0.1:8787/v1/chat/completions"   # dflash directly (no CCR/Headroom)
MODEL      = "mlx-community/Qwen3.6-27B-4bit"

STRICT_SYS_PROMPT = (
    "You drive a coding agent through a translation proxy that FAILS if a single "
    "assistant message mixes prose and tool calls. Rules:\n"
    "1. Do NOT narrate.\n"
    "2. NEVER write text AFTER a tool call in the same response.\n"
    "3. Prefer ONE tool call per response.\n"
    "4. For file-creation, write the file directly; do NOT read other files unless required.\n"
    "5. Do only the single atomic task, then stop."
)

DFLASH_CMD = [
    "dflash", "serve",
    "--model", MODEL,
    "--draft-model", "z-lab/Qwen3.6-27B-DFlash",
    "--host", "127.0.0.1", "--port", "8787",
    "--verify-mode", "adaptive",
    "--temp", "0.2",
    "--max-tokens", "4096",
    "--chat-template-args", '{"enable_thinking": false}',
    "--prefix-cache-max-entries", "64",
    "--prefix-cache-max-bytes", "12GB",      # was 24GB → caused Metal OOM at the 51.8GB wired limit
    "--max-snapshot-tokens", "16000",
    "--no-clear-cache-boundaries",
]


class RalphSupervisor:
    def __init__(self):
        self.server_process = None
        self._stop = False
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)

    # ---------- server lifecycle ----------
    def _ping(self, timeout=3):
        try:
            return urllib.request.urlopen(HEALTH_URL, timeout=timeout).getcode() == 200
        except Exception:
            return False

    def start_server(self):
        if self.server_process and self.server_process.poll() is None:
            return
        print("🚀 [Ralph] Starting DFlash server...")
        with open("dflash_server.log", "a") as log:
            self.server_process = subprocess.Popen(
                DFLASH_CMD, stdout=log, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        self.wait_for_health()

    def wait_for_health(self, boot_timeout=600):
        print("⏳ [Ralph] Waiting for model to load into RAM...")
        start = time.time()
        while not self._stop:
            if self._ping():
                print("✅ [Ralph] Server online and healthy.")
                return True
            if self.server_process.poll() is not None:
                print("❌ [Ralph] Server died during boot. Restarting...")
                self.server_process = None
                return self.start_server()
            if time.time() - start > boot_timeout:
                print("❌ [Ralph] Server boot timed out.")
                return False
            time.sleep(5)

    def restart_server(self):
        print("♻️  [Ralph] Hard-restarting DFlash...")
        self.kill_server(); time.sleep(3); self.start_server()

    def kill_server(self):
        if self.server_process:
            try:
                os.killpg(os.getpgid(self.server_process.pid), signal.SIGTERM)
                self.server_process.wait(timeout=15)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(os.getpgid(self.server_process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.server_process = None

    # ---------- DIRECT generation (no agent, no CCR/Headroom) ----------
    def _strip_fences(self, t):
        t = t.strip()
        if t.startswith("```"):
            t = t.split("\n", 1)[1] if "\n" in t else ""
            if t.rstrip().endswith("```"):
                t = t.rstrip()[:-3]
        return t.strip() + "\n"

    def run_direct_task(self, task):
        out_file = task["file"]
        context = task.get("context", [])
        ctx = ""
        for cf in context:
            p = os.path.join(DEV_ROOT, cf)
            if os.path.exists(p):
                with open(p) as f:
                    ctx += f"\n\n--- existing {cf} ---\n{f.read()}"
        user = task["prompt"]
        if ctx:
            user += f"\n\nRelevant existing files:{ctx}"
        if out_file in context:
            user += (f"\n\nYou are MODIFYING {out_file}: preserve ALL existing functionality "
                     f"and add the requested behavior. Output the COMPLETE updated file.")
        user += f"\n\nOutput ONLY the complete contents of {out_file}. No markdown fences, no commentary."

        body = json.dumps({
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "You are a precise code generator. Output only raw, valid file contents."},
                {"role": "user", "content": user},
            ],
            "max_tokens": task.get("max_tokens", 4096),
            "temperature": 0.2,
            "stream": False,
        }).encode()

        print(f"✍️  [Ralph] Direct-generating {out_file} (context: {context or 'none'})")
        req = urllib.request.Request(DIRECT_URL, data=body, headers={"Content-Type": "application/json"})
        try:
            resp = json.load(urllib.request.urlopen(req, timeout=CONFIG["task_timeout"]))
        except Exception as e:
            print(f"❌ [Ralph] Direct call failed: {e}")
            return "TIMEOUT"
        try:
            code = self._strip_fences(resp["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError):
            print(f"❌ [Ralph] Unexpected response: {str(resp)[:300]}")
            return "BAD_OUTPUT"
        with open(os.path.join(DEV_ROOT, out_file), "w") as f:
            f.write(code)
        print(f"📝 [Ralph] Wrote {out_file} ({len(code)} bytes).")
        return "OK" if self._verify(task) else "VERIFY_FAILED"

    # ---------- cache warm-up (agentic only) ----------
    def warm_up_cache(self):
        print("🔥 [Ralph] Warming the agentic prefix cache...")
        try:
            subprocess.run(
                ["ccr", "code", "-p", "Reply with OK only.",
                 "--output-format", "json",
                 "--permission-mode", CONFIG["permission_mode"], "--max-turns", "1"],
                cwd=DEV_ROOT, capture_output=True, text=True, timeout=CONFIG["task_timeout"])
            print("✅ [Ralph] Cache warm.")
        except Exception as e:
            print(f"⚠️  [Ralph] Warm-up skipped ({e}).")

    # ---------- AGENTIC execution (fallback for non-direct tasks) ----------
    def _retry_directive(self, attempt):
        if attempt <= 1: return ""
        if attempt == 2: return " RETRY: be terse — one tool call to write the file, then stop."
        return " FINAL RETRY: a single Write call only, minimal but valid."

    def execute_task(self, task, attempt=1):
        prompt = task["prompt"]
        sys_prompt = STRICT_SYS_PROMPT + self._retry_directive(attempt)
        max_turns = CONFIG["max_turns"] if attempt == 1 else 6
        cmd = ["ccr", "code", "-p", prompt, "--output-format", "json",
               "--permission-mode", CONFIG["permission_mode"],
               "--max-turns", str(max_turns), "--append-system-prompt", sys_prompt]
        tools = task.get("tools")
        if tools:
            cmd += ["--allowedTools", *tools]
        print(f"⚙️  [Ralph] Running Task {task.get('id')} (agentic) in {DEV_ROOT}")
        server_crashed = threading.Event()
        proc = subprocess.Popen(cmd, cwd=DEV_ROOT, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=os.setsid)
        threading.Thread(target=self._watch_during_task, args=(proc, server_crashed), daemon=True).start()
        try:
            out, err = proc.communicate(timeout=CONFIG["task_timeout"])
        except subprocess.TimeoutExpired:
            self._kill_proc(proc); return "TIMEOUT"
        if server_crashed.is_set():
            return "SERVER_CRASH"
        return self._evaluate(out, err, task)

    def _evaluate(self, stdout, stderr, task):
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, TypeError):
            print("❌ [Ralph] Could not parse CLI JSON:", (stdout or stderr or "<empty>")[:300])
            return "BAD_OUTPUT"
        result = None
        if isinstance(data, list):
            for msg in data:
                if isinstance(msg, dict) and msg.get("type") == "result":
                    result = msg
        elif isinstance(data, dict):
            result = data
        if not result:
            return "BAD_OUTPUT"
        subtype, is_error = result.get("subtype"), result.get("is_error")
        if is_error or subtype != "success":
            detail = result.get("result") or result.get("error") or ""
            if isinstance(detail, (dict, list)): detail = json.dumps(detail)
            print(f"ℹ️  [Ralph] is_error={is_error}, subtype={subtype}. Detail: {str(detail)[:300]}")
        if subtype in ("error_max_turns", "error_during_execution"):
            return "AGENT_ERROR"
        return "OK" if self._verify(task) else "VERIFY_FAILED"

    def _watch_during_task(self, proc, server_crashed):
        fails = 0
        while proc.poll() is None:
            if not self._ping():
                fails += 1
                if fails >= 3:
                    print("🔥 [Ralph] DFlash died DURING the task — aborting agent.")
                    server_crashed.set(); self._kill_proc(proc); return
            else:
                fails = 0
            time.sleep(3)

    def _kill_proc(self, proc):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass

    # ---------- verify / checkpoint ----------
    def _verify(self, task):
        verify_cmd = task.get("verify")
        if not verify_cmd:
            print("⚠️  [Ralph] No 'verify' for this task — skipping gate.")
            return True
        print(f"🔎 [Ralph] Verifying: {verify_cmd}")
        r = subprocess.run(verify_cmd, shell=True, cwd=DEV_ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"❌ [Ralph] Verification FAILED:\n{r.stdout}\n{r.stderr}")
        return r.returncode == 0

    def git_checkpoint(self, task):
        subprocess.run(["git", "init"], cwd=DEV_ROOT, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=DEV_ROOT, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"Ralph checkpoint: task {task.get('id')} verified"],
                       cwd=DEV_ROOT, capture_output=True)
        print(f"📦 [Ralph] Git checkpoint saved for task {task.get('id')}.")

    def mark_complete(self, plan, task):
        task["status"] = "completed"
        with open(PLAN_FILE, "w") as f:
            json.dump(plan, f, indent=2)

    # ---------- main loop ----------
    def run_plan(self):
        if not os.path.exists(PLAN_FILE):
            print(f"❌ [Ralph] Plan file '{PLAN_FILE}' not found."); return
        with open(PLAN_FILE) as f:
            plan = json.load(f)
        tasks = plan.get("tasks", [])
        print(f"📋 [Ralph] Loaded {len(tasks)} tasks.")

        pending = [t for t in tasks if t.get("status") != "completed"]
        if any(t.get("mode") != "direct" for t in pending):
            self.warm_up_cache()           # only needed when an agentic task remains

        for task in tasks:
            if task.get("status") == "completed":
                print(f"⏭️  [Ralph] Skipping Task {task.get('id')} (completed)"); continue

            attempts, done = 0, False
            while not done and attempts < CONFIG["max_retries"] and not self._stop:
                if not self._ping():
                    self.restart_server()
                attempts += 1
                print(f"▶️  [Ralph] Task {task.get('id')} — attempt {attempts}")
                if task.get("mode") == "direct":
                    outcome = self.run_direct_task(task)
                else:
                    outcome = self.execute_task(task, attempt=attempts)

                if outcome == "OK":
                    self.git_checkpoint(task)
                    self.mark_complete(plan, task)
                    print(f"✅ [Ralph] Task {task.get('id')} COMPLETE & verified.")
                    done = True
                elif outcome == "SERVER_CRASH":
                    print("♻️  [Ralph] Server crash — restarting; retry won't count.")
                    self.restart_server()
                    attempts -= 1                    # a crash is not an agent failure
                else:
                    print(f"⚠️  [Ralph] Task {task.get('id')} -> {outcome}. Retry in 10s.")
                    time.sleep(10)

            if not done:
                print(f"🚨 [Ralph] Task {task.get('id')} NOT completed. Halting (NOT marked done).")
                self.shutdown()
                return

        print("\n🎉 [Ralph] All tasks verified and committed!")
        self.shutdown()

    def shutdown(self, signum=None, frame=None):
        self._stop = True
        print("\n🛑 [Ralph] Shutting down infrastructure...")
        self.kill_server()
        sys.exit(0)


if __name__ == "__main__":
    ralph = RalphSupervisor()
    ralph.start_server()
    ralph.run_plan()
```

That completes `ralph_loop.py`. Now the remaining two scripts.

---

### 6. `~/local-llm-workspace/ralph_launcher.bash`

Full launcher with the **correct** Headroom wiring (`OPENAI_TARGET_API_URL`), the isolated 3.13 subshell, kill-and-restart, and a hard pre-flight that aborts if Headroom isn't routing to dflash.

```bash
#!/bin/bash
set -e

echo "🤖 Booting Ralph Unattended Agent System..."

# 1. Must run from the workspace
if [ ! -d "env" ]; then
  echo "❌ Error: virtualenv 'env' not found. Run this from ~/local-llm-workspace."
  exit 1
fi
source env/bin/activate

# 2. Force local model: clear cloud keys
unset ANTHROPIC_AUTH_TOKEN
unset ANTHROPIC_API_KEY

# 3. Claude Code long-request timeouts (agentic fallback)
export API_TIMEOUT_MS=1200000
export CLAUDE_STREAM_IDLE_TIMEOUT_MS=1200000
export CLAUDE_ENABLE_BYTE_WATCHDOG=0
export CLAUDE_ENABLE_STREAM_WATCHDOG=0

# 4. Versions
echo "🔎 Versions:"
claude --version 2>/dev/null || echo "  (claude not found)"
ccr -v 2>/dev/null || ccr version 2>/dev/null || echo "  (ccr version unknown)"

# 5. Pre-seed folder trust
python3 - <<'PYEOF'
import json, os
try:
    dev_root = json.load(open("llmstack_config.json")).get("dev_root", "./pacman_clone")
except Exception:
    dev_root = "./pacman_clone"
path = os.path.abspath(dev_root)
cc = os.path.expanduser("~/.claude.json")
try:
    data = json.load(open(cc))
except (FileNotFoundError, json.JSONDecodeError):
    data = {}
proj = data.setdefault("projects", {}).setdefault(path, {})
proj["hasTrustDialogAccepted"] = True
proj["hasCompletedProjectOnboarding"] = True
json.dump(data, open(cc, "w"), indent=2)
print(f"🔐 Pre-trusted folder: {path}")
PYEOF

# 6. Headroom compression proxy (own 3.13 venv) → upstream = dflash.
#    Optional for an all-direct plan (direct tasks hit dflash :8787 directly),
#    but kept up so the agentic fallback also gets compression.
pkill -f "headroom proxy" 2>/dev/null || true
sleep 1
: > headroom.log
(
  unset VIRTUAL_ENV PYTHONPATH PYTHONHOME          # scrub 3.14 leakage into the 3.13 process
  export OPENAI_TARGET_API_URL="http://127.0.0.1:8787"   # dflash ORIGIN; Headroom appends /v1/chat/completions
  export OPENAI_API_KEY="dflash-local"
  export HEADROOM_TELEMETRY=off
  exec ~/headroom-env/bin/headroom proxy --port 8789 --code-aware --no-telemetry
) >> headroom.log 2>&1 &
sleep 6

if ! curl -s -o /dev/null http://127.0.0.1:8789/health; then
  echo "❌ Headroom not responding on :8789 — see headroom.log"; tail -n 20 headroom.log; exit 1
fi
if ! grep -q "127.0.0.1:8787" headroom.log; then
  echo "❌ Headroom upstream NOT pointed at dflash (expected '→ http://127.0.0.1:8787')."
  grep -A6 "Routing:" headroom.log 2>/dev/null || tail -n 20 headroom.log
  exit 1
fi
echo "🗜️  Headroom proxy on :8789 → dflash :8787 (compression + code-aware ON)"

# 7. Restart the router (for the agentic fallback path)
echo "🔄 Restarting Claude Code Router daemon..."
ccr restart

# 8. Hand over to the orchestrator (it starts dflash and runs the plan)
echo "🚀 Handing over control to Ralph Orchestrator..."
python3 ralph_loop.py
```

---

### 7. `~/local-llm-workspace/start_headroom.sh` (standalone, for manual testing)

```bash
#!/bin/bash
if [ ! -d "$HOME/headroom-env" ]; then
  echo "❌ ~/headroom-env not found"; exit 1
fi
pkill -f "headroom proxy" 2>/dev/null || true
sleep 1
: > headroom.log
(
  unset VIRTUAL_ENV PYTHONPATH PYTHONHOME
  export OPENAI_TARGET_API_URL="http://127.0.0.1:8787"
  export OPENAI_API_KEY="dflash-local"
  export HEADROOM_TELEMETRY=off
  exec ~/headroom-env/bin/headroom proxy --port 8789 --code-aware --no-telemetry
) >> headroom.log 2>&1 &
sleep 6
echo "Routing check:"; grep -A6 "Routing:" headroom.log || tail -n 20 headroom.log
echo "Test:  curl -s http://127.0.0.1:8789/v1/chat/completions -H 'Content-Type: application/json' \\"
echo "         -d '{\"model\":\"mlx-community/Qwen3.6-27B-4bit\",\"messages\":[{\"role\":\"user\",\"content\":\"say OK\"}],\"max_tokens\":5}'"
```

---

### Unchanged files (keep your current versions)

- `dflash_dashboard.py` and `start_dashboard.sh` — they read `dflash_server.log` on `:8787` directly, so they still work as-is. Direct mode will show up as fast, small-`prompt` calls.
- `~/.claude/settings.json` env block and `update_stack.sh` — no changes.

### Run order

```bash
cd ~/local-llm-workspace
chmod +x ralph_launcher.bash start_headroom.sh
./ralph_launcher.bash          # terminal 1
./start_dashboard.sh           # terminal 2 (optional)
```

### What to expect now (and the one caveat)

- **Task 9** runs as a single direct call: the dflash log should show a small prompt (a few hundred tokens + `map.js`), not 22–34k, and `ghosts.js` is written by Ralph and gated by `node --check`. No tool loop, no max-turns, and the 12 GB cache keeps `mlx_peak` well under the 51.8 GB wired limit, so **no more Metal OOM**.
- **Caveat for the modify tasks (10–22):** direct mode regenerates *one whole file* per task. For each modify task the target file is in `context` and the prompt says "preserve all existing functionality and add X," but a local 27B can still occasionally drop an earlier feature when it rewrites. That's why every task is git-checkpointed — if task 11 regresses something from task 10, `git -C pacman_clone reset --hard HEAD~1` rolls it back, and you can re-run. If a task genuinely needs two files edited together (e.g., a future cross-file change), split it into two single-file direct tasks rather than reaching for the agent, which is what kept crashing.

Want me to add a tiny `--dry-run` flag to `run_direct_task` that prints the assembled prompt + estimated token count per task (without calling the model), so you can sanity-check the `context` sizes before a full run?

# Fixes

Your diagnosis is exactly right. `ghosts.js` grew 7.5 KB → 15 KB, and a 15 KB file is ~5–6k tokens — past the `max_tokens: 4096` output cap. So the model's output was cut mid-file (`Unexpected end of input` / `missing )`), and each retry regenerated the *same* oversized file and truncated again. Two fixes: **raise the cap** and **auto-continue when the model hits it** instead of restarting.

## Fix 1 — raise the server cap

In `ralph_loop.py`, `DFLASH_CMD`, bump `--max-tokens` so the request isn't clamped:

```python
    "--max-tokens", "8192",
```

## Fix 2 — continuation logic in `run_direct_task`

Replace your current `run_direct_task` with this version (it adds a `_post_chat` helper and a continuation loop that stitches truncated output instead of failing). Also pass `attempt` from the dispatch.

```python
MAX_CONTINUATIONS = 6   # add near the top with the other constants

    def _post_chat(self, messages, max_tokens):
        body = json.dumps({
            "model": MODEL, "messages": messages,
            "max_tokens": max_tokens, "temperature": 0.2, "stream": False,
        }).encode()
        req = urllib.request.Request(DIRECT_URL, data=body, headers={"Content-Type": "application/json"})
        resp = json.load(urllib.request.urlopen(req, timeout=CONFIG["task_timeout"]))
        choice = resp["choices"][0]
        return (choice["message"]["content"] or ""), choice.get("finish_reason", "stop")

    def run_direct_task(self, task, attempt=1):
        out_file = task["file"]
        context = task.get("context", [])
        ctx = ""
        for cf in context:
            p = os.path.join(DEV_ROOT, cf)
            if os.path.exists(p):
                with open(p) as f:
                    ctx += f"\n\n--- existing {cf} ---\n{f.read()}"
        user = task["prompt"]
        if ctx:
            user += f"\n\nRelevant existing files:{ctx}"
        if out_file in context:
            user += (f"\n\nYou are MODIFYING {out_file}: preserve ALL existing functionality "
                     f"and add the requested behavior. Output the COMPLETE updated file.")
        if attempt > 1:
            user += ("\n\nNOTE: the previous attempt produced invalid/truncated code. "
                     "Produce the COMPLETE, syntactically valid file this time.")
        user += f"\n\nOutput ONLY the complete contents of {out_file}. No markdown fences, no commentary."

        messages = [
            {"role": "system", "content": "You are a precise code generator. Output only raw, valid file contents."},
            {"role": "user", "content": user},
        ]
        max_tokens = task.get("max_tokens", 8192)
        print(f"✍️  [Ralph] Direct-generating {out_file} (context: {context or 'none'})")

        full = ""
        for rnd in range(MAX_CONTINUATIONS):
            try:
                piece, finish = self._post_chat(messages, max_tokens)
            except Exception as e:
                print(f"❌ [Ralph] Direct call failed: {e}")
                return "TIMEOUT"
            full += piece
            if finish != "length":           # natural stop → done
                break
            print(f"   ↪︎ hit token cap — asking model to CONTINUE (round {rnd + 1})...")
            messages.append({"role": "assistant", "content": piece})
            messages.append({"role": "user", "content":
                "Continue the file from EXACTLY where you stopped. Do NOT repeat any previous "
                "lines, do NOT add fences or commentary — output only the remaining raw content."})
        else:
            print("⚠️  [Ralph] Still truncated after continuations; writing partial (verify will catch it).")

        code = self._strip_fences(full)
        with open(os.path.join(DEV_ROOT, out_file), "w") as f:
            f.write(code)
        print(f"📝 [Ralph] Wrote {out_file} ({len(code)} bytes).")
        return "OK" if self._verify(task) else "VERIFY_FAILED"
```

And in `run_plan`, pass the attempt so the retry hint kicks in:

```python
                if task.get("mode") == "direct":
                    outcome = self.run_direct_task(task, attempt=attempts)
                else:
                    outcome = self.execute_task(task, attempt=attempts)
```

Why this works: a file under ~8k tokens now finishes in one shot (no seam risk). A bigger one comes back with `finish_reason == "length"`, and Ralph feeds the partial back and says "continue from where you stopped," stitching the pieces. The continuation reuses the same cached prefix in dflash, so it's fast. `node --check` still gates the final stitched result.

> One honest caveat: whole-file regeneration makes the file grow every task, so input *and* output both climb. Continuation handles the output side; eventually (for very large files) you'd want to switch those tasks to the **agent** path (targeted `Edit`s instead of full rewrites). That's the natural answer to your next question.

---

## Your doubt #1 — autonomously building the plan, with Code steps

You're right that everything became `direct` and nothing uses Claude Code. Here's a generator that decomposes a goal with the local model, then **deterministically** fills the schema — and routes integration/test tasks to the **agent** (ccr) path so you *do* get Code-driven steps.

`~/local-llm-workspace/build_plan.py`:

```python
#!/usr/bin/env python3
"""Autonomously build a Ralph plan.json from a high-level goal.
Requires dflash running on :8787.  Usage: python build_plan.py "your project goal"
"""
import json, os, sys, urllib.request

CONFIG    = json.load(open("llmstack_config.json")) if os.path.exists("llmstack_config.json") else {}
DEV_ROOT  = os.path.abspath(CONFIG.get("dev_root", "."))
PLAN_FILE = CONFIG.get("plan_file", "plan.json")
DIRECT_URL = "http://127.0.0.1:8787/v1/chat/completions"
MODEL = "mlx-community/Qwen3.6-27B-4bit"

DECOMP_SYS = (
    "You are a software planner. Given a project goal, output a JSON array of small, ordered, "
    "atomic build tasks. Each object has EXACTLY: \"title\", \"prompt\" (one imperative sentence "
    "for a single change), \"file\" (the ONE file it creates/modifies), \"deps\" (array of other "
    "existing files it must read). Build dependencies first. Output ONLY the JSON array."
)
AGENT_KW = ("integrate", "wire", "connect", " run ", "test", "install", "across files", "end-to-end")
VERIFY = {".js": 'node --check "{f}"', ".mjs": 'node --check "{f}"',
          ".ts": 'npx -y tsc --noEmit "{f}"', ".py": 'python -m py_compile "{f}"'}

def call_model(goal, max_tokens=4096):
    body = json.dumps({"model": MODEL, "temperature": 0.2, "stream": False, "max_tokens": max_tokens,
                       "messages": [{"role": "system", "content": DECOMP_SYS},
                                    {"role": "user", "content": goal}]}).encode()
    req = urllib.request.Request(DIRECT_URL, data=body, headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=1800))["choices"][0]["message"]["content"]

def verify_for(file):
    if not file: return "true"
    _, ext = os.path.splitext(file)
    t = VERIFY.get(ext)
    return (f'test -f "{file}" && ' + t.format(f=file)) if t else f'test -s "{file}"'

def normalize(raw):
    seen, out = set(), []
    for i, t in enumerate(raw, 1):
        file = (t.get("file") or "").strip()
        deps = [d for d in (t.get("deps") or []) if d and d != file]
        prompt = t.get("prompt") or t.get("title") or ""
        first = file not in seen
        if file: seen.add(file)
        agentic = (not file) or any(k in prompt.lower() for k in AGENT_KW)
        task = {"id": str(i), "status": "pending",
                "mode": "agent" if agentic else "direct", "prompt": prompt}
        if agentic:
            task["tools"] = ["Read", "Edit", "Write", "Bash"]
        else:
            task["file"] = file
            task["context"] = ([file] if not first else []) + deps
        task["verify"] = verify_for(file)
        out.append(task)
    return out

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('usage: python build_plan.py "high-level project goal"'); sys.exit(1)
    print("🧠 Decomposing goal via local model...")
    raw = call_model(sys.argv[1])
    s, e = raw.find("["), raw.rfind("]")
    tasks = normalize(json.loads(raw[s:e + 1]))
    plan = {"project": sys.argv[1][:60], "tasks": tasks}
    os.makedirs(os.path.dirname(PLAN_FILE) or ".", exist_ok=True)
    json.dump(plan, open(PLAN_FILE, "w"), indent=2)
    print(f"✅ Wrote {len(tasks)} tasks to {PLAN_FILE}:")
    for t in tasks:
        print(f"  {t['id']:>2} [{t['mode']:6}] {t.get('file','-'):14} verify={t['verify'][:40]}")
```

Workflow: start dflash (the launcher does, or run the `dflash serve …` line by hand), then `python build_plan.py "Build a browser Pacman clone in vanilla JS"`, **review the printed plan**, tweak any task, then run the launcher. The model does the creative decomposition; the script guarantees the `mode`/`verify`/`context` schema. Integration/test tasks (anything matching "integrate", "test", "wire"…) become **agent** tasks routed through ccr → Claude Code, so you get real Code steps where multi-file work or command execution is needed.

## Your doubt #2 — de-couple from `pacman_clone` + guarantee the ccr path

- **The only project coupling is `llmstack_config.json`.** `ralph_loop.py` and `build_plan.py` already read `dev_root`/`plan_file` from it. The single remaining literal is the launcher's trust-seed fallback — change it so nothing assumes pacman:

```python
    dev_root = json.load(open("llmstack_config.json")).get("dev_root", ".")
```

  To start a new project: make a new folder, set `dev_root`/`plan_file` in `llmstack_config.json`, run `build_plan.py`, then the launcher. No script edits.

- **The Claude Code/ccr path is fully live.** Any task without `mode: "direct"` (or with `"mode": "agent"`) routes to `execute_task`, which runs `ccr code -p …` headless. `build_plan.py` now emits those automatically; you can also force any task agentic by hand:

```json
{ "id": "15", "status": "pending", "mode": "agent",
  "tools": ["Read","Edit","Write","Bash"],
  "prompt": "Wire ghost updates into the game loop in game.js and run `node --check` on all files.",
  "verify": "for f in *.js; do node --check \"$f\" || exit 1; done" }
```

Use **direct** for "produce one self-contained file" and **agent** for "touch several files / run commands / integrate" — the agent path is where Claude Code earns its keep, and the 12 GB cache fix keeps it from OOM-ing on those larger contexts.

Want me to add a `"strategy": "rewrite" | "edit"` field so large files (like `ghosts.js`) automatically switch to agent-mode targeted `Edit`s once they cross a size threshold, instead of being fully regenerated every task?

Both fixes make sense, and they're related: the **size-based auto-switch** stops big files from being truncated in the first place, and the **git-restore-before-retry** guarantees a failed attempt never poisons the next one with a corrupt file (which is exactly what was happening — attempt 2 read the broken `ghosts.js` as context). Here are the complete modified files.

### `~/local-llm-workspace/ralph_loop.py` (complete)

```python
import subprocess
import threading
import time
import json
import urllib.request
import os
import signal
import sys

# Long-request timeouts so Claude Code waits for slow local generations (agentic path).
os.environ.update({
    "API_TIMEOUT_MS": "1800000",
    "CLAUDE_STREAM_IDLE_TIMEOUT_MS": "1800000",
    "CLAUDE_ENABLE_BYTE_WATCHDOG": "0",
    "CLAUDE_ENABLE_STREAM_WATCHDOG": "0",
})
print(f"⏱️  [Ralph] API_TIMEOUT_MS={os.environ['API_TIMEOUT_MS']} forced.")

# ---------------- CONFIG ----------------
def load_config():
    cfg = {
        "dev_root": ".", "plan_file": "plan.json",
        "permission_mode": "acceptEdits", "max_turns": 40,
        "task_timeout": 1800, "max_retries": 3,
        "size_threshold_bytes": 12000,     # files bigger than this switch to agent 'edit' mode
    }
    if os.path.exists("llmstack_config.json"):
        with open("llmstack_config.json") as f:
            cfg.update(json.load(f))
        print(f"🔧 [Ralph] Config loaded: Root='{cfg['dev_root']}', Plan='{cfg['plan_file']}'")
    else:
        print("⚠️ [Ralph] No llmstack_config.json found, using defaults.")
    return cfg

CONFIG     = load_config()
DEV_ROOT   = os.path.abspath(CONFIG["dev_root"])
PLAN_FILE  = CONFIG["plan_file"]
HEALTH_URL = "http://127.0.0.1:8787/v1/models"
DIRECT_URL = "http://127.0.0.1:8787/v1/chat/completions"   # dflash directly (no CCR/Headroom)
MODEL      = "mlx-community/Qwen3.6-27B-4bit"
MAX_CONTINUATIONS = 6

STRICT_SYS_PROMPT = (
    "You drive a coding agent through a translation proxy that FAILS if a single "
    "assistant message mixes prose and tool calls. Rules:\n"
    "1. Do NOT narrate.\n"
    "2. NEVER write text AFTER a tool call in the same response.\n"
    "3. Prefer ONE tool call per response.\n"
    "4. For file-creation, write the file directly; do NOT read other files unless required.\n"
    "5. Do only the single atomic task, then stop."
)

DFLASH_CMD = [
    "dflash", "serve",
    "--model", MODEL,
    "--draft-model", "z-lab/Qwen3.6-27B-DFlash",
    "--host", "127.0.0.1", "--port", "8787",
    "--verify-mode", "adaptive",
    "--temp", "0.2",
    "--max-tokens", "8192",
    "--chat-template-args", '{"enable_thinking": false}',
    "--prefix-cache-max-entries", "64",
    "--prefix-cache-max-bytes", "12GB",
    "--max-snapshot-tokens", "16000",
    "--no-clear-cache-boundaries",
]


class RalphSupervisor:
    def __init__(self):
        self.server_process = None
        self._stop = False
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)

    # ---------- server lifecycle ----------
    def _ping(self, timeout=3):
        try:
            return urllib.request.urlopen(HEALTH_URL, timeout=timeout).getcode() == 200
        except Exception:
            return False

    def start_server(self):
        if self.server_process and self.server_process.poll() is None:
            return
        print("🚀 [Ralph] Starting DFlash server...")
        with open("dflash_server.log", "a") as log:
            self.server_process = subprocess.Popen(
                DFLASH_CMD, stdout=log, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        self.wait_for_health()

    def wait_for_health(self, boot_timeout=600):
        print("⏳ [Ralph] Waiting for model to load into RAM...")
        start = time.time()
        while not self._stop:
            if self._ping():
                print("✅ [Ralph] Server online and healthy.")
                return True
            if self.server_process.poll() is not None:
                print("❌ [Ralph] Server died during boot. Restarting...")
                self.server_process = None
                return self.start_server()
            if time.time() - start > boot_timeout:
                print("❌ [Ralph] Server boot timed out.")
                return False
            time.sleep(5)

    def restart_server(self):
        print("♻️  [Ralph] Hard-restarting DFlash...")
        self.kill_server(); time.sleep(3); self.start_server()

    def kill_server(self):
        if self.server_process:
            try:
                os.killpg(os.getpgid(self.server_process.pid), signal.SIGTERM)
                self.server_process.wait(timeout=15)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(os.getpgid(self.server_process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.server_process = None

    # ---------- git: checkpoints + restore ----------
    def _git(self, *args):
        return subprocess.run(["git", *args], cwd=DEV_ROOT, capture_output=True, text=True)

    def ensure_git(self):
        if not os.path.isdir(os.path.join(DEV_ROOT, ".git")):
            self._git("init", "-q")
        # Protect runtime state (plan/config/logs) from reset --hard / clean.
        gi = os.path.join(DEV_ROOT, ".gitignore")
        needed = [".claude/", "node_modules/", "*.log"]
        existing = set()
        if os.path.exists(gi):
            existing = {l.strip() for l in open(gi)}
        missing = [l for l in needed if l not in existing]
        if missing:
            with open(gi, "a") as f:
                f.write("\n".join(missing) + "\n")
        # Stop tracking .claude if an earlier checkpoint committed it.
        self._git("rm", "-r", "--cached", "-q", "--ignore-unmatch", ".claude")
        self._git("add", ".gitignore")
        if self._git("rev-parse", "--verify", "-q", "HEAD").returncode != 0:
            self._git("add", "-A")
            self._git("commit", "-q", "-m", "Ralph baseline")
        else:
            self._git("commit", "-q", "-m", "Ralph: protect runtime state")  # no-op if nothing staged
        print("📦 [Ralph] Git ready (last verified state protected).")

    def restore_to_checkpoint(self, task=None):
        """Return the working tree to the last verified commit before an attempt,
        dropping any corrupt/partial file a previous attempt left behind."""
        if self._git("rev-parse", "--verify", "-q", "HEAD").returncode == 0:
            self._git("reset", "--hard", "-q", "HEAD")
            self._git("clean", "-fdq")          # removes untracked code (e.g. a failed create); .claude is ignored
        elif task and task.get("file"):
            p = os.path.join(DEV_ROOT, task["file"])
            if os.path.exists(p):
                os.remove(p)
                print(f"🗑️  [Ralph] No checkpoint yet — removed partial {task['file']}.")

    def git_checkpoint(self, task):
        self._git("add", "-A")               # respects .gitignore → never commits .claude/plan
        self._git("commit", "-q", "-m", f"Ralph checkpoint: task {task.get('id')} verified")
        print(f"📦 [Ralph] Git checkpoint saved for task {task.get('id')}.")

    # ---------- executor selection (strategy: rewrite | edit | auto) ----------
    def _choose_executor(self, task):
        if task.get("mode") != "direct":
            return "agent"
        strategy = task.get("strategy")          # explicit override
        if strategy == "edit":
            return "agent"
        if strategy == "rewrite":
            return "direct"
        # auto: a MODIFY of an existing file over the size threshold → agent (targeted edits)
        file = task.get("file")
        if file and file in task.get("context", []):
            p = os.path.join(DEV_ROOT, file)
            if os.path.exists(p) and os.path.getsize(p) > CONFIG["size_threshold_bytes"]:
                return "agent"
        return "direct"

    # ---------- DIRECT generation (with continuation on truncation) ----------
    def _strip_fences(self, t):
        t = t.strip()
        if t.startswith("```"):
            t = t.split("\n", 1)[1] if "\n" in t else ""
            if t.rstrip().endswith("```"):
                t = t.rstrip()[:-3]
        return t.strip() + "\n"

    def _post_chat(self, messages, max_tokens):
        body = json.dumps({
            "model": MODEL, "messages": messages,
            "max_tokens": max_tokens, "temperature": 0.2, "stream": False,
        }).encode()
        req = urllib.request.Request(DIRECT_URL, data=body, headers={"Content-Type": "application/json"})
        resp = json.load(urllib.request.urlopen(req, timeout=CONFIG["task_timeout"]))
        choice = resp["choices"][0]
        return (choice["message"]["content"] or ""), choice.get("finish_reason", "stop")

    def run_direct_task(self, task, attempt=1):
        out_file = task["file"]
        context = task.get("context", [])
        ctx = ""
        for cf in context:
            p = os.path.join(DEV_ROOT, cf)
            if os.path.exists(p):
                with open(p) as f:
                    ctx += f"\n\n--- existing {cf} ---\n{f.read()}"
        user = task["prompt"]
        if ctx:
            user += f"\n\nRelevant existing files:{ctx}"
        if out_file in context:
            user += (f"\n\nYou are MODIFYING {out_file}: preserve ALL existing functionality "
                     f"and add the requested behavior. Output the COMPLETE updated file.")
        if attempt > 1:
            user += ("\n\nNOTE: the previous attempt produced invalid/truncated code. "
                     "Produce the COMPLETE, syntactically valid file this time.")
        user += f"\n\nOutput ONLY the complete contents of {out_file}. No markdown fences, no commentary."

        messages = [
            {"role": "system", "content": "You are a precise code generator. Output only raw, valid file contents."},
            {"role": "user", "content": user},
        ]
        max_tokens = task.get("max_tokens", 8192)
        print(f"✍️  [Ralph] Direct-generating {out_file} (context: {context or 'none'})")

        full = ""
        for rnd in range(MAX_CONTINUATIONS):
            try:
                piece, finish = self._post_chat(messages, max_tokens)
            except Exception as e:
                print(f"❌ [Ralph] Direct call failed: {e}")
                return "TIMEOUT"
            full += piece
            if finish != "length":
                break
            print(f"   ↪︎ hit token cap — asking model to CONTINUE (round {rnd + 1})...")
            messages.append({"role": "assistant", "content": piece})
            messages.append({"role": "user", "content":
                "Continue the file from EXACTLY where you stopped. Do NOT repeat any previous "
                "lines, do NOT add fences or commentary — output only the remaining raw content."})
        else:
            print("⚠️  [Ralph] Still truncated after continuations; writing partial (verify will catch it).")

        code = self._strip_fences(full)
        with open(os.path.join(DEV_ROOT, out_file), "w") as f:
            f.write(code)
        print(f"📝 [Ralph] Wrote {out_file} ({len(code)} bytes).")
        return "OK" if self._verify(task) else "VERIFY_FAILED"

    # ---------- cache warm-up (agentic only) ----------
    def warm_up_cache(self):
        print("🔥 [Ralph] Warming the agentic prefix cache...")
        try:
            subprocess.run(
                ["ccr", "code", "-p", "Reply with OK only.",
                 "--output-format", "json",
                 "--permission-mode", CONFIG["permission_mode"], "--max-turns", "1"],
                cwd=DEV_ROOT, capture_output=True, text=True, timeout=CONFIG["task_timeout"])
            print("✅ [Ralph] Cache warm.")
        except Exception as e:
            print(f"⚠️  [Ralph] Warm-up skipped ({e}).")

    # ---------- AGENTIC execution (Claude Code via ccr) ----------
    def _retry_directive(self, attempt):
        if attempt <= 1:
            return ""
        if attempt == 2:
            return " RETRY: be terse and make minimal targeted edits, then stop."
        return " FINAL RETRY: smallest valid change only."

    def execute_task(self, task, attempt=1):
        prompt = task["prompt"]
        sys_prompt = STRICT_SYS_PROMPT + self._retry_directive(attempt)
        file = task.get("file")
        if file:
            sys_prompt += (f" Use the Edit tool to make minimal, targeted changes to {file}; "
                           f"preserve all unrelated code and do NOT rewrite the whole file.")
        tools = task.get("tools") or (["Read", "Edit", "Write"] if file else None)
        max_turns = CONFIG["max_turns"] if attempt == 1 else 8
        cmd = ["ccr", "code", "-p", prompt, "--output-format", "json",
               "--permission-mode", CONFIG["permission_mode"],
               "--max-turns", str(max_turns), "--append-system-prompt", sys_prompt]
        if tools:
            cmd += ["--allowedTools", *tools]

        print(f"⚙️  [Ralph] Running Task {task.get('id')} (agentic) in {DEV_ROOT}")
        server_crashed = threading.Event()
        proc = subprocess.Popen(cmd, cwd=DEV_ROOT, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=os.setsid)
        threading.Thread(target=self._watch_during_task, args=(proc, server_crashed), daemon=True).start()
        try:
            out, err = proc.communicate(timeout=CONFIG["task_timeout"])
        except subprocess.TimeoutExpired:
            self._kill_proc(proc); return "TIMEOUT"
        if server_crashed.is_set():
            return "SERVER_CRASH"
        return self._evaluate(out, err, task)

    def _evaluate(self, stdout, stderr, task):
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, TypeError):
            print("❌ [Ralph] Could not parse CLI JSON:", (stdout or stderr or "<empty>")[:300])
            return "BAD_OUTPUT"
        result = None
        if isinstance(data, list):
            for msg in data:
                if isinstance(msg, dict) and msg.get("type") == "result":
                    result = msg
        elif isinstance(data, dict):
            result = data
        if not result:
            return "BAD_OUTPUT"
        subtype, is_error = result.get("subtype"), result.get("is_error")
        if is_error or subtype != "success":
            detail = result.get("result") or result.get("error") or ""
            if isinstance(detail, (dict, list)): detail = json.dumps(detail)
            print(f"ℹ️  [Ralph] is_error={is_error}, subtype={subtype}. Detail: {str(detail)[:300]}")
        if subtype in ("error_max_turns", "error_during_execution"):
            return "AGENT_ERROR"
        return "OK" if self._verify(task) else "VERIFY_FAILED"

    def _watch_during_task(self, proc, server_crashed):
        fails = 0
        while proc.poll() is None:
            if not self._ping():
                fails += 1
                if fails >= 3:
                    print("🔥 [Ralph] DFlash died DURING the task — aborting agent.")
                    server_crashed.set(); self._kill_proc(proc); return
            else:
                fails = 0
            time.sleep(3)

    def _kill_proc(self, proc):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass

    # ---------- verify ----------
    def _verify(self, task):
        verify_cmd = task.get("verify")
        if not verify_cmd:
            print("⚠️  [Ralph] No 'verify' for this task — skipping gate.")
            return True
        print(f"🔎 [Ralph] Verifying: {verify_cmd}")
        r = subprocess.run(verify_cmd, shell=True, cwd=DEV_ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"❌ [Ralph] Verification FAILED:\n{r.stdout}\n{r.stderr}")
        return r.returncode == 0

    def mark_complete(self, plan, task):
        task["status"] = "completed"
        with open(PLAN_FILE, "w") as f:
            json.dump(plan, f, indent=2)

    # ---------- main loop ----------
    def run_plan(self):
        if not os.path.exists(PLAN_FILE):
            print(f"❌ [Ralph] Plan file '{PLAN_FILE}' not found."); return
        with open(PLAN_FILE) as f:
            plan = json.load(f)
        tasks = plan.get("tasks", [])
        print(f"📋 [Ralph] Loaded {len(tasks)} tasks.")
        self.ensure_git()

        pending = [t for t in tasks if t.get("status") != "completed"]
        if any(self._choose_executor(t) == "agent" for t in pending):
            self.warm_up_cache()

        for task in tasks:
            if task.get("status") == "completed":
                print(f"⏭️  [Ralph] Skipping Task {task.get('id')} (completed)"); continue

            attempts, done = 0, False
            while not done and attempts < CONFIG["max_retries"] and not self._stop:
                if not self._ping():
                    self.restart_server()
                # Start every attempt from the last verified state (discards corrupt/partial files).
                self.restore_to_checkpoint(task)
                attempts += 1
                executor = self._choose_executor(task)
                print(f"▶️  [Ralph] Task {task.get('id')} — attempt {attempts} ({executor})")
                if executor == "direct":
                    outcome = self.run_direct_task(task, attempt=attempts)
                else:
                    outcome = self.execute_task(task, attempt=attempts)

                if outcome == "OK":
                    self.mark_complete(plan, task)
                    self.git_checkpoint(task)
                    print(f"✅ [Ralph] Task {task.get('id')} COMPLETE & verified.")
                    done = True
                elif outcome == "SERVER_CRASH":
                    print("♻️  [Ralph] Server crash — restarting; retry won't count.")
                    self.restart_server()
                    attempts -= 1                    # a crash is not an agent failure
                else:
                    print(f"⚠️  [Ralph] Task {task.get('id')} -> {outcome}. Retry in 10s.")
                    time.sleep(10)

            if not done:
                self.restore_to_checkpoint(task)     # leave disk clean, not corrupted
                print(f"🚨 [Ralph] Task {task.get('id')} NOT completed. Halting (NOT marked done).")
                self.shutdown(); return

        print("\n🎉 [Ralph] All tasks verified and committed!")
        self.shutdown()

    def shutdown(self, signum=None, frame=None):
        self._stop = True
        print("\n🛑 [Ralph] Shutting down infrastructure...")
        self.kill_server()
        sys.exit(0)


if __name__ == "__main__":
    ralph = RalphSupervisor()
    ralph.start_server()
    ralph.run_plan()
```

### `~/local-llm-workspace/llmstack_config.json` (complete)

```json
{
  "dev_root": "./pacman_clone",
  "plan_file": "./pacman_clone/.claude/plans/pacman_plan.json",
  "permission_mode": "acceptEdits",
  "max_turns": 40,
  "task_timeout": 1800,
  "max_retries": 3,
  "size_threshold_bytes": 12000
}
```

---

### Fix the corrupted `ghosts.js` you have right now

You don't strictly need to — the new `restore_to_checkpoint` runs at the start of every attempt, so re-running the launcher will reset `ghosts.js` to the task‑12 commit before it touches it. But to clean it immediately and surgically (without disturbing the plan), restore just that one file from the last good commit:

```bash
cd ~/local-llm-workspace/pacman_clone
git checkout HEAD -- ghosts.js && node --check ghosts.js && echo "✅ restored & valid"
```

(Use `git checkout HEAD -- ghosts.js`, **not** `git reset --hard` — your earlier checkpoints tracked the plan under `.claude/`, and a hard reset would roll the plan's completed-status back. The new `ensure_git` untracks `.claude/` so this footgun is gone on future runs.)

---

### How it behaves now

- **Task 13 (`ghosts.js` ≈ 14 KB > 12 KB):** `_choose_executor` auto-switches it to the **agent** path with `--allowedTools Read,Edit,Write` and a "make minimal targeted edits, don't rewrite the whole file" directive. Claude Code reads the file and emits a small `Edit` diff — no full regeneration, so no truncation.
- **Small files (create tasks, small modifies):** stay **direct** (fast), and if a direct output ever hits the cap it now auto-continues instead of failing.
- **Every retry** first runs `git reset --hard HEAD` + `git clean -fd`, so attempt N+1 always starts from the last verified commit — a botched attempt can't feed a corrupt file into the next one as context. A create task that fails before any commit has its partial file deleted instead.
- **On final give-up**, the working tree is restored too, so you're never left with a broken file on disk.

You can also override the auto-decision per task: add `"strategy": "edit"` to force the agent path, or `"strategy": "rewrite"` to force direct regeneration regardless of size.

No other files changed — `ralph_launcher.bash`, `start_headroom.sh`, the CCR config, `build_plan.py`, and the dashboard stay as they are. Want me to extend `build_plan.py` so it pre-marks tasks that modify a known-large file (like a central `game.js`/`ghosts.js`) with `"strategy": "edit"` up front, so they go straight to the agent without waiting to cross the size threshold mid-run?

You're right on both counts, and they're real bugs in my logic — not your setup. The agent was making genuine incremental Edits, but (1) on `TIMEOUT` I rolled the file back instead of keeping the progress, and (2) my retry path *shrank* `max_turns` to 8 (`CONFIG["max_turns"] if attempt == 1 else 8`), so attempt 2 ran out of turns almost immediately. Both are now fixed: **valid progress is committed and resumed instead of discarded**, `max_turns` is large and never shrinks, and "made progress" attempts get their own budget so they don't burn the hard-fail retries.

First: **Ctrl-C the current run**, paste the two files below, then re-run.

### `~/local-llm-workspace/ralph_loop.py` (complete)

```python
import subprocess
import threading
import time
import json
import urllib.request
import os
import signal
import sys

os.environ.update({
    "API_TIMEOUT_MS": "1800000",
    "CLAUDE_STREAM_IDLE_TIMEOUT_MS": "1800000",
    "CLAUDE_ENABLE_BYTE_WATCHDOG": "0",
    "CLAUDE_ENABLE_STREAM_WATCHDOG": "0",
})
print(f"⏱️  [Ralph] API_TIMEOUT_MS={os.environ['API_TIMEOUT_MS']} forced.")

# ---------------- CONFIG ----------------
def load_config():
    cfg = {
        "dev_root": ".", "plan_file": "plan.json",
        "permission_mode": "acceptEdits",
        "max_turns": 150,                  # generous for local dev; NEVER shrunk on retry
        "task_timeout": 1800,              # per-attempt ceiling (s); progress is preserved on timeout
        "max_retries": 3,                  # HARD failures (corrupt/no-progress) before giving up
        "max_resumes": 8,                  # progress-preserving continuations allowed
        "size_threshold_bytes": 12000,     # bigger files use agent 'edit' instead of full rewrite
    }
    if os.path.exists("llmstack_config.json"):
        with open("llmstack_config.json") as f:
            cfg.update(json.load(f))
        print(f"🔧 [Ralph] Config loaded: Root='{cfg['dev_root']}', Plan='{cfg['plan_file']}'")
    else:
        print("⚠️ [Ralph] No llmstack_config.json found, using defaults.")
    return cfg

CONFIG     = load_config()
DEV_ROOT   = os.path.abspath(CONFIG["dev_root"])
PLAN_FILE  = CONFIG["plan_file"]
HEALTH_URL = "http://127.0.0.1:8787/v1/models"
DIRECT_URL = "http://127.0.0.1:8787/v1/chat/completions"
MODEL      = "mlx-community/Qwen3.6-27B-4bit"
MAX_CONTINUATIONS = 6

STRICT_SYS_PROMPT = (
    "You drive a coding agent through a translation proxy that FAILS if a single "
    "assistant message mixes prose and tool calls. Rules:\n"
    "1. Do NOT narrate.\n"
    "2. NEVER write text AFTER a tool call in the same response.\n"
    "3. Prefer ONE tool call per response.\n"
    "4. For file-creation, write the file directly; do NOT read other files unless required.\n"
    "5. Do only the single atomic task, then stop."
)

DFLASH_CMD = [
    "dflash", "serve",
    "--model", MODEL,
    "--draft-model", "z-lab/Qwen3.6-27B-DFlash",
    "--host", "127.0.0.1", "--port", "8787",
    "--verify-mode", "adaptive",
    "--temp", "0.2",
    "--max-tokens", "8192",
    "--chat-template-args", '{"enable_thinking": false}',
    "--prefix-cache-max-entries", "64",
    "--prefix-cache-max-bytes", "12GB",
    "--max-snapshot-tokens", "16000",
    "--no-clear-cache-boundaries",
]


class RalphSupervisor:
    def __init__(self):
        self.server_process = None
        self._stop = False
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)

    # ---------- server lifecycle ----------
    def _ping(self, timeout=3):
        try:
            return urllib.request.urlopen(HEALTH_URL, timeout=timeout).getcode() == 200
        except Exception:
            return False

    def start_server(self):
        if self.server_process and self.server_process.poll() is None:
            return
        print("🚀 [Ralph] Starting DFlash server...")
        with open("dflash_server.log", "a") as log:
            self.server_process = subprocess.Popen(
                DFLASH_CMD, stdout=log, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        self.wait_for_health()

    def wait_for_health(self, boot_timeout=600):
        print("⏳ [Ralph] Waiting for model to load into RAM...")
        start = time.time()
        while not self._stop:
            if self._ping():
                print("✅ [Ralph] Server online and healthy.")
                return True
            if self.server_process.poll() is not None:
                print("❌ [Ralph] Server died during boot. Restarting...")
                self.server_process = None
                return self.start_server()
            if time.time() - start > boot_timeout:
                print("❌ [Ralph] Server boot timed out.")
                return False
            time.sleep(5)

    def restart_server(self):
        print("♻️  [Ralph] Hard-restarting DFlash...")
        self.kill_server(); time.sleep(3); self.start_server()

    def kill_server(self):
        if self.server_process:
            try:
                os.killpg(os.getpgid(self.server_process.pid), signal.SIGTERM)
                self.server_process.wait(timeout=15)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(os.getpgid(self.server_process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.server_process = None

    # ---------- git ----------
    def _git(self, *args):
        return subprocess.run(["git", *args], cwd=DEV_ROOT, capture_output=True, text=True)

    def ensure_git(self):
        if not os.path.isdir(os.path.join(DEV_ROOT, ".git")):
            self._git("init", "-q")
        gi = os.path.join(DEV_ROOT, ".gitignore")
        needed = [".claude/", "node_modules/", "*.log"]
        existing = {l.strip() for l in open(gi)} if os.path.exists(gi) else set()
        missing = [l for l in needed if l not in existing]
        if missing:
            with open(gi, "a") as f:
                f.write("\n".join(missing) + "\n")
        self._git("rm", "-r", "--cached", "-q", "--ignore-unmatch", ".claude")
        self._git("add", ".gitignore")
        if self._git("rev-parse", "--verify", "-q", "HEAD").returncode != 0:
            self._git("add", "-A"); self._git("commit", "-q", "-m", "Ralph baseline")
        else:
            self._git("commit", "-q", "-m", "Ralph: protect runtime state")
        print("📦 [Ralph] Git ready (last verified state protected).")

    def restore_to_checkpoint(self, task=None):
        if self._git("rev-parse", "--verify", "-q", "HEAD").returncode == 0:
            self._git("reset", "--hard", "-q", "HEAD")
            self._git("clean", "-fdq")
        elif task and task.get("file"):
            p = os.path.join(DEV_ROOT, task["file"])
            if os.path.exists(p):
                os.remove(p)
                print(f"🗑️  [Ralph] No checkpoint yet — removed partial {task['file']}.")

    def git_checkpoint(self, task, label="verified"):
        self._git("add", "-A")
        self._git("commit", "-q", "-m", f"Ralph: task {task.get('id')} {label}")

    def _wip_commit(self, task):
        """Persist valid-but-incomplete progress so a timeout/crash can't lose it."""
        self.git_checkpoint(task, label="WIP (resumable)")
        print(f"💾 [Ralph] Progress on task {task.get('id')} saved (WIP commit).")

    # ---------- validity check ----------
    def _syntax_ok(self, task):
        f = task.get("file")
        if not f:
            return True
        p = os.path.join(DEV_ROOT, f)
        if not os.path.exists(p):
            return True                     # nothing yet (create task) — not "corrupt"
        if f.endswith((".js", ".mjs")):
            return subprocess.run(["node", "--check", f], cwd=DEV_ROOT,
                                  capture_output=True).returncode == 0
        return True

    # ---------- executor selection ----------
    def _choose_executor(self, task):
        if task.get("mode") != "direct":
            return "agent"
        strategy = task.get("strategy")
        if strategy == "edit":
            return "agent"
        if strategy == "rewrite":
            return "direct"
        file = task.get("file")
        if file and file in task.get("context", []):
            p = os.path.join(DEV_ROOT, file)
            if os.path.exists(p) and os.path.getsize(p) > CONFIG["size_threshold_bytes"]:
                return "agent"
        return "direct"

    # ---------- DIRECT generation (continuation on truncation) ----------
    def _strip_fences(self, t):
        t = t.strip()
        if t.startswith("```"):
            t = t.split("\n", 1)[1] if "\n" in t else ""
            if t.rstrip().endswith("```"):
                t = t.rstrip()[:-3]
        return t.strip() + "\n"

    def _post_chat(self, messages, max_tokens):
        body = json.dumps({"model": MODEL, "messages": messages,
                           "max_tokens": max_tokens, "temperature": 0.2, "stream": False}).encode()
        req = urllib.request.Request(DIRECT_URL, data=body, headers={"Content-Type": "application/json"})
        resp = json.load(urllib.request.urlopen(req, timeout=CONFIG["task_timeout"]))
        choice = resp["choices"][0]
        return (choice["message"]["content"] or ""), choice.get("finish_reason", "stop")

    def run_direct_task(self, task, attempt=1):
        out_file = task["file"]
        context = task.get("context", [])
        ctx = ""
        for cf in context:
            p = os.path.join(DEV_ROOT, cf)
            if os.path.exists(p):
                with open(p) as f:
                    ctx += f"\n\n--- existing {cf} ---\n{f.read()}"
        user = task["prompt"]
        if ctx:
            user += f"\n\nRelevant existing files:{ctx}"
        if out_file in context:
            user += (f"\n\nYou are MODIFYING {out_file}: preserve ALL existing functionality "
                     f"and add the requested behavior. Output the COMPLETE updated file.")
        if attempt > 1:
            user += ("\n\nNOTE: the previous attempt produced invalid/truncated code. "
                     "Produce the COMPLETE, syntactically valid file this time.")
        user += f"\n\nOutput ONLY the complete contents of {out_file}. No markdown fences, no commentary."

        messages = [
            {"role": "system", "content": "You are a precise code generator. Output only raw, valid file contents."},
            {"role": "user", "content": user},
        ]
        max_tokens = task.get("max_tokens", 8192)
        print(f"✍️  [Ralph] Direct-generating {out_file} (context: {context or 'none'})")
        full = ""
        for rnd in range(MAX_CONTINUATIONS):
            try:
                piece, finish = self._post_chat(messages, max_tokens)
            except Exception as e:
                print(f"❌ [Ralph] Direct call failed: {e}")
                return "TIMEOUT"
            full += piece
            if finish != "length":
                break
            print(f"   ↪︎ hit token cap — asking model to CONTINUE (round {rnd + 1})...")
            messages.append({"role": "assistant", "content": piece})
            messages.append({"role": "user", "content":
                "Continue the file from EXACTLY where you stopped. Do NOT repeat any previous "
                "lines, do NOT add fences or commentary — output only the remaining raw content."})
        code = self._strip_fences(full)
        with open(os.path.join(DEV_ROOT, out_file), "w") as f:
            f.write(code)
        print(f"📝 [Ralph] Wrote {out_file} ({len(code)} bytes).")
        return "OK" if self._verify(task) else "VERIFY_FAILED"

    # ---------- warm-up ----------
    def warm_up_cache(self):
        print("🔥 [Ralph] Warming the agentic prefix cache...")
        try:
            subprocess.run(["ccr", "code", "-p", "Reply with OK only.", "--output-format", "json",
                            "--permission-mode", CONFIG["permission_mode"], "--max-turns", "1"],
                           cwd=DEV_ROOT, capture_output=True, text=True, timeout=CONFIG["task_timeout"])
            print("✅ [Ralph] Cache warm.")
        except Exception as e:
            print(f"⚠️  [Ralph] Warm-up skipped ({e}).")

    # ---------- AGENTIC execution ----------
    def execute_task(self, task, attempt=1, resuming=False):
        prompt = task["prompt"]
        file = task.get("file")
        sys_prompt = STRICT_SYS_PROMPT
        if file:
            sys_prompt += (f" Use the Edit tool to make minimal, targeted changes to {file}; "
                           f"preserve all unrelated code and do NOT rewrite the whole file.")
        if resuming:
            sys_prompt += (f" IMPORTANT: {file or 'the file'} ALREADY contains partial work for this "
                           f"task from a previous run. CONTINUE and COMPLETE it — do not restart from "
                           f"scratch and do not duplicate code that is already there.")
        tools = task.get("tools") or (["Read", "Edit", "Write"] if file else None)
        cmd = ["ccr", "code", "-p", prompt, "--output-format", "json",
               "--permission-mode", CONFIG["permission_mode"],
               "--max-turns", str(CONFIG["max_turns"]),          # full budget EVERY attempt
               "--append-system-prompt", sys_prompt]
        if tools:
            cmd += ["--allowedTools", *tools]

        print(f"⚙️  [Ralph] Running Task {task.get('id')} (agentic, turns={CONFIG['max_turns']}) in {DEV_ROOT}")
        server_crashed = threading.Event()
        proc = subprocess.Popen(cmd, cwd=DEV_ROOT, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=os.setsid)
        threading.Thread(target=self._watch_during_task, args=(proc, server_crashed), daemon=True).start()
        try:
            out, err = proc.communicate(timeout=CONFIG["task_timeout"])
        except subprocess.TimeoutExpired:
            self._kill_proc(proc); return "TIMEOUT"
        if server_crashed.is_set():
            return "SERVER_CRASH"
        return self._evaluate(out, err, task)

    def _evaluate(self, stdout, stderr, task):
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, TypeError):
            print("❌ [Ralph] Could not parse CLI JSON:", (stdout or stderr or "<empty>")[:300])
            return "BAD_OUTPUT"
        result = None
        if isinstance(data, list):
            for msg in data:
                if isinstance(msg, dict) and msg.get("type") == "result":
                    result = msg
        elif isinstance(data, dict):
            result = data
        if not result:
            return "BAD_OUTPUT"
        subtype, is_error = result.get("subtype"), result.get("is_error")
        if is_error or subtype != "success":
            detail = result.get("result") or result.get("error") or ""
            if isinstance(detail, (dict, list)): detail = json.dumps(detail)
            print(f"ℹ️  [Ralph] is_error={is_error}, subtype={subtype}. Detail: {str(detail)[:300]}")
        if subtype in ("error_max_turns", "error_during_execution"):
            return "AGENT_ERROR"
        return "OK" if self._verify(task) else "VERIFY_FAILED"

    def _watch_during_task(self, proc, server_crashed):
        fails = 0
        while proc.poll() is None:
            if not self._ping():
                fails += 1
                if fails >= 3:
                    print("🔥 [Ralph] DFlash died DURING the task — aborting agent.")
                    server_crashed.set(); self._kill_proc(proc); return
            else:
                fails = 0
            time.sleep(3)

    def _kill_proc(self, proc):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _verify(self, task):
        verify_cmd = task.get("verify")
        if not verify_cmd:
            print("⚠️  [Ralph] No 'verify' for this task — skipping gate.")
            return True
        print(f"🔎 [Ralph] Verifying: {verify_cmd}")
        r = subprocess.run(verify_cmd, shell=True, cwd=DEV_ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"❌ [Ralph] Verification FAILED:\n{r.stdout}\n{r.stderr}")
        return r.returncode == 0

    def mark_complete(self, plan, task):
        task["status"] = "completed"
        with open(PLAN_FILE, "w") as f:
            json.dump(plan, f, indent=2)

    # ---------- main loop ----------
    def run_plan(self):
        if not os.path.exists(PLAN_FILE):
            print(f"❌ [Ralph] Plan file '{PLAN_FILE}' not found."); return
        with open(PLAN_FILE) as f:
            plan = json.load(f)
        tasks = plan.get("tasks", [])
        print(f"📋 [Ralph] Loaded {len(tasks)} tasks.")
        self.ensure_git()

        pending = [t for t in tasks if t.get("status") != "completed"]
        if any(self._choose_executor(t) == "agent" for t in pending):
            self.warm_up_cache()

        for task in tasks:
            if task.get("status") == "completed":
                print(f"⏭️  [Ralph] Skipping Task {task.get('id')} (completed)"); continue

            executor = self._choose_executor(task)

            # Clean only a CORRUPT leftover at task start — never discard valid progress.
            if executor == "agent" and not self._syntax_ok(task):
                print("🧹 [Ralph] Corrupt leftover detected — restoring to last checkpoint.")
                self.restore_to_checkpoint(task)

            hard_fails = resumes = 0
            done = False
            while (not done and hard_fails < CONFIG["max_retries"]
                   and resumes <= CONFIG["max_resumes"] and not self._stop):
                if not self._ping():
                    self.restart_server()

                if executor == "direct":
                    self.restore_to_checkpoint(task)     # whole-file rewrite → start clean

                n = hard_fails + resumes + 1
                tag = executor + (", resume" if resumes else "")
                print(f"▶️  [Ralph] Task {task.get('id')} — attempt {n} ({tag})")

                if executor == "direct":
                    outcome = self.run_direct_task(task, attempt=n)
                else:
                    outcome = self.execute_task(task, attempt=n, resuming=(resumes > 0))

                if outcome == "OK":
                    self.mark_complete(plan, task)
                    self.git_checkpoint(task, label="verified")
                    print(f"✅ [Ralph] Task {task.get('id')} COMPLETE & verified.")
                    done = True

                elif outcome == "SERVER_CRASH":
                    print("♻️  [Ralph] Server crash — restarting (not counted).")
                    self.restart_server()
                    if executor == "agent" and self._syntax_ok(task):
                        self._wip_commit(task)

                elif outcome in ("TIMEOUT", "AGENT_ERROR"):
                    if executor == "agent" and self._syntax_ok(task):
                        self._wip_commit(task)
                        resumes += 1
                        print(f"⏸️  [Ralph] {outcome} but file is VALID — progress kept, RESUMING "
                              f"(resume {resumes}/{CONFIG['max_resumes']}).")
                    else:
                        hard_fails += 1
                        self.restore_to_checkpoint(task)
                        print(f"⚠️  [Ralph] {outcome} (no usable progress) — rolled back "
                              f"({hard_fails}/{CONFIG['max_retries']}).")
                        time.sleep(5)

                else:  # VERIFY_FAILED / BAD_OUTPUT
                    hard_fails += 1
                    self.restore_to_checkpoint(task)
                    print(f"⚠️  [Ralph] {outcome} — rolled back ({hard_fails}/{CONFIG['max_retries']}).")
                    time.sleep(5)

            if not done:
                if executor == "agent" and self._syntax_ok(task):
                    self._wip_commit(task)
                    print(f"🚧 [Ralph] Task {task.get('id')} INCOMPLETE — valid progress KEPT as WIP. "
                          f"Re-run to resume from here. Halting.")
                else:
                    self.restore_to_checkpoint(task)
                    print(f"🚨 [Ralph] Task {task.get('id')} NOT completed — rolled back. Halting.")
                self.shutdown(); return

        print("\n🎉 [Ralph] All tasks verified and committed!")
        self.shutdown()

    def shutdown(self, signum=None, frame=None):
        self._stop = True
        print("\n🛑 [Ralph] Shutting down infrastructure...")
        self.kill_server()
        sys.exit(0)


if __name__ == "__main__":
    ralph = RalphSupervisor()
    ralph.start_server()
    ralph.run_plan()
```

### `~/local-llm-workspace/llmstack_config.json` (complete)

```json
{
  "dev_root": "./pacman_clone",
  "plan_file": "./pacman_clone/.claude/plans/pacman_plan.json",
  "permission_mode": "acceptEdits",
  "max_turns": 150,
  "task_timeout": 1800,
  "max_retries": 3,
  "max_resumes": 8,
  "size_threshold_bytes": 12000
}
```

### What changed and what to expect

- **Timeout no longer loses work.** When an agent attempt times out (or hits max turns) and the file still *parses*, Ralph commits a **WIP checkpoint** and the next attempt **resumes** — the agent is told the file "already contains partial work, continue and complete it." Over a few attempts a big feature converges instead of restarting each time.
- **`max_turns` is now 150 and never shrinks.** The "counter didn't reset" was my retry code dropping it to 8 — gone. Each attempt is a fresh `-p` call with the full budget.
- **Separate budgets.** `max_resumes` (8) governs progress-preserving continuations; `max_retries` (3) governs *hard* failures (corrupt output / verify breakage). Making progress no longer eats your retry budget, and an endless no-progress loop still stops.
- **Rollback is now surgical.** It only happens on a *corrupt* result (syntax breakage / bad output) or for direct whole-file rewrites — never when valid agentic progress exists. On final give-up, valid WIP is **kept** (committed), so re-running picks up exactly where it stopped.

One honest note: the work from that first attempt before the old code reset it is unfortunately gone (it was discarded by an uncommitted `git reset --hard`, so it's not in history). But from here forward every valid increment is committed, so a timeout costs you a re-read, not the work. If you want even finer-grained safety, lower `task_timeout` (e.g. to `900`) so it WIP-commits and resumes every ~15 minutes instead of 30.

Here's the complete `ralph_loop.py` with the two fixes (`_evaluate` clean-finish/timeout handling and `_verify` feature-marker gate) folded into the full file.

```python
import subprocess
import threading
import time
import json
import urllib.request
import os
import signal
import sys

# Long-request timeouts so Claude Code waits for slow local generations (agentic path).
os.environ.update({
    "API_TIMEOUT_MS": "1800000",
    "CLAUDE_STREAM_IDLE_TIMEOUT_MS": "1800000",
    "CLAUDE_ENABLE_BYTE_WATCHDOG": "0",
    "CLAUDE_ENABLE_STREAM_WATCHDOG": "0",
})
print(f"⏱️  [Ralph] API_TIMEOUT_MS={os.environ['API_TIMEOUT_MS']} forced.")

# ---------------- CONFIG ----------------
def load_config():
    cfg = {
        "dev_root": ".", "plan_file": "plan.json",
        "permission_mode": "acceptEdits",
        "max_turns": 150,                  # generous for local dev; NEVER shrunk on retry
        "task_timeout": 1800,              # per-attempt ceiling (s); progress is preserved on timeout
        "max_retries": 3,                  # HARD failures (corrupt/no-progress) before giving up
        "max_resumes": 8,                  # progress-preserving continuations allowed
        "size_threshold_bytes": 12000,     # bigger files use agent 'edit' instead of full rewrite
    }
    if os.path.exists("llmstack_config.json"):
        with open("llmstack_config.json") as f:
            cfg.update(json.load(f))
        print(f"🔧 [Ralph] Config loaded: Root='{cfg['dev_root']}', Plan='{cfg['plan_file']}'")
    else:
        print("⚠️ [Ralph] No llmstack_config.json found, using defaults.")
    return cfg

CONFIG     = load_config()
DEV_ROOT   = os.path.abspath(CONFIG["dev_root"])
PLAN_FILE  = CONFIG["plan_file"]
HEALTH_URL = "http://127.0.0.1:8787/v1/models"
DIRECT_URL = "http://127.0.0.1:8787/v1/chat/completions"   # dflash directly (no CCR/Headroom)
MODEL      = "mlx-community/Qwen3.6-27B-4bit"
MAX_CONTINUATIONS = 6

STRICT_SYS_PROMPT = (
    "You drive a coding agent through a translation proxy that FAILS if a single "
    "assistant message mixes prose and tool calls. Rules:\n"
    "1. Do NOT narrate.\n"
    "2. NEVER write text AFTER a tool call in the same response.\n"
    "3. Prefer ONE tool call per response.\n"
    "4. For file-creation, write the file directly; do NOT read other files unless required.\n"
    "5. Do only the single atomic task, then stop."
)

DFLASH_CMD = [
    "dflash", "serve",
    "--model", MODEL,
    "--draft-model", "z-lab/Qwen3.6-27B-DFlash",
    "--host", "127.0.0.1", "--port", "8787",
    "--verify-mode", "adaptive",
    "--temp", "0.2",
    "--max-tokens", "8192",
    "--chat-template-args", '{"enable_thinking": false}',
    "--prefix-cache-max-entries", "64",
    "--prefix-cache-max-bytes", "12GB",
    "--max-snapshot-tokens", "16000",
    "--no-clear-cache-boundaries",
]


class RalphSupervisor:
    def __init__(self):
        self.server_process = None
        self._stop = False
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)

    # ---------- server lifecycle ----------
    def _ping(self, timeout=3):
        try:
            return urllib.request.urlopen(HEALTH_URL, timeout=timeout).getcode() == 200
        except Exception:
            return False

    def start_server(self):
        if self.server_process and self.server_process.poll() is None:
            return
        print("🚀 [Ralph] Starting DFlash server...")
        with open("dflash_server.log", "a") as log:
            self.server_process = subprocess.Popen(
                DFLASH_CMD, stdout=log, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        self.wait_for_health()

    def wait_for_health(self, boot_timeout=600):
        print("⏳ [Ralph] Waiting for model to load into RAM...")
        start = time.time()
        while not self._stop:
            if self._ping():
                print("✅ [Ralph] Server online and healthy.")
                return True
            if self.server_process.poll() is not None:
                print("❌ [Ralph] Server died during boot. Restarting...")
                self.server_process = None
                return self.start_server()
            if time.time() - start > boot_timeout:
                print("❌ [Ralph] Server boot timed out.")
                return False
            time.sleep(5)

    def restart_server(self):
        print("♻️  [Ralph] Hard-restarting DFlash...")
        self.kill_server(); time.sleep(3); self.start_server()

    def kill_server(self):
        if self.server_process:
            try:
                os.killpg(os.getpgid(self.server_process.pid), signal.SIGTERM)
                self.server_process.wait(timeout=15)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(os.getpgid(self.server_process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.server_process = None

    # ---------- git ----------
    def _git(self, *args):
        return subprocess.run(["git", *args], cwd=DEV_ROOT, capture_output=True, text=True)

    def ensure_git(self):
        if not os.path.isdir(os.path.join(DEV_ROOT, ".git")):
            self._git("init", "-q")
        gi = os.path.join(DEV_ROOT, ".gitignore")
        needed = [".claude/", "node_modules/", "*.log"]
        existing = {l.strip() for l in open(gi)} if os.path.exists(gi) else set()
        missing = [l for l in needed if l not in existing]
        if missing:
            with open(gi, "a") as f:
                f.write("\n".join(missing) + "\n")
        self._git("rm", "-r", "--cached", "-q", "--ignore-unmatch", ".claude")
        self._git("add", ".gitignore")
        if self._git("rev-parse", "--verify", "-q", "HEAD").returncode != 0:
            self._git("add", "-A"); self._git("commit", "-q", "-m", "Ralph baseline")
        else:
            self._git("commit", "-q", "-m", "Ralph: protect runtime state")
        print("📦 [Ralph] Git ready (last verified state protected).")

    def restore_to_checkpoint(self, task=None):
        if self._git("rev-parse", "--verify", "-q", "HEAD").returncode == 0:
            self._git("reset", "--hard", "-q", "HEAD")
            self._git("clean", "-fdq")
        elif task and task.get("file"):
            p = os.path.join(DEV_ROOT, task["file"])
            if os.path.exists(p):
                os.remove(p)
                print(f"🗑️  [Ralph] No checkpoint yet — removed partial {task['file']}.")

    def git_checkpoint(self, task, label="verified"):
        self._git("add", "-A")
        self._git("commit", "-q", "-m", f"Ralph: task {task.get('id')} {label}")

    def _wip_commit(self, task):
        """Persist valid-but-incomplete progress so a timeout/crash can't lose it."""
        self.git_checkpoint(task, label="WIP (resumable)")
        print(f"💾 [Ralph] Progress on task {task.get('id')} saved (WIP commit).")

    # ---------- validity check ----------
    def _syntax_ok(self, task):
        f = task.get("file")
        if not f:
            return True
        p = os.path.join(DEV_ROOT, f)
        if not os.path.exists(p):
            return True                     # nothing yet (create task) — not "corrupt"
        if f.endswith((".js", ".mjs")):
            return subprocess.run(["node", "--check", f], cwd=DEV_ROOT,
                                  capture_output=True).returncode == 0
        return True

    # ---------- executor selection ----------
    def _choose_executor(self, task):
        if task.get("mode") != "direct":
            return "agent"
        strategy = task.get("strategy")
        if strategy == "edit":
            return "agent"
        if strategy == "rewrite":
            return "direct"
        file = task.get("file")
        if file and file in task.get("context", []):
            p = os.path.join(DEV_ROOT, file)
            if os.path.exists(p) and os.path.getsize(p) > CONFIG["size_threshold_bytes"]:
                return "agent"
        return "direct"

    # ---------- DIRECT generation (continuation on truncation) ----------
    def _strip_fences(self, t):
        t = t.strip()
        if t.startswith("```"):
            t = t.split("\n", 1)[1] if "\n" in t else ""
            if t.rstrip().endswith("```"):
                t = t.rstrip()[:-3]
        return t.strip() + "\n"

    def _post_chat(self, messages, max_tokens):
        body = json.dumps({"model": MODEL, "messages": messages,
                           "max_tokens": max_tokens, "temperature": 0.2, "stream": False}).encode()
        req = urllib.request.Request(DIRECT_URL, data=body, headers={"Content-Type": "application/json"})
        resp = json.load(urllib.request.urlopen(req, timeout=CONFIG["task_timeout"]))
        choice = resp["choices"][0]
        return (choice["message"]["content"] or ""), choice.get("finish_reason", "stop")

    def run_direct_task(self, task, attempt=1):
        out_file = task["file"]
        context = task.get("context", [])
        ctx = ""
        for cf in context:
            p = os.path.join(DEV_ROOT, cf)
            if os.path.exists(p):
                with open(p) as f:
                    ctx += f"\n\n--- existing {cf} ---\n{f.read()}"
        user = task["prompt"]
        if ctx:
            user += f"\n\nRelevant existing files:{ctx}"
        if out_file in context:
            user += (f"\n\nYou are MODIFYING {out_file}: preserve ALL existing functionality "
                     f"and add the requested behavior. Output the COMPLETE updated file.")
        if attempt > 1:
            user += ("\n\nNOTE: the previous attempt produced invalid/truncated code. "
                     "Produce the COMPLETE, syntactically valid file this time.")
        user += f"\n\nOutput ONLY the complete contents of {out_file}. No markdown fences, no commentary."

        messages = [
            {"role": "system", "content": "You are a precise code generator. Output only raw, valid file contents."},
            {"role": "user", "content": user},
        ]
        max_tokens = task.get("max_tokens", 8192)
        print(f"✍️  [Ralph] Direct-generating {out_file} (context: {context or 'none'})")
        full = ""
        for rnd in range(MAX_CONTINUATIONS):
            try:
                piece, finish = self._post_chat(messages, max_tokens)
            except Exception as e:
                print(f"❌ [Ralph] Direct call failed: {e}")
                return "TIMEOUT"
            full += piece
            if finish != "length":
                break
            print(f"   ↪︎ hit token cap — asking model to CONTINUE (round {rnd + 1})...")
            messages.append({"role": "assistant", "content": piece})
            messages.append({"role": "user", "content":
                "Continue the file from EXACTLY where you stopped. Do NOT repeat any previous "
                "lines, do NOT add fences or commentary — output only the remaining raw content."})
        else:
            print("⚠️  [Ralph] Still truncated after continuations; writing partial (verify will catch it).")

        code = self._strip_fences(full)
        with open(os.path.join(DEV_ROOT, out_file), "w") as f:
            f.write(code)
        print(f"📝 [Ralph] Wrote {out_file} ({len(code)} bytes).")
        return "OK" if self._verify(task) else "VERIFY_FAILED"

    # ---------- warm-up ----------
    def warm_up_cache(self):
        print("🔥 [Ralph] Warming the agentic prefix cache...")
        try:
            subprocess.run(["ccr", "code", "-p", "Reply with OK only.", "--output-format", "json",
                            "--permission-mode", CONFIG["permission_mode"], "--max-turns", "1"],
                           cwd=DEV_ROOT, capture_output=True, text=True, timeout=CONFIG["task_timeout"])
            print("✅ [Ralph] Cache warm.")
        except Exception as e:
            print(f"⚠️  [Ralph] Warm-up skipped ({e}).")

    # ---------- AGENTIC execution ----------
    def execute_task(self, task, attempt=1, resuming=False):
        prompt = task["prompt"]
        file = task.get("file")
        sys_prompt = STRICT_SYS_PROMPT
        if file:
            sys_prompt += (f" Use the Edit tool to make minimal, targeted changes to {file}; "
                           f"preserve all unrelated code and do NOT rewrite the whole file.")
        if resuming:
            sys_prompt += (f" IMPORTANT: {file or 'the file'} ALREADY contains partial work for this "
                           f"task from a previous run. CONTINUE and COMPLETE it — do not restart from "
                           f"scratch and do not duplicate code that is already there.")
        tools = task.get("tools") or (["Read", "Edit", "Write"] if file else None)
        cmd = ["ccr", "code", "-p", prompt, "--output-format", "json",
               "--permission-mode", CONFIG["permission_mode"],
               "--max-turns", str(CONFIG["max_turns"]),          # full budget EVERY attempt
               "--append-system-prompt", sys_prompt]
        if tools:
            cmd += ["--allowedTools", *tools]

        print(f"⚙️  [Ralph] Running Task {task.get('id')} (agentic, turns={CONFIG['max_turns']}) in {DEV_ROOT}")
        server_crashed = threading.Event()
        proc = subprocess.Popen(cmd, cwd=DEV_ROOT, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=os.setsid)
        threading.Thread(target=self._watch_during_task, args=(proc, server_crashed), daemon=True).start()
        try:
            out, err = proc.communicate(timeout=CONFIG["task_timeout"])
        except subprocess.TimeoutExpired:
            self._kill_proc(proc); return "TIMEOUT"
        if server_crashed.is_set():
            return "SERVER_CRASH"
        return self._evaluate(out, err, task)

    def _evaluate(self, stdout, stderr, task):
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, TypeError):
            print("❌ [Ralph] Could not parse CLI JSON:", (stdout or stderr or "<empty>")[:300])
            return "BAD_OUTPUT"
        result = None
        if isinstance(data, list):
            for msg in data:
                if isinstance(msg, dict) and msg.get("type") == "result":
                    result = msg
        elif isinstance(data, dict):
            result = data
        if not result:
            return "BAD_OUTPUT"

        subtype = result.get("subtype")
        is_error = bool(result.get("is_error"))
        detail = result.get("result") or result.get("error") or ""
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail)
        detail = str(detail)

        # Hard session failures → resume.
        if subtype in ("error_max_turns", "error_during_execution"):
            print(f"ℹ️  [Ralph] subtype={subtype}. Detail: {detail[:200]}")
            return "AGENT_ERROR"

        # A flagged error (e.g. a mid-loop 'Request timed out') is NOT a clean finish.
        # NEVER trust it as done — route to resume so progress is preserved & re-checked.
        if is_error or subtype != "success":
            print(f"ℹ️  [Ralph] DIRTY finish: is_error={is_error}, subtype={subtype}. Detail: {detail[:200]}")
            low = detail.lower()
            if "tim" in low and "out" in low:        # 'timed out' / 'timeout'
                return "TIMEOUT"
            return "AGENT_ERROR"

        # Only a CLEAN finish reaches the gate (syntax + feature markers).
        return "OK" if self._verify(task) else "VERIFY_FAILED"

    def _watch_during_task(self, proc, server_crashed):
        fails = 0
        while proc.poll() is None:
            if not self._ping():
                fails += 1
                if fails >= 3:
                    print("🔥 [Ralph] DFlash died DURING the task — aborting agent.")
                    server_crashed.set(); self._kill_proc(proc); return
            else:
                fails = 0
            time.sleep(3)

    def _kill_proc(self, proc):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass

    # ---------- verify (syntax + feature markers) ----------
    def _verify(self, task):
        verify_cmd = task.get("verify")
        if verify_cmd:
            print(f"🔎 [Ralph] Verifying: {verify_cmd}")
            r = subprocess.run(verify_cmd, shell=True, cwd=DEV_ROOT, capture_output=True, text=True)
            if r.returncode != 0:
                print(f"❌ [Ralph] Syntax/verify FAILED:\n{r.stdout}\n{r.stderr}")
                return False

        # Feature-presence gate: a valid-but-incomplete file can't false-pass.
        expect = task.get("expect") or []
        target = task.get("file")
        if expect and target:
            p = os.path.join(DEV_ROOT, target)
            content = (open(p, encoding="utf-8", errors="ignore").read().lower()
                       if os.path.exists(p) else "")
            missing = [s for s in expect if s.lower() not in content]
            if missing:
                print(f"❌ [Ralph] Feature markers MISSING in {target}: {missing}")
                return False
            print(f"✅ [Ralph] Feature markers present: {expect}")

        if not verify_cmd and not expect:
            print("⚠️  [Ralph] No verify/expect for this task — skipping gate.")
        return True

    def mark_complete(self, plan, task):
        task["status"] = "completed"
        with open(PLAN_FILE, "w") as f:
            json.dump(plan, f, indent=2)

    # ---------- main loop ----------
    def run_plan(self):
        if not os.path.exists(PLAN_FILE):
            print(f"❌ [Ralph] Plan file '{PLAN_FILE}' not found."); return
        with open(PLAN_FILE) as f:
            plan = json.load(f)
        tasks = plan.get("tasks", [])
        print(f"📋 [Ralph] Loaded {len(tasks)} tasks.")
        self.ensure_git()

        pending = [t for t in tasks if t.get("status") != "completed"]
        if any(self._choose_executor(t) == "agent" for t in pending):
            self.warm_up_cache()

        for task in tasks:
            if task.get("status") == "completed":
                print(f"⏭️  [Ralph] Skipping Task {task.get('id')} (completed)"); continue

            executor = self._choose_executor(task)

            # Clean only a CORRUPT leftover at task start — never discard valid progress.
            if executor == "agent" and not self._syntax_ok(task):
                print("🧹 [Ralph] Corrupt leftover detected — restoring to last checkpoint.")
                self.restore_to_checkpoint(task)

            hard_fails = resumes = 0
            done = False
            while (not done and hard_fails < CONFIG["max_retries"]
                   and resumes <= CONFIG["max_resumes"] and not self._stop):
                if not self._ping():
                    self.restart_server()

                if executor == "direct":
                    self.restore_to_checkpoint(task)     # whole-file rewrite → start clean

                n = hard_fails + resumes + 1
                tag = executor + (", resume" if resumes else "")
                print(f"▶️  [Ralph] Task {task.get('id')} — attempt {n} ({tag})")

                if executor == "direct":
                    outcome = self.run_direct_task(task, attempt=n)
                else:
                    outcome = self.execute_task(task, attempt=n, resuming=(resumes > 0))

                if outcome == "OK":
                    self.mark_complete(plan, task)
                    self.git_checkpoint(task, label="verified")
                    print(f"✅ [Ralph] Task {task.get('id')} COMPLETE & verified.")
                    done = True

                elif outcome == "SERVER_CRASH":
                    print("♻️  [Ralph] Server crash — restarting (not counted).")
                    self.restart_server()
                    if executor == "agent" and self._syntax_ok(task):
                        self._wip_commit(task)

                elif outcome in ("TIMEOUT", "AGENT_ERROR"):
                    if executor == "agent" and self._syntax_ok(task):
                        self._wip_commit(task)
                        resumes += 1
                        print(f"⏸️  [Ralph] {outcome} but file is VALID — progress kept, RESUMING "
                              f"(resume {resumes}/{CONFIG['max_resumes']}).")
                    else:
                        hard_fails += 1
                        self.restore_to_checkpoint(task)
                        print(f"⚠️  [Ralph] {outcome} (no usable progress) — rolled back "
                              f"({hard_fails}/{CONFIG['max_retries']}).")
                        time.sleep(5)

                else:  # VERIFY_FAILED / BAD_OUTPUT
                    hard_fails += 1
                    self.restore_to_checkpoint(task)
                    print(f"⚠️  [Ralph] {outcome} — rolled back ({hard_fails}/{CONFIG['max_retries']}).")
                    time.sleep(5)

            if not done:
                if executor == "agent" and self._syntax_ok(task):
                    self._wip_commit(task)
                    print(f"🚧 [Ralph] Task {task.get('id')} INCOMPLETE — valid progress KEPT as WIP. "
                          f"Re-run to resume from here. Halting.")
                else:
                    self.restore_to_checkpoint(task)
                    print(f"🚨 [Ralph] Task {task.get('id')} NOT completed — rolled back. Halting.")
                self.shutdown(); return

        print("\n🎉 [Ralph] All tasks verified and committed!")
        self.shutdown()

    def shutdown(self, signum=None, frame=None):
        self._stop = True
        print("\n🛑 [Ralph] Shutting down infrastructure...")
        self.kill_server()
        sys.exit(0)


if __name__ == "__main__":
    ralph = RalphSupervisor()
    ralph.start_server()
    ralph.run_plan()
```

This is the full file with both fixes in place:

- **`_evaluate`** now treats `is_error: true` / `subtype != "success"` (including the `"Request timed out"` case that previously slipped through as success) as a **dirty finish** → returns `TIMEOUT`/`AGENT_ERROR`, which the loop resumes instead of marking complete.
- **`_verify`** now enforces an optional **`expect`** list of feature markers (case-insensitive substring match on the target file), so a syntactically-valid-but-incomplete file can no longer pass the gate.

Remember the companion plan change from the previous message: set task 13 back to `"status": "pending"` and add the `"expect"` arrays (e.g. `["setFrightened","isFrightened"]` for task 13), then re-run.