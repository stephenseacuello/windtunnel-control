#!/usr/bin/env python3
"""Figures for the Stage 1 (smooth blade section) analysis of 15 Oct 2026.

    nice -n 10 python3 cfd/analysis/2026-10-15/src/section_figures.py   # after section_analysis.py

Adapted from cfd/analysis/2026-10-13/src/section_figures.py. Reads the table through section_lib
and ../out/section_*.csv / .json; writes ../fig/ (200 dpi, 3.4 in wide = half a page):
  section_health.png             the 13 Oct flag on all 125 runs: proxy, force symptoms, jumps, residuals
  section_timestep.png           Cd, Cl, St against maxCo (5 / 2.5 / 1.25), alpha 0 and 180, SST and LM
  section_polar.png              the LM polar at 23 m/s from healthy runs, maxCo per point, alpha-0 states
  section_transition_lm_sst.png  Cd and Cl against alpha (150-210), LM against SST, per speed
  section_transition_tu.png      Cd and Cl against alpha, LM at Tu 0.5 / 1 / 3 % and SST, per speed
  section_transition_a180.png    alpha 180: Cd, tip-B separation and base pressure against speed
(section_timestep_histories.png is written by section_histories.py.)
Encoding (13 Oct, extended): smooth blade black; LM circle, solid line; SST square, dashed line;
maxCo 5 open, 2.5 filled, 1.25 half-filled; flagged run grey x; Tu 0.5 / 1 / 3 % (LM) a violet
ramp light to dark with dotted / solid / dash-dot lines. Bars are +-|drift| of each run, so two
bars that do not overlap mark a change larger than its noise (the 13 Oct rule). A grey ring marks a run whose
first pressure solve starts above 0.05 in more than half of its window's steps (all three transition figures
and, since the review of 19 Oct, the polar); a run with jumps in more than half of its window is an open
circle with x and is never joined by a line.
"""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import NullFormatter  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import section_lib as L  # noqa: E402

BLACK, GREY = L.BLACK, L.GREY
TT_ALPHA = (150, 165, 180, 195, 210)
TT_U = (10.2, 23.0, 38.0)


def mk(model, maxco, corrupted=False, **kw):
    st = L.mstyle(model, maxco, corrupted)
    st.update(kw)
    return st


def load():
    d = L.load().set_index("name", drop=False)
    q = pd.read_csv(L.OUT / "section_case_quality.csv").set_index("name")
    for c in ("jumps", "nojump_share", "Cd_nj", "Cd_drift_nj", "Cd_last10", "pres_share_win", "jump_max_win"):
        d[c] = q.loc[d.index, c]
    return d


RING = dict(ls="none", marker="o", ms=8.0, mfc="none", mec="#9a9a9a", mew=0.6, zorder=1.5)


def residual_ring(ax, x, y, share):
    """Grey ring: in more than half of the window's time steps the first pressure solve starts with an
    initial residual above 0.05 (the solver signature of the flagged runs)."""
    if np.isfinite(share) and share >= 0.5:
        ax.plot([x], [y], **RING)


def drift_bar(ax, x, y, dr, color=BLACK, z=3):
    ax.errorbar([x], [y], yerr=[abs(dr)], ls="none", ecolor=color, elinewidth=0.6, capsize=1.4, zorder=z)


def nojump_tick(ax, x, y, ynj, color=BLACK):
    """Thin line from the window mean to the window mean without jump intervals (small diamond)."""
    if np.isfinite(ynj) and abs(ynj - y) > 1e-9:
        ax.plot([x, x], [y, ynj], color=color, lw=0.5, zorder=2)
        ax.plot([x], [ynj], ls="none", marker="D", ms=2.2, mfc="white", mec=color, mew=0.6, zorder=4)


