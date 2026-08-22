"""
simulator.py — a fake ACS550 that behaves like the real one.

Two uses:

  · **Dry run.** Rehearse a five-minute turbulence profile at real speed before
    committing a test session to it. You find the typo in the amplitude on the
    bench, not with a 15 HP fan spinning.
  · **Testing.** Everything in this package is exercised against this rather
    than against hardware nobody has at their desk.

═══════════════════════════════════════════════════════════════════════════
WHAT IT MODELS, AND WHY EACH PIECE IS THERE
═══════════════════════════════════════════════════════════════════════════
It is deliberately not a perfect drive. It reproduces the four behaviours that
actually bite:

1. **Ramp limiting.** The drive will not slew faster than par 2202/2203, so a
   profile that demands more gets silently clipped. If your dry run comes out
   flatter than you drew it, that is the reason, and it will do the same thing
   on the real tunnel.

2. **Asymmetric response.** Acceleration is limited by motor torque against fan
   inertia; deceleration is limited by how much regenerated energy the DC bus
   can absorb. Without a brake chopper, down is slower than up. The simulator
   uses separate time constants so a symmetric 1-cosine gust comes out
   *asymmetric*, which is what the real tunnel does.

3. **Dead time.** Roughly a hundred milliseconds between commanding and the
   flow beginning to move. Small next to τ, but it is the part that a
   first-order model gets wrong, and it matters for feedforward design.

4. **Measurement noise and quantization.** Actuals come back in tenths, with
   turbulence-like noise that scales with speed — matching the heteroscedastic
   behaviour in the March report.

The default constants are plausible for a 15 HP tunnel fan, **not measured
from yours.** Run `characterize` and pass the real numbers.
"""

from __future__ import annotations

import math
import threading
import time

import numpy as np

from acs550 import (ADDR_ACT1, ADDR_ACT2, ADDR_CW, ADDR_REF1, ADDR_SW,
                    CW_COAST, CW_READY, CW_RESET, CW_RUN, REF_FULL_SCALE,
                    SW_BITS, DriveError)


