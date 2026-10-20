#!/usr/bin/env python3
"""Reviewer's independent check of the Stage 2 (roughness on the section) findings of 15 Oct 2026.

    nice -n 10 python3 cfd/analysis/2026-10-15/src/roughness_review_check.py            # about 10 s with the cache
    nice -n 10 python3 cfd/analysis/2026-10-15/src/roughness_review_check.py --logs     # re-parse the 16 solver
                                                                                         # logs (~15 GB, ~10 min)

Written in the review of 19 Oct 2026. It shares no code with roughness_analysis.py, roughness_histories.py,
roughness_surface.py, roughness_verify.py or cfd/post:
  - table: cfd/stage2/results/stage2_polars.csv read directly; the 13 Oct copy
    (cfd/analysis/2026-10-13/data/stage2_polars.csv) for the identity check of the 43 old rows;
  - forces: its own reader of postProcessing/forceCoeffs1/<t>/coefficient.dat (sessions sorted by start time,
    a later session replaces the earlier one from its first sample on); windows by time, running means by
    time (pandas rolling with a time offset), not by resampling;
  - solver logs: an awk state machine (first p solve of 'PIMPLE: iteration 1' of every step), summarised per
    5-c/U block into ../out/roughness_review_logblocks.csv (the cache);
  - wall pressure: its own binary reader of polyMesh/{points,faces,boundary} and <t_end>/{pMean,
    wallShearStressMean,UMean}; face area vectors by Newell's method; the blade patch split into its two open
    chains by shared point labels; arc-length smoothing over 1 mm by cumulative sums;
  - measured: reports/roughness_2026-09/build/derived/{comparisons,rotor_by_wind_speed}.csv.
Each line prints the quoted value (findings R1-R4 as given to the reviewer, UPDATE.md section 6 for the rest,
and the figure captions), the recomputed one and OK, or CHECK where the quoted text is wrong or imprecise.
Definitions are those of the analysis: noise of a change = |drift_a| + |drift_b|, drift = second-half minus
first-half window mean; jump = |dCd| > 0.5 between consecutive samples from 2 c/U on, counted by 1-c/U interval
in the window; alpha-0 state from the 8-c/U running mean (high-drag above Cd 2.5).
Reads only; writes nothing but the log-block cache.
"""
import argparse
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[4]
RUNS = REPO / "cfd" / "stage2" / "runs"
TAB = REPO / "cfd" / "stage2" / "results" / "stage2_polars.csv"
TAB13 = REPO / "cfd" / "analysis" / "2026-10-13" / "data" / "stage2_polars.csv"
SEC = REPO / "cfd" / "section2d" / "results" / "section_polars.csv"
RIG = REPO / "reports" / "roughness_2026-09" / "build" / "derived"
CACHE = Path(__file__).resolve().parents[1] / "out" / "roughness_review_logblocks.csv"
N_CHECK = 0
N_LINES = 0


def out(label, quoted, got, ok):
    global N_CHECK, N_LINES
    N_CHECK += not ok
    N_LINES += 1
    print(f"{'OK   ' if ok else 'CHECK'} {label:64s} quoted {str(quoted):>26s} | recomputed {got}")


def near(a, b, tol):
    return abs(float(a) - float(b)) <= tol


def pct(x, ref):
    return 100.0 * (x - ref) / abs(ref)


# ------------------------------------------------------------------ table helpers
T = pd.read_csv(TAB)
T["t"] = T.tex_t_mm.round(2)
TI = T.set_index("name")


def wfname(a, ks, co, U=23.0):
    return f"a{a:05.1f}_U{U:.1f}_SST_wf_Ks{ks}_Tu1.0" + ("_Co2.5n2" if co == 2.5 else "")


def txname(a, m, t, co, U=23.0):
    return f"a{a:05.1f}_U{U:.1f}_{m}_tex{t:.3f}_s1_Tu1.0_" + ("Co2.5n2" if co == 2.5 else "N80A50")


def row(n):
    return TI.loc[n]


def chg(ref, x, q="Cd"):
    """(change, change %, noise, ratio) of x against ref from the table."""
    a, b = row(ref), row(x)
    d = b[f"{q}_mean"] - a[f"{q}_mean"]
    n = abs(a[f"{q}_drift"]) + abs(b[f"{q}_drift"])
    return d, 100 * d / abs(a[f"{q}_mean"]), n, abs(d) / n


# ------------------------------------------------------------------ force histories (own reader)
_H = {}


def hist(case):
    if case in _H:
        return _H[case]
    base = RUNS / case / "postProcessing" / "forceCoeffs1"
    parts = [np.loadtxt(d / "coefficient.dat", comments="#", usecols=(0, 1, 4))
             for d in sorted(base.iterdir(), key=lambda p: float(p.name))]
    keep = [p[p[:, 0] < parts[i + 1][0, 0]] if i + 1 < len(parts) else p for i, p in enumerate(parts)]
    a = np.vstack(keep)
    P = json.loads((RUNS / case / "case.json").read_text())
    s = pd.DataFrame({"t": a[:, 0] / P["convTime"], "Cd": a[:, 1], "Cl": a[:, 2]})
    _H[case] = (s, P)
    return _H[case]


def wstats(s, t0, t1, q="Cd", tol=1e-9):
    w = s[(s.t >= t0 - tol) & (s.t <= t1 + tol)]
    mid = 0.5 * (w.t.iloc[0] + w.t.iloc[-1])
    return w[q].mean(), w[q][w.t >= mid].mean() - w[q][w.t < mid].mean()


def table_window(s, P):
    t1 = s.t.iloc[-1]
    return t1 - P["nAvg"], t1


def jump_bins(s, lim, t0, t1):
    d = s.Cd.diff().abs()
    hit = s.t[(d > lim) & (s.t >= 2.0)]
    k = np.floor(hit.to_numpy()).astype(int)
    k0, k1 = int(round(t0)), int(round(t1))
    k = np.where(k == k1, k1 - 1, k)
    return sorted(set(int(x) for x in k if k0 <= x < k1))


def max_step_in_window(s, t0, t1):
    w = s[(s.t >= t0) & (s.t <= t1)]
    return w.Cd.diff().abs().max()


def noise_end(s, lim=0.1):
    d = s.Cd.diff().abs()
    hit = s.t[(d > lim) & (s.t >= 2.0)]
    return float(np.floor(hit.iloc[-1]) + 1) if len(hit) else float("nan")


def running(s, width, q="Cd"):
    """Centred running mean over `width` c/U by time (own: pandas time-offset rolling)."""
    x = s.set_index(pd.to_timedelta(s.t, unit="s"))[q]
    r = x.rolling(pd.Timedelta(seconds=width), min_periods=1).mean()
    tc = s.t.to_numpy() - width / 2          # trailing window -> centre
    ok = s.t.to_numpy() >= s.t.iloc[0] + width
    return tc[ok], r.to_numpy()[ok]


# ------------------------------------------------------------------ per-run history metrics
def run_metrics():
    rows = []
    for name in T.name:
        s, P = hist(name)
        t0, t1 = table_window(s, P)
        cd, dr = wstats(s, t0, t1, tol=0.0)          # the table's window: t >= t_end - nAvg exactly
        r = dict(name=name, t_end=s.t.iloc[-1], w0=t0, w1=t1, Cd_win=cd, drift_win=dr,
                 Cd_tab=row(name).Cd_mean, drift_tab=row(name).Cd_drift,
                 step_max_win=max_step_in_window(s, t0, t1), noise_end=noise_end(s))
        for lim in (0.5, 0.2, 0.1):
            r[f"jumps_{lim}"] = len(jump_bins(s, lim, t0, t1))
        for lab, (a, b) in (("30_80", (30, 80)), ("100_150", (100, 150))):
            if s.t.iloc[-1] >= b - 0.05:
                r[f"Cd_{lab}"], r[f"drift_{lab}"] = wstats(s, a, b)
            else:
                r[f"Cd_{lab}"], r[f"drift_{lab}"] = np.nan, np.nan
        sl = s[s.t >= s.t.iloc[-1] - 50]
        r["slope_last50_per100"] = 100 * np.polyfit(sl.t, sl.Cd, 1)[0]
        if row(name).alpha_deg == 0:
            tc, rm = running(s, 8.0)
            inw = (tc >= t0) & (tc <= t1)
            hi = rm > 2.5
            r["state"] = "high" if hi[inw].all() else ("low" if not hi[inw].any() else "mixed")
            late = tc >= 20
            r["high_last"] = float(tc[late][hi[late]].max()) if hi[late].any() else np.nan
            r["high_share_win"] = hi[inw].mean()
        rows.append(r)
    return pd.DataFrame(rows).set_index("name")


