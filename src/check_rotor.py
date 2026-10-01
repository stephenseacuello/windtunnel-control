#!/usr/bin/env python3
"""
check_rotor.py — is the rotor-speed sensor telling the truth?

    python src/check_rotor.py logs/sweep_v1_Ra20_repeat_points.csv

Run this on the FIRST sweep after touching the rotor-speed sensor, before
trusting any Cp that comes out of it.

═══════════════════════════════════════════════════════════════════════════
WHAT IT CHECKS, AND WHY THAT ONE THING
═══════════════════════════════════════════════════════════════════════════
The generator is a permanent-magnet machine, so its open-circuit voltage is
proportional to rotor speed:

    V_oc = K · rotor_rpm         K constant, set by magnets and turns

K is a property of the GENERATOR. It cannot depend on wind speed, on load, or
on which blade is fitted. So if K comes out constant across the wind range,
two independent instruments — the electronic load and the reed sensor — agree
about rotor speed at fourteen operating points. If it does not, one of them is
lying, and the shape says which.

    K constant           ✅ sensor is good
    K RISES with wind    ⚠️ MISSING counts. K = V_oc/rotor_rpm, so a rotor
                            speed that reads low pushes K up. This is the
                            reed running out of bandwidth, and it is the
                            reed's known failure mode.
    K FALLS with wind    ⚠️ EXTRA counts — contact bounce, more passes seen
                            than happened, so rotor_rpm reads high.
    K scattered          ⚠️ bounce that varies pass to pass. This is what the
                            VJ12-D10K did: 28 counts over 10 revolutions, and
                            not the same 2.8 twice.

Get the sign the right way round. K is V_oc **divided by** rotor rpm, so the
sensor error and the K error move in OPPOSITE directions, and reading it
backwards sends you to fix the opposite problem.

── what a rotor-speed error actually breaks ──
Cp_elec = P / (½ρAv³) contains **no rotor speed at all**, so a bad sensor does
not change Cp by even a percent. What it moves is λ = ωR/v — the horizontal
axis. A curve built on a sensor that misses counts is the right Cp curve slid
to the left, and its peak is reported at a λ the rotor never ran at.

That matters because "Cp peaks at λ = 2.8" is a headline number and the whole
point of measuring rotor speed. But it also means **P_max(v) — every result
banked so far — is untouched by this.** The reed gates Cp(λ) and nothing else.

A fixed error in K is harmless for comparing blades: it cancels. A
wind-DEPENDENT one does not cancel, and it distorts the λ axis differently at
each wind speed, which no later correction can undo.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def read_points(path):
    """Group a *_points.csv by fan setpoint, keeping volts, amps, rotor rpm."""
    with open(path) as f:
        body = [l for l in f if not l.startswith("#")]
    rdr = csv.DictReader(body)
    cols = rdr.fieldnames or []
    rpm_col = next((c for c in ("turbine_rpm", "rotor_rpm", "rpm")
                    if c in cols), None)
    by = defaultdict(list)
    for r in rdr:
        try:
            by[int(float(r.get("fan_rpm") or 0))].append((
                float(r["amps"]), float(r["volts"]),
                float(r.get("wind_mps") or 0),
                float(r[rpm_col]) if rpm_col and r.get(rpm_col) else None))
        except (TypeError, ValueError, KeyError):
            continue
    return by, rpm_col, cols


def open_circuit_row(pts):
    """
    The lightest-loaded dwell that carries a rotor speed: (volts, amps, rpm).

    ── why volts and rpm must come from the SAME row ──
    K = V_oc/rotor_rpm is only a generator constant if both numbers describe
    the same instant. They do not describe the same instant if the voltage is
    taken at open circuit and the speed is averaged over the whole ladder,
    because **the rotor slows as current is drawn — that is where the power
    comes from.** Pairing an unloaded voltage with a loaded mean speed inflates
    K by the droop, and the ladder loads harder at high wind (0.03 W at the
    bottom of the range against 3.8 W at the top), so the inflation GROWS with
    wind speed and reads exactly like a sensor losing counts.

    This was the original implementation and it was wrong: fed a
    mathematically perfect sensor built on the real banked ladder, it reported
    a 26% spread and told the operator to replace the reed. The rig's own
    StallGuard tolerates a 60% droop as normal, so the gradient needed to
    trigger the false alarm is well inside routine operation.

    Not extrapolated to true zero current. The ladder's first dwell is within
    a few mV of open circuit, and extrapolating would import the Thevenin
    fit's assumptions into a test whose entire value is being independent of
    them. The residual I*R_int is a fixed offset in K, and this test reads the
    TREND in K, which a fixed offset cannot move.
    """
    have = [p for p in pts if p[3]]
    if not have:
        return None, 0
    lo = min(have, key=lambda p: p[0])
    # How many LIGHTER dwells had no rotor speed at all. This is not
    # bookkeeping: the rotor is fastest at the lightest load, so a reed that
    # drops out at speed drops out HERE FIRST. Silently sliding down to a more
    # heavily loaded row hides the dropout and makes the remaining points look
    # consistent — the tool would certify the sensor precisely when it is
    # failing, and in the direction this rig actually fails.
    skipped = sum(1 for p in pts if p[0] < lo[0] and not p[3])
    return (lo[1], lo[0], lo[3]), skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("points", help="a *_points.csv from blade_sweep.py")
    ap.add_argument("--droop-pct", type=float, default=10.0,
                    help="flag if K drifts more than this %% across the range")
    a = ap.parse_args()

    if not Path(a.points).exists():
        raise SystemExit(f"\n  no such file: {a.points}\n")

    by, rpm_col, cols = read_points(a.points)
    if not by:
        raise SystemExit(f"\n  no usable rows in {a.points}\n")

    if rpm_col is None:
        print(f"\n  ⛔ no rotor-speed column in {Path(a.points).name}")
        print(f"     looked for: turbine_rpm, rotor_rpm, rpm")
        print(f"     found:      {', '.join(cols)}")
        print(f"\n  This sweep carries no rotor speed, so there is nothing to")
        print(f"  check and no Cp(λ) can come from it. That is not a bug in")
        print(f"  the file — it is a sweep run before the sensor worked, and")
        print(f"  it cannot be repaired after the fact. Re-run it.\n")
        return 2

    print(f"\n  rotor speed from column '{rpm_col}'")
    print(f"  K = V_oc / rotor_rpm — a GENERATOR constant. It must not depend")
    print(f"  on wind speed.\n")
    print(f"  {'fan rpm':>8} {'m/s':>6} {'V_oc':>7} {'at A':>7} "
          f"{'rotor rpm':>10} {'K (mV/rpm)':>11}")
    print(f"  {'-'*8} {'-'*6} {'-'*7} {'-'*7} {'-'*10} {'-'*11}")

    ks, missing, dropped, dead = [], 0, {}, []
    for fan in sorted(by):
        pts = by[fan]
        mps = pts[0][2]
        row, skipped = open_circuit_row(pts)
        dropped[fan] = skipped
        if row is None:
            missing += 1
            dead.append(fan)
            print(f"  {fan:>8} {mps:>6.1f} {'—':>7} {'—':>7} "
                  f"{'—':>10} {'—':>11}")
            continue
        v_oc, at_a, rpm = row
        if v_oc <= 0 or rpm <= 0:
            missing += 1
            print(f"  {fan:>8} {mps:>6.1f} {v_oc:>7.3f} {at_a:>7.4f} "
                  f"{rpm:>10.1f} {'—':>11}")
            continue
        k = 1000.0 * v_oc / rpm
        ks.append((mps, k))
        print(f"  {fan:>8} {mps:>6.1f} {v_oc:>7.3f} {at_a:>7.4f} "
              f"{rpm:>10.1f} {k:>11.3f}")

    blanked = {f: k for f, k in dropped.items() if k}
    if blanked:
        print(f"\n  ⚠ at {len(blanked)} wind speed(s) the LIGHTEST dwells "
              f"carry no rotor speed:")
        for f in sorted(blanked):
            print(f"       fan {f}: {blanked[f]} lighter dwell(s) blank")
        print(f"\n    The rotor turns fastest at the lightest load, so this is "
              f"where a reed\n    running out of bandwidth drops out FIRST. "
              f"Treating those as missing data\n    and using a more heavily "
              f"loaded row makes the rest look consistent —\n    which is the "
              f"tool certifying the sensor at the moment it is failing.")
        print(f"    Read a green verdict below with that in mind.")

    if len(ks) < 3:
        print(f"\n  ⛔ only {len(ks)} wind speed(s) carry rotor speed — not")
        print(f"     enough to say whether K is constant.\n")
        return 2

    vals = [k for _, k in ks]
    med = statistics.median(vals)
    spread = 100.0 * (max(vals) - min(vals)) / med
    lo_half = statistics.median([k for _, k in ks[:len(ks) // 2]])
    hi_half = statistics.median([k for _, k in ks[len(ks) // 2:]])
    trend = 100.0 * (hi_half - lo_half) / med

    print(f"\n  K median {med:.3f} mV/rpm, spread {spread:.1f}% of median")
    print(f"  low-wind half {lo_half:.3f} → high-wind half {hi_half:.3f} "
          f"({trend:+.1f}%)")
    # ── whole wind speeds with NO rotor speed ────────────────────────────
    # WHERE they sit decides what they mean, and the two readings call for
    # opposite actions:
    #
    #   at the TOP of the range   the rotor is fastest there, so this is the
    #                             sensor's bandwidth ceiling. Fatal for Cp
    #                             above the break.
    #   at the BOTTOM             the rotor is barely turning and genuinely
    #                             produces no pulses. Real data about a real
    #                             state, and not a fault.
    #
    # Counting them without locating them made whole-speed dropout — the more
    # severe failure — score BETTER than partial dropout, because `blanked`
    # only ever saw wind speeds that still had a surviving row.
    ceiling = []
    if dead and ks:
        live_fans = [f for f in sorted(by) if f not in dead]
        if live_fans:
            ceiling = [f for f in dead if f > max(live_fans)]
    if missing:
        low = [f for f in dead if f not in ceiling]
        print(f"  {missing} wind speed(s) had no rotor speed at all"
              f"{'' if not dead else ': ' + ', '.join(str(f) for f in dead)}")
        if low:
            print(f"     fan {', '.join(str(f) for f in low)} sit BELOW the "
                  f"working range — a rotor that is\n     barely turning "
                  f"makes no pulses, which is a real state, not a fault.")

    print()
    if ceiling:
        print(f"  ⛔ NO rotor speed at ALL above fan {min(ceiling)} "
              f"({', '.join(str(f) for f in ceiling)}).")
        print(f"\n     The rotor turns fastest at the highest wind, so losing "
              f"whole wind\n     speeds at the TOP of the range is the "
              f"sensor's bandwidth ceiling —\n     not missing data. K "
              f"computed from what survived is flat because\n     the hard "
              f"points are gone, which is survivorship, not agreement.")
        print(f"\n     **fan {min(ceiling)} is the reed's ceiling. Cp(λ) is "
              f"good BELOW it and\n     meaningless above it.** Raise RPMGAP, "
              f"or fit a sensor that can\n     follow the rotor at speed, "
              f"then re-run.")
        print()
        return 1

    if abs(trend) <= a.droop_pct and spread <= 2 * a.droop_pct:
        if blanked:
            # A flat K computed only from the rows that survived is not
            # evidence the sensor is good. Dropout REMOVES the fast points
            # rather than corrupting them, so the survivors agree beautifully
            # and the trend test sees nothing. Reporting "trustworthy" here
            # would be the tool at its most confidently wrong.
            print(f"  ⚠ K is flat ({spread:.1f}%) across the dwells that "
                  f"HAVE a rotor speed —")
            print(f"     but {len(blanked)} wind speed(s) are missing their "
                  f"fastest ones, so that")
            print(f"     flatness is survivorship, not agreement. The check "
                  f"cannot pass on")
            print(f"     this run.")
            print(f"\n     Raise RPMGAP or fit a faster sensor, then re-run. "
                  f"If the blanks\n     persist above a particular wind speed, "
                  f"that speed is the reed's\n     ceiling and Cp(λ) is only "
                  f"good below it.")
            return 1
        print(f"  ✅ K is constant to within {spread:.1f}%. The load and the")
        print(f"     rotor sensor agree at {len(ks)} operating points, and")
        print(f"     they share no hardware. Rotor speed is trustworthy —")
        print(f"     Cp(λ) from this run means something.")
        print(f"\n     Note: this tests whether K is CONSTANT, not whether it "
              f"is RIGHT.\n     A debounce that counts every pass exactly "
              f"twice gives a perfectly\n     flat K at half its true value "
              f"and a doubled λ. Only the 10-turn\n     hand count settles "
              f"the scale.")
        return 0

    if trend > a.droop_pct:
        print(f"  ⚠️  K RISES {trend:+.1f}% toward high wind, so rotor speed")
        print(f"     reads LOW where the rotor turns fastest. The sensor is")
        print(f"     MISSING counts — it is out of bandwidth.")
        print(f"\n     λ = ωR/v is therefore too small at high wind and the")
        print(f"     Cp(λ) curve is squashed toward the origin. Cp itself is")
        print(f"     unaffected — no rotor speed enters it — so the curve")
        print(f"     will look entirely believable at the wrong λ.")
        print(f"\n     The VJ12-D10K is rated 20 Hz on its own packaging.")
        print(f"     This rotor needs ~37 Hz at the BOTTOM of the wind "
              f"range and\n     308 Hz at fan 1800 (18,500 rpm, measured "
              f"1 Sept) — a 15x shortfall.\n     No capacitor and no debounce "
              f"closes that; a faster sensor does.")
    elif trend < -a.droop_pct:
        print(f"  ⚠️  K FALLS {trend:+.1f}% toward high wind, so rotor speed")
        print(f"     reads HIGH: EXTRA counts per magnet pass. Contact bounce,")
        print(f"     getting worse as passes come faster. More filtering —")
        print(f"     step up one capacitor value.")
    else:
        print(f"  ⚠️  K scatters {spread:.1f}% with no clean trend, which is")
        print(f"     bounce that varies pass to pass — the hardest kind to")
        print(f"     correct, because no fixed divisor fixes it.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
