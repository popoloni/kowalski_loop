"""Phase 3.5 — lightweight run observability (budget guard support).

Greenfield: there is no existing token/cost accounting in llmstack, so
`estimate_tokens` is a coarse character-count proxy, not a real tokenizer.
`log_run` appends one JSON line per completed task to a runlog file, purely
for observability — it must never be able to break the main loop, so all
failures are swallowed (and printed as a warning).
"""
import json
import os
import time


def estimate_tokens(*texts):
    total_chars = sum(len(t) for t in texts if t)
    return total_chars // 4


def default_runlog_path(dev_root, config=None):
    configured = (config or {}).get("runlog_file")
    if configured:
        return configured if os.path.isabs(configured) else os.path.join(dev_root, configured)
    return os.path.join(dev_root, "logs", "kowalski_runlog.jsonl")


def log_run(dev_root, config, entry):
    try:
        path = default_runlog_path(dev_root, config)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        entry = dict(entry)
        entry.setdefault("logged_at", time.time())
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 - observability must never break the loop
        print(f"⚠️  [Kowalski] Failed to write runlog entry: {exc}")
