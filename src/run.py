#!/usr/bin/env python3
"""
run.py — command line entry point for the wind tunnel.

    python run.py --port /dev/ttyVFD monitor
    python run.py --port /dev/ttyVFD characterize --base 20 --step 10
    python run.py --port /dev/ttyVFD gust 1mc --mean 25 --amp 8 --length 6
    python run.py --port /dev/ttyVFD turbulence --mean 25 --sigma 2 --duration 120
    python run.py --port /dev/ttyVFD sweep 15 45 5

Start with `monitor`. It writes nothing to the drive and is safe to run
before parameters 1001/1103 are switched to COMM.

Every mode that can move the fan prints the plan and pauses for confirmation
unless you pass --yes. That pause is there because a 15 HP fan starting
unexpectedly is a hazard to whoever is standing near the test section, and a
typo in an amplitude is easy to make.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

import gusts
from acs550 import ACS550, DriveError, SW_BITS
from calibration import Calibration, TO_MPS, to_mps
from characterize import freq_response, step_response
from config import TunnelConfig
import feedforward as ff
import selftest as _selftest
from simulator import SimulatedACS550
from player import ProfileAborted, ProfilePlayer, play_profile

LOG_DIR = Path("logs")


def timestamped(name):
    """Log path stamped with the wall-clock start, so runs sort chronologically."""
    return LOG_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{name}.csv"


def resolve_units(a, cfg):
    """
    Turn --units into a (to_hz, describe) pair.

    In Hz mode everything passes through untouched. In a velocity mode the
    profile is generated in velocity units and mapped to Hz point by point —
    never by scaling mean and amplitude separately, because a nonzero
    intercept or any curvature would put harmonic content into the gust that
    nobody designed and nobody would expect to find in the results.
    """
    if a.units in ("hz", "Hz"):
        return None, "Hz"

    cal = cfg.calibration
    if cal is None:
        raise SystemExit(
            f"--units {a.units} needs a velocity calibration. "
            f"Run `calibrate` first, or use --units hz.")

    factor = TO_MPS.get(a.units.lower())
    if factor is None:
        raise SystemExit(f"unknown unit {a.units}")

    def to_hz(profile_in_user_units):
        # user units → the calibration's own units → Hz, pointwise
        mps = np.asarray(profile_in_user_units) * factor
        native = mps / TO_MPS.get(cal.units.lower(), 1.0)
        return cal.hz_profile(native)

    return to_hz, a.units


def confirm(plan, auto_yes):
    """
    Print the plan and require a keystroke before anything moves.

    The pause exists because a 15 HP fan starting unexpectedly is a hazard to
    whoever is near the test section, and a typo in an amplitude is easy to
    make. --yes skips it for scripted runs; use it deliberately.
    """
    print("\n" + "─" * 60)
    for line in plan:
        print(f"  {line}")
    print("─" * 60)
    if auto_yes:
        return True
    print("  Test section clear? Anyone nearby warned?")
    return input("  Proceed? [y/N] ").strip().lower() == "y"


# ── modes ─────────────────────────────────────────────────────────────────

def _make_source(a, drive):
    """Build the velocity source the CLI was asked for."""
    from velocity_source import ManualSource, SimulatedSource, build_source
    spec = dict(a.cfg.get("velocity_source") or {})
    kind = a.velocity or spec.pop("kind", None)
    if kind in (None, "manual"):
        return None
    if kind == "simulated":
        return SimulatedSource(drive, a.cfg.calibration).start()
    return build_source(kind, **spec).start()


def mode_hold(drive, a):
    """
    Closed-loop hold on measured wind speed.

    Open loop commands Hz and predicts velocity. This commands velocity and
    lets the loop find the Hz, which is the difference between assuming the
    calibration is right today and checking.
    """
    from velocity_loop import VelocityController, suggest_gains
    src = _make_source(a, drive)
    if src is None:
        raise SystemExit("closed loop needs a live source — pass "
                         "--velocity nidaq|serial|simulated, or configure "
                         "velocity_source in tunnel.json")
    cal = a.cfg.calibration
    if cal is None:
        raise SystemExit("closed loop needs a velocity calibration")
    if not src.healthy:
        raise SystemExit(f"{src.name} source is not producing readings")

    g = suggest_gains(a.tau or 3.0, 1.0 / cal.coeffs[0])
    print(f"  gains {g}")
    if not confirm([f"CLOSED-LOOP HOLD at {a.target} {cal.units}",
                    f"for {a.seconds:.0f} s, source: {src.name}"], a.yes):
        return
    try:
        c = VelocityController(drive, src.read, cal, kp=g["kp"], ki=g["ki"],
                               period=g["period"], hz_limit=a.cfg.hz_limit)
        res = c.hold(a.target, a.seconds)
        if not res["converged"]:
            print("\n  The correction above is NOT a calibration measurement "
                  "— the loop\n  had not settled. Run longer before drawing "
                  "conclusions from it.")
    finally:
        src.stop()


def mode_status(drive, a):
    """What the tunnel knows about itself, and what is still missing."""
    print(a.cfg.summary())
    print()
    print(f"  drive REF1 MAX (par 1105): {drive.ref1_max_hz:.1f} Hz")
    try:
        accel, decel = drive.get_ramp_times()
        print(f"  drive ramps: {accel:.1f} s accel / {decel:.1f} s decel")
        print(f"  comm counters: {drive.comm_counters()}")
    except DriveError:
        print("  ramps and comm counters are not readable over this "
              "transport — use the keypad")


def mode_calibrate(drive, a):
    """
    Build a velocity calibration from an existing table of measurements.

    Reads a CSV with either an `rpm` or `hz` column plus a `velocity` column.
    An RPM table also needs the motor nameplate so slip can be corrected —
    use the LOADED nameplate speed (e.g. 1750 rpm at 60 Hz), not the 1800 rpm
    synchronous speed, or you bake a systematic 3% error into every velocity
    you ever command.
    """
    col = "rpm" if a.rpm else "hz"
    cal = Calibration.from_csv(a.file, x_col=col, v_col=a.velocity_col,
                               nameplate_rpm=a.nameplate_rpm,
                               nameplate_hz=a.nameplate_hz,
                               order=a.order, units=a.velocity_units)
    print()
    cal.check()
    a.cfg.set_calibration(cal, note=f"from {a.file}").save()
    print(f"\n  saved to {a.cfg.path}")
    print(f"  you can now use --units {a.velocity_units} on gust and "
          f"turbulence modes")


def mode_verify(drive, a):
    """
    Confirm or auto-correct the Hz→RPM assumption from ONE measurement.

    The velocity-vs-RPM relationship is measured and solid. The only assumed
    link is Hz→RPM, which depends on the motor nameplate and any pulley ratio.
    A single velocity reading at a single frequency pins it down exactly:

        correction = measured_velocity_ratio  →  new rpm_per_hz

    Run the tunnel at the stated frequency, read the anemometer once the flow
    has settled, and type the number in. That is the whole calibration.
    """
    cal = a.cfg.calibration
    if cal is None:
        raise SystemExit("no calibration loaded — check --config path")

    predicted = float(cal.velocity(a.hz))
    print(f"\n  running {a.hz:.1f} Hz  (predicted {predicted:.2f} {cal.units}, "
          f"{a.hz * cal.rpm_per_hz:.0f} rpm assumed)")

    if not confirm([f"VERIFY at {a.hz:.1f} Hz",
                    f"holds for {a.settle + a.hold:.0f} s while you read the "
                    f"anemometer"], a.yes):
        return

    drive.start_keepalive()
    drive.start(a.hz)
    print(f"  settling {a.settle:.0f} s")
    time.sleep(a.settle)
    f_meas, i_meas = drive.actuals()
    print(f"  drive reports {f_meas:.2f} Hz, {i_meas:.1f} A")
    print(f"  READ THE ANEMOMETER NOW — holding {a.hold:.0f} s")
    time.sleep(a.hold)
    drive.stop()

    if a.measured is None:
        print(f"\n  re-run with --measured <value in {cal.units}> to apply "
              f"the correction")
        return

    ratio = a.measured / predicted
    print(f"\n  predicted {predicted:.2f}, measured {a.measured:.2f} "
          f"→ ratio {ratio:.4f}")

    if abs(ratio - 1) < 0.05:
        print("  within 5% — the direct-drive assumption holds. Nothing to change.")
        a.cfg.set("calibration_status", "VERIFIED at one point").save()
        return

    # Velocity is affine in RPM, so scaling rpm_per_hz is not exactly a scale
    # on velocity. Solve for the rpm_per_hz that makes the prediction land on
    # the measurement at this frequency.
    #   v = A*(k*hz) + B   →   k = (v_meas - B) / (A * hz)
    A_rpm = cal.coeffs[0] / cal.rpm_per_hz     # slope back in RPM space
    B = cal.coeffs[1]
    k_new = (a.measured - B) / (A_rpm * a.hz)
    implied_pulley = k_new / (1750.0 / 60.0)

    print(f"  → rpm_per_hz {cal.rpm_per_hz:.2f} should be {k_new:.2f}")
    print(f"  → implies a pulley ratio of {implied_pulley:.3f} "
          f"(1.0 = direct drive)")
    if implied_pulley > 1.15:
        print("     a step-up belt would explain this, and would also explain "
              "the 2400 rpm figure in the Feb 13 data")
    elif implied_pulley < 0.85:
        print("     a step-down belt, or the motor is not 4-pole")

    from calibration import Calibration
    fresh = Calibration.from_dict(a.cfg.data["calibration"])
    fresh.domain = "rpm"
    fresh.coeffs = np.array([A_rpm, B])
    fresh.hz_min *= cal.rpm_per_hz
    fresh.hz_max *= cal.rpm_per_hz
    fresh.attach_drive_map(k_new, 1.0)
    a.cfg.set_calibration(fresh, note=f"verified at {a.hz} Hz = {a.measured}")
    a.cfg.set("calibration_status", "VERIFIED and corrected").save()
    print(f"\n  updated: v = {fresh.coeffs[0]:.4f}*Hz {fresh.coeffs[1]:+.3f}")


def mode_table(drive, a):
    """
    Print the speed → velocity reference. Reads nothing, moves nothing.

    Was Hz-domain and produced nonsense on this drive: it labelled the first
    column Hz, multiplied it by the vestigial rpm_per_hz for the RPM column,
    and then fed the HZ value to an rpm-domain calibration — so "5 Hz" came
    out as 148 rpm and −0.3 m/s. Three different unit errors in one row.
    """
    cal = a.cfg.calibration
    if cal is None:
        raise SystemExit("no calibration loaded")
    unit = (a.cfg.get("drive_reference") or {}).get("unit", "Hz")
    rpm_native = str(unit).lower() == "rpm" or getattr(cal, "domain", "") == "rpm"
    lim = a.cfg.hz_limit or cal.hz_max

    if rpm_native:
        print(f"\n  v = {cal.coeffs[0]:.5f}*RPM {cal.coeffs[1]:+.3f}   "
              f"[{a.cfg.get('calibration_status','')}]")
        print(f"\n  {'RPM':>6} {'m/s':>7} {'mph':>7}")
        step = 100.0 if lim > 500 else 25.0
        x = step
        while x <= lim + 0.01:
            v = float(cal.velocity(x))
            print(f"  {x:6.0f} {v:7.1f} {v / 0.44704:7.1f}")
            x += step
    else:
        print(f"\n  v = {cal.coeffs[0]:.4f}*Hz {cal.coeffs[1]:+.3f}   "
              f"[{a.cfg.get('calibration_status','')}]")
        print(f"\n  {'Hz':>4} {'RPM':>6} {'m/s':>7} {'mph':>7}")
        hz = 5.0
        while hz <= lim + 0.01:
            v = float(cal.velocity(hz))
            print(f"  {hz:4.0f} {hz * cal.rpm_per_hz:6.0f} {v:7.1f} "
                  f"{v / 0.44704:7.1f}")
            hz += 5.0


def mode_selftest(drive, a):
    """Read-only. Verifies the assumptions this code makes against the drive."""
    _selftest.run(drive, interactive=not a.yes)


def mode_ambient(drive, a):
    """Record the session's air conditions. Read-only on the drive."""
    if a.temperature is not None:
        a.cfg.set("temperature_c", a.temperature)
        a.cfg.set("pressure_pa", a.pressure, note="session ambient").save()
    amb = a.cfg.ambient()
    if amb is None:
        print("  no ambient recorded. Set it with:")
        print("    run.py --port X ambient --temperature 21.5 --pressure 101100")
        print("  Dynamic pressure scales with density, so two identical RPM")
        print("  sweeps on different days give different forces. Record it")
        print("  every session — it cannot be reconstructed afterwards.")
        return
    for k, v in amb.items():
        print(f"  {k:24s} {v}")
    dev = abs(amb["density_ratio"] - 1)
    if dev > 0.02:
        print(f"\n  air is {amb['density_ratio']:.3f}x ISA density — forces "
              f"and dynamic pressure scale by the same factor. Normalize "
              f"before comparing against runs taken on other days.")


