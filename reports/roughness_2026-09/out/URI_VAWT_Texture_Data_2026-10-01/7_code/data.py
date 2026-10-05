"""Load and reduce the 1 October 2026 rig sweeps.

Everything here is a reduction of the raw files; nothing is fitted across rotors.
analysis.py does the statistics and build_report.py writes the report inputs.

Run files: sweep_v1_<label>[_repeat]_20261001_{summary,points,trace}.csv, each a
block of '#' header lines followed by a CSV table. <label> names the blade set
(SPECIMENS); '_repeat' marks the second run of the same mounting.

Rotor speed: T. Kang's per-run summaries (RPM_DIR), one row per fan set point,
made by his RPM.m from a tachometer record the rig did not have.
"""
import json
import re
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parent.parent

# Inputs: the repository layout, or the unzipped data package (7_code/ next to 1_rig_sweeps/).
PACKAGED = (ROOT / "1_rig_sweeps").is_dir()
if PACKAGED:
    LOGS = ROOT / "1_rig_sweeps"
    RPM_DIR = ROOT / "2_rotor_speed"
    SCANS = ROOT / "3_surface_scans"
    CAL_CSV = ROOT / "5_reference" / "tunnel_calibration_test1.csv"
    SLICER_JSON = ROOT / "5_reference" / "turbine_default_summary.json"
    GEOMETRY = ROOT / "5_reference" / "rotor_geometry.json"
    BUILD = ROOT / "rebuilt"
else:
    LOGS = REPO / "logs"
    RPM_DIR = ROOT / "inputs" / "taegu_rpm_20261001" / "processed"
    SCANS = REPO / "keyence readings 20261001"
    CAL_CSV = REPO / "data" / "test1_rpm_velocity.csv"
    SLICER_JSON = ROOT / "inputs" / "slicer" / "turbine_default_summary.json"
    GEOMETRY = ROOT / "inputs" / "rotor_geometry.json"
    BUILD = ROOT / "build"

DAY = "20261001"
PROTOCOL = "94bed28333f7"

# Blade sets in report order. key: short code used in macro names; label: as printed.
SPECIMENS = {
    "v1_smooth": dict(key="P", label="Plain", fuzz_mm=0.0, old="baseline"),
    "v1_Ra20": dict(key="A", label="FS 0.05", fuzz_mm=0.050, old="Ra 20"),
    "v1_Ra40": dict(key="B", label="FS 0.10", fuzz_mm=0.101, old="Ra 40"),
    "v1_Ra80": dict(key="C", label="FS 0.20", fuzz_mm=0.202, old="Ra 80"),
}
ORDER = list(SPECIMENS)
REF = "v1_smooth"
# Run on 1 Oct but not reported: print settings could not be confirmed.
EXCLUDED = {"v1_unk"}

# Tunnel calibration, Test 1 (13 Feb 2026): least-squares line through every
# point of CAL_CSV (the tunnel's adopted calibration), air speed in m/s against
# commanded fan speed in rpm.
_cal = pd.read_csv(CAL_CSV)
CAL_A, CAL_B = (float(c) for c in np.polyfit(_cal.rpm, _cal.velocity, 1))

# Rotor geometry from the blade mesh (GEOMETRY)
_geo = json.load(open(GEOMETRY, encoding="utf-8"))
R_M, H_M = _geo["rotor"]["radius_m"], _geo["rotor"]["span_m"]
CHORD_M = _geo["blade_section"]["chord_mm"] / 1000
AREA_M2 = 2 * R_M * H_M                 # swept area of an H-rotor: 2RH
RHO_STD = 1.204                          # kg/m^3, dry air at 20 C and 101.325 kPa
NU_STD = 1.516e-5                        # m^2/s, air at 20 C


def wind(rpm):
    """Air speed from the commanded fan speed (Test 1 calibration)."""
    return CAL_A * np.asarray(rpm, float) + CAL_B


