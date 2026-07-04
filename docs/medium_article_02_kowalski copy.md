# From "It Runs" to "It Builds While You Sleep": Adding an Autonomous Agentic Loop to Your Local Claude Code

In Part 1 — *The Ultimate Local AI Setup Guide for Apple Silicon using DFlash* — we got Claude Code running entirely offline against a local Qwen3.6-27B, with DFlash speculative decoding for speed and the Claude Code Router bridging the API. By the end you had an interactive `ccr code` session driven by a model on your own Mac.

That setup is great for *interactive* work — you in the driver's seat, reading every diff. This follow-up is about the next step: making the local model build things **unattended**, without babysitting every turn, without committing broken code, and without losing an hour of work to a single timeout.

We'll add two pieces on top of the Part 1 stack:

1. **Headroom** — a code-aware compression proxy that shrinks the prompt before it ever reaches the model.
2. **Kowalski** — a Python supervisor that boots the whole stack, decomposes a goal into atomic tasks, runs each one, and puts every change through six verification gates before it's allowed near a git commit.

By the end, you'll be able to write a build plan, run one command, and walk away.

---

## The problem this solves

Part 1 ended on a high note. Then you ask the local model to do something real and you hit the wall every local-agent builder hits:

> **A local 27B is good enough to write the code. It is not good enough to be *trusted*.**

It drifts. It narrates when it should act. It writes a `ghost.js` that nothing imports. It "finishes" a task by producing a truncated file that doesn't parse. It times out mid-edit and leaves you with half a function.

In interactive mode *you* are the verification layer — you catch the orphan file, you hit `/clear` when the context balloons. The moment you want the loop to run **unattended**, you have to replace yourself with code. That's exactly what we're building.

> **Prerequisite:** This guide assumes you completed Part 1 — Homebrew, the `~/local-llm-workspace/env` virtualenv, `dflash-mlx`, the Claude Code CLI, and `claude-code-router`, all working. If `ccr code` already talks to your local model, you're ready.

---

## The architecture, after this guide

Part 1's chain gains one box (Headroom) and one brain (Kowalski):

```
Claude Code  →  ccr (router)  →  Headroom proxy :8789  →  DFlash server :8787  →  MLX / Apple GPU
                                  └── compresses the prompt        └── runs the model
        ▲
   Kowalski supervisor (boots all of the above, warms the cache, runs the plan)
```

| Component | Job |
|---|---|
| **DFlash server** | The OpenAI-compatible endpoint from Part 1, running the 4-bit Qwen3.6-27B + 2B draft. |
| **Headroom proxy** | New. Sits in front of DFlash and compresses the context before forwarding. |
| **ccr** | The Part 1 bridge — now pointed at Headroom (`:8789`) instead of DFlash directly. |
| **Kowalski** | New. Lifecycle, planning, execution, verification, checkpoints, resume. |

---

## Phase 1: Add Headroom, the compression proxy

The hardest lesson of local agentic coding is that it's **prefill-bound** — you pay to re-read an 18,000–25,000-token prompt on *every single turn*, and speculative decoding doesn't touch that cost. The most direct lever is simple: **send fewer tokens.** Headroom is a proxy that rewrites the context in a code-aware way before it reaches the model.

### Step 1 — Create Headroom's own virtualenv

Headroom needs its **own** Python environment, separate from the Part 1 project venv. On my machine the project venv is Python 3.14, and Headroom runs cleanly on 3.13:

```bash
brew install python@3.13
python3.13 -m venv ~/headroom-env
```

### Step 2 — Install Headroom

