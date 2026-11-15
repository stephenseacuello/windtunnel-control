#!/usr/bin/env python3
"""Boundary layers of the smooth low-Re single-blade runs, 15 Nov 2026 (2D URANS, time means), and the roughness
numbers they give: Ks+, Ks/delta99, t/delta99 and Re_k for the roughness heights the report uses.

    nice -n 10 python3 cfd/analysis/2026-11-15/src/bl_ks_tables.py           # about 20 s, 4 processes

Why
  Dr. Jahangiri's 1 Nov question J4: why the CFD gain appears at Ks 400 um but is inconclusive near the printed
  roughness. Until now Ks+ came from wall-function runs (blade means, cfd/stage2/results/stage2_polars.csv and
  cfd/rotor2d/results/rotor_cp.csv) and Re_k from the upper bound u_k = U (cfd/analysis/2026-10-13/RESULTS.md
  section 3.4). This script measures the smooth-wall boundary layer itself, on the low-Re meshes (first cell
  4.5 um, y+ < 1), at stations along the attached part of the wall, and places each roughness height in it.
  Existing runs only: the verification runs of 15 Nov (B1) have not finished.

Reads (read only)
  cfd/section2d/runs/a{000,090,180}.0_U23.0_SST_medium_Tu1.0_Co{2.5,1.25}n2/ (5 runs) and every complete
      cfd/stage2/runs/a*_tex0.000_* run (12: SST and LM, alpha 0 and 180, 18.8-25.2 m/s, maxCo 2.5 and 5):
      constant/polyMesh/*, <final time>/{UMean,pMean,wallShearStressMean}, case.json, mesh_info.json,
      results.json (yplus_blade_mean for Stage 2, yplus_mean_mean for Stage 1; checks only)
  ./surface_extract.py                   imported: mesh, wall loop, sampler, stagnation point and first
                                         separation on each branch (the same rules as surface_summary.csv)
  cfd/stage2/runs/a{000,090,180}.0_U23.0_SST_wf_Ks{0,100,400}_Tu1.0_Co2.5n2/ (9 wall-function runs; checks and
      comparison only): the same fields, <final time>/wallShearStress and postProcessing/yPlus1/*/yPlus.dat; every
      run above also gives its final-time wallShearStress and yPlus.dat (checks only)
  cfd/stage2/results/stage2_polars.csv   yplus_blade_mean, ksplus_blade_mean, yP_m (checks and comparison only)
  cfd/rotor2d/results/rotor_cp.csv       ksplus_blade_mean of the rough rotor runs (comparison only)
Writes
  ../out/bl_stations.csv     every station (every 5 mm of arc from tip A on the convex and concave faces): region,
                             distance from the stagnation point, wall Cp, tau_w, u_tau, y1+, edge velocity and
                             total pressure, delta99, delta*, theta, H, Re_theta, delta99+
  ../out/bl_ks_tables.csv    per run and face (and both faces pooled), for each roughness height: number of
                             attached stations, h+ = h u_tau/nu, h/delta99, u_k/U_e and Re_k = u_k h/nu (median,
                             minimum, maximum), the 2D and 3D transition criteria and where the median falls
  ../out/bl_utau_check.csv   kind 'validation': the wall-mean y+ from this script's reading of the final-time wall
                             shear and wall distance against the run's own y+ function object at the same instant
                             (16 low-Re and 9 wall-function runs; the script exits 1 if one is off by more than 2 %);
                             'diagnostic': the same from the time-mean shear against the window means (the runs'
                             tables), which differ by the shear's unsteadiness; 'comparison': this script's u_tau
                             against the repo's Ks+ (rotor and static wall-function runs), with the reasons they
                             differ in 'note'
  ../fig/bl_ks_tables.png    delta99 and u_tau along the windward face (SST, maxCo 2.5), and Ks+ and Re_k
                             against roughness height with the transition criteria

Conventions
  Wall, faces, s/c, loop, stagnation point, branches A and B and the first separation (S) on each branch: as
  surface_extract.py (the Cf reversal basis: these walls are smooth). Stations: s = 5, 10, 15 ... mm from tip A on
  the convex and concave faces. Region 'primary': on a branch between the stagnation point and its first S, at
  least 2 mm from the stagnation point and from a corner and 1 mm upstream of the S; 'other attached': the 1-mm Cf
  has the attached sign elsewhere (reattached flow, or a wake recirculation that runs away from the stagnation
  point); 'reversed': the rest. Profiles are computed at primary and other-attached stations; the tables use the
  primary stations only.
  Profile: along the smooth-wall normal of the station's face, d = 0 and 260 heights from 0.5 um to 6 mm
  (geometric); UMean and pMean interpolated linearly (Delaunay triangulation of the cell centres within 8 mm of the
  wall and the wall-face centres, where U = 0 and p = the wall pMean). u = UMean . t_ds (t_ds: the wall tangent
  pointing away from the stagnation point), v = UMean . n.
  Edge: the total-pressure method of Griffin, Fu and Moin (2021, Phys. Rev. Fluids 6, 024608; from memory, not
  re-checked): local inviscid velocity U_I(d) = sqrt(2 (P0 - p(d)) - v(d)^2), P0 the largest p + |U|^2/2 on the
  line (the time-mean total pressure above the attached layer is 1.01-1.06 q, not q: P0_over_q), delta99 the
  first d with u/U_I >= 0.99 (linear between samples), U_e = U_I(delta99). delta* = int_0^delta99 (1 - u/U_I) dd,
  theta = int_0^delta99 (u/U_I)(1 - u/U_I) dd (U_I inside the integrals follows the wall-normal change of the
  inviscid velocity on the curved wall), H = delta*/theta, Re_theta = U_e theta/nu. delta99 is flagged ill
  conditioned (d99_ok false) where U_e < 0.3 U: there a 0.1 % q change in P0 moves the 99 % point by tenths of a mm;
  the h/delta99 statistics use d99_ok stations only.
  Wall shear: tau_w = |wallShearStressMean . t_ds| (kinematic), u_tau = sqrt(tau_w); y1+ = y_P u_tau/nu with y_P the
  owner-cell centre's distance from the wall face.
  Roughness heights: Ks = 25, 38, 50, 90, 100, 200, 211, 400, 422 um (the report's sand-grain values:
  cfd/docs/ROUGHNESS_KS.md, 2.09 t for FS 0.05-0.20) and the FS amplitudes t = 0.025, 0.05, 0.10, 0.20, 0.40,
  0.805 mm. h+ = h u_tau/nu uses the smooth wall's u_tau (a rough wall raises it: the 'note' column of
  bl_utau_check.csv). u_k = u(h) on the smooth-wall profile; Re_k = u_k h/nu.
  Transition criteria (cfd/docs/ROUGHNESS_KS.md section 5, after the 7 Oct meeting notes; literature values from
  memory): 2D roughness, onset Re_k 40-260; isolated 3D roughness, critical Re_k 600-900 (h/d)^0.4 with the element
  width d taken as the fuzzy-skin point distance, 0.2 mm (assumed; d = 0.1 mm, one layer, raises it 1.32 times).
  nu = 1.516e-5 m^2/s (case.json).
"""
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import surface_extract as SE  # noqa: E402

