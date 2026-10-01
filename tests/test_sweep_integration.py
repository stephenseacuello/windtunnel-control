"""
test_sweep_integration.py — actually RUN a dashboard sweep.

Every other test in this repo is static: it reads source, checks a header,
asserts a string is present. That caught a great deal, and it did not catch
this:

    class _Rig:  ...   # defined inside start_blade_sweep, next to its user

was inserted against an anchor matching the FIRST `def work():` in the file —
which belongs to a different method entirely. The class landed there, the
dashboard sweep raised `NameError: name '_Rig' is not defined` on its second
point, and 155 tests passed, because not one of them ran a sweep.

A refactor that moves the measurement between two front ends needs one test
that performs the measurement. This is that test.
"""

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "webapp"))


@pytest.fixture(scope="module")
def swept(tmp_path_factory):
    """One simulated dashboard sweep, three points, run for real."""
    import controller as C
    import sweep_core as sc

    ctl = C.TunnelController(port=None, dry_run=True,
                             config_path=str(ROOT / "data" / "tunnel.json"))
    # start() is what connects the drive AND the simulated load, and starts
    # the poll thread — which is also the only sampler of fan speed and rotor
    # pulses, so a sweep without it measures nothing.
    ctl.start()
    time.sleep(0.5)
    ctl.load_on()
    time.sleep(0.3)
    ctl.start_blade_sweep(blade="pytest_sweep", notes="integration",
                          start_rpm=1700, stop_rpm=1800, rpm_step=100,
                          step_amps=0.02, dwell=0.02)
    for _ in range(600):
        if (ctl.sweep or {}).get("state") == "done":
            break
        time.sleep(0.1)
    sw = ctl.sweep or {}
    yield sw, sc
    for f in (ROOT / "logs").glob("sweep_pytest_sweep*"):
        f.unlink(missing_ok=True)
    try:
        ctl.close()
    except Exception:
        pass


def test_the_sweep_completes(swept):
    sw, _ = swept
    assert sw.get("state") == "done", "the sweep never finished"
    assert sw.get("message") == "complete", \
        f"the sweep did not complete: {sw.get('message')}"


def test_it_measured_every_point(swept):
    sw, _ = swept
    assert len(sw.get("points", [])) == sw.get("n"), \
        f"{len(sw.get('points', []))} of {sw.get('n')} points recorded"
    for p in sw["points"]:
        assert p["p_w"] > 0, f"no power at {p['rpm']} rpm"


def test_it_wrote_campaign_shaped_files(swept):
    """
    The dashboard once wrote nine summary columns against the CLI's sixteen,
    so a shared fingerprint certified agreement between files that could not
    be compared.
    """
    import csv
    sw, sc = swept
    for path, header in ((sw["summary_csv"], sc.SUMMARY_HEADER),
                         (sw["points_csv"], sc.POINTS_HEADER)):
        body = [l for l in Path(path).read_text().splitlines(True)
                if not l.startswith("#")]
        assert next(csv.reader(body)) == header, \
            f"{Path(path).name} does not carry the shared columns"


def test_wind_speed_comes_from_the_measured_fan_rpm(swept):
    """Not the commanded one — the drive settles below setpoint."""
    import csv
    sw, _ = swept
    body = [l for l in Path(sw["summary_csv"]).read_text().splitlines(True)
            if not l.startswith("#")]
    rows = list(csv.DictReader(body))
    assert rows, "no summary rows"
    for r in rows:
        assert r["fan_rpm_actual"], "measured fan rpm is not recorded"


def test_the_run_is_readable_by_the_comparison_tool(swept):
    """A file the campaign's own analysis cannot open is not a result."""
    import compare_blades as cb
    sw, _ = swept
    loaded = cb.load(sw["summary_csv"])
    assert loaded["meta"].get("protocol"), "no fingerprint in the header"
    assert loaded["rows"], "compare_blades read no rows"


