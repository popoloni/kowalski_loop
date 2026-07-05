import json
import os

VALID_PLUGIN_WHENS = {
    "task",
    "plan_complete",
}

VALID_PLUGIN_FAILURE_MODES = {
    "fail",
    "warn",
}

VALID_THINKING_MODES = {
    "off",
    "auto",
    "on",
}

VALID_PERMISSION_MODES = {
    "default",
    "acceptEdits",
    "plan",
    "auto",
    "dontAsk",
    "bypassPermissions",
}

LEGACY_PERMISSION_MODE_ALIASES = {
    "acceptAll": "acceptEdits",
    "askEdits": "default",
    "readOnly": "plan",
}

DEFAULT_CONFIG = {
    "local_host": "127.0.0.1",
    "inference_port": 8787,
    "headroom_port": 8789,
    "dev_root": ".",
    "plan_file": "plan.json",
    "loop_mode": "plan",
    "continuous_queue_file": "task_queue.json",
    "continuous_poll_seconds": 2,
    "watch_queue_file": "task_queue.json",
    "watch_root": ".",
    "watch_poll_seconds": 2,
    "watch_debounce_seconds": 0.5,
    "log_dir": "logs",
    "dflash_log": "logs/dflash_server.log",
    "dflash_watchdog_poll_seconds": 5,
    "dflash_watchdog_fail_threshold": 3,
    "backend_stability_profile": "balanced",
    "backend_stability_overrides": {},
    "dflash_stability_profile": None,
    "dflash_stability_overrides": {},
    "mlx_stability_profile": None,
    "mlx_stability_overrides": {},
    "turboquant_stability_profile": None,
    "turboquant_stability_overrides": {},
    "headroom_log": "logs/headroom.log",
    "headroom_traffic_log": "logs/headroom_traffic.jsonl",
    "timings_csv": "logs/dflash_timings.csv",
    "permission_mode": "acceptEdits",
    "max_turns": 150,
    "timeout_seconds": 1800,
    "warmup_timeout_seconds": 120,
    "max_retries": 3,
    "max_resumes": 8,
    "agent_format_retries": 2,
    "size_threshold_bytes": 12000,
    "debug_log": "logs/kowalski_debug.log",
    "debug_max_chars": 0,
    "require_change": True,
    "wiring_check": True,
    "review_enabled": False,
    "verification_plugins": {},
    "thinking_mode": "off",
}


def _http_base_url(host, port):
    return f"http://{host}:{int(port)}"


def apply_runtime_network_defaults(cfg):
    host = str(cfg.get("local_host", DEFAULT_CONFIG["local_host"]) or DEFAULT_CONFIG["local_host"]).strip()
    inference_port = int(cfg.get("inference_port", DEFAULT_CONFIG["inference_port"]))
    headroom_port = int(cfg.get("headroom_port", DEFAULT_CONFIG["headroom_port"]))

    cfg["local_host"] = host
    cfg["inference_port"] = inference_port
    cfg["headroom_port"] = headroom_port

    cfg["inference_base_url"] = _http_base_url(host, inference_port)
    cfg["inference_health_url"] = cfg["inference_base_url"] + "/v1/models"
    cfg["inference_chat_url"] = cfg["inference_base_url"] + "/v1/chat/completions"

    cfg["headroom_base_url"] = _http_base_url(host, headroom_port)
    cfg["headroom_health_url"] = cfg["headroom_base_url"] + "/health"
    cfg["headroom_chat_url"] = cfg["headroom_base_url"] + "/v1/chat/completions"
    return cfg


def _normalize_string_list(value, label):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{label} must be a list of non-empty strings")
    return [item.strip() for item in value]


def normalize_verification_plugins(raw_plugins):
    if raw_plugins in (None, ""):
        return {}
    if not isinstance(raw_plugins, dict):
        raise ValueError("verification_plugins must be an object mapping plugin names to definitions")

    normalized = {}
    for name, spec in raw_plugins.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("verification_plugins keys must be non-empty strings")
        if not isinstance(spec, dict):
            raise ValueError(f"verification_plugins['{name}'] must be an object")

        command = str(spec.get("command") or "").strip()
        if not command:
            raise ValueError(f"verification_plugins['{name}'].command is required")

        when = str(spec.get("when", "task") or "task").strip().lower()
        if when not in VALID_PLUGIN_WHENS:
            raise ValueError(
                f"verification_plugins['{name}'].when must be one of {sorted(VALID_PLUGIN_WHENS)}"
            )

        on_failure = str(spec.get("on_failure", "fail") or "fail").strip().lower()
        if on_failure not in VALID_PLUGIN_FAILURE_MODES:
            raise ValueError(
                f"verification_plugins['{name}'].on_failure must be one of {sorted(VALID_PLUGIN_FAILURE_MODES)}"
            )

        enabled = spec.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"verification_plugins['{name}'].enabled must be true or false")

        normalized[name.strip()] = {
            "command": command,
            "when": when,
            "languages": _normalize_string_list(spec.get("languages"), f"verification_plugins['{name}'].languages"),
            "files": _normalize_string_list(spec.get("files"), f"verification_plugins['{name}'].files"),
            "on_failure": on_failure,
            "enabled": enabled,
        }
    return normalized


