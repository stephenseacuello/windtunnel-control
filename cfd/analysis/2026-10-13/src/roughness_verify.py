#!/usr/bin/env python3
"""Independent check of the Stage 2 (roughness) numbers, written by the verifier on 13 Oct 2026.

    nice -n 10 python3 cfd/analysis/2026-10-13/src/roughness_verify.py

Recomputes every number quoted in the Stage 2 findings directly from data/stage2_polars.csv
(and data/section_polars.csv, the report's build/ files), without importing roughness_analysis.py.
Prints the checks; writes nothing. Drift rule (cfd/stage2/compare_roughness.py): a change between
cases a and b is resolved when |X_a - X_b| > |drift_a| + |drift_b|.
"""
import itertools
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parents[2]
REP = REPO / "reports" / "roughness_2026-09" / "build"
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 60)
pd.set_option("display.max_rows", 300)

d = pd.read_csv(ROOT / "data" / "stage2_polars.csv")
s1 = pd.read_csv(ROOT / "data" / "section_polars.csv")
d["t"] = d.tex_t_mm.round(3)


def row(name):
    r = d[d["name"] == name]
    assert len(r) == 1, (name, len(r))
    return r.iloc[0]


def wf(a, U, ks, co):
    suf = "_Co2.5n2" if co == 2.5 else ""
    return row(f"a{a:05.1f}_U{U:.1f}_SST_wf_Ks{ks}_Tu1.0{suf}")


def tex(a, m, t):
    return row(f"a{a:05.1f}_U23.0_{m}_tex{t:.3f}_s1_Tu1.0_N80A50")


def change(r, r0, q="Cd"):
    dq = r[f"{q}_mean"] - r0[f"{q}_mean"]
    n = abs(r[f"{q}_drift"]) + abs(r0[f"{q}_drift"])
    return dq, 100 * dq / abs(r0[f"{q}_mean"]), n, abs(dq) > n


def rank(x):
    return pd.Series(x).rank().to_numpy()


def rho(x, y):
    return float(np.corrcoef(rank(x), rank(y))[0, 1])


def perm(x, y):
    o = abs(rho(x, y))
    y = np.asarray(y)
    ps = list(itertools.permutations(range(len(y))))
    return sum(abs(rho(x, y[list(p)])) >= o - 1e-12 for p in ps) / len(ps)


