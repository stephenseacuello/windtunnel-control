#!/usr/bin/env python3
"""Rotor stage (cfd/rotor2d, 2D URANS): numbers and figures from the merged result tables.

    nice -n 10 python3 cfd/analysis/2026-10-13/src/rotor_analysis.py

Inputs (read only)
  ../data/rotor_static.csv   16 static cases: hypotheses A and B, blade azimuth theta 0-105 deg
                             in 15-deg steps, 23 m/s, SST, medium mesh, wall functions
  ../data/rotor_cp.csv       40 rotating cases: A at 10.2, 23 and 38 m/s and B at 23 m/s, each
                             in both rotation senses, plus two maxCo 2 checks (A, 23 m/s, lambda 0.15)
  reports/roughness_2026-09/build/tacho/derived/rotor_speed_by_dwell.csv
                             rig (Plain rotor, 1 Oct 2026): lambda, C_P,el and generator input
                             power p_gen_in_w at every load step
  reports/roughness_2026-09/build/derived/rotor_speed_by_run.csv
                             rig light-load lambda (first, lightest load step of each wind speed)
  Rig load steps after a stall (lambda falling below 0.8 x the previous step; only at 35.8 m/s)
  are dropped. The rig's highest loaded lambda is a lower bound on its aerodynamic zero-torque
  lambda (generator and friction torque are both positive there).
Outputs
  ../fig/rotor_*.png         figures, 200 dpi
  ../out/rotor_numbers.json  every number quoted in the rotor findings

Conventions (cfd/rotor2d/README.md). C_Q and C_P per unit span on the swept width 2R,
R = 101.6 mm; lambda = Omega R / U; C_Q > 0 drives the rotor in the case's rotation sense
(model frame, viewed from CAD +z). 'Drag-rule sense' = the sense the queue's 'sense auto' picks
(A: CW, B: CCW); 'reversed' = the cases named _senseCCW (A) or _senseCW (B). The static
cases are all in the drag-rule sense, so their C_Q in the reversed sense is -C_Q.

Uncertainty of a rotating mean (an estimate made here, not in the tables). The revolution-to-
revolution standard deviation sigma_rev is pooled over the production cases of one hypothesis
and wind speed from the difference of the last two revolution means, d = CQ_drift_last_two_rev:
sigma_rev^2 = mean(d^2) / 2, and u(C_Q) = sigma_rev / sqrt(n_avg_rev). It treats revolution
means as independent, and it covers neither the mesh (one level only) nor the time step
(checked separately with the two maxCo 2 cases).
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

HERE = Path(__file__).resolve().parent
BASE = HERE.parent                      # cfd/analysis/2026-10-13
REPO = BASE.parents[2]                  # repository root
DATA, FIG, OUT = BASE / "data", BASE / "fig", BASE / "out"
DWELL = REPO / "reports/roughness_2026-09/build/tacho/derived/rotor_speed_by_dwell.csv"
BYRUN = REPO / "reports/roughness_2026-09/build/derived/rotor_speed_by_run.csv"
RHO_RIG = 1.204                         # as cfd/post/plot_rotor_cp.py and the rig's cp_el column
AREA_RIG = 2 * 0.1016 * 0.2451          # 2RH (m^2), the reports' swept area

# ---------------------------------------------------------------- style
C_A, C_B = "#000000", "#7a7a7a"         # smooth blades: hypothesis A black, B grey
C_RIG = "#eb6834"                       # rig measurements (Plain rotor)
C_U = {10.2: "#a3a3a3", 23.0: "#5c5c5c", 38.0: "#000000"}   # wind speed, light -> dark
M_U = {10.2: "^", 23.0: "o", 38.0: "s"}
HYP_C = {"A": C_A, "B": C_B}
HYP_M = {"A": "o", "B": "s"}


def style():
    plt.rcParams.update({
        "font.family": "sans-serif", "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
        "mathtext.fontset": "dejavusans",
        "font.size": 8.5, "axes.titlesize": 8.5, "axes.labelsize": 8.5,
        "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 7.2,
        "axes.linewidth": 0.6, "axes.edgecolor": "#333333", "axes.labelcolor": "#111111",
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": "#e4e4e4", "grid.linewidth": 0.5,
        "xtick.color": "#333333", "ytick.color": "#333333",
        "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "lines.linewidth": 1.3, "lines.markersize": 4.5,
        "legend.frameon": False, "legend.handlelength": 2.2,
        "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.dpi": 200, "savefig.facecolor": "white", "savefig.bbox": "tight",
        "savefig.pad_inches": 0.03,
    })


# ---------------------------------------------------------------- helpers
def is_production(r):
    """Production settings of cfd/rotor2d/run_case.py (as cfd/post/plot_rotor_cp.py: variant_tag)."""
    return (r["freestream_decay"] == "control" and abs(r["Tu_rotor_pct"] - 1.0) < 1e-6
            and abs(r["lt_m"] - 1e-3) < 1e-9 and abs(r["maxCo"] - 4.0) < 1e-9 and int(r["nOuter"]) == 2)


def minus(s):
    """Typographic minus sign in annotation text."""
    return s.replace("-", "−")


def peak_of(lam, cp):
    """lambda and C_P at the peak: parabola through the top three points if the maximum is
    interior (the method of cfd/post/plot_rotor_cp.py), else the maximum sample, flagged.
    Repeated lambda values (the rig's speed resolution) are averaged first."""
    lam, cp = np.asarray(lam, float), np.asarray(cp, float)
    ul = np.unique(lam)
    if len(ul) < len(lam):
        cp = np.array([cp[lam == v].mean() for v in ul])
        lam = ul
    i = int(np.argmax(cp))
    if 0 < i < len(lam) - 1:
        a, b, c = np.polyfit(lam[i - 1:i + 2], cp[i - 1:i + 2], 2)
        if a < 0:
            return dict(lam_peak=float(-b / (2 * a)), CP_peak=float(c - b * b / (4 * a)), at_edge=None,
                        bracket=[float(lam[i - 1]), float(lam[i + 1])])
    edge = "lowest" if i == 0 else ("highest" if i == len(lam) - 1 else None)
    br = [0.0 if i == 0 else float(lam[i - 1]), float(lam[i + 1]) if i < len(lam) - 1 else None]
    return dict(lam_peak=float(lam[i]), CP_peak=float(cp[i]), at_edge=edge, bracket=br)


def zero_crossings(lam, cq, u):
    """Every sign change of C_Q, linear interpolation, with its standard uncertainty from u(C_Q)."""
    out = []
    for i in range(len(lam) - 1):
        q1, q2 = cq[i], cq[i + 1]
        if np.sign(q1) != np.sign(q2) and q1 != q2:
            s = lam[i + 1] - lam[i]
            lam0 = lam[i] + s * q1 / (q1 - q2)
            ul = s * math.hypot(q2 * u[i], q1 * u[i + 1]) / (q1 - q2) ** 2
            out.append(dict(lam0=float(lam0), u_lam0=float(ul), between=[float(lam[i]), float(lam[i + 1])],
                            direction="+ to -" if q1 > 0 else "- to +"))
    return out


def lin_fit(lam, cq):
    b, a = np.polyfit(lam, cq, 1)
    res = cq - (a + b * lam)
    d = dict(a=float(a), b=float(b), resid_rms=float(np.sqrt(np.mean(res ** 2))))
    if b < 0 and a > 0:
        d.update(lam0=float(-a / b), lam_peak=float(-a / (2 * b)), CP_max=float(-a * a / (4 * b)))
    return d


def r6(x):
    return None if x is None else float(f"{x:.6g}")


# ---------------------------------------------------------------- static (stage 3a)
def analyse_static(st):
    res = {}
    for hyp, g in st.groupby("hypothesis"):
        g = g.sort_values("theta_deg")
        th, cq, sem, sd = (g[c].to_numpy(float) for c in ("theta_deg", "CQ_mean", "CQ_sem", "CQ_std"))
        assert len(th) == 8 and th[0] == 0 and np.allclose(np.diff(th), 15), "expected theta 0..105 step 15"
        mean = float(cq.mean())                       # uniform grid over one 120-deg period
        sem_t = float(np.sqrt(np.sum(sem ** 2)) / len(cq))
        sub_a, sub_b = float(cq[::2].mean()), float(cq[1::2].mean())   # theta 0,30,60,90 / 15,45,75,105
        verdict = ("positive beyond 2 SEM: starts in the drag-rule sense" if mean > 2 * sem_t else
                   "negative beyond 2 SEM: starts in the reversed sense" if mean < -2 * sem_t else
                   "within 2 SEM of zero")
        res[hyp] = dict(
            cases=g["name"].tolist(), sense_drag_rule=g["sense"].iloc[0], ran_on=g["ran_on"].tolist(),
            theta_deg=th.tolist(), CQ_mean=[r6(v) for v in cq], CQ_sem=[r6(v) for v in sem],
            CQ_std=[r6(v) for v in sd],
            mean_over_theta_drag_rule_sense=r6(mean), sem_time_of_mean=r6(sem_t),
            mean_over_theta_reversed_sense=r6(-mean),
            subset_means_30deg={"theta_0_30_60_90": r6(sub_a), "theta_15_45_75_105": r6(sub_b)},
            sampling_halfspread=r6(abs(sub_a - sub_b) / 2),
            n_positive_drag_rule=int((cq > 0).sum()), n_negative_drag_rule=int((cq < 0).sum()),
            theta_negative_in_starting_sense=[float(t) for t, v in zip(th, cq) if (v if mean > 0 else -v) < 0],
            CQ_std_range=[r6(sd.min()), r6(sd.max())],
            verdict_2sem_time=verdict,
            subsets_agree_in_sign=bool(np.sign(sub_a) == np.sign(sub_b)),
            yplus_mean_range=[r6(g.yplus_mean.min()), r6(g.yplus_mean.max())],
            yplus_max_max=r6(g.yplus_max.max()),
            ami_weight_range=[r6(g.ami_weight_min.min()), r6(g.ami_weight_max.max())],
            t_end_conv_min=r6(g.t_end_conv.min()), avg_window_conv=r6(g.avg_window_conv.min()),
            all_windows_complete=bool(g.avg_window_complete.all()),
            omega_bounded_steps=int(g.omega_bounded_steps.sum()),
            Tu_probe_range=[r6(g.Tu_upstream_probe_pct.min()), r6(g.Tu_upstream_probe_pct.max())],
            St_D_range=[r6(g.St_D.min()), r6(g.St_D.max())],
            Cx_mean_range=[r6(g.Cx_mean.min()), r6(g.Cx_mean.max())],
            CQ_viscous_abs_max=r6(np.max(np.abs(g.CQ_mean - g.CQ_pressure_mean))),
        )
    return res


# ---------------------------------------------------------------- rotating (stage 3b)
def analyse_rotating(rc, drag_rule, static):
    rc = rc.copy()
    rc["production"] = rc.apply(is_production, axis=1)
    rc["sense_kind"] = np.where(rc["sense"] == rc["hypothesis"].map(drag_rule), "drag rule", "reversed")
    # pooled revolution-to-revolution s.d. per hypothesis and speed (production cases only)
    sig = {}
    for (h, U), g in rc[rc.production].groupby(["hypothesis", "U_ms"]):
        d = g["CQ_drift_last_two_rev"].to_numpy(float)
        sig[(h, float(U))] = dict(sigma_rev=float(math.sqrt(np.mean(d ** 2) / 2)), n_cases=int(len(d)),
                                 drift_abs_max=float(np.max(np.abs(d))))
    rc["u_CQ"] = [sig[(h, float(U))]["sigma_rev"] / math.sqrt(n)
                  for h, U, n in zip(rc.hypothesis, rc.U_ms, rc.n_avg_rev)]
    rc["u_CP"] = rc["lam"] * rc["u_CQ"]

    curves = {}
    for (h, U, sense), g in rc[rc.production].groupby(["hypothesis", "U_ms", "sense"]):
        g = g.sort_values("lam")
        lam, cq, cp, u = (g[c].to_numpy(float) for c in ("lam", "CQ_mean", "CP_mean", "u_CQ"))
        key = f"{h}_U{float(U):g}_{sense}"
        kind = g["sense_kind"].iloc[0]
        c = dict(hypothesis=h, U_ms=float(U), sense=sense, sense_kind=kind, cases=g["name"].tolist(),
                 lam=lam.tolist(), CQ=[r6(v) for v in cq], CP=[r6(v) for v in cp], u_CQ=[r6(v) for v in u],
                 drift=[r6(v) for v in g["CQ_drift_last_two_rev"]], n_rev_done=g["n_rev_done"].tolist(),
                 n_avg_rev=g["n_avg_rev"].tolist(), CQ_std=[r6(v) for v in g["CQ_std"]],
                 CQ_min=[r6(v) for v in g["CQ_min"]], CQ_max=[r6(v) for v in g["CQ_max"]],
                 CQ_viscous=[r6(a - b) for a, b in zip(g["CQ_mean"], g["CQ_pressure_mean"])],
                 n_positive=int((cq > 0).sum()), n_resolved_positive_2u=int((cq > 2 * u).sum()),
                 n_resolved_negative_2u=int((cq < -2 * u).sum()),
                 zero_crossings=zero_crossings(lam, cq, u), peak=peak_of(lam, cp), linear_CQ_fit=lin_fit(lam, cq))
        # static mean at lambda = 0 in this sense (23 m/s only)
        if abs(float(U) - 23.0) < 0.05 and h in static:
            m = static[h]["mean_over_theta_drag_rule_sense"]
            c["static_CQ_this_sense"] = m if kind == "drag rule" else -m
            c["CQ_lam005_minus_static"] = r6(cq[0] - c["static_CQ_this_sense"]) if abs(lam[0] - 0.05) < 1e-9 else None
            if c["static_CQ_this_sense"] > 0 and len(lam) >= 2:
                # cubic through C_P(0) = 0 with slope = static C_Q, and the two lowest-lambda points
                l1, l2 = lam[0], lam[1]
                q0 = c["static_CQ_this_sense"]
                A = np.array([[l1, l1 ** 2], [l2, l2 ** 2]])
                c1, c2 = np.linalg.solve(A, np.array([cq[0] - q0, cq[1] - q0]))
                ll = np.linspace(0, l2, 2001)
                cpp = ll * (q0 + c1 * ll + c2 * ll ** 2)
                j = int(np.argmax(cpp))
                c["static_anchored_peak_inferred"] = dict(lam_peak=r6(ll[j]), CP_peak=r6(cpp[j]),
                                                          method="C_Q = q0 + c1 lam + c2 lam^2 through the static "
                                                                 "mean and the two lowest-lambda points")
        curves[key] = c

    # sense decomposition at common lambda: D = (C_Q,CCW - C_Q,CW)/2, E = (C_Q,CCW + C_Q,CW)/2
    decomp = {}
    for (h, U), g in rc[rc.production].groupby(["hypothesis", "U_ms"]):
        a = g[g.sense == "CCW"].set_index("lam")
        b = g[g.sense == "CW"].set_index("lam")
        common = sorted(set(a.index) & set(b.index))
        D = [(a.loc[l, "CQ_mean"] - b.loc[l, "CQ_mean"]) / 2 for l in common]
        E = [(a.loc[l, "CQ_mean"] + b.loc[l, "CQ_mean"]) / 2 for l in common]
        lam = np.array(common, float)
        Ea = np.array(E)
        k = float(-np.sum(Ea * lam) / np.sum(lam ** 2))      # E = -k lambda, through the origin
        d = dict(lam=lam.tolist(), D_CCW_frame=[r6(v) for v in D], E_common=[r6(v) for v in E],
                 k_fit=r6(k), E_fit_resid_rms=r6(float(np.sqrt(np.mean((Ea + k * lam) ** 2)))),
                 D_mean=r6(float(np.mean(D))), D_range=[r6(min(D)), r6(max(D))])
        if abs(float(U) - 23.0) < 0.05 and h in static:
            m = static[h]["mean_over_theta_drag_rule_sense"]
            d["D_static_lambda0"] = r6(m if drag_rule[h] == "CCW" else -m)
        decomp[f"{h}_U{float(U):g}"] = d

    # time-step check: maxCo 2 against maxCo 4, same case otherwise
    tstep = []
    for _, r in rc[~rc.production].iterrows():
        m = rc[rc.production & (rc.hypothesis == r.hypothesis) & (rc.U_ms == r.U_ms) & (rc.sense == r.sense)
               & (np.abs(rc.lam - r.lam) < 1e-9)]
        if len(m) != 1:
            continue
        p = m.iloc[0]
        dq = float(r.CQ_mean - p.CQ_mean)
        tstep.append(dict(case_Co4=p["name"], case_Co2=r["name"], sense=r.sense, sense_kind=r.sense_kind,
                          lam=float(r.lam), CQ_Co4=r6(p.CQ_mean), CQ_Co2=r6(r.CQ_mean), dCQ=r6(dq),
                          dCQ_over_u_diff=r6(dq / math.hypot(p.u_CQ, r.u_CQ)),
                          CQ_std_Co4=r6(p.CQ_std), CQ_std_Co2=r6(r.CQ_std),
                          drift_Co4=r6(p.CQ_drift_last_two_rev), drift_Co2=r6(r.CQ_drift_last_two_rev),
                          dt_mean_Co4=r6(p.dt_mean_s), dt_mean_Co2=r6(r.dt_mean_s),
                          steps_Co4=int(p.n_steps), steps_Co2=int(r.n_steps)))

    quality = dict(
        n_cases=int(len(rc)), n_production=int(rc.production.sum()),
        all_windows_complete=bool(rc.avg_window_complete.all()),
        n_rev_done_values=sorted(set(float(v) for v in rc.n_rev_done)),
        n_avg_rev_values=sorted(set(round(float(v), 3) for v in rc.n_avg_rev)),
        drift_abs_median=r6(float(np.median(np.abs(rc.CQ_drift_last_two_rev)))),
        drift_abs_max=r6(float(np.max(np.abs(rc.CQ_drift_last_two_rev)))),
        drift_abs_max_case=rc.loc[np.argmax(np.abs(rc.CQ_drift_last_two_rev.to_numpy())), "name"],
        sigma_rev_pooled={f"{h}_U{U:g}": {k: r6(v) if isinstance(v, float) else v for k, v in s.items()}
                          for (h, U), s in sig.items()},
        ami_weight_min=r6(rc.ami_weight_min.min()), ami_weight_max=r6(rc.ami_weight_max.max()),
        yplus_mean_range=[r6(rc.yplus_mean.min()), r6(rc.yplus_mean.max())],
        yplus_max_range=[r6(rc.yplus_max.min()), r6(rc.yplus_max.max())],
        yplus_mean_by_U={f"{U:g}": [r6(g.yplus_mean.min()), r6(g.yplus_mean.max())] for U, g in rc.groupby("U_ms")},
        h0_by_U={f"{U:g}": r6(g.h0_m.iloc[0]) for U, g in rc.groupby("U_ms")},
        omega_bounded_steps=int(rc.omega_bounded_steps.sum()),
        Co_max_mean_range=[r6(rc.Co_max_mean.min()), r6(rc.Co_max_mean.max())],
        Tu_probe_range=[r6(rc.Tu_upstream_probe_pct.min()), r6(rc.Tu_upstream_probe_pct.max())],
        ran_on=sorted(set(rc.ran_on)), nProcs=sorted(set(int(v) for v in rc.nProcs)),
        CQ_viscous_abs_max=r6(float(np.max(np.abs(rc.CQ_mean - rc.CQ_pressure_mean)))),
        CQ_std_range_A=[r6(rc[rc.hypothesis == "A"].CQ_std.min()), r6(rc[rc.hypothesis == "A"].CQ_std.max())],
        CQ_std_range_B=[r6(rc[rc.hypothesis == "B"].CQ_std.min()), r6(rc[rc.hypothesis == "B"].CQ_std.max())],
        wall_time_h_total=r6(float(rc.wall_time_s.sum()) / 3600),
        core_h_total=r6(float((rc.wall_time_s * rc.nProcs).sum()) / 3600),
        deg_per_step_range=[r6(float((np.degrees(rc.Omega * rc.dt_mean_s)).min())),
                            r6(float((np.degrees(rc.Omega * rc.dt_mean_s)).max()))],
    )
    return rc, curves, decomp, tstep, quality


# ---------------------------------------------------------------- rig
def drop_stall(g):
    """Load steps in demand order; from the first step whose lambda falls below 0.8 x the previous
    valid step's, the rotor was stalling (only at 35.8 m/s: lambda 0.077, 0.017, 0.007), so that
    step and every later one are dropped."""
    g = g.sort_values("demand_a")
    keep, prev = [], None
    for idx, lam in zip(g.index, g.tip_speed_ratio):
        if prev is not None and lam < 0.8 * prev:
            break
        keep.append(idx)
        prev = lam
    return g.loc[keep], int(len(g) - len(keep))


def analyse_rig():
    dw = pd.read_csv(DWELL)
    dw = dw[(dw.rotor == "Plain") & (dw.speed_ok.astype(str) == "True")].copy()
    dw["U"] = dw.wind_mps.round(2)
    dw["cp_gen_in"] = dw.p_gen_in_w / (0.5 * RHO_RIG * AREA_RIG * dw.wind_mps ** 3)
    br = pd.read_csv(BYRUN)
    br = br[(br.rotor == "Plain")]
    rig = {}
    for (U, run), g in dw.groupby(["U", "run"]):
        g, n_stall = drop_stall(g)
        g = g.sort_values("tip_speed_ratio")
        lam = g.tip_speed_ratio.to_numpy(float)
        pe, pg = peak_of(lam, g.cp_el.to_numpy(float)), peak_of(lam, g.cp_gen_in.to_numpy(float))
        ll = br[(np.abs(br.wind_mps - g.wind_mps.iloc[0]) < 0.05) & (br.run == run)]
        light = float(ll.tip_speed_ratio.iloc[0]) if len(ll) and int(ll.light_load.iloc[0]) == 1 else None
        rig.setdefault(f"{U:g}", {})[f"run{run}"] = dict(
            U_ms=float(g.wind_mps.iloc[0]), n_steps=int(len(g)), n_stall_steps_dropped=n_stall,
            lam_min_loaded=float(lam.min()), lam_max_loaded=float(lam.max()),
            lam_peak_cp_el=r6(pe["lam_peak"]), cp_el_peak=r6(pe["CP_peak"]), cp_el_peak_at_edge=pe["at_edge"],
            lam_peak_cp_gen_in=r6(pg["lam_peak"]), cp_gen_in_peak=r6(pg["CP_peak"]),
            cp_gen_in_peak_at_edge=pg["at_edge"], lam_light_load=light,
            points=dict(lam=[r6(v) for v in lam], cp_el=[r6(v) for v in g.cp_el], cp_gen_in=[r6(v) for v in g.cp_gen_in]))
    return rig


def rig_at(rig, U, lam):
    """Rig C_P,el and C_P,gen-in interpolated at lambda (runs averaged; None outside the loaded range)."""
    key = min(rig, key=lambda k: abs(float(k) - U))
    el, gi = [], []
    for run in rig[key].values():
        p = run["points"]
        x = np.array(p["lam"])
        if x.min() <= lam <= x.max():
            # sort and average duplicates in lambda before interpolating
            order = np.argsort(x)
            el.append(float(np.interp(lam, x[order], np.array(p["cp_el"])[order])))
            gi.append(float(np.interp(lam, x[order], np.array(p["cp_gen_in"])[order])))
    return (r6(np.mean(el)) if el else None, r6(np.mean(gi)) if gi else None)


# ---------------------------------------------------------------- figures
def fig_static(st, static):
    fig, ax = plt.subplots(figsize=(3.6, 2.95))
    for hyp, dx in (("A", -0.9), ("B", 0.9)):
        s, col, mk = static[hyp], HYP_C[hyp], HYP_M[hyp]
        th, cq, sem = np.array(s["theta_deg"]), np.array(s["CQ_mean"]), np.array(s["CQ_sem"])
        face = "concave" if hyp == "A" else "convex"
        ax.errorbar(th + dx, cq, yerr=2 * sem, fmt=mk + "-", color=col, mfc=col, mec=col, ms=4.2, lw=1.2,
                    elinewidth=0.8, capsize=1.8, zorder=3,
                    label=f"{hyp}: arm on {face} face, {s['sense_drag_rule']}")
        ax.plot([th[-1] + dx, 120 + dx], [cq[-1], cq[0]], "-", color=col, lw=1.2, zorder=3)
        ax.plot(120 + dx, cq[0], mk, mfc="white", mec=col, ms=4.2, zorder=4)
        m = s["mean_over_theta_drag_rule_sense"]
        ax.plot([-4, 124], [m, m], "-", color=col, lw=0.7, zorder=2)
        ax.annotate(minus(f"{hyp} mean {m:+.3f}"), xy=(124, m), xytext=(2, 0), textcoords="offset points",
                    va="center", ha="left", fontsize=7.2, color="#111111")
    ax.axhline(0, color="#333333", lw=0.6, zorder=1)
    ax.set_xlim(-6, 124)
    ax.set_ylim(-0.245, 0.135)
    ax.set_xticks(range(0, 121, 15))
    # theta runs in each hypothesis's drag-rule sense (rotor_geometry.blade_transform: phi = pi + s theta),
    # so the same theta is a mirror-image blade position for A (CW) and B (CCW)
    ax.set_xlabel(r"azimuth $\theta$ of blade 1 (deg), increasing in the drag-rule sense;" "\n"
                  r"0 = its radial line points upwind")
    ax.set_ylabel(r"static $C_Q$ in the drag-rule sense (–)")
    hl, lb = ax.get_legend_handles_labels()
    hl.append(Line2D([], [], color="#555555", marker="o", mfc="white", lw=0, ms=4.2))
    lb.append(r"open: $\theta$ = 120° repeats $\theta$ = 0°")
    ax.legend(hl, lb, loc="lower left", fontsize=6.6, handlelength=1.6, borderaxespad=0.3,
              title="bars: ±2 SEM of each time mean", title_fontsize=6.6, alignment="left")
    ax.set_title("Static torque, 23 m/s, SST, medium mesh (2D)", loc="left", fontsize=8.2)
    fig.savefig(FIG / "rotor_static_CQ_theta.png")
    plt.close(fig)


def _curve_label(c):
    return f"{c['hypothesis']}, {c['sense_kind']} ({c['sense']})"


def _sense_style(c):
    """Model-frame CCW (the sense both static means favour) filled, CW open."""
    col, mk = HYP_C[c["hypothesis"]], HYP_M[c["hypothesis"]]
    return dict(color=col, marker=mk, mfc=col if c["sense"] == "CCW" else "white", mec=col)


ORDER23 = ["A_U23_CCW", "A_U23_CW", "B_U23_CCW", "B_U23_CW"]


def _cfd_handles(with_co2=True, with_static=False):
    h = []
    for k, (hyp, kind, sense) in zip(ORDER23, (("A", "reversed", "CCW"), ("A", "drag rule", "CW"),
                                               ("B", "drag rule", "CCW"), ("B", "reversed", "CW"))):
        col, mk = HYP_C[hyp], HYP_M[hyp]
        h.append(Line2D([], [], color=col, marker=mk, mfc=col if sense == "CCW" else "white", mec=col, ms=4.2,
                        lw=1.2, label=f"{hyp}, {kind} ({sense})"))
    if with_co2:
        h.append(Line2D([], [], color=C_A, marker="x", lw=0, ms=5, mew=1.1, label="A, maxCo 2 check (λ 0.15)"))
    if with_static:
        h.append(Line2D([], [], color="#555555", marker="D", mfc="white", lw=0, ms=4,
                        label=r"static mean over $\theta$; bar: 30° subsets"))
    return h


def fig_cp_u23(curves, tstep, rig):
    fig, (ax, bx) = plt.subplots(2, 1, figsize=(3.6, 5.6), gridspec_kw=dict(height_ratios=[1, 1.15]))
    for k in ORDER23:
        c = curves[k]
        lam, cp = np.array(c["lam"]), np.array(c["CP"])
        ax.errorbar(lam, cp, yerr=2 * lam * np.array(c["u_CQ"]), lw=1.2, ms=4.2, elinewidth=0.7, capsize=1.6,
                    **_sense_style(c))
    for t in tstep:
        ax.plot(t["lam"] + 0.006, t["CQ_Co2"] * t["lam"], "x", color=C_A, ms=5, mew=1.1)
    ax.axhline(0, color="#333333", lw=0.6)
    ax.set_ylabel(r"$C_P$ (–)")
    ax.set_xlim(0, 0.27)
    ax.legend(handles=_cfd_handles(), loc="lower left", fontsize=6.6, handlelength=2.0)
    ax.set_title("(a) CFD, 23 m/s: both hypotheses, both senses", loc="left", fontsize=8.2)

    # (b) zoom on the power-producing region, with the rig
    r23 = rig["23.03"]
    for j, run in enumerate(sorted(r23)):
        p = r23[run]["points"]
        bx.plot(p["lam"], p["cp_el"], "o", ms=2.6, color=C_RIG, alpha=0.85, mew=0)
        bx.plot(p["lam"], p["cp_gen_in"], "+", ms=3.6, color=C_RIG, mew=0.8)
    lmax = max(r["lam_max_loaded"] for r in r23.values())
    bx.axvline(lmax, color=C_RIG, lw=0.9, zorder=1)
    bx.annotate(f"rig light-load\nλ {lmax:.3f}", xy=(lmax, 0.0033), xytext=(3, 0), textcoords="offset points",
                fontsize=6.6, color="#111111", va="top")
    for k in ("A_U23_CCW", "B_U23_CCW"):
        c = curves[k]
        lam, cp = np.array(c["lam"]), np.array(c["CP"])
        bx.errorbar(lam, cp, yerr=2 * lam * np.array(c["u_CQ"]), lw=1.2, ms=4.2, elinewidth=0.7, capsize=1.6,
                    **_sense_style(c))
    t = [t for t in tstep if t["sense"] == "CCW"][0]
    bx.plot(t["lam"] + 0.004, t["CQ_Co2"] * t["lam"], "x", color=C_A, ms=5, mew=1.1)
    z = [z for z in curves["A_U23_CCW"]["zero_crossings"] if z["direction"] == "+ to -"][-1]
    # the +-2u bar lies on the C_P = 0 line, so draw it thick with caps (that line is grey in this panel)
    bx.errorbar(z["lam0"], 0, xerr=2 * z["u_lam0"], fmt="|", color=C_A, ms=9, mew=1.4, elinewidth=1.8, capsize=3,
                capthick=1.2, zorder=5)
    bx.annotate(minus(f"A reversed: zero torque\nλ = {z['lam0']:.3f} ± {2 * z['u_lam0']:.3f} (2u)"),
                xy=(z["lam0"] + 0.002, 0.00005), xytext=(0.183, 0.0013), fontsize=6.6, color="#111111",
                ha="left", va="center", arrowprops=dict(arrowstyle="-", lw=0.6, color="#333333"))
    bx.annotate("λ ≥ 0.20: below this\nwindow, see (a)", xy=(0.196, -0.0040), fontsize=6.4, color="#555555",
                ha="left", va="bottom")
    bx.axhline(0, color="#9a9a9a", lw=0.6, zorder=1)
    bx.set_xlim(0, 0.27)
    bx.set_ylim(-0.0042, 0.0034)
    bx.set_xlabel(r"tip-speed ratio $\lambda = \Omega R/U$ (–), R = 101.6 mm")
    bx.set_ylabel(r"$C_P$ (–)")
    h = [Line2D([], [], color=C_RIG, marker="o", ms=2.6, mew=0, lw=0, label=r"rig $C_{P,\mathrm{el}}$, 2 runs"),
         Line2D([], [], color=C_RIG, marker="+", ms=3.6, mew=0.8, lw=0,
                label=r"rig $C_{P,\mathrm{gen\,in}}$ ($I^2R$ added back)")]
    bx.legend(handles=h, loc="lower left", fontsize=6.6, handlelength=1.2, borderaxespad=0.3)
    bx.set_title("(b) zoom: the two CCW curves and the rig (Plain, 23.0 m/s)", loc="left", fontsize=8.2)
    fig.savefig(FIG / "rotor_cp_lambda_U23.png")
    plt.close(fig)


def fig_cq_u23(curves, decomp, static, tstep):
    fig, (ax, bx) = plt.subplots(2, 1, figsize=(3.6, 5.9), gridspec_kw=dict(height_ratios=[1.15, 1]))
    for k in ORDER23:
        c = curves[k]
        lam, cq, u = np.array(c["lam"]), np.array(c["CQ"]), np.array(c["u_CQ"])
        st = _sense_style(c)
        ax.errorbar(lam, cq, yerr=2 * u, lw=1.2, ms=4.2, elinewidth=0.7, capsize=1.6, **st)
        s0 = c["static_CQ_this_sense"]
        hs = static[c["hypothesis"]]["sampling_halfspread"]
        ax.errorbar(0.0, s0, yerr=hs, fmt="D", color=st["color"], mfc=st["mfc"], mec=st["mec"], ms=4.0,
                    elinewidth=0.7, capsize=1.6, zorder=4)
        ax.plot([0.0, lam[0]], [s0, cq[0]], ":", color=st["color"], lw=0.8)
    for t in tstep:
        ax.plot(t["lam"] + 0.006, t["CQ_Co2"], "x", color=C_A, ms=5, mew=1.1)
    ax.axhline(0, color="#333333", lw=0.6)
    ax.set_xlim(-0.012, 0.27)
    ax.set_ylabel(r"$C_Q$ in the case's own sense (–)")
    ax.set_title(r"(a) torque, 23 m/s; diamonds: static runs at $\lambda$ = 0", loc="left", fontsize=8.2)

    for h in ("A", "B"):
        d = decomp[f"{h}_U23"]
        lam = np.array(d["lam"])
        col, mk = HYP_C[h], HYP_M[h]
        D0 = d["D_static_lambda0"]
        Dl = np.r_[D0, d["D_CCW_frame"]]
        El = np.r_[0, d["E_common"]]
        bx.plot(np.r_[0, lam], Dl, "-", marker=mk, color=col, mfc=col, ms=4.2, lw=1.2)
        bx.plot(np.r_[0, lam], El, "-", marker=mk, color=col, mfc="white", mec=col, ms=4.2, lw=1.2)
        ll = np.linspace(0, 0.25, 10)
        bx.plot(ll, -d["k_fit"] * ll, "-", color=col, lw=0.6, alpha=0.8)
        bx.annotate(minus(f"{h} common; fit −{d['k_fit']:.2f}λ"), xy=(0.25, El[-1]), xytext=(4, -1 if h == "A" else 0),
                    textcoords="offset points", fontsize=6.6, va="center", color="#111111")
        bx.annotate(f"{h} drive", xy=(0.25, Dl[-1]), xytext=(4, 4 if h == "B" else -4), textcoords="offset points",
                    fontsize=6.6, va="center", color="#111111")
    bx.axhline(0, color="#333333", lw=0.6)
    bx.set_xlim(-0.012, 0.36)
    bx.set_xticks(np.arange(0, 0.26, 0.05))
    bx.spines["bottom"].set_bounds(-0.012, 0.27)
    bx.set_xlabel(r"tip-speed ratio $\lambda$ (–)")
    bx.set_ylabel(r"$C_Q$ part (–)")
    bx.set_title("(b) drive = (CCW − CW)/2, filled; common = (CCW + CW)/2, open", loc="left", fontsize=8.0)
    fig.legend(handles=_cfd_handles(with_co2=True, with_static=True), loc="lower center", ncol=2, fontsize=6.6,
               handlelength=1.8, bbox_to_anchor=(0.5, -0.005), columnspacing=1.0)
    fig.subplots_adjust(bottom=0.17, hspace=0.32)
    fig.savefig(FIG / "rotor_cq_lambda_U23.png")
    plt.close(fig)


def fig_by_speed(curves):
    fig, (ax, bx) = plt.subplots(2, 1, figsize=(3.6, 5.0), sharex=True)
    for axis, sense, title in ((ax, "CCW", "(a) A, reversed sense (CCW)"),
                               (bx, "CW", "(b) A, drag-rule sense (CW)")):
        for U in (10.2, 23.0, 38.0):
            c = curves[f"A_U{U:g}_{sense}"]
            lam, cp = np.array(c["lam"]), np.array(c["CP"])
            u = lam * np.array(c["u_CQ"])
            col, mk = C_U[U], M_U[U]
            axis.errorbar(lam, cp, yerr=2 * u, fmt=mk + "-", color=col, mfc=col if sense == "CCW" else "white",
                          mec=col, ms=4.2, lw=1.2, elinewidth=0.7, capsize=1.6, label=f"{U:g} m/s")
        axis.axhline(0, color="#333333", lw=0.6)
        axis.set_ylabel(r"$C_P$ (–)")
        axis.set_title(title, loc="left", fontsize=8.2)
        axis.legend(loc="lower left", fontsize=6.8)
    ax.set_ylim(-0.0105, 0.0050)
    c38 = curves["A_U38_CCW"]
    v, u = c38["CP"][-1], 2 * c38["lam"][-1] * c38["u_CQ"][-1]
    ax.annotate(minus(f"38 m/s, λ 0.30:\n{v:.4f} ± {u:.4f}"), xy=(0.30, -0.0105), xytext=(0.30, -0.0072),
                fontsize=6.4, ha="center", va="bottom", color="#111111",
                arrowprops=dict(arrowstyle="->", lw=0.6, color="#333333"))
    bx.set_xlabel(r"tip-speed ratio $\lambda$ (–)")
    bx.set_xlim(0.03, 0.32)
    fig.savefig(FIG / "rotor_cp_lambda_by_speed.png")
    plt.close(fig)


def fig_lambda_vs_U(curves, rig, tstep):
    fig, ax = plt.subplots(figsize=(3.6, 3.0))
    Us = sorted(float(k) for k in rig)
    xs = [np.mean([r["U_ms"] for r in rig[f"{U:g}"].values()]) for U in Us]
    for field, mk, mfc, alpha in (("lam_max_loaded", "^", C_RIG, 1.0), ("lam_peak_cp_el", "o", "white", 0.75)):
        ys = []
        for xi, U in zip(xs, Us):
            v = [r[field] for r in rig[f"{U:g}"].values()]
            ax.plot([xi] * len(v), v, mk, color=C_RIG, mfc=mfc, mec=C_RIG, ms=3.4, mew=0.9, alpha=alpha)
            ys.append(np.mean(v))
        ax.plot(xs, ys, "-", color=C_RIG, lw=1.0, alpha=alpha)
    for U in Us:
        for r in rig[f"{U:g}"].values():
            if r["cp_gen_in_peak_at_edge"] is None:
                ax.plot(r["U_ms"], r["lam_peak_cp_gen_in"], "d", color=C_RIG, ms=3.4, mew=0)
            elif r["cp_gen_in_peak_at_edge"] == "lowest":
                ax.plot(r["U_ms"], r["lam_peak_cp_gen_in"], "v", color=C_RIG, ms=3.6, mew=0)
    # CFD, hypothesis A reversed sense
    for U in (10.2, 23.0, 38.0):
        c = curves[f"A_U{U:g}_CCW"]
        z = [z for z in c["zero_crossings"] if z["direction"] == "+ to -"][-1]
        ax.errorbar(U, z["lam0"], yerr=2 * z["u_lam0"], fmt="s", color=C_A, ms=4.6, elinewidth=1.0, capsize=2.2,
                    zorder=5)
        p = c["peak"]
        if p["at_edge"] is None:
            lo, hi, mid = p["bracket"][0], p["bracket"][1], p["lam_peak"]
        elif "static_anchored_peak_inferred" in c:
            lo, hi, mid = c["lam"][0], c["lam"][1], c["static_anchored_peak_inferred"]["lam_peak"]
        else:
            lo, hi, mid = None, None, None
        if lo is not None:
            xp = U - 1.1
            ax.plot([xp, xp], [lo, hi], "-", color=C_A, lw=0.9, zorder=4)
            ax.plot([xp - 0.45, xp + 0.45], [lo, lo], "-", color=C_A, lw=0.9, zorder=4)
            ax.plot([xp - 0.45, xp + 0.45], [hi, hi], "-", color=C_A, lw=0.9, zorder=4)
            ax.plot(xp, mid, "s", mfc="white", mec=C_A, ms=4.6, mew=1.0, zorder=5)
    alt = curves["A_U23_CCW"].get("zero_torque_maxCo2")
    if alt:
        ax.plot(23.0 + 0.9, alt, "s", mfc="white", mec=C_A, ms=3.4, mew=0.9, zorder=5)
        ax.plot([23.0, 23.9], [alt, alt], "-", color=C_A, lw=0.6)
    ax.set_xlabel("wind speed U (m/s)")
    ax.set_ylabel(r"tip-speed ratio $\lambda$ (–)")
    ax.set_xlim(8, 40)
    ax.set_ylim(0.04, 0.225)
    h = [Line2D([], [], color=C_RIG, marker="^", ms=3.4, lw=1.0, mew=0.9,
                label="rig: light-load λ (zero-torque λ lies above)"),
         Line2D([], [], color=C_RIG, marker="o", mfc="white", ms=3.4, lw=1.0, alpha=0.75, label=r"rig: λ at peak $C_{P,\mathrm{el}}$"),
         Line2D([], [], color=C_RIG, marker="d", ms=3.4, lw=0, label=r"rig: λ at peak $C_{P,\mathrm{gen\,in}}$"),
         Line2D([], [], color=C_RIG, marker="v", ms=3.6, lw=0, label=r"rig: $C_{P,\mathrm{gen\,in}}$ peak at or below the lowest loaded λ"),
         Line2D([], [], color=C_A, marker="s", ms=4.6, lw=0, label="CFD A reversed: zero-torque λ (±2u)"),
         Line2D([], [], color=C_A, marker="s", mfc="white", ms=4.6, lw=0.9,
                label=r"CFD A reversed: peak-$C_P$ λ estimate and sampled bracket"),
         Line2D([], [], color=C_A, marker="s", mfc="white", ms=3.4, lw=0,
                label="CFD zero-torque λ with the maxCo 2 value at λ 0.15")]
    fig.legend(handles=h, loc="upper center", bbox_to_anchor=(0.53, 0.0), ncol=1, fontsize=6.4, handlelength=1.8,
               labelspacing=0.35)
    fig.savefig(FIG / "rotor_lambda_vs_U.png")
    plt.close(fig)


def resolution_rows(quality, tstep, rig_gain):
    """Rows of rotor_resolution.png. A roughness comparison is the difference of two runs (rough minus
    smooth, same settings), so its averaging noise is 2u of a difference of two 3-revolution means,
    2 sqrt(2) sigma_rev / sqrt(3) (verifier fix, 13 Oct: the first version showed the single-run 2u)."""
    rows = []
    for key, lab in (("A_U10.2", "A, 10.2 m/s"), ("A_U23", "A, 23 m/s"), ("A_U38", "A, 38 m/s"), ("B_U23", "B, 23 m/s")):
        s = quality["sigma_rev_pooled"][key]["sigma_rev"]
        rows.append((f"averaging, {lab}", 2 * math.sqrt(2) * s / math.sqrt(3), "#7a7a7a", "o"))
    for t in tstep:
        rows.append((f"time step, A {t['sense']}", abs(t["dCQ"]), "#000000", "s"))
    for lab, v in rig_gain:
        rows.append((lab, v, C_RIG, "D"))
    return rows


def fig_resolution(rows):
    """Noise of a rough-minus-smooth C_Q difference against the C_Q change the rig's roughness gain implies."""
    fig, ax = plt.subplots(figsize=(3.6, 2.95))
    y = np.arange(len(rows))[::-1]
    for yi, (lab, v, col, mk) in zip(y, rows):
        ax.plot([0, v], [yi, yi], "-", color=col, lw=1.0, alpha=0.6)
        ax.plot(v, yi, mk, color=col, ms=4.6)
        ax.annotate(f"{v:.4f}", xy=(v, yi), xytext=(4, 0), textcoords="offset points", va="center", fontsize=6.6)
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows], fontsize=7.6)
    ax.set_xlabel(r"size in $C_Q$ (–)")
    ax.set_xlim(0, 0.0295)
    ax.set_xticks([0, 0.005, 0.01, 0.015, 0.02, 0.025])
    ax.grid(axis="y", visible=False)
    ax.set_title(r"Noise of a rough-minus-smooth $C_Q$ difference" "\n"
                 r"against the change the rig's gains imply", loc="left", fontsize=8.0)
    ax.text(0.0112, 1.5,
            "grey: 2u of the difference of\ntwo 3-revolution means\n"
            r"black: $|C_Q(\mathrm{maxCo}\ 2) - C_Q(\mathrm{maxCo}\ 4)|$," "\nλ 0.15, 23 m/s\n"
            r"orange: 12.8 % and 16.2 % of $C_Q$" "\nof A reversed at λ 0.10, 23 m/s",
            fontsize=6.4, color="#333333", ha="left", va="center", linespacing=1.25)
    fig.savefig(FIG / "rotor_resolution.png")
    plt.close(fig)


