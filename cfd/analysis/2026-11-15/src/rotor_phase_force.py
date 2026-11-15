#!/usr/bin/env python3
"""Blade forces through the rotation, 15 Nov 2026 (cfd/rotor2d, 2D URANS): each blade's streamwise and
cross-stream force, lift and drag about its relative wind, and torque split into pressure and viscous
parts, against blade azimuth, for the eight 45-revolution runs of cfd/rotor2d/queues/priorityE_rough.txt.

    nice -n 10 python3 cfd/analysis/2026-11-15/src/rotor_phase_force.py

Why
  Dr. Jahangiri's 1 Nov questions J3 (separation, pressure, lift, drag and torque through the rotation)
  and J4 (why the gain appears at Ks 400 um but is inconclusive near the printed roughness). The 15 Oct
  analysis binned only each blade's torque by azimuth (cfd/analysis/2026-10-15/out/
  rotor_roughness_phase.csv, rotor_roughness_sectors.csv) and quoted the streamwise force in two 20-deg
  windows (cfd/analysis/2026-10-15/src/rotor_review_check.py). The per-blade force and moment histories
  of the same runs hold the rest; this script extracts it. Existing runs only: no 15 Nov verification
  run (B1) is used, so the mesh and time-step errors of these numbers are still open.

Reads (read only)
  cfd/rotor2d/queues/priorityE_rough.txt   the eight runs: lambda 0.10, 0.12 x (Spalding, Ks 0, 100, 400 um)
  cfd/rotor2d/runs/<case>/case.json, mesh_info.json (pose_full: the blade pose of the mesh),
      results.json (per-blade window means, checks only),
      postProcessing/forces{Blade1,Blade2,Blade3,Rotor}/0/{force,moment}.dat
  cfd/rotor2d/results/rotor_cp.csv         window means of the runs (checks only)
  cfd/rotor2d/rotor_geometry.py            imported, not edited: blade section (cfd/geometry/section_v1.json),
                                           its area centroid and outer-tip chord, model-frame placement
  cfd/analysis/2026-10-15/src/rotor_analysis.py   imported, not edited: phase_bins (the binning rule, and
                                           checked against), cumint, SECTORS, sector_mask, style, colours
  cfd/analysis/2026-10-15/out/rotor_roughness_phase.csv, rotor_roughness_sectors.csv, rotor_numbers.json
                                           (15 Oct numbers, checks only; the physics link's Stage 2 alpha-90
                                           section coefficients for the context rows)
Writes
  ../out/rotor_phase_force.csv          8 runs x blade (1, 2, 3, mean) x 36 bins: coefficients, each with 2u
                                        (and, for the mean, the between-blade 2u)
  ../out/rotor_phase_force_diff.csv     Ks 400 - Ks 0 and Ks 100 - Ks 0 (same wall function), per lambda,
                                        blade and bin, each with 2u (and the between-blade 2u for the mean)
  ../out/rotor_phase_force_sectors.csv  the same by azimuth sector (the 15 Oct sectors, the gaps between
                                        them and the whole revolution): the 8 runs and the 5 differences of
                                        rotor_roughness_sectors.csv
  ../out/rotor_phase_force_check.csv    every check: reference value and its source, recomputed value,
                                        tolerance, pass. kind 'validation' (the script exits 1 if one fails),
                                        'diagnostic' (ok False = flagged, not fatal) or 'context' (no test)
  ../fig/rotor_phase_force.png          blade torque, lift and drag against azimuth, Ks 0 and Ks 400 um,
                                        lambda 0.10 and 0.12
  ../fig/rotor_phase_force_diff.png     their changes, Ks 400 - Ks 0 and Ks 100 - Ks 0, +-2u

Conventions
  Frame and azimuth (cfd/rotor2d/README.md). Shaft axis at the origin, wind along +x, z out of the plane;
  assembly A turning counter-clockwise (s = +1, curled tip B leading). Blade azimuth theta is 0 when
  blade 1's radial line (shaft to attachment point) points upwind (-x) and grows with the rotation;
  blade k sits at theta_1 + 120 (k - 1), theta_1 = Omega t (thetaDeg 0 in every run). theta 0: upwind,
  convex side to the wind; 90: advancing, edge-on, moving downwind, tip A first; 180: cup to the wind;
  270: returning, edge-on, curl first.
  Bins (rotor_analysis.py phase_bins, reused): 36 bins of 10 deg, [10 m, 10 m + 10). In each of the last
  45 of the 50 revolutions (the runs' averaging window; revolutions counted on blade 1), a bin's value is
  the time mean of the quantity while the blade is in the bin: the cumulative trapezoid integral of the
  0.5-deg samples, interpolated at the instants the blade crosses the bin edges. Every quantity is formed
  sample by sample before it is binned. 'mean' = the three blades averaged within each revolution.
  Forces, per unit span, on the free-stream dynamic pressure q = rho U^2 / 2 and the section reference
  chord c_ref = 48 mm (cfd/section2d/README.md section 1; as rotor_review_check.py): C = F / (q c_ref dz).
  Cx streamwise (+x, downwind), Cy cross-stream (+y).
  Relative wind (geometric): W = U e_x - Omega e_z x r_c at the blade section's area centroid r_c, 96.79 mm
  from the shaft and 1.37 deg ahead of the attachment line (rotor_geometry.py with the mesh's pose;
  poses_A_B.json r_centroid_m). Why the centroid and not the attachment radius R = 101.6 mm: the blade
  turns rigidly, so its velocity is linear in position and the centroid's velocity is the blade's
  area-mean velocity; the centroid is also the origin of the section body frame (cfd/section2d/README.md)
  and the 15 Oct lever arm (rotor_analysis.py physics link). The attachment point changes lift and drag
  by little (check 'radius sensitivity'). W leaves out the rotor's induced velocity and blockage, which
  force histories cannot give: lift and drag are about the geometric relative wind. At lambda 0.10 and
  0.12, W stays within 5.5 and 6.6 deg of +x, so CD ~ Cx and CL ~ Cy.
  Drag CD along W, lift CL 90 deg counter-clockwise from W: the section's dragDir and liftDir
  (cfd/section2d/README.md section 1). CD_p, CD_v: pressure and viscous parts of CD. CL_W, CD_W: the same
  forces on the local dynamic pressure rho |W|^2 / 2 (sample by sample), for comparison with section
  polars at alpha_geo, the section angle of attack (cfd/section2d/README.md section 1: body x normal to the
  outer-tip chord, toward the convex side) of W at the bin centre. Cm_c: moment about the blade's area
  centroid, counter-clockwise positive, on q c_ref^2 dz (the section's Cm); M_z = (r_c x F)_z + M_c.
  Torque, on the rotor's scale (cfd/rotor2d/README.md): CQ_blade = s M_z / dz / (q (2R) R), R = 101.6 mm,
  positive when it drives the rotor; the three blades sum to the rotor C_Q, so 3 x (mean over the 36 bins)
  is the rotor's window-mean C_Q. CQ_blade_p, CQ_blade_v: pressure and viscous parts (the moment file's
  columns).
  Sectors (rotor_analysis.py SECTORS): upwind 330-30, advancing 60-120, downwind 150-210, returning
  240-300 deg, the four 30-deg gaps, the whole revolution. Torque (columns CQ_contrib*): contribution to
  the rotor C_Q, 3 x (sum over the sector's bins) / 36, so the four sectors and the gaps add up to the
  rotor C_Q. Forces and Cm_c: mean over the sector's bins.
  Uncertainty, 2u (the 15 Oct rule, asked for): u = s / sqrt(45), s the standard deviation (n - 1) of the
  45 revolution values of the bin or sector. A difference of two runs: u = sqrt(u_a^2 + u_b^2)
  (independent runs). It covers the revolution-to-revolution scatter only, not the mesh, the time step,
  the wall function or the turbulence model. A difference is 'resolved' when it exceeds its 2u.
  Between-blade 2u (columns *_2u_blades, three-blade means only): 2 sd / sqrt(3), sd the standard
  deviation (n - 1) of the three blades' 45-revolution means; for a difference, the two runs' combined in
  quadrature (unpaired: the blades' deviation patterns differ from run to run). Added because the three
  nominally identical blades differ by more than their revolution scatter (check file, blade-to-blade). It
  has 2 degrees of freedom per run: an indicator of that spread, not a replacement for 2u.

Checks (rotor_phase_force_check.csv)
  validation: the binning reproduces rotor_analysis.py phase_bins to 1e-12; the blade torque by azimuth
  and its u reproduce rotor_roughness_phase.csv, and the sector contributions, differences and 2u
  reproduce rotor_roughness_sectors.csv, to their 6 printed significant digits; the quoted 15 Oct numbers
  (UPDATE.md section 7, rotor_review_check.py: sector changes, the Spalding budget, the blade's streamwise
  force change at theta 80-100 and 260-280 deg, among them +7.5 +- 1.6 % at Ks 100 um, the pressure and
  viscous parts of the rotor's change, the rotor C_x change; rotor_numbers.json physics link) to their
  printed digits; window means against rotor_cp.csv and results.json within 2u; the blade forces and
  moments sum to the rotor's; total = pressure + viscous; the lever check (M_z against r_c x F) picks the
  azimuth convention used here over the blades 2 and 3 swapped.
  diagnostic: blade-to-blade consistency, lag-1 autocorrelation and batch means (9 x 5 revolutions) of
  the revolution values, sensitivity of lift and drag to the reference radius.
  context: the change of the rotor blade's CD_W and CL_W at theta 90-100 deg (alpha_geo about 89 deg)
  against the static section's at alpha 90 (Stage 2 wall-function runs, maxCo 2.5; rotor_numbers.json
  physics link): a quasi-steady comparison about the geometric wind, not a test.
"""
import sys

