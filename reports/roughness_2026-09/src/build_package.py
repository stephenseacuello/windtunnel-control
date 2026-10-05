"""Assemble the data package that accompanies the 1 October 2026 texture report.

    python3 src/build_package.py        (after src/build_report.py and the LaTeX build)

Raw files are copied byte for byte and checksummed; nothing in 1_rig_sweeps/,
2_rotor_speed/ or 3_surface_scans/ is edited. 4_derived/ is copied from
build/derived/, which build_report.py writes, so it always matches the report. The finished folder is
unzipped and re-run as a check: its rebuilt/ output must equal build/.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parent.parent
BUILD = ROOT / "build"
NAME = "URI_VAWT_Texture_Data_2026-10-01"
REPORT = "URI_VAWT_Texture_Report_2026-10-01.pdf"
PKG = ROOT / "out" / NAME

sys.path.insert(0, str(HERE))
import data as D  # noqa: E402

SCAN_FILES = ["baseline_Height.csv", "20 1_Height.csv", "40 1_Height.csv", "801_Height.csv",
              "80 2_Height.csv", "baseline.png", "20.png", "40.png", "80 1.png", "80 2.png"]
CODE = {
    "build_report.py": "Regenerates every number, table and data figure in the report: python3 7_code/build_report.py",
    "data.py": "Loads the run and rotor-speed files and reduces each load ladder (peak power, Thevenin fit).",
    "analysis.py": "Statistics: Tukey comparisons, nested ANOVA, permutation test, drift model, rotor speed.",
    "figures.py": "Report figures.",
    "style.py": "Figure style (colours, markers).",
    "keyence.py": "Surface parameters (Pa, Ra, layer period) from the profilometer height maps.",
    "slicer.py": "Summarises the slicer project (not shipped) into the JSON shipped as 5_reference/turbine_default_summary.json.",
}
DERIVED = {
    "comparisons.csv": "All six pairwise rotor comparisons of peak power (Tukey 95% intervals, parabolic-fit sensitivity, mounting tipping points), V_oc, R_int and light-load rotor speed (report Tables 3 and 4, Section 6.2).",
    "drift_model.csv": "Run means refitted with a linear time term: drift per hour and drift-adjusted changes vs Plain (report Section 8).",
    "run_summary.csv": "One row per run: change vs Plain in peak power, V_oc, R_int and rotor speed; steepest-rise wind speed (report Table 2).",
    "peak_power_by_run.csv": "Peak electrical power per run and set point, both estimators (report Appendix A).",
    "thevenin_by_run.csv": "V = V_oc - I*R_int fitted per run and set point (report Section 6.4).",
    "rotor_by_wind_speed.csv": "Per rotor and set point: geometric-mean peak power, C_P,el, Thevenin parameters, rotor speed, tip-speed ratio, changes vs Plain (report Figs 4, 6, 7 and 8).",
    "rotor_speed_by_run.csv": "T. Kang's rotor speed per run and set point (taken as light-load from 600 rpm), with tip-speed ratio and the first-step voltage check (report Sections 3.3 and 6.5, Appendix A).",
    "anova.csv": "Analyses of variance of ln P_max (with two sensitivity analyses), ln R_int, ln V_oc and ln n_0 (report Appendix B).",
    "surface_roughness.csv": "Pa, Ra and layer period per blade set (report Sections 2.3 and 6.6, Table 5).",
}
FIGURES = ["fig_surface", "fig_ladders", "fig_power", "fig_runs", "fig_gain", "fig_thevenin",
           "fig_speed", "fig_calibration"]
FIGNUM = dict(fig_surface=1, fig_ladders=3, fig_power=4, fig_runs=5, fig_gain=6, fig_thevenin=7,
              fig_speed=8, fig_calibration=9)                    # Fig. 2 is the TikZ rig diagram


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def data_rows(p):
    """Data rows of a CSV: after the '#' header for rig files, after the "Height"
    line for Keyence height maps."""
    if p.suffix != ".csv":
        return ""
    with open(p, errors="replace") as f:
        lines = f.read().splitlines()
    if '"Height"' in lines:
        return str(len(lines) - lines.index('"Height"') - 1)
    body = [l for l in lines if not l.startswith("#")]
    return str(max(len(body) - 1, 0))


def copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    assert sha256(src) == sha256(dst), f"copy changed bytes: {src}"


def main():
    # remove this package and any older build output, so nothing stale can be sent by mistake
    for old in list(PKG.parent.glob("URI_VAWT_*")) + list(PKG.parent.glob("report.pdf")):
        shutil.rmtree(old) if old.is_dir() else old.unlink()
    PKG.mkdir(parents=True)
    desc = {}

    # 1 - rig sweeps, verbatim
    stems, _ = D.discover()
    for spec, pair in stems.items():
        for j, stem in enumerate(pair):
            for kind, what in (("summary", "peak power per set point, as logged by the rig"),
                               ("points", "every load-ladder dwell"),
                               ("trace", "fan telemetry through the run")):
                src = D._path(f"sweep_{stem}_{kind}.csv")
                dst = PKG / "1_rig_sweeps" / src.name
                copy(src, dst)
                desc[dst] = f"{D.SPECIMENS[spec]['label']}, run {j + 1}: {what}. Verbatim."

    # 2 - T. Kang's rotor-speed summaries and his script, verbatim
    for spec, pair in stems.items():
        for j, stem in enumerate(pair):
            src = [D.RPM_DIR / f"sweep_{stem}{s}_summary.csv" for s in ("_RPM", "")]
            src = [f for f in src if f.is_file()][0]
            copy(src, PKG / "2_rotor_speed" / src.name)
            desc[PKG / "2_rotor_speed" / src.name] = (f"{D.SPECIMENS[spec]['label']}, run {j + 1}: T. Kang's rotor speed "
                                                      "per set point, taken as light-load from 600 rpm (RPM.m output). Verbatim.")
    copy(D.RPM_DIR / "RPM.m", PKG / "2_rotor_speed" / "RPM.m")
    desc[PKG / "2_rotor_speed" / "RPM.m"] = ("T. Kang's MATLAB script that made the summaries from his tachometer "
                                             "record (record not included). Verbatim.")

    # 3 - profilometer height maps, verbatim
    for fn in SCAN_FILES:
        dst = PKG / "3_surface_scans" / fn
        copy(D.SCANS / fn, dst)
        desc[dst] = ("Keyence VR-6000 height map (mm), 1.853 um/px. Verbatim." if fn.endswith(".csv")
                     else "Keyence VR-6000 screenshot of the same field. Verbatim.")

    # 4 - derived tables, written by build_report.py
    for fn, what in DERIVED.items():
        dst = PKG / "4_derived" / fn
        copy(BUILD / "derived" / fn, dst)
        desc[dst] = what

    # 5 - reference: geometry, blade mesh, wind calibration, slicer summary
    ref = PKG / "5_reference"
    ref.mkdir(parents=True)
    copy(D.GEOMETRY, ref / "rotor_geometry.json")
    desc[ref / "rotor_geometry.json"] = "Rotor and blade geometry; the code reads these values."
    copy(REPO / "blades" / "v1.stl", ref / "blade_v1.stl")
    desc[ref / "blade_v1.stl"] = "Blade mesh: one blade, metres, own coordinates."
    copy(REPO / "data" / "test1_rpm_velocity.csv", ref / "tunnel_calibration_test1.csv")
    desc[ref / "tunnel_calibration_test1.csv"] = ("Tunnel calibration Test 1 (13 Feb 2026): air speed vs fan rpm; "
                                                  "'measured' or 'possible trendline read'. Verbatim.")
    copy(D.SLICER_JSON, ref / "turbine_default_summary.json")
    desc[ref / "turbine_default_summary.json"] = "Summary of the slicer project turbine_default.3mf, written by 7_code/slicer.py."

    # 6 - figures; the report itself
    for stem in FIGURES:
        dst = PKG / "6_figures" / f"{stem}.png"
        copy(BUILD / "fig" / f"{stem}.png", dst)
        desc[dst] = f"Report Fig. {FIGNUM[stem]} (PNG)."
    copy(ROOT / "report" / "report.pdf", PKG / REPORT)
    desc[PKG / REPORT] = "The report this package accompanies."

    # 7 - code
    for f, what in CODE.items():
        copy(HERE / f, PKG / "7_code" / f)
        desc[PKG / "7_code" / f] = what

    for f, what in (("README.md", "Start here: what was tested, layout, caveats, how to reproduce."),
                    ("DATA_DICTIONARY.md", "Every data file, header key and column.")):
        copy(HERE / "package" / f, PKG / f)
        desc[PKG / f] = what

    assert not any("unk" in p.name for p in PKG.rglob("*")), "unreported set leaked into the package"
    man = []
    for p in sorted(PKG.rglob("*")):
        if p.is_file():
            man.append(dict(path=str(p.relative_to(PKG)), bytes=p.stat().st_size,
                            data_rows=data_rows(p), sha256=sha256(p), description=desc.get(p, "")))
    pd.DataFrame(man).to_csv(PKG / "MANIFEST.csv", index=False)

    # the package must reproduce the build on its own
    run = subprocess.run([sys.executable, str(PKG / "7_code" / "build_report.py")], capture_output=True, text=True,
                         env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert run.returncode == 0, run.stderr[-2000:]
    for fn in DERIVED:
        assert sha256(BUILD / "derived" / fn) == sha256(PKG / "rebuilt" / "derived" / fn), f"{fn} does not reproduce"
    strip = lambda p: [l for l in open(p) if not l.startswith("%")]
    assert strip(BUILD / "numbers.tex") == strip(PKG / "rebuilt" / "numbers.tex"), "numbers.tex does not reproduce"
    shutil.rmtree(PKG / "rebuilt")
    assert not list(PKG.rglob("__pycache__")), "bytecode cache left in the package"

    z = PKG.with_suffix(".zip")
    if z.exists():
        z.unlink()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(PKG.rglob("*")):
            if p.is_file():
                zf.write(p, Path(NAME) / p.relative_to(PKG))
    print(f"{len(man)} files, {z.stat().st_size / 1e6:.1f} MB -> {z}  (reproduces build/: yes)")


if __name__ == "__main__":
    main()
