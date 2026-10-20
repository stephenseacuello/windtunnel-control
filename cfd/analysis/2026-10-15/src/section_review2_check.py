#!/usr/bin/env python3
"""Second independent check of the Stage 1 (smooth section) findings S1-S9 of 15 Oct 2026 (review of 19 Oct).

    nice -n 10 python3 cfd/analysis/2026-10-15/src/section_review2_check.py          # ~10 s with the log cache
    nice -n 10 python3 cfd/analysis/2026-10-15/src/section_review2_check.py --logs   # re-parse all 128 logs (~4 min)

Shares no code with section_lib.py, section_histories.py, section_analysis.py, section_figures.py,
section_verify.py, section_review_check.py or cfd/post:
  - forces: own reader of postProcessing/forceCoeffs1/<t>/coefficient.dat (sessions sorted by first time;
    an earlier session is cut at the next session's first sample);
  - logs: grep (LC_ALL=C) for 'deltaT = ', 'Time = ' and the p-solve lines; the first p solve after each
    'Time = ' line is that step's first pressure solve; when Time goes backwards (a restart), the earlier
    session's steps from that time on are dropped (so flagged multi-session runs count each step once);
    per-case summary cached in ../out/section_review2_logs.csv;
  - wall data: own search in records/<case>/fields/surface_mean.csv (stagnation = maximum Cp on the outer
    side, separation = linearly interpolated + to - zero crossing of Cf after its peak; base Cp =
    length-weighted mean over s/c 1.60-2.85, identical to the plain mean because the points are uniform);
  - lift cycles: own extremum search on a 1-c/U running mean.
Definitions are those of the analysis: 13 Oct flag (u_Co/U > 5); jump = |dCd| > 0.5 between samples, its
1-c/U interval counted in the 50-150 c/U window; usable = jump-free share >= 0.5; resolved = beyond the drift
noise with and without the jump intervals, same sign, both runs usable; residual share = share of window
steps whose first p solve starts above 0.05. Each line prints the quoted value, the recomputed one and OK, or
CHECK where the quoted text needs a correction, or NEW for a number the analysis did not quote.
Reads only; writes nothing but the log cache.
"""
import argparse
import json
import subprocess
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[4]
RUNS = REPO / "cfd" / "section2d" / "runs"
REC = REPO / "cfd" / "section2d" / "results" / "records"
CACHE = Path(__file__).resolve().parents[1] / "out" / "section_review2_logs.csv"
EXTRA = ["_unity_a000.0_U23.0_SST_medium_Tu1.0", "_hyst_Co5to2p5_a000", "_hyst_Co2p5to5_a000"]
DXC = {"coarse": 64e-6, "medium": 45e-6, "fine": 32e-6}
COUNT = {"OK": 0, "CHECK": 0, "NEW": 0}


def say(tag, label, quoted, got):
    COUNT[tag] += 1
    print(f"{tag:5s} {label:62s} quoted {str(quoted):>26s} | recomputed {got}")


# ------------------------------------------------------------------ readers
def hist(name):
    sess = []
    for d in (RUNS / name / "postProcessing" / "forceCoeffs1").iterdir():
        f = d / "coefficient.dat"
        if not f.exists():
            continue
        with open(f) as fh:
            hdr = next(ln for ln in fh if ln.startswith("# Time")).lstrip("#").split()
        a = pd.read_csv(f, comment="#", sep=r"\s+", header=None).to_numpy(float)
        ic = {h: i for i, h in enumerate(hdr)}
        sess.append((a[0, 0], a[:, ic["Time"]], a[:, ic["Cd"]], a[:, ic["Cl"]]))
    sess.sort(key=lambda s: s[0])
    keep = [s if i == len(sess) - 1 else tuple(x[s[1] < sess[i + 1][0]] if k else x for k, x in enumerate(s))
            for i, s in enumerate(sess)]
    tc = json.loads((RUNS / name / "case.json").read_text())["convTime"]
    return (np.concatenate([s[1] for s in keep]) / tc, np.concatenate([s[2] for s in keep]),
            np.concatenate([s[3] for s in keep]))