ROOT, REPO = SE.ROOT, SE.REPO
OUT, FIG = SE.OUT, SE.FIG
NU, C_REF = SE.NU, SE.C_REF
STATION_DS = 5e-3
STAG_GUARD, CORNER_GUARD, SEP_GUARD = 2e-3, 2e-3, 1e-3
HEIGHTS = np.r_[0.0, np.geomspace(0.5e-6, 6e-3, 260)]
BAND = 8e-3
UE_MIN = 0.3
KS_UM = (25, 38, 50, 90, 100, 200, 211, 400, 422)
T_MM = (0.025, 0.05, 0.10, 0.20, 0.40, 0.805)
CRIT_2D = (40.0, 260.0)
CRIT_3D = (600.0, 900.0)
D_ELEMENT = 0.2e-3


def fo_yplus_last(d, patch):
    """(time, patch average) of the y+ function object's last sample for one patch."""
    rows = []
    for f in sorted((Path(d) / "postProcessing" / "yPlus1").glob("*/yPlus.dat")):
        for line in f.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                v = line.split()
                if v[1] == patch:
                    rows.append((float(v[0]), float(v[4])))
    return max(rows)


def wall_yplus(M, W, G, C, tau, faces):
    """y+ = y_P |tau_w|^0.5 / nu on the given faces: y_P the owner-cell centre's distance from the face plane,
    tau the {patch: values} wall shear."""
    out = []
    for f in faces:
        own = M["owner"][W[f]["g"]]
        yP = np.abs(np.sum((C[own] - G[f]["cen"]) * G[f]["nin"], axis=1))
        t = np.array([tau[pa][i] for pa, i in zip(W[f]["patch"], W[f]["pidx"])])
        out.append(yP * np.sqrt(np.linalg.norm(t, axis=1)) / NU)
    return np.concatenate(out)


