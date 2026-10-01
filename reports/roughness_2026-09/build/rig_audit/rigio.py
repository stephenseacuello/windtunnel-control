"""Shared readers for the rig-run audit. Standalone: numpy/pandas only, no repo imports."""
import csv
import io
from pathlib import Path

import pandas as pd

REPO = Path("/Users/stepheneacuello/Projects/windtunnel-control")
LOGS = REPO / "logs"
OUT = REPO / "reports/roughness_2026-09/build/rig_audit"
RUNS = ["Ra20", "Ra40", "Ra80"]          # nominal Ra order
TEST_ORDER = ["Ra20", "Ra80", "Ra40"]    # Aug 20, Aug 26, Sep 1


def wind_from_rpm(rpm):
    """Same constants as src/load_ramp.py wind_from_rpm."""
    return 0.02132 * rpm - 0.424


def read_run_file(run, kind):
    """Return (meta list of (key, value), DataFrame) for logs/sweep_v1_<run>_<kind>.csv."""
    path = LOGS / f"sweep_v1_{run}_{kind}.csv"
    meta, body = [], []
    with open(path, newline="") as f:
        for line in f:
            if line.startswith("#"):
                row = next(csv.reader([line[1:].strip()]))
                key = row[0].strip()
                val = ",".join(row[1:]).strip() if len(row) > 1 else ""
                meta.append((key, val))
            else:
                body.append(line)
    df = pd.read_csv(io.StringIO("".join(body)), keep_default_na=False)
    return meta, df


def setpoint_groups(points):
    """Contiguous blocks of rows per commanded fan rpm, in file (= trace) order."""
    blocks = []
    cur, rows = None, []
    for idx, r in points.iterrows():
        sp = int(r["fan_rpm"])
        if sp != cur:
            if rows:
                blocks.append((cur, points.loc[rows]))
            cur, rows = sp, []
        rows.append(idx)
    if rows:
        blocks.append((cur, points.loc[rows]))
    return blocks
