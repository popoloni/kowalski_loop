import sys

from .base import InferenceBackend


class MLXBackend(InferenceBackend):
    def build_serve_cmd(self):
        c = self.cfg
        return [
            sys.executable,
            "-m",
            "mlx_lm",
            "server",
            "--model", c["target"],
            "--host", "127.0.0.1", "--port", "8787",
            "--temp", str(c.get("temp", 0.2)),
            "--max-tokens", str(c.get("max_tokens", 8192)),
            "--chat-template-args", self._chat_template_args(c),
            "--prompt-concurrency", str(c.get("prompt_concurrency", 1)),
            "--prefill-step-size", str(c.get("prefill_step_size", 2048)),
            "--prompt-cache-size", str(c.get("cache_max_entries", 64)),
            "--prompt-cache-bytes", c.get("cache_max_bytes", "12GB"),
        ]