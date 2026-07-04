# Evolution Plan — local-llm-workspace

> Critical analysis and actionable roadmap to **modularize**, **generalize** (more models, more loop modes), add **remote control**, and finally deliver a **fully automated installation**.

---

## 0 · Progress Snapshot (verified 2026-07-01)

| Phase | Scope | Status |
|-------|-------|--------|
| **Phase 0** | Modular refactor (`llmstack/` package, services, core, CLI, shims) | ✅ **Done** |
| **Phase 1** | Model generalization (registry, DFlash/TurboQuant backends, model-aware CCR, `model use/list/recommend`, hardening 1.9–1.13) | ✅ **Done** |
| **Phase 2** | Loop modes (`plan`/`continuous`/`watch`/`supervised`) + priority ordering + smart retry | ✅ **Done** (2026-07-01) |
| **Phase 3** | Pragmatic extensibility: pluggable gates + minimal `llmstack init` + per-task `thinking_mode` | ✅ **Done** (2026-07-01) |
| **Phase 4** | Control plane (IPC bus, pause/stop) + Telegram notifier/controller | ⬜ **Not started** |
| **Phase 5** | Dashboards & analytics (state-driven TUI, web dashboard, SQLite metrics) | ⬜ **Not started** |
| **Phase 6** | Multi-project workflow (`project use`, named configs, project-scoped defaults) | ⬜ **Not started** |
| **Phase 7** | Automated installation (`install.sh`/`doctor.sh`/`update.sh`) | ⬜ **Not started** |

**Verification basis (code inspection + tests, 2026-07-01):**
- `llmstack/modes/` contains `base.py` (`LoopMode` ABC), `plan_mode.py`, `continuous_mode.py`, `watch_mode.py`, `supervised_mode.py`, all exported from `__init__.py`.
- `Supervisor._make_mode()` (`llmstack/core/supervisor.py`) dispatches on `config["loop_mode"]`; `run()` delegates to `mode.next_task()` / `on_result()` / `on_incomplete()` and calls `mode.close()` on exit.
- Smart retry: `gates.verify_detailed()` returns `(ok, reason, feedback)`; `executors._retry_feedback_note()` injects the feedback into direct and agent retry prompts.
- Pluggable gates: `config.normalize_verification_plugins()` validates `verification_plugins`; `gates.run_verification_plugins()` runs task-level plugins and `gates.run_plan_complete_plugins()` runs final suite hooks once at the end.
- Thinking mode: `config.normalize_thinking_mode()` validates `thinking_mode`; `Executor._agent_env()` applies `off` / `auto` / `on` per task and records it in debug logs.
- Init wizard: `llmstack init` writes a compact starter config, derives a starter plan path, and can optionally call `build_plan.py` for the provided goal.
- Priority ordering: `PlanMode._ordered_tasks()` sorts by `(-priority, original_index)` and is inherited by all modes.
- Corner-case suite `tests/test_phase2_modes.py` (13 checks: priority/ties, bad priority, all-done, continuous empty/append/invalid-JSON/list-shape/persist, watch enqueue/ignore/close-idempotent, supervised quit/skip, smart-retry note) → **ALL PASS**.
- Phase 3 gate suite `tests/test_phase3_pluggable_gates.py` (8 checks: defaults disabled, invalid config fails fast, language/file filtering, smart-retry feedback, task opt-in/out, direct `plan_complete`, supervisor end hook) → **ALL PASS**.
- Phase 3 init suite `tests/test_phase3_init_wizard.py` (3 checks: config creation + bootstrap plan, overwrite refusal, force overwrite) → **ALL PASS**.
- No `control/`, `notify/`, or `dashboard/` packages exist yet under `llmstack/` (Phase 4+).

### Phase 3 follow-up refinements

- Add a non-interactive `llmstack init` flow beyond `--force` so the wizard can be scripted end-to-end.
- Add more explicit starter config templates for `python`, `js`, and `generic` projects.

### 👉 Recommended next step — **Phase 4 (control plane + Telegram)**

Phase 3 is complete. The next meaningful seam is the control plane/state bus, because remote pause/stop/status and Telegram all become much cleaner once there is a shared runtime state surface.

Then proceed to **Phase 4** for IPC + remote control. **Phase 5** (dashboards) remains downstream of the control/state surface. **Multi-project** moves later because it is the most likely to be reshaped by project-scoped control, notifier, and dashboard state.

---

## 1 · Current State — Strengths and Weaknesses

### What works well
- Cleanly layered runtime architecture (DFlash → Headroom → CCR → Claude Code)
- Kowalski has a robust loop: 6 verification gates, git checkpoints, resume-on-timeout
- Complete Rich TUI dashboard (DFlash + Headroom metrics)
- Dual execution mode (direct generation + agentic via `ccr code`)
- `build-plan.py` for autonomous plan generation

### Critical weaknesses
| Area | Problem |
|------|---------|
| **Monolithic scripts** | Launch logic, configuration, environment setup, and orchestration logic are tangled inside the same files (e.g. `kowalski_loop.py` mixes config loading, server lifecycle, gates, executors; bash launchers duplicate the same env/trust/timeout setup) |
| **Hardcoded model** | `Qwen3.6-27B-4bit` + draft `z-lab/Qwen3.6-27B-DFlash` wired into 6+ files |
| **No model registry** | Cannot switch models without editing code |
| **Duplicated boot logic** | Trust pre-seeding, CCR timeout patching, key unsetting, and Headroom boot are copy-pasted across `kowalski_launcher.bash`, `ccr_interactive.bash`, `start_*.bash` |
| **Config not generalized** | `llmstack_config.json` hardcoded to `./pacman_clone` |
| **Single loop strategy** | Only one-shot plan execution; no continuous/watch/supervised modes |
| **No remote control** | Zero visibility unless sitting at the terminal |
| **Manual installation** | `docs/install.md` is a blog article, not an executable script — and it does **not document Headroom installation at all** (the README also points at a wrong repo URL) |
| **Headroom out-of-tree** | `~/headroom-env` is a **separate Python 3.13 venv** (the project venv is 3.14); the real pip package is **`headroom-ai`**, invoked as the `headroom` executable |

### Root cause
The project grew organically: launch concerns (env vars, trust, ports, timeouts), control concerns (start/stop/status), and **business logic** (the Kowalski loop, the verification gates, the executors) are all interleaved. **The single most valuable refactor is to separate these layers** so every later feature (more models, more loop modes, Telegram, web dashboard) plugs into a stable core instead of patching tangled scripts.

---

## 2 · Target Architecture (Modular)

The goal is a clean separation between **launch/control** (the "shell") and **logic** (the "core").

