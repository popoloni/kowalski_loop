# LLM_COMPARISON.md — Qwen A/B and Crash-Risk Modeling

This report answers a practical question: which Qwen model behaves better on the real workload captured in the dflash telemetry, and for what kind of usage should each model be preferred?

The comparison is between:

- `mlx-community/Qwen3.6-35B-A3B-4bit`
- `mlx-community/Qwen3.6-27B-4bit`

The data comes from `logs/dflash_timings.csv`, using only the cleaned dflash rows.

The report has two parts:

1. A matched A/B analysis that compares performance and memory after balancing the workload.
2. A crash-risk model that tries to estimate when the system is under dangerous memory pressure.

Run/update command:

```bash
cd ~/local-llm-workspace
env/bin/python llmstack/tools/llm_comparison_metrics.py --update-md
```

---

## 1. What this report is doing

The telemetry is not a controlled experiment. Requests are not randomly assigned to the two models, so the raw averages would be biased by workload mix. For example, one model might receive longer prompts, more cached sessions, or more advanced turns in the conversation.

To reduce that bias, the A/B part uses a standard observational strategy:

1. Split requests into comparable buckets by prompt size, cache hit rate, and session progress.
2. Pair similar requests from the two models inside each bucket.
3. Compare the paired outcomes instead of comparing all raw requests at once.

That approach does not turn the data into a randomized experiment, but it makes the comparison much fairer.

The three outcomes measured here are:

1. Prefill time, which is the time spent processing the prompt before generation starts.
2. Decode time, which is the time spent generating the answer.
3. Peak memory, which is the maximum MLX memory reached during the request.

For the crash-risk part, the report fits a logistic model. Logistic models are useful when the target is binary, such as “normal” versus “high-risk”. The model combines several inputs into a probability-like score. Here the inputs are:

1. Peak memory.
2. Prompt size.
3. Uncached tail size.
4. A prefill-tail indicator.
5. Which model was used.

Important caveat: because true crash labels are sparse and unstable in this dataset, the risk model is currently best interpreted as an operational warning score, not as a calibrated crash probability.

---

## 2. How to read the stacked A/B figure

The stacked figure combines the A/B views into one compact panel set. It is the easiest way to read the model comparison because it shows the result and the quality check together.

How to read the top panel:

1. Each dot is the estimated average difference for one outcome.
2. The horizontal line is the confidence interval.
3. The vertical zero line means “no difference”.
4. If the interval stays entirely on one side of zero, the effect is statistically clear in this telemetry slice.
5. Negative values mean Qwen 35B-A3B is lower than Qwen 27B for that metric.

For this report, negative is good for latency and memory, because lower prefill time, lower decode time, and lower peak memory are all improvements.

How to read the middle panel:

1. The red points are the raw unmatched differences between the two model populations.
2. The green points are the differences after matching.
3. Values closer to zero mean the two groups are more comparable.
4. If a covariate is still far from zero after matching, the A/B estimate is less trustworthy.

In short: the top panel tells you the latency and memory result, and the middle panel tells you whether the comparison was fair.

## 3. A/B results

The table below shows the matched difference between Qwen 35B-A3B and Qwen 27B after balancing requests by prompt size, cache hit rate, and session progress. Negative values are good for latency and memory, because they mean the 35B-A3B model is lower than the 27B model on that metric.

<!-- LLM_AB_TABLE_START -->

| Outcome | Matched effect (35B-A3B - 27B) | 95% CI | Conclusive? |
|---|---:|---:|---:|
| prefill_time_s | -26.12 s | [-32.24, -20.97] s | yes |
| decode_time_s | -15.76 s | [-20.01, -11.62] s | yes |
| mlx_peak_gb | -4.75 GB | [-5.31, -4.18] GB | yes |
| Matched pairs | 787 | n/a | n/a |

<!-- LLM_AB_TABLE_END -->

### 3.1 Balance diagnostics

The balance table checks whether the matching step made the two groups comparable. Values closer to zero are better. Here the post-match differences are small overall, although one covariate remains slightly farther from zero than the others; that is acceptable for a descriptive observational comparison, but it is not perfect balance.

<!-- LLM_BALANCE_TABLE_START -->

| Covariate | SMD before matching | SMD after matching |
|---|---:|---:|
| log_prompt | 0.020 | 0.019 |
| cache_hit_pct | -0.007 | 0.041 |
| log_uncached | 0.177 | 0.190 |
| session_progress | -0.018 | -0.024 |

<!-- LLM_BALANCE_TABLE_END -->

![Stacked A/B panels](docs/img/llm_comparison/ab_stack.png)

The stacked figure combines the three A/B views in one compact panel set. Top: matched latency and memory effects. Middle: balance diagnostics, which check whether matching made the two groups comparable. Bottom: throughput effects, where positive values mean Qwen 35B-A3B is faster in tokens per second.

Reading the panels together helps with interpretation: the first and third panels tell you whether the model is better on latency, memory, and throughput; the middle panel tells you whether that comparison is fair.

---

## 4. Throughput / tokens per second

Throughput is the flip side of latency: higher tokens per second means the model processes or emits tokens faster. This section matters because latency tells you how long a request takes, while throughput tells you how much work the system can push through in a unit of time.

