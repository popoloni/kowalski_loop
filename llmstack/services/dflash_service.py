import json
import os
import signal
import subprocess
import time
import urllib.request

from .manager import ServiceManager
from .inference_probe import served_model_id


class DFlashService(ServiceManager):
    def __init__(self, backend, log_file="dflash_server.log"):
        super().__init__("dflash")
        self.backend = backend
        self.cmd = backend.build_serve_cmd()
        self.health_url = backend.health_url()
        self.port = backend.serve_port()
        self.log_file = log_file
        self.server_process = None
        self._stop = False

    def _ping(self, timeout=3):
        try:
            return urllib.request.urlopen(self.health_url, timeout=timeout).getcode() == 200
        except Exception:
            return False

    def served_model_id(self, timeout=3):
        """Return the model id currently served on the configured inference port via /v1/models, or None."""
        return served_model_id(
            port=self.port,
            health_url=self.health_url,
            timeout=timeout,
            expected_target=self.backend.model_target(),
        )

    def _free_port(self, port=None):
        """Kill any process holding the inference port so a different backend can bind it."""
        port = self.port if port is None else port
        try:
            out = subprocess.check_output(["lsof", "-ti", f"tcp:{port}"], text=True).strip()
        except Exception:
            out = ""
        pids = [p for p in out.splitlines() if p.strip().isdigit()]
        if not pids:
            return
        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
        time.sleep(3)
        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        time.sleep(1)

    def ensure_running(self):
        self._stop = False
        if self.server_process and self.server_process.poll() is None:
            return
        expected = self.backend.model_target()
        served = self.served_model_id()
        if served is not None:
            if served == expected:
                print(f"✅ [Kowalski] Inference server already serving '{served}' on :{self.port}; reusing.")
                return
            print(f"♻️  [Kowalski] Port {self.port} serves '{served}' but active model is '{expected}'; replacing...")
            self._free_port()
        print(f"🚀 [Kowalski] Starting inference server for model '{self.backend.model_name}'...")
        with open(self.log_file, "a") as log:
            self.server_process = subprocess.Popen(
                self.cmd, stdout=log, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        self.wait_for_health()

    def wait_for_health(self, boot_timeout=600):
        print("⏳ [Kowalski] Waiting for model to load into RAM...")
        start = time.time()
        while not self._stop:
            if self._ping():
                print("✅ [Kowalski] Server online and healthy.")
                return True
            if self.server_process and self.server_process.poll() is not None:
                print("❌ [Kowalski] Server died during boot. Restarting...")
                self.server_process = None
                return self.start()
            if time.time() - start > boot_timeout:
                print("❌ [Kowalski] Server boot timed out.")
                return False
            time.sleep(5)

    def restart(self):
        print("♻️  [Kowalski] Hard-restarting DFlash...")
        self.stop()
        time.sleep(3)
        self._stop = False
        self.start()

    def start(self):
        self._stop = False
        self.ensure_running()

    def watchdog_loop(self, poll_seconds=5, fail_threshold=3):
        interval = max(1.0, float(poll_seconds or 5))
        fail_threshold = max(1, int(fail_threshold or 3))
        max_backoff = max(interval, 60.0)
        restart_backoff = interval
        health_fails = 0
        print(
            f"🛡️  [Kowalski] DFlash watchdog active "
            f"(poll={interval:.1f}s, fail-threshold={fail_threshold})."
        )
        self._stop = False
        while not self._stop:
            process_died = bool(self.server_process and self.server_process.poll() is not None)
            healthy = self._ping()

            if process_died:
                should_restart = True
                reason = "process exited"
            else:
                if healthy:
                    health_fails = 0
                    should_restart = False
                else:
                    health_fails += 1
                    should_restart = health_fails >= fail_threshold
                    reason = f"health check failed {health_fails}/{fail_threshold}"

            if should_restart:
                print(f"🔥 [Kowalski] DFlash unhealthy ({reason}) — restarting...")
                try:
                    self.restart()
                    health_fails = 0
                    restart_backoff = interval
                except Exception as exc:
                    print(f"⚠️  [Kowalski] DFlash restart failed: {exc}")
                    print(f"⏳ [Kowalski] Backing off {restart_backoff:.1f}s before next restart attempt.")
                    time.sleep(restart_backoff)
                    restart_backoff = min(max_backoff, restart_backoff * 2.0)
                    continue
            time.sleep(interval)

    def stop(self):
        self._stop = True
        if self.server_process:
            try:
                os.killpg(os.getpgid(self.server_process.pid), signal.SIGTERM)
                self.server_process.wait(timeout=15)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(os.getpgid(self.server_process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.server_process = None

    def health(self) -> bool:
        return self._ping()

    def is_healthy(self) -> bool:
        return self.health()