def inst_check(d, M, W, G, C, T, stage):
    """Final-time y+ from the instantaneous wallShearStress field against the function object's last sample."""
    patches = {p for f in SE.FACES for p in W[f]["patch"]}
    tau = {pa: SE.RS.patch_values(T / "wallShearStress", pa, 3)[:, :2] for pa in patches}
    faces = ("convex", "concave") if stage == 2 else SE.FACES        # the FO's patch 'blade'
    t_fo, y_fo = fo_yplus_last(d, "blade")
    mine = float(wall_yplus(M, W, G, C, tau, faces).mean())
    return dict(t_fo=t_fo, t_field=float(T.name), yplus_fo_last=y_fo, yplus_inst_fields=mine)


def bl_cases():
    out = []
    for c in SE.discover():
        P = json.loads((Path(c["dir"]) / "case.json").read_text())
        if c["stage"] == 1 or (P.get("wall") == "tex" and P["texT"] == 0):
            out.append(c)
    return out


def profile_params(u, v, p, d):
    """Edge and integral thicknesses of one wall-normal profile (arrays over heights d, d[0] = 0)."""
    P0 = np.nanmax(p + 0.5 * (u ** 2 + v ** 2))
    UI = np.sqrt(np.maximum(0.0, 2 * (P0 - p) - v ** 2))
    r = np.divide(u, UI, out=np.full_like(u, np.nan), where=UI > 0)
    hit = np.where(r[1:] >= 0.99)[0]
    res = dict(P0=P0, d99=np.nan, Ue=np.nan, dstar=np.nan, theta=np.nan)
    if not len(hit):
        return res, r, UI
    j = hit[0] + 1
    f = (0.99 - r[j - 1]) / (r[j] - r[j - 1]) if np.isfinite(r[j - 1]) else 0.0
    d99 = d[j - 1] + f * (d[j] - d[j - 1])
    rr = np.r_[np.nan_to_num(r[:j], nan=0.0), 0.99]
    dd = np.r_[d[:j], d99]
    res.update(d99=d99, Ue=float(np.interp(d99, d, UI)), dstar=float(np.trapezoid(1 - rr, dd)),
               theta=float(np.trapezoid(rr * (1 - rr), dd)))
    return res, r, UI