def mode_monitor(drive, a):
    """Read-only. Nothing is written to the drive."""
    unit = (a.cfg.get("drive_reference") or {}).get("unit", "Hz")
    print(f"REF1 MAX (par 1105) = {drive.ref1_max_hz:g} {unit}")
    # Parameter reads are register-shaped and the PMC line protocol is
    # command-shaped, so these are best-effort rather than required. Monitor
    # is the first thing anyone runs; it must not die because a nice-to-have
    # readback is unavailable.
    try:
        accel, decel = drive.get_ramp_times()
        print(f"ramps: {accel:.1f} s accel / {decel:.1f} s decel")
    except DriveError:
        print("ramps: not readable over this transport (read 2202/2203 on "
              "the keypad)")
    try:
        print(f"comm counters: {drive.comm_counters()}")
    except DriveError:
        print("comm counters: not readable over this transport — read "
              "5306/5307/5308 on the keypad")
    t0 = time.monotonic()
    while a.seconds == 0 or time.monotonic() - t0 < a.seconds:
        st = drive.status()
        f, i = drive.actuals()
        active = " ".join(n for _, n in SW_BITS if st[n])
        print(f"{time.monotonic() - t0:7.1f}s  SW=0x{st['_raw']:04X}  "
              f"{f:8.1f} {unit}  {i:5.1f} A   {active}")
        time.sleep(1.0)


