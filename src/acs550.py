"""
acs550.py — Modbus RTU driver for the ABB ACS550 on the Aerolab wind tunnel.

See docs/02_code.md for design rationale, PLAYBOOK.md
for the physical layer.

═══════════════════════════════════════════════════════════════════════════
WHY THE REGISTER NUMBERS LOOK WEIRD
═══════════════════════════════════════════════════════════════════════════
Modbus has two numbering schemes, off by one. ABB's manual says "holding
register 40001"; on the wire that is address 0. Always:

    wire_address = register_number − 40001

pymodbus wants the wire address, so every constant below is pre-converted.

The drive exposes two things through the same space:
  1. A fixed control/status block at 40001–40012
  2. Every parameter, at 4xxxx where xxxx is the parameter number.
     Parameter 1105 → register 41105 → wire address 1104. Hence `P − 1`.
"""

from __future__ import annotations

import struct
import threading
import time

from pymodbus.client import ModbusSerialClient


# ── register addresses (zero-based wire addresses) ────────────────────────
ADDR_CW = 0      # 40001 Control Word
ADDR_REF1 = 1      # 40002 Reference 1
ADDR_SW = 3      # 40004 Status Word
ADDR_ACT1 = 4      # 40005 Actual 1  (contents set by par 5310)
ADDR_ACT2 = 5      # 40006 Actual 2  (contents set by par 5311)


# ── control word, ABB Drives profile ──────────────────────────────────────
# A bitfield of latches, not a command code. The three OFF bits are active
# low: all must be held high to permit running, and dropping each one is a
# different flavour of stop.
#
#   bit 0  OFF1   1 = ready · 0 = ramp stop over par 2203
#   bit 1  OFF2   1 = ok    · 0 = coast, output gated off
#   bit 2  OFF3   1 = ok    · 0 = emergency ramp stop over par 2208
#   bit 3  RUN    1 = run   · 0 = hold at zero
#   bit 4  RAMP_OUT_ZERO   1 = normal
#   bit 5  RAMP_HOLD       1 = normal (0 freezes the ramp mid-accel)
#   bit 6  RAMP_IN_ZERO    1 = normal
#   bit 7  RESET  0→1 edge clears a fault
#   bit 10 REMOTE_CMD      1 = accept fieldbus control at all
#
# Forget bit 10 and every other bit is ignored while your writes still
# report success.
CW_READY = 0x047E
CW_RUN = 0x047F
CW_COAST = 0x047C
CW_EMG_STOP = 0x047A
CW_RESET = 0x04FE

SW_BITS = [
    (0, "RDY_ON"), (1, "RDY_RUN"), (2, "RDY_REF"), (3, "TRIPPED"),
    (4, "OFF2_STA"), (5, "OFF3_STA"), (6, "SWC_ON_INHIB"), (7, "ALARM"),
    (8, "AT_SETPOINT"), (9, "REMOTE"), (10, "ABOVE_LIMIT"),
]

REF_FULL_SCALE = 20000   # 20000 counts == parameter 1105 REF1 MAX


class DriveError(RuntimeError):
    """Failure to reach the drive, or the drive refusing a request."""