sys.dont_write_bytecode = True          # imported modules (15 Oct, rotor2d) get no __pycache__ from this run

import importlib.util  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

HERE = Path(__file__).resolve().parent
BASE = HERE.parent                      # cfd/analysis/2026-11-15
REPO = BASE.parents[2]                  # repository root
OUT, FIG = BASE / "out", BASE / "fig"
RUNS = REPO / "cfd/rotor2d/runs"
QUEUE = REPO / "cfd/rotor2d/queues/priorityE_rough.txt"
ROTOR_CP = REPO / "cfd/rotor2d/results/rotor_cp.csv"
OCT15 = REPO / "cfd/analysis/2026-10-15"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ra = _load("rotor_analysis_20261015", OCT15 / "src/rotor_analysis.py")    # 15 Oct binning, sectors, style
rg = _load("rotor_geometry_cfd", REPO / "cfd/rotor2d/rotor_geometry.py")   # blade section and placement

C_REF = 0.048           # m, section reference chord (cfd/section2d/README.md section 1; rotor_review_check.py)
NB = 36                 # 10-deg bins: rotor_analysis.py phase_bins(nb=36), rotor_roughness_phase.csv
LAMS = (0.10, 0.12)
WALLS = ("spalding", "Ks0", "Ks100", "Ks400")
SUFFIX = {"spalding": "", "Ks0": "_Ks0", "Ks100": "_Ks100", "Ks400": "_Ks400"}
WALL_FN = {"spalding": "nutUSpaldingWallFunction", "Ks0": "nutkRoughWallFunction",
           "Ks100": "nutkRoughWallFunction", "Ks400": "nutkRoughWallFunction"}
# the roughness effect: rough minus Ks 0 with the same wall function (priorityE_rough.txt header)
PAIRS = (("Ks400", "Ks0"), ("Ks100", "Ks0"))
PAIRS_15OCT = (("Ks400", "Ks0"), ("Ks100", "Ks0"), ("Ks0", "spalding"), ("Ks400", "spalding"),
               ("Ks100", "spalding"))      # the differences of rotor_roughness_sectors.csv
QUANTS = ("Cx", "Cy", "CL", "CD", "CQ_blade", "CQ_blade_p", "CQ_blade_v",     # asked for (J3)
          "CD_p", "CD_v", "CL_W", "CD_W", "Cm_c")                            # added: drag split, local q, Cm
TORQUE = ("CQ_blade", "CQ_blade_p", "CQ_blade_v")
GAPS = "the four 30° gaps between"
WHOLE = "whole revolution"
SECT_RANGE = {"upwind": "330-30", "advancing": "60-120", "downwind": "150-210", "returning": "240-300",
              GAPS: "30-60, 120-150, 210-240, 300-330", WHOLE: "0-360"}

# ---------------------------------------------------------------- quoted 15 Oct numbers (checks)
SRC_RC = "cfd/analysis/2026-10-15/src/rotor_review_check.py (corrected findings)"
SRC_UP = "cfd/analysis/2026-10-15/UPDATE.md section 7"
# sector changes of the rotor C_Q, (d, 2u), printed to 4 decimals (rotor_review_check.py; UPDATE.md section 7)
Q_SECT = {(0.10, "Ks400", "Ks0"): dict(advancing=(0.0092, 0.0006), returning=(-0.0048, 0.0022),
                                       upwind=(-0.0015, 0.0006), downwind=(0.0032, 0.0011)),
          (0.12, "Ks400", "Ks0"): dict(advancing=(0.0085, 0.0005), returning=(-0.0024, 0.0021),
                                       upwind=(-0.0021, 0.0007), downwind=(0.0018, 0.0017)),
          (0.10, "Ks0", "spalding"): dict(advancing=(-0.0072, 0.0005), returning=(0.0069, 0.0026),
                                          upwind=(0.0025, 0.0006)),
          (0.12, "Ks0", "spalding"): dict(advancing=(-0.0046, 0.0004), returning=(0.0043, 0.0022),
                                          upwind=(0.0038, 0.0008)),
          (0.10, "Ks400", "spalding"): dict(advancing=(0.0020, 0.0006)),
          (0.12, "Ks400", "spalding"): dict(advancing=(0.0039, 0.0005)),
          (0.10, "Ks100", "Ks0"): dict(advancing=(0.0011, 0.0004)),
          (0.12, "Ks100", "Ks0"): dict(advancing=(0.0009, 0.0005))}
# smooth (Spalding) rotor at lambda 0.10: sector contributions (rotor_review_check.py; gaps, net: UPDATE.md)
Q_SP010 = {"upwind": 0.0670, "advancing": 0.0216, "downwind": -0.0116, "returning": -0.0489, GAPS: -0.0110,
           WHOLE: 0.0170}
# a blade's streamwise force over theta [lo, hi), run a against Ks 0: change and 2u (%) (rotor_review_check.py)
Q_EDGE = ((0.10, 80, 100, "Ks400", 50.0, 1.3), (0.12, 80, 100, "Ks400", 47.7, 1.7),
          (0.10, 80, 100, "Ks100", 7.5, 1.6), (0.12, 80, 100, "Ks100", 3.7, 2.0),
          (0.10, 260, 280, "Ks400", 0.7, 3.8), (0.12, 260, 280, "Ks400", 1.9, 3.7),
          (0.10, 80, 100, "spalding", 20.3, 1.7), (0.10, 260, 280, "spalding", 15.4, 5.3))
# Ks 400 - Ks 0, whole rotor: pressure C_Q, viscous C_Q, C_x (on 2R) and its 2u (rotor_review_check.py)
Q_R1 = {0.10: (0.00543, -0.00033, 0.0128, 0.0079), 0.12: (0.00614, -0.00038, 0.0089, 0.0110)}

CHECKS = []


def check(kind, name, case, source, ref, value, tol=None, ok=None, note=""):
    """One row of the check file. ok defaults to |value - ref| <= tol."""
    d = None if ref is None or value is None else float(value) - float(ref)
    if ok is None:
        ok = d is not None and abs(d) <= tol
    CHECKS.append(dict(kind=kind, check=name, case=case, source=source, reference=ref, recomputed=value,
                       diff=d, tol=tol, ok=bool(ok), note=note))
    return bool(ok)


