#!/usr/bin/env python3
"""Rotor stage, 15 Oct 2026 (cfd/rotor2d, 2D URANS): the 13 rotor cases added since 13 Oct.

    nice -n 10 python3 cfd/analysis/2026-10-15/src/rotor_analysis.py

Adapted from cfd/analysis/2026-10-13/src/rotor_analysis.py (13 Oct; that folder is not edited).
Kept from it: the static and production-curve analysis, the rig landmarks, the zero-crossing
and peak helpers, the figure style. Changed: the production filter (it now also requires the
medium mesh, smooth Spalding blades and the standard run length, because the new table holds
coarse/fine, rough and long runs that the 13 Oct filter would have let into the curves), and
the time-step check is limited to maxCo != 4. New: per-revolution torque from the force
histories, the rotor health check, the rough-blade long runs (priorityE), their phase-resolved
blade torque, the mesh check (priorityD) and the 38 m/s, lambda 0.30 run of 16 revolutions.

Inputs (read only)
  cfd/rotor2d/results/rotor_cp.csv       53 rotating cases (the 40 of 13 Oct, values unchanged,
                                         plus 13 new: priorityD_rerun 5, priorityE_rough 8)
  cfd/rotor2d/results/rotor_static.csv   16 static cases (unchanged since 13 Oct)
  cfd/rotor2d/runs/<case>/case.json, mesh_info.json, hpc_jobs.jsonl and
      postProcessing/forces{Rotor,Blade1,Blade2,Blade3}/0/moment.dat   (every rotating case)
  cfd/analysis/2026-10-13/data/rotor_cp.csv and out/rotor_numbers.json  (the 13 Oct case list
      and numbers, for the comparison only)
  reports/roughness_2026-09/build/tacho/derived/rotor_speed_by_dwell.csv,
  reports/roughness_2026-09/build/derived/rotor_speed_by_run.csv          (rig, as 13 Oct)
  reports/roughness_2026-09/build/derived/rotor_by_wind_speed.csv         (rig peak-power change at 23.03 m/s,
                                         for the same-speed band; added by the verifier, 19 Oct)
  cfd/stage2/results/stage2_polars.csv     (only the rough-wall-function rows at alpha 90 and 180,
                                            23 m/s, maxCo 2.5, for the physics link of the phase result)
  cfd/rotor2d/layout/poses_A_B.json        (blade centroid radius of assembly A)
Outputs
  ../out/rotor_health.csv, rotor_per_rev.csv, rotor_noise.csv, rotor_roughness.csv,
  rotor_roughness_phase.csv, rotor_roughness_sectors.csv, rotor_grid.csv, rotor_lambda0.csv,
  rotor_numbers.json
  ../fig/rotor_roughness_dCQ.png, rotor_roughness_phase.png, rotor_histories.png,
  rotor_grid.png, rotor_lambda_vs_U.png

Conventions (cfd/rotor2d/README.md). C_Q, C_P per unit span on the swept width 2R, R = 101.6 mm;
lambda = Omega R / U; C_Q > 0 drives the rotor in the case's sense. All new cases are assembly A
turning CCW in the model frame (curled tip B leading; 13 Oct 'A reversed').

Per-revolution means (computed here from forcesRotor moment.dat): the cumulative trapezoid
integral of C_Q(t), interpolated at the revolution boundaries k T, divided by T. The averaging
window is the case's last n_avg_rev revolutions, as in the table. Window means quoted as C_Q are
the table's values (time mean over the window, cfd/post/rotor_summary.py); the per-revolution
series give the scatter, drift and autocorrelation.

Uncertainty of a rotating mean u = s_rev / sqrt(n): s_rev is the standard deviation of the
revolution means in the window. For the 45-revolution runs each run's own s_rev (44 degrees of
freedom) is used; for the short runs (2-8 revolutions averaged), s_rev is pooled per hypothesis
and wind speed over the medium-mesh, smooth (Spalding), maxCo-4 runs, the long ones included
(this replaces the 13 Oct estimate from the last-two-revolution differences; both are printed).
It treats revolution means as independent (checked: lag-1 autocorrelation and batch means of the
long runs) and covers neither the mesh nor the time step. 2u = twice that. A difference is
'resolved' when it exceeds its 2u. Secondary checks: the Stage 2 drift rule (|change| >
|drift_a| + |drift_b|, drift = second-half minus first-half mean of the window, each half a whole
number of blade-passing periods T/3: the first and last floor(3 n/2) of them; fixed 19 Oct, the
earlier split at n T/2 cut a period and biased every drift negative) and the sign of the change
in the first and last 22 revolutions of the window.

Health check (the 13 Oct section flag, carried over to the rotor meshes): time-step proxy
u_Co/U = maxCo * ds_corner / (dt_mean * U) with ds_corner the mesh's corner wall spacing
(mesh_info.json), flagged above 5 (the section limit); the mean time step against the median of
the runs with the same hypothesis, mesh, speed and maxCo; and the symptoms that have a rotor
counterpart: negative mean streamwise force (C_x < 0), |C_y| > 3, omega bounding, AMI weight sums
outside 1 +- 1e-3, time-mean max Co above 1.01 maxCo, blade-mean y+ outside 11-300 (log-law
range of the wall functions) and C_Q std more than twice the median of its group.
"""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

HERE = Path(__file__).resolve().parent
BASE = HERE.parent                      # cfd/analysis/2026-10-15
REPO = BASE.parents[2]                  # repository root
FIG, OUT = BASE / "fig", BASE / "out"
RES = REPO / "cfd/rotor2d/results"
RUNS = REPO / "cfd/rotor2d/runs"
OCT13 = REPO / "cfd/analysis/2026-10-13"
STAGE2 = REPO / "cfd/stage2/results/stage2_polars.csv"
POSES = REPO / "cfd/rotor2d/layout/poses_A_B.json"
C_REF = 0.048                           # section reference chord (m), cfd/section2d/README.md
DWELL = REPO / "reports/roughness_2026-09/build/tacho/derived/rotor_speed_by_dwell.csv"
BYRUN = REPO / "reports/roughness_2026-09/build/derived/rotor_speed_by_run.csv"
# peak-power change of each FS rotor against Plain at each wind speed (measured, 1 Oct report); used for the
# same-speed (23 m/s) rig band added by the verifier on 19 Oct (fair comparison: the CFD runs are at 23 m/s)
BYSPEED = REPO / "reports/roughness_2026-09/build/derived/rotor_by_wind_speed.csv"
RHO_RIG = 1.204                         # as cfd/post/plot_rotor_cp.py and the rig's cp_el column
AREA_RIG = 2 * 0.1016 * 0.2451          # 2RH (m^2), the reports' swept area
# cases that ran on the Mac (13 Oct README); every rotating case and every new case ran on Unity
MAC_CASES = {"A_sta_U23.0_th000.0_SST_medium", "A_sta_U23.0_th030.0_SST_medium", "A_sta_U23.0_th060.0_SST_medium",
             "B_sta_U23.0_th000.0_SST_medium", "B_sta_U23.0_th060.0_SST_medium"}
# rig gains (measured, 1 Oct report: geometric mean over 10.2-38 m/s of the peak electrical power)
GAINS = {"FS 0.10": 0.128, "FS 0.20": 0.162}
# azimuth sectors of blade theta for assembly A turning CCW (blade at polar angle 180 + theta deg)
SECTORS = [("upwind, convex side to the wind", 330, 30), ("advancing, edge-on (tip A first)", 60, 120),
           ("downwind, cup to the wind", 150, 210), ("returning, edge-on (curl first)", 240, 300)]

# ---------------------------------------------------------------- style (13 Oct)
C_A, C_B = "#000000", "#7a7a7a"         # smooth blades: hypothesis A black, B grey
C_RIG = "#eb6834"                       # rig measurements (Plain rotor)
C_U = {10.2: "#a3a3a3", 23.0: "#5c5c5c", 38.0: "#000000"}
M_U = {10.2: "^", 23.0: "o", 38.0: "s"}
HYP_C = {"A": C_A, "B": C_B}
HYP_M = {"A": "o", "B": "s"}
RAMP = {50: "#86b6ef", 100: "#5598e7", 200: "#256abf", 400: "#184f95"}   # 13 Oct roughness ramp
C_WALL = {"spalding": "#000000", "Ks0": "#8c8c8c", "Ks100": RAMP[100], "Ks400": RAMP[400]}
LAB_WALL = {"spalding": "smooth, Spalding wall function (production)", "Ks0": "Ks 0, rough wall function",
            "Ks100": "Ks 100 µm", "Ks400": "Ks 400 µm"}
C_LVL = {"coarse": "#b3b3b3", "medium": "#000000", "fine": "#6b6b6b"}
M_LVL = {"coarse": "v", "medium": "o", "fine": "^"}


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


# ---------------------------------------------------------------- helpers (13 Oct)
def is_production(r):
    """Production settings of cfd/rotor2d/run_case.py, as 13 Oct, plus (new) the medium mesh,
    smooth Spalding blades and the standard run length (at most 3 revolutions averaged)."""
    return (r["freestream_decay"] == "control" and abs(r["Tu_rotor_pct"] - 1.0) < 1e-6
            and abs(r["lt_m"] - 1e-3) < 1e-9 and abs(r["maxCo"] - 4.0) < 1e-9 and int(r["nOuter"]) == 2
            and r["level"] == "medium" and pd.isna(r["Ks_um"]) and r["n_avg_rev"] <= 3 + 1e-6)


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


def last_down_crossing(lam, cq, u):
    z = [z for z in zero_crossings(np.asarray(lam, float), np.asarray(cq, float), np.asarray(u, float))
         if z["direction"] == "+ to -"]
    return z[-1] if z else None


def lin_fit(lam, cq):
    b, a = np.polyfit(lam, cq, 1)
    res = cq - (a + b * lam)
    d = dict(a=float(a), b=float(b), resid_rms=float(np.sqrt(np.mean(res ** 2))))
    if b < 0 and a > 0:
        d.update(lam0=float(-a / b), lam_peak=float(-a / (2 * b)), CP_max=float(-a * a / (4 * b)))
    return d


