"""
turbine.py — wind turbine power characterization: Cp against tip-speed ratio.

The experiment this whole rig exists to run. Two nested sweeps:

    for each wind speed V:
        for each load resistance R, high → low:
            settle, measure V_dc, I_dc, rotor RPM
            λ  = ωR_rotor / V
            Cp = P_elec / (½ ρ A V³)

Replaces doing it by hand with a resistor box, which is where the repeatability
problem came from.

═══════════════════════════════════════════════════════════════════════════
WHY CONSTANT RESISTANCE, NOT CONSTANT CURRENT
═══════════════════════════════════════════════════════════════════════════
Both modes are just "how much current to pull from the turbine". The
difference is what happens when the rotor slows.

A generator's braking torque tracks the current it is delivering. Consider the
rotor slowing slightly:

  · **CR** — current is V/R, and V falls with rotor speed, so current falls
    too. Braking torque eases off and the rotor recovers. Self-correcting
    everywhere on the curve, like a spring.

  · **CC** — the load pulls the same current at the lower voltage, so braking
    torque is unchanged while aero torque has moved.

Whether that is a problem depends on **which side of peak λ you are on**, and
this is more precise than "CC is unstable":

  · *Above* peak λ, slowing moves you toward the Cp peak, so aero torque
    **rises** and the rotor recovers. CC is perfectly stable here.
  · *Below* peak λ, slowing moves you away from the peak, aero torque
    **falls**, and with braking pinned there is nothing to arrest it. The
    rotor runs down to a stop.

A Cp sweep must traverse below peak λ — that is where the peak is found and
where the far side of the curve lives. So the mode has to be stable there, and
only CR is. Simulation in `tests/`: CR at 13 Ω settles at λ = 3.2 and holds
through a 15% disturbance; CC asking for comparable braking collapses to
λ = 0.2.

A physical resistor bank *is* CR. Using it here means the instrument imitates
what you were doing by hand, with a knob software can turn — and it means the
data is comparable to the resistive-loading convention most Cp–λ curves in the
literature were taken under.

**CP (constant power) is never used here.** Commanding fixed power from a
source whose available power you are measuring is the CC failure with the
accelerator held down: rotor slows → voltage drops → the load demands *more*
current to hold the wattage → brakes harder → slows more.

═══════════════════════════════════════════════════════════════════════════
WHAT Cp MEANS HERE, PRECISELY
═══════════════════════════════════════════════════════════════════════════
This computes P_electrical / (½ρAV³). That is **not** the aerodynamic power
coefficient. It is

    Cp_elec  =  Cp_aero × η_generator × η_rectifier

so it is lower than the rotor's true Cp by whatever the drivetrain loses, and
those losses vary with speed and current rather than being a constant offset.

Two consequences worth stating in any writeup:

  · **Do not compare Cp_elec to the Betz limit (0.593).** A rotor at Cp_aero
    0.40 behind a 70%-efficient drivetrain reads 0.28, and that is a
    measurement of the *system*, not a poor rotor.
  · The λ at which Cp_elec peaks is usually close to, but not identical to,
    the λ where Cp_aero peaks — generator efficiency shifts it.

Columns are named `cp_elec` throughout so nobody has to remember this.
"""

from __future__ import annotations

import csv
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from chroma_load import LoadError, TurbineInterlock

LOG_DIR = Path("logs")


# ═══════════════════════════════════════════════════════════════════════════
# GEOMETRY AND AIR
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class TurbineGeometry:
    """
    Rotor geometry. `radius_m` is tip radius from the axis of rotation — not
    blade length, unless the blades start at the centre, which they do not.
    Getting this wrong scales λ linearly and Cp inversely with its square,
    so it is worth measuring rather than taking from a drawing.
    """
    radius_m: float
    n_blades: int = 3
    hub_radius_m: float = 0.0
    name: str = ""

    @property
    def swept_area_m2(self):
        # Annulus if a hub radius is given. For most small rotors the hub is a
        # couple of percent of area and ignoring it is fine — but if you took
        # the trouble to measure it, use it.
        return math.pi * (self.radius_m ** 2 - self.hub_radius_m ** 2)

    def tip_speed_ratio(self, rpm, wind_mps):
        if wind_mps <= 0:
            return float("nan")
        omega = 2 * math.pi * rpm / 60.0
        return omega * self.radius_m / wind_mps

    def cp_elec(self, power_w, wind_mps, rho=1.225):
        if wind_mps <= 0:
            return float("nan")
        return power_w / (0.5 * rho * self.swept_area_m2 * wind_mps ** 3)


