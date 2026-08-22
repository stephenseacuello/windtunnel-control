"""
gusts.py — velocity profile generators for wind tunnel gust simulation.

Every generator returns (t, u) where t is seconds from profile start and u is
the commanded quantity in whatever units you are working in — m/s if you have
a velocity calibration, Hz if you are commanding the drive directly.

Nothing here talks to hardware. These are pure functions, so you can plot and
sanity-check a profile before it ever reaches a 15 HP fan. Do that.

────────────────────────────────────────────────────────────────────────────
READ docs/03_gusts.md FIRST
────────────────────────────────────────────────────────────────────────────
The tunnel is a low-pass filter with a corner frequency somewhere in the
tenths of a Hz. Asking for a 2 Hz gust produces a barely-visible ripple, not
a gust. Run characterize.py to measure your actual bandwidth before designing
profiles, then keep the content below that corner.
"""

from __future__ import annotations

import numpy as np


# ═══════════════════════════════════════════════════════════════════════════
# DISCRETE GUSTS
# ═══════════════════════════════════════════════════════════════════════════

def one_minus_cosine(u_mean, u_gust, gust_length, dt=0.05,
                     lead=5.0, trail=10.0):
    """
    The classic discrete gust shape from aviation certification
    (FAA/EASA CS-25, MIL-F-8785C):

        u(t) = u_mean + (u_gust/2) · [1 − cos(2πt / T)]     for 0 ≤ t ≤ T

    Smooth start and end, single peak at T/2, no discontinuity in value or
    slope at either end. That last property is why it is the standard shape —
    a step or a triangle asks the fan for infinite acceleration at the corners
    and you just get the drive's ramp limit instead of the shape you drew.

    Args:
        u_mean:      baseline the gust rides on
        u_gust:      peak excursion above baseline (can be negative for a lull)
        gust_length: T, seconds from start of gust to end
        lead:        seconds of steady baseline before the gust
        trail:       seconds of steady baseline after, to let the flow recover

    Returns (t, u).
    """
    t_gust = np.arange(0, gust_length, dt)
    gust = (u_gust / 2.0) * (1.0 - np.cos(2 * np.pi * t_gust / gust_length))

    t_lead = np.arange(0, lead, dt)
    t_trail = np.arange(0, trail, dt)

    u = np.concatenate([
        np.full_like(t_lead, u_mean),
        u_mean + gust,
        np.full_like(t_trail, u_mean),
    ])
    t = np.arange(len(u)) * dt
    return t, u


def sharp_edged(u_mean, u_gust, hold, dt=0.05, lead=5.0, trail=15.0):
    """
    Step gust — the theoretical worst case, and a useful system-ID input even
    though the tunnel cannot reproduce the edge.

    What you actually get is the tunnel's step response, which is exactly what
    characterize.py measures. Use this to find your time constant; use
    one_minus_cosine() for gusts you intend to draw conclusions from.
    """
    t_lead = np.arange(0, lead, dt)
    t_hold = np.arange(0, hold, dt)
    t_trail = np.arange(0, trail, dt)

    u = np.concatenate([
        np.full_like(t_lead, u_mean),
        np.full_like(t_hold, u_mean + u_gust),
        np.full_like(t_trail, u_mean),
    ])
    return np.arange(len(u)) * dt, u


def ramp(u_start, u_end, duration, dt=0.05, lead=5.0, trail=10.0):
    """Linear ramp between two levels. Constant dU/dt in the middle."""
    t_lead = np.arange(0, lead, dt)
    t_ramp = np.arange(0, duration, dt)
    t_trail = np.arange(0, trail, dt)

    u = np.concatenate([
        np.full_like(t_lead, u_start),
        u_start + (u_end - u_start) * (t_ramp / duration),
        np.full_like(t_trail, u_end),
    ])
    return np.arange(len(u)) * dt, u


# ═══════════════════════════════════════════════════════════════════════════
# PERIODIC AND SWEPT
# ═══════════════════════════════════════════════════════════════════════════

def sinusoid(u_mean, amplitude, frequency, duration, dt=0.05, lead=5.0):
    """
    Sinusoidal oscillation about a mean. Good for steady-state frequency
    response at one frequency, and for repeatable periodic loading.

    Keep `frequency` below the tunnel corner or the amplitude you get will be
    a fraction of the amplitude you asked for — see the attenuation warning
    in check_realizable().
    """
    t_lead = np.arange(0, lead, dt)
    t_osc = np.arange(0, duration, dt)

    u = np.concatenate([
        np.full_like(t_lead, u_mean),
        u_mean + amplitude * np.sin(2 * np.pi * frequency * t_osc),
    ])
    return np.arange(len(u)) * dt, u


