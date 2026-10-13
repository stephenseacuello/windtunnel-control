#!/usr/bin/env python3
"""Figures for the Stage 1 (blade section) analysis of 13 Oct 2026.

    nice -n 10 python3 cfd/analysis/2026-10-13/src/section_figures.py

Reads ../data/section_polars.csv through section_lib; writes ../fig/section_*.png (200 dpi):
  section_polar.png       Cd, Cl, Cm against alpha: LM 23 m/s polar, SST at 0/90/180, literature
  section_speed_tu.png    Cd at alpha 0 and 180 against wind speed (SST, LM) and Tu (LM)
  section_grid.png        grid study (maxCo 2.5) and time-step check (maxCo 5), Cd and St
  section_strouhal.png    St against alpha for runs with a usable lift spectrum
  section_health.png      the numerical-health flag: time-step collapse and force symptoms
Encoding in every figure: smooth blade = black; LM = circle, solid line; SST = square, dashed
line; maxCo 2.5 = filled marker, maxCo 5 = open marker; flagged (corrupted) run = grey x.
Verifier changes of 13 Oct (see the "Verifier fix" comments): polar marks a healthy run whose
window mean is not stationary with a dagger; speed/Tu joins only runs in the same alpha-0 flow
state; grid states its run conditions; Strouhal notes that the alpha-90 runs are steady at maxCo 2.5.
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import NullFormatter  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import section_analysis as A  # noqa: E402
import section_lib as L  # noqa: E402

BLACK, GREY = L.BLACK, L.GREY
MS = 4.5


def save(fig, name):
    L.FIG.mkdir(exist_ok=True)
    out = L.FIG / name
    fig.savefig(out, dpi=200, facecolor="white")
    plt.close(fig)
    print(out)


def mk(model, maxco, corrupted=False, **kw):
    st = L.mstyle(model, maxco, corrupted)
    st.update(kw)
    return st


def st_point(ax, x, y, model, maxco, status, **kw):
    """St marker; a centre dot marks a broadband spectrum (peak band < 50 % of the Cl variance)."""
    ax.plot([x], [y], ls="none", **mk(model, maxco), **kw)
    if status != "clean peak":
        filled = float(maxco) < 5
        ax.plot([x], [y], ls="none", marker="o", ms=1.6, mfc="white" if filled else BLACK,
                mec="white" if filled else BLACK, mew=0, **kw)


def bb_handle():
    return (Line2D([], [], ls="none", **mk("LM", 5)),
            Line2D([], [], ls="none", marker="o", ms=1.6, mfc=BLACK, mec=BLACK, mew=0))


def clip_plot(ax, x, y, lo, hi, label_fmt="{:.1f}", dx=0.0):
    """Grey x for corrupted runs; values outside [lo, hi] drawn as a grey triangle at the edge
    with the value written next to it."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    inside = (y >= lo) & (y <= hi)
    ax.plot(x[inside], y[inside], ls="none", **mk("LM", 5, True))
    for xi, yi in zip(x[~inside], y[~inside]):
        top = yi > hi
        yy = hi - 0.02 * (hi - lo) if top else lo + 0.02 * (hi - lo)
        ax.plot([xi], [yy], marker="^" if top else "v", color=GREY, ms=4, ls="none")
        ax.annotate(label_fmt.format(yi), (xi, yy), xytext=(4 + dx, -2 if top else 1), textcoords="offset points",
                    fontsize=6, color=GREY, va="center")


def segments(alpha, ok, step=15):
    """Indices of runs of consecutive healthy alphas (spacing = step)."""
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