def sig6(x):
    """Rounding bound of a value printed with %.6g (the 15 Oct CSVs), plus floating-point slack."""
    x = abs(float(x))
    return 1e-15 if x == 0 else 0.5 * 10.0 ** (math.floor(math.log10(x)) - 5) * 1.001 + 1e-15


def short(sector):
    return sector.split(",")[0]


def col(q):
    """Sector-table column name: torque is a contribution to the rotor C_Q there."""
    return q.replace("CQ_blade", "CQ_contrib")


def case_name(lam, wall):
    """Folder name of a priorityE_rough.txt line (cfd/rotor2d/run_case.py case_name for these options)."""
    return f"A_rot_U23.0_lam{lam:.3f}_SST_medium{SUFFIX[wall]}_senseCCW_rev50a45"


def queue_cases():
    """(lambda, wall) of the eight lines of priorityE_rough.txt, checked against the expected set."""
    out = []
    for ln in QUEUE.read_text().splitlines():
        p = ln.split("#")[0].split()
        if not p:
            continue
        assert p[:3] == ["rot", "A", "23"] and p[4:6] == ["SST", "medium"], ln
        kv = dict(x.split("=", 1) for x in p[6:])
        assert kv["sense"] == "CCW" and kv["nrev"] == "50" and kv["navg"] == "45", ln
        wall = "spalding" if "ks" not in kv else f"Ks{int(float(kv['ks']))}"
        assert (kv.get("nutwf") == "kRough") == (wall == "Ks0"), ln      # Ks > 0 implies the rough wall function
        out.append((round(float(p[3]), 2), wall))
    assert sorted(out) == sorted((lam, w) for lam in LAMS for w in WALLS), out
    return out


def read_dat(path):
    """Rows (time, total xyz, pressure xyz, viscous xyz) of an OpenFOAM forces file; repeated times are
    dropped as rotor_analysis.py read_moment does. Returns the rows and the number dropped."""
    a = np.loadtxt(path, comments="#")
    _, idx = np.unique(a[:, 0], return_index=True)
    return a[np.sort(idx)], len(a) - len(idx)


def bin_window(t, T, nav, nr, i, nb=NB):
    """Instants (nav, nb) at which blade i (0-based) enters and leaves each bin in each revolution of the
    window: rotor_analysis.py phase_bins' rule (blade i is at azimuth 360 m / nb when
    theta_1 = 360 m / nb - 120 i, mod 360)."""
    rr = np.arange(nr - nav, nr)[:, None]
    start = np.mod(np.arange(nb) * 360.0 / nb - 120.0 * i, 360.0)[None, :] / 360.0 * T + rr * T
    return np.clip(start, t[0], t[-1]), np.clip(start + T / nb, t[0], t[-1])


def bin_means(t, y, ta, tb):
    """Time mean of y over [ta, tb]: cumulative trapezoid, interpolated (rotor_analysis.py phase_bins)."""
    cum = ra.cumint(t, y)
    return (np.interp(tb, t, cum) - np.interp(ta, t, cum)) / (tb - ta)


def rotate(c0, ph):
    """Point c0 (2,) turned counter-clockwise by the angles ph (rad): arrays x, y."""
    c, s = np.cos(ph), np.sin(ph)
    return c * c0[0] - s * c0[1], s * c0[0] + c * c0[1]


def blade_series(P, t, f, m, c0):
    """Per-sample coefficients of one blade. f, m: its force and moment rows; c0: the model-frame position at
    t = 0 of the point whose velocity defines the relative wind (and about which Cm_c is taken)."""
    U, q, dz, omz = P["Uinf"], P["qRef"], P["dz"], P["omegaZ"]
    kF, kM = 1.0 / (q * C_REF * dz), 1.0 / (q * C_REF ** 2 * dz)
    kQ = P["sense"] / P["dz"] / (P["qRef"] * P["Aref"] * P["R"])     # as rotor_analysis.py phase_bins
    cx, cy = rotate(c0, omz * t)                                     # the rotor turns by omegaZ t
    wx, wy = U + omz * cy, -omz * cx                                 # W = U e_x - omegaZ e_z x c
    wm = np.hypot(wx, wy)
    ex, ey = wx / wm, wy / wm                                        # drag direction
    nx, ny = -ey, ex                                                 # lift direction, 90 deg CCW from W
    fx, fy = f[:, 1], f[:, 2]
    drag = {k: f[:, 1 + 3 * j] * ex + f[:, 2 + 3 * j] * ey for j, k in enumerate(("tot", "p", "v"))}
    lift = fx * nx + fy * ny
    rxf = cx * fy - cy * fx                                          # (c x F)_z
    g = (U / wm) ** 2
    ser = dict(Cx=kF * fx, Cy=kF * fy, CL=kF * lift, CD=kF * drag["tot"], CQ_blade=kQ * m[:, 3],
               CQ_blade_p=kQ * m[:, 6], CQ_blade_v=kQ * m[:, 9], CD_p=kF * drag["p"], CD_v=kF * drag["v"],
               CL_W=kF * lift * g, CD_W=kF * drag["tot"] * g, Cm_c=kM * (m[:, 3] - rxf))
    return ser, rxf


def r2(y, yhat):
    return 1.0 - float(np.sum((y - yhat) ** 2) / np.sum((y - y.mean()) ** 2))


def mean_2u(x):
    """Mean over the revolutions (axis 0) and 2u = 2 s / sqrt(n)."""
    return x.mean(axis=0), 2.0 * x.std(axis=0, ddof=1) / math.sqrt(x.shape[0])


def blades_2u(xb):
    """Between-blade 2u of a three-blade mean: xb (3, nav, ...) per-blade revolution values."""
    return 2.0 * xb.mean(axis=1).std(axis=0, ddof=1) / math.sqrt(xb.shape[0])


def lag1(x):
    """Lag-1 autocorrelation of each column of x (n, ...), as rotor_analysis.py window_stats."""
    d = x - x.mean(axis=0)
    return np.sum(d[:-1] * d[1:], axis=0) / np.sum(d * d, axis=0)


