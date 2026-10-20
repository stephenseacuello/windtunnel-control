#!/usr/bin/env python3
"""Stage 2 (roughness on the section) analysis of the 69 cases of 15 Oct 2026.

    nice -n 10 python3 cfd/analysis/2026-10-15/src/roughness_histories.py   # first (reads the case folders)
    nice -n 10 python3 cfd/analysis/2026-10-15/src/roughness_analysis.py

Adapted from cfd/analysis/2026-10-13/src/roughness_analysis.py (same rules, same style). New here:
the 26 re-runs of stage2/queues/S2e_rerun.txt:
  - rough-wall-function sweeps at alpha 90 and 180 at maxCo 2.5 (10), against the maxCo-5 sweeps;
  - resolved texture at maxCo 2.5, 150 c/U averaged over the last 100: SST and LM, alpha 0 and 180,
    t 0 / 0.2 mm, LM also 0.1 (10), against the maxCo-5, 80-c/U runs (last 50 averaged);
  - LM texture at alpha 180 at 18.8, 20.9 and 25.2 m/s, t 0 and 0.2 (6), with 23 m/s.

Reads (read only)
  cfd/stage2/results/stage2_polars.csv          the 69 cases (the 43 of 13 Oct are byte-for-value identical)
  cfd/section2d/results/section_polars.csv      only the medium-mesh maxCo 5 / 2.5 / 1.25 rows at 23 m/s
                                                (context for the time-step question; Stage 1's own analysis
                                                is separate)
  ../out/roughness_histories_runs.csv           from roughness_histories.py (windows, jumps, alpha-0 states)
  cfd/stage2/runs/<case>/postProcessing/forceCoeffs1 (through roughness_histories.forces; the speed figure)
  reports/roughness_2026-09/build/derived/{comparisons,rotor_by_wind_speed,run_summary}.csv, build/numbers.json
Writes
  ../out/roughness_*.csv, ../out/roughness_numbers.json, ../fig/roughness_*.png

Rules (13 Oct, RESULTS.md section 1.3, unchanged):
  noise of a change between runs a and b = |drift_a| + |drift_b| (drift = mean of the second half of the
  averaging window minus the first half); the change is resolved when it exceeds its noise. 'Not resolved'
  bounds a change; it does not show equality.
  Fair comparison: same mesh, model (except SST-LM brackets), maxCo, speed, Tu and averaging window, and at
  alpha 0 the same flow state (high-drag: Cd > 2.5; low-drag: below).
  Health flag (13 Oct): flagged = time-step anomaly (mean dt at least 1.9 times shorter than the median of
  its family) with at least one corruption symptom (Cd < 0, Cd_std > |Cd|, |Cl| > 3, time-mean maximum
  y+ > 2 on a low-Re mesh); jumps (Cd change > 0.5 between samples) are counted as in the 13 Oct addendum.
Provenance: every number written here is computed from the files above; the two-position drag-rotor model,
the literature shell values (cfd/PLAN.md) and the Ks mappings are assumptions named where used.
"""
import itertools
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parents[2]
FIG, OUT = ROOT / "fig", ROOT / "out"
STAGE2_CSV = REPO / "cfd" / "stage2" / "results" / "stage2_polars.csv"
SECTION_CSV = REPO / "cfd" / "section2d" / "results" / "section_polars.csv"
REP = REPO / "reports" / "roughness_2026-09" / "build"

NU = 1.516e-5           # m^2/s (cfd/section2d/README.md section 3)
C_REF = 0.048
LAM = 0.125             # tip-speed ratio of the quasi-steady weighting; measured peak 0.122-0.131
U_CFD = 23.0
KS_SWEEP = [0, 50, 100, 200, 400]
T_SWEEP = [0.0, 0.05, 0.10, 0.20]
U_BRACKET = [18.8, 20.9, 23.0, 25.2]
CD_SHELL_LIT = (2.3, 1.2)   # thin semicircular shell (cfd/PLAN.md; literature, not this blade)
MAC_RUNS = {"a180.0_U23.0_SST_wf_Ks0_Tu1.0"}        # 13 Oct README: the one Stage 2 case finished on the Mac
MIGRATED = {"a180.0_U23.0_SST_wf_Ks50_Tu1.0"}       # moved Mac -> Unity inside its averaging window
DX_MIN = {"wf": 200e-6, "tex": 40e-6}   # smallest wall spacing: wf ds_corner; tex texture wall spacing
                                        # (mesh_info.json); the 13 Oct proxy used Stage 1's ds_corner
DT_ANOMALY = 1.9        # 13 Oct: flagged runs stepped 1.9-9.6 times shorter than their family's median
ROTORS = ["Plain", "FS 0.05", "FS 0.10", "FS 0.20"]
FS_T = {"Plain": 0.0, "FS 0.05": 0.050, "FS 0.10": 0.101, "FS 0.20": 0.202}

# ------------------------------------------------------------------ style (mirrors 13 Oct section_lib.style)
BLACK = "#000000"
INK2 = "#52514e"
MUTED = "#8c8c8c"
BAND1 = "#f2f2f2"
BAND2 = "#e3e3e3"
RAMP = {50: "#86b6ef", 100: "#5598e7", 200: "#256abf", 400: "#184f95"}   # validated ordinal blue ramp
T_COLOR = {0.0: BLACK, 0.05: RAMP[100], 0.10: RAMP[200], 0.20: RAMP[400]}
FS_COLOR = {"Plain": BLACK, "FS 0.05": RAMP[100], "FS 0.10": RAMP[200], "FS 0.20": RAMP[400]}
RIG = "#d9822b"         # rig data (13 Oct encoding: orange)
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


def mk(model, maxco, color, ms=MS):
    """Marker style: shape by model, filled for maxCo 2.5, open for maxCo 5 (13 Oct encoding)."""
    filled = float(maxco) < 5
    return dict(marker=MODEL_MARKER[model], ms=ms, mec=color, mfc=color if filled else "white", mew=1.1, ls="none")


def sgn(x, nd=1, unit=""):
    return f"{x:+.{nd}f}{unit}".replace("-", "−")


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


def change(a, b, q="Cd"):
    """Change b - a of q with the drift-rule noise; a is the reference."""
    dq = b[f"{q}_mean"] - a[f"{q}_mean"]
    n = abs(b[f"{q}_drift"]) + abs(a[f"{q}_drift"])
    return dq, 100 * dq / abs(a[f"{q}_mean"]), n, abs(dq) > n


# ------------------------------------------------------------------ loading
def load():
    d = pd.read_csv(STAGE2_CSV)
    assert len(d) == 69, len(d)
    d["ran_on"] = np.where(d["name"].isin(MAC_RUNS), "mac", "unity")
    d["Co"] = d["maxCo"].astype(float)
    d["t"] = d["tex_t_mm"].astype(float).round(2)
    d["window"] = np.where(d.t_end_conv > 100, "50-150 c/U", "30-80 c/U")
    d["new_15oct"] = d["name"].str.endswith("_Co2.5n2") & (
        ((d.wall == "wf") & d.alpha_deg.isin([90, 180])) | (d.wall == "tex"))
    h = pd.read_csv(OUT / "roughness_histories_runs.csv").set_index("name")
    keep = ["jump_max_win", "jump_bins_win_0.5", "jump_bins_win_0.2", "jump_bins_win_0.1", "noise_end",
            "Cd_30_80", "drift_30_80", "Cl_30_80", "Cd_100_150", "drift_100_150", "Cl_100_150", "end_slope_per100",
            "state_win", "state_30_80", "state_high_share_win", "high_to", "state_end", "Cd_win_nojump"]
    d = d.join(h[keep], on="name")
    s1 = pd.read_csv(SECTION_CSV)
    meas = dict(
        comp=pd.read_csv(REP / "derived" / "comparisons.csv"),
        bys=pd.read_csv(REP / "derived" / "rotor_by_wind_speed.csv"),
        runs=pd.read_csv(REP / "derived" / "run_summary.csv"),
        num=json.loads((REP / "numbers.json").read_text()),
    )
    return d, s1, meas


# ------------------------------------------------------------------ 0. health flag on all 69 runs
def health(d):
    h = d.copy()
    h["neg_drag"] = h.Cd_mean < 0
    h["std_gt_mean"] = h.Cd_std > h.Cd_mean.abs()
    h["cl_gt3"] = h.Cl_mean.abs() > 3
    h["yplus_max"] = h[["yplus_blade_max", "yplus_bladeEnds_max"]].max(axis=1)
    h["yplus_spike"] = (h.wall == "tex") & (h.yplus_max > 2)       # low-Re criterion; wf meshes sit at y+ 17-49
    h["any_symptom"] = h.neg_drag | h.std_gt_mean | h.cl_gt3 | h.yplus_spike
    h["dt_conv"] = h.dt_mean_s * h.U_ms / C_REF
    # family: same mesh and maxCo (wf meshes differ by speed; the tex mesh differs by alpha only)
    h["family"] = np.where(h.wall == "wf",
                           h.wall + " a" + h.alpha_deg.astype(int).astype(str) + " U" + h.U_ms.map("{:g}".format)
                           + " Co" + h.Co.map("{:g}".format),
                           h.wall + " a" + h.alpha_deg.astype(int).astype(str) + " Co" + h.Co.map("{:g}".format))
    h["dt_family_median"] = h.groupby("family").dt_conv.transform("median")
    h["dt_ratio_median_over_run"] = h.dt_family_median / h.dt_conv
    h["dt_anomaly"] = h.dt_ratio_median_over_run >= DT_ANOMALY
    h["u_co_over_U"] = h.Co * h.wall.map(DX_MIN) / (h.dt_mean_s * h.U_ms)
    h["flagged"] = h.dt_anomaly & h.any_symptom
    h["jumps_win"] = h["jump_bins_win_0.5"].astype(int)
    h["status"] = np.where(h.flagged, "flagged", np.where(h.jumps_win > 0, "healthy, with jumps", "healthy"))
    h["comparison_use"] = np.where(
        (h.alpha_deg == 0) & (h.state_win == "mixed"), "excluded: alpha-0 state changes inside the window",
        "usable")
    cols = ["name", "wall", "alpha_deg", "U_ms", "model", "Ks_um", "t", "Co", "ran_on", "new_15oct", "Cd_mean",
            "Cd_std", "Cl_mean", "yplus_max", "neg_drag", "std_gt_mean", "cl_gt3", "yplus_spike", "any_symptom",
            "dt_conv", "family", "dt_family_median", "dt_ratio_median_over_run", "dt_anomaly", "u_co_over_U",
            "jump_max_win", "jumps_win", "jump_bins_win_0.2", "jump_bins_win_0.1", "noise_end", "state_win",
            "flagged", "status", "comparison_use"]
    return h[cols]


