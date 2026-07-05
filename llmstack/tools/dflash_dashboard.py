import csv
import json
import os
import re
import time
import urllib.request
from collections import deque

import psutil
from llmstack.config import DEFAULT_CONFIG, apply_runtime_network_defaults
from llmstack.services.inference_probe import detect_running_model
from rich.align import Align
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

CONFIG_PATH = "llmstack_config.json"
START_AT_END = True
RECENT_KEEP = 12
DECODE_BAR_CAP = 8192

CSV_HEADER = [
    "backend",
    "served_target",
    "timestamp",
    "req",
    "prompt_tokens",
    "cached_tokens",
    "cache_hit_pct",
    "prefill_time_s",
    "decode_tokens",
    "decode_tps",
    "decode_time_s",
    "total_time_s",
    "accept_pct",
    "prefill_real_tps",
    "mlx_active_gb",
    "mlx_peak_gb",
]

RE_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

# DFlash patterns
RE_DF_CACHE = re.compile(r"\[dflash\]\s+prefix cache hit\s+(\d+)/(\d+)\s+tokens")
RE_DF_PREFILL = re.compile(r"\[dflash\]\s+prefill:\s+(\d+)/(\d+)\s+tokens\s+\|\s+([\d.]+)s")
RE_DF_PROG = re.compile(
    r"\[dflash\]\s+(?P<tps>[\d.]+)\s+tok/s\s+\|\s+(?P<acc>[\d.]+)%\s+accepted\s+\|\s+"
    r"(?P<tok>\d+)\s+tokens\s+\|\s+(?P<tot>[\d.]+)s\s+\|\s+prompt:\s+(?P<prompt>\d+)"
)
RE_DF_END = re.compile(
    r"\[dflash\]\s+decode\s+(?P<tps>[\d.]+)\s+tok/s\b.*?prefill real\s+(?P<real>[\d.]+)\s+tok/s"
    r".*?(?P<acc>[\d.]+)%\s+accepted\s+\|\s+(?P<tok>\d+)\s+tokens\s+\|\s+(?P<tot>[\d.]+)s\s+\|"
    r"\s+prompt:\s+(?P<prompt>\d+)"
)
RE_DF_MEM = re.compile(
    r"req#(?P<req>\d+)\s+mlx_active=(?P<act>[\d.]+)\s+mlx_cache=(?P<cache>[\d.]+)\s+"
    r"mlx_peak=(?P<peak>[\d.]+)\s+rss_now=(?P<rss>[\d.]+)"
)

# TurboQuant / mlx_lm.server patterns
RE_TQ_PREFILL = re.compile(r"Prompt processing progress:\s+(\d+)/(\d+)")
RE_TQ_POST = re.compile(r'"POST /v1/chat/completions HTTP/1\.1" 200')
RE_TQ_CACHE = re.compile(r"Prompt Cache:\s+(\d+)\s+sequences,\s+([\d.]+)\s+GB")


def _bar(frac, width=22):
    frac = max(0.0, min(1.0, frac))
    n = int(frac * width)
    return "█" * n + "░" * (width - n)


def _fmt(v, nd=1):
    if v is None or v == "":
        return "N/A"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _parse_ts(line):
    m = RE_TS.match(line)
    return m.group(1) if m else ""


def _load_runtime_config(config_path=CONFIG_PATH):
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(config_path):
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg.update(json.load(f))
        except (OSError, json.JSONDecodeError):
            cfg = dict(DEFAULT_CONFIG)

    apply_runtime_network_defaults(cfg)

    base_dir = os.path.dirname(os.path.abspath(config_path))
    log_dir = cfg.get("log_dir", "logs")
    log_dir = log_dir if os.path.isabs(log_dir) else os.path.normpath(os.path.join(base_dir, log_dir))

    def resolve(key, filename):
        value = cfg.get(key, os.path.join(log_dir, filename))
        return value if os.path.isabs(value) else os.path.normpath(os.path.join(base_dir, value))

    active_name = cfg.get("active_model") or "dflash-qwen27b"
    active_target = None
    active_type = None
    models = cfg.get("models")
    if not isinstance(models, dict):
        models = {}
    model_cfg = models.get(active_name)
    if isinstance(model_cfg, dict):
        active_target = model_cfg.get("target")
        active_type = model_cfg.get("type")

    return {
        "log_file": resolve("dflash_log", "dflash_server.log"),
        "headroom_log": resolve("headroom_traffic_log", "headroom_traffic.jsonl"),
        "timings_csv": resolve("timings_csv", "dflash_timings.csv"),
        "active_model_name": active_name,
        "active_target": active_target,
        "active_type": active_type,
        "inference_health_url": cfg["inference_health_url"],
        "headroom_health_url": cfg["headroom_health_url"],
        "inference_port": cfg["inference_port"],
    }
