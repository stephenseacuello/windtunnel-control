#!/usr/bin/env python3
r"""Figures, numbers and provenance for the CFD verification report (cfd_verification.tex).

    cd reports/cfd_verification_2026-12 && python3 make_figures.py
    latexmk -pdf -interaction=nonstopmode -halt-on-error cfd_verification.tex

Why
  The report answers Dr. Jahangiri's requests of 1 Nov 2026 (J1 mesh and time step, J2 how
  turbulence and roughness are modelled, J3 the flow and forces through the rotation, J4 why the
  gains appear only at high roughness; J5-J7 experiments) and the items of the 7 Oct meeting,
  from data already on disk. The verification runs (B1, submitted to Unity on 15 Nov) and the
  mechanism runs (B2) have not finished. So that the report builds at every stage, every number it
  quotes is a macro written here into numbers.tex, and a number whose source does not exist yet
  prints \pending. Re-running this script after cfd/hpc/pull_results.py has added the B1 rows to
  the result tables, or after cfd/analysis/2026-11-15/ has written its tables, fills those in.

Reads (read only; 'local' = git-ignored, on the Mac only)
  cfd/analysis/2026-10-13/out/section_grid.csv             smooth-section mesh study (maxCo 2.5)
  cfd/analysis/2026-10-15/out/section_timestep_changes.csv, section_timestep.csv,
      section_case_quality.csv
  cfd/analysis/2026-10-15/out/roughness_wf_effects.csv, roughness_tex_effects.csv,
      roughness_tex_timestep.csv, roughness_measured.csv
  cfd/analysis/2026-10-15/out/rotor_roughness.csv, rotor_roughness_sectors.csv, rotor_numbers.json
  cfd/analysis/2026-11-15/out/surface_summary.csv, surface_profiles.csv, rotor_phase_force.csv,
      rotor_phase_force_sectors.csv, rotor_phase_force_check.csv   if present; else 'pending'
  cfd/section2d/results/section_polars.csv, cfd/stage2/results/stage2_polars.csv,
      cfd/rotor2d/results/rotor_cp.csv, rotor_static.csv   counts, cells, time steps; the B1 rows
  cfd/stage2/queues/S2f_verify.txt, cfd/section2d/queues/priority7_verify.txt,
      cfd/rotor2d/queues/priorityF_verify.txt              the B1 queue lines
  cfd/hpc/jobs/submitted.log (local)                        cross-check of the B1 case names
  cfd/*/runs/*/hpc_jobs.jsonl (local)                       core-hours of the October jobs
  cfd/section2d/runs/_cont_Co1p25to1p25_a000/, _hyst_Co5to1p25_a000/ case.json and
      run_hysteresis.sbatch (local)                         the two B1 restarts
  reports/roughness_2026-09/build/derived/surface_roughness.csv      measured Ra, layer period
  reports/roughness_2026-09/out/URI_VAWT_Texture_Data_2026-10-01_rev2/4_derived/
      rotor_speed_by_dwell.csv (local; its tracked copy build/tacho/derived/ is read if it is absent)
  stated_values.csv (this folder)   numbers with no table behind them, one row each with its source

Writes (this folder only)
  fig1_numerics, fig2_surface, fig3_rotor_phase, fig4_ksplus, fig5_rotor_speed (.pdf and .png), the
  report's Figs 1-5; figB1_checks (.pdf, .png), the B1 results against the existing values, drawn for
  the revision after B1 and not in the 15 Nov draft (it shows only open slots until the runs finish);
  numbers.tex (one \newcommand per quoted number, its source in a comment); provenance.tex (git hash,
  build date, SHA-256 prefix and git status of every input)

Conventions
  As cfd/analysis/2026-10-15/README.md. Section alpha 0: cup to the wind; 90: edge-on, flow from
  tip A; 180: convex side to the wind. Rotor: assembly A, curled tip leading, 23 m/s; blade azimuth
  theta 0 upwind (convex side to the wind), 90 advancing edge-on, 180 cup to the wind, 270
  returning edge-on. A change is rough minus smooth with the same wall treatment (Ks 0 with the
  rough wall function; t 0 on the texture mesh): section changes in % of the reference Cd, rotor
  changes in C_Q with +-2u (twice the averaging uncertainty). Case labels (alpha, lambda, Ks, t,
  maxCo, dates) are typed in the report; results, estimates, counts and costs are macros. A missing
  source prints \pending, never a guess; a git-ignored source missing on another machine prints
  \localonly.
"""
import csv
import datetime
import hashlib
import json
import math
import re
import subprocess
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
A13, A15, A1115 = "cfd/analysis/2026-10-13/out", "cfd/analysis/2026-10-15/out", "cfd/analysis/2026-11-15/out"
SELF = "reports/cfd_verification_2026-12"

# Palette, style and save() as reports/cfd_2026-10/make_figures.py.
NAVY, GOLD, GREY, INK2 = "#002147", "#B8860B", "#9A9890", "#52514E"
INK, RULE, NOTE = "#0B0B0B", "#C9C8C2", "#F4F3EF"
SET_COLOUR = {"Plain": INK, "FS 0.05": "#9DB4CF", "FS 0.10": "#4F7AA8", "FS 0.20": NAVY}
plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
                     "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.edgecolor": INK2, "axes.labelcolor": "#0B0B0B", "xtick.color": INK2,
                     "ytick.color": INK2, "axes.titleweight": "bold", "axes.titlesize": 10.5})


