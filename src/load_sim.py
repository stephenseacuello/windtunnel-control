#!/usr/bin/env python3
"""
load_sim.py — a turbine that rolls over, and a Chroma that reports it.

Lets the peak-finder be developed, argued about and regression-tested without
wind, without a rotor, and without the chance of throwing a blade. It presents
exactly the interface `ChromaLoad` does, so the code under test is the code
that will run on the bench.

═══════════════════════════════════════════════════════════════════════════
WHAT IS AND IS NOT MODELLED
═══════════════════════════════════════════════════════════════════════════
This reproduces the *shape* the detector has to cope with. It is not a
prediction of your rotor, and no number that comes out of it belongs in a
report.

    V(I) = V_oc · sqrt(1 − I/I_stall)          per wind speed
    V_oc  ∝ v          (voltage follows rotor speed)
    I_stall ∝ v²       (threshold current follows torque)

which puts electrical power P = V·I at a maximum of

    I_peak = ⅔ · I_stall        V_peak = V_oc/√3       P ∝ v³

Two consequences fall out of that and both are real:

  · **peak power is at ⅔ of the stall current**, so a protocol that hunts for
    the current peak necessarily goes past the power peak to get there.
  · **80% of the stall threshold is past the power peak**, on the falling
    side. Worth knowing before it is described as an operating point.

The default constants are anchored on the only two numbers available — 4 W at
1800 rpm fan, and an assumed 12 V there. Change `volts_at_peak` the moment a
real open-circuit reading exists; it is the term everything else scales from.

The rotor's inertia is NOT modelled: each call returns the steady state for
the demand it is given. So this exercises the detector's logic and its
arithmetic, and it says nothing about whether your dwell time is long enough.
Only the real rotor answers that.
"""

from __future__ import annotations

import math
import random

# Drive-side calibration, from the handoff: the ACS550 commands rpm, not Hz.
V_PER_RPM, V_INTERCEPT = 0.02132, -0.424


def wind_mps(fan_rpm):
    """Tunnel wind speed from the drive's speed reference."""
    return V_PER_RPM * fan_rpm + V_INTERCEPT


class SimulatedTurbine:
    """
    Steady-state V(I) for a rotor + generator + rectifier, per wind speed.

    Anchored so that at `ref_rpm` the electrical power peaks at `peak_watts`
    with `volts_at_peak` across the terminals.
    """

    def __init__(self, peak_watts=4.0, volts_at_peak=12.0, ref_rpm=1800.0,
                 seed=1):
        self.ref_v = wind_mps(ref_rpm)
        # P_peak = V_oc · I_stall · (2/3)·√(1/3);  V_peak = V_oc/√3
        self.v_oc_ref = volts_at_peak * math.sqrt(3.0)
        self.i_stall_ref = peak_watts / (self.v_oc_ref * (2 / 3) *
                                         math.sqrt(1 / 3))
        self.fan_rpm = ref_rpm
        self._rng = random.Random(seed)

    # ── per wind speed ───────────────────────────────────────────────────

    @property
    def u(self):
        return wind_mps(self.fan_rpm) / self.ref_v

    @property
    def v_oc(self):
        return self.v_oc_ref * self.u

    @property
    def i_stall(self):
        return self.i_stall_ref * self.u ** 2

    def terminals(self, demand_a):
        """
        (volts, amps) the load would see holding `demand_a`.

        Above the threshold the rotor stalls: speed and voltage collapse and
        the load gets nothing, which is what a real one does — not a graceful
        reduced current.
        """
        if demand_a <= 0:
            return self.v_oc, 0.0
        if demand_a >= self.i_stall:
            return 0.0, 0.0
        v = self.v_oc * math.sqrt(max(0.0, 1.0 - demand_a / self.i_stall))
        return v, demand_a

    def noise(self, value, frac=0.004, floor=2e-4):
        return value + self._rng.gauss(0.0, max(floor, frac * abs(value)))


class SimulatedLoad:
    """
    A Chroma that is not there. Same surface as `ChromaLoad`.

    Reproduces the two behaviours that actually shape the caller's code:
      · setpoints quantise to 0.1 mA and are refused above the active range
      · below CONF:VOLT:OFF the load stops sinking, and the source recovers to
        open circuit — which reads as a sudden loss of tracking, not a zero
    """

    CC_FULL_SCALE = {"low": 2.0, "mid": 6.0, "high": 60.0}

    def __init__(self, turbine=None, volt_off=3.0):
        self.turbine = turbine or SimulatedTurbine()
        self.identity = "Chroma,63004-150-60,SIMULATED,2.01"
        self._on = False
        self._demand = 0.0
        self._range = "low"
        self._volt_off = volt_off

    # ── transport surface ────────────────────────────────────────────────

    def connect(self):
        return self

    def close(self):
        pass

    def write(self, cmd):
        pass

    def query(self, cmd):
        return {"LOAD?": "ON" if self._on else "OFF",
                "MODE?": "CC" + self._range[0].upper(),
                "CONF:VOLT:OFF?": f"{self._volt_off:.2f}"}.get(cmd, "0")

    def check_errors(self):
        pass

    # ── state ────────────────────────────────────────────────────────────

    @property
    def is_on(self):
        return self._on

    def on(self):
        self._on = True

    def off(self):
        self._on = False

    def read_mode(self):
        return "CC" + self._range[0].upper()

    def read_setpoint(self, kind="curr"):
        return self._demand if kind == "curr" else None

    def volt_off(self, volts=None):
        if volts is not None:
            self._volt_off = float(volts)
        return self._volt_off

    def protection(self, **kw):
        # The real instrument rejects all of these. Say so, don't pretend.
        return {"applied": {}, "unsupported": [k for k, v in kw.items() if v]}

    def set_mode_cc(self, amps, range_="low", verify=True):
        from chroma_load import LoadError
        if range_ not in self.CC_FULL_SCALE:
            range_ = "low"
        if amps > self.CC_FULL_SCALE[range_]:
            raise LoadError(f'2,"Data Range Error" — {amps:g} A is above the '
                            f'{range_} range ({self.CC_FULL_SCALE[range_]} A)')
        self._range = range_
        self._demand = round(float(amps), 4)      # 0.1 mA quantisation

    def set_mode_cr(self, ohms, range_="low", verify=True):
        raise NotImplementedError("the simulator is constant-current only")

    def measure(self):
        """(volts, amps, watts) — zeros when off, as the real one reads."""
        if not self._on:
            return 0.0, 0.0, 0.0
        v, i = self.turbine.terminals(self._demand)
        if v < self._volt_off:
            # The load drops out and the rotor unloads. This is the failure
            # that looks like nothing at all in a log: a row of zero amps at
            # full open-circuit voltage, and no error anywhere.
            v, i = self.turbine.v_oc, 0.0
        v = max(0.0, self.turbine.noise(v))
        i = max(0.0, self.turbine.noise(i))
        return v, i, v * i
