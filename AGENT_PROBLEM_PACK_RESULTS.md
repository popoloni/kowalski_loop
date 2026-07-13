# AGENT_PROBLEM_PACK_RESULTS.md

Generated at: 2026-07-13T09:18:18  
Matrix run: **20260713_003824**

This report cross-references every Agent Problem Pack run with the live server logs
(`logs/dflash_timings.csv`, `logs/headroom_traffic.jsonl`) to compare
efficiency (memory, throughput, latency) and effectiveness (pass rate) for each
model + backend combination.

---

## Executive Summary

| Category | Winner |
| --- | --- |
| Best overall (pass rate + throughput) | **dflash-qwen35b-moe** (5/5 pass, decode 57.0 tok/s) |
| Highest decode throughput | **dflash-qwen35b-moe** (57.0 tok/s) |
| Lowest memory footprint | **dflash-gemma4-12b** (median peak 24.2 GB) |

## Pass / Fail Heatmap

Each cell shows whether the model solved the problem in the latest matrix run.
Green = PASS, Red = FAIL.

![Pass/Fail heatmap](docs/img/agent_pack/pass_heatmap.png)

## Efficiency vs Effectiveness

X-axis: decode throughput (higher = more efficient).  
Y-axis: pass rate (higher = more effective).  
Bubble size ∝ median MLX peak memory GB (larger bubble = more memory pressure).

![Efficiency vs effectiveness scatter](docs/img/agent_pack/efficiency_vs_effectiveness.png)

## Per-Model Aggregate Table

> **Telemetry note:** DFlash rows expose `decode_tps`, `cache_hit_pct`, and `mlx_peak_gb` from the speculative server. MLX and TurboQuant rows expose only `total_time_s` (shown here as **Prefill s**), without separate decode throughput or GPU memory fields.
> Compare DFlash models on all metrics; compare MLX / TurboQuant on pass rate, wall time, TTFT, and token costs.

| Model | Backend | Pass | Pass% | Dur med s | TTFT med s | Turns med | Decode tok/s | Prefill s | Cache hit% | MLX peak GB | Headroom savings% | Total cost USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dflash-gemma4-12b | dflash | 0/5 | 0% | 769 | 121.2 | 2.0 | 21.1 | 6.30 | 93.3 | 24.2 | 0.0 | 3.381 |
| dflash-ornith35b-moe | dflash | 5/5 | 100% | 58 | 13.6 | 10.0 | 54.9 | 0.90 | 99.4 | 30.7 | 0.0 | 0.989 |
| dflash-qwen27b-dense | dflash | 4/5 | 80% | 292 | 81.8 | 11.0 | 17.7 | 6.50 | 97.8 | 38.0 | 1.4 | 1.020 |
| dflash-qwen35b-moe | dflash | 5/5 | 100% | 64 | 14.2 | 12.0 | 57.0 | 1.10 | 98.4 | 37.2 | 0.0 | 1.164 |
| mlx-gemma4-12b | mlx | 0/5 | 0% | 87 | 87.4 | 1.0 | n/a | 68.20 | n/a | n/a | 0.0 | 0.592 |
| mlx-ornith35b | mlx | 5/5 | 100% | 88 | 46.7 | 10.0 | n/a | 38.70 | n/a | n/a | 0.0 | 1.587 |
| turboquant-qwen35b-moe | turboquant | 4/5 | 80% | 333 | 76.3 | 11.0 | n/a | 1.50 | n/a | n/a | 0.0 | 1.736 |

## Interpretation

### Models that solved all 5 problems

- **dflash-qwen35b-moe** (5/5 pass, dur 64s, decode 57.0tok/s, TTFT 14.2s)
- **dflash-ornith35b-moe** (5/5 pass, dur 58s, decode 54.9tok/s, TTFT 13.6s)
- **mlx-ornith35b** (5/5 pass, dur 88s, decode n/atok/s, TTFT 46.7s)

### Models with partial success

- **dflash-qwen27b-dense** (4/5 pass, dur 292s, decode 17.7tok/s, TTFT 81.8s)
- **turboquant-qwen35b-moe** (4/5 pass, dur 333s, decode n/atok/s, TTFT 76.3s)

### Models that failed all problems

- **dflash-gemma4-12b** (0/5 pass, dur 769s, decode 21.1tok/s, TTFT 121.2s)
- **mlx-gemma4-12b** (0/5 pass, dur 87s, decode n/atok/s, TTFT 87.4s)

### Key observations

1. **DFlash cache reuse dominates wall time.** dflash-ornith35b-moe and dflash-qwen35b-moe complete each problem in under 100 s because their DFlash cache hit rate exceeds 98%, keeping median prefill under 1.1 s. mlx-ornith35b achieves the same 100% pass rate but takes ~88 s with ~39 s prefill per request (no prefix cache).