def mode_characterize(drive, a):
    """
    Step response -> tau, saved to the config.

    MOVES THE FAN. A positive step gives the rising constant, a negative one
    the falling constant -- and the falling one is what actually limits a
    symmetric gust, because the tunnel decelerates more slowly than it
    accelerates.
    """
    unit = (a.cfg.get("drive_reference") or {}).get("unit", "Hz")
    if not confirm([f"STEP RESPONSE TEST",
                    f"baseline {a.base:g} {unit}, step to "
                    f"{a.base + a.step:g} {unit}",
                    f"settle {a.settle} s, record {a.record} s"], a.yes):
        return
    LOG_DIR.mkdir(exist_ok=True)
    res = step_response(drive, base_hz=a.base, step_hz=a.step,
                        settle=a.settle, record=a.record, dt=a.dt,
                        log_path=timestamped("step"))
    for k, v in res.items():
        print(f"  {k:20s} {v}")

    tau = res.get("tau_s")
    if tau and tau == tau:
        # Direction matters. A negative step measures the FALLING constant,
        # which is limited by how fast the DC bus can absorb a decelerating
        # fan — usually the slower of the two, and the one that constrains a
        # symmetric gust. Saving both to the same key silently overwrites the
        # rising measurement with the falling one.
        key = "tau_down" if a.step < 0 else "tau"
        unit = (a.cfg.get("drive_reference") or {}).get("unit", "Hz")
        a.cfg.set(key, round(float(tau), 3),
                  note=f"step {a.base:g}→{a.base + a.step:g} {unit}").save()
        other = "tau" if key == "tau_down" else "tau_down"
        have = a.cfg.get(other)
        print(f"\n  saved as `{key}` = {tau:.2f} s in {a.cfg.path}")
        if have:
            up = a.cfg.get("tau")
            dn = a.cfg.get("tau_down")
            print(f"  rising {up:.2f} s · falling {dn:.2f} s "
                  f"(ratio {dn / up:.2f})")
            if dn > 1.3 * up:
                print(f"  The falling side is the binding constraint for a "
                      f"symmetric gust.\n  If par 2203 is longer than 2202, "
                      f"that is why — shorten it and re-measure,\n  watching "
                      f"for overvoltage faults.")
        else:
            sign = "--step -300" if key == "tau" else "--step 300"
            print(f"  `{other}` is not set yet — run characterize with "
                  f"{sign} to measure it.")


