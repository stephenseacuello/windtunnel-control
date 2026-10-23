"""
test_section_balance.py — the blade-section force balance, with no hardware.

The analysis turns raw HX711 counts into Cd and Cl through a calibration
matrix with cross-talk, wind-off zeros interpolated in time, a support tare
and a blockage correction. Every one of those steps can be wrong and still
give a plausible coefficient. So the central test runs a simulated session
with KNOWN coefficients through the real logger and the real analysis, checks
that what comes out is what went in, and then removes a correction to check
that the answer moves by what that correction is worth.

The simulator speaks the firmware's line protocol. Tests at the top pin the
two together, so the simulator cannot drift into testing a board that does
not exist.
"""

import csv
import math
import os
import re
import select
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import section_balance_analyze as an                         # noqa: E402
import section_balance_logger as lg                          # noqa: E402

INO = (ROOT / "firmware" / "section_balance" / "section_balance.ino").read_text()
LOGGER_SRC = (ROOT / "scripts" / "section_balance_logger.py").read_text()
README = ROOT / "firmware" / "section_balance" / "README.md"

TRUTH = lg.SIM_DEFAULTS["coefficients"]
RIG = {"span_m": 0.100, "lift_sign": -1, "test_section": {"area_m2": 0.30},
       "maskell_theta": 2.5, "u_maskell_theta": 0.0, "u_U_sys_rel": 0.0,
       "u_rho_rel": 0.0, "draws": 2000}


def quiet(*_a, **_k):
    pass


def calibration_commands():
    c = ["air 18.0", "cal d 0"] + [f"cal d {m} +" for m in (500, 1000, 2000)] + ["cal d 0"]
    for m in (500, 1000, 2000):
        c += [f"cal l {m} +", f"cal l {m} -"]
    return c + ["cal l 0", "fit", "cleared"]


def campaign_commands(sets=("Plain", "FS0.20"), alphas=(0, 90, 180), rpms=(500, 1100, 1800)):
    c = calibration_commands() + ["set support", "alpha 0", "zero"]
    for r in rpms:
        c += [f"rpm {r}", "support"]
    c += ["rpm 0", "zero"]
    for s in sets:
        c += [f"set {s}", "mount"]
        for a in alphas:
            c += [f"alpha {a}", "zero"]
            for r in rpms:
                c += [f"rpm {r}", "wind"]
                if a == 180 and r == 1100:
                    c += ["burst 4000"]
            c += ["rpm 0", "zero"]
    return c


def run_session(folder, commands, truth=None, seed=7, link_wrapper=None):
    sim = lg.SimulatedBalance(truth, seed=seed)
    link = link_wrapper(sim) if link_wrapper else sim
    b = lg.Balance(link, "SIM", out=quiet)
    b.identify()
    s = lg.Session(b, folder, balance_cfg_path=Path(folder).parent / "balance.json",
                   save_cal=False, out=quiet)
    try:
        for line in commands:
            lg.execute(s, line)
    finally:
        s.close()
    return Path(folder)


def analyse(folder, out, **rig_over):
    rig = an.load_rig(None, {**RIG, **rig_over})
    return an.analyse([folder], rig, out_dir=out, plots=False, echo=quiet)


@pytest.fixture(scope="module")
def campaign(tmp_path_factory):
    base = tmp_path_factory.mktemp("balance")
    folder = run_session(base / "campaign", campaign_commands())
    res = analyse(folder, base / "analysis")
    return folder, res, base


def truth(set_name, alpha):
    return tuple(TRUTH[set_name][str(int(alpha))])


# ── the firmware and the logger describe the same board ────────────────────

