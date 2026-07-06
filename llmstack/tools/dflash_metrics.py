#!/usr/bin/env python3
"""Compute DFlash summary metrics and optionally update DFLASH.md blocks."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from llmstack.tools.plot_dflash import _prepare_frame, _resolve_timings_csv


ROOT = Path(__file__).resolve().parents[2]

CORE_START = "<!-- DFLASH_CORE_TABLE_START -->"
CORE_END = "<!-- DFLASH_CORE_TABLE_END -->"
CACHE_BAND_START = "<!-- DFLASH_CACHE_BAND_BLOCK_START -->"
CACHE_BAND_END = "<!-- DFLASH_CACHE_BAND_BLOCK_END -->"
UNCACHED_BAND_START = "<!-- DFLASH_UNCACHED_BAND_BLOCK_START -->"
UNCACHED_BAND_END = "<!-- DFLASH_UNCACHED_BAND_BLOCK_END -->"
MODEL_TABLE_START = "<!-- DFLASH_MODEL_TABLE_START -->"
MODEL_TABLE_END = "<!-- DFLASH_MODEL_TABLE_END -->"

CACHE_BANDS = [(80, 90), (90, 95), (95, 99), (99, 100.000001)]
UNCACHED_BANDS = [(-0.1, 100), (100, 500), (500, 1000), (1000, 5000), (5000, 10000), (10000, 20000)]


def _fmt_num(value: float, digits: int = 2) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:.{digits}f}"


def _fmt_int(value: float) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:,.0f}"


def _load_raw_and_clean() -> tuple[pd.DataFrame, pd.DataFrame]:
    csv_path = _resolve_timings_csv()
    raw = pd.read_csv(csv_path)
    raw = raw[raw["backend"] == "dflash"].copy()
    clean = _prepare_frame(csv_path)
    return raw, clean


def build_core_table(raw: pd.DataFrame, clean: pd.DataFrame) -> str:
    removed = len(raw) - len(clean)
    lines = [
        "| Metric | Value |",
        "|---|---:|",
        f"| dflash rows in CSV | {_fmt_int(len(raw))} |",
        f"| clean dflash rows | {_fmt_int(len(clean))} |",
        f"| parser outliers removed | {_fmt_int(removed)} |",
        f"| sessions | {_fmt_int(clean['session_id'].nunique())} |",
    ]
    return "\n".join(lines)


def build_logs_table(clean: pd.DataFrame) -> str:
    lines = [
        "| Metric | Value |",
        "|---|---:|",
        f"| Cache-hit median | {_fmt_num(clean['cache_hit_pct'].median())}% |",
        f"| Cache-hit mean | {_fmt_num(clean['cache_hit_pct'].mean())}% |",
        f"| Prefill median | {_fmt_num(clean['prefill_time_s'].median())} s |",
        f"| Prefill mean | {_fmt_num(clean['prefill_time_s'].mean())} s |",
        f"| Prefill 90th percentile | {_fmt_num(clean['prefill_time_s'].quantile(0.9))} s |",
        f"| Prefill <= 2 s | {_fmt_num((clean['prefill_time_s'] <= 2).mean() * 100.0, 1)}% |",
        f"| Prefill <= 5 s | {_fmt_num((clean['prefill_time_s'] <= 5).mean() * 100.0, 1)}% |",
        f"| Requests with >= 95% cache | {_fmt_num((clean['cache_hit_pct'] >= 95).mean() * 100.0, 1)}% |",
        f"| Requests with >= 99% cache | {_fmt_num((clean['cache_hit_pct'] >= 99).mean() * 100.0, 1)}% |",
    ]
    return "\n".join(lines)


def build_cache_band_block(clean: pd.DataFrame) -> str:
    lines = ["```text"]
    for low, high in CACHE_BANDS:
        rows = clean[(clean["cache_hit_pct"] >= low) & (clean["cache_hit_pct"] < high)]
        label = "99-100%" if low >= 99 else f"{int(low)}-{int(high)}%"
        lines.append(f"{label:<8} n={len(rows):>4} median_prefill={_fmt_num(rows['prefill_time_s'].median(), 2):>6}s")
    lines.append("```")
    return "\n".join(lines)


def build_uncached_band_block(clean: pd.DataFrame) -> str:
    lines = ["```text"]
    for low, high in UNCACHED_BANDS:
        rows = clean[(clean["uncached_tokens"] > low) & (clean["uncached_tokens"] <= high)]
        label = f"<= {int(high)}"
        lines.append(f"{label:<9} n={len(rows):>4} median_prefill={_fmt_num(rows['prefill_time_s'].median(), 2):>6}s")
    lines.append("```")
    return "\n".join(lines)


def build_model_table(clean: pd.DataFrame, *, min_rows: int) -> str:
    lines = [
        "| Target | Rows | Median prefill | p90 prefill | Median cache hit | Share >=99% cache |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    grouped = clean.groupby("served_target", sort=True)
    for target, rows in grouped:
        if len(rows) < min_rows:
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{target}`",
                    _fmt_int(len(rows)),
                    f"{_fmt_num(rows['prefill_time_s'].median())} s",
                    f"{_fmt_num(rows['prefill_time_s'].quantile(0.9))} s",
                    f"{_fmt_num(rows['cache_hit_pct'].median())}%",
                    f"{_fmt_num((rows['cache_hit_pct'] >= 99).mean() * 100.0, 1)}%",
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _replace_between_markers(content: str, start: str, end: str, payload: str) -> str:
    start_idx = content.find(start)
    end_idx = content.find(end)
    if start_idx < 0 or end_idx < 0 or end_idx <= start_idx:
        raise ValueError(f"Marker block not found or malformed: {start} / {end}")
    pivot = start_idx + len(start)
    return content[:pivot] + "\n\n" + payload + "\n\n" + content[end_idx:]


def update_dflash_md(path: Path, *, core: str, logs: str, cache_band: str, uncached_band: str, model_table: str) -> None:
    content = path.read_text(encoding="utf-8")
    # Replace first static "Clean sample used here" table and first "What the logs tell us" table by marker blocks.
    content = _replace_between_markers(content, CORE_START, CORE_END, core)
    content = _replace_between_markers(content, "<!-- DFLASH_LOGS_TABLE_START -->", "<!-- DFLASH_LOGS_TABLE_END -->", logs)
    content = _replace_between_markers(content, CACHE_BAND_START, CACHE_BAND_END, cache_band)
    content = _replace_between_markers(content, UNCACHED_BAND_START, UNCACHED_BAND_END, uncached_band)
    content = _replace_between_markers(content, MODEL_TABLE_START, MODEL_TABLE_END, model_table)
    path.write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute DFlash metrics and optionally update DFLASH.md")
    parser.add_argument("--update-dflash-md", action="store_true", help="Update DFLASH.md marker blocks")
    parser.add_argument("--dflash-md", type=Path, default=ROOT / "DFLASH.md", help="Path to DFLASH.md")
    parser.add_argument("--min-model-rows", type=int, default=100, help="Minimum rows for model table inclusion")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw, clean = _load_raw_and_clean()

    core = build_core_table(raw, clean)
    logs = build_logs_table(clean)
    cache_band = build_cache_band_block(clean)
    uncached_band = build_uncached_band_block(clean)
    model_table = build_model_table(clean, min_rows=args.min_model_rows)

    print(core)
    print("\n" + logs)
    print("\n" + cache_band)
    print("\n" + uncached_band)
    print("\n" + model_table)

    if args.update_dflash_md:
        update_dflash_md(
            args.dflash_md,
            core=core,
            logs=logs,
            cache_band=cache_band,
            uncached_band=uncached_band,
            model_table=model_table,
        )
        print(f"\nUpdated {args.dflash_md}")


if __name__ == "__main__":
    main()
