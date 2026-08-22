#!/usr/bin/env python3
"""
archive_logs.py — bundle old runs off the Pi.

    python archive_logs.py --older-than 30 --to ~/tunnel-archive
    python archive_logs.py --older-than 30 --to ~/archive --delete

Pre-flight warns when the log directory gets large; this is the thing that
acts on that warning. Left alone, logs fill an SD card, and the failure mode
is a write error *mid-profile* rather than a clean refusal — the player
flushes every sample by design, so a full disk lands in the middle of a run.

═══════════════════════════════════════════════════════════════════════════
WHAT IT REFUSES TO DO
═══════════════════════════════════════════════════════════════════════════
Each run is a set: the CSV, its provenance sidecar, the points table for a
sweep, and any plot. Archiving the CSV and leaving the JSON behind produces a
dataset nobody can interpret in a year — which is worse than not archiving at
all, because the data still exists and now looks trustworthy.

So runs move as complete sets, and `--delete` refuses to remove anything whose
sidecar is missing: no provenance means it cannot be safely archived, and
somebody should look at it before it disappears.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
import zipfile
from pathlib import Path


def group_runs(log_dir):
    """Collect every file belonging to each run, keyed by stem."""
    d = Path(log_dir)
    runs = {}
    for f in d.glob("*"):
        if f.is_dir():
            continue
        stem = f.stem
        if stem.endswith("_points"):
            stem = stem[:-7]
        runs.setdefault(stem, []).append(f)
    return runs


def main():
    p = argparse.ArgumentParser(description="archive old wind tunnel runs")
    p.add_argument("--log-dir", default="logs")
    p.add_argument("--to", required=True, help="archive destination directory")
    p.add_argument("--older-than", type=float, default=30,
                   help="days; runs older than this are archived")
    p.add_argument("--delete", action="store_true",
                   help="remove originals after a verified copy")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    cutoff = time.time() - a.older_than * 86400
    dest = Path(a.to)
    dest.mkdir(parents=True, exist_ok=True)

    runs = group_runs(a.log_dir)
    old = {s: fs for s, fs in runs.items()
           if max(f.stat().st_mtime for f in fs) < cutoff}

    if not old:
        print(f"  nothing older than {a.older_than:g} days in {a.log_dir}")
        return

    total = sum(f.stat().st_size for fs in old.values() for f in fs)
    print(f"  {len(old)} runs older than {a.older_than:g} days "
          f"({total / 1e6:.1f} MB)")

    archived = skipped = 0
    for stem, files in sorted(old.items()):
        has_meta = any(f.suffix == ".json" for f in files)
        if not has_meta:
            print(f"  SKIP {stem} — no provenance sidecar. Look at this one "
                  f"before it goes anywhere.")
            skipped += 1
            continue

        target = dest / f"{stem}.zip"
        if a.dry_run:
            print(f"  would archive {stem} ({len(files)} files) → {target.name}")
            archived += 1
            continue

        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            for f in files:
                z.write(f, f.name)

        # Verify before deleting anything. An archive that silently failed to
        # write is worse than no archive, because you delete the original
        # believing it is safe.
        with zipfile.ZipFile(target) as z:
            if z.testzip() is not None or len(z.namelist()) != len(files):
                print(f"  FAILED verify on {stem} — originals left in place")
                continue

        if a.delete:
            for f in files:
                f.unlink()
        archived += 1
        print(f"  {stem}: {len(files)} files → {target.name}"
              + (" (originals removed)" if a.delete else ""))

    print(f"\n  archived {archived}, skipped {skipped}")
    if not a.delete and archived and not a.dry_run:
        print("  originals kept. Re-run with --delete once you have checked "
              "the archive.")


if __name__ == "__main__":
    main()
