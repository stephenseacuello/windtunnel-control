#!/usr/bin/env python3
"""Force histories of the 125 Stage 1 section runs (15 Oct 2026): jump scan, solver-log residuals,
the time-step runs at maxCo 5 / 2.5 / 1.25, the Unity repeat and the alpha-0 restart test.

    nice -n 10 python3 cfd/analysis/2026-10-15/src/section_histories.py            # about 10 min (49 GB of logs)
    nice -n 10 python3 cfd/analysis/2026-10-15/src/section_histories.py --no-logs  # reuse ../out/section_log_residuals.csv

Adapted from cfd/analysis/2026-10-13/src/section_histories.py (13 Oct addendum). The readers, the
running mean, the jump definition and the window bookkeeping are copied unchanged, so the 51 runs of
13 Oct reproduce ../../2026-10-13/out/section_force_jumps.csv (checked at the end; the script stops
if they do not).

Reads, read only:
  cfd/section2d/runs/<case>/case.json, results.json, postProcessing/forceCoeffs1/<t>/coefficient.dat
    (restarts joined by cfd/post/section_summary.read_table) and log.pimpleFoam, for the 125 cases of
    cfd/section2d/results/section_polars.csv, the Unity repeat _unity_a000.0_U23.0_SST_medium_Tu1.0
    and the restarts _hyst_Co5to2p5_a000 and _hyst_Co2p5to5_a000.
Writes:
  ../out/section_jumps.csv            one row per case: jumps at the limits 0.5, 0.2 and 0.1, the
                                      window mean, drift and share without the jump intervals,
                                      last-50 and last-10 c/U means, residual share (from the log)
  ../out/section_log_residuals.csv    per case: steps parsed and the window share of steps whose
                                      first pressure solve starts above P_RES (cache for --no-logs)
  ../out/section_timestep_blocks.csv  10-c/U blocks of the time-step runs and of the restarts
  ../out/section_histories.json       the numbers quoted from this script
  ../fig/section_timestep_histories.png

Definitions (13 Oct addendum unless marked new):
  t* = t U/c, c = 48 mm; forces sampled every 0.02 c/U; window = avg_from_conv to avg_to_conv
  (50-150 c/U for every case here).
  Jump: |Cd change| > JUMP = 0.5 between consecutive samples; its 1-c/U interval is a jump interval.
  Jump-free statistics (new: drift and share): window samples outside the jump intervals; the
  jump-free drift is their mean over the second half of the window minus the first half.
  Residual share (new): share of the window's time steps whose first pressure solve (first PIMPLE
  iteration) starts with an initial residual above P_RES = 0.05 (the 13 Oct addendum's level).
  Running mean: centred, 8 c/U. Cycle amplitude (new use): peak-to-peak Cl of each cycle of a 1-c/U
  running mean (cl_peaks); growth or decay e-folding times are least-squares fits of log(amplitude).
"""
import argparse
import json
import mmap
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import section_lib as L  # noqa: E402

sys.path.insert(0, str(L.REPO / "cfd" / "post"))
import section_summary as S  # noqa: E402  restart-joining reader of postProcessing tables

RUNS, FIG, OUT = L.RUNS, L.FIG, L.OUT
DT_S = 0.02
RM_WIDTH = 8.0
STATE_CD = L.STATE_CD
ENTER_HI, ENTER_LO = 2.75, 2.25
SETTLE = 0.05
JUMP = 0.5
JUMP_ALT = (0.1, 0.2)
T_START = 2.0
P_RES = 0.05
BLOCK = 10.0

# the time-step runs (alpha 0 and 180, medium mesh, 23 m/s, Tu 1 %); restart continuations appended
TS_RUNS = [
    ("a000.0_U23.0_SST_medium_Tu1.0", "α 0, SST, maxCo 5 (Mac); then restart (a) at maxCo 2.5", L.RESTART_A),
    ("a000.0_U23.0_SST_medium_Tu1.0_Co2.5n2", "α 0, SST, maxCo 2.5; then restart (b) at maxCo 5", L.RESTART_B),
    ("a000.0_U23.0_SST_medium_Tu1.0_Co1.25n2", "α 0, SST, maxCo 1.25", None),
    ("a000.0_U23.0_LM_medium_Tu1.0", "α 0, LM, maxCo 5", None),
    ("a000.0_U23.0_LM_medium_Tu1.0_Co1.25n2", "α 0, LM, maxCo 1.25", None),
    ("a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2", "α 180, SST, maxCo 2.5", None),
    ("a180.0_U23.0_SST_medium_Tu1.0_Co1.25n2", "α 180, SST, maxCo 1.25", None),
    ("a180.0_U23.0_LM_medium_Tu1.0_Co2.5n2", "α 180, LM, maxCo 2.5", None),
    ("a180.0_U23.0_LM_medium_Tu1.0_Co1.25n2", "α 180, LM, maxCo 1.25", None),
]