class TestFirmwareAndLoggerAgree:
    def test_the_row_header_is_the_same_string(self):
        """A reordered column on one side would be parsed as the wrong force."""
        m = re.search(r'ROW_HEADER\s*=\s*"([^"]+)"', INO.replace('"\n    "', ""))
        assert m, "ROW_HEADER not found in the sketch"
        assert m.group(1) == lg.HEADER_LINE

    def test_the_flag_bits_are_the_same(self):
        for name, val in (("FLAG_DRAG_FRESH", lg.FLAG_DRAG_FRESH),
                          ("FLAG_LIFT_FRESH", lg.FLAG_LIFT_FRESH),
                          ("FLAG_DRAG_SAT", lg.FLAG_DRAG_SAT),
                          ("FLAG_LIFT_SAT", lg.FLAG_LIFT_SAT)):
            m = re.search(rf"{name}\s*=\s*(\d+)", INO)
            assert m and int(m.group(1)) == val, name

    def test_the_simulator_offers_exactly_the_firmware_commands(self):
        """The simulator is only a fair stand-in if its command set is the board's."""
        m = re.search(r'Serial\.println\("OK HELP ([^)]*)\);', INO, re.S)
        fw = re.sub(r'"\s*"', "", m.group(1)).strip('"')
        sim = lg.SimulatedBalance()
        sim.reset_input_buffer()
        sim.write(b"HELP\n")
        assert sim.readline().decode().strip() == "OK HELP " + fw

    def test_both_use_standard_gravity(self):
        m = re.search(r"G_STD\s*=\s*([\d.]+)f", INO)
        assert float(m.group(1)) == lg.G_STD

    def test_a_row_parses_and_a_broken_one_does_not(self):
        r = lg.parse_row("F,123456,7,90.00,1500000,-90000,0.12345,nan,3")
        assert r["drag_counts"] == 1500000 and r["flags"] == 3 and math.isnan(r["lift_n"])
        assert lg.parse_row("F,123456,7,90.00,1500000") is None
        assert lg.parse_row("OK START") is None


# ── it never touches the drive's port ─────────────────────────────────────

class TestItNeverDisturbsTheDrive:
    CFG = {"transport": {"port": "/dev/cu.usbmodem1101"},
           "tunnel_node": {"port": "/dev/cu.usbmodem14301"}}

    def test_autodetect_excludes_the_drive_and_the_node(self):
        p = lg.resolve_port(None, {}, self.CFG, ports=[
            "/dev/cu.usbmodem1101", "/dev/cu.usbmodem14301", "/dev/cu.usbmodem2201"])
        assert p == "/dev/cu.usbmodem2201"

    def test_it_refuses_rather_than_guessing(self):
        with pytest.raises(lg.BalanceError, match="several candidate ports"):
            lg.resolve_port(None, {}, self.CFG, ports=[
                "/dev/cu.usbmodem1101", "/dev/cu.usbmodem2201", "/dev/cu.usbmodem2202"])

    def test_the_tunnel_nodes_port_needs_an_explicit_choice(self):
        """It may be the same board reflashed, or the dashboard may hold it."""
        with pytest.raises(lg.BalanceError, match="TUNNEL NODE"):
            lg.resolve_port(None, {}, self.CFG, ports=[
                "/dev/cu.usbmodem1101", "/dev/cu.usbmodem14301"])
        assert lg.resolve_port("/dev/cu.usbmodem14301", {}, self.CFG, ports=[]) \
            == "/dev/cu.usbmodem14301"

    def test_it_listens_before_it_writes(self):
        i = LOGGER_SRC.index("def open_serial")
        body = LOGGER_SRC[i:i + 2000]
        assert "sniff" in body and body.index("sniff") < body.index(".command(")

    def test_it_imports_nothing_that_can_command_the_rig(self):
        for mod in ("acs550", "transport", "chroma_load", "pymodbus", "sweep_core"):
            assert not re.search(rf"^\s*(import|from)\s+{mod}\b", LOGGER_SRC, re.M), mod


# ── calibration ───────────────────────────────────────────────────────────