def test_campaign_settings_reproduce_the_banked_ladder():
    """
    sweep_core.CAMPAIGN carried min_step_amps = 0.001 for two days. The banked
    runs used 0.002 — provable from the data: the first demands at fan 500 are
    0.0010, 0.0020, 0.0040, 0.0060, a 2.000 mA step.

    min_step_amps is NOT in the hashed shape, so settings() produced a 1.455 mA
    ladder and stamped it 94bed28333f7, the fingerprint of a 2.000 mA one. The
    dashboard would have run a different measurement while the hash swore it
    had not.
    """
    import csv
    from collections import defaultdict
    import sweep_core as sc

    by = defaultdict(list)
    body = [l for l in (ROOT / "logs" / "sweep_v1_Ra20_points.csv")
            .read_text().splitlines(True) if not l.startswith("#")]
    for r in csv.DictReader(body):
        try:
            by[int(float(r["fan_rpm"]))].append(float(r["demand_a"]))
        except (KeyError, TypeError, ValueError):
            pass
    lo = min(by)
    demands = sorted(set(by[lo]))
    observed = round(demands[2] - demands[1], 6)      # past the floor

    a = sc.settings(step_amps=0.02, dwell=1.0)
    assert abs(sc.step_for(lo, a) - observed) < 1e-6, (
        f"CAMPAIGN walks {sc.step_for(lo, a)*1000:.3f} mA at {lo} rpm; the "
        f"banked runs walked {observed*1000:.3f}")


def test_the_full_hash_sees_what_the_original_cannot():
    """
    stop_rpm is the v² ladder's NORMALISATION reference, not a stopping point.
    Shortening a sweep to save tunnel time reads like "how far the run got"
    and is actually a different ladder at every wind speed — under one
    fingerprint.
    """
    import sweep_core as sc
    a = sc.settings(step_amps=0.02, dwell=1.0)
    b = sc.settings(step_amps=0.02, dwell=1.0, stop_rpm=1200)
    ma, mb = sc.protocol(a, 0.5, "low"), sc.protocol(b, 0.5, "low")
    assert ma["protocol"] == mb["protocol"], \
        "the original hash changed; the banked runs are orphaned"
    assert ma["protocol_full"] != mb["protocol_full"], \
        "protocol_full does not see a stop_rpm change either"
    assert sc.step_for(1000, a) != sc.step_for(1000, b), \
        "stop_rpm no longer moves the ladder — check step_for"


def test_the_campaign_fingerprint_is_still_the_banked_one():
    import sweep_core as sc
    a = sc.settings(step_amps=0.02, dwell=1.0)
    assert sc.protocol(a, 0.5, "low")["protocol"] == "94bed28333f7"


def test_every_sweep_records_which_signal_the_fan_readback_came_from():
    """
    Par 5310/5311 decide what `actuals()` returns, and they are NOT among the
    383 parameters the profile captures — so nothing restores them and they
    are whatever the drive happens to hold.

    That is not hypothetical. sweep_v1_Ra20 recorded fan speed slipping 4-21
    rpm below setpoint across 10 distinct values — a real measurement of a
    loaded 15 HP fan. sweep_v1_Ra80 recorded 0-1 rpm across TWO distinct
    values: the setpoint echoed back. Same code, same rig, different meaning,
    and it moves the wind column 1.2%, which is 4.6% in power at v^3.77.

    Recording it per run makes that answerable later instead of forensic.
    """
    import sweep_core
    assert hasattr(sweep_core, "actuals_meta")

    class Drive:
        def actual_signals(self):
            return 103, 104

    m = sweep_core.actuals_meta(Drive())
    assert m["drive_actual_signals"].startswith("5310=103;5311=104")
    assert "⚠" not in m["drive_actual_signals"]

    class Wrong(Drive):
        def actual_signals(self):
            return 102, 104          # SPEED, not OUTPUT FREQ

    assert "⚠" in sweep_core.actuals_meta(Wrong())["drive_actual_signals"]

    class Dead:
        def actual_signals(self):
            raise RuntimeError("no link")

    # must never abort a sweep over a diagnostic
    assert "not read" in sweep_core.actuals_meta(Dead())["drive_actual_signals"]


def test_the_banked_runs_disagree_about_fan_telemetry():
    """Guards the observation above against someone 'fixing' the CSVs."""
    import csv

    def slips(path, key):
        rows = [r for r in csv.DictReader(
            [l for l in open(ROOT / path) if not l.startswith("#")])]
        return {round(float(r["fan_rpm_actual"]) - float(r[key]), 1)
                for r in rows if r.get("fan_rpm_actual")}

    ra20 = slips("logs/sweep_v1_Ra20_summary.csv", "fan_rpm_cmd")
    ra80 = slips("logs/sweep_v1_Ra80_summary.csv", "fan_rpm_cmd")
    assert len(ra20) >= 8, f"Ra20 should show real slip, got {ra20}"
    assert min(ra20) <= -15
    assert len(ra80) <= 2, f"Ra80 should be a setpoint echo, got {ra80}"
    assert min(ra80) >= -1


