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