class TestCalibration:
    def test_the_fit_recovers_k_and_its_cross_talk_through_drift(self):
        import numpy as np
        rng = np.random.default_rng(3)
        K = np.array([[2.0e5, 0.08e5], [-0.05e5, 1.7e5]])
        pts, t = [], 0.0
        for F in [(0, 0), (5, 0), (10, 0), (0, 0), (0, 5), (0, -5), (0, 10), (0, 0)]:
            t += 30.0
            r = np.array([4e4, -2e4]) + np.array([2.0, -1.5]) * t + K @ np.array(F, float)
            r += rng.normal(0, 3.0, 2)
            pts.append({"F_drag": F[0], "F_lift": F[1], "t_s": t,
                        "drag_counts": r[0], "lift_counts": r[1]})
        fit = lg.fit_k(pts)
        assert fit["drift_fitted"]
        assert np.allclose(fit["K"], K, rtol=2e-4, atol=20)
        assert fit["crosstalk"]["lift_counts_per_drag_counts"] == pytest.approx(-0.025, abs=1e-4)

    def test_an_axis_never_loaded_is_refused(self):
        pts = [{"F_drag": f, "F_lift": 0.0, "t_s": i, "drag_counts": 1e5 * f,
                "lift_counts": 0.0} for i, f in enumerate((0, 1, 2, 3))]
        with pytest.raises(lg.BalanceError, match="lift axis"):
            lg.fit_k(pts)


# ── the synthetic campaign: known in, known out ───────────────────────────

class TestSyntheticCampaign:
    def test_every_coefficient_is_recovered(self, campaign):
        _, res, _ = campaign
        assert len(res["groups"]) == 18
        for (s, a, U), g in res["groups"].items():
            cd, cl = truth(s, a)
            got_cd, got_cl = g["Cd"]["summary"]["value"], g["Cl"]["summary"]["value"]
            assert abs(got_cd - cd) <= 0.03 * cd, f"{s} alpha {a} U {U}: Cd {got_cd:.4f} vs {cd}"
            assert abs(got_cl - cl) <= 0.03 * abs(cl) + 0.01, \
                f"{s} alpha {a} U {U}: Cl {got_cl:.4f} vs {cl}"

    def test_the_intervals_cover_the_truth(self, campaign):
        """95 % intervals: at most a couple of 18 may miss, never most."""
        _, res, _ = campaign
        for q, k in (("Cd", 0), ("Cl", 1)):
            inside = sum(g[q]["summary"]["lo"] <= truth(s, a)[k] <= g[q]["summary"]["hi"]
                         for (s, a, U), g in res["groups"].items())
            assert inside >= 16, f"{q}: only {inside} of 18 intervals contain the truth"

    def test_the_planted_differences_come_back(self, campaign):
        _, res, _ = campaign
        assert len(res["diffs"]) == 9
        hits = 0
        for r in res["diffs"]:
            for q, k in (("Cd", 0), ("Cl", 1)):
                true = truth("FS0.20", r["alpha_deg"])[k] - truth("Plain", r["alpha_deg"])[k]
                hits += r[f"d{q}_lo"] <= true <= r[f"d{q}_hi"]
                # Where the planted change is 4 standard uncertainties or more,
                # the 95 % interval must exclude zero.
                u = (r[f"d{q}_hi"] - r[f"d{q}_lo"]) / 3.92
                if abs(true) > 4 * u:
                    assert r[f"d{q}_resolved"] == "yes", (q, r["alpha_deg"], r["U_nom_ms"])
        assert hits >= 16

    def test_every_wind_dwell_had_bracketing_zeros(self, campaign):
        _, res, _ = campaign
        winds = [d for d in res["dwells"] if d["kind"] == "wind"]
        assert winds and all(d["zero"]["kind"] == "bracketed" for d in winds)

    def test_the_blockage_correction_is_worth_what_it_should_be(self, campaign):
        """
        Without the area, nothing is applied and the summary says so. With it,
        alpha 0 at 38 m/s moves by the Maskell factor of that dwell's own drag,
        plus about 1.5 % from correcting the support tare at its own (smaller)
        blockage before it is subtracted.
        """
        folder, res, base = campaign
        bare = analyse(folder, base / "no_area", test_section={"area_m2": None})
        key = ("Plain", 0.0, 38.0)
        corrected = res["groups"][key]["Cd"]["summary"]["value"]
        uncorrected = bare["groups"][key]["Cd"]["summary"]["value"]
        f = res["groups"][key]["blockage"]["nom"]
        assert f > 1.10
        assert f < uncorrected / corrected < 1.03 * f
        text = (base / "no_area" / "summary.txt").read_text()
        assert "NOT APPLIED" in text and "would fall by" in text

    def test_the_support_tare_is_what_keeps_alpha_90_honest(self, campaign):
        """The simulated support drags as much as the slice at alpha 90."""
        folder, res, base = campaign
        raw = analyse(folder, base / "no_tare", support_tare="none")
        key = ("Plain", 90.0, 23.0)
        assert raw["groups"][key]["Cd"]["summary"]["value"] > \
            1.8 * res["groups"][key]["Cd"]["summary"]["value"]
        assert "INCLUDE the support" in (base / "no_tare" / "summary.txt").read_text()

    def test_the_bursts_find_the_shedding_frequency(self, campaign):
        _, res, _ = campaign
        on = [b for b in res["bursts"] if b["U_nom_ms"] > 0]
        assert len(on) == 2
        for b in on:
            assert b["St_measured"] == pytest.approx(0.2232, abs=0.005)
            assert b["peak_over_median"] > 10

    def test_the_plots_are_drawn_when_matplotlib_is_there(self, campaign):
        pytest.importorskip("matplotlib")
        folder, _, base = campaign
        rig = an.load_rig(None, {**RIG, "draws": 300})
        an.analyse([folder], rig, out_dir=base / "plots", plots=True, echo=quiet)
        names = {f.name for f in (base / "plots").glob("*.png")}
        assert {"coefficients_vs_alpha_U023.0.png", "coefficients_vs_U_alpha090.0.png",
                "differences.png", "spectra.png"} <= names

    def test_the_output_files_exist_and_carry_provenance(self, campaign):
        _, res, base = campaign
        out = base / "analysis"
        for f in ("dwells.csv", "coefficients.csv", "differences.csv",
                  "calibration.json", "bursts.csv", "summary.txt"):
            assert (out / f).exists(), f
        text = (out / "summary.txt").read_text()
        for phrase in ("assumed", "NOT CORRECTED", "Cross-talk", "bracketed"):
            assert phrase in text, phrase


