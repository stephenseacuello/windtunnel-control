#!/usr/bin/env python3
"""Fan-speed readback audit: summary vs points vs trace, per run and set point."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from rigio import OUT, RUNS, read_run_file, setpoint_groups, wind_from_rpm  # noqa: E402

N_EXP = 3.77

rows = []
for run in RUNS:
    _, s = read_run_file(run, "summary")
    _, p = read_run_file(run, "points")
    pts_by = dict(setpoint_groups(p))
    for _, r in s.iterrows():
        sp = int(r.fan_rpm_cmd)
        blk = pts_by[sp]
        d_pts = sorted(set(int(x) - sp for x in blk.fan_rpm_actual))
        act = int(r.fan_rpm_actual)
        # is the summary value on the f2 x 295 grid (0.1 Hz output-frequency steps x 29.5 rpm/Hz)?
        k = round(act / 2.95)
        on_grid = any(round(kk * 2.95) == act or abs(kk * 2.95 - act) <= 0.5 for kk in (k - 1, k, k + 1))
        hz = act / 29.5
        rows.append(dict(run=run, fan_rpm_cmd=sp, summ_actual=act, summ_minus_cmd=act - sp,
                         pts_actual_minus_cmd_distinct=";".join(f"{x:+d}" for x in d_pts),
                         pts_rows_per_actual=len(set(blk.fan_rpm_actual)),
                         wind_summary=float(r.wind_mps), wind_points=float(blk.wind_mps.iloc[0]),
                         wind_from_cmd=round(wind_from_rpm(sp), 2),
                         wind_from_summ_actual_recalc=round(wind_from_rpm(act), 3),
                         wind_summ_vs_cmd_pct=round(100 * (float(r.wind_mps) / wind_from_rpm(sp) - 1), 3),
                         power_equiv_pct_at_n377=round(100 * ((float(r.wind_mps) / wind_from_rpm(sp)) ** N_EXP - 1), 2),
                         on_f2x295_grid=on_grid,
                         implied_output_hz=round(hz, 3) if run == "Ra20" else None,
                         implied_sync_rpm_4pole=round(30 * hz, 1) if run == "Ra20" else None))
df = pd.DataFrame(rows)
df.to_csv(OUT / "fan_speed_by_setpoint.csv", index=False)
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)
print(df.to_string(index=False))

print("\n== summary actual-cmd by run ==")
for run in RUNS:
    d = df[df.run == run]
    print(f"{run}: min {d.summ_minus_cmd.min():+d} max {d.summ_minus_cmd.max():+d}, "
          f"distinct values {sorted(set(d.summ_minus_cmd))}, "
          f"wind summ vs cmd mean {d.wind_summ_vs_cmd_pct.mean():+.3f}% "
          f"(range {d.wind_summ_vs_cmd_pct.min():+.3f}..{d.wind_summ_vs_cmd_pct.max():+.3f}), "
          f"power-equivalent mean {d.power_equiv_pct_at_n377.mean():+.2f}%, "
          f"all summary actuals on f2x295 grid: {d.on_f2x295_grid.all()} ({d.on_f2x295_grid.sum()}/14)")
    # does summary wind = wind_from_rpm(actual) to 2 dp?
    mism = d[(d.wind_summary - d.wind_from_summ_actual_recalc).abs() > 0.0051]
    print(f"   summary wind != f(summary actual) at: {list(mism.fan_rpm_cmd)} "
          f"{list(zip(mism.wind_summary, mism.wind_from_summ_actual_recalc))}")
    mism2 = d[(d.wind_points - d.wind_from_cmd).abs() > 0.0051]
    print(f"   points wind != f(cmd) at: {list(mism2.fan_rpm_cmd)}")

# grid test for Ra40/Ra80 actuals too (all distinct values anywhere)
for run in RUNS:
    _, p = read_run_file(run, "points")
    vals = sorted(set(int(x) for x in p.fan_rpm_actual))
    ong = [v for v in vals if any(abs(kk * 2.95 - v) <= 0.5 for kk in range(int(v / 2.95) - 1, int(v / 2.95) + 2))]
    print(f"{run} points: {len(vals)} distinct fan_rpm_actual values, {len(ong)} lie on the f2x295 grid")

# Ra40 trace: fan speed during every dwell window
_, tr = read_run_file("Ra40", "trace")
_, p40 = read_run_file("Ra40", "points")
res = []
for sp, blk in setpoint_groups(p40):
    t0, t1 = blk.t_unix.iloc[0] - 1.0, blk.t_unix.iloc[-1]
    w = tr[(tr.t_unix >= t0) & (tr.t_unix <= t1)]
    d = w.fan_rpm_actual - sp
    res.append(dict(sp=sp, n=len(w), mean_dev=round(d.mean(), 3), sd=round(d.std(), 3),
                    min=int(d.min()), max=int(d.max()),
                    motor_a_min=w.motor_amps.min(), motor_a_max=w.motor_amps.max()))
print("\nRa40 trace, fan_rpm_actual - cmd over each set point's ramp (first dwell start .. last dwell):")
print(pd.DataFrame(res).to_string(index=False))

# consequence: level Ra40 vs Ra20 at matched wind (log-log interpolation of Ra20) using the two Ra20 wind labels
pr = pd.read_csv(OUT / "pmax_recomputed.csv")
a = pr[pr.blade == "v1_Ra20"].sort_values("fan_rpm_cmd")
b = pr[pr.blade == "v1_Ra40"].sort_values("fan_rpm_cmd")
c = pr[pr.blade == "v1_Ra80"].sort_values("fan_rpm_cmd")
print("\nConsequence for a cross-run comparison made on a wind axis (interpolate Ra20 in log-log at the other run's wind):")
for name, other in [("Ra40", b), ("Ra80", c)]:
    for label, va in [("Ra20 wind = summary (f2x29.5 based)", a.wind_mps_summary.values),
                      ("Ra20 wind = from commanded rpm", a.wind_mps_cmd.values)]:
        for col in ["p_raw", "p_fit"]:
            vb = other.wind_mps_cmd.values
            m = (vb >= va.min()) & (vb <= va.max())
            pa = np.exp(np.interp(np.log(vb[m]), np.log(va), np.log(a[col].values)))
            lr = np.log(other[col].values[m] / pa)
            print(f"  {name}/Ra20 {col}: {label:38s} n={m.sum():2d} geo-mean level {100*(np.exp(lr.mean())-1):+6.2f}%")