# ------------------------------------------------------------------ 1. health
def fig_health(d):
    fig, axs = plt.subplots(3, 1, figsize=(3.4, 6.5), gridspec_kw=dict(hspace=0.5))
    old_h = d[~d.new_15oct & ~d.corrupted].u_co_over_U.max()
    old_f = d[~d.new_15oct & d.corrupted].u_co_over_U.min()

    def marker_for(r):
        if r.neg_drag:
            return dict(marker="v", ms=4.5, color=GREY, mec=GREY, mfc=GREY, mew=0.9)
        return mk(r.model, r.maxCo, r.corrupted)

    ax = axs[0]
    ax.axhspan(old_h, old_f, color="#efefef", lw=0, zorder=0)
    for r in d.itertuples():
        off = {10.2: -4, 23.0: 0, 38.0: 4}[r.U_ms] if r.alpha_deg in TT_ALPHA else \
            ({"coarse": -4, "medium": 0, "fine": 4}[r.level] if r.alpha_deg in (0, 90, 180) else 0)
        ax.plot([r.alpha_deg + off], [r.u_co_over_U], ls="none", zorder=3, **marker_for(r))
        if r.symptom_without_flag:
            ax.plot([r.alpha_deg + off], [r.u_co_over_U], ls="none", marker="o", ms=8.5, mfc="none", mec=BLACK,
                    mew=0.6, zorder=4)
    ax.axhline(L.U_CO_LIMIT, color=BLACK, lw=0.7, ls=":")
    ax.set_yscale("log")
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.set_ylim(0.9, 50)
    ax.set_yticks([1, 2, 5, 10, 20, 50])
    ax.set_yticklabels(["1", "2", "5", "10", "20", "50"])
    ax.set_xticks(np.arange(0, 361, 45))
    ax.set_xlim(-12, 357)
    ax.set_xlabel("angle of attack α (deg)")
    ax.set_ylabel("time-step proxy $u_{Co}/U$")
    ax.annotate("limit 5 (flag)", (352, L.U_CO_LIMIT), xytext=(0, 2), textcoords="offset points", ha="right",
                fontsize=6, va="bottom")
    ax.set_title("(a) the 13 Oct flag: no new run is above the limit", loc="left", fontsize=7)

    ax = axs[1]
    ax.axvspan(old_h, old_f, color="#efefef", lw=0, zorder=0)
    for r in d.itertuples():
        ax.plot([r.u_co_over_U], [r.Cd_relstd], ls="none", zorder=3, **marker_for(r))
        if r.symptom_without_flag:
            ax.plot([r.u_co_over_U], [r.Cd_relstd], ls="none", marker="o", ms=8.5, mfc="none", mec=BLACK, mew=0.6,
                    zorder=4)
    ax.axvline(L.U_CO_LIMIT, color=BLACK, lw=0.7, ls=":")
    ax.axhline(1.0, color="#bdbdbd", lw=0.6)
    ax.set_xscale("log")
    ax.set_yscale("log")
    for a_ in (ax.xaxis, ax.yaxis):
        a_.set_minor_formatter(NullFormatter())
    ax.set_xlim(0.9, 50)
    ax.set_xticks([1, 2, 5, 10, 20, 50])
    ax.set_xticklabels(["1", "2", "5", "10", "20", "50"])
    ax.set_ylim(1e-5, 200)
    ax.set_yticks([1e-4, 1e-2, 1, 100])
    ax.set_xlabel("time-step proxy $u_{Co}/U$")
    ax.set_ylabel("$C_{d,std}\\ /\\ |C_{d,mean}|$")
    # review 19 Oct: label moved 5 pt lower, clear of the flagged run at proxy 25.0 (std/mean 0.75)
    ax.annotate("std = mean", (48, 1.0), xytext=(0, -7), textcoords="offset points", fontsize=6, va="top",
                ha="right", color="#555555")
    n_sym = int(d.symptom_without_flag.sum())
    ax.set_title(f"(b) force symptom: {n_sym} healthy runs (circled) have std > mean", loc="left", fontsize=7)

    ax = axs[2]
    ax.axvspan(old_h, old_f, color="#efefef", lw=0, zorder=0)
    for r in d.itertuples():
        y = r.jumps
        ax.plot([r.u_co_over_U], [y + 0.0], ls="none", zorder=3, **marker_for(r))
        if r.symptom_without_flag:
            ax.plot([r.u_co_over_U], [y], ls="none", marker="o", ms=8.5, mfc="none", mec=BLACK, mew=0.6, zorder=4)
    ax.axvline(L.U_CO_LIMIT, color=BLACK, lw=0.7, ls=":")
    ax.axhline(50, color="#bdbdbd", lw=0.6)
    ax.annotate("half the window", (0.95, 50), xytext=(0, 2), textcoords="offset points", fontsize=6, va="bottom",
                color="#555555")
    ax.set_xscale("log")
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.set_xlim(0.9, 50)
    ax.set_xticks([1, 2, 5, 10, 20, 50])
    ax.set_xticklabels(["1", "2", "5", "10", "20", "50"])
    ax.set_ylim(-4, 104)
    ax.set_xlabel("time-step proxy $u_{Co}/U$")
    ax.set_ylabel("window c/U with a $C_d$ jump > 0.5")
    nj = int(((d.jumps > 0) & ~d.corrupted).sum())
    ax.set_title(f"(c) force jumps: {nj} of {int((~d.corrupted).sum())} healthy runs have jumps", loc="left",
                 fontsize=7)
    h = [Line2D([], [], ls="none", **mk("LM", 5)), Line2D([], [], ls="none", **mk("LM", 2.5)),
         Line2D([], [], ls="none", **mk("LM", 1.25)), Line2D([], [], ls="none", **mk("SST", 5)),
         Line2D([], [], ls="none", **mk("SST", 2.5)), Line2D([], [], ls="none", **mk("SST", 1.25)),
         Line2D([], [], ls="none", **mk("LM", 5, True)),
         Line2D([], [], ls="none", marker="v", ms=4.5, color=GREY, mfc=GREY),
         Line2D([], [], ls="none", marker="o", ms=8.5, mfc="none", mec=BLACK, mew=0.6)]
    fig.legend(h, ["LM, maxCo 5", "LM, maxCo 2.5", "LM, maxCo 1.25", "SST, maxCo 5", "SST, maxCo 2.5",
                   "SST, maxCo 1.25", "flagged run", "flagged, mean $C_d$ < 0", "healthy with a symptom"],
               loc="upper center", ncol=3, bbox_to_anchor=(0.54, 1.0), handlelength=1.2, columnspacing=0.7,
               fontsize=6)
    fig.text(0.54, 0.908, "all 125 runs; grey band: the empty gap of 13 Oct (4.48–6.27);\n"
             "in (a), α 150–210 at 10.2 / 23 / 38 m/s drawn 4° apart", ha="center", va="top", fontsize=6,
             color=L.NOTE)
    fig.subplots_adjust(left=0.17, right=0.97, top=0.835, bottom=0.065)
    L.save(fig, "section_health.png")


