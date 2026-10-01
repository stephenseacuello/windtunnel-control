"""Figures for the roughness report. Called by build_report.main()."""
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, NullFormatter
import numpy as np

import style
from build_report import FIG, BASE, SPECIMENS, v_nominal

style.apply()
W = style.TEXT_W_IN


def save(fig, name):
    fig.savefig(FIG / f"{name}.pdf")
    fig.savefig(FIG / f"{name}.png", dpi=200)
    plt.close(fig)


def panel_tag(ax, s):
    ax.set_title(s, loc="left", fontsize=9, fontweight="bold", color=style.INK, pad=6)


def series(names, repeats):
    """Plot order: levels in roughness order, each remount right after its parent."""
    out = []
    for b in names:
        out.append(b)
        out += [r for r, p in repeats.items() if p == b]
    return out


# ------------------------------------------------------------------ fig 1 --
def fig_pmax(rec, PL, names, repeats):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(W, 2.7), constrained_layout=True)
    for b in series(names, repeats):
        r = rec[b]
        a1.plot(r.wind_mps_nominal, r.p_raw, **style.kw(b))
        k = style.kw(b, linestyle="none")
        a2.plot(r.wind_mps_nominal, r.p_raw, **k)
        fit = PL[(b, "p_raw")]
        v = np.linspace(r.wind_mps_nominal.min(), r.wind_mps_nominal.max(), 50)
        a2.plot(v, fit["a"] * v ** fit["n"], color=k["color"], linewidth=0.9, marker=None,
                label="_nolegend_")
    a1.set_xlabel("Wind speed (m/s, nominal)")
    a1.set_ylabel("Peak electrical power $P_{\\max}$ (W)")
    a1.set_ylim(0, None)
    a1.legend(loc="upper left", title="Nominal Ra (fuzzy-skin thickness)", title_fontsize=7,
              alignment="left")
    panel_tag(a1, "(a) Linear axes")
    a2.set_xscale("log"); a2.set_yscale("log")
    a2.set_xticks([10, 15, 20, 30, 40]); a2.set_xticklabels(["10", "15", "20", "30", "40"])
    a2.xaxis.set_minor_formatter(NullFormatter())
    a2.set_xlabel("Wind speed (m/s, nominal, log)")
    a2.set_ylabel("$P_{\\max}$ (W, log)")
    a2.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:g}"))
    ns = ", ".join(f"{PL[(b, 'p_raw')]['n']:.2f}" for b in names)
    a2.text(0.97, 0.05, f"power-law exponents $n$ = {ns}", transform=a2.transAxes,
            ha="right", va="bottom", fontsize=7.5, color=style.INK_2)
    panel_tag(a2, "(b) Log axes with power-law fits")
    save(fig, "fig_pmax")


# ------------------------------------------------------------------ fig 2 --
def fig_ratio(P, names, repeats):
    fig, ax = plt.subplots(figsize=(W, 2.8), constrained_layout=True)
    ax.axhline(0, color=style.INK_3, linewidth=0.8, zorder=1)
    for c in [b for b in series(names, repeats) if b != BASE]:
        r = P[(BASE, c, "p_raw")]
        k = style.kw(c)
        ax.axhspan(100 * r["lo"], 100 * r["hi"], color=k["color"], alpha=0.10, linewidth=0, zorder=0)
        ax.axhline(100 * r["level"], color=k["color"], linewidth=0.9, zorder=1)
        lab = (f"{k['label'].split(' (')[0]} vs Ra 20:  {100 * r['level']:+.1f}% "
               f"[{100 * r['lo']:+.1f}, {100 * r['hi']:+.1f}]")
        k["label"] = lab
        ax.plot(r["v"], 100 * r["ratios"], zorder=3, **k)
    ax.set_xlabel("Wind speed (m/s, nominal)")
    ax.set_ylabel("Change in $P_{\\max}$ vs Ra 20 (%)")
    lo, hi = ax.get_ylim()
    ax.set_ylim(min(lo, -2), hi + 0.35 * (hi - lo))
    ax.legend(loc="upper left", ncols=1, title="Geometric mean over 14 set points [95% CI]",
              title_fontsize=7, alignment="left")
    save(fig, "fig_ratio")


