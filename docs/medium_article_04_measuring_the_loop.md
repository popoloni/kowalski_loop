# Measuring the Kowalski Loop

## The Metrics That Make Local AI Agents Work

![Measuring the Kowalski Loop banner](img/measuring_kowalski.png)

Part 4 of The Ultimate Local AI Setup Guide.

In Part 1 we made local inference fast enough to be practical. In Part 2 we made the loop autonomous enough to execute plans unattended. In Part 3 we turned that prototype into a reusable framework.

This fourth part is where we move from excitement to accountability. The central question is simple: is the Kowalski loop actually improving engineering outcomes, or are we just feeling good because the terminal keeps printing tokens?

The purpose of this article is to answer that question with evidence. It is written as a narrative, but every claim is grounded in logs, reproducible scripts, and explicit limits.

If you run local agents seriously, this is the layer that separates a cool demo from an operable system.

## Published update (2026-07-12): Ornith-1.0-35B MoE is now included

This article has been updated after publication to include a new production model in the telemetry stack: `mlx-community/Ornith-1.0-35B-4bit` (Mix of Experts).

What changed in this revision:

1. Ornith is now part of the per-model metrics in [SAVINGS.md](../SAVINGS.md), [DFLASH.md](../DFLASH.md), and [HEADROOM.md](../HEADROOM.md).
2. In the by-model synthesis chart (`img/savings/savings_landscape_by_model.png`), Ornith is rendered as the red trace for immediate visual tracking.
3. Aggregate metrics were refreshed end-to-end on the expanded dataset, and key values in this article were updated accordingly.

This is a real data update, not a wording-only edit.

---

## Before the numbers, a familiar failure mode

Picture a late-night session: the assistant is still answering, the model is still online, and everything looks fine. Then a request suddenly takes minutes instead of seconds. A few turns later the backend restarts. From the outside it feels random. From the inside it is usually not random at all.

Prompt context has grown. Cache reuse changed shape. Prefill cost exploded. Memory crossed a dangerous zone. Those are measurable transitions, not mysteries.

That is why metrics are not cosmetic in Kowalski. They are the operating system for decisions.

## Why metrics become the real control plane

A local coding stack can continue producing responses while silently degrading. You can see "healthy" logs and still be moving toward a crash. You can see high cache-hit percentages and still pay expensive prefill. You can compress prompts and still get limited real savings if the workload is not actually redundant.

So in Kowalski the loop is not only plan, execute, verify. It is also observe, quantify, decide. Without this second loop, operations are driven by intuition. With it, operations are driven by measured thresholds.

Once you see the system this way, every chart is no longer reporting. It is steering.

## What exactly we measured

The measurement stack spans four layers: memory reliability, Headroom compression, DFlash cache/prefill efficiency, and model-level comparison. The Qwen matched A/B remains in place (Qwen3.6-27B vs Qwen3.6-35B-A3B), and Ornith-1.0-35B MoE is now included in per-model contribution analysis.

Telemetry comes primarily from `logs/dflash_timings.csv`, `logs/headroom_traffic.jsonl`, and `logs/dflash_server.log`. The analysis is consolidated in [MEMORY.md](../MEMORY.md), [HEADROOM.md](../HEADROOM.md), [DFLASH.md](../DFLASH.md), [SAVINGS.md](../SAVINGS.md), and [LLM_COMPARISON.md](../LLM_COMPARISON.md).

Everything is reproducible via scripts in `llmstack/tools/` and can be refreshed end-to-end with `bin/refresh_metrics_docs.bash`.

Methodologically, this is observational evidence, not a randomized trial. That distinction matters. Wherever we compare models, we use matching, confidence intervals, and balance diagnostics instead of naive global averages.

## The metric architecture in one picture

![Savings landscape](img/savings/savings_landscape.png)

This is the synthesis view. Memory defines the hard boundary. Headroom acts before inference by reducing prompt payload. DFlash acts during prefill by reusing prefix work. Decode then follows its own throughput dynamics.

The key insight is timing: these mechanisms do not activate at the same stage of a request. A useful operational decomposition is:

`total_time_s ≈ prefill_time_s + decode_time_s + overhead`

In practice, `prefill_time_s` is dominated by prompt size and uncached suffix. `decode_time_s` is dominated by generated length and model throughput. Memory peak determines whether the system can sustain that cycle over long sessions.

