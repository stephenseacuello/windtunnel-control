#!/usr/bin/env python3
"""
section_balance_analyze.py — Cd and Cl of the blade section, with uncertainty.

    python scripts/section_balance_analyze.py logs/section_balance/<session> --rig rig.yaml
    python scripts/section_balance_analyze.py <session> <session> ... --rig rig.json --out <dir>
    python scripts/section_balance_analyze.py --write-rig-template rig.yaml

Reads the folders scripts/section_balance_logger.py writes and produces, in --out:

    dwells.csv         one row per dwell: mean counts, the zero used, forces, q, Cd, Cl
    coefficients.csv   per blade set, alpha and wind speed: Cd and Cl with 95 % intervals
    differences.csv    each set minus the reference set (Plain) at the same alpha and speed
    calibration.json   K, its covariance, residuals and cross-talk
    bursts.csv         accelerometer peaks and their Strouhal numbers
    summary.txt        what was applied, what was assumed, what was not corrected
    *.png              Cd and Cl against alpha and U with the CFD; differences; spectra

═══════════════════════════════════════════════════════════════════════════
THE MEASUREMENT MODEL, IN ORDER
═══════════════════════════════════════════════════════════════════════════
1. Dwell means of the raw counts, after `settle_s`, using only conversions
   flagged fresh; a dwell with a saturated row is dropped. Standard error by
   batch means (10 batches), because 10 Hz samples of a turbulent force are
   correlated and the plain s/sqrt(n) understates the error.
2. Calibration: counts = a + d t + K F per channel, least squares over the
   calibration dwells. K's off-diagonal terms are the cross-talk. a and d are
   discarded: zeros come from step 3.
3. Zero: the wind-off dwells of the same session, set, mount and alpha, the
   one before and the one after, interpolated linearly in time. One-sided
   zeros are used with a drift allowance; a dwell with no zero at its alpha
   is excluded, because the zero moves with alpha (the slice's weight acts at
   a different arm).
4. F = K^-1 (counts - zero). With `balance_frame: body` the axes turn with the
   slice and are rotated back to the wind.
5. Support tare: the support-only dwells at the same speed (and alpha, if
   the support turns with it), scaled by the dynamic-pressure ratio, are
   subtracted. Interference between support and slice is not in a tare.
6. q = rho U^2 / 2. U from a measured column (q_pa or U_meas_ms) if the run
   sheet has one, otherwise the fan label. rho from rho_kg_m3, otherwise the
   reference thermometer and the pressure (reference barometer, else the
   board's LPS22HB), otherwise 1.204 assumed.
7. Cd = D / (q S), Cl = L / (q S), S = c_ref x span, c_ref = 48.0 mm as in the
   CFD (cfd/section2d/README.md). Cl follows the CFD convention: positive
   along liftDir, 90 deg counter-clockwise from the wind seen from +z_body.
   `lift_sign` maps the balance's lift axis onto it.
8. Blockage, Maskell type, only when the test-section area is given:
   q_c / q = 1 + theta (D / q) / C with D the drag that measurement saw.
   Each measurement is corrected with its own drag (the wind dwell with slice
   plus support, the support-only dwell with the support's) and the tare is
   subtracted after, so the support's force is removed at the right q. With
   no area, nothing is applied and summary.txt says what the correction would
   be for a range of areas.

═══════════════════════════════════════════════════════════════════════════
UNCERTAINTY
═══════════════════════════════════════════════════════════════════════════
Monte Carlo through the whole chain, split into a SYSTEMATIC part shared by
every dwell that uses the same input (K, the fan calibration, rho per
session, span per set, theta) and a RANDOM part per dwell (dwell noise, zero
noise and drift allowance, set-point repeatability). Values are the nominal
plus both parts; for repeated dwells the random part is scaled up to the
observed repeat scatter when that is larger. Differences between sets are
taken draw by draw, so what both sets share (the calibration, the fan
calibration) cancels as far as it really does. Intervals are 2.5-97.5 %.

Not propagated, and listed in summary.txt: the alpha setting, support
interference, 3D and end effects of a finite slice, streamline curvature,
solid blockage, and whichever 2D flow state the slice takes at alpha 0.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from section_balance_logger import (FLAG_DRAG_FRESH, FLAG_DRAG_SAT,   # noqa: E402
                                    FLAG_LIFT_FRESH, FLAG_LIFT_SAT, G_STD,
                                    BalanceError, fit_k, read_meta_csv)

R_DRY = 287.05

RIG_DEFAULTS = {
    "span_m": None,
    "span_m_by_set": {},
    "u_span_m": 0.0002,
    "c_ref_m": 0.048,
    "lift_sign": 1,
    "lift_sign_by_set": {},
    "balance_frame": "wind",
    "body_frame_alpha0_deg": 0.0,
    "test_section": {"width_m": None, "height_m": None, "area_m2": None},
    "maskell_theta": 1.68,       # docs/12_section_force_test.md 5.4 (0.96-2.40 band)
    "u_maskell_theta": 0.41,
    "extra_drag_area_m2": 0.0,
    "settle_s": 2.0,
    "u_U_sys_rel": 0.05,
    "u_U_rand_rel": 0.005,
    "u_U_meas_rel": 0.01,
    "u_q_meas_rel": 0.01,
    "rho_kg_m3": None,
    "u_rho_rel": 0.01,
    "air_temp_c_default": None,
    "support_tare": "auto",
    "reference_set": "Plain",
    "cfd_polars": "cfd/section2d/results/section_polars.csv",
    "cfd_quality": "cfd/analysis/2026-10-15/out/section_case_quality.csv",
    "cfd_level": "medium",
    "cfd_tu_pct": 1.0,
    "draws": 4000,
    "seed": 1,
    "nu_m2_s": 1.516e-5,
    "burst_band_hz": [15.0, 450.0],
}

RIG_TEMPLATE = """\
# Rig sheet for scripts/section_balance_analyze.py. Units SI.
# Provenance: say for each value whether it is measured, calculated or assumed.

span_m: null              # MEASURED exposed span (calipers), required; nominal 0.1201
                          # for the sleeve mount (docs/12_section_force_test.md 1.2)
span_m_by_set: {}         # per set, e.g. {Plain: 0.1002, FS0.20: 0.0998}
u_span_m: 0.0002          # calipers, assumed
c_ref_m: 0.048            # CFD reference chord (definition, cfd/section2d/README.md)

lift_sign: 1              # +1 if the balance's +lift axis is the CFD liftDir:
                          # at alpha 90 (wind from tip A to tip B) liftDir points
                          # from the convex face toward the open side of the cup
lift_sign_by_set: {}      # only if a slice was mounted the other way up
balance_frame: wind       # wind: balance fixed, slice turns on it; body: balance turns with the slice
body_frame_alpha0_deg: 0  # body frame only: alpha at which the drag axis is along the wind

test_section:             # NOT YET MEASURED (cfd/MEASUREMENTS_NEEDED.md section 2)
  width_m: null
  height_m: null
  area_m2: null           # or give the area directly; null = no blockage correction
maskell_theta: 1.68       # end-plated 120.1 mm piece: theta lies in 0.96 (2D wake) to
u_maskell_theta: 0.41     # 2.40 (free tip); mean and s.d. of that band, drawn as a normal
                          # (docs/12_section_force_test.md 5.4). For each bound, run with
                          # --theta 0.96 or --theta 2.40 and u_maskell_theta 0.
extra_drag_area_m2: 0.0   # drag area of NON-metric parts in the flow (shield, cables):
                          # they block the tunnel but the balance does not feel them

settle_s: 2.0             # dropped from the start of every dwell
u_U_sys_rel: 0.05         # fan calibration, assumed: measured to 700 rpm only
u_U_rand_rel: 0.005       # set-point repeatability per dwell, assumed
u_U_meas_rel: 0.01        # if the run sheet carries U_meas_ms
u_q_meas_rel: 0.01        # if the run sheet carries q_pa
rho_kg_m3: null           # force a density; otherwise from the session's air readings
u_rho_rel: 0.01           # thermometer, barometer and the dry-air formula, assumed
air_temp_c_default: null  # used when a session has no `air` reading

support_tare: auto        # auto | by_U | by_U_alpha | none
reference_set: Plain