# ------------------------------------------------------------------ fig 3 --
def fig_trend(rec, TR, names):
    fig, ax = plt.subplots(figsize=(3.3, 2.75), constrained_layout=True)
    tex = [b for b in names if SPECIMENS[b]["fuzz_mm"] > 0]
    xs = {b: SPECIMENS[b]["fuzz_mm"] for b in tex}
    if "v1_smooth" in names:
        xs["v1_smooth"] = 0.0125               # plotted left of the log axis, labelled 'none'
    order = [b for b in names if b in xs]
    base = rec[BASE].set_index("fan_rpm_cmd").p_raw
    rel = []
    for cmd in base.index:
        y = [rec[b].set_index("fan_rpm_cmd").p_raw[cmd] / base[cmd] for b in order]
        rel.append(y)
        ax.plot([xs[b] for b in order], 100 * (np.array(y) - 1), color=style.INK_3,
                linewidth=0.6, alpha=0.7, marker=None, zorder=1)
    rel = np.log(np.array(rel))
    t = 2.160                                   # t(0.975, 13)
    m, half = rel.mean(0), t * rel.std(0, ddof=1) / math.sqrt(rel.shape[0])
    for i, b in enumerate(order):
        c = style.SERIES[b]
        ax.errorbar(xs[b], 100 * np.expm1(m[i]),
                    yerr=[[100 * (np.expm1(m[i]) - np.expm1(m[i] - half[i]))],
                          [100 * (np.expm1(m[i] + half[i]) - np.expm1(m[i]))]],
                    color=c["color"], marker=c["marker"], markersize=6, markeredgecolor="white",
                    capsize=2.5, linewidth=1.2, zorder=3)
    tr = TR["p_raw"]
    t0 = SPECIMENS[BASE]["fuzz_mm"]
    # The fit has a free intercept per set point, so draw the slope through the
    # centroid of the textured levels' mean log-ratios, not pinned at Ra 20.
    ti = [order.index(b) for b in tex]
    c0 = np.mean([m[i] - tr["beta"] * math.log(xs[order[i]] / t0) for i in ti])
    xx = np.geomspace(min(xs[b] for b in tex), max(xs[b] for b in tex), 40)
    ax.plot(xx, 100 * np.expm1(c0 + tr["beta"] * np.log(xx / t0)), color=style.INK,
            linewidth=1.0, zorder=2)
    ax.text(0.04, 0.95, f"fit: $P_{{\\max}} \\propto t_{{\\mathrm{{fuzz}}}}^{{\\,{tr['beta']:.3f}}}$",
            transform=ax.transAxes, fontsize=7.5, color=style.INK, ha="left", va="top")
    ax.set_xscale("log", base=2)
    ticks = sorted(xs.values())
    ax.set_xticks(ticks)
    ax.set_xticklabels(["none" if v == 0.0125 else f"{v:g}" for v in ticks])
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.set_xlim(min(ticks) / 1.25, max(ticks) * 1.25)
    ax.set_xlabel("Fuzzy-skin thickness (mm, log scale)")
    ax.set_ylabel("$P_{\\max}$ relative to Ra 20 (%)")
    save(fig, "fig_trend")


# ------------------------------------------------------------------ fig 4 --
def fig_pi(runs, names, repeats, setpoints=(700, 1200, 1700)):
    fig, axes = plt.subplots(1, 3, figsize=(W, 2.35), constrained_layout=True)
    for ax, cmd in zip(axes, setpoints):
        for b in series(names, repeats):
            p = runs[b]["points"]
            g = p[(p.fan_rpm == cmd) & (p.tracking == 1)]
            ax.plot(g.amps, g.watts, **style.kw(b, markersize=3.2, linewidth=1.1))
        panel_tag(ax, f"Fan {cmd} rpm ({v_nominal(cmd):.1f} m/s)")
        ax.set_xlabel("Load current (A)")
        ax.set_ylim(0, None); ax.set_xlim(0, None)
    axes[0].set_ylabel("Electrical power (W)")
    axes[0].legend(loc="lower center", fontsize=6.5)
    save(fig, "fig_pi")


