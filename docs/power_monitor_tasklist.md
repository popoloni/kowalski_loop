# Power Monitor & TCO Analysis — Implementation Task List

> Source: `docs/power_monitor_plan.md`
> Goal: Add energy/total-cost-of-ownership (TCO) treatment for local inference, targeting ~2–3 pages for Chapter 5 (Local Loop).

---

## Phase 0 — Prerequisites & Discovery

- [ ] **0.1** Verify current logging infrastructure: audit `dflash_timings.csv` columns, `headroom_traffic.jsonl` format, and `inference_probe.py` output
- [ ] **0.2** Confirm available libraries in venv: `psutil` (battery/fans), `powermetrics` (system CLI), `sysctl` (model detection)
- [ ] **0.3** Detect machine type: run `sysctl -n hw.model` to classify as laptop (MacBook Pro/Air) vs desktop (Mac Mini/Studio/iMac)
- [ ] **0.4** Document current API pricing for frontier and mid-tier providers (per 1M tokens) for break-even comparison

---

## Phase 1 — Hardware Configuration

- [ ] **1.1** Add `"hardware"` block to `llmstack_config.json` with fields:
  - `model` (e.g., "MacBook Pro 16-inch M3 Max")
  - `ram_gb`, `gpu_memory_gb`
  - `purchase_price_usd`
  - `expected_life_years`
  - `power_supply_w`
  - `avg_grid_cost_kwh`
  - `cooling` ("passive" / "active")
- [ ] **1.2** Add `"enable_power_sampling": false` flag (opt-in, default off)
- [ ] **1.3** Add `"battery_monitor_enabled": false` flag (opt-in, default off)

**Estimated effort:** 15 minutes (config edits only)

---

## Phase 2 — Battery Monitor (Laptop-Only)

- [ ] **2.1** Create `is_laptop()` helper in `dflash_dashboard.py`:
  - Uses `psutil.sensors_battery()` to detect presence of battery
  - Returns `True` if battery exists AND `secsleft != psutil.POWER_TIME_UNLIMITED`
  - Returns `False` on desktop Macs (no panel rendered)
- [ ] **2.2** Create `get_battery_info()` function:
  - Returns dict: `{percent, plugged, secsleft}` or `None` on desktops
- [ ] **2.3** Add top-row battery panel to Rich dashboard:
  - Display: `🔋 92% | Plugged: Yes | Est. remaining: N/A (plugged)`
  - On desktop Macs: panel hidden entirely (no token waste)
  - Position: above existing CPU/memory panels in header row
- [ ] **2.4** Add conditional rendering logic:
  - `is_laptop()` → render battery panel
  - Desktop → skip panel entirely (no "N/A" noise)

**Estimated effort:** ~30 lines of code

---

## Phase 3 — Power Sampling Sidecar

- [ ] **3.1** Create new file: `llmstack/tools/power_sampler.py`
- [ ] **3.2** Implement `sample_powermetrics()`:
  - Runs `powermetrics --samplers gpu,cpu_power -i 1 -n 1` (requires `sudo` for full data)
  - Parses output lines for: `GPU Power (W)`, `CPU Power (W)`, `Thermal State`, `Fan RPM`
  - Falls back gracefully if `sudo` not available (log warning, continue without power data)
- [ ] **3.3** Implement `PowerSampler` class:
  - Configurable sampling interval (default: every 5 seconds during active inference)
  - Writes to `logs/power_metrics.csv` with columns:
    - `timestamp, gpu_power_w, cpu_power_w, total_w, thermal_state, fan_rpm`
  - Only activates when `"enable_power_sampling": true` in config
- [ ] **3.4** Implement session correlation:
  - Tag each power sample with `session_id` (UUID per Kowalski run)
  - Correlate samples with `dflash_timings.csv` entries via `session_id`
- [ ] **3.5** Add laptop-only guard: skip power sampling on desktop Macs (no thermal/battery concern for TCO)

**Estimated effort:** ~100 lines of code

---

## Phase 4 — Extended Timing Logs

- [ ] **4.1** Extend `CSV_HEADER` in `dflash_dashboard.py` with 9 new columns:
  - `gpu_power_w` — measured GPU power at request commit
  - `cpu_power_w` — measured CPU power at request commit
  - `thermal_throttled` — boolean: was the SoC throttling?
  - `ambient_temp_c` — SoC/ambient temperature (if available)
  - `wall_start_s` — `time.time()` at request start
  - `wall_end_s` — `time.time()` at request end
  - `session_id` — UUID per Kowalski run (group requests into sessions)
  - `task_id` — from plan task (map energy to specific tasks)
  - `accepted_tokens` — from `decode_tokens` (already captured, reuse)
- [ ] **4.2** Compute derived metric: `energy_per_accepted_token = total_energy_kwh / accepted_tokens`
- [ ] **4.3** Integrate `power_sampler.py` calls at request commit time in `dflash_dashboard.py`

**Estimated effort:** ~20 lines (column additions + integration)

