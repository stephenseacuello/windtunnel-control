#!/usr/bin/env python3
"""
sweep_core.py — the blade-sweep protocol, in one place.

`blade_sweep.py` and the Flask dashboard both characterise a rotor, and their
numbers only mean something if they are the SAME measurement. They were not.

    CLI        94bed28333f7
    dashboard  8cfbc0b85199

The two hashed differences (a `via=dashboard` prefix and floor 0.002 vs 0.000)
were the visible part. The important differences were not in the hash at all:

  · the dashboard's settle was a blind `time.sleep(max(2.0, dwell*2))` with no
    wait for the fan to reach speed — reintroducing the exact failure this
    package documents, because 0.000 V is perfectly stable and a still-
    accelerating tunnel therefore reads as settled;
  · `CONF:VOLT:OFF` was never written on the dashboard's real path, while its
    fingerprint asserted voff=0.500. The Chroma ships at 3.00 V and the
    setting is instrument-persistent, so it claimed a cut-out it never set;
  · the ceiling rule differed — max(4*step, ...) computed from a different
    base — and `collapse_frac` and `confirm` were asserted but never passed.

A fingerprint that hashes settings the code does not actually use is worse
than no fingerprint: it certifies agreement that does not exist. So the rules,
the settle and the per-point body live here, and both callers use them.

═══════════════════════════════════════════════════════════════════════════
WHAT THIS DELIBERATELY DOES NOT OWN
═══════════════════════════════════════════════════════════════════════════
· It never opens a transport and never starts a thread. The dashboard already
  polls the PMC on its own thread behind a lock; a second poller here would be
  two readers on a port that permits one, outside that lock.
· It does not persist. The caller decides where rows go, because the CLI
  writes CSVs and the dashboard also streams to a browser.
· It does not command RUN or STOP. Those sit behind interlocks owned by the
  caller, and a core that could start a fan would put a 15 HP machine one
  import away from anything.

The caller passes a `rig` exposing:
    set_speed(rpm)        command the fan
    fan_rpm               actual fan speed, kept fresh by the caller
    motor_amps            actual motor current
    load                  the electronic load, already serialised if needed
    rotor_rpm_between(t0, t1)   optional; None when unavailable
"""

from __future__ import annotations

import math
import time
from pathlib import Path
from types import SimpleNamespace

from chroma_load import CC_FULL_SCALE, ChromaLoad, LoadError
from load_ramp import protocol_meta, wind_from_rpm
from peak_finder import find_peak

# The campaign protocol. Changing any of these changes the fingerprint, which
# is the point: a run under different settings must not be mistaken for one of
# these. `94bed28333f7` is the hash of these values at step 0.02 / dwell 1.0.
CAMPAIGN = dict(
    step_amps=0.02, step_scaling="v2", min_step_amps=0.001, dwell=1.0,
    stop_power_frac=0.80, unload_amps=0.0, max_amps=0.8, volt_off=0.5,
    range="low", collapse_frac=0.70, confirm=2, step_frac=0.0,
    settle_min=2.0, settle_max=30.0, settle_poll=0.25, settle_tol=0.02,
    settle_confirm=3, rpm_tol_abs=15.0, rpm_tol_frac=0.03,
    start_rpm=500, stop_rpm=1800, rpm_step=100,
)


def settings(**over):
    """
    A settings object with the campaign defaults, overridable.

    Returned as a namespace rather than a dict because `protocol_meta` and the
    rules below read attributes, and because the CLI's argparse namespace can
    be passed to exactly the same functions — which is what makes the
    extraction a pure move rather than a rewrite.
    """
    s = SimpleNamespace(**CAMPAIGN)
    for k, v in over.items():
        if v is not None:
            setattr(s, k, v)
    # protocol_meta reads these names; keep them in lockstep with the ladder.
    s.min_step = s.step_amps
    s.floor_amps = s.unload_amps
    s.percent = s.stop_power_frac * 100.0
    s.blade = getattr(s, "blade", None)
    s.notes = getattr(s, "notes", "")
    # protocol_meta records the FIRST wind speed of the run in its header.
    s.fan_rpm = getattr(s, "fan_rpm", s.start_rpm)
    return s


# ── the rules ─────────────────────────────────────────────────────────────

def ceiling_for(rpm, a):
    """
    Backstop current for this wind speed.

    Scales as v², because threshold current tracks torque. It is only a
    backstop — the power roll-off should stop the ramp long before it — but
    without it a point where the roll-off is never detected would ramp to the
    top of the range against a rotor that cannot supply it.
    """
    frac = (wind_from_rpm(rpm) / wind_from_rpm(a.stop_rpm)) ** 2
    return max(4 * a.step_amps, a.max_amps * frac)