# ------------------------------------------------------------------ 1. polar
def fig_polar(d):
    pol = A.pick(d, model="LM", U_ms=23.0, Tu_body_pct=1.0, level="medium", maxCo=5.0).sort_values("alpha_deg")
    a0 = pol[pol.alpha_deg == 0].copy()
    a0["alpha_deg"] = 360.0                     # alpha 360 repeats alpha 0 (same run)
    pol = __import__("pandas").concat([pol, a0], ignore_index=True)
    sst = d[(d.model == "SST") & (d.U_ms == 23.0) & (d.level == "medium")]
    fig, axs = plt.subplots(3, 1, figsize=(3.4, 5.6), sharex=True, gridspec_kw=dict(hspace=0.12))
    lims = {"Cd_mean": (-2.3, 4.1), "Cl_mean": (-3.6, 3.1), "Cm_mean": (-2.2, 2.7)}
    ylab = {"Cd_mean": "drag coefficient $C_d$", "Cl_mean": "lift coefficient $C_l$",
            "Cm_mean": "moment coefficient $C_m$"}
    for ax, q in zip(axs, ("Cd_mean", "Cl_mean", "Cm_mean")):
        lo, hi = lims[q]
        ok = ~pol.corrupted.to_numpy()
        al = pol.alpha_deg.to_numpy()
        for seg in segments(al, ok):
            ax.plot(al[seg], pol[q].to_numpy()[seg], "-", color=BLACK, lw=1.0, zorder=2)
        ax.plot(al[ok], pol[q].to_numpy()[ok], ls="none", zorder=3, **mk("LM", 5))
        clip_plot(ax, al[~ok], pol[q].to_numpy()[~ok], lo, hi)
        for r in sst.itertuples():          # drawn 6 deg either side of alpha for legibility
            ax.plot([r.alpha_deg + (6 if r.maxCo < 5 else -6)], [getattr(r, q)], ls="none", zorder=4,
                    **mk("SST", r.maxCo, r.corrupted, ms=5 if not r.corrupted else 4.5))
        ax.axhline(0, color="#bdbdbd", lw=0.6, zorder=1)
        ax.set_ylim(lo, hi)
        ax.set_ylabel(ylab[q])
    # Verifier fix (13 Oct): a healthy run whose window mean is not stationary (Cd drift between
    # the two halves of the averaging window > 20 % of the mean) gets a dagger; alpha 15 drifts by
    # 35 % over about 2 slow lift cycles, so its mean is not converged.
    ns = pol[~pol.corrupted & (pol.Cd_drift.abs() > 0.2 * pol.Cd_mean.abs()) & (pol.alpha_deg < 360)]
    for ax, q in zip(axs, ("Cd_mean", "Cl_mean", "Cm_mean")):
        for r in ns.itertuples():
            ax.annotate("†", (r.alpha_deg, getattr(r, q)), xytext=(3, 3), textcoords="offset points",
                        fontsize=7, ha="left", va="bottom", color=BLACK)
    ns_txt = "; ".join(f"† α {r.alpha_deg:g}: mean not stationary (C$_d$ drift {100 * abs(r.Cd_drift / r.Cd_mean):.0f} %"
                       f" of the mean, {r.n_cycles_avg:.1f} lift cycles)" for r in ns.itertuples())
    axs[0].plot([0, 180], [L.LIT_CD_CONCAVE, L.LIT_CD_CONVEX], ls="none", marker="*",
                ms=7.5, mfc="white", mec=L.LIT, mew=0.9, zorder=5)
    axs[0].annotate("concave\nto wind", (0, 3.6), xytext=(9, 0), textcoords="offset points", fontsize=6,
                    color="#444444", va="center")
    axs[0].annotate("convex to wind", (180, 3.75), ha="center", fontsize=6, color="#444444", va="center")
    axs[2].set_xlabel("angle of attack α (deg)")
    axs[2].set_xticks(np.arange(0, 361, 45))
    axs[2].set_xticks(np.arange(0, 361, 15), minor=True)
    axs[2].set_xlim(-13, 370)
    h = [Line2D([], [], lw=1.0, **mk("LM", 5)),
         Line2D([], [], **mk("SST", 5, ls="none")),
         Line2D([], [], **mk("SST", 2.5, ls="none")),
         Line2D([], [], ls="none", **mk("LM", 5, True)),
         Line2D([], [], ls="none", marker="*", ms=7.5, mfc="white", mec=L.LIT, mew=0.9)]
    lab = ["LM, maxCo 5", "SST, maxCo 5", "SST, maxCo 2.5", "flagged run (corrupted)",
           "literature, 2D half-cylinder shell"]
    fig.legend(h, lab, loc="upper center", ncol=2, bbox_to_anchor=(0.55, 1.0), columnspacing=1.0,
               handlelength=2.2)
    fig.text(0.57, 0.903, "23 m/s, Tu 1 %, medium mesh; α 360 repeats α 0" + ("\n" + ns_txt if len(ns) else ""),
             ha="center", va="top", fontsize=6, color="#444444", linespacing=1.15)
    fig.subplots_adjust(left=0.17, right=0.97, top=0.865, bottom=0.075)
    save(fig, "section_polar.png")


