#!/usr/bin/env python3
"""
recompute_pmax.py -- standalone re-implementation of the rig's P_max rules,
applied to the logged points files, compared against the logged summaries.

Rules mirrored (src/peak_finder.py, unchanged since commit 7d4dba4, 2026-08-22;
called from src/sweep_core.py measure_point):

RAW (PeakResult.power_peak_*), from find_peak's ramp loop:
  * the first dwell of each set point is the floor dwell (dwell_at(floor)) and
    is NOT eligible;
  * every later dwell that is not "bad" (note empty: not collapsed, tracking,
    above v_floor) updates the peak if watts > running peak (STRICT >, so the
    first of equal values wins).

FIT (PeakResult.refine(span=2)):
  * pts = every trace dwell with tracking and amps > 0, in trace order
    (this INCLUDES the floor dwell);
  * k = index of the first maximum of watts in pts;
  * window = pts[max(0,k-2) : min(n,k+3)]  (up to 5 points);
  * fallback to RAW if n < 5, len(window) < 3, the 3x3 normal-equation
    determinant < 1e-18, the quadratic is not concave (a2 >= 0), or the vertex
    lies outside [window[0].amps, window[-1].amps];
  * otherwise ordinary least squares W = a2*I^2 + a1*I + a0 in MEASURED CURRENT
    (amps), solved by Cramer's rule; i_fit = -a1/(2 a2), p_fit = W(i_fit).
  * With operate_frac=0.0 (sweep_core) no operating-point dwell is appended, so
    the second refine() call sees the same trace.

The logged summaries were computed from the UNROUNDED trace; the points files
carry watts/amps rounded to 4 dp, so small fit differences are expected.
"""
import math
import sys

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from rigio import OUT, RUNS, read_run_file, setpoint_groups, wind_from_rpm  # noqa: E402


def raw_peak(block):
    """find_peak's loop: skip the floor dwell and any 'bad' dwell; strict >."""
    best = None
    for j, (_, r) in enumerate(block.iterrows()):
        if j == 0:
            continue                       # floor dwell
        if str(r["note"]).strip() or int(r["tracking"]) != 1:
            continue                       # bad dwell never updates the peak
        if best is None or r["watts"] > best["watts"]:
            best = r
    return float(best["watts"]), float(best["amps"]), float(best["volts"])


def refine_mirror(block, raw_w, raw_i, span=2):
    """PeakResult.refine, line for line (Cramer's rule, pure python)."""
    pts = [(float(r["amps"]), float(r["watts"])) for _, r in block.iterrows()
           if int(r["tracking"]) == 1 and float(r["amps"]) > 0]
    if len(pts) < 2 * span + 1:
        return raw_w, raw_i, 0, "fallback:n<5"
    k = max(range(len(pts)), key=lambda j: pts[j][1])
    lo, hi = max(0, k - span), min(len(pts), k + span + 1)
    window = pts[lo:hi]
    if len(window) < 3:
        return raw_w, raw_i, 0, "fallback:window<3"
    n = len(window)
    sx = [sum(i ** m for i, _ in window) for m in range(5)]
    sy = [sum(w * i ** m for i, w in window) for m in range(3)]
    A = [[sx[4], sx[3], sx[2]], [sx[3], sx[2], sx[1]], [sx[2], sx[1], n]]
    b = [sy[2], sy[1], sy[0]]

    def det3(M):
        return (M[0][0] * (M[1][1] * M[2][2] - M[1][2] * M[2][1])
                - M[0][1] * (M[1][0] * M[2][2] - M[1][2] * M[2][0])
                + M[0][2] * (M[1][0] * M[2][1] - M[1][1] * M[2][0]))
    det = det3(A)
    if abs(det) < 1e-18:
        return raw_w, raw_i, 0, "fallback:det"

    def solve(col):
        M = [row[:] for row in A]
        for r in range(3):
            M[r][col] = b[r]
        return det3(M) / det
    a2, a1, a0 = solve(0), solve(1), solve(2)
    if a2 >= 0:
        return raw_w, raw_i, 0, "fallback:convex"
    i_hat = -a1 / (2 * a2)
    if not (window[0][0] <= i_hat <= window[-1][0]):
        return raw_w, raw_i, 0, "fallback:vertex_outside"
    return a2 * i_hat ** 2 + a1 * i_hat + a0, i_hat, n, f"fit:{n}pts,k={k}"


