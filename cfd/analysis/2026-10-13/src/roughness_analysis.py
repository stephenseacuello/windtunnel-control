#!/usr/bin/env python3
"""Stage 2 (roughness) analysis of the merged CFD tables of 13 Oct 2026.

    nice -n 10 python3 cfd/analysis/2026-10-13/src/roughness_analysis.py

Reads (read-only)
  ../data/stage2_polars.csv      43 Stage 2 cases: rough wall functions (wall = wf) and resolved texture (tex)
  ../data/section_polars.csv     Stage 1 cases, only to place the alpha-0 flow states in context
  reports/roughness_2026-09/build/derived/comparisons.csv          measured peak-power changes (Tukey 95 %)
  reports/roughness_2026-09/build/derived/rotor_by_wind_speed.csv  measured change at each wind speed
  reports/roughness_2026-09/build/derived/surface_roughness.csv    measured Ra, Pa
  reports/roughness_2026-09/build/numbers.json, build/tacho/numbers.tex   report macros
Writes
  ../out/roughness_*.csv, ../out/roughness_numbers.json
  ../fig/roughness_*.png
No case folder (cfd/*/runs, cfd/*/results) is read.

Conventions (cfd/section2d/README.md section 1): alpha 0 = concave side into the wind, 180 = convex side
into the wind, 90 = flow from tip A to tip B; coefficients on c_ref = 48 mm per unit span.
Noise rule (project convention, cfd/stage2/compare_roughness.py): a change between cases a and b is
'resolved' when |X_a - X_b| > |drift_a| + |drift_b|, drift = mean of the second half of the averaging
window minus the first half. 'not resolved' bounds the change; it does not show equality.
Provenance: every number written here is calculated from the files above. Assumptions are named where
they are used: Ks ~ k and Ks ~ 2.09 t (docs/ROUGHNESS_KS.md), the quasi-steady two-position
drag-rotor model, the literature shell drag 2.3 / 1.2 (cfd/PLAN.md).
"""
import itertools
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parents[2]
DATA, FIG, OUT = ROOT / "data", ROOT / "fig", ROOT / "out"
REP = REPO / "reports" / "roughness_2026-09" / "build"

NU = 1.516e-5           # m^2/s, the CFD value (cfd/section2d/README.md section 3)
LAM = 0.125             # tip-speed ratio for the quasi-steady weighting; measured peak 0.122-0.131
U_CFD = 23.0
KS_SWEEP = [0, 50, 100, 200, 400]
T_SWEEP = [0.0, 0.05, 0.10, 0.20]
CD_SHELL_LIT = (2.3, 1.2)   # semicircular shell, concave / convex into the wind (cfd/PLAN.md; literature, not this blade)
K_SCAN = {"Plain": (38.0, 38.0), "FS 0.05": (38.0, 38.0), "FS 0.10": (38.0, 38.0), "FS 0.20": (84.0, 97.0)}
FS_T = {"Plain": 0.0, "FS 0.05": 0.050, "FS 0.10": 0.101, "FS 0.20": 0.202}   # slicer thickness (mm)
ROTORS = ["Plain", "FS 0.05", "FS 0.10", "FS 0.20"]

# ------------------------------------------------------------------ style (mirrors section_lib.style)
BLACK = "#000000"
INK2 = "#52514e"
MUTED = "#8c8c8c"
BAND1 = "#f2f2f2"
BAND2 = "#e3e3e3"
RAMP = {50: "#86b6ef", 100: "#5598e7", 200: "#256abf", 400: "#184f95"}   # validated ordinal blue ramp
T_COLOR = {0.0: BLACK, 0.05: RAMP[100], 0.10: RAMP[200], 0.20: RAMP[400]}  # t ~ Ks/2.09 um (nominal texture)
FS_COLOR = {"Plain": BLACK, "FS 0.05": RAMP[100], "FS 0.10": RAMP[200], "FS 0.20": RAMP[400]}
MODEL_LS = {"LM": "-", "SST": "--"}
MODEL_MARKER = {"LM": "o", "SST": "s"}
MS = 5.0


def ks_color(ks):
    return BLACK if ks == 0 else RAMP[int(ks)]


def style():
    matplotlib.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
        "font.size": 8, "axes.labelsize": 8, "axes.titlesize": 8,
        "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 6.5,
        "axes.linewidth": 0.6, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "xtick.major.size": 2.5, "ytick.major.size": 2.5,
        "lines.linewidth": 1.2, "lines.markersize": 4.5,
        "axes.grid": True, "grid.color": "#e6e6e6", "grid.linewidth": 0.5, "grid.linestyle": "-",
        "axes.axisbelow": True,
        "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
        "savefig.dpi": 200, "legend.frameon": False,
        "axes.spines.top": False, "axes.spines.right": False, "mathtext.default": "regular",
    })


def mk(model, maxco, color):
    """Marker style: shape by model, filled for maxCo 2.5, open for maxCo 5 (as section_lib.mstyle)."""
    filled = float(maxco) < 5
    return dict(marker=MODEL_MARKER[model], ms=MS, mec=color, mfc=color if filled else "white",
                mew=1.1, ls="none")


def sgn(x, nd=1, unit=""):
    s = f"{x:+.{nd}f}{unit}"
    return s.replace("-", "\u2212")


# ------------------------------------------------------------------ helpers
def pick(d, **kw):
    m = np.ones(len(d), bool)
    for k, v in kw.items():
        m &= np.isclose(d[k].to_numpy(dtype=float), v) if isinstance(v, float) else (d[k] == v).to_numpy()
    return d[m]


def one(d, **kw):
    r = pick(d, **kw)
    if len(r) != 1:
        raise KeyError(f"{kw}: {len(r)} rows")
    return r.iloc[0]


def spearman(x, y):
    return float(np.corrcoef(pd.Series(x).rank().to_numpy(), pd.Series(y).rank().to_numpy())[0, 1])


def perm_p(x, y):
    """Exact two-sided permutation p of |Spearman rho| (all orderings equally likely under no effect)."""
    obs, y = abs(spearman(x, y)), np.asarray(y, float)
    hits = tot = 0
    for p in itertools.permutations(range(len(y))):
        tot += 1
        hits += abs(spearman(x, y[list(p)])) >= obs - 1e-12
    return hits / tot


