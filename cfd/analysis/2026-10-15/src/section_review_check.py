#!/usr/bin/env python3
"""Reviewer's independent check of the Stage 1 (smooth section) findings S1-S9 of 15 Oct 2026.

    nice -n 10 python3 cfd/analysis/2026-10-15/src/section_review_check.py          # about 3 s with the cache
    nice -n 10 python3 cfd/analysis/2026-10-15/src/section_review_check.py --logs   # re-parse the 49 GB of logs (~15 min)

Written in the review of 19 Oct 2026. It shares no code with section_lib.py, section_histories.py,
section_analysis.py, section_figures.py, section_verify.py or cfd/post:
  - forces: its own reader of postProcessing/forceCoeffs1/<t>/coefficient.dat (sessions sorted by start
    time; a later session replaces the earlier one from its first sample on);
  - solver logs: grep for the deltaT / Time / 'PIMPLE: iteration 1' / p-solve lines, then the first
    p solve of iteration 1 of each step; per-case summary cached in ../out/section_review_residuals.csv;
  - wall data: its own search in records/<case>/fields/surface_mean.csv;
  - lift cycles: scipy.signal.find_peaks on a 1-c/U pandas rolling mean.
Each line prints the analyst's quoted value, the recomputed one and OK, or CHECK where the quoted text is
wrong (the review's corrections). Definitions are those of the analysis (13 Oct flag; jump = |dCd| > 0.5
between samples, its 1-c/U interval counted in the 50-150 c/U window; residual share = share of window
steps whose first p solve starts above 0.05; drift = second-half minus first-half window mean).
Reads only; writes nothing but the residual cache.
"""
import argparse
import json
import subprocess
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

REPO = Path(__file__).resolve().parents[4]
RUNS = REPO / "cfd" / "section2d" / "runs"
REC = REPO / "cfd" / "section2d" / "results" / "records"
CACHE = Path(__file__).resolve().parents[1] / "out" / "section_review_residuals.csv"
DX = {"coarse": 64e-6, "medium": 45e-6, "fine": 32e-6}
EXTRA = ["_unity_a000.0_U23.0_SST_medium_Tu1.0", "_hyst_Co5to2p5_a000", "_hyst_Co2p5to5_a000"]
N_CHECK = 0


def out(label, quoted, got, ok):
    global N_CHECK
    N_CHECK += not ok
    print(f"{'OK   ' if ok else 'CHECK'} {label:58s} quoted {quoted:>30s} | recomputed {got}")


def near(a, b, tol):
    return abs(float(a) - float(b)) <= tol


# ------------------------------------------------------------------ readers
def coef(case):
    base = RUNS / case / "postProcessing" / "forceCoeffs1"
    parts = []
    for d in sorted(base.iterdir(), key=lambda p: float(p.name)):
        f = d / "coefficient.dat"
        hdr = next(line for line in open(f) if line.startswith("# Time"))
        cols = [h.strip() for h in hdr[1:].split("\t") if h.strip()]
        a = np.loadtxt(f, comments="#")
        parts.append(pd.DataFrame(a[:, :len(cols)], columns=cols))
    keep = [p[p.Time < parts[i + 1].Time.iloc[0]] if i + 1 < len(parts) else p for i, p in enumerate(parts)]
    df = pd.concat(keep, ignore_index=True)
    tc = json.loads((RUNS / case / "case.json").read_text())["convTime"]
    return df.Time.to_numpy() / tc, df.Cd.to_numpy(), df.Cl.to_numpy()


def jump_bins(t, cd, lim=0.5):
    m = (np.abs(np.diff(cd)) > lim) & (t[1:] >= 2.0)
    return {149 if k == 150 else k for k in np.floor(t[1:][m]).astype(int) if 50 <= k <= 150}


