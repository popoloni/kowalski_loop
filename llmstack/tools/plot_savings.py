#!/usr/bin/env python3
"""Generate a synthesis chart that connects memory, headroom, and dflash savings.

Outputs (into docs/img/savings/):
  1. savings_landscape.png - three-panel overview of the three efficiency layers
"""

import json
import argparse
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
PROMPT_TREND_BINS = np.logspace(0, np.log10(200000), 14)
HEADROOM_TREND_BINS = np.unique(
    np.concatenate(
        [
            np.logspace(0, 4.4, 10),
            np.logspace(4.4, np.log10(200000), 16),
        ]
    )
)
DECODE_TREND_BINS = np.logspace(0, 5, 15)

TARGET_COLORS = {
    "mlx-community/Ornith-1.0-35B-4bit": "#c1121f",
    "mlx-community/Qwen3.6-27B-4bit": "#1f6feb",
    "mlx-community/Qwen3.6-35B-A3B-4bit": "#d97706",
    "mlx-community/gemma-4-12B-4bit": "#10b981",
}

OVERALL_POINT_COLOR = "#9ca3af"
OVERALL_LINE_COLOR = "#111827"
OVERALL_ALPHA = 0.16
CI_ALPHA = 0.35
CI_LINE_WIDTH = 1.15
CI_CAP_SIZE = 3.5
CI_RESAMPLES = 300


def _stat_label(statistic: str) -> str:
    if statistic == "mean":
        return "mean"
    if statistic == "median":
        return "median"
    if statistic.startswith("q"):
        return f"p{statistic[1:]}"
    return statistic


def _draw_ci(ax, xs: np.ndarray, ys: np.ndarray, lower: np.ndarray, upper: np.ndarray, *, color: str) -> None:
    ax.errorbar(
        xs,
        ys,
        yerr=np.vstack([ys - lower, upper - ys]),
        fmt="none",
        ecolor=color,
        elinewidth=CI_LINE_WIDTH,
        capsize=CI_CAP_SIZE,
        capthick=CI_LINE_WIDTH,
        alpha=CI_ALPHA,
        zorder=2,
    )


def _binned_stat(
    x: pd.Series,
    y: pd.Series,
    bins: np.ndarray,
    *,
    statistic: str = "mean",
    show_ci: bool = False,
    confidence: float = 0.95,
) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None, np.ndarray | None]:
    frame = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")})
    frame = frame.dropna(subset=["x", "y"])
    if frame.empty:
        return None, None, None, None

    frame["bucket"] = pd.cut(frame["x"], bins, include_lowest=True)
    grouped = frame.groupby("bucket", observed=False)["y"]
    if statistic.startswith("q"):
        quantile = float(statistic[1:]) / 100.0
        aggregated = grouped.quantile(quantile).dropna()
    else:
        aggregated = grouped.agg(statistic).dropna()
    if aggregated.empty:
        return None, None, None, None

    if not show_ci:
        xs = np.array([interval.mid for interval in aggregated.index])
        values = aggregated.values
        return xs, values, None, None

    rng = np.random.default_rng(42)
    lower_values = []
    upper_values = []
    retained_xs = []
    retained_values = []
    alpha = (1.0 - confidence) / 2.0

    for bucket, bucket_values in grouped:
        clean = pd.to_numeric(bucket_values, errors="coerce").dropna().to_numpy()
        if clean.size == 0:
            continue

        if statistic == "median":
            center = float(np.median(clean))
        elif statistic.startswith("q"):
            center = float(np.quantile(clean, float(statistic[1:]) / 100.0))
        else:
            center = float(np.mean(clean))

        if clean.size == 1:
            lower = center
            upper = center
        else:
            resampled = rng.choice(clean, size=(CI_RESAMPLES, clean.size), replace=True)
            if statistic == "median":
                samples = np.median(resampled, axis=1)
            elif statistic.startswith("q"):
                samples = np.quantile(resampled, float(statistic[1:]) / 100.0, axis=1)
            else:
                samples = np.mean(resampled, axis=1)
            lower = float(np.quantile(samples, alpha))
            upper = float(np.quantile(samples, 1.0 - alpha))

        retained_xs.append(bucket.mid)
        retained_values.append(center)
        lower_values.append(lower)
        upper_values.append(upper)

    if not retained_xs:
        return None, None, None, None

    return (
        np.asarray(retained_xs),
        np.asarray(retained_values),
        np.asarray(lower_values),
        np.asarray(upper_values),
    )


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