def analyse(case):
    name = case["name"]
    row, prof, _, _ = SE.analyse(case)                    # stagnation point and first separations (surface rules)
    d = Path(case["dir"])
    P = json.loads((d / "case.json").read_text())
    R = json.loads((d / "results.json").read_text())
    corners = json.loads((d / "mesh_info.json").read_text())["frame"]["corners_body_m"]
    T = SE.final_time(d, P)
    U = P["Uinf"]
    M = SE.load_mesh(d)
    W = SE.wall_loop(M, corners)
    G = SE.face_frames(M, W)
    C = SE.cell_centres(M)
    Um = SE.RS.internal_values(T / "UMean", 3)[:, :2]
    pm = SE.RS.internal_values(T / "pMean", 1)
    pat = {pa: (SE.RS.patch_values(T / "pMean", pa, 1), SE.RS.patch_values(T / "wallShearStressMean", pa, 3)[:, :2])
           for pa in {p for f in SE.FACES for p in W[f]["patch"]}}
    pw = {f: np.array([pat[pa][0][i] for pa, i in zip(W[f]["patch"], W[f]["pidx"])]) for f in SE.FACES}
    tw = {f: np.array([pat[pa][1][i] for pa, i in zip(W[f]["patch"], W[f]["pidx"])]) for f in SE.FACES}
    pwall = np.concatenate([pw[f] for f in SE.FACES])                  # wall faces in SE.FACES order, as the sampler
    samp = SE.wall_sampler(C, np.c_[Um, pm], G, wall_values=np.c_[np.zeros((len(pwall), 2)), pwall], band=BAND)
    # loop bookkeeping (as surface_extract)
    offs, acc = {}, 0.0
    for f in SE.FACES:
        offs[f] = acc
        acc += G[f]["L"]
    Ltot = acc
    l0 = row["stag_loop_over_c"] * C_REF
    plus_is = {"convex": "B", "endB": "B", "concave": "A", "endA": "B"}[row["stag_face"]]
    firstS = {br: row[f"first_S_{br}_from_stag_over_c"] * C_REF for br in ("A", "B")}
    Pf = {f: prof[prof.face == f].reset_index(drop=True) for f in SE.FACES}

    # wall-mean y+ from the time-mean wall shear (against the window mean of the y+ function object), and the
    # final-time check (instantaneous field against the function object's last sample)
    faces_fo = ("convex", "concave") if case["stage"] == 2 else SE.FACES
    tw_patch = {pa: pat[pa][1] for pa in pat}
    chk = dict(name=name, stage=case["stage"], model=row["model"], alpha_deg=row["alpha_deg"], U=U, maxCo=row["maxCo"],
               yplus_mean_fields=float(wall_yplus(M, W, G, C, tw_patch, faces_fo).mean()),
               yplus_table=float(R["yplus_blade_mean"] if case["stage"] == 2 else R["yplus_mean_mean"]),
               yplus_table_source=("results.json yplus_blade_mean (painted faces)" if case["stage"] == 2
                                   else "results.json yplus_mean_mean (whole wall)"),
               utau_painted_mean=float(np.concatenate([np.sqrt(np.linalg.norm(tw[f], axis=1))
                                                       for f in ("convex", "concave")]).mean()))
    chk.update(inst_check(d, M, W, G, C, T, case["stage"]))

    stations, heights = [], []
    for f in ("convex", "concave"):
        s = G[f]["s"]
        for k, s_st in enumerate(np.arange(STATION_DS, G[f]["L"], STATION_DS)):
            i = int(np.argmin(np.abs(s - s_st)))
            lpos = offs[f] + (s[i] if SE.LOOP_DIR[f] > 0 else G[f]["L"] - s[i])
            dplus = (lpos - l0) % Ltot
            sign_loop, br, dist = (1, plus_is, dplus) if dplus <= Ltot / 2 else (-1, "B" if plus_is == "A" else "A",
                                                                                   Ltot - dplus)
            t_ds = G[f]["tng"][i] * SE.LOOP_DIR[f] * sign_loop          # away from the stagnation point
            cf1 = Pf[f].Cf_1mm.iloc[i] * SE.LOOP_DIR[f] * sign_loop      # > 0: attached
            near_corner = min(s[i], G[f]["L"] - s[i]) < CORNER_GUARD
            before_S = (dist <= firstS[br] - SEP_GUARD) if np.isfinite(firstS[br]) else (f == row["stag_face"])
            if not near_corner and dist >= STAG_GUARD and before_S:
                region = "primary"
            elif cf1 > 0 and not near_corner and dist >= STAG_GUARD:
                region = "other attached"
            else:
                region = "near corner" if near_corner else ("near stagnation" if dist < STAG_GUARD else "reversed")
            st = dict(name=name, model=row["model"], alpha_deg=row["alpha_deg"], U=U, maxCo=row["maxCo"],
                      nconv=row["nconv"], face=f, s_mm=s[i] * 1e3, s_over_c=s[i] / C_REF, branch=br,
                      from_stag_mm=dist * 1e3, region=region, Cp_wall=pw[f][i] / (0.5 * U ** 2),
                      Cf_1mm_attached_sign=cf1)
            if region in ("primary", "other attached"):
                X = G[f]["cen"][i] + HEIGHTS[:, None] * G[f]["nin"][i]
                V = samp(X)
                u, v, p = V[:, :2] @ t_ds, V[:, :2] @ G[f]["nin"][i], V[:, 2]
                res, r, UI = profile_params(u, v, p, HEIGHTS)
                tau = abs(float(tw[f][i] @ t_ds))
                ut = np.sqrt(tau)
                own = M["owner"][W[f]["g"][i]]
                y1 = abs(float((C[own] - G[f]["cen"][i]) @ G[f]["nin"][i]))
                st.update(tau_w=tau, u_tau=ut, y1_plus=y1 * ut / NU,
                          grad_check=NU * u[1] / HEIGHTS[1] / tau if tau > 0 else np.nan,
                          P0_over_q=res["P0"] / (0.5 * U ** 2), Ue_over_U=res["Ue"] / U, d99_mm=res["d99"] * 1e3,
                          dstar_mm=res["dstar"] * 1e3, theta_mm=res["theta"] * 1e3, H=res["dstar"] / res["theta"],
                          Re_theta=res["Ue"] * res["theta"] / NU, d99_plus=res["d99"] * ut / NU,
                          d99_ok=bool(np.isfinite(res["d99"]) and res["Ue"] >= UE_MIN * U and res["d99"] < 3e-3),
                          u_min_below_d99_over_U=float(np.nanmin(u[1:][HEIGHTS[1:] <= res["d99"]]) / U)
                          if np.isfinite(res["d99"]) else np.nan)
                if region == "primary":
                    for kind, hs in (("Ks", [h * 1e-6 for h in KS_UM]), ("t", [h * 1e-3 for h in T_MM])):
                        for h in hs:
                            uk = float(np.interp(h, HEIGHTS, u))
                            heights.append(dict(name=name, face=f, s_mm=s[i] * 1e3, kind=kind, h_um=round(h * 1e6, 3),
                                                hplus=h * ut / NU,
                                                h_over_d99=h / res["d99"] if st["d99_ok"] else np.nan,
                                                uk_over_Ue=uk / res["Ue"] if np.isfinite(res["Ue"]) else np.nan,
                                                Re_k=uk * h / NU))
            stations.append(st)
    return stations, heights, chk


