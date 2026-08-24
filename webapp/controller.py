"""
controller.py — the single owner of the drive.

═══════════════════════════════════════════════════════════════════════════
WHY THIS EXISTS AS A SEPARATE LAYER
═══════════════════════════════════════════════════════════════════════════
RS-485 is half duplex with exactly one master. A Flask app is the opposite of
that by default: every request runs in its own thread, and if each one opened
the port or issued its own transaction, frames would collide on the wire and
you would get CRC errors that look exactly like a wiring fault.

So the drive is owned by **one** object with **one** background poll thread.
Every HTTP request goes through it. Nothing else in the web app is allowed to
touch the serial port.

═══════════════════════════════════════════════════════════════════════════
SAFETY PROPERTIES THIS LAYER GUARANTEES
═══════════════════════════════════════════════════════════════════════════
A browser is a worse place to control a 15 HP fan from than a terminal: tabs
get closed, laptops sleep, someone opens the page on their phone and forgets.
So the enforcement lives here, server-side, never in the UI:

  · **Soft frequency limit** is applied to every setpoint, whatever asked.
  · **A profile run cannot be started while another is running.**
  · **Estop** issues a coast stop and latches until explicitly cleared.
  · **The drive's own comm watchdog is never disabled**, and the poll thread
    is what feeds it. If this process dies, the fan stops on its own — which
    is the entire reason a web UI is acceptable here at all.

The UI can be wrong, disconnected, or malicious. The drive still stops.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np

import contextlib
import io

import characterize as _char
import feedforward as _ff
import gusts
import preflight as _pre
from acs550 import ACS550, DriveError
from calibration import Calibration
from calibration import TO_MPS
from config import TunnelConfig
from player import ProfileAborted, ProfilePlayer
from simulator import SimulatedACS550
from velocity_loop import VelocityController, suggest_gains
from velocity_source import (ManualSource, SimulatedSource, StaleReading,
                             build_source)

# Anchored on the repo, NOT the process CWD. windtunnel.service sets
# WorkingDirectory=.../webapp and the README says `cd webapp && python app.py`,
# so a bare relative "logs" put profiles, characterize and stepped sweeps in
# webapp/logs/ while the blade library read repo/logs/ — two divergent trees,
# and the Logs tab showed only one of them.
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


class _SweepStopped(RuntimeError):
    """Raised inside a ramp when the operator stops it or E-stop latches."""


class TunnelController:
    """Owns the drive. Everything the web app does goes through here."""

    def __init__(self, port, baud=19200, parity="N", unit=1,
                 dry_run=False, config_path="tunnel.json", poll_hz=4.0):
        self.cfg = TunnelConfig.load(config_path)
        self.dry_run = dry_run
        self.poll_period = 1.0 / poll_hz

        ref = self.cfg.get("drive_reference") or {}
        self.ref_unit = ref.get("unit", "rpm")
        self.ref1_max = float(ref.get("ref1_max") or 2435.0)

        if dry_run:
            # max_freq is the span the drive's ramp generator traverses in
            # `accel` seconds. It defaulted to 60 — correct when the reference
            # was Hz, and 6 rpm/s once it became speed, which is 100 s to reach
            # 600 rpm. Every dry run since the rpm migration ramped at a
            # fortieth of the real rate.
            self.drive = SimulatedACS550(
                ref1_max_hz=self.ref1_max, max_freq=self.ref1_max,
                tau_up=self.cfg.tau or 0.8,
                tau_down=self.cfg.get("tau_down") or (self.cfg.tau or 0.8),
                dead_time=self.cfg.get("dead_time", 0.15))
        else:
            # Honour tunnel.json. The dashboard used to build a raw-Modbus
            # ACS550 unconditionally, which on this rig means speaking Modbus
            # at a PMC that answers ASCII lines — it would simply never
            # connect, and the error would point at the cable.
            tspec = self.cfg.get("transport") or {"kind": "direct"}
            if tspec.get("kind") == "pmc":
                import transport as _tr
                tp = _tr.PMCTransport(
                    port,
                    baudrate=int(tspec.get("baudrate", 115200)),
                    host_watchdog_ms=int(tspec.get("host_watchdog_ms", 5000)),
                    feedback_scale=float(tspec.get("feedback_scale", 295.0)))
                self.drive = ACS550(port, transport=tp,
                                    ref1_max_fallback=self.ref1_max,
                                    ref_unit=self.ref_unit)
            else:
                ser = self.cfg.get("drive_serial") or {}
                self.drive = ACS550(port, baudrate=baud,
                                    parity=ser.get("parity", parity),
                                    unit=int(ser.get("station_id", unit)))

        # ── the load half ────────────────────────────────────────────────
        # Absent from this dashboard until now, which made the turbine
        # invisible on a rig whose whole purpose is turbines.
        self.load = None
        self.load_error = None
        # SCPI is request/response over ONE session and ChromaLoad holds no
        # lock of its own. The poll thread measures at 4 Hz while the sweep
        # thread drives find_peak; concurrent query() calls interleave and one
        # thread reads the other's reply. On a measuring instrument that is
        # not a crash — it is silently wrong volts and amps in the data.
        self._load_lock = threading.RLock()
        self._authz = threading.RLock()   # check-and-claim for _authorise
        self._abort_evt = threading.Event()
        self.load_last = {"volts": 0.0, "amps": 0.0, "watts": 0.0, "on": False,
                          "t": 0.0}
        self.load_demand = 0.0
        self.sweep = None                   # live blade-sweep progress

        self.connected = False
        self.connect_error = None
        self.estopped = False
        self.target_hz = 0.0
        self.running = False

        # Telemetry ring buffer. 4 Hz x 900 = 15 minutes of history, which is
        # longer than any single profile and cheap to hold.
        self.trace = deque(maxlen=900)
        self.events = deque(maxlen=200)

        self._lock = threading.RLock()      # guards drive access
        self._poll_thread = None
        self._stop_evt = threading.Event()
        self._job = None                    # active profile run, if any
        self._job_thread = None

        self.last = {"hz": 0.0, "amps": 0.0, "status": {}, "t": 0.0}

        # Live velocity input. Manual by default — an operator reading a gauge
        # is a perfectly valid source, it just goes stale. A dry run gets the
        # simulated source with a deliberate calibration bias so the
        # closed-loop path is actually exercised rather than merely present.
        self.vsource = None
        self.vloop = None
        try:
            self._cfg_mtime = self.cfg.path.stat().st_mtime
        except Exception:
            self._cfg_mtime = 0.0

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self):
        """
        Connect, bring up the velocity source, and start the poll thread.

        Returns False rather than raising if the drive is unreachable: the
        dashboard should still come up so you can read the diagnostics that
        tell you why. The poll thread is also what feeds the drive's
        comm-loss watchdog, so nothing else may own the port.
        """
        try:
            with self._lock:
                self.drive.connect()
            self.connected = True
            self.log("connected to drive"
                     + (" (SIMULATED)" if self.dry_run else ""), "ok")
        except Exception as e:
            self.connect_error = str(e)
            self.log(f"connect failed: {e}", "fault")
            return False

        self._init_velocity_source()
        self._init_load()

        self._stop_evt.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True,
                                             name="tunnel-poll")
        self._poll_thread.start()
        return True

    def _init_load(self):
        """
        Open the Chroma, or a modelled one in a dry run.

        Failure here is not fatal: the tunnel half must still come up so the
        operator can read why the load is missing. Half a dashboard beats a
        blank page and a traceback in a terminal nobody is looking at.
        """
        try:
            if self.dry_run:
                from load_sim import SimulatedLoad, SimulatedTurbine
                turb = SimulatedTurbine(peak_watts=3.8, volts_at_peak=10.9)
                turb.fan_rpm = 1.0
                self.load = SimulatedLoad(turb, volt_off=0.5).connect()
                self._sim_turbine = turb
                self.log("load simulated", "ok")
                return
            spec = self.cfg.get("load")
            if not spec:
                self.load_error = "no `load` block in tunnel.json"
                return
            from chroma_load import ChromaLoad, build_transport
            self.load = ChromaLoad(build_transport(spec),
                                   channel=spec.get("channel", 1)).connect()
            self.log(f"load connected: {self.load.identity}", "ok")
        except Exception as e:
            self.load_error = str(e)
            self.log(f"load unavailable: {e}", "warn")

    def _init_velocity_source(self):
        spec = dict(self.cfg.get("velocity_source") or {})
        kind = spec.pop("kind", None)
        try:
            if kind and kind not in ("manual", "simulated"):
                self.vsource = build_source(kind, **spec).start()
            elif self.dry_run and self.cfg.calibration:
                self.vsource = SimulatedSource(
                    self.drive, self.cfg.calibration,
                    bias=float(spec.get("bias", 0.88))).start()
                self.log("velocity: simulated source (0.88 bias to exercise "
                         "the loop)", "warn")
            else:
                self.vsource = ManualSource().start()
            if kind:
                self.log(f"velocity source: {self.vsource.name}", "ok")
        except Exception as e:
            self.vsource = ManualSource().start()
            self.log(f"velocity source failed ({e}) — falling back to manual",
                     "warn")

    def shutdown(self):
        """Always stop the fan on the way out."""
        self._stop_evt.set()
        if self.vsource:
            try:
                self.vsource.stop()
            except Exception:
                pass
        try:
            with self._lock:
                self.drive.stop()
                self.drive.stop_keepalive()
                self.drive.close()
        except Exception:
            pass

    def reload_config(self):
        """
        Re-read tunnel.json from disk.

        The CLI and the dashboard write the same file. If someone runs
        `characterize` from a terminal while the dashboard is up, the
        dashboard's in-memory τ is stale — and a stale τ silently disables the
        bandwidth check on every profile built afterwards. Cheap to re-read;
        expensive to be wrong about.
        """
        path = self.cfg.path
        self.cfg = TunnelConfig.load(path)
        self.log("config reloaded from disk")
        return self.cfg.summary()

    def _config_changed_on_disk(self):
        try:
            return self.cfg.path.stat().st_mtime > self._cfg_mtime
        except Exception:
            return False

    def log(self, message, level="info"):
        """Ring-buffered event line for the dashboard strip. Not persistent."""
        self.events.appendleft({"t": datetime.now().strftime("%H:%M:%S"),
                                "msg": message, "level": level})

    # ── the poll loop: also what feeds the drive's watchdog ──────────────

    def _poll_loop(self):
        while not self._stop_evt.wait(self.poll_period):
            try:
                with self._lock:
                    hz, amps = self.drive.actuals()
                    st = self.drive.status()
                self.last = {"hz": hz, "amps": amps, "status": st,
                             "t": time.time()}
                # Log measured velocity alongside derived. Where they differ,
                # the difference is the calibration being wrong today — which
                # is exactly the thing a static calibration cannot tell you.
                v_meas = self.vsource.read_or_none() if self.vsource else None
                v_derived = None
                if self.cfg.calibration:
                    try:
                        v_derived = round(float(
                            self.cfg.calibration.velocity(hz)), 3)
                    except Exception:
                        pass
                self.trace.append({
                    "t": time.time(), "meas": hz, "amps": amps,
                    "cmd": self.target_hz if self.running else 0.0,
                    "v_meas": round(v_meas, 3) if v_meas is not None else None,
                    "v_derived": v_derived})

                # The simulated rotor only knows about wind if we tell it.
                if self.dry_run and getattr(self, "_sim_turbine", None):
                    self._sim_turbine.fan_rpm = max(1.0, hz)

                if self.load is not None:
                    try:
                        with self._load_lock:
                            v, i, w = self.load.measure()
                        self.load_last = {"volts": v, "amps": i, "watts": w,
                                          "on": bool(self.load.is_on),
                                          "t": time.time()}
                        self.trace[-1]["p_w"] = round(w, 4)
                    except Exception as e:
                        self.load_error = str(e)

                if st.get("TRIPPED") and not self.estopped:
                    # Latch FIRST. last_fault() reads parameter 0401, which
                    # the PMC line protocol cannot serve — it raised, the
                    # except branch below caught it as "lost comms", and the
                    # latch was never set. On the real rig a drive fault was
                    # misreported as a dropped link and E-stop never engaged.
                    self.running = False
                    self.estopped = True
                    self._halt_all("drive fault")
                    try:
                        code = self.drive.last_fault()
                    except Exception:
                        code = "unreadable over this transport"
                    self.log(f"DRIVE FAULT — par 0401 = {code}", "fault")
            except DriveError as e:
                # Do not spam the log on a dead bus; one entry is enough.
                if self.connected:
                    self.connected = False
                    self.log(f"lost comms: {e}", "fault")
            except Exception:
                pass
            else:
                if not self.connected:
                    self.connected = True
                    self.log("comms restored", "ok")

    # ── unit helpers ─────────────────────────────────────────────────────

    def to_hz(self, value, unit):
        """Convert a UI value in hz / rpm / mps / mph into drive Hz."""
        cal = self.cfg.calibration
        u = (unit or "hz").lower()
        if u == "hz":
            return float(value)
        if not cal:
            raise ValueError(f"{unit} needs a velocity calibration")
        if u == "rpm":
            # The drive commands SPEED. When the calibration is rpm-native the
            # reference already IS rpm and there is nothing to convert —
            # dividing by the vestigial rpm_per_hz (29.5, left over from the Hz
            # era) turned a request for 1800 rpm into 61 rpm, and let a request
            # for 70,000 "rpm" slip under the 2400 soft limit as 2373.
            if self.ref_unit.lower() == "rpm" or getattr(cal, "domain", "") == "rpm":
                return float(value)
            if not cal.rpm_per_hz:
                raise ValueError("no drive map — run verify first")
            return float(value) / cal.rpm_per_hz
        native = float(value) * TO_MPS[u] / TO_MPS.get(cal.units.lower(), 1.0)
        return float(cal.hz(native))

    def describe(self, hz):
        """
        One frequency rendered in every unit the operator might think in.

        Returns Hz always, plus RPM and velocity when a calibration with a
        drive map is loaded. Missing keys mean the calibration cannot supply
        them — which the UI shows as a dash rather than inventing a number.
        """
        cal = self.cfg.calibration
        out = {"hz": round(float(hz), 2)}
        if cal:
            try:
                # Same trap in reverse: multiplying an rpm reference by
                # rpm_per_hz quoted 70,800 rpm on a 2435 rpm machine, in the
                # confirmation dialog that precedes starting a 15 HP fan.
                if self.ref_unit.lower() == "rpm" or \
                        getattr(cal, "domain", "") == "rpm":
                    out["rpm"] = round(float(hz))
                else:
                    out["rpm"] = round(float(hz) * cal.rpm_per_hz) \
                        if cal.rpm_per_hz else None
                v = float(cal.velocity(hz))
                out["mps"] = round(v, 2)
                out["mph"] = round(v / 0.44704, 1)
            except Exception:
                pass
        return out

    # ── manual control ───────────────────────────────────────────────────

    # ══════════════════════════════════════════════════════════════════
    # ONE AUTHORITY
    # ══════════════════════════════════════════════════════════════════
    #
    # Round 2 of the audit found the load check on 2 of 8 paths that can spin
    # the fan, E-stop invisible to characterize / freqresp / verify-hold, and
    # `_guard()` doing a check with no lock so two clicks start two threads.
    # The diagnosis from every reviewer was the same: safety was a set of
    # checks scattered across call sites, and each new path forgot one.
    #
    # So there is now exactly one gate. Every path that can produce output
    # calls `_authorise()`, it holds a lock across check-and-claim, and adding
    # a new path without it is the only way to get it wrong.

    # The smallest demand that counts as "loaded". Below this, constant
    # current is electrically an open circuit and the rotor is free to run
    # away - peak_finder refuses floor_amps <= 0 for the same reason.
    LOAD_FLOOR_A = 0.002

    def _authorise(self, action, *, moves_fan=True, needs_load=True):
        """
        The single gate in front of anything that can move the fan.

        Holds `_authz` across check-and-claim so two clicks, two tabs, or a
        request arriving mid-sweep cannot both pass. Raises with a reason an
        operator can act on; never returns a boolean to be ignored.
        """
        with self._authz:
            if self.estopped:
                raise RuntimeError(
                    f"refusing to {action}: E-STOP is latched. Clear it "
                    f"deliberately once you know why it tripped.")
            if not self.connected:
                raise RuntimeError(
                    f"refusing to {action}: no link to the drive "
                    f"({self.connect_error or 'comms lost'}).")
            if self._job and self._job.get("state") in ("running", "settling"):
                raise RuntimeError(
                    f"refusing to {action}: '{self._job.get('kind')}' is "
                    f"already running. Stop it first.")
            if self.sweep and self.sweep.get("state") == "running":
                raise RuntimeError(
                    f"refusing to {action}: a blade sweep is running "
                    f"({self.sweep.get('blade')}, point {self.sweep.get('i')}"
                    f"/{self.sweep.get('n')}). Abort it first.")

            if moves_fan and needs_load and self.load is not None:
                # `is_on` alone is not enough: LOAD ON at 0.000 A is
                # electrically an open circuit and the old check passed it
                # while reporting "safe to wind up".
                if not self.load.is_on:
                    raise RuntimeError(
                        f"refusing to {action}: the electronic load is OFF "
                        f"and a rotor is connected. An unloaded rotor in "
                        f"moving air accelerates until something mechanical "
                        f"stops it. Load ON, then wind UP.")
                if self.load_demand < self.LOAD_FLOOR_A:
                    raise RuntimeError(
                        f"refusing to {action}: the load is ON but commanding "
                        f"{self.load_demand * 1000:.1f} mA, which is an open "
                        f"circuit as far as the rotor is concerned. Set at "
                        f"least {self.LOAD_FLOOR_A * 1000:.0f} mA first.")
            return True

    def _halt_all(self, why):
        """
        Latch every running activity as aborted.

        `stop()` and `estop()` used to touch only the drive and `_job`. A
        blade sweep runs on its own thread and consults `sw["abort"]`, so a
        stop was silently undone: the worker's next iteration saw
        `self.running == False` and called `drive.start()` again. Pressing
        Ramp Stop RESTARTED the fan. One helper now marks everything, and
        both stop paths call it.
        """
        if self.sweep and self.sweep.get("state") == "running":
            self.sweep["abort"] = True
            self.sweep.setdefault("message", f"aborted — {why}")
        if self._job and self._job.get("state") in ("running", "settling"):
            self._job["state"] = "aborted"
        self._abort_evt.set()

    def should_stop(self):
        """
        Predicate handed to any long-running routine so it can bail.

        `characterize`, `freqresp` and the velocity hold are fixed sleep
        sequences that never looked at `_job["state"]`, so E-stop did not
        reach them: the latch was set, the log said aborted, and the fan kept
        running the profile to completion.
        """
        return bool(self.estopped or self._abort_evt.is_set()
                    or (self._job and self._job.get("state") == "aborted"))

    def _guard(self, action="command the fan", **kw):
        """
        Retained as the name every existing call site already uses; the logic
        now lives in `_authorise`, so the checks cannot drift apart.
        """
        return self._authorise(action, **kw)

    def _guard_legacy(self):
        """
        Superseded. Kept only to document what used to be checked: a latched
        E-stop and a profile already running. It missed the load entirely,
        held no lock, and did not see a blade sweep.
        """
        if self.estopped:
            raise RuntimeError("E-STOP is latched — clear it before commanding")
        if self._job and self._job.get("state") == "running":
            raise RuntimeError("a profile is running — stop it first")
        # A blade sweep spawns its own thread and never populates _job, so it
        # was invisible here: a second browser tab could set a setpoint or
        # start a profile straight into a running sweep, and the two would
        # interleave setpoints on one drive.
        if self.sweep and self.sweep.get("state") == "running":
            raise RuntimeError(
                f"a blade sweep is running ({self.sweep.get('blade')}, point "
                f"{self.sweep.get('i')}/{self.sweep.get('n')}) — abort it first")

    def set_setpoint(self, value, unit="hz"):
        """Clamp server-side. The UI's limit is a convenience, not the guard."""
        self._guard("change the setpoint", moves_fan=False)
        hz = self.to_hz(value, unit)
        limit = self.cfg.hz_limit
        if limit and hz > limit:
            raise ValueError(f"{hz:.1f} Hz exceeds the {limit:.0f} Hz soft limit")
        hz = max(0.0, hz)
        with self._lock:
            self.target_hz = self.drive.set_hz(hz) if self.running else hz
            if not self.running:
                self.target_hz = hz
        self.log(f"setpoint {self.describe(hz)['hz']} Hz")
        return self.describe(self.target_hz)

    def _require_loaded(self, what):
        """
        Refuse to spin the fan with the rotor unloaded.

        The interlock was advisory: `interlock_state()` reported `wind_ok`
        and the UI greyed a button, but nothing on the server refused. A
        stale page, a second tab, or a direct POST would start a 15 HP fan
        against an open-circuit rotor regardless.

        Only enforced when a load is actually configured — a tunnel run with
        no turbine in the section is a legitimate thing to do.
        """
        if self.load is None:
            return
        if not self.load.is_on:
            raise RuntimeError(
                f"refusing to {what}: the electronic load is OFF and a rotor "
                f"is connected. An unloaded rotor in moving air accelerates "
                f"until something mechanical stops it. Turn the load on "
                f"first — load ON, then wind UP.")

    def go(self):
        """
        Start the fan at the current setpoint.

        Three things happen before any output: the E-stop latch and job guard
        are checked, the drive is verified to be in REMOTE (LOC/REM on the
        keypad silently diverts control to the panel while writes still report
        success), and the keep-alive is started so the drive's watchdog is fed
        for as long as this stays running.

        Raises rather than starting if any of those fail.
        """
        self._authorise("start the fan")
        if self.target_hz <= 0:
            raise ValueError("set a speed before starting")
        with self._lock:
            st = self.drive.status()
            if not st.get("REMOTE", True):
                raise RuntimeError(
                    "drive is in LOCAL keypad mode and is ignoring the "
                    "fieldbus. Press LOC/REM on the keypad.")
            self.drive.start_keepalive()
            self.drive.start(self.target_hz)
        self.running = True
        self.log(f"START at {self.target_hz:.1f} Hz", "ok")
        return True

    def stop(self):
        """
        Ramp to stop over parameter 2203. Not instantaneous — on a fan with
        real rotating inertia the ramp may be tens of seconds, and on the way
        down it is limited by how much regenerated energy the DC bus absorbs.

        For an immediate output cut use estop(); for the actual safety device
        use the button on the wall.
        """
        self._halt_all("ramp stop")
        with self._lock:
            self.drive.stop()
        self.running = False
        self.log("ramp stop")
        return True

    def estop(self):
        """
        Coast stop and latch. This is a *convenience*, not a safety device —
        the hardwired E-stop in the contactor circuit is the safety device and
        nothing here is a substitute for it.
        """
        self._halt_all("E-STOP")
        with self._lock:
            try:
                self.drive.coast()
            finally:
                self.running = False
                self.estopped = True
        if self._job:
            self._job["state"] = "aborted"
        self.log("E-STOP — coast stop issued", "fault")
        return True

    def clear_estop(self):
        """
        Release the E-stop latch, resetting a drive fault if one is active.

        Zeroes the setpoint deliberately: whatever was commanded before the
        stop is no longer a statement of intent, and resuming at it would be a
        surprise to whoever pressed the button.
        """
        # Refuse while a worker is still unwinding. Clearing the latch used to
        # let an in-flight sweep — which only polls `estopped` about once a
        # second — resume and drive the fan again on its next point.
        if self._job_thread is not None and self._job_thread.is_alive():
            raise RuntimeError(
                "a run is still stopping — wait for it to finish before "
                "clearing the E-stop, or the fan may restart under it")
        self._abort_evt.clear()

        with self._lock:
            if self.drive.is_faulted():
                self.drive.reset_fault()
                self.log("fault reset", "warn")
        self.estopped = False
        self.target_hz = 0.0
        self.log("E-stop cleared, setpoint zeroed", "ok")
        return True

    # ── parameters ───────────────────────────────────────────────────────

    # ══════════════════════════════════════════════════════════════════
    # DRIVE PARAMETERS — capability, profiles, snapshots
    # ══════════════════════════════════════════════════════════════════

    def param_capability(self):
        """
        What this transport can actually do with parameters, and why.

        The Parameters tab used to offer a Write button on every row whatever
        the transport underneath could do. Over a 2.0 PMC every one of them
        failed with a register-level error that pointed at the wrong thing.
        """
        tp = getattr(self.drive, "transport", None)
        if tp is None:
            return {"read": True, "write": True, "kind": "direct",
                    "note": "direct Modbus — full parameter access"}
        rdwr = bool(getattr(tp, "_rdwr", False))
        return {
            "read": rdwr, "write": rdwr, "kind": "pmc",
            "firmware": "3.0+" if rdwr else "2.x",
            "note": ("PMC firmware 3.0 — RD/WR available" if rdwr else
                     "This PMC is command-shaped only (HZ/RUN/STAT) and "
                     "cannot reach a parameter. Flash "
                     "firmware/acs550_pmc_v3/ to enable RD/WR. The original "
                     "sketch is untouched at firmware/acs550_pmc/."),
        }

    def param_refusal(self, par):
        """Why the firmware would refuse this write, or None."""
        try:
            from drive_profile import refusal
            return refusal(int(par))
        except Exception:
            return None

    def list_profiles(self):
        from drive_profile import PROFILES
        out = []
        for f in sorted(PROFILES.glob("*.json")):
            try:
                d = json.loads(f.read_text())
                out.append({"name": d.get("name", f.stem),
                            "description": d.get("description", ""),
                            "count": len(d.get("parameters", {}))})
            except Exception:
                pass
        return out

    def profile_diff(self, name):
        """Live drive vs a stored profile. Read-only."""
        from drive_profile import PROFILES, KNOWN
        f = PROFILES / f"{name}.json"
        if not f.exists():
            raise RuntimeError(f"no profile '{name}'")
        prof = json.loads(f.read_text())
        want = prof.get("parameters", {})
        rows = []
        with self._lock:
            for k, spec in sorted(want.items(), key=lambda kv: int(kv[0])):
                par = int(k)
                target = spec["value"] if isinstance(spec, dict) else spec
                try:
                    live = self.drive.read_param(par)
                    err = None
                except Exception as e:
                    live, err = None, str(e)[:70]
                rows.append({
                    "num": par, "name": KNOWN.get(par, ""),
                    "live": live, "target": target,
                    "match": (live == target) if live is not None else None,
                    "why": spec.get("why", "") if isinstance(spec, dict) else "",
                    "refused": self.param_refusal(par), "error": err})
        return {"profile": prof.get("name", name),
                "description": prof.get("description", ""), "rows": rows}

    def snapshot_params(self, note=""):
        """Read every known parameter and write a timestamped record."""
        from drive_profile import KNOWN, write_snapshot
        vals, failed = {}, []
        with self._lock:
            for par in sorted(KNOWN):
                try:
                    vals[str(par)] = self.drive.read_param(par)
                except Exception as e:
                    failed.append({"num": par, "error": str(e)[:70]})
        path = write_snapshot(vals, "dashboard", note or "taken from the dashboard")
        self.log(f"parameter snapshot: {len(vals)} read → {path.name}", "ok")
        return {"file": str(path), "read": len(vals), "failed": failed,
                "values": vals}

    def unlock_param_writes(self):
        tp = getattr(self.drive, "transport", None)
        if tp is None or not hasattr(tp, "unlock_writes"):
            return {"unlocked": True, "note": "direct transport needs no unlock"}
        with self._lock:
            tp.unlock_writes()
        self.log("parameter writes unlocked for 120 s", "warn")
        return {"unlocked": True, "seconds": 120}

    def read_params(self, numbers):
        out = {}
        with self._lock:
            for n in numbers:
                try:
                    out[n] = self.drive.read_param(int(n))
                except DriveError as e:
                    out[n] = None
        return out

    def write_param(self, number, value):
        """
        Persistent, no undo — same as editing on the keypad.

        The two that hand over control are deliberately refused while the fan
        is turning: changing the command source mid-run is a good way to get
        surprised.
        """
        n = int(number)
        # One refusal list, shared with drive_profile and enforced again in
        # the PMC firmware. The old guard covered control-source parameters
        # while running and said nothing about the comm-loss watchdog, the
        # serial config, or the motor model — so on a direct-transport bench
        # rig the dashboard would happily disable 3018/3019, the mechanism
        # that makes this whole architecture safe.
        no = self.param_refusal(n)
        if no:
            raise RuntimeError(f"refusing to write par {n}: {no}")
        if self.running:
            raise RuntimeError(
                f"refusing to write par {n} while the fan is turning — "
                f"stop it first")
        with self._lock:
            before = self.drive.read_param(n)
            self.drive.write_param(n, int(value))
            after = self.drive.read_param(n)
        self.log(f"par {n}: {before} → {after}", "warn")
        return {"param": n, "before": before, "after": after}

    # ── profiles ─────────────────────────────────────────────────────────

    def build_profile(self, spec):
        """Turn a UI spec into (t, u_hz, description, diagnostics)."""
        kind = spec.get("kind", "1mc")
        unit = spec.get("units", "hz")
        dt = float(spec.get("dt", 0.05))
        mean = float(spec.get("mean", 20))
        amp = float(spec.get("amp", 5))
        length = float(spec.get("length", 20))

        if kind == "1mc":
            t, u = gusts.one_minus_cosine(mean, amp, length, dt=dt,
                                          lead=float(spec.get("lead", 5)),
                                          trail=float(spec.get("trail", 10)))
        elif kind == "step":
            t, u = gusts.sharp_edged(mean, amp, length, dt=dt)
        elif kind == "ramp":
            t, u = gusts.ramp(mean, mean + amp, length, dt=dt)
        elif kind == "sine":
            t, u = gusts.sinusoid(mean, amp, float(spec.get("freq", 0.05)),
                                  length, dt=dt)
        elif kind in ("vonkarman", "dryden"):
            gen = (gusts.von_karman if kind == "vonkarman" else gusts.dryden)
            f_max = None
            if self.cfg.tau:
                f_max = 1.0 / (2 * np.pi * self.cfg.tau)
            t, u = gen(mean, float(spec.get("sigma", 2)),
                       float(spec.get("length_scale", 40)),
                       float(spec.get("duration", 120)), dt=dt,
                       seed=int(spec.get("seed", 1)), f_max=f_max)
        else:
            raise ValueError(f"unknown profile {kind}")

        if unit != "hz":
            u = np.array([self.to_hz(x, unit) for x in u])

        with self._lock:
            accel, _ = self.drive.get_ramp_times()
        max_slew = self.drive.ref1_max_hz / accel if accel > 0 else None

        diag = gusts.check_realizable(
            t, u, tau=self.cfg.tau, max_slew_hz_s=max_slew, verbose=False,
            tau_down=self.cfg.get("tau_down"),
            dead_time=self.cfg.get("dead_time", 0.0))

        desc = f"{kind} · {len(u)} samples · {t[-1]:.0f} s"
        predicted = None

        if spec.get("feedforward"):
            if not self.cfg.tau:
                raise ValueError("feedforward needs τ — run characterize first")
            comp = _ff.compensate(
                t, u, tau=self.cfg.tau, tau_down=self.cfg.get("tau_down"),
                dead_time=self.cfg.get("dead_time", 0.0),
                slew_limit=max_slew, hz_limit=self.cfg.hz_limit, verbose=False)
            diag["feedforward"] = {k: v for k, v in comp.items()
                                   if k not in ("command", "predicted")}
            # Keep the array OUT of diag: diag is serialized into the run's
            # metadata sidecar, and a 700-element float array does not belong
            # in a record meant to be readable six months from now.
            predicted = comp["predicted"]
            u = comp["command"]
            desc += " · feedforward"

        return t, u, desc, diag, predicted

    def preflight(self, samples=0, duration_s=0, diagnostics=None):
        ok, checks = _pre.run_all(
            drive=self.drive, velocity_source=self.vsource, samples=samples,
            duration_s=duration_s, diagnostics=diagnostics, tau=self.cfg.tau,
            log_dir=str(LOG_DIR))
        return {"ok": ok, "checks": checks}

    def start_profile(self, spec, skip_preflight=False):
        """
        Build, check and play a profile in a background thread.

        Refuses on a pre-flight failure rather than discovering the problem at
        minute eighteen. `skip_preflight` exists because most of what
        pre-flight reports is a judgement call the operator is better placed
        to make -- but it must be asked for explicitly.
        """
        self._guard()
        t, u, desc, diag, _ = self.build_profile(spec)

        # Refuse rather than fail at minute eighteen.
        if not skip_preflight:
            pf = self.preflight(samples=len(u),
                                duration_s=float(t[-1]) + float(spec.get("settle", 20)),
                                diagnostics=diag)
            if not pf["ok"]:
                bad = "; ".join(c["name"] for c in pf["checks"]
                                if c["status"] == "fail")
                raise RuntimeError(f"pre-flight failed: {bad}")

        limit = self.cfg.hz_limit
        if limit and float(u.max()) > limit:
            raise ValueError(f"profile peaks at {u.max():.1f} Hz, above the "
                             f"{limit:.0f} Hz soft limit")

        settle = float(spec.get("settle", 20))
        LOG_DIR.mkdir(exist_ok=True)
        tag = f"{datetime.now():%Y%m%d_%H%M%S}_{spec.get('kind','profile')}"
        log_path = LOG_DIR / f"{tag}.csv"

        self._job = {"state": "settling", "desc": desc, "spec": spec,
                     "diagnostics": diag, "log": str(log_path),
                     "progress": 0.0, "started": time.time(),
                     "duration": float(t[-1]) + settle}

        def run():
            try:
                with self._lock:
                    self.drive.start_keepalive()
                    self.drive.start(float(u[0]))
                self.running = True
                self.target_hz = float(u[0])
                self.log(f"profile: settling {settle:.0f} s at "
                         f"{u[0]:.1f} Hz", "ok")

                t_settle = time.time()
                while time.time() - t_settle < settle:
                    if self._job["state"] == "aborted":
                        return
                    self._job["progress"] = ((time.time() - t_settle) / settle) * 0.15
                    time.sleep(0.2)

                self._job["state"] = "running"
                self.log(f"profile playing: {desc}", "ok")

                meta = self.run_metadata({"mode": "profile", "spec": spec,
                                          "diagnostics": diag})

                player = ProfilePlayer(self.drive, log_path=log_path,
                                       hz_limit=limit, metadata=meta,
                                       velocity_source=self.vsource)

                def on_sample(k, elapsed, cmd, meas, amps):
                    self.target_hz = cmd
                    self._job["progress"] = 0.15 + 0.85 * (k / max(len(u), 1))
                    if self._job["state"] == "aborted":
                        raise ProfileAborted("aborted from the dashboard")

                player.play(t, u, on_sample=on_sample,
                            return_to=float(u[0]))
                self._job["state"] = "done"
                self._job["progress"] = 1.0
                self.log(f"profile complete → {log_path.name}", "ok")

            except ProfileAborted as e:
                self._job["state"] = "aborted"
                self._job["error"] = str(e)
                self.log(f"profile aborted: {e}", "fault")
            except Exception as e:
                self._job["state"] = "error"
                self._job["error"] = str(e)
                self.log(f"profile error: {e}", "fault")
            finally:
                try:
                    with self._lock:
                        self.drive.stop()
                except Exception:
                    pass
                self.running = False

        self._job_thread = threading.Thread(target=run, daemon=True,
                                            name="tunnel-profile")
        self._job_thread.start()
        return self._job

    def abort_profile(self):
        if self._job:
            self._job["state"] = "aborted"
        self.stop()
        return True

    @property
    def job(self):
        return self._job

    # ── commissioning jobs ───────────────────────────────────────────────
    #
    # characterize, freqresp and verify are the steps that decide what the
    # whole project can promise, and until now they only existed in the CLI.
    # They are long-running (minutes), so they get the same job treatment as a
    # profile: one at a time, progress reported, output captured for the UI.

    def _start_job(self, kind, fn, est_duration):
        # Covers characterize, freqresp, verify-hold, the stepped sweep and
        # the velocity hold in one place. Each of those called drive.start()
        # directly and was behind no load check at all.
        self._guard(f"start {kind}")
        self._job = {"state": "running", "kind": kind, "progress": 0.0,
                     "started": time.time(), "duration": est_duration,
                     "output": "", "desc": kind}

        def wrap():
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    result = fn()
                self._job["result"] = result
                self._job["state"] = "done"
                self._job["progress"] = 1.0
                self.log(f"{kind} complete", "ok")
            except Exception as e:
                self._job["state"] = "error"
                self._job["error"] = str(e)
                self.log(f"{kind} failed: {e}", "fault")
            finally:
                self._job["output"] = buf.getvalue()
                try:
                    with self._lock:
                        self.drive.stop()
                except Exception:
                    pass
                self.running = False

        # A cheap progress estimate off wall time. The underlying routines are
        # mostly fixed-duration sleeps, so this tracks well enough to be useful
        # and is far simpler than threading a callback through them.
        def ticker():
            t0 = time.time()
            while self._job and self._job["state"] == "running":
                self._job["progress"] = min(
                    0.99, (time.time() - t0) / max(est_duration, 1))
                time.sleep(0.5)

        self.running = True
        threading.Thread(target=ticker, daemon=True).start()
        self._job_thread = threading.Thread(target=wrap, daemon=True,
                                            name=f"job-{kind}")
        self._job_thread.start()
        return self._job

    def _job_was_aborted(self):
        return bool(self._job and self._job.get("state") == "aborted") \
            or self.estopped

    def run_characterize(self, base=20.0, step=10.0, settle=30.0, record=30.0):
        """
        Step response → τ, rise time, corner frequency. Saves τ to the config
        so every profile from then on is checked against it automatically.

        A negative step measures the *falling* constant, which is the one that
        actually limits a symmetric gust — the tunnel decelerates more slowly
        than it accelerates.
        """
        LOG_DIR.mkdir(exist_ok=True)
        falling = step < 0
        tag = "step_down" if falling else "step_up"
        log = LOG_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{tag}.csv"

        def fn():
            res = _char.step_response(self.drive, base_hz=base, step_hz=step,
                                      settle=settle, record=record,
                                      log_path=log)
            tau = res.get("tau_s")
            if tau and tau == tau:
                key = "tau_down" if falling else "tau"
                self.cfg.set(key, round(float(tau), 3),
                             note=f"step {base}→{base + step} Hz").save()
                res["saved_as"] = key
            return res

        return self._start_job(f"characterize {'down' if falling else 'up'}",
                               fn, settle + record + 10)

    def run_freqresp(self, base=25.0, amp=5.0, frequencies=None, cycles=6):
        freqs = frequencies or [0.02, 0.05, 0.1, 0.2, 0.5]
        LOG_DIR.mkdir(exist_ok=True)
        est = sum(cycles / f for f in freqs) + 30

        def fn():
            return {"points": _char.freq_response(
                self.drive, base_hz=base, amplitude_hz=amp,
                frequencies=freqs, cycles=cycles, log_dir=str(LOG_DIR))}

        return self._start_job("freqresp", fn, est)

    def run_verify_hold(self, hz=30.0, settle=30.0, hold=30.0):
        """
        Hold one frequency while the operator reads the anemometer. The
        measurement comes back through apply_verify().
        """
        cal = self.cfg.calibration
        predicted = float(cal.velocity(hz)) if cal else None

        def fn():
            self.drive.start_keepalive()
            self.drive.start(hz)
            self.target_hz = hz
            time.sleep(settle)
            f, a = self.drive.actuals()
            time.sleep(hold)
            self.drive.stop()
            return {"hz": hz, "predicted": predicted,
                    "measured_hz": f, "amps": a,
                    "units": cal.units if cal else None}

        return self._start_job(f"verify at {hz:.0f} Hz", fn, settle + hold + 5)

    def submit_manual_velocity(self, value):
        if not isinstance(self.vsource, ManualSource):
            raise RuntimeError(f"velocity source is {self.vsource.name}, "
                               f"not manual")
        return self.vsource.submit(value)

    def hold_velocity(self, target, duration=90.0, kp=None, ki=None,
                      period=None):
        """
        Closed-loop hold on *measured* wind speed.

        The open-loop calibration sets the starting point; the loop trims from
        there and reports how far off the calibration is under today's
        conditions. A steady correction that persists across sessions is a
        calibration error worth folding in; one that moves day to day is air
        density, and closed loop is the right permanent answer.

        Deliberately slow — it corrects the operating point, not the waveform.
        A controller tuned faster than the plant does not make the tunnel
        faster, it makes it oscillate, and an oscillating 15 HP fan is not
        something you want to stand next to.
        """
        self._guard()
        if self.vsource is None or not self.vsource.healthy:
            raise RuntimeError("no healthy velocity source — enter a manual "
                               "reading or configure a DAQ channel")
        cal = self.cfg.calibration
        if cal is None:
            raise RuntimeError("closed loop needs a velocity calibration")

        g = suggest_gains(self.cfg.tau or 3.0, 1.0 / cal.coeffs[0])
        ctrl = VelocityController(
            self.drive, self.vsource.read, cal,
            kp=kp if kp is not None else g["kp"],
            ki=ki if ki is not None else g["ki"],
            period=period if period is not None else g["period"],
            hz_limit=self.cfg.hz_limit)
        self.vloop = ctrl

        def fn():
            self.running = True
            res = ctrl.hold(target, duration, verbose=True)
            res["history"] = ctrl.history[-200:]
            res["gains"] = {"kp": ctrl.kp, "ki": ctrl.ki, "period": ctrl.period}
            return res

        return self._start_job(f"hold {target:g} {cal.units}", fn,
                               duration + ctrl.period * 4 + 5)

    def apply_verify(self, hz, measured):
        """
        Solve for the rpm_per_hz that makes the calibration land on the
        measurement, and report the implied pulley ratio.

        The velocity-vs-RPM half is measured and solid; only the Hz→RPM link
        is assumed. One reading pins it down without needing the nameplate.
        """
        cal = self.cfg.calibration
        if cal is None:
            raise ValueError("no calibration loaded")

        # ── refuse on an rpm-native calibration ─────────────────────────
        # This routine corrects the Hz→RPM link. There is no such link on
        # this drive: par 1105 is a SPEED reference and the calibration is
        # rpm→velocity directly. Run against it, the old code divided an
        # already-per-rpm slope by the vestigial rpm_per_hz, called
        # attach_drive_map() which flipped domain to "hz" while drive_unit
        # stayed "rpm", saved that over tunnel.json and stamped it "VERIFIED
        # and corrected". Every velocity lookup then raised, the wind-speed
        # readouts silently became dashes, and the only copy of a measured
        # calibration was gone.
        if self.ref_unit.lower() == "rpm" or getattr(cal, "domain", "") == "rpm":
            raise ValueError(
                "this calibration is rpm-native and the drive commands speed, "
                "so there is no Hz→RPM stage to correct. A disagreement here "
                "means the rpm→velocity fit itself is off, or the anemometer "
                "is — refit from measured points with `run.py calibrate` "
                "rather than rescaling a drive map that does not exist.")

        # Back the previous calibration up before touching it. This writes the
        # only measured calibration in the project.
        try:
            import json as _json
            bak = Path(self.cfg.path).with_suffix(".json.bak")
            bak.write_text(_json.dumps(
                {"calibration": self.cfg.get("calibration"),
                 "saved": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2))
            self.log(f"previous calibration backed up to {bak.name}", "ok")
        except Exception as e:
            raise ValueError(f"refusing to overwrite the calibration — could "
                             f"not write a backup first: {e}")

        predicted = float(cal.velocity(hz))
        ratio = measured / predicted if predicted else float("nan")

        out = {"hz": hz, "predicted": predicted, "measured": measured,
               "ratio": ratio}

        if abs(ratio - 1) < 0.05:
            self.cfg.set("calibration_status", "VERIFIED at one point").save()
            out["verdict"] = ("within 5% — the direct-drive assumption holds, "
                              "nothing to change")
            self.log(f"calibration verified at {hz} Hz", "ok")
            return out

        A_rpm = cal.coeffs[0] / cal.rpm_per_hz
        B = cal.coeffs[1]
        k_new = (measured - B) / (A_rpm * hz)
        implied = k_new / (1750.0 / 60.0)

        fresh = Calibration.from_dict(self.cfg.data["calibration"])
        fresh.domain = "rpm"
        fresh.coeffs = np.array([A_rpm, B])
        fresh.hz_min *= cal.rpm_per_hz
        fresh.hz_max *= cal.rpm_per_hz
        fresh.attach_drive_map(k_new, 1.0)
        self.cfg.set_calibration(fresh, note=f"verified at {hz} Hz = {measured}")
        self.cfg.set("calibration_status", "VERIFIED and corrected").save()

        out.update({"rpm_per_hz_old": cal.rpm_per_hz, "rpm_per_hz_new": k_new,
                    "implied_pulley": implied,
                    "verdict": (f"corrected: {cal.rpm_per_hz:.2f} → "
                                f"{k_new:.2f} rpm/Hz, implying a pulley ratio "
                                f"of {implied:.3f} "
                                f"({'direct drive' if abs(implied - 1) < 0.05 else 'a belt'})")})
        self.log(f"calibration corrected to {k_new:.2f} rpm/Hz", "warn")
        return out

    # ── session attribution ──────────────────────────────────────────────
    #
    # A run's numbers are only half of it. Six months later — or when Jeong's
    # lab asks which dataset had which blades — "20250316_1655_1mc.csv" tells
    # you nothing about who ran it or what was in the test section. That
    # context cannot be reconstructed afterwards, so it gets captured once per
    # session and stamped into every run.

    def set_session(self, operator=None, configuration=None, notes=None,
                    project=None):
        sess = dict(self.cfg.get("session") or {})
        for k, v in (("operator", operator), ("configuration", configuration),
                     ("notes", notes), ("project", project)):
            if v is not None:
                sess[k] = v
        sess["opened"] = sess.get("opened") or datetime.now().isoformat(
            timespec="seconds")
        sess["updated"] = datetime.now().isoformat(timespec="seconds")
        self.cfg.set("session", sess).save()
        self.log(f"session: {sess.get('operator','?')} · "
                 f"{sess.get('configuration','?')}")
        return sess

    def run_metadata(self, extra=None):
        """The provenance block stamped into every run's sidecar."""
        meta = {
            "session": self.cfg.get("session"),
            "velocity_source": self.vsource.describe() if self.vsource else None,
            "ambient": self.cfg.ambient(),
            "tau": self.cfg.tau, "tau_down": self.cfg.get("tau_down"),
            "hz_limit": self.cfg.hz_limit,
            "calibration": self.cfg.calibration.to_dict()
            if self.cfg.calibration else None,
            "calibration_status": self.cfg.get("calibration_status"),
            "simulated": self.dry_run,
            "recorded": datetime.now().isoformat(timespec="seconds"),
        }
        meta.update(extra or {})
        return meta

    # ── stepped sweep ────────────────────────────────────────────────────

    def run_sweep(self, start, stop, step, settle=25.0, dwell=15.0,
                  units="hz"):
        """
        The classic point-by-point run: step, let the flow settle, acquire,
        advance.

        Logs continuously with a `phase` column so an acquisition window is
        identifiable after the fact — that is the marker Jeong's DAQ side
        needs to line its records up against, without either lab having to
        trust a stopwatch.

        Records the mean AND standard deviation at each point. The std is not
        decoration: it is how you tell a settled point from one that was still
        drifting when you acquired.
        """
        # Argument validation BEFORE the authorisation gate. An out-of-range
        # sweep is wrong whatever the link state, and reporting "no link"
        # first would hide the real problem behind a transient one.
        pts_user = list(np.arange(start, stop + step / 2, step))
        pts_hz = [self.to_hz(v, units) for v in pts_user]

        limit = self.cfg.hz_limit
        over = [h for h in pts_hz if limit and h > limit]
        if over:
            raise ValueError(f"sweep reaches {max(over):.0f} rpm, above the "
                             f"{limit:.0f} rpm soft limit")

        self._guard("start a stepped sweep")

        LOG_DIR.mkdir(exist_ok=True)
        tag = f"{datetime.now():%Y%m%d_%H%M%S}_sweep"
        log_path = LOG_DIR / f"{tag}.csv"
        pts_path = LOG_DIR / f"{tag}_points.csv"
        est = len(pts_hz) * (settle + dwell) + 10

        def fn():
            import csv as _csv
            results = []
            with open(log_path, "w", newline="") as fh:
                w = _csv.writer(fh)
                w.writerow(["t_s", "cmd_hz", "meas_hz", "meas_a", "v_meas",
                            "phase", "point"])
                t0 = time.time()

                self.drive.start_keepalive()
                self.drive.start(pts_hz[0])
                self.running = True

                for i, (hz, uv) in enumerate(zip(pts_hz, pts_user)):
                    self.drive.set_hz(hz)
                    self.target_hz = hz
                    print(f"→ point {i+1}/{len(pts_hz)}: {uv:.2f} {units} "
                          f"= {hz:.2f} Hz")

                    for phase, dur in (("settling", settle), ("acquiring", dwell)):
                        samples = []
                        tp = time.time()
                        while time.time() - tp < dur:
                            if self._job["state"] == "aborted":
                                raise ProfileAborted("aborted from the dashboard")
                            f, a = self.drive.actuals()
                            v = (self.vsource.read_or_none()
                                 if self.vsource else None)
                            w.writerow([f"{time.time()-t0:.3f}", f"{hz:.3f}",
                                        f"{f:.2f}", f"{a:.2f}",
                                        "" if v is None else f"{v:.3f}",
                                        phase, i])
                            if phase == "acquiring":
                                samples.append((f, a, v))
                            time.sleep(0.25)
                        fh.flush()

                    fs = np.array([s[0] for s in samples])
                    amps = np.array([s[1] for s in samples])
                    vs = np.array([s[2] for s in samples if s[2] is not None])
                    rec = {"point": i, "setpoint_user": float(uv),
                           "units": units, "setpoint_hz": float(hz),
                           "mean_hz": float(fs.mean()),
                           "std_hz": float(fs.std()),
                           "mean_a": float(amps.mean()),
                           "n": len(fs)}
                    if self.cfg.calibration:
                        try:
                            rec["derived_mps"] = round(
                                float(self.cfg.calibration.velocity(fs.mean())), 3)
                        except Exception:
                            pass
                    if len(vs):
                        # Measured velocity is the number that belongs in the
                        # paper; derived is what the calibration predicted.
                        # Recording both makes the calibration auditable after
                        # the fact instead of an article of faith.
                        rec["mean_mps"] = round(float(vs.mean()), 3)
                        rec["std_mps"] = round(float(vs.std()), 4)
                    else:
                        rec["mean_mps"] = rec.get("derived_mps")
                    results.append(rec)
                    print(f"   settled {rec['mean_hz']:.2f} ± "
                          f"{rec['std_hz']:.3f} Hz, {rec['mean_a']:.1f} A")
                    if rec["std_hz"] > 0.25:
                        print(f"   NOTE  spread is wide — this point may not "
                              f"have settled. Lengthen settle.")

            with open(pts_path, "w", newline="") as fh:
                w = _csv.writer(fh)
                cols = list(results[0].keys())
                w.writerow(cols)
                for r in results:
                    w.writerow([r[c] for c in cols])

            import json as _json
            log_path.with_suffix(".json").write_text(_json.dumps(
                self.run_metadata({"mode": "sweep", "units": units,
                                   "setpoints": pts_user, "settle": settle,
                                   "dwell": dwell, "points": results}),
                indent=2, default=str))
            self.drive.stop()
            return {"points": results, "log": str(log_path),
                    "points_csv": str(pts_path)}

        return self._start_job("sweep", fn, est)

    # ── snapshot for the UI ──────────────────────────────────────────────

    # ══════════════════════════════════════════════════════════════════
    # THE LOAD, AND THE INTERLOCK IT LIVES UNDER
    # ══════════════════════════════════════════════════════════════════

    def interlock_state(self):
        """
        Is it currently safe to raise the wind, and is it safe to unload?

        Returns a dict the UI renders as a single prominent indicator, because
        this is the one rule on the rig that breaks hardware rather than data.
        """
        spinning = bool(self.running or self.last.get("hz", 0.0) > 5.0)
        # `is_on` is an optimistic Python attribute set by on()/off() and
        # never read back from the instrument. It says what we asked for, not
        # what the Chroma is doing. Measured current is the only evidence the
        # rotor is actually loaded.
        on = bool(self.load and self.load.is_on)
        amps = self.load_last.get("amps", 0.0)
        fresh = (time.time() - (self.load_last.get("t") or 0)) < 3.0
        if self.load is None:
            return {"level": "none", "text": "no load connected",
                    "wind_ok": False, "unload_ok": True}
        if spinning and not on:
            return {"level": "danger",
                    "text": "ROTOR TURNING WITH THE LOAD OFF — open circuit",
                    "wind_ok": False, "unload_ok": False}
        if spinning and not fresh:
            return {"level": "danger",
                    "text": "ROTOR TURNING and the load reading is STALE — "
                            "cannot confirm it is loaded",
                    "wind_ok": False, "unload_ok": False}
        if spinning and amps < self.LOAD_FLOOR_A:
            return {"level": "danger",
                    "text": f"ROTOR TURNING but the load is drawing only "
                            f"{amps * 1000:.1f} mA — effectively open circuit",
                    "wind_ok": False, "unload_ok": False}
        if spinning:
            return {"level": "ok", "text": f"loaded, {amps * 1000:.0f} mA",
                    "wind_ok": True, "unload_ok": False}
        if on:
            return {"level": "ok", "text": "load on, fan stopped — safe to wind up",
                    "wind_ok": True, "unload_ok": True}
        return {"level": "warn", "text": "load OFF — turn it on before the wind",
                "wind_ok": False, "unload_ok": True}

    def load_on(self):
        if self.load is None:
            raise RuntimeError(self.load_error or "no load connected")
        # The startup default is 0.0 A, so "Load ON" alone used to put the
        # Chroma in constant current at 0.000 A — on, reporting safe, and
        # electrically an open circuit. Never arm below the floor.
        amps = max(float(self.load_demand), self.LOAD_FLOOR_A)
        with self._load_lock:
            self.load.set_mode_cc(amps, range_="low", verify=False)
            self.load.on()
        self.load_demand = amps
        self.log(f"load ON at {amps * 1000:.1f} mA", "ok")

    def load_off(self):
        """Refuses while the rotor may be turning. That is the whole point."""
        if self.load is None:
            raise RuntimeError(self.load_error or "no load connected")
        if not self.interlock_state()["unload_ok"]:
            raise RuntimeError(
                "refusing to switch the load off while the fan is turning — "
                "an unloaded rotor in moving air accelerates until something "
                "mechanical stops it. Wind down first.")
        with self._load_lock:
            self.load.off()
        self.log("load OFF", "ok")

    def set_load_amps(self, amps):
        if self.load is None:
            raise RuntimeError(self.load_error or "no load connected")
        amps = max(0.0, min(float(amps), 2.0))
        spinning = bool(self.running or self.last.get("hz", 0.0) > 5.0)
        if spinning and amps < self.LOAD_FLOOR_A:
            raise RuntimeError(
                f"refusing {amps * 1000:.1f} mA while the fan is turning — "
                f"below {self.LOAD_FLOOR_A * 1000:.0f} mA the rotor is "
                f"effectively open-circuit. Wind down first.")
        with self._load_lock:
            self.load.set_mode_cc(amps, range_="low", verify=False)
        self.load_demand = amps
        return amps

    # ══════════════════════════════════════════════════════════════════
    # BLADE SWEEP
    # ══════════════════════════════════════════════════════════════════

    def start_blade_sweep(self, blade, notes="", start_rpm=500, stop_rpm=1800,
                          rpm_step=100, step_amps=0.02, dwell=1.0,
                          stop_power_frac=0.80, max_amps=0.8):
        """
        The campaign, run from the dashboard, using the same `find_peak` the
        CLI uses. Progress is published for live plotting rather than only
        written at the end.
        """
        self._guard("start a blade sweep")
        if self.load is None:
            raise RuntimeError(self.load_error or "no load connected")
        if not blade:
            raise RuntimeError("a blade name is required — an unlabelled "
                               "curve is not a measurement")

        from peak_finder import find_peak
        lock = self._load_lock

        class _Serialised:
            """
            The load, with every call serialised against the poll thread.

            find_peak drives the instrument continuously for the length of a
            ramp. Wrapping it here rather than locking inside find_peak keeps
            the measurement code identical to the CLI's, which is the whole
            reason the dashboard and `blade_sweep.py` produce the same numbers.
            """
            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                attr = getattr(self._inner, name)
                if not callable(attr):
                    return attr

                def wrapped(*a, **k):
                    with lock:
                        return attr(*a, **k)
                return wrapped

        rpms = list(range(int(start_rpm), int(stop_rpm) + 1, int(rpm_step)))
        cal = self.cfg.calibration

        def wind(r):
            try:
                return round(float(cal.velocity(r)), 2)
            except Exception:
                return None

        # ── the protocol fingerprint ────────────────────────────────────
        # Blades are compared against each other, so a curve only means
        # something alongside the settings that produced it. The CLI hashes
        # them; the dashboard used to hash nothing, which made a dashboard
        # curve incomparable with every CLI curve AND with itself. Built from
        # the same field list as load_ramp.protocol_meta, with `via` set so a
        # dashboard run can never be mistaken for a CLI one — its ladder and
        # settle really are different.
        import hashlib
        shape = (f"via=dashboard;scaling=v2;step={step_amps:.5f};frac=0.0000;"
                 f"dwell={dwell:.2f};voff=0.500;range=low;floor=0.00200;"
                 f"operate={stop_power_frac * 100:.1f};collapse=0.700;confirm=2")
        fingerprint = hashlib.sha256(shape.encode()).hexdigest()[:12]

        # Canonical name, NOT stamped. `_sweep_summary()` in app.py joins the
        # blade library on exactly `sweep_<blade>_summary.csv`; adding a
        # timestamp made every dashboard sweep invisible to the Blades tab —
        # a regression my own round-1 persistence fix introduced. The stamped
        # copy is kept alongside so a re-run does not destroy the previous one.
        stamp = time.strftime("%Y%m%d_%H%M%S")
        logs = Path(self.cfg.path).resolve().parent.parent / "logs"
        out = logs / f"sweep_{blade}"
        self._sweep_archive = logs / f"sweep_{blade}_{stamp}"

        self.sweep = {"blade": blade, "notes": notes, "state": "running",
                      "rpms": rpms, "i": 0, "n": len(rpms), "points": [],
                      "ramp": [], "current_rpm": None, "message": "",
                      "protocol": fingerprint, "protocol_detail": shape,
                      "summary_csv": str(out) + "_summary.csv",
                      "points_csv": str(out) + "_points.csv"}

        def work():
            sw = self.sweep
            try:
                self.load_on()
                time.sleep(0.4)
                for n, rpm in enumerate(rpms, 1):
                    # Checked at EVERY point, not only at the start. E-stop
                    # latches self.estopped and stops the drive — but this
                    # thread used to sail on and call drive.start() at the
                    # next wind speed, restarting a 15 HP fan seconds after
                    # somebody hit the button. Four of five reviewers found
                    # this independently; it is the worst defect in the file.
                    if self.estopped:
                        sw["message"] = "ABORTED — E-STOP latched"
                        break
                    if sw.get("abort"):
                        sw["message"] = "aborted"
                        break

                    # The soft limit and the REMOTE check apply to every other
                    # path that can move the fan (_guard, set_setpoint). A
                    # sweep is not exempt from them.
                    limit = self.cfg.hz_limit
                    if limit and rpm > float(limit):
                        sw["message"] = (f"refused {rpm} rpm — above the "
                                         f"{limit:g} rpm soft limit")
                        break

                    sw.update(i=n, current_rpm=rpm, ramp=[])
                    if self.should_stop():
                        sw["message"] = "aborted"
                        break
                    with self._lock:
                        if self.estopped:
                            sw["message"] = "ABORTED — E-STOP latched"
                            break
                        self.drive.set_hz(rpm)
                        if not self.running:
                            self.drive.start(rpm)
                            self.running = True
                    self.target_hz = rpm
                    time.sleep(max(2.0, dwell * 2))

                    frac = (wind(rpm) or 1) / (wind(stop_rpm) or 1)
                    step = max(0.002, step_amps * frac ** 2)
                    ceiling = max(4 * step, max_amps * frac ** 2)

                    def _watch(_st, _sw=sw):
                        if self.should_stop() or _sw.get("abort"):
                            raise _SweepStopped(
                                "E-STOP latched" if self.estopped else "stopped")

                    r = find_peak(
                        _Serialised(self.load), max_amps=ceiling, floor_amps=0.002,
                        min_step=step, step_frac=0.0, dwell=dwell,
                        operate_frac=0.0, v_floor=0.5, range_="low",
                        stop_power_frac=stop_power_frac,
                        on_step=lambda st: (_watch(st), sw["ramp"].append(
                            {"a": round(st.amps, 5), "v": round(st.volts, 4),
                             "w": round(st.watts, 5)})))
                    sw["points"].append({
                        "rpm": rpm, "mps": wind(rpm),
                        "p_w": round(r.fit_watts, 5),
                        "i_a": round(r.fit_amps, 5),
                        "p_raw": round(r.power_peak_watts, 5),
                        "limited_by": r.limited_by, "clean": bool(r.clean),
                        "steps": len(r.trace)})
                    # Flushed as each point completes, not at the end: a sweep
                    # is 10-30 minutes of fan and load time, and an abort or a
                    # crash at point 9 must not discard points 1-8.
                    self._write_sweep(sw, r)
                    # NOT 0 A. The CLI protocol unloads to zero between wind
                    # points, but there the fan is stepped immediately; here
                    # the rotor sits at the new, HIGHER wind speed for 2+ s
                    # before find_peak re-loads it. Zero amps in constant
                    # current is an open circuit, so that is 2 s of runaway at
                    # every one of 14 points, each faster than the last.
                    with self._load_lock:
                        self.load.set_mode_cc(self.LOAD_FLOOR_A, range_="low",
                                              verify=False)
                    self.load_demand = self.LOAD_FLOOR_A
                else:
                    sw["message"] = "complete"
            except _SweepStopped as e:
                sw["message"] = f"stopped mid-ramp — {e}"
                self.log(f"blade sweep stopped: {e}", "warn")
            except Exception as e:
                sw["message"] = f"failed: {e}"
                self.log(f"blade sweep failed: {e}", "fault")
            finally:
                # Fan first, then the load — and the load is left ON at a
                # small floor, never switched off, because the rotor may still
                # be spinning down. That asymmetry is deliberate: an energised
                # load is a nuisance, a spinning open-circuit rotor is broken
                # hardware.
                try:
                    with self._lock:
                        self.drive.stop()
                    self.running = False
                    self.target_hz = 0.0
                except Exception as e:
                    self.log(f"could not stop the fan after the sweep: {e}",
                             "fault")
                try:
                    with self._load_lock:
                        self.load.set_mode_cc(0.002, range_="low", verify=False)
                except Exception:
                    pass
                sw["state"] = "done"
                self.log(f"blade sweep {sw.get('message', 'ended')} — "
                         f"{len(sw['points'])} points", "ok")

        self._job_thread = threading.Thread(target=work, daemon=True,
                                            name="blade-sweep")
        self._job_thread.start()
        return self.sweep

    def _write_sweep(self, sw, last=None):
        """Rewrite both CSVs from scratch. Small files; atomicity beats speed."""
        import csv as _csv
        try:
            head = [("blade", sw["blade"]), ("notes", sw["notes"]),
                    ("via", "dashboard"),
                    ("instrument", getattr(self.load, "identity", "?")),
                    ("protocol", sw["protocol"]),
                    ("protocol_detail", sw["protocol_detail"]),
                    ("clock", time.strftime("%Y-%m-%dT%H:%M:%S%z")),
                    ("_note", "Written by the dashboard. The `via=dashboard` "
                              "field is inside the fingerprint, so these runs "
                              "are deliberately NOT comparable with CLI "
                              "blade_sweep.py curves - the ladder and settle "
                              "differ.")]
            sp = Path(sw["summary_csv"])
            sp.parent.mkdir(parents=True, exist_ok=True)
            with sp.open("w", newline="") as f:
                w = _csv.writer(f)
                for k, v in head:
                    w.writerow([f"# {k}", v])
                w.writerow(["fan_rpm_cmd", "wind_mps", "blade", "p_max_fit_w",
                            "i_at_pmax_fit_a", "p_max_raw_w", "limited_by",
                            "clean", "steps"])
                for p in sw["points"]:
                    w.writerow([p["rpm"], p["mps"], sw["blade"], p["p_w"],
                                p["i_a"], p["p_raw"], p["limited_by"],
                                int(p["clean"]), p["steps"]])
            if last is not None:
                pp = Path(sw["points_csv"])
                new = not pp.exists()
                with pp.open("a", newline="") as f:
                    w = _csv.writer(f)
                    if new:
                        for k, v in head:
                            w.writerow([f"# {k}", v])
                        w.writerow(["t_unix", "fan_rpm", "wind_mps", "blade",
                                    "demand_a", "volts", "amps", "watts",
                                    "tracking", "note"])
                    for st in last.trace:
                        w.writerow([f"{st.t_unix:.3f}", sw["current_rpm"],
                                    sw["points"][-1]["mps"], sw["blade"],
                                    f"{st.demand_a:.5f}", f"{st.volts:.4f}",
                                    f"{st.amps:.5f}", f"{st.watts:.5f}",
                                    int(st.tracking), st.note])
            # archive copy, so re-running a blade keeps the earlier curve
            arch = getattr(self, "_sweep_archive", None)
            if arch is not None:
                import shutil
                shutil.copy2(sp, str(arch) + "_summary.csv")
        except Exception as e:
            self.log(f"could not write the sweep to disk: {e}", "fault")
            sw["write_error"] = str(e)

    def abort_blade_sweep(self):
        if self.sweep and self.sweep.get("state") == "running":
            self.sweep["abort"] = True
            return True
        return False

    def snapshot(self):
        """
        Everything the dashboard renders, in one dict.

        This is the UI contract: adding a key is safe, renaming one breaks the
        frontend silently. Sent on every SSE tick, so keep it small -- the
        telemetry ring buffer is fetched separately.
        """
        st = self.last.get("status", {})
        cal = self.cfg.calibration
        return {
            "connected": self.connected,
            "dry_run": self.dry_run,
            "estopped": self.estopped,
            "running": self.running,
            "measured": self.describe(self.last.get("hz", 0.0)),
            "target": self.describe(self.target_hz),
            "amps": self.last.get("amps", 0.0),
            "status_bits": {k: v for k, v in st.items() if k != "_raw"},
            "status_raw": st.get("_raw", 0),
            "hz_limit": self.cfg.hz_limit,
            "ref1_max": getattr(self.drive, "ref1_max_hz", 60.0),
            "tau": self.cfg.tau,
            "tau_down": self.cfg.get("tau_down"),
            "calibration": {
                "status": self.cfg.get("calibration_status", "none"),
                "units": cal.units if cal else None,
                "rpm_per_hz": cal.rpm_per_hz if cal else None,
                "coeffs": cal.coeffs.tolist() if cal else None,
                "r2": cal.r2 if cal else None,
            } if cal else None,
            "ambient": self.cfg.ambient(),
            "session": self.cfg.get("session"),
            "velocity_source": self.vsource.describe() if self.vsource else None,
            "job": {k: v for k, v in (self._job or {}).items()
                    if k not in ("spec", "diagnostics")} if self._job else None,
            "events": list(self.events)[:12],
            "ref_unit": self.ref_unit,
            "load": ({"connected": True,
                      "identity": getattr(self.load, "identity", None),
                      "on": self.load_last.get("on", False),
                      "volts": round(self.load_last.get("volts", 0.0), 4),
                      "amps": round(self.load_last.get("amps", 0.0), 5),
                      "watts": round(self.load_last.get("watts", 0.0), 5),
                      "demand": round(self.load_demand, 5)}
                     if self.load is not None else
                     {"connected": False, "error": self.load_error}),
            "interlock": self.interlock_state(),
            # Age of the newest reading. A frozen panel and a live one looked
            # identical: on a dropped stream every indicator held its last
            # value with nothing to say it had stopped updating.
            "age_s": round(time.time() - (self.last.get("t") or 0), 2)
                     if self.last.get("t") else None,
            "load_age_s": round(time.time() - (self.load_last.get("t") or 0), 2)
                          if self.load_last.get("t") else None,
            "load_error": self.load_error,
            "server_time": round(time.time(), 3),
            "sweep": ({k: v for k, v in self.sweep.items() if k != "abort"}
                      if self.sweep else None),
        }
