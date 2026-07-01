"""Phase 2 loop-mode corner-case tests.

Run with the project venv from the repo root:

    env/bin/python tests/test_phase2_modes.py

Exits non-zero if any check fails. No third-party test runner required.
"""
import builtins
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llmstack.modes.plan_mode import PlanMode
from llmstack.modes.continuous_mode import ContinuousMode
from llmstack.modes.watch_mode import WatchMode
from llmstack.modes.supervised_mode import SupervisedMode


class GitStub:
    def __init__(self):
        self.changed = {"foo.py"}

    def git_checkpoint(self, task, label=""):
        pass

    def restore_to_checkpoint(self, task):
        pass

    def wip_commit(self, task):
        pass

    def changed_files(self):
        return set(self.changed)


class ExecStub:
    def syntax_ok(self, task):
        return True

    def run_direct_context_fallback(self, task, attempt=1):
        return "OK"

    def choose_executor(self, task):
        return task.get("mode", "agent")

    def run_direct_task(self, task, attempt=1):
        return "OK"

    def execute_task(self, task, attempt=1, resuming=False):
        return "OK"


class ServicesStub:
    def __init__(self):
        self.stop_called = False
        self._stop = False

    def restart(self):
        pass

    def warm_up_cache(self):
        pass

    def should_stop(self):
        return self._stop

    def is_healthy(self):
        return True

    def stop(self):
        self.stop_called = True


def _cfg(**overrides):
    base = {
        "max_retries": 3,
        "max_resumes": 8,
        "allow_already_done_if_verified": False,
        "task_timeout": 1,
        "max_turns": 1,
        "require_change": False,
        "wiring_check": False,
        "review_enabled": False,
    }
    base.update(overrides)
    return base


def check(cond, msg):
    if not cond:
        raise AssertionError(f"FAIL: {msg}")
    print(f"  ok: {msg}")


# ---------------------------------------------------------------------------
def test_plan_priority_and_ties():
    print("[plan] priority ordering + ties + missing priority")
    with tempfile.TemporaryDirectory() as td:
        pf = os.path.join(td, "plan.json")
        plan = {"tasks": [
            {"id": 1, "status": "pending", "title": "no-prio", "file": "a.py"},
            {"id": 2, "status": "pending", "title": "low", "file": "b.py", "priority": 1},
            {"id": 3, "status": "pending", "title": "high", "file": "c.py", "priority": 5},
            {"id": 4, "status": "pending", "title": "high2", "file": "d.py", "priority": 5},
        ]}
        json.dump(plan, open(pf, "w"))
        cfg = _cfg(plan_file=pf)
        mode = PlanMode(cfg, td, plan, GitStub(), ExecStub(), ServicesStub())
        order = mode._ordered_tasks()
        ids = [t["id"] for t in order]
        # priority 5 tasks first, ties keep original index order (3 before 4)
        check(ids == [3, 4, 2, 1], f"order was {ids}")


def test_plan_bad_priority():
    print("[plan] non-numeric priority defaults to 0")
    with tempfile.TemporaryDirectory() as td:
        pf = os.path.join(td, "plan.json")
        plan = {"tasks": [
            {"id": 1, "status": "pending", "file": "a.py", "priority": "not-a-number"},
            {"id": 2, "status": "pending", "file": "b.py", "priority": 3},
        ]}
        json.dump(plan, open(pf, "w"))
        cfg = _cfg(plan_file=pf)
        mode = PlanMode(cfg, td, plan, GitStub(), ExecStub(), ServicesStub())
        task = mode.next_task()
        check(task is not None and task["id"] == 2, "task 2 (priority 3) first")


def test_plan_all_done():
    print("[plan] all tasks completed/skipped -> None")
    with tempfile.TemporaryDirectory() as td:
        pf = os.path.join(td, "plan.json")
        plan = {"tasks": [
            {"id": 1, "status": "completed", "file": "a.py"},
            {"id": 2, "status": "skipped", "file": "b.py"},
        ]}
        json.dump(plan, open(pf, "w"))
        cfg = _cfg(plan_file=pf)
        mode = PlanMode(cfg, td, plan, GitStub(), ExecStub(), ServicesStub())
        check(mode.next_task() is None, "no tasks left")