def step_for(rpm, a):
    """
    Ladder increment at this wind speed.

    `fixed` is the protocol as stated: 10 mA everywhere. It works at the top of
    the range and cannot work at the bottom — peak current goes as v², so the
    same 10 mA that gives ~35 dwells to the peak at 1800 rpm gives THREE at
    500 rpm, and a ramp with three points either side of a maximum overshoots
    into stall before the roll-off can be confirmed. That is not a tuning
    preference; it showed up as four failed points out of fourteen.

    `v2` keeps the chosen step at --stop-rpm and scales it down as v², so every
    wind speed gets comparable resolution. One rule applied identically to
    every blade, and the rule is in the fingerprint.
    """
    if a.step_scaling == "fixed":
        return a.step_amps
    frac = (wind_from_rpm(rpm) / wind_from_rpm(a.stop_rpm)) ** 2
    return max(a.min_step_amps, a.step_amps * frac)


def estimate(a, rpms):
    """Seconds of continuous tunnel time, roughly."""
    total = 0.0
    for rpm in rpms:
        steps = ceiling_for(rpm, a) / max(step_for(rpm, a), 1e-6)
        total += a.settle_min * 2 + steps * a.dwell + 2 * a.dwell
    return total


def protocol(a, voff, rng, load=None):
    """
    The fingerprint and its metadata — ONE definition.

    Built by `load_ramp.protocol_meta` so the CLI's existing runs keep their
    hash. The dashboard used to hand-write this string, which is how it came
    to assert a cut-out voltage it never applied.
    """
    return protocol_meta(a, load, voff, rng)


def prepare_load(load, a):
    """
    Range and cut-out voltage, applied and read back.

    `CONF:VOLT:OFF` is instrument-persistent and the Chroma ships at 3.00 V.
    The dashboard never wrote it while its fingerprint claimed 0.500, so every
    dashboard run carried a cut-out three times higher than recorded — which
    truncates a ramp early and looks like a rotor that gave up.
    """
    rng = a.range if a.range != "auto" else ChromaLoad.pick_range(
        ceiling_for(a.stop_rpm, a), CC_FULL_SCALE)
    voff = load.volt_off(a.volt_off) if a.volt_off is not None else load.volt_off()
    return rng, voff


# ── the settle ────────────────────────────────────────────────────────────

def settle_wind(load, a, rig=None, target_rpm=None, log=None):
    """
    Wait for the wind to arrive, then for it to stop changing.

    A fixed settle is a guess about the tunnel's time constant. Too short and
    every point is measured on the way somewhere — and since power goes as v³,
    a velocity still 5% low is a power 15% low. Too long and it is fourteen
    times wasted.

    Watching terminal voltage answers it directly: voltage follows rotor speed,
    rotor speed follows wind, so when voltage stops moving the wind has
    arrived.

    Watching voltage ALONE is not enough, and point 1 of the first real sweep
    proved it: the fan was still accelerating through 440 rpm, the rotor was
    producing nothing, and **0.000 V is perfectly stable**. The test declared
    it settled and the point was recorded empty.

    So it waits on the FAN first, then on the voltage. This is precisely the
    guard the dashboard's blind sleep did not have.

    Returns (volts, amps, fan_rpm).
    """
    t0 = time.monotonic()

    # ── phase 1: is the fan actually at the speed we asked for? ─────────
    if rig is not None and target_rpm:
        tol = max(a.rpm_tol_abs, a.rpm_tol_frac * target_rpm)
        while time.monotonic() - t0 < a.settle_max:
            if abs(rig.fan_rpm - target_rpm) <= tol:
                break
            time.sleep(a.settle_poll)
        else:
            if log:
                log(f"fan reached {rig.fan_rpm:.0f} rpm, asked for "
                    f"{target_rpm:.0f}, after {a.settle_max:.0f} s")

    # ── phase 2: has the rotor stopped changing? ────────────────────────
    t1 = time.monotonic()
    last, stable = None, 0
    while time.monotonic() - t1 < a.settle_max:
        time.sleep(a.settle_poll)
        v, i, _ = load.measure()
        if last is not None and abs(v - last) <= max(a.settle_tol * max(v, 0.1),
                                                     0.02):
            stable += 1
            if stable >= a.settle_confirm and time.monotonic() - t1 >= a.settle_min:
                return v, i, (rig.fan_rpm if rig else 0.0)
        else:
            stable = 0
        last = v
    v, i, _ = load.measure()
    return v, i, (rig.fan_rpm if rig else 0.0)


# ── one wind speed ────────────────────────────────────────────────────────

