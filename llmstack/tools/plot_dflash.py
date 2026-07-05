#!/usr/bin/env python3
"""Generate aggregate and per-session charts from dflash_timings.csv.

Outputs (into docs/img/dflash/):
  1. cache_cliff.png          - prefill time vs cache hit percentage
  2. uncached_cliff.png       - prefill time vs uncached tokens
  3. cache_band_latency.png   - median prefill latency by cache-hit band
  4. session_maturity.png     - prompt growth + prefill latency in the longest run
  5. sessions/dflash_session_*.png - one composite chart per work session
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
IMG = ROOT / "docs" / "img" / "dflash"
SESSION_IMG = IMG / "sessions"

SESSION_GAP_MINUTES = 60
SESSION_MIN_CALLS = 5
PREFILL_HIT_BINS = [0, 50, 80, 90, 95, 99, 100]
UNCACHED_BINS = [-0.1, 1, 10, 100, 500, 1000, 5000, 10000, 20000, 50000]
HIST_BINS = [0, 1, 2, 5, 10, 30, 60, 120, 300, 600, 1200, 1800]


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


def _prepare_frame(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df = df[df["backend"] == "dflash"].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    # The raw cache_hit_pct field has a few parser artifacts outside [0, 100].
    df = df[df["cache_hit_pct"].between(0, 100)].copy()
    df["uncached_tokens"] = df["prompt_tokens"] * (1.0 - df["cache_hit_pct"] / 100.0)
    df["cache_bucket"] = pd.cut(df["cache_hit_pct"], PREFILL_HIT_BINS, include_lowest=True)
    df["uncached_bucket"] = pd.cut(df["uncached_tokens"], UNCACHED_BINS, include_lowest=True)

    gap_minutes = df["timestamp"].diff().dt.total_seconds().div(60)
    df["session_id"] = gap_minutes.ge(SESSION_GAP_MINUTES).fillna(True).cumsum().astype(int)
    session_starts = df.groupby("session_id")["timestamp"].transform("min")
    df["session_label"] = (
        "d"
        + df["session_id"].astype(str).str.zfill(2)
        + "_"
        + session_starts.dt.strftime("%Y%m%d_%H%M")
    )
    df["turn_in_session"] = df.groupby("session_id").cumcount() + 1
    df["session_size"] = df.groupby("session_id")["req"].transform("size")
    df["session_progress"] = df["turn_in_session"] / df["session_size"]
    return df


def _stats(series: pd.Series) -> str:
    series = series.dropna()
    if series.empty:
        return "n=0"
    return (
        f"n={len(series)} median={series.median():.2f}s "
        f"p90={series.quantile(0.9):.2f}s max={series.max():.1f}s"
    )


def _plot_cache_cliff(ax, df: pd.DataFrame) -> bool:
    if df.empty:
        ax.text(0.5, 0.5, "No dflash rows found", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return False

    colors = np.where(df["prompt_tokens"] >= 40000, "#d97706", "#1f6feb")
    ax.scatter(df["cache_hit_pct"], df["prefill_time_s"], s=12, alpha=0.22, c=colors, linewidths=0)

    medians = df.groupby("cache_bucket", observed=False)["prefill_time_s"].median().dropna()
    if not medians.empty:
        xs = np.array([interval.mid for interval in medians.index])
        ax.plot(xs, medians.values, color="#111827", lw=2.0, marker="o", label="median by band")

    ax.set_yscale("log")
    ax.set_xlim(0, 100)
    ax.set_xlabel("Cache hit percentage")
    ax.set_ylabel("Prefill time (s, log scale)")
    ax.set_title("DFlash becomes fast only when the prefix is almost fully cached")
    for value, label in [(80, "80%"), (90, "90%"), (95, "95%"), (99, "99%")]:
        ax.axvline(value, color="#6b7280", ls=":", lw=0.9)
        ax.text(value, ax.get_ylim()[1], f" {label}", va="top", ha="left", fontsize=8, color="#6b7280")
    ax.axhline(1.0, color="#16a34a", ls=":", lw=1)
    ax.axhline(60.0, color="#dc2626", ls=":", lw=1)
    ax.grid(True, which="both", ls="--", alpha=0.25)
    ax.legend(loc="upper right", framealpha=0.9)
    return True


def _plot_uncached_cliff(ax, df: pd.DataFrame) -> bool:
    if df.empty:
        ax.text(0.5, 0.5, "No dflash rows found", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return False

    ax.scatter(df["uncached_tokens"], df["prefill_time_s"], s=12, alpha=0.22, color="#2563eb", linewidths=0)
    medians = df.groupby("uncached_bucket", observed=False)["prefill_time_s"].median().dropna()
    if not medians.empty:
        xs = np.array([interval.mid for interval in medians.index])
        ax.plot(xs, medians.values, color="#111827", lw=2.0, marker="o", label="median by band")

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Uncached tokens (log scale)")
    ax.set_ylabel("Prefill time (s, log scale)")
    ax.set_title("Prefill time tracks the uncached suffix, not the total prompt alone")
    ax.grid(True, which="both", ls="--", alpha=0.25)
    ax.legend(loc="upper left", framealpha=0.9)
    return True


def _plot_cache_band_latency(ax, df: pd.DataFrame) -> bool:
    grouped = df.groupby("cache_bucket", observed=False)["prefill_time_s"].agg(["count", "mean", "median", "max"])
    grouped = grouped.dropna(how="all")
    if grouped.empty:
        ax.text(0.5, 0.5, "No cache bands available", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return False

    labels = [str(interval).replace("(", "").replace(")", "") for interval in grouped.index]
    x = np.arange(len(grouped))
    ax.bar(x, grouped["median"], color="#0f766e", alpha=0.85, label="median prefill")
    ax.plot(x, grouped["mean"], color="#d97706", marker="o", lw=1.7, label="mean prefill")
    for idx, count in enumerate(grouped["count"]):
        ax.text(idx, grouped["median"].iloc[idx] + max(grouped["median"].max() * 0.03, 0.2), f"n={int(count)}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Prefill time (s)")
    ax.set_title("80-90% cache is better, but 95-99% is where dflash becomes fast")
    ax.grid(True, axis="y", ls="--", alpha=0.25)
    ax.legend(loc="upper right", framealpha=0.9)
    return True


def _plot_session_maturity(ax_top, ax_bottom, session: pd.DataFrame) -> None:
    x = session["turn_in_session"]
    ax_top.plot(x, session["prompt_tokens"], color="#1f6feb", lw=1.8, label="prompt tokens")
    hit = session[session["cache_hit_pct"] >= 95]
    miss = session[session["cache_hit_pct"] < 95]
    if not hit.empty:
        ax_top.scatter(hit["turn_in_session"], hit["prompt_tokens"], s=14, color="#16a34a", alpha=0.75, label="cache >=95%")
    if not miss.empty:
        ax_top.scatter(miss["turn_in_session"], miss["prompt_tokens"], s=18, color="#dc2626", alpha=0.8, marker="x", label="cache <95%")
    ax_top.set_ylabel("Prompt tokens")
    ax_top.set_title("Prompt growth over the longest session")
    ax_top.grid(True, ls="--", alpha=0.25)
    ax_top.legend(loc="upper left", framealpha=0.9)

    ax_bottom.plot(x, session["prefill_time_s"], color="#d97706", lw=1.8, label="prefill time")
    ax_bottom.axhline(2.0, color="#16a34a", ls=":", lw=1)
    ax_bottom.axhline(60.0, color="#dc2626", ls=":", lw=1)
    ax_bottom.set_yscale("log")
    ax_bottom.set_xlabel("Turn within session")
    ax_bottom.set_ylabel("Prefill time (s, log scale)")
    ax_bottom.set_title("Latency collapses only when the reused prefix is almost complete")
    ax_bottom.grid(True, which="both", ls="--", alpha=0.25)
    ax_bottom.legend(loc="upper left", framealpha=0.9)


def _render_aggregate(df: pd.DataFrame) -> None:
    IMG.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9.8, 5.6))
    _plot_cache_cliff(ax, df)
    fig.tight_layout()
    fig.savefig(IMG / "cache_cliff.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9.8, 5.6))
    _plot_uncached_cliff(ax, df)
    fig.tight_layout()
    fig.savefig(IMG / "uncached_cliff.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9.0, 5.2))
    _plot_cache_band_latency(ax, df)
    fig.tight_layout()
    fig.savefig(IMG / "cache_band_latency.png", dpi=140)
    plt.close(fig)

    longest_session_id = df.groupby("session_id").size().idxmax()
    run = df[df["session_id"] == longest_session_id].reset_index(drop=True)
    fig, (ax_top, ax_bottom) = plt.subplots(2, 1, figsize=(11.0, 7.6), sharex=True)
    fig.suptitle(
        f"Longest dflash session {run['session_label'].iat[0]} | calls={len(run)} | "
        f"{run['timestamp'].min():%Y-%m-%d %H:%M} → {run['timestamp'].max():%H:%M}",
        fontsize=12,
    )
    _plot_session_maturity(ax_top, ax_bottom, run)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(IMG / "session_maturity.png", dpi=140)
    plt.close(fig)

    print("DFlash charts written to", str(IMG))
    print("  clean requests   :", len(df))
    print("  sessions         :", df["session_id"].nunique())
    print("  cache median     :", f"{df['cache_hit_pct'].median():.2f}%")
    print("  prefill median   :", f"{df['prefill_time_s'].median():.2f}s")
    print("  prefill p90      :", f"{df['prefill_time_s'].quantile(0.9):.2f}s")
    print("  <=2s share       :", f"{(df['prefill_time_s'] <= 2).mean() * 100:.1f}%")
    print("  <=5s share       :", f"{(df['prefill_time_s'] <= 5).mean() * 100:.1f}%")
    print("  <=100 uncached   :", f"{(df['uncached_tokens'] <= 100).mean() * 100:.1f}%")
    print("  >95% cache share :", f"{(df['cache_hit_pct'] >= 95).mean() * 100:.1f}%")
    print("  >99% cache share :", f"{(df['cache_hit_pct'] >= 99).mean() * 100:.1f}%")
    print("  longest session   :", run["session_label"].iat[0], "calls", len(run))


def _render_sessions(df: pd.DataFrame) -> None:
    SESSION_IMG.mkdir(parents=True, exist_ok=True)
    created = 0
    for session_id, session in df.groupby("session_id", sort=True):
        session = session.reset_index(drop=True)
        if len(session) < SESSION_MIN_CALLS:
            continue

        label = session["session_label"].iat[0]
        model = ", ".join(sorted({str(v) for v in session["served_target"].dropna() if str(v).strip()})) or "unknown"
        fig, (ax_top, ax_bottom) = plt.subplots(2, 1, figsize=(11.5, 8.2), sharex=True)
        fig.suptitle(
            f"dflash session {label} | model={model} | calls={len(session)} | "
            f"{session['timestamp'].min():%Y-%m-%d %H:%M} → {session['timestamp'].max():%H:%M}",
            fontsize=12,
        )

        _plot_session_maturity(ax_top, ax_bottom, session)
        fig.tight_layout(rect=(0, 0, 1, 0.95))
        fig.savefig(SESSION_IMG / f"dflash_session_{label}.png", dpi=140)
        plt.close(fig)
        created += 1
        print(
            "  session",
            session_id,
            label,
            f"calls={len(session)}",
            f"median_cache={session['cache_hit_pct'].median():.2f}%",
            f"median_prefill={session['prefill_time_s'].median():.2f}s",
        )

    print("Per-session charts written to", str(SESSION_IMG), f"({created} sessions)")


def main() -> None:
    csv_path = _resolve_timings_csv()
    if not csv_path.exists():
        raise FileNotFoundError(f"timings CSV not found at {csv_path}")

    df = _prepare_frame(csv_path)
    _render_aggregate(df)
    _render_sessions(df)


if __name__ == "__main__":
    main()