class ACS550:
    """
    Small wrapper around the drive's embedded fieldbus.

    Two properties the rest of the package depends on:

      · The object caches the last control word and reference it sent, so the
        keep-alive thread can retransmit without racing foreground code.
      · It is a context manager whose __exit__ always issues a stop. Normal
        return, exception, Ctrl-C — the fan ramps down. Don't restructure into
        bare connect/close without replicating that.
    """

    def __init__(self, port, baudrate=19200, parity="N", stopbits=1,
                 unit=1, timeout=0.5, ref1_max_hz=None, transport=None,
                 ref1_max_fallback=None, ref_unit="Hz"):
        self.unit = unit
        self.port = port
        self.baudrate = baudrate

        # A transport may be supplied — direct pymodbus, or the PMC line
        # protocol. When it is, this class stops owning the serial port and
        # becomes purely drive semantics on top of whatever pipe it is given.
        self.transport = transport
        self.client = None if transport is not None else ModbusSerialClient(
            port=port, baudrate=baudrate, parity=parity,
            stopbits=stopbits, bytesize=8, timeout=timeout,
        )
        self._slave_kw = None
        self._lock = threading.Lock()
        self._cw = CW_READY
        self._ref = 0
        self._keepalive = None
        self._stop_evt = threading.Event()
        self.ref1_max_hz = ref1_max_hz
        self._ref1_max_fallback = ref1_max_fallback
        self._ref_unit = ref_unit
        self._counts_per_hz = None      # precomputed for the fast path

    # ── transport ────────────────────────────────────────────────────────

    def _kw(self):
        """pymodbus renamed the unit-id kwarg across versions. Probe once."""
        if self._slave_kw is None:
            try:
                self.client.read_holding_registers(ADDR_SW, count=1,
                                                   slave=self.unit)
                self._slave_kw = "slave"
            except TypeError:
                self._slave_kw = "device_id"
        return {self._slave_kw: self.unit}

    def _read(self, addr, count=1):
        if self.transport is not None:
            try:
                return self.transport.read(addr, count=count)
            except Exception as e:
                raise DriveError(str(e))
        return self._read_direct(addr, count)

    def _read_direct(self, addr, count=1):
        """
        One read transaction. The lock is not optional: RS-485 is half duplex
        with a single master. If the keep-alive thread transmits while the
        foreground thread awaits a reply, the frames collide and you get CRC
        errors that look exactly like a wiring fault.
        """
        with self._lock:
            rr = self.client.read_holding_registers(addr, count=count, **self._kw())
        if rr.isError():
            raise DriveError(f"read at wire address {addr} failed: {rr}")
        return rr.registers

    def _write(self, addr, value):
        if self.transport is not None:
            try:
                return self.transport.write(addr, value)
            except Exception as e:
                raise DriveError(str(e))
        with self._lock:
            rq = self.client.write_register(addr, int(value) & 0xFFFF, **self._kw())
        if rq.isError():
            raise DriveError(f"write {value} to wire address {addr} failed: {rq}")

    def connect(self):
        """
        Open the port and learn the speed scaling.

        Reading 1105 rather than assuming 60 Hz matters: if someone changed it,
        a hardcoded assumption makes every commanded speed wrong with no error
        anywhere. Silent, plausible, and it contaminates results retroactively.

        The tenths heuristic handles ABB storing frequencies in 0.1 Hz units.
        If speeds ever come out 10× off, this is the line.
        """
        if self.transport is not None:
            self.transport.connect()
        elif not self.client.connect():
            raise DriveError(f"could not open serial port {self.port}")
        if self.ref1_max_hz is None:
            try:
                raw = self.read_param(1105)
                self.ref1_max_hz = raw / 10.0 if raw > 200 else float(raw)
            except DriveError:
                # The PMC line protocol is command-shaped, not register-shaped,
                # so it cannot serve arbitrary parameter reads. Fall back to
                # the configured value — and refuse to invent one, because an
                # unverified full scale is the silent-ratio-error that selftest
                # exists to catch.
                if self._ref1_max_fallback is None:
                    raise DriveError(
                        "cannot read par 1105 over this transport and no "
                        "ref1_max is configured. Read 1105 on the keypad and "
                        "put it in tunnel.json under drive_reference.ref1_max "
                        "— guessing it makes every commanded speed wrong by "
                        "that ratio, silently.")
                self.ref1_max_hz = float(self._ref1_max_fallback)
                print(f"  reference full scale: {self.ref1_max_hz:g} "
                      f"{self._ref_unit} (from config, par 1105 not readable "
                      f"over this transport)")
        self._counts_per_hz = REF_FULL_SCALE / self.ref1_max_hz
        return self

    def close(self):
        if self.transport is not None:
            self.transport.close()
        elif self.client:
            self.client.close()

    # ── parameters ───────────────────────────────────────────────────────

    def read_param(self, pnum):
        """Read any parameter by keypad number. drive.read_param(1105)."""
        return self._read(pnum - 1)[0]

    def write_param(self, pnum, value):
        """
        Write a parameter. This is the same as editing on the keypad — it
        persists across power cycles and there is no undo. The drive rejects
        writes to read-only parameters and to many parameters while running;
        both surface here as DriveError.
        """
        self._write(pnum - 1, value)

    def get_ramp_times(self):
        """
        Return (accel, decel) seconds from parameters 2202/2203.

        These are the time to traverse the full range 0 → par 2008 MAX FREQ,
        not the time to reach your setpoint. That is the single most common
        misreading of these parameters.
        """
        return (self.read_param(2202) / 10.0, self.read_param(2203) / 10.0)

    def set_ramp_times(self, accel_s, decel_s):
        """
        Set 2202/2203. Needed for gust work — at the shipped defaults the
        drive's own ramp generator smooths any gust into a gentle drift.

        Shorten with care and in steps:
          · Too-fast accel trips overcurrent against fan inertia.
          · Too-fast decel is worse. A decelerating fan pumps energy back into
            the DC bus and trips overvoltage. Without a brake chopper and
            resistor there is a hard floor on how fast you can slow down, and
            par 2005 OVERVOLT CTRL will silently stretch your ramp to avoid
            tripping — so the drive may simply not do what you asked.

        See docs/03_gusts.md.
        """
        self.write_param(2202, int(round(accel_s * 10)))
        self.write_param(2203, int(round(decel_s * 10)))

    # ── status ───────────────────────────────────────────────────────────

    def status(self):
        """
        Decode the status word into named booleans plus `_raw`.

        Worth reading rather than assuming a command worked. TRIPPED and
        SWC_ON_INHIB explain most "it will not start" situations, and REMOTE
        going clear means the keypad has taken control and the drive is
        ignoring you while writes still succeed.
        """
        sw = self._read(ADDR_SW)[0]
        flags = {name: bool(sw >> bit & 1) for bit, name in SW_BITS}
        flags["_raw"] = sw
        return flags

    def actuals(self):
        """
        (output_frequency_hz, motor_current_a) in one transaction.

        Assumes par 5310 = 103 and 5311 = 104. Verify on the keypad rather
        than trusting this docstring. Frequency is signed — negative is
        reverse — hence the struct reinterpretation. Both arrive in tenths.
        """
        act1, act2 = self._read(ADDR_ACT1, count=2)
        freq = struct.unpack(">h", struct.pack(">H", act1))[0] / 10.0
        return freq, act2 / 10.0

    def is_faulted(self):
        return self.status()["TRIPPED"]

    def last_fault(self):
        """Parameter 0401 holds the most recent fault code."""
        return self.read_param(401)

    def comm_counters(self):
        """
        Diagnostics for a bus that won't talk. Readable from the keypad too,
        which works even when Modbus doesn't.

          5306 OK climbing        → frames arriving and parsing; PC-side issue
          5307 CRC climbing       → noise, termination, or baud mismatch
          5308 UART climbing      → parity or framing mismatch
          all three at zero       → nothing physical getting through
        """
        return {"ok": self.read_param(5306),
                "crc_err": self.read_param(5307),
                "uart_err": self.read_param(5308)}

    # ── commands ─────────────────────────────────────────────────────────

    def set_hz(self, hz):
        """
        Set the speed reference. Clamped to [0, REF1 MAX] so the value we
        cache for the keep-alive matches what the drive actually holds.
        Returns the clamped value, so callers log what happened rather than
        what they asked for.
        """
        hz = max(0.0, min(float(hz), self.ref1_max_hz))
        self._ref = int(round(hz * self._counts_per_hz))
        self._write(ADDR_REF1, self._ref)
        return hz

    def set_hz_fast(self, hz):
        """
        Minimal-latency setpoint write for profile streaming.

        Identical to set_hz() minus the clamp bookkeeping — used by player.py
        where the profile has already been validated and clipped, and where
        every millisecond of transaction time eats into the update rate. At
        19200 baud one write round-trip is roughly 10 ms, so ~20 Hz is the
        practical ceiling; 38400 buys you double.

        Still updates the cached reference so the keep-alive stays coherent.
        """
        self._ref = int(hz * self._counts_per_hz)
        if self._ref < 0:
            self._ref = 0
        elif self._ref > REF_FULL_SCALE:
            self._ref = REF_FULL_SCALE
        self._write(ADDR_REF1, self._ref)

    def start(self, hz=None):
        """
        Reference first, then the two-step start.

        Order matters. Send RUN before the reference and the drive accelerates
        toward whatever setpoint the last session left in 40002. On a 15 HP fan
        that is a genuinely unpleasant surprise for anyone near the tunnel.

        The CW_READY → CW_RUN pass exists because the drive latches on the
        rising edge of bit 3. If the word already reads 0x047F from a session
        that died badly, rewriting 0x047F makes no edge and the drive sits idle
        while every write succeeds. Going through 0x047E guarantees the edge.
        """
        if hz is not None:
            self.set_hz(hz)
        elif self._ref == 0:
            self.set_hz(0)

        self._cw = CW_READY
        self._write(ADDR_CW, CW_READY)
        time.sleep(0.05)
        self._cw = CW_RUN
        self._write(ADDR_CW, CW_RUN)

    def stop(self):
        """Ramp down over par 2203. Not instant — on a fan it may be tens of seconds."""
        self._cw = CW_READY
        self._write(ADDR_CW, CW_READY)

    def coast(self):
        """
        Gate the output off and let the fan freewheel. De-energizes faster than
        stop() but the fan spins down aerodynamically for a long time. Not an
        emergency stop — that is the hardwired button, and it stays that way.
        """
        self._cw = CW_COAST
        self._write(ADDR_CW, CW_COAST)

    def reset_fault(self):
        """
        Clear a fault on the rising edge of bit 7. Find out why it faulted
        first — repeatedly resetting a drive that is protecting itself turns a
        $40 fault into a $4000 one.
        """
        self._write(ADDR_CW, CW_RESET)
        time.sleep(0.1)
        self._cw = CW_READY
        self._write(ADDR_CW, CW_READY)

    def wait_until_stopped(self, threshold=0.5, timeout=180):
        """Block until output frequency falls below threshold. Bounded."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if self.actuals()[0] <= threshold:
                return True
            time.sleep(0.5)
        return False

    # ── watchdog keep-alive ──────────────────────────────────────────────

    def start_keepalive(self, period=0.5):
        """
        Retransmit the cached control word and reference on a timer.

        Parameters 3018/3019 arm a watchdog in the drive: hear nothing for
        3019 seconds and it faults and stops the fan. That watchdog is the
        entire safety argument for running a 15 HP fan from a Pi — if Python
        hangs, the cable is kicked, or the board dies, the tunnel winds down
        on its own.

        The cost is that the master must keep talking during any stretch where
        foreground code is busy settling or acquiring. Hence a daemon thread.

        Not needed while player.py is streaming — that writes far faster than
        the watchdog period on its own — but harmless, and it covers the gaps
        between profile runs.
        """
        # Two different watchdogs, depending on the transport:
        #
        #   direct  we are the Modbus master, so we must re-send the control
        #           word and reference to feed the DRIVE's watchdog (3018/3019)
        #   PMC     the PMC feeds the drive itself, but runs its OWN host
        #           watchdog and ramps the fan down if WE go quiet. So the
        #           thread still runs — it just pings the PMC instead of
        #           writing control words, which would fight the PMC for the
        #           control word.
        #
        # Suppressing the thread entirely over the PMC transport — which is
        # what this used to do — meant any settle longer than the host
        # watchdog silently stopped the fan mid-run.
        if self._keepalive:
            return
        self._stop_evt.clear()

        def loop():
            # wait() returns True when set, so this exits promptly rather than
            # sleeping out the final period.
            delegated = (self.transport is not None
                         and not self.transport.is_master)
            while not self._stop_evt.wait(period):
                try:
                    if delegated:
                        self.transport.keepalive_tick()
                    else:
                        self._write(ADDR_CW, self._cw)
                        self._write(ADDR_REF1, self._ref)
                except DriveError:
                    # Deliberately swallowed. If the bus is broken we WANT the
                    # drive's watchdog to trip and stop the fan — that is more
                    # reliable than anything this process can do while it is
                    # the thing failing. Retrying hard would be trying to keep
                    # a 15 HP fan running using the subsystem that just died.
                    pass

        self._keepalive = threading.Thread(target=loop, daemon=True,
                                           name="acs550-keepalive")
        self._keepalive.start()

    def stop_keepalive(self):
        self._stop_evt.set()
        if self._keepalive:
            self._keepalive.join(timeout=2)
            self._keepalive = None

    # ── context manager ──────────────────────────────────────────────────

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        """
        Always attempt a stop on the way out. Wrapped in try/except because if
        we are unwinding from a comms failure the stop write fails too, and
        raising here would mask the original exception. If the write does fail,
        the drive's watchdog catches it. Returns False so exceptions propagate.
        """
        try:
            self.stop_keepalive()
            self.stop()
        except Exception:
            pass
        self.close()
        return False
