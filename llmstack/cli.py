import argparse
import json
import os
import signal
import subprocess
import sys

from llmstack.config import load_config
from llmstack.core.supervisor import Supervisor
from llmstack.models.registry import active_model_name, load_active_backend, load_model_registry
from llmstack.services.ccr_service import CCRService
from llmstack.services.inference_probe import served_model_id
from llmstack.services.stack import ServiceStack

CONFIG_PATH = "llmstack_config.json"
INIT_PROJECT_TEMPLATES = {
    "python": {
        "language": "python",
        "description": "Python project template with pyproject.toml, src/, and tests/",
        "starter_layout": ["pyproject.toml", "src/", "tests/"],
        "plan_name": "python_plan.json",
        "goal_default": "Build a Python project",
    },
    "js": {
        "language": "javascript",
        "description": "JavaScript project template with package.json, src/, and tests/",
        "starter_layout": ["package.json", "src/", "tests/"],
        "plan_name": "js_plan.json",
        "goal_default": "Build a JavaScript project",
    },
    "generic": {
        "language": "generic",
        "description": "Language-agnostic project template for any codebase",
        "starter_layout": ["README.md", "tasks.md"],
        "plan_name": "plan.json",
        "goal_default": "Build a generic project",
    },
}


def _parse_init_options(extra):
    parser = argparse.ArgumentParser(prog="llmstack init")
    parser.add_argument("--dev-root")
    parser.add_argument("--project-type")
    parser.add_argument("--goal")
    parser.add_argument("--model")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--bootstrap-plan", dest="bootstrap_plan", action="store_true")
    parser.add_argument("--no-bootstrap-plan", dest="bootstrap_plan", action="store_false")
    parser.set_defaults(bootstrap_plan=None)
    return parser.parse_args(extra or [])


def _slugify(text, fallback="project"):
    slug = []
    prev_dash = False
    for ch in str(text or "").strip().lower():
        if ch.isalnum():
            slug.append(ch)
            prev_dash = False
        elif not prev_dash:
            slug.append("-")
            prev_dash = True
    result = "".join(slug).strip("-")
    return result or fallback


def _prompt_input(prompt, default="", input_func=input):
    suffix = f" [{default}]" if default else ""
    value = input_func(f"{prompt}{suffix}: ").strip()
    return value or default


def _prompt_yes_no(prompt, default=True, input_func=input):
    suffix = " [Y/n]" if default else " [y/N]"
    value = input_func(f"{prompt}{suffix}: ").strip().lower()
    if not value:
        return default
    return value in ("y", "yes", "true", "1")


def _select_init_model(registry, input_func=input):
    items = list(registry.items())
    default_name = next((name for name, cfg in items if cfg.get("best_for") == "agentic"), items[0][0])
    print("📚 [llmstack init] Available models:")
    for idx, (name, cfg) in enumerate(items, 1):
        marker = " (recommended)" if name == default_name else ""
        print(f"  {idx}. {name} [{cfg.get('type', 'unknown')}] -> {cfg.get('target', '(missing target)')}{marker}")

    while True:
        raw = input_func(f"Choose model/backend [default: {default_name}]: ").strip()
        if not raw:
            return default_name
        if raw in registry:
            return raw
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(items):
                return items[idx - 1][0]
        print("❌ [llmstack init] Invalid selection. Enter a model name or number from the list above.")


def _default_init_model(registry):
    items = list(registry.items())
    return next((name for name, cfg in items if cfg.get("best_for") == "agentic"), items[0][0])


def _normalize_init_project_type(project_type):
    slug = _slugify(project_type, fallback="generic")
    aliases = {
        "javascript": "js",
        "typescript": "js",
        "node": "js",
        "nodejs": "js",
        "py": "python",
    }
    return aliases.get(slug, slug) if slug in INIT_PROJECT_TEMPLATES or slug in aliases else "generic"


def _project_template(project_type):
    template_key = _normalize_init_project_type(project_type)
    template = INIT_PROJECT_TEMPLATES.get(template_key, INIT_PROJECT_TEMPLATES["generic"])
    return template_key, template


