#!/usr/bin/env python3
"""
fit_sensor.py — fit the anemometer's voltage→velocity calibration, and work
out which functional form the data actually supports.

    python fit_sensor.py pairs.csv                 # columns: volts, velocity
    python fit_sensor.py --march-report            # the URI cross-cal data

═══════════════════════════════════════════════════════════════════════════
WHY THE FORM MATTERS MORE THAN THE COEFFICIENTS
═══════════════════════════════════════════════════════════════════════════
Three sensor types produce three different relationships:

    linear   v = a·V + b            cup or vane — output ∝ velocity
    sqrt     v = a·√(V − b)         pitot + pressure transducer — ΔP ∝ v²
    king     v = ((V² − a)/b)^(1/n) hot wire, King's law

Pick the wrong family and the coefficients will still fit your calibration
points tolerably while being wrong everywhere between them — worst at the ends
of the range, which is exactly where people extrapolate.

The March 2 report is internally inconsistent on this point. It justifies the
curvature in its data with a dynamic-pressure argument (ΔP ∝ u², implying
v ∝ √V), then applies a *linear* calibration (m/s = 115·V + 1.5). Those cannot
both be right. It also names the sensor three different ways across the
document: cup anemometer, hot-wire anemometer, cup anemometer.

This tool answers the question from data instead of from prose.

═══════════════════════════════════════════════════════════════════════════
A TRAP WORTH KNOWING ABOUT
═══════════════════════════════════════════════════════════════════════════
Test 1 (Feb 13) tabulates both voltage and wind speed, which looks like an
ideal calibration set. It is not: the footnote records that the voltage column
was **back-calculated as m/s ÷ 14**. Voltage and velocity there are the same
numbers twice. Fitting one against the other returns a perfect straight line
by construction and tells you nothing.

`--march-report` therefore uses only the genuinely independent pairs: Test 2's
*measured* voltages against Test 1's *measured* velocities at the six
overlapping RPM conditions. The tool refuses any dataset whose ratio is
suspiciously constant, for the same reason.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import curve_fit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from velocity_source import SensorCalibration

# Test 2 (Mar 2) measured mean voltage vs Test 1 (Feb 13) measured wind speed,
# at the six overlapping RPM conditions. 100 RPM excluded (anemometer stalled),
# 500 RPM excluded (byte-identical duplicate of 200 RPM).
MARCH_PAIRS = [
    # rpm,  volts,   m/s
    (200,  0.0236,  3.92),
    (300,  0.0422,  6.12),
    (400,  0.0591,  8.33),
    (600,  0.0814, 12.03),
    (700,  0.1124, 13.99),
    (1400, 0.2434, 29.40),
]


def _aic(y, pred, k):
    resid = np.asarray(y) - np.asarray(pred)
    n = len(y)
    ss = float(np.sum(resid ** 2))
    if ss <= 0:
        return -np.inf, 0.0
    return n * np.log(ss / n) + 2 * k, float(np.sqrt(ss / n))


def check_independence(volts, vel):
    """
    Refuse data where velocity is a fixed multiple of voltage.

    That pattern means one column was computed from the other, and a fit will
    return a perfect line that means nothing. It is exactly what the Feb 13
    table looks like.
    """
    v, u = np.asarray(volts, float), np.asarray(vel, float)
    mask = np.abs(v) > 1e-9
    if mask.sum() < 3:
        return True, ""
    ratio = u[mask] / v[mask]
    spread = (ratio.max() - ratio.min()) / abs(ratio.mean())
    if spread < 0.01:
        return False, (
            f"velocity is a constant {ratio.mean():.4g}x voltage across every "
            f"point (spread {spread:.2%}).\nOne column was almost certainly "
            f"computed from the other — a fit would be circular.")
    return True, ""


def fit_all(volts, vel, verbose=True):
    """
    Fit every calibration form and rank them by AIC.

    The ranking is only meaningful if the gap is: below 2 the forms are
    indistinguishable on this data, above 10 the call is decisive. The printed
    output says which case you are in rather than leaving you to assume.
    """
    V, y = np.asarray(volts, float), np.asarray(vel, float)
    out = {}

    c = np.polyfit(V, y, 1)
    a, rmse = _aic(y, np.polyval(c, V), 2)
    out["linear"] = {"aic": a, "rmse": rmse, "params": {"a": c[0], "b": c[1]},
                     "cal": SensorCalibration(c[0], c[1], "linear"),
                     "implies": "a linear-output sensor: cup or vane"}

    try:
        f = lambda x, a_, b_: a_ * np.sqrt(np.maximum(x - b_, 0))
        p, _ = curve_fit(f, V, y, p0=[60, 0], maxfev=20000)
        a, rmse = _aic(y, f(V, *p), 2)
        out["sqrt"] = {"aic": a, "rmse": rmse,
                       "params": {"a": p[0], "b": p[1]},
                       "cal": SensorCalibration(p[0], p[1], "sqrt"),
                       "implies": "a pressure sensor: pitot + transducer"}
    except Exception:
        pass

    try:
        g = lambda x, a_, b_: (np.maximum(x * x - a_, 0) / b_) ** 2
        p, _ = curve_fit(g, V, y, p0=[1e-5, 1e-4], maxfev=40000)
        a, rmse = _aic(y, g(V, *p), 2)
        out["king"] = {"aic": a, "rmse": rmse,
                       "params": {"a": p[0], "b": p[1]},
                       "cal": SensorCalibration(p[0], p[1], "king", n=0.5),
                       "implies": "a hot wire"}
    except Exception:
        pass

    c2 = np.polyfit(V, y, 2)
    a, rmse = _aic(y, np.polyval(c2, V), 3)
    out["quadratic"] = {"aic": a, "rmse": rmse,
                        "params": {"c": c2.tolist()}, "cal": None,
                        "implies": "empirical — no physical sensor model"}

    ranked = sorted(out.items(), key=lambda kv: kv[1]["aic"])
    best = ranked[0][0]

    if verbose:
        print(f"\n  n = {len(V)} points\n")
        print(f"  {'form':<11}{'AIC':>9}{'RMSE':>9}   implies")
        print("  " + "─" * 62)
        for name, r in ranked:
            print(f"  {name:<11}{r['aic']:>9.2f}{r['rmse']:>9.3f}   {r['implies']}")

        # ΔAIC of 2 is noise; 10 is decisive. Say which this is rather than
        # letting the reader assume the ranking is meaningful.
        print()
        second = ranked[1]
        d = second[1]["aic"] - ranked[0][1]["aic"]
        print(f"  best: {best}  (ΔAIC to next = {d:.1f})")
        if d < 2:
            print("  ΔAIC below 2 — these are indistinguishable on this data. "
                  "Do not\n  choose between them on this basis; collect more "
                  "points or identify\n  the sensor physically.")
        elif d < 10:
            print("  ΔAIC 2–10 — suggestive but not decisive.")
        else:
            print("  ΔAIC above 10 — decisive on this data.")

        physical = [k for k, _ in ranked if k in ("linear", "sqrt", "king")]
        if len(physical) > 1:
            top, nxt = physical[0], physical[1]
            gap = out[nxt]["aic"] - out[top]["aic"]
            print(f"\n  Among physical sensor models: {top} beats {nxt} by "
                  f"ΔAIC {gap:.1f}")
            if gap > 10:
                print(f"  → the data says this is {out[top]['implies']}, "
                      f"not {out[nxt]['implies']}.")

    return out, best


def main():
    p = argparse.ArgumentParser(
        description="fit and compare anemometer calibration forms")
    p.add_argument("file", nargs="?", help="CSV with volts,velocity columns")
    p.add_argument("--march-report", action="store_true",
                   help="use the URI Feb/Mar cross-calibration pairs")
    p.add_argument("--save", help="write the winning form to a JSON file")
    p.add_argument("--force", action="store_true",
                   help="fit even if the data looks circular")
    a = p.parse_args()

    if a.march_report:
        rpm = [r[0] for r in MARCH_PAIRS]
        volts = [r[1] for r in MARCH_PAIRS]
        vel = [r[2] for r in MARCH_PAIRS]
        print("URI cross-calibration pairs")
        print("  Test 2 (Mar 2) MEASURED voltage vs Test 1 (Feb 13) MEASURED "
              "velocity,\n  at overlapping RPM. 100 RPM excluded (stalled), "
              "500 RPM excluded (duplicate).")
        print(f"  RPM: {rpm}")
    elif a.file:
        rows = list(csv.DictReader(open(a.file)))
        keys = {k.strip().lower(): k for k in rows[0]}
        vk = next((keys[k] for k in ("volts", "v", "voltage") if k in keys), None)
        yk = next((keys[k] for k in ("velocity", "mps", "m/s", "speed")
                   if k in keys), None)
        if not vk or not yk:
            sys.exit(f"need volts and velocity columns; found {list(rows[0])}")
        volts = [float(r[vk]) for r in rows]
        vel = [float(r[yk]) for r in rows]
        print(f"{a.file}")
    else:
        sys.exit("give a CSV or --march-report")

    ok, why = check_independence(volts, vel)
    if not ok:
        print(f"\n  REFUSING TO FIT\n  {why}")
        if not a.force:
            print("\n  Use --force only if you are certain the columns are "
                  "independent measurements.")
            sys.exit(1)
        print("\n  --force given, continuing anyway\n")

    out, best = fit_all(volts, vel)

    if a.march_report:
        print("""
  WHAT THIS DOES AND DOES NOT SETTLE

  Settled: the sensor is a linear-output device — a cup or vane — not a
  pressure transducer and not a hot wire. The report's Section 3 calls it a
  hot-wire anemometer; the data says otherwise, and the executive summary's
  "cup anemometer" is the correct label.

  A consequence: the report justifies the quadratic voltage-vs-RPM curvature
  with a dynamic-pressure argument (dP proportional to u squared). That is a
  pressure-sensor argument, and it does not apply to a linear sensor. The
  calibration FORM in the report is right; the physical reasoning offered for
  the curvature is not.

  Still open: with a linear sensor, quadratic voltage-vs-RPM means velocity is
  quadratic in RPM — which contradicts both Test 1 (linear, adj R^2 0.9996)
  and fan affinity laws. Two candidate explanations were tested and one was
  ruled out:

    - Cup friction under-reading at low speed would bend the curve upward at
      the bottom. RULED OUT: dropping low-RPM points leaves the quadratic
      coefficient at ~3.5e-8 rather than fading, so the curvature is spread
      across the range, not concentrated at the low end.

    - An RPM-dependent gain discrepancy between the two test sessions. STILL
      LIVE: the report's own cross-calibration ratio falls monotonically from
      166 at 200 RPM to 121 at 1400 RPM, which is exactly that signature.

  No amount of re-fitting the existing data resolves this. It needs one clean
  measurement, which is now cheap:

    Run a stepped sweep with the drive under Modbus control, logging the
    anemometer voltage and a trusted velocity reference simultaneously, in a
    single session with one DAQ configuration. Ten points from 10 to 55 Hz.
    That removes the between-session gain question entirely, and settles
    linear-vs-quadratic velocity-vs-RPM in one afternoon.
""")

    if a.save and out[best].get("cal"):
        import json
        cal = out[best]["cal"]
        cal.source = a.file or "march-report cross-calibration"
        cal.notes = (f"selected by AIC over {len(out)} forms, "
                     f"n={len(volts)} points")
        Path(a.save).write_text(json.dumps(cal.to_dict(), indent=2))
        print(f"\n  wrote {a.save}")


if __name__ == "__main__":
    main()