# ------------------------------------------------------------------ 1. rough wall functions
def wf_effects(d):
    wf = d[d.wall == "wf"]
    rows = []
    for (a, U, co), g in wf.groupby(["alpha_deg", "U_ms", "Co"]):
        g = g.sort_values("Ks_um")
        ref = g[g.Ks_um == 0]
        note = "Ks 0, same alpha, U, maxCo and mesh"
        if ref.empty:
            ref = g.iloc[[0]]
            note = f"Ks {int(ref.Ks_um.iloc[0])} (Ks 0 and 100 diverged at this maxCo; 13 Oct)"
        r0 = ref.iloc[0]
        for _, r in g.iterrows():
            dCd, pCd, nCd, okCd = change(r0, r, "Cd")
            dCl, pCl, nCl, okCl = change(r0, r, "Cl")
            is_ref = r["name"] == r0["name"]
            rows.append(dict(
                case=r["name"], reference=r0["name"], reference_rule=note, alpha_deg=a, U_ms=U, maxCo=co,
                Ks_um=r.Ks_um, Cd=r.Cd_mean, Cd_std=r.Cd_std, Cd_drift=r.Cd_drift, dCd=dCd, dCd_pct=pCd,
                noise_Cd=nCd, noise_Cd_pct=100 * nCd / r0.Cd_mean, dCd_over_noise=abs(dCd) / nCd if nCd > 0 else np.nan,
                resolved_Cd="n/a" if is_ref else ("yes" if okCd else "no"),
                dCd_pressure=r.Cd_pressure_mean - r0.Cd_pressure_mean, dCd_viscous=r.Cd_viscous_mean - r0.Cd_viscous_mean,
                Cd_viscous=r.Cd_viscous_mean, Cl=r.Cl_mean, Cl_drift=r.Cl_drift, dCl=dCl, dCl_pct=pCl, noise_Cl=nCl,
                resolved_Cl="n/a" if is_ref else ("yes" if okCl else "no"), St=r.St, St_peak_frac=r.St_peak_frac,
                dSt_pct=100 * (r.St - r0.St) / r0.St, ksplus_mean=r.ksplus_blade_mean, ksplus_max=r.ksplus_blade_max,
                Ks_over_yP=r.Ks_over_yP, yplus_mean=r.yplus_blade_mean, ran_on=r.ran_on, ref_ran_on=r0.ran_on))
    return pd.DataFrame(rows)


def timestep_pairs(d):
    """maxCo 5 against 2.5 for every wall-function case run at both, and the roughness effect at both."""
    wf = d[d.wall == "wf"]
    rows, effects = [], []
    for (a, U, ks), g in wf.groupby(["alpha_deg", "U_ms", "Ks_um"]):
        if {5.0, 2.5} <= set(g.Co):
            c5, c25 = one(g, Co=5.0), one(g, Co=2.5)
            dCd, pCd, n, ok = change(c25, c5, "Cd")
            dCl, pCl, nCl, okCl = change(c25, c5, "Cl")
            rows.append(dict(alpha_deg=a, U_ms=U, Ks_um=ks, case_Co5=c5["name"], case_Co2_5=c25["name"],
                             ran_on_Co5=c5.ran_on, Cd_Co5=c5.Cd_mean, Cd_Co2_5=c25.Cd_mean, dCd=dCd, dCd_pct=pCd,
                             noise_Cd=n, resolved="yes" if ok else "no", Cl_Co5=c5.Cl_mean, Cl_Co2_5=c25.Cl_mean,
                             dCl=dCl, dCl_pct=pCl, noise_Cl=nCl, resolved_Cl="yes" if okCl else "no",
                             dSt_pct=100 * (c5.St - c25.St) / c25.St,
                             jump_max_Co5=c5.jump_max_win, jump_max_Co2_5=c25.jump_max_win))
    tp = pd.DataFrame(rows)
    for (a, U), g in tp.groupby(["alpha_deg", "U_ms"]):
        g = g.sort_values("Ks_um")
        r0 = g.iloc[0]
        for _, r in g.iloc[1:].iterrows():
            c = {}
            for co, key in ((5.0, "Co5"), (2.5, "Co2_5")):
                x = one(wf, alpha_deg=a, U_ms=U, Ks_um=r.Ks_um, Co=co)
                x0 = one(wf, alpha_deg=a, U_ms=U, Ks_um=r0.Ks_um, Co=co)
                c[key] = (x.Cd_mean - x0.Cd_mean, 100 * (x.Cd_mean - x0.Cd_mean) / x0.Cd_mean,
                          abs(x.Cd_drift) + abs(x0.Cd_drift), x.Cl_mean - x0.Cl_mean,
                          100 * (x.Cl_mean - x0.Cl_mean) / abs(x0.Cl_mean), abs(x.Cl_drift) + abs(x0.Cl_drift))
            e5, e25 = c["Co5"], c["Co2_5"]
            nd = e5[2] + e25[2]
            ndl = e5[5] + e25[5]
            effects.append(dict(alpha_deg=a, U_ms=U, Ks_um=r.Ks_um, reference_Ks_um=r0.Ks_um,
                                effect_Co5=e5[0], effect_Co2_5=e25[0], effect_pct_Co5=e5[1], effect_pct_Co2_5=e25[1],
                                noise_Co5=e5[2], noise_Co2_5=e25[2],
                                resolved_Co5="yes" if abs(e5[0]) > e5[2] else "no",
                                resolved_Co2_5="yes" if abs(e25[0]) > e25[2] else "no",
                                effect_diff=e5[0] - e25[0], effect_diff_pp=e5[1] - e25[1], noise_effect_diff=nd,
                                effect_diff_resolved="yes" if abs(e5[0] - e25[0]) > nd else "no",
                                effect_ratio_Co2_5_over_Co5=e25[0] / e5[0] if e5[0] != 0 else np.nan,
                                Cl_effect_Co5=e5[3], Cl_effect_Co2_5=e25[3], Cl_effect_pct_Co5=e5[4],
                                Cl_effect_pct_Co2_5=e25[4], Cl_effect_diff=e5[3] - e25[3], Cl_noise_effect_diff=ndl,
                                Cl_effect_diff_resolved="yes" if abs(e5[3] - e25[3]) > ndl else "no"))
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


