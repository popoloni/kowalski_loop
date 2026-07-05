import json
from abc import ABC, abstractmethod

from llmstack.config import DEFAULT_CONFIG


class InferenceBackend(ABC):
    def __init__(self, model_name, model_cfg):
        self.model_name = model_name
        self.cfg = model_cfg

    def provider_name(self):
        return str(self.cfg.get("type") or "dflash")

    def model_target(self):
        return self.cfg.get("target")

    def serve_host(self):
        return str(self.cfg.get("serve_host") or "127.0.0.1")

    def serve_port(self):
        return int(self.cfg.get("serve_port", 8787))

    @abstractmethod
    def build_serve_cmd(self):
        raise NotImplementedError

    def health_url(self):
        return self.cfg.get("inference_health_url") or f"http://{self.serve_host()}:{self.serve_port()}/v1/models"

    def chat_url(self):
        return self.cfg.get("inference_chat_url") or f"http://{self.serve_host()}:{self.serve_port()}/v1/chat/completions"

    def ccr_provider(self, timeout_ms=3600000):
        return {
            "name": self.provider_name(),
            "api_base_url": self.cfg.get("headroom_chat_url") or f"http://{DEFAULT_CONFIG['local_host']}:{DEFAULT_CONFIG['headroom_port']}/v1/chat/completions",
            "api_key": "dflash-local",
            "timeout": timeout_ms,
            "models": [self.model_target()],
            "transformer": {
                "use": [["maxtoken", {"max_tokens": int(self.cfg.get("max_tokens", 8192))}], "enhancetool"],
                "context_window": int(self.cfg.get("context_window", 32000)),
                "system_prompt_caching": bool(self.cfg.get("system_prompt_caching", True)),
            },
        }

    @staticmethod
    def _chat_template_args(cfg):
        return json.dumps(cfg.get("chat_template_args", {"enable_thinking": False}))
