"""
feedforward.py — pre-compensate a profile so the tunnel produces what you asked for.

This is the highest-leverage thing in the package. It attacks the project's
binding constraint — bandwidth — with software instead of hardware.

═══════════════════════════════════════════════════════════════════════════
THE IDEA
═══════════════════════════════════════════════════════════════════════════
The tunnel is a low-pass filter G(s). Command u and you get G·u, which is
smaller and later than u. But if you command G⁻¹·u instead, you get
G·G⁻¹·u = u — the gust you actually drew.

In practice G⁻¹ is a high-pass, so the compensated command overshoots hard at
every edge: to make the flow rise quickly you have to demand far more than the
final value and then back off. That is exactly what a human does easing a
throttle, and it is why the compensated waveform looks alarming on a plot and
is nevertheless correct.

═══════════════════════════════════════════════════════════════════════════
WHY IT DOESN'T GIVE YOU INFINITE BANDWIDTH
═══════════════════════════════════════════════════════════════════════════
Three walls, in the order you hit them:

1. **Slew limit.** The overshoot has to be reachable. Par 2202/2203 cap how
   fast the drive will move, and beyond that the compensation is clipped —
   you get partial correction, not the full inverse.

2. **Amplitude headroom.** Compensating a gust near the top of the operating
   range needs frequency the drive does not have. There is more room to
   compensate at 20 Hz than at 55 Hz.

3. **Noise amplification.** G⁻¹ amplifies everything at high frequency,
   including numerical noise in the profile. Hence the mandatory low-pass on
   the inverse (`f_cutoff`), which is what keeps this from being a
   differentiator.

Realistically this buys **2–3x usable bandwidth**. That can be the difference
between "long-period gusts only" and a defensible gust generator — but it does
not turn a 15 HP fan into a fast actuator. Be careful how you describe it.

═══════════════════════════════════════════════════════════════════════════
HONESTY REQUIREMENT
═══════════════════════════════════════════════════════════════════════════
`compensate()` returns the compensated command **and** the flow it predicts.
Log and plot the predicted flow, not the command, when you describe what the
model saw. The command is a means; the flow is the experiment.
"""

from __future__ import annotations

import numpy as np