# ------------------------------------------------------------------ 2. drag difference D (fair pairs)
def drag_difference(d):
    """D = Cd(0) - Cd(180) at 23 m/s for each set; changes against the set's smooth (or smallest-roughness)
    member. Fair sets have both angles at one maxCo and window and the alpha-0 member in one state."""
    w0, w1 = (1 - LAM) ** 2, (1 + LAM) ** 2
    wf = d[(d.wall == "wf") & (d.U_ms == U_CFD)]
    tx = d[(d.wall == "tex") & (d.U_ms == U_CFD)]
    sets = [
        ("wf, both angles maxCo 2.5", "SST", "fair",
         [(k, one(wf, alpha_deg=0, Co=2.5, Ks_um=k), one(wf, alpha_deg=180, Co=2.5, Ks_um=k)) for k in KS_SWEEP]),
        ("wf, both angles maxCo 5", "SST", "fair",
         [(k, one(wf, alpha_deg=0, Co=5.0, Ks_um=k), one(wf, alpha_deg=180, Co=5.0, Ks_um=k)) for k in (50, 200, 400)]),
        ("wf, alpha 0 maxCo 2.5 with alpha 180 maxCo 5 (13 Oct set)", "SST", "mixed maxCo (13 Oct)",
         [(k, one(wf, alpha_deg=0, Co=2.5, Ks_um=k), one(wf, alpha_deg=180, Co=5.0, Ks_um=k)) for k in KS_SWEEP]),
    ]
    for m in ("SST", "LM"):
        sets.append((f"tex {m}, maxCo 5, 80 c/U", m, "fair",
                     [(t, one(tx, alpha_deg=0, model=m, t=t, Co=5.0), one(tx, alpha_deg=180, model=m, t=t, Co=5.0))
                      for t in T_SWEEP]))
    sets.append(("tex SST, maxCo 2.5, 150 c/U", "SST", "fair",
                 [(t, one(tx, alpha_deg=0, model="SST", t=t, Co=2.5), one(tx, alpha_deg=180, model="SST", t=t, Co=2.5))
                  for t in (0.0, 0.2)]))
    sets.append(("tex LM, maxCo 2.5, 150 c/U", "LM", "no same-state t 0 reference",
                 [(t, one(tx, alpha_deg=0, model="LM", t=t, Co=2.5), one(tx, alpha_deg=180, model="LM", t=t, Co=2.5))
                  for t in (0.0, 0.1, 0.2)]))
    rows = []
    for name, model, fair, members in sets:
        x0, a0, b0 = members[0]
        D0 = a0.Cd_mean - b0.Cd_mean
        n0 = abs(a0.Cd_drift) + abs(b0.Cd_drift)
        for x, a, b in members:
            D = a.Cd_mean - b.Cd_mean
            n_own = abs(a.Cd_drift) + abs(b.Cd_drift)
            dD = D - D0
            d0, d180 = a.Cd_mean - a0.Cd_mean, b.Cd_mean - b0.Cd_mean
            same_state = (a.state_win == a0.state_win) and a.state_win != "mixed"
            ok = fair == "fair" and same_state
            first = x == x0
            lam = np.linspace(0, 0.25, 26)
            dN_lam = d0 * (1 - lam) ** 2 - d180 * (1 + lam) ** 2
            rows.append(dict(
                set=name, model=model, set_fairness=fair, roughness=x,
                roughness_unit="Ks um" if name.startswith("wf") else "t mm",
                case_alpha0=a["name"], case_alpha180=b["name"], state_alpha0=a.state_win, Cd0=a.Cd_mean,
                Cd180=b.Cd_mean, D=D, noise_own=n_own, reference_roughness=x0, dCd0=d0, dCd180=d180, dD=dD,
                dD_pct=100 * dD / D0, noise_dD=n_own + n0, dD_over_noise=abs(dD) / (n_own + n0),
                comparison_fair="yes" if ok else "no",
                resolved="n/a" if first else (("yes" if abs(dD) > n_own + n0 else "no") if ok else "not fair"),
                dN_lam=d0 * w0 - d180 * w1,
                noise_dN=(abs(a.Cd_drift) + abs(a0.Cd_drift)) * w0 + (abs(b.Cd_drift) + abs(b0.Cd_drift)) * w1,
                dN_sign_lam_0_to_0p25=("n/a" if first else
                                       ("+" if (dN_lam > 0).all() else "-" if (dN_lam < 0).all() else "mixed"))))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ 3. resolved texture
def tex_effects(d):
    """Texture change against t 0 of the same alpha, model, maxCo, speed (and window). Also on the other
    windows from the histories: 30-80 c/U (both maxCo) and 100-150 c/U (maxCo 2.5)."""
    tx = d[d.wall == "tex"]
    rows = []
    for (a, m, co, U), g in tx.groupby(["alpha_deg", "model", "Co", "U_ms"]):
        r0 = one(g, t=0.0)
        for _, r in g.sort_values("t").iterrows():
            dCd, pCd, n, ok = change(r0, r, "Cd")
            dCl, pCl, nCl, okCl = change(r0, r, "Cl")
            same_state = a != 0 or (r.state_win == r0.state_win and r.state_win != "mixed")
            ref = r["name"] == r0["name"]
            row = dict(case=r["name"], reference=r0["name"], alpha_deg=a, model=m, maxCo=co, U_ms=U, t_mm=r.t,
                       window=r.window, Cd=r.Cd_mean, Cd_std=r.Cd_std, Cd_drift=r.Cd_drift, dCd=dCd, dCd_pct=pCd,
                       noise_Cd=n, noise_Cd_pct=100 * n / r0.Cd_mean, dCd_over_noise=abs(dCd) / n,
                       comparison_fair="yes" if same_state else "no (alpha-0 state of t 0 changes in its window)",
                       resolved_Cd="n/a" if ref else (("yes" if ok else "no") if same_state else "not fair"),
                       dCd_pressure=r.Cd_pressure_mean - r0.Cd_pressure_mean,
                       dCd_viscous=r.Cd_viscous_mean - r0.Cd_viscous_mean, Cd_viscous=r.Cd_viscous_mean,
                       Cl=r.Cl_mean, dCl=dCl, noise_Cl=nCl,
                       resolved_Cl="n/a" if ref else (("yes" if okCl else "no") if same_state else "not fair"),
                       St=r.St, St_peak_frac=r.St_peak_frac, n_cycles_avg=r.n_cycles_avg, state_alpha0=r.state_win,
                       yplus_max=r.yplus_blade_max, Re_k_upper=U * r.t * 1e-3 / NU, end_slope_per100=r.end_slope_per100)
            # alternative windows (histories): 30-80 for every run, 100-150 for the 150-c/U runs
            for lab in ("30_80", "100_150"):
                x, x0 = r[f"Cd_{lab}"], r0[f"Cd_{lab}"]
                nx = abs(r[f"drift_{lab}"]) + abs(r0[f"drift_{lab}"])
                st = "state_30_80" if lab == "30_80" else "state_win"
                same_w = a != 0 or (r[st] == r0[st] and r[st] != "mixed")
                row[f"dCd_{lab}"] = x - x0
                row[f"dCd_pct_{lab}"] = 100 * (x - x0) / x0 if np.isfinite(x0) else np.nan
                row[f"noise_{lab}"] = nx
                row[f"resolved_{lab}"] = ("n/a" if ref or not np.isfinite(x) else
                                          (("yes" if abs(x - x0) > nx else "no") if same_w else "not fair"))
            rows.append(row)
    return pd.DataFrame(rows)


def tex_timestep(d):
    """maxCo 5 (80 c/U, 30-80 window) against maxCo 2.5 (150 c/U) for the same texture case: on the same 30-80
    window (time-step effect alone) and on each run's own window (time step and window together)."""
    tx = d[(d.wall == "tex") & (d.U_ms == U_CFD)]
    rows = []
    for (a, m, t), g in tx.groupby(["alpha_deg", "model", "t"]):
        if {5.0, 2.5} <= set(g.Co):
            c5, c25 = one(g, Co=5.0), one(g, Co=2.5)
            same = c25.Cd_30_80 - c5.Cd_mean
            n_same = abs(c25.drift_30_80) + abs(c5.Cd_drift)
            own = c25.Cd_mean - c5.Cd_mean
            n_own = abs(c25.Cd_drift) + abs(c5.Cd_drift)
            fair_same = a != 0 or (c25.state_30_80 == c5.state_30_80 and c5.state_30_80 != "mixed")
            fair_own = a != 0 or (c25.state_win == c5.state_win and c5.state_win != "mixed")
            rows.append(dict(alpha_deg=a, model=m, t_mm=t, case_Co5=c5["name"], case_Co2_5=c25["name"],
                             Cd_Co5_30_80=c5.Cd_mean, Cd_Co2_5_30_80=c25.Cd_30_80, Cd_Co2_5_50_150=c25.Cd_mean,
                             Cd_Co2_5_100_150=c25.Cd_100_150,
                             d_same_window=same, d_same_window_pct=100 * same / c5.Cd_mean, noise_same=n_same,
                             state_30_80_Co5=c5.state_30_80, state_30_80_Co2_5=c25.state_30_80,
                             resolved_same=("yes" if abs(same) > n_same else "no") if fair_same else "not fair",
                             d_own_windows=own, d_own_windows_pct=100 * own / c5.Cd_mean, noise_own=n_own,
                             resolved_own=("yes" if abs(own) > n_own else "no") if fair_own else "not fair",
                             Cl_Co5=c5.Cl_mean, Cl_Co2_5=c25.Cl_mean, St_peak_frac_Co5=c5.St_peak_frac,
                             St_peak_frac_Co2_5=c25.St_peak_frac, state_Co5=c5.state_win, state_Co2_5=c25.state_win,
                             end_slope_Co5=c5.end_slope_per100, end_slope_Co2_5=c25.end_slope_per100))
    return pd.DataFrame(rows)


def sst_minus_lm(d):
    tx = d[d.wall == "tex"]
    rows = []
    for (a, t, co, U), g in tx.groupby(["alpha_deg", "t", "Co", "U_ms"]):
        if set(g.model) >= {"SST", "LM"}:
            s, l = one(g, model="SST"), one(g, model="LM")
            dd, pct, n, ok = change(l, s, "Cd")
            fair = a != 0 or (s.state_win == l.state_win and l.state_win != "mixed")
            rows.append(dict(alpha_deg=a, t_mm=t, maxCo=co, U_ms=U, case_SST=s["name"], case_LM=l["name"],
                             Cd_SST=s.Cd_mean, Cd_LM=l.Cd_mean, dCd_SST_minus_LM=dd, pct_of_LM=pct, noise=n,
                             comparison_fair="yes" if fair else "no (alpha-0 states differ)",
                             resolved=("yes" if ok else "no") if fair else "not fair",
                             Cl_SST=s.Cl_mean, Cl_LM=l.Cl_mean, St_peak_frac_SST=s.St_peak_frac,
                             St_peak_frac_LM=l.St_peak_frac))
    pr = pd.DataFrame(rows)
    # D(SST) - D(LM) where both angles exist on the same mesh, maxCo and window
    dl = []
    for (t, co), g in pr.groupby(["t_mm", "maxCo"]):
        if set(g.alpha_deg) >= {0, 180}:
            r0, r1 = one(g, alpha_deg=0), one(g, alpha_deg=180)
            Ds, Dl = r0.Cd_SST - r1.Cd_SST, r0.Cd_LM - r1.Cd_LM
            n = r0.noise + r1.noise
            fair = r0.comparison_fair == "yes"
            dl.append(dict(t_mm=t, maxCo=co, D_SST=Ds, D_LM=Dl, D_SST_minus_LM=Ds - Dl, pct_of_LM=100 * (Ds - Dl) / Dl,
                           noise=n, comparison_fair="yes" if fair else "no (alpha-0 states differ)",
                           resolved=("yes" if abs(Ds - Dl) > n else "no") if fair else "not fair"))
    return pr, pd.DataFrame(dl)


