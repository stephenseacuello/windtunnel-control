"""Assemble the data package that accompanies the report.

    python3 src/build_package.py        (after src/build_report.py)

Raw files are copied byte-for-byte and checksummed; nothing in 1_rig_sweeps/
or 2_jeong_lab/ is edited. Derived, analysis-ready tables go in 4_derived/,
generated here from build/ so they always match the report.
"""
import hashlib
import shutil
import zipfile
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parent.parent
BUILD = ROOT / "build"
NAME = "URI_VAWT_Roughness_Data_2026-10-01"
REPORT = "URI_VAWT_Roughness_Report_2026-10-01.pdf"
PKG = ROOT / "out" / NAME

RIG = [  # (run, test date, [files]). The unconfirmed v1_unk set is not shipped.
    ("v1_Ra20", "2026-08-20", ["summary", "points"]),
    ("v1_Ra80", "2026-08-26", ["summary", "points"]),
    ("v1_Ra40", "2026-09-01", ["summary", "points", "trace"]),
] + [(f"v1_{r}{m}_20261001", "2026-10-01", ["summary", "points", "trace"])
     for r in ("smooth", "Ra20", "Ra40", "Ra80") for m in ("", "_repeat")]
KEYENCE = REPO / "keyence readings 20261001"
SCAN_FILES = ["baseline_Height.csv", "20 1_Height.csv", "40 1_Height.csv", "801_Height.csv",
              "80 2_Height.csv", "baseline.png", "20.png", "40.png", "80 1.png", "80 2.png"]
CODE = ["build_report.py", "figures.py", "style.py", "day.py", "keyence.py", "slicer.py"]
JL = ROOT / "inputs" / "jeong_lab"


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def data_rows(p):
    if p.suffix != ".csv":
        return ""
    with open(p, errors="replace") as f:
        lines = [l for l in f if not l.startswith("#")]
    return str(max(len(lines) - 1, 0))


def copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    assert sha256(src) == sha256(dst), f"copy changed bytes: {src}"


