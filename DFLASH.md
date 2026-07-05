# DFLASH.md — Prefill Efficiency, Cache Reuse, and the Real Speedup Threshold

This document explains when DFlash is actually efficient and where the speedup comes from.
The short version is: DFlash is not “fast” because every request is fast. It is fast because
after the first expensive prefill, later requests often reuse nearly the entire prefix.

The analysis below uses `logs/dflash_timings.csv` and `logs/dflash_server.log`.

Important note: the raw `cache_hit_pct` field in the CSV has a few parser artifacts outside
the valid range. For this report, I use only the clean dflash rows where `0 <= cache_hit_pct <= 100`.

Clean sample used here:

| Metric | Value |
|---|---:|
| dflash rows in CSV | 3,369 |
| clean dflash rows | 3,364 |
| parser outliers removed | 5 |
| sessions | 23 |

---

## 1. What DFlash is doing

DFlash combines speculative decoding with a prefix cache. In practice, that means:

- The first time a large prompt appears, prefill can be very slow.
- Once the prefix is cached, repeated requests with the same or similar context become much faster.
- The real speedup is not linear. It jumps when the uncached suffix becomes tiny.

The key operational metric is the uncached suffix:

```text
uncached_tokens = prompt_tokens × (1 - cache_hit_pct / 100)
```

That is the part that still needs prefill work. The rest is reused.

### What the logs tell us

From the clean dflash sample:

| Metric | Value |
|---|---:|
| Cache-hit median | 99.50% |
| Cache-hit mean | 88.96% |
| Prefill median | 2.40 s |
| Prefill mean | 24.22 s |
| Prefill 90th percentile | 67.44 s |
| Prefill <= 2 s | 46.0% |
| Prefill <= 5 s | 63.0% |
| Requests with >= 95% cache | 76.5% |
| Requests with >= 99% cache | 59.5% |

That already tells the main truth:

1. DFlash is often extremely efficient.
2. The tail still exists and is expensive.
3. “80-90% cached” is better than cold start, but it is not yet the fast regime.

### The strongest evidence from the server log

The dflash server log shows a typical pattern:

- a first long prefill can take minutes,
- then a nearly identical follow-up prompt can hit almost the whole prefix,
- and prefill collapses to about 1 second.

In other words, the first expensive prefill is the investment; later requests harvest it.

---

## 2. Evidence in charts

### 2.1 Cache-hit cliff

![Cache-hit cliff](docs/img/dflash/cache_cliff.png)

This chart plots prefill time against cache-hit percentage.

What happened in aggregate:

1. Requests below 80% cache remain slow.
2. Requests in the 80-90% band still have long prefill times.
3. The big drop starts at 95-99%.
4. The fast regime is 99%+.

What the numbers tell us:

- 80-90% cache: median prefill 60.95 s.
- 90-95% cache: median prefill 28.30 s.
- 95-99% cache: median prefill 8.20 s.
- 99-100% cache: median prefill 1.20 s.

So the true threshold for “fast” is not 80-90% reuse. It is much closer to 95-99%, with
99%+ being the clearest fast path.

### 2.2 Uncached suffix cliff

![Uncached suffix cliff](docs/img/dflash/uncached_cliff.png)

This chart plots prefill time against the number of uncached tokens.

What happened in aggregate:

1. A tiny uncached suffix gives near-instant prefill.
2. Once the uncached suffix reaches hundreds or thousands of tokens, latency rises fast.
3. The tail grows very quickly when thousands of uncached tokens remain.

What the numbers tell us:

- <= 100 uncached tokens: about 1.1 s median prefill.
- 100-500 uncached tokens: about 3.7 s median prefill.
- 500-1000 uncached tokens: about 9.6 s median prefill.
- 1000-5000 uncached tokens: about 20.3 s median prefill.
- 5000-10000 uncached tokens: about 71.4 s median prefill.
- 10000-20000 uncached tokens: about 152.4 s median prefill.

