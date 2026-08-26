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