# ------------------------------------------------------------------ solver logs (awk), cached per 5-c/U block
AWK = r'''
/^deltaT = / { dt = $3; next }
/^Time = /   { t = $3; want = 0; next }
/^PIMPLE: iteration 1$/ { want = 1; next }
/^PIMPLE: iteration/ { want = 0; next }
want == 1 && /Solving for p,/ { s = $0; sub(/.*Initial residual = /, "", s); sub(/,.*/, "", s); print t, dt, s; want = 0 }
'''


def log_blocks(reparse, steps_dir=None):
    if CACHE.exists() and not reparse:
        return pd.read_csv(CACHE)
    rows = []
    for name in T.name[(T.wall == "tex") & (T.maxCo == 2.5)]:
        P = json.loads((RUNS / name / "case.json").read_text())
        if steps_dir:
            txt = (Path(steps_dir) / f"{name}.txt").read_text()
        else:
            txt = subprocess.run(["awk", AWK, str(RUNS / name / "log.pimpleFoam")], capture_output=True, text=True,
                                 env={"LC_ALL": "C"}, check=True).stdout
        a = np.array(txt.split(), float).reshape(-1, 3)
        t, dt, pr = a[:, 0] / P["convTime"], a[:, 1] / P["convTime"], a[:, 2]
        for k in range(30):
            m = (t >= 5 * k) & (t < 5 * k + 5) if k < 29 else (t >= 145)
            rows.append(dict(name=name, t_from=5 * k, n=int(m.sum()), dt_mean=dt[m].mean(), dt_min=dt[m].min(),
                             p_med=np.median(pr[m]), p_share_gt_0p05=np.mean(pr[m] > 0.05)))
    L = pd.DataFrame(rows)
    L.to_csv(CACHE, index=False, float_format="%.6g")
    return L


# ------------------------------------------------------------------ wall pressure (own binary readers)
def _list(b, pos, dtype, ncomp):
    m = re.compile(rb"(\d+)\s*\(").search(b, pos)
    n = int(m.group(1))
    a = np.frombuffer(b, dtype=dtype, count=n * ncomp, offset=m.end())
    return (a.reshape(n, ncomp) if ncomp > 1 else a), m.end() + a.nbytes


def _hdr(b):
    return b.index(b"// * * *")


def mesh(case):
    pm = RUNS / case / "constant" / "polyMesh"
    b = (pm / "points").read_bytes()
    pts, _ = _list(b, _hdr(b), "<f8", 3)
    b = (pm / "faces").read_bytes()
    off, e = _list(b, _hdr(b), "<i4", 1)
    lab, _ = _list(b, e, "<i4", 1)
    b = (pm / "owner").read_bytes()
    own, _ = _list(b, _hdr(b), "<i4", 1)
    txt = (pm / "boundary").read_text()
    bnd = {m.group(1): (int(re.search(r"startFace\s+(\d+)", m.group(2)).group(1)),
                        int(re.search(r"nFaces\s+(\d+)", m.group(2)).group(1)))
           for m in re.finditer(r"(\w+)\s*\{\s*([^}]*)\}", txt) if "startFace" in m.group(2)}
    return pts, off, lab, own, bnd


def patch_vals(case, tdir, field, patch, ncomp):
    b = (RUNS / case / tdir / field).read_bytes()
    j = re.compile(rb"\n\s+" + patch.encode() + rb"\s*\n\s*\{").search(b, b.index(b"boundaryField")).end()
    return _list(b, b.index(b"nonuniform", j), "<f8", ncomp)[0]


def internal_vals(case, tdir, field, ncomp):
    b = (RUNS / case / tdir / field).read_bytes()
    return _list(b, b.index(b"internalField"), "<f8", ncomp)[0]


def newell(pts, off, lab, fidx):
    S = np.zeros((len(fidx), 3))
    C = np.zeros((len(fidx), 3))
    for i, f in enumerate(fidx):
        v = pts[lab[off[f]:off[f + 1]]]
        S[i] = 0.5 * np.cross(v, np.roll(v, -1, axis=0)).sum(axis=0)
        C[i] = v.mean(axis=0)
    return S, C


def two_chains(pts, off, lab, fidx):
    z0 = pts[:, 2].min()
    seg = []
    for f in fidx:
        v = lab[off[f]:off[f + 1]]
        seg.append([int(p) for p in v if abs(pts[p, 2] - z0) < 1e-12])
    by = defaultdict(list)
    for i, (a, b) in enumerate(seg):
        by[a].append(i)
        by[b].append(i)
    chains, seen = [], set()
    for p0 in [p for p, l in by.items() if len(l) == 1]:
        i, cur = by[p0][0], p0
        if i in seen:
            continue
        order = []
        while True:
            seen.add(i)
            order.append(i)
            a, b = seg[i]
            nxt = b if a == cur else a
            nb = [j for j in by[nxt] if j != i]
            if not nb:
                break
            i, cur = nb[0], nxt
        chains.append((np.array(order), pts[p0, :2], pts[nxt, :2]))
    return chains


def smooth_len(s, y, L=1e-3):
    cs = np.concatenate([[0.0], np.cumsum(y)])
    lo = np.searchsorted(s, s - L / 2, side="left")
    hi = np.searchsorted(s, s + L / 2, side="right")
    return (cs[hi] - cs[lo]) / (hi - lo)


_REFS = {}


def surface(case):
    """Pressure drag by face, stagnation point, suction peaks and (smooth runs) separation on the convex face."""
    P = json.loads((RUNS / case / "case.json").read_text())
    tds = [p.name for p in (RUNS / case).iterdir() if re.fullmatch(r"\d+(\.\d+)?", p.name) and float(p.name) > 0]
    td = max(tds, key=float)
    pts, off, lab, own, bnd = mesh(case)
    fr = json.loads((RUNS / case / "mesh_info.json").read_text())["frame"]["corners_body_m"]
    q, Aref = 0.5 * P["Uinf"] ** 2, P["Aref"]
    drag = np.array(P["dragDir"])
    res = dict(case=case)
    s0, n = bnd["bladeEnds"]
    S, C = newell(pts, off, lab, np.arange(s0, s0 + n))
    res["ends"] = float(((patch_vals(case, td, "pMean", "bladeEnds", 1)[:, None] * S) @ drag).sum() / (q * Aref))
    s0, n = bnd["blade"]
    fidx = np.arange(s0, s0 + n)
    S, C = newell(pts, off, lab, fidx)
    p = patch_vals(case, td, "pMean", "blade", 1)
    tau = patch_vals(case, td, "wallShearStressMean", "blade", 3)
    Um = internal_vals(case, td, "UMean", 3)
    dC = (p[:, None] * S) @ drag / (q * Aref)
    for order, e1, e2 in two_chains(pts, off, lab, fidx):
        near = [min(fr, key=lambda k: np.hypot(*(np.array(fr[k]) - e))) for e in (e1, e2)]
        if near[0].startswith("B"):
            order, near = order[::-1], near[::-1]
        face = "convex" if near[0] == "A_outer" else "concave"
        res[face] = float(dC[order].sum())
        if face == "concave":
            continue
        xy = C[order, :2]
        key = (P["alphaDeg"], len(order))
        if P["texT"] == 0 and key not in _REFS:
            nrm = -S[order, :2] / np.linalg.norm(S[order, :2], axis=1)[:, None]
            _REFS[key] = (xy, np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]), nrm)
        rxy, sref, nref = _REFS[key]
        res["dev_mm"] = float(np.hypot(*(xy - rxy).T).max() * 1e3)
        Cp = p[order] / q
        Cps = smooth_len(sref, Cp)
        ist = int(np.argmax(Cps))
        B = np.arange(ist, len(order))
        A = np.arange(0, ist)
        iB = B[np.argmin(Cps[B])]
        up = nref @ (-drag[:2])
        res.update(stag=sref[ist] / 0.048, tipB=(sref[-1] - sref[ist]) / 0.048, CpminB=float(Cps[iB]),
                   CpminB_at=(sref[iB] - sref[ist]) / 0.048, CpminB_facing_up=float(up[iB]),
                   CdpB=float(dC[order][B].sum()), CdpA=float(dC[order][A].sum()),
                   turn_down_at=(sref[B[np.argmax(up[B] <= 0)]] - sref[ist]) / 0.048)
        if P["texT"] == 0:
            # signed Cf along +s (tip A -> tip B), smoothed over 1 mm; separation toward tip B = first reversal
            # (Cf < 0 against the attached sign +) lasting >= 0.5 mm, beyond 1 mm from the stagnation point
            tng = np.gradient(rxy, axis=0)
            tng /= np.linalg.norm(tng, axis=1)[:, None]
            cell = own[fidx[order]]
            sgn = np.sign(np.sum(Um[cell, :2] * tng, axis=1))
            Cf = sgn * np.abs(np.sum(tau[order, :2] * tng, axis=1)) / q
            Cfs = smooth_len(sref, Cf)
            sB = sref[B] - sref[ist]
            rev = (Cfs[B] < 0) & (sB > 1e-3)
            sep = np.nan
            k = 0
            while k < len(B):
                if rev[k]:
                    j = k
                    while j < len(B) and rev[j]:
                        j += 1
                    if sB[min(j, len(B) - 1)] - sB[k] >= 0.5e-3:
                        sep = sB[k] / 0.048
                        break
                    k = j
                k += 1
            res["sepB"] = sep
    res["total"] = res["convex"] + res["concave"] + res["ends"]
    res["Cdp_tab"] = row(case).Cd_pressure_mean
    return res


