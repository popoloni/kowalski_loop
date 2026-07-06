#!/usr/bin/env python3
"""Qwen A/B comparison + crash-risk modeling with auto-updated markdown blocks."""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from llmstack.tools.plot_dflash import _prepare_frame, _resolve_timings_csv


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "llmstack_config.json"
IMG_DIR = ROOT / "docs" / "img" / "llm_comparison"

AB_TABLE_START = "<!-- LLM_AB_TABLE_START -->"
AB_TABLE_END = "<!-- LLM_AB_TABLE_END -->"
BALANCE_TABLE_START = "<!-- LLM_BALANCE_TABLE_START -->"
BALANCE_TABLE_END = "<!-- LLM_BALANCE_TABLE_END -->"
THROUGHPUT_TABLE_START = "<!-- LLM_THROUGHPUT_TABLE_START -->"
THROUGHPUT_TABLE_END = "<!-- LLM_THROUGHPUT_TABLE_END -->"
RISK_TABLE_START = "<!-- LLM_RISK_TABLE_START -->"
RISK_TABLE_END = "<!-- LLM_RISK_TABLE_END -->"
MODEL_NOTE_START = "<!-- LLM_MODEL_NOTE_START -->"
MODEL_NOTE_END = "<!-- LLM_MODEL_NOTE_END -->"

QWEN_27 = "mlx-community/Qwen3.6-27B-4bit"
QWEN_35 = "mlx-community/Qwen3.6-35B-A3B-4bit"


@dataclass(frozen=True)
class Effect:
    metric: str
    estimate: float
    ci_low: float
    ci_high: float
    unit: str


def _fmt_num(value: float, digits: int = 2) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:.{digits}f}"


def _fmt_int(value: float) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:,.0f}"


def _bootstrap_ci(values: np.ndarray, n_boot: int = 1000, alpha: float = 0.05) -> tuple[float, float, float]:
    if len(values) == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(42)
    idx = rng.integers(0, len(values), size=(n_boot, len(values)))
    means = values[idx].mean(axis=1)
    lo = float(np.quantile(means, alpha / 2.0))
    hi = float(np.quantile(means, 1.0 - alpha / 2.0))
    return float(values.mean()), lo, hi


def _standardized_mean_diff(a: pd.Series, b: pd.Series) -> float:
    av = pd.to_numeric(a, errors="coerce").dropna().to_numpy()
    bv = pd.to_numeric(b, errors="coerce").dropna().to_numpy()
    if av.size == 0 or bv.size == 0:
        return float("nan")
    va = av.var(ddof=1) if av.size > 1 else 0.0
    vb = bv.var(ddof=1) if bv.size > 1 else 0.0
    pooled = math.sqrt(max((va + vb) / 2.0, 1e-12))
    return float((av.mean() - bv.mean()) / pooled)


def _load_qwen_clean_frame() -> pd.DataFrame:
    df = _prepare_frame(_resolve_timings_csv())
    df = df[df["served_target"].isin([QWEN_27, QWEN_35])].copy()
    df["log_prompt"] = np.log10(df["prompt_tokens"].clip(lower=1))
    df["log_uncached"] = np.log10(df["uncached_tokens"].clip(lower=1))
    return df