def refine_numpy(block, span=2):
    """Independent cross-check with numpy.polyfit (same window rule)."""
    pts = [(float(r["amps"]), float(r["watts"])) for _, r in block.iterrows()
           if int(r["tracking"]) == 1 and float(r["amps"]) > 0]
    k = int(np.argmax([w for _, w in pts]))
    win = np.array(pts[max(0, k - span): min(len(pts), k + span + 1)])
    c = np.polyfit(win[:, 0], win[:, 1], 2)
    ih = -c[1] / (2 * c[0])
    return float(np.polyval(c, ih)), float(ih)


def stop_rule_check(block, frac=0.80, confirm=2):
    """Replay the power-rolloff stop; return (index it would stop at, pct text)."""
    peak, roll = 0.0, 0
    for j, (_, r) in enumerate(block.iterrows()):
        if j == 0:
            continue
        w = float(r["watts"])
        if w > peak:
            peak = w
        if peak > 0 and w <= frac * peak:
            roll += 1
            if roll >= confirm:
                return j, round(w / peak * 100), w, peak, float(r["demand_a"])
        else:
            roll = 0
    return None, None, None, None, None


def geo_level(ratios):
    lr = np.log(np.asarray(ratios, float))
    n = len(lr)
    m, s = lr.mean(), lr.std(ddof=1)
    t = stats.t.ppf(0.975, n - 1)
    return (100 * (math.exp(m) - 1), 100 * (math.exp(m - t * s / math.sqrt(n)) - 1),
            100 * (math.exp(m + t * s / math.sqrt(n)) - 1), n,
            int((np.asarray(ratios) > 1).sum()), 100 * s)


