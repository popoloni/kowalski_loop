from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_ALLOWED_PROGRAMS = {
    "python", "python3", "node", "npm", "npx", "pytest", "ruff", "git",
    "bash", "sh", "make", "cmake", "cargo", "go", "java", "javac",
}


def confined_path(root: str | os.PathLike[str], value: str | os.PathLike[str], *, must_exist: bool = False) -> Path:
    base = Path(root).resolve()
    raw = Path(value)
    candidate = raw.resolve() if raw.is_absolute() else (base / raw).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"Path escapes dev_root: {value!s}") from exc
    if must_exist and not candidate.exists():
        raise FileNotFoundError(candidate)
    return candidate


def normalize_command(command: Any) -> tuple[list[str], float | None]:
    timeout = None
    if isinstance(command, dict):
        program = command.get("program")
        args = command.get("args", [])
        timeout = command.get("timeout_seconds")
        if not isinstance(program, str) or not program.strip():
            raise ValueError("command.program must be a non-empty string")
        if not isinstance(args, list) or any(not isinstance(x, str) for x in args):
            raise ValueError("command.args must be a list of strings")
        argv = [program, *args]
    elif isinstance(command, list) and command and all(isinstance(x, str) for x in command):
        argv = list(command)
    elif isinstance(command, str) and command.strip():
        # Compatibility mode: parse shell syntax but never invoke a shell. Reject operators.
        argv = shlex.split(command)
        forbidden = {"|", "||", "&&", ";", ">", ">>", "<", "2>", "&"}
        if any(token in forbidden for token in argv):
            raise ValueError("Shell operators are not allowed; use a structured command")
    else:
        raise ValueError("command must be a structured object, argv list, or non-empty string")
    return argv, float(timeout) if timeout is not None else None


def run_command(command: Any, *, cwd: str, timeout: float = 120, allowed_programs=None,
                max_output_bytes: int = 1_000_000) -> subprocess.CompletedProcess[str]:
    argv, embedded_timeout = normalize_command(command)
    allowed = set(allowed_programs or DEFAULT_ALLOWED_PROGRAMS)
    program_name = Path(argv[0]).name
    if program_name not in allowed:
        raise ValueError(f"Program is not allowed by command policy: {program_name}")
    result = subprocess.run(
        argv, cwd=cwd, shell=False, capture_output=True, text=True,
        timeout=embedded_timeout or timeout, check=False,
        env={k: v for k, v in os.environ.items() if k not in {
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "AZURE_OPENAI_API_KEY"
        }},
    )
    if len(result.stdout.encode(errors="ignore")) > max_output_bytes:
        result.stdout = result.stdout[:max_output_bytes] + "\n...[truncated]"
    if len(result.stderr.encode(errors="ignore")) > max_output_bytes:
        result.stderr = result.stderr[:max_output_bytes] + "\n...[truncated]"
    return result