def save(fig, name):
    for ext in ("pdf", "png"):
        fig.savefig(HERE / f"{name}.{ext}", dpi=220, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------ inputs, numbers, formatting
INPUTS = {}    # label -> list of absolute paths (one file, or a group of local files)


def use(rel):
    """Register a repository file as an input (for provenance.tex) and return its path."""
    INPUTS.setdefault(rel, [REPO / rel])
    return REPO / rel


def read_csv(rel):
    with open(use(rel), newline="") as f:
        return list(csv.DictReader(f))


def one(rows, what, **kw):
    hit = [r for r in rows if all(r.get(k) == v for k, v in kw.items())]
    if len(hit) != 1:
        raise SystemExit(f"{what}: expected one row with {kw}, found {len(hit)}")
    return hit[0]


def rnd(x, nd):
    """Round half up (not to even), as a reader expects."""
    q = Decimal(1).scaleb(-nd)
    return float(Decimal(repr(float(x))).quantize(q, rounding=ROUND_HALF_UP))


def fnum(x, nd=0, sign=False):
    v = rnd(x, nd)
    v = 0.0 if v == 0 else v
    s = f"{abs(v):,.{nd}f}".replace(",", "{,}")
    if v < 0:
        return r"\textminus{}" + s
    return "+" + s if sign and v > 0 else s


class Numbers:
    """numbers.tex: one macro per quoted number, with its source in a comment."""

    def __init__(self):
        self.rows, self.names = [], set()

    def tex(self, name, tex, src):
        if not re.fullmatch(r"n[A-Z][A-Za-z]*", name):
            raise SystemExit(f"bad macro name {name}")
        if name in self.names:
            raise SystemExit(f"duplicate macro {name}")
        self.names.add(name)
        self.rows.append((name, tex, " ".join(str(src).split())))

    def num(self, name, x, nd, src, sign=False):
        if x is None or not math.isfinite(float(x)):
            self.pending(name, src)
        else:
            self.tex(name, fnum(x, nd, sign), src)

    def pending(self, name, src):
        self.tex(name, r"\pending", f"{src} [no data yet]")

    def write(self, path):
        out = ["% numbers.tex: generated by make_figures.py; do not edit.",
               "% Every number the report quotes, with its source (file, row, column) after the %.",
               r"\providecommand{\pending}{\textit{pending}}",
               r"\providecommand{\localonly}{\textit{local}}"]
        out += [f"\\newcommand{{\\{n}}}{{{t}}}% {s}" for n, t, s in self.rows]
        path.write_text("\n".join(out) + "\n")


N = Numbers()
SV_USED = set()
SV = {r["key"]: r for r in read_csv(f"{SELF}/stated_values.csv")}


def sv(key):
    SV_USED.add(key)
    return float(SV[key]["value"])


def svs(key):
    r = SV[key]
    return f"stated_values.csv {key}: {r['source']}"


def stated(name, key, nd):
    N.num(name, sv(key), nd, svs(key))


# =================================================================== J1: smooth section (low-Re SST)
grid = read_csv(f"{A13}/section_grid.csv")
G = {(r["alpha_deg"], r["quantity"]): r for r in grid}
for key, verdict in ((("90", "Cd_mean"), "monotonic"), (("90", "Cl_mean"), "diverging"),
                     (("0", "Cd_mean"), "oscillatory"), (("180", "Cd_mean"), "oscillatory")):
    if not G[key]["verdict"].startswith(verdict):   # the report's wording depends on these verdicts
        raise SystemExit(f"section_grid.csv {key}: verdict changed to {G[key]['verdict']!r}")
gsrc = f"{A13}/section_grid.csv"
N.num("nGciCdNinety", float(G[("90", "Cd_mean")]["GCI_fine_pct"]), 1, f"{gsrc} alpha 90 Cd_mean GCI_fine_pct")
N.num("nSpreadClNinety", float(G[("90", "Cl_mean")]["spread_pct_of_fine"]), 0, f"{gsrc} alpha 90 Cl_mean spread_pct_of_fine")
N.num("nSpreadCdZero", float(G[("0", "Cd_mean")]["spread_pct_of_fine"]), 1, f"{gsrc} alpha 0 Cd_mean spread_pct_of_fine")
N.num("nSpreadCdOneEighty", float(G[("180", "Cd_mean")]["spread_pct_of_fine"]), 1, f"{gsrc} alpha 180 Cd_mean spread_pct_of_fine")
mesh_sm90 = float(G[("90", "Cd_mean")]["spread_pct_of_fine"])
mesh_sm180 = float(G[("180", "Cd_mean")]["spread_pct_of_fine"])

tsc = read_csv(f"{A15}/section_timestep_changes.csv")
sst180 = one(tsc, "section_timestep_changes", alpha="180", model="SST", maxCo_a="1.25", maxCo_b="2.5")
lm180 = one(tsc, "section_timestep_changes", alpha="180", model="LM", maxCo_a="1.25", maxCo_b="2.5")
step_sm180 = float(sst180["dCd_pct"])
N.num("nTsDropSST", -step_sm180, 1, f"{A15}/section_timestep_changes.csv alpha 180 SST maxCo 1.25 vs 2.5, -dCd_pct")
N.num("nTsDropLM", -float(lm180["dCd_pct"]), 1, f"{A15}/section_timestep_changes.csv alpha 180 LM maxCo 1.25 vs 2.5, -dCd_pct")

tstep = read_csv(f"{A15}/section_timestep.csv")
z5 = one(tstep, "section_timestep", alpha="0", model="SST", maxCo="5")
z25 = one(tstep, "section_timestep", alpha="0", model="SST", maxCo="2.5")
z125 = one(tstep, "section_timestep", alpha="0", model="SST", maxCo="1.25")
tsrc = f"{A15}/section_timestep.csv alpha 0 SST"
N.num("nZeroCdFive", float(z5["Cd"]), 2, f"{tsrc} maxCo 5 Cd ({z5['state']})")
N.num("nZeroCdTwoFive", float(z25["Cd"]), 2, f"{tsrc} maxCo 2.5 Cd ({z25['state']})")
N.num("nZeroCdLastTen", float(z125["Cd_last10"]), 2, f"{tsrc} maxCo 1.25 Cd_last10")

# wall data around the single blade (cfd/analysis/2026-11-15/src/surface_extract.py; 'pending' until written)
SURF_SUM, SURF_PROF = REPO / A1115 / "surface_summary.csv", REPO / A1115 / "surface_profiles.csv"
SURF_CASES = {"WfNinetyZero": "a090.0_U23.0_SST_wf_Ks0_Tu1.0_Co2.5n2", "WfNinetyFour": "a090.0_U23.0_SST_wf_Ks400_Tu1.0_Co2.5n2",
              "TexZeroTwoFive": "a180.0_U23.0_SST_tex0.000_s1_Tu1.0_Co2.5n2", "TexTwoTwoFive": "a180.0_U23.0_SST_tex0.200_s1_Tu1.0_Co2.5n2",
              "TexZeroFive": "a180.0_U23.0_SST_tex0.000_s1_Tu1.0_N80A50", "TexTwoFive": "a180.0_U23.0_SST_tex0.200_s1_Tu1.0_N80A50",
              "MedTwoFive": "a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2", "MedOneTwoFive": "a180.0_U23.0_SST_medium_Tu1.0_Co1.25n2"}
SURF_COLS = {"Cp": ("Cp_min_B_1mm", 2), "Sep": ("sep_B_from_stag_over_c", 2), "Cdp": ("Cd_p_convex", 3)}
surf = {r["name"]: r for r in read_csv(f"{A1115}/surface_summary.csv")} if SURF_SUM.exists() else {}


def sval(case, col):
    r = surf.get(case)
    return float(r[col]) if r and r.get(col) not in (None, "") else None


N.num("nSurfCases", len(surf) if surf else None, 0, f"{A1115}/surface_summary.csv rows")
for stem, case in SURF_CASES.items():
    for q, (col, nd) in SURF_COLS.items():
        N.num(f"nS{q}{stem}", sval(case, col), nd, f"{A1115}/surface_summary.csv {case} {col}")
for nm, (a, b) in {"Ninety": ("WfNinetyZero", "WfNinetyFour"), "Tex": ("TexZeroTwoFive", "TexTwoTwoFive"),
                   "Med": ("MedTwoFive", "MedOneTwoFive")}.items():
    va, vb = sval(SURF_CASES[a], "sep_B_from_stag_over_c"), sval(SURF_CASES[b], "sep_B_from_stag_over_c")
    N.num(f"nSSepShift{nm}", None if va is None or vb is None else va - vb, 2,
          f"{A1115}/surface_summary.csv sep_B_from_stag_over_c, {SURF_CASES[a]} minus {SURF_CASES[b]} (chords)")

# pressure drag share over the healthy section runs (a pressure-tap section would miss the rest)
quality = {r["name"]: r for r in read_csv(f"{A15}/section_case_quality.csv")}
sec = {r["name"]: r for r in read_csv("cfd/section2d/results/section_polars.csv")}
st2 = {r["name"]: r for r in read_csv("cfd/stage2/results/stage2_polars.csv")}
rcp = {r["name"]: r for r in read_csv("cfd/rotor2d/results/rotor_cp.csv")}
rstat = read_csv("cfd/rotor2d/results/rotor_static.csv")
healthy = [n for n, q in quality.items() if q["corrupted"] == "False" and n in sec]
pshare = min(float(sec[n]["Cd_pressure_mean"]) / float(sec[n]["Cd_mean"]) for n in healthy)
N.num("nPressShareMin", 100 * pshare, 1, f"section_polars.csv min Cd_pressure_mean/Cd_mean over the {len(healthy)} runs with corrupted False in {A15}/section_case_quality.csv")
N.num("nPressViscMax", 100 * (1 - pshare), 1, "100 - nPressShareMin: largest viscous share of Cd over the healthy section runs")
N.num("nHealthyRuns", len(healthy), 0, f"{A15}/section_case_quality.csv corrupted False")

# =================================================================== B1: case names and queue lines
# From cfd/hpc/jobs/submitted.log, 15 Nov 2026 (local); the queue files below hold the same lines.
B1 = {
    "T1": [("stage2", "a180.0_U23.0_SST_tex0.000_s1_Tu1.0_Co1.25n2"), ("stage2", "a180.0_U23.0_SST_tex0.200_s1_Tu1.0_Co1.25n2")],
    "T2a": [("stage2", "a180.0_U23.0_SST_tex0.000_s1_n10_Tu1.0_Co2.5n2"), ("stage2", "a180.0_U23.0_SST_tex0.200_s1_n10_Tu1.0_Co2.5n2")],
    "E90t": [("stage2", "a090.0_U23.0_SST_tex0.000_s1_Tu1.0_Co2.5n2"), ("stage2", "a090.0_U23.0_SST_tex0.200_s1_Tu1.0_Co2.5n2"),
             ("stage2", "a090.0_U23.0_SST_tex0.000_s1_Tu1.0_Co1.25n2"), ("stage2", "a090.0_U23.0_SST_tex0.200_s1_Tu1.0_Co1.25n2")],
    "S1": [("section2d", "a180.0_U23.0_SST_medium_Tu1.0_Co0.625n2"), ("section2d", "a180.0_U23.0_SST_coarse_Tu1.0_Co1.25n2"),
           ("section2d", "a180.0_U23.0_SST_fine_Tu1.0_Co1.25n2")],
    "E90s": [("section2d", "a090.0_U23.0_SST_coarse_Tu1.0_Co1.25n2"), ("section2d", "a090.0_U23.0_SST_medium_Tu1.0_Co1.25n2"),
             ("section2d", "a090.0_U23.0_SST_fine_Tu1.0_Co1.25n2")],
    "S2": [("section2d", "a000.0_U23.0_SST_medium_Tu1.0_Co0.625n2_N300A100"), ("section2d", "a000.0_U23.0_SST_coarse_Tu1.0_Co1.25n2_N300A100"),
           ("section2d", "a000.0_U23.0_SST_fine_Tu1.0_Co1.25n2_N300A100")],
    "R1": [("rotor2d", "A_rot_U23.0_lam0.100_SST_fine_Ks0_senseCCW_rev60a55"), ("rotor2d", "A_rot_U23.0_lam0.100_SST_fine_Ks400_senseCCW_rev60a55"),
           ("rotor2d", "A_rot_U23.0_lam0.100_SST_medium_Ks0_senseCCW_Co2n2_rev50a45"), ("rotor2d", "A_rot_U23.0_lam0.100_SST_medium_Ks400_senseCCW_Co2n2_rev50a45"),
           ("rotor2d", "A_rot_U23.0_lam0.100_SST_coarse_Ks0_senseCCW_rev50a45"), ("rotor2d", "A_rot_U23.0_lam0.100_SST_coarse_Ks400_senseCCW_rev50a45")],
}
B1_NAMES = {name for runs in B1.values() for _, name in runs}
RESTARTS = ["_cont_Co1p25to1p25_a000", "_hyst_Co5to1p25_a000"]
QUEUES = ["cfd/stage2/queues/S2f_verify.txt", "cfd/section2d/queues/priority7_verify.txt", "cfd/rotor2d/queues/priorityF_verify.txt"]
n_lines = 0
for q in QUEUES:
    n_lines += sum(1 for ln in use(q).read_text().splitlines() if ln.strip() and not ln.lstrip().startswith("#"))
if n_lines != len(B1_NAMES):
    raise SystemExit(f"B1: {n_lines} queue lines but {len(B1_NAMES)} case names here")
sublog = REPO / "cfd/hpc/jobs/submitted.log"
if sublog.exists():
    INPUTS["cfd/hpc/jobs/submitted.log"] = [sublog]
    ok = {m.group(1) for m in re.finditer(r"^2026-11-15 \S+ \S+ OK cfd\.\w+\.(\S+)", sublog.read_text(), re.M)}
    if not B1_NAMES <= ok:
        raise SystemExit(f"B1 names not in submitted.log: {sorted(B1_NAMES - ok)}")
restart_coreh, restart_found = 0.0, 0
for rs in RESTARTS:
    cj, sb = REPO / f"cfd/section2d/runs/{rs}/case.json", REPO / f"cfd/section2d/runs/{rs}/run_hysteresis.sbatch"
    if cj.exists() and sb.exists():
        INPUTS[f"cfd/section2d/runs/{rs}/case.json"] = [cj]
        INPUTS[f"cfd/section2d/runs/{rs}/run_hysteresis.sbatch"] = [sb]
        rec = json.loads(cj.read_text())["restart"]
        ranks = int(re.search(r"#SBATCH --ntasks=(\d+)", sb.read_text()).group(1))
        restart_coreh += rec["estimate_steps"] * rec["estimate_s_per_step"] * ranks / 3600
        restart_found += 1
N.num("nBoneJobs", n_lines + len(RESTARTS), 0, f"{n_lines} active lines of {', '.join(QUEUES)} + {len(RESTARTS)} restarts named in priority7_verify.txt")
N.num("nBoneQueueJobs", n_lines, 0, f"active lines of {', '.join(QUEUES)}")
b1_lo = sv("b1_t1_lo") + sv("b1_t2a_lo") + sv("b1_e90_lo") + sv("b1_section_lo") + sv("b1_rotor")
b1_hi = sv("b1_t1_hi") + sv("b1_t2a_hi") + sv("b1_e90_hi") + sv("b1_section_hi") + sv("b1_rotor")
if restart_found == len(RESTARTS):
    N.num("nBoneCoreLo", rnd((b1_lo + restart_coreh) / 100, 0) * 100, 0, "sum of the queue-header estimates (stated_values.csv b1_*) + the restarts' case.json estimate_steps x estimate_s_per_step x ranks")
    N.num("nBoneCoreHi", rnd((b1_hi + restart_coreh) / 100, 0) * 100, 0, "as nBoneCoreLo")
    N.num("nRestartCoreH", restart_coreh, -2 if restart_coreh >= 1000 else 0, "cfd/section2d/runs/{_cont,_hyst}*/case.json restart estimates (local)")
else:
    for m in ("nBoneCoreLo", "nBoneCoreHi", "nRestartCoreH"):
        N.tex(m, r"\localonly", "needs the local restart folders cfd/section2d/runs/_cont*, _hyst*")
stated("nBoneLongestDays", "b1_longest_days", 1)

# =================================================================== counts, cells, wall resolution
sec_oct = [n for n in sec if n not in B1_NAMES]
wf_rows = [r for n, r in st2.items() if r["wall"] == "wf" and n not in B1_NAMES]
tex_rows = [r for n, r in st2.items() if r["wall"] == "tex" and n not in B1_NAMES]
rot_oct = [n for n in rcp if n not in B1_NAMES]
n_cases = len(sec_oct) + len(wf_rows) + len(tex_rows) + len(rot_oct) + len(rstat)
N.num("nRunsSec", len(sec_oct), 0, "cfd/section2d/results/section_polars.csv rows (October)")
N.num("nRunsWf", len(wf_rows), 0, "cfd/stage2/results/stage2_polars.csv rows, wall wf")
N.num("nRunsTex", len(tex_rows), 0, "cfd/stage2/results/stage2_polars.csv rows, wall tex")
N.num("nRunsRotor", len(rot_oct) + len(rstat), 0, "cfd/rotor2d/results/rotor_cp.csv + rotor_static.csv rows")
N.num("nRunsAll", n_cases, 0, "sum of the four")
N.num("nRunsSecSST", sum(sec[n]["model"] == "SST" for n in sec_oct), 0, "section_polars.csv rows, model SST")
N.num("nRunsSecLM", sum(sec[n]["model"] == "LM" for n in sec_oct), 0, "section_polars.csv rows, model LM")
N.num("nRunsTexSST", sum(r["model"] == "SST" for r in tex_rows), 0, "stage2_polars.csv rows, wall tex, model SST")
N.num("nRunsTexLM", sum(r["model"] == "LM" for r in tex_rows), 0, "stage2_polars.csv rows, wall tex, model LM")
N.num("nRunsRotRot", len(rot_oct), 0, "cfd/rotor2d/results/rotor_cp.csv rows (rotating)")
N.num("nRunsRotStat", len(rstat), 0, "cfd/rotor2d/results/rotor_static.csv rows (static)")
N.num("nCellsRotLo", float(rcp["A_rot_U23.0_lam0.100_SST_coarse_senseCCW_rev6"]["n_cells"]) / 1000, 0, "rotor_cp.csv n_cells, coarse mesh of assembly A (thousands)")
N.num("nCellsRotHi", float(rcp["A_rot_U23.0_lam0.100_SST_fine_senseCCW_rev6"]["n_cells"]) / 1000, 0, "rotor_cp.csv n_cells, fine mesh of assembly A (thousands)")
if n_cases != 263:
    print(f"note: {n_cases} October cases (263 on 19 Oct)")
grid_cases = {lvl: [sec[f"a{a}_U23.0_SST_{lvl}_Tu1.0_Co2.5n2"] for a in ("000.0", "090.0", "180.0")] for lvl in ("coarse", "medium", "fine")}
N.num("nCellsSecLo", min(float(r["n_cells"]) for r in grid_cases["coarse"]) / 1000, 0, "section_polars.csv n_cells, coarse grid cases (thousands)")
N.num("nCellsSecHi", max(float(r["n_cells"]) for r in grid_cases["fine"]) / 1000, 0, "section_polars.csv n_cells, fine grid cases (thousands)")
N.num("nCellsWf", np.median([float(r["n_cells"]) for r in wf_rows]) / 1000, 0, "stage2_polars.csv n_cells, wf rows, median (thousands)")
N.num("nCellsTex", np.median([float(r["n_cells"]) for r in tex_rows]) / 1000, 0, "stage2_polars.csv n_cells, tex rows, median (thousands)")
yp = [float(r["yplus_blade_mean"]) for r in wf_rows]
N.num("nYplusWfLo", min(yp), 0, "stage2_polars.csv yplus_blade_mean, wf rows, min")
N.num("nYplusWfHi", max(yp), 0, "stage2_polars.csv yplus_blade_mean, wf rows, max")
N.num("nKsOverYpMax", max(float(r["Ks_over_yP"]) for r in wf_rows), 2, "stage2_polars.csv Ks_over_yP, wf rows, max")

# =================================================================== rough wall function (Stage 2b)
WF = {r["case"]: r for r in read_csv(f"{A15}/roughness_wf_effects.csv")}
wsrc = f"{A15}/roughness_wf_effects.csv"


def wfrow(alpha, ks, co):
    return WF[f"a{alpha:05.1f}_U23.0_SST_wf_Ks{ks}_Tu1.0" + ("_Co2.5n2" if co == 2.5 else "")]


eff_wf90, eff_wf180 = float(wfrow(90, 400, 2.5)["dCd_pct"]), float(wfrow(180, 400, 2.5)["dCd_pct"])
N.num("nCdWfSmooth", float(wfrow(180, 0, 2.5)["Cd"]), 2, f"{wsrc} a180.0 Ks0 Co2.5n2 Cd (smooth reference of the rough-wall family)")
stated("nKspSmoothLimit", "wf_ksplus_smooth", 2)
stated("nKspRoughLimit", "wf_ksplus_rough", 0)
N.num("nWfNinetyTwoFive", eff_wf90, 1, f"{wsrc} a090.0 Ks400 Co2.5n2 dCd_pct")
N.num("nWfNinetyFive", float(wfrow(90, 400, 5)["dCd_pct"]), 1, f"{wsrc} a090.0 Ks400 (maxCo 5) dCd_pct")
N.num("nWfOneEightyTwoFive", eff_wf180, 1, f"{wsrc} a180.0 Ks400 Co2.5n2 dCd_pct")
moves = [abs(float(wfrow(a, k, 2.5)["dCd_pct"]) - float(wfrow(a, k, 5)["dCd_pct"])) for a in (90, 180) for k in (50, 100, 200, 400)]
for a in (90, 180):        # the report says every effect keeps its sign from maxCo 5 to 2.5
    for k in (50, 100, 200, 400):
        for col in ("dCd_pct", "dCl_pct"):
            if np.sign(float(wfrow(a, k, 2.5)[col])) != np.sign(float(wfrow(a, k, 5)[col])):
                raise SystemExit(f"{wsrc}: {col} at alpha {a}, Ks {k} changes sign between maxCo 5 and 2.5")
N.num("nWfMaxMove", max(moves), 1, f"{wsrc} max |dCd_pct(maxCo 2.5) - dCd_pct(maxCo 5)|, alpha 90 and 180, Ks 50-400")
step_wf90 = 100 * (float(wfrow(90, 0, 2.5)["Cd"]) / float(wfrow(90, 0, 5)["Cd"]) - 1)
step_wf180 = 100 * (float(wfrow(180, 0, 2.5)["Cd"]) / float(wfrow(180, 0, 5)["Cd"]) - 1)
N.num("nWfLevelMove", max(abs(step_wf90), abs(step_wf180)), 1, f"{wsrc} Ks0 Cd, |Co2.5n2/maxCo 5 - 1|, larger of alpha 90 and 180")
for a, nm in ((90, "Ninety"), (180, "OneEighty")):
    for k, km in ((50, "Fifty"), (100, "Hundred")):
        N.num(f"nWf{nm}{km}", float(wfrow(a, k, 2.5)["dCd_pct"]), 2 if abs(float(wfrow(a, k, 2.5)["dCd_pct"])) < 1 else 1,
              f"{wsrc} a{a:05.1f} Ks{k} Co2.5n2 dCd_pct", sign=True)

KS_SWEEP = (0, 50, 100, 200, 400)
ksp_sec = {a: [float(wfrow(a, k, 2.5)["ksplus_mean"]) for k in KS_SWEEP] for a in (90, 180)}
K_LO, K_HI_LO, K_HI = sv("k_low_um"), sv("k_fs20_lo_um"), sv("k_fs20_hi_um")
band_sec = {a: (float(np.interp(K_LO, KS_SWEEP, ksp_sec[a])), float(np.interp(K_HI, KS_SWEEP, ksp_sec[a]))) for a in (90, 180)}
N.num("nKspSecLo", min(b[0] for b in band_sec.values()), 0, f"{wsrc} ksplus_mean (maxCo 2.5) interpolated in Ks at k = {K_LO:.0f} um, min of alpha 90/180")
N.num("nKspSecHi", max(b[1] for b in band_sec.values()), 0, f"{wsrc} ksplus_mean interpolated at k = {K_HI:.0f} um, max of alpha 90/180")
N.num("nKspSecFourLo", min(ksp_sec[a][-1] for a in (90, 180)), 0, f"{wsrc} ksplus_mean Ks400 Co2.5n2, min of alpha 90/180")
N.num("nKspSecFourHi", max(ksp_sec[a][-1] for a in (90, 180)), 0, f"{wsrc} ksplus_mean Ks400 Co2.5n2, max of alpha 90/180")

# =================================================================== resolved texture (Stage 2e)
TT = read_csv(f"{A15}/roughness_tex_timestep.csv")
tt0 = one(TT, "roughness_tex_timestep", alpha_deg="180", model="SST", t_mm="0")
tt2 = one(TT, "roughness_tex_timestep", alpha_deg="180", model="SST", t_mm="0.2")
step_tex = float(tt0["d_same_window_pct"])
N.num("nTexDropSmooth", -step_tex, 1, f"{A15}/roughness_tex_timestep.csv 180 SST t 0, -d_same_window_pct (maxCo 5 to 2.5)")
N.num("nTexDropTex", -float(tt2["d_same_window_pct"]), 1, f"{A15}/roughness_tex_timestep.csv 180 SST t 0.2, -d_same_window_pct")
TE = {r["case"]: r for r in read_csv(f"{A15}/roughness_tex_effects.csv")}
e5 = TE["a180.0_U23.0_SST_tex0.200_s1_Tu1.0_N80A50"]
e25 = TE["a180.0_U23.0_SST_tex0.200_s1_Tu1.0_Co2.5n2"]
eff_tex = float(e25["dCd_pct"])
N.num("nTexEffFive", float(e5["dCd_pct"]), 1, f"{A15}/roughness_tex_effects.csv a180 SST t 0.2 N80A50 (maxCo 5, {e5['window']}) dCd_pct")
N.num("nTexEffTwoFiveShort", float(e25["dCd_pct_30_80"]), 1, f"{A15}/roughness_tex_effects.csv a180 SST t 0.2 Co2.5n2 dCd_pct_30_80")
N.num("nTexEffLong", eff_tex, 1, f"{A15}/roughness_tex_effects.csv a180 SST t 0.2 Co2.5n2 ({e25['window']}) dCd_pct")
w_short = [float(x) for x in re.findall(r"[\d.]+", e5["window"])]
w_long = [float(x) for x in re.findall(r"[\d.]+", e25["window"])]
N.num("nWinShortLo", w_short[0], 0, f"{A15}/roughness_tex_effects.csv window of the maxCo-5 runs")
N.num("nWinShortHi", w_short[1], 0, "as nWinShortLo")
N.num("nWinLongLo", w_long[0], 0, f"{A15}/roughness_tex_effects.csv window of the maxCo-2.5 runs")
N.num("nWinLongHi", w_long[1], 0, "as nWinLongLo")

tex0_25, tex0_5 = st2["a180.0_U23.0_SST_tex0.000_s1_Tu1.0_Co2.5n2"], st2["a180.0_U23.0_SST_tex0.000_s1_Tu1.0_N80A50"]
med25, med125 = sec["a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2"], sec["a180.0_U23.0_SST_medium_Tu1.0_Co1.25n2"]
N.num("nTexCdSmooth", float(tex0_25["Cd_mean"]), 3, "stage2_polars.csv a180.0_U23.0_SST_tex0.000_s1_Tu1.0_Co2.5n2 Cd_mean")
N.num("nMedCdTwoFive", float(med25["Cd_mean"]), 3, "section_polars.csv a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2 Cd_mean")
N.num("nMedCdOneTwoFive", float(med125["Cd_mean"]), 3, "section_polars.csv a180.0_U23.0_SST_medium_Tu1.0_Co1.25n2 Cd_mean")
N.num("nTexGapPct", -100 * (float(tex0_25["Cd_mean"]) / float(med25["Cd_mean"]) - 1), 0, "1 - Cd_mean(stage2 tex0.000 Co2.5n2) / Cd_mean(section medium Co2.5n2), alpha 180")
N.num("nTexGapMatched", -100 * (float(tex0_5["Cd_mean"]) / float(med125["Cd_mean"]) - 1), 1,
      f"1 - Cd_mean(stage2 tex0.000 N80A50, window {tex0_5['avg_from_conv']}-{tex0_5['avg_to_conv']}) / Cd_mean(section medium Co1.25n2, {med125['avg_from_conv']}-{med125['avg_to_conv']}), alpha 180")
N.num("nTexGapDt", 100 * abs(float(tex0_5["dt_mean_s"]) / float(med125["dt_mean_s"]) - 1), 1, "|dt_mean_s(stage2 tex0.000 N80A50) / dt_mean_s(section medium Co1.25n2) - 1|")

# =================================================================== measured surfaces and gains
SR = {r["rotor"]: r for r in read_csv("reports/roughness_2026-09/build/derived/surface_roughness.csv")}
srsrc = "reports/roughness_2026-09/build/derived/surface_roughness.csv"
RA_T = sv("ra_per_t")
KS_T = sv("ks_per_t")
T_SET = {"FS 0.05": sv("t_fs05_mm"), "FS 0.10": sv("t_fs10_mm"), "FS 0.20": sv("t_fs20_mm")}
SETS = ["Plain", "FS 0.05", "FS 0.10", "FS 0.20"]
TAG = {"Plain": "Plain", "FS 0.05": "FsFive", "FS 0.10": "FsTen", "FS 0.20": "FsTwenty"}
t_eq = {}
for s in SETS:
    ra = float(SR[s]["Ra_lc025_um"])
    t_eq[s] = ra / RA_T / 1000
    N.num(f"nRa{TAG[s]}", ra, 1, f"{srsrc} {s} Ra_lc025_um")
    N.num(f"nTeq{TAG[s]}", t_eq[s], 3, f"{srsrc} {s} Ra_lc025_um / ra_per_t / 1000 (mm)")
    N.num(f"nScans{TAG[s]}", float(SR[s]["scans"]), 0, f"{srsrc} {s} scans")
    if SR[s]["layer_period_um"]:
        N.num(f"nLayer{TAG[s]}", float(SR[s]["layer_period_um"]) / 1000, 1, f"{srsrc} {s} layer_period_um / 1000 (mm)")
N.num("nTeqLo", min(t_eq.values()), 3, "min of nTeq*")
N.num("nTeqHi", max(t_eq.values()), 3, "max of nTeq*")
ks_eq = {s: KS_T * t_eq[s] * 1000 for s in SETS}
N.num("nKsEqLo", min(ks_eq.values()), 0, "ks_per_t x Ra / ra_per_t, min over the four tested sets (um)")
N.num("nKsEqHi", max(ks_eq.values()), 0, "as nKsEqLo, max")
amp = [RA_T * T_SET[s] * 1000 / float(SR[s]["Ra_lc025_um"]) for s in ("FS 0.05", "FS 0.10", "FS 0.20")]
N.num("nNomOverRaLo", min(amp), 0, f"ra_per_t x t / measured Ra ({srsrc}), min over FS 0.05-0.20")
N.num("nNomOverRaHi", max(amp), 0, "as nNomOverRaLo, max")

MEAS = {r["rotor"]: r for r in read_csv(f"{A15}/roughness_measured.csv")}
msrc = f"{A15}/roughness_measured.csv"
for s, tag in (("FS 0.05", "FsFive"), ("FS 0.10", "FsTen"), ("FS 0.20", "FsTwenty")):
    N.num(f"nGain{tag}", float(MEAS[s]["change_pct"]), 1, f"{msrc} {s} change_pct", sign=True)
    N.num(f"nGain{tag}Lo", float(MEAS[s]["tukey95_lo_pct"]), 1, f"{msrc} {s} tukey95_lo_pct", sign=True)
    N.num(f"nGain{tag}Hi", float(MEAS[s]["tukey95_hi_pct"]), 1, f"{msrc} {s} tukey95_hi_pct", sign=True)

for name, key, nd in (("nKLow", "k_low_um", 0), ("nKHighLo", "k_fs20_lo_um", 0), ("nKHighHi", "k_fs20_hi_um", 0),
                      ("nKsPerT", "ks_per_t", 2), ("nRaPerT", "ra_per_t", 3),
                      ("nKsNomFsFive", "ks_nom_fs05_um", 0), ("nKsNomFsTen", "ks_nom_fs10_um", 0),
                      ("nKsNomFsTwenty", "ks_nom_fs20_um", 0), ("nKsNomFsForty", "ks_nom_fs40_um", 0),
                      ("nTFsFive", "t_fs05_mm", 3), ("nTFsTen", "t_fs10_mm", 3), ("nTFsTwenty", "t_fs20_mm", 3),
                      ("nTFsQuarter", "t_fs025_mm", 3), ("nTFsForty", "t_fs40_mm", 2), ("nTFsEighty", "t_fs80_mm", 3),
                      ("nLayerFsEighty", "layer_fs80_mm", 2), ("nLayerSlicer", "layer_slicer_mm", 1),
                      ("nLayerLimit", "layer_limit_mm", 2), ("nNozzleSmall", "nozzle_tested_mm", 1),
                      ("nNozzleLarge", "nozzle_large_mm", 1), ("nSlicerMax", "slicer_max_fs_mm", 0)):
    stated(name, key, nd)
N.num("nKsNomFsQuarter", KS_T * sv("t_fs025_mm") * 1000, 0, "ks_per_t x t_fs025_mm (um)")

# =================================================================== rotor (2D, assembly A, 23 m/s)
RR = read_csv(f"{A15}/rotor_roughness.csv")
rsrc = f"{A15}/rotor_roughness.csv"


def rpair(lam, a, b="Ks0"):
    return one(RR, "rotor_roughness", lam=lam, a=a, b=b)


p10, p12, h10, h12 = rpair("0.1", "Ks400"), rpair("0.12", "Ks400"), rpair("0.1", "Ks100"), rpair("0.12", "Ks100")
for nm, r, lab in (("RotEffTen", p10, "0.1 Ks400-Ks0"), ("RotEffTwelve", p12, "0.12 Ks400-Ks0"),
                   ("RotHunTen", h10, "0.1 Ks100-Ks0"), ("RotHunTwelve", h12, "0.12 Ks100-Ks0")):
    N.num(f"n{nm}", float(r["dCQ"]), 4, f"{rsrc} {lab} dCQ", sign=True)
    N.num(f"n{nm}U", float(r["two_u"]), 4, f"{rsrc} {lab} two_u")
N.num("nRotEffTenPct", float(p10["rel_change_pct"]), 0, f"{rsrc} 0.1 Ks400-Ks0 rel_change_pct")
N.num("nRotEffTwelvePct", float(p12["rel_change_pct"]), 0, f"{rsrc} 0.12 Ks400-Ks0 rel_change_pct")
twou_pairs = [float(rpair(l, a)["two_u"]) for l in ("0.1", "0.12") for a in ("Ks100", "Ks400")]
N.num("nRotTwoULo", min(twou_pairs), 4, f"{rsrc} two_u, Ks 100/400 - Ks 0 pairs, min")
N.num("nRotTwoUHi", max(twou_pairs), 4, f"{rsrc} two_u, Ks 100/400 - Ks 0 pairs, max")

SECT = read_csv(f"{A15}/rotor_roughness_sectors.csv")
SECTOR = {"adv": "advancing, edge-on (tip A first)", "ret": "returning, edge-on (curl first)",
          "down": "downwind, cup to the wind", "up": "upwind, convex side to the wind"}


def sector(lam, a, key):
    return one(SECT, "rotor_roughness_sectors", lam=lam, a=a, b="Ks0", sector=SECTOR[key])


adv100 = sector("0.1", "Ks100", "adv")
if adv100["resolved_2u"] != "True":
    raise SystemExit("rotor_roughness_sectors.csv: the Ks-100 advancing change is no longer resolved")
N.num("nAdvHun", float(adv100["d"]), 5, f"{A15}/rotor_roughness_sectors.csv 0.1 Ks100-Ks0 advancing d", sign=True)
N.num("nAdvHunU", float(adv100["two_u"]), 5, f"{A15}/rotor_roughness_sectors.csv 0.1 Ks100-Ks0 advancing two_u")
for key, nm in (("adv", "Adv"), ("ret", "Ret"), ("down", "Down"), ("up", "Up")):
    r = sector("0.1", "Ks400", key)
    N.num(f"nSec{nm}", float(r["d"]), 4, f"{A15}/rotor_roughness_sectors.csv 0.1 Ks400-Ks0 {key} d", sign=True)
    N.num(f"nSec{nm}U", float(r["two_u"]), 4, f"{A15}/rotor_roughness_sectors.csv 0.1 Ks400-Ks0 {key} two_u")

RN = json.loads(use(f"{A15}/rotor_numbers.json").read_text())
rnsrc = f"{A15}/rotor_numbers.json"
gd = RN["grid"]["differences"]["0.10"]
rot_mesh, rot_mesh_u = gd["fine_minus_coarse"], gd["two_u_diff"]
N.num("nRotMeshFC", rot_mesh, 4, f"{rnsrc} grid.differences.0.10.fine_minus_coarse", sign=True)
N.num("nRotMeshFCU", rot_mesh_u, 4, f"{rnsrc} grid.differences.0.10.two_u_diff")
N.num("nRotMeshOverEff", rot_mesh / float(p10["dCQ"]), 1, "nRotMeshFC / nRotEffTen")
grid_rows = {(r["level"], r["lam"]): r for r in RN["grid"]["rows"]}
N.num("nRotNrevGrid", grid_rows[("fine", 0.1)]["n_avg_rev"], 0, f"{rnsrc} grid.rows fine 0.1 n_avg_rev")
tsr = [x for x in RN["time_step_check"] if x["sense"] == "CCW"]
if len(tsr) != 1:
    raise SystemExit("rotor_numbers.json: expected one CCW time-step check")
tsr = tsr[0]
rot_step, rot_step_u = tsr["dCQ"], 2 * abs(tsr["dCQ"] / tsr["dCQ_over_u_diff"])
N.num("nRotTs", rot_step, 4, f"{rnsrc} time_step_check CCW dCQ (lambda {tsr['lam']}, maxCo 4 to 2)", sign=True)
N.num("nRotTsU", rot_step_u, 4, f"{rnsrc} time_step_check CCW 2 |dCQ / dCQ_over_u_diff|")
runs = RN["roughness"]["runs"]
ksp_rot = {lam: [0.0, runs[f"{lam}_Ks100"]["ksplus_mean"], runs[f"{lam}_Ks400"]["ksplus_mean"]] for lam in ("0.10", "0.12")}
band_rot = [float(np.interp(k, (0, 100, 400), ksp_rot[lam])) for lam in ksp_rot for k in (K_LO, K_HI)]
N.num("nKspRotLo", min(band_rot), 0, f"{rnsrc} roughness.runs.*_Ks100/400.ksplus_mean interpolated in Ks at {K_LO:.0f} um (min over lambda)")
N.num("nKspRotHi", max(band_rot), 0, f"as nKspRotLo, at {K_HI:.0f} um (max over lambda)")
N.num("nKspRotFour", runs["0.10_Ks400"]["ksplus_mean"], 0, f"{rnsrc} roughness.runs.0.10_Ks400.ksplus_mean")
N.num("nKsOverYpRot", runs["0.10_Ks400"]["Ks_over_yP"], 2, f"{rnsrc} roughness.runs.0.10_Ks400.Ks_over_yP")
trend = RN["roughness"]["ks_trend"]["0.10"]
slope = trend["slope_per_100um"]
d_lo, d_hi = slope * K_LO / 100, slope * K_HI / 100
N.num("nTrendLo", d_lo, 4, f"{rnsrc} roughness.ks_trend.0.10.slope_per_100um x {K_LO:.0f}/100")
N.num("nTrendHi", d_hi, 4, f"{rnsrc} roughness.ks_trend.0.10.slope_per_100um x {K_HI:.0f}/100")
sigma = RN["noise_model"]["sigma_long_runs_rms"]
n_need = math.ceil(8 * sigma ** 2 / d_hi ** 2)
N.num("nRevNeeded", rnd(n_need / 10, 0) * 10, 0, f"8 sigma^2 / d^2 with sigma = {rnsrc} noise_model.sigma_long_runs_rms, d = nTrendHi (rounded to 10)")
navg = {int(float(rcp[n]["n_avg_rev"])) for n in (p10["case_a"], p10["case_b"])}
N.num("nRevNow", navg.pop(), 0, "cfd/rotor2d/results/rotor_cp.csv n_avg_rev of the lambda-0.10 Ks pair")
cpr = []
for case, c in RN["cost_long_runs"].items():
    ranks = RN["inputs"]["jobs_new"][case]["ntasks"]
    cpr.append(c["wall_h"] * ranks / float(rcp[case]["n_rev_done"]))
N.num("nCoreHPerRev", float(np.mean(cpr)), 1, f"{rnsrc} cost_long_runs wall_h x inputs.jobs_new ntasks / rotor_cp.csv n_rev_done, mean of {len(cpr)} runs")

# =================================================================== J3: blade forces through the turn (2026-11-15)
PF_S, PF, PF_C = (REPO / A1115 / f for f in ("rotor_phase_force_sectors.csv", "rotor_phase_force.csv", "rotor_phase_force_check.csv"))
have_pf = PF_S.exists() and PF.exists()
pf_names = ["nPfRuns", "nPfAdvCD", "nPfAdvCDU", "nPfAdvCDPct", "nPfAdvCL", "nPfAdvCLU", "nPfUpCD", "nPfUpCDU", "nPfUpCL", "nPfUpCLU",
            "nPfRetCD", "nPfRetCDU", "nPfBladeShare", "nPfBladeExpect"]
if have_pf:
    pfs = read_csv(f"{A1115}/rotor_phase_force_sectors.csv")
    psrc = f"{A1115}/rotor_phase_force_sectors.csv lambda 0.1"

    def pfd(key):
        return one(pfs, "rotor_phase_force_sectors", kind="difference", lam="0.1", a="Ks400", b="Ks0", sector=SECTOR[key])

    adv, up, ret = pfd("adv"), pfd("up"), pfd("ret")
    N.num("nPfRuns", len({r["case_a"] for r in pfs if r["kind"] == "run"}), 0, f"{A1115}/rotor_phase_force_sectors.csv distinct runs")
    adv0 = one(pfs, "rotor_phase_force_sectors", kind="run", lam="0.1", a="Ks0", sector=SECTOR["adv"])
    N.num("nPfAdvCD", float(adv["CD"]), 3, f"{psrc} difference Ks400-Ks0 advancing CD", sign=True)
    N.num("nPfAdvCDU", float(adv["CD_2u"]), 3, f"{psrc} difference Ks400-Ks0 advancing CD_2u")
    N.num("nPfAdvCDPct", 100 * float(adv["CD"]) / float(adv0["CD"]), 0, f"{psrc} advancing CD difference / run Ks0 CD")
    N.num("nPfAdvCL", float(adv["CL"]), 2, f"{psrc} difference Ks400-Ks0 advancing CL", sign=True)
    N.num("nPfAdvCLU", float(adv["CL_2u"]), 2, f"{psrc} difference Ks400-Ks0 advancing CL_2u")
    N.num("nPfUpCD", float(up["CD"]), 3, f"{psrc} difference Ks400-Ks0 upwind CD", sign=True)
    N.num("nPfUpCDU", float(up["CD_2u"]), 3, f"{psrc} difference Ks400-Ks0 upwind CD_2u")
    N.num("nPfUpCL", float(up["CL"]), 3, f"{psrc} difference Ks400-Ks0 upwind CL", sign=True)
    N.num("nPfUpCLU", float(up["CL_2u"]), 3, f"{psrc} difference Ks400-Ks0 upwind CL_2u")
    N.num("nPfRetCD", float(ret["CD"]), 3, f"{psrc} difference Ks400-Ks0 returning CD", sign=True)
    N.num("nPfRetCDU", float(ret["CD_2u"]), 3, f"{psrc} difference Ks400-Ks0 returning CD_2u")
    if PF_C.exists():
        chk = read_csv(f"{A1115}/rotor_phase_force_check.csv")
        bb = [r for r in chk if r["check"].startswith("blade-to-blade") and r["check"].rstrip().endswith(", CD")]
        if len(bb) == 1:
            N.num("nPfBladeShare", 100 * float(bb[0]["recomputed"]), 0, f"{A1115}/rotor_phase_force_check.csv blade-to-blade CD recomputed")
            N.num("nPfBladeExpect", 100 * float(bb[0]["reference"]), 0, f"{A1115}/rotor_phase_force_check.csv blade-to-blade CD reference")
        else:
            N.pending("nPfBladeShare", f"{A1115}/rotor_phase_force_check.csv blade-to-blade CD row")
            N.pending("nPfBladeExpect", f"{A1115}/rotor_phase_force_check.csv blade-to-blade CD row")
    else:
        N.pending("nPfBladeShare", f"{A1115}/rotor_phase_force_check.csv")
        N.pending("nPfBladeExpect", f"{A1115}/rotor_phase_force_check.csv")
else:
    for m in pf_names:
        N.pending(m, f"{A1115}/rotor_phase_force_sectors.csv")

# =================================================================== J7: rotor speed through the loading
DWELL = "reports/roughness_2026-09/out/URI_VAWT_Texture_Data_2026-10-01_rev2/4_derived/rotor_speed_by_dwell.csv"
DWELL_TRACKED = "reports/roughness_2026-09/build/tacho/derived/rotor_speed_by_dwell.csv"
dw_rel = DWELL if (REPO / DWELL).exists() else DWELL_TRACKED
dwell = read_csv(dw_rel)
N.num("nDwells", len(dwell), 0, f"{dw_rel} rows (load steps)")
N.num("nDwellsOk", sum(r["speed_ok"] == "True" for r in dwell), 0, f"{dw_rel} speed_ok True")
FAN_23 = "1100"     # 23.0 m/s on the tunnel's calibration
by_run = {}
for r in dwell:
    if r["speed_ok"] == "True":
        by_run.setdefault((r["fan_rpm_cmd"], r["rotor"], r["run"]), []).append(r)
light, heavy, at_pmax = [], [], []
for (fan, rot, run), rs in by_run.items():
    if fan != FAN_23:
        continue
    rs.sort(key=lambda r: float(r["demand_a"]))
    light.append(float(rs[0]["tip_speed_ratio"]))
    heavy.append(float(rs[-1]["tip_speed_ratio"]))
    at_pmax.append(float(max(rs, key=lambda r: float(r["cp_el"]))["tip_speed_ratio"]))
dsrc = f"{dw_rel} fan_rpm_cmd {FAN_23}, per rotor and run"
N.num("nLamLightLo", min(light), 3, f"{dsrc}: tip_speed_ratio at the lightest load, min")
N.num("nLamLightHi", max(light), 3, f"{dsrc}: tip_speed_ratio at the lightest load, max")
N.num("nLamHeavyLo", min(heavy), 3, f"{dsrc}: tip_speed_ratio at the heaviest load, min")
N.num("nLamHeavyHi", max(heavy), 3, f"{dsrc}: tip_speed_ratio at the heaviest load, max")
N.num("nLamPmaxLo", min(at_pmax), 3, f"{dsrc}: tip_speed_ratio at the largest cp_el, min")
N.num("nLamPmaxHi", max(at_pmax), 3, f"{dsrc}: tip_speed_ratio at the largest cp_el, max")

# =================================================================== computing used and planned
jobs = sorted(REPO.glob("cfd/*/runs/*/hpc_jobs.jsonl"))
if jobs:
    INPUTS["cfd/*/runs/*/hpc_jobs.jsonl"] = jobs
    seen, coreh, by_stage = set(), 0.0, {}
    for f in jobs:
        for ln in f.read_text().splitlines():
            if not ln.strip():
                continue
            j = json.loads(ln)
            if not j.get("wall_s") or not j.get("ntasks") or j.get("start", "")[:7] != "2026-10":
                continue
            key = (j.get("job"), j.get("name"))
            if key in seen:
                continue
            seen.add(key)
            ch = j["wall_s"] * j["ntasks"] / 3600
            coreh += ch
            by_stage[j["stage"]] = by_stage.get(j["stage"], 0.0) + ch
    N.num("nLocalJobs", len(seen), 0, "cfd/*/runs/*/hpc_jobs.jsonl records started in Oct 2026 (local)")
    N.num("nLocalCoreH", coreh, 0, "sum of wall_s x ntasks / 3600 over those records (local)")
    for st, nm in (("section2d", "Sec"), ("stage2", "Stage"), ("rotor2d", "Rot")):
        N.num(f"nLocalCoreH{nm}", by_stage.get(st, 0.0), 0, f"as nLocalCoreH, stage {st}")
else:
    for m in ("nLocalJobs", "nLocalCoreH", "nLocalCoreHSec", "nLocalCoreHStage", "nLocalCoreHRot"):
        N.tex(m, r"\localonly", "cfd/*/runs/*/hpc_jobs.jsonl (local)")
for name, key, nd in (("nOctJobs", "oct_jobs", 0), ("nOctCoreH", "oct_core_h", 0), ("nUnityDays", "unity_max_days", 0),
                      ("nBTwoLo", "b2_lo", 0), ("nBTwoHi", "b2_hi", 0), ("nTexRotRevLo", "texrotor_rev_lo", 0),
                      ("nTexRotRevHi", "texrotor_rev_hi", 0), ("nTexRotPairLo", "texrotor_pair_lo", 0),
                      ("nTexRotPairHi", "texrotor_pair_hi", 0), ("nLmRotLo", "lmrotor_lo", 0), ("nLmRotHi", "lmrotor_hi", 0),
                      ("nStripLo", "strip_lo", 0), ("nStripHi", "strip_hi", 0), ("nBladeCellsLo", "blade3d_gcells_lo", 0),
                      ("nBladeCellsHi", "blade3d_gcells_hi", 0), ("nBladeCoreLo", "blade3d_mcoreh_lo", 1),
                      ("nBladeCoreHi", "blade3d_mcoreh_hi", 0), ("nTunnelLo", "tunnel_h_lo", 0), ("nTunnelHi", "tunnel_h_hi", 0),
                      ("nAccLevel", "acc_level_pct", 0), ("nAccEff", "acc_effect_pts", 0), ("nAccCostLo", "acc_cost_lo", 1),
                      ("nAccCostHi", "acc_cost_hi", 1), ("nAccRot", "acc_rotor", 3),
                      ("nBalLentLo", "balance_lent_lo_usd", 0), ("nBalLentHi", "balance_lent_hi_usd", 0),
                      ("nBalLo", "balance_lo_usd", 0), ("nBalHi", "balance_hi_usd", 0),
                      ("nBalOldLo", "summary_balance_lo_usd", 0), ("nBalOldHi", "summary_balance_hi_usd", 0)):
    stated(name, key, nd)
N.num("nBladeOverOctLo", sv("blade3d_mcoreh_lo") * 1e6 / sv("oct_core_h"), 0, "blade3d_mcoreh_lo x 1e6 / oct_core_h")
N.num("nBladeOverOctHi", rnd(sv("blade3d_mcoreh_hi") * 1e6 / sv("oct_core_h") / 10, 0) * 10, 0, "blade3d_mcoreh_hi x 1e6 / oct_core_h (to 10)")

# Print Lab estimates for the November sets: 0.50 USD/h + filament at the Print Lab's USD/kg
rate, fil = sv("print_rate_usd_h"), sv("filament_usd_kg")
stated("nPrintRate", "print_rate_usd_h", 2)
stated("nFilament", "filament_usd_kg", 2)
for tag, key in (("PlainFour", "plain04"), ("FsForty", "fs40"), ("FsQuarter", "fs025")):
    h, g = sv(f"print_{key}_h"), sv(f"print_{key}_g")
    N.num(f"nPrint{tag}H", h, 0, svs(f"print_{key}_h"))
    N.num(f"nPrint{tag}G", g, 2, svs(f"print_{key}_g"))
    N.num(f"nPrint{tag}Usd", rate * h + g / 1000 * fil, 2, f"print_rate_usd_h x print_{key}_h + print_{key}_g / 1000 x filament_usd_kg")
    N.num(f"nPrint{tag}Set", 3 * (rate * h + g / 1000 * fil), 2, f"3 x nPrint{tag}Usd")

# =================================================================== B1 results, filled in when the rows exist
def b1_row(stage, name):
    """The result-table row of a finished B1 case, else None."""
    table = {"section2d": sec, "stage2": st2, "rotor2d": rcp}[stage]
    r = table.get(name)
    if r is None:
        return None
    if stage == "rotor2d":
        return r if r.get("avg_window_complete") == "True" else None
    need = 300 if "_N300A100" in name else 150
    return r if float(r["t_end_conv"]) >= need - 0.5 else None


def cd(stage, name):
    r = b1_row(stage, name)
    return float(r["Cd_mean"]) if r else None


def pct(a, b):
    return None if a is None or b is None else 100 * (a / b - 1)


def spread(vals):
    if any(v is None for v in vals):
        return None
    return 100 * (max(vals) - min(vals)) / abs(vals[-1])


B1V = {}
t1 = [cd(*c) for c in B1["T1"]]
B1V["T1"] = (pct(t1[0], float(tex0_25["Cd_mean"])), pct(t1[1], t1[0]))
t2 = [cd(*c) for c in B1["T2a"]]
B1V["T2a"] = (pct(t2[0], float(tex0_25["Cd_mean"])), pct(t2[1], t2[0]))
e9 = [cd(*c) for c in B1["E90t"]]
B1V["E90t"] = (pct(e9[1], e9[0]), pct(e9[3], e9[2]))
s1 = [cd(*c) for c in B1["S1"]]
B1V["S1"] = (pct(s1[0], float(med125["Cd_mean"])), spread([s1[1], float(med125["Cd_mean"]), s1[2]]))
cl90 = []
for c in B1["E90s"]:
    r = b1_row(*c)
    cl90.append(float(r["Cl_mean"]) if r else None)
B1V["E90s"] = (spread([cd(*c) for c in B1["E90s"]]), spread(cl90))
B1V["S2"] = tuple(cd(*c) for c in B1["S2"])


def dcq(i):
    a, b = b1_row(*B1["R1"][i + 1]), b1_row(*B1["R1"][i])
    return float(a["CQ_mean"]) - float(b["CQ_mean"]) if a and b else None


B1V["R1"] = (dcq(0), dcq(2), dcq(4))
bsrc = "B1 rows of the result tables (section_polars.csv, stage2_polars.csv, rotor_cp.csv)"
N.num("nBoneTOneLevel", B1V["T1"][0], 1, f"{bsrc}: tex0.000 Co1.25n2 Cd_mean vs Co2.5n2, %", sign=True)
N.num("nBoneTOneEff", B1V["T1"][1], 1, f"{bsrc}: tex0.200 vs tex0.000, Co1.25n2, %", sign=True)
N.num("nBoneTTwoLevel", B1V["T2a"][0], 1, f"{bsrc}: tex0.000 n10 vs nseg 5, Co2.5n2, %", sign=True)
N.num("nBoneTTwoEff", B1V["T2a"][1], 1, f"{bsrc}: tex0.200 vs tex0.000, n10, %", sign=True)
N.num("nBoneTexNinetyA", B1V["E90t"][0], 1, f"{bsrc}: a090 tex0.200 vs tex0.000, Co2.5n2, %", sign=True)
N.num("nBoneTexNinetyB", B1V["E90t"][1], 1, f"{bsrc}: a090 tex0.200 vs tex0.000, Co1.25n2, %", sign=True)
N.num("nBoneSOneStep", B1V["S1"][0], 1, f"{bsrc}: a180 medium Co0.625n2 vs Co1.25n2, %", sign=True)
N.num("nBoneSOneSpread", B1V["S1"][1], 1, f"{bsrc}: a180 coarse/medium/fine at Co1.25n2, spread % of fine")
N.num("nBoneNinetyCd", B1V["E90s"][0], 1, f"{bsrc}: a090 Co1.25n2 Cd spread % of fine")
N.num("nBoneNinetyCl", B1V["E90s"][1], 1, f"{bsrc}: a090 Co1.25n2 Cl spread % of fine")
N.num("nBoneSTwoMed", B1V["S2"][0], 2, f"{bsrc}: a000 medium Co0.625n2_N300A100 Cd_mean")
N.num("nBoneSTwoCoarse", B1V["S2"][1], 2, f"{bsrc}: a000 coarse Co1.25n2_N300A100 Cd_mean")
N.num("nBoneSTwoFine", B1V["S2"][2], 2, f"{bsrc}: a000 fine Co1.25n2_N300A100 Cd_mean")
N.num("nBoneROneFine", B1V["R1"][0], 4, f"{bsrc}: fine Ks400 - Ks0 CQ_mean", sign=True)
N.num("nBoneROneMedTwo", B1V["R1"][1], 4, f"{bsrc}: medium maxCo 2 Ks400 - Ks0 CQ_mean", sign=True)
N.num("nBoneROneCoarse", B1V["R1"][2], 4, f"{bsrc}: coarse Ks400 - Ks0 CQ_mean", sign=True)
N.num("nBoneDone", sum(b1_row(*c) is not None for runs in B1.values() for c in runs), 0, f"{bsrc}: finished B1 cases in the tables")

# S2h, the rough-wall mesh study (submitted 15 Nov with B1): the Ks-400 change on each wf mesh, its own Ks 0
S2H = {al: {lev: (f"a{al}.0_U23.0_SST_wf_Ks0{tag}_Tu1.0_Co2.5n2", f"a{al}.0_U23.0_SST_wf_Ks400{tag}_Tu1.0_Co2.5n2")
            for lev, tag in (("C", "_wfC"), ("M", ""), ("F", "_wfF"))} for al in ("090", "180")}
ssrc = "stage2_polars.csv, S2h_wf_mesh.txt cases (coarse/fine) and S2e_rerun.txt (medium), maxCo 2.5"
for al, tag in (("090", "Ninety"), ("180", "OneEighty")):
    for lev in ("C", "M", "F"):
        a, b = (b1_row("stage2", n) for n in S2H[al][lev])
        dcd = 100 * (float(b["Cd_mean"]) / float(a["Cd_mean"]) - 1) if a and b else None
        dcl = 100 * (float(b["Cl_mean"]) / float(a["Cl_mean"]) - 1) if a and b else None
        N.num(f"nWfMesh{tag}Cd{lev}", dcd, 1, f"{ssrc}: a{al} wf mesh {lev}, Ks400 vs Ks0 Cd_mean, %", sign=True)
        N.num(f"nWfMesh{tag}Cl{lev}", dcl, 1, f"{ssrc}: a{al} wf mesh {lev}, Ks400 vs Ks0 Cl_mean, %", sign=True)
    smooth = [b1_row("stage2", S2H[al][lev][0]) for lev in ("C", "M", "F")]
    N.num(f"nWfMesh{tag}Level", spread([float(r["Cd_mean"]) if r else None for r in smooth]), 1,
          f"{ssrc}: a{al} Ks0 Cd_mean on the three meshes, spread % of fine")
N.num("nWfMeshDone", sum(b1_row("stage2", n) is not None for al in S2H.values() for pr in al.values() for n in pr) - 4, 0,
      f"{ssrc}: finished S2h cases (the 4 medium partners not counted)")

N.num("nMedCdSixTwoFive", cd("section2d", "a180.0_U23.0_SST_medium_Tu1.0_Co0.625n2"), 3,
      "section_polars.csv: a180 medium Co0.625n2 Cd_mean (mean dt about that of the texture mesh at maxCo 2.5)")
# alpha 0 restarts (B1 S2): last 100 c/U of each (stated_values.csv, from section_summary.py)
stated("nRestartContCd", "restart_cont_cd", 2)
stated("nRestartHystCd", "restart_hyst_cd", 2)
# the smooth section's edge-on time step (medium mesh, maxCo 2.5 -> 1.25)
_m90 = [b1_row("section2d", f"a090.0_U23.0_SST_medium_Tu1.0_{co}") or sec.get(f"a090.0_U23.0_SST_medium_Tu1.0_{co}") for co in ("Co2.5n2", "Co1.25n2")]
N.num("nSecNinetyStep", pct(*(float(r["Cd_mean"]) if r else None for r in _m90[::-1])), 0,
      "section_polars.csv: a090 medium Co1.25n2 vs Co2.5n2 Cd_mean, %", sign=True)

# G-code profiles (cfd/geometry/gcode_profiles/, gcode_profile.py): each printed set's own mid-span layer
import json as _json
GC = {}
for _s in ("Ra10", "Ra40", "Ra80"):
    _rel = f"cfd/geometry/gcode_profiles/{_s}_z1226.json"
    use(_rel)
    GC[_s] = _json.loads((REPO / _rel).read_text())["stats"]
gsrc = "cfd/geometry/gcode_profiles/<set>_z1226.json stats"
for _s, tag in (("Ra10", "Ten"), ("Ra40", "Forty"), ("Ra80", "Eighty")):
    N.num(f"nGcRa{tag}", GC[_s]["both"]["Ra_mm"] * 1e3, 1, f"{gsrc}: {_s} both faces Ra, um")
_rt = [GC[_s]["both"]["Ra_mm"] / GC[_s]["synthetic"]["t_mm"] for _s in GC]
N.num("nGcRatioLo", min(_rt), 2, f"{gsrc}: Ra / nominal t, smallest of Ra10, Ra40, Ra80")
N.num("nGcRatioHi", max(_rt), 2, f"{gsrc}: Ra / nominal t, largest")
for _s, tag in (("Ra40", "Forty"), ("Ra80", "Eighty")):
    span, scan = GC[_s]["spanwise"]["Ra_lc025_mm"] * 1e3, GC[_s]["scans"]["Ra_lc025_um"]
    N.num(f"nGcSpan{tag}", span, 1, f"{gsrc}: {_s} spanwise Ra after lambda_c 0.25 mm, um")
    N.num(f"nGcOverScan{tag}", span / scan, 1, f"{gsrc}: {_s} spanwise Ra_lc025 / measured scan Ra_lc025 (surface_roughness.csv)")

# =================================================================== figure 1: each effect next to its numerics
fig, (axa, axb) = plt.subplots(1, 2, figsize=(7.3, 2.0), gridspec_kw={"width_ratios": [2.15, 1], "wspace": 0.42})
fams = [("Rough wall, α 90°\nKs 400 µm", eff_wf90, None, step_wf90, ("", "no mesh study", "")),
        ("Rough wall, α 180°\nKs 400 µm", eff_wf180, None, step_wf180, ("", "no mesh study", "")),
        ("Texture, α 180°\nt 0.20 mm", eff_tex, None, step_tex, ("", "one mesh: B1", "")),
        ("Smooth, α 90°", None, mesh_sm90, None, ("no roughness", "", "untested: B1")),
        ("Smooth, α 180°", None, mesh_sm180, step_sm180, ("no roughness", "", ""))]
off = (0.27, 0.0, -0.27)
cols = (NAVY, GREY, GOLD)
for i, (lab, *vals, notes) in enumerate(fams):
    y0 = -i
    for v, dy, c, note in zip(vals, off, cols, notes):
        if v is None:
            ax_note = note or "n/a"
            axa.plot(0, y0 + dy, marker="x", color=INK2, ms=4, lw=0)
            axa.annotate(ax_note, (0, y0 + dy), xytext=(5, 0), textcoords="offset points", va="center", fontsize=7, color=INK2, style="italic")
            continue
        axa.barh(y0 + dy, v, 0.25, color=c)
        axa.annotate(f"{v:+.1f}%".replace("-", "\u2212"), (v, y0 + dy), xytext=(3 if v >= 0 else -3, 0), textcoords="offset points",
                     va="center", ha="left" if v >= 0 else "right", fontsize=7, color=INK2)
axa.set_yticks([-i for i in range(len(fams))], [f[0] for f in fams], fontsize=8)
axa.axvline(0, color=INK2, lw=0.8)
axa.set_xlim(-32, 60)
axa.set_xlabel("Change of the section drag (%)", fontsize=8.5)
axa.set_title("(a) Single blade, 23 m/s", loc="left", fontsize=9)
axa.tick_params(axis="x", labelsize=8)
fig.legend(handles=[Patch(color=NAVY, label="roughness effect"), Patch(color=GREY, label="mesh: spread of three meshes"),
                    Patch(color=GOLD, label="time step halved: change of the reference level")], frameon=False, fontsize=7.5,
           loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=3)
rot = [("Ks 400 − Ks 0\n(medium, maxCo 4)", float(p10["dCQ"]), float(p10["two_u"]), NAVY),
       ("fine − coarse\n(smooth, λ 0.10)", rot_mesh, rot_mesh_u, GREY),
       ("maxCo 2 − maxCo 4\n(smooth, λ 0.15)", rot_step, rot_step_u, GOLD)]
for j, (lab, v, u, c) in enumerate(rot):
    axb.barh(-j, v, 0.5, color=c)
    axb.errorbar(v, -j, xerr=u, color=INK, lw=0.9, capsize=3)
axb.set_yticks([-j for j in range(3)], [r[0] for r in rot], fontsize=7.5)
axb.axvline(0, color=INK2, lw=0.8)
axb.set_xlim(-0.022, 0.028)
axb.set_xlabel("Change of rotor $C_Q$ (±2u)", fontsize=8.5)
axb.set_title("(b) Rotor, 23 m/s", loc="left", fontsize=9)
axb.tick_params(axis="x", labelsize=7.5)
save(fig, "fig1_numerics")

# =================================================================== B1 figure (for the revision after B1)
fig, axs = plt.subplots(1, 3, figsize=(7.3, 1.65), gridspec_kw={"wspace": 0.45, "width_ratios": [1, 1.25, 1.1]})


def pending_at(ax, x, marker="o", text="B1"):
    """A B1 slot not yet run: an open marker in a shaded band at the foot of the axes, not at a value."""
    tr = ax.get_xaxis_transform()
    if not getattr(ax, "_b1_band", False):
        ax.add_patch(plt.Rectangle((0, 0), 1, 0.2, transform=ax.transAxes, fc=NOTE, ec="none", zorder=0))
        ax.text(0.99, 0.015, "not run yet", transform=ax.transAxes, ha="right", va="bottom", fontsize=6, color=GREY)
        ax._b1_band = True
    ax.plot(x, 0.07, marker=marker, mfc="white", mec=GREY, ls="", ms=5.5, transform=tr, clip_on=False)
    ax.text(x, 0.13, text, transform=tr, ha="center", va="bottom", fontsize=6.5, color=INK2, style="italic")


ax = axs[0]
xs = {"2.5": 0, "1.25": 1, "0.625": 2}
ax.plot([0, 1], [float(med25["Cd_mean"]), float(med125["Cd_mean"])], "s-", color=NAVY, ms=5, label="medium")
ax.plot([0], [float(grid_cases["coarse"][2]["Cd_mean"])], "^", color=GREY, ms=5, label="coarse")
ax.plot([0], [float(grid_cases["fine"][2]["Cd_mean"])], "v", color=INK, ms=5, label="fine")
for x, v, mk, c in ((2, s1[0], "s", NAVY), (0.85, s1[1], "^", GREY), (1.15, s1[2], "v", INK)):
    if v is None:
        pending_at(ax, x, mk, "B1" if mk != "v" else "")
    else:
        ax.plot(x, v, mk, color=c, ms=6, mec=INK)
ax.set_xticks(list(xs.values()), list(xs.keys()), fontsize=8)
ax.set_xlim(-0.4, 2.4)
ax.set_ylim(0.9, 1.85)
ax.set_xlabel("maxCo (smaller = shorter time step)", fontsize=7.5)
ax.set_ylabel("Cd at α 180°", fontsize=8)
ax.set_title("(a) Smooth blade", loc="left", fontsize=9)
ax.legend(frameon=False, fontsize=6.5, loc="upper right", handletextpad=0.2)
ax.tick_params(labelsize=7.5)

ax = axs[1]
cats = ["5", "2.5", "1.25", "2.5\n20 µm", "α 90°\n2.5", "α 90°\n1.25"]
ax.axhspan(eff_tex - sv("acc_effect_pts"), eff_tex + sv("acc_effect_pts"), xmin=0.32, xmax=0.72, color=NAVY, alpha=0.08, lw=0)
ax.plot([0], [float(e5["dCd_pct"])], "o", mfc="white", mec=NAVY, ms=5)
ax.plot([1], [eff_tex], "o", color=NAVY, ms=5)
for x, v in ((2, B1V["T1"][1]), (3, B1V["T2a"][1]), (4, B1V["E90t"][0]), (5, B1V["E90t"][1])):
    if v is None:
        pending_at(ax, x)
    else:
        ax.plot(x, v, "o", color=GOLD, ms=6, mec=INK)
ax.set_xticks(range(len(cats)), cats, fontsize=7)
ax.set_ylim(-2, 24)
ax.axhline(0, color=INK2, lw=0.6)
ax.set_ylabel("Drag change, t 0.20 mm (%)", fontsize=8)
ax.set_title("(b) Texture, α 180° unless marked", loc="left", fontsize=9)
ax.annotate(f"keep if inside\n(±{sv('acc_effect_pts'):.0f} points)", (2.5, eff_tex + sv("acc_effect_pts")), xytext=(0, 2),
            textcoords="offset points", ha="center", fontsize=6.5, color=NAVY)
ax.tick_params(labelsize=7.5)
ax.set_xlabel("maxCo (wall spacing 40 µm unless marked)", fontsize=7.5)

ax = axs[2]
cats = ["medium\nmaxCo 4", "fine", "medium\nmaxCo 2", "coarse"]
ax.axhspan(float(p10["dCQ"]) - sv("acc_rotor"), float(p10["dCQ"]) + sv("acc_rotor"), xmin=0.28, xmax=0.97, color=NAVY, alpha=0.08, lw=0)
ax.errorbar([0], [float(p10["dCQ"])], yerr=[float(p10["two_u"])], fmt="o", color=NAVY, ms=5, capsize=3, lw=0.9)
for x, v in ((1, B1V["R1"][0]), (2, B1V["R1"][1]), (3, B1V["R1"][2])):
    if v is None:
        pending_at(ax, x)
    else:
        ax.plot(x, v, "o", color=GOLD, ms=6, mec=INK)
ax.axhline(0, color=INK2, lw=0.6)
ax.set_xticks(range(len(cats)), cats, fontsize=7)
ax.set_xlim(-0.5, 3.5)
ax.set_ylim(-0.004, 0.012)
ax.set_ylabel("Rotor $C_Q$, Ks 400 − Ks 0", fontsize=8)
ax.set_title("(c) Rotor, λ 0.10", loc="left", fontsize=9)
ax.tick_params(labelsize=7.5)
save(fig, "figB1_checks")


# =================================================================== figures 2 and 3: J3 (2026-11-15 tables, else pending)
def placeholder(name, title, lines, size=(3.45, 3.3)):
    fig, ax = plt.subplots(figsize=size)
    ax.set_axis_off()
    ax.add_patch(plt.Rectangle((0.01, 0.01), 0.98, 0.98, transform=ax.transAxes, fc=NOTE, ec=RULE, lw=0.8))
    ax.text(0.5, 0.66, "Pending", transform=ax.transAxes, ha="center", va="center", fontsize=13, color=INK2, fontweight="bold")
    ax.text(0.5, 0.52, title, transform=ax.transAxes, ha="center", va="center", fontsize=8, color=INK2)
    ax.text(0.5, 0.30, "\n".join(lines), transform=ax.transAxes, ha="center", va="center", fontsize=6.8, color=GREY, family="monospace")
    save(fig, name)


fig3_state = "pending"
if SURF_PROF.exists():
    prof = read_csv(f"{A1115}/surface_profiles.csv")
    byname = {}
    for r in prof:
        byname.setdefault(r.get("name"), []).append(r)
    panels = [("(a) α 90°, edge-on", [("a090.0_U23.0_SST_wf_Ks0_Tu1.0_Co2.5n2", "rough wall, Ks 0", INK2, "-"),
                                     ("a090.0_U23.0_SST_wf_Ks400_Tu1.0_Co2.5n2", "rough wall, Ks 400 µm", NAVY, "-")]),
              ("(b) α 180°, convex side to the wind", [("a180.0_U23.0_SST_wf_Ks0_Tu1.0_Co2.5n2", "rough wall, Ks 0", INK2, "-"),
                                     ("a180.0_U23.0_SST_wf_Ks400_Tu1.0_Co2.5n2", "rough wall, Ks 400 µm", NAVY, "-"),
                                     ("a180.0_U23.0_SST_tex0.000_s1_Tu1.0_Co2.5n2", "texture mesh, t 0", GREY, "--"),
                                     ("a180.0_U23.0_SST_tex0.200_s1_Tu1.0_Co2.5n2", "texture mesh, t 0.20 mm", GOLD, "-")])]
    need = {"name", "face", "loop_over_c", "Cp_1mm", "Cf_1mm"}
    if prof and need <= set(prof[0]) and all(c in byname for _, cs in panels for c, *_ in cs):
        fig, axs = plt.subplots(2, 2, figsize=(7.3, 2.2), sharex=True, gridspec_kw={"hspace": 0.1, "wspace": 0.2,
                                                                                    "height_ratios": [1.25, 1]})
        for j, (title, cases) in enumerate(panels):
            for case, lab, col, ls in cases:
                rs = sorted(byname[case], key=lambda r: float(r["loop_over_c"]))
                x = np.array([float(r["loop_over_c"]) for r in rs])
                axs[0, j].plot(x, [float(r["Cp_1mm"]) for r in rs], ls, color=col, lw=0.9, label=lab)
                if "tex0.200" not in case:     # textured wall: the shear reverses at the facet scale (surface_extract.py)
                    axs[1, j].plot(x, [float(r["Cf_1mm"]) for r in rs], ls, color=col, lw=0.9)
            spans = {}
            for r in byname[cases[0][0]]:
                lo, hi = spans.get(r["face"], (9.0, -9.0))
                spans[r["face"]] = (min(lo, float(r["loop_over_c"])), max(hi, float(r["loop_over_c"])))
            for a in axs[:, j]:
                for face in ("endB", "endA"):
                    if face in spans:
                        a.axvspan(*spans[face], color=RULE, alpha=0.6, lw=0)
                a.tick_params(labelsize=7)
            for face, lab in (("convex", "convex face"), ("concave", "concave face")):
                if face in spans:
                    axs[0, j].text(sum(spans[face]) / 2, 1.0, lab, transform=axs[0, j].get_xaxis_transform(), ha="center",
                                   va="bottom", fontsize=6.5, color=INK2)
            axs[0, j].set_title(title, loc="left", fontsize=8.5, pad=11)
            axs[0, j].invert_yaxis()
            axs[1, j].axhline(0, color=INK2, lw=0.5)
            axs[1, j].set_xlabel("position round the wall from tip A, loop/c (grey: square tip faces)", fontsize=7)
        axs[0, 0].set_ylabel("Cp (1 mm mean)", fontsize=8)
        axs[1, 0].set_ylabel("Cf (1 mm mean)", fontsize=8)
        axs[0, 1].legend(frameon=False, fontsize=6.2, loc="lower right", ncol=2, handlelength=1.6, columnspacing=0.8)
        save(fig, "fig2_surface")
        fig3_state = "data"
    else:
        placeholder("fig2_surface", "wall Cp and Cf around the blade", ["surface_profiles.csv present,", "cases or columns not found"])
        fig3_state = "unrecognised"
else:
    placeholder("fig2_surface", "wall Cp and Cf around the blade:\nsmooth, Ks 400 µm, texture",
                ["cfd/analysis/2026-11-15/out/", "surface_profiles.csv"])
N.tex("nSurfFigState", "" if fig3_state == "data" else r"\pending", f"{A1115}/surface_profiles.csv: {fig3_state}")

if have_pf:
    pfr = read_csv(f"{A1115}/rotor_phase_force.csv")
    lev = {w: sorted([r for r in pfr if r["lam"] == "0.1" and r["wall"] == w and r["blade"] == "mean"],
                     key=lambda r: float(r["theta_mid_deg"])) for w in ("Ks0", "Ks400")}
    PFD = REPO / A1115 / "rotor_phase_force_diff.csv"
    dif = {}
    if PFD.exists():
        pfd = read_csv(f"{A1115}/rotor_phase_force_diff.csv")
        dif = {a: sorted([r for r in pfd if r["lam"] == "0.1" and r["a"] == a and r["b"] == "Ks0" and r["blade"] == "mean"],
                         key=lambda r: float(r["theta_mid_deg"])) for a in ("Ks400", "Ks100")}
    rows_n = 2 if dif else 1
    fig, axs = plt.subplots(rows_n, 3, figsize=(7.3, 1.03 * rows_n + 0.3), sharex=True, squeeze=False,
                            gridspec_kw={"wspace": 0.32, "hspace": 0.12})
    qty = (("CQ_blade", "blade torque $C_Q$"), ("CD", "drag $C_D$"), ("CL", "lift $C_L$"))
    for k, (col, lab) in enumerate(qty):
        for i_row in range(rows_n):
            a = axs[i_row, k]
            for lo, hi, c in ((60, 120, NAVY), (240, 300, GREY)):
                a.axvspan(lo, hi, color=c, alpha=0.08, lw=0)
            a.axhline(0, color=INK2, lw=0.4)
            a.tick_params(labelsize=7)
        a = axs[0, k]
        for w, c, lab2 in (("Ks0", INK2, "Ks 0"), ("Ks400", NAVY, "Ks 400 µm")):
            th = np.array([float(r["theta_mid_deg"]) for r in lev[w]])
            v, u = (np.array([float(r[x]) for r in lev[w]]) for x in (col, col + "_2u"))
            a.plot(th, v, color=c, lw=1.0, label=lab2)
            a.fill_between(th, v - u, v + u, color=c, alpha=0.2, lw=0)
        a.set_title(lab, loc="left", fontsize=8.5)
        if dif:
            a = axs[1, k]
            for w, c, lab2 in (("Ks400", NAVY, "Ks 400 − Ks 0"), ("Ks100", GOLD, "Ks 100 − Ks 0")):
                th = np.array([float(r["theta_mid_deg"]) for r in dif[w]])
                v, u = (np.array([float(r[x]) for r in dif[w]]) for x in ("d" + col, "d" + col + "_2u"))
                a.plot(th, v, color=c, lw=1.0, label=lab2)
                a.fill_between(th, v - u, v + u, color=c, alpha=0.25, lw=0)
        axs[-1, k].set_xlabel("blade azimuth θ (°)", fontsize=7.5)
        axs[-1, k].set_xticks(range(0, 361, 90))
    axs[0, 0].set_ylabel("level", fontsize=8)
    axs[0, 2].legend(frameon=False, fontsize=6.3, loc="lower left")
    if dif:
        axs[1, 0].set_ylabel("change (±2u)", fontsize=8)
        axs[1, 2].legend(frameon=False, fontsize=6.3, loc="lower left")
    for xm, txt, c in ((90, "advancing", NAVY), (270, "returning", INK2)):
        axs[0, 0].text(xm, 0.97, txt, transform=axs[0, 0].get_xaxis_transform(), ha="center", va="top", fontsize=6.3, color=c)
    save(fig, "fig3_rotor_phase")
else:
    placeholder("fig3_rotor_phase", "blade torque, lift and drag\nagainst azimuth, Ks 0 and 400 µm",
                ["cfd/analysis/2026-11-15/out/", "rotor_phase_force*.csv"])

# =================================================================== figure 4: J4, the change against Ks+
fig, (axa, axb) = plt.subplots(1, 2, figsize=(7.3, 1.75), gridspec_kw={"wspace": 0.32})
for a, c, mk in ((90, NAVY, "s"), (180, GOLD, "o")):
    xs25 = ksp_sec[a]
    ys25 = [float(wfrow(a, k, 2.5)["dCd_pct"]) for k in KS_SWEEP]
    axa.plot(xs25, ys25, mk + "-", color=c, ms=4.5, lw=1.0, label=f"α {a}°")
    ks5 = [k for k in KS_SWEEP if f"a{a:05.1f}_U23.0_SST_wf_Ks{k}_Tu1.0" in WF]
    axa.plot([float(wfrow(a, k, 5)["ksplus_mean"]) for k in ks5], [float(wfrow(a, k, 5)["dCd_pct"]) for k in ks5],
             mk, mfc="white", mec=c, ms=4.5, lw=0)
lo_b, hi_b = min(b[0] for b in band_sec.values()), max(b[1] for b in band_sec.values())
axa.axvspan(lo_b, hi_b, color=GREY, alpha=0.22, lw=0)
axa.annotate(f"printed blades\nif Ks = k\n({K_LO:.0f}–{K_HI:.0f} µm)", ((lo_b + hi_b) / 2, 30), ha="center", fontsize=6.5, color=INK2)
for k, lab in ((sv("ks_nom_fs10_um"), "FS 0.10\nnominal"), (sv("ks_nom_fs20_um"), "FS 0.20\nnominal")):
    xk = float(np.interp(k, KS_SWEEP, ksp_sec[90])) if k <= 400 else ksp_sec[90][-1] * k / 400
    axa.annotate(lab, (xk, -6), ha="center", fontsize=6.5, color=NAVY)
    axa.plot([xk, xk], [-2.5, -0.5], color=NAVY, lw=0.8)
axa.axhline(0, color=INK2, lw=0.6)
axa.set_ylim(-9, 50)
axa.set_xlim(0, 42)
axa.set_xlabel("Ks+ (blade mean)", fontsize=8.5)
axa.set_ylabel("Drag change from Ks 0 (%)", fontsize=8.5)
axa.set_title("(a) Single blade, rough wall, 23 m/s", loc="left", fontsize=9)
axa.legend(frameon=False, fontsize=7, loc="upper left")
axa.tick_params(labelsize=7.5)
rows_b = []
for lam, mk, dx in (("0.1", "o", -0.25), ("0.12", "D", 0.25)):
    for ks, nm in ((100, "Ks100"), (400, "Ks400")):
        r = rpair(lam, nm)
        sct = sector(lam, nm, "adv")
        x = runs[f"{float(lam):.2f}_{nm}"]["ksplus_mean"] + dx
        axb.errorbar(x, float(r["dCQ"]), yerr=float(r["two_u"]), fmt=mk, color=NAVY, ms=4.5, capsize=2.5, lw=0.8,
                     label=f"rotor total, λ {float(lam):.2f}" if ks == 100 else None)
        axb.errorbar(x + 0.8, float(sct["d"]), yerr=float(sct["two_u"]), fmt=mk, mfc="white", mec=GOLD, ecolor=GOLD, ms=4.5,
                     capsize=2.5, lw=0.8, label=f"advancing sector, λ {float(lam):.2f}" if ks == 100 else None)
axb.axvspan(min(band_rot), max(band_rot), color=GREY, alpha=0.22, lw=0)
axb.axhline(0, color=INK2, lw=0.6)
axb.set_xlim(0, 40)
axb.set_ylim(-0.008, 0.013)
axb.set_xlabel("Ks+ (blade mean)", fontsize=8.5)
axb.set_ylabel("Rotor $C_Q$ change from Ks 0 (±2u)", fontsize=8.5)
axb.set_title("(b) Rotor, 23 m/s", loc="left", fontsize=9)
axb.legend(frameon=False, fontsize=6.3, loc="upper left")
axb.tick_params(labelsize=7.5)
save(fig, "fig4_ksplus")

# =================================================================== figure 5: J7, tip-speed ratio through the loading
fans = [("600", "(a)"), (FAN_23, "(b)"), ("1800", "(c)")]
fig, axs = plt.subplots(1, 3, figsize=(7.3, 1.5), sharey=True, gridspec_kw={"wspace": 0.12})
for ax, (fan, tag) in zip(axs, fans):
    wind = np.mean([float(r["wind_mps"]) for r in dwell if r["fan_rpm_cmd"] == fan])
    for s in SETS:
        for run, ls in (("1", "-"), ("2", "--")):
            rs = sorted(by_run.get((fan, s, run), []), key=lambda r: float(r["demand_a"]))
            ax.plot([float(r["torque_gen_nm"]) for r in rs], [float(r["tip_speed_ratio"]) for r in rs], ls,
                    color=SET_COLOUR[s], lw=0.9, label=s if (run == "1" and fan == "600") else None)
    if fan == FAN_23:
        for lam in (0.10, 0.12):
            ax.axhline(lam, color=GOLD, lw=0.8, ls=":")
        ax.annotate("CFD runs: λ 0.10 and 0.12", (ax.get_xlim()[0], 0.10), xytext=(3, -9), textcoords="offset points",
                    ha="left", fontsize=6.5, color=GOLD)
    ax.set_title(f"{tag} {wind:.1f} m/s", loc="left", fontsize=9)
    ax.set_xlabel("Generator torque (N·m)", fontsize=8)
    ax.tick_params(labelsize=7.5)
axs[0].set_ylabel("Tip-speed ratio λ", fontsize=8.5)
axs[0].legend(frameon=False, fontsize=6.5, loc="lower left")
save(fig, "fig5_rotor_speed")

# =================================================================== provenance.tex
unused = sorted(set(SV) - SV_USED)
if unused:
    print("note: stated values not used:", ", ".join(unused))


def git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True).stdout


