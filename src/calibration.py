"""
calibration.py — map drive frequency ↔ fan RPM ↔ test-section velocity.

This is what lets you specify experiments in m/s instead of Hz. Nobody outside
this repository wants to talk about drive frequency; Sodhi, Jeong, Tim's CFD,
and any paper all speak velocity.

────────────────────────────────────────────────────────────────────────────
THE TWO-STAGE MAP
────────────────────────────────────────────────────────────────────────────

    drive Hz  ──[motor slip]──►  fan RPM  ──[fan + tunnel]──►  velocity

Stage 1 is nearly linear. An induction motor's synchronous speed is
120·f/poles, and actual speed is that minus slip. Under a fan load slip grows
mildly with speed, but across a normal operating band a straight line through
the nameplate point is good to about 1%.

Stage 2 should be *very* linear. Fan affinity laws give volumetric flow
Q ∝ N, and velocity is Q over a fixed area, so v ∝ N with only a small
intercept from losses that do not scale. If your fit comes out badly nonlinear,
something is wrong with the data, not with the physics — see check() below.

────────────────────────────────────────────────────────────────────────────
WHY THE NONLINEARITY MATTERS FOR GUSTS
────────────────────────────────────────────────────────────────────────────
If v = a·Hz + b with b ≠ 0, then a *sinusoidal velocity* profile is NOT a
sinusoidal frequency command — the mapping stretches one half of the waveform
relative to the other. `Calibration.hz_profile()` maps point by point rather
than scaling the whole array, so the velocity you asked for is the velocity
commanded, and any waveform distortion lands in the Hz signal where it belongs.

Get this backwards and your "sinusoidal gust" has a second harmonic in it that
you did not put there and will not expect to find in the results.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


class Calibration:
    """
    Velocity ↔ frequency mapping, fitted from measured data.

    Construct via from_rpm_table(), from_hz_table(), or load().
    """

    domain = "hz"        # "hz" or "rpm" — which variable coeffs are in

    # What the DRIVE's speed reference is denominated in. Most ACS550
    # installations use frequency, but a drive configured for speed control
    # (par 1105 in rpm) commands rpm directly — and then an rpm-domain
    # calibration needs no conversion at all. The guard below compares the two
    # rather than assuming Hz, because assuming Hz is how a perfectly usable
    # calibration gets rejected.
    drive_unit = "hz"

    def __init__(self, coeffs, hz_range, source="", rpm_per_hz=None,
                 r2=None, residual_std=None, units="m/s", notes=""):
        self.coeffs = np.asarray(coeffs, dtype=float)  # highest order first
        self.hz_min, self.hz_max = hz_range
        self.source = source
        self.rpm_per_hz = rpm_per_hz
        self.r2 = r2
        self.residual_std = residual_std
        self.units = units
        self.notes = notes

    # ── construction ─────────────────────────────────────────────────────

    @classmethod
    def from_hz_table(cls, hz, velocity, order=1, units="m/s", source="",
                      notes=""):
        """
        Fit directly from (drive Hz, velocity) pairs — the ideal case, because
        it collapses both stages into one measured relationship and carries no
        assumption about slip.
        """
        hz = np.asarray(hz, dtype=float)
        v = np.asarray(velocity, dtype=float)
        if len(hz) < order + 2:
            raise ValueError(f"need at least {order + 2} points for order {order}")

        coeffs = np.polyfit(hz, v, order)
        pred = np.polyval(coeffs, hz)
        resid = v - pred
        r2 = 1 - np.var(resid) / np.var(v) if np.var(v) > 0 else 1.0

        return cls(coeffs, (float(hz.min()), float(hz.max())),
                   source=source or "hz table", r2=float(r2),
                   residual_std=float(np.std(resid)), units=units, notes=notes)

    @classmethod
    def from_rpm_velocity(cls, rpm, velocity, order=1, units="m/s",
                          source="", notes=""):
        """
        Fit velocity against fan RPM only, deferring the Hz link.

        Use this when you have a measured RPM → velocity table but do not yet
        know the motor nameplate or whether the fan is belt-driven. The fit is
        stored in RPM space and `attach_drive_map()` supplies the Hz ↔ RPM
        relation later, without refitting.

        Keeping the two stages separate matters: the RPM → velocity
        relationship is a property of the fan and duct and does not change,
        while the Hz → RPM relationship depends on the motor, the drive, and
        any pulley ratio — things that can be changed or misremembered.
        """
        rpm = np.asarray(rpm, dtype=float)
        v = np.asarray(velocity, dtype=float)
        coeffs = np.polyfit(rpm, v, order)
        pred = np.polyval(coeffs, rpm)
        resid = v - pred
        r2 = 1 - np.var(resid) / np.var(v) if np.var(v) > 0 else 1.0

        cal = cls(coeffs, (float(rpm.min()), float(rpm.max())),
                  source=source or "rpm→velocity table", r2=float(r2),
                  residual_std=float(np.std(resid)), units=units, notes=notes)
        cal.domain = "rpm"          # coeffs are in RPM, not Hz
        return cal

    def attach_drive_map(self, nameplate_rpm, nameplate_hz, pulley_ratio=1.0):
        """
        Supply the Hz → RPM relationship and convert an RPM-domain fit into a
        Hz-domain one.

        fan_rpm = hz · (nameplate_rpm / nameplate_hz) · pulley_ratio

        Use the LOADED nameplate speed (e.g. 1750 rpm at 60 Hz), not the 1800
        synchronous figure — the difference is slip, and using 1800 bakes a
        systematic 3% error into every velocity you command.

        `pulley_ratio` is fan RPM per motor RPM. 1.0 for direct drive; greater
        than 1 for a step-up belt. If the fan reaches speeds the motor cannot,
        there is a pulley in there and this is where it goes.
        """
        rpm_per_hz = float(nameplate_rpm) / float(nameplate_hz) * float(pulley_ratio)
        if getattr(self, "domain", "hz") == "rpm":
            # v(rpm) with rpm = k·hz  →  substitute to get v(hz)
            order = len(self.coeffs) - 1
            new = np.array([c * rpm_per_hz ** (order - i)
                            for i, c in enumerate(self.coeffs)])
            self.coeffs = new
            self.hz_min = self.hz_min / rpm_per_hz
            self.hz_max = self.hz_max / rpm_per_hz
            self.domain = "hz"
        self.rpm_per_hz = rpm_per_hz
        return self

    @classmethod
    def from_rpm_table(cls, rpm, velocity, nameplate_rpm, nameplate_hz,
                       order=1, units="m/s", source="", notes=""):
        """
        Fit from (fan RPM, velocity) pairs plus the motor nameplate, which is
        what you have if RPM was measured with a tach.

        The nameplate gives the slip-corrected slope:

            rpm_per_hz = nameplate_rpm / nameplate_hz

        e.g. a 4-pole motor tagged 1750 rpm at 60 Hz → 29.17 rpm/Hz. Note this
        is the *loaded* speed, not the 1800 rpm synchronous speed — using 1800
        here would put a systematic 3% error into every velocity you command.

        Assumes slip scales proportionally with frequency. Good to about 1%
        across a normal band; if you need better, measure a few (Hz, RPM)
        pairs directly and use from_hz_table() instead.
        """
        rpm = np.asarray(rpm, dtype=float)
        v = np.asarray(velocity, dtype=float)
        rpm_per_hz = float(nameplate_rpm) / float(nameplate_hz)
        hz = rpm / rpm_per_hz

        cal = cls.from_hz_table(hz, v, order=order, units=units,
                                source=source or "rpm table + nameplate",
                                notes=notes)
        cal.rpm_per_hz = rpm_per_hz
        return cal

    @classmethod
    def from_csv(cls, path, x_col="rpm", v_col="velocity",
                 nameplate_rpm=None, nameplate_hz=None, order=1,
                 units="m/s", delimiter=","):
        """
        Load a calibration table from CSV with a header row.

        Accepts either an `rpm` or `hz` column. With rpm you must supply the
        nameplate values so the slip correction can be applied.
        """
        import csv as _csv
        xs, vs = [], []
        with open(path, newline="") as f:
            for row in _csv.DictReader(f, delimiter=delimiter):
                keys = {k.strip().lower(): k for k in row}
                xk = keys.get(x_col.lower())
                vk = keys.get(v_col.lower())
                if xk is None or vk is None:
                    raise KeyError(f"CSV needs '{x_col}' and '{v_col}' columns; "
                                   f"found {list(row)}")
                xs.append(float(row[xk]))
                vs.append(float(row[vk]))

        if x_col.lower() == "rpm":
            if nameplate_rpm is None or nameplate_hz is None:
                raise ValueError("an RPM table needs nameplate_rpm and "
                                 "nameplate_hz for the slip correction")
            return cls.from_rpm_table(xs, vs, nameplate_rpm, nameplate_hz,
                                      order=order, units=units,
                                      source=str(path))
        return cls.from_hz_table(xs, vs, order=order, units=units,
                                 source=str(path))

    # ── the mapping ──────────────────────────────────────────────────────

    def velocity(self, hz):
        """Hz → velocity. Vectorized."""
        self._require_hz_domain()
        return np.polyval(self.coeffs, np.asarray(hz, dtype=float))

    def _require_hz_domain(self):
        domain = getattr(self, "domain", "hz")
        unit = getattr(self, "drive_unit", "hz")
        if domain == unit:
            return                      # already in the drive's own units
        if domain == "rpm":
            raise ValueError(
                "this calibration is in RPM space but the drive commands "
                f"{unit}. Either call attach_drive_map(nameplate_rpm, "
                "nameplate_hz, pulley_ratio), or set drive_unit='rpm' if the "
                "drive is configured for speed reference (check par 1105 — if "
                "it reads in rpm, it is).")
        raise ValueError(f"calibration is in {domain}, drive commands {unit}")

    def hz(self, velocity):
        """
        Velocity → Hz. Inverts the fit.

        Linear inverts analytically. Higher orders solve numerically and pick
        the root inside the calibrated range — which is why extrapolation
        raises rather than guessing.
        """
        self._require_hz_domain()
        v = np.atleast_1d(np.asarray(velocity, dtype=float))

        if len(self.coeffs) == 2:                    # linear: v = a·f + b
            a, b = self.coeffs
            out = (v - b) / a
        else:
            out = np.empty_like(v)
            for i, vi in enumerate(v):
                c = self.coeffs.copy()
                c[-1] -= vi
                roots = np.roots(c)
                real = roots[np.abs(roots.imag) < 1e-9].real
                inband = real[(real >= self.hz_min * 0.5) &
                              (real <= self.hz_max * 1.5)]
                if len(inband) == 0:
                    raise ValueError(f"no physical frequency gives {vi:.2f} "
                                     f"{self.units}")
                out[i] = inband[np.argmin(np.abs(inband - np.mean(
                    [self.hz_min, self.hz_max])))]

        return float(out[0]) if np.isscalar(velocity) or out.size == 1 else out

    def rpm(self, hz):
        """Hz → fan RPM, if the nameplate relationship is known."""
        if self.rpm_per_hz is None:
            raise ValueError("no rpm_per_hz — calibration was built from a "
                             "Hz table without nameplate data")
        return np.asarray(hz, dtype=float) * self.rpm_per_hz

    def hz_profile(self, u_velocity):
        """
        Convert a whole velocity profile to a frequency profile, point by point.

        Use this rather than scaling the array, and rather than converting only
        the mean and amplitude. With a nonzero intercept — or any curvature —
        those shortcuts distort the waveform, and you end up with harmonic
        content in your gust that you did not design and will not expect.
        """
        return np.asarray([self.hz(float(x)) for x in np.atleast_1d(u_velocity)])

    # ── validation ───────────────────────────────────────────────────────

    def check(self, verbose=True):
        """
        Sanity-check the fit against what the physics should look like.
        Returns a dict; prints findings by default.

        Fan affinity laws say velocity should be very nearly proportional to
        speed. Three things worth catching:

        · Poor R². Below about 0.998 for a linear fit on a well-behaved tunnel
          usually means insufficient settling between points, a partially
          blocked probe, or a transcription error — not real physics.

        · Large intercept. A few percent of full-scale velocity is normal
          (losses that do not scale with speed). Much more than that suggests
          the low-speed points were taken before the flow established, which
          drags the whole fit.

        · Negative velocity at the low end of the range. The fit is being
          extrapolated somewhere meaningless, so profiles near the bottom of
          the band will command nonsense.
        """
        out = {"r2": self.r2, "residual_std": self.residual_std,
               "hz_range": (self.hz_min, self.hz_max), "order": len(self.coeffs) - 1}

        v_lo = float(self.velocity(self.hz_min))
        v_hi = float(self.velocity(self.hz_max))
        out["velocity_range"] = (v_lo, v_hi)
        intercept = float(self.coeffs[-1])
        out["intercept"] = intercept
        out["intercept_frac"] = abs(intercept) / v_hi if v_hi else float("inf")

        if verbose:
            print(f"  calibration  {self.source}")
            print(f"    {self.hz_min:.1f}–{self.hz_max:.1f} Hz  →  "
                  f"{v_lo:.2f}–{v_hi:.2f} {self.units}")
            if len(self.coeffs) == 2:
                print(f"    v = {self.coeffs[0]:.4f}·Hz {intercept:+.4f}")
            else:
                print(f"    coeffs {np.round(self.coeffs, 6).tolist()}")
            if self.rpm_per_hz:
                print(f"    {self.rpm_per_hz:.2f} rpm/Hz  "
                      f"({self.hz_min * self.rpm_per_hz:.0f}–"
                      f"{self.hz_max * self.rpm_per_hz:.0f} rpm)")
            if self.r2 is not None:
                print(f"    R² = {self.r2:.5f}   residual σ = "
                      f"{self.residual_std:.3f} {self.units}")

            if self.r2 is not None and self.r2 < 0.998:
                print("    NOTE  poorer fit than a well-behaved tunnel gives. "
                      "Check settling time, probe blockage, transcription.")
            if out["intercept_frac"] > 0.10:
                print(f"    NOTE  intercept is {out['intercept_frac']:.0%} of "
                      f"full-scale velocity. Suspect the low-speed points.")
            if v_lo < 0:
                print("    WARNING  fit gives negative velocity at the bottom "
                      "of the range. Do not command profiles down there.")

        return out

    def in_range(self, hz):
        """Is this frequency inside the calibrated band?"""
        return self.hz_min <= float(hz) <= self.hz_max

    def warn_extrapolation(self, hz_array):
        """Warn once if a profile leaves the calibrated band."""
        arr = np.atleast_1d(hz_array)
        lo, hi = float(arr.min()), float(arr.max())
        if lo < self.hz_min or hi > self.hz_max:
            print(f"  WARNING  profile spans {lo:.1f}–{hi:.1f} Hz but the "
                  f"calibration only covers {self.hz_min:.1f}–{self.hz_max:.1f}. "
                  f"Velocities outside that band are extrapolated and should "
                  f"not be quoted as measured.")
            return True
        return False

    # ── persistence ──────────────────────────────────────────────────────

    def to_dict(self):
        return {"domain": getattr(self, "domain", "hz"),
                "drive_unit": getattr(self, "drive_unit", "hz"),
                "coeffs": self.coeffs.tolist(),
                "hz_range": [self.hz_min, self.hz_max],
                "rpm_per_hz": self.rpm_per_hz, "r2": self.r2,
                "residual_std": self.residual_std, "units": self.units,
                "source": self.source, "notes": self.notes}

    @classmethod
    def from_dict(cls, d):
        cal = cls(d["coeffs"], d["hz_range"], source=d.get("source", ""),
                  rpm_per_hz=d.get("rpm_per_hz"), r2=d.get("r2"),
                  residual_std=d.get("residual_std"),
                  units=d.get("units", "m/s"), notes=d.get("notes", ""))
        cal.domain = d.get("domain", "hz")
        cal.drive_unit = d.get("drive_unit", "hz")
        return cal

    def save(self, path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))
        return path

    @classmethod
    def load(cls, path):
        return cls.from_dict(json.loads(Path(path).read_text()))

    def __repr__(self):
        return (f"<Calibration {self.hz_min:.0f}–{self.hz_max:.0f} Hz → "
                f"{self.velocity(self.hz_min):.1f}–"
                f"{self.velocity(self.hz_max):.1f} {self.units}, "
                f"R²={self.r2:.4f}>" if self.r2 else "<Calibration>")


# ── unit helpers ──────────────────────────────────────────────────────────

TO_MPS = {"mps": 1.0, "m/s": 1.0, "mph": 0.44704,
          "fps": 0.3048, "ft/s": 0.3048, "kt": 0.514444}


def to_mps(value, unit):
    """Convert a velocity to m/s from any supported unit."""
    u = unit.strip().lower()
    if u not in TO_MPS:
        raise ValueError(f"unknown unit {unit!r}; known: {sorted(TO_MPS)}")
    return value * TO_MPS[u]


def from_mps(value_mps, unit):
    u = unit.strip().lower()
    if u not in TO_MPS:
        raise ValueError(f"unknown unit {unit!r}")
    return value_mps / TO_MPS[u]
