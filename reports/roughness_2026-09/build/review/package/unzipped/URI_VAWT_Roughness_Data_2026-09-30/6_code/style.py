"""Figure style for the roughness report.

One identity per condition, used in every figure. The first three hues are
the reference palette's slots 1-3, which validate all-pairs in light mode
(worst CVD dE 9.2, normal-vision dE 24.0). The two Jeong-lab series only ever
appear beside Ra 20 (blue), and that trio also validates all-pairs. Every
series carries its own marker too, so identity survives greyscale printing.
"""
import matplotlib as mpl

TEXT_W_IN = 6.5          # LaTeX \textwidth at 1in margins on letter paper

INK = "#0b0b0b"
INK_2 = "#52514e"
INK_3 = "#8a8983"
GRID = "#e4e3de"
SURFACE = "#ffffff"

SERIES = {
    # rig specimens, in roughness order (adjacent-pair validated as a line palette)
    "v1_smooth": dict(color="#4a3aa7", marker="D", label="No texture"),
    "v1_Ra10":  dict(color="#e87ba4", marker="v", label="Ra 10 (0.025 mm)"),
    "v1_Ra20":  dict(color="#2a78d6", marker="o", label="Ra 20 (0.050 mm)"),
    "v1_Ra40":  dict(color="#eb6834", marker="s", label="Ra 40 (0.101 mm)"),
    "v1_Ra80":  dict(color="#1baf7a", marker="^", label="Ra 80 (0.202 mm)"),
    # Jeong-lab tests: violet = the same no-texture specimen type, hollow = lab data
    "jl_0727":  dict(color="#4a3aa7", marker="D", label="No texture, Jeong lab 27 Jul"),
    "jl_0605":  dict(color="#008300", marker="P", label="Initial reference, Jeong lab 5 Jun"),
}
RA_ORDER = ["v1_Ra20", "v1_Ra40", "v1_Ra80"]


def apply():
    mpl.rcParams.update({
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.03,
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 8.5,
        "axes.titlesize": 9,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.labelsize": 8.5,
        "axes.labelcolor": INK,
        "axes.edgecolor": INK_3,
        "axes.linewidth": 0.6,
        "axes.grid": True,
        "axes.axisbelow": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.prop_cycle": mpl.cycler(color=[SERIES[k]["color"] for k in RA_ORDER]),
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "grid.linestyle": "-",
        "xtick.color": INK_2,
        "ytick.color": INK_2,
        "xtick.labelsize": 7.5,
        "ytick.labelsize": 7.5,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.major.size": 3,
        "ytick.major.size": 3,
        "lines.linewidth": 1.5,
        "lines.markersize": 4.5,
        "lines.markeredgewidth": 0.8,
        "lines.markeredgecolor": SURFACE,
        "legend.fontsize": 7.5,
        "legend.frameon": False,
        "legend.handlelength": 2.2,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })


def kw(key, **over):
    """Line/marker kwargs for a condition, e.g. ax.plot(x, y, **kw('v1_Ra40')).
    A remount ('v1_Ra20_repeat') wears its parent's colour with hollow markers."""
    parent = key.split("_repeat")[0]
    s = SERIES[parent]
    if parent != key:
        d = dict(color=s["color"], marker=s["marker"], label=s["label"].split(" (")[0] + " remount",
                 markerfacecolor=SURFACE, markeredgecolor=s["color"], markeredgewidth=1.0,
                 linewidth=1.0, linestyle=(0, (4, 2)))
        d.update(over)
        return d
    d = dict(color=s["color"], marker=s["marker"], label=s["label"],
             markeredgecolor=SURFACE, markeredgewidth=0.8, linewidth=1.5)
    d.update(over)
    return d
