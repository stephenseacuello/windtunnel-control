#!/usr/bin/env python3
"""Independent check of the numbers quoted in RESULTS.md, "Addendum (13 Oct): force histories".

Written 14 Oct 2026. It shares no code with section_histories.py or cfd/post/section_summary.py:
  - its own readers of coefficient.dat (restarts joined: each session replaces the earlier rows
    from its start time on), yPlus.dat and log.pimpleFoam (a streaming line parser);
  - running means with pandas rolling over the samples (no interpolation to a uniform grid);
  - scipy.signal.find_peaks for the start-up lift cycles.
Each line prints the quoted text, the recomputed value(s) and OK, or CHECK when a value differs
from the quoted text by more than half a unit of its last digit. Times of entry and settling
(running mean centred on a sample here, on a uniform grid there) are allowed 0.15 c/U.

    nice -n 10 python3 cfd/analysis/2026-10-13/src/section_histories_verify.py            # about 60 s
    nice -n 10 python3 cfd/analysis/2026-10-13/src/section_histories_verify.py --repeat DIR

--repeat DIR also checks the Unity repeat of a000.0_U23.0_SST_medium_Tu1.0 (job 65650307, folder
_unity_a000.0_U23.0_SST_medium_Tu1.0; not downloaded on 14 Oct) from DIR/case.json, DIR/results.json
and DIR/coefficient.dat or DIR/postProcessing/forceCoeffs1/0/coefficient.dat. Without it, those
lines print NOT CHECKED and do not count.

Reads (read only): cfd/section2d/runs/<case>/case.json, postProcessing/forceCoeffs1/,
postProcessing/yPlus1/ and, for two runs, log.pimpleFoam; ../data/section_polars.csv (names, the
Mac values, the alpha-0 state ranges of section 2.3); ../out/section_case_quality.csv (the flag).
Writes nothing.
"""
import argparse
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

ROOT = Path(__file__).resolve().parents[1]                 # cfd/analysis/2026-10-13
RUNS = ROOT.parents[2] / "cfd" / "section2d" / "runs"
LIMIT = 0.5                                                # Cd change between samples that is a jump
N_RM = 400                                                 # samples in 8 c/U (one per 0.02 c/U)
MED5, MED25 = "a000.0_U23.0_SST_medium_Tu1.0", "a000.0_U23.0_SST_medium_Tu1.0_Co2.5n2"
CO5, CO25 = "a000.0_U23.0_SST_coarse_Tu1.0", "a000.0_U23.0_SST_coarse_Tu1.0_Co2.5n2"
FINE, LM10 = "a000.0_U23.0_SST_fine_Tu1.0_Co2.5n2", "a000.0_U10.2_LM_medium_Tu1.0"
A180_5, A180_25 = "a180.0_U23.0_SST_medium_Tu1.0", "a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2"

n_bad = 0
NUM = re.compile(r"[−+-]?\d+(?:\.\d+)?(?:e[−+-]?\d+)?")


def numbers(text):
    return [float(x.replace("−", "-")) for x in NUM.findall(text)]


def half_unit(token):
    """Half a unit of the last digit of a quoted number ('3.190' -> 0.0005, '4.8e-5' -> 0.05e-5)."""
    mant, _, exp = token.replace("−", "-").partition("e")
    dec = len(mant.split(".")[1]) if "." in mant else 0
    return 0.5 * 10 ** (-dec) * (10 ** int(exp) if exp else 1) * (1 + 1e-9)


def show(label, quoted, values, tol=None):
    """quoted: the text in RESULTS.md, holding exactly the numbers checked, in order."""
    global n_bad
    vals = [float(v) for v in (values if isinstance(values, (list, tuple)) else [values])]
    toks = NUM.findall(quoted)
    q = numbers(quoted)
    ok = len(q) == len(vals) and all(
        abs(a - b) <= (tol if tol is not None else half_unit(t)) for a, b, t in zip(q, vals, toks))
    n_bad += not ok
    txt = ", ".join(f"{v:.6g}" for v in vals)
    print(f"{'OK   ' if ok else 'CHECK'} {label:58s} quoted {quoted:>30s} | recomputed {txt}")