# ---------------------------------------------------------------- one run
def analyse_case(lam, wall, geo):
    name = case_name(lam, wall)
    d = RUNS / name
    P = json.loads((d / "case.json").read_text())
    mi = json.loads((d / "mesh_info.json").read_text())
    rj = json.loads((d / "results.json").read_text())
    assert P["caseName"] == name and P["mode"] == "rotating" and P["hypothesis"] == "A", name
    assert abs(P["lam"] - lam) < 1e-12 and P["Uinf"] == 23.0 and P["sense"] == 1, name
    assert P["turbulenceModel"] == "kOmegaSST" and int(P["nRev"]) == 50 and int(P["nAvgRev"]) == 45, name
    assert abs(P.get("thetaDeg", 0.0)) < 1e-12 and abs(P["Aref"] - 2 * P["R"]) < 1e-12, name
    assert abs(P["qRef"] - 0.5 * P["rhoInf"] * P["Uinf"] ** 2) < 1e-9 * P["qRef"], name
    assert abs(P["omegaZ"] - P["sense"] * 2 * math.pi / P["Trev"]) < 1e-9 * abs(P["omegaZ"]), name
    assert P.get("nutWallFunction", WALL_FN["spalding"]) == WALL_FN[wall], name
    if wall != "spalding":
        assert abs(P["KsBlade"] * 1e6 - float(wall[2:])) < 1e-6, name
    assert mi["pose_full"] == geo["pose"], f"{name}: blade pose differs from the first run's"
    pp = d / "postProcessing"
    for fo in ("forcesBlade1", "forcesBlade2", "forcesBlade3", "forcesRotor"):
        dirs = sorted(x.name for x in (pp / fo).iterdir() if x.is_dir())
        assert dirs == ["0"], (name, fo, dirs)                      # no restarts, as read_moment
    fb, mb = zip(*[(read_dat(pp / f"forcesBlade{k}/0/force.dat"), read_dat(pp / f"forcesBlade{k}/0/moment.dat"))
                   for k in (1, 2, 3)])
    fr, mr = read_dat(pp / "forcesRotor/0/force.dat"), read_dat(pp / "forcesRotor/0/moment.dat")
    n_dup = sum(x[1] for x in fb + mb + (fr, mr))
    fb, mb, fr, mr = [x[0] for x in fb], [x[0] for x in mb], fr[0], mr[0]
    t = fb[0][:, 0]
    assert all(np.array_equal(a[:, 0], t) for a in fb + mb + [fr, mr]), name
    T, nav = P["Trev"], int(P["nAvgRev"])
    nr = int(round(t[-1] / T))
    assert abs(t[-1] / T - nr) < 1e-6 and nr == 50, (name, t[-1] / T)

    # file consistency: blades sum to the rotor; total = pressure + viscous
    s_f = max(float(np.max(np.abs(sum(a[:, c] for a in fb) - fr[:, c])) / np.max(np.abs(fr[:, c]))) for c in (1, 2))
    s_m = float(np.max(np.abs(sum(a[:, 3] for a in mb) - mr[:, 3])) / np.max(np.abs(mr[:, 3])))
    pv = max([float(np.max(np.abs(a[:, c] - a[:, c + 3] - a[:, c + 6])) / np.max(np.abs(a[:, c])))
              for a in fb for c in (1, 2)]
             + [float(np.max(np.abs(a[:, 3] - a[:, 6] - a[:, 9])) / np.max(np.abs(a[:, 3]))) for a in mb])

    X = {q: np.zeros((3, nav, NB)) for q in QUANTS}
    alt = {q: np.zeros((3, nav, NB)) for q in ("CL", "CD", "CL_W", "CD_W")}
    w = t >= t[-1] - nav * T                                           # the averaging window (lever check)
    lever = {}
    for i in range(3):
        ta, tb = bin_window(t, T, nav, nr, i)
        ser, rxf = blade_series(P, t, fb[i], mb[i], geo["c0"][i])
        for q in QUANTS:
            X[q][i] = bin_means(t, ser[q], ta, tb)
        ser_a, _ = blade_series(P, t, fb[i], mb[i], geo["att0"][i])   # relative wind at the attachment point
        for q in alt:
            alt[q][i] = bin_means(t, ser_a[q], ta, tb)
        # lever check: M_z against (r_c x F)_z with this azimuth convention and with blades 2 and 3 swapped
        _, rxf_sw = blade_series(P, t, fb[i], mb[i], geo["c0"][[0, 2, 1][i]])
        mz = mb[i][:, 3]
        lever[i + 1] = (r2(mz[w], rxf[w]), r2(mz[w], rxf_sw[w]))
    mid, pb = ra.phase_bins(name)                                      # the 15 Oct rule, for the reuse check
    return dict(name=name, P=P, rj=rj, X=X, alt=alt, lever=lever, pb=pb, mid=mid, n_dup=n_dup,
                sum_force=s_f, sum_moment=s_m, p_plus_v=pv, nav=nav)


# ---------------------------------------------------------------- geometry
def geometry():
    """Blade pose of the runs' mesh, centroid and attachment point of each blade at t = 0 (model frame),
    and the section body x axis (normal to the outer-tip chord, toward the convex side) of blade 1."""
    sec = rg.Section()
    mi = json.loads((RUNS / case_name(0.10, "Ks0") / "mesh_info.json").read_text())
    pose = mi["pose_full"]
    assert pose["name"] == "A" and pose["sense"] == 1 and abs(pose["R_m"] - 0.1016) < 1e-12
    c0 = np.array([rg.to_model(pose, sec.centroid, 0.0, k)[0] for k in (1, 2, 3)])
    att0 = np.array([rg.to_model(pose, np.array(pose["P_att_cad"]), 0.0, k)[0] for k in (1, 2, 3)])
    assert np.allclose(np.hypot(c0[:, 0], c0[:, 1]), pose["r_centroid_m"], atol=1e-12)
    assert np.allclose(np.hypot(att0[:, 0], att0[:, 1]), pose["R_m"], atol=1e-12)
    ch = sec.B_out - sec.A_out                                         # outer-tip chord, tip A -> tip B (CAD)
    xb_cad = np.array([ch[1], -ch[0]]) / np.linalg.norm(ch)            # chord turned -90 deg: toward the convex side
    Rm, _ = rg.blade_transform(pose, 0.0, 1)
    xb0 = Rm @ xb_cad
    # the section body frame of cfd/section2d/README.md: +x_body at -4.76 deg in CAD, centroid (17.620, 31.507) mm
    assert abs(math.degrees(math.atan2(xb_cad[1], xb_cad[0])) + 4.76) < 0.01
    assert np.allclose(sec.centroid * 1e3, [17.620, 31.507], atol=1e-3)
    delta = math.degrees(math.atan2(c0[0, 1], c0[0, 0])) % 360.0 - 180.0   # centroid ahead of blade 1's radial line
    return dict(pose=pose, c0=c0, att0=att0, xb0=xb0, r_c=float(np.hypot(*c0[0])), delta_deg=delta)


def bin_geometry(P, geo, mid):
    """|W|/U, the direction of W (deg from +x, counter-clockwise) and alpha_geo (section convention) for a
    blade at azimuth mid (blade 1's centroid turned by s theta)."""
    U, s, omz = P["Uinf"], P["sense"], P["omegaZ"]
    ph = s * np.radians(mid)
    cx, cy = rotate(geo["c0"][0], ph)
    wx, wy = U + omz * cy, -omz * cx
    ang = np.degrees(np.arctan2(wy, wx))
    body = np.degrees(np.arctan2(geo["xb0"][1], geo["xb0"][0]) + ph)
    return np.hypot(wx, wy) / U, ang, np.mod(ang - body, 360.0)


# ---------------------------------------------------------------- figures
def shade(ax):
    for _, lo, hi in ra.SECTORS:
        for a, b in (((lo, 360), (0, hi)) if lo > hi else ((lo, hi),)):
            ax.axvspan(a, b, color="#f1f1f1", lw=0, zorder=0)


def wrap(mid, *ys):
    """Bin centres extended by one bin each side (periodic), so lines run from 0 to 360 deg."""
    x = np.concatenate([[mid[-1] - 360.0], mid, [mid[0] + 360.0]])
    return (x,) + tuple(np.concatenate([[y[-1]], y, [y[0]]]) for y in ys)


def label_sectors(ax):
    tr = ax.get_xaxis_transform()
    for lab, lo, hi in ra.SECTORS:
        s = short(lab)
        for x in ((345, 15) if lo > hi else (0.5 * (lo + hi),)):
            ax.text(x, 0.985, s, transform=tr, fontsize=6.0, ha="center", va="top", color="#555555")


ROWS = (("CQ_blade", r"one blade's $C_Q$ (–)", "torque of one blade"),
        ("CL", r"lift $C_L$ (–)", "lift, normal to the relative wind"),
        ("CD", r"drag $C_D$ (–)", "drag, along the relative wind"))


def frame(fig, axs, title_fmt):
    """Shared axes furniture of both figures."""
    for c, lam in enumerate(LAMS):
        for r, (q, ylab, ttl) in enumerate(ROWS):
            ax = axs[r, c]
            ax.axhline(0, color="#333333", lw=0.6)
            ax.set_xlim(0, 360)
            ax.set_xticks(range(0, 361, 60))
            ax.set_title(f"({'abcdef'[2 * r + c]}) " + title_fmt.format(ttl) + rf", $\lambda$ {lam:.2f}",
                         loc="left", fontsize=8.2)
            if c == 0:
                ax.set_ylabel(ylab if "change" not in title_fmt else r"$\Delta$ " + ylab)
            if r == 2:
                ax.set_xlabel(r"blade azimuth $\theta$ (deg)")
    for r in range(3):                                   # head room for the sector names in the top row
        lo, hi = axs[r, 0].get_ylim()
        axs[r, 0].set_ylim(lo, hi + (0.22 if r == 0 else 0.0) * (hi - lo))
    for c in range(2):
        label_sectors(axs[0, c])