def _coarsen_and_pair(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["prompt_bin"] = pd.cut(work["prompt_tokens"], [0, 5000, 10000, 20000, 40000, 80000, 200000], include_lowest=True)
    work["cache_bin"] = pd.cut(work["cache_hit_pct"], [0, 80, 90, 95, 99, 100], include_lowest=True)
    work["prog_bin"] = pd.cut(work["session_progress"], [0.0, 0.25, 0.5, 0.75, 1.0], include_lowest=True)

    pairs: list[dict] = []
    strata = work.groupby(["prompt_bin", "cache_bin", "prog_bin"], observed=False)
    for key, chunk in strata:
        a = chunk[chunk["served_target"] == QWEN_35].copy().sort_values("timestamp")
        b = chunk[chunk["served_target"] == QWEN_27].copy().sort_values("timestamp")
        if a.empty or b.empty:
            continue

        # Greedy nearest pairing on uncached tokens inside each coarsened stratum.
        used_b: set[int] = set()
        b_idx = b.index.to_list()
        b_uncached = b["uncached_tokens"].to_dict()
        for ai, arow in a.iterrows():
            candidates = [idx for idx in b_idx if idx not in used_b]
            if not candidates:
                break
            nearest = min(candidates, key=lambda idx: abs(b_uncached[idx] - arow["uncached_tokens"]))
            brow = b.loc[nearest]
            used_b.add(nearest)
            pairs.append(
                {
                    "prompt_bin": str(key[0]),
                    "cache_bin": str(key[1]),
                    "prog_bin": str(key[2]),
                    "prefill_diff": float(arow["prefill_time_s"] - brow["prefill_time_s"]),
                    "decode_diff": float(arow["decode_time_s"] - brow["decode_time_s"]),
                    "decode_tps_diff": float(arow["decode_tps"] - brow["decode_tps"]),
                    "prefill_tps_diff": float(arow["prefill_real_tps"] - brow["prefill_real_tps"]),
                    "peak_diff": float(arow["mlx_peak_gb"] - brow["mlx_peak_gb"]),
                    "prompt_diff": float(arow["prompt_tokens"] - brow["prompt_tokens"]),
                    "cache_diff": float(arow["cache_hit_pct"] - brow["cache_hit_pct"]),
                    "uncached_diff": float(arow["uncached_tokens"] - brow["uncached_tokens"]),
                    "a_prefill": float(arow["prefill_time_s"]),
                    "b_prefill": float(brow["prefill_time_s"]),
                    "a_decode": float(arow["decode_time_s"]),
                    "b_decode": float(brow["decode_time_s"]),
                    "a_decode_tps": float(arow["decode_tps"]),
                    "b_decode_tps": float(brow["decode_tps"]),
                    "a_prefill_tps": float(arow["prefill_real_tps"]),
                    "b_prefill_tps": float(brow["prefill_real_tps"]),
                    "a_peak": float(arow["mlx_peak_gb"]),
                    "b_peak": float(brow["mlx_peak_gb"]),
                    "a_log_prompt": float(arow["log_prompt"]),
                    "b_log_prompt": float(brow["log_prompt"]),
                    "a_cache_hit": float(arow["cache_hit_pct"]),
                    "b_cache_hit": float(brow["cache_hit_pct"]),
                    "a_log_uncached": float(arow["log_uncached"]),
                    "b_log_uncached": float(brow["log_uncached"]),
                    "a_session_progress": float(arow["session_progress"]),
                    "b_session_progress": float(brow["session_progress"]),
                }
            )
    return pd.DataFrame(pairs)


def _fit_logistic(X: np.ndarray, y: np.ndarray, max_iter: int = 2000, lr: float = 0.01, l2: float = 1e-4) -> np.ndarray:
    beta = np.zeros(X.shape[1], dtype=float)
    for _ in range(max_iter):
        z = X @ beta
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -50, 50)))
        grad = (X.T @ (p - y)) / len(y)
        grad += l2 * beta
        beta -= lr * grad
    return beta


def _predict_prob(X: np.ndarray, beta: np.ndarray) -> np.ndarray:
    z = X @ beta
    return 1.0 / (1.0 + np.exp(-np.clip(z, -50, 50)))


def _roc_auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    y = np.asarray(y_true, dtype=float)
    s = np.asarray(y_score, dtype=float)
    pos = y == 1
    neg = y == 0
    n_pos = int(pos.sum())
    n_neg = int(neg.sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(s)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(s) + 1, dtype=float)
    rank_sum_pos = float(ranks[pos].sum())
    u = rank_sum_pos - (n_pos * (n_pos + 1) / 2.0)
    return float(u / (n_pos * n_neg))