def detect_active_backend(cfg):
    probe = detect_running_model(port=cfg.get("inference_port", DEFAULT_CONFIG["inference_port"]), health_url=cfg["inference_health_url"], timeout=1.0, expected_target=cfg.get("active_target"))
    served = probe.get("model_id")
    backend = probe.get("backend_name")
    confidence = probe.get("confidence", "low")

    if backend not in ("turboquant", "dflash", "mlx") and cfg.get("active_type") in ("turboquant", "dflash", "mlx"):
        backend = cfg["active_type"]
        confidence = "medium"
    elif backend not in ("turboquant", "dflash", "mlx"):
        backend = "unknown"
        confidence = "low"

    active_target = cfg.get("active_target")
    mismatch = bool(served and active_target and served != active_target)

    return {
        "backend_name": backend,
        "active_model_name": cfg.get("active_model_name") or "n/a",
        "active_target": active_target,
        "served_target": served,
        "confidence": confidence,
        "mismatch": mismatch,
    }


class BaseInferenceParser:
    name = "unknown"

    def on_backend_switch(self, monitor):
        pass

    def parse_line(self, monitor, line):
        raise NotImplementedError


class DFlashParser(BaseInferenceParser):
    name = "dflash"

    def parse_line(self, monitor, line):
        ts = _parse_ts(line)
        if "[dflash]" in line:
            monitor.last_log_wall = time.time()

        m = RE_DF_CACHE.search(line)
        if m:
            monitor.cached = int(m.group(1))
            monitor.prompt = int(m.group(2))
            monitor.pf_cur, monitor.pf_total, monitor.pf_time = 0, max(monitor.prompt, 1), 0.0
            monitor.phase = "PREFILLING"
            return

        m = RE_DF_PREFILL.search(line)
        if m:
            monitor.pf_cur = int(m.group(1))
            monitor.pf_total = max(int(m.group(2)), 1)
            monitor.pf_time = float(m.group(3))
            monitor.phase = "DECODING" if monitor.pf_cur >= monitor.pf_total else "PREFILLING"
            return

        if "tok/s" in line and "accepted" in line and "decode " not in line:
            m = RE_DF_PROG.search(line)
            if m:
                monitor.dec_tps = float(m.group("tps"))
                monitor.dec_acc = float(m.group("acc"))
                monitor.dec_tok = int(m.group("tok"))
                monitor.prompt = int(m.group("prompt"))
                monitor.dec_time = monitor.dec_tok / monitor.dec_tps if monitor.dec_tps else 0.0
                monitor.phase = "DECODING"
            return

        m = RE_DF_END.search(line)
        if m:
            tps = float(m.group("tps"))
            tok = int(m.group("tok"))
            tot = float(m.group("tot"))
            prompt = int(m.group("prompt"))
            real = float(m.group("real"))
            dec_time = tok / tps if tps else 0.0
            pf_time = monitor.pf_time if monitor.pf_time > 0 else max(tot - dec_time, 0.0)
            if monitor.pending:
                monitor.commit(monitor.pending)
            monitor.pending = {
                "backend": self.name,
                "served_target": monitor.runtime.get("served_target"),
                "timestamp": ts or "",
                "prompt_tokens": prompt,
                "cached_tokens": monitor.cached,
                "cache_hit_pct": round(100 * monitor.cached / prompt, 1) if prompt else None,
                "prefill_time_s": round(pf_time, 1),
                "decode_tokens": tok,
                "decode_tps": tps,
                "decode_time_s": round(dec_time, 1),
                "total_time_s": round(tot, 1),
                "accept_pct": round(float(m.group("acc")), 1),
                "prefill_real_tps": real,
            }
            monitor.phase = "IDLE"
            monitor.dec_tok, monitor.dec_tps, monitor.dec_time = tok, tps, dec_time
            monitor.pf_time = 0.0
            monitor.cached = 0
            return

        m = RE_DF_MEM.search(line)
        if m:
            monitor.mlx_active = m.group("act")
            monitor.mlx_cache = m.group("cache")
            monitor.rss_now = m.group("rss")
            if monitor.pending:
                monitor.pending["req"] = int(m.group("req"))
                monitor.pending["mlx_active_gb"] = float(m.group("act"))
                monitor.pending["mlx_peak_gb"] = float(m.group("peak"))
                monitor.commit(monitor.pending)
                monitor.pending = None
            return