def _build_init_config(dev_root, project_type, goal, active_model):
    project_slug, template = _project_template(project_type)
    plan_name = template["plan_name"]
    plan_file = os.path.join(".", ".claude", "plans", plan_name)
    return {
        "dev_root": dev_root,
        "project_type": project_slug,
        "project_template": {
            "name": project_slug,
            "language": template["language"],
            "description": template["description"],
            "starter_layout": template["starter_layout"],
            "plan_name": plan_name,
        },
        "project_goal": goal,
        "plan_file": plan_file,
        "active_model": active_model,
        "loop_mode": "plan",
        "permission_mode": "acceptEdits",
        "thinking_mode": "off",
        "verification_plugins": {},
    }, plan_file


def _write_init_config(config_path, init_config):
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(init_config, f, indent=2)
        f.write("\n")


def _default_plan_runner(goal, cwd):
    subprocess.run([sys.executable, "-m", "llmstack.tools.build_plan", goal], cwd=cwd, check=True)


def run_init(args, input_func=input, plan_runner=None, config_path=CONFIG_PATH):
    cwd = os.getcwd()
    config_path = os.path.abspath(config_path)
    init_args = _parse_init_options(getattr(args, "extra", []))
    force = bool(getattr(args, "force", False) or init_args.force)
    if os.path.exists(config_path) and not force:
        print(f"❌ [llmstack init] '{config_path}' already exists. Use --force to overwrite it.")
        return 1

    print("🧩 [llmstack init] Minimal workspace bootstrap")

    registry = load_model_registry({})
    if init_args.non_interactive:
        dev_root = init_args.dev_root or "."
        project_type = init_args.project_type or "generic"
        _, template = _project_template(project_type)
        goal = init_args.goal or template["goal_default"]
        active_model = init_args.model or _default_init_model(registry)
        bootstrap_plan = True if init_args.bootstrap_plan is None else init_args.bootstrap_plan
    else:
        dev_root = init_args.dev_root or _prompt_input("Dev root", default=".", input_func=input_func)
        project_type = init_args.project_type or _prompt_input("Project type", default="generic", input_func=input_func)
        _, template = _project_template(project_type)
        goal_default = init_args.goal or template["goal_default"]
        goal = _prompt_input("Goal", default=goal_default, input_func=input_func)
        if init_args.model:
            active_model = init_args.model
            if active_model not in registry:
                print(f"❌ [llmstack init] Unknown model '{active_model}'. Run 'llmstack model list'.")
                return 1
        else:
            active_model = _select_init_model(registry, input_func=input_func)
        bootstrap_plan = (
            init_args.bootstrap_plan
            if init_args.bootstrap_plan is not None
            else _prompt_yes_no("Generate a starter plan now", default=True, input_func=input_func)
        )

    if active_model not in registry:
        print(f"❌ [llmstack init] Unknown model '{active_model}'. Run 'llmstack model list'.")
        return 1

    init_config, plan_file = _build_init_config(dev_root, project_type, goal, active_model)

    os.makedirs(dev_root, exist_ok=True)
    os.makedirs(os.path.join(cwd, ".claude", "plans"), exist_ok=True)
    os.makedirs(os.path.dirname(config_path) or ".", exist_ok=True)
    _write_init_config(config_path, init_config)
    print(f"✅ [llmstack init] Wrote {config_path}")
    print(f"  dev_root={dev_root}")
    print(f"  project_type={project_type}")
    print(f"  project_language={init_config['project_template']['language']}")
    print(f"  active_model={active_model}")
    print(f"  plan_file={plan_file}")

    if bootstrap_plan:
        runner = plan_runner or _default_plan_runner
        print("🧠 [llmstack init] Generating starter plan...")
        try:
            runner(goal, cwd)
        except subprocess.CalledProcessError as exc:
            print(f"⚠️  [llmstack init] Plan generation failed: {exc}")
            return 1
        print("✅ [llmstack init] Starter plan generated.")
    else:
        print("ℹ️  [llmstack init] Skipped starter plan generation.")

    return 0


def _load_raw_user_config(config_path=CONFIG_PATH):
    try:
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_raw_user_config(raw_cfg, config_path=CONFIG_PATH):
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(raw_cfg, f, indent=2)


def _watchdog_pid_file(config):
    return os.path.join(config.get("log_dir", "logs"), "inference_watchdog.pid")


