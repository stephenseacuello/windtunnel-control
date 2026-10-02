"""Figures for the roughness report. Called by build_report.main()."""
import math
from pathlib import Path

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


def kwp(b, **over):
    """style.kw, but an unconfirmed specimen is drawn hollow and labelled as such."""
    parent = b.split("_repeat")[0]
    k = style.kw(b, **over)
    if parent in SPECIMENS and not SPECIMENS[parent]["confirmed"]:
        k.update(markerfacecolor="white", markeredgecolor=k["color"], markeredgewidth=1.0,
                 label=k["label"].split(" (")[0] + " (identity unconfirmed)")
        k.update({kk: v for kk, v in over.items() if kk == "label"})
    return k


def series(names, repeats):
    """Main figures show one primary run per specimen. Every mounting appears in
    the tables; plotting a dozen near-identical curves here would
    hide the comparison."""
    return list(names)


# ------------------------------------------------------------------ fig 1 --
def fig_pmax(rec, PL, names, repeats):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(W, 2.7), constrained_layout=True)
    for b in series(names, repeats):
        r = rec[b]
        a1.plot(r.wind_mps_nominal, r.p_raw, **kwp(b))
        k = kwp(b, linestyle="none")
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
    ns = ", ".join(f"{PL[(b, 'p_raw')]['n']:.2f} ({style.SERIES[b]['label'].split(' (')[0]})" for b in names)
    a2.text(0.97, 0.05, f"exponent $n$: {ns}", transform=a2.transAxes,
            ha="right", va="bottom", fontsize=7.5, color=style.INK_2)
    panel_tag(a2, "(b) Log axes with power-law fits")
    save(fig, "fig_pmax")


# ------------------------------------------------------------------ fig 2 --
def fig_ratio(P, names, repeats):
    fig, ax = plt.subplots(figsize=(W, 2.8), constrained_layout=True)
    ax.axhline(0, color=style.INK_3, linewidth=0.8, zorder=1)
    for c in [b for b in series(names, repeats) if b != BASE]:
        r = P[(BASE, c, "p_raw")]
        k = kwp(c)
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
    tex_all = [b for b in names if SPECIMENS[b]["fuzz_mm"] > 0]
    tex = [b for b in tex_all if SPECIMENS[b]["confirmed"]]
    xs = {b: SPECIMENS[b]["fuzz_mm"] for b in tex_all}
    if "v1_smooth" in names:
        xs["v1_smooth"] = 0.0125               # plotted left of the log axis, labelled 'none'
    order = [b for b in names if b in xs]
    base = rec[BASE].set_index("fan_rpm_cmd").p_raw
    rel = []
    for cmd in base.index:
        y = [rec[b].set_index("fan_rpm_cmd").p_raw.get(cmd, np.nan) / base[cmd] for b in order]
        rel.append(y)
        ax.plot([xs[b] for b in order], 100 * (np.array(y) - 1), color=style.INK_3,
                linewidth=0.6, alpha=0.7, marker=None, zorder=1)
    rel = np.log(np.array(rel, dtype=float))
    nn = np.sum(~np.isnan(rel), axis=0)
    t = 2.160                                   # t(0.975, 13)
    m = np.nanmean(rel, axis=0)
    half = t * np.nanstd(rel, axis=0, ddof=1) / np.sqrt(nn)
    for i, b in enumerate(order):
        c = style.SERIES[b]
        prov = not SPECIMENS[b]["confirmed"]
        ax.errorbar(xs[b], 100 * np.expm1(m[i]), markerfacecolor="white" if prov else c["color"],
                    markeredgewidth=1.0 if prov else 0.8,
                    yerr=[[100 * (np.expm1(m[i]) - np.expm1(m[i] - half[i]))],
                          [100 * (np.expm1(m[i] + half[i]) - np.expm1(m[i]))]],
                    color=c["color"], marker=c["marker"], markersize=6,
                    markeredgecolor=c["color"] if prov else "white",
                    capsize=2.5, linewidth=1.2, zorder=3)
        if prov:
            ax.annotate("unconfirmed", (xs[b], 100 * np.expm1(m[i])), xytext=(0, -14),
                        textcoords="offset points", ha="center", fontsize=6.5, color=style.INK_2)
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
    ax.set_xticklabels(["none" if v == 0.0125 else f"{v:.3f}" for v in ticks])
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
            ax.plot(g.amps, g.watts, **kwp(b, markersize=3.2, linewidth=1.1))
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
        a1.plot(t.wind_mps_nominal, t.v_oc, **kwp(b, markersize=3.5))
    base = TH[BASE].set_index("fan_rpm_cmd")
    for a in (a2, a3):
        a.axhline(0, color=style.INK_3, linewidth=0.8)
    for c in [b for b in series(names, repeats) if b != BASE]:
        t = TH[c].set_index("fan_rpm_cmd")
        b_ = base.reindex(t.index)                     # align on set point; a run may lack one
        a2.plot(t.wind_mps_nominal, 100 * (t.v_oc / b_.v_oc - 1), **kwp(c, markersize=3.5))
        a3.plot(t.wind_mps_nominal, 100 * (t.r_int / b_.r_int - 1), **kwp(c, markersize=3.5))
    lim = max(abs(v) for a in (a2, a3) for v in a.get_ylim())
    for a in (a2, a3):
        a.set_ylim(-lim, lim)
    a1.set_ylabel("$V_\\mathrm{oc}$ (V)"); panel_tag(a1, "(a) Open-circuit voltage")
    a2.set_ylabel("Change vs Ra 20 (%)"); panel_tag(a2, "(b) $V_\\mathrm{oc}$ vs Ra 20")
    a3.set_ylabel("Change vs Ra 20 (%)"); panel_tag(a3, "(c) $R_\\mathrm{int}$ vs Ra 20")
    for a in (a1, a2, a3):
        a.set_xlabel("Wind speed (m/s, nominal)")
    a1.legend(loc="upper left", fontsize=6.5)
    save(fig, "fig_thevenin")