# ── zeros: what happens when one is missing ───────────────────────────────

class TestZeros:
    def test_a_dwell_with_no_zero_at_its_alpha_is_excluded(self, tmp_path):
        """The zero moves with alpha (the slice's weight acts at another arm)."""
        cmds = calibration_commands() + ["set Plain", "alpha 0", "zero", "rpm 1100",
                                         "wind", "rpm 0", "zero", "alpha 90", "rpm 1100",
                                         "wind"]
        folder = run_session(tmp_path / "s", cmds)
        res = analyse(folder, tmp_path / "a", support_tare="none")
        w90 = [d for d in res["dwells"] if d["kind"] == "wind" and d["alpha"] == 90]
        assert w90 and w90[0].get("excluded")
        assert any("no wind-off zero" in s for s in w90[0]["status"])
        assert ("Plain", 0.0, 23.0) in res["groups"] and ("Plain", 90.0, 23.0) not in res["groups"]

    def test_a_one_sided_zero_is_used_and_flagged(self, tmp_path):
        cmds = calibration_commands() + ["set Plain", "alpha 0", "zero", "rpm 1100", "wind"]
        folder = run_session(tmp_path / "s", cmds)
        res = analyse(folder, tmp_path / "a", support_tare="none")
        w = [d for d in res["dwells"] if d["kind"] == "wind"][0]
        assert w["zero"]["kind"] == "one-sided"
        assert any("one-sided" in s for s in w["status"])


# ── habits the logger enforces ────────────────────────────────────────────