# panel notes (the numbers come from the run's own statistics)
NOTES = {
    "a000.0_U23.0_SST_medium_Tu1.0": lambda q: (f"high-drag; window {q['Cd_win']:.3f}; restart keeps shedding, "
                                                 f"Cd {q['restart']['parts']['30-60']['Cd']:.3f} at 180–210 c/U"),
    "a000.0_U23.0_SST_medium_Tu1.0_Co2.5n2": lambda q: (f"low-drag; window {q['Cd_win']:.3f}; restart: lift "
                                                         f"oscillation grows (×{q['restart']['cl_cycles'][-1][1] / q['restart']['cl_cycles'][0][1]:.0f})"),
    "a000.0_U23.0_SST_medium_Tu1.0_Co1.25n2": lambda q: (f"shedding, running-mean Cd > 2.5 to {q['t_last_cross_2p5']:.0f} c/U,"
                                                          f" then decays; window {q['Cd_win']:.3f}"),
    "a000.0_U23.0_LM_medium_Tu1.0": lambda q: f"low-drag; jumps in {q['jumps_win']} window c/U; window {q['Cd_win']:.3f}",
    "a000.0_U23.0_LM_medium_Tu1.0_Co1.25n2": lambda q: (f"shedding decays, below 2.5 from {q['t_last_cross_2p5']:.0f} c/U;"
                                                         f" window {q['Cd_win']:.3f}"),
    "a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2": lambda q: f"shedding; jumps in {q['jumps_win']} window c/U; window {q['Cd_win']:.3f}",
    # review 19 Oct: "steady from ~15 c/U" was wrong; the lift oscillation decays slowly after the start-up
    # jumps (10-c/U lift std 0.029 at 20-30 c/U) and falls below 0.001 only from t_quiet on
    "a180.0_U23.0_SST_medium_Tu1.0_Co1.25n2": lambda q: (f"oscillation decays; lift std < 0.001 from {q['t_quiet']:.0f} c/U;"
                                                          f" window {q['Cd_win']:.3f}"),
    "a180.0_U23.0_LM_medium_Tu1.0_Co2.5n2": lambda q: f"weak oscillation with spikes; window {q['Cd_win']:.3f}",
    "a180.0_U23.0_LM_medium_Tu1.0_Co1.25n2": lambda q: (f"oscillation decays, slow decline; lift std < 0.001 from "
                                                         f"{q['t_quiet']:.0f} c/U; window {q['Cd_win']:.3f}"),
}

STEP = re.compile(rb"^deltaT = (\S+)\nTime = (\S+)\n\nPIMPLE: iteration 1\n(?:(?!GAMG)[^\n]*\n){0,8}"
                  rb"GAMG:  Solving for p, Initial residual = ([^,]+),", re.M)


# ------------------------------------------------------------------ reading (13 Oct, unchanged)
def case_info(name):
    d = RUNS / name
    P = json.loads((d / "case.json").read_text())
    R = json.loads((d / "results.json").read_text()) if (d / "results.json").exists() else {}
    return d, P, R


def forces(name):
    d, P, _ = case_info(name)
    names, a = S.read_table(d / "postProcessing" / "forceCoeffs1", "coefficient.dat")
    col = {n: i for i, n in enumerate(names)}
    ts, tc = a[:, 0], P["convTime"]
    w = ts >= max(ts[0], ts[-1] - P["nAvg"] * tc)
    return ts / tc, a[:, col["Cd"]], a[:, col["Cl"]], w