def test_continuous_empty_then_appended():
    print("[continuous] empty queue then appended task picked up")
    with tempfile.TemporaryDirectory() as td:
        qf = os.path.join(td, "task_queue.json")
        json.dump({"tasks": []}, open(qf, "w"))
        cfg = _cfg(plan_file=os.path.join(td, "plan.json"),
                   continuous_queue_file=qf, continuous_poll_seconds=0.1)
        mode = ContinuousMode(cfg, td, {"tasks": []}, GitStub(), ExecStub(), ServicesStub())
        check(mode._next_available_task() is None, "empty -> None (non-blocking)")
        # append a task, bump mtime
        time.sleep(0.02)
        json.dump({"tasks": [{"id": 1, "status": "pending", "file": "x.py"}]}, open(qf, "w"))
        os.utime(qf, None)
        task = mode._next_available_task()
        check(task is not None and task["id"] == 1, "appended task picked up after refresh")


def test_continuous_invalid_json():
    print("[continuous] invalid JSON queue -> no crash, empty")
    with tempfile.TemporaryDirectory() as td:
        qf = os.path.join(td, "task_queue.json")
        open(qf, "w").write("{not valid json")
        cfg = _cfg(plan_file=os.path.join(td, "plan.json"),
                   continuous_queue_file=qf, continuous_poll_seconds=0.1)
        mode = ContinuousMode(cfg, td, {"tasks": []}, GitStub(), ExecStub(), ServicesStub())
        check(mode._next_available_task() is None, "invalid json -> None, no crash")


def test_continuous_list_shape():
    print("[continuous] queue stored as bare list works")
    with tempfile.TemporaryDirectory() as td:
        qf = os.path.join(td, "task_queue.json")
        json.dump([{"id": 7, "status": "pending", "file": "x.py"}], open(qf, "w"))
        cfg = _cfg(plan_file=os.path.join(td, "plan.json"),
                   continuous_queue_file=qf, continuous_poll_seconds=0.1)
        mode = ContinuousMode(cfg, td, {"tasks": []}, GitStub(), ExecStub(), ServicesStub())
        task = mode._next_available_task()
        check(task is not None and task["id"] == 7, "list-shaped queue loaded")


def test_continuous_persist_status():
    print("[continuous] completing a task persists status back to queue")
    with tempfile.TemporaryDirectory() as td:
        qf = os.path.join(td, "task_queue.json")
        json.dump({"tasks": [{"id": 1, "status": "pending", "file": "x.py"}]}, open(qf, "w"))
        cfg = _cfg(plan_file=os.path.join(td, "plan.json"),
                   continuous_queue_file=qf, continuous_poll_seconds=0.1)
        mode = ContinuousMode(cfg, td, {"tasks": []}, GitStub(), ExecStub(), ServicesStub())
        task = mode._next_available_task()
        mode.on_result(task, "OK", {"attempt": 1, "executor_type": "agent",
                                    "hard_fails": 0, "resumes": 0, "done": False})
        persisted = json.load(open(qf))
        check(persisted["tasks"][0]["status"] == "completed", "status persisted to queue file")


def test_watch_enqueue_on_change():
    print("[watch] editing a .py enqueues a fix task (mtime scan)")
    with tempfile.TemporaryDirectory() as td:
        watch_dir = os.path.join(td, "proj")
        os.makedirs(watch_dir)
        target = os.path.join(watch_dir, "mod.py")
        open(target, "w").write("x = 1\n")
        qf = os.path.join(td, "task_queue.json")
        cfg = _cfg(plan_file=os.path.join(td, "plan.json"),
                   watch_queue_file=qf, watch_root=watch_dir,
                   watch_poll_seconds=0.1, watch_debounce_seconds=0.0)
        services = ServicesStub()
        mode = WatchMode(cfg, watch_dir, {"tasks": []}, GitStub(), ExecStub(), services)
        try:
            # prime mtime baseline
            mode._scan_for_changes()
            time.sleep(0.02)
            open(target, "w").write("x = 2\n")
            os.utime(target, None)
            mode._scan_for_changes()
            check(len(mode.tasks) >= 1, "at least one watch task enqueued")
            t = mode.tasks[-1]
            check(t["file"].endswith("mod.py"), "task targets changed file")
            check("py_compile" in t["verify"], "verify runs py_compile")
        finally:
            mode.close()


