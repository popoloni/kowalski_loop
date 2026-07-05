#!/usr/bin/env python3
"""Generate a synthesis chart that connects memory, headroom, and dflash savings.

Outputs (into docs/img/savings/):
  1. savings_landscape.png - three-panel overview of the three efficiency layers
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "llmstack_config.json"
IMG = ROOT / "docs" / "img" / "savings"

HEADROOM_PROMPT_BINS = [0, 5000, 10000, 20000, 30000, 40000, 50000, 60000, 80000, 120000, 200000]
HEADROOM_PROGRESS_BINS = [0.0, 0.25, 0.5, 0.75, 1.0]
DFLASH_CACHE_BINS = [0, 50, 80, 90, 95, 99, 100]
DFLASH_UNCACHED_BINS = [-0.1, 1, 10, 100, 500, 1000, 5000, 10000, 20000, 50000]
DECODE_BINS = [0, 50, 100, 200, 400, 800, 1600, 3200, 100000]

TARGET_COLORS = {
    "mlx-community/Qwen3.6-27B-4bit": "#1f6feb",
    "mlx-community/Qwen3.6-35B-A3B-4bit": "#d97706",
    "mlx-community/gemma-4-12B-4bit": "#10b981",
    "mlx-community/gemma-4-12b-coder-fable5-composer2.5-4bit": "#8b5cf6",
}


def _resolve_headroom_log() -> Path:
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cfg = {}
        log_path = cfg.get("headroom_traffic_log", "./logs/headroom_traffic.jsonl")
    else:
        log_path = "./logs/headroom_traffic.jsonl"

    resolved = Path(log_path)
    if not resolved.is_absolute():
        resolved = (ROOT / resolved).resolve()
    return resolved


def _resolve_timings_csv() -> Path:
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cfg = {}
        csv_path = cfg.get("timings_csv", "./logs/dflash_timings.csv")
    else:
        csv_path = "./logs/dflash_timings.csv"

    resolved = Path(csv_path)
    if not resolved.is_absolute():
        resolved = (ROOT / resolved).resolve()
    return resolved


def _prepare_headroom_frame(log_path: Path) -> pd.DataFrame:
    df = pd.read_json(log_path, lines=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    df["input_tokens_original"] = pd.to_numeric(df["input_tokens_original"], errors="coerce")
    df["tokens_saved"] = pd.to_numeric(df["tokens_saved"], errors="coerce").fillna(0)
    df["savings_percent"] = pd.to_numeric(df["savings_percent"], errors="coerce").fillna(0)
    df["cache_hit"] = df["cache_hit"].fillna(False).astype(bool)
    gap_minutes = df["timestamp"].diff().dt.total_seconds().div(60)
    df["session_id"] = gap_minutes.ge(60).fillna(True).cumsum().astype(int)
    session_sizes = df.groupby("session_id")["request_id"].transform("size")
    df["turn_in_session"] = df.groupby("session_id").cumcount() + 1
    df["session_progress"] = df["turn_in_session"] / session_sizes
    df["prompt_bin"] = pd.cut(df["input_tokens_original"], HEADROOM_PROMPT_BINS, include_lowest=True, right=False)
    df["progress_bin"] = pd.cut(df["session_progress"], HEADROOM_PROGRESS_BINS, include_lowest=True)
    return df


def _prepare_dflash_frame(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df = df[df["backend"] == "dflash"].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    df = df[df["cache_hit_pct"].between(0, 100)].copy()
    df["uncached_tokens"] = df["prompt_tokens"] * (1.0 - df["cache_hit_pct"] / 100.0)
    df["cache_bucket"] = pd.cut(df["cache_hit_pct"], DFLASH_CACHE_BINS, include_lowest=True)
    df["uncached_bucket"] = pd.cut(df["uncached_tokens"], DFLASH_UNCACHED_BINS, include_lowest=True)
    return df


def _stats(series: pd.Series, suffix: str = "") -> str:
    series = series.dropna()
    if series.empty:
        return "n=0"
    return f"n={len(series)} median={series.median():.2f}{suffix} p90={series.quantile(0.9):.2f}{suffix}"


def _plot_memory_panel(ax, df: pd.DataFrame) -> None:
    palette = {
        "mlx-community/Qwen3.6-27B-4bit": "#1f6feb",
        "mlx-community/Qwen3.6-35B-A3B-4bit": "#d97706",
    }
    for target, color in palette.items():
        subset = df[df["served_target"] == target].copy()
        if subset.empty:
            continue
        ax.scatter(
            subset["prompt_tokens"],
            subset["mlx_peak_gb"],
            s=10,
            alpha=0.12,
            color=color,
            linewidths=0,
        )
        grouped = subset.groupby(pd.cut(subset["prompt_tokens"], [0, 5000, 10000, 20000, 40000, 60000, 80000, 120000], include_lowest=True), observed=False)["mlx_peak_gb"].median().dropna()
        if not grouped.empty:
            xs = np.array([interval.mid for interval in grouped.index])
            label = target.rsplit("/", 1)[-1].replace("-4bit", "")
            ax.plot(xs, grouped.values, color=color, lw=2.0, marker="o", label=label)

    ax.axhline(48.0, color="#6b7280", ls=":", lw=1.0)
    ax.axhline(52.0, color="#dc2626", ls=":", lw=1.0)
    ax.text(120000, 48.0, " 48 GB", ha="right", va="bottom", color="#6b7280", fontsize=9)
    ax.text(120000, 52.0, " 52 GB", ha="right", va="bottom", color="#dc2626", fontsize=9)
    ax.set_xscale("log")
    ax.set_xlabel("Prompt size (tokens, log scale)")
    ax.set_ylabel("MLX peak memory (GB)")
    ax.set_title("Memory climbs with prompt size and crosses the danger band on long runs")
    ax.grid(True, which="both", ls="--", alpha=0.25)
    ax.legend(loc="upper left", framealpha=0.9)


def _plot_headroom_panel(ax, df: pd.DataFrame) -> None:
    big = df[df["input_tokens_original"] >= 5000].copy()
    if big.empty:
        ax.text(0.5, 0.5, "No large Headroom calls found", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return

    colors = np.where(big["cache_hit"], "#2e8b57", "#c1121f")
    ax.scatter(big["input_tokens_original"], big["savings_percent"], s=10, alpha=0.16, c=colors, linewidths=0)
    grouped = big.groupby("prompt_bin", observed=False)["savings_percent"].median().dropna()
    if not grouped.empty:
        xs = np.array([interval.mid for interval in grouped.index])
        ax.plot(xs, grouped.values, color="#1f6feb", lw=2.0, marker="o", label="binned median")
    ax.axhline(20.0, color="#d97706", ls=":", lw=1.0)
    ax.text(big["input_tokens_original"].max(), 20.0, " 20%", ha="right", va="bottom", color="#d97706", fontsize=9)
    ax.set_xscale("log")
    ax.set_xlabel("Input tokens (log scale)")
    ax.set_ylabel("Savings percent")
    ax.set_title("Headroom savings appears only after prompts and sessions get large")
    ax.grid(True, which="both", ls="--", alpha=0.25)
    ax.legend(loc="upper left", framealpha=0.9)


def _plot_dflash_panel(ax, df: pd.DataFrame) -> None:
    if df.empty:
        ax.text(0.5, 0.5, "No clean dflash calls found", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return

    ax.scatter(df["cache_hit_pct"], df["prefill_time_s"], s=10, alpha=0.16, color="#2563eb", linewidths=0)
    grouped = df.groupby("cache_bucket", observed=False)["prefill_time_s"].median().dropna()
    if not grouped.empty:
        xs = np.array([interval.mid for interval in grouped.index])
        ax.plot(xs, grouped.values, color="#111827", lw=2.0, marker="o", label="median by cache band")
    for value, label in [(80, "80%"), (90, "90%"), (95, "95%"), (99, "99%")]:
        ax.axvline(value, color="#6b7280", ls=":", lw=0.9)
        ax.text(value, ax.get_ylim()[1], f" {label}", va="top", ha="left", fontsize=8, color="#6b7280")
    ax.axhline(1.0, color="#16a34a", ls=":", lw=1.0)
    ax.axhline(60.0, color="#dc2626", ls=":", lw=1.0)
    ax.set_yscale("log")
    ax.set_xlim(0, 100)
    ax.set_xlabel("Cache hit percentage")
    ax.set_ylabel("Prefill time (s, log scale)")
    ax.set_title("DFlash gets fast only when the reused prefix is nearly complete")
    ax.grid(True, which="both", ls="--", alpha=0.25)
    ax.legend(loc="upper right", framealpha=0.9)


def _plot_output_panel(ax, df: pd.DataFrame) -> None:
    subset = df[df["decode_time_s"].notna() & df["decode_tokens"].notna()].copy()
    if subset.empty:
        ax.text(0.5, 0.5, "No output-time rows found", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return

    for target, color in TARGET_COLORS.items():
        rows = subset[subset["served_target"] == target]
        if rows.empty:
            continue
        ax.scatter(rows["decode_tokens"], rows["decode_time_s"], s=10, alpha=0.16, color=color, linewidths=0)

    grouped = subset.groupby(pd.cut(subset["decode_tokens"], DECODE_BINS, include_lowest=True), observed=False)["decode_time_s"].median().dropna()
    if not grouped.empty:
        xs = np.array([interval.mid for interval in grouped.index])
        ax.plot(xs, grouped.values, color="#111827", lw=2.0, marker="o", label="median by output band")

    ax.set_xscale("log")
    ax.set_xlabel("Generated tokens (log scale)")
    ax.set_ylabel("Decode time (s)")
    ax.set_title("Output time follows generated length and model speed, not cache savings")
    ax.grid(True, which="both", ls="--", alpha=0.25)

    legend_items = [plt.Line2D([0], [0], marker="o", color="none", markerfacecolor=color, markersize=6, label=label.rsplit("/", 1)[-1].replace("-4bit", "")) for label, color in TARGET_COLORS.items() if not subset[subset["served_target"] == label].empty]
    if legend_items:
        legend_items.append(plt.Line2D([0], [0], color="#111827", lw=2.0, marker="o", label="median by output band"))
        ax.legend(handles=legend_items, loc="upper left", framealpha=0.9)
    else:
        ax.legend(loc="upper left", framealpha=0.9)


def _render_overview(memory_df: pd.DataFrame, headroom_df: pd.DataFrame, dflash_df: pd.DataFrame) -> None:
    IMG.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(17.6, 10.0))
    axes = axes.flatten()
    _plot_memory_panel(axes[0], memory_df)
    _plot_headroom_panel(axes[1], headroom_df)
    _plot_dflash_panel(axes[2], dflash_df)
    _plot_output_panel(axes[3], dflash_df)
    fig.suptitle("Where the stack saves time, and where it still pays the full cost", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(IMG / "savings_landscape.png", dpi=140)
    plt.close(fig)

    memory_27 = memory_df[memory_df["served_target"] == "mlx-community/Qwen3.6-27B-4bit"]
    memory_35 = memory_df[memory_df["served_target"] == "mlx-community/Qwen3.6-35B-A3B-4bit"]
    print("Savings charts written to", str(IMG))
    print("  memory 27B      :", _stats(memory_27["mlx_peak_gb"], " GB"))
    print("  memory 35B-A3B  :", _stats(memory_35["mlx_peak_gb"], " GB"))
    print("  headroom savings :", _stats(headroom_df["savings_percent"], "%"))
    print("  headroom >=20%   :", f"{(headroom_df['savings_percent'] >= 20).mean() * 100:.1f}%")
    print("  dflash prefill   :", _stats(dflash_df["prefill_time_s"], " s"))
    print("  output decode    :", _stats(dflash_df["decode_time_s"], " s"))
    print("  decode tokens    :", f"median={dflash_df['decode_tokens'].median():.0f} p90={dflash_df['decode_tokens'].quantile(0.9):.0f}")
    print("  dflash <=2s      :", f"{(dflash_df['prefill_time_s'] <= 2).mean() * 100:.1f}%")
    print("  dflash >99% cache:", f"{(dflash_df['cache_hit_pct'] >= 99).mean() * 100:.1f}%")


def main() -> None:
    headroom_log = _resolve_headroom_log()
    timings_csv = _resolve_timings_csv()
    if not headroom_log.exists():
        raise FileNotFoundError(f"Headroom traffic log not found at {headroom_log}")
    if not timings_csv.exists():
        raise FileNotFoundError(f"timings CSV not found at {timings_csv}")

    headroom_df = _prepare_headroom_frame(headroom_log)
    dflash_df = _prepare_dflash_frame(timings_csv)
    memory_df = dflash_df[dflash_df["served_target"].isin(["mlx-community/Qwen3.6-27B-4bit", "mlx-community/Qwen3.6-35B-A3B-4bit"])].copy()

    _render_overview(memory_df, headroom_df, dflash_df)


if __name__ == "__main__":
    main()