def _plot_memory_panel(ax, df: pd.DataFrame, *, split_by_model: bool, statistic: str, show_ci: bool, confidence: float) -> None:
    if split_by_model:
        for target, color in TARGET_COLORS.items():
            subset = df[df["served_target"] == target].copy()
            if subset.empty:
                continue
            ax.scatter(subset["prompt_tokens"], subset["mlx_peak_gb"], s=10, alpha=0.15, color=color, linewidths=0)
            xs, ys, lower, upper = _binned_stat(
                subset["prompt_tokens"],
                subset["mlx_peak_gb"],
                PROMPT_TREND_BINS,
                statistic=statistic,
                show_ci=show_ci,
                confidence=confidence,
            )
            if xs is not None:
                label = target.rsplit("/", 1)[-1].replace("-4bit", "")
                if show_ci and lower is not None and upper is not None:
                    _draw_ci(ax, xs, ys, lower, upper, color=color)
                ax.plot(xs, ys, color=color, lw=2.0, marker="o", label=label)
    else:
        ax.scatter(df["prompt_tokens"], df["mlx_peak_gb"], s=10, alpha=OVERALL_ALPHA, color=OVERALL_POINT_COLOR, linewidths=0)
        xs, ys, lower, upper = _binned_stat(
            df["prompt_tokens"],
            df["mlx_peak_gb"],
            PROMPT_TREND_BINS,
            statistic=statistic,
            show_ci=show_ci,
            confidence=confidence,
        )
        if xs is not None:
            if show_ci and lower is not None and upper is not None:
                _draw_ci(ax, xs, ys, lower, upper, color=OVERALL_LINE_COLOR)
            ax.plot(xs, ys, color=OVERALL_LINE_COLOR, lw=2.3, marker="o", label=f"overall {_stat_label(statistic)}")

    ax.axhline(48.0, color="#6b7280", ls=":", lw=1.0)
    ax.axhline(52.0, color="#dc2626", ls=":", lw=1.0)
    ax.text(120000, 48.0, " 48 GB", ha="right", va="bottom", color="#6b7280", fontsize=9)
    ax.text(120000, 52.0, " 52 GB", ha="right", va="bottom", color="#dc2626", fontsize=9)
    ax.set_xscale("log")
    ax.set_xlabel("Prompt size (tokens, log scale)")
    ax.set_ylabel("MLX peak memory (GB)")
    ax.set_title("Memory climbs with prompt size and crosses the danger band on long runs")
    ax.grid(True, which="both", ls="--", alpha=0.25)
    if split_by_model:
        ax.legend(loc="upper left", framealpha=0.9)
    else:
        ax.legend(loc="upper left", framealpha=0.9)