def _brier_score(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(y_prob, dtype=float)
    if len(y) == 0:
        return float("nan")
    return float(np.mean((y - p) ** 2))


def _parse_crash_times() -> list[pd.Timestamp]:
    if not CONFIG_PATH.exists():
        return []
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    log_path = Path(cfg.get("dflash_log", "./logs/dflash_server.log"))
    if not log_path.is_absolute():
        log_path = (ROOT / log_path).resolve()
    if not log_path.exists():
        return []

    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    ts_regex = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
    crashes: list[pd.Timestamp] = []
    for i, line in enumerate(lines):
        if "Impacting Interactivity" not in line:
            continue
        ts: pd.Timestamp | None = None
        for j in range(max(0, i - 5), i + 1):
            m = ts_regex.search(lines[j])
            if m:
                ts = pd.to_datetime(m.group(1), errors="coerce", utc=True)
        if ts is not None and not pd.isna(ts):
            crashes.append(ts)

    # Deduplicate near-duplicate crash lines (restart storms).
    crashes = sorted(crashes)
    dedup: list[pd.Timestamp] = []
    for ts in crashes:
        if not dedup or (ts - dedup[-1]).total_seconds() > 900:
            dedup.append(ts)
    return dedup


def _risk_model(df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray, str, dict[str, float | str]]:
    work = df.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True, errors="coerce")
    crashes = _parse_crash_times()

    # Primary label: requests close to crash signatures.
    near = np.zeros(len(work), dtype=int)
    if crashes:
        for idx, ts in enumerate(work["timestamp"]):
            if pd.isna(ts):
                continue
            for cts in crashes:
                delta = (cts - ts).total_seconds()
                if 0 <= delta <= 15 * 60:
                    near[idx] = 1
                    break
    work["near_crash"] = near

    label_note = "near-crash-window"
    near_count = int(work["near_crash"].sum())
    peak_corr = float(work[["near_crash", "mlx_peak_gb"]].corr().iloc[0, 1]) if near_count > 0 else float("nan")

    # Fallback label if too sparse or weakly aligned with memory risk direction.
    if near_count < 200 or (not pd.isna(peak_corr) and peak_corr <= 0):
        work["near_crash"] = (work["mlx_peak_gb"] >= 48).astype(int)
        label_note = "high-risk-proxy(mlx_peak_gb>=48)"

    work["model_is_35"] = (work["served_target"] == QWEN_35).astype(int)
    work["log_prompt"] = np.log10(work["prompt_tokens"].clip(lower=1))
    work["log_uncached"] = np.log10(work["uncached_tokens"].clip(lower=1))
    work["prefill_tail"] = (work["prefill_time_s"] >= work["prefill_time_s"].quantile(0.95)).astype(int)

    X = np.column_stack(
        [
            np.ones(len(work)),
            work["mlx_peak_gb"].to_numpy(),
            work["log_prompt"].to_numpy(),
            work["log_uncached"].to_numpy(),
            work["prefill_tail"].to_numpy(),
            work["model_is_35"].to_numpy(),
        ]
    )
    y = work["near_crash"].to_numpy().astype(float)
    # Temporal split validation (first 80% train, last 20% test by timestamp).
    valid_ts = work["timestamp"].notna()
    time_sorted = work.loc[valid_ts].sort_values("timestamp").index.to_numpy()
    split_pos = int(len(time_sorted) * 0.8)
    split_pos = max(1, min(split_pos, max(len(time_sorted) - 1, 1))) if len(time_sorted) > 1 else 0
    train_idx = time_sorted[:split_pos]
    test_idx = time_sorted[split_pos:]

    temporal: dict[str, float | str] = {
        "cutoff": "n/a",
        "train_rows": float("nan"),
        "test_rows": float("nan"),
        "train_prev": float("nan"),
        "test_prev": float("nan"),
        "train_auc": float("nan"),
        "test_auc": float("nan"),
        "train_brier": float("nan"),
        "test_brier": float("nan"),
    }

    if len(train_idx) > 10 and len(test_idx) > 10:
        tr = work.loc[train_idx]
        te = work.loc[test_idx]
        X_train = np.column_stack(
            [
                np.ones(len(tr)),
                tr["mlx_peak_gb"].to_numpy(),
                tr["log_prompt"].to_numpy(),
                tr["log_uncached"].to_numpy(),
                tr["prefill_tail"].to_numpy(),
                tr["model_is_35"].to_numpy(),
            ]
        )
        y_train = tr["near_crash"].to_numpy().astype(float)
        X_test = np.column_stack(
            [
                np.ones(len(te)),
                te["mlx_peak_gb"].to_numpy(),
                te["log_prompt"].to_numpy(),
                te["log_uncached"].to_numpy(),
                te["prefill_tail"].to_numpy(),
                te["model_is_35"].to_numpy(),
            ]
        )
        y_test = te["near_crash"].to_numpy().astype(float)

        beta_train = _fit_logistic(X_train, y_train)
        p_train = _predict_prob(X_train, beta_train)
        p_test = _predict_prob(X_test, beta_train)

        temporal = {
            "cutoff": str(pd.to_datetime(te["timestamp"].iloc[0]).strftime("%Y-%m-%d %H:%M:%S UTC")),
            "train_rows": float(len(tr)),
            "test_rows": float(len(te)),
            "train_prev": float(y_train.mean() * 100.0),
            "test_prev": float(y_test.mean() * 100.0),
            "train_auc": _roc_auc(y_train, p_train),
            "test_auc": _roc_auc(y_test, p_test),
            "train_brier": _brier_score(y_train, p_train),
            "test_brier": _brier_score(y_test, p_test),
        }

    # Fit final model on full sample for report coefficients and risk curves.
    beta = _fit_logistic(X, y)
    work["risk_prob"] = _predict_prob(X, beta)
    return work, beta, label_note, temporal


