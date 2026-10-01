"""
The OpenFOAM driver.

Everything here runs WITHOUT OpenFOAM installed — the parsing and the safety
boundaries are the parts that must not regress, and neither needs a solver.
The one test that does need it is skipped rather than failed, because this
repo also runs on the tunnel PC and in CI.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import openfoam as of            # noqa: E402


# ── parsing: real solver output, copied verbatim ─────────────────────────

SAMPLE = """Time = 1

smoothSolver:  Solving for Ux, Initial residual = 1, Final residual = 0.0538101, No Iterations 1
smoothSolver:  Solving for Uy, Initial residual = 1, Final residual = 0.030925, No Iterations 2
GAMG:  Solving for p, Initial residual = 1, Final residual = 0.068427, No Iterations 17
time step continuity errors : sum local = 1.19733, global = 0.179883, cumulative = 0.179883
smoothSolver:  Solving for epsilon, Initial residual = 0.199978, Final residual = 0.0100279, No Iterations 3
bounding epsilon, min: -1.98669 max: 1080.25 average: 47.5306
smoothSolver:  Solving for k, Initial residual = 1, Final residual = 0.0439206, No Iterations 3
ExecutionTime = 0.14 s  ClockTime = 3 s

Time = 2

smoothSolver:  Solving for Ux, Initial residual = 0.437825, Final residual = 0.030824, No Iterations 5
GAMG:  Solving for p, Initial residual = 0.052242, Final residual = 0.00424172, No Iterations 15
SIMPLE solution converged in 283 iterations
"""


def test_parses_a_real_solver_transcript():
    st = {}
    for line in SAMPLE.splitlines():
        of.parse_line(line, st)
    assert st["time"] == 2.0
    assert st["converged"] == 283
    assert st["exec_s"] == 0.14
    assert set(st["residuals"]) == {"Ux", "Uy", "p", "epsilon", "k"}
    assert st["residuals"]["Ux"] == [(1.0, 1.0), (2.0, 0.437825)]
    assert st["residuals"]["epsilon"] == [(1.0, 0.199978)]


def test_takes_the_INITIAL_residual_not_the_final():
    """
    Final residual only says the linear solver hit its own tolerance, which it
    does nearly every iteration whether or not the run is converging. Plotting
    it produces a flat line that looks like health.
    """
    st = {}
    of.parse_line("Time = 5", st)
    of.parse_line("GAMG:  Solving for p, Initial residual = 0.11757, "
                  "Final residual = 0.011387, No Iterations 3", st)
    assert st["residuals"]["p"] == [(5.0, 0.11757)]


def test_noise_lines_are_ignored():
    st = {}
    for line in ("bounding epsilon, min: -40 max: 23853 average: 84",
                 "time step continuity errors : sum local = 4.02",
                 "Create mesh for time = 0", ""):
        assert of.parse_line(line, st) is False
    assert not st.get("residuals")


# ── safety: this is a web app, not a shell ───────────────────────────────

@pytest.mark.parametrize("bad", [
    "../../etc", "/etc", "pitzDaily/../../..", "../", "~/.ssh",
])
def test_case_paths_cannot_escape_the_run_directory(bad):
    with pytest.raises(of.FoamError):
        of.resolve_case(bad)


@pytest.mark.parametrize("argv", [
    ["rm", "-rf", "/"], ["bash"], ["sh", "-c", "x"], ["python"],
    ["curl"], [""], [],
])
def test_only_whitelisted_binaries_run(argv):
    with pytest.raises(of.FoamError):
        of.run("pitzDaily", [argv])


@pytest.mark.parametrize("arg", [
    "; rm -rf /", "$(whoami)", "`id`", "&& curl evil.sh", "|tee /etc/passwd",
    "a b", "\n reboot",
])
def test_arguments_with_shell_metacharacters_are_refused(arg):
    with pytest.raises(of.FoamError):
        of.run("pitzDaily", [["simpleFoam", arg]])


def test_nothing_is_passed_through_a_shell():
    """
    A regression guard: shell=True here would be remote code execution the
    moment somebody binds the dashboard to 0.0.0.0, which --host allows.

    Checked on the parsed tree, not the text. The first version of this test
    grepped for the string and failed on the docstring that explains why the
    string must not appear — a test that cannot tell an argument from a
    sentence about an argument.
    """
    import ast
    tree = ast.parse((ROOT / "src" / "openfoam.py").read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "shell":
                assert not (isinstance(kw.value, ast.Constant)
                            and kw.value.value), "shell=True in a real call"


def test_discover_never_raises_when_openfoam_is_absent(monkeypatch):
    monkeypatch.setattr(of, "wrapper", lambda: None)
    d = of.discover()
    assert d["ok"] is False
    assert "brew install" in d["note"]


def test_residual_series_thins_for_a_plot():
    st = {"residuals": {"p": [(float(i), 1.0 / (i + 1)) for i in range(5000)]}}
    s = of.residual_series(st, max_points=200)
    assert len(s["p"]["t"]) <= 201
    assert s["p"]["r"][0] == 1.0


# ── the dashboard surface ────────────────────────────────────────────────

def test_every_cfd_control_has_a_handler():
    js = (ROOT / "webapp" / "static" / "app.js").read_text()
    html = (ROOT / "webapp" / "templates" / "index.html").read_text()
    for el, fn in (("cf-go", "runCfd"), ("cf-stop", "stopCfd")):
        assert f'id="{el}"' in html, f"#{el} missing from the page"
        assert f"function {fn}" in js or f"async function {fn}" in js
        assert js.count(fn) >= 2, f"{fn} defined but never wired"
    assert 'data-p="cfd"' in html and 'id="p-cfd"' in html
    assert "cfd: loadCfd" in js, "the tab never loads its own data"


def test_cfd_routes_exist_and_are_reachable_from_the_page():
    app = (ROOT / "webapp" / "app.py").read_text()
    js = (ROOT / "webapp" / "static" / "app.js").read_text()
    for r in ("/api/cfd/state", "/api/cfd/cases", "/api/cfd/run",
              "/api/cfd/install", "/api/cfd/stop"):
        assert r in app, f"{r} not defined"
        assert r in js, f"{r} has no caller in the page"


def test_residuals_are_plotted_on_a_log_axis():
    """
    Residuals span four or five decades. On a linear axis everything after the
    first few iterations is a flat line on zero — which is exactly the region
    that says whether it converged.
    """
    js = (ROOT / "webapp" / "static" / "app.js").read_text()
    blk = js[js.index("function drawCfdResiduals"):][:900]
    assert "logY: true" in blk


# ── the real thing, when it is present ───────────────────────────────────

@pytest.mark.skipif(of.wrapper() is None, reason="OpenFOAM not installed")
def test_discovery_finds_a_real_install():
    d = of.discover()
    assert d["ok"], d["note"]
    assert d["version"]