class TestLoggerHabits:
    def _session(self, tmp_path):
        b = lg.Balance(lg.SimulatedBalance(), "SIM", out=quiet)
        b.identify()
        return lg.Session(b, tmp_path / "s", balance_cfg_path=tmp_path / "b.json",
                          save_cal=False, out=quiet)

    def test_no_wind_dwell_while_calibration_hardware_may_be_in(self, tmp_path):
        """A string, a pulley and masses in the test section must not meet the wind."""
        s = self._session(tmp_path)
        lg.execute(s, "cal d 500 +")
        lg.execute(s, "rpm 1100")
        with pytest.raises(lg.BalanceError, match="calibration hardware"):
            lg.execute(s, "wind")
        lg.execute(s, "cleared")
        lg.execute(s, "wind")
        s.close()

    def test_support_dwells_need_the_support_label(self, tmp_path):
        s = self._session(tmp_path)
        lg.execute(s, "rpm 1100")
        with pytest.raises(lg.BalanceError, match="set support"):
            lg.execute(s, "support")
        s.close()

    def test_zero_rpm_is_zero_wind_not_minus_0_42(self):
        assert lg.wind_from_rpm(0) == 0.0
        assert lg.wind_from_rpm(1100) == pytest.approx(23.03, abs=0.01)

    def test_an_aborted_dwell_keeps_its_rows(self, tmp_path):
        """A five-minute session must not lose minute four to a Ctrl-C."""
        class Interrupting:
            def __init__(self, sim):
                self.sim, self.rows = sim, 0

            def __getattr__(self, k):
                return getattr(self.sim, k)

            def readline(self):
                line = self.sim.readline()
                if line.startswith(b"F,"):
                    self.rows += 1
                    if self.rows == 50:
                        raise KeyboardInterrupt
                return line

        folder = run_session(tmp_path / "s", ["set Plain", "zero"],
                             link_wrapper=Interrupting)
        _, run = lg.read_meta_csv(folder / "runsheet.csv")
        _, trace = lg.read_meta_csv(folder / "trace.csv")
        assert run[0]["use"] == "0" and "aborted" in run[0]["notes"]
        assert len(trace) == 49


# ── the analysis' pieces ──────────────────────────────────────────────────

class TestPieces:
    def test_body_frame_rotation(self):
        """A pure drag, seen by a balance turned 90 deg with the slice, is on its lift axis."""
        D, L = an.to_wind_frame(0.0, 2.0, alpha_deg=90.0, frame="body")
        assert D == pytest.approx(2.0) and L == pytest.approx(0.0, abs=1e-12)
        D, L = an.to_wind_frame(1.0, 0.5, alpha_deg=37.0, lift_sign=-1, frame="wind")
        assert (D, L) == (1.0, -0.5)

    def test_the_cfd_overlay_uses_only_healthy_runs(self):
        cfd, note = an.load_cfd(an.load_rig())
        q = ROOT / an.RIG_DEFAULTS["cfd_quality"]
        if not q.exists():
            pytest.skip("CFD quality table not in this checkout")
        with open(q, newline="") as f:
            flagged = {r["name"] for r in csv.DictReader(f) if r["corrupted"] == "True"}
        names = {c["name"] for c in cfd}
        assert names and not names & flagged
        assert "a090.0_U23.0_SST_medium_Tu1.0" in names
        assert "a180.0_U23.0_SST_medium_Tu1.0" not in names      # flagged
        assert "healthy" in note

    def test_batch_means_does_not_understate_correlated_noise(self):
        import numpy as np
        rng = np.random.default_rng(0)
        e, x = 0.0, []
        for _ in range(3000):
            e = 0.95 * e + rng.normal()
            x.append(e)
        x = np.array(x)
        naive = x.std(ddof=1) / math.sqrt(len(x))
        assert an.batch_se(x) > 3 * naive

    def test_a_rig_sheet_template_round_trips(self, tmp_path):
        p = tmp_path / "rig.json"
        assert an.main(["--write-rig-template", str(p)]) == 0
        rig = an.load_rig(p)
        assert rig["c_ref_m"] == 0.048 and rig["test_section"]["area_m2"] is None


# ── the real serial path, against a pseudo-terminal ───────────────────────