def measure_point(rig, a, rpm, rng, voff, log=None, on_step=None):
    """
    One wind speed: command it, settle, ramp the load, find the peak, unload.

    Returns a namespace with the PeakResult and everything a row needs, or
    with `.dead` set when the rotor produced no terminal voltage — the caller
    decides whether two of those in a row should abort, because the CLI exits
    and the dashboard reports.
    """
    log = log or (lambda *_: None)
    rig.set_speed(rpm)
    v, i, rpm_act = settle_wind(rig.load, a, rig, rpm, log=log)
    log(f"settled: {v:.3f} V at {i:.4f} A   (fan {rpm_act:.0f} rpm, "
        f"{rig.motor_amps:.1f} A)")

    if v <= max(voff, 0.05):
        rig.load.set_mode_cc(a.unload_amps, range_=rng, verify=False)
        return SimpleNamespace(rpm=rpm, dead=True, result=None,
                               rpm_act=rpm_act, volts=v)

    ceiling, step = ceiling_for(rpm, a), step_for(rpm, a)
    if abs(step - a.step_amps) > 1e-9:
        log(f"step {step * 1000:.1f} mA (v² scaling of {a.step_amps * 1000:.0f} mA)")

    t_start = time.time()
    r = find_peak(
        rig.load, max_amps=ceiling, on_step=on_step,
        floor_amps=max(a.unload_amps, step * 0.5),
        min_step=step, step_frac=0.0, dwell=a.dwell,
        operate_frac=0.0,               # the protocol unloads, it does not hold
        v_floor=voff, range_=rng,
        stop_power_frac=a.stop_power_frac,
        collapse_frac=a.collapse_frac, confirm=a.confirm)

    # Unload before the next wind step.
    rig.load.set_mode_cc(a.unload_amps, range_=rng, verify=False)
    time.sleep(a.dwell)

    return SimpleNamespace(rpm=rpm, dead=False, result=r, rpm_act=rpm_act,
                           volts=v, t_start=t_start, step=step,
                           ceiling=ceiling, dwell=a.dwell)


# ── rotor speed ───────────────────────────────────────────────────────────

RPM_PULSES_PER_REV = 1      # one magnet on one blade

def rotor_rpm_between(samples, t0, t1):
    """
    Mean rotor rpm over a window, from (t, pulses, last_us) samples, or None.

    Counts whole revolutions between the first and last accepted pulse in the
    window and divides by the time THOSE pulses took, measured by the PMC's own
    microsecond timer. Exact: no host scheduling jitter, and no quantisation
    from where the window edges fall relative to the magnet.

    BRACKETS the window rather than requiring two samples strictly inside it.
    At a 1 s tick against a 1 s dwell there is usually exactly one, so a strict
    test returns None and the column comes back empty for a whole run — a
    tunnel session spent producing a blank.

    ⚠️ The reed currently bounces 2-3 times per magnet pass and the count
    varies, so the number this returns is not yet trustworthy. See
    docs/11_open_questions.md.
    """
    ss = [x for x in samples if x[1] is not None]
    if len(ss) < 2:
        return None
    before = [x for x in ss if x[0] <= t0]
    upto = [x for x in ss if x[0] <= t1]
    s0 = before[-1] if before else ss[0]
    s1 = upto[-1] if upto else None
    if s1 is None or s1[0] <= s0[0]:
        return None
    d_pulses = (s1[1] - s0[1]) & 0xFFFFFFFF
    d_us = (s1[2] - s0[2]) & 0xFFFFFFFF
    if d_pulses < 1 or d_us < 1:
        return None                 # rotor stopped, or one pulse is not a rate
    return 60e6 * d_pulses / (d_us * RPM_PULSES_PER_REV)


def interp_at(pairs, x):
    """
    Linear interpolation of y at x over (x, y) pairs, y possibly None.

    Used to read rotor speed at the FITTED peak current. The peak lies between
    two dwells, so the honest answer is between their two speeds; taking the
    nearer dwell would pair a tip-speed ratio with a power measured somewhere
    else. Returns None rather than guessing when the fitted peak falls outside
    the measured currents — which happens when a ramp stopped early, and is
    exactly when a silently extrapolated number would mislead most.
    """
    pts = sorted(((float(a), float(b)) for a, b in pairs if b is not None),
                 key=lambda t: t[0])
    if len(pts) < 2 or x is None:
        return None
    if x <= pts[0][0] or x >= pts[-1][0]:
        return None
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return None


# ── the files ─────────────────────────────────────────────────────────────
#
# Both front ends write the SAME columns. The dashboard used to write nine
# where the CLI wrote sixteen, and derived wind speed from COMMANDED rpm where
# the CLI uses measured — so even at an identical protocol the two produced
# files that could not be compared. A shared fingerprint over files of
# different shape is the same false assurance the fingerprint exists to
# prevent.

