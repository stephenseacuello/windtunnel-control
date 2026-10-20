#!/usr/bin/env python3
"""Independent check of every Stage 2 number quoted for 15 Oct 2026 (roughness stage).

    nice -n 10 python3 cfd/analysis/2026-10-15/src/roughness_verify.py

Shares no code with roughness_analysis.py, roughness_histories.py or roughness_surface.py:
  - the table: cfd/stage2/results/stage2_polars.csv, read directly;
  - force histories: its own parser of postProcessing/forceCoeffs1/0/coefficient.dat (single-session runs only;
    every re-run of 15 Oct has one session);
  - wall pressure: its own integration, segment by segment from the two low-z points of each wall face, with
    the outward normal fixed by the polygon's orientation (roughness_surface.py uses OpenFOAM's face area vectors);
  - measured numbers: reports/roughness_2026-09/build/derived/*.csv.
Prints each quoted value against the recomputed one, OK or CHECK, and the count of CHECK lines (expected 0).
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parents[2]
RUNS = REPO / "cfd" / "stage2" / "runs"
REP = REPO / "reports" / "roughness_2026-09" / "build" / "derived"
T = pd.read_csv(REPO / "cfd" / "stage2" / "results" / "stage2_polars.csv").set_index("name")
NCHECK = [0]


def show(label, quoted, value, nd):
    """quoted: number or tuple of numbers as written in the findings; value: recomputed; nd: decimals compared."""
    q = np.atleast_1d(np.asarray(quoted, float))
    v = np.atleast_1d(np.asarray(value, float))
    ok = q.shape == v.shape and np.all(np.abs(np.round(v, nd) - q) <= 0.5 * 10.0 ** (-nd) + 1e-12)
    if not ok:
        NCHECK[0] += 1
    vs = ", ".join(f"{x:.{nd}f}" for x in v)
    print(f"{'OK   ' if ok else 'CHECK'} {label}: quoted {quoted}; recomputed {vs}")


def wf(a, ks, co, U=23.0):
    return T.loc[f"a{a:05.1f}_U{U:.1f}_SST_wf_Ks{ks}_Tu1.0" + ("_Co2.5n2" if co == 2.5 else "")]


def tex(a, m, t, co, U=23.0):
    return T.loc[f"a{a:05.1f}_U{U:.1f}_{m}_tex{t:.3f}_s1_Tu1.0_" + ("Co2.5n2" if co == 2.5 else "N80A50")]


def pct(a, b):
    return 100 * (a - b) / b


def noise(*rows):
    return sum(abs(r.Cd_drift) for r in rows)


# ------------------------------------------------------------------ own history reader
def hist(name):
    f = RUNS / name / "postProcessing" / "forceCoeffs1"
    dirs = [d for d in f.iterdir() if d.is_dir()]
    assert len(dirs) == 1, (name, dirs)
    rows = []
    for line in (dirs[0] / "coefficient.dat").read_text().splitlines():
        if line and not line.startswith("#"):
            p = line.split()
            rows.append((float(p[0]), float(p[1]), float(p[4])))
    a = np.array(rows)
    P = json.loads((RUNS / name / "case.json").read_text())
    return a[:, 0] / P["convTime"], a[:, 1], a[:, 2]


def window(t, y, w0, w1):
    m = (t >= w0 - 1e-6) & (t <= w1 + 1e-6)
    tw, yw = t[m], y[m]
    mid = 0.5 * (tw[0] + tw[-1])
    return yw.mean(), yw[tw >= mid].mean() - yw[tw < mid].mean()


print("== counts and health")
show("cases in the table / new since 13 Oct", (69, 26), (len(T), sum(1 for n in T.index if n.endswith("_Co2.5n2") and (
    "_tex" in n or n.startswith(("a090", "a180"))))), 0)
sym = (T.Cd_mean < 0) | (T.Cd_std > T.Cd_mean.abs()) | (T.Cl_mean.abs() > 3)
yp = T[["yplus_blade_max", "yplus_bladeEnds_max"]].max(axis=1)
sym |= T.index.str.contains("_tex") & (yp > 2)
show("runs with a corruption symptom", 0, int(sym.sum()), 0)
show("largest texture-run y+ (time-mean maximum)", 1.17, yp[T.index.str.contains("_tex")].max(), 2)
# family-median time-step ratio of the new runs (own grouping)
T2 = T.copy()
T2["dtc"] = T2.dt_mean_s * T2.U_ms / 0.048
fam = [("tex" if "_tex" in n else "wf") + f"{a:g}" + (f"U{u:g}" if "_wf_" in n else "") + f"Co{c:g}"
       for n, a, u, c in zip(T2.index, T2.alpha_deg, T2.U_ms, T2.maxCo)]
T2["fam"] = fam
T2["ratio"] = T2.groupby("fam").dtc.transform("median") / T2.dtc
new = [n for n in T2.index if n.endswith("_Co2.5n2") and ("_tex" in n or n.startswith(("a090", "a180")))]
show("largest family-median / run time-step ratio among the new runs", 1.27, T2.loc[new, "ratio"].max(), 2)
dt180 = T2[(T2.index.str.contains("_tex")) & (T2.alpha_deg == 180) & (T2.maxCo == 2.5) & (T2.U_ms == 23)].dt_mean_s
dt0 = T2[(T2.index.str.contains("_tex")) & (T2.alpha_deg == 0) & (T2.maxCo == 2.5)].dt_mean_s
show("texture maxCo 2.5: dt alpha 180 / alpha 0 (medians)", 0.61, dt180.median() / dt0.median(), 2)
d5a = T2[(T2.index.str.contains("_tex")) & (T2.alpha_deg == 180) & (T2.maxCo == 5)].dt_mean_s
d5b = T2[(T2.index.str.contains("_tex")) & (T2.alpha_deg == 0) & (T2.maxCo == 5)].dt_mean_s
show("texture maxCo 5: dt alpha 180 / alpha 0 (medians)", 0.61, d5a.median() / d5b.median(), 2)
show("u_Co/U with 40 um, alpha-180 texture runs at maxCo 5 (min, max)", (5.55, 5.79),
     ((5 * 40e-6 / (d5a * 23.0)).min(), (5 * 40e-6 / (d5a * 23.0)).max()), 2)
prox = 2.5 * 40e-6 / (dt180 * 23.0)
show("u_Co/U with 40 um, alpha-180 texture runs at maxCo 2.5, 23 m/s (min, max)", (5.39, 6.84), (prox.min(), prox.max()), 2)

print("== force jumps, states and start-up noise (own reader)")
t, cd, cl = hist("a000.0_U23.0_LM_tex0.000_s1_Tu1.0_Co2.5n2")
d = np.abs(np.diff(cd))
w = (t[1:] >= 50 - 1e-6) & (t[1:] <= 150 + 1e-6) & (t[:-1] >= 50 - 1e-6)
bins = sorted(set(np.floor(t[1:][w & (d > 0.5)]).astype(int).tolist()))
bins = sorted({149 if b == 150 else b for b in bins})
show("LM alpha-0 t 0 maxCo 2.5: jump intervals in the window, largest change", (19, 8.08), (len(bins), d[w].max()), 2)
tu = np.arange(t[0], t[-1], 0.02)
cu = np.interp(tu, t, cd)
k = int(8 / 0.02)
rm = np.convolve(cu, np.ones(k) / k, mode="valid")
tm = tu[:len(rm)] + 4.0
hi = rm > 2.5
late = tm >= 20
last_hi = tm[late][hi[late]][-1]
show("LM alpha-0 t 0 maxCo 2.5: last time in the high-drag state (8-c/U running mean > 2.5), c/U", 135, last_hi, 0)
show("LM alpha-0 t 0 maxCo 2.5: window mean, drift", (2.814, -0.336), window(t, cd, 50, 150), 3)
t, cd, cl = hist("a000.0_U23.0_SST_tex0.000_s1_Tu1.0_Co2.5n2")
tu = np.arange(t[0], t[-1], 0.02)
rm = np.convolve(np.interp(tu, t, cd), np.ones(k) / k, mode="valid")
tm = tu[:len(rm)] + 4.0
show("SST alpha-0 t 0 maxCo 2.5: last time above Cd 2.5 (running mean), c/U", 35, tm[(tm >= 20) & (rm > 2.5)][-1], 0)
for U, q in ((18.8, 52), (20.9, 56), (23.0, 48), (25.2, 38)):
    t, cd, cl = hist(f"a180.0_U{U:.1f}_LM_tex0.000_s1_Tu1.0_Co2.5n2")
    d = np.abs(np.diff(cd))
    m = (d > 0.1) & (t[1:] >= 2)
    show(f"smooth LM alpha 180, {U} m/s: start-up noise ends (last 1-c/U interval with a change > 0.1), c/U", q,
         np.floor(t[1:][m][-1]) + 1, 0)
ne = []
for U in (18.8, 20.9, 23.0, 25.2):
    t, cd, cl = hist(f"a180.0_U{U:.1f}_LM_tex0.200_s1_Tu1.0_Co2.5n2")
    d = np.abs(np.diff(cd))
    m = (d > 0.1) & (t[1:] >= 2)
    ne.append(np.floor(t[1:][m][-1]) + 1)
show("textured (t 0.2) LM alpha 180: start-up noise ends (min, max over the four speeds), c/U", (16, 22),
     (min(ne), max(ne)), 0)
jm = []
for ks in (0, 100, 200, 400):
    t, cd, cl = hist(f"a180.0_U23.0_SST_wf_Ks{ks}_Tu1.0_Co2.5n2")
    w = (t >= 50 - 1e-6)
    jm.append(np.abs(np.diff(cd[w])).max())
show("wf alpha 180 maxCo 2.5 (Ks 0/100/200/400): largest sample-to-sample Cd change (min, max)", (0.046, 0.053),
     (min(jm), max(jm)), 3)

print("== (1) wall functions: alpha 90 and 180 at both maxCo")
for a, co, quoted in ((90, 2.5, (0.73, 4.82, 17.27, 45.43)), (90, 5.0, (0.54, 4.72, 16.84, 44.40)),
                      (180, 2.5, (0.19, 0.75, 2.21, 5.50)), (180, 5.0, (0.22, 1.12, 2.43, 5.81))):
    r0 = wf(a, 0, co)
    show(f"alpha {a} maxCo {co}: Cd change vs Ks 0 at 50/100/200/400 um (%)", quoted,
         [pct(wf(a, k, co).Cd_mean, r0.Cd_mean) for k in (50, 100, 200, 400)], 2)
r0 = wf(180, 0, 2.5)
show("alpha 180 maxCo 2.5: change / noise at Ks 50, 100, 200, 400", (4.3, 17.8, 87.2, 43.0),
     [abs(wf(180, k, 2.5).Cd_mean - r0.Cd_mean) / noise(wf(180, k, 2.5), r0) for k in (50, 100, 200, 400)], 1)
show("alpha 180 maxCo 5: Ks 50 change / noise", 0.67, abs(wf(180, 50, 5).Cd_mean - wf(180, 0, 5).Cd_mean)
     / noise(wf(180, 50, 5), wf(180, 0, 5)), 2)
show("alpha 180 Cd at maxCo 2.5, Ks 0 and 400", (1.6218, 1.7110), (wf(180, 0, 2.5).Cd_mean, wf(180, 400, 2.5).Cd_mean), 4)
show("alpha 90 Cd at maxCo 2.5, Ks 0 and 400", (0.1932, 0.2810), (wf(90, 0, 2.5).Cd_mean, wf(90, 400, 2.5).Cd_mean), 4)
KS = [0, 50, 100, 200, 400]
ts = [pct(wf(90, k, 5).Cd_mean, wf(90, k, 2.5).Cd_mean) for k in KS]
show("alpha 90: maxCo 5 above 2.5 in Cd (min, max %)", (0.49, 1.20), (min(ts), max(ts)), 2)
ts = [pct(wf(180, k, 5).Cd_mean, wf(180, k, 2.5).Cd_mean) for k in KS]
show("alpha 180: maxCo 5 above 2.5 in Cd (min, max %)", (1.26, 1.63), (min(ts), max(ts)), 2)
e5 = wf(180, 400, 5).Cd_mean - wf(180, 0, 5).Cd_mean
e25 = wf(180, 400, 2.5).Cd_mean - wf(180, 0, 2.5).Cd_mean
show("alpha 180 Ks 400: effect at maxCo 5, 2.5, difference, its noise", (0.0955, 0.0892, 0.0063, 0.0027),
     (e5, e25, e5 - e25, noise(wf(180, 400, 5), wf(180, 0, 5), wf(180, 400, 2.5), wf(180, 0, 2.5))), 4)
r4, r0_ = wf(180, 400, 2.5), wf(180, 0, 2.5)
show("alpha 180 maxCo 2.5, Ks 400: pressure share of the Cd rise (%)", 88.2,
     100 * (r4.Cd_pressure_mean - r0_.Cd_pressure_mean) / (r4.Cd_mean - r0_.Cd_mean), 1)
show("... viscous Cd at Ks 0 and 400", (0.0085, 0.0190), (r0_.Cd_viscous_mean, r4.Cd_viscous_mean), 4)
show("alpha 90 Cl change at Ks 400 (%), maxCo 5 and 2.5", (64.1, 67.0),
     (pct(wf(90, 400, 5).Cl_mean, wf(90, 0, 5).Cl_mean), pct(wf(90, 400, 2.5).Cl_mean, wf(90, 0, 2.5).Cl_mean)), 1)
show("alpha 180 |Cl| change at Ks 400 (%), maxCo 5 and 2.5", (-6.4, -7.3),
     (pct(abs(wf(180, 400, 5).Cl_mean), abs(wf(180, 0, 5).Cl_mean)),
      pct(abs(wf(180, 400, 2.5).Cl_mean), abs(wf(180, 0, 2.5).Cl_mean))), 1)
show("alpha 90 St at Ks 0 and 400, maxCo 2.5", (0.6022, 0.5129), (wf(90, 0, 2.5).St, wf(90, 400, 2.5).St), 4)
show("... St change (%), maxCo 2.5 and 5", (-14.83, -14.78), (pct(wf(90, 400, 2.5).St, wf(90, 0, 2.5).St),
                                                          pct(wf(90, 400, 5).St, wf(90, 0, 5).St)), 2)

print("== (1) fair drag difference D (both angles at one maxCo; alpha 0 high-drag)")
D = {k: wf(0, k, 2.5).Cd_mean - wf(180, k, 2.5).Cd_mean for k in KS}
show("D, maxCo 2.5, Ks 0/50/100/200/400", (1.4860, 1.4722, 1.4173, 1.3581, 1.2098), [D[k] for k in KS], 4)
show("D change vs Ks 0 (%), maxCo 2.5", (-0.93, -4.63, -8.61, -18.59), [pct(D[k], D[0]) for k in KS[1:]], 2)
n0 = noise(wf(0, 0, 2.5), wf(180, 0, 2.5))
show("D change / noise at Ks 200 and 400 (maxCo 2.5)", (1.01, 1.76),
     [abs(D[k] - D[0]) / (n0 + noise(wf(0, k, 2.5), wf(180, k, 2.5))) for k in (200, 400)], 2)
D5 = {k: wf(0, k, 5).Cd_mean - wf(180, k, 5).Cd_mean for k in (50, 200, 400)}
n50 = noise(wf(0, 50, 5), wf(180, 50, 5))
show("D change vs Ks 50 (%), maxCo 5, Ks 200 and 400", (-8.81, -17.69), [pct(D5[k], D5[50]) for k in (200, 400)], 2)
show("... their change / noise", (0.67, 1.47), [abs(D5[k] - D5[50]) / (n50 + noise(wf(0, k, 5), wf(180, k, 5)))
                                                for k in (200, 400)], 2)
st0 = T[(T.index.str.contains("_wf_")) & (T.alpha_deg == 0)].Cd_mean
show("every wall-function alpha-0 run in the high-drag state: Cd (min, max)", (2.921, 3.146), (st0.min(), st0.max()), 3)

print("== (2) texture at maxCo 2.5 (150 c/U, last 100) against maxCo 5 (80 c/U, last 50)")
s0, s2 = tex(180, "SST", 0.0, 2.5), tex(180, "SST", 0.2, 2.5)
show("SST alpha 180 maxCo 2.5: Cd t 0, t 0.2; change (%); noise (% of Cd); ratio", (0.9026, 1.0255, 13.62, 2.41, 5.65),
     (s0.Cd_mean, s2.Cd_mean, pct(s2.Cd_mean, s0.Cd_mean), 100 * noise(s0, s2) / s0.Cd_mean,
      abs(s2.Cd_mean - s0.Cd_mean) / noise(s0, s2)), 2)
show("SST alpha 180 maxCo 5: change (%)", 13.68, pct(tex(180, "SST", 0.2, 5).Cd_mean, tex(180, "SST", 0.0, 5).Cd_mean), 2)
H = {}
for nm in ("a180.0_U23.0_SST_tex0.000_s1_Tu1.0_Co2.5n2", "a180.0_U23.0_SST_tex0.200_s1_Tu1.0_Co2.5n2",
           "a180.0_U23.0_LM_tex0.000_s1_Tu1.0_Co2.5n2", "a180.0_U23.0_LM_tex0.100_s1_Tu1.0_Co2.5n2",
           "a180.0_U23.0_LM_tex0.200_s1_Tu1.0_Co2.5n2", "a000.0_U23.0_SST_tex0.000_s1_Tu1.0_Co2.5n2",
           "a000.0_U23.0_SST_tex0.200_s1_Tu1.0_Co2.5n2") + tuple(
        f"a180.0_U{U:.1f}_LM_tex{t:.3f}_s1_Tu1.0_Co2.5n2" for U in (18.8, 20.9, 25.2) for t in (0.0, 0.2)):
    t, cd, cl = hist(nm)
    H[nm] = {w: window(t, cd, *w) for w in ((30, 80), (50, 150), (100, 150))}
a0, a2 = H["a180.0_U23.0_SST_tex0.000_s1_Tu1.0_Co2.5n2"], H["a180.0_U23.0_SST_tex0.200_s1_Tu1.0_Co2.5n2"]
show("SST alpha 180 texture effect (%) on 30-80 and 100-150 c/U", (15.48, 13.02),
     (pct(a2[(30, 80)][0], a0[(30, 80)][0]), pct(a2[(100, 150)][0], a0[(100, 150)][0])), 2)
show("SST alpha 180, maxCo 5 -> 2.5 on the same 30-80 window (%), t 0 and t 0.2", (-17.47, -16.16),
     (pct(a0[(30, 80)][0], tex(180, "SST", 0.0, 5).Cd_mean), pct(a2[(30, 80)][0], tex(180, "SST", 0.2, 5).Cd_mean)), 2)
show("SST alpha 180 t 0 maxCo 2.5: St, peak share, Cl; t 0.2: St, peak share, Cl", (0.2185, 0.9941, -0.9740, 0.1856, 0.0573, -0.6092),
     (s0.St, s0.St_peak_frac, s0.Cl_mean, s2.St, s2.St_peak_frac, s2.Cl_mean), 4)
l0, l1, l2 = tex(180, "LM", 0.0, 2.5), tex(180, "LM", 0.1, 2.5), tex(180, "LM", 0.2, 2.5)
show("LM alpha 180 maxCo 2.5: Cd t 0, 0.1, 0.2", (0.9544, 1.1003, 1.0366), (l0.Cd_mean, l1.Cd_mean, l2.Cd_mean), 4)
show("LM alpha 180 maxCo 2.5: change (%) t 0.1, t 0.2; ratios", (15.28, 8.61, 3.00, 2.03),
     (pct(l1.Cd_mean, l0.Cd_mean), pct(l2.Cd_mean, l0.Cd_mean), abs(l1.Cd_mean - l0.Cd_mean) / noise(l0, l1),
      abs(l2.Cd_mean - l0.Cd_mean) / noise(l0, l2)), 2)
show("LM alpha 180 maxCo 5: change (%) t 0.05, 0.1, 0.2", (-2.77, -1.30, 0.36),
     [pct(tex(180, "LM", t, 5).Cd_mean, tex(180, "LM", 0.0, 5).Cd_mean) for t in (0.05, 0.1, 0.2)], 2)
L = {t: H[f"a180.0_U23.0_LM_tex{t:.3f}_s1_Tu1.0_Co2.5n2"] for t in (0.0, 0.1, 0.2)}
show("LM alpha 180 texture effect t 0.1 / t 0.2 on 100-150 (%)", (14.65, 8.35),
     (pct(L[0.1][(100, 150)][0], L[0.0][(100, 150)][0]), pct(L[0.2][(100, 150)][0], L[0.0][(100, 150)][0])), 2)
show("LM alpha 180, maxCo 5 -> 2.5 on 30-80 (%), t 0 / 0.1 / 0.2", (-13.84, 0.23, -6.24),
     [pct(L[t][(30, 80)][0], tex(180, "LM", t, 5).Cd_mean) for t in (0.0, 0.1, 0.2)], 2)
show("LM alpha 180 t 0.1 maxCo 2.5: cycles in the window", 1.51, l1.n_cycles_avg, 2)
show("SST minus LM, alpha 180, t 0, maxCo 2.5: dCd and noise", (-0.0518, 0.0221), (s0.Cd_mean - l0.Cd_mean, noise(s0, l0)), 4)
show("... as % of LM", -5.43, pct(s0.Cd_mean, l0.Cd_mean), 2)
show("SST minus LM, alpha 180, t 0, maxCo 5 (% of LM)", -4.21,
     pct(tex(180, "SST", 0.0, 5).Cd_mean, tex(180, "LM", 0.0, 5).Cd_mean), 2)
show("SST minus LM, alpha 180, t 0.2, maxCo 2.5: dCd (% of LM)", -1.07, pct(s2.Cd_mean, l2.Cd_mean), 2)
Dsst = tex(0, "SST", 0.2, 2.5).Cd_mean - s2.Cd_mean
Dlm = tex(0, "LM", 0.2, 2.5).Cd_mean - l2.Cd_mean
show("D(SST) - D(LM) at t 0.2, maxCo 2.5: difference and noise", (0.0472, 0.1189),
     (Dsst - Dlm, noise(tex(0, "SST", 0.2, 2.5), s2, tex(0, "LM", 0.2, 2.5), l2)), 4)
show("... as % of D(LM)", 7.46, pct(Dsst, Dlm), 2)
show("D(SST) - D(LM) on t 0 at maxCo 5 (13 Oct, % of LM)", 18.60,
     pct(tex(0, "SST", 0.0, 5).Cd_mean - tex(180, "SST", 0.0, 5).Cd_mean,
         tex(0, "LM", 0.0, 5).Cd_mean - tex(180, "LM", 0.0, 5).Cd_mean), 2)
q0, q2 = tex(0, "SST", 0.0, 2.5), tex(0, "SST", 0.2, 2.5)
show("SST alpha 0 maxCo 2.5: Cd t 0, t 0.2, change (%), noise (% of Cd)", (1.7420, 1.7058),
     (q0.Cd_mean, q2.Cd_mean), 4)
show("... change (%), noise (% of Cd)", (-2.08, 9.20), (pct(q2.Cd_mean, q0.Cd_mean), 100 * noise(q0, q2) / q0.Cd_mean), 2)
b0, b2 = H["a000.0_U23.0_SST_tex0.000_s1_Tu1.0_Co2.5n2"], H["a000.0_U23.0_SST_tex0.200_s1_Tu1.0_Co2.5n2"]
show("SST alpha 0 texture effect on 100-150 (%) and its noise (% of Cd)", (0.74, 1.33),
     (pct(b2[(100, 150)][0], b0[(100, 150)][0]), 100 * (abs(b2[(100, 150)][1]) + abs(b0[(100, 150)][1])) / b0[(100, 150)][0]), 2)
show("LM alpha 0 maxCo 2.5: Cd t 0.1, t 0.2 (low-drag)", (1.6976, 1.6697),
     (tex(0, "LM", 0.1, 2.5).Cd_mean, tex(0, "LM", 0.2, 2.5).Cd_mean), 4)
nl = [100 * noise(tex(180, "LM", 0.0, 2.5, U), tex(180, "LM", 0.2, 2.5, U)) / tex(180, "LM", 0.0, 2.5, U).Cd_mean
      for U in (18.8, 20.9, 23.0, 25.2)] + [100 * noise(l0, l1) / l0.Cd_mean]
show("LM alpha-180 noise at maxCo 2.5, % of Cd (min, max)", (3.89, 5.10), (min(nl), max(nl)), 2)
nl5 = [100 * noise(tex(a, "LM", t, 5), tex(a, "LM", 0.0, 5)) / tex(a, "LM", 0.0, 5).Cd_mean
       for a in (0, 180) for t in (0.05, 0.1, 0.2)]
show("LM noise at maxCo 5 (13 Oct), % of Cd (min, max)", (4.53, 8.35), (min(nl5), max(nl5)), 2)
sl = []
for nm in ("a180.0_U23.0_SST_tex0.200_s1_Tu1.0_Co2.5n2", "a180.0_U23.0_LM_tex0.100_s1_Tu1.0_Co2.5n2",
           "a180.0_U23.0_LM_tex0.200_s1_Tu1.0_Co2.5n2"):
    t, cd, cl = hist(nm)
    m = t >= t[-1] - 50
    sl.append(100 * np.polyfit(t[m], cd[m], 1)[0])
show("SST alpha 180 t 0.2 vs t 0, maxCo 5: noise (% of Cd)", 4.34,
     100 * noise(tex(180, "SST", 0.2, 5), tex(180, "SST", 0.0, 5)) / tex(180, "SST", 0.0, 5).Cd_mean, 2)
t25 = T[T.index.str.contains("_tex") & (T.maxCo == 2.5)]
show("texture runs at maxCo 2.5: count, with negative drift; drift (min, max)", (16, 16, -0.336, -0.005),
     (len(t25), int((t25.Cd_drift < 0).sum()), t25.Cd_drift.min(), t25.Cd_drift.max()), 3)
late = []
for U, t_ in ((18.8, 0.2), (20.9, 0.2), (23.0, 0.1), (23.0, 0.2), (25.2, 0.2)):
    h0 = H.get(f"a180.0_U{U:.1f}_LM_tex0.000_s1_Tu1.0_Co2.5n2") or L[0.0]
    h1 = H.get(f"a180.0_U{U:.1f}_LM_tex{t_:.3f}_s1_Tu1.0_Co2.5n2") or L[t_]
    late.append(100 * (abs(h0[(100, 150)][1]) + abs(h1[(100, 150)][1])) / h0[(100, 150)][0])
late.append(100 * (abs(a0[(100, 150)][1]) + abs(a2[(100, 150)][1])) / a0[(100, 150)][0])
show("drift noise on the last 50 c/U, alpha-180 texture comparisons at maxCo 2.5 (% of Cd; min, max)", (0.46, 1.23),
     (min(late), max(late)), 2)
show("end slopes over the last 50 c/U, textured alpha-180 runs at 23 m/s (min, max per 100 c/U)", (-0.038, -0.012),
     (min(sl), max(sl)), 3)

print("== (3) LM texture against speed, alpha 180, maxCo 2.5")
eff, rat, l50 = [], [], []
for U in (18.8, 20.9, 23.0, 25.2):
    r0, r1 = tex(180, "LM", 0.0, 2.5, U), tex(180, "LM", 0.2, 2.5, U)
    eff.append(pct(r1.Cd_mean, r0.Cd_mean))
    rat.append(abs(r1.Cd_mean - r0.Cd_mean) / noise(r0, r1))
    if U != 23.0:
        h0, h1 = H[f"a180.0_U{U:.1f}_LM_tex0.000_s1_Tu1.0_Co2.5n2"], H[f"a180.0_U{U:.1f}_LM_tex0.200_s1_Tu1.0_Co2.5n2"]
    else:
        h0, h1 = L[0.0], L[0.2]
    l50.append(pct(h1[(100, 150)][0], h0[(100, 150)][0]))
show("texture effect (%) at 18.8/20.9/23.0/25.2 m/s", (0.04, 7.31, 8.61, 8.50), eff, 2)
show("... change / noise", (0.01, 1.88, 2.03, 2.02), rat, 2)
show("... on the last 50 c/U (%)", (0.30, 7.49, 8.35, 8.41), l50, 2)
show("smooth Cd at the four speeds", (1.0473, 0.9792, 0.9544, 0.9533),
     [tex(180, "LM", 0.0, 2.5, U).Cd_mean for U in (18.8, 20.9, 23.0, 25.2)], 4)
show("textured Cd at the four speeds", (1.0477, 1.0508, 1.0366, 1.0343),
     [tex(180, "LM", 0.2, 2.5, U).Cd_mean for U in (18.8, 20.9, 23.0, 25.2)], 4)
show("smooth Cd change 18.8 -> 20.9 m/s (%)", -6.50, pct(tex(180, "LM", 0.0, 2.5, 20.9).Cd_mean,
                                                      tex(180, "LM", 0.0, 2.5, 18.8).Cd_mean), 2)
tx = [tex(180, "LM", 0.2, 2.5, U).Cd_mean for U in (18.8, 20.9, 23.0, 25.2)]
show("textured spread over the bracket (% of the smallest)", 1.60, 100 * (max(tx) - min(tx)) / min(tx), 2)
show("Re_k = U t / nu for t 0.2 mm", (248, 276, 303, 332), [U * 0.2e-3 / 1.516e-5 for U in (18.8, 20.9, 23.0, 25.2)], 0)
b = pd.read_csv(REP / "rotor_by_wind_speed.csv")
for rot, quoted in (("FS 0.20", (12.6, 31.5, 36.2, 25.8)), ("FS 0.10", (8.7, 13.5, 21.2, 22.4))):
    g = b[b.rotor == rot].set_index("wind_mps")
    vals = [g.p_max_change_vs_plain_pct.iloc[np.argmin(np.abs(g.index - U))] for U in (18.8, 20.9, 23.0, 25.2)]
    show(f"measured {rot} P_max change at the four set points (%)", quoted, vals, 1)
g = b[b.rotor == "FS 0.20"].set_index("wind_mps")
show("measured pointwise 95 % half-widths at the four set points (%)", (11.1, 4.3, 2.1, 1.3),
     [g.pointwise95_halfwidth_pct.iloc[np.argmin(np.abs(g.index - U))] for U in (18.8, 20.9, 23.0, 25.2)], 1)

print("== wall pressure (own integration over face segments)")


def read_bin(buf, start=0, dtype="<f8", ncomp=1):
    m = re.search(rb"\n(\d+)\n\(", buf[start:])
    n, off = int(m.group(1)), start + m.end()
    a = np.frombuffer(buf, dtype=dtype, count=n * ncomp, offset=off)
    return (a.reshape(n, ncomp) if ncomp > 1 else a), off + n * ncomp * np.dtype(dtype).itemsize


def split_by_face(name):
    """Pressure drag of the convex face, concave face and end faces: the wall's low-z edges are joined into one
    closed polygon (blade + bladeEnds); its orientation gives the normal out of the solid; F_p = -sum p n dl dz."""
    d = RUNS / name
    P = json.loads((d / "case.json").read_text())
    pts, _ = read_bin((d / "constant/polyMesh/points").read_bytes(), ncomp=3)
    fbuf = (d / "constant/polyMesh/faces").read_bytes()
    offs, end = read_bin(fbuf, dtype="<i4")
    lab, _ = read_bin(fbuf, start=end, dtype="<i4")
    btxt = (d / "constant/polyMesh/boundary").read_text(errors="replace")
    tdir = sorted([q for q in d.iterdir() if re.fullmatch(r"[0-9.]+", q.name)], key=lambda q: float(q.name))[-1]
    pbuf = (tdir / "pMean").read_bytes()
    tbuf = (tdir / "wallShearStressMean").read_bytes()
    key = lambda j: (round(float(pts[j, 0]), 9), round(float(pts[j, 1]), 9))
    segs = []                                       # (key a, key b, p, patch, tau)
    for patch in ("blade", "bladeEnds"):
        mm = re.search(patch + r"\s*\{[^}]*?nFaces\s+(\d+);\s*startFace\s+(\d+);", btxt)
        nf, sf = int(mm.group(1)), int(mm.group(2))
        i = pbuf.index(b"value", pbuf.index(b"\n    " + patch.encode() + b"\n", pbuf.index(b"boundaryField")))
        p, _ = read_bin(pbuf, start=i)
        j = tbuf.index(b"value", tbuf.index(b"\n    " + patch.encode() + b"\n", tbuf.index(b"boundaryField")))
        tau, _ = read_bin(tbuf, start=j, ncomp=3)
        for f, pv, tv in zip(range(sf, sf + nf), p, tau):
            ids = lab[offs[f]:offs[f + 1]]
            low = [j for j in ids if pts[j, 2] < 0.5 * P["dz"]][:2]
            segs.append((key(low[0]), key(low[1]), pv, patch, tv[:2]))
    nb = {}
    for i, (a, b, *_) in enumerate(segs):
        nb.setdefault(a, []).append(i)
        nb.setdefault(b, []).append(i)
    order, pts_cyc, used = [0], [segs[0][0], segs[0][1]], {0}
    while True:
        cur = pts_cyc[-1]
        nxt = [i for i in nb[cur] if i not in used]
        if not nxt:
            break
        i = nxt[0]
        used.add(i)
        order.append(i)
        a, b = segs[i][0], segs[i][1]
        pts_cyc.append(b if a == cur else a)
    assert len(order) == len(segs), (len(order), len(segs))
    xy = np.array(pts_cyc[:-1])
    area = 0.5 * np.sum(xy[:, 0] * np.roll(xy[:, 1], -1) - np.roll(xy[:, 0], -1) * xy[:, 1])
    mi = json.loads((d / "mesh_info.json").read_text())["frame"]["corners_body_m"]
    ao = np.array(mi["A_outer"])
    q = 0.5 * P["Uinf"] ** 2
    drag = np.array(P["dragDir"][:2])
    # walk the cycle; label blade runs by whether their end touches A_outer
    runs, cur = [], None
    for k, i in enumerate(order):
        lab_ = segs[i][3]
        if cur is None or cur["patch"] != lab_:
            cur = dict(patch=lab_, idx=[], pts=[])
            runs.append(cur)
        cur["idx"].append(k)
    if len(runs) > 1 and runs[0]["patch"] == runs[-1]["patch"]:
        runs[0]["idx"] = runs[-1]["idx"] + runs[0]["idx"]
        runs.pop()
    res = {"convex": 0.0, "concave": 0.0, "ends": 0.0, "convex_profile": None}
    for r in runs:
        ends_xy = [np.array(pts_cyc[r["idx"][0]]), np.array(pts_cyc[r["idx"][-1] + 1])]
        if r["patch"] == "bladeEnds":
            name_ = "ends"
        else:
            name_ = "convex" if min(np.linalg.norm(e - ao) for e in ends_xy) < 1e-4 else "concave"
        prof = []
        for k in r["idx"]:
            p0, p1 = np.array(pts_cyc[k]), np.array(pts_cyc[k + 1])
            dv = p1 - p0
            n_out = np.array([dv[1], -dv[0]]) * (1 if area > 0 else -1)      # out of the solid, length |dl|
            fk = float(-segs[order[k]][2] * (n_out @ drag) * P["dz"] / (q * P["Aref"]))
            res[name_] += fk
            prof.append((0.5 * (p0 + p1), dv / np.linalg.norm(dv), segs[order[k]][2] / q, segs[order[k]][4] / q,
                         np.linalg.norm(dv), fk))
        if name_ == "convex":
            res["convex_profile"] = (prof, ao)
    return res


def convex_side_B(res, cref=0.048, textured=False):
    """Side B of the convex face (from the stagnation point toward tip B): minimum Cp, and the distance from the
    stagnation point to the first reversed near-wall flow over >= 0.5 mm (near-wall flow taken as -tau, the
    stress on the wall from the fluid; the sign convention is fixed by the viscous-drag check of
    roughness_surface.py, which matched the table only with -tau)."""
    prof, ao = res["convex_profile"]
    mids = np.array([m for m, *_ in prof])
    if np.linalg.norm(mids[0] - ao) > np.linalg.norm(mids[-1] - ao):
        prof = prof[::-1]                                                # order from tip A to tip B
    Cp = np.array([c for _, _, c, _, _, _ in prof])
    Cp = pd.Series(Cp).rolling(25, center=True, min_periods=1).mean().to_numpy()   # 1 mm, as quoted
    dl = np.array([pr[4] for pr in prof])
    ist = int(np.argmax(Cp))
    sB = np.cumsum(dl[ist:]) - dl[ist]
    flow = np.array([-t @ tg for (_, tg, _, t, _, _) in prof[ist:]])
    # tangent tg runs along the cycle; make it point from the stagnation point toward tip B
    tdir = np.sign(np.dot(prof[-1][0] - prof[ist][0], prof[ist + 1][1])) or 1.0
    rev = (tdir * flow < 0) & (sB > 1e-3)
    sep = np.nan
    k = 0
    while k < len(rev):
        if rev[k]:
            j = k
            while j < len(rev) and rev[j]:
                j += 1
            if sB[min(j, len(sB) - 1)] - sB[k] >= 0.5e-3:
                sep = sB[k] / cref
                break
            k = j
        k += 1
    if textured:
        return float(Cp[ist:].min()), float(sum(pr[5] for pr in prof[ist:]))
    return float(Cp[ist:].min()), sep, float(sB[-1] / cref), float(sum(pr[5] for pr in prof[ist:]))


SURF = {}
for nm, quoted in (("a180.0_U23.0_SST_tex0.000_s1_Tu1.0_Co2.5n2", (0.088, 0.738, 0.061)),
                   ("a180.0_U23.0_SST_tex0.200_s1_Tu1.0_Co2.5n2", (0.279, 0.692, 0.055)),
                   ("a180.0_U23.0_LM_tex0.000_s1_Tu1.0_Co2.5n2", (0.189, 0.696, 0.056)),
                   ("a180.0_U23.0_LM_tex0.200_s1_Tu1.0_Co2.5n2", (0.27, 0.71, 0.06)),
                   ("a180.0_U18.8_LM_tex0.000_s1_Tu1.0_Co2.5n2", (0.266, 0.715, 0.057)),
                   ("a180.0_U25.2_LM_tex0.000_s1_Tu1.0_Co2.5n2", (0.183, 0.702, 0.056)),
                   ("a180.0_U20.9_LM_tex0.000_s1_Tu1.0_Co2.5n2", (0.212, 0.699, 0.056)),
                   ("a180.0_U18.8_LM_tex0.200_s1_Tu1.0_Co2.5n2", (0.29, 0.70, 0.06)),
                   ("a180.0_U20.9_LM_tex0.200_s1_Tu1.0_Co2.5n2", (0.26, 0.73, 0.06)),
                   ("a180.0_U25.2_LM_tex0.200_s1_Tu1.0_Co2.5n2", (0.28, 0.70, 0.06))):
    r = split_by_face(nm)
    SURF[nm] = r
    show(f"{nm}: pressure drag convex / concave / ends", quoted, (r["convex"], r["concave"], r["ends"]),
         2 if "tex0.200" in nm and "LM" in nm else 3)
    dif = abs(r["convex"] + r["concave"] + r["ends"] - float(T.loc[nm, "Cd_pressure_mean"]))
    show(f"    ... |sum - table Cd_pressure_mean| below 3e-4 (it is {dif:.1e})", 1, int(dif < 3e-4), 0)

for nm, quoted in (("a180.0_U23.0_SST_tex0.000_s1_Tu1.0_Co2.5n2", (-3.19, 0.69, 0.79, -0.13)),
                   ("a180.0_U18.8_LM_tex0.000_s1_Tu1.0_Co2.5n2", (-1.60, 0.58, 0.75, 0.05)),
                   ("a180.0_U20.9_LM_tex0.000_s1_Tu1.0_Co2.5n2", (-2.06, 0.74, 0.76, -0.01)),
                   ("a180.0_U23.0_LM_tex0.000_s1_Tu1.0_Co2.5n2", (-2.26, 0.75, 0.77, -0.03)),
                   ("a180.0_U25.2_LM_tex0.000_s1_Tu1.0_Co2.5n2", (-2.31, 0.75, 0.77, -0.04))):
    r = SURF.get(nm) or split_by_face(nm)
    show(f"{nm[:28]}: side B min Cp (1 mm), separation and tip distance from the stagnation point (s/c), "
         "side-B pressure drag", quoted, convex_side_B(r), 2)
for nm, quoted in (("a180.0_U23.0_SST_tex0.200_s1_Tu1.0_Co2.5n2", (-1.81, 0.04)),
                   ("a180.0_U23.0_LM_tex0.200_s1_Tu1.0_Co2.5n2", (-2.01, 0.03)),
                   ("a180.0_U23.0_LM_tex0.100_s1_Tu1.0_Co2.5n2", (-1.16, 0.10)),
                   ("a180.0_U18.8_LM_tex0.200_s1_Tu1.0_Co2.5n2", (-1.88, 0.05)),
                   ("a180.0_U20.9_LM_tex0.200_s1_Tu1.0_Co2.5n2", (-2.15, 0.02)),
                   ("a180.0_U25.2_LM_tex0.200_s1_Tu1.0_Co2.5n2", (-2.01, 0.04))):
    r = SURF.get(nm) or split_by_face(nm)
    show(f"{nm[:28]}: side B min Cp (1 mm), side-B pressure drag", quoted, convex_side_B(r, textured=True), 2)

print("== (4) bottom line (own enumeration of the fair comparisons)")
rows = []
for a, U, co in ((0, 10.2, 2.5), (0, 23.0, 2.5), (0, 23.0, 5.0), (0, 38.0, 2.5), (0, 38.0, 5.0), (180, 23.0, 2.5), (180, 23.0, 5.0)):
    ks_all = [k for k in KS if f"a{a:05.1f}_U{U:.1f}_SST_wf_Ks{k}_Tu1.0" + ("_Co2.5n2" if co == 2.5 else "") in T.index]
    r0 = wf(a, ks_all[0], co, U)
    for k in ks_all[1:]:
        r = wf(a, k, co, U)
        rows.append((r.Cd_mean - r0.Cd_mean, noise(r, r0), +1 if a == 0 else -1))
for co, ks_all in ((2.5, KS), (5.0, [50, 200, 400])):
    Dd = {k: wf(0, k, co).Cd_mean - wf(180, k, co).Cd_mean for k in ks_all}
    for k in ks_all[1:]:
        rows.append((Dd[k] - Dd[ks_all[0]], noise(wf(0, k, co), wf(180, k, co), wf(0, ks_all[0], co), wf(180, ks_all[0], co)), +1))
for a in (0, 180):
    for m in ("SST", "LM"):
        for t in (0.05, 0.1, 0.2):
            r, r0 = tex(a, m, t, 5), tex(a, m, 0.0, 5)
            rows.append((r.Cd_mean - r0.Cd_mean, noise(r, r0), +1 if a == 0 else -1))
rows.append((q2.Cd_mean - q0.Cd_mean, noise(q0, q2), +1))
rows.append((s2.Cd_mean - s0.Cd_mean, noise(s0, s2), -1))
rows.append((l1.Cd_mean - l0.Cd_mean, noise(l0, l1), -1))
rows.append((l2.Cd_mean - l0.Cd_mean, noise(l0, l2), -1))
for U in (18.8, 20.9, 25.2):
    r0, r1 = tex(180, "LM", 0.0, 2.5, U), tex(180, "LM", 0.2, 2.5, U)
    rows.append((r1.Cd_mean - r0.Cd_mean, noise(r0, r1), -1))
for m in ("SST", "LM"):
    Dt = {t: tex(0, m, t, 5).Cd_mean - tex(180, m, t, 5).Cd_mean for t in (0.0, 0.05, 0.1, 0.2)}
    for t in (0.05, 0.1, 0.2):
        rows.append((Dt[t] - Dt[0.0], noise(tex(0, m, t, 5), tex(180, m, t, 5), tex(0, m, 0.0, 5), tex(180, m, 0.0, 5)), +1))
rows.append(((q2.Cd_mean - s2.Cd_mean) - (q0.Cd_mean - s0.Cd_mean), noise(q0, q2, s0, s2), +1))
R = np.array(rows)
res = np.abs(R[:, 0]) > R[:, 1]
need = np.sign(R[:, 0]) == R[:, 2]
show("fair comparisons / resolved / resolved with the needed sign / needed sign at all", (52, 21, 0, 8),
     (len(R), res.sum(), (res & need).sum(), need.sum()), 0)
show("largest change/noise among those with the needed sign", 0.74, (np.abs(R[need, 0]) / R[need, 1]).max(), 2)

print("== two-position model: section change each mean gain needs (fair maxCo-2.5 wall-function pair, lambda 0.125)")
c0, c1, lam = wf(0, 0, 2.5).Cd_mean, wf(180, 0, 2.5).Cd_mean, 0.125
N = c0 * (1 - lam) ** 2 - c1 * (1 + lam) ** 2
cmp_ = pd.read_csv(REP / "comparisons.csv")
g = cmp_[cmp_.relative_to == "Plain"].set_index("rotor").change_pct
show("Cd(180) alone (%), FS 0.10 and FS 0.20", (-2.04, -2.58),
     [-100 * g[r] / 100 * N / (1 + lam) ** 2 / c1 for r in ("FS 0.10", "FS 0.20")], 2)
show("Cd(0) alone (%), FS 0.10 and FS 0.20", (1.76, 2.23),
     [100 * g[r] / 100 * N / (1 - lam) ** 2 / c0 for r in ("FS 0.10", "FS 0.20")], 2)

print("== context from the Stage 1 table (medium mesh, 23 m/s, Tu 1 %; health not assessed here)")
S1 = pd.read_csv(REPO / "cfd" / "section2d" / "results" / "section_polars.csv").set_index("name")
sm = lambda a, m, suf: S1.loc[f"a{a:05.1f}_U23.0_{m}_medium_Tu1.0{suf}"].Cd_mean
show("alpha 180 SST Cd at maxCo 2.5 and 1.25; LM at 2.5 and 1.25", (1.4794, 1.2204, 1.3091, 1.1156),
     (sm(180, "SST", "_Co2.5n2"), sm(180, "SST", "_Co1.25n2"), sm(180, "LM", "_Co2.5n2"), sm(180, "LM", "_Co1.25n2")), 4)
show("... maxCo 2.5 -> 1.25 (%), SST and LM", (-17.51, -14.78),
     (pct(sm(180, "SST", "_Co1.25n2"), sm(180, "SST", "_Co2.5n2")), pct(sm(180, "LM", "_Co1.25n2"), sm(180, "LM", "_Co2.5n2"))), 2)
show("... SST minus LM (% of LM) at maxCo 2.5 and 1.25", (13.01, 9.39),
     (pct(sm(180, "SST", "_Co2.5n2"), sm(180, "LM", "_Co2.5n2")), pct(sm(180, "SST", "_Co1.25n2"), sm(180, "LM", "_Co1.25n2"))), 2)

print("== solver logs (own awk parse: first pressure solve after each Time line)")
import subprocess
AWK = r'/^Time = /{t=$3; f=1; next} f && /Solving for p,/{split($0,a,"Initial residual = "); split(a[2],b,","); print t, b[1]; f=0}'
for nm, quoted in (("a180.0_U20.9_LM_tex0.000_s1_Tu1.0_Co2.5n2", (0.122, 0.0007)),
                   ("a180.0_U23.0_SST_tex0.000_s1_Tu1.0_Co2.5n2", (0.121, 0.0008))):
    out = subprocess.run(["awk", AWK, str(RUNS / nm / "log.pimpleFoam")], capture_output=True, text=True, check=True).stdout
    a = np.array([list(map(float, ln.split())) for ln in out.splitlines()])
    tc = json.loads((RUNS / nm / "case.json").read_text())["convTime"]
    tt, rr = a[:, 0] / tc, a[:, 1]
    med = [np.median(rr[(tt >= k) & (tt < k + 5)]) for k in range(10, 150, 5)]
    last = [np.median(rr[(tt >= k) & (tt < k + 5 + (1e-6 if k == 145 else 0))]) for k in range(100, 150, 5)]
    show(f"{nm[:30]}: largest 5-c/U median first-p residual after 10 c/U", quoted[0], max(med), 3)
    show(f"{nm[:30]}: largest 5-c/U median in the last 50 c/U", quoted[1], max(last), 4)

nm = "a000.0_U23.0_LM_tex0.000_s1_Tu1.0_Co2.5n2"
out = subprocess.run(["awk", AWK, str(RUNS / nm / "log.pimpleFoam")], capture_output=True, text=True, check=True).stdout
a = np.array([list(map(float, ln.split())) for ln in out.splitlines()])
tt, rr = a[:, 0] / json.loads((RUNS / nm / "case.json").read_text())["convTime"], a[:, 1]
before = [np.median(rr[(tt >= k) & (tt < k + 5)]) for k in range(50, 135, 5)]
after = [np.median(rr[(tt >= k) & (tt < k + 5 + (1e-6 if k == 145 else 0))]) for k in (135, 140, 145)]
show("LM alpha-0 t 0 maxCo 2.5: 5-c/U median first-p residual, 50-135 c/U (min, max) and 135-150 c/U (min, max)",
     (0.0028, 0.0093, 0.0142, 0.0252), (min(before), max(before), min(after), max(after)), 4)

print(f"== {NCHECK[0]} CHECK line(s)")
