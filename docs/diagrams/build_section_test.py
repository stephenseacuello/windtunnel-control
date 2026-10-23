#!/usr/bin/env python3
"""
build_section_test.py — numbers and figures for docs/12_section_force_test.md.

    python3 docs/diagrams/build_section_test.py

Needs numpy, scipy, pandas and matplotlib (the CFD analysis interpreter has
them; the rig itself does not need them). Reads, read only:

    data/tunnel.json                                       fan rpm -> m/s
    cfd/geometry/section_v1.json, section_v1.csv           blade section (STL)
    cfd/measurements/blade_section_cad.json                mounting holes
    cfd/section2d/results/section_polars.csv               smooth-section CFD
    cfd/analysis/2026-10-15/out/section_case_quality.csv   health flag, alpha-0 state
    cfd/analysis/2026-10-15/out/roughness_wf_effects.csv   rough-wall CFD changes

Writes into docs/diagrams/:

    section_test_numbers.json      every number the document quotes
    section_test_concept.png       mounting, balance, alpha and lift convention
    section_test_loads.png         expected drag and lift against wind speed
    section_test_frequencies.png   shedding frequencies against structural modes

Nothing here is a measurement of the section test: it has not been built.
Inputs that are design choices or assumptions are the constants below, each
labelled; the document repeats the labels.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Circle, Polygon, Rectangle  # noqa: E402
from scipy.interpolate import BSpline  # noqa: E402
from scipy.stats import t as student_t  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

# URI palette, as docs/diagrams/build_diagrams.py
NAVY, KEANEY, PALE = "#002147", "#2277b3", "#c0ddf2"
GOLD, GOLDDK = "#b5985a", "#8a7038"
INK, DIM, LINE, WASH = "#0d2338", "#5b7288", "#d3e0eb", "#f5f8fb"
OK, FAULT = "#1f7a52", "#b3261e"

G0 = 9.80665                 # m/s2, standard gravity

# ── design choices (proposed) ───────────────────────────────────────────────
C_REF = 0.048                # m, the CFD reference chord (cfd/section2d/README.md)
SLEEVE_DEPTH = 0.125         # m, near end of the blade held in the sleeve
GAP = 0.001                  # m, free end to end plate
SET_RPM = [500, 900, 1000, 1100, 1400, 1800]
CORE_RPM = [500, 1100, 1800]
CELL_KG = [1, 2, 3, 5]       # bar-cell capacities compared
CHOSEN_KG = 3                # both axes
POST_D, POST_L, POST_S = 2.0e-3, 0.110, 0.120     # flexure rods: dia, length, square side
STINGER_D, STINGER_L = 0.8e-3, 0.040              # music-wire stingers
PLATE_BELOW_FLOOR = 0.158    # m, metric plate below the floor surface
DISC_D, SLOT_CLEAR = 0.080, 0.0003                # turntable disc; slot clearance per side
SLEEVE_BASE = 0.015          # m, sleeve below the slot floor
END_PLATE_T, POST_MIN = 0.003, 0.025              # m, end plate; shortest useful post
BELOW_PLATE = 0.006 + 0.012 + 0.060 + 0.050       # m: plate, index plate, cell base, box clearance
SETTLE_S, RECORD_S, ZERO_S = 20.0, 30.0, 20.0     # per point / per zero
JOG_S = 70.0                 # s, `run.py jog --seconds`: ramp up, settle, record and a margin
MOUNT_S = 600.0              # s, bench re-bolt and reinstall per mounting
TUNNEL_SIDES = [0.30, 0.40, 0.50, 0.60]           # m, square sections tabulated

# ── assumptions (no data yet) ───────────────────────────────────────────────
RHO = 1.20                   # kg/m3, nominal air density for sizing
NU = 1.516e-5                # m2/s, value used by the CFD
E_PLA = (2.3e9, 3.5e9)       # Pa, printed PLA, low and high
NU_PLA = 0.36                # Poisson ratio, for G = E / 2(1 + nu)
RHO_PLA = 1260.0             # kg/m3, the slicer material in the 7 Oct meeting notes
CELL_DEFL_FS = (0.2e-3, 0.4e-3)   # m, cell deflection at full scale (not in datasheet)
METRIC_MASS = (0.6, 1.0)     # kg, sleeve + spigot + index disc + plate + blade
U_Q_1100 = 0.007             # q at 1100 rpm after the in-place manometer check (estimate)
U_CAL = 0.003                # force calibration slope: weights, pulley friction, fit (estimate)
ALPHA_SET_DEG = 0.2          # absolute alpha setting, gauge against the tunnel wall (estimate)
ALPHA_REPEAT_DEG = 0.1       # alpha repeatability between mountings, pin index (estimate)
FLOW_ANGLE_DEG = 0.5         # flow angularity before the cylinder check (assumed)
STEEL_E = 200e9              # Pa

# ── datasheet values ────────────────────────────────────────────────────────
CELL_MV_V = 1.0              # mV/V, TAL220B
CELL_REPEAT = 0.0005         # repeatability 0.05 % FS, TAL220B
EXC_V = 3.3                  # V, bridge excitation from the Nano's 3.3 V rail
HX_NOISE = {10: 50e-9, 80: 90e-9}   # V rms, HX711, gain 128
SLEW_RPM_S = 405.8           # drive ramp, data/tunnel.json max_slew_rpm_s
IMU_ODR = 952                # Hz, LSM9DS1 setting in firmware/tunnel_node

# ── literature ──────────────────────────────────────────────────────────────
THETA_2D = 0.96              # Maskell blockage factor, 2D limit of 0.96 + 1.94 exp(-0.06 AR)
PVC_OD = 0.04826             # m, NPS 1-1/2 schedule 40 pipe (1.900 in)
CD_CYL_2D = 1.17             # 2D circular cylinder, Hoerner (1965), Re 1e4-1e6
CD_HALFTUBE = (2.30, 1.20)   # 2D half-tube, concave / convex side upstream, Hoerner (1965)


def rpm_to_mps(rpm):
    cfg = json.loads((ROOT / "data" / "tunnel.json").read_text())
    a, b = cfg["calibration"]["coeffs"]
    return a * np.asarray(rpm, float) + b


# ═══════════════════════════════════════════════════════════════════════════
# GEOMETRY: thin-wall section properties from the B-spline of the STL section
# ═══════════════════════════════════════════════════════════════════════════

def section_geometry():
    s = json.loads((ROOT / "cfd/geometry/section_v1.json").read_text())
    cad = json.loads((ROOT / "cfd/measurements/blade_section_cad.json").read_text())
    o = s["model"]["outer_surface"]
    spl = BSpline(np.array(o["knots"]), np.array(o["ctrl_xy_m"]), 3)
    u = np.linspace(0, 1, 8001)
    xy, d1, d2 = spl(u), spl.derivative(1)(u), spl.derivative(2)(u)
    tang = d1 / np.linalg.norm(d1, axis=1)[:, None]
    nrm = np.column_stack([-tang[:, 1], tang[:, 0]])
    n_in = nrm * np.sign(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0])[:, None]
    t = s["model"]["wall_m"]
    # body frame of the CFD: x_b = R(+4.76 deg)(x_CAD - c), c = area centroid
    c_body = np.array([17.620e-3, 31.507e-3])
    rot = math.radians(4.76364)
    Rm = np.array([[math.cos(rot), -math.sin(rot)], [math.sin(rot), math.cos(rot)]])
    mid = (Rm @ (xy + 0.5 * t * n_in - c_body).T).T
    ds = np.linalg.norm(np.diff(mid, axis=0), axis=1)
    P = 0.5 * (mid[1:] + mid[:-1])
    L = ds.sum()
    cen = (P * ds[:, None]).sum(0) / L
    x, y = P[:, 0] - cen[0], P[:, 1] - cen[1]
    Ixx, Iyy, Ixy = t * np.sum(y * y * ds), t * np.sum(x * x * ds), t * np.sum(x * y * ds)
    Iav, Idf = 0.5 * (Ixx + Iyy), math.hypot(0.5 * (Ixx - Iyy), Ixy)
    I_min, I_max = Iav - Idf, Iav + Idf
    # extreme fibre about the weak principal axis
    phis = np.linspace(0, math.pi, 3601)
    mom = [t * np.sum((-x * math.sin(p) + y * math.cos(p)) ** 2 * ds) for p in phis]
    p_min = phis[int(np.argmin(mom))]
    c_weak = np.abs(-x * math.sin(p_min) + y * math.cos(p_min)).max() + 0.5 * t
    weak_load_deg = math.degrees(p_min + math.pi / 2) % 180
    if weak_load_deg > 90:
        weak_load_deg -= 180
    # torsion: St Venant J, shear centre and warping constant (sectorial method)
    J = L * t ** 3 / 3
    dx, dy = np.diff(mid[:, 0]), np.diff(mid[:, 1])
    dw = x * dy - y * dx
    wB = np.concatenate([[0], np.cumsum(dw)])[:-1] + 0.5 * dw
    Iwx, Iwy = t * np.sum(wB * x * ds), t * np.sum(wB * y * ds)
    xs, ys = np.linalg.solve(np.array([[-Ixy, Iyy], [-Ixx, Ixy]]), -np.array([Iwx, Iwy]))
    wS = wB - xs * (y - y[0]) + ys * (x - x[0])
    wn = wS - np.sum(wS * ds) / L
    Gam = t * np.sum(wn ** 2 * ds)
    # outline (for R_max and the drawings), area centroid
    pts = np.array([[float(r["x_m"]), float(r["y_m"])]
                    for r in csv.DictReader(open(ROOT / "cfd/geometry/section_v1.csv"))])
    px, py = pts[:, 0], pts[:, 1]
    cr = px * np.roll(py, -1) - np.roll(px, -1) * py
    a2 = cr.sum() / 2
    cx = ((px + np.roll(px, -1)) * cr).sum() / (6 * a2)
    cy = ((py + np.roll(py, -1)) * cr).sum() / (6 * a2)
    r_max = float(np.hypot(px - cx, py - cy).max())
    holes = sorted(h["z_from_near_end_mm"] for h in cad["holes"])
    hole_d = s["holes"]["found"][0]["diameter_from_z_extent_m"]
    far_edge = (holes[-1] * 1e-3) + 0.5 * hole_d
    span = s["source"]["span_m"]
    return {
        "span_m": span, "wall_m": t, "midline_m": L, "area_m2": t * L,
        "I_min_m4": I_min, "I_max_m4": I_max, "c_weak_m": c_weak,
        "weak_load_dir_from_xbody_deg": weak_load_deg,
        "J_m4": J, "Gamma_m6": Gam, "shear_centre_body_m": [float(xs), float(ys)],
        "r_max_about_centroid_m": r_max,
        "chord_tip_to_tip_m": s["dimensions"]["chord_outer_tip_to_tip_m"],
        "depth_m": s["dimensions"]["depth_from_chord_m"],
        "holes_from_near_end_mm": holes, "hole_d_m": hole_d,
        "far_hole_far_edge_from_near_end_m": far_edge,
        "sleeve_depth_m": SLEEVE_DEPTH, "sleeve_margin_past_hole_m": SLEEVE_DEPTH - far_edge,
        "holes_below_disc_face_mm": [SLEEVE_DEPTH * 1e3 - h for h in holes][::-1],
        "b_e_m": span - SLEEVE_DEPTH,
        "_outline": pts, "_outline_c": (cx, cy),
    }


# ═══════════════════════════════════════════════════════════════════════════
# CFD (healthy runs only)
# ═══════════════════════════════════════════════════════════════════════════

def cfd_numbers():
    pol = pd.read_csv(ROOT / "cfd/section2d/results/section_polars.csv")
    qual = pd.read_csv(ROOT / "cfd/analysis/2026-10-15/out/section_case_quality.csv")
    h = pol.merge(qual[["name", "corrupted", "branch_a0"]], on="name", how="left")
    h = h[h.corrupted == False].copy()  # noqa: E712
    out = {"n_healthy": int(len(h))}
    for a in (0, 90, 180, 270):
        g = h[h.alpha_deg == a]
        out[f"a{a}"] = {"speeds": sorted(g.U_ms.unique().tolist()), "n": int(len(g)),
                        "Cd": [float(g.Cd_mean.min()), float(g.Cd_mean.max())],
                        "Cl": [float(g.Cl_mean.min()), float(g.Cl_mean.max())]}
    # alpha-0 states; the SST maxCo-1.25 run changes state inside its window
    a0 = h[(h.alpha_deg == 0) & ~((h.model == "SST") & (h.maxCo == 1.25))]
    lo, hi = a0[a0.branch_a0 == "low-drag"], a0[a0.branch_a0 == "high-drag"]
    out["a0_low"] = [float(lo.Cd_mean.min()), float(lo.Cd_mean.max())]
    out["a0_high"] = [float(hi.Cd_mean.min()), float(hi.Cd_mean.max())]
    out["a0_high_Cl"] = [float(hi.Cl_mean.min()), float(hi.Cl_mean.max())]
    out["a0_low_Cl"] = [float(lo.Cl_mean.min()), float(lo.Cl_mean.max())]
    # Strouhal numbers (clean spectral peaks)
    clean = h[(h.St_peak_frac >= 0.5) & (h.St < 1.0)]
    for a in (0, 180):
        g = clean[clean.alpha_deg == a]
        out[f"St_a{a}"] = [float(g.St.min()), float(g.St.max())]
    g90 = h[(h.alpha_deg == 90) & (h.maxCo == 5)]
    out["St_a90_maxCo5"] = [float(g90.St.min()), float(g90.St.max())]
    g180_125 = h[(h.alpha_deg == 180) & (h.maxCo == 1.25)]
    out["a180_maxCo1p25_Cd"] = [float(g180_125.Cd_mean.min()), float(g180_125.Cd_mean.max())]
    # whole healthy set
    out["max_Cd"] = float(h.Cd_mean.max())
    i = h.Cl_mean.abs().idxmax()
    out["max_absCl"], out["max_absCl_alpha"] = float(abs(h.Cl_mean[i])), float(h.alpha_deg[i])
    out["max_absCl_a0_90_180"] = float(h[h.alpha_deg.isin([0, 90, 180])].Cl_mean.abs().max())
    # peak (mean + 3 std) per CFD speed, any alpha
    pk = {}
    for U in (10.2, 23.0, 38.0):
        g = h[h.U_ms == U]
        pk[str(U)] = {"Cd": float((g.Cd_mean.abs() + 3 * g.Cd_std).max()),
                      "Cl": float((g.Cl_mean.abs() + 3 * g.Cl_std).max())}
    out["peak3"] = pk
    # LM 23 m/s polar slopes around 90 and 180 deg (healthy runs, per deg)
    lm = h[(h.model == "LM") & (h.U_ms == 23.0) & (h.Tu_inlet_pct == 1.0) & (h.level == "medium")]
    lm = lm.sort_values("maxCo").drop_duplicates("alpha_deg", keep="first").set_index("alpha_deg")
    def slope(col, a1, a2):
        return float((lm.loc[a2, col] - lm.loc[a1, col]) / (a2 - a1))
    out["slopes_per_deg"] = {
        "Cl_75_90": slope("Cl_mean", 75, 90), "Cl_90_105": slope("Cl_mean", 90, 105),
        "Cd_75_90": slope("Cd_mean", 75, 90), "Cd_90_105": slope("Cd_mean", 90, 105),
        "Cd_165_180": slope("Cd_mean", 165, 180), "Cd_180_195": slope("Cd_mean", 180, 195),
        "Cl_165_180": slope("Cl_mean", 165, 180), "Cl_180_195": slope("Cl_mean", 180, 195),
        "Cl_345_0": float((lm.loc[0, "Cl_mean"] - lm.loc[345, "Cl_mean"]) / 15),
        "Cd_345_0": float((lm.loc[0, "Cd_mean"] - lm.loc[345, "Cd_mean"]) / 15),
        "Cl_0_15": slope("Cl_mean", 0, 15)}
    # moments about the centroid, for torsion
    out["_rows"] = h[["alpha_deg", "U_ms", "Cd_mean", "Cl_mean", "Cm_mean"]].copy()
    # rough-wall changes (SST wall functions, 23 m/s, maxCo 2.5), relative to Ks 0
    wf = pd.read_csv(ROOT / "cfd/analysis/2026-10-15/out/roughness_wf_effects.csv")
    rw = {}
    for a in (0, 90, 180):
        base = wf[(wf.alpha_deg == a) & (wf.Ks_um == 0) & (wf.maxCo == 2.5) & (wf.U_ms == 23.0)]
        rw[f"a{a}_Ks0_Cd"] = float(base.Cd.iloc[0])
        rw[f"a{a}_Ks0_Cl"] = float(base.Cl.iloc[0])
        for ks in (50, 100, 200, 400):
            r = wf[(wf.alpha_deg == a) & (wf.Ks_um == ks) & (wf.maxCo == 2.5) & (wf.U_ms == 23.0)]
            rw[f"a{a}_Ks{ks}"] = {"dCd_pct": float(r.dCd_pct.iloc[0]), "dCl_pct": float(r.dCl_pct.iloc[0]),
                                  "Cd": float(r.Cd.iloc[0]), "Cl": float(r.Cl.iloc[0])}
    # FS minus Plain under two Ks mappings (Plain ~ Ks 50, the nearest run to 38 um)
    def rel(a, ks_hi, ks_lo, col):
        return 100 * (rw[f"a{a}_Ks{ks_hi}"][col] / rw[f"a{a}_Ks{ks_lo}"][col] - 1)
    rw["a90_FS020_vs_Plain_Ks_eq_k"] = {"dCd_pct": rel(90, 100, 50, "Cd"), "dCl_pct": rel(90, 100, 50, "Cl")}
    rw["a90_FS010_vs_Plain_nominal"] = {"dCd_pct": rel(90, 200, 50, "Cd"), "dCl_pct": rel(90, 200, 50, "Cl")}
    rw["a90_FS020_vs_Plain_nominal"] = {"dCd_pct": rel(90, 400, 50, "Cd"), "dCl_pct": rel(90, 400, 50, "Cl")}
    out["rough_wall_23"] = rw
    return out


# ═══════════════════════════════════════════════════════════════════════════
# CALCULATIONS
# ═══════════════════════════════════════════════════════════════════════════

def beam_modes(geo):
    mprime = RHO_PLA * geo["area_m2"]
    res = {"mass_per_length_kg_m": mprime}
    for name, Lb, bl in (("cantilever_exposed", geo["b_e_m"], 1.8751),
                         ("cantilever_full", geo["span_m"], 1.8751),
                         ("clamped_both_full", geo["span_m"], 4.7300)):
        for axis, I in (("weak", geo["I_min_m4"]), ("strong", geo["I_max_m4"])):
            res[f"{name}_{axis}_Hz"] = [bl ** 2 / (2 * math.pi * Lb ** 2) * math.sqrt(E * I / mprime)
                                        for E in E_PLA]
    return res


def twist(geo, m, L, E):
    """Tip twist of a cantilever under a uniform torque m (N m/m) about the
    shear centre. Returns (St Venant, Vlasov with the root warping held)."""
    G = E / (2 * (1 + NU_PLA))
    J, Gam = geo["J_m4"], geo["Gamma_m6"]
    phi_sv = m * L ** 2 / (2 * G * J)
    k = math.sqrt(G * J / (E * Gam))
    A = -m * L / (G * J)
    B = (m / (G * J) / k - A * math.sinh(k * L)) / math.cosh(k * L)
    z = np.linspace(0, L, 2001)
    psi = m * (L - z) / (G * J) + A * np.cosh(k * z) + B * np.sinh(k * z)
    phi = np.concatenate([[0.0], np.cumsum(0.5 * (psi[1:] + psi[:-1]) * np.diff(z))])
    return phi_sv, float(phi[-1]), k * L, 2 * phi_sv / 3, float(phi.mean())


def moment_about_sc(geo, rows, alpha, q):
    """Largest |torque per span| about the shear centre over healthy CFD runs,
    with its sign (+ = counter-clockwise about +z_body, which lowers alpha)."""
    xs, ys = geo["shear_centre_body_m"]
    best, sign = 0.0, 1.0
    for _, r in rows[rows.alpha_deg == alpha].iterrows():
        a = math.radians(r.alpha_deg)
        F = q * C_REF * (r.Cd_mean * np.array([math.cos(a), math.sin(a)])
                         + r.Cl_mean * np.array([-math.sin(a), math.cos(a)]))
        Ms = r.Cm_mean * q * C_REF ** 2 + (-xs * F[1] + ys * F[0])
        if abs(Ms) > best:
            best, sign = abs(Ms), math.copysign(1.0, Ms)
    return best, sign


def main():
    geo = section_geometry()
    cfd = cfd_numbers()
    U = rpm_to_mps(SET_RPM)
    q = 0.5 * RHO * U ** 2
    b_e = geo["b_e_m"]
    S, S_full = C_REF * b_e, C_REF * geo["span_m"]
    iq = {r: i for i, r in enumerate(SET_RPM)}
    N = {"_README": "Generated by docs/diagrams/build_section_test.py. Design-stage numbers; "
                    "nothing here is a measurement of the section test."}
    N["inputs"] = {
        "proposed": {"c_ref_m": C_REF, "sleeve_depth_m": SLEEVE_DEPTH, "gap_m": GAP,
                     "set_rpm": SET_RPM, "core_rpm": CORE_RPM, "cell_kg": CHOSEN_KG,
                     "post_d_m": POST_D, "post_L_m": POST_L, "post_square_m": POST_S,
                     "stinger_d_m": STINGER_D, "stinger_L_m": STINGER_L,
                     "settle_s": SETTLE_S, "record_s": RECORD_S, "zero_s": ZERO_S,
                     "jog_s": JOG_S},
        "assumed": {"rho_kg_m3": RHO, "nu_m2_s": NU, "E_PLA_Pa": E_PLA, "nu_PLA": NU_PLA,
                    "rho_PLA_kg_m3": RHO_PLA, "cell_deflection_at_FS_m": CELL_DEFL_FS,
                    "metric_mass_kg": METRIC_MASS, "u_q_1100": U_Q_1100, "u_cal": U_CAL,
                    "alpha_set_deg": ALPHA_SET_DEG, "alpha_repeat_deg": ALPHA_REPEAT_DEG,
                    "flow_angle_deg": FLOW_ANGLE_DEG},
        "datasheet": {"cell_mV_V": CELL_MV_V, "cell_repeatability_FS": CELL_REPEAT,
                      "excitation_V": EXC_V, "hx711_noise_V": HX_NOISE, "imu_odr_Hz": IMU_ODR},
        "literature": {"theta_2D": THETA_2D, "Cd_cyl_2D": CD_CYL_2D, "Cd_halftube_2D": CD_HALFTUBE,
                       "pvc_od_m": PVC_OD}}
    N["geometry"] = {k: v for k, v in geo.items() if not k.startswith("_")}
    N["geometry"].update({"disc_margin_outside_slot_m": DISC_D / 2 - geo["r_max_about_centroid_m"] - SLOT_CLEAR,
                          "sleeve_length_m": SLEEVE_DEPTH + SLEEVE_BASE,
                          "gap_pct_of_b_e": 100 * GAP / b_e, "gap_pct_of_c_ref": 100 * GAP / C_REF,
                          "wall_to_wall_dimension_m": [geo["span_m"] + 2 * 0.0005, geo["span_m"] + 2 * 0.001],
                          "depth_behind_wall_m": PLATE_BELOW_FLOOR + BELOW_PLATE,
                          "min_dimension_along_span_m": b_e + GAP + END_PLATE_T + POST_MIN,
                          "S_m2": S, "S_full_m2": S_full, "AR_exposed": b_e / C_REF,
                          "AR_full_blade": geo["span_m"] / C_REF,
                          "turntable_min_d_m": 2 * geo["r_max_about_centroid_m"],
                          "chord_factor_ref_over_tips": C_REF / geo["chord_tip_to_tip_m"]})
    N["setpoints"] = [{"rpm": r, "U": float(u), "q_Pa": float(qq), "Re_c": float(u * C_REF / NU),
                       "qS_N": float(qq * S), "qS_full_N": float(qq * S_full)}
                      for r, u, qq in zip(SET_RPM, U, q)]
    N["cfd"] = {k: v for k, v in cfd.items() if not k.startswith("_")}

    # ── loads ────────────────────────────────────────────────────────────
    q38, q23, q10 = q[iq[1800]], q[iq[1100]], q[iq[500]]
    pk38 = cfd["peak3"]["38.0"]
    N["loads"] = {
        "D_mean_max_N": cfd["max_Cd"] * q38 * S,
        "D_peak3_38_N": pk38["Cd"] * q38 * S,
        "L_mean_max_a0_90_180_N": cfd["max_absCl_a0_90_180"] * q38 * S,
        "L_mean_max_any_alpha_N": cfd["max_absCl"] * q38 * S,
        "L_mean_max_any_alpha_23_N": cfd["max_absCl"] * q23 * S,
        "L_peak3_38_N": pk38["Cl"] * q38 * S,
        "full_span_D_mean_max_N": cfd["max_Cd"] * q38 * S_full,
        "side_wall_lift_cell_N": [m * G0 + cfd["max_absCl"] * q38 * S for m in METRIC_MASS],
        "full_span_D_peak3_38_N": pk38["Cd"] * q38 * S_full,
        "a90_D_N": {"10.2": [v * q10 * S for v in cfd["a90"]["Cd"]],
                    "23": [v * q23 * S for v in cfd["a90"]["Cd"]],
                    "38": [v * q38 * S for v in cfd["a90"]["Cd"]]},
        "a90_L_N": {"10.2": [v * q10 * S for v in cfd["a90"]["Cl"]],
                    "23": [v * q23 * S for v in cfd["a90"]["Cl"]]},
        "a180_D_N_23": [v * q23 * S for v in cfd["a180"]["Cd"]],
        "a0_high_D_N_38": [v * q38 * S for v in cfd["a0_high"]],
    }
    L_ = N["loads"]
    tab = {}
    for key, cd, cl in (("a0_low", cfd["a0_low"], cfd["a0_low_Cl"]), ("a0_high", cfd["a0_high"], cfd["a0_high_Cl"]),
                        ("a90", cfd["a90"]["Cd"], cfd["a90"]["Cl"]), ("a180", cfd["a180"]["Cd"], cfd["a180"]["Cl"])):
        lo_l, hi_l = sorted((abs(cl[0]), abs(cl[1])))
        if cl[0] * cl[1] < 0:
            lo_l = 0.0
        tab[key] = {r: {"D": [cd[0] * q[iq[r]] * S, cd[1] * q[iq[r]] * S],
                        "L": [lo_l * q[iq[r]] * S, hi_l * q[iq[r]] * S]} for r in (500, 1100, 1800)}
    L_["table"] = tab
    cells = []
    for kg in CELL_KG:
        FS = kg * G0
        cells.append({
            "kg": kg, "FS_N": FS,
            "D_mean_pct": 100 * L_["D_mean_max_N"] / FS, "D_peak_pct": 100 * L_["D_peak3_38_N"] / FS,
            "L_mean_a0_90_180_pct": 100 * L_["L_mean_max_a0_90_180_N"] / FS,
            "L_mean_any_pct": 100 * L_["L_mean_max_any_alpha_N"] / FS,
            "L_peak_pct": 100 * L_["L_peak3_38_N"] / FS,
            "repeat_mN": 1e3 * CELL_REPEAT * FS,
            "repeat_pct_a90_D_10": [100 * CELL_REPEAT * FS / v for v in L_["a90_D_N"]["10.2"]][::-1],
            "repeat_pct_a90_D_23": [100 * CELL_REPEAT * FS / v for v in L_["a90_D_N"]["23"]][::-1],
            "repeat_pct_a90_D_38": [100 * CELL_REPEAT * FS / v for v in L_["a90_D_N"]["38"]][::-1],
            "repeat_pct_a90_L_23": [100 * CELL_REPEAT * FS / v for v in L_["a90_L_N"]["23"]][::-1],
            "hx711_noise_mN": {r: 1e3 * HX_NOISE[r] / (EXC_V * CELL_MV_V * 1e-3) * FS for r in HX_NOISE},
            "stiffness_N_mm": [FS / CELL_DEFL_FS[1] * 1e-3, FS / CELL_DEFL_FS[0] * 1e-3]})
    N["cells"] = cells
    cell = [c for c in cells if c["kg"] == CHOSEN_KG][0]

    # ── structure ────────────────────────────────────────────────────────
    modes = beam_modes(geo)
    N["modes"] = modes
    E_lo = E_PLA[0]
    w = L_["D_mean_max_N"] / b_e
    N["strength"] = {
        "tip_deflection_mm": 1e3 * w * b_e ** 4 / (8 * E_lo * geo["I_min_m4"]),
        "root_stress_MPa": 1e-6 * (L_["D_mean_max_N"] * b_e / 2) * geo["c_weak_m"] / geo["I_min_m4"],
        "full_root_stress_MPa": 1e-6 * (L_["full_span_D_mean_max_N"] * geo["span_m"] / 2)
        * geo["c_weak_m"] / geo["I_min_m4"]}
    tw = {}
    sl = cfd["slopes_per_deg"]
    # local polar slopes on the side the twist moves alpha to (CFD LM polar, 23 m/s)
    side = {0: {-1: ("Cd_345_0", "Cl_345_0")}, 90: {1: ("Cd_90_105", "Cl_90_105")},
            180: {1: ("Cd_180_195", "Cl_180_195")}}
    coef = {0: (np.mean(cfd["a0_low"]), 0.1), 90: (np.mean(cfd["a90"]["Cd"]), np.mean(cfd["a90"]["Cl"])),
            180: (np.mean(cfd["a180"]["Cd"]), np.mean(cfd["a180"]["Cl"]))}
    for a in (0, 90, 180):
        for lab, qq in (("23", q23), ("38", q38)):
            m, sgn = moment_about_sc(geo, cfd["_rows"], a, qq)
            sv, vl, kL, sv_mean, vl_mean = twist(geo, m, b_e, E_lo)
            dalpha = -sgn          # +torque about +z turns the blade CCW about +z: alpha falls
            ks = side[a].get(int(dalpha))
            mean_deg = [math.degrees(vl_mean), math.degrees(sv_mean)]
            row = {"torque_N_m_per_m": m, "alpha_moves": "up" if dalpha > 0 else "down",
                   "tip_deg": [math.degrees(vl), math.degrees(sv)], "span_mean_deg": mean_deg}
            if ks:
                dcd = [abs(sl[ks[0]]) * d for d in mean_deg]
                dcl = [abs(sl[ks[1]]) * d for d in mean_deg]
                row.update({"dCd": dcd, "dCl": dcl,
                            "dCd_pct": [100 * v / coef[a][0] for v in dcd],
                            "dCl_pct": [100 * v / abs(coef[a][1]) for v in dcl]})
            tw[f"a{a}_{lab}"] = row
    tw["kL"] = kL
    m90, _ = moment_about_sc(geo, cfd["_rows"], 90, q38)
    tw["a90_38_full_span_stvenant_deg"] = math.degrees(twist(geo, m90, geo["span_m"], E_lo)[0])
    N["twist_E_low"] = tw

    st0, st180, st90 = cfd["St_a0"], cfd["St_a180"], cfd["St_a90_maxCo5"]
    U10, U38 = U[iq[500]], U[iq[1800]]
    N["shedding"] = {
        "f_a0_Hz": [st0[0] * U10 / C_REF, st0[1] * U38 / C_REF],
        "f_a180_Hz": [st180[0] * U10 / C_REF, st180[1] * U38 / C_REF],
        "f_a90_Hz": [st90[0] * U10 / C_REF, st90[1] * U38 / C_REF],
        "lock_full_weak_a180_U": [modes["cantilever_full_weak_Hz"][0] * C_REF / st180[1],
                                  modes["cantilever_full_weak_Hz"][1] * C_REF / st180[0]],
        "lock_full_weak_a0_U": [modes["cantilever_full_weak_Hz"][0] * C_REF / st0[1],
                                modes["cantilever_full_weak_Hz"][1] * C_REF / st0[0]],
        "lock_exposed_weak_a90_U": [modes["cantilever_exposed_weak_Hz"][0] * C_REF / st90[1],
                                    modes["cantilever_exposed_weak_Hz"][1] * C_REF / st90[0]],
        # in-line (drag) forces at twice the shedding frequency, alpha 180
        "f2_a180_38_Hz": [2 * st180[0] * U38 / C_REF, 2 * st180[1] * U38 / C_REF],
        "lock_exposed_weak_a180_2f_U": [modes["cantilever_exposed_weak_Hz"][0] * C_REF / (2 * st180[1]),
                                        modes["cantilever_exposed_weak_Hz"][1] * C_REF / (2 * st180[0])],
        "imu_nyquist_Hz": IMU_ODR / 2}
    k_cell = [s * 1e3 for s in cell["stiffness_N_mm"]]
    f_bal = [1 / (2 * math.pi) * math.sqrt(k_cell[0] / METRIC_MASS[1]),
             1 / (2 * math.pi) * math.sqrt(k_cell[1] / METRIC_MASS[0])]
    I_p = math.pi * POST_D ** 4 / 64
    k_p = 12 * STEEL_E * I_p / POST_L ** 3
    I_s = math.pi * STINGER_D ** 4 / 64
    k_s = 12 * STEEL_E * I_s / STINGER_L ** 3
    arm = b_e / 2 + PLATE_BELOW_FLOOR
    M_ov = L_["D_mean_max_N"] * arm
    N["balance"] = {
        "f1_Hz": f_bal,
        "shed_lock_U_a0": [f_bal[0] * C_REF / st0[1], f_bal[1] * C_REF / st0[0]],
        "shed_lock_U_a180": [f_bal[0] * C_REF / st180[1], f_bal[1] * C_REF / st180[0]],
        "posts_lateral_N_mm": 4 * k_p * 1e-3,
        "posts_shunt_pct": [100 * 4 * k_p / (4 * k_p + k_cell[1]), 100 * 4 * k_p / (4 * k_p + k_cell[0])],
        "post_buckling_N": math.pi ** 2 * STEEL_E * I_p / (0.5 * POST_L) ** 2,
        "stinger_lateral_N_mm": k_s * 1e-3,
        "stinger_cross_pct": [100 * k_s / (k_s + k_cell[1]), 100 * k_s / (k_s + k_cell[0])],
        "stinger_buckling_N": math.pi ** 2 * STEEL_E * I_s / (0.5 * STINGER_L) ** 2,
        "overturning_arm_m": arm, "overturning_moment_Nm": M_ov,
        "post_axial_from_moment_N": M_ov / (2 * POST_S)}

    # ── blockage: Maskell q_c/q = 1 + theta Cd S/C ───────────────────────
    th_free = THETA_2D + 1.94 * math.exp(-0.06 * 2 * b_e / C_REF)
    cds = {"a0_high": cfd["a0_high"][1], "a0_low": cfd["a0_low"][0], "a180": 1.5, "a90": 0.39}
    rows = []
    for side in TUNNEL_SIDES:
        Cts = side * side
        r = {"side_m": side, "C_m2": Cts, "S_over_C_pct": 100 * S / Cts,
             "S_full_over_C_pct": 100 * S_full / Cts}
        for k, cd in cds.items():
            r[k] = {"Cd": cd, "corr_pct": [100 * THETA_2D * cd * S / Cts, 100 * th_free * cd * S / Cts]}
        rows.append(r)
    need = {f"{k}_{int(100*lim)}pct_C_m2": 0.5 * (th_free - THETA_2D) * cds[k] * S / lim
            for k in ("a180", "a0_high") for lim in (0.05, 0.10)}
    Cs = TUNNEL_SIDES[0] ** 2
    hi = cfd["a0_high"][1]
    N["blockage"] = {"theta_2D": THETA_2D, "theta_free_tip": th_free, "AR_reflected": 2 * b_e / C_REF,
                     "theta_uniform_mean": 0.5 * (THETA_2D + th_free),
                     "theta_uniform_sd": (th_free - THETA_2D) / math.sqrt(12),
                     "table": rows, "C_needed": need,
                     "a0_state_ratio_min": cfd["a0_high"][0] / cfd["a0_low"][1],
                     "theta_band_factor_smallest_C": (1 + th_free * hi * S / Cs) / (1 + THETA_2D * hi * S / Cs)}

    # ── reference cylinder ───────────────────────────────────────────────
    N["cylinder"] = {"od_m": PVC_OD, "Re": [float(U10 * PVC_OD / NU), float(U38 * PVC_OD / NU)],
                     "Re_1100": float(U[iq[1100]] * PVC_OD / NU),
                     "S_m2": PVC_OD * b_e, "D_23_N": float(CD_CYL_2D * q23 * PVC_OD * b_e),
                     "flow_angle_resolution_deg": math.degrees(math.atan(1e-3 * cell["repeat_mN"]
                                                                         / (CD_CYL_2D * q23 * PVC_OD * b_e)))}

    # ── time budget ──────────────────────────────────────────────────────
    # one run.py jog per point: it holds JOG_S from its start (ramp up, settle, record,
    # margin), then ramps down; then a wind-off zero
    def point(rpm):
        return JOG_S + rpm / SLEW_RPM_S + ZERO_S
    block = ZERO_S + sum(point(r) for r in CORE_RPM)
    repeat = ZERO_S + point(1100)
    mount = 3 * block + repeat + MOUNT_S
    polar_mount = 24 * (ZERO_S + point(1100)) + MOUNT_S
    N["time"] = {"ramp_0_1800_s": 1800 / SLEW_RPM_S, "point_1100_s": point(1100),
                 "jog_margin_1800_s": JOG_S - 1800 / SLEW_RPM_S - SETTLE_S - RECORD_S,
                 "alpha_block_min": block / 60, "mounting_min": mount / 60,
                 "session1_h": 7 * mount / 3600, "polar_mounting_min": polar_mount / 60,
                 "session3_h": 4 * polar_mount / 3600}

    # ── uncertainty (design-stage, 1100 rpm, chosen cells) ───────────────
    sl = cfd["slopes_per_deg"]
    rep = 1e-3 * cell["repeat_mN"]
    unc = {}
    for a, cd, cl, scd, scl in ((90, np.mean(cfd["a90"]["Cd"]), np.mean(cfd["a90"]["Cl"]),
                                 max(abs(sl["Cd_75_90"]), abs(sl["Cd_90_105"])),
                                 max(abs(sl["Cl_75_90"]), abs(sl["Cl_90_105"]))),
                                (180, np.mean(cfd["a180"]["Cd"]), np.mean(cfd["a180"]["Cl"]),
                                 max(abs(sl["Cd_165_180"]), abs(sl["Cd_180_195"])),
                                 max(abs(sl["Cl_165_180"]), abs(sl["Cl_180_195"])))):
        D, Lf = cd * q23 * S, abs(cl) * q23 * S
        cellp = [100 * rep / D, 100 * rep / Lf]
        alp = [100 * scd * ALPHA_SET_DEG / cd, 100 * scl * ALPHA_SET_DEG / abs(cl)]
        alr = [100 * scd * ALPHA_REPEAT_DEG / cd, 100 * scl * ALPHA_REPEAT_DEG / abs(cl)]
        flo = [100 * math.sin(math.radians(FLOW_ANGLE_DEG)) * abs(cl) / cd,
               100 * math.sin(math.radians(FLOW_ANGLE_DEG)) * cd / abs(cl)]
        Sp = 100 * 0.2e-3 / b_e
        tot = [math.sqrt(cellp[i] ** 2 + alp[i] ** 2 + flo[i] ** 2 + Sp ** 2
                         + (100 * U_Q_1100) ** 2 + (100 * U_CAL) ** 2) for i in (0, 1)]
        dif = [math.sqrt(2) * math.hypot(cellp[i], alr[i]) for i in (0, 1)]
        unc[f"a{a}"] = {
            "Cd": float(cd), "Cl": float(cl), "D_N": float(D), "L_N": float(Lf),
            "cell_pct": cellp, "alpha_set_pct": alp, "alpha_repeat_pct": alr, "flow_angle_pct": flo,
            "S_pct": Sp, "q_pct": 100 * U_Q_1100, "cal_pct": 100 * U_CAL,
            "total_abs_pct_excl_blockage": tot, "pair_difference_pct": dif}
    N["uncertainty_1100rpm"] = unc
    # 95 % interval of FS - Plain with Session 1's mountings (Plain 3, each FS 2), only the
    # budgeted per-mounting terms (cell repeatability, alpha repeatability): a lower bound
    n_p, n_f = 3, 2
    tq = float(student_t.ppf(0.975, n_p + n_f - 2))
    fac = tq * math.sqrt(1 / n_p + 1 / n_f)
    hw = {}
    for a in ("a90", "a180"):
        u_ = unc[a]
        for i, cname in ((0, "Cd"), (1, "Cl")):
            sig = math.hypot(u_["cell_pct"][i], u_["alpha_repeat_pct"][i])
            hw[f"{a}_{cname}_1100"] = fac * sig
            # at 1800 rpm the cell term scales with 1/q; the alpha term is relative
            sig38 = math.hypot(u_["cell_pct"][i] * q23 / q38, u_["alpha_repeat_pct"][i])
            hw[f"{a}_{cname}_1800"] = fac * sig38
    N["session1_halfwidth_pct"] = {"t": tq, "n_plain": n_p, "n_fs": n_f, **hw}

    (HERE / "section_test_numbers.json").write_text(json.dumps(N, indent=1, default=float) + "\n")
    fig_concept(geo, N)
    fig_loads(N)
    fig_frequencies(N)
    return N


# ═══════════════════════════════════════════════════════════════════════════
# FIGURES
# ═══════════════════════════════════════════════════════════════════════════

def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(DIM)
    ax.tick_params(colors=INK, labelsize=8)


def fig_concept(geo, N):
    fig = plt.figure(figsize=(11.0, 6.6), dpi=150)
    ax = fig.add_axes([0.01, 0.02, 0.57, 0.93])
    ax.set_aspect("equal")
    ax.axis("off")
    b_e, ds = geo["b_e_m"] * 1e3, SLEEVE_DEPTH * 1e3
    H, tp = 300, 12
    plate_y = -PLATE_BELOW_FLOOR * 1e3
    # test section, flow left to right
    ax.add_patch(Rectangle((-280, 0), 560, H, fc=WASH, ec="none"))
    ax.add_patch(Rectangle((-280, -tp), 238, tp, fc="#b9c7d4", ec="none"))
    ax.add_patch(Rectangle((42, -tp), 238, tp, fc="#b9c7d4", ec="none"))
    ax.plot([-280, 280], [H, H], color=NAVY, lw=2.2)
    ax.text(-275, H + 8, "ceiling (opposite wall)", fontsize=7, color=DIM)
    ax.text(95, 6, "floor panel (a copy of the existing one)", fontsize=7, color=DIM)
    ax.annotate("", xy=(-190, 175), xytext=(-268, 175),
                arrowprops=dict(arrowstyle="-|>", color=KEANEY, lw=2))
    ax.text(-268, 183, "U", color=KEANEY, fontsize=10, weight="bold")
    # pitot-static, from the ceiling, above the end plate
    ax.plot([-170, -212], [232, 232], color=INK, lw=2.4)
    ax.plot([-170, -170], [232, H], color=INK, lw=2.4)
    ax.text(-162, 262, "reference pitot-static\n(its wake passes above\nthe end plate)", fontsize=7, color=INK)
    # sleeve top = turntable disc, blade
    ax.add_patch(Rectangle((-40, -ds - 15), 80, ds + 15, fc="#eaf1f8", ec=NAVY, lw=1.2))
    ax.add_patch(Rectangle((-11, -ds), 22, ds, fc=GOLD, ec=GOLDDK, lw=0.8, alpha=0.5))
    ax.add_patch(Rectangle((-11, 0), 22, b_e, fc=GOLD, ec=GOLDDK, lw=1.2))
    ax.text(16, 70, f"existing blade,\nexposed span {b_e:.0f} mm", fontsize=7.5, color=INK)
    for zh in geo["holes_below_disc_face_mm"]:
        ax.plot([-38, 38], [-zh, -zh], color=FAULT, lw=1.6)
    ax.annotate("2 bolts through the blade's\nown holes (heads recessed)", xy=(38, -10), xytext=(50, 22),
                fontsize=7, color=FAULT, arrowprops=dict(arrowstyle="-", color=FAULT, lw=0.8))
    ax.text(112, -ds + 30, f"printed sleeve:\nholds the near\nend {ds:.0f} mm deep", fontsize=6.8, color=NAVY)
    ax.annotate("Ø80 disc in an Ø82 opening:\n1 mm gap, no contact", xy=(-41, -2), xytext=(-255, 28),
                fontsize=7, color=NAVY, arrowprops=dict(arrowstyle="-", color=NAVY, lw=0.8))
    # end plate (non-metric) and its posts
    ep = b_e + GAP * 1e3
    ax.add_patch(Rectangle((-120, ep), 360, 3.5, fc=NAVY, ec=NAVY))
    for xp in (150, 215):
        ax.add_patch(Rectangle((xp - 3, ep + 3.5), 6, H - ep - 3.5, fc="#8fa5b8", ec="none"))
    ax.text(-118, ep + 9, f"clear end plate (non-metric), gap {GAP*1e3:.0f} mm", fontsize=7, color=NAVY)
    ax.text(157, 205, "2 posts,\nbolted both ends", fontsize=6.8, color=DIM)
    # below the floor: spigot, index disc, metric plate, rods, cells, box
    ax.add_patch(Rectangle((-12, plate_y + 6), 24, -ds - 15 - plate_y - 6, fc="#8fa5b8", ec=NAVY, lw=0.8))
    ax.add_patch(Rectangle((-70, plate_y - 12), 140, 8, fc=PALE, ec=NAVY))
    ax.text(-68, plate_y - 24, "index plate, 24 × 15°, lock pin", fontsize=6.8, color=NAVY)
    ax.add_patch(Rectangle((-115, plate_y), 230, 6, fc=KEANEY, ec=NAVY))
    ax.text(-190, plate_y + 1, "metric plate", fontsize=6.8, color=KEANEY)
    gy = -tp - 30
    ax.plot([-135, -62], [gy, gy], color=DIM, lw=3.2)
    ax.plot([62, 135], [gy, gy], color=DIM, lw=3.2)
    for xp in (-105, 105):
        ax.plot([xp, xp], [gy, plate_y + 6], color=DIM, lw=1.3)
    ax.text(-196, gy - 4, "ground frame", fontsize=6.8, color=DIM)
    ax.text(-190, (gy + plate_y) / 2, "4 flexure\nrods Ø2,\nhanging", fontsize=6.8, color=DIM, va="center")
    # drag cell as a column, stinger to the plate
    cx0 = 160
    ax.add_patch(Rectangle((cx0, plate_y - 52), 13, 55, fc=GOLDDK, ec=INK))
    ax.plot([115, cx0], [plate_y + 3, plate_y + 3], color=INK, lw=1.0)
    ax.plot([cx0 - 10, cx0 + 30], [plate_y - 52, plate_y - 52], color=DIM, lw=3)
    ax.text(cx0 + 18, plate_y - 30, "drag cell\n+ wire stinger\n(lift cell the same,\nnormal to the page)",
            fontsize=6.8, color=INK, va="center")
    bx0, by0 = -200, plate_y - 75
    ax.add_patch(Rectangle((bx0, by0), 495, -tp - by0, fill=False, ec=DIM, ls="--", lw=1))
    ax.text(bx0 + 4, by0 + 5, "sealed balance box; Nano and 2 × HX711 on the ground frame; USB to the host",
            fontsize=6.8, color=DIM)
    ax.set_xlim(-285, 300)
    ax.set_ylim(by0 - 8, H + 22)
    ax.set_title("Side view, floor mount, span vertical (schematic; mm)", fontsize=9, color=NAVY, loc="left")

    # top views: alpha and lift convention, true section outline
    pts = geo["_outline"]
    cx, cy = geo["_outline_c"]
    rot = math.radians(4.76364)
    R0 = np.array([[math.cos(rot), -math.sin(rot)], [math.sin(rot), math.cos(rot)]])
    ob = (R0 @ (pts - [cx, cy]).T).T * 1e3                   # body frame, mm
    for k, a in enumerate((0, 90, 180, 270)):
        axt = fig.add_axes([0.60 + 0.20 * (k % 2), 0.47 - 0.45 * (k // 2), 0.19, 0.40])
        axt.set_aspect("equal")
        axt.axis("off")
        ar = math.radians(a)
        R = np.array([[math.cos(ar), -math.sin(ar)], [math.sin(ar), math.cos(ar)]])
        pv = (R @ np.column_stack([ob[:, 0], -ob[:, 1]]).T).T   # seen from above: y_body down
        axt.add_patch(Circle((0, 0), N["geometry"]["turntable_min_d_m"] * 1e3 / 2 + 8, fc=WASH, ec=LINE))
        axt.add_patch(Polygon(pv, closed=True, fc=GOLD, ec=GOLDDK, lw=1))
        axt.plot(*pv[0], "o", ms=3.2, color=FAULT)
        axt.annotate("", xy=(-18, 46), xytext=(-46, 46), arrowprops=dict(arrowstyle="-|>", color=KEANEY, lw=1.6))
        axt.text(-46, 50, "U", fontsize=8, color=KEANEY, weight="bold")
        axt.annotate("", xy=(44, -36), xytext=(44, -10), arrowprops=dict(arrowstyle="-|>", color=OK, lw=1.6))
        axt.text(34, -48, "+L", fontsize=8, color=OK, weight="bold")
        axt.text(-46, -48, f"α = {a}°", fontsize=9, color=NAVY, weight="bold")
        axt.set_xlim(-50, 50)
        axt.set_ylim(-52, 58)
    fig.text(0.60, 0.985, "Seen from above (from the free end); near end down in the sleeve.\n"
             "α increases as the blade turns counter-clockwise. +L is 90° clockwise\n"
             "from U: to the right looking downstream. Red dot: tip A (end of the long leg).",
             fontsize=7.4, color=INK, va="top")
    fig.savefig(HERE / "section_test_concept.png", dpi=150)
    plt.close(fig)


def fig_loads(N):
    fig, axs = plt.subplots(1, 2, figsize=(8.6, 3.5), dpi=150)
    Uf = np.linspace(9.5, 39, 120)
    S = N["geometry"]["S_m2"]
    qf = 0.5 * RHO * Uf ** 2
    c = N["cfd"]
    drag = [("α 0, high-drag state", c["a0_high"], NAVY), ("α 0, low-drag state", c["a0_low"], KEANEY),
            ("α 90", c["a90"]["Cd"], GOLDDK), ("α 180", c["a180"]["Cd"], OK)]
    for lab, cd, col in drag:
        axs[0].fill_between(Uf, cd[0] * qf * S, cd[1] * qf * S, color=col, alpha=0.35, lw=0, label=lab)
    lift = [("α 0", c["a0"]["Cl"], NAVY), ("α 90", c["a90"]["Cl"], GOLDDK), ("α 180", c["a180"]["Cl"], OK)]
    for lab, cl, col in lift:
        lo, hi = sorted((abs(cl[0]), abs(cl[1])))
        if cl[0] * cl[1] < 0:
            lo = 0.0
        axs[1].fill_between(Uf, lo * qf * S, hi * qf * S, color=col, alpha=0.35, lw=0, label=lab)
    axs[1].fill_between(Uf, 0, c["max_absCl"] * qf * S, color=DIM, alpha=0.10, lw=0,
                        label=f"any α (|Cl| ≤ {c['max_absCl']:.2f}, α {c['max_absCl_alpha']:.0f})")
    FS = CHOSEN_KG * G0
    for ax in axs:
        ax.axhline(FS, color=FAULT, lw=1.2)
        ax.axhline(0.6 * FS, color=FAULT, lw=0.9, ls="--")
        ax.text(10, FS * 1.02, f"{CHOSEN_KG} kg cell: full scale", fontsize=7, color=FAULT)
        ax.text(10, 0.6 * FS * 1.03, "60 % of full scale", fontsize=7, color=FAULT)
        ax.set_xlabel("wind speed U (m/s)", fontsize=8, color=INK)
        for rpm in SET_RPM:
            ax.axvline(float(rpm_to_mps(rpm)), color=LINE, lw=0.8, zorder=0)
        ax.set_xlim(9.5, 39)
        ax.set_ylim(0, 32)
        style(ax)
        ax.legend(fontsize=6.5, frameon=False, loc="upper left", bbox_to_anchor=(0.0, 0.9))
    axs[0].set_ylabel("mean drag D (N)", fontsize=8, color=INK)
    axs[1].set_ylabel("mean |lift| (N)", fontsize=8, color=INK)
    fig.suptitle(f"Expected loads on the {N['geometry']['b_e_m']*1e3:.0f} mm exposed span: 2D CFD "
                 f"coefficients (healthy runs), ρ {RHO} kg/m³. Grey lines: proposed fan set points.",
                 fontsize=8, color=NAVY)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(HERE / "section_test_loads.png", dpi=150)
    plt.close(fig)


def fig_frequencies(N):
    fig, ax = plt.subplots(figsize=(6.6, 3.7), dpi=150)
    Uf = np.linspace(9.5, 39, 100)
    c = N["cfd"]
    for lab, st, col in (("α 0 shedding (CFD St)", c["St_a0"], NAVY),
                         ("α 180 shedding (CFD St)", c["St_a180"], OK),
                         ("α 90 shedding (maxCo-5 runs only)", c["St_a90_maxCo5"], GOLDDK)):
        ax.fill_between(Uf, st[0] * Uf / C_REF, st[1] * Uf / C_REF + 1.5, color=col, alpha=0.35, lw=0,
                        label=lab)
    m = N["modes"]
    for key, lab, col in (("cantilever_full_weak_Hz", "full 245 mm blade as a cantilever", FAULT),
                          ("cantilever_exposed_weak_Hz",
                           f"{N['geometry']['b_e_m']*1e3:.0f} mm exposed span (recommended)", KEANEY)):
        lo, hi = m[key]
        ax.axhspan(lo, hi, color=col, alpha=0.20, lw=0)
        ax.text(38.7, hi + 5, lab + ": 1st bending", fontsize=7, color=col, ha="right")
    lo, hi = N["balance"]["f1_Hz"]
    ax.axhspan(lo, hi, facecolor="none", edgecolor=DIM, hatch="///", lw=0)
    ax.text(23.5, 14, "hatched: balance first mode (estimate; measure by tap test)", fontsize=6.8, color=DIM)
    ax.axhline(N["shedding"]["imu_nyquist_Hz"], color=DIM, lw=0.9, ls=":")
    ax.text(38.7, N["shedding"]["imu_nyquist_Hz"] + 6, f"IMU Nyquist ({IMU_ODR} Hz output rate)",
            fontsize=7, color=DIM, ha="right")
    ax.set_xlabel("wind speed U (m/s)", fontsize=8, color=INK)
    ax.set_ylabel("frequency (Hz)", fontsize=8, color=INK)
    ax.set_xlim(9.5, 39)
    ax.set_ylim(0, 620)
    style(ax)
    ax.legend(fontsize=6.5, frameon=False, loc="upper left", bbox_to_anchor=(0.0, 1.0))
    ax.set_title("Shedding f = St·U/c_ref against structural modes (PLA E 2.3–3.5 GPa, rigid root)",
                 fontsize=8, color=NAVY, loc="left")
    fig.tight_layout()
    fig.savefig(HERE / "section_test_frequencies.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    out = main()
    g = out["geometry"]
    print(f"exposed span {g['b_e_m']*1e3:.2f} mm, S {g['S_m2']*1e4:.2f} cm2; "
          f"max mean drag {out['loads']['D_mean_max_N']:.1f} N; numbers -> section_test_numbers.json")
