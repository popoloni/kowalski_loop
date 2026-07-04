from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
CLI_FILE = ROOT / "llmstack" / "cli.py"


def _extract_bash_commands(text: str) -> list[str]:
    blocks = re.findall(r"```bash\n(.*?)\n```", text, flags=re.S)
    commands: list[str] = []

    for body in blocks:
        in_heredoc = False
        heredoc_end = None
        for raw in body.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            if in_heredoc:
                if line == heredoc_end:
                    in_heredoc = False
                continue

            if "<<'" in line:
                end = line.split("<<'", 1)[1].split("'", 1)[0]
                in_heredoc = True
                heredoc_end = end
                commands.append(line)
                continue

            commands.append(line)

    return commands


def _cli_choices() -> set[str]:
    tree = ast.parse(CLI_FILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "add_argument"):
            continue
        if not node.args:
            continue
        arg0 = node.args[0]
        if not (isinstance(arg0, ast.Constant) and arg0.value == "command"):
            continue
        for kw in node.keywords:
            if kw.arg == "choices" and isinstance(kw.value, (ast.List, ast.Tuple)):
                out = set()
                for elt in kw.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        out.add(elt.value)
                return out
    raise AssertionError("Could not extract llmstack CLI command choices from cli.py")


def test_readme_bash_commands_are_well_formed_and_resolvable():
    text = README.read_text(encoding="utf-8")
    commands = _extract_bash_commands(text)

    assert commands, "No bash commands found in README"

    cli_choices = _cli_choices()

    # Keep this in sync with run_model() accepted values in llmstack/cli.py.
    model_subcommands = {"list", "use", "recommend", "preset", "help", "-h", "--help"}

    for cmd in commands:
        if cmd.startswith("bash bin/"):
            script = cmd.split()[1]
            script_path = ROOT / script
            assert script_path.exists(), f"README references missing script: {script}"
            assert script_path.is_file(), f"README script target is not a file: {script}"

            # Syntax-only check to avoid starting long-running services.
            subprocess.run(["bash", "-n", str(script_path)], check=True, cwd=ROOT)
            continue

        if cmd.startswith("source env/bin/activate"):
            assert (ROOT / "env" / "bin" / "activate").exists(), "env/bin/activate not found"
            continue

        if cmd.startswith("env/bin/python -m llmstack.cli "):
            parts = cmd.split()
            assert len(parts) >= 4, f"Malformed llmstack CLI command: {cmd}"
            subcmd = parts[3]
            assert subcmd in cli_choices, f"Unknown llmstack CLI command in README: {subcmd}"
            if subcmd == "model" and len(parts) >= 5:
                model_sub = parts[4]
                assert model_sub in model_subcommands, (
                    f"Unknown llmstack model subcommand in README: {model_sub}"
                )
            continue

        if cmd.startswith("python -m llmstack.cli "):
            parts = cmd.split()
            assert len(parts) >= 4, f"Malformed llmstack CLI command: {cmd}"
            subcmd = parts[3]
            assert subcmd in cli_choices, f"Unknown llmstack CLI command in README: {subcmd}"
            if subcmd == "model" and len(parts) >= 5:
                model_sub = parts[4]
                assert model_sub in model_subcommands, (
                    f"Unknown llmstack model subcommand in README: {model_sub}"
                )
            continue

        if cmd.startswith("python3 -m llmstack.tools."):
            mod = cmd.split()[2]
            assert mod.startswith("llmstack.tools."), f"Unexpected tools module format: {cmd}"
            rel = mod.replace(".", "/") + ".py"
            assert (ROOT / rel).exists(), f"Missing module referenced in README: {mod}"
            continue

        if cmd.startswith("cat >") or cmd.startswith("env/bin/python - <<"):
            # Heredoc starters are validated structurally by parser; runtime effects are context-specific.
            continue

        if cmd.startswith("cd ") or cmd.startswith("mkdir ") or cmd.startswith("git init"):
            continue

        # Keep this explicit: any new command pattern in README must be reviewed.
        raise AssertionError(f"Unclassified README command pattern: {cmd}")
