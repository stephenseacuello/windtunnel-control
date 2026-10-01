"""
The Monday chain: sweep writes turbine_rpm -> check_rotor -> cp_lambda.

Each link was broken in a different way, and every break produced a message
pointing somewhere other than the real cause.
"""
import csv
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

HDR = ["fan_rpm", "wind_mps", "blade", "demand_a", "held_a", "volts", "amps",
       "watts", "tracking", "note", "fan_rpm_actual", "motor_amps",
       "turbine_rpm"]


def _points(path, blanks=0):
    K = 0.0182
    written = 0
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HDR)
        for i, fan in enumerate(range(500, 1900, 100)):
            mps = 0.02132 * fan - 0.424
            oc = 62.0 * mps
            droop = 0.05 + 0.40 * (i / 13.0)
            for j in range(6):
                a = 0.002 + j * 0.02
                rotor = oc * (1.0 - droop * (j / 5.0))
                v = K * rotor
                cell = "" if written < blanks else f"{rotor:.1f}"
                written += 1
                w.writerow([fan, f"{mps:.3f}", "syn", a, a, f"{v:.4f}", a,
                            f"{v*a:.5f}", 1, "", fan - 8, 9.0, cell])
    return path


def _cp(path, *extra):
    r = subprocess.run(
        [sys.executable, str(ROOT / "src" / "cp_lambda.py"), "--sweep",
         str(path), "--radius", "0.1016", "--rotor", "vawt",
         "--height", "0.2451", *extra], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_turbine_rpm_needs_no_flag(tmp_path):
    """
    A sweep that recorded rotor speed must just work.

    It used to exit 1 with "No rotor speed. Give one of: ..." while holding a
    populated turbine_rpm column, and the remedy list presented --rpm-column
    and --assume-lambda as peers. --assume-lambda fabricates rotor speed from
    an assumed lambda, so the Cp(lambda) it returns can only give back the
    lambda it was fed. At the rig, at the end of a session, that is the wrong
    one to reach for.
    """
    code, out = _cp(_points(tmp_path / "p.csv"))
    assert code == 0, out
    assert "peak Cp_elec" in out


def test_partial_blanks_do_not_reject_the_whole_sweep(tmp_path):
    """
    sweep_core writes a blank whenever a dwell's rotor window caught no
    pulses. Requiring every row to be populated discarded all fourteen wind
    speeds over one missing dwell, and said "has no rotor-rpm column" about a
    file that plainly had one.
    """
    code, out = _cp(_points(tmp_path / "b.csv", blanks=9))
    assert code == 0, out
    assert "skipped" in out
    assert "peak Cp_elec" in out


def test_an_entirely_empty_column_says_so_precisely(tmp_path):
    code, out = _cp(_points(tmp_path / "e.csv", blanks=10_000))
    assert code != 0
    assert "every cell is empty" in out
    assert "Re-run it" in out


def test_assume_lambda_is_marked_circular(tmp_path):
    """The refusal text must not offer it as an equal option."""
    p = tmp_path / "norpm.csv"
    _points(p)
    rows = list(csv.reader(open(p)))
    keep = [i for i, c in enumerate(rows[0]) if c != "turbine_rpm"]
    with open(p, "w", newline="") as f:
        csv.writer(f).writerows([[r[i] for i in keep] for r in rows])
    code, out = _cp(p)
    assert code != 0
    assert "circular" in out
    assert "needs NO flag" in out


def test_swept_area_is_the_cylinder(tmp_path):
    """2*R*H = 0.0498 m2. pi*R^2 would be 0.0324 — a 54% error in Cp."""
    import cp_lambda
    a = cp_lambda.swept_area(0.1016, 0.0, "vawt", 0.2451)
    assert abs(a - 2 * 0.1016 * 0.2451) < 1e-9
    assert abs(a - 0.0498) < 1e-3


# ── the protocol hash ─────────────────────────────────────────────────────

def _args(as_float):
    import sweep_core as sc
    C = dict(sc.CAMPAIGN)
    cv = ((lambda v: float(v) if isinstance(v, (int, float))
           and not isinstance(v, bool) else v) if as_float else (lambda v: v))
    d = {k: cv(v) for k, v in C.items()}
    d.update(min_step=cv(C["step_amps"]), floor_amps=cv(0.0), percent=cv(80.0),
             dwell=cv(C["dwell"]), step_frac=cv(0.0),
             collapse_frac=cv(C["collapse_frac"]), confirm=2,
             step_scaling="v2", blade="x", notes="", fan_rpm=cv(1800))
    return SimpleNamespace(**d), C


def test_int_and_float_are_the_same_protocol():
    """
    argparse leaves --stop-rpm an int; the dashboard float()s every field. The
    two used to hash to different protocol_full values, so compare_blades
    called two IDENTICAL ladders "NOT comparable" — on exactly the
    dashboard-vs-CLI pairing planned for v1_Ra20_repeat. Formatting is not
    protocol.
    """
    import sweep_core as sc
    ai, C = _args(False)
    af, _ = _args(True)
    a = sc.protocol(ai, C["volt_off"], C["range"])
    b = sc.protocol(af, C["volt_off"], C["range"])
    assert a["protocol_full"] == b["protocol_full"]
    assert a["protocol_extra"] == b["protocol_extra"]


def test_the_campaign_fingerprint_did_not_move():
    """Both banked runs are stamped 94bed28333f7. It must never drift."""
    import sweep_core as sc
    ai, C = _args(False)
    assert sc.protocol(ai, C["volt_off"], C["range"])["protocol"] \
        == "94bed28333f7"


# ── the explicit-column flag ──────────────────────────────────────────────

def _shaft(path, col="shaft_rpm", blanks=0):
    hdr = [col if c == "turbine_rpm" else c for c in HDR]
    K, written = 0.0182, 0
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(hdr)
        for i, fan in enumerate(range(500, 1900, 100)):
            mps = 0.02132 * fan - 0.424
            oc = 62.0 * mps
            for j in range(6):
                a = 0.002 + j * 0.02
                rot = oc * (1 - 0.30 * (j / 5.0))
                v = K * rot
                cell = "" if written < blanks else f"{rot:.1f}"
                written += 1
                w.writerow([fan, f"{mps:.3f}", "syn", a, a, f"{v:.4f}", a,
                            f"{v*a:.5f}", 1, "", fan - 8, 9.0, cell])
    return path


def test_rpm_column_actually_reads_that_column(tmp_path):
    """
    --rpm-column never reached read_sweep(). A fully populated `shaft_rpm`
    plus `--rpm-column shaft_rpm` exited 1 saying "every cell is empty ...
    Re-run it" — a confident message pointing at a sensor fault that did not
    exist, and the refusal text recommends this very flag for exactly this
    case.
    """
    code, out = _cp(_shaft(tmp_path / "s.csv"), "--rpm-column", "shaft_rpm")
    assert code == 0, out
    assert "peak Cp_elec" in out
    assert "empty" not in out


def test_a_mistyped_rpm_column_is_refused_not_ignored(tmp_path):
    """
    A typo used to exit 0 and stamp the nonexistent name into the result's
    provenance line while the numbers came from a different column.
    """
    code, out = _cp(_shaft(tmp_path / "s.csv"), "--rpm-column", "shaft_rmp")
    assert code != 0
    assert "not a column" in out
    assert "shaft_rpm" in out          # it lists what IS there


def test_the_banner_and_the_arithmetic_name_the_same_column(tmp_path):
    """
    The detection loop broke on the first match; the value loop had no break,
    so the LAST populated name won. A file with both turbine_rpm and rotor_rpm
    reported 'turbine_rpm' while computing lambda from rotor_rpm.
    """
    import cp_lambda
    p = tmp_path / "both.csv"
    _points(p)
    rows = list(csv.reader(open(p)))
    rows[0].append("rotor_rpm")
    for r in rows[1:]:
        r.append(str(2 * float(r[12])))       # double, so a swap is obvious
    with open(p, "w", newline="") as f:
        csv.writer(f).writerows(rows)
    parsed, col, _ = cp_lambda.read_sweep(p)
    assert col == "turbine_rpm"
    first = next(r for r in parsed if "rpm" in r)
    src = next(r for r in csv.DictReader(open(p)) if r["turbine_rpm"])
    assert abs(first["rpm"] - float(src["turbine_rpm"])) < 1e-6, \
        "banner says turbine_rpm but the value came from rotor_rpm"


def test_compute_refuses_to_guess_the_swept_area(tmp_path):
    """A silent pi*R^2 default inflated every Cp by 53.6% for any caller."""
    import cp_lambda
    import pytest
    with pytest.raises(ValueError, match="explicit swept area"):
        cp_lambda.compute([{"mps": 10.0, "p_w": 1.0, "rpm": 600}], 0.1016)


def test_missing_height_is_a_clean_refusal(tmp_path):
    code, out = _cp(_points(tmp_path / "p.csv"))
    assert code == 0
    r = subprocess.run(
        [sys.executable, str(ROOT / "src" / "cp_lambda.py"), "--sweep",
         str(tmp_path / "p.csv"), "--radius", "0.1016", "--rotor", "vawt"],
        capture_output=True, text=True)
    assert r.returncode != 0
    assert "Traceback" not in r.stderr, "a stack trace reads as a broken tool"
    assert "BLADE HEIGHT" in (r.stdout + r.stderr)
