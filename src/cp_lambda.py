#!/usr/bin/env python3
"""
cp_lambda.py — turn a blade sweep into Cp(λ), once rotor speed is available.

    # rotor speed recovered from the generator's three phases
    python src/cp_lambda.py --sweep logs/sweep_v1_Ra20_summary.csv \
           --radius 0.30 --poles 12 --daq reference/data/03162026_sec_backup.xlsx

    # or from a column already in the points CSV
    python src/cp_lambda.py --sweep logs/sweep_v1_Ra20_points.csv --radius 0.30

    # or explore what a radius/pole guess would imply, with no rotor data
    python src/cp_lambda.py --sweep logs/sweep_v1_Ra20_summary.csv \
           --radius 0.30 --assume-lambda 4.0

═══════════════════════════════════════════════════════════════════════════
WHAT IS AND IS NOT COMPUTED
═══════════════════════════════════════════════════════════════════════════
    λ    = ω R / v            tip-speed ratio
    Cp_elec = P / (½ ρ A v³)  ELECTRICAL power coefficient

    A = 2·R·H   for a VERTICAL-axis rotor — it sweeps a cylinder   [default]
    A = π·R²    for a horizontal-axis propeller — it sweeps a disc

The Aerolab rotor is a three-blade VAWT, so its swept area is a rectangle,
not a disc. The two differ by 1.54× here. Getting it wrong scales every Cp by
that factor and nothing in the numbers looks wrong.

**Cp_elec is not Cp.** It is Cp_aero × η_gen × η_rect: everything the rotor
extracted, minus what the generator and rectifier lost. It is the honest
quantity to report from this rig because P is measured at the load terminals
and nothing here measures shaft torque.

Do not compare Cp_elec to the Betz limit. A rotor at Betz with a 40%
efficient generator reads 0.24, and the number means nothing without the
efficiency chain attached to it.

═══════════════════════════════════════════════════════════════════════════
THE TWO NUMBERS THIS NEEDS
═══════════════════════════════════════════════════════════════════════════
**Tip radius**, from the AXIS OF ROTATION — not blade length. λ scales
linearly with it and Cp as 1/R², so a 10% error in radius is a 21% error in
Cp. There is no default and there will not be one.

**Rotor speed.** Three routes, in descending order of directness:

  1. `--rpm-column` — a column already in the sweep CSV. Best.
  2. `--daq` + `--poles` — recovered from the generator's three phases via a
     Clarke transform. The March capture showed ch3/4/6 mutually correlated
     at −0.50 = cos(120°), so the phases are already on the DAQ; only the
     pole count is missing. See `docs/08_march_daq.md`.
  3. `--assume-lambda` — assume a constant tip-speed ratio and back rotor
     speed out of it. This is EXPLORATORY ONLY: it assumes the answer to the
     question Cp(λ) exists to ask, so every point lands at the λ you assumed.
     Useful for sizing an axis, never for a result.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 1.204 kg/m3 = dry air at 20 C, 101325 Pa — a lab, not the ISA 15 C sea-level
# 1.225 this used to hold. The docs quote 1.204 and the difference is 1.7% in
# every Cp, which is larger than several effects this rig is trying to resolve.
# Pass --temp and --pressure from the tunnel node and neither number applies.
RHO_DEFAULT = 1.204


# ═══════════════════════════════════════════════════════════════════════════
# ROTOR SPEED FROM THE GENERATOR'S THREE PHASES
# ═══════════════════════════════════════════════════════════════════════════

def clarke_frequency(a, b, c, fs, smooth=201):
    """
    Instantaneous electrical frequency from a three-phase set.

    The Clarke transform turns three 120°-separated signals into one rotating
    vector, so the electrical angle is just its argument and the frequency is
    the derivative. That beats zero-crossing detection on every count: it uses
    all three channels, it is immune to amplitude imbalance, and it gives a
    value at every sample rather than twice a cycle.

    Returns |f| in Hz, median-filtered.
    """
    from scipy.signal import medfilt
    a, b, c = np.asarray(a, float), np.asarray(b, float), np.asarray(c, float)
    alpha = (2 * a - b - c) / 3.0
    beta = (b - c) / math.sqrt(3.0)
    phase = np.unwrap(np.arctan2(beta, alpha))
    f = np.gradient(phase, 1.0 / fs) / (2 * math.pi)
    k = smooth if smooth % 2 else smooth + 1
    return np.abs(medfilt(f, k))


def rotor_rpm_from_phases(f_elec_hz, poles):
    """
    Electrical Hz → rotor rpm.

    `poles` is the number of MAGNETIC POLES, not pole pairs. A 12-pole machine
    turns 6 electrical cycles per revolution, so rpm = 60 f / (poles/2).
    Getting this factor wrong scales every λ by the same ratio and every Cp
    with it — it is the single easiest way to produce a plausible wrong curve.
    """
    if poles < 2 or poles % 2:
        raise ValueError("poles must be an even number >= 2 (magnetic poles, "
                         "not pole pairs)")
    return 60.0 * np.asarray(f_elec_hz, float) / (poles / 2.0)


def load_daq_phases(path, cols=(2, 3, 5), fs=None):
    """Pull three phase columns out of the DAQ export."""
    import warnings
    warnings.filterwarnings("ignore")
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    t = np.array([float(r[0]) for r in rows])
    volts = np.array([[float(x) if x is not None else np.nan
                       for x in r[3:9]] for r in rows]).T
    if fs is None:
        fs = 1.0 / float(np.median(np.diff(t)))
    return t, volts[list(cols)], fs


# ═══════════════════════════════════════════════════════════════════════════

def swept_area(radius_m, hub_m=0.0, rotor="vawt", height_m=None):
    """
    Swept area — and the formula depends on the ROTOR TYPE, not a detail.

    **VAWT** (vertical axis, H-rotor / Darrieus): the blades sweep a CYLINDER,
    and the frontal area the wind sees is its rectangular projection:

        A = 2 · R · H

    **HAWT** (horizontal axis, propeller): the blades sweep a DISC:

        A = π · (R² − hub²)

    On this rig the two differ by 1.54×, so using the wrong one puts every
    Cp out by that factor while every number still looks entirely plausible.
    The Aerolab rotor is a three-blade VAWT — hence the default.
    """
    if rotor == "hawt":
        return math.pi * (radius_m ** 2 - hub_m ** 2)
    if not height_m:
        raise ValueError(
            "a VAWT sweeps a cylinder, so its area needs BLADE HEIGHT as well "
            "as radius: A = 2*R*H. Pass --height, or --rotor hawt if this is "
            "a propeller.")
    return 2.0 * radius_m * height_m


def air_density(temp_c=None, pressure_pa=None):
    if temp_c is None or pressure_pa is None:
        return RHO_DEFAULT
    return pressure_pa / (287.058 * (temp_c + 273.15))


def compute(points, radius_m, hub_m=0.0, rho=RHO_DEFAULT, area=None):
    """
    points: iterable of dicts with mps, p_w, and rpm (rotor).
    Returns the same rows with lam and cp_elec added.
    """
    if area is None:
        # No silent default. 'hawt' here meant pi*R^2, which for this VAWT is
        # 0.0324 against the true 2*R*H = 0.0498 — every Cp inflated by 53.6%
        # with nothing raised. The CLI always passes an area, so this only
        # ever bit a programmatic caller, which is exactly the caller with no
        # banner to notice it.
        raise ValueError(
            "compute() needs an explicit swept area. Call "
            "swept_area(radius, hub, rotor, height) and pass the result — "
            "a VAWT sweeps a cylinder (2*R*H), not a disc, and guessing "
            "wrong is a 54% error in every Cp.")
    A = area
    out = []
    for p in points:
        v, P, n = p.get("mps"), p.get("p_w"), p.get("rpm")
        if not v or v <= 0 or n is None:
            continue
        omega = 2 * math.pi * float(n) / 60.0
        avail = 0.5 * rho * A * v ** 3
        out.append({**p,
                    "omega": omega,
                    "lam": omega * radius_m / v,
                    "avail_w": avail,
                    "cp_elec": (P / avail) if avail > 0 else float("nan")})
    return out


RPM_NAMES = ("turbine_rpm", "turbine_rpm_at_pmax", "rotor_rpm", "rpm")


def read_header(path):
    """The CSV's column names, skipping the `#` metadata block."""
    with open(path) as f:
        for line in f:
            if not line.startswith("#"):
                return [c.strip() for c in line.rstrip("\n").split(",")]
    return []


