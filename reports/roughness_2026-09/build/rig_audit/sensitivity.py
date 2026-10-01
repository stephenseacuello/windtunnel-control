#!/usr/bin/env python3
"""Sensitivity checks for the fit-basis level, the wind label, and the Thevenin reading."""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).parent))
from rigio import OUT, read_run_file, setpoint_groups  # noqa: E402
from recompute_pmax import refine_mirror, raw_peak, geo_level  # noqa: E402

pr = pd.read_csv(OUT / "pmax_recomputed.csv")
piv = pr.pivot(index="fan_rpm_cmd", columns="blade", values="p_fit")
pivr = pr.pivot(index="fan_rpm_cmd", columns="blade", values="p_raw")
fb = pr[pr.fit_status.str.startswith("fallback")][["blade", "fan_rpm_cmd", "fit_status"]]
print("fit fallbacks:\n", fb.to_string(index=False))
keep = [sp for sp in piv.index if sp not in (600, 700)]
print("\n(a) fit-basis level excluding set points 600 and 700 (where a fit fell back), n=12:")
for num, den in [("v1_Ra40", "v1_Ra20"), ("v1_Ra80", "v1_Ra20"), ("v1_Ra80", "v1_Ra40")]:
    L, lo, hi, n, nh, sd = geo_level((piv[num] / piv[den]).loc[keep].values)
    Lr, lor, hir, _, nhr, _ = geo_level((pivr[num] / pivr[den]).loc[keep].values)
    print(f"   {num[3:]}/{den[3:]}: fit {L:+.2f}% [{lo:+.2f}, {hi:+.2f}] ({nh}/{n} higher); raw {Lr:+.2f}% [{lor:+.2f}, {hir:+.2f}] ({nhr}/{n})")

print("\n(b) Monte Carlo: Ra20 fit uncertainty from 4-dp rounding of watts (uniform +/-0.5e-4 W), 2000 draws:")
_, p = read_run_file("Ra20", "points")
rng = np.random.default_rng(1)
out = []
for sp, blk in setpoint_groups(p):
    rw, ri, _ = raw_peak(blk)
    base = refine_mirror(blk, rw, ri)[0]
    vals = []
    for _ in range(2000):
        b = blk.copy()
        b["watts"] = b["watts"] + rng.uniform(-5e-5, 5e-5, len(b))
        rw2, ri2, _ = raw_peak(b)
        vals.append(refine_mirror(b, rw2, ri2)[0])
    vals = np.array(vals)
    out.append((sp, base, 100 * vals.std() / base, 100 * (np.percentile(vals, 97.5) - np.percentile(vals, 2.5)) / 2 / base))
for sp, b, sdp, hw in out:
    print(f"   {sp}: p_fit {b:.5f} W, sd {sdp:.3f}%, 95% half-width {hw:.3f}%")

print("\n(c) wind label arithmetic at n = 3.77:")
for d in (0.714, 1.026, 1.203, 1.2):
    print(f"   wind {d:.3f}% low -> power at matched wind {100*((1/(1-d/100))**3.77-1):+.2f}% (inverse {100*((1-d/100)**3.77-1):+.2f}%)")

print("\n(b2) matched-wind comparison restricted to the same 13 set points (drop 1800):")
a = pr[pr.blade == "v1_Ra20"].sort_values("fan_rpm_cmd")
for name in ("v1_Ra40", "v1_Ra80"):
    o = pr[pr.blade == name].sort_values("fan_rpm_cmd")
    for label, va in [("summary", a.wind_mps_summary.values), ("cmd", a.wind_mps_cmd.values)]:
        vb = o.wind_mps_cmd.values[:-1]
        pa = np.exp(np.interp(np.log(vb), np.log(va), np.log(a.p_raw.values)))
        lr = np.log(o.p_raw.values[:-1] / pa)
        print(f"   {name[3:]}/Ra20 raw, Ra20 wind={label:7s}: {100*(math.exp(lr.mean())-1):+.2f}%")

print("\n(d) would a pure wind-speed offset explain the Thevenin pattern?")
th = pd.read_csv(OUT / "thevenin_by_run.csv")
# within-run exponents (all-points fit), pooled
for run in ("Ra20", "Ra40", "Ra80"):
    d = th[th.run == run]
    bv = np.polyfit(np.log(d.wind_mps_cmd), np.log(d.voc_all_v), 1)[0]
    br = np.polyfit(np.log(d.wind_mps_cmd), np.log(d.r_all_ohm), 1)[0]
    bl = np.polyfit(np.log(d.wind_mps_cmd), np.log(d.v_light_v), 1)[0]
    print(f"   {run}: Voc ~ v^{bv:.3f}, R ~ v^{br:.3f}, V_light ~ v^{bl:.3f}")
pv = {c: th.pivot(index="fan_rpm_cmd", columns="run", values=c) for c in ("voc_all_v", "r_all_ohm", "v_light_v")}
for num, den in (("Ra40", "Ra20"), ("Ra80", "Ra20"), ("Ra80", "Ra40")):
    dv = np.log(pv["voc_all_v"][num] / pv["voc_all_v"][den])
    dr = np.log(pv["r_all_ohm"][num] / pv["r_all_ohm"][den])
    n = len(dr)
    t = stats.t.ppf(0.975, n - 1)
    delta = dv.mean() / 1.497     # Ra20 Voc exponent from generator_model
    pred_r = -0.791 * delta
    print(f"   {num}/{den}: dlnVoc {100*dv.mean():+.2f}% -> implied wind offset {100*delta:+.2f}% -> "
          f"predicted dlnR {100*pred_r:+.2f}%; observed dlnR {100*dr.mean():+.2f}% "
          f"[{100*(dr.mean()-t*dr.std(ddof=1)/math.sqrt(n)):+.2f}, {100*(dr.mean()+t*dr.std(ddof=1)/math.sqrt(n)):+.2f}]")