# ------------------------------------------------------------------ 2. speed and Tu
def fig_speed_tu(d):
    m5 = d[(d.level == "medium") & (d.maxCo == 5.0)]
    fig, axs = plt.subplots(2, 2, figsize=(3.4, 3.7), sharey="row",
                            gridspec_kw=dict(wspace=0.08, hspace=0.42, width_ratios=[1.25, 1]))
    good0 = d[(d.alpha_deg == 0) & ~d.corrupted]
    hi_b = good0[good0.branch_a0 == "high-drag shedding"].Cd_mean
    lo_b = good0[good0.branch_a0 == "low-drag"].Cd_mean
    ref180 = A.pick(d, model="SST", U_ms=23.0, maxCo=2.5, alpha_deg=180).Cd_mean
    ylims = {0: (1.3, 3.75), 180: (-2.4, 3.2)}
    xu = {10.2: 0, 23.0: 1, 38.0: 2}
    xt = {0.5: 0, 1.0: 1, 3.0: 2}
    for i, a in enumerate((0, 180)):
        for j, sweep in enumerate(("speed", "Tu")):
            ax = axs[i, j]
            if a == 0:
                for rng, txt in ((hi_b, "high-drag\nstate"), (lo_b, "low-drag\nstate")):
                    ax.axhspan(rng.min(), rng.max(), color="#efefef", zorder=0, lw=0)
                    if j == 1:
                        ax.annotate(txt, (2.45, 0.5 * (rng.min() + rng.max())), fontsize=5.8, color="#555555",
                                    va="center", ha="left", annotation_clip=False)
                ax.axhline(L.LIT_CD_CONCAVE, color=L.LIT, lw=0.8, ls=":", zorder=1)
            else:
                ax.axhspan(ref180.min(), ref180.max(), color="#efefef", zorder=0, lw=0)
                ax.axhline(L.LIT_CD_CONVEX, color=L.LIT, lw=0.8, ls=":", zorder=1)
                ax.axhline(0, color="#bdbdbd", lw=0.6, zorder=1)
            if sweep == "speed":
                g = m5[(m5.alpha_deg == a) & (m5.Tu_body_pct == 1.0)]
                xmap, xcol = xu, "U_ms"
                models = ("SST", "LM")
            else:
                g = m5[(m5.alpha_deg == a) & (m5.U_ms == 23.0) & (m5.model == "LM")]
                xmap, xcol = xt, "Tu_body_pct"
                models = ("LM",)
            for mdl in models:
                gg = g[g.model == mdl].sort_values(xcol)
                off = {"SST": -0.07, "LM": 0.07}[mdl] if sweep == "speed" else 0.0
                x = gg[xcol].map(xmap).to_numpy() + off
                ok = ~gg.corrupted.to_numpy()
                y = gg.Cd_mean.to_numpy()
                # Verifier fix (13 Oct): join neighbouring healthy runs only when they are in the
                # same alpha-0 flow state. A line across a state change (LM 23 -> 38 m/s, the LM Tu
                # sweep) drew a speed or Tu trend that the runs do not show.
                br = gg.branch_a0.to_numpy()
                idx = np.flatnonzero(ok)
                for i0, i1 in zip(idx[:-1], idx[1:]):
                    if br[i0] == br[i1]:
                        ax.plot(x[[i0, i1]], y[[i0, i1]], L.MODEL_LS[mdl], color=BLACK, lw=0.9, zorder=2)
                ax.errorbar(x[ok], y[ok], yerr=2 * gg.Cd_se.to_numpy()[ok], ls="none", ecolor=BLACK,
                            elinewidth=0.6, capsize=1.5, zorder=3)
                ax.plot(x[ok], y[ok], ls="none", zorder=4, **mk(mdl, 5))
                lo, hi = ylims[a]
                yb = y[~ok]
                inside = (yb >= lo) & (yb <= hi)
                ax.plot(x[~ok][inside], yb[inside], ls="none", zorder=4, **mk(mdl, 5, True))
            ax.set_xticks(range(3))
            ax.set_xticklabels(["10.2", "23", "38"] if sweep == "speed" else ["0.5", "1", "3"])
            ax.set_xlim(-0.45, 2.45)
            ax.set_ylim(*ylims[a])
            ax.grid(axis="x", visible=False)
            if j == 0:
                ax.set_ylabel(f"$C_d$ at α = {a}°")
            if i == 1:
                ax.set_xlabel("U (m/s)" if sweep == "speed" else "Tu (%)")
            if i == 0:
                ax.set_title("wind speed (Tu 1 %)" if sweep == "speed" else "turbulence (LM, 23 m/s)", fontsize=7.5)
    axs[1, 1].annotate("all 8 runs at α 180\nare flagged", (1.0, -1.7), ha="center", va="center", fontsize=6,
                       color="#555555")
    axs[1, 1].annotate("SST maxCo 2.5\n(c/m/f, 23 m/s)", (2.45, ref180.mean()), fontsize=5.8, color="#555555",
                       va="center", ha="left", annotation_clip=False)
    h = [Line2D([], [], lw=0.9, **mk("SST", 5)), Line2D([], [], lw=0.9, **mk("LM", 5)),
         Line2D([], [], ls="none", **mk("LM", 5, True)), Line2D([], [], color=L.LIT, lw=0.8, ls=":")]
    fig.legend(h, ["SST", "LM", "flagged run", "literature"], loc="upper center", ncol=4,
               bbox_to_anchor=(0.5, 1.0), handlelength=2.0, columnspacing=0.8)
    fig.text(0.47, 0.922, "medium mesh, maxCo 5; bars ±2 sampling standard errors;\n"
             "lines join only runs in the same flow state", ha="center", va="top", fontsize=6,
             color="#444444", linespacing=1.15)
    fig.subplots_adjust(left=0.15, right=0.79, top=0.795, bottom=0.12)
    save(fig, "section_speed_tu.png")


