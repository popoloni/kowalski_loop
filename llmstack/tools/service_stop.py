from __future__ import annotations
import argparse
import json
import os
import signal
import sys
from pathlib import Path

from llmstack.config import load_config


def _record_path(cfg, service):
    return Path(cfg["log_dir"]) / f"{service}.owner.json"


def stop_owned(cfg, service):
    record = _record_path(cfg, service)
    if not record.exists():
        print(f"ℹ️  No owned {service} process record; nothing stopped.")
        return 0
    try:
        data = json.loads(record.read_text())
        pid = int(data["pid"])
        workspace = str(data["workspace"])
    except Exception as exc:
        print(f"ERROR: invalid ownership record {record}: {exc}", file=sys.stderr)
        return 2
    if workspace != str(Path(cfg["config_path"]).resolve().parent):
        print("ERROR: ownership record belongs to another workspace", file=sys.stderr)
        return 3
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    record.unlink(missing_ok=True)
    print(f"✅ Stop signal sent to owned {service} process {pid}.")
    return 0


def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument('service',choices=['inference','headroom'])
    args=ap.parse_args(argv);cfg=load_config();return stop_owned(cfg,args.service)

if __name__=='__main__': raise SystemExit(main())
