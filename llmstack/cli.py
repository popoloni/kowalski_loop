import argparse
import json
import os
import subprocess
import sys

from llmstack.config import load_config
from llmstack.core.supervisor import Supervisor
from llmstack.models.registry import active_model_name, load_active_backend, load_model_registry
from llmstack.services.ccr_service import CCRService
from llmstack.services.stack import ServiceStack

CONFIG_PATH = "llmstack_config.json"


def _load_raw_user_config(config_path=CONFIG_PATH):
    try:
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_raw_user_config(raw_cfg, config_path=CONFIG_PATH):
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(raw_cfg, f, indent=2)


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
    served = stack.dflash.served_model_id()
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
    extra = args.extra or []
    model_name = extra[0] if extra and not extra[0].startswith("-") else None
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
    registry = load_model_registry(config)
    active = active_model_name(config, registry)
    extra = args.extra or []

    if not extra or extra[0] in ("help", "-h", "--help"):
        print("Usage: llmstack model list | llmstack model use <name> | llmstack model recommend --use agentic|decode [--apply]")
        return 0

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
    parser.add_argument("command", nargs="?", choices=["serve", "proxy", "interactive", "run", "dashboard", "doctor", "model"])
    parser.add_argument("extra", nargs=argparse.REMAINDER,
                        help="Additional arguments passed to the chosen command.")
    args = parser.parse_args(argv)
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