```
local-llm-workspace/
├── llmstack/                     # ← the importable Python package (the CORE)
│   ├── __init__.py
│   ├── config.py                 # load/validate llmstack_config.json, env, defaults
│   ├── models/                   # MODEL ABSTRACTION
│   │   ├── registry.py           # ModelConfig, load active model, list models
│   │   ├── base.py               # Backend ABC: build_serve_cmd(), health_url(), chat_url(), ccr_provider()
│   │   ├── dflash.py             # DFlash backend
│   │   └── turboquant.py         # TurboQuant MoE backend
│   ├── services/                 # SERVICE LIFECYCLE (launch concern)
│   │   ├── manager.py            # start/stop/health for any service
│   │   ├── dflash_service.py     # wraps the inference server
│   │   ├── headroom_service.py   # wraps Headroom proxy
│   │   └── ccr_service.py        # wraps CCR (config patch, restart)
│   ├── core/                     # ORCHESTRATION LOGIC (business concern)
│   │   ├── supervisor.py         # the loop driver (was KowalskiSupervisor)
│   │   ├── executors.py          # direct + agentic executors
│   │   ├── gates.py              # the 6 verification gates (pluggable)
│   │   ├── plan.py               # plan load/save/normalize
│   │   └── git_ckpt.py           # checkpoint/restore/WIP
│   ├── modes/                    # LOOP MODES (pluggable strategies)
│   │   ├── base.py               # LoopMode ABC: next_task(), on_result()
│   │   ├── plan_mode.py          # current behavior (ordered plan)
│   │   ├── continuous_mode.py    # infinite queue
│   │   ├── watch_mode.py         # filesystem watcher
│   │   └── supervised_mode.py    # ask-before-each-step
│   ├── notify/                   # NOTIFICATION SINKS (pluggable)
│   │   ├── base.py               # Notifier ABC: emit(event)
│   │   ├── console.py
│   │   ├── macos.py              # osascript notifications
│   │   └── telegram.py
│   ├── control/                  # CONTROL PLANE
│   │   ├── bus.py                # in-process event bus + command queue (pause/stop/inject)
│   │   ├── state.py              # shared runtime state (status, current task, metrics)
│   │   └── ipc.py                # control socket (UNIX socket / file) for external controllers
│   ├── dashboard/                # PRESENTATION (reads state, never owns it)
│   │   ├── tui.py                # the Rich TUI (was dflash_dashboard.py)
│   │   └── web.py                # optional FastAPI + WebSocket
│   └── cli.py                    # `llmstack` entrypoint (argparse/typer)
├── bin/                          # thin launch shims (the SHELL)
│   ├── llmstack                  # → python -m llmstack.cli
│   └── *.bash                    # kept as 5-line wrappers calling the CLI
├── llmstack_config.json             # config (now with models + modes sections)
├── kowalski_config.template.json
└── install/                      # automation (done LAST)
    ├── install.sh
    ├── doctor.sh
    └── update.sh
```

### Design principles
1. **Core is import-only.** `llmstack/core`, `llmstack/models`, `llmstack/modes` never call `subprocess` for env setup, never `print` for control flow — they emit **events** and return **results**.
2. **Services own processes; core owns decisions.** The supervisor asks `dflash_service.ensure_running()`; it does not build `dflash serve` argv itself.
3. **Everything pluggable via ABCs:** backends, loop modes, notifiers, gates. Adding a model/mode = adding one class + one config entry, never editing the loop.
4. **One CLI, thin shells.** All bash launchers become wrappers around `llmstack <command>` so logic lives in Python and is testable.

### Example: what a backend class looks like

```python
# llmstack/models/base.py
from abc import ABC, abstractmethod
import json

class InferenceBackend(ABC):
    def __init__(self, model_cfg: dict): self.cfg = model_cfg
    @abstractmethod
    def build_serve_cmd(self) -> list[str]: ...
    @abstractmethod
    def health_url(self) -> str: ...
    def chat_url(self) -> str:
        # DIRECT executor + build-plan.py bypass CCR/Headroom and hit dflash directly on :8787.
        return "http://127.0.0.1:8787/v1/chat/completions"
    def ccr_provider(self) -> dict:
        """Provider block to inject into ~/.claude-code-router/config.json.
        NOTE: the agentic path goes Claude Code → CCR → Headroom (:8789) → dflash (:8787),
        so api_base_url MUST point at Headroom :8789, NOT dflash :8787."""
        ...

# llmstack/models/dflash.py
class DFlashBackend(InferenceBackend):
    def build_serve_cmd(self) -> list[str]:
        c = self.cfg
        return [
            "dflash", "serve",
            "--model", c["target"],
            "--draft-model", c["draft"],
            "--host", "127.0.0.1", "--port", "8787",
            "--verify-mode", c.get("verify_mode", "adaptive"),
            "--temp", str(c.get("temp", 0.2)),
            "--max-tokens", str(c.get("max_tokens", 8192)),
            "--chat-template-args", json.dumps(c.get("chat_template_args", {"enable_thinking": False})),
            "--prefix-cache-max-entries", str(c.get("cache_max_entries", 64)),
            "--prefix-cache-max-bytes", c.get("cache_max_bytes", "12GB"),
            "--max-snapshot-tokens", str(c.get("max_snapshot_tokens", 16000)),
            "--no-clear-cache-boundaries",
        ]
    def health_url(self) -> str: return "http://127.0.0.1:8787/v1/models"

# llmstack/models/turboquant.py  (sparse MoE — no draft model, prefill-optimized)
class TurboQuantBackend(InferenceBackend):
    def build_serve_cmd(self) -> list[str]:
        c = self.cfg
        return [
            "turboquant-serve",
            "--model", c["target"],
            # KV-cache quantization: a MEMORY win (keeps the cache <2GB at long context),
            # NOT a speed win. Required to fit long agentic contexts without OOM.
            "--kv-k-bits", str(c.get("kv_k_bits", 8)),
            "--kv-v-bits", str(c.get("kv_v_bits", 3)),
            "--kv-min-tokens", str(c.get("kv_min_tokens", 128)),
            "--prompt-concurrency", str(c.get("prompt_concurrency", 1)),
            "--host", "127.0.0.1", "--port", "8787",
            "--chat-template-args", json.dumps(c.get("chat_template_args", {"enable_thinking": False})),
        ]
    def health_url(self) -> str: return "http://127.0.0.1:8787/v1/models"
```