def r6(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(f"{x:.6g}")


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def wall_of(r):
    return "spalding" if pd.isna(r["Ks_um"]) else f"Ks{int(round(r['Ks_um']))}"


# ---------------------------------------------------------------- static (stage 3a, 13 Oct)
def analyse_static(st):
    res = {}
    for hyp, g in st.groupby("hypothesis"):
        g = g.sort_values("theta_deg")
        th, cq, sem, sd = (g[c].to_numpy(float) for c in ("theta_deg", "CQ_mean", "CQ_sem", "CQ_std"))
        assert len(th) == 8 and th[0] == 0 and np.allclose(np.diff(th), 15), "expected theta 0..105 step 15"
        mean = float(cq.mean())
        sem_t = float(np.sqrt(np.sum(sem ** 2)) / len(cq))
        sub_a, sub_b = float(cq[::2].mean()), float(cq[1::2].mean())
        res[hyp] = dict(sense_drag_rule=g["sense"].iloc[0], mean_over_theta_drag_rule_sense=r6(mean),
                        sem_time_of_mean=r6(sem_t), sampling_halfspread=r6(abs(sub_a - sub_b) / 2),
                        subset_means_30deg={"theta_0_30_60_90": r6(sub_a), "theta_15_45_75_105": r6(sub_b)})
    return res


# ---------------------------------------------------------------- rotating curves (13 Oct method)
def analyse_rotating(rc, drag_rule, static, sigma=None):
    """13 Oct curves. sigma: {(hyp, U): sigma_rev} to use instead of the 13 Oct estimate from the
    last-two-revolution differences of the production cases (None: the 13 Oct estimate)."""
    rc = rc.copy()
    rc["production"] = rc.apply(is_production, axis=1)
    rc["sense_kind"] = np.where(rc["sense"] == rc["hypothesis"].map(drag_rule), "drag rule", "reversed")
    sig13 = {}
    for (h, U), g in rc[rc.production].groupby(["hypothesis", "U_ms"]):
        d = g["CQ_drift_last_two_rev"].to_numpy(float)
        sig13[(h, float(U))] = float(math.sqrt(np.mean(d ** 2) / 2))
    sig = sig13 if sigma is None else sigma
    rc["u_CQ"] = [sig[(h, float(U))] / math.sqrt(n) for h, U, n in zip(rc.hypothesis, rc.U_ms, rc.n_avg_rev)]
    curves = {}
    for (h, U, sense), g in rc[rc.production].groupby(["hypothesis", "U_ms", "sense"]):
        g = g.sort_values("lam")
        lam, cq, cp, u = (g[c].to_numpy(float) for c in ("lam", "CQ_mean", "CP_mean", "u_CQ"))
        key = f"{h}_U{float(U):g}_{sense}"
        curves[key] = dict(hypothesis=h, U_ms=float(U), sense=sense, sense_kind=g["sense_kind"].iloc[0],
                           cases=g["name"].tolist(), lam=lam.tolist(), CQ=[r6(v) for v in cq],
                           CP=[r6(v) for v in cp], u_CQ=[r6(v) for v in u], n_avg_rev=g["n_avg_rev"].tolist(),
                           zero_crossings=zero_crossings(lam, cq, u), peak=peak_of(lam, cp),
                           linear_CQ_fit=lin_fit(lam, cq))
    tstep = []
    for _, r in rc[~rc.production & (np.abs(rc.maxCo - 4.0) > 1e-9) & (rc.level == "medium")].iterrows():
        m = rc[rc.production & (rc.hypothesis == r.hypothesis) & (rc.U_ms == r.U_ms) & (rc.sense == r.sense)
               & (np.abs(rc.lam - r.lam) < 1e-9)]
        if len(m) != 1:
            continue
        p = m.iloc[0]
        dq = float(r.CQ_mean - p.CQ_mean)
        tstep.append(dict(case_Co4=p["name"], case_Co2=r["name"], sense=r.sense, lam=float(r.lam),
                          CQ_Co4=r6(p.CQ_mean), CQ_Co2=r6(r.CQ_mean), dCQ=r6(dq),
                          dCQ_over_u_diff=r6(dq / math.hypot(p.u_CQ, r.u_CQ)),
                          dt_mean_Co4=r6(p.dt_mean_s), dt_mean_Co2=r6(r.dt_mean_s)))
    return rc, curves, tstep, {f"{h}_U{U:g}": r6(v) for (h, U), v in sig13.items()}


# ---------------------------------------------------------------- rig (13 Oct)
def drop_stall(g):
    """Load steps in demand order; from the first step whose lambda falls below 0.8 x the previous
    valid step's, the rotor was stalling (only at 35.8 m/s), so that step and every later one are
    dropped."""
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
    rig = {}
    for (U, run), g in dw.groupby(["U", "run"]):
        g, n_stall = drop_stall(g)
        g = g.sort_values("tip_speed_ratio")
        lam = g.tip_speed_ratio.to_numpy(float)
        pe = peak_of(lam, g.cp_el.to_numpy(float))
        rig.setdefault(f"{U:g}", {})[f"run{run}"] = dict(
            U_ms=float(g.wind_mps.iloc[0]), n_steps=int(len(g)), n_stall_steps_dropped=n_stall,
            lam_max_loaded=float(lam.max()), lam_peak_cp_el=r6(pe["lam_peak"]))
    return rig


# ---------------------------------------------------------------- force histories (new)
def read_moment(case, fo="forcesRotor"):
    """t, total M_z, pressure M_z from postProcessing/<fo>/0/moment.dat (no restarts in any rotor
    case: each has the single time folder 0, checked)."""
    root = RUNS / case / "postProcessing" / fo
    dirs = [d.name for d in root.iterdir() if d.is_dir()]
    assert dirs == ["0"], f"{case} {fo}: time folders {dirs}"
    a = np.loadtxt(root / "0" / "moment.dat", comments="#", usecols=(0, 3, 6))
    _, idx = np.unique(a[:, 0], return_index=True)
    return a[np.sort(idx)]


def cumint(t, y):
    return np.concatenate([[0.0], np.cumsum(0.5 * (y[1:] + y[:-1]) * np.diff(t))])


def rev_history(case):
    P = json.loads((RUNS / case / "case.json").read_text())
    a = read_moment(case)
    t = a[:, 0]
    k = P["sense"] / P["dz"] / (P["qRef"] * P["Aref"] * P["R"])
    cq, cqp = k * a[:, 1], k * a[:, 2]
    T = P["Trev"]
    nr = int(round(t[-1] / T))
    assert abs(t[-1] / T - nr) < 1e-6, (case, t[-1] / T)
    b = np.arange(nr + 1) * T
    b[0], b[-1] = t[0], t[-1]
    I = cumint(t, cq)
    Ib = np.interp(b, t, I)
    return dict(P=P, t=t, cq=cq, cqp=cqp, I=I, T=T, nr=nr, rev=np.diff(Ib) / np.diff(b))


def window_stats(h, nav):
    """Scatter, drift and autocorrelation of the last nav revolution means of a history."""
    w = h["rev"][-nav:]
    n = len(w)
    out = dict(n_avg=n, CQ_win_from_revs=float(w.mean()))
    t, I, T = h["t"], h["I"], h["T"]
    t1 = t[-1]
    t0 = t1 - nav * T
    # Halves of whole blade-passing periods (T/3, three blades). Splitting at nav*T/2 cuts a period
    # in two when 3*nav is odd (nav 45: 67.5 periods; nav 3: 4.5) and biases every drift by the
    # 3-per-revolution torque cycle (about -0.0005 to -0.0009 in C_Q for the 45-revolution runs;
    # verifier, 19 Oct). Each half is the first / last floor(3 nav / 2) periods of the window, so
    # one third of a revolution in the middle is left out when 3*nav is odd (nav 2 and 8: exact halves).
    th = ((3 * nav) // 2) * T / 3
    Ia, Ib, Ic, Id = np.interp([t0, t0 + th, t1 - th, t1], t, I)
    out["drift_half"] = float((Id - Ic) / th - (Ib - Ia) / th)
    out["drift_last_two_rev"] = float(h["rev"][-1] - h["rev"][-2])
    if n >= 2:
        sd = float(w.std(ddof=1))
        out.update(s_rev=sd, u_iid=sd / math.sqrt(n))
    if n >= 4:
        x = w - w.mean()
        out["lag1_autocorr"] = float(np.sum(x[:-1] * x[1:]) / np.sum(x * x))
        kk = np.arange(n, dtype=float)
        b1, b0 = np.polyfit(kk, w, 1)
        res = w - (b0 + b1 * kk)
        se = math.sqrt(np.sum(res ** 2) / (n - 2) / np.sum((kk - kk.mean()) ** 2))
        out.update(trend_over_window=float(b1 * (n - 1)), u_trend_over_window=float(se * (n - 1)))
    if n == 45:
        bm = w.reshape(9, 5).mean(axis=1)
        out["u_batch_9x5"] = float(bm.std(ddof=1) / 3.0)
        h1, h2 = w[:22], w[23:]
        out.update(mean_first22=float(h1.mean()), mean_last22=float(h2.mean()))
    return out


def phase_bins(case, nb=36):
    """Single-blade C_Q against blade azimuth, three blades averaged: per-revolution bin means over the
    averaging window, shape (n_avg, nb). Each bin mean is the time integral of the blade's C_Q (cumulative
    trapezoid, interpolated at the instants the blade crosses the bin edges) over the bin's duration, so the
    mean over the bins of a revolution is exactly one third of that revolution's rotor C_Q. Blade k sits at
    theta_1 + 120 (k - 1) with theta_1 = Omega t (+ thetaDeg, 0 for every case)."""
    P = json.loads((RUNS / case / "case.json").read_text())
    k = P["sense"] / P["dz"] / (P["qRef"] * P["Aref"] * P["R"])
    T, nav = P["Trev"], int(P["nAvgRev"])
    assert abs(P.get("thetaDeg", 0.0)) < 1e-12
    blades = [read_moment(case, f"forcesBlade{i}") for i in (1, 2, 3)]
    rot = read_moment(case)
    t = blades[0][:, 0]
    assert all(len(b) == len(t) and np.allclose(b[:, 0], t) for b in blades) and np.allclose(rot[:, 0], t)
    assert np.max(np.abs(sum(b[:, 1] for b in blades) - rot[:, 1])) < 1e-6 * np.max(np.abs(rot[:, 1]))
    nr = int(round(t[-1] / T))
    dtb = T / nb                                       # time a blade spends in one bin
    out = np.zeros((nav, nb))
    for i, b in enumerate(blades):
        I = cumint(t, k * b[:, 1])
        for j, rr in enumerate(range(nr - nav, nr)):
            # blade i is at azimuth 360 m / nb when theta_1 = 360 m / nb - 120 i (mod 360)
            start = np.mod(np.arange(nb) * 360.0 / nb - 120.0 * i, 360.0) / 360.0 * T + rr * T
            ta = np.clip(start, t[0], t[-1])
            tb = np.clip(start + dtb, t[0], t[-1])
            out[j] += (np.interp(tb, t, I) - np.interp(ta, t, I)) / (tb - ta)
    edges = np.linspace(0, 360, nb + 1)
    return 0.5 * (edges[1:] + edges[:-1]), out / 3.0


def sector_mask(mid, lo, hi):
    return ((mid >= lo) | (mid < hi)) if lo > hi else ((mid >= lo) & (mid < hi))


# ---------------------------------------------------------------- health (new)
def health(st, rc):
    rows = []
    for kind, d in (("static", st), ("rotating", rc)):
        d = d.copy()
        ds = []
        for nm in d["name"]:
            mi = json.loads((RUNS / nm / "mesh_info.json").read_text())
            ds.append(mi["params"]["ds_corner"])
        d["ds_corner_m"] = ds
        d["u_co_over_U"] = d.maxCo * d.ds_corner_m / (d.dt_mean_s * d.U_ms)
        grp = ["hypothesis", "level", "U_ms", "maxCo"]
        d["dt_over_group_median"] = d.dt_mean_s / d.groupby(grp)["dt_mean_s"].transform("median")
        d["CQ_std_over_group_median"] = d.CQ_std / d.groupby(grp)["CQ_std"].transform("median")
        d["sym_neg_Cx"] = d.Cx_mean < 0
        d["sym_Cy_gt3"] = d.Cy_mean.abs() > 3
        d["sym_omega_bounded"] = d.omega_bounded_steps > 0
        d["sym_ami"] = (d.ami_weight_min < 1 - 1e-3) | (d.ami_weight_max > 1 + 1e-3)
        d["sym_Co"] = d.Co_max_mean > 1.01 * d.maxCo
        d["sym_yplus"] = (d.yplus_mean < 11) | (d.yplus_mean > 300) | (d.yplus_max > 300)
        d["sym_CQ_std"] = d.CQ_std_over_group_median > 2
        sym = [c for c in d.columns if c.startswith("sym_")]
        d["any_symptom"] = d[sym].any(axis=1)
        d["flagged"] = d.u_co_over_U > 5.0
        d["kind"] = kind
        d["new_since_13oct"] = False
        rows.append(d[["name", "kind", "hypothesis", "level", "U_ms", "maxCo", "ds_corner_m", "dt_mean_s",
                       "u_co_over_U", "dt_over_group_median", "Co_max_mean", "omega_bounded_steps",
                       "ami_weight_min", "ami_weight_max", "yplus_mean", "yplus_max", "Cx_mean", "Cy_mean",
                       "CQ_std", "CQ_std_over_group_median", *sym, "any_symptom", "flagged", "new_since_13oct"]])
    return pd.concat(rows, ignore_index=True)


# ---------------------------------------------------------------- figures (new)
def fig_roughness_dcq(long_tab, diffs, band, band23=None):
    fig, (ax, bx) = plt.subplots(2, 1, figsize=(3.6, 6.1), gridspec_kw=dict(height_ratios=[1, 1.15]))
    walls = ["spalding", "Ks0", "Ks100", "Ks400"]
    dx = {"spalding": -0.0027, "Ks0": -0.0009, "Ks100": 0.0009, "Ks400": 0.0027}
    for wl in walls:
        g = long_tab[long_tab.wall == wl].sort_values("lam")
        col = C_WALL[wl]
        mfc = "white" if wl == "Ks0" else col
        ax.errorbar(g.lam + dx[wl], g.CQ_mean, yerr=2 * g.u_own, fmt="o", color=col, mfc=mfc, mec=col, ms=4.6,
                    elinewidth=0.9, capsize=2.0, mew=1.1, label=LAB_WALL[wl], zorder=3)
    ax.set_xlim(0.0915, 0.1285)
    ax.set_xticks([0.10, 0.12])
    ax.set_ylim(0.0085, 0.0345)
    ax.set_ylabel(r"$C_Q$, mean of 45 revolutions (–)")
    ax.set_xlabel(r"tip-speed ratio $\lambda$ (–)")
    ax.legend(loc="upper center", fontsize=6.4, handlelength=1.0, borderaxespad=0.1, ncol=2, columnspacing=0.8,
              title="bars: ±2u from the revolution scatter of each run", title_fontsize=6.4)
    ax.set_title("(a) A, CCW, 23 m/s, medium mesh, maxCo 4, SST", loc="left", fontsize=8.2)

    order = [("Ks100", "Ks0"), ("Ks400", "Ks0"), ("Ks0", "spalding")]
    width = 0.0042
    off = {("Ks100", "Ks0"): -width, ("Ks400", "Ks0"): 0.0, ("Ks0", "spalding"): width}
    bx.axhspan(band[0], band[1], color=C_RIG, alpha=0.30, lw=0, zorder=1)
    if band23 is not None:   # same-speed band, its two edges dashed (verifier, 19 Oct)
        for yb in band23:
            bx.axhline(yb, color=C_RIG, lw=0.9, ls=(0, (3, 2)), zorder=1)
    for (a, b) in order:
        for lam in (0.10, 0.12):
            d = diffs[(lam, a, b)]
            x = lam + off[(a, b)]
            if b == "Ks0":
                col, hatch, ec = C_WALL[a], None, C_WALL[a]
            else:
                col, hatch, ec = "white", "////", "#555555"
            bx.bar(x, d["dCQ"], width=width * 0.92, color=col, edgecolor=ec, hatch=hatch, lw=0.7, zorder=2)
            bx.errorbar(x, d["dCQ"], yerr=d["two_u"], fmt="none", ecolor="#222222", elinewidth=0.9, capsize=2.0,
                        zorder=3)
            ytxt = d["dCQ"] + d["two_u"] if d["dCQ"] >= 0 else d["dCQ"] - d["two_u"]
            bx.annotate(minus(f"{d['dCQ']:+.4f}"), xy=(x, ytxt), xytext=(0, 2 if d["dCQ"] >= 0 else -2),
                        textcoords="offset points", ha="center", va="bottom" if d["dCQ"] >= 0 else "top",
                        fontsize=6.3, rotation=90, color="#111111",
                        bbox=dict(boxstyle="square,pad=0.05", fc="white", ec="none"), zorder=4)
    bx.axhline(0, color="#333333", lw=0.6, zorder=2)
    bx.set_xlim(0.0915, 0.1285)
    bx.set_xticks([0.10, 0.12])
    bx.set_ylim(-0.0118, 0.0145)
    bx.set_xlabel(r"tip-speed ratio $\lambda$ (–)")
    bx.set_ylabel(r"$\Delta C_Q$ (–)")
    h = [Patch(facecolor=C_WALL["Ks100"], edgecolor=C_WALL["Ks100"], label="Ks 100 µm − Ks 0"),
         Patch(facecolor=C_WALL["Ks400"], edgecolor=C_WALL["Ks400"], label="Ks 400 µm − Ks 0"),
         Patch(facecolor="white", edgecolor="#555555", hatch="////",
               label="wall-function change: Ks 0 − Spalding"),
         Line2D([], [], color="#222222", marker="|", ms=7, lw=0, mew=0.9, label="±2u of the difference"),
         # names the speed-averaged gains, so the band and the dashed 23 m/s lines read as two mappings of one
         # measurement (verifier 2, 19 Oct)
         Patch(facecolor=C_RIG, alpha=0.30, lw=0,
               label=f"implied by the rig's gains over 10.2–38 m/s (+{100 * GAINS['FS 0.10']:.1f} %, "
                     f"+{100 * GAINS['FS 0.20']:.1f} %):\n+{band[0]:.4f} to +{band[1]:.4f} (assumed, order of magnitude)")]
    bx.legend(handles=h, loc="upper left", bbox_to_anchor=(-0.17, -0.2), fontsize=6.4, handlelength=1.5,
              borderaxespad=0.0, ncol=2, columnspacing=0.9)
    lg_ = bx.get_legend()
    # the last entry spans both columns: move it to its own row by re-creating the legend in two parts
    lg_.remove()
    l1 = bx.legend(handles=h[:4], loc="upper left", bbox_to_anchor=(-0.17, -0.2), fontsize=6.4, handlelength=1.5,
                   borderaxespad=0.0, ncol=2, columnspacing=0.9)
    bx.add_artist(l1)
    if band23 is not None:
        h.append(Patch(facecolor="none", edgecolor=C_RIG, lw=0.9, ls=(0, (3, 2)),
                       label=f"the same, gains at 23 m/s only (+21.2 %, +36.2 %): "
                             f"+{band23[0]:.4f} to +{band23[1]:.4f}"))
    bx.legend(handles=h[4:], loc="upper left", bbox_to_anchor=(-0.17, -0.335), fontsize=6.4, handlelength=1.5,
              borderaxespad=0.0)
    bx.set_title("(b) change of the 45-revolution mean torque", loc="left", fontsize=8.2)
    fig.subplots_adjust(hspace=0.40)
    fig.savefig(FIG / "rotor_roughness_dCQ.png")
    plt.close(fig)


def fig_roughness_phase(phase, sect):
    fig, axs = plt.subplots(3, 1, figsize=(3.6, 7.3), gridspec_kw=dict(height_ratios=[1.05, 1, 0.95]))
    ax, bx, cx = axs
    mid = phase["mid"]
    for a in (ax, bx):
        for _, lo, hi in SECTORS:
            if lo > hi:
                a.axvspan(lo, 360, color="#f1f1f1", lw=0, zorder=0)
                a.axvspan(0, hi, color="#f1f1f1", lw=0, zorder=0)
            else:
                a.axvspan(lo, hi, color="#f1f1f1", lw=0, zorder=0)
    for wl in ("Ks0", "Ks400"):
        m = phase[(0.10, wl)].mean(axis=0)
        ax.plot(mid, m, "-", color=C_WALL[wl], lw=1.3 if wl == "Ks400" else 1.1,
                label=LAB_WALL[wl] if wl != "Ks0" else "Ks 0 (rough wall function)")
    ax.axhline(0, color="#333333", lw=0.6)
    ax.set_xlim(0, 360)
    ax.set_xticks(range(0, 361, 60))
    ax.set_ylabel(r"single-blade $C_Q$ (–)")
    ax.set_ylim(-0.24, 0.33)
    for lab, lo, hi in SECTORS:
        short = lab.split(",")[0]
        if lo > hi:
            ax.annotate(short, xy=(345, 0.30), fontsize=6.2, ha="center", va="center", color="#555555")
            ax.annotate(short, xy=(3, 0.30), fontsize=6.2, ha="left", va="center", color="#555555")
        else:
            ax.annotate(short, xy=(0.5 * (lo + hi), 0.30), fontsize=6.2, ha="center", va="center", color="#555555")
    ax.legend(loc="lower left", fontsize=6.4, handlelength=1.6, borderaxespad=0.2)
    ax.set_title(r"(a) one blade's torque against its azimuth, $\lambda$ 0.10", loc="left", fontsize=8.2)

    for lam, ls, alpha in ((0.10, "-", 0.20), (0.12, "--", 0.10)):
        a0, a1 = phase[(lam, "Ks0")], phase[(lam, "Ks400")]
        d = a1.mean(axis=0) - a0.mean(axis=0)
        u = np.sqrt(a1.var(axis=0, ddof=1) / len(a1) + a0.var(axis=0, ddof=1) / len(a0))
        bx.fill_between(mid, d - 2 * u, d + 2 * u, color=RAMP[400], alpha=alpha, lw=0)
        bx.plot(mid, d, ls, color=RAMP[400], lw=1.2, label=rf"$\lambda$ {lam:.2f}")
    bx.axhline(0, color="#333333", lw=0.6)
    bx.set_xlim(0, 360)
    bx.set_xticks(range(0, 361, 60))
    bx.set_ylim(-0.062, 0.052)
    bx.set_xlabel(r"blade azimuth $\theta$ (deg); 0 = upwind, 90 = moving downwind")
    bx.set_ylabel(r"$\Delta$ single-blade $C_Q$ (–)")
    bx.legend(loc="lower left", fontsize=6.4, handlelength=1.8, borderaxespad=0.2, ncol=2,
              title="Ks 400 µm − Ks 0; band ±2u", title_fontsize=6.4, alignment="left")
    bx.set_title("(b) change with roughness against azimuth", loc="left", fontsize=8.2)

    names = [s[0] for s in SECTORS] + ["the four 30° gaps between"]
    y = np.arange(len(names))[::-1]
    for lam, dy, fc in ((0.10, 0.17, RAMP[400]), (0.12, -0.17, "white")):
        vals = [sect[(lam, "Ks400", "Ks0", nm)] for nm in names]
        bx_v = np.array([v["d"] for v in vals])
        bx_u = np.array([v["two_u"] for v in vals])
        cx.barh(y + dy, bx_v, height=0.32, color=fc, edgecolor=RAMP[400], lw=0.8, label=rf"$\lambda$ {lam:.2f}")
        cx.errorbar(bx_v, y + dy, xerr=bx_u, fmt="none", ecolor="#222222", elinewidth=0.8, capsize=1.8)
    cx.axvline(0, color="#333333", lw=0.6)
    cx.set_yticks(y)
    cx.set_yticklabels(["upwind (330–30°),\nconvex side to wind", "advancing (60–120°),\nedge-on, tip A first",
                        "downwind (150–210°),\ncup to wind", "returning (240–300°),\nedge-on, curl first",
                        "the four 30° gaps"], fontsize=6.6)
    cx.grid(axis="y", visible=False)
    cx.set_xlabel(r"contribution to rotor $\Delta C_Q$, Ks 400 µm − Ks 0 (–)")
    cx.set_xlim(-0.0085, 0.0115)
    cx.set_xticks([-0.005, 0.0, 0.005, 0.010])
    cx.set_xticklabels([minus(f"{v:+.3f}") if v else "0" for v in (-0.005, 0.0, 0.005, 0.010)])
    cx.legend(loc="lower right", fontsize=6.4, handlelength=1.2, borderaxespad=0.2, title="bars ±2u",
              title_fontsize=6.4)
    cx.set_title("(c) where the torque change comes from", loc="left", fontsize=8.2)
    fig.subplots_adjust(hspace=0.48)
    fig.savefig(FIG / "rotor_roughness_phase.png")
    plt.close(fig)


def fig_histories(hist, long_tab, r38):
    fig, axs = plt.subplots(3, 1, figsize=(3.6, 7.0), gridspec_kw=dict(height_ratios=[1, 1, 1]))
    for ax, lam in zip(axs[:2], (0.10, 0.12)):
        for wl in ("spalding", "Ks0", "Ks100", "Ks400"):
            row = long_tab[(long_tab.wall == wl) & (np.abs(long_tab.lam - lam) < 1e-9)].iloc[0]
            h = hist[row["name"]]
            w = h["rev"][-45:]
            k = np.arange(6, 51)
            run = np.cumsum(w) / np.arange(1, 46)
            col = C_WALL[wl]
            ax.plot(k, w, ".", color=col, ms=2.2, alpha=0.45, zorder=2)
            ax.plot(k, run, "-", color=col, lw=1.3, zorder=3, label=LAB_WALL[wl] if wl != "spalding" else
                    "smooth, Spalding")
            ax.errorbar(51.6 + {"spalding": 0, "Ks0": 0.7, "Ks100": 1.4, "Ks400": 2.1}[wl], row["CQ_mean"],
                        yerr=2 * row["u_own"], fmt="o", color=col, mfc=col if wl != "Ks0" else "white", ms=3.4,
                        elinewidth=0.9, capsize=1.6, zorder=4)
        ax.axhline(0, color="#333333", lw=0.6)
        ax.set_xlim(4.5, 54.6)
        ax.set_ylim(-0.014, 0.041)
        ax.set_ylabel(r"$C_Q$ (–)")
        ax.set_title(rf"({'a' if lam < 0.11 else 'b'}) 23 m/s, $\lambda$ {lam:.2f}: dots, each revolution; "
                     "lines, running mean", loc="left", fontsize=7.6)
        if lam < 0.11:
            ax.legend(loc="lower center", fontsize=6.2, ncol=2, handlelength=1.4, borderaxespad=0.1,
                      columnspacing=0.9)
    axs[1].set_xlabel("revolution (averaging window: 6–50; right: window mean ±2u)")
    cx = axs[2]
    for key, col, mfc, lab in (("rev8", "#8c8c8c", "white", "8 revolutions (13 Oct)"),
                               ("rev16", "#000000", "#000000", "16 revolutions (new)")):
        r = r38[key]
        k = np.arange(1, len(r["rev"]) + 1)
        cx.plot(k, r["rev"], "o-", color=col, mfc=mfc, mec=col, ms=3.6, lw=0.9, label=lab, zorder=3)
        n = r["n_avg"]
        cx.plot([k[-n] - 0.5, k[-1] + 0.5], [r["CQ_mean"]] * 2, "-", color=col, lw=2.2, alpha=0.55, zorder=2)
    cx.annotate(minus(f"13 Oct: last two revolutions\ndiffer by {r38['rev8']['drift_last_two_rev']:+.4f}"),
                xy=(7.8, r38["rev8"]["rev"][-1]), xytext=(1.0, -0.022), fontsize=6.3, ha="left", va="center",
                arrowprops=dict(arrowstyle="-", lw=0.7, color="#555555", relpos=(1.0, 0.5), shrinkB=3))
    cx.set_xlim(0.3, 16.7)
    cx.set_ylim(-0.105, -0.012)
    cx.set_xticks(range(1, 17))
    cx.tick_params(axis="x", labelsize=7)
    cx.set_xlabel("revolution (thick lines: window means, last 3 and last 8)")
    cx.set_ylabel(r"$C_Q$ (–)")
    cx.legend(loc="lower right", fontsize=6.4, handlelength=1.6, borderaxespad=0.2)
    cx.set_title(r"(c) 38 m/s, $\lambda$ 0.30, A CCW: per-revolution means", loc="left", fontsize=7.6)
    fig.subplots_adjust(hspace=0.55)
    fig.savefig(FIG / "rotor_histories.png")
    plt.close(fig)


def fig_grid(grid_curves, lam0_rows, rig23):
    fig, (ax, bx) = plt.subplots(2, 1, figsize=(3.6, 5.9), gridspec_kw=dict(height_ratios=[1.25, 1]))
    lo, hi = rig23
    ax.axvspan(lo, hi, color=C_RIG, alpha=0.35, lw=0, zorder=1)
    ax.annotate(f"rig light-load λ\n{lo:.3f}–{hi:.3f}", xy=(lo, 0.054), xytext=(-3, 0), textcoords="offset points",
                fontsize=6.3, color="#8a3a12", va="center", ha="right")
    # offsets 0.0045 / 0.0095 / 0.0075 (were 0.0035 / 0.0065 / 0.0065: the coarse marker at lambda 0.10 was hidden
    # behind the medium marker and the 45-revolution diamond; verifier, 19 Oct)
    dxl = {"coarse": -0.0045, "medium": 0.0, "fine": 0.0045}
    for lvl in ("coarse", "medium", "fine"):
        c = grid_curves[lvl]
        lam, cq, u = np.array(c["lam"]), np.array(c["CQ"]), np.array(c["u"])
        col, mk = C_LVL[lvl], M_LVL[lvl]
        ax.errorbar(lam + dxl[lvl], cq, yerr=2 * u, fmt=mk + "-", color=col, mfc=col, mec=col, ms=4.4, lw=1.1,
                    elinewidth=0.8, capsize=1.8, label=f"{lvl}, {c['cells']:,} cells", zorder=3)
    co2 = grid_curves["medium_maxCo2"]
    ax.errorbar(0.15 + 0.0075, co2["CQ"], yerr=2 * co2["u"], fmt="x", color=C_A, ms=5, mew=1.1, elinewidth=0.8,
                capsize=1.8, label="medium, maxCo 2 (λ 0.15)", zorder=4)
    lg = grid_curves["medium_long"]
    ax.errorbar(np.array(lg["lam"]) - np.where(np.abs(np.array(lg["lam"]) - 0.10) < 1e-9, 0.0095, 0.0), lg["CQ"],
                yerr=2 * np.array(lg["u"]), fmt="D", color=C_A,
                mfc="white", mec=C_A, ms=3.6, elinewidth=0.8, capsize=1.6, label="medium, 45 revolutions", zorder=4)
    ax.axhline(0, color="#333333", lw=0.6, zorder=2)
    ax.set_xlim(0.035, 0.265)
    ax.set_ylim(-0.047, 0.062)
    ax.set_xlabel(r"tip-speed ratio $\lambda$ (–)")
    ax.set_ylabel(r"$C_Q$ (–)")
    # the lambda offsets above are disclosed in the legend title: on a lambda axis an undisclosed shift of up to
    # 0.0095 put the lambda-0.10 diamond at 0.09 and the lambda-0.15 cross inside the rig band (verifier 2, 19 Oct)
    ax.legend(loc="upper right", fontsize=6.2, handlelength=1.6, borderaxespad=0.1,
              title="bars ±2u; last 3 revolutions\naveraged unless noted; markers\nshifted ≤ 0.01 in λ for legibility",
              title_fontsize=6.1, alignment="left")
    ax.set_title("(a) A, CCW, 23 m/s, SST, wall functions, maxCo 4", loc="left", fontsize=8.0)

    labels = [r["label"] for r in lam0_rows]
    x = np.arange(len(labels))
    bx.axhspan(lo, hi, color=C_RIG, alpha=0.35, lw=0, zorder=1)
    for xi, r in zip(x, lam0_rows):
        col = C_LVL.get(r["level"], C_A)
        mk = M_LVL.get(r["level"], "x")
        if r.get("lam0_tab") is not None:
            bx.errorbar(xi - 0.12, r["lam0_tab"], yerr=r["two_u_tab"], fmt=mk, color=col, mfc=col, mec=col, ms=5,
                        elinewidth=0.9, capsize=2.0, zorder=3)
            bx.annotate(f"{r['lam0_tab']:.3f}", xy=(xi - 0.12, r["lam0_tab"] - r["two_u_tab"]), xytext=(0, -2),
                        textcoords="offset points", fontsize=5.9, ha="center", va="top")
        if r.get("lam0_ext") is not None:
            bx.errorbar(xi + 0.12, r["lam0_ext"], yerr=r["two_u_ext"], fmt=mk, color=col, mfc="white", mec=col,
                        ms=5, elinewidth=0.9, capsize=2.0, zorder=3)
            bx.annotate(f"{r['lam0_ext']:.3f}", xy=(xi + 0.12, r["lam0_ext"] + r["two_u_ext"]), xytext=(0, 2),
                        textcoords="offset points", fontsize=5.9, ha="center", va="bottom")
    bx.set_xticks(x)
    bx.set_xticklabels(labels, fontsize=6.8)
    bx.grid(axis="x", visible=False)
    bx.set_xlim(-0.6, len(x) - 0.4)
    bx.set_ylim(0.095, 0.180)
    bx.set_ylabel(r"zero-torque $\lambda$ (–)")
    h = [Line2D([], [], color="#555555", marker="o", ms=4.5, lw=0, label="window of the table (last 3 revolutions)"),
         Line2D([], [], color="#555555", marker="o", mfc="white", ms=4.5, lw=0,
                label="revolutions 3–8 (3–6 at λ 0.10)"),
         Patch(facecolor=C_RIG, alpha=0.35, lw=0, label=f"rig light-load λ {lo:.3f}–{hi:.3f} (lower bound)")]
    bx.legend(handles=h, loc="lower right", fontsize=6.2, handlelength=1.2, borderaxespad=0.2,
              title="bars ±2u", title_fontsize=6.2, alignment="left")
    bx.set_title("(b) zero-torque λ, 23 m/s, by mesh and window", loc="left", fontsize=8.2)
    fig.subplots_adjust(hspace=0.36)
    fig.savefig(FIG / "rotor_grid.png")
    plt.close(fig)


def fig_lambda_vs_U(lam0_speed, lam0_mesh23, rig):
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
    for U, r in lam0_speed.items():
        ax.errorbar(U, r["lam0"], yerr=r["two_u"], fmt="s", color=C_A, ms=4.6, elinewidth=1.0, capsize=2.2, zorder=5)
        if r.get("lam0_ext") is not None:
            ax.errorbar(U + 0.9, r["lam0_ext"], yerr=r["two_u_ext"], fmt="s", color=C_A, mfc="white", mec=C_A,
                        ms=4.2, elinewidth=0.8, capsize=1.8, zorder=5)
    for lvl, dxx in (("coarse", -1.5), ("fine", -0.75)):
        r = lam0_mesh23[lvl]
        ax.errorbar(23.0 + dxx, r["lam0"], yerr=r["two_u"], fmt=M_LVL[lvl], color=C_LVL[lvl], mfc=C_LVL[lvl],
                    mec=C_LVL[lvl] if lvl == "fine" else "#7a7a7a", ms=4.6, elinewidth=0.9, capsize=2.0, zorder=5)
    r = lam0_mesh23["medium_maxCo2"]
    # with its +-2u bar, like every other CFD marker (the bar was missing; verifier, 19 Oct)
    ax.errorbar(23.0 + 1.8, r["lam0"], yerr=r["two_u"], fmt="x", color=C_A, ms=4.6, mew=1.1, elinewidth=0.8,
                capsize=1.8, zorder=5)
    ax.set_xlabel("wind speed U (m/s)")
    ax.set_ylabel(r"tip-speed ratio $\lambda$ (–)")
    ax.set_xlim(8, 40)
    ax.set_ylim(0.065, 0.225)
    h = [Line2D([], [], color=C_RIG, marker="^", ms=3.4, lw=1.0, mew=0.9,
                label="rig: light-load λ (zero-torque λ lies above)"),
         Line2D([], [], color=C_RIG, marker="o", mfc="white", ms=3.4, lw=1.0, alpha=0.75,
                label=r"rig: λ at peak $C_{P,\mathrm{el}}$"),
         Line2D([], [], color=C_A, marker="s", ms=4.6, lw=0, label="CFD zero-torque λ, medium mesh (±2u)"),
         Line2D([], [], color=C_A, marker="s", mfc="white", ms=4.2, lw=0,
                label="the same, revolution 3 to the end averaged (+0.9 m/s)"),
         Line2D([], [], color=C_LVL["fine"], marker=M_LVL["fine"], ms=4.6, lw=0,
                label="23 m/s, fine mesh (−0.75 m/s)"),
         Line2D([], [], color=C_LVL["coarse"], marker=M_LVL["coarse"], mec="#7a7a7a", ms=4.6, lw=0,
                label="23 m/s, coarse mesh (−1.5 m/s)"),
         Line2D([], [], color=C_A, marker="x", ms=4.6, mew=1.1, lw=0,
                label="23 m/s, medium, maxCo 2 at λ 0.15 (+1.8 m/s)")]
    fig.legend(handles=h, loc="upper center", bbox_to_anchor=(0.53, 0.0), ncol=1, fontsize=6.4, handlelength=1.8,
               labelspacing=0.35)
    ax.set_title("A, CCW (curled tip leading), SST, maxCo 4 unless noted", loc="left", fontsize=7.8)
    fig.savefig(FIG / "rotor_lambda_vs_U.png")
    plt.close(fig)


# ---------------------------------------------------------------- main
def main():
    style()
    FIG.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    st = pd.read_csv(RES / "rotor_static.csv")
    rc = pd.read_csv(RES / "rotor_cp.csv")
    old = pd.read_csv(OCT13 / "data/rotor_cp.csv")
    old_st = pd.read_csv(OCT13 / "data/rotor_static.csv")
    n13 = json.loads((OCT13 / "out/rotor_numbers.json").read_text())
    new_names = sorted(set(rc.name) - set(old.name))
    assert len(rc) == 53 and len(st) == 16 and len(new_names) == 13 and set(old.name) <= set(rc.name)
    assert set(old_st.name) == set(st.name)
    # the 40 old rotating rows and 16 static rows are unchanged (every common column)
    unchanged = {}
    for a, b in ((old, rc), (old_st, st)):
        m = a.merge(b, on="name", suffixes=("_o", "_n"))
        bad = []
        for c in a.columns:
            if c in ("name", "ran_on") or c not in b.columns:
                continue
            x, y = m[c + "_o"], m[c + "_n"]
            if x.dtype.kind in "fi":
                if not np.allclose(x.to_numpy(float), y.to_numpy(float), rtol=0, atol=0, equal_nan=True):
                    bad.append(c)
            elif (x.astype(str) != y.astype(str)).any():
                bad.append(c)
        unchanged["rotating" if len(a) == 40 else "static"] = dict(rows=int(len(m)), differing_columns=bad)
    for d in (rc, st):
        d["ran_on"] = np.where(d["name"].isin(MAC_CASES), "mac", "unity")
    jobs = {}
    for nm in new_names:
        j = json.loads((RUNS / nm / "hpc_jobs.jsonl").read_text().strip().splitlines()[-1])
        jobs[nm] = dict(job=j["job"], host=j["host"], ntasks=j["ntasks"], status=j["status"], start=j["start"])
        assert j["status"] == "complete" and j["host"].startswith("uri-")

    # ---------------- 13 Oct reproduction (the 40 old rows only)
    static = analyse_static(st)
    drag_rule = {h: v["sense_drag_rule"] for h, v in static.items()}
    rc13 = rc[rc.name.isin(old.name)]
    _, curves13, tstep13, sig13 = analyse_rotating(rc13, drag_rule, static)
    repro = {}
    for k, c in curves13.items():
        o = n13["curves"][k]
        z, zo = c["zero_crossings"], o["zero_crossings"]
        repro[k] = bool(c["CQ"] == o["CQ"] and c["u_CQ"] == o["u_CQ"] and len(z) == len(zo)
                        and all(abs(a["lam0"] - b["lam0"]) < 1e-12 and abs(a["u_lam0"] - b["u_lam0"]) < 1e-12
                                for a, b in zip(z, zo)))
    assert all(repro.values()), repro

    # ---------------- per-revolution histories of every rotating case
    hist = {nm: rev_history(nm) for nm in rc["name"]}
    rc = rc.copy()
    rc["production"] = rc.apply(is_production, axis=1)
    rc["wall"] = rc.apply(wall_of, axis=1)
    nrows, prow = [], []
    for _, r in rc.iterrows():
        h = hist[r["name"]]
        nav = int(round(r["n_avg_rev"]))
        ws = window_stats(h, nav)
        ext = h["rev"][2:]                     # revolutions 3..end ("extended window")
        nrows.append(dict(name=r["name"], new_since_13oct=r["name"] in new_names, hypothesis=r.hypothesis,
                          U_ms=r.U_ms, level=r.level, wall=r.wall, sense=r.sense, maxCo=r.maxCo, lam=r.lam,
                          n_rev=h["nr"], CQ_mean_table=r.CQ_mean, CQ_win_from_revs=ws["CQ_win_from_revs"],
                          d_win=ws["CQ_win_from_revs"] - r.CQ_mean, n_avg=ws["n_avg"], s_rev=ws.get("s_rev"),
                          u_iid=ws.get("u_iid"), u_batch_9x5=ws.get("u_batch_9x5"),
                          lag1_autocorr=ws.get("lag1_autocorr"), drift_half=ws["drift_half"],
                          drift_last_two_rev=ws["drift_last_two_rev"],
                          drift_last_two_rev_table=r.CQ_drift_last_two_rev,
                          trend_over_window=ws.get("trend_over_window"),
                          u_trend_over_window=ws.get("u_trend_over_window"),
                          mean_first22=ws.get("mean_first22"), mean_last22=ws.get("mean_last22"),
                          CQ_rev3_to_end=float(ext.mean()), n_rev3_to_end=int(len(ext)),
                          s_rev3_to_end=float(ext.std(ddof=1))))
        for i, v in enumerate(h["rev"]):
            prow.append(dict(name=r["name"], revolution=i + 1, CQ=v, in_window=i >= h["nr"] - nav))
    noise = pd.DataFrame(nrows)
    per_rev = pd.DataFrame(prow)
    # results.json per-revolution lists drop the last revolution when t_end/T falls short of an integer
    trunc = []
    for nm in rc["name"]:
        rj = json.loads((RUNS / nm / "results.json").read_text())
        if len(rj["CQ_per_rev"]) != hist[nm]["nr"]:
            trunc.append(dict(name=nm, listed=len(rj["CQ_per_rev"]), revolutions=hist[nm]["nr"],
                              n_rev_done=rj["n_rev_done"]))

    # pooled within-window revolution scatter per hypothesis and speed (medium, Spalding, maxCo 4)
    pool = {}
    sel = noise[(noise.level == "medium") & (noise.wall == "spalding") & (np.abs(noise.maxCo - 4) < 1e-9)]
    for (h, U), g in sel.groupby(["hypothesis", "U_ms"]):
        dof = int((g.n_avg - 1).sum())
        s = math.sqrt(float(((g.n_avg - 1) * g.s_rev ** 2).sum()) / dof)
        dofe = int((g.n_rev3_to_end - 1).sum())
        se_ = math.sqrt(float(((g.n_rev3_to_end - 1) * g.s_rev3_to_end ** 2).sum()) / dofe)
        d2 = g.drift_last_two_rev.to_numpy(float)
        pool[(h, float(U))] = dict(sigma_rev=s, dof=dof, n_cases=int(len(g)), sigma_rev_rev3_to_end=se_,
                                   dof_rev3_to_end=dofe, sigma_13oct_method=math.sqrt(np.mean(d2 ** 2) / 2),
                                   cases=g.name.tolist())
    sig_new = {k: v["sigma_rev"] for k, v in pool.items()}
    # all A 23 m/s maxCo-4 runs, every mesh and wall function (for the mesh-check runs)
    gA = noise[(noise.hypothesis == "A") & (noise.U_ms == 23.0) & (np.abs(noise.maxCo - 4) < 1e-9)]
    dofA = int((gA.n_avg - 1).sum())
    sigA_all = math.sqrt(float(((gA.n_avg - 1) * gA.s_rev ** 2).sum()) / dofA)
    long_sel = noise[noise.n_avg == 45]
    sig_long = math.sqrt(float((long_sel.s_rev ** 2).mean()))

    # ---------------- health check
    hl = health(st, rc)
    hl["new_since_13oct"] = hl["name"].isin(new_names)
    hl.to_csv(OUT / "rotor_health.csv", index=False, float_format="%.6g")
    hnew = hl[hl.new_since_13oct]

    # ---------------- production curves with the new noise model
    _, curves, tstep, _ = analyse_rotating(rc, drag_rule, static, sigma=sig_new)
    lam0_speed = {}
    for U in (10.2, 23.0, 38.0):
        c = curves[f"A_U{U:g}_CCW"]
        z = last_down_crossing(c["lam"], c["CQ"], c["u_CQ"])
        z13 = [x for x in n13["curves"][f"A_U{U:g}_CCW"]["zero_crossings"] if x["direction"] == "+ to -"][-1]
        # extended windows (revolutions 3..end) of the same cases
        ce = [noise.loc[noise.name == nm].iloc[0] for nm in c["cases"]]
        qe = [r.CQ_rev3_to_end for r in ce]
        ue = [sig_new[("A", U)] / math.sqrt(r.n_rev3_to_end) for r in ce]
        ze = last_down_crossing(c["lam"], qe, ue)
        lam0_speed[U] = dict(lam0=z["lam0"], two_u=2 * z["u_lam0"], between=z["between"], lam0_13oct=z13["lam0"],
                             two_u_13oct=2 * z13["u_lam0"], lam0_ext=ze["lam0"] if ze else None,
                             two_u_ext=2 * ze["u_lam0"] if ze else None, between_ext=ze["between"] if ze else None,
                             CQ_ext=[r6(v) for v in qe], n_ext=[int(r.n_rev3_to_end) for r in ce], lam=c["lam"],
                             CQ=c["CQ"], u_CQ=c["u_CQ"], sigma_rev=sig_new[("A", U)])

    # ---------------- rig landmarks
    rig = analyse_rig()
    r23 = [r["lam_max_loaded"] for r in rig["23.03"].values()]
    r38 = [r["lam_max_loaded"] for r in rig["37.95"].values()]
    r10 = [r["lam_max_loaded"] for r in rig["10.24"].values()]
    rig_light = {"10.2": r10, "23": r23, "38": r38}

    # ---------------- (1) rough-blade long runs
    lt = rc[(rc.n_avg_rev > 40) & (rc.U_ms == 23.0)].copy()
    lt = lt.merge(noise[["name", "s_rev", "u_iid", "u_batch_9x5", "lag1_autocorr", "drift_half", "drift_last_two_rev",
                         "trend_over_window", "u_trend_over_window", "mean_first22", "mean_last22",
                         "CQ_win_from_revs"]], on="name")
    lt["u_own"] = lt["u_iid"]
    lt["CQ_viscous"] = lt.CQ_mean - lt.CQ_pressure_mean
    assert len(lt) == 8 and set(lt.wall) == {"spalding", "Ks0", "Ks100", "Ks400"}
    cq_ref13 = n13["roughness_signal"]["CQ_A_reversed_lam010_U23"]
    band = (n13["roughness_signal"]["implied_dCQ"]["FS 0.10"], n13["roughness_signal"]["implied_dCQ"]["FS 0.20"])
    assert abs(band[0] - GAINS["FS 0.10"] * cq_ref13) < 1e-7 and abs(band[1] - GAINS["FS 0.20"] * cq_ref13) < 1e-7
    # same-speed band (verifier, 19 Oct): the rig's peak-power change at the 23.03 m/s set point (pointwise 95 %
    # half-width in the same file), on the same 13 Oct base C_Q as the speed-averaged band above
    bys = pd.read_csv(BYSPEED)
    g23 = {}
    for rot in ("FS 0.05", "FS 0.10", "FS 0.20"):
        rr = bys[(bys.rotor == rot)].copy()
        rr = rr.loc[(rr.wind_mps - 23.0).abs().idxmin()]
        assert abs(rr.wind_mps - 23.03) < 0.01
        g23[rot] = dict(wind_mps=float(rr.wind_mps), change_pct=float(rr.p_max_change_vs_plain_pct),
                        pointwise95_halfwidth_pct=float(rr.pointwise95_halfwidth_pct))
    band23 = (g23["FS 0.10"]["change_pct"] / 100 * cq_ref13, g23["FS 0.20"]["change_pct"] / 100 * cq_ref13)
    diffs, drows = {}, []
    pairs = [("Ks100", "Ks0"), ("Ks400", "Ks0"), ("Ks0", "spalding"), ("Ks100", "spalding"), ("Ks400", "spalding")]
    for lam in (0.10, 0.12):
        g = lt[np.abs(lt.lam - lam) < 1e-9].set_index("wall")
        for a, b in pairs:
            A, B = g.loc[a], g.loc[b]
            d = float(A.CQ_mean - B.CQ_mean)
            u = math.hypot(A.u_own, B.u_own)
            ub = math.hypot(A.u_batch_9x5, B.u_batch_9x5)
            up = sig_long * math.sqrt(2 / 45)
            dsum = abs(A.drift_half) + abs(B.drift_half)
            d1, d2 = float(A.mean_first22 - B.mean_first22), float(A.mean_last22 - B.mean_last22)
            implied = [GAINS[k] * float(B.CQ_mean) for k in GAINS]
            rec = dict(lam=lam, a=a, b=b, case_a=A["name"], case_b=B["name"], CQ_a=float(A.CQ_mean),
                       CQ_b=float(B.CQ_mean), dCQ=d, two_u=2 * u, ratio_to_2u=d / (2 * u), z=d / u,
                       resolved_2u=bool(abs(d) > 2 * u), two_u_batch=2 * ub, resolved_2u_batch=bool(abs(d) > 2 * ub),
                       two_u_pooled=2 * up, drift_sum=dsum, resolved_drift_rule=bool(abs(d) > dsum),
                       d_first22=d1, d_last22=d2, halves_same_sign=bool(np.sign(d1) == np.sign(d2) == np.sign(d)),
                       dCP=lam * d, two_u_CP=2 * lam * u, rel_change_pct=100 * d / float(B.CQ_mean),
                       dCQ_pressure=float(A.CQ_pressure_mean - B.CQ_pressure_mean),
                       dCQ_viscous=float(A.CQ_viscous - B.CQ_viscous), dCx=float(A.Cx_mean - B.Cx_mean),
                       dCQ_std=float(A.CQ_std - B.CQ_std),
                       minus_band_lo_over_u=(d - band[0]) / u, minus_band_hi_over_u=(d - band[1]) / u,
                       ci_2u=[d - 2 * u, d + 2 * u], implied_on_own_base=implied)
            diffs[(lam, a, b)] = rec
            drows.append(rec)
    rough_df = pd.DataFrame([{k: (v if not isinstance(v, list) else ";".join(f"{x:.6g}" for x in v))
                              for k, v in r.items()} for r in drows])
    rough_df.to_csv(OUT / "rotor_roughness.csv", index=False, float_format="%.6g")
    # Ks trend at each lambda (C_Q against Ks over 0/100/400 um, rough wall function), weighted fit
    ks_trend = {}
    for lam in (0.10, 0.12):
        g = lt[(np.abs(lt.lam - lam) < 1e-9) & (lt.wall != "spalding")].sort_values("Ks_um")
        x, y, w = g.Ks_um.to_numpy(float), g.CQ_mean.to_numpy(float), 1 / g.u_own.to_numpy(float) ** 2
        X = np.vstack([np.ones_like(x), x]).T
        cov = np.linalg.inv(X.T @ (X * w[:, None]))
        beta = cov @ (X.T @ (w * y))
        ks_trend[f"{lam:.2f}"] = dict(slope_per_100um=float(100 * beta[1]), u_slope_per_100um=float(100 * math.sqrt(cov[1, 1])))

    # ---------------- phase-resolved blade torque of the long runs
    phase = {}
    for _, r in lt.iterrows():
        mid, pb = phase_bins(r["name"])
        phase[(round(r.lam, 2), r.wall)] = pb
        phase["mid"] = mid
    mid = phase["mid"]
    sect, srows, ph_rows = {}, [], []
    names = [s[0] for s in SECTORS] + ["the four 30° gaps between"]
    masks = [sector_mask(mid, lo, hi) for _, lo, hi in SECTORS]
    masks.append(~np.any(masks, axis=0))
    for lam in (0.10, 0.12):
        for wl in ("spalding", "Ks0", "Ks100", "Ks400"):
            pb = phase[(lam, wl)]
            for j, m_ in enumerate(mid):
                ph_rows.append(dict(lam=lam, wall=wl, theta_mid_deg=m_, CQ_single_blade=float(pb[:, j].mean()),
                                    u=float(pb[:, j].std(ddof=1) / math.sqrt(len(pb)))))
        for a, b in (("Ks400", "Ks0"), ("Ks100", "Ks0"), ("Ks0", "spalding"), ("Ks400", "spalding"),
                     ("Ks100", "spalding")):
            pa, pbb = phase[(lam, a)], phase[(lam, b)]
            tot_check = 0.0
            for nm, msk in zip(names, masks):
                ca = 3 * pa[:, msk].sum(axis=1) / len(mid)       # rotor C_Q contribution, per revolution
                cb = 3 * pbb[:, msk].sum(axis=1) / len(mid)
                d = float(ca.mean() - cb.mean())
                u = math.sqrt(ca.var(ddof=1) / len(ca) + cb.var(ddof=1) / len(cb))
                sect[(lam, a, b, nm)] = dict(d=d, two_u=2 * u, a=float(ca.mean()), b=float(cb.mean()))
                srows.append(dict(lam=lam, a=a, b=b, sector=nm, contrib_a=float(ca.mean()), contrib_b=float(cb.mean()),
                                  d=d, two_u=2 * u, resolved_2u=bool(abs(d) > 2 * u)))
                tot_check += d
            sect[(lam, a, b, "total")] = dict(d=tot_check)
    pd.DataFrame(ph_rows).to_csv(OUT / "rotor_roughness_phase.csv", index=False, float_format="%.6g")
    pd.DataFrame(srows).to_csv(OUT / "rotor_roughness_sectors.csv", index=False, float_format="%.6g")
    # sum of the bin means equals the window mean up to the sampling rule (sample mean vs trapezoid)
    phase_vs_table = max(abs(3 * phase[(lam, wl)].mean() - float(lt[(np.abs(lt.lam - lam) < 1e-9)
                                                                      & (lt.wall == wl)].CQ_mean.iloc[0]))
                         for lam in (0.10, 0.12) for wl in ("spalding", "Ks0", "Ks100", "Ks400"))

    # ---------------- (2) mesh check, 23 m/s, A CCW
    def pick(**kw):
        m = np.ones(len(rc), bool)
        for k_, v in kw.items():
            m &= (np.abs(rc[k_] - v) < 1e-9) if isinstance(v, float) else (rc[k_] == v)
        g = rc[m]
        assert len(g) == 1, (kw, g.name.tolist())
        return g.iloc[0]
    sA = sig_new[("A", 23.0)]
    grid_rows, grid_curves = [], {}
    for lvl in ("coarse", "medium", "fine"):
        lams = [0.10, 0.15] if lvl != "medium" else curves["A_U23_CCW"]["lam"]
        cq, u, cqe, ue, nmz = [], [], [], [], []
        for lam in lams:
            if lvl == "medium":
                r = rc[rc.production & (rc.hypothesis == "A") & (rc.U_ms == 23.0) & (rc.sense == "CCW")
                       & (np.abs(rc.lam - lam) < 1e-9)].iloc[0]
            else:
                r = pick(hypothesis="A", U_ms=23.0, sense="CCW", level=lvl, lam=float(lam))
            nz = noise[noise.name == r["name"]].iloc[0]
            cq.append(float(r.CQ_mean))
            u.append(sA / math.sqrt(r.n_avg_rev))
            cqe.append(float(nz.CQ_rev3_to_end))
            ue.append(sA / math.sqrt(nz.n_rev3_to_end))
            nmz.append(r["name"])
            if lam in (0.10, 0.15):
                grid_rows.append(dict(level=lvl, lam=lam, case=r["name"], n_cells=int(r.n_cells), dt_mean_s=r.dt_mean_s,
                                      n_avg_rev=int(round(r.n_avg_rev)), CQ=float(r.CQ_mean), CP=float(r.CP_mean),
                                      two_u=2 * sA / math.sqrt(r.n_avg_rev), CQ_rev3_to_end=float(nz.CQ_rev3_to_end),
                                      n_rev3_to_end=int(nz.n_rev3_to_end),
                                      two_u_rev3_to_end=2 * sA / math.sqrt(nz.n_rev3_to_end),
                                      s_rev_own=float(nz.s_rev), drift_last_two_rev=float(nz.drift_last_two_rev),
                                      Cx=float(r.Cx_mean), CQ_std=float(r.CQ_std), yplus_mean=float(r.yplus_mean)))
        grid_curves[lvl] = dict(lam=list(map(float, lams)), CQ=cq, u=u, CQ_ext=cqe, u_ext=ue, cases=nmz,
                                cells=int(rc[rc.name == nmz[0]].n_cells.iloc[0]))
    co2 = pick(hypothesis="A", U_ms=23.0, sense="CCW", level="medium", lam=0.15, maxCo=2.0)
    nz2 = noise[noise.name == co2["name"]].iloc[0]
    grid_curves["medium_maxCo2"] = dict(CQ=float(co2.CQ_mean), u=sA / math.sqrt(co2.n_avg_rev),
                                        CQ_ext=float(nz2.CQ_rev3_to_end), u_ext=sA / math.sqrt(nz2.n_rev3_to_end),
                                        case=co2["name"], dt_mean_s=float(co2.dt_mean_s))
    lg = lt[lt.wall == "spalding"].sort_values("lam")
    grid_curves["medium_long"] = dict(lam=lg.lam.tolist(), CQ=lg.CQ_mean.tolist(), u=lg.u_own.tolist(),
                                      cases=lg.name.tolist())
    gdf = pd.DataFrame(grid_rows)
    # differences and convergence ratio (Celik et al. 2008: R = (phi_m - phi_f)/(phi_c - phi_m))
    grid_diff = {}
    for lam in (0.10, 0.15):
        g = gdf[np.abs(gdf.lam - lam) < 1e-9].set_index("level")
        c_, m_, f_ = g.loc["coarse"], g.loc["medium"], g.loc["fine"]
        u3 = sA / math.sqrt(3)
        grid_diff[f"{lam:.2f}"] = dict(
            fine_minus_medium=float(f_.CQ - m_.CQ), medium_minus_coarse=float(m_.CQ - c_.CQ),
            fine_minus_coarse=float(f_.CQ - c_.CQ), two_u_diff=2 * math.sqrt(2) * u3,
            R=float((m_.CQ - f_.CQ) / (c_.CQ - m_.CQ)), spread=float(max(g.CQ) - min(g.CQ)),
            fine_minus_medium_ext=float(f_.CQ_rev3_to_end - m_.CQ_rev3_to_end),
            medium_minus_coarse_ext=float(m_.CQ_rev3_to_end - c_.CQ_rev3_to_end),
            two_u_diff_ext=2 * math.sqrt(2) * sA / math.sqrt(m_.n_rev3_to_end),
            dt_ratio_fine_medium=float(f_.dt_mean_s / m_.dt_mean_s),
            dt_ratio_coarse_medium=float(c_.dt_mean_s / m_.dt_mean_s),
            cells_ratio_medium_coarse=float(m_.n_cells / c_.n_cells), cells_ratio_fine_medium=float(f_.n_cells / m_.n_cells))
    lg10 = float(lg[np.abs(lg.lam - 0.10) < 1e-9].CQ_mean.iloc[0])
    lgu10 = float(lg[np.abs(lg.lam - 0.10) < 1e-9].u_own.iloc[0])
    f10 = float(gdf[(gdf.level == "fine") & (np.abs(gdf.lam - 0.10) < 1e-9)].CQ.iloc[0])
    grid_diff["0.10"]["fine_minus_medium45"] = f10 - lg10
    grid_diff["0.10"]["two_u_fine_minus_medium45"] = 2 * math.hypot(sA / math.sqrt(3), lgu10)
    gdf.to_csv(OUT / "rotor_grid.csv", index=False, float_format="%.6g")
    # zero-torque lambda per mesh: coarse and fine from lambda 0.10 and 0.15; medium from its full curve
    lam0_mesh, lam0_rows = {}, []
    for lvl in ("coarse", "medium", "fine"):
        c = grid_curves[lvl]
        z = last_down_crossing(c["lam"], c["CQ"], c["u"])
        ze = last_down_crossing(c["lam"], c["CQ_ext"], c["u_ext"])
        lam0_mesh[lvl] = dict(lam0=z["lam0"], two_u=2 * z["u_lam0"], between=z["between"], lam0_ext=ze["lam0"],
                              two_u_ext=2 * ze["u_lam0"], between_ext=ze["between"])
    # medium with the maxCo-2 value at lambda 0.15 (13 Oct: 0.149)
    cm = grid_curves["medium"]
    i15 = cm["lam"].index(0.15)
    q2 = list(cm["CQ"]); q2[i15] = grid_curves["medium_maxCo2"]["CQ"]
    u2 = list(cm["u"]); u2[i15] = grid_curves["medium_maxCo2"]["u"]
    z2 = last_down_crossing(cm["lam"], q2, u2)
    q2e = list(cm["CQ_ext"]); q2e[i15] = grid_curves["medium_maxCo2"]["CQ_ext"]
    u2e = list(cm["u_ext"]); u2e[i15] = grid_curves["medium_maxCo2"]["u_ext"]
    z2e = last_down_crossing(cm["lam"], q2e, u2e)
    lam0_mesh["medium_maxCo2"] = dict(lam0=z2["lam0"], two_u=2 * z2["u_lam0"], between=z2["between"],
                                      lam0_ext=z2e["lam0"], two_u_ext=2 * z2e["u_lam0"], between_ext=z2e["between"])
    for key, lab, lvl in (("coarse", "coarse", "coarse"), ("medium", "medium", "medium"), ("fine", "fine", "fine"),
                          ("medium_maxCo2", "medium,\nmaxCo 2 at 0.15", "co2")):
        r = lam0_mesh[key]
        lam0_rows.append(dict(key=key, label=lab, level=lvl, lam0_tab=r["lam0"], two_u_tab=r["two_u"],
                              lam0_ext=r["lam0_ext"], two_u_ext=r["two_u_ext"], between=r["between"],
                              between_ext=r["between_ext"]))
    lam0_out = []
    for U, r in lam0_speed.items():
        lam0_out.append(dict(U_ms=U, level="medium", window="table", lam0=r["lam0"], two_u=r["two_u"],
                             between=str(r["between"]), lam0_13oct=r["lam0_13oct"], two_u_13oct=r["two_u_13oct"]))
        lam0_out.append(dict(U_ms=U, level="medium", window="revolutions 3 to end", lam0=r["lam0_ext"],
                             two_u=r["two_u_ext"], between=str(r["between_ext"])))
    for row in lam0_rows:
        if row["key"] == "medium":
            continue
        lam0_out.append(dict(U_ms=23.0, level=row["key"], window="table", lam0=row["lam0_tab"], two_u=row["two_u_tab"],
                             between=str(row["between"])))
        lam0_out.append(dict(U_ms=23.0, level=row["key"], window="revolutions 3 to end", lam0=row["lam0_ext"],
                             two_u=row["two_u_ext"], between=str(row["between_ext"])))
    pd.DataFrame(lam0_out).to_csv(OUT / "rotor_lambda0.csv", index=False, float_format="%.6g")

    # ---------------- (3) 38 m/s, lambda 0.30: 8 against 16 revolutions
    n8 = "A_rot_U38.0_lam0.300_SST_medium_senseCCW"
    n16 = "A_rot_U38.0_lam0.300_SST_medium_senseCCW_rev16a8"
    s38 = sig_new[("A", 38.0)]
    r38 = {}
    for key, nm in (("rev8", n8), ("rev16", n16)):
        h = hist[nm]
        nz = noise[noise.name == nm].iloc[0]
        row = rc[rc.name == nm].iloc[0]
        r38[key] = dict(case=nm, rev=h["rev"].tolist(), n_avg=int(round(row.n_avg_rev)), CQ_mean=float(row.CQ_mean),
                        CP_mean=float(row.CP_mean), two_u_pooled=2 * s38 / math.sqrt(row.n_avg_rev),
                        s_rev_own=float(nz.s_rev), two_u_own=2 * float(nz.s_rev) / math.sqrt(row.n_avg_rev),
                        drift_last_two_rev=float(nz.drift_last_two_rev), drift_half=float(nz.drift_half),
                        trend_over_window=nz.trend_over_window, u_trend_over_window=nz.u_trend_over_window,
                        CQ_rev3_to_end=float(nz.CQ_rev3_to_end), n_rev3_to_end=int(nz.n_rev3_to_end),
                        s_rev3_to_end=float(nz.s_rev3_to_end))
    # the two runs share every setting except the run length; their histories agree for the first
    # revolutions and then decorrelate (floating-point differences grow in this unsteady flow)
    rev_diff_16_minus_8 = [float(b - a) for a, b in zip(r38["rev8"]["rev"], r38["rev16"]["rev"])]
    d38 = r38["rev16"]["CQ_mean"] - r38["rev8"]["CQ_mean"]
    u38 = math.hypot(s38 / math.sqrt(8), s38 / math.sqrt(3))
    # the 38 m/s curve with the 16-revolution value at lambda 0.30 instead
    c38 = curves["A_U38_CCW"]
    q16 = list(c38["CQ"]); q16[c38["lam"].index(0.3)] = r38["rev16"]["CQ_mean"]
    u16 = list(c38["u_CQ"]); u16[c38["lam"].index(0.3)] = s38 / math.sqrt(8)
    z16 = last_down_crossing(c38["lam"], q16, u16)
    gap38 =float(np.mean(rig_light["38"])) - lam0_speed[38.0]["lam0"]

    # ---------------- physics link: Stage 2 rough wall function, edge-on (alpha 90) and convex side (180)
    s2 = pd.read_csv(STAGE2)
    s2 = s2[(s2.wall == "wf") & (s2.U_ms == 23.0) & (np.abs(s2.maxCo - 2.5) < 1e-9) & s2.alpha_deg.isin([90, 180])
            & s2.Ks_um.isin([0, 100, 400])]
    assert len(s2) == 6
    sec = {}
    for (al, ks), r in s2.set_index(["alpha_deg", "Ks_um"]).iterrows():
        sec[f"a{al:g}_Ks{ks:g}"] = dict(case=r["name"], Cd=r6(r.Cd_mean), Cd_pressure=r6(r.Cd_pressure_mean),
                                        Cd_viscous=r6(r.Cd_viscous_mean), Cl=r6(r.Cl_mean), Cd_drift=r6(r.Cd_drift))
    r_c = json.loads(POSES.read_text())["poses"][0]["r_centroid_m"]
    assert json.loads(POSES.read_text())["poses"][0]["name"] == "A"
    qs = {}
    for ks in (100, 400):
        dcd = sec[f"a90_Ks{ks}"]["Cd"] - sec["a90_Ks0"]["Cd"]
        for lam in (0.10, 0.12):
            # one blade at theta 90 deg, edge-on, moving downwind: relative speed (1 - lam) U, drag along the
            # motion, lever arm = centroid radius; C_Q per unit span on 2R R
            qs[f"Ks{ks}_lam{lam:.2f}"] = r6((1 - lam) ** 2 * C_REF / (2 * 0.1016) * r_c / 0.1016 * dcd)
    ph = pd.DataFrame(ph_rows)
    bins90 = {}
    for ks in ("Ks400", "Ks100"):
        for lam in (0.10, 0.12):
            a_ = ph[(np.abs(ph.lam - lam) < 1e-9) & (ph.wall == ks)].set_index("theta_mid_deg").CQ_single_blade
            b_ = ph[(np.abs(ph.lam - lam) < 1e-9) & (ph.wall == "Ks0")].set_index("theta_mid_deg").CQ_single_blade
            dd = (a_ - b_)
            bins90[f"{ks}_lam{lam:.2f}"] = dict(theta_85=r6(dd.loc[85.0]), theta_95=r6(dd.loc[95.0]),
                                                range_75_115=[r6(dd.loc[75.0:115.0].min()),
                                                              r6(dd.loc[75.0:115.0].max())])
    physics = dict(stage2_wall_function_maxCo2p5=sec, r_centroid_A_m=r6(r_c),
                   quasi_steady_dCQ_single_blade_theta90=qs, computed_dCQ_single_blade_minus_Ks0=bins90)

    # ---------------- revolutions needed to resolve the rig-implied change at 2u (two runs, same sigma)
    nrev_needed = {k: math.ceil((2 * math.sqrt(2) * sig_long / v) ** 2) for k, v in
                   (("FS 0.10", band[0]), ("FS 0.20", band[1]))}
    cost = {}
    for _, r in lt.iterrows():
        steps_rev = r.n_steps / r.n_rev_done
        cost[r["name"]] = dict(steps_per_rev=r6(steps_rev), s_per_step=r6(r.s_per_step),
                               s_per_rev=r6(steps_rev * r.s_per_step), wall_h=r6(r.wall_time_s / 3600),
                               host=jobs[r["name"]]["host"])

    # ---------------- figures
    fig_roughness_dcq(lt, diffs, band, band23)
    fig_roughness_phase(phase, sect)
    fig_histories(hist, lt, r38)
    fig_grid(grid_curves, lam0_rows, (min(r23), max(r23)))
    fig_lambda_vs_U(lam0_speed, lam0_mesh, rig)

    # ---------------- outputs
    noise.to_csv(OUT / "rotor_noise.csv", index=False, float_format="%.6g")
    per_rev.to_csv(OUT / "rotor_per_rev.csv", index=False, float_format="%.6g")
    numbers = dict(
        provenance="computed by cfd/analysis/2026-10-15/src/rotor_analysis.py from cfd/rotor2d/results/rotor_cp.csv, "
                   "rotor_static.csv and the case folders cfd/rotor2d/runs/<case> (read only); rig CSVs as 13 Oct",
        inputs=dict(rotor_cp_csv_sha256=sha256(RES / "rotor_cp.csv"), rotor_static_csv_sha256=sha256(RES / "rotor_static.csv"),
                    n_rotating=int(len(rc)), n_static=int(len(st)), new_cases=new_names, jobs_new=jobs,
                    old_rows_unchanged=unchanged),
        reproduction_13oct=dict(curves_identical=repro, sigma_rev_13oct=sig13),
        results_json_per_rev_truncated=trunc,
        health=dict(new=dict(n=int(len(hnew)), n_flagged=int(hnew.flagged.sum()), n_any_symptom=int(hnew.any_symptom.sum()),
                             u_co_over_U=[r6(hnew.u_co_over_U.min()), r6(hnew.u_co_over_U.max())],
                             dt_over_group_median=[r6(hnew.dt_over_group_median.min()), r6(hnew.dt_over_group_median.max())]),
                    all=dict(n=int(len(hl)), n_flagged=int(hl.flagged.sum()), n_any_symptom=int(hl.any_symptom.sum()),
                             u_co_over_U=[r6(hl.u_co_over_U.min()), r6(hl.u_co_over_U.max())],
                             dt_over_group_median=[r6(hl.dt_over_group_median.min()), r6(hl.dt_over_group_median.max())],
                             yplus_mean=[r6(hl.yplus_mean.min()), r6(hl.yplus_mean.max())],
                             yplus_max=[r6(hl.yplus_max.min()), r6(hl.yplus_max.max())])),
        noise_model=dict(
            pooled={f"{h}_U{U:g}": {k: (r6(v) if isinstance(v, float) else v) for k, v in d.items()} for (h, U), d in pool.items()},
            sigma_A23_all_meshes_and_walls=r6(sigA_all), dof_A23_all=dofA, sigma_long_runs_rms=r6(sig_long),
            long_runs=dict(s_rev=[r6(lt.s_rev.min()), r6(lt.s_rev.max())],
                           lag1_autocorr=[r6(lt.lag1_autocorr.min()), r6(lt.lag1_autocorr.max())],
                           lag1_autocorr_mean=r6(lt.lag1_autocorr.mean()),
                           u_iid=[r6(lt.u_iid.min()), r6(lt.u_iid.max())],
                           u_batch_9x5=[r6(lt.u_batch_9x5.min()), r6(lt.u_batch_9x5.max())],
                           drift_half=[r6(lt.drift_half.min()), r6(lt.drift_half.max())],
                           trend_over_window_over_u=[r6(v) for v in (lt.trend_over_window / lt.u_trend_over_window)],
                           queue_header_two_u_diff_planned=r6(2 * math.sqrt(2) * 0.00586 / math.sqrt(45)),
                           two_u_diff_from_rms=r6(2 * sig_long * math.sqrt(2 / 45))),
            transient=None),
        roughness=dict(
            runs={f"{r.lam:.2f}_{r.wall}": dict(case=r["name"], CQ=r6(r.CQ_mean), CP=r6(r.CP_mean), two_u=r6(2 * r.u_own),
                                                 two_u_CP=r6(2 * r.lam * r.u_own), s_rev=r6(r.s_rev),
                                                 u_batch=r6(r.u_batch_9x5), lag1=r6(r.lag1_autocorr),
                                                 drift_half=r6(r.drift_half), drift_last_two_rev=r6(r.drift_last_two_rev),
                                                 trend_over_window=r6(r.trend_over_window),
                                                 u_trend_over_window=r6(r.u_trend_over_window),
                                                 CQ_pressure=r6(r.CQ_pressure_mean), CQ_viscous=r6(r.CQ_viscous),
                                                 Cx=r6(r.Cx_mean), CQ_std=r6(r.CQ_std), yplus_mean=r6(r.yplus_mean),
                                                 Ks_over_yP=r6(r.Ks_over_yP), ksplus_mean=r6(r.ksplus_blade_mean),
                                                 ksplus_max=r6(r.ksplus_blade_max), wall_time_h=r6(r.wall_time_s / 3600),
                                                 n_steps=int(r.n_steps))
                  for _, r in lt.iterrows()},
            differences={f"{k[0]:.2f}_{k[1]}-{k[2]}": {kk: (r6(vv) if isinstance(vv, float) else
                                                         ([r6(x) for x in vv] if isinstance(vv, list) else vv))
                                                    for kk, vv in v.items()} for k, v in diffs.items()},
            rig_band_13oct=dict(lo=r6(band[0]), hi=r6(band[1]), base_CQ=cq_ref13, gains=GAINS),
            rig_band_23ms=dict(lo=r6(band23[0]), hi=r6(band23[1]), base_CQ=cq_ref13, gains_at_23ms=g23,
                               on_Ks0_base={f"{lam:.2f}": [r6(g23[k]["change_pct"] / 100 * float(lt[(np.abs(lt.lam - lam) < 1e-9) & (lt.wall == "Ks0")].CQ_mean.iloc[0])) for k in ("FS 0.10", "FS 0.20")] for lam in (0.10, 0.12)},
                               nrev_needed_per_run_2u={k: int(math.ceil(8 * sig_long ** 2 / (g23[k]["change_pct"] / 100 * cq_ref13) ** 2)) for k in ("FS 0.10", "FS 0.20")},
                               source="reports/roughness_2026-09/build/derived/rotor_by_wind_speed.csv, rows at 23.03 m/s (measured); added by the verifier, 19 Oct"),
            ks_trend=ks_trend,
            sectors={f"{k[0]:.2f}_{k[1]}-{k[2]}_{k[3]}": {kk: r6(vv) for kk, vv in v.items()} for k, v in sect.items()},
            phase_sum_vs_table_max_abs=r6(phase_vs_table)),
        grid=dict(rows=[{k: (r6(v) if isinstance(v, float) else v) for k, v in r.items()} for r in grid_rows],
                  differences={k: {kk: r6(vv) for kk, vv in v.items()} for k, v in grid_diff.items()},
                  maxCo2=dict(case=co2["name"], CQ=r6(float(co2.CQ_mean)), CQ_rev3_to_end=r6(float(nz2.CQ_rev3_to_end)),
                              dt_mean_s=r6(float(co2.dt_mean_s))),
                  lam0={k: {kk: (r6(vv) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in lam0_mesh.items()},
                  sigma_used=r6(sA)),
        lambda0_by_speed={f"{U:g}": {k: (r6(v) if isinstance(v, float) else v) for k, v in d.items()}
                          for U, d in lam0_speed.items()},
        rig_light_load=rig_light,
        u38=dict(rev8=r38["rev8"], rev16=r38["rev16"], rev_diff_16_minus_8_revs1to8=[r6(v) for v in rev_diff_16_minus_8],
                 d_16_minus_8=r6(d38), two_u_d=r6(2 * u38), lam0_with_rev16=r6(z16["lam0"]),
                 two_u_lam0_with_rev16=r6(2 * z16["u_lam0"]), sigma_rev_38=r6(s38),
                 gap_rig_minus_cfd=r6(gap38), gap_over_u=r6(gap38 / (lam0_speed[38.0]["two_u"] / 2)),
                 gap_ext=r6(float(np.mean(rig_light["38"])) - lam0_speed[38.0]["lam0_ext"])),
        time_step_check=tstep,
        physics_link=physics,
        nrev_needed_per_run_2u=dict(sigma_rev=r6(sig_long), n=nrev_needed,
                                    note="averaged revolutions per run so that 2u of a two-run difference "
                                         "equals the rig-implied change (estimated)"),
        cost_long_runs=cost,
    )
    # transient: excess of revolution k over the window mean, in units of s_rev, mean over the long runs
    ex = np.array([[(hist[nm]["rev"][k] - hist[nm]["rev"][5:].mean()) / hist[nm]["rev"][5:].std(ddof=1)
                    for k in range(8)] for nm in lt["name"]])
    numbers["noise_model"]["transient"] = dict(
        excess_of_revolution_k_over_window_mean_in_s_rev=[r6(v) for v in ex.mean(axis=0)],
        se=[r6(v) for v in ex.std(axis=0, ddof=1) / math.sqrt(len(ex))], revolutions=list(range(1, 9)))
    corr = []
    for lam in (0.10, 0.12):
        g = lt[np.abs(lt.lam - lam) < 1e-9]
        nms = g["name"].tolist()
        for i in range(len(nms)):
            for j in range(i + 1, len(nms)):
                corr.append(float(np.corrcoef(hist[nms[i]]["rev"][5:], hist[nms[j]]["rev"][5:])[0, 1]))
    numbers["noise_model"]["cross_run_corr_revs6_50"] = [r6(min(corr)), r6(max(corr))]
    (OUT / "rotor_numbers.json").write_text(json.dumps(numbers, indent=1, default=float))

    # ---------------- console summary
    print("old rows unchanged:", unchanged)
    print("13 Oct curves reproduced:", repro)
    print("results.json per-rev truncated:", [(t["name"], t["listed"], t["revolutions"]) for t in trunc])
    print("health, new:", numbers["health"]["new"], "\nhealth, all:", numbers["health"]["all"])
    for k, v in pool.items():
        print("sigma", k, {kk: vv for kk, vv in v.items() if kk != "cases"})
    print("sigma A23 all", sigA_all, dofA, "long rms", sig_long)
    print(lt[["name", "CQ_mean", "CP_mean", "u_own", "s_rev", "u_batch_9x5", "lag1_autocorr", "drift_half",
              "drift_last_two_rev", "trend_over_window", "u_trend_over_window"]].to_string())
    for k, v in diffs.items():
        print(k, {kk: (round(vv, 6) if isinstance(vv, float) else vv) for kk, vv in v.items()
                  if kk in ("dCQ", "two_u", "ratio_to_2u", "z", "resolved_2u", "two_u_batch", "drift_sum",
                            "resolved_drift_rule", "d_first22", "d_last22", "dCP", "two_u_CP", "rel_change_pct",
                            "dCQ_pressure", "dCQ_viscous", "dCx", "minus_band_lo_over_u")})
    print("ks trend", ks_trend)
    for k, v in sect.items():
        print("sector", k, {kk: round(vv, 6) for kk, vv in v.items()})
    print("phase vs table", phase_vs_table)
    print(gdf.to_string())
    print("grid diff", json.dumps(grid_diff, indent=0))
    print("lam0 mesh", json.dumps(lam0_mesh, indent=0))
    print("lam0 speed", json.dumps({k: {kk: vv for kk, vv in v.items() if kk not in ('CQ', 'u_CQ')} for k, v in lam0_speed.items()}, indent=0, default=str))
    print("38:", {k: {kk: vv for kk, vv in v.items() if kk != "rev"} for k, v in r38.items()})
    print("38 rev8", np.round(r38["rev8"]["rev"], 4), "\n38 rev16", np.round(r38["rev16"]["rev"], 4))
    print("38 d16-8", d38, "2u", 2 * u38, "per-rev 16-8", np.round(rev_diff_16_minus_8, 4), "lam0 with rev16", z16,
          "gap", gap38)
    print("tstep", tstep)
    print("physics", json.dumps(physics, indent=0))
    print("nrev needed", nrev_needed, "cost", json.dumps(cost, indent=0))


if __name__ == "__main__":
    main()
