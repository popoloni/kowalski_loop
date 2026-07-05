from .base import InferenceBackend


TURBOQUANT_STABILITY_PROFILES = {
    "performance": {
        "prompt_concurrency": 2,
        "kv_min_tokens": 256,
        "kv_k_bits": 8,
        "kv_v_bits": 3,
    },
    "balanced": {
        "prompt_concurrency": 1,
        "kv_min_tokens": 128,
        "kv_k_bits": 8,
        "kv_v_bits": 3,
    },
    "stable": {
        "prompt_concurrency": 1,
        "kv_min_tokens": 96,
        "kv_k_bits": 8,
        "kv_v_bits": 3,
    },
    "safest": {
        "prompt_concurrency": 1,
        "kv_min_tokens": 64,
        "kv_k_bits": 8,
        "kv_v_bits": 3,
    },
}


class TurboQuantBackend(InferenceBackend):
    def _effective_serve_settings(self):
        c = self.cfg
        profile_name = str(c.get("stability_profile", "balanced") or "balanced").strip().lower()
        profile = TURBOQUANT_STABILITY_PROFILES.get(profile_name, TURBOQUANT_STABILITY_PROFILES["balanced"])

        settings = {
            "kv_k_bits": c.get("kv_k_bits", 8),
            "kv_v_bits": c.get("kv_v_bits", 3),
            "kv_min_tokens": c.get("kv_min_tokens", 128),
            "prompt_concurrency": c.get("prompt_concurrency", 1),
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
            "turboquant-serve",
            "--model", c["target"],
            "--kv-k-bits", str(s["kv_k_bits"]),
            "--kv-v-bits", str(s["kv_v_bits"]),
            "--kv-min-tokens", str(s["kv_min_tokens"]),
            "--prompt-concurrency", str(s["prompt_concurrency"]),
            "--host", self.serve_host(), "--port", str(self.serve_port()),
            "--chat-template-args", self._chat_template_args(c),
        ]