def read_sweep(path, prefer=None):
    """
    Returns (rows, rpm_col, n_blank).

    `rpm_col` is the rotor-speed column found, or None. `n_blank` counts rows
    that HAVE the column but leave it empty — sweep_core writes a blank
    whenever the rotor window held no pulses, which happens routinely at the
    bottom of the wind range and during a stall. Those rows are real data for
    everything except lambda, so they are reported, not used to condemn the
    file.
    """
    rows = []
    rpm_col, n_blank = None, 0
    # `prefer` is --rpm-column. It used never to reach here: the flag only
    # selected a branch in main() and formatted a display string, so a fully
    # populated `shaft_rpm` plus `--rpm-column shaft_rpm` was reported as
    # "every cell is empty ... Re-run it" — a confident message pointing at a
    # sensor fault that did not exist, costing a tunnel session. A misspelled
    # name meanwhile succeeded and stamped the nonexistent column into the
    # result's provenance line.
    # NO FALLBACK when the operator names a column. Appending the standard
    # names as backups meant a blank cell in `shaft_rpm` silently took the
    # value from `turbine_rpm` instead — a bouncing reed reading 2x high —
    # while the banner and the result CSV's provenance line both still said
    # `shaft_rpm`. The headline lambda came out doubled from a column the
    # operator had explicitly told the tool not to use, and the archived file
    # recorded the wrong source, so it could not be caught afterwards.
    # Naming a column is an instruction, not a hint.
    names = (prefer,) if prefer else RPM_NAMES
    with open(path) as f:
        body = [l for l in f if not l.startswith("#")]
    for r in csv.DictReader(body):
        try:
            v = float(r.get("wind_mps") or r.get("mps") or 0)
            p = float(r.get("p_max_fit_w") or r.get("p_max_w")
                      or r.get("watts") or 0)
        except (TypeError, ValueError):
            continue
        row = {"mps": v, "p_w": p,
               "fan_rpm": float(r.get("fan_rpm_cmd") or r.get("fan_rpm") or 0)}
        for k in names:
            if k in r:
                rpm_col = rpm_col or k
                if not str(r[k]).strip():
                    n_blank += 1
                break
        # `turbine_rpm` FIRST: that is what sweep_core actually writes
        # (POINTS_HEADER) and what the summary carries as
        # `turbine_rpm_at_pmax`. This list originally held only the two names
        # below, so a sweep that DID record rotor speed would have been read as
        # one that did not, and Cp would have quietly come from --assume-lambda
        # instead. Nothing in the output would have said so.
        # `break` on the first hit. Without it the LAST populated name won,
        # so a file carrying both turbine_rpm and rotor_rpm reported
        # "column 'turbine_rpm'" in the banner while computing lambda from
        # rotor_rpm — the banner and the arithmetic naming different columns.
        for k in names:
            if r.get(k):
                try:
                    row["rpm"] = float(r[k])
                    break
                except ValueError:
                    pass
        rows.append(row)
    return rows, rpm_col, n_blank