2. **Effectiveness and efficiency diverge for Gemma-4-12B.** Both dflash-gemma4-12b and mlx-gemma4-12b scored 0/5, despite dflash-gemma4-12b having the lowest memory footprint (24 GB). Low memory cost alone does not make a model useful for agentic tasks.

3. **TurboQuant has high wall time despite low prefill.** turboquant-qwen35b-moe shows only 1.5 s prefill but 333 s median wall time, suggesting the bottleneck is decode speed or scheduling overhead, not prefill.

4. **Recommended pairing for agent tasks:** `dflash + ornith35b-moe` or `dflash + qwen35b-moe` — both deliver 100% pass rate with sub-100 s wall time and 55–57 tok/s decode throughput, at median MLX peaks of 30–37 GB on this 64 GB machine.

## Server Performance by Model

Decode throughput, prefill time, DFlash cache hit rate, and MLX peak memory.

![Server performance by model](docs/img/agent_pack/server_perf_by_model.png)

## Wall Time and TTFT per Model

![Run duration by model](docs/img/agent_pack/run_duration_by_model.png)

![TTFT by model](docs/img/agent_pack/ttft_by_model.png)

## Token Usage Breakdown

Median new input tokens, cache read tokens, and output tokens per run.
High cache read with low new input indicates effective prefix reuse (DFlash).

![Token usage by model](docs/img/agent_pack/tokens_by_model.png)

## Headroom Context Compression

Median Headroom savings percentage during pack runs.
Higher savings means more context was compressed before reaching the inference server.

![Headroom savings by model](docs/img/agent_pack/headroom_savings_by_model.png)

## Per-Run Detail

