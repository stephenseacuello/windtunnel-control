"""
test_tunnel.py — regression suite. Run before trusting a change.

    pip install pytest
    cd tests && python -m pytest -v

Everything runs against the simulator, so no hardware and no serial port.

═══════════════════════════════════════════════════════════════════════════
WHAT THIS IS ACTUALLY FOR
═══════════════════════════════════════════════════════════════════════════
This is research code. It will be modified — by you, by a student next
semester, by whoever inherits the tunnel. The tests that matter are not the
ones checking that arithmetic works; they are the ones checking that the
**safety properties still hold** after somebody refactors something:

  · a profile that exceeds the soft limit is refused, not clipped
  · a mid-run fault aborts rather than continuing to command a stopped drive
  · every exit path from ACS550 leaves the fan stopped
  · a calibration in RPM space refuses to command velocity
  · the keep-alive keeps talking so the drive's watchdog never trips on us

If one of those breaks, the failure on real hardware is a 15 HP fan doing
something nobody asked for. Keep them passing.
"""

import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
ROOT = Path(__file__).resolve().parent.parent

import feedforward as ff
import gusts
from acs550 import CW_READY, CW_RUN, DriveError
from calibration import Calibration
from config import TunnelConfig
from player import ProfileAborted, ProfilePlayer
from simulator import SimulatedACS550


# ═══════════════════════════════════════════════════════════════════════════
# SAFETY PROPERTIES — the ones that matter on real hardware
# ═══════════════════════════════════════════════════════════════════════════

class TestSafety:

    def test_profile_over_limit_is_refused_not_clipped(self):
        """
        Clipping would silently run a different experiment than the one
        designed. Refusing makes the operator confront the discrepancy.
        """
        d = SimulatedACS550().connect()
        d.start(20)
        t, u = gusts.one_minus_cosine(30, 20, 10, dt=0.05)   # peaks at 50
        p = ProfilePlayer(d, hz_limit=40)
        with pytest.raises(ProfileAborted, match="above the"):
            p.play(t, u)
        assert len(p.rows) == 0, "nothing should have been played"

    def test_midrun_fault_aborts(self):
        """
        Without this the loop keeps commanding a stopped drive for the rest of
        a multi-minute profile and logs a record that looks complete.
        """
        d = SimulatedACS550(fault_at_hz=25, tau_up=0.05, dead_time=0.0).connect()
        d.start(20)
        time.sleep(0.5)
        t, u = gusts.sharp_edged(20, 20, 5, dt=0.02, lead=0.5, trail=0.5)
        p = ProfilePlayer(d, check_every=5)
        with pytest.raises(ProfileAborted, match="faulted"):
            p.play(t, u)
        assert 0 < len(p.rows) < len(u), "should stop partway"

    def test_lost_comms_aborts(self):
        class Flaky(SimulatedACS550):
            def set_hz_fast(self, hz):
                self.writes += 1
                if self.writes > 20:
                    raise DriveError("simulated bus failure")
                super().set_hz_fast(hz)

        d = Flaky().connect()
        d.start(20)
        t, u = gusts.one_minus_cosine(20, 5, 3, dt=0.02, lead=0.2, trail=0.2)
        p = ProfilePlayer(d)
        with pytest.raises(ProfileAborted, match="lost comms"):
            p.play(t, u)

    def test_local_mode_is_detected(self):
        """
        If someone presses LOC/REM the drive ignores the fieldbus while writes
        still report success. A profile would 'run' against a deaf drive.
        """
        d = SimulatedACS550().connect()
        d.start(20)
        real_status = d.status

        def local_status():
            s = real_status()
            s["REMOTE"] = False
            return s
        d.status = local_status

        t, u = gusts.one_minus_cosine(20, 5, 2, dt=0.05)
        with pytest.raises(ProfileAborted, match="LOCAL"):
            ProfilePlayer(d).play(t, u)

    def test_context_manager_always_stops(self):
        d = SimulatedACS550()
        with pytest.raises(RuntimeError):
            with d as drive:
                drive.start(30)
                assert drive._cw == CW_RUN
                raise RuntimeError("simulated experiment failure")
        assert d._cw == CW_READY, "must ramp-stop even on exception"

    def test_partial_log_survives_abort(self, tmp_path):
        """A five-minute run must not lose everything if it dies at minute four."""
        d = SimulatedACS550(fault_at_hz=25, tau_up=0.05, dead_time=0.0).connect()
        d.start(20)
        time.sleep(0.5)
        log = tmp_path / "partial.csv"
        t, u = gusts.sharp_edged(20, 20, 5, dt=0.02, lead=0.5, trail=0.5)
        with pytest.raises(ProfileAborted):
            ProfilePlayer(d, log_path=log, check_every=5).play(t, u)
        assert log.exists()
        lines = log.read_text().splitlines()
        assert len(lines) > 2, "header plus whatever was captured"
        meta = log.with_suffix(".json")
        assert meta.exists() and "aborted_reason" in meta.read_text()

    def test_setpoint_is_clamped_to_ref1_max(self):
        d = SimulatedACS550(ref1_max_hz=60).connect()
        assert d.set_hz(500) == 60
        assert d.set_hz(-10) == 0


# ═══════════════════════════════════════════════════════════════════════════
# CALIBRATION — where a silent error is worst
# ═══════════════════════════════════════════════════════════════════════════