def fig_jeong(J, JUNE, rec, DX=None):
    """Two figures. fig_jeong_context (Section 6): the Jeong-lab tests relative to the
    rig's Ra 20 at the same fan set point, against the band the rig's textured rotors
    span. fig_jeong_processing (Appendix C): the July table as reported vs reprocessed."""
    import pandas as _pd
    if DX and DX.get("DC"):
        DC = DX["DC"]
        base = _pd.Series(DC["curve"]["v1_smooth"], index=DC["sp"])
        reflabel = "rig no-texture rotor (1 Oct)"
        tex = [_pd.Series(DC["curve"][c], index=DC["sp"]) / base for c in ("v1_Ra20", "v1_Ra40", "v1_Ra80")]
        sp = np.array(DC["sp"])
        bandlab = "Rig, textured rotors (1 Oct)"
    else:
        base = rec[BASE].set_index("fan_rpm_cmd").p_raw
        reflabel = "rig Ra 20"
        sp = base.index.values
        tex = [rec[c].set_index("fan_rpm_cmd").p_raw.reindex(sp) / base for c in ("v1_Ra20", "v1_Ra40", "v1_Ra80")]
        bandlab = "Rig, textured rotors (Ra 20 to Ra 80)"
    lo = 100 * (np.minimum.reduce([t.values for t in tex]) - 1)
    hi = 100 * (np.maximum.reduce([t.values for t in tex]) - 1)
    fig, ax = plt.subplots(figsize=(W, 2.6), constrained_layout=True)
    ax.fill_between(sp, lo, hi, color=style.GRID, alpha=0.9, linewidth=0, zorder=0, label=bandlab)
    ax.axhline(0, color=style.INK_3, linewidth=0.8, zorder=1)
    jn = JUNE.set_index("Setting_RPM").Pdc_max
    cm = [s_ for s_ in jn.index if s_ in base.index]
    ax.plot(cm, 100 * (jn[cm].values / base[cm].values - 1),
            **style.kw("jl_0605", label="Initial reference, 5 Jun (as reported)"))
    m = J[(J.setting_rpm >= 900) & (J.setting_rpm <= 1800)]
    y = 100 * (m.p_1s_max_zc_w.values / base[m.setting_rpm].values - 1)
    y[(m.setting_rpm == 1300).values] = np.nan               # window spans the step to 1400
    ax.plot(m.setting_rpm, y,
            **style.kw("jl_0727", label="No texture, 27 Jul (reprocessed)"))
    ax.set_xlim(450, 1850)
    ax.set_xlabel("Fan set point (rpm)")
    ax.set_ylabel(f"Power relative to {reflabel} (%)", fontsize=7.5)
    ax.legend(loc="upper right", fontsize=7)
    save(fig, "fig_jeong_context")

    fig, ax = plt.subplots(figsize=(3.3, 2.6), constrained_layout=True)
    c = style.SERIES["jl_0727"]["color"]
    ax.plot(J.setting_rpm, J.lab_pdc_max_w, color=c, marker="D", markerfacecolor="white",
            markeredgecolor=c, markeredgewidth=1.0, linewidth=1.0, linestyle=(0, (4, 2)),
            label="Table as reported")
    ax.plot(J.setting_rpm, J.p_1s_max_zc_w, **style.kw("jl_0727", label="Reprocessed (1 s mean)"))
    ax.axvspan(450, 750, color=style.GRID, alpha=0.6, linewidth=0, zorder=0)
    ax.text(600, 0.97, "load\noff", transform=ax.get_xaxis_transform(), ha="center",
            va="top", fontsize=6.5, color=style.INK_2)
    ax.set_xlim(450, 2050)
    ax.set_xlabel("Fan set point (rpm)")
    ax.set_ylabel("Power in the lab's window (W)")
    ax.set_ylim(0, None)
    ax.legend(loc="upper left", fontsize=6.5, bbox_to_anchor=(0.2, 1.0))
    save(fig, "fig_jeong_processing")