def mode_freqresp(drive, a):
    """
    Attenuation measured across the band rather than inferred from tau.

    MOVES THE FAN, for a long time -- several minutes per frequency at the
    slow end. Gives you the -3 dB bandwidth to quote.
    """
    freqs = [float(f) for f in a.frequencies.split(",")]
    if not confirm([f"FREQUENCY RESPONSE SWEEP",
                    f"baseline {a.base} Hz ± {a.amp} Hz",
                    f"frequencies {freqs} Hz, {a.cycles} cycles each",
                    f"roughly {sum(a.cycles / f for f in freqs) / 60:.0f} min"],
                   a.yes):
        return
    LOG_DIR.mkdir(exist_ok=True)
    freq_response(drive, base_hz=a.base, amplitude_hz=a.amp,
                  frequencies=freqs, cycles=a.cycles, log_dir=str(LOG_DIR))


def mode_gust(drive, a):
    """Discrete gust: 1-cosine, step, ramp or sine."""
    to_hz, unit_label = resolve_units(a, a.cfg)

    if a.shape == "1mc":
        t, u = gusts.one_minus_cosine(a.mean, a.amp, a.length,
                                      dt=a.dt, lead=a.lead, trail=a.trail)
    elif a.shape == "step":
        t, u = gusts.sharp_edged(a.mean, a.amp, a.length,
                                 dt=a.dt, lead=a.lead, trail=a.trail)
    elif a.shape == "ramp":
        t, u = gusts.ramp(a.mean, a.mean + a.amp, a.length,
                          dt=a.dt, lead=a.lead, trail=a.trail)
    else:
        t, u = gusts.sinusoid(a.mean, a.amp, a.freq, a.length,
                              dt=a.dt, lead=a.lead)

    u_user = u.copy()
    if to_hz is not None:
        u = to_hz(u)
        a.cfg.calibration.warn_extrapolation(u)

    try:
        accel, _decel = drive.get_ramp_times()
        max_slew = drive.ref1_max_hz / accel if accel > 0 else None
    except DriveError:
        # Without the ramp time the slew check cannot run. Say so rather than
        # letting a profile through unchecked and silently clipped.
        max_slew = None
        print("  NOTE  ramp time unreadable over this transport — the slew "
              "check is OFF.\n        Read par 2202 on the keypad and pass "
              "--max-slew to restore it.")
    print(f"\nprofile check ({a.shape}):")
    diag = gusts.check_realizable(t, u, tau=a.tau, max_slew_hz_s=max_slew,
                                  tau_down=a.tau_down, dead_time=a.dead_time)

    u_desired = u.copy()
    if a.feedforward:
        if not a.tau:
            raise SystemExit("--feedforward needs τ — run `characterize` first")
        print()
        comp = ff.compensate(t, u, tau=a.tau, tau_down=a.tau_down,
                             dead_time=a.dead_time, slew_limit=max_slew,
                             hz_limit=a.cfg.hz_limit)
        if comp["rms_improvement"] < 1.0 and not a.yes:
            if input("\n  compensation degrades tracking. Continue anyway? "
                     "[y/N] ").strip().lower() != "y":
                return
        u = comp["command"]
        diag["feedforward"] = {k: v for k, v in comp.items()
                               if k not in ("command", "predicted")}

    ref_unit = (a.cfg.get("drive_reference") or {}).get("unit", "Hz")
    shown = unit_label if unit_label.lower() != "hz" else ref_unit
    plan = [f"{a.shape.upper()} GUST",
            f"mean {a.mean:g} {shown}, amplitude {a.amp:g} {shown}, "
            f"length {a.length:g} s"]
    if to_hz is not None:
        plan.append(f"→ {u.min():.1f}–{u.max():.1f} {ref_unit} commanded")
    elif a.cfg.calibration:
        try:
            plan.append(f"= {float(a.cfg.calibration.velocity(u.min())):.1f}"
                        f"–{float(a.cfg.calibration.velocity(u.max())):.1f} m/s")
        except Exception:
            pass
    plan += [f"total run {t[-1]:.0f} s at {1 / a.dt:.0f} Hz update",
             f"repeats: {a.repeat}"]
    if not confirm(plan, a.yes):
        return

    LOG_DIR.mkdir(exist_ok=True)
    for rep in range(a.repeat):
        tag = f"{a.shape}_rep{rep + 1}" if a.repeat > 1 else a.shape
        print(f"\nrun {rep + 1}/{a.repeat}")
        meta = {"mode": "gust", "shape": a.shape, "units": unit_label,
                "mean": a.mean, "amplitude": a.amp, "length_s": a.length,
                "dt": a.dt, "repeat": f"{rep + 1}/{a.repeat}",
                "tau": a.tau, "diagnostics": diag,
                "calibration": a.cfg.calibration.to_dict()
                if a.cfg.calibration else None}
        try:
            play_profile(drive, t, u, baseline_hz=float(u[0]),
                         settle=a.settle, log_path=timestamped(tag),
                         hz_limit=a.cfg.hz_limit, metadata=meta,
                         velocity_source=getattr(a, "_vsrc", None))
        except ProfileAborted:
            print("  stopping the repeat sequence")
            break
        if rep < a.repeat - 1:
            print(f"  recovering {a.settle:.0f} s before next repeat")
            time.sleep(a.settle)


