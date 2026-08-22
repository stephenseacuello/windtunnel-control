"""
velocity_loop.py — command measured velocity instead of predicted velocity.

Everything else in this package is open loop: it commands Hz and *predicts*
velocity from a static calibration. That prediction degrades for reasons that
have nothing to do with the drive:

  · **Air density.** ρ shifts ~10% between a cold morning and a hot afternoon
    in an unconditioned lab. Same RPM, different velocity, no warning.
  · **Blockage.** Every time a model or turbine goes in the test section the
    effective area changes, and so does the velocity at a given fan speed.
  · **Drift.** Belt wear, bearing condition, filter loading.

Closing the loop on the anemometer makes the calibration a starting guess
rather than a load-bearing assumption. Your sensor resolves 24–44 Hz, which is
two orders of magnitude more than this loop needs.

═══════════════════════════════════════════════════════════════════════════
WHY THE LOOP MUST BE SLOW
═══════════════════════════════════════════════════════════════════════════
The plant has a several-second time constant plus dead time. A controller
tuned faster than the plant does not make the tunnel faster — it makes it
oscillate, and on a 15 HP fan an oscillating controller is a genuinely
unpleasant thing to stand next to.

So this is deliberately a slow integral-dominant loop that corrects **the
operating point**, not the waveform. Use it to hold a steady velocity against
drift, or to set the mean that a gust rides on. Do not try to make it track a
gust — that is what feedforward is for, and the two compose cleanly:
feedforward shapes the fast part, this loop trims the slow part.

The default gains are conservative on purpose. If it seems sluggish, that is
the correct behaviour for this plant.
"""

from __future__ import annotations

import time

import numpy as np

from acs550 import DriveError