> **Why two backends, and why the MoE matters (from the benchmark in `docs/original_articles.md`, Part 2):**
> Local agentic coding is **prefill-bound, not decode-bound** — Claude Code re-sends an 18–25k-token prompt every turn and the model usually replies with a short tool call. So **time-to-first-token dominates**, and the lever is *active parameters per token*, not speculative decoding:
> - At a realistic **24k-token** context the MoE (`35B-A3B`, ~3B active) reaches first token in **~31 s** vs **~141 s** for dense+DFlash and **~195 s** for plain dense (**~4.5–6.3× faster**).
> - DFlash wins **decode** (145–182 tok/s) — but decode isn't the bottleneck for agents, so it loses the per-turn clock at real context sizes. DFlash only "feels" fastest on tiny `/clear`'d prompts.
> - On a cache miss (e.g. the infamous 35k-token "stop the servers" stall), the MoE turns a **~4-minute** re-prefill into a **~45 s** one.
>
> **Implication for this plan:** the model recommendation must be **workload-aware**, not purely RAM-based. For the autonomous agentic loop, **prefer the MoE even on a 64 GB Mac**; reserve dense+DFlash for decode-heavy or max-quality work. Headroom's context compression and aggressive `/clear`/short-context hygiene attack the same prefill cost and stack on top.

### Example: what the loop driver becomes (logic decoupled from launch)

```python
# llmstack/core/supervisor.py  (sketch)
class Supervisor:
    def __init__(self, cfg, services, mode, notifier, bus):
        self.cfg, self.services, self.mode = cfg, services, mode
        self.notify, self.bus = notifier, bus

    def run(self):
        self.services.ensure_all_running()        # launch concern delegated
        while not self.bus.should_stop():
            task = self.mode.next_task()           # loop-mode strategy decides
            if task is None: break
            self.bus.wait_if_paused()              # control plane
            result = self._execute(task)           # executors + gates
            self.mode.on_result(task, result)
            self.notify.emit(TaskEvent(task, result))   # pluggable sinks
```

---

## 3 · Phase 0 — Modular Refactor (FOUNDATION, do first)

This phase changes **structure, not behavior**. After it, the system must run identically to today.

### Phase 0 reality check (implemented)

Phase 0 is completed, with a few deliberate implementation differences from the original wording below.

| # | Task | Status | Updated acceptance / notes |
|---|------|--------|----------------------------|
| 0.1 | Create `llmstack/` package skeleton with empty modules + `__init__.py` | ✅ Done | Package exists and is importable. |
| 0.2 | Extract config loading from `kowalski_loop.py` → `llmstack/config.py` (`load_config()`, validation, defaults, env derivation) | ✅ Done | `llmstack/config.py` is now the single config loader with normalization and env derivation. |
| 0.3 | Extract server lifecycle (`start_server`, `wait_for_health`, `kill_server`, `restart_server`, `_ping`) → `llmstack/services/dflash_service.py` + generic `manager.py` | ✅ Done | DFlash lifecycle is encapsulated in `DFlashService` implementing `ServiceManager`. |
| 0.4 | Extract Headroom boot (from `kowalski_launcher.bash` + `start_headroom.bash`) → `llmstack/services/headroom_service.py` | ✅ Done | Headroom lifecycle is centralized in `HeadroomService` (including env isolation and health loop). |
| 0.5 | Extract CCR config patching + trust pre-seeding (duplicated in 3 bash files) → `llmstack/services/ccr_service.py` | ✅ Done | `CCRService` exposes `patch_timeout(ms)` and `pretrust(path)`; CLI paths now call the service. |
| 0.6 | Move gates (`_verify`, `_check_wiring`, `_run_smoke`, `_review`, `_changed_files`) → `llmstack/core/gates.py` | ✅ Done | Gate logic moved to `llmstack/core/gates.py` and used by executors/supervisor. |
| 0.7 | Move executors (`run_direct_task`, `execute_task`, `_evaluate`, `_choose_executor`) → `llmstack/core/executors.py` | ✅ Done | Executor split is complete; behavior remains aligned to current runtime. |
| 0.8 | Move git logic → `llmstack/core/git_ckpt.py` | ✅ Done | Checkpoint/restore/WIP logic is centralized in `GitManager`. |
| 0.9 | Reassemble `Supervisor` in `llmstack/core/supervisor.py` wiring the above | ✅ Done | `Supervisor` orchestrates plan loop using services, executors, gates, and git checkpointing. |
| 0.10 | Create `llmstack/cli.py` with subcommands: `serve`, `proxy`, `interactive`, `run`, `dashboard`, `doctor` | ✅ Done | Subcommands exist and drive the modular stack. |
| 0.11 | Convert bash launchers into 5-line shims calling the CLI | ✅ Done (implemented differently) | Entry points are now in `bin/` (`launch_kowalski.bash`, `launch_ccr.bash`, `launch_dashboard.bash`, `start_*`), not root-level `kowalski_launcher.bash`. |
| 0.12 | Add `compileall` + a smoke test that loads config and dry-runs gate selection | ✅ Done (implemented differently) | Validation is covered by runtime gates + `llmstack doctor` health checks rather than a dedicated in-repo `compileall` + dry-run-gates script. |

**Migration outcome:** refactor was delivered alongside runtime parity. Launching has been flipped to CLI wrappers in `bin/`, and legacy scripts are retained under `old/` and `llmstack/tools/` for backwards compatibility/history.

**Example shim after refactor:**
```bash
# kowalski_launcher.bash (after Phase 0)
#!/bin/bash
set -e
cd "$(dirname "$0")"
source env/bin/activate
exec python -m llmstack.cli run "$@"
```

---

## 4 · Phase 1 — Model Generalization

### Phase 1 reality check (updated)

Important correction: until now we had implemented only the dynamic CCR config rewrite path, not the full Phase 1 model-generalization scope.

Current implementation status after this update:
- ✅ 1.1 Model registry implemented (`llmstack/models/registry.py`).
- ✅ 1.2 DFlash + TurboQuant backend classes implemented (`llmstack/models/dflash.py`, `llmstack/models/turboquant.py`).
- ✅ 1.3 Service stack now consumes active backend (no hardcoded dflash argv in `services/stack.py`).
- ✅ 1.4 Executors now use active model target/chat URL from backend (removed `MODEL` constant hardcoding in `core/executors.py`).
- ✅ 1.5 CCR sync is model-aware and supports backend metadata while generating multi-model config.
- ✅ 1.6 `llmstack model list` / `llmstack model use <name>` implemented and wired to config persistence + CCR rewrite + `ccr restart`.
- ✅ 1.7 Workload-aware recommendation policy automation implemented via `llmstack model recommend --use agentic|decode [--apply]` (RAM + intended use).
- ✅ 1.8 Dashboard header now shows active model.

#### Phase 1 hardening (added after backend integration review)

