"""Figures for the 1 October 2026 fuzzy-skin report. Called by build_report.main()."""
import logging
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import data as D
import style

logging.getLogger("fontTools").setLevel(logging.ERROR)     # font subsetting chatter
style.apply()
W = style.TEXT_W_IN
FIG = D.BUILD / "fig"


def save(fig, name):
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / f"{name}.pdf")
    fig.savefig(FIG / f"{name}.png", dpi=200)
    plt.close(fig)


def tag(ax, s):
    ax.set_title(s, loc="left", fontsize=9, fontweight="bold", color=style.INK, pad=6)


def lab(spec):
    return style.SERIES[spec]["label"]


def run_legend(ax, loc="upper left"):
    """Rotor legend plus a note that hollow markers are the second run."""
    h, l = ax.get_legend_handles_labels()
    h.append(plt.Line2D([], [], marker="o", linestyle="none", markerfacecolor="white",
                        markeredgecolor=style.INK_2, color=style.INK_2))
    l.append("hollow: run 2")
    ax.legend(h, l, loc=loc, fontsize=7)


# ------------------------------------------------------------ surface maps --
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
        ax.set_title(lab(r), fontsize=7.5, loc="center", fontweight="bold", pad=3)
        ax.set_xticks([0, 1]); ax.set_yticks([0, 1])
        ax.tick_params(labelsize=6.5)
        ax.set_xlabel("chordwise (mm)", fontsize=7, labelpad=1)
        ax.grid(False)
    axes[0].set_ylabel("spanwise (mm)", fontsize=7)
    cb = fig.colorbar(im, ax=axes, shrink=0.85, pad=0.01)
    cb.set_label("Height (µm)", fontsize=7); cb.ax.tick_params(labelsize=6.5)
    save(fig, "fig_surface")


# ------------------------------------------------------------ power curves --
def fig_power(A, sp):
    v = D.wind(sp)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(W, 2.65), constrained_layout=True)
    for r, spec in enumerate(D.ORDER):
        for j in range(A["Y"].shape[1]):
            a1.plot(v, np.exp(A["Y"][r, j]), linestyle="none", markersize=4,
                    **style.kw(spec, run=j + 1, label=lab(spec) if j == 0 else "_nolegend_"))
        a1.plot(v, A["curve"][r], color=style.SERIES[spec]["color"], linewidth=0.9, zorder=1)
        a2.plot(v, 100 * A["cp"][r], markersize=3.5, **style.kw(spec, linewidth=1.1))
    a1.set_xscale("log"); a1.set_yscale("log")
    a1.set_xticks([10, 15, 20, 30, 40]); a1.set_xticklabels(["10", "15", "20", "30", "40"])
    a1.set_xlabel("Wind speed (m/s)"); a1.set_ylabel("Peak electrical power $P_{\\max}$ (W)")
    run_legend(a1)
    tag(a1, "(a) Peak electrical power")
    a2.set_xlabel("Wind speed (m/s)"); a2.set_ylabel("$C_{P,\\mathrm{el}}$ (%)")
    a2.set_ylim(0, None)
    tag(a2, "(b) Electrical power coefficient")
    save(fig, "fig_power")


# ------------------------------------------------------- run-level result --
def fig_runs(A):
    tk = A["tk"]
    fig, ax = plt.subplots(figsize=(W, 2.35), constrained_layout=True)
    ax.axhline(0, color=style.INK_3, linewidth=0.8)
    for r, spec in enumerate(D.ORDER):
        for j, y in enumerate(A["yrj"][r]):
            ax.plot(r + (j - 0.5) * 0.12, 100 * math.expm1(y), linestyle="none", markersize=6,
                    zorder=3, **style.kw(spec, run=j + 1))
        if r == 0:
            continue
        c = tk["pairs"][(0, r)]
        ax.plot([r - 0.22, r + 0.22], [100 * c["level"]] * 2, color=style.INK, linewidth=1.2, zorder=2)
        ax.plot([r + 0.3] * 2, [100 * c["lo"], 100 * c["hi"]], color=style.INK, linewidth=1.3)
        for yy in (c["lo"], c["hi"]):
            ax.plot([r + 0.26, r + 0.34], [100 * yy] * 2, color=style.INK, linewidth=1.3)
        ax.text(r + 0.4, 100 * c["level"], f"{100 * c['level']:+.1f}%", va="center", fontsize=7.5)
    ax.set_xticks(range(len(D.ORDER)))
    ax.set_xticklabels([lab(s) for s in D.ORDER])
    ax.set_xlim(-0.5, len(D.ORDER) - 0.25)
    ax.set_ylabel("$P_{\\max}$ relative to Plain (%)")
    ax.grid(axis="x", visible=False)
    save(fig, "fig_runs")


