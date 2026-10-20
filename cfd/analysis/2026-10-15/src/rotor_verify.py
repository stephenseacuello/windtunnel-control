#!/usr/bin/env python3
"""Independent check of the 15 Oct rotor numbers (shares no code with rotor_analysis.py).

    nice -n 10 python3 cfd/analysis/2026-10-15/src/rotor_verify.py

Adapted from cfd/analysis/2026-10-13/src/rotor_verify.py (13 Oct). Recomputes, from the table
cfd/rotor2d/results/rotor_cp.csv and the raw force files of the case folders (read only), every
number of the rotor stage of 15 Oct and compares it with ../out/rotor_numbers.json, printing
OK or CHECK per number and the count of CHECK lines at the end.

Different methods from the analysis script, on purpose:
- force files are parsed with pandas (whitespace separator), not numpy.loadtxt;
- revolution means come from resampling C_Q(t) onto 3600 uniformly spaced instants per
  revolution (linear interpolation) and averaging, not from a cumulative trapezoid integral;
- the window halves for the drift rule are formed on that resampled series;
- the phase-resolved blade torque is binned on the resampled series by blade azimuth;
- zero crossings and their uncertainty are recomputed with a numerical derivative.
Tolerances: 3e-5 in C_Q for window means and differences (resampling against trapezoid),
2 % relative for standard deviations and uncertainties, 2e-4 in lambda for crossings.
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
REPO = BASE.parents[2]
RUNS = REPO / "cfd/rotor2d/runs"
TAB = pd.read_csv(REPO / "cfd/rotor2d/results/rotor_cp.csv")
STA = pd.read_csv(REPO / "cfd/rotor2d/results/rotor_static.csv")
OLD = pd.read_csv(REPO / "cfd/analysis/2026-10-13/data/rotor_cp.csv")
NUM = json.loads((BASE / "out/rotor_numbers.json").read_text())
DW = pd.read_csv(REPO / "reports/roughness_2026-09/build/tacho/derived/rotor_speed_by_dwell.csv")
NCHECK = [0]
NOK = [0]


def cmp(label, mine, theirs, tol_abs=None, tol_rel=None):
    ok = True
    if theirs is None or mine is None:
        ok = theirs is None and mine is None
    elif isinstance(mine, bool) or isinstance(theirs, bool):
        ok = bool(mine) == bool(theirs)
    else:
        d = abs(float(mine) - float(theirs))
        lim = 0.0
        if tol_abs is not None:
            lim = max(lim, tol_abs)
        if tol_rel is not None:
            lim = max(lim, tol_rel * abs(float(theirs)))
        ok = d <= lim + 1e-12
    if ok:
        NOK[0] += 1
    else:
        NCHECK[0] += 1
    print(f"{'OK   ' if ok else 'CHECK'} {label}: recomputed {mine} | analysis {theirs}")


def load_cq(case, fo="forcesRotor"):
    cj = json.loads((RUNS / case / "case.json").read_text())
    f = RUNS / case / "postProcessing" / fo / "0" / "moment.dat"
    df = pd.read_csv(f, sep=r"\s+", comment="#", header=None, engine="python")
    t = df[0].to_numpy(float)
    mz = df[3].to_numpy(float)
    keep = np.concatenate([[True], np.diff(t) > 0])
    t, mz = t[keep], mz[keep]
    q = cj["sense"] * mz / cj["dz"] / (0.5 * cj["rhoInf"] * cj["Uinf"] ** 2 * 2 * cj["R"] * cj["R"])
    return cj, t, q


def resampled(case, fo="forcesRotor", per=3600):
    cj, t, q = load_cq(case, fo)
    T = 2 * math.pi * cj["R"] / (cj["lam"] * cj["Uinf"])
    assert abs(T - cj["Trev"]) < 1e-9 * T
    nrev = int(round(t[-1] / T))
    tt = (np.arange(nrev * per) + 0.5) * T / per        # mid-points of uniform sub-intervals
    qq = np.interp(tt, t, q)
    return cj, T, nrev, tt, qq.reshape(nrev, per)


def rev_means(case):
    cj, T, nrev, tt, Q = resampled(case)
    return cj, Q.mean(axis=1), Q


def sd(x):
    x = np.asarray(x, float)
    return float(np.sqrt(np.sum((x - x.mean()) ** 2) / (len(x) - 1)))


print("=== inputs")
cmp("rotating cases in the table", len(TAB), NUM["inputs"]["n_rotating"])
cmp("new cases since 13 Oct", len(set(TAB.name) - set(OLD.name)), len(NUM["inputs"]["new_cases"]))
old_vals = OLD.drop(columns=["ran_on"]).set_index("name").sort_index()
new_vals = TAB[old_vals.columns.tolist() + ["name"]].set_index("name").loc[old_vals.index]
same = all(np.array_equal(old_vals[c].to_numpy(), new_vals[c].to_numpy()) if old_vals[c].dtype.kind not in "f"
           else np.allclose(old_vals[c].to_numpy(float), new_vals[c].to_numpy(float), rtol=0, atol=0, equal_nan=True)
           for c in old_vals.columns)
cmp("13 Oct rotating rows unchanged", same, NUM["inputs"]["old_rows_unchanged"]["rotating"]["differing_columns"] == [])

# ------------------------------------------------------------------ revolution means, all cases
print("=== revolution means and window statistics")
REV, QS = {}, {}
for nm in TAB.name:
    cj, r, Q = rev_means(nm)
    REV[nm] = r
    QS[nm] = Q
noise = pd.read_csv(BASE / "out/rotor_noise.csv").set_index("name")
worst = 0.0
for nm, row in TAB.set_index("name").iterrows():
    nav = int(round(row.n_avg_rev))
    worst = max(worst, abs(REV[nm][-nav:].mean() - row.CQ_mean))
print(f"largest |window mean (resampled) - table C_Q| over 53 cases: {worst:.2e}")
cmp("window means reproduce the table (max abs diff < 3e-4)", worst < 3e-4, True)
for nm in [n for n in TAB.name if n not in set(OLD.name)]:
    nav = int(round(TAB.set_index("name").loc[nm, "n_avg_rev"]))
    w = REV[nm][-nav:]
    cmp(f"s_rev {nm}", sd(w), noise.loc[nm, "s_rev"], tol_rel=0.02)
    cmp(f"last-two-revolution difference {nm}", REV[nm][-1] - REV[nm][-2], noise.loc[nm, "drift_last_two_rev"],
        tol_abs=3e-5)
    ext = REV[nm][2:]
    cmp(f"mean of revolutions 3..end {nm}", ext.mean(), noise.loc[nm, "CQ_rev3_to_end"], tol_abs=3e-5)

# truncated per-revolution lists in results.json
tr = []
for nm in TAB.name:
    rj = json.loads((RUNS / nm / "results.json").read_text())
    if len(rj["CQ_per_rev"]) != len(REV[nm]):
        tr.append(nm)
cmp("results.json lists that drop the last revolution", len(tr), len(NUM["results_json_per_rev_truncated"]))

# pooled sigma per hypothesis and speed (medium, smooth Spalding, maxCo 4)
print("=== pooled revolution scatter")
pooled = {}
for (h, U), g in TAB[(TAB.level == "medium") & TAB.Ks_um.isna() & (TAB.maxCo == 4)].groupby(["hypothesis", "U_ms"]):
    ss, dof = 0.0, 0
    for nm, nav in zip(g.name, g.n_avg_rev):
        w = REV[nm][-int(round(nav)):]
        ss += np.sum((w - w.mean()) ** 2)
        dof += len(w) - 1
    pooled[(h, U)] = math.sqrt(ss / dof)
    cmp(f"sigma_rev {h} {U:g} m/s", pooled[(h, U)], NUM["noise_model"]["pooled"][f"{h}_U{U:g}"]["sigma_rev"], tol_rel=0.02)
    cmp(f"dof {h} {U:g} m/s", dof, NUM["noise_model"]["pooled"][f"{h}_U{U:g}"]["dof"])

# ------------------------------------------------------------------ long runs (priority E)
print("=== rough-blade long runs")
L = TAB[TAB.n_avg_rev > 40].copy()
L["wall"] = ["spalding" if np.isnan(k) else f"Ks{int(k)}" for k in L.Ks_um]
lag1 = []
for _, r in L.iterrows():
    w = REV[r["name"]][5:]
    x = w - w.mean()
    lag1.append(float(np.sum(x[1:] * x[:-1]) / np.sum(x * x)))
    key = f"{r.lam:.2f}_{r.wall}"
    run = NUM["roughness"]["runs"][key]
    cmp(f"C_Q {key}", r.CQ_mean, run["CQ"], tol_abs=1e-6)
    cmp(f"C_P {key}", r.lam * r.CQ_mean, run["CP"], tol_abs=1e-7)
    cmp(f"2u {key}", 2 * sd(w) / math.sqrt(len(w)), run["two_u"], tol_rel=0.02)
    # batch means, 9 batches of 5 revolutions
    bm = w.reshape(9, 5).mean(axis=1)
    cmp(f"u batch 9x5 {key}", sd(bm) / 3, run["u_batch"], tol_rel=0.02)
    # drift: halves of the window (resampled series), each the first / last 67 blade-passing periods
    # (T/3; 45 revolutions = 135 periods), so that no half cuts a 120-degree torque cycle (19 Oct fix)
    Q = QS[r["name"]][5:].ravel()
    half = (3 * 45 // 2) * (len(Q) // 135)
    cmp(f"half-window drift {key}", Q[-half:].mean() - Q[:half].mean(), run["drift_half"], tol_abs=5e-5)
    cmp(f"pressure part {key}", r.CQ_pressure_mean, run["CQ_pressure"], tol_abs=1e-6)
cmp("lag-1 autocorrelation, min", min(lag1), NUM["noise_model"]["long_runs"]["lag1_autocorr"][0], tol_abs=0.02)
cmp("lag-1 autocorrelation, max", max(lag1), NUM["noise_model"]["long_runs"]["lag1_autocorr"][1], tol_abs=0.02)
band = (0.128 * 0.0159683, 0.162 * 0.0159683)
cmp("rig band low (12.8 % of C_Q(0.10), 13 Oct)", band[0], NUM["roughness"]["rig_band_13oct"]["lo"], tol_abs=1e-7)
cmp("rig band high (16.2 %)", band[1], NUM["roughness"]["rig_band_13oct"]["hi"], tol_abs=1e-7)
# same-speed band (verifier, 19 Oct): the rig's peak-power change at the 23.03 m/s set point
BYS = pd.read_csv(REPO / "reports/roughness_2026-09/build/derived/rotor_by_wind_speed.csv")
g23v = {rot: float(BYS[(BYS.rotor == rot) & (np.abs(BYS.wind_mps - 23.03) < 0.05)].p_max_change_vs_plain_pct.iloc[0])
        for rot in ("FS 0.10", "FS 0.20")}
cmp("rig band at 23 m/s, low (FS 0.10)", g23v["FS 0.10"] / 100 * 0.0159683, NUM["roughness"]["rig_band_23ms"]["lo"], tol_abs=1e-7)
cmp("rig band at 23 m/s, high (FS 0.20)", g23v["FS 0.20"] / 100 * 0.0159683, NUM["roughness"]["rig_band_23ms"]["hi"], tol_abs=1e-7)
for lamk, cqk in (("0.10", 0.10), ("0.12", 0.12)):
    b0 = float(TAB[(np.abs(TAB.lam - cqk) < 1e-9) & (TAB.U_ms == 23.0) & (TAB.Ks_um == 0)].CQ_mean.iloc[0])
    for i, rot in enumerate(("FS 0.10", "FS 0.20")):
        cmp(f"rig change at 23 m/s on the Ks-0 base, {rot}, lambda {lamk}", g23v[rot] / 100 * b0,
            NUM["roughness"]["rig_band_23ms"]["on_Ks0_base"][lamk][i], tol_abs=1e-7)
    s_l = math.sqrt(np.mean([sd(REV[n][5:]) ** 2 for n in TAB[TAB.n_avg_rev > 40].name]))
for rot in ("FS 0.10", "FS 0.20"):
    cmp(f"revolutions needed at 23 m/s, {rot}", math.ceil(8 * s_l ** 2 / (g23v[rot] / 100 * 0.0159683) ** 2),
        NUM["roughness"]["rig_band_23ms"]["nrev_needed_per_run_2u"][rot])
for lam in (0.10, 0.12):
    g = L[np.isclose(L.lam, lam)].set_index("wall")
    for a, b in (("Ks100", "Ks0"), ("Ks400", "Ks0"), ("Ks0", "spalding"), ("Ks100", "spalding"), ("Ks400", "spalding")):
        key = f"{lam:.2f}_{a}-{b}"
        D = NUM["roughness"]["differences"][key]
        wa, wb = REV[g.loc[a, "name"]][5:], REV[g.loc[b, "name"]][5:]
        d = g.loc[a, "CQ_mean"] - g.loc[b, "CQ_mean"]
        u = math.sqrt(sd(wa) ** 2 / 45 + sd(wb) ** 2 / 45)
        cmp(f"dC_Q {key}", d, D["dCQ"], tol_abs=1e-6)
        cmp(f"2u {key}", 2 * u, D["two_u"], tol_rel=0.02)
        cmp(f"resolved at 2u {key}", abs(d) > 2 * u, D["resolved_2u"])
        cmp(f"dC_P {key}", lam * d, D["dCP"], tol_abs=1e-7)
        cmp(f"relative change {key} (%)", 100 * d / g.loc[b, "CQ_mean"], D["rel_change_pct"], tol_abs=1e-3)
        Qa, Qb = QS[g.loc[a, "name"]][5:].ravel(), QS[g.loc[b, "name"]][5:].ravel()
        h = (3 * 45 // 2) * (len(Qa) // 135)
        dsum = abs(Qa[-h:].mean() - Qa[:h].mean()) + abs(Qb[-h:].mean() - Qb[:h].mean())
        cmp(f"drift-rule verdict {key}", abs(d) > dsum, D["resolved_drift_rule"])
        cmp(f"first-22 difference {key}", wa[:22].mean() - wb[:22].mean(), D["d_first22"], tol_abs=3e-5)
        cmp(f"last-22 difference {key}", wa[23:].mean() - wb[23:].mean(), D["d_last22"], tol_abs=3e-5)

# ------------------------------------------------------------------ sectors (phase-resolved blade torque)
print("=== azimuth sectors")
SECT = {"upwind, convex side to the wind": (330, 30), "advancing, edge-on (tip A first)": (60, 120),
        "downwind, cup to the wind": (150, 210), "returning, edge-on (curl first)": (240, 300)}


def sector_contrib(case):
    """Per-revolution contribution of each sector to the rotor C_Q (window revolutions)."""
    out = {k: np.zeros(45) for k in list(SECT) + ["gaps"]}
    for i in (1, 2, 3):
        cj, T, nrev, tt, Q = resampled(case, f"forcesBlade{i}")
        th = np.mod(360.0 * tt / T + 120.0 * (i - 1), 360.0).reshape(nrev, -1)
        for j, rr in enumerate(range(nrev - 45, nrev)):
            used = np.zeros(Q.shape[1], bool)
            for k, (lo, hi) in SECT.items():
                m = ((th[rr] >= lo) | (th[rr] < hi)) if lo > hi else ((th[rr] >= lo) & (th[rr] < hi))
                out[k][j] += Q[rr, m].sum() / Q.shape[1]
                used |= m
            out["gaps"][j] += Q[rr, ~used].sum() / Q.shape[1]
    return out


SC = {nm: sector_contrib(nm) for nm in L.name}
for lam in (0.10, 0.12):
    g = L[np.isclose(L.lam, lam)].set_index("wall")
    for a, b in (("Ks400", "Ks0"), ("Ks400", "spalding")):
        ca, cb = SC[g.loc[a, "name"]], SC[g.loc[b, "name"]]
        tot = 0.0
        for k in list(SECT) + ["gaps"]:
            d = ca[k].mean() - cb[k].mean()
            u = math.sqrt(sd(ca[k]) ** 2 / 45 + sd(cb[k]) ** 2 / 45)
            kk = k if k != "gaps" else "the four 30° gaps between"
            ref = NUM["roughness"]["sectors"][f"{lam:.2f}_{a}-{b}_{kk}"]
            cmp(f"sector {lam:.2f} {a}-{b} {k}", d, ref["d"], tol_abs=1e-4)
            cmp(f"sector 2u {lam:.2f} {a}-{b} {k}", 2 * u, ref["two_u"], tol_rel=0.05)
            tot += d
        cmp(f"sectors add to the total {lam:.2f} {a}-{b}", tot, g.loc[a, "CQ_mean"] - g.loc[b, "CQ_mean"], tol_abs=1e-4)

# ------------------------------------------------------------------ mesh check
print("=== mesh check")
sA = pooled[("A", 23.0)]


def crossing(lams, qs, us):
    """Last + to - sign change, linear interpolation; u from a numerical derivative of lam0(q1, q2)."""
    res = None
    for i in range(len(lams) - 1):
        q1, q2 = qs[i], qs[i + 1]
        if q1 > 0 > q2:
            f = lambda a, b: lams[i] + (lams[i + 1] - lams[i]) * a / (a - b)  # noqa: E731
            l0 = f(q1, q2)
            h = 1e-7
            d1 = (f(q1 + h, q2) - f(q1 - h, q2)) / (2 * h)
            d2 = (f(q1, q2 + h) - f(q1, q2 - h)) / (2 * h)
            res = (l0, math.hypot(d1 * us[i], d2 * us[i + 1]))
    return res


T = TAB.set_index("name")
prod23 = TAB[(TAB.hypothesis == "A") & (TAB.U_ms == 23) & (TAB.sense == "CCW") & (TAB.level == "medium")
             & TAB.Ks_um.isna() & (TAB.maxCo == 4) & (TAB.n_avg_rev <= 3)].sort_values("lam")
lev = {}
for lvl in ("coarse", "fine"):
    g = TAB[(TAB.level == lvl)].sort_values("lam")
    lev[lvl] = g
lev["medium"] = prod23
for lvl in ("coarse", "medium", "fine"):
    g = lev[lvl]
    lam_, q_, n_ = g.lam.tolist(), g.CQ_mean.tolist(), g.n_avg_rev.tolist()
    l0, ul = crossing(lam_, q_, [sA / math.sqrt(n) for n in n_])
    cmp(f"zero-torque lambda, {lvl}, table window", l0, NUM["grid"]["lam0"][lvl]["lam0"], tol_abs=2e-4)
    cmp(f"2u, {lvl}, table window", 2 * ul, NUM["grid"]["lam0"][lvl]["two_u"], tol_rel=0.03)
    qe = [REV[nm][2:].mean() for nm in g.name]
    ne = [len(REV[nm]) - 2 for nm in g.name]
    l0e, ule = crossing(lam_, qe, [sA / math.sqrt(n) for n in ne])
    cmp(f"zero-torque lambda, {lvl}, revolutions 3..end", l0e, NUM["grid"]["lam0"][lvl]["lam0_ext"], tol_abs=2e-4)
co2 = TAB[(TAB.maxCo == 2) & (TAB.sense == "CCW")].iloc[0]
qm = prod23.CQ_mean.tolist()
qm[prod23.lam.tolist().index(0.15)] = co2.CQ_mean
l0, _ = crossing(prod23.lam.tolist(), qm, [sA / math.sqrt(3)] * len(qm))
cmp("zero-torque lambda, medium with maxCo 2 at 0.15", l0, NUM["grid"]["lam0"]["medium_maxCo2"]["lam0"], tol_abs=2e-4)
gd = NUM["grid"]["differences"]
for lam in (0.10, 0.15):
    c = TAB[(TAB.level == "coarse") & np.isclose(TAB.lam, lam)].CQ_mean.iloc[0]
    m = prod23[np.isclose(prod23.lam, lam)].CQ_mean.iloc[0]
    f = TAB[(TAB.level == "fine") & np.isclose(TAB.lam, lam)].CQ_mean.iloc[0]
    cmp(f"fine - medium at {lam}", f - m, gd[f"{lam:.2f}"]["fine_minus_medium"], tol_abs=1e-6)
    cmp(f"medium - coarse at {lam}", m - c, gd[f"{lam:.2f}"]["medium_minus_coarse"], tol_abs=1e-6)
    cmp(f"convergence ratio R at {lam}", (m - f) / (c - m), gd[f"{lam:.2f}"]["R"], tol_rel=1e-4)
    cmp(f"2u of a 3-revolution difference at {lam}", 2 * math.sqrt(2) * sA / math.sqrt(3),
        gd[f"{lam:.2f}"]["two_u_diff"], tol_rel=0.02)

# ------------------------------------------------------------------ zero-torque lambda by speed, 38 m/s run
print("=== zero-torque lambda by speed and the 38 m/s run")
for U in (10.2, 23.0, 38.0):
    g = TAB[(TAB.hypothesis == "A") & np.isclose(TAB.U_ms, U) & (TAB.sense == "CCW") & (TAB.level == "medium")
            & TAB.Ks_um.isna() & (TAB.maxCo == 4) & (TAB.n_avg_rev <= 3)].sort_values("lam")
    s = pooled[("A", U)]
    l0, ul = crossing(g.lam.tolist(), g.CQ_mean.tolist(), [s / math.sqrt(n) for n in g.n_avg_rev])
    ref = NUM["lambda0_by_speed"][f"{U:g}"]
    cmp(f"zero-torque lambda {U:g} m/s", l0, ref["lam0"], tol_abs=2e-4)
    cmp(f"2u {U:g} m/s", 2 * ul, ref["two_u"], tol_rel=0.03)
    qe = [REV[nm][2:].mean() for nm in g.name]
    l0e, _ = crossing(g.lam.tolist(), qe, [1.0] * len(qe))
    cmp(f"zero-torque lambda {U:g} m/s, revolutions 3..end", l0e, ref["lam0_ext"], tol_abs=2e-4)
n8, n16 = "A_rot_U38.0_lam0.300_SST_medium_senseCCW", "A_rot_U38.0_lam0.300_SST_medium_senseCCW_rev16a8"
u38 = NUM["u38"]
cmp("38 m/s lambda 0.30, 16-rev mean", T.loc[n16, "CQ_mean"], u38["rev16"]["CQ_mean"], tol_abs=1e-6)
cmp("16-rev minus 8-rev", T.loc[n16, "CQ_mean"] - T.loc[n8, "CQ_mean"], u38["d_16_minus_8"], tol_abs=1e-6)
s38 = pooled[("A", 38.0)]
cmp("2u of that difference", 2 * math.hypot(s38 / math.sqrt(8), s38 / math.sqrt(3)), u38["two_u_d"], tol_rel=0.02)
cmp("16-rev last-two-revolution difference", REV[n16][-1] - REV[n16][-2], u38["rev16"]["drift_last_two_rev"], tol_abs=3e-5)
cmp("8-rev last-two-revolution difference", REV[n8][-1] - REV[n8][-2], u38["rev8"]["drift_last_two_rev"], tol_abs=3e-5)
cmp("16-rev own s_rev (last 8)", sd(REV[n16][-8:]), u38["rev16"]["s_rev_own"], tol_rel=0.02)
dw = DW[(DW.rotor == "Plain") & (DW.speed_ok.astype(str) == "True")]
lam_rig38 = [dw[(np.isclose(dw.wind_mps, x, atol=0.02)) & (dw.run == r)].tip_speed_ratio.max()
             for x in (37.95,) for r in (1, 2)]
cmp("rig light-load lambda 38 m/s (mean of runs)", float(np.mean(lam_rig38)), float(np.mean(NUM["rig_light_load"]["38"])),
    tol_abs=1e-6)
cmp("gap rig - CFD at 38 m/s", float(np.mean(lam_rig38)) - NUM["lambda0_by_speed"]["38"]["lam0"], u38["gap_rig_minus_cfd"],
    tol_abs=1e-5)

# ------------------------------------------------------------------ physics link and revolutions needed
print("=== physics link (Stage 2 table, quasi-steady estimate) and revolutions needed")
S2 = pd.read_csv(REPO / "cfd/stage2/results/stage2_polars.csv")
pl = NUM["physics_link"]
for al in (90, 180):
    for ks in (0, 100, 400):
        r = S2[(S2.wall == "wf") & (S2.alpha_deg == al) & (S2.Ks_um == ks) & (S2.maxCo == 2.5) & (S2.U_ms == 23)]
        assert len(r) == 1
        cmp(f"Stage 2 Cd alpha {al} Ks {ks}", r.Cd_mean.iloc[0], pl["stage2_wall_function_maxCo2p5"][f"a{al}_Ks{ks}"]["Cd"],
            tol_abs=1e-6)
rc_ = json.loads((REPO / "cfd/rotor2d/layout/poses_A_B.json").read_text())["poses"][0]["r_centroid_m"]
cd0 = S2[(S2.wall == "wf") & (S2.alpha_deg == 90) & (S2.Ks_um == 0) & (S2.maxCo == 2.5)].Cd_mean.iloc[0]
for ks in (100, 400):
    cdk = S2[(S2.wall == "wf") & (S2.alpha_deg == 90) & (S2.Ks_um == ks) & (S2.maxCo == 2.5)].Cd_mean.iloc[0]
    for lam in (0.10, 0.12):
        # force per unit span 0.5 rho ((1-lam)U)^2 c dCd at lever arm r_c, over 0.5 rho U^2 (2R) R
        q = ((1 - lam) ** 2 * 0.048 * (cdk - cd0) * rc_) / (2 * 0.1016 * 0.1016)
        cmp(f"quasi-steady dC_Q one blade, theta 90, Ks {ks}, lambda {lam}", q,
            pl["quasi_steady_dCQ_single_blade_theta90"][f"Ks{ks}_lam{lam:.2f}"], tol_rel=1e-4)
srms = math.sqrt(np.mean([sd(REV[nm][5:]) ** 2 for nm in L.name]))
for k, v in (("FS 0.10", band[0]), ("FS 0.20", band[1])):
    cmp(f"revolutions needed per run, {k}", math.ceil(8 * srms ** 2 / v ** 2), NUM["nrev_needed_per_run_2u"]["n"][k])

# ------------------------------------------------------------------ health
print("=== health")
hl = pd.read_csv(BASE / "out/rotor_health.csv")
prox = []
for _, r in pd.concat([TAB, STA]).iterrows():
    mi = json.loads((RUNS / r["name"] / "mesh_info.json").read_text())
    prox.append(r.maxCo * mi["params"]["ds_corner"] / (r.dt_mean_s * r.U_ms))
cmp("time-step proxy, max over 69 rotor cases", max(prox), NUM["health"]["all"]["u_co_over_U"][1], tol_rel=1e-4)
cmp("flagged rotor cases (proxy > 5)", int(sum(p > 5 for p in prox)), NUM["health"]["all"]["n_flagged"])
allc = pd.concat([TAB, STA])
sym = ((allc.Cx_mean < 0) | (allc.Cy_mean.abs() > 3) | (allc.omega_bounded_steps > 0)
       | (allc.ami_weight_min < 0.999) | (allc.ami_weight_max > 1.001) | (allc.Co_max_mean > 1.01 * allc.maxCo)
       | (allc.yplus_mean < 11) | (allc.yplus_mean > 300) | (allc.yplus_max > 300))
cmp("cases with a symptom (without the C_Q std test)", int(sym.sum()), NUM["health"]["all"]["n_any_symptom"])
cmp("health table rows", len(hl), 69)

print(f"\n{NOK[0]} OK, {NCHECK[0]} CHECK")
