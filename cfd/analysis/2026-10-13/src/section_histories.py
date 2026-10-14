#!/usr/bin/env python3
"""Force histories of eight Stage 1 section runs, and a force-jump scan of all 51 (addendum of 13 Oct 2026).

    nice -n 10 python3 cfd/analysis/2026-10-13/src/section_histories.py           # about 25 s
    nice -n 10 python3 cfd/analysis/2026-10-13/src/section_histories.py --no-logs # skip the solver logs

Reads, read only, the downloaded case folders cfd/section2d/runs/<case>/ (RESULTS.md, addendum):
  case.json, results.json;
  postProcessing/forceCoeffs1/<t>/coefficient.dat, joined over restarts by
    cfd/post/section_summary.read_table (the eight plotted runs have one session each);
  postProcessing/yPlus1/<t>/yPlus.dat (maximum y+ on the blade, once per c/U);
  log.pimpleFoam of the eight plotted runs: deltaT and the initial residual of the first pressure
    solve of every time step (skipped with --no-logs);
  ../data/section_polars.csv (machine) and ../out/section_case_quality.csv (the 23 flagged runs).
Writes:
  ../fig/section_alpha0_histories.png   Cd(t), Cl(t) of the eight runs
  ../out/section_histories_runs.csv     one row per plotted run: states, entry and settling times,
                                        window statistics, force jumps
  ../out/section_histories_blocks.csv   one row per plotted run and 10-c/U block (forces, dt, y+,
                                        pressure residual)
  ../out/section_force_jumps.csv        all 51 runs: largest sample-to-sample Cd change in the
                                        averaging window, 1-c/U intervals with a jump, window mean
                                        without them
  ../out/section_histories.json         every number quoted in the RESULTS.md addendum

Definitions (RESULTS.md, addendum):
  t* = t U/c, c = 48 mm. Forces are sampled every c/U/50; the averaging window is that of
    results.json (avg_from_conv to avg_to_conv: 50-150 c/U for all these runs).
  Running mean: centred, over RM_WIDTH = 8 c/U (about one shedding period at alpha 0, St 0.12-0.13),
    on the samples interpolated to a uniform 0.02-c/U grid; defined from 4 to 146 c/U.
  alpha-0 state: high-drag if the mean Cd over the last 50 c/U exceeds 2.5 (the boundary of
    section_lib.flag_cases), else low-drag. Entry time: the earliest time after which the running
    mean stays above 2.75 (high-drag) or below 2.25 (low-drag) to 146 c/U. Settling time: the earliest
    time after which the running mean stays within +-5 % of the mean of the last 50 c/U.
  Force jump: a change of Cd by more than JUMP = 0.5 between consecutive samples. The 1-c/U interval
    [k, k+1) that holds the later sample is a jump interval. Over the averaging window, the largest
    change is at most 0.097 in 18 of the 28 healthy runs and 2.3-11.0 in the other 10, so any limit
    from 0.1 to 2.3 marks the same runs (checked here for 0.1, 0.2 and 0.5); the number of intervals
    does depend on the limit (section_force_jumps.csv lists all three). The window holds the 100
    intervals [50, 51) to [149, 150]; a jump at its last sample (150 + 2e-8 c/U) counts in the last.
  Decay of the low-drag runs: log-linear least-squares fits over the 10-c/U blocks inside 50-150 c/U
    of Cl_std (e-folding time of the lift fluctuation) and of Cd minus the mean of the last block
    (blocks 50-140 c/U).
  Jump-free statistics: the window samples outside the jump intervals (Cd mean and std, Cl mean); the
    running mean of the jump-free samples is defined where at least half of its 8 c/U are jump-free.
  Fine run during its jumps (28-96 c/U, where almost every 1-c/U interval has a jump): the 10-c/U
    means of Cl (all samples) of the blocks 30-90 c/U, against the window blocks of the medium and
    coarse maxCo-5 runs (high-drag).
  y+: the blade maximum of yPlus1 (one sample per c/U) in the window, with and without the samples
    that fall in a jump interval.
  Start-up lift: peak-to-peak Cl of each cycle (a maximum minus the next minimum of a 1-c/U running
    mean) between 5 and 45 c/U.
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
ROOT = HERE.parent                                   # cfd/analysis/2026-10-13
REPO = ROOT.parents[2]
RUNS = REPO / "cfd" / "section2d" / "runs"
sys.path.insert(0, str(REPO / "cfd" / "post"))
import section_summary as S  # noqa: E402  restart-joining reader of postProcessing tables

sys.path.insert(0, str(HERE))
import section_lib as L  # noqa: E402  figure style, colours

FIG, OUT, DATA = ROOT / "fig", ROOT / "out", ROOT / "data"
DT_S = 0.02                       # c/U, sample interval of forceCoeffs1 (sampleInterval = c/U / 50)
RM_WIDTH = 8.0                    # c/U, running-mean width
STATE_CD = 2.5                    # alpha-0 state boundary (section_lib.flag_cases)
ENTER_HI, ENTER_LO = 2.75, 2.25   # entry: running mean stays beyond these
SETTLE = 0.05                     # settling band, +- fraction of the last-50-c/U mean
JUMP = 0.5                        # Cd change between consecutive samples that marks a jump
JUMP_ALT = (0.1, 0.2)             # other limits, for the sensitivity columns
T_START = 2.0                     # c/U; jumps are counted from here (the impulsive start changes Cd
                                  # by up to 0.59 between the first samples)
P_RES = 0.05                      # first pressure-solve initial residual counted as high
BLOCK = 10.0                      # c/U, block length of the block table

# the eight plotted runs: (case, short label); order = figure rows
RUNS8 = [
    ("a000.0_U23.0_SST_medium_Tu1.0", "α 0, SST, medium, maxCo 5"),
    ("a000.0_U23.0_SST_medium_Tu1.0_Co2.5n2", "α 0, SST, medium, maxCo 2.5"),
    ("a000.0_U23.0_SST_coarse_Tu1.0", "α 0, SST, coarse, maxCo 5"),
    ("a000.0_U23.0_SST_coarse_Tu1.0_Co2.5n2", "α 0, SST, coarse, maxCo 2.5"),
    ("a000.0_U23.0_SST_fine_Tu1.0_Co2.5n2", "α 0, SST, fine, maxCo 2.5"),
    ("a000.0_U10.2_LM_medium_Tu1.0", "α 0, LM, medium, maxCo 5, 10.2 m/s"),
    ("a180.0_U23.0_SST_medium_Tu1.0", "α 180, SST, medium, maxCo 5 (flagged)"),
    ("a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2", "α 180, SST, medium, maxCo 2.5"),
]

# one time step in log.pimpleFoam: deltaT, Time, then (first PIMPLE iteration) U lines and the
# first pressure solve
STEP = re.compile(rb"^deltaT = (\S+)\nTime = (\S+)\n\nPIMPLE: iteration 1\n(?:(?!GAMG)[^\n]*\n){0,8}"
                  rb"GAMG:  Solving for p, Initial residual = ([^,]+),", re.M)


# ------------------------------------------------------------------ reading
def case_info(name):
    d = RUNS / name
    P = json.loads((d / "case.json").read_text())
    R = json.loads((d / "results.json").read_text())
    return d, P, R


def forces(name):
    """t (c/U), Cd, Cl of one case, restarts joined (section_summary.read_table), and the mask of
    the averaging window, taken exactly as section_summary.summarize takes it (in seconds)."""
    d, P, _ = case_info(name)
    names, a = S.read_table(d / "postProcessing" / "forceCoeffs1", "coefficient.dat")
    col = {n: i for i, n in enumerate(names)}
    ts, tc = a[:, 0], P["convTime"]
    w = ts >= max(ts[0], ts[-1] - P["nAvg"] * tc)
    return ts / tc, a[:, col["Cd"]], a[:, col["Cl"]], w


def yplus_max(name):
    """(t c/U, max y+ on the blade) from postProcessing/yPlus1."""
    d, P, _ = case_info(name)
    rows = []
    for _, sub in S._num_dirs(d / "postProcessing" / "yPlus1"):
        f = S.session_file(sub, "yPlus.dat")
        for line in f.read_text().splitlines() if f else []:
            if line.strip() and not line.startswith("#"):
                s = line.split()
                rows.append((float(s[0]), float(s[3])))
    a = np.array(sorted(set(rows)))
    return a[:, 0] / P["convTime"], a[:, 1]


def log_steps(name):
    """(t c/U, dt U/c, first-p initial residual) per time step, from log.pimpleFoam."""
    d, P, _ = case_info(name)
    with open(d / "log.pimpleFoam", "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        n_time = len(re.findall(rb"^Time = ", mm, re.M))
        a = np.array([(float(m.group(2)), float(m.group(1)), float(m.group(3))) for m in STEP.finditer(mm)])
    if len(a) != n_time:
        raise RuntimeError(f"{name}: parsed {len(a)} of {n_time} time steps in log.pimpleFoam")
    tc = P["convTime"]
    return a[:, 0] / tc, a[:, 1] / tc, a[:, 2]


# ------------------------------------------------------------------ measures
def running_mean(t, y, width=RM_WIDTH):
    """Centred running mean on a uniform DT_S grid; (grid, mean) where the full window fits."""
    tu = np.arange(np.ceil(t[0] / DT_S) * DT_S, t[-1] + 1e-9, DT_S)
    yu = np.interp(tu, t, y)
    n = int(round(width / DT_S))
    c = np.concatenate([[0.0], np.cumsum(yu)])
    m = (c[n:] - c[:-n]) / n                      # mean of yu[i:i+n]
    tm = tu[: len(m)] + (n - 1) * DT_S / 2        # centre of each window
    return tm, m


def running_mean_masked(t, y, bins, width=RM_WIDTH):
    """running_mean() of the samples outside the 1-c/U intervals in bins; nan where fewer than half
    of the samples in the window are outside them."""
    tu = np.arange(np.ceil(t[0] / DT_S) * DT_S, t[-1] + 1e-9, DT_S)
    yu = np.interp(tu, t, y)
    ok = ~np.isin(np.floor(tu).astype(int), bins)
    n = int(round(width / DT_S))
    cs = np.concatenate([[0.0], np.cumsum(np.where(ok, yu, 0.0))])
    cn = np.concatenate([[0], np.cumsum(ok)])
    s, k = cs[n:] - cs[:-n], cn[n:] - cn[:-n]
    tm = tu[: len(s)] + (n - 1) * DT_S / 2
    return tm, np.where(k >= n / 2, s / np.maximum(k, 1), np.nan)


def stays_from(tm, ok):
    """Earliest time from which ok holds to the end (nan if it never does at the end)."""
    if not ok[-1]:
        return float("nan")
    bad = np.where(~ok)[0]
    return float(tm[0] if bad.size == 0 else tm[bad[-1] + 1])


def jump_bins(t, Cd, limit=JUMP):
    """Sorted 1-c/U interval indices k (k >= T_START) whose later sample follows a Cd change > limit."""
    d = np.abs(np.diff(Cd))
    m = (d > limit) & (t[1:] >= T_START)
    return sorted(set(np.floor(t[1:][m]).astype(int).tolist()))


def window(R):
    return float(R["avg_from_conv"]), float(R["avg_to_conv"])


def in_window(bins, w0, w1):
    """The 1-c/U intervals [k, k+1) of the window that hold a jump: k0 <= k < k1, with the bounds
    rounded to whole c/U (avg_from_conv carries round-off, 50.0000000187, which would drop [50, 51)).
    The window's last sample lies at k1 + 2e-8; a jump there counts in the last interval, k1 - 1."""
    k0, k1 = int(round(w0)), int(round(w1))
    return sorted({k1 - 1 if k == k1 else k for k in bins if k0 <= k <= k1})


