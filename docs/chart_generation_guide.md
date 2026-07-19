# Generating Charts from Kowalski Loop Telemetry

## How to use `plot_timings.py`

![Chart generation banner](img/chart_generation.png)

---

## What it does

`llmstack/tools/plot_timings.py` reads the raw telemetry collected by DFlash (and other backends) during your Kowalski sessions and produces publication-ready charts:

| Chart | File | What it shows |
|-------|------|---------------|
| Prefill cliff | `docs/img/prefill_cliff.png` | Prefill time vs prompt size, cache HIT vs MISS |
| Context memory | `docs/img/context_memory.png` | Prompt tokens + MLX peak memory over the longest session |
| Cache hit distribution | `docs/img/cachehit_hist.png` | Per-call total time, hit vs miss for large prompts |
| **Energy break-even** | `docs/img/energy_break_even.png` | **NEW** — cumulative local cost (energy + depreciation) vs cloud API cost |
| **Energy cost** | `docs/img/energy_cost.png` | **NEW** — cumulative energy cost over the full session history |
| Per-session composites | `docs/img/sessions/session_s*.png` | 3-panel view per work session (prefill, context, total time) |

---

## Prerequisites

- Python environment with the packages from `pyproject.toml` (activated)
- A populated `logs/dflash_timings.csv` file (generated automatically by DFlash when running with telemetry enabled)
- A valid `llmstack_config.json` with a `"hardware"` section (see below)

---

## Quick start

```bash
cd ~/local-llm-workspace
env/bin/python llmstack/tools/plot_timings.py
```

That's it. The script:

1. Reads `llmstack_config.json` to find the CSV path (default: `./logs/dflash_timings.csv`)
2. Derives session boundaries from gaps > 60 minutes between calls
3. Derives a `miss` flag from `cache_hit_pct < 50%`
4. Renders 5 aggregate charts into `docs/img/`
5. Renders per-session 3-panel composites into `docs/img/sessions/`

---

## Input data format

The script expects a CSV with these columns (produced by DFlash telemetry):

```
backend, served_target, timestamp, req, prompt_tokens, cached_tokens,
cache_hit_pct, prefill_time_s, decode_tokens, decode_tps, decode_time_s,
total_time_s, accept_pct, prefill_real_tps, mlx_active_gb, mlx_peak_gb
```

Additional columns (`session_id`, `session_label`, `miss`) are **derived** by the script — you do not need to produce them.

---

## Configuration

The script reads `llmstack_config.json`. Two fields matter:

### `timings_csv` (optional)

Override the default CSV path:

```json
{
  "timings_csv": "./logs/my_custom_timings.csv"
}
```

### `hardware` (required for energy charts)

The energy charts (`energy_break_even.png`, `energy_cost.png`) read hardware specs from config:

```json
{
  "hardware": {
    "purchase_price_usd": 3499,
    "expected_life_years": 5,
    "power_supply_w": 140,
    "avg_grid_cost_kwh": 0.15
  }
}
```

If missing, defaults are used ($3000 purchase, 5 years, 80W average draw, $0.15/kWh).

---

## Understanding the new energy charts

### `energy_break_even.png`

Plots two cumulative cost curves:

- **Red line** — Cloud API cost (estimated at ~$0.27/M input tokens, $1.10/M output tokens for Qwen3-tier models)
- **Green line** — Local cost = energy cost + hardware depreciation

A dashed yellow marker shows the **break-even point** — the call number where local stops being more expensive than cloud.

**Interpretation:**
- If break-even is early (call #0–#100), your local hardware pays for itself quickly
- If break-even is never reached, local is still cheaper for your workload size
- The chart accounts for hardware depreciation (purchase price / useful life hours)

### `energy_cost.png`

Shows cumulative energy cost (excl. depreciation) over elapsed time. Useful for:

- Estimating electricity cost of long-running sessions
- Comparing energy efficiency across models
- Planning capacity for extended autonomous runs

---

## Customization

You can modify these constants at the top of the script:

```python
BIG_PROMPT_TOKENS = 5000        # Calls above this are "big"
SESSION_GAP_MINUTES = 60        # Gap to start a new session
SESSION_MIN_CALLS = 5           # Minimum calls to render a session chart
METAL_LIMIT_GB = 52             # Apple Silicon memory ceiling for reference
HIST_BINS = [0, 2, 5, 10, 30, 60, 120, 300, 600, 1200]  # Histogram bins (seconds)
```

---

## Troubleshooting

### "timings CSV not found"

Make sure DFlash is running with telemetry enabled. Check your config:

```bash
grep timings_csv llmstack_config.json
```

Or run manually:

```bash
ls -la logs/dflash_timings.csv
```

### "No >=5k-token calls in this slice"

Your dataset may be too small or all calls are short prompts. Run more sessions or use larger context regeneration tasks.

### Missing energy charts

Check that `llmstack_config.json` contains a `"hardware"` section (see Configuration above).

### Charts look empty or have no data

Verify the CSV has data:

```bash
wc -l logs/dflash_timings.csv
head -3 logs/dflash_timings.csv
```

You need at least a few hundred rows for meaningful charts.

---

## Example: full workflow

```bash
# 1. Ensure your config points to the right CSV
grep timings_csv llmstack_config.json

# 2. Verify data exists
wc -l logs/dflash_timings.csv

# 3. Run the chart generator
env/bin/python llmstack/tools/plot_timings.py

# 4. Check output
ls -lh docs/img/energy_break_even.png docs/img/energy_cost.png
ls -lh docs/img/sessions/
```

---

## See also

- [Measuring the Kowalski Loop](medium_article_04_measuring_the_loop.md) — the narrative article behind the metrics
- [SAVINGS.md](../SAVINGS.md) — per-model cost analysis
- [DFLASH.md](../DFLASH.md) — DFlash cache mechanics
