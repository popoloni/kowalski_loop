from .base import InferenceBackend


class DFlashBackend(InferenceBackend):
    def build_serve_cmd(self):
        c = self.cfg
        return [
            "dflash", "serve",
            "--model", c["target"],
            "--draft-model", c["draft"],
            "--host", "127.0.0.1", "--port", "8787",
            "--verify-mode", c.get("verify_mode", "adaptive"),
            "--temp", str(c.get("temp", 0.2)),
            "--max-tokens", str(c.get("max_tokens", 8192)),
            "--chat-template-args", self._chat_template_args(c),
            "--prefix-cache-max-entries", str(c.get("cache_max_entries", 64)),
            "--prefix-cache-max-bytes", c.get("cache_max_bytes", "12GB"),
            "--max-snapshot-tokens", str(c.get("max_snapshot_tokens", 16000)),
            "--no-clear-cache-boundaries",
        ]
