#!/usr/bin/env python3
"""Independent check of the Stage 1 (smooth section) numbers quoted from the 15 Oct analysis.

    nice -n 10 python3 cfd/analysis/2026-10-15/src/section_verify.py      # about 1 min

Written 19 Oct 2026. It shares no code with section_lib.py, section_histories.py,
section_analysis.py or cfd/post/section_summary.py:
  - its own reader of coefficient.dat (the new runs, the Unity repeat and the restarts have one
    session each; the script checks that);
  - its own streaming parser of log.pimpleFoam (first pressure solve of each time step);
  - its own reader of the records' surface_mean.csv and its own separation search;
  - running means with pandas rolling over samples; cycles with scipy.signal.find_peaks.
Each line prints the quoted text, the recomputed value(s) and OK, or CHECK when a value differs from
the quoted text by more than half a unit of its last digit (or the tolerance given). It ends with
the number of CHECK lines.

Reads (read only): cfd/section2d/results/section_polars.csv, cfd/analysis/2026-10-13/data/
section_polars.csv, cfd/section2d/runs/<case>/{case.json,postProcessing/forceCoeffs1,log.pimpleFoam}
and cfd/section2d/results/records/<case>/fields/surface_mean.csv. Writes nothing.
"""
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

REPO = Path(__file__).resolve().parents[4]
TAB = REPO / "cfd" / "section2d" / "results" / "section_polars.csv"
OLD = REPO / "cfd" / "analysis" / "2026-10-13" / "data" / "section_polars.csv"
RUNS = REPO / "cfd" / "section2d" / "runs"
REC = REPO / "cfd" / "section2d" / "results" / "records"
CORNER = {"coarse": 64e-6, "medium": 45e-6, "fine": 32e-6}
NUM = re.compile(r"[−+-]?\d+(?:\.\d+)?(?:e[−+-]?\d+)?")
n_bad = 0


def half_unit(tok):
    mant, _, exp = tok.replace("−", "-").partition("e")
    dec = len(mant.split(".")[1]) if "." in mant else 0
    return 0.5 * 10 ** (-dec) * (10 ** int(exp) if exp else 1) * (1 + 1e-9)


def show(label, quoted, values, tol=None):
    global n_bad
    vals = [float(v) for v in (values if isinstance(values, (list, tuple, np.ndarray)) else [values])]
    toks = NUM.findall(quoted)
    q = [float(t.replace("−", "-")) for t in toks]
    ok = len(q) == len(vals) and all(abs(a - b) <= (tol if tol is not None else half_unit(t))
                                     for a, b, t in zip(q, vals, toks))
    n_bad += not ok
    print(f"{'OK   ' if ok else 'CHECK'} {label:60s} quoted {quoted:>34s} | recomputed "
          + ", ".join(f"{v:.6g}" for v in vals))


def claim(label, text, value):
    global n_bad
    n_bad += not value
    print(f"{'OK   ' if value else 'CHECK'} {label:60s} {text}")


# ------------------------------------------------------------------ readers
def conv(name):
    P = json.loads((RUNS / name / "case.json").read_text())
    return P["convTime"], P


def coeffs(name):
    """t (c/U), Cd, Cl from the single forceCoeffs1 session of a run."""
    d = RUNS / name / "postProcessing" / "forceCoeffs1"
    subs = [p for p in d.iterdir() if p.is_dir()]
    assert len(subs) == 1, f"{name}: {len(subs)} sessions"
    hdr, rows = None, []
    with open(subs[0] / "coefficient.dat") as f:
        for line in f:
            if line.startswith("#"):
                if line[1:].split()[:1] == ["Time"]:
                    hdr = line[1:].split()
                continue
            if line.strip():
                rows.append(line.split())
    a = np.array(rows, float)
    tc, _ = conv(name)
    return a[:, 0] / tc, a[:, hdr.index("Cd")], a[:, hdr.index("Cl")]


def jumps_in_window(t, cd, lim, w0=50, w1=150):
    dd = np.abs(np.diff(cd))
    tt = t[1:]
    ks = {int(math.floor(x)) for x in tt[(dd > lim) & (tt >= 2.0)]}
    return {k if k < w1 else w1 - 1 for k in ks if w0 <= k <= w1}