def test_watch_ignores_non_py_and_queue():
    print("[watch] ignores non-.py and the queue file itself")
    with tempfile.TemporaryDirectory() as td:
        watch_dir = os.path.join(td, "proj")
        os.makedirs(watch_dir)
        qf = os.path.join(watch_dir, "task_queue.json")
        cfg = _cfg(plan_file=os.path.join(td, "plan.json"),
                   watch_queue_file=qf, watch_root=watch_dir,
                   watch_poll_seconds=0.1, watch_debounce_seconds=0.0)
        mode = WatchMode(cfg, watch_dir, {"tasks": []}, GitStub(), ExecStub(), ServicesStub())
        try:
            check(mode._should_ignore(os.path.join(watch_dir, "notes.txt")), "ignores .txt")
            check(mode._should_ignore(qf), "ignores queue file")
            check(mode._should_ignore(os.path.join(watch_dir, "env", "lib.py")), "ignores env/")
            check(not mode._should_ignore(os.path.join(watch_dir, "good.py")), "accepts good.py")
        finally:
            mode.close()


def test_watch_close_idempotent():
    print("[watch] close() is idempotent")
    with tempfile.TemporaryDirectory() as td:
        watch_dir = os.path.join(td, "proj")
        os.makedirs(watch_dir)
        cfg = _cfg(plan_file=os.path.join(td, "plan.json"),
                   watch_queue_file=os.path.join(td, "q.json"), watch_root=watch_dir)
        mode = WatchMode(cfg, watch_dir, {"tasks": []}, GitStub(), ExecStub(), ServicesStub())
        mode.close()
        mode.close()
        check(True, "double close did not raise")


def test_supervised_quit():
    print("[supervised] quit stops services and returns None")
    with tempfile.TemporaryDirectory() as td:
        pf = os.path.join(td, "plan.json")
        plan = {"tasks": [{"id": 1, "status": "pending", "file": "a.py"}]}
        json.dump(plan, open(pf, "w"))
        cfg = _cfg(plan_file=pf)
        services = ServicesStub()
        mode = SupervisedMode(cfg, td, plan, GitStub(), ExecStub(), services)
        answers = iter(["q"])
        orig = builtins.input
        builtins.input = lambda p="": next(answers)
        try:
            check(mode.next_task() is None, "quit -> None")
            check(services.stop_called, "services.stop called on quit")
        finally:
            builtins.input = orig


def test_supervised_skip_then_none():
    print("[supervised] skip all -> None, persisted as skipped")
    with tempfile.TemporaryDirectory() as td:
        pf = os.path.join(td, "plan.json")
        plan = {"tasks": [{"id": 1, "status": "pending", "file": "a.py"}]}
        json.dump(plan, open(pf, "w"))
        cfg = _cfg(plan_file=pf)
        mode = SupervisedMode(cfg, td, plan, GitStub(), ExecStub(), ServicesStub())
        answers = iter(["s"])
        orig = builtins.input
        builtins.input = lambda p="": next(answers)
        try:
            check(mode.next_task() is None, "skip only task -> None")
            persisted = json.load(open(pf))
            check(persisted["tasks"][0]["status"] == "skipped", "skip persisted")
        finally:
            builtins.input = orig


def test_smart_retry_note():
    print("[retry] _verify_feedback becomes retry note")
    from llmstack.core.executors import Executor
    exec_obj = object.__new__(Executor)
    note = Executor._retry_feedback_note(exec_obj, {"_verify_feedback": "SyntaxError: bad"})
    check("SyntaxError: bad" in note and "Fix exactly this" in note, "note contains feedback")
    empty = Executor._retry_feedback_note(exec_obj, {})
    check(empty == "", "no feedback -> empty note")


if __name__ == "__main__":
    tests = [
        test_plan_priority_and_ties,
        test_plan_bad_priority,
        test_plan_all_done,
        test_continuous_empty_then_appended,
        test_continuous_invalid_json,
        test_continuous_list_shape,
        test_continuous_persist_status,
        test_watch_enqueue_on_change,
        test_watch_ignores_non_py_and_queue,
        test_watch_close_idempotent,
        test_supervised_quit,
        test_supervised_skip_then_none,
        test_smart_retry_note,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  !! {t.__name__}: {e}")
    print("\n" + ("ALL PASS" if failed == 0 else f"{failed} FAILED"))
    sys.exit(1 if failed else 0)
