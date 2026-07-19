# LOOP.md — Understanding the Kowalski Loop

This document teaches you **how the Kowalski Loop actually works**, from the moment you run
`bash bin/launch_kowalski.bash` to the moment it prints `🎉 All tasks verified and committed!`.

It is written to be read top to bottom, like a course: each section builds on the previous one.
For exhaustive parameter tables (every config key, every task field), see
[README.md § Advanced Reference](README.md#advanced-reference-kowalski-configuration-llmstack_configjson) —
this document explains the *mental model*, README is the *field-by-field reference*.

---

## Table of contents

1. [The Big Picture](#1-the-big-picture)
2. [The Core Loop Contract](#2-the-core-loop-contract)
3. [The Four Loop Modes](#3-the-four-loop-modes)
4. [Choosing an Executor: Agent vs Direct](#4-choosing-an-executor-agent-vs-direct)
5. [The Verification Pipeline](#5-the-verification-pipeline)
6. [Smart Retry & Escalation](#6-smart-retry--escalation)
7. [Git Checkpointing & Rollback](#7-git-checkpointing--rollback)
8. [`loop_strategy`: the Pluggable Layer](#8-loop_strategy-the-pluggable-layer)
9. [Observability: the Runlog](#9-observability-the-runlog)
10. [Putting It Together: One Task's Life Story](#10-putting-it-together-one-tasks-life-story)
11. [Quick Decision Cheatsheet](#11-quick-decision-cheatsheet)
12. [Where to Go Next](#12-where-to-go-next)

---

## 1. The Big Picture

Think of Kowalski as a **project manager** who never gets tired, and Claude Code as the
**employee** who actually writes code. The project manager doesn't write code itself (well,
sometimes it does — see [Direct Mode](#4-choosing-an-executor-agent-vs-direct)) — its job is to:

1. Decide **what task comes next**.
2. Decide **who does the work** (a quick one-shot write, or a multi-turn agent session).
3. **Check the work** against objective criteria before accepting it.
4. **Protect the codebase** with git checkpoints, so a bad attempt can always be undone.
5. **Retry intelligently** when something fails, feeding the failure back as guidance.
6. **Log everything**, so you can audit what happened after the fact.

Five building blocks implement this, and every one of them is a separate, swappable Python
component:

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Supervisor.run()                             │
│         (the generic engine — identical for all 4 loop modes)        │
│                                                                      │
│   ┌───────────┐   picks task    ┌───────────┐   runs attempt         │
│   │ LoopMode  │ ─────────────►  │ Executor  │ ─────────────────►     │
│   │ (WHICH    │                 │ (agent or │                        │
│   │  task?)   │ ◄─────────────  │  direct)  │                        │
│   └───────────┘   reports       └───────────┘                        │
│         │           outcome            │                             │
│         │                              ▼                             │
│         │                       ┌───────────┐                        │
│         │                       │  Gates    │  pass/fail + feedback  │
│         │                       │ (verify,  │                        │
│         │                       │  expect,  │                        │
│         │                       │  smoke...)│                        │
│         │                       └───────────┘                        │
│         │                              │                             │
│         ▼                              ▼                             │
│   ┌────────────────────────────────────────┐                         │
│   │        GitManager (checkpoint/         │                         │
│   │        rollback/commit)                │                         │
│   └────────────────────────────────────────┘                         │
└──────────────────────────────────────────────────────────────────────┘
```

The single most important idea in this whole document is:

> **The loop engine (`Supervisor`) never changes.** What changes between `plan`, `continuous`,
> `watch`, and `supervised` is only *which object decides the next task* — everything else
> (executors, gates, git, retries) is shared, identical code.

---

## 2. The Core Loop Contract

Every loop mode is a small Python class that implements exactly **three methods** — this is the
entire contract a mode has to fulfill (`llmstack/modes/base.py`):

```python
class LoopMode(ABC):
    def next_task(self):
        """Return the next task dict to run, or None if there's nothing left to do."""

    def on_result(self, task, outcome, state):
        """React to an attempt's outcome (OK / VERIFY_FAILED / TIMEOUT / ...).
        Returns whether to retry, resume, or move on."""

    def on_incomplete(self, task, executor_type):
        """Called once a task is permanently abandoned (git rollback happens here)."""
```

`Supervisor.run()` is the one loop that drives all modes. In pseudocode, this is what happens for
every task it receives from `mode.next_task()`:

```
task = mode.next_task()
while task is not None:
    executor_type = executor.choose_executor(task)     # → "agent" or "direct"      (§4)
    strategy = LoopStrategy(resolve_loop_strategy(task, plan))  # → §8

    attempts = 0
    while not done and hard_fails < max_retries:
        attempts += 1
        outcome = run the attempt (agent or direct)     # → "OK" / "VERIFY_FAILED" / "TIMEOUT" / ...
        if outcome == "OK":
            outcome = run gates + independent checker + safety guardrail   # → §5, §8
        result = mode.on_result(task, outcome, {...})    # mode decides: retry? resume? done?
        hard_fails, resumes, done = result["hard_fails"], result["resumes"], result["done"]

    if not done:
        mode.on_incomplete(task, executor_type)          # rollback, mark failed          (§7)
        log_run(...)                                     # §9
        stop the whole run                               # a task that can't complete halts Kowalski
    else:
        log_run(...)
        task = mode.next_task()                          # ask the mode for the next one
```

Two counters matter here, and they are **not the same thing**:

- **`hard_fails`** — attempts that failed *without any usable progress*. Bounded by `max_retries`
  (default `3`). Once this is hit, the task is abandoned and Kowalski halts.
- **`resumes`** — attempts that failed with a `TIMEOUT`/`AGENT_ERROR` but left behind a git WIP
  commit worth continuing from. Bounded by `max_resumes` (default `8`), and doesn't count against
  `max_retries`.

This distinction exists because a timeout after 90% of a large file was written is a completely
different situation from a syntax error on attempt 1 — the former deserves more patience.

---

## 3. The Four Loop Modes

All four modes share the contract above; they only differ in **how `next_task()` decides what's
next**, and correspondingly in **when the loop naturally stops**.

| Mode | Task source | `next_task()` logic | Stops when | Typical use |
|---|---|---|---|---|
| **`plan`** (default) | `plan_file` (a static JSON list) | Highest `priority` first among tasks not yet `completed`/`skipped`, ties keep file order | All tasks resolved | One-off builds: you already know the full scope of work. |
| **`continuous`** | `continuous_queue_file`, polled every `continuous_poll_seconds` | Same priority ordering, but re-reads the queue file on every poll and tolerates invalid JSON without crashing | You stop it (Ctrl+C) | A long-running worker you feed tasks into over time from another process, without restarting Kowalski. |
| **`watch`** | Filesystem events under `watch_root` | Auto-enqueues a `py_compile` fix task for every `.py` file that changes (debounced), on top of manually queued tasks | You stop it (Ctrl+C) | A live guardrail while you hand-write Python: catches syntax mistakes the moment you save. |
| **`supervised`** | `plan_file` (like `plan`) | Same priority ordering as `plan`, but pauses before returning a task and waits for console approval | All tasks resolved, or you quit at a prompt | Human-in-the-loop control for risky/expensive tasks, or validating a brand-new plan before trusting it unattended. |

### Why this matters when picking a mode

Ask yourself: **"Do I know all the work up front, and do I trust Kowalski to just do it?"**

- Yes to both → **`plan`**. This is the 90% case and the one used in the Quick Start.
- Yes to the first, no to the second → **`supervised`**. Same task source, but you get a checkpoint
  before every single task — useful the first time you point Kowalski at an unfamiliar or
  sensitive codebase.
- No to the first (work arrives over time) → **`continuous`**. Feed it a queue file from a script,
  a webhook handler, or your own terminal, whenever new work shows up.
- You're not asking Kowalski to build anything — you're coding by hand and want a safety net →
  **`watch`**. It reacts to *your* edits, not to a plan.

### Shared mechanics across all four modes

- **Task priority.** Any task can carry an integer `priority` (default `0`); higher runs first,
  ties preserve file order. This works identically in all four modes because it's implemented in
  the ordering step of `next_task()`, not per-mode.
- **Smart retry.** When a gate fails, the failure detail (stderr, missing markers, checker output)
  is captured and injected into the *next* attempt's prompt — the model literally sees *why* it
  failed. Automatic, no configuration needed.
- **The same verification pipeline and the same git checkpointing** (§5, §7) run underneath every
  mode — nothing about "how a task is judged" changes based on which mode selected it.

---

## 4. Choosing an Executor: Agent vs Direct

Once a task is selected, Kowalski must decide **who writes the file**: a multi-turn Claude Code
*agent* session, or a single-shot *direct* generation call. This is the actual decision logic
(`Executor.choose_executor`, `llmstack/core/executors.py`) — read carefully, because it is more
specific than "large files go to the agent":

```
choose_executor(task):
    if task["mode"] != "direct":
        return "agent"                      # ← unset mode, or mode="agent": ALWAYS agent

    # From here on, task["mode"] == "direct" explicitly.
    if task["strategy"] == "edit":
        return "agent"                      # explicit escape hatch back to agent
    if task["strategy"] == "rewrite":
        return "direct"

    # Neither strategy hint given — one more safety check:
    if task["file"] is also listed in task["context"]:
        # i.e. this task is re-generating a file that already exists and is passed to itself
        if that file's current size > size_threshold_bytes (default 12000 bytes):
            return "agent"                  # too big to safely regenerate in one shot

    return "direct"
```

**The one thing to remember:** `"mode": "direct"` must be set **explicitly** on the task for
direct execution to ever be considered. `size_threshold_bytes` and `strategy` only *fine-tune*
behavior once you're already in direct mode — they do not automatically route an unset-mode task
to direct just because its target file is small. If you want one-shot generation, say so.

### Agent Mode

- Multi-turn conversation with Claude Code — it can read files, make several edits, and correct
  itself within the same task attempt.
- Best for: complex logic, refactors, anything touching multiple files or requiring iterative
  reasoning.
- Slower and more expensive (more turns), but far more capable of recovering mid-task.

### Direct Mode

- One-shot generation: the whole file is produced in a single response.
- Best for: new, self-contained files (a starter HTML page, a utility module) where there's
  nothing to "discuss" — the model just needs to produce a complete answer.
- Faster and cheaper, but with no ability to course-correct within the same attempt (a failed
  attempt goes through the normal retry loop as a brand-new attempt instead).
- Routed through the same Headroom proxy as everything else (see [Architecture](README.md#architecture)),
  so direct-mode calls are just as visible in `logs/headroom_traffic.jsonl` as agent calls.
- **Protected by an anti-degeneration guardrail** before the file is ever written: outputs
  ≥ 12,000 characters are scanned for repeated single-character runs (≥ 512), repeated long
  identifiers (≥ 140 occurrences), or a low lexical-diversity signature (unique-token-ratio
  < 0.06 once ≥ 200 tokens are extracted). If corruption is detected, the write is skipped and the
  task goes through the normal retry loop instead of committing garbage. These thresholds are
  intentionally strict, to avoid false positives on legitimately large, repetitive-looking files.

### A worked example

```json
{ "id": "task_A", "file": "index.html", "mode": "direct" }
// → DIRECT. mode is explicitly "direct", no strategy override, file doesn't
//   pre-exist in its own context → falls through to the default: DIRECT.

{ "id": "task_B", "file": "game_logic.js", "context": ["utils.js"], "mode": "agent" }
// → AGENT. mode != "direct", so agent is chosen immediately — strategy is never even read.

{ "id": "task_C", "file": "big_lib.ts", "mode": "direct", "strategy": "rewrite" }
// → DIRECT. mode == "direct" and strategy == "rewrite" confirms it explicitly.

{ "id": "task_D", "prompt": "Fix the collision detection..." }
// → AGENT. No mode field at all → defaults straight to agent, unconditionally.
```

---

## 5. The Verification Pipeline

A task attempt reporting "I'm done" is not the same as a task actually being done. Every attempt
that claims success passes through a pipeline of gates before Kowalski will commit it
(`llmstack/core/gates.py`, `build_task_gate_specs`). The gates run in this fixed order, and the
**first one that fails stops the chain** — everything downstream is skipped for that attempt:

```
Attempt reports success
        │
        ▼
1. verify          — run the task's `verify` shell command (e.g. `node --check file.js`)
        │  (skipped entirely if the task has no `verify` field)
        ▼
2. expect          — every string in `expect` must appear (case-insensitively) in `file`
        │  (skipped if the task has no `expect` field)
        ▼
3. require_change  — `file` must actually have changed according to git
        │  (skippable per-task via `"require_change": false`, or globally via config)
        ▼
4. wiring          — every *.js file must be <script>-referenced by index.html, and
        │            every referenced script must exist (skippable via `wiring_check: false`)
        ▼
5. smoke           — the task's `smoke` Node.js snippet must run and exit 0
        │  (skipped if the task has no `smoke` field)
        ▼
6. plugins (task)  — any matching `verification_plugins` with `"when": "task"` must pass
        │            (unless their `on_failure` is `"warn"`, which only logs)
        ▼
7. **review** — LLM-based code review: a separate model call reads the generated file and judges correctness with a strict "default NO" system prompt. If the call fails/times out, the gate **passes by default** (transient LLM errors never break a run). Controlled by `review_enabled: true` in config.
        │
        ▼
   [all passed] → git commit  /  [any failed] → git rollback → smart retry
```

Three more behaviors sit **around** this pipeline, not inside it:

- **Already-done override** (`allow_already_done_if_verified`, agent tasks only). If the agent
  reports `KowalskiStatus: already_done`, Kowalski re-runs the deterministic gates above with
  `require_change` temporarily forced off for that one attempt. The task only completes if
  everything else still passes — this exists so an idempotent "nothing to do here" report from
  the model isn't blindly trusted.
- **Format fallback** (`"on_format_error": "direct_context_fallback"`, agent tasks only). If an
  agent task keeps failing with provider/transport formatting errors, this per-task option makes
  Kowalski regenerate *only* the task's declared `file` using direct mode, with the task's
  `context` files supplied as read-only references (never rewritten), then re-run the same gate
  pipeline above.
- **Thinking mode** (`thinking_mode`, agent tasks only). Controls whether the underlying Claude
  Code call runs with extended reasoning off, adaptive, or fully on — a generation-time setting,
  not a pass/fail gate.
- **Review gate** (`review_enabled: true` in config). After all deterministic gates pass, an
  additional LLM call reads the generated file and judges correctness with a strict "default NO"
  system prompt. If the call fails (timeout, network error, malformed response), the gate
  **passes by default** — the deterministic gates are the real protection. Controlled by the
  `review_enabled` config key (default `false` to avoid extra latency/cost).

Once every task in the plan is finished, Kowalski runs one more round: any `verification_plugins`
declared with `"when": "plan_complete"` (for example a full `pytest -x` suite) execute exactly
once, after everything else.

---

## 6. Smart Retry & Escalation

When a gate fails, two things happen automatically, with no configuration required:

1. **Feedback injection.** The specific failure reason (stderr/stdout from `verify`, the missing
   markers from `expect`, the checker's output, etc.) is attached to the task and shows up in the
   *next* attempt's prompt, so the model sees exactly what went wrong last time instead of
   guessing blind.
2. **Direct → Agent auto-escalation.** If a **direct**-mode attempt fails in a way that looks
   structural rather than incidental — a `TIMEOUT`, or `VERIFY_FAILED` feedback containing markers
   like `SyntaxError`, `was never closed`, `degenerate`, `corrupted`, or `repeated` — Kowalski
   silently switches that task to the **agent** executor for its next attempt. The reasoning: a
   one-shot regeneration that produced garbage once is unlikely to fix itself by trying the exact
   same one-shot approach again; a multi-turn agent has a much better chance of actually reading
   and correcting the problem.

Retries are bounded (§2): `max_retries` hard failures abandon the task entirely; `max_resumes`
timeouts-with-progress are given extra chances before that budget is spent too. When a task is
ultimately abandoned, **the whole Kowalski run halts** — it does not silently skip ahead and leave
a half-broken repo behind.

---

## 7. Git Checkpointing & Rollback

Every task attempt is bracketed by git operations, so a failed or corrupting attempt never lingers
in your working tree:

- **Before an attempt**, Kowalski checkpoints the current state.
- **On success**, the verified changes are committed — this becomes the new safe baseline for the
  next task.
- **On failure**, Kowalski restores to the last checkpoint (`git clean -fdq` + reset), so a bad
  attempt leaves *zero* trace, including any stray untracked files it created.
- **On a resumable timeout**, instead of a full rollback, Kowalski takes a **WIP commit** of
  whatever partial progress exists, so the next attempt (a "resume") can build on it rather than
  starting from scratch.

This is why you can safely point Kowalski at a fresh `git init` project: worst case, a task fails
and the repo is exactly as clean as before that task started.

---

## 8. `loop_strategy`: the Pluggable Layer

Everything above is what Kowalski does **by default**, with zero extra configuration — this is
intentional, so old plans keep working forever unchanged. `loop_strategy` is an optional block —
settable at the plan level and/or per task, with task-level fields shallow-merging over plan
defaults — that layers *extra* behaviors on top of the loop described in §2–§7, without changing
any of it structurally.

| Field | What it adds |
|---|---|
| `run_until_done` (default `true`) | Set `false` to make the *first* failed attempt final — no retries at all for that task. |
| `checker` | An independent verification command that must *also* pass after the built-in gates already said `OK` — catches a plausible-but-wrong self-report that fooled the model's own review. |
| `risk_policy` | A denylist of file patterns (`.env`, `**/secrets/**`, ...) and a `max_changed_files` cap. If violated after an `OK` outcome, the change is rolled back and **the entire run halts** for human review — it is not retried. |
| `budget` | Caps on `max_attempts`, `max_duration_seconds`, or a coarse `max_token_estimate`, so a stuck task stops burning attempts before `max_retries` is even reached. |
| `context_policy` | `"changed_only"` trims a **direct**-mode task's `context` list down to files already changed in git (no effect in agent mode, which builds its own context via tool calls). |

Four ready-made presets bundle these into common intents:

| Preset | Bundles | Use it when... |
|---|---|---|
| `simple_direct` | nothing (fully inert) | You want to be explicit that no extra strategy applies — identical to omitting `loop_strategy`. |
| `agent_run_until_done` | `run_until_done: true` | You want to formalize today's default behavior in the plan file itself. |
| `verified_maker_checker` | `run_until_done: true` (you still supply `checker.command`) | Correctness matters more than speed — an extra command run costs time but catches self-deceiving "looks right" completions. |
| `safe_repo_edit` | `risk_policy` denylisting `.env`/secrets/auth/payments/billing/migrations/k8s-prod paths, `max_changed_files: 5` | The task touches anything sensitive and an accidental large/wrong-file change should stop everything rather than get silently committed. |

`loop_strategy` composes with **any** of the four loop modes from §3 — most commonly you'll reach
for it on `plan` or `supervised` tasks that are higher-stakes than the rest of the plan.

---

## 9. Observability: the Runlog

Every task run — whether or not it uses `loop_strategy` — appends one JSON line to
`logs/kowalski_runlog.jsonl` (path configurable via `runlog_file`) once it finishes or halts:

```json
{
  "task_id": "task_09",
  "strategy": "preset=safe_repo_edit",
  "executor_type": "direct",
  "attempts": 1,
  "hard_fails": 0,
  "resumes": 0,
  "outcome": "OK",
  "escalated": false,
  "escalation_reason": "",
  "duration_s": 12.4,
  "token_estimate": 310,
  "logged_at": 1752845000.1
}
```

This is a plain append-only log designed to be diffed, grepped, or loaded into a notebook for
post-run analysis — it never affects control flow, and writing to it can never fail a run (errors
are caught and printed as a warning, nothing more).

---

## 10. Putting It Together: One Task's Life Story

Let's trace a single task end to end, to see every piece from §1–§9 acting together.

```json
{
  "id": "task_02",
  "prompt": "Add JavaScript to log 'Button clicked' when clicked",
  "file": "script.js",
  "context": ["index.html"],
  "verify": "node --check script.js"
}
```

1. **`plan` mode's `next_task()`** returns this task — it's the highest-priority task not yet
   `completed`/`skipped`. *(§3)*
2. **`choose_executor()`** sees no `"mode"` field at all → routes to **agent**, unconditionally.
   *(§4)*
3. **`resolve_loop_strategy()`** finds no `loop_strategy` anywhere for this task or plan → an inert
   spec. Nothing in §8 changes behavior for this task.
4. Kowalski checkpoints git, then hands the task to Claude Code as a multi-turn agent session,
   with `index.html` supplied as read-only context.
5. Suppose the agent's first attempt has a typo and reports success anyway. The **gate pipeline**
   runs: `verify` (`node --check script.js`) **fails** — that's gate 1 of 7, so gates 2–7 are
   skipped for this attempt. *(§5)*
6. Git **rolls back** to the pre-attempt checkpoint — the broken `script.js` never lands in the
   repo. *(§7)*
7. `plan` mode's `on_result()` sees `VERIFY_FAILED`, increments `hard_fails` (now `1` of the
   default `max_retries: 3`), and asks for a retry. The syntax error's stderr is captured and
   injected into the next attempt's prompt. *(§6)*
8. Attempt 2: the agent fixes the typo, `verify` now **passes**, `expect`/`require_change`/etc. are
   skipped because this task doesn't declare them, and the attempt is accepted.
9. Git **commits** the verified change.
10. A line is appended to `logs/kowalski_runlog.jsonl`: `outcome: "OK"`, `attempts: 2`,
    `hard_fails: 1`. *(§9)*
11. `plan` mode's `next_task()` is asked again, and the loop continues with whatever comes next —
    or prints `🎉 All tasks verified and committed!` if nothing does.

Every one of the four loop modes runs exactly this same sequence for every task they hand out —
the only thing that changed across `plan`/`continuous`/`watch`/`supervised` would have been step 1.

---

## 11. Quick Decision Cheatsheet

| If you want to... | Do this |
|---|---|
| Build a whole project from a written spec, once | `loop_mode: "plan"` (the default) |
| Keep an agent running and feed it work over time | `loop_mode: "continuous"` + append to `continuous_queue_file` |
| Get auto-fixes for syntax errors as you hand-code Python | `loop_mode: "watch"` |
| Approve every task by hand before it runs | `loop_mode: "supervised"` |
| Force one-shot generation for a specific task | `"mode": "direct"` on that task (never implicit) |
| Force multi-turn refinement for a specific task | `"mode": "agent"` on that task (or just omit `mode`) |
| Make a task fail fast with no retries | `"loop_strategy": {"run_until_done": false}` on that task |
| Add an independent correctness check beyond the built-in gates | `"loop_strategy": {"checker": {"command": "..."}}` |
| Hard-stop the whole run if a sensitive file gets touched | `"loop_strategy": {"preset": "safe_repo_edit"}` |
| Reduce a direct-mode task's context to only what's already changed | `"loop_strategy": {"context_policy": "changed_only"}` |
| Reorder tasks without renumbering the whole plan | Add an integer `"priority"` to the tasks that matter |
| Audit what happened after a run | Read `logs/kowalski_runlog.jsonl` |

---

## 12. Where to Go Next

- [README.md § Advanced Reference: Kowalski Configuration](README.md#advanced-reference-kowalski-configuration-llmstack_configjson) — every config key, defaults, and valid values.
- [README.md § Advanced Reference: Task Schema](README.md#advanced-reference-task-schema-plan-json) — every task field, with worked examples.
- [README.md § Advanced Reference: Loop Modes](README.md#advanced-reference-loop-modes) — copy-paste recipes for each mode.
- [docs/evolution-plan.md](docs/evolution-plan.md) — the design history of how this loop engine was generalized, phase by phase, including what was deliberately deferred.
- [MEMORY.md](MEMORY.md), [HEADROOM.md](HEADROOM.md), [DFLASH.md](DFLASH.md), [SAVINGS.md](SAVINGS.md) — the inference-stack side of the system (memory, compression, cache) that this loop runs on top of.
