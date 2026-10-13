#!/usr/bin/env python3
"""Independent check of the Stage 1 (blade section) findings of 13 Oct 2026.

    nice -n 10 python3 cfd/analysis/2026-10-13/src/section_verify.py

Written by the verifier, separately from section_lib.py / section_analysis.py (nothing is
imported from them). Reads only ../data/section_polars.csv and cfd/geometry/section_v1.{csv,json};
prints every number quoted in the verified findings. No case folder is read.
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parents[2]
C = 0.048                                     # m, c_ref (section2d/README.md section 1)
DX = {"coarse": 64e-6, "medium": 45e-6, "fine": 32e-6}   # corner wall spacing (README section 2)
LIT0, LIT180 = 2.3, 1.2                       # PLAN.md, 2D semicircular shell, frontal width
RIG_LAM_LIGHT = 0.158                         # rotor2d/README.md, Plain, 23 m/s

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 200)


def hdr(t):
    print("\n" + "=" * 8, t)


def rng(s, f="{:.4g}"):
    return f"{f.format(s.min())}-{f.format(s.max())}"


d = pd.read_csv(ROOT / "data" / "section_polars.csv")
d["dtc"] = d.dt_mean_s * d.U_ms / C                       # mean time step in c/U
d["uco"] = d.maxCo * d.level.map(DX) / (d.dt_mean_s * d.U_ms)
d["rel_std"] = d.Cd_std / d.Cd_mean.abs()
d["se"] = d.Cd_std / np.sqrt(d.n_cycles_avg.clip(lower=1))
d["drift_rel"] = d.Cd_drift / d.Cd_mean.abs()
d["key"] = (d.name.str.replace("_Tu1.0", "", regex=False).str.replace("_medium", "_m", regex=False)
            .str.replace("_coarse", "_c", regex=False).str.replace("_fine", "_f", regex=False))

# ------------------------------------------------------------------ S1-health
hdr("S1-health: time-step proxy and symptoms")
srt = d.sort_values("uco")
print(srt[["key", "level", "maxCo", "dtc", "uco", "Cd_mean", "rel_std", "Cl_mean", "yplus_max_mean"]]
      .to_string(index=False, float_format=lambda x: f"{x:.4g}"))
flag = d.uco > 5
F, H = d[flag], d[~flag]
print(f"flagged {len(F)}, healthy {len(H)}; proxy healthy {rng(H.uco, '{:.3f}')}, flagged {rng(F.uco, '{:.3f}')}; "
      f"gap factor {F.uco.min() / H.uco.max():.3f}")
print("flagged by level/maxCo:", F.groupby(["level", "maxCo"]).size().to_dict(),
      " all by level/maxCo:", d.groupby(["level", "maxCo"]).size().to_dict())
print("flagged by model:", F.model.value_counts().to_dict(), " flagged at alpha 180:", int((F.alpha_deg == 180).sum()))
m5 = d[(d.level == "medium") & (d.maxCo == 5)]
print("medium maxCo5 dt (c/U): healthy", rng(m5[m5.uco <= 5].dtc, "{:.3e}"), "median", f"{m5[m5.uco <= 5].dtc.median():.3e}",
      "; flagged", rng(m5[m5.uco > 5].dtc, "{:.3e}"))
print("  ratio healthy-median / flagged:", f"{m5[m5.uco <= 5].dtc.median() / m5[m5.uco > 5].dtc.max():.2f}-"
      f"{m5[m5.uco <= 5].dtc.median() / m5[m5.uco > 5].dtc.min():.2f}")
print("steps: flagged", rng(F.n_steps, "{:,.0f}"), "; healthy medium Co5", rng(m5[m5.uco <= 5].n_steps, "{:,.0f}"),
      "; medium Co2.5", rng(d[(d.level == "medium") & (d.maxCo == 2.5)].n_steps, "{:,.0f}"))
neg = F.Cd_mean < 0
sgt = F.Cd_std > F.Cd_mean.abs()
cl3 = F.Cl_mean.abs() > 3
yp2 = F.yplus_max_mean > 2
print(f"symptoms in flagged: Cd<0 {neg.sum()} (min {F.Cd_mean.min():.3f}); std>|mean| {sgt.sum()} "
      f"(max std {F.Cd_std.max():.2f}); |Cl|>3 {cl3.sum()} (min Cl {F.Cl_mean.min():.2f}); "
      f"y+maxmean>2 {yp2.sum()} (flagged range {rng(F.yplus_max_mean, '{:.2f}')}, inst max {F.yplus_max_max.max():.2f})")
print("  flagged with no force symptom:", F[~(neg | sgt | cl3)].key.tolist())
print("  flagged with no y+ symptom:", F[~yp2].key.tolist(), F[~yp2].yplus_max_mean.round(3).tolist())
print("  flagged with std <= |mean|:", F[~sgt][["key", "rel_std", "Cd_mean"]].round(3).values.tolist())
print(f"healthy: max y+maxmean {H.yplus_max_mean.max():.3f}, max y+ inst {H.yplus_max_max.max():.2f} "
      f"({H.loc[H.yplus_max_max.idxmax(), 'key']}); max std/|mean| {H.rel_std.max():.3f} "
      f"({H.loc[H.rel_std.idxmax(), 'key']}); any Cd<0 {bool((H.Cd_mean < 0).any())}; "
      f"any |Cl|>3 {bool((H.Cl_mean.abs() > 3).any())}")
print("negative-drag cases:", F[neg].key.tolist())
# matched maxCo-5 refinement comparison (the only cases run on more than one mesh at maxCo 5)
mt = d[(d.model == "SST") & (d.U_ms == 23) & (d.maxCo == 5) & d.alpha_deg.isin([0, 90, 180])]
print("matched SST 23 m/s maxCo 5 at alpha 0/90/180, flagged per level:",
      mt.groupby("level").apply(lambda g: f"{int((g.uco > 5).sum())} of {len(g)}").to_dict(),
      "(fine maxCo 5: 3 of 3 diverged, RUN_JOURNAL 12 Oct)")

# ------------------------------------------------------------------ S1-dt-control
hdr("S1-dt-control: time step by model")
h5 = m5[m5.uco <= 5]
for mdl, g in h5.groupby("model"):
    print(f"healthy medium Co5 {mdl}: n {len(g)}, dt c/U {rng(g.dtc, '{:.3e}')}, median {g.dtc.median():.3e}")
for (fl, mdl), g in m5[m5.U_ms == 23].groupby([m5[m5.U_ms == 23].uco > 5, "model"]):
    print(f"23 m/s medium Co5 {'flagged' if fl else 'healthy'} {mdl}: dt us {rng(g.dt_mean_s * 1e6, '{:.3f}')}")
a0 = d[(d.alpha_deg == 0) & (d.level == "medium") & (d.maxCo == 5) & (d.Tu_body_pct == 1)]
for U, g in a0.groupby("U_ms"):
    s, l = g[g.model == "SST"].iloc[0], g[g.model == "LM"].iloc[0]
    print(f"alpha 0, {U} m/s, matched: dt SST {s.dt_mean_s * 1e6:.3f} us, LM {l.dt_mean_s * 1e6:.3f} us, "
          f"LM/SST {l.dt_mean_s / s.dt_mean_s:.3f}; Cd SST {s.Cd_mean:.4f}, LM {l.Cd_mean:.4f}")
for nm in ("a180.0_U10.2_LM_medium_Tu1.0", "a165.0_U23.0_LM_medium_Tu1.0"):
    r = d[d.name == nm].iloc[0]
    print(f"{nm}: proxy {r.uco:.2f}, steps {r.n_steps:,}")
c25 = d[(d.level == "medium") & (d.maxCo == 2.5)]
print("medium Co2.5 steps", c25.n_steps.tolist(), "wall s", c25.wall_time_s.tolist(),
      "h", (c25.wall_time_s / 3600).round(2).tolist(), "ran_on", c25.ran_on.tolist())
print("cases with s_per_step < 0.02 (wall time of last session only):", d[d.s_per_step < 0.02].key.tolist())

# ------------------------------------------------------------------ S1-alpha0-states
hdr("S1-alpha0-states")
z = d[d.alpha_deg == 0].copy()
z["state"] = np.where(z.Cd_mean > 2.5, "high", "low")
print(z.sort_values(["state", "Cd_mean"])[["key", "ran_on", "uco", "state", "Cd_mean", "Cd_std", "se", "Cd_drift",
                                           "drift_rel", "Cl_mean", "Cl_std", "Cm_mean", "St", "St_peak_frac",
                                           "n_cycles_avg"]].to_string(index=False, float_format=lambda x: f"{x:.4g}"))
for s, g in z.groupby("state"):
    print(f"{s}: n {len(g)}; Cd {rng(g.Cd_mean)}; Cd_std {rng(g.Cd_std)}; Cl {rng(g.Cl_mean)}; "
          f"Cl_std {rng(g.Cl_std)}; Cm {rng(g.Cm_mean)}; St {rng(g.St)}")
for lvl in ("coarse", "medium"):
    g = z[(z.model == "SST") & (z.U_ms == 23) & (z.level == lvl)].set_index("maxCo")
    print(f"SST 23 {lvl}: Co5 {g.loc[5.0, 'Cd_mean']:.4f} -> Co2.5 {g.loc[2.5, 'Cd_mean']:.4f} "
          f"({100 * (g.loc[2.5, 'Cd_mean'] / g.loc[5.0, 'Cd_mean'] - 1):+.1f} %), ratio {g.loc[5.0, 'Cd_mean'] / g.loc[2.5, 'Cd_mean']:.3f}; "
          f"Cl_std {g.loc[5.0, 'Cl_std']:.4f} -> {g.loc[2.5, 'Cl_std']:.4f}; ran_on {g.loc[5.0, 'ran_on']} / {g.loc[2.5, 'ran_on']}")
geo = json.load(open(REPO / "cfd" / "geometry" / "section_v1.json"))
xy = pd.read_csv(REPO / "cfd" / "geometry" / "section_v1.csv").to_numpy()
cd = math.radians(geo["dimensions"]["chord_direction_deg_from_x"])
ey = np.array([math.cos(cd), math.sin(cd)])
ex = np.array([math.cos(cd - math.pi / 2), math.sin(cd - math.pi / 2)])


def width(alpha):
    a = math.radians(alpha)
    n = -math.sin(a) * ex + math.cos(a) * ey           # direction normal to U in the CAD frame
    s = xy @ n
    return s.max() - s.min()


W = {a: width(a) for a in (0, 90, 180, 270)}
print("frontal width mm (polyline):", {a: round(w * 1e3, 3) for a, w in W.items()},
      "; model extents: along chord", round(geo["dimensions"]["max_extent_along_outer_tip_chord"] * 1e3, 3) if
      "max_extent_along_outer_tip_chord" in geo["dimensions"] else
      round(geo["dimensions"]["chord_other_definitions_m"]["max_extent_along_outer_tip_chord"] * 1e3, 3),
      "normal", round(1e3 * (geo["dimensions"]["section_extent_normal_to_chord_m"][1]
                             - geo["dimensions"]["section_extent_normal_to_chord_m"][0]), 3))
f0 = C / W[0]
print(f"c/d at alpha 0: {f0:.4f}")
for s, g in z.groupby("state"):
    lo, hi = g.Cd_mean.min() * f0, g.Cd_mean.max() * f0
    print(f"{s} on frontal width: {lo:.3f}-{hi:.3f}, vs 2.3: {100 * (lo / LIT0 - 1):+.1f} to {100 * (hi / LIT0 - 1):+.1f} %")
h180 = d[(d.alpha_deg == 180) & (d.uco <= 5)]
lo, hi = h180.Cd_mean.min() * C / W[180], h180.Cd_mean.max() * C / W[180]
print(f"healthy alpha 180 ({len(h180)} runs: {h180.key.tolist()}) on frontal: {lo:.3f}-{hi:.3f}, "
      f"vs 1.2: {100 * (lo / LIT180 - 1):+.1f} to {100 * (hi / LIT180 - 1):+.1f} %")

# ------------------------------------------------------------------ S1-drag-ratio
hdr("S1-drag-ratio")


def lam0(k):
    s = math.sqrt(k)
    return (s - 1) / (s + 1)


def lampk(k):
    # maximise lam [k (1 - lam)^2 - (1 + lam)^2] numerically (no closed form reused)
    lam = np.linspace(0, lam0(k), 200001)
    p = lam * (k * (1 - lam) ** 2 - (1 + lam) ** 2)
    return lam[np.argmax(p)]


pairs = []
for key, g in d.groupby(["level", "model", "maxCo", "U_ms", "Tu_body_pct"]):
    if {0, 180} <= set(g.alpha_deg):
        r0, r1 = g[g.alpha_deg == 0].iloc[0], g[g.alpha_deg == 180].iloc[0]
        ok = r0.uco <= 5 and r1.uco <= 5
        k = r0.Cd_mean / r1.Cd_mean
        pairs.append((key, ok, r0.Cd_mean, r1.Cd_mean, k, lam0(k) if ok and k > 0 else np.nan,
                      lampk(k) if ok and k > 1 else np.nan, r0.ran_on, r1.ran_on))
for p in pairs:
    print(p[0], "usable" if p[1] else "UNUSABLE", f"{p[2]:.4f}/{p[3]:.4f} = {p[4]:.4f}", f"lam0 {p[5]:.4f}",
          f"lam_pk {p[6]:.4f}", p[7], p[8])
kl = LIT0 / LIT180
print(f"literature k {kl:.4f}, lam0 {lam0(kl):.4f}, lam_pk {lampk(kl):.4f}")
kneed = ((1 + RIG_LAM_LIGHT) / (1 - RIG_LAM_LIGHT)) ** 2
print(f"k needed for lam0 >= {RIG_LAM_LIGHT}: {kneed:.4f}; lam0 of k 1.8109 = {lam0(1.8109):.4f} "
      f"({100 * (lam0(1.8109) / RIG_LAM_LIGHT - 1):+.1f} % vs rig light-load)")
print(f"frontal widths at 0 and 180 equal: {W[0] * 1e3:.3f} / {W[180] * 1e3:.3f} mm")

# ------------------------------------------------------------------ time step pairs
hdr("maxCo 5 vs 2.5 (SST, 23 m/s, Tu 1 %)")
for (a, lvl), g in d[(d.model == "SST") & (d.U_ms == 23)].groupby(["alpha_deg", "level"]):
    if set(g.maxCo) >= {5.0, 2.5}:
        r5, r2 = g[g.maxCo == 5].iloc[0], g[g.maxCo == 2.5].iloc[0]
        print(f"alpha {a} {lvl}: flagged5 {r5.uco > 5}; Cd {r5.Cd_mean:.4f}->{r2.Cd_mean:.4f} "
              f"({100 * (r2.Cd_mean / r5.Cd_mean - 1):+.1f} %); Cl {r5.Cl_mean:.4f}->{r2.Cl_mean:.4f} "
              f"({100 * (r2.Cl_mean - r5.Cl_mean) / abs(r5.Cl_mean):+.1f} %); Cl_std {r5.Cl_std:.4g}->{r2.Cl_std:.4g}; "
              f"St {r5.St:.4f}({r5.St_peak_frac:.2f})->{r2.St:.4f}({r2.St_peak_frac:.2f}); ran_on {r5.ran_on}/{r2.ran_on}")

# ------------------------------------------------------------------ grid study
hdr("grid study, SST, 23 m/s, maxCo 2.5 (Celik et al. 2008, own implementation)")


def gci(f3, f2, f1, N3, N2, N1):
    r21, r32 = math.sqrt(N1 / N2), math.sqrt(N2 / N3)
    e21, e32 = f2 - f1, f3 - f2
    R = e21 / e32
    if not (0 < R < 1):
        return dict(R=R, p=None)
    s = np.sign(e32 / e21)
    p = 1.0
    for _ in range(500):
        q = math.log((r21 ** p - s) / (r32 ** p - s))
        p = abs(math.log(abs(e32 / e21)) + q) / math.log(r21)
    ext = (r21 ** p * f1 - f2) / (r21 ** p - 1)
    g = 1.25 * abs((f1 - f2) / f1) / (r21 ** p - 1)
    return dict(R=R, p=p, ext=ext, gci=100 * g, r21=r21, r32=r32)


for a in (0, 90, 180):
    g = d[(d.model == "SST") & (d.U_ms == 23) & (d.maxCo == 2.5) & (d.alpha_deg == a)].set_index("level")
    for q in ("Cd_mean", "Cl_mean", "Cm_mean", "St"):
        res = gci(g.loc["coarse", q], g.loc["medium", q], g.loc["fine", q],
                  g.loc["coarse", "n_cells"], g.loc["medium", "n_cells"], g.loc["fine", "n_cells"])
        vals = [g.loc[lv, q] for lv in ("coarse", "medium", "fine")]
        spread = 100 * (max(vals) - min(vals)) / abs(vals[2])
        print(f"alpha {a} {q}: c/m/f {vals[0]:.5g} {vals[1]:.5g} {vals[2]:.5g}; R {res['R']:.3f}; "
              + (f"p {res['p']:.3f}, ext {res['ext']:.4f}, GCI_fine {res['gci']:.2f} %" if res["p"] else "no order")
              + f"; spread/fine {spread:.1f} %")
    print(f"   h/h_fine medium {math.sqrt(g.loc['fine', 'n_cells'] / g.loc['medium', 'n_cells']):.3f}, "
          f"coarse {math.sqrt(g.loc['fine', 'n_cells'] / g.loc['coarse', 'n_cells']):.3f}; "
          f"Cd_std c/m/f {g.loc['coarse', 'Cd_std']:.4f} {g.loc['medium', 'Cd_std']:.4f} {g.loc['fine', 'Cd_std']:.4f}; "
          f"Cl_std {g.loc['coarse', 'Cl_std']:.4g} {g.loc['medium', 'Cl_std']:.4g} {g.loc['fine', 'Cl_std']:.4g}; "
          f"St frac {g.loc['coarse', 'St_peak_frac']:.3f} {g.loc['medium', 'St_peak_frac']:.3f} {g.loc['fine', 'St_peak_frac']:.3f}; "
          f"y+max inst {g.loc['coarse', 'yplus_max_max']:.2f} {g.loc['medium', 'yplus_max_max']:.2f} {g.loc['fine', 'yplus_max_max']:.2f}")

# ------------------------------------------------------------------ Strouhal
hdr("Strouhal: healthy runs with Cl_std >= 1e-3 and peak share >= 0.2")
s = d[(d.uco <= 5) & (d.Cl_std >= 1e-3) & (d.St_peak_frac >= 0.2)].copy()
s["d_mm"] = s.alpha_deg.map(lambda a: width(a) * 1e3)
s["St_d"] = s.St * s.d_mm / (C * 1e3)
s["f23"] = s.St * 23 / C
s["f_own"] = s.St * s.U_ms / C
print(s.sort_values(["alpha_deg", "model", "level", "maxCo"])[["key", "St", "St_peak_frac", "St_d", "f_own", "f23"]]
      .to_string(index=False, float_format=lambda x: f"{x:.4g}"))
print("factors d/c:", {a: round(width(a) / C, 4) for a in (0, 90, 180, 270)})

# ------------------------------------------------------------------ SST vs LM
hdr("SST vs LM, matched alpha/U/Tu/level/maxCo")
for key, g in d.groupby(["alpha_deg", "U_ms", "Tu_body_pct", "level", "maxCo"]):
    if set(g.model) >= {"SST", "LM"}:
        sr, lr = g[g.model == "SST"].iloc[0], g[g.model == "LM"].iloc[0]
        ok = sr.uco <= 5 and lr.uco <= 5
        cse = math.hypot(sr.se, lr.se)
        print(key, "usable" if ok else "UNUSABLE", f"Cd SST {sr.Cd_mean:.4f} LM {lr.Cd_mean:.4f} "
              f"d {lr.Cd_mean - sr.Cd_mean:+.4f} ({100 * (lr.Cd_mean / sr.Cd_mean - 1):+.2f} %), 2*comb SE {2 * cse:.3f}; "
              f"St {sr.St:.4f}/{lr.St:.4f} ({100 * (lr.St / sr.St - 1):+.2f} %); Cl {sr.Cl_mean:.3f}/{lr.Cl_mean:.3f}")

# ------------------------------------------------------------------ speed / Tu at alpha 0
hdr("alpha 0 speed and Tu sweeps (medium, maxCo 5)")
for mdl in ("SST", "LM"):
    g = d[(d.alpha_deg == 0) & (d.level == "medium") & (d.maxCo == 5) & (d.model == mdl) & (d.Tu_body_pct == 1)]
    g = g.set_index("U_ms")
    for U in (10.2, 38.0):
        dd = g.loc[U, "Cd_mean"] - g.loc[23.0, "Cd_mean"]
        print(f"{mdl} {U} vs 23: {g.loc[U, 'Cd_mean']:.4f} vs {g.loc[23.0, 'Cd_mean']:.4f}: "
              f"{100 * dd / g.loc[23.0, 'Cd_mean']:+.2f} %, {dd / math.hypot(g.loc[U, 'se'], g.loc[23.0, 'se']):+.2f} comb SE")
g = d[(d.alpha_deg == 0) & (d.level == "medium") & (d.model == "LM") & (d.U_ms == 23)]
print("LM 23 Tu sweep:", g.sort_values("Tu_body_pct")[["Tu_body_pct", "Cd_mean", "Cd_std", "Cl_std", "St"]].values.round(4).tolist())

# ------------------------------------------------------------------ viscous share, drift, Tu, LM polar
hdr("other checks")
for a in (0, 90, 180):
    g = H[H.alpha_deg == a]
    v = 100 * g.Cd_viscous_mean / g.Cd_mean
    print(f"alpha {a}: viscous share of Cd {v.min():.2f} to {v.max():.2f} % ({len(g)} healthy runs)")
v = 100 * H.Cd_viscous_mean / H.Cd_mean
print(f"all healthy: viscous share {v.min():.2f} to {v.max():.2f} %; |share| max {v.abs().max():.2f} %")
uns = H[H.Cl_std >= 1e-3]
print("healthy unsteady runs with |drift| > 2 SE:",
      uns[uns.Cd_drift.abs() > 2 * uns.se][["key", "Cd_drift", "se", "drift_rel"]].round(4).values.tolist(),
      f"of {len(uns)}")
print("healthy runs with |drift| > 10 % of mean:", H[H.drift_rel.abs() > 0.10][["key", "drift_rel", "n_cycles_avg",
                                                                               "St", "St_peak_frac"]].round(3).values.tolist())
print("Tu probe by target:", {t: rng(g.Tu_upstream_probe_pct) for t, g in d.groupby("Tu_body_pct")})
pol = d[(d.model == "LM") & (d.U_ms == 23) & (d.Tu_body_pct == 1) & (d.level == "medium")].sort_values("alpha_deg")
print("LM 23 polar healthy alphas:", pol[pol.uco <= 5].alpha_deg.tolist(), "; flagged:", pol[pol.uco > 5].alpha_deg.tolist())
print("LM 23 polar healthy rows:")
print(pol[pol.uco <= 5][["alpha_deg", "Cd_mean", "Cd_std", "rel_std", "Cl_mean", "Cl_std", "Cm_mean", "St", "St_peak_frac",
                         "n_cycles_avg", "drift_rel"]].to_string(index=False, float_format=lambda x: f"{x:.4g}"))
print("a090 SST medium Co5 window:", d[(d.alpha_deg == 90) & (d.model == "SST") & (d.level == "medium") & (d.maxCo == 5)]
      [["avg_from_conv", "avg_to_conv", "t_end_conv", "ran_on"]].values.tolist())