# ------------------------------------------------------------------ 2. time step
def fig_timestep(d, TS):
    fig, axs = plt.subplots(3, 2, figsize=(3.4, 4.9), sharex=True, gridspec_kw=dict(hspace=0.16, wspace=0.42))
    X = {5.0: 2.0, 2.5: 1.0, 1.25: 0.0}
    off = {"SST": -0.09, "LM": 0.09}
    good0 = d[(d.alpha_deg == 0) & ~d.corrupted & ~d.new_15oct]
    for j, a in enumerate((0, 180)):
        for i, q in enumerate(("Cd", "Cl", "St")):
            ax = axs[i, j]
            if a == 0 and q == "Cd":
                # second review, 19 Oct: the bands are the 13 Oct ranges of the two states (the state itself
                # is Cd above or below 2.5; LM at maxCo 1.25 ends below the 13 Oct low-drag range)
                for b, txt in (("high-drag", "high-drag (13 Oct)"), ("low-drag", "low-drag (13 Oct)")):
                    g = good0[good0.branch_a0 == b].Cd_mean
                    ax.axhspan(g.min(), g.max(), color="#efefef", zorder=0, lw=0)
                    xy = (0.85, 3.1) if b == "high-drag" else (2.5, 1.56)
                    ax.annotate(txt.replace("\n", " "), xy, fontsize=5.4, color="#555555", va="center",
                                ha="center" if b == "high-drag" else "right")
            steady_at = {}
            for mdl in ("SST", "LM"):
                g = TS[(TS.alpha == a) & (TS.model == mdl)].sort_values("maxCo")
                xs, ys, cos = [], [], []
                for r in g.itertuples():
                    x = X[r.maxCo] + off[mdl]
                    if r.flagged:
                        if q == "Cd":
                            ax.plot([x], [r.Cd], ls="none", **mk(mdl, r.maxCo, True))
                        continue
                    if q == "St":
                        # no shedding at the end of the window: lift std over the last 10 c/U below 0.001
                        if r.Cl_std_last10 < 1e-3:
                            steady_at.setdefault(r.maxCo, []).append(mdl)
                            continue
                        y = r.St
                    elif q == "Cd":
                        y = r.Cd
                        drift_bar(ax, x, y, r.Cd_drift)
                        nojump_tick(ax, x, y, r.Cd_nj)
                    else:
                        y = r.Cl
                    ax.plot([x], [y], ls="none", zorder=4, **mk(mdl, r.maxCo))
                    xs.append(x)
                    ys.append(y)
                    cos.append(r.maxCo)
                    # the alpha-0 runs at maxCo 1.25 are not stationary: show where the last 10 c/U sit
                    if a == 0 and r.maxCo == 1.25 and q in ("Cd", "Cl"):
                        yl = r.Cd_last10 if q == "Cd" else r.Cl_last10
                        xa = x + (-0.17 if mdl == "SST" else 0.17)
                        ax.annotate("", (xa, yl), xytext=(xa, y),
                                    arrowprops=dict(arrowstyle="-|>", lw=0.6, color=BLACK, mutation_scale=5))
                        ax.plot([xa], [yl], ls="none", marker="_", ms=5, mew=1.0, color=BLACK, zorder=4)
                # join only neighbouring time steps (a factor of 2 apart)
                for k in range(len(xs) - 1):
                    if abs(cos[k + 1] / cos[k] - 2.0) < 1e-9:
                        ax.plot(xs[k:k + 2], ys[k:k + 2], L.MODEL_LS[mdl], color=BLACK, lw=0.8, zorder=2)
            for co, mdls in steady_at.items():
                txt = "steady" if len(mdls) == 1 else "both steady"
                xx = X[co] + (off[mdls[0]] if len(mdls) == 1 else 0.14)
                ax.annotate(f"{txt}\n({', '.join(mdls)})", (xx, 0.0), xytext=(0, 3), textcoords="offset points",
                            fontsize=5.2, ha="center", va="bottom", color="#555555", annotation_clip=False)
            ax.set_xlim(-0.45, 2.55)
            ax.set_xticks([0, 1, 2])
            ax.set_xticklabels(["1.25", "2.5", "5"])
            ax.grid(axis="x", visible=False)
            lab = {"Cd": "$C_d$", "Cl": "$C_l$", "St": "St"}[q]
            ax.set_ylabel(f"{lab}, α = {a}°")
            if q == "St":
                ax.set_ylim(0.0, 0.26)
                ax.set_xlabel("maxCo")
            if a == 180 and q == "Cd":
                ax.set_ylim(0.4, 1.75)
                ax.annotate("flagged runs\nat maxCo 5", (2.0, 0.93), fontsize=5.4, ha="center", va="center",
                            color="#555555")
            if a == 0 and q == "Cd":
                ax.set_ylim(1.4, 3.75)
    h = [Line2D([], [], lw=0.8, ls="--", **{k: v for k, v in mk("SST", 2.5).items()}),
         Line2D([], [], lw=0.8, ls="-", **{k: v for k, v in mk("LM", 2.5).items()}),
         Line2D([], [], ls="none", **mk("LM", 5, True)),
         Line2D([], [], ls="none", marker="D", ms=2.2, mfc="white", mec=BLACK, mew=0.6),
         Line2D([], [], ls="none", marker="_", ms=5, mew=1.0, color=BLACK)]
    fig.legend(h, ["SST", "LM", "flagged run", "mean without jump intervals", "last 10 c/U (arrow: from window)"],
               loc="upper center", ncol=2, bbox_to_anchor=(0.53, 1.0), handlelength=2.0, columnspacing=0.9,
               fontsize=6)
    fig.text(0.53, 0.905, "medium mesh, 23 m/s, Tu 1 %; window 50–150 c/U; bars ±|drift|; maxCo 5 open,\n"
             "2.5 filled, 1.25 half-filled; 'steady': lift std < 0.001 over the last 10 c/U", ha="center",
             va="top", fontsize=6, color=L.NOTE)
    fig.subplots_adjust(left=0.15, right=0.98, top=0.855, bottom=0.085)
    L.save(fig, "section_timestep.png")