def loglin_efold(x, y):
    """e-folding length of y(x) from a least-squares line through log y (positive = decay)."""
    p = np.polyfit(x, np.log(y), 1)
    return float(-1.0 / p[0])


def cl_peaks(t, Cl, t0, t1):
    """Peak-to-peak amplitudes (time of the maximum, max - next min) of Cl in [t0, t1]."""
    tm, s = running_mean(t, Cl, 1.0)               # 1-c/U smoothing removes start-up wiggles
    i_max = np.where((s[1:-1] > s[:-2]) & (s[1:-1] >= s[2:]))[0] + 1
    i_min = np.where((s[1:-1] < s[:-2]) & (s[1:-1] <= s[2:]))[0] + 1
    out = []
    for i in i_max:
        if t0 <= tm[i] <= t1:
            nxt = i_min[i_min > i]
            if nxt.size:
                out.append((float(tm[i]), float(s[i] - s[nxt[0]])))
    return out


# ------------------------------------------------------------------ analysis
def analyse_run(name, label, ran_on, with_logs):
    d, P, R = case_info(name)
    t, Cd, Cl, w = forces(name)
    w0, w1 = window(R)
    tm, rm = running_mean(t, Cd)
    last50 = t >= t[-1] - 50 - 1e-9
    last10 = t >= t[-1] - 10 - 1e-9
    jb = jump_bins(t, Cd)
    jb_win = in_window(jb, w0, w1)
    r = dict(name=name, label=label, ran_on=ran_on, ranks=int(P["nProcs"]), alpha=float(P["alphaDeg"]),
             U=float(P["Uinf"]), model=P["model"], level=P["level"], maxCo=float(P["maxCo"]),
             n_samples=int(t.size), t_end=float(t[-1]), win_from=w0, win_to=w1,
             Cd_win=float(Cd[w].mean()), Cd_std_win=float(Cd[w].std()), Cl_win=float(Cl[w].mean()),
             Cd_win_table=float(R["Cd_mean"]), Cd_std_table=float(R["Cd_std"]),
             Cd_last50=float(Cd[last50].mean()), Cd_last10=float(Cd[last10].mean()),
             Cl_std_last10=float(Cl[last10].std()),
             rm_min_win=float(rm[(tm >= w0) & (tm <= w1)].min()), rm_max_win=float(rm[(tm >= w0) & (tm <= w1)].max()),
             jump_max_win=float(np.abs(np.diff(Cd))[w[1:] & w[:-1]].max()),
             jump_bins_win=len(jb_win), jump_first=float(jb[0]) if jb else float("nan"),
             jump_last=float(jb[-1] + 1) if jb else float("nan"),
             Cd_min=float(Cd.min()), Cd_max=float(Cd.max()), Cl_min=float(Cl.min()), Cl_max=float(Cl.max()))
    keep = w & ~np.isin(np.floor(t).astype(int), jb)
    r["Cd_win_nojump"] = float(Cd[keep].mean()) if keep.any() else float("nan")
    # the window without its jump intervals: share of samples, Cd scatter, mean lift
    r["nojump_share_win"] = float(keep.sum() / w.sum())
    r["Cd_std_win_nojump"] = float(Cd[keep].std()) if keep.any() else float("nan")
    r["Cl_win_nojump"] = float(Cl[keep].mean()) if keep.any() else float("nan")
    # running mean of the jump-free samples (defined where at least half of the 8 c/U are jump-free)
    tj, rj = running_mean_masked(t, Cd, jb)
    for lab, sel in (("win", (tj >= w0) & (tj <= w1)), ("after30", tj >= 30.0)):
        ok = sel & np.isfinite(rj)
        r[f"rmj_min_{lab}"] = float(rj[ok].min()) if ok.any() else float("nan")
        r[f"rmj_max_{lab}"] = float(rj[ok].max()) if ok.any() else float("nan")
        r[f"rmj_cover_{lab}"] = float(ok.sum() / sel.sum())
    if r["alpha"] == 0:
        hi = r["Cd_last50"] > STATE_CD
        r["state"] = "high-drag" if hi else "low-drag"
        r["t_enter"] = stays_from(tm, rm > ENTER_HI if hi else rm < ENTER_LO)
        r["t_settle5"] = stays_from(tm, np.abs(rm / r["Cd_last50"] - 1) <= SETTLE)
        # a running mean that later passes through jump intervals does not mark a state
        if jb and jb[-1] + 1 > min(r["t_enter"], r["t_settle5"]):
            r["t_enter"] = r["t_settle5"] = float("nan")
        r["rm_side_win"] = bool(np.all((rm[(tm >= w0) & (tm <= w1)] > STATE_CD) == hi))
    else:
        r["state"], r["t_enter"], r["t_settle5"], r["rm_side_win"] = "", float("nan"), float("nan"), None
    # blocks
    blocks = []
    yt, yp = yplus_max(name)
    # blade-maximum y+ in the window (sampled once per c/U): largest value, its time, and whether it
    # falls in a jump interval; largest value outside the jump intervals
    yw = (yt >= w0 - 1e-9) & (yt <= w1 + 1e-9)
    iy = int(np.argmax(np.where(yw, yp, -np.inf)))
    yin = np.isin(np.floor(yt).astype(int), jb)
    r.update(yplus_max_win=float(yp[iy]), yplus_max_win_t=float(yt[iy]), yplus_max_win_in_jump=bool(yin[iy]),
             yplus_max_win_nojump=float(yp[yw & ~yin].max()) if (yw & ~yin).any() else float("nan"))
    steps = log_steps(name) if with_logs else None
    nb = int(round(t[-1] / BLOCK))
    for k in range(nb):
        lo, hi_ = k * BLOCK, (k + 1) * BLOCK
        m = (t >= lo) & (t < hi_ + (1e-6 if k == nb - 1 else 0))
        b = dict(name=name, t_from=lo, t_to=hi_, Cd_mean=Cd[m].mean(), Cd_std=Cd[m].std(), Cd_min=Cd[m].min(),
                 Cd_max=Cd[m].max(), Cl_mean=Cl[m].mean(), Cl_std=Cl[m].std(),
                 jump_bins=len([j for j in jb if lo <= j < hi_]))
        my = (yt >= lo) & (yt < hi_ + (1e-6 if k == nb - 1 else 0))
        b["yplus_max"] = yp[my].max() if my.any() else np.nan
        if steps is not None:
            st, sdt, spr = steps
            ms = (st >= lo) & (st < hi_ + (1e-6 if k == nb - 1 else 0))
            b.update(n_steps=int(ms.sum()), dt_mean=sdt[ms].mean(), dt_min=sdt[ms].min(),
                     pres_median=float(np.median(spr[ms])), pres_share=float(np.mean(spr[ms] > P_RES)))
        blocks.append(b)
    B = pd.DataFrame(blocks)
    if r["alpha"] == 0 and r["state"] == "low-drag" and not jb_win:
        inwin = (B.t_from >= w0) & (B.t_to <= w1)
        r["Cl_std_efold"] = loglin_efold((B.t_from[inwin] + B.t_to[inwin]) / 2, B.Cl_std[inwin])
        last = B.Cd_mean.iloc[-1]
        m2 = inwin & (B.t_to <= w1 - BLOCK + 1e-9)
        r["Cd_excess_efold"] = loglin_efold((B.t_from[m2] + B.t_to[m2]) / 2, B.Cd_mean[m2] - last)
    return r, B, (t, Cd, Cl, tm, rm, jb)