def first_p_residuals(name):
    """(t c/U, initial residual of the first pressure solve) for every time step of log.pimpleFoam."""
    tc, _ = conv(name)
    ts, rs, t, want = [], [], None, False
    with open(RUNS / name / "log.pimpleFoam", errors="replace") as f:
        for line in f:
            if line.startswith("Time = "):
                t, want = float(line.split()[2]) / tc, True
            elif want and line.startswith("GAMG:  Solving for p,"):
                rs.append(float(line.split("Initial residual = ")[1].split(",")[0]))
                ts.append(t)
                want = False
    return np.array(ts), np.array(rs)


def residual_share(name):
    t, r = first_p_residuals(name)
    m = (t >= 50 - 1e-9) & (t <= 150 + 1e-9)
    return float(np.mean(r[m] > 0.05))


def surface(name):
    s = pd.read_csv(REC / name / "fields" / "surface_mean.csv", comment="#")
    s = s[s.patch == "blade"].reset_index(drop=True)
    cvx = s[s.s_over_c <= 1.48]
    i_st = cvx.Cp.idxmax()
    side = s[(s.index > i_st) & (s.s_over_c <= 1.48)]
    i_pk = side.Cf.idxmax()
    after = side[(side.index > i_pk) & (side.Cf <= 0)]
    base = s[(s.s_over_c >= 1.60) & (s.s_over_c <= 2.85)].Cp.mean()
    return float(after.s_over_c.iloc[0]), float(base)


def p2p_cycles(t, cl, t0, t1, min_amp=0.003, min_gap=4.0):
    """(t of max, max - next min) of a 1-c/U centred rolling mean, cycles of at least min_amp."""
    s = pd.Series(cl).rolling(50, center=True).mean().to_numpy()
    ok = np.isfinite(s)
    tt, ss = t[ok], s[ok]
    imax, _ = find_peaks(ss)
    imin, _ = find_peaks(-ss)
    out = []
    for i in imax:
        if t0 <= tt[i] <= t1:
            nxt = imin[imin > i]
            if nxt.size:
                amp = ss[i] - ss[nxt[0]]
                if amp >= min_amp and (not out or tt[i] - out[-1][0] >= min_gap):
                    out.append((tt[i], amp))
    return out


