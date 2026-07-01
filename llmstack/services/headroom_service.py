import argparse
import os
import signal
import subprocess
import time
import urllib.request

from .manager import ServiceManager


class HeadroomService(ServiceManager):
    def __init__(
        self,
        headroom_executable=None,
        port=8789,
        upstream_url="http://127.0.0.1:8787",
        log_file="headroom.log",
        traffic_log="headroom_traffic.jsonl",
    ):
        super().__init__("headroom")
        self.headroom_executable = headroom_executable or os.path.expanduser("~/headroom-env/bin/headroom")
        self.port = port
        self.upstream_url = upstream_url
        self.log_file = log_file
        self.traffic_log = traffic_log
        self.server_process = None
        self._stop = False

    def _health_url(self):
        return f"http://127.0.0.1:{self.port}/health"

    def _ping(self, timeout=3):
        try:
            return urllib.request.urlopen(self._health_url(), timeout=timeout).getcode() == 200
        except Exception:
            return False

    def _build_env(self):
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env["OPENAI_TARGET_API_URL"] = self.upstream_url
        env["OPENAI_API_KEY"] = "dflash-local"
        env["HEADROOM_TELEMETRY"] = "off"
        return env

    def _kill_existing_proxy(self):
        try:
            subprocess.run(["pkill", "-f", "headroom proxy"], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def ensure_running(self):
        if self.server_process and self.server_process.poll() is None:
            return
        print("🗜️  [Ralph] Starting Headroom proxy...")
        self._kill_existing_proxy()
        with open(self.log_file, "a") as log:
            self.server_process = subprocess.Popen(
                [self.headroom_executable, "proxy", "--port", str(self.port), "--code-aware",
                 "--no-telemetry", "--log-file", self.traffic_log],
                stdout=log,
                stderr=subprocess.STDOUT,
                env=self._build_env(),
                preexec_fn=os.setsid,
            )
        self.wait_for_health()

    def wait_for_health(self, boot_timeout=60):
        print("⏳ [Ralph] Waiting for Headroom proxy to become healthy...")
        start = time.time()
        while not self._stop:
            if self._ping():
                print("✅ [Ralph] Headroom proxy online and healthy.")
                return True
            if self.server_process and self.server_process.poll() is not None:
                print("❌ [Ralph] Headroom proxy exited during startup.")
                self.server_process = None
                return False
            if time.time() - start > boot_timeout:
                print("❌ [Ralph] Headroom proxy startup timed out.")
                return False
            time.sleep(2)
        return False

    def restart(self):
        print("♻️  [Ralph] Restarting Headroom proxy...")
        self.stop()
        time.sleep(1)
        self.ensure_running()

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
        else:
            self._kill_existing_proxy()

    def health(self) -> bool:
        return self._ping()

    def is_healthy(self) -> bool:
        return self.health()


def main():
    parser = argparse.ArgumentParser(description="Headroom proxy service helper")
    parser.add_argument("command", nargs="?", default="start", choices=["start", "restart", "stop", "health"])
    parser.add_argument("--executable", default=None,
                        help="Path to the headroom executable (default: ~/headroom-env/bin/headroom)")
    parser.add_argument("--port", type=int, default=8789)
    parser.add_argument("--upstream", default="http://127.0.0.1:8787")
    parser.add_argument("--log-file", default="headroom.log")
    parser.add_argument("--traffic-log", default="headroom_traffic.jsonl")
    args = parser.parse_args()

    service = HeadroomService(
        headroom_executable=args.executable,
        port=args.port,
        upstream_url=args.upstream,
        log_file=args.log_file,
        traffic_log=args.traffic_log,
    )

    if args.command == "start":
        service.ensure_running()
    elif args.command == "restart":
        service.restart()
    elif args.command == "stop":
        service.stop()
    elif args.command == "health":
        print("healthy" if service.health() else "unhealthy")
        return 0 if service.health() else 1


if __name__ == "__main__":
    main()