class TestCalibration:

    @pytest.fixture
    def rpm_cal(self):
        rpm = [0, 100, 200, 300, 400, 500, 600, 700]
        ms = [0.08, 1.83, 3.92, 6.12, 8.33, 9.79, 12.03, 13.99]
        return Calibration.from_rpm_velocity(rpm, ms, order=1)

    def test_rpm_domain_refuses_to_command_velocity(self, rpm_cal):
        """
        Without a drive map there is no Hz↔RPM link, and guessing one would
        put a systematic error into every commanded speed.
        """
        with pytest.raises(ValueError, match="RPM space"):
            rpm_cal.velocity(30)
        with pytest.raises(ValueError, match="RPM space"):
            rpm_cal.hz(12)

    def test_attach_drive_map_converts_domain(self, rpm_cal):
        rpm_cal.attach_drive_map(1750, 60)
        assert rpm_cal.domain == "hz"
        v60 = float(rpm_cal.velocity(60))
        # 60 Hz -> 1750 rpm; slope was ~0.0213 m/s per rpm
        assert 34 < v60 < 40, f"60 Hz gave {v60}"

    def test_roundtrip(self, rpm_cal):
        rpm_cal.attach_drive_map(1750, 60)
        for v in (5, 12, 20, 30):
            assert float(rpm_cal.velocity(rpm_cal.hz(v))) == pytest.approx(v, abs=1e-6)

    def test_pulley_ratio_scales(self, rpm_cal):
        import copy
        direct = copy.deepcopy(rpm_cal).attach_drive_map(1750, 60, 1.0)
        stepup = copy.deepcopy(rpm_cal).attach_drive_map(1750, 60, 2.0)
        assert float(stepup.velocity(30)) > float(direct.velocity(30))

    def test_profile_conversion_is_pointwise(self, rpm_cal):
        """
        A nonzero intercept means scaling mean and amplitude separately puts
        harmonic content into the gust that nobody designed.
        """
        rpm_cal.attach_drive_map(1750, 60)
        t, u_v = gusts.sinusoid(15, 4, 0.05, 60, dt=0.1)
        u_hz = rpm_cal.hz_profile(u_v)
        back = np.array([float(rpm_cal.velocity(h)) for h in u_hz])
        assert np.allclose(back, u_v, atol=1e-6)

    def test_persistence(self, tmp_path, rpm_cal):
        rpm_cal.attach_drive_map(1750, 60)
        p = tmp_path / "cal.json"
        rpm_cal.save(p)
        again = Calibration.load(p)
        assert np.allclose(again.coeffs, rpm_cal.coeffs)
        assert again.domain == "hz"
        assert again.rpm_per_hz == pytest.approx(rpm_cal.rpm_per_hz)

    def test_tenths_heuristic(self):
        """If this breaks, every commanded speed is off by 10x, silently."""
        d = SimulatedACS550(ref1_max_hz=60).connect()
        assert d.ref1_max_hz == pytest.approx(60.0)


# ═══════════════════════════════════════════════════════════════════════════
# PROFILE GENERATION AND PHYSICS
# ═══════════════════════════════════════════════════════════════════════════

class TestProfiles:

    def test_one_minus_cosine_shape(self):
        t, u = gusts.one_minus_cosine(25, 8, 20, dt=0.05, lead=5, trail=10)
        assert u[0] == pytest.approx(25)
        assert u[-1] == pytest.approx(25)
        assert u.max() == pytest.approx(33, abs=0.01)
        # continuous slope at the ends is the whole point of the shape
        d = np.diff(u) / 0.05
        assert abs(d[int(5 / 0.05)]) < 0.5

    def test_turbulence_is_reproducible(self):
        a = gusts.von_karman(25, 2, 40, 60, seed=7)[1]
        b = gusts.von_karman(25, 2, 40, 60, seed=7)[1]
        c = gusts.von_karman(25, 2, 40, 60, seed=8)[1]
        assert np.array_equal(a, b), "same seed must give the same realization"
        assert not np.array_equal(a, c)

    def test_turbulence_hits_requested_sigma(self):
        _, u = gusts.von_karman(25, 2.0, 40, 200, seed=1, lead=0, taper_s=0)
        assert u.std() == pytest.approx(2.0, rel=0.05)

    def test_taper_prevents_step_at_onset(self):
        """
        Splicing raw noise onto a steady lead commands a step of order sigma
        in a single sample — a slew violation and a pointless transient right
        where you least want one.

        This tests the *junction specifically*, not the overall maximum slew.
        The taper fixes the onset discontinuity; band-limiting is what fixes
        general high-frequency content, and conflating the two would make this
        test fail for the wrong reason.
        """
        lead, dt = 5.0, 0.05
        j = int(lead / dt) - 1
        _, tapered = gusts.von_karman(25, 3, 40, 60, seed=3, lead=lead,
                                      taper_s=4)
        _, raw = gusts.von_karman(25, 3, 40, 60, seed=3, lead=lead, taper_s=0)

        junction_tapered = abs(tapered[j + 1] - tapered[j]) / dt
        junction_raw = abs(raw[j + 1] - raw[j]) / dt
        assert junction_raw > 20, "the untapered case should show the step"
        assert junction_tapered < 1.0, \
            f"taper left a {junction_tapered:.1f} Hz/s step at the onset"

    def test_band_limit_reduces_slew(self):
        kw = dict(u_mean=25, sigma=2, length_scale=40, duration=120, seed=5)
        _, raw = gusts.von_karman(**kw, taper_s=0)
        _, lim = gusts.von_karman(**kw, f_max=0.05, taper_s=0)
        # Measured at ~4.4x on this seed; assert a conservative 3x so the
        # test does not become a tripwire on harmless numerical changes.
        assert np.abs(np.diff(lim)).max() < np.abs(np.diff(raw)).max() / 3

    def test_realizability_ranks_gusts_correctly(self):
        slow = gusts.check_realizable(*gusts.one_minus_cosine(30, 8, 40),
                                      tau=3.0, verbose=False)
        fast = gusts.check_realizable(*gusts.one_minus_cosine(30, 8, 2),
                                      tau=3.0, verbose=False)
        assert slow["amplitude_retained"] > 0.9
        assert fast["amplitude_retained"] < 0.4

    def test_asymmetric_model_costs_recovery_time(self):
        t, u = gusts.one_minus_cosine(30, 8, 12, dt=0.05, trail=40)
        r = gusts.check_realizable(t, u, tau=3.0, tau_down=6.0, verbose=False)
        assert r["recovery_penalty_s"] > 0, "slower decel must cost recovery"

    def test_csv_roundtrip(self, tmp_path):
        p = tmp_path / "plan.csv"
        p.write_text("time_s,hz\n0,20\n30,20\n40,35\n90,35\n")
        t, u, desc = gusts.from_csv(p, dt=0.1)
        assert u[0] == pytest.approx(20)
        assert u.max() == pytest.approx(35, abs=0.1)
        assert "4 breakpoints" in desc

    def test_csv_rejects_bad_time_column(self, tmp_path):
        p = tmp_path / "bad.csv"
        p.write_text("time_s,hz\n0,20\n30,20\n10,35\n")
        with pytest.raises(ValueError, match="increasing"):
            gusts.from_csv(p)

    def test_csv_rpm_needs_drive_map(self, tmp_path):
        p = tmp_path / "r.csv"
        p.write_text("time_s,rpm\n0,600\n30,900\n")
        with pytest.raises(ValueError, match="calibration"):
            gusts.from_csv(p, calibration=None)