def tables(ST, HT):
    rows = []
    meta = ST.groupby("name").first()[["model", "alpha_deg", "U", "maxCo", "nconv"]]
    for (name, face), g in pd.concat([HT, HT.assign(face="both")]).groupby(["name", "face"], sort=False):
        for (kind, h), gg in g.groupby(["kind", "h_um"], sort=False):
            m = meta.loc[name]
            hd = gg.h_over_d99.dropna()
            med = float(gg.Re_k.median())
            c3 = (CRIT_3D[0] * (h * 1e-6 / D_ELEMENT) ** 0.4, CRIT_3D[1] * (h * 1e-6 / D_ELEMENT) ** 0.4)
            rows.append(dict(name=name, model=m.model, alpha_deg=m.alpha_deg, U=m.U, maxCo=m.maxCo, nconv=m.nconv,
                             face=face, kind=kind, h_um=h, n_stations=len(gg),
                             hplus_median=gg.hplus.median(), hplus_min=gg.hplus.min(), hplus_max=gg.hplus.max(),
                             n_d99=len(hd), h_over_d99_median=hd.median() if len(hd) else np.nan,
                             h_over_d99_min=hd.min() if len(hd) else np.nan,
                             h_over_d99_max=hd.max() if len(hd) else np.nan,
                             uk_over_Ue_median=gg.uk_over_Ue.median(),
                             Re_k_median=med, Re_k_min=gg.Re_k.min(), Re_k_max=gg.Re_k.max(),
                             crit2D_lo=CRIT_2D[0], crit2D_hi=CRIT_2D[1], crit3D_lo=c3[0], crit3D_hi=c3[1],
                             frac_Re_k_ge_crit2D_lo=float((gg.Re_k >= CRIT_2D[0]).mean()),
                             frac_Re_k_ge_crit3D_lo=float((gg.Re_k >= c3[0]).mean()),
                             median_vs_2D=("below onset" if med < CRIT_2D[0] else "in onset range" if med <= CRIT_2D[1]
                                           else "above range"),
                             median_vs_3D=("below" if med < c3[0] else "in range" if med <= c3[1] else "above")))
    return pd.DataFrame(rows)