## 1) Memory: where local reliability is won or lost

![Prefill cliff](img/prefill_cliff.png)

![Context and memory](img/context_memory.png)

Memory is the physical boundary of local agentic development on Apple Silicon. In this workload, instability emerges around an empirical danger band near 52 GB of peak usage. The most important pattern is that crashes are tied to long prefill misses, not to decode.

This changes behavior in production: memory becomes a leading indicator, not a post-mortem artifact. Repeated peaks near 48 GB should already trigger mitigation. Waiting for failures near 52 GB is too late.

The practical failure narrative is consistent across sessions: context grows, uncached suffix spikes, prefill duration stretches, memory climbs, and then a single heavy turn can cross the boundary.

In plain terms, memory is not just another metric. It is the kill switch.

## 2) Headroom: compression is not uniform, it is conditional

![Headroom savings vs prompt](img/headroom/savings_prompt.png)

![Headroom savings vs session progress](img/headroom/savings_progress.png)

Headroom is not a uniform accelerator. It is highly effective in some phases and nearly neutral in others.

Current telemetry shows weighted savings around 9.74%, but the median per-request savings is much lower (about 4.37%). This gap is important: it tells us the distribution is skewed. A minority of high-impact turns contributes a large share of total benefit.

The qualitative pattern is stable: very small prompts usually save little, while larger and more repetitive sessions create compressible structure that Headroom can exploit.

So the correct mental model is not “Headroom always compresses well.” The right model is “Headroom amplifies redundancy when redundancy exists.”

This is why the same stack can look brilliant in one session and neutral in another without any code change.

## 3) DFlash: the speedup is a threshold effect

![DFlash cache cliff](img/dflash/cache_cliff.png)

![DFlash uncached suffix cliff](img/dflash/uncached_cliff.png)

DFlash does not improve linearly with cache hit. It behaves like a threshold system.

In this dataset, 80-90% cache hit is better than cold start but often still expensive. The turning region appears around 95-99%, and the truly fast regime is 99%+ cache reuse.

The key metric behind that behavior is uncached suffix size. Two requests can show similarly high cache percentages and still differ sharply in latency if their uncached tails are different. That is why “cache hit” alone can mislead when interpreted without suffix context.

The aggregate anchors reinforce this: prefill median is around 1.10 s, prefill p90 is about 22.61 s, and the 99-100% cache band concentrates the clear low-latency behavior.

Operationally, this means tuning for "high average cache" is not enough. You need to tune for "small uncached suffix most of the time."

## 3.5) Ornith contribution: where the new model changes the picture

With Ornith now in the production traces, the stack gains a large new evidence block rather than a tiny side sample.

From the refreshed per-model table in [SAVINGS.md](../SAVINGS.md):

1. DFlash rows: 3,300 (largest model slice in the current dataset).
2. DFlash median prefill: 1.00 s; p90 prefill: 6.00 s.
3. Share of calls with prefill <= 2 s: 81.2%.
4. Share of calls with cache hit >= 99%: 84.2%.
5. Headroom median savings: 4.90%; p90 savings: 13.57%; >=20% savings share: 7.3%.

Interpretation: Ornith materially strengthens the fast-prefill regime and high-cache-reuse share. It does not magically remove decode-length effects, but it shifts more real traffic into the low-latency prefill band.

## 4) A/B on real traffic: which Qwen is operationally stronger?

![Qwen A/B stacked panels](img/llm_comparison/ab_stack.png)

This section is where rigor matters most, because model comparisons are the easiest place to overclaim.

Traffic is observational, not randomized. So instead of comparing raw global averages, we build a quasi-experimental design: coarsened matching by prompt size, cache-hit region, and session progress; then pairwise effect estimation with bootstrap confidence intervals; then balance diagnostics to verify comparability.

The measured effects (35B-A3B minus 27B) are substantial in this telemetry slice. Prefill time is about -23.30 s with a confidence interval fully below zero. Decode time is about -14.47 s, again with interval below zero. Peak memory is about -4.62 GB, also clearly below zero. Throughput, evaluated in the dedicated throughput section and table, moves in the opposite direction as expected (higher is better), with decode throughput around +29.95 tokens/s and prefill throughput around +117.11 tokens/s in matched comparisons.

