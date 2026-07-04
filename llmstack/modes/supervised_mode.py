from .plan_mode import PlanMode


class SupervisedMode(PlanMode):
    def __init__(self, config, dev_root, plan, git_manager, executor, services):
        super().__init__(config, dev_root, plan, git_manager, executor, services)
        self.approval_mode = str(config.get("supervised_approval_mode", "console")).strip().lower()

    def _approval_prompt(self, task):
        label = task.get("title") or task.get("prompt") or f"Task {task.get('id')}"
        file_name = task.get("file") or "(no file)"
        priority = self._task_priority(task)
        print("\n👀 [Kowalski] Supervised preview")
        print(f"  task={task.get('id')} priority={priority} file={file_name}")
        print(f"  {label}")
        if task.get("prompt"):
            print(f"  prompt={task['prompt']}")

        while True:
            answer = input("Approve task? [a]pprove / [s]kip / [q]uit: ").strip().lower()
            if answer in ("a", "approve", "y", "yes"):
                return "approve"
            if answer in ("s", "skip", "n", "no"):
                return "skip"
            if answer in ("q", "quit", "stop"):
                return "quit"
            print("Please answer approve, skip, or quit.")

    def next_task(self):
        while True:
            task = super().next_task()
            if task is None:
                return None

            decision = self._approval_prompt(task)
            if decision == "approve":
                return task
            if decision == "skip":
                task["status"] = "skipped"
                self._persist_plan()
                print(f"⏭️  [Kowalski] Task {task.get('id')} skipped by user.")
                continue

            self.services.stop()
            return None