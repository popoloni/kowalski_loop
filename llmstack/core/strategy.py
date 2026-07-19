"""Phase 3.5 — Loop Strategy abstraction.

A `loop_strategy` block (optional, task- or plan-level) lets a task opt into
extra behaviors layered on top of the existing Kowalski retry loop:

  - `checker`: an independent verification command (maker/checker pattern).
  - `risk_policy`: a denylist / changed-file cap safety guardrail.
  - `budget`: attempt / duration / token-estimate caps.
  - `context_policy`: how much context direct-mode generation is given.
  - `run_until_done`: whether the existing smart-retry loop keeps retrying
    with feedback (default True — this is the pre-existing behavior).

Plans/tasks that do not set `loop_strategy` get a fully inert spec: every
check below is a no-op and `Supervisor.run()` behaves exactly as before
Phase 3.5. This module intentionally does NOT reach into worktrees, multi-loop
coordination, or parallel execution — those remain deferred (see
docs/plan-kowalskiLoopGeneralization.prompt.md, Phase B).
"""
import copy
import fnmatch
import subprocess

from llmstack.core.safety import run_command

VALID_CONTEXT_POLICIES = {"full", "changed_only"}

# Phase A presets, per docs/plan-kowalskiLoopGeneralization.prompt.md.
PRESETS = {
    "simple_direct": {},
    "agent_run_until_done": {
        "run_until_done": True,
    },
    "verified_maker_checker": {
        "run_until_done": True,
        # Callers must still supply a concrete checker.command; the preset
        # only documents the intent (an independent re-verification step).
    },
    "safe_repo_edit": {
        "risk_policy": {
            "denylist": [
                ".env", "*.env", "**/secrets/**", "**/*secret*",
                "**/auth/**", "**/payments/**", "**/billing/**",
                "**/migrations/**", "**/k8s-prod/**",
            ],
            "max_changed_files": 5,
        },
    },
}


def _require_dict(value, label):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _require_str_list(value, label):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
        raise ValueError(f"{label} must be a list of non-empty strings")
    return [v.strip() for v in value]


def _require_number(value, label, minimum=0):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    if value < minimum:
        raise ValueError(f"{label} must be >= {minimum}")
    return value


def normalize_loop_strategy(raw, label="loop_strategy"):
    """Validate a raw loop_strategy dict and fill in defaults.

    Never mutates `raw`. Raises ValueError with a readable message on
    malformed input. `raw=None` (or `{}`) yields the fully inert/legacy spec.
    """
    raw = _require_dict(raw, label)

    preset_name = raw.get("preset")
    preset = {}
    if preset_name is not None:
        if not isinstance(preset_name, str) or preset_name not in PRESETS:
            raise ValueError(f"{label}.preset must be one of {sorted(PRESETS)}")
        preset = copy.deepcopy(PRESETS[preset_name])

    checker = _require_dict(raw.get("checker", preset.get("checker")), f"{label}.checker")
    checker_command = checker.get("command")
    if checker_command is not None and (not isinstance(checker_command, str) or not checker_command.strip()):
        raise ValueError(f"{label}.checker.command must be a non-empty string")

    risk_policy = _require_dict(raw.get("risk_policy", preset.get("risk_policy")), f"{label}.risk_policy")
    denylist = _require_str_list(risk_policy.get("denylist"), f"{label}.risk_policy.denylist")
    max_changed_files = _require_number(
        risk_policy.get("max_changed_files"), f"{label}.risk_policy.max_changed_files", minimum=0
    )

    budget = _require_dict(raw.get("budget", preset.get("budget")), f"{label}.budget")
    max_attempts = _require_number(budget.get("max_attempts"), f"{label}.budget.max_attempts", minimum=1)
    max_duration_seconds = _require_number(
        budget.get("max_duration_seconds"), f"{label}.budget.max_duration_seconds", minimum=1
    )
    max_token_estimate = _require_number(
        budget.get("max_token_estimate"), f"{label}.budget.max_token_estimate", minimum=1
    )

    context_policy = raw.get("context_policy", preset.get("context_policy", "full"))
    if context_policy not in VALID_CONTEXT_POLICIES:
        raise ValueError(f"{label}.context_policy must be one of {sorted(VALID_CONTEXT_POLICIES)}")

    run_until_done = raw.get("run_until_done", preset.get("run_until_done", True))
    if not isinstance(run_until_done, bool):
        raise ValueError(f"{label}.run_until_done must be true or false")

    return {
        "preset": preset_name,
        "run_until_done": run_until_done,
        "checker": {"command": checker_command} if checker_command else None,
        "risk_policy": (
            {"denylist": denylist, "max_changed_files": max_changed_files}
            if (denylist or max_changed_files is not None) else None
        ),
        "budget": (
            {
                "max_attempts": max_attempts,
                "max_duration_seconds": max_duration_seconds,
                "max_token_estimate": max_token_estimate,
            }
            if (max_attempts is not None or max_duration_seconds is not None or max_token_estimate is not None)
            else None
        ),
        "context_policy": context_policy,
    }