def log_summary(case, w0, w1):
    cmd = ["grep", "-E", r"^(deltaT = |Time = |PIMPLE: iteration 1$|[A-Za-z]+:  Solving for p, )",
           str(RUNS / case / "log.pimpleFoam")]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"})
    T, R, want = [], [], False
    for line in p.stdout:
        if line.startswith(b"Time = "):
            T.append(float(line.split(b"=")[1]))
            R.append(np.nan)
            want = False
        elif line.startswith(b"PIMPLE"):
            want = True
        elif want and b"Solving for p" in line:
            R[-1] = float(line.split(b"Initial residual = ")[1].split(b",")[0])
            want = False
    p.wait()
    tc = json.loads((RUNS / case / "case.json").read_text())["convTime"]
    t, r = np.array(T) / tc, np.array(R)
    m = (t >= w0) & (t <= w1 + 1e-9)          # all window steps, as the analysis counts them
    return dict(name=case, steps=len(t), nan=int(np.isnan(r).sum()), share=float(np.mean(r[m] > 0.05)),
                median=float(np.nanmedian(r[m])))


def rmean(t, y, w):
    tu = np.arange(np.ceil(t[0] / 0.02) * 0.02, t[-1] + 1e-9, 0.02)
    return tu, pd.Series(np.interp(tu, t, y)).rolling(int(round(w / 0.02)), center=True).mean().to_numpy()


def cycles(t, cl, t0, t1, prom):
    tu, s = rmean(t, cl, 1.0)
    ok = np.isfinite(s)
    tu, s = tu[ok], s[ok]
    ip, iv = find_peaks(s, prominence=prom)[0], find_peaks(-s, prominence=prom)[0]
    res = []
    for i in ip:
        nx = iv[iv > i]
        if t0 <= tu[i] <= t1 and nx.size:
            res.append((tu[i], s[i] - s[nx[0]]))
    return np.array(res)


def efold(c):
    return 1.0 / np.polyfit(c[:, 0], np.log(c[:, 1]), 1)[0]


def surface(case):
    s = pd.read_csv(REC / case / "fields" / "surface_mean.csv", comment="#")
    s = s[s.patch == "blade"]
    sc, cp, cf = s.s_over_c.to_numpy(), s.Cp.to_numpy(), s.Cf.to_numpy()
    cv = np.flatnonzero((sc > 0.0) & (sc <= 1.48))
    i0 = cv[np.argmax(cp[cv])]
    j = np.arange(i0, cv[-1] + 1)
    ipk = j[np.argmax(cf[j])]
    isep = next(i for i in range(ipk, cv[-1] + 1) if cf[i] <= 0)
    return dict(sep=sc[isep], cfpk=cf[ipk], cpb=cp[(sc >= 1.60) & (sc <= 2.85)].mean())


