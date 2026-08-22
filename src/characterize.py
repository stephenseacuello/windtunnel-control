"""
characterize.py — measure what the tunnel can actually do before you design
experiments around what you wish it could do.

Three routines:

    step_response()   → time constant τ and settling time
    freq_response()   → attenuation vs frequency, measured not assumed
    velocity_cal()    → Hz ↔ velocity calibration, if you have a probe

Run step_response() first. Everything else depends on knowing τ.

═══════════════════════════════════════════════════════════════════════════
WHY THIS MATTERS MORE THAN IT SOUNDS
═══════════════════════════════════════════════════════════════════════════
The chain from your command to the air in the test section is:

    setpoint → drive ramp → motor torque → fan inertia → air momentum

Every link is a lag. The composite behaves roughly first-order with a time
constant of seconds, which puts the corner frequency (1/2πτ) somewhere in the
tenths of a Hz. A gust with meaningful content above that corner comes out
attenuated and phase-shifted, and — this is the dangerous part — it still
comes out looking like a plausible gust. Nothing errors. You just publish a
figure captioned "2 Hz gust" that was really a 40%-amplitude smear.

Measure τ once. Then every profile you design can be checked against it with
gusts.check_realizable() before it costs you a test session.
"""

from __future__ import annotations

import time

import numpy as np

from acs550 import ACS550, DriveError
from player import ProfilePlayer


def step_response(drive: ACS550, base_hz=20.0, step_hz=10.0,
                  settle=30.0, record=30.0, dt=0.05, log_path=None):
    """
    Command a step and record how the tunnel actually follows it.

    Fits a first-order model  f(t) = f0 + Δ·(1 − e^(−t/τ))  and reports τ,
    the 10–90% rise time, and the implied corner frequency.

    Note this measures the *drive plus fan* response, not the velocity in the
    test section — the air lags the fan further still. If you have a probe,
    run this again logging velocity and expect a larger τ. Use the larger one.

    Returns a dict of results.
    """
    print(f"step response: {base_hz:g} → {base_hz + step_hz:g} "
          f"(drive reference units)")

    drive.start_keepalive()          # before the settle, not after
    drive.start(base_hz)
    print(f"  settling {settle:.0f} s at baseline")
    time.sleep(settle)

    n = int(record / dt)
    t = np.arange(n) * dt
    u = np.full(n, base_hz + step_hz)
    u[0] = base_hz                       # one baseline sample for reference

    player = ProfilePlayer(drive, log_path=log_path, read_every=1)
    player.play(t, u, dt=dt, return_to=base_hz)

    tm, _cmd, fm, _amps, _v = player.columns()
    good = ~np.isnan(fm)
    tm, fm = tm[good], fm[good]
    if len(fm) < 10:
        print("  too few valid speed readings to fit — check that the "
              "feedback field is mapped correctly")
        return {"error": "insufficient data"}

    f0, f_inf = fm[0], np.median(fm[-int(len(fm) * 0.1):])
    delta = f_inf - f0

    result = {"f_start": float(f0), "f_final": float(f_inf),
              "step_commanded": float(step_hz), "step_achieved": float(delta)}

    if abs(delta) < 0.1:
        print("  step too small to fit — increase step_hz")
        return result

    # τ from the 63.2% crossing. Cruder than a least-squares fit but robust
    # to the non-exponential early part where the drive ramp dominates.
    target = f0 + 0.632 * delta
    idx = np.argmax(fm >= target) if delta > 0 else np.argmax(fm <= target)
    tau = float(tm[idx]) if idx > 0 else float("nan")

    def crossing(frac):
        tgt = f0 + frac * delta
        i = np.argmax(fm >= tgt) if delta > 0 else np.argmax(fm <= tgt)
        return float(tm[i]) if i > 0 else float("nan")

    t10, t90 = crossing(0.10), crossing(0.90)

    result.update({
        "tau_s": tau,
        "rise_10_90_s": t90 - t10,
        "settling_95_s": crossing(0.95),
        "f_corner_hz": 1.0 / (2 * np.pi * tau) if tau == tau and tau > 0 else float("nan"),
    })

    print(f"  τ ≈ {tau:.2f} s")
    print(f"  10–90% rise {result['rise_10_90_s']:.2f} s")
    print(f"  corner frequency ≈ {result['f_corner_hz']:.3f} Hz")
    print(f"  → gusts slower than about {1 / (3 * tau):.2f} Hz will reproduce "
          f"faithfully; faster ones will be attenuated")

    try:
        accel, decel = drive.get_ramp_times()
        print(f"  drive ramps are currently {accel:.1f} s accel / "
              f"{decel:.1f} s decel")
    except Exception:
        # Not readable over the PMC line protocol. The tau result stands on
        # its own; this is only the "is the ramp your bottleneck" hint.
        print("  drive ramp times not readable over this transport — "
              "read par 2202/2203 on the keypad to see whether the ramp, "
              "rather than the fan, is your limiting factor")
        accel = None
    if accel is not None and accel > 3 * tau:
        print("  NOTE  the drive ramp, not the fan, is your limiting factor. "
              "Shortening par 2202 will buy real bandwidth. See "
              "docs/03_gusts.md before you do.")

    return result


