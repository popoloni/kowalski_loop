#!/usr/bin/env python3
"""Generate aggregate and per-session charts from dflash_timings.csv.

Outputs (into docs/img/):
  1. prefill_cliff.png   — prefill time vs prompt size, cache HIT vs MISS
  2. context_memory.png  — prompt-token + peak-memory growth over the longest run
  3. cachehit_hist.png   — distribution of per-call total time, hit vs miss
  4. sessions/session_*.png — one composite chart per work session
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "llmstack_config.json"
IMG = ROOT / "docs" / "img"
SESSION_IMG = IMG / "sessions"
BIG_PROMPT_TOKENS = 5000
SESSION_GAP_MINUTES = 60
SESSION_MIN_CALLS = 5
METAL_LIMIT_GB = 52
HIST_BINS = [0, 2, 5, 10, 30, 60, 120, 300, 600, 1200]


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
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        df["miss"] = df["cache_hit_pct"].fillna(0.0) < 50.0
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


def _stats(series: pd.Series) -> str:
        series = series.dropna()
        if series.empty:
                return "n=0"
        return f"n={len(series)} median={series.median():.1f}s max={series.max():.0f}s"


def _plot_prefill(ax, subset: pd.DataFrame, title: str) -> bool:
        big = subset[subset["prompt_tokens"] >= BIG_PROMPT_TOKENS].copy()
        if big.empty:
                ax.text(0.5, 0.5, "No >=5k-token calls in this slice", ha="center", va="center", transform=ax.transAxes)
                ax.set_title(title)
                ax.set_axis_off()
                return False

        hit = big[~big["miss"]]
        miss = big[big["miss"]]
        if not hit.empty:
                ax.scatter(
                        hit["prompt_tokens"] / 1000,
                        hit["prefill_time_s"],
                        s=22,
                        alpha=0.55,
                        color="#2e8b57",
                        label=f"cache HIT (n={len(hit)})",
                )
        if not miss.empty:
                ax.scatter(
                        miss["prompt_tokens"] / 1000,
                        miss["prefill_time_s"],
                        s=40,
                        alpha=0.8,
                        color="#c1121f",
                        marker="x",
                        label=f"cache MISS (n={len(miss)})",
                )
        ax.set_yscale("log")
        ax.set_xlabel("Prompt size (thousands of tokens)")
        ax.set_ylabel("Prefill time (s, log scale)")
        ax.set_title(title)
        ax.axhline(1.0, color="#2e8b57", ls=":", lw=1, alpha=0.7)
        ax.axhline(60.0, color="#c1121f", ls=":", lw=1, alpha=0.7)
        xmax = max(float(big["prompt_tokens"].max() / 1000), 1.0)
        ax.text(xmax, 1.0, " ~1 s", va="bottom", ha="right", color="#2e8b57", fontsize=9)
        ax.text(xmax, 60.0, " 1 min", va="bottom", ha="right", color="#c1121f", fontsize=9)
        ax.grid(True, which="both", ls="--", alpha=0.25)
        ax.legend(loc="upper left", framealpha=0.9)
        return True


def _plot_context_memory(ax, subset: pd.DataFrame, title: str) -> bool:
        if subset.empty:
                ax.text(0.5, 0.5, "No calls in this slice", ha="center", va="center", transform=ax.transAxes)
                ax.set_title(title)
                ax.set_axis_off()
                return False

        x = range(len(subset))
        ax.plot(x, subset["prompt_tokens"] / 1000, color="#1f6feb", lw=1.8, label="prompt size (k tokens)")
        ax.set_xlabel("Successive model calls")
        ax.set_ylabel("Prompt size (thousands of tokens)", color="#1f6feb")
        ax.tick_params(axis="y", labelcolor="#1f6feb")
        ax.grid(True, ls="--", alpha=0.25)
        ax.set_title(title)

        twin = ax.twinx()
        peak = subset["mlx_peak_gb"].dropna()
        if not peak.empty:
                twin.plot(x, subset["mlx_peak_gb"], color="#d4a017", lw=1.8, label="MLX peak memory (GB)")
        twin.set_ylabel("MLX peak memory (GB)", color="#d4a017")
        twin.tick_params(axis="y", labelcolor="#d4a017")
        twin.axhline(METAL_LIMIT_GB, color="#c1121f", ls=":", lw=1.2, label="_nolegend_")
        twin.text(len(subset) - 1, METAL_LIMIT_GB, " ~52 GB Metal limit", va="bottom", ha="right", color="#c1121f", fontsize=9)

        lines = [line for line in (ax.get_lines() + twin.get_lines()) if not line.get_label().startswith("_")]
        ax.legend(lines, [line.get_label() for line in lines], loc="upper left", framealpha=0.9)
        return True


def _plot_total_hist(ax, subset: pd.DataFrame, title: str) -> bool:
        big = subset[subset["prompt_tokens"] >= BIG_PROMPT_TOKENS].copy()
        if big.empty:
                ax.text(0.5, 0.5, "No >=5k-token calls in this slice", ha="center", va="center", transform=ax.transAxes)
                ax.set_title(title)
                ax.set_axis_off()
                return False

        hit = big[~big["miss"]]["total_time_s"].dropna()
        miss = big[big["miss"]]["total_time_s"].dropna()
        if not hit.empty:
                ax.hist(hit, bins=HIST_BINS, alpha=0.7, color="#2e8b57", label=f"cache HIT (n={len(hit)})")
        if not miss.empty:
                ax.hist(miss, bins=HIST_BINS, alpha=0.7, color="#c1121f", label=f"cache MISS (n={len(miss)})")
        ax.set_xscale("log")
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda value, _: f"{value:g}"))
        ax.set_xlabel("Total turn time (s, log scale)")
        ax.set_ylabel("Number of calls")
        ax.set_title(title)
        ax.grid(True, ls="--", alpha=0.25)
        ax.legend(framealpha=0.9)
        return True


def _render_aggregate(df: pd.DataFrame) -> None:
        big = df[df["prompt_tokens"] >= BIG_PROMPT_TOKENS].copy()
        hit = big[~big["miss"]]
        miss = big[big["miss"]]

        fig, ax = plt.subplots(figsize=(9, 5.5))
        _plot_prefill(ax, df, "The prefix-cache cliff: one second on a hit, minutes on a miss")
        fig.tight_layout()
        fig.savefig(IMG / "prefill_cliff.png", dpi=130)
        plt.close(fig)

        longest_session_id = df.groupby("session_id").size().idxmax()
        run = df[df["session_id"] == longest_session_id].reset_index(drop=True)
        fig, ax = plt.subplots(figsize=(9, 5.5))
        _plot_context_memory(ax, run, "Whole-file regeneration bloats context — and memory creeps toward the ceiling")
        fig.tight_layout()
        fig.savefig(IMG / "context_memory.png", dpi=130)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(9, 5.5))
        _plot_total_hist(ax, df, "Misses are the minority of calls — but they own the wall clock")
        fig.tight_layout()
        fig.savefig(IMG / "cachehit_hist.png", dpi=130)
        plt.close(fig)

        print("Charts written to", str(IMG))
        print("  big calls (>=5k tok):", len(big))
        print("  HIT prefill :", _stats(hit["prefill_time_s"]))
        print("  MISS prefill:", _stats(miss["prefill_time_s"]))
        print("  HIT total   :", _stats(hit["total_time_s"]))
        print("  MISS total  :", _stats(miss["total_time_s"]))
        print(
                "  longest session for chart2:",
                run["session_label"].iat[0],
                "calls",
                len(run),
                "prompt",
                f"{run['prompt_tokens'].min()}→{run['prompt_tokens'].max()}",
                "mem",
                f"{run['mlx_peak_gb'].min()}→{run['mlx_peak_gb'].max()}",
        )


def _render_sessions(df: pd.DataFrame) -> None:
        SESSION_IMG.mkdir(parents=True, exist_ok=True)
        created = 0
        for session_id, session in df.groupby("session_id", sort=True):
                session = session.reset_index(drop=True)
                if len(session) < SESSION_MIN_CALLS:
                        continue
                label = session["session_label"].iat[0]
                backend = ", ".join(sorted({str(v) for v in session["backend"].dropna() if str(v).strip()})) or "unknown"
                fig, axes = plt.subplots(1, 3, figsize=(16.5, 4.8))
                fig.suptitle(
                        f"Work session {label}  |  backend={backend}  |  calls={len(session)}  |  "
                        f"{session['timestamp'].min():%Y-%m-%d %H:%M} → {session['timestamp'].max():%H:%M}",
                        fontsize=12,
                )
                _plot_prefill(axes[0], session, "Prefill cliff in this session")
                _plot_context_memory(axes[1], session, "Context and memory during this session")
                _plot_total_hist(axes[2], session, "Total turn-time distribution")
                fig.tight_layout(rect=(0, 0, 1, 0.94))
                fig.savefig(SESSION_IMG / f"session_{label}.png", dpi=130)
                plt.close(fig)
                created += 1
                print(
                        "  session",
                        session_id,
                        label,
                        f"calls={len(session)}",
                        f"big_calls={(session['prompt_tokens'] >= BIG_PROMPT_TOKENS).sum()}",
                        f"backend={backend}",
                )
        print("Per-session charts written to", str(SESSION_IMG), f"({created} sessions)")


def main() -> None:
        csv_path = _resolve_timings_csv()
        IMG.mkdir(parents=True, exist_ok=True)
        if not csv_path.exists():
                raise FileNotFoundError(f"timings CSV not found at {csv_path}")

        df = _prepare_frame(csv_path)
        _render_aggregate(df)
        _render_sessions(df)


if __name__ == "__main__":
        main()
