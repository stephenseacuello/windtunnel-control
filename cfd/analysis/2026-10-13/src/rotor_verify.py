#!/usr/bin/env python3
"""Independent check of the rotor-stage findings (written by the verifier; shares no code with
rotor_analysis.py). Prints every recomputed number and writes ../out/rotor_verify.json.

    nice -n 10 python3 cfd/analysis/2026-10-13/src/rotor_verify.py

Inputs (read only): ../data/rotor_static.csv, ../data/rotor_cp.csv, and the rig's
reports/roughness_2026-09/build/tacho/derived/rotor_speed_by_dwell.csv (Plain rotor).

Uncertainty used here (same definition as the analyst's, re-derived): the revolution-to-revolution
s.d. of the C_Q mean is pooled per hypothesis and wind speed over the production cases from the
last-two-revolution difference d (var(d) = 2 s^2 if the revolution means are independent), and a
mean over n revolutions has u = s / sqrt(n). Static cases: the batch-means SEM in the table.
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
REPO = BASE.parents[2]
ST = pd.read_csv(BASE / "data/rotor_static.csv")
RC = pd.read_csv(BASE / "data/rotor_cp.csv")
DW = pd.read_csv(REPO / "reports/roughness_2026-09/build/tacho/derived/rotor_speed_by_dwell.csv")
OUT = {}


def put(key, val):
    OUT[key] = val
    print(f"{key}: {val}")


# ------------------------------------------------------------------ static
for hyp in ("A", "B"):
    g = ST[ST.hypothesis == hyp].sort_values("theta_deg")
    th = g.theta_deg.to_numpy()
    q = g.CQ_mean.to_numpy()
    se = g.CQ_sem.to_numpy()
    sd = g.CQ_std.to_numpy()
    assert np.allclose(th, np.arange(0, 106, 15)), th
    m = q.mean()
    se_m = math.sqrt((se ** 2).sum()) / len(q)
    s0, s1 = q[th % 30 == 0].mean(), q[th % 30 == 15].mean()
    put(f"static_{hyp}", dict(
        sense=sorted(set(g.sense)), model=sorted(set(g.model)), level=sorted(set(g.level)),
        U=sorted(set(g.U_ms)), maxCo=sorted(set(g.maxCo)), nProcs=g.nProcs.tolist(), ran_on=g.ran_on.tolist(),
        CQ=np.round(q, 4).tolist(), two_sem=np.round(2 * se, 4).tolist(),
        mean=round(m, 5), sem_mean=round(se_m, 5), two_sem_mean=round(2 * se_m, 5), mean_over_sem=round(m / se_m, 2),
        sub_0_30_60_90=round(s0, 5), sub_15_45_75_105=round(s1, 5), half_spread=round(abs(s0 - s1) / 2, 5),
        n_pos=int((q > 0).sum()), n_neg=int((q < 0).sum()),
        resolved_2sem=[bool(abs(a) > 2 * b) for a, b in zip(q, se)],
        sd_range=[round(sd.min(), 3), round(sd.max(), 3)], sd_mean=round(sd.mean(), 4),
        t_end=g.t_end_conv.tolist(), window_complete=bool(g.avg_window_complete.all()),
        viscous_abs_max=round(float(np.abs(g.CQ_mean - g.CQ_pressure_mean).max()), 5)))
sA, sB = OUT["static_A"], OUT["static_B"]
put("static_B_over_A_abs_mean", round(abs(sB["mean"]) / abs(sA["mean"]), 3))
put("static_B_subset_over_A_abs", [round(abs(sB["sub_0_30_60_90"]) / abs(sA["mean"]), 3),
                                   round(abs(sB["sub_15_45_75_105"]) / abs(sA["mean"]), 3)])
put("static_sd_ratio_B_over_A_mean", round(sB["sd_mean"] / sA["sd_mean"], 2))

# ------------------------------------------------------------------ rotating
prod = ((RC.freestream_decay == "control") & (RC.maxCo == 4) & (RC.nOuter == 2) & (RC.Tu_rotor_pct == 1)
        & (np.isclose(RC.lt_m, 1e-3)) & (RC.model == "kOmegaSST") & (RC.level == "medium"))
RC["prod"] = prod
put("n_rot_cases", int(len(RC)))
put("n_rot_production", int(prod.sum()))
put("nonproduction_cases", RC.loc[~prod, "name"].tolist())
put("CP_equals_lam_CQ_maxabs", float(np.abs(RC.CP_mean - RC.lam * RC.CQ_mean).max()))
drag_rule = {"A": "CW", "B": "CCW"}

sig = {}
for (h, U), g in RC[prod].groupby(["hypothesis", "U_ms"]):
    d = g.CQ_drift_last_two_rev.to_numpy()
    s = math.sqrt((d ** 2).mean() / 2)
    i = np.argmax(np.abs(d))
    d_wo = np.delete(d, i)
    sig[(h, U)] = s
    put(f"sigma_rev_{h}_{U:g}", dict(sigma=round(s, 5), n=len(d), two_u_n3=round(2 * s / math.sqrt(3), 5),
                                     two_u_n2=round(2 * s / math.sqrt(2), 5),
                                     max_drift_case=g.name.iloc[i], max_drift=round(float(d[i]), 4),
                                     sigma_without_max=round(math.sqrt((d_wo ** 2).mean() / 2), 5)))
RC["u"] = [sig[(h, U)] / math.sqrt(n) if (h, U) in sig else np.nan
           for h, U, n in zip(RC.hypothesis, RC.U_ms, RC.n_avg_rev)]


def curve(h, U, sense, co=4):
    g = RC[(RC.hypothesis == h) & np.isclose(RC.U_ms, U) & (RC.sense == sense) & (RC.maxCo == co)]
    return g.sort_values("lam")


def zero_cross(lam, q, u):
    res = []
    for i in range(len(lam) - 1):
        if q[i] * q[i + 1] < 0:
            dl = lam[i + 1] - lam[i]
            l0 = lam[i] + dl * q[i] / (q[i] - q[i + 1])
            # first-order propagation, independent errors
            dq1 = -dl * q[i + 1] / (q[i] - q[i + 1]) ** 2
            dq2 = dl * q[i] / (q[i] - q[i + 1]) ** 2
            res.append((round(l0, 4), round(math.hypot(dq1 * u[i], dq2 * u[i + 1]), 4)))
    return res


curves = {}
for h, U in (("A", 10.2), ("A", 23.0), ("A", 38.0), ("B", 23.0)):
    for sense in ("CW", "CCW"):
        g = curve(h, U, sense)
        lam, q, u, cp = (g[c].to_numpy() for c in ("lam", "CQ_mean", "u", "CP_mean"))
        kind = "drag rule" if sense == drag_rule[h] else "reversed"
        b, a = np.polyfit(lam, q, 1)
        rms = float(np.sqrt(np.mean((q - a - b * lam) ** 2)))
        c = dict(kind=kind, lam=lam.tolist(), CQ=np.round(q, 4).tolist(), two_u=np.round(2 * u, 4).tolist(),
                 z=[round(x, 2) for x in q / u], CP=np.round(cp, 5).tolist(), two_uCP=np.round(2 * lam * u, 5).tolist(),
                 zero=zero_cross(lam, q, u), lin=dict(a=round(a, 4), b=round(b, 3), rms=round(rms, 4),
                                                      lam0=round(-a / b, 4) if a * b < 0 else None),
                 cp_max_lam=float(lam[np.argmax(cp)]), cp_max=round(float(cp.max()), 5),
                 n_rev=g.n_rev_done.tolist(), n_avg=g.n_avg_rev.tolist(),
                 viscous=np.round(g.CQ_mean - g.CQ_pressure_mean, 5).tolist())
        curves[(h, U, sense)] = (lam, q, u, cp)
        put(f"curve_{h}_{U:g}_{sense}", c)

# static continuation and static-anchored peak (23 m/s)
for h in ("A", "B"):
    for sense in ("CW", "CCW"):
        lam, q, u, cp = curves[(h, 23.0, sense)]
        q0 = OUT[f"static_{h}"]["mean"] * (1 if sense == drag_rule[h] else -1)
        put(f"lam005_minus_static_{h}_{sense}", round(q[0] - q0, 4))
        if q0 > 0:
            # quadratic C_Q through (0, q0), (lam1, q1), (lam2, q2); C_P = lam C_Q; maximise
            M = np.array([[lam[0], lam[0] ** 2], [lam[1], lam[1] ** 2]])
            c1, c2 = np.linalg.solve(M, [q[0] - q0, q[1] - q0])
            roots = np.roots([3 * c2, 2 * c1, q0])
            roots = [r.real for r in roots if abs(r.imag) < 1e-12 and 0 < r.real <= lam[1]]
            put(f"static_anchored_peak_{h}_{sense}",
                [(round(r, 4), round(r * (q0 + c1 * r + c2 * r * r), 5)) for r in roots] or "edge (no interior root)")

# CP differences that decide where the peak lies
def diff_cp(h, U, sense, l1, l2):
    lam, q, u, cp = curves[(h, U, sense)]
    i, j = int(np.argmin(abs(lam - l1))), int(np.argmin(abs(lam - l2)))
    dd = cp[i] - cp[j]
    ud = math.hypot(lam[i] * u[i], lam[j] * u[j])
    return dict(d=round(dd, 5), u=round(ud, 5), z=round(dd / ud, 2))


put("dCP_A23CCW_005_minus_010", diff_cp("A", 23.0, "CCW", 0.05, 0.10))
put("dCP_A10CCW_008_minus_005", diff_cp("A", 10.2, "CCW", 0.08, 0.05))
put("dCP_A10CCW_008_minus_011", diff_cp("A", 10.2, "CCW", 0.08, 0.11))
put("dCP_A38CCW_010_minus_015", diff_cp("A", 38.0, "CCW", 0.10, 0.15))

# cross-speed comparisons at common lambda (A reversed); different meshes per speed (h0 scaled, capped at 10.2)
for l, pairs in ((0.15, ((10.2, 23.0), (23.0, 38.0), (10.2, 38.0))), (0.05, ((10.2, 23.0),)), (0.10, ((23.0, 38.0),))):
    for U1, U2 in pairs:
        for sense in ("CCW", "CW"):
            r = []
            for U in (U1, U2):
                lam, q, u, cp = curves[("A", U, sense)]
                i = int(np.argmin(abs(lam - l)))
                assert abs(lam[i] - l) < 1e-9
                r.append((q[i], u[i]))
            dd = r[0][0] - r[1][0]
            ud = math.hypot(r[0][1], r[1][1])
            put(f"dCQ_A_{sense}_lam{l}_U{U1:g}_minus_U{U2:g}", dict(d=round(dd, 4), two_u=round(2 * ud, 4), z=round(dd / ud, 2)))
z = {U: zero_cross(*curves[("A", U, "CCW")][:2], curves[("A", U, "CCW")][2])[-1] for U in (10.2, 23.0, 38.0)}
for U1, U2 in ((10.2, 23.0), (23.0, 38.0), (10.2, 38.0)):
    dd = z[U1][0] - z[U2][0]
    ud = math.hypot(z[U1][1], z[U2][1])
    put(f"dlam0_A_CCW_U{U1:g}_minus_U{U2:g}", dict(d=round(dd, 4), two_u=round(2 * ud, 4), z=round(dd / ud, 2)))

# sense decomposition: D = (CCW - CW)/2 (even part in signed Omega), E = (CCW + CW)/2 (odd part)
for h, U in (("A", 10.2), ("A", 23.0), ("A", 38.0), ("B", 23.0)):
    l1, q1, u1, _ = curves[(h, U, "CCW")]
    l2, q2, u2, _ = curves[(h, U, "CW")]
    assert np.allclose(l1, l2)
    D, E, uD = (q1 - q2) / 2, (q1 + q2) / 2, np.hypot(u1, u2) / 2
    k = -np.sum(E * l1) / np.sum(l1 ** 2)
    kk = np.polyfit(l1, E, 1)
    put(f"decomp_{h}_{U:g}", dict(lam=l1.tolist(), D=np.round(D, 4).tolist(), E=np.round(E, 4).tolist(),
                                  two_uD=np.round(2 * uD, 4).tolist(), k_origin=round(k, 3),
                                  E_rms_origin=round(float(np.sqrt(np.mean((E + k * l1) ** 2))), 4),
                                  E_free_fit=dict(slope=round(kk[0], 3), intercept=round(kk[1], 4)),
                                  D_range=[round(D.min(), 4), round(D.max(), 4)]))
    if U == 23.0:
        D0 = OUT[f"static_{h}"]["mean"] * (1 if drag_rule[h] == "CCW" else -1)
        put(f"decomp_{h}_23_D_minus_static", np.round(D - D0, 4).tolist())

# time-step pairs (maxCo 2 vs 4), same everything else
for sense in ("CW", "CCW"):
    a = RC[(RC.hypothesis == "A") & (RC.U_ms == 23) & (RC.sense == sense) & np.isclose(RC.lam, 0.15)]
    p, c2 = a[a.maxCo == 4].iloc[0], a[a.maxCo == 2].iloc[0]
    same = all(p[k] == c2[k] for k in ("model", "level", "n_cells", "h0_m", "Tu_rotor_pct", "lt_m", "nOuter",
                                        "n_rev_done", "n_avg_rev", "nProcs"))
    uc2 = sig[("A", 23.0)] / math.sqrt(c2.n_avg_rev)
    dd = c2.CQ_mean - p.CQ_mean
    put(f"tstep_A23_{sense}", dict(Co4=round(p.CQ_mean, 5), Co2=round(c2.CQ_mean, 5), d=round(dd, 5),
                                   z=round(dd / math.hypot(p.u, uc2), 2), otherwise_same=bool(same),
                                   dt=(p.dt_mean_s, c2.dt_mean_s), drift=(round(p.CQ_drift_last_two_rev, 4),
                                                                         round(c2.CQ_drift_last_two_rev, 4))))
# A reversed 23 m/s zero crossing with the maxCo 2 value at 0.15
lam, q, u, _ = curves[("A", 23.0, "CCW")]
q2 = q.copy()
q2[np.isclose(lam, 0.15)] = OUT["tstep_A23_CCW"]["Co2"]
put("zero_A23CCW_with_Co2_value", zero_cross(lam, q2, u))

# quality
put("quality", dict(
    all_windows_complete=bool(RC.avg_window_complete.all()), ran_on=sorted(set(RC.ran_on)),
    nProcs=sorted(set(RC.nProcs)), yplus_mean=[round(RC.yplus_mean.min(), 1), round(RC.yplus_mean.max(), 1)],
    yplus_max=[round(RC.yplus_max.min(), 1), round(RC.yplus_max.max(), 1)],
    ami=[RC.ami_weight_min.min(), RC.ami_weight_max.max()], omega_bounded=int(RC.omega_bounded_steps.sum()),
    Tu_probe=[RC.Tu_upstream_probe_pct.min(), RC.Tu_upstream_probe_pct.max()],
    drift_abs_median=round(float(RC.CQ_drift_last_two_rev.abs().median()), 4),
    viscous_abs_max=round(float((RC.CQ_mean - RC.CQ_pressure_mean).abs().max()), 5),
    sd_A=[round(RC[RC.hypothesis == "A"].CQ_std.min(), 3), round(RC[RC.hypothesis == "A"].CQ_std.max(), 3)],
    sd_B=[round(RC[RC.hypothesis == "B"].CQ_std.min(), 3), round(RC[RC.hypothesis == "B"].CQ_std.max(), 3)],
    h0_by_U={f"{U:g}": float(g.h0_m.iloc[0]) for U, g in RC.groupby("U_ms")},
    yplus_mean_by_U={f"{U:g}": [round(g.yplus_mean.min(), 1), round(g.yplus_mean.max(), 1)] for U, g in RC.groupby("U_ms")}))

# ------------------------------------------------------------------ rig (Plain, both runs)
RHO, AREA = 1.204, 2 * 0.1016 * 0.2451
dw = DW[(DW.rotor == "Plain") & (DW.speed_ok == True)].copy()  # noqa: E712
dw["cp_gi"] = dw.p_gen_in_w / (0.5 * RHO * AREA * dw.wind_mps ** 3)
dw["cq_gen"] = dw.torque_gen_nm / (0.5 * RHO * AREA * 0.1016 * dw.wind_mps ** 2)
put("rig_cp_el_check_maxrel", float(np.abs(dw.watts / (0.5 * RHO * AREA * dw.wind_mps ** 3) / dw.cp_el - 1).max()))
rig = {}
for (U, run), g in dw.groupby([dw.wind_mps.round(2), "run"]):
    g = g.sort_values("demand_a")
    lamv = g.tip_speed_ratio.to_numpy()
    # stall: lambda drops by more than 20 % from one load step to the next (then stop)
    keep = len(lamv)
    for i in range(1, len(lamv)):
        if lamv[i] < 0.8 * lamv[i - 1]:
            keep = i
            break
    g = g.iloc[:keep].sort_values("tip_speed_ratio")
    lam, cpe, cpg = g.tip_speed_ratio.to_numpy(), g.cp_el.to_numpy(), g.cp_gi.to_numpy()
    i = int(np.argmax(cpe))
    lp = None
    if 0 < i < len(lam) - 1:
        cc = np.polyfit(lam[i - 1:i + 2], cpe[i - 1:i + 2], 2)
        lp = (round(-cc[1] / (2 * cc[0]), 4), round(float(np.polyval(cc, -cc[1] / (2 * cc[0]))), 6))
    j = int(np.argmax(cpg))
    rig[(U, run)] = g
    if U in (10.24, 23.03, 37.95, 35.82):
        put(f"rig_U{U}_run{run}", dict(n=len(g), dropped=len(lamv) - keep, lam_max=round(lam.max(), 4),
                                         lam_min=round(lam.min(), 4), lam_at_max_cpel_sample=round(lam[i], 4),
                                         cpel_max_sample=round(cpe[i], 6), parabola_peak=lp,
                                         lam_at_max_cpgi=round(lam[j], 4), cpgi_max=round(cpg[j], 5),
                                         cq_gen_at_lightest=round(float(g.sort_values("demand_a").cq_gen.iloc[0]), 5)))
# rig at lambda 0.10 and 0.15, 23 m/s (both runs, linear interpolation in lambda)
for l in (0.10, 0.15):
    e, gi = [], []
    for run in (1, 2):
        g = rig[(23.03, run)].sort_values("tip_speed_ratio")
        e.append(np.interp(l, g.tip_speed_ratio, g.cp_el))
        gi.append(np.interp(l, g.tip_speed_ratio, g.cp_gi))
    put(f"rig_23_at_lam{l}", dict(cp_el=round(float(np.mean(e)), 5), cp_gen_in=round(float(np.mean(gi)), 5)))

# ------------------------------------------------------------------ resolution
cq10 = float(curves[("A", 23.0, "CCW")][1][np.isclose(curves[("A", 23.0, "CCW")][0], 0.10)][0])
gains = {"FS 0.10": 0.128, "FS 0.20": 0.162}
sig_dq = {k: g * cq10 for k, g in gains.items()}
noise = {f"avg {h} {U:g}": 2 * sig[(h, U)] / math.sqrt(3) for (h, U) in sig}
noise.update({f"tstep {s}": abs(OUT[f"tstep_A23_{s}"]["d"]) for s in ("CW", "CCW")})
put("res_signal", {k: round(v, 5) for k, v in sig_dq.items()})
put("res_noise", {k: round(v, 5) for k, v in noise.items()})
ratios = {f"{n}/{s}": round(v / w, 2) for n, v in noise.items() for s, w in sig_dq.items()}
put("res_ratios", ratios)
put("res_ratio_range_all", [min(ratios.values()), max(ratios.values())])
put("res_ratio_range_averaging_only", [min(v for k, v in ratios.items() if k.startswith("avg")),
                                       max(v for k, v in ratios.items() if k.startswith("avg"))])
# revolutions needed so that the 2-sigma uncertainty of a rough-minus-smooth difference (two cases,
# same settings) is below the implied change, A 23 m/s
s = sig[("A", 23.0)]
put("res_nrev_needed_A23", {k: math.ceil((2 * math.sqrt(2) * s / v) ** 2) for k, v in sig_dq.items()})

(BASE / "out/rotor_verify.json").write_text(json.dumps(OUT, indent=1, default=str))


# ------------------------------------------------------------------ CFD (A reversed) against the rig, matched lambda
def rig_interp(U, l):
    vals = []
    for run in (1, 2):
        g = rig[(U, run)].sort_values("tip_speed_ratio")
        x = g.tip_speed_ratio.to_numpy()
        if x.min() <= l <= x.max():
            # average duplicate lambda samples (rpm quantisation) before interpolating
            gg = g.groupby("tip_speed_ratio")[["cp_el", "cp_gi"]].mean()
            vals.append((np.interp(l, gg.index, gg.cp_el), np.interp(l, gg.index, gg.cp_gi)))
    if not vals:
        return None
    return tuple(round(float(np.mean([v[i] for v in vals])), 6) for i in (0, 1)) + (len(vals),)


mag = {}
for U_cfd, U_rig in ((10.2, 10.24), (23.0, 23.03), (38.0, 37.95)):
    lam, q, u, cp = curves[("A", U_cfd, "CCW")]
    for l, c, uu in zip(lam, cp, u):
        r = rig_interp(U_rig, l)
        if r:
            mag[f"U{U_cfd:g}_lam{l:g}"] = dict(cp_cfd=round(float(c), 5), two_u=round(float(2 * l * uu), 5),
                                              rig_el=r[0], rig_gen_in=r[1], runs=r[2],
                                              ratio_gen_in=round(float(c) / r[1], 2),
                                              cfd_minus_gen_in_over_u=round((float(c) - r[1]) / float(l * uu), 1))
put("cfd_vs_rig_A_reversed", mag)
for U in (23.03, 37.95):
    for run in (1, 2):
        g = rig[(U, run)].sort_values("demand_a")
        put(f"rig_lightest_U{U}_run{run}", dict(lam=round(float(g.tip_speed_ratio.iloc[0]), 4),
                                                cq_gen=round(float(g.cq_gen.iloc[0]), 5)))
put("gap_rig_bound_minus_cfd_lam0_U38", dict(gap=round(0.2065 - z[38.0][0], 4), z=round((0.2065 - z[38.0][0]) / z[38.0][1], 2)))
(BASE / "out/rotor_verify.json").write_text(json.dumps(OUT, indent=1, default=str))
