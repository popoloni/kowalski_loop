#!/usr/bin/env python3
"""Migrate dflash_timings.csv: pad old 16-column rows to match the 23-column CSV_HEADER.

Usage:
    env/bin/python llmstack/tools/migrate_timings_csv.py

Behavior:
    1. Backs up the original CSV to logs/dflash_timings.csv.bak
    2. Rewrites the header to match the new 23-column CSV_HEADER
    3. Pads any row with fewer fields than CSV_HEADER with empty trailing values
    4. Leaves rows with >= CSV_HEADER fields untouched
    5. Writes everything back in-place (original preserved as .bak)
"""

import csv
import os
import sys
from pathlib import Path

# Import CSV_HEADER from dflash_dashboard — avoid circular import by reading it
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from llmstack.tools.dflash_dashboard import CSV_HEADER

TIMINGS_CSV = Path("logs/dflash_timings.csv")
BACKUP_SUFFIX = ".bak"


def migrate():
    if not TIMINGS_CSV.exists():
        print(f"[SKIP] {TIMINGS_CSV} does not exist. Nothing to do.")
        return

    expected_ncols = len(CSV_HEADER)
    print(f"CSV_HEADER has {expected_ncols} columns: {', '.join(CSV_HEADER)}")

    # --- Step 1: Create backup ---
    backup = Path(str(TIMINGS_CSV) + BACKUP_SUFFIX)
    import shutil
    shutil.copy2(TIMINGS_CSV, backup)
    print(f"[OK] Backup created: {backup}")

    # --- Step 2: Read all rows ---
    with open(TIMINGS_CSV, "r", newline="") as f:
        reader = csv.reader(f)
        all_rows = list(reader)

    if not all_rows:
        print("[SKIP] File is empty.")
        return

    old_header = all_rows[0]
    data_rows = all_rows[1:]
    print(f"[INFO] Existing header ({len(old_header)} cols): {', '.join(old_header)}")
    print(f"[INFO] Data rows: {len(data_rows)}")

    # --- Step 3: Count rows by field count ---
    old_rows = 0
    padded_rows = 0
    skipped_rows = 0

    for row in data_rows:
        if len(row) < expected_ncols:
            old_rows += 1
        elif len(row) == expected_ncols:
            skipped_rows += 1
        else:
            skipped_rows += 1  # rows with more columns are left as-is

    print(f"[INFO] Rows needing padding: {old_rows}")
    print(f"[INFO] Rows already correct:  {skipped_rows}")

    # --- Step 4: Write migrated file ---
    with open(TIMINGS_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for row in data_rows:
            if len(row) < expected_ncols:
                # Pad with empty strings to match CSV_HEADER length
                padded = row + [""] * (expected_ncols - len(row))
                writer.writerow(padded)
                padded_rows += 1
            else:
                writer.writerow(row)

    print(f"[OK] Padded {padded_rows} rows with {expected_ncols - min(len(r) for r in data_rows)} empty trailing fields")
    print(f"[OK] Migrated {TIMINGS_CSV} (backup at {backup})")
    print(f"[OK] New file has {len(data_rows) + 1} lines (1 header + {len(data_rows)} data rows)")


if __name__ == "__main__":
    migrate()
