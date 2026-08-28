"""
test_docs.py — the documentation is tested too.

    cd tests && python -m pytest test_docs.py -v

Roughly 1,500 lines of documentation across this project make specific claims:
commands you can run, parameters to set, wind speeds you will get. Every one of
those is a chance for the docs and the code to drift apart — and the drift is
silent, because nothing breaks until somebody follows the instructions at the
tunnel and it does not work.

These tests make the docs falsifiable. If a flag is renamed, a mode removed, or
the calibration changed, a test goes red instead of a colleague getting stuck
in front of a 15 HP fan.

Deliberately **not** tested: prose. Whether an explanation is *good* is not
something a test can tell you. What is testable is whether the commands exist,
the numbers agree, and the cross-references resolve.
"""

import ast
import contextlib
import io
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

MD_FILES = [f for f in ROOT.rglob("*.md") if ".pytest_cache" not in str(f)]


def all_docs_text():
    return {f: f.read_text() for f in MD_FILES}


# ═══════════════════════════════════════════════════════════════════════════
# COMMANDS
# ═══════════════════════════════════════════════════════════════════════════

def documented_commands():
    """Every `run.py ...` invocation appearing in a fenced code block."""
    out = []
    for f, text in all_docs_text().items():
        in_block = False
        for line in text.splitlines():
            if line.strip().startswith("```"):
                in_block = not in_block
                continue
            if not in_block:
                continue        # prose mentions are not commands
            # Anchor to the start of the line: layout diagrams inside code
            # fences mention run.py mid-line as prose, and those are not
            # commands.
            m = re.match(r"\s*(?:\$\s*)?(?:python3?\s+)(?:src/)?run\.py\s+([^\n#]+)",
                         line)
            if m:
                out.append((f, m.group(1).strip().rstrip("\\")))
    return out


def test_every_documented_command_parses():
    """
    A command in a code block is an instruction. If it does not parse, someone
    following the playbook hits an error at the tunnel.
    """
    import run as runmod
    parser = runmod.build_parser()

    broken = []
    for f, cmd in documented_commands():
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                parser.parse_args(cmd.split())
        except SystemExit:
            broken.append(f"{f.relative_to(ROOT)}: run.py {cmd}")

    assert not broken, "documented commands that do not parse:\n  " + \
                       "\n  ".join(broken)


def test_documented_commands_are_not_trivially_few():
    """Guards against the extractor silently matching nothing."""
    assert len(documented_commands()) > 15


def test_every_cli_mode_is_documented_somewhere():
    """A mode nobody can find is a mode nobody uses."""
    import run as runmod
    parser = runmod.build_parser()
    sub = next(a for a in parser._actions if hasattr(a, "choices") and a.dest == "mode")
    modes = set(sub.choices)

    text = "\n".join(all_docs_text().values())
    undocumented = {m for m in modes if not re.search(rf"\b{re.escape(m)}\b", text)}
    assert not undocumented, f"CLI modes never mentioned in docs: {undocumented}"


# ═══════════════════════════════════════════════════════════════════════════
# NUMBERS
# ═══════════════════════════════════════════════════════════════════════════

def load_calibration():
    from calibration import Calibration
    cfg = json.loads((ROOT / "data" / "tunnel.json").read_text())
    return Calibration.from_dict(cfg["calibration"])


def test_wind_speed_tables_match_the_calibration():
    """
    The RPM → m/s tables appear in several documents. If the calibration is
    ever corrected these must move with it, or somebody quotes a velocity that
    was never true.

    Rewritten for the rpm domain: the drive commands speed, not frequency, so
    the old three-number Hz|RPM|m/s row no longer exists anywhere. Rows are now
    `| rpm | m/s |` with an optional mph column.
    """
    cal = load_calibration()
    wrong = []
    for f, text in all_docs_text().items():
        for line in text.splitlines():
            for m in re.finditer(
                    r"\|\s*(\d{3,4})\s*\|\s*(\d+\.\d)\s*\|(?:\s*(\d+\.\d)\s*\|)?",
                    line):
                rpm, mps = int(m[1]), float(m[2])
                if not 150 <= rpm <= 2435:
                    continue                     # not a speed row
                e_mps = float(cal.velocity(rpm))
                if abs(e_mps - mps) > 0.06:
                    wrong.append(f"{f.relative_to(ROOT)}: {rpm} rpm → doc "
                                 f"{mps} m/s, actual {e_mps:.2f}")
                    continue
                if m[3] is not None:
                    mph = float(m[3])
                    if abs(e_mps / 0.44704 - mph) > 0.15:
                        wrong.append(f"{f.relative_to(ROOT)}: {rpm} rpm → doc "
                                     f"{mph} mph, actual {e_mps / 0.44704:.1f}")
    assert not wrong, "wind speed tables out of date:\n  " + "\n  ".join(wrong)


