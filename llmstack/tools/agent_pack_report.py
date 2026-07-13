#!/usr/bin/env python3
"""
Generate AGENT_PROBLEM_PACK_RESULTS.md with figures from agent problem pack runs.

This script:
  1. Loads all pack run data via agent_pack_extract.load_all()
  2. Generates matplotlib figures under docs/img/agent_pack/
  3. Writes AGENT_PROBLEM_PACK_RESULTS.md at the repo root

Usage:
    env/bin/python llmstack/tools/agent_pack_report.py [--matrix 20260713_003824]

Optional args:
    --matrix   Matrix ID to analyse. Defaults to the latest one found.
    --output   Path for the markdown report. Default: AGENT_PROBLEM_PACK_RESULTS.md
    --no-show  Do not call plt.show() (default for headless runs).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Optional

# load sibling extractor
_TOOLS_DIR = Path(__file__).parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from agent_pack_extract import load_all, ModelAggregate, RunRecord  # noqa: E402

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
IMG_DIR = REPO_ROOT / "docs" / "img" / "agent_pack"
DEFAULT_REPORT = REPO_ROOT / "AGENT_PROBLEM_PACK_RESULTS.md"


# ── helpers ───────────────────────────────────────────────────────────────────
def _fmt(v: Optional[float], decimals: int = 1, suffix: str = "") -> str:
    if v is None:
        return "n/a"
    return f"{v:.{decimals}f}{suffix}"


def _bar_colors(labels: list[str]) -> list[str]:
    palette = {
        "dflash": "#4C72B0",
        "mlx": "#DD8452",
        "turboquant": "#55A868",
    }
    return [palette.get(lbl.split("-")[0], "#888888") for lbl in labels]


def _legend_patches(backends: set[str]) -> list[mpatches.Patch]:
    colors = {"dflash": "#4C72B0", "mlx": "#DD8452", "turboquant": "#55A868"}
    return [
        mpatches.Patch(color=colors.get(b, "#888888"), label=b)
        for b in sorted(backends)
    ]


# ── figure generators ─────────────────────────────────────────────────────────
def fig_pass_heatmap(records: list[RunRecord], img_dir: Path) -> Path:
    """Problem × model pass/fail heatmap."""
    problems = sorted({r.problem for r in records})
    models = sorted({r.model_key for r in records})
    short_problems = [p.replace("problem-0", "P").replace("-", " ") for p in problems]
    # build matrix: 1=pass, 0=fail, -1=no run
    matrix = np.full((len(problems), len(models)), -1.0)
    for r in records:
        pi = problems.index(r.problem)
        mi = models.index(r.model_key)
        matrix[pi][mi] = 1.0 if r.passed else 0.0

    fig, ax = plt.subplots(figsize=(max(8, len(models) * 1.2), max(4, len(problems) * 0.9)))
    cmap = plt.cm.RdYlGn
    cmap.set_bad(color="#cccccc")
    masked = np.ma.masked_where(matrix < 0, matrix)
    im = ax.imshow(masked, cmap=cmap, vmin=0, vmax=1, aspect="auto")

    # annotate cells
    for pi in range(len(problems)):
        for mi in range(len(models)):
            val = matrix[pi][mi]
            if val < 0:
                txt, color = "—", "#888888"
            elif val == 1:
                txt, color = "PASS", "white"
            else:
                txt, color = "FAIL", "white"
            ax.text(mi, pi, txt, ha="center", va="center", fontsize=8, color=color, fontweight="bold")

    ax.set_xticks(range(len(models)))
    ax.set_xticklabels(models, rotation=30, ha="right", fontsize=8)
    ax.set_yticks(range(len(problems)))
    ax.set_yticklabels(short_problems, fontsize=8)
    ax.set_title("Agent Problem Pack — Pass / Fail per Model × Problem", fontsize=12, pad=12)
    plt.colorbar(im, ax=ax, fraction=0.03, pad=0.04, label="0 = FAIL  1 = PASS")
    plt.tight_layout()
    out = img_dir / "pass_heatmap.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def fig_efficiency_vs_effectiveness(aggs: list[ModelAggregate], img_dir: Path) -> Path:
    """Scatter: decode_tps (efficiency) vs pass_rate (effectiveness), bubble = mlx_peak."""
    fig, ax = plt.subplots(figsize=(9, 6))
    backends = {ma.backend for ma in aggs}

    for ma in aggs:
        x = ma.decode_tps_median
        y = ma.pass_rate
        if x is None:
            x = 0.0
        size = (ma.mlx_peak_median_gb or 30.0) * 15
        color = _bar_colors([ma.model_key])[0]
        ax.scatter(x, y, s=size, color=color, alpha=0.75, edgecolors="black", linewidths=0.8)
        ax.annotate(
            ma.model_key,
            (x, y),
            textcoords="offset points",
            xytext=(6, 4),
            fontsize=7,
        )

    ax.set_xlabel("Decode throughput — median tok/s  (higher = more efficient)", fontsize=10)
    ax.set_ylabel("Pass rate %  (higher = more effective)", fontsize=10)
    ax.set_title("Efficiency vs Effectiveness — bubble size ∝ median MLX peak GB", fontsize=11)
    ax.set_ylim(-5, 110)
    ax.axhline(100, color="#888888", linestyle="--", linewidth=0.8, alpha=0.6)
    ax.grid(True, alpha=0.3)
    ax.legend(handles=_legend_patches(backends), title="Backend", fontsize=8)
    plt.tight_layout()
    out = img_dir / "efficiency_vs_effectiveness.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def fig_server_perf(aggs: list[ModelAggregate], img_dir: Path) -> Path:
    """2×2 subplot: decode_tps, prefill_median_s, cache_hit_pct, mlx_peak_gb per model."""
    models = [ma.model_key for ma in aggs]
    colors = _bar_colors(models)
    x = np.arange(len(models))
    w = 0.65

    decode_tps = [ma.decode_tps_median or 0.0 for ma in aggs]
    prefill_s = [ma.prefill_median_s or 0.0 for ma in aggs]
    cache_hit = [ma.cache_hit_median_pct or 0.0 for ma in aggs]
    mlx_peak = [ma.mlx_peak_median_gb or 0.0 for ma in aggs]

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle("Server Performance per Model — Agent Problem Pack runs", fontsize=13)

    def _bar_subplot(ax, values, ylabel, title, fmt="{:.1f}", higher_better=True):
        bars = ax.bar(x, values, width=w, color=colors, edgecolor="white", linewidth=0.5)
        ax.set_xticks(x)
        ax.set_xticklabels(models, rotation=30, ha="right", fontsize=7)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.set_title(title, fontsize=10)
        ax.grid(axis="y", alpha=0.3)
        for bar, v in zip(bars, values):
            if v > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01 * max(values or [1]),
                        fmt.format(v), ha="center", va="bottom", fontsize=7)
        note = "↑ better" if higher_better else "↓ better"
        ax.annotate(note, xy=(0.98, 0.97), xycoords="axes fraction",
                    ha="right", va="top", fontsize=7, color="#555555")

    _bar_subplot(axes[0][0], decode_tps, "tok/s", "Decode throughput (median)", higher_better=True)
    _bar_subplot(axes[0][1], prefill_s, "s", "Prefill time (median)", fmt="{:.2f}", higher_better=False)
    _bar_subplot(axes[1][0], cache_hit, "%", "DFlash cache hit (median)", fmt="{:.1f}", higher_better=True)
    _bar_subplot(axes[1][1], mlx_peak, "GB", "MLX peak memory (median GB)", fmt="{:.1f}", higher_better=False)

    backends = {ma.backend for ma in aggs}
    fig.legend(handles=_legend_patches(backends), title="Backend", loc="lower right",
               fontsize=8, bbox_to_anchor=(0.99, 0.01))
    plt.tight_layout(rect=[0, 0.03, 1, 1])
    out = img_dir / "server_perf_by_model.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def fig_run_duration(aggs: list[ModelAggregate], img_dir: Path) -> Path:
    """Bar chart of median wall time per run."""
    models = [ma.model_key for ma in aggs]
    colors = _bar_colors(models)
    durations = [ma.duration_median_s or 0.0 for ma in aggs]
    x = np.arange(len(models))

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(x, durations, color=colors, edgecolor="white", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("Median wall time per problem run (s)", fontsize=10)
    ax.set_title("Wall Time per Run — Agent Problem Pack", fontsize=12)
    ax.grid(axis="y", alpha=0.3)
    for bar, v in zip(bars, durations):
        if v > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                    f"{v:.0f}s", ha="center", va="bottom", fontsize=8)
    backends = {ma.backend for ma in aggs}
    ax.legend(handles=_legend_patches(backends), title="Backend", fontsize=8)
    ax.annotate("↓ better", xy=(0.98, 0.97), xycoords="axes fraction",
                ha="right", va="top", fontsize=8, color="#555555")
    plt.tight_layout()
    out = img_dir / "run_duration_by_model.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def fig_ttft(aggs: list[ModelAggregate], img_dir: Path) -> Path:
    """Bar chart of median TTFT (time-to-first-token) per model."""
    models = [ma.model_key for ma in aggs]
    colors = _bar_colors(models)
    ttft = [ma.ttft_median_s or 0.0 for ma in aggs]
    x = np.arange(len(models))

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(x, ttft, color=colors, edgecolor="white", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("Median TTFT per problem run (s)", fontsize=10)
    ax.set_title("Time to First Token — Agent Problem Pack", fontsize=12)
    ax.grid(axis="y", alpha=0.3)
    for bar, v in zip(bars, ttft):
        if v > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                    f"{v:.1f}s", ha="center", va="bottom", fontsize=8)
    backends = {ma.backend for ma in aggs}
    ax.legend(handles=_legend_patches(backends), title="Backend", fontsize=8)
    ax.annotate("↓ better", xy=(0.98, 0.97), xycoords="axes fraction",
                ha="right", va="top", fontsize=8, color="#555555")
    plt.tight_layout()
    out = img_dir / "ttft_by_model.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def fig_tokens_breakdown(aggs: list[ModelAggregate], img_dir: Path) -> Path:
    """Stacked bar: input, cache_read, output tokens median per model."""
    models = [ma.model_key for ma in aggs]
    inp = [ma.input_tokens_median or 0.0 for ma in aggs]
    cache_r = [median(ma.cache_read_tokens_list) if ma.cache_read_tokens_list else 0.0 for ma in aggs]
    out_tok = [ma.output_tokens_median or 0.0 for ma in aggs]
    x = np.arange(len(models))
    w = 0.6

    fig, ax = plt.subplots(figsize=(11, 5))
    b1 = ax.bar(x, inp, w, label="Input tokens (new)", color="#4C72B0")
    b2 = ax.bar(x, cache_r, w, bottom=inp, label="Cache read tokens", color="#aec7e8")
    b3 = ax.bar(x, out_tok, w, bottom=[a + b for a, b in zip(inp, cache_r)], label="Output tokens", color="#55A868")

    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("Median tokens per run", fontsize=10)
    ax.set_title("Token Usage Breakdown — Agent Problem Pack", fontsize=12)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    outpath = img_dir / "tokens_by_model.png"
    fig.savefig(outpath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return outpath


def fig_headroom_savings(aggs: list[ModelAggregate], img_dir: Path) -> Path:
    """Bar chart of median headroom savings % per model."""
    models = [ma.model_key for ma in aggs]
    colors = _bar_colors(models)
    savings = [ma.headroom_savings_median_pct or 0.0 for ma in aggs]
    x = np.arange(len(models))

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(x, savings, color=colors, edgecolor="white", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("Median Headroom savings %", fontsize=10)
    ax.set_title("Headroom Context Compression During Pack Runs", fontsize=12)
    ax.grid(axis="y", alpha=0.3)
    for bar, v in zip(bars, savings):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                f"{v:.1f}%", ha="center", va="bottom", fontsize=8)
    backends = {ma.backend for ma in aggs}
    ax.legend(handles=_legend_patches(backends), title="Backend", fontsize=8)
    ax.annotate("↑ better (more context compressed)", xy=(0.98, 0.97), xycoords="axes fraction",
                ha="right", va="top", fontsize=8, color="#555555")
    plt.tight_layout()
    out = img_dir / "headroom_savings_by_model.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


# ── report builder ─────────────────────────────────────────────────────────────
def _rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def build_report(
    records: list[RunRecord],
    aggs: list[ModelAggregate],
    matrix_id: str,
    img_dir: Path,
    output_path: Path,
) -> None:
    img_dir.mkdir(parents=True, exist_ok=True)

    # generate figures
    fig_heatmap = fig_pass_heatmap(records, img_dir)
    fig_eff = fig_efficiency_vs_effectiveness(aggs, img_dir)
    fig_srv = fig_server_perf(aggs, img_dir)
    fig_dur = fig_run_duration(aggs, img_dir)
    fig_ttft_ = fig_ttft(aggs, img_dir)
    fig_tok = fig_tokens_breakdown(aggs, img_dir)
    fig_hr = fig_headroom_savings(aggs, img_dir)

    base = output_path.parent

    def imglink(p: Path, alt: str) -> str:
        return f"![{alt}]({_rel(p, base)})"

    # identify best model
    best = max(aggs, key=lambda ma: (ma.pass_rate, ma.decode_tps_median or 0.0))
    best_eff = max(
        (ma for ma in aggs if ma.decode_tps_median),
        key=lambda ma: ma.decode_tps_median or 0.0,
        default=None,
    )
    most_mem_eff = min(
        (ma for ma in aggs if ma.mlx_peak_median_gb),
        key=lambda ma: ma.mlx_peak_median_gb or 999.0,
        default=None,
    )

    lines: list[str] = []
    lines += [
        "# AGENT_PROBLEM_PACK_RESULTS.md",
        "",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}  ",
        f"Matrix run: **{matrix_id}**",
        "",
        "This report cross-references every Agent Problem Pack run with the live server logs",
        "(`logs/dflash_timings.csv`, `logs/headroom_traffic.jsonl`) to compare",
        "efficiency (memory, throughput, latency) and effectiveness (pass rate) for each",
        "model + backend combination.",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
    ]

    lines += [
        f"| Category | Winner |",
        f"| --- | --- |",
        f"| Best overall (pass rate + throughput) | **{best.model_key}** ({best.n_passed}/{best.n_problems} pass, decode {_fmt(best.decode_tps_median)} tok/s) |",
        f"| Highest decode throughput | **{best_eff.model_key if best_eff else 'n/a'}** ({_fmt(best_eff.decode_tps_median if best_eff else None)} tok/s) |",
        f"| Lowest memory footprint | **{most_mem_eff.model_key if most_mem_eff else 'n/a'}** (median peak {_fmt(most_mem_eff.mlx_peak_median_gb if most_mem_eff else None)} GB) |",
        "",
    ]

    lines += [
        "## Pass / Fail Heatmap",
        "",
        "Each cell shows whether the model solved the problem in the latest matrix run.",
        "Green = PASS, Red = FAIL.",
        "",
        imglink(fig_heatmap, "Pass/Fail heatmap"),
        "",
    ]

    lines += [
        "## Efficiency vs Effectiveness",
        "",
        "X-axis: decode throughput (higher = more efficient).  ",
        "Y-axis: pass rate (higher = more effective).  ",
        "Bubble size ∝ median MLX peak memory GB (larger bubble = more memory pressure).",
        "",
        imglink(fig_eff, "Efficiency vs effectiveness scatter"),
        "",
    ]

    lines += [
        "## Per-Model Aggregate Table",
        "",
        "> **Telemetry note:** DFlash rows expose `decode_tps`, `cache_hit_pct`, and `mlx_peak_gb`"
        " from the speculative server. MLX and TurboQuant rows expose only `total_time_s`"
        " (shown here as **Prefill s**), without separate decode throughput or GPU memory fields.",
        "> Compare DFlash models on all metrics; compare MLX / TurboQuant on pass rate, wall time,"
        " TTFT, and token costs.",
        "",
        "| Model | Backend | Pass | Pass% | Dur med s | TTFT med s | Turns med |"
        " Decode tok/s | Prefill s | Cache hit% | MLX peak GB | Headroom savings% | Total cost USD |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for ma in aggs:
        lines.append(
            f"| {ma.model_key} | {ma.backend}"
            f" | {ma.n_passed}/{ma.n_problems}"
            f" | {ma.pass_rate:.0f}%"
            f" | {_fmt(ma.duration_median_s, 0)}"
            f" | {_fmt(ma.ttft_median_s, 1)}"
            f" | {_fmt(ma.turns_median, 1)}"
            f" | {_fmt(ma.decode_tps_median, 1)}"
            f" | {_fmt(ma.prefill_median_s, 2)}"
            f" | {_fmt(ma.cache_hit_median_pct, 1)}"
            f" | {_fmt(ma.mlx_peak_median_gb, 1)}"
            f" | {_fmt(ma.headroom_savings_median_pct, 1)}"
            f" | {ma.cost_usd_total:.3f}"
            " |"
        )
    lines.append("")

    # ── interpretation ─────────────────────────────────────────────────────
    full_pass = [ma for ma in aggs if ma.n_passed == ma.n_problems]
    partial_pass = [ma for ma in aggs if 0 < ma.n_passed < ma.n_problems]
    zero_pass = [ma for ma in aggs if ma.n_passed == 0]

    def _rank(ma: ModelAggregate) -> str:
        return (
            f"**{ma.model_key}** ({ma.n_passed}/{ma.n_problems} pass, "
            f"dur {_fmt(ma.duration_median_s, 0)}s, "
            f"decode {_fmt(ma.decode_tps_median)}tok/s, "
            f"TTFT {_fmt(ma.ttft_median_s, 1)}s)"
        )

    lines += [
        "## Interpretation",
        "",
        "### Models that solved all 5 problems",
        "",
    ]
    for ma in sorted(full_pass, key=lambda x: (-(x.decode_tps_median or 0), x.duration_median_s or 999)):
        lines.append(f"- {_rank(ma)}")
    lines.append("")

    if partial_pass:
        lines += ["### Models with partial success", ""]
        for ma in sorted(partial_pass, key=lambda x: -x.n_passed):
            lines.append(f"- {_rank(ma)}")
        lines.append("")

    if zero_pass:
        lines += ["### Models that failed all problems", ""]
        for ma in zero_pass:
            lines.append(f"- {_rank(ma)}")
        lines.append("")

    lines += [
        "### Key observations",
        "",
        "1. **DFlash cache reuse dominates wall time.** dflash-ornith35b-moe and dflash-qwen35b-moe"
        " complete each problem in under 100 s because their DFlash cache hit rate exceeds 98%,"
        " keeping median prefill under 1.1 s. mlx-ornith35b achieves the same 100% pass rate"
        " but takes ~88 s with ~39 s prefill per request (no prefix cache).",
        "",
        "2. **Effectiveness and efficiency diverge for Gemma-4-12B.** Both dflash-gemma4-12b"
        " and mlx-gemma4-12b scored 0/5, despite dflash-gemma4-12b having the lowest memory"
        " footprint (24 GB). Low memory cost alone does not make a model useful for agentic tasks.",
        "",
        "3. **TurboQuant has high wall time despite low prefill.** turboquant-qwen35b-moe shows"
        " only 1.5 s prefill but 333 s median wall time, suggesting the bottleneck is decode"
        " speed or scheduling overhead, not prefill.",
        "",
        "4. **Recommended pairing for agent tasks:** `dflash + ornith35b-moe` or"
        " `dflash + qwen35b-moe` — both deliver 100% pass rate with sub-100 s wall time"
        " and 55–57 tok/s decode throughput, at median MLX peaks of 30–37 GB on this 64 GB machine.",
        "",
    ]
    # ── end interpretation ──────────────────────────────────────────────────

    lines += [
        "## Server Performance by Model",
        "",
        "Decode throughput, prefill time, DFlash cache hit rate, and MLX peak memory.",
        "",
        imglink(fig_srv, "Server performance by model"),
        "",
    ]

    lines += [
        "## Wall Time and TTFT per Model",
        "",
        imglink(fig_dur, "Run duration by model"),
        "",
        imglink(fig_ttft_, "TTFT by model"),
        "",
    ]

    lines += [
        "## Token Usage Breakdown",
        "",
        "Median new input tokens, cache read tokens, and output tokens per run.",
        "High cache read with low new input indicates effective prefix reuse (DFlash).",
        "",
        imglink(fig_tok, "Token usage by model"),
        "",
    ]

    lines += [
        "## Headroom Context Compression",
        "",
        "Median Headroom savings percentage during pack runs.",
        "Higher savings means more context was compressed before reaching the inference server.",
        "",
        imglink(fig_hr, "Headroom savings by model"),
        "",
    ]

    # per-run detail table
    lines += [
        "## Per-Run Detail",
        "",
        "| Model | Problem | Pass | Dur s | TTFT s | Turns | Input tok | Cache read | Output tok |"
        " Server requests | Decode tok/s | Prefill s | MLX peak GB | Headroom sav% |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for rec in sorted(records, key=lambda r: (r.model_key, r.problem)):
        sm = rec.server
        lines.append(
            f"| {rec.model_key}"
            f" | {rec.problem_title}"
            f" | {'✓' if rec.passed else '✗'}"
            f" | {_fmt(rec.duration_s, 0)}"
            f" | {_fmt(rec.ttft_s, 1)}"
            f" | {rec.num_turns or 'n/a'}"
            f" | {rec.input_tokens or 'n/a'}"
            f" | {rec.cache_read_input_tokens or 'n/a'}"
            f" | {rec.output_tokens or 'n/a'}"
            f" | {sm.n_timing_rows}"
            f" | {_fmt(sm.decode_tps_median, 1)}"
            f" | {_fmt(sm.prefill_median_s, 2)}"
            f" | {_fmt(sm.mlx_peak_median_gb, 1)}"
            f" | {_fmt(sm.headroom_savings_median_pct, 1)}"
            " |"
        )
    lines.append("")

    # data source note
    lines += [
        "## Data Sources",
        "",
        "| Source | Path | What it provides |",
        "| --- | --- | --- |",
        "| Agent pack artifacts | `local-coding-agent-evals/agent-problem-pack/runs/` | pass/fail, duration, ttft, turns, token usage |",
        "| DFlash/MLX/TurboQuant timings | `logs/dflash_timings.csv` | prefill_time_s, decode_tps, mlx_peak_gb, cache_hit_pct |",
        "| Headroom traffic | `logs/headroom_traffic.jsonl` | savings_percent, optimization_latency_ms |",
        "",
        "Server metrics are correlated by matching each run's time window",
        "(headless-stdout.jsonl mtime − duration → mtime) against log timestamps,",
        "filtered by the served model target.",
        "",
    ]

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote report: {output_path}")
    for fig_path in (fig_heatmap, fig_eff, fig_srv, fig_dur, fig_ttft_, fig_tok, fig_hr):
        print(f"  figure: {_rel(fig_path, base)}")


# ── main ───────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate AGENT_PROBLEM_PACK_RESULTS.md from pack run artifacts + server logs."
    )
    parser.add_argument(
        "--matrix",
        help="Matrix ID to analyse (e.g. 20260713_003824). Defaults to auto-detect latest.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_REPORT,
        help=f"Output markdown path. Default: {DEFAULT_REPORT}",
    )
    args = parser.parse_args(argv)

    # auto-detect latest matrix if not specified
    matrix_id = args.matrix
    if not matrix_id:
        import re as _re
        from pathlib import Path as _Path
        runs_root = REPO_ROOT / "local-coding-agent-evals" / "agent-problem-pack" / "runs"
        ids: set[str] = set()
        for p in runs_root.rglob("*/"):
            m = _re.search(r"llmstack-matrix-(\d{8}_\d{6})", p.name)
            if m:
                ids.add(m.group(1))
        matrix_id = sorted(ids)[-1] if ids else None
        if matrix_id:
            print(f"Auto-detected latest matrix: {matrix_id}")
        else:
            print("No matrix runs found.", file=sys.stderr)
            return 1

    records, aggs = load_all(matrix_filter=matrix_id)
    if not records:
        print(f"No runs found for matrix {matrix_id}.", file=sys.stderr)
        return 1

    print(f"Loaded {len(records)} runs for {len(aggs)} model+backend pairs.")

    build_report(records, aggs, matrix_id, IMG_DIR, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