def mode_turbulence(drive, a):
    """
    Continuous turbulence, von Karman or Dryden. MOVES THE FAN.

    Band-limits to the tunnel corner by default when tau is known: raw
    spectrally-shaped noise runs to Nyquist, and commanding content the tunnel
    cannot follow produces a record honestly described as "turbulence,
    attenuated in ways we did not characterize".
    """
    to_hz, unit_label = resolve_units(a, a.cfg)
    gen = gusts.von_karman if a.model == "vonkarman" else gusts.dryden

    # If tau is known, band-limit to the tunnel corner by default. Raw
    # spectrally-shaped noise runs to Nyquist, and the drive would spend the
    # whole run chasing setpoints it can never reach — producing a record
    # honestly described as "turbulence, attenuated in ways we did not
    # characterize." Filtering up front means commanded and measured agree.
    f_max = a.f_max
    if f_max is None and a.tau:
        f_max = 1.0 / (2 * np.pi * a.tau)
        print(f"  band-limiting to {f_max:.3f} Hz (corner from τ={a.tau:.1f} s)")
        print(f"  pass --f-max 0 to disable and command the raw spectrum")
    if f_max == 0:
        f_max = None

    t, u = gen(a.mean, a.sigma, a.length_scale, a.duration,
               dt=a.dt, lead=a.lead, seed=a.seed, f_max=f_max)

    if to_hz is not None:
        u = to_hz(u)
        a.cfg.calibration.warn_extrapolation(u)

    try:
        accel, _ = drive.get_ramp_times()
        max_slew = drive.ref1_max_hz / accel if accel > 0 else None
    except DriveError:
        max_slew = None
    print(f"\nprofile check ({a.model}, seed {a.seed}):")
    diag = gusts.check_realizable(t, u, tau=a.tau, max_slew_hz_s=max_slew)

    plan = [f"{a.model.upper()} TURBULENCE",
            f"mean {a.mean} {unit_label}, σ {a.sigma} {unit_label} "
            f"({a.sigma / a.mean:.1%} intensity)",
            f"length scale {a.length_scale} m, duration {a.duration} s",
            f"band limit {f_max:.3f} Hz" if f_max else "no band limit",
            f"seed {a.seed} — reproducible"]
    if to_hz is not None:
        plan.insert(2, f"→ {u.min():.1f}–{u.max():.1f} Hz commanded")
    if not confirm(plan, a.yes):
        return

    LOG_DIR.mkdir(exist_ok=True)
    meta = {"mode": "turbulence", "model": a.model, "units": unit_label,
            "mean": a.mean, "sigma": a.sigma,
            "length_scale_m": a.length_scale, "duration_s": a.duration,
            "seed": a.seed, "f_max": f_max, "dt": a.dt, "tau": a.tau,
            "diagnostics": diag,
            "calibration": a.cfg.calibration.to_dict()
            if a.cfg.calibration else None}
    play_profile(drive, t, u, baseline_hz=float(u[0]), settle=a.settle,
                 log_path=timestamped(f"{a.model}_seed{a.seed}"),
                 hz_limit=a.cfg.hz_limit, metadata=meta,
                 velocity_source=getattr(a, "_vsrc", None))


def mode_csv(drive, a):
    """Replay a preprogrammed plan from CSV. Units come from the column name."""
    t, u, desc = gusts.from_csv(a.file, dt=a.dt, calibration=a.cfg.calibration)
    cal = a.cfg.calibration

    print(f"\n  {a.file}: {desc} → {len(u)} samples at {1 / a.dt:.0f} Hz")
    if cal:
        cal.warn_extrapolation(u)
    try:
        accel, _ = drive.get_ramp_times()
        max_slew = drive.ref1_max_hz / accel if accel > 0 else None
    except DriveError:
        max_slew = None
    diag = gusts.check_realizable(t, u, tau=a.tau, max_slew_hz_s=max_slew)

    plan = [f"REPLAY {a.file}", desc,
            f"{t[-1]:.0f} s, {u.min():.1f}–{u.max():.1f} Hz"]
    if cal:
        plan.append(f"= {float(cal.velocity(u.min())):.1f}–"
                    f"{float(cal.velocity(u.max())):.1f} {cal.units}")
    plan.append(f"repeats: {a.repeat}")
    if not confirm(plan, a.yes):
        return

    LOG_DIR.mkdir(exist_ok=True)
    meta = {"mode": "csv", "file": a.file, "source": desc, "dt": a.dt,
            "tau": a.tau, "diagnostics": diag,
            "calibration": cal.to_dict() if cal else None}
    for rep in range(a.repeat):
        if a.repeat > 1:
            print(f"\nrun {rep + 1}/{a.repeat}")
        try:
            play_profile(drive, t, u, baseline_hz=float(u[0]), settle=a.settle,
                         log_path=timestamped(f"replay_rep{rep + 1}"),
                         hz_limit=a.cfg.hz_limit, metadata=meta)
        except ProfileAborted:
            break
        if rep < a.repeat - 1:
            time.sleep(a.settle)