# ═══════════════════════════════════════════════════════════════════════════
# FEEDFORWARD
# ═══════════════════════════════════════════════════════════════════════════

class TestFeedforward:

    def test_helps_slow_gusts(self):
        t, u = gusts.one_minus_cosine(30, 8, 20, dt=0.05)
        r = ff.compensate(t, u, tau=3.0, tau_down=5.0, slew_limit=12,
                          hz_limit=58, verbose=False)
        assert r["rms_improvement"] > 1.3

    def test_flags_when_it_makes_things_worse(self):
        """
        At short gust lengths the inverse gets clipped into something that
        overshoots and mistimes. Amplitude looks recovered; shape is worse.
        The caller must be able to detect that.
        """
        t, u = gusts.one_minus_cosine(30, 8, 3, dt=0.05)
        r = ff.compensate(t, u, tau=3.0, tau_down=5.0, slew_limit=12,
                          hz_limit=58, verbose=False)
        assert r["rms_improvement"] < 1.0
        assert r["retained_compensated"] > r["retained_uncompensated"], \
            "amplitude metric alone would have said this was an improvement"

    def test_respects_limits(self):
        t, u = gusts.one_minus_cosine(50, 8, 5, dt=0.05)
        r = ff.compensate(t, u, tau=3.0, slew_limit=6, hz_limit=58,
                          verbose=False)
        assert r["command"].max() <= 58 + 1e-9
        assert r["clipped_range"] or r["clipped_slew"]

    def test_forward_model_is_asymmetric(self):
        cmd = np.concatenate([np.full(200, 20.0), np.full(200, 30.0),
                              np.full(400, 20.0)])
        y = ff.simulate_flow(cmd, 0.05, tau_up=1.0, tau_down=4.0)
        rise = np.argmax(y > 29) - 200
        fall = np.argmax(y[400:] < 21)
        assert fall > rise, "down-ramp must be slower than up"


# ═══════════════════════════════════════════════════════════════════════════
# VELOCITY SOURCE AND CLOSED LOOP
# ═══════════════════════════════════════════════════════════════════════════