| Model | Problem | Pass | Dur s | TTFT s | Turns | Input tok | Cache read | Output tok | Server requests | Decode tok/s | Prefill s | MLX peak GB | Headroom sav% |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dflash-gemma4-12b | Tokenizer Regression | ✗ | 2369 | n/a | 7 | 33121 | 218755 | 49330 | 14 | 15.8 | 2.15 | 18.0 | 0.0 |
| dflash-gemma4-12b | Shell Command Injection | ✗ | 127 | 123.2 | 2 | 19094 | n/a | 35 | 4 | 12.7 | 2.90 | 24.1 | 0.0 |
| dflash-gemma4-12b | Cross-Platform Task Path | ✗ | 123 | 119.3 | 2 | 19086 | n/a | 60 | 4 | 16.7 | 2.75 | 24.2 | 0.0 |
| dflash-gemma4-12b | Import Error After Refactor | ✗ | 769 | n/a | 43 | 61455 | 801486 | 1300 | 56 | 21.9 | 7.70 | 24.2 | 0.0 |
| dflash-gemma4-12b | Mutable Default Cache Leak | ✗ | 1517 | n/a | 1 | 19245 | 57393 | 32768 | 5 | 21.7 | 1.00 | 24.3 | 0.0 |
| dflash-ornith35b-moe | Tokenizer Regression | ✓ | 83 | 46.3 | 11 | 24141 | 230918 | 1330 | 17 | 56.6 | 1.00 | 25.4 | 0.0 |
| dflash-ornith35b-moe | Shell Command Injection | ✓ | 78 | 14.6 | 11 | 8985 | 238853 | 2733 | 18 | 58.5 | 1.00 | 28.5 | 0.0 |
| dflash-ornith35b-moe | Cross-Platform Task Path | ✓ | 41 | 13.1 | 9 | 5059 | 188545 | 1307 | 17 | 57.9 | 0.60 | 30.7 | 0.0 |
| dflash-ornith35b-moe | Import Error After Refactor | ✓ | 39 | 12.8 | 8 | 5072 | 165901 | 1084 | 14 | 52.8 | 0.85 | 32.7 | 0.0 |
| dflash-ornith35b-moe | Mutable Default Cache Leak | ✓ | 58 | 13.6 | 10 | 5624 | 213649 | 2047 | 11 | 51.4 | 0.80 | 34.1 | 0.0 |
| dflash-qwen27b-dense | Tokenizer Regression | ✓ | 441 | 264.4 | 10 | 27526 | 173825 | 1639 | 11 | 18.3 | 6.40 | 33.0 | 7.0 |
| dflash-qwen27b-dense | Shell Command Injection | ✓ | 452 | 79.9 | 11 | 21664 | 186853 | 1915 | 11 | 15.8 | 6.50 | 38.0 | 0.0 |
| dflash-qwen27b-dense | Cross-Platform Task Path | ✗ | 174 | n/a | 3 | 9603 | 32768 | 325 | 5 | 16.5 | 9.10 | 38.0 | 0.0 |
| dflash-qwen27b-dense | Import Error After Refactor | ✓ | 241 | 83.7 | 11 | 9222 | 216986 | 1660 | 12 | 18.2 | 6.10 | 38.0 | 0.0 |
| dflash-qwen27b-dense | Mutable Default Cache Leak | ✓ | 292 | 73.0 | 11 | 13151 | 219536 | 1928 | 11 | 18.0 | 6.90 | 38.4 | 6.7 |
| dflash-qwen35b-moe | Tokenizer Regression | ✓ | 85 | 45.8 | 11 | 24313 | 233292 | 1765 | 14 | 56.2 | 0.95 | 25.1 | 0.0 |
| dflash-qwen35b-moe | Shell Command Injection | ✓ | 102 | 13.6 | 12 | 20631 | 240756 | 2793 | 17 | 57.9 | 1.30 | 32.9 | 6.4 |
| dflash-qwen35b-moe | Cross-Platform Task Path | ✓ | 47 | 14.2 | 9 | 6125 | 194381 | 1677 | 15 | 57.0 | 1.10 | 38.2 | 0.0 |
| dflash-qwen35b-moe | Import Error After Refactor | ✓ | 49 | 14.1 | 12 | 5816 | 215766 | 1847 | 15 | 57.1 | 1.00 | 39.4 | 0.0 |
| dflash-qwen35b-moe | Mutable Default Cache Leak | ✓ | 64 | 14.9 | 13 | 7942 | 250076 | 2292 | 12 | 56.3 | 1.25 | 39.4 | 0.0 |
| mlx-gemma4-12b | Tokenizer Regression | ✗ | 131 | 129.2 | 1 | 19149 | 19074 | 1042 | 5 | n/a | 34.60 | n/a | 0.0 |
| mlx-gemma4-12b | Shell Command Injection | ✗ | 82 | 82.4 | 1 | 19079 | 25 | 96 | 4 | n/a | 34.60 | n/a | 0.0 |
| mlx-gemma4-12b | Cross-Platform Task Path | ✗ | 84 | 81.8 | 3 | 19216 | 38322 | 87 | 6 | n/a | 68.20 | n/a | 0.0 |
| mlx-gemma4-12b | Import Error After Refactor | ✗ | 128 | 125.8 | 1 | 19143 | 19116 | 1045 | 5 | n/a | 68.20 | n/a | 0.0 |
| mlx-gemma4-12b | Mutable Default Cache Leak | ✗ | 87 | 87.4 | 1 | 19095 | n/a | 207 | 2 | n/a | 34.50 | n/a | 0.0 |
| mlx-ornith35b | Tokenizer Regression | ✓ | 88 | 48.5 | 10 | 24084 | 205859 | 1317 | 13 | n/a | 20.20 | n/a | 0.0 |
| mlx-ornith35b | Shell Command Injection | ✓ | 151 | 46.7 | 9 | 44079 | 159197 | 2508 | 12 | n/a | 38.70 | n/a | 6.8 |
| mlx-ornith35b | Cross-Platform Task Path | ✓ | 81 | 45.7 | 11 | 22311 | 217918 | 1345 | 14 | n/a | 19.60 | n/a | 0.0 |
| mlx-ornith35b | Import Error After Refactor | ✓ | 86 | 45.8 | 11 | 21607 | 216974 | 1640 | 14 | n/a | 0.50 | n/a | 0.0 |
| mlx-ornith35b | Mutable Default Cache Leak | ✓ | 185 | 47.2 | 9 | 65405 | 132378 | 2016 | 10 | n/a | 40.60 | n/a | 0.0 |
| turboquant-qwen35b-moe | Tokenizer Regression | ✗ | 64 | n/a | 1 | n/a | n/a | n/a | 4 | n/a | 28.50 | n/a | 0.0 |
| turboquant-qwen35b-moe | Shell Command Injection | ✓ | 954 | 84.7 | 9 | 67377 | 130426 | 1688 | 14 | n/a | 1.55 | n/a | 1.4 |
| turboquant-qwen35b-moe | Cross-Platform Task Path | ✓ | 590 | 76.5 | 13 | 114908 | 179100 | 2217 | 17 | n/a | 1.50 | n/a | 1.4 |
| turboquant-qwen35b-moe | Import Error After Refactor | ✓ | 242 | 75.4 | 11 | 23521 | 177533 | 1646 | 12 | n/a | 1.50 | n/a | 0.0 |
| turboquant-qwen35b-moe | Mutable Default Cache Leak | ✓ | 333 | 76.1 | 12 | 24898 | 256459 | 2334 | 12 | n/a | 1.55 | n/a | 0.0 |

## Data Sources

| Source | Path | What it provides |
| --- | --- | --- |
| Agent pack artifacts | `local-coding-agent-evals/agent-problem-pack/runs/` | pass/fail, duration, ttft, turns, token usage |
| DFlash/MLX/TurboQuant timings | `logs/dflash_timings.csv` | prefill_time_s, decode_tps, mlx_peak_gb, cache_hit_pct |
| Headroom traffic | `logs/headroom_traffic.jsonl` | savings_percent, optimization_latency_ms |

Server metrics are correlated by matching each run's time window
(headless-stdout.jsonl mtime − duration → mtime) against log timestamps,
filtered by the served model target.