ROTOR_RADIUS_M = 0.1016     # 4 in, axis of rotation to blade attachment

SUMMARY_HEADER = ["fan_rpm_cmd", "fan_rpm_actual", "wind_mps", "blade",
                  "p_max_fit_w", "i_at_pmax_fit_a", "p_max_raw_w",
                  "i_at_pmax_raw_a", "v_at_pmax_v", "i_last_a", "limited_by",
                  "clean", "steps", "stopped_by",
                  "turbine_rpm_at_pmax", "tsr_at_pmax"]

POINTS_HEADER = ["t_unix", "t_local", "fan_rpm", "wind_mps", "blade",
                 "demand_a", "held_a", "volts", "amps", "watts", "tracking",
                 "note", "fan_rpm_actual", "motor_amps", "turbine_rpm"]


def summary_row(pt, blade, rotor_rpm=None):
    """One summary row from a measure_point result."""
    r = pt.result
    v_mps = wind_from_rpm(pt.rpm_act or pt.rpm)
    tsr = (None if rotor_rpm is None or v_mps <= 0 else
           (rotor_rpm * 2 * math.pi / 60.0) * ROTOR_RADIUS_M / v_mps)
    return [pt.rpm, f"{pt.rpm_act:.0f}", f"{v_mps:.2f}", blade,
            f"{r.fit_watts:.4f}", f"{r.fit_amps:.4f}",
            f"{r.power_peak_watts:.4f}", f"{r.power_peak_amps:.4f}",
            f"{r.power_peak_volts:.4f}", f"{r.peak_amps:.4f}", r.limited_by,
            int(r.clean), len(r.trace), r.stopped_by,
            "" if rotor_rpm is None else f"{rotor_rpm:.1f}",
            "" if tsr is None else f"{tsr:.4f}"]


def point_rows(pt, blade, fan_rpm_at, rotor_rpm_at):
    """
    Per-dwell rows, with the drive state and rotor speed DURING each dwell.

    `fan_rpm_at(t)` and `rotor_rpm_at(t0, t1)` are supplied by the caller,
    because the CLI samples on DriveWatch's thread and the dashboard on its
    own poll thread. Neither may start a second one.
    """
    out, dwell_rpm = [], []
    for st in pt.result.trace:
        w_rpm = rotor_rpm_at(st.t_unix - pt.dwell, st.t_unix)
        f_rpm, m_amps = fan_rpm_at(st.t_unix)
        dwell_rpm.append((st.amps, w_rpm))
        out.append([f"{st.t_unix:.3f}",
                    time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.t_unix)),
                    pt.rpm, f"{wind_from_rpm(pt.rpm):.2f}", blade,
                    f"{st.demand_a:.4f}",
                    "" if st.held_a is None else f"{st.held_a:.4f}",
                    f"{st.volts:.4f}", f"{st.amps:.4f}", f"{st.watts:.4f}",
                    int(st.tracking), st.note,
                    f"{f_rpm:.0f}", f"{m_amps:.2f}",
                    "" if w_rpm is None else f"{w_rpm:.1f}"])
    return out, dwell_rpm


def archive_existing(logs_dir, blade):
    """
    Move a previous run of this blade name aside. Returns what it moved.

    Both front ends write to logs/sweep_<blade>_*.csv, and both overwrote.
    The dashboard's "archive copy" ran AFTER the write and copied the file it
    had just produced, so a re-run destroyed the earlier curve and then
    archived the new one under a timestamp. The CLI had no archive at all.

    v1_Ra20 is one of two blade runs this project has and the baseline for its
    only result. Typing that name a second time would have taken it.

    Renamed rather than copied, and stamped from the ORIGINAL file's mtime, so
    the archive records when the data was TAKEN rather than when it was
    displaced. Both files move together: a summary without its points is a
    curve nobody can re-analyse.
    """
    import time as _t
    logs_dir = Path(logs_dir)
    moved = []
    for suffix in ("_summary.csv", "_points.csv"):
        old = logs_dir / f"sweep_{blade}{suffix}"
        if not old.exists():
            continue
        when = _t.strftime("%Y%m%d_%H%M%S", _t.localtime(old.stat().st_mtime))
        keep = logs_dir / f"sweep_{blade}_{when}{suffix}"
        i = 1
        while keep.exists():
            keep = logs_dir / f"sweep_{blade}_{when}_{i}{suffix}"
            i += 1
        old.rename(keep)
        moved.append(keep.name)
    return moved