def chirp(u_mean, amplitude, f_start, f_end, duration, dt=0.05, lead=5.0):
    """
    Linear frequency sweep. This is the efficient way to measure the tunnel's
    frequency response — one run gives you the whole transfer function instead
    of a sinusoid per point.

    Sweep slowly. If the sweep rate is comparable to the system's own time
    constant the response smears and the identification is garbage. For a
    tunnel with a several-second time constant, allow a couple of minutes.
    """
    t_lead = np.arange(0, lead, dt)
    t_c = np.arange(0, duration, dt)

    # Instantaneous phase is the integral of the linearly-varying frequency.
    k = (f_end - f_start) / duration
    phase = 2 * np.pi * (f_start * t_c + 0.5 * k * t_c ** 2)

    u = np.concatenate([
        np.full_like(t_lead, u_mean),
        u_mean + amplitude * np.sin(phase),
    ])
    return np.arange(len(u)) * dt, u


# ═══════════════════════════════════════════════════════════════════════════
# CONTINUOUS TURBULENCE
# ═══════════════════════════════════════════════════════════════════════════

def band_limit(u, dt, f_max):
    """
    Brick-wall low-pass a profile at f_max.

    Use this on turbulence before playing it. Raw spectrally-shaped noise has
    content all the way to Nyquist, most of which the tunnel cannot reproduce
    — so the drive spends the whole run chasing setpoints it can never reach,
    and the slew warning fires on content that contributes nothing.

    Filtering it out up front means the commanded profile is one the tunnel
    can actually track, so commanded and measured agree and the run is
    honestly described as "turbulence band-limited to f_max" rather than
    "turbulence, mostly attenuated, in ways we did not characterize."

    Rescales to preserve the original standard deviation.
    """
    n = len(u)
    mean = u.mean()
    freqs = np.fft.rfftfreq(n, dt)
    spec = np.fft.rfft(u - mean)
    spec[freqs > f_max] = 0
    out = np.fft.irfft(spec, n=n)
    if np.std(out) > 0:
        out = out * (np.std(u - mean) / np.std(out))
    return out + mean