def log_summary(args):
    name, w0, w1 = args
    tc = json.loads((RUNS / name / "case.json").read_text())["convTime"]
    p = subprocess.Popen(["grep", "-a", "-E", r"^(Time = |[A-Za-z]+:  Solving for p,)", str(RUNS / name / "log.pimpleFoam")],
                         stdout=subprocess.PIPE, env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"}, bufsize=1 << 20)
    t, r, got = [], [], True
    for ln in p.stdout:
        if ln.startswith(b"Time = "):
            tt = float(ln[7:])
            if t and tt <= t[-1]:
                k = int(np.searchsorted(np.array(t), tt))
                del t[k:], r[k:]
            t.append(tt)
            r.append(np.nan)
            got = False
        elif not got:
            i = ln.find(b"Initial residual = ")
            r[-1] = float(ln[i + 19:ln.find(b",", i)])
            got = True
    p.wait()
    t, r = np.array(t) / tc, np.array(r)
    w = (t >= w0 - 1e-6) & (t <= w1 + 1e-6)
    return dict(name=name, steps=len(t), share=float(np.mean(r[w] > 0.05)), median=float(np.nanmedian(r[w])),
                share_0_20=float(np.mean(r[t < 20] > 0.05)))


def runmean(t, y, w):
    tu = np.arange(np.ceil(t[0] / 0.02) * 0.02, t[-1], 0.02)
    n = int(round(w / 0.02))
    m = np.convolve(np.interp(tu, t, y), np.ones(n) / n, mode="valid")
    return tu[(n - 1) // 2:(n - 1) // 2 + len(m)] + (0.01 if n % 2 == 0 else 0), m


def cycles(t, y, t0, t1, floor=0.0):
    tm, s = runmean(t, y, 1.0)
    ds = np.sign(np.diff(s))
    imax = np.flatnonzero((ds[:-1] > 0) & (ds[1:] <= 0)) + 1
    imin = np.flatnonzero((ds[:-1] < 0) & (ds[1:] >= 0)) + 1
    out = []
    for i in imax:
        j = imin[imin > i]
        if t0 <= tm[i] <= t1 and j.size and s[i] - s[j[0]] > floor:
            out.append((tm[i], s[i] - s[j[0]]))
    return np.array(out)


def efold(c):
    return 1.0 / np.polyfit(c[:, 0], np.log(c[:, 1]), 1)[0]


def wall(name):
    s = pd.read_csv(REC / name / "fields" / "surface_mean.csv", comment="#")
    s = s[s.patch == "blade"].sort_values("s_over_c")
    sc, cp, cf = (s[c].to_numpy() for c in ("s_over_c", "Cp", "Cf"))
    ov = np.flatnonzero((sc > 0.05) & (sc < 1.45))
    i0 = ov[np.argmax(cp[ov])]
    j = np.arange(i0, np.flatnonzero(sc < 1.48)[-1] + 1)
    ip = j[np.argmax(cf[j])]
    sep = next(sc[k] + (sc[k + 1] - sc[k]) * cf[k] / (cf[k] - cf[k + 1]) for k in range(ip, j[-1]) if cf[k] > 0 >= cf[k + 1])
    m = (sc >= 1.60) & (sc <= 2.85)
    ds = np.gradient(sc)
    return dict(sep=sep, cfpk=cf[ip], cpb=float(np.sum(cp[m] * ds[m]) / np.sum(ds[m])))


# ------------------------------------------------------------------ main
def main():
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", action="store_true")
    a = ap.parse_args()
    T = pd.read_csv(REPO / "cfd/section2d/results/section_polars.csv").set_index("name")
    O = pd.read_csv(REPO / "cfd/analysis/2026-10-13/data/section_polars.csv").set_index("name")
    T["new"] = ~T.index.isin(O.index)
    T["proxy"] = T.maxCo * T.level.map(DXC) / (T.dt_mean_s * T.U_ms)
    T["flag"] = T.proxy > 5
    T["sym"] = (T.Cd_mean < 0) | (T.Cd_std > T.Cd_mean.abs()) | (T.Cl_mean.abs() > 3) | (T.yplus_max_mean > 2)
    T["vr"] = [json.loads((RUNS / n / "case.json").read_text())["viscosityRatioBody"] for n in T.index]
    rng = lambda s, f=".2f": f"{s.min():{f}}-{s.max():{f}}"  # noqa: E731

    print("== S1")
    nw = T[T.new]
    say("OK" if (len(T), len(nw), T.flag.sum(), nw.flag.sum()) == (125, 74, 23, 0) else "CHECK",
        "rows / new / flagged / flagged new", "125/74/23/0", f"{len(T)}/{len(nw)}/{T.flag.sum()}/{nw.flag.sum()}")
    num = [c for c in O.select_dtypes("number").columns if c in T.columns]
    say("OK", "51 rows of 13 Oct unchanged (max abs diff)", 0, float((T.loc[O.index, num] - O[num]).abs().max().max()))
    for lab, q, s in (("proxy new", "1.10-4.46", nw.proxy), ("proxy maxCo 1.25", "1.59-3.30", T[T.maxCo == 1.25].proxy),
                      ("proxy 13 Oct healthy / flagged", "2.25-4.48 / 6.27-32.30", None)):
        got = rng(s) if s is not None else f"{rng(T[~T.new & ~T.flag].proxy)} / {rng(T[~T.new & T.flag].proxy)}"
        say("OK" if got == q else "CHECK", lab, q, got)
    rr = T.loc[[n + "_Co2.5n2" for n in T[T.flag].index]]
    say("OK", "re-runs: proxy, flagged, symptom, new", "1.30-4.46, 0, 0, 22", f"{rng(rr.proxy)}, {rr.flag.sum()}, {rr.sym.sum()}, {rr.new.sum()}")
    hs = T[~T.flag & T.sym]
    say("OK", "healthy runs with a symptom (std/|mean|)", "1.06,1.03,1.53,1.0001",
        ", ".join(f"a{r.alpha_deg} {r.U_ms:g} m/s {r.model} Tu{r.Tu_body_pct:g}: {r.Cd_std / abs(r.Cd_mean):.4f}" for _, r in hs.iterrows()))

    # ---------------------------------------------------------------- histories
    H = {n: hist(n) for n in list(T.index) + EXTRA}
    rows = []
    for n, r in T.iterrows():
        t, cd, cl = H[n]
        w = (t >= r.avg_from_conv - 1e-6) & (t <= r.avg_to_conv + 1e-6)
        out = dict(name=n)
        for lim in (0.5, 0.2, 0.1):
            k = np.floor(t[1:][(np.abs(np.diff(cd)) > lim) & (t[1:] >= 2.0)]).astype(int)
            out[f"J{lim:g}"] = len({149 if x == 150 else x for x in k if 50 <= x <= 150})
            if lim == 0.5:
                jb = {149 if x == 150 else x for x in k if 50 <= x <= 150}
                ib = np.floor(t).astype(int)
                ib[ib == 150] = 149
                keep = w & ~np.isin(ib, list(jb))
                mid = 0.5 * (r.avg_from_conv + r.avg_to_conv)
                out.update(share_nj=keep.sum() / w.sum(), Cd_nj=cd[keep].mean(),
                           drift_nj=cd[keep & (t >= mid)].mean() - cd[keep & (t < mid)].mean())
        out.update(dmax=np.abs(np.diff(cd))[w[1:] & w[:-1]].max(), Cd_l10=cd[t >= t[-1] - 10].mean(),
                   Cl_l10=cl[t >= t[-1] - 10].mean(), Clsd_l10=cl[t >= t[-1] - 10].std())
        rows.append(out)
    D = T.join(pd.DataFrame(rows).set_index("name"))
    nw, hl = D[D.new], D[~D.flag]

    print("== S2")
    say("OK", "new runs with jumps at 0.5/0.2/0.1", "25/32/36", f"{(nw['J0.5'] > 0).sum()}/{(nw['J0.2'] > 0).sum()}/{(nw['J0.1'] > 0).sum()}")
    say("OK", "LM / SST new with jumps", "14 of 58 / 11 of 16",
        f"{(nw[nw.model == 'LM']['J0.5'] > 0).sum()} of {(nw.model == 'LM').sum()} / {(nw[nw.model == 'SST']['J0.5'] > 0).sum()} of {(nw.model == 'SST').sum()}")
    say("OK", "healthy runs with jumps (13 Oct)", "35 of 102 (10 of 28)", f"{(hl['J0.5'] > 0).sum()} of {len(hl)} ({(hl[~hl.new]['J0.5'] > 0).sum()} of {(~hl.new).sum()})")
    lm3 = nw[(nw.model == "LM") & (nw.Tu_body_pct == 3)]
    say("CHECK", "'all 15 LM runs at Tu 3 % ... free of it' (jumps)", "0 of 15",
        f"{(lm3['J0.5'] > 0).sum()} of {len(lm3)}: " + ", ".join(f"a{r.alpha_deg} {r.U_ms:g} m/s: {int(r['J0.5'])}" for _, r in lm3[lm3['J0.5'] > 0].iterrows()))
    a195 = nw[nw.alpha_deg == 195]
    say("CHECK", "alpha 195 jumps (SST every speed; LM at 38 m/s every Tu)", "'SST at alpha 195'",
        "; ".join(f"{r.model} {r.U_ms:g} Tu{r.Tu_body_pct:g}: {int(r['J0.5'])}" for _, r in a195.iterrows() if r['J0.5'] > 0))
    say("OK", "not usable (jump-free share)", "0.29, 0.04, 0.0002, 0.11", ", ".join(f"{v:.2g}" for v in nw[nw.share_nj < 0.5].share_nj))
    q = nw[nw["J0.5"] == 0]
    say("NEW", "largest window dCd in new runs without a 0.5 jump", "-", f"{q.dmax.max():.3f} (limit on a continuum)")
    if a.logs or not CACHE.exists():
        with ProcessPoolExecutor(4) as ex:
            L = pd.DataFrame(list(ex.map(log_summary, [(n, D.loc[n, "avg_from_conv"], D.loc[n, "avg_to_conv"]) for n in D.index])))
        L.to_csv(CACHE, index=False, float_format="%.6g")
    L = pd.read_csv(CACHE).set_index("name")
    D = D.join(L)
    nw, hl, fl = D[D.new], D[~D.flag], D[D.flag]
    say("OK", "flagged share (restart steps counted once), n > 0.5", "0.405-1.000, 22", f"{rng(fl.share, '.3f')}, {(fl.share > 0.5).sum()}")
    c = hl[hl.dmax <= 0.1]
    say("OK", "healthy, no window dCd > 0.1: n, share, median", "56, 0-0.368, 0.00015-0.0137",
        f"{len(c)}, {rng(c.share, '.3f')}, {c['median'].min():.2g}-{c['median'].max():.3g}")
    g = nw[nw.share > 0.5]
    say("OK", "new runs with share > 0.5; medians", "15; 0.058-0.418", f"{len(g)}; {rng(g['median'], '.3f')}")
    say("CHECK", "physics 'initial residuals 0.2-0.4 against 0.001-0.01'", "0.2-0.4 / 0.001-0.01",
        f"medians {rng(g['median'], '.3f')} ({(g['median'] >= 0.2).sum()} of {len(g)} >= 0.2) / clean {c['median'].min():.2g}-{c['median'].max():.3g}")
    say("NEW", "jumps without signature / signature without jumps (new)", "-",
        f"{((nw['J0.5'] > 0) & (nw.share <= 0.5)).sum()} / {((nw['J0.5'] == 0) & (nw.share > 0.5)).sum()}")
    say("CHECK", "nu_t/nu: signature runs max; runs with jumps range", "'none at Tu 3 %'",
        f"{g.vr.max():.1f}; {rng(nw[nw['J0.5'] > 0].vr, '.1f')}")
    say("OK", "maxCo 1.25: window share; share at 0-20 c/U", "0", f"{D[D.maxCo == 1.25].share.max():g}; " +
        ", ".join(f"a{int(r.alpha_deg)} {r.model} {r.share_0_20:.2f}" for _, r in D[D.maxCo == 1.25].iterrows()))

    def get(al, U, m, tu=1.0, co=2.5):
        x = D[(D.alpha_deg == al) & (D.U_ms == U) & (D.model == m) & (D.Tu_body_pct == tu) & (D.maxCo == co) & (D.level == "medium") & ~D.flag]
        assert len(x) == 1
        return x.iloc[0]

    def chg(A, B):
        d, n = A.Cd_mean - B.Cd_mean, abs(A.Cd_drift) + abs(B.Cd_drift)
        dn, nn = A.Cd_nj - B.Cd_nj, abs(A.drift_nj) + abs(B.drift_nj)
        res = A.share_nj >= 0.5 and B.share_nj >= 0.5 and abs(d) > n and abs(dn) > nn and np.sign(d) == np.sign(dn)
        return 100 * d / abs(B.Cd_mean), n, res, abs(d) / n

    print("== S3")
    for m, qp in (("SST", "-17.51 (5.6x)"), ("LM", "-14.78 (5.3x)")):
        A, B = get(180, 23.0, m, co=1.25), get(180, 23.0, m)
        p, n, res, x = chg(A, B)
        say("OK", f"{m} alpha 180 maxCo 2.5 -> 1.25", qp, f"{p:.2f} % (noise {n:.4f}, {x:.1f}x, resolved {res}); dCl {A.Cl_mean - B.Cl_mean:+.3f}")
        t, cd, cl = H[A.name]
        bl = [cl[(t >= lo) & (t < lo + 10)].std() for lo in range(0, 150, 10)]
        tq = next(10 * k for k in range(15) if max(bl[k:]) < 1e-3)
        say("CHECK", f"{m} 1.25 'steady from ~{15 if m == 'SST' else 20} c/U'", f"~{15 if m == 'SST' else 20} c/U",
            f"10-c/U lift std < 0.001 from {tq} c/U (20-30: {bl[2]:.2g}); window lift std {A.Cl_std:.2g}; table St {A.St:.3f} (peak {A.St_peak_frac:.2f})")
    sh = D[~D.flag & (D.maxCo == 2.5) & (D.level == "medium") & (D.Cl_std > 0.3) & (D.share < 0.05)]
    say("CHECK", "physics: 'unconverged p solves keep the wake shedding'", "inferred",
        f"{len(sh)} maxCo-2.5 runs shed (lift std > 0.3) with share < 0.05, e.g. LM Tu3 38 m/s a150: lift std "
        f"{get(150, 38.0, 'LM', 3.0).Cl_std:.2f}, share {get(150, 38.0, 'LM', 3.0).share:.3f}")

    print("== S4")
    tM, cM, _ = H["a000.0_U23.0_SST_medium_Tu1.0"]
    tU, cU, _ = H[EXTRA[0]]
    m = (tM >= 2) & (tM <= tU[-1])
    rj = json.loads((RUNS / EXTRA[0] / "results.json").read_text())
    say("OK", "Unity repeat: Cd, Cl, St; max sample |dCd|", "3.1894, -0.6905, 0.12173; 0.038",
        f"{rj['Cd_mean']:.4f}, {rj['Cl_mean']:.4f}, {rj['St']:.5f}; {np.abs(np.interp(tM[m], tU, cU) - cM[m]).max():.3f}")
    S1 = get(0, 23.0, "SST", co=1.25)
    t, cd, cl = H[S1.name]
    tm, rm = runmean(t, cd, 8.0)
    blk = [cd[(t >= lo) & (t < lo + 10)].mean() for lo in range(0, 150, 10)]
    say("OK", "SST a0 1.25: last running mean > 2.5; e-fold; last 10", "102.4; 13.8; 1.822",
        f"{tm[np.flatnonzero(rm > 2.5)[-1]]:.1f}; {-efold(cycles(t, cl, 95, 150)):.1f}; {S1.Cd_l10:.3f}")
    d3 = np.diff(blk[-4:])
    r_ = np.mean(d3[1:] / d3[:-1])
    say("NEW", "SST a0 1.25: 10-c/U means 110-150; geometric extrapolation", "-",
        f"{', '.join(f'{v:.3f}' for v in blk[-4:])}; -> {blk[-1] + d3[-1] * r_ / (1 - r_):.2f} (estimated; maxCo 2.5: {get(0, 23.0, 'SST').Cd_mean:.3f})")
    L5, L1 = get(0, 23.0, "LM", co=5.0), get(0, 23.0, "LM", co=1.25)
    t, cd, cl = H[L1.name]
    blk = [cd[(t >= lo) & (t < lo + 10)].mean() for lo in range(0, 150, 10)]
    d3 = np.diff(blk[-4:])
    r_ = np.mean(d3[1:] / d3[:-1])
    say("CHECK", "'within a state the time step moves Cd by about 1 %' (LM a0)", "about 1 %",
        f"LM maxCo 5 last 10 {L5.Cd_l10:.3f} -> 1.25 last 10 {L1.Cd_l10:.3f} ({100 * (L1.Cd_l10 / L5.Cd_l10 - 1):+.1f} %), still falling "
        f"{-d3[-1]:.3f} per 10 c/U, extrapolated {blk[-1] + d3[-1] * r_ / (1 - r_):.2f} (estimated)")
    for rst, q in ((EXTRA[1], "3.253/3.198/3.171"), (EXTRA[2], "1.737/1.745/1.754")):
        tr, cr, lr = H[rst]
        b = [cr[(tr >= 150 + lo) & (tr < 150 + hi + (1e-6 if hi == 60 else 0))].mean() for lo, hi in ((0, 10), (10, 30), (30, 60))]
        say("OK", f"{rst}: Cd 0-10/10-30/30-60 c/U", q, "/".join(f"{v:.3f}" for v in b))
    tr, cr, lr = H[EXTRA[2]]
    c8 = cycles(tr, lr, 155, 210, floor=0.003)
    say("CHECK", "restart (b): 'it was leaving the low-drag state'", "constant growth, 79 c/U",
        f"p2p {c8[0, 1]:.4f} -> {c8[-1, 1]:.3f} ({len(c8)} cycles); e-fold {efold(c8[:4]):.0f} -> {efold(c8[-4:]):.0f} c/U; "
        f"to p2p 2.46: {efold(c8) * np.log(2.46 / c8[-1, 1]):.0f} c/U at the mean rate, {efold(c8[-4:]) * np.log(2.46 / c8[-1, 1]):.0f} at the late rate")

    print("== S5")
    P = D[(D.model == "LM") & (D.U_ms == 23) & (D.Tu_body_pct == 1) & ~D.flag]
    say("OK", "healthy LM polar angles; Cd range at maxCo 2.5", "24; 0.217-1.590", f"{P.alpha_deg.nunique()}; {rng(P[P.maxCo == 2.5].Cd_mean, '.3f')}")
    say("CHECK", "residual signature in the polar (caveat named 195, 210)", "195, 210",
        ", ".join(f"{int(r.alpha_deg)}@{r.maxCo:g} {r.share:.2f} J{int(r['J0.5'])}" for _, r in P[P.share > 0.5].iterrows()))
    pf = 100 * hl.Cd_pressure_mean / hl.Cd_mean
    say("NEW", "pressure drag share, all healthy runs / alpha 0 and 180", "13 Oct: >= 98.5 %",
        f"{pf.min():.1f} % ({pf.idxmin()[:4]}) / {pf[hl.alpha_deg.isin([0, 180])].min():.1f} %")

    print("== S6 (LM - SST, maxCo 2.5, Tu 1 %)")
    quiet_res = []
    for U in (10.2, 23.0, 38.0):
        for al in (150, 165, 180, 195, 210):
            A, B = get(al, U, "LM"), get(al, U, "SST")
            p, n, res, x = chg(A, B)
            if U < 30 and res and A.share < 0.5 and B.share < 0.5:
                quiet_res.append(f"{al}@{U:g}: SST jumps {int(B['J0.5'])}")
            print(f"      {U:4g} {al}: {p:+6.1f} % noise {n:.4f} ({x:.1f}x) resolved {res}; shares {A.share:.2f}/{B.share:.2f}; jumps {int(A['J0.5'])}/{int(B['J0.5'])}")
    say("CHECK", "'4 resolved pairs free of solver disturbance'", "4 (165@10.2 'clean pair')", "; ".join(quiet_res))
    p, n, res, x = chg(get(180, 38.0, "LM"), get(180, 38.0, "SST"))
    say("CHECK", "38 m/s alpha 180: 'equal' / 'a trip changes nothing'", "equal", f"{p:+.2f} % ({x:.1f}x noise {n:.4f}, resolved {res})")
    p, n, res, x = chg(get(180, 23.0, "LM", co=1.25), get(180, 23.0, "SST", co=1.25))
    say("OK", "maxCo 1.25 pair at alpha 180", "-8.59 %, 0.0366", f"{p:+.2f} %, {n:.4f} ({x:.2f}x)")

    print("== S6/S7 wall data at alpha 180")
    for U in (10.2, 23.0, 38.0):
        l, s = wall(get(180, U, "LM").name), wall(get(180, U, "SST").name)
        print(f"      {U:4g} m/s: sep LM {l['sep']:.3f} SST {s['sep']:.3f}; Cf peak ratio {l['cfpk'] / s['cfpk']:.2f}; base Cp LM {l['cpb']:.3f} SST {s['cpb']:.3f}")
    l, s = wall(get(180, 23.0, "LM", co=1.25).name), wall(get(180, 23.0, "SST", co=1.25).name)
    say("CHECK", "separation gap LM-SST at maxCo 1.25 (2.5: 0.097 c)", "laminar-separation reading",
        f"sep LM {l['sep']:.3f} SST {s['sep']:.3f}, gap {s['sep'] - l['sep']:.3f} c; base Cp LM {l['cpb']:.3f} SST {s['cpb']:.3f}")
    print("      Tu (LM, 23 m/s): sep " + " / ".join(f"{wall(get(180, 23.0, 'LM', tu).name)['sep']:.3f}" for tu in (0.5, 1.0, 3.0)))

    print("== S7")
    p, n, res, x = chg(get(180, 10.2, "LM"), get(180, 23.0, "LM"))
    say("CHECK", "LM Tu 1 % alpha 180, 10.2 vs 23 m/s ('flat')", "flat", f"{p:+.2f} % ({x:.1f}x, resolved {res})")
    for U1, U0, m, q in ((38.0, 23.0, "LM", "+20.5"), (38.0, 23.0, "SST", "+7.1")):
        p, n, res, x = chg(get(180, U1, m), get(180, U0, m))
        say("OK", f"{m} alpha 180, {U1:g} vs {U0:g} m/s", q, f"{p:+.1f} % ({x:.1f}x)")
    p, n, res, x = chg(get(180, 10.2, "SST"), get(180, 23.0, "SST"))
    say("NEW", "SST alpha 180, 10.2 vs 23 m/s (non-monotonic)", "-", f"{p:+.1f} % ({x:.1f}x, resolved {res}); 13 Oct grid at 23 m/s: coarse 1.669, fine 1.653")
    for U, tu, q in ((23.0, 3.0, "-17.0"), (38.0, 0.5, "+6.7"), (38.0, 3.0, "-6.6"), (10.2, 3.0, "-12.1")):
        p, n, res, x = chg(get(180, U, "LM", tu), get(180, U, "LM"))
        say("OK", f"LM alpha 180 {U:g} m/s Tu {tu:g} vs 1 %", q, f"{p:+.1f} % ({x:.1f}x, resolved {res})")

    print("== S8 / S9")
    for U in (10.2, 23.0, 38.0):
        A, B = get(180, U, "SST"), get(180, U, "LM")
        n = abs(A.Cl_drift) + abs(B.Cl_drift)
        say("NEW", f"alpha 180 {U:g} m/s: LM -> SST change of Cl (drift noise)", "-",
            f"Cd {100 * (A.Cd_mean / B.Cd_mean - 1):+.1f} %; Cl {B.Cl_mean:+.3f} -> {A.Cl_mean:+.3f} (|Cl| {100 * (abs(A.Cl_mean) / abs(B.Cl_mean) - 1):+.0f} %, {abs(A.Cl_mean - B.Cl_mean) / n:.1f}x)")
    A, B = get(180, 23.0, "SST", co=1.25), get(180, 23.0, "LM", co=1.25)
    say("NEW", "alpha 180 maxCo 1.25: LM -> SST", "-", f"Cd {100 * (A.Cd_mean / B.Cd_mean - 1):+.1f} %; |Cl| {100 * (abs(A.Cl_mean) / abs(B.Cl_mean) - 1):+.0f} %")
    l0, s0, l1, s1 = get(0, 23.0, "LM", co=1.25), get(0, 23.0, "SST", co=1.25), get(180, 23.0, "LM", co=1.25), get(180, 23.0, "SST", co=1.25)
    say("OK", "D last 10 c/U at maxCo 1.25, LM / SST", "0.583 / 0.602 (+3.3 %)", f"{l0.Cd_l10 - l1.Cd_l10:.3f} / {s0.Cd_l10 - s1.Cd_l10:.3f}")
    k = s0.Cd_l10 / s1.Cd_mean
    say("OK", "SST maxCo 1.25: k, lambda0", "1.49, 0.100", f"{k:.2f}, {(np.sqrt(k) - 1) / (np.sqrt(k) + 1):.3f}")
    print(f"\n{COUNT['OK']} OK, {COUNT['CHECK']} CHECK, {COUNT['NEW']} NEW")


if __name__ == "__main__":
    main()