# ------------------------------------------------------------ 1 Oct campaign --
DAY_ORDER = ["v1_smooth", "v1_Ra20", "v1_Ra40", "v1_Ra80"]


def _lab(r):
    return style.SERIES[r]["label"]


def fig_day(DX):
    """Every 1 Oct run as one point, with each textured rotor's Aug/Sep run (another
    mounting, another day) and the interval that allows for mounting variation."""
    DC, DM = DX["DC"], DX.get("DM")
    fig, ax = plt.subplots(figsize=(W, 2.5), constrained_layout=True)
    ax.axhline(0, color=style.INK_3, linewidth=0.8)
    rots = [r for r in DAY_ORDER if r in DC["Y"]]
    for i, r in enumerate(rots):
        c = style.SERIES[r]
        ys = [100 * math.expm1(v) for v in DC["Y"][r]]
        for j, y in enumerate(ys):
            ax.plot(i + (j - 0.5) * 0.12, y, marker=c["marker"], markersize=6, linestyle="none",
                    color=c["color"], markerfacecolor=c["color"] if j == 0 else "white",
                    markeredgecolor=c["color"], markeredgewidth=1.1, zorder=3)
        if r in DC.get("first", {}):
            ax.plot(i - 0.33, 100 * math.expm1(DC["first"][r]), marker="x", markersize=6,
                    linestyle="none", color=style.INK, markeredgecolor=style.INK,
                    markeredgewidth=1.3, zorder=3)
        if r in DC["vs_ref"]:
            v = DC["vs_ref"][r]
            ax.plot([i - 0.22, i + 0.22], [100 * v["level"]] * 2, color=style.INK, linewidth=1.2, zorder=2)
            iv = DM["vs_ref"][r] if DM else v
            ax.plot([i + 0.3] * 2, [100 * iv["lo"], 100 * iv["hi"]], color=style.INK_2, linewidth=1.0)
            ax.plot([i + 0.3] * 2, [100 * v["lo"], 100 * v["hi"]], color=style.INK, linewidth=3.0,
                    solid_capstyle="butt")
            ax.text(i + 0.36, 100 * v["level"], f"{100 * v['level']:+.1f}%", va="center",
                    fontsize=7.5, color=style.INK)
    ax.plot([], [], marker="o", linestyle="none", color=style.INK_2, label="1 Oct, run 1 (filled), run 2 (hollow)")
    ax.plot([], [], marker="x", linestyle="none", color=style.INK, markeredgecolor=style.INK,
            markeredgewidth=1.3, label="Aug–Sep run (another mounting)")
    ax.plot([], [], color=style.INK, linewidth=3.0, label="95% CI, run-to-run")
    ax.plot([], [], color=style.INK_2, linewidth=1.0, label="95% CI, with mounting")
    ax.legend(loc="upper left", fontsize=6.5, frameon=False)
    ax.set_xticks(range(len(rots)))
    ax.set_xticklabels([_lab(r).replace(" (", "\n(") for r in rots])
    ax.set_xlim(-0.55, len(rots) - 0.3)
    ax.set_ylabel("Peak power vs no texture (%)")
    ax.grid(axis="x", visible=False)
    save(fig, "fig_day")