---

## Phase 5 — Session-Level Energy Summary

- [ ] **5.1** Create `logs/session_summary.jsonl` (one line per Kowalski run)
- [ ] **5.2** Append summary at end of each Kowalski run (in `supervisor.py` or CLI `run` command):
  ```json
  {
    "session_id": "abc123",
    "start": "2026-07-18T10:00:00",
    "end": "2026-07-18T11:30:00",
    "total_prompt_tokens": 1234567,
    "total_decode_tokens": 890123,
    "total_energy_kwh": 0.42,
    "energy_cost_usd": 0.063,
    "cloud_equivalent_usd": 18.50,
    "savings_usd": 18.44,
    "thermal_throttle_minutes": 4.2,
    "peak_gpu_power_w": 98.3,
    "avg_gpu_power_w": 67.1
  }
  ```
- [ ] **5.3** Compute TCO formulas:
  - `amortized_monthly = purchase_price_usd / (expected_life_years * 12)`
  - `break_even_volume = amortized_monthly / (cloud_cost_per_m_tokens - local_energy_per_m_tokens)`
  - `cloud_equivalent_usd` — lookup current API pricing for equivalent token volume
  - `savings_usd = cloud_equivalent_usd - (energy_cost_usd + amortized_monthly)`

**Estimated effort:** ~80 lines (summary writer + TCO calculator)

---

## Phase 6 — Visualization & Reporting

- [ ] **6.1** Extend `plot_timings.py` with new chart: `energy_break_even.png`
  - Plot cumulative energy cost vs. cloud API cost over session
  - Mark break-even point with vertical line
- [ ] **6.2** Generate TCO comparison table (2–3 pages for Chapter 5):
  | Metric | Local (64GB Mac) | Cloud API (frontier) | Cloud API (mid-tier) |
  |--------|-------------------|---------------------|---------------------|
  | Hardware amortization/month | ~$X | $0 | $0 |
  | Energy cost/1M tokens | ~$Y | included | included |
  | API cost/1M tokens | $0 | $Z | $W |
  | Thermal throttle impact | yes, after sustained load | no | no |
  | Break-even monthly volume | N tokens | — | — |
  | Privacy premium value | high (data stays local) | depends on contract | depends |
- [ ] **6.3** Generate `energy_cost.png` — cumulative energy cost chart
- [ ] **6.4** Add thermal throttle duration tracking and visualization

**Estimated effort:** ~50 lines (new chart) + ~3 pages (written analysis)

---

## Phase 7 — Testing & Validation

- [ ] **7.1** Test battery monitor on laptop: verify panel renders correctly with live data
- [ ] **7.2** Test battery monitor on desktop: verify panel is hidden (no "N/A" output)
- [ ] **7.3** Test power sampling with `sudo`: verify full GPU/CPU power data captured
- [ ] **7.4** Test power sampling without `sudo`: verify graceful fallback (warning logged, no crash)
- [ ] **7.5** Run sustained inference workload (10–15 min) to trigger thermal throttling; verify throttle detection
- [ ] **7.6** Validate `session_summary.jsonl` output format and TCO calculations
- [ ] **7.7** Cross-check `power_metrics.csv` correlation with `dflash_timings.csv` via `session_id`

**Estimated effort:** 2–3 hours (real-world testing)

---

## Summary of Files to Modify/Create

| File | Action | Change | Scope |
|---|---|---|---|
| `llmstack_config.json` | Edit | Add `"hardware"` block + `"enable_power_sampling"` + `"battery_monitor_enabled"` flags | ~15 lines |
| `llmstack/tools/dflash_dashboard.py` | Edit | Add `is_laptop()`, `get_battery_info()`, battery panel, 9 new CSV columns, power sampler integration | ~50 lines |
| `llmstack/tools/power_sampler.py` | **New** | `powermetrics` parser, writes `logs/power_metrics.csv`, session correlation | ~100 lines |
| `logs/session_summary.jsonl` | **New** | One line per Kowalski run with aggregated energy + cost + TCO | ~10 lines (schema) |
| `llmstack/tools/plot_timings.py` | Edit | Add `energy_break_even.png` and `energy_cost.png` charts | ~50 lines |
| `docs/power_monitor_plan.md` | Update | Mark task list as complete, append measured data | Ongoing |

**Total estimated implementation effort:** ~4–6 hours of coding + 2–3 hours testing + 2–3 pages writing

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| `powermetrics` requires `sudo` on macOS | Graceful fallback: log warning, continue without power data |
| Desktop Macs have no battery/thermal APIs | `is_laptop()` guard: skip all battery/thermal features on desktops |
| `psutil.sensors_fans` / `sensors_temperatures` unavailable on Apple Silicon | Skip these sensors; rely on `powermetrics` for thermal data |
| `sudo` prompt blocks non-interactive runs | Make power sampling opt-in via config flag; default `false` |
| Thermal throttling varies by model | Document per-model throttle thresholds in TCO analysis |
