#!/usr/bin/env python3
"""
load_ramp.py — prove the Chroma actually sinks current, by ramping it.

    python src/load_ramp.py --plan-only --peak-amps 5 --percent 80
    python src/load_ramp.py --peak-amps 5 --percent 80 --steps 9

═══════════════════════════════════════════════════════════════════════════
WHAT THIS IS FOR
═══════════════════════════════════════════════════════════════════════════
`probe_load.py --verify` proves the instrument *parses* every command the
driver sends. It cannot prove more than that, because it runs with the load
OFF — nothing it does draws a single milliamp.

The question "how do we know it's working" only has one honest answer, and it
is this: put a source on the terminals, command a current, and check that the
current the instrument reports back is the current you asked for. This does
that, as a ramp from 0 to a percentage of a peak you name.

Every step is checked three ways:

  · **the error queue**       — did the instrument reject the command?
  · **the setpoint readback** — is it holding the number you sent? An
                                out-of-range demand is refused, and the
                                setpoint then keeps its PREVIOUS value. The
                                queue tells you something was rejected; only
                                the readback tells you what it is holding now.
  · **the measurement**       — is it actually sinking that current?

Only the third one is proof. The first two are how you find out *why* when the
third fails.

═══════════════════════════════════════════════════════════════════════════
BENCH ONLY — NOT FOR THE TURBINE
═══════════════════════════════════════════════════════════════════════════
Run this against a bench DC supply, not against the turbine.

This script starts the ramp at zero amps, which for a spinning turbine is
electrically the same as open circuit — the exact condition `TurbineInterlock`
exists to prevent — and it switches the load OFF when it finishes. It also has
no rotor-speed feedback, so it cannot tell a good operating point from a stall.

The turbine path is `turbine.CpSweep`, which sweeps resistance rather than
current, holds the interlock throughout, and watches RPM. Use that one there.

═══════════════════════════════════════════════════════════════════════════
"80% OF PEAK" — OF WHAT?
═══════════════════════════════════════════════════════════════════════════
The 63004-150-60 has three ratings and they are corners of an envelope, not a
box you can sit anywhere inside:

    150 V   ·   60 A   ·   400 W

80% of the current rating is 48 A. That is comfortably inside the current
rating and roughly six times outside the power rating at any voltage a small
turbine produces. 80% of the power rating is 320 W, which is CP mode, which
this package deliberately does not expose — commanding constant power from a
source whose available power you are trying to measure is a positive feedback
loop straight into stall.

The percentage that means something is a percentage of what the SOURCE can
deliver. For the turbine that number is not known yet: `turbine.rpm_source`
and `turbine.v_open_circuit_at_15mps` are both still null in tunnel.json, and
TODO B3 is where they get measured.

So `--peak-amps` is required and has no default. Name the peak, and this
script will hold you to the envelope around it.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chroma_load import (CC_FULL_SCALE, ChromaLoad, LoadError, RATINGS,
                         build_transport)
from peak_finder import PeakFinderError, find_peak

REPO = Path(__file__).resolve().parent.parent


def load_spec(config_path):
    """Pull the `load` block out of tunnel.json."""
    import json
    p = Path(config_path)
    if not p.is_absolute() and not p.exists():
        # Same papercut as run.py's --config: the file lives in data/ and the
        # command gets run from wherever. Look there before giving up.
        for cand in (REPO / config_path, REPO / "data" / Path(config_path).name):
            if cand.exists():
                p = cand
                break
    if not p.exists():
        raise SystemExit(f"no config at {config_path}")
    cfg = json.loads(p.read_text())
    spec = cfg.get("load")
    if not spec:
        raise SystemExit(
            f"{p} has no `load` block. Run `python src/probe_load.py --verify` "
            f"and paste what it prints.")
    return p, spec


def ladder(peak, pct_start, pct_stop, steps):
    """Setpoints from pct_start% to pct_stop% of peak, endpoints included."""
    if steps < 2:
        raise SystemExit("--steps must be at least 2")
    span = (pct_stop - pct_start) / (steps - 1)
    return [peak * (pct_start + i * span) / 100.0 for i in range(steps)]


def resolve_range(a, peak_demand):
    """`--range auto` picks the smallest range that covers the top of the ramp."""
    if a.range != "auto":
        return a.range
    try:
        return ChromaLoad.pick_range(peak_demand, CC_FULL_SCALE)
    except LoadError as e:
        raise SystemExit(f"  ✗ {e}")


def envelope_note(amps, volts):
    """Which rating, if any, this point is outside."""
    watts = amps * volts
    bad = []
    if amps > RATINGS["amps"]:
        bad.append(f"{amps:.2f} A > {RATINGS['amps']:.0f} A rating")
    if volts > RATINGS["volts"]:
        bad.append(f"{volts:.1f} V > {RATINGS['volts']:.0f} V rating")
    if watts > RATINGS["watts"]:
        bad.append(f"{watts:.1f} W > {RATINGS['watts']:.0f} W rating")
    return "; ".join(bad)


# ═══════════════════════════════════════════════════════════════════════════

def plan_only(a, points):
    print(f"\n  ladder — {a.pct_start:.0f}% to {a.percent:.0f}% of "
          f"{a.peak_amps:g} A, {a.steps} steps\n")
    print(f"  {'%':>6}  {'A demand':>9}  {'W at ' + format(a.v_nominal, '.1f') + ' V':>14}")
    print(f"  {'-'*6}  {'-'*9}  {'-'*14}")
    worst = ""
    for i, amps in enumerate(points):
        pct = a.pct_start + i * (a.percent - a.pct_start) / (a.steps - 1)
        w = amps * a.v_nominal
        flag = envelope_note(amps, a.v_nominal)
        print(f"  {pct:6.1f}  {amps:9.3f}  {w:14.1f}"
              + (f"   ← {flag}" if flag else ""))
        worst = flag or worst

    rng = resolve_range(a, max(points))
    limit = CC_FULL_SCALE[rng]
    print(f"\n  active range: CC{rng[0].upper()} — full scale {limit:g} A "
          f"(of {', '.join(f'{k} {v:g} A' for k, v in CC_FULL_SCALE.items())})")
    if max(points) > limit:
        print(f"  ✗ the top of this ladder ({max(points):.3f} A) is above the "
              f"{rng} range.\n    The instrument will REFUSE it — "
              f"2,\"Data Range Error\" — and keep the previous\n    setpoint. "
              f"Use a larger --range.")
    if worst:
        print(f"\n  ✗ this ladder leaves the rated envelope. Lower --peak-amps "
              f"or --percent.")
    else:
        print(f"  ✓ inside the rated envelope at {a.v_nominal:.1f} V")
    print(f"\n  Nothing was connected or energised. Drop --plan-only to run it.\n")


def run(a, points):
    cfg_path, spec = load_spec(a.config)
    print(f"\n  config: {cfg_path}")

    try:
        load = ChromaLoad(build_transport(spec), channel=spec.get("channel", 1))
    except ImportError as e:
        raise SystemExit(
            f"\n  {e}\n\n  This machine cannot reach a USB-TMC instrument yet. "
            f"macOS has no\n  kernel usbtmc driver, so VISA is the only route:"
            f"\n\n      pip install pyvisa pyvisa-py pyusb\n")

    try:
        load.connect()
    except ImportError as e:
        raise SystemExit(
            f"\n  {e}\n\n      pip install pyvisa pyvisa-py pyusb\n")

    print(f"  instrument: {load.identity}")
    print(f"  mode before: {load.read_mode()}   load: "
          f"{load.query('LOAD?').strip()}")

    a.range = resolve_range(a, max(points))
    print(f"  CC range: {a.range} — full scale {CC_FULL_SCALE[a.range]:g} A")

    if a.v_floor is None:
        # The instrument stops sinking below CONF:VOLT:OFF regardless of what
        # we command, so a floor under it would be testing the load's ability
        # to do nothing.
        voff = load.volt_off()
        a.v_floor = voff if voff is not None else 1.0
        print(f"  v-floor: {a.v_floor:.2f} V (the instrument's own "
              f"CONF:VOLT:OFF)")

    # ── 1. is there a source on the terminals at all? ───────────────────
    # Before the try/finally, deliberately: the load is already off here, so
    # there is nothing to unwind, and an unwind message printed ahead of the
    # reason for it reads like the ramp ran and failed.
    load.off()
    time.sleep(0.3)
    v_oc, i_oc, _ = load.measure()
    print(f"\n  open circuit (load OFF): {v_oc:.3f} V, {i_oc:.4f} A")
    if v_oc < a.v_floor:
        load.close()
        raise SystemExit(
            f"\n  ✗ {v_oc:.3f} V at the terminals with the load off.\n\n"
            f"  There is no source connected, or the polarity is reversed, "
            f"or the\n  supply's output is off. An electronic load is a "
            f"sink — it cannot\n  demonstrate anything into an open "
            f"circuit, and every step below\n  would read 0.000 A and "
            f"tell you nothing.\n\n  Put a bench supply on it (set to "
            f"{max(a.v_nominal, 5):.0f} V, current limit at least "
            f"{max(points) * 1.2:.2f} A) and run this again.\n")

    rows, aborted = [], None
    try:
        # ── 2. protection, such as it is ────────────────────────────────
        prot = load.protection(
            max_volts=min(a.max_volts, RATINGS["volts"]),
            max_amps=min(a.peak_amps * 1.25, RATINGS["amps"]),
            max_watts=min(a.max_watts, RATINGS["watts"]))
        if prot["unsupported"]:
            print(f"  protection: NOT AVAILABLE on this firmware "
                  f"({', '.join(prot['unsupported'])} rejected).")
            print(f"              The {a.max_watts:.0f} W ceiling below is "
                  f"enforced by this script, not by the\n"
                  f"              instrument. If it stops, nothing else is "
                  f"watching.")
        else:
            print(f"  protection: {prot['applied']}")

        # ── 3. start at zero, then walk up ───────────────────────────────
        load.set_mode_cc(0.0, range_=a.range)
        load.on()
        time.sleep(0.3)
        print(f"\n  load ON in CC{a.range[0].upper()} at 0.000 A\n")

        hdr = (f"  {'%':>6} {'demand':>8} {'held':>8} {'volts':>8} "
               f"{'amps':>8} {'watts':>8}  {'':>4}")
        print(hdr)
        print(f"  {'-'*6} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}  {'-'*4}")

        for i, amps in enumerate(points):
            pct = a.pct_start + i * (a.percent - a.pct_start) / (a.steps - 1)

            # Predict against the last measured voltage before committing.
            v_last = rows[-1]["volts"] if rows else v_oc
            over = envelope_note(amps, v_last)
            if over:
                aborted = f"step {pct:.0f}% would leave the envelope: {over}"
                break

            load.set_mode_cc(amps, range_=a.range)     # raises on clamp
            time.sleep(a.dwell)
            v, i_meas, w = load.measure()
            held = load.read_setpoint("curr")

            tol = max(a.tol_abs, a.tol_frac * amps)
            tracking = abs(i_meas - amps) <= tol
            mark = "ok" if tracking else "OFF"

            rows.append({"percent": round(pct, 2), "demand_a": round(amps, 4),
                         "held_a": held, "volts": round(v, 4),
                         "amps": round(i_meas, 4), "watts": round(w, 4),
                         "tracking": tracking})

            print(f"  {pct:6.1f} {amps:8.3f} "
                  f"{(f'{held:8.3f}' if held is not None else '       ?')} "
                  f"{v:8.3f} {i_meas:8.3f} {w:8.2f}  {mark:>4}")

            if v < a.v_floor and amps > 0:
                aborted = (f"terminal voltage collapsed to {v:.3f} V — the "
                           f"source cannot hold up at {amps:.3f} A")
                break
            if w > a.max_watts:
                aborted = f"{w:.1f} W exceeds the {a.max_watts:.1f} W limit"
                break

    except LoadError as e:
        aborted = str(e)
    finally:
        # ── 4. unwind, whatever happened ─────────────────────────────────
        try:
            print("\n  ramping back to zero...")
            for amps in reversed([p for p in points[:len(rows)] if p > 0]):
                load.set_mode_cc(amps * 0.5, range_=a.range, verify=False)
                time.sleep(0.1)
            load.set_mode_cc(0.0, range_=a.range, verify=False)
            time.sleep(0.2)
            load.off()
            print("  load OFF")
        except Exception as e:
            print(f"  ✗ could not switch the load off cleanly: {e}\n"
                  f"    Do it by hand at the front panel.")
        load.close()

    return rows, aborted


def wind_from_rpm(fan_rpm):
    """Drive-side calibration. The ACS550 commands rpm, not Hz."""
    return 0.02132 * fan_rpm - 0.424


def protocol_meta(a, load, v_floor, rng):
    """
    Everything a later reader needs to know whether two runs can be compared.

    The `protocol` field is a hash of exactly the settings that change what a
    curve MEANS — step size, dwell, cut-out voltage, range, floor, operating
    fraction. Two blades measured under different settings are not two data
    points, and across a campaign of many rotors that is very easy to do by
    accident and very hard to notice afterwards. If the fingerprints differ,
    the runs differ.

    Deliberately excluded: --max-amps (a ceiling, not a method), --csv,
    --wait-for-source, --wind-seconds. Those change how far a run got or how
    it was scheduled, not what its numbers mean.
    """
    import hashlib
    shape = (f"scaling={getattr(a, 'step_scaling', 'fixed')};"
             f"step={a.min_step:.5f};frac={a.step_frac:.4f};"
             f"dwell={a.dwell:.2f};voff={v_floor:.3f};range={rng};"
             f"floor={a.floor_amps:.5f};operate={a.percent:.1f};"
             f"collapse={a.collapse_frac:.3f};confirm={a.confirm}")
    return {
        "blade": a.blade or "UNLABELLED",
        "notes": a.notes or "",
        "fan_rpm": f"{a.fan_rpm:.0f}",
        "wind_mps": f"{wind_from_rpm(a.fan_rpm):.2f}",
        "instrument": getattr(load, "identity", "?"),
        "protocol": hashlib.sha256(shape.encode()).hexdigest()[:12],
        "protocol_detail": shape,
        "clock": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "clock_unix": f"{time.time():.3f}",
        "_clock_note": ("host wall clock at run start. Every row carries t_unix "
                        "so a DAQ record can be joined to it — check the two "
                        "machines agree to better than a dwell before trusting "
                        "the join."),
    }


def open_load(a):
    """The instrument, or the simulator standing in for it."""
    if a.simulate:
        from load_sim import SimulatedLoad, SimulatedTurbine, wind_mps
        turb = SimulatedTurbine(peak_watts=a.sim_watts,
                                volts_at_peak=a.sim_volts)
        turb.fan_rpm = a.fan_rpm
        load = SimulatedLoad(turb).connect()
        print(f"\n  SIMULATED — no instrument, no rotor.")
        print(f"  fan {a.fan_rpm:.0f} rpm = {wind_mps(a.fan_rpm):.2f} m/s   "
              f"open circuit {turb.v_oc:.2f} V   stall at "
              f"{turb.i_stall:.4f} A")
        return load

    _, spec = load_spec(a.config)
    try:
        load = ChromaLoad(build_transport(spec), channel=spec.get("channel", 1))
        load.connect()
    except ImportError as e:
        raise SystemExit(f"\n  {e}\n\n      pip install pyvisa pyvisa-py "
                         f"pyusb\n")
    print(f"\n  instrument: {load.identity}")
    return load


def mode_peak(a):
    """
    Walk the demand up until the rotor lets go, then settle at 80% of it.

    One wind speed. The outer loop over fan rpm belongs with the drive and the
    interlock, not here — see the module docstring.
    """
    load = open_load(a)

    rng = a.range if a.range != "auto" else \
        ChromaLoad.pick_range(a.max_amps, CC_FULL_SCALE)
    print(f"  CC range: {rng} — full scale {CC_FULL_SCALE[rng]:g} A")

    voff = load.volt_off()
    if a.volt_off is not None and abs((voff or 0) - a.volt_off) > 1e-6:
        voff = load.volt_off(a.volt_off)
        print(f"  CONF:VOLT:OFF set to {voff:.2f} V")
    else:
        print(f"  CONF:VOLT:OFF is {voff:.2f} V — below this the load stops "
              f"sinking")
    v_floor = a.v_floor if a.v_floor is not None else (voff or 1.0)

    # ── load ON at the floor, FIRST ──────────────────────────────────────
    # An earlier version switched the load off here to take a clean
    # open-circuit reading. On a rig where the load is already wired to the
    # turbine that is the runaway condition, and it would have fired the
    # moment the rotor was turning. Nothing in peak mode switches the load
    # off any more; see --release for the one deliberate exception.
    load.set_mode_cc(a.floor_amps, range_=rng)
    load.on()
    time.sleep(0.5)
    v_now, i_now, _ = load.measure()
    print(f"  load ON at the {a.floor_amps:.4f} A floor: {v_now:.3f} V, "
          f"{i_now:.4f} A")

    # ── wait for the source, rather than refusing before the wind is up ──
    if v_now <= v_floor and a.wait_for_source:
        print(f"\n  waiting up to {a.wait_for_source:.0f} s for the source. "
              f"The load is ON and holding\n  the floor, so bring the fan up "
              f"NOW — that is the correct order.")
        t0 = time.monotonic()
        while time.monotonic() - t0 < a.wait_for_source:
            time.sleep(1.0)
            v_now, i_now, _ = load.measure()
            print(f"\r    {time.monotonic() - t0:5.0f}s  {v_now:7.3f} V  "
                  f"{i_now:7.4f} A", end="", flush=True)
            if v_now > v_floor:
                print(f"\n  source is up at {v_now:.3f} V — starting the ramp")
                break
        else:
            print()

    if v_now <= v_floor:
        # Deliberately NOT switching the load off: if the rotor is turning,
        # off is worse than a pointless energised load.
        raise SystemExit(
            f"\n  ✗ {v_now:.3f} V at the terminals, at or below the "
            f"{v_floor:.2f} V floor.\n\n"
            f"  If the source is the TURBINE, this means there is no wind — the "
            f"rotor\n  makes nothing at rest, and the reading is correct. Bring "
            f"the fan up with\n  the load already ON, or re-run with "
            f"--wait-for-source 120 and raise the\n  wind while it waits.\n\n"
            f"  If the source is a BENCH SUPPLY, check polarity and that its "
            f"output is on.\n\n"
            f"  Either way the load is left ON and holding the floor, not "
            f"switched off.\n")

    # ── will this ramp finish before the wind stops? ────────────────────
    n_steps = int((a.max_amps - a.floor_amps) /
                  (a.min_step if a.step_frac <= 0 else a.min_step)) + 1
    per_step = a.dwell + 0.35            # SCPI round trips, measured
    est = n_steps * per_step + a.dwell * 2
    print(f"  plan: up to {n_steps} steps of {a.min_step * 1000:.0f} mA at "
          f"{a.dwell:.1f} s  ≈ {est:.0f} s of wind")
    if a.wind_seconds and est > a.wind_seconds:
        raise SystemExit(
            f"\n  ✗ the ramp needs ~{est:.0f} s but the wind lasts "
            f"{a.wind_seconds:.0f} s.\n\n"
            f"  A ramp that outruns the fan records the SPIN-DOWN as a stall: "
            f"voltage\n  collapses, current stops tracking, and it looks "
            f"exactly like the rotor\n  letting go. Raise the jog duration to "
            f"{est * 1.2:.0f} s, or lower --max-amps.\n")

    hdr = (f"\n  {'demand':>9} {'held':>9} {'volts':>8} {'amps':>9} "
           f"{'watts':>8}  note")
    print(hdr)
    print(f"  {'-'*9} {'-'*9} {'-'*8} {'-'*9} {'-'*8}  {'-'*16}")

    def show(st):
        held = f"{st.held_a:9.4f}" if st.held_a is not None else "        ?"
        print(f"  {st.demand_a:9.4f} {held} {st.volts:8.3f} {st.amps:9.4f} "
              f"{st.watts:8.3f}  {st.note or ('ok' if st.tracking else 'OFF')}")

    result, err = None, None
    try:
        result = find_peak(
            load, max_amps=a.max_amps, floor_amps=a.floor_amps,
            min_step=a.min_step, step_frac=a.step_frac, dwell=a.dwell,
            operate_frac=a.percent / 100.0, v_floor=v_floor,
            max_watts=a.max_watts, range_=rng, tol_frac=a.tol_frac,
            tol_abs=a.tol_abs, collapse_frac=a.collapse_frac,
            confirm=a.confirm, on_step=show)
    except (PeakFinderError, LoadError) as e:
        err = str(e)
    finally:
        try:
            load.set_mode_cc(a.floor_amps, range_=rng, verify=False)
            print(f"\n  held at the {a.floor_amps:.4f} A floor — NOT zero. "
                  f"The rotor stays loaded.")
            if a.release:
                load.off()
                print(f"  load OFF (--release). Only correct with the rotor "
                      f"stopped.")
        except Exception as e:
            print(f"  ✗ could not return to the floor: {e}")
        load.close()

    if err:
        print(f"\n  ✗ {err}")
        return 1
    if not result:
        return 1

    print()
    print(result.summary())

    if a.csv:
        out = Path(a.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        meta = protocol_meta(a, load, v_floor, rng)
        with out.open("w", newline="") as f:
            w = csv.writer(f)
            for k, v in meta.items():                 # '#' rows, ignored by
                w.writerow([f"# {k}", v])             # pandas with comment='#'
            w.writerow(["fan_rpm", "wind_mps", "blade", "demand_a", "held_a",
                        "volts", "amps", "watts", "tracking", "note"])
            for st in result.trace:
                w.writerow([a.fan_rpm, f"{wind_from_rpm(a.fan_rpm):.2f}",
                            a.blade or "", f"{st.demand_a:.4f}",
                            "" if st.held_a is None else f"{st.held_a:.4f}",
                            f"{st.volts:.4f}", f"{st.amps:.4f}",
                            f"{st.watts:.4f}", int(st.tracking), st.note])
        print(f"\n  wrote {out} — {len(result.trace)} rows")
        print(f"  protocol fingerprint: {meta['protocol']}  "
              f"— runs must match this to be comparable")

    if not result.found:
        print(f"\n  ⚠ No rollover. {result.stopped_by}\n"
              f"    Raise --max-amps, or accept this as a lower bound.")
        return 1
    print(f"\n  ✓ threshold found and the rotor recovered under load.")
    return 0


def report(a, rows, aborted):
    if aborted:
        print(f"\n  ✗ ABORTED — {aborted}")

    if not rows:
        print("  no steps completed.\n")
        return 1

    tracked = [r for r in rows if r["tracking"]]
    loaded = [r for r in rows if r["demand_a"] > 0]
    worst = max((abs(r["amps"] - r["demand_a"]) for r in loaded), default=0.0)

    print(f"\n  {len(tracked)}/{len(rows)} steps tracked within "
          f"{a.tol_frac * 100:.0f}% / {a.tol_abs:.3f} A")
    print(f"  worst error: {worst:.4f} A")
    if loaded:
        print(f"  peak: {max(r['amps'] for r in loaded):.3f} A at "
              f"{max(r['watts'] for r in loaded):.2f} W")

    if a.csv:
        out = Path(a.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"  wrote {out}")

    ok = not aborted and len(tracked) == len(rows)
    if ok:
        print(f"\n  ✓ The load sinks the current it is told to, from "
              f"{a.pct_start:.0f}% to {a.percent:.0f}% of {a.peak_amps:g} A.\n"
              f"    That is the proof `probe_load.py --verify` could not give "
              f"you.\n")
    else:
        print(f"\n  ✗ Commanded and measured current disagree. Before "
              f"suspecting the driver:\n"
              f"    · is the demand above the active range? "
              f"(--range {'high' if a.range == 'low' else 'low'})\n"
              f"    · is the SOURCE current-limiting? watch the volts column "
              f"sag\n"
              f"    · are the VSense leads landed and the right way round? in "
              f"CR mode the\n"
              f"      load REGULATES on sense, so bad sense controls to the "
              f"wrong thing\n")
    return 0 if ok else 1


def main():
    p = argparse.ArgumentParser(
        description="ramp the Chroma from 0 to a percentage of a named peak, "
                    "and check it actually sinks what it is told to",
        epilog="BENCH ONLY — see the module docstring. The turbine path is "
               "turbine.CpSweep.")
    p.add_argument("--config", default="data/tunnel.json")
    p.add_argument("--peak-amps", type=float, dest="peak_amps",
                   help="the peak the percentage is OF, in amps. Required — "
                        "see the module docstring for why there is no default.")
    p.add_argument("--percent", type=float, default=80.0,
                   help="top of the ramp, %% of peak (default 80)")
    p.add_argument("--pct-start", type=float, default=0.0, dest="pct_start")
    p.add_argument("--steps", type=int, default=9)
    p.add_argument("--dwell", type=float, default=1.5,
                   help="seconds at each step before measuring (default 1.5, "
                        "the protocol's settling time)")
    p.add_argument("--range", choices=["auto", "low", "mid", "high"],
                   default="auto",
                   help="CC range — low 2 A, mid 6 A, high 60 A, measured off "
                        "this instrument. `auto` takes the smallest one that "
                        "covers the top of the ramp, which is what you want: "
                        "resolution spent on the 60 A range is resolution "
                        "lost from Cp.")
    p.add_argument("--v-nominal", type=float, default=24.0, dest="v_nominal",
                   help="source voltage, for the --plan-only power estimate")
    p.add_argument("--v-floor", type=float, default=None, dest="v_floor",
                   help="abort if the terminals fall below this. Defaults to "
                        "the instrument's own CONF:VOLT:OFF, below which it "
                        "stops sinking anyway.")
    p.add_argument("--max-watts", type=float, default=RATINGS["watts"] * 0.8,
                   dest="max_watts")
    p.add_argument("--max-volts", type=float, default=RATINGS["volts"],
                   dest="max_volts")
    p.add_argument("--tol-frac", type=float, default=0.03, dest="tol_frac")
    p.add_argument("--tol-abs", type=float, default=0.02, dest="tol_abs")
    p.add_argument("--csv", default=None, help="write the steps here")

    g = p.add_argument_group(
        "peak mode — walk the demand up until the rotor lets go")
    g.add_argument("--mode", choices=["peak", "ladder"], default="peak",
                   help="peak: find the stall threshold, then settle at "
                        "--percent of it (the protocol). ladder: a fixed "
                        "percentage ramp of a peak you already know.")
    g.add_argument("--fan-rpm", type=float, default=1800.0, dest="fan_rpm",
                   help="the drive's speed reference for THIS point. Recorded "
                        "in the log and used by the simulator. The drive "
                        "commands rpm, not Hz — 500..1800 rpm is 10.2..38.0 m/s")
    g.add_argument("--max-amps", type=float, default=None, dest="max_amps",
                   help="hard ceiling on the ramp. Required in peak mode — it "
                        "is the backstop for a source that never rolls over.")
    g.add_argument("--floor-amps", type=float, default=0.005,
                   dest="floor_amps",
                   help="the light load held between phases. Never zero: zero "
                        "amps in CC is an open circuit to a spinning rotor.")
    g.add_argument("--min-step", type=float, default=0.01, dest="min_step",
                   help="demand increment (default 10 mA, the protocol's step). "
                        "With --step-frac 0 the ladder is exact multiples of "
                        "this: 0.01, 0.02, 0.03... The instrument resolves "
                        "0.1 mA, so finer is available where it is worth it.")
    g.add_argument("--step-frac", type=float, default=0.0, dest="step_frac",
                   help="0 (default) = a fixed --min-step ladder. Above 0, the "
                        "step becomes that fraction of the largest current seen "
                        "instead, giving equal RELATIVE resolution at every "
                        "wind speed rather than equal absolute.")
    g.add_argument("--collapse-frac", type=float, default=0.70,
                   dest="collapse_frac",
                   help="measured current below this fraction of the running "
                        "maximum counts as a collapse")
    g.add_argument("--confirm", type=int, default=2,
                   help="consecutive bad dwells before believing it. One is a "
                        "transient; two in a row is the rotor.")
    g.add_argument("--volt-off", type=float, default=None, dest="volt_off",
                   help="set CONF:VOLT:OFF for this run. The shipped 3.00 V "
                        "will silently delete the bottom of a wind sweep.")
    g.add_argument("--wind-seconds", type=float, default=None,
                   dest="wind_seconds",
                   help="how long the fan will actually be running, e.g. the "
                        "--seconds you gave jog. The ramp is checked against "
                        "it up front and refuses to start if it cannot finish "
                        "in time — a ramp that outruns the wind reads the "
                        "spin-down as a stall.")
    g.add_argument("--wait-for-source", type=float, default=0.0,
                   dest="wait_for_source",
                   help="seconds to wait for terminal voltage to appear before "
                        "starting. Lets you start the script with the load "
                        "already ON at the floor and THEN raise the wind — "
                        "which is the order the interlock requires.")
    g.add_argument("--release", action="store_true",
                   help="switch the load OFF at the end. ONLY with the rotor "
                        "stopped — otherwise it is the runaway condition.")

    camp = p.add_argument_group(
        "campaign — many blades, compared against each other")
    camp.add_argument("--blade", default=None,
                      help="which rotor this run is of. REQUIRED for a real "
                           "run: a curve with no blade name on it is worth "
                           "nothing three months later, and a campaign that "
                           "compares blades cannot afford an unlabelled one.")
    camp.add_argument("--notes", default=None,
                      help="surface finish, print settings, anything that "
                           "distinguishes this rotor from the last one")

    sim = p.add_argument_group("simulator — prove the detector with no rotor")
    sim.add_argument("--simulate", action="store_true",
                     help="run against a modelled turbine instead of hardware")
    sim.add_argument("--sim-watts", type=float, default=4.0, dest="sim_watts",
                     help="peak electrical watts at --sim-ref-rpm (default 4)")
    sim.add_argument("--sim-volts", type=float, default=12.0, dest="sim_volts",
                     help="terminal volts at that peak. ASSUMED — one "
                          "open-circuit reading replaces it (default 12)")
    p.add_argument("--plan-only", action="store_true", dest="plan_only",
                   help="print the ladder and the envelope check, connect to "
                        "nothing")
    a = p.parse_args()

    if a.mode == "peak":
        if a.max_amps is None:
            raise SystemExit(
                "\n  --max-amps is required in peak mode. It is the ceiling the "
                "ramp stops at\n  if the rotor never lets go, so it has to be a "
                "number you chose.\n\n  Scaling 4 W at 1800 rpm: the stall "
                "threshold is near 0.5 A there and\n  goes as v², so ~0.04 A at "
                "500 rpm. Give it maybe 1.5x headroom.\n\n      --fan-rpm 1800 "
                "--max-amps 0.8\n      --fan-rpm  500 --max-amps 0.08\n")
        if a.percent <= 0 or a.percent > 100:
            raise SystemExit("--percent must be in (0, 100]")
        if not a.simulate and not a.blade:
            raise SystemExit(
                "\n  --blade is required. You test many rotors and will test "
                "more; a curve\n  with no rotor name attached is not a "
                "measurement, it is a number.\n\n"
                "      --blade v2-smooth --notes 'PLA, 0.1mm layers, sanded'\n")
        return mode_peak(a)

    if a.peak_amps is None:
        print(__doc__.split('"80% OF PEAK" — OF WHAT?')[1].split("═══")[0]
              if '"80% OF PEAK"' in __doc__ else "")
        print("  --peak-amps is required. Pick the one you mean:\n")
        print(f"    --peak-amps {RATINGS['amps']:g}      "
              f"the instrument's current rating — 80% is "
              f"{RATINGS['amps'] * 0.8:.0f} A, which is\n"
              f"                        outside the {RATINGS['watts']:.0f} W "
              f"envelope above {RATINGS['watts'] / (RATINGS['amps'] * 0.8):.1f} V\n")
        print(f"    --peak-amps {CC_FULL_SCALE['low']:g}       "
              f"the low range's full scale — a sane bench-supply proof\n")
        print(f"    --peak-amps <turbine>   what the rotor can actually "
              f"deliver. NOT KNOWN YET —\n"
              f"                        tunnel.json has "
              f"turbine.v_open_circuit_at_15mps = null.\n"
              f"                        TODO B3 is where that gets measured.\n")
        return 2

    if a.peak_amps <= 0:
        raise SystemExit("--peak-amps must be positive")

    points = ladder(a.peak_amps, a.pct_start, a.percent, a.steps)

    if a.plan_only:
        plan_only(a, points)
        return 0

    rows, aborted = run(a, points)
    return report(a, rows, aborted)


if __name__ == "__main__":
    sys.exit(main())