def air_density(temp_c, pressure_pa=101325.0):
    """ρ = p/(RT), dry air. A 10 °C swing moves it ~3.5%, and Cp with it."""
    return pressure_pa / (287.05 * (temp_c + 273.15))


# ═══════════════════════════════════════════════════════════════════════════
# STALL PROTECTION
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class StallGuard:
    """
    Decides when a resistance sweep has gone far enough.

    Three rules, cheapest first. Only the first is a safety rule; the other two
    stop you wasting run time past the useful part of the curve.

    1. **Did it settle?** If rotor speed is still falling when the settle
       window ends, that point never found equilibrium. Abort it and step the
       resistance back up. This catches stall while it is still developing,
       which is the only time catching it is useful.

    2. **RPM floor.** Below `min_rpm_fraction` of the no-load speed at this
       wind speed, stop. You are well past peak Cp.

    3. **Power rollover.** Once measured power has fallen `rollover_frac`
       below the best seen at this wind speed, the peak and its far side are
       captured. The rest is stall behaviour you neither need nor should
       provoke.
    """
    min_rpm_fraction: float = 0.40
    rollover_frac: float = 0.20
    min_volts: float = 1.0

    # Deceleration threshold as a FRACTION of current speed per second, not an
    # absolute rpm/s. An absolute figure is meaningless across operating
    # points: -5 rpm/s is a hard stall for a rotor at 200 rpm and ordinary
    # settling for one at 5000. Testing found this immediately — the guard
    # aborted the first point of every sweep because a rotor coasting down
    # from no-load naturally exceeds any fixed rpm/s limit for a while.
    settle_slope_frac_per_s: float = -0.02

    def check(self, rpm_history, times, rpm_noload, power_w, best_power_w,
              volts):
        """Returns (ok_to_continue, reason). reason is '' when fine."""
        if volts < self.min_volts:
            return False, (f"output collapsed to {volts:.2f} V — the rotor has "
                           f"stalled or stopped")

        if len(rpm_history) >= 4:
            # Least-squares slope over the settle window, normalised by speed.
            # A point still descending has not found an operating point, and
            # loading it further completes the stall rather than measuring it.
            slope = np.polyfit(times[-len(rpm_history):], rpm_history, 1)[0]
            rpm_now = max(abs(rpm_history[-1]), 1.0)
            frac = slope / rpm_now
            if frac < self.settle_slope_frac_per_s:
                return False, (f"rotor still decelerating at {slope:.0f} rpm/s "
                               f"({frac:+.1%} of speed per second) when the "
                               f"settle window ended — this point never "
                               f"reached equilibrium")

        rpm = rpm_history[-1] if rpm_history else 0.0
        if rpm_noload and rpm < self.min_rpm_fraction * rpm_noload:
            return False, (f"{rpm:.0f} rpm is below "
                           f"{self.min_rpm_fraction:.0%} of the {rpm_noload:.0f} "
                           f"rpm no-load speed — past the useful curve")

        if best_power_w > 0 and power_w < (1 - self.rollover_frac) * best_power_w:
            return False, (f"power has rolled over: {power_w:.1f} W against a "
                           f"peak of {best_power_w:.1f} W — the curve is "
                           f"captured")
        return True, ""


# ═══════════════════════════════════════════════════════════════════════════
# PLANNING THE RESISTANCE SWEEP
# ═══════════════════════════════════════════════════════════════════════════

