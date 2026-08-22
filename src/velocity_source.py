"""
velocity_source.py — live wind speed into the control loop.

Until now every velocity in this package was *derived* from drive frequency
through a static calibration, or typed in by hand. That is enough to command a
tunnel and not enough to trust it: air density moves ~10% across a lab day,
blockage changes whenever a model goes in, and neither shows up in a number
computed from Hz.

This is the abstraction that lets a real sensor feed the same interface,
whatever it is:

    ManualSource      operator types a reading (what you have today)
    DaqSource         an NI DAQ analog channel
    SerialSource      an anemometer that streams over a serial port
    SimulatedSource   derived from the simulator, for dry runs and tests

Everything downstream — the verify step, closed-loop control, the logged
velocity column — takes a VelocitySource and does not care which one.

═══════════════════════════════════════════════════════════════════════════
TWO THINGS THAT MATTER MORE THAN THE PLUMBING
═══════════════════════════════════════════════════════════════════════════

**Averaging.** Your March 16 data showed the anemometer resolving 24–44 Hz,
which is far more bandwidth than a control loop wants. Feeding raw samples to
a controller means chasing turbulence. Every source therefore averages over a
window, and the window is a declared property rather than an accident.

**Staleness.** A source that has stopped updating must say so. A closed-loop
controller integrating against a frozen reading will wind the fan up until
something stops it, and the reading will look perfectly plausible the whole
time. `read()` raises `StaleReading` rather than returning the last good value
forever.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class StaleReading(RuntimeError):
    """The source has not produced a fresh sample within its stale window."""


class VelocitySource:
    """Base class. Subclasses implement `_sample()` returning m/s."""

    name = "base"
    units = "m/s"

    def __init__(self, average_s=2.0, stale_after_s=10.0, poll_hz=5.0):
        self.average_s = average_s
        self.stale_after_s = stale_after_s
        self.poll_period = 1.0 / poll_hz
        self._buf = deque(maxlen=max(2, int(average_s * poll_hz)))
        self._last_ok = 0.0
        self._last_error = None
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self):
        if self._thread:
            return self
        self._stop.clear()

        def loop():
            while not self._stop.wait(self.poll_period):
                try:
                    v = float(self._sample())
                    with self._lock:
                        self._buf.append((time.monotonic(), v))
                        self._last_ok = time.monotonic()
                        self._last_error = None
                except Exception as e:
                    self._last_error = str(e)

        self._thread = threading.Thread(target=loop, daemon=True,
                                        name=f"vel-{self.name}")
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _sample(self):
        raise NotImplementedError

    # ── reading ──────────────────────────────────────────────────────────

    def read(self):
        """
        Averaged velocity in m/s.

        Raises StaleReading rather than returning a frozen value — a control
        loop integrating against a dead sensor is how a fan ends up somewhere
        nobody asked for, and the number looks fine right up until it doesn't.
        """
        with self._lock:
            now = time.monotonic()
            if not self._buf or now - self._last_ok > self.stale_after_s:
                raise StaleReading(
                    f"{self.name}: no fresh sample in "
                    f"{now - self._last_ok:.1f} s"
                    + (f" ({self._last_error})" if self._last_error else ""))
            cutoff = now - self.average_s
            vals = [v for t, v in self._buf if t >= cutoff] or \
                   [self._buf[-1][1]]
            return sum(vals) / len(vals)

    def read_or_none(self):
        try:
            return self.read()
        except StaleReading:
            return None

    @property
    def healthy(self):
        return self.read_or_none() is not None

    def describe(self):
        return {"name": self.name, "units": self.units,
                "average_s": self.average_s, "healthy": self.healthy,
                "last_error": self._last_error,
                "value": self.read_or_none()}


# ═══════════════════════════════════════════════════════════════════════════
# SENSOR CALIBRATION — voltage to velocity
# ═══════════════════════════════════════════════════════════════════════════

class SensorCalibration:
    """
    Volts → m/s for the anemometer. Separate from the drive calibration, and
    deliberately so: one describes the fan, the other describes the probe, and
    conflating them is how a swapped sensor silently corrupts a season of data.

    ── on the March 2 report ──
    That analysis proposed `m/s = 115*V + 1.5` while justifying the curvature
    in the data with a dynamic-pressure argument (ΔP ∝ u²), which implies
    u ∝ √V. Those two cannot both be right, and the report also names the
    sensor three different ways (cup, hot-wire, cup). Until that is settled,
    treat any coefficients here as provisional and record which form you used
    with the data — `form` is written into every export for exactly that
    reason.

        linear  : v = a·V + b        a linear-output sensor (cup, vane)
        sqrt    : v = a·√(V−b)       a pressure-based sensor (pitot + transducer)
        king    : v = ((V²−a)/b)^(1/n)   a hot wire, King's law
    """

    def __init__(self, a, b=0.0, form="linear", n=0.5, source="",
                 notes=""):
        self.a, self.b, self.form, self.n = a, b, form, n
        self.source, self.notes = source, notes

    def to_velocity(self, volts):
        """Convert a raw reading to velocity using this sensor's functional form."""
        v = float(volts)
        if self.form == "linear":
            return self.a * v + self.b
        if self.form == "sqrt":
            return self.a * (max(v - self.b, 0.0)) ** 0.5
        if self.form == "king":
            num = max(v * v - self.a, 0.0)
            return (num / self.b) ** (1.0 / self.n) if self.b else 0.0
        raise ValueError(f"unknown calibration form {self.form}")

    def to_dict(self):
        return {"a": self.a, "b": self.b, "form": self.form, "n": self.n,
                "source": self.source, "notes": self.notes}

    @classmethod
    def from_dict(cls, d):
        return cls(d["a"], d.get("b", 0.0), d.get("form", "linear"),
                   d.get("n", 0.5), d.get("source", ""), d.get("notes", ""))


