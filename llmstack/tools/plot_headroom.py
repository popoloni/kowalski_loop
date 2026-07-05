#!/usr/bin/env python3
"""Generate aggregate and per-session charts from headroom_traffic.jsonl.

Outputs (into docs/img/headroom/):
  1. savings_prompt.png     - savings vs prompt size, with a binned median trend
  2. savings_progress.png   - savings by session progress quartile
  3. savings_hist.png       - distribution of savings percent
  4. transforms_impact.png  - mean savings by transform family
  5. sessions/headroom_session_*.png - one composite per work session
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "llmstack_config.json"
IMG = ROOT / "docs" / "img" / "headroom"
SESSION_IMG = IMG / "sessions"

SESSION_GAP_MINUTES = 60
SESSION_MIN_CALLS = 5
PROMPT_THRESHOLD = 5000
PROGRESS_BINS = [0.0, 0.25, 0.5, 0.75, 1.0]
PROMPT_BINS = [0, 5000, 10000, 20000, 30000, 40000, 50000, 60000, 80000, 120000, 200000]


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


def _prepare_frame(log_path: Path) -> pd.DataFrame:
    df = pd.read_json(log_path, lines=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    df["input_tokens_original"] = pd.to_numeric(df["input_tokens_original"], errors="coerce")
    df["input_tokens_optimized"] = pd.to_numeric(df["input_tokens_optimized"], errors="coerce")
    df["tokens_saved"] = pd.to_numeric(df["tokens_saved"], errors="coerce").fillna(0)
    df["savings_percent"] = pd.to_numeric(df["savings_percent"], errors="coerce").fillna(0)
    df["cache_hit"] = df["cache_hit"].fillna(False).astype(bool)
    df["transforms_applied"] = df["transforms_applied"].apply(lambda value: value if isinstance(value, list) else [])

    gap_minutes = df["timestamp"].diff().dt.total_seconds().div(60)
    df["session_id"] = gap_minutes.ge(SESSION_GAP_MINUTES).fillna(True).cumsum().astype(int)
    session_starts = df.groupby("session_id")["timestamp"].transform("min")
    df["session_label"] = (
        "h"
        + df["session_id"].astype(str).str.zfill(2)
        + "_"
        + session_starts.dt.strftime("%Y%m%d_%H%M")
    )
    df["turn_in_session"] = df.groupby("session_id").cumcount() + 1
    df["session_size"] = df.groupby("session_id")["request_id"].transform("size")
    df["session_progress"] = df["turn_in_session"] / df["session_size"]
    df["prompt_bin"] = pd.cut(df["input_tokens_original"], PROMPT_BINS, include_lowest=True, right=False)
    df["progress_bin"] = pd.cut(df["session_progress"], PROGRESS_BINS, include_lowest=True)
    return df


def _stats(series: pd.Series) -> str:
    series = series.dropna()
    if series.empty:
        return "n=0"
    return f"n={len(series)} median={series.median():.2f}% p90={series.quantile(0.9):.2f}% max={series.max():.2f}%"


def _plot_savings_vs_prompt(ax, df: pd.DataFrame) -> bool:
    big = df[df["input_tokens_original"] >= PROMPT_THRESHOLD].copy()
    if big.empty:
        ax.text(0.5, 0.5, "No prompt-sized calls found", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return False

    colors = np.where(big["cache_hit"], "#2e8b57", "#c1121f")
    ax.scatter(
        big["input_tokens_original"],
        big["savings_percent"],
        s=12,
        alpha=0.18,
        c=colors,
        linewidths=0,
    )

    grouped = (
        big.groupby("prompt_bin", observed=False)["savings_percent"]
        .median()
        .dropna()
    )
    if not grouped.empty:
        xs = np.array([interval.mid for interval in grouped.index])
        ax.plot(xs, grouped.values, color="#1f6feb", lw=2.2, marker="o", label="binned median")

    ax.set_xscale("log")
    ax.set_xlabel("Input tokens (log scale)")
    ax.set_ylabel("Savings percent")
    ax.set_title("Headroom savings rises with prompt size")
    ax.axhline(0.0, color="#666666", lw=1, ls=":")
    ax.axhline(20.0, color="#d97706", lw=1, ls=":")
    ax.text(big["input_tokens_original"].max(), 20.0, " 20%", va="bottom", ha="right", color="#d97706", fontsize=9)
    ax.grid(True, which="both", ls="--", alpha=0.25)
    ax.legend(loc="upper left", framealpha=0.9)
    return True


def _plot_savings_by_progress(ax, df: pd.DataFrame) -> bool:
    grouped = df.groupby("progress_bin", observed=False)["savings_percent"].agg(["mean", "median", "size"])
    grouped = grouped.dropna(how="all")
    if grouped.empty:
        ax.text(0.5, 0.5, "No sessions found", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return False

    labels = [str(interval).replace("(", "").replace(")", "").replace(",", "-") for interval in grouped.index]
    x = np.arange(len(grouped))
    ax.bar(x, grouped["mean"], color="#1f6feb", alpha=0.82, label="mean savings")
    ax.plot(x, grouped["median"], color="#d97706", marker="o", lw=1.8, label="median savings")
    for idx, n in enumerate(grouped["size"]):
        ax.text(idx, grouped["mean"].iloc[idx] + 0.4, f"n={int(n)}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Savings percent")
    ax.set_title("Savings improves as the session matures")
    ax.grid(True, axis="y", ls="--", alpha=0.25)
    ax.legend(loc="upper left", framealpha=0.9)
    return True


def _plot_savings_hist(ax, df: pd.DataFrame) -> bool:
    values = df["savings_percent"].dropna()
    if values.empty:
        ax.text(0.5, 0.5, "No savings values found", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return False

    buckets = [
        (-0.1, 0.0, "0"),
        (0.0, 1.0, "0-1"),
        (1.0, 5.0, "1-5"),
        (5.0, 10.0, "5-10"),
        (10.0, 20.0, "10-20"),
        (20.0, 30.0, "20-30"),
        (30.0, 50.0, "30-50"),
    ]
    counts = []
    labels = []
    for low, high, label in buckets:
        if label == "0":
            mask = values.abs() < 0.05
        else:
            mask = (values >= low) & (values < high)
        counts.append(int(mask.sum()))
        labels.append(label)

    ax.bar(labels, counts, color="#3b82f6", alpha=0.85)
    for idx, count in enumerate(counts):
        ax.text(idx, count + max(counts) * 0.01 + 1, str(count), ha="center", va="bottom", fontsize=8)
    ax.set_ylabel("Number of requests")
    ax.set_xlabel("Savings percent bucket")
    ax.set_title("Most requests save little; the useful tail starts near 20%")
    ax.grid(True, axis="y", ls="--", alpha=0.25)
    return True


def _plot_transform_impact(ax, df: pd.DataFrame) -> bool:
    exploded = df[["savings_percent", "transforms_applied"]].explode("transforms_applied")
    exploded = exploded.dropna(subset=["transforms_applied"])
    if exploded.empty:
        ax.text(0.5, 0.5, "No transforms found", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return False

    summary = (
        exploded.groupby("transforms_applied")
        .agg(n=("savings_percent", "size"), mean_savings=("savings_percent", "mean"))
        .sort_values("n", ascending=False)
        .head(12)
        .sort_values("mean_savings")
    )
    if summary.empty:
        ax.text(0.5, 0.5, "No transform summary available", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return False

    ax.barh(summary.index, summary["mean_savings"], color="#10b981", alpha=0.85)
    for idx, (name, row) in enumerate(summary.iterrows()):
        ax.text(row["mean_savings"] + 0.3, idx, f"n={int(row['n'])}", va="center", fontsize=8)
    ax.set_xlabel("Mean savings percent")
    ax.set_title("Which transforms carry the highest compression pay-off")
    ax.grid(True, axis="x", ls="--", alpha=0.25)
    return True


def _render_aggregate(df: pd.DataFrame) -> None:
    IMG.mkdir(parents=True, exist_ok=True)
    all_values = df["savings_percent"].dropna()
    weighted_saved = float(df["tokens_saved"].sum())
    weighted_original = float(df["input_tokens_original"].sum())
    weighted_pct = weighted_saved / weighted_original * 100 if weighted_original else 0.0

    fig, ax = plt.subplots(figsize=(9.5, 5.5))
    _plot_savings_vs_prompt(ax, df)
    fig.tight_layout()
    fig.savefig(IMG / "savings_prompt.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.8, 5.2))
    _plot_savings_by_progress(ax, df)
    fig.tight_layout()
    fig.savefig(IMG / "savings_progress.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.8, 5.2))
    _plot_savings_hist(ax, df)
    fig.tight_layout()
    fig.savefig(IMG / "savings_hist.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    _plot_transform_impact(ax, df)
    fig.tight_layout()
    fig.savefig(IMG / "transforms_impact.png", dpi=140)
    plt.close(fig)

    print("Headroom charts written to", str(IMG))
    print("  requests         :", len(df))
    print("  sessions         :", df["session_id"].nunique())
    print("  weighted savings :", f"{weighted_pct:.2f}%")
    print("  savings percent  :", _stats(all_values))
    print("  zero-share       :", f"{(df['tokens_saved'].abs() < 0.5).mean() * 100:.1f}%")
    print("  >=20% share      :", f"{(df['savings_percent'] >= 20).mean() * 100:.1f}%")
    print("  prompt median    :", f"{df['input_tokens_original'].median():.0f} tokens")


def _render_sessions(df: pd.DataFrame) -> None:
    SESSION_IMG.mkdir(parents=True, exist_ok=True)
    created = 0

    for session_id, session in df.groupby("session_id", sort=True):
        session = session.reset_index(drop=True)
        if len(session) < SESSION_MIN_CALLS:
            continue

        label = session["session_label"].iat[0]
        model = ", ".join(sorted({str(v) for v in session["model"].dropna() if str(v).strip()})) or "unknown"
        fig, axes = plt.subplots(2, 1, figsize=(11.5, 8.0), sharex=True)
        fig.suptitle(
            f"Headroom session {label} | model={model} | calls={len(session)} | "
            f"{session['timestamp'].min():%Y-%m-%d %H:%M} → {session['timestamp'].max():%H:%M}",
            fontsize=12,
        )

        ax = axes[0]
        ax.plot(session["turn_in_session"], session["input_tokens_original"], color="#1f6feb", lw=1.8, label="input tokens")
        hit = session[session["cache_hit"]]
        miss = session[~session["cache_hit"]]
        if not hit.empty:
            ax.scatter(hit["turn_in_session"], hit["input_tokens_original"], s=16, color="#2e8b57", alpha=0.75, label="cache hit")
        if not miss.empty:
            ax.scatter(miss["turn_in_session"], miss["input_tokens_original"], s=24, color="#c1121f", alpha=0.85, marker="x", label="cache miss")
        ax.set_ylabel("Prompt size (tokens)")
        ax.set_title("Prompt size grows as the session matures")
        ax.grid(True, ls="--", alpha=0.25)
        ax.legend(loc="upper left", framealpha=0.9)

        ax2 = axes[1]
        ax2.plot(session["turn_in_session"], session["savings_percent"], color="#d97706", lw=1.8, label="savings percent")
        if not hit.empty:
            ax2.scatter(hit["turn_in_session"], hit["savings_percent"], s=16, color="#2e8b57", alpha=0.75, label="cache hit")
        if not miss.empty:
            ax2.scatter(miss["turn_in_session"], miss["savings_percent"], s=24, color="#c1121f", alpha=0.85, marker="x", label="cache miss")
        ax2.axhline(20.0, color="#d97706", ls=":", lw=1.2)
        ax2.text(session["turn_in_session"].max(), 20.0, " 20%", va="bottom", ha="right", color="#d97706", fontsize=9)
        ax2.set_xlabel("Turn within session")
        ax2.set_ylabel("Savings percent")
        ax2.set_title("Savings rises as the context accumulates")
        ax2.grid(True, ls="--", alpha=0.25)
        ax2.legend(loc="upper left", framealpha=0.9)

        fig.tight_layout(rect=(0, 0, 1, 0.95))
        fig.savefig(SESSION_IMG / f"headroom_session_{label}.png", dpi=140)
        plt.close(fig)
        created += 1

        print(
            "  session",
            session_id,
            label,
            f"calls={len(session)}",
            f"weighted_savings={session['tokens_saved'].sum() / session['input_tokens_original'].sum() * 100:.2f}%",
            f"mean_savings={session['savings_percent'].mean():.2f}%",
        )

    print("Per-session charts written to", str(SESSION_IMG), f"({created} sessions)")


def main() -> None:
    log_path = _resolve_headroom_log()
    if not log_path.exists():
        raise FileNotFoundError(f"Headroom traffic log not found at {log_path}")

    df = _prepare_frame(log_path)
    _render_aggregate(df)
    _render_sessions(df)


if __name__ == "__main__":
    main()