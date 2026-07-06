#!/usr/bin/env python3
"""Compute Headroom summary metrics and optionally update HEADROOM.md blocks."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from llmstack.tools.plot_savings import _prepare_headroom_frame, _resolve_headroom_log


ROOT = Path(__file__).resolve().parents[2]

CORE_START = "<!-- HEADROOM_CORE_TABLE_START -->"
CORE_END = "<!-- HEADROOM_CORE_TABLE_END -->"
PIECEWISE_START = "<!-- HEADROOM_PIECEWISE_START -->"
PIECEWISE_END = "<!-- HEADROOM_PIECEWISE_END -->"
REG_START = "<!-- HEADROOM_REGRESSION_START -->"
REG_END = "<!-- HEADROOM_REGRESSION_END -->"
MODEL_START = "<!-- HEADROOM_MODEL_TABLE_START -->"
MODEL_END = "<!-- HEADROOM_MODEL_TABLE_END -->"

PIECEWISE_BINS = [
    (0, 10_000),
    (10_000, 30_000),
    (30_000, 40_000),
    (40_000, 60_000),
    (60_000, 10**9),
]


def _fmt_num(value: float, digits: int = 2) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:.{digits}f}"


def _fmt_int(value: float) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:,.0f}"


def _load_headroom() -> pd.DataFrame:
    return _prepare_headroom_frame(_resolve_headroom_log())


def build_core_table(df: pd.DataFrame) -> str:
    total_original = pd.to_numeric(df["input_tokens_original"], errors="coerce").sum()
    total_saved = pd.to_numeric(df["tokens_saved"], errors="coerce").sum()
    weighted_savings = (total_saved / total_original * 100.0) if total_original else float("nan")
    retained_after_opt = ((total_original - total_saved) / total_original * 100.0) if total_original else float("nan")

    lines = [
        "| Metric | Value |",
        "|---|---:|",
        f"| Requests | {_fmt_int(len(df))} |",
        f"| Sessions | {_fmt_int(df['session_id'].nunique())} |",
        f"| Total original tokens | {_fmt_int(total_original)} |",
        f"| Total tokens saved | {_fmt_int(total_saved)} |",
        f"| Weighted savings | {_fmt_num(weighted_savings)}% |",
        f"| Tokens retained after optimization | {_fmt_num(retained_after_opt)}% |",
        f"| Mean savings per request | {_fmt_num(df['savings_percent'].mean())}% |",
        f"| Median savings per request | {_fmt_num(df['savings_percent'].median())}% |",
        f"| 90th percentile savings | {_fmt_num(df['savings_percent'].quantile(0.9))}% |",
        f"| Max savings | {_fmt_num(df['savings_percent'].max())}% |",
        f"| Zero-savings share | {_fmt_num((df['savings_percent'] <= 0).mean() * 100.0, 1)}% |",
        f"| Requests at 20%+ savings | {_fmt_num((df['savings_percent'] >= 20).mean() * 100.0, 1)}% |",
    ]
    return "\n".join(lines)


def build_piecewise_block(df: pd.DataFrame) -> str:
    lines = [
        "```text",
    ]
    for low, high in PIECEWISE_BINS:
        subset = df[(df["input_tokens_original"] >= low) & (df["input_tokens_original"] < high)]
        med = subset["savings_percent"].median() if not subset.empty else float("nan")
        mean = subset["savings_percent"].mean() if not subset.empty else float("nan")
        ge20 = (subset["savings_percent"] >= 20).mean() * 100.0 if not subset.empty else float("nan")
        if high >= 10**9:
            label = "60k+"
        else:
            label = f"{int(low/1000)}k-{int(high/1000)}k"
        lines.append(
            f"{label:<9} n={len(subset):>4} median={_fmt_num(med):>5}% mean={_fmt_num(mean):>5}% share>=20%={_fmt_num(ge20,1):>4}%"
        )
    lines.append("```")
    return "\n".join(lines)


def build_regression_block(df: pd.DataFrame) -> tuple[str, float]:
    reg = df.dropna(subset=["input_tokens_original", "savings_percent", "session_progress"]).copy()
    reg = reg[reg["input_tokens_original"] > 0]
    reg["log_prompt"] = np.log10(reg["input_tokens_original"])
    reg["cache_hit_i"] = reg["cache_hit"].astype(int)

    if "transforms_applied" in reg.columns:
        reg["noop"] = reg["transforms_applied"].apply(
            lambda vals: 1 if isinstance(vals, list) and any(str(v) == "router:noop" for v in vals) else 0
        )
    else:
        reg["noop"] = 0

    X = np.column_stack(
        [
            np.ones(len(reg)),
            reg["log_prompt"].to_numpy(),
            reg["session_progress"].to_numpy(),
            reg["cache_hit_i"].to_numpy(),
            reg["noop"].to_numpy(),
        ]
    )
    y = reg["savings_percent"].to_numpy()
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    y_hat = X @ beta
    ssr = ((y - y_hat) ** 2).sum()
    sst = ((y - y.mean()) ** 2).sum()
    r2 = float(1.0 - ssr / sst) if sst else float("nan")

    block = "\n".join(
        [
            "```text",
            f"savings_percent ≈ {_fmt_num(beta[0])} + {_fmt_num(beta[1])}*log10(prompt_tokens)",
            f"                 + {_fmt_num(beta[2])}*session_progress",
            f"                 - {_fmt_num(abs(beta[3]))}*cache_hit",
            f"                 - {_fmt_num(abs(beta[4]))}*noop",
            "```",
        ]
    )
    return block, r2


def build_model_table(df: pd.DataFrame, *, min_rows: int) -> str:
    grouped = []
    for model, rows in df.groupby("model"):
        if len(rows) < min_rows:
            continue
        grouped.append(
            (
                model,
                len(rows),
                rows["savings_percent"].mean(),
                rows["savings_percent"].median(),
                rows["savings_percent"].quantile(0.9),
                (rows["savings_percent"] >= 20).mean() * 100.0,
            )
        )

    lines = [
        "| Model | n | Mean savings | Median savings | p90 savings | Share >=20% |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for model, n, mean, median, p90, ge20 in grouped:
        lines.append(
            f"| `{model}` | {_fmt_int(n)} | {_fmt_num(mean)}% | {_fmt_num(median)}% | {_fmt_num(p90)}% | {_fmt_num(ge20, 1)}% |"
        )
    return "\n".join(lines)


def _replace_between_markers(content: str, start: str, end: str, payload: str) -> str:
    start_idx = content.find(start)
    end_idx = content.find(end)
    if start_idx < 0 or end_idx < 0 or end_idx <= start_idx:
        raise ValueError(f"Marker block not found or malformed: {start} / {end}")
    pivot = start_idx + len(start)
    return content[:pivot] + "\n\n" + payload + "\n\n" + content[end_idx:]


def update_headroom_md(path: Path, core: str, piecewise: str, regression: str, model_table: str, r2: float) -> None:
    content = path.read_text(encoding="utf-8")
    content = _replace_between_markers(content, CORE_START, CORE_END, core)
    content = _replace_between_markers(content, PIECEWISE_START, PIECEWISE_END, piecewise)
    content = _replace_between_markers(content, REG_START, REG_END, regression)
    content = _replace_between_markers(content, MODEL_START, MODEL_END, model_table)

    # Keep the R^2 sentence updated too.
    content = content.replace(
        "This linear model is only a rough guide. Its $R^2$ is about 0.25, so it is useful for\n"
        "direction, not for precise forecasting. The piecewise model above is more actionable.",
        f"This linear model is only a rough guide. Its $R^2$ is about {_fmt_num(r2, 2)}, so it is useful for\n"
        "direction, not for precise forecasting. The piecewise model above is more actionable.",
    )

    path.write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute Headroom metrics and optionally update HEADROOM.md.")
    parser.add_argument("--update-headroom-md", action="store_true", help="Update HEADROOM.md marker blocks.")
    parser.add_argument("--headroom-md", type=Path, default=ROOT / "HEADROOM.md", help="Path to HEADROOM.md")
    parser.add_argument("--min-model-rows", type=int, default=100, help="Minimum rows for model table inclusion")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = _load_headroom()
    core = build_core_table(df)
    piecewise = build_piecewise_block(df)
    regression, r2 = build_regression_block(df)
    model_table = build_model_table(df, min_rows=args.min_model_rows)

    print(core)
    print("\n" + piecewise)
    print("\n" + regression)
    print(f"\nR2={_fmt_num(r2, 2)}")
    print("\n" + model_table)

    if args.update_headroom_md:
        update_headroom_md(args.headroom_md, core, piecewise, regression, model_table, r2)
        print(f"\nUpdated {args.headroom_md}")


if __name__ == "__main__":
    main()
