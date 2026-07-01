import json
import os
import time

from llmstack.core.executors import Executor
from llmstack.core.gates import verify_detailed
from llmstack.core.git_ckpt import GitManager


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
                                 direct_url=self.services.backend.chat_url())

    def ensure_git(self):
        self.git.ensure_git()

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

    def load_plan(self):
        plan_file = self.config["plan_file"]
        if not os.path.exists(plan_file):
            raise FileNotFoundError(f"Plan file '{plan_file}' not found")
        with open(plan_file, encoding="utf-8") as f:
            return json.load(f)

    def run(self):
        plan = self.load_plan()
        tasks = plan.get("tasks", [])
        print(f"📋 [Ralph] Loaded {len(tasks)} tasks.")
        self.ensure_git()

        pending = [t for t in tasks if t.get("status") != "completed"]
        if any(self.executor.choose_executor(t) == "agent" for t in pending):
            self.services.warm_up_cache()

        for task in tasks:
            if task.get("status") == "completed":
                print(f"⏭️  [Ralph] Skipping Task {task.get('id')} (completed)")
                continue

            executor_type = self.executor.choose_executor(task)
            if executor_type == "agent" and not self.executor.syntax_ok(task):
                print("🧹 [Ralph] Corrupt leftover detected — restoring to last checkpoint.")
                self.git.restore_to_checkpoint(task)

            hard_fails = resumes = 0
            done = False
            while (not done and hard_fails < self.config["max_retries"] and not self.services.should_stop()):
                if not self.services.is_healthy():
                    self.services.restart()

                if executor_type == "direct":
                    self.git.restore_to_checkpoint(task)

                n = hard_fails + resumes + 1
                tag = executor_type + (", resume" if resumes else "")
                print(f"▶️  [Ralph] Task {task.get('id')} — attempt {n} ({tag})")

                if executor_type == "direct":
                    outcome = self.executor.run_direct_task(task, attempt=n)
                else:
                    outcome = self.executor.execute_task(task, attempt=n, resuming=(resumes > 0))

                if outcome == "FORMAT_ERROR" and executor_type == "agent":
                    if task.get("on_format_error") == "direct_context_fallback":
                        print("🛟 [Ralph] Agent format error persisted — falling back to direct context generation.")
                        outcome = self.executor.run_direct_context_fallback(task, attempt=n)
                    else:
                        print("⚠️  [Ralph] FORMAT_ERROR with no fallback strategy configured.")
                        outcome = "AGENT_ERROR"

                if outcome == "OK":
                    task["status"] = "completed"
                    with open(self.config["plan_file"], "w", encoding="utf-8") as f:
                        json.dump(plan, f, indent=2)
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
                        continue

                    ok, reason = verify_detailed(
                        task,
                        self.dev_root,
                        self.git,
                        self.config,
                        require_change_override=False,
                    )
                    if ok:
                        task["status"] = "completed"
                        with open(self.config["plan_file"], "w", encoding="utf-8") as f:
                            json.dump(plan, f, indent=2)
                        self.git.git_checkpoint(task, label="already-done-verified")
                        print(f"✅ [Ralph] Task {task.get('id')} ALREADY_DONE and verified.")
                        done = True
                    else:
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

            if not done:
                if (executor_type == "agent"
                        and self.executor.syntax_ok(task)
                        and self._has_usable_progress(task)):
                    self.git.wip_commit(task)
                    print(f"🚧 [Ralph] Task {task.get('id')} INCOMPLETE — valid progress KEPT as WIP. "
                          f"Re-run to resume from here. Halting.")
                else:
                    self.git.restore_to_checkpoint(task)
                    print(f"🚨 [Ralph] Task {task.get('id')} NOT completed — rolled back. Halting.")
                self.services.stop()
                return

        print("\n🎉 [Ralph] All tasks verified and committed!")
        self.services.stop()
