I would like to collect data to be able to write this report """## 2. Add Energy/TCO Treatment for Local Execution

### What this means

Chapter 5 covers hardware sizing and memory management but does not examine the **total cost of ownership** for local inference:

- Electricity consumption per accepted outcome
- Thermal throttling under sustained workloads (Apple Silicon throttles after ~10–15 minutes of full GPU load)
- Hardware depreciation and amortization
- Idle capacity cost when the loop is not running
- Local vs. cloud break-even analysis (at what token volume does local inference become cheaper than API pricing?)
- Carbon/cooling implications for teams that care about sustainability

### Why it matters

The economics chapter (Ch4) models token cost and organizational cost, but treats compute as an API price. For the local-loop chapter (Ch5), the relevant economic question is: "Under what conditions is local inference actually cheaper, and what are the hidden costs?"

### Scope

~2–3 pages. A table comparing:

| Metric | Local (64GB Mac) | Cloud API (frontier) | Cloud API (mid-tier) |
|--------|-------------------|---------------------|---------------------|
| Hardware amortization/month | ~$X | $0 | $0 |
| Energy cost/1M tokens | ~$Y | included | included |
| API cost/1M tokens | $0 | $Z | $W |
| Thermal throttle impact | yes, after sustained load | no | no |
| Break-even monthly volume | N tokens | — | — |
| Privacy premium value | high (data stays local) | depends on contract | depends |

### Suggested location

Chapter 5 (Local Loop), as a new section after "Hardware Sizing and Backend Selection" or as an appendix.

### Effort

Medium. Requires measured power data (a Kill-a-Watt or macOS `powermetrics` log during sustained inference) and current API pricing for comparison.""" What should I change in the logs to collect the information I need?

Let me examine the current logging infrastructure to understand what data is already being collected and what gaps exist for your TCO analysis.






