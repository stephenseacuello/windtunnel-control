#!/usr/bin/env python3
"""Stage 1 (blade section) analysis of the merged CFD table of 13 Oct 2026.

    nice -n 10 python3 cfd/analysis/2026-10-13/src/section_analysis.py

Reads  ../data/section_polars.csv (51 cases) and cfd/geometry/section_v1.csv.
Writes ../out/section_case_quality.csv   one row per case: health indicators, flags
       ../out/section_polar_LM23.csv      the 360-degree LM polar at 23 m/s with flags
       ../out/section_ratio.csv           Cd(alpha 0)/Cd(alpha 180) on matched runs, literature
       ../out/section_speed_tu.csv        alpha 0 / 180 against U and Tu (medium, maxCo 5)
       ../out/section_sst_vs_lm.csv       matched SST-LM pairs
       ../out/section_timestep.csv        maxCo 5 against 2.5, same mesh
       ../out/section_grid.csv            grid study at maxCo 2.5 (Celik et al. 2008)
       ../out/section_summary.json        the numbers quoted in the findings
and prints a readable summary. No case folder is read.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import section_lib as L  # noqa: E402

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 200)

RIG_LAMBDA_LIGHT_LOAD_U23 = 0.158   # Plain, 23 m/s; cfd/rotor2d/README.md "Comparison with the rig"
RIG_LAMBDA_PEAK_EL_U23 = (0.120, 0.122)


def pct(a, b):
    return 100.0 * (a - b) / abs(b)


def pick(d, **kw):
    m = np.ones(len(d), bool)
    for k, v in kw.items():
        m &= (d[k] == v).to_numpy()
    return d[m]


def one(d, **kw):
    r = pick(d, **kw)
    if len(r) != 1:
        raise KeyError(f"{kw}: {len(r)} rows")
    return r.iloc[0]


# --------------------------------------------------------------------- Celik et al. (2008)
def celik(phi, n_cells):
    """phi, n_cells ordered (coarse, medium, fine). Returns a dict; p and GCI only for
    monotonic convergence (0 < e21/e32 < 1)."""
    phi3, phi2, phi1 = phi
    N3, N2, N1 = n_cells
    r21, r32 = math.sqrt(N1 / N2), math.sqrt(N2 / N3)
    e21, e32 = phi2 - phi1, phi3 - phi2
    out = dict(coarse=phi3, medium=phi2, fine=phi1, r21=r21, r32=r32, e32=e32, e21=e21,
               R=e21 / e32 if e32 != 0 else float("nan"), p=float("nan"), phi_ext=float("nan"),
               GCI_fine_pct=float("nan"),
               spread_pct_of_fine=100 * (max(phi) - min(phi)) / abs(phi1))
    R = out["R"]
    if not np.isfinite(R):
        out["verdict"] = "undefined"
    elif R < 0:
        out["verdict"] = "oscillatory: no order; report the range"
    elif R >= 1:
        out["verdict"] = "diverging: the change grows with refinement"
    else:
        s = 1.0
        p = abs(math.log(abs(e32 / e21))) / math.log(r21)
        for _ in range(200):
            q = math.log((r21 ** p - s) / (r32 ** p - s))
            p_new = abs(math.log(abs(e32 / e21)) + q) / math.log(r21)
            if abs(p_new - p) < 1e-12:
                break
            p = p_new
        rp = r21 ** p
        out.update(p=p, phi_ext=(rp * phi1 - phi2) / (rp - 1),
                   GCI_fine_pct=100 * 1.25 * abs((phi1 - phi2) / phi1) / (rp - 1),
                   verdict="monotonic convergence")
    return out


def lambda0(k):
    """Zero-torque tip-speed ratio of the quasi-steady two-cup drag model,
    k (1 - lam)^2 = (1 + lam)^2, k = Cd_concave / Cd_convex."""
    s = math.sqrt(k)
    return (s - 1) / (s + 1) if k > 0 else float("nan")


def lambda_peak(k):
    """Tip-speed ratio of peak power of the same model, P ~ lam [k (1-lam)^2 - (1+lam)^2]."""
    if k <= 1:
        return float("nan")
    a, b, c = 3 * (k - 1), -4 * (k + 1), (k - 1)
    return (-b - math.sqrt(b * b - 4 * a * c)) / (2 * a)


def main():
    d = L.load()
    L.OUT.mkdir(exist_ok=True)
    S = {}   # summary numbers

    # ---------------------------------------------------------------- 1. quality flags
    bad = d[d.corrupted]
    good = d[~d.corrupted]
    lo_bad, hi_good = bad.u_co_over_U.min(), good.u_co_over_U.max()
    assert hi_good < L.U_CO_LIMIT < lo_bad, "the u_Co/U groups overlap: revisit the flag"
    assert bad.any_symptom.all(), "a flagged case has no independent symptom: revisit the flag"
    assert not good.any_symptom.any(), "a healthy case has a symptom: revisit the flag"
    S["n_cases"] = len(d)
    S["n_corrupted"] = int(d.corrupted.sum())
    S["u_co_over_U_healthy_range"] = [round(good.u_co_over_U.min(), 2), round(hi_good, 2)]
    S["u_co_over_U_corrupted_range"] = [round(lo_bad, 2), round(bad.u_co_over_U.max(), 2)]
    S["corrupted_by_symptom"] = dict(
        negative_mean_drag=int(bad.neg_drag.sum()), Cd_std_gt_abs_mean=int(bad.std_gt_mean.sum()),
        abs_Cl_mean_gt_3=int(bad.cl_gt3.sum()), yplus_max_mean_gt_2=int(bad.yplus_spike.sum()),
        any_implausible_force=int(bad.implausible_forces.sum()),
        only_yplus=bad[~bad.implausible_forces].name.tolist(),
        only_forces=bad[~bad.yplus_spike].name.tolist())
    S["healthy_yplus_max_mean_max"] = round(good.yplus_max_mean.max(), 3)
    S["corrupted_yplus_max_mean_range"] = [round(bad.yplus_max_mean.min(), 2), round(bad.yplus_max_mean.max(), 2)]
    grp = d.groupby(["level", "maxCo"]).agg(n=("name", "size"), corrupted=("corrupted", "sum"))
    S["corrupted_by_level_co"] = {f"{k[0]} maxCo {k[1]:g}": f"{int(v.corrupted)} of {int(v.n)}"
                                  for k, v in grp.iterrows()}
    S["negative_drag_cases"] = bad[bad.neg_drag].name.tolist()
    S["corrupted_cases"] = bad.sort_values(["alpha_deg", "model", "U_ms", "Tu_body_pct"]).name.tolist()
    # dt and steps: healthy vs corrupted, medium maxCo 5
    m5 = pick(d, level="medium", maxCo=5.0)
    S["medium_co5_dt_conv_healthy"] = [float(f"{m5[~m5.corrupted].dt_conv.min():.3g}"),
                                       float(f"{m5[~m5.corrupted].dt_conv.max():.3g}")]
    S["medium_co5_dt_conv_corrupted"] = [float(f"{m5[m5.corrupted].dt_conv.min():.3g}"),
                                         float(f"{m5[m5.corrupted].dt_conv.max():.3g}")]
    S["medium_co5_steps_healthy"] = [int(m5[~m5.corrupted].n_steps.min()), int(m5[~m5.corrupted].n_steps.max())]
    S["medium_co5_steps_corrupted"] = [int(m5[m5.corrupted].n_steps.min()), int(m5[m5.corrupted].n_steps.max())]
    S["medium_co25_steps"] = pick(d, level="medium", maxCo=2.5).set_index("alpha_deg").n_steps.astype(int).to_dict()
    h5 = m5[~m5.corrupted]
    S["medium_co5_dt_conv_healthy_by_model"] = {
        mdl: dict(n=int(len(g)), min=float(f"{g.dt_conv.min():.3g}"), median=float(f"{g.dt_conv.median():.3g}"),
                  max=float(f"{g.dt_conv.max():.3g}")) for mdl, g in h5.groupby("model")}
    S["medium_co5_dt_us_23ms"] = {
        ("corrupted" if c else "healthy") + " " + mdl: [round(1e6 * g.dt_mean_s.min(), 3), round(1e6 * g.dt_mean_s.max(), 3)]
        for (c, mdl), g in m5[m5.U_ms == 23.0].groupby(["corrupted", "model"])}
    cols = ["name", "alpha_deg", "U_ms", "model", "level", "maxCo", "Tu_body_pct", "ran_on", "n_cells",
            "Cd_mean", "Cd_std", "Cl_mean", "Cl_std", "Cm_mean", "Cd_pressure_mean", "Cd_viscous_mean",
            "St", "St_peak_frac", "St_status", "n_cycles_avg", "Cd_drift", "Cd_drift_rel", "Cd_se",
            "dt_mean_s", "dt_conv", "u_co_over_U", "yplus_max_mean", "yplus_max_max", "yplus_mean_mean",
            "Tu_upstream_probe_pct", "n_steps", "neg_drag", "std_gt_mean", "cl_gt3", "corrupted",
            "branch_a0", "d_frontal_mm", "Cd_on_frontal", "St_on_frontal"]
    d.sort_values(["alpha_deg", "model", "level_i", "maxCo", "U_ms", "Tu_body_pct"])[cols].to_csv(
        L.OUT / "section_case_quality.csv", index=False, float_format="%.6g")

    print("== 1. Quality flag: u_Co/U = maxCo dx_corner / (dt U)")
    print(f"healthy {len(good)} cases: {good.u_co_over_U.min():.2f}-{hi_good:.2f}; "
          f"corrupted {len(bad)} cases: {lo_bad:.2f}-{bad.u_co_over_U.max():.2f}")
    print("by symptom:", S["corrupted_by_symptom"])
    print("by level/maxCo:", S["corrupted_by_level_co"])
    print("medium Co5 dt (c/U) healthy", S["medium_co5_dt_conv_healthy"], "corrupted", S["medium_co5_dt_conv_corrupted"])
    print("medium Co5 steps healthy", S["medium_co5_steps_healthy"], "corrupted", S["medium_co5_steps_corrupted"],
          "; medium Co2.5 steps", S["medium_co25_steps"])
    print("healthy medium Co5 dt (c/U) by model:", S["medium_co5_dt_conv_healthy_by_model"])
    print("medium Co5 dt (us) at 23 m/s:", S["medium_co5_dt_us_23ms"])

    # ---------------------------------------------------------------- 2. LM polar 23 m/s
    pol = pick(d, model="LM", U_ms=23.0, Tu_body_pct=1.0, level="medium", maxCo=5.0).sort_values("alpha_deg")
    pol[["name", "alpha_deg", "Cd_mean", "Cd_std", "Cl_mean", "Cl_std", "Cm_mean", "Cm_std", "St",
         "St_peak_frac", "St_status", "Cd_drift_rel", "n_cycles_avg", "u_co_over_U", "yplus_max_mean",
         "corrupted", "d_frontal_mm"]].to_csv(L.OUT / "section_polar_LM23.csv", index=False, float_format="%.6g")
    S["LM23_polar_healthy_alpha"] = pol[~pol.corrupted].alpha_deg.astype(int).tolist()
    S["LM23_polar_corrupted_alpha"] = pol[pol.corrupted].alpha_deg.astype(int).tolist()
    S["LM23_polar_healthy"] = {int(r.alpha_deg): dict(Cd=round(r.Cd_mean, 4), Cl=round(r.Cl_mean, 4),
                                                      Cm=round(r.Cm_mean, 4), Cd_std=round(r.Cd_std, 4),
                                                      St=round(r.St, 4), St_status=r.St_status,
                                                      Cd_drift_rel=round(r.Cd_drift_rel, 3),
                                                      n_cycles=round(r.n_cycles_avg, 1))
                               for r in pol[~pol.corrupted].itertuples()}
    print("\n== 2. LM polar, 23 m/s, Tu 1 %, medium, maxCo 5")
    print(pol[["alpha_deg", "Cd_mean", "Cd_std", "Cl_mean", "Cl_std", "Cm_mean", "St", "St_peak_frac",
               "n_cycles_avg", "Cd_drift_rel", "u_co_over_U", "corrupted"]].to_string(index=False, float_format=lambda x: f"{x:.4g}"))
    sst3 = d[(d.model == "SST") & (d.U_ms == 23.0) & (d.level == "medium")].sort_values(["alpha_deg", "maxCo"])
    print(sst3[["name", "Cd_mean", "Cl_mean", "Cm_mean", "St", "corrupted"]].to_string(index=False))

    # ---------------------------------------------------------------- 3. drag ratio
    rows = []
    for (lvl, mdl, co, U, tu), g in d.groupby(["level", "model", "maxCo", "U_ms", "Tu_body_pct"]):
        a0, a180 = g[g.alpha_deg == 0], g[g.alpha_deg == 180]
        if len(a0) == 1 and len(a180) == 1:
            r0, r1 = a0.iloc[0], a180.iloc[0]
            ok = (not r0.corrupted) and (not r1.corrupted)
            k = r0.Cd_mean / r1.Cd_mean
            rows.append(dict(source="CFD", level=lvl, model=mdl, maxCo=co, U_ms=U, Tu_pct=tu,
                             case_a0=r0["name"], case_a180=r1["name"], Cd_a0=r0.Cd_mean, Cd_a180=r1.Cd_mean,
                             branch_a0=r0.branch_a0, usable=ok, ratio=k if ok else float("nan"),
                             dCd=(r0.Cd_mean - r1.Cd_mean) if ok else float("nan"),
                             lambda0_qs=lambda0(k) if ok else float("nan"),
                             lambda_peak_qs=lambda_peak(k) if ok else float("nan")))
    klit = L.LIT_CD_CONCAVE / L.LIT_CD_CONVEX
    rows.append(dict(source="literature (cfd/PLAN.md; 2D half-cylinder shell)", Cd_a0=L.LIT_CD_CONCAVE,
                     Cd_a180=L.LIT_CD_CONVEX, usable=True, ratio=klit, dCd=L.LIT_CD_CONCAVE - L.LIT_CD_CONVEX,
                     lambda0_qs=lambda0(klit), lambda_peak_qs=lambda_peak(klit)))
    ratio = pd.DataFrame(rows)
    ratio.to_csv(L.OUT / "section_ratio.csv", index=False, float_format="%.5g")
    k_needed = ((1 + RIG_LAMBDA_LIGHT_LOAD_U23) / (1 - RIG_LAMBDA_LIGHT_LOAD_U23)) ** 2
    S["ratio"] = [dict(case_a0=r.case_a0, case_a180=r.case_a180, Cd_a0=round(r.Cd_a0, 4), Cd_a180=round(r.Cd_a180, 4),
                       ratio=round(r.ratio, 3), dCd=round(r.dCd, 3), lambda0_qs=round(r.lambda0_qs, 3),
                       lambda_peak_qs=round(r.lambda_peak_qs, 3), branch_a0=r.branch_a0)
                  for r in ratio[(ratio.source == "CFD") & ratio.usable].itertuples()]
    S["ratio_unusable_pairs"] = int(((ratio.source == "CFD") & ~ratio.usable).sum())
    S["ratio_literature"] = dict(ratio=round(klit, 3), lambda0_qs=round(lambda0(klit), 3),
                                 lambda_peak_qs=round(lambda_peak(klit), 3))
    S["ratio_needed_for_rig_light_load_lambda"] = round(k_needed, 3)
    S["frontal_width_mm"] = {int(a): round(L.frontal_width(a) * 1e3, 2) for a in (0, 90, 180, 270)}
    print("\n== 3. Cd(alpha 0)/Cd(alpha 180), matched runs")
    print(ratio.to_string(index=False, float_format=lambda x: f"{x:.4g}"))
    print(f"k needed for lambda0 >= {RIG_LAMBDA_LIGHT_LOAD_U23}: {k_needed:.3f}; frontal widths (mm):", S["frontal_width_mm"])

    # ---------------------------------------------------------------- 4. speed and Tu
    st = d[(d.level == "medium") & (d.maxCo == 5.0) & d.alpha_deg.isin([0, 180])]
    sp = st[st.Tu_body_pct == 1.0].copy()
    tu = st[(st.model == "LM") & (st.U_ms == 23.0)].copy()
    sp["sweep"], tu["sweep"] = "speed", "Tu"
    sw = pd.concat([sp, tu]).drop_duplicates(subset=["name", "sweep"])
    sw = sw.sort_values(["sweep", "alpha_deg", "model", "U_ms", "Tu_body_pct"])
    sw[["sweep", "name", "alpha_deg", "model", "U_ms", "Re_c", "Tu_body_pct", "Cd_mean", "Cd_std", "Cd_se",
        "Cl_mean", "Cl_std", "Cm_mean", "St", "St_peak_frac", "Cd_drift_rel", "Cd_pressure_mean",
        "Cd_viscous_mean", "corrupted", "branch_a0"]].to_csv(L.OUT / "section_speed_tu.csv", index=False,
                                                             float_format="%.6g")
    print("\n== 4. Speed and Tu sweeps (medium, maxCo 5)")
    print(sw[["sweep", "alpha_deg", "model", "U_ms", "Tu_body_pct", "Cd_mean", "Cd_std", "Cd_se", "Cl_mean",
              "Cl_std", "St", "St_peak_frac", "Cd_drift_rel", "corrupted", "branch_a0"]].to_string(
        index=False, float_format=lambda x: f"{x:.4g}"))
    S["speed_a0"] = {f"{r.model} {r.U_ms:g}": dict(Cd=round(r.Cd_mean, 4), Cd_se=round(r.Cd_se, 3),
                                                   Cl=round(r.Cl_mean, 3), Cl_std=round(r.Cl_std, 3),
                                                   St=round(r.St, 4), St_frac=round(r.St_peak_frac, 2),
                                                   branch=r.branch_a0, Re_c=round(r.Re_c))
                     for r in sp[sp.alpha_deg == 0].itertuples()}
    S["speed_a180_all_corrupted"] = bool(sp[sp.alpha_deg == 180].corrupted.all())
    S["tu_a0"] = {f"Tu {r.Tu_body_pct:g}": dict(Cd=round(r.Cd_mean, 4), Cd_se=round(r.Cd_se, 3),
                                                Cl_std=round(r.Cl_std, 3), St=round(r.St, 4),
                                                St_frac=round(r.St_peak_frac, 2), branch=r.branch_a0,
                                                drift_rel=round(r.Cd_drift_rel, 3))
                  for r in tu[tu.alpha_deg == 0].itertuples()}
    S["tu_a180_all_corrupted"] = bool(tu[tu.alpha_deg == 180].corrupted.all())
    s0 = sp[(sp.alpha_deg == 0) & (sp.model == "SST")].set_index("U_ms")
    S["SST_a0_speed_change_pct_vs_23"] = {f"{u:g}": round(pct(s0.loc[u, "Cd_mean"], s0.loc[23.0, "Cd_mean"]), 2)
                                          for u in (10.2, 38.0)}
    S["SST_a0_speed_change_in_combined_SE"] = {
        f"{u:g}": round((s0.loc[u, "Cd_mean"] - s0.loc[23.0, "Cd_mean"]) /
                        math.hypot(s0.loc[u, "Cd_se"], s0.loc[23.0, "Cd_se"]), 2) for u in (10.2, 38.0)}
    a0h = d[(d.alpha_deg == 0) & ~d.corrupted]
    for b in ("high-drag shedding", "low-drag"):
        g = a0h[a0h.branch_a0 == b]
        S[f"a0_branch_{b}"] = dict(n=len(g), cases=g.name.tolist(),
                                   Cd=[round(g.Cd_mean.min(), 4), round(g.Cd_mean.max(), 4)],
                                   Cl_mean=[round(g.Cl_mean.min(), 3), round(g.Cl_mean.max(), 3)],
                                   Cl_std=[round(g.Cl_std.min(), 4), round(g.Cl_std.max(), 4)],
                                   Cm=[round(g.Cm_mean.min(), 3), round(g.Cm_mean.max(), 3)],
                                   St=[round(g.St.min(), 4), round(g.St.max(), 4)])
    print("\nalpha 0 branches:")
    for b in ("high-drag shedding", "low-drag"):
        print(b, {k: v for k, v in S[f'a0_branch_{b}'].items() if k != 'cases'})

    # ---------------------------------------------------------------- 5. SST vs LM
    prs = []
    for (a, U, tuv, lvl, co), g in d.groupby(["alpha_deg", "U_ms", "Tu_body_pct", "level", "maxCo"]):
        if set(g.model) >= {"SST", "LM"}:
            s, l = g[g.model == "SST"].iloc[0], g[g.model == "LM"].iloc[0]
            ok = (not s.corrupted) and (not l.corrupted)
            prs.append(dict(alpha_deg=a, U_ms=U, Tu_pct=tuv, level=lvl, maxCo=co, case_SST=s["name"],
                            case_LM=l["name"], usable=ok, Cd_SST=s.Cd_mean, Cd_LM=l.Cd_mean,
                            dCd_pct=pct(l.Cd_mean, s.Cd_mean) if ok else float("nan"),
                            St_SST=s.St, St_LM=l.St, dSt_pct=pct(l.St, s.St) if ok else float("nan"),
                            Cl_SST=s.Cl_mean, Cl_LM=l.Cl_mean, Cdv_SST=s.Cd_viscous_mean,
                            Cdv_LM=l.Cd_viscous_mean, branch_SST=s.branch_a0, branch_LM=l.branch_a0))
    prs = pd.DataFrame(prs)
    prs.to_csv(L.OUT / "section_sst_vs_lm.csv", index=False, float_format="%.6g")
    S["sst_vs_lm"] = [dict(alpha=int(r.alpha_deg), U=r.U_ms, usable=bool(r.usable), Cd_SST=round(r.Cd_SST, 4),
                           Cd_LM=round(r.Cd_LM, 4), dCd_pct=round(r.dCd_pct, 2) if r.usable else None,
                           St_SST=round(r.St_SST, 4), St_LM=round(r.St_LM, 4),
                           dSt_pct=round(r.dSt_pct, 2) if r.usable else None,
                           branch_SST=r.branch_SST, branch_LM=r.branch_LM) for r in prs.itertuples()]
    print("\n== 5. SST vs LM, matched (same alpha, U, Tu, mesh, maxCo)")
    print(prs[["alpha_deg", "U_ms", "usable", "Cd_SST", "Cd_LM", "dCd_pct", "St_SST", "St_LM", "dSt_pct",
               "Cdv_SST", "Cdv_LM", "branch_SST", "branch_LM"]].to_string(index=False, float_format=lambda x: f"{x:.4g}"))
    hv = d[~d.corrupted]
    S["viscous_share_pct"] = {
        "alpha0_healthy": [round(100 * (hv[hv.alpha_deg == 0].Cd_viscous_mean / hv[hv.alpha_deg == 0].Cd_mean).min(), 2),
                           round(100 * (hv[hv.alpha_deg == 0].Cd_viscous_mean / hv[hv.alpha_deg == 0].Cd_mean).max(), 2)],
        "alpha180_healthy": [round(100 * (hv[hv.alpha_deg == 180].Cd_viscous_mean / hv[hv.alpha_deg == 180].Cd_mean).min(), 2),
                             round(100 * (hv[hv.alpha_deg == 180].Cd_viscous_mean / hv[hv.alpha_deg == 180].Cd_mean).max(), 2)],
        "alpha90_healthy": [round(100 * (hv[hv.alpha_deg == 90].Cd_viscous_mean / hv[hv.alpha_deg == 90].Cd_mean).min(), 2),
                            round(100 * (hv[hv.alpha_deg == 90].Cd_viscous_mean / hv[hv.alpha_deg == 90].Cd_mean).max(), 2)]}
    print("viscous share of Cd (%):", S["viscous_share_pct"])

    # ---------------------------------------------------------------- 6. time step
    ts = []
    for (a, lvl), g in d[(d.model == "SST") & (d.U_ms == 23.0)].groupby(["alpha_deg", "level"]):
        if set(g.maxCo) >= {5.0, 2.5}:
            c5, c25 = g[g.maxCo == 5.0].iloc[0], g[g.maxCo == 2.5].iloc[0]
            ok = (not c5.corrupted) and (not c25.corrupted)
            ts.append(dict(alpha_deg=a, level=lvl, case_Co5=c5["name"], case_Co25=c25["name"], usable=ok,
                           Cd_Co5=c5.Cd_mean, Cd_Co25=c25.Cd_mean, dCd_pct=pct(c25.Cd_mean, c5.Cd_mean),
                           Cl_Co5=c5.Cl_mean, Cl_Co25=c25.Cl_mean, dCl_pct=pct(c25.Cl_mean, c5.Cl_mean),
                           Cl_std_Co5=c5.Cl_std, Cl_std_Co25=c25.Cl_std, St_Co5=c5.St, St_Co25=c25.St,
                           St_status_Co5=c5.St_status, St_status_Co25=c25.St_status,
                           steps_Co5=int(c5.n_steps), steps_Co25=int(c25.n_steps)))
    ts = pd.DataFrame(ts)
    ts.to_csv(L.OUT / "section_timestep.csv", index=False, float_format="%.6g")
    S["timestep"] = [dict(alpha=int(r.alpha_deg), level=r.level, usable=bool(r.usable), Cd_Co5=round(r.Cd_Co5, 4),
                          Cd_Co25=round(r.Cd_Co25, 4), dCd_pct=round(r.dCd_pct, 1), Cl_Co5=round(r.Cl_Co5, 4),
                          Cl_Co25=round(r.Cl_Co25, 4), dCl_pct=round(r.dCl_pct, 1),
                          Cl_std_Co5=round(r.Cl_std_Co5, 4), Cl_std_Co25=round(r.Cl_std_Co25, 5),
                          St_Co5=round(r.St_Co5, 4), St_Co25=round(r.St_Co25, 4),
                          St_status_Co5=r.St_status_Co5, St_status_Co25=r.St_status_Co25) for r in ts.itertuples()]
    print("\n== 6. maxCo 5 vs 2.5 (SST, 23 m/s, Tu 1 %)")
    print(ts.drop(columns=["case_Co5", "case_Co25"]).to_string(index=False, float_format=lambda x: f"{x:.4g}"))

    # ---------------------------------------------------------------- 7. grid study
    gs = []
    for a in (0, 90, 180):
        g = pick(d, model="SST", U_ms=23.0, maxCo=2.5, alpha_deg=a).sort_values("level_i")
        assert list(g.level) == ["coarse", "medium", "fine"] and not g.corrupted.any()
        for q in ("Cd_mean", "Cl_mean", "Cm_mean", "St"):
            res = celik(g[q].tolist(), g.n_cells.tolist())
            st_ok = (g.St_status == "clean peak").all() if q == "St" else True
            res.update(alpha_deg=a, quantity=q, cases=" | ".join(g.name), St_usable=bool(st_ok))
            if q == "St" and not st_ok:
                res["verdict"] = "St not usable: " + ", ".join(g.St_status.tolist())
                for k in ("p", "phi_ext", "GCI_fine_pct"):
                    res[k] = float("nan")
            gs.append(res)
    gs = pd.DataFrame(gs)
    gs.to_csv(L.OUT / "section_grid.csv", index=False, float_format="%.6g")
    S["grid"] = [dict(alpha=int(r.alpha_deg), q=r.quantity, coarse=round(r.coarse, 5), medium=round(r.medium, 5),
                      fine=round(r.fine, 5), R=round(r.R, 3), p=round(r.p, 3) if np.isfinite(r.p) else None,
                      phi_ext=round(r.phi_ext, 4) if np.isfinite(r.phi_ext) else None,
                      GCI_fine_pct=round(r.GCI_fine_pct, 2) if np.isfinite(r.GCI_fine_pct) else None,
                      spread_pct_of_fine=round(r.spread_pct_of_fine, 2), verdict=r.verdict) for r in gs.itertuples()]
    S["grid_r21_r32"] = {int(a): (round(gs[gs.alpha_deg == a].r21.iloc[0], 4), round(gs[gs.alpha_deg == a].r32.iloc[0], 4))
                         for a in (0, 90, 180)}
    print("\n== 7. Grid study, SST, 23 m/s, maxCo 2.5 (Celik et al. 2008)")
    print(gs[["alpha_deg", "quantity", "coarse", "medium", "fine", "r21", "r32", "R", "p", "phi_ext", "GCI_fine_pct",
              "spread_pct_of_fine", "verdict"]].to_string(index=False, float_format=lambda x: f"{x:.4g}"))
    g0 = pick(d, model="SST", U_ms=23.0, maxCo=2.5, alpha_deg=0).sort_values("level_i")
    S["grid_a0_Cd_std"] = dict(zip(g0.level, g0.Cd_std.round(4)))
    S["grid_a0_Cl_std"] = dict(zip(g0.level, g0.Cl_std.round(4)))
    S["grid_a0_St_frac"] = dict(zip(g0.level, g0.St_peak_frac.round(3)))
    g180 = pick(d, model="SST", U_ms=23.0, maxCo=2.5, alpha_deg=180).sort_values("level_i")
    S["grid_a180_yplus_max_max"] = dict(zip(g180.level, g180.yplus_max_max.round(2)))
    S["grid_a180_St_frac"] = dict(zip(g180.level, g180.St_peak_frac.round(3)))

    # ---------------------------------------------------------------- 8. St, drift, y+, Tu, cost
    clean = d[d.St_status == "clean peak"].sort_values(["alpha_deg", "model", "level_i", "maxCo", "U_ms"])
    S["St_clean"] = [dict(case=r.name, St=round(r.St, 4), frac=round(r.St_peak_frac, 3),
                          St_on_frontal=round(r.St_on_frontal, 4), f_Hz=round(r.St * r.U_ms / L.C_REF, 1))
                     for r in clean.itertuples()]
    print("\n== 8. Strouhal (clean peaks, healthy runs)")
    print(clean[["name", "St", "St_peak_frac", "St_on_frontal", "d_frontal_mm", "n_cycles_avg"]].to_string(
        index=False, float_format=lambda x: f"{x:.4g}"))
    for a in (0, 90, 180, 270):
        print(f"  f at 10.2/23/38 m/s for St(c) of alpha {a}:", end=" ")
        g = clean[clean.alpha_deg == a]
        if len(g):
            stv = g.St.median()
            print(f"median St {stv:.4f} ->", ", ".join(f"{stv * U / L.C_REF:.0f} Hz" for U in (10.2, 23.0, 38.0)))
        else:
            print("no clean peak")
    hd = d[~d.corrupted & d.Cd_drift_rel.notna()]
    big = hd[hd.Cd_drift_rel.abs() > 0.10]
    S["drift_healthy_abs_rel_max_pct"] = round(100 * hd.Cd_drift_rel.abs().max(), 1)
    S["drift_healthy_gt10pct"] = {r.name: dict(drift_rel_pct=round(100 * r.Cd_drift_rel, 1), drift=round(r.Cd_drift, 3),
                                               two_se=round(2 * r.Cd_se, 3), n_cycles=round(r.n_cycles_avg, 1))
                                  for r in big.itertuples()}
    hu = hd[hd.St_status.isin(["clean peak", "broadband (peak frac < 0.5)"])]
    S["drift_within_2se_unsteady"] = f"{int((hu.Cd_drift.abs() <= 2 * hu.Cd_se).sum())} of {len(hu)}"
    S["drift_beyond_2se_unsteady"] = {r.name: dict(drift=round(r.Cd_drift, 4), two_se=round(2 * r.Cd_se, 4))
                                      for r in hu[hu.Cd_drift.abs() > 2 * hu.Cd_se].itertuples()}
    print("\nhealthy cases with |Cd drift| > 10 % of mean:", S["drift_healthy_gt10pct"])
    print("unsteady healthy cases with |drift| <= 2 SE:", S["drift_within_2se_unsteady"], S["drift_beyond_2se_unsteady"])
    S["yplus_healthy"] = dict(max_mean=[round(good.yplus_max_mean.min(), 3), round(good.yplus_max_mean.max(), 3)],
                              max_max=round(good.yplus_max_max.max(), 2),
                              mean_mean=[round(good.yplus_mean_mean.min(), 3), round(good.yplus_mean_mean.max(), 3)])
    S["yplus_healthy_by_U"] = {f"{u:g}": round(good[good.U_ms == u].yplus_max_mean.max(), 3) for u in (10.2, 23.0, 38.0)}
    dev = 100 * (d.Tu_upstream_probe_pct / d.Tu_body_pct - 1)
    S["Tu_probe_dev_pct"] = [round(dev.min(), 2), round(dev.max(), 2)]
    S["Tu_probe_by_target"] = {f"{t:g}": [round(d[d.Tu_body_pct == t].Tu_upstream_probe_pct.min(), 4),
                                          round(d[d.Tu_body_pct == t].Tu_upstream_probe_pct.max(), 4)]
                               for t in (0.5, 1.0, 3.0)}
    S["omega_bounded_steps_total"] = int(d.omega_bounded_steps.sum())
    S["wall_time_only_last_session"] = d[d.s_per_step < 0.02].name.tolist()
    # Verifier addition (13 Oct): dt_mean_s equals t_end / n_steps exactly (to 1e-4) for every
    # single-session run, so a run whose step count exceeds t_end / dt_mean_s re-ran steps after a
    # restart (time-limit resubmission or migration). Its wall_time_s may cover only part of the run,
    # and the s_per_step < 0.02 test above catches only 4 of them.
    t_end_s = d.t_end_conv * L.C_REF / d.U_ms
    over = d.n_steps * d.dt_mean_s / t_end_s - 1.0
    rs = d[over > 0.005].sort_values("alpha_deg")
    S["restarted_runs_step_overcount_pct"] = {r.name: round(100 * o, 1) for r, o in zip(rs.itertuples(), over[rs.index])}
    S["restarted_runs_all_flagged_except"] = rs[~rs.corrupted].name.tolist()
    S["a090_SST_medium_Co5_window"] = [float(one(d, alpha_deg=90, model="SST", level="medium", maxCo=5.0).avg_from_conv),
                                       float(one(d, alpha_deg=90, model="SST", level="medium", maxCo=5.0).avg_to_conv)]
    print("y+ healthy:", S["yplus_healthy"], S["yplus_healthy_by_U"])
    print("Tu probe deviation (%):", S["Tu_probe_dev_pct"], S["Tu_probe_by_target"])
    print("s_per_step < 0.02 (wall time of the last session only):", S["wall_time_only_last_session"])
    print("restarted runs (step over-count %):", S["restarted_runs_step_overcount_pct"],
          "; not flagged among them:", S["restarted_runs_all_flagged_except"])

    with open(L.OUT / "section_summary.json", "w") as f:
        json.dump(S, f, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print("\nwrote", *(p.name for p in sorted(L.OUT.glob("section_*"))))


if __name__ == "__main__":
    main()
