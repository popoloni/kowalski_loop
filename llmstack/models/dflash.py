from pathlib import Path
import shutil
import sys

from .base import InferenceBackend


DFLASH_STABILITY_PROFILES = {
    # Highest throughput / lowest guardrails.
    "performance": {
        "max_tokens": 8192,
        "max_snapshot_tokens": 20000,
        "cache_max_entries": 64,
        "cache_max_bytes": "12GB",
    },
    # Current default behavior.
    "balanced": {
        "max_tokens": 8192,
        "max_snapshot_tokens": 16000,
        "cache_max_entries": 64,
        "cache_max_bytes": "12GB",
    },
    # Reduced memory pressure to lower GPU runtime instability risk.
    "stable": {
        "max_tokens": 4096,
        "max_snapshot_tokens": 12000,
        "cache_max_entries": 48,
        "cache_max_bytes": "8GB",
    },
    # Most conservative profile when long requests repeatedly crash the runtime.
    "safest": {
        "max_tokens": 2048,
        "max_snapshot_tokens": 8000,
        "cache_max_entries": 32,
        "cache_max_bytes": "6GB",
    },
}


class DFlashBackend(InferenceBackend):
    def _dflash_executable(self):
        # Prefer the venv-local executable so watchdog restarts do not depend on an activated shell PATH.
        candidate = Path(sys.executable).resolve().parent / "dflash"
        if candidate.exists():
            return str(candidate)
        found = shutil.which("dflash")
        return found or "dflash"

    def _effective_serve_settings(self):
        c = self.cfg
        profile_name = str(c.get("stability_profile", "balanced") or "balanced").strip().lower()
        profile = DFLASH_STABILITY_PROFILES.get(profile_name, DFLASH_STABILITY_PROFILES["balanced"])

        settings = {
            "verify_mode": c.get("verify_mode", "adaptive"),
            "temp": c.get("temp", 0.2),
            "max_tokens": c.get("max_tokens", 8192),
            "cache_max_entries": c.get("cache_max_entries", 64),
            "cache_max_bytes": c.get("cache_max_bytes", "12GB"),
            "max_snapshot_tokens": c.get("max_snapshot_tokens", 16000),
        }

        # Profile values intentionally override baseline model params.
        settings.update(profile)

        overrides = c.get("stability_overrides")
        if isinstance(overrides, dict):
            for k in settings.keys():
                if k in overrides and overrides[k] is not None:
                    settings[k] = overrides[k]

        return settings

    def build_serve_cmd(self):
        c = self.cfg
        s = self._effective_serve_settings()
        return [
            self._dflash_executable(), "serve",
            "--model", c["target"],
            "--draft-model", c["draft"],
            "--host", self.serve_host(), "--port", str(self.serve_port()),
            "--verify-mode", str(s["verify_mode"]),
            "--temp", str(s["temp"]),
            "--max-tokens", str(s["max_tokens"]),
            "--chat-template-args", self._chat_template_args(c),
            "--prefix-cache-max-entries", str(s["cache_max_entries"]),
            "--prefix-cache-max-bytes", str(s["cache_max_bytes"]),
            "--max-snapshot-tokens", str(s["max_snapshot_tokens"]),
            "--no-clear-cache-boundaries",
        ]