def sha(paths):
    h = hashlib.sha256()
    if len(paths) == 1:
        h.update(paths[0].read_bytes())
    else:
        for p in paths:
            h.update(str(p.relative_to(REPO)).encode() + b"\0" + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()[:8]


rels = {label: [str(p.relative_to(REPO)) for p in paths] for label, paths in INPUTS.items()}
tracked = set(git("ls-files", "--", *[r for v in rels.values() for r in v]).split())
changed = set(git("diff", "--name-only", "HEAD").split())
head = git("rev-parse", "--short=7", "HEAD").strip()
dirty = bool(git("status", "--porcelain", "--untracked-files=no").strip())
when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def status(label):
    files = rels[label]
    if all(f in tracked for f in files):
        return "tracked, modified" if any(f in changed for f in files) else "tracked"
    ignored = git("check-ignore", *files).split()
    return "local" if ignored else "untracked"


def texpath(s):
    return s.replace("_", r"\_").replace("*", r"$*$")


groups = {}
for label in sorted(INPUTS):
    d, _, base = label.rpartition("/")
    n = len(INPUTS[label])
    st = status(label)
    groups.setdefault(d, []).append(f"{base.replace('_', chr(92) + '_')}{f' ({n} files)' if n > 1 else ''} {sha(INPUTS[label])}"
                                    f"{'' if st == 'tracked' else ' ' + st}")
items = [f"\\nolinkurl{{{d}/}} " + ", ".join(v) for d, v in groups.items()]
lines = ["% provenance.tex: generated by make_figures.py; do not edit.",
         f"\\newcommand{{\\BuildGit}}{{{head}{' (+ uncommitted changes)' if dirty else ''}}}",
         f"\\newcommand{{\\BuildDate}}{{{when}}}",
         f"\\newcommand{{\\NInputs}}{{{len(INPUTS)}}}",
         "\\newcommand{\\ProvenanceList}{%", "; ".join(items) + ".}"]
(HERE / "provenance.tex").write_text("\n".join(lines) + "\n")
N.write(HERE / "numbers.tex")
print(f"numbers.tex: {len(N.rows)} macros, {sum(t == chr(92) + 'pending' for _, t, _ in N.rows)} pending; "
      f"provenance.tex: {len(INPUTS)} inputs; B1 cases finished: {sum(b1_row(*c) is not None for v in B1.values() for c in v)}/{len(B1_NAMES)}; "
      f"fig 2: {fig3_state}; fig 3: {'data' if have_pf else 'pending'}")