This is the clearest model in the whole dataset: prefill time tracks the uncached suffix,
not just the nominal cache-hit percentage.

### 2.3 Latency by cache band

![Latency by cache band](docs/img/dflash/cache_band_latency.png)

What happened in aggregate:

1. The 0-80% cache bands are still in the slow regime.
2. 90-95% is better, but it is still not “fast”.
3. 95-99% is the turning point.
4. 99-100% is where DFlash becomes obviously worth it.

What the numbers tell us:

- 80-90% cache is an improvement, but not the end state.
- The speedup is nonlinear.
- The model only looks fast when the cache reuse is almost complete.

### 2.4 Longest session

![Longest session](docs/img/dflash/session_maturity.png)

This chart shows the longest run in the dataset.

What happened in this session:

1. The prompt grew over time.
2. Once the prompt stabilized, later turns reused most of the prefix.
3. Prefill then dropped from long, expensive runs to a few seconds.

What the numbers tell us:

- DFlash does not get faster because time passes.
- It gets faster because the prompt becomes reusable.
- The real gain appears after the first cold prefill has created a stable prefix.

### 2.5 Per-session views

Per-session composites live in `docs/img/dflash/sessions/`.
They show the same pattern at session level: prompt growth first, then latency collapse when
reuse becomes nearly complete.

The plotter renders 22 session images here because one very short session falls below the
minimum chart threshold.

Two useful examples:

- `dflash_session_d17_20260630_0038.png`
  - 12 calls.
  - Median cache hit: 86.1%.
  - Median prefill: 18.05 s.

- `dflash_session_d22_20260705_1211.png`
  - 816 calls.
  - Median cache hit: 99.7%.
  - Median prefill: 0.80 s.

The lesson is not that long sessions always help. The lesson is that long sessions tend to
help only when they keep reusing the same scaffold.

---

## 3. What is true, and what is not

### The truth

1. The first cold prefill is expensive.
2. After that, DFlash can make later requests dramatically faster.
3. The strongest gains appear when the uncached suffix shrinks to a few hundred tokens or less.
4. 99%+ cache reuse is the clearest “fast path”.

### The misconception to avoid

It is not accurate to say that “80-90% cache means fast”.

The data says:

- 80-90% cache is still typically tens of seconds.
- 90-95% cache is better, but still not the fast path.
- 95-99% cache is the point where latency drops sharply.
- 99-100% cache is where the request usually becomes obviously quick.

### A simple practical model

```text
if cache_hit_pct < 80:        DFlash is still in the slow regime
if 80-90:                     better, but not fast
if 90-95:                     useful improvement
if 95-99:                     strong speedup
if 99-100:                    fast path
```

Or, in uncached-token terms:

```text
if uncached_tokens <= 100:    near-instant
if 100-1000:                  fast to moderate
if 1000-5000:                 noticeable latency
if 5000+:                     slow again
```

### Target comparison note

The two main dflash targets behave differently in absolute median latency, but the same cache
curve applies to both.

| Target | Rows | Median prefill |
|---|---:|---:|
| Qwen3.6-27B-4bit | 2,094 | 3.6 s |
| Qwen3.6-35B-A3B-4bit | 1,079 | 1.1 s |

That difference is mostly a workload-mix effect, not proof that one model is intrinsically
faster in the abstract. The real driver is still how much of the prompt is reused.

---

## 4. Conclusions

1. DFlash gives the largest benefit after the first cold prefill has populated the prefix cache.
2. The real efficiency threshold is much higher than 80-90% reuse; it is closer to 95-99%.
3. 99%+ cache reuse is where DFlash becomes clearly fast.
4. The uncached suffix is the best predictor of prefill latency.
5. The model is simple: long reusable scaffolds pay off; short or highly variable requests do not.

In short: DFlash is not merely “better after the first prefill”. It becomes truly efficient when the same prefix is reused almost entirely.