- ✅ 1.9 **Hot backend swap on model switch.** `llmstack model use <name>` and `model recommend --apply` now also restart the inference server (`_restart_inference_server_if_running` in `llmstack/cli.py`): if a server is already serving on `:8787` with a different model, it is stopped and the active backend (DFlash/TurboQuant) is started in its place. If nothing is serving, the swap is skipped and the next `llmstack run`/`serve` starts the correct backend (avoids forcing a cold model load).
- ✅ 1.10 **Port 8787 detection / stale-model guard.** `DFlashService` (backend-agnostic inference service) gained `served_model_id()` (reads `:8787/v1/models`) and `_free_port()` (kills processes holding the port). `ensure_running()` reuses the server if it already serves the active model, replaces it on mismatch, otherwise starts fresh — preventing port conflicts and stale models.
- ✅ 1.11 **Doctor served-model check.** `llmstack doctor` compares the model actually served on `:8787` against `active_model` and reports a mismatch (non-zero exit) with a remediation hint.
- ✅ 1.12 **Explicit TurboQuant backend scripts.** `bin/start_turboquant_server.bash` (switches `active_model` to a TurboQuant model + syncs CCR + serves on `:8787`) and `bin/stop_turboquant_server.bash` mirror the DFlash scripts. `llmstack serve [<model_name>]` accepts an optional model to start a specific backend coherently with CCR.
- ✅ 1.13 **Dashboard multi-backend awareness implemented.** (`llmstack/tools/dflash_dashboard.py`)
  - Detect active backend at runtime (`dflash` / `turboquant`) and show it in the dashboard header with `active_model` + target.
  - Keep a backend-agnostic metric layer (Headroom traffic: in/out tokens, savings, cache/compression, total latency).
  - Add backend-specific parsers behind a common interface:
    - `DFlashParser`: keep current rich metrics (`prefill`, `decode`, `accept%`, `mlx_active/peak`, cache hit).
    - `TurboQuantParser`: parse the subset of metrics actually available in TurboQuant logs (typically fewer fields) and expose `N/A` for non-applicable metrics.
  - Render adaptive UI panels/columns: always show common metrics; show backend-specific metrics only when present.
  - Optional but recommended: split inference CSV/log output by backend (`timings_dflash.csv`, `timings_turboquant.csv`) or add a `backend` column.

> **Note on the service layer:** both backends bind `:8787` and speak the OpenAI-compatible API, so the single `DFlashService` (despite its name) manages **either** backend generically — `build_serve_cmd()` comes from the active backend (`DFlashBackend` or `TurboQuantBackend`). Headroom (`:8789`) forwards to `:8787` regardless of backend, and CCR remains required for the Anthropic→OpenAI agentic path (neither backend is natively Anthropic-compatible).


### 4.1 Model registry in `llmstack_config.json`

```json
{
  "active_model": "dflash-qwen27b",
  "models": {
    "dflash-qwen27b": {
      "type": "dflash",
      "target": "mlx-community/Qwen3.6-27B-4bit",
      "draft": "z-lab/Qwen3.6-27B-DFlash",
      "verify_mode": "adaptive",
      "max_tokens": 8192,
      "temp": 0.2,
      "chat_template_args": { "enable_thinking": false },
      "cache_max_bytes": "12GB",
      "cache_max_entries": 64,
      "max_snapshot_tokens": 16000,
      "ram_required_gb": 48,
      "description": "Dense 27B with DFlash speculative decoding (64GB Mac)"
    },
    "turboquant-qwen35b-moe": {
      "type": "turboquant",
      "target": "manjunathshiva/Qwen3.6-35B-A3B-tq3-g32",
      "draft": null,
      "kv_k_bits": 8,
      "kv_v_bits": 3,
      "kv_min_tokens": 128,
      "prompt_concurrency": 1,
      "max_tokens": 8192,
      "temp": 0.2,
      "ram_required_gb": 24,
      "best_for": "agentic",
      "description": "Sparse MoE 35B / ~3B active. Prefill-optimized: ~6x faster TTFT than dense at 24k ctx. Best default for the agentic loop; also the 16GB-Mac path."
    }
  }
}
```

> **`pip` package for the MoE:** `turboquant-mlx-full` (`pip install -U "turboquant-mlx-full>=0.4.1"`), served via `turboquant-serve`. The MoE has **no draft model** (`draft: null`) — speculative decoding is a dense-model technique.

> **Recommended default policy (workload-aware):**
> - **Agentic / autonomous (Kowalski) →** `turboquant-qwen35b-moe` (prefill-bound workload; the MoE's TTFT advantage dominates).
> - **Decode-heavy / max quality →** `dflash-qwen27b` (4-bit dense is lossless under DFlash and prefills faster *per bit* than 3-bit, but is far slower at long context).
> - **≤ ~24 GB RAM →** MoE is the only viable path.

### 4.2 Tasks
| # | Task | Acceptance criteria |
|---|------|---------------------|
| 1.1 | Implement `ModelConfig` + `load_active_model()` in `models/registry.py` | Returns a backend instance for `active_model` |
| 1.2 | Implement `DFlashBackend` and `TurboQuantBackend` (see §2 example) | `build_serve_cmd()` reproduces today's argv exactly for dflash |
| 1.3 | `dflash_service` consumes the backend (no hardcoded argv) | Switching `active_model` changes the serve command |
| 1.4 | `executors` read model name + chat URL from registry (drop the `MODEL` constant) | Direct calls hit the active model |
| 1.5 | `ccr_service.sync_provider(backend)` rewrites CCR config from backend metadata | **CCR becomes multi-model**: multiple provider/model entries are present; `Router.default/background/think/longContext/webSearch` point to the active model mapping |
| 1.6 | CLI: `llmstack model list` / `llmstack model use <name>` | Switching persists `active_model`, restarts services |
| 1.7 | Workload-aware recommendation: combine `sysctl hw.memsize` **and** intended use | Agentic/≤24GB → MoE; decode-heavy & >32GB → dense+DFlash (see policy above) |
| 1.8 | Dashboard header shows the active model name | Visible in TUI |
| 1.13 | Dashboard backend-aware rendering + parser abstraction | Header shows active backend/model/target; TurboQuant path renders partial metrics safely (`N/A` where unavailable) while preserving full DFlash metrics |

#### 4.2.1 Detailed implementation steps for 1.13 (Dashboard multi-backend)

Implementation sequence (low-risk, incremental):

1. **Introduce runtime backend detection (`detect_active_backend`)**
  - Inputs: `llmstack_config.json`, process bound to `:8787`, `/v1/models` response.
  - Resolution priority:
    1) process cmdline signature (`turboquant-serve` vs `dflash`),
    2) `active_model` type from model registry,
    3) fallback `unknown`.
  - Output payload:
    - `backend_name` (`dflash`/`turboquant`/`unknown`)
    - `active_model_name`
    - `active_target`
    - `served_target` (if available)
    - `confidence` (`high`/`medium`/`low`)