# ================================================================== checks
def check_table():
    print("\n== 0. Table")
    old = pd.read_csv(TAB13)
    new = T.set_index("name")
    o = old.set_index("name")
    common = [c for c in o.columns if c in new.columns]
    same = all(np.allclose(o[c].astype(float), new.loc[o.index, c].astype(float), equal_nan=True, rtol=0, atol=0)
               if o[c].dtype.kind in "fi" else (o[c] == new.loc[o.index, c]).all() for c in common)
    out("rows / 13 Oct rows value-identical", "69, 43 identical", f"{len(T)}, {len(o)} identical={same}",
        len(T) == 69 and len(o) == 43 and same)
    nn = T[~T.name.isin(o.index)]
    out("new rows (S2e_rerun)", 26, len(nn), len(nn) == 26)
    return nn


def check_R1(H, L, new):
    print("\n== R1 health")
    tx = T.wall == "tex"
    sym = (T.Cd_mean < 0) | (T.Cd_std > T.Cd_mean.abs()) | (T.Cl_mean.abs() > 3) | \
          (tx & (T[["yplus_blade_max", "yplus_bladeEnds_max"]].max(axis=1) > 2))
    out("runs with a corruption symptom", "0 of 69", f"{int(sym.sum())} of {len(T)}", sym.sum() == 0)
    yp = T[tx].set_index("name")[["yplus_blade_max", "yplus_bladeEnds_max"]].max(axis=1)
    out("largest texture-run y+ (time-mean max), case", "1.17, LM a0 t0 Co2.5", f"{yp.max():.3f}, {yp.idxmax()}",
        near(yp.max(), 1.17, 0.005) and yp.idxmax() == txname(0, "LM", 0, 2.5))
    # time-step ratio to the family median (family as the analysis: wall, alpha, U for wf, maxCo)
    dtc = T.dt_mean_s * T.U_ms / 0.048
    fam = T.wall + " " + T.alpha_deg.astype(str) + " " + np.where(T.wall == "wf", T.U_ms.astype(str), "") + " " + \
        T.maxCo.astype(str)
    ratio = dtc.groupby(fam).transform("median") / dtc
    rn = ratio[T.name.isin(new.name)]
    i = rn.idxmax()
    out("largest family-median/run dt ratio, new runs", "1.27, LM a0 t0 Co2.5", f"{rn.max():.3f}, {T.name[i]}",
        near(rn.max(), 1.27, 0.005) and T.name[i] == txname(0, "LM", 0, 2.5))
    out("dt-anomaly (ratio >= 1.9) and flagged", "0, 0", f"{int((ratio >= 1.9).sum())}, "
        f"{int(((ratio >= 1.9) & sym).sum())}", (ratio >= 1.9).sum() == 0)
    # same-mesh twin (SST/LM on the same tex mesh and maxCo) as an alternative family
    a = row(txname(0, "LM", 0, 2.5)).dt_mean_s / row(txname(0, "SST", 0, 2.5)).dt_mean_s
    print(f"      note: LM/SST dt on the same smooth alpha-0 texture mesh at maxCo 2.5 = {a:.3f}")
    # jumps
    j5 = H[H["jumps_0.5"] > 0]
    out("runs with jumps (0.5) in the window", "only LM a0 t0 Co2.5", ", ".join(j5.index), list(j5.index) ==
        [txname(0, "LM", 0, 2.5)])
    r = H.loc[txname(0, "LM", 0, 2.5)]
    out("  its jump intervals / largest step", "19 of 100, 8.08", f"{int(r['jumps_0.5'])}, {r.step_max_win:.3f}",
        r["jumps_0.5"] == 19 and near(r.step_max_win, 8.08, 0.005))
    over2 = H[(H.step_max_win > 0.2)].drop(txname(0, "LM", 0, 2.5))
    wf5 = over2[over2.index.str.contains("_wf_") & ~over2.index.str.endswith("Co2.5n2")]
    oth = over2.drop(wf5.index)
    out("limit 0.2 adds: U20.9 LM t0 (0.263) + 5 wf a180 maxCo 5 (0.30-0.36)",
        "0.263; 5 runs 0.30-0.36", f"{', '.join(f'{n} {v:.3f}' for n, v in oth.step_max_win.items())}; "
        f"{len(wf5)} wf runs {wf5.step_max_win.min():.3f}-{wf5.step_max_win.max():.3f}",
        list(oth.index) == [txname(180, "LM", 0, 2.5, 20.9)] and near(oth.step_max_win.iloc[0], 0.263, 0.0005) and
        len(wf5) == 5 and all(n.startswith("a180") for n in wf5.index) and near(wf5.step_max_win.min(), 0.30, 0.005)
        and near(wf5.step_max_win.max(), 0.36, 0.005))
    rep = H.loc[[wfname(180, k, 2.5) for k in (0, 50, 100, 200, 400)]].step_max_win
    out("  their maxCo-2.5 repeats", "0.046-0.053", f"{rep.min():.3f}-{rep.max():.3f}",
        near(rep.min(), 0.046, 0.0005) and near(rep.max(), 0.053, 0.0005))
    over1 = H[(H.step_max_win > 0.1) & (H.step_max_win <= 0.2)]
    out("limit 0.1 adds U18.8 LM t0 (0.172)", "0.172", ", ".join(f"{n} {v:.3f}" for n, v in
                                                          over1.step_max_win.items()),
        list(over1.index) == [txname(180, "LM", 0, 2.5, 18.8)] and near(over1.step_max_win.iloc[0], 0.172, 0.0005))
    # u_Co/U proxy with 40 um (tex) and 200 um (wf)
    dx = np.where(T.wall == "tex", 40e-6, 200e-6)
    uco = T.maxCo * dx / (T.dt_mean_s * T.U_ms)
    for a, co, q in ((180, 2.5, (5.39, 6.84)), (180, 5.0, (5.55, 5.79))):
        m = tx & (T.alpha_deg == a) & (T.maxCo == co)
        lo, hi = uco[m].min(), uco[m].max()
        out(f"u_Co/U, tex alpha {a} maxCo {co:g} (40 um)", f"{q[0]}-{q[1]}", f"{lo:.2f}-{hi:.2f}",
            near(lo, q[0], 0.005) and near(hi, q[1], 0.005))
    out("u_Co/U, all other runs", "< 5", f"max {uco[~(tx & (T.alpha_deg == 180))].max():.2f}",
        uco[~(tx & (T.alpha_deg == 180))].max() < 5)
    # alpha-180 / alpha-0 time step on the texture mesh (23 m/s), pairwise (same model, t, maxCo) and by median
    for co in (2.5, 5.0):
        rs = []
        for m in ("SST", "LM"):
            for t in (0.0, 0.05, 0.1, 0.2):
                n0, n1 = txname(0, m, t, co), txname(180, m, t, co)
                if n0 in TI.index and n1 in TI.index:
                    rs.append(row(n1).dt_mean_s / row(n0).dt_mean_s)
        g0 = T[tx & (T.alpha_deg == 0) & (T.maxCo == co) & (T.U_ms == 23)].dt_mean_s.median()
        g1 = T[tx & (T.alpha_deg == 180) & (T.maxCo == co) & (T.U_ms == 23)].dt_mean_s.median()
        out(f"tex dt(180)/dt(0), maxCo {co:g}", "0.61 at both maxCo",
            f"ratio of medians {g1 / g0:.3f}; pairwise {min(rs):.2f}-{max(rs):.2f} (n={len(rs)})",
            near(g1 / g0, 0.61, 0.005) and max(rs) - min(rs) < 0.1)
    # start-up noise and residuals (smooth alpha-180 maxCo-2.5 runs)
    sm = [txname(180, "SST", 0, 2.5)] + [txname(180, "LM", 0, 2.5, U) for U in (18.8, 20.9, 23.0, 25.2)]
    ne = H.loc[sm].noise_end
    out("noise end: SST / LM", "29; 38-56", f"{ne.iloc[0]:.0f}; {ne.iloc[1:].min():.0f}-{ne.iloc[1:].max():.0f}",
        ne.iloc[0] == 29 and ne.iloc[1:].min() == 38 and ne.iloc[1:].max() == 56)
    out("  inside the window, LM 18.8 / 20.9", "2, 6", f"{ne.iloc[1] - 50:.0f}, {ne.iloc[2] - 50:.0f}",
        ne.iloc[1] - 50 == 2 and ne.iloc[2] - 50 == 6)
    pm = {}
    for n in sm:
        g = L[L.name == n]
        noisy = g[(g.t_from >= 10) & (g.t_from + 5 <= H.loc[n].noise_end)]
        pm[n] = (noisy.p_med.max(), g[g.t_from >= 100].p_med.max())
    mx = max(v[0] for v in pm.values())
    late = max(v[1] for v in pm.values())
    out("5-c/U median first-p residual, noisy start-up max", "0.12 (0.122 LM 20.9, 0.121 SST)",
        f"{mx:.4f}; LM 20.9 {pm[sm[2]][0]:.4f}, SST {pm[sm[0]][0]:.4f}",
        near(pm[sm[2]][0], 0.122, 0.0005) and near(pm[sm[0]][0], 0.121, 0.0005))
    out("  last 50 c/U, max", "<= 0.0008", f"{late:.5f}", late <= 0.0008 + 5e-5)
    rat = [v[0] / v[1] for v in pm.values()]
    lm0 = L[L.name == txname(0, "LM", 0, 2.5)]
    quiet = lm0[(lm0.t_from >= 60) & (lm0.t_from < 100)]
    jump_rat = lm0[lm0.t_from >= 135].p_med.max() / quiet.p_med.median()
    out("residuals of jumps / start-ups vs late level (x)", "10-150",
        f"smooth a180 start-ups {min(rat):.0f}-{max(rat):.0f}; LM a0 jump phase {jump_rat:.0f} (vs its 60-100 c/U)",
        near(min(rat), 150, 5) and near(max(rat), 150, 5) and near(jump_rat, 10, 1))
    dsm = min(L[(L.name == n) & (L.t_from >= 10)].dt_min.min() / L[(L.name == n) & (L.t_from >= 100)].dt_mean.mean()
              for n in sm)
    out("smallest dt / late mean dt, the 5 smooth a180 runs (start-ups)", ">= 0.62", f"{dsm:.3f}", near(dsm, 0.62, 0.005))
    d_lm = lm0[lm0.t_from >= 10].dt_min.min() / lm0[lm0.t_from >= 100].dt_mean.mean()
    d_lmj = lm0[lm0.t_from >= 50].dt_min.min() / quiet.dt_mean.mean()
    out("  the LM a0 jump run (start-up; jump phase vs 60-100 c/U)", ">= 0.62",
        f"{d_lm:.3f} (at {lm0.loc[lm0[lm0.t_from >= 10].dt_min.idxmin(), 't_from']:.0f} c/U); {d_lmj:.3f}",
        d_lm >= 0.615 and d_lmj >= 0.615)
    share = L[L.t_from >= 50].groupby("name").p_share_gt_0p05.mean()
    out("residual signature (>50 % of window steps with first p > 0.05)", "none (Stage 1 term)",
        f"max share {share.max():.3f} ({share.idxmax()})", share.max() < 0.5)
    st = T[(T.wall == "wf") & T.name.isin(new.name)].St_peak_frac
    out("new wf runs: St peak share", ">= 0.966", f"{st.min():.4f}", near(st.min(), 0.966, 0.0005))


