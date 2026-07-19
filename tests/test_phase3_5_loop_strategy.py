"""Phase 3.5 loop-strategy generalization tests.

Run with the project venv from the repo root:

    env/bin/python tests/test_phase3_5_loop_strategy.py

Exits non-zero if any check fails. No third-party test runner required.

Covers:
  - loop_strategy schema normalization/validation (strategy.py unit tests)
  - plan/task merge semantics (resolve_loop_strategy)
  - safety guardrail (risk_policy), maker/checker, budget guard, context_policy
    hooks in isolation
  - end-to-end Supervisor.run() integration:
      * a plan with no loop_strategy behaves exactly like before Phase 3.5
        (only new side effect: a runlog line is appended)
      * an independent checker downgrades a plausible-but-wrong OK to a retry
      * a safety guardrail blocks/escalates before auto-committing
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The existing retry/rollback paths use time.sleep(2..5) as backoff; make the
# suite fast and deterministic.
time.sleep = lambda *_a, **_k: None

from llmstack.core.strategy import LoopStrategy, normalize_loop_strategy, resolve_loop_strategy
from llmstack.core.runlog import default_runlog_path, estimate_tokens
from llmstack.core.supervisor import Supervisor


def check(cond, msg):
    if not cond:
        raise AssertionError(f"FAIL: {msg}")
    print(f"  ok: {msg}")


# ---------------------------------------------------------------------------
# strategy.py unit tests
# ---------------------------------------------------------------------------
def test_normalize_defaults_are_inert():
    print("[strategy] normalize_loop_strategy(None) is a fully inert/legacy spec")
    spec = normalize_loop_strategy(None)
    check(spec["run_until_done"] is True, "run_until_done defaults True")
    check(spec["checker"] is None, "checker defaults None")
    check(spec["risk_policy"] is None, "risk_policy defaults None")
    check(spec["budget"] is None, "budget defaults None")
    check(spec["context_policy"] == "full", "context_policy defaults full")


def test_normalize_preset_expansion():
    print("[strategy] preset expansion fills risk_policy from safe_repo_edit")
    spec = normalize_loop_strategy({"preset": "safe_repo_edit"})
    check(spec["risk_policy"] is not None, "preset populated risk_policy")
    check(".env" in spec["risk_policy"]["denylist"], "preset denylist includes .env")
    check(spec["risk_policy"]["max_changed_files"] == 5, "preset max_changed_files == 5")


def test_normalize_invalid_inputs_fail_readably():
    print("[strategy] malformed loop_strategy fields raise readable ValueErrors")
    for bad, needle in [
        ({"context_policy": "sometimes"}, "context_policy"),
        ({"budget": {"max_attempts": 0}}, "max_attempts"),
        ({"checker": {"command": ""}}, "command"),
        ({"preset": "not-a-preset"}, "preset"),
        ({"run_until_done": "yes"}, "run_until_done"),
    ]:
        try:
            normalize_loop_strategy(bad)
        except ValueError as exc:
            check(needle in str(exc), f"error for {bad} mentions '{needle}': {exc}")
        else:
            raise AssertionError(f"FAIL: {bad} should have raised ValueError")


def test_resolve_merges_plan_and_task_shallow():
    print("[strategy] resolve_loop_strategy merges plan defaults with task overrides")
    plan = {"loop_strategy": {"budget": {"max_attempts": 4}, "context_policy": "changed_only"}}
    task = {"loop_strategy": {"checker": {"command": "true"}}}
    spec = resolve_loop_strategy(task, plan)
    check(spec["budget"]["max_attempts"] == 4, "plan-level budget preserved")
    check(spec["context_policy"] == "changed_only", "plan-level context_policy preserved")
    check(spec["checker"]["command"] == "true", "task-level checker applied")


def test_resolve_task_overrides_same_key():
    print("[strategy] task-level key wins over plan-level for the same key")
    plan = {"loop_strategy": {"context_policy": "changed_only"}}
    task = {"loop_strategy": {"context_policy": "full"}}
    spec = resolve_loop_strategy(task, plan)
    check(spec["context_policy"] == "full", "task override wins")


def test_resolve_no_strategy_anywhere_is_inert():
    print("[strategy] no loop_strategy anywhere -> inert legacy spec")
    spec = resolve_loop_strategy({}, {"tasks": []})
    check(LoopStrategy(spec).describe() == "legacy", "describe() reports legacy")


def test_check_safety_denylist_blocks():
    print("[strategy] risk_policy denylist blocks matching changed files")

    class GitStub:
        def changed_files(self):
            return {".env", "app.py"}

    strategy = LoopStrategy(normalize_loop_strategy({"risk_policy": {"denylist": [".env"]}}))
    ok, reason = strategy.check_safety("/tmp", GitStub())
    check(not ok, "denylisted file blocks safety check")
    check(".env" in reason, "reason mentions blocked file")


def test_check_safety_max_changed_files():
    print("[strategy] risk_policy max_changed_files caps blast radius")

    class GitStub:
        def changed_files(self):
            return {"a.py", "b.py", "c.py"}

    strategy = LoopStrategy(normalize_loop_strategy({"risk_policy": {"max_changed_files": 2}}))
    ok, reason = strategy.check_safety("/tmp", GitStub())
    check(not ok, "too many changed files blocks safety check")
    check("max_changed_files" in reason, "reason mentions cap")


def test_check_safety_noop_when_unconfigured():
    print("[strategy] check_safety is a no-op without risk_policy")
    strategy = LoopStrategy(normalize_loop_strategy(None))
    ok, reason = strategy.check_safety("/tmp", None)
    check(ok and reason == "", "legacy spec never blocks")


def test_run_checker_pass_and_fail():
    print("[strategy] independent checker command runs and reports failure feedback")
    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, "app.py"), "w").write("bad\n")
        strategy = LoopStrategy(normalize_loop_strategy({"checker": {"command": "grep -q GOOD {file}"}}))
        ok, reason = strategy.run_checker({"file": "app.py"}, td)
        check(not ok, "checker rejects mismatching content")
        check(reason, "failure feedback is non-empty")

        open(os.path.join(td, "app.py"), "w").write("GOOD\n")
        ok2, reason2 = strategy.run_checker({"file": "app.py"}, td)
        check(ok2 and reason2 == "", "checker passes once content matches")


def test_budget_exceeded_dimensions():
    print("[strategy] budget guard trips on attempts/duration/tokens independently")
    attempts_only = LoopStrategy(normalize_loop_strategy({"budget": {"max_attempts": 2}}))
    hit, reason = attempts_only.budget_exceeded(attempts_used=2, elapsed_seconds=0, token_estimate=0)
    check(hit and "max_attempts" in reason, "attempts budget trips")

    tokens_only = LoopStrategy(normalize_loop_strategy({"budget": {"max_token_estimate": 100}}))
    hit2, reason2 = tokens_only.budget_exceeded(attempts_used=0, elapsed_seconds=0, token_estimate=150)
    check(hit2 and "max_token_estimate" in reason2, "token budget trips")

    unconfigured = LoopStrategy(normalize_loop_strategy(None))
    hit3, _ = unconfigured.budget_exceeded(attempts_used=999, elapsed_seconds=999999, token_estimate=999999)
    check(not hit3, "no budget configured -> never trips")


def test_effective_context_changed_only():
    print("[strategy] context_policy=changed_only trims context to changed files")

    class GitStub:
        def changed_files(self):
            return {"a.py"}

    strategy = LoopStrategy(normalize_loop_strategy({"context_policy": "changed_only"}))
    ctx = strategy.effective_context({"context": ["a.py", "b.py"]}, GitStub())
    check(ctx == ["a.py"], f"context trimmed to changed files only, got {ctx}")


def test_estimate_tokens_and_runlog_path():
    print("[runlog] estimate_tokens is a coarse char-count proxy; default path resolves under dev_root")
    check(estimate_tokens("abcd" * 10) == 10, "estimate_tokens ~ len/4")
    check(default_runlog_path("/tmp/proj").endswith("logs/kowalski_runlog.jsonl"), "default runlog path")
    check(default_runlog_path("/tmp/proj", {"runlog_file": "custom.jsonl"}) == "/tmp/proj/custom.jsonl",
          "config override respected (relative)")


# ---------------------------------------------------------------------------
# Supervisor integration tests
# ---------------------------------------------------------------------------
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


def _init_git_repo(td):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=td, check=True)
    subprocess.run(["git", "config", "user.email", "kowalski-test@example.com"], cwd=td, check=True)
    subprocess.run(["git", "config", "user.name", "Kowalski Test"], cwd=td, check=True)


def _cfg(td, plan_path, **overrides):
    base = {
        "dev_root": td,
        "plan_file": plan_path,
        "loop_mode": "plan",
        "require_change": False,
        "wiring_check": False,
        "review_enabled": False,
        "verification_plugins": {},
        "max_retries": 3,
        "max_resumes": 0,
        "task_timeout": 1,
        "max_turns": 1,
        "debug_log": None,
        "debug_max_chars": 0,
        "permission_mode": "acceptEdits",
        "size_threshold_bytes": 12000,
        "headroom_chat_url": "http://127.0.0.1:8789/v1/chat/completions",
    }
    base.update(overrides)
    return base


class AlwaysOkDirectExecutor:
    """Writes a fixed 'ok' payload and reports OK on every attempt."""

    def choose_executor(self, task):
        return "direct"

    def syntax_ok(self, task):
        return True

    def run_direct_task(self, task, attempt=1):
        path = os.path.join(self._dev_root, task["file"])
        os.makedirs(os.path.dirname(path) or self._dev_root, exist_ok=True)
        open(path, "w").write("ok\n")
        return "OK"

    def run_direct_context_fallback(self, task, attempt=1):
        return "OK"

    def execute_task(self, task, attempt=1, resuming=False):
        return "OK"


class ImprovingDirectExecutor(AlwaysOkDirectExecutor):
    """Writes 'bad' on the first attempt (plausible per its own self-report, i.e.
    still returns OK) and 'GOOD' from the second attempt on, to exercise the
    maker/checker downgrade path."""

    def run_direct_task(self, task, attempt=1):
        path = os.path.join(self._dev_root, task["file"])
        content = "bad\n" if attempt == 1 else "GOOD\n"
        open(path, "w").write(content)
        return "OK"


class DenylistedFileExecutor(AlwaysOkDirectExecutor):
    def run_direct_task(self, task, attempt=1):
        path = os.path.join(self._dev_root, task["file"])
        open(path, "w").write("SECRET=1\n")
        return "OK"


def test_supervisor_legacy_plan_unaffected_plus_runlog():
    print("[supervisor] plan without loop_strategy behaves as before + gains a runlog line")
    with tempfile.TemporaryDirectory() as td:
        _init_git_repo(td)
        plan_path = os.path.join(td, "plan.json")
        json.dump({"tasks": [{"id": 1, "status": "pending", "file": "a.py"}]}, open(plan_path, "w"))
        cfg = _cfg(td, plan_path)

        supervisor = Supervisor(cfg, td, ServicesStub())
        stub = AlwaysOkDirectExecutor()
        stub._dev_root = td
        supervisor.executor = stub
        supervisor.run()

        persisted = json.load(open(plan_path))
        check(persisted["tasks"][0]["status"] == "completed", "legacy task completes exactly as before")

        runlog_path = os.path.join(td, "logs", "kowalski_runlog.jsonl")
        check(os.path.exists(runlog_path), "runlog file created as new observability side effect")
        entry = json.loads(open(runlog_path).read().strip().splitlines()[-1])
        check(entry["strategy"] == "legacy", "runlog records legacy strategy")
        check(entry["outcome"] == "OK", "runlog records OK outcome")
        check(entry["escalated"] is False, "runlog records no escalation")


def test_supervisor_checker_downgrades_then_succeeds():
    print("[supervisor] independent checker downgrades a plausible-but-wrong OK, then passes")
    with tempfile.TemporaryDirectory() as td:
        _init_git_repo(td)
        plan_path = os.path.join(td, "plan.json")
        json.dump({"tasks": [{
            "id": 1, "status": "pending", "file": "app.py",
            "loop_strategy": {"checker": {"command": "grep -q GOOD {file}"}},
        }]}, open(plan_path, "w"))
        cfg = _cfg(td, plan_path)

        supervisor = Supervisor(cfg, td, ServicesStub())
        stub = ImprovingDirectExecutor()
        stub._dev_root = td
        supervisor.executor = stub
        supervisor.run()

        persisted = json.load(open(plan_path))
        check(persisted["tasks"][0]["status"] == "completed", "task eventually completes once checker passes")
        check(open(os.path.join(td, "app.py")).read() == "GOOD\n", "final committed content is the good one")

        runlog_path = os.path.join(td, "logs", "kowalski_runlog.jsonl")
        entry = json.loads(open(runlog_path).read().strip().splitlines()[-1])
        check(entry["attempts"] == 2, f"took 2 attempts, got {entry['attempts']}")
        check("checker" in entry["strategy"], "runlog strategy mentions checker")


def test_supervisor_safety_guardrail_blocks_before_commit():
    print("[supervisor] risk_policy denylist blocks/escalates before auto-commit")
    with tempfile.TemporaryDirectory() as td:
        _init_git_repo(td)
        plan_path = os.path.join(td, "plan.json")
        json.dump({"tasks": [{
            "id": 1, "status": "pending", "file": ".env",
            "loop_strategy": {"risk_policy": {"denylist": [".env"]}},
        }]}, open(plan_path, "w"))
        cfg = _cfg(td, plan_path)

        services = ServicesStub()
        supervisor = Supervisor(cfg, td, services)
        stub = DenylistedFileExecutor()
        stub._dev_root = td
        supervisor.executor = stub
        supervisor.run()

        persisted = json.load(open(plan_path))
        check(persisted["tasks"][0]["status"] == "pending", "denylisted task never marked completed")
        check(not os.path.exists(os.path.join(td, ".env")), "denylisted file rolled back, not committed")
        check(services.stop_called, "services.stop() called on escalation halt")

        runlog_path = os.path.join(td, "logs", "kowalski_runlog.jsonl")
        entry = json.loads(open(runlog_path).read().strip().splitlines()[-1])
        check(entry["escalated"] is True, "runlog marks the run as escalated")
        check(".env" in entry["escalation_reason"], "runlog escalation_reason mentions the denylisted file")
        check(entry["outcome"] == "INCOMPLETE", "runlog outcome is INCOMPLETE")


if __name__ == "__main__":
    tests = [
        test_normalize_defaults_are_inert,
        test_normalize_preset_expansion,
        test_normalize_invalid_inputs_fail_readably,
        test_resolve_merges_plan_and_task_shallow,
        test_resolve_task_overrides_same_key,
        test_resolve_no_strategy_anywhere_is_inert,
        test_check_safety_denylist_blocks,
        test_check_safety_max_changed_files,
        test_check_safety_noop_when_unconfigured,
        test_run_checker_pass_and_fail,
        test_budget_exceeded_dimensions,
        test_effective_context_changed_only,
        test_estimate_tokens_and_runlog_path,
        test_supervisor_legacy_plan_unaffected_plus_runlog,
        test_supervisor_checker_downgrades_then_succeeds,
        test_supervisor_safety_guardrail_blocks_before_commit,
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