def compensate(t, u_desired, tau, dead_time=0.0, tau_down=None,
               f_cutoff=None, slew_limit=None, hz_limit=None,
               hz_floor=0.0, verbose=True):
    """
    Build a drive command that makes the *flow* follow u_desired.

    Args:
        u_desired:  the profile you want the air to follow, in Hz
        tau:        tunnel time constant (rising), from characterize
        tau_down:   falling time constant. Defaults to tau. Supply the real
                    one — the tunnel decelerates more slowly than it
                    accelerates, and the falling edge is what limits a
                    symmetric gust.
        dead_time:  transport delay. Compensated by advancing the command.
        f_cutoff:   low-pass on the inverse. Defaults to 5/(2πτ), i.e. five
                    times the tunnel corner. Raising it buys sharpness and
                    amplifies noise.
        slew_limit: Hz/s the drive can actually deliver (MAX FREQ / par 2202)
        hz_limit:   soft ceiling; the compensated command is clipped to it

    Returns dict with 'command', 'predicted', and diagnostics.
    """
    n = len(u_desired)
    dt = float(t[1] - t[0])
    tau_down = tau if tau_down is None else tau_down
    if f_cutoff is None:
        f_cutoff = 5.0 / (2 * np.pi * tau)

    mean = float(np.mean(u_desired))
    x = np.asarray(u_desired, dtype=float) - mean

    freqs = np.fft.rfftfreq(n, dt)
    w = 2 * np.pi * freqs

    # Inverse of the first-order lag, low-passed so it stays a filter rather
    # than a differentiator. Use the average of the two time constants for the
    # linear inverse — the asymmetry is handled by the slew check below, since
    # a single LTI inverse cannot represent a direction-dependent plant.
    tau_eff = 0.5 * (tau + tau_down)
    G_inv = 1.0 + 1j * w * tau_eff
    lp = 1.0 / (1.0 + 1j * freqs / f_cutoff) ** 2      # 2-pole, gentle rolloff
    H = G_inv * lp

    if dead_time > 0:
        H = H * np.exp(1j * w * dead_time)             # advance the command

    cmd = np.fft.irfft(np.fft.rfft(x) * H, n=n) + mean

    out = {"f_cutoff": float(f_cutoff), "tau_eff": float(tau_eff),
           "clipped_slew": False, "clipped_range": False}

    # Enforce the physical limits, in the order the drive would.
    if slew_limit is not None:
        max_step = slew_limit * dt
        limited = np.empty_like(cmd)
        limited[0] = cmd[0]
        for i in range(1, n):
            d = cmd[i] - limited[i - 1]
            limited[i] = limited[i - 1] + np.clip(d, -max_step, max_step)
        clipped = float(np.max(np.abs(limited - cmd)))
        if clipped > 0.05:
            out["clipped_slew"] = True
            out["slew_clip_hz"] = clipped
        cmd = limited

    lo, hi = hz_floor, (hz_limit if hz_limit else np.inf)
    if np.any(cmd < lo) or np.any(cmd > hi):
        out["clipped_range"] = True
        out["range_overshoot_hz"] = float(max(lo - cmd.min(), cmd.max() - hi, 0))
        cmd = np.clip(cmd, lo, hi)

    # Predict what the flow will actually do given the command we ended up with.
    pred = simulate_flow(cmd, dt, tau, tau_down, dead_time)

    pp_want = float(u_desired.max() - u_desired.min())
    pp_get = float(pred.max() - pred.min())
    naive = simulate_flow(np.asarray(u_desired, float), dt, tau,
                          tau_down, dead_time)
    pp_naive = float(naive.max() - naive.min())

    # Peak-to-peak alone is a misleading score: the compensator can overshoot
    # and report >100% "retained" while tracking the shape worse. RMS error
    # against the desired profile is the honest number, so report both.
    des = np.asarray(u_desired, float)
    scale = pp_want if pp_want > 0 else 1.0
    rms_comp = float(np.sqrt(np.mean((pred - des) ** 2)) / scale)
    rms_naive = float(np.sqrt(np.mean((naive - des) ** 2)) / scale)

    out.update({
        "command": cmd, "predicted": pred,
        "overshoot_ratio": float((cmd.max() - cmd.min()) / pp_want) if pp_want else 1.0,
        "retained_compensated": pp_get / pp_want if pp_want else 1.0,
        "retained_uncompensated": pp_naive / pp_want if pp_want else 1.0,
        "rms_error_compensated": rms_comp,
        "rms_error_uncompensated": rms_naive,
    })
    out["rms_improvement"] = (rms_naive / rms_comp if rms_comp > 0 else np.nan)
    out["improvement"] = (out["retained_compensated"] /
                          out["retained_uncompensated"]
                          if out["retained_uncompensated"] > 0 else np.nan)

    if verbose:
        print(f"  FEEDFORWARD  τ={tau:.1f}/{tau_down:.1f} s, "
              f"cutoff {f_cutoff:.3f} Hz")
        print(f"    without compensation the flow retains "
              f"{out['retained_uncompensated']:.0%} of the commanded amplitude")
        print(f"    with compensation:      "
              f"{out['retained_compensated']:.0%}  "
              f"({out['improvement']:.1f}x better)")
        print(f"    RMS tracking error {rms_naive:.1%} → {rms_comp:.1%} of "
              f"amplitude ({out['rms_improvement']:.1f}x)")
        if out["retained_compensated"] > 1.05:
            print(f"    note: >100% retained means the compensated flow "
                  f"overshoots. The inverse uses a single time constant while "
                  f"the tunnel's differs up vs down, so the rising edge is "
                  f"slightly over-driven. RMS error is the metric to trust.")
        print(f"    command swings {out['overshoot_ratio']:.1f}x the "
              f"desired amplitude to achieve it")
        if out["clipped_slew"]:
            print(f"    ! slew-limited by {out['slew_clip_hz']:.1f} Hz — "
                  f"shorten par 2202/2203 to get the full benefit")
        if out["clipped_range"]:
            print(f"    ! clipped {out['range_overshoot_hz']:.1f} Hz at the "
                  f"limits — lower the mean or reduce the amplitude")
        if out["rms_improvement"] < 1.0:
            print(f"    !! COMPENSATION IS MAKING THIS WORSE. Amplitude looks\n"
                  f"       recovered but the shape is more distorted than the\n"
                  f"       uncompensated run. The profile is beyond what the\n"
                  f"       drive can deliver, so the inverse gets clipped into\n"
                  f"       something that overshoots and mistimes rather than\n"
                  f"       tracking. Lengthen the gust or raise the slew limit;\n"
                  f"       do not run this as-is.")
        elif out["improvement"] < 1.15:
            print(f"    compensation is buying almost nothing here. The "
                  f"profile is either already slow enough not to need it, or "
                  f"so fast that the drive cannot deliver the overshoot.")
    return out


def simulate_flow(cmd, dt, tau_up, tau_down=None, dead_time=0.0):
    """
    Forward model: what the flow does given a drive command.

    Direction-dependent time constant, so a symmetric command produces an
    asymmetric flow — which is what the real tunnel does, and what a
    frequency-domain model cannot represent.
    """
    tau_down = tau_up if tau_down is None else tau_down
    n = len(cmd)
    lag = int(round(dead_time / dt))
    y = np.empty(n)
    y[0] = cmd[0]
    for i in range(1, n):
        drive_val = cmd[max(0, i - lag)]
        tau = tau_up if drive_val > y[i - 1] else tau_down
        alpha = 1 - np.exp(-dt / tau) if tau > 0 else 1.0
        y[i] = y[i - 1] + alpha * (drive_val - y[i - 1])
    return y


def max_useful_frequency(tau, slew_limit, amplitude_hz, tau_down=None):
    """
    The highest sinusoid frequency the tunnel can produce at a given amplitude
    once compensation is applied, limited by slew rate.

    Compensating a sinusoid of amplitude A at frequency f needs a command
    amplitude of roughly A·√(1+(2πfτ)²), whose peak slew is 2πf times that.
    Setting that equal to the slew limit and solving gives the ceiling.

    Use this to size a test matrix before running anything.
    """
    tau_eff = tau if tau_down is None else 0.5 * (tau + tau_down)
    lo, hi = 1e-4, 50.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        w = 2 * np.pi * mid
        need = amplitude_hz * np.sqrt(1 + (w * tau_eff) ** 2) * w
        if need > slew_limit:
            hi = mid
        else:
            lo = mid
    return lo