def check_R2():
    print("\n== R2 wall functions at alpha 90 and 180, maxCo 5 against 2.5")
    q180 = {2.5: (0.19, 0.75, 2.21, 5.50), 5.0: (0.22, 1.12, 2.43, 5.81)}
    rq = (4.3, 17.8, 87.2, 43.0)
    eff = {}
    for a in (90, 180):
        for co in (2.5, 5.0):
            for k in (50, 100, 200, 400):
                eff[(a, co, k)] = chg(wfname(a, 0, co), wfname(a, k, co))
    got = [eff[(180, 2.5, k)] for k in (50, 100, 200, 400)]
    out("a180 maxCo 2.5: % at Ks 50/100/200/400", "/".join(f"{x:+.2f}" for x in q180[2.5]),
        "/".join(f"{g[1]:+.2f}" for g in got), all(near(g[1], x, 0.005) for g, x in zip(got, q180[2.5])))
    out("  ratio to noise", "/".join(str(x) for x in rq), "/".join(f"{g[3]:.1f}" for g in got),
        all(near(g[3], x, 0.05) for g, x in zip(got, rq)))
    out("  Cd Ks 0 -> 400", "1.6218 -> 1.7110", f"{row(wfname(180, 0, 2.5)).Cd_mean:.4f} -> "
        f"{row(wfname(180, 400, 2.5)).Cd_mean:.4f}", near(row(wfname(180, 0, 2.5)).Cd_mean, 1.6218, 5e-5) and
        near(row(wfname(180, 400, 2.5)).Cd_mean, 1.7110, 5e-5))
    got5 = [eff[(180, 5.0, k)] for k in (50, 100, 200, 400)]
    out("a180 maxCo 5: % at Ks 50/100/200/400 (Ks 50 n.r. 0.67x)", "/".join(f"{x:+.2f}" for x in q180[5.0]),
        "/".join(f"{g[1]:+.2f}" for g in got5) + f" (Ks50 {got5[0][3]:.2f}x)",
        all(near(g[1], x, 0.005) for g, x in zip(got5, q180[5.0])) and near(got5[0][3], 0.67, 0.005))
    q90 = {2.5: (0.73, 4.82, 17.27, 45.43), 5.0: (0.54, 4.72, 16.84, 44.40)}
    for co in (2.5, 5.0):
        g = [eff[(90, co, k)] for k in (50, 100, 200, 400)]
        out(f"a90 maxCo {co:g}: % at Ks 50/100/200/400", "/".join(f"{x:+.2f}" for x in q90[co]),
            "/".join(f"{x[1]:+.2f}" for x in g), all(near(x[1], y, 0.005) for x, y in zip(g, q90[co])))
        print(f"      a90 maxCo {co:g} ratios to noise: " + "/".join(f"{x[3]:.0f}" for x in g))
    out("a90 Cd Ks 0 -> 400 at maxCo 2.5", "0.1932 -> 0.2810", f"{row(wfname(90, 0, 2.5)).Cd_mean:.4f} -> "
        f"{row(wfname(90, 400, 2.5)).Cd_mean:.4f}", near(row(wfname(90, 0, 2.5)).Cd_mean, 0.1932, 5e-5) and
        near(row(wfname(90, 400, 2.5)).Cd_mean, 0.2810, 5e-5))
    dpp = [abs(eff[(a, 5.0, k)][1] - eff[(a, 2.5, k)][1]) for a in (90, 180) for k in (50, 100, 200, 400)]
    out("largest change of an effect between maxCo (pp), R2 text", "1.03", f"{max(dpp):.3f} (UPDATE.md: 1.02)",
        near(max(dpp), 1.03, 0.005))
    sg = all(np.sign(eff[(a, 5.0, k)][0]) == np.sign(eff[(a, 2.5, k)][0]) for a in (90, 180) for k in (50, 100, 200, 400))
    sgl = all(np.sign(chg(wfname(a, 0, 5.0), wfname(a, k, 5.0), "Cl")[0]) ==
              np.sign(chg(wfname(a, 0, 2.5), wfname(a, k, 2.5), "Cl")[0]) for a in (90, 180) for k in (50, 100, 200, 400))
    out("every Cd and Cl effect keeps its sign", "yes", f"Cd {sg}, Cl {sgl}", sg and sgl)
    e5, e25 = eff[(180, 5.0, 400)], eff[(180, 2.5, 400)]
    out("a180 Ks400 effect maxCo 5 / 2.5; diff vs noise", "0.0955 / 0.0892; 0.0063 > 0.0027",
        f"{e5[0]:.4f} / {e25[0]:.4f}; {e5[0] - e25[0]:.4f} vs {e5[2] + e25[2]:.4f}",
        near(e5[0], 0.0955, 5e-5) and near(e25[0], 0.0892, 5e-5) and near(e5[0] - e25[0], 0.0063, 5e-5) and
        near(e5[2] + e25[2], 0.0027, 5e-5))
    for a, co, qv in ((90, 5.0, 64.1), (90, 2.5, 67.0)):
        d = chg(wfname(a, 0, co), wfname(a, 400, co), "Cl")
        out(f"Cl a{a} Ks400 maxCo {co:g}", f"+{qv} %", f"{d[1]:+.2f} %", near(d[1], qv, 0.05))
    for co, qv in ((5.0, 6.4), (2.5, 7.3)):
        c0, c4 = row(wfname(180, 0, co)).Cl_mean, row(wfname(180, 400, co)).Cl_mean
        v = 100 * (abs(c4) - abs(c0)) / abs(c0)
        out(f"|Cl| a180 Ks400 maxCo {co:g}", f"-{qv} %", f"{v:+.2f} %", near(v, -qv, 0.05))
    s0, s4 = row(wfname(90, 0, 2.5)).St, row(wfname(90, 400, 2.5)).St
    s05, s45 = row(wfname(90, 0, 5.0)).St, row(wfname(90, 400, 5.0)).St
    out("a90 St 0.6022 -> 0.5129; -14.83 % (2.5), -14.78 % (5)", "0.6022->0.5129; -14.83/-14.78",
        f"{s0:.4f}->{s4:.4f}; {pct(s4, s0):.2f}/{pct(s45, s05):.2f}",
        near(s0, 0.6022, 5e-5) and near(s4, 0.5129, 5e-5) and near(pct(s4, s0), -14.83, 0.005) and
        near(pct(s45, s05), -14.78, 0.005))
    for a, q in ((90, (0.49, 1.20)), (180, (1.26, 1.63))):
        v = []
        res = []
        for k in (0, 50, 100, 200, 400):
            d = chg(wfname(a, k, 2.5), wfname(a, k, 5.0))
            v.append(d[1])
            res.append(d[3] > 1)
        out(f"abs Cd maxCo 5 above 2.5, alpha {a}", f"+{q[0]} to +{q[1]} %, resolved",
            f"{min(v):+.2f} to {max(v):+.2f} %, resolved {sum(res)}/5",
            near(min(v), q[0], 0.005) and near(max(v), q[1], 0.005) and all(res))
    r0, r4 = row(wfname(180, 0, 2.5)), row(wfname(180, 400, 2.5))
    share = (r4.Cd_pressure_mean - r0.Cd_pressure_mean) / (r4.Cd_mean - r0.Cd_mean)
    out("a180 Ks400 maxCo 2.5: pressure share of the rise; viscous Cd", "88.2 %; 0.0085 -> 0.0190",
        f"{100 * share:.1f} %; {r0.Cd_viscous_mean:.4f} -> {r4.Cd_viscous_mean:.4f}",
        near(100 * share, 88.2, 0.05) and near(r0.Cd_viscous_mean, 0.0085, 5e-5) and
        near(r4.Cd_viscous_mean, 0.0190, 5e-5))
    w = T[(T.wall == "wf") & (T.U_ms == 23)]
    out("blade-mean y+ 17-49; Ks/y_P <= 0.91 (wf, 23 m/s)", "17-49; 0.91",
        f"{T[T.wall == 'wf'].yplus_blade_mean.min():.1f}-{T[T.wall == 'wf'].yplus_blade_mean.max():.1f}; "
        f"{T[T.wall == 'wf'].Ks_over_yP.max():.3f}",
        near(T[T.wall == 'wf'].yplus_blade_mean.min(), 17, 0.5) and near(T[T.wall == 'wf'].yplus_blade_mean.max(), 49, 0.5))
    stw = T[(T.wall == "wf") & (T.alpha_deg == 180)].St
    out("a180 wf St range", "0.236-0.239", f"{stw.min():.4f}-{stw.max():.4f}", near(stw.min(), 0.236, 0.0006) and
        near(stw.max(), 0.239, 0.0006))
    mig = row("a180.0_U23.0_SST_wf_Ks50_Tu1.0")
    print(f"      a180 Ks50 maxCo 5 (migrated): drift {mig.Cd_drift:+.5f}; others' |drift| "
          f"{T[(T.wall == 'wf') & (T.alpha_deg == 180) & (T.maxCo == 5) & (T.Ks_um != 50)].Cd_drift.abs().max():.5f}")