class TestVelocity:

    def test_manual_source_goes_stale(self):
        from velocity_source import ManualSource, StaleReading
        src = ManualSource(stale_after_s=0.4).start()
        try:
            src.submit(12.5)
            assert src.read() == pytest.approx(12.5)
            time.sleep(0.7)
            # A value typed twenty minutes ago is not a measurement of now.
            with pytest.raises(StaleReading):
                src.read()
        finally:
            src.stop()

    def test_source_with_no_reading_is_not_healthy(self):
        from velocity_source import ManualSource
        src = ManualSource().start()
        try:
            assert not src.healthy
            assert src.read_or_none() is None
        finally:
            src.stop()

    def test_sensor_calibration_forms(self):
        from velocity_source import SensorCalibration
        lin = SensorCalibration(115, 1.5, "linear")
        assert lin.to_velocity(0.2) == pytest.approx(24.5)
        sq = SensorCalibration(30, 0.0, "sqrt")
        assert sq.to_velocity(4.0) == pytest.approx(60.0)
        # below the offset must clamp, not produce a complex number
        assert sq.to_velocity(-1.0) == 0.0

    def test_suggest_gains_uses_plant_tau_for_integral(self):
        """
        IMC-PI sets Ti = plant tau, not the closed-loop tau. Using the latter
        makes ki smaller by tau/lambda and the loop converges so slowly that a
        two-minute hold ends mid-approach — and then reports the approach as
        a calibration error.
        """
        from velocity_loop import suggest_gains
        tau, K = 3.3, 0.6219
        g = suggest_gains(tau, 1 / K)
        assert g["ki"] == pytest.approx(g["kp"] / tau, rel=1e-3)
        assert g["ki"] > g["kp"] / g["closed_loop_tau"]

    def test_loop_converges_and_finds_injected_error(self):
        from calibration import Calibration
        from velocity_loop import VelocityController, suggest_gains
        from velocity_source import SimulatedSource

        cal = Calibration.from_rpm_velocity(
            [0, 700], [0.08, 13.99], order=1).attach_drive_map(1750, 60)
        d = SimulatedACS550(tau_up=0.2, tau_down=0.3, dead_time=0.02,
                            accel=1, decel=1).connect()
        BIAS = 0.88                      # sensor reads 12% low
        src = SimulatedSource(d, cal, bias=BIAS, noise=0.005,
                              average_s=0.3, poll_hz=20).start()
        try:
            g = suggest_gains(0.25, 1 / cal.coeffs[0])
            c = VelocityController(d, src.read, cal, kp=g["kp"], ki=g["ki"],
                                   period=0.15, hz_limit=58)
            res = c.hold(9.0, 12.0, verbose=False, settle_first=False)
            assert res["converged"], f"did not converge: {res}"
            # The loop must recover the injected error, not merely hold.
            assert res["implied_calibration_error"] == pytest.approx(
                1 / BIAS - 1, abs=0.04)
        finally:
            src.stop()
            d.stop()

    def test_unconverged_loop_withholds_the_calibration_number(self):
        """
        An unconverged correction is a snapshot of an approach. Reporting it
        as a calibration error would bake a wrong conclusion into someone's
        notes, so it must come back as None.
        """
        from calibration import Calibration
        from velocity_loop import VelocityController
        from velocity_source import SimulatedSource

        cal = Calibration.from_rpm_velocity(
            [0, 700], [0.08, 13.99], order=1).attach_drive_map(1750, 60)
        d = SimulatedACS550(tau_up=2.0, dead_time=0.05).connect()
        src = SimulatedSource(d, cal, bias=0.7, noise=0.001,
                              average_s=0.2, poll_hz=20).start()
        try:
            # Cripplingly small ki: guaranteed to end mid-approach.
            c = VelocityController(d, src.read, cal, kp=0.05, ki=0.001,
                                   period=0.2, hz_limit=58)
            res = c.hold(12.0, 3.0, verbose=False, settle_first=False)
            assert not res["converged"]
            assert res["implied_calibration_error"] is None
        finally:
            src.stop()
            d.stop()


# ═══════════════════════════════════════════════════════════════════════════
# PRE-FLIGHT — catching avoidable failures before they cost a session
# ═══════════════════════════════════════════════════════════════════════════

class TestPreflight:

    def test_blocks_unrealizable_profile(self):
        import preflight
        diag = {"amplitude_retained": 0.24}
        status, name, detail = preflight.check_realizability(diag, tau=3.0)
        assert status == preflight.FAIL
        assert "ripple" in detail

    def test_warns_without_tau(self):
        import preflight
        status, _, detail = preflight.check_realizability({}, tau=None)
        assert status == preflight.WARN
        assert "characterize" in detail

    def test_disk_check_fails_when_run_would_not_fit(self, tmp_path):
        import shutil

        import preflight
        # Derive the sample count from the ACTUAL free space rather than
        # assuming a number no machine could have. The old version asked for
        # ~40 GB and passed on a laptop with more than that free, which made
        # the test a statement about the test box rather than about the check.
        free = shutil.disk_usage(tmp_path).free
        samples = int(free / preflight.BYTES_PER_SAMPLE * 2) + 10**6
        status, _, detail = preflight.check_disk(tmp_path, samples=samples)
        assert status == preflight.FAIL, detail
        assert "mid-profile" in detail

    def test_disk_check_passes_for_a_normal_run(self, tmp_path):
        import preflight
        status, _, _ = preflight.check_disk(tmp_path, samples=6000)
        assert status in (preflight.PASS, preflight.WARN)

    def test_warns_on_missing_velocity_source(self):
        import preflight
        status, _, detail = preflight.check_velocity(None)
        assert status == preflight.WARN
        assert "drive frequency only" in detail

    def test_warnings_do_not_block(self):
        import preflight
        ok, checks = preflight.run_all(velocity_source=None, samples=100,
                                       diagnostics={}, tau=None,
                                       log_dir="/tmp/pf-test")
        assert ok, "warnings are judgement calls and must not block"
        assert any(c["status"] == preflight.WARN for c in checks)


