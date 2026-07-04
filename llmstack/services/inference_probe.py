import json
import subprocess
import urllib.request


DEFAULT_HEALTH_URL = "http://127.0.0.1:8787/v1/models"


def _fetch_model_ids(health_url=DEFAULT_HEALTH_URL, timeout=3):
    try:
        with urllib.request.urlopen(health_url, timeout=timeout) as resp:
            if resp.getcode() != 200:
                return []
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    model_ids = []
    for entry in data:
        if isinstance(entry, dict):
            model_id = entry.get("id")
            if model_id:
                model_ids.append(model_id)
    return model_ids


def cmdline_for_port(port=8787):
    try:
        pid_lines = subprocess.check_output(["lsof", "-ti", f"tcp:{port}"], text=True).strip().splitlines()
    except Exception:
        pid_lines = []
    if not pid_lines:
        return None
    pid = pid_lines[0].strip()
    if not pid:
        return None
    try:
        return subprocess.check_output(["ps", "-ww", "-p", pid, "-o", "command="], text=True).strip()
    except Exception:
        return None


def detect_backend_from_cmdline(cmdline):
    cmd = (cmdline or "").lower()
    if "turboquant-serve" in cmd:
        return "turboquant", "high"
    if "mlx_lm.server" in cmd or "mlx_lm server" in cmd:
        return "mlx", "high"
    if " dflash " in cmd or "dflash serve" in cmd:
        return "dflash", "high"
    return None, "low"


def model_from_cmdline(cmdline):
    if not cmdline:
        return None
    parts = cmdline.split()
    for index, token in enumerate(parts[:-1]):
        if token == "--model":
            return parts[index + 1]
    return None


def detect_running_model(port=8787, health_url=DEFAULT_HEALTH_URL, timeout=3, expected_target=None):
    cmdline = cmdline_for_port(port)
    backend_name, backend_confidence = detect_backend_from_cmdline(cmdline)
    active_model = model_from_cmdline(cmdline)
    if active_model:
        return {
            "model_id": active_model,
            "backend_name": backend_name,
            "confidence": backend_confidence,
            "source": "process",
            "cmdline": cmdline,
            "model_ids": [],
        }

    model_ids = _fetch_model_ids(health_url=health_url, timeout=timeout)
    chosen = None
    source = None
    confidence = backend_confidence if backend_name else "low"
    if expected_target and expected_target in model_ids:
        chosen = expected_target
        source = "models-contains-expected"
        confidence = "medium"
    elif len(model_ids) == 1:
        chosen = model_ids[0]
        source = "models-singleton"
        confidence = "medium"

    return {
        "model_id": chosen,
        "backend_name": backend_name,
        "confidence": confidence,
        "source": source,
        "cmdline": cmdline,
        "model_ids": model_ids,
    }


def served_model_id(port=8787, health_url=DEFAULT_HEALTH_URL, timeout=3, expected_target=None):
    return detect_running_model(
        port=port,
        health_url=health_url,
        timeout=timeout,
        expected_target=expected_target,
    ).get("model_id")