def Dset(pairs):
    """[(label, alpha-0 case, alpha-180 case)] -> D, own noise, change vs first, % and ratio to noise."""
    out_ = []
    a0, b0 = row(pairs[0][1]), row(pairs[0][2])
    D0, n0 = a0.Cd_mean - b0.Cd_mean, abs(a0.Cd_drift) + abs(b0.Cd_drift)
    for lab, x0, x1 in pairs:
        a, b = row(x0), row(x1)
        D, n = a.Cd_mean - b.Cd_mean, abs(a.Cd_drift) + abs(b.Cd_drift)
        out_.append(dict(lab=lab, D=D, n=n, dD=D - D0, pct=100 * (D - D0) / D0, ratio=abs(D - D0) / (n + n0),
                         d0=a.Cd_mean - a0.Cd_mean, d180=b.Cd_mean - b0.Cd_mean))
    return pd.DataFrame(out_)


def check_R3(H):
    print("\n== R3 drag difference D (wall functions)")
    s = Dset([(k, wfname(0, k, 2.5), wfname(180, k, 2.5)) for k in (0, 50, 100, 200, 400)])
    qD = (1.4860, 1.4722, 1.4173, 1.3581, 1.2098)
    out("D at Ks 0/50/100/200/400, both maxCo 2.5", "/".join(f"{x:.4f}" for x in qD),
        "/".join(f"{x:.4f}" for x in s.D), all(near(a, b, 5e-5) for a, b in zip(s.D, qD)))
    qp = (-0.93, -4.63, -8.61, -18.59)
    out("  changes %", "/".join(str(x) for x in qp), "/".join(f"{x:.2f}" for x in s.pct[1:]),
        all(near(a, b, 0.005) for a, b in zip(s.pct[1:], qp)))
    out("  ratio at Ks 200 / 400", "1.01 / 1.76", f"{s.ratio[3]:.3f} / {s.ratio[4]:.3f}",
        near(s.ratio[3], 1.01, 0.005) and near(s.ratio[4], 1.76, 0.005))
    out("  Ks 400: alpha-0 fall, alpha-180 rise, alpha-0 share", "0.1870, 0.0892, 68 %",
        f"{-s.d0[4]:.4f}, {s.d180[4]:.4f}, {100 * s.d0[4] / s.dD[4]:.1f} %",
        near(-s.d0[4], 0.1870, 5e-5) and near(s.d180[4], 0.0892, 5e-5) and near(100 * s.d0[4] / s.dD[4], 68, 0.5))
    s5 = Dset([(k, wfname(0, k, 5.0), wfname(180, k, 5.0)) for k in (50, 200, 400)])
    out("maxCo 5 vs Ks 50: Ks 200 / 400 (% and ratio)", "-8.81 (0.67x) / -17.69 (1.47x)",
        f"{s5.pct[1]:.2f} ({s5.ratio[1]:.2f}x) / {s5.pct[2]:.2f} ({s5.ratio[2]:.2f}x)",
        near(s5.pct[1], -8.81, 0.005) and near(s5.ratio[1], 0.67, 0.005) and near(s5.pct[2], -17.69, 0.005) and
        near(s5.ratio[2], 1.47, 0.005))
    sm = Dset([(k, wfname(0, k, 2.5), wfname(180, k, 5.0)) for k in (0, 400)])
    out("13 Oct mixed set at Ks 400", "-19.27 %", f"{sm.pct[1]:.2f} %", near(sm.pct[1], -19.27, 0.005))
    w0 = T[(T.wall == "wf") & (T.alpha_deg == 0)]
    st = H.loc[w0.name].state
    out("every wf alpha-0 run high-drag; Cd range", "yes; 2.921-3.146",
        f"{(st == 'high').all()} ({len(st)} runs); {w0.Cd_mean.min():.3f}-{w0.Cd_mean.max():.3f}",
        (st == "high").all() and near(w0.Cd_mean.min(), 2.921, 0.0005) and near(w0.Cd_mean.max(), 3.146, 0.0005))
    nd = [100 * chg(wfname(0, 0, 2.5), wfname(0, k, 2.5))[2] / row(wfname(0, 0, 2.5)).Cd_mean for k in (50, 100, 200, 400)]
    out("noise of the alpha-0 wf changes (23 m/s, maxCo 2.5), % of Cd", "3.4-5.0 % ('drifts')",
        f"{min(nd):.2f}-{max(nd):.2f} %", near(min(nd), 3.4, 0.05) and near(max(nd), 5.0, 0.05))
    # two-position drive change for lambda 0-0.25 (inferred model)
    lam = np.linspace(0, 0.25, 26)
    dN = [s.d0[i] * (1 - lam) ** 2 - s.d180[i] * (1 + lam) ** 2 for i in range(1, 5)]
    out("two-position dN < 0 for lambda 0-0.25 (Ks 50-400, maxCo 2.5)", "all negative",
        str([bool((x < 0).all()) for x in dN]), all((x < 0).all() for x in dN))


def win_change(H, ref, x, lab):
    a, b = H.loc[ref], H.loc[x]
    d = b[f"Cd_{lab}"] - a[f"Cd_{lab}"]
    n = abs(a[f"drift_{lab}"]) + abs(b[f"drift_{lab}"])
    return 100 * d / a[f"Cd_{lab}"], abs(d) / n