def mode_live(drive, a):
    """
    Interactive console — change the setpoint by hand, any time.

    The keep-alive thread holds the drive's watchdog fed while you sit at the
    prompt, so the fan stays where you put it indefinitely without you having
    to keep typing.

    Note what "real time" means here. You can issue a new setpoint whenever you
    like and the drive accepts it within a few milliseconds — but the drive
    then ramps to it over par 2202/2203, and the tunnel's flow follows with its
    own several-second time constant. Instant command, slow tunnel.
    """
    cal = a.cfg.calibration
    unit = a.units.lower()
    use_v = unit not in ("hz",) and cal is not None

    def to_hz(x):
        if not use_v:
            return x
        from calibration import TO_MPS
        return cal.hz(x * TO_MPS[unit] / TO_MPS.get(cal.units.lower(), 1.0))

    def describe(hz):
        if cal is None:
            return f"{hz:.1f} Hz"
        return (f"{hz:.1f} Hz · {hz * cal.rpm_per_hz:.0f} rpm · "
                f"{float(cal.velocity(hz)):.1f} {cal.units}")

    print("\n" + "─" * 58)
    print("  LIVE CONTROL" + (f"  — entering values in {unit}" if use_v else
                              "  — entering values in Hz"))
    print("─" * 58)
    print("   <number>   set speed          +N / -N   nudge by N")
    print("   go         start              stop      ramp down")
    print("   ?          read actuals       table     reference")
    print("   quit       stop and exit")
    if a.cfg.hz_limit:
        print(f"\n   soft limit {a.cfg.hz_limit:.0f} Hz"
              + (f" ({float(cal.velocity(a.cfg.hz_limit)):.1f} {cal.units})"
                 if cal else ""))
    print()

    drive.start_keepalive()
    running = False
    target_hz = 0.0

    while True:
        try:
            raw = input("  tunnel> ").strip().lower()
        except EOFError:
            break
        if not raw:
            continue

        if raw in ("quit", "q", "exit"):
            break

        if raw in ("?", "status"):
            f, i = drive.actuals()
            st = drive.status()
            print(f"    measured {describe(f)} · {i:.1f} A"
                  f"{'  [FAULT]' if st['TRIPPED'] else ''}")
            continue

        if raw == "table":
            mode_table(drive, a)
            continue

        if raw in ("stop", "s"):
            drive.stop()
            running = False
            print("    ramping down")
            continue

        if raw in ("go", "start"):
            if target_hz <= 0:
                print("    set a speed first")
                continue
            drive.start(target_hz)
            running = True
            print(f"    running → {describe(target_hz)}")
            continue

        try:
            if raw[0] in "+-" and len(raw) > 1:
                delta = float(raw)
                new_hz = target_hz + (to_hz(delta) - to_hz(0) if use_v else delta)
            else:
                new_hz = to_hz(float(raw))
        except ValueError:
            print("    ? — type a number, go, stop, ?, table, or quit")
            continue

        if new_hz < 0:
            new_hz = 0.0
        if a.cfg.hz_limit and new_hz > a.cfg.hz_limit:
            print(f"    refused — {new_hz:.1f} Hz exceeds the "
                  f"{a.cfg.hz_limit:.0f} Hz soft limit")
            continue

        target_hz = new_hz
        if running:
            drive.set_hz(target_hz)
            print(f"    → {describe(target_hz)}")
        else:
            print(f"    armed at {describe(target_hz)} — type 'go' to run")

    print("\n  stopping")
    drive.stop()
    drive.wait_until_stopped()
    print("  stopped")


def mode_sweep(drive, a):
    """Stepped steady-state sweep — the classic point-by-point run."""
    setpoints = list(np.arange(a.start, a.stop + a.step / 2, a.step))
    if not confirm(["STEPPED SWEEP",
                    f"{setpoints[0]:.0f} → {setpoints[-1]:.0f} Hz "
                    f"in {a.step:.0f} Hz steps",
                    f"{len(setpoints)} points, {a.settle} s settle + "
                    f"{a.dwell} s acquire each",
                    f"about {len(setpoints) * (a.settle + a.dwell) / 60:.0f} min"],
                   a.yes):
        return

    drive.start(setpoints[0])
    drive.start_keepalive()
    for sp in setpoints:
        drive.set_hz(sp)
        print(f"→ {sp:.1f} Hz, settling {a.settle} s")
        time.sleep(a.settle)
        f, i = drive.actuals()
        print(f"   settled at {f:.2f} Hz, {i:.1f} A — ACQUIRE")

        # ══════════════ DAQ HOOK ══════════════
        # Trigger acquisition here. Log the commanded setpoint AND the
        # measured frequency — they differ under load and the measured one
        # is what belongs in the data.
        time.sleep(a.dwell)
        # ══════════════════════════════════════

    print("sweep complete")


def mode_jog(drive, a):
    """Hold one setpoint. MOVES THE FAN. The first real test after handover."""
    unit = (a.cfg.get("drive_reference") or {}).get("unit", "Hz")
    cal = a.cfg.calibration
    vel = ""
    try:
        vel = f"  ({float(cal.velocity(a.hz)):.1f} m/s)" if cal else ""
    except Exception:
        pass
    if not confirm([f"JOG at {a.hz:g} {unit}{vel} for {a.seconds:g} s"], a.yes):
        return
    drive.start_keepalive()
    drive.start(a.hz)
    t0 = time.monotonic()
    while time.monotonic() - t0 < a.seconds:
        f, i = drive.actuals()
        print(f"  {time.monotonic() - t0:5.1f}s  {f:8.1f} {unit}  {i:5.1f} A")
        time.sleep(1.0)
    drive.stop()
    drive.wait_until_stopped()
    print("stopped")


def mode_reset(drive, a):
    """
    Clear a drive fault.

    Prints parameter 0401 first, deliberately: find out why it faulted before
    clearing it. Repeatedly resetting a drive that is protecting itself is how
    a cheap fault becomes an expensive one.
    """
    print(f"last fault code (par 0401): {drive.last_fault()}")
    drive.reset_fault()
    print("reset sent;", drive.status())


