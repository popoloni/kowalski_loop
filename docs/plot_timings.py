#!/usr/bin/env python3
"""Generate charts from dflash_timings.csv for the Medium article.

Outputs (into docs/img/):
  1. prefill_cliff.png   — prefill time vs prompt size, cache HIT vs MISS
  2. context_memory.png  — prompt-token + peak-memory growth over the build
  3. cachehit_hist.png   — distribution of per-call total time, hit vs miss
"""
import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "..", "logs", "dflash_timings.csv")
IMG = os.path.join(HERE, "img")
os.makedirs(IMG, exist_ok=True)

df = pd.read_csv(CSV)
df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
df = df.dropna(subset=["timestamp"]).reset_index(drop=True)

# A call is a real cache MISS when almost nothing was reused.
df["miss"] = df["cache_hit_pct"] < 50.0

# Focus on agentic-scale calls (the small 385/420-token warm-up pings hide the story).
big = df[df["prompt_tokens"] >= 5000].copy()

# ---------------------------------------------------------------- Chart 1
# Prefill time vs prompt size, colored by cache hit/miss. THE thesis chart.
fig, ax = plt.subplots(figsize=(9, 5.5))
hit = big[~big["miss"]]
miss = big[big["miss"]]
ax.scatter(hit["prompt_tokens"] / 1000, hit["prefill_time_s"],
           s=22, alpha=0.55, color="#2e8b57", label="cache HIT (≥50% reused)")
ax.scatter(miss["prompt_tokens"] / 1000, miss["prefill_time_s"],
           s=40, alpha=0.8, color="#c1121f", marker="x", label="cache MISS (<50% reused)")
ax.set_yscale("log")
ax.set_xlabel("Prompt size (thousands of tokens)")
ax.set_ylabel("Prefill time — time to first token (s, log scale)")
ax.set_title("The prefix-cache cliff: one second on a hit, minutes on a miss")
ax.axhline(1.0, color="#2e8b57", ls=":", lw=1, alpha=0.7)
ax.axhline(60.0, color="#c1121f", ls=":", lw=1, alpha=0.7)
ax.text(big["prompt_tokens"].max() / 1000, 1.0, " ~1 s", va="bottom", ha="right",
        color="#2e8b57", fontsize=9)
ax.text(big["prompt_tokens"].max() / 1000, 60.0, " 1 min", va="bottom", ha="right",
        color="#c1121f", fontsize=9)
ax.grid(True, which="both", ls="--", alpha=0.25)
ax.legend(loc="upper left", framealpha=0.9)
fig.tight_layout()
fig.savefig(os.path.join(IMG, "prefill_cliff.png"), dpi=130)
plt.close(fig)

# ---------------------------------------------------------------- Chart 2
# Context + memory growth across the longest single run (June 25 — the 80k-token day).
run = df[(df["timestamp"] >= "2026-06-24 23:00") & (df["timestamp"] <= "2026-06-25 09:00")].copy()
run = run.reset_index(drop=True)
fig, ax1 = plt.subplots(figsize=(9, 5.5))
x = range(len(run))
ax1.plot(x, run["prompt_tokens"] / 1000, color="#1f6feb", lw=1.8, label="prompt size (k tokens)")
ax1.set_xlabel("Successive model calls during one multi-hour run")
ax1.set_ylabel("Prompt size (thousands of tokens)", color="#1f6feb")
ax1.tick_params(axis="y", labelcolor="#1f6feb")
ax1.grid(True, ls="--", alpha=0.25)

ax2 = ax1.twinx()
ax2.plot(x, run["mlx_peak_gb"], color="#d4a017", lw=1.8, label="MLX peak memory (GB)")
ax2.set_ylabel("MLX peak memory (GB)", color="#d4a017")
ax2.tick_params(axis="y", labelcolor="#d4a017")
ax2.axhline(52, color="#c1121f", ls=":", lw=1.2, label="_nolegend_")
ax2.text(len(run) - 1, 52, " ~52 GB Metal wired limit", va="bottom", ha="right",
         color="#c1121f", fontsize=9)

ax1.set_title("Whole-file regeneration bloats context — and memory creeps toward the ceiling")
handles = []
labels = []
for line in (ax1.get_lines() + ax2.get_lines()):
        label = str(line.get_label())
        if not label.startswith("_"):
                handles.append(line)
                labels.append(label)
ax1.legend(handles, labels, loc="upper left", framealpha=0.9)
fig.tight_layout()
fig.savefig(os.path.join(IMG, "context_memory.png"), dpi=130)
plt.close(fig)

# ---------------------------------------------------------------- Chart 3
# How rare misses are, yet how much wall-clock they cost: total time, hit vs miss.
fig, ax = plt.subplots(figsize=(9, 5.5))
bins = [0, 2, 5, 10, 30, 60, 120, 300, 600, 1200]
ax.hist(hit["total_time_s"], bins=bins, alpha=0.7, color="#2e8b57",
        label=f"cache HIT  (n={len(hit)})")
ax.hist(miss["total_time_s"], bins=bins, alpha=0.7, color="#c1121f",
        label=f"cache MISS (n={len(miss)})")
ax.set_xscale("log")
ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:g}"))
ax.set_xlabel("Total turn time (s, log scale)")
ax.set_ylabel("Number of calls")
ax.set_title("Misses are the minority of calls — but they own the wall clock")
ax.grid(True, ls="--", alpha=0.25)
ax.legend(framealpha=0.9)
fig.tight_layout()
fig.savefig(os.path.join(IMG, "cachehit_hist.png"), dpi=130)
plt.close(fig)

# ---------------------------------------------------------------- Summary
def stats(s):
    return f"n={len(s)} median={s.median():.1f}s max={s.max():.0f}s"

print("Charts written to", IMG)
print("  big calls (>=5k tok):", len(big))
print("  HIT prefill :", stats(hit["prefill_time_s"]))
print("  MISS prefill:", stats(miss["prefill_time_s"]))
print("  HIT total   :", stats(hit["total_time_s"]))
print("  MISS total  :", stats(miss["total_time_s"]))
print("  run calls for chart2:", len(run),
      "prompt", f"{run['prompt_tokens'].min()}→{run['prompt_tokens'].max()}",
      "mem", f"{run['mlx_peak_gb'].min()}→{run['mlx_peak_gb'].max()}")
