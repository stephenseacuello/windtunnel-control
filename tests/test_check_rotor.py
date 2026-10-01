"""
The rotor-speed sanity check, tested on sensors whose faults are known.

The sign convention is the whole point of these tests. K = V_oc / rotor_rpm,
so a sensor that MISSES counts pushes K UP — the opposite of what reads
naturally, and it was written backwards the first time. A test that only
checked "K is not flat" would have passed that version.
"""
import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Explicit, not inherited. This module used to pass only when another test
# file happened to import first and left src/ on sys.path; run alone it
# failed with ModuleNotFoundError.
sys.path.insert(0, str(ROOT / "src"))
HDR = ["fan_rpm", "wind_mps", "blade", "demand_a", "held_a", "volts", "amps",
       "watts", "tracking", "note", "fan_rpm_actual", "motor_amps",
       "turbine_rpm"]


K_TRUE = 0.0182          # V per rotor rpm, by construction


def _sweep(path, count_error=0.0, rpm_col="turbine_rpm", droop_top=0.45,
           blanks=0):
    """
    A synthetic sweep with a PHYSICALLY HONEST ladder.

    `count_error` > 0 means the sensor MISSES that fraction of counts by the
    top of the wind range; < 0 means it sees extras; 0 is a perfect sensor.

    `droop_top` is the fraction of rotor speed lost between the lightest and
    heaviest dwell at the TOP of the wind range, tapering to 5% at the bottom.
    **This is the part the first version of these tests left out**, and leaving
    it out is what let a real bug through: with the same rotor rpm written on
    every ladder row, the median over the ladder equals the open-circuit value
    and an operating-point mismatch in check_rotor cancelled exactly.

    A rotor MUST slow as current is drawn — that is where the power comes
    from — so a fixture that holds it constant is not a simplification, it is
    the one shape that cannot detect the bug.
    """
    hdr = [rpm_col if c == "turbine_rpm" else c for c in HDR]
    written = 0
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(hdr)
        for i, fan in enumerate(range(500, 1900, 100)):
            mps = 0.02132 * fan - 0.424
            rotor_oc = 62.0 * mps
            droop = 0.05 + (droop_top - 0.05) * (i / 13.0)
            for j in range(6):
                a = 0.002 + j * 0.02
                rotor = rotor_oc * (1.0 - droop * (j / 5.0))
                v = K_TRUE * rotor            # sensor exact on every row
                seen = rotor * (1.0 - count_error * (i / 13.0))
                # Blanks fill from the HEAVIEST dwell backwards. That is
                # where a genuine blank comes from — a stalled or barely
                # turning rotor puts no pulses in the window. Blanks at the
                # LIGHT end mean something else entirely: the rotor is
                # fastest there, so that is the reed running out of
                # bandwidth, and test_dropout_at_the_light_end covers it.
                cell = "" if j >= 6 - blanks else f"{seen:.1f}"
                written += 1
                w.writerow([fan, f"{mps:.3f}", "syn", a, a, f"{v:.4f}", a,
                            f"{v*a:.5f}", 1, "", fan - 8, 9.0, cell])
    return path


def _run(path):
    r = subprocess.run([sys.executable, str(ROOT / "src" / "check_rotor.py"),
                        str(path)], capture_output=True, text=True)
    return r.returncode, r.stdout


def test_clean_sensor_passes(tmp_path):
    code, out = _run(_sweep(tmp_path / "good.csv", 0.0))
    assert code == 0, out
    assert "K is constant" in out


def test_missing_counts_reads_as_K_RISING(tmp_path):
    """The reed's real failure. K must go UP, not down."""
    code, out = _run(_sweep(tmp_path / "miss.csv", 0.25))
    assert code == 1, out
    assert "K RISES" in out
    assert "MISSING counts" in out
    assert "out of bandwidth" in out
    assert "K FALLS" not in out


def test_extra_counts_reads_as_K_FALLING(tmp_path):
    """Contact bounce: more passes seen than happened."""
    code, out = _run(_sweep(tmp_path / "extra.csv", -0.25))
    assert code == 1, out
    assert "K FALLS" in out
    assert "EXTRA counts" in out
    assert "MISSING counts" not in out