def plan_resistances(v_open_circuit, i_max=5.0, n=10, r_min=None, r_max=None):
    """
    Choose the resistance ladder from the turbine's open-circuit voltage.

    Spaced logarithmically, not linearly. Current goes as 1/R, so equal steps
    in R crowd all the interesting behaviour into the bottom of the range and
    waste half the run at loads so light the rotor barely notices.

    `r_max` defaults to roughly ten times the resistance that would draw a
    tenth of `i_max` — a genuinely light load, so the sweep starts near the
    runaway end and walks *down* toward stall. That direction matters: you can
    always stop early, and stopping early on the way down leaves you on the
    safe side.
    """
    if r_max is None:
        r_max = v_open_circuit / max(i_max * 0.05, 1e-3)
    if r_min is None:
        r_min = v_open_circuit / i_max
    if r_min >= r_max:
        raise ValueError(f"r_min {r_min:.2f} must be below r_max {r_max:.2f}")
    return list(np.geomspace(r_max, r_min, n))


# ═══════════════════════════════════════════════════════════════════════════
# THE SWEEP
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SweepPoint:
    wind_mps: float
    hz: float
    resistance_ohm: float
    volts: float
    amps: float
    power_w: float
    rpm: float
    tsr: float
    cp_elec: float
    rho: float
    rpm_std: float = 0.0
    settled: bool = True
    note: str = ""