def test_documented_formula_matches_the_calibration():
    """
    Rounded for readability is fine; wrong is not. The tolerance below allows
    two decimal places on the intercept — 0.005 m/s, negligible at any speed
    this tunnel reaches — but catches a genuine change.
    """
    cal = load_calibration()
    found = 0
    for f, text in all_docs_text().items():
        for m in re.finditer(r"v\s*\(?m/s\)?\s*=\s*([\d.]+)\s*[×x*]\s*RPM\s*([−\-+])\s*([\d.]+)",
                             text, re.IGNORECASE):
            found += 1
            a = float(m[1])
            b = float(m[3]) * (-1 if m[2] in "−-" else 1)
            assert abs(a - cal.coeffs[0]) < 5e-5, f"{f}: slope {a}"
            assert abs(b - cal.coeffs[1]) < 0.006, f"{f}: intercept {b}"
    assert found, "the calibration formula is not stated in any document"


def test_hz_limit_agrees_across_config_and_docs():
    cfg = json.loads((ROOT / "data" / "tunnel.json").read_text())
    limit = cfg.get("hz_limit")
    assert limit, "no hz_limit in the shipped config"
    text = "\n".join(all_docs_text().values())
    # The key name is legacy; the value is rpm. Both the drive and the docs
    # moved to speed reference, and a doc still saying "2400 Hz" would be a
    # much worse failure than one saying nothing.
    assert re.search(rf"{int(limit)}\s*rpm", text, re.IGNORECASE), \
        f"hz_limit is {limit} rpm but that number appears nowhere in the docs"
    assert not re.search(rf"{int(limit)}\s*Hz", text), \
        f"a document calls the {int(limit)} rpm limit a frequency"


# ═══════════════════════════════════════════════════════════════════════════
# CROSS-REFERENCES
# ═══════════════════════════════════════════════════════════════════════════

def test_referenced_files_exist():
    """
    Renaming a document is easy; updating everything that points at it is the
    part that gets forgotten. This caught three stale paths during the doc
    consolidation.
    """
    pattern = re.compile(
        r"[`(]((?:docs|src|webapp|tests|examples|scripts|reference)/[\w/]+\.(?:md|py|svg|json)"
        r"|[A-Z_]+\.md)[`)]")
    missing = []
    for f, text in all_docs_text().items():
        for m in pattern.finditer(text):
            target = m.group(1)
            if "CHANGELOG" in str(f):
                continue        # the changelog records deleted files on purpose
            if not (ROOT / target).exists():
                missing.append(f"{f.relative_to(ROOT)} → {target}")
    assert not missing, "broken references:\n  " + "\n  ".join(missing)


def test_python_files_referenced_in_docs_exist():
    missing = []
    for f, text in all_docs_text().items():
        if "CHANGELOG" in str(f):
            continue
        for m in re.finditer(r"`(\w+)\.py`", text):
            name = m.group(1) + ".py"
            if not any((ROOT / d / name).exists()
                       for d in ("src", "webapp", "tests", "examples",
                                 "scripts", "docs/slides", "docs/diagrams")):
                missing.append(f"{f.relative_to(ROOT)} → {name}")
    assert not missing, "referenced modules that do not exist:\n  " + \
                        "\n  ".join(missing)


# ═══════════════════════════════════════════════════════════════════════════
# PARAMETERS
# ═══════════════════════════════════════════════════════════════════════════

def test_parameters_the_playbook_says_to_record_are_in_the_dashboard():
    """
    Phase 1 of the commissioning procedure lists parameters to write down
    before changing
    anything. If the dashboard cannot show one, you have to walk to the keypad
    for it — which is the sort of gap nobody notices until they are standing
    at the drive.
    """
    playbook = (ROOT / "docs" / "10_commissioning.md").read_text()
    phase1 = playbook.split("# PHASE 2")[0]
    cited = {int(x) for x in re.findall(r"`(\d{4})`", phase1)}

    app = (ROOT / "webapp" / "app.py").read_text()
    in_ui = {int(x) for x in re.findall(r"\((\d{3,4}), \"", app)}

    missing = sorted(cited - in_ui)
    assert not missing, (f"playbook phase 1 says to record {missing}, but they "
                         f"are not in the dashboard's parameter editor")


def test_safety_parameters_are_never_described_as_optional():
    """
    3018/3019 are the comm-loss watchdog — the reason it is acceptable to
    command this fan from a Pi or a browser. No document should ever suggest
    turning them off.
    """
    for f, text in all_docs_text().items():
        for m in re.finditer(r"[^.]*30(?:18|19)[^.]*\.", text):
            sentence = m.group(0).lower()
            if "disable" in sentence or "turn off" in sentence:
                assert "not" in sentence or "do not" in sentence, \
                    f"{f.relative_to(ROOT)} appears to suggest disabling the " \
                    f"watchdog: {m.group(0).strip()[:120]}"