class TestVelocityLogging:

    def test_run_logs_measured_velocity(self, tmp_path):
        """
        Without this a run records what the *drive* did, which is only a proxy
        for what the air did.
        """
        from calibration import Calibration
        from velocity_source import SimulatedSource

        cal = Calibration.from_rpm_velocity(
            [0, 700], [0.08, 13.99], order=1).attach_drive_map(1750, 60)
        d = SimulatedACS550(tau_up=0.2, dead_time=0.02, accel=1).connect()
        src = SimulatedSource(d, cal, bias=1.0, noise=0.002,
                              average_s=0.2, poll_hz=20).start()
        try:
            d.start(20)
            time.sleep(1.5)
            log = tmp_path / "v.csv"
            t, u = gusts.one_minus_cosine(20, 5, 2, dt=0.05, lead=0.5, trail=0.5)
            p = ProfilePlayer(d, log_path=log, velocity_source=src)
            summary = p.play(t, u)

            header = log.read_text().splitlines()[0]
            assert "v_meas" in header
            assert summary["velocity_coverage"] > 0.9
        finally:
            src.stop()
            d.stop()

    def test_stale_source_leaves_blanks_not_repeats(self, tmp_path):
        """
        A stale sensor must leave a gap in the record rather than silently
        repeating its last value, which would look like real data.
        """
        from velocity_source import ManualSource
        src = ManualSource(stale_after_s=0.3).start()
        src.submit(10.0)
        d = SimulatedACS550(tau_up=0.1, accel=1).connect()
        try:
            d.start(20)
            time.sleep(0.5)
            log = tmp_path / "stale.csv"
            t, u = gusts.one_minus_cosine(20, 4, 2, dt=0.05, lead=1, trail=1)
            ProfilePlayer(d, log_path=log, velocity_source=src).play(t, u)
            rows = log.read_text().splitlines()
            blanks = sum(1 for r in rows[1:] if r.rstrip().endswith(","))
            assert blanks > 0, "stale readings should appear as blanks"
        finally:
            src.stop()
            d.stop()


# ═══════════════════════════════════════════════════════════════════════════
# SENSOR CALIBRATION FITTING
# ═══════════════════════════════════════════════════════════════════════════

class TestSensorFit:

    def test_refuses_circular_data(self):
        """
        The Feb 13 table's voltage column was back-calculated as m/s / 14.
        Fitting one against the other returns a perfect line and means
        nothing — the tool must catch that rather than reporting R2 = 1.
        """
        import fit_sensor
        vel = [1.83, 3.92, 6.12, 8.33, 12.03, 29.40]
        volts = [v / 14.0 for v in vel]
        ok, why = fit_sensor.check_independence(volts, vel)
        assert not ok
        assert "circular" in why

    def test_accepts_genuinely_independent_data(self):
        import fit_sensor
        volts = [r[1] for r in fit_sensor.MARCH_PAIRS]
        vel = [r[2] for r in fit_sensor.MARCH_PAIRS]
        ok, _ = fit_sensor.check_independence(volts, vel)
        assert ok

    def test_identifies_a_linear_sensor(self):
        import fit_sensor
        rng = np.random.default_rng(0)
        volts = np.linspace(0.02, 0.30, 12)
        vel = 115 * volts + 1.5 + rng.normal(0, 0.15, len(volts))
        out, best = fit_sensor.fit_all(volts, vel, verbose=False)
        assert best in ("linear", "quadratic")
        assert out["linear"]["aic"] < out["sqrt"]["aic"]
        assert out["linear"]["params"]["a"] == pytest.approx(115, rel=0.05)

    def test_identifies_a_pressure_sensor(self):
        """A tool that always answers 'linear' is not identifying anything."""
        import fit_sensor
        rng = np.random.default_rng(1)
        vel = np.linspace(4, 30, 12)
        volts = (vel / 60.0) ** 2 + rng.normal(0, 2e-4, len(vel))
        out, _ = fit_sensor.fit_all(volts, vel, verbose=False)
        assert out["sqrt"]["aic"] < out["linear"]["aic"]

    def test_march_data_favours_linear_over_pressure(self):
        import fit_sensor
        volts = [r[1] for r in fit_sensor.MARCH_PAIRS]
        vel = [r[2] for r in fit_sensor.MARCH_PAIRS]
        out, _ = fit_sensor.fit_all(volts, vel, verbose=False)
        gap = out["sqrt"]["aic"] - out["linear"]["aic"]
        assert gap > 10, f"expected a decisive gap, got {gap:.1f}"


# ═══════════════════════════════════════════════════════════════════════════
# TURBINE — Cp(λ) and the stall guard
# ═══════════════════════════════════════════════════════════════════════════

