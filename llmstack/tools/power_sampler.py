"""Power sampling utilities for TCO analysis on Apple Silicon Macs.

Provides:
- is_laptop(): detect if this Mac has a battery (laptop vs desktop)
- get_battery_info(): battery percent, plugged status, secs left
- sample_powermetrics(): collect and parse Apple powermetrics output
- write_power_sample(): append measurements and diagnostic status
- compute_session_energy(): aggregate energy/cost from timing + power data
"""
import csv
import os
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import psutil

# Apple Silicon powermetrics normally reports values such as
# "CPU Power: 336 mW" and "GPU Power: 197 mW".  Accept both mW and W,
# with or without a colon, and normalize all values to watts.
_POWER_VALUE = r"([\d.]+)\s*(mW|W)\b"
RE_GPU_POWER = re.compile(r"GPU Power\s*:?\s*" + _POWER_VALUE, re.IGNORECASE)
RE_CPU_POWER = re.compile(r"CPU Power\s*:?\s*" + _POWER_VALUE, re.IGNORECASE)
RE_TOTAL_POWER = re.compile(
    r"(?:System Power|Package Power|Combined Power(?:\s*\([^\n]*\))?)\s*:?\s*" + _POWER_VALUE,
    re.IGNORECASE,
)
RE_THERMAL = re.compile(
    r"(?:Thermal(?: pressure| state)?|Current pressure level)\s*:?\s*([^\r\n]+)",
    re.IGNORECASE,
)
RE_FAN_RPM = re.compile(r"Fan Speed\s*:?\s*([\d.]+)\s*RPM", re.IGNORECASE)
RE_GPU_ACTIVE = re.compile(
    r"GPU (?:Active|active residency)\s*:?\s*([\d.]+)%", re.IGNORECASE
)
RE_SOC_TEMP = re.compile(r"SoC Temperature\s*:?\s*([\d.]+)\s*(?:°?C)", re.IGNORECASE)
RE_CPU_TEMP = re.compile(r"CPU Temperature\s*:?\s*([\d.]+)\s*(?:°?C)", re.IGNORECASE)

_LAST_POWER_ERROR = ""


def _set_power_error(message: str) -> None:
    global _LAST_POWER_ERROR
    _LAST_POWER_ERROR = message.strip()


def get_last_power_error() -> str:
    """Return the diagnostic message from the latest sampling attempt."""
    return _LAST_POWER_ERROR


def is_laptop() -> bool:
    """Return True if this Mac has a battery."""
    try:
        bat = psutil.sensors_battery()
        if bat is None:
            return False
        if hasattr(psutil, "POWER_TIME_UNLIMITED"):
            return bat.secsleft != psutil.POWER_TIME_UNLIMITED
        return bat.percent is not None
    except Exception:
        return False


def get_battery_info() -> dict | None:
    """Return battery information, or None on desktop Macs."""
    if not is_laptop():
        return None
    try:
        bat = psutil.sensors_battery()
        if bat is None:
            return None
        return {
            "percent": bat.percent,
            "plugged": bool(bat.power_plugged),
            "secsleft": bat.secsleft,
        }
    except Exception:
        return None


def _run_powermetrics(samples: int = 1, interval_ms: int = 1000) -> str | None:
    """Run powermetrics non-interactively and return stdout.

    powermetrics expects the sample interval in milliseconds and the Apple
    Silicon sampler names are cpu_power, gpu_power and thermal.  The command
    requires elevated privileges on normal macOS installations.  We use
    ``sudo -n`` so the full-screen dashboard never hangs waiting for a hidden
    password prompt.  Run ``sudo -v`` in the same terminal before launching
    the dashboard, or configure an appropriately restricted sudoers rule.
    """
    _set_power_error("")

    if platform.system() != "Darwin":
        _set_power_error("powermetrics is available only on macOS")
        return None

    executable = "/usr/bin/powermetrics"
    if not os.path.exists(executable):
        _set_power_error(f"{executable} not found")
        return None

    samples = max(1, int(samples))
    interval_ms = max(100, int(interval_ms))
    base_cmd = [
        executable,
        "--samplers",
        "cpu_power,gpu_power,thermal",
        "-i",
        str(interval_ms),
        "-n",
        str(samples),
    ]

    commands = [base_cmd] if os.geteuid() == 0 else [["/usr/bin/sudo", "-n"] + base_cmd, base_cmd]
    failures: list[str] = []
    timeout_s = max(15.0, samples * interval_ms / 1000.0 + 10.0)

    for cmd in commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            failures.append(f"{' '.join(cmd)}: timed out")
            continue
        except OSError as exc:
            failures.append(f"{' '.join(cmd)}: {exc}")
            continue

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout

        detail = (result.stderr or result.stdout or "no output").strip().replace("\n", " | ")
        failures.append(f"{' '.join(cmd)}: exit {result.returncode}: {detail}")

    _set_power_error("; ".join(failures))
    return None