# ═══════════════════════════════════════════════════════════════════════════
# BACKENDS
# ═══════════════════════════════════════════════════════════════════════════

class ManualSource(VelocitySource):
    """
    Operator types a reading. What the verify step uses today.

    Deliberately goes stale: a value typed twenty minutes ago is not a
    measurement of what the tunnel is doing now, and pretending otherwise is
    worse than having no source at all.

    Staleness is measured from **submission**, not from polling. The obvious
    implementation — a poll loop that keeps returning the stored value —
    refreshes its own timestamp on every tick and therefore never expires,
    which defeats the entire purpose of the class. `_sample()` refuses to
    return anything older than the stale window so the base class's freshness
    tracking works as intended.
    """

    name = "manual"

    def __init__(self, stale_after_s=120.0):
        super().__init__(average_s=0.1, stale_after_s=stale_after_s, poll_hz=2)
        self._value = None
        self._submitted_at = 0.0

    def submit(self, value):
        """Record an operator reading. Resets the staleness clock."""
        self._value = float(value)
        self._submitted_at = time.monotonic()
        with self._lock:
            self._buf.append((self._submitted_at, self._value))
            self._last_ok = self._submitted_at
        return self._value

    @property
    def age(self):
        return (time.monotonic() - self._submitted_at
                if self._value is not None else float("inf"))

    def _sample(self):
        if self._value is None:
            raise RuntimeError("no reading entered yet")
        if self.age > self.stale_after_s:
            raise RuntimeError(f"last reading is {self.age:.0f} s old")
        return self._value

    def describe(self):
        d = super().describe()
        d["age_s"] = round(self.age, 1) if self._value is not None else None
        return d


class SimulatedSource(VelocitySource):
    """
    Derives velocity from the simulated drive plus the drive calibration, with
    turbulence-like noise added.

    Exists so the closed-loop path can be exercised in a dry run. The optional
    `bias` lets you inject a calibration error — the loop should discover and
    report it, and a test that never sees a wrong calibration is not testing
    the interesting case.
    """

    name = "simulated"

    def __init__(self, drive, calibration, bias=1.0, noise=0.02, **kw):
        super().__init__(**kw)
        self.drive, self.cal = drive, calibration
        self.bias, self.noise = bias, noise
        import numpy as _np
        self._rng = _np.random.default_rng(0)

    def _sample(self):
        hz, _ = self.drive.actuals()
        v = float(self.cal.velocity(hz)) * self.bias
        return max(0.0, v + self._rng.normal(0, self.noise * max(v, 1.0)))


class DaqSource(VelocitySource):
    """
    NI DAQ analog input through nidaqmx.

    Reads a block of samples per poll and means them in the *voltage* domain
    before converting — which is correct for a linear calibration and only
    approximately right for a nonlinear one. With a sqrt or King's-law form,
    averaging voltage then converting is not the same as converting then
    averaging, and the difference grows with turbulence intensity. For a slow
    outer control loop that error is negligible; for published velocity
    statistics, convert sample by sample instead.
    """

    name = "nidaq"

    def __init__(self, channel, calibration: SensorCalibration,
                 rate=1000, samples=200, **kw):
        super().__init__(**kw)
        self.channel, self.cal = channel, calibration
        self.rate, self.samples = rate, samples
        self._task = None

    def start(self):
        import nidaqmx                      # optional dependency
        from nidaqmx.constants import AcquisitionType
        self._task = nidaqmx.Task()
        self._task.ai_channels.add_ai_voltage_chan(self.channel)
        self._task.timing.cfg_samp_clk_timing(
            rate=self.rate, sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=self.samples * 4)
        self._task.start()
        return super().start()

    def stop(self):
        super().stop()
        if self._task:
            try:
                self._task.stop()
                self._task.close()
            finally:
                self._task = None

    def _sample(self):
        data = self._task.read(number_of_samples_per_channel=self.samples)
        return self.cal.to_velocity(sum(data) / len(data))


class SerialSource(VelocitySource):
    """
    An anemometer that streams readings over a serial port.

    Expects one number per line. `scale` converts whatever it emits into m/s;
    `field` picks a column out of a comma- or space-separated line.
    """

    name = "serial"

    def __init__(self, port, baudrate=9600, scale=1.0, field=0, **kw):
        super().__init__(**kw)
        self.port, self.baudrate = port, baudrate
        self.scale, self.field = scale, field
        self._ser = None

    def start(self):
        import serial
        self._ser = serial.Serial(self.port, self.baudrate, timeout=1)
        self._ser.reset_input_buffer()
        return super().start()

    def stop(self):
        super().stop()
        if self._ser:
            self._ser.close()
            self._ser = None

    def _sample(self):
        # Drain to the newest line: a backlog means we would otherwise be
        # controlling against readings from seconds ago.
        line = None
        while self._ser.in_waiting:
            line = self._ser.readline()
        if line is None:
            line = self._ser.readline()
        parts = line.decode(errors="ignore").replace(",", " ").split()
        return float(parts[self.field]) * self.scale


def build_source(kind, **kw):
    """Factory used by the config and the dashboard."""
    return {"manual": ManualSource, "simulated": SimulatedSource,
            "nidaq": DaqSource, "serial": SerialSource}[kind](**kw)
