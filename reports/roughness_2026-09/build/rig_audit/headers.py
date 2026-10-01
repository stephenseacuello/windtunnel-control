#!/usr/bin/env python3
"""Tabulate every '#' header line and the column sets, per run and file."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from rigio import OUT, RUNS, read_run_file  # noqa: E402

pd.set_option("display.width", 250)
pd.set_option("display.max_colwidth", 70)
recs, cols = [], {}
files = [(r, k) for r in RUNS for k in ("summary", "points")] + [("Ra40", "trace")]
for run, kind in files:
    meta, df = read_run_file(run, kind)
    for i, (k, v) in enumerate(meta):
        recs.append(dict(run=run, file=kind, order=i + 1, key=k, value=v))
    cols[(run, kind)] = list(df.columns)
h = pd.DataFrame(recs)
h.to_csv(OUT / "headers_by_run.csv", index=False)
# wide: key x run for summary, and whether points header is byte-identical to summary header
wide = h[h.file == "summary"].pivot(index="key", columns="run", values="value")
order = list(dict.fromkeys(h[h.run == "Ra40"][h.file == "summary"].key))
wide = wide.reindex(order)
print(wide.fillna("(absent)").to_string())
for run in RUNS:
    a = h[(h.run == run) & (h.file == "summary")][["key", "value"]].values.tolist()
    b = h[(h.run == run) & (h.file == "points")][["key", "value"]].values.tolist()
    print(f"{run}: points header identical to summary header: {a == b} ({len(a)} lines)")
a = h[(h.run == "Ra40") & (h.file == "summary")][["key", "value"]].values.tolist()
b = h[(h.run == "Ra40") & (h.file == "trace")][["key", "value"]].values.tolist()
print(f"Ra40: trace header identical to summary header: {a == b}")
allc = []
for (run, kind), c in cols.items():
    for x in c:
        if x not in allc:
            allc.append(x)
ct = pd.DataFrame({f"{r}_{k}": ["x" if x in c else "" for x in allc] for (r, k), c in cols.items()}, index=allc)
ct.to_csv(OUT / "columns_by_file.csv")
print(ct.to_string())
