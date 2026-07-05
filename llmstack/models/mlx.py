import sys

from .base import InferenceBackend


MLX_STABILITY_PROFILES = {
    "performance": {
        "max_tokens": 8192,
        "prompt_concurrency": 2,
        "prefill_step_size": 2048,
        "cache_max_entries": 64,
        "cache_max_bytes": "12GB",
    },
    "balanced": {
        "max_tokens": 8192,
        "prompt_concurrency": 1,
        "prefill_step_size": 2048,
        "cache_max_entries": 64,
        "cache_max_bytes": "12GB",
    },
    "stable": {
        "max_tokens": 4096,
        "prompt_concurrency": 1,
        "prefill_step_size": 1536,
        "cache_max_entries": 48,
        "cache_max_bytes": "8GB",
    },
    "safest": {
        "max_tokens": 2048,
        "prompt_concurrency": 1,
        "prefill_step_size": 1024,
        "cache_max_entries": 32,
        "cache_max_bytes": "6GB",
    },
}


class MLXBackend(InferenceBackend):
    def _effective_serve_settings(self):
        c = self.cfg
        profile_name = str(c.get("stability_profile", "balanced") or "balanced").strip().lower()
        profile = MLX_STABILITY_PROFILES.get(profile_name, MLX_STABILITY_PROFILES["balanced"])

        settings = {
            "temp": c.get("temp", 0.2),
            "max_tokens": c.get("max_tokens", 8192),
            "prompt_concurrency": c.get("prompt_concurrency", 1),
            "prefill_step_size": c.get("prefill_step_size", 2048),
            "cache_max_entries": c.get("cache_max_entries", 64),
            "cache_max_bytes": c.get("cache_max_bytes", "12GB"),
        }
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
            sys.executable,
            "-m",
            "mlx_lm",
            "server",
            "--model", c["target"],
            "--host", self.serve_host(), "--port", str(self.serve_port()),
            "--temp", str(s["temp"]),
            "--max-tokens", str(s["max_tokens"]),
            "--chat-template-args", self._chat_template_args(c),
            "--prompt-concurrency", str(s["prompt_concurrency"]),
            "--prefill-step-size", str(s["prefill_step_size"]),
            "--prompt-cache-size", str(s["cache_max_entries"]),
            "--prompt-cache-bytes", str(s["cache_max_bytes"]),
        ]