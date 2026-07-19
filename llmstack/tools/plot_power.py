#!/usr/bin/env python3
"""Generate power-metrics charts from logs/power_metrics.csv.

Outputs (into docs/img/):
  1. power_over_time.png  — GPU, CPU, total power over time (line chart)
  2. power_histogram.png  — distribution of GPU / CPU / total power (histograms)
  3. power_summary.png    — aggregate stats table + box plots per channel
  4. sessions/session_*.png — one composite chart per 30-min session window
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "llmstack_config.json"
IMG = ROOT / "docs" / "img"
SESSION_IMG = IMG / "sessions"

# Columns we expect (some may be empty on certain Macs)
POWER_COLS = ["gpu_power_w", "cpu_power_w", "total_power_w"]
TEMP_COLS = ["soc_temp_c", "cpu_temp_c"]
FAN_COL = "fan_rpm"
SESSION_GAP_MINUTES = 30


def _resolve_power_csv() -> Path:
    """Resolve the power_metrics.csv path from config or default."""
    csv_path = str(ROOT / "logs" / "power_metrics.csv")
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            csv_path = cfg.get("power_metrics_csv", csv_path)
        except json.JSONDecodeError:
            pass
    resolved = Path(csv_path)
    if not resolved.is_absolute():
        resolved = (ROOT / resolved).resolve()
    return resolved


def _prepare_frame(csv_path: Path) -> pd.DataFrame:
    """Load CSV, parse timestamps, compute session IDs."""
    df = pd.read_csv(csv_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    # Session breaks: gaps > SESSION_GAP_MINUTES start a new session
    gap_minutes = df["timestamp"].diff().dt.total_seconds().div(60)
    df["session_id"] = gap_minutes.ge(SESSION_GAP_MINUTES).fillna(True).cumsum().astype(int)
    session_starts = df.groupby("session_id")["timestamp"].transform("min")
    df["session_label"] = (
        "s"
        + df["session_id"].astype(str).str.zfill(2)
        + "_"
        + session_starts.dt.strftime("%Y%m%d_%H%M")
    )
    return df


def _valid_power(df: pd.DataFrame) -> list[str]:
    """Return power columns that actually have data."""
    return [c for c in POWER_COLS if df[c].notna().any()]


# ── Chart 1: Power over time ──────────────────────────────────────────────

def plot_power_over_time(df: pd.DataFrame, out: Path):
    """Line chart: GPU, CPU, total power vs wall-clock."""
    valid = _valid_power(df)
    if not valid:
        _empty_chart(out, "No power data available")
        return

    fig, ax = plt.subplots(figsize=(14, 5))
    colors = {"gpu_power_w": "#e74c3c", "cpu_power_w": "#3498db", "total_power_w": "#2ecc71"}
    labels = {"gpu_power_w": "GPU Power", "cpu_power_w": "CPU Power", "total_power_w": "Total Power"}

    for col in valid:
        ax.plot(
            df["timestamp"],
            df[col],
            color=colors.get(col, "#888"),
            linewidth=0.8,
            alpha=0.85,
            label=labels.get(col, col),
        )

    ax.set_xlabel("Time")
    ax.set_ylabel("Power (W)")
    ax.set_title("Power Metrics Over Time")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.25)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ── Chart 2: Histograms ───────────────────────────────────────────────────

def plot_power_histograms(df: pd.DataFrame, out: Path):
    """Side-by-side histograms for each power channel."""
    valid = _valid_power(df)
    if not valid:
        _empty_chart(out, "No power data available")
        return

    n = len(valid)
    fig, axes = plt.subplots(1, n, figsize=(5 * n, 4))
    if n == 1:
        axes = [axes]

    colors = {"gpu_power_w": "#e74c3c", "cpu_power_w": "#3498db", "total_power_w": "#2ecc71"}
    labels = {"gpu_power_w": "GPU Power", "cpu_power_w": "CPU Power", "total_power_w": "Total Power"}

    for ax, col in zip(axes, valid):
        data = df[col].dropna()
        ax.hist(data, bins=80, color=colors.get(col, "#888"), alpha=0.75, edgecolor="none")
        ax.axvline(data.median(), color="black", ls="--", lw=1.5, label=f"median={data.median():.3f} W")
        ax.set_xlabel("Power (W)")
        ax.set_title(labels.get(col, col))
        ax.legend()
        ax.grid(True, alpha=0.25)

    fig.suptitle("Power Distribution")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ── Chart 3: Summary stats + box plots ────────────────────────────────────

def plot_power_summary(df: pd.DataFrame, out: Path):
    """Box plots per channel + aggregate stats table."""
    valid = _valid_power(df)
    if not valid:
        _empty_chart(out, "No power data available")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # Box plot
    data_for_box = [df[c].dropna().values for c in valid if df[c].notna().any()]
    if data_for_box:
        bp = ax1.boxplot(
            data_for_box,
            tick_labels=[labels.get(c, c) for c in valid if df[c].notna().any()],
            patch_artist=True,
            medianprops=dict(color="black"),
        )
        box_colors = {"gpu_power_w": "#e74c3c", "cpu_power_w": "#3498db", "total_power_w": "#2ecc71"}
        for patch, col in zip(bp["boxes"], valid):
            patch.set_facecolor(box_colors.get(col, "#888"))
            patch.set_alpha(0.7)
        ax1.set_ylabel("Power (W)")
        ax1.set_title("Power by Channel (Box Plot)")
        ax1.grid(True, alpha=0.25, axis="y")

    # Stats table
    ax2.axis("off")
    stats_lines = [
        f"{'Channel':<16} {'N':>5} {'Min':>8} {'Median':>8} {'Max':>8} {'Mean':>8}",
        "-" * 65,
    ]
    for col in valid:
        s = df[col].dropna()
        if len(s) > 0:
            stats_lines.append(
                f"{labels.get(col, col):<16} {len(s):>5} {s.min():>8.3f} {s.median():>8.3f} {s.max():>8.3f} {s.mean():>8.3f}"
            )
    ax2.text(0.05, 0.5, "\n".join(stats_lines), fontsize=10, family="monospace",
             verticalalignment="center", transform=ax2.transAxes)
    ax2.set_title("Aggregate Statistics")

    fig.suptitle("Power Metrics Summary")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ── Chart 4: Per-session composites ────────────────────────────────────────

def plot_session_charts(df: pd.DataFrame, out_dir: Path):
    """One composite chart per session window."""
    out_dir.mkdir(parents=True, exist_ok=True)
    valid = _valid_power(df)
    if not valid:
        return

    for sid, sdf in df.groupby("session_id"):
        if len(sdf) < 2:
            continue
        fig, axes = plt.subplots(2, 1, figsize=(14, 6), gridspec_kw={"height_ratios": [3, 1]})

        # Power over time
        colors = {"gpu_power_w": "#e74c3c", "cpu_power_w": "#3498db", "total_power_w": "#2ecc71"}
        for col in valid:
            axes[0].plot(sdf["timestamp"], sdf[col], color=colors.get(col, "#888"),
                         linewidth=0.7, alpha=0.8, label=labels.get(col, col))
        axes[0].set_ylabel("Power (W)")
        axes[0].set_title(f"Session {sdf['session_label'].iloc[0]}  (n={len(sdf)} samples)")
        axes[0].legend(loc="upper left", fontsize=8)
        axes[0].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        axes[0].grid(True, alpha=0.25)
        fig.autofmt_xdate()

        # Status bar
        status_colors = {"ok": "#2ecc71", "error": "#e74c3c"}
        status_map = df["status"].map(status_colors).fillna("#888")
        axes[1].hlines(0.5, sdf["timestamp"].min(), sdf["timestamp"].max(),
                       color=status_map.values, alpha=0.7)
        axes[1].set_ylim(-0.2, 1.2)
        axes[1].set_yticks([0.5])
        axes[1].set_yticklabels(["status"])
        axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        axes[1].grid(True, alpha=0.25)

        fig.savefig(out_dir / f"session_{sdf['session_label'].iloc[0]}.png",
                    dpi=150, bbox_inches="tight")
        plt.close(fig)


# ── Helpers ───────────────────────────────────────────────────────────────

labels = {"gpu_power_w": "GPU Power", "cpu_power_w": "CPU Power", "total_power_w": "Total Power"}


def _empty_chart(out: Path, message: str):
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes, fontsize=14)
    ax.set_axis_off()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    csv_path = _resolve_power_csv()
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found.")
        return

    IMG.mkdir(parents=True, exist_ok=True)
    SESSION_IMG.mkdir(parents=True, exist_ok=True)

    df = _prepare_frame(csv_path)
    valid = _valid_power(df)

    if not valid:
        print("No power columns with data found. Nothing to plot.")
        return

    print(f"Loaded {len(df)} samples from {df['timestamp'].min()} to {df['timestamp'].max()}")
    print(f"Power columns with data: {valid}")

    # 1. Power over time (full run)
    plot_power_over_time(df, IMG / "power_over_time.png")
    print("  → docs/img/power_over_time.png")

    # 2. Histograms
    plot_power_histograms(df, IMG / "power_histogram.png")
    print("  → docs/img/power_histogram.png")

    # 3. Summary
    plot_power_summary(df, IMG / "power_summary.png")
    print("  → docs/img/power_summary.png")

    # 4. Per-session composites
    plot_session_charts(df, SESSION_IMG)
    n_sessions = df["session_id"].nunique()
    print(f"  → docs/img/sessions/ ({n_sessions} session charts)")

    print("Done.")


if __name__ == "__main__":
    main()
