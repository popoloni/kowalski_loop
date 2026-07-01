"""Phase 3 minimal init wizard tests.

Run with the project venv from the repo root:

    env/bin/python tests/test_phase3_init_wizard.py

Exits non-zero if any check fails. No third-party test runner required.
"""
import builtins
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llmstack.cli import run_init


class Args:
    def __init__(self, force=False, extra=None):
        self.force = force
        self.extra = list(extra or [])


def check(cond, msg):
    if not cond:
        raise AssertionError(f"FAIL: {msg}")
    print(f"  ok: {msg}")


class InputFeeder:
    def __init__(self, answers):
        self.answers = list(answers)

    def __call__(self, prompt=""):
        if not self.answers:
            raise AssertionError(f"No more answers left for prompt: {prompt}")
        return self.answers.pop(0)


def test_init_writes_config_and_bootstrap_plan():
    print("[init] writes starter config and bootstraps plan")
    with tempfile.TemporaryDirectory() as td:
        old_cwd = os.getcwd()
        os.chdir(td)
        calls = []
        try:
            feeder = InputFeeder([
                ".",
                "python",
                "Build a tiny CLI tool",
                "",
                "y",
            ])

            def fake_plan_runner(goal, cwd):
                calls.append((goal, cwd))
                plan_dir = os.path.join(cwd, ".claude", "plans")
                os.makedirs(plan_dir, exist_ok=True)
                with open(os.path.join(plan_dir, "python_plan.json"), "w", encoding="utf-8") as f:
                    json.dump({"project": goal, "tasks": []}, f)

            rc = run_init(Args(force=False), input_func=feeder, plan_runner=fake_plan_runner)
            check(rc == 0, "run_init returned success")

            cfg_path = os.path.join(td, "llmstack_config.json")
            check(os.path.exists(cfg_path), "config file created")
            cfg = json.load(open(cfg_path, encoding="utf-8"))
            check(cfg["dev_root"] == ".", "dev_root stored as current directory")
            check(cfg["plan_file"] == os.path.join(".", ".claude", "plans", "python_plan.json"), "plan file derived from project type")
            check(cfg["active_model"] == "turboquant-qwen35b-moe", "recommended model selected")
            check(cfg["loop_mode"] == "plan", "loop mode defaults to plan")
            check(cfg["thinking_mode"] == "off", "thinking mode defaults to off")
            check(cfg["verification_plugins"] == {}, "verification plugins default to empty")
            check(
                len(calls) == 1
                and calls[0][0] == "Build a tiny CLI tool"
                and os.path.realpath(calls[0][1]) == os.path.realpath(td),
                "plan runner called with provided goal and cwd",
            )
            check(os.path.exists(os.path.join(td, ".claude", "plans", "python_plan.json")), "starter plan written")
        finally:
            os.chdir(old_cwd)


def test_init_refuses_overwrite_without_force():
    print("[init] refuses to overwrite config without --force")
    with tempfile.TemporaryDirectory() as td:
        old_cwd = os.getcwd()
        os.chdir(td)
        try:
            with open(os.path.join(td, "llmstack_config.json"), "w", encoding="utf-8") as f:
                json.dump({"sentinel": True}, f)
            rc = run_init(Args(force=False), input_func=InputFeeder([]), plan_runner=lambda *a, **k: None)
            check(rc == 1, "run_init refused overwrite")
            cfg = json.load(open(os.path.join(td, "llmstack_config.json"), encoding="utf-8"))
            check(cfg.get("sentinel") is True, "existing config preserved")
        finally:
            os.chdir(old_cwd)


def test_init_force_overwrites_existing_config():
    print("[init] overwrites existing config with --force")
    with tempfile.TemporaryDirectory() as td:
        old_cwd = os.getcwd()
        os.chdir(td)
        try:
            with open(os.path.join(td, "llmstack_config.json"), "w", encoding="utf-8") as f:
                json.dump({"sentinel": True}, f)
            feeder = InputFeeder([".", "generic", "Build a generic tool", "1", "n"])
            rc = run_init(Args(force=True), input_func=feeder, plan_runner=lambda *a, **k: None)
            check(rc == 0, "run_init succeeded with --force")
            cfg = json.load(open(os.path.join(td, "llmstack_config.json"), encoding="utf-8"))
            check(cfg.get("sentinel") is None, "old content replaced")
            check(cfg["plan_file"] == os.path.join(".", ".claude", "plans", "plan.json"), "generic plan path used")
        finally:
            os.chdir(old_cwd)


def test_init_non_interactive_uses_explicit_template():
    print("[init] non-interactive flow uses explicit templates")
    with tempfile.TemporaryDirectory() as td:
        old_cwd = os.getcwd()
        os.chdir(td)
        try:
            args = Args(
                force=False,
                extra=[
                    "--non-interactive",
                    "--dev-root",
                    "workspace-js",
                    "--project-type",
                    "js",
                    "--goal",
                    "Build a JS tool",
                    "--model",
                    "dflash-qwen27b",
                    "--no-bootstrap-plan",
                ],
            )

            plan_calls = []

            def fake_plan_runner(goal, cwd):
                plan_calls.append((goal, cwd))

            rc = run_init(args, input_func=InputFeeder([]), plan_runner=fake_plan_runner)
            check(rc == 0, "run_init succeeded without prompts")

            cfg = json.load(open(os.path.join(td, "llmstack_config.json"), encoding="utf-8"))
            check(cfg["dev_root"] == "workspace-js", "dev_root came from flags")
            check(cfg["project_type"] == "js", "project type normalized to js")
            check(cfg["project_template"]["language"] == "javascript", "js template language recorded")
            check(cfg["project_template"]["starter_layout"] == ["package.json", "src/", "tests/"], "js starter layout recorded")
            check(cfg["project_goal"] == "Build a JS tool", "goal came from flags")
            check(cfg["active_model"] == "dflash-qwen27b", "model came from flags")
            check(cfg["plan_file"] == os.path.join(".", ".claude", "plans", "js_plan.json"), "js plan path used")
            check(plan_calls == [], "starter plan generation was skipped")
        finally:
            os.chdir(old_cwd)


def test_init_force_flag_via_extra_overwrites():
    print("[init] --force passed as an init flag (CLI dispatch) overwrites")
    with tempfile.TemporaryDirectory() as td:
        old_cwd = os.getcwd()
        os.chdir(td)
        try:
            with open(os.path.join(td, "llmstack_config.json"), "w", encoding="utf-8") as f:
                json.dump({"sentinel": True}, f)
            # args.force is False here: --force arrives only through extra, exactly
            # like `llmstack init --force --non-interactive ...` on the real CLI.
            args = Args(
                force=False,
                extra=["--force", "--non-interactive", "--project-type", "generic", "--no-bootstrap-plan"],
            )
            rc = run_init(args, input_func=InputFeeder([]), plan_runner=lambda *a, **k: None)
            check(rc == 0, "run_init honored --force from extra")
            cfg = json.load(open(os.path.join(td, "llmstack_config.json"), encoding="utf-8"))
            check(cfg.get("sentinel") is None, "old content replaced via extra --force")
        finally:
            os.chdir(old_cwd)


if __name__ == "__main__":
    tests = [
        test_init_writes_config_and_bootstrap_plan,
        test_init_refuses_overwrite_without_force,
        test_init_force_overwrites_existing_config,
        test_init_non_interactive_uses_explicit_template,
        test_init_force_flag_via_extra_overwrites,
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