# ═══════════════════════════════════════════════════════════════════════════
# STRUCTURE
# ═══════════════════════════════════════════════════════════════════════════

def test_no_duplicate_wiring_procedures():
    """
    Four documents once described how to wire the drive, and six how to start.
    That is worse than having less: you cannot tell which is authoritative.
    Only the playbook and the field card should carry the terminal-level
    procedure.
    """
    allowed = {"10_commissioning.md", "FIELD_CARD.md", "CHANGELOG.md",
               "04_troubleshooting.md", "README.md", "02_code.md",
               # These cite the terminals to say WHICH device lands there —
               # not to duplicate the procedure for landing it.
               "05_integration.md"}
    offenders = [f.relative_to(ROOT) for f, text in all_docs_text().items()
                 if "X1-29" in text and f.name not in allowed]
    assert not offenders, f"wiring procedure duplicated in: {offenders}"


def test_every_source_module_has_a_docstring():
    """A module whose purpose is not stated in it is a module nobody trusts."""
    missing = []
    for d in ("src", "webapp", "scripts", "examples"):
        for f in (ROOT / d).glob("*.py"):
            if not ast.get_docstring(ast.parse(f.read_text())):
                missing.append(str(f.relative_to(ROOT)))
    assert not missing, f"modules without a docstring: {missing}"


def test_readme_points_at_documents_that_exist():
    """The README is the map. A map with a wrong road on it is worse than none."""
    readme = (ROOT / "README.md").read_text()
    table = readme.split("## Where do I start?")[1].split("\n---\n")[0]
    refs = re.findall(r"`([\w/.]+\.md)`|\*\*`([\w/.]+\.md)`\*\*", table)
    targets = [a or b for a, b in refs]
    assert len(targets) >= 8, "the documentation map lost entries"
    for t in targets:
        assert (ROOT / t).exists(), f"README map points at missing {t}"


# ═══════════════════════════════════════════════════════════════════════════
# RESULTS
# ═══════════════════════════════════════════════════════════════════════════

def test_results_doc_matches_the_data_files():
    """
    docs/09_results.md states the campaign's findings. Prose drifts from data
    silently — that is how "Cp is still climbing with Reynolds" reached six
    documents, and how tau was quoted as 0.63, 0.80 and 3.0 in the same repo.

    So the headline numbers are checked against the files they came from. If a
    CSV changes and the document does not, this fails.
    """
    import csv as _csv
    doc = (ROOT / "docs" / "09_results.md").read_text()

    body = [l for l in (ROOT / "logs" / "sweep_v1_Ra20_summary.csv")
            .read_text().splitlines(True) if not l.startswith("#")]
    rows = list(_csv.DictReader(body))
    peak = max(float(r["p_max_w"]) for r in rows)
    assert f"{peak:.3f} W" in doc, \
        f"results doc does not state the measured peak {peak:.3f} W"
    assert str(len(rows)) in doc, "results doc does not state the point count"

    # The generator fit is computed, never typed.
    sys.path.insert(0, str(ROOT / "src"))
    import generator_model as gm
    g = gm.model(gm.fit(gm.read_points(
        ROOT / "logs" / "sweep_v1_Ra20_points.csv")))
    for val, what in ((f"{g['r_int_lo']:.1f}", "R_int at the bottom"),
                      (f"{g['r_int_hi']:.1f}", "R_int at the top"),
                      (f"{g['n_predicted']:.2f}", "the 2a-b cross-check")):
        assert val in doc, f"results doc disagrees with generator_model on {what} ({val})"


def test_tau_is_quoted_consistently():
    """
    tau was 0.63 in the README, 0.80 in tunnel.json and 3.0 throughout the
    gusts document — all at once, all presented as fact. The measured value is
    0.60 +/- 0.14 s over four unclipped runs.
    """
    import json as _json
    cfg = _json.loads((ROOT / "data" / "tunnel.json").read_text())
    assert abs(cfg["tau"] - 0.60) < 0.005, \
        f"tunnel.json tau is {cfg['tau']}, not the measured 0.60"

    stale = []
    for f, text in all_docs_text().items():
        if "CHANGELOG" in str(f):
            continue          # history records what was believed at the time
        for bad in ("tau = 3", "τ = 3 s", "τ = 0.63", "tau of 0.63"):
            if bad in text:
                stale.append(f"{f.relative_to(ROOT)}: {bad}")
    assert not stale, "superseded tau values still quoted:\n  " + "\n  ".join(stale)