# ------------------------------------------------------------------ 4. LM texture against speed (alpha 180)
def lm_speed(d, meas):
    tx = d[(d.wall == "tex") & (d.alpha_deg == 180) & (d.model == "LM") & (d.Co == 2.5)]
    bys = meas["bys"]
    rows = []
    for U in U_BRACKET:
        r0, r1 = one(tx, U_ms=U, t=0.0), one(tx, U_ms=U, t=0.2)
        dCd, pCd, n, ok = change(r0, r1, "Cd")
        dCl, pCl, nCl, okCl = change(r0, r1, "Cl")
        l0, l1 = r0.Cd_100_150, r1.Cd_100_150
        nl = abs(r0.drift_100_150) + abs(r1.drift_100_150)
        v = bys.wind_mps.iloc[(bys.wind_mps - U).abs().argmin()]
        at = bys[np.isclose(bys.wind_mps, v)].set_index("rotor")
        row = dict(U_ms=U, Re_c=U * C_REF / NU, Re_k_t0p2_upper=U * 0.2e-3 / NU, case_t0=r0["name"],
                   case_t0p2=r1["name"], Cd_t0=r0.Cd_mean, Cd_t0p2=r1.Cd_mean, drift_t0=r0.Cd_drift,
                   drift_t0p2=r1.Cd_drift, dCd=dCd, dCd_pct=pCd, noise=n, noise_pct=100 * n / r0.Cd_mean,
                   dCd_over_noise=abs(dCd) / n, resolved="yes" if ok else "no",
                   Cd_t0_100_150=l0, Cd_t0p2_100_150=l1, dCd_100_150=l1 - l0, dCd_pct_100_150=100 * (l1 - l0) / l0,
                   noise_100_150=nl, resolved_100_150="yes" if abs(l1 - l0) > nl else "no",
                   Cl_t0=r0.Cl_mean, Cl_t0p2=r1.Cl_mean, dCl=dCl, noise_Cl=nCl, resolved_Cl="yes" if okCl else "no",
                   dCd_pressure=r1.Cd_pressure_mean - r0.Cd_pressure_mean,
                   dCd_viscous=r1.Cd_viscous_mean - r0.Cd_viscous_mean,
                   St_t0=r0.St, St_t0p2=r1.St, noise_end_t0=r0.noise_end, noise_end_t0p2=r1.noise_end,
                   rig_wind_mps=v)
        for rot in ROTORS[1:]:
            row[f"rig_{rot}_change_pct"] = at.loc[rot, "p_max_change_vs_plain_pct"]
            row[f"rig_{rot}_pw95_pct"] = at.loc[rot, "pointwise95_halfwidth_pct"]
        rows.append(row)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ 5. measured gains, required change
def measured(meas):
    comp = meas["comp"]
    c = comp[comp.relative_to == "Plain"].set_index("rotor")
    rows = []
    bys = meas["bys"]
    v23 = bys.wind_mps.iloc[(bys.wind_mps - U_CFD).abs().argmin()]
    at = bys[np.isclose(bys.wind_mps, v23)].set_index("rotor")
    for rot in ROTORS[1:]:
        rows.append(dict(rotor=rot, t_mm=FS_T[rot], change_pct=c.loc[rot, "change_pct"],
                         tukey95_lo_pct=c.loc[rot, "tukey95_lo_pct"], tukey95_hi_pct=c.loc[rot, "tukey95_hi_pct"],
                         wind_mps_near_23=v23, change_at_23_pct=at.loc[rot, "p_max_change_vs_plain_pct"],
                         pointwise95_halfwidth_at_23_pct=at.loc[rot, "pointwise95_halfwidth_pct"]))
    num = meas["num"]
    extra = dict(stepV={r: num[k] for r, k in (("Plain", "stepVP"), ("FS 0.05", "stepVA"), ("FS 0.10", "stepVB"),
                                                ("FS 0.20", "stepVC"))},
                 steepest_rise_by_run=meas["runs"][["rotor", "run", "steepest_rise_mps"]].to_dict("records"))
    return pd.DataFrame(rows), extra


def required_change(d, mt):
    """Section-drag change that each measured gain needs in the two-position model (inferred, assumed model)."""
    wf = d[(d.wall == "wf") & (d.U_ms == U_CFD) & (d.Co == 2.5)]
    refs = {"literature shells": CD_SHELL_LIT,
            "CFD wf Ks 0, both angles maxCo 2.5": (one(wf, alpha_deg=0, Ks_um=0).Cd_mean,
                                                    one(wf, alpha_deg=180, Ks_um=0).Cd_mean)}
    mti = mt.set_index("rotor")
    rows = []
    w0, w1 = (1 - LAM) ** 2, (1 + LAM) ** 2
    for lab, (c0, c1) in refs.items():
        N = c0 * w0 - c1 * w1
        for rot, g in (("FS 0.10", mti.loc["FS 0.10", "change_pct"]), ("FS 0.20", mti.loc["FS 0.20", "change_pct"]),
                       ("FS 0.10 at 23 m/s", mti.loc["FS 0.10", "change_at_23_pct"]),
                       ("FS 0.20 at 23 m/s", mti.loc["FS 0.20", "change_at_23_pct"])):
            dN = g / 100 * N
            rows.append(dict(reference=lab, Cd0=c0, Cd180=c1, lam=LAM, N=N, measured=rot, gain_pct=g,
                             dCd0_alone_pct=100 * dN / w0 / c0, dCd180_alone_pct=-100 * dN / w1 / c1,
                             dD_alone_pct_if_Cd0=100 * (dN / w0) / (c0 - c1)))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ 6. bottom line: every fair comparison
def bottom_line(eff, dd, te):
    rows = []

    def add(family, config, quantity, need, dq, ref, noise, case, reference, fair=True):
        rows.append(dict(family=family, config=config, quantity=quantity, needed_sign=need, change=dq,
                         change_pct=100 * dq / abs(ref), noise=noise, noise_pct=100 * noise / abs(ref),
                         ratio=abs(dq) / noise if noise > 0 else np.nan, resolved="yes" if abs(dq) > noise else "no",
                         sign_as_needed="yes" if np.sign(dq) == (1 if need == "+" else -1) else "no",
                         case=case, reference=reference))

    for _, r in eff[(eff.resolved_Cd != "n/a") & eff.alpha_deg.isin([0, 180])].iterrows():
        q = "Cd(180)" if r.alpha_deg == 180 else "Cd(0)"
        add("rough wall function (SST)", f"alpha {int(r.alpha_deg)}, {r.U_ms:g} m/s, maxCo {r.maxCo:g}, "
            f"Ks {int(r.Ks_um)} vs {r.reference.split('_Ks')[1].split('_')[0]}", q, "-" if r.alpha_deg == 180 else "+",
            r.dCd, r.Cd - r.dCd, r.noise_Cd, r.case, r.reference)
    for _, r in dd[(dd.resolved != "n/a") & (dd.comparison_fair == "yes")].iterrows():
        unit = "Ks" if r.roughness_unit.startswith("Ks") else "t"
        add("rough wall function (SST)" if r.set.startswith("wf") else f"resolved texture ({r.model})",
            f"{r.set}, {unit} {r.roughness:g} vs {r.reference_roughness:g}", "D", "+", r.dD, r.D - r.dD, r.noise_dD,
            r.case_alpha0 + " / " + r.case_alpha180, "")
    for _, r in te[(te.resolved_Cd.isin(["yes", "no"]))].iterrows():
        q = "Cd(180)" if r.alpha_deg == 180 else "Cd(0)"
        add(f"resolved texture ({r.model})", f"alpha {int(r.alpha_deg)}, {r.U_ms:g} m/s, maxCo {r.maxCo:g}, "
            f"{r.window}, t {r.t_mm:g} vs 0", q, "-" if r.alpha_deg == 180 else "+", r.dCd, r.Cd - r.dCd, r.noise_Cd,
            r.case, r.reference)
    return pd.DataFrame(rows)


# ================================================================== figures
def save(fig, name):
    p = FIG / f"{name}.png"
    fig.savefig(p, dpi=200, facecolor="white")
    plt.close(fig)
    return p


def handles(items):
    return [Line2D([], [], **kw) for kw in items]