def _watts(match: re.Match | None) -> float | None:
    if match is None:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    return value / 1000.0 if unit == "mw" else value


def parse_powermetrics(output: str) -> dict:
    """Parse powermetrics text and normalize all power readings to watts."""
    result = {
        "gpu_power_w": _watts(RE_GPU_POWER.search(output)),
        "cpu_power_w": _watts(RE_CPU_POWER.search(output)),
        "total_power_w": _watts(RE_TOTAL_POWER.search(output)),
        "thermal_state": None,
        "fan_rpm": None,
        "gpu_active_pct": None,
        "soc_temp_c": None,
        "cpu_temp_c": None,
    }

    scalar_patterns = {
        "thermal_state": RE_THERMAL,
        "fan_rpm": RE_FAN_RPM,
        "gpu_active_pct": RE_GPU_ACTIVE,
        "soc_temp_c": RE_SOC_TEMP,
        "cpu_temp_c": RE_CPU_TEMP,
    }
    for key, pattern in scalar_patterns.items():
        match = pattern.search(output)
        if not match:
            continue
        value = match.group(1).strip()
        if key == "thermal_state":
            result[key] = value
        else:
            try:
                result[key] = float(value)
            except ValueError:
                pass

    return result


def sample_powermetrics() -> dict:
    """Take one one-second powermetrics sample.

    Returns an empty dict on failure.  Call get_last_power_error() for the
    reason; failures are no longer silently discarded by the dashboard.
    """
    output = _run_powermetrics(samples=1, interval_ms=1000)
    if output is None:
        return {}

    sample = parse_powermetrics(output)
    if not any(value is not None for value in sample.values()):
        _set_power_error("powermetrics ran, but no supported fields were found in its output")
        return {}

    _set_power_error("")
    return sample


def get_powermetrics_csv_path(log_dir: str = "logs") -> Path:
    """Return logs/power_metrics.csv (plural)."""
    base = Path(log_dir)
    base.mkdir(parents=True, exist_ok=True)
    return base / "power_metrics.csv"


def _csv_value(value):
    return "" if value is None else value


def write_power_sample(
    log_dir: str = "logs",
    sample: dict | None = None,
    error: str = "",
) -> None:
    """Append a sample or a diagnostic failure row to power_metrics.csv."""
    csv_path = get_powermetrics_csv_path(log_dir)
    header = [
        "timestamp",
        "gpu_power_w",
        "cpu_power_w",
        "total_power_w",
        "thermal_state",
        "fan_rpm",
        "gpu_active_pct",
        "soc_temp_c",
        "cpu_temp_c",
        "status",
        "error",
    ]

    sample = sample or {}
    has_data = any(value is not None for value in sample.values())
    row = [
        datetime.now(timezone.utc).isoformat(),
        _csv_value(sample.get("gpu_power_w")),
        _csv_value(sample.get("cpu_power_w")),
        _csv_value(sample.get("total_power_w")),
        _csv_value(sample.get("thermal_state")),
        _csv_value(sample.get("fan_rpm")),
        _csv_value(sample.get("gpu_active_pct")),
        _csv_value(sample.get("soc_temp_c")),
        _csv_value(sample.get("cpu_temp_c")),
        "ok" if has_data else "error",
        "" if has_data else (error or get_last_power_error() or "unknown sampling failure"),
    ]

    new_file = (not csv_path.exists()) or csv_path.stat().st_size == 0
    if not new_file:
        # Upgrade an older/header-only file without discarding measurements.
        with open(csv_path, "r", newline="", encoding="utf-8") as file_obj:
            existing_rows = list(csv.reader(file_obj))
        existing_header = existing_rows[0] if existing_rows else []
        if existing_header != header:
            old_index = {name: idx for idx, name in enumerate(existing_header)}
            migrated_rows = []
            for old_row in existing_rows[1:]:
                migrated_rows.append([
                    old_row[old_index[name]] if name in old_index and old_index[name] < len(old_row) else ""
                    for name in header
                ])
            with open(csv_path, "w", newline="", encoding="utf-8") as file_obj:
                writer = csv.writer(file_obj)
                writer.writerow(header)
                writer.writerows(migrated_rows)
            new_file = False

    with open(csv_path, "a", newline="", encoding="utf-8") as file_obj:
        writer = csv.writer(file_obj)
        if new_file:
            writer.writerow(header)
        writer.writerow(row)
        file_obj.flush()


