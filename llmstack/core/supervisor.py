import json
import os
import time

from llmstack.core.executors import Executor
from llmstack.core.gates import run_plan_complete_plugins
from llmstack.core.git_ckpt import GitManager
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
                                 direct_url=self.services.backend.chat_url())

    def ensure_git(self):
        self.git.ensure_git()

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
        print(f"📋 [Ralph] Loaded {len(tasks)} tasks.")
        self.ensure_git()

        pending = [t for t in tasks if t.get("status") != "completed"]
        if any(self.executor.choose_executor(t) == "agent" for t in pending):
            self.services.warm_up_cache()

        task = mode.next_task()
        while task is not None:
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

            if not done:
                mode.on_incomplete(task, executor_type)
                self.services.stop()
                return

            task = mode.next_task()

        plugins_ok, _, plugins_feedback, _ = run_plan_complete_plugins(self.dev_root, self.config)
        if not plugins_ok:
            close = getattr(mode, "close", None)
            if callable(close):
                close()
            self.services.stop()
            raise RuntimeError(plugins_feedback)

        print("\n🎉 [Ralph] All tasks verified and committed!")
        close = getattr(mode, "close", None)
        if callable(close):
            close()
        self.services.stop()
        return