def fig_values(S, mid):
    fig, axs = plt.subplots(3, 2, figsize=(7.2, 7.9), sharex=True, sharey="row")
    for c, lam in enumerate(LAMS):
        for r, (q, _, _) in enumerate(ROWS):
            ax = axs[r, c]
            shade(ax)
            for wl, lw in (("Ks0", 1.1), ("Ks400", 1.3)):
                m, u2 = S[(lam, wl)][q]
                x, y, e = wrap(mid, m, u2)
                ax.fill_between(x, y - e, y + e, color=ra.C_WALL[wl], alpha=0.25, lw=0)
                ax.plot(x, y, "-", color=ra.C_WALL[wl], lw=lw)
    frame(fig, axs, "{}")
    h = [Line2D([], [], color=ra.C_WALL["Ks0"], lw=1.1), Line2D([], [], color=ra.C_WALL["Ks400"], lw=1.3),
         Patch(color="#9a9a9a", alpha=0.35, lw=0)]
    fig.legend(h, ["Ks 0 (rough wall function, smooth)", "Ks 400 µm", "±2u, revolution-to-revolution scatter"],
               loc="lower center", ncol=3, fontsize=6.8, handlelength=1.8, bbox_to_anchor=(0.5, 0.045))
    fig.text(0.01, 0.003, r"$\theta$ 0 = upwind (convex side to the wind), 90 = advancing edge-on (moving "
             "downwind), 180 = cup to the wind, 270 = returning edge-on. Three-blade mean, 45 revolutions, "
             "10° bins.\nForces per unit span on the free-stream "
             r"$\frac{1}{2}\rho U^2$ and $c_{ref}$ 48 mm; lift and drag about the geometric relative wind at the "
             "blade centroid (no induction). Torque on the rotor scale:\nthe three blades sum to the rotor "
             r"$C_Q$. Shaded: the 15 Oct sectors. 2D URANS, SST, medium mesh, 23 m/s, maxCo 4 (computed; one "
             "mesh, one time step).", fontsize=5.9, color="#444444", va="bottom")
    fig.subplots_adjust(hspace=0.34, wspace=0.08, bottom=0.135)
    fig.savefig(FIG / "rotor_phase_force.png")
    plt.close(fig)


def fig_diffs(D, mid):
    fig, axs = plt.subplots(3, 2, figsize=(7.2, 7.9), sharex=True, sharey="row")
    vis = {"CQ_blade": "CQ_blade_v", "CL": None, "CD": "CD_v"}
    for c, lam in enumerate(LAMS):
        for r, (q, _, _) in enumerate(ROWS):
            ax = axs[r, c]
            shade(ax)
            for (a, b), colr, ls, alpha in ((("Ks400", "Ks0"), ra.RAMP[400], "-", 0.22),
                                            (("Ks100", "Ks0"), ra.RAMP[100], "--", 0.18)):
                d, u2 = D[(lam, a, b)][q][:2]
                x, y, e = wrap(mid, d, u2)
                ax.fill_between(x, y - e, y + e, color=colr, alpha=alpha, lw=0)
                ax.plot(x, y, ls, color=colr, lw=1.2)
            if vis[q]:
                x, y = wrap(mid, D[(lam, "Ks400", "Ks0")][vis[q]][0])
                ax.plot(x, y, ":", color=ra.RAMP[400], lw=1.0)
    frame(fig, axs, "change of {}")
    h = [Line2D([], [], color=ra.RAMP[400], lw=1.2), Line2D([], [], color=ra.RAMP[100], lw=1.2, ls="--"),
         Line2D([], [], color=ra.RAMP[400], lw=1.0, ls=":"), Patch(color=ra.RAMP[400], alpha=0.3, lw=0)]
    fig.legend(h, ["Ks 400 µm − Ks 0", "Ks 100 µm − Ks 0", "Ks 400 µm − Ks 0, viscous part",
                   "±2u of each difference (revolution scatter)"], loc="lower center", ncol=4, fontsize=6.8,
               handlelength=1.8, bbox_to_anchor=(0.5, 0.045))
    fig.text(0.01, 0.003, r"$\theta$ 0 = upwind, 90 = advancing edge-on, 180 = cup to the wind, 270 = returning "
             "edge-on. Three-blade mean, 45 revolutions per run, 10° bins; the same wall function "
             "(nutkRoughWallFunction) in every run.\nA change is resolved where its band clears zero. 2u covers "
             "the revolution scatter only, not the mesh, the time step or the turbulence model. Single blades "
             "differ from one another\nby more than 2u in about a third of the bin comparisons (between-blade 2u: "
             "CSV columns *_2u_blades). Computed; one mesh, one time step.", fontsize=5.9, color="#444444",
             va="bottom")
    fig.subplots_adjust(hspace=0.34, wspace=0.08, bottom=0.135)
    fig.savefig(FIG / "rotor_phase_force_diff.png")
    plt.close(fig)