def show_bool(label, claim, value):
    global n_bad
    n_bad += not value
    print(f"{'OK   ' if value else 'CHECK'} {label:58s} {claim}")


# ------------------------------------------------------------------ readers
def case(name):
    return json.loads((RUNS / name / "case.json").read_text())


def read_coeff(f):
    cols, rows = None, []
    with open(f) as fh:
        for line in fh:
            if line.startswith("#"):
                h = line[1:].split()
                if h[:1] == ["Time"]:
                    cols = h
            elif line.strip():
                rows.append(line.split())
    a = np.asarray(rows, dtype=float)
    return a[:, cols.index("Time")], a[:, cols.index("Cd")], a[:, cols.index("Cl")]


def forces(name, base=None):
    """dict: t (c/U), ts (s), Cd, Cl, window mask (last nAvg c/U), sessions, case parameters."""
    P = case(name) if base is None else json.loads((base / "case.json").read_text())
    tc = float(P["convTime"])
    if base is not None:
        f = base / "coefficient.dat"
        f = f if f.is_file() else base / "postProcessing" / "forceCoeffs1" / "0" / "coefficient.dat"
        sessions = [(0.0, f)]
    else:
        root = RUNS / name / "postProcessing" / "forceCoeffs1"
        sessions = []
        for d in root.iterdir():
            try:
                t0 = float(d.name)
            except ValueError:
                continue
            for f in sorted(d.glob("coefficient*.dat"), key=lambda x: x.stat().st_mtime):
                sessions.append((t0, f))
        sessions.sort(key=lambda s: s[0])
    ts, cd, cl = np.empty(0), np.empty(0), np.empty(0)
    for t0, f in sessions:
        a, b, c = read_coeff(f)
        keep = ts < t0                       # this session replaces the earlier rows from t0 on
        ts, cd, cl = np.r_[ts[keep], a], np.r_[cd[keep], b], np.r_[cl[keep], c]
    w = ts >= max(ts[0], ts[-1] - float(P["nAvg"]) * tc)
    return dict(t=ts / tc, ts=ts, Cd=cd, Cl=cl, w=w, n_sessions=len(sessions), P=P, tc=tc)


def jump_intervals(t, cd, limit=LIMIT):
    later = t[1:]
    sel = (np.abs(np.diff(cd)) > limit) & (later >= 2.0)
    return np.unique(np.floor(later[sel]).astype(int))


def window_intervals(J, k0=50, k1=150):
    """Intervals [k, k+1) of the window 50-150 c/U holding a jump; the last sample (150 + 2e-8)
    belongs to [149, 150]."""
    return sorted({min(int(k), k1 - 1) for k in J if k0 <= k <= k1})


def in_jumps(t, J):
    return np.isin(np.floor(t).astype(int), J)


def rmean(y, minp=None):
    return pd.Series(y).rolling(N_RM, center=True, min_periods=minp or N_RM).mean().to_numpy()


def stays_from(t, r, cond):
    """Earliest time after which cond(r) holds at every defined point to the last one."""
    i = np.where(np.isfinite(r))[0]
    c = cond(r[i])
    if not c[-1]:
        return math.nan
    bad = np.where(~c)[0]
    return float(t[i[0]] if bad.size == 0 else t[i[bad[-1] + 1]])


def cycles(t, cl, t0, t1):
    """(time, peak-to-peak) per cycle: a maximum of the 1-c/U running mean of Cl in [t0, t1] minus
    the next minimum."""
    s = pd.Series(cl).rolling(50, center=True).mean().to_numpy()
    s = np.where(np.isfinite(s), s, np.nanmean(s))
    mx, _ = find_peaks(s, distance=150)
    mn, _ = find_peaks(-s, distance=150)
    out = []
    for i in mx:
        nxt = mn[mn > i]
        if t0 <= t[i] <= t1 and nxt.size:
            out.append((float(t[i]), float(s[i] - s[nxt[0]])))
    return out