def fig_day_curves(DX, v_of):
    DC = DX["DC"]
    sp = np.array(DC["sp"]); v = v_of(sp)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(W, 2.6), constrained_layout=True)
    for r in DAY_ORDER:
        if r in DC["curve"]:
            a1.plot(v, DC["curve"][r], **style.kw(r))
    a1.set_xlabel("Wind speed (m/s, nominal)"); a1.set_ylabel("$P_{\\max}$ (W)")
    a1.set_ylim(0, None); a1.legend(loc="upper left", fontsize=7)
    panel_tag(a1, "(a) Peak electrical power")
    a2.axhline(0, color=style.INK_3, linewidth=0.8)
    for r in DAY_ORDER[1:]:
        if r in DC["ratio_curve"]:
            a2.plot(v, 100 * DC["ratio_curve"][r], **style.kw(r))
    a2.set_xlabel("Wind speed (m/s, nominal)"); a2.set_ylabel("Change vs no texture (%)")
    panel_tag(a2, "(b) Relative to no texture")
    save(fig, "fig_day_curves")


def fig_day_thevenin(DX, v_of):
    DT = DX["DT"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(W, 2.3), constrained_layout=True)
    for a in (a1, a2):
        a.axhline(0, color=style.INK_3, linewidth=0.8)
    for r in DAY_ORDER[1:]:
        if r in DT:
            x = v_of(np.array(DT[r]["curve_sp"]))
            a1.plot(x, 100 * DT[r]["curve_voc"], **style.kw(r, markersize=3.5))
            a2.plot(x, 100 * DT[r]["curve_r"], **style.kw(r, markersize=3.5))
    lim = max(abs(v) for a in (a1, a2) for v in a.get_ylim())
    for a in (a1, a2):
        a.set_ylim(-lim, lim); a.set_xlabel("Wind speed (m/s, nominal)")
        a.set_ylabel("Change vs no texture (%)")
    panel_tag(a1, "(a) Open-circuit voltage $V_\\mathrm{oc}$")
    panel_tag(a2, "(b) Source resistance $R_\\mathrm{int}$")
    a1.legend(loc="upper left", fontsize=6.5)
    save(fig, "fig_day_thevenin")


def fig_surface(folder, clip=60.0):
    import keyence
    from matplotlib.colors import LinearSegmentedColormap
    scans = [("baseline_Height.csv", "v1_smooth"), ("20 1_Height.csv", "v1_Ra20"),
             ("40 1_Height.csv", "v1_Ra40"), ("801_Height.csv", "v1_Ra80")]
    cmap = LinearSegmentedColormap.from_list("div", ["#184f95", "#6da7ec", "#f0efec", "#ef8a6f", "#a3262a"])
    fig, axes = plt.subplots(1, 4, figsize=(W, 1.75), constrained_layout=True)
    im = None
    for ax, (fn, r) in zip(axes, scans):
        z, dx = keyence.display_map(Path(folder) / fn, clip)
        h, w = z.shape
        im = ax.imshow(z, cmap=cmap, vmin=-clip, vmax=clip, origin="lower",
                       extent=[0, w * dx / 1000, 0, h * dx / 1000], interpolation="nearest")
        ax.set_title(_lab(r), fontsize=7.5, loc="center", fontweight="bold", pad=3)
        ax.set_xticks([0, 1]); ax.set_yticks([0, 1])
        ax.tick_params(labelsize=6.5)
        ax.set_xlabel("mm", fontsize=7, labelpad=1)
        ax.grid(False)
    axes[0].set_ylabel("spanwise (mm)", fontsize=7)
    cb = fig.colorbar(im, ax=axes, shrink=0.85, pad=0.01)
    cb.set_label("Height (µm)", fontsize=7); cb.ax.tick_params(labelsize=6.5)
    save(fig, "fig_surface")


def make_all(rec, P, PL, TR, TH, runs, names, repeats, J, JUNE, DX=None):
    fig_pmax(rec, PL, names, repeats)
    fig_ratio(P, names, repeats)
    fig_trend(rec, TR, names)
    fig_pi(runs, names, repeats)
    fig_thevenin(TH, names, repeats)
    fig_jeong(J, JUNE, rec, DX)
    if DX and DX.get("DC"):
        fig_day(DX)
        fig_day_curves(DX, v_nominal)
        fig_day_thevenin(DX, v_nominal)
    if DX and DX.get("SURF"):
        from build_report import KEYENCE_DIR, PACKAGED, ROOT
        fig_surface(ROOT / "3_surface_scans" if PACKAGED else KEYENCE_DIR)
