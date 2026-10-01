#!/usr/bin/env python3
"""
Light-load voltage and per-set-point Thevenin fit V = Voc - I*R, per run.

The 'all' fit mirrors src/generator_model.py fit(): every tracking dwell with
V>0 and I>0 at a set point (floor dwell included, past-peak dwells included),
numpy.polyfit degree 1, rejected if slope>=0 or intercept<=0.
A second variant ('prepeak') uses only dwells up to and including the raw
argmax, to show how much the past-peak droop moves Voc and R.
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).parent))
from rigio import OUT, RUNS, read_run_file, setpoint_groups, wind_from_rpm  # noqa: E402


def lin(I, V):
    slope, icept = np.polyfit(I, V, 1)
    pred = icept + slope * I
    ss = ((V - V.mean()) ** 2).sum()
    r2 = 1 - ((V - pred) ** 2).sum() / ss if ss > 0 else float("nan")
    return float(icept), float(-slope), float(r2)


pr = pd.read_csv(OUT / "pmax_recomputed.csv")
rows = []
for run in RUNS:
    _, p = read_run_file(run, "points")
    for sp, blk in setpoint_groups(p):
        b = blk[(blk.tracking.astype(int) == 1)]
        I, V = b.amps.values.astype(float), b.volts.values.astype(float)
        m = (V > 0) & (I > 0)
        voc, R, r2 = lin(I[m], V[m])
        # pre-peak: floor dwell .. raw argmax (inclusive)
        k = int(np.argmax(b.watts.values[1:])) + 1          # argmax excluding floor dwell
        voc_p, R_p, r2_p = lin(I[:k + 1], V[:k + 1]) if k + 1 >= 4 else (np.nan,) * 3
        q = pr[(pr.blade == f"v1_{run}") & (pr.fan_rpm_cmd == sp)].iloc[0]
        rows.append(dict(
            run=run, fan_rpm_cmd=sp, wind_mps_cmd=round(wind_from_rpm(sp), 2),
            i_light_a=float(blk.amps.iloc[0]), v_light_v=float(blk.volts.iloc[0]),
            i_2nd_a=float(blk.amps.iloc[1]), v_2nd_v=float(blk.volts.iloc[1]),
            n_all=int(m.sum()), voc_all_v=round(voc, 4), r_all_ohm=round(R, 3), r2_all=round(r2, 5),
            n_prepeak=k + 1, voc_prepeak_v=round(voc_p, 4), r_prepeak_ohm=round(R_p, 3), r2_prepeak=round(r2_p, 5),
            p_thev_all_w=round(voc ** 2 / (4 * R), 5), p_raw_w=q.p_raw, p_fit_w=q.p_fit,
            i_fit_a=q.i_fit, v_at_praw_v=q.v_raw,
            thev_over_fit_pct=round(100 * (voc ** 2 / (4 * R) / q.p_fit - 1), 2),
        ))
df = pd.DataFrame(rows)
df.to_csv(OUT / "thevenin_by_run.csv", index=False)
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
print(df.to_string(index=False))

# cross-check: my 'all' fit vs the repo tool's printed values (2 dp V, 1 dp R)
print("\nworst r2 (all-points fit):", df.groupby("run").r2_all.min().to_dict())
print("Thevenin P = Voc^2/4R over p_fit, by run: ",
      {r: f"mean {g.thev_over_fit_pct.mean():+.2f}% range {g.thev_over_fit_pct.min():+.2f}..{g.thev_over_fit_pct.max():+.2f}"
       for r, g in df.groupby("run")})


def gm(x):
    lr = np.log(np.asarray(x, float))
    n = len(lr)
    t = stats.t.ppf(0.975, n - 1)
    s = lr.std(ddof=1)
    return 100 * (math.exp(lr.mean()) - 1), 100 * (math.exp(lr.mean() - t * s / math.sqrt(n)) - 1), \
        100 * (math.exp(lr.mean() + t * s / math.sqrt(n)) - 1), int((np.asarray(x) > 1).sum())


piv = {c: df.pivot(index="fan_rpm_cmd", columns="run", values=c)
       for c in ["v_light_v", "v_2nd_v", "voc_all_v", "r_all_ohm", "voc_prepeak_v", "r_prepeak_ohm",
                 "p_fit_w", "p_raw_w", "i_fit_a", "v_at_praw_v"]}
comp = []
per = pd.DataFrame({"fan_rpm_cmd": piv["p_fit_w"].index})
for num, den in [("Ra40", "Ra20"), ("Ra80", "Ra20"), ("Ra80", "Ra40")]:
    for c in piv:
        ratio = piv[c][num] / piv[c][den]
        L, lo, hi, nh = gm(ratio.values)
        comp.append(dict(pair=f"{num}/{den}", quantity=c, gm_pct=round(L, 2), ci_lo=round(lo, 2),
                         ci_hi=round(hi, 2), n_higher=nh))
        if c in ("v_light_v", "voc_all_v", "r_all_ohm", "p_fit_w"):
            per[f"{num}/{den} {c} %"] = (100 * (ratio - 1)).round(2).values
    # decomposition of dlnP_fit into 2*dlnVoc and -dlnR (all-points fit)
    dP = np.log(piv["p_fit_w"][num] / piv["p_fit_w"][den])
    dV = 2 * np.log(piv["voc_all_v"][num] / piv["voc_all_v"][den])
    dR = -np.log(piv["r_all_ohm"][num] / piv["r_all_ohm"][den])
    per[f"{num}/{den} dlnP_fit"] = (100 * dP).round(2).values
    per[f"{num}/{den} 2dlnVoc"] = (100 * dV).round(2).values
    per[f"{num}/{den} -dlnR"] = (100 * dR).round(2).values
    print(f"\n{num}/{den}: mean over 14 set points (log-%): dlnP_fit {100*dP.mean():+.2f}  "
          f"= 2dlnVoc {100*dV.mean():+.2f} + (-dlnR) {100*dR.mean():+.2f}  "
          f"[sum {100*(dV+dR).mean():+.2f}; residual {100*(dP-dV-dR).mean():+.2f}]  "
          f"share from Voc {100*dV.mean()/(dV+dR).mean():.0f}%")
    # same on the raw basis and with pre-peak fit
    dPr = np.log(piv["p_raw_w"][num] / piv["p_raw_w"][den])
    dVp = 2 * np.log(piv["voc_prepeak_v"][num] / piv["voc_prepeak_v"][den])
    dRp = -np.log(piv["r_prepeak_ohm"][num] / piv["r_prepeak_ohm"][den])
    print(f"   raw basis dlnP {100*dPr.mean():+.2f}; pre-peak fit: 2dlnVoc {100*dVp.mean():+.2f}, -dlnR {100*dRp.mean():+.2f}")
    dVl = np.log(piv["v_light_v"][num] / piv["v_light_v"][den])
    print(f"   light-load V: mean dlnV {100*dVl.mean():+.2f} (x2 = {200*dVl.mean():+.2f}); "
          f"set points with higher V_light: {(dVl > 0).sum()}/14")
    # correlation across set points between dlnP and the two parts
    print(f"   across set points: corr(dlnP, 2dlnVoc) = {np.corrcoef(dP, dV)[0,1]:+.2f}, corr(dlnP, -dlnR) = {np.corrcoef(dP, dR)[0,1]:+.2f}, corr(2dlnVoc,-dlnR) = {np.corrcoef(dV, dR)[0,1]:+.2f}")
    # low vs high half
    lo_m, hi_m = per.fan_rpm_cmd <= 1100, per.fan_rpm_cmd >= 1200
    print(f"   500-1100: 2dlnVoc {100*dV[lo_m.values].mean():+.2f}, -dlnR {100*dR[lo_m.values].mean():+.2f}; "
          f"1200-1800: 2dlnVoc {100*dV[hi_m.values].mean():+.2f}, -dlnR {100*dR[hi_m.values].mean():+.2f}")
cp = pd.DataFrame(comp)
cp.to_csv(OUT / "thevenin_cross_blade_summary.csv", index=False)
per.to_csv(OUT / "thevenin_cross_blade_by_setpoint.csv", index=False)
print()
print(cp.to_string(index=False))
print()
print(per.to_string(index=False))