def resolve_loop_strategy(task, plan):
    """Merge plan-level defaults with task-level overrides (shallow, per top-level
    key) and normalize. Returns the inert/legacy spec if neither the task nor the
    plan set a `loop_strategy` block."""
    plan_default = (plan or {}).get("loop_strategy")
    task_override = task.get("loop_strategy")

    if plan_default is None and task_override is None:
        return normalize_loop_strategy(None)

    if plan_default is not None and not isinstance(plan_default, dict):
        raise ValueError("plan['loop_strategy'] must be an object")
    if task_override is not None and not isinstance(task_override, dict):
        raise ValueError("task['loop_strategy'] must be an object")

    merged = {}
    merged.update(plan_default or {})
    merged.update(task_override or {})
    return normalize_loop_strategy(merged)


class LoopStrategy:
    """Wraps a normalized loop_strategy spec and applies it at well-defined
    hook points inside Supervisor.run()."""

    def __init__(self, spec):
        self.spec = spec

    def describe(self):
        parts = []
        if self.spec.get("preset"):
            parts.append(f"preset={self.spec['preset']}")
        if self.spec.get("checker"):
            parts.append("checker")
        if self.spec.get("risk_policy"):
            parts.append("risk_policy")
        if self.spec.get("budget"):
            parts.append("budget")
        if self.spec.get("context_policy") != "full":
            parts.append(f"context={self.spec['context_policy']}")
        return "+".join(parts) if parts else "legacy"

    def effective_context(self, task, git_manager):
        """Only affects direct-mode context assembly (agent mode gathers its own
        context via tool calls, so context_policy is a no-op there)."""
        context = list(task.get("context") or [])
        if self.spec.get("context_policy") != "changed_only" or git_manager is None:
            return context
        try:
            changed = git_manager.changed_files()
        except Exception:
            return context
        return [c for c in context if c in changed]

    def check_safety(self, dev_root, git_manager):
        policy = self.spec.get("risk_policy")
        if not policy or git_manager is None:
            return True, ""
        try:
            changed = sorted(git_manager.changed_files())
        except Exception:
            return True, ""
        denylist = policy.get("denylist") or []
        blocked = [f for f in changed if any(fnmatch.fnmatch(f, pat) for pat in denylist)]
        if blocked:
            return False, f"safety guardrail: denylisted files changed: {blocked}"
        max_files = policy.get("max_changed_files")
        if max_files is not None and len(changed) > max_files:
            return False, (
                f"safety guardrail: {len(changed)} files changed, "
                f"exceeds max_changed_files={max_files}"
            )
        return True, ""

    def run_checker(self, task, dev_root):
        checker = self.spec.get("checker")
        if not checker or not checker.get("command"):
            return True, ""
        command = checker["command"].format(file=task.get("file", ""), dev_root=dev_root)
        try:
            result = subprocess.run(
                command, shell=True, cwd=dev_root,
                capture_output=True, text=True, timeout=120,
            )
        except subprocess.TimeoutExpired:
            return False, f"Independent checker '{command}' timed out."
        if result.returncode == 0:
            return True, ""
        parts = []
        if result.stdout.strip():
            parts.append(f"stdout:\n{result.stdout.strip()}")
        if result.stderr.strip():
            parts.append(f"stderr:\n{result.stderr.strip()}")
        payload = "\n\n".join(parts) if parts else f"exit code {result.returncode}"
        return False, f"Independent checker rejected the change.\n{payload}"

    def budget_exceeded(self, attempts_used, elapsed_seconds, token_estimate):
        budget = self.spec.get("budget")
        if not budget:
            return False, ""
        max_attempts = budget.get("max_attempts")
        if max_attempts is not None and attempts_used >= max_attempts:
            return True, f"budget exceeded: attempts_used={attempts_used} >= max_attempts={max_attempts}"
        max_duration = budget.get("max_duration_seconds")
        if max_duration is not None and elapsed_seconds >= max_duration:
            return True, (
                f"budget exceeded: elapsed={elapsed_seconds:.1f}s "
                f">= max_duration_seconds={max_duration}"
            )
        max_tokens = budget.get("max_token_estimate")
        if max_tokens is not None and token_estimate >= max_tokens:
            return True, (
                f"budget exceeded: token_estimate={token_estimate} "
                f">= max_token_estimate={max_tokens}"
            )
        return False, ""