class TurboQuantParser(BaseInferenceParser):
    def __init__(self, backend_name="turboquant"):
        self.name = backend_name
        self.req_counter = 0
        self.req_start_wall = None
        self.req_ts = ""
        self.inflight = False
        self.post_queue = 0
        self.post_ts = ""

    def on_backend_switch(self, monitor):
        self.req_start_wall = None
        self.req_ts = ""
        self.inflight = False
        self.post_queue = 0
        self.post_ts = ""
        monitor.pending = None
        monitor.mlx_active = "N/A"
        monitor.mlx_cache = "N/A"
        monitor.rss_now = "N/A"

    def _commit_request(self, monitor, ts_hint=""):
        now = time.time()
        self.req_counter += 1
        elapsed = (now - self.req_start_wall) if self.req_start_wall else 0.0
        rec = {
            "backend": self.name,
            "served_target": monitor.runtime.get("served_target"),
            "timestamp": self.req_ts or self.post_ts or ts_hint or "",
            "req": self.req_counter,
            "prompt_tokens": monitor.pf_total if monitor.pf_total > 1 else monitor.prompt,
            "cached_tokens": None,
            "cache_hit_pct": None,
            "prefill_time_s": round(elapsed, 1) if elapsed else None,
            "decode_tokens": None,
            "decode_tps": None,
            "decode_time_s": None,
            "total_time_s": round(elapsed, 1) if elapsed else None,
            "accept_pct": None,
            "prefill_real_tps": None,
            "mlx_active_gb": None,
            "mlx_peak_gb": None,
        }
        monitor.commit(rec)
        monitor.phase = "IDLE"
        monitor.dec_tok = 0
        monitor.dec_tps = 0.0
        monitor.dec_acc = 0.0
        monitor.dec_time = 0.0
        monitor.pf_cur = 0
        monitor.pf_total = 1
        monitor.pf_time = 0.0
        monitor.prompt = 0
        self.req_start_wall = None
        self.req_ts = ""
        self.inflight = False
        if self.post_queue > 0:
            self.post_queue -= 1
        self.post_ts = ""

    def parse_line(self, monitor, line):
        ts = _parse_ts(line)

        m = RE_TQ_CACHE.search(line)
        if m:
            monitor.mlx_cache = m.group(2)

        m = RE_TQ_PREFILL.search(line)
        if m:
            cur = int(m.group(1))
            total = max(int(m.group(2)), 1)
            now = time.time()
            if cur == 0 or self.req_start_wall is None:
                self.req_start_wall = now
                self.req_ts = ts or ""
                self.inflight = True
            monitor.last_log_wall = now
            monitor.cached = 0
            monitor.prompt = total
            monitor.pf_cur = cur
            monitor.pf_total = total
            monitor.pf_time = (now - self.req_start_wall) if self.req_start_wall else 0.0
            monitor.phase = "DECODING" if cur >= total else "PREFILLING"
            if self.post_queue > 0 and cur >= total:
                self._commit_request(monitor, ts)
            return

        if RE_TQ_POST.search(line):
            monitor.last_log_wall = time.time()
            self.post_queue += 1
            self.post_ts = ts or self.post_ts
            if self.inflight and self.post_queue > 0 and monitor.pf_total > 1 and monitor.pf_cur >= monitor.pf_total:
                self._commit_request(monitor, ts)
            return