def main():
    if PKG.exists():
        shutil.rmtree(PKG)
    PKG.mkdir(parents=True)
    desc = {}

    # 1 — rig sweeps, verbatim
    for blade, date, kinds in RIG:
        for k in kinds:
            src = REPO / "logs" / f"sweep_{blade}_{k}.csv"
            dst = PKG / "1_rig_sweeps" / date / src.name
            copy(src, dst)
            desc[dst] = {"summary": "Peak power per wind speed (one row per fan set point)",
                         "points": "Every load step (dwell) of the sweep",
                         "trace": "Fan speed and rotor-pulse telemetry at ~16 Hz through the run"}[k] + \
                        f" — {blade}, tested {date}. VERBATIM from the rig."

    # 2 — Jeong lab, verbatim
    for sub, files in [
        ("2026-06-05_initial_reference", ["Summary_Table_Part1_MAX.csv", "Graph2_WS_vs_MaxPower.jpg",
                                          "Graph3_Power_vs_Current_MaxEnvelope_Fixed.jpg",
                                          "Graph4_Power_vs_Current_MaxEnvelope_Combined_Fixed.jpg"]),
        ("2026-07-27_no_texture_baseline", ["Summary_Table.csv", "0727windturbine.csv",
                                            "Power_vs_RPM_0727_WindTurbine.jpg"]),
    ]:
        for fn in files:
            src = JL / sub / fn
            dst = PKG / "2_jeong_lab" / sub / fn
            copy(src, dst)
            desc[dst] = f"VERBATIM as e-mailed by T. Kang ({sub[:10]})."
    desc[PKG / "2_jeong_lab/2026-07-27_no_texture_baseline/0727windturbine.csv"] = \
        "Raw DAQ export, 360 Hz, 5 channels (see DATA_DICTIONARY for the inferred channel map). VERBATIM as e-mailed by T. Kang (2026-07-27)."

    # 3 — Keyence height maps, verbatim
    for fn in SCAN_FILES:
        copy(KEYENCE / fn, PKG / "3_surface_scans" / fn)
        desc[PKG / "3_surface_scans" / fn] = (
            "Keyence VR-6000 height map (mm), 1.853 um/px. VERBATIM." if fn.endswith(".csv")
            else "Keyence VR-6000 screenshot of the same field. VERBATIM.")

    # 4 — derived tables, written by build_report.py
    d = PKG / "4_derived"
    DESC4 = {
        "oct1_vs_no_texture.csv": "1 Oct: each textured rotor against the no-texture rotor, with and without mounting variation (report Table 1).",
        "oct1_by_run.csv": "1 Oct: every run as one observation (report Fig. 3).",
        "surface_roughness.csv": "Pa, Ra and layer period per blade set from the Keyence scans (report Section 1.1).",
        "peak_power_all_rotors.csv": "Peak power per run and fan set point, both estimators, recomputed from the points files with the rig's own rule.",
        "thevenin_by_setpoint.csv": "Per run and set point: V = V_oc - I*R_int fitted over the load ladder.",
        "jeong_0727_reprocessed_by_setting.csv": "27 Jul no-texture test reprocessed from the raw export (report Section 4, Appendix C). Derived; not the lab's own numbers. Use only rows with usable_for_rig_comparison = 1.",
    }
    for fn, what in DESC4.items():
        copy(BUILD / "derived" / fn, d / fn)
        desc[d / fn] = what

    # 5 — reference geometry (curated; the repo's blades/v1.json carries internal notes)
    geo = {
        "units": "metres unless stated",
        "rotor": {"n_blades": 3, "radius_m": 0.1016, "radius_definition": "axis of rotation to blade attachment",
                  "span_m": 0.2451, "swept_area_m2": 0.0498, "swept_area_definition": "2 * radius * span (a VAWT sweeps a cylinder)"},
        "blade_section": {"chord_mm": 48.0, "outer_depth_mm": 24.46, "wall_mm": 1.79, "turning_deg": 183,
                          "twist_deg": 0.0, "edges": "square cut",
                          "description": "thin cambered plate of constant wall; prismatic along the span"},
        "mesh": {"file": "blade_v1.stl", "content": "ONE blade in its own coordinates (not positioned on the rotor), metres",
                 "geometry_name": "v1 (first printed replica of the original rotor; chosen over v2 on 4 Aug 2026)"},
    }
    (PKG / "5_reference").mkdir(parents=True, exist_ok=True)
    import json as _json
    (PKG / "5_reference" / "rotor_geometry.json").write_text(_json.dumps(geo, indent=2) + "\n")
    desc[PKG / "5_reference" / "rotor_geometry.json"] = "Rotor and blade geometry used in the report."
    copy(REPO / "blades" / "v1.stl", PKG / "5_reference" / "blade_v1.stl")
    desc[PKG / "5_reference" / "blade_v1.stl"] = "Blade mesh: one blade, metres, own coordinates."
    copy(ROOT / "inputs" / "slicer" / "turbine_default_summary.json", PKG / "5_reference" / "turbine_default_summary.json")
    desc[PKG / "5_reference" / "turbine_default_summary.json"] = (
        "Summary of the slicer project turbine_default.3mf (Bambu Studio): "
        "printer, nozzle, layer, material, and per reported plate the blade size and painted fuzzy-skin share. "
        "Written by 7_code/slicer.py.")
    for stem in ("fig_surface", "fig_day", "fig_day_curves", "fig_day_thevenin", "fig_jeong_context"):
        copy(BUILD / "fig" / f"{stem}.png", PKG / "6_figures" / f"{stem}.png")
        desc[PKG / "6_figures" / f"{stem}.png"] = "Report figure (PNG); see README for which figure it is."
    rp = ROOT / "report" / "report.pdf"
    copy(rp, PKG / REPORT)
    desc[PKG / REPORT] = "The report this package accompanies."

    # 7 — code, so every derived number can be regenerated
    for f in CODE:
        copy(HERE / f, PKG / "7_code" / f)
        desc[PKG / "7_code" / f] = {
            "build_report.py": "Regenerates every number, table and data figure in the report (run: python3 7_code/build_report.py).",
            "figures.py": "Figure code, called by build_report.py.",
            "style.py": "Figure style (palette, markers).",
            "day.py": "The 1 Oct same-day comparison (two runs per rotor, one mounting) and the mounting-variance interval, called by build_report.py.",
            "slicer.py": "Writes 5_reference/turbine_default_summary.json from the slicer project (.3mf, not shipped).",
            "keyence.py": "Surface parameters from the Keyence height maps, called by build_report.py.",
        }[f]

    # README, dictionary (hand-written templates in src/), manifest
    for f in ["README.md", "DATA_DICTIONARY.md"]:
        copy(HERE / "package" / f, PKG / f)

    for f in CODE:
        assert sha256(HERE / f) == sha256(PKG / "7_code" / f), f"stale code in package: {f}"
    assert not any("unk" in p.name for p in PKG.rglob("*")), "unreported set leaked into the package"
    man = []
    for p in sorted(PKG.rglob("*")):
        if p.is_file() and p.name != "MANIFEST.csv":
            man.append(dict(path=str(p.relative_to(PKG)), bytes=p.stat().st_size,
                            data_rows=data_rows(p), sha256=sha256(p), description=desc.get(p, "")))
    pd.DataFrame(man).to_csv(PKG / "MANIFEST.csv", index=False)

    z = PKG.with_suffix(".zip")
    if z.exists():
        z.unlink()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(PKG.rglob("*")):
            if p.is_file():
                zf.write(p, Path(NAME) / p.relative_to(PKG))
    print(f"{len(man)} files, {z.stat().st_size / 1e6:.1f} MB -> {z}")


if __name__ == "__main__":
    main()