class VelocityController:
    """
    Slow PI loop from measured velocity to drive frequency.

    Args:
        drive:          connected ACS550 (or simulator)
        read_velocity:  callable returning the current measured velocity
        calibration:    used for the feedforward guess and for unit reporting
        kp, ki:         gains in Hz per (velocity unit) and per (unit·second).
                        Defaults are deliberately gentle.
        period:         seconds between corrections. Keep it comparable to the
                        plant time constant, not faster.
        max_correction: hard cap on how far the loop may pull away from the
                        calibration's open-loop guess. If the loop wants more
                        than this, the calibration is wrong or the anemometer
                        is lying, and quietly winding the fan up is the wrong
                        response to either.
    """

    def __init__(self, drive, read_velocity, calibration,
                 kp=0.15, ki=0.08, period=3.0, max_correction_hz=8.0,
                 hz_limit=None, deadband=0.05):
        self.drive = drive
        self.read_velocity = read_velocity
        self.cal = calibration
        self.kp, self.ki = kp, ki
        self.period = period
        self.max_correction = max_correction_hz
        self.hz_limit = hz_limit
        self.deadband = deadband

        self.integral = 0.0
        self.history = []

    def _feedforward_hz(self, target_velocity):
        """Open-loop guess from the calibration — where the loop starts."""
        return float(self.cal.hz(target_velocity))

    def hold(self, target_velocity, duration, verbose=True, settle_first=True):
        """
        Hold a measured velocity for `duration` seconds.

        Returns a summary dict including the steady-state correction, which is
        the interesting number: it tells you how far your calibration is off
        *today*, and can be folded back into the calibration if it persists.
        """
        ff_hz = self._feedforward_hz(target_velocity)
        if self.hz_limit and ff_hz > self.hz_limit:
            raise ValueError(
                f"{target_velocity:.1f} {self.cal.units} needs {ff_hz:.1f} Hz, "
                f"above the {self.hz_limit:.1f} Hz soft limit")

        if verbose:
            print(f"  target {target_velocity:.2f} {self.cal.units} → "
                  f"open-loop guess {ff_hz:.2f} Hz")

        self.drive.start_keepalive()      # before the settle below
        self.drive.start(ff_hz)

        if settle_first:
            if verbose:
                print(f"  settling {self.period * 4:.0f} s before closing the loop")
            time.sleep(self.period * 4)

        self.integral = 0.0
        t0 = time.monotonic()
        correction = 0.0

        while time.monotonic() - t0 < duration:
            time.sleep(self.period)
            try:
                v = float(self.read_velocity())
            except Exception as e:
                # A sensor failure must not leave the loop integrating blind.
                print(f"  velocity read failed ({e}) — holding last command")
                continue

            err = target_velocity - v
            if abs(err) < self.deadband:
                err = 0.0            # stop hunting inside sensor noise

            self.integral += err * self.period
            raw = self.kp * err + self.ki * self.integral

            # Clamp, and anti-windup: if we are pinned at the cap, stop
            # accumulating, or the integral runs away and the loop takes
            # minutes to recover once the error changes sign.
            correction = float(np.clip(raw, -self.max_correction,
                                       self.max_correction))
            if correction != raw:
                self.integral -= err * self.period

            cmd = ff_hz + correction
            if self.hz_limit:
                cmd = min(cmd, self.hz_limit)
            self.drive.set_hz(max(cmd, 0.0))

            self.history.append({"t": time.monotonic() - t0, "measured": v,
                                 "target": target_velocity, "error": err,
                                 "correction_hz": correction, "cmd_hz": cmd})
            if verbose:
                print(f"    {time.monotonic() - t0:6.1f}s  {v:6.2f} "
                      f"{self.cal.units}  err {err:+5.2f}  "
                      f"cmd {cmd:5.2f} Hz ({correction:+.2f})")

        return self._summary(target_velocity, ff_hz, correction)

    def _summary(self, target, ff_hz, correction):
        if not self.history:
            return {"samples": 0}
        tail = self.history[max(0, len(self.history) // 2):]
        meas = np.array([h["measured"] for h in tail])
        out = {"target": target, "open_loop_hz": ff_hz,
               "final_correction_hz": correction,
               "mean_measured": float(meas.mean()),
               "std_measured": float(meas.std()),
               "residual_error": float(target - meas.mean()),
               "samples": len(self.history)}

        # Has it actually settled? Two tests, because either alone lies:
        #   · residual error — is it *at* the target?
        #   · recent drift   — is it still moving?
        # A loop caught mid-approach has a large residual; one fighting a
        # disturbance has a small residual and persistent movement.
        #
        # Drift compares the last quarter against the one before it, not the
        # endpoint against the midpoint. A slow asymptote accumulates a lot of
        # total movement while barely moving *recently*, and measuring total
        # movement would call a settled loop unsettled forever.
        rel_err = abs(out["residual_error"]) / target if target else 0.0
        corr = np.array([h["correction_hz"] for h in self.history])
        if len(corr) >= 8:
            q = len(corr) // 4
            drift = abs(float(corr[-q:].mean() - corr[-2 * q:-q].mean()))
        else:
            drift = float("inf")
        out["relative_error"] = rel_err
        out["correction_drift_hz"] = float(drift)
        out["converged"] = bool(rel_err < 0.02 and drift < 0.15)

        implied = (ff_hz + correction) / ff_hz if ff_hz else 1.0
        out["implied_calibration_error"] = implied - 1.0

        print(f"\n  held {out['mean_measured']:.2f} ± {out['std_measured']:.2f} "
              f"{self.cal.units} (target {target:.2f})")
        print(f"  steady correction {correction:+.2f} Hz on a {ff_hz:.2f} Hz "
              f"open-loop guess")

        if not out["converged"]:
            # This is the important guard. An unconverged loop's correction is
            # a snapshot of an approach, not a measurement of the plant, and
            # quoting it as a calibration error would bake a wrong conclusion
            # into the data.
            print(f"  NOT CONVERGED — still {rel_err:.1%} from target, "
                  f"correction drifting {drift:.2f} Hz over the run.")
            print(f"  Do NOT read the correction as a calibration error yet. "
                  f"Run longer (try {max(120, int(self.period * 60))} s) or "
                  f"raise ki.")
            out["implied_calibration_error"] = None
            return out

        if abs(implied - 1) > 0.05:
            print(f"  → the calibration is off by {implied - 1:+.1%} under "
                  f"today's conditions. If that persists across sessions it is "
                  f"a calibration error worth folding in; if it moves day to "
                  f"day it is air density, and closed loop is the right answer.")
        else:
            print(f"  → the calibration is holding to within "
                  f"{abs(implied - 1):.1%} today.")
        return out

    def sweep(self, velocities, dwell=60.0, on_point=None):
        """
        Step through target velocities, holding each closed-loop.

        This is the version of `sweep` to use once you have a live velocity
        signal: each point is held at the velocity you asked for, rather than
        at the frequency the calibration guessed would produce it.
        """
        results = []
        for v in velocities:
            print(f"\n→ {v:.2f} {self.cal.units}")
            r = self.hold(v, dwell)
            if on_point:
                on_point(v, r)
            results.append(r)
        self.drive.stop()
        return results


def suggest_gains(tau, plant_gain_hz_per_unit=None, aggressiveness=0.3):
    """
    Conservative starting gains from the measured time constant.

    Internal-model-control PI tuning for a first-order plant G = K/(τs+1),
    with the closed-loop time constant λ deliberately several times the
    open-loop one — trading speed for the stability margin you want when the
    actuator is a 15 HP fan:

        kp = τ / (K·λ)
        Ti = τ          →   ki = kp / τ

    **The integral time is the plant time constant, not λ.** Setting Ti = λ
    instead — which is easy to do and looks plausible — makes ki smaller by
    τ/λ, here a factor of about three. The loop still converges, but so slowly
    that a two-minute hold ends while it is visibly still creeping, and the
    steady-state correction it reports is a snapshot of an approach rather
    than a measurement of the plant. That is worse than being slow: it invites
    someone to write down a calibration error that is simply an unconverged
    loop.

    `plant_gain_hz_per_unit` is dHz/dvelocity — the inverse of the calibration
    slope. Pass it and the gains come out in the right units.
    """
    g = plant_gain_hz_per_unit or 1.0
    tau_cl = tau / aggressiveness          # closed loop deliberately slower
    kp = g * tau / tau_cl
    ki = kp / tau                          # Ti = τ, per IMC-PI
    return {"kp": round(kp, 4), "ki": round(ki, 4),
            "period": round(max(tau / 2, 1.0), 2),
            "closed_loop_tau": round(tau_cl, 1)}