# ------------------------------------------------------------------ 3. grid and time step
def fig_grid(d, grid_tab):
    fig, axs = plt.subplots(3, 2, figsize=(3.4, 4.6), sharex=True, gridspec_kw=dict(hspace=0.22, wspace=0.42))
    for i, a in enumerate((0, 90, 180)):
        g25 = A.pick(d, model="SST", U_ms=23.0, maxCo=2.5, alpha_deg=a).sort_values("level_i")
        g5 = A.pick(d, model="SST", U_ms=23.0, maxCo=5.0, alpha_deg=a).sort_values("level_i")
        g5 = g5[g5.level.isin(["coarse", "medium"])]
        n_f = g25.n_cells.iloc[-1]
        h25 = np.sqrt(n_f / g25.n_cells.to_numpy())
        h5 = np.sqrt(n_f / g5.n_cells.to_numpy())
        for j, q in enumerate(("Cd_mean", "St")):
            ax = axs[i, j]
            y25, y5 = g25[q].to_numpy(), g5[q].to_numpy()
            use25 = np.ones(3, bool) if q == "Cd_mean" else g25.St_status.isin(
                ["clean peak", "broadband (peak frac < 0.5)"]).to_numpy()
            use5 = ~g5.corrupted.to_numpy()
            if q == "St":
                use5 &= g5.St_status.isin(["clean peak", "broadband (peak frac < 0.5)"]).to_numpy()
            if use25.sum() > 1:
                ax.plot(h25[use25], y25[use25], "--", color=BLACK, lw=0.9)
            for k in range(3):
                if use25[k]:
                    st_point(ax, h25[k], y25[k], "SST", 2.5, g25.St_status.iloc[k] if q == "St" else "clean peak")
            for k in range(len(g5)):
                if use5[k]:
                    st_point(ax, h5[k], y5[k], "SST", 5, g5.St_status.iloc[k] if q == "St" else "clean peak")
                elif g5.corrupted.iloc[k] and q == "Cd_mean":
                    ax.plot([h5[k]], [y5[k]], ls="none", **mk("SST", 5, True))
            if q == "St" and use25.sum() == 0:
                ax.annotate("steady at maxCo 2.5\n(no shedding)", (0.5, 0.5), xycoords="axes fraction",
                            ha="center", va="center", fontsize=6, color="#555555")
            row = grid_tab[(grid_tab.alpha_deg == a) & (grid_tab.quantity == q)].iloc[0]
            if np.isfinite(row.phi_ext):
                gci = row.GCI_fine_pct / 100 * abs(row.fine)
                ax.errorbar([1.0], [row.fine], yerr=[gci], ecolor=BLACK, elinewidth=0.7, capsize=2, ls="none")
                ax.plot([0], [row.phi_ext], ls="none", marker="D", ms=3.8, mfc="white", mec=BLACK, mew=0.8)
                ax.annotate(f"p = {row.p:.2f}\nGCI {row.GCI_fine_pct:.1f} %", (0.06, 0.06),
                            xycoords="axes fraction", fontsize=5.8, va="bottom")
            elif q == "Cd_mean":
                ax.annotate("oscillatory" if row.R < 0 else "diverging", (0.06, 0.06), xycoords="axes fraction",
                            fontsize=5.8, va="bottom", color="#555555")
            ax.margins(y=0.25)
            ax.set_xlim(-0.15, 2.15)
            if j == 0:
                ax.set_ylabel(f"$C_d$, α = {a}°")
            else:
                ax.set_ylabel(f"St, α = {a}°")
    for ax in axs[2]:
        ax.set_xticks([0, 1, 1.39, 1.93])
        ax.set_xticklabels(["0", "1\nfine", "1.39\nmed.", "1.93\ncoarse"], fontsize=6)
        ax.set_xlabel("cell size h / h$_{fine}$")
    # the medium maxCo 5 run at alpha 180 is far off scale: say so
    m5 = A.one(d, model="SST", U_ms=23.0, maxCo=5.0, alpha_deg=180, level="medium")
    ax = axs[2, 0]
    lo, hi = ax.get_ylim()
    if m5.Cd_mean < lo:
        ax.set_ylim(min(lo, m5.Cd_mean - 0.1), hi)
    h = [Line2D([], [], lw=0.9, ls="--", **{k: v for k, v in mk("SST", 2.5).items() if k != "ls"}),
         Line2D([], [], ls="none", **{k: v for k, v in mk("SST", 5).items() if k != "ls"}),
         Line2D([], [], ls="none", **mk("SST", 5, True)),
         Line2D([], [], ls="none", marker="D", ms=3.8, mfc="white", mec=BLACK, mew=0.8),
         (Line2D([], [], ls="none", **mk("SST", 5)),
          Line2D([], [], ls="none", marker="o", ms=1.6, mfc=BLACK, mec=BLACK, mew=0))]
    fig.legend(h, ["SST, maxCo 2.5", "SST, maxCo 5", "flagged run", "extrapolated (h → 0)",
                   "broadband St spectrum"], loc="upper center", ncol=2,
               bbox_to_anchor=(0.53, 1.0), handlelength=2.2, columnspacing=1.0)
    # Verifier fix (13 Oct): the run conditions were not stated anywhere on the figure
    fig.text(0.53, 0.882, "SST, 23 m/s, Tu 1 %; St = f c/U with c = 48 mm", ha="center", va="top",
             fontsize=6, color="#444444")
    fig.subplots_adjust(left=0.15, right=0.98, top=0.86, bottom=0.11)
    save(fig, "section_grid.png")


