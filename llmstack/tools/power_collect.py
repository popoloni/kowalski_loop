from __future__ import annotations
import argparse
import subprocess
import sys
import time
from llmstack.config import load_config
from llmstack.tools.power_sampler import PowerSampler


def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument('--mode',choices=['idle','light','sustained'],default='sustained');ap.add_argument('--duration',type=int,default=60)
    args=ap.parse_args(argv)
    if args.duration < 1: ap.error('--duration must be positive')
    cfg=load_config(); sampler=PowerSampler(cfg)
    print(f"Collecting {args.mode} power samples for {args.duration}s into {sampler.csv_path}")
    sampler.start()
    try:
        time.sleep(args.duration)
    except KeyboardInterrupt:
        pass
    finally:
        sampler.stop()
    return 0
if __name__=='__main__': raise SystemExit(main())