def ols(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    A = np.vstack([np.ones_like(x), x]).T
    coef, res, *_ = np.linalg.lstsq(A, y, rcond=None)
    yhat = A @ coef
    s2 = ((y - yhat) ** 2).sum() / (len(x) - 2)
    cov = s2 * np.linalg.inv(A.T @ A)
    r2 = 1 - ((y - yhat) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    return coef[1], np.sqrt(cov[1, 1]), r2


KS = [0, 50, 100, 200, 400]
print("=" * 30, "R2-R4: wall-function sweeps at 23 m/s")
for a, co in ((0, 2.5), (90, 5.0), (180, 5.0)):
    r0 = wf(a, 23, 0, co)
    print(f"-- alpha {a}, maxCo {co}; ref {r0['name']} ({r0.ran_on})")
    xs, cds, cls = [], [], []
    for ks in KS:
        r = wf(a, 23, ks, co)
        dCd, pCd, nCd, okCd = change(r, r0, "Cd")
        dCl, pCl, nCl, okCl = change(r, r0, "Cl")
        print(f"Ks {ks:3d}: Cd {r.Cd_mean:.4f} d {dCd:+.4f} ({pCd:+.2f}%) noise {nCd:.4f} res {okCd} | "
              f"dCdp {r.Cd_pressure_mean - r0.Cd_pressure_mean:+.4f} dCdv {r.Cd_viscous_mean - r0.Cd_viscous_mean:+.4f} "
              f"Cdv {r.Cd_viscous_mean:.4f} | Cl {r.Cl_mean:.4f} dCl {dCl:+.4f} ({pCl:+.1f}%) nCl {nCl:.4f} res {okCl} | "
              f"St {r.St:.4f} ({100 * (r.St / r0.St - 1):+.1f}%) Cd_std {r.Cd_std:.3f} cyc {r.n_cycles_avg:.2f} "
              f"drift {r.Cd_drift:+.5f} y+ {r.yplus_blade_mean:.1f} on {r.ran_on}")
        xs.append(ks), cds.append(r.Cd_mean), cls.append(r.Cl_mean)
    for q, y in (("Cd", cds), ("Cl", cls)):
        b, se, r2 = ols(xs, y)
        print(f"   {q}: slope {100 * b:+.4f} +/- {100 * se:.4f} per 100 um, R2 {r2:.3f}, rho {rho(xs, y):+.0f}, "
              f"perm p {perm(xs, y):.4f}")

print("-- alpha 0, maxCo 5 set vs its Ks 50")
r50 = wf(0, 23, 50, 5.0)
for ks in (200, 400):
    r = wf(0, 23, ks, 5.0)
    dCd, p, n, ok = change(r, r50)
    print(f"Ks {ks}: Cd {r.Cd_mean:.4f} d {dCd:+.4f} ({p:+.2f}%) noise {n:.4f} res {ok}")

print("=" * 30, "R1: D = Cd(0) - Cd(180)")
lam = np.linspace(0, 0.25, 251)


def dset(label, pairs):
    a0, b0 = pairs[0][1], pairs[0][2]
    D0 = a0.Cd_mean - b0.Cd_mean
    n0 = abs(a0.Cd_drift) + abs(b0.Cd_drift)
    print(f"-- {label}")
    for x, a, b in pairs:
        D = a.Cd_mean - b.Cd_mean
        n = abs(a.Cd_drift) + abs(b.Cd_drift)
        dD = D - D0
        d0, d180 = a.Cd_mean - a0.Cd_mean, b.Cd_mean - b0.Cd_mean
        dN = d0 * (1 - lam) ** 2 - d180 * (1 + lam) ** 2
        # drift-rule noise of the weighted drive change at each lambda
        nN = ((abs(a.Cd_drift) + abs(a0.Cd_drift)) * (1 - lam) ** 2
              + (abs(b.Cd_drift) + abs(b0.Cd_drift)) * (1 + lam) ** 2)
        sign = "+" if (dN > 0).all() else "-" if (dN < 0).all() else "mixed"
        resN = "all" if (abs(dN) > nN).all() else "none" if (abs(dN) <= nN).all() else "some"
        print(f"{x}: Cd0 {a.Cd_mean:.4f} Cd180 {b.Cd_mean:.4f} D {D:.4f} dD {dD:+.4f} ({100 * dD / D0:+.2f}%) "
              f"noise {n + n0:.4f} res {abs(dD) > n + n0} | dN sign {sign}, dN(0.125) "
              f"{np.interp(0.125, lam, dN):+.4f} noise {np.interp(0.125, lam, nN):.4f} resolved over lam: {resN}")
    return D0


dset("wf mixed (0 at Co2.5, 180 at Co5)", [(k, wf(0, 23, k, 2.5), wf(180, 23, k, 5.0)) for k in KS])
dset("wf both Co5 (ref Ks 50)", [(k, wf(0, 23, k, 5.0), wf(180, 23, k, 5.0)) for k in (50, 200, 400)])
dset("wf mixed (ref Ks 50, for the Co5 comparison)", [(k, wf(0, 23, k, 2.5), wf(180, 23, k, 5.0)) for k in (50, 200, 400)])
for m in ("SST", "LM"):
    dset(f"tex {m}", [(t, tex(0, m, t), tex(180, m, t)) for t in (0.0, 0.05, 0.10, 0.20)])

print("=" * 30, "R5: time step pairs")
for U, kss in ((23, (50, 200, 400)), (38, (0, 100, 200))):
    for ks in kss:
        c5, c25 = wf(0, U, ks, 5.0), wf(0, U, ks, 2.5)
        dd = c5.Cd_mean - c25.Cd_mean
        n = abs(c5.Cd_drift) + abs(c25.Cd_drift)
        print(f"U {U} Ks {ks}: Co5 {c5.Cd_mean:.4f} Co2.5 {c25.Cd_mean:.4f} d {dd:+.4f} ({100 * dd / c25.Cd_mean:+.2f}%) "
              f"noise {n:.4f} res {abs(dd) > n} dCl {c5.Cl_mean - c25.Cl_mean:+.4f} dSt {100 * (c5.St / c25.St - 1):+.2f}% "
              f"dt5 {c5.dt_mean_s * 1e6:.2f}us dt2.5 {c25.dt_mean_s * 1e6:.2f}us")
for U, ref, kss in ((23, 50, (200, 400)), (38, 0, (100, 200))):
    for ks in kss:
        e5 = wf(0, U, ks, 5.0).Cd_mean - wf(0, U, ref, 5.0).Cd_mean
        e25 = wf(0, U, ks, 2.5).Cd_mean - wf(0, U, ref, 2.5).Cd_mean
        print(f"U {U}: Ks {ks}-{ref}: Co5 {e5:+.4f} Co2.5 {e25:+.4f} diff {e5 - e25:+.4f} "
              f"({100 * (e5 - e25) / wf(0, U, ref, 2.5).Cd_mean:+.2f} pp)")

print("=" * 30, "R6: speed sweep and Ks+ collapse (alpha 0)")
xs, ys, lab = [], [], []
for U, co, kss in ((10.2, 2.5, (100, 200)), (23, 2.5, (50, 100, 200, 400)), (38, 2.5, (100, 200)), (38, 5.0, (100, 200))):
    r0 = wf(0, U, 0, co)
    for ks in kss:
        r = wf(0, U, ks, co)
        dCd, p, n, ok = change(r, r0)
        print(f"U {U} Co {co} Ks {ks}: dCd {dCd:+.4f} ({p:+.2f}%) noise {n:.4f} ratio {abs(dCd) / n:.2f} res {ok} "
              f"Ks+ mean {r.ksplus_blade_mean:.2f} max {r.ksplus_blade_max:.1f} y+ {r.yplus_blade_mean:.1f}")
        xs.append(r.ksplus_blade_mean), ys.append(p), lab.append((U, co, ks))
xs, ys = np.array(xs), np.array(ys)
b = (xs * ys).sum() / (xs * xs).sum()
res = ys - b * xs
se = np.sqrt((res ** 2).sum() / (len(xs) - 1) / (xs * xs).sum())
print(f"fit through 0 (n {len(xs)}): {b:.4f} +/- {se:.4f} %/Ks+, rms {np.sqrt((res ** 2).mean()):.3f} max {abs(res).max():.3f}")
m25 = np.array([c == 2.5 for _, c, _ in lab])
b2 = (xs[m25] * ys[m25]).sum() / (xs[m25] ** 2).sum()
print(f"fit through 0, maxCo 2.5 only (n {m25.sum()}): {b2:.4f} %/Ks+")
for i in range(len(xs)):
    print(f"   {lab[i]}: Ks+ {xs[i]:.2f} d% {ys[i]:+.2f} resid {res[i]:+.2f}")

print("=" * 30, "R7: wall-function validity")
w = d[d.wall == "wf"]
rw = w[w.Ks_um > 0]
print("Ks/yP", rw.Ks_over_yP.min(), rw.Ks_over_yP.max(), "| 10.2 m/s max", rw[rw.U_ms == 10.2].Ks_over_yP.max())
print("yP um", sorted(set((w.yP_m * 1e6).round(1))))
for k, g in rw.groupby("Ks_um"):
    print(f"Ks {k}: Ks+ mean {g.ksplus_blade_mean.min():.2f}-{g.ksplus_blade_mean.max():.2f}, "
          f"max {g.ksplus_blade_max.min():.1f}-{g.ksplus_blade_max.max():.1f}; n {len(g)}")
print("Ks+ max overall", rw.ksplus_blade_max.max(), rw.loc[rw.ksplus_blade_max.idxmax(), "name"])
print("n cases with Ks+ max > 90:", (rw.ksplus_blade_max > 90).sum(), list(rw[rw.ksplus_blade_max > 90]["name"]))
print("y+ mean", w.yplus_blade_mean.min(), w.yplus_blade_mean.max(), "y+ max", w.yplus_blade_max.min(), w.yplus_blade_max.max())
print("y+ bladeEnds mean", w.yplus_bladeEnds_mean.min(), w.yplus_bladeEnds_mean.max())
# Ks+ consistency: ksplus_mean ~ y+ Ks / yP ?
chk = (rw.ksplus_blade_mean - rw.yplus_blade_mean * rw.Ks_um * 1e-6 / rw.yP_m).abs().max()
print("max |Ks+ - y+ Ks/yP| =", chk)

print("=" * 30, "R8-R9: texture")
for a in (0, 180):
    for m in ("SST", "LM"):
        r0 = tex(a, m, 0.0)
        for t in (0.0, 0.05, 0.10, 0.20):
            r = tex(a, m, t)
            dCd, p, n, ok = change(r, r0)
            dCl, pl, nl, okl = change(r, r0, "Cl")
            print(f"a {a} {m} t {t:.2f}: Cd {r.Cd_mean:.4f} d {dCd:+.4f} ({p:+.2f}%) noise {n:.4f} ratio "
                  f"{abs(dCd) / n:.2f} res {ok} | dCdp {r.Cd_pressure_mean - r0.Cd_pressure_mean:+.4f} "
                  f"dCdv {r.Cd_viscous_mean - r0.Cd_viscous_mean:+.4f} Cdv {r.Cd_viscous_mean:+.5f} | Cl {r.Cl_mean:+.4f} "
                  f"dCl {dCl:+.4f} nCl {nl:.4f} res {okl} | St {r.St:.4f} pk {r.St_peak_frac:.3f} Cd_std {r.Cd_std:.4f} "
                  f"drift {r.Cd_drift:+.4f} cyc {r.n_cycles_avg:.2f} {r.mesh_check}")
print("-- SST - LM")
for a in (0, 180):
    for t in (0.0, 0.05, 0.10, 0.20):
        s, l = tex(a, "SST", t), tex(a, "LM", t)
        dd = s.Cd_mean - l.Cd_mean
        n = abs(s.Cd_drift) + abs(l.Cd_drift)
        print(f"a {a} t {t:.2f}: SST {s.Cd_mean:.4f} LM {l.Cd_mean:.4f} d {dd:+.4f} ({100 * dd / l.Cd_mean:+.2f}%) "
              f"noise {n:.4f} res {abs(dd) > n}")
for t in (0.0, 0.05, 0.10, 0.20):
    Ds = tex(0, "SST", t).Cd_mean - tex(180, "SST", t).Cd_mean
    Dl = tex(0, "LM", t).Cd_mean - tex(180, "LM", t).Cd_mean
    n = sum(abs(tex(a, m, t).Cd_drift) for a in (0, 180) for m in ("SST", "LM"))
    print(f"t {t:.2f}: D SST {Ds:.4f} D LM {Dl:.4f} diff {Ds - Dl:+.4f} ({100 * (Ds - Dl) / Dl:+.1f}%) noise {n:.4f}")
print("Re_k = U t / nu (nu 1.516e-5):", [round(23 * t * 1e-3 / 1.516e-5, 1) for t in (0.05, 0.1, 0.2)])
nu_csv = 23 * 0.048 / d.Re_c[d.U_ms == 23].iloc[0]
print("nu implied by Re_c in the CSV:", nu_csv)

print("=" * 30, "R11: required section change (quasi-steady two-position model)")
comp = pd.read_csv(REP / "derived" / "comparisons.csv")
bys = pd.read_csv(REP / "derived" / "rotor_by_wind_speed.csv")
cp = comp[comp.relative_to == "Plain"].set_index("rotor")
v23 = bys.wind_mps.iloc[(bys.wind_mps - 23).abs().argmin()]
at23 = bys[np.isclose(bys.wind_mps, v23)].set_index("rotor")
print("measured:", cp[["change_pct", "tukey95_lo_pct", "tukey95_hi_pct"]].round(2).to_dict("index"))
print("at", v23, ":", at23[["p_max_change_vs_plain_pct", "pointwise95_halfwidth_pct"]].round(2).to_dict("index"))
for L in (0.125, 0.08):
    for lab_, c0, c1 in (("shells", 2.3, 1.2), ("CFD Ks0", wf(0, 23, 0, 2.5).Cd_mean, wf(180, 23, 0, 5.0).Cd_mean)):
        N = c0 * (1 - L) ** 2 - c1 * (1 + L) ** 2
        out = []
        for g in (cp.loc["FS 0.10", "change_pct"], cp.loc["FS 0.20", "change_pct"],
                  at23.loc["FS 0.10", "p_max_change_vs_plain_pct"], at23.loc["FS 0.20", "p_max_change_vs_plain_pct"]):
            dN = g / 100 * N
            out.append(f"{g:.1f}%: dCd0 {100 * dN / (1 - L) ** 2 / c0:+.2f}% or dCd180 {-100 * dN / (1 + L) ** 2 / c1:+.2f}%")
        print(f"lam {L} {lab_}: N {N:.4f}; " + "; ".join(out))
# lambda at which N is maximal for the CFD values: P ~ lam * N(lam)
for lab_, c0, c1 in (("shells", 2.3, 1.2), ("CFD Ks0", wf(0, 23, 0, 2.5).Cd_mean, wf(180, 23, 0, 5.0).Cd_mean)):
    L = np.linspace(0, 0.5, 5001)
    P = L * (c0 * (1 - L) ** 2 - c1 * (1 + L) ** 2)
    print(f"{lab_}: optimum lam of lam*N = {L[P.argmax()]:.3f}")
# noise as % of Cd
for a, co in ((0, 2.5), (180, 5.0), (90, 5.0)):
    r0 = wf(a, 23, 0, co)
    ns = [100 * (abs(wf(a, 23, k, co).Cd_drift) + abs(r0.Cd_drift)) / r0.Cd_mean for k in (50, 100, 200, 400)]
    print(f"noise % of Cd, alpha {a}: {min(ns):.2f}-{max(ns):.2f}")
for a in (0, 180):
    for m in ("SST", "LM"):
        r0 = tex(a, m, 0.0)
        ns = [100 * (abs(tex(a, m, t).Cd_drift) + abs(r0.Cd_drift)) / r0.Cd_mean for t in (0.05, 0.1, 0.2)]
        print(f"noise % of Cd, tex alpha {a} {m}: {min(ns):.2f}-{max(ns):.2f}")

print("=" * 30, "R12: mapping")
surf = pd.read_csv(REP / "derived" / "surface_roughness.csv").set_index("rotor")
c0s = [wf(0, 23, k, 2.5).Cd_mean for k in KS]
c1s = [wf(180, 23, k, 5.0).Cd_mean for k in KS]


def Dk(k):
    k = min(k, 400)
    return np.interp(k, KS, c0s) - np.interp(k, KS, c1s)


kscan = {"Plain": (38, 38), "FS 0.05": (38, 38), "FS 0.10": (38, 38), "FS 0.20": (84, 97)}
tset = {"Plain": 0, "FS 0.05": 0.050, "FS 0.10": 0.101, "FS 0.20": 0.202}
for rule in ("k", "Ra", "Pa", "2.09t"):
    vals = {}
    for rot in kscan:
        ra, pa = surf.loc[rot, "Ra_lc025_um"], surf.loc[rot, "Pa_um"]
        lo, hi = {"k": kscan[rot], "Ra": (3 * ra, 6 * ra), "Pa": (3 * pa, 6 * pa),
                  "2.09t": (2090 * tset[rot], 2090 * tset[rot])}[rule]
        vals[rot] = (lo, hi, Dk(0.5 * (lo + hi)), Dk(lo), Dk(hi))
    p = vals["Plain"][2]
    print(rule, {r: (round(v[0]), round(v[1]), f"{100 * (v[2] - p) / p:+.2f}%") for r, v in vals.items()})
    if rule in ("Ra", "Pa"):
        # one common multiplier m (3-6) for every surface: range of the D change against Plain, and whether any
        # m gives the measured order FS 0.20 > FS 0.10 > FS 0.05
        col = "Ra_lc025_um" if rule == "Ra" else "Pa_um"
        ms = np.linspace(3, 6, 61)
        g = {rot: [100 * (Dk(m * surf.loc[rot, col]) - Dk(m * surf.loc["Plain", col])) / Dk(m * surf.loc["Plain", col])
                   for m in ms] for rot in ("FS 0.05", "FS 0.10", "FS 0.20")}
        order = any(Dk(m * surf.loc["FS 0.20", col]) > Dk(m * surf.loc["FS 0.10", col]) > Dk(m * surf.loc["FS 0.05", col])
                    for m in ms)
        print("   common multiplier 3-6:", {r: (round(min(v), 2), round(max(v), 2)) for r, v in g.items()},
              "| measured order for some m:", order)

print("-- two-position drive in each flow state (zero-drive lam = (1 - r)/(1 + r), r = sqrt(Cd180/Cd0))")
for lab_, a0, a1 in (("wf Ks 0 (high-drag)", wf(0, 23, 0, 2.5), wf(180, 23, 0, 5.0)),
                     ("wf Ks 400", wf(0, 23, 400, 2.5), wf(180, 23, 400, 5.0)),
                     ("tex SST t 0 (low-drag)", tex(0, "SST", 0.0), tex(180, "SST", 0.0)),
                     ("tex LM t 0 (low-drag)", tex(0, "LM", 0.0), tex(180, "LM", 0.0))):
    c0, c1 = a0.Cd_mean, a1.Cd_mean
    r_ = np.sqrt(c1 / c0)
    print(f"{lab_}: N(0.125) {c0 * 0.875 ** 2 - c1 * 1.125 ** 2:+.4f}, zero-drive lam {(1 - r_) / (1 + r_):.3f}")
pdw = pd.read_csv(REP / "tacho" / "per_dwell.csv")
pdw = pdw[pdw.speed_ok == True]  # noqa: E712
lt = pdw.groupby(["rotor", "fan_rpm"]).agg(U=("wind_mps", "mean"), lam_max=("tsr", "max")).reset_index()
for U0 in (23.03, 37.95):
    sel = lt[np.isclose(lt.U, U0, atol=0.05)]
    print(f"rig light-load (largest) lam at {U0} m/s:", dict(zip(sel.rotor, sel.lam_max.round(3))))
print("rig rotor-speed change vs Plain (Tukey 95%):",
      cp[["rotor_rpm_change_pct", "rotor_rpm_tukey95_lo_pct", "rotor_rpm_tukey95_hi_pct"]].round(1).to_dict("index"))
print("-- residual scatter about straight lines in Ks (23 m/s), against the drift-rule noise")
for a, co in ((0, 2.5), (180, 5.0)):
    y = np.array([wf(a, 23, k, co).Cd_mean for k in KS])
    A = np.vstack([np.ones(5), KS]).T
    res = y - A @ np.linalg.lstsq(A, y, rcond=None)[0]
    print(f"alpha {a}: residual rms {np.sqrt((res ** 2).mean()):.4f}, max {abs(res).max():.4f}; per-case |drift| "
          f"{min(abs(wf(a, 23, k, co).Cd_drift) for k in KS):.4f}-{max(abs(wf(a, 23, k, co).Cd_drift) for k in KS):.4f}")
print("-- oscillation size at alpha 0 (23 m/s, maxCo 2.5): Cd_std and Cl_std, Ks 0 -> 400")
for q in ("Cd_std", "Cl_std"):
    v = [wf(0, 23, k, 2.5)[q] for k in KS]
    print(q, [round(x, 4) for x in v], f"{100 * (v[-1] / v[0] - 1):+.1f}%")
print("-- Stage 1 alpha 90 and alpha 0, SST medium/coarse at maxCo 5 and 2.5 (time-step sensitivity outside Stage 2)")
print(s1[(s1.alpha_deg.isin([0, 90])) & (s1.model == "SST") & np.isclose(s1.U_ms, 23)][
    ["name", "maxCo", "Cd_mean", "Cd_std", "St", "St_peak_frac"]].to_string())
print("-- a180 Ks 50 migration: t = 0.236 s ->", round(0.236 * 23 / 0.048, 1), "c/U (window 50-150 c/U); |drift| a180:",
      {k: round(abs(wf(180, 23, k, 5.0).Cd_drift), 5) for k in KS})
print("-- noise as % of Cd, texture (each change's drift-rule noise / its t = 0 reference Cd)")
allp = [100 * (abs(tex(a, m, t).Cd_drift) + abs(tex(a, m, 0.0).Cd_drift)) / tex(a, m, 0.0).Cd_mean
        for a in (0, 180) for m in ("SST", "LM") for t in (0.05, 0.1, 0.2)]
print(f"{min(allp):.2f}-{max(allp):.2f}")

print("=" * 30, "R13: measured by speed")
num = json.loads((REP / "numbers.json").read_text())
print({k: num.get(k) for k in ("stepVP", "stepVA", "stepVB", "stepVC", "gMaxB", "gMaxVB", "gMaxC", "gMaxVC", "bandLo", "bandHi")})
tk = dict(re.findall(r"\\newcommand\{\\(\w+)\}\{([^}]*)\}", (REP / "tacho" / "numbers.tex").read_text()))
print({k: tk.get(k) for k in ("tkTsrP", "tkTsrA", "tkTsrB", "tkTsrC")})
g = bys[bys.rotor != "Plain"]
for rot, gg in g.groupby("rotor"):
    hi = gg[gg.wind_mps > 27]
    i = gg.p_max_change_vs_plain_pct.idxmax()
    print(f"{rot}: max {gg.loc[i, 'p_max_change_vs_plain_pct']:.1f}% at {gg.loc[i, 'wind_mps']:.1f} m/s; >27 m/s "
          f"{hi.p_max_change_vs_plain_pct.min():.1f} to {hi.p_max_change_vs_plain_pct.max():.1f}%")
print("Re_c at 21 and 25 m/s:", 21 * 0.048 / nu_csv, 25 * 0.048 / nu_csv)

print("=" * 30, "R14: alpha-0 flow states")
st = []
for _, r in s1[s1.alpha_deg == 0].iterrows():
    st.append(("S1 " + r.level, r["name"], r.U_ms, r.model, r.maxCo, r.Cd_mean, r.Cl_mean, r.St, r.Cd_std))
for _, r in d[d.alpha_deg == 0].iterrows():
    st.append(("S2 " + r.wall, r["name"], r.U_ms, r.model, r.maxCo, r.Cd_mean, r.Cl_mean, r.St, r.Cd_std))
st = pd.DataFrame(st, columns=["fam", "name", "U", "model", "Co", "Cd", "Cl", "St", "Cd_std"])
for fam, gg in st.groupby("fam"):
    print(fam, f"Cd {gg.Cd.min():.3f}-{gg.Cd.max():.3f} Cl {gg.Cl.min():.3f}-{gg.Cl.max():.3f} "
               f"St {gg.St.min():.3f}-{gg.St.max():.3f} Cd_std {gg.Cd_std.min():.3f}-{gg.Cd_std.max():.3f} n {len(gg)}")
s23 = st[np.isclose(st.U, 23)]
print("23 m/s, all:", f"high Cd {s23[s23.Cd > 2.5].Cd.min():.3f}-{s23[s23.Cd > 2.5].Cd.max():.3f}, "
      f"Cl {s23[s23.Cd > 2.5].Cl.min():.3f}-{s23[s23.Cd > 2.5].Cl.max():.3f}; "
      f"low Cd {s23[s23.Cd < 2.5].Cd.min():.3f}-{s23[s23.Cd < 2.5].Cd.max():.3f}, "
      f"Cl {s23[s23.Cd < 2.5].Cl.min():.3f}-{s23[s23.Cd < 2.5].Cl.max():.3f}")
gap = wf(0, 23, 0, 2.5).Cd_mean - tex(0, "SST", 0.0).Cd_mean
big = max(abs(wf(0, 23, 400, 2.5).Cd_mean - wf(0, 23, 0, 2.5).Cd_mean), 0)
print(f"gap {gap:.4f}, largest wf dCd {big:.4f}, ratio {gap / big:.2f}")
print(st[np.isclose(st.U, 23)].sort_values("Cd").to_string())
