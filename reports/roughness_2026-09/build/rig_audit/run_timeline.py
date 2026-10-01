#!/usr/bin/env python3
"""Per-run timeline, dwell counts, flags, motor current, and a test-order check."""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from rigio import OUT, RUNS, TEST_ORDER, read_run_file, setpoint_groups  # noqa: E402

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)


def ts(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


summ_rows, sp_rows = [], []
for run in RUNS:
    meta, s = read_run_file(run, "summary")
    _, p = read_run_file(run, "points")
    md = dict(meta)
    info = dict(run=run, n_setpoints=len(s), n_dwells_points=len(p), sum_steps=int(s.steps.sum()),
                clean_values=sorted(set(s.clean)), limited_by_values=sorted(set(s.limited_by)),
                tracking0_rows=int((p.tracking.astype(int) == 0).sum()),
                nonempty_note_rows=int((p.note.astype(str).str.strip() != "").sum()),
                motor_amps_min=p.motor_amps.min(), motor_amps_max=p.motor_amps.max(),
                header_clock=md.get("clock", "(none)"))
    if "t_unix" in p:
        t = p.t_unix.values
        info.update(first_dwell=ts(t[0]), last_dwell=ts(t[-1]), span_s=round(t[-1] - t[0], 1),
                    header_clock_minus_last_dwell_s=round(float(md["clock_unix"]) - t[-1], 1)
                    if "clock_unix" in md else None)
        dts = []
        prev_end = None
        for sp, blk in setpoint_groups(p):
            tt = blk.t_unix.values
            d = np.diff(tt)
            dts.extend(d)
            sp_rows.append(dict(run=run, sp=sp, n=len(blk), t_first=ts(tt[0]), t_last=ts(tt[-1]),
                                ramp_s=round(tt[-1] - tt[0], 2), dwell_dt_median=round(float(np.median(d)), 3),
                                dwell_dt_max=round(float(d.max()), 3),
                                gap_from_prev_sp_s=None if prev_end is None else round(tt[0] - prev_end, 2)))
            prev_end = tt[-1]
        dts = np.array(dts)
        info.update(dwell_dt_median=round(float(np.median(dts)), 3), dwell_dt_min=round(float(dts.min()), 3),
                    dwell_dt_max=round(float(dts.max()), 3))
    else:
        info.update(first_dwell="not recorded (no t_unix column)", last_dwell="not recorded", span_s=None)
    summ_rows.append(info)

info = pd.DataFrame(summ_rows)
print(info.T.to_string())
info.to_csv(OUT / "run_timeline_summary.csv", index=False)
spd = pd.DataFrame(sp_rows)
spd.to_csv(OUT / "run_timeline_by_setpoint.csv", index=False)
print()
print(spd.to_string(index=False))

# Ra40 trace span
_, tr = read_run_file("Ra40", "trace")
print(f"\nRa40 trace: {ts(tr.t_unix.iloc[0])} .. {ts(tr.t_unix.iloc[-1])}, {len(tr)} ticks, "
      f"{tr.t_rel_s.iloc[-1]:.1f} s")

# motor current per set point across runs (points: Ra20/Ra80 single end-of-ramp value per set point; Ra40 per dwell)
mc = {}
for run in RUNS:
    _, p = read_run_file(run, "points")
    mc[run] = p.groupby("fan_rpm").motor_amps.median()
mcd = pd.DataFrame(mc)
# slope of motor current vs rpm within each run (A per rpm), local, to translate a speed deficit into current
slope = mcd["Ra80"].diff() / 100.0
fs = pd.read_csv(OUT / "fan_speed_by_setpoint.csv")
ded = fs[fs.run == "Ra20"].set_index("fan_rpm_cmd").summ_minus_cmd
mcd["Ra20_minus_Ra80_A"] = (mcd.Ra20 - mcd.Ra80).round(2)
mcd["Ra20_minus_Ra40_A"] = (mcd.Ra20 - mcd.Ra40).round(2)
mcd["local_dI_drpm_Ra80"] = slope.round(4)
mcd["expected_Ra20_shift_if_slower_A"] = (slope * ded).round(2)
print("\nMotor current (median per set point) and what a real Ra20 speed deficit would imply:")
print(mcd.to_string())
mcd.to_csv(OUT / "motor_current_by_setpoint.csv")

# ordering vs test order
pr = pd.read_csv(OUT / "pmax_recomputed.csv")
for col in ["p_raw", "p_fit"]:
    piv = pr.pivot(index="fan_rpm_cmd", columns="blade", values=col)
    ra_order = (piv["v1_Ra20"] < piv["v1_Ra40"]) & (piv["v1_Ra40"] < piv["v1_Ra80"])
    date_order = (piv["v1_Ra20"] < piv["v1_Ra80"]) & (piv["v1_Ra80"] < piv["v1_Ra40"])
    ranks = piv[["v1_Ra20", "v1_Ra80", "v1_Ra40"]].rank(axis=1)
    print(f"\n{col}: set points ordered Ra20<Ra40<Ra80 (Ra order): {int(ra_order.sum())}/14 "
          f"{list(piv.index[~ra_order])} excluded; ordered Ra20<Ra80<Ra40 (test-date order): {int(date_order.sum())}/14 "
          f"{list(piv.index[date_order])}")
    print("   mean rank (1=lowest) by run in test order Ra20, Ra80, Ra40:", ranks.mean().round(2).to_dict())