def _plot_effects(effects: list[Effect]) -> None:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    names = [e.metric for e in effects]
    est = np.array([e.estimate for e in effects])
    lo = np.array([e.ci_low for e in effects])
    hi = np.array([e.ci_high for e in effects])
    y = np.arange(len(effects))

    fig, ax = plt.subplots(figsize=(8.8, 4.8))
    ax.errorbar(est, y, xerr=np.vstack([est - lo, hi - est]), fmt="o", color="#1f6feb", capsize=4)
    ax.axvline(0.0, color="#6b7280", ls="--", lw=1.0)
    ax.set_yticks(y, names)
    ax.set_xlabel("Matched A/B effect (35B-A3B minus 27B)")
    ax.set_title("Qwen A/B matched effects with bootstrap CI")
    ax.grid(True, axis="x", ls="--", alpha=0.25)
    fig.tight_layout()
    fig.savefig(IMG_DIR / "ab_effects.png", dpi=140)
    plt.close(fig)


def _plot_balance(before: dict[str, float], after: dict[str, float]) -> None:
    names = list(before.keys())
    xb = np.array([before[k] for k in names])
    xa = np.array([after[k] for k in names])
    y = np.arange(len(names))

    fig, ax = plt.subplots(figsize=(8.8, 4.8))
    ax.scatter(xb, y, color="#dc2626", label="before")
    ax.scatter(xa, y, color="#16a34a", label="after")
    ax.axvline(0.1, color="#6b7280", ls=":", lw=1)
    ax.axvline(-0.1, color="#6b7280", ls=":", lw=1)
    ax.set_yticks(y, names)
    ax.set_xlabel("Standardized mean difference")
    ax.set_title("Covariate balance before vs after matching")
    ax.grid(True, axis="x", ls="--", alpha=0.25)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(IMG_DIR / "ab_balance.png", dpi=140)
    plt.close(fig)


