#!/usr/bin/env python3
"""
blade_sweep.py — one blade, the whole wind range, in a single run.

    python src/blade_sweep.py --blade v1_Ra20 --notes "PLA, 0.1mm, Ra 20"
    python src/blade_sweep.py --blade demo --simulate      # no hardware

THE PROTOCOL
════════════════════════════════════════════════════════════════════════════
    at 500 rpm fan:
        ramp the load 0.01, 0.02, 0.03 ... A
        stop once electrical power has fallen to 80% of its peak
        unload
    +100 rpm, repeat, up to 1800 rpm

Fourteen wind speeds, 10.2 to 38.0 m/s. The fan runs continuously; the drive
is stepped between points rather than stopped and restarted, which is both
faster and easier on a 15 HP motor than fourteen starts.

WHY IT STOPS ON THE POWER ROLL-OFF
════════════════════════════════════════════════════════════════════════════
Stopping at "power has fallen to 80% of peak" is a much better-behaved
criterion than ramping to the rotor's stall threshold:

  · it ends on the far side of a maximum you have actually observed, so the
    peak is bracketed rather than extrapolated
  · it never approaches stall, so the rotor is never driven to let go
  · it never reaches the load's cut-out voltage, so nothing is censored
  · it is far shorter. On the 1800 rpm data it stops near 0.48 A instead of
    0.69 A — 21 fewer dwells, and none of them in the interesting-but-useless
    region below 1 V.

COMPARING BLADES
════════════════════════════════════════════════════════════════════════════
Every run carries a protocol fingerprint. Two blades measured under different
settings are not two data points, and across a dozen rotors that is very easy
to do by accident. `summarise.py`-style analysis should refuse to compare runs
whose fingerprints differ.

**What this does NOT give you is Cp or λ.** Those need rotor RPM, and rotor
RPM comes from the DAQ. Without it you have P_max(v) per blade — a real
comparison, but one that cannot separate a blade that is aerodynamically
better from a blade whose runaway speed happens to sit closer to the
generator's sweet spot. Wire the DAQ channel in before the campaign, not
after, or every blade gets re-run.

THE INTERLOCK
════════════════════════════════════════════════════════════════════════════
Load on before wind up; wind down before load off; and if the fan cannot be
confirmed stopped, the load stays on. `TurbineInterlock` enforces it and this
runs inside it from end to end.

The protocol asks for 0 A between wind speeds. Worth being clear about what
that is: zero amps in constant current is an open circuit, and an unloaded
rotor accelerates. On this rig it is a smaller change than it sounds — at
1800 rpm the 5 mA floor already sits at 22.0 V against roughly 23 V open
circuit, so the "light load" was never far from open anyway. `--unload-amps`
sets it; 0.0 is the protocol, and a few tens of mA would be a genuinely
loaded idle if a future rotor turns out to be less tolerant.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chroma_load import (CC_FULL_SCALE, ChromaLoad, LoadError, TurbineInterlock,
                         build_transport)
from config import TunnelConfig
from peak_finder import find_peak
from load_ramp import protocol_meta, wind_from_rpm

REPO = Path(__file__).resolve().parent.parent


# ═══════════════════════════════════════════════════════════════════════════
# HARDWARE, OR SOMETHING SHAPED LIKE IT
# ═══════════════════════════════════════════════════════════════════════════

class SimulatedDrive:
    """Just enough ACS550 to run the loop with no tunnel."""

    def __init__(self, turbine):
        self.turbine = turbine
        self.ref1_max_hz = 2435.0
        self._rpm = 0.0

    def connect(self):
        return self

    def close(self):
        pass

    def start(self, rpm):
        self.set_hz(rpm)

    def set_hz(self, rpm):
        self._rpm = float(rpm)
        self.turbine.fan_rpm = max(1.0, float(rpm))
        return self._rpm

    def stop(self):
        self.set_hz(0.0)

    def actuals(self):
        return self._rpm, 0.0

    def is_faulted(self):
        return False

    def status(self):
        return {"_raw": 0}


def open_rig(a):
    """(drive, load, teardown). Real or simulated, same shape."""
    if a.simulate:
        from load_sim import SimulatedLoad, SimulatedTurbine
        turb = SimulatedTurbine(peak_watts=a.sim_watts, volts_at_peak=a.sim_volts)
        load = SimulatedLoad(turb, volt_off=a.volt_off or 0.5).connect()
        print("\n  SIMULATED — no tunnel, no instrument, no rotor.")
        return SimulatedDrive(turb).connect(), load

    cfg = TunnelConfig.load(a.config)

    spec = cfg.get("load")
    if not spec:
        raise SystemExit("tunnel.json has no `load` block")
    load = ChromaLoad(build_transport(spec), channel=spec.get("channel", 1))
    load.connect()
    print(f"  load : {load.identity}")

    import transport as _tr
    from acs550 import ACS550
    tspec = cfg.get("transport") or {}
    if tspec.get("kind") != "pmc":
        raise SystemExit(
            "this sweep assumes the PMC transport (tunnel.json transport.kind"
            " = 'pmc'). The direct topology needs the FTDI cable landed, and "
            "only one master may be on X1-29/30/31.")
    port = _tr.resolve_port(a.port, cfg)
    tp = _tr.PMCTransport(
        port, baudrate=int(tspec.get("baudrate", 115200)),
        host_watchdog_ms=int(tspec.get("host_watchdog_ms", 5000)),
        feedback_scale=float(tspec.get("feedback_scale", 295.0)))
    ref = cfg.get("drive_reference") or {}
    drive = ACS550(port, transport=tp,
                   ref1_max_fallback=ref.get("ref1_max"),
                   ref_unit=ref.get("unit", "rpm")).connect()
    print(f"  drive: reference full scale {drive.ref1_max_hz:g} "
          f"{ref.get('unit', 'rpm')}")
    return drive, load


class DriveWatch:
    """
    Feed the PMC's host watchdog, and log what the drive is actually doing.

    THE BUG THIS EXISTS FOR: the PMC ramps the fan down if it stops hearing
    from the host. This sweep commands a wind speed and then talks only to the
    Chroma for the length of a whole load ramp — tens of seconds of silence
    against a 5000 ms timeout. The fan stops, every subsequent point measures a
    stopped tunnel, and nothing in the load-side data says why: the voltages
    are simply zero.

    Ticking also buys the drive telemetry for free, so every dwell can be
    logged against the fan speed and motor current that were present, rather
    than the ones that were commanded.
    """

    def __init__(self, drive, interval=1.0):
        import threading
        self.drive = drive
        self.tp = getattr(drive, "transport", None)
        self.interval = interval
        self.rpm = self.amps = 0.0
        self.ticks = self.errors = 0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        while not self._stop.wait(self.interval):
            try:
                if self.tp is not None:
                    self.tp.keepalive_tick()
                self.rpm, self.amps = self.drive.actuals()
                self.ticks += 1
            except Exception:
                self.errors += 1

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join(timeout=2.0)
        return False


# ═══════════════════════════════════════════════════════════════════════════

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


def settle_wind(load, a, watch=None, target_rpm=None):
    """
    Wait for the wind to arrive, then for it to stop changing.

    A fixed settle is a guess about the tunnel's time constant, which has
    never been measured (TODO A3). Too short and every point is measured on
    the way somewhere — and since power goes as v³, a velocity still 5% low
    is a power 15% low. Too long and it is fourteen times wasted.

    Watching the terminal voltage instead answers the question directly:
    voltage follows rotor speed, rotor speed follows wind, so when the voltage
    stops moving the wind has arrived. Costs nothing and adapts to whatever τ
    turns out to be.

    Watching voltage ALONE is not enough, and point 1 of the first real sweep
    proved it: the fan was still accelerating through 440 rpm, the rotor was
    producing nothing yet, and 0.000 V is perfectly stable. The test happily
    declared it settled and the point was recorded as empty.

    So it waits on the DRIVE first — the fan has to be at the speed it was
    asked for — and only then on the voltage. The first point is the slow one,
    accelerating from rest; the rest are 100 rpm steps.

    Returns (volts, amps, fan_rpm) once stable, or at --settle-max.
    """
    t0 = time.monotonic()

    # ── phase 1: is the fan actually at the speed we asked for? ─────────
    if watch is not None and target_rpm:
        tol = max(a.rpm_tol_abs, a.rpm_tol_frac * target_rpm)
        while time.monotonic() - t0 < a.settle_max:
            if abs(watch.rpm - target_rpm) <= tol:
                break
            time.sleep(a.settle_poll)
        else:
            print(f"     ⚠ fan reached {watch.rpm:.0f} rpm, asked for "
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
                return v, i, (watch.rpm if watch else 0.0)
        else:
            stable = 0
        last = v
    v, i, _ = load.measure()
    return v, i, (watch.rpm if watch else 0.0)


def step_for(rpm, a):
    """
    Ladder increment at this wind speed.

    `fixed` is the protocol as stated: 10 mA everywhere. It works at the top of
    the range and cannot work at the bottom — peak current goes as v², so the
    same 10 mA that gives ~35 dwells to the peak at 1800 rpm gives THREE at
    500 rpm, and a ramp with three points either side of a maximum overshoots
    into stall before the roll-off can be confirmed. That is not a tuning
    preference; it showed up as four failed points out of fourteen.

    `v2` keeps 10 mA at --stop-rpm and scales it down as v², so every wind
    speed gets comparable resolution. It is still one rule applied identically
    to every blade, so runs stay comparable — and the rule is in the
    fingerprint, so a run under the other one cannot be mistaken for it.
    """
    if a.step_scaling == "fixed":
        return a.step_amps
    frac = (wind_from_rpm(rpm) / wind_from_rpm(a.stop_rpm)) ** 2
    return max(a.min_step_amps, a.step_amps * frac)


def estimate(a, rpms):
    """Seconds of tunnel time, so the plan can be argued with before it runs."""
    per = a.dwell + 0.35
    total = 0.0
    for rpm in rpms:
        # the roll-off typically lands near 1.4x the peak current, and the
        # peak near a third of the ceiling — from the 500/1200/1800 runs
        steps = max(3, int(ceiling_for(rpm, a) * 0.7 / step_for(rpm, a)))
        total += a.settle_min * 2 + steps * per + 2 * a.dwell
    return total


def run_sweep(a):
    rpms = list(range(int(a.start_rpm), int(a.stop_rpm) + 1, int(a.rpm_step)))
    est = estimate(a, rpms)
    print(f"\n  blade   : {a.blade}")
    print(f"  points  : {len(rpms)} — {rpms[0]} to {rpms[-1]} rpm "
          f"({wind_from_rpm(rpms[0]):.1f} to {wind_from_rpm(rpms[-1]):.1f} m/s)")
    scale = ("fixed everywhere" if a.step_scaling == "fixed" else
             f"at {a.stop_rpm:.0f} rpm, v²-scaled to "
             f"{step_for(rpms[0], a) * 1000:.1f} mA at {rpms[0]:.0f}")
    print(f"  ladder  : {a.step_amps * 1000:.0f} mA {scale}, {a.dwell:.1f} s "
          f"each,\n            stop at {a.stop_power_frac * 100:.0f}% of peak "
          f"power")
    print(f"  estimate: {est / 60:.0f} min of continuous tunnel time")

    drive, load = open_rig(a)

    rng = a.range if a.range != "auto" else ChromaLoad.pick_range(
        ceiling_for(a.stop_rpm, a), CC_FULL_SCALE)
    voff = load.volt_off(a.volt_off) if a.volt_off is not None else load.volt_off()
    print(f"  CC range {rng} (full scale {CC_FULL_SCALE[rng]:g} A), "
          f"CONF:VOLT:OFF {voff:.2f} V")

    rows, summary, dead = [], [], 0
    interlock = TurbineInterlock(drive, load, min_amps=0.0,
                                 spindown_timeout=a.spindown_timeout)
    try:
        # ── load on FIRST, then wind. Not negotiable. ────────────────────
        interlock.arm(initial_amps=max(a.unload_amps, a.step_amps * 0.5))
        print(f"\n  load ON — the fan may now be started\n")
        watch = _watch = DriveWatch(drive, interval=a.keepalive)
        _watch.__enter__()

        for n, rpm in enumerate(rpms, 1):
            print(f"  ── {n}/{len(rpms)}  fan {rpm} rpm = "
                  f"{wind_from_rpm(rpm):.2f} m/s " + "─" * 28)
            if n == 1:
                interlock.wind_up(rpm)
            else:
                interlock.set_hz(rpm)
            v, i, rpm_act = settle_wind(load, a, watch, rpm)
            print(f"     settled: {v:.3f} V at {i:.4f} A   "
                  f"(fan {rpm_act:.0f} rpm, {watch.amps:.1f} A)")

            if v <= max(voff, 0.05):
                dead += 1
                print(f"     ✗ no terminal voltage — the rotor is not turning.")
                if dead >= 2:
                    raise SystemExit(
                        f"\n  ✗ two wind speeds in a row produced nothing.\n\n"
                        f"  The fan reports {watch.rpm:.0f} rpm and "
                        f"{watch.amps:.1f} A after {watch.ticks} watchdog "
                        f"ticks\n  ({watch.errors} failed). If that is zero, "
                        f"the drive is not running: check that\n  1103/1001 "
                        f"still hand control to Modbus, and that the drive is "
                        f"not faulted.\n  Aborting rather than recording "
                        f"twelve more empty points.\n")
                load.set_mode_cc(a.unload_amps, range_=rng, verify=False)
                continue
            dead = 0

            ceiling, step = ceiling_for(rpm, a), step_for(rpm, a)
            if step != a.step_amps:
                print(f"     step {step * 1000:.1f} mA "
                      f"(v² scaling of {a.step_amps * 1000:.0f} mA)")
            try:
                r = find_peak(
                    load, max_amps=ceiling,
                    floor_amps=max(a.unload_amps, step * 0.5),
                    min_step=step, step_frac=0.0, dwell=a.dwell,
                    operate_frac=0.0,           # protocol unloads, not settles
                    v_floor=voff, range_=rng,
                    stop_power_frac=a.stop_power_frac,
                    collapse_frac=a.collapse_frac, confirm=a.confirm)
            except LoadError as e:
                print(f"     ✗ {e} — skipping this point")
                load.set_mode_cc(a.unload_amps, range_=rng, verify=False)
                continue

            flag = ("clean" if r.clean else
                    "LOAD CUT-OUT" if r.limited_by == "load-cutout" else
                    "ceiling" if r.limited_by == "ceiling" else r.limited_by)
            print(f"     peak {r.fit_watts:7.4f} W at {r.fit_amps:.3f} A "
                  f"(fit)   raw {r.power_peak_watts:.4f} W at "
                  f"{r.power_peak_amps:.3f} A   [{len(r.trace)} steps, {flag}]")

            for st in r.trace:
                rows.append([f"{st.t_unix:.3f}",
                             time.strftime("%Y-%m-%dT%H:%M:%S",
                                           time.localtime(st.t_unix)),
                             rpm, f"{wind_from_rpm(rpm):.2f}", a.blade,
                             f"{st.demand_a:.4f}",
                             "" if st.held_a is None else f"{st.held_a:.4f}",
                             f"{st.volts:.4f}", f"{st.amps:.4f}",
                             f"{st.watts:.4f}", int(st.tracking), st.note,
                             f"{watch.rpm:.0f}", f"{watch.amps:.2f}"])
            summary.append([rpm, f"{rpm_act:.0f}",
                            f"{wind_from_rpm(rpm_act or rpm):.2f}", a.blade,
                            f"{r.fit_watts:.4f}", f"{r.fit_amps:.4f}",
                            f"{r.power_peak_watts:.4f}",
                            f"{r.power_peak_amps:.4f}",
                            f"{r.power_peak_volts:.4f}",
                            f"{r.peak_amps:.4f}", r.limited_by,
                            int(r.clean), len(r.trace), r.stopped_by])

            # ── unload before the next wind step ─────────────────────────
            load.set_mode_cc(a.unload_amps, range_=rng, verify=False)
            time.sleep(a.dwell)

    except KeyboardInterrupt:
        print("\n  interrupted — winding down with the load still on")
    finally:
        try:
            _watch.__exit__()
            print(f"\n  watchdog: {watch.ticks} ticks, {watch.errors} failed")
        except Exception:
            pass
        print("  shutting down: fan first, then the load")
        ok = interlock.safe_shutdown()
        print("  " + ("clean shutdown" if ok else
                      "⚠ LOAD LEFT ON — confirm the rotor has stopped by hand"))
        try:
            drive.close()
        except Exception:
            pass
        load.close()

    return rows, summary, protocol_meta(a, load, voff, rng)


def write_out(a, rows, summary, meta):
    if not summary:
        print("\n  no points completed — nothing written")
        return 1
    stem = Path(a.out) if a.out else Path("logs") / f"sweep_{a.blade}"
    stem.parent.mkdir(parents=True, exist_ok=True)

    for path, header, data in (
            (stem.with_name(stem.name + "_points.csv"),
             ["t_unix", "t_local", "fan_rpm", "wind_mps", "blade", "demand_a",
              "held_a", "volts", "amps", "watts", "tracking", "note",
              "fan_rpm_actual", "motor_amps"], rows),
            (stem.with_name(stem.name + "_summary.csv"),
             ["fan_rpm_cmd", "fan_rpm_actual", "wind_mps", "blade",
              "p_max_fit_w", "i_at_pmax_fit_a", "p_max_raw_w", "i_at_pmax_raw_a",
              "v_at_pmax_v", "i_last_a", "limited_by", "clean", "steps",
              "stopped_by"], summary)):
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            for k, v in meta.items():
                w.writerow([f"# {k}", v])
            w.writerow(header)
            w.writerows(data)
        print(f"  wrote {path}")

    print(f"\n  {'fan rpm':>8} {'m/s':>7} {'P_fit (W)':>10} {'at A':>8} "
          f"{'P_raw (W)':>10} {'at A':>8}  stop")
    for s in summary:
        print(f"  {s[0]:>8} {s[2]:>7} {float(s[4]):>10.4f} {float(s[5]):>8.3f} "
              f"{float(s[6]):>10.4f} {float(s[7]):>8.3f}  {s[10]}")
    dirty = [s for s in summary if not s[11]]
    if dirty:
        print(f"\n  ⚠ {len(dirty)} point(s) did not stop on the power roll-off. "
              f"Their peaks may\n    be truncated — check the limited_by column "
              f"before using them.")
    print(f"\n  protocol fingerprint: {meta['protocol']}")
    print(f"  Only compare blades whose fingerprint matches this one.")
    return 0


def main():
    p = argparse.ArgumentParser(
        description="one blade, 500 to 1800 rpm, load ramped to the power "
                    "roll-off at each speed",
        epilog="Cp and lambda need rotor RPM from the DAQ; this gives P_max(v).")
    p.add_argument("--blade", required=True, help="which rotor this is")
    p.add_argument("--notes", default=None, help="material, finish, anything "
                                                 "that distinguishes it")
    p.add_argument("--config", default="data/tunnel.json")
    p.add_argument("--port", default=None,
                   help="PMC serial port; default comes from tunnel.json, then autodetect")
    p.add_argument("--out", default=None, help="path stem for the two CSVs")

    w = p.add_argument_group("the wind ladder")
    w.add_argument("--start-rpm", type=float, default=500, dest="start_rpm")
    w.add_argument("--stop-rpm", type=float, default=1800, dest="stop_rpm")
    w.add_argument("--rpm-step", type=float, default=100, dest="rpm_step")
    w.add_argument("--settle-min", type=float, default=2.0, dest="settle_min",
                   help="floor on the settle, seconds")
    w.add_argument("--settle-max", type=float, default=20.0, dest="settle_max",
                   help="ceiling on the settle, seconds")
    w.add_argument("--settle-tol", type=float, default=0.01, dest="settle_tol",
                   help="terminal voltage counts as settled when it moves less "
                        "than this fraction between polls (default 1%%)")
    w.add_argument("--settle-poll", type=float, default=0.5, dest="settle_poll")
    w.add_argument("--settle-confirm", type=int, default=3,
                   dest="settle_confirm")
    w.add_argument("--rpm-tol-frac", type=float, default=0.02,
                   dest="rpm_tol_frac",
                   help="fan counts as at speed within this fraction")
    w.add_argument("--rpm-tol-abs", type=float, default=10.0,
                   dest="rpm_tol_abs", help="...or this many rpm")
    w.add_argument("--keepalive", type=float, default=1.0,
                   help="seconds between PMC watchdog ticks. Must stay well "
                        "under tunnel.json transport.host_watchdog_ms, or the "
                        "PMC ramps the fan down mid-ramp.")

    l = p.add_argument_group("the load ladder")
    l.add_argument("--step-amps", type=float, default=0.01, dest="step_amps")
    l.add_argument("--dwell", type=float, default=1.5)
    l.add_argument("--stop-power-frac", type=float, default=0.80,
                   dest="stop_power_frac",
                   help="stop once power has fallen to this fraction of its "
                        "peak (default 0.80)")
    l.add_argument("--unload-amps", type=float, default=0.0, dest="unload_amps",
                   help="held between wind speeds. 0.0 is the protocol, and "
                        "is an open circuit to the rotor.")
    l.add_argument("--max-amps", type=float, default=0.8, dest="max_amps",
                   help="backstop ceiling AT --stop-rpm; scales as v² below "
                        "it. The roll-off should stop the ramp first.")
    l.add_argument("--step-scaling", choices=["v2", "fixed"], default="v2",
                   dest="step_scaling",
                   help="v2 (default): --step-amps at --stop-rpm, scaled down "
                        "as v² below it, so every wind speed gets comparable "
                        "resolution. fixed: the same step everywhere — the "
                        "protocol as literally stated, which cannot resolve "
                        "the peak below about 900 rpm.")
    l.add_argument("--min-step-amps", type=float, default=0.002,
                   dest="min_step_amps",
                   help="floor under the v² scaling (default 2 mA)")
    l.add_argument("--range", choices=["auto", "low", "mid", "high"],
                   default="auto")
    l.add_argument("--volt-off", type=float, default=0.5, dest="volt_off")
    l.add_argument("--collapse-frac", type=float, default=0.70,
                   dest="collapse_frac")
    l.add_argument("--confirm", type=int, default=2)
    l.add_argument("--spindown-timeout", type=float, default=180,
                   dest="spindown_timeout")

    s = p.add_argument_group("simulator")
    s.add_argument("--simulate", action="store_true")
    s.add_argument("--sim-watts", type=float, default=3.8, dest="sim_watts")
    s.add_argument("--sim-volts", type=float, default=10.9, dest="sim_volts")

    a = p.parse_args()
    # protocol_meta reads these names off the namespace
    a.min_step, a.step_frac, a.percent = a.step_amps, 0.0, a.stop_power_frac * 100
    a.floor_amps, a.fan_rpm = a.unload_amps, a.start_rpm

    rows, summary, meta = run_sweep(a)
    return write_out(a, rows, summary, meta)


if __name__ == "__main__":
    sys.exit(main())
