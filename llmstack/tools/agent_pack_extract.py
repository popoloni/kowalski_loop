#!/usr/bin/env python3
"""
Extract Agent Problem Pack run data and cross-reference with server logs.

For every run found under agent-problem-pack/runs/ this module parses:
  - artifacts/headless-stdout.jsonl  → duration_ms, ttft_ms, num_turns, token usage, served model
  - artifacts/verification.txt       → pass/fail (exit_code == 0)
  - metadata.json                     → problem name, run_name

Then correlates each run's time window with:
  - logs/dflash_timings.csv          → prefill_time_s, decode_tps, mlx_peak_gb, cache_hit_pct
  - logs/headroom_traffic.jsonl      → savings_percent, optimization_latency_ms

Returns a list of RunRecord dataclasses ready for reporting.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median, mean
from typing import Optional

# ── paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_RUNS_ROOT = REPO_ROOT / "local-coding-agent-evals" / "agent-problem-pack" / "runs"
DFLASH_CSV = REPO_ROOT / "logs" / "dflash_timings.csv"
HEADROOM_JSONL = REPO_ROOT / "logs" / "headroom_traffic.jsonl"


# ── data classes ──────────────────────────────────────────────────────────────
@dataclass
class ServerMetrics:
    """Aggregated server-side metrics for one pack run time window."""
    # dflash/mlx/turboquant timings CSV
    n_timing_rows: int = 0
    prefill_times: list[float] = field(default_factory=list)
    decode_tps_list: list[float] = field(default_factory=list)
    decode_times: list[float] = field(default_factory=list)
    mlx_peaks: list[float] = field(default_factory=list)
    cache_hits: list[float] = field(default_factory=list)
    # headroom log
    n_headroom_rows: int = 0
    headroom_savings: list[float] = field(default_factory=list)
    headroom_opt_latency_ms: list[float] = field(default_factory=list)

    @property
    def prefill_median_s(self) -> Optional[float]:
        return median(self.prefill_times) if self.prefill_times else None

    @property
    def decode_tps_median(self) -> Optional[float]:
        return median(self.decode_tps_list) if self.decode_tps_list else None

    @property
    def decode_time_median_s(self) -> Optional[float]:
        return median(self.decode_times) if self.decode_times else None

    @property
    def mlx_peak_median_gb(self) -> Optional[float]:
        return median(self.mlx_peaks) if self.mlx_peaks else None

    @property
    def mlx_peak_max_gb(self) -> Optional[float]:
        return max(self.mlx_peaks) if self.mlx_peaks else None

    @property
    def cache_hit_median_pct(self) -> Optional[float]:
        return median(self.cache_hits) if self.cache_hits else None

    @property
    def headroom_savings_median_pct(self) -> Optional[float]:
        return median(self.headroom_savings) if self.headroom_savings else None

    @property
    def headroom_savings_mean_pct(self) -> Optional[float]:
        return mean(self.headroom_savings) if self.headroom_savings else None

    @property
    def headroom_opt_latency_median_ms(self) -> Optional[float]:
        return median(self.headroom_opt_latency_ms) if self.headroom_opt_latency_ms else None


@dataclass
class RunRecord:
    """One agent problem pack run with merged artifact + server metrics."""
    # identity
    run_name: str
    model_key: str           # e.g. "dflash-ornith35b-moe"
    backend: str             # "dflash" | "mlx" | "turboquant"
    problem: str             # e.g. "problem-02-shell-command-injection"
    problem_title: str
    matrix_id: str           # e.g. "20260713_003824"
    # from headless-stdout
    served_target: str       # full model path e.g. "mlx-community/Ornith-1.0-35B-4bit"
    duration_s: Optional[float]
    ttft_s: Optional[float]
    num_turns: Optional[int]
    input_tokens: Optional[int]
    cache_read_input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_cost_usd: Optional[float]
    # from verification.txt
    passed: bool
    exit_code: Optional[int]
    # time window
    end_time: Optional[datetime]   # mtime of headless-stdout.jsonl
    start_time: Optional[datetime] # end_time - duration_s
    # correlated server metrics
    server: ServerMetrics = field(default_factory=ServerMetrics)


# ── parsing helpers ────────────────────────────────────────────────────────────
_MATRIX_RE = re.compile(r"llmstack-matrix-(\d{8}_\d{6})")
_MODEL_KEY_RE = re.compile(
    r"^matrix-"                      # prefix
    r"([a-z0-9]+-[a-z0-9\-]+)"       # model_key
    r"-llmstack-matrix-\d{8}_\d{6}"  # suffix
)


def _infer_model_key(run_name: str) -> str:
    """Extract model key from run_name like 'matrix-dflash-ornith35b-moe-dflash-ornith35b-moe-llmstack-matrix-20260713_003824-02'."""
    # Remove matrix suffix and problem number
    stripped = re.sub(r"-llmstack-matrix-\d{8}_\d{6}-\d{2}$", "", run_name)
    stripped = re.sub(r"^matrix-", "", stripped)
    # The model key is repeated: "dflash-ornith35b-moe-dflash-ornith35b-moe"
    # Split and find the repeated half
    parts = stripped.split("-")
    n = len(parts)
    for half in range(2, n):
        candidate = "-".join(parts[:half])
        rest = "-".join(parts[half:])
        if candidate == rest:
            return candidate
    return stripped


def _infer_backend(model_key: str) -> str:
    if model_key.startswith("dflash"):
        return "dflash"
    if model_key.startswith("mlx"):
        return "mlx"
    if model_key.startswith("turboquant"):
        return "turboquant"
    return "unknown"


def _parse_verification(path: Path) -> tuple[bool, Optional[int]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^exit_code=(\d+)\s*$", text, re.MULTILINE)
    if not m:
        return False, None
    code = int(m.group(1))
    return code == 0, code


def _parse_headless_stdout(path: Path) -> Optional[dict]:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            if d.get("type") == "result":
                return d
        except json.JSONDecodeError:
            pass
    return None


def _dt_from_mtime(mtime: float) -> datetime:
    return datetime.fromtimestamp(mtime)


# ── discover runs ──────────────────────────────────────────────────────────────
def discover_runs(
    runs_root: Path = PACK_RUNS_ROOT,
    matrix_filter: Optional[str] = None,
) -> list[RunRecord]:
    """
    Walk runs_root and parse every run directory.

    Args:
        runs_root: Root of agent-problem-pack/runs/
        matrix_filter: Optional matrix ID to restrict to (e.g. "20260713_003824").
                       If None, all runs are included (latest per model+problem wins).
    """
    records: list[RunRecord] = []

    for problem_dir in sorted(runs_root.iterdir()):
        if not problem_dir.is_dir():
            continue
        problem = problem_dir.name

        for run_dir in sorted(problem_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            run_name = run_dir.name

            # filter by matrix id
            m = _MATRIX_RE.search(run_name)
            if m is None:
                continue  # skip non-matrix runs (smoke runs, etc.)
            matrix_id = m.group(1)
            if matrix_filter and matrix_id != matrix_filter:
                continue

            artifacts = run_dir / "artifacts"
            stdout_path = artifacts / "headless-stdout.jsonl"
            verification_path = artifacts / "verification.txt"
            metadata_path = run_dir / "metadata.json"

            model_key = _infer_model_key(run_name)
            backend = _infer_backend(model_key)

            # problem title
            problem_title = problem
            if metadata_path.exists():
                try:
                    meta = json.loads(metadata_path.read_text(encoding="utf-8"))
                    problem_title = meta.get("title", problem)
                except (json.JSONDecodeError, OSError):
                    pass

            # verification
            passed, exit_code = False, None
            if verification_path.exists():
                passed, exit_code = _parse_verification(verification_path)

            # headless stdout
            duration_s = ttft_s = None
            num_turns = input_tokens = cache_read = output_tokens = None
            total_cost_usd = None
            served_target = ""
            end_time = start_time = None

            if stdout_path.exists() and stdout_path.stat().st_size > 0:
                result = _parse_headless_stdout(stdout_path)
                if result:
                    duration_ms = result.get("duration_ms")
                    if duration_ms is not None:
                        duration_s = duration_ms / 1000.0

                    ttft_ms = result.get("ttft_ms")
                    if ttft_ms is not None:
                        ttft_s = ttft_ms / 1000.0

                    num_turns = result.get("num_turns")
                    total_cost_usd = result.get("total_cost_usd")

                    usage = result.get("usage") or {}
                    input_tokens = usage.get("input_tokens")
                    cache_read = usage.get("cache_read_input_tokens")
                    output_tokens = usage.get("output_tokens")

                    model_usage = result.get("modelUsage") or {}
                    if model_usage:
                        # key is "backend,served_target"
                        first_key = next(iter(model_usage))
                        parts = first_key.split(",", 1)
                        served_target = parts[1] if len(parts) == 2 else first_key

                mtime = stdout_path.stat().st_mtime
                end_time = _dt_from_mtime(mtime)
                if duration_s is not None:
                    start_time = end_time - timedelta(seconds=duration_s)

            records.append(
                RunRecord(
                    run_name=run_name,
                    model_key=model_key,
                    backend=backend,
                    problem=problem,
                    problem_title=problem_title,
                    matrix_id=matrix_id,
                    served_target=served_target,
                    duration_s=duration_s,
                    ttft_s=ttft_s,
                    num_turns=num_turns,
                    input_tokens=input_tokens,
                    cache_read_input_tokens=cache_read,
                    output_tokens=output_tokens,
                    total_cost_usd=total_cost_usd,
                    passed=passed,
                    exit_code=exit_code,
                    end_time=end_time,
                    start_time=start_time,
                )
            )

    return records


# ── load server logs ───────────────────────────────────────────────────────────
def load_dflash_timings(path: Path = DFLASH_CSV) -> list[dict]:
    """Load dflash_timings.csv into a list of dicts with datetime-parsed timestamps."""
    rows = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ts_str = row.get("timestamp") or ""
            try:
                row["_dt"] = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S") if ts_str else None
            except ValueError:
                row["_dt"] = None
            rows.append(row)
    return rows


def load_headroom_traffic(path: Path = HEADROOM_JSONL) -> list[dict]:
    """Load headroom_traffic.jsonl into a list of dicts with datetime-parsed timestamps."""
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                ts_str = d.get("timestamp", "")
                try:
                    # ISO format, possibly with fractional seconds
                    d["_dt"] = datetime.fromisoformat(ts_str)
                except ValueError:
                    d["_dt"] = None
                rows.append(d)
            except json.JSONDecodeError:
                pass
    return rows


# ── correlate runs with server logs ────────────────────────────────────────────
_SLACK = timedelta(seconds=30)  # extend end window slightly for async writes


def _to_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def correlate_with_server_logs(
    records: list[RunRecord],
    timing_rows: list[dict],
    headroom_rows: list[dict],
) -> None:
    """
    For each RunRecord, find matching rows in timing/headroom logs by time window
    and served_target, then populate record.server.
    """
    for rec in records:
        if rec.start_time is None or rec.end_time is None:
            continue

        start = rec.start_time
        end = rec.end_time + _SLACK
        target = rec.served_target

        # --- timings CSV ---
        sm = rec.server
        for row in timing_rows:
            dt = row.get("_dt")
            if dt is None or not (start <= dt <= end):
                continue
            if target and row.get("served_target") != target:
                continue
            sm.n_timing_rows += 1
            # prefill_time_s is the authoritative prefill metric; for mlx/turboquant
            # it equals total_time_s when no speculative decode is used
            pf = _to_float(row.get("prefill_time_s"))
            if pf is None or pf <= 0:
                pf = _to_float(row.get("total_time_s"))
            if pf is not None and pf > 0:
                sm.prefill_times.append(pf)
            dtps = _to_float(row.get("decode_tps"))
            if dtps is not None and dtps > 0:
                sm.decode_tps_list.append(dtps)
            dt2 = _to_float(row.get("decode_time_s"))
            if dt2 is not None and dt2 > 0:
                sm.decode_times.append(dt2)
            pk = _to_float(row.get("mlx_peak_gb"))
            if pk is not None and pk > 0:
                sm.mlx_peaks.append(pk)
            ch = _to_float(row.get("cache_hit_pct"))
            if ch is not None and 0.0 <= ch <= 100.0:
                sm.cache_hits.append(ch)

        # --- headroom log ---
        for row in headroom_rows:
            dt = row.get("_dt")
            if dt is None or not (start <= dt <= end):
                continue
            # headroom model field is the full served target
            if target and row.get("model") != target:
                continue
            sm.n_headroom_rows += 1
            sav = _to_float(row.get("savings_percent"))
            if sav is not None:
                sm.headroom_savings.append(sav)
            opt_lat = _to_float(row.get("optimization_latency_ms"))
            if opt_lat is not None:
                sm.headroom_opt_latency_ms.append(opt_lat)


# ── aggregate per model ────────────────────────────────────────────────────────
@dataclass
class ModelAggregate:
    model_key: str
    backend: str
    served_target: str
    n_problems: int
    n_passed: int

    duration_s_list: list[float] = field(default_factory=list)
    ttft_s_list: list[float] = field(default_factory=list)
    num_turns_list: list[int] = field(default_factory=list)
    input_tokens_list: list[int] = field(default_factory=list)
    cache_read_tokens_list: list[int] = field(default_factory=list)
    output_tokens_list: list[int] = field(default_factory=list)
    cost_usd_list: list[float] = field(default_factory=list)

    all_prefill_times: list[float] = field(default_factory=list)
    all_decode_tps: list[float] = field(default_factory=list)
    all_mlx_peaks: list[float] = field(default_factory=list)
    all_cache_hits: list[float] = field(default_factory=list)
    all_headroom_savings: list[float] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return (self.n_passed / self.n_problems * 100.0) if self.n_problems else 0.0

    @property
    def duration_median_s(self) -> Optional[float]:
        return median(self.duration_s_list) if self.duration_s_list else None

    @property
    def ttft_median_s(self) -> Optional[float]:
        return median(self.ttft_s_list) if self.ttft_s_list else None

    @property
    def turns_median(self) -> Optional[float]:
        return median(self.num_turns_list) if self.num_turns_list else None

    @property
    def input_tokens_median(self) -> Optional[float]:
        return median(self.input_tokens_list) if self.input_tokens_list else None

    @property
    def output_tokens_median(self) -> Optional[float]:
        return median(self.output_tokens_list) if self.output_tokens_list else None

    @property
    def cost_usd_total(self) -> float:
        return sum(self.cost_usd_list)

    @property
    def prefill_median_s(self) -> Optional[float]:
        return median(self.all_prefill_times) if self.all_prefill_times else None

    @property
    def decode_tps_median(self) -> Optional[float]:
        return median(self.all_decode_tps) if self.all_decode_tps else None

    @property
    def mlx_peak_median_gb(self) -> Optional[float]:
        return median(self.all_mlx_peaks) if self.all_mlx_peaks else None

    @property
    def mlx_peak_max_gb(self) -> Optional[float]:
        return max(self.all_mlx_peaks) if self.all_mlx_peaks else None

    @property
    def cache_hit_median_pct(self) -> Optional[float]:
        return median(self.all_cache_hits) if self.all_cache_hits else None

    @property
    def headroom_savings_median_pct(self) -> Optional[float]:
        return median(self.all_headroom_savings) if self.all_headroom_savings else None


def aggregate_by_model(records: list[RunRecord]) -> list[ModelAggregate]:
    agg: dict[str, ModelAggregate] = {}
    for rec in records:
        if rec.model_key not in agg:
            agg[rec.model_key] = ModelAggregate(
                model_key=rec.model_key,
                backend=rec.backend,
                served_target=rec.served_target,
                n_problems=0,
                n_passed=0,
            )
        ma = agg[rec.model_key]
        ma.n_problems += 1
        if rec.passed:
            ma.n_passed += 1
        if rec.duration_s is not None:
            ma.duration_s_list.append(rec.duration_s)
        if rec.ttft_s is not None:
            ma.ttft_s_list.append(rec.ttft_s)
        if rec.num_turns is not None:
            ma.num_turns_list.append(rec.num_turns)
        if rec.input_tokens is not None:
            ma.input_tokens_list.append(rec.input_tokens)
        if rec.cache_read_input_tokens is not None:
            ma.cache_read_tokens_list.append(rec.cache_read_input_tokens)
        if rec.output_tokens is not None:
            ma.output_tokens_list.append(rec.output_tokens)
        if rec.total_cost_usd is not None:
            ma.cost_usd_list.append(rec.total_cost_usd)
        sm = rec.server
        ma.all_prefill_times.extend(sm.prefill_times)
        ma.all_decode_tps.extend(sm.decode_tps_list)
        ma.all_mlx_peaks.extend(sm.mlx_peaks)
        ma.all_cache_hits.extend(sm.cache_hits)
        ma.all_headroom_savings.extend(sm.headroom_savings)

    return sorted(agg.values(), key=lambda x: x.model_key)


# ── public entry point ─────────────────────────────────────────────────────────
def load_all(
    matrix_filter: Optional[str] = None,
    runs_root: Path = PACK_RUNS_ROOT,
    timings_path: Path = DFLASH_CSV,
    headroom_path: Path = HEADROOM_JSONL,
) -> tuple[list[RunRecord], list[ModelAggregate]]:
    """Load, correlate, and aggregate all pack run data.

    Returns:
        (records, aggregates) where records is per-run and aggregates is per-model.
    """
    records = discover_runs(runs_root, matrix_filter=matrix_filter)
    timing_rows = load_dflash_timings(timings_path)
    headroom_rows = load_headroom_traffic(headroom_path)
    correlate_with_server_logs(records, timing_rows, headroom_rows)
    aggregates = aggregate_by_model(records)
    return records, aggregates


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dump extracted agent pack run data.")
    parser.add_argument("--matrix", help="Matrix ID filter, e.g. 20260713_003824.")
    args = parser.parse_args()

    records, aggs = load_all(matrix_filter=args.matrix)
    print(f"Loaded {len(records)} run records, {len(aggs)} model aggregates.")
    for ma in aggs:
        print(
            f"  {ma.model_key:40s} pass={ma.n_passed}/{ma.n_problems}"
            f"  dur_med={ma.duration_median_s:.0f}s"
            f"  decode_tps={ma.decode_tps_median or 'n/a'}"
            f"  mlx_peak={ma.mlx_peak_median_gb or 'n/a'}GB"
        )
