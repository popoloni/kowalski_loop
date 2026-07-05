import os
import signal
import subprocess
import time

from llmstack.config import DEFAULT_CONFIG
from llmstack.models.registry import load_active_backend

from .ccr_service import CCRService
from .dflash_service import DFlashService
from .headroom_service import HeadroomService


class ServiceStack:
    def __init__(self, config):
        self.config = config
        self._stop = False
        self.active_model_name, self.backend, self.model_registry = load_active_backend(config)
        self.ccr = CCRService(config=self.config)
        self.dflash = DFlashService(
            backend=self.backend,
            log_file=self.config.get("dflash_log", "dflash_server.log"),
        )
        self.headroom = HeadroomService(
            host=self.config.get("local_host", "127.0.0.1"),
            port=int(self.config.get("headroom_port", 8789)),
            upstream_url=self.config.get("inference_base_url", f"http://{DEFAULT_CONFIG['local_host']}:{DEFAULT_CONFIG['inference_port']}"),
            log_file=self.config.get("headroom_log", "headroom.log"),
            traffic_log=self.config.get("headroom_traffic_log", "headroom_traffic.jsonl"),
        )
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        self._stop = True
        self.stop()

    def patch_ccr_timeout(self):
        timeout_ms = int(self.config["task_timeout"] * 1000)
        self.ccr.patch_timeout(timeout_ms)

    def pretrust(self):
        self.ccr.pretrust(self.config["dev_root"])

    def ensure_running(self):
        self.patch_ccr_timeout()
        self.pretrust()
        try:
            self.ccr.restart()
        except Exception as exc:
            print(f"⚠️  [llmstack] CCR restart failed; continuing anyway: {exc}")
        self.dflash._stop = False
        self.headroom._stop = False
        self.dflash.ensure_running()
        self.headroom.ensure_running()

    def warm_up_cache(self):
        print("🔥 [llmstack] Warming the agentic prefix cache...")
        warmup_timeout = int(self.config.get("warmup_timeout_seconds", 120))
        cmd = [
            "ccr", "code", "-p", "Reply with OK only.", "--output-format", "json",
            "--permission-mode", self.config.get("permission_mode", "acceptEdits"),
            "--max-turns", str(self.config.get("max_turns", 1)),
        ]
        try:
            subprocess.run(cmd, cwd=self.config.get("dev_root", "."),
                           capture_output=True, text=True,
                           timeout=warmup_timeout, check=True)
            print("✅ [llmstack] Cache warm.")
        except Exception as exc:
            print(f"⚠️  [llmstack] Warm-up skipped after {warmup_timeout}s ({exc}).")

    def is_healthy(self):
        return self.dflash.is_healthy() and self.headroom.is_healthy()

    def restart(self):
        print("♻️  [llmstack] Restarting services...")
        self.dflash.restart()
        self.headroom.restart()

    def stop(self):
        self._stop = True
        self.headroom.stop()
        self.dflash.stop()

    def should_stop(self):
        return self._stop
