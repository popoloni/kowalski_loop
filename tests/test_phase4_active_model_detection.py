"""Phase 4 active-model detection tests.

Run with the project venv from the repo root:

    env/bin/python tests/test_phase4_active_model_detection.py

Exits non-zero if any check fails. No third-party test runner required.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llmstack.services.inference_probe as probe


def check(cond, msg):
    if not cond:
        raise AssertionError(f"FAIL: {msg}")
    print(f"  ok: {msg}")


def test_detect_backend_and_model_from_process_cmdline():
    print("[probe] process cmdline identifies backend + active model for all backends")
    cases = [
        (
            "/Users/me/env/bin/dflash serve --model mlx-community/Qwen3.6-35B-A3B-4bit --draft-model z-lab/foo",
            "dflash",
            "mlx-community/Qwen3.6-35B-A3B-4bit",
        ),
        (
            "/opt/homebrew/bin/python3 -m mlx_lm server --model mlx-community/gemma-4-12b-coder-fable5-composer2.5-4bit --port 8787",
            "mlx",
            "mlx-community/gemma-4-12b-coder-fable5-composer2.5-4bit",
        ),
        (
            "turboquant-serve --model manjunathshiva/Qwen3.6-35B-A3B-tq3-g32 --kv-k-bits 8",
            "turboquant",
            "manjunathshiva/Qwen3.6-35B-A3B-tq3-g32",
        ),
    ]
    for cmdline, expected_backend, expected_model in cases:
        backend, confidence = probe.detect_backend_from_cmdline(cmdline)
        check(backend == expected_backend, f"backend detected for {expected_backend}")
        check(confidence == "high", f"confidence high for {expected_backend}")
        check(probe.model_from_cmdline(cmdline) == expected_model, f"model extracted for {expected_backend}")


def test_detect_running_model_prefers_process_model():
    print("[probe] process model wins over ambiguous /v1/models list")
    original_cmdline = probe.cmdline_for_port
    original_fetch = probe._fetch_model_ids
    try:
        probe.cmdline_for_port = lambda port=8787: (
            "turboquant-serve --model manjunathshiva/Qwen3.6-35B-A3B-tq3-g32 --host 127.0.0.1 --port 8787"
        )
        probe._fetch_model_ids = lambda health_url=probe.DEFAULT_HEALTH_URL, timeout=3: [
            "mlx-community/gemma-4-12B-4bit",
            "manjunathshiva/Qwen3.6-35B-A3B-tq3-g32",
        ]
        info = probe.detect_running_model(expected_target="mlx-community/gemma-4-12B-4bit")
        check(info["model_id"] == "manjunathshiva/Qwen3.6-35B-A3B-tq3-g32", "process model selected")
        check(info["backend_name"] == "turboquant", "backend propagated from process")
        check(info["source"] == "process", "source marked as process")
    finally:
        probe.cmdline_for_port = original_cmdline
        probe._fetch_model_ids = original_fetch


def test_detect_running_model_http_fallbacks():
    print("[probe] HTTP fallback handles singleton and expected-target matches")
    original_cmdline = probe.cmdline_for_port
    original_fetch = probe._fetch_model_ids
    try:
        probe.cmdline_for_port = lambda port=8787: None

        probe._fetch_model_ids = lambda health_url=probe.DEFAULT_HEALTH_URL, timeout=3: ["only-model"]
        info = probe.detect_running_model()
        check(info["model_id"] == "only-model", "singleton list resolves active model")
        check(info["source"] == "models-singleton", "singleton source recorded")

        probe._fetch_model_ids = lambda health_url=probe.DEFAULT_HEALTH_URL, timeout=3: [
            "model-a",
            "model-b",
            "model-c",
        ]
        info = probe.detect_running_model(expected_target="model-b")
        check(info["model_id"] == "model-b", "expected target chosen from model list")
        check(info["source"] == "models-contains-expected", "expected-target source recorded")

        info = probe.detect_running_model(expected_target="missing-model")
        check(info["model_id"] is None, "ambiguous list without match returns None")
    finally:
        probe.cmdline_for_port = original_cmdline
        probe._fetch_model_ids = original_fetch


if __name__ == "__main__":
    tests = [
        test_detect_backend_and_model_from_process_cmdline,
        test_detect_running_model_prefers_process_model,
        test_detect_running_model_http_fallbacks,
    ]
    failed = 0
    for test_func in tests:
        try:
            test_func()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  !! {test_func.__name__}: {exc}")
    print("\n" + ("ALL PASS" if failed == 0 else f"{failed} FAILED"))
    sys.exit(1 if failed else 0)