def yplus(name, tc):
    rows = []
    for d in (RUNS / name / "postProcessing" / "yPlus1").iterdir():
        for f in d.glob("yPlus*.dat"):
            for line in f.read_text().splitlines():
                s = line.split()
                if s and not line.startswith("#") and s[1] == "blade":
                    rows.append((float(s[0]), float(s[3])))
    a = np.array(sorted(set(rows)))
    return a[:, 0] / tc, a[:, 1]


def log_steps(name, tc):
    """(t c/U, dt c/U, initial residual of the first pressure solve) per time step."""
    T, DT, PR = [], [], []
    dt, pending, n_time = None, False, 0
    with open(RUNS / name / "log.pimpleFoam", "rb") as fh:
        for line in fh:
            if line.startswith(b"deltaT = "):
                dt = float(line[9:])
            elif line.startswith(b"Time = "):
                n_time += 1
                t, pending = float(line[7:]), True
            elif pending and b"Solving for p," in line:
                PR.append(float(line.split(b"Initial residual = ")[1].split(b",")[0]))
                T.append(t)
                DT.append(dt)
                pending = False
    if len(T) != n_time:
        raise SystemExit(f"{name}: {len(T)} pressure solves for {n_time} time steps")
    return np.array(T) / tc, np.array(DT) / tc, np.array(PR)


def blocks(t, lo, hi):
    return (t >= lo) & ((t < hi) if hi < 150 else (t <= hi + 1e-6))