def test_says_so_when_the_column_is_absent(tmp_path):
    """Both banked sweeps are in this state; it must not look like success."""
    p = tmp_path / "norpm.csv"
    _sweep(p, 0.0)
    rows = list(csv.reader(open(p)))
    keep = [i for i, c in enumerate(rows[0]) if c != "turbine_rpm"]
    with open(p, "w", newline="") as f:
        csv.writer(f).writerows([[r[i] for i in keep] for r in rows])
    code, out = _run(p)
    assert code == 2, out
    assert "no rotor-speed column" in out
    assert "Re-run it" in out


def test_reads_the_column_the_sweep_actually_writes(tmp_path):
    """
    sweep_core writes `turbine_rpm`. cp_lambda originally looked only for
    `rotor_rpm`/`rpm`, so a good sweep read as one with no rotor data.
    """
    import sweep_core
    assert "turbine_rpm" in sweep_core.POINTS_HEADER
    cp = (ROOT / "src" / "cp_lambda.py").read_text()
    assert '"turbine_rpm"' in cp, "cp_lambda cannot see the sweep's own column"
    for name in ("turbine_rpm", "rotor_rpm", "rpm"):
        code, out = _run(_sweep(tmp_path / f"{name}.csv", 0.0, rpm_col=name))
        assert code == 0, f"{name}: {out}"


# ── the bug the original fixture could not see ────────────────────────────

def test_perfect_sensor_passes_however_hard_the_rotor_droops(tmp_path):
    """
    K = V_oc/rotor_rpm is only a generator constant if both numbers come from
    the SAME dwell. Taking volts at open circuit and rpm as a median over the
    whole ladder inflates K by the droop — and because the ladder loads harder
    at high wind, the inflation grows with wind and reads as a sensor losing
    counts.

    The rig's own StallGuard treats a 60% droop as inside the useful curve, so
    every value here is routine operation, not a stress case.
    """
    for droop in (0.25, 0.45, 0.60):
        code, out = _run(_sweep(tmp_path / f"d{int(droop*100)}.csv",
                                count_error=0.0, droop_top=droop))
        assert code == 0, f"droop {droop}: a PERFECT sensor was failed\n{out}"
        assert "K is constant" in out


def test_K_recovers_the_true_generator_constant(tmp_path):
    """Not just 'flat' — flat at the RIGHT value. 18.200 mV/rpm."""
    _run(_sweep(tmp_path / "k.csv", count_error=0.0, droop_top=0.45))
    r = subprocess.run([sys.executable, str(ROOT / "src" / "check_rotor.py"),
                        str(tmp_path / "k.csv")], capture_output=True, text=True)
    med = [l for l in r.stdout.splitlines() if "K median" in l][0]
    got = float(med.split("K median")[1].split()[0])
    assert abs(got - 1000 * K_TRUE) < 0.05, f"K={got}, true={1000*K_TRUE}"


def test_real_faults_survive_the_fix(tmp_path):
    """The fix must not buy a clean bill of health by going blind."""
    code, out = _run(_sweep(tmp_path / "miss.csv", 0.25, droop_top=0.45))
    assert code == 1 and "MISSING counts" in out, out
    code, out = _run(_sweep(tmp_path / "extra.csv", -0.25, droop_top=0.45))
    assert code == 1 and "EXTRA counts" in out, out


def test_blank_cells_at_the_heavy_end_do_not_condemn_the_run(tmp_path):
    """
    sweep_core leaves turbine_rpm blank when a dwell caught no pulses, which
    at the heaviest load is a rotor that has all but stopped — real data
    about a real state, not a sensor fault.
    """
    code, out = _run(_sweep(tmp_path / "b.csv", 0.0, blanks=2))
    assert code == 0, out


def test_dropout_at_the_light_end_is_not_certified_as_healthy(tmp_path):
    """
    The rotor is fastest at the lightest load, so a reed running out of
    bandwidth loses THOSE dwells first. Dropout removes the fast points rather
    than corrupting them, so whatever survives agrees beautifully and the
    trend test sees nothing — the tool at its most confidently wrong, in the
    exact direction this rig fails.
    """
    p = tmp_path / "drop.csv"
    K, rows = K_TRUE, []
    for i, fan in enumerate(range(500, 1900, 100)):
        mps = 0.02132 * fan - 0.424
        oc = 62.0 * mps
        for j in range(6):
            a = 0.002 + j * 0.02
            rot = oc * (1 - 0.45 * (j / 5.0))
            blank = i >= 7 and j <= 1          # fastest rotor, lightest steps
            rows.append([fan, f"{mps:.3f}", "syn", a, a, f"{K*rot:.4f}", a,
                         f"{K*rot*a:.5f}", 1, "", fan - 8, 9.0,
                         "" if blank else f"{rot:.1f}"])
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HDR)
        w.writerows(rows)

    code, out = _run(p)
    assert code == 1, f"a dropping-out sensor was certified\n{out}"
    assert "survivorship" in out
    assert "trustworthy" not in out