2. **Refactor log parsing to a pluggable parser interface**
  - Add `BaseInferenceParser` with normalized event output:
    - `timestamp`, `req`, `prompt_tokens`, `decode_tokens`, `decode_tps`, `total_time_s`
    - optional fields: `prefill_time_s`, `accept_pct`, `prefill_real_tps`, `cache_hit_pct`, `mlx_active_gb`, `mlx_peak_gb`
  - Implement `DFlashParser` by reusing current regex behavior unchanged.
  - Implement `TurboQuantParser` for available TurboQuant log fields only.
  - Missing fields must be emitted as `None` and rendered as `N/A` in UI.

3. **Split dashboard metrics into common vs backend-specific layers**
  - Common (always visible, backend-agnostic):
    - Headroom request counts, input/output tokens, tokens saved, savings %, cache/compression ratios, recent request latency.
  - Backend-specific (conditional):
    - DFlash: prefill bars, accept %, MLX/cache lines, detailed decode/prefill rates.
    - TurboQuant: reduced panel (no fake values), only metrics present in parser output.

4. **Make the header backend-aware and runtime-accurate**
  - Header string must include:
    - `backend_name`
    - `active_model_name`
    - `active_target`
    - health status
  - If `served_target != active_target`, show a warning badge (`MISMATCH`) in header.

5. **Adapt tables and CSV output to sparse metrics**
  - Keep one normalized schema with optional columns or add a `backend` column.
  - Recommended:
    - either a single CSV with `backend` + nullable fields,
    - or two backend-specific CSVs (`timings_dflash.csv`, `timings_turboquant.csv`).
  - No renderer should assume DFlash-only fields are always present.

6. **Backward compatibility and migration**
  - Existing DFlash behavior and visuals must remain unchanged when backend is DFlash.
  - Existing log files remain valid input.
  - `unknown` backend must not crash the dashboard; show common metrics only.

Acceptance tests for 1.13:

1. Start DFlash backend and open dashboard:
  - Header shows `backend=dflash` and active model/target.
  - DFlash-specific panels render exactly as today.

2. Switch to TurboQuant backend and open dashboard:
  - Header shows `backend=turboquant` and active model/target.
  - Dashboard remains fully functional with reduced metric surface (`N/A` where unavailable).

3. Force mismatch scenario (`active_model` different from served model):
  - Header displays explicit mismatch indicator.
  - Dashboard keeps running and reports common metrics.

4. Regression check:
  - No exceptions while tailing mixed historical logs.
  - CSV rows are written correctly for both backends.

### 4.3 CCR multi-model config requirement (critical)

Current live config is single-model (`Providers[0].models = ["mlx-community/Qwen3.6-27B-4bit"]` and all `Router.*` keys pinned to that same pair). For Phase 1, CCR config generation must become model-aware and multi-model.

Minimum target behavior:
1. Keep one provider entry per backend family (e.g. `dflash`, `turboquant`) with `api_base_url` pointing to Headroom `:8789`.
2. Populate provider `models` with all configured model targets for that backend.
3. Rewrite `Router.default/background/think/longContext/webSearch` to the currently active provider+model pair.
4. Preserve global settings (`NON_INTERACTIVE_MODE`, `API_TIMEOUT_MS`, transformer defaults) unless explicitly overridden.
5. `llmstack model use <name>` updates `active_model`, rewrites CCR config, and restarts `ccr`.

Example target shape (abbreviated):

```json
{
  "Providers": [
    {
      "name": "dflash",
      "api_base_url": "http://127.0.0.1:8789/v1/chat/completions",
      "models": ["mlx-community/Qwen3.6-27B-4bit"]
    },
    {
      "name": "turboquant",
      "api_base_url": "http://127.0.0.1:8789/v1/chat/completions",
      "models": ["manjunathshiva/Qwen3.6-35B-A3B-tq3-g32"]
    }
  ],
  "Router": {
    "default": "turboquant,manjunathshiva/Qwen3.6-35B-A3B-tq3-g32",
    "background": "turboquant,manjunathshiva/Qwen3.6-35B-A3B-tq3-g32",
    "think": "turboquant,manjunathshiva/Qwen3.6-35B-A3B-tq3-g32",
    "longContext": "turboquant,manjunathshiva/Qwen3.6-35B-A3B-tq3-g32",
    "webSearch": "turboquant,manjunathshiva/Qwen3.6-35B-A3B-tq3-g32"
  }
}
```

**Example CLI session:**
```bash
$ llmstack model list
  dflash-qwen27b        (active)  dense 27B · needs 48GB RAM
  turboquant-qwen35b-moe          MoE 35B/3B · needs 12GB RAM
$ llmstack model use turboquant-qwen35b-moe
🔧 active_model → turboquant-qwen35b-moe; restarting services...
```

**Forward-compat targets:** Llama 4 Scout/Maverick, DeepSeek V3/R1 (MoE), future Qwen quantizations, LoRA adapters via `mlx_lm.lora` — each is one new backend class + one config block.

---

## 5 · Phase 2 — Loop Modes (pluggable strategies)

All modes implement `LoopMode` (`next_task()`, `on_result(task, result)`), selected via config:

```json
{ "loop_mode": "plan", "modes": { "continuous": { "queue_file": "task_queue.json" } } }
```

| # | Task | Mode | Acceptance criteria |
|---|------|------|---------------------|
| 2.1 | `plan_mode.py` — wrap current ordered-plan behavior | `plan` | ✅ Done — `LoopMode` ABC + `PlanMode` reproduce the ordered-plan behavior identically |
| 2.2 | `continuous_mode.py` — read/append a queue, run forever | `continuous` | ✅ Done — queue-backed mode reloads on append; new task appended to `task_queue.json` is picked up |
| 2.3 | `watch_mode.py` — `watchdog` observer, enqueue on file change | `watch` | ✅ Done — editing a `*.py` enqueues a lint/fix task (watchdog observer + mtime fallback) |
| 2.4 | `supervised_mode.py` — preview next task, await approval (console or Telegram) | `supervised` | ✅ Done — console approval blocks until approve/skip, with skipped tasks persisted |
| 2.5 | Priority ordering — honor a `priority` field on tasks | any | ✅ Done — higher-priority tasks run first across plan, continuous, watch, and supervised modes |
| 2.6 | Smart retry with error feedback — capture verify stderr, inject into retry prompt | core | ✅ Done — `verify_detailed` feedback is captured and injected into the next direct/agent retry prompt (truncated) |

**Example smart-retry injection:**
```python
if attempt > 1 and last_error:
    user += f"\n\nThe previous attempt FAILED verification with:\n{last_error[:800]}\nFix exactly this."
```

---

## 6 · Phase 3 — Pragmatic Extensibility Before Remote Control