# ------------------------------------------------------------------ 4. Strouhal
def fig_strouhal(d):
    ok = d[~d.corrupted & d.St_status.isin(["clean peak", "broadband (peak frac < 0.5)"]) & (d.St_peak_frac >= 0.2)]
    fig, ax = plt.subplots(figsize=(3.4, 2.5))
    lm = A.pick(ok, model="LM", U_ms=23.0, Tu_body_pct=1.0, level="medium", maxCo=5.0).sort_values("alpha_deg")
    for r in lm.itertuples():
        st_point(ax, r.alpha_deg, r.St, "LM", 5, r.St_status)
    sst = ok[(ok.model == "SST") & (ok.U_ms == 23.0) & (ok.level == "medium")]
    for r in sst.itertuples():
        st_point(ax, r.alpha_deg + (5 if r.maxCo < 5 else -5), r.St, "SST", r.maxCo, r.St_status)
    for a, st, txt, xy in ((0, 0.1467, "≈ 58-70 Hz", (-4, 13)), (90, 0.5066, "≈ 243 Hz", (7, 4)),
                           (180, 0.2232, "≈ 107 Hz", (7, 4)), (270, 0.5067, "≈ 243 Hz", (7, 4))):
        ax.annotate(txt, (a, st), xytext=xy, textcoords="offset points", fontsize=6, color="#444444")
    # Verifier fix (13 Oct): the alpha-90 shedding exists only at maxCo 5. The maxCo 2.5 runs at
    # alpha 90 are steady on all three meshes (Cl_std <= 8e-4), so this St is not time-step robust.
    s90 = A.pick(d, model="SST", U_ms=23.0, maxCo=2.5, alpha_deg=90)
    if len(s90) and (s90.Cl_std < 1e-3).all():
        ax.annotate(f"steady at maxCo 2.5\n(all {len(s90)} meshes): no St", (85, 0.5066), xytext=(0, -9),
                    textcoords="offset points", ha="center", va="top", fontsize=5.8, color="#444444")
    ax.annotate("frequencies f at 23 m/s", (0.98, 0.03), xycoords="axes fraction", ha="right", fontsize=6,
                color="#444444")
    ax.set_xlabel("angle of attack α (deg)")
    ax.set_ylabel("Strouhal number St = f c / U\n(c = 48 mm)")
    ax.set_xticks(np.arange(0, 361, 45))
    ax.set_xticks(np.arange(0, 361, 15), minor=True)
    ax.set_xlim(-10, 370)
    ax.set_ylim(0, 0.6)
    h = [Line2D([], [], ls="none", **mk("LM", 5)), Line2D([], [], ls="none", **mk("SST", 5)),
         Line2D([], [], ls="none", **mk("SST", 2.5)), bb_handle()]
    ax.legend(h, ["LM, maxCo 5", "SST, maxCo 5", "SST, maxCo 2.5", "broadband spectrum"], loc="upper center",
              ncol=2, bbox_to_anchor=(0.5, 1.22), handlelength=1.5, columnspacing=1.0)
    fig.subplots_adjust(left=0.16, right=0.97, top=0.82, bottom=0.17)
    save(fig, "section_strouhal.png")