# ------------------------------------------------------------------ 3. polar
def segments(alpha, ok, step=15):
    runs, cur = [], []
    for i, (a, o) in enumerate(zip(alpha, ok)):
        if o and cur and abs(a - alpha[cur[-1]] - step) < 1e-6:
            cur.append(i)
        else:
            if len(cur) > 1:
                runs.append(cur)
            cur = [i] if o else []
    if len(cur) > 1:
        runs.append(cur)
    return runs


def fig_polar(d, pol):
    """LM only (the SST alpha-0 and 180 runs are in section_timestep.png and the transition figures)."""
    hp = pol[pol.used].copy()
    a0 = hp[hp.alpha_deg == 0].copy()
    a0["alpha_deg"] = 360.0
    hp = pd.concat([hp, a0], ignore_index=True)
    fig, axs = plt.subplots(3, 1, figsize=(3.4, 5.9), sharex=True, gridspec_kw=dict(hspace=0.12))
    ylab = {"Cd_mean": "drag coefficient $C_d$", "Cl_mean": "lift coefficient $C_l$",
            "Cm_mean": "moment coefficient $C_m$"}
    lims = {"Cd_mean": (-0.1, 3.4), "Cl_mean": (-3.1, 2.1), "Cm_mean": (-0.75, 0.75)}
    lm_off = {5.0: 0.0, 2.5: 0.0, 1.25: 5.0}
    for ax, q in zip(axs, ("Cd_mean", "Cl_mean", "Cm_mean")):
        for co in (5.0, 2.5):
            g = hp[hp.maxCo == co].sort_values("alpha_deg")
            al = g.alpha_deg.to_numpy()
            for seg in segments(al, np.ones(len(al), bool)):
                ax.plot(al[seg], g[q].to_numpy()[seg], "-", color=BLACK, lw=0.9, zorder=2)
        for r in hp.itertuples():
            ax.plot([r.alpha_deg + lm_off[r.maxCo]], [getattr(r, q)], ls="none", zorder=3, **mk("LM", r.maxCo))
            # review 19 Oct: the residual signature is marked here as in the transition figures
            # (alpha 15 and 30 at maxCo 5, 195 and 210 at maxCo 2.5)
            residual_ring(ax, r.alpha_deg + lm_off[r.maxCo], getattr(r, q), r.pres_share_win)
        ax.axhline(0, color="#bdbdbd", lw=0.6, zorder=1)
        ax.set_ylim(*lims[q])
        ax.set_ylabel(ylab[q])
        # daggers: window mean not stationary (|drift| > 20 % of the mean)
        for r in hp[hp.not_stationary & (hp.alpha_deg < 360)].itertuples():
            ax.annotate("†", (r.alpha_deg + lm_off[r.maxCo], getattr(r, q)), xytext=(2.5, 2.5),
                        textcoords="offset points", fontsize=7, ha="left", va="bottom")
    # review 19 Oct: the star is an outline (no white fill), so it no longer hides the maxCo-1.25 point
    # at alpha 180 (Cd 1.116, drawn at 185 deg) that lies under it
    axs[0].plot([0, 180], [L.LIT_CD_CONCAVE, L.LIT_CD_CONVEX], ls="none", marker="*", ms=7.5, mfc="none",
                mec=L.LIT, mew=0.9, zorder=5)
    r0 = hp[(hp.alpha_deg == 0) & (hp.maxCo == 5.0)].iloc[0]
    r1 = hp[(hp.alpha_deg == 0) & (hp.maxCo == 1.25)].iloc[0]
    axs[0].annotate(f"α 0: low-drag state at maxCo 5 ({r0.Cd_mean:.3f}) and\n"
                    f"1.25 ({r1.Cd_mean:.3f}, still falling: {r1.Cd_last10:.3f} over the last 10 c/U)",
                    (2, 2.02), xytext=(10, 3.0), textcoords="data", fontsize=5.6, color=L.NOTE, va="center",
                    arrowprops=dict(arrowstyle="-", lw=0.5, color="#777777"))
    r2 = hp[(hp.alpha_deg == 180) & (hp.maxCo == 2.5)].iloc[0]
    r3 = hp[(hp.alpha_deg == 180) & (hp.maxCo == 1.25)].iloc[0]
    axs[0].annotate(f"α 180: {r2.Cd_mean:.3f} (2.5), {r3.Cd_mean:.3f} (1.25)", (184, 1.12), xytext=(196, 2.05),
                    textcoords="data", fontsize=5.6, color=L.NOTE, va="center",
                    arrowprops=dict(arrowstyle="-", lw=0.5, color="#777777"))
    axs[2].set_xlabel("angle of attack α (deg)")
    axs[2].set_xticks(np.arange(0, 361, 45))
    axs[2].set_xticks(np.arange(0, 361, 15), minor=True)
    axs[2].set_xlim(-10, 370)
    h = [Line2D([], [], lw=0.9, **mk("LM", 5)), Line2D([], [], lw=0.9, **mk("LM", 2.5)),
         Line2D([], [], ls="none", **mk("LM", 1.25)),
         Line2D([], [], ls="none", marker="*", ms=7.5, mfc="white", mec=L.LIT, mew=0.9)]
    fig.legend(h, ["LM, maxCo 5", "LM, maxCo 2.5", "LM, maxCo 1.25 (drawn 5° right)",
                   "literature, 2D half-cylinder shell"], loc="upper center", ncol=2,
               bbox_to_anchor=(0.55, 1.0), columnspacing=1.0, handlelength=2.0, fontsize=6)
    fig.text(0.56, 0.925, "LM, 23 m/s, Tu 1 %, medium mesh, healthy runs only; α 360 repeats α 0;\n"
             "lines join neighbours 15° apart at the same maxCo; † window mean not stationary\n"
             "(|drift| > 20 % of the mean); grey ring: p residual > 0.05 in > 50 % of steps",
             ha="center", va="top", fontsize=5.8, color=L.NOTE, linespacing=1.15)
    fig.subplots_adjust(left=0.17, right=0.97, top=0.855, bottom=0.07)
    L.save(fig, "section_polar.png")


