#!/usr/bin/env python3
"""Force histories of all 69 Stage 2 runs: health and jump scan, alpha-0 states, window sensitivity
(analysis of 15 Oct 2026, roughness stage; adapted from 2026-10-13/src/section_histories.py).

    nice -n 10 python3 cfd/analysis/2026-10-15/src/roughness_histories.py            # about 4 min
    nice -n 10 python3 cfd/analysis/2026-10-15/src/roughness_histories.py --no-logs  # about 20 s

Reads, read only:
  cfd/stage2/results/stage2_polars.csv                 the 69 cases (43 of 13 Oct + 26 re-runs)
  cfd/stage2/runs/<case>/case.json, results.json
  cfd/stage2/runs/<case>/postProcessing/forceCoeffs1/<t>/coefficient.dat  (restarts joined by
      cfd/post/section_summary.read_table, as on 13 Oct)
  cfd/stage2/runs/<case>/postProcessing/yPlus1/<t>/yPlus.dat              (blade maximum y+)
  cfd/stage2/runs/<case>/log.pimpleFoam of the 16 texture runs at maxCo 2.5 (time step and the
      initial residual of the first pressure solve of every step; skipped with --no-logs)
Writes:
  ../out/roughness_histories_runs.csv    one row per run: table check, jumps, windows, end slope,
                                         alpha-0 state, start-up noise
  ../out/roughness_histories_blocks.csv  10-c/U blocks of every run (Cd, Cl)
  ../out/roughness_log_blocks.csv        5-c/U blocks of the 16 texture runs at maxCo 2.5: time
                                         step and first pressure residual (not with --no-logs)
  ../out/roughness_histories.json        numbers quoted from this script
  ../fig/roughness_texture_histories.png Cd(t) of the 23 m/s texture runs, maxCo 5 and 2.5

Definitions (as 13 Oct, RESULTS.md addendum, unless stated):
  t* = t U/c, c = 48 mm; forces sampled every 0.02 c/U.
  Table window: the samples with t >= t_end - nAvg c/U (section_summary.summarize): 50-150 c/U for
    the 150-c/U runs, 30-80 c/U for the 80-c/U texture runs of 13 Oct.
  Drift (noise rule): mean of the second half of a window minus the mean of the first half.
  Other windows (new here): 30-80 c/U (the 13 Oct texture window, so maxCo 5 and 2.5 can be
    compared on the same window) and 100-150 c/U (the last 50 c/U of a 150-c/U run).
  End slope: least-squares slope of Cd over the last 50 c/U, per 100 c/U (a still-decaying run has
    a non-zero slope).
  Force jump: a Cd change of more than 0.5 between consecutive samples, from 2 c/U on; the 1-c/U
    interval holding the later sample is a jump interval (13 Oct). Limits 0.2 and 0.1 are reported
    as sensitivities.
  Start-up noise end: the end of the last 1-c/U interval with a Cd change of more than 0.1 between
    samples (new here; descriptive).
  alpha-0 state (13 Oct boundary): high-drag where the 8-c/U running mean of Cd exceeds 2.5, else
    low-drag. A run is 'mixed' when its table window holds both; the switch time is the last time
    the running mean crosses 2.5.
  Running means for the figure: 8 c/U at alpha 0 (about one shedding period, St 0.12-0.15) and
    5 c/U at alpha 180 (St 0.17-0.22).
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
ROOT = HERE.parent                                   # cfd/analysis/2026-10-15
REPO = ROOT.parents[2]
RUNS = REPO / "cfd" / "stage2" / "runs"
TABLE = REPO / "cfd" / "stage2" / "results" / "stage2_polars.csv"
sys.path.insert(0, str(REPO / "cfd" / "post"))
import section_summary as S  # noqa: E402  restart-joining reader of postProcessing tables

FIG, OUT = ROOT / "fig", ROOT / "out"
DT_S = 0.02
JUMP, JUMP_ALT = 0.5, (0.2, 0.1)
NOISE_LIM = 0.1
T_START = 2.0
STATE_CD = 2.5
W_OLD, W_NEW, W_LAST = (30.0, 80.0), (50.0, 150.0), (100.0, 150.0)
BLOCK = 10.0
LOG_BLOCK = 5.0
P_RES = 0.05

STEP = re.compile(rb"^deltaT = (\S+)\nTime = (\S+)\n\nPIMPLE: iteration 1\n(?:(?!GAMG)[^\n]*\n){0,8}"
                  rb"GAMG:  Solving for p, Initial residual = ([^,]+),", re.M)


# ------------------------------------------------------------------ reading
def case_info(name):
    d = RUNS / name
    return d, json.loads((d / "case.json").read_text()), json.loads((d / "results.json").read_text())


def forces(name):
    """t (c/U), Cd, Cl (restarts joined) and the table-window mask (as section_summary.summarize)."""
    d, P, _ = case_info(name)
    names, a = S.read_table(d / "postProcessing" / "forceCoeffs1", "coefficient.dat")
    col = {n: i for i, n in enumerate(names)}
    ts, tc = a[:, 0], P["convTime"]
    w = ts >= max(ts[0], ts[-1] - P["nAvg"] * tc)
    return ts / tc, a[:, col["Cd"]], a[:, col["Cl"]], w


def yplus_blade_max(name):
    d, P, _ = case_info(name)
    rows = []
    for _, sub in S._num_dirs(d / "postProcessing" / "yPlus1"):
        f = S.session_file(sub, "yPlus.dat")
        for line in f.read_text().splitlines() if f else []:
            if line.strip() and not line.startswith("#"):
                s = line.split()
                if s[1] == "blade":
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
        raise RuntimeError(f"{name}: parsed {len(a)} of {n_time} time steps")
    tc = P["convTime"]
    return a[:, 0] / tc, a[:, 1] / tc, a[:, 2]


# ------------------------------------------------------------------ measures
def running_mean(t, y, width):
    tu = np.arange(np.ceil(t[0] / DT_S) * DT_S, t[-1] + 1e-9, DT_S)
    yu = np.interp(tu, t, y)
    n = int(round(width / DT_S))
    c = np.concatenate([[0.0], np.cumsum(yu)])
    m = (c[n:] - c[:-n]) / n
    return tu[: len(m)] + (n - 1) * DT_S / 2, m


def win_stats(t, y, w0, w1):
    """Mean and drift (second half minus first half) of y over [w0, w1] c/U; nan if not covered (a run
    ending up to 0.05 c/U short of w1 counts as covered: the migrated alpha-180 Ks-50 run ends at 149.98)."""
    if t[-1] < w1 - 0.05 or t[0] > w0 + 1e-6:
        return float("nan"), float("nan")
    m = (t >= w0 - 1e-6) & (t <= w1 + 1e-6)
    tw, yw = t[m], y[m]
    half = tw[0] + 0.5 * (tw[-1] - tw[0])
    return float(yw.mean()), float(yw[tw >= half].mean() - yw[tw < half].mean())


def end_slope(t, y, span=50.0):
    m = t >= t[-1] - span - 1e-9
    return float(100.0 * np.polyfit(t[m], y[m], 1)[0])          # per 100 c/U


def jump_bins(t, Cd, limit):
    d = np.abs(np.diff(Cd))
    m = (d > limit) & (t[1:] >= T_START)
    return sorted(set(np.floor(t[1:][m]).astype(int).tolist()))


def in_window(bins, w0, w1):
    """1-c/U intervals [k, k+1) of the window holding a jump (13 Oct rule: bounds rounded; a jump at
    the last sample counts in the last interval)."""
    k0, k1 = int(round(w0)), int(round(w1))
    return sorted({k1 - 1 if k == k1 else k for k in bins if k0 <= k <= k1})


# ------------------------------------------------------------------ per run
def analyse(row, with_logs):
    name = row["name"]
    d, P, R = case_info(name)
    t, Cd, Cl, w = forces(name)
    w0, w1 = float(R["avg_from_conv"]), float(R["avg_to_conv"])
    half = t[w][0] + 0.5 * (t[w][-1] - t[w][0])
    drift_tab_recalc = float(Cd[w][t[w] >= half].mean() - Cd[w][t[w] < half].mean())
    dd = np.abs(np.diff(Cd))
    ww = w[1:] & w[:-1]
    r = dict(name=name, wall=row["wall"], alpha=float(row["alpha_deg"]), U=float(row["U_ms"]), model=row["model"],
             Ks_um=float(row["Ks_um"]), t_mm=round(float(row["tex_t_mm"]), 3), maxCo=float(row["maxCo"]),
             ranks=int(P["nProcs"]), t_end=float(t[-1]), win_from=w0, win_to=w1, n_samples=int(t.size),
             Cd_win=float(Cd[w].mean()), Cd_win_table=float(R["Cd_mean"]), Cd_drift_recalc=drift_tab_recalc,
             Cd_drift_table=float(R["Cd_drift"]), Cl_win=float(Cl[w].mean()), Cd_std_win=float(Cd[w].std()),
             jump_max_win=float(dd[ww].max()))
    r["table_check_absdiff"] = max(abs(r["Cd_win"] - r["Cd_win_table"]), abs(drift_tab_recalc - r["Cd_drift_table"]))
    for lim in (JUMP,) + JUMP_ALT:
        jb = jump_bins(t, Cd, lim)
        r[f"jump_bins_win_{lim:g}"] = len(in_window(jb, w0, w1))
        r[f"jump_bins_run_{lim:g}"] = len(jb)
        r[f"jump_last_{lim:g}"] = float(jb[-1] + 1) if jb else float("nan")
        if lim == JUMP:
            keep = w & ~np.isin(np.floor(t).astype(int), jb)
            r["Cd_win_nojump"] = float(Cd[keep].mean()) if keep.any() else float("nan")
            r["nojump_share_win"] = float(keep.sum() / w.sum())
    jb_noise = jump_bins(t, Cd, NOISE_LIM)
    r["noise_end"] = float(jb_noise[-1] + 1) if jb_noise else float("nan")
    for lab, (a0, a1) in (("30_80", W_OLD), ("50_150", W_NEW), ("100_150", W_LAST)):
        r[f"Cd_{lab}"], r[f"drift_{lab}"] = win_stats(t, Cd, a0, a1)
        r[f"Cl_{lab}"], _ = win_stats(t, Cl, a0, a1)
    r["end_slope_per100"] = end_slope(t, Cd)
    r["Cd_last1"] = float(Cd[t >= t[-1] - 1.0 - 1e-9].mean())
    yt, yp = yplus_blade_max(name)
    yw = (yt >= w0 - 1e-6) & (yt <= w1 + 1e-6)
    r["yplus_blade_max_win_max"] = float(yp[yw].max())
    width = 8.0 if r["alpha"] == 0 else 5.0
    tm, rm = running_mean(t, Cd, width)
    r["rm_width"] = width
    if r["alpha"] == 0:
        inw = (tm >= w0) & (tm <= w1)
        hi = rm > STATE_CD
        r["state_high_share_win"] = float(hi[inw].mean())
        r["state_win"] = ("high-drag" if hi[inw].all() else "low-drag" if not hi[inw].any() else "mixed")
        in30 = (tm >= W_OLD[0]) & (tm <= W_OLD[1])
        r["state_30_80"] = ("high-drag" if hi[in30].all() else "low-drag" if not hi[in30].any() else "mixed")
        late = tm >= 20.0
        cross = np.where(np.diff(hi[late].astype(int)) != 0)[0]
        r["state_last_cross"] = float(tm[late][cross[-1] + 1]) if cross.size else float("nan")
        r["state_end"] = "high-drag" if rm[-1] > STATE_CD else "low-drag"
        # high-drag phase entered after 20 c/U (start-up excluded): first and last time above 2.5
        r["high_from"] = float(tm[late][hi[late]][0]) if hi[late].any() else float("nan")
        r["high_to"] = float(tm[late][hi[late]][-1]) if hi[late].any() else float("nan")
    # blocks
    blocks = []
    for k in range(int(round(t[-1] / BLOCK))):
        lo, hi_ = k * BLOCK, (k + 1) * BLOCK
        m = (t >= lo) & (t < hi_ + (1e-6 if hi_ >= t[-1] - 1e-6 else 0))
        blocks.append(dict(name=name, t_from=lo, t_to=hi_, Cd_mean=Cd[m].mean(), Cd_std=Cd[m].std(),
                           Cl_mean=Cl[m].mean(), Cl_std=Cl[m].std(),
                           jump_max=float(np.abs(np.diff(Cd[m])).max()) if m.sum() > 1 else float("nan")))
    logb = []
    if with_logs and r["wall"] == "tex" and r["maxCo"] == 2.5:
        st, sdt, spr = log_steps(name)
        r["log_steps"] = int(st.size)
        for k in range(int(round(t[-1] / LOG_BLOCK))):
            lo, hi_ = k * LOG_BLOCK, (k + 1) * LOG_BLOCK
            m = (st >= lo) & (st < hi_ + (1e-6 if hi_ >= st[-1] - 1e-6 else 0))
            logb.append(dict(name=name, t_from=lo, t_to=hi_, n_steps=int(m.sum()), dt_mean=float(sdt[m].mean()),
                             dt_min=float(sdt[m].min()), pres_median=float(np.median(spr[m])),
                             pres_share_gt=float(np.mean(spr[m] > P_RES))))
        L = pd.DataFrame(logb)
        quiet = L[L.t_from >= 100]
        r["log_dt_mean_last50"] = float(quiet.dt_mean.mean())
        r["log_pres_median_last50_max"] = float(quiet.pres_median.max())
        noisy = L[(L.t_from >= 10) & (L.t_to <= (r["noise_end"] if np.isfinite(r["noise_end"]) else 0))]
        r["log_pres_median_noisy_max"] = float(noisy.pres_median.max()) if len(noisy) else float("nan")
        r["log_dt_min_over_last50_mean"] = float(L[L.t_from >= 10].dt_min.min() / r["log_dt_mean_last50"])
    return r, pd.DataFrame(blocks), pd.DataFrame(logb), (t, Cd, Cl, tm, rm)


# ------------------------------------------------------------------ figure
TEX_PANELS = [
    ("a", 180, "SST", [0.0, 0.2], (0.85, 1.32), "α = 180°, SST"),
    ("b", 180, "LM", [0.0, 0.1, 0.2], (0.85, 1.32), "α = 180°, LM"),
    ("c", 0, "SST", [0.0, 0.2], (1.6, 2.35), "α = 0°, SST"),
    ("d", 0, "LM", [0.0, 0.1, 0.2], (1.6, 3.6), "α = 0°, LM"),
]
T_COLOR = {0.0: "#000000", 0.05: "#5598e7", 0.1: "#256abf", 0.2: "#184f95"}
T_LABEL = {0.0: "t 0 (smooth)", 0.1: "t 0.10 mm", 0.2: "t 0.20 mm"}


def tex_name(a, U, m, t, co):
    suf = "Co2.5n2" if co == 2.5 else "N80A50"
    return f"a{a:05.1f}_U{U:.1f}_{m}_tex{t:.3f}_s1_Tu1.0_{suf}"


def figure(series, runs):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    sys.path.insert(0, str(HERE))
    import roughness_analysis as RA          # same style as the other roughness figures
    RA.style()
    INK2 = "#52514e"
    fig, axes = plt.subplots(4, 1, figsize=(3.6, 8.9), sharex=True, constrained_layout=True,
                             gridspec_kw=dict(height_ratios=[1, 1, 1, 1.25]))
    idx = runs.set_index("name")
    for ax, (lab, a, m, ts, ylim, title) in zip(axes, TEX_PANELS):
        ax.axvspan(*W_NEW, color="#ececec", lw=0, zorder=0)
        ax.axvspan(*W_OLD, ymin=0.955, ymax=1.0, color="#9a9a9a", lw=0, zorder=0.5)
        for t_mm in ts:
            for co, ls, lw in ((5.0, (0, (2.2, 1.6)), 1.0), (2.5, "-", 1.2)):
                n = tex_name(a, 23.0, m, t_mm, co)
                tt, cd, cl, tm, rm = series[n]
                ok = tm >= 10
                y = np.clip(rm[ok], ylim[0] - 1, ylim[1] + 1)
                ax.plot(tm[ok], y, color=T_COLOR[t_mm], ls=ls, lw=lw, zorder=3)
        ax.set_ylim(*ylim)
        ax.set_ylabel("$C_d$, running mean (\u2013)")
        ax.set_title(f"({lab}) {title}, 23 m/s", loc="left")
        if a == 0 and m == "LM":
            r = idx.loc[tex_name(0, 23.0, "LM", 0.0, 2.5)]
            ax.annotate(f"t 0, maxCo 2.5: high-drag to {r.high_to:.0f} c/U,\nthen low-drag; jumps in "
                        f"{int(r['jump_bins_win_0.5'])} of 100 window c/U",
                        xy=(r.high_to, 2.62), xytext=(58, 3.36), fontsize=6.0, ha="left", va="center",
                        arrowprops=dict(arrowstyle="-", lw=0.6, color=INK2), color=INK2,
                        bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none", alpha=0.85))
        if a == 0 and m == "SST":
            r = idx.loc[tex_name(0, 23.0, "SST", 0.0, 2.5)]
            ax.text(56, 2.30, f"t 0, maxCo 2.5: above $C_d$ 2.5 (high-drag)\nto {r.high_to:.0f} c/U, off scale",
                    fontsize=6.0, ha="left", va="top", color=INK2)
    axes[-1].set_xlabel("Time t U/c (\u2013)")
    axes[-1].set_xlim(0, 150)
    axes[-1].set_xticks(range(0, 151, 25))
    h = [Line2D([], [], color=T_COLOR[t], lw=1.2, label=T_LABEL[t]) for t in (0.0, 0.1, 0.2)]
    h += [Line2D([], [], color=INK2, lw=1.2, ls="-", label="maxCo 2.5, 150 c/U"),
          Line2D([], [], color=INK2, lw=1.0, ls=(0, (2.2, 1.6)), label="maxCo 5, 80 c/U"),
          Patch(color="#ececec", label="window 50\u2013150 c/U"),
          Patch(color="#9a9a9a", label="bar: window 30\u201380 c/U")]
    fig.legend(handles=h, loc="outside lower center", ncol=3, fontsize=6.2, handlelength=2.2,
               columnspacing=1.0)
    fig.suptitle("Resolved texture: running mean of $C_d$ over about one shedding period\n"
                 "(5 c/U at 180\u00b0, 8 c/U at 0\u00b0)", fontsize=6.6, x=0.02, ha="left", color=INK2)
    out = FIG / "roughness_texture_histories.png"
    fig.savefig(out, dpi=200, facecolor="white")
    plt.close(fig)
    return out


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-logs", action="store_true", help="do not read the solver logs")
    a = ap.parse_args()
    tab = pd.read_csv(TABLE)
    assert len(tab) == 69, len(tab)
    runs, blocks, logs, series = [], [], [], {}
    for _, row in tab.iterrows():
        r, B, Lb, s = analyse(row, not a.no_logs)
        runs.append(r)
        blocks.append(B)
        if len(Lb):
            logs.append(Lb)
        series[row["name"]] = s
        print(f"{row['name']:46s} win {r['Cd_win']:.4f} (table {r['Cd_win_table']:.4f}) drift {r['Cd_drift_recalc']:+.4f} "
              f"jmax {r['jump_max_win']:.3g} jumps {r['jump_bins_win_0.5']:2d} noise_end {r['noise_end']:.0f} "
              f"30-80 {r['Cd_30_80']:.4f} 100-150 {r['Cd_100_150']:.4f} slope {r['end_slope_per100']:+.4f}"
              + (f" state {r['state_win']}" if r["alpha"] == 0 else ""))
    R = pd.DataFrame(runs)
    OUT.mkdir(exist_ok=True)
    R.to_csv(OUT / "roughness_histories_runs.csv", index=False, float_format="%.6g")
    pd.concat(blocks).to_csv(OUT / "roughness_histories_blocks.csv", index=False, float_format="%.6g")
    if logs:
        pd.concat(logs).to_csv(OUT / "roughness_log_blocks.csv", index=False, float_format="%.6g")
    # checks against the table (every recomputed window mean and drift must match)
    worst = float(R.table_check_absdiff.max())
    assert worst < 1e-9, worst
    tex25 = R[(R.wall == "tex") & (R.maxCo == 2.5)]
    nums = dict(
        n_runs=len(R), table_check_max_absdiff=worst,
        jumps_win_0p5={n: int(v) for n, v in R.set_index("name")["jump_bins_win_0.5"].items() if v > 0},
        jump_max_win_by_group={
            "wf alpha 180 maxCo 5": [float(R[(R.wall == "wf") & (R.alpha == 180) & (R.maxCo == 5)].jump_max_win.min()),
                                     float(R[(R.wall == "wf") & (R.alpha == 180) & (R.maxCo == 5)].jump_max_win.max())],
            "wf alpha 180 maxCo 2.5": [float(R[(R.wall == "wf") & (R.alpha == 180) & (R.maxCo == 2.5)].jump_max_win.min()),
                                       float(R[(R.wall == "wf") & (R.alpha == 180) & (R.maxCo == 2.5)].jump_max_win.max())],
            "wf alpha 90": [float(R[(R.wall == "wf") & (R.alpha == 90)].jump_max_win.min()),
                            float(R[(R.wall == "wf") & (R.alpha == 90)].jump_max_win.max())],
            "wf alpha 0": [float(R[(R.wall == "wf") & (R.alpha == 0)].jump_max_win.min()),
                           float(R[(R.wall == "wf") & (R.alpha == 0)].jump_max_win.max())],
            "tex": [float(R[R.wall == "tex"].jump_max_win.min()), float(R[R.wall == "tex"].jump_max_win.max())],
        },
        runs_over_0p2={n: float(v) for n, v in R.set_index("name").jump_max_win.items() if v > 0.2},
        runs_over_0p1={n: float(v) for n, v in R.set_index("name").jump_max_win.items() if v > 0.1},
        noise_end_tex25={n: float(v) for n, v in tex25.set_index("name").noise_end.items()},
        alpha0_states={n: dict(state_win=s, high_share=float(h), last_cross=float(c), high_from=float(f),
                               high_to=float(tt), end=e)
                       for n, s, h, c, f, tt, e in zip(R[R.alpha == 0].name, R[R.alpha == 0].state_win,
                                                       R[R.alpha == 0].state_high_share_win,
                                                       R[R.alpha == 0].state_last_cross, R[R.alpha == 0].high_from,
                                                       R[R.alpha == 0].high_to, R[R.alpha == 0].state_end)},
    )
    if logs:
        nums["log"] = {n: dict(pres_noisy_max=float(p1), pres_last50_max=float(p2), dt_min_rel=float(dm))
                       for n, p1, p2, dm in zip(tex25.name, R.loc[tex25.index, "log_pres_median_noisy_max"],
                                                R.loc[tex25.index, "log_pres_median_last50_max"],
                                                R.loc[tex25.index, "log_dt_min_over_last50_mean"])}
    (OUT / "roughness_histories.json").write_text(json.dumps(nums, indent=1, default=float))
    print(json.dumps(nums, indent=1, default=float))
    print("wrote", figure(series, R))


if __name__ == "__main__":
    main()