def log_steps(name, strict=True):
    """(t c/U, dt U/c, first-p initial residual) per time step, from log.pimpleFoam."""
    d, P, _ = case_info(name)
    with open(d / "log.pimpleFoam", "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        n_time = len(re.findall(rb"^Time = ", mm, re.M))
        a = np.array([(float(m.group(2)), float(m.group(1)), float(m.group(3))) for m in STEP.finditer(mm)])
    if strict and len(a) != n_time:
        raise RuntimeError(f"{name}: parsed {len(a)} of {n_time} time steps in log.pimpleFoam")
    tc = P["convTime"]
    return a[:, 0] / tc, a[:, 1] / tc, a[:, 2], n_time


def running_mean(t, y, width=RM_WIDTH):
    tu = np.arange(np.ceil(t[0] / DT_S) * DT_S, t[-1] + 1e-9, DT_S)
    yu = np.interp(tu, t, y)
    n = int(round(width / DT_S))
    c = np.concatenate([[0.0], np.cumsum(yu)])
    m = (c[n:] - c[:-n]) / n
    tm = tu[: len(m)] + (n - 1) * DT_S / 2
    return tm, m


def stays_from(tm, ok):
    if not ok[-1]:
        return float("nan")
    bad = np.where(~ok)[0]
    return float(tm[0] if bad.size == 0 else tm[bad[-1] + 1])


def jump_bins(t, Cd, limit=JUMP):
    d = np.abs(np.diff(Cd))
    m = (d > limit) & (t[1:] >= T_START)
    return sorted(set(np.floor(t[1:][m]).astype(int).tolist()))


def window(R):
    return float(R["avg_from_conv"]), float(R["avg_to_conv"])


def in_window(bins, w0, w1):
    k0, k1 = int(round(w0)), int(round(w1))
    return sorted({k1 - 1 if k == k1 else k for k in bins if k0 <= k <= k1})


def cl_peaks(t, Cl, t0, t1):
    """Peak-to-peak amplitudes (time of the maximum, max - next min) of Cl in [t0, t1]."""
    tm, s = running_mean(t, Cl, 1.0)
    i_max = np.where((s[1:-1] > s[:-2]) & (s[1:-1] >= s[2:]))[0] + 1
    i_min = np.where((s[1:-1] < s[:-2]) & (s[1:-1] <= s[2:]))[0] + 1
    out = []
    for i in i_max:
        if t0 <= tm[i] <= t1:
            nxt = i_min[i_min > i]
            if nxt.size:
                out.append((float(tm[i]), float(s[i] - s[nxt[0]])))
    return out


def clean_cycles(cycles, min_p2p=0.003, min_gap=4.0):
    """Cycles of at least min_p2p, each at least min_gap c/U after the previous one kept (drops the
    sub-threshold wiggles of a 1-c/U running mean of an almost steady signal)."""
    kept = []
    for c in cycles:
        if c[1] < min_p2p or (kept and c[0] - kept[-1][0] < min_gap):
            continue
        kept.append(c)
    return kept


def efold(points):
    """e-folding time (c/U) of a least-squares line through log(amplitude); > 0 growth, < 0 decay."""
    p = np.array(points, float)
    k = np.polyfit(p[:, 0], np.log(p[:, 1]), 1)[0]
    return float(1.0 / k)


# ------------------------------------------------------------------ scan of all cases
def jump_free(t, Cd, Cl, w, w0, w1, jb):
    keep = w & ~np.isin(np.floor(t).astype(int), jb)
    mid = 0.5 * (w0 + w1)
    h1, h2 = keep & (t < mid), keep & (t >= mid)
    out = dict(nojump_share=float(keep.sum() / w.sum()))
    out["Cd_nj"] = float(Cd[keep].mean()) if keep.any() else float("nan")
    out["Cl_nj"] = float(Cl[keep].mean()) if keep.any() else float("nan")
    out["Cd_std_nj"] = float(Cd[keep].std()) if keep.any() else float("nan")
    out["Cd_drift_nj"] = float(Cd[h2].mean() - Cd[h1].mean()) if (h1.any() and h2.any()) else float("nan")
    out["Cl_drift_nj"] = float(Cl[h2].mean() - Cl[h1].mean()) if (h1.any() and h2.any()) else float("nan")
    return out


def scan_case(name):
    d, P, R = case_info(name)
    t, Cd, Cl, w = forces(name)
    w0, w1 = window(R)
    dd = np.abs(np.diff(Cd))[w[1:] & w[:-1]]
    row = dict(name=name, alpha=float(P["alphaDeg"]), U=float(P["Uinf"]), model=P["model"], level=P["level"],
               maxCo=float(P["maxCo"]), Tu=float(P["TuBodyPercent"]), win_from=w0, win_to=w1,
               Cd_win=float(Cd[w].mean()), Cl_win=float(Cl[w].mean()), jump_max_win=float(dd.max()))
    for lim in (JUMP,) + JUMP_ALT:
        jb = jump_bins(t, Cd, lim)
        keep = w & ~np.isin(np.floor(t).astype(int), jb)
        row[f"jump_bins_win_{lim:g}"] = len(in_window(jb, w0, w1))
        row[f"Cd_win_nojump_{lim:g}"] = float(Cd[keep].mean()) if keep.any() else float("nan")
    jb = jump_bins(t, Cd, JUMP)
    row.update(jump_free(t, Cd, Cl, w, w0, w1, jb))
    row["jump_first"] = float(jb[0]) if jb else float("nan")
    row["jump_last"] = float(jb[-1] + 1) if jb else float("nan")
    for lab, span in (("last50", 50.0), ("last10", 10.0)):
        m = t >= t[-1] - span - 1e-9
        row[f"Cd_{lab}"] = float(Cd[m].mean())
        row[f"Cl_{lab}"] = float(Cl[m].mean())
        row[f"Cl_std_{lab}"] = float(Cl[m].std())
    return row, (t, Cd, Cl, w, jb)


def log_residuals(name, w0, w1):
    """Window share of steps whose first pressure solve starts above P_RES; dt statistics."""
    try:
        ts, dt, pr, n_time = log_steps(name, strict=False)
    except (FileNotFoundError, ValueError, IndexError) as e:
        return dict(name=name, log_steps=0, log_t_from=np.nan, log_t_to=np.nan, log_note=f"unreadable: {e}")
    m = (ts >= w0) & (ts <= w1 + 1e-9)
    out = dict(name=name, log_steps=int(len(ts)), log_time_lines=int(n_time),
               log_t_from=float(ts[0]) if len(ts) else np.nan, log_t_to=float(ts[-1]) if len(ts) else np.nan,
               win_steps_in_log=int(m.sum()),
               pres_share_win=float(np.mean(pr[m] > P_RES)) if m.any() else np.nan,
               pres_median_win=float(np.median(pr[m])) if m.any() else np.nan,
               dt_min_win=float(dt[m].min()) if m.any() else np.nan,
               dt_mean_win=float(dt[m].mean()) if m.any() else np.nan,
               log_note="" if len(ts) == n_time else f"parsed {len(ts)} of {n_time} steps")
    return out


# ------------------------------------------------------------------ time-step runs and restarts
def series(name):
    t, Cd, Cl, _ = forces(name)
    return t, Cd, Cl


def blocks(name, t, Cd, Cl, t0, t1, steps=None, tag=""):
    rows = []
    edges = np.arange(t0, t1 + 1e-9, BLOCK)
    for lo, hi in zip(edges[:-1], edges[1:]):
        last = hi >= t1 - 1e-9
        m = (t >= lo) & (t < hi + (1e-6 if last else 0))
        if not m.any():
            continue
        b = dict(name=name, part=tag, t_from=lo, t_to=hi, Cd_mean=Cd[m].mean(), Cd_std=Cd[m].std(),
                 Cl_mean=Cl[m].mean(), Cl_std=Cl[m].std(), Cl_min=Cl[m].min(), Cl_max=Cl[m].max(),
                 dCd_max=float(np.abs(np.diff(Cd[m])).max()) if m.sum() > 1 else np.nan)
        if steps is not None:
            st, sdt, spr = steps
            ms = (st >= lo) & (st < hi + (1e-6 if last else 0))
            if ms.any():
                b.update(n_steps=int(ms.sum()), dt_mean=sdt[ms].mean(), dt_min=sdt[ms].min(),
                         pres_median=float(np.median(spr[ms])), pres_share=float(np.mean(spr[ms] > P_RES)))
        rows.append(b)
    return rows


def state_times(t, Cd):
    """13 Oct alpha-0 state bookkeeping on the 8-c/U running mean, plus the last crossing of Cd 2.5."""
    tm, rm = running_mean(t, Cd)
    last50 = Cd[t >= t[-1] - 50 - 1e-9].mean()
    hi = last50 > STATE_CD
    side = rm > STATE_CD
    cross = np.where(side[1:] != side[:-1])[0]
    return dict(state_last50="high-drag" if hi else "low-drag", Cd_last50=float(last50),
                t_enter=stays_from(tm, rm > ENTER_HI if hi else rm < ENTER_LO),
                t_settle5=stays_from(tm, np.abs(rm / last50 - 1) <= SETTLE),
                t_last_cross_2p5=float(tm[cross[-1] + 1]) if cross.size else float("nan"),
                rm_min_win=float(rm[(tm >= 50) & (tm <= 150)].min()),
                rm_max_win=float(rm[(tm >= 50) & (tm <= 150)].max()))


def trajectory_difference(tM, CdM, ClM, tU, CdU, ClU):
    """Sample-by-sample difference of two runs of the same case (Unity series interpolated to the Mac
    sample times), from 2 c/U (after the impulsive start) to the end."""
    m = (tM >= T_START) & (tM <= tU[-1])
    dcd = np.abs(np.interp(tM[m], tU, CdU) - CdM[m])
    dcl = np.abs(np.interp(tM[m], tU, ClU) - ClM[m])
    first = {}
    for thr in (0.01, 0.03, 0.1):
        k = np.flatnonzero(dcd > thr)
        first[f"first_t_abs_dCd_gt_{thr:g}"] = float(tM[m][k[0]]) if k.size else None
    return dict(max_abs_dCd_2_150=float(dcd.max()), t_max_abs_dCd=float(tM[m][np.argmax(dcd)]),
                max_abs_dCl_2_150=float(dcl.max()), **first)


def figure(rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    L.style()
    SAMPLE = "#9a9a9a"
    n = len(rows)
    H_ = 0.9 * n + 0.75
    fig = plt.figure(figsize=(3.4, H_))
    gs = fig.add_gridspec(n, 2, hspace=1.25, wspace=0.42, left=0.115, right=0.985,
                          top=1 - 0.72 / H_, bottom=0.36 / H_)
    for i, r in enumerate(rows):
        a0 = r["alpha"] == 0
        for j, key in enumerate(("Cd", "Cl")):
            ax = fig.add_subplot(gs[i, j])
            ax.axvspan(50, 150, color=L.WINC, zorder=0, lw=0)
            for k in r["jb"]:
                ax.axvspan(k, k + 1, color=L.JUMPC, zorder=0.5, lw=0)
            y = r[key]
            ax.plot(r["t"], y, color=SAMPLE, lw=0.3, zorder=2)
            if r["restart"] is not None:
                ax.plot(r["rt"], r["r" + key], color=SAMPLE, lw=0.3, zorder=2)
                ax.axvline(150, color=L.BLACK, lw=0.6, ls="--", zorder=3)
            if key == "Cd":
                ax.plot(r["tm"], r["rm"], color=L.BLACK, lw=0.9, zorder=3)
                if r["restart"] is not None:
                    ax.plot(r["rtm"], r["rrm"], color=L.BLACK, lw=0.9, zorder=3)
                if a0:
                    ax.axhline(STATE_CD, color=L.BLACK, ls=(0, (1, 1.5)), lw=0.6, zorder=1)
            if a0:
                ylim = (1.2, 4.3) if key == "Cd" else (-2.3, 2.3)
            else:
                ylim = (0.6, 2.4) if key == "Cd" else (-2.3, 0.3)
            ax.set_ylim(*ylim)
            ax.set_xlim(0, 210)
            ax.set_xticks([0, 50, 100, 150, 200])
            ax.tick_params(labelsize=6, pad=1.5)
            ax.set_ylabel("$C_d$" if key == "Cd" else "$C_l$", fontsize=7, labelpad=1)
            if i < n - 1:
                ax.set_xticklabels([])
            else:
                ax.set_xlabel("t U/c", fontsize=7, labelpad=1)
            lo_, hi_ = np.nanmin(y[r["t"] > 2]), np.nanmax(y[r["t"] > 2])
            if lo_ < ylim[0] or hi_ > ylim[1]:
                ax.text(0.99, 0.04, f"{lo_:.3g} to {hi_:.3g}", transform=ax.transAxes, ha="right", va="bottom",
                        fontsize=5, color="#7a1f1f", zorder=6,
                        bbox=dict(boxstyle="square,pad=0.1", fc="white", ec="none", alpha=0.85))
            if j == 0:
                ax.text(-0.2, 1.33, r["label"], transform=ax.transAxes, ha="left", va="bottom", fontsize=6.3)
                ax.text(-0.2, 1.06, r["note"], transform=ax.transAxes, ha="left", va="bottom", fontsize=5.4,
                        color=L.NOTE)
    handles = [Line2D([], [], color=SAMPLE, lw=0.8, label="samples"),
               Line2D([], [], color=L.BLACK, lw=0.9, label="running mean, 8 c/U"),
               Line2D([], [], color=L.BLACK, lw=0.6, ls="--", label="restart at 150 c/U"),
               Patch(color=L.WINC, label="window 50–150 c/U"),
               Patch(color=L.JUMPC, label="Cd jump > 0.5 (1 c/U)"),
               Line2D([], [], color=L.BLACK, lw=0.6, ls=(0, (1, 1.5)), label="Cd 2.5 (α-0 states)")]
    fig.legend(handles=handles, loc="upper center", ncol=3, fontsize=5.6, bbox_to_anchor=(0.53, 1.0),
               handlelength=1.8, columnspacing=0.9)
    return L.save(fig, "section_timestep_histories.png")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-logs", action="store_true", help="reuse ../out/section_log_residuals.csv")
    a = ap.parse_args()
    d = L.load()
    OUT.mkdir(exist_ok=True)

    # ---------------------------------------------------------------- 1. scan of every case
    rows, ser = [], {}
    for name in d["name"]:
        r, s = scan_case(name)
        rows.append(r)
        ser[name] = s
    J = pd.DataFrame(rows)
    # the 51 cases of 13 Oct must reproduce its jump scan
    old = pd.read_csv(L.OUT_13OCT / "section_force_jumps.csv").set_index("name")
    chk = J.set_index("name").loc[old.index]
    cols = ["Cd_win", "jump_max_win"] + [f"jump_bins_win_{x:g}" for x in (0.5, 0.1, 0.2)] + \
           [f"Cd_win_nojump_{x:g}" for x in (0.5, 0.1, 0.2)]
    # the 13 Oct file holds 6 significant digits (float_format %.6g): compare relative to that
    dev = max(float(np.nanmax(np.abs(chk[c].to_numpy(float) - old[c].to_numpy(float)) /
                              np.maximum(np.abs(old[c].to_numpy(float)), 1e-12))) for c in cols)
    if dev > 5.001e-6:
        raise SystemExit(f"the 13 Oct jump scan is not reproduced (max relative deviation {dev})")
    print(f"13 Oct jump scan reproduced for {len(old)} cases (max relative deviation {dev:.2e}, "
          f"the rounding of its 6 significant digits)")

    # ---------------------------------------------------------------- 2. solver logs
    cache = OUT / "section_log_residuals.csv"
    if a.no_logs:
        LG = pd.read_csv(cache)
    else:
        lrows = []
        for r in J.itertuples():
            lrows.append(log_residuals(r.name, r.win_from, r.win_to))
            print(f"log {len(lrows):3d}/{len(J)} {r.name}: share {lrows[-1].get('pres_share_win', np.nan):.3f}",
                  flush=True)
        LG = pd.DataFrame(lrows)
        LG.to_csv(cache, index=False, float_format="%.6g")
    J = J.merge(LG, on="name", how="left")
    meta = d.set_index("name")[["new_15oct", "corrupted", "any_symptom", "symptom_without_flag", "u_co_over_U",
                                "ran_on"]]
    J = J.merge(meta, left_on="name", right_index=True)
    J.to_csv(OUT / "section_jumps.csv", index=False, float_format="%.6g")

    # ---------------------------------------------------------------- 3. time-step runs and restarts
    Q = {}
    brows, frows = [], []
    for name, label, rst in TS_RUNS:
        t, Cd, Cl = series(name)
        w, jb = ser[name][3], ser[name][4]
        steps = log_steps(name)[:3]
        brows += blocks(name, t, Cd, Cl, 0.0, 150.0, steps, "run")
        tm, rm = running_mean(t, Cd)
        r = dict(name=name, label=label, alpha=float(case_info(name)[1]["alphaDeg"]), t=t, Cd=Cd, Cl=Cl, tm=tm,
                 rm=rm, jb=jb, restart=rst)
        jr = J.set_index("name").loc[name]
        q = dict(Cd_win=float(jr.Cd_win), Cd_last10=float(jr.Cd_last10), Cl_last10=float(jr.Cl_last10),
                 Cl_std_last10=float(jr.Cl_std_last10), jumps_win=int(jr["jump_bins_win_0.5"]),
                 jump_first=float(jr.jump_first), jump_last=float(jr.jump_last),
                 pres_share_win=float(jr.pres_share_win), pres_median_win=float(jr.pres_median_win))
        if r["alpha"] == 0:
            q.update(state_times(t, Cd))
        q["cl_cycles"] = cl_peaks(t, Cl, 5.0, 149.0)
        # review 19 Oct: start of the first 10-c/U block from which every block to 150 c/U has a lift
        # std below 0.001 (the 'steady' level of section_timestep.png); nan if the run never gets there
        qb = [(lo, float(Cl[(t >= lo) & (t < lo + BLOCK + (1e-6 if lo + BLOCK >= 150.0 else 0))].std()))
              for lo in np.arange(0.0, 150.0, BLOCK)]
        quiet = [lo for k, (lo, _) in enumerate(qb) if all(sd < 1e-3 for _, sd in qb[k:])]
        q["t_quiet"] = float(quiet[0]) if quiet else float("nan")
        if rst is not None:
            rt, rCd, rCl = series(rst)
            rsteps = log_steps(rst)[:3]
            brows += blocks(rst, rt, rCd, rCl, 150.0, 210.0, rsteps, "restart")
            rtm, rrm = running_mean(rt, rCd)
            r.update(rt=rt, rCd=rCd, rCl=rCl, rtm=rtm, rrm=rrm)
            parts = {}
            for lo, hi in ((0, 10), (10, 30), (30, 60)):
                m = (rt >= 150 + lo) & (rt < 150 + hi + (1e-6 if hi == 60 else 0))
                parts[f"{lo}-{hi}"] = dict(Cd=float(rCd[m].mean()), Cl=float(rCl[m].mean()), Cl_std=float(rCl[m].std()))
            cyc = clean_cycles(cl_peaks(rt, rCl, 151.0, 209.5))
            q["restart"] = dict(name=rst, maxCo=float(case_info(rst)[1]["maxCo"]), parts=parts, cl_cycles=cyc,
                                cl_cycle_efold=efold(cyc) if len(cyc) >= 3 else float("nan"),
                                Cd_first10_last10=[float(rCd[rt < 160].mean()), float(rCd[rt >= 200].mean())],
                                Cl_std_first10_last10=[float(rCl[rt < 160].std()), float(rCl[rt >= 200].std())],
                                pres_share=float(np.mean(rsteps[2] > P_RES)), steps=int(len(rsteps[0])),
                                parent_last10=dict(Cd=float(Cd[t >= 140].mean()), Cl=float(Cl[t >= 140].mean()),
                                                   Cl_std=float(Cl[t >= 140].std())),
                                parent_last50=dict(Cd=float(Cd[t >= 100].mean()), Cl=float(Cl[t >= 100].mean()),
                                                   Cl_std=float(Cl[t >= 100].std())))
            q["restart"]["dCd_30_60_vs_parent_last50_pct"] = L.pct(parts["30-60"]["Cd"], q["restart"]["parent_last50"]["Cd"])
        r["note"] = NOTES[name](q)
        frows.append(r)
        Q[name] = q

    # growth and decay of the lift oscillation
    rb = Q["a000.0_U23.0_SST_medium_Tu1.0_Co2.5n2"]["restart"]
    hi_ref = Q["a000.0_U23.0_SST_medium_Tu1.0"]
    hi_p2p = float(np.median([c[1] for c in hi_ref["cl_cycles"] if c[0] >= 50]))
    last_b = rb["cl_cycles"][-1]
    Q["restart_b_growth"] = dict(
        efold_conv=rb["cl_cycle_efold"], cycles=rb["cl_cycles"], high_drag_cycle_p2p_median=hi_p2p,
        conv_to_reach_high_drag_p2p=float(rb["cl_cycle_efold"] * np.log(hi_p2p / last_b[1])),
        note="estimate: constant exponential growth from the last cycle of the restart to the median "
             "peak-to-peak Cl of the maxCo-5 run's window cycles")
    s125 = Q["a000.0_U23.0_SST_medium_Tu1.0_Co1.25n2"]["cl_cycles"]
    dec = [c for c in s125 if c[0] >= 95]
    l125 = Q["a000.0_U23.0_LM_medium_Tu1.0_Co1.25n2"]["cl_cycles"]
    decl = [c for c in l125 if 20 <= c[0] <= 100]
    Q["decay_co125"] = dict(
        SST=dict(efold_conv=efold(dec), cycles_used=dec,
                 p2p_before90=[float(min(c[1] for c in s125 if 10 <= c[0] < 85)),
                               float(max(c[1] for c in s125 if 10 <= c[0] < 85))]),
        LM=dict(efold_conv=efold(decl), cycles_used=decl))
    ra = Q["a000.0_U23.0_SST_medium_Tu1.0"]["restart"]
    Q["restart_a_cycles"] = dict(p2p=[float(min(c[1] for c in ra["cl_cycles"])), float(max(c[1] for c in ra["cl_cycles"]))],
                                 n=len(ra["cl_cycles"]), efold_conv=ra["cl_cycle_efold"])
    # Unity repeat against the Mac run
    rep = json.loads((RUNS / L.UNITY_REPEAT / "results.json").read_text())
    mac = d.set_index("name").loc["a000.0_U23.0_SST_medium_Tu1.0"]
    tU, CdU, ClU, wU = forces(L.UNITY_REPEAT)
    tM, CdM, ClM = frows[0]["t"], frows[0]["Cd"], frows[0]["Cl"]
    Q["unity_repeat"] = dict(
        unity=dict(Cd=rep["Cd_mean"], Cd_std=rep["Cd_std"], Cl=rep["Cl_mean"], Cl_std=rep["Cl_std"], St=rep["St"],
                   Cm=rep["Cm_mean"], ranks=int(case_info(L.UNITY_REPEAT)[1]["nProcs"]),
                   state=state_times(tU, CdU)),
        mac=dict(Cd=float(mac.Cd_mean), Cd_std=float(mac.Cd_std), Cl=float(mac.Cl_mean), Cl_std=float(mac.Cl_std),
                 St=float(mac.St), Cm=float(mac.Cm_mean), ranks=int(case_info("a000.0_U23.0_SST_medium_Tu1.0")[1]["nProcs"])),
        dCd_pct=L.pct(rep["Cd_mean"], float(mac.Cd_mean)), dCl_pct=L.pct(rep["Cl_mean"], float(mac.Cl_mean)),
        dSt_pct=L.pct(rep["St"], float(mac.St)),
        **trajectory_difference(tM, CdM, ClM, tU, CdU, ClU))

    B = pd.DataFrame(brows)
    B.to_csv(OUT / "section_timestep_blocks.csv", index=False, float_format="%.6g")
    # scan summary
    new = J[J.new_15oct]
    H = J[~J.corrupted]
    Q["scan"] = dict(
        n_cases=int(len(J)), n_new=int(len(new)), n_flagged_new=int(new.corrupted.sum()),
        new_with_jumps=int((new["jump_bins_win_0.5"] > 0).sum()),
        new_with_jumps_by_limit={f"{x:g}": int((new[f"jump_bins_win_{x:g}"] > 0).sum()) for x in (0.5, 0.2, 0.1)},
        healthy_with_jumps=int((H["jump_bins_win_0.5"] > 0).sum()), n_healthy=int(len(H)),
        pres_share_healthy_nojump_max=float(H[H.jump_max_win <= 0.1].pres_share_win.max()),
    )
    (OUT / "section_histories.json").write_text(json.dumps(Q, indent=1, default=float))
    print(figure(frows))


if __name__ == "__main__":
    main()
