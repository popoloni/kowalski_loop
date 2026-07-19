import json
import os
import time

from llmstack.core.executors import Executor
from llmstack.core.gates import run_plan_complete_plugins, review
from llmstack.core.git_ckpt import GitManager
from llmstack.core.runlog import estimate_tokens, log_run
from llmstack.core.strategy import LoopStrategy, resolve_loop_strategy
from llmstack.modes.continuous_mode import ContinuousMode
from llmstack.modes.plan_mode import PlanMode
from llmstack.modes.supervised_mode import SupervisedMode
from llmstack.modes.watch_mode import WatchMode


class Supervisor:
    def __init__(self, config, dev_root, services):
        self.config = config
        self.dev_root = os.path.abspath(dev_root)
        self.services = services
        self.git = GitManager(self.dev_root)
        self.executor = Executor(config, self.dev_root,
                                 git_manager=self.git,
                                 debug_log=config.get("debug_log"),
                                 debug_max=int(config.get("debug_max_chars", 0)),
                                 health_url=self.services.backend.health_url(),
                                 model_name=self.services.active_model_name,
                                 model_target=self.services.backend.model_target(),
                                 direct_url=self.config.get("headroom_chat_url"))
        # Wire the review gate with the same inference endpoint the executor uses.
        review._chat_url = self.executor.direct_url
        review._model_target = self.executor.model_target
        review._task_timeout = int(config.get("task_timeout", 120))

    def ensure_git(self):
        self.git.ensure_git()

    def _should_promote_direct_to_agent(self, task, outcome):
        if outcome == "TIMEOUT":
            # Direct timeouts after continuation rounds rarely recover by retrying direct.
            return True
        if outcome != "VERIFY_FAILED":
            return False
        feedback = str(task.get("_verify_feedback") or "").lower()
        if not feedback:
            return False
        # Structural failures are unlikely to improve with repeated direct generation.
        escalation_markers = [
            "syntaxerror",
            "invalid syntax",
            "was never closed",
            "expected '('",
            "expected an indented block",
            "degenerate",
            "corrupted",
            "repeated",
            "filler text",
        ]
        return any(marker in feedback for marker in escalation_markers)

    def load_plan(self):
        plan_file = self.config["plan_file"]
        if not os.path.exists(plan_file):
            loop_mode = str(self.config.get("loop_mode", "plan")).strip().lower()
            if loop_mode in ("continuous", "watch"):
                return {"tasks": []}
            raise FileNotFoundError(f"Plan file '{plan_file}' not found")
        with open(plan_file, encoding="utf-8") as f:
            return json.load(f)

    def _make_mode(self, plan):
        loop_mode = str(self.config.get("loop_mode", "plan")).strip().lower()
        if loop_mode == "continuous":
            return ContinuousMode(self.config, self.dev_root, plan, self.git, self.executor, self.services)
        if loop_mode == "watch":
            return WatchMode(self.config, self.dev_root, plan, self.git, self.executor, self.services)
        if loop_mode == "supervised":
            return SupervisedMode(self.config, self.dev_root, plan, self.git, self.executor, self.services)
        return PlanMode(self.config, self.dev_root, plan, self.git, self.executor, self.services)

    def run(self):
        plan = self.load_plan()
        mode = self._make_mode(plan)
        tasks = mode.tasks
        print(f"📋 [Kowalski] Loaded {len(tasks)} tasks.")
        self.ensure_git()

        pending = [t for t in tasks if t.get("status") != "completed"]
        if any(self.executor.choose_executor(t) == "agent" for t in pending):
            self.services.warm_up_cache()

        task = mode.next_task()
        while task is not None:
            executor_type = self.executor.choose_executor(task)
            if executor_type == "agent" and not self.executor.syntax_ok(task):
                print("🧹 [Kowalski] Corrupt leftover detected — restoring to last checkpoint.")
                self.git.restore_to_checkpoint(task)

            strategy = LoopStrategy(resolve_loop_strategy(task, plan))
            task_started_at = time.time()
            cumulative_tokens = 0
            escalated = False
            escalation_reason = ""

            hard_fails = resumes = 0
            done = False
            n = 0
            while (not done and hard_fails < self.config["max_retries"] and not self.services.should_stop()):
                if not self.services.is_healthy():
                    self.services.restart()

                if executor_type == "direct":
                    self.git.restore_to_checkpoint(task)

                n = hard_fails + resumes + 1

                budget_hit, budget_reason = strategy.budget_exceeded(
                    attempts_used=n - 1,
                    elapsed_seconds=time.time() - task_started_at,
                    token_estimate=cumulative_tokens,
                )
                if budget_hit:
                    print(f"🛑 [Kowalski] {budget_reason}")
                    escalated = True
                    escalation_reason = budget_reason
                    hard_fails = self.config["max_retries"]
                    break

                tag = executor_type + (", resume" if resumes else "")
                print(f"▶️  [Kowalski] Task {task.get('id')} — attempt {n} ({tag})")

                if executor_type == "direct":
                    original_context = task.get("context")
                    if strategy.spec.get("context_policy") == "changed_only":
                        task["context"] = strategy.effective_context(task, self.git)
                    try:
                        outcome = self.executor.run_direct_task(task, attempt=n)
                    finally:
                        if original_context is None:
                            task.pop("context", None)
                        else:
                            task["context"] = original_context
                else:
                    outcome = self.executor.execute_task(task, attempt=n, resuming=(resumes > 0))

                cumulative_tokens += estimate_tokens(task.get("prompt", ""))

                escalated_this_attempt = False
                if outcome == "OK":
                    safety_ok, safety_reason = strategy.check_safety(self.dev_root, self.git)
                    if not safety_ok:
                        print(f"🛑 [Kowalski] {safety_reason}")
                        outcome = "VERIFY_FAILED"
                        task["_verify_feedback"] = safety_reason
                        escalated = True
                        escalated_this_attempt = True
                        escalation_reason = safety_reason
                    else:
                        checker_ok, checker_reason = strategy.run_checker(task, self.dev_root)
                        if not checker_ok:
                            print(f"🧑‍⚖️ [Kowalski] {checker_reason}")
                            outcome = "VERIFY_FAILED"
                            task["_verify_feedback"] = checker_reason

                result = mode.on_result(
                    task,
                    outcome,
                    {
                        "attempt": n,
                        "executor_type": executor_type,
                        "hard_fails": hard_fails,
                        "resumes": resumes,
                        "done": done,
                    },
                )
                hard_fails = result["hard_fails"]
                resumes = result["resumes"]
                done = result["done"]

                if escalated_this_attempt:
                    # Safety violations are blocked, not retried — no auto-act.
                    hard_fails = self.config["max_retries"]
                    done = False
                elif not strategy.spec.get("run_until_done", True) and not done:
                    # run_until_done=False opts out of the smart-retry loop:
                    # a single failed attempt is final.
                    hard_fails = self.config["max_retries"]

                if (not done
                        and executor_type == "direct"
                        and self._should_promote_direct_to_agent(task, outcome)):
                    executor_type = "agent"
                    print("🔀 [Kowalski] Direct failed structurally — switching to agent for next retry.")

            if not done:
                # on_incomplete() may run `git clean` — do this before writing the
                # runlog entry so the fresh log line doesn't get swept away.
                mode.on_incomplete(task, executor_type)

            log_run(self.dev_root, self.config, {
                "task_id": task.get("id"),
                "strategy": strategy.describe(),
                "executor_type": executor_type,
                "attempts": n,
                "hard_fails": hard_fails,
                "resumes": resumes,
                "outcome": "OK" if done else "INCOMPLETE",
                "escalated": escalated,
                "escalation_reason": escalation_reason,
                "duration_s": time.time() - task_started_at,
                "token_estimate": cumulative_tokens,
            })

            if not done:
                self.services.stop()
                return False

            task = mode.next_task()

        plugins_ok, _, plugins_feedback, _ = run_plan_complete_plugins(self.dev_root, self.config)
        if not plugins_ok:
            close = getattr(mode, "close", None)
            if callable(close):
                close()
            self.services.stop()
            raise RuntimeError(plugins_feedback)

        print("\n🎉 [Kowalski] All tasks verified and committed!")
        close = getattr(mode, "close", None)
        if callable(close):
            close()
        self.services.stop()
        return True