def _plot_throughput_effects(effects: list[Effect]) -> None:
    names = ["decode_tps", "prefill_real_tps"]
    est = np.array([e.estimate for e in effects])
    lo = np.array([e.ci_low for e in effects])
    hi = np.array([e.ci_high for e in effects])
    y = np.arange(len(effects))

    fig, ax = plt.subplots(figsize=(8.2, 3.6))
    ax.errorbar(est, y, xerr=np.vstack([est - lo, hi - est]), fmt="o", color="#059669", capsize=3)
    ax.axvline(0.0, color="#6b7280", ls="--", lw=1.0)
    ax.set_yticks(y, names)
    ax.set_xlabel("Matched throughput effect (35B-A3B minus 27B, tokens/s)")
    ax.set_title("Qwen throughput after matching")
    ax.grid(True, axis="x", ls="--", alpha=0.25)
    ax.margins(y=0.22)
    fig.tight_layout()
    fig.savefig(IMG_DIR / "throughput_effects.png", dpi=140)
    plt.close(fig)


def _plot_ab_stack(
    effects: list[Effect],
    before: dict[str, float],
    after: dict[str, float],
    throughput_effects: list[Effect],
) -> None:
    names = [e.metric for e in effects]
    est = np.array([e.estimate for e in effects])
    lo = np.array([e.ci_low for e in effects])
    hi = np.array([e.ci_high for e in effects])
    y = np.arange(len(effects))

    fig, axes = plt.subplots(
        2,
        1,
        figsize=(9.8, 7.6),
        gridspec_kw={"height_ratios": [1.15, 1.0], "hspace": 0.28},
        constrained_layout=False,
    )

    ax = axes[0]
    ax.errorbar(est, y, xerr=np.vstack([est - lo, hi - est]), fmt="o", color="#1f6feb", capsize=3)
    ax.axvline(0.0, color="#6b7280", ls="--", lw=1.0)
    ax.set_yticks(y, names)
    ax.set_xlabel("Matched A/B effect (35B-A3B minus 27B)")
    ax.set_title("A/B effects", pad=8)
    ax.grid(True, axis="x", ls="--", alpha=0.25)
    ax.margins(y=0.18)

    ax = axes[1]
    ax.scatter([before[k] for k in before], np.arange(len(before)), color="#dc2626", label="before", s=22)
    ax.scatter([after[k] for k in after], np.arange(len(after)), color="#16a34a", label="after", s=22)
    ax.axvline(0.1, color="#6b7280", ls=":", lw=1)
    ax.axvline(-0.1, color="#6b7280", ls=":", lw=1)
    ax.set_yticks(np.arange(len(before)), list(before.keys()))
    ax.set_xlabel("Standardized mean difference")
    ax.set_title("Balance diagnostics", pad=8)
    ax.grid(True, axis="x", ls="--", alpha=0.25)
    ax.legend(loc="lower right", fontsize=8)
    ax.margins(y=0.2)

    for axis in axes:
        axis.tick_params(axis="y", labelsize=9)
        axis.tick_params(axis="x", labelsize=9)

    fig.subplots_adjust(top=0.95, bottom=0.08, left=0.12, right=0.98)
    fig.savefig(IMG_DIR / "ab_stack.png", dpi=140)
    plt.close(fig)