# ── CLI ───────────────────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        description="Aerolab wind tunnel control via ABB ACS550",
        epilog="Start with `monitor` — it writes nothing to the drive.")
    p.add_argument("--port", default=None,
                   help="serial port. Defaults to transport.port in "
                        "tunnel.json, then to whichever /dev/cu.usbmodem* is "
                        "present — being forced to retype the port every time "
                        "is how the wrong one eventually gets typed.")
    p.add_argument("--baud", type=int, default=19200, help="match par 5303")
    p.add_argument("--parity", default="N", choices=["N", "E", "O"])
    p.add_argument("--unit", type=int, default=1, help="station ID, par 5302")
    p.add_argument("--yes", action="store_true",
                   help="skip the confirmation prompt (scripted runs)")
    p.add_argument("--tau", type=float, default=None,
                   help="tunnel time constant. Read from the config file if "
                        "not given — run `characterize` to measure it.")
    p.add_argument("--tau-down", type=float, default=None, dest="tau_down",
                   help="falling time constant. The tunnel decelerates more "
                        "slowly than it accelerates; supplying this makes the "
                        "feasibility check honest about the falling edge.")
    p.add_argument("--dead-time", type=float, default=0.0, dest="dead_time",
                   help="transport delay, seconds")
    p.add_argument("--velocity", default=None,
                   choices=["manual", "simulated", "nidaq", "serial"],
                   help="live wind speed source; overrides tunnel.json")
    p.add_argument("--dry-run", action="store_true",
                   help="run against a simulated drive — no hardware, real "
                        "timing. Rehearse a long profile before committing a "
                        "session to it.")
    p.add_argument("--config", default="tunnel.json",
                   help="persistent tunnel config (tau, calibration, limits)")

    sub = p.add_subparsers(dest="mode", required=True)

    m = sub.add_parser("status", help="what the tunnel knows about itself")
    m.set_defaults(func=mode_status)

    m = sub.add_parser("calibrate", help="build a velocity calibration from a CSV")
    m.add_argument("file", help="CSV with rpm-or-hz and velocity columns")
    m.add_argument("--rpm", action="store_true",
                   help="table is RPM-based (needs nameplate values)")
    m.add_argument("--nameplate-rpm", type=float, default=None,
                   dest="nameplate_rpm",
                   help="LOADED nameplate speed, e.g. 1750 — not 1800 sync")
    m.add_argument("--nameplate-hz", type=float, default=60.0,
                   dest="nameplate_hz")
    m.add_argument("--velocity-col", default="velocity", dest="velocity_col")
    m.add_argument("--velocity-units", default="m/s", dest="velocity_units")
    m.add_argument("--order", type=int, default=1,
                   help="1 = linear (correct for fan affinity laws). Only go "
                        "higher if the residuals genuinely demand it.")
    m.set_defaults(func=mode_calibrate)

    m = sub.add_parser("hold", help="closed-loop hold on measured wind speed")
    m.add_argument("target", type=float, help="velocity in the calibration's units")
    m.add_argument("--seconds", type=float, default=120)
    m.set_defaults(func=mode_hold)

    m = sub.add_parser("selftest",
                       help="verify every assumption against the drive (read-only)")
    m.set_defaults(func=mode_selftest)

    m = sub.add_parser("ambient", help="record/report session air conditions")
    m.add_argument("--temperature", type=float, default=None, help="deg C")
    m.add_argument("--pressure", type=float, default=101325.0, help="Pa")
    m.set_defaults(func=mode_ambient)

    m = sub.add_parser("table", help="Hz → RPM → wind speed reference")
    m.set_defaults(func=mode_table)

    m = sub.add_parser("verify", help="confirm/correct Hz→RPM from one reading")
    m.add_argument("--hz", type=float, default=30.0)
    m.add_argument("--measured", type=float, default=None,
                   help="anemometer reading; omit on the first pass")
    m.add_argument("--settle", type=float, default=30)
    m.add_argument("--hold", type=float, default=30)
    m.set_defaults(func=mode_verify)

    m = sub.add_parser("monitor", help="read-only status loop")
    m.add_argument("--seconds", type=float, default=0, help="0 = forever")
    m.set_defaults(func=mode_monitor)

    m = sub.add_parser("jog", help="hold one setpoint")
    m.add_argument("hz", type=float)
    m.add_argument("--seconds", type=float, default=30)
    m.set_defaults(func=mode_jog)

    m = sub.add_parser("characterize", help="step response, measures tau")
    m.add_argument("--base", type=float, default=20)
    m.add_argument("--step", type=float, default=10)
    m.add_argument("--settle", type=float, default=30)
    m.add_argument("--record", type=float, default=30)
    m.add_argument("--dt", type=float, default=0.1,
                   help="sample interval. 0.1 s resolves a 2 s time constant "
                        "with 20 points on the rise; go faster only if the "
                        "link is reliable at that rate.")
    m.set_defaults(func=mode_characterize)

    m = sub.add_parser("freqresp", help="frequency response sweep")
    m.add_argument("--base", type=float, default=25)
    m.add_argument("--amp", type=float, default=5)
    m.add_argument("--frequencies", default="0.02,0.05,0.1,0.2,0.5,1.0")
    m.add_argument("--cycles", type=int, default=6)
    m.set_defaults(func=mode_freqresp)

    m = sub.add_parser("gust", help="discrete gust")
    m.add_argument("shape", choices=["1mc", "step", "ramp", "sine"])
    m.add_argument("--mean", type=float, required=True, help="baseline Hz")
    m.add_argument("--amp", type=float, required=True, help="excursion Hz")
    m.add_argument("--length", type=float, required=True, help="gust length s")
    m.add_argument("--freq", type=float, default=0.1, help="for sine")
    m.add_argument("--dt", type=float, default=0.05)
    m.add_argument("--lead", type=float, default=5)
    m.add_argument("--trail", type=float, default=10)
    m.add_argument("--settle", type=float, default=25)
    m.add_argument("--repeat", type=int, default=1)
    m.add_argument("--units", default="hz",
                   help="hz (default), or a velocity unit: mps, mph, fps. "
                        "Velocity units need a calibration.")
    m.add_argument("--feedforward", action="store_true",
                   help="pre-compensate for the tunnel lag (needs --tau)")
    m.set_defaults(func=mode_gust)

    m = sub.add_parser("turbulence", help="continuous turbulence")
    m.add_argument("--model", default="vonkarman",
                   choices=["vonkarman", "dryden"])
    m.add_argument("--mean", type=float, required=True)
    m.add_argument("--sigma", type=float, required=True)
    m.add_argument("--length-scale", type=float, default=50.0, dest="length_scale")
    m.add_argument("--duration", type=float, default=120)
    m.add_argument("--dt", type=float, default=0.05)
    m.add_argument("--lead", type=float, default=5)
    m.add_argument("--settle", type=float, default=25)
    m.add_argument("--seed", type=int, default=1,
                   help="fix it — reproducibility is the point")
    m.add_argument("--units", default="hz",
                   help="hz (default), or mps / mph / fps with a calibration")
    m.add_argument("--f-max", type=float, default=None, dest="f_max",
                   help="band-limit cutoff Hz. Defaults to the tunnel corner "
                        "when --tau is given. Pass 0 to disable.")
    m.set_defaults(func=mode_turbulence)

    m = sub.add_parser("csv", help="replay a preprogrammed plan from CSV")
    m.add_argument("file")
    m.add_argument("--dt", type=float, default=0.05)
    m.add_argument("--settle", type=float, default=25)
    m.add_argument("--repeat", type=int, default=1)
    m.set_defaults(func=mode_csv)

    m = sub.add_parser("live", help="interactive console — set speed by hand")
    m.add_argument("--units", default="hz",
                   help="hz (default), or mps / mph / fps with a calibration")
    m.set_defaults(func=mode_live)

    m = sub.add_parser("sweep", help="stepped steady-state sweep")
    m.add_argument("start", type=float)
    m.add_argument("stop", type=float)
    m.add_argument("step", type=float)
    m.add_argument("--settle", type=float, default=25)
    m.add_argument("--dwell", type=float, default=15)
    m.set_defaults(func=mode_sweep)

    m = sub.add_parser("reset", help="clear a drive fault")
    m.set_defaults(func=mode_reset)

    return p


