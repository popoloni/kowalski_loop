import os
import json
import time

from .plan_mode import PlanMode


class ContinuousMode(PlanMode):
    def __init__(self, config, dev_root, plan, git_manager, executor, services):
        self.queue_file = config.get("continuous_queue_file", "task_queue.json")
        self.poll_seconds = float(config.get("continuous_poll_seconds", 2))
        self._queue_mtime = None
        super().__init__(config, dev_root, self._load_queue_plan(plan), git_manager, executor, services)

    def _load_queue_plan(self, fallback_plan=None):
        plan = fallback_plan if isinstance(fallback_plan, dict) else {"tasks": []}
        if not self.queue_file:
            return plan
        try:
            with open(self.queue_file, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                plan = {"tasks": loaded}
            elif isinstance(loaded, dict):
                plan = loaded if isinstance(loaded.get("tasks"), list) else {"tasks": []}
            self._queue_mtime = os.path.getmtime(self.queue_file)
        except FileNotFoundError:
            plan = fallback_plan if isinstance(fallback_plan, dict) else {"tasks": []}
            self._queue_mtime = None
        except json.JSONDecodeError:
            print(f"⚠️  [Ralph] Continuous queue '{self.queue_file}' is invalid JSON — waiting for a valid queue.")
            plan = fallback_plan if isinstance(fallback_plan, dict) else {"tasks": []}
        return plan

    def _refresh_queue_if_needed(self):
        try:
            mtime = os.path.getmtime(self.queue_file)
        except FileNotFoundError:
            mtime = None
        if mtime != self._queue_mtime:
            self.plan = self._load_queue_plan({"tasks": self.tasks})
            self.tasks = self.plan.get("tasks", [])

    def _persist_plan(self):
        if not self.queue_file:
            return super()._persist_plan()
        with open(self.queue_file, "w", encoding="utf-8") as f:
            json.dump(self.plan, f, indent=2)
        try:
            self._queue_mtime = os.path.getmtime(self.queue_file)
        except FileNotFoundError:
            self._queue_mtime = None

    def _next_available_task(self):
        self._refresh_queue_if_needed()
        return super().next_task()

    def next_task(self):
        while True:
            task = self._next_available_task()
            if task is not None:
                return task
            print(f"⏳ [Ralph] Continuous queue empty — waiting {self.poll_seconds:.1f}s for new tasks...")
            time.sleep(self.poll_seconds)