The pip package is **`headroom-ai`** (not `headroom` — that one's unrelated, and getting this wrong cost me an evening):

```bash
~/headroom-env/bin/pip install -U pip headroom-ai
~/headroom-env/bin/headroom --version   # confirm it installed
```

### Step 3 — Launch it in front of DFlash

The one critical gotcha: Headroom **must** be launched with the project venv's environment variables unset, or it inherits the wrong Python interpreter and dies in confusing ways. Scrub the environment, point it upstream at DFlash on `:8787`, and have it listen on `:8789`:

```bash
pkill -f "headroom proxy" 2>/dev/null || true

(
  unset VIRTUAL_ENV PYTHONPATH PYTHONHOME
  export OPENAI_TARGET_API_URL="http://127.0.0.1:8787"
  export OPENAI_API_KEY="dflash-local"
  export HEADROOM_TELEMETRY=off
  exec ~/headroom-env/bin/headroom proxy --port 8789 --code-aware --no-telemetry \
       --log-file headroom_traffic.jsonl
) >> headroom.log 2>&1 &
```

### Step 4 — Verify it's alive and pointed the right way

```bash
sleep 6
curl -s http://127.0.0.1:8789/health && echo "  ✅ Headroom up"
grep -q "127.0.0.1:8787" headroom.log && echo "✅ upstream = dflash"
```

Every request Headroom handles is appended to `headroom_traffic.jsonl` with how many tokens it saved — we'll watch that live on the dashboard later.

### Step 5 — Point the router at Headroom instead of DFlash

Edit `~/.claude-code-router/config.json` from Part 1 and change the provider's `api_base_url` so requests flow *through* Headroom:

```json
"api_base_url": "http://127.0.0.1:8789/v1/chat/completions",
```

Then reload it:

```bash
ccr restart
```

That's the entire compression layer. Stacked on top of DFlash's prefix cache and aggressive `/clear` hygiene, it's a third independent attack on the prefill bottleneck.

---

## Phase 2: Meet Kowalski, the supervisor that doesn't trust the model

Kowalski's design philosophy is one sentence:

> **Assume the model will fail every task, and make failure cheap and reversible.**

Here's how it earns that — and how to set it up.

### Step 1 — Write a config

Kowalski reads a single `llmstack_config.json` at the workspace root. It's the one source of truth for timeouts, permissions, and which project to build:

```json
{
  "dev_root": "./pacman_clone",
  "plan_file": "./pacman_clone/.claude/plans/pacman_plan.json",
  "permission_mode": "acceptEdits",
  "max_turns": 100,
  "timeout_seconds": 3600,
  "max_retries": 3,
  "max_resumes": 8
}
```

One important detail learned the hard way: **every timeout must come from one knob.** Claude Code, the router, and the model each have their own idea of "too slow," and if they disagree you get phantom failures where one layer kills a request another was happily processing. Kowalski derives all of them from `timeout_seconds` and pushes the value into the environment and the router config on boot.

### Step 2 — Generate a plan (don't hand it a vague goal)

You don't give Kowalski "build a Pac-Man clone" and hope. `build-plan.py` asks the local model to decompose the goal into a JSON array of **atomic, ordered, verifiable tasks** — each touching a single file, with explicit dependencies and a shell command that proves it worked:

```bash
source env/bin/activate
python build-plan.py "Build a Pac-Man clone in HTML/CSS/JS"
```

A generated task looks like this:

```json
{ "id": "9", "mode": "direct", "file": "ghosts.js", "context": ["map.js"],
  "prompt": "Create ghosts.js: define four ghosts with grid positions and a draw(ctx) method...",
  "verify": "test -f ghosts.js && node --check ghosts.js" }
```

This is Part 1's "Golden Rule" — *force atomic steps* — turned into infrastructure. Small tasks mean small prompts mean cheap prefill mean the model actually succeeds.

### Step 3 — Understand the two execution modes

The trick that made the whole thing stable is that Kowalski picks an executor **per task**:

- **Direct mode** — for self-contained file creation, Kowalski bypasses the agent loop and sends *one* request straight to DFlash: "write this file." No 33k-token agent context, no tool-call dance, no OOM. If the model hits the token cap mid-file, Kowalski asks it to *continue from exactly where it stopped* and stitches the pieces together.
- **Agentic mode** — for tasks that genuinely need to read across files and make targeted edits, it falls back to `ccr code` with a strict system prompt and a tight tool allowlist.

Most file-creation tasks run *direct*, and that single decision eliminated the majority of crashes and timeouts. You use the expensive agent loop only when you actually need it.

### Step 4 — Know the six gates a task must survive

A task isn't "done" because the model said so. It's done when it clears every applicable gate:

1. **Syntax / shell verify** — `node --check`, `py_compile`, whatever the task declared.
2. **Feature markers** — required strings must actually be present in the output.
3. **Change gate** — the declared file must *actually* have been modified. No no-ops, no wrong-file edits.
4. **Wiring check** — every `*.js` must be referenced by `index.html`, and every reference must resolve. This catches the orphan `ghost.js` the app never loads.
5. **Behavioral smoke test** — runs the task's runtime assertion via `node -e`, in the repo, without writing anything into it.
6. **Optional LLM review** — a soft second opinion (off by default; it's the same weak model grading its own homework).

Only a change that clears all applicable gates reaches a commit. Everything else is rolled back.

### Step 5 — Checkpoints, resume, and crash recovery (free)

Every verified task becomes a git commit. If the model times out but left **valid, parseable** progress, Kowalski makes a "WIP (resumable)" commit and re-runs the task telling it *"this file already contains partial work — continue it, don't restart."* If the work is garbage, it hard-resets to the last good checkpoint and retries. If DFlash itself crashes, a health-check watchdog restarts the server without counting it against the retry budget.

The payoff: you can `Ctrl-C` Kowalski and re-launch it, and it picks up from the last verified commit. A timeout costs you minutes, not your session.

---

## Phase 3: Run it

With Headroom up (Phase 1) and a plan generated (Phase 2), launch the whole thing with one command:

```bash
bash kowalski_launcher.bash
```

The launcher will:

1. Activate the venv and **clear cloud keys** (`unset ANTHROPIC_AUTH_TOKEN ANTHROPIC_API_KEY`) so Claude can't silently call the cloud.
2. Centralize the timeout into the environment and the router config.
3. **Pre-seed folder trust** in `~/.claude.json` so the unattended run doesn't block on the trust dialog.
4. Start (or confirm) Headroom, then restart the router.
5. Hand control to `kowalski_loop.py`, which boots DFlash, warms the prefix cache, and grinds through the plan — committing only verified work.

Then walk away. When you come back, `git log` shows you exactly which tasks passed.

---

## Phase 4: Watch it work (the dashboard)

Numbers you can't see, you can't fix. In a second terminal:

```bash
bash dashboard_launcher.bash
```

It tails both the DFlash log and the Headroom traffic log and shows you, live:

- **Phase** — IDLE / PREFILLING / DECODING, with progress bars. Watch the prefill bar crawl on a cold context, then snap to instant once the prefix cache warms — that's the prefill bottleneck made visible.
- **Cache hit %**, decode tok/s, acceptance %.
- **Headroom savings** — tokens stripped, per request and cumulative.
- **MLX active / cache / peak memory** — your early-warning system for the OOM cliff.

Every completed call is also appended to `dflash_timings.csv` for later analysis.

---

## Lessons from the build (the stuff tutorials skip)

A few scars worth sharing:

**The OOM cliff is about the cache, not the model.** The model fits fine in 64 GB. What kills you is an unbounded prefix cache colliding with a long agent context. The fix was capping the cache (`--prefix-cache-max-bytes 12GB`, `--max-snapshot-tokens 16000`) and preferring direct mode so contexts stay small.

**"Done" is the most dangerous word a local model says.** A dirty finish — a response flagged with an error, or a "timed out" buried in the result — must *never* be trusted as success. Kowalski treats any non-clean finish as "resume and re-verify," never "complete." That one rule killed an entire class of silent corruption.

**The model will narrate when you beg it not to.** The strict system prompt ("do NOT write text after a tool call in the same response") exists because the translation proxy genuinely breaks when a message mixes prose and tool calls. Local models love to explain themselves; you have to forbid it, explicitly, every time.

**Two separate venvs is not optional.** Headroom on 3.13, the project on 3.14, and Headroom launched with the venv variables scrubbed. Skip this and you'll chase ghosts.

---

## Honest status

Let me be straight about maturity:

**What works well:**
- The autonomous loop runs a multi-task plan end-to-end and commits only verified work.
- Direct mode is fast and reliable for file generation.
- The six gates catch real failures — orphan files, no-ops, truncation, broken syntax.
- Checkpoint/resume makes interruptions cheap.
- The dashboard makes the whole thing observable.

**What's rough:**
- It's **hardcoded to one model** (the Part 1 DFlash setup) and **one project** (`pacman_clone`). Switching either means editing code.
- **Launch and logic are tangled** — the bash launchers duplicate setup and `kowalski_loop.py` does everything in one file.
- **No remote visibility** — if Kowalski is grinding overnight, you can't check on it from your phone.
- **The gates are JS-centric** — the wiring check assumes an `index.html` + `*.js` web app.

It's a genuinely useful tool currently shaped like *one person's setup for one project on one machine.*

---

## What's next

The roadmap writes itself from those caveats:

1. **Generalize the model layer** — a registry so you can declare DFlash *and* a sparse MoE in config and switch with one command.
2. **Modularize** — separate launch/control from logic so new features plug into stable seams.
3. **More loop modes** — continuous queue, file-watcher, supervised-with-approval.
4. **Remote control** — a Telegram bot for status, notifications, and injecting tasks from your phone.
5. **Pluggable gates** — `ruff`, `tsc`, `pytest`, `cargo check` — verification that adapts to the language.
6. **A real installer** — one script that replicates every hard-won manual step from Part 1 and this guide.

---

## Conclusion

Part 1 proved a local 27B can be *fast*. This part is about the unglamorous thing that actually makes a local agent useful: **trust**. A fast model that quietly commits broken code is worse than no model at all. Kowalski's six gates, dual execution modes, and checkpoint-and-resume discipline are what turn "Claude Code runs locally" into "Claude Code *builds* something locally, unattended, and I believe the result."

It's not Cloud Claude, and it won't be. But it's a free, private, offline coding agent that can grind through a plan while you're not watching — and hand you back only the work that passed every test.

*If you're building something similar, I'd love to hear how you're handling the trust problem. Deterministic gates? LLM-as-judge? Something smarter? Drop a comment.*