def main():
    rows, checks = [], []
    for run in RUNS:
        _, summ = read_run_file(run, "summary")
        _, pts = read_run_file(run, "points")
        s_by = {int(r["fan_rpm_cmd"]): r for _, r in summ.iterrows()}
        for sp, blk in setpoint_groups(pts):
            s = s_by[sp]
            rw, ri, rv = raw_peak(blk)
            fw, fi, fn, why = refine_mirror(blk, rw, ri)
            nw, ni = refine_numpy(blk)
            j, pct, w_stop, pk, dem = stop_rule_check(blk)
            logged_raw = float(s["p_max_raw_w"] if "p_max_raw_w" in s else s["p_max_w"])
            logged_iraw = float(s["i_at_pmax_raw_a"] if "i_at_pmax_raw_a" in s else s["i_at_pmax_a"])
            logged_fit = float(s["p_max_fit_w"]) if "p_max_fit_w" in s else float("nan")
            logged_ifit = float(s["i_at_pmax_fit_a"]) if "i_at_pmax_fit_a" in s else float("nan")
            rows.append(dict(
                blade=f"v1_{run}", fan_rpm_cmd=sp,
                fan_rpm_actual_summary=int(s["fan_rpm_actual"]),
                wind_mps_summary=float(s["wind_mps"]),
                p_raw=round(rw, 4), i_raw=round(ri, 4), v_raw=round(rv, 4),
                p_fit=round(fw, 5), i_fit=round(fi, 5), n_steps=len(blk),
                logged_p_raw=logged_raw, logged_p_fit=logged_fit,
                # extras (after the requested columns)
                wind_mps_cmd=round(wind_from_rpm(sp), 4),
                logged_i_raw=logged_iraw, logged_i_fit=logged_ifit,
                logged_v_raw=float(s["v_at_pmax_v"]),
                logged_steps=int(s["steps"]), logged_i_last=float(s["i_last_a"]),
                i_last_points=float(blk["amps"].iloc[-1]),
                fit_status=why, p_fit_numpy=round(nw, 5), i_fit_numpy=round(ni, 5),
            ))
            # stop-rule replay vs logged stopped_by
            checks.append(dict(run=run, sp=sp, stop_index=j, last_index=len(blk) - 1,
                               stop_pct=pct, stop_w=w_stop, stop_peak=pk, stop_demand=dem,
                               logged=s["stopped_by"]))
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "pmax_recomputed.csv", index=False)
    ck = pd.DataFrame(checks)
    ck["stop_matches_last_row"] = ck.stop_index == ck.last_index
    ck["pct_in_text"] = [f"power fell to {int(p)}% of its peak ({w:.4f} W vs {k:.4f} W) at {d:.4f} A" == t
                         for p, w, k, d, t in zip(ck.stop_pct, ck.stop_w, ck.stop_peak, ck.stop_demand, ck.logged)]
    ck.to_csv(OUT / "stop_rule_replay.csv", index=False)

    print("== discrepancy vs logged summary ==")
    for run in RUNS:
        d = df[df.blade == f"v1_{run}"]
        out = {}
        for mine, logged in [("p_raw", "logged_p_raw"), ("i_raw", "logged_i_raw"),
                             ("v_raw", "logged_v_raw"), ("p_fit", "logged_p_fit"),
                             ("i_fit", "logged_i_fit"), ("n_steps", "logged_steps"),
                             ("i_last_points", "logged_i_last")]:
            if d[logged].isna().all():
                out[mine] = "n/a (not logged)"
                continue
            a = (d[mine] - d[logged]).abs()
            r = (a / d[logged].abs()).max() * 100
            out[mine] = f"max|d|={a.max():.6f} (at {int(d.loc[a.idxmax(), 'fan_rpm_cmd'])}), max rel={r:.4f}%"
        print(run)
        for k, v in out.items():
            print(f"   {k:14s} {v}")
        print(f"   fit status: {d.fit_status.str.split(':').str[0].value_counts().to_dict()}")
        print(f"   mirror vs numpy max|dP| = {(d.p_fit - d.p_fit_numpy).abs().max():.2e}")
        c = ck[ck.run == run]
        print(f"   stop-rule replay: stops on last row {c.stop_matches_last_row.sum()}/14, "
              f"stopped_by text reproduced {c.pct_in_text.sum()}/14")

    # ladder identity across runs
    lad = {}
    for run in RUNS:
        _, pts = read_run_file(run, "points")
        lad[run] = {sp: list(b["demand_a"]) for sp, b in setpoint_groups(pts)}
    bad = 0
    for sp in lad["Ra20"]:
        for a in RUNS[1:]:
            L = min(len(lad["Ra20"][sp]), len(lad[a][sp]))
            if lad["Ra20"][sp][:L] != lad[a][sp][:L]:
                bad += 1
    print(f"\n== demand ladders identical (common prefix) across runs: {'yes' if bad == 0 else f'NO ({bad})'}")

    print("\n== pairwise LEVEL: geometric-mean ratio over 14 set points matched on fan_rpm_cmd, t(13) 95% CI ==")
    piv = {c: df.pivot(index="fan_rpm_cmd", columns="blade", values=c)
           for c in ["p_raw", "p_fit", "logged_p_fit"]}
    lev = []
    for num, den in [("Ra40", "Ra20"), ("Ra80", "Ra20"), ("Ra80", "Ra40")]:
        for basis, col in [("raw (recomputed = logged)", "p_raw"),
                           ("fit (recomputed from points, all runs)", "p_fit")]:
            ratios = piv[col][f"v1_{num}"] / piv[col][f"v1_{den}"]
            L, lo, hi, n, nhi, sd = geo_level(ratios)
            lev.append(dict(num=num, den=den, basis=basis, level_pct=round(L, 3),
                            ci_lo=round(lo, 3), ci_hi=round(hi, 3), n=n,
                            n_num_higher=nhi, sd_log_pct=round(sd, 3)))
        # mixed: logged fit for Ra40/Ra80, recomputed fit for Ra20
        a = piv["logged_p_fit"][f"v1_{num}"] if num != "Ra20" else None
        b = (piv["p_fit"][f"v1_{den}"] if den == "Ra20" else piv["logged_p_fit"][f"v1_{den}"])
        ratios = a / b
        L, lo, hi, n, nhi, sd = geo_level(ratios)
        lev.append(dict(num=num, den=den, basis="fit (logged Ra40/Ra80; Ra20 recomputed)",
                        level_pct=round(L, 3), ci_lo=round(lo, 3), ci_hi=round(hi, 3), n=n,
                        n_num_higher=nhi, sd_log_pct=round(sd, 3)))
    lv = pd.DataFrame(lev)
    lv.to_csv(OUT / "pairwise_level_raw_vs_fit.csv", index=False)
    print(lv.to_string(index=False))

    # per set point ratios table
    per = pd.DataFrame({"fan_rpm_cmd": piv["p_raw"].index})
    for num, den in [("Ra40", "Ra20"), ("Ra80", "Ra20"), ("Ra80", "Ra40")]:
        for col in ["p_raw", "p_fit"]:
            per[f"{num}/{den}_{col}_pct"] = (100 * (piv[col][f"v1_{num}"] / piv[col][f"v1_{den}"] - 1)).round(2).values
    per.to_csv(OUT / "ratios_by_setpoint.csv", index=False)
    print(per.to_string(index=False))

    # fit/raw ratio per run: how much the fit pulls below the argmax
    print("\n== p_fit / p_raw per run (recomputed) ==")
    for run in RUNS:
        d = df[df.blade == f"v1_{run}"]
        r = d.p_fit / d.p_raw
        print(f"  {run}: mean {100*(r.mean()-1):+.3f}%  min {100*(r.min()-1):+.3f}%  max {100*(r.max()-1):+.3f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