def _plot_risk_curve(beta: np.ndarray, base_row_27: pd.Series, base_row_35: pd.Series) -> None:
    peaks = np.linspace(35, 56, 120)

    def probs(base: pd.Series, model_is_35: int) -> np.ndarray:
        X = np.column_stack(
            [
                np.ones_like(peaks),
                peaks,
                np.full_like(peaks, float(base["log_prompt"])),
                np.full_like(peaks, float(base["log_uncached"])),
                np.full_like(peaks, float(base["prefill_tail"])),
                np.full_like(peaks, float(model_is_35)),
            ]
        )
        z = X @ beta
        return 1.0 / (1.0 + np.exp(-np.clip(z, -50, 50)))

    p27 = probs(base_row_27, 0)
    p35 = probs(base_row_35, 1)

    fig, ax = plt.subplots(figsize=(8.8, 4.8))
    ax.plot(peaks, p27, color="#1f6feb", lw=2, label="Qwen3.6-27B")
    ax.plot(peaks, p35, color="#d97706", lw=2, label="Qwen3.6-35B-A3B")
    ax.axvline(48, color="#6b7280", ls=":", lw=1)
    ax.axvline(52, color="#dc2626", ls=":", lw=1)
    ax.set_xlabel("MLX peak memory (GB)")
    ax.set_ylabel("Predicted risk probability")
    ax.set_title("Predicted crash-risk curve vs memory peak")
    ax.grid(True, ls="--", alpha=0.25)
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(IMG_DIR / "crash_risk_curve.png", dpi=140)
    plt.close(fig)


def _replace_between_markers(content: str, start: str, end: str, payload: str) -> str:
    i = content.find(start)
    j = content.find(end)
    if i < 0 or j < 0 or j <= i:
        raise ValueError(f"Marker block not found or malformed: {start} / {end}")
    pivot = i + len(start)
    return content[:pivot] + "\n\n" + payload + "\n\n" + content[j:]


def _ab_table(effects: list[Effect], n_pairs: int) -> str:
    lines = [
        "| Outcome | Matched effect (35B-A3B - 27B) | 95% CI | Conclusive? |",
        "|---|---:|---:|---:|",
    ]
    for e in effects:
        conclusive = "yes" if (e.ci_low > 0 or e.ci_high < 0) else "no"
        lines.append(
            f"| {e.metric} | {_fmt_num(e.estimate)} {e.unit} | [{_fmt_num(e.ci_low)}, {_fmt_num(e.ci_high)}] {e.unit} | {conclusive} |"
        )
    lines.append(f"| Matched pairs | {_fmt_int(n_pairs)} | n/a | n/a |")
    return "\n".join(lines)


def _throughput_table(df: pd.DataFrame, effects: list[Effect], n_pairs: int) -> str:
    labels = {
        QWEN_35: "Qwen3.6-35B-A3B-4bit",
        QWEN_27: "Qwen3.6-27B-4bit",
    }
    raw_lines = [
        "| Model | decode_tps median | decode_tps p90 | prefill_real_tps median | prefill_real_tps p90 |",
        "|---|---:|---:|---:|---:|",
    ]
    for model in [QWEN_35, QWEN_27]:
        g = df[df["served_target"] == model]
        decode = pd.to_numeric(g["decode_tps"], errors="coerce").dropna()
        prefill = pd.to_numeric(g["prefill_real_tps"], errors="coerce").dropna()
        raw_lines.append(
            f"| {labels.get(model, model)} | {_fmt_num(float(decode.median()), 1)} | {_fmt_num(float(decode.quantile(0.9)), 1)} | {_fmt_num(float(prefill.median()), 1)} | {_fmt_num(float(prefill.quantile(0.9)), 1)} |"
        )

    effect_lines = [
        "| Throughput metric | Matched effect (35B-A3B - 27B) | 95% CI | Better when |",
        "|---|---:|---:|---|",
    ]
    for e in effects:
        effect_lines.append(
            f"| {e.metric} | {_fmt_num(e.estimate, 2)} {e.unit} | [{_fmt_num(e.ci_low, 2)}, {_fmt_num(e.ci_high, 2)}] {e.unit} | higher |"
        )
    effect_lines.append(f"| Matched pairs | {_fmt_int(n_pairs)} | n/a | n/a |")
    return "\n\n".join(["\n".join(raw_lines), "\n".join(effect_lines)])