def read_sweep(path):
    meta, body = {}, []
    for line in open(path, encoding="utf-8"):
        if line.startswith("#"):
            k, _, v = line[1:].strip().partition(",")
            meta[k.strip()] = v.strip().strip('"')
        else:
            body.append(line)
    return meta, pd.read_csv(StringIO("".join(body)))


RUN_RE = re.compile(r"sweep_(v1_[A-Za-z0-9]+?)(_repeat)?_(\d{8})_summary\.csv")


def discover():
    """{specimen: [run1_stem, run2_stem]} for the 1 Oct session, plus the excluded stems."""
    runs, excluded = {}, []
    for f in sorted(LOGS.rglob(f"sweep_v1_*_{DAY}_summary.csv")):
        m = RUN_RE.fullmatch(f.name)
        if not m:
            continue
        spec, rep = m.group(1), bool(m.group(2))
        stem = f.name[len("sweep_"):-len("_summary.csv")]
        if spec in EXCLUDED:
            excluded.append(stem)
            continue
        if spec not in SPECIMENS:
            raise ValueError(f"unknown blade set in {f.name}")
        runs.setdefault(spec, [None, None])[1 if rep else 0] = stem
    missing = [s for s in ORDER if s not in runs or None in runs[s]]
    if missing:
        raise FileNotFoundError(f"1 Oct runs missing for {missing}")
    return {s: runs[s] for s in ORDER}, excluded


def _path(name):
    hits = list(LOGS.rglob(name))
    if len(hits) != 1:
        raise FileNotFoundError(f"{name}: {len(hits)} matches under {LOGS}")
    return hits[0]


def load(stem):
    meta, summary = read_sweep(_path(f"sweep_{stem}_summary.csv"))
    _, points = read_sweep(_path(f"sweep_{stem}_points.csv"))
    if meta.get("protocol") != PROTOCOL:
        raise ValueError(f"{stem}: protocol {meta.get('protocol')} != {PROTOCOL}")
    return dict(stem=stem, meta=meta, summary=summary, points=points)


# ------------------------------------------------------------- peak power --

def refine(amps, watts, span=2):
    """Port of src/peak_finder.PeakResult.refine: least-squares parabola through
    the arg max and up to `span` dwells either side. Falls back to the arg max if
    there are too few points, the fit is not concave, or the vertex lies outside
    the fitted window. Returns (power, current, points used; 0 = fell back)."""
    k = int(np.argmax(watts))
    raw = (float(watts[k]), float(amps[k]))
    if len(amps) < 2 * span + 1:
        return raw + (0,)
    lo, hi = max(0, k - span), min(len(amps), k + span + 1)
    x, y = amps[lo:hi], watts[lo:hi]
    if len(x) < 3:
        return raw + (0,)
    a2, a1, a0 = np.polyfit(x, y, 2)
    if a2 >= 0:
        return raw + (0,)
    i_hat = -a1 / (2 * a2)
    if not (x[0] <= i_hat <= x[-1]):
        return raw + (0,)
    return float(a2 * i_hat ** 2 + a1 * i_hat + a0), float(i_hat), len(x)


def peaks(run):
    """One row per fan set point: peak electrical power two ways, plus ladder facts.
    The ladder is every dwell at that set point in which the load tracked its
    demand with current above zero."""
    s, p = run["summary"], run["points"]
    rows = []
    for _, srow in s.iterrows():
        cmd = int(srow.fan_rpm_cmd)
        lad = p[(p.fan_rpm == cmd) & (p.tracking == 1) & (p.amps > 0)]
        a, w, v = lad.amps.values, lad.watts.values, lad.volts.values
        k = int(np.argmax(w))
        p_fit, i_fit, nfit = refine(a, w)
        every = p[p.fan_rpm == cmd]
        rows.append(dict(
            fan_rpm_cmd=cmd, fan_rpm_logged=int(srow.fan_rpm_actual), wind_mps=float(wind(cmd)),
            p_max_w=float(w[k]), i_at_p_max_a=float(a[k]), v_at_p_max_v=float(v[k]),
            p_fit_w=p_fit, i_at_p_fit_a=i_fit, fit_points=nfit,
            v_first_v=float(every.volts.values[0]), i_first_a=float(every.amps.values[0]),
            dwells=int(len(every)), stop=str(srow.limited_by), clean=int(srow.clean),
            # after the peak, how far power had fallen at the last dwell above the voltage floor
            last_frac=float(_last_before_cutout(every) / w.max()),
            logged_p_max_w=float(srow.p_max_raw_w), logged_p_fit_w=float(srow.p_max_fit_w),
            fan_motor_a=float(every.motor_amps.median()),
        ))
    return pd.DataFrame(rows)


