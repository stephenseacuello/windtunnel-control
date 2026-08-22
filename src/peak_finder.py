#!/usr/bin/env python3
"""
peak_finder.py — find the most current a turbine will give up, then back off.

    from peak_finder import find_peak
    result = find_peak(load, max_amps=0.6, step_frac=0.05, dwell=3.0)
    result.peak_amps      # the last setpoint the rotor sustained
    result.operating_amps # 80% of it — where you actually run
    result.trace          # every step, for the log

═══════════════════════════════════════════════════════════════════════════
WHAT IT IS LOOKING FOR
═══════════════════════════════════════════════════════════════════════════
At a fixed wind speed, walk the constant-current demand up from a light load.
The rotor slows as the braking torque rises. Three things happen in order:

    1. current tracks demand, voltage falls slowly     — light, stable
    2. electrical power peaks, then starts falling     — past peak Cp
    3. the rotor can no longer hold; speed and voltage
       collapse and measured current falls away from
       the demand entirely                             — STALL

Point 3 is the thing this finds. It is not a gentle maximum. Torque
coefficient is Cp/λ, and dividing by λ moves the maximum to a lower λ than
Cp's own — so peak current sits deeper into stall than peak power, and by the
time you reach it there is nothing left to arrest the collapse. In constant
current the rotor does not roll over, it falls off.

So "the peak" here means **the last demand the rotor sustained**, which is the
stall threshold. 80% of it is a working margin below that threshold. That is
an operating-envelope measurement, and it is a different thing from a Cp
curve — for Cp you want the *power* peak, which this also records, and rotor
RPM, which this cannot see.

═══════════════════════════════════════════════════════════════════════════
WHY THE STEP IS A FRACTION AND NOT A FIXED 10 mA
═══════════════════════════════════════════════════════════════════════════
Current at the stall threshold goes roughly as v². Across a 500 → 1800 rpm
fan sweep that is 10.2 → 38.0 m/s, a factor of 14 in current. A fixed 10 mA
step gives about 33 points at the top of that range and **two** at the bottom.

    step = max(min_step, step_frac × largest current seen so far)

gives the same *relative* resolution at every wind speed — around 1/step_frac
points to the threshold, wherever the threshold happens to be. The instrument
resolves 0.1 mA in every range, measured, so min_step is a floor chosen for
the physics rather than one the hardware forces.

═══════════════════════════════════════════════════════════════════════════
IT NEVER COMMANDS ZERO
═══════════════════════════════════════════════════════════════════════════
Zero amps in constant current is, to a spinning rotor, an open circuit — the
runaway condition `TurbineInterlock` exists to prevent. On recovery from a
stall this drops to `floor_amps`, not to zero, and lets the rotor come back up
under load. A caller stepping wind speed between runs should do the same:
raise the wind with the load still on, never unload between points.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field


class PeakFinderError(RuntimeError):
    pass


@dataclass
class Step:
    """One dwell point."""
    demand_a: float
    volts: float
    amps: float
    watts: float
    t_unix: float = 0.0     # wall clock at the MEASUREMENT, for DAQ merging
    held_a: float | None = None
    tracking: bool = True
    note: str = ""


@dataclass
class PeakResult:
    peak_amps: float = 0.0          # largest SUSTAINED current
    peak_volts: float = 0.0
    peak_watts_at_peak: float = 0.0
    power_peak_amps: float = 0.0    # where V*I was largest — NOT the same point
    power_peak_watts: float = 0.0
    power_peak_volts: float = 0.0
    fit_watts: float = 0.0          # parabolic fit — use THIS to compare blades
    fit_amps: float = 0.0
    fit_points: int = 0
    operating_amps: float = 0.0     # the fraction of peak you actually run at
    operating: Step | None = None
    stopped_by: str = ""
    stalled: bool = False
    limited_by: str = ""            # rotor | ceiling | power
    censored: bool = False          # peak is a LOWER BOUND — ramp stopped short
    power_peak_ratio: float = 0.0   # power peak / threshold; ~0.67 when healthy
    unloaded: bool = False          # the rotor is open-circuit right now
    rolled_off: bool = False        # stopped cleanly on the power roll-off
    volt_off: float = 0.0
    trace: list = field(default_factory=list)

    def refine(self, span=2):
        """
        Locate the power peak by fitting a parabola, not by taking the argmax.

        The top of P(I) is flat: at 1700 rpm on the first full sweep every
        point from 0.21 to 0.30 A sat within 4% of the same power. Over a
        plateau like that `argmax` reports whichever sample happened to read
        highest, so it

          · jitters in POSITION by ±20% run to run, and
          · is biased HIGH in VALUE, because the maximum of N noisy samples
            exceeds the true maximum by more as N grows.

        The second one is what makes it a campaign problem rather than an
        annoyance. Two blades sampled with different numbers of points near
        their peaks carry different upward biases, and the difference between
        them is then partly an artefact of how many dwells each got.

        A least-squares parabola through the points either side uses all of
        them instead of the luckiest one. Falls back to the argmax if there
        are too few points or the fit is not concave.
        """
        pts = [(t.amps, t.watts) for t in self.trace if t.tracking and t.amps > 0]
        if len(pts) < 2 * span + 1:
            self.fit_watts, self.fit_amps = self.power_peak_watts, self.power_peak_amps
            return self
        k = max(range(len(pts)), key=lambda j: pts[j][1])
        lo, hi = max(0, k - span), min(len(pts), k + span + 1)
        window = pts[lo:hi]
        if len(window) < 3:
            self.fit_watts, self.fit_amps = self.power_peak_watts, self.power_peak_amps
            return self
        n = len(window)
        sx = [sum(i ** m for i, _ in window) for m in range(5)]
        sy = [sum(w * i ** m for i, w in window) for m in range(3)]
        # normal equations for a quadratic, solved by hand to avoid numpy here
        A = [[sx[4], sx[3], sx[2]], [sx[3], sx[2], sx[1]], [sx[2], sx[1], n]]
        b = [sy[2], sy[1], sy[0]]
        det = (A[0][0] * (A[1][1] * A[2][2] - A[1][2] * A[2][1])
               - A[0][1] * (A[1][0] * A[2][2] - A[1][2] * A[2][0])
               + A[0][2] * (A[1][0] * A[2][1] - A[1][1] * A[2][0]))
        if abs(det) < 1e-18:
            self.fit_watts, self.fit_amps = self.power_peak_watts, self.power_peak_amps
            return self

        def solve(col):
            M = [row[:] for row in A]
            for r in range(3):
                M[r][col] = b[r]
            return (M[0][0] * (M[1][1] * M[2][2] - M[1][2] * M[2][1])
                    - M[0][1] * (M[1][0] * M[2][2] - M[1][2] * M[2][0])
                    + M[0][2] * (M[1][0] * M[2][1] - M[1][1] * M[2][0])) / det

        a2, a1, a0 = solve(0), solve(1), solve(2)
        if a2 >= 0:                       # not concave — no maximum to find
            self.fit_watts, self.fit_amps = self.power_peak_watts, self.power_peak_amps
            return self
        i_hat = -a1 / (2 * a2)
        if not (window[0][0] <= i_hat <= window[-1][0]):
            self.fit_watts, self.fit_amps = self.power_peak_watts, self.power_peak_amps
            return self
        self.fit_amps = i_hat
        self.fit_watts = a2 * i_hat ** 2 + a1 * i_hat + a0
        self.fit_points = len(window)
        return self

    @property
    def clean(self):
        """Stopped the way the protocol intends: past the power peak, no stall."""
        return self.rolled_off

    @property
    def found(self):
        return self.stalled or self.rolled_off or \
            self.stopped_by.startswith("rollover")

    def summary(self):
        out = [
            f"  peak sustained : {self.peak_amps:.4f} A at "
            f"{self.peak_volts:.3f} V  ({self.peak_watts_at_peak:.3f} W)",
            f"  peak POWER     : {self.fit_watts:.4f} W at "
            f"{self.fit_amps:.4f} A   (parabola, {self.fit_points} pts)",
            f"    raw argmax   : {self.power_peak_watts:.4f} W at "
            f"{self.power_peak_amps:.4f} A, {self.power_peak_volts:.3f} V "
            f"— biased high, do not compare blades on this",
            f"  operating point: {self.operating_amps:.4f} A",
            f"  stopped by     : {self.stopped_by}",
        ]
        if self.power_peak_amps and self.peak_amps:
            r = self.power_peak_amps / self.peak_amps
            out.append(f"  power peak sits at {r * 100:.0f}% of the threshold")
        out.append(f"  limited by     : {self.limited_by}")
        if self.limited_by == "load-cutout":
            out.append(
                f"\n  ⚠ THE ROTOR NEVER LET GO — this is the LOAD's limit.\n"
                f"    Measured current was still tracking demand exactly when "
                f"the ramp\n    stopped; the terminal voltage just fell under "
                f"CONF:VOLT:OFF "
                f"({self.volt_off:.2f} V)\n    first. The rotor's stall "
                f"threshold is higher and was not reached.\n"
                f"    That may be the right answer anyway: below the cut-out "
                f"there is\n    barely any power left to have. But do not "
                f"record it as a stall.")
        elif self.censored:
            out.append(
                f"\n  ⚠ CENSORED — this is a LOWER BOUND, not the threshold.\n"
                f"    The power peak sits at {self.power_peak_ratio * 100:.0f}% "
                f"of it. A ramp that actually\n"
                f"    reached the rotor's limit lands near 67% — torque peaks "
                f"well past\n"
                f"    power. So this one stopped short, at "
                f"{self.peak_volts:.2f} V with CONF:VOLT:OFF\n"
                f"    at {self.volt_off:.2f} V: the load quit before the rotor "
                f"did. The turbine's\n"
                f"    real threshold is HIGHER and was never seen.\n"
                f"    Lower it (--volt-off) and repeat, or record this point as "
                f"censored.")
        if self.unloaded:
            out.append(
                "\n  ⚠ The rotor is OPEN CIRCUIT as of the last dwell — current\n"
                "    went to zero while voltage rose toward open circuit. That "
                "is the\n"
                "    runaway condition. The floor load below re-loads it; do "
                "not leave\n"
                "    the rig here.")
        return "\n".join(out)


def find_peak(load, *, max_amps, floor_amps=0.005, min_step=0.001,
              step_frac=0.05, dwell=3.0, operate_frac=0.80,
              v_floor=1.0, max_watts=None, range_="low",
              tol_frac=0.15, tol_abs=0.002, collapse_frac=0.70,
              confirm=2, censor_shape=0.85, stop_power_frac=None,
              settle=None, on_step=None):
    """
    Ramp the demand up until the rotor lets go, then settle at a fraction of it.

    Args:
        max_amps:      hard ceiling. The ramp stops here whatever happens —
                       this is the backstop for a source that never rolls over.
        floor_amps:    the light load held between phases. NEVER zero.
        min_step:      smallest demand increment.
        step_frac:     step as a fraction of the largest current seen, so the
                       resolution is relative rather than absolute.
        dwell:         seconds at each step before measuring. Must be several
                       rotor time constants or you measure the transient.
        operate_frac:  where to settle afterwards, as a fraction of peak.
        v_floor:       abort if terminal voltage reaches this. Pass the
                       instrument's own CONF:VOLT:OFF — below it the load stops
                       sinking and every reading afterwards is a zero.
        collapse_frac: measured current below this fraction of the running
                       maximum counts as a collapse.
        confirm:       consecutive bad dwells before believing a collapse. One
                       is a transient; two in a row is the rotor.
        stop_power_frac: stop once measured power has fallen to this fraction
                       of the peak seen. THE PREFERRED STOP. It ends the ramp
                       on the far side of the power peak without ever going
                       near stall or the load's cut-out, so the rotor is never
                       driven to let go and the run is much shorter. Set to
                       None to ramp until the rotor or the ceiling stops it.
        censor_shape:  if the power peak sits above this fraction of the
                       threshold, the ramp stopped short and the result is
                       reported as a lower bound. Torque peaks well past
                       power, so a healthy ramp lands near 0.67.
        settle:        seconds to hold the operating point (defaults to 2*dwell)
        on_step:       callback(Step) for live display.

    Returns PeakResult.
    """
    if floor_amps <= 0:
        raise PeakFinderError(
            "floor_amps must be greater than zero. Commanding 0 A in constant "
            "current is an open circuit as far as the rotor is concerned, and "
            "an unloaded rotor in moving air accelerates until something "
            "mechanical stops it.")
    if max_amps <= floor_amps:
        raise PeakFinderError(f"max_amps {max_amps} must exceed floor_amps "
                              f"{floor_amps}")

    r = PeakResult()
    settle = settle if settle is not None else dwell * 2

    def dwell_at(amps, seconds):
        load.set_mode_cc(amps, range_=range_)
        time.sleep(seconds)
        v, i, w = load.measure()
        held = None
        try:
            held = load.read_setpoint("curr")
        except Exception:
            pass
        tol = max(tol_abs, tol_frac * amps)
        # Stamped after the measurement, not before the dwell: this is the
        # instant the numbers describe, and it is what a DAQ record has to be
        # joined against.
        s = Step(t_unix=time.time(), demand_a=amps, volts=v, amps=i, watts=w,
                 held_a=held, tracking=abs(i - amps) <= tol)
        r.trace.append(s)
        if on_step:
            on_step(s)
        return s

    # ── settle at the floor before asking anything of the rotor ──────────
    dwell_at(floor_amps, dwell)

    demand = floor_amps
    bad = 0
    rolloff = 0

    k = 0
    while True:
        if step_frac <= 0:
            # Fixed ladder on exact multiples of min_step: 0.01, 0.02, 0.03...
            # Without the snap, starting from a 5 mA floor gives 0.015, 0.025,
            # which is a different experiment from the one that was asked for.
            k += 1
            demand = min(k * min_step, max_amps)
            if demand <= floor_amps:
                continue
        else:
            step = max(min_step, step_frac * max(r.peak_amps, floor_amps))
            demand = min(demand + step, max_amps)

        s = dwell_at(demand, dwell)

        # ── is this a collapse? ──────────────────────────────────────────
        collapsed = (r.peak_amps > 0
                     and s.amps < collapse_frac * r.peak_amps)
        lost_tracking = not s.tracking
        under_volts = s.volts <= v_floor

        if collapsed or lost_tracking or under_volts:
            bad += 1
            s.note = ("collapsed" if collapsed else
                      "lost tracking" if lost_tracking else "under v_floor")
            if bad >= confirm:
                r.stalled = True
                # ── what does this measurement actually mean? ────────────
                # A rotor stall and a load drop-out END the same way: current
                # goes to zero, the rotor unloads, voltage rises to open
                # circuit. So the final dwell does NOT tell them apart — an
                # earlier version of this tried and was wrong.
                #
                # What separates them is how much VOLTAGE HEADROOM the last
                # sustained point still had. Deep into a rotor stall the
                # terminal voltage is far below where the load gives up. If
                # the last good point was already near CONF:VOLT:OFF, the ramp
                # ended at the instrument's limit and the rotor's own
                # threshold is higher and unseen — the result is censored, and
                # saying so is the whole point.
                prior = [t for t in r.trace[:-1] if t.tracking and t.amps > 0]
                v_before = prior[-1].volts if prior else s.volts
                r.limited_by = "rotor"
                r.volt_off = v_floor
                # ── is this threshold real, or did the ramp stop short? ──
                # The SHAPE says it, not the voltage. Torque peaks well past
                # power, so in an untruncated ramp the power peak lands near
                # 2/3 of the threshold. If it sits right up against it, the
                # ramp ended before the rotor did.
                #
                # An earlier version tested voltage headroom against
                # CONF:VOLT:OFF instead. It called a 96%-accurate run at
                # 1800 rpm censored, which is how a warning that matters at
                # 500 rpm gets ignored.
                shape = (r.power_peak_amps / r.peak_amps) if r.peak_amps else 0.0
                r.power_peak_ratio = shape

                # ── did the ROTOR let go, or did the LOAD give up? ───────
                # If measured current was still tracking demand when the ramp
                # stopped, the rotor was still supplying everything asked of
                # it — the terminal voltage simply fell under the load's
                # cut-out first. That is the instrument's limit, not the
                # turbine's, and the two must not share a column in a log.
                if under_volts and not lost_tracking and not collapsed:
                    r.limited_by = "load-cutout"
                r.censored = shape > censor_shape or r.limited_by == "load-cutout"
                r.unloaded = s.volts > v_before * 1.2 and s.amps <= 0.0
                r.stopped_by = (
                    f"rollover — {s.note} at {demand:.4f} A "
                    f"({s.amps:.4f} A measured, {s.volts:.3f} V, was "
                    f"{v_before:.3f} V)")
                break
            continue

        bad = 0

        # Only a dwell that TRACKED counts as sustained. A step the rotor
        # could not hold is not a data point about what it can hold.
        if s.amps > r.peak_amps:
            r.peak_amps, r.peak_volts = s.amps, s.volts
            r.peak_watts_at_peak = s.watts
        if s.watts > r.power_peak_watts:
            r.power_peak_watts = s.watts
            r.power_peak_amps, r.power_peak_volts = s.amps, s.volts

        # ── the clean stop: power has rolled off the peak ────────────────
        # Confirmed over `confirm` dwells, because one low reading on a noisy
        # rotor is not a trend. Nothing here approaches stall — that is the
        # point of stopping this way rather than at the threshold.
        if (stop_power_frac and r.power_peak_watts > 0
                and s.watts <= stop_power_frac * r.power_peak_watts):
            rolloff += 1
            if rolloff >= confirm:
                r.limited_by = "power-rolloff"
                r.stopped_by = (
                    f"power fell to {s.watts / r.power_peak_watts * 100:.0f}% "
                    f"of its peak ({s.watts:.4f} W vs "
                    f"{r.power_peak_watts:.4f} W) at {demand:.4f} A")
                r.rolled_off = True
                break
        else:
            rolloff = 0

        if max_watts and s.watts > max_watts:
            r.limited_by = "power"
            r.stopped_by = f"{s.watts:.1f} W exceeds the {max_watts:.1f} W limit"
            break
        if demand >= max_amps:
            r.limited_by = "ceiling"
            r.stopped_by = (
                f"reached the {max_amps:.4f} A ceiling without a rollover — "
                f"the rotor never let go, so this is a lower bound on the "
                f"threshold, not the threshold")
            break

    # ── recover to the floor, NEVER to zero ──────────────────────────────
    load.set_mode_cc(floor_amps, range_=range_)
    time.sleep(settle)

    # ── settle at the operating point, approached from below ─────────────
    r.refine()
    r.operating_amps = operate_frac * r.peak_amps
    if r.operating_amps > floor_amps:
        # Walk up rather than stepping straight there. The target is on the
        # stable side of the threshold, but a step load large enough to get
        # there in one go can overshoot through it on the way.
        n = max(2, int(math.ceil((r.operating_amps - floor_amps)
                                 / max(min_step, step_frac * r.peak_amps))))
        for k in range(1, n + 1):
            load.set_mode_cc(
                floor_amps + (r.operating_amps - floor_amps) * k / n,
                range_=range_)
            time.sleep(min(dwell, 1.0))
        r.operating = dwell_at(r.operating_amps, settle)
        r.operating.note = "operating point"

    return r.refine()