def checks(CK, ST):
    """bl_utau_check.csv: validation (instantaneous y+), diagnostics (time-mean y+, wall-function Ks+) and the
    comparison of u_tau with the repo's Ks+."""
    rows = []
    pol = pd.read_csv(REPO / "cfd" / "stage2" / "results" / "stage2_polars.csv").set_index("name")
    wf = []
    for a in (0, 90, 180):
        for ks in (0, 100, 400):
            n = f"a{a:05.1f}_U23.0_SST_wf_Ks{ks}_Tu1.0_Co2.5n2"
            d = SE.S2_RUNS / n
            P = json.loads((d / "case.json").read_text())
            corners = json.loads((d / "mesh_info.json").read_text())["frame"]["corners_body_m"]
            T = SE.final_time(d, P)
            M = SE.load_mesh(d)
            W = SE.wall_loop(M, corners)
            G = SE.face_frames(M, W)
            C = SE.cell_centres(M)
            tau = {"blade": SE.RS.patch_values(T / "wallShearStressMean", "blade", 3)[:, :2]}
            r = dict(name=n, stage=2, alpha_deg=float(a), Ks_um=float(ks), yP_nominal=P["yP"],
                     yplus_mean_fields=float(wall_yplus(M, W, G, C, tau, ("convex", "concave")).mean()),
                     yplus_table=float(pol.loc[n, "yplus_blade_mean"]),
                     ksplus_table=float(pol.loc[n, "ksplus_blade_mean"]))
            r.update(inst_check(d, M, W, G, C, T, 2))
            wf.append(r)
    for r in list(CK.to_dict("records")) + wf:
        ratio = r["yplus_inst_fields"] / r["yplus_fo_last"]
        rows.append(dict(kind="validation", check="final-time wall-mean y+ (y_P |tau_w|^0.5/nu, instantaneous "
                         "wallShearStress) against the y+ function object's last sample, same instant (2 %)",
                         case=r["name"], reference=r["yplus_fo_last"], source="postProcessing/yPlus1/*/yPlus.dat, "
                         f"last row (t {r['t_fo']:.10g} s; field {r['t_field']:.10g} s)", value=r["yplus_inst_fields"],
                         ratio=ratio, passed=bool(abs(ratio - 1) <= 0.02 and abs(r["t_fo"] - r["t_field"]) < 1e-9)))
    for r in list(CK.to_dict("records")) + wf:
        ratio = r["yplus_mean_fields"] / r["yplus_table"]
        rows.append(dict(kind="diagnostic", check="wall-mean y+ from the time-mean shear against the window mean of "
                         "the instantaneous y+ (the runs' tables); below 1 where the shear fluctuates "
                         "(sqrt is concave)",
                         case=r["name"], reference=r["yplus_table"],
                         source=r.get("yplus_table_source", "cfd/stage2/results/stage2_polars.csv yplus_blade_mean"),
                         value=r["yplus_mean_fields"], ratio=ratio, passed=None))
    for r in wf:
        if r["Ks_um"] > 0:
            mine = r["yplus_mean_fields"] * r["Ks_um"] * 1e-6 / r["yP_nominal"]
            rows.append(dict(kind="diagnostic", check="wall-function Ks+ (painted faces, y+ Ks/y_P) from the time-mean "
                             "shear against stage2_polars.csv ksplus_blade_mean", case=r["name"],
                             reference=r["ksplus_table"],
                             source="cfd/stage2/results/stage2_polars.csv ksplus_blade_mean", value=mine,
                             ratio=mine / r["ksplus_table"], passed=None))
    # u_tau of the repo's Ks+ next to this script's
    why_rot = ("rotating blade: every orientation of the revolution and a relative speed of (1 +- lambda) U, blade "
               "mean over 3 blades; the wall function's k-based y* = Cmu^0.25 k_P^0.5 y/nu where y* > 11.53, which "
               "stays finite where the wall shear vanishes (separated, stagnant and wake regions); rough wall: the "
               "roughness itself raises it (Ks 400 against 100: x1.10)")
    rot = pd.read_csv(REPO / "cfd" / "rotor2d" / "results" / "rotor_cp.csv")
    for r in rot[rot.Ks_um.isin([100.0, 400.0])].itertuples():
        rows.append(dict(kind="comparison", check="rotor, rough wall function: u* = Ks+ nu/Ks", case=r.name,
                         source="cfd/rotor2d/results/rotor_cp.csv ksplus_blade_mean", value=r.ksplus_blade_mean,
                         utau_ms=r.ksplus_blade_mean * NU / (r.Ks_um * 1e-6), lam=r.lam, Ks_um=r.Ks_um, note=why_rot))
    why_wf = ("static section at one alpha; wall-shear y+ (useWallFunction false) on the painted faces, window mean of "
              "the instantaneous y+, every region of the wall (wake and stagnant cup included); blade-mean y+ "
              "22-41 at 23 m/s (stage2_polars.csv), much of the wall in the buffer layer "
              "(cfd/analysis/2026-10-13/RESULTS.md section 3.6); Ks 0 is the same mesh and wall function")
    for r in wf:
        u_t = r["yplus_table"] * NU / r["yP_nominal"]
        rows.append(dict(kind="comparison", check="static section, rough wall function: u_tau = y+ nu/y_P (painted "
                         "faces)", case=r["name"], source="cfd/stage2/results/stage2_polars.csv yplus_blade_mean",
                         value=r["ksplus_table"], utau_ms=u_t, Ks_um=r["Ks_um"], note=why_wf))
    why_me = ("static section, smooth low-Re wall (y+ < 1), time-mean shear; primary stations = the attached "
              "boundary layer from the stagnation point (windward face), which tripping and Ks+ act on; the "
              "painted-face mean covers the whole wall as the blade means above do")
    CKi = CK.set_index("name")
    for n, g in ST[ST.region == "primary"].groupby("name", sort=False):
        um = float(g.u_tau.median())
        rows.append(dict(kind="comparison", check="static section, smooth low-Re wall (this script): u_tau, primary "
                         "stations, median (min-max) and the painted-face mean", case=n, source="bl_stations.csv",
                         utau_ms=um, utau_min_ms=float(g.u_tau.min()), utau_max_ms=float(g.u_tau.max()),
                         utau_painted_mean_ms=float(CKi.loc[n, "utau_painted_mean"]), Ks_um=np.nan,
                         ksplus_100_median=um * 1e-4 / NU, ksplus_400_median=um * 4e-4 / NU, note=why_me))
    return pd.DataFrame(rows)


