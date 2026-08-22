"""
chroma_load.py — Chroma 63004-150-60 DC electronic load, over SCPI.

The load is two things at once, and it is worth being clear about both:

  1. **The turbine's brake.** How much current it draws sets the turbine's
     operating point — which is what makes a Cp(λ) curve possible at all.
  2. **Your best electrical instrument.** Its V and I readings are better than
     anything on the DAQ, and with remote sense they are better than anything
     you could measure at the DAQ's terminals.

═══════════════════════════════════════════════════════════════════════════
THE INTERLOCK — READ THIS BEFORE USING IT
═══════════════════════════════════════════════════════════════════════════
**With the load OFF, the turbine sees an open circuit and runs away.**

A Chroma in the off state presents hundreds of kΩ. An unloaded turbine in
moving air has almost nothing opposing it, so it accelerates until something
mechanical stops it — a bearing, a blade root, or the blade leaving the hub.
On a printed SLA rotor that is a real outcome, not a theoretical one.

Therefore the sequence is not negotiable:

    load ON   →  wind UP    →  test  →  wind DOWN  →  load OFF

and never the reverse at either end. `TurbineInterlock` below enforces it, and
`safe_shutdown()` unwinds it in the right order even from an exception.

This belongs in the orchestrator rather than in either instrument's driver,
because neither the drive nor the load can see the other. That is exactly the
kind of coupling that gets forgotten when two subsystems are built in
separate conversations.

═══════════════════════════════════════════════════════════════════════════
MODES
═══════════════════════════════════════════════════════════════════════════
    CC   constant current      the usual choice for sweeping a turbine
    CR   constant resistance   closest to a physical resistor bank; stable
                               near stall where CC can stall the rotor
    CV   constant voltage      rarely what you want here
    CP   constant power        deliberately not exposed — commanding constant
                               power from a source whose available power you
                               are trying to *measure* is a positive feedback
                               loop into stall

Remote sense matters more than it looks. In CR mode the load computes
resistance from the sense terminals, so bad sense means it regulates to the
wrong thing rather than merely reporting wrong. Land the sense leads at the
rectifier output, not at the load's binding posts.
"""

from __future__ import annotations

import socket
import time


class LoadError(RuntimeError):
    pass


# ═══════════════════════════════════════════════════════════════════════════
# THE RATED ENVELOPE — 63004-150-60
# ═══════════════════════════════════════════════════════════════════════════
#
# Three numbers, and they are corner limits that CANNOT be had at once:
#
#     150 V      only below ~2.7 A   (400 / 150)
#      60 A      only below ~6.7 V   (400 / 60)
#     400 W      the binding constraint everywhere in between
#
# So "80% of peak" is ambiguous until you say peak of what. 80% of 60 A is
# 48 A, which is inside the current rating and 6x outside the power rating at
# any voltage a turbine produces. Whenever a percentage is used here it is a
# percentage of an explicitly named quantity.
#
# ── ranges, MEASURED not assumed ──
# Taken off the instrument on 2026-08-19 by demanding a value that is certainly
# too large and bisecting what it refused. Worth doing rather than assuming a
# decade convention: the model number says 60 A and the LOW range stops at 2 A,
# which is not a tenth of anything.
#
# Pick the smallest range that covers the demand. A turbine making 1.5 A read
# on the 60 A range is being measured with resolution it does not deserve, and
# the error that introduces lands directly in Cp.
CC_FULL_SCALE = {"low": 2.0, "mid": 6.0, "high": 60.0}          # amps
CR_FULL_SCALE = {"low": 250.0, "mid": 1250.0, "high": 2500.0}   # ohms

RATINGS = {
    "volts": 150.0, "amps": 60.0, "watts": 400.0,
    "amps_low": CC_FULL_SCALE["low"], "amps_mid": CC_FULL_SCALE["mid"],
}

# An out-of-range demand is REFUSED — 2,"Data Range Error" — not clamped.
# Confirmed on this unit. That means check_errors() is a real guard here, but
# the setpoint then holds its PREVIOUS value, which is the thing that will
# quietly poison a log. Reading it back is what catches that.