class PtyBoard(threading.Thread):
    """
    The far end of a pseudo-terminal, standing in for the USB port. It either
    speaks the firmware's protocol (through the simulator) or, as the drive
    link does, streams PMC telemetry whatever it is sent.
    """

    def __init__(self, sim=None, chatter=None):
        super().__init__(daemon=True)
        self.master, self.slave = os.openpty()
        self.port = os.ttyname(self.slave)
        self.sim, self.chatter = sim, chatter
        self.received = b""
        self.done = False

    def run(self):
        buf = b""
        while not self.done:
            r, _, _ = select.select([self.master], [], [], 0.01)
            if r:
                data = os.read(self.master, 1024)
                self.received += data
                buf += data
                while self.sim and b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self.sim.write(line + b"\n")
            if self.chatter:
                os.write(self.master, self.chatter)
                time.sleep(0.05)
            elif self.sim:
                for _ in range(20):
                    line = self.sim.readline()
                    if not line:
                        break
                    os.write(self.master, line)

    def close(self):
        self.done = True
        self.join(timeout=2)
        for fd in (self.master, self.slave):
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="needs a pseudo-terminal")
class TestTheSerialPath:
    def test_a_port_streaming_pmc_telemetry_is_closed_untouched(self):
        """
        The rule tunnel_node.py learned: what a port says unprompted is the
        only reliable identity. Nothing may be written to the drive link.
        """
        pytest.importorskip("serial")
        board = PtyBoard(chatter=b"T,812345,RUNNING,1100.00,1096.20,9.10,1.70,637,1,0,0,0,0,0.0\r\n")
        board.start()
        try:
            with pytest.raises(lg.BalanceError, match="DRIVE link"):
                lg.Balance.open_serial(board.port, settle=0.0, out=quiet)
            time.sleep(0.1)
            assert board.received == b"", "something was written to the drive's port"
        finally:
            board.close()

    def test_a_session_runs_over_a_real_serial_port(self, tmp_path):
        pytest.importorskip("serial")
        board = PtyBoard(sim=lg.SimulatedBalance(seed=3))
        board.start()
        try:
            b = lg.Balance.open_serial(board.port, settle=0.0, out=quiet)
            assert "section-balance" in b.identify()
            s = lg.Session(b, tmp_path / "s", balance_cfg_path=tmp_path / "b.json",
                           save_cal=False, out=quiet)
            lg.execute(s, "zero 3")
            lg.execute(s, "burst 500")
            s.close()
            b.close()
        finally:
            board.close()
        _, run = lg.read_meta_csv(tmp_path / "s" / "runsheet.csv")
        _, trace = lg.read_meta_csv(tmp_path / "s" / "trace.csv")
        assert [r["kind"] for r in run] == ["zero", "burst"]
        assert run[0]["use"] == "1" and 25 <= len(trace) <= 31
        assert (tmp_path / "s" / "bursts" / "burst_002.csv").exists()


# ── the command lines, as a user runs them ────────────────────────────────

def test_the_command_lines_run_end_to_end(tmp_path):
    script = tmp_path / "cmds.txt"
    script.write_text("\n".join(calibration_commands() + [
        "set Plain", "alpha 90", "zero", "rpm 1100", "wind 10", "rpm 0", "zero"]) + "\n")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "section_balance_logger.py"),
                        "--simulate", "--script", str(script), "--out", str(tmp_path / "logs"),
                        "--balance-config", str(tmp_path / "b.json"), "--session", "cli"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    folder = next((tmp_path / "logs").glob("*_cli"))
    rig = tmp_path / "rig.json"
    rig.write_text('{"span_m": 0.1, "lift_sign": -1}')
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "section_balance_analyze.py"),
                        str(folder), "--rig", str(rig), "--no-plots", "--draws", "500",
                        "--no-support-tare"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "NOT APPLIED" in r.stdout
    assert (folder / "analysis" / "coefficients.csv").exists()


def test_documented_commands_parse():
    """Every logger or analysis command in the README's code blocks must parse."""
    if not README.exists():
        pytest.skip("no README yet")
    parsers = {"section_balance_logger.py": lg.build_parser(),
               "section_balance_analyze.py": an.build_parser()}
    found = 0
    in_block = False
    for line in README.read_text().splitlines():
        if line.strip().startswith("```"):
            in_block = not in_block
            continue
        m = re.match(r"\s*python3?\s+scripts/(section_balance_\w+\.py)\s*(.*)", line)
        if in_block and m:
            found += 1
            args = [a for a in shlex.split(m.group(2).split("#")[0]) if a != "\\"]
            try:
                parsers[m.group(1)].parse_args(args)
            except SystemExit:
                pytest.fail(f"README command does not parse: {line.strip()}")
    assert found >= 3