# ---------------------------------------------------------------- main
def main():
    ra.style()
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    cases = queue_cases()
    geo = geometry()
    R = {(lam, wl): analyse_case(lam, wl, geo) for lam, wl in cases}
    names = {k: v["name"] for k, v in R.items()}
    nav = R[(0.10, "Ks0")]["nav"]
    edges = np.linspace(0.0, 360.0, NB + 1)
    lo_e, hi_e, mid = edges[:-1], edges[1:], 0.5 * (edges[1:] + edges[:-1])
    assert all(np.allclose(r["mid"], mid) for r in R.values())

    # ---------------- per-run, per-blade and three-blade-mean tables
    Y = {}                                   # (lam, wall, blade) -> {q: (nav, NB)}
    for (lam, wl), r in R.items():
        for b in ("1", "2", "3", "mean"):
            Y[(lam, wl, b)] = {q: (r["X"][q][int(b) - 1] if b != "mean" else r["X"][q].mean(axis=0)) for q in QUANTS}
    B2U = {(lam, wl): {q: blades_2u(r["X"][q]) for q in QUANTS} for (lam, wl), r in R.items()}
    rows = []
    for (lam, wl), r in R.items():
        W_U, ang, alpha = bin_geometry(r["P"], geo, mid)
        for b in ("1", "2", "3", "mean"):
            st = {q: mean_2u(Y[(lam, wl, b)][q]) for q in QUANTS}
            for j in range(NB):
                row = dict(lam=lam, wall=wl, Ks_um=(np.nan if wl == "spalding" else float(wl[2:])),
                           wall_function=WALL_FN[wl], case=r["name"], blade=b, theta_lo_deg=lo_e[j],
                           theta_hi_deg=hi_e[j], theta_mid_deg=mid[j], n_rev=nav, W_over_U=W_U[j],
                           wind_angle_deg=ang[j], alpha_geo_deg=alpha[j])
                for q in QUANTS:
                    row[q], row[q + "_2u"] = st[q][0][j], st[q][1][j]
                for q in QUANTS:
                    row[q + "_2u_blades"] = B2U[(lam, wl)][q][j] if b == "mean" else np.nan
                rows.append(row)
    pd.DataFrame(rows).to_csv(OUT / "rotor_phase_force.csv", index=False, float_format="%.6g")

    drows, D = [], {}
    for lam in LAMS:
        for a, b in PAIRS:
            for bl in ("1", "2", "3", "mean"):
                st = {}
                for q in QUANTS:
                    ma, ua = mean_2u(Y[(lam, a, bl)][q])
                    mb_, ub = mean_2u(Y[(lam, b, bl)][q])
                    ubl = np.hypot(B2U[(lam, a)][q], B2U[(lam, b)][q]) if bl == "mean" else np.full(NB, np.nan)
                    st[q] = (ma - mb_, np.hypot(ua, ub), ubl)
                if bl == "mean":
                    D[(lam, a, b)] = st
                for j in range(NB):
                    row = dict(lam=lam, a=a, b=b, case_a=names[(lam, a)], case_b=names[(lam, b)], blade=bl,
                               theta_lo_deg=lo_e[j], theta_hi_deg=hi_e[j], theta_mid_deg=mid[j], n_rev=nav)
                    for q in QUANTS:
                        row["d" + q], row["d" + q + "_2u"] = st[q][0][j], st[q][1][j]
                    for q in QUANTS:
                        row["d" + q + "_2u_blades"] = st[q][2][j]
                    drows.append(row)
    pd.DataFrame(drows).to_csv(OUT / "rotor_phase_force_diff.csv", index=False, float_format="%.6g")

    # ---------------- sectors: torque contributions and force means, per revolution
    snames = [s[0] for s in ra.SECTORS] + [GAPS, WHOLE]
    masks = [ra.sector_mask(mid, lo, hi) for _, lo, hi in ra.SECTORS]
    masks += [~np.any(masks, axis=0), np.ones(NB, bool)]

    def sector_rev(y, msk):
        return {q: (3.0 * y[q][..., msk].sum(axis=-1) / NB if q in TORQUE else y[q][..., msk].mean(axis=-1))
                for q in QUANTS}

    SR, SB = {}, {}             # three-blade mean (nav,) and per blade (3, nav), per (lam, wall, sector)
    for (lam, wl), r in R.items():
        for nm, msk in zip(snames, masks):
            SR[(lam, wl, nm)] = sector_rev(Y[(lam, wl, "mean")], msk)
            SB[(lam, wl, nm)] = sector_rev(r["X"], msk)
    srows, SD = [], {}
    for lam in LAMS:
        for wl in WALLS:
            for nm in snames:
                row = dict(kind="run", lam=lam, a=wl, b="", case_a=names[(lam, wl)], case_b="", sector=nm,
                           theta_deg=SECT_RANGE[short(nm)], n_rev=nav)
                for q in QUANTS:
                    row[col(q)], row[col(q) + "_2u"] = mean_2u(SR[(lam, wl, nm)][q])
                for q in QUANTS:
                    row[col(q) + "_2u_blades"] = blades_2u(SB[(lam, wl, nm)][q])
                srows.append(row)
        for a, b in PAIRS_15OCT:
            for nm in snames:
                row = dict(kind="difference", lam=lam, a=a, b=b, case_a=names[(lam, a)], case_b=names[(lam, b)],
                           sector=nm, theta_deg=SECT_RANGE[short(nm)], n_rev=nav)
                for q in QUANTS:
                    ma, ua = mean_2u(SR[(lam, a, nm)][q])
                    mb_, ub = mean_2u(SR[(lam, b, nm)][q])
                    ubl = math.hypot(blades_2u(SB[(lam, a, nm)][q]), blades_2u(SB[(lam, b, nm)][q]))
                    SD[(lam, a, b, nm, q)] = (ma - mb_, math.hypot(ua, ub), ubl)
                    row[col(q)], row[col(q) + "_2u"] = SD[(lam, a, b, nm, q)][:2]
                for q in QUANTS:
                    row[col(q) + "_2u_blades"] = SD[(lam, a, b, nm, q)][2]
                srows.append(row)
    pd.DataFrame(srows).to_csv(OUT / "rotor_phase_force_sectors.csv", index=False, float_format="%.6g")

    # ================================================================ checks
    V, G, C = "validation", "diagnostic", "context"
    # (1) reuse of phase_bins: same rule, same data
    for k, r in R.items():
        dmax = float(np.max(np.abs(r["X"]["CQ_blade"].mean(axis=0) - r["pb"])))
        check(V, "binning = rotor_analysis.py phase_bins (max abs, three-blade C_Q)", r["name"],
              "cfd/analysis/2026-10-15/src/rotor_analysis.py phase_bins", 0.0, dmax, 1e-12)
    # (2) file consistency
    for k, r in R.items():
        check(V, "blades sum to the rotor: force x, y (max rel.)", r["name"], "forcesBlade1..3, forcesRotor force.dat",
              0.0, r["sum_force"], 1e-6)
        check(V, "blades sum to the rotor: moment z (max rel.)", r["name"], "forcesBlade1..3, forcesRotor moment.dat",
              0.0, r["sum_moment"], 1e-6)
        check(V, "total = pressure + viscous (max rel., blades)", r["name"], "forcesBlade1..3 force.dat, moment.dat",
              0.0, r["p_plus_v"], 1e-7, note=f"repeated times dropped: {r['n_dup']}")
    # (3) rotor_roughness_phase.csv (15 Oct): blade torque by azimuth and its u, to 6 significant digits
    ph = pd.read_csv(OCT15 / "out/rotor_roughness_phase.csv")
    for (lam, wl), r in R.items():
        g = ph[np.isclose(ph.lam, lam) & (ph.wall == wl)].sort_values("theta_mid_deg")
        assert len(g) == NB and np.allclose(g.theta_mid_deg.to_numpy(float), mid)
        m, u2 = mean_2u(Y[(lam, wl, "mean")]["CQ_blade"])
        ref, refu = g.CQ_single_blade.to_numpy(float), g.u.to_numpy(float)
        dm, du = np.abs(m - ref), np.abs(u2 / 2 - refu)
        ok_m = bool(np.all(dm <= np.array([sig6(x) for x in ref])))
        ok_u = bool(np.all(du <= np.array([sig6(x) for x in refu])))
        j = int(np.argmax(dm))
        check(V, "blade C_Q by azimuth = rotor_roughness_phase.csv (worst bin; all 36 to 6 s.f.)", r["name"],
              "cfd/analysis/2026-10-15/out/rotor_roughness_phase.csv", ref[j], m[j], sig6(ref[j]), ok=ok_m,
              note=f"max |diff|/(2u) over bins {float(np.max(dm / (2 * refu))):.2g}")
        j = int(np.argmax(du))
        check(V, "u of blade C_Q by azimuth = rotor_roughness_phase.csv (worst bin; all 36 to 6 s.f.)", r["name"],
              "cfd/analysis/2026-10-15/out/rotor_roughness_phase.csv", refu[j], u2[j] / 2, sig6(refu[j]), ok=ok_u)
    # (4) rotor_roughness_sectors.csv (15 Oct): every row's d and 2u, and the contributions
    sc = pd.read_csv(OCT15 / "out/rotor_roughness_sectors.csv")
    assert len(sc) == 50
    worst = 0.0
    for _, s in sc.iterrows():
        lam = 0.10 if abs(s.lam - 0.1) < 1e-9 else 0.12
        d, u2, _ = SD[(lam, s.a, s.b, s.sector, "CQ_blade")]
        pair = f"lambda {lam:.2f} {s.a} - {s.b}, {short(s.sector)}"
        check(V, "sector change of rotor C_Q = rotor_roughness_sectors.csv d", pair,
              "cfd/analysis/2026-10-15/out/rotor_roughness_sectors.csv", s.d, d, sig6(s.d),
              note=f"|diff|/(2u) {abs(d - s.d) / s.two_u:.2g}; resolved here {abs(d) > u2}, there {s.resolved_2u}")
        check(V, "sector change 2u = rotor_roughness_sectors.csv two_u", pair,
              "cfd/analysis/2026-10-15/out/rotor_roughness_sectors.csv", s.two_u, u2, sig6(s.two_u))
        for c_, wl in (("contrib_a", s.a), ("contrib_b", s.b)):
            v = float(mean_2u(SR[(lam, wl, s.sector)]["CQ_blade"])[0])
            worst = max(worst, abs(v - s[c_]) / sig6(s[c_]))
    check(V, "sector contributions contrib_a, contrib_b (worst |diff| / 6-s.f. bound, all 100)", "all",
          "cfd/analysis/2026-10-15/out/rotor_roughness_sectors.csv", 0.0, worst, 1.0)
    # (5) quoted 15 Oct numbers (rounded): sector changes, Spalding budget
    for (lam, a, b), dd in Q_SECT.items():
        for sname, (dq, tq) in dd.items():
            full = [s for s in snames if short(s) == sname][0]
            d, u2, ub = SD[(lam, a, b, full, "CQ_blade")]
            check(V, f"sector change of rotor C_Q, {sname}", f"lambda {lam:.2f} {a} - {b}", SRC_RC, dq, d, 6e-5,
                  note=f"within quoted 2u {abs(d - dq) <= tq}; between-blade 2u {ub:.4f}")
            check(V, f"sector change 2u, {sname}", f"lambda {lam:.2f} {a} - {b}", SRC_RC, tq, u2, 6e-5)
    for sname, v in Q_SP010.items():
        full = [s for s in snames if short(s) == sname or s == sname][0]
        m, u2 = mean_2u(SR[(0.10, "spalding", full)]["CQ_blade"])
        check(V, f"Spalding rotor sector contribution, {sname}", names[(0.10, "spalding")],
              SRC_UP if sname in (GAPS, WHOLE) else SRC_RC, v, float(m), 6e-5, note=f"2u {float(u2):.2g}")
    # (6) a blade's streamwise force over theta 80-100 and 260-280 deg against Ks 0 (%), incl. 7.5 +- 1.6 % at Ks 100
    for lam, lo, hi, a, rel, tq in Q_EDGE:
        msk = (mid > lo) & (mid < hi)
        x = Y[(lam, a, "mean")]["Cx"][:, msk].mean(axis=1)
        y = Y[(lam, "Ks0", "mean")]["Cx"][:, msk].mean(axis=1)
        (mx, ux), (my, uy) = mean_2u(x), mean_2u(y)
        v, tu = 100 * (mx / my - 1), 100 * math.hypot(ux, uy) / my
        xb = R[(lam, a)]["X"]["Cx"][:, :, msk].mean(axis=2)
        yb = R[(lam, "Ks0")]["X"]["Cx"][:, :, msk].mean(axis=2)
        tb = 100 * math.hypot(blades_2u(xb), blades_2u(yb)) / my
        case = f"lambda {lam:.2f} {a} vs Ks0, theta {lo}-{hi}"
        check(V, "blade streamwise force change (%)", case, SRC_RC, rel, v, 0.06,
              note=f"within quoted 2u {abs(v - rel) <= tq}; between-blade 2u {tb:.1f} %")
        check(V, "  its 2u (%)", case, SRC_RC, tq, tu, 0.06)
    # (7) Ks 400 - Ks 0, whole rotor: pressure / viscous torque, C_x on 2R
    for lam, (dp, dv, dcx, tcx) in Q_R1.items():
        k = 3 * C_REF / (2 * R[(lam, "Ks0")]["P"]["R"])
        (ma, ua), (mb_, ub) = mean_2u(k * SR[(lam, "Ks400", WHOLE)]["Cx"]), mean_2u(k * SR[(lam, "Ks0", WHOLE)]["Cx"])
        c_ = f"lambda {lam:.2f} Ks400 - Ks0"
        check(V, "rotor dC_Q, pressure part", c_, SRC_RC, dp, SD[(lam, "Ks400", "Ks0", WHOLE, "CQ_blade_p")][0], 6e-6)
        check(V, "rotor dC_Q, viscous part", c_, SRC_RC, dv, SD[(lam, "Ks400", "Ks0", WHOLE, "CQ_blade_v")][0], 6e-6)
        check(V, "rotor dC_x (on 2R)", c_, SRC_RC, dcx, ma - mb_, 6e-5)
        check(V, "  its 2u", c_, SRC_RC, tcx, math.hypot(ua, ub), 6e-5)
    # (8) window means against the tables (within 2u), and the 15 Oct phase-sum check
    cp = pd.read_csv(ROTOR_CP).set_index("name")
    psum = 0.0
    for (lam, wl), r in R.items():
        t_ = cp.loc[r["name"]]
        for q, c_, scale in (("CQ_blade", "CQ_mean", 3.0), ("CQ_blade_p", "CQ_pressure_mean", 3.0),
                             ("Cx", "Cx_mean", 3.0 * C_REF / (2 * r["P"]["R"]))):
            m, u2 = mean_2u(scale * Y[(lam, wl, "mean")][q].mean(axis=1))
            check(V, f"window mean {c_} = rotor_cp.csv (within 2u)", r["name"], "cfd/rotor2d/results/rotor_cp.csv",
                  float(t_[c_]), float(m), float(u2), note="table: trapezoid over the samples after the window start")
        psum = max(psum, abs(3 * float(r["pb"].mean()) - float(t_["CQ_mean"])))
        for i in range(3):
            m, u2 = mean_2u(Y[(lam, wl, str(i + 1))]["CQ_blade"].mean(axis=1))
            check(V, f"blade {i + 1} window-mean C_Q = results.json CQ_blade_mean (within 2u)", r["name"],
                  f"cfd/rotor2d/runs/{r['name']}/results.json", r["rj"]["CQ_blade_mean"][i], float(m), float(u2))
    n15 = json.loads((OCT15 / "out/rotor_numbers.json").read_text())
    check(V, "3 x mean of phase bins - table C_Q (max abs over the 8 runs)", "all",
          "cfd/analysis/2026-10-15/out/rotor_numbers.json roughness.phase_sum_vs_table_max_abs",
          n15["roughness"]["phase_sum_vs_table_max_abs"], psum, sig6(n15["roughness"]["phase_sum_vs_table_max_abs"]))
    for key, v in n15["physics_link"]["computed_dCQ_single_blade_minus_Ks0"].items():
        ks, lam = key.split("_lam")
        d = D[(float(lam), ks, "Ks0")]["CQ_blade"][0]
        for th in (85, 95):
            j = int(np.argmin(np.abs(mid - th)))
            check(V, f"single-blade dC_Q at theta {th}", f"lambda {lam} {ks} - Ks0",
                  "cfd/analysis/2026-10-15/out/rotor_numbers.json physics_link", v[f"theta_{th}"], float(d[j]),
                  sig6(v[f"theta_{th}"]))
    # (9) lever check: the azimuth convention (blade k at theta_1 + 120 (k - 1)) against blades 2 and 3 swapped
    for (lam, wl), r in R.items():
        for k in (2, 3):
            conv, sw = r["lever"][k]
            check(V, f"lever check, blade {k}: R^2 of M_z on (r_c x F)_z, convention > swapped", r["name"],
                  "cfd/rotor2d/README.md azimuth convention", sw, conv, ok=conv > sw)
        check(G, "lever check, blade 1: R^2 of M_z on (r_c x F)_z", r["name"], "", None, r["lever"][1][0],
              ok=True, note="the rest of M_z is the moment about the centroid, Cm_c")

    # ---------------- diagnostics
    # blade-to-blade: paired differences per revolution, |mean| > 2u in a share of the 36 x 3 tests per run
    for q in QUANTS:
        hits, pats, ratio = [], [], []
        for (lam, wl), r in R.items():
            for i, j in ((1, 2), (1, 3), (2, 3)):
                m, u2 = mean_2u(Y[(lam, wl, str(i))][q] - Y[(lam, wl, str(j))][q])
                hits.append(np.abs(m) > u2)
            bm = r["X"][q].mean(axis=1)
            pats.append((bm - bm.mean(axis=0)).ravel())
            ratio.append(B2U[(lam, wl)][q] / mean_2u(Y[(lam, wl, "mean")][q])[1])
        cc = np.corrcoef(np.array(pats))[np.triu_indices(len(pats), 1)]
        frac = float(np.mean(np.concatenate(hits)))
        check(G, f"blade-to-blade: share of (bin, blade pair) differences beyond 2u, {q}", "all 8 runs", "", 0.05,
              frac, ok=frac <= 0.10,
              note=f"about 0.05 if the blades were statistically identical (flag above 0.10); between-blade 2u / 2u "
                   f"of the three-blade mean, median {np.median(np.concatenate(ratio)):.2f}; correlation of the "
                   f"blade-deviation patterns between runs, median {np.median(cc):.2f}")
    # revolution independence (the 2u rule assumes it): lag-1 autocorrelation and 9 x 5 batch means
    r1s, ratios = [], []
    for (lam, wl) in R:
        for q in QUANTS:
            x = Y[(lam, wl, "mean")][q]
            r1s.append(lag1(x))
            ub = x.reshape(9, 5, NB).mean(axis=1).std(axis=0, ddof=1) / 3.0
            ratios.append(ub / (x.std(axis=0, ddof=1) / math.sqrt(x.shape[0])))
    r1s, ratios = np.concatenate(r1s), np.concatenate(ratios)
    check(G, "lag-1 autocorrelation of revolution values (three-blade mean), median over runs, quantities, bins",
          "all 8 runs", "", 0.0, float(np.median(r1s)), 1.96 / math.sqrt(nav),
          note=f"5th-95th percentile {np.percentile(r1s, 5):.3f} to {np.percentile(r1s, 95):.3f}; "
               f"tolerance 1.96/sqrt(45)")
    check(G, "batch-means u (9 x 5) / revolution u (three-blade mean), median", "all 8 runs", "", 1.0,
          float(np.median(ratios)), 0.25,
          note=f"95th percentile {np.percentile(ratios, 95):.3f}; above 1 means the 2u here is optimistic")
    # reference radius: centroid (used) against the attachment point R 101.6 mm, three-blade mean
    for q in ("CL", "CD", "CL_W", "CD_W"):
        v = max(float(np.max(np.abs(Y[(lam, wl, "mean")][q].mean(axis=0) - R[(lam, wl)]["alt"][q].mean(axis=(0, 1)))))
                for lam, wl in R)
        check(G, f"radius sensitivity: max |{q}(centroid) - {q}(attachment point)| over bins and runs", "all 8 runs",
              "", 0.0, v, ok=True)
    worst_ratio = 0.0
    for lam in LAMS:
        for a, b in PAIRS:
            for q in ("CL", "CD"):
                d_c, u2 = D[(lam, a, b)][q][:2]
                d_r = R[(lam, a)]["alt"][q].mean(axis=(0, 1)) - R[(lam, b)]["alt"][q].mean(axis=(0, 1))
                worst_ratio = max(worst_ratio, float(np.max(np.abs(d_c - d_r) / u2)))
    check(G, "radius sensitivity of the rough - Ks 0 lift and drag changes: max |change| / 2u over bins",
          "all pairs", "", 0.0, worst_ratio, 1.0)
    # context: the advancing blade near edge-on against the static section at alpha 90 (Stage 2, same wall function)
    s2 = n15["physics_link"]["stage2_wall_function_maxCo2p5"]
    j = int(np.argmin(np.abs(mid - 95)))
    for lam in LAMS:
        alpha_j = bin_geometry(R[(lam, "Ks0")]["P"], geo, mid)[2][j]
        for ks in (400, 100):
            for q, sq in (("CD_W", "Cd"), ("CL_W", "Cl")):
                ref = s2[f"a90_Ks{ks}"][sq] - s2["a90_Ks0"][sq]
                d, u2, ub = (float(v[j]) for v in D[(lam, f"Ks{ks}", "Ks0")][q])
                base, sbase = float(mean_2u(Y[(lam, "Ks0", "mean")][q])[0][j]), s2["a90_Ks0"][sq]
                rel = (f"; relative: rotor {100 * d / base:+.1f} %, section {100 * ref / sbase:+.1f} %"
                       if base > 0 and sbase > 0 else "")
                check(C, f"Ks {ks} - Ks 0, rotor {q} at theta 90-100 against section {sq} at alpha 90",
                      f"lambda {lam:.2f}", "cfd/analysis/2026-10-15/out/rotor_numbers.json physics_link "
                      "(cfd/stage2/results/stage2_polars.csv)", ref, d, ok=True,
                      note=f"rotor 2u {u2:.4f} (between-blade {ub:.4f}); Ks 0 level: rotor {base:+.4f}, section "
                           f"{sbase:+.4f}{rel}; alpha_geo of the bin {alpha_j:.1f}; quasi-steady, geometric wind")
    W_U, ang, alpha = {}, {}, {}
    for lam in LAMS:
        W_U[lam], ang[lam], alpha[lam] = bin_geometry(R[(lam, "Ks0")]["P"], geo, np.linspace(0, 360, 3601))
    chk = pd.DataFrame(CHECKS)
    chk.to_csv(OUT / "rotor_phase_force_check.csv", index=False, float_format="%.6g")

    # ---------------- figures
    S = {(lam, wl): {q: mean_2u(Y[(lam, wl, "mean")][q]) for q in QUANTS} for lam in LAMS for wl in WALLS}
    fig_values(S, mid)
    fig_diffs(D, mid)

    # ---------------- console summary
    print(f"geometry: r_c {geo['r_c'] * 1e3:.2f} mm, {geo['delta_deg']:.2f} deg ahead of the attachment line")
    for lam in LAMS:
        print(f"lambda {lam:.2f}: |W|/U {W_U[lam].min():.4f}-{W_U[lam].max():.4f}, W within "
              f"{np.max(np.abs(ang[lam])):.2f} deg of +x; alpha_geo at theta 0/90/180/270: "
              + ", ".join(f"{alpha[lam][int(10 * th)]:.1f}" for th in (0, 90, 180, 270)))
    nv, nf = int((chk.kind == V).sum()), int(((chk.kind == V) & ~chk.ok).sum())
    print(f"checks: {nv} validation, {nf} failed; {int((chk.kind == G).sum())} diagnostic, "
          f"{int(((chk.kind == G) & ~chk.ok).sum())} flagged; {int((chk.kind == C).sum())} context")
    for _, c in chk[(chk.kind == V) & ~chk.ok].iterrows():
        print("  FAILED:", c.check, c.case, c.reference, c.recomputed, c.note)
    for _, c in chk[chk.kind != V].iterrows():
        print(f"  {c.kind[:4]} {'' if c.ok else 'FLAG '}{c.check} [{c.case}]: {c.recomputed:.4g} (ref {c.reference}) "
              f"{c.note}")
    lev = [R[k]["lever"][b] for k in R for b in (1, 2, 3)]
    sw = [x[1] for i, x in enumerate(lev) if i % 3]
    print(f"lever R^2: convention {min(x[0] for x in lev):.4f}-{max(x[0] for x in lev):.4f}, blades 2/3 swapped "
          f"{min(sw):.2f} to {max(sw):.2f}")
    for lam in LAMS:
        for a, b in PAIRS:
            for nm in snames:
                parts = []
                for q in ("CQ_blade", "CQ_blade_p", "CQ_blade_v", "CD", "CD_p", "CD_v", "CL", "Cm_c"):
                    d, u2, ub = SD[(lam, a, b, nm, q)]
                    parts.append(f"{q} {d:+.4f}±{u2:.4f}[{ub:.4f}]")
                print(f"{lam:.2f} {a}-{b} {short(nm)[:10]:10s}", "; ".join(parts))
            for q in ("CQ_blade", "CL", "CD"):
                d, u2, ub = D[(lam, a, b)][q]
                res, resb = np.abs(d) > u2, np.abs(d) > np.hypot(u2, ub)
                print(f"   bins resolved {q}: {int(res.sum())}/36 (with the between-blade 2u added: {int(resb.sum())}) "
                      "at theta", ",".join(f"{m:g}" for m in mid[res]))
    for lam in LAMS:
        for wl in ("Ks0", "Ks100", "Ks400"):
            for nm in snames[:4]:
                m = {q: float(mean_2u(SR[(lam, wl, nm)][q])[0]) for q in ("CD", "CD_p", "CD_v", "CL", "CQ_blade")}
                print(f"{lam:.2f} {wl:6s} {short(nm):10s} CD {m['CD']:.4f} (p {m['CD_p']:.4f}, v {m['CD_v']:.4f}) "
                      f"CL {m['CL']:+.4f} CQ contrib {m['CQ_blade']:+.4f}")
    if nf:
        sys.exit(1)


if __name__ == "__main__":
    main()
