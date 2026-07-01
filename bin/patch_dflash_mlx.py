#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import py_compile
import sys


DRAFT_NEEDLE = """        data[\"layer_types\"] = layer_types
        data[\"dflash_config\"] = dict(data.get(\"dflash_config\") or {})
        return cls(
            **{key: value for key, value in data.items() if key in cls.__annotations__}
        )
"""

DRAFT_REPLACEMENT = """        rope_parameters = data.get(\"rope_parameters\")
        if \"rope_theta\" not in data and isinstance(rope_parameters, dict):
            rope_theta = rope_parameters.get(\"rope_theta\")
            if rope_theta is not None:
                data[\"rope_theta\"] = rope_theta
        dflash_config = data.get(\"dflash_config\")
        if \"block_size\" not in data and isinstance(dflash_config, dict):
            block_size = dflash_config.get(\"block_size\")
            if block_size is not None:
                data[\"block_size\"] = block_size
        data[\"layer_types\"] = layer_types
        data[\"dflash_config\"] = dict(data.get(\"dflash_config\") or {})
        return cls(
            **{key: value for key, value in data.items() if key in cls.__annotations__}
        )
"""

MODEL_REMAPPING_NEEDLE = """    \"iquestcoder\": \"llama\",
}
"""

MODEL_REMAPPING_REPLACEMENT = """    \"iquestcoder\": \"llama\",
    \"gemma4_unified\": \"gemma4\",
}
"""

GEMMA4_SANITIZE_NEEDLE = """                (
                    \"vision_tower\",
                    \"multi_modal_projector\",
                    \"audio_tower\",
                    \"embed_audio\",
                    \"embed_vision\",
                )
"""

GEMMA4_SANITIZE_REPLACEMENT = """                (
                    \"vision_tower\",
                    \"vision_embedder\",
                    \"multi_modal_projector\",
                    \"audio_tower\",
                    \"embed_audio\",
                    \"embed_vision\",
                )
"""

DFLASH_GEMMA4_TARGET_NEEDLE = """        if model_type not in (\"gemma4\", \"gemma4_text\"):
            return False
"""

DFLASH_GEMMA4_TARGET_REPLACEMENT = """        if model_type not in (\"gemma4\", \"gemma4_text\", \"gemma4_unified\", \"gemma4_unified_text\"):
            return False
"""


def patch_file(path: Path, needle: str, replacement: str, label: str) -> str:
    source = path.read_text()

    if replacement in source:
        return f"{label} already patched: {path}"

    if needle not in source:
        raise RuntimeError(
            f"Could not find expected patch anchor for {label} in {path}; upstream layout may have changed."
        )

    path.write_text(source.replace(needle, replacement, 1))
    py_compile.compile(str(path), doraise=True)
    return f"Patched {label}: {path}"


def main() -> int:
    try:
        import dflash_mlx.model as model
    except ImportError as exc:
        print(f"dflash_mlx is not installed in this interpreter: {exc}", file=sys.stderr)
        return 1

    try:
        import mlx_lm.utils as mlx_utils
    except ImportError as exc:
        print(f"mlx_lm is not installed in this interpreter: {exc}", file=sys.stderr)
        return 1

    try:
        import mlx_lm.models.gemma4 as gemma4_model
    except ImportError as exc:
        print(f"mlx_lm gemma4 model is not installed in this interpreter: {exc}", file=sys.stderr)
        return 1

    try:
        import dflash_mlx.engine.target_gemma4 as dflash_target_gemma4
    except ImportError as exc:
        print(f"dflash_mlx Gemma4 target ops are not installed in this interpreter: {exc}", file=sys.stderr)
        return 1

    try:
        print(
            patch_file(
                Path(model.__file__).resolve(),
                DRAFT_NEEDLE,
                DRAFT_REPLACEMENT,
                "dflash_mlx draft config loader",
            )
        )
        print(
            patch_file(
                Path(mlx_utils.__file__).resolve(),
                MODEL_REMAPPING_NEEDLE,
                MODEL_REMAPPING_REPLACEMENT,
                "mlx_lm gemma4_unified remapping",
            )
        )
        print(
            patch_file(
                Path(gemma4_model.__file__).resolve(),
                GEMMA4_SANITIZE_NEEDLE,
                GEMMA4_SANITIZE_REPLACEMENT,
                "mlx_lm gemma4 vision weight filter",
            )
        )
        print(
            patch_file(
                Path(dflash_target_gemma4.__file__).resolve(),
                DFLASH_GEMMA4_TARGET_NEEDLE,
                DFLASH_GEMMA4_TARGET_REPLACEMENT,
                "dflash_mlx gemma4 target dispatch",
            )
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())