def _last_before_cutout(every):
    t = every[every.tracking == 1].reset_index(drop=True)
    cut = t.note.astype(str).str.contains("v_floor")
    return float(t.watts[: cut.idxmax()].iloc[-1] if cut.any() else t.watts.iloc[-1])


# ------------------------------------------------------- Thevenin source --

def thevenin(run):
    """Per set point, V = V_oc - I*R_int by least squares over the tracking dwells
    with V, I > 0, excluding dwells flagged 'under v_floor' (at or below the host's
    voltage floor, after the peak)."""
    p = run["points"]
    out = []
    for cmd, g in p[p.tracking == 1].groupby("fan_rpm"):
        g = g[(g.volts > 0) & (g.amps > 0) & ~g.note.astype(str).str.contains("v_floor")]
        slope, icept = np.polyfit(g.amps, g.volts, 1)
        pred = icept + slope * g.amps
        r2 = 1 - ((g.volts - pred) ** 2).sum() / ((g.volts - g.volts.mean()) ** 2).sum()
        out.append(dict(fan_rpm_cmd=int(cmd), wind_mps=float(wind(cmd)), v_oc_v=float(icept),
                        r_int_ohm=float(-slope), r2=float(r2), dwells_fitted=int(len(g)),
                        p_matched_w=float(icept ** 2 / (-4 * slope))))
    return pd.DataFrame(out)


def first_dwell_rise(run, cmd):
    """True if the terminal voltage rose between the first two dwells at a set
    point, i.e. the rotor was still speeding up when the ladder began."""
    p = run["points"]
    v = p[(p.fan_rpm == cmd) & (p.tracking == 1)].volts.values
    return bool(v[1] > v[0])


def times(run):
    t = run["points"].t_local.astype(str)
    return t.min()[11:16], t.max()[11:16]


# ------------------------------------------------------------ rotor speed --

def tacho_fs():
    """Sampling rate (Hz) of T. Kang's tachometer record, as set in his RPM.m."""
    m = re.search(r"^\s*Fs\s*=\s*([0-9.]+)\s*;", (RPM_DIR / "RPM.m").read_text(encoding="utf-8"), re.M)
    return float(m.group(1))


def rotor_speed(stem):
    """T. Kang's summary for one run, one row per fan set point: rotor_rpm is the
    most frequent per-revolution speed at that set point (rounded to 1 rpm), and
    pulses the tachometer pulses counted. One file is named without '_RPM'."""
    hits = [RPM_DIR / f"sweep_{stem}{s}_summary.csv" for s in ("_RPM", "")]
    hits = [h for h in hits if h.is_file()]
    if len(hits) != 1:
        raise FileNotFoundError(f"rotor speed for {stem}: {len(hits)} files under {RPM_DIR}")
    t = pd.read_csv(hits[0])
    return t.rename(columns={"Setting_RPM": "fan_rpm_cmd", "Measured_RPM": "rotor_rpm",
                             "Pulse_Count": "pulses"})


def calibration():
    """Test 1 calibration points: rpm, velocity, source ('measured' or a trend-line read)."""
    return _cal.copy()