# ------------------------------------------------------------------ 4. transition test, LM against SST
def fig_transition_lm_sst(d):
    t2 = d[(d.level == "medium") & (d.maxCo == 2.5) & d.alpha_deg.isin(TT_ALPHA) & (d.Tu_body_pct == 1.0)]
    fig, axs = plt.subplots(3, 2, figsize=(3.4, 4.9), sharex=True, gridspec_kw=dict(hspace=0.3, wspace=0.42))
    off = {"SST": -1.6, "LM": 1.6}
    for i, U in enumerate(TT_U):
        for j, q in enumerate(("Cd_mean", "Cl_mean")):
            ax = axs[i, j]
            for mdl in ("SST", "LM"):
                g = t2[(t2.U_ms == U) & (t2.model == mdl)].sort_values("alpha_deg")
                x = g.alpha_deg.to_numpy() + off[mdl]
                y = g[q].to_numpy()
                ax.plot(x, y, L.MODEL_LS[mdl], color=BLACK, lw=0.8, zorder=2)
                for xi, r in zip(x, g.itertuples()):
                    dr = r.Cd_drift if q == "Cd_mean" else r.Cl_drift
                    drift_bar(ax, xi, getattr(r, q), dr)
                    if q == "Cd_mean":
                        nojump_tick(ax, xi, r.Cd_mean, r.Cd_nj)
                    residual_ring(ax, xi, getattr(r, q), r.pres_share_win)
                    ax.plot([xi], [getattr(r, q)], ls="none", zorder=4, **mk(mdl, 2.5))
            if U == 23.0:   # the maxCo 1.25 pair at alpha 180
                for mdl in ("SST", "LM"):
                    r = L.one(d, alpha_deg=180, U_ms=23.0, model=mdl, level="medium", maxCo=1.25)
                    xi = 180 + off[mdl] * 3.2
                    ax.plot([xi], [r[q]], ls="none", zorder=4, **mk(mdl, 1.25))
            ax.set_xlim(141, 219)
            ax.set_xticks(TT_ALPHA)
            ax.set_ylim(*((0.3, 2.3) if q == "Cd_mean" else (-1.45, 0.1)))
            ax.set_ylabel(("$C_d$" if q == "Cd_mean" else "$C_l$") + f", {U:g} m/s")
            if i == 2:
                ax.set_xlabel("α (deg)")
    h = [Line2D([], [], lw=0.8, ls="--", **mk("SST", 2.5)), Line2D([], [], lw=0.8, ls="-", **mk("LM", 2.5)),
         Line2D([], [], ls="none", **mk("SST", 1.25)), Line2D([], [], ls="none", **mk("LM", 1.25)),
         Line2D([], [], ls="none", marker="D", ms=2.2, mfc="white", mec=BLACK, mew=0.6),
         Line2D([], [], **RING)]
    fig.legend(h, ["SST, maxCo 2.5", "LM, maxCo 2.5", "SST, maxCo 1.25", "LM, maxCo 1.25 (α 180)",
                   "$C_d$ without jump intervals", "pressure residual > 0.05 in > 50 % of steps"],
               loc="upper center", ncol=2, bbox_to_anchor=(0.53, 1.0), handlelength=2.0, columnspacing=0.9,
               fontsize=6)
    fig.text(0.53, 0.893, "medium mesh, Tu 1 %, window 50–150 c/U; bars ±|drift|;\n"
             "SST drawn 1.6° left, LM 1.6° right; maxCo-1.25 pair 5° either side of 180°",
             ha="center", va="top", fontsize=5.8, color=L.NOTE)
    fig.subplots_adjust(left=0.15, right=0.98, top=0.835, bottom=0.085)
    L.save(fig, "section_transition_lm_sst.png")