def test_a_clean_run_still_warns_that_scale_is_untested(tmp_path):
    """
    check_rotor tests whether K is CONSTANT, not whether it is RIGHT. A
    debounce counting every pass exactly twice gives a perfectly flat K at
    half its true value and a doubled lambda, and nothing in the data can see
    it. The green verdict must say so.
    """
    code, out = _run(_sweep(tmp_path / "ok.csv", 0.0, droop_top=0.45))
    assert code == 0, out
    assert "CONSTANT, not whether it is RIGHT" in out
    assert "10-turn" in out


def _graded(path, dead_fans, droop=0.45):
    """A perfect sensor that goes entirely blank at the named fan speeds."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HDR)
        for fan in range(500, 1900, 100):
            mps = 0.02132 * fan - 0.424
            oc = 62.0 * mps
            for j in range(6):
                a = 0.002 + j * 0.02
                rot = oc * (1 - droop * (j / 5.0))
                w.writerow([fan, f"{mps:.3f}", "syn", a, a,
                            f"{K_TRUE*rot:.4f}", a, f"{K_TRUE*rot*a:.5f}", 1,
                            "", fan - 8, 9.0,
                            "" if fan in dead_fans else f"{rot:.1f}"])
    return path


def test_whole_speeds_lost_at_the_TOP_is_a_ceiling_not_missing_data(tmp_path):
    """
    Losing entire wind speeds used to score BETTER than losing part of one:
    open_circuit_row returned (None, 0), so nothing was recorded as blanked
    and the survivorship guard never ran. K over what survived is flat
    precisely because the hard points are gone.
    """
    code, out = _run(_graded(tmp_path / "c.csv", set(range(1600, 1900, 100))))
    assert code == 1, f"a reed with a bandwidth ceiling was certified\n{out}"
    assert "ceiling" in out
    assert "1600" in out                      # it names the break
    assert "trustworthy" not in out


def test_the_run_monday_actually_expects_is_reported_as_a_ceiling(tmp_path):
    """
    NEXT_SESSION plans for roughly the bottom four wind speeds to work and
    asks check_rotor to "name the break". With 10 of 14 dead it used to print
    a green tick.
    """
    code, out = _run(_graded(tmp_path / "p.csv", set(range(900, 1900, 100))))
    assert code == 1, out
    assert "fan 900 is the reed's ceiling" in out


def test_whole_speeds_lost_at_the_BOTTOM_is_legitimate(tmp_path):
    """
    A rotor that is barely turning makes no pulses. That is a real state, and
    failing it would condemn every sweep that starts below cut-in — so the
    check has to be range-aware rather than simply intolerant of gaps.
    """
    code, out = _run(_graded(tmp_path / "l.csv", {500, 600}))
    assert code == 0, out
    assert "BELOW the working range" in out


def test_the_sensor_requirement_is_quoted_at_the_top_of_the_range():
    """
    The text said "this rotor needs 50-70 Hz" — the BOTTOM-of-range figure.
    At 50-70 Hz a 20 Hz reed looks like a 3x shortfall a capacitor might
    close; at fan 1800 the rotor needs ~554 Hz, which is 28x and closes only
    with a different sensor. This is the number someone buys a part from.
    """
    src = (ROOT / "src" / "check_rotor.py").read_text()
    # 308 Hz = 18,500 rpm at fan 1800, MEASURED on 1 Sept. Supersedes 554,
    # which came from the firmware comment's "~66 rev/s at fan 500" — itself
    # a bounced count, inflated ~1.8x, right in the measured bounce ratio.
    assert "308" in src
    assert "554" not in src
    assert "50–70 Hz" not in src and "50-70 Hz" not in src
