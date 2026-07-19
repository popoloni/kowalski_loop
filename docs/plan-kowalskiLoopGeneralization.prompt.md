## Plan: Kowalski Loop Generalization

Generalize Kowalski by turning today's single, sequential JSON-driven task engine into a set of **pluggable loop strategies**, while **keeping Claude Code as the agentic engine**. The `direct|agent` execution split is preserved unchanged; only the "how to iterate" decision becomes swappable. Work is split into two phases: **Phase A (core, do now)** — strategy abstraction, execution feedback, independent checking, context/RAG, budget and safety; **Phase B (postponed, second iteration)** — worktree isolation, multi-loop coordination, and any domain template that requires parallel execution.

**Architecture correction (embedded from code review):** the real generic loop — retry/resume budget, health checks, and `direct → agent` promotion (`_should_promote_direct_to_agent`) — lives in the inner `while` of `Supervisor.run()`, shared by *every* `LoopMode` (`plan`/`continuous`/`watch`/`supervised`). It is **not** inside `PlanMode`/`LoopMode.on_result()`. The `LoopStrategy` abstraction must therefore be anchored at `Supervisor.run()`, so all existing modes inherit it automatically without extra wiring.

**Steps**

*Phase A — Core generalization (do now)*
1. Inventory the current contract: `Supervisor.run()`'s inner while (budget, health checks, promotion), `LoopMode.next_task()/on_result()/on_incomplete()`, `Executor`, `gates`, git checkpoints, and the `plan.json`/`task_queue.json` field set. Output: a table of current task fields, outcomes, and transitions. Depends only on reading the current code.
2. Define a taxonomy of core strategies (Phase A scope only): `run_until_done`, `maker_checker`, `sample_select`, `rag_context`, `budget_guard`, `safety_guardrails`, `domain_loop_templates` (presets that do not require concurrency). Each policy declares when it applies, required inputs, produced outcomes, and compatibility with Claude Code as executor.
3. Extend the plan format without breaking the existing one. Add an optional `strategy` block per task or per plan, with fully backward-compatible defaults: tasks without `strategy` keep using today's priority + retry/resume logic untouched. Suggested fields: `loop_strategy`, `checker`, `context_policy`, `budget`, `risk_policy`, `completion_criteria`.
4. Introduce the `LoopStrategy` abstraction **anchored at `Supervisor.run()`** (not only inside `LoopMode.on_result()`), with hooks `prepare_attempt`, `select_executor`, `evaluate_attempt`, `next_action`, `on_budget`, `on_escalation` wrapping executor_type selection, direct→agent promotion, and the retry/resume counters. Ship a legacy adapter first that reproduces current behavior exactly, so generalization starts from parity, not a rewrite.
5. Reuse the existing `verification_plugins` mechanism (config + `gates.py`, field `when=task|plan_complete`, validated by `normalize_verification_plugins`) for completion-criteria and safety strategies, instead of building a new plugin system from scratch.
6. Implement the core strategies incrementally, in risk/impact order:
   - **Execution feedback / run-until-done** — lowest risk; extends the existing smart-retry feedback so failing verification output is re-fed into the next attempt.
   - **Independent maker/checker** — separate prompt/permissions from the implementer so a plausible-but-wrong result is rejected even when the implementer reports done.
   - **RAG/context injection policy** — pluggable context selection instead of always passing full file context.
   - **Budget guard + runlog** — flagged **greenfield**: no token/cost accounting exists today in `executors.py` (only a word-count degeneracy heuristic); requires intercepting Claude Code/Headroom responses to extract or estimate real usage.
   - **Safety guardrails** — flagged **greenfield**: no denylist/risk-policy exists today in `gates.py`/`config.py`; needs a multi-axis policy (denylist, file-count cap, confidence gate) built from scratch.
7. Document Phase A operating presets: `simple_direct`, `agent_run_until_done`, `verified_maker_checker`, `safe_repo_edit`. Each preset documents tradeoffs, cost, and stop criteria.
8. Migrate examples and compatibility tests: legacy plan JSON files must run unchanged without a `strategy` block; new plan files exercise the new strategies explicitly.
9. Align observability with course metrics: task completion, retries, resumes, false accepts, escalations, token estimate, duration, actions taken, rollback, checkpoint id — saved as comparable JSON per run.

