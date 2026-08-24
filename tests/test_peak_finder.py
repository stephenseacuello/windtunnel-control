"""
test_peak_finder.py — the stall-threshold detector, against a modelled rotor.

Weighted toward the failures that would cost real hardware or real data:
zero-current demands, a threshold reported as fact when it is a lower bound,
and an operating point that is quietly past the power peak.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from load_sim import SimulatedLoad, SimulatedTurbine, wind_mps
from peak_finder import PeakFinderError, find_peak


# The detector must cope with either source shape. A detector tested only
# against the curve it was tuned on has not been tested — and this rig turned
# out to follow the linear form, not the aerodynamic one it was written for.
MODELS = ["thevenin", "sqrt"]
PEAK_FRACTION = {"thevenin": 0.5, "sqrt": 2 / 3}


def rig(fan_rpm=1800.0, volt_off=0.5, **kw):
    t = SimulatedTurbine(**kw)
    t.fan_rpm = fan_rpm
    load = SimulatedLoad(t, volt_off=volt_off)
    load.on()
    return t, load


def sweep(load, turbine, voff=0.5, **kw):
    opts = dict(max_amps=turbine.i_stall * 1.6,
                floor_amps=min(0.002, turbine.i_stall * 0.1),
                min_step=0.0002, step_frac=0.05, dwell=0.0,
                v_floor=voff, range_="low")
    opts.update(kw)
    return find_peak(load, **opts)


class TestSafety:
    def test_refuses_a_zero_floor(self):
        """Zero amps in CC is an open circuit to a spinning rotor."""
        t, load = rig()
        with pytest.raises(PeakFinderError, match="open circuit"):
            sweep(load, t, floor_amps=0.0)

    def test_never_commands_zero(self):
        """Not one dwell in the whole ramp may unload the rotor."""
        t, load = rig()
        r = sweep(load, t)
        assert r.trace
        assert all(s.demand_a > 0 for s in r.trace)

    def test_leaves_the_rotor_loaded_after_a_stall(self):
        t, load = rig()
        r = sweep(load, t)
        assert r.stalled
        # the finder's last act is to re-load; the demand it holds is the floor
        assert load.read_setpoint("curr") > 0


class TestThreshold:
    @pytest.mark.parametrize("model", MODELS)
    def test_finds_the_true_stall_current(self, model):
        t, load = rig(volt_off=0.5, model=model)
        r = sweep(load, t, voff=0.5)
        assert r.found
        assert r.peak_amps == pytest.approx(t.i_stall, rel=0.10)

    def test_ceiling_stops_a_source_that_never_rolls_over(self):
        t, load = rig()
        r = sweep(load, t, max_amps=t.i_stall * 0.5)
        assert not r.found
        assert r.limited_by == "ceiling"
        assert "lower bound" in r.stopped_by

    @pytest.mark.parametrize("rpm", [500, 900, 1400, 1800])
    def test_relative_step_gives_comparable_resolution_at_every_wind_speed(self, rpm):
        """
        The point of a fractional step. A fixed 10 mA step gives ~2 points at
        500 rpm and ~33 at 1800; this should give a similar count at both.
        """
        t, load = rig(fan_rpm=rpm)
        r = sweep(load, t)
        assert 15 <= len(r.trace) <= 200


class TestCensoring:
    def test_shipped_volt_off_censors_the_threshold(self):
        """
        The failure that would otherwise be invisible: at CONF:VOLT:OFF = 3 V
        the load quits before the rotor does, and the number recorded is the
        instrument's limit wearing the turbine's name.
        """
        t, load = rig(fan_rpm=500, volt_off=3.0)
        r = sweep(load, t, voff=3.0)
        assert r.censored
        assert r.peak_amps < t.i_stall          # genuinely an under-read
        assert "LOWER BOUND" in r.summary()
        assert r.power_peak_ratio > 0.85

    @pytest.mark.parametrize("model", MODELS)
    def test_lowering_volt_off_recovers_the_real_threshold(self, model):
        t_hi, load_hi = rig(fan_rpm=500, volt_off=3.0, model=model)
        r_hi = sweep(load_hi, t_hi, voff=3.0)
        t_lo, load_lo = rig(fan_rpm=500, volt_off=0.5, model=model)
        r_lo = sweep(load_lo, t_lo, voff=0.5)
        assert r_lo.peak_amps > r_hi.peak_amps
        assert r_lo.peak_amps == pytest.approx(t_lo.i_stall, rel=0.12)


class TestPowerVersusCurrent:
    @pytest.mark.parametrize("model", MODELS)
    def test_power_peak_is_below_the_current_threshold(self, model):
        """
        Peak current sits deeper into stall than peak power under EITHER
        source model — only the ratio differs (½ linear, ⅔ aerodynamic).
        That ordering is what makes the protocol's "ramp past the power peak
        to find the current peak" description true.
        """
        t, load = rig(model=model)
        r = sweep(load, t)
        assert r.power_peak_amps < r.peak_amps
        assert r.power_peak_amps / t.i_stall == pytest.approx(
            PEAK_FRACTION[model], rel=0.18)

    def test_the_80pc_operating_point_is_past_the_power_peak(self):
        """
        Worth asserting because it is counterintuitive and it changes what the
        number means: 80% of the STALL current is on the falling side of the
        power curve, so it is not 80% of peak power and not near it.
        """
        t, load = rig()
        r = sweep(load, t)
        assert r.operating_amps > r.power_peak_amps
        assert r.operating is not None
        assert r.operating.watts < r.power_peak_watts

    def test_operating_point_is_the_requested_fraction(self):
        t, load = rig()
        r = sweep(load, t, operate_frac=0.80)
        assert r.operating_amps == pytest.approx(0.80 * r.peak_amps, rel=1e-6)


class TestCalibrationAnchor:
    def test_model_reproduces_the_one_measured_point(self):
        """4 W at 1800 rpm, the only anchor there is."""
        t, load = rig(fan_rpm=1800, peak_watts=4.0, volts_at_peak=12.0)
        r = sweep(load, t)
        assert r.power_peak_watts == pytest.approx(4.0, rel=0.10)
        assert r.power_peak_volts == pytest.approx(12.0, rel=0.15)

    def test_power_scales_as_v_cubed(self):
        lo, _ = rig(fan_rpm=900)
        hi, _ = rig(fan_rpm=1800)
        ratio = (wind_mps(1800) / wind_mps(900)) ** 3
        p_lo = lo.v_oc * lo.i_stall * (2 / 3) * (1 / 3) ** 0.5
        p_hi = hi.v_oc * hi.i_stall * (2 / 3) * (1 / 3) ** 0.5
        assert p_hi / p_lo == pytest.approx(ratio, rel=1e-6)