# ═══════════════════════════════════════════════════════════════════════════
# TRANSPORTS
# ═══════════════════════════════════════════════════════════════════════════
#
# SCPI is the same over every link; only the byte pipe differs. Instruments
# expose USB as one of two entirely different things and the distinction is
# not cosmetic:
#
#   USB-TMC   Test & Measurement Class. Enumerates as /dev/usbtmc0 on Linux,
#             or is reached through VISA. A message-based protocol with its
#             own framing — you cannot just write bytes at it.
#   USB-CDC   A serial bridge. Enumerates as /dev/ttyACM0 or /dev/ttyUSB0 and
#             behaves like any other serial port.
#
# Which one a given Chroma presents depends on the model and the fitted
# option, so `discover()` below finds out rather than assuming.


class ScpiTransport:
    """A line-oriented SCPI pipe. Subclasses supply the bytes."""

    kind = "base"

    def open(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def write(self, cmd):
        raise NotImplementedError

    def read(self):
        raise NotImplementedError

    def query(self, cmd):
        self.write(cmd)
        return self.read()


class TcpTransport(ScpiTransport):
    """
    SCPI over TCP — the Ethernet option, port 5025 by convention.

    **Not available on this rig's instrument.** The 63004-150-60 in the lab has
    the GPIB/LAN slot blanked off; USB Type B is its only digital interface.
    Kept because a second load, or a fitted option card, would use it.
    """

    kind = "tcp"

    def __init__(self, host, port=5025, timeout=5.0):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock = None

    def open(self):
        self.sock = socket.create_connection((self.host, self.port),
                                             timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        return self

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None

    def write(self, cmd):
        if self.sock is None:
            raise LoadError("not connected")
        self.sock.sendall((cmd + "\n").encode())

    def read(self):
        buf = b""
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            buf += chunk
            if buf.endswith(b"\n"):
                break
        return buf.decode(errors="ignore").strip()

    def describe(self):
        return f"tcp://{self.host}:{self.port}"


class SerialTransport(ScpiTransport):
    """
    SCPI over a serial port — RS-232, or USB presenting as CDC.

    Chroma's RS-232 defaults vary by model; 9600 8N1 is the usual starting
    point but check the manual. If `*IDN?` comes back garbled rather than
    empty, the baud rate is wrong.
    """

    kind = "serial"

    def __init__(self, port, baudrate=9600, timeout=3.0,
                 parity="N", stopbits=1, bytesize=8):
        self.port, self.baudrate, self.timeout = port, baudrate, timeout
        self.parity, self.stopbits, self.bytesize = parity, stopbits, bytesize
        self.ser = None

    def open(self):
        import serial
        self.ser = serial.Serial(
            self.port, self.baudrate, timeout=self.timeout,
            parity=self.parity, stopbits=self.stopbits,
            bytesize=self.bytesize)
        self.ser.reset_input_buffer()
        return self

    def close(self):
        if self.ser:
            self.ser.close()
            self.ser = None

    def write(self, cmd):
        if self.ser is None:
            raise LoadError("not connected")
        self.ser.reset_input_buffer()
        self.ser.write((cmd + "\n").encode())

    def read(self):
        return self.ser.readline().decode(errors="ignore").strip()

    def describe(self):
        return f"serial://{self.port}@{self.baudrate}"


class VisaTransport(ScpiTransport):
    """
    SCPI through VISA — the route for USB-TMC, and also works for TCP and GPIB.

    Needs `pyvisa` plus a backend. `pyvisa-py` is the pure-Python one and is
    usually enough for USB-TMC on Linux:

        pip install pyvisa pyvisa-py pyusb

    On Linux a udev rule is generally required to reach the device without
    root — see `docs/06_chroma.md`.
    """

    kind = "visa"

    def __init__(self, resource, timeout=5.0):
        self.resource, self.timeout = resource, timeout
        self.inst = None

    @staticmethod
    def _normalise(r):
        """A resource string with the instrument's padding taken out."""
        return r.replace("\x00", "").strip().upper()

    def _resolve(self, rm):
        """
        Find the live resource that corresponds to the configured one.

        This exists because of a specific, silent trap. The Chroma pads its
        serial-number field with NULs, so the resource VISA actually reports is

            USB0::2665::2176::630041501113\x00\x00::0::INSTR

        Those NULs cannot be written into a JSON config and read back
        dependably, so `probe_load.py` strips them — and the stripped string
        then does not match any device, because the padding is part of the
        identifier. Recording what the probe printed left a config that could
        not open the instrument it had just been talking to.

        Matching on the NUL-stripped form fixes it in both directions, and has
        the side benefit of surviving a backend that pads differently or a
        USB0/USB1 renumber after a replug.
        """
        available = list(rm.list_resources())
        if self.resource in available:
            return self.resource

        want = self._normalise(self.resource)
        hits = [r for r in available if self._normalise(r) == want]
        if len(hits) == 1:
            return hits[0]

        # Last resort: the serial number is the part that identifies the
        # instrument; the bus numbering around it is not stable across replugs.
        serial = [f for f in want.split("::") if f.isdigit() and len(f) > 8]
        if serial:
            hits = [r for r in available
                    if serial[-1] in self._normalise(r)]
            if len(hits) == 1:
                return hits[0]

        raise LoadError(
            f"no VISA device matches {self.resource!r}.\n  Visible right now: "
            + (", ".join(repr(r) for r in available) or "(nothing)")
            + "\n  Re-run `python src/probe_load.py` if the instrument moved.")

    def open(self):
        import pyvisa
        rm = pyvisa.ResourceManager()
        self.resource = self._resolve(rm)
        self.inst = rm.open_resource(self.resource)
        self.inst.timeout = int(self.timeout * 1000)
        return self

    def close(self):
        if self.inst:
            self.inst.close()
            self.inst = None

    def write(self, cmd):
        self.inst.write(cmd)

    def read(self):
        return self.inst.read().strip()

    def query(self, cmd):
        return self.inst.query(cmd).strip()

    def describe(self):
        return self.resource


class UsbTmcTransport(ScpiTransport):
    """
    Raw USB-TMC through the Linux kernel driver at /dev/usbtmcN.

    **The likely path for this rig** — the load's only digital interface is a
    USB Type B device port. Whether it presents as TMC (here) or CDC (a serial
    port) is a property of the instrument's firmware, so run
    `src/probe_load.py` rather than assuming.

    No dependencies at all, which makes it the least fragile option when it
    works. It only exists on Linux, and only if the kernel bound usbtmc to the
    device.
    """

    kind = "usbtmc"

    def __init__(self, path="/dev/usbtmc0", timeout=5.0):
        self.path, self.timeout = path, timeout
        self.fd = None

    def open(self):
        self.fd = open(self.path, "r+b", buffering=0)
        return self

    def close(self):
        if self.fd:
            self.fd.close()
            self.fd = None

    def write(self, cmd):
        self.fd.write((cmd + "\n").encode())

    def read(self):
        return self.fd.read(4096).decode(errors="ignore").strip()

    def describe(self):
        return self.path


def discover(hints=None, verbose=True):
    """
    Find the load, whatever it is plugged into.

    Tries, in order of how little can go wrong: the kernel usbtmc node, serial
    ports that look like an instrument, VISA resources, then TCP if a host was
    given. Returns a list of (transport, idn) for everything that answered
    `*IDN?` with something Chroma-shaped.

    Run this once when you plug the instrument in. It tells you which
    transport to record in `tunnel.json` so nobody has to rediscover it.
    """
    found = []
    hints = hints or {}

    def try_it(t):
        try:
            t.open()
            idn = t.query("*IDN?")
            if idn:
                if verbose:
                    mark = "chroma" in idn.lower()
                    print(f"  {'✓' if mark else '?'} {t.describe():<34} {idn}")
                found.append((t, idn))
                return
        except Exception as e:
            if verbose and hints.get("show_failures"):
                print(f"  ·   {t.describe():<34} {type(e).__name__}: {e}")
        try:
            t.close()
        except Exception:
            pass

    if verbose:
        print("scanning for the load...")

    import glob
    import sys as _sys

    # Device naming is per-platform, and getting this wrong means the scan
    # silently finds nothing on a machine where the instrument is plugged in
    # and working.
    #
    #   Linux   USB-TMC → /dev/usbtmc0 (kernel driver)
    #           USB-CDC → /dev/ttyACM0, /dev/ttyUSB0
    #   macOS   USB-TMC → no kernel driver at all; VISA only
    #           USB-CDC → /dev/cu.usbmodem*, /dev/cu.usbserial*
    #   Windows → COM ports, and VISA for TMC
    if _sys.platform == "darwin":
        tmc_nodes = []
        serial_ports = sorted(glob.glob("/dev/cu.usbmodem*")
                              + glob.glob("/dev/cu.usbserial*"))
    elif _sys.platform.startswith("win"):
        tmc_nodes = []
        serial_ports = [f"COM{i}" for i in range(1, 21)]
    else:
        tmc_nodes = sorted(glob.glob("/dev/usbtmc*"))
        serial_ports = sorted(glob.glob("/dev/ttyACM*")
                              + glob.glob("/dev/ttyUSB*"))

    # Don't interrogate a port we already know is something else — sending
    # *IDN? at the PMC would just confuse both ends.
    skip = set(hints.get("skip_ports") or [])
    serial_ports = [p for p in serial_ports if p not in skip]

    for node in tmc_nodes:
        try_it(UsbTmcTransport(node))

    for port in serial_ports:
        for baud in (hints.get("baud"), 115200, 9600, 38400):
            if baud is None:
                continue
            t = SerialTransport(port, baudrate=baud, timeout=1.0)
            before = len(found)
            try_it(t)
            if len(found) > before:
                break

    try:
        import pyvisa
        for res in pyvisa.ResourceManager().list_resources():
            if res.startswith(("USB", "TCPIP", "GPIB")):
                try_it(VisaTransport(res))
    except Exception:
        if verbose:
            print("  ·   pyvisa not installed — skipping VISA scan")
            if _sys.platform == "darwin":
                print("        On macOS there is no kernel USB-TMC driver, so "
                      "VISA is the only\n        route for a TMC instrument:  "
                      "pip install pyvisa pyvisa-py pyusb")

    if hints.get("host"):
        try_it(TcpTransport(hints["host"], hints.get("port", 5025), timeout=2))

    if verbose and not found:
        print("  nothing answered *IDN?. Check the instrument is powered, that "
              "it is\n  not in Local lockout, and that the cable is a DATA "
              "cable rather than\n  a charge-only one.")
    return found


def build_transport(spec):
    """
    Construct the transport described by config.

        {"kind": "usbtmc", "path": "/dev/usbtmc0"}
        {"kind": "serial", "port": "/dev/ttyACM0", "baudrate": 9600}
        {"kind": "visa",   "resource": "USB0::0x1698::...::INSTR"}
        {"kind": "tcp",    "host": "192.168.1.50"}
    """
    spec = dict(spec)
    kind = spec.pop("kind", "tcp")
    cls = {"tcp": TcpTransport, "serial": SerialTransport,
           "visa": VisaTransport, "usbtmc": UsbTmcTransport}.get(kind)
    if cls is None:
        raise LoadError(f"unknown load transport {kind!r}")

    # tunnel.json's `load` block carries more than the transport needs — the
    # model, the serial, `_note`, the alternatives probe_load found. Passing
    # those straight through as kwargs is a TypeError, which is a silly way
    # for a config file to fail. Keep what the constructor accepts.
    import inspect
    accepted = set(inspect.signature(cls).parameters)
    return cls(**{k: v for k, v in spec.items() if k in accepted})


class ChromaLoad:
    """
    Transport-agnostic SCPI driver.

        ChromaLoad(TcpTransport("192.168.1.50"))
        ChromaLoad(SerialTransport("/dev/ttyACM0"))
        ChromaLoad.from_config({"kind": "usbtmc", "path": "/dev/usbtmc0"})

    Every state-changing method checks the error queue afterwards. SCPI
    instruments accept malformed commands silently and queue the complaint, so
    a driver that never reads the queue will report success while the load
    ignores everything it was told.

    ── SCPI syntax needs verifying against YOUR manual ──
    The command strings below follow Chroma 63000-series conventions, but
    mnemonics differ across models and firmware revisions. `verify_commands()`
    exercises each one and reports which the instrument actually accepted —
    run it once, before trusting a sweep.
    """

    def __init__(self, transport, channel=1, timeout=5.0):
        self.t = transport
        self.channel = channel
        self.timeout = timeout
        self._on = False
        self.identity = None

    @classmethod
    def from_config(cls, spec, channel=1):
        return cls(build_transport(spec), channel=channel)

    # ── transport ────────────────────────────────────────────────────────

    def connect(self):
        self.t.open()
        idn = self.query("*IDN?")
        if "chroma" not in idn.lower():
            raise LoadError(f"unexpected instrument on {self.t.describe()}: "
                            f"{idn!r}")
        self.identity = idn
        self.write("*CLS")
        self.write(f"CHAN {self.channel}")
        return self

    def close(self):
        """Leaves the load ON if the turbine may still be spinning."""
        self.t.close()

    def write(self, cmd):
        self.t.write(cmd)

    def query(self, cmd):
        return self.t.query(cmd)

    def check_errors(self):
        """
        Drain the SCPI error queue.

        Bounded, because an instrument in a bad state can queue errors faster
        than you drain them and an unbounded loop here would hang the run.
        """
        errs = []
        for _ in range(10):
            e = self.query("SYST:ERR?")
            if not e or e.startswith("0,") or "no error" in e.lower():
                break
            errs.append(e)
        if errs:
            raise LoadError("; ".join(errs))

    # ── measurement ──────────────────────────────────────────────────────

    def measure(self):
        """
        (volts, amps, watts) at the sense terminals.

        Power is computed from the instrument's own V and I rather than read
        separately, so the three numbers are consistent with each other even
        if they were sampled microseconds apart.
        """
        v = float(self.query("MEAS:VOLT?"))
        i = float(self.query("MEAS:CURR?"))
        return v, i, v * i

    # ── state ────────────────────────────────────────────────────────────

    @property
    def is_on(self):
        return self._on

    def read_mode(self):
        """`MODE?` — what the instrument thinks it is doing. None if unreadable."""
        try:
            return (self.query("MODE?") or "").strip().upper() or None
        except Exception:
            return None

    def read_setpoint(self, kind="curr"):
        """
        Read back the demand the instrument is actually holding.

        The error queue catches a *rejected* command. It does not catch a
        command that parsed, was accepted, and did something other than what
        you meant — a wrong range, a clamped value, a channel that was never
        selected. Reading the number back is the only thing that does.

        Returns None if the readback mnemonic is not supported, so callers can
        tell "it disagrees" apart from "I could not ask".
        """
        q = {"curr": "CURR:STAT:L1?", "res": "RES:STAT:L1?"}[kind]
        try:
            return float(self.query(q))
        except Exception:
            return None

    def _confirm_setpoint(self, kind, wanted, tol_frac=0.02, tol_abs=1e-3):
        """Compare readback to demand. Raises on disagreement; None if unasked."""
        got = self.read_setpoint(kind)
        if got is None:
            return None
        if abs(got - wanted) > max(tol_abs, tol_frac * abs(wanted)):
            raise LoadError(
                f"setpoint readback disagrees: asked for {wanted:g}, the "
                f"instrument is holding {got:g}. Check the range — a demand "
                f"above the active range is clamped, not refused.")
        return got

    @staticmethod
    def pick_range(value, scales):
        """Smallest range that covers `value`. Raises if nothing does."""
        for name in ("low", "mid", "high"):
            if value <= scales[name]:
                return name
        raise LoadError(f"{value:g} is above every range (max "
                        f"{scales['high']:g})")

    def _mode_token(self, prefix, range_):
        r = str(range_).lower()
        tok = {"low": "L", "l": "L", "mid": "M", "m": "M", "middle": "M",
               "high": "H", "h": "H"}.get(r)
        if tok is None:
            raise LoadError(f"unknown range {range_!r} — low, mid or high")
        return prefix + tok

    def set_mode_cc(self, amps, range_="high", verify=True):
        """
        Constant current. The usual sweep variable for a turbine.

        `range_` is low / mid / high — 2 A, 6 A, 60 A on this unit. It is not
        cosmetic: a turbine making a couple of amps measured on the 60 A range
        is being read with resolution it does not deserve, and that error
        lands straight in Cp.

        A demand above the active range is refused with 2,"Data Range Error",
        so `check_errors()` catches it. What it does NOT undo is that the
        setpoint then keeps its previous value — the instrument is now holding
        a number nobody asked for. `verify` reads it back for exactly that.
        """
        self.write("MODE " + self._mode_token("CC", range_))
        self.write(f"CURR:STAT:L1 {float(amps):.4f}")
        self.check_errors()
        if verify:
            self._confirm_setpoint("curr", float(amps))

    def set_mode_cr(self, ohms, range_="high", verify=True):
        """
        Constant resistance — the closest analogue to a physical resistor bank,
        and better behaved than CC near stall, where a fixed current demand can
        drag the rotor to a stop rather than finding an operating point.
        """
        self.write("MODE " + self._mode_token("CR", range_))
        self.write(f"RES:STAT:L1 {float(ohms):.4f}")
        self.check_errors()
        if verify:
            self._confirm_setpoint("res", float(ohms))

    def on(self):
        self.write("LOAD ON")
        self.check_errors()
        self._on = True

    def off(self):
        """
        Turn the load off.

        Only safe when the turbine is stopped. Use TurbineInterlock rather than
        calling this directly during a test.
        """
        self.write("LOAD OFF")
        self._on = False

    def verify_commands(self, verbose=True):
        """
        Check every SCPI command this driver uses against the instrument.

        **Run this once before trusting a sweep.** The mnemonics below follow
        Chroma 63000-series conventions, but they differ across models and
        firmware revisions — and a load that silently ignores `MODE CRH` will
        sit in whatever mode it was already in while your log records the
        resistance you thought you set. That is a whole afternoon of data that
        looks fine and is not.

        Read-only commands are issued for real. State-changing ones are sent
        with harmless values, with the load OFF, and the error queue is read
        after each. Returns a list of (command, ok, detail).
        """
        if self._on:
            raise LoadError("turn the load off before verifying commands")

        checks = [
            ("*IDN?",            "query",  None),
            ("SYST:ERR?",        "query",  None),
            ("MEAS:VOLT?",       "query",  None),
            ("MEAS:CURR?",       "query",  None),
            ("MEAS:POW?",        "query",  "power readback"),
            ("MODE CRH",         "write",  "constant resistance, high range"),
            ("RES:STAT:L1 100",  "write",  "set resistance"),
            ("RES:STAT:L1?",     "query",  "resistance SETPOINT readback"),
            ("MODE CCH",         "write",  "constant current, high range"),
            ("CURR:STAT:L1 0.5", "write",  "set current"),
            ("CURR:STAT:L1?",    "query",  "current SETPOINT readback"),
            ("MODE CCL",         "write",  "constant current, low range"),
            ("MODE?",            "query",  "active mode readback"),
            ("CONF:VOLT:RANG?",  "query",  "voltage range readback"),
            ("LOAD?",            "query",  "load on/off state"),
            ("MODE CCM",         "write",  "constant current, mid range"),
            # The real protective settings on this model. The :PROT: tree does
            # not exist here — see protection() — so these are what there is.
            ("CONF:VOLT:OFF?",   "query",  "load-off voltage"),
            ("CONF:VOLT:ON?",    "query",  "load-on voltage"),
            ("CONF:VOLT:LATC?",  "query",  "Von/Voff latch"),
            ("SPEC:TEST?",       "query",  "go/no-go spec test state"),
        ]

        results = []
        for cmd, kind, note in checks:
            try:
                self.write("*CLS")
                if kind == "query":
                    reply = self.query(cmd)
                    ok = bool(reply)
                    detail = reply if ok else "no reply"
                else:
                    self.write(cmd)
                    time.sleep(0.05)
                    err = self.query("SYST:ERR?")
                    ok = err.startswith("0,") or "no error" in err.lower()
                    detail = "accepted" if ok else err
            except Exception as e:
                ok, detail = False, f"{type(e).__name__}: {e}"
            results.append((cmd, ok, detail))
            if verbose:
                print(f"  {'ok  ' if ok else 'FAIL'} {cmd:<20} {detail}"
                      + (f"   ({note})" if note and not ok else ""))

        if verbose:
            bad = [c for c, ok, _ in results if not ok]
            if bad:
                print(f"\n  {len(bad)} command(s) rejected. Find the right "
                      f"mnemonics in the\n  programming manual for this model "
                      f"and update chroma_load.py before\n  running a sweep — "
                      f"a silently-ignored mode command produces data\n  that "
                      f"looks correct and is not.")
            else:
                print("\n  every command accepted — the driver matches this "
                      "instrument")

            readbacks = [c for c, ok, _ in results
                         if c.endswith("STAT:L1?") and not ok]
            if readbacks:
                print("\n  NOTE  the setpoint readbacks failed. Everything "
                      "else can pass and the\n        load can still be "
                      "holding a value other than the one you sent —\n"
                      "        a demand above the active range is clamped, "
                      "not refused. Find\n        the right query mnemonic "
                      "before running an unattended sweep.")

            print("\n  This proves the instrument PARSES what the driver "
                  "sends. It does not\n  prove the load sinks current — "
                  "every check above ran with LOAD OFF.\n  For that, put a "
                  "source on it:  python src/load_ramp.py --peak-amps ...")
        return results

    def protection(self, max_volts=None, max_amps=None, max_watts=None):
        """
        Ask for instrument-level limits, and report what actually took.

        **On this unit, nothing does.** 63004-150-60 firmware 2.01 answers
        every `:PROT:` mnemonic with 3,"Command Error" — VOLT:PROT:HIGH,
        CURR:PROT:LEV, CONF:CURR:PROT, SOUR:CURR:PROT and the rest were all
        tried against the instrument on 2026-08-19 and all were rejected.
        There is no programmable OVP/OCP/OPP on this model.

        That is worth knowing rather than working around, because the previous
        version of this method sent the commands and called `check_errors()`,
        so any caller asking for protection got a LoadError instead of the
        limits — and a caller that swallowed it got neither.

        What you have instead:

          · **the envelope, enforced in software.** Whatever is driving the
            load has to keep V×I under 400 W itself. `load_ramp.py` does.
          · **CONF:VOLT:OFF**, the load-off voltage — genuinely programmable,
            and the one real protective setting on the instrument. Below it
            the load stops sinking. It is at 3.00 V as shipped.
          · **the front panel**, for anything else.

        Returns {"applied": {...}, "unsupported": [...]} rather than raising,
        so a caller can decide whether it can proceed without them.
        """
        applied, unsupported = {}, []
        for name, value, cmd in (
                ("max_volts", max_volts, "VOLT:PROT:HIGH {:.2f}"),
                ("max_amps", max_amps, "CURR:PROT:HIGH {:.3f}"),
                ("max_watts", max_watts, "POW:PROT:HIGH {:.1f}")):
            if not value:
                continue
            self.write("*CLS")
            self.write(cmd.format(float(value)))
            err = self.query("SYST:ERR?")
            if err.startswith("0,") or "no error" in err.lower():
                applied[name] = float(value)
            else:
                unsupported.append(name)
        return {"applied": applied, "unsupported": unsupported}

    # ── the load-off voltage: the one protective setting that IS settable ──

    def volt_off(self, volts=None):
        """
        Get or set CONF:VOLT:OFF — the terminal voltage below which the load
        stops sinking.

        On a turbine this is the difference between a load that lets go
        gracefully as the rotor slows and one that holds a current demand into
        a collapsing source. Shipped at 3.00 V.
        """
        if volts is None:
            try:
                return float(self.query("CONF:VOLT:OFF?"))
            except Exception:
                return None
        self.write(f"CONF:VOLT:OFF {float(volts):.2f}")
        self.check_errors()
        return float(volts)


# ═══════════════════════════════════════════════════════════════════════════
# THE INTERLOCK
# ═══════════════════════════════════════════════════════════════════════════

class TurbineInterlock:
    """
    Enforces load-before-wind and wind-before-load-off.

    Wraps a drive and a load, and refuses any ordering that would leave a
    spinning turbine open-circuit. Use it as a context manager:

        with TurbineInterlock(drive, load, min_amps=0.2) as rig:
            rig.wind_up(25.0)             # load already on, verified
            ...
            rig.wind_down()               # waits for the fan to stop
        # load switched off here, in the right order, even on an exception

    The `min_amps` check is the part that catches the real failure. `LOAD ON`
    with a setpoint of zero amps is electrically almost the same as off, and
    an instrument that reports its output as enabled while drawing nothing
    tells you nothing about whether the turbine is actually loaded.
    """

    def __init__(self, drive, load, min_amps=0.1, spindown_timeout=180):
        self.drive, self.load = drive, load
        self.min_amps = min_amps
        self.spindown_timeout = spindown_timeout
        self._armed = False

    def __enter__(self):
        return self.arm()

    def __exit__(self, *exc):
        self.safe_shutdown()
        return False

    def arm(self, initial_amps=None):
        """Load on and verified before the fan is allowed to turn."""
        if initial_amps is not None:
            self.load.set_mode_cc(initial_amps)
        self.load.on()
        time.sleep(0.5)
        self._armed = True
        return self

    def verify_loaded(self):
        """
        Is the turbine actually loaded right now?

        Returns (ok, reason). Only meaningful while the turbine is turning —
        at zero wind it legitimately draws nothing.
        """
        if not self.load.is_on:
            return False, "the load is switched off"
        _, amps, _ = self.load.measure()
        if amps < self.min_amps:
            return False, (f"load reports {amps:.3f} A, below the "
                           f"{self.min_amps} A floor — the turbine is "
                           f"effectively open-circuit")
        return True, f"{amps:.2f} A"

    def wind_up(self, hz):
        """Bring the fan up. Refuses if the load is not on."""
        if not self._armed or not self.load.is_on:
            raise LoadError(
                "refusing to start the fan with the load off — an unloaded "
                "turbine in moving air accelerates until something mechanical "
                "stops it. Call arm() first.")
        self.drive.start(hz)
        return hz

    def set_hz(self, hz):
        if not self.load.is_on:
            raise LoadError("load went off while the fan is running — stopping")
        return self.drive.set_hz(hz)

    def wind_down(self):
        """
        Ramp the fan down and wait for it to actually stop.

        Waiting matters: the load must stay on through the whole spin-down,
        and the drive reaching zero commanded frequency is not the same as
        the rotor having stopped.
        """
        self.drive.stop()
        t0 = time.monotonic()
        while time.monotonic() - t0 < self.spindown_timeout:
            if self.drive.actuals()[0] <= 0.5:
                return True
            time.sleep(0.5)
        return False

    def safe_shutdown(self):
        """
        Unwind in the correct order, whatever went wrong.

        Fan first, then the load — and if the fan cannot be confirmed stopped,
        **the load stays on.** Leaving a load energised is a nuisance;
        leaving a spinning turbine open-circuit breaks hardware.
        """
        stopped = False
        try:
            stopped = self.wind_down()
        except Exception as e:
            print(f"  wind-down failed ({e}) — leaving the load ON")
            return False

        if not stopped:
            print("  fan did not reach zero within the timeout — leaving the "
                  "load ON deliberately. Confirm the rotor has stopped, then "
                  "switch the load off by hand.")
            return False

        try:
            self.load.off()
        except Exception as e:
            print(f"  could not switch the load off: {e}")
        self._armed = False
        return True