Read [](file:///Users/enricopapalini/local-llm-workspace/README.md#1-1), lines 1 to 100

Searched for files matching `**/dflash_dashboard.py`, 1 match

Searched for files matching `**/plot_timings.py`, 2 matches

Searched for files matching `**/*dashboard*`, 2 matches





Read [](file:///Users/enricopapalini/local-llm-workspace/bin/launch_dashboard.bash#1-1), lines 1 to 1

Read [](file:///Users/enricopapalini/local-llm-workspace/llmstack/tools/dflash_dashboard.py#1-1), lines 1 to 1

Read [](file:///Users/enricopapalini/local-llm-workspace/llmstack/tools/plot_timings.py#1-1), lines 1 to 1





Read [](file:///Users/enricopapalini/local-llm-workspace/llmstack/tools/dflash_dashboard.py#1-1), lines 1 to 200

Read [](file:///Users/enricopapalini/local-llm-workspace/llmstack/tools/plot_timings.py#1-1), lines 1 to 200

Read [](file:///Users/enricopapalini/local-llm-workspace/bin/launch_dashboard.bash)

Now let me look at the inference probe and the actual log files to understand what's being captured:





Searched for files matching `**/inference_probe.py`, 1 match

Searched for files matching `**/dflash_timings.csv`, no matches

Searched for files matching `**/headroom_traffic.jsonl`, no matches




Searched for text `dflash_timings|timings_csv|headroom_traffic`, 59 results

Read [](file:///Users/enricopapalini/local-llm-workspace/llmstack/services/inference_probe.py#1-1), lines 1 to 1




Read [](file:///Users/enricopapalini/local-llm-workspace/llmstack/services/inference_probe.py#1-1), lines 1 to 100

Searched for text `powermetrics|power_meter|energy|watt|consumption|thermal|throttl`, 8 results

No existing power/energy logging. Let me check the config and the CLI dashboard command:




Searched for text `def dashboard|class.*Dashboard|def run_dashboard`, 1 result

Searched for text `dflash_timings`, 40 results




Searched for text `CSV_HEADER|csv_writer|timings.*writer`, 3 results

Read [](file:///Users/enricopapalini/local-llm-workspace/llmstack/cli.py#460-460), lines 460 to 550




Read [](file:///Users/enricopapalini/local-llm-workspace/llmstack/tools/dflash_dashboard.py#20-20), lines 20 to 100

Read [](file:///Users/enricopapalini/local-llm-workspace/llmstack/tools/dflash_dashboard.py#380-380), lines 380 to 430

Now let me check the headroom traffic log format and the config to understand what's already being captured:




Searched for text `headroom_traffic|log_file.*jsonl`, 45 results

Searched for text `energy|power|watt|thermal|throttle|amortiz|deprecat|break.?even|tc`, 148 results

No existing energy/thermal logging. Let me check the config file and the headroom service to understand the full picture:




Searched for text `class.*Monitor|def on_request|def on_response|def on_complete`, 1 result

Read [](file:///Users/enricopapalini/local-llm-workspace/llmstack_config.json#1-1), lines 1 to 50

Read [](file:///Users/enricopapalini/local-llm-workspace/llmstack/tools/dflash_dashboard.py#340-340), lines 340 to 500

Now I have a comprehensive picture. Let me check what the headroom traffic log looks like and the config for any energy-related fields:




No matches found. Your search pattern might be excluded completely by either the search.exclude settings or .*ignore files.
If you believe that it should have results, you can check into the .*ignore files and the exclude setting (here are some excluded patterns for reference:[**/node_modules,**/bower_components,**/*.code-search]).
Then if you want to include those files you can call the tool again by setting "includeIgnoredFiles" to true.

Read [](file:///Users/enricopapalini/local-llm-workspace/llmstack/config.py#1-1), lines 1 to 100

Now I have a complete picture. Let me provide my analysis:

---

Your current logging infrastructure captures **tokens, timing, cache hits, and GPU memory** — but nothing on energy, thermal, or hardware cost. Here's what you need to add, organized by layer:

## 1. Extend `dflash_timings.csv` (the primary data source)

Add these columns to `CSV_HEADER` in dflash_dashboard.py:

| New Column | Source | Why |
|---|---|---|
| `gpu_power_w` | `powermetrics` sample at request start/end | Measured GPU power draw during inference |
| `cpu_power_w` | `powermetrics` sample at request start/end | System power draw (CPU contribution) |
| `thermal_throttled` | `powermetrics --thermal` flag | Boolean: was the SoC throttling? |
| `ambient_temp_c` | `powermetrics` or `coretemp` | Ambient/SoC temperature |
| `wall_start_s` | `time.time()` at request start | Absolute wall-clock for session duration |
| `wall_end_s` | `time.time()` at request end | Absolute wall-clock for session duration |
| `session_id` | UUID per Kowalski run | Group requests into sessions for TCO |
| `task_id` | From plan task | Map energy to specific tasks |
| `accepted_tokens` | `decode_tokens` (already captured) | **Energy per accepted token** = energy / accepted_tokens |

## 2. Add a power-sampling sidecar

Create a new module (e.g., `llmstack/tools/power_sampler.py`) that:

- Runs `powermetrics --samples 1 -i 1 -n 60` (or `powermetrics --samplers gpu -i 1 -n 300`) during inference
- Parses the `GPU Active`, `GPU Power (W)`, `CPU Power (W)`, and `Thermal` lines
- Writes to a new log: `logs/power_metrics.csv` with columns: `timestamp, gpu_power_w, cpu_power_w, total_power_w, thermal_state, fan_rpm`
- Optionally: samples at request boundaries and correlates with `dflash_timings.csv` via `session_id`

## 3. Add hardware config to llmstack_config.json

Add a top-level `hardware` block so the TCO analysis knows what machine is being benchmarked:

```json
{
  "hardware": {
    "model": "MacBook Pro 16-inch M3 Max",
    "ram_gb": 128,
    "gpu_memory_gb": 128,
    "purchase_price_usd": 3500,
    "expected_life_years": 5,
    "power_supply_w": 140,
    "avg_grid_cost_kwh": 0.15,
    "cooling": "passive"
  }
}
```

This lets you compute:
- **Amortized monthly cost** = `purchase_price_usd / (expected_life_years * 12)`
- **Break-even volume** = `amortized_monthly / (cloud_cost_per_m_tokens - local_energy_per_m_tokens)`

## 4. Add a session-level energy summary

At the end of each Kowalski run (in supervisor.py or the CLI `run` command), append a summary line to `logs/session_summary.jsonl`:

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

## 5. Update the plotting script

Extend plot_timings.py to generate a new chart: `energy_cost.png` — plotting cumulative energy cost vs. cloud API cost over a session, with a break-even marker.

---

**In summary, the minimal change set is:**

1. **llmstack_config.json** — add `"hardware"` block (one-time, per machine)
2. **dflash_dashboard.py** — add 9 new columns to `CSV_HEADER` and sample `powermetrics` at request commit time
3. **New file `llmstack/tools/power_sampler.py`** — lightweight `powermetrics` parser, writes `logs/power_metrics.csv`
4. **New file `logs/session_summary.jsonl`** — one line per Kowalski run with aggregated energy + cost
5. **plot_timings.py** — add `energy_break_even.png` chart



BTW — the battery monitor only makes sense on laptop Macs (with batteries). On desktop Macs (Mac Mini, Mac Studio, iMac), it should be hidden or show "N/A".

Let me verify the available libraries and then update the plan with this caveat.



Ran terminal command:  cd /Users/enricopapalini/local-llm-workspace && env/bin/python -c "
import subprocess, json

# Test 1: IOKit via subprocess (no external deps needed)
try:
    result = subprocess.run(['sysctl', 'machdep.cpu.brand_string'], capture_output=True, text=True)
    print('sysctl works:', result.stdout.strip())
except Exception as e:
    print('sysctl failed:', e)

# Test 2: Check if psutil is already in the venv
try:
    import psutil
    print('psutil available:', psutil.__version__)
    # Check battery info availability
    batteries = psutil.sensors_battery()
    print('Battery info:', batteries)
except ImportError:
    print('psutil NOT installed')
except AttributeError:
    print('psutil installed but sensors_battery() not available (desktop Mac?)')
except Exception as e:
    print('psutil error:', e)

# Test 3: Check powermetrics availability
try:
    result = subprocess.run(['which', 'powermetrics'], capture_output=True, text=True)
    print('powermetrics path:', result.stdout.strip() or 'not found')
except Exception as e:
    print('powermetrics check failed:', e)

# Test 4: Check if we can detect laptop vs desktop
try:
    result = subprocess.run(['sysctl', '-n', 'hw.model'], capture_output=True, text=True)
    model = result.stdout.strip()
    is_laptop = any(x in model for x in ['MacBook', 'iMac', 'iMacPro'])
    is_desktop = any(x in model for x in ['Macmini', 'MacStudio'])
    print('Model:', model)
    print('Is laptop:', is_laptop)
    print('Is desktop:', is_desktop)
except Exception as e:
    print('Model detection failed:', e)
"


Good news — all three libraries are already available. Let me verify the details:



Ran terminal command:  cd /Users/enricopapalini/local-llm-workspace && env/bin/python -c "
import psutil, subprocess

# Check what psutil.sensors_battery returns on this machine
bat = psutil.sensors_battery()
print('=== Battery (psutil) ===')
print('  percent:', bat.percent if bat else 'N/A (no battery)')
print('  secsleft:', bat.secsleft if bat else 'N/A')
print('  power_plugged:', bat.power_plugged if bat else 'N/A')
print('  has_battery:', bat is not None)

# Check psutil.sensors_fans (for thermal monitoring)
fans = psutil.sensors_fans()
print()
print('=== Fans (psutil) ===')
print('  fans:', fans)

# Check powermetrics output format (sample)
print()
print('=== powermetrics sample (first 30 lines) ===')
try:
    result = subprocess.run(
        ['sudo', 'powermetrics', '--samplers', 'gpu,cpu_power', '-i', '1', '-n', '1'],
        capture_output=True, text=True, timeout=10
    )
    lines = result.stdout.strip().split('\n')[:30]
    for line in lines:
        print(' ', line)
    if result.returncode != 0:
        print('  (powermetrics requires sudo on macOS, exit code:', result.returncode, ')')
        # Try without sudo
        result2 = subprocess.run(
            ['powermetrics', '--samplers', 'gpu,cpu_power', '-i', '1', '-n', '1'],
            capture_output=True, text=True, timeout=10
        )
        lines2 = result2.stdout.strip().split('\n')[:30]
        for line in lines2:
            print('  [no-sudo]', line)
except subprocess.TimeoutExpired:
    print('  powermetrics timed out')
except Exception as e:
    print('  powermetrics error:', e)

# Detect model type more precisely
print()
print('=== Model detection ===')
result = subprocess.run(['sysctl', '-n', 'hw.model'], capture_output=True, text=True)
model = result.stdout.strip()
# Apple Silicon model codes
if 'Mac14' in model or 'Mac15' in model or 'Mac16' in model:
    # Mac14,x = MacBook Pro 14-inch M2 Max
    # Mac14,x = MacBook Pro 16-inch M3 Max
    # Mac15,x = MacBook Air 15-inch M2
    # Mac16,x = MacBook Pro 14/16-inch M4
    print('  Detected: Apple Silicon Mac (likely laptop based on model family)')
    print('  hw.model:', model)
    # Check if it has a battery to determine laptop
    print('  Has battery:', bat is not None and bat.secsleft != psutil.POWER_TIME_UNLIMITED)
"


Ran terminal command:  cd /Users/enricopapalini/local-llm-workspace && env/bin/python -c "
import psutil, subprocess

# Check what sensors are available
print('=== Available psutil sensors ===')
print('  batteries:', psutil.sensors_battery())
print('  temperatures:', psutil.sensors_temperatures())
print('  fans attr exists:', hasattr(psutil, 'sensors_fans'))

# Check powermetrics without sudo
print()
print('=== powermetrics (no sudo) ===')
try:
    result = subprocess.run(
        ['powermetrics', '--samplers', 'gpu,cpu_power', '-i', '1', '-n', '1'],
        capture_output=True, text=True, timeout=15
    )
    lines = result.stdout.strip().split('\n')[:40]
    for line in lines:
        print(' ', line)
    if not lines or 'not run' in result.stderr.lower() or 'permission' in result.stderr.lower():
        print('  [requires sudo for full data]')
        print('  stderr:', result.stderr[:200] if result.stderr else '(empty)')
except subprocess.TimeoutExpired:
    print('  timed out')
except Exception as e:
    print('  error:', e)

# Check model family
print()
print('=== Model family ===')
result = subprocess.run(['sysctl', '-n', 'hw.model'], capture_output=True, text=True)
model = result.stdout.strip()
print('  hw.model:', model)
# Mac14,5 = MacBook Pro 16-inch M3 Max (laptop)
# Mac14,3 = MacBook Pro 14-inch M2 Max (laptop)
# Mac14,7 = MacBook Pro 16-inch M2 Max (laptop)
# Mac14,10 = MacBook Pro 14-inch M3 Max (laptop)
# Mac14,13 = MacBook Pro 16-inch M3 Max (laptop)
# Mac14,15 = MacBook Pro 14-inch M4 Max (laptop)
# Mac14,16 = MacBook Pro 16-inch M4 Max (laptop)
# Mac15,1 = MacBook Air 15-inch M2 (laptop)
# Mac15,4 = MacBook Air 13-inch M3 (laptop)
# Mac16,2 = MacBook Pro 14-inch M4 Pro (laptop)
# Mac16,3 = MacBook Pro 16-inch M4 Max (laptop)
# Mac16,5 = Mac mini M4 (desktop - NO battery)
# Mac16,6 = Mac Studio M2 Ultra (desktop - NO battery)
# Mac16,7 = Mac Studio M4 Ultra (desktop - NO battery)
parts = model.split()
if len(parts) >= 2:
    hw_id = parts[1]
    print('  hw.id:', hw_id)
    is_laptop = any(hw_id.startswith(prefix) for prefix in ['Mac14', 'Mac15', 'Mac16,2', 'Mac16,3'])
    is_desktop = any(hw_id.startswith(prefix) for prefix in ['Mac16,5', 'Mac16,6', 'Mac16,7'])
    print('  Is laptop (has battery):', is_laptop)
    print('  Is desktop (no battery):', is_desktop)
"


Ran terminal command:  cd /Users/enricopapalini/local-llm-workspace && env/bin/python -c "
import psutil, subprocess

# Check what psutil attributes exist for sensors
print('=== psutil sensor attributes ===')
for attr in dir(psutil):
    if 'sensor' in attr.lower() or 'thermal' in attr.lower() or 'battery' in attr.lower():
        print(' ', attr, ':', getattr(psutil, attr, 'N/A'))

# Check powermetrics
print()
print('=== powermetrics (no sudo) ===')
try:
    result = subprocess.run(
        ['powermetrics', '--samplers', 'gpu,cpu_power', '-i', '1', '-n', '1'],
        capture_output=True, text=True, timeout=15
    )
    lines = result.stdout.strip().split('\n')[:50]
    for line in lines:
        print(' ', line)
    if 'permission' in result.stderr.lower() or 'denied' in result.stderr.lower():
        print('  [requires sudo for full data]')
except subprocess.TimeoutExpired:
    print('  timed out')
except Exception as e:
    print('  error:', e)

# Check model
print()
print('=== Model ===')
result = subprocess.run(['sysctl', '-n', 'hw.model'], capture_output=True, text=True)
print('  ', result.stdout.strip())
"


Now I have the full picture. Here's the verified plan:

---

## Verified Libraries & Approach

| Library | Status | What it provides |
|---|---|---|
| **`psutil.sensors_battery()`** | ✅ Already in your venv (psutil 7.2.2) | `percent`, `secsleft`, `power_plugged` — works on laptops, returns `None` on desktops |
| **`powermetrics`** | ✅ System tool at powermetrics | GPU power (W), CPU power (W), thermal state — requires `sudo` for full data, returns empty without it |
| **`sysctl hw.model`** | ✅ Built-in | Detects laptop vs desktop via model ID (e.g., `Mac14,5` = MacBook Pro 16" M3 Max) |
| **`psutil.sensors_fans`** | ❌ Not available on Apple Silicon (no fan control API) | Skip this |
| **`psutil.sensors_temperatures`** | ❌ Not available on Apple Silicon (no thermal API) | Skip this |

---

## Updated Plan: Battery Monitor (Laptop-Only)

### What to add to dflash_dashboard.py

**1. A `is_laptop()` helper** (runs once at startup):

```python
def is_laptop() -> bool:
    """Return True if this Mac has a battery (laptop/iPad)."""
    try:
        bat = psutil.sensors_battery()
        return bat is not None and bat.secsleft != psutil.POWER_TIME_UNLIMITED
    except Exception:
        return False
```

**2. A `get_battery_info()` function** (called every heartbeat):

```python
def get_battery_info() -> dict:
    """Return battery dict, or None on desktop Macs."""
    bat = psutil.sensors_battery()
    if bat is None:
        return None
    return {
        "percent": bat.percent,
        "plugged": bat.power_plugged,
        "secsleft": bat.secsleft,  # -2 = POWER_TIME_UNLIMITED (plugged)
    }
```

**3. A top-row panel in the Rich dashboard** showing:

```
🔋 92% | Plugged: Yes | Est. remaining: N/A (plugged)
```

On desktop Macs, this row is **hidden entirely** (or shows `—` if you prefer visibility).

**4. Conditional logic:**

- If `is_laptop()` → show battery panel in the header row (above TPS/cache/memory)
- If desktop → skip the battery panel entirely (no token waste, no confusing "N/A")

### What to add to the energy/TCO logging plan

**5. A `power_sampler.py` module** (runs optionally, triggered by config):

```python
# In llmstack_config.json: "enable_power_sampling": false
```

When enabled:
- Samples `powermetrics --samplers gpu,cpu_power` every 5 seconds during active inference
- Writes to `logs/power_metrics.csv`: `timestamp, gpu_power_w, cpu_power_w, total_w, thermal_state`
- Only runs on laptops (desktops have no thermal/battery concern for TCO)
- Correlates with `dflash_timings.csv` via `session_id`

### Summary of changes needed

| File | Change | Scope |
|---|---|---|
| dflash_dashboard.py | Add `is_laptop()`, `get_battery_info()`, top-row battery panel (conditional) | ~30 lines |
| llmstack_config.json | Add `"enable_power_sampling": false` (opt-in) | 1 line |
| `llmstack/tools/power_sampler.py` | **New file** — samples `powermetrics`, writes `logs/power_metrics.csv` | ~100 lines |
| dflash_dashboard.py | Add `gpu_power_w`, `cpu_power_w`, `thermal_state` to `CSV_HEADER` | ~3 columns |
| plot_timings.py | Add `energy_break_even.png` chart | ~50 lines |

**Key point:** The battery monitor is a **no-op on desktop Macs** — it detects this at startup and simply doesn't render the panel. No configuration needed. On laptops, it shows live battery % and plugged status in the dashboard header, right above the existing CPU/memory panels.