# ---------------------------------------------------------------- main
def main():
    style()
    FIG.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    st = pd.read_csv(DATA / "rotor_static.csv")
    rc = pd.read_csv(DATA / "rotor_cp.csv")
    static = analyse_static(st)
    drag_rule = {h: v["sense_drag_rule"] for h, v in static.items()}
    _, curves, decomp, tstep, quality = analyse_rotating(rc, drag_rule, static)
    rig = analyse_rig()

    # CFD against rig magnitudes at matching lambda (A reversed; B drag rule at 23 m/s)
    mag = {}
    for key in ("A_U10.2_CCW", "A_U23_CCW", "A_U38_CCW", "B_U23_CCW"):
        c = curves[key]
        rows = []
        for lam, cp in zip(c["lam"], c["CP"]):
            el, gi = rig_at(rig, c["U_ms"], lam)
            rows.append(dict(lam=lam, CP_cfd=cp, CP_el_rig=el, CP_gen_in_rig=gi,
                             ratio_cfd_to_el=r6(cp / el) if el else None,
                             ratio_cfd_to_gen_in=r6(cp / gi) if gi else None))
        mag[key] = rows

    # C_Q change implied by the rig's peak-power gains, applied to A reversed at lambda 0.10 (23 m/s)
    a23 = curves["A_U23_CCW"]
    i10 = a23["lam"].index(0.1)
    cq10 = a23["CQ"][i10]
    gains = {"FS 0.10": 0.128, "FS 0.20": 0.162}
    rig_gain = [(f"implied by rig, {k} (+{100 * g:.1f} %)", g * cq10) for k, g in gains.items()]
    res_rows = resolution_rows(quality, tstep, rig_gain)
    # revolutions to average per run so that 2u of a rough-minus-smooth difference (A, 23 m/s) is below
    # the implied change: 2 sqrt(2) sigma_rev / sqrt(n) < dC_Q
    s23 = quality["sigma_rev_pooled"]["A_U23"]["sigma_rev"]
    nrev_needed = {k: math.ceil((2 * math.sqrt(2) * s23 / (g * cq10)) ** 2) for k, g in gains.items()}

    # zero-torque lambda of A reversed at 23 m/s with the maxCo 2 value at lambda 0.15 instead
    t2 = [t for t in tstep if t["sense"] == "CCW" and abs(t["lam"] - 0.15) < 1e-9]
    if t2:
        c = curves["A_U23_CCW"]
        cq_alt = np.array(c["CQ"], float)
        cq_alt[c["lam"].index(0.15)] = t2[0]["CQ_Co2"]
        zc = zero_crossings(np.array(c["lam"]), cq_alt, np.array(c["u_CQ"], float))
        c["zero_torque_maxCo2"] = r6([z for z in zc if z["direction"] == "+ to -"][-1]["lam0"])

    numbers = dict(
        provenance="computed by cfd/analysis/2026-10-13/src/rotor_analysis.py from data/rotor_static.csv, "
                   "data/rotor_cp.csv and the rig CSVs (read only)",
        drag_rule_sense=drag_rule, static=static, curves=curves, sense_decomposition=decomp,
        time_step_check=tstep, quality=quality, rig=rig, cfd_vs_rig_magnitude=mag,
        roughness_signal=dict(CQ_A_reversed_lam010_U23=cq10,
                              implied_dCQ={k: r6(g * cq10) for k, g in gains.items()},
                              figure_rows={lab: r6(v) for lab, v, _, _ in res_rows},
                              noise_definition="averaging rows: 2u of a difference of two 3-revolution means",
                              nrev_averaged_per_run_needed_A_U23=nrev_needed),
    )
    (OUT / "rotor_numbers.json").write_text(json.dumps(numbers, indent=1, default=float))

    fig_static(st, static)
    fig_cp_u23(curves, tstep, rig)
    fig_cq_u23(curves, decomp, static, tstep)
    fig_by_speed(curves)
    fig_lambda_vs_U(curves, rig, tstep)
    fig_resolution(res_rows)

    # console summary
    for h, s in static.items():
        print(f"static {h}: mean {s['mean_over_theta_drag_rule_sense']:+.4f} (drag-rule {s['sense_drag_rule']}), "
              f"SEM_t {s['sem_time_of_mean']:.4f}, subsets {s['subset_means_30deg']}, "
              f"+{s['n_positive_drag_rule']}/-{s['n_negative_drag_rule']}, {s['verdict_2sem_time']}")
    for k, c in curves.items():
        zc = "; ".join(f"{z['lam0']:.4f}±{z['u_lam0']:.4f} ({z['direction']})" for z in c["zero_crossings"])
        print(f"{k:12s} {c['sense_kind']:9s} CQ {c['CQ']} u {c['u_CQ']}\n"
              f"{'':12s} CP {c['CP']} peak {c['peak']} zero {zc} lin {c['linear_CQ_fit']}"
              + (f" static {c.get('static_CQ_this_sense')} anchored {c.get('static_anchored_peak_inferred')}"
                 if 'static_CQ_this_sense' in c else ""))
    print("decomp", json.dumps(decomp, indent=0))
    print("tstep", json.dumps(tstep, indent=0))
    print("quality", json.dumps(quality, indent=0))
    print("mag", json.dumps(mag, indent=0))
    for U, runs in rig.items():
        print("rig", U, {k: {kk: v for kk, v in r.items() if kk != 'points'} for k, r in runs.items()})


if __name__ == "__main__":
    main()