def taper_ends(fluct, dt, taper_s=4.0):
    """
    Cosine-taper a fluctuation to zero at both ends.

    Without this, a turbulence realization begins at whatever random value the
    noise happens to take, so splicing it onto a steady lead section commands
    a step of order sigma in a single sample. On this tunnel that is both a
    slew violation and a pointless transient sitting at the front of every
    record, right where you least want one.

    Tapering costs you the first and last few seconds of turbulence and buys a
    clean onset. Keep taper_s well under the run duration.
    """
    n = len(fluct)
    w = np.ones(n)
    k = min(int(taper_s / dt), n // 2)
    if k > 1:
        ramp_ = 0.5 * (1 - np.cos(np.pi * np.arange(k) / k))
        w[:k] = ramp_
        w[-k:] = ramp_[::-1]
    return fluct * w


def von_karman(u_mean, sigma, length_scale, duration, dt=0.05,
               lead=5.0, seed=None, f_max=None, taper_s=4.0):
    """
    Continuous turbulence with a von Kármán longitudinal spectrum — the
    standard model for atmospheric turbulence, and the one you want if the
    question is "how does this structure behave in real wind" rather than
    "how does it respond to one discrete event."

    Implemented by shaping Gaussian white noise in the frequency domain to
    match the target PSD:

        Φ(Ω) = σ² · (2L/π) / [1 + (1.339 L Ω)²]^(5/6)

    where Ω = 2πf/U is the spatial frequency. Taylor's frozen turbulence
    hypothesis converts between spatial and temporal — valid when σ << u_mean,
    which holds for the intensities you can produce here.

    Args:
        sigma:        turbulence intensity, same units as u_mean (σ/u_mean is
                      typically 0.05–0.20 for atmospheric boundary layer)
        length_scale: integral length scale L in metres. ~100–300 m at
                      altitude; tens of metres near the ground. Scale it to
                      your model, not to full-scale, or the whole spectrum
                      sits below your tunnel's bandwidth.
        seed:         fix it. Reproducible turbulence is the entire point when
                      you are comparing configurations or matching CFD.

    Returns (t, u).
    """
    rng = np.random.default_rng(seed)
    n = int(round(duration / dt))

    # Frequency grid for the real FFT
    freqs = np.fft.rfftfreq(n, dt)
    omega = 2 * np.pi * freqs / u_mean        # spatial frequency, rad/m

    psd = (sigma ** 2) * (2 * length_scale / np.pi) / \
          (1 + (1.339 * length_scale * omega) ** 2) ** (5.0 / 6.0)
    psd[0] = 0.0                              # no DC — that is u_mean's job

    # White noise, shaped. sqrt(PSD) gives the amplitude envelope; random
    # phase makes it a realization rather than an impulse.
    white = rng.normal(size=len(freqs)) + 1j * rng.normal(size=len(freqs))
    shaped = white * np.sqrt(psd)
    fluct = np.fft.irfft(shaped, n=n)

    # Renormalize — the FFT scaling above is up to a constant, and what
    # actually matters experimentally is hitting the requested sigma.
    if np.std(fluct) > 0:
        fluct = fluct * (sigma / np.std(fluct))

    # Strip content the tunnel cannot follow, then restore sigma. Strongly
    # recommended — pass f_max = 1/(2πτ) from characterize.py.
    if f_max is not None:
        fluct = band_limit(fluct, dt, f_max)
    # Ease in and out so the splice onto the steady lead is smooth.
    fluct = taper_ends(fluct, dt, taper_s)

    t_lead = np.arange(0, lead, dt)
    u = np.concatenate([np.full_like(t_lead, u_mean), u_mean + fluct])
    return np.arange(len(u)) * dt, u


def dryden(u_mean, sigma, length_scale, duration, dt=0.05,
           lead=5.0, seed=None, f_max=None, taper_s=4.0):
    """
    Dryden turbulence — the rational-transfer-function cousin of von Kármán.
    Slightly wrong in the high-frequency tail, but it has an exact state-space
    form, which is why control people prefer it.

        Φ(Ω) = σ² · (2L/π) / [1 + (LΩ)²]²

    For this tunnel the difference between Dryden and von Kármán lives well
    above the achievable bandwidth, so pick either. Included because reviewers
    sometimes ask for one specifically.
    """
    rng = np.random.default_rng(seed)
    n = int(round(duration / dt))

    freqs = np.fft.rfftfreq(n, dt)
    omega = 2 * np.pi * freqs / u_mean

    psd = (sigma ** 2) * (2 * length_scale / np.pi) / \
          (1 + (length_scale * omega) ** 2) ** 2
    psd[0] = 0.0

    white = rng.normal(size=len(freqs)) + 1j * rng.normal(size=len(freqs))
    fluct = np.fft.irfft(white * np.sqrt(psd), n=n)
    if np.std(fluct) > 0:
        fluct = fluct * (sigma / np.std(fluct))
    if f_max is not None:
        fluct = band_limit(fluct, dt, f_max)
    fluct = taper_ends(fluct, dt, taper_s)

    t_lead = np.arange(0, lead, dt)
    u = np.concatenate([np.full_like(t_lead, u_mean), u_mean + fluct])
    return np.arange(len(u)) * dt, u


# ═══════════════════════════════════════════════════════════════════════════
# ARBITRARY PROFILES
# ═══════════════════════════════════════════════════════════════════════════

def from_csv(path, dt=0.05, calibration=None):
    """
    Load a preprogrammed plan from CSV and resample onto a uniform dt.

    Expects a header row with a time column and one value column:

        time_s, rpm          ← fan RPM
        time_s, hz           ← drive frequency
        time_s, mps          ← velocity, m/s   (needs a calibration)
        time_s, mph          ← velocity, mph   (needs a calibration)

    The time column may be named t, time, time_s, or seconds. Rows need not be
    evenly spaced — the plan is linearly interpolated onto `dt`, so you can
    write sparse breakpoints and let the resampler fill in:

        time_s,mps
        0,10
        30,10
        45,22        ← a 15 s ramp, written as two lines
        90,22
        105,10

    Returns (t, u_hz) ready to hand to the player, plus a description string.

    Interpolation is linear between your breakpoints, so a plan written as
    sparse corners produces straight ramps — not the smooth 1-cosine shape a
    real gust has. If you want a smooth gust, use `gust 1mc` rather than
    hand-writing corners here.
    """
    import csv as _csv

    with open(path, newline="") as f:
        rows = list(_csv.DictReader(f))
    if not rows:
        raise ValueError(f"{path} has no data rows")

    cols = {k.strip().lower(): k for k in rows[0]}
    t_key = next((cols[k] for k in ("t", "time", "time_s", "seconds", "sec")
                  if k in cols), None)
    if t_key is None:
        raise ValueError(f"{path} needs a time column (t / time / time_s). "
                         f"Found: {list(rows[0])}")

    for unit in ("hz", "rpm", "mps", "m/s", "mph", "fps"):
        if unit in cols:
            v_key, v_unit = cols[unit], unit
            break
    else:
        raise ValueError(f"{path} needs a value column named one of "
                         f"hz / rpm / mps / mph / fps. Found: {list(rows[0])}")

    t_raw = np.array([float(r[t_key]) for r in rows])
    v_raw = np.array([float(r[v_key]) for r in rows])

    if not np.all(np.diff(t_raw) > 0):
        raise ValueError("time column must be strictly increasing")

    # Convert to Hz, which is the only thing the drive understands.
    if v_unit == "hz":
        hz_raw, desc = v_raw, "Hz"
    elif v_unit == "rpm":
        if calibration is None or calibration.rpm_per_hz is None:
            raise ValueError("an RPM plan needs a calibration with a drive map")
        hz_raw, desc = v_raw / calibration.rpm_per_hz, "RPM"
    else:
        if calibration is None:
            raise ValueError(f"a {v_unit} plan needs a velocity calibration")
        from calibration import TO_MPS
        native = v_raw * TO_MPS[v_unit] / TO_MPS.get(calibration.units.lower(), 1.0)
        hz_raw, desc = calibration.hz_profile(native), v_unit

    t = np.arange(t_raw[0], t_raw[-1] + dt / 2, dt)
    return t, np.interp(t, t_raw, hz_raw), f"{len(rows)} breakpoints in {desc}"


# ═══════════════════════════════════════════════════════════════════════════
# UNIT CONVERSION AND FEASIBILITY
# ═══════════════════════════════════════════════════════════════════════════

def velocity_to_hz(u, calibration):
    """
    Convert a velocity profile to drive frequency.

    `calibration` is a callable, u → Hz. Get it from characterize.py's steady
    sweep, which fits your tunnel's actual velocity-vs-frequency curve. It is
    close to linear on most tunnels but do not assume it passes through the
    origin — there is usually an offset from fan and duct losses at low speed.
    """
    return np.asarray([calibration(x) for x in np.atleast_1d(u)])


def predict_response(t, u, tau, tau_down=None, dead_time=0.0):
    """
    Push a profile through the tunnel model and return what comes out.

    Integrated in the time domain rather than the frequency domain, because
    the plant is **direction-dependent** and that cannot be represented as a
    single transfer function:

      · Rising, the limit is motor torque against fan inertia.
      · Falling, the limit is how much regenerated energy the DC bus can
        absorb. Without a brake chopper, down is slower than up.

    This matters more than it sounds. A 1-cosine gust is symmetric by
    construction, so the **falling edge is what limits you** — and a symmetric
    model is optimistic about exactly the half that fails first.

    Pass tau_down from characterize. If you leave it None the model is
    symmetric and you should treat its answer as a best case.
    """
    u = np.asarray(u, dtype=float)
    dt = float(t[1] - t[0])
    tau_down = tau if tau_down is None else tau_down
    lag = int(round(dead_time / dt))
    y = np.empty(len(u))
    y[0] = u[0]
    for i in range(1, len(u)):
        drive_val = u[max(0, i - lag)]
        tc = tau if drive_val > y[i - 1] else tau_down
        alpha = 1 - np.exp(-dt / tc) if tc > 0 else 1.0
        y[i] = y[i - 1] + alpha * (drive_val - y[i - 1])
    return y


def check_realizable(t, u, tau=None, max_slew_hz_s=None, verbose=True,
                     tau_down=None, dead_time=0.0):
    """
    Check a profile against the tunnel's physical limits before you run it.
    Returns a dict of diagnostics; prints warnings by default.

    Two failure modes, both of which are silent on the hardware:

    1. **Slew rate.** If the profile demands faster dU/dt than the drive's ramp
       allows, the drive clips it. No error anywhere — you simply run a
       different experiment than the one you designed.

    2. **Bandwidth.** Content above the corner frequency (1/2πτ) is attenuated
       and phase-shifted. The headline number here is `amplitude_retained`:
       the fraction of your commanded peak-to-peak that survives the lag.
       Below about 0.7 you are no longer running the gust you drew.

    Args:
        tau:           tunnel time constant in seconds, from characterize.py
        max_slew_hz_s: MAX FREQ / ramp time, from parameters 2008 and 2202
    """
    dt = t[1] - t[0]
    slew = np.abs(np.diff(u) / dt)
    pp_in = float(u.max() - u.min())
    out = {"max_slew": float(slew.max()) if len(slew) else 0.0,
           "peak_to_peak": pp_in,
           "mean": float(u.mean()),
           "std": float(u.std()),
           "duration": float(t[-1])}

    if max_slew_hz_s is not None:
        out["slew_ok"] = out["max_slew"] <= max_slew_hz_s
        if verbose and not out["slew_ok"]:
            print(f"  SLEW      profile demands {out['max_slew']:.1f} Hz/s, "
                  f"drive ramp allows {max_slew_hz_s:.1f} Hz/s")
            print(f"            → shorten par 2202/2203, or lengthen the gust")

    if tau is not None:
        f_corner = 1.0 / (2 * np.pi * tau)
        out["f_corner"] = float(f_corner)

        filtered = predict_response(t, u, tau, tau_down=tau_down,
                                    dead_time=dead_time)
        pp_out = float(filtered.max() - filtered.min())
        retained = pp_out / pp_in if pp_in > 0 else 1.0
        out["amplitude_retained"] = retained
        out["predicted_peak_to_peak"] = pp_out

        # Power spectrum, not magnitude — magnitude sums over thousands of
        # near-empty high-frequency bins and reads alarmingly high for
        # profiles that are perfectly fine.
        power = np.abs(np.fft.rfft(u - u.mean())) ** 2
        freqs = np.fft.rfftfreq(len(u), dt)
        if power.sum() > 0:
            out["frac_power_above_corner"] = float(
                power[freqs > f_corner].sum() / power.sum())

        if tau_down and tau_down > tau * 1.1:
            sym = predict_response(t, u, tau)
            # Peak-to-peak cannot see this: a 1-cosine returns to its own
            # baseline, so both models share a minimum. The asymmetry lives in
            # the shape and in how long the tunnel takes to come back.
            out["asymmetry_rms"] = (float(np.sqrt(np.mean((filtered - sym) ** 2)))
                                    / pp_in if pp_in else 0.0)
            base = float(u[0])
            tol = 0.05 * pp_in
            def recovery(y):
                after = np.where(np.abs(y - base) > tol)[0]
                return float(t[after[-1]] - t[np.argmax(np.abs(u - base) > tol)]) \
                    if len(after) else 0.0
            out["recovery_s"] = recovery(filtered)
            out["recovery_penalty_s"] = out["recovery_s"] - recovery(sym)

        if verbose:
            if out.get("asymmetry_rms", 0) > 0.02:
                print(f"  ASYMMETRY the slower down-ramp distorts the shape by "
                      f"{out['asymmetry_rms']:.1%} RMS vs a symmetric model,")
                print(f"            and the tunnel takes "
                      f"{out['recovery_penalty_s']:.1f} s longer to return to "
                      f"baseline ({out['recovery_s']:.0f} s total). Budget that "
                      f"between repeats or they contaminate each other.")
            if retained >= 0.85:
                verdict = "good — the tunnel will follow this closely"
            elif retained >= 0.70:
                verdict = "acceptable — mild rounding of the peak"
            elif retained >= 0.40:
                verdict = "MARGINAL — noticeably smaller and smoother than drawn"
            else:
                verdict = "NOT REALIZABLE — you will get a ripple, not a gust"
            td = tau_down if tau_down else tau
            print(f"  BANDWIDTH τ={tau:.1f} s up / {td:.1f} s down, "
                  f"corner {f_corner:.3f} Hz")
            print(f"            predicted amplitude retained: {retained:.0%} "
                  f"({pp_in:.1f} → {pp_out:.1f} Hz p-p)")
            print(f"            {verdict}")

    if verbose:
        print(f"  PROFILE   {out['duration']:.0f} s · mean {out['mean']:.1f} · "
              f"p-p {pp_in:.1f} · peak slew {out['max_slew']:.1f} Hz/s")
    return out


PROFILES = {
    "1mc": one_minus_cosine,
    "step": sharp_edged,
    "ramp": ramp,
    "sine": sinusoid,
    "chirp": chirp,
    "vonkarman": von_karman,
    "dryden": dryden,
}