def normalize_permission_mode(raw_mode):
    mode = str(raw_mode or "").strip()
    if not mode:
        return DEFAULT_CONFIG["permission_mode"]

    if mode in VALID_PERMISSION_MODES:
        return mode

    if mode in LEGACY_PERMISSION_MODE_ALIASES:
        mapped = LEGACY_PERMISSION_MODE_ALIASES[mode]
        print(
            f"⚠️ [Kowalski] Legacy permission_mode '{mode}' mapped to '{mapped}'. "
            "Please update llmstack_config.json."
        )
        return mapped

    print(
        f"⚠️ [Kowalski] Unsupported permission_mode '{mode}', "
        f"falling back to '{DEFAULT_CONFIG['permission_mode']}'."
    )
    return DEFAULT_CONFIG["permission_mode"]


def normalize_thinking_mode(raw_mode):
    mode = str(raw_mode or "").strip().lower()
    if not mode:
        return DEFAULT_CONFIG["thinking_mode"]
    if mode in VALID_THINKING_MODES:
        return mode
    raise ValueError(f"thinking_mode must be one of {sorted(VALID_THINKING_MODES)}")


def _abs_path(base_dir, value):
    if not value:
        return value
    return value if os.path.isabs(value) else os.path.normpath(os.path.join(base_dir, value))


def load_config(config_path="llmstack_config.json"):
    cfg = dict(DEFAULT_CONFIG)
    base_dir = os.path.dirname(os.path.abspath(config_path))
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as f:
            cfg.update(json.load(f))
        print(f"🔧 [Kowalski] Config loaded: Root='{cfg['dev_root']}', Plan='{cfg['plan_file']}'")
    else:
        print("⚠️ [Kowalski] No llmstack_config.json found, using defaults.")

    apply_runtime_network_defaults(cfg)

    cfg["log_dir"] = _abs_path(base_dir, cfg.get("log_dir", "logs"))
    os.makedirs(cfg["log_dir"], exist_ok=True)

    # Resolve all log file paths from config or derive them from log_dir.
    cfg["dflash_log"] = _abs_path(base_dir, cfg.get("dflash_log") or os.path.join(cfg["log_dir"], "dflash_server.log"))
    cfg["headroom_log"] = _abs_path(base_dir, cfg.get("headroom_log") or os.path.join(cfg["log_dir"], "headroom.log"))
    cfg["headroom_traffic_log"] = _abs_path(base_dir, cfg.get("headroom_traffic_log") or os.path.join(cfg["log_dir"], "headroom_traffic.jsonl"))
    cfg["timings_csv"] = _abs_path(base_dir, cfg.get("timings_csv") or os.path.join(cfg["log_dir"], "dflash_timings.csv"))
    cfg["debug_log"] = _abs_path(base_dir, cfg.get("debug_log") or os.path.join(cfg["log_dir"], "kowalski_debug.log"))

    for key in ("dflash_log", "headroom_log", "headroom_traffic_log", "timings_csv", "debug_log"):
        os.makedirs(os.path.dirname(cfg[key]), exist_ok=True)

    cfg["permission_mode"] = normalize_permission_mode(cfg.get("permission_mode"))
    if "interactive_permission_mode" in cfg:
        cfg["interactive_permission_mode"] = normalize_permission_mode(cfg.get("interactive_permission_mode"))
    cfg["verification_plugins"] = normalize_verification_plugins(cfg.get("verification_plugins"))
    cfg["thinking_mode"] = normalize_thinking_mode(cfg.get("thinking_mode"))

    timeout_s = int(cfg.get("timeout_seconds", cfg["timeout_seconds"]))
    cfg["task_timeout"] = timeout_s
    os.environ.update({
        "API_TIMEOUT_MS": str(timeout_s * 1000),
        "CLAUDE_STREAM_IDLE_TIMEOUT_MS": str(timeout_s * 1000),
        "CLAUDE_ENABLE_BYTE_WATCHDOG": "0",
        "CLAUDE_ENABLE_STREAM_WATCHDOG": "0",
        "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING": "1",
        "CLAUDE_CODE_DISABLE_THINKING": "1",
    })
    print(f"⏱️  [Kowalski] Timeout = {timeout_s}s (API_TIMEOUT_MS={os.environ['API_TIMEOUT_MS']}).")
    return cfg