# ── logging rate: the dashboard must match the CLI ────────────────────────

def test_dashboard_polls_fast_enough_during_a_run():
    """
    Rotor speed is read from the gap between two telemetry samples, so the
    sample period must be MUCH shorter than a dwell. At 4 Hz against a 1 s
    dwell there were four samples per window and the window spilled into the
    previous ladder step — which carries a different load, and the rotor slows
    under load. Idle stays slow; nothing needs 20 Hz of a stationary fan.
    """
    import controller as C
    c = C.TunnelController.__new__(C.TunnelController)
    c.poll_period, c.sweep_poll_period = 0.25, 0.05

    c.sweep, c._job = None, None
    assert c._active_period == 0.25, "idle should stay slow"

    c.sweep = {"state": "running"}
    assert c._active_period == 0.05, "a running sweep must poll fast"

    c.sweep = {"state": "done"}
    c._job = {"state": "settling"}
    assert c._active_period == 0.05, "settling counts as a run"


def test_dashboard_trace_buffer_outlives_a_whole_sweep():
    """
    900 entries held 225 s at 20 Hz. The Ra 40 sweep ran 505 s, so the first
    half — every rotor sample belonging to the low wind speeds — was silently
    dropped before anything could write it out.
    """
    src = (ROOT / "webapp" / "controller.py").read_text()
    import re
    m = re.search(r"self\.trace = deque\(maxlen=(\d+)\)", src)
    assert m, "trace deque not found"
    maxlen = int(m.group(1))
    assert maxlen / 20.0 >= 600, \
        f"{maxlen} at 20 Hz is {maxlen/20:.0f}s — shorter than a sweep"


def test_dashboard_writes_the_same_trace_file_as_the_cli(tmp_path):
    """A dashboard run and a CLI run must produce the same three files."""
    import csv
    import controller as C
    c = C.TunnelController.__new__(C.TunnelController)
    c.sweep_poll_period = 0.05
    c.log = lambda *a, **k: None
    c.trace = [{"t": 1000 + i * 0.05, "meas": 1800.0, "amps": 13.6,
                "pulses": 100 + i * 15, "last_us": 5000 + i * 900}
               for i in range(200)]
    sw = {"_t0": 1000.0, "blade": "t", "protocol": "94bed28333f7",
          "summary_csv": str(tmp_path / "s_summary.csv")}
    c._write_trace(sw)

    p = tmp_path / "s_trace.csv"
    assert p.exists(), "no trace file from the dashboard"
    rows = list(csv.DictReader([l for l in open(p) if not l.startswith("#")]))
    assert len(rows) == 200
    assert list(rows[0]) == ["t_unix", "t_rel_s", "fan_rpm_actual",
                             "motor_amps", "rpm_pulses", "rpm_last_us"]
    dt = float(rows[1]["t_rel_s"]) - float(rows[0]["t_rel_s"])
    assert abs(dt - 0.05) < 1e-6, f"interval {dt}, expected 0.05"
    assert all(r["rpm_pulses"] for r in rows)


def test_trace_only_covers_the_run_not_the_idle_before_it():
    """The ring buffer holds pre-run idle; a trace must start at the sweep."""
    import controller as C
    c = C.TunnelController.__new__(C.TunnelController)
    c.sweep_poll_period, c.log = 0.05, lambda *a, **k: None
    c.trace = [{"t": 900 + i, "meas": 0.0, "amps": 0.0,
                "pulses": None, "last_us": None} for i in range(50)] + \
              [{"t": 1000 + i * 0.05, "meas": 1800.0, "amps": 13.6,
                "pulses": i, "last_us": i} for i in range(20)]
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        sw = {"_t0": 1000.0, "blade": "t", "protocol": "x",
              "summary_csv": f"{d}/x_summary.csv"}
        c._write_trace(sw)
        import csv as _c
        rows = list(_c.DictReader([l for l in open(f"{d}/x_trace.csv")
                                   if not l.startswith("#")]))
    assert len(rows) == 20, f"idle samples leaked in: {len(rows)} rows"
