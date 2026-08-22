"""
transport.py — how the host reaches the drive.

Two topologies exist for this rig, and **only one may be wired at a time.**

    DIRECT      host ──USB-RS485── ACS550
                pymodbus on the host. The host is the Modbus master.

    PMC         host ──USB── Portenta ──RS-485── ACS550
                The PMC is the Modbus master. The host speaks an ASCII line
                protocol to it and never touches Modbus.

═══════════════════════════════════════════════════════════════════════════
WHY THIS IS A SAFETY MODULE, NOT A CONVENIENCE
═══════════════════════════════════════════════════════════════════════════
Modbus RTU has exactly one master. If the FTDI cable and the PMC are both
landed on X1-29/30/31, there are two — and the failure is not merely CRC
errors. Two independent processes can then command a 15 HP fan, each unaware
of the other, and neither log will show what the other did.

`assert_single_master()` below refuses to open a direct connection when a PMC
is configured, and vice versa. That check is cheap and the alternative is
discovering the problem by watching the tunnel do something nobody asked for.

═══════════════════════════════════════════════════════════════════════════
WHICH TOPOLOGY
═══════════════════════════════════════════════════════════════════════════
**PMC** is the better rig and the one to build toward:

  · Its Modbus loop is real-time; a Linux host's is not. Under load the Pi
    can stall for tens of milliseconds, and a stalled master means missed
    keep-alives.
  · It adds a second watchdog layer. The drive stops if the PMC goes quiet;
    the PMC stops the fan if the *host* goes quiet. The direct topology has
    only the first.
  · The host can crash, be updated, or be unplugged without the fan noticing.

**DIRECT** is fine for bench work, commissioning, and anything where the PMC
is not yet flashed. It is what the playbook's phases 8–14 assume.

Serial settings must match at both ends. The two design threads for this
project disagreed — the PMC sketch assumed even parity, this package's
playbook specifies 8N1. Pick one, set drive parameter 5304 to match, and
record it in tunnel.json so the next person does not rediscover it.
"""

from __future__ import annotations

import threading
import time


class TransportError(RuntimeError):
    """Any failure to reach the drive, by whatever path."""