def figure(ST, KT):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import roughness_analysis as RA          # 15 Oct style (read only)
    RA.style()
    INK2, GRID = "#52514e", "#8c8c8c"
    # dataviz validator, all pairs: CVD dE >= 17.6, normal-vision >= 28.1; magenta < 3:1, so markers differ too
    COL = {0: "#e87ba4", 90: "#6250d6", 180: "#008300"}
    MK = {0: "s", 90: "^", 180: "o"}
    sst = ST[(ST.model == "SST") & (ST.maxCo == 2.5) & (ST.U == 23.0) & (ST.region == "primary")]
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 5.8), constrained_layout=True)
    ax, bx = axes[0]
    xl = "distance from the stagnation point (mm): toward tip A < 0 < toward tip B"
    for (n, a), g in sst.groupby(["name", "alpha_deg"], sort=False):
        a = int(round(a))
        ls = "-" if "medium" in n else "--"
        lab = f"α {a}°, " + ("Stage 1 medium mesh" if "medium" in n else "texture mesh, t 0")
        for br, gg in g.groupby("branch"):
            gg = gg.assign(x=gg.from_stag_mm * (1 if br == "B" else -1)).sort_values("x")
            kw = dict(color=COL[a], ls=ls, marker=MK[a], ms=3.2, lw=1.0, mfc=COL[a] if ls == "-" else "white")
            ok = gg[gg.d99_ok]
            if a != 0 and len(ok):
                ax.plot(ok.x, ok.d99_mm, label=lab if br == "B" or len(g.branch.unique()) == 1 else None, **kw)
            bx.plot(gg.x, gg.u_tau, label=lab if br == "B" or len(g.branch.unique()) == 1 else None, **kw)
    ax.set_xlabel(xl, fontsize=6.6)
    bx.set_xlabel(xl, fontsize=6.6)
    ax.set_ylabel("δ99 (mm)")
    bx.set_ylabel("u_τ (m/s)")
    ax.set_title("(a) δ99 (α 0: no edge in the stagnant cup, U_e < 0.3 U)", loc="left")
    bx.set_title("(b) Friction velocity", loc="left")
    ax.legend(fontsize=5.8, loc="upper left")
    bx.legend(fontsize=5.8, loc="upper left")
    cx, dx = axes[1]
    med = KT[(KT.face == "both") & KT.name.str.contains("SST_medium") & (KT.maxCo == 2.5)]
    med = med.drop_duplicates(["name", "h_um"])          # Ks 50, 100, 200, 400 um = t 0.05, 0.10, 0.20, 0.40 mm
    for a, g in med.groupby("alpha_deg"):
        a = int(round(a))
        g = g.sort_values("h_um")
        for x_, col, lo, hi in ((cx, "hplus_median", "hplus_min", "hplus_max"),
                                (dx, "Re_k_median", "Re_k_min", "Re_k_max")):
            x_.errorbar(g.h_um * (1 + 0.04 * (a - 90) / 90), g[col], yerr=[g[col] - g[lo], g[hi] - g[col]],
                        color=COL[a], marker=MK[a], ms=3.6, lw=0.9, capsize=1.8, ls="none", label=f"α {a}°")
    hh = np.geomspace(20, 1000, 60)
    dx.fill_between(hh, CRIT_2D[0], CRIT_2D[1], color="#e6e6e6", lw=0, zorder=0)
    dx.fill_between(hh, CRIT_3D[0] * (hh * 1e-6 / D_ELEMENT) ** 0.4, CRIT_3D[1] * (hh * 1e-6 / D_ELEMENT) ** 0.4,
                    color="#d0d0d0", lw=0, zorder=0)
    dx.text(22, 175, "2D ridges: onset Re_k 40–260", fontsize=5.8, color=INK2)
    dx.text(22, 1500, "isolated 3D: 600–900 (h/d)$^{0.4}$, d 0.2 mm", fontsize=5.8, color=INK2)
    cx.axhspan(0.05, 2.25, color="#e6e6e6", lw=0, zorder=0)
    cx.axhline(90, color=GRID, lw=0.6, zorder=0)
    cx.text(120, 0.14, "Ks+ < 2.25: roughness off\nin the wall function", fontsize=5.8, color=INK2)
    cx.text(22, 100, "fully rough above 90", fontsize=5.8, color=INK2)
    ticks = [25, 50, 100, 200, 400, 800]
    for x_ in (cx, dx):
        x_.set_xscale("log")
        x_.set_yscale("log")
        x_.set_xticks(ticks)
        x_.set_xticklabels([str(t) for t in ticks])
        x_.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
        x_.set_xlim(20, 1000)
        x_.set_xlabel("roughness height h (µm): the report's Ks and FS amplitudes t")
    cx.set_ylim(0.1, 300)
    cx.set_ylabel("h+ = h u_τ/ν (smooth-wall u_τ)")
    dx.set_ylabel("Re_k = u(h) h/ν")
    cx.set_title("(c) Roughness in wall units", loc="left")
    dx.set_title("(d) Roughness Reynolds number", loc="left")
    cx.legend(fontsize=5.8, loc="lower right")
    fig.suptitle("Smooth low-Re walls, SST, 23 m/s, maxCo 2.5, time means; attached (primary) stations every 5 mm.\n"
                 "(c), (d): Stage 1 medium mesh, both faces, median and min–max over the stations; Ks 50, 100, 200, "
                 "400 µm coincide with t 0.05, 0.10, 0.20, 0.40 mm", fontsize=6.4, x=0.01, ha="left", color=INK2)
    out = FIG / "bl_ks_tables.png"
    fig.savefig(out, dpi=200, facecolor="white")
    plt.close(fig)
    return out


