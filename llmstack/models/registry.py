import copy

from .dflash import DFlashBackend
from .mlx import MLXBackend
from .turboquant import TurboQuantBackend


DEFAULT_MODELS = {
    "dflash-qwen27b": {
        "type": "dflash",
        "target": "mlx-community/Qwen3.6-27B-4bit",
        "draft": "z-lab/Qwen3.6-27B-DFlash",
        "verify_mode": "adaptive",
        "max_tokens": 8192,
        "temp": 0.2,
        "chat_template_args": {"enable_thinking": False},
        "cache_max_entries": 64,
        "cache_max_bytes": "12GB",
        "max_snapshot_tokens": 16000,
        "ram_required_gb": 48,
        "description": "Dense 27B with DFlash speculative decoding",
    },
    "dflash-qwen35b-a3b-optiq4": {
        "type": "dflash",
        "target": "mlx-community/Qwen3.6-35B-A3B-OptiQ-4bit",
        "draft": "z-lab/Qwen3.6-35B-A3B-DFlash",
        "verify_mode": "adaptive",
        "max_tokens": 8192,
        "temp": 0.2,
        "chat_template_args": {"enable_thinking": False},
        "cache_max_entries": 64,
        "cache_max_bytes": "12GB",
        "max_snapshot_tokens": 16000,
        "ram_required_gb": 56,
        "best_for": "decode",
        "description": "Dense 35B-A3B OptiQ 4bit with DFlash draft",
    },
    "dflash-gemma4-12b": {
        "type": "dflash",
        "target": "mlx-community/gemma-4-12B-4bit",
        "draft": "z-lab/gemma4-12B-it-DFlash",
        "verify_mode": "adaptive",
        "max_tokens": 8192,
        "temp": 0.2,
        "chat_template_args": {"enable_thinking": False},
        "cache_max_entries": 64,
        "cache_max_bytes": "12GB",
        "max_snapshot_tokens": 16000,
        "ram_required_gb": 16,
        "best_for": "decode",
        "description": "Gemma 4 12B with DFlash speculative decoding",
    },
    "mlx-gemma4-12b": {
        "type": "mlx",
        "target": "mlx-community/gemma-4-12B-4bit",
        "draft": None,
        "max_tokens": 1024,
        "temp": 0.2,
        "chat_template_args": {"enable_thinking": False},
        "prompt_concurrency": 1,
        "prefill_step_size": 2048,
        "cache_max_entries": 64,
        "cache_max_bytes": "12GB",
        "ram_required_gb": 16,
        "best_for": "quality",
        "description": "Gemma 4 12B on pure MLX server without DFlash",
    },
    "turboquant-qwen35b-moe": {
        "type": "turboquant",
        "target": "manjunathshiva/Qwen3.6-35B-A3B-tq3-g32",
        "draft": None,
        "kv_k_bits": 8,
        "kv_v_bits": 3,
        "kv_min_tokens": 128,
        "prompt_concurrency": 1,
        "max_tokens": 8192,
        "temp": 0.2,
        "ram_required_gb": 24,
        "best_for": "agentic",
        "description": "Sparse MoE 35B / ~3B active",
    },
}


BACKEND_BY_TYPE = {
    "dflash": DFlashBackend,
    "mlx": MLXBackend,
    "turboquant": TurboQuantBackend,
}


def load_model_registry(config):
    models = config.get("models")
    if isinstance(models, dict) and models:
        return models
    return copy.deepcopy(DEFAULT_MODELS)


def active_model_name(config, registry=None):
    registry = registry or load_model_registry(config)
    active = config.get("active_model")
    if active in registry:
        return active
    return next(iter(registry.keys()))


def build_backend(model_name, model_cfg):
    backend_type = str(model_cfg.get("type") or "dflash")
    cls = BACKEND_BY_TYPE.get(backend_type)
    if cls is None:
        raise ValueError(f"Unsupported backend type '{backend_type}' for model '{model_name}'")
    if not model_cfg.get("target"):
        raise ValueError(f"Model '{model_name}' is missing 'target'")
    return cls(model_name=model_name, model_cfg=model_cfg)


def load_active_backend(config):
    registry = load_model_registry(config)
    model_name = active_model_name(config, registry)
    model_cfg = copy.deepcopy(registry[model_name])
    backend_type = str(model_cfg.get("type") or "").strip().lower()

    # Priority: model-local < global backend_stability_* < type-specific *_stability_*
    profile = config.get("backend_stability_profile")
    type_profile = config.get(f"{backend_type}_stability_profile") if backend_type else None
    if type_profile:
        profile = type_profile
    if profile:
        model_cfg["stability_profile"] = profile

    merged_overrides = dict(model_cfg.get("stability_overrides") or {})
    global_overrides = config.get("backend_stability_overrides")
    if isinstance(global_overrides, dict) and global_overrides:
        merged_overrides.update(global_overrides)
    type_overrides = config.get(f"{backend_type}_stability_overrides") if backend_type else None
    if isinstance(type_overrides, dict) and type_overrides:
        merged_overrides.update(type_overrides)
    if merged_overrides:
        model_cfg["stability_overrides"] = merged_overrides

    backend = build_backend(model_name, model_cfg)
    return model_name, backend, registry
