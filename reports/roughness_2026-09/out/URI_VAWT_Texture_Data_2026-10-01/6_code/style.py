"""Figure style for the 1 October 2026 texture report.

One identity per blade set, used in every figure: a hue from the validated
reference palette (all pairs distinguishable under colour-vision deficiency)
plus its own marker, so identity survives greyscale printing. The second run
of a rotor wears the same colour with a hollow marker.
"""
import matplotlib as mpl

TEXT_W_IN = 6.5          # LaTeX \textwidth at 1 in margins on letter paper

INK = "#0b0b0b"
INK_2 = "#52514e"
INK_3 = "#8a8983"
GRID = "#e4e3de"
SURFACE = "#ffffff"

SERIES = {
    "v1_smooth": dict(color="#4a3aa7", marker="D", label="Plain"),
    "v1_Ra20": dict(color="#2a78d6", marker="o", label="FS 0.05"),
    "v1_Ra40": dict(color="#eb6834", marker="s", label="FS 0.10"),
    "v1_Ra80": dict(color="#1baf7a", marker="^", label="FS 0.20"),
}


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
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "xtick.color": INK_2,
        "ytick.color": INK_2,
        "xtick.labelsize": 7.5,
        "ytick.labelsize": 7.5,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.major.size": 3,
        "ytick.major.size": 3,
        "lines.linewidth": 1.4,
        "lines.markersize": 4.5,
        "lines.markeredgewidth": 0.9,
        "legend.fontsize": 7.5,
        "legend.frameon": False,
        "legend.handlelength": 2.2,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })


def kw(spec, run=1, **over):
    """Line and marker kwargs for a blade set; run 2 is hollow."""
    s = SERIES[spec]
    d = dict(color=s["color"], marker=s["marker"], label=s["label"], markeredgecolor=s["color"],
             markerfacecolor=s["color"] if run == 1 else SURFACE)
    d.update(over)
    return d