*Phase B — Parallelism & coordination (postponed to a second iteration)*
10. Worktree isolation — flagged **higher complexity than initially assumed**: today's `GitManager` (`core/git_ckpt.py`) assumes a single linear working tree for checkpoint/rollback. Per-worktree checkpointing is not a simple additional policy; it needs a dedicated design pass before effort can be estimated.
11. Multi-loop coordination — a shared `acting_on` registry with priority-based claim arbitration to avoid duplicate work across concurrent loops. Requires first verifying stable, unique task identity across processes/plans.
12. Parallel-dependent domain loop templates — CI sweeper across concurrent PRs, dependency sweeper batches, PR babysitter concurrency, issue triage, changelog drafting at scale. These depend on steps 10-11 landing first.
13. Extended presets: `parallel_worktree`, `ci_repair`, `release_cleanup`, and any triage preset that needs concurrency.

**Relevant files**
- `/Users/enricopapalini/local-llm-workspace/llmstack/core/supervisor.py` — the real shared generic loop (retry/resume budget, promotion); anchor point for the `LoopStrategy` hook.
- `/Users/enricopapalini/local-llm-workspace/llmstack/modes/plan_mode.py` — current sequential behavior, outcome routing; reference for the legacy adapter.
- `/Users/enricopapalini/local-llm-workspace/llmstack/modes/base.py` — `LoopMode` contract; stays orthogonal to `LoopStrategy` (mode decides "which task", strategy decides "how to complete it").
- `/Users/enricopapalini/local-llm-workspace/llmstack/core/executors.py` — `direct` vs `agent` split; Claude Code stays here as the agentic engine, not as a loop strategy.
- `/Users/enricopapalini/local-llm-workspace/llmstack/core/gates.py` — executable verification and smoke behavior; base for independent checker and completion criteria; already hosts `verification_plugins`.
- `/Users/enricopapalini/local-llm-workspace/llmstack/core/git_ckpt.py` — checkpoint, WIP commit, rollback; needed for run-until-done now, and for worktree isolation/safety later (Phase B).
- `/Users/enricopapalini/local-llm-workspace/llmstack/config.py` — default config, budgets, timeouts, and where strategy presets would be declared.
- `/Users/enricopapalini/local_repos/agentic-loop-engineering-course/common/loops.py` — reference for self-refine with real execution feedback.
- `/Users/enricopapalini/local_repos/agentic-loop-engineering-course/common/agents.py` — reference for sample-n, maker/checker, self-tests, and select-by-tests.
- `/Users/enricopapalini/local_repos/agentic-loop-engineering-course/common/memory.py` — reference for retrieval and anti state-rot relevance threshold.
- `/Users/enricopapalini/local_repos/agentic-loop-engineering-course/common/tools.py` — reference for the ReAct/tool loop with execution and feedback.
- `/Users/enricopapalini/local_repos/agentic-loop-engineering-course/common/runlog.py` — reference for the runlog observability schema.

**Verification**
1. Compatibility: running an existing JSON plan without a `strategy` block must produce the same `direct|agent` routing, same checkpoints, same verified result as today.
2. Strategy parsing: plans with complete, partial, and malformed `strategy` blocks — partial must fall back to defaults, malformed must fail with a readable error.
3. Run-until-done: a task that fails first verification and passes after feedback — confirm test output is re-injected into the next attempt.
4. Maker/checker: a task with a plausible-but-wrong implementation — confirm the independent checker rejects it even if the executor reports completion.
5. Budget guard: a low budget must trigger early stop with a complete runlog entry and no runaway loop.
6. Safety gates: a task touching denylisted files or too many changes must be escalated or blocked before auto-act.
7. Worktree isolation (Phase B): two parallel tasks on the same repo must use separate worktrees and surface conflicts instead of losing changes.
8. Multi-loop registry (Phase B): two loops sharing a `coordination_key` must avoid duplicate work via claim/priority.
9. Observability: every run must log duration, token estimate, actions, escalations, outcome, retries/resumes, and checkpoint id.

**Decisions**
- Claude Code remains the agentic engine for `agent` tasks; generalization is about loop/orchestration strategy, not replacing the agentic engine.
- The plan format stays JSON and backward-compatible; the new `strategy` block and presets are opt-in.
- Phase A prioritizes the highest-impact, lowest-risk strategies: execution feedback, independent checker, budget guard, safety gates.
- Phase B (worktree isolation, multi-loop coordination, parallel domain templates) is explicitly postponed — it requires more delicate isolation/coordination and depends on Phase A's `LoopStrategy` abstraction existing first.
- Out of scope for the first iteration: changing the LLM backend, removing direct mode, rewriting the supervisor from scratch, or introducing a non-JSON plan format.

**Further Considerations**
1. Strategy granularity: recommend task-level with plan-level defaults. Enables global presets with local overrides without duplicating configuration.
2. Checker engine: start with Claude Code in an independent checker role (separate prompt/permissions), then consider a cheaper direct-mode checker for low-stakes cases.
3. Parallelism (Phase B): opt-in only when `isolation=worktree` and a `coordination_key` are both defined; sequential remains the default for safety.