def _balance_table(before: dict[str, float], after: dict[str, float]) -> str:
    lines = [
        "| Covariate | SMD before matching | SMD after matching |",
        "|---|---:|---:|",
    ]
    for name in before:
        lines.append(f"| {name} | {_fmt_num(before[name], 3)} | {_fmt_num(after[name], 3)} |")
    return "\n".join(lines)


def _risk_table(risk_df: pd.DataFrame, beta: np.ndarray, label_note: str, temporal: dict[str, float | str]) -> str:
    positives = int(risk_df["near_crash"].sum())
    total = int(len(risk_df))
    prevalence = positives / total * 100 if total else float("nan")
    test_prev = float(temporal["test_prev"])
    test_auc = float(temporal["test_auc"])
    unstable_temporal = pd.isna(test_prev) or test_prev < 1.0 or pd.isna(test_auc) or test_auc < 0.55
    reliability = "low (temporal split unstable)" if unstable_temporal else "acceptable"
    lines = [
        "| Item | Value |",
        "|---|---:|",
        f"| Risk label used | {label_note} |",
        f"| Positive events | {_fmt_int(positives)} |",
        f"| Positive prevalence | {_fmt_num(prevalence, 2)}% |",
        f"| Temporal split cutoff | {temporal['cutoff']} |",
        f"| Temporal train rows | {_fmt_int(temporal['train_rows'])} |",
        f"| Temporal test rows | {_fmt_int(temporal['test_rows'])} |",
        f"| Temporal train prevalence | {_fmt_num(float(temporal['train_prev']), 2)}% |",
        f"| Temporal test prevalence | {_fmt_num(float(temporal['test_prev']), 2)}% |",
        f"| Temporal train AUC | {_fmt_num(float(temporal['train_auc']), 3)} |",
        f"| Temporal test AUC | {_fmt_num(float(temporal['test_auc']), 3)} |",
        f"| Temporal train Brier | {_fmt_num(float(temporal['train_brier']), 4)} |",
        f"| Temporal test Brier | {_fmt_num(float(temporal['test_brier']), 4)} |",
        f"| Temporal reliability | {reliability} |",
        f"| Coef: mlx_peak_gb | {_fmt_num(beta[1], 3)} |",
        f"| Coef: log_prompt | {_fmt_num(beta[2], 3)} |",
        f"| Coef: log_uncached | {_fmt_num(beta[3], 3)} |",
        f"| Coef: prefill_tail | {_fmt_num(beta[4], 3)} |",
        f"| Coef: model_is_35 | {_fmt_num(beta[5], 3)} |",
    ]
    return "\n".join(lines)