# ------------------------------------------------- gain against wind speed --
def fig_gain(A, sp):
    v = D.wind(sp)
    fig, ax = plt.subplots(figsize=(W, 2.6), constrained_layout=True)
    hw = A["band_hw"]
    ax.fill_between(v, 100 * np.expm1(-hw), 100 * np.expm1(hw), color=style.GRID, alpha=0.9,
                    linewidth=0, zorder=0, label="95% band, one wind speed")
    ax.axhline(0, color=style.INK_3, linewidth=0.8)
    for r, spec in enumerate(D.ORDER):
        if r == 0:
            continue
        for j in range(A["gain_run"].shape[1]):
            ax.plot(v, 100 * A["gain_run"][r, j], linestyle="none", markersize=3.6, alpha=0.9,
                    **style.kw(spec, run=j + 1, label="_nolegend_"))
        ax.plot(v, 100 * A["gain"][r], color=style.SERIES[spec]["color"], linewidth=1.3,
                label=lab(spec))
    ax.set_xlabel("Wind speed (m/s)")
    ax.set_ylabel("$P_{\\max}$ relative to Plain (%)")
    run_legend(ax)
    save(fig, "fig_gain")


# ---------------------------------------------------------------- Thevenin --
def fig_thevenin(A, sp):
    v = D.wind(sp)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(W, 2.5), constrained_layout=True, sharey=True)
    for ax, key, title in ((a1, "voc_gain", "(a) Open-circuit voltage $V_{\\mathrm{oc}}$"),
                           (a2, "rint_gain", "(b) Source resistance $R_{\\mathrm{int}}$")):
        ax.axhline(0, color=style.INK_3, linewidth=0.8)
        for r, spec in enumerate(D.ORDER):
            if r:
                ax.plot(v, 100 * A[key][r], markersize=3.5, **style.kw(spec, linewidth=1.1))
        ax.set_xlabel("Wind speed (m/s)")
        tag(ax, title)
    a1.set_ylabel("Change relative to Plain (%)")
    a1.legend(loc="upper left", fontsize=7)
    save(fig, "fig_thevenin")


# ------------------------------------------------------------- rotor speed --
def fig_speed(A):
    sa = A["spd"]
    v = D.wind(sa["sp"])
    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(W, 2.45), constrained_layout=True)
    a2.axhline(0, color=style.INK_3, linewidth=0.8)
    for r, spec in enumerate(D.ORDER):
        color = style.SERIES[spec]["color"]
        for j in range(sa["n"].shape[1]):
            a1.plot(v, sa["lam"][r, j], linestyle="none", markersize=3.4,
                    **style.kw(spec, run=j + 1, label=lab(spec) if j == 0 else "_nolegend_"))
            a3.plot(sa["n"][r, j], 1000 * sa["ke"][r, j], linestyle="none", markersize=3.0,
                    **style.kw(spec, run=j + 1, label="_nolegend_"))
            if r:
                a2.plot(v, 100 * sa["gain_run"][r, j], linestyle="none", markersize=3.4,
                        **style.kw(spec, run=j + 1, label="_nolegend_"))
        a1.plot(v, sa["lam_curve"][r], color=color, linewidth=0.9, zorder=1)
        if r:
            a2.plot(v, 100 * sa["gain"][r], color=color, linewidth=1.2)
    x = np.linspace(0.95 * sa["n"].min(), 1.03 * sa["n"].max(), 100)
    f = sa["fit"]
    a3.plot(x, 1000 * (f["icept"] + f["slope"] * x) / x, color=style.INK_2, linewidth=0.9, zorder=0,
            label=f"$V_1$ = {1000 * f['slope']:.1f} mV/rpm $\\times\\, n_0$ $-$ {-f['icept']:.2f} V")
    a1.set_xlabel("Wind speed (m/s)"); a1.set_ylabel("Tip-speed ratio $\\lambda_0$ (on $R$)")
    a1.set_ylim(0, None)
    run_legend(a1, loc="lower right")
    tag(a1, "(a) Light-load tip-speed ratio")
    a2.set_xlabel("Wind speed (m/s)"); a2.set_ylabel("$n_0$ relative to Plain (%)")
    tag(a2, "(b) Speed relative to Plain")
    a3.set_xlabel("Light-load speed $n_0$ (rpm)"); a3.set_ylabel("$V_1/n_0$ (mV/rpm)")
    a3.set_xlim(0, None)
    lo_ = 1000 * sa["ke"].min()
    a3.set_ylim(lo_ - 0.55, None)                           # room for the legend below the points
    a3.legend(loc="lower right", fontsize=6.0)
    tag(a3, "(c) Voltage per rpm")
    save(fig, "fig_speed")