# ------------------------------------------------------------------ 5. health
def fig_health(d):
    fig, axs = plt.subplots(2, 1, figsize=(3.4, 4.3), gridspec_kw=dict(hspace=0.42))
    ax = axs[0]
    lo_bad = d[d.corrupted].u_co_over_U.min()
    hi_good = d[~d.corrupted].u_co_over_U.max()
    for a in axs:
        a.axhspan(hi_good, lo_bad, color="#efefef", lw=0, zorder=0) if a is axs[0] else \
            a.axvspan(hi_good, lo_bad, color="#efefef", lw=0, zorder=0)
    for r in d.itertuples():
        off = {"coarse": -4, "medium": 0, "fine": 4}[r.level] if r.alpha_deg in (0, 90, 180) else 0
        if r.neg_drag:
            ax.plot([r.alpha_deg + off], [r.u_co_over_U], ls="none", marker="v", ms=4.5, color=GREY, mec=GREY,
                    zorder=3)
        else:
            ax.plot([r.alpha_deg + off], [r.u_co_over_U], ls="none", zorder=3, **mk(r.model, r.maxCo, r.corrupted))
    ax.axhline(L.U_CO_LIMIT, color=BLACK, lw=0.7, ls=":")
    ax.set_yscale("log")
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.set_ylim(1.5, 50)
    ax.set_yticks([2, 5, 10, 20, 50])
    ax.set_yticklabels(["2", "5", "10", "20", "50"])
    ax.set_xticks(np.arange(0, 361, 45))
    ax.set_xlim(-12, 357)
    ax.set_xlabel("angle of attack α (deg)")
    ax.set_ylabel("time-step proxy $u_{Co}/U$")
    ax.annotate("limit 5", (352, L.U_CO_LIMIT), xytext=(0, 2), textcoords="offset points", ha="right",
                fontsize=6, va="bottom")
    ax = axs[1]
    for r in d.itertuples():
        y = r.Cd_relstd
        if r.neg_drag:
            ax.plot([r.u_co_over_U], [y], ls="none", marker="v", ms=4.5, color=GREY, mec=GREY, zorder=3)
        else:
            ax.plot([r.u_co_over_U], [y], ls="none", zorder=3, **mk(r.model, r.maxCo, r.corrupted))
    ax.axvline(L.U_CO_LIMIT, color=BLACK, lw=0.7, ls=":")
    ax.axhline(1.0, color="#bdbdbd", lw=0.6)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.set_xlim(1.5, 50)
    ax.set_xticks([2, 5, 10, 20, 50])
    ax.set_xticklabels(["2", "5", "10", "20", "50"])
    ax.set_xlabel("time-step proxy $u_{Co}/U$")
    ax.set_ylabel("$C_{d,std}\\ /\\ |C_{d,mean}|$")
    ax.annotate("std = mean", (1.6, 1.0), xytext=(0, 2), textcoords="offset points", fontsize=6, va="bottom",
                color="#555555")
    h = [Line2D([], [], ls="none", **mk("LM", 5)), Line2D([], [], ls="none", **mk("SST", 5)),
         Line2D([], [], ls="none", **mk("SST", 2.5)), Line2D([], [], ls="none", **mk("LM", 5, True)),
         Line2D([], [], ls="none", marker="v", ms=4.5, color=GREY)]
    fig.legend(h, ["LM, maxCo 5", "SST, maxCo 5", "SST, maxCo 2.5", "flagged run", "flagged, mean $C_d$ < 0"],
               loc="upper center", ncol=3, bbox_to_anchor=(0.54, 1.0), handlelength=1.2, columnspacing=0.8)
    fig.subplots_adjust(left=0.17, right=0.97, top=0.88, bottom=0.1)
    save(fig, "section_health.png")


def main():
    L.style()
    d = L.load()
    import pandas as pd
    grid_tab = pd.read_csv(L.OUT / "section_grid.csv") if (L.OUT / "section_grid.csv").exists() else None
    if grid_tab is None:
        raise SystemExit("run section_analysis.py first (it writes ../out/section_grid.csv)")
    fig_polar(d)
    fig_speed_tu(d)
    fig_grid(d, grid_tab)
    fig_strouhal(d)
    fig_health(d)


if __name__ == "__main__":
    main()