# ------------------------------------------------------------------ 5. transition test, Tu
def fig_transition_tu(d):
    t2 = d[(d.level == "medium") & (d.maxCo == 2.5) & d.alpha_deg.isin(TT_ALPHA)]
    fig, axs = plt.subplots(3, 2, figsize=(3.4, 4.9), sharex=True, gridspec_kw=dict(hspace=0.3, wspace=0.42))
    off = {0.5: -2.4, 1.0: 0.0, 3.0: 2.4}
    for i, U in enumerate(TT_U):
        for j, q in enumerate(("Cd_mean", "Cl_mean")):
            ax = axs[i, j]
            s = t2[(t2.U_ms == U) & (t2.model == "SST")].sort_values("alpha_deg")
            ax.plot(s.alpha_deg, s[q], "--", color=BLACK, lw=0.7, zorder=2)
            ax.plot(s.alpha_deg, s[q], ls="none", zorder=3, **mk("SST", 2.5, ms=3.6))
            for r in s.itertuples():
                residual_ring(ax, r.alpha_deg, getattr(r, q), r.pres_share_win)
            for tu in (0.5, 1.0, 3.0):
                g = t2[(t2.U_ms == U) & (t2.model == "LM") & (t2.Tu_body_pct == tu)].sort_values("alpha_deg")
                ok = (g.nojump_share >= 0.5).to_numpy()
                x = g.alpha_deg.to_numpy() + off[tu]
                y = g[q].to_numpy()
                c = L.TU_COLOR[tu]
                idx = np.flatnonzero(ok)
                for i0, i1 in zip(idx[:-1], idx[1:]):
                    if i1 == i0 + 1:
                        ax.plot(x[[i0, i1]], y[[i0, i1]], L.TU_LS[tu], color=c, lw=1.0, zorder=2)
                for k, r in enumerate(g.itertuples()):
                    residual_ring(ax, x[k], y[k], r.pres_share_win)
                    if ok[k]:
                        dr = r.Cd_drift if q == "Cd_mean" else r.Cl_drift
                        drift_bar(ax, x[k], y[k], dr, color=c)
                        ax.plot([x[k]], [y[k]], ls="none", zorder=4, marker="o", ms=4.0, mfc=c, mec=c, mew=0.8)
                    else:
                        ax.plot([x[k]], [y[k]], ls="none", zorder=4, marker="o", ms=4.0, mfc="white", mec=c,
                                mew=0.8)
                        ax.plot([x[k]], [y[k]], ls="none", zorder=5, marker="x", ms=3.0, mec=c, mew=0.7)
            ax.set_xlim(141, 219)
            ax.set_xticks(TT_ALPHA)
            ax.set_ylim(*((0.3, 2.3) if q == "Cd_mean" else (-1.45, 0.1)))
            ax.set_ylabel(("$C_d$" if q == "Cd_mean" else "$C_l$") + f", {U:g} m/s")
            if i == 2:
                ax.set_xlabel("α (deg)")
    h = [Line2D([], [], color=L.TU_COLOR[tu], ls=L.TU_LS[tu], lw=1.0, marker="o", ms=4.0, mfc=L.TU_COLOR[tu],
                mec=L.TU_COLOR[tu]) for tu in (0.5, 1.0, 3.0)]
    h += [Line2D([], [], lw=0.7, ls="--", **mk("SST", 2.5, ms=3.6)),
          (Line2D([], [], ls="none", marker="o", ms=4.0, mfc="white", mec=L.TU_COLOR[0.5], mew=0.8),
           Line2D([], [], ls="none", marker="x", ms=3.0, mec=L.TU_COLOR[0.5], mew=0.7))]
    h += [Line2D([], [], **RING)]
    fig.legend(h, ["LM, Tu 0.5 %", "LM, Tu 1 %", "LM, Tu 3 %", "SST, Tu 1 %", "jumps in > 50 % of window",
                   "p residual > 0.05 in > 50 % of steps"],
               loc="upper center", ncol=2, bbox_to_anchor=(0.53, 1.0), handlelength=2.2, columnspacing=0.8,
               fontsize=6)
    fig.text(0.53, 0.893, "medium mesh, maxCo 2.5, window 50–150 c/U; bars ±|drift|;\n"
             "Tu 0.5 % drawn 2.4° left, 3 % 2.4° right", ha="center", va="top", fontsize=5.8, color=L.NOTE)
    fig.subplots_adjust(left=0.15, right=0.98, top=0.835, bottom=0.085)
    L.save(fig, "section_transition_tu.png")