def _plot_headroom_panel(ax, df: pd.DataFrame, *, split_by_model: bool, statistic: str, show_ci: bool, confidence: float) -> None:
    big = df[df["input_tokens_original"] >= 5000].copy()
    if big.empty:
        ax.text(0.5, 0.5, "No large Headroom calls found", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return

    if split_by_model:
        for target, color in TARGET_COLORS.items():
            rows = big[big["model"] == target]
            if rows.empty:
                continue
            hit = rows[rows["cache_hit"]]
            miss = rows[~rows["cache_hit"]]
            if not hit.empty:
                ax.scatter(hit["input_tokens_original"], hit["savings_percent"], s=10, alpha=0.15, color=color, linewidths=0)
            if not miss.empty:
                ax.scatter(miss["input_tokens_original"], miss["savings_percent"], s=14, alpha=0.18, color=color, marker="x", linewidths=0.7)
            xs, ys, lower, upper = _binned_stat(
                rows["input_tokens_original"],
                rows["savings_percent"],
                HEADROOM_TREND_BINS,
                statistic=statistic,
                show_ci=show_ci,
                confidence=confidence,
            )
            if xs is not None:
                label = target.rsplit("/", 1)[-1].replace("-4bit", "")
                if show_ci and lower is not None and upper is not None:
                    _draw_ci(ax, xs, ys, lower, upper, color=color)
                ax.plot(xs, ys, color=color, lw=2.0, marker="o", label=label)
    else:
        colors = np.where(big["cache_hit"], OVERALL_POINT_COLOR, "#c1121f")
        ax.scatter(big["input_tokens_original"], big["savings_percent"], s=10, alpha=OVERALL_ALPHA, c=colors, linewidths=0)
        xs, ys, lower, upper = _binned_stat(
            big["input_tokens_original"],
            big["savings_percent"],
            HEADROOM_TREND_BINS,
            statistic=statistic,
            show_ci=show_ci,
            confidence=confidence,
        )
        if xs is not None:
            if show_ci and lower is not None and upper is not None:
                _draw_ci(ax, xs, ys, lower, upper, color=OVERALL_LINE_COLOR)
            ax.plot(xs, ys, color=OVERALL_LINE_COLOR, lw=2.3, marker="o", label=f"overall {_stat_label(statistic)}")
    ax.axhline(20.0, color="#d97706", ls=":", lw=1.0)
    ax.text(big["input_tokens_original"].max(), 20.0, " 20%", ha="right", va="bottom", color="#d97706", fontsize=9)
    ax.set_xscale("log")
    ax.set_xlabel("Input tokens (log scale)")
    ax.set_ylabel("Savings percent")
    ax.set_title("Headroom savings appears only after prompts and sessions get large")
    ax.grid(True, which="both", ls="--", alpha=0.25)
    ax.legend(loc="upper left", framealpha=0.9)


def _plot_dflash_panel(ax, df: pd.DataFrame, *, split_by_model: bool, statistic: str, show_ci: bool, confidence: float) -> None:
    if df.empty:
        ax.text(0.5, 0.5, "No clean dflash calls found", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return

    if split_by_model:
        for target, color in TARGET_COLORS.items():
            rows = df[df["served_target"] == target]
            if rows.empty:
                continue
            ax.scatter(rows["cache_hit_pct"], rows["prefill_time_s"], s=10, alpha=0.15, color=color, linewidths=0)
            xs, ys, lower, upper = _binned_stat(
                rows["cache_hit_pct"],
                rows["prefill_time_s"],
                np.asarray(DFLASH_CACHE_BINS, dtype=float),
                statistic=statistic,
                show_ci=show_ci,
                confidence=confidence,
            )
            if xs is not None:
                label = target.rsplit("/", 1)[-1].replace("-4bit", "")
                if show_ci and lower is not None and upper is not None:
                    _draw_ci(ax, xs, ys, lower, upper, color=color)
                ax.plot(xs, ys, color=color, lw=2.0, marker="o", label=label)
    else:
        ax.scatter(df["cache_hit_pct"], df["prefill_time_s"], s=10, alpha=OVERALL_ALPHA, color=OVERALL_POINT_COLOR, linewidths=0)
        xs, ys, lower, upper = _binned_stat(
            df["cache_hit_pct"],
            df["prefill_time_s"],
            np.asarray(DFLASH_CACHE_BINS, dtype=float),
            statistic=statistic,
            show_ci=show_ci,
            confidence=confidence,
        )
        if xs is not None:
            if show_ci and lower is not None and upper is not None:
                _draw_ci(ax, xs, ys, lower, upper, color=OVERALL_LINE_COLOR)
            ax.plot(xs, ys, color=OVERALL_LINE_COLOR, lw=2.3, marker="o", label=f"overall {_stat_label(statistic)}")
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


def _plot_output_panel(ax, df: pd.DataFrame, *, split_by_model: bool, statistic: str, show_ci: bool, confidence: float) -> None:
    subset = df[df["decode_time_s"].notna() & df["decode_tokens"].notna()].copy()
    if subset.empty:
        ax.text(0.5, 0.5, "No output-time rows found", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return

    if split_by_model:
        for target, color in TARGET_COLORS.items():
            rows = subset[subset["served_target"] == target]
            if rows.empty:
                continue
            ax.scatter(rows["decode_tokens"], rows["decode_time_s"], s=10, alpha=0.15, color=color, linewidths=0)
            xs, ys, lower, upper = _binned_stat(
                rows["decode_tokens"],
                rows["decode_time_s"],
                DECODE_TREND_BINS,
                statistic=statistic,
                show_ci=show_ci,
                confidence=confidence,
            )
            if xs is not None:
                label = target.rsplit("/", 1)[-1].replace("-4bit", "")
                if show_ci and lower is not None and upper is not None:
                    _draw_ci(ax, xs, ys, lower, upper, color=color)
                ax.plot(xs, ys, color=color, lw=2.0, marker="o", label=label)
    else:
        ax.scatter(subset["decode_tokens"], subset["decode_time_s"], s=10, alpha=OVERALL_ALPHA, color=OVERALL_POINT_COLOR, linewidths=0)
        xs, ys, lower, upper = _binned_stat(
            subset["decode_tokens"],
            subset["decode_time_s"],
            DECODE_TREND_BINS,
            statistic=statistic,
            show_ci=show_ci,
            confidence=confidence,
        )
        if xs is not None:
            if show_ci and lower is not None and upper is not None:
                _draw_ci(ax, xs, ys, lower, upper, color=OVERALL_LINE_COLOR)
            ax.plot(xs, ys, color=OVERALL_LINE_COLOR, lw=2.3, marker="o", label=f"overall {_stat_label(statistic)}")

    ax.set_xscale("log")
    ax.set_xlabel("Generated tokens (log scale)")
    ax.set_ylabel("Decode time (s)")
    ax.set_title("Output time follows generated length and model speed, not cache savings")
    ax.grid(True, which="both", ls="--", alpha=0.25)

    ax.legend(loc="upper left", framealpha=0.9)


def _render_overview(
    memory_df: pd.DataFrame,
    headroom_df: pd.DataFrame,
    dflash_df: pd.DataFrame,
    *,
    split_by_model: bool,
    output_name: str,
    title: str,
    statistic: str,
    show_ci: bool,
    confidence: float,
) -> None:
    IMG.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(17.6, 10.0))
    axes = axes.flatten()
    _plot_memory_panel(axes[0], memory_df, split_by_model=split_by_model, statistic=statistic, show_ci=show_ci, confidence=confidence)
    _plot_headroom_panel(axes[1], headroom_df, split_by_model=split_by_model, statistic=statistic, show_ci=show_ci, confidence=confidence)
    _plot_dflash_panel(axes[2], dflash_df, split_by_model=split_by_model, statistic=statistic, show_ci=show_ci, confidence=confidence)
    _plot_output_panel(axes[3], dflash_df, split_by_model=split_by_model, statistic=statistic, show_ci=show_ci, confidence=confidence)
    fig.suptitle(title, fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(IMG / output_name, dpi=140)
    plt.close(fig)

    memory_ornith = memory_df[memory_df["served_target"] == "mlx-community/Ornith-1.0-35B-4bit"]
    memory_27 = memory_df[memory_df["served_target"] == "mlx-community/Qwen3.6-27B-4bit"]
    memory_35 = memory_df[memory_df["served_target"] == "mlx-community/Qwen3.6-35B-A3B-4bit"]
    memory_gemma = memory_df[memory_df["served_target"] == "mlx-community/gemma-4-12B-4bit"]
    print("Savings charts written to", str(IMG))
    print("  memory ornith35B:", _stats(memory_ornith["mlx_peak_gb"], " GB"))
    print("  memory 27B      :", _stats(memory_27["mlx_peak_gb"], " GB"))
    print("  memory 35B-A3B  :", _stats(memory_35["mlx_peak_gb"], " GB"))
    print("  memory gemma12B :", _stats(memory_gemma["mlx_peak_gb"], " GB"))
    print("  headroom savings :", _stats(headroom_df["savings_percent"], "%"))
    print("  headroom >=20%   :", f"{(headroom_df['savings_percent'] >= 20).mean() * 100:.1f}%")
    print("  dflash prefill   :", _stats(dflash_df["prefill_time_s"], " s"))
    print("  output decode    :", _stats(dflash_df["decode_time_s"], " s"))
    print("  decode tokens    :", f"median={dflash_df['decode_tokens'].median():.0f} p90={dflash_df['decode_tokens'].quantile(0.9):.0f}")
    print("  dflash <=2s      :", f"{(dflash_df['prefill_time_s'] <= 2).mean() * 100:.1f}%")
    print("  dflash >99% cache:", f"{(dflash_df['cache_hit_pct'] >= 99).mean() * 100:.1f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the savings synthesis charts.")
    parser.add_argument("--statistic", choices=("mean", "median"), default="median", help="Aggregation used for every binned line.")
    ci_group = parser.add_mutually_exclusive_group()
    ci_group.add_argument("--show-ci", dest="show_ci", action="store_true", help="Draw bootstrap confidence whiskers for each binned line sample.")
    ci_group.add_argument("--no-show-ci", dest="show_ci", action="store_false", help="Disable confidence whiskers.")
    parser.set_defaults(show_ci=True)
    parser.add_argument("--ci-level", type=float, default=0.95, help="Confidence level for the optional whiskers.")
    args = parser.parse_args()

    headroom_log = _resolve_headroom_log()
    timings_csv = _resolve_timings_csv()
    if not headroom_log.exists():
        raise FileNotFoundError(f"Headroom traffic log not found at {headroom_log}")
    if not timings_csv.exists():
        raise FileNotFoundError(f"timings CSV not found at {timings_csv}")

    headroom_df = _prepare_headroom_frame(headroom_log)
    dflash_df = _prepare_dflash_frame(timings_csv)
    memory_df = dflash_df[dflash_df["served_target"].isin(TARGET_COLORS.keys())].copy()

    _render_overview(
        memory_df,
        headroom_df,
        dflash_df,
        split_by_model=False,
        output_name="savings_landscape.png",
        title="Where the stack saves time, and where it still pays the full cost",
        statistic=args.statistic,
        show_ci=args.show_ci,
        confidence=args.ci_level,
    )
    _render_overview(
        memory_df,
        headroom_df,
        dflash_df,
        split_by_model=True,
        output_name="savings_landscape_by_model.png",
        title="Where the stack saves time, split by model",
        statistic=args.statistic,
        show_ci=args.show_ci,
        confidence=args.ci_level,
    )


if __name__ == "__main__":
    main()