class SimulatedACS550:
    """
    Drop-in replacement for ACS550. Same public methods, no serial port.

    Args:
        tau_up / tau_down: flow time constants, seconds. Down should be the
                           larger of the two unless you have a brake chopper.
        dead_time:         transport delay from command to first response.
        accel / decel:     drive ramp times over the full frequency range,
                           i.e. par 2202 / 2203.
        noise:             turbulence noise as a fraction of output frequency.
        fault_at_hz:       trip on overcurrent above this, to exercise the
                           abort paths.
    """

    def __init__(self, ref1_max_hz=60.0, tau_up=3.0, tau_down=5.0,
                 dead_time=0.15, accel=10.0, decel=15.0, max_freq=60.0,
                 noise=0.004, seed=0, fault_at_hz=None, **_):
        self.ref1_max_hz = ref1_max_hz
        self.tau_up, self.tau_down = tau_up, tau_down
        self.dead_time = dead_time
        self.accel, self.decel = accel, decel
        self.max_freq = max_freq
        self.noise = noise
        self.fault_at_hz = fault_at_hz
        self.rng = np.random.default_rng(seed)

        self._lock = threading.Lock()
        self._cw = CW_READY
        self._ref_hz = 0.0
        self._ramp_hz = 0.0        # drive's internal ramp output
        self._flow_hz = 0.0        # what the flow has actually reached
        self._delay = []           # dead-time queue of (t, value)
        self._t_last = time.monotonic()
        self._faulted = False
        self._fault_code = 0
        self._keepalive = None
        self._stop_evt = threading.Event()
        self._counts_per_hz = REF_FULL_SCALE / ref1_max_hz
        self.port = "SIMULATED"
        self.writes = 0

    # ── physics ──────────────────────────────────────────────────────────

    def _advance(self):
        """Integrate forward to now. Called on every read or write."""
        now = time.monotonic()
        dt = now - self._t_last
        if dt <= 0:
            return
        self._t_last = now

        running = self._cw == CW_RUN and not self._faulted
        target = self._ref_hz if running else 0.0
        if self._cw == CW_COAST:
            target = 0.0

        # Drive ramp generator: par 2202/2203 are the time to traverse the
        # full range, not the time to reach your setpoint.
        rate_up = self.max_freq / self.accel
        rate_dn = self.max_freq / self.decel
        err = target - self._ramp_hz
        step = (rate_up if err > 0 else rate_dn) * dt
        self._ramp_hz += math.copysign(min(abs(err), step), err)

        # Transport delay. Interpolate the ramp history at (now - dead_time)
        # rather than popping a queue: _advance() is called whenever someone
        # reads or writes, which may be milliseconds or seconds apart, and a
        # pop-based delay line silently lags by the *call interval* instead of
        # by dead_time. That made the simulated flow never catch up at all
        # between sparse polls.
        self._delay.append((now, self._ramp_hz))
        while len(self._delay) > 2 and self._delay[1][0] <= now - self.dead_time:
            self._delay.pop(0)

        target_t = now - self.dead_time
        if len(self._delay) == 1 or target_t <= self._delay[0][0]:
            delayed = self._delay[0][1]
        else:
            (ta, va), (tb, vb) = self._delay[0], self._delay[1]
            if tb <= ta:
                delayed = vb
            else:
                frac = min(max((target_t - ta) / (tb - ta), 0.0), 1.0)
                delayed = va + frac * (vb - va)

        # Asymmetric first-order flow response.
        tau = self.tau_up if delayed > self._flow_hz else self.tau_down
        alpha = 1 - math.exp(-dt / tau) if tau > 0 else 1.0
        self._flow_hz += alpha * (delayed - self._flow_hz)

        if self.fault_at_hz and self._flow_hz > self.fault_at_hz:
            self._faulted = True
            self._fault_code = 1          # overcurrent

    def _measured(self):
        self._advance()
        f = self._flow_hz
        # Noise grows with speed — heteroscedastic, as the real tunnel is.
        f += self.rng.normal(0, self.noise * max(f, 1.0))
        f = round(max(f, 0.0), 1)         # drive reports tenths
        amps = round(2.0 + 0.55 * f + self.rng.normal(0, 0.3), 1)
        return f, amps

    # ── ACS550-compatible surface ────────────────────────────────────────

    # Low-level accessors so selftest.py can probe a simulated drive the same
    # way it probes a real one. Without these the self-test cannot be
    # rehearsed, which defeats the point of having a simulator.
    _slave_kw = "slave"

    def _read(self, addr, count=1):
        if addr == ADDR_SW:
            return [self.status()["_raw"]]
        if addr in (ADDR_ACT1, ADDR_ACT2):
            f, amps = self._measured()
            vals = [int(f * 10), int(amps * 10)]
            return vals[addr - ADDR_ACT1:addr - ADDR_ACT1 + count]
        if addr == ADDR_CW:
            return [self._cw]
        if addr == ADDR_REF1:
            return [int(self._ref_hz * self._counts_per_hz)]
        return [self.read_param(addr + 1)]

    def _write(self, addr, value):
        self.writes += 1

    def connect(self):
        self._t_last = time.monotonic()
        return self

    def close(self):
        pass

    def read_param(self, pnum):
        return {1105: int(self.ref1_max_hz * 10),
                1001: 10, 1103: 8, 5310: 103, 5311: 104,
                3018: 1, 3019: 30,
                2202: int(self.accel * 10), 2203: int(self.decel * 10),
                2008: int(self.max_freq * 10),
                401: self._fault_code,
                5306: 1000 + self.writes, 5307: 0, 5308: 0}.get(pnum, 0)

    def write_param(self, pnum, value):
        if pnum == 2202:
            self.accel = value / 10.0
        elif pnum == 2203:
            self.decel = value / 10.0

    def get_ramp_times(self):
        return self.accel, self.decel

    def set_ramp_times(self, accel_s, decel_s):
        self.accel, self.decel = accel_s, decel_s

    def status(self):
        self._advance()
        running = self._cw == CW_RUN and not self._faulted
        raw = 0
        bits = {"RDY_ON": True, "RDY_RUN": running, "RDY_REF": running,
                "TRIPPED": self._faulted, "OFF2_STA": True, "OFF3_STA": True,
                "SWC_ON_INHIB": False, "ALARM": False,
                "AT_SETPOINT": abs(self._flow_hz - self._ref_hz) < 0.3,
                "REMOTE": True, "ABOVE_LIMIT": False}
        for bit, name in SW_BITS:
            if bits.get(name):
                raw |= 1 << bit
        bits["_raw"] = raw
        return bits

    def actuals(self):
        return self._measured()

    def is_faulted(self):
        self._advance()
        return self._faulted

    def last_fault(self):
        return self._fault_code

    def comm_counters(self):
        return {"ok": 1000 + self.writes, "crc_err": 0, "uart_err": 0}

    def set_hz(self, hz):
        with self._lock:
            self._advance()
            hz = max(0.0, min(float(hz), self.ref1_max_hz))
            self._ref_hz = hz
            self.writes += 1
        return hz

    def set_hz_fast(self, hz):
        self.set_hz(hz)

    def start(self, hz=None):
        if hz is not None:
            self.set_hz(hz)
        with self._lock:
            self._advance()
            self._cw = CW_READY
            self._cw = CW_RUN

    def stop(self):
        with self._lock:
            self._advance()
            self._cw = CW_READY

    def coast(self):
        with self._lock:
            self._advance()
            self._cw = CW_COAST

    def reset_fault(self):
        with self._lock:
            self._faulted = False
            self._fault_code = 0
            self._cw = CW_READY

    def wait_until_stopped(self, threshold=0.5, timeout=180):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if self.actuals()[0] <= threshold:
                return True
            time.sleep(0.2)
        return False

    def start_keepalive(self, period=0.5):
        pass          # nothing to feed; there is no watchdog in here

    def stop_keepalive(self):
        pass

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        try:
            self.stop()
        except Exception:
            pass
        return False
