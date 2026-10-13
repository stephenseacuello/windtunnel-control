"""Shared loading, quality flags and figure style for the Stage 1 (blade section) analysis.

Input : ../data/section_polars.csv (merged Mac + Unity table of 13 Oct 2026, 51 cases).
Used by section_analysis.py (tables, numbers) and section_figures.py (PNGs).

Conventions (cfd/section2d/README.md section 1): alpha 0 = concave side to the wind,
180 = convex side to the wind; coefficients per unit span on c_ref = 48.0 mm; Cm about the
section centroid, counter-clockwise positive. SST = kOmegaSST (fully turbulent),
LM = kOmegaSSTLM (gamma-ReTheta transition).

Quality flag (computed here, see flag_cases):
  u_Co/U  = maxCo * dx_corner / (dt_mean * U), the speed (in units of U) that the solver's
            Courant-number control reacts to in a corner-sized cell. OpenFOAM's adjustTimeStep
            sets dt from the flux field only (pimpleFoam setDeltaT.H), so a run whose mean dt
            is several times smaller than its neighbours' had much faster near-wall flow.
            It is a proxy, not a measured velocity.
  'corrupted' = u_Co/U > U_CO_LIMIT. In this table the 51 cases split into 2.2-4.5 and
            6.3-32 with nothing in between. Every case above the limit also has at least one
            independent symptom (negative mean drag, Cd_std > |Cd_mean|, |Cl_mean| > 3, or a
            time-mean of the maximum y+ above 2), and no case below it has any;
            section_analysis.py checks this and stops if it ever fails.
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]          # cfd/analysis/2026-10-13
DATA = ROOT / "data"
FIG = ROOT / "fig"
OUT = ROOT / "out"
REPO = ROOT.parents[2]                                # windtunnel-control
SECTION_CSV = REPO / "cfd" / "geometry" / "section_v1.csv"

C_REF = 0.048                                         # m, reference chord (README section 1)
NU = 1.516e-5                                         # m^2/s (README section 3)
# wall spacing at the square corners per mesh level (README section 2, "Levels")
DX_CORNER = {"coarse": 64e-6, "medium": 45e-6, "fine": 32e-6}
LEVEL_ORDER = {"coarse": 0, "medium": 1, "fine": 2}
U_CO_LIMIT = 5.0
# chord direction in the CAD frame (cfd/geometry/section_v1.json, chord_direction_deg_from_x);
# +y_body points along it, +x_body is 90 deg clockwise from it (README section 1)
CHORD_DIR_DEG = 85.23635850611012

# Literature, as quoted in cfd/PLAN.md ("Validation without a load cell"): 2D semicircular
# (half-cylinder) shell, drag on the frontal width (the diameter). Not this blade.
LIT_CD_CONCAVE = 2.3
LIT_CD_CONVEX = 1.2


def frontal_width(alpha_deg):
    """Projected width (m) of the section normal to the free stream at alpha (body frame),
    from the 49-point outline cfd/geometry/section_v1.csv (chord error 0.048 mm)."""
    xy = pd.read_csv(SECTION_CSV).to_numpy()
    ey = np.deg2rad(CHORD_DIR_DEG)
    ex = ey - np.pi / 2
    e_x = np.array([np.cos(ex), np.sin(ex)])
    e_y = np.array([np.cos(ey), np.sin(ey)])
    a = np.deg2rad(np.atleast_1d(alpha_deg).astype(float))
    out = []
    for ai in a:
        n = -np.sin(ai) * e_x + np.cos(ai) * e_y          # lift direction in the CAD frame
        s = xy @ n
        out.append(s.max() - s.min())
    out = np.array(out)
    return out if out.size > 1 else float(out[0])


def short_name(r):
    lvl = {"coarse": "c", "medium": "m", "fine": "f"}[r["level"]]
    s = f"a{r['alpha_deg']:g} {r['U_ms']:g}m/s {r['model']} {lvl} Tu{r['Tu_body_pct']:g} Co{r['maxCo']:g}"
    return s


def load():
    d = pd.read_csv(DATA / "section_polars.csv")
    d["u_co_over_U"] = d["maxCo"] * d["level"].map(DX_CORNER) / (d["dt_mean_s"] * d["U_ms"])
    d["dt_conv"] = d["dt_mean_s"] * d["U_ms"] / C_REF          # time step in c/U
    d["Cd_relstd"] = d["Cd_std"] / d["Cd_mean"].abs()
    d["Cd_drift_rel"] = d["Cd_drift"] / d["Cd_mean"].abs()
    # sampling error of a window mean, rough: one independent sample per shedding cycle
    d["Cd_se"] = d["Cd_std"] / np.sqrt(d["n_cycles_avg"].clip(lower=1.0))
    d["short"] = d.apply(short_name, axis=1)
    d["level_i"] = d["level"].map(LEVEL_ORDER)
    widths = {a: frontal_width(a) for a in sorted(d["alpha_deg"].unique())}
    d["d_frontal_mm"] = d["alpha_deg"].map(widths) * 1e3
    d["Cd_on_frontal"] = d["Cd_mean"] * C_REF * 1e3 / d["d_frontal_mm"]
    d["St_on_frontal"] = d["St"] * d["d_frontal_mm"] / (C_REF * 1e3)
    return flag_cases(d)


def flag_cases(d):
    d = d.copy()
    d["neg_drag"] = d["Cd_mean"] < 0
    d["std_gt_mean"] = d["Cd_std"] > d["Cd_mean"].abs()
    d["cl_gt3"] = d["Cl_mean"].abs() > 3
    d["implausible_forces"] = d["neg_drag"] | d["std_gt_mean"] | d["cl_gt3"]
    # design y+ <= 1 away from the corners (README section 2); healthy runs stay <= 1.7
    d["yplus_spike"] = d["yplus_max_mean"] > 2
    d["any_symptom"] = d["implausible_forces"] | d["yplus_spike"]
    d["corrupted"] = d["u_co_over_U"] > U_CO_LIMIT
    unsteady = d["Cl_std"] >= 1e-3
    clean = d["St_peak_frac"] >= 0.5
    d["St_status"] = np.select(
        [d["corrupted"], ~unsteady, unsteady & clean, unsteady & ~clean],
        ["corrupted run", "steady (Cl_std < 0.001)", "clean peak", "broadband (peak frac < 0.5)"],
        default="?")
    # alpha 0 branches (two clusters of healthy runs; see section_analysis.py)
    a0 = (d["alpha_deg"] == 0) & ~d["corrupted"]
    d["branch_a0"] = np.where(a0, np.where(d["Cd_mean"] > 2.5, "high-drag shedding", "low-drag"), "")
    return d


# ---------------------------------------------------------------- figure style
BLACK = "#000000"
GREY = "#8c8c8c"           # flagged (corrupted) runs
LIGHT = "#d9d9d9"
LIT = "#5a5a5a"            # literature markers (shape carries the identity)


def style():
    import matplotlib as mpl
    mpl.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
        "font.size": 8,
        "axes.labelsize": 8,
        "axes.titlesize": 8,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "legend.fontsize": 6.5,
        "axes.linewidth": 0.6,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.major.size": 2.5,
        "ytick.major.size": 2.5,
        "lines.linewidth": 1.2,
        "lines.markersize": 4.5,
        "axes.grid": True,
        "grid.color": "#e6e6e6",
        "grid.linewidth": 0.5,
        "grid.linestyle": "-",
        "axes.axisbelow": True,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "savefig.dpi": 200,
        "legend.frameon": False,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "mathtext.default": "regular",
    })


# model -> marker and line style (SST dashed, LM solid); maxCo 2.5 filled, maxCo 5 open
MODEL_MARKER = {"LM": "o", "SST": "s"}
MODEL_LS = {"LM": "-", "SST": "--"}


def mstyle(model, maxco, corrupted=False):
    if corrupted:
        return dict(marker="x", color=GREY, mec=GREY, mfc="none", ms=4.5, mew=0.9)
    filled = float(maxco) < 5
    return dict(marker=MODEL_MARKER[model], color=BLACK, mec=BLACK,
                mfc=BLACK if filled else "white", ms=4.5, mew=0.9)