cfd_polars: cfd/section2d/results/section_polars.csv
cfd_quality: cfd/analysis/2026-10-15/out/section_case_quality.csv
cfd_level: medium
cfd_tu_pct: 1.0

draws: 4000
seed: 1
nu_m2_s: 1.516e-5         # as the CFD, for Re only
burst_band_hz: [15, 450]
"""

# Fixed per blade set, never by rank: a set keeps its colour whatever else is
# plotted. Slots 1-3 of the validated categorical palette go to the three sets
# the comparisons are about.
SET_COLOURS = {"plain": "#2a78d6", "fs0.10": "#eb6834", "fs0.20": "#1baf7a",
               "fs0.05": "#eda100", "fs0.40": "#e87ba4", "fs0.80": "#008300"}
SPARE_COLOURS = ["#4a3aa7", "#e34948"]
INK, INK2, MUTED, GRID, AXIS, SURFACE = ("#0b0b0b", "#52514e", "#898781",
                                         "#e1e0d9", "#c3c2b7", "#fcfcfb")


# ── configuration ─────────────────────────────────────────────────────────

def load_rig(path=None, overrides=None):
    rig = json.loads(json.dumps(RIG_DEFAULTS))
    user = {}
    if path:
        text = Path(path).read_text()
        if str(path).endswith((".yaml", ".yml")):
            try:
                import yaml
            except ImportError:
                raise SystemExit("\n  PyYAML is not installed: pip install pyyaml, "
                                 "or give the rig sheet as .json\n")
            user = yaml.safe_load(text) or {}
        else:
            user = json.loads(text)
    for k, v in {**user, **(overrides or {})}.items():
        if k.startswith("_") or v is None and k not in rig:
            continue
        if isinstance(v, dict) and isinstance(rig.get(k), dict):
            rig[k].update({kk: vv for kk, vv in v.items() if not kk.startswith("_")})
        else:
            rig[k] = v
    ts = rig["test_section"]
    if not ts.get("area_m2") and ts.get("width_m") and ts.get("height_m"):
        ts["area_m2"] = float(ts["width_m"]) * float(ts["height_m"])
    return rig


def _key(name):
    return str(name).strip().lower().replace(" ", "")


def _by_set(rig, field, set_name, default):
    tab = {_key(k): v for k, v in (rig.get(field) or {}).items()}
    return tab.get(_key(set_name), default)


def set_colour(name, order):
    k = _key(name)
    if k in SET_COLOURS:
        return SET_COLOURS[k]
    others = [n for n in order if _key(n) not in SET_COLOURS]
    i = others.index(name) if name in others else 0
    return SPARE_COLOURS[i] if i < len(SPARE_COLOURS) else MUTED


def same_alpha(a, b, tol=0.5):
    return abs(((float(a) - float(b) + 180.0) % 360.0) - 180.0) < tol


def _f(x, default=None):
    try:
        if x is None or str(x).strip() == "":
            return default
        return float(x)
    except ValueError:
        return default


# ── loading ───────────────────────────────────────────────────────────────

def load_sessions(folders):
    dwells = []
    for folder in folders:
        folder = Path(folder)
        if not (folder / "runsheet.csv").exists():
            raise SystemExit(f"\n  {folder} has no runsheet.csv — is it a session folder?\n")
        _, run = read_meta_csv(folder / "runsheet.csv")
        _, tr = read_meta_csv(folder / "trace.csv")
        rows = collections.defaultdict(list)
        for r in tr:
            rows[r["dwell"]].append(r)
        for r in run:
            rr = rows.get(r["dwell"], [])
            use = str(r.get("use", "1")).strip()
            dwells.append({
                **r,
                "session": folder.name, "folder": folder,
                "id": f"{folder.name}#{r['dwell']}",
                "kind": r["kind"].strip(), "set": r["set"].strip(),
                "mount": int(_f(r.get("mount"), 1)),
                "alpha": _f(r.get("alpha_deg"), 0.0),
                "U_nom": _f(r.get("U_nom_ms"), 0.0),
                "use": use not in ("0", "false", "no", "n"),
                "t": np.array([float(x["t_s"]) for x in rr]),
                "drag": np.array([float(x["drag_counts"]) for x in rr]),
                "lift": np.array([float(x["lift_counts"]) for x in rr]),
                "flags": np.array([int(x["flags"]) for x in rr], int),
                "status": [],
            })
    return dwells


# ── step 1: dwell statistics ──────────────────────────────────────────────

def batch_se(x, nb=10):
    """Standard error of the mean by batch means; falls back to s/sqrt(n)."""
    n = len(x)
    if n < 2:
        return float("nan")
    nb = min(nb, n // 5)
    if nb >= 3:
        means = [b.mean() for b in np.array_split(x, nb)]
        return float(np.std(means, ddof=1) / math.sqrt(nb))
    return float(np.std(x, ddof=1) / math.sqrt(n))


def dwell_stats(d, settle_s):
    """Fills mean, se, t_mid, n and drift for one dwell. False if unusable."""
    if d["kind"] == "burst":
        return False
    if len(d["t"]) == 0:
        d["status"].append("no rows")
        return False
    keep = (d["t"] - d["t"][0]) >= settle_s
    if np.any(d["flags"][keep] & (FLAG_DRAG_SAT | FLAG_LIFT_SAT)):
        d["status"].append("saturated")
        return False
    mean, se, n, drift = [], [], [], []
    for ch, bit in (("drag", FLAG_DRAG_FRESH), ("lift", FLAG_LIFT_FRESH)):
        m = keep & ((d["flags"] & bit) != 0)
        x = d[ch][m]
        if len(x) < 5:
            d["status"].append(f"too few {ch} samples after settle")
            return False
        mean.append(float(x.mean()))
        se.append(batch_se(x))
        n.append(int(len(x)))
        h = len(x) // 2
        drift.append(float(x[h:].mean() - x[:h].mean()))
    d["mean"] = np.array(mean)
    d["se"] = np.array(se)
    d["n"] = n
    d["drift_halves"] = np.array(drift)
    d["t_mid"] = float(d["t"][keep].mean())
    # A drift between the halves larger than 4 standard errors means the
    # dwell did not sit still: a zero still drifting, or, at alpha 0, the
    # flow switching between states. Reported, not removed.
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.abs(d["drift_halves"]) / (2 * d["se"])
    if np.any(ratio > 4):
        d["status"].append("unsteady (halves differ > 4 se)")
    return True


# ── step 2: calibration ───────────────────────────────────────────────────

def calibration_points(dwells, g=G_STD):
    pts = []
    for d in dwells:
        if d["kind"] != "cal" or not d["use"] or "mean" not in d:
            continue
        m = _f(d.get("mass_g"), 0.0)
        sgn = -1.0 if str(d.get("direction", "+")).strip() == "-" else 1.0
        F = m / 1000.0 * g * sgn
        ax = str(d.get("axis", "")).strip().lower()
        if ax not in ("d", "l"):
            d["status"].append("calibration dwell without an axis")
            continue
        pts.append({"F_drag": F if ax == "d" else 0.0, "F_lift": F if ax == "l" else 0.0,
                    "t_s": d["t_mid"], "drag_counts": d["mean"][0],
                    "lift_counts": d["mean"][1], "dwell": d["id"], "group": d["session"]})
    return pts


def get_calibration(dwells, cal_file=None):
    if cal_file:
        c = json.loads(Path(cal_file).read_text())
        c.setdefault("source", f"file {cal_file}")
        return c
    pts = calibration_points(dwells)
    if not pts:
        for folder in sorted({d["folder"] for d in dwells}):
            f = folder / "calibration_fit.json"
            if f.exists():
                c = json.loads(f.read_text())
                c["source"] = f"{f} (the logger's fit; no calibration dwells given)"
                return c
        raise SystemExit("\n  no calibration: these sessions have no `cal` dwells and no "
                         "calibration_fit.json.\n  Pass --calibration <calibration.json> "
                         "or --cal-sessions <folder>.\n")
    try:
        c = fit_k(pts)
    except BalanceError as e:
        raise SystemExit(f"\n  calibration: {e}\n")
    c["source"] = f"fitted here from {len(pts)} calibration dwells"
    c["points"] = [{k: (float(v) if isinstance(v, (float, np.floating)) else v)
                    for k, v in p.items()} for p in pts]
    return c


# ── step 3: zeros ─────────────────────────────────────────────────────────

def assign_zeros(dwells):
    """Pre and post zero for each wind/support dwell; drift allowance."""
    zeros = [d for d in dwells if d["kind"] == "zero" and d["use"] and "mean" in d]
    rates = []
    by = collections.defaultdict(list)
    for z in zeros:
        by[(z["session"], z["set"], z["mount"])].append(z)
    for group in by.values():
        group.sort(key=lambda z: z["t_mid"])
        for a, b in zip(group, group[1:]):
            if same_alpha(a["alpha"], b["alpha"]) and b["t_mid"] > a["t_mid"]:
                rates.append(np.abs(b["mean"] - a["mean"]) / (b["t_mid"] - a["t_mid"]))
    typical_rate = np.median(np.array(rates), axis=0) if rates else None

    for d in dwells:
        if d["kind"] not in ("wind", "support") or not d["use"] or "mean" not in d:
            continue
        cands = [z for z in by.get((d["session"], d["set"], d["mount"]), [])
                 if same_alpha(z["alpha"], d["alpha"])]
        before = [z for z in cands if z["t_mid"] < d["t_mid"]]
        after = [z for z in cands if z["t_mid"] > d["t_mid"]]
        zb = max(before, key=lambda z: z["t_mid"]) if before else None
        za = min(after, key=lambda z: z["t_mid"]) if after else None
        if zb is not None and za is not None:
            w = (d["t_mid"] - zb["t_mid"]) / (za["t_mid"] - zb["t_mid"])
            # Linear in time is exact for a linear drift. The allowance for a
            # bowed one is assumed: at most half the pre-post change, largest
            # mid-way, zero at either zero.
            nl = np.abs(za["mean"] - zb["mean"]) * 2 * w * (1 - w) / math.sqrt(3)
            d["zero"] = {"before": zb, "after": za, "w": w, "u_nl": nl, "kind": "bracketed"}
        elif zb is not None or za is not None:
            z = zb if zb is not None else za
            gap = abs(d["t_mid"] - z["t_mid"])
            if typical_rate is not None:
                nl = typical_rate * gap
                d["status"].append("one-sided zero (drift allowance from the session)")
            else:
                nl = np.zeros(2)
                d["status"].append("one-sided zero, drift unknown")
            d["zero"] = {"before": z, "after": z, "w": 0.0, "u_nl": nl, "kind": "one-sided"}
        else:
            d["status"].append("EXCLUDED: no wind-off zero at this alpha and mount")
            d["excluded"] = True
    return typical_rate


# ── step 5: support tare ──────────────────────────────────────────────────

def assign_support(dwells, mode):
    sup = [d for d in dwells if d["kind"] == "support" and d["use"] and "zero" in d]
    if mode == "auto":
        # Support dwells at more than one alpha mean the support turns with
        # the slice, so its tare is matched on alpha as well as speed.
        alphas = {round(s["alpha"] % 360.0, 1) for s in sup}
        mode = "none" if not sup else ("by_U_alpha" if len(alphas) > 1 else "by_U")
    for d in dwells:
        if d["kind"] != "wind" or "zero" not in d:
            continue
        if mode == "none":
            d["support"] = None
            continue
        c = [s for s in sup if abs(s["U_nom"] - d["U_nom"]) <= 0.3]
        if mode == "by_U_alpha":
            ca = [s for s in c if same_alpha(s["alpha"], d["alpha"])]
            if ca:
                c = ca
            elif c:
                d["status"].append("support tare from another alpha")
        same = [s for s in c if s["session"] == d["session"]]
        c = same or c
        if not c:
            d["support"] = None
            d["status"].append("NO SUPPORT TARE at this speed: Cd includes the support")
            continue
        if not same:
            d["status"].append("support tare from another session")
        d["support"] = min(c, key=lambda s: abs(s["t_mid"] - d["t_mid"]))
    return mode


# ── steps 4, 6-8: the Monte Carlo chain ───────────────────────────────────

def air_density(d, rig):
    """(rho, u_rel, source)."""
    rho = _f(d.get("rho_kg_m3"))
    if rho:
        return rho, rig["u_rho_rel"], "run sheet rho_kg_m3"
    if rig.get("rho_kg_m3"):
        return float(rig["rho_kg_m3"]), rig["u_rho_rel"], "rig sheet rho_kg_m3"
    T = _f(d.get("air_temp_ref_c"), _f(rig.get("air_temp_c_default")))
    p = _f(d.get("pressure_ref_pa"), _f(d.get("board_pressure_pa")))
    if T is not None and p:
        src = "reference thermometer, " + ("reference barometer" if _f(d.get("pressure_ref_pa"))
                                          else "board LPS22HB pressure")
        return p / (R_DRY * (T + 273.15)), rig["u_rho_rel"], src + ", dry air"
    if p:
        return p / (R_DRY * 293.15), math.hypot(rig["u_rho_rel"], 5.0 / 293.15), \
            "board pressure, 20 +- 5 C assumed (no thermometer reading)"
    return 1.204, 0.03, "1.204 assumed (no air readings)"


def to_wind_frame(f_drag_axis, f_lift_axis, alpha_deg, lift_sign=1.0, frame="wind",
                  alpha0_deg=0.0):
    """
    Balance-axis forces to (D, L) in the wind frame, L positive along the CFD
    liftDir (90 deg counter-clockwise from the wind, seen from +z_body).

    `lift_sign` first makes the lift axis point along liftDir at alpha0. In
    the `body` frame the axes then turn with the slice: raising alpha turns
    the slice CLOCKWISE seen from +z_body (alpha is the wind's angle measured
    counter-clockwise in body axes), so after a turn of a = alpha - alpha0 a
    pure drag D reads D cos a on the drag axis and D sin a on the lift axis.
    """
    fd = f_drag_axis
    fl = lift_sign * f_lift_axis
    if frame == "wind":
        return fd, fl
    if frame != "body":
        raise SystemExit(f"\n  balance_frame must be 'wind' or 'body', not {frame!r}\n")
    a = math.radians(float(alpha_deg) - float(alpha0_deg))
    return fd * math.cos(a) + fl * math.sin(a), -fd * math.sin(a) + fl * math.cos(a)


def wind_speed(d, rig):
    """(U nominal, kind) — kind: 'fan', 'U_meas' or 'q_meas'."""
    q = _f(d.get("q_pa"))
    if q:
        return None, "q_meas"
    U = _f(d.get("U_meas_ms"))
    if U:
        return U, "U_meas"
    return d["U_nom"], "fan"


class Chain:
    """
    Every measured quantity of every dwell as N Monte Carlo draws, split
    into a systematic part (shared) and a random part (per dwell).
    """

    def __init__(self, dwells, cal, rig):
        self.rig = rig
        self.N = int(rig["draws"])
        self.rng = np.random.default_rng(int(rig["seed"]))
        N, rng = self.N, self.rng
        self.K = np.array(cal["K"], float)
        Kd = np.empty((N, 2, 2))
        for ch in range(2):
            cov = np.array(cal.get("cov_rows", [[[0, 0], [0, 0]]] * 2)[ch], float)
            Kd[:, ch, :] = rng.multivariate_normal(self.K[ch], cov, N, method="eigh")
        self.Kd = Kd
        self.eps = {"U_fan": rng.normal(0, rig["u_U_sys_rel"], N),
                    "U_meas": rng.normal(0, rig["u_U_meas_rel"], N),
                    "q_meas": rng.normal(0, rig["u_q_meas_rel"], N),
                    "theta": rng.normal(0, rig["u_maskell_theta"], N)}
        self.rho_eps, self.span_eps = {}, {}
        self.noise, self.nl, self.urand = {}, {}, {}
        for d in dwells:
            if "mean" in d:
                self.noise[d["id"]] = rng.normal(0, 1, (N, 2)) * d["se"]
            if "zero" in d:
                self.nl[d["id"]] = rng.normal(0, 1, (N, 2)) * d["zero"]["u_nl"]
                self.urand[d["id"]] = rng.normal(0, rig["u_U_rand_rel"], N)
            if d["kind"] in ("wind", "support") and "zero" in d:
                rho, u, _ = air_density(d, rig)
                if d["session"] not in self.rho_eps:
                    self.rho_eps[d["session"]] = rng.normal(0, 1, N)
                d["rho"], d["u_rho_rel"] = rho, u
        for s in {d["set"] for d in dwells}:
            span = _by_set(rig, "span_m_by_set", s, rig["span_m"])
            u = float(rig["u_span_m"]) / float(span) if span else 0.0
            self.span_eps[s] = rng.normal(0, u, N)

    def _counts(self, d, sys_on, rand_on):
        z = d["zero"]
        R = d["mean"] + rand_on * self.noise[d["id"]]
        zb, za, w = z["before"], z["after"], z["w"]
        Zb = zb["mean"] + rand_on * self.noise[zb["id"]]
        Za = za["mean"] + rand_on * self.noise[za["id"]]
        Z = (1 - w) * Zb + w * Za + rand_on * self.nl[d["id"]]
        return R - Z

    def forces(self, d, sys_on, rand_on):
        """(D, L) in the wind frame, CFD lift sign, newtons, shape (N,)."""
        dR = self._counts(d, sys_on, rand_on)
        K = self.Kd if sys_on else np.broadcast_to(self.K, (self.N, 2, 2))
        F = np.linalg.solve(K, dR[..., None])[..., 0]
        sign = float(_by_set(self.rig, "lift_sign_by_set", d["set"], self.rig["lift_sign"]))
        return to_wind_frame(F[:, 0], F[:, 1], d["alpha"], sign, self.rig["balance_frame"],
                             float(self.rig["body_frame_alpha0_deg"]))

    def q(self, d, sys_on, rand_on):
        rho = d["rho"] * (1 + sys_on * d["u_rho_rel"] * self.rho_eps[d["session"]])
        U, kind = wind_speed(d, self.rig)
        if kind == "q_meas":
            qv = float(d["q_pa"]) * (1 + sys_on * self.eps["q_meas"]) \
                * (1 + rand_on * self.urand[d["id"]]) ** 2
            return qv, np.sqrt(2 * qv / rho)
        e = self.eps["U_fan"] if kind == "fan" else self.eps["U_meas"]
        Uv = U * (1 + sys_on * e) * (1 + rand_on * self.urand[d["id"]])
        return 0.5 * rho * Uv ** 2, Uv

    def blockage(self, D, q, sys_on):
        """Maskell: q_c / q = 1 + theta (D/q + non-metric drag area) / C; 1 without C."""
        C = self.rig["test_section"].get("area_m2")
        if not C:
            return np.ones(self.N)
        theta = float(self.rig["maskell_theta"]) + sys_on * self.eps["theta"]
        extra = float(self.rig.get("extra_drag_area_m2") or 0.0)
        return 1 + theta * (D / q + extra) / float(C)

    def evaluate(self, d, sys_on, rand_on):
        """
        Everything for one wind dwell, as draws.

        Each measurement is corrected with ITS OWN drag: the wind dwell with
        the total (slice + support) it measured, the support-only dwell with
        the support's. Then the tare is subtracted. Subtracting first and
        correcting after would leave the support's force at the wrong q, a
        bias of theta (CdA_support) Cd / C (1.5 % at alpha 0 in the
        simulator's tunnel).
        """
        Dt, Lt = self.forces(d, sys_on, rand_on)
        q, U = self.q(d, sys_on, rand_on)
        f = self.blockage(Dt, q, sys_on)
        Dc, Lc = Dt / f, Lt / f
        Du, Lu = Dt, Lt
        s = d.get("support")
        if s is not None:
            Sd, Sl = self.forces(s, sys_on, rand_on)
            qs, _ = self.q(s, sys_on, rand_on)
            fs = self.blockage(Sd, qs, sys_on)
            Dc, Lc = Dc - Sd / fs * q / qs, Lc - Sl / fs * q / qs
            Du, Lu = Du - Sd * q / qs, Lu - Sl * q / qs
        span = float(_by_set(self.rig, "span_m_by_set", d["set"], self.rig["span_m"]))
        S = float(self.rig["c_ref_m"]) * span * (1 + sys_on * self.span_eps[d["set"]])
        return {"D": Dc, "L": Lc, "D_total": Dt, "q": q, "U": U,
                "Cd_u": Du / (q * S), "Cl_u": Lu / (q * S),
                "Cd": Dc / (q * S), "Cl": Lc / (q * S), "blockage": f}

    def decompose(self, d):
        nom = {k: float(v[0]) for k, v in self.evaluate(d, 0.0, 0.0).items()}
        sys_ = self.evaluate(d, 1.0, 0.0)
        rnd = self.evaluate(d, 0.0, 1.0)
        return nom, {k: sys_[k] - nom[k] for k in sys_}, {k: rnd[k] - nom[k] for k in rnd}


def summarise(nom, dsys, drand):
    full = nom + dsys + drand
    lo, hi = np.percentile(full, [2.5, 97.5])
    return {"value": nom, "u": float(np.std(dsys + drand)), "u_sys": float(np.std(dsys)),
            "u_rand": float(np.std(drand)), "lo": float(lo), "hi": float(hi)}


# ── CFD ───────────────────────────────────────────────────────────────────

def load_cfd(rig):
    """Healthy CFD runs at the rig's mesh level and Tu, or [] with a reason."""
    p = ROOT / rig["cfd_polars"]
    if not p.exists():
        return [], f"{rig['cfd_polars']} not found: no CFD overlay"
    with open(p, newline="") as f:
        rows = list(csv.DictReader(f))
    q = ROOT / rig["cfd_quality"]
    note = "healthy = not flagged in " + rig["cfd_quality"]
    flagged, st_status = set(), {}
    if q.exists():
        with open(q, newline="") as f:
            for r in csv.DictReader(f):
                if str(r.get("corrupted", "")).strip() == "True":
                    flagged.add(r["name"])
                st_status[r["name"]] = r.get("St_status", "")
    else:
        note = f"{rig['cfd_quality']} not found: CFD runs NOT filtered for health"
    out = []
    for r in rows:
        if r["name"] in flagged:
            continue
        if str(r.get("level")) != str(rig["cfd_level"]):
            continue
        if abs(_f(r.get("Tu_body_pct"), -1) - float(rig["cfd_tu_pct"])) > 1e-6:
            continue
        # A Strouhal number only where the quality table found a clean peak;
        # a broadband or steady run has a "St" that is not a shedding frequency.
        clean = st_status.get(r["name"], "clean peak") == "clean peak"
        out.append({"name": r["name"], "alpha": float(r["alpha_deg"]),
                    "U": float(r["U_ms"]), "model": r["model"],
                    "maxCo": float(r["maxCo"]), "Cd": float(r["Cd_mean"]),
                    "Cl": float(r["Cl_mean"]), "St": _f(r.get("St")) if clean else None})
    return out, note + f"; {len(out)} runs at level {rig['cfd_level']}, Tu {rig['cfd_tu_pct']} %"


def cfd_near(cfd, U, alpha=None, tol=0.10):
    """CFD runs within 10 % of U (and at alpha, if given)."""
    out = [c for c in cfd if abs(c["U"] - U) <= tol * max(U, 1e-9)]
    if alpha is not None:
        out = [c for c in out if same_alpha(c["alpha"], alpha)]
    return out


# ── bursts ────────────────────────────────────────────────────────────────

def burst_spectrum(path):
    """(freqs, amplitude rss over axes in g, fs, jitter) — resampled first."""
    meta, rows = read_meta_csv(path)
    us = np.array([int(r["us"]) for r in rows], np.int64)
    if len(us) < 64:
        return None
    t = np.cumsum(np.r_[0, np.diff(us) % (2 ** 32)]) * 1e-6     # micros() wraps
    a = np.array([[float(r["ax_g"]), float(r["ay_g"]), float(r["az_g"])] for r in rows])
    if len(t) < 64 or t[-1] <= 0:
        return None
    fs = (len(t) - 1) / t[-1]
    grid = np.linspace(0, t[-1], len(t))
    win = np.hanning(len(t))
    amps = []
    for k in range(3):
        x = np.interp(grid, t, a[:, k])
        x = x - x.mean()
        # Hann coherent gain is 0.5: without it every amplitude reads half.
        amps.append(np.abs(np.fft.rfft(x * win)) * 2.0 / (len(x) * 0.5))
    f = np.fft.rfftfreq(len(t), 1.0 / fs)
    jitter = float(np.std(np.diff(t)) / np.mean(np.diff(t)))
    return f, np.sqrt(np.sum(np.square(amps), axis=0)), fs, jitter, meta


def analyse_bursts(dwells, rig, cfd):
    out = []
    lo_hz, hi_hz = [float(x) for x in rig["burst_band_hz"]]
    for d in dwells:
        if d["kind"] != "burst" or not d["use"] or not d.get("burst_file"):
            continue
        s = burst_spectrum(d["folder"] / d["burst_file"])
        if s is None:
            continue
        f, amp, fs, jitter, _ = s
        band = (f >= lo_hz) & (f <= min(hi_hz, 0.45 * fs))
        if not band.any():
            continue
        i = int(np.argmax(np.where(band, amp, -1)))
        floor = float(np.median(amp[band]))
        U = d["U_nom"]
        ref = sorted({(c["model"], c["maxCo"], round(c["St"], 4))
                      for c in cfd_near(cfd, U, d["alpha"]) if c.get("St")}) if U > 0 else []
        c_ref = float(rig["c_ref_m"])
        out.append({"dwell": d["id"], "set": d["set"], "mount": d["mount"],
                    "alpha_deg": d["alpha"], "U_nom_ms": U, "fs_hz": fs,
                    "jitter_frac": jitter, "f_peak_hz": float(f[i]),
                    "amp_peak_g": float(amp[i]),
                    "peak_over_median": float(amp[i] / floor) if floor else float("nan"),
                    "St_measured": float(f[i] * c_ref / U) if U > 0 else float("nan"),
                    "St_cfd": "; ".join(f"{m} maxCo {co:g}: {st:g}" for m, co, st in ref),
                    "f_expected_hz": "; ".join(f"{st * U / c_ref:.1f}" for _, _, st in ref),
                    "_spec": (f, amp)})
    return out


# ── the analysis ──────────────────────────────────────────────────────────

def analyse(folders, rig, cal_file=None, cal_folders=(), out_dir=None, plots=True,
            echo=print):
    if not rig.get("span_m") and not rig.get("span_m_by_set"):
        raise SystemExit("\n  span_m is required: the measured span of the printed slice "
                         "(rig sheet or --span).\n")
    dwells = load_sessions(folders)
    cal_dwells = load_sessions(cal_folders) if cal_folders else []
    missing = sorted({d["set"] for d in dwells if d["kind"] == "wind"
                      and not _by_set(rig, "span_m_by_set", d["set"], rig.get("span_m"))})
    if missing:
        raise SystemExit(f"\n  no span for {', '.join(missing)}: give span_m or "
                         f"span_m_by_set in the rig sheet\n")
    for d in dwells + cal_dwells:
        if d["use"]:
            dwell_stats(d, float(rig["settle_s"]))
        else:
            d["status"].append("use=0 in the run sheet")
    cal = get_calibration(dwells + cal_dwells, cal_file)
    rate = assign_zeros(dwells)
    mode = assign_support(dwells, rig["support_tare"])
    for d in dwells:
        if d["kind"] in ("wind", "support") and d["use"] and "mean" in d and "zero" not in d:
            d["excluded"] = True
    chain = Chain([d for d in dwells if not d.get("excluded")], cal, rig)

    # per dwell ----------------------------------------------------------------
    per = {}
    for d in dwells:
        if d["kind"] != "wind" or "zero" not in d or d.get("excluded"):
            continue
        if d["set"].lower() == "support":
            continue
        nom, dsys, drand = chain.decompose(d)
        per[d["id"]] = (d, nom, dsys, drand)

    # groups and differences ------------------------------------------------------
    groups = collections.defaultdict(list)
    for did, (d, *_rest) in per.items():
        groups[(d["set"], round(d["alpha"] % 360.0, 1), round(d["U_nom"], 1))].append(did)
    grp = {}
    for key, ids in groups.items():
        g = {}
        for q in ("Cd", "Cl", "Cd_u", "Cl_u", "D", "L", "q", "U", "blockage", "D_total"):
            noms = np.array([per[i][1][q] for i in ids])
            dsys = np.mean([per[i][2][q] for i in ids], axis=0)
            drand = np.mean([per[i][3][q] for i in ids], axis=0)
            scale = 1.0
            sb = float(np.std(noms, ddof=1)) if len(ids) > 1 else 0.0
            if len(ids) > 1 and np.std(drand) > 0:
                scale = max(1.0, (sb / math.sqrt(len(ids))) / float(np.std(drand)))
            g[q] = {"nom": float(noms.mean()), "dsys": dsys, "drand": drand * scale,
                    "s_between": sb, "scale": scale}
        g["n"] = len(ids)
        g["ids"] = ids
        g["sessions"] = sorted({per[i][0]["session"] for i in ids})
        grp[key] = g

    ref = _key(rig["reference_set"])
    diffs = []
    for (s, a, U), g in sorted(grp.items()):
        if _key(s) == ref:
            continue
        r = next((v for (s2, a2, U2), v in grp.items()
                  if _key(s2) == ref and a2 == a and U2 == U), None)
        if r is None:
            continue
        row = {"set": s, "reference": rig["reference_set"], "alpha_deg": a, "U_nom_ms": U,
               "n_set": g["n"], "n_ref": r["n"],
               "same_session": "yes" if set(g["sessions"]) & set(r["sessions"]) else "no"}
        for q in ("Cd", "Cl"):
            x = g[q]["nom"] + g[q]["dsys"] + g[q]["drand"]
            y = r[q]["nom"] + r[q]["dsys"] + r[q]["drand"]
            dd = x - y
            lo, hi = np.percentile(dd, [2.5, 97.5])
            row[f"d{q}"] = g[q]["nom"] - r[q]["nom"]
            row[f"d{q}_lo"], row[f"d{q}_hi"] = float(lo), float(hi)
            row[f"d{q}_resolved"] = "yes" if lo > 0 or hi < 0 else "no"
            if abs(r[q]["nom"]) >= 0.1:
                rel = 100 * (x / y - 1)
                lo, hi = np.percentile(rel, [2.5, 97.5])
                row[f"d{q}_pct"] = 100 * (g[q]["nom"] / r[q]["nom"] - 1)
                row[f"d{q}_pct_lo"], row[f"d{q}_pct_hi"] = float(lo), float(hi)
            else:
                row[f"d{q}_pct"] = row[f"d{q}_pct_lo"] = row[f"d{q}_pct_hi"] = float("nan")
        diffs.append(row)

    cfd, cfd_note = load_cfd(rig)
    bursts = analyse_bursts(dwells, rig, cfd)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_outputs(out_dir, dwells, per, grp, diffs, cal, rig, cfd, cfd_note, bursts,
                  mode, rate, folders, echo)
    if plots:
        try:
            import matplotlib
            matplotlib.use("Agg")
            make_plots(out_dir, grp, diffs, cfd, bursts, rig)
        except ImportError:
            echo("  matplotlib is not installed: no plots (pip install matplotlib)")
    return {"dwells": dwells, "per": per, "groups": grp, "diffs": diffs, "cal": cal,
            "bursts": bursts, "out": out_dir}


# ── outputs ───────────────────────────────────────────────────────────────

def _fmt(x, nd=5):
    if x is None:
        return ""
    if isinstance(x, (float, np.floating)):
        return "" if math.isnan(x) else f"{x:.{nd}g}"
    return str(x)


def write_outputs(out, dwells, per, grp, diffs, cal, rig, cfd, cfd_note, bursts,
                  mode, drift_rate, folders, echo):
    C = rig["test_section"].get("area_m2")

    # dwells.csv
    cols = ["dwell", "kind", "set", "mount", "alpha_deg", "U_nom_ms", "n_drag", "n_lift",
            "mean_drag_counts", "mean_lift_counts", "se_drag_counts", "se_lift_counts",
            "zero", "zero_w", "support_dwell", "rho_kg_m3", "rho_source", "q_pa",
            "D_N", "L_N", "Cd_uncorrected", "Cl_uncorrected", "blockage_factor",
            "Cd", "u_Cd", "Cd_lo", "Cd_hi", "Cl", "u_Cl", "Cl_lo", "Cl_hi", "Re_c", "status"]
    with open(out / "dwells.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for d in dwells:
            z = d.get("zero")
            row = {"dwell": d["id"], "kind": d["kind"], "set": d["set"], "mount": d["mount"],
                   "alpha_deg": d["alpha"], "U_nom_ms": d["U_nom"],
                   "n_drag": (d.get("n") or ["", ""])[0], "n_lift": (d.get("n") or ["", ""])[1],
                   "status": "; ".join(d["status"])}
            if "mean" in d:
                row.update({"mean_drag_counts": d["mean"][0], "mean_lift_counts": d["mean"][1],
                            "se_drag_counts": d["se"][0], "se_lift_counts": d["se"][1]})
            if z:
                row["zero"] = (z["before"]["dwell"] if z["kind"] == "one-sided" else
                               f"{z['before']['dwell']}->{z['after']['dwell']}")
                row["zero_w"] = z["w"]
            if d.get("support") is not None:
                row["support_dwell"] = d["support"]["dwell"]
            if "rho" in d:
                row["rho_kg_m3"] = d["rho"]
                row["rho_source"] = air_density(d, rig)[2]
            if d["id"] in per:
                _, nom, dsys, drand = per[d["id"]]
                row.update({"q_pa": nom["q"], "D_N": nom["D"], "L_N": nom["L"],
                            "Cd_uncorrected": nom["Cd_u"], "Cl_uncorrected": nom["Cl_u"],
                            "blockage_factor": nom["blockage"],
                            "Re_c": nom["U"] * float(rig["c_ref_m"]) / float(rig["nu_m2_s"])})
                for q in ("Cd", "Cl"):
                    s = summarise(nom[q], dsys[q], drand[q])
                    row.update({q: s["value"], f"u_{q}": s["u"], f"{q}_lo": s["lo"],
                                f"{q}_hi": s["hi"]})
            w.writerow([_fmt(row.get(c, "")) for c in cols])

    # coefficients.csv
    cols = ["set", "alpha_deg", "U_nom_ms", "U_ms", "n_dwells", "sessions", "Re_c", "q_pa",
            "blockage_factor"]
    for q in ("Cd", "Cl"):
        cols += [q, f"u_{q}", f"u_{q}_sys", f"u_{q}_rand", f"{q}_lo", f"{q}_hi",
                 f"{q}_repeat_sd", f"{q}_uncorrected"]
    with open(out / "coefficients.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for (s, a, U), g in sorted(grp.items()):
            row = {"set": s, "alpha_deg": a, "U_nom_ms": U, "U_ms": g["U"]["nom"],
                   "n_dwells": g["n"],
                   "sessions": " ".join(g["sessions"]), "q_pa": g["q"]["nom"],
                   "Re_c": g["U"]["nom"] * float(rig["c_ref_m"]) / float(rig["nu_m2_s"]),
                   "blockage_factor": g["blockage"]["nom"]}
            for q in ("Cd", "Cl"):
                sm = summarise(g[q]["nom"], g[q]["dsys"], g[q]["drand"])
                row.update({q: sm["value"], f"u_{q}": sm["u"], f"u_{q}_sys": sm["u_sys"],
                            f"u_{q}_rand": sm["u_rand"], f"{q}_lo": sm["lo"],
                            f"{q}_hi": sm["hi"], f"{q}_repeat_sd": g[q]["s_between"],
                            f"{q}_uncorrected": g[f"{q}_u"]["nom"]})
                g[q]["summary"] = sm
            w.writerow([_fmt(row.get(c, "")) for c in cols])

    # differences.csv
    cols = ["set", "reference", "alpha_deg", "U_nom_ms", "n_set", "n_ref", "same_session"]
    for q in ("Cd", "Cl"):
        cols += [f"d{q}", f"d{q}_lo", f"d{q}_hi", f"d{q}_resolved",
                 f"d{q}_pct", f"d{q}_pct_lo", f"d{q}_pct_hi"]
    with open(out / "differences.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in diffs:
            w.writerow([_fmt(r.get(c, "")) for c in cols])

    # calibration.json
    keep = {k: v for k, v in cal.items() if k != "points"}
    keep["points"] = cal.get("points", [])
    (out / "calibration.json").write_text(json.dumps(keep, indent=1, default=float) + "\n")

    # bursts.csv
    if bursts:
        cols = [k for k in bursts[0] if not k.startswith("_")]
        with open(out / "bursts.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for b in bursts:
                w.writerow([_fmt(b[c]) for c in cols])

    # summary.txt
    L = []
    say = L.append
    say(f"Section balance analysis, {time.strftime('%Y-%m-%d %H:%M')}")
    say("Sessions: " + ", ".join(Path(x).name for x in folders))
    say("")
    say("APPLIED")
    K = np.array(cal["K"])
    x = cal.get("crosstalk", {})
    say(f"- Calibration ({cal.get('source', '?')}): K = [[{K[0,0]:.1f}, {K[0,1]:.1f}], "
        f"[{K[1,0]:.1f}, {K[1,1]:.1f}]] counts/N (calculated).")
    if x:
        say(f"  Cross-talk {100 * x['lift_counts_per_drag_counts']:+.2f} % (lift per drag) and "
            f"{100 * x['drag_counts_per_lift_counts']:+.2f} % (drag per lift); worst residual "
            f"{1000 * cal.get('resid_n_max', float('nan')):.2f} mN over loads to "
            f"{cal.get('max_load_n', float('nan')):.2f} N; drift term "
            f"{'fitted' if cal.get('drift_fitted') else 'not fitted'}.")
    wind = [d for d in dwells if d["kind"] == "wind"]
    used = [d for d in wind if d["id"] in per]
    br = sum(1 for d in used if d["zero"]["kind"] == "bracketed")
    one = len(used) - br
    say(f"- Zeros: {br} of {len(used)} wind dwells bracketed by wind-off zeros at their "
        f"alpha and mount; {one} one-sided"
        + ("" if not one else
           " (drift allowance from the session's median zero drift)" if drift_rate is not None
           else " (drift unknown: no pair of zeros at one alpha to measure it)")
        + ".")
    say(f"- Support tare: {mode}; "
        f"{sum(1 for d in used if d.get('support') is not None)} of {len(used)} wind dwells tared."
        + ("" if mode != "none" else " Cd and Cl INCLUDE the support's force."))
    rhos = collections.Counter(air_density(d, rig)[2] for d in used)
    say("- Density: " + "; ".join(f"{n} dwells from {k}" for k, n in rhos.items()) +
        f". u(rho) {100 * rig['u_rho_rel']:.1f} % assumed for measured air.")
    kinds = collections.Counter(wind_speed(d, rig)[1] for d in used)
    say("- Wind speed: " + "; ".join(f"{n} dwells from {k}" for k, n in kinds.items()) +
        f". The fan label carries u_sys {100 * rig['u_U_sys_rel']:.1f} % (assumed: the "
        f"calibration was measured to 700 rpm only) and u_rand {100 * rig['u_U_rand_rel']:.1f} %.")
    if C:
        say(f"- Blockage: Maskell type, theta {rig['maskell_theta']} +- {rig['u_maskell_theta']} "
            f"(assumed), C = {C:.4f} m^2, each dwell with its own measured drag"
            + (f" plus {rig['extra_drag_area_m2']} m^2 non-metric" if rig.get('extra_drag_area_m2') else "")
            + ". Factors "
            f"{min(g['blockage']['nom'] for g in grp.values()):.4f} to "
            f"{max(g['blockage']['nom'] for g in grp.values()):.4f}." if grp else
            "- Blockage: no wind groups.")
    else:
        say("- Blockage: NOT APPLIED. The test-section area is not recorded "
            "(cfd/MEASUREMENTS_NEEDED.md section 2).")
        if grp:
            da = max(g["D_total"]["nom"] / g["q"]["nom"] for g in grp.values())
            say(f"  What it would change: q_c/q - 1 = theta (D/q) / C. The largest drag area "
                f"here is {1e4 * da:.1f} cm^2; with theta {rig['maskell_theta']}, Cd and Cl "
                f"would fall by " + ", ".join(
                    f"{100 * (1 - 1 / (1 + rig['maskell_theta'] * da / c)):.1f} % at "
                    f"C = {c} m^2" for c in (0.25, 0.5, 1.0)) + ".")
    say(f"- Settle: first {rig['settle_s']} s of each dwell dropped. Uncertainty: "
        f"{rig['draws']} Monte Carlo draws, 95 % intervals.")
    say(f"- CFD overlay: {cfd_note}.")
    say("")
    say("NOT CORRECTED OR NOT PROPAGATED")
    say("- Finite span and end effects: the CFD is 2D, per unit span; the slice is not.")
    say("- Support interference with the slice (a tare removes the support's own force only).")
    say("- Alpha setting error; repeats with alpha re-set capture it in the repeat scatter.")
    say("- Streamline curvature and solid blockage (thin shell, assumed small).")
    say("- Which 2D state the slice takes at alpha 0 (CFD: Cd about 1.75 or 3.2). "
        "Dwells flagged 'unsteady' are where to look.")
    excl = [d for d in dwells if d["kind"] == "wind" and d["id"] not in per]
    if excl:
        say("")
        say("WIND DWELLS NOT USED")
        for d in excl:
            say(f"- {d['id']} {d['set']} alpha {d['alpha']:g} U {d['U_nom']:.2f}: "
                + ("; ".join(d["status"]) or "no zero"))
    flagged = [d for d in dwells if d["id"] in per and d["status"]]
    if flagged:
        say("")
        say("FLAGS ON USED DWELLS")
        for d in flagged:
            say(f"- {d['id']} {d['set']} alpha {d['alpha']:g} U {d['U_nom']:.2f}: "
                + "; ".join(d["status"]))
    say("")
    say("COEFFICIENTS (measured, corrected as above; 95 % intervals)")
    say(f"{'set':<9}{'alpha':>6}{'U':>7}{'n':>3}{'Cd':>9}{'[95 %]':>18}{'Cl':>9}{'[95 %]':>18}")
    for (s, a, U), g in sorted(grp.items()):
        cd, cl = g["Cd"]["summary"], g["Cl"]["summary"]
        say(f"{s:<9}{a:6.0f}{g['U']['nom']:7.2f}{g['n']:3d}{cd['value']:9.3f}  [{cd['lo']:6.3f}, {cd['hi']:6.3f}]"
            f"{cl['value']:9.3f}  [{cl['lo']:6.3f}, {cl['hi']:6.3f}]")
    if diffs:
        say("")
        say(f"DIFFERENCES, set minus {rig['reference_set']} (resolved = 95 % interval excludes 0)")
        for r in diffs:
            say(f"{r['set']:<9}alpha {r['alpha_deg']:5.0f}  U {r['U_nom_ms']:6.2f}  "
                f"dCd {r['dCd']:+.4f} [{r['dCd_lo']:+.4f}, {r['dCd_hi']:+.4f}] "
                f"{'resolved' if r['dCd_resolved'] == 'yes' else 'not resolved'}   "
                f"dCl {r['dCl']:+.4f} [{r['dCl_lo']:+.4f}, {r['dCl_hi']:+.4f}] "
                f"{'resolved' if r['dCl_resolved'] == 'yes' else 'not resolved'}"
                + ("" if r["same_session"] == "yes" else "   (different sessions)"))
    if bursts:
        say("")
        say("ACCELEROMETER BURSTS (structural response; shedding if f scales with U)")
        for b in bursts:
            say(f"- {b['dwell']} {b['set']} alpha {b['alpha_deg']:g} U {b['U_nom_ms']:.2f}: "
                f"peak {b['f_peak_hz']:.1f} Hz, {1000 * b['amp_peak_g']:.2f} mg, "
                f"{b['peak_over_median']:.1f}x the band median"
                + (f", St {b['St_measured']:.3f} (CFD {b['St_cfd'] or 'n/a'})"
                   if b["U_nom_ms"] > 0 else " (wind off)"))
    (out / "summary.txt").write_text("\n".join(L) + "\n")
    echo("\n".join(L))
    echo(f"\n  wrote {out}")


# ── plots ─────────────────────────────────────────────────────────────────

def _style(ax):
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(AXIS)
    ax.tick_params(colors=INK2, labelsize=8)


def _measured(ax, x, g, q, colour, marker="o"):
    sm = g[q]["summary"]
    ax.errorbar([x], [sm["value"]], yerr=[[sm["value"] - sm["lo"]], [sm["hi"] - sm["value"]]],
                fmt=marker, color=colour, ecolor=colour, elinewidth=1.2, capsize=0,
                markersize=7, markeredgecolor=SURFACE, markeredgewidth=1.2, zorder=3)


def _cfd(ax, pts, xkey, q):
    for model, marker in (("SST", "s"), ("LM", "^")):
        p = [c for c in pts if c["model"] == model]
        if p:
            ax.plot([c[xkey] for c in p], [c[q] for c in p], linestyle="none",
                    marker=marker, markersize=5, markerfacecolor="none",
                    markeredgecolor=MUTED, markeredgewidth=1.0, zorder=2)


def _legend(fig, colour_sets):
    from matplotlib.lines import Line2D
    h = [Line2D([], [], marker="o", linestyle="none", color=c, markeredgecolor=SURFACE,
                markersize=7, label=f"{s}, measured (95 %)") for s, c in colour_sets]
    h += [Line2D([], [], marker="s", linestyle="none", markerfacecolor="none",
                 markeredgecolor=MUTED, label="CFD SST, healthy runs"),
          Line2D([], [], marker="^", linestyle="none", markerfacecolor="none",
                 markeredgecolor=MUTED, label="CFD LM, healthy runs")]
    fig.legend(handles=h, loc="lower center", ncol=2, frameon=False,
               fontsize=8, labelcolor=INK2)


def _legend_room(n_sets):
    """Bottom margin, as a fraction of the figure, for the two-column legend."""
    return 0.035 + 0.04 * math.ceil((n_sets + 2) / 2)


def make_plots(out, grp, diffs, cfd, bursts, rig):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator
    plt.rcParams.update({"font.family": "sans-serif", "figure.facecolor": SURFACE,
                         "axes.labelcolor": INK2, "axes.titlecolor": INK,
                         "axes.titlesize": 9, "axes.labelsize": 8})
    sets = sorted({k[0] for k in grp}, key=lambda s: (_key(s) != _key(rig["reference_set"]), s))
    colours = {s: set_colour(s, sets) for s in sets}
    speeds = sorted({k[2] for k in grp})
    alphas = sorted({k[1] for k in grp})

    # Cd, Cl against alpha: one figure per speed, one column per set
    for U in speeds:
        fig, axs = plt.subplots(2, len(sets), figsize=(3.2 * len(sets) + 0.6, 5.6),
                                squeeze=False, sharey="row")
        near = cfd_near(cfd, U)
        for j, s in enumerate(sets):
            for i, q in enumerate(("Cd", "Cl")):
                ax = axs[i, j]
                _style(ax)
                _cfd(ax, near, "alpha", q)
                for (s2, a, U2), g in grp.items():
                    if s2 == s and U2 == U:
                        _measured(ax, a, g, q, colours[s])
                ax.set_xlim(-15, 375)
                ax.set_xticks([0, 90, 180, 270, 360])
                if i == 0:
                    ax.set_title(s)
                if i == 1:
                    ax.set_xlabel("alpha, deg (CFD convention)")
                if j == 0:
                    ax.set_ylabel(q)
        fig.suptitle(f"Cd and Cl against alpha at U {U:.1f} m/s"
                     + (f"; CFD at {near[0]['U']:g} m/s" if near else "; no CFD within 10 %"),
                     color=INK, fontsize=10)
        _legend(fig, [(s, colours[s]) for s in sets])
        fig.tight_layout(rect=(0, _legend_room(len(sets)), 1, 0.95))
        fig.savefig(out / f"coefficients_vs_alpha_U{U:05.1f}.png", dpi=150)
        plt.close(fig)

    # Cd, Cl against U: one figure per alpha, one column per set
    for a in alphas:
        fig, axs = plt.subplots(2, len(sets), figsize=(3.2 * len(sets) + 0.6, 5.6),
                                squeeze=False, sharey="row")
        near = [c for c in cfd if same_alpha(c["alpha"], a)]
        for j, s in enumerate(sets):
            for i, q in enumerate(("Cd", "Cl")):
                ax = axs[i, j]
                _style(ax)
                _cfd(ax, near, "U", q)
                pts = sorted((U2, g) for (s2, a2, U2), g in grp.items() if s2 == s and a2 == a)
                if len(pts) > 1:
                    ax.plot([p[0] for p in pts], [p[1][q]["summary"]["value"] for p in pts],
                            color=colours[s], linewidth=2, zorder=2)
                for U2, g in pts:
                    _measured(ax, U2, g, q, colours[s])
                ax.set_xlim(0, 42)
                if i == 0:
                    ax.set_title(s)
                if i == 1:
                    ax.set_xlabel("U, m/s (fan label unless measured)")
                if j == 0:
                    ax.set_ylabel(q)
        fig.suptitle(f"Cd and Cl against wind speed at alpha {a:g} deg", color=INK, fontsize=10)
        _legend(fig, [(s, colours[s]) for s in sets])
        fig.tight_layout(rect=(0, _legend_room(len(sets)), 1, 0.95))
        fig.savefig(out / f"coefficients_vs_U_alpha{a:05.1f}.png", dpi=150)
        plt.close(fig)

    # differences: one row of panels per set, a single series in each
    others = sorted({r["set"] for r in diffs})
    if others:
        conds = sorted({(r["alpha_deg"], r["U_nom_ms"]) for r in diffs})
        fig, axs = plt.subplots(len(others), 2, figsize=(8.0, 0.45 * len(conds) * len(others) + 1.6),
                                squeeze=False)
        for i, s in enumerate(others):
            for j, (key, label) in enumerate((("dCd_pct", "Cd change, % of reference"),
                                              ("dCl", "Cl change (absolute)"))):
                ax = axs[i, j]
                _style(ax)
                ax.axvline(0, color=AXIS, linewidth=1)
                for k, c in enumerate(conds):
                    r = next((r for r in diffs if r["set"] == s and
                              (r["alpha_deg"], r["U_nom_ms"]) == c), None)
                    if r is None or math.isnan(r[key]):
                        continue
                    lo, hi = r[key + "_lo"], r[key + "_hi"]
                    ax.plot([lo, hi], [k, k], color=colours.get(s, MUTED), linewidth=2)
                    ax.plot([r[key]], [k], "o", color=colours.get(s, MUTED), markersize=7,
                            markeredgecolor=SURFACE, markeredgewidth=1.2)
                ax.set_yticks(range(len(conds)))
                ax.set_yticklabels([f"alpha {a:g}, {U:.1f} m/s" for a, U in conds]
                                   if j == 0 else [""] * len(conds))
                ax.invert_yaxis()
                ax.xaxis.set_major_locator(MaxNLocator(5))
                ax.set_xlabel(label)
                ax.set_title(f"{s} minus {rig['reference_set']}" if j == 0 else "")
        fig.tight_layout()
        fig.savefig(out / "differences.png", dpi=150)
        plt.close(fig)

    # spectra
    shown = [b for b in bursts if b["U_nom_ms"] > 0][:12]
    if shown:
        fig, axs = plt.subplots(len(shown), 1, figsize=(7.5, 1.9 * len(shown) + 0.6),
                                squeeze=False)
        for i, b in enumerate(shown):
            ax = axs[i, 0]
            _style(ax)
            off = [o for o in bursts if o["U_nom_ms"] == 0 and o["set"] == b["set"]
                   and o["mount"] == b["mount"] and same_alpha(o["alpha_deg"], b["alpha_deg"])]
            if off:
                f, a = off[0]["_spec"]
                ax.plot(f, 1000 * a, color=MUTED, linewidth=1, label="wind off")
            f, a = b["_spec"]
            ax.plot(f, 1000 * a, color=colours.get(b["set"], SET_COLOURS["plain"]),
                    linewidth=1.2, label="wind on")
            for k, fe in enumerate(x for x in b["f_expected_hz"].split(";") if x.strip()):
                ax.axvline(float(fe), color=INK2, linewidth=0.8,
                           label="CFD St x U / c_ref (clean peaks)" if k == 0 else None)
            ax.set_xlim(0, min(500, f[-1]))
            ax.set_yscale("log")
            ax.set_ylabel("mg (log)")
            ax.set_title(f"{b['set']}, alpha {b['alpha_deg']:g}, U {b['U_nom_ms']:.1f} m/s: "
                         f"peak {b['f_peak_hz']:.0f} Hz, St {b['St_measured']:.3f}", loc="left")
            if i == 0:
                ax.legend(frameon=False, fontsize=8, labelcolor=INK2)
        axs[-1, 0].set_xlabel("frequency, Hz (accelerometer, resampled uniform)")
        fig.tight_layout()
        fig.savefig(out / "spectra.png", dpi=150)
        plt.close(fig)


# ── command line ──────────────────────────────────────────────────────────

def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("sessions", nargs="*", help="session folders from the logger")
    ap.add_argument("--rig", default=None, help="rig sheet, .yaml or .json")
    ap.add_argument("--out", default=None, help="output folder")
    ap.add_argument("--calibration", default=None,
                    help="calibration.json from an earlier analysis, instead of cal dwells")
    ap.add_argument("--cal-sessions", nargs="*", default=[],
                    help="extra folders whose cal dwells are used for K")
    ap.add_argument("--span", type=float, default=None, help="slice span, m (overrides the rig sheet)")
    ap.add_argument("--section-area", type=float, default=None, help="test-section area, m^2")
    ap.add_argument("--section-wh", type=float, nargs=2, default=None, metavar=("W", "H"),
                    help="test-section width and height, m")
    ap.add_argument("--theta", type=float, default=None, help="Maskell blockage factor")
    ap.add_argument("--lift-sign", type=int, choices=(-1, 1), default=None)
    ap.add_argument("--reference", default=None, help="reference set (default Plain)")
    ap.add_argument("--no-support-tare", action="store_true")
    ap.add_argument("--draws", type=int, default=None)
    ap.add_argument("--no-plots", action="store_true")
    ap.add_argument("--write-rig-template", default=None, metavar="PATH")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    if a.write_rig_template:
        p = Path(a.write_rig_template)
        if p.exists():
            raise SystemExit(f"\n  {p} exists; not overwritten\n")
        if p.suffix == ".json":
            p.write_text(json.dumps({"_note": "see the YAML template for comments",
                                     **RIG_DEFAULTS}, indent=1) + "\n")
        else:
            p.write_text(RIG_TEMPLATE)
        print(f"  wrote {p}")
        return 0
    if not a.sessions:
        raise SystemExit("\n  give at least one session folder (or --write-rig-template)\n")
    over = {}
    if a.span is not None:
        over["span_m"] = a.span
    if a.section_area is not None:
        over["test_section"] = {"area_m2": a.section_area}
    if a.section_wh is not None:
        over["test_section"] = {"width_m": a.section_wh[0], "height_m": a.section_wh[1],
                                "area_m2": a.section_wh[0] * a.section_wh[1]}
    if a.theta is not None:
        over["maskell_theta"] = a.theta
    if a.lift_sign is not None:
        over["lift_sign"] = a.lift_sign
    if a.reference:
        over["reference_set"] = a.reference
    if a.no_support_tare:
        over["support_tare"] = "none"
    if a.draws:
        over["draws"] = a.draws
    rig = load_rig(a.rig, over)
    out = a.out or (Path(a.sessions[0]) / "analysis" if len(a.sessions) == 1 else
                    ROOT / "logs" / "section_balance" / f"analysis_{time.strftime('%Y%m%d_%H%M%S')}")
    analyse(a.sessions, rig, cal_file=a.calibration, cal_folders=a.cal_sessions,
            out_dir=out, plots=not a.no_plots)
    return 0


if __name__ == "__main__":
    sys.exit(main())
