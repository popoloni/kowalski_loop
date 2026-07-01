from .base import InferenceBackend


class TurboQuantBackend(InferenceBackend):
    def build_serve_cmd(self):
        c = self.cfg
        return [
            "turboquant-serve",
            "--model", c["target"],
            "--kv-k-bits", str(c.get("kv_k_bits", 8)),
            "--kv-v-bits", str(c.get("kv_v_bits", 3)),
            "--kv-min-tokens", str(c.get("kv_min_tokens", 128)),
            "--prompt-concurrency", str(c.get("prompt_concurrency", 1)),
            "--host", "127.0.0.1", "--port", "8787",
            "--chat-template-args", self._chat_template_args(c),
        ]