def main():
    a = build_parser().parse_args()

    # Config first, so tau and the calibration are available without being
    # retyped. A guard that is easy to forget is a guard that does nothing.
    a.cfg = TunnelConfig.load(a.config)

    if not a.port:
        import glob
        cand = (a.cfg.get("transport") or {}).get("port")
        found = sorted(glob.glob("/dev/cu.usbmodem*") or
                       glob.glob("/dev/ttyACM*") or glob.glob("/dev/ttyUSB*"))
        if cand and Path(cand).exists():
            a.port = cand
        elif len(found) == 1:
            a.port = found[0]
        elif found:
            raise SystemExit(
                "several serial ports are present — say which:\n  "
                + "\n  ".join(found))
        else:
            raise SystemExit("no serial port found; pass --port")
        print(f"  port: {a.port}")
    if a.tau is None:
        a.tau = a.cfg.tau
    if a.tau_down is None:
        a.tau_down = a.cfg.get("tau_down")
    if not a.dead_time:
        a.dead_time = a.cfg.get("dead_time", 0.0)
    if not hasattr(a, "units"):
        a.units = "hz"

    if a.dry_run:
        print("\n  DRY RUN — simulated drive, no hardware. Timing is real, so"
              "\n  a five-minute profile takes five minutes.\n")
        # ref1_max and max_freq both come from the config: the drive commands
        # rpm, and a simulator left at 60 ramps forty times too slowly.
        _ref = float((a.cfg.get("drive_reference") or {}).get("ref1_max")
                     or 2435.0)
        maker = lambda: SimulatedACS550(
            ref1_max_hz=_ref, max_freq=_ref, tau_up=a.tau or 3.0,
            tau_down=a.tau_down or (a.tau or 3.0) * 1.6,
            dead_time=a.dead_time or 0.15)
    else:
        # Honour the transport in tunnel.json. Without this, run.py always
        # spoke raw Modbus — which, with a PMC in the middle, means talking a
        # protocol the PMC does not understand down a port that answers.
        import transport as _tr
        tspec = a.cfg.get("transport") or {"kind": "direct"}
        kind = tspec.get("kind", "direct")
        if kind == "pmc":
            print(f"  transport: PMC line protocol on {a.port}")
            tp = _tr.PMCTransport(
                a.port,
                baudrate=int(tspec.get("baudrate", 115200)),
                host_watchdog_ms=int(tspec.get("host_watchdog_ms", 5000)),
                feedback_scale=float(tspec.get("feedback_scale", 295.0)))
            ref = a.cfg.get("drive_reference") or {}
            maker = lambda: ACS550(
                a.port, transport=tp,
                ref1_max_fallback=ref.get("ref1_max"),
                ref_unit=ref.get("unit", "Hz"))
        else:
            ser = a.cfg.get("drive_serial") or {}
            parity = a.parity if a.parity != "N" else ser.get("parity", "N")
            maker = lambda: ACS550(a.port, baudrate=a.baud, parity=parity,
                                   unit=a.unit)

    try:
        with maker() as drive:
            if drive.is_faulted() and a.mode != "reset":
                print(f"drive is faulted (par 0401 = {drive.last_fault()}). "
                      f"Find out why before resetting.", file=sys.stderr)
                sys.exit(1)
            # A source, if configured, so runs log measured velocity rather
            # than only what the drive reported.
            a._vsrc = None
            if a.mode in ("gust", "turbulence", "csv", "sweep"):
                try:
                    a._vsrc = _make_source(a, drive)
                    if a._vsrc:
                        print(f"  velocity source: {a._vsrc.name}")
                except Exception as e:
                    print(f"  velocity source unavailable ({e}) — logging "
                          f"drive frequency only")
            try:
                a.func(drive, a)
            finally:
                if a._vsrc:
                    a._vsrc.stop()
    except ProfileAborted as e:
        # An abort is a designed outcome, not a crash. The player has already
        # reported why and attempted a stop; a four-deep traceback on top of
        # that buries the one line that matters.
        print(f"\n  run aborted: {e}")
        print("  the fan is stopped or the drive's comm watchdog will stop it "
              "within par 3019 seconds")
        sys.exit(1)
    except KeyboardInterrupt:
        # __exit__ has already issued the stop by the time this prints.
        print("\ninterrupted — stop command sent on exit")
    except DriveError as e:
        print(f"drive error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