def ols(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    xm, ym = x.mean(), y.mean()
    sxx = ((x - xm) ** 2).sum()
    b = ((x - xm) * (y - ym)).sum() / sxx
    res = y - (ym + b * (x - xm))
    dof = len(x) - 2
    se = math.sqrt((res ** 2).sum() / dof / sxx) if dof > 0 else float("nan")
    r2 = 1 - (res ** 2).sum() / ((y - ym) ** 2).sum()
    return b, se, r2, dof


def latex_num(s):
    s = str(s).replace("\\ensuremath{-}", "-").replace("$", "").strip()
    return float(re.sub(r"^[=<>+]", "", s))


# ------------------------------------------------------------------ loading
def load():
    d = pd.read_csv(DATA / "stage2_polars.csv")
    d["Co"] = d["maxCo"].astype(float)
    d["t"] = d["tex_t_mm"].astype(float).round(2)
    s1 = pd.read_csv(DATA / "section_polars.csv")
    meas = dict(
        comp=pd.read_csv(REP / "derived" / "comparisons.csv"),
        bys=pd.read_csv(REP / "derived" / "rotor_by_wind_speed.csv"),
        surf=pd.read_csv(REP / "derived" / "surface_roughness.csv"),
        num=json.loads((REP / "numbers.json").read_text()),
        tacho=dict(re.findall(r"\\newcommand\{\\(\w+)\}\{([^}]*)\}", (REP / "tacho" / "numbers.tex").read_text())),
    )
    return d, s1, meas


# ------------------------------------------------------------------ 1. rough-wall-function sweep
def wf_effects(d):
    wf = d[d.wall == "wf"]
    rows = []
    for (a, U, co), g in wf.groupby(["alpha_deg", "U_ms", "Co"]):
        g = g.sort_values("Ks_um")
        ref = g[g.Ks_um == 0]
        note = "Ks 0, same alpha, U, maxCo and mesh"
        if ref.empty:
            ref = g.iloc[[0]]
            note = (f"Ks {int(ref.Ks_um.iloc[0])} (the Ks 0 and Ks 100 cases at this maxCo diverged "
                    "and are not in the table)")
        r0 = ref.iloc[0]
        for _, r in g.iterrows():
            nCd = abs(r.Cd_drift) + abs(r0.Cd_drift)
            nCl = abs(r.Cl_drift) + abs(r0.Cl_drift)
            dCd, dCl = r.Cd_mean - r0.Cd_mean, r.Cl_mean - r0.Cl_mean
            is_ref = r["name"] == r0["name"]
            rows.append(dict(
                case=r["name"], reference=r0["name"], reference_rule=note, alpha_deg=a, U_ms=U, maxCo=co,
                Ks_um=r.Ks_um, Cd=r.Cd_mean, Cd_std=r.Cd_std, Cd_drift=r.Cd_drift,
                dCd=dCd, dCd_pct=100 * dCd / r0.Cd_mean, noise_Cd=nCd,
                dCd_over_noise=abs(dCd) / nCd if nCd > 0 else np.nan,
                resolved_Cd="n/a" if is_ref else ("yes" if abs(dCd) > nCd else "no"),
                dCd_pressure=r.Cd_pressure_mean - r0.Cd_pressure_mean,
                dCd_viscous=r.Cd_viscous_mean - r0.Cd_viscous_mean,
                Cd_viscous=r.Cd_viscous_mean,
                Cl=r.Cl_mean, Cl_std=r.Cl_std, Cl_drift=r.Cl_drift, dCl=dCl,
                dCl_pct=100 * dCl / abs(r0.Cl_mean), noise_Cl=nCl,
                resolved_Cl="n/a" if is_ref else ("yes" if abs(dCl) > nCl else "no"),
                dCm=r.Cm_mean - r0.Cm_mean, St=r.St, St_peak_frac=r.St_peak_frac,
                dSt_pct=100 * (r.St - r0.St) / r0.St, n_cycles_avg=r.n_cycles_avg,
                ksplus_mean=r.ksplus_blade_mean, ksplus_max=r.ksplus_blade_max, Ks_over_yP=r.Ks_over_yP,
                yP_um=1e6 * r.yP_m, h0_mm=1e3 * r.h0_m, yplus_mean=r.yplus_blade_mean,
                yplus_max=r.yplus_blade_max, n_cells=r.n_cells, ran_on=r.ran_on, ref_ran_on=r0.ran_on))
    return pd.DataFrame(rows)


def timestep_pairs(d):
    wf = d[d.wall == "wf"]
    rows, effects = [], []
    for (a, U, ks), g in wf.groupby(["alpha_deg", "U_ms", "Ks_um"]):
        if {5.0, 2.5} <= set(g.Co):
            c5, c25 = one(g, Co=5.0), one(g, Co=2.5)
            dCd = c5.Cd_mean - c25.Cd_mean
            n = abs(c5.Cd_drift) + abs(c25.Cd_drift)
            rows.append(dict(alpha_deg=a, U_ms=U, Ks_um=ks, case_Co5=c5["name"], case_Co2_5=c25["name"],
                             Cd_Co5=c5.Cd_mean, Cd_Co2_5=c25.Cd_mean, dCd=dCd, dCd_pct=100 * dCd / c25.Cd_mean,
                             noise_Cd=n, resolved="yes" if abs(dCd) > n else "no",
                             dCl=c5.Cl_mean - c25.Cl_mean, dSt=c5.St - c25.St,
                             dSt_pct=100 * (c5.St - c25.St) / c25.St,
                             dksplus_mean=c5.ksplus_blade_mean - c25.ksplus_blade_mean))
    tp = pd.DataFrame(rows)
    # the Ks effect itself at the two time steps (reference: smallest Ks present at both)
    for (a, U), g in tp.groupby(["alpha_deg", "U_ms"]):
        g = g.sort_values("Ks_um")
        r0 = g.iloc[0]
        for _, r in g.iloc[1:].iterrows():
            e5, e25 = r.Cd_Co5 - r0.Cd_Co5, r.Cd_Co2_5 - r0.Cd_Co2_5
            effects.append(dict(alpha_deg=a, U_ms=U, Ks_um=r.Ks_um, reference_Ks_um=r0.Ks_um,
                                effect_Co5=e5, effect_Co2_5=e25, effect_diff=e5 - e25,
                                effect_diff_pct_of_Cd=100 * (e5 - e25) / r0.Cd_Co2_5))
    return tp, pd.DataFrame(effects)


def trends(eff):
    rows = []
    for (a, U, co), g in eff.groupby(["alpha_deg", "U_ms", "maxCo"]):
        g = g.sort_values("Ks_um")
        for q in ("Cd", "Cl"):
            b, se, r2, dof = ols(g.Ks_um, g[q])
            rows.append(dict(alpha_deg=a, U_ms=U, maxCo=co, quantity=q, n=len(g),
                             Ks_um=" ".join(str(int(k)) for k in g.Ks_um),
                             slope_per_100um=100 * b, slope_se_per_100um=100 * se, r2=r2, dof=dof,
                             spearman_rho=spearman(g.Ks_um, g[q]), perm_p_two_sided=perm_p(g.Ks_um, g[q])))
    return pd.DataFrame(rows)


def ksplus_collapse(eff):
    """dCd (%) against the blade-mean Ks+ for alpha 0, every set with a same-maxCo Ks 0 reference."""
    m = (eff.alpha_deg == 0) & (eff.Ks_um > 0) & eff.reference.str.contains("_Ks0_")
    g = eff[m]
    x, y = g.ksplus_mean.to_numpy(), g.dCd_pct.to_numpy()
    b = (x * y).sum() / (x * x).sum()
    res = y - b * x
    se = math.sqrt((res ** 2).sum() / (len(x) - 1) / (x * x).sum())
    return g, dict(slope_pct_per_ksplus=b, slope_se=se, n=len(x), resid_rms_pct=float(np.sqrt((res ** 2).mean())),
                   resid_max_pct=float(np.abs(res).max()))


# ------------------------------------------------------------------ 2. resolved texture
def tex_effects(d):
    tx = d[d.wall == "tex"]
    rows = []
    for (a, m), g in tx.groupby(["alpha_deg", "model"]):
        r0 = one(g, t=0.0)
        for _, r in g.sort_values("t").iterrows():
            n = abs(r.Cd_drift) + abs(r0.Cd_drift)
            dCd = r.Cd_mean - r0.Cd_mean
            dCl = r.Cl_mean - r0.Cl_mean
            nCl = abs(r.Cl_drift) + abs(r0.Cl_drift)
            ref = r["name"] == r0["name"]
            rows.append(dict(
                case=r["name"], reference=r0["name"], alpha_deg=a, model=m, t_mm=r.t, Cd=r.Cd_mean,
                Cd_std=r.Cd_std, Cd_drift=r.Cd_drift, dCd=dCd, dCd_pct=100 * dCd / r0.Cd_mean, noise_Cd=n,
                dCd_over_noise=abs(dCd) / n, resolved_Cd="n/a" if ref else ("yes" if abs(dCd) > n else "no"),
                dCd_pressure=r.Cd_pressure_mean - r0.Cd_pressure_mean,
                dCd_viscous=r.Cd_viscous_mean - r0.Cd_viscous_mean, Cd_viscous=r.Cd_viscous_mean,
                Cl=r.Cl_mean, dCl=dCl, noise_Cl=nCl, resolved_Cl="n/a" if ref else ("yes" if abs(dCl) > nCl else "no"),
                St=r.St, St_peak_frac=r.St_peak_frac, n_cycles_avg=r.n_cycles_avg,
                yplus_mean=r.yplus_blade_mean, yplus_max=r.yplus_blade_max, mesh_check=r.mesh_check,
                Re_k_upper_U_t_over_nu=U_CFD * r.t * 1e-3 / NU))
    te = pd.DataFrame(rows)
    pairs = []
    for (a, t), g in tx.groupby(["alpha_deg", "t"]):
        s, l = one(g, model="SST"), one(g, model="LM")
        dd = s.Cd_mean - l.Cd_mean
        n = abs(s.Cd_drift) + abs(l.Cd_drift)
        pairs.append(dict(alpha_deg=a, t_mm=t, case_SST=s["name"], case_LM=l["name"], Cd_SST=s.Cd_mean,
                          Cd_LM=l.Cd_mean, dCd_SST_minus_LM=dd, dCd_pct_of_LM=100 * dd / l.Cd_mean,
                          noise_Cd=n, resolved="yes" if abs(dd) > n else "no",
                          dCl_SST_minus_LM=s.Cl_mean - l.Cl_mean))
    return te, pd.DataFrame(pairs)


# ------------------------------------------------------------------ 3. concave-convex drag difference
def drag_difference(d):
    """D = Cd(alpha 0) - Cd(alpha 180) at 23 m/s, per roughness level and set; changes against the smooth
    (or smallest-roughness) member of the same set. dN = change of the quasi-steady two-position drive
    Cd0 (1 - lam)^2 - Cd180 (1 + lam)^2 (inferred model)."""
    w0, w1 = (1 - LAM) ** 2, (1 + LAM) ** 2
    sets = []
    wf = d[(d.wall == "wf") & (d.U_ms == U_CFD)]
    sets.append(("wf: alpha 0 maxCo 2.5, alpha 180 maxCo 5", "SST",
                 [(ks, one(wf, alpha_deg=0, Co=2.5, Ks_um=ks), one(wf, alpha_deg=180, Co=5.0, Ks_um=ks))
                  for ks in KS_SWEEP]))
    sets.append(("wf: alpha 0 and 180 maxCo 5", "SST",
                 [(ks, one(wf, alpha_deg=0, Co=5.0, Ks_um=ks), one(wf, alpha_deg=180, Co=5.0, Ks_um=ks))
                  for ks in (50, 200, 400)]))
    tx = d[d.wall == "tex"]
    for m in ("SST", "LM"):
        sets.append((f"tex: {m}", m, [(t, one(tx, alpha_deg=0, model=m, t=t), one(tx, alpha_deg=180, model=m, t=t))
                                      for t in T_SWEEP]))
    rows = []
    for name, model, members in sets:
        x0, a0, b0 = members[0]
        D0 = a0.Cd_mean - b0.Cd_mean
        n0 = abs(a0.Cd_drift) + abs(b0.Cd_drift)
        for x, a, b in members:
            D = a.Cd_mean - b.Cd_mean
            n_own = abs(a.Cd_drift) + abs(b.Cd_drift)
            dD = D - D0
            d0, d180 = a.Cd_mean - a0.Cd_mean, b.Cd_mean - b0.Cd_mean
            dN = d0 * w0 - d180 * w1
            nN = (abs(a.Cd_drift) + abs(a0.Cd_drift)) * w0 + (abs(b.Cd_drift) + abs(b0.Cd_drift)) * w1
            lam = np.linspace(0, 0.25, 26)
            dN_lam = d0 * (1 - lam) ** 2 - d180 * (1 + lam) ** 2
            first = x == x0
            rows.append(dict(
                set=name, model=model, roughness=x, roughness_unit="Ks um" if name.startswith("wf") else "t mm",
                case_alpha0=a["name"], case_alpha180=b["name"], Cd0=a.Cd_mean, Cd180=b.Cd_mean, D=D,
                noise_own=n_own, reference_roughness=x0, dCd0=d0, dCd180=d180, dD=dD,
                dD_pct=100 * dD / D0, noise_dD=n_own + n0, dD_over_noise=abs(dD) / (n_own + n0),
                resolved="n/a" if first else ("yes" if abs(dD) > n_own + n0 else "no"),
                dN_lam=dN, noise_dN=nN, lam=LAM,
                dN_sign_lam_0_to_0p25=("n/a" if first else
                                       ("+" if (dN_lam > 0).all() else "-" if (dN_lam < 0).all() else "mixed"))))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ 4. measured roughness -> Ks (assumed)
def mapping(d, meas):
    wf = d[(d.wall == "wf") & (d.U_ms == U_CFD)]
    cd0 = [one(wf, alpha_deg=0, Co=2.5, Ks_um=k).Cd_mean for k in KS_SWEEP]
    cd180 = [one(wf, alpha_deg=180, Co=5.0, Ks_um=k).Cd_mean for k in KS_SWEEP]
    cd90 = [one(wf, alpha_deg=90, Co=5.0, Ks_um=k).Cd_mean for k in KS_SWEEP]

    def interp(ks):
        ks = min(ks, 400.0)
        c0, c1 = np.interp(ks, KS_SWEEP, cd0), np.interp(ks, KS_SWEEP, cd180)
        return c0, c1, c0 - c1, np.interp(ks, KS_SWEEP, cd90)

    surf = meas["surf"].set_index("rotor")
    rows = []
    for rot in ROTORS:
        ra, pa = float(surf.loc[rot, "Ra_lc025_um"]), float(surf.loc[rot, "Pa_um"])
        klo, khi = K_SCAN[rot]
        nominal = 2.09 * FS_T[rot] * 1000
        rules = {"Ks = k (scan height)": (klo, khi), "Ks = 3-6 Ra": (3 * ra, 6 * ra),
                 "Ks = 3-6 Pa": (3 * pa, 6 * pa), "Ks = 2.09 t (nominal texture)": (nominal, nominal)}
        for rule, (lo, hi) in rules.items():
            mid = 0.5 * (lo + hi)
            c0, c1, D, c90 = interp(mid)
            rows.append(dict(rotor=rot, t_mm=FS_T[rot], Ra_um=ra, Pa_um=pa, rule=rule, Ks_lo_um=lo, Ks_hi_um=hi,
                             Ks_mid_um=mid, beyond_sweep=mid > 400, Cd0_interp=c0, Cd180_interp=c1, D_interp=D,
                             Cd90_interp=c90, ksplus_note="interpolated in the 23 m/s wf sweep (alpha 0 maxCo 2.5, "
                                                          "alpha 90 and 180 maxCo 5)"))
    mp = pd.DataFrame(rows)
    # D change relative to Plain under the same rule
    out = []
    for rule, g in mp.groupby("rule", sort=False):
        Dp = one(g, rotor="Plain").D_interp
        for _, r in g.iterrows():
            out.append(dict(rule=rule, rotor=r.rotor, dD_vs_Plain=r.D_interp - Dp, dD_pct_vs_Plain=100 * (r.D_interp - Dp) / Dp))
    mp = mp.merge(pd.DataFrame(out), on=["rule", "rotor"])
    # FS 0.20 at both ends of its k range (84 and 97 um) against Plain at 38 um
    k_end = {}
    for k in (84.0, 97.0):
        k_end[k] = 100 * (interp(k)[2] - interp(38.0)[2]) / interp(38.0)[2]
    return mp, k_end


def measured(meas):
    comp = meas["comp"]
    c = comp[comp.relative_to == "Plain"].set_index("rotor")
    bys = meas["bys"]
    v23 = bys.wind_mps.iloc[(bys.wind_mps - U_CFD).abs().argmin()]
    at = bys[np.isclose(bys.wind_mps, v23)].set_index("rotor")
    rows = []
    for rot in ROTORS[1:]:
        rows.append(dict(rotor=rot, t_mm=FS_T[rot], change_pct=c.loc[rot, "change_pct"],
                         tukey95_lo_pct=c.loc[rot, "tukey95_lo_pct"], tukey95_hi_pct=c.loc[rot, "tukey95_hi_pct"],
                         wind_mps_near_23=v23, change_at_23_pct=at.loc[rot, "p_max_change_vs_plain_pct"],
                         pointwise95_halfwidth_at_23_pct=at.loc[rot, "pointwise95_halfwidth_pct"]))
    num, tk = meas["num"], meas["tacho"]
    extra = dict(stepV={r: num[k] for r, k in (("Plain", "stepVP"), ("FS 0.05", "stepVA"), ("FS 0.10", "stepVB"),
                                                ("FS 0.20", "stepVC"))},
                 band=(num["bandLo"], num["bandHi"]), gMaxB=num["gMaxB"], gMaxVB=num["gMaxVB"],
                 gMaxC=num["gMaxC"], gMaxVC=num["gMaxVC"],
                 lam_peak={r: float(tk[k]) for r, k in (("Plain", "tkTsrP"), ("FS 0.05", "tkTsrA"),
                                                         ("FS 0.10", "tkTsrB"), ("FS 0.20", "tkTsrC"))})
    # per-speed gains for the onset table
    g = bys[bys.rotor != "Plain"][["rotor", "wind_mps", "p_max_change_vs_plain_pct", "pointwise95_halfwidth_pct"]]
    return pd.DataFrame(rows), extra, g


# ------------------------------------------------------------------ alpha-0 flow states (context)
def alpha0_states(d, s1):
    rows = []
    for _, r in s1[(s1.alpha_deg == 0)].iterrows():
        rows.append(dict(table="section_polars", case=r["name"], U_ms=r.U_ms, model=r.model, family=f"Stage 1 {r.level}",
                         maxCo=r.maxCo, roughness="smooth", Cd=r.Cd_mean, Cd_std=r.Cd_std, Cl=r.Cl_mean, St=r.St))
    for _, r in d[d.alpha_deg == 0].iterrows():
        rough = f"Ks {int(r.Ks_um)} um" if r.wall == "wf" else f"t {r.t:.2f} mm"
        rows.append(dict(table="stage2_polars", case=r["name"], U_ms=r.U_ms, model=r.model,
                         family="Stage 2 wf" if r.wall == "wf" else "Stage 2 tex", maxCo=r.Co, roughness=rough,
                         Cd=r.Cd_mean, Cd_std=r.Cd_std, Cl=r.Cl_mean, St=r.St))
    st = pd.DataFrame(rows)
    st["state"] = np.where(st.Cd > 2.5, "high-drag", "low-drag")
    return st


# ================================================================== figures
def save(fig, name):
    p = FIG / f"{name}.png"
    fig.savefig(p, dpi=200, facecolor="white")
    plt.close(fig)
    return p


def legend_handles(items):
    return [Line2D([], [], **kw) for kw in items]


def fig_wf_vs_ks(d, eff, q="Cd"):
    wf = d[(d.wall == "wf") & (d.U_ms == U_CFD)]
    fig, axes = plt.subplots(3, 1, figsize=(3.6, 6.4), sharex=True, constrained_layout=True)
    spec = [(0, "\u03b1 = 0\u00b0: concave side into the wind"),
            (90, "\u03b1 = 90\u00b0: edge-on, tip A first"),
            (180, "\u03b1 = 180\u00b0: convex side into the wind")]
    col, dcol = (f"{q}_mean", f"{q}_drift")
    for ax, (a, title), lab in zip(axes, spec, "abc"):
        g = wf[wf.alpha_deg == a]
        primary = 2.5 if a == 0 else 5.0
        for co in (2.5, 5.0):
            s = g[g.Co == co].sort_values("Ks_um")
            if s.empty:
                continue
            dx = 0 if co == primary else 9
            x = s.Ks_um.to_numpy() + dx
            if co == primary:
                ax.plot(x, s[col], ls=MODEL_LS["SST"], color=INK2, lw=1.0, zorder=2)
            ax.errorbar(x, s[col], yerr=s[dcol].abs(), fmt="none", ecolor=MUTED, elinewidth=0.8, capsize=2,
                        zorder=3)
            for xi, (_, r) in zip(x, s.iterrows()):
                ax.plot(xi, r[col], zorder=4, **mk("SST", co, ks_color(r.Ks_um)))
        e = eff[(eff.alpha_deg == a) & (eff.U_ms == U_CFD) & (eff.maxCo == primary) & (eff.Ks_um == 400)].iloc[0]
        val = e[f"d{q}_pct"]
        txt = (sgn(val, 1, " %") if q == "Cd" else "\u0394$C_l$ = " + sgn(e["dCl"], 3)) + " at 400 \u00b5m"
        ax.annotate(txt, (400, e[q]), xytext=(-6, 9 if e[f"d{q}"] > 0 else -11),
                    textcoords="offset points", ha="right", va="center", fontsize=6.8, color=BLACK)
        ax.set_title(f"({lab}) {title}", loc="left")
        ax.set_ylabel("$C_d$ (\u2013)" if q == "Cd" else "$C_l$ (\u2013)")
        ax.margins(y=0.18)
    axes[-1].set_xlabel("Sand-grain roughness $K_s$ (\u00b5m)")
    axes[-1].set_xticks(KS_SWEEP)
    axes[-1].set_xlim(-20, 425)
    h = legend_handles([
        dict(marker="s", ls="none", mfc=INK2, mec=INK2, ms=MS, label="maxCo 2.5"),
        dict(marker="s", ls="none", mfc="white", mec=INK2, mew=1.1, ms=MS, label="maxCo 5"),
        dict(color=MUTED, lw=0.8, marker="|", ms=6, label="\u00b1|drift|"),
    ])
    axes[0].legend(handles=h, loc="upper right", ncol=3, handletextpad=0.3, columnspacing=0.9)
    fig.suptitle("kOmegaSST + rough wall function, 23 m/s; colour = $K_s$ (black: smooth)", fontsize=7, x=0.02,
                 ha="left", color=INK2)
    return save(fig, f"roughness_{q.lower()}_vs_ks")


def fig_speed(eff, col_fit):
    g_all, fit = col_fit
    fig, (ax, bx) = plt.subplots(2, 1, figsize=(3.6, 5.6), constrained_layout=True)
    e0 = eff[(eff.alpha_deg == 0)]
    # (a) dCd % against U
    ax.axhline(0, color=BLACK, lw=0.8, zorder=1)
    ax.text(8.0, 0.35, "smooth reference ($K_s$ = 0)", ha="left", va="bottom", fontsize=6.5, color=BLACK)
    dx = {50: -0.9, 100: -0.45, 200: 0.0, 400: 0.45}       # small offsets so the error bars stay apart
    for ks in (100, 200):
        s = e0[(e0.maxCo == 2.5) & (e0.Ks_um == ks)].sort_values("U_ms")
        x = s.U_ms + dx[ks]
        ax.plot(x, s.dCd_pct, ls=MODEL_LS["SST"], color=ks_color(ks), lw=1.1, zorder=2)
        ax.errorbar(x, s.dCd_pct, yerr=100 * s.noise_Cd / (s.Cd - s.dCd), fmt="none", ecolor=ks_color(ks),
                    elinewidth=0.8, capsize=2, zorder=3)
        for xi, (_, r) in zip(x, s.iterrows()):
            ax.plot(xi, r.dCd_pct, zorder=4, **mk("SST", 2.5, ks_color(ks)))
    for ks in (50, 400):
        r = e0[(e0.maxCo == 2.5) & (e0.Ks_um == ks) & (e0.U_ms == U_CFD)].iloc[0]
        ax.errorbar(r.U_ms + dx[ks], r.dCd_pct, yerr=100 * r.noise_Cd / (r.Cd - r.dCd), fmt="none",
                    ecolor=ks_color(ks), elinewidth=0.8, capsize=2, zorder=3)
        ax.plot(r.U_ms + dx[ks], r.dCd_pct, zorder=4, **mk("SST", 2.5, ks_color(ks)))
    s5 = e0[(e0.maxCo == 5.0) & (e0.U_ms == 38.0) & (e0.Ks_um > 0)]
    for _, r in s5.iterrows():
        ax.errorbar(r.U_ms + 1.6 + dx[r.Ks_um], r.dCd_pct, yerr=100 * r.noise_Cd / (r.Cd - r.dCd), fmt="none",
                    ecolor=ks_color(r.Ks_um), elinewidth=0.8, capsize=2, zorder=3)
        ax.plot(r.U_ms + 1.6 + dx[r.Ks_um], r.dCd_pct, zorder=4, **mk("SST", 5.0, ks_color(r.Ks_um)))
    ax.set_xlabel("Wind speed U (m/s)")
    ax.set_ylabel("$\\Delta C_d$ vs $K_s$ = 0 (%)")
    ax.set_xticks([10.2, 23.0, 38.0])
    ax.set_xlim(7, 42)
    ax.set_ylim(-14, 4.5)
    ax.set_yticks(np.arange(-14, 5, 2))
    ax.set_title("(a) \u03b1 = 0\u00b0, change against the smooth case at each speed", loc="left")
    h = legend_handles([
        dict(marker="s", ls="none", mfc="white", mec=INK2, mew=1.1, ms=MS, label="open: maxCo 5"),
        dict(color=MUTED, lw=0.8, marker="|", ms=6, label="\u00b1(|drift| + |drift$_{ref}$|)"),
    ])
    ax.legend(handles=h, loc="lower left", ncol=1, handletextpad=0.3)
    # (b) collapse on Ks+
    bx.axvspan(0, 2.25, color=BAND1, lw=0, zorder=0)
    bx.text(1.12, -5.2, "function off at local $K_s^+$ < 2.25", rotation=90, ha="center", va="center",
            fontsize=5.8, color=INK2)
    xs = np.linspace(0, 32, 50)
    bx.plot(xs, fit["slope_pct_per_ksplus"] * xs, color=MUTED, lw=0.9, zorder=1)
    bx.text(31, 2.4, f"grey line: fit through 0, {sgn(fit['slope_pct_per_ksplus'], 2)} % per unit $K_s^+$",
            ha="right", fontsize=6.5, color=INK2)
    shape_u = {10.2: "o", 23.0: "s", 38.0: "^"}
    for _, r in g_all.iterrows():
        filled = r.maxCo < 5
        c = ks_color(r.Ks_um)
        # verifier, 13 Oct: the drift-rule bars of panel (a) are drawn here too, so the collapse is read
        # against the noise of each point (2.5-5 % of Cd at 23 and 38 m/s), not against the residuals alone
        bx.errorbar(r.ksplus_mean, r.dCd_pct, yerr=100 * r.noise_Cd / (r.Cd - r.dCd), fmt="none", ecolor=c,
                    elinewidth=0.6, capsize=1.5, alpha=0.55, zorder=2)
        bx.plot(r.ksplus_mean, r.dCd_pct, marker=shape_u[r.U_ms], ms=MS, ls="none", mec=c,
                mfc=c if filled else "white", mew=1.1, zorder=3)
    hs = [Line2D([], [], marker=m, ls="none", mfc=INK2, mec=INK2, ms=MS, label=f"{u:g} m/s") for u, m in shape_u.items()]
    hs += [Line2D([], [], marker="s", ls="none", mfc=ks_color(k), mec=ks_color(k), ms=MS, label=f"$K_s$ {k} \u00b5m")
           for k in (50, 100, 200, 400)]
    bx.legend(handles=hs, loc="lower left", bbox_to_anchor=(0.08, 0.0), ncol=2, handletextpad=0.3,
              columnspacing=0.8, title="colour: $K_s$ (both panels); shape: U", title_fontsize=6.5)
    bx.set_xlabel("Roughness Reynolds number $K_s^+$, blade mean (\u2013)")
    bx.set_ylabel(r"$\Delta C_d$ vs $K_s$ = 0 (%)")
    bx.set_xlim(0, 32)
    bx.set_ylim(-14, 4.5)       # same scale as panel (a)
    bx.set_yticks(np.arange(-14, 5, 2))
    bx.axhline(0, color=BLACK, lw=0.8, zorder=1)
    bx.set_title("(b) the same changes and bars against $K_s^+$ (open: maxCo 5)", loc="left")
    return save(fig, "roughness_speed_sweep")


def fig_ksplus_mapping(eff, mp):
    fig, (ax, bx) = plt.subplots(2, 1, figsize=(3.6, 6.0), constrained_layout=True,
                                 gridspec_kw=dict(height_ratios=[1, 1.15]))
    # (a) Ks+ mean (marker) and max (whisker) for every rough wf case
    ax.axhspan(0.5, 2.25, color=BAND1, lw=0, zorder=0)
    ax.axhspan(90, 300, color=BAND2, lw=0, zorder=0)
    ax.text(395, 1.4, "smooth (roughness function off)", ha="right", va="center", fontsize=6, color=INK2)
    ax.text(395, 160, "fully rough", ha="right", va="center", fontsize=6, color=INK2)
    ax.text(395, 15, "transitionally\nrough", ha="right", va="center", fontsize=6, color=INK2)
    conds = [(0, 10.2, 2.5, "o", -14), (0, 23.0, 2.5, "s", -7), (0, 38.0, 2.5, "^", 0),
             (90, 23.0, 5.0, "D", 7), (180, 23.0, 5.0, "v", 14)]
    for a, U, co, m, dx in conds:
        s = eff[(eff.alpha_deg == a) & (eff.U_ms == U) & (eff.maxCo == co) & (eff.Ks_um > 0)]
        for _, r in s.iterrows():
            c = ks_color(r.Ks_um)
            ax.plot([r.Ks_um + dx] * 2, [r.ksplus_mean, r.ksplus_max], color=c, lw=0.8, zorder=2)
            ax.plot(r.Ks_um + dx, r.ksplus_mean, marker=m, ms=4.6, ls="none", mfc=c, mec=c, zorder=3)
    hs = [Line2D([], [], marker=m, ls="none", mfc=INK2, mec=INK2, ms=4.6,
                 label=f"\u03b1 {a}\u00b0, {U:g} m/s") for a, U, co, m, dx in conds]
    ax.legend(handles=hs, loc="upper left", ncol=2, handletextpad=0.2, columnspacing=0.7)
    ax.set_yscale("log")
    ax.set_ylim(0.8, 300)
    ax.set_xlim(20, 425)
    ax.set_xticks([50, 100, 200, 400])
    ax.set_xlabel("Sand-grain roughness $K_s$ (\u00b5m)")
    ax.set_ylabel("$K_s^+$ (\u2013): marker mean, line to max")
    ax.set_title("(a) Roughness Reynolds number on the painted faces", loc="left")
    # (b) where the measured surfaces sit on the Ks axis (assumed mappings)
    lanes = [("Ks = k (scan height)", 0.27, "o"), ("Ks = 3-6 Ra", 0.09, None), ("Ks = 3-6 Pa", -0.09, None),
             ("Ks = 2.09 t (nominal texture)", -0.27, "^")]
    for i, rot in enumerate(ROTORS):
        y0 = len(ROTORS) - 1 - i
        c = FS_COLOR[rot]
        for rule, dy, m in lanes:
            r = mp[(mp.rotor == rot) & (mp.rule == rule)].iloc[0]
            y = y0 + dy
            if m is None:
                bx.plot([r.Ks_lo_um, r.Ks_hi_um], [y, y], color=c, lw=3.0 if "Ra" in rule else 1.4,
                        solid_capstyle="butt", zorder=3)
            elif r.Ks_hi_um > 0:
                if r.Ks_hi_um > r.Ks_lo_um:
                    bx.plot([r.Ks_lo_um, r.Ks_hi_um], [y, y], color=c, lw=1.4, zorder=3)
                bx.plot(r.Ks_mid_um, y, marker=m, ms=4.6, ls="none", mfc=c, mec=c, zorder=4)
            else:
                bx.text(10.5, y, "2.09 t = 0", va="center", ha="left", fontsize=5.8, color=c)
    for k in (50, 100, 200, 400):
        bx.axvline(k, color="#d0d0d0", lw=0.7, zorder=1)
    for yp, lab in ((440, "$y_P$, 23 and 38 m/s"), (650, "$y_P$, 10.2 m/s")):
        bx.axvline(yp, color=INK2, lw=0.9, zorder=2)
        bx.text(yp * 1.04, -0.62, lab, rotation=90, fontsize=5.8, color=INK2, va="bottom", ha="left")
    bx.set_xscale("log")
    bx.set_xlim(10, 1500)
    bx.set_xticks([10, 20, 50, 100, 200, 500, 1000])
    bx.set_xticklabels(["10", "20", "50", "100", "200", "500", "1000"])
    bx.minorticks_off()
    bx.set_ylim(-0.7, len(ROTORS) - 0.45)
    bx.set_yticks(range(len(ROTORS)))
    bx.set_yticklabels(ROTORS[::-1])
    bx.grid(axis="y", visible=False)
    bx.set_xlabel("Sand-grain roughness $K_s$ (\u00b5m), log scale")
    bx.set_title("(b) Measured surfaces mapped to $K_s$ (assumed rules)", loc="left")
    hs = [Line2D([], [], marker="o", ls="none", mfc=INK2, mec=INK2, ms=4.6, label="$K_s$ = k (scan)"),
          Line2D([], [], marker="^", ls="none", mfc=INK2, mec=INK2, ms=4.6, label="2.09 t (nominal)"),
          Line2D([], [], color=INK2, lw=3.0, label="3\u20136 Ra"),
          Line2D([], [], color="#d0d0d0", lw=0.7, label="CFD sweep values"),
          Line2D([], [], color=INK2, lw=1.4, label="3\u20136 Pa")]
    bx.legend(handles=hs, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=3, handletextpad=0.3,
              columnspacing=0.8)
    return save(fig, "roughness_ksplus_validity")


def fig_texture(te):
    fig, axes = plt.subplots(2, 1, figsize=(3.6, 4.9), sharex=True, constrained_layout=True)
    for ax, a, lab, title in ((axes[0], 0, "a", "\u03b1 = 0\u00b0: concave side into the wind"),
                              (axes[1], 180, "b", "\u03b1 = 180\u00b0: convex side into the wind")):
        for m, dx in (("SST", -0.003), ("LM", 0.003)):
            s = te[(te.alpha_deg == a) & (te.model == m)].sort_values("t_mm")
            x = s.t_mm.to_numpy() + dx
            ax.plot(x, s.Cd, ls=MODEL_LS[m], color=INK2, lw=1.0, zorder=2)
            ax.errorbar(x, s.Cd, yerr=s.Cd_drift.abs(), fmt="none", ecolor=MUTED, elinewidth=0.8, capsize=2, zorder=3)
            for xi, (_, r) in zip(x, s.iterrows()):
                ax.plot(xi, r.Cd, zorder=4, **mk(m, 5.0, T_COLOR[round(r.t_mm, 2)]))
            for _, r in s[s.resolved_Cd == "yes"].iterrows():
                ax.annotate(sgn(r.dCd_pct, 1, " %"), (r.t_mm + dx, r.Cd), xytext=(-7, 3), textcoords="offset points",
                            ha="right", va="bottom", fontsize=6.6, color=BLACK)
        ax.set_title(f"({lab}) {title}", loc="left")
        ax.set_ylabel("$C_d$ (\u2013)")
        ax.margins(y=0.15)
    axes[0].set_ylim(1.64, 1.93)
    axes[-1].set_xlabel("Texture amplitude t (mm)")
    axes[-1].set_xticks(T_SWEEP)
    axes[-1].set_xlim(-0.015, 0.215)
    h = legend_handles([
        dict(marker="s", ls=MODEL_LS["SST"], color=INK2, mfc="white", mec=INK2, mew=1.1, ms=MS,
             label="SST (fully turbulent)"),
        dict(marker="o", ls=MODEL_LS["LM"], color=INK2, mfc="white", mec=INK2, mew=1.1, ms=MS,
             label="LM (transition model)"),
        dict(color=MUTED, lw=0.8, marker="|", ms=6, label="\u00b1|drift|"),
    ])
    axes[0].legend(handles=h, loc="lower right", ncol=1, handletextpad=0.4)
    fig.suptitle("Resolved texture, 23 m/s, maxCo 5, 80 c/U (mean of last 50); % = resolved changes",
                 fontsize=6.5, x=0.02, ha="left", color=INK2)
    return save(fig, "roughness_texture")


def fig_drag_difference(dd, mt):
    fig, axes = plt.subplots(3, 1, figsize=(3.6, 7.6), constrained_layout=True,
                             gridspec_kw=dict(height_ratios=[1, 1, 0.9]))
    ax, bx, cx = axes
    # (a) wall functions against Ks
    for lo, hi in ((36, 40), (84, 97)):
        ax.axvspan(lo, hi, color=BAND2, lw=0, zorder=0)
    a1 = dd[dd.set.str.startswith("wf: alpha 0 maxCo 2.5")]
    a2 = dd[dd.set.str.startswith("wf: alpha 0 and 180 maxCo 5")]
    ax.plot(a1.roughness, a1.D, ls=MODEL_LS["SST"], color=INK2, lw=1.0, zorder=2)
    ax.errorbar(a1.roughness, a1.D, yerr=a1.noise_own, fmt="none", ecolor=MUTED, elinewidth=0.8, capsize=2, zorder=3)
    for _, r in a1.iterrows():
        ax.plot(r.roughness, r.D, zorder=4, **mk("SST", 2.5, ks_color(r.roughness)))
    ax.errorbar(a2.roughness + 9, a2.D, yerr=a2.noise_own, fmt="none", ecolor=MUTED, elinewidth=0.8, capsize=2,
                zorder=3)
    for _, r in a2.iterrows():
        ax.plot(r.roughness + 9, r.D, zorder=4, **mk("SST", 5.0, ks_color(r.roughness)))
    # label every change of the primary set that passes the drift rule (verifier, 13 Oct: Ks 200 was resolved
    # but unlabelled, against the caption rule "a label marks a change resolved by the drift rule")
    for _, r in a1[a1.resolved == "yes"].iterrows():
        txt = sgn(r.dD_pct, 1, " %") + (" at 400 \u00b5m" if r.roughness == 400 else "")
        ax.annotate(txt, (r.roughness, r.D), xytext=(-8, -2), textcoords="offset points", ha="right", va="top",
                    fontsize=6.6)
    ax.text(41, 1.095, "\u2190 Plain, FS 0.05, FS 0.10\n    (k \u2248 38 \u00b5m)", ha="left", va="bottom", fontsize=5.8,
            color=INK2)
    ax.text(99, 1.20, "\u2190 FS 0.20\n    (k 84\u201397 \u00b5m)", ha="left", va="bottom", fontsize=5.8, color=INK2)
    ax.set_xticks(KS_SWEEP)
    ax.set_xlim(-20, 425)
    ax.set_ylim(1.08, 1.62)
    ax.set_xlabel("Sand-grain roughness $K_s$ (\u00b5m)")
    ax.set_ylabel("D = $C_d$(0\u00b0) \u2212 $C_d$(180\u00b0) (\u2013)")
    ax.set_title("(a) Rough wall function, SST, 23 m/s; grey: $K_s$ \u2248 k (assumed)", loc="left")
    h = legend_handles([
        dict(marker="s", ls="none", mfc=INK2, mec=INK2, ms=MS, label="0\u00b0 at maxCo 2.5, 180\u00b0 at 5"),
        dict(marker="s", ls="none", mfc="white", mec=INK2, mew=1.1, ms=MS, label="both at maxCo 5"),
        dict(color=MUTED, lw=0.8, marker="|", ms=6, label="\u00b1(|drift| 0\u00b0 + |drift| 180\u00b0)"),
    ])
    ax.legend(handles=h, loc="upper right", ncol=1, handletextpad=0.3)
    # (b) resolved texture
    for m, dx in (("SST", -0.003), ("LM", 0.003)):
        s = dd[dd.set == f"tex: {m}"].sort_values("roughness")
        x = s.roughness.to_numpy() + dx
        bx.plot(x, s.D, ls=MODEL_LS[m], color=INK2, lw=1.0, zorder=2)
        bx.errorbar(x, s.D, yerr=s.noise_own, fmt="none", ecolor=MUTED, elinewidth=0.8, capsize=2, zorder=3)
        for xi, (_, r) in zip(x, s.iterrows()):
            bx.plot(xi, r.D, zorder=4, **mk(m, 5.0, T_COLOR[round(r.roughness, 2)]))
            if r.resolved == "yes":
                bx.annotate(sgn(r.dD_pct, 1, " %") + f" ({m})", (xi, r.D), xytext=(-7, -3),
                            textcoords="offset points", ha="right", va="top", fontsize=6.6)
    bx.set_xticks(T_SWEEP)
    bx.set_xlim(-0.015, 0.22)
    bx.set_ylabel("D = $C_d$(0\u00b0) \u2212 $C_d$(180\u00b0) (\u2013)")
    bx.set_xlabel("Texture amplitude t (mm)")
    bx.set_title("(b) Resolved texture, 23 m/s, maxCo 5", loc="left")
    h = legend_handles([
        dict(marker="s", ls=MODEL_LS["SST"], color=INK2, mfc="white", mec=INK2, mew=1.1, ms=MS, label="SST"),
        dict(marker="o", ls=MODEL_LS["LM"], color=INK2, mfc="white", mec=INK2, mew=1.1, ms=MS, label="LM"),
    ])
    bx.legend(handles=h, loc="upper right", ncol=2, handletextpad=0.3)
    bx.margins(y=0.2)
    # (c) measured peak-power change (wind tunnel)
    cx.axhline(0, color=BLACK, lw=0.8, zorder=1)
    cx.plot(0, 0, marker="D", ms=MS, ls="none", mfc=BLACK, mec=BLACK, zorder=4)
    for _, r in mt.iterrows():
        c = FS_COLOR[r.rotor]
        cx.errorbar(r.t_mm - 0.004, r.change_pct, yerr=[[r.change_pct - r.tukey95_lo_pct], [r.tukey95_hi_pct - r.change_pct]],
                    fmt="none", ecolor=c, elinewidth=1.0, capsize=2, zorder=3)
        cx.plot(r.t_mm - 0.004, r.change_pct, marker="D", ms=MS, ls="none", mfc=c, mec=c, zorder=4)
        cx.errorbar(r.t_mm + 0.004, r.change_at_23_pct, yerr=r.pointwise95_halfwidth_at_23_pct, fmt="none", ecolor=c,
                    elinewidth=1.0, capsize=2, zorder=3)
        cx.plot(r.t_mm + 0.004, r.change_at_23_pct, marker="D", ms=MS, ls="none", mfc="white", mec=c, mew=1.1, zorder=4)
    cx.set_xticks([0, 0.05, 0.10, 0.20])
    cx.set_xlim(-0.015, 0.22)
    cx.set_xlabel("Fuzzy-skin thickness (mm)")
    cx.set_ylabel(r"$P_{max}$ change vs Plain (%)")
    cx.set_title("(c) Measured, wind tunnel, 1 Oct 2026", loc="left")
    h = legend_handles([
        dict(marker="D", ls="none", mfc=INK2, mec=INK2, ms=MS, label="mean over 10.2\u201338 m/s, Tukey 95 %"),
        dict(marker="D", ls="none", mfc="white", mec=INK2, mew=1.1, ms=MS, label="at 23.0 m/s, pointwise 95 %"),
    ])
    cx.legend(handles=h, loc="upper left", ncol=1, handletextpad=0.3)
    cx.set_ylim(-5, 45)
    return save(fig, "roughness_drag_difference")


def fig_states(st):
    fig, ax = plt.subplots(figsize=(3.6, 3.2), constrained_layout=True)
    s = st[np.isclose(st.U_ms, U_CFD)]
    shape = {"Stage 1": "^", "Stage 2 wf": "s", "Stage 2 tex": "o"}
    for _, r in s.iterrows():
        fam = "Stage 1" if r.family.startswith("Stage 1") else r.family
        if r.roughness == "smooth":
            c = BLACK
        elif r.roughness.startswith("Ks"):
            c = ks_color(int(r.roughness.split()[1]))
        else:
            c = T_COLOR[round(float(r.roughness.split()[1]), 2)]
        filled = r.model == "SST"
        ax.plot(r.Cl, r.Cd, marker=shape[fam], ms=MS, ls="none", mec=c, mfc=c if filled else "white", mew=1.1, zorder=3)
        # verifier, 13 Oct: label the Stage 1 points by mesh and maxCo (SST) or Tu (LM), so the figure shows
        # the claim it illustrates (the same smooth section lands in either state depending on maxCo and Tu)
        if fam == "Stage 1":
            lvl = r.family.split()[-1]
            if r.model == "SST":
                lab = f"{lvl[0].upper()}{r.maxCo:g}"
            else:
                lab = f"LM Tu {float(re.search(r'_Tu([0-9.]+)', r.case).group(1)):g} %"
            dx, dy, ha, va = {"C5": (-4, -4, "right", "top"), "M5": (0, 5, "center", "bottom"),
                              "C2.5": (-4, 3, "right", "bottom"), "M2.5": (4, -3, "left", "top"),
                              "F2.5": (5, 0, "left", "center"), "LM Tu 1 %": (-5, 2, "right", "center"),
                              "LM Tu 0.5 %": (4, 4, "left", "bottom"),
                              "LM Tu 3 %": (5, 0, "left", "center")}.get(lab, (4, 4, "left", "bottom"))
            ax.annotate(lab, (r.Cl, r.Cd), xytext=(dx, dy), textcoords="offset points", ha=ha, va=va,
                        fontsize=5.8, color=INK2)
    ax.axhline(2.5, color=MUTED, lw=0.7, zorder=1)
    ax.text(-0.78, 2.53, "high-drag state", fontsize=6.6, va="bottom", color=INK2)
    ax.text(-0.78, 2.47, "low-drag state", fontsize=6.6, va="top", color=INK2)
    ax.text(-0.78, 2.32, "Stage 1 labels: mesh (C coarse, M medium,\nF fine) and maxCo, SST at Tu 1 %;\n"
            "LM: medium mesh, maxCo 5, Tu as given.\nColour: roughness (black: smooth; light to\n"
            "dark blue: larger $K_s$ or t).", fontsize=5.8, va="top", ha="left", color=INK2, linespacing=1.25)
    hs = [Line2D([], [], marker="^", ls="none", mfc=INK2, mec=INK2, ms=MS, label="Stage 1 (smooth, low-Re)"),
          Line2D([], [], marker="s", ls="none", mfc=INK2, mec=INK2, ms=MS, label="Stage 2 wall function"),
          Line2D([], [], marker="o", ls="none", mfc=INK2, mec=INK2, ms=MS, label="Stage 2 texture"),
          Line2D([], [], marker="o", ls="none", mfc="white", mec=INK2, mew=1.1, ms=MS, label="open: LM; filled: SST")]
    ax.legend(handles=hs, loc="center right", handletextpad=0.3)
    ax.set_xlabel("$C_l$ (\u2013)")
    ax.set_ylabel("$C_d$ (\u2013)")
    ax.set_xlim(-0.8, 0.45)
    ax.set_ylim(1.65, 3.35)
    ax.set_title("\u03b1 = 0\u00b0, 23 m/s: every case, both tables", loc="left")
    return save(fig, "roughness_alpha0_states")


# ================================================================== main
def main():
    style()
    FIG.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    d, s1, meas = load()
    assert len(d) == 43, len(d)

    eff = wf_effects(d)
    tp, teff = timestep_pairs(d)
    tr = trends(eff)
    col_g, col_fit = ksplus_collapse(eff)
    te, tpairs = tex_effects(d)
    dd = drag_difference(d)
    mp, k_end = mapping(d, meas)
    mt, mextra, mby = measured(meas)
    st = alpha0_states(d, s1)

    # required section-drag changes for the measured gains (inferred, quasi-steady two-position model)
    wfr = d[(d.wall == "wf") & (d.U_ms == U_CFD)]
    refs = {"literature shells": CD_SHELL_LIT,
            "CFD wf Ks 0 (23 m/s)": (one(wfr, alpha_deg=0, Co=2.5, Ks_um=0).Cd_mean,
                                      one(wfr, alpha_deg=180, Co=5.0, Ks_um=0).Cd_mean)}
    req = []
    mti = mt.set_index("rotor")
    for lam in (LAM, 0.08):          # 0.125: measured peak; 0.08: the two-position model's own optimum
        w0, w1 = (1 - lam) ** 2, (1 + lam) ** 2
        for lab, (c0, c1) in refs.items():
            N = c0 * w0 - c1 * w1
            for rot, g in (("FS 0.10", mti.loc["FS 0.10", "change_pct"]), ("FS 0.20", mti.loc["FS 0.20", "change_pct"]),
                           ("FS 0.10 at 23 m/s", mti.loc["FS 0.10", "change_at_23_pct"]),
                           ("FS 0.20 at 23 m/s", mti.loc["FS 0.20", "change_at_23_pct"])):
                dN = g / 100 * N
                req.append(dict(reference=lab, Cd0=c0, Cd180=c1, lam=lam, N=N, measured=rot, gain_pct=g,
                                dN_needed=dN, dCd0_alone=dN / w0, dCd0_alone_pct=100 * dN / w0 / c0,
                                dCd180_alone=-dN / w1, dCd180_alone_pct=-100 * dN / w1 / c1))
    req = pd.DataFrame(req)
    # SST - LM gap of D on the texture meshes (transition bracket per t)
    dsl = []
    for t in T_SWEEP:
        s, l = one(dd, set="tex: SST", roughness=t), one(dd, set="tex: LM", roughness=t)
        dsl.append(dict(t_mm=t, D_SST=s.D, D_LM=l.D, D_SST_minus_LM=s.D - l.D, pct_of_LM=100 * (s.D - l.D) / l.D,
                        noise=s.noise_own + l.noise_own,
                        resolved="yes" if abs(s.D - l.D) > s.noise_own + l.noise_own else "no"))
    dsl = pd.DataFrame(dsl)
    # ranges quoted in the quality checks and findings
    wfall = d[d.wall == "wf"]
    rough = wfall[wfall.Ks_um > 0]
    hi_state = st[(st.table == "stage2_polars") & st.family.eq("Stage 2 wf")]
    lo_state = st[(st.table == "stage2_polars") & st.family.eq("Stage 2 tex")]
    q = dict(
        n_cases=len(d), n_wf=int((d.wall == "wf").sum()), n_tex=int((d.wall == "tex").sum()),
        alpha0_wf_drift_negative=f"{int((d[(d.wall == 'wf') & (d.alpha_deg == 0)].Cd_drift < 0).sum())} of "
                                 f"{int(((d.wall == 'wf') & (d.alpha_deg == 0)).sum())}",
        alpha0_wf_drift_range=[float(d[(d.wall == 'wf') & (d.alpha_deg == 0)].Cd_drift.min()),
                               float(d[(d.wall == 'wf') & (d.alpha_deg == 0)].Cd_drift.max())],
        tex_drift_negative=f"{int((d[d.wall == 'tex'].Cd_drift < 0).sum())} of {int((d.wall == 'tex').sum())}",
        tex_drift_range=[float(d[d.wall == 'tex'].Cd_drift.min()), float(d[d.wall == 'tex'].Cd_drift.max())],
        wf_a90_a180_absdrift_max=float(d[(d.wall == 'wf') & (d.alpha_deg != 0)].Cd_drift.abs().max()),
        Ks_over_yP_range=[float(rough.Ks_over_yP.min()), float(rough.Ks_over_yP.max())],
        yplus_wf_mean_range=[float(wfall.yplus_blade_mean.min()), float(wfall.yplus_blade_mean.max())],
        yplus_wf_max_range=[float(wfall.yplus_blade_max.min()), float(wfall.yplus_blade_max.max())],
        yplus_tex_mean_range=[float(d[d.wall == 'tex'].yplus_blade_mean.min()),
                              float(d[d.wall == 'tex'].yplus_blade_mean.max())],
        yplus_tex_max=float(d[d.wall == 'tex'].yplus_blade_max.max()),
        ksplus_mean_by_Ks={int(k): [float(g.ksplus_blade_mean.min()), float(g.ksplus_blade_mean.max())]
                           for k, g in rough.groupby("Ks_um")},
        ksplus_max_overall=float(rough.ksplus_blade_max.max()),
        omega_bounded_steps_total=int(d.omega_bounded_steps.sum()),
        Tu_probe_range=[float(d.Tu_upstream_probe_pct.min()), float(d.Tu_upstream_probe_pct.max())],
        cycles_alpha0_wf=[float(d[(d.wall == 'wf') & (d.alpha_deg == 0)].n_cycles_avg.min()),
                          float(d[(d.wall == 'wf') & (d.alpha_deg == 0)].n_cycles_avg.max())],
        cycles_alpha180_wf=[float(d[(d.wall == 'wf') & (d.alpha_deg == 180)].n_cycles_avg.min()),
                            float(d[(d.wall == 'wf') & (d.alpha_deg == 180)].n_cycles_avg.max())],
        cycles_tex_alpha0=[float(d[(d.wall == 'tex') & (d.alpha_deg == 0)].n_cycles_avg.min()),
                           float(d[(d.wall == 'tex') & (d.alpha_deg == 0)].n_cycles_avg.max())],
        St_peak_frac_tex_a180=[float(d[(d.wall == 'tex') & (d.alpha_deg == 180)].St_peak_frac.min()),
                               float(d[(d.wall == 'tex') & (d.alpha_deg == 180)].St_peak_frac.max())],
        timestep_dCd_pct_range=[float(tp.dCd_pct.min()), float(tp.dCd_pct.max())],
        timestep_effect_diff_range=[float(teff.effect_diff.min()), float(teff.effect_diff.max())],
        state_wf_alpha0_Cd=[float(hi_state.Cd.min()), float(hi_state.Cd.max())],
        state_wf_alpha0_Cl=[float(hi_state.Cl.min()), float(hi_state.Cl.max())],
        state_wf_alpha0_St=[float(hi_state.St.min()), float(hi_state.St.max())],
        state_wf_alpha0_Cdstd=[float(hi_state.Cd_std.min()), float(hi_state.Cd_std.max())],
        state_tex_alpha0_Cd=[float(lo_state.Cd.min()), float(lo_state.Cd.max())],
        state_tex_alpha0_Cl=[float(lo_state.Cl.min()), float(lo_state.Cl.max())],
        state_tex_alpha0_St=[float(lo_state.St.min()), float(lo_state.St.max())],
        state_tex_alpha0_Cdstd=[float(lo_state.Cd_std.min()), float(lo_state.Cd_std.max())],
        state_gap_SST_23=float(one(st, case="a000.0_U23.0_SST_wf_Ks0_Tu1.0_Co2.5n2").Cd
                               - one(st, case="a000.0_U23.0_SST_tex0.000_s1_Tu1.0_N80A50").Cd),
        largest_wf_dCd=float(eff.dCd.abs().max()),
        Re_k_upper_23ms={"k 38 um": U_CFD * 38e-6 / NU, "k 84 um": U_CFD * 84e-6 / NU, "k 97 um": U_CFD * 97e-6 / NU},
    )
    q["state_gap_over_largest_wf_dCd"] = q["state_gap_SST_23"] / q["largest_wf_dCd"]

    for name, df in (("wf_effects", eff), ("timestep_pairs", tp), ("timestep_effects", teff), ("trends", tr),
                     ("ksplus_collapse", col_g), ("tex_effects", te), ("tex_sst_minus_lm", tpairs),
                     ("drag_difference", dd), ("ks_mapping", mp), ("measured", mt),
                     ("required_section_change", req), ("alpha0_states", st), ("measured_by_speed", mby),
                     ("tex_D_sst_minus_lm", dsl)):
        df.to_csv(OUT / f"roughness_{name}.csv", index=False, float_format="%.6g")

    figs = [fig_wf_vs_ks(d, eff, "Cd"), fig_wf_vs_ks(d, eff, "Cl"), fig_speed(eff, (col_g, col_fit)),
            fig_ksplus_mapping(eff, mp), fig_texture(te), fig_drag_difference(dd, mt), fig_states(st)]

    nums = dict(col_fit=col_fit, k_end_FS020_vs_Plain_dD_pct=k_end, measured_extra=mextra, lam=LAM, quality=q)
    (OUT / "roughness_numbers.json").write_text(json.dumps(nums, indent=1, default=float))
    print("== quality / ranges"); print(json.dumps(q, indent=1, default=float))
    print("== tex D SST - LM"); print(dsl.round(4).to_string())

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    pd.set_option("display.max_rows", 200)
    print("== wf effects")
    print(eff[["case", "maxCo", "Ks_um", "Cd", "dCd", "dCd_pct", "noise_Cd", "dCd_over_noise", "resolved_Cd",
               "dCd_pressure", "dCd_viscous", "Cl", "dCl", "noise_Cl", "resolved_Cl", "St", "dSt_pct",
               "ksplus_mean", "ksplus_max", "Ks_over_yP", "yplus_mean", "yplus_max"]].round(4).to_string())
    print("== time step pairs");  print(tp.round(4).to_string())
    print("== time step effects"); print(teff.round(4).to_string())
    print("== trends");  print(tr.round(5).to_string())
    print("== Ks+ collapse", col_fit)
    print(col_g[["case", "Ks_um", "U_ms", "maxCo", "ksplus_mean", "dCd_pct"]].round(3).to_string())
    print("== tex effects")
    print(te[["case", "t_mm", "Cd", "Cd_std", "Cd_drift", "dCd", "dCd_pct", "noise_Cd", "dCd_over_noise", "resolved_Cd",
              "dCd_pressure", "dCd_viscous", "Cl", "dCl", "resolved_Cl", "St", "St_peak_frac", "yplus_mean",
              "Re_k_upper_U_t_over_nu"]].round(4).to_string())
    print("== tex SST - LM"); print(tpairs.round(4).to_string())
    print("== drag difference")
    print(dd[["set", "roughness", "Cd0", "Cd180", "D", "noise_own", "dCd0", "dCd180", "dD", "dD_pct", "noise_dD",
              "dD_over_noise", "resolved", "dN_lam", "noise_dN", "dN_sign_lam_0_to_0p25"]].round(4).to_string())
    print("== required section change"); print(req.round(4).to_string())
    print("== mapping"); print(mp.round(3).to_string())
    print("k_end", k_end)
    print("== measured"); print(mt.round(3).to_string()); print(mextra)
    print("== alpha-0 states"); print(st.round(3).to_string())
    for p in figs:
        print("wrote", p)


if __name__ == "__main__":
    main()
