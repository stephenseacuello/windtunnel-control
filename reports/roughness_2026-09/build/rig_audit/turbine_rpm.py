#!/usr/bin/env python3
"""Ra40 turbine_rpm (magnet + reed): scatter at fixed set point, trend with load, usability."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).parent))
from rigio import OUT, read_run_file, setpoint_groups, wind_from_rpm  # noqa: E402

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)
R = 0.1016   # m, sweep_core.ROTOR_RADIUS_M
meta, p = read_run_file("Ra40", "points")
_, s = read_run_file("Ra40", "summary")
_, tr = read_run_file("Ra40", "trace")

rows = []
allp = []
for sp, blk in setpoint_groups(p):
    r = pd.to_numeric(blk.turbine_rpm, errors="coerce")
    ok = r.notna()
    rr, I, V = r[ok].values, blk.amps[ok].values, blk.volts[ok].values
    rho, pval = stats.spearmanr(I, rr)
    rho_v, _ = stats.spearmanr(V, rr)
    v = wind_from_rpm(sp)
    lam = rr * 2 * np.pi / 60 * R / v
    k_light = V[0] / rr[0] * 1000 if rr[0] > 0 else np.nan     # mV per reed-rpm at the floor dwell
    rows.append(dict(sp=sp, n=len(blk), n_blank=int((~ok).sum()), median=round(float(np.median(rr)), 1),
                     min=round(float(rr.min()), 1), max=round(float(rr.max()), 1),
                     max_over_min=round(float(rr.max() / rr.min()), 1),
                     cv_pct=round(100 * rr.std(ddof=1) / rr.mean(), 1),
                     iqr_over_median_pct=round(100 * (np.percentile(rr, 75) - np.percentile(rr, 25)) / np.median(rr), 1),
                     spearman_rpm_vs_I=round(rho, 2), p=round(pval, 3), spearman_rpm_vs_V=round(rho_v, 2),
                     lambda_median=round(float(np.median(lam)), 2), lambda_min=round(float(lam.min()), 2),
                     lambda_max=round(float(lam.max()), 2),
                     v_light=float(V[0]), reed_rpm_light=float(rr[0]), mV_per_reed_rpm_light=round(k_light, 3),
                     summary_rpm_at_pmax=float(s[s.fan_rpm_cmd == sp].turbine_rpm_at_pmax.iloc[0]),
                     summary_tsr_at_pmax=float(s[s.fan_rpm_cmd == sp].tsr_at_pmax.iloc[0])))
    for a, b, c in zip(I, V, rr):
        allp.append((sp, a, b, c))
df = pd.DataFrame(rows)
df.to_csv(OUT / "ra40_turbine_rpm_by_setpoint.csv", index=False)
print(df.to_string(index=False))
print(f"\nmedian CV across set points {df.cv_pct.median():.1f}% (range {df.cv_pct.min()}..{df.cv_pct.max()}); "
      f"set points with significant negative Spearman(rpm, I) at p<0.05: {int(((df.spearman_rpm_vs_I < 0) & (df.p < 0.05)).sum())}/14; "
      f"positive: {int(((df.spearman_rpm_vs_I > 0) & (df.p < 0.05)).sum())}/14")
print(f"light-load V / reed rpm (mV/rpm) across set points: min {df.mV_per_reed_rpm_light.min()} max {df.mV_per_reed_rpm_light.max()} "
      f"ratio {df.mV_per_reed_rpm_light.max()/df.mV_per_reed_rpm_light.min():.1f}x (a generator constant should be flat)")
# adjacent-dwell jumps
jumps = []
for sp, blk in setpoint_groups(p):
    r = pd.to_numeric(blk.turbine_rpm, errors="coerce").values
    jumps.extend(np.abs(np.diff(np.log(r))))
jumps = np.array(jumps)
jumps = jumps[np.isfinite(jumps)]
print(f"adjacent-dwell |dln rpm|: median {100*np.median(jumps):.0f}%, 90th pct {100*np.percentile(jumps, 90):.0f}%")

# the pulse counter itself, from the trace: counts per second while the fan is at each set point
tr = tr.copy()
tr["dp"] = tr.rpm_pulses.diff()
tr["dus"] = (tr.rpm_last_us.diff()) % 2**32
res = []
for sp, blk in setpoint_groups(p):
    t0, t1 = blk.t_unix.iloc[0] - 1.0, blk.t_unix.iloc[-1]
    w = tr[(tr.t_unix > t0) & (tr.t_unix <= t1)]
    counts = w.rpm_pulses.iloc[-1] - w.rpm_pulses.iloc[0]
    secs = w.t_unix.iloc[-1] - w.t_unix.iloc[0]
    frac_ticks_zero = float((w.dp == 0).mean())
    res.append(dict(sp=sp, ramp_s=round(secs, 1), pulses=int(counts), pulses_per_s=round(counts / secs, 1),
                    implied_rpm_1ppr=round(60 * counts / secs, 0), frac_ticks_no_new_pulse=round(frac_ticks_zero, 2),
                    max_pulses_per_tick=int(w.dp.max())))
pt = pd.DataFrame(res)
print("\nPulse counter over each set point's ramp (trace, ~18.7 Hz ticks):")
print(pt.to_string(index=False))
pt.to_csv(OUT / "ra40_pulse_rate_by_setpoint.csv", index=False)