class CpSweep:
    """
    Two-dimensional characterization: wind speed × load resistance.

    Args:
        drive:          connected ACS550 (via whichever transport)
        load:           ChromaLoad
        read_rpm:       callable returning turbine rotor RPM
        geometry:       TurbineGeometry
        calibration:    Hz → wind speed
        read_velocity:  optional live anemometer. When present it is used in
                        preference to the calibration, because Cp goes as V³
                        and a 5% velocity error is a 15% Cp error — by far the
                        largest term in the uncertainty budget.
    """

    def __init__(self, drive, load, read_rpm, geometry, calibration,
                 read_velocity=None, guard=None, rho=1.225,
                 settle_s=25.0, dwell_s=10.0, sample_hz=4.0):
        self.drive, self.load = drive, load
        self.read_rpm = read_rpm
        self.geom = geometry
        self.cal = calibration
        self.read_velocity = read_velocity
        self.guard = guard or StallGuard()
        self.rho = rho
        self.settle_s, self.dwell_s = settle_s, dwell_s
        self.sample_hz = sample_hz
        self.points: list[SweepPoint] = []

    # ── one operating point ──────────────────────────────────────────────

    def _hold_point(self, wind_mps, hz, ohms, rpm_noload, best_power):
        """Set the resistance, watch it settle, then measure."""
        self.load.set_mode_cr(ohms)

        rpm_hist, t_hist = [], []
        t0 = time.monotonic()
        dt = 1.0 / self.sample_hz

        while time.monotonic() - t0 < self.settle_s:
            time.sleep(dt)
            rpm_hist.append(float(self.read_rpm()))
            t_hist.append(time.monotonic() - t0)

        v, i, p = self.load.measure()

        # Judge settling on the last third of the window: the first part is the
        # transient you deliberately allowed for.
        tail = max(4, len(rpm_hist) // 3)
        ok, why = self.guard.check(rpm_hist[-tail:], t_hist, rpm_noload,
                                   p, best_power, v)

        if not ok:
            return SweepPoint(wind_mps, hz, ohms, v, i, p,
                              rpm_hist[-1] if rpm_hist else 0.0,
                              float("nan"), float("nan"), self.rho,
                              settled=False, note=why)

        # Acquire over the dwell, averaging in the measured domain.
        vs, is_, rpms = [], [], []
        t1 = time.monotonic()
        while time.monotonic() - t1 < self.dwell_s:
            time.sleep(dt)
            vv, ii, _ = self.load.measure()
            vs.append(vv)
            is_.append(ii)
            rpms.append(float(self.read_rpm()))

        v, i = float(np.mean(vs)), float(np.mean(is_))
        rpm = float(np.mean(rpms))
        p = v * i
        return SweepPoint(
            wind_mps=wind_mps, hz=hz, resistance_ohm=ohms,
            volts=v, amps=i, power_w=p, rpm=rpm,
            tsr=self.geom.tip_speed_ratio(rpm, wind_mps),
            cp_elec=self.geom.cp_elec(p, wind_mps, self.rho),
            rho=self.rho, rpm_std=float(np.std(rpms)), settled=True)

    def _wind_speed_now(self, hz):
        """Measured velocity if we have it, otherwise the calibration."""
        if self.read_velocity is not None:
            v = self.read_velocity()
            if v is not None and v > 0:
                return float(v), "measured"
        return float(self.cal.velocity(hz)), "derived"

    # ── one wind speed ───────────────────────────────────────────────────

    def sweep_one_speed(self, hz, resistances, rpm_noload=None, verbose=True):
        """
        Walk the resistance ladder at one tunnel setting, high R to low.

        Stops early when the guard says so. Stopping early is the expected
        outcome on a good run, not a failure — the ladder is planned to extend
        past the useful range so that the guard, not the plan, decides where
        the curve ends.
        """
        wind, src = self._wind_speed_now(hz)
        if verbose:
            print(f"\n  {hz:.1f} Hz → {wind:.2f} m/s ({src})")

        results, best_power = [], 0.0
        for ohms in resistances:
            pt = self._hold_point(wind, hz, ohms, rpm_noload, best_power)
            results.append(pt)
            self.points.append(pt)

            if not pt.settled:
                if verbose:
                    print(f"    {ohms:7.2f} Ω  STOP — {pt.note}")
                # Back off to the last good load before returning. Leaving the
                # turbine on the resistance that just stalled it is exactly
                # the wrong place to sit while the next thing happens.
                good = [p for p in results if p.settled]
                self.load.set_mode_cr(good[-1].resistance_ohm if good
                                      else resistances[0])
                time.sleep(3)
                break

            best_power = max(best_power, pt.power_w)
            if verbose:
                print(f"    {ohms:7.2f} Ω  {pt.volts:6.2f} V  {pt.amps:5.2f} A  "
                      f"{pt.power_w:6.1f} W  {pt.rpm:6.0f} rpm  "
                      f"λ={pt.tsr:5.2f}  Cp_elec={pt.cp_elec:.3f}")
        return results

    def measure_noload_rpm(self, hz, seconds=8.0, verbose=True):
        """
        Free-running rotor speed, for the guard's RPM floor.

        **Deliberately brief and deliberately at the lightest load the
        instrument can hold — never with the load off.** Open circuit is the
        condition the whole interlock exists to prevent; this measures close
        to it without ever going there.
        """
        self.load.set_mode_cr(9999)          # very light, still connected
        time.sleep(seconds * 0.6)
        samples = []
        t0 = time.monotonic()
        while time.monotonic() - t0 < seconds * 0.4:
            samples.append(float(self.read_rpm()))
            time.sleep(0.25)
        rpm = float(np.mean(samples)) if samples else 0.0
        if verbose:
            print(f"    near-no-load {rpm:.0f} rpm "
                  f"(floor will be {self.guard.min_rpm_fraction * rpm:.0f})")
        return rpm

    # ── the full 2-D run ─────────────────────────────────────────────────

    def run(self, hz_points, v_open_circuit, i_max=5.0, n_loads=10,
            log_path=None, metadata=None, verbose=True):
        """
        The whole characterization, wrapped in the interlock.

        Sequencing is not negotiable and is enforced by TurbineInterlock:
        load on → wind up → sweep → wind down → load off, and the load stays
        on if the fan cannot be confirmed stopped.
        """
        resistances = plan_resistances(v_open_circuit, i_max=i_max, n=n_loads)
        if verbose:
            print(f"  resistance ladder: "
                  f"{', '.join(f'{r:.1f}' for r in resistances)} Ω")
            print(f"  rotor: R={self.geom.radius_m:.3f} m, "
                  f"A={self.geom.swept_area_m2:.4f} m², ρ={self.rho:.3f}")

        self.drive.start_keepalive()      # before any long settle
        with TurbineInterlock(self.drive, self.load) as rig:
            rig.arm()
            self.load.set_mode_cr(resistances[0])

            for hz in hz_points:
                if not rig.load.is_on:
                    raise LoadError("load dropped out — aborting the sweep")
                rig.wind_up(hz) if not self.drive.status()["RDY_REF"] \
                    else rig.set_hz(hz)
                time.sleep(self.settle_s)

                rpm_noload = self.measure_noload_rpm(hz, verbose=verbose)
                self.sweep_one_speed(hz, resistances, rpm_noload, verbose)

        if log_path:
            self.write(log_path, metadata)
        return self.points

    # ── output ───────────────────────────────────────────────────────────

    def write(self, path=None, metadata=None):
        path = Path(path or LOG_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_cp.csv")
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = ["wind_mps", "hz", "resistance_ohm", "volts", "amps", "power_w",
                "rpm", "rpm_std", "tsr", "cp_elec", "rho", "settled", "note"]
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for p in self.points:
                w.writerow([getattr(p, c) for c in cols])

        meta = dict(metadata or {})
        meta.update({
            "mode": "cp_sweep",
            "geometry": {"radius_m": self.geom.radius_m,
                         "swept_area_m2": self.geom.swept_area_m2,
                         "n_blades": self.geom.n_blades,
                         "name": self.geom.name},
            "rho": self.rho, "settle_s": self.settle_s, "dwell_s": self.dwell_s,
            "load_mode": "CR",
            "cp_definition": ("P_electrical / (0.5*rho*A*V^3) — this is "
                              "Cp_aero x eta_generator x eta_rectifier, NOT "
                              "the aerodynamic Cp. Do not compare to Betz."),
            "written": datetime.now().isoformat(timespec="seconds")})
        path.with_suffix(".json").write_text(json.dumps(meta, indent=2,
                                                        default=str))
        return path

    # ── analysis ─────────────────────────────────────────────────────────

    def summary(self):
        """Peak Cp_elec and the λ it occurs at, per wind speed."""
        out = []
        for hz in sorted({p.hz for p in self.points}):
            pts = [p for p in self.points if p.hz == hz and p.settled
                   and p.cp_elec == p.cp_elec]
            if not pts:
                continue
            best = max(pts, key=lambda p: p.cp_elec)
            out.append({"hz": hz, "wind_mps": best.wind_mps,
                        "n_points": len(pts),
                        "cp_elec_max": best.cp_elec,
                        "tsr_at_peak": best.tsr,
                        "power_w_at_peak": best.power_w,
                        "resistance_at_peak": best.resistance_ohm})
        return out

    def print_summary(self):
        rows = self.summary()
        if not rows:
            print("  no settled points")
            return
        print(f"\n  {'Hz':>5}{'m/s':>7}{'n':>4}{'Cp_elec':>9}{'λ':>7}"
              f"{'W':>8}{'Ω':>8}")
        print("  " + "─" * 48)
        for r in rows:
            print(f"  {r['hz']:>5.1f}{r['wind_mps']:>7.2f}{r['n_points']:>4}"
                  f"{r['cp_elec_max']:>9.3f}{r['tsr_at_peak']:>7.2f}"
                  f"{r['power_w_at_peak']:>8.1f}{r['resistance_at_peak']:>8.1f}")

        tsrs = [r["tsr_at_peak"] for r in rows]
        if len(tsrs) > 1:
            spread = (max(tsrs) - min(tsrs)) / np.mean(tsrs)
            print(f"\n  peak λ across wind speeds: {np.mean(tsrs):.2f} "
                  f"± {np.std(tsrs):.2f}")
            if spread < 0.15:
                print("  Consistent, as it should be — peak λ is a property of "
                      "the rotor,\n  not of wind speed. That consistency is "
                      "your best evidence the\n  measurement is sound.")
            else:
                print("  Wider spread than expected. Peak λ should barely move "
                      "with wind\n  speed; if it does, suspect the velocity "
                      "calibration, the rotor\n  radius, or Reynolds effects "
                      "at the low end.")
