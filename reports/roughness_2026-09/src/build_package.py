"""Assemble the data package that accompanies the report.

    python3 src/build_package.py        (after src/build_report.py)

Raw files are copied byte-for-byte and checksummed; nothing in 1_rig_sweeps/
or 2_jeong_lab/ is edited. Derived, analysis-ready tables go in 3_derived/,
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
NAME = "URI_VAWT_Roughness_Data_2026-09-30"
PKG = ROOT / "out" / NAME

RIG = [  # (blade, test date, [files])
    ("v1_Ra20", "2026-08-20", ["summary", "points"]),
    ("v1_Ra80", "2026-08-26", ["summary", "points"]),
    ("v1_Ra40", "2026-09-01", ["summary", "points", "trace"]),
]
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
            dst = PKG / "1_rig_sweeps" / f"{blade}_{date}" / src.name
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

    # 3 — derived tables, written by build_report.py
    d = PKG / "3_derived"
    DESC3 = {
        "peak_power_all_rotors.csv": "Peak power per rotor and fan set point, both estimators, recomputed from the points files with the rig's own rule.",
        "thevenin_by_setpoint.csv": "Per rotor and set point: V = V_oc - I*R_int fitted over the load ladder.",
        "paired_comparisons.csv": "Paired comparisons at matched fan set points (report Table 4).",
        "power_law_fits.csv": "P_max = a * v^n per rotor (report Table 5).",
        "jeong_0727_reprocessed_by_setting.csv": "27 Jul no-texture test reprocessed from the raw export (report Section 6, Appendix C). Derived; not the lab's own numbers. Use only rows with usable_for_rig_comparison = 1.",
    }
    for fn, what in DESC3.items():
        copy(BUILD / "derived" / fn, d / fn)
        desc[d / fn] = what

    # 4 — reference geometry (curated; the repo's blades/v1.json carries internal notes)
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
    (PKG / "4_reference").mkdir(parents=True, exist_ok=True)
    import json as _json
    (PKG / "4_reference" / "rotor_geometry.json").write_text(_json.dumps(geo, indent=2) + "\n")
    desc[PKG / "4_reference" / "rotor_geometry.json"] = "Rotor and blade geometry used in the report."
    copy(REPO / "blades" / "v1.stl", PKG / "4_reference" / "blade_v1.stl")
    desc[PKG / "4_reference" / "blade_v1.stl"] = "Blade mesh: one blade, metres, own coordinates."
    FIGNUM = {k: k for k in ("fig_ratio", "fig_pmax", "fig_trend", "fig_thevenin", "fig_pi",
                             "fig_mounts", "fig_jeong_context", "fig_jeong_processing")}
    for stem, out in FIGNUM.items():
        f = BUILD / "fig" / f"{stem}.png"
        if f.exists():
            copy(f, PKG / "5_figures" / f"{out}.png")
            desc[PKG / "5_figures" / f"{out}.png"] = "Report figure (PNG); see README for which figure it is."
    rp = ROOT / "out" / "report.pdf"
    if rp.exists():
        copy(rp, PKG / "URI_VAWT_Roughness_Report_2026-09-30.pdf")
        desc[PKG / "URI_VAWT_Roughness_Report_2026-09-30.pdf"] = "The report this package accompanies."

    # 6 — code, so every derived number can be regenerated
    for f in ["build_report.py", "figures.py", "style.py"]:
        copy(HERE / f, PKG / "6_code" / f)
        desc[PKG / "6_code" / f] = {
            "build_report.py": "Regenerates every number, table and figure in the report (run: python3 6_code/build_report.py).",
            "figures.py": "Figure code, called by build_report.py.",
            "style.py": "Figure style (palette, markers).",
        }[f]

    # README, dictionary (hand-written templates in src/), manifest
    for f in ["README.md", "DATA_DICTIONARY.md"]:
        copy(HERE / "package" / f, PKG / f)

    for f in ["build_report.py", "figures.py", "style.py"]:
        assert sha256(HERE / f) == sha256(PKG / "6_code" / f), f"stale code in package: {f}"
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