def update_markdown(md_path: Path, ab: str, balance: str, throughput: str, risk: str, note: str) -> None:
    content = md_path.read_text(encoding="utf-8")
    content = _replace_between_markers(content, AB_TABLE_START, AB_TABLE_END, ab)
    content = _replace_between_markers(content, BALANCE_TABLE_START, BALANCE_TABLE_END, balance)
    content = _replace_between_markers(content, THROUGHPUT_TABLE_START, THROUGHPUT_TABLE_END, throughput)
    content = _replace_between_markers(content, RISK_TABLE_START, RISK_TABLE_END, risk)
    content = _replace_between_markers(content, MODEL_NOTE_START, MODEL_NOTE_END, note)
    md_path.write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Qwen A/B + crash-risk analysis")
    parser.add_argument("--update-md", action="store_true", help="Update LLM_COMPARISON.md marker blocks")
    parser.add_argument("--markdown", type=Path, default=ROOT / "LLM_COMPARISON.md", help="Path to markdown output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = _load_qwen_clean_frame()

    # A/B matching
    pairs = _coarsen_and_pair(df)
    effects = [
        Effect("prefill_time_s", *_bootstrap_ci(pairs["prefill_diff"].to_numpy()), "s"),
        Effect("decode_time_s", *_bootstrap_ci(pairs["decode_diff"].to_numpy()), "s"),
        Effect("mlx_peak_gb", *_bootstrap_ci(pairs["peak_diff"].to_numpy()), "GB"),
    ]
    throughput_effects = [
        Effect("decode_tps", *_bootstrap_ci(pairs["decode_tps_diff"].to_numpy()), "tokens/s"),
        Effect("prefill_real_tps", *_bootstrap_ci(pairs["prefill_tps_diff"].to_numpy()), "tokens/s"),
    ]

    before = {
        "log_prompt": _standardized_mean_diff(df[df["served_target"] == QWEN_35]["log_prompt"], df[df["served_target"] == QWEN_27]["log_prompt"]),
        "cache_hit_pct": _standardized_mean_diff(
            df[df["served_target"] == QWEN_35]["cache_hit_pct"], df[df["served_target"] == QWEN_27]["cache_hit_pct"]
        ),
        "log_uncached": _standardized_mean_diff(
            df[df["served_target"] == QWEN_35]["log_uncached"], df[df["served_target"] == QWEN_27]["log_uncached"]
        ),
        "session_progress": _standardized_mean_diff(
            df[df["served_target"] == QWEN_35]["session_progress"], df[df["served_target"] == QWEN_27]["session_progress"]
        ),
    }
    after = {
        "log_prompt": _standardized_mean_diff(pairs["a_log_prompt"], pairs["b_log_prompt"]),
        "cache_hit_pct": _standardized_mean_diff(pairs["a_cache_hit"], pairs["b_cache_hit"]),
        "log_uncached": _standardized_mean_diff(pairs["a_log_uncached"], pairs["b_log_uncached"]),
        "session_progress": _standardized_mean_diff(pairs["a_session_progress"], pairs["b_session_progress"]),
    }

    # Risk model
    risk_df, beta, label_note, temporal = _risk_model(df)

    # Plots
    _plot_effects(effects)
    _plot_balance(before, after)
    _plot_throughput_effects(throughput_effects)
    _plot_ab_stack(effects, before, after, throughput_effects)
    base27 = risk_df[risk_df["served_target"] == QWEN_27].median(numeric_only=True)
    base35 = risk_df[risk_df["served_target"] == QWEN_35].median(numeric_only=True)
    _plot_risk_curve(beta, base27, base35)

    # Markdown payloads
    ab_payload = _ab_table(effects, len(pairs))
    balance_payload = _balance_table(before, after)
    throughput_payload = _throughput_table(df, throughput_effects, len(pairs))
    risk_payload = _risk_table(risk_df, beta, label_note, temporal)

    conclusive_flags = [e.ci_low > 0 or e.ci_high < 0 for e in effects]
    if all(conclusive_flags):
        ab_note = "Matched A/B effects are statistically conclusive for all tracked outcomes under this observational design."
    elif any(conclusive_flags):
        ab_note = "Matched A/B effects are only partially conclusive: at least one outcome remains non-conclusive (CI crosses zero)."
    else:
        ab_note = "Matched A/B effects are non-conclusive for all tracked outcomes (all CIs cross zero)."

    test_prev = float(temporal["test_prev"])
    test_auc = float(temporal["test_auc"])
    if pd.isna(test_prev) or test_prev < 1.0 or pd.isna(test_auc) or test_auc < 0.55:
        risk_note = "Crash-risk temporal validation is non-conclusive (low event prevalence and/or weak test discrimination)."
    else:
        risk_note = "Crash-risk temporal validation is acceptable for monitoring use."
    note = f"{ab_note} {risk_note}"

    print(ab_payload)
    print("\n" + balance_payload)
    print("\n" + throughput_payload)
    print("\n" + risk_payload)
    print("\n" + note)
    print("\nCharts written to", IMG_DIR)

    if args.update_md:
        update_markdown(args.markdown, ab_payload, balance_payload, throughput_payload, risk_payload, note)
        print("Updated", args.markdown)


if __name__ == "__main__":
    main()