def main():
    cases = bl_cases()
    print(f"{len(cases)} smooth low-Re runs")
    with ProcessPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(analyse, cases))
    ST = pd.DataFrame([s for r in res for s in r[0]])
    HT = pd.DataFrame([h for r in res for h in r[1]])
    CK = pd.DataFrame([r[2] for r in res])
    KT = tables(ST, HT)
    CH = checks(CK, ST)
    for n, g in ST[ST.region == "primary"].groupby("name", sort=False):
        per_face = ", ".join(f"{f} {int((g.face == f).sum())}" for f in ("convex", "concave"))
        print(f"{n:46s} primary {len(g):2d} ({per_face}) "
              f"u_tau {g.u_tau.median():.3f} [{g.u_tau.min():.3f}, {g.u_tau.max():.3f}] m/s  d99 "
              f"{g.d99_mm[g.d99_ok].median():.3f} [{g.d99_mm[g.d99_ok].min():.3f}, {g.d99_mm[g.d99_ok].max():.3f}] mm  "
              f"H {g.H.median():.2f}  Re_theta {g.Re_theta.median():.0f}  y1+ max {g.y1_plus.max():.2f}")
    print(CH[["kind", "case", "reference", "value", "ratio", "passed", "utau_ms"]].to_string(max_colwidth=50))
    bad = CH[(CH.kind == "validation") & (CH.passed != True)]  # noqa: E712
    OUT.mkdir(exist_ok=True)
    ST.to_csv(OUT / "bl_stations.csv", index=False, float_format="%.5g")
    KT.to_csv(OUT / "bl_ks_tables.csv", index=False, float_format="%.4g")
    CH.to_csv(OUT / "bl_utau_check.csv", index=False, float_format="%.5g")
    print("wrote", figure(ST, KT))
    print(f"validation checks: {int((CH.kind == 'validation').sum())}, failed {len(bad)}")
    return 1 if len(bad) else 0


if __name__ == "__main__":
    sys.exit(main())
