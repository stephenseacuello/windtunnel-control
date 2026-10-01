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

    # 3 — derived tables, regenerated from build/
    d = PKG / "3_derived"
    d.mkdir()
    ra = {"v1_Ra20": 20, "v1_Ra40": 40, "v1_Ra80": 80}
    dates = {b: dt for b, dt, _ in RIG}
    frames = []
    for b in ra:
        t = pd.read_csv(BUILD / "tables" / f"pmax_{b}.csv")
        t.insert(0, "test_date", dates[b])
        t.insert(0, "ra_nominal_um", ra[b])
        t.insert(0, "rotor", b)
        frames.append(t)
    pk = pd.concat(frames)[[
        "rotor", "ra_nominal_um", "test_date", "fan_rpm_cmd", "fan_rpm_actual",
        "wind_mps_nominal", "wind_mps_logged", "p_raw", "i_raw", "v_raw", "p_fit", "i_fit",
        "fit_points", "v_light", "i_light", "n_steps", "limited_by", "clean"]].rename(columns={
            "fan_rpm_actual": "fan_rpm_logged", "p_raw": "p_max_raw_w", "i_raw": "i_at_p_max_raw_a",
            "v_raw": "v_at_p_max_raw_v", "p_fit": "p_max_fit_w", "i_fit": "i_at_p_max_fit_a",
            "v_light": "v_first_step_v", "i_light": "i_first_step_a"})
    pk.to_csv(d / "peak_power_all_rotors.csv", index=False, float_format="%.6g")
    desc[d / "peak_power_all_rotors.csv"] = "Peak power per rotor and fan set point, both estimators, recomputed from the points files with the rig's own rule. One row per (rotor, set point)."

    th = []
    for b in ra:
        t = pd.read_csv(BUILD / "tables" / f"thevenin_{b}.csv")
        t.insert(0, "rotor", b)
        th.append(t)
    pd.concat(th).rename(columns={"v_oc": "v_oc_v", "r_int": "r_int_ohm", "p_match": "p_thevenin_match_w",
                                  "n": "n_steps_fitted"}).to_csv(
        d / "thevenin_by_setpoint.csv", index=False, float_format="%.6g")
    desc[d / "thevenin_by_setpoint.csv"] = "Per rotor and set point: V = V_oc - I*R_int fitted over the load ladder."

    import json
    J = json.load(open(BUILD / "numbers.json"))
    rows = []
    for key, r in J["pairs"].items():
        b, c, col = key.split("|")
        rows.append(dict(baseline=b, candidate=c, basis={"p_raw": "raw_argmax", "p_fit": "parabolic_fit"}[col],
                         n_setpoints=r["n"], change_pct=100 * r["level"], ci95_lo_pct=100 * r["lo"],
                         ci95_hi_pct=100 * r["hi"], setpoints_higher=r["higher"], sign_test_p=r["sign_p"],
                         delta_n=r["dn"], delta_n_ci95_half=r["dn_half"]))
    pd.DataFrame(rows).to_csv(d / "paired_comparisons.csv", index=False, float_format="%.6g")
    desc[d / "paired_comparisons.csv"] = "Paired comparisons at matched fan set points (Table 4 of the report)."
    rows = [dict(rotor=k.split("|")[0], basis={"p_raw": "raw_argmax", "p_fit": "parabolic_fit"}[k.split("|")[1]],
                 n=v["n"], n_ci95_lo=v["lo"], n_ci95_hi=v["hi"], a_w=v["a"], r2_log=v["r2_log"], r2_linear=v["r2_lin"])
            for k, v in J["powerlaw"].items()]
    pd.DataFrame(rows).to_csv(d / "power_law_fits.csv", index=False, float_format="%.6g")
    desc[d / "power_law_fits.csv"] = "P_max = a * v^n per rotor (Table 5 of the report)."

    jd = BUILD / "daq_july" / "july_segments.csv"
    if (BUILD / "july_final.csv").exists():
        copy(BUILD / "july_final.csv", d / "jeong_0727_reprocessed_by_setting.csv")
        desc[d / "jeong_0727_reprocessed_by_setting.csv"] = "July no-texture run reprocessed from the raw DAQ export (Section 6 of the report). DERIVED, not the lab's own numbers."

    # 4 — reference: geometry and figures
    for src, rel, what in [
        (REPO / "blades" / "v1.json", "4_reference/blade_v1.json", "Blade geometry notes (one blade)."),
        (REPO / "blades" / "v1.stl", "4_reference/blade_v1.stl", "Blade mesh, one blade, metres."),
    ]:
        copy(src, PKG / rel)
        desc[PKG / rel] = what
    for f in sorted((BUILD / "fig").glob("*.png")):
        copy(f, PKG / "5_figures" / f.name)
        desc[PKG / "5_figures" / f.name] = "Report figure (PNG)."

    # 6 — code, so every derived number can be regenerated
    for f in ["build_report.py", "figures.py", "style.py", "build_package.py"]:
        copy(HERE / f, PKG / "6_code" / f)
        desc[PKG / "6_code" / f] = {
            "build_report.py": "Regenerates every number, table and figure in the report (run: python3 6_code/build_report.py).",
            "figures.py": "Figure code, called by build_report.py.",
            "style.py": "Figure style (palette, markers).",
            "build_package.py": "Assembles this package. Paths assume the project repository layout.",
        }[f]
    if (BUILD / "daq_july" / "analyze_july.py").exists():
        copy(BUILD / "daq_july" / "analyze_july.py", PKG / "6_code" / "analyze_july.py")
        desc[PKG / "6_code" / "analyze_july.py"] = ("Exploratory analysis of the 27 Jul export (channel identification, fan-step "
                                                    "segmentation, tach check). Paths assume the project layout; not needed to reproduce the report's tables.")

    # README, dictionary (hand-written templates in src/), manifest
    for f in ["README.md", "DATA_DICTIONARY.md"]:
        copy(HERE / "package" / f, PKG / f)

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