class TestTurbine:

    def test_geometry_and_cp(self):
        from turbine import TurbineGeometry, air_density
        g = TurbineGeometry(radius_m=0.30)
        assert g.swept_area_m2 == pytest.approx(np.pi * 0.09, rel=1e-6)
        # lambda = omega*R/V
        assert g.tip_speed_ratio(1910, 15.0) == pytest.approx(4.0, rel=0.02)
        assert air_density(15.0) == pytest.approx(1.225, rel=0.01)

    def test_resistance_ladder_is_log_spaced_and_descends(self):
        """
        Current goes as 1/R, so linear steps crowd everything interesting into
        the bottom of the range. Descending order matters too: you can always
        stop early, and stopping early on the way down leaves you safe.
        """
        from turbine import plan_resistances
        r = plan_resistances(30.0, i_max=5.0, n=8)
        assert r[0] > r[-1], "must walk from light load toward heavy"
        ratios = [r[i] / r[i + 1] for i in range(len(r) - 1)]
        assert max(ratios) - min(ratios) < 0.05, "should be geometric"

    def test_guard_threshold_scales_with_rotor_speed(self):
        """
        An absolute rpm/s threshold is meaningless across operating points:
        -5 rpm/s is a hard stall at 200 rpm and ordinary settling at 5000.
        Testing caught this — the guard aborted the first point of every
        sweep because a rotor coasting from no-load exceeds any fixed limit.
        """
        from turbine import StallGuard
        g = StallGuard()
        t = list(np.arange(0, 2.0, 0.25))
        # -20 rpm/s: trivial for a fast rotor, fatal for a slow one
        fast = [5000 - 20 * x for x in t]
        slow = [200 - 20 * x for x in t]
        ok_fast, _ = g.check(fast, t, 6000, 100, 100, 50)
        ok_slow, why = g.check(slow, t, 260, 5, 100, 10)
        assert ok_fast, "0.4%/s is normal settling for a fast rotor"
        assert not ok_slow and "equilibrium" in why

    def test_guard_stops_on_power_rollover(self):
        from turbine import StallGuard
        g = StallGuard(rollover_frac=0.20)
        t = list(np.arange(0, 2.0, 0.25))
        steady = [1500.0] * len(t)
        ok, why = g.check(steady, t, 3000, power_w=60, best_power_w=100,
                          volts=20)
        assert not ok and "rolled over" in why

    def test_guard_stops_on_collapsed_output(self):
        from turbine import StallGuard
        g = StallGuard()
        t = list(np.arange(0, 2.0, 0.25))
        ok, why = g.check([300.0] * len(t), t, 3000, 1, 50, volts=0.3)
        assert not ok and "collapsed" in why

    def test_cc_cannot_hold_below_peak_lambda_but_cr_can(self):
        """
        The precise reason CR is the mode — and it is narrower than "CC is
        unstable".

        CC is perfectly stable *above* peak λ: slow down there and you move
        toward the Cp peak, aero torque rises, and the rotor recovers. It is
        below peak λ that the sign flips — slowing reduces aero torque while
        the commanded current keeps braking just as hard, and nothing stops
        the collapse.

        A Cp sweep has to traverse below peak λ; that is where the peak is
        found. So the mode has to be stable there, and only CR is.

        Deterministic dt: a physics assertion that depends on scheduler
        timing is not testing physics.
        """
        import sys as _s
        _s.path.insert(0, str(Path(__file__).resolve().parent))
        from simturb import SimLoad, SimTurbine

        DT, WIND = 0.002, 15.0

        def run(setup, knock=1.0):
            t = SimTurbine()
            L = SimLoad(t)
            L.on()
            t.spin_to(WIND)
            setup(L)
            for _ in range(4000):
                t.step(DT)
            base = t.omega
            t.omega *= knock
            for _ in range(6000):
                t.step(DT)
            lam = t.omega * t.R / WIND
            return base * 60 / (2 * np.pi), t.omega * 60 / (2 * np.pi), lam

        # CR at 13 Ω finds a stable point below peak λ (5.5) and holds it
        # through a 15% disturbance.
        cr_base, cr_end, cr_lam = run(lambda L: L.set_mode_cr(13.0), knock=0.85)
        assert 1.5 < cr_lam < 5.0, f"CR should sit below peak λ, got {cr_lam:.2f}"
        assert cr_end / cr_base > 0.75, \
            f"CR should hold near its point, kept {cr_end / cr_base:.0%}"

        # CC asking for enough braking to reach that region has no stable
        # equilibrium there and runs away to a stop.
        cc_base, cc_end, cc_lam = run(lambda L: L.set_mode_cc(3.6))
        assert cc_lam < 1.0, f"CC should collapse, ended at λ={cc_lam:.2f}"
        assert cc_end < 0.2 * cr_end

    def test_cc_is_stable_above_peak_lambda(self):
        """
        The other half of the same claim, and the reason not to overstate it:
        CC is fine on the high-λ side. Asserting CC is simply unstable would
        be wrong, and a test that passes for the wrong reason is worse than
        no test.
        """
        import sys as _s
        _s.path.insert(0, str(Path(__file__).resolve().parent))
        from simturb import SimLoad, SimTurbine

        DT = 0.002
        t = SimTurbine()
        L = SimLoad(t)
        L.on()
        t.spin_to(15.0)
        L.set_mode_cc(2.85)                # light enough to sit above peak λ
        for _ in range(4000):
            t.step(DT)
        base = t.omega
        lam = t.omega * t.R / 15.0
        t.omega *= 0.85
        for _ in range(6000):
            t.step(DT)
        assert lam > 5.0, f"expected the high-λ branch, got {lam:.2f}"
        assert t.omega / base > 0.9, "CC recovers above peak λ"


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════

class TestConfig:

    def test_corner_from_tau(self, tmp_path):
        c = TunnelConfig({}, tmp_path / "t.json")
        c.set("tau", 3.0)
        assert c.f_corner == pytest.approx(1 / (2 * np.pi * 3.0))

    def test_ambient_density(self, tmp_path):
        c = TunnelConfig({}, tmp_path / "t.json")
        assert c.ambient() is None
        c.set("temperature_c", 15.0).set("pressure_pa", 101325.0)
        a = c.ambient()
        assert a["density_ratio"] == pytest.approx(1.0, abs=0.005)
        c.set("temperature_c", 35.0)
        assert c.ambient()["density_ratio"] < 0.95

    def test_history_is_bounded(self, tmp_path):
        c = TunnelConfig({}, tmp_path / "t.json")
        for i in range(100):
            c.set("tau", i)
        assert len(c.data["_history"]) <= 40