This phase intentionally pulls forward the **low-coupling, high-leverage** pieces from the old Phase 5. The rule is strict: only ship features that fit the current single-process, single-project architecture and attach to seams that already exist today.

### 6.1 Pluggable verification gates (anticipated old 5.3)

Goal: extend verification without hardcoding more logic into `verify_detailed()`.

| # | Task | Acceptance criteria |
|---|------|---------------------|
| 3.1 | Add config schema for `verification_plugins` with defaults = disabled | ✅ Done — `load_config()` normalizes and validates plugin definitions; omitted config preserves current behavior |
| 3.2 | Define plugin shape: `command`, `when`, `languages`, `files`, `on_failure`, `enabled` | ✅ Done — invalid plugin definitions fail fast with a clear config error |
| 3.3 | Add gate runner in `core/gates.py` after built-in deterministic checks | ✅ Done — configured plugin commands run in `dev_root` and contribute pass/fail to verification |
| 3.4 | Support task-level opt-in/opt-out (`task["verification_plugins"]` or `task["disable_plugins"]`) | ✅ Done — tasks can allow-list or suppress named plugins |
| 3.5 | Define failure semantics: plugin stderr/stdout is fed into smart retry feedback | ✅ Done — failing `fail` plugins store feedback on the task for the next retry prompt |
| 3.6 | Ship 2-3 example plugins in docs: `ruff check {file}`, `tsc --noEmit`, `pytest -x` on `plan_complete` | ✅ Done — README documents task plugins, `plan_complete`, interpolation, and examples |
| 3.7 | Add narrow tests for plugin selection, substitution, pass/fail, and disabled-by-default behavior | ✅ Done — `tests/test_phase3_pluggable_gates.py` passes |

**Design constraints:**
- Preserve the built-in gates (`verify`, `expect`, `require_change`, `wiring`, `smoke`) as the default path.
- Start with **shell-command plugins only**; no Python entrypoint/plugin loader system yet.
- Keep interpolation minimal and explicit: `{file}`, `{dev_root}`, `{plan_file}` only.
- `plan_complete` hooks must run only once at the end, not after every task.

### 6.2 Minimal `llmstack init` wizard (anticipated old 5.1)

Goal: reduce onboarding friction without introducing multi-project state yet.

| # | Task | Acceptance criteria |
|---|------|---------------------|
| 3.8 | Add CLI subcommand `llmstack init` | ✅ Done — running it interactively creates a starter `llmstack_config.json` in the current workspace |
| 3.9 | Ask only the minimum: `dev_root`, project type, goal, inference backend/model preference | ✅ Done — prompt flow completes in under a minute for a new user |
| 3.10 | Generate a single-project config using current stable keys only | ✅ Done — produced config works with existing `run`, `interactive`, `model`, and `serve` commands |
| 3.11 | Optionally bootstrap a starter plan path and call `build_plan.py` with the provided goal | ✅ Done — user ends with both config and a first draft plan |
| 3.12 | Provide non-interactive flags for the same fields (`--dev-root`, `--goal`, `--project-type`) | ✅ Done — wizard can be used from scripts without prompt input |
| 3.13 | Refuse to overwrite an existing config unless `--force` is passed | ✅ Done — existing work is protected by default |
| 3.14 | Document 2-3 starter profiles (Python script, JS app, generic codebase) | ✅ Done — new user can choose a sensible default without editing many keys |

**Scope guardrails:**
- Single project only; do **not** invent `projects[]` yet.
- No remote credentials, Telegram, or dashboard setup.
- No installer responsibilities; this wizard writes config, not environments.

### 6.3 Per-task `thinking_mode` (anticipated old 5.4)

Goal: expose a controllable quality/cost knob for agentic tasks.

| # | Task | Acceptance criteria |
|---|------|---------------------|
| 3.15 | Add config default `thinking_mode: "off"` and task override `thinking_mode` | ✅ Done — omitted values preserve today's behavior; task-level override wins |
| 3.16 | Support values `off`, `auto`, `on` with validation in config/task normalization | ✅ Done — invalid values fail clearly instead of silently degrading |
| 3.17 | Map the mode to Claude/CCR env toggles in `core/executors.py` | ✅ Done — `off` keeps current env, `auto` enables adaptive thinking, `on` enables full thinking |
| 3.18 | Ensure the mode is visible in debug logs per task attempt | ✅ Done — debug log records the chosen thinking mode per task attempt |
| 3.19 | Allow high-complexity tasks to opt in while cheap tasks stay off | ✅ Done — tasks can mix low-cost direct work with higher-effort agentic runs |
| 3.20 | Document expected trade-offs (latency, token cost, quality) and recommended defaults | ✅ Done — README documents defaults, overrides, and trade-offs |

---

## 7 · Phase 4 — Control Plane & Remote (Telegram)

### 7.1 Control plane (prerequisite for remote)
Phase 0 introduced `control/bus.py` + `control/state.py`. Here we expose them after Phase 3 hardens the single-process UX and gate model:
| # | Task | Acceptance criteria |
|---|------|---------------------|
| 4.1 | `control/ipc.py` — UNIX-socket command server (pause/resume/stop/status/inject-task) | `llmstack ctl status` returns live state |
| 4.2 | Wire `bus.wait_if_paused()` / `should_stop()` into supervisor | `llmstack ctl pause` halts after current task |

### 7.2 Telegram notifier + controller
```json
{
  "telegram": {
    "enabled": true,
    "bot_token_env": "RALPH_TELEGRAM_TOKEN",
    "allowed_chat_ids": [123456789],
    "notify_on": ["task_complete", "task_failed", "plan_complete", "server_crash", "stalled"]
  }
}
```

| # | Task | Acceptance criteria |
|---|------|---------------------|
| 4.3 | `notify/telegram.py` implements `Notifier.emit(event)` | Task events arrive in chat |
| 4.4 | Auto notifications: complete / failed / plan done / crash / stalled | Each event delivered once |
| 4.5 | Command handlers: `/status`, `/plan`, `/stop`, `/pause`, `/resume`, `/logs [n]`, `/metrics` | Commands drive the IPC control plane |
| 4.6 | Advanced: `/task "<prompt>"` (inject), `/model list`, `/model use <name>` | Inject reaches the queue; model switch restarts services |
| 4.7 | Security: token from env var only, `allowed_chat_ids` whitelist, per-command rate limit | Unknown chat IDs rejected; no secret in repo |

**Notification examples:** `✅ Task 5/22 ghosts.js (12.3s)` · `❌ Task 6 failed after 3 attempts (verify gate)` · `🎉 Plan complete 22/22 in 45m` · `🔥 DFlash crashed — restarting`.

---

## 8 · Phase 5 — Dashboards & Analytics

