"""Shared loading, health flag and figure style for the Stage 1 (blade section) analysis of 15 Oct 2026.

Adapted from cfd/analysis/2026-10-13/src/section_lib.py (13 Oct). Changes:
  - input: the live table cfd/section2d/results/section_polars.csv (125 cases: the 51 of 13 Oct,
    unchanged, and 74 new ones), read only; load() stops if its SHA-256 differs from TABLE_SHA256,
    so any rebuilt table is noticed before a number moves;
  - ran_on: the 13 Oct value for the 51 old cases (cfd/analysis/2026-10-13/data/section_polars.csv),
    'unity' for the 74 new ones, checked against each case's hpc_jobs.jsonl (host uri-cpu*);
  - new_15oct marks the 74 new cases;
  - figure style: maxCo 1.25 is a half-filled marker (maxCo 2.5 filled, maxCo 5 open, as before);
    the Tu levels of the transition test use an ordinal violet ramp (validated with the dataviz
    skill's validate_palette.js --ordinal: monotone lightness, single hue, light end 2.56:1 on white).
The 13 Oct health flag is unchanged: a run is *flagged* (column `corrupted`) when
u_Co/U = maxCo dx_corner / (dt_mean U) > 5; a *healthy* run is one that is not flagged, which does
not mean converged. The 13 Oct symptoms (negative mean drag, Cd_std > |Cd_mean|, |Cl_mean| > 3, a
time-mean maximum y+ above 2) are computed as before; unlike 13 Oct, a healthy run with a symptom no
longer stops the analysis: it is reported (column symptom_without_flag).
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]           # cfd/analysis/2026-10-15
FIG = ROOT / "fig"
OUT = ROOT / "out"
REPO = ROOT.parents[2]                                # windtunnel-control
TABLE = REPO / "cfd" / "section2d" / "results" / "section_polars.csv"
TABLE_13OCT = REPO / "cfd" / "analysis" / "2026-10-13" / "data" / "section_polars.csv"
OUT_13OCT = REPO / "cfd" / "analysis" / "2026-10-13" / "out"
RUNS = REPO / "cfd" / "section2d" / "runs"
RECORDS = REPO / "cfd" / "section2d" / "results" / "records"
SECTION_CSV = REPO / "cfd" / "geometry" / "section_v1.csv"
N_CASES = 125
TABLE_SHA256 = "316e5000231866448da8ded6a5e48899705e069fbdd4947f0b3f2d6e7323c6aa"   # 15 Oct table

C_REF = 0.048                                         # m, reference chord
NU = 1.516e-5                                         # m^2/s
DX_CORNER = {"coarse": 64e-6, "medium": 45e-6, "fine": 32e-6}
LEVEL_ORDER = {"coarse": 0, "medium": 1, "fine": 2}
U_CO_LIMIT = 5.0
CHORD_DIR_DEG = 85.23635850611012
STATE_CD = 2.5                                        # alpha-0 state boundary (13 Oct)

# Literature, as quoted in cfd/PLAN.md: 2D semicircular shell, drag on the frontal width. Not this blade.
LIT_CD_CONCAVE = 2.3
LIT_CD_CONVEX = 1.2

# the two cases outside the table used here (read only)
UNITY_REPEAT = "_unity_a000.0_U23.0_SST_medium_Tu1.0"   # the Mac's maxCo-5 alpha-0 case repeated on Unity
RESTART_A = "_hyst_Co5to2p5_a000"                       # high-drag field (maxCo 5) continued at maxCo 2.5
RESTART_B = "_hyst_Co2p5to5_a000"                       # low-drag field (maxCo 2.5) continued at maxCo 5


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frontal_width(alpha_deg):
    """Projected width (m) of the section normal to the free stream at alpha (body frame)."""
    xy = pd.read_csv(SECTION_CSV).to_numpy()
    ey = np.deg2rad(CHORD_DIR_DEG)
    ex = ey - np.pi / 2
    e_x = np.array([np.cos(ex), np.sin(ex)])
    e_y = np.array([np.cos(ey), np.sin(ey)])
    a = np.deg2rad(np.atleast_1d(alpha_deg).astype(float))
    out = []
    for ai in a:
        n = -np.sin(ai) * e_x + np.cos(ai) * e_y
        s = xy @ n
        out.append(s.max() - s.min())
    out = np.array(out)
    return out if out.size > 1 else float(out[0])


def short_name(r):
    lvl = {"coarse": "c", "medium": "m", "fine": "f"}[r["level"]]
    return f"a{r['alpha_deg']:g} {r['U_ms']:g}m/s {r['model']} {lvl} Tu{r['Tu_body_pct']:g} Co{r['maxCo']:g}"


def ran_on_column(d):
    """13 Oct ran_on for the old cases; 'unity' for new cases whose every job ran on a uri-cpu node."""
    old = pd.read_csv(TABLE_13OCT).set_index("name")["ran_on"]
    out = []
    for name in d["name"]:
        if name in old.index:
            out.append(old[name])
            continue
        jobs = [json.loads(s) for s in (RUNS / name / "hpc_jobs.jsonl").read_text().splitlines() if s.strip()]
        hosts = {j.get("host", "") for j in jobs}
        if not hosts or not all(h.startswith("uri-cpu") for h in hosts):
            raise RuntimeError(f"{name}: hosts {hosts} are not all Unity nodes")
        out.append("unity")
    return out


def load(check_hash=True):
    if check_hash:
        h = sha256(TABLE)
        if h != TABLE_SHA256:
            raise SystemExit(f"{TABLE} changed (sha256 {h}); re-check every quoted number before updating TABLE_SHA256")
    d = pd.read_csv(TABLE)
    if len(d) != N_CASES or d["name"].duplicated().any():
        raise SystemExit(f"expected {N_CASES} unique cases, found {len(d)}")
    old_names = set(pd.read_csv(TABLE_13OCT)["name"])
    d["new_15oct"] = ~d["name"].isin(old_names)
    d["ran_on"] = ran_on_column(d)
    d["u_co_over_U"] = d["maxCo"] * d["level"].map(DX_CORNER) / (d["dt_mean_s"] * d["U_ms"])
    d["dt_conv"] = d["dt_mean_s"] * d["U_ms"] / C_REF
    d["Cd_relstd"] = d["Cd_std"] / d["Cd_mean"].abs()
    d["Cd_drift_rel"] = d["Cd_drift"] / d["Cd_mean"].abs()
    d["Cd_se"] = d["Cd_std"] / np.sqrt(d["n_cycles_avg"].clip(lower=1.0))
    d["short"] = d.apply(short_name, axis=1)
    d["level_i"] = d["level"].map(LEVEL_ORDER)
    widths = {a: frontal_width(a) for a in sorted(d["alpha_deg"].unique())}
    d["d_frontal_mm"] = d["alpha_deg"].map(widths) * 1e3
    d["Cd_on_frontal"] = d["Cd_mean"] * C_REF * 1e3 / d["d_frontal_mm"]
    return flag_cases(d)


def flag_cases(d):
    d = d.copy()
    d["neg_drag"] = d["Cd_mean"] < 0
    d["std_gt_mean"] = d["Cd_std"] > d["Cd_mean"].abs()
    d["cl_gt3"] = d["Cl_mean"].abs() > 3
    d["implausible_forces"] = d["neg_drag"] | d["std_gt_mean"] | d["cl_gt3"]
    d["yplus_spike"] = d["yplus_max_mean"] > 2
    d["any_symptom"] = d["implausible_forces"] | d["yplus_spike"]
    d["corrupted"] = d["u_co_over_U"] > U_CO_LIMIT          # the 13 Oct flag
    d["symptom_without_flag"] = d["any_symptom"] & ~d["corrupted"]
    unsteady = d["Cl_std"] >= 1e-3
    clean = d["St_peak_frac"] >= 0.5
    d["St_status"] = np.select(
        [d["corrupted"], ~unsteady, unsteady & clean, unsteady & ~clean],
        ["corrupted run", "steady (Cl_std < 0.001)", "clean peak", "broadband (peak frac < 0.5)"],
        default="?")
    a0 = (d["alpha_deg"] == 0) & ~d["corrupted"]
    d["branch_a0"] = np.where(a0, np.where(d["Cd_mean"] > STATE_CD, "high-drag", "low-drag"), "")
    return d


def pick(d, **kw):
    m = np.ones(len(d), bool)
    for k, v in kw.items():
        m &= (d[k] == v).to_numpy()
    return d[m]


def one(d, **kw):
    r = pick(d, **kw)
    if len(r) != 1:
        raise KeyError(f"{kw}: {len(r)} rows")
    return r.iloc[0]


def pct(a, b):
    return 100.0 * (a - b) / abs(b)


# ---------------------------------------------------------------- figure style (13 Oct, extended)
BLACK = "#000000"
GREY = "#8c8c8c"           # flagged runs
LIGHT = "#d9d9d9"
LIT = "#5a5a5a"            # literature markers
NOTE = "#444444"           # annotation ink
JUMPC = "#f2c4c4"          # 1-c/U intervals with a force jump (13 Oct addendum)
WINC = "#ececec"           # averaging window
# Tu levels of the transition test (LM): ordinal violet ramp, light -> dark = Tu 0.5 -> 3 %;
# line styles carry the same order (dotted, solid, dash-dot), so colour is never the only cue
TU_COLOR = {0.5: "#a497ea", 1.0: "#735acc", 3.0: "#452b8a"}
TU_LS = {0.5: ":", 1.0: "-", 3.0: "-."}


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


MODEL_MARKER = {"LM": "o", "SST": "s"}
MODEL_LS = {"LM": "-", "SST": "--"}


def mstyle(model, maxco, corrupted=False, color=BLACK):
    """Marker: shape by model; fill by maxCo (5 open, 2.5 filled, 1.25 half-filled, lower half);
    a flagged run is a grey x."""
    if corrupted:
        return dict(marker="x", color=GREY, mec=GREY, mfc="none", ms=4.5, mew=0.9)
    co = float(maxco)
    st = dict(marker=MODEL_MARKER[model], color=color, mec=color, ms=4.5, mew=0.9)
    if co >= 5:
        st.update(mfc="white")
    elif co >= 2.5:
        st.update(mfc=color)
    else:
        st.update(mfc=color, fillstyle="bottom", markerfacecoloralt="white")
    return st


def save(fig, name):
    FIG.mkdir(exist_ok=True)
    out = FIG / name
    fig.savefig(out, dpi=200, facecolor="white")
    import matplotlib.pyplot as plt
    plt.close(fig)
    print(out)
    return out