Interpretation: on this workload, Qwen3.6-35B-A3B is not merely competitive; it is consistently stronger on latency, memory, and throughput after adjustment for key workload differences.

Boundary of claim: this is strong operational evidence for this environment and traffic profile, not a universal statement for all hardware and all prompt distributions.

Coding-quality disclaimer: in day-to-day coding use, Qwen3.6-27B can sometimes feel more first-try consistent, but this is currently a qualitative impression only. We have not yet run a dedicated quantitative coding benchmark suite (for example pass@k, unit-test pass rate, or task-level acceptance), so no conclusive ranking on coding-output quality is claimed here.

Still, for this stack and these sessions, the decision signal is clear enough to drive default routing policy.

## 5) Crash-risk modeling: useful signal, not yet a calibrated predictor

![Crash risk curve](img/llm_comparison/crash_risk_curve.png)

We also trained a logistic crash-risk model from memory and request-shape features. The motivation is straightforward: fixed thresholds are useful but coarse, while a probabilistic score can surface relative risk earlier.

At the moment, the model is directionally useful but not yet calibration-grade. Temporal validation is still unstable in the latest split. The current metrics reflect this limitation (train AUC around 0.561, test AUC around 0.442, temporal reliability still marked low).

So the correct operational use is ranking and warning, not hard gating.

This is a good example of disciplined analytics: we keep the model because it is useful, and we limit its authority because calibration is not yet stable.

## Method notes (rigor and limits)

This is an engineering-grade observational analysis, not a randomized controlled experiment. To preserve rigor, we clean invalid rows, avoid naive global averages for model comparison, use matched effects with confidence intervals, and include balance and temporal checks. We also explicitly mark non-conclusive outputs when evidence is weak.

What we cannot claim yet is strict causality across all workloads and hardware tiers, or stable probabilistic calibration of crash risk without richer event labels.

So think of this as decision-quality operational evidence, not as a universal benchmark paper.

## Executive summary

If you operate Kowalski on production-like local workflows, the evidence supports a clear policy. With the published Ornith update, use Ornith-1.0-35B MoE as the default DFlash interactive route for this environment, keep Qwen3.6-35B-A3B as a high-throughput comparison path, and keep Qwen3.6-27B as fallback and baseline. Treat memory as the first reliability guardrail and react before repeated peaks around 48 GB. Use Headroom and DFlash as complementary levers that activate at different phases. Use crash-risk scoring as warning intelligence until temporal validation becomes stable enough for stricter controls.

If this article had to collapse into one sentence, it would be this:

**Do not optimize one metric in isolation; optimize the loop where compression, cache reuse, throughput, and memory safety move together.**

## Final takeaway

Kowalski does not win because one model is fast or one optimization is clever. It wins when measurement closes the loop between behavior and decisions.

That is the real lesson from this dataset: performance, reliability, and cost are not separate dashboards. They are one coupled system.

When you treat them that way, local AI agents stop feeling fragile and start behaving like infrastructure.

---

## Reproducibility

If you are starting from zero and do not have Kowalski installed yet, do this first:

Clone the repository:

```bash
git clone https://github.com/popoloni/kowalski_loop.git
cd kowalski_loop
```

Then follow the installation guide from the repository root (`INSTALL.md`).

Read the project README carefully and run a real trial first (interactive mode and/or Kowalski loop on a local project), so the system generates actual telemetry logs.

Important: if you refresh metrics before running real local workloads, reports and plots will be empty, weak, or misleading because there is no meaningful data to aggregate.

Only after you have produced telemetry from real usage, run the refresh scripts below.

Refresh all reports and figures:

```bash
cd ~/kowalski_loop
bash bin/refresh_metrics_docs.bash
```

Regenerate only the comparison report:

```bash
cd ~/kowalski_loop
env/bin/python llmstack/tools/llm_comparison_metrics.py --update-md
```

For a fully fresh state, run both commands in sequence.

If you publish your own numbers, keep the same discipline: show methods, show uncertainty, and show limits.

## Related deep-dive documents

- [MEMORY.md](../MEMORY.md)
- [HEADROOM.md](../HEADROOM.md)
- [DFLASH.md](../DFLASH.md)
- [SAVINGS.md](../SAVINGS.md)
- [LLM_COMPARISON.md](../LLM_COMPARISON.md)