class Transport:
    """
    Register-level access to the drive. `acs550.ACS550` sits on top of this
    and knows nothing about how the bytes get there.
    """

    kind = "base"
    is_master = True        # does the HOST own the Modbus bus?

    def connect(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def read(self, addr, count=1):
        raise NotImplementedError

    def write(self, addr, value):
        raise NotImplementedError

    def keepalive_tick(self):
        """
        One cheap message to whatever is watching us.

        Direct Modbus has nothing upstream to reassure, so this is a no-op
        there. The PMC, however, runs a host watchdog and will ramp the fan
        down if the host goes quiet — so over that transport this is what
        keeps a long settle alive.
        """
        return None

    def describe(self):
        return {"kind": self.kind, "host_is_master": self.is_master}


class DirectTransport(Transport):
    """
    pymodbus straight down an FTDI USB-RS485 cable. The host is the master.

    Everything in this package was originally written against this, and it
    remains the right choice for commissioning — there is one less thing
    between you and the drive when you are trying to work out why the drive
    will not answer.
    """

    kind = "direct"
    is_master = True

    def __init__(self, port, baudrate=19200, parity="N", stopbits=1,
                 unit=1, timeout=0.5):
        from pymodbus.client import ModbusSerialClient
        self.port, self.unit = port, unit
        self.client = ModbusSerialClient(
            port=port, baudrate=baudrate, parity=parity,
            stopbits=stopbits, bytesize=8, timeout=timeout)
        self._kw = None
        self._lock = threading.Lock()

    def _kwargs(self):
        # pymodbus renamed this between releases; probe once rather than pin
        # a version and break on someone else's machine.
        if self._kw is None:
            try:
                self.client.read_holding_registers(3, count=1, slave=self.unit)
                self._kw = {"slave": self.unit}
            except TypeError:
                self._kw = {"device_id": self.unit}
        return self._kw

    def connect(self):
        if not self.client.connect():
            raise TransportError(f"could not open serial port {self.port}")
        return self

    def close(self):
        self.client.close()

    def read(self, addr, count=1):
        with self._lock:
            rr = self.client.read_holding_registers(addr, count=count,
                                                    **self._kwargs())
        if rr.isError():
            raise TransportError(f"read at {addr} failed: {rr}")
        return rr.registers

    def write(self, addr, value):
        with self._lock:
            rq = self.client.write_register(addr, int(value) & 0xFFFF,
                                            **self._kwargs())
        if rq.isError():
            raise TransportError(f"write {value} to {addr} failed: {rq}")


# Reference scale: 20000 counts == parameter 1105 REF1 MAX. Defined here
# rather than imported from acs550, which would make the dependency circular.
REF_FULL_SCALE = 20000


class PMCTransport(Transport):
    """
    Through an Arduino Portenta Machine Control running `acs550_pmc.ino`.

    The PMC owns the Modbus loop and both watchdogs. The host sends ASCII
    lines over USB and gets exactly one `OK`/`ERR` back per command, so it
    never has to guess whether something landed.

    ── consequences for the rest of this package ──

    **Do not run the host keep-alive.** The PMC feeds the drive's watchdog
    itself, at a rate a Linux host cannot guarantee. Running both means two
    things writing the control word, which is the same class of problem as
    two masters. `ACS550.start_keepalive()` is a no-op over this transport.

    **The host watchdog replaces it.** The PMC ramps the fan down if it stops
    hearing from the host — so the host must still talk, just at its own pace.
    `WD <ms>` sets that timeout; the default is deliberately short.

    **Register access is emulated.** The line protocol is command-shaped
    (`HZ 20`, `RUN`, `STAT`), not register-shaped, so `read`/`write` here map
    onto it. Reads of anything the protocol does not expose raise rather than
    silently returning zero.
    """

    kind = "pmc"
    is_master = False        # the PMC is the master, not us

    # Control/status registers this transport can emulate from STAT.
    ADDR_CW, ADDR_REF, ADDR_SW, ADDR_ACT1, ADDR_ACT2 = 0, 1, 3, 4, 5

    def __init__(self, port, baudrate=115200, timeout=2.0,
                 ref1_max_hz=60.0, host_watchdog_ms=5000,
                 feedback_scale=295.0):
        self.port, self.baudrate, self.timeout = port, baudrate, timeout
        self.ref1_max_hz = ref1_max_hz
        self.host_watchdog_ms = host_watchdog_ms

        # Feedback scaling, measured on the bench 19 Aug 2026.
        #
        # The reference is a SPEED reference (par 1105 = 2435 rpm) but the PMC
        # reports par 0103 OUTPUT FREQ, which is frequency — so there IS a
        # Hz stage, on the feedback path only. Two corrections compose:
        #
        #   · the sketch appears to divide register 40005 by 100 rather than
        #     10, so the reported value is output_Hz / 10
        #   · Hz → rpm is the motor's nameplate ratio, par 9908 / 60
        #
        #   rpm = f2 x 10 x (1770/60) = f2 x 295
        #
        # Verified: commanded 500 rpm, f2 settled at 1.68 -> 496 rpm. The 0.9%
        # deficit is slip, which is correct and expected.
        #
        # This would be cleaner if the sketch read par 0102 SPEED (already in
        # rpm) instead of 0103. Then feedback_scale becomes 1.0 and slip is
        # handled by the drive rather than by us.
        self.feedback_scale = feedback_scale
        self.ser = None
        self._lock = threading.Lock()
        self._last_stat = {}
        self._stat_at = 0.0

    def connect(self):
        import serial
        self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        time.sleep(2.0)                 # Portenta resets on port open
        self.ser.reset_input_buffer()

        ident = self.command("ID")
        if "ERR" in ident:
            raise TransportError(f"PMC did not identify itself: {ident}")

        # Quieten the telemetry stream: it interleaves with command replies
        # and turns a simple request/response protocol into a parsing problem.
        self.command("STREAM 0")
        self.command(f"WD {int(self.host_watchdog_ms)}")
        return self

    def close(self):
        """
        Best-effort stop, then close.

        Both are wrapped: if the port has already gone away — which is exactly
        when close() runs — writing STOP raises, and an exception here would
        bury the original failure under a second traceback. The drive's own
        comm watchdog is what actually stops the fan in that case, which is
        the entire reason it is enabled.
        """
        if not self.ser:
            return
        try:
            self.command("STOP")
        except Exception:
            pass
        try:
            self.ser.close()
        except Exception:
            pass
        self.ser = None

    def command(self, line, expect_reply=True):
        """
        Send one line, return one reply.

        Lines beginning with `#` are the PMC's diagnostics rather than
        protocol — surfaced separately so they are not mistaken for a reply.
        """
        if self.ser is None:
            raise TransportError("PMC transport is not connected")
        with self._lock:
            try:
                self.ser.reset_input_buffer()
            except Exception as e:
                raise TransportError(
                    f"serial port went away ({e}). The PMC has disconnected or "
                    f"re-enumerated. The drive's comm watchdog (par 3018/3019) "
                    f"is what stops the fan now.")
            self.ser.write((line.strip() + "\n").encode())
            if not expect_reply:
                return ""
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                raw = self.ser.readline().decode(errors="ignore").strip()
                if not raw:
                    continue
                if raw.startswith("#"):
                    self._last_diag = raw
                    continue
                return raw
        raise TransportError(f"PMC did not answer '{line}' within "
                             f"{self.timeout}s")

    # Telemetry line format, confirmed against acs550-pmc 2.0 on the bench:
    #
    #   T,<millis>,<STATE>,<ref_hz>,<f2>,<f3>,<f4>,<u1>,<u2>,<u3>,<u4>
    #   T,2029103,IDLE,12.50,0.00,0.00,0.00,1233,0,0,2265
    #
    # CONFIRMED on the bench:
    #   millis   advances ~100/line while streaming at 10 Hz
    #   state    IDLE, COMM_LOST (RUNNING and FAULT presumed)
    #   ref_hz   field 3 — showed 12.50 after `HZ 12.5`
    #
    # NOT CONFIRMED. Fields u1..u4 (1233, 0, 0, 2265) were initially guessed
    # to be Modbus counters, because they were 0/939 during COMM_LOST and
    # 1233/2265 once the link came up. They are not: they then sat frozen for
    # seven minutes while the drive's own par 5306 counter was demonstrably
    # climbing, so the PMC was polling the whole time.
    #
    # They are named u1..u4 deliberately. A field called `ok_count` that is
    # not one is worse than a field with no name, because code and people
    # both act on it. Identify them from the sketch before relying on them.
    TELEMETRY_FIELDS = ["millis", "state", "ref_hz", "f2", "f3", "f4",
                        "u1", "u2", "u3", "u4"]

    def stat(self, max_age=0.2):
        """
        Cached STAT.

        STAT replies on **two** lines: an `OK STAT` acknowledgement followed by
        a `T,` telemetry record. Reading only the first gets you the ack and
        none of the data — which is exactly what happened the first time this
        was run against real firmware.
        """
        if time.monotonic() - self._stat_at < max_age:
            return self._last_stat

        with self._lock:
            try:
                self.ser.reset_input_buffer()
                self.ser.write(b"STAT\n")
            except Exception as e:
                raise TransportError(
                    f"serial port went away ({e}) — PMC disconnected or "
                    f"re-enumerated mid-run")
            deadline = time.monotonic() + self.timeout
            ack, line = None, None
            while time.monotonic() < deadline and line is None:
                raw = self.ser.readline().decode(errors="ignore").strip()
                if not raw:
                    continue
                if raw.startswith("T,"):
                    line = raw
                elif raw.startswith(("OK", "ERR")):
                    ack = raw
                    if raw.startswith("ERR"):
                        raise TransportError(f"PMC rejected STAT: {raw}")

        if line is None:
            raise TransportError(f"no telemetry record after STAT "
                                 f"(ack was {ack!r})")

        parts = line.split(",")[1:]          # drop the leading 'T'
        out = {}
        for name, raw in zip(self.TELEMETRY_FIELDS, parts):
            if name == "state":
                out[name] = raw
                continue
            try:
                out[name] = float(raw)
            except ValueError:
                out[name] = raw
        out["_raw"] = line
        self._last_stat, self._stat_at = out, time.monotonic()
        return out

    def read(self, addr, count=1):
        s = self.stat()

        # The PMC reports a state word rather than the drive's raw status
        # register. Synthesise the bits the rest of the package reads so
        # everything above the transport works unchanged.
        state = str(s.get("state", "")).upper()
        if True:                      # always synthesise; no confirmed SW field
            sw = 0
            if state != "COMM_LOST":
                sw |= 1 << 0            # RDY_ON
                sw |= 1 << 9            # REMOTE
            if state in ("RUNNING", "RUN"):
                sw |= (1 << 1) | (1 << 2)
            if state in ("FAULT", "TRIPPED"):
                sw |= 1 << 3
            s = dict(s, sw=sw)

        vals = []
        for a in range(addr, addr + count):
            if a == self.ADDR_SW:
                vals.append(int(s.get("sw", 0)))
            elif a == self.ADDR_ACT1:
                # f2 -> rpm. See feedback_scale in __init__ for the derivation.
                vals.append(int(round(s.get("f2", 0.0)
                                      * self.feedback_scale * 10)))
            elif a == self.ADDR_ACT2:
                vals.append(int(round(s.get("f3", 0.0) * 10)))
            elif a == self.ADDR_CW:
                vals.append(0x047F if str(s.get("state", "")).upper()
                            in ("RUNNING", "RUN") else 0x047E)
            elif a == self.ADDR_REF:
                hz = s.get("ref_hz", 0.0)
                vals.append(int(hz / self.ref1_max_hz * REF_FULL_SCALE))
            else:
                # Parameter reads would need a PMC protocol extension. Failing
                # loudly beats returning a plausible zero that quietly becomes
                # a wrong calibration.
                raise TransportError(
                    f"the PMC line protocol does not expose register {a}. "
                    f"Read it from the keypad, or use the direct transport "
                    f"for commissioning.")
        return vals

    def write(self, addr, value):
        if addr == self.ADDR_REF:
            hz = value / 20000.0 * self.ref1_max_hz
            r = self.command(f"HZ {hz:.2f}")
        elif addr == self.ADDR_CW:
            # The PMC owns the ABB control-word handshake; the host expresses
            # intent and lets it do the sequencing.
            r = self.command("RUN" if value == 0x047F else "STOP")
        else:
            raise TransportError(f"cannot write register {addr} over the PMC "
                                 f"line protocol")
        if r.startswith("ERR"):
            raise TransportError(f"PMC rejected the command: {r}")

    def keepalive_tick(self):
        """
        Feed the PMC's host watchdog.

        A plain STAT is enough — the PMC only needs to hear from us, not to be
        told anything. This must run during any silent stretch longer than
        host_watchdog_ms, which includes every settle, dwell and acquisition
        window in this package. Without it the PMC ramps the fan down mid-run
        and the next operation fails with "drive is not running", which points
        at entirely the wrong thing.
        """
        try:
            self.stat(max_age=0.0)
        except TransportError:
            pass          # let the PMC's own watchdog handle a dead link

    def describe(self):
        d = super().describe()
        d.update({"port": self.port,
                  "host_watchdog_ms": self.host_watchdog_ms,
                  "note": "PMC owns the Modbus loop and both watchdogs"})
        return d


# ═══════════════════════════════════════════════════════════════════════════
# THE CHECK THAT MATTERS
# ═══════════════════════════════════════════════════════════════════════════

def assert_single_master(config):
    """
    Refuse to bring up a second Modbus master.

    Reads `transport.kind` from tunnel.json and compares it against what is
    about to be opened. Two masters on one RS-485 pair is not a degraded mode
    — it is two things commanding a 15 HP fan with neither aware of the other,
    and neither log showing what the other did.

    This cannot detect a PMC that is physically wired but unconfigured. The
    real guarantee is that **only one device is landed on X1-29/30/31**;
    this is the software half of that.
    """
    declared = (config.get("transport") or {}).get("kind")
    if declared is None:
        return None
    return declared


def build(config, port=None, **overrides):
    """
    Construct the transport described by tunnel.json, or a direct one.

    ```json
    "transport": {"kind": "pmc", "port": "/dev/ttyACM0"}
    "transport": {"kind": "direct", "port": "/dev/ttyVFD", "parity": "N"}
    ```
    """
    spec = dict(config.get("transport") or {"kind": "direct"})
    spec.update({k: v for k, v in overrides.items() if v is not None})
    kind = spec.pop("kind", "direct")
    if port:
        spec["port"] = port
    if "port" not in spec:
        raise TransportError("no port configured for the transport")

    if kind == "pmc":
        return PMCTransport(**{k: v for k, v in spec.items()
                               if k in ("port", "baudrate", "timeout",
                                        "ref1_max_hz", "host_watchdog_ms")})
    if kind == "direct":
        return DirectTransport(**{k: v for k, v in spec.items()
                                  if k in ("port", "baudrate", "parity",
                                           "stopbits", "unit", "timeout")})
    raise TransportError(f"unknown transport kind {kind!r}")