def freq_response(drive: ACS550, base_hz=25.0, amplitude_hz=5.0,
                  frequencies=(0.02, 0.05, 0.1, 0.2, 0.5, 1.0),
                  cycles=6, dt=0.05, settle=20.0, log_dir=None):
    """
    Measure amplitude attenuation at each frequency by playing a sinusoid and
    fitting the measured response at the drive frequency.

    Slower and more thorough than a chirp, but the per-frequency numbers are
    easier to defend in a paper and easier to debug when one point looks odd.

    Returns a list of dicts with gain and phase per frequency.
    """
    results = []
    drive.start(base_hz)
    drive.start_keepalive()
    print(f"  settling {settle:.0f} s")
    time.sleep(settle)

    for f_hz in frequencies:
        duration = cycles / f_hz
        n = int(duration / dt)
        t = np.arange(n) * dt
        u = base_hz + amplitude_hz * np.sin(2 * np.pi * f_hz * t)

        print(f"  {f_hz:.3f} Hz — {duration:.0f} s")
        log = f"{log_dir}/freq_{f_hz:.3f}Hz.csv" if log_dir else None
        player = ProfilePlayer(drive, log_path=log, read_every=1)
        player.play(t, u, dt=dt, return_to=base_hz)

        tm, _cmd, fm, _amps, _v = player.columns()
        good = ~np.isnan(fm)
        tm, fm = tm[good], fm[good]

        # Single-frequency fit by projection onto sin and cos at f_hz. More
        # robust than peak-picking when the signal is noisy or attenuated.
        skip = len(tm) // cycles          # drop the first cycle (transient)
        tm, fm = tm[skip:], fm[skip:] - np.mean(fm[skip:])
        s = np.sin(2 * np.pi * f_hz * tm)
        c = np.cos(2 * np.pi * f_hz * tm)
        a = 2 * np.mean(fm * s)
        b = 2 * np.mean(fm * c)

        measured_amp = float(np.hypot(a, b))
        gain = measured_amp / amplitude_hz
        phase_deg = float(np.degrees(np.arctan2(b, a)))

        results.append({"f_hz": f_hz, "gain": gain,
                        "gain_db": 20 * np.log10(gain) if gain > 0 else -np.inf,
                        "phase_deg": phase_deg,
                        "measured_amp_hz": measured_amp})
        print(f"      gain {gain:.3f} ({20 * np.log10(gain):+.1f} dB), "
              f"phase {phase_deg:+.0f}°")

    # −3 dB is the conventional bandwidth edge: half the power, ~71% amplitude.
    below = [r for r in results if r["gain"] >= 0.707]
    if below:
        print(f"\n  −3 dB bandwidth ≈ {max(r['f_hz'] for r in below):.3f} Hz")
        print("  design gusts with their energy below this and they will "
              "come out the shape you drew")
    return results


def velocity_cal(drive: ACS550, read_velocity, hz_points=(10, 15, 20, 25, 30,
                                                          35, 40, 45, 50),
                 settle=25.0, samples=20):
    """
    Build the Hz ↔ velocity calibration, given a callable that returns the
    current test-section velocity (your pitot, hot wire, or a DAQ channel).

    Fits a straight line and returns both the coefficients and a callable
    suitable for gusts.velocity_to_hz().

    Do not force the fit through the origin. Real tunnels have an offset from
    fan and duct losses at low speed, and pinning the intercept at zero throws
    that error into every point.
    """
    drive.start(hz_points[0])
    drive.start_keepalive()

    hz_meas, v_meas = [], []
    for hz in hz_points:
        drive.set_hz(hz)
        print(f"  {hz:.0f} Hz — settling {settle:.0f} s")
        time.sleep(settle)
        vs = []
        for _ in range(samples):
            vs.append(read_velocity())
            time.sleep(0.25)
        f_actual = drive.actuals()[0]
        hz_meas.append(f_actual)
        v_meas.append(float(np.mean(vs)))
        print(f"      {f_actual:.2f} Hz → {v_meas[-1]:.3f} m/s "
              f"(σ {np.std(vs):.3f})")

    slope, intercept = np.polyfit(hz_meas, v_meas, 1)
    resid = np.array(v_meas) - (slope * np.array(hz_meas) + intercept)
    r2 = 1 - np.var(resid) / np.var(v_meas)

    print(f"\n  v = {slope:.4f}·Hz + {intercept:+.4f}   R² = {r2:.5f}")
    if r2 < 0.995:
        print("  NOTE  the fit is poorer than a well-behaved tunnel usually "
              "gives. Check for a blocked probe, insufficient settling, or "
              "genuine nonlinearity at the low end.")

    def hz_for_velocity(v):
        return (v - intercept) / slope

    return {"slope": float(slope), "intercept": float(intercept),
            "r2": float(r2), "hz_points": hz_meas, "v_points": v_meas,
            "hz_for_velocity": hz_for_velocity}