# ------------------------------------------------------------------ checks
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repeat", help="folder with the Unity repeat's case.json, results.json, coefficient.dat")
    a = ap.parse_args()
    pol = pd.read_csv(ROOT / "data" / "section_polars.csv").set_index("name")
    flag = pd.read_csv(ROOT / "out" / "section_case_quality.csv").set_index("name")["corrupted"]
    F = {n: forces(n) for n in (MED5, MED25, CO5, CO25, FINE, LM10, A180_5, A180_25)}
    for n, f in F.items():
        f["J"] = jump_intervals(f["t"], f["Cd"])
        f["rm"] = rmean(f["Cd"])

    print("== data")
    show_bool("eight runs: one session, window 50-150 c/U", "one force session each; windows 50-150 c/U",
              all(f["n_sessions"] == 1 and abs(f["t"][f["w"]][0] - 50) < 0.03 and abs(f["t"][-1] - 150) < 1e-6
                  for f in F.values()))

    print("== start-up and settling")
    c5 = [min(cycles(F[n]["t"], F[n]["Cl"], 5, 45), key=lambda p: abs(p[0] - 24))[1] for n in (MED5, CO5)]
    show("maxCo 5: peak-to-peak Cl near 24 c/U (medium, coarse)", "3.0–3.2", [min(c5), max(c5)])
    cm, cc = cycles(F[MED25]["t"], F[MED25]["Cl"], 5, 45), cycles(F[CO25]["t"], F[CO25]["Cl"], 5, 45)
    ratios = [p[1] / q[1] for cyc in (cm, cc) for p, q in zip(cyc[:-1], cyc[1:])]
    show("maxCo 2.5: decay factor per cycle", "1.8–2.5", [min(ratios), max(ratios)])
    show("maxCo 2.5: last cycle by 45 c/U (medium, coarse)", "0.09 (medium) and 0.05", [cm[-1][1], cc[-1][1]])
    show("  ... at (c/U)", "about 40 c/U", (cm[-1][0] + cc[-1][0]) / 2, tol=2.0)
    cf = cycles(F[FINE]["t"], F[FINE]["Cl"], 5, 27)
    # the third cycle's minimum falls where the jumps start (28 c/U), so only two cycles are quoted
    show("fine: peak-to-peak Cl of the first two cycles", "2.53 and 1.89", [p[1] for p in cf[:2]])
    show("fine: their times (c/U)", "near 9 and 16", [p[0] for p in cf[:2]], tol=0.5)
    show("fine: decay factor", "1.34", cf[0][1] / cf[1][1])
    ent = []
    for n, hi in ((MED5, True), (CO5, True), (MED25, False), (CO25, False)):
        f = F[n]
        ent.append(stays_from(f["t"], f["rm"], (lambda r: r > 2.75) if hi else (lambda r: r < 2.25)))
    show("entry: high-drag medium, coarse (c/U)", "17.3 c/U (medium) and 8.9", ent[:2], tol=0.15)
    show("entry: low-drag medium, coarse (c/U)", "18.3 and 12.9", ent[2:], tol=0.15)
    st = []
    for n in (MED25, CO25, MED5, CO5):
        f = F[n]
        m50 = f["Cd"][f["t"] >= f["t"][-1] - 50].mean()
        st.append(stays_from(f["t"], f["rm"], lambda r, m=m50: np.abs(r / m - 1) <= 0.05))
    show("settling within 5 % (maxCo 2.5: medium, coarse)", "46.0 and 36.9", st[:2], tol=0.15)
    show("settling within 5 % (maxCo 5: medium, coarse)", "59.1 and 80.6", st[2:], tol=0.15)
    f = F[FINE]
    show("fine: first and last jump interval (c/U)", "from 28 to 96", [f["J"][0], f["J"][-1] + 1], tol=0)
    show("fine: low-drag from (c/U)", "97.0", stays_from(f["t"], f["rm"], lambda r: r < 2.25), tol=0.15)
    f = F[LM10]
    show("LM 10.2: first jump interval (c/U)", "from 21 c/U", f["J"][0], tol=0)
    m50 = f["Cd"][f["t"] >= f["t"][-1] - 50].mean()
    show_bool("LM 10.2: jumps to the end, never settles", "last jump interval [149, 150); never within 5 %",
              f["J"][-1] == 149 and math.isnan(stays_from(f["t"], f["rm"], lambda r: np.abs(r / m50 - 1) <= 0.05)))

    print("== state switches")
    rng = []
    for n in (FINE, LM10):
        f = F[n]
        cdm = np.where(in_jumps(f["t"], f["J"]), np.nan, f["Cd"])
        r = rmean(cdm, minp=N_RM // 2)
        sel = (f["t"] >= 30) & np.isfinite(r)
        rng += [r[sel].min(), r[sel].max()]
    show("jump-free running mean from 30 c/U, fine", "1.87–2.13", rng[:2])
    show("jump-free running mean from 30 c/U, LM", "1.93–2.30", rng[2:])
    # review of 14 Oct: what the fine run's jump-free samples cover, and its lift during the jumps
    f = F[FINE]
    J = set(int(k) for k in f["J"])
    span = list(range(min(J), max(J) + 1))
    show("fine: span of the jump intervals (c/U)", "between 28 and 96", [span[0], span[-1] + 1], tol=0)
    show_bool("  ... jump-free 1-c/U intervals in it", "only two", sum(k not in J for k in span) == 2)
    r = rmean(np.where(in_jumps(f["t"], f["J"]), np.nan, f["Cd"]), minp=N_RM // 2)
    sel = (f["t"] >= 30) & np.isfinite(r)
    show("fine: jump-free running mean defined (after 30 c/U) from", "95 c/U", f["t"][sel][0])
    clb = [f["Cl"][blocks(f["t"], lo, lo + 10)].mean() for lo in range(30, 90, 10)]
    show("fine: 10-c/U means of Cl, all samples, 30-90 c/U", "+0.06 to +0.17", [min(clb), max(clb)])
    hdb = [F[n]["Cl"][blocks(F[n]["t"], lo, lo + 10)].mean() for n in (MED5, CO5) for lo in range(50, 150, 10)]
    show("maxCo-5 medium and coarse: window 10-c/U means of Cl", "−0.91 to −0.46", [min(hdb), max(hdb)])
    hi = pol[(pol.alpha_deg == 0) & ~flag.reindex(pol.index).astype(bool) & (pol.Cd_mean > 2.5)]
    show("high-drag mean Cl range (section 2.3)", "−0.70 to −0.27", [hi.Cl_mean.min(), hi.Cl_mean.max()])
    cl_nj, sd, sd_nj, m_nj = [], [], [], []
    for n in (FINE, LM10):
        f = F[n]
        k = f["w"] & ~in_jumps(f["t"], f["J"])
        cl_nj.append(f["Cl"][k].mean())
        sd.append(f["Cd"][f["w"]].std())
        sd_nj.append(f["Cd"][k].std())
        m_nj.append(f["Cd"][k].mean())
    show("jump-free mean Cl, fine and LM", "+0.067 and +0.158", cl_nj)
    show("window Cd_std, fine and LM", "1.02 and 1.05", sd)
    show("jump-free Cd_std, fine and LM", "0.105 and 0.109", sd_nj)

    print("== window inside one state")
    rw = []
    for n in (MED5, CO5, MED25, CO25):
        f = F[n]
        sel = (f["t"] >= 50) & (f["t"] <= 150) & np.isfinite(f["rm"])
        rw += [f["rm"][sel].min(), f["rm"][sel].max()]
    show("running mean in the window, maxCo 5 med, coarse", "3.09–3.50 and 2.97–3.40", rw[:4])
    show("running mean in the window, maxCo 2.5 med, coarse", "1.74–1.81 and 1.79–1.83", rw[4:])
    for n, lab, qtxt in ((MED5, "medium", "1.7 % (medium, 3.190 against 3.137)"),
                         (CO5, "coarse", "3.0 % (coarse, 3.168 against 3.076)")):
        f = F[n]
        mw, m50 = f["Cd"][f["w"]].mean(), f["Cd"][f["t"] >= f["t"][-1] - 50].mean()
        show(f"maxCo 5 {lab}: window mean above last-50 mean", qtxt, [100 * (mw / m50 - 1), mw, m50])
    show("window jump intervals, fine and LM", "45 and 32",
         [len(window_intervals(F[n]["J"])) for n in (FINE, LM10)], tol=0)
    show("jump-free window means, fine and LM", "1.904 and 2.026", m_nj)
    show("table window means, fine and LM", "1.925 and 2.013", [F[n]["Cd"][F[n]["w"]].mean() for n in (FINE, LM10)])
    f = F[FINE]
    l50 = f["t"] >= f["t"][-1] - 50
    show_bool("fine: last 50 c/U without jumps", "no jump interval at 100-150 c/U", not any(k >= 100 for k in f["J"]))
    show("fine: last-50 mean", "1.885", f["Cd"][l50].mean())
    show("fine: 10-c/U means 100-110 and 140-150", "1.912 to 1.870",
         [f["Cd"][blocks(f["t"], 100, 110)].mean(), f["Cd"][blocks(f["t"], 140, 150)].mean()])
    g = [F[n]["Cd"][F[n]["t"] >= F[n]["t"][-1] - 50].mean() for n in (CO25, MED25, FINE)]
    show("alpha-0 last-50 values coarse / medium / fine", "1.789 / 1.740 / 1.885", g)
    show("  spread (% of fine), and section 2.4 (window values)", "7.7 % of the fine value (9.0 %",
         [100 * (max(g) - min(g)) / g[2],
          100 * (pol.loc[FINE, "Cd_mean"] - pol.loc[MED25, "Cd_mean"]) / pol.loc[FINE, "Cd_mean"]])
    show_bool("  not monotonic", "coarse > medium < fine", g[0] > g[1] < g[2])

    print("== alpha 180, medium mesh")
    f = F[A180_5]
    show("maxCo 5: window jump intervals", "62", len(window_intervals(f["J"])), tol=0)
    show("maxCo 5: window Cd samples", "−131 to 5.6", [f["Cd"][f["w"]].min(), f["Cd"][f["w"]].max()])
    f = F[A180_25]
    show("maxCo 2.5: window jump intervals", "8", len(window_intervals(f["J"])), tol=0)
    tl, dtl, prl = log_steps(A180_25, f["tc"])
    jb, cb = [], []
    for lo in range(50, 150, 10):
        dmin = dtl[blocks(tl, lo, lo + 10)].min()
        (jb if any(lo <= k < lo + 10 for k in window_intervals(f["J"])) else cb).append(dmin)
    show("min dt of window blocks with jumps (c/U)", "4.8e-5 to 3.2e-4", [min(jb), max(jb)])
    show("min dt of window blocks without jumps (c/U)", "4.6e-4 to 6.8e-4", [min(cb), max(cb)])
    yt, yp = yplus(A180_25, f["tc"])
    yw = (yt >= 50) & (yt <= 150 + 1e-6)
    i = int(np.argmax(np.where(yw, yp, -1)))
    yj = in_jumps(yt, f["J"])
    show("window y+ maximum", "4.94", yp[i])
    show_bool("  ... in a jump interval", f"at {yt[i]:.2f} c/U, interval {int(np.floor(yt[i]))}", bool(yj[i]))
    show("window y+ maximum outside jump intervals", "0.95", yp[yw & ~yj].max())
    tri = []
    for lv in ("coarse", "medium", "fine"):
        g_ = forces(f"a180.0_U23.0_SST_{lv}_Tu1.0_Co2.5n2")
        Jg = jump_intervals(g_["t"], g_["Cd"])
        tri.append(g_["Cd"][g_["w"] & ~in_jumps(g_["t"], Jg)].mean())
    show("alpha-180 jump-free values coarse / medium / fine", "1.669 / 1.496 / 1.661", tri)
    show("  medium below coarse, below fine (%)", "10.4 % below the coarse run and 9.9 %",
         [100 * (1 - tri[1] / tri[0]), 100 * (1 - tri[1] / tri[2])])

    print("== scan of the 51 runs")
    rows = []
    for n in pol.index:
        g_ = forces(n)
        w = g_["w"]
        d = np.abs(np.diff(g_["Cd"]))[w[1:] & w[:-1]]
        J = jump_intervals(g_["t"], g_["Cd"])
        rows.append(dict(name=n, alpha=pol.loc[n, "alpha_deg"], flagged=bool(flag[n]), dmax=d.max(),
                         nwin=len(window_intervals(J)), m=g_["Cd"][w].mean(),
                         m_nj=g_["Cd"][w & ~in_jumps(g_["t"], J)].mean(),
                         sel01=d.max() > 0.1, sel23=d.max() > 2.3))
    S = pd.DataFrame(rows).set_index("name")
    Fl, H = S[S.flagged], S[~S.flagged]
    show("flagged runs: count, all with jumps", "23", len(Fl), tol=0)
    show_bool("  every flagged run has a jump", "all 23", bool((Fl.dmax > LIMIT).all()))
    show("  window jump intervals of the flagged runs", "8–97", [Fl.nwin.min(), Fl.nwin.max()], tol=0)
    Hj, Hc = H[H.dmax > LIMIT], H[H.dmax <= LIMIT]
    show("healthy runs with jumps, of 28", "10 of the 28", [len(Hj), len(H)], tol=0)
    expect = {"a000.0_U10.2_LM_medium_Tu1.0", "a000.0_U23.0_LM_medium_Tu0.5", "a000.0_U23.0_LM_medium_Tu1.0",
              "a000.0_U23.0_LM_medium_Tu3.0", "a015.0_U23.0_LM_medium_Tu1.0", "a030.0_U23.0_LM_medium_Tu1.0",
              FINE, "a180.0_U23.0_SST_coarse_Tu1.0", "a180.0_U23.0_SST_fine_Tu1.0_Co2.5n2", A180_25}
    show_bool("  the named runs", "LM a0 x4, LM a15, a30, SST a0 fine, SST a180 coarse/fine/medium",
              set(Hj.index) == expect)
    show("  largest change between samples, jumpy runs", "2.3–11.0", [Hj.dmax.min(), Hj.dmax.max()])
    show("  largest change in the other 18", "0.097", Hc.dmax.max())
    show("  ratio to it", "24–114", [Hj.dmax.min() / Hc.dmax.max(), Hj.dmax.max() / Hc.dmax.max()])
    show_bool("  limits 0.1 and 2.3 select the same runs", "any limit from 0.1 to 2.3",
              bool((H.sel01 == (H.dmax > LIMIT)).all() and (H.sel23 == (H.dmax > LIMIT)).all()))
    chg = 100 * (Hj.m_nj / Hj.m - 1)
    big = ["a015.0_U23.0_LM_medium_Tu1.0", "a030.0_U23.0_LM_medium_Tu1.0"]
    show("  mean change without jumps (%), others", "−1.2 to +2.6", [chg.drop(big).min(), chg.drop(big).max()])
    show("  mean change, LM a30 and LM a15 (%)", "+5.7 % and +17.0 %", [chg[big[1]], chg[big[0]]])
    a0 = H[H.alpha == 0]
    show_bool("  no alpha-0 run changes state", "state by Cd 2.5 with and without jumps",
              bool(((a0.m > 2.5) == (a0.m_nj > 2.5)).all()))

    print("== origin: pressure solves of the fine run")
    f = F[FINE]
    tl, dtl, prl = log_steps(FINE, f["tc"])
    med = {lo: np.median(prl[blocks(tl, lo, lo + 10)]) for lo in range(0, 150, 10)}
    ep = [med[lo] for lo in range(30, 90, 10)]
    out = [med[lo] for lo in (0, 10, 100, 110, 120, 130, 140)]
    show("median first p residual, blocks 30-90 c/U", "0.19–0.38", [min(ep), max(ep)])
    show("  blocks 0-20 and 100-150 c/U", "0.0032–0.0080", [min(out), max(out)])

    print("== machine and hysteresis")
    if a.repeat:
        base = Path(a.repeat)
        R = json.loads((base / "results.json").read_text())
        g_ = forces(None, base=base)
        m, s = g_["Cd"][g_["w"]].mean(), g_["Cd"][g_["w"]].std()
        show("Unity repeat: Cd, Cd_std, mean Cl, Cl_std", "3.189, Cd_std 0.398, mean Cl −0.690 and Cl_std 0.857",
             [m, s, g_["Cl"][g_["w"]].mean(), g_["Cl"][g_["w"]].std()])
        show_bool("  equals its results.json", "Cd_mean, Cd_std",
                  abs(m - R["Cd_mean"]) < 1e-9 and abs(s - R["Cd_std"]) < 1e-9)
        show("  entry into the high-drag state (c/U)", "17.2", stays_from(g_["t"], rmean(g_["Cd"]), lambda r: r > 2.75),
             tol=0.15)
    else:
        print("NOT CHECKED Unity repeat (give --repeat DIR)")
    mac = pol.loc[MED5]
    show("Mac run: Cd, Cd_std, mean Cl, Cl_std", "3.190, 0.399, −0.689 and 0.857",
         [mac.Cd_mean, mac.Cd_std, mac.Cl_mean, mac.Cl_std])
    l10 = lambda n: F[n]["Cl"][F[n]["t"] >= F[n]["t"][-1] - 10].std()  # noqa: E731
    show("(b): Cl_std of its last 10 c/U", "3.3e-4", l10(MED25))
    show("  high-drag level: Cl_std of the maxCo-5 run's last 10", "0.80", l10(MED5))
    gc = [p for p in cycles(F[MED5]["t"], F[MED5]["Cl"], 5, 45) if 9 <= p[0] <= 25]
    efold = 1.0 / np.polyfit([p[0] for p in gc], np.log([p[1] for p in gc]), 1)[0]
    show("  e-folding of the maxCo-5 start-up (c/U)", "21", efold)
    show("  time to the high-drag level (c/U)", "about 165", efold * math.log(l10(MED5) / l10(MED25)), tol=2.5)

    print(f"\n{n_bad} CHECK line(s)")


if __name__ == "__main__":
    main()