class Monitor:
    def __init__(self):
        self.status = "OFFLINE"
        self.inference_status = "[bold red]OFFLINE[/bold red]"
        self.headroom_status = "[bold red]OFFLINE[/bold red]"
        self.last_hb = 0.0

        self.cfg = _load_runtime_config(CONFIG_PATH)
        self.log_file = self.cfg["log_file"]
        self.headroom_log = self.cfg["headroom_log"]
        self.csv_file = self.cfg["timings_csv"]

        self.runtime = detect_active_backend(self.cfg)

        self._buf = ""
        self._fpos = os.path.getsize(self.log_file) if (START_AT_END and os.path.exists(self.log_file)) else 0

        self._hr_buf = ""
        self._hr_fpos = os.path.getsize(self.headroom_log) if (START_AT_END and os.path.exists(self.headroom_log)) else 0

        self.hr_recent = deque(maxlen=RECENT_KEEP)
        self.hr_count = 0
        self.hr_in_orig = 0
        self.hr_in_opt = 0
        self.hr_out = 0
        self.hr_saved = 0
        self.hr_cache_hits = 0
        self.hr_compressed = 0

        self.phase = "IDLE"
        self.prompt = 0
        self.cached = 0
        self.pf_cur = 0
        self.pf_total = 1
        self.pf_time = 0.0
        self.dec_tok = 0
        self.dec_tps = 0.0
        self.dec_acc = 0.0
        self.dec_time = 0.0
        self.last_log_wall = 0.0

        self.mlx_active = "N/A"
        self.mlx_cache = "N/A"
        self.rss_now = "N/A"

        self.pending = None
        self.recent = deque(maxlen=RECENT_KEEP)
        self.total_calls = 0

        self.parser = self._make_parser(self.runtime["backend_name"])

        new = (not os.path.exists(self.csv_file)) or os.path.getsize(self.csv_file) == 0
        os.makedirs(os.path.dirname(self.csv_file), exist_ok=True)
        self.csv_fp = open(self.csv_file, "a", newline="")
        self.csv_w = csv.writer(self.csv_fp)
        if new:
            self.csv_w.writerow(CSV_HEADER)
            self.csv_fp.flush()

    def _make_parser(self, backend_name):
        if backend_name in ("turboquant", "mlx"):
            return TurboQuantParser(backend_name)
        return DFlashParser()

    def refresh_runtime_context(self):
        self.cfg = _load_runtime_config(CONFIG_PATH)
        self.runtime = detect_active_backend(self.cfg)

        if self.cfg["log_file"] != self.log_file:
            self.log_file = self.cfg["log_file"]
            self._fpos = os.path.getsize(self.log_file) if os.path.exists(self.log_file) else 0
            self._buf = ""
        if self.cfg["headroom_log"] != self.headroom_log:
            self.headroom_log = self.cfg["headroom_log"]
            self._hr_fpos = os.path.getsize(self.headroom_log) if os.path.exists(self.headroom_log) else 0
            self._hr_buf = ""

        if self.parser.name != self.runtime["backend_name"]:
            self.parser = self._make_parser(self.runtime["backend_name"])
            self.parser.on_backend_switch(self)

    def heartbeat(self):
        now = time.time()
        if now - self.last_hb < 2.0:
            return
        self.last_hb = now
        self.refresh_runtime_context()

        inference_ok = False
        headroom_ok = False
        try:
            inference_ok = urllib.request.urlopen(self.cfg["inference_health_url"], timeout=1).getcode() == 200
        except Exception:
            inference_ok = False

        try:
            headroom_ok = urllib.request.urlopen(self.cfg["headroom_health_url"], timeout=1).getcode() == 200
        except Exception:
            headroom_ok = False

        self.inference_status = "[bold green]ONLINE[/bold green]" if inference_ok else "[bold red]OFFLINE[/bold red]"
        self.headroom_status = "[bold green]ONLINE[/bold green]" if headroom_ok else "[bold red]OFFLINE[/bold red]"

        if inference_ok and headroom_ok:
            self.status = "[bold green]ONLINE & HEALTHY[/bold green]"
        elif inference_ok or headroom_ok:
            self.status = "[bold yellow]DEGRADED[/bold yellow]"
        else:
            self.status = "[bold red]OFFLINE / UNREACHABLE[/bold red]"

    def read_new_lines(self):
        if not os.path.exists(self.log_file):
            return []
        size = os.path.getsize(self.log_file)
        if size < self._fpos:
            self._fpos, self._buf = 0, ""
        with open(self.log_file, "r", errors="ignore") as f:
            f.seek(self._fpos)
            data = f.read()
            self._fpos = f.tell()
        self._buf += data
        parts = self._buf.split("\n")
        self._buf = parts.pop()
        return parts

    def ingest(self):
        for line in self.read_new_lines():
            if not line:
                continue
            if "GET /v1/models" in line:
                continue
            self.parser.parse_line(self, line)

    def commit(self, rec):
        if "backend" not in rec:
            rec["backend"] = self.runtime.get("backend_name")
        if "served_target" not in rec:
            rec["served_target"] = self.runtime.get("served_target")
        row = [rec.get(k, "") for k in CSV_HEADER]
        self.csv_w.writerow(row)
        self.csv_fp.flush()
        self.recent.appendleft(rec)
        self.total_calls += 1

    def read_new_hr(self):
        if not os.path.exists(self.headroom_log):
            return []
        size = os.path.getsize(self.headroom_log)
        if size < self._hr_fpos:
            self._hr_fpos, self._hr_buf = 0, ""
        with open(self.headroom_log, "r", errors="ignore") as f:
            f.seek(self._hr_fpos)
            data = f.read()
            self._hr_fpos = f.tell()
        self._hr_buf += data
        parts = self._hr_buf.split("\n")
        self._hr_buf = parts.pop()
        return parts

    def ingest_headroom(self):
        for line in self.read_new_hr():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            self.hr_count += 1
            self.hr_in_orig += int(rec.get("input_tokens_original") or 0)
            self.hr_in_opt += int(rec.get("input_tokens_optimized") or 0)
            self.hr_out += int(rec.get("output_tokens") or 0)
            self.hr_saved += int(rec.get("tokens_saved") or 0)
            if rec.get("cache_hit"):
                self.hr_cache_hits += 1
            if int(rec.get("tokens_saved") or 0) > 0:
                self.hr_compressed += 1
            self.hr_recent.appendleft(rec)

    def panel_hardware(self):
        t = Table(show_header=False, expand=True, box=None)
        t.add_column("k", style="yellow", no_wrap=True)
        t.add_column("v", justify="left")
        cpu = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        ru, rt = vm.used / 1024**3, vm.total / 1024**3
        t.add_row("CPU:", f"{_bar(cpu/100, 16)} {cpu:.0f}%")
        t.add_row("RAM:", f"{_bar(ru/rt, 16)} {ru:.1f}/{rt:.1f} GB")
        t.add_row("", "")
        t.add_row("MLX active:", f"{_fmt(self.mlx_active)} GB" if self.mlx_active != "N/A" else "N/A")
        t.add_row("MLX cache:", f"{_fmt(self.mlx_cache)} GB" if self.mlx_cache != "N/A" else "N/A")
        t.add_row("RSS:", f"{_fmt(self.rss_now)} GB" if self.rss_now != "N/A" else "N/A")
        return Panel(t, title="[bold]Hardware[/bold]", border_style="cyan")

    def panel_current(self):
        c = {"IDLE": "bold green", "PREFILLING": "bold yellow blink", "DECODING": "bold cyan blink"}.get(
            self.phase, "white"
        )
        ago = ""
        if self.last_log_wall:
            ago = f"  [dim](+{time.time()-self.last_log_wall:.0f}s)[/dim]"
        cache_pct = (100 * self.cached / self.prompt) if self.prompt else 0

        t = Table(show_header=False, expand=True, box=None)
        t.add_column("k", style="yellow", no_wrap=True)
        t.add_column("v", justify="left")
        t.add_row("Backend:", self.runtime.get("backend_name", "unknown"))
        t.add_row("Phase:", f"[{c}]{self.phase}[/{c}]{ago}")
        t.add_row("Prompt:", f"{self.prompt} tok   [dim]cache {cache_pct:.0f}%[/dim]" if self.prompt else "N/A")

        t.add_row("", "")
        pf_frac = self.pf_cur / self.pf_total if self.pf_total else 0
        pf_style = "yellow" if self.phase == "PREFILLING" else "dim"
        t.add_row("Prefill:", f"[{pf_style}]{_bar(pf_frac)}[/{pf_style}] {pf_frac*100:4.0f}%")
        t.add_row("", f"[dim]{self.pf_cur}/{self.pf_total} tok · {_fmt(self.pf_time)}s[/dim]")

        t.add_row("", "")
        if self.runtime.get("backend_name") == "dflash":
            dec_frac = self.dec_tok / DECODE_BAR_CAP if DECODE_BAR_CAP else 0
            dec_style = "cyan" if self.phase == "DECODING" else "dim"
            t.add_row("Decode:", f"[{dec_style}]{_bar(dec_frac)}[/{dec_style}] {self.dec_tok} tok")
            t.add_row("", f"[dim]{self.dec_time:.1f}s · {self.dec_tps:.1f} tok/s · {self.dec_acc:.0f}% acc[/dim]")
        else:
            t.add_row("Decode:", "[dim]N/A (not provided by MLX server logs)[/dim]")

        if self.phase == "IDLE" and self.recent:
            r = self.recent[0]
            t.add_row("", "")
            t.add_row(
                "Last call:",
                f"[green]pf {_fmt(r.get('prefill_time_s'))}s · tot {_fmt(r.get('total_time_s'))}s"
                f" · dec {_fmt(r.get('decode_tokens'))}[/green]",
            )

        return Panel(t, title="[bold]Current Call[/bold]", border_style="yellow")

    def panel_hr_summary(self):
        t = Table(show_header=False, expand=True, box=None)
        t.add_column("k", style="magenta", no_wrap=True)
        t.add_column("v", justify="right")
        pct = (100 * self.hr_saved / self.hr_in_orig) if self.hr_in_orig else 0.0
        chr_ = (100 * self.hr_cache_hits / self.hr_count) if self.hr_count else 0.0
        t.add_row("Status:", self.headroom_status)
        t.add_row("Requests:", f"{self.hr_count}")
        t.add_row("In orig:", f"{self.hr_in_orig:,}")
        t.add_row("In sent:", f"{self.hr_in_opt:,}")
        t.add_row("Saved:", f"[green]{self.hr_saved:,} ({pct:.1f}%)[/green]")
        t.add_row("Output:", f"{self.hr_out:,}")
        t.add_row("Compressed:", f"{self.hr_compressed}/{self.hr_count}")
        t.add_row("HR cache hit:", f"{chr_:.0f}%")
        return Panel(t, title="[bold]🗜️ Headroom[/bold]", border_style="magenta")

    def panel_hr_requests(self):
        t = Table(expand=True, box=None, header_style="bold white")
        t.add_column("time", justify="left")
        t.add_column("in→sent", justify="right")
        t.add_column("saved", justify="right", style="green")
        t.add_column("%", justify="right", style="green")
        t.add_column("out", justify="right", style="cyan")
        t.add_column("transform", justify="left", style="dim")
        t.add_column("hit", justify="center")
        for rec in self.hr_recent:
            ts = str(rec.get("timestamp", ""))[11:19]
            xf = ",".join(s.replace("router:", "") for s in (rec.get("transforms_applied") or [])) or "—"
            if len(xf) > 24:
                xf = xf[:23] + "…"
            t.add_row(
                ts,
                f"{rec.get('input_tokens_original', 0)}→{rec.get('input_tokens_optimized', 0)}",
                str(rec.get("tokens_saved", 0)),
                f"{float(rec.get('savings_percent', 0)):.1f}",
                str(rec.get("output_tokens", 0)),
                xf,
                "✓" if rec.get("cache_hit") else "·",
            )
        return Panel(t, title="[bold]Headroom Requests[/bold]", border_style="magenta")

    def panel_recent(self):
        if self.runtime.get("backend_name") == "dflash":
            t = Table(expand=True, box=None, header_style="bold white")
            for col, just, style in [
                ("#", "right", "dim"),
                ("time", "left", None),
                ("prompt", "right", None),
                ("c%", "right", None),
                ("pf s", "right", "yellow"),
                ("dec", "right", None),
                ("t/s", "right", "cyan"),
                ("dec s", "right", "cyan"),
                ("tot s", "right", "green"),
                ("acc%", "right", None),
            ]:
                t.add_column(col, justify=just, style=style) if style else t.add_column(col, justify=just)
            for r in self.recent:
                t.add_row(
                    _fmt(r.get("req"), 0),
                    str(r.get("timestamp", ""))[-8:],
                    _fmt(r.get("prompt_tokens"), 0),
                    _fmt(r.get("cache_hit_pct")),
                    _fmt(r.get("prefill_time_s")),
                    _fmt(r.get("decode_tokens"), 0),
                    _fmt(r.get("decode_tps")),
                    _fmt(r.get("decode_time_s")),
                    _fmt(r.get("total_time_s")),
                    _fmt(r.get("accept_pct")),
                )
            title = f"[bold]Inference Completed ({self.runtime.get('backend_name')})[/bold] (logged {self.total_calls})"
            return Panel(t, title=title, border_style="white")

        t = Table(expand=True, box=None, header_style="bold white")
        t.add_column("#", justify="right", style="dim")
        t.add_column("time", justify="left")
        t.add_column("prompt", justify="right")
        t.add_column("pf s", justify="right", style="yellow")
        t.add_column("tot s", justify="right", style="green")
        t.add_column("dec", justify="right")
        for r in self.recent:
            t.add_row(
                _fmt(r.get("req"), 0),
                str(r.get("timestamp", ""))[-8:],
                _fmt(r.get("prompt_tokens"), 0),
                _fmt(r.get("prefill_time_s")),
                _fmt(r.get("total_time_s")),
                _fmt(r.get("decode_tokens"), 0),
            )
        title = f"[bold]Inference Completed ({self.runtime.get('backend_name')})[/bold] (logged {self.total_calls})"
        return Panel(t, title=title, border_style="white")

    def render(self):
        self.heartbeat()
        self.ingest()
        self.ingest_headroom()

        backend = self.runtime.get("backend_name", "unknown")
        served_target = self.runtime.get("served_target") or "n/a"

        header_text = (
            f"⚡ Inference Monitor   |   engine={backend}   |   inference {self.inference_status}   |   "
            f"served {served_target}   |   headroom {self.headroom_status}"
        )

        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", size=12),
            Layout(name="bottom"),
        )
        layout["main"].split_row(
            Layout(self.panel_hardware(), name="hw"),
            Layout(self.panel_current(), name="cur"),
            Layout(self.panel_hr_summary(), name="hrs"),
        )
        layout["bottom"].split_row(
            Layout(self.panel_recent(), name="inf"),
            Layout(self.panel_hr_requests(), name="hrr"),
        )
        layout["header"].update(Panel(Align.center(header_text), style="bold white on blue"))
        return layout

    def close(self):
        try:
            self.csv_fp.close()
        except Exception:
            pass


if __name__ == "__main__":
    mon = Monitor()
    try:
        with Live(mon.render(), refresh_per_second=4, screen=True) as live:
            while True:
                live.update(mon.render())
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        mon.close()
        print(f"Dashboard closed. Timings saved to {mon.csv_file}.")