# ------------------------------------------------------- raw load ladders --
def fig_ladders(runs, stems, points=(700, 1200, 1800)):
    fig, axes = plt.subplots(1, len(points), figsize=(W, 2.3), constrained_layout=True)
    for ax, cmd in zip(axes, points):
        for spec in D.ORDER:
            for j, stem in enumerate(stems[spec]):
                p = runs[stem]["points"]
                lad = p[(p.fan_rpm == cmd) & (p.tracking == 1) & (p.amps > 0)]
                k = int(np.argmax(lad.watts.values))
                ax.plot(1000 * lad.amps, lad.watts, markersize=2.6, linewidth=0.8,
                        linestyle="-" if j == 0 else (0, (3, 2)),
                        **style.kw(spec, run=j + 1, label=lab(spec) if j == 0 else "_nolegend_"))
                ax.plot(1000 * lad.amps.values[k], lad.watts.values[k], marker="*", markersize=7,
                        color=style.INK, linestyle="none", zorder=4, label="_nolegend_")
        ax.set_xlabel("Load current (mA)")
        tag(ax, f"{float(D.wind(cmd)):.1f} m/s")
        ax.set_ylim(0, None)
    axes[0].set_ylabel("Electrical power (W)")
    axes[0].plot([], [], marker="*", color=style.INK, linestyle="none", label="$P_{\\max}$")
    axes[0].legend(loc="lower center", fontsize=6.5)
    save(fig, "fig_ladders")


# ----------------------------------------------------- wind calibration --
def fig_calibration(cal, fits, sp):
    fig, ax = plt.subplots(figsize=(W * 0.5, 1.95), constrained_layout=True)
    ax.axvspan(min(sp), max(sp), color=style.GRID, alpha=0.7, linewidth=0, label="1 Oct test range")
    m = cal[cal.source == "measured"]
    t = cal[cal.source != "measured"]
    ax.plot(m.rpm, m.velocity, "o", color=style.INK, markersize=4.5, label="measured")
    ax.plot(t.rpm, t.velocity, "o", color=style.INK, markerfacecolor="white", markersize=4.5,
            label="possibly trend-line value")
    x = np.linspace(0, cal.rpm.max(), 100)
    ax.plot(x, D.wind(x), color="#2a78d6", linewidth=1.2, label="adopted fit (all points)")
    a, b = fits["measured"]
    ax.plot(x, a * x + b, color="#eb6834", linewidth=1.1, linestyle=(0, (4, 2)),
            label="fit to measured points only")
    ax.set_xlabel("Fan speed (rpm)"); ax.set_ylabel("Air speed (m/s)")
    ax.set_xlim(0, None); ax.set_ylim(0, None)
    ax.legend(loc="upper left", fontsize=6.5)
    save(fig, "fig_calibration")


def make_all(A, runs, stems, sp, cal, fits):
    fig_surface(D.SCANS)
    fig_power(A, sp)
    fig_runs(A)
    fig_gain(A, sp)
    fig_thevenin(A, sp)
    fig_speed(A)
    fig_ladders(runs, stems)
    fig_calibration(cal, fits, sp)