# ------------------------------------------------------------------ fig 5 --
def fig_thevenin(TH, names, repeats):
    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(W, 2.35), constrained_layout=True)
    for b in series(names, repeats):
        t = TH[b]
        a1.plot(t.wind_mps_nominal, t.v_oc, **style.kw(b, markersize=3.5))
        a2.plot(t.wind_mps_nominal, t.r_int, **style.kw(b, markersize=3.5))
    base = TH[BASE].set_index("fan_rpm_cmd")
    a3.axhline(0, color=style.INK_3, linewidth=0.8)
    for c in [b for b in series(names, repeats) if b != BASE]:
        t = TH[c].set_index("fan_rpm_cmd")
        a3.plot(t.wind_mps_nominal, 100 * (t.v_oc / base.v_oc - 1), **style.kw(c, markersize=3.5))
    a1.set_ylabel("$V_{oc}$ (V)"); panel_tag(a1, "(a) Open-circuit voltage")
    a2.set_ylabel("$R_{int}$ (Ω)"); panel_tag(a2, "(b) Source resistance")
    a3.set_ylabel("$V_{oc}$ change vs Ra 20 (%)"); panel_tag(a3, "(c) $V_{oc}$ vs Ra 20")
    for a in (a1, a2, a3):
        a.set_xlabel("Wind speed (m/s, nominal)")
    a1.legend(loc="upper left", fontsize=6.5)
    save(fig, "fig_thevenin")


# ------------------------------------------------------------------ fig 6 --
def fig_jeong(J, JUNE, rec):
    """(a) The July table as reported vs reprocessed in the lab's own windows.
    (b) Reprocessed July beside the rig's Ra 20 and the June table, by fan set
    point (the two labs' fan-to-wind calibrations differ)."""
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(W, 2.75), constrained_layout=True)
    c = style.SERIES["jl_0727"]["color"]
    a1.plot(J.setting_rpm, J.lab_pdc_max_w, color=c, marker="D", markerfacecolor="white",
            markeredgecolor=c, markeredgewidth=1.0, linewidth=1.0, linestyle=(0, (4, 2)),
            label="As reported (max of 360 Hz samples)")
    a1.plot(J.setting_rpm, J.p_1s_max_zc_w, **style.kw("jl_0727", label="Reprocessed (1 s mean, zeroed current)"))
    a1.axvspan(450, 750, color=style.GRID, alpha=0.6, linewidth=0, zorder=0)
    a1.text(600, 0.93, "load at 0 A", transform=a1.get_xaxis_transform(), ha="center",
            va="top", fontsize=7, color=style.INK_2)
    a1.set_xlim(450, 2050)
    a1.set_xlabel("Fan set point (rpm)")
    a1.set_ylabel("Power in the lab's window (W)")
    a1.set_ylim(0, None)
    a1.legend(loc="upper left", fontsize=6.8, bbox_to_anchor=(0.0, 0.88))
    panel_tag(a1, "(a) Jeong lab, 27 July: same data, two statistics")

    r20 = rec[BASE]
    a2.plot(r20.fan_rpm_cmd, r20.p_raw, **style.kw("v1_Ra20", label="Rig, Ra 20 ($P_{\\max}$)"))
    m = J[J.setting_rpm >= 800]
    a2.plot(m.setting_rpm, m.p_1s_max_zc_w, **style.kw("jl_0727", label="Jeong lab 27 Jul, reprocessed"))
    a2.plot(JUNE.Setting_RPM, JUNE.Pdc_max, **style.kw("jl_0605", label="Jeong lab 5 Jun, as reported"))
    a2.set_xlim(450, 2050)
    a2.set_xlabel("Fan set point (rpm)")
    a2.set_ylabel("Electrical power (W)")
    a2.set_ylim(0, None)
    a2.legend(loc="upper left", fontsize=6.8)
    panel_tag(a2, "(b) Context against the rig")
    save(fig, "fig_jeong")


def make_all(rec, P, PL, TR, TH, runs, names, repeats, J, JUNE):
    fig_pmax(rec, PL, names, repeats)
    fig_ratio(P, names, repeats)
    fig_trend(rec, TR, names)
    fig_pi(runs, names, repeats)
    fig_thevenin(TH, names, repeats)
    fig_jeong(J, JUNE, rec)