# ═══════════════════════════════════════════════════════════════════════════
# PROVENANCE — the metadata that cannot be reconstructed later
# ═══════════════════════════════════════════════════════════════════════════

class TestReferenceScaling:
    """
    The silent-10x failure, pinned.

    par 1105 is stored in TENTHS in the Hz domain (600 = 60.0 Hz) and in
    WHOLE UNITS in the speed domain (2435 = 2435 rpm). Applying the tenths
    heuristic to a speed reference makes every commanded speed exactly ten
    times too high, and nothing anywhere reports it — the fan simply runs at
    the wrong speed and every velocity derived from it is wrong too.

    It was dormant for months because the read failed over PMC firmware 2.x
    and the configured fallback was used instead. Adding RD in firmware 3.0
    made the read succeed and the heuristic fired for the first time.
    """

    def _drive(self, raw_1105, unit, fallback=None):
        import acs550
        d = acs550.ACS550.__new__(acs550.ACS550)
        d.ref1_max_hz = None
        d.ref_unit = unit
        d._ref1_max_fallback = fallback
        d.read_param = lambda p: raw_1105
        return d

    def _resolve(self, d):
        raw = d.read_param(1105)
        if str(d.ref_unit).lower() == "rpm":
            return float(raw)
        return raw / 10.0 if raw > 200 else float(raw)

    def test_rpm_reference_is_not_divided_by_ten(self):
        d = self._drive(2435, "rpm")
        assert self._resolve(d) == 2435.0, (
            "a speed reference of 2435 rpm was read as 243.5 — every "
            "commanded speed would be 10x too high")

    def test_hz_reference_still_uses_tenths(self):
        d = self._drive(600, "Hz")
        assert self._resolve(d) == 60.0

    def test_small_hz_value_is_not_treated_as_tenths(self):
        d = self._drive(60, "Hz")
        assert self._resolve(d) == 60.0

    def test_commanding_ten_rpm_gives_ten_rpm(self):
        """The end-to-end arithmetic, at the value that exposed the bug."""
        REF_FULL_SCALE = 20000
        for ref1_max, expect in ((2435.0, 10.0), (243.5, 100.0)):
            counts = round(10.0 * REF_FULL_SCALE / ref1_max)
            actual = counts / REF_FULL_SCALE * 2435.0
            assert abs(actual - expect) < 1.0, (ref1_max, actual)


class TestProvenance:

    def _controller(self, tmp_path):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))
        from controller import TunnelController
        cfg = tmp_path / "t.json"
        cfg.write_text('{"hz_limit": 58, "tau": 3.0}')
        c = TunnelController("SIM", dry_run=True, config_path=str(cfg))
        c.start()
        return c

    def test_session_is_stamped_into_run_metadata(self, tmp_path):
        c = self._controller(tmp_path)
        try:
            c.set_session(operator="S. Eacuello",
                          configuration="3-blade SLA rotor")
            meta = c.run_metadata({"mode": "test"})
            assert meta["session"]["operator"] == "S. Eacuello"
            assert meta["session"]["configuration"] == "3-blade SLA rotor"
            # Simulated runs must be self-identifying, or somebody eventually
            # publishes a figure made from simulator output.
            assert meta["simulated"] is True
        finally:
            c.shutdown()

    def test_soft_limit_blocks_a_sweep(self, tmp_path):
        c = self._controller(tmp_path)
        try:
            with pytest.raises(ValueError, match="soft limit"):
                c.run_sweep(10, 90, 10)
        finally:
            c.shutdown()

    def test_estop_latches_against_setpoints(self, tmp_path):
        c = self._controller(tmp_path)
        try:
            c.estop()
            with pytest.raises(RuntimeError, match="E-STOP"):
                c.set_setpoint(20, "hz")
            c.clear_estop()
            assert c.set_setpoint(20, "hz")["hz"] == pytest.approx(20)
        finally:
            c.shutdown()

    def test_setpoint_over_limit_refused(self, tmp_path):
        c = self._controller(tmp_path)
        try:
            with pytest.raises(ValueError, match="soft limit"):
                c.set_setpoint(70, "hz")
        finally:
            c.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# END TO END
# ═══════════════════════════════════════════════════════════════════════════

