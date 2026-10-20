#!/usr/bin/env python3
"""Stage 1 (smooth blade section) analysis of the 125-case table of 15 Oct 2026.

    nice -n 10 python3 cfd/analysis/2026-10-15/src/section_histories.py   # first: jumps, logs, histories
    nice -n 10 python3 cfd/analysis/2026-10-15/src/section_analysis.py

Adapted from cfd/analysis/2026-10-13/src/section_analysis.py. Reads (read only)
cfd/section2d/results/section_polars.csv through section_lib, ../out/section_jumps.csv and
../out/section_histories.json (section_histories.py) and, for the transition-test runs, the
time-mean wall distributions cfd/section2d/results/records/<case>/fields/surface_mean.csv.
Writes
  ../out/section_case_quality.csv        one row per case (125): health flag, symptoms, jumps, residuals
  ../out/section_timestep.csv            alpha 0 and 180, SST and LM, medium, 23 m/s: maxCo 5 / 2.5 / 1.25
  ../out/section_timestep_changes.csv    the changes between time steps, with noise
  ../out/section_polar_LM23.csv          the LM polar at 23 m/s, Tu 1 %, healthy runs, maxCo per point
  ../out/section_transition_pairs.csv    LM against SST (Tu 1 %), alpha 150-210, 10.2 / 23 / 38 m/s
  ../out/section_transition_tu.csv       LM at Tu 0.5 and 3 % against Tu 1 %
  ../out/section_transition_speed.csv    10.2 and 38 m/s against 23 m/s, LM (each Tu) and SST
  ../out/section_transition_surface.csv  stagnation, tip-B separation, Cf peak, base pressure per run
  ../out/section_summary.json            the numbers quoted
and prints a readable summary.

Comparison rule. A change between runs a and b is *resolved* when
  (1) both runs keep at least half of their window outside jump intervals (13 Oct addendum), and
  (2) |change| exceeds its noise, |drift_a| + |drift_b| (the 13 Oct rule), and
  (3) the same holds, with the same sign, for the window means and drifts without the jump intervals.
Otherwise it is "not resolved" (which bounds the change; it never means "equal"). Two sampling
standard errors (Cd_std / sqrt(cycles), combined) are reported alongside, as on 13 Oct.
Fair comparisons only: same mesh, maxCo, speed, Tu and window, unless the varied factor is named.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import section_lib as L  # noqa: E402

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 50)
pd.set_option("display.max_rows", 300)

TT_ALPHA = (150, 165, 180, 195, 210)
TT_U = (10.2, 23.0, 38.0)
CONVEX = (0.0, 1.48)        # s/c of the convex (outer) side, tip A outer corner to tip B (records' s)
CONCAVE = (1.60, 2.85)      # s/c of the concave side used for the base pressure (corners excluded)


def r4(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), 4)


def compare(a, b):
    """Change a - b of Cd (and Cl) with the comparison rule of the module docstring."""
    out = dict(case_a=a["name"], case_b=b["name"], Cd_a=a.Cd_mean, Cd_b=b.Cd_mean,
               dCd=a.Cd_mean - b.Cd_mean, dCd_pct=L.pct(a.Cd_mean, b.Cd_mean),
               noise=abs(a.Cd_drift) + abs(b.Cd_drift),
               two_se=2 * math.hypot(a.Cd_se, b.Cd_se),
               Cd_nj_a=a.Cd_nj, Cd_nj_b=b.Cd_nj, dCd_nj=a.Cd_nj - b.Cd_nj,
               dCd_nj_pct=L.pct(a.Cd_nj, b.Cd_nj), noise_nj=abs(a.Cd_drift_nj) + abs(b.Cd_drift_nj),
               share_a=a.nojump_share, share_b=b.nojump_share, jumps_a=int(a.jumps), jumps_b=int(b.jumps),
               dCl=a.Cl_mean - b.Cl_mean, noise_Cl=abs(a.Cl_drift) + abs(b.Cl_drift),
               St_a=a.St, St_b=b.St)
    usable = (a.nojump_share >= 0.5) and (b.nojump_share >= 0.5)
    ok_full = abs(out["dCd"]) > out["noise"]
    ok_nj = abs(out["dCd_nj"]) > out["noise_nj"] and np.sign(out["dCd_nj"]) == np.sign(out["dCd"])
    out["usable"] = bool(usable)
    out["resolved"] = bool(usable and ok_full and ok_nj)
    out["verdict"] = ("resolved" if out["resolved"] else
                      "not usable (jump-free share < 50 %)" if not usable else "not resolved")
    out["ratio_to_noise"] = abs(out["dCd"]) / out["noise"] if out["noise"] > 0 else float("inf")
    # solver-residual sensitivity: both runs start the first pressure solve above 0.05 in fewer than
    # half of their window's time steps (section_histories.py, residual share)
    out["pres_share_a"], out["pres_share_b"] = a.pres_share_win, b.pres_share_win
    out["quiet"] = bool(a.pres_share_win < 0.5 and b.pres_share_win < 0.5)
    out["Cl_resolved"] = bool(usable and abs(out["dCl"]) > out["noise_Cl"])
    return out


def surface_metrics(name):
    f = L.RECORDS / name / "fields" / "surface_mean.csv"
    if not f.exists():
        return dict(name=name, surface="missing")
    s = pd.read_csv(f, comment="#")
    s = s[s.patch == "blade"]
    sc, cp, cf = s.s_over_c.to_numpy(), s.Cp.to_numpy(), s.Cf.to_numpy()
    j = np.arange(len(sc))
    cvx = (sc >= CONVEX[0]) & (sc <= CONVEX[1])
    i0 = int(np.argmax(np.where(cvx, cp, -np.inf)))
    up = (j > i0) & (sc <= CONVEX[1])
    ipk = int(j[up][np.argmax(cf[up])])
    after = j[(j > ipk) & (sc <= CONVEX[1]) & (cf <= 0)]
    conc = (sc >= CONCAVE[0]) & (sc <= CONCAVE[1])
    return dict(name=name, surface="ok", s_stag=sc[i0], Cp_stag=cp[i0], Cf_peak_B=cf[ipk], s_Cf_peak_B=sc[ipk],
                s_sep_B=sc[after[0]] if after.size else np.nan,
                Cp_min_B=cp[(sc > sc[i0]) & (sc <= CONVEX[1])].min(), Cp_base=cp[conc].mean())


def main():
    d = L.load()
    J = pd.read_csv(L.OUT / "section_jumps.csv").set_index("name")
    H = json.loads((L.OUT / "section_histories.json").read_text())
    d = d.set_index("name", drop=False)
    for c in ("Cd_win_nojump_0.5", "jump_bins_win_0.5", "jump_bins_win_0.2", "jump_bins_win_0.1", "jump_max_win",
              "nojump_share", "Cd_nj", "Cl_nj", "Cd_drift_nj", "Cl_drift_nj", "Cd_last50", "Cd_last10",
              "Cl_last10", "Cl_std_last10", "pres_share_win", "pres_median_win", "dt_min_win", "log_note",
              "jump_first", "jump_last"):
        d[c] = J.loc[d.index, c]
    d["jumps"] = d["jump_bins_win_0.5"].astype(int)
    S = {"input": dict(table=str(L.TABLE.relative_to(L.REPO)), sha256=L.sha256(L.TABLE), n_cases=len(d),
                       n_new=int(d.new_15oct.sum()))}

    # ---------------------------------------------------------------- 1. health
    new, old = d[d.new_15oct], d[~d.new_15oct]
    rerun_names = [n for n in pd.read_csv(L.OUT_13OCT / "section_case_quality.csv").query("corrupted").name]
    rr_map = {}
    for n in rerun_names:
        cand = n + "_Co2.5n2"
        rr_map[n] = cand if cand in d.index else None
    rr = d.loc[[v for v in rr_map.values() if v]]
    S["health"] = dict(
        flagged_total=int(d.corrupted.sum()), flagged_new=int(new.corrupted.sum()),
        proxy_new=[r4(new.u_co_over_U.min()), r4(new.u_co_over_U.max())],
        proxy_healthy_13oct=[r4(old[~old.corrupted].u_co_over_U.min()), r4(old[~old.corrupted].u_co_over_U.max())],
        proxy_flagged_13oct=[r4(old[old.corrupted].u_co_over_U.min()), r4(old[old.corrupted].u_co_over_U.max())],
        symptom_without_flag=new[new.symptom_without_flag].name.tolist(),
        symptom_without_flag_detail={r.name: dict(Cd=r4(r.Cd_mean), Cd_std=r4(r.Cd_std), relstd=r4(r.Cd_relstd),
                                                  jumps=int(r.jumps), nojump_share=r4(r.nojump_share),
                                                  Cd_nj=r4(r.Cd_nj), pres_share=r4(r.pres_share_win))
                                     for r in new[new.symptom_without_flag].itertuples()},
        reruns=dict(n=len(rr_map), found=int(sum(v is not None for v in rr_map.values())),
                    existing_before_13oct=[v for v in rr_map.values() if v and v in old.index],
                    flagged=int(rr.corrupted.sum()), with_symptom=int(rr.any_symptom.sum()),
                    proxy=[r4(rr.u_co_over_U.min()), r4(rr.u_co_over_U.max())],
                    with_jumps=rr[rr.jumps > 0].name.tolist(),
                    jumps_detail={r.name: dict(jumps=int(r.jumps), Cd=r4(r.Cd_mean), Cd_nj=r4(r.Cd_nj))
                                  for r in rr[rr.jumps > 0].itertuples()},
                    pres_share=[r4(rr.pres_share_win.min()), r4(rr.pres_share_win.max())],
                    pres_share_gt_half=rr[rr.pres_share_win > 0.5].name.tolist(),
                    pres_share_max_others=r4(rr[rr.pres_share_win <= 0.5].pres_share_win.max())),
        new_pres_share_gt_half=new[new.pres_share_win > 0.5].name.tolist(),
        new_with_jumps={f"{x:g}": int((new[f"jump_bins_win_{x:g}"] > 0).sum()) for x in (0.5, 0.2, 0.1)},
        new_with_jumps_names=new[new.jumps > 0].name.tolist(),
        co125=new[new.maxCo == 1.25][["name", "u_co_over_U", "jumps", "jump_max_win", "pres_share_win",
                                      "any_symptom"]].to_dict(orient="records"),
        jumps_by_group={},
    )
    tt = d[d.new_15oct & (d.maxCo == 2.5) & d.alpha_deg.isin(TT_ALPHA)]
    for key, g in (("SST 10.2", tt[(tt.model == "SST") & (tt.U_ms == 10.2)]),
                   ("SST 23", tt[(tt.model == "SST") & (tt.U_ms == 23.0)]),
                   ("SST 38", tt[(tt.model == "SST") & (tt.U_ms == 38.0)]),
                   ("LM Tu0.5", tt[(tt.model == "LM") & (tt.Tu_body_pct == 0.5)]),
                   ("LM Tu1", tt[(tt.model == "LM") & (tt.Tu_body_pct == 1.0)]),
                   ("LM Tu3", tt[(tt.model == "LM") & (tt.Tu_body_pct == 3.0)])):
        S["health"]["jumps_by_group"][key] = dict(n=len(g), with_jumps=int((g.jumps > 0).sum()),
                                                  jump_intervals=[int(g.jumps.min()), int(g.jumps.max())],
                                                  pres_share=[r4(g.pres_share_win.min()), r4(g.pres_share_win.max())])
    # residual share: runs with and without jumps (healthy)
    hh = d[~d.corrupted & d.pres_share_win.notna()]
    S["health"]["pres_share"] = dict(
        healthy_no_change_over_0p1=[r4(hh[hh.jump_max_win <= 0.1].pres_share_win.min()),
                                    r4(hh[hh.jump_max_win <= 0.1].pres_share_win.max())],
        healthy_with_jumps=[r4(hh[hh.jumps > 0].pres_share_win.min()), r4(hh[hh.jumps > 0].pres_share_win.max())],
        flagged=[r4(d[d.corrupted].pres_share_win.min()), r4(d[d.corrupted].pres_share_win.max())],
        n_healthy_share_gt_0p01=int((hh.pres_share_win > 0.01).sum()),
        logs_partial=d[d.log_note.fillna("").str.len() > 0].name.tolist())
    cols = ["name", "new_15oct", "alpha_deg", "U_ms", "model", "level", "maxCo", "Tu_body_pct", "ran_on", "n_cells",
            "Cd_mean", "Cd_std", "Cl_mean", "Cl_std", "Cm_mean", "Cd_pressure_mean", "Cd_viscous_mean", "St",
            "St_peak_frac", "St_status", "n_cycles_avg", "Cd_drift", "Cd_drift_rel", "Cd_se", "dt_mean_s", "dt_conv",
            "u_co_over_U", "yplus_max_mean", "yplus_max_max", "n_steps", "neg_drag", "std_gt_mean", "cl_gt3",
            "yplus_spike", "any_symptom", "corrupted", "symptom_without_flag", "jumps", "jump_bins_win_0.2",
            "jump_bins_win_0.1", "jump_max_win", "nojump_share", "Cd_nj", "Cd_drift_nj", "Cd_last50", "Cd_last10",
            "pres_share_win", "pres_median_win", "branch_a0"]
    d.sort_values(["alpha_deg", "model", "level_i", "maxCo", "U_ms", "Tu_body_pct"])[cols].to_csv(
        L.OUT / "section_case_quality.csv", index=False, float_format="%.6g")
    print("== 1. Health")
    print(json.dumps(S["health"], indent=1, default=str)[:4000])

    # ---------------------------------------------------------------- 2. time step
    rows, chg = [], []
    for a in (0, 180):
        for mdl in ("SST", "LM"):
            g = d[(d.alpha_deg == a) & (d.model == mdl) & (d.level == "medium") & (d.U_ms == 23.0) &
                  (d.Tu_body_pct == 1.0)].sort_values("maxCo", ascending=False)
            for r in g.itertuples():
                rows.append(dict(alpha=a, model=mdl, maxCo=r.maxCo, case=r.name, ran_on=r.ran_on, flagged=r.corrupted,
                                 Cd=r.Cd_mean, Cd_std=r.Cd_std, Cd_drift=r.Cd_drift, Cd_nj=r.Cd_nj, jumps=r.jumps,
                                 Cd_last10=r.Cd_last10, Cl=r.Cl_mean, Cl_std=r.Cl_std, Cl_last10=r.Cl_last10,
                                 Cl_std_last10=r.Cl_std_last10, St=r.St, St_peak_frac=r.St_peak_frac,
                                 St_status=r.St_status, n_cycles=r.n_cycles_avg, state=r.branch_a0,
                                 drift_rel_pct=100 * r.Cd_drift_rel, pres_share=r.pres_share_win, steps=r.n_steps))
            hg = g[~g.corrupted]
            for (c1, c2) in ((2.5, 5.0), (1.25, 2.5), (1.25, 5.0)):
                if {c1, c2} <= set(hg.maxCo):
                    x = compare(hg[hg.maxCo == c1].iloc[0], hg[hg.maxCo == c2].iloc[0])
                    x.update(alpha=a, model=mdl, maxCo_a=c1, maxCo_b=c2)
                    chg.append(x)
    TS = pd.DataFrame(rows)
    TS.to_csv(L.OUT / "section_timestep.csv", index=False, float_format="%.6g")
    TC = pd.DataFrame(chg)
    TC.to_csv(L.OUT / "section_timestep_changes.csv", index=False, float_format="%.6g")
    S["timestep"] = dict(runs=[{k: (r4(v) if isinstance(v, (float, np.floating)) else v) for k, v in r.items()}
                               for r in rows],
                         changes=[dict(alpha=x["alpha"], model=x["model"], maxCo=f"{x['maxCo_a']:g} vs {x['maxCo_b']:g}",
                                       dCd=r4(x["dCd"]), dCd_pct=round(x["dCd_pct"], 2), noise=r4(x["noise"]),
                                       dCd_nj_pct=round(x["dCd_nj_pct"], 2), verdict=x["verdict"],
                                       dCl=r4(x["dCl"])) for x in chg],
                         histories={k: v for k, v in H.items() if k in (
                             "restart_b_growth", "decay_co125", "restart_a_cycles", "unity_repeat")},
                         restart_a=H["a000.0_U23.0_SST_medium_Tu1.0"]["restart"],
                         restart_b=H["a000.0_U23.0_SST_medium_Tu1.0_Co2.5n2"]["restart"],
                         a0_states={n: {k: H[n].get(k) for k in ("state_last50", "Cd_last50", "t_enter", "t_settle5",
                                                                 "t_last_cross_2p5", "Cd_last10", "Cl_last10")}
                                    for n in H if n.startswith("a000.0")})
    print("\n== 2. Time step (alpha 0 and 180, medium, 23 m/s, Tu 1 %)")
    print(TS[["alpha", "model", "maxCo", "ran_on", "flagged", "Cd", "Cd_nj", "Cd_last10", "Cd_drift", "jumps", "Cl",
              "Cl_last10", "Cl_std", "St", "St_status", "state", "pres_share"]].to_string(
        index=False, float_format=lambda v: f"{v:.4g}"))
    print(TC[["alpha", "model", "maxCo_a", "maxCo_b", "dCd", "dCd_pct", "noise", "dCd_nj_pct", "verdict", "dCl"]].to_string(
        index=False, float_format=lambda v: f"{v:.4g}"))

    # ---------------------------------------------------------------- 3. LM polar, 23 m/s
    pol = d[(d.model == "LM") & (d.U_ms == 23.0) & (d.Tu_body_pct == 1.0) & (d.level == "medium")].copy()
    pol["used"] = ~pol.corrupted
    pol["not_stationary"] = pol.Cd_drift.abs() > 0.2 * pol.Cd_mean.abs()
    pol = pol.sort_values(["alpha_deg", "maxCo"])
    pcols = ["name", "alpha_deg", "maxCo", "used", "corrupted", "Cd_mean", "Cd_std", "Cd_nj", "jumps", "Cl_mean",
             "Cl_std", "Cm_mean", "St", "St_peak_frac", "St_status", "Cd_drift_rel", "not_stationary", "n_cycles_avg",
             "Cd_last10", "branch_a0", "u_co_over_U", "pres_share_win"]
    pol[pcols].to_csv(L.OUT / "section_polar_LM23.csv", index=False, float_format="%.6g")
    hp = pol[pol.used]
    S["polar"] = dict(
        healthy_by_maxCo={f"{c:g}": hp[hp.maxCo == c].alpha_deg.astype(int).tolist() for c in (5.0, 2.5, 1.25)},
        replaced_flagged=pol[pol.corrupted].alpha_deg.astype(int).tolist(),
        points={f"{int(r.alpha_deg)} maxCo {r.maxCo:g}": dict(Cd=r4(r.Cd_mean), Cl=r4(r.Cl_mean), Cm=r4(r.Cm_mean),
                                                              St=r4(r.St), St_status=r.St_status, jumps=int(r.jumps),
                                                              Cd_nj=r4(r.Cd_nj), drift_rel=r4(r.Cd_drift_rel),
                                                              not_stationary=bool(r.not_stationary),
                                                              state=r.branch_a0)
                for r in hp.itertuples()},
        steady=hp[hp.St_status.str.startswith("steady")].alpha_deg.astype(int).tolist(),
        not_stationary=[f"{int(r.alpha_deg)} maxCo {r.maxCo:g}" for r in hp[hp.not_stationary].itertuples()],
        jumps_gt10=[f"{int(r.alpha_deg)} maxCo {r.maxCo:g}: {int(r.jumps)}" for r in hp[hp.jumps > 10].itertuples()],
        Cd_range_75_255=[r4(hp[hp.alpha_deg.between(75, 255) & (hp.maxCo == 2.5)].Cd_mean.min()),
                         r4(hp[hp.alpha_deg.between(75, 255) & (hp.maxCo == 2.5)].Cd_mean.max())],
    )
    print("\n== 3. LM polar, 23 m/s, healthy runs")
    print(hp[["alpha_deg", "maxCo", "Cd_mean", "Cd_nj", "jumps", "Cl_mean", "Cm_mean", "St", "St_status",
              "Cd_drift_rel", "not_stationary", "branch_a0"]].to_string(index=False, float_format=lambda v: f"{v:.4g}"))

    # ---------------------------------------------------------------- 4. transition test
    t2 = d[(d.level == "medium") & (d.maxCo == 2.5) & d.alpha_deg.isin(TT_ALPHA) & d.U_ms.isin(TT_U)]
    prs = []
    for a in TT_ALPHA:
        for U in TT_U:
            s = t2[(t2.alpha_deg == a) & (t2.U_ms == U) & (t2.model == "SST") & (t2.Tu_body_pct == 1.0)]
            lm = t2[(t2.alpha_deg == a) & (t2.U_ms == U) & (t2.model == "LM") & (t2.Tu_body_pct == 1.0)]
            if len(s) == 1 and len(lm) == 1:
                x = compare(lm.iloc[0], s.iloc[0])
                x.update(alpha=a, U=U, maxCo=2.5, Cl_LM=lm.iloc[0].Cl_mean, Cl_SST=s.iloc[0].Cl_mean,
                         Cl_std_LM=lm.iloc[0].Cl_std, Cl_std_SST=s.iloc[0].Cl_std)
                prs.append(x)
    # the same pair at maxCo 1.25 (alpha 180, 23 m/s)
    s125 = L.one(d, alpha_deg=180, U_ms=23.0, model="SST", level="medium", maxCo=1.25)
    l125 = L.one(d, alpha_deg=180, U_ms=23.0, model="LM", level="medium", maxCo=1.25)
    x = compare(l125, s125)
    x.update(alpha=180, U=23.0, maxCo=1.25, Cl_LM=l125.Cl_mean, Cl_SST=s125.Cl_mean, Cl_std_LM=l125.Cl_std,
             Cl_std_SST=s125.Cl_std)
    prs.append(x)
    PR = pd.DataFrame(prs)
    PR.to_csv(L.OUT / "section_transition_pairs.csv", index=False, float_format="%.6g")
    tus = []
    for a in TT_ALPHA:
        for U in TT_U:
            g = t2[(t2.alpha_deg == a) & (t2.U_ms == U) & (t2.model == "LM")].set_index("Tu_body_pct")
            for tu in (0.5, 3.0):
                if tu in g.index and 1.0 in g.index:
                    x = compare(g.loc[tu], g.loc[1.0])
                    x.update(alpha=a, U=U, Tu=tu)
                    tus.append(x)
    TU = pd.DataFrame(tus)
    TU.to_csv(L.OUT / "section_transition_tu.csv", index=False, float_format="%.6g")
    sps = []
    for a in TT_ALPHA:
        for mdl, tu in (("SST", 1.0), ("LM", 0.5), ("LM", 1.0), ("LM", 3.0)):
            g = t2[(t2.alpha_deg == a) & (t2.model == mdl) & (t2.Tu_body_pct == tu)].set_index("U_ms")
            for U in (10.2, 38.0):
                if U in g.index and 23.0 in g.index:
                    x = compare(g.loc[U], g.loc[23.0])
                    x.update(alpha=a, model=mdl, Tu=tu, U=U)
                    sps.append(x)
    SP = pd.DataFrame(sps)
    SP.to_csv(L.OUT / "section_transition_speed.csv", index=False, float_format="%.6g")
    srf = pd.DataFrame([surface_metrics(n) for n in t2.name.tolist() + [s125["name"], l125["name"]]])
    srf = srf.merge(d[["name", "alpha_deg", "U_ms", "model", "Tu_body_pct", "maxCo", "Cd_mean", "Cl_std"]].reset_index(
        drop=True), on="name")
    srf.to_csv(L.OUT / "section_transition_surface.csv", index=False, float_format="%.6g")

    def tbl(df, keys):
        return [{k: (r4(v) if isinstance(v, (float, np.floating)) else v) for k, v in r.items() if k in keys}
                for r in df.to_dict(orient="records")]
    keys = ["alpha", "U", "maxCo", "Tu", "model", "case_a", "case_b", "Cd_a", "Cd_b", "dCd", "dCd_pct", "noise",
            "two_se", "dCd_nj", "dCd_nj_pct", "noise_nj", "jumps_a", "jumps_b", "share_a", "share_b", "verdict",
            "ratio_to_noise", "dCl", "noise_Cl", "Cl_resolved", "St_a", "St_b", "Cl_LM", "Cl_SST", "Cl_std_LM",
            "Cl_std_SST", "pres_share_a", "pres_share_b", "quiet", "resolved"]
    P25 = PR[PR.maxCo == 2.5]
    S["transition"] = dict(
        pairs=tbl(PR, keys), tu=tbl(TU, keys), speed=tbl(SP, keys),
        surface=tbl(srf, list(srf.columns)),
        lm_below_sst={f"{U:g}": dict(n=int((P25[P25.U == U].dCd < 0).sum()), of=int((P25.U == U).sum()),
                                     resolved_below=int(((P25.U == U) & (P25.dCd < 0) & P25.resolved).sum()),
                                     resolved_above=int(((P25.U == U) & (P25.dCd > 0) & P25.resolved).sum()),
                                     pct=[r4(P25[P25.U == U].dCd_pct.min()), r4(P25[P25.U == U].dCd_pct.max())])
                      for U in TT_U},
        tu_a180={f"{U:g}": {f"{tu:g}": r4(L.one(t2, alpha_deg=180, U_ms=U, model="LM", Tu_body_pct=tu).Cd_mean)
                            for tu in (0.5, 1.0, 3.0)} for U in TT_U},
        sst_a180={f"{U:g}": r4(L.one(t2, alpha_deg=180, U_ms=U, model="SST").Cd_mean) for U in TT_U},
    )
    print("\n== 4a. LM against SST (Tu 1 %), maxCo 2.5 (and 1.25 at alpha 180, 23 m/s)")
    print(PR[["alpha", "U", "maxCo", "Cd_a", "Cd_b", "dCd", "dCd_pct", "noise", "two_se", "dCd_nj_pct", "jumps_a",
              "jumps_b", "share_a", "share_b", "pres_share_a", "pres_share_b", "verdict", "quiet", "dCl",
              "Cl_resolved"]].to_string(
        index=False, float_format=lambda v: f"{v:.4g}"))
    print("\n== 4b. LM, Tu 0.5 and 3 % against Tu 1 %")
    print(TU[["alpha", "U", "Tu", "Cd_a", "Cd_b", "dCd", "dCd_pct", "noise", "dCd_nj_pct", "jumps_a", "share_a",
              "pres_share_a", "pres_share_b", "verdict", "quiet"]].to_string(index=False, float_format=lambda v: f"{v:.4g}"))
    print("\n== 4c. 10.2 and 38 m/s against 23 m/s")
    print(SP[["alpha", "model", "Tu", "U", "Cd_a", "Cd_b", "dCd", "dCd_pct", "noise", "dCd_nj_pct", "verdict",
              "quiet"]].to_string(
        index=False, float_format=lambda v: f"{v:.4g}"))
    print("\n== 4d. Wall distributions (time-mean)")
    print(srf.sort_values(["alpha_deg", "U_ms", "model", "Tu_body_pct", "maxCo"]).to_string(
        index=False, float_format=lambda v: f"{v:.4g}"))

    with open(L.OUT / "section_summary.json", "w") as f:
        json.dump(S, f, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print("\nwrote", *(p.name for p in sorted(L.OUT.glob("section_*"))))


if __name__ == "__main__":
    main()