def check_R4(H, SF):
    print("\n== R4 SST texture at alpha 180")
    s0, s2 = txname(180, "SST", 0, 2.5), txname(180, "SST", 0.2, 2.5)
    d = chg(s0, s2)
    out("Cd t0 / t0.2, change, noise % of Cd, ratio", "0.9026/1.0255, +13.62 %, 2.41 %, 5.65x",
        f"{row(s0).Cd_mean:.4f}/{row(s2).Cd_mean:.4f}, {d[1]:+.2f} %, {100 * d[2] / row(s0).Cd_mean:.2f} %, "
        f"{d[3]:.2f}x", near(d[1], 13.62, 0.005) and near(100 * d[2] / row(s0).Cd_mean, 2.41, 0.005) and
        near(d[3], 5.65, 0.005))
    p30, r30 = win_change(H, s0, s2, "30_80")
    p100, r100 = win_change(H, s0, s2, "100_150")
    out("on 30-80 / 100-150 c/U", "+15.48 / +13.02 %", f"{p30:+.2f} ({r30:.1f}x) / {p100:+.2f} ({r100:.1f}x)",
        near(p30, 15.48, 0.005) and near(p100, 13.02, 0.005))
    d5 = chg(txname(180, "SST", 0, 5.0), txname(180, "SST", 0.2, 5.0))
    out("maxCo 5", "+13.68 % (3.15x)", f"{d5[1]:+.2f} % ({d5[3]:.2f}x)", near(d5[1], 13.68, 0.005) and
        near(d5[3], 3.15, 0.005))
    for t, qs, qo in ((0.0, -17.47, -18.56), (0.2, -16.16, -18.60)):
        c5, c25 = txname(180, "SST", t, 5.0), txname(180, "SST", t, 2.5)
        same = pct(H.loc[c25].Cd_30_80, row(c5).Cd_mean)
        ns = abs(H.loc[c25].drift_30_80) + abs(row(c5).Cd_drift)
        own_ = chg(c5, c25)
        out(f"maxCo 5 -> 2.5, t {t}: same window / own windows", f"{qs} / {qo} %, resolved",
            f"{same:.2f} ({abs(H.loc[c25].Cd_30_80 - row(c5).Cd_mean) / ns:.1f}x) / {own_[1]:.2f} ({own_[3]:.1f}x)",
            near(same, qs, 0.011) and near(own_[1], qo, 0.005))
    out("smooth Co2.5: St, peak share, Cl; textured peak share, Cl", "0.2185, 0.994, -0.974; 0.057, -0.609",
        f"{row(s0).St:.4f}, {row(s0).St_peak_frac:.3f}, {row(s0).Cl_mean:.3f}; {row(s2).St_peak_frac:.3f}, "
        f"{row(s2).Cl_mean:.3f}", near(row(s0).St, 0.2185, 5e-5) and near(row(s0).St_peak_frac, 0.994, 0.0005) and
        near(row(s2).St_peak_frac, 0.057, 0.0005) and near(row(s2).Cl_mean, -0.609, 0.0005))
    print(f"      maxCo 5: smooth peak share {row(txname(180, 'SST', 0, 5.0)).St_peak_frac:.3f}, textured "
          f"{row(txname(180, 'SST', 0.2, 5.0)).St_peak_frac:.3f} (regimes swap between the time steps)")
    print(f"      end slope (last 50 c/U, per 100 c/U): smooth {H.loc[s0].slope_last50_per100:+.4f}, textured "
          f"{H.loc[s2].slope_last50_per100:+.4f}")
    a, b = SF[s0], SF[s2]
    out("convex / concave / ends pressure drag (smooth, t0.2)", "0.088/0.738/0.061; 0.279/0.692/0.055",
        f"{a['convex']:.3f}/{a['concave']:.3f}/{a['ends']:.3f}; {b['convex']:.3f}/{b['concave']:.3f}/{b['ends']:.3f}",
        all(near(a[k], v, 0.0005) for k, v in (("convex", 0.088), ("concave", 0.738), ("ends", 0.061))) and
        all(near(b[k], v, 0.0005) for k, v in (("convex", 0.279), ("concave", 0.692), ("ends", 0.055))))
    out("  sum vs table Cd_pressure", "match", f"{a['total']:.4f}/{a['Cdp_tab']:.4f}; {b['total']:.4f}/"
        f"{b['Cdp_tab']:.4f}", near(a["total"], a["Cdp_tab"], 2e-5) and near(b["total"], b["Cdp_tab"], 2e-5))
    out("tip-B half suction peak (1 mm), smooth -> t0.2", "-3.19 -> -1.81", f"{a['CpminB']:.3f} -> {b['CpminB']:.3f}",
        near(a["CpminB"], -3.19, 0.005) and near(b["CpminB"], -1.81, 0.005))
    out("tip-B half pressure drag", "-0.13 (thrust) -> +0.04", f"{a['CdpB']:+.4f} -> {b['CdpB']:+.4f}",
        near(a["CdpB"], -0.13, 0.005) and near(b["CdpB"], 0.04, 0.005))
    print(f"      tip-A half: {a['CdpA']:+.4f} -> {b['CdpA']:+.4f}; share of the convex rise from the B half "
          f"{100 * (b['CdpB'] - a['CdpB']) / (b['convex'] - a['convex']):.0f} %")
    out("suction peak sits on surface facing ... (caption: 'looks downstream')", "downstream",
        f"n_out.upstream = {a['CpminB_facing_up']:+.3f} at s/c {a['CpminB_at']:.3f} from stag.; the face turns "
        f"downstream-facing only at {a['turn_down_at']:.3f} (tip {a['tipB']:.3f})", a["CpminB_facing_up"] < 0)


