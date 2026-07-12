#!/usr/bin/env python3
"""Compute reusable savings metrics per model and render/update markdown tables."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from llmstack.tools.plot_savings import (
    _prepare_dflash_frame,
    _prepare_headroom_frame,
    _resolve_headroom_log,
    _resolve_timings_csv,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODELS = [
    "mlx-community/Ornith-1.0-35B-4bit",
    "mlx-community/Qwen3.6-27B-4bit",
    "mlx-community/Qwen3.6-35B-A3B-4bit",
    "mlx-community/gemma-4-12B-4bit",
]
LABEL_OVERRIDES = {
    "mlx-community/Ornith-1.0-35B-4bit": "Ornith-1.0-35B",
    "mlx-community/Qwen3.6-27B-4bit": "Qwen3.6-27B",
    "mlx-community/Qwen3.6-35B-A3B-4bit": "Qwen3.6-35B-A3B",
    "mlx-community/gemma-4-12B-4bit": "Gemma-4-12B",
}

TABLE_START = "<!-- SAVINGS_TABLE_START -->"
TABLE_END = "<!-- SAVINGS_TABLE_END -->"


@dataclass(frozen=True)
class ModelStats:
    model: str
    dflash_rows: int
    headroom_rows: int
    memory_median_gb: float
    memory_p90_gb: float
    headroom_median_pct: float
    headroom_p90_pct: float
    headroom_ge20_pct: float
    prefill_median_s: float
    prefill_p90_s: float
    decode_median_s: float
    decode_p90_s: float
    tokens_median: float
    tokens_p90: float
    prefill_le2_pct: float
    cache_ge99_pct: float


def _q(series: pd.Series, quantile: float) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return float("nan")
    return float(clean.quantile(quantile))


def _med(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return float("nan")
    return float(clean.median())


def _pct(mask: pd.Series) -> float:
    if mask.empty:
        return float("nan")
    return float(mask.mean() * 100.0)


def _fmt_num(value: float, decimals: int = 2) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:.{decimals}f}"


def _fmt_int(value: float) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:.0f}"


def compute_model_stats(models: list[str]) -> list[ModelStats]:
    timings_df = _prepare_dflash_frame(_resolve_timings_csv())
    headroom_df = _prepare_headroom_frame(_resolve_headroom_log())
    # Keep metrics on the same scope used in the headroom chart panel.
    headroom_df = headroom_df[headroom_df["input_tokens_original"] >= 5000].copy()

    results: list[ModelStats] = []
    for model in models:
        dflash_rows = timings_df[timings_df["served_target"] == model].copy()
        headroom_rows = headroom_df[headroom_df["model"] == model].copy()

        results.append(
            ModelStats(
                model=model,
                dflash_rows=int(dflash_rows.dropna(subset=["prefill_time_s", "decode_time_s", "decode_tokens"]).shape[0]),
                headroom_rows=int(headroom_rows.dropna(subset=["savings_percent"]).shape[0]),
                memory_median_gb=_med(dflash_rows["mlx_peak_gb"]),
                memory_p90_gb=_q(dflash_rows["mlx_peak_gb"], 0.90),
                headroom_median_pct=_med(headroom_rows["savings_percent"]),
                headroom_p90_pct=_q(headroom_rows["savings_percent"], 0.90),
                headroom_ge20_pct=_pct(headroom_rows["savings_percent"].fillna(-1.0).ge(20.0)),
                prefill_median_s=_med(dflash_rows["prefill_time_s"]),
                prefill_p90_s=_q(dflash_rows["prefill_time_s"], 0.90),
                decode_median_s=_med(dflash_rows["decode_time_s"]),
                decode_p90_s=_q(dflash_rows["decode_time_s"], 0.90),
                tokens_median=_med(dflash_rows["decode_tokens"]),
                tokens_p90=_q(dflash_rows["decode_tokens"], 0.90),
                prefill_le2_pct=_pct(dflash_rows["prefill_time_s"].fillna(float("inf")).le(2.0)),
                cache_ge99_pct=_pct(dflash_rows["cache_hit_pct"].fillna(-1.0).ge(99.0)),
            )
        )

    return results


def build_markdown_table(stats: list[ModelStats]) -> str:
    headers = ["Metric", *[LABEL_OVERRIDES.get(s.model, s.model.rsplit("/", 1)[-1].replace("-4bit", "")) for s in stats], "Notes"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---", *(["---:"] * len(stats)), "---"]) + " |",
    ]

    def row(metric: str, values: list[str], notes: str) -> None:
        lines.append("| " + " | ".join([metric, *values, notes]) + " |")

    row("Samples (dflash rows)", [_fmt_int(s.dflash_rows) for s in stats], "rows with valid prefill/decode/tokens")
    row("Samples (headroom rows)", [_fmt_int(s.headroom_rows) for s in stats], "rows with valid headroom savings and input_tokens_original >= 5000")
    row("Memory peak, median", [f"{_fmt_num(s.memory_median_gb)} GB" for s in stats], "median mlx peak per model")
    row("Memory peak, p90", [f"{_fmt_num(s.memory_p90_gb)} GB" for s in stats], "tail mlx peak per model")
    row("Headroom savings, median", [f"{_fmt_num(s.headroom_median_pct)}%" for s in stats], "computed from headroom model field on the same >=5000-token scope as the chart")
    row("Headroom savings, p90", [f"{_fmt_num(s.headroom_p90_pct)}%" for s in stats], "late-session tail by model")
    row("Headroom savings >= 20%", [f"{_fmt_num(s.headroom_ge20_pct, 1)}%" for s in stats], "share of strong-compression turns")
    row("DFlash prefill, median", [f"{_fmt_num(s.prefill_median_s)} s" for s in stats], "lower is better")
    row("DFlash prefill, p90", [f"{_fmt_num(s.prefill_p90_s)} s" for s in stats], "long-tail prefill latency")
    row("Output decode, median", [f"{_fmt_num(s.decode_median_s)} s" for s in stats], "center decode latency")
    row("Output decode, p90", [f"{_fmt_num(s.decode_p90_s)} s" for s in stats], "decode long tail")
    row("Decode tokens, median", [_fmt_int(s.tokens_median) for s in stats], "output length center")
    row("Decode tokens, p90", [_fmt_int(s.tokens_p90) for s in stats], "output length tail")
    row("DFlash share <= 2 s", [f"{_fmt_num(s.prefill_le2_pct, 1)}%" for s in stats], "fraction of fast-prefill requests")
    row("DFlash share > 99% cache", [f"{_fmt_num(s.cache_ge99_pct, 1)}%" for s in stats], "fraction in high-reuse regime")
    return "\n".join(lines)


def update_savings_md(savings_md_path: Path, table_markdown: str) -> None:
    content = savings_md_path.read_text(encoding="utf-8")
    start = content.find(TABLE_START)
    end = content.find(TABLE_END)
    if start < 0 or end < 0 or end <= start:
        raise ValueError(
            "SAVINGS.md markers not found. Add <!-- SAVINGS_TABLE_START --> and <!-- SAVINGS_TABLE_END --> around the table block."
        )

    start_block_end = start + len(TABLE_START)
    new_content = content[:start_block_end] + "\n\n" + table_markdown + "\n\n" + content[end:]
    savings_md_path.write_text(new_content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute reusable savings metrics table per model.")
    parser.add_argument(
        "--models",
        nargs="+",
        default=DEFAULT_MODELS,
        help="Model targets to include (served_target/model values).",
    )
    parser.add_argument(
        "--output-markdown",
        type=Path,
        default=None,
        help="Optional path to write only the generated markdown table.",
    )
    parser.add_argument(
        "--update-savings-md",
        action="store_true",
        help="Update SAVINGS.md table between SAVINGS_TABLE markers.",
    )
    parser.add_argument(
        "--savings-md",
        type=Path,
        default=ROOT / "SAVINGS.md",
        help="Path to SAVINGS markdown file for --update-savings-md.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stats = compute_model_stats(args.models)
    table = build_markdown_table(stats)

    print(table)

    if args.output_markdown is not None:
        args.output_markdown.write_text(table + "\n", encoding="utf-8")

    if args.update_savings_md:
        update_savings_md(args.savings_md, table)
        print(f"\nUpdated {args.savings_md}")


if __name__ == "__main__":
    main()