def fig_timestep_sweeps(d, eff):
    """Cd and Cl against Ks at alpha 90 and 180, maxCo 5 (open) and 2.5 (filled), 23 m/s."""
    wf = d[(d.wall == "wf") & (d.U_ms == U_CFD)]
    fig, axes = plt.subplots(4, 1, figsize=(3.6, 8.4), sharex=True, constrained_layout=True)
    spec = [(90, "Cd", "a", "α = 90° (edge-on): $C_d$"), (180, "Cd", "b", "α = 180° (convex side): $C_d$"),
            (90, "Cl", "c", "α = 90°: $C_l$"), (180, "Cl", "d", "α = 180°: $C_l$")]
    for ax, (a, q, lab, title) in zip(axes, spec):
        g = wf[wf.alpha_deg == a]
        txt = []
        for co, dx in ((5.0, 7), (2.5, -7)):
            s = g[g.Co == co].sort_values("Ks_um")
            x = s.Ks_um.to_numpy() + dx
            ax.plot(x, s[f"{q}_mean"], ls=MODEL_LS["SST"], color=INK2 if co == 2.5 else MUTED, lw=0.9, zorder=2)
            ax.errorbar(x, s[f"{q}_mean"], yerr=s[f"{q}_drift"].abs(), fmt="none", ecolor=MUTED, elinewidth=0.8,
                        capsize=1.8, zorder=3)
            for xi, (_, r) in zip(x, s.iterrows()):
                ax.plot(xi, r[f"{q}_mean"], zorder=4, **mk("SST", co, ks_color(r.Ks_um)))
            e = one(eff, alpha_deg=a, U_ms=U_CFD, maxCo=co, Ks_um=400)
            if q == "Cl" and e.Cl < 0:
                pc = 100 * (abs(e.Cl) - abs(e.Cl - e.dCl)) / abs(e.Cl - e.dCl)
                txt.append(f"maxCo {co:g}: |$C_l$| {sgn(pc, 1, ' %')}")
            else:
                txt.append(f"maxCo {co:g}: {sgn(e[f'd{q}_pct'], 1, ' %')}")
        ax.text(0.03, 0.95, "400 µm vs smooth: " + "; ".join(txt), transform=ax.transAxes,
                fontsize=6.4, ha="left", va="top", color=BLACK,
                bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none", alpha=0.85))
        ax.set_title(f"({lab}) {title}", loc="left")
        ax.set_ylabel(f"$C_{{{q[1]}}}$ (–)")
        ax.margins(y=0.2)
    axes[-1].set_xlabel("Sand-grain roughness $K_s$ (µm)")
    axes[-1].set_xticks(KS_SWEEP)
    axes[-1].set_xlim(-25, 425)
    h = handles([dict(marker="s", ls="none", mfc=INK2, mec=INK2, ms=MS, label="maxCo 2.5 (offset −7 µm)"),
                 dict(marker="s", ls="none", mfc="white", mec=INK2, mew=1.1, ms=MS, label="maxCo 5 (offset +7 µm)"),
                 dict(color=MUTED, lw=0.8, marker="|", ms=6, label="±|drift|")])
    fig.legend(handles=h, loc="outside lower center", ncol=3, fontsize=6.2, handletextpad=0.3, columnspacing=0.9)
    fig.suptitle("kOmegaSST + rough wall function, 23 m/s, 150 c/U (last 100 averaged);\n"
                 "colour = $K_s$ (black: smooth); same mesh at both maxCo", fontsize=6.6, x=0.02, ha="left", color=INK2)
    return save(fig, "roughness_timestep_sweeps")


def fig_drag_difference(dd, mt):
    fig, axes = plt.subplots(3, 1, figsize=(3.6, 7.9), constrained_layout=True,
                             gridspec_kw=dict(height_ratios=[1.05, 1.05, 0.9]))
    ax, bx, cx = axes
    # (a) wall functions, fair sets only
    for lo, hi in ((36, 40), (84, 97)):
        ax.axvspan(lo, hi, color=BAND2, lw=0, zorder=0)
    for setname, co, dx in (("wf, both angles maxCo 2.5", 2.5, 0), ("wf, both angles maxCo 5", 5.0, 9)):
        s = dd[dd.set == setname].sort_values("roughness")
        x = s.roughness.to_numpy() + dx
        ax.plot(x, s.D, ls=MODEL_LS["SST"], color=INK2 if co == 2.5 else MUTED, lw=1.0, zorder=2)
        ax.errorbar(x, s.D, yerr=s.noise_own, fmt="none", ecolor=MUTED, elinewidth=0.8, capsize=2, zorder=3)
        for xi, (_, r) in zip(x, s.iterrows()):
            ax.plot(xi, r.D, zorder=4, **mk("SST", co, ks_color(r.roughness)))
            if r.resolved == "yes":
                ax.annotate(sgn(r.dD_pct, 1, " %"), (xi, r.D), xytext=(-7, -2) if co == 2.5 else (6, 6),
                            textcoords="offset points", ha="right" if co == 2.5 else "left",
                            va="top" if co == 2.5 else "bottom", fontsize=6.4, color=BLACK if co == 2.5 else INK2)
    ax.text(41, 1.145, "← Plain, FS 0.05, FS 0.10 (k ≈ 38 µm)", fontsize=5.8, color=INK2, ha="left")
    ax.text(99, 1.205, "← FS 0.20 (k 84–97 µm)", fontsize=5.8, color=INK2, ha="left")
    ax.set_xticks(KS_SWEEP)
    ax.set_xlim(-20, 450)
    ax.set_ylim(1.10, 1.62)
    ax.set_xlabel("Sand-grain roughness $K_s$ (µm)")
    ax.set_ylabel("D = $C_d$(0°) − $C_d$(180°) (–)")
    ax.set_title("(a) Rough wall function, SST, 23 m/s; α 0 in the high-drag state", loc="left")
    h = handles([dict(marker="s", ls="none", mfc=INK2, mec=INK2, ms=MS, label="both angles maxCo 2.5"),
                 dict(marker="s", ls="none", mfc="white", mec=INK2, mew=1.1, ms=MS,
                      label="both angles maxCo 5 (vs $K_s$ 50)"),
                 dict(color=MUTED, lw=0.8, marker="|", ms=6, label="±(|drift| 0° + |drift| 180°)")])
    ax.legend(handles=h, loc="upper right", ncol=1, handletextpad=0.3)
    # (b) texture
    for setname, m, co, dx in (("tex SST, maxCo 5, 80 c/U", "SST", 5.0, -0.004), ("tex LM, maxCo 5, 80 c/U", "LM", 5.0, 0.004),
                               ("tex SST, maxCo 2.5, 150 c/U", "SST", 2.5, -0.004),
                               ("tex LM, maxCo 2.5, 150 c/U", "LM", 2.5, 0.004)):
        s = dd[(dd.set == setname)].sort_values("roughness")
        s = s[s.state_alpha0 != "mixed"]
        x = s.roughness.to_numpy() + dx
        bx.plot(x, s.D, ls=MODEL_LS[m], color=INK2 if co == 2.5 else MUTED, lw=1.0, zorder=2)
        bx.errorbar(x, s.D, yerr=s.noise_own, fmt="none", ecolor=MUTED, elinewidth=0.8, capsize=2, zorder=3)
        for xi, (_, r) in zip(x, s.iterrows()):
            bx.plot(xi, r.D, zorder=4, **mk(m, co, T_COLOR[round(r.roughness, 2)]))
            if r.resolved == "yes":
                # reviewer, 19 Oct: two lines and a leader line; the one-line label ran left to the LM maxCo-2.5
                # t-0.10 marker and read as its label
                bx.annotate(sgn(r.dD_pct, 1, " %") + f"\n({m}, maxCo {co:g})", (xi, r.D), xytext=(-7, -11),
                            textcoords="offset points", ha="right", va="top", fontsize=6.2,
                            arrowprops=dict(arrowstyle="-", lw=0.5, color=INK2, shrinkA=0, shrinkB=2))
    lm0 = one(dd, set="tex LM, maxCo 2.5, 150 c/U", roughness=0.0)
    bx.text(0.222, 0.46, f"LM, maxCo 2.5, t 0: D = {lm0.D:.2f}, off scale;\nits α-0 run changes state "
            "in the window\n(not comparable)", fontsize=5.8, color=INK2, ha="right", va="bottom")
    bx.set_xticks(T_SWEEP)
    bx.set_xlim(-0.015, 0.225)
    bx.set_ylim(0.45, 0.98)
    bx.set_ylabel("D = $C_d$(0°) − $C_d$(180°) (–)")
    bx.set_xlabel("Texture amplitude t (mm)")
    bx.set_title("(b) Resolved texture, 23 m/s; α 0 in the low-drag state", loc="left")
    h = handles([dict(marker="s", ls=MODEL_LS["SST"], color=INK2, mfc=INK2, mec=INK2, ms=MS, label="SST, maxCo 2.5"),
                 dict(marker="o", ls=MODEL_LS["LM"], color=INK2, mfc=INK2, mec=INK2, ms=MS, label="LM, maxCo 2.5"),
                 dict(marker="s", ls=MODEL_LS["SST"], color=MUTED, mfc="white", mec=INK2, mew=1.1, ms=MS,
                      label="SST, maxCo 5"),
                 dict(marker="o", ls=MODEL_LS["LM"], color=MUTED, mfc="white", mec=INK2, mew=1.1, ms=MS,
                      label="LM, maxCo 5")])
    bx.legend(handles=h, loc="upper right", ncol=2, handletextpad=0.3, columnspacing=0.8)
    # (c) measured (unchanged from 13 Oct)
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
    cx.set_xlim(-0.015, 0.225)
    cx.set_xlabel("Fuzzy-skin thickness (mm)")
    cx.set_ylabel(r"$P_{max}$ change vs Plain (%)")
    cx.set_title("(c) Measured, wind tunnel, 1 Oct 2026", loc="left")
    h = handles([dict(marker="D", ls="none", mfc=INK2, mec=INK2, ms=MS, label="mean over 10.2–38 m/s, Tukey 95 %"),
                 dict(marker="D", ls="none", mfc="white", mec=INK2, mew=1.1, ms=MS, label="at 23.0 m/s, pointwise 95 %")])
    cx.legend(handles=h, loc="upper left", ncol=1, handletextpad=0.3)
    cx.set_ylim(-5, 45)
    return save(fig, "roughness_drag_difference")


def fig_texture_windows(d, te):
    """Cd against t at alpha 0 and 180: maxCo 5 / 80 c/U (open) and maxCo 2.5 / 150 c/U (filled)."""
    tx = d[(d.wall == "tex") & (d.U_ms == U_CFD)]
    fig, axes = plt.subplots(2, 1, figsize=(3.6, 5.6), sharex=True, constrained_layout=True)
    for ax, a, lab, title, ylim in ((axes[0], 0, "a", "α = 0° (concave side), low-drag state", (1.60, 1.98)),
                                    (axes[1], 180, "b", "α = 180° (convex side)", (0.86, 1.30))):
        for m, co, dx in (("SST", 5.0, -0.006), ("LM", 5.0, -0.002), ("SST", 2.5, 0.002), ("LM", 2.5, 0.006)):
            s = tx[(tx.alpha_deg == a) & (tx.model == m) & (tx.Co == co)].sort_values("t")
            s = s[s.state_win != "mixed"] if a == 0 else s
            x = s.t.to_numpy() + dx
            ax.plot(x, s.Cd_mean, ls=MODEL_LS[m], color=INK2 if co == 2.5 else MUTED, lw=1.0, zorder=2)
            ax.errorbar(x, s.Cd_mean, yerr=s.Cd_drift.abs(), fmt="none", ecolor=MUTED, elinewidth=0.8, capsize=2,
                        zorder=3)
            for xi, (_, r) in zip(x, s.iterrows()):
                ax.plot(xi, r.Cd_mean, zorder=4, **mk(m, co, T_COLOR[round(r.t, 2)]))
            e = te[(te.alpha_deg == a) & (te.model == m) & (te.maxCo == co) & (te.U_ms == U_CFD) & (te.resolved_Cd == "yes")]
            for _, r in e.iterrows():
                off = (5, 4) if (co == 5.0 or m == "LM") else (5, -5)
                ax.annotate(sgn(r.dCd_pct, 1, " %"), (r.t_mm + dx, r.Cd), xytext=off,
                            textcoords="offset points", ha="left", va="bottom" if off[1] > 0 else "top",
                            fontsize=6.4, color=BLACK if co == 2.5 else INK2)
        ax.set_title(f"({lab}) {title}", loc="left")
        ax.set_ylabel("$C_d$ (–)")
        ax.set_ylim(*ylim)
    lm0 = one(tx, alpha_deg=0, model="LM", t=0.0, Co=2.5)
    axes[0].text(0.003, 1.972, f"LM t 0 at maxCo 2.5: $C_d$ {lm0.Cd_mean:.2f}, off scale (high-drag state\n"
                 f"to {lm0.high_to:.0f} c/U, then low-drag; jumps): not comparable", fontsize=5.8, color=INK2,
                 ha="left", va="top")
    axes[-1].set_xlabel("Texture amplitude t (mm)")
    axes[-1].set_xticks(T_SWEEP)
    axes[-1].set_xlim(-0.015, 0.235)
    h = handles([dict(marker="s", ls=MODEL_LS["SST"], color=INK2, mfc=INK2, mec=INK2, ms=MS, label="SST, maxCo 2.5, 150 c/U"),
                 dict(marker="o", ls=MODEL_LS["LM"], color=INK2, mfc=INK2, mec=INK2, ms=MS, label="LM, maxCo 2.5, 150 c/U"),
                 dict(marker="s", ls=MODEL_LS["SST"], color=MUTED, mfc="white", mec=INK2, mew=1.1, ms=MS,
                      label="SST, maxCo 5, 80 c/U"),
                 dict(marker="o", ls=MODEL_LS["LM"], color=MUTED, mfc="white", mec=INK2, mew=1.1, ms=MS,
                      label="LM, maxCo 5, 80 c/U"),
                 dict(color=MUTED, lw=0.8, marker="|", ms=6, label="±|drift|")])
    fig.legend(handles=h, loc="outside lower center", ncol=2, fontsize=6.2, handletextpad=0.3, columnspacing=0.9)
    fig.suptitle("Resolved texture, 23 m/s; colour = t; % = change vs t 0 resolved by the drift rule\n"
                 "(maxCo 2.5: last 100 of 150 c/U; maxCo 5: last 50 of 80 c/U)", fontsize=6.4, x=0.02, ha="left",
                 color=INK2)
    return save(fig, "roughness_texture_windows")


def fig_lm_speed(ls, req):
    import roughness_histories as RH
    fig, axes = plt.subplots(3, 1, figsize=(3.6, 8.0), constrained_layout=True,
                             gridspec_kw=dict(height_ratios=[1.25, 1.0, 1.0]))
    ax, bx, cx = axes
    # (a) histories
    lw_u = {18.8: 0.7, 20.9: 0.95, 23.0: 1.2, 25.2: 1.45}
    ax.axvspan(50, 150, color="#ececec", lw=0, zorder=0)
    ends = []
    for _, r in ls.iterrows():
        for case, t_mm in ((r.case_t0, 0.0), (r.case_t0p2, 0.2)):
            t, Cd, Cl, w = RH.forces(case)
            tm, rm = RH.running_mean(t, Cd, 5.0)
            ok = tm >= 10
            ax.plot(tm[ok], rm[ok], color=T_COLOR[t_mm], lw=lw_u[r.U_ms], zorder=3)
            ends.append([rm[-1], f"{r.U_ms:g}", T_COLOR[t_mm], tm[-1]])
    ends.sort(key=lambda e: e[0])
    ylab = [e[0] for e in ends]
    for i in range(1, len(ylab)):                         # keep the end labels 0.0125 apart
        ylab[i] = max(ylab[i], ylab[i - 1] + 0.0125)
    for e, yl in zip(ends, ylab):
        ax.annotate(e[1], (e[3], e[0]), xytext=(153, yl), textcoords="data", fontsize=5.8, color=e[2],
                    va="center", ha="left", arrowprops=dict(arrowstyle="-", lw=0.4, color=e[2], shrinkA=0, shrinkB=0))
    ax.set_xlim(0, 163)
    ax.set_xticks(range(0, 151, 25))
    ax.set_ylim(0.9, 1.3)
    ax.set_xlabel("Time t U/c (–)")
    ax.set_ylabel("$C_d$, 5-c/U running mean (–)")
    ax.set_title("(a) LM, α = 180°, maxCo 2.5; labels: U (m/s)", loc="left")
    h = handles([dict(color=BLACK, lw=1.2, label="smooth (t 0)"), dict(color=T_COLOR[0.2], lw=1.2, label="t 0.20 mm"),
                 dict(color=INK2, lw=0.7, label="thin to thick: 18.8 to 25.2 m/s")])
    # verifier, 19 Oct: edge added; the patch had the band's own grey and was invisible on it
    h.append(Patch(facecolor="#ececec", edgecolor=MUTED, lw=0.6, label="window 50–150 c/U"))
    ax.legend(handles=h, loc="upper right", ncol=2, fontsize=6.0, handlelength=1.8, columnspacing=0.8)
    # (b) texture effect on Cd(180) against U
    lo, hi = req.dCd180_alone_pct.min(), req.dCd180_alone_pct.max()
    r_mean = req[~req.measured.str.contains("23 m/s")]
    lo2, hi2 = r_mean.dCd180_alone_pct.min(), r_mean.dCd180_alone_pct.max()
    bx.axhspan(lo2, hi2, color="#f6dcc0", lw=0, zorder=0)
    bx.text(18.15, lo2 - 0.25, f"needed for the mean gains: {sgn(hi2, 1)} to {sgn(lo2, 1)} % (two-position model)",
            fontsize=5.8, color="#8a4a12", va="top", ha="left")
    bx.axhline(0, color=BLACK, lw=0.8, zorder=1)
    bx.errorbar(ls.U_ms - 0.12, ls.dCd_pct, yerr=ls.noise_pct, fmt="none", ecolor=T_COLOR[0.2], elinewidth=0.9,
                capsize=2, zorder=3)
    bx.plot(ls.U_ms - 0.12, ls.dCd_pct, color=T_COLOR[0.2], lw=1.0, zorder=2, **{k: v for k, v in mk("LM", 2.5, T_COLOR[0.2]).items() if k != "ls"})
    nl = 100 * ls.noise_100_150 / ls.Cd_t0_100_150
    bx.errorbar(ls.U_ms + 0.12, ls.dCd_pct_100_150, yerr=nl, fmt="none", ecolor=MUTED, elinewidth=0.8, capsize=2,
                zorder=3)
    bx.plot(ls.U_ms + 0.12, ls.dCd_pct_100_150, marker="o", ms=4.2, ls="none", mfc="white", mec=T_COLOR[0.2], mew=1.0,
            zorder=4)
    for _, r in ls.iterrows():
        first = r.U_ms == U_BRACKET[0]
        bx.annotate(sgn(r.dCd_pct, 2 if abs(r.dCd_pct) < 0.1 else 1, " %") + ("" if r.resolved == "yes" else " (n.r.)"),
                    (r.U_ms - 0.12, r.dCd_pct),
                    xytext=(6, 16) if first else (-5, 7), textcoords="offset points", ha="left" if first else "right",
                    va="bottom", fontsize=6.2)
    bx.set_xlim(18.0, 26.0)
    bx.set_xticks(U_BRACKET)
    bx.set_ylim(-6, 16)
    bx.set_xlabel("Wind speed U (m/s)")
    bx.set_ylabel("$\\Delta C_d$(180°), t 0.20 vs 0 (%)")
    bx.set_title("(b) Texture effect on the convex-side drag, LM", loc="left")
    h = handles([dict(marker="o", ls="-", color=T_COLOR[0.2], mfc=T_COLOR[0.2], mec=T_COLOR[0.2], ms=MS,
                      label="window 50–150, ±noise (drift rule)"),
                 dict(marker="o", ls="none", mfc="white", mec=T_COLOR[0.2], mew=1.0, ms=4.2,
                      label="last 50 c/U, ±its noise")])
    bx.legend(handles=h, loc="upper left", ncol=1, handletextpad=0.3)
    # (c) measured
    cx.axhline(0, color=BLACK, lw=0.8, zorder=1)
    for rot, dx in (("FS 0.05", -0.15), ("FS 0.10", 0.0), ("FS 0.20", 0.15)):
        c = FS_COLOR[rot]
        y = ls[f"rig_{rot}_change_pct"]
        cx.errorbar(ls.rig_wind_mps + dx, y, yerr=ls[f"rig_{rot}_pw95_pct"], fmt="none", ecolor=c, elinewidth=0.9,
                    capsize=2, zorder=3)
        cx.plot(ls.rig_wind_mps + dx, y, marker="D", ms=4.6, color=c, mfc=c, mec=c, lw=1.0, zorder=4, label=rot)
    cx.set_xlim(18.0, 26.0)
    cx.set_xticks(U_BRACKET)
    cx.set_ylim(-16, 42)
    cx.set_xlabel("Wind speed U (m/s)")
    cx.set_ylabel(r"$P_{max}$ change vs Plain (%)")
    cx.set_title("(c) Measured at the same set points (pointwise 95 %)", loc="left")
    cx.legend(loc="upper left", ncol=3, handletextpad=0.3, columnspacing=0.8)
    return save(fig, "roughness_lm_speed")


BL_ROWS = [   # (quantity, family, config, label): the largest roughness of each fair set, every comparison with
             # the sign the gains need, and the LM speed bracket
    ("Cd(180)", "rough wall function (SST)", "alpha 180, 23 m/s, maxCo 2.5, Ks 400 vs 0", "wf Ks 400, maxCo 2.5"),
    ("Cd(180)", "rough wall function (SST)", "alpha 180, 23 m/s, maxCo 5, Ks 400 vs 0", "wf Ks 400, maxCo 5"),
    ("Cd(180)", "resolved texture (SST)", "alpha 180, 23 m/s, maxCo 2.5, 50-150 c/U, t 0.2 vs 0", "SST t 0.20, maxCo 2.5"),
    ("Cd(180)", "resolved texture (SST)", "alpha 180, 23 m/s, maxCo 5, 30-80 c/U, t 0.2 vs 0", "SST t 0.20, maxCo 5"),
    ("Cd(180)", "resolved texture (LM)", "alpha 180, 23 m/s, maxCo 2.5, 50-150 c/U, t 0.2 vs 0", "LM t 0.20, maxCo 2.5"),
    ("Cd(180)", "resolved texture (LM)", "alpha 180, 23 m/s, maxCo 2.5, 50-150 c/U, t 0.1 vs 0", "LM t 0.10, maxCo 2.5"),
    ("Cd(180)", "resolved texture (LM)", "alpha 180, 23 m/s, maxCo 5, 30-80 c/U, t 0.2 vs 0", "LM t 0.20, maxCo 5"),
    ("Cd(180)", "resolved texture (LM)", "alpha 180, 23 m/s, maxCo 5, 30-80 c/U, t 0.1 vs 0", "LM t 0.10, maxCo 5"),
    ("Cd(180)", "resolved texture (LM)", "alpha 180, 23 m/s, maxCo 5, 30-80 c/U, t 0.05 vs 0", "LM t 0.05, maxCo 5"),
    ("Cd(180)", "resolved texture (LM)", "alpha 180, 18.8 m/s, maxCo 2.5, 50-150 c/U, t 0.2 vs 0", "LM t 0.20, 18.8 m/s"),
    ("Cd(180)", "resolved texture (LM)", "alpha 180, 20.9 m/s, maxCo 2.5, 50-150 c/U, t 0.2 vs 0", "LM t 0.20, 20.9 m/s"),
    ("Cd(180)", "resolved texture (LM)", "alpha 180, 25.2 m/s, maxCo 2.5, 50-150 c/U, t 0.2 vs 0", "LM t 0.20, 25.2 m/s"),
    ("Cd(0)", "rough wall function (SST)", "alpha 0, 23 m/s, maxCo 2.5, Ks 400 vs 0", "wf Ks 400, maxCo 2.5"),
    ("Cd(0)", "rough wall function (SST)", "alpha 0, 23 m/s, maxCo 5, Ks 400 vs 50", "wf Ks 400 vs 50, maxCo 5"),
    # verifier, 19 Oct: the largest Ks of the 10.2 and 38 m/s alpha-0 sets, so the panel matches its caption
    ("Cd(0)", "rough wall function (SST)", "alpha 0, 10.2 m/s, maxCo 2.5, Ks 200 vs 0", "wf Ks 200, 10.2 m/s, maxCo 2.5"),
    ("Cd(0)", "rough wall function (SST)", "alpha 0, 38 m/s, maxCo 2.5, Ks 200 vs 0", "wf Ks 200, 38 m/s, maxCo 2.5"),
    ("Cd(0)", "rough wall function (SST)", "alpha 0, 38 m/s, maxCo 5, Ks 200 vs 0", "wf Ks 200, 38 m/s, maxCo 5"),
    ("Cd(0)", "resolved texture (SST)", "alpha 0, 23 m/s, maxCo 2.5, 50-150 c/U, t 0.2 vs 0", "SST t 0.20, maxCo 2.5"),
    ("Cd(0)", "resolved texture (SST)", "alpha 0, 23 m/s, maxCo 5, 30-80 c/U, t 0.2 vs 0", "SST t 0.20, maxCo 5"),
    ("Cd(0)", "resolved texture (SST)", "alpha 0, 23 m/s, maxCo 5, 30-80 c/U, t 0.1 vs 0", "SST t 0.10, maxCo 5"),
    ("Cd(0)", "resolved texture (LM)", "alpha 0, 23 m/s, maxCo 5, 30-80 c/U, t 0.2 vs 0", "LM t 0.20, maxCo 5"),
    ("Cd(0)", "resolved texture (LM)", "alpha 0, 23 m/s, maxCo 5, 30-80 c/U, t 0.1 vs 0", "LM t 0.10, maxCo 5"),
    ("D", "rough wall function (SST)", "wf, both angles maxCo 2.5, Ks 400 vs 0", "wf Ks 400, maxCo 2.5"),
    ("D", "rough wall function (SST)", "wf, both angles maxCo 5, Ks 400 vs 50", "wf Ks 400 vs 50, maxCo 5"),
    ("D", "resolved texture (SST)", "tex SST, maxCo 2.5, 150 c/U, t 0.2 vs 0", "SST t 0.20, maxCo 2.5"),
    ("D", "resolved texture (SST)", "tex SST, maxCo 5, 80 c/U, t 0.2 vs 0", "SST t 0.20, maxCo 5"),
    ("D", "resolved texture (LM)", "tex LM, maxCo 5, 80 c/U, t 0.2 vs 0", "LM t 0.20, maxCo 5"),
    ("D", "resolved texture (LM)", "tex LM, maxCo 5, 80 c/U, t 0.1 vs 0", "LM t 0.10, maxCo 5"),
    ("D", "resolved texture (LM)", "tex LM, maxCo 5, 80 c/U, t 0.05 vs 0", "LM t 0.05, maxCo 5"),
]


def fig_bottom_line(bl):
    """Selected fair roughness comparisons: change of the drive-relevant quantity with its drift-rule noise."""
    groups = [("Cd(180)", "(a) Convex side, $C_d$(180°): the gains need a decrease"),
              ("Cd(0)", "(b) Concave side, $C_d$(0°): the gains need an increase"),
              ("D", "(c) D = $C_d$(0°) − $C_d$(180°): the gains need an increase")]
    n = [sum(1 for r in BL_ROWS if r[0] == g) for g, _ in groups]
    fig, axes = plt.subplots(3, 1, figsize=(3.6, 0.16 * sum(n) + 2.3), sharex=True, constrained_layout=True,
                             gridspec_kw=dict(height_ratios=[k + 1.2 for k in n]))
    sel = []
    for ax, (g, title), k in zip(axes, groups, n):
        rows = [r for r in BL_ROWS if r[0] == g]
        y = np.arange(len(rows))[::-1]
        if g == "Cd(180)":
            ax.axvspan(-60, 0, color="#f6dcc0", lw=0, zorder=0)
        else:
            ax.axvspan(0, 60, color="#f6dcc0", lw=0, zorder=0)
        ax.set_xlim(-44, 44)   # verifier, 19 Oct: was +-32, which clipped three noise bars in (c) (to -40.6, +35.2, +37.5)
        ax.axvline(0, color=BLACK, lw=0.8, zorder=1)
        for yi, (q, fam, cfg, lab) in zip(y, rows):
            r = bl[(bl.quantity == q) & (bl.family == fam) & (bl.config == cfg)]
            if len(r) != 1:
                raise KeyError((q, fam, cfg, len(r)))
            r = r.iloc[0]
            sel.append(r)
            c = BLACK if r.resolved == "yes" else MUTED
            mk_ = "o" if "LM" in fam else "s"
            ax.errorbar(r.change_pct, yi, xerr=r.noise_pct, fmt="none", ecolor=c, elinewidth=0.8, capsize=1.5, zorder=2)
            ax.plot(r.change_pct, yi, marker=mk_, ms=3.8, mfc=c if r.resolved == "yes" else "white", mec=c, mew=0.9,
                    ls="none", zorder=3)
        ax.set_yticks(y)
        ax.set_yticklabels([r[3] for r in rows], fontsize=5.9)
        ax.set_ylim(-0.7, len(rows) - 0.3)
        ax.grid(axis="y", visible=False)
        ax.set_title(title, loc="left", fontsize=6.6)
    axes[-1].set_xlim(-44, 44)
    axes[-1].set_xlabel("Change vs the smooth case (%)\nbar: drift-rule noise")
    h = handles([dict(marker="s", ls="none", mfc=BLACK, mec=BLACK, ms=3.8, label="resolved"),
                 dict(marker="s", ls="none", mfc="white", mec=MUTED, mew=0.9, ms=3.8, label="not resolved"),
                 dict(marker="o", ls="none", mfc=INK2, mec=INK2, ms=3.8, label="LM (circle), SST (square)")])
    h.append(Patch(color="#f6dcc0", label="direction the gains need"))
    fig.legend(handles=h, loc="outside lower center", ncol=2, fontsize=6.0, handletextpad=0.3, columnspacing=0.9)
    fig.suptitle("Fair roughness comparisons, 23 m/s unless stated; wf = rough wall function (SST),\n"
                 "t = texture amplitude (mm); maxCo 2.5: last 100 of 150 c/U, maxCo 5: as 13 Oct",
                 fontsize=6.3, x=0.02, ha="left", color=INK2)
    return save(fig, "roughness_bottom_line"), pd.DataFrame(sel)


# ================================================================== main
def main():
    style()
    FIG.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    d, s1, meas = load()

    hl = health(d)
    eff = wf_effects(d)
    tp, teff = timestep_pairs(d)
    tr = trends(eff)
    dd = drag_difference(d)
    te = tex_effects(d)
    tts = tex_timestep(d)
    slm, dslm = sst_minus_lm(d)
    mt, mextra = measured(meas)
    req = required_change(d, mt)
    ls = lm_speed(d, meas)
    bl = bottom_line(eff, dd, te)

    # context: Stage 1 medium mesh, 23 m/s, maxCo 5 / 2.5 / 1.25 (the time-step question on a low-Re mesh)
    ctx = s1[(s1.level == "medium") & (s1.U_ms == 23.0) & s1.alpha_deg.isin([0, 180]) & (s1.Tu_body_pct == 1.0)]
    ctx = ctx[["name", "alpha_deg", "model", "maxCo", "Cd_mean", "Cd_std", "Cd_drift", "Cl_mean", "St_peak_frac"]]

    q = dict(
        n_cases=len(d), n_new=int(d.new_15oct.sum()), n_wf=int((d.wall == "wf").sum()), n_tex=int((d.wall == "tex").sum()),
        flagged=int(hl.flagged.sum()), any_symptom=int(hl.any_symptom.sum()), dt_anomaly=int(hl.dt_anomaly.sum()),
        with_jumps=hl[hl.jumps_win > 0].name.tolist(),
        dt_ratio_max_new=float(hl[hl.new_15oct].dt_ratio_median_over_run.max()),
        dt_ratio_max_new_case=hl[hl.new_15oct].sort_values("dt_ratio_median_over_run").name.iloc[-1],
        u_co_range_by_family={f: [float(g.u_co_over_U.min()), float(g.u_co_over_U.max())] for f, g in hl.groupby("family")},
        yplus_tex_max=float(hl[hl.wall == "tex"].yplus_max.max()),
        yplus_tex_max_case=hl[hl.wall == "tex"].sort_values("yplus_max").name.iloc[-1],
        Cd_std_over_Cd_max_tex=float((d[d.wall == "tex"].Cd_std / d[d.wall == "tex"].Cd_mean).max()),
        excluded=hl[hl.comparison_use != "usable"].name.tolist(),
        tex_dt_us={f"{a} {co:g}": [float(1e6 * g.dt_mean_s.min()), float(1e6 * g.dt_mean_s.max())]
                   for (a, co), g in d[(d.wall == "tex") & (d.U_ms == 23)].groupby(["alpha_deg", "Co"])},
        wf_new_absdrift_max={str(a): float(d[(d.wall == "wf") & (d.alpha_deg == a) & (d.Co == 2.5)].Cd_drift.abs().max())
                             for a in (90, 180)},
        tex25_drift_range=[float(d[(d.wall == "tex") & (d.Co == 2.5)].Cd_drift.min()),
                           float(d[(d.wall == "tex") & (d.Co == 2.5)].Cd_drift.max())],
        tex25_cycles=[float(d[(d.wall == "tex") & (d.Co == 2.5)].n_cycles_avg.min()),
                      float(d[(d.wall == "tex") & (d.Co == 2.5)].n_cycles_avg.max())],
        tex25_end_slope_range=[float(d[(d.wall == "tex") & (d.Co == 2.5)].end_slope_per100.min()),
                               float(d[(d.wall == "tex") & (d.Co == 2.5)].end_slope_per100.max())],
        omega_bounded_steps_total=int(d.omega_bounded_steps.sum()),
        Tu_probe_range_new=[float(d[d.new_15oct].Tu_upstream_probe_pct.min()),
                            float(d[d.new_15oct].Tu_upstream_probe_pct.max())],
        mesh_check_new=sorted(d[d.new_15oct].mesh_check.unique().tolist()),
        St_peak_frac_wf_new=[float(d[(d.wall == "wf") & d.new_15oct].St_peak_frac.min()),
                             float(d[(d.wall == "wf") & d.new_15oct].St_peak_frac.max())],
    )
    bl_summary = dict(
        n=len(bl), n_resolved=int((bl.resolved == "yes").sum()),
        n_resolved_needed_sign=int(((bl.resolved == "yes") & (bl.sign_as_needed == "yes")).sum()),
        n_needed_sign_any=int((bl.sign_as_needed == "yes").sum()),
        resolved_needed=bl[(bl.resolved == "yes") & (bl.sign_as_needed == "yes")].config.tolist(),
        largest_needed_sign_ratio=float(bl[bl.sign_as_needed == "yes"].ratio.max()),
        largest_needed_sign_config=bl[bl.sign_as_needed == "yes"].sort_values("ratio").config.iloc[-1],
    )
    for name, df in (("health", hl), ("wf_effects", eff), ("timestep_pairs", tp), ("timestep_effects", teff),
                     ("trends", tr), ("drag_difference", dd), ("tex_effects", te), ("tex_timestep", tts),
                     ("tex_sst_minus_lm", slm), ("tex_D_sst_minus_lm", dslm), ("lm_speed", ls),
                     ("measured", mt), ("required_section_change", req), ("bottom_line", bl),
                     ("section_timestep_context", ctx)):
        df.to_csv(OUT / f"roughness_{name}.csv", index=False, float_format="%.6g")

    figs = [fig_timestep_sweeps(d, eff), fig_drag_difference(dd, mt), fig_texture_windows(d, te),
            fig_lm_speed(ls, req)]
    p, S = fig_bottom_line(bl)
    figs.append(p)
    nums = dict(quality=q, bottom_line=bl_summary, measured_extra=mextra, lam=LAM)
    (OUT / "roughness_numbers.json").write_text(json.dumps(nums, indent=1, default=float))

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 60)
    pd.set_option("display.max_rows", 300)
    print("== quality"); print(json.dumps(q, indent=1, default=float))
    print("== health (new runs)")
    print(hl[hl.new_15oct][["name", "any_symptom", "dt_ratio_median_over_run", "u_co_over_U", "jump_max_win", "jumps_win",
                            "noise_end", "state_win", "status", "comparison_use"]].round(3).to_string())
    print("== wf effects")
    print(eff[["case", "maxCo", "Ks_um", "Cd", "dCd", "dCd_pct", "noise_Cd", "dCd_over_noise", "resolved_Cd", "dCd_pressure",
               "dCd_viscous", "Cl", "dCl", "dCl_pct", "noise_Cl", "resolved_Cl", "St", "dSt_pct"]].round(4).to_string())
    print("== time-step pairs"); print(tp.round(4).to_string())
    print("== time-step effects"); print(teff.round(4).to_string())
    print("== trends"); print(tr.round(5).to_string())
    print("== drag difference")
    print(dd[["set", "roughness", "state_alpha0", "Cd0", "Cd180", "D", "noise_own", "dCd0", "dCd180", "dD", "dD_pct",
              "noise_dD", "dD_over_noise", "resolved", "dN_lam", "dN_sign_lam_0_to_0p25"]].round(4).to_string())
    print("== texture effects")
    print(te[["case", "t_mm", "Cd", "Cd_drift", "dCd", "dCd_pct", "noise_Cd", "dCd_over_noise", "resolved_Cd",
              "dCd_pct_30_80", "resolved_30_80", "dCd_pct_100_150", "resolved_100_150", "dCd_pressure", "dCd_viscous",
              "Cl", "dCl", "resolved_Cl", "St", "St_peak_frac", "end_slope_per100"]].round(4).to_string())
    print("== texture time step"); print(tts.round(4).to_string())
    print("== SST - LM"); print(slm.round(4).to_string()); print(dslm.round(4).to_string())
    print("== LM speed"); print(ls.round(4).T.to_string())
    print("== required change"); print(req.round(3).to_string())
    print("== bottom line", json.dumps(bl_summary, indent=1, default=float))
    print(bl.round(3).to_string())
    print("== context: Stage 1 medium, 23 m/s"); print(ctx.round(4).to_string())
    for p in figs:
        print("wrote", p)


if __name__ == "__main__":
    main()