def check_LM(H, SF):
    print("\n== LM texture (UPDATE.md section 6 and figure captions)")
    l0 = txname(180, "LM", 0, 2.5)
    q = {(0.1, 2.5): 15.28, (0.2, 2.5): 8.61, (0.1, 5.0): -1.30, (0.2, 5.0): 0.36}
    for (t, co), v in q.items():
        d = chg(txname(180, "LM", 0, co), txname(180, "LM", t, co))
        out(f"LM a180 23 m/s t {t} maxCo {co:g}", f"{v:+.2f} %", f"{d[1]:+.2f} % ({d[3]:.2f}x)", near(d[1], v, 0.005))
    same = pct(H.loc[l0].Cd_30_80, row(txname(180, "LM", 0, 5.0)).Cd_mean)
    out("smooth LM a180, maxCo 5 -> 2.5 on 30-80 c/U", "-13.84 %", f"{same:.2f} %", near(same, -13.84, 0.005))
    for t in (0.1, 0.2):
        v = pct(H.loc[txname(180, "LM", t, 2.5)].Cd_30_80, row(txname(180, "LM", t, 5.0)).Cd_mean)
        print(f"      textured LM t {t}: maxCo 5 -> 2.5 on 30-80 c/U {v:+.2f} %")
    qU = {18.8: 0.04, 20.9: 7.31, 23.0: 8.61, 25.2: 8.50}
    for U, v in qU.items():
        d = chg(txname(180, "LM", 0, 2.5, U), txname(180, "LM", 0.2, 2.5, U))
        pl, rl = win_change(H, txname(180, "LM", 0, 2.5, U), txname(180, "LM", 0.2, 2.5, U), "100_150")
        out(f"LM a180 t0.2 effect at {U} m/s", f"{v:+.2f} %", f"{d[1]:+.2f} % ({d[3]:.2f}x); last 50 c/U "
            f"{pl:+.2f} % ({rl:.1f}x)", near(d[1], v, 0.005) and ((d[3] > 1) == (U != 18.8)))
    c = [row(txname(180, "LM", 0, 2.5, U)).Cd_mean for U in (18.8, 20.9)]
    tex = [row(txname(180, "LM", 0.2, 2.5, U)).Cd_mean for U in (18.8, 20.9, 23.0, 25.2)]
    out("smooth LM 18.8 -> 20.9; textured spread 18.8-25.2", "-6.50 %; within 1.60 %",
        f"{pct(c[1], c[0]):.2f} %; {100 * (max(tex) / min(tex) - 1):.2f} %",
        near(pct(c[1], c[0]), -6.50, 0.005) and near(100 * (max(tex) / min(tex) - 1), 1.60, 0.005))
    for U in (18.8, 20.9, 23.0, 25.2):
        r = SF[txname(180, "LM", 0, 2.5, U)]
        print(f"      smooth LM {U}: tip-B separation {r['sepB']:.3f} c from stag., tip at {r['tipB']:.3f} c "
              f"-> {r['tipB'] - r['sepB']:.3f} c before the tip; convex Cd_p {r['convex']:.4f}, concave "
              f"{r['concave']:.4f}; B-half Cp min {r['CpminB']:.3f}")
    r = SF[txname(180, "LM", 0, 2.5, 18.8)]
    r2 = SF[txname(180, "LM", 0, 2.5, 20.9)]
    out("smooth LM tip-B layer separates 0.17 c before the tip at 18.8, not at 20.9", "0.17 c",
        f"{r['tipB'] - r['sepB']:.3f} c; at 20.9: {r2['tipB'] - r2['sepB']:.3f} c",
        near(r["tipB"] - r["sepB"], 0.17, 0.005))
    cv = {U: (SF[txname(180, "LM", 0, 2.5, U)]["convex"], SF[txname(180, "LM", 0.2, 2.5, U)]["convex"])
          for U in (18.8, 20.9, 23.0, 25.2)}
    print("      convex-face pressure drag smooth / t0.2: " +
          "; ".join(f"{U}: {a:.3f}/{b:.3f}" for U, (a, b) in cv.items()))
    cc0 = [SF[txname(180, "LM", 0, 2.5, U)]["concave"] for U in (18.8, 20.9, 23.0, 25.2)]
    cc2 = [SF[txname(180, "LM", 0.2, 2.5, U)]["concave"] for U in (18.8, 20.9, 23.0, 25.2)]
    out("fig 6c: concave LM smooth / t0.2 ranges", "0.696-0.715 / 0.701-0.728",
        f"{min(cc0):.3f}-{max(cc0):.3f} / {min(cc2):.3f}-{max(cc2):.3f}",
        near(min(cc0), 0.696, 0.0005) and near(max(cc0), 0.715, 0.0005) and near(min(cc2), 0.701, 0.0005) and
        near(max(cc2), 0.728, 0.0005))
    tx = [cv[U][1] for U in cv]
    out("fig 6c: textured convex drag 'stays flat' 18.8-25.2", "flat", f"{min(tx):.3f}-{max(tx):.3f} "
        f"({100 * (max(tx) / min(tx) - 1):.1f} % spread; smooth {cv[18.8][0]:.3f}->{cv[20.9][0]:.3f})",
        max(tx) / min(tx) - 1 < 0.05)
    # SST against LM, smooth, alpha 180
    d = chg(txname(180, "LM", 0, 2.5), txname(180, "SST", 0, 2.5))
    out("smooth SST vs LM, a180, texture mesh, maxCo 2.5", "-5.43 %", f"{d[1]:+.2f} % ({d[3]:.2f}x)",
        near(d[1], -5.43, 0.005))
    S1 = pd.read_csv(SEC).set_index("name")
    sst, lm = S1.loc["a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2"], S1.loc["a180.0_U23.0_LM_medium_Tu1.0_Co2.5n2"]
    v = pct(sst.Cd_mean, lm.Cd_mean)
    out("smooth SST vs LM, a180, medium mesh, maxCo 2.5", "+13.01 %", f"{v:+.2f} % "
        f"({abs(sst.Cd_mean - lm.Cd_mean) / (abs(sst.Cd_drift) + abs(lm.Cd_drift)):.1f}x)", near(v, 13.01, 0.005))
    # alpha-0 states of the texture runs at maxCo 2.5
    for m, qv in (("SST", 35), ("LM", 135)):
        out(f"smooth {m} a0 Co2.5 leaves the high-drag state at", f"{qv} c/U",
            f"{H.loc[txname(0, m, 0, 2.5)].high_last:.1f} c/U; state in window {H.loc[txname(0, m, 0, 2.5)].state}",
            near(H.loc[txname(0, m, 0, 2.5)].high_last, qv, 0.5))
    st = H.loc[[n for n in T.name if n.startswith("a000") and "_tex" in n]].state
    print("      alpha-0 texture states: " + ", ".join(f"{n.split('_')[2]} t{n.split('tex')[1][:5]} "
                                                    f"{'Co2.5' if n.endswith('n2') else 'Co5'}: {v}"
                                                    for n, v in st.items()))
    D = row(txname(0, "LM", 0, 2.5)).Cd_mean - row(l0).Cd_mean
    out("fig 2b: LM maxCo 2.5 t0 D", "1.86", f"{D:.3f}", near(D, 1.86, 0.005))
    # fig 3 caption: alpha-180 maxCo-2.5 levels 16-19 % below maxCo 5
    v = {(m, t): chg(txname(180, m, t, 5.0), txname(180, m, t, 2.5))[1] for m, t in
         (("SST", 0), ("SST", 0.2), ("LM", 0), ("LM", 0.1), ("LM", 0.2))}
    out("fig 3: a180 maxCo-2.5 levels 16-19 % below maxCo 5", "16-19 %",
        "; ".join(f"{m} t{t}: {x:.1f}" for (m, t), x in v.items()), all(-19.5 < x < -15.5 for x in v.values()))
    # fig 4 caption: "at alpha 180 the textured runs are still decaying at 150 c/U, while the smooth maxCo-2.5 runs settle"
    sl = {n: H.loc[n].slope_last50_per100 for n in (txname(180, "SST", 0, 2.5), txname(180, "SST", 0.2, 2.5),
                                                    txname(180, "LM", 0, 2.5), txname(180, "LM", 0.1, 2.5),
                                                    txname(180, "LM", 0.2, 2.5))}
    v = list(sl.values())
    out("fig 4: a180 end slopes /100 c/U: smooth SST, LM settle; textured decay", "smooth settle",
        f"SST t0 {v[0]:+.4f}, t0.2 {v[1]:+.4f}; LM t0 {v[2]:+.4f}, t0.1 {v[3]:+.4f}, t0.2 {v[4]:+.4f}",
        abs(v[2]) < 0.5 * abs(v[4]))
    # SST alpha-0 texture effect at maxCo 2.5, by window
    a, b = txname(0, "SST", 0, 2.5), txname(0, "SST", 0.2, 2.5)
    d = chg(a, b)
    pl, rl = win_change(H, a, b, "100_150")
    print(f"      SST a0 t0.2 vs t0, maxCo 2.5: window {d[1]:+.2f} % ({d[3]:.2f}x); last 50 c/U {pl:+.2f} % "
          f"({rl:.2f}x); smooth end slope {H.loc[a].slope_last50_per100:+.4f}/100 c/U, drift {row(a).Cd_drift:+.4f}")


def check_bottom_line():
    print("\n== Bottom line (UPDATE.md section 6, figure 7)")
    rows = []

    def add(q, need, ref, x, kind):
        d = chg(ref, x)
        rows.append(dict(q=q, need=need, ref=ref, x=x, pct=d[1], ratio=d[3], kind=kind))

    def addD(need, p0, p1, kind):
        s = Dset([("0", *p0), ("1", *p1)])
        rows.append(dict(q="D", need=need, ref=p0[0], x=p1[0], pct=s.pct[1], ratio=s.ratio[1], kind=kind))
    # rough wall functions, alpha 0 and 180, against Ks 0 (Ks 50 where Ks 0 diverged)
    for U, co, ks, ref in ((23.0, 2.5, (50, 100, 200, 400), 0), (23.0, 5.0, (200, 400), 50),
                           (10.2, 2.5, (100, 200), 0), (38.0, 2.5, (100, 200), 0), (38.0, 5.0, (100, 200), 0)):
        for k in ks:
            add("Cd(0)", "+", wfname(0, ref, co, U), wfname(0, k, co, U), "wf")
    for co in (2.5, 5.0):
        for k in (50, 100, 200, 400):
            add("Cd(180)", "-", wfname(180, 0, co), wfname(180, k, co), "wf")
    for co, ks, ref in ((2.5, (50, 100, 200, 400), 0), (5.0, (200, 400), 50)):
        for k in ks:
            addD("+", (wfname(0, ref, co), wfname(180, ref, co)), (wfname(0, k, co), wfname(180, k, co)), "wf")
    # texture: same model, maxCo, speed, window; alpha 0 only within one state (LM maxCo 2.5 t0 excluded)
    for m in ("SST", "LM"):
        for t in (0.05, 0.1, 0.2):
            add("Cd(0)", "+", txname(0, m, 0, 5.0), txname(0, m, t, 5.0), "tex")
            add("Cd(180)", "-", txname(180, m, 0, 5.0), txname(180, m, t, 5.0), "tex")
            addD("+", (txname(0, m, 0, 5.0), txname(180, m, 0, 5.0)), (txname(0, m, t, 5.0), txname(180, m, t, 5.0)),
                 "tex")
    add("Cd(0)", "+", txname(0, "SST", 0, 2.5), txname(0, "SST", 0.2, 2.5), "tex")
    add("Cd(180)", "-", txname(180, "SST", 0, 2.5), txname(180, "SST", 0.2, 2.5), "tex")
    addD("+", (txname(0, "SST", 0, 2.5), txname(180, "SST", 0, 2.5)),
         (txname(0, "SST", 0.2, 2.5), txname(180, "SST", 0.2, 2.5)), "tex")
    for t in (0.1, 0.2):
        add("Cd(180)", "-", txname(180, "LM", 0, 2.5), txname(180, "LM", t, 2.5), "tex")
    for U in (18.8, 20.9, 25.2):
        add("Cd(180)", "-", txname(180, "LM", 0, 2.5, U), txname(180, "LM", 0.2, 2.5, U), "tex")
    B = pd.DataFrame(rows)
    B["res"] = B.ratio > 1
    B["as_needed"] = np.where(B.need == "+", B.pct > 0, B.pct < 0)
    out("fair comparisons / resolved / resolved with wrong sign", "52 / 21 / 21",
        f"{len(B)} / {int(B.res.sum())} / {int((B.res & ~B.as_needed).sum())}",
        len(B) == 52 and B.res.sum() == 21 and (B.res & ~B.as_needed).sum() == 21)
    nd = B[B.as_needed]
    out("needed sign / resolved / largest ratio", "8 / 0 / 0.743", f"{len(nd)} / {int(nd.res.sum())} / "
        f"{nd.ratio.max():.3f}", len(nd) == 8 and nd.res.sum() == 0 and near(nd.ratio.max(), 0.743, 0.0005))
    print("      needed-sign rows: " + "; ".join(f"{r.q} {r.x.split('_Tu')[0]} {r.pct:+.2f} % ({r.ratio:.2f}x)"
                                               for r in nd.itertuples()))
    print(f"      by family: wf {int((B.kind == 'wf').sum())} ({int(B[B.kind == 'wf'].res.sum())} resolved), "
          f"tex {int((B.kind == 'tex').sum())} ({int(B[B.kind == 'tex'].res.sum())} resolved)")
    return B


