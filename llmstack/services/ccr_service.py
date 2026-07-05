import argparse
import json
import os
import subprocess

from llmstack.config import DEFAULT_CONFIG

from .manager import ServiceManager


class CCRService(ServiceManager):
    def __init__(self, config_path=None, config=None):
        super().__init__("ccr")
        self.config_path = config_path or os.path.expanduser("~/.claude-code-router/config.json")
        self.config = config or {}

    @staticmethod
    def _router_keys():
        return ["default", "background", "think", "longContext", "webSearch"]

    @staticmethod
    def _default_transformer():
        return {
            "use": [["maxtoken", {"max_tokens": 8192}], "enhancetool"],
            "context_window": 32000,
            "system_prompt_caching": True,
        }

    @staticmethod
    def _ensure_provider_transformer(existing, max_tokens):
        """Ensure transformer keeps enhancetool and uses provider max token cap."""
        xf = dict(existing) if isinstance(existing, dict) else {}
        use = list(xf.get("use") or [])

        saw_maxtoken = False
        saw_enhancetool = False
        rebuilt_use = []
        for item in use:
            if isinstance(item, list) and item and item[0] == "maxtoken":
                saw_maxtoken = True
                rebuilt_use.append(["maxtoken", {"max_tokens": int(max_tokens)}])
                continue
            if item == "enhancetool":
                saw_enhancetool = True
            rebuilt_use.append(item)

        if not saw_maxtoken:
            rebuilt_use.insert(0, ["maxtoken", {"max_tokens": int(max_tokens)}])
        if not saw_enhancetool:
            rebuilt_use.append("enhancetool")

        xf["use"] = rebuilt_use
        xf["context_window"] = int(xf.get("context_window", 32000))
        xf["system_prompt_caching"] = bool(xf.get("system_prompt_caching", True))
        return xf

    @staticmethod
    def _model_entry_to_provider_name(model_cfg):
        return str(model_cfg.get("type") or "dflash")

    @staticmethod
    def _model_entry_to_target(model_cfg):
        return model_cfg.get("target")

    def _resolve_active_pair(self, registry, active_model):
        if not isinstance(registry, dict) or not registry:
            raise ValueError("Model registry is empty; cannot build CCR configuration")

        model_name = active_model if active_model in registry else next(iter(registry.keys()))
        model_cfg = registry[model_name]
        target = self._model_entry_to_target(model_cfg)
        if not target:
            raise ValueError(f"Model '{model_name}' has no target")
        provider_name = self._model_entry_to_provider_name(model_cfg)
        return model_name, provider_name, target

    def render(self, registry, active_model, timeout_ms=3600000, backend=None):
        """Render a multi-model CCR config from llmstack model registry data."""
        base = self._load_config()
        headroom_chat_url = self.config.get("headroom_chat_url", f"http://{DEFAULT_CONFIG['local_host']}:{DEFAULT_CONFIG['headroom_port']}/v1/chat/completions")
        local_host = self.config.get("local_host", "127.0.0.1")
        model_name, active_provider, active_target = self._resolve_active_pair(registry, active_model)

        if backend is not None:
            active_provider = getattr(backend, "provider_name", lambda: active_provider)()
            active_target = getattr(backend, "model_target", lambda: active_target)()

        existing_providers = {
            p.get("name"): p for p in base.get("Providers", []) if isinstance(p, dict) and p.get("name")
        }

        provider_models = {}
        provider_cfgs = {}
        for _, model_cfg in registry.items():
            provider_name = self._model_entry_to_provider_name(model_cfg)
            target = self._model_entry_to_target(model_cfg)
            if not target:
                continue
            provider_models.setdefault(provider_name, [])
            provider_cfgs.setdefault(provider_name, [])
            if target not in provider_models[provider_name]:
                provider_models[provider_name].append(target)
            provider_cfgs[provider_name].append(model_cfg)

        providers = []
        for provider_name in sorted(provider_models.keys()):
            existing = existing_providers.get(provider_name, {})
            model_cfgs = provider_cfgs.get(provider_name, [])
            provider_max_tokens = 8192
            if model_cfgs:
                provider_max_tokens = int(model_cfgs[0].get("max_tokens", 8192))
            provider_cfg = {
                "name": provider_name,
                "api_base_url": existing.get("api_base_url", headroom_chat_url),
                "api_key": existing.get("api_key", "dflash-local"),
                "timeout": timeout_ms,
                "models": provider_models[provider_name],
                "transformer": self._ensure_provider_transformer(
                    existing.get("transformer", self._default_transformer()),
                    provider_max_tokens,
                ),
            }
            # Enforce local Headroom route for every provider.
            provider_cfg["api_base_url"] = headroom_chat_url
            providers.append(provider_cfg)

        route_target = f"{active_provider},{active_target}"
        router = dict(base.get("Router", {}))
        for key in self._router_keys():
            router[key] = route_target
        router["longContextThreshold"] = router.get("longContextThreshold", 30000)

        rendered = {
            "LOG": base.get("LOG", True),
            "HOST": base.get("HOST", local_host),
            "NON_INTERACTIVE_MODE": base.get("NON_INTERACTIVE_MODE", True),
            "API_TIMEOUT_MS": timeout_ms,
            "Providers": providers,
            "Router": router,
        }

        print(
            "🔧 [Kowalski] Rendered CCR multi-model config "
            f"(active={model_name} -> {route_target}, providers={len(providers)})"
        )
        return rendered

    def sync_provider(self, registry, active_model, timeout_ms=3600000, backend=None):
        cfg = self.render(
            registry=registry,
            active_model=active_model,
            timeout_ms=timeout_ms,
            backend=backend,
        )
        self._save_config(cfg)
        print(f"✅ [Kowalski] CCR config synced to {self.config_path}")
        return cfg

    def validate_multi_model_config(self, registry, active_model):
        issues = []
        cfg = self._load_config()
        expected_api_base = self.config.get("headroom_chat_url", f"http://{DEFAULT_CONFIG['local_host']}:{DEFAULT_CONFIG['headroom_port']}/v1/chat/completions")

        try:
            _, active_provider, active_target = self._resolve_active_pair(registry, active_model)
        except ValueError as exc:
            return [str(exc)]

        expected_route = f"{active_provider},{active_target}"
        providers = cfg.get("Providers", [])
        provider_models = {}

        for p in providers:
            if not isinstance(p, dict):
                continue
            name = p.get("name")
            if not name:
                continue
            provider_models[name] = set(p.get("models") or [])
            api_base = str(p.get("api_base_url") or "")
            if api_base != expected_api_base:
                issues.append(
                    f"Provider '{name}' api_base_url must be '{expected_api_base}' (found '{api_base}')"
                )

        for model_name, model_cfg in registry.items():
            provider_name = self._model_entry_to_provider_name(model_cfg)
            target = self._model_entry_to_target(model_cfg)
            if not target:
                issues.append(f"Model '{model_name}' has no target")
                continue
            if provider_name not in provider_models:
                issues.append(f"Missing provider '{provider_name}' in CCR config")
                continue
            if target not in provider_models[provider_name]:
                issues.append(
                    f"Missing model target '{target}' in provider '{provider_name}' models list"
                )

        router = cfg.get("Router", {})
        for key in self._router_keys():
            current = router.get(key)
            if current != expected_route:
                issues.append(
                    f"Router.{key} must be '{expected_route}' (found '{current}')"
                )

        return issues

    def _load_config(self):
        try:
            with open(self.config_path, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_config(self, config):
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    def patch_timeout(self, timeout_ms):
        cfg = self._load_config()
        cfg["API_TIMEOUT_MS"] = timeout_ms
        for prov in cfg.get("Providers", []):
            prov["timeout"] = timeout_ms
        self._save_config(cfg)
        print(f"🔧 [Kowalski] CCR config timeout set to {timeout_ms} ms")

    def pretrust(self, dev_root):
        path = os.path.abspath(dev_root)
        claude_json = os.path.expanduser("~/.claude.json")
        try:
            data = json.load(open(claude_json, encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        proj = data.setdefault("projects", {}).setdefault(path, {})
        proj["hasTrustDialogAccepted"] = True
        proj["hasCompletedProjectOnboarding"] = True
        with open(claude_json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"🔐 [Kowalski] Pre-trusted folder: {path}")

    def ensure_running(self):
        self.restart()

    def restart(self):
        print("🔄 [Kowalski] Restarting Claude Code Router daemon...")
        subprocess.run(["ccr", "restart"], check=True)

    def stop(self):
        raise NotImplementedError("CCRService stop is not supported")

    def health(self):
        return True

    def is_healthy(self) -> bool:
        return True


def main():
    parser = argparse.ArgumentParser(description="CCR configuration helper")
    parser.add_argument("command", choices=["patch-timeout", "pretrust", "restart"])
    parser.add_argument("value", nargs="?")
    parser.add_argument("--config-path", default=None,
                        help="Path to ~/.claude-code-router/config.json")
    args = parser.parse_args()

    service = CCRService(config_path=args.config_path)
    if args.command == "patch-timeout":
        if args.value is None:
            parser.error("patch-timeout requires a timeout value in milliseconds")
        service.patch_timeout(int(args.value))
    elif args.command == "pretrust":
        if args.value is None:
            parser.error("pretrust requires a dev_root path")
        service.pretrust(args.value)
    elif args.command == "restart":
        service.restart()


if __name__ == "__main__":
    main()
