"""Phase 3 pluggable-gates tests.

Run with the project venv from the repo root:

    env/bin/python tests/test_phase3_pluggable_gates.py

Exits non-zero if any check fails. No third-party test runner required.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llmstack.config import load_config
from llmstack.core.gates import build_task_gate_specs, run_plan_complete_plugins, verify, verify_detailed
from llmstack.core.executors import Executor
from llmstack.core.supervisor import Supervisor


class GitStub:
    def __init__(self, changed=None):
        self.changed = set(changed or {"app.py"})

    def changed_files(self):
        return set(self.changed)


class BackendStub:
    def health_url(self):
        return "http://127.0.0.1:8787/v1/models"

    def model_target(self):
        return "test-model"

    def chat_url(self):
        return "http://127.0.0.1:8787/v1/chat/completions"


class ServicesStub:
    def __init__(self):
        self.backend = BackendStub()
        self.active_model_name = "test-model"
        self.stop_called = False

    def warm_up_cache(self):
        pass

    def stop(self):
        self.stop_called = True

    def should_stop(self):
        return False

    def is_healthy(self):
        return True

    def restart(self):
        pass


class ExecutorStub(Executor):
    pass


def _cfg(**overrides):
    base = {
        "plan_file": "plan.json",
        "require_change": False,
        "wiring_check": False,
        "review_enabled": False,
        "verification_plugins": {},
        "max_retries": 1,
        "max_resumes": 0,
        "task_timeout": 1,
        "max_turns": 1,
        "debug_log": None,
        "debug_max_chars": 0,
        "permission_mode": "acceptEdits",
    }
    base.update(overrides)
    return base


def check(cond, msg):
    if not cond:
        raise AssertionError(f"FAIL: {msg}")
    print(f"  ok: {msg}")


def test_config_defaults_plugins_disabled():
    print("[plugins] default config keeps plugins disabled")
    with tempfile.TemporaryDirectory() as td:
        cfg_path = os.path.join(td, "llmstack_config.json")
        json.dump({}, open(cfg_path, "w"))
        cfg = load_config(cfg_path)
        check(cfg["verification_plugins"] == {}, "verification_plugins defaults to empty")


def test_config_invalid_plugin_fails_fast():
    print("[plugins] invalid plugin config fails fast")
    with tempfile.TemporaryDirectory() as td:
        cfg_path = os.path.join(td, "llmstack_config.json")
        json.dump({"verification_plugins": {"broken": {"when": "task"}}}, open(cfg_path, "w"))
        try:
            load_config(cfg_path)
        except ValueError as exc:
            check("command" in str(exc), "missing command rejected")
        else:
            raise AssertionError("FAIL: invalid plugin config should raise ValueError")


def test_task_plugin_runs_with_substitution_and_language_filter():
    print("[plugins] task plugin runs for matching language and expands {file}")
    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, "app.py"), "w").write("print('ok')\n")
        cfg = _cfg(verification_plugins={
            "capture_file": {
                "command": "printf {file} > plugin_marker.txt",
                "languages": [".py"],
                "when": "task",
            }
        })
        ok, reason, _ = verify_detailed({"file": "app.py"}, td, GitStub(), cfg)
        check(ok and reason == "ok", "matching plugin passed")
        check(open(os.path.join(td, "plugin_marker.txt")).read() == "app.py", "{file} substituted in command")


def test_task_plugin_skipped_by_file_filter():
    print("[plugins] file filter skips non-matching task")
    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, "app.py"), "w").write("print('ok')\n")
        cfg = _cfg(verification_plugins={
            "only_tests": {
                "command": "printf ran > skipped_marker.txt",
                "files": ["tests/*.py"],
                "when": "task",
            }
        })
        ok, reason, _ = verify_detailed({"file": "app.py"}, td, GitStub(), cfg)
        check(ok and reason == "ok", "non-matching plugin skipped cleanly")
        check(not os.path.exists(os.path.join(td, "skipped_marker.txt")), "skipped plugin did not run")


def test_task_plugin_failure_sets_retry_feedback():
    print("[plugins] failing plugin returns feedback for smart retry")
    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, "app.py"), "w").write("print('ok')\n")
        cfg = _cfg(verification_plugins={
            "lint": {
                "command": "printf lint-broke 1>&2; exit 2",
                "when": "task",
            }
        })
        task = {"file": "app.py"}
        ok = verify(task, td, GitStub(), cfg)
        check(not ok, "plugin failure fails verification")
        check("lint-broke" in task.get("_verify_feedback", ""), "failure feedback stored on task")


def test_task_plugin_opt_in_and_disable_lists():
    print("[plugins] task opt-in / disable lists select plugins")
    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, "app.py"), "w").write("print('ok')\n")
        cfg = _cfg(verification_plugins={
            "first": {"command": "printf first > first.txt", "when": "task"},
            "second": {"command": "printf second > second.txt", "when": "task"},
        })
        task = {
            "file": "app.py",
            "verification_plugins": ["first"],
            "disable_plugins": ["second"],
        }
        ok, reason, _ = verify_detailed(task, td, GitStub(), cfg)
        check(ok and reason == "ok", "selected plugin set passed")
        check(os.path.exists(os.path.join(td, "first.txt")), "opted-in plugin ran")
        check(not os.path.exists(os.path.join(td, "second.txt")), "disabled plugin did not run")


def test_standard_gates_use_the_unified_gate_schema():
    print("[plugins] standard gates are normalized into the unified gate schema")
    cfg = _cfg(
        require_change=True,
        wiring_check=True,
        review_enabled=True,
        verification_plugins={
            "python_lint": {
                "command": "ruff check {file}",
                "when": "task",
                "languages": [".py"],
            }
        },
    )
    task = {
        "file": "app.py",
        "verify": "python -m py_compile app.py",
        "expect": ["hello"],
        "smoke": "print('ok')",
    }
    specs = build_task_gate_specs(task, cfg)
    names = [spec["name"] for spec in specs]
    check(
        names == ["verify", "expect", "require_change", "wiring", "smoke", "plugin:python_lint", "review"],
        f"gate schema order was {names}",
    )


def test_thinking_mode_validation_and_env_mapping():
    print("[thinking] validation + env mapping")
    with tempfile.TemporaryDirectory() as td:
        cfg_path = os.path.join(td, "llmstack_config.json")
        json.dump({"thinking_mode": "auto"}, open(cfg_path, "w"))
        cfg = load_config(cfg_path)
        exec_obj = object.__new__(Executor)
        exec_obj.config = cfg
        exec_obj.dev_root = td
        env_off = Executor._apply_thinking_mode(exec_obj, {}, "off")
        env_auto = Executor._apply_thinking_mode(exec_obj, {}, "auto")
        env_on = Executor._apply_thinking_mode(exec_obj, {}, "on")
        check(cfg["thinking_mode"] == "auto", "config default normalized to auto")
        check(env_off["CLAUDE_CODE_DISABLE_THINKING"] == "1", "off disables thinking")
        check(env_auto["CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING"] == "0", "auto enables adaptive thinking")
        check(env_auto["CLAUDE_CODE_DISABLE_THINKING"] == "1", "auto keeps full thinking off")
        check(env_on["CLAUDE_CODE_DISABLE_THINKING"] == "0", "on enables thinking")
        try:
            json.dump({"thinking_mode": "maybe"}, open(cfg_path, "w"))
            load_config(cfg_path)
        except ValueError as exc:
            check("thinking_mode" in str(exc), "invalid thinking mode rejected")
        else:
            raise AssertionError("FAIL: invalid thinking_mode should raise ValueError")


def test_thinking_mode_task_override():
    print("[thinking] task override wins over config default")
    exec_obj = object.__new__(Executor)
    exec_obj.config = _cfg()
    check(exec_obj._thinking_mode_for_task({}) == "off", "default is off")
    check(exec_obj._thinking_mode_for_task({"thinking_mode": "on"}) == "on", "task override to on")
    check(exec_obj._thinking_mode_for_task({"thinking_mode": "auto"}) == "auto", "task override to auto")


def test_plan_complete_plugin_runs_once_via_supervisor():
    print("[plugins] plan_complete hook runs once at end of supervisor run")
    with tempfile.TemporaryDirectory() as td:
        plan_path = os.path.join(td, "plan.json")
        marker = os.path.join(td, "plan_complete.count")
        json.dump({"tasks": []}, open(plan_path, "w"))
        cfg = _cfg(
            plan_file=plan_path,
            dev_root=td,
            verification_plugins={
                "suite": {
                    "command": "printf x >> plan_complete.count",
                    "when": "plan_complete",
                }
            },
        )
        supervisor = Supervisor(cfg, td, ServicesStub())
        supervisor.ensure_git = lambda: None
        supervisor.run()
        check(open(marker).read() == "x", "plan_complete plugin ran exactly once")


def test_plan_complete_runner_direct():
    print("[plugins] direct plan_complete runner works")
    with tempfile.TemporaryDirectory() as td:
        cfg = _cfg(verification_plugins={
            "suite": {
                "command": "printf done > suite.txt",
                "when": "plan_complete",
            }
        })
        ok, reason, _, ran_any = run_plan_complete_plugins(td, cfg)
        check(ok and reason == "ok" and ran_any, "plan_complete plugin runner passed")
        check(open(os.path.join(td, "suite.txt")).read() == "done", "plan_complete command executed")


if __name__ == "__main__":
    tests = [
        test_config_defaults_plugins_disabled,
        test_config_invalid_plugin_fails_fast,
        test_task_plugin_runs_with_substitution_and_language_filter,
        test_task_plugin_skipped_by_file_filter,
        test_task_plugin_failure_sets_retry_feedback,
        test_task_plugin_opt_in_and_disable_lists,
        test_standard_gates_use_the_unified_gate_schema,
        test_thinking_mode_validation_and_env_mapping,
        test_thinking_mode_task_override,
        test_plan_complete_plugin_runs_once_via_supervisor,
        test_plan_complete_runner_direct,
    ]
    failed = 0
    for test_func in tests:
        try:
            test_func()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  !! {test_func.__name__}: {exc}")
    print("\n" + ("ALL PASS" if failed == 0 else f"{failed} FAILED"))
    sys.exit(1 if failed else 0)