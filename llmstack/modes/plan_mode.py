import json
import time

from llmstack.core.gates import verify_detailed

from .base import LoopMode


class PlanMode(LoopMode):
    def __init__(self, config, dev_root, plan, git_manager, executor, services):
        self.config = config
        self.dev_root = dev_root
        self.plan = plan
        self.tasks = plan.get("tasks", [])
        self.git = git_manager
        self.executor = executor
        self.services = services

    def _task_priority(self, task):
        try:
            return int(task.get("priority", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _ordered_tasks(self):
        indexed = list(enumerate(self.tasks))
        indexed.sort(key=lambda item: (-self._task_priority(item[1]), item[0]))
        return [task for _, task in indexed]

    def next_task(self):
        for task in self._ordered_tasks():
            if task.get("status") in ("completed", "skipped"):
                print(f"⏭️  [Ralph] Skipping Task {task.get('id')} ({task.get('status')})")
                continue
            return task
        return None

    def _persist_plan(self):
        with open(self.config["plan_file"], "w", encoding="utf-8") as f:
            json.dump(self.plan, f, indent=2)

    def on_result(self, task, outcome, state):
        executor_type = state["executor_type"]
        hard_fails = state["hard_fails"]
        resumes = state["resumes"]
        done = state["done"]
        attempt = state["attempt"]

        if outcome == "FORMAT_ERROR" and executor_type == "agent":
            if task.get("on_format_error") == "direct_context_fallback":
                print("🛟 [Ralph] Agent format error persisted — falling back to direct context generation.")
                outcome = self.executor.run_direct_context_fallback(task, attempt=attempt)
            else:
                print("⚠️  [Ralph] FORMAT_ERROR with no fallback strategy configured.")
                outcome = "AGENT_ERROR"

        if outcome == "OK":
            task["status"] = "completed"
            self._persist_plan()
            self.git.git_checkpoint(task, label="verified")
            print(f"✅ [Ralph] Task {task.get('id')} COMPLETE & verified.")
            done = True
        elif outcome == "ALREADY_DONE":
            allow_already_done = task.get(
                "allow_already_done_if_verified",
                self.config.get("allow_already_done_if_verified", False),
            )
            if not allow_already_done:
                hard_fails += 1
                print(f"⚠️  [Ralph] Agent says already_done but policy is disabled "
                      f"({hard_fails}/{self.config['max_retries']}).")
                time.sleep(2)
            else:
                ok, reason, feedback = verify_detailed(
                    task,
                    self.dev_root,
                    self.git,
                    self.config,
                    require_change_override=False,
                )
                if ok:
                    task.pop("_verify_feedback", None)
                    task["status"] = "completed"
                    self._persist_plan()
                    self.git.git_checkpoint(task, label="already-done-verified")
                    print(f"✅ [Ralph] Task {task.get('id')} ALREADY_DONE and verified.")
                    done = True
                else:
                    task["_verify_feedback"] = feedback or reason
                    hard_fails += 1
                    self.git.restore_to_checkpoint(task)
                    print(f"⚠️  [Ralph] ALREADY_DONE verification failed ({reason}) — rolled back "
                          f"({hard_fails}/{self.config['max_retries']}).")
                    time.sleep(3)
        elif outcome == "SERVER_CRASH":
            print("♻️  [Ralph] Server crash — restarting (not counted).")
            self.services.restart()
            if executor_type == "agent" and self.executor.syntax_ok(task):
                self.git.wip_commit(task)
        elif outcome in ("TIMEOUT", "AGENT_ERROR"):
            if (executor_type == "agent"
                    and self.executor.syntax_ok(task)
                    and self._has_usable_progress(task)):
                if resumes < self.config["max_resumes"]:
                    self.git.wip_commit(task)
                    resumes += 1
                    print(f"⏸️  [Ralph] {outcome} but file is VALID — progress kept, RESUMING "
                          f"(resume {resumes}/{self.config['max_resumes']}).")
                else:
                    hard_fails += 1
                    print(f"⚠️  [Ralph] Resume budget exhausted for task {task.get('id')} "
                          f"({resumes}/{self.config['max_resumes']}); counting as hard fail "
                          f"({hard_fails}/{self.config['max_retries']}).")
                    time.sleep(3)
            else:
                hard_fails += 1
                self.git.restore_to_checkpoint(task)
                print(f"⚠️  [Ralph] {outcome} (no usable progress) — rolled back "
                      f"({hard_fails}/{self.config['max_retries']}).")
                time.sleep(5)
        else:
            hard_fails += 1
            self.git.restore_to_checkpoint(task)
            print(f"⚠️  [Ralph] {outcome} — rolled back ({hard_fails}/{self.config['max_retries']}).")
            time.sleep(5)

        return {
            "attempt": attempt,
            "executor_type": executor_type,
            "hard_fails": hard_fails,
            "resumes": resumes,
            "done": done,
        }

    def on_incomplete(self, task, executor_type):
        if (executor_type == "agent"
                and self.executor.syntax_ok(task)
                and self._has_usable_progress(task)):
            self.git.wip_commit(task)
            print(f"🚧 [Ralph] Task {task.get('id')} INCOMPLETE — valid progress KEPT as WIP. "
                  f"Re-run to resume from here. Halting.")
        else:
            self.git.restore_to_checkpoint(task)
            print(f"🚨 [Ralph] Task {task.get('id')} NOT completed — rolled back. Halting.")

    def _has_usable_progress(self, task):
        changed = self.git.changed_files()
        if not changed:
            return False

        target = task.get("file")
        context = set(task.get("context") or [])
        if target:
            context.add(target)

        if not context:
            return True
        return bool(changed.intersection(context))
