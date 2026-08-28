"""
The comparison is where a campaign's conclusions are actually formed, so its
refusals matter more than its arithmetic. These pin the three failure modes
that produce a plausible number instead of an error.
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import compare_blades as cb          # noqa: E402

REF = REPO / "logs" / "sweep_v1_Ra20_summary.csv"


def _variant(tmp_path, name, *, protocol=None, fmt="old", fit_scale=1.0):
    """
    A copy of the reference sweep with one thing changed.

    fmt="new"      the post-22-Aug layout: BOTH p_max_fit_w and p_max_raw_w
    fmt="fit_only" a file carrying a fit and no raw — must be refused against
                   an old raw-only run, since there is nothing common to
                   compare
    """
    import csv as _csv
    import io
    text = REF.read_text()
    if protocol:
        text = text.replace("# protocol,94bed28333f7", f"# protocol,{protocol}")
    if fmt != "old":
        head = [l for l in text.splitlines(True) if l.startswith("#")]
        body = [l for l in text.splitlines(True) if not l.startswith("#")]
        rows = list(_csv.DictReader(body))
        buf = io.StringIO()
        if fmt == "new":
            cols = ["fan_rpm_cmd", "fan_rpm_actual", "wind_mps", "blade",
                    "p_max_fit_w", "i_at_pmax_fit_a", "p_max_raw_w",
                    "i_at_pmax_raw_a", "v_at_pmax_v", "i_last_a",
                    "limited_by", "clean", "steps", "stopped_by"]
        else:
            cols = ["fan_rpm_cmd", "fan_rpm_actual", "wind_mps", "blade",
                    "p_max_fit_w", "i_at_pmax_fit_a", "v_at_pmax_v",
                    "i_last_a", "limited_by", "clean", "steps", "stopped_by"]
        w = _csv.DictWriter(buf, cols)
        w.writeheader()
        for r in rows:
            o = {c: r.get(c, "") for c in cols}
            o["p_max_fit_w"] = f"{float(r['p_max_w']) * fit_scale:.4f}"
            o["i_at_pmax_fit_a"] = r["i_at_pmax_a"]
            if "p_max_raw_w" in cols:
                o["p_max_raw_w"] = r["p_max_w"]
                o["i_at_pmax_raw_a"] = r["i_at_pmax_a"]
            w.writerow(o)
        text = "".join(head) + buf.getvalue()
    p = tmp_path / f"sweep_{name}_summary.csv"
    p.write_text(text)
    return p


def _run(*args):
    return subprocess.run(
        [sys.executable, str(REPO / "src" / "compare_blades.py"), *args],
        capture_output=True, text=True)


class TestRefusals:
    def test_mismatched_fingerprint_refuses(self, tmp_path):
        other = _variant(tmp_path, "other", protocol="deadbeef0000")
        r = _run(str(REF), str(other))
        assert r.returncode == 2, "a protocol mismatch must not produce a number"
        assert "PROTOCOL MISMATCH" in r.stdout

    def test_force_proceeds_but_says_so(self, tmp_path):
        other = _variant(tmp_path, "other", protocol="deadbeef0000")
        r = _run(str(REF), str(other), "--force")
        assert r.returncode == 0
        assert "NOT a blade comparison" in r.stdout

    def test_missing_sweep_is_an_error_not_an_empty_result(self):
        r = _run("v1_Ra20", "no_such_blade_anywhere")
        assert r.returncode != 0
        assert "no sweep found" in (r.stdout + r.stderr)


class TestColumnEquivalence:
    """
    The summary format gained parabolic-fit columns on 22 Aug. Comparing a fit
    against an argmax injects the argmax's upward bias (~1.3% on the reference
    sweep) straight into the difference — the same size as the effects being
    hunted.
    """

    def test_raw_is_used_when_either_side_predates_the_fit(self, tmp_path):
        new = _variant(tmp_path, "new", fmt="new")
        col_a, col_b, why = cb.pick_column(cb.load(str(REF)), cb.load(str(new)))
        assert col_a == "p_max_w" and col_b == "p_max_raw_w"
        assert "fit" not in col_a and "fit" not in col_b
        assert "argmax" in why

    def test_a_fit_never_gets_compared_against_an_argmax(self, tmp_path):
        """
        The whole point of the column logic. A fit-vs-argmax comparison would
        inject the argmax's upward bias into the difference, so if the two
        runs share no like-for-like column the tool must refuse rather than
        reach across.
        """
        fit_only = _variant(tmp_path, "fitonly", fmt="fit_only")
        with pytest.raises(SystemExit):
            cb.pick_column(cb.load(str(REF)), cb.load(str(fit_only)))

    def test_choosing_raw_changes_the_answer(self, tmp_path):
        """
        Not hypothetical: pick the fit on one side and the argmax on the other
        and the level shifts by the bias, not by anything physical.
        """
        new = _variant(tmp_path, "new", fmt="new", fit_scale=0.987)
        A, B = cb.load(str(REF)), cb.load(str(new))
        honest = cb.analyse(cb.paired(A, B, *cb.pick_column(A, B)[:2]))
        crossed = cb.analyse(cb.paired(A, B, "p_max_w", "p_max_fit_w"))
        assert honest["level"] == pytest.approx(0.0, abs=1e-9)
        assert crossed["level"] == pytest.approx(-0.013, abs=1e-3)

    def test_fit_preferred_when_both_have_it(self, tmp_path):
        x = _variant(tmp_path, "x", fmt="new")
        y = _variant(tmp_path, "y", fmt="new")
        col_a, col_b, why = cb.pick_column(cb.load(str(x)), cb.load(str(y)))
        assert col_a == col_b == "p_max_fit_w"
        assert "fit" in why

    def test_reference_p_max_w_really_is_the_raw_argmax(self):
        """
        Not an assumption — the claim the tool's column choice rests on.
        Every summary value must equal the largest single dwell in the points
        file for the same fan speed.
        """
        import csv
        from collections import defaultdict
        body = [l for l in (REPO / "logs" / "sweep_v1_Ra20_points.csv")
                .read_text().splitlines(True) if not l.startswith("#")]
        pts = defaultdict(list)
        for r in csv.DictReader(body):
            if r.get("tracking") not in (None, "", "1", "True", "true"):
                continue
            pts[int(float(r["fan_rpm"]))].append(float(r["watts"]))
        sb = [l for l in REF.read_text().splitlines(True)
              if not l.startswith("#")]
        checked = 0
        for r in csv.DictReader(sb):
            rpm = int(float(r["fan_rpm_actual"]))
            cand = [v for k, v in pts.items() if abs(k - rpm) < 25]
            if not cand:
                continue
            assert max(cand[0]) == pytest.approx(float(r["p_max_w"]), abs=5e-4)
            checked += 1
        assert checked == 14


class TestAnalysis:
    def test_identical_runs_give_exactly_zero(self):
        a = cb.load(str(REF))
        col_a, col_b, _ = cb.pick_column(a, a)
        r = cb.analyse(cb.paired(a, a, col_a, col_b))
        assert r["level"] == pytest.approx(0.0, abs=1e-12)
        assert r["dn"] == pytest.approx(0.0, abs=1e-12)
        assert r["n"] == 14

    def test_a_uniform_shift_moves_the_level_and_not_the_exponent(self):
        """The reason the tool leads with LEVEL rather than Δn."""
        a = cb.load(str(REF))
        pts = cb.paired(a, a, "p_max_w", "p_max_w")
        for p in pts:                       # every point 5% higher
            p["pb"] *= 1.05
            p["ratio"] = p["pb"] / p["pa"]
        r = cb.analyse(pts)
        assert r["level"] == pytest.approx(0.05, abs=1e-9)
        assert r["dn"] == pytest.approx(0.0, abs=1e-9), \
            "a uniform change must leave the exponent untouched"


class TestRotorRpmWindow:
    """
    The sampler is the only source of rotor speed, so its windowing decides
    whether the column has numbers in it or is silently blank.
    """

    def _watch(self, samples):
        import blade_sweep as bs
        w = bs.DriveWatch.__new__(bs.DriveWatch)
        w._samples = samples
        import threading
        w._lock = threading.Lock()
        w.rpm = w.amps = 0.0
        return w

    def test_one_sample_per_dwell_still_yields_a_number(self):
        """
        The bug this guards: at a 1 s tick and a 1 s dwell there is usually
        exactly ONE sample inside the window. Requiring two strictly inside
        returned None for every dwell, and the run produced a blank column.
        """
        # (t, fan_rpm, amps, pulses, last_us) — 60 rpm rotor, 1 pulse/rev
        ss = [(t, 1800.0, 9.0, t, int(t * 1e6)) for t in range(0, 5)]
        w = self._watch(ss)
        got = w.rotor_rpm_between(2.4, 3.4)
        assert got is not None
        assert got == pytest.approx(60.0, rel=1e-6)

    def test_stopped_rotor_is_none_not_zero(self):
        ss = [(t, 1800.0, 9.0, 7, 7_000_000) for t in range(0, 5)]
        assert self._watch(ss).rotor_rpm_between(1.0, 4.0) is None

    def test_micros_rollover_does_not_invent_a_huge_interval(self):
        hi = 0xFFFFFFFF - 500_000
        ss = [(0.0, 1800.0, 9.0, 10, hi),
              (1.0, 1800.0, 9.0, 11, (hi + 1_000_000) & 0xFFFFFFFF)]
        got = self._watch(ss).rotor_rpm_between(0.0, 1.0)
        assert got == pytest.approx(60.0, rel=1e-6)

    def test_firmware_without_rpm_gives_none_not_a_wrong_number(self):
        """v2/v3 report no pulse fields; the column must be blank, not zero."""
        ss = [(t, 1800.0, 9.0, None, None) for t in range(0, 5)]
        assert self._watch(ss).rotor_rpm_between(1.0, 4.0) is None


class TestArchiveProtectsBankedRuns:
    """
    Both front ends wrote to logs/sweep_<blade>_*.csv and both overwrote. The
    dashboard's "archive copy" ran AFTER the write and copied the file it had
    just produced — so a re-run destroyed the earlier curve and archived the
    new one. The CLI had no archive at all.

    v1_Ra20 is one of two blade runs this project has and the baseline for its
    only result.
    """

    def _core(self):
        import sweep_core
        return sweep_core

    def test_an_existing_run_is_moved_not_overwritten(self, tmp_path):
        sm = tmp_path / "sweep_v1_Ra20_summary.csv"
        pt = tmp_path / "sweep_v1_Ra20_points.csv"
        sm.write_text("ORIGINAL SUMMARY")
        pt.write_text("ORIGINAL POINTS")

        moved = self._core().archive_existing(tmp_path, "v1_Ra20")

        assert len(moved) == 2, "both files must move together"
        assert not sm.exists() and not pt.exists(), \
            "the canonical names must be free for the new run"
        texts = {(tmp_path / m).read_text() for m in moved}
        assert texts == {"ORIGINAL SUMMARY", "ORIGINAL POINTS"}, \
            "the archived copies do not contain the original data"

    def test_the_stamp_comes_from_the_data_not_the_move(self, tmp_path):
        """
        An archive stamped with the moment it was displaced tells you nothing.
        Stamped from the file's mtime it says when the data was taken.
        """
        import os, time
        f = tmp_path / "sweep_x_summary.csv"
        f.write_text("data")
        old = time.time() - 86400 * 3          # three days ago
        os.utime(f, (old, old))
        moved = self._core().archive_existing(tmp_path, "x")
        want = time.strftime("%Y%m%d_%H%M%S", time.localtime(old))
        assert want in moved[0], \
            f"archive is stamped {moved[0]}, not from the data's date {want}"

    def test_a_second_archive_does_not_clobber_the_first(self, tmp_path):
        import os, time
        stamp = time.time() - 86400
        names = []
        for _ in range(2):
            f = tmp_path / "sweep_y_summary.csv"
            f.write_text("run")
            os.utime(f, (stamp, stamp))        # identical mtime, on purpose
            names += self._core().archive_existing(tmp_path, "y")
        assert len(set(names)) == 2, \
            f"two archives collapsed onto one name: {names}"

    def test_nothing_to_archive_is_not_an_error(self, tmp_path):
        assert self._core().archive_existing(tmp_path, "never_run") == []


def test_both_front_ends_archive_before_writing():
    """A fix that lands in one caller and not the other is not a fix."""
    ctl = (REPO / "webapp" / "controller.py").read_text()
    cli = (REPO / "src" / "blade_sweep.py").read_text()
    assert "archive_existing" in ctl, "the dashboard does not archive"
    assert "archive_existing" in cli, "the CLI does not archive"
    assert "shutil.copy2(sp" not in ctl, \
        "the dashboard is copying the file it just wrote again"