| # | Task | Acceptance criteria |
|---|------|---------------------|
| 5.1 | Move Rich TUI into `dashboard/tui.py`, read from `control/state.py` only | TUI no longer parses logs directly where state exists |
| 5.2 | `dashboard/web.py` — FastAPI + WebSocket streaming the same state | Reachable on LAN, live metrics |
| 5.3 | Per-task metrics in SQLite (`task_id, attempt, outcome, prefill_s, decode_s, tps`) | Queryable history |
| 5.4 | Reports: daily summary (tasks, retries, avg time) emitted via notifier | Daily message/file produced |

---

## 9 · Phase 6 — Multi-Project Workflow

| # | Task | Notes |
|---|------|-------|
| 6.1 | Multi-project config + `llmstack project use <name>` | Array/map of named projects, each with own `dev_root`, plan path, loop defaults, and gate defaults |
| 6.2 | Project-scoped state separation for logs, checkpoints, and queue files | Switching projects does not leak runtime state |
| 6.3 | Project-scoped control/dashboard integration | IPC status and future dashboards identify the active project cleanly |
| 6.4 | Optional project templates layered on top of the minimal wizard | `llmstack init --template js-app` can target a named project entry |

**Multi-project example:**
```json
{
  "active_project": "pacman",
  "projects": {
    "pacman": {
      "dev_root": "./pacman_clone",
      "plan_file": "./pacman_clone/.claude/plans/pacman_plan.json"
    },
    "api": {
      "dev_root": "./services/api",
      "plan_file": "./services/api/.claude/plans/api_plan.json"
    }
  }
}
```

---

## 10 · Phase 7 — Automated Installation (LAST)

Installation is automated **only after the codebase is modular and feature-complete**, so the installer provisions a known-good structure rather than a moving target.

> **Ground truth (verified on the working machine, 2026-06-26).** The installer must replicate this *exactly*; these values were captured from the live setup. The manual guide is now `INSTALL.md` (root), which documents the full flow including Headroom:
> - **Project venv:** `env/` built with **Python 3.14** (`/opt/homebrew/opt/python@3.14`).
> - **Headroom venv:** a **separate** `~/headroom-env/` built with **Python 3.13** (`/opt/homebrew/opt/python@3.13`). Headroom is **not** compatible with the 3.14 project venv and must stay isolated.
> - **Headroom package name is `headroom-ai`** (currently `0.26.0`), exposed as the `headroom` executable. `pip install headroom` is WRONG.
> - **Claude Code** is a **native arm64 binary** at `~/.local/bin/claude` (v2.1.183) *and* also present as the npm global `@anthropic-ai/claude-code`. Ensure `~/.local/bin` precedes the npm path on `PATH`, or pick one consistently.
> - **CCR** = `@musistudio/claude-code-router` (npm global, v2.0.0), launched via `ccr`.
> - **Node** = `node@20` (v20.20.2) from Homebrew keg `/opt/homebrew/opt/node@20/bin`.
> - **CCR `api_base_url` points at Headroom `:8789`**, not dflash `:8787`. Timeout is `3600000` ms in both `API_TIMEOUT_MS` and the provider `timeout`. `NON_INTERACTIVE_MODE: true` is set.
> - Machine has **64 GB** → *both* paths fit. The current live setup runs the **dense DFlash** path, but per the Part 2 benchmark the **MoE is the better default for the agentic loop** even here (prefill-bound). The installer should default the **agentic** profile to the MoE and offer dense+DFlash as the decode-heavy / max-quality alternative.

### 9.0 Prerequisite captured from manual history (do not skip)
These are the manual gotchas that took trial-and-error and MUST be scripted:
1. `npm config set allow-scripts=@anthropic-ai/claude-code --location=user` **before** installing Claude (npm now blocks its post-install script).
2. **Accept the HF license** for `z-lab/Qwen3.6-27B-DFlash` in the browser, then `hf auth login` — gated download fails silently otherwise.
3. **Pre-download** the draft model so dflash doesn't self-kill on its 300 s download timeout.
4. Headroom must be launched with `VIRTUAL_ENV`/`PYTHONPATH`/`PYTHONHOME` **unset** and `OPENAI_TARGET_API_URL=http://127.0.0.1:8787`, else it inherits the 3.14 venv and breaks.
5. Cloud keys (`ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_API_KEY`) must be **unset** in every launcher, or Claude silently calls the cloud.
6. Folder trust must be pre-seeded in `~/.claude.json` (`hasTrustDialogAccepted`, `hasCompletedProjectOnboarding`) so unattended runs don't block on the trust dialog.

### 9.1 `install/install.sh` — master setup
| Step | Action | Exact command / note |
|------|--------|----------------------|
| 1 | Choose profile (workload + hardware) | Ask intended use; `sysctl -n hw.memsize` ÷ 1024³. **Agentic OR ≤ ~24 GB → TurboQuant MoE (default)**; **decode-heavy/max-quality AND > 32 GB → DFlash dense**. MoE is the recommended default for Kowalski even on 64 GB (prefill-bound). |
| 2 | Install Homebrew if missing | `/bin/bash -c "$(curl -fsSL .../install.sh)"` then run its `eval` PATH lines |
| 3 | Install runtimes | `brew install python@3.14 python@3.13 node@20` (BOTH Pythons: 3.14 for project, 3.13 for Headroom) |
| 4 | Fix Node icu4c crash | `brew reinstall node@20 && brew link --overwrite node@20`; verify `node --version` has no dyld error |
| 5 | PATH ordering | Ensure `/opt/homebrew/opt/node@20/bin` and `~/.local/bin` are on PATH (keg-only node@20) |
| 6 | Create workspace + project venv | `python3.14 -m venv env && source env/bin/activate` |
| 7 | Pip deps (project venv) | `pip install -U pip "huggingface_hub[cli]"` + per step 1: dense → `dflash-mlx`; MoE → `"turboquant-mlx-full>=0.4.1"` |
| 8 | Install `llmstack` package | `pip install -e .` (editable install of the modular core) |
| 9 | npm allow-scripts (CRITICAL) | `npm config set allow-scripts=@anthropic-ai/claude-code --location=user` |
| 10 | npm globals | `npm i -g @anthropic-ai/claude-code @musistudio/claude-code-router` |
| 11 | Verify CLIs | `claude --version`, `ccr -v` (warn if `~/.local/bin/claude` native binary shadows npm — pick one) |
| 12 | HF auth (+ license if dense) | `hf auth login` (token typed directly in terminal — never via any tool). **Dense path only:** also accept the gated license for `z-lab/Qwen3.6-27B-DFlash` at its model page first, or the draft download fails silently. The MoE model is not gated. |
| 13 | Pre-download model(s) | Dense → `hf download z-lab/Qwen3.6-27B-DFlash && hf download mlx-community/Qwen3.6-27B-4bit` (avoids dflash 300 s draft-download timeout). MoE → `hf download manjunathshiva/Qwen3.6-35B-A3B-tq3-g32` (no draft). |
| 14 | Headroom isolated venv | `python3.13 -m venv ~/headroom-env && ~/headroom-env/bin/pip install -U pip headroom-ai`; verify `~/headroom-env/bin/headroom --version` |
| 15 | Generate CCR config | Write **multi-model** `~/.claude-code-router/config.json` from `ccr_service.render()` — one provider per backend family, provider `models` lists all configured targets, and `Router.*` points to current `active_model`; **`api_base_url` → `http://127.0.0.1:8789/v1/chat/completions` (Headroom)**, `timeout`/`API_TIMEOUT_MS` = `timeout_seconds × 1000`, `NON_INTERACTIVE_MODE: true`, transformer `maxtoken=8192`+`enhancetool`, `context_window: 32000`, `system_prompt_caching: true` |
| 16 | Generate `llmstack_config.json` | From `kowalski_config.template.json`; prompt for `dev_root` (or run `llmstack init`) |
| 17 | Pre-seed folder trust | Write `hasTrustDialogAccepted`/`hasCompletedProjectOnboarding` for `dev_root` into `~/.claude.json` |
| 18 | Smoke test | `llmstack doctor` then: start the **active model's server** (`dflash serve` or `turboquant-serve`) → wait health on `:8787/v1/models` → start Headroom → assert it logged upstream `127.0.0.1:8787` and answers `:8789/health` → `ccr restart` → one `ccr code -p "say OK" --max-turns 1` round-trip → shut all down |
| 19 | Print next steps | Interactive (`bin/launch_ccr.bash`) vs Autonomous (`bin/launch_kowalski.bash`) |