# ------------------------------------------------------------------ main
def main():
    warnings.filterwarnings("ignore", category=RuntimeWarning)   # empty jump-free halves give nan
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", action="store_true", help="re-parse every log.pimpleFoam (49 GB)")
    a = ap.parse_args()
    T = pd.read_csv(REPO / "cfd" / "section2d" / "results" / "section_polars.csv").set_index("name")
    O = pd.read_csv(REPO / "cfd" / "analysis" / "2026-10-13" / "data" / "section_polars.csv").set_index("name")
    T["new"] = ~T.index.isin(O.index)
    T["proxy"] = T.maxCo * T.level.map(DX) / (T.dt_mean_s * T.U_ms)
    T["flag"] = T.proxy > 5
    T["sym"] = (T.Cd_mean < 0) | (T.Cd_std > T.Cd_mean.abs()) | (T.Cl_mean.abs() > 3) | (T.yplus_max_mean > 2)
    new = T[T.new]
    rng = lambda s: f"{s.min():.2f}-{s.max():.2f}"  # noqa: E731

    print("== S1 health flag")
    out("rows / new / flagged / flagged new", "125 / 74 / 23 / 0",
        f"{len(T)} / {len(new)} / {T.flag.sum()} / {new.flag.sum()}",
        (len(T), len(new), T.flag.sum(), new.flag.sum()) == (125, 74, 23, 0))
    num = [c for c in O.select_dtypes("number").columns if c in T.columns]
    dmax = float((T.loc[O.index, num] - O[num]).abs().max().max())
    out("the 51 rows of 13 Oct unchanged (max abs diff)", "0", f"{dmax:g}", dmax == 0.0)
    for lab, q, s in (("proxy new", "1.10-4.46", new.proxy), ("proxy maxCo 1.25", "1.59-3.30", T[T.maxCo == 1.25].proxy),
                      ("proxy 13 Oct healthy", "2.25-4.48", T[~T.new & ~T.flag].proxy),
                      ("proxy 13 Oct flagged", "6.27-32.30", T[~T.new & T.flag].proxy)):
        out(lab, q, rng(s), rng(s) == q)
    rr = T.loc[[n + "_Co2.5n2" for n in T[T.flag].index]]
    out("re-runs: proxy, flagged, symptom, new", "1.30-4.46, 0, 0, 22", f"{rng(rr.proxy)}, {rr.flag.sum()}, {rr.sym.sum()}, {rr.new.sum()}",
        (rng(rr.proxy), rr.flag.sum(), rr.sym.sum(), rr.new.sum()) == ("1.30-4.46", 0, 0, 22))
    hs = T[~T.flag & T.sym]
    out("healthy runs with a symptom", "4, all new, 10.2 m/s, 195-210",
        f"{len(hs)}: " + ", ".join(f"{n[:4]} {T.loc[n,'model']} {T.loc[n,'Cd_std']/abs(T.loc[n,'Cd_mean']):.4f}" for n in hs.index),
        len(hs) == 4 and hs.new.all() and (hs.U_ms == 10.2).all())

    print("== force histories")
    H = {}
    for n in list(T.index) + EXTRA:
        H[n] = coef(n)
    rows = []
    for n, r in T.iterrows():
        t, cd, cl = H[n]
        w = (t >= r.avg_from_conv - 1e-6) & (t <= r.avg_to_conv + 1e-6)
        jb = {lim: jump_bins(t, cd, lim) for lim in (0.5, 0.2, 0.1)}
        keep = w & ~np.isin(np.floor(t).astype(int), list(jb[0.5]))
        mid = 0.5 * (r.avg_from_conv + r.avg_to_conv)
        rows.append(dict(name=n, J5=len(jb[0.5]), J2=len(jb[0.2]), J1=len(jb[0.1]), share_nj=keep.sum() / w.sum(),
                         Cd_nj=cd[keep].mean(), drift_nj=cd[keep & (t >= mid)].mean() - cd[keep & (t < mid)].mean(),
                         dmax=np.abs(np.diff(cd))[(w[1:] & w[:-1])].max(), Cd_l10=cd[t >= t[-1] - 10].mean(),
                         Cl_l10=cl[t >= t[-1] - 10].mean(), Cl_std_l10=cl[t >= t[-1] - 10].std()))
    D = T.join(pd.DataFrame(rows).set_index("name"))
    nw = D[D.new]

    print("== S2 jumps and residuals")
    out("new runs with jumps at 0.5/0.2/0.1", "25/32/36",
        f"{(nw.J5 > 0).sum()}/{(nw.J2 > 0).sum()}/{(nw.J1 > 0).sum()}", ((nw.J5 > 0).sum(), (nw.J2 > 0).sum(), (nw.J1 > 0).sum()) == (25, 32, 36))
    out("LM / SST new with jumps", "14 of 58 / 11 of 16",
        f"{(nw[nw.model == 'LM'].J5 > 0).sum()} of {(nw.model == 'LM').sum()} / {(nw[nw.model == 'SST'].J5 > 0).sum()} of {(nw.model == 'SST').sum()}", True)
    s10 = nw[(nw.model == "SST") & (nw.U_ms == 10.2)]
    out("SST 10.2 m/s: runs with jumps, intervals", "5 of 5, 7-26", f"{(s10.J5 > 0).sum()} of {len(s10)}, {s10.J5.min()}-{s10.J5.max()}",
        (s10.J5 > 0).sum() == 5 and (s10.J5.min(), s10.J5.max()) == (7, 26))
    hl = D[~D.flag]
    out("healthy runs with jumps (13 Oct)", "35 of 102 (10 of 28)",
        f"{(hl.J5 > 0).sum()} of {len(hl)} ({(hl[~hl.new].J5 > 0).sum()} of {(~hl.new).sum()})", (hl.J5 > 0).sum() == 35)
    r2 = D.loc[rr.index]
    out("re-runs with jumps", "4: 26, 22, 8, 15", ", ".join(f"{n.split('_')[0]} {n.split('_')[1]} {n.split('_')[2]} {v}" for n, v in r2[r2.J5 > 0].J5.items()),
        sorted(r2[r2.J5 > 0].J5) == [8, 15, 22, 26])
    lm3 = nw[(nw.model == "LM") & (nw.Tu_body_pct == 3.0)]
    out("'all 15 LM runs at Tu 3 % free of it' (jumps)", "0 of 15 with jumps",
        f"{(lm3.J5 > 0).sum()} of {len(lm3)}: " + ", ".join(f"{n.split('_')[0]} {n.split('_')[1]} {v}" for n, v in lm3[lm3.J5 > 0].J5.items()),
        (lm3.J5 > 0).sum() == 0)
    a195 = nw[(nw.alpha_deg == 195) & (nw.U_ms == 38.0)]
    print(f"      note: alpha 195 at 38 m/s, window jump intervals: " + ", ".join(f"{r.model} Tu{r.Tu_body_pct:g} {r.J5}" for r in a195.itertuples()))
    nu = nw[nw.share_nj < 0.5]
    out("not usable (jump-free share)", "0.29, 0.04, 0.0002, 0.11", ", ".join(f"{v:.2g}" for v in nu.share_nj), len(nu) == 4)
    if a.logs or not CACHE.exists():
        L = pd.DataFrame([log_summary(n, D.loc[n, "avg_from_conv"], D.loc[n, "avg_to_conv"]) for n in D.index])
        L.to_csv(CACHE, index=False, float_format="%.6g")
    L = pd.read_csv(CACHE).set_index("name")
    D = D.join(L)
    nw, hl = D[D.new], D[~D.flag]
    out("log steps = table n_steps; logs with one p line missing", "all; 3 flagged",
        f"{(D.steps == D.n_steps).all()}; {(D.nan > 0).sum()} ({', '.join(D[D.nan > 0].index.str[:20])})", (D.steps == D.n_steps).all())
    fl = D[D.flag]
    out("flagged: residual share range, n > 0.5", "0.405-1.000, 22", f"{fl.share.min():.3f}-{fl.share.max():.3f}, {(fl.share > 0.5).sum()}",
        near(fl.share.min(), 0.405, 6e-4) and (fl.share > 0.5).sum() == 22)
    q = hl[hl.dmax <= 0.1]
    out("healthy, no window change > 0.1: n, share, median", "56, 0-0.368, 0.00015-0.0137",
        f"{len(q)}, {q.share.min():.3f}-{q.share.max():.3f}, {q['median'].min():.2g}-{q['median'].max():.3g}", len(q) == 56)
    g = nw[nw.share > 0.5]
    out("new runs with share > 0.5; medians", "15; 0.058-0.418", f"{len(g)}; {g['median'].min():.3f}-{g['median'].max():.3f}", len(g) == 15)
    tt = nw[(nw.maxCo == 2.5) & nw.alpha_deg.between(150, 210)]
    for tu, qv in ((0.5, 8), (1.0, 6), (3.0, 0)):
        x = tt[(tt.model == "LM") & (tt.Tu_body_pct == tu)]
        out(f"LM Tu {tu:g} % (transition set): share > 0.5", f"{qv} of 15", f"{(x.share > 0.5).sum()} of {len(x)} (max {x.share.max():.3f})", (x.share > 0.5).sum() == qv)
    out("SST new: share > 0.5; maxCo 1.25: share", "1 of 16; 0", f"{(nw[nw.model == 'SST'].share > 0.5).sum()}; {D[D.maxCo == 1.25].share.max():g}", True)
    both = nw[(nw.J5 > 0) & (nw.share <= 0.5)]
    only = nw[(nw.J5 == 0) & (nw.share > 0.5)]
    print(f"      note: jumps with share <= 0.5: {len(both)} new runs; share > 0.5 without jumps: {len(only)}")

    def get(al, U, m, tu=1.0, co=2.5):
        x = D[(D.alpha_deg == al) & (D.U_ms == U) & (D.model == m) & (D.Tu_body_pct == tu) & (D.maxCo == co) & (D.level == "medium")]
        assert len(x) == 1
        return x.iloc[0]

    def chg(A, B):
        d, n = A.Cd_mean - B.Cd_mean, abs(A.Cd_drift) + abs(B.Cd_drift)
        dn, nn = A.Cd_nj - B.Cd_nj, abs(A.drift_nj) + abs(B.drift_nj)
        res = A.share_nj >= 0.5 and B.share_nj >= 0.5 and abs(d) > n and abs(dn) > nn and np.sign(d) == np.sign(dn)
        return 100 * d / abs(B.Cd_mean), n, res

    print("== S3 time step at alpha 180 (23 m/s)")
    for m, qp, qn in (("SST", "-17.51", "0.0466"), ("LM", "-14.78", "0.0369")):
        A, B = get(180, 23.0, m, co=1.25), get(180, 23.0, m)
        p, n, res = chg(A, B)
        out(f"{m} 2.5 -> 1.25: change %, noise, resolved", f"{qp}, {qn}, yes", f"{p:.2f}, {n:.4f}, {res} ({abs(A.Cd_mean - B.Cd_mean) / n:.2f} x)",
            near(p, float(qp), 0.005) and near(n, float(qn), 5e-5) and res)
        out(f"{m} 1.25 lift std over the last 10 c/U", "9.8e-5" if m == "SST" else "3.2e-4", f"{A.Cl_std_l10:.2g}", True)
        t, cd, cl = H[A.name]
        qb = [cl[(t >= lo) & (t < lo + 10 + (1e-6 if lo == 140 else 0))].std() for lo in range(0, 150, 10)]
        tq = next(lo for k, lo in enumerate(range(0, 150, 10)) if max(qb[k:]) < 1e-3)
        jb = sorted({int(k) for k in np.floor(t[1:][(np.abs(np.diff(cd)) > 0.5) & (t[1:] >= 2)])})
        out(f"{m} 1.25 'steady from ~{15 if m == 'SST' else 20} c/U' (10-c/U lift std < 0.001)", f"~{15 if m == 'SST' else 20} c/U",
            f"from {tq} c/U (20-30 c/U: {qb[2]:.2g}); window lift std {A.Cl_std:.2g}; start-up jumps {jb[0]}-{jb[-1] + 1} c/U", False)
    out("residual share at maxCo 2.5 (SST, LM)", "0.150, 0.412", f"{get(180, 23.0, 'SST').share:.3f}, {get(180, 23.0, 'LM').share:.3f}", True)
    out("SST 1.25 on the frontal width 48.76 mm", "1.201", f"{get(180, 23.0, 'SST', co=1.25).Cd_mean * 48 / 48.76:.3f}", True)
    out("wall time h: SST/LM 1.25, SST/LM 2.5", "11.0/7.1, 7.3/3.1",
        "/".join(f"{get(180, 23.0, m, co=c).wall_time_s / 3600:.1f}" for c in (1.25, 2.5) for m in ("SST", "LM")), True)

    print("== S4 alpha 0")
    t, cd, cl = H["a000.0_U23.0_SST_medium_Tu1.0_Co1.25n2"]
    bc = [cd[(t >= lo) & (t < lo + 10)].mean() for lo in range(0, 90, 10)]
    bl = [cl[(t >= lo) & (t < lo + 10)].mean() for lo in range(0, 90, 10)]
    out("SST 1.25 blocks to 90 c/U: Cd, mean Cl", "2.77-3.20, -0.17 to +0.26", f"{min(bc):.2f}-{max(bc):.2f}, {min(bl):+.2f} to {max(bl):+.2f}", True)
    tm, rm = rmean(t, cd, 8.0)
    c = cycles(t, cl, 95, 149, 0.002)
    out("SST 1.25: running mean last > 2.5; decay e-fold", "102.4; 13.8", f"{tm[np.flatnonzero(rm > 2.5)[-1]]:.1f}; {-efold(c):.1f}", True)
    tM, cM, lM = H["a000.0_U23.0_SST_medium_Tu1.0"]
    tU, cU, lU = H[EXTRA[0]]
    m = (tM >= 2) & (tM <= tU[-1])
    out("Mac vs Unity repeat: max |dCd| sample by sample", "0.038", f"{np.abs(np.interp(tM[m], tU, cU) - cM[m]).max():.3f}", True)
    for par, rst, qd in (("a000.0_U23.0_SST_medium_Tu1.0", EXTRA[1], "3.253/3.198/3.171"), ("a000.0_U23.0_SST_medium_Tu1.0_Co2.5n2", EXTRA[2], "1.737/1.745/1.754")):
        tr, cr, lr = H[rst]
        b = [cr[(tr >= 150 + lo) & (tr < 150 + hi + (1e-6 if hi == 60 else 0))].mean() for lo, hi in ((0, 10), (10, 30), (30, 60))]
        out(f"{rst}: Cd 0-10/10-30/30-60 c/U", qd, "/".join(f"{v:.3f}" for v in b), True)
    tr, cr, lr = H[EXTRA[2]]
    c = cycles(tr, lr, 151, 209.5, 0.0005)
    out("restart (b): lift p2p first -> last cycle; e-fold all", "0.0046 -> 0.050; 20.4", f"{c[0, 1]:.4f} -> {c[-1, 1]:.3f}; {efold(c):.1f}", True)
    out("restart (b) 'it was leaving the low-drag state'", "constant growth, ~79 c/U to switch",
        f"e-fold {efold(c[:4]):.0f} c/U (first 4 cycles) -> {efold(c[-4:]):.0f} c/U (last 4); Cd 1.737-1.754 (low-drag)", False)

    print("== S5 LM polar (23 m/s, Tu 1 %)")
    p = D[(D.model == "LM") & (D.U_ms == 23) & (D.Tu_body_pct == 1) & ~D.flag]
    out("healthy angles", "24", f"{p.alpha_deg.nunique()}", p.alpha_deg.nunique() == 24)
    out("steady by window lift std < 0.001", "60, 90, 105, 225, 240, 255", ", ".join(f"{a:g}" for a in p[p.Cl_std < 1e-3].alpha_deg), True)
    out("same by last-10 lift std (section_timestep.png)", "(not quoted)", ", ".join(f"{a:g}@{c:g}" for a, c in p[p.Cl_std_l10 < 1e-3][["alpha_deg", "maxCo"]].values), True)
    sig = p[p.share > 0.5]
    out("caveat 'alpha 195 and 210 carry disturbance'", "195, 210",
        ", ".join(f"{a:g}@{c:g} share {s:.2f} jumps {int(j)}" for a, c, s, j in sig[["alpha_deg", "maxCo", "share", "J5"]].values), False)

    print("== S6 LM against SST (Tu 1 %, maxCo 2.5)")
    res_q, res_clean = 0, 0
    for U in (10.2, 23.0, 38.0):
        for al in (150, 165, 180, 195, 210):
            A, B = get(al, U, "LM"), get(al, U, "SST")
            pc, n, res = chg(A, B)
            if U < 30 and res:
                res_q += A.share < 0.5 and B.share < 0.5
                res_clean += A.share < 0.5 and B.share < 0.5 and A.J5 == 0 and B.J5 == 0
            print(f"      {U:4g} m/s {al}: {pc:+6.1f} %  noise {n:.4f}  resolved {res}  shares {A.share:.2f}/{B.share:.2f}  jumps {A.J5}/{B.J5}")
    out("10.2-23 m/s resolved pairs with both shares < 0.5", "4 ('free of solver disturbance')",
        f"{res_q}; with both also jump-free: {res_clean}", res_clean == 4)
    pc, n, res = chg(get(180, 23.0, "LM", co=1.25), get(180, 23.0, "SST", co=1.25))
    out("maxCo 1.25 pair at 180, 23 m/s", "-8.59 %, noise 0.0366", f"{pc:.2f} %, {n:.4f}, resolved {res}", near(pc, -8.59, 0.005))

    print("== S6/S7 wall data at alpha 180")
    W = {n: surface(n) for n in D[(D.alpha_deg == 180) & (D.level == "medium") & ~D.flag].index}
    for U in (10.2, 23.0, 38.0):
        sl, ss = W[get(180, U, "LM").name], W[get(180, U, "SST").name]
        print(f"      {U:4g} m/s maxCo 2.5: separation LM {sl['sep']:.3f} SST {ss['sep']:.3f}; Cf peak ratio {sl['cfpk'] / ss['cfpk']:.2f}; base Cp LM {sl['cpb']:.3f} SST {ss['cpb']:.3f}")
    sl, ss = W[get(180, 23.0, "LM", co=1.25).name], W[get(180, 23.0, "SST", co=1.25).name]
    s25 = W[get(180, 23.0, "SST").name]
    out("SST separation / base Cp, maxCo 2.5 -> 1.25 (not quoted)", "(gap LM-SST 0.097 c quoted at 2.5)",
        f"{s25['sep']:.3f} -> {ss['sep']:.3f}, {s25['cpb']:.3f} -> {ss['cpb']:.3f}; at 1.25 LM {sl['sep']:.3f} (gap {ss['sep'] - sl['sep']:.3f} c)", False)

    print("== S7 speed and Tu (LM, alpha 180)")
    pc, n, res = chg(get(180, 10.2, "LM"), get(180, 23.0, "LM"))
    out("LM Tu 1 % 10.2 vs 23 m/s ('flat')", "flat", f"{pc:+.2f} % ({abs(pc) / 100 * get(180, 23.0, 'LM').Cd_mean / n:.1f} x noise, resolved {res}); 10.2 m/s share {get(180, 10.2, 'LM').share:.2f}", False)
    for (U1, U0, m, tu, qp) in ((38.0, 23.0, "LM", 1.0, "+20.5"), (38.0, 23.0, "SST", 1.0, "+7.1")):
        pc, n, res = chg(get(180, U1, m, tu), get(180, U0, m, tu))
        out(f"{m} Tu {tu:g} % {U1:g} vs {U0:g} m/s", qp, f"{pc:+.1f} % (noise {n:.4f}, resolved {res})", near(pc, float(qp), 0.05))
    for U, tu, qp in ((23.0, 3.0, "-17.0"), (38.0, 0.5, "+6.7"), (38.0, 3.0, "-6.6"), (10.2, 3.0, "-12.1")):
        pc, n, res = chg(get(180, U, "LM", tu), get(180, U, "LM", 1.0))
        out(f"LM {U:g} m/s Tu {tu:g} vs 1 %", qp, f"{pc:+.1f} % (resolved {res})", near(pc, float(qp), 0.05))
    vr = {(tu, U): json.loads((RUNS / get(180, U, "LM", tu).name / "case.json").read_text())["viscosityRatioBody"] for tu in (0.5, 1.0, 3.0) for U in (10.2, 23.0, 38.0)}
    print("      free-stream nu_t/nu (Tu 0.5/1/3 % x 10.2/23/38 m/s): " + "; ".join(f"Tu {tu:g}: " + "/".join(f"{vr[(tu, U)]:.1f}" for U in (10.2, 23.0, 38.0)) for tu in (0.5, 1.0, 3.0)))

    print("== S8 / S9")
    l0, s0 = get(0, 23.0, "LM", co=1.25), get(0, 23.0, "SST", co=1.25)
    l1, s1 = get(180, 23.0, "LM", co=1.25), get(180, 23.0, "SST", co=1.25)
    Dl, Ds = l0.Cd_l10 - l1.Cd_l10, s0.Cd_l10 - s1.Cd_l10
    out("D = Cd(0) - Cd(180), last 10 c/U, LM / SST", "0.583 / 0.602 (+3.3 %)", f"{Dl:.3f} / {Ds:.3f} ({100 * (Ds / Dl - 1):+.1f} %)", True)
    k = s0.Cd_l10 / s1.Cd_mean
    out("SST maxCo 1.25: k, lambda0", "1.49, 0.100", f"{k:.2f}, {(np.sqrt(k) - 1) / (np.sqrt(k) + 1):.3f}", True)
    print(f"\n{N_CHECK} CHECK lines (each is a correction made in the review of 19 Oct)")


if __name__ == "__main__":
    main()