# ═══════════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(
        description="Cp(lambda) from a blade sweep",
        epilog="Reports Cp_elec, not Cp. Do not compare it to the Betz limit.")
    p.add_argument("--sweep", required=True, help="a *_summary.csv or *_points.csv")
    p.add_argument("--radius", type=float, required=True,
                   help="tip radius in METRES, from the axis of rotation — "
                        "NOT blade length. No default: a 10%% error here is a "
                        "21%% error in Cp.")
    p.add_argument("--hub", type=float, default=0.0,
                   help="hub radius, m — HAWT only")
    p.add_argument("--rotor", choices=["vawt", "hawt"], default="vawt",
                   help="vawt (default, sweeps a cylinder: A = 2RH) or hawt "
                        "(sweeps a disc: A = pi R^2). This is not cosmetic — "
                        "the two differ by 1.54x on this rig.")
    p.add_argument("--height", type=float, default=None,
                   help="blade height/span in METRES. Required for a VAWT.")
    p.add_argument("--temp", type=float, default=None, help="air temp °C")
    p.add_argument("--pressure", type=float, default=None, help="Pa")

    g = p.add_argument_group("rotor speed — pick one")
    g.add_argument("--rpm-column", dest="rpm_column",
                   help="a rotor-rpm column already in the CSV")
    g.add_argument("--daq", help="DAQ export carrying the generator phases")
    g.add_argument("--poles", type=int,
                   help="MAGNETIC POLES of the generator (not pole pairs)")
    g.add_argument("--phase-cols", default="2,3,5", dest="phase_cols",
                   help="0-based voltage columns of the three phases "
                        "(default 2,3,5 = ch3/ch4/ch6)")
    g.add_argument("--assume-lambda", type=float, default=None,
                   dest="assume_lambda",
                   help="EXPLORATORY: assume a constant tip-speed ratio. This "
                        "assumes the answer to the question Cp(lambda) exists "
                        "to ask.")
    p.add_argument("--csv", default=None, help="write the result here")
    a = p.parse_args()

    rows, found_col, n_blank = read_sweep(a.sweep, a.rpm_column)
    if a.rpm_column and found_col != a.rpm_column:
        raise SystemExit(
            f"\n  --rpm-column '{a.rpm_column}' is not a column in "
            f"{Path(a.sweep).name}.\n"
            f"  Columns present: {', '.join(read_header(a.sweep))}\n\n"
            f"  Checked against the header rather than assumed, because a\n"
            f"  typo here used to succeed and write the misspelled name into\n"
            f"  the result's provenance line while using a different column.\n")
    if not rows:
        raise SystemExit(f"no usable rows in {a.sweep}")
    rho = air_density(a.temp, a.pressure)

    # ── rotor speed ─────────────────────────────────────────────────────
    src = None
    have = [r for r in rows if "rpm" in r and r["rpm"] > 0]
    # NOT `and have`: a column that exists but is entirely blank is a
    # different problem from a column that is absent, and it needs its own
    # message. Gating on `have` sent the empty case to the generic "no rotor
    # speed, give one of these flags" text, which invites the operator to
    # reach for --assume-lambda over a file whose sensor simply never fired.
    if a.rpm_column or (found_col and not a.daq and not a.assume_lambda):
        col = a.rpm_column or found_col
        src = f"column '{col}'"
        if not have:
            raise SystemExit(
                f"\n  '{col}' is present in {Path(a.sweep).name} but every "
                f"cell is empty.\n  The sweep ran before the rotor sensor "
                f"produced pulses. Re-run it.\n")
        # Partial coverage is NORMAL, not a failure. sweep_core leaves the
        # cell blank whenever a dwell's rotor window caught no pulses, which
        # happens at low wind and through a stall. Rejecting all fourteen
        # wind speeds to protect against one missing dwell used to print
        # "has no rotor-rpm column" about a file that plainly had one, and
        # sent the operator back to burn tunnel time re-running a good sweep.
        if len(have) < len(rows):
            print(f"  {len(rows) - len(have)} of {len(rows)} rows have no "
                  f"rotor speed and are skipped for Cp(lambda).")
            if len(have) < 3:
                raise SystemExit(
                    f"\n  only {len(have)} row(s) carry rotor speed — too few "
                    f"for a curve.\n")
        rows = have
    elif a.daq:
        if not a.poles:
            raise SystemExit("--daq needs --poles (magnetic poles, not pairs)")
        cols = tuple(int(x) for x in a.phase_cols.split(","))
        print(f"  reading generator phases from {Path(a.daq).name}…")
        t, ph, fs = load_daq_phases(a.daq, cols)
        f_elec = clarke_frequency(ph[0], ph[1], ph[2], fs)
        rpm = rotor_rpm_from_phases(f_elec, a.poles)
        keep = t > 30                      # drop the start-up transient
        print(f"    {fs:.0f} Hz, {t[-1]:.0f} s · electrical "
              f"{np.percentile(f_elec[keep],2):.2f}–"
              f"{np.percentile(f_elec[keep],98):.2f} Hz")
        print(f"    → rotor {np.percentile(rpm[keep],2):.0f}–"
              f"{np.percentile(rpm[keep],98):.0f} rpm at {a.poles} poles")
        print(f"\n  ⚠ The DAQ capture and this sweep are DIFFERENT RUNS. They "
              f"cannot be\n    joined point by point without a shared time "
              f"base — see docs/05_integration.md.\n    Reporting the rotor "
              f"range only; per-point Cp needs rotor rpm IN the sweep.\n")
        return 0
    elif a.assume_lambda:
        src = f"ASSUMED constant lambda = {a.assume_lambda}"
        for r in rows:
            r["rpm"] = a.assume_lambda * r["mps"] / a.radius * 60 / (2 * math.pi)
    else:
        raise SystemExit(
            "\n  No rotor speed in " + Path(a.sweep).name + ".\n"
            "  Columns searched: turbine_rpm, turbine_rpm_at_pmax, "
            "rotor_rpm, rpm\n\n"
            "  A sweep that recorded rotor speed needs NO flag — it is found\n"
            "  automatically. So this file did not record any, and no flag\n"
            "  will conjure it. Re-run the sweep with the sensor working.\n\n"
            "  Only if you know what you are doing:\n"
            "    --rpm-column <name>     a differently-named column\n"
            "    --daq <file> --poles N  recovered from the generator phases\n"
            "    --assume-lambda X       ⚠ FABRICATES rotor speed from an\n"
            "                            assumed lambda. The resulting Cp(λ)\n"
            "                            is circular — it can only return the\n"
            "                            lambda you fed it. Never a result.\n\n"
            "  Rotor speed is the measurement that separates rotor "
            "aerodynamics\n  from generator matching. Without it this is "
            "P_max(v), not Cp(lambda).\n")

    # SystemExit, not a traceback. The message is right either way, but a
    # stack trace reads as "the tool broke" rather than "you left a flag off",
    # and the operator is at a rig with the fan running.
    try:
        A_ = swept_area(a.radius, a.hub, a.rotor, a.height)
    except ValueError as e:
        raise SystemExit(f"\n  {e}\n")
    res = compute(rows, a.radius, a.hub, rho, A_)
    if not res:
        raise SystemExit("nothing computable")

    A = swept_area(a.radius, a.hub, a.rotor, a.height)
    geom = (f"{a.rotor.upper()}  R = {a.radius:.4f} m" +
            (f", H = {a.height:.4f} m" if a.rotor == 'vawt'
             else f", hub {a.hub:.4f} m"))
    print(f"\n  {geom} → A = {A:.5f} m²"
          f"   ρ = {rho:.4f} kg/m³")
    print(f"  rotor speed: {src}\n")
    print(f"  {'m/s':>6} {'rotor rpm':>10} {'lambda':>8} {'P (W)':>9} "
          f"{'avail (W)':>10} {'Cp_elec':>9}")
    print(f"  {'-'*6} {'-'*10} {'-'*8} {'-'*9} {'-'*10} {'-'*9}")
    for r in res:
        print(f"  {r['mps']:6.1f} {r['rpm']:10.0f} {r['lam']:8.2f} "
              f"{r['p_w']:9.4f} {r['avail_w']:10.2f} {r['cp_elec']:9.5f}")

    cps = [r["cp_elec"] for r in res]
    best = res[int(np.argmax(cps))]
    print(f"\n  peak Cp_elec = {max(cps):.5f} at λ = {best['lam']:.2f}, "
          f"{best['mps']:.1f} m/s")
    print(f"  ── Cp_elec is Cp_aero × η_gen × η_rect. Do NOT compare it to "
          f"the Betz limit.")
    if a.assume_lambda:
        print(f"\n  ⚠ λ was ASSUMED constant, so every point sits at "
              f"{a.assume_lambda}. This curve\n    shows only how Cp_elec "
              f"would vary with wind speed at fixed λ — it cannot\n    "
              f"locate a peak in λ, which is the entire purpose of Cp(λ).")

    if a.csv:
        out = Path(a.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["# rotor_speed_source", src])
            w.writerow(["# rotor_type", a.rotor])
            w.writerow(["# radius_m", a.radius]); w.writerow(["# height_m", a.height])
            w.writerow(["# rho", rho]); w.writerow(["# area_m2", A])
            w.writerow(["# quantity", "Cp_elec = Cp_aero * eta_gen * eta_rect"])
            w.writerow(["mps", "fan_rpm", "rotor_rpm", "lambda", "p_w",
                        "avail_w", "cp_elec"])
            for r in res:
                w.writerow([f"{r['mps']:.3f}", f"{r.get('fan_rpm',0):.0f}",
                            f"{r['rpm']:.1f}", f"{r['lam']:.4f}",
                            f"{r['p_w']:.5f}", f"{r['avail_w']:.4f}",
                            f"{r['cp_elec']:.6f}"])
        print(f"\n  wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