def main():
    d = pd.read_csv(TAB)
    old = pd.read_csv(OLD)
    print("== A. Table")
    show("cases in the 15 Oct table", "125", len(d))
    new = d[~d.name.isin(old.name)]
    show("new cases", "74", len(new))
    o, n = old.set_index("name"), d.set_index("name").loc[old.name]
    cols = [c for c in d.columns if c != "name" and pd.api.types.is_numeric_dtype(d[c])]
    diff = sum(int(not np.isclose(float(o.loc[k, c]), float(n.loc[k, c]), rtol=1e-12, atol=0, equal_nan=True))
               for k in old.name for c in cols)
    show("differing values in the 51 old rows", "0", diff)

    print("== B. Health flag (13 Oct) and symptoms")
    d["proxy"] = d.maxCo * d.level.map(CORNER) / (d.dt_mean_s * d.U_ms)
    d["flag"] = d.proxy > 5
    d["new"] = ~d.name.isin(old.name)
    show("flagged runs, all / new", "23 / 0", [d.flag.sum(), (d.flag & d.new).sum()])
    show("time-step proxy of the new runs", "1.10–4.46", [d[d.new].proxy.min(), d[d.new].proxy.max()])
    reruns = [x + "_Co2.5n2" for x in old[(old.maxCo * old.level.map(CORNER) / (old.dt_mean_s * old.U_ms)) > 5].name]
    rr = d[d.name.isin(reruns)]
    show("re-runs found / flagged", "23 / 0", [len(rr), rr.flag.sum()])
    show("time-step proxy of the 23 re-runs", "1.30–4.46", [rr.proxy.min(), rr.proxy.max()])
    sym = (d.Cd_mean < 0) | (d.Cd_std > d.Cd_mean.abs()) | (d.Cl_mean.abs() > 3) | (d.yplus_max_mean > 2)
    show("re-runs with a 13 Oct symptom", "0", (sym & d.name.isin(reruns)).sum())
    sw = d[sym & ~d.flag].sort_values("name")
    claim("healthy runs with a symptom: the four 10.2 m/s runs", ", ".join(sw.name),
          list(sw.name) == ["a195.0_U10.2_LM_medium_Tu0.5_Co2.5n2", "a195.0_U10.2_SST_medium_Tu1.0_Co2.5n2",
                            "a210.0_U10.2_LM_medium_Tu1.0_Co2.5n2", "a210.0_U10.2_SST_medium_Tu1.0_Co2.5n2"])
    show("their Cd_std / |Cd_mean|", "1.06, 1.03, 1.53, 1.0001", (sw.Cd_std / sw.Cd_mean.abs()).tolist(), tol=0.006)

    print("== C. Force jumps of the new runs (own reader)")
    cnt = {0.5: 0, 0.2: 0, 0.1: 0}
    jb = {}
    for name in new.name:
        t, cd, cl = coeffs(name)
        for lim in cnt:
            j = jumps_in_window(t, cd, lim)
            cnt[lim] += bool(j)
            if lim == 0.5:
                jb[name] = len(j)
    show("new runs with jumps at the limits 0.5 / 0.2 / 0.1", "25 / 32 / 36", [cnt[0.5], cnt[0.2], cnt[0.1]])
    sst10 = [jb[n] for n in new.name if "_U10.2_SST" in n]
    show("SST at 10.2 m/s (5 runs): with jumps; interval range", "5; 7–26", [sum(x > 0 for x in sst10), min(sst10),
                                                                              max(sst10)])
    co125 = [n for n in new.name if "Co1.25" in n]
    show("maxCo-1.25 runs: jump intervals in the window (sum)", "0", sum(jb[n] for n in co125))
    rrj = sorted(n for n in rr.name if jb.get(n, 0) > 0 or n == "a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2")
    t, cd, cl = coeffs("a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2")
    show("re-runs with jumps: LM 180/23/Tu0.5, SST 180/10.2, SST 180/23, LM 210/23",
         "26, 22, 8, 15", [jb["a180.0_U23.0_LM_medium_Tu0.5_Co2.5n2"], jb["a180.0_U10.2_SST_medium_Tu1.0_Co2.5n2"],
                           len(jumps_in_window(t, cd, 0.5)), jb["a210.0_U23.0_LM_medium_Tu1.0_Co2.5n2"]])
    claim("no other re-run has a jump in its window", f"{len(rrj)} re-runs with jumps", len(rrj) == 4)

    print("== D. Solver residual share (own log parser; three runs)")
    show("LM α 180, 23 m/s, maxCo 2.5: share of steps with p residual > 0.05", "0.412",
         residual_share("a180.0_U23.0_LM_medium_Tu1.0_Co2.5n2"))
    show("LM α 180, 23 m/s, maxCo 1.25", "0", residual_share("a180.0_U23.0_LM_medium_Tu1.0_Co1.25n2"))
    show("LM α 195, 23 m/s, maxCo 2.5", "0.963", residual_share("a195.0_U23.0_LM_medium_Tu1.0_Co2.5n2"))

    print("== E. Time step (alpha 0 and 180, medium, 23 m/s, Tu 1 %)")
    T = d.set_index("name")
    show("α 180 SST: Cd at maxCo 2.5 / 1.25", "1.4793 / 1.2204",
         [T.loc["a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2", "Cd_mean"], T.loc["a180.0_U23.0_SST_medium_Tu1.0_Co1.25n2", "Cd_mean"]])
    a, b = T.loc["a180.0_U23.0_SST_medium_Tu1.0_Co1.25n2"], T.loc["a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2"]
    show("α 180 SST: change 2.5 -> 1.25 (%), noise", "−17.51, 0.0466",
         [100 * (a.Cd_mean / b.Cd_mean - 1), abs(a.Cd_drift) + abs(b.Cd_drift)])
    a, b = T.loc["a180.0_U23.0_LM_medium_Tu1.0_Co1.25n2"], T.loc["a180.0_U23.0_LM_medium_Tu1.0_Co2.5n2"]
    show("α 180 LM: Cd 2.5 / 1.25; change (%); noise", "1.3091 / 1.1156; −14.78; 0.0369",
         [b.Cd_mean, a.Cd_mean, 100 * (a.Cd_mean / b.Cd_mean - 1), abs(a.Cd_drift) + abs(b.Cd_drift)])
    show("α 180 Cl at 2.5 / 1.25: SST, LM", "−0.959 / −0.568, −0.529 / −0.416",
         [T.loc["a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2", "Cl_mean"], T.loc["a180.0_U23.0_SST_medium_Tu1.0_Co1.25n2", "Cl_mean"],
          T.loc["a180.0_U23.0_LM_medium_Tu1.0_Co2.5n2", "Cl_mean"], T.loc["a180.0_U23.0_LM_medium_Tu1.0_Co1.25n2", "Cl_mean"]])
    for name, quoted in (("a180.0_U23.0_SST_medium_Tu1.0_Co1.25n2", "9.8e-5"),
                         ("a180.0_U23.0_LM_medium_Tu1.0_Co1.25n2", "3.2e-4")):
        t, cd, cl = coeffs(name)
        show(f"lift std, last 10 c/U: {name[:24]}", quoted, cl[t >= t[-1] - 10].std(), tol=0.06e-4)
    t, cd, cl = coeffs("a000.0_U23.0_SST_medium_Tu1.0_Co1.25n2")
    show("α 0 SST maxCo 1.25: window Cd; drift", "2.4452; −0.793",
         [T.loc["a000.0_U23.0_SST_medium_Tu1.0_Co1.25n2", "Cd_mean"], T.loc["a000.0_U23.0_SST_medium_Tu1.0_Co1.25n2", "Cd_drift"]])
    show("α 0 SST maxCo 1.25: Cd over the last 10 c/U", "1.822", cd[t >= t[-1] - 10].mean())
    blk = [cd[(t >= k) & (t < k + 10)].mean() for k in range(0, 90, 10)]
    blkl = [cl[(t >= k) & (t < k + 10)].mean() for k in range(0, 90, 10)]
    show("α 0 SST maxCo 1.25: 10-c/U block Cd, 0–90 c/U (min, max)", "2.77–3.20", [min(blk), max(blk)])
    show("α 0 SST maxCo 1.25: block mean Cl, 0–90 c/U (min, max)", "−0.17 to +0.26", [min(blkl), max(blkl)])
    rm = pd.Series(cd).rolling(400, center=True).mean().to_numpy()
    above = np.where(rm > 2.5)[0]
    show("α 0 SST maxCo 1.25: running mean (8 c/U) last above 2.5 at (c/U)", "102.4", t[above[-1]], tol=0.3)
    cyc = [c for c in p2p_cycles(t, cl, 95, 149) if c[1] > 0.003]
    k = np.polyfit([c[0] for c in cyc], np.log([c[1] for c in cyc]), 1)[0]
    show("α 0 SST maxCo 1.25: decay e-folding of the lift cycles (c/U)", "13.8", -1 / k, tol=0.6)
    t, cd, cl = coeffs("a000.0_U23.0_LM_medium_Tu1.0_Co1.25n2")
    show("α 0 LM maxCo 1.25: window Cd; last 10 c/U", "1.836; 1.676",
         [T.loc["a000.0_U23.0_LM_medium_Tu1.0_Co1.25n2", "Cd_mean"], cd[t >= t[-1] - 10].mean()])

    print("== F. Unity repeat and restarts")
    tm, cdm, clm = coeffs("a000.0_U23.0_SST_medium_Tu1.0")
    tu, cdu, clu = coeffs("_unity_a000.0_U23.0_SST_medium_Tu1.0")
    R = json.loads((RUNS / "_unity_a000.0_U23.0_SST_medium_Tu1.0" / "results.json").read_text())
    show("Unity repeat: Cd, Cl, St", "3.1894, −0.6905, 0.12173", [R["Cd_mean"], R["Cl_mean"], R["St"]])
    show("Unity against Mac: Cd change (%)", "−0.033", 100 * (R["Cd_mean"] / T.loc["a000.0_U23.0_SST_medium_Tu1.0", "Cd_mean"] - 1))
    m = (tm >= 2) & (tm <= tu[-1])
    show("largest |ΔCd| between the two runs, 2–150 c/U", "0.038", np.abs(np.interp(tm[m], tu, cdu) - cdm[m]).max())
    ta, cda, cla = coeffs("_hyst_Co5to2p5_a000")
    parts = [(150, 160), (160, 180), (180, 210.01)]
    show("restart (a) Cd at 0–10 / 10–30 / 30–60 c/U", "3.253 / 3.198 / 3.171",
         [cda[(ta >= x) & (ta < y)].mean() for x, y in parts])
    show("restart (a) mean Cl, same parts", "−0.814 / −0.726 / −0.614", [cla[(ta >= x) & (ta < y)].mean() for x, y in parts])
    ca = p2p_cycles(ta, cla, 151, 209.5)
    show("restart (a) lift cycles: peak-to-peak range", "2.60–2.68", [min(c[1] for c in ca), max(c[1] for c in ca)],
         tol=0.01)
    show("restart (a) Cd 30–60 c/U against the parent's last 50 c/U (%)", "+1.08",
         100 * (cda[ta >= 180].mean() / cdm[tm >= 100].mean() - 1))
    tb, cdb, clb = coeffs("_hyst_Co2p5to5_a000")
    show("restart (b) Cd at 0–10 / 10–30 / 30–60 c/U", "1.737 / 1.745 / 1.754",
         [cdb[(tb >= x) & (tb < y)].mean() for x, y in parts])
    show("restart (b) lift std at 0–10 / 30–60 c/U", "0.0040 / 0.0167",
         [clb[(tb >= 150) & (tb < 160)].std(), clb[tb >= 180].std()])
    cb = p2p_cycles(tb, clb, 155, 209.5)
    kb = np.polyfit([c[0] for c in cb], np.log([c[1] for c in cb]), 1)[0]
    show("restart (b) growth e-folding of the lift cycles (c/U)", "20.4", 1 / kb, tol=1.5)
    show("restart (b) last cycle peak-to-peak", "0.050", cb[-1][1], tol=0.002)

    print("== G. LM polar at 23 m/s")
    lm = d[(d.model == "LM") & (d.U_ms == 23.0) & (d.Tu_body_pct == 1.0) & (d.level == "medium") & ~d.flag]
    claim("healthy LM angles at maxCo 5", str(sorted(lm[lm.maxCo == 5].alpha_deg.astype(int))),
          sorted(lm[lm.maxCo == 5].alpha_deg.astype(int)) == [0, 15, 30, 45, 60, 270, 315, 345])
    claim("healthy LM angles at maxCo 2.5", str(sorted(lm[lm.maxCo == 2.5].alpha_deg.astype(int))),
          sorted(lm[lm.maxCo == 2.5].alpha_deg.astype(int)) == [75, 90, 105, 120, 135, 150, 165, 180, 195, 210,
                                                                225, 240, 255, 285, 300, 330])
    g = lm[(lm.maxCo == 2.5) & lm.alpha_deg.between(75, 255)]
    show("Cd range at 75–255 (maxCo 2.5)", "0.217 (255) to 1.590 (165)", [g.Cd_mean.min(), 255, g.Cd_mean.max(), 165])
    r = lm[(lm.alpha_deg == 210)].iloc[0]
    show("α 210: Cd, drift / mean", "0.475, 0.341", [r.Cd_mean, r.Cd_drift / r.Cd_mean])

    print("== H. Transition test (maxCo 2.5, medium, Tu 1 %)")
    tt = d[(d.maxCo == 2.5) & (d.level == "medium") & d.alpha_deg.isin([150, 165, 180, 195, 210])]
    pct = {}
    for (al, U), gg in tt[tt.Tu_body_pct == 1.0].groupby(["alpha_deg", "U_ms"]):
        lmr, sst = gg[gg.model == "LM"].iloc[0], gg[gg.model == "SST"].iloc[0]
        pct[(int(al), U)] = 100 * (lmr.Cd_mean / sst.Cd_mean - 1)
    show("LM − SST (%) at 23 m/s, α 150/165/180/195/210", "−16.3, −13.9, −11.5, −16.9, −51.1",
         [pct[(a_, 23.0)] for a_ in (150, 165, 180, 195, 210)], tol=0.051)
    show("LM − SST (%) at 10.2 m/s", "−35.0, −30.9, −20.3, −10.7, −27.3",
         [pct[(a_, 10.2)] for a_ in (150, 165, 180, 195, 210)], tol=0.051)
    show("LM − SST (%) at 38 m/s", "+5.4, −33.2, −0.45, −1.8, +29.5",
         [pct[(a_, 38.0)] for a_ in (150, 165, 180, 195, 210)], tol=0.051)
    show("LM below SST: pairs at 10.2 / 23 / 38 m/s (of 5)", "5 / 5 / 3",
         [sum(pct[(a_, U)] < 0 for a_ in (150, 165, 180, 195, 210)) for U in (10.2, 23.0, 38.0)])
    a, b = T.loc["a180.0_U23.0_LM_medium_Tu1.0_Co1.25n2"], T.loc["a180.0_U23.0_SST_medium_Tu1.0_Co1.25n2"]
    show("α 180, 23 m/s, maxCo 1.25: LM − SST (%), noise", "−8.59, 0.0366",
         [100 * (a.Cd_mean / b.Cd_mean - 1), abs(a.Cd_drift) + abs(b.Cd_drift)])
    cdl = {(U, tu_): T.loc[f"a180.0_U{U:.1f}_LM_medium_Tu{tu_:.1f}_Co2.5n2", "Cd_mean"]
           for U in (10.2, 23.0, 38.0) for tu_ in (0.5, 1.0, 3.0)}
    show("LM α 180, Tu 0.5 / 1 / 3 % at 23 m/s", "1.388 / 1.309 / 1.087", [cdl[(23.0, x)] for x in (0.5, 1.0, 3.0)])
    show("LM α 180, Tu 0.5 / 1 / 3 % at 38 m/s", "1.683 / 1.578 / 1.474", [cdl[(38.0, x)] for x in (0.5, 1.0, 3.0)])
    show("LM α 180, Tu 1 / 3 % at 10.2 m/s", "1.320 / 1.161", [cdl[(10.2, x)] for x in (1.0, 3.0)])
    show("LM α 180 Tu 1: 23 -> 38 m/s (%); SST (%)", "+20.5; +7.1",
         [100 * (cdl[(38.0, 1.0)] / cdl[(23.0, 1.0)] - 1),
          100 * (T.loc["a180.0_U38.0_SST_medium_Tu1.0_Co2.5n2", "Cd_mean"] /
                 T.loc["a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2", "Cd_mean"] - 1)])
    show("LM α 180 at 23 m/s: Tu 3 against Tu 1 (%)", "−17.0", 100 * (cdl[(23.0, 3.0)] / cdl[(23.0, 1.0)] - 1))

    print("== I. Time-mean wall distributions, alpha 180 (own parser)")
    for name, quoted in (("a180.0_U23.0_LM_medium_Tu1.0_Co2.5n2", "1.238, −1.076"),
                         ("a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2", "1.334, −1.401"),
                         ("a180.0_U38.0_LM_medium_Tu1.0_Co2.5n2", "1.309, −1.504"),
                         ("a180.0_U38.0_SST_medium_Tu1.0_Co2.5n2", "1.369, −1.543"),
                         ("a180.0_U23.0_LM_medium_Tu1.0_Co1.25n2", "1.228, −0.824"),
                         ("a180.0_U23.0_SST_medium_Tu1.0_Co1.25n2", "1.253, −0.993"),
                         ("a180.0_U23.0_LM_medium_Tu0.5_Co2.5n2", "1.241, −1.187"),
                         ("a180.0_U23.0_LM_medium_Tu3.0_Co2.5n2", "1.250, −0.829")):
        show(f"tip-B separation s/c, base Cp: {name[:30]}", quoted, list(surface(name)))
    print("== J. Further quoted numbers")
    # separation and Cf peak at 10.2 and 38 m/s, Cf peak ratio LM/SST at alpha 180, Tu 1 %
    def cf_peak(name):
        s = pd.read_csv(REC / name / "fields" / "surface_mean.csv", comment="#")
        s = s[s.patch == "blade"].reset_index(drop=True)
        i_st = s[s.s_over_c <= 1.48].Cp.idxmax()
        return float(s[(s.index > i_st) & (s.s_over_c <= 1.48)].Cf.max())
    ratios = [cf_peak(f"a180.0_U{U}_LM_medium_Tu1.0_Co2.5n2") / cf_peak(f"a180.0_U{U}_SST_medium_Tu1.0_Co2.5n2")
              for U in ("10.2", "23.0", "38.0")]
    show("Cf peak (tip-B side) LM / SST at α 180: 10.2 / 23 / 38 m/s", "0.78 / 0.79 / 0.94", ratios)
    show("Cf peak at α 180, 23 m/s: LM, SST", "0.025, 0.032",
         [cf_peak("a180.0_U23.0_LM_medium_Tu1.0_Co2.5n2"), cf_peak("a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2")])
    show("tip-B separation at 10.2 m/s: LM, SST", "1.244, 1.325",
         [surface("a180.0_U10.2_LM_medium_Tu1.0_Co2.5n2")[0], surface("a180.0_U10.2_SST_medium_Tu1.0_Co2.5n2")[0]])
    show("LM α 180 at 38 m/s: separation Tu 0.5 / 3 %", "1.309 / 1.313",
         [surface("a180.0_U38.0_LM_medium_Tu0.5_Co2.5n2")[0], surface("a180.0_U38.0_LM_medium_Tu3.0_Co2.5n2")[0]])
    show("LM α 180 at 38 m/s: base Cp Tu 0.5 / 3 %", "−1.586 / −1.437",
         [surface("a180.0_U38.0_LM_medium_Tu0.5_Co2.5n2")[1], surface("a180.0_U38.0_LM_medium_Tu3.0_Co2.5n2")[1]])
    show("LM α 180 at 23 m/s: lift std Tu 0.5 / 1 / 3 %", "0.117 / 0.041 / 0.022",
         [T.loc[f"a180.0_U23.0_LM_medium_Tu{x}_Co2.5n2", "Cl_std"] for x in ("0.5", "1.0", "3.0")])
    show("α 180, 38 m/s: lift std LM, SST", "0.47, 0.43",
         [T.loc["a180.0_U38.0_LM_medium_Tu1.0_Co2.5n2", "Cl_std"], T.loc["a180.0_U38.0_SST_medium_Tu1.0_Co2.5n2", "Cl_std"]])
    t12 = tt[(tt.Tu_body_pct == 1.0) & tt.U_ms.isin([10.2, 23.0])]
    s_ = t12[t12.model == "SST"].Cl_std
    l_ = t12[(t12.model == "LM") & ~((t12.alpha_deg == 210) & (t12.U_ms == 10.2))].Cl_std
    show("lift std at 10.2 and 23 m/s: SST range; LM range (without α 210/10.2)", "0.19–1.16; 0.008–0.25",
         [s_.min(), s_.max(), l_.min(), l_.max()], tol=0.0051)
    show("LM α 210, 10.2 m/s: lift std", "0.97", T.loc["a210.0_U10.2_LM_medium_Tu1.0_Co2.5n2", "Cl_std"])
    show("a trip (LM -> SST) at α 180: 10.2 / 23 / 23 at maxCo 1.25 / 38 m/s (%)", "+25.5 / +13.0 / +9.4 / +0.45",
         [100 * (T.loc[f"a180.0_U{U}_SST_medium_Tu1.0_Co{c}n2", "Cd_mean"] /
                 T.loc[f"a180.0_U{U}_LM_medium_Tu1.0_Co{c}n2", "Cd_mean"] - 1)
          for U, c in (("10.2", "2.5"), ("23.0", "2.5"), ("23.0", "1.25"), ("38.0", "2.5"))])
    hi = {}
    for al in (150, 165):
        g1 = T.loc[f"a{al:.1f}_U38.0_LM_medium_Tu1.0_Co2.5n2"]
        for x in ("0.5", "3.0"):
            g = T.loc[f"a{al:.1f}_U38.0_LM_medium_Tu{x}_Co2.5n2"]
            hi[(al, x)] = (100 * (g.Cd_mean / g1.Cd_mean - 1), g.Cl_std, g1.Cl_std)
    show("38 m/s, α 150/165: Tu 0.5 and 3 % above Tu 1 % (%, range)", "41–62",
         [min(v[0] for v in hi.values()), max(v[0] for v in hi.values())], tol=0.51)
    show("their lift std; Tu 1 % lift std (ranges)", "0.71–1.20; 0.02–0.04",
         [min(v[1] for v in hi.values()), max(v[1] for v in hi.values()),
          min(v[2] for v in hi.values()), max(v[2] for v in hi.values())], tol=0.0051)
    # alpha 180 last 10 c/U at maxCo 1.25, drag differences D
    lmf = {}
    for name in ("a180.0_U23.0_LM_medium_Tu1.0_Co1.25n2", "a180.0_U23.0_SST_medium_Tu1.0_Co1.25n2",
                 "a000.0_U23.0_LM_medium_Tu1.0_Co1.25n2", "a000.0_U23.0_SST_medium_Tu1.0_Co1.25n2"):
        t, cd, cl = coeffs(name)
        lmf[name] = cd[t >= t[-1] - 10].mean()
    show("α 180, maxCo 1.25, last 10 c/U: LM, SST", "1.093, 1.220",
         [lmf["a180.0_U23.0_LM_medium_Tu1.0_Co1.25n2"], lmf["a180.0_U23.0_SST_medium_Tu1.0_Co1.25n2"]])
    dl = lmf["a000.0_U23.0_LM_medium_Tu1.0_Co1.25n2"] - lmf["a180.0_U23.0_LM_medium_Tu1.0_Co1.25n2"]
    ds = lmf["a000.0_U23.0_SST_medium_Tu1.0_Co1.25n2"] - lmf["a180.0_U23.0_SST_medium_Tu1.0_Co1.25n2"]
    show("D = Cd(0) − Cd(180), last 10 c/U, maxCo 1.25: LM, SST; SST/LM − 1 (%)", "0.583, 0.602; +3.3",
         [dl, ds, 100 * (ds / dl - 1)])
    k = lmf["a000.0_U23.0_SST_medium_Tu1.0_Co1.25n2"] / lmf["a180.0_U23.0_SST_medium_Tu1.0_Co1.25n2"]
    show("two-position model, SST maxCo 1.25 (last 10 c/U): k, λ0", "1.49, 0.100",
         [k, (math.sqrt(k) - 1) / (math.sqrt(k) + 1)])
    # frontal width at alpha 180 from the outline (own projection on the chord direction)
    xy = pd.read_csv(REPO / "cfd" / "geometry" / "section_v1.csv").to_numpy()
    ey = np.deg2rad(85.23635850611012)
    proj = xy @ np.array([np.cos(ey), np.sin(ey)])
    w180 = proj.max() - proj.min()
    show("α 180 frontal width (mm); SST maxCo 1.25 Cd on it", "48.76; 1.201",
         [w180 * 1e3 if w180 < 1 else w180, T.loc["a180.0_U23.0_SST_medium_Tu1.0_Co1.25n2", "Cd_mean"] * 48.0 /
          (w180 * 1e3 if w180 < 1 else w180)])
    pl = lm.set_index("alpha_deg")
    show("LM polar: Cl min (60°), max (300°); Cm min (120°), max (60°)", "−2.682, +1.651, −0.357, +0.538",
         [pl.loc[60, "Cl_mean"], pl.loc[300, "Cl_mean"], pl.loc[120, "Cm_mean"], pl.loc[60, "Cm_mean"]])
    show("LM polar, α 15: drift / mean", "0.353", pl.loc[15, "Cd_drift"] / pl.loc[15, "Cd_mean"])
    print(f"\n{n_bad} CHECK line(s)")


if __name__ == "__main__":
    main()