def scan_all(quality, polars):
    """Force jumps in every section run (all 51 of the table)."""
    rows = []
    for name in polars["name"]:
        d, P, R = case_info(name)
        t, Cd, _, w = forces(name)
        w0, w1 = window(R)
        dd = np.abs(np.diff(Cd))[w[1:] & w[:-1]]
        row = dict(name=name, alpha=float(P["alphaDeg"]), U=float(P["Uinf"]), model=P["model"], level=P["level"],
                   maxCo=float(P["maxCo"]), Tu=float(P["TuBodyPercent"]),
                   flagged=bool(quality.set_index("name").loc[name, "corrupted"]),
                   Cd_win=float(Cd[w].mean()), jump_max_win=float(dd.max()))
        for lim in (JUMP,) + JUMP_ALT:
            jb = jump_bins(t, Cd, lim)
            keep = w & ~np.isin(np.floor(t).astype(int), jb)
            row[f"jump_bins_win_{lim:g}"] = len(in_window(jb, w0, w1))
            row[f"Cd_win_nojump_{lim:g}"] = float(Cd[keep].mean()) if keep.any() else float("nan")
        rows.append(row)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ figure
def figure(results, series):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    L.style()
    SAMPLE, JUMPC, WIN = "#9a9a9a", "#f2c4c4", "#ececec"
    fig = plt.figure(figsize=(7.4, 11.2))
    gs = fig.add_gridspec(len(results), 2, width_ratios=[1.3, 1.0], hspace=0.62, wspace=0.16,
                          left=0.075, right=0.985, top=0.935, bottom=0.045)
    for i, (r, (t, Cd, Cl, tm, rm, jb)) in enumerate(zip(results, series)):
        a0 = r["alpha"] == 0
        ylim_d = (1.0, 4.9) if a0 else (0.0, 3.4)
        ylim_l = (-2.4, 2.4) if a0 else (-3.0, 1.2)
        for j, (y, ylim, lab) in enumerate(((Cd, ylim_d, "Cd"), (Cl, ylim_l, "Cl"))):
            ax = fig.add_subplot(gs[i, j])
            ax.axvspan(r["win_from"], r["win_to"], color=WIN, zorder=0, lw=0)
            for k in jb:
                ax.axvspan(k, k + 1, color=JUMPC, zorder=0.5, lw=0)
            ax.plot(t, y, color=SAMPLE, lw=0.35, zorder=2)
            if j == 0:
                ax.plot(tm, rm, color=L.BLACK, lw=1.1, zorder=3)
                if a0:
                    ax.axhline(STATE_CD, color=L.BLACK, ls=":", lw=0.7, zorder=1)
            ax.set_xlim(0, 150)
            ax.set_ylim(*ylim)
            ax.set_ylabel(lab, labelpad=1)
            ax.set_xticks(range(0, 151, 25))
            if i < len(results) - 1:
                ax.set_xticklabels([])
            else:
                ax.set_xlabel("t U/c")
            off = (y.min() < ylim[0]) or (y.max() > ylim[1])
            if off:
                ax.text(0.995, 0.04 if j == 0 else 0.96, f"range {y.min():.3g} to {y.max():.3g} (off scale)",
                        transform=ax.transAxes, ha="right", va="bottom" if j == 0 else "top", fontsize=5.6,
                        color="#7a1f1f", zorder=6,
                        bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none", alpha=0.9))
            if j == 0:
                where = "Mac" if r["ran_on"] == "mac" else "Unity"
                ax.set_title(f"{r['label']}  ({where}, {r['ranks']} ranks)", loc="left", fontsize=7, pad=2.5)
                parts = []
                if a0 and np.isfinite(r["t_enter"]):
                    parts.append(f"{r['state']} from {r['t_enter']:.0f} c/U")
                elif a0:
                    parts.append(f"{r['state']} in the last 50 c/U")
                if r["jump_bins_win"]:
                    parts.append(f"jumps in {r['jump_bins_win']} of 100 window c/U")
                elif jb:
                    parts.append(f"jumps in {jb[0]}-{jb[-1] + 1} c/U")
                parts.append(f"window Cd {r['Cd_win']:.3f} ± {r['Cd_std_win']:.3f}")
                txt = "; ".join(parts)
                ax.text(0.01, 0.955, txt, transform=ax.transAxes, ha="left", va="top", fontsize=5.8,
                        bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none", alpha=0.85), zorder=6)
    handles = [Line2D([], [], color=SAMPLE, lw=0.8, label="samples (every 0.02 c/U)"),
               Line2D([], [], color=L.BLACK, lw=1.1, label=f"running mean over {RM_WIDTH:g} c/U"),
               Line2D([], [], color=L.BLACK, lw=0.7, ls=":", label=f"Cd {STATE_CD:g}: state boundary (α 0)"),
               Patch(color=WIN, label="averaging window (last 100 c/U)"),
               Patch(color=JUMPC, label=f"1-c/U interval with a Cd jump > {JUMP:g} between samples")]
    fig.legend(handles=handles, loc="upper center", ncol=3, fontsize=6.3, frameon=False,
               bbox_to_anchor=(0.53, 0.995), handlelength=2.2, columnspacing=1.4)
    FIG.mkdir(exist_ok=True)
    out = FIG / "section_alpha0_histories.png"
    fig.savefig(out, dpi=200, facecolor="white")
    plt.close(fig)
    return out


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-logs", action="store_true", help="do not read the solver logs (no dt, y+ only)")
    a = ap.parse_args()
    polars = pd.read_csv(DATA / "section_polars.csv")
    quality = pd.read_csv(OUT / "section_case_quality.csv")
    ran_on = polars.set_index("name")["ran_on"]

    results, blocks, series = [], [], []
    for name, label in RUNS8:
        r, B, s = analyse_run(name, label, ran_on[name], not a.no_logs)
        results.append(r)
        blocks.append(B)
        series.append(s)
        print(f"{name:42s} window {r['Cd_win']:.4f} ± {r['Cd_std_win']:.4f} (table {r['Cd_win_table']:.4f}); "
              f"{r['state'] or '-':9s} enter {r['t_enter']:6.2f} settle5 {r['t_settle5']:6.2f}; "
              f"jumps in window {r['jump_bins_win']:3d}, max {r['jump_max_win']:.3g}")
    R8 = pd.DataFrame(results)
    R8.to_csv(OUT / "section_histories_runs.csv", index=False, float_format="%.6g")
    pd.concat(blocks).to_csv(OUT / "section_histories_blocks.csv", index=False, float_format="%.6g")
    J = scan_all(quality, polars)
    J.to_csv(OUT / "section_force_jumps.csv", index=False, float_format="%.6g")

    # numbers quoted in the addendum
    H = J[~J.flagged]
    jumpy = H[H.jump_max_win > JUMP]
    clean = H[H.jump_max_win <= JUMP]
    same = all(((H.jump_max_win > lim) == (H.jump_max_win > JUMP)).all() for lim in JUMP_ALT)
    Bk = pd.concat(blocks).set_index(["name", "t_from"])
    q = dict(
        runs=R8.set_index("name").to_dict(orient="index"),
        scan=dict(n_runs=int(len(J)), n_healthy=int(len(H)), n_healthy_with_jumps=int(len(jumpy)),
                  healthy_with_jumps=sorted(jumpy.name), healthy_jump_max_range=[float(jumpy.jump_max_win.min()),
                                                                                 float(jumpy.jump_max_win.max())],
                  clean_jump_max=float(clean.jump_max_win.max()), clean_jump_max_run=str(
                      clean.loc[clean.jump_max_win.idxmax(), "name"]),
                  same_runs_for_limits_0p1_0p2_0p5=bool(same),
                  flagged_jump_bins_win_range=[int(J[J.flagged][f"jump_bins_win_{JUMP:g}"].min()),
                                               int(J[J.flagged][f"jump_bins_win_{JUMP:g}"].max())]),
    )
    if not a.no_logs:
        fine = "a000.0_U23.0_SST_fine_Tu1.0_Co2.5n2"
        fb = Bk.loc[fine]
        ep = (fb.index >= 30) & (fb.index < 90)
        outside = (fb.index < 20) | (fb.index >= 100)
        q["fine_episode"] = dict(
            blocks="episode: the 10-c/U blocks 30-90 (inside the jumps of 28-96 c/U); outside: 0-20 and 100-150",
            pres_median_episode=[float(fb.pres_median[ep].min()), float(fb.pres_median[ep].max())],
            pres_median_outside=[float(fb.pres_median[outside].min()), float(fb.pres_median[outside].max())],
            dt_min_episode=float(fb.dt_min[ep].min()), dt_mean_episode=float(fb.dt_mean[ep].mean()),
            dt_mean_after100=float(fb.dt_mean[fb.index >= 100].mean()),
            dt_min_after100=float(fb.dt_min[fb.index >= 100].min()),
            yplus_max_episode=float(fb.yplus_max[ep].max()),
            yplus_max_after100=float(fb.yplus_max[fb.index >= 100].max()))
        f180 = Bk.loc["a180.0_U23.0_SST_medium_Tu1.0"]
        o180 = Bk.loc["a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2"]
        win5, win25 = f180.index >= 50, o180.index >= 50
        jblk, cblk = win25 & (o180.jump_bins > 0), win25 & (o180.jump_bins == 0)
        q["a180_medium"] = dict(
            blocks="10-c/U blocks inside the averaging window (50-150 c/U)",
            co5_dt_min_win=float(f180.dt_min[win5].min()), co5_dt_mean_win=float(f180.dt_mean[win5].mean()),
            co5_yplus_max_win=float(f180.yplus_max[win5].max()),
            co5_pres_share_win=[float(f180.pres_share[win5].min()), float(f180.pres_share[win5].max())],
            co25_dt_min_win_jump_blocks=float(o180.dt_min[jblk].min()),
            co25_dt_min_win_clean_blocks=float(o180.dt_min[cblk].min()),
            # the minimum time step of each window block: range over the blocks with and without jumps
            co25_dt_min_jump_blocks_range=[float(o180.dt_min[jblk].min()), float(o180.dt_min[jblk].max())],
            co25_dt_min_clean_blocks_range=[float(o180.dt_min[cblk].min()), float(o180.dt_min[cblk].max())],
            co25_dt_mean_win=float(o180.dt_mean[win25].mean()),
            co25_yplus_max_win=float(o180.yplus_max[win25].max()))
    # alpha 180, medium mesh, maxCo 5: window Cd samples; grid values without the jump intervals
    by_ = R8.set_index("name")
    t5_, Cd5_ = series[6][0], series[6][1]
    r5 = by_.loc[RUNS8[6][0]]
    w5_ = (t5_ >= r5.win_from - 1e-9) & (t5_ <= r5.win_to + 1e-9)
    Jn = J.set_index("name")
    tri = [float(Jn.loc[f"a180.0_U23.0_SST_{lv}_Tu1.0_Co2.5n2", f"Cd_win_nojump_{JUMP:g}"])
           for lv in ("coarse", "medium", "fine")]
    q.setdefault("a180_medium", {}).update(
        co5_Cd_win_range=[float(Cd5_[w5_].min()), float(Cd5_[w5_].max())],
        grid_nojump_coarse_medium_fine=tri,
        medium_vs_coarse_pct=100 * (tri[1] / tri[0] - 1), medium_vs_fine_pct=100 * (tri[1] / tri[2] - 1))
    # alpha 0 grid at maxCo 2.5 on the last 50 c/U of each run (the fine run's last 50 c/U have no jumps)
    g50 = [float(by_.loc[f"a000.0_U23.0_SST_{lv}_Tu1.0_Co2.5n2", "Cd_last50"]) for lv in ("coarse", "medium", "fine")]
    q["grid_alpha0_last50"] = dict(coarse_medium_fine=g50, spread_pct_of_fine=100 * (max(g50) - min(g50)) / g50[2],
                                   monotonic=bool(np.all(np.diff(g50) > 0) or np.all(np.diff(g50) < 0)))
    # healthy runs with jumps: change of the window mean without the jump intervals; alpha-0 states
    chg = (100 * (jumpy[f"Cd_win_nojump_{JUMP:g}"] / jumpy.Cd_win - 1)).round(6)
    chg.index = jumpy.name
    big = chg[chg.abs() > 3]
    a0 = H[H.alpha == 0]
    q["scan"].update(
        healthy_mean_change_pct=chg.to_dict(),
        healthy_mean_change_pct_range_others=[float(chg.drop(big.index).min()), float(chg.drop(big.index).max())],
        healthy_mean_change_pct_large=big.to_dict(),
        alpha0_healthy_state_unchanged=bool(
            ((a0.Cd_win > STATE_CD) == (a0[f"Cd_win_nojump_{JUMP:g}"] > STATE_CD)).all()),
        jump_to_clean_ratio=[float(jumpy.jump_max_win.min() / clean.jump_max_win.max()),
                             float(jumpy.jump_max_win.max() / clean.jump_max_win.max())],
        flagged_all_with_jumps=bool((J[J.flagged].jump_max_win > JUMP).all()))
    # start-up growth and decay of the lift oscillation (medium pair)
    t5, Cl5 = series[0][0], series[0][2]
    t25, Cl25 = series[1][0], series[1][2]
    tf, Clf = series[4][0], series[4][2]
    q["startup_cl_p2p"] = dict(co5=cl_peaks(t5, Cl5, 5, 45), co25=cl_peaks(t25, Cl25, 5, 45),
                               fine=cl_peaks(tf, Clf, 5, 27),
                               coarse_co5=cl_peaks(series[2][0], series[2][2], 5, 45),
                               coarse_co25=cl_peaks(series[3][0], series[3][2], 5, 45))
    sp = q["startup_cl_p2p"]
    near24 = lambda pk: min(pk, key=lambda p: abs(p[0] - 24.0))  # noqa: E731  cycle nearest 24 c/U
    ratios = [a[1] / b[1] for k in ("co25", "coarse_co25") for a, b in zip(sp[k][:-1], sp[k][1:])]
    sp.update(co5_near24=[near24(sp["co5"]), near24(sp["coarse_co5"])],
              co25_decay_ratio_per_cycle=[float(min(ratios)), float(max(ratios))],
              co25_last=[sp["co25"][-1], sp["coarse_co25"][-1]],
              # the fine run's third cycle ends where its jumps start (28 c/U): only two are quoted
              fine_first_two_ratio=float(sp["fine"][0][1] / sp["fine"][1][1]))
    # restart (b): how far 60 c/U take the residual lift oscillation of the low-drag field if it
    # regrows as fast as the maxCo-5 start-up grew (maxima between 9 and 25 c/U; an estimate)
    g = np.array([p for p in q["startup_cl_p2p"]["co5"] if 9 <= p[0] <= 25])
    efold = 1.0 / np.polyfit(g[:, 0], np.log(g[:, 1]), 1)[0]
    by = R8.set_index("name")
    cl0, clhi = float(by.loc[RUNS8[1][0], "Cl_std_last10"]), float(by.loc[RUNS8[0][0], "Cl_std_last10"])
    q["restart_b_estimate"] = dict(
        growth_efold_conv=float(efold), maxima_used=g.tolist(), amplification_60=float(np.exp(60 / efold)),
        cl_std_start=cl0, cl_std_after_60=float(cl0 * np.exp(60 / efold)), cl_std_high_drag=clhi,
        conv_to_high_drag_level=float(efold * np.log(clhi / cl0)))
    # the fine run's jumps (review, 14 Oct): its jump-free samples lie almost all after the jump span, so
    # its state during the jumps is judged from the lift of all samples, against the high-drag runs
    tF, CdF, jbF = series[4][0], series[4][1], series[4][5]
    tjF, rjF = running_mean_masked(tF, CdF, jbF)
    okF = (tjF >= 30.0) & np.isfinite(rjF)
    fbk = Bk.loc[RUNS8[4][0]]
    epF = (fbk.index >= 30) & (fbk.index < 90)
    hd = pd.concat([Bk.loc[RUNS8[k][0]] for k in (0, 2)])          # medium and coarse, maxCo 5 (high-drag)
    q["fine_jumps_state"] = dict(
        jump_span=[int(jbF[0]), int(jbF[-1] + 1)],
        jump_free_intervals_in_span=sorted(set(range(jbF[0], jbF[-1] + 1)) - set(jbF)),
        rmj_first_defined_after30=float(tjF[okF][0]),
        cl_mean_blocks_30_90=[float(fbk.Cl_mean[epF].min()), float(fbk.Cl_mean[epF].max())],
        high_drag_window_block_cl_mean=[float(hd.Cl_mean[hd.index >= 50].min()),
                                        float(hd.Cl_mean[hd.index >= 50].max())])
    (OUT / "section_histories.json").write_text(json.dumps(q, indent=1, default=float))
    print(f"healthy runs with Cd jumps > {JUMP:g} in the window: {len(jumpy)} of {len(H)} "
          f"(jumps {jumpy.jump_max_win.min():.3g}-{jumpy.jump_max_win.max():.3g}; "
          f"others <= {clean.jump_max_win.max():.3g}); "
          f"same runs at limits {JUMP_ALT}: {same}")
    print(figure(results, series))


if __name__ == "__main__":
    main()