def _pid_cmdline(pid):
    try:
        return subprocess.check_output(["ps", "-ww", "-p", str(pid), "-o", "command="], text=True).strip()
    except Exception:
        return ""


def _is_watchdog_pid_active(pid):
    cmdline = _pid_cmdline(pid)
    return "-m llmstack.cli serve --watchdog" in cmdline


def _active_watchdog_pid(config):
    pid_file = _watchdog_pid_file(config)
    try:
        with open(pid_file, encoding="utf-8") as f:
            pid = int((f.read() or "").strip())
    except Exception:
        return None

    if _is_watchdog_pid_active(pid):
        return pid

    try:
        os.remove(pid_file)
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return None


def _write_watchdog_pid(config):
    pid_file = _watchdog_pid_file(config)
    os.makedirs(os.path.dirname(pid_file), exist_ok=True)
    with open(pid_file, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
        f.write("\n")


def _clear_watchdog_pid(config):
    pid_file = _watchdog_pid_file(config)
    try:
        if os.path.exists(pid_file):
            with open(pid_file, encoding="utf-8") as f:
                owner_pid = int((f.read() or "").strip())
            if owner_pid == os.getpid():
                os.remove(pid_file)
    except Exception:
        pass


def _sync_ccr_for_active_model(config, restart=False):
    active_model, backend, registry = load_active_backend(config)
    timeout_ms = int(config["task_timeout"] * 1000)
    ccr = CCRService()
    ccr.sync_provider(registry=registry, active_model=active_model, timeout_ms=timeout_ms, backend=backend)
    if restart:
        ccr.restart()


def _restart_inference_server_if_running(config):
    """Swap the running inference server (DFlash/TurboQuant) to the active backend.

    No-op if nothing is currently serving on :8787 — the next `llmstack run`/`serve`
    will start the correct backend. If a server is up with a different model, it is
    stopped and the active backend is started in its place.
    """
    stack = ServiceStack(config)
    served = served_model_id(expected_target=stack.backend.model_target())
    expected = stack.backend.model_target()
    if served is None:
        print("ℹ️  [llmstack] No inference server on :8787; skipping server restart "
              "(it will start with the active backend on next 'llmstack run').")
        return
    if served == expected:
        print(f"✅ [llmstack] Inference server already serving '{expected}'.")
        return
    print(f"♻️  [llmstack] Swapping inference server: '{served}' -> '{expected}' (loading into RAM)...")
    stack.dflash._stop = False
    stack.dflash.ensure_running()


def run_dflash(config, args):
    extra = list(args.extra or [])
    watchdog = False
    filtered = []
    for token in extra:
        if token == "--watchdog":
            watchdog = True
        else:
            filtered.append(token)

    model_name = filtered[0] if filtered and not filtered[0].startswith("-") else None
    if model_name:
        registry = load_model_registry(config)
        if model_name not in registry:
            print(f"❌ [llmstack] Unknown model '{model_name}'. Run 'llmstack model list'.")
            return 1
        raw_cfg = _load_raw_user_config()
        raw_cfg["active_model"] = model_name
        if "models" not in raw_cfg:
            raw_cfg["models"] = registry
        _save_raw_user_config(raw_cfg)
        config["active_model"] = model_name
        print(f"🔧 [llmstack] active_model -> {model_name}")
        _sync_ccr_for_active_model(config, restart=True)
    if watchdog:
        stack = ServiceStack(config)
        service = stack.dflash

        def _handle_watchdog_signal(*_):
            _clear_watchdog_pid(config)
            service._stop = True
            raise SystemExit(0)

        try:
            signal.signal(signal.SIGINT, _handle_watchdog_signal)
            signal.signal(signal.SIGTERM, _handle_watchdog_signal)
        except Exception:
            pass

        service.ensure_running()

        existing_pid = _active_watchdog_pid(config)
        if existing_pid and existing_pid != os.getpid():
            print(f"ℹ️  [llmstack] Watchdog already active (PID {existing_pid}); skipping duplicate.")
            return 0

        _write_watchdog_pid(config)

        poll_seconds = float(config.get("dflash_watchdog_poll_seconds", 5))
        fail_threshold = int(config.get("dflash_watchdog_fail_threshold", 3))
        try:
            service.watchdog_loop(poll_seconds=poll_seconds, fail_threshold=fail_threshold)
        finally:
            _clear_watchdog_pid(config)
    else:
        service = ServiceStack(config).dflash
        service.ensure_running()

    return 0


def run_proxy(config, args):
    service = ServiceStack(config).headroom
    service.ensure_running()


def run_interactive(config, args):
    _sync_ccr_for_active_model(config, restart=False)
    ccr = CCRService()
    active_model, active_backend, _ = load_active_backend(config)
    active_target = active_backend.model_target()
    timeout_ms = int(config["task_timeout"] * 1000)
    ccr.patch_timeout(timeout_ms)
    ccr.pretrust(config["dev_root"])

    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.update({
        "API_TIMEOUT_MS": str(timeout_ms),
        "CLAUDE_STREAM_IDLE_TIMEOUT_MS": str(timeout_ms),
        "CLAUDE_ENABLE_BYTE_WATCHDOG": "0",
        "CLAUDE_ENABLE_STREAM_WATCHDOG": "0",
        "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING": "1",
        "CLAUDE_CODE_DISABLE_THINKING": "1",
    })

    permission_mode = config.get("interactive_permission_mode", "acceptEdits")
    max_turns = config.get("max_turns", 100)
    dev_root = config.get("dev_root", ".")

    print("🚀 [llmstack] Starting interactive Claude Code...")
    print(f"  dev_root={dev_root}")
    print(f"  permission_mode={permission_mode}")
    print(f"  max_turns={max_turns}")
    print(f"  active_model={active_model}")
    print(f"  active_target={active_target}")

    if not os.path.isdir(dev_root):
        raise FileNotFoundError(f"dev_root '{dev_root}' not found")

    system_prompt = (
        "You are a precise, autonomous coding assistant. Rules:\n"
        "1. Answer concisely — no unnecessary narration.\n"
        "2. One tool call per response (tools: Read, Write, Edit, WebFetch).\n"
        "3. For file creation, write directly; read only what is needed.\n"
        "4. Preserve ALL unrelated code when editing.\n"
        "5. Complete the task atomically, then stop.\n"
        "6. Never mix prose and tool calls in the same message."
    )

    cmd = [
        "ccr", "code",
        "--permission-mode", permission_mode,
        "--append-system-prompt", system_prompt,
        "--max-turns", str(max_turns),
    ]

    # Claude sessions can persist a model selection; force active target unless
    # caller explicitly provides --model.
    extra = args.extra or []
    has_model_override = any(t == "--model" or t.startswith("--model=") for t in extra)
    if not has_model_override:
        cmd.extend(["--model", active_target])
    cmd.extend(extra)

    subprocess.run(cmd, cwd=dev_root, env=env, check=True)


def run_dashboard(config, args):
    subprocess.run([sys.executable, "-m", "llmstack.tools.dflash_dashboard"] + (args.extra or []), check=True)


def _detected_ram_gb():
    try:
        raw = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
        return int(raw) / (1024 ** 3)
    except Exception:
        return 0.0


def _recommend_model(registry, use_case, ram_gb):
    candidates = []
    for name, cfg in registry.items():
        required = float(cfg.get("ram_required_gb", 0) or 0)
        fits = (ram_gb <= 0) or (required <= ram_gb)
        candidates.append((name, cfg, required, fits))

    fitting = [c for c in candidates if c[3]]
    pool = fitting if fitting else candidates

    if use_case == "agentic":
        def key(item):
            name, cfg, required, _ = item
            best_for = str(cfg.get("best_for", ""))
            model_type = str(cfg.get("type", ""))
            return (
                0 if "agentic" in best_for else 1,
                0 if model_type == "turboquant" else 1,
                required,
                name,
            )
    else:
        def key(item):
            name, cfg, required, _ = item
            best_for = str(cfg.get("best_for", ""))
            model_type = str(cfg.get("type", ""))
            return (
                0 if model_type == "dflash" else 1,
                0 if "decode" in best_for or "quality" in best_for else 1,
                required,
                name,
            )

    chosen = sorted(pool, key=key)[0]
    return chosen[0], chosen[1], bool(fitting)


def run_model(config, args):
    extra = args.extra or []
    preset_values = {"performance", "balanced", "stable", "safest"}

    if not extra or extra[0] in ("help", "-h", "--help"):
        print(
            "Usage: llmstack model list | llmstack model use <name> | "
            "llmstack model recommend --use agentic|decode [--apply] | "
            "llmstack model preset <performance|balanced|stable|safest> "
            "[--restart] [--keep-backend-overrides]"
        )
        return 0

    registry = load_model_registry(config)
    active = active_model_name(config, registry)

    sub = extra[0]
    if sub == "list":
        print("📚 [llmstack] Available models:")
        for name, model_cfg in registry.items():
            marker = "(active)" if name == active else ""
            model_type = model_cfg.get("type", "unknown")
            target = model_cfg.get("target", "(missing target)")
            desc = model_cfg.get("description", "")
            if desc:
                print(f"  {name} {marker} [{model_type}] -> {target} :: {desc}")
            else:
                print(f"  {name} {marker} [{model_type}] -> {target}")
        return 0

    if sub == "use":
        if len(extra) < 2:
            print("❌ [llmstack] Missing model name. Usage: llmstack model use <name>")
            return 1
        target_name = extra[1]
        if target_name not in registry:
            print(f"❌ [llmstack] Unknown model '{target_name}'. Run 'llmstack model list'.")
            return 1

        raw_cfg = _load_raw_user_config()
        raw_cfg["active_model"] = target_name
        if "models" not in raw_cfg:
            raw_cfg["models"] = registry
        _save_raw_user_config(raw_cfg)

        config["active_model"] = target_name
        print(f"🔧 [llmstack] active_model -> {target_name}")
        _sync_ccr_for_active_model(config, restart=True)
        _restart_inference_server_if_running(config)
        return 0

    if sub == "recommend":
        use_case = None
        apply_choice = False
        i = 1
        while i < len(extra):
            token = extra[i]
            if token == "--use" and (i + 1) < len(extra):
                use_case = extra[i + 1].strip().lower()
                i += 2
                continue
            if token == "--apply":
                apply_choice = True
                i += 1
                continue
            print(f"❌ [llmstack] Unknown recommend option '{token}'.")
            return 1

        if use_case not in ("agentic", "decode"):
            print("❌ [llmstack] Usage: llmstack model recommend --use agentic|decode [--apply]")
            return 1

        ram_gb = _detected_ram_gb()
        recommended_name, recommended_cfg, had_fit = _recommend_model(registry, use_case, ram_gb)

        print(f"🧠 [llmstack] Recommendation for use='{use_case}' with RAM={ram_gb:.1f}GB")
        print(f"  -> {recommended_name} [{recommended_cfg.get('type')}] {recommended_cfg.get('target')}")
        if not had_fit:
            print("⚠️  No model fits detected RAM; selected best fallback candidate.")

        if apply_choice:
            raw_cfg = _load_raw_user_config()
            raw_cfg["active_model"] = recommended_name
            if "models" not in raw_cfg:
                raw_cfg["models"] = registry
            _save_raw_user_config(raw_cfg)
            config["active_model"] = recommended_name
            print(f"🔧 [llmstack] active_model -> {recommended_name}")
            _sync_ccr_for_active_model(config, restart=True)
            _restart_inference_server_if_running(config)
        else:
            print("ℹ️  Add --apply to persist active_model and sync+restart CCR.")
        return 0

    if sub == "preset":
        if len(extra) < 2:
            print("❌ [llmstack] Missing preset name.")
            print("   Usage: llmstack model preset <performance|balanced|stable|safest> "
                  "[--restart] [--keep-backend-overrides]")
            return 1

        preset_name = str(extra[1] or "").strip().lower()
        if preset_name not in preset_values:
            print(f"❌ [llmstack] Invalid preset '{preset_name}'.")
            print("   Allowed values: performance, balanced, stable, safest")
            return 1

        restart = "--restart" in extra[2:]
        keep_backend_overrides = "--keep-backend-overrides" in extra[2:]
        unknown_flags = [t for t in extra[2:] if t not in ("--restart", "--keep-backend-overrides")]
        if unknown_flags:
            print(f"❌ [llmstack] Unknown preset option(s): {' '.join(unknown_flags)}")
            return 1

        raw_cfg = _load_raw_user_config()
        raw_cfg["backend_stability_profile"] = preset_name
        if "backend_stability_overrides" not in raw_cfg:
            raw_cfg["backend_stability_overrides"] = {}

        # Keep one-knob behavior by default: clear backend-specific profile locks.
        if not keep_backend_overrides:
            raw_cfg["dflash_stability_profile"] = None
            raw_cfg["mlx_stability_profile"] = None
            raw_cfg["turboquant_stability_profile"] = None

        _save_raw_user_config(raw_cfg)

        config["backend_stability_profile"] = preset_name
        if not keep_backend_overrides:
            config["dflash_stability_profile"] = None
            config["mlx_stability_profile"] = None
            config["turboquant_stability_profile"] = None

        print(f"🎛️  [llmstack] backend_stability_profile -> {preset_name}")
        if keep_backend_overrides:
            print("ℹ️  [llmstack] Backend-specific profile overrides were preserved.")
        else:
            print("ℹ️  [llmstack] Backend-specific profile overrides cleared (single-knob mode).")

        if restart:
            _restart_inference_server_if_running(config)
            print("✅ [llmstack] Running inference server (if any) restarted with new preset.")
        else:
            print("ℹ️  Add --restart to apply immediately to a running server.")
        return 0

    print(f"❌ [llmstack] Unknown model subcommand '{sub}'.")
    return 1


def run_doctor(config, args):
    print("🔎 [llmstack doctor] Checking installation...\n")
    print(f"Config dev_root: {config.get('dev_root')}")
    print(f"Plan file: {config.get('plan_file')}")
    stack = ServiceStack(config)
    print(f"DFlash healthy: {stack.dflash.is_healthy()}")
    print(f"Headroom healthy: {stack.headroom.is_healthy()}")

    registry = load_model_registry(config)
    active = active_model_name(config, registry)

    served_model = stack.dflash.served_model_id()
    expected_target = stack.backend.model_target()
    served_mismatch = False
    if served_model is None:
        print("ℹ️  Inference server: not running on :8787 (nothing to compare).")
    elif served_model == expected_target:
        print(f"✅ Served model matches active_model '{active}': {served_model}")
    else:
        served_mismatch = True
        print(f"❌ Served model mismatch: :8787 serves '{served_model}' "
              f"but active_model '{active}' expects '{expected_target}'")
        print("   Fix: run 'llmstack model use <name>' to swap the server, or restart 'llmstack run'.")

    ccr = CCRService()
    ccr_issues = ccr.validate_multi_model_config(registry=registry, active_model=active)

    if ccr_issues:
        print("❌ CCR multi-model config validation: FAILED")
        for issue in ccr_issues:
            print(f"  - {issue}")
        return 1

    print("✅ CCR multi-model config validation: OK")
    return 1 if served_mismatch else 0


def run_orchestrator(config, args):
    _sync_ccr_for_active_model(config, restart=False)
    stack = ServiceStack(config)
    stack.ensure_running()
    supervisor = Supervisor(config, config["dev_root"], stack)
    supervisor.run()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="llmstack")
    parser.add_argument("command", nargs="?", choices=["init", "serve", "proxy", "interactive", "run", "dashboard", "doctor", "model"])
    parser.add_argument("extra", nargs=argparse.REMAINDER,
                        help="Additional arguments passed to the chosen command.")
    parser.add_argument("--force", action="store_true", help="Overwrite files when supported by the command.")
    args = parser.parse_args(argv)

    if args.command == "init":
        return run_init(args)

    if args.command == "model" and (not args.extra or args.extra[0] in ("help", "-h", "--help")):
        return run_model({}, args)

    config = load_config()

    if args.command == "serve":
        return run_dflash(config, args)
    elif args.command == "proxy":
        run_proxy(config, args)
    elif args.command == "interactive":
        run_interactive(config, args)
    elif args.command == "run":
        run_orchestrator(config, args)
    elif args.command == "dashboard":
        run_dashboard(config, args)
    elif args.command == "doctor":
        run_doctor(config, args)
    elif args.command == "model":
        return run_model(config, args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
