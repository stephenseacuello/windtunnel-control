#!/usr/bin/env python3
"""
generator_model.py — fit the generator the rig actually has.

    python src/generator_model.py
    python src/generator_model.py --sweep logs/sweep_v1_Ra20_points.csv --json

The rotor + generator + rectifier behaves as a Thevenin source at every wind
speed tested:

    V(I) = V_oc(v) - I · R_int(v)

Both terms depend on wind speed, and BOTH were guessed before this existed.
The digital twin carried a flat 40 ohm internal resistance; the real value runs
88 ohm at the bottom of the range to 36 ohm at the top, so the guess was 121%
low exactly where the rotor produces least and errors hurt most.

═══════════════════════════════════════════════════════════════════════════
WHY THIS IS TRUSTWORTHY, AND WHERE IT STOPS
═══════════════════════════════════════════════════════════════════════════
Trustworthy: V against I is fitted per wind speed by ordinary least squares
and reported with r². It is above 0.985 at all fourteen. The two fitted
exponents then reproduce the independently measured power law:

    P_max = V_oc² / 4R_int   at the Thevenin match
    so    n = 2a - b   where V_oc ∝ v^a and R_int ∝ v^b

which gives 3.785 against 3.77 measured directly from P_max(v) — a 0.4%
agreement that neither fit was tuned to produce.

Where it stops: R_int here is the WHOLE source impedance — generator winding,
rectifier drop, wiring and the series sense IC together. It is not the winding
resistance. Ohm the winding phase-to-phase to separate them.

And this says nothing about ROTOR SPEED. Converting V_oc to rpm needs the
generator constant, which is unmeasured. The twin still assumes one.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

DEFAULT_SWEEP = "logs/sweep_v1_Ra20_points.csv"


def read_points(path):
    with open(path) as f:
        body = [l for l in f if not l.startswith("#")]
    by = defaultdict(list)
    for r in csv.DictReader(body):
        try:
            if r.get("tracking") not in (None, "", "1", "True", "true"):
                continue
            by[int(float(r["fan_rpm"]))].append(
                (float(r["amps"]), float(r["volts"]),
                 float(r.get("wind_mps") or 0)))
        except (TypeError, ValueError, KeyError):
            continue
    return by


def fit(by_rpm, min_points=4):
    """Per wind speed: V = V_oc - I·R_int by least squares."""
    rows = []
    for rpm in sorted(by_rpm):
        p = by_rpm[rpm]
        I = np.array([x[0] for x in p])
        V = np.array([x[1] for x in p])
        mps = p[0][2]
        m = (V > 0) & (I > 0)
        if m.sum() < min_points:
            continue
        slope, icept = np.polyfit(I[m], V[m], 1)
        if slope >= 0 or icept <= 0:
            continue                      # not a source; do not report it
        pred = icept + slope * I[m]
        ss = ((V[m] - V[m].mean()) ** 2).sum()
        r2 = 1 - ((V[m] - pred) ** 2).sum() / ss if ss > 0 else 0.0
        rows.append({"rpm": rpm, "mps": mps, "n": int(m.sum()),
                     "v_oc": float(icept), "r_int": float(-slope),
                     "r2": float(r2)})
    return rows


def power_law(x, y):
    b, a = np.polyfit(np.log(x), np.log(y), 1)
    return float(np.exp(a)), float(b)


def model(rows):
    v = np.array([r["mps"] for r in rows])
    ka, kb = power_law(v, np.array([r["r_int"] for r in rows]))
    na, nb = power_law(v, np.array([r["v_oc"] for r in rows]))
    return {
        "r_int_coeff": ka, "r_int_exp": kb,
        "v_oc_coeff": na, "v_oc_exp": nb,
        "r_int_lo": rows[0]["r_int"], "r_int_hi": rows[-1]["r_int"],
        "mps_lo": rows[0]["mps"], "mps_hi": rows[-1]["mps"],
        # P_max = V_oc^2 / 4R_int at the match, so the exponent follows.
        "n_predicted": 2 * nb - kb,
        "min_r2": min(r["r2"] for r in rows), "points": len(rows),
    }


def r_int(mps, m):
    """Source resistance at a wind speed, clamped to the measured range."""
    if mps <= 0:
        return m["r_int_lo"]
    lo, hi = min(m["r_int_hi"], m["r_int_lo"]), max(m["r_int_hi"], m["r_int_lo"])
    return float(np.clip(m["r_int_coeff"] * mps ** m["r_int_exp"], lo, hi))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--sweep", default=DEFAULT_SWEEP)
    ap.add_argument("--json", action="store_true", help="emit the model only")
    a = ap.parse_args()

    rows = fit(read_points(a.sweep))
    if len(rows) < 3:
        raise SystemExit(f"only {len(rows)} fittable wind speeds in {a.sweep}")
    m = model(rows)

    if a.json:
        print(json.dumps(m, indent=2))
        return 0

    print(f"\n  V(I) = V_oc − I·R_int, fitted per wind speed — {a.sweep}\n")
    print(f"  {'m/s':>6} {'n':>4} {'V_oc':>8} {'R_int Ω':>9} {'r²':>8}")
    print(f"  {'-'*6} {'-'*4} {'-'*8} {'-'*9} {'-'*8}")
    for r in rows:
        print(f"  {r['mps']:>6.1f} {r['n']:>4} {r['v_oc']:>8.2f} "
              f"{r['r_int']:>9.1f} {r['r2']:>8.4f}")

    print(f"\n  R_int = {m['r_int_coeff']:.1f} · v^{m['r_int_exp']:.3f}"
          f"     {m['r_int_lo']:.1f} Ω at {m['mps_lo']:.1f} m/s "
          f"→ {m['r_int_hi']:.1f} Ω at {m['mps_hi']:.1f} m/s")
    print(f"  V_oc  = {m['v_oc_coeff']:.3f} · v^{m['v_oc_exp']:.3f}")
    print(f"\n  worst r² across {m['points']} wind speeds: {m['min_r2']:.4f}")
    print(f"\n  CROSS-CHECK — P_max = V_oc²/4R_int at the Thévenin match,")
    print(f"  so n = 2a − b = {m['n_predicted']:.3f}, against 3.77 measured")
    print(f"  directly from P_max(v). Neither fit was tuned to produce that.")
    print(f"\n  R_int is the WHOLE source impedance — winding, rectifier,")
    print(f"  wiring and the sense IC together. Ohm the winding to separate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