def check_measured():
    print("\n== Measured (report build) and the required section change")
    c = pd.read_csv(RIG / "comparisons.csv")
    c = c[c.relative_to == "Plain"].set_index("rotor")
    for r, q in (("FS 0.10", (12.8, 10.1, 15.5)), ("FS 0.20", (16.2, 13.5, 19.0))):
        v = c.loc[r]
        out(f"{r} mean gain [Tukey 95 %]", f"{q[0]} [{q[1]}, {q[2]}]",
            f"{v.change_pct:.1f} [{v.tukey95_lo_pct:.1f}, {v.tukey95_hi_pct:.1f}]",
            near(v.change_pct, q[0], 0.05) and near(v.tukey95_lo_pct, q[1], 0.05) and near(v.tukey95_hi_pct, q[2], 0.05))
    b = pd.read_csv(RIG / "rotor_by_wind_speed.csv")
    for U, q in ((18.765, (12.6, 11.1)), (20.8972, (31.5, 4.3))):
        v = b[(b.rotor == "FS 0.20") & np.isclose(b.wind_mps, U)].iloc[0]
        out(f"FS 0.20 at {U:.3f} m/s (pointwise 95 %)", f"{q[0]} +- {q[1]}",
            f"{v.p_max_change_vs_plain_pct:.1f} +- {v.pointwise95_halfwidth_pct:.1f}",
            near(v.p_max_change_vs_plain_pct, q[0], 0.05) and near(v.pointwise95_halfwidth_pct, q[1], 0.05))
    lam = 0.125
    w0, w1 = (1 - lam) ** 2, (1 + lam) ** 2
    refs = {"shell": (2.3, 1.2), "wf Ks0 maxCo 2.5": (row(wfname(0, 0, 2.5)).Cd_mean, row(wfname(180, 0, 2.5)).Cd_mean)}
    v = []
    for k, (a, b_) in refs.items():
        N = a * w0 - b_ * w1
        for g in (c.loc["FS 0.10"].change_pct, c.loc["FS 0.20"].change_pct):
            v.append(-g / 100 * N / (w1 * b_) * 100)
    out("Cd(180) change the mean gains need (two-position, lambda 0.125)", "-2.0 to -2.6 %",
        f"{max(v):.2f} to {min(v):.2f} %", near(max(v), -2.0, 0.05) and near(min(v), -2.6, 0.05))


def check_missed(H, SF):
    print("\n== Reviewer: findings missing from the analysis (computed here)")
    S1 = pd.read_csv(SEC).set_index("name")
    for m, q in (("SST", None), ("LM", None)):
        tex = row(txname(180, m, 0, 2.5)).Cd_mean
        med = S1.loc[f"a180.0_U23.0_{m}_medium_Tu1.0_Co2.5n2"].Cd_mean
        extra = ""
        if m == "SST":
            co = S1.loc["a180.0_U23.0_SST_coarse_Tu1.0_Co2.5n2"].Cd_mean
            fi = S1.loc["a180.0_U23.0_SST_fine_Tu1.0_Co2.5n2"].Cd_mean
            c125 = S1.loc["a180.0_U23.0_SST_medium_Tu1.0_Co1.25n2"].Cd_mean
            extra = f"; coarse {co:.3f}, fine {fi:.3f} ({pct(tex, co):+.1f}, {pct(tex, fi):+.1f} %); medium maxCo 1.25 {c125:.3f}"
        print(f"      smooth {m} a180, maxCo 2.5: texture mesh {tex:.4f} vs Stage 1 medium {med:.4f} ({pct(tex, med):+.1f} %){extra}")
    for lev in ("coarse", "medium", "fine"):
        mi = json.loads((REPO / "cfd" / "section2d" / "runs" / f"a180.0_U23.0_SST_{lev}_Tu1.0_Co2.5n2" / "mesh_info.json").read_text())
        print(f"      Stage 1 {lev}: wall spacing median {1e6 * mi['ring']['edge_spacing_m']['median']:.0f} um")
    mi = json.loads((RUNS / txname(180, "SST", 0, 2.5) / "mesh_info.json").read_text())
    print(f"      texture mesh: wall spacing median {1e6 * mi['ring']['edge_spacing_m']['median']:.0f} um")
    a0t = row(txname(0, "SST", 0, 2.5)).Cd_mean
    a0m = S1.loc["a000.0_U23.0_SST_medium_Tu1.0_Co2.5n2"].Cd_mean
    print(f"      smooth SST a0 (low-drag), maxCo 2.5: texture mesh {a0t:.4f} vs medium {a0m:.4f} ({pct(a0t, a0m):+.1f} %)")
    print("      LM a180 texture runs, St (peak share): " + "; ".join(
        f"{n.split('_')[1]} t{row(n).t:g} Co{row(n).maxCo:g}: {row(n).St:.3f} ({row(n).St_peak_frac:.2f})"
        for n in T.name if n.startswith("a180") and "_LM_tex" in n))
    r1, r2 = SF[txname(180, "LM", 0.1, 2.5)], SF[txname(180, "LM", 0.2, 2.5)]
    print(f"      LM 23 m/s maxCo 2.5, t0.1 vs t0.2: B-half Cp min {r1['CpminB']:.2f} vs {r2['CpminB']:.2f}; B-half Cd_p "
          f"{r1['CdpB']:+.3f} vs {r2['CdpB']:+.3f}; end slope {H.loc[txname(180, 'LM', 0.1, 2.5)].slope_last50_per100:+.4f} vs "
          f"{H.loc[txname(180, 'LM', 0.2, 2.5)].slope_last50_per100:+.4f} /100 c/U")
    for U in (18.8, 20.9, 23.0, 25.2):
        a, b = SF[txname(180, "LM", 0, 2.5, U)], SF[txname(180, "LM", 0.2, 2.5, U)]
        print(f"      LM {U} m/s: B-half suction peak smooth {a['CpminB']:.3f}, t0.2 {b['CpminB']:.3f} "
              f"({'capped' if b['CpminB'] > a['CpminB'] else 'NOT capped'}); convex Cd_p change {b['convex'] - a['convex']:+.3f} "
              f"(A {b['CdpA'] - a['CdpA']:+.3f}, B {b['CdpB'] - a['CdpB']:+.3f})")
    for U in (18.8, 20.9, 23.0, 25.2):
        P = json.loads((RUNS / txname(180, "LM", 0, 2.5, U) / "case.json").read_text())
        print(f"      LM {U} m/s: Re_c {P['ReChord']:.0f}, free-stream nu_t/nu {P['viscosityRatioBody']:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", action="store_true", help="re-parse the solver logs")
    ap.add_argument("--steps", default=None, help="directory of per-step files (t dt p_res) instead of the logs")
    a = ap.parse_args()
    nn = check_table()
    H = run_metrics()
    tab_dev = max((H.Cd_win - H.Cd_tab).abs().max(), (H.drift_win - H.drift_tab).abs().max())
    out("own window means and drifts vs table (max |diff|)", "0", f"{tab_dev:.2e}", tab_dev < 5e-5)
    L = log_blocks(a.logs or a.steps is not None, a.steps)
    SF = {n: surface(n) for n in T.name if n.startswith("a180") and "_tex" in n and n.endswith("Co2.5n2")}
    check_R1(H, L, nn)
    check_R2()
    check_R3(H)
    check_R4(H, SF)
    check_LM(H, SF)
    check_bottom_line()
    check_measured()
    check_missed(H, SF)
    print(f"\n{N_LINES} checks, {N_CHECK} CHECK lines")


if __name__ == "__main__":
    main()