# ------------------------------------------------------------------ 6. alpha 180 summary
def fig_transition_a180(d, srf):
    s = srf[srf.alpha_deg == 180]
    fig, axs = plt.subplots(3, 1, figsize=(3.4, 5.0), sharex=True, gridspec_kw=dict(hspace=0.14))
    xU = {10.2: 0, 23.0: 1, 38.0: 2}
    off = {("LM", 0.5): -0.15, ("LM", 1.0): -0.05, ("LM", 3.0): 0.05, ("SST", 1.0): 0.15}
    for ax, q, lab in zip(axs, ("Cd_mean", "s_sep_B", "Cp_base"),
                          ("$C_d$ at α = 180°", "tip-B separation s/c", "base $C_p$ (concave side)")):
        for (mdl, tu), o in off.items():
            g = s[(s.model == mdl) & (s.Tu_body_pct == tu) & (s.maxCo == 2.5)].sort_values("U_ms")
            x = g.U_ms.map(xU).to_numpy() + o
            y = g[q].to_numpy()
            nj = d.loc[g.name, "nojump_share"].to_numpy() >= 0.5
            shares = d.loc[g.name, "pres_share_win"].to_numpy()
            for xi, yi, sh in zip(x, y, shares):
                residual_ring(ax, xi, yi, sh)
            if mdl == "SST":
                ax.plot(x, y, "--", color=BLACK, lw=0.8, zorder=2)
                ax.plot(x, y, ls="none", zorder=3, **mk("SST", 2.5))
            else:
                c = L.TU_COLOR[tu]
                # review 19 Oct: lines join only neighbouring speeds whose runs are both usable (jump-free
                # share >= 0.5), as in section_transition_tu.png; an unusable run is never part of a trend
                for k in range(len(x) - 1):
                    if nj[k] and nj[k + 1]:
                        ax.plot(x[k:k + 2], y[k:k + 2], L.TU_LS[tu], color=c, lw=1.0, zorder=2)
                for xi, yi, ok in zip(x, y, nj):
                    if ok:
                        ax.plot([xi], [yi], ls="none", marker="o", ms=4.0, mfc=c, mec=c, mew=0.8, zorder=4)
                    else:
                        ax.plot([xi], [yi], ls="none", marker="o", ms=4.0, mfc="white", mec=c, mew=0.8, zorder=4)
                        ax.plot([xi], [yi], ls="none", marker="x", ms=3.0, mec=c, mew=0.7, zorder=5)
        # second review, 19 Oct: the maxCo-1.25 pair is drawn right of the 23 m/s group (SST at 1.20, LM at
        # 1.28); at x = 1.05 the LM marker sat on LM Tu 3 % (maxCo 2.5, x = 1.05) and hid it in the base-Cp
        # panel (-0.824 against -0.829); these positions keep both clear of the Tu 3 % line
        for mdl, xm in (("LM", 1.28), ("SST", 1.20)):
            g = s[(s.model == mdl) & (s.maxCo == 1.25)]
            for r in g.itertuples():
                ax.plot([xm], [getattr(r, q)], ls="none", zorder=4, **mk(mdl, 1.25))
        ax.set_ylabel(lab)
        ax.grid(axis="x", visible=False)
    axs[1].invert_yaxis()
    axs[1].annotate("later separation ↓", (-0.35, 1.362), fontsize=5.6, ha="left", va="center", color="#555555")
    axs[2].invert_yaxis()
    axs[2].annotate("higher base pressure ↓", (2.45, -0.85), fontsize=5.6, ha="right", va="center", color="#555555")
    axs[2].set_xticks([0, 1, 2])
    axs[2].set_xticklabels(["10.2", "23", "38"])
    axs[2].set_xlim(-0.4, 2.5)
    axs[2].set_xlabel("U (m/s)")
    h = [Line2D([], [], color=L.TU_COLOR[tu], ls=L.TU_LS[tu], lw=1.0, marker="o", ms=4.0, mfc=L.TU_COLOR[tu],
                mec=L.TU_COLOR[tu]) for tu in (0.5, 1.0, 3.0)]
    h += [Line2D([], [], lw=0.8, ls="--", **mk("SST", 2.5)), Line2D([], [], ls="none", **mk("LM", 1.25)),
          Line2D([], [], ls="none", **mk("SST", 1.25))]
    fig.legend(h, ["LM, Tu 0.5 %", "LM, Tu 1 %", "LM, Tu 3 %", "SST, Tu 1 %", "LM, maxCo 1.25", "SST, maxCo 1.25"],
               loc="upper center", ncol=3, bbox_to_anchor=(0.54, 1.0), handlelength=2.2, columnspacing=0.8,
               fontsize=6)
    fig.text(0.54, 0.915, "medium mesh, maxCo 2.5 unless marked (maxCo-1.25 pair drawn right of 23 m/s);\n"
             "time-mean wall values from the records; open circle with x: jumps in > 50 %\n"
             "of the window (not joined); grey ring: p residual > 0.05 in > 50 % of steps", ha="center",
             va="top", fontsize=5.8, color=L.NOTE, linespacing=1.15)
    fig.subplots_adjust(left=0.17, right=0.97, top=0.85, bottom=0.08)
    L.save(fig, "section_transition_a180.png")


def main():
    L.style()
    d = load()
    TS = pd.read_csv(L.OUT / "section_timestep.csv")
    pol = pd.read_csv(L.OUT / "section_polar_LM23.csv")
    srf = pd.read_csv(L.OUT / "section_transition_surface.csv")
    fig_health(d)
    fig_timestep(d, TS)
    fig_polar(d, pol)
    fig_transition_lm_sst(d)
    fig_transition_tu(d)
    fig_transition_a180(d, srf)


if __name__ == "__main__":
    main()