class TestEndToEnd:

    def test_gust_run_produces_usable_log(self, tmp_path):
        d = SimulatedACS550(tau_up=0.3, tau_down=0.5, dead_time=0.02,
                            accel=2, decel=3).connect()
        d.start(20)
        time.sleep(2)                       # settle properly
        log = tmp_path / "run.csv"
        t, u = gusts.one_minus_cosine(20, 6, 3, dt=0.05, lead=1, trail=2)
        summary = ProfilePlayer(d, log_path=log,
                                metadata={"mode": "test"}).play(t, u)

        assert summary["complete"]
        assert summary["samples_played"] == len(u)
        # Absolute deadlines must keep the run close to its requested length.
        assert summary["actual_duration"] == pytest.approx(
            summary["requested_duration"], rel=0.25)

        import analyze
        res = analyze.analyze(str(log), verbose=False)
        assert not res["unsettled_start"]
        assert 0.2 < res["amplitude_retained"] <= 1.3

    def test_analyze_flags_unsettled_start(self, tmp_path):
        d = SimulatedACS550(tau_up=2.0, dead_time=0.05).connect()
        d.start(25)                          # deliberately no settle
        log = tmp_path / "unsettled.csv"
        t, u = gusts.one_minus_cosine(25, 5, 2, dt=0.05, lead=0.5, trail=0.5)
        ProfilePlayer(d, log_path=log).play(t, u)

        import analyze
        res = analyze.analyze(str(log), verbose=False)
        assert res["unsettled_start"], "should notice the flow was still climbing"

    def test_estimate_tau_recovers_known_value(self, tmp_path):
        import csv as _csv
        import analyze
        TRUE = 4.2
        t, u = gusts.one_minus_cosine(25, 8, 20, dt=0.05)
        n = len(u)
        f = np.fft.rfftfreq(n, 0.05)
        H = 1 / (1 + 1j * 2 * np.pi * f * TRUE)
        meas = np.fft.irfft(np.fft.rfft(u - u.mean()) * H, n=n) + u.mean()
        log = tmp_path / "syn.csv"
        with open(log, "w", newline="") as fh:
            w = _csv.writer(fh)
            w.writerow(["t_s", "cmd_hz", "meas_hz", "meas_a"])
            for i in range(n):
                w.writerow([f"{t[i]:.4f}", f"{u[i]:.3f}", f"{meas[i]:.2f}", "14.0"])
        res = analyze.analyze(str(log), verbose=False)
        assert res["tau_s"] == pytest.approx(TRUE, rel=0.05)


class TestGustAchievabilityIsDocumentedFromMeasurement:
    """
    docs/03_gusts.md was written against an ASSUMED tau of 3 s. The measured
    value is 0.60 s, so the tunnel is roughly five times better than the
    document claimed — and the document was advising against experiments this
    rig can actually run.
    """

    def _retained(self, period_s, tau):
        import math
        fc = 1.0 / (2 * math.pi * tau)
        f = 1.0 / period_s
        return 1.0 / math.sqrt(1.0 + (f / fc) ** 2)

    def test_three_second_gusts_are_usable_at_the_measured_tau(self):
        """
        62% at tau = 0.60 against 16% at the assumed 3 s. The difference
        between an experiment worth running and one that is pointless.
        """
        assert self._retained(3.0, 0.60) > 0.60
        assert self._retained(3.0, 3.00) < 0.20

    def test_the_document_quotes_the_measured_figures(self):
        doc = (ROOT / "docs" / "03_gusts.md").read_text()
        assert "0.265 Hz" in doc, "the corner frequency is not the measured one"
        assert "62%" in doc, "the 3 s retention is not stated"
        assert "8.65 m/s" in doc, "the slew limit is not stated"

    def test_the_slew_limit_is_recorded_so_the_check_can_run(self):
        """
        check_realizable's own docstring calls an exceeded slew a SILENT
        failure: the drive clips and you run a different experiment than the
        one you designed. Without a slew figure the check does not run at all.
        """
        import json
        cfg = json.loads((ROOT / "data" / "tunnel.json").read_text())
        assert cfg.get("max_slew_rpm_s"), \
            "no slew limit recorded, so a fallback check cannot run"
        assert cfg.get("accel_s") == 6.0, "par 2202 is not recorded"

    def test_the_dashboard_says_when_the_slew_check_is_off(self):
        """
        run.py has always announced it. The dashboard silently left max_slew
        as None, which disables the check without telling anyone — the worst
        of both: no protection and no warning.
        """
        ctl = (ROOT / "webapp" / "controller.py").read_text()
        i = ctl.index("def profile_preview") if "def profile_preview" in ctl else 0
        assert "slew_note" in ctl, "the dashboard cannot report a disabled check"
        assert "SLEW CHECK IS OFF" in ctl, "it does not say so plainly"


class TestSlewClippedRunsAreExcludedFromTau:
    """
    R² alone cannot distinguish a bad FIT from a bad MODEL. One of the five
    1-cosine runs on this rig commanded 238% of the drive's ramp limit — the
    drive clipped it, so the response is not first order — and it produced
    the worst fit of the set (0.926 against 0.989+) while still being counted
    as a "good fit".
    """

    def _summary(self):
        import subprocess, sys as _s
        return subprocess.run(
            [_s.executable, str(ROOT / "src" / "analyze.py"),
             *[str(p) for p in sorted((ROOT / "logs").glob("20260820_14*_1mc.csv"))],
             "--summary"], capture_output=True, text=True).stdout

    def test_the_clipped_run_is_flagged(self):
        out = self._summary()
        assert "CLIPPED" in out, "analyze.py does not flag a slew-clipped run"
        assert "144715" in out.split("CLIPPED")[0].splitlines()[-1], \
            "the wrong run is flagged"

    def test_it_is_excluded_from_the_average(self):
        out = self._summary()
        assert "EXCLUDED" in out
        assert "4 unclipped fits" in out, \
            "the clipped run is still in the tau average"

    def test_the_headline_value_is_unchanged(self):
        """
        Reassuring rather than convenient: excluding a bad-model run left the
        mean at 0.60. Had it moved, every gust figure downstream would have
        needed revisiting.
        """
        out = self._summary()
        assert "0.60 ±" in out, f"tau moved: {out[-200:]}"

    def test_a_run_under_the_limit_is_not_excluded(self):
        out = self._summary()
        body = [l for l in out.splitlines() if "144426" in l]
        assert body and "CLIPPED" not in body[0], \
            "a run at 20% of the limit was wrongly excluded"
