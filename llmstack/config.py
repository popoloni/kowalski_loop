import json
import os

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
    "dev_root": ".",
    "plan_file": "plan.json",
    "log_dir": "logs",
    "dflash_log": "logs/dflash_server.log",
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
    "debug_log": "logs/ralph_debug.log",
    "debug_max_chars": 0,
    "require_change": True,
    "wiring_check": True,
    "review_enabled": False,
}


def normalize_permission_mode(raw_mode):
    mode = str(raw_mode or "").strip()
    if not mode:
        return DEFAULT_CONFIG["permission_mode"]

    if mode in VALID_PERMISSION_MODES:
        return mode

    if mode in LEGACY_PERMISSION_MODE_ALIASES:
        mapped = LEGACY_PERMISSION_MODE_ALIASES[mode]
        print(
            f"⚠️ [Ralph] Legacy permission_mode '{mode}' mapped to '{mapped}'. "
            "Please update llmstack_config.json."
        )
        return mapped

    print(
        f"⚠️ [Ralph] Unsupported permission_mode '{mode}', "
        f"falling back to '{DEFAULT_CONFIG['permission_mode']}'."
    )
    return DEFAULT_CONFIG["permission_mode"]


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
        print(f"🔧 [Ralph] Config loaded: Root='{cfg['dev_root']}', Plan='{cfg['plan_file']}'")
    else:
        print("⚠️ [Ralph] No llmstack_config.json found, using defaults.")

    cfg["log_dir"] = _abs_path(base_dir, cfg.get("log_dir", "logs"))
    os.makedirs(cfg["log_dir"], exist_ok=True)

    # Resolve all log file paths from config or derive them from log_dir.
    cfg["dflash_log"] = _abs_path(base_dir, cfg.get("dflash_log") or os.path.join(cfg["log_dir"], "dflash_server.log"))
    cfg["headroom_log"] = _abs_path(base_dir, cfg.get("headroom_log") or os.path.join(cfg["log_dir"], "headroom.log"))
    cfg["headroom_traffic_log"] = _abs_path(base_dir, cfg.get("headroom_traffic_log") or os.path.join(cfg["log_dir"], "headroom_traffic.jsonl"))
    cfg["timings_csv"] = _abs_path(base_dir, cfg.get("timings_csv") or os.path.join(cfg["log_dir"], "dflash_timings.csv"))
    cfg["debug_log"] = _abs_path(base_dir, cfg.get("debug_log") or os.path.join(cfg["log_dir"], "ralph_debug.log"))

    for key in ("dflash_log", "headroom_log", "headroom_traffic_log", "timings_csv", "debug_log"):
        os.makedirs(os.path.dirname(cfg[key]), exist_ok=True)

    cfg["permission_mode"] = normalize_permission_mode(cfg.get("permission_mode"))
    if "interactive_permission_mode" in cfg:
        cfg["interactive_permission_mode"] = normalize_permission_mode(cfg.get("interactive_permission_mode"))

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
    print(f"⏱️  [Ralph] Timeout = {timeout_s}s (API_TIMEOUT_MS={os.environ['API_TIMEOUT_MS']}).")
    return cfg