def compute_session_energy(
    timings_csv: str,
    power_csv: str | None = None,
    hardware: dict | None = None,
) -> dict:
    """Aggregate energy and cost data from timings + power CSVs.

    Returns a dict suitable for session_summary.jsonl:
    {
        "total_prompt_tokens": int,
        "total_decode_tokens": int,
        "total_energy_kwh": float,
        "energy_cost_usd": float,
        "cloud_equivalent_usd": float,
        "savings_usd": float,
        "thermal_throttle_minutes": float,
        "peak_gpu_power_w": float,
        "avg_gpu_power_w": float,
    }
    """
    import pandas as pd

    if hardware is None:
        hardware = {}

    # Read timings CSV
    timings_path = Path(timings_csv)
    if not timings_path.exists():
        return {}

    df = pd.read_csv(timings_path)

    total_prompt = int(df["prompt_tokens"].sum()) if "prompt_tokens" in df.columns else 0
    total_decode = int(df["decode_tokens"].fillna(0).sum()) if "decode_tokens" in df.columns else 0

    # Read power CSV if available
    total_energy_kwh = 0.0
    peak_gpu_power = 0.0
    avg_gpu_power = 0.0
    thermal_throttle_minutes = 0.0

    if power_csv and Path(power_csv).exists():
        power_df = pd.read_csv(power_csv)

        if "gpu_power_w" in power_df.columns:
            gpu_powers = power_df["gpu_power_w"].dropna()
            if not gpu_powers.empty:
                avg_gpu_power = float(gpu_powers.mean())
                peak_gpu_power = float(gpu_powers.max())

        # Prefer the combined/system measurement. If unavailable, sum CPU and
        # GPU power; fall back to GPU-only for compatibility with old files.
        power_series = None
        if "total_power_w" in power_df.columns and power_df["total_power_w"].notna().any():
            power_series = power_df["total_power_w"].dropna()
        elif {"cpu_power_w", "gpu_power_w"}.issubset(power_df.columns):
            power_series = power_df[["cpu_power_w", "gpu_power_w"]].fillna(0).sum(axis=1)
        elif "gpu_power_w" in power_df.columns:
            power_series = power_df["gpu_power_w"].dropna()

        if power_series is not None and not power_series.empty:
            # Each row is approximately one second. W*s / 3,600,000 = kWh.
            total_watt_seconds = float(power_series.sum())
            total_energy_kwh = total_watt_seconds / 3_600_000.0

        # Count thermal throttle time (one row is approximately one second).
        if "thermal_state" in power_df.columns:
            throttle_rows = power_df[power_df["thermal_state"].str.contains("thrott", case=False, na=False)]
            thermal_throttle_minutes = float(len(throttle_rows)) / 60.0

    # Compute costs
    grid_cost_kwh = float(hardware.get("avg_grid_cost_kwh", 0.15))
    energy_cost_usd = total_energy_kwh * grid_cost_kwh

    # Cloud API pricing estimates (per 1M tokens, approximate frontier pricing)
    cloud_cost_per_m_prompt = 2.50  # e.g., Claude Pro
    cloud_cost_per_m_decode = 10.0  # e.g., Claude Pro

    total_prompt_m = total_prompt / 1_000_000
    total_decode_m = total_decode / 1_000_000
    cloud_equivalent_usd = (total_prompt_m * cloud_cost_per_m_prompt) + (total_decode_m * cloud_cost_per_m_decode)

    savings_usd = cloud_equivalent_usd - energy_cost_usd

    return {
        "total_prompt_tokens": total_prompt,
        "total_decode_tokens": total_decode,
        "total_energy_kwh": round(total_energy_kwh, 6),
        "energy_cost_usd": round(energy_cost_usd, 4),
        "cloud_equivalent_usd": round(cloud_equivalent_usd, 2),
        "savings_usd": round(savings_usd, 2),
        "thermal_throttle_minutes": round(thermal_throttle_minutes, 1),
        "peak_gpu_power_w": round(peak_gpu_power, 1),
        "avg_gpu_power_w": round(avg_gpu_power, 1),
    }


def compute_break_even_volume(hardware: dict) -> float:
    """Compute the monthly token volume at which local inference breaks even vs cloud.

    Returns break-even in tokens per month.
    """
    purchase_price = float(hardware.get("purchase_price_usd", 0))
    life_years = float(hardware.get("expected_life_years", 5))
    grid_cost_kwh = float(hardware.get("avg_grid_cost_kwh", 0.15))

    if purchase_price == 0 or life_years == 0:
        return float("inf")

    # Amortized monthly hardware cost
    monthly_amortization = purchase_price / (life_years * 12)

    # Average energy cost per 1M tokens (from measured data, default estimate)
    avg_energy_per_m_tokens_kwh = 0.05  # ~50 Wh per 1M tokens (estimate)
    energy_cost_per_m_tokens = avg_energy_per_m_tokens_kwh * grid_cost_kwh

    # Cloud cost per 1M tokens (blended prompt+decode)
    cloud_cost_per_m_tokens = 5.0  # rough average

    cost_savings_per_m_tokens = cloud_cost_per_m_tokens - energy_cost_per_m_tokens

    if cost_savings_per_m_tokens <= 0:
        return float("inf")

    break_even_tokens = (monthly_amortization / cost_savings_per_m_tokens) * 1_000_000
    return break_even_tokens