The raw numbers below are useful as a quick sanity check, but they can still be influenced by request mix. The matched effect is the more reliable comparison because it uses the same pairing logic as the latency section.

<!-- LLM_THROUGHPUT_TABLE_START -->

| Model | decode_tps median | decode_tps p90 | prefill_real_tps median | prefill_real_tps p90 |
|---|---:|---:|---:|---:|
| Qwen3.6-35B-A3B-4bit | 42.2 | 58.7 | 112.4 | 388.8 |
| Qwen3.6-27B-4bit | 13.3 | 18.0 | 35.4 | 77.4 |

| Throughput metric | Matched effect (35B-A3B - 27B) | 95% CI | Better when |
|---|---:|---:|---|
| decode_tps | 31.52 tokens/s | [30.25, 32.75] tokens/s | higher |
| prefill_real_tps | 128.58 tokens/s | [120.67, 137.69] tokens/s | higher |
| Matched pairs | 787 | n/a | n/a |

<!-- LLM_THROUGHPUT_TABLE_END -->

![Throughput effects](docs/img/llm_comparison/throughput_effects.png)

This standalone throughput figure shows the same pairwise comparison in token/sec terms. It stays compact on the page, and positive values are good because they mean Qwen 35B-A3B is faster after balancing the workload.

---

## 5. Crash-risk model

This model asks a different question from the A/B section: not which model is faster, but which request patterns look dangerous for the system. The numbers below should be read as an operational risk signal, not as a calibrated crash probability.

The output is a risk curve. It does not measure speed. It estimates how risk changes as memory peak increases, while holding other inputs at representative values.

How to read the crash-risk chart:

1. The x-axis is peak memory in GB.
2. The y-axis is the model’s predicted risk score.
3. A rising curve means that higher memory pressure is associated with higher risk.
4. The two lines compare the same memory range under the two model identities.
5. Because the label is currently a proxy, the absolute probability should not be treated as a final calibrated number.

The most important practical use of this chart is thresholding and alerting. It helps answer questions like: “At what memory level should we start warning the system?”

<!-- LLM_RISK_TABLE_START -->

| Item | Value |
|---|---:|
| Risk label used | high-risk-proxy(mlx_peak_gb>=48) |
| Positive events | 205 |
| Positive prevalence | 6.46% |
| Temporal split cutoff | 2026-07-05 12:31:01 UTC |
| Temporal train rows | 2,538 |
| Temporal test rows | 635 |
| Temporal train prevalence | 8.04% |
| Temporal test prevalence | 0.16% |
| Temporal train AUC | 0.595 |
| Temporal test AUC | 0.167 |
| Temporal train Brier | 0.0768 |
| Temporal test Brier | 0.0136 |
| Temporal reliability | low (temporal split unstable) |
| Coef: mlx_peak_gb | 0.034 |
| Coef: log_prompt | -0.720 |
| Coef: log_uncached | -0.134 |
| Coef: prefill_tail | -0.002 |
| Coef: model_is_35 | -0.239 |

<!-- LLM_RISK_TABLE_END -->

![Crash-risk curve](docs/img/llm_comparison/crash_risk_curve.png)

This plot shows how the risk score changes as peak memory increases. The upward trend means that higher memory pressure is associated with higher risk. Because the label is currently a proxy, the absolute scale is less important than the shape of the curve and the threshold region around 48-52 GB.

---

## 6. Conclusion status

<!-- LLM_MODEL_NOTE_START -->

Matched A/B effects are statistically conclusive for all tracked outcomes under this observational design. Crash-risk temporal validation is non-conclusive (low event prevalence and/or weak test discrimination).

<!-- LLM_MODEL_NOTE_END -->

Interpretation rule:

1. If CI crosses zero, the A/B effect is non-conclusive for that outcome.
2. If all outcomes cross zero, overall A/B conclusion is non-conclusive.
3. Crash-risk model coefficients are directional under observational data and should not be interpreted as causal effects.

## 7. Model recommendation (which LLM for what)

Recommended default model for most interactive traffic:

1. Qwen3.6-35B-A3B-4bit.

Why:

1. Better latency in matched A/B (prefill + decode).
2. Lower memory peak in matched A/B.
3. More favorable behavior under cache-heavy workloads.

When to prefer Qwen3.6-27B-4bit:

1. You need a conservative fallback path for compatibility checks or regression baselines.
2. You are running controlled experiments where architectural simplicity is preferred over best observed latency.

Suggested usage policy:

1. Route normal coding-agent and long-context iterative sessions to 35B-A3B.
2. Keep 27B as backup/canary and as a comparison baseline.
3. Trigger soft alerts when peak memory approaches 48 GB, and stronger alerts near 52 GB.
4. Avoid treating current crash-risk probability as calibrated; re-train after collecting more balanced recent crash events.

## 8. What would make the risk model reliable

To promote the risk model from directional to decision-grade:

1. Capture a larger and more balanced set of recent crash/near-crash events.
2. Add explicit restart/crash event IDs aligned to request timestamps (instead of proxy labels).
3. Re-run rolling temporal validation (for example weekly windows) and require stable test AUC before enforcing hard policy.