**Headroom launch contract the installer/service must honor (verbatim from the working launchers):**
```bash
pkill -f "headroom proxy" 2>/dev/null || true
( unset VIRTUAL_ENV PYTHONPATH PYTHONHOME
  export OPENAI_TARGET_API_URL="http://127.0.0.1:8787"
  export OPENAI_API_KEY="dflash-local"
  export HEADROOM_TELEMETRY=off
  exec ~/headroom-env/bin/headroom proxy --port 8789 --code-aware --no-telemetry \
       --log-file headroom_traffic.jsonl
) >> headroom.log 2>&1 &
# health gate: curl -s http://127.0.0.1:8789/health  AND  grep "127.0.0.1:8787" headroom.log
```

### 9.2 `install/doctor.sh` — diagnostics (`llmstack doctor`)
Checks, with the exact expectations above:
- Tool versions: `python3.14`, `python3.13`, `node@20`, `claude`, `ccr`, `dflash`/`turboquant-serve`, `~/headroom-env/bin/headroom`.
- `~/headroom-env` exists, is **Python 3.13**, and has **`headroom-ai`** installed.
- Project `env/` is **Python 3.14**.
- Ports `8787`/`8789` free (or owned by our services).
- HF token valid (`hf auth whoami`) and the gated draft model is downloaded.
- RAM (`sysctl hw.memsize`) ≥ `ram_required_gb` of the active model.
- CCR config `api_base_url` resolves to `:8789`; cloud keys are unset.
- CCR config is multi-model: provider/model catalog includes all configured local models and `Router.*` points to the active one.
- Health endpoints respond.

### 9.3 `install/update.sh`
Update `dflash-mlx`/`turboquant-mlx-full` (project venv), **`headroom-ai`** (its 3.13 venv), `pip` deps, npm globals (`claude` + `ccr`), then `ccr restart`. Optionally check HF for newer model revisions. Print resulting versions.

> An interim manual equivalent already exists: `bin/update_stack.bash` (npm globals, project-venv packages, `headroom-ai` refresh, `ccr restart`, with `--dry-run` support). `install/update.sh` should supersede it or wrap it.

---

## 10 · Dependencies & Risks
| Risk | Mitigation |
|------|------------|
| Refactor introduces regressions | Phase 0 keeps behavior identical; gate on pacman-plan parity before deleting old files |
| Headroom/CCR change their CLI | Isolated in `services/*`; one place to patch |
| New MLX models need different flags | Handled by per-backend classes |
| Telegram token exposure | Env var only, chat-id whitelist, no secrets in repo |
| Installer fragile across macOS versions | Test on macOS 14/15; `doctor.sh` catches drift |
| **Headroom needs Python 3.13, project needs 3.14** | Installer creates two venvs; `doctor.sh` asserts each interpreter version; Headroom launched with venv env-vars unset |
| **Wrong pip package (`headroom` vs `headroom-ai`)** | Pin `headroom-ai` explicitly in installer + `update.sh` |
| **CCR pointed at dflash instead of Headroom** | `ccr_provider()` hardcodes `:8789`; smoke test greps Headroom log for upstream `:8787` |
| **Native `claude` binary shadows npm install** | Installer detects both, warns, and standardizes on one PATH entry |

---

## 11 · Execution Order (summary)
1. ✅ **Phase 0 — Modular refactor** (foundation; behavior-preserving) — *done*
2. ✅ **Phase 1 — Model registry / generalization** — *done*
3. ✅ **Phase 2 — Loop modes + priority ordering + smart retry** — *done*
4. ✅ **Phase 3 — Pluggable gates + minimal init + per-task thinking_mode** — *done*
5. ⬅️ **Phase 4 — Control plane + Telegram** — *NEXT*
6. ⬜ **Phase 5 — Dashboards & analytics**
7. ⬜ **Phase 6 — Multi-project workflow**
8. ⬜ **Phase 7 — Automated installation (install/doctor/update)**

> Rationale: after Phase 2, the cheapest high-value work is whatever attaches to already-stable seams (`config`, `gates`, `executors`, `cli`) without first requiring shared runtime state. Control, dashboards, and multi-project support all become cleaner once those local seams are hardened; installation still stays last so it targets the final shape.

---

## 12 · Immediate Quick Wins (safe to do now, pre-refactor)
1. Create `kowalski_config.template.json` with no hardcoded `dev_root`.
2. Lift model constants (`MODEL`, dflash flags) into `llmstack_config.json` and read them — a stepping stone to the registry.
3. Add error-feedback to retries: capture verify `stderr`, inject into the retry prompt.
4. Native macOS notifications on plan complete/fail via `osascript -e 'display notification ...'`.
5. Add `--model`/`--config` override flags to `start_dflash_server.bash` for quick experiments. ✅ Partially done: `llmstack serve [<model_name>]` accepts an optional model name; `bin/start_turboquant_server.bash` / `bin/stop_turboquant_server.bash` added for the TurboQuant backend.
