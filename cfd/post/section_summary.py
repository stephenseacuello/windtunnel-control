#!/usr/bin/env python3
"""Summary of one Stage 1 section case (cfd/section2d/runs/<name>/).

    python3 cfd/post/section_summary.py cfd/section2d/runs/<name>            # print JSON
    python3 cfd/post/section_summary.py cfd/section2d/runs/<name> --window 20  # last 20 c/U

Reads case.json (written by run_case.py), postProcessing/{forceCoeffs1,forces1,
yPlus1,probes1}/<t>/*, timing.json and log.pimpleFoam. A restarted run writes a new
<t>/ directory; rows of an earlier directory at or after the next start time are
dropped (the restart repeats them). A second restart from the same time writes
<name>_<t>.dat in that directory; the newest file there is used.

Statistics are over the averaging window [t_end - nAvg c/U, t_end]:
  Cd, Cl         mean and standard deviation (Cl along z x free stream)
  Cm             moment coefficient about +z through the section centroid,
                 counter-clockwise positive (= -CmPitch of forceCoeffs)
  Cd_pressure, Cd_viscous  from forces1 (rho = rhoInf)
  St             f c_ref / U of the largest peak in the Cl spectrum (Hann window,
                 uniform resampling, zero padding x8, parabolic peak fit);
                 St_peak_frac = fraction of the Cl variance within +-15 % of f
  Cd_drift       mean over the second half of the window minus the first half
  yplus_*        first-cell-centre y+ on the blade, sampled once per c/U
  wall_time_s    elapsed solver time over all sessions; run_time_s excludes system
                 sleep; s_per_step = run_time_s / n_steps
No OpenFOAM install is needed.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np


def _num_dirs(p):
    out = []
    for q in Path(p).iterdir() if Path(p).exists() else []:
        try:
            out.append((float(q.name), q))
        except ValueError:
            pass
    return sorted(out)


def session_file(d, fname):
    """The output file of the latest session in one postProcessing/<fo>/<t>/ directory.
    A run restarted twice from the same write time t (e.g. killed again before its next
    write) puts the second session in <stem>_<t><ext> next to the first
    (OpenFOAM functionObjects::writeFile::newFileAtTime); the newest file is the latest
    session, which supersedes the others from t on."""
    stem, ext = Path(fname).stem, Path(fname).suffix
    cands = [f for f in [d / fname, *d.glob(f"{stem}_*{ext}")] if f.is_file()]
    return max(cands, key=lambda f: f.stat().st_mtime) if cands else None


def read_table(fo_dir, fname):
    """Concatenate postProcessing/<fo>/<t>/<fname> over restarts.
    Returns (column names, array) with time in column 0."""
    dirs = _num_dirs(fo_dir)
    names, chunks = None, []
    for i, (t0, d) in enumerate(dirs):
        f = session_file(d, fname)
        if f is None:
            continue
        hdr = None
        rows = []
        for line in f.read_text().splitlines():
            if line.startswith("#"):
                if re.match(r"#\s*Time\b", line):
                    hdr = line.lstrip("#").split()
                continue
            line = line.replace("(", " ").replace(")", " ")
            if line.strip():
                rows.append(line.split())
        if not rows:
            continue
        a = np.array(rows, float)
        if i + 1 < len(dirs):
            a = a[a[:, 0] < dirs[i + 1][0] - 1e-15]
        chunks.append(a)
        names = names or hdr
    if not chunks:
        return names, np.empty((0, 1))
    a = np.vstack(chunks)
    _, idx = np.unique(a[:, 0], return_index=True)
    return names, a[np.sort(idx)]


def strouhal(t, y, c, U):
    """Dominant frequency of y(t) as a Strouhal number f c / U."""
    if t.size < 32:
        return float("nan"), float("nan")
    dt = np.median(np.diff(t))
    tu = np.arange(t[0], t[-1], dt)
    yu = np.interp(tu, t, y)
    yu = yu - yu.mean()
    if not np.any(yu):
        return float("nan"), float("nan")
    w = np.hanning(yu.size)
    nfft = 8 * int(2 ** np.ceil(np.log2(yu.size)))
    P = np.abs(np.fft.rfft(yu * w, nfft)) ** 2
    f = np.fft.rfftfreq(nfft, dt)
    fmin = 2.0 / (tu[-1] - tu[0])             # at least two cycles in the window
    m = f > fmin
    if not m.any():
        return float("nan"), float("nan")
    i = np.argmax(np.where(m, P, 0))
    if 0 < i < P.size - 1:
        a, b, g = np.log(P[i - 1] + 1e-300), np.log(P[i] + 1e-300), np.log(P[i + 1] + 1e-300)
        den = a - 2 * b + g
        di = 0.5 * (a - g) / den if den != 0 else 0.0
    else:
        di = 0.0
    fp = (i + di) * (f[1] - f[0])
    band = (f > 0.85 * fp) & (f < 1.15 * fp)
    frac = P[band].sum() / P[f > 0].sum()
    return fp * c / U, float(frac)


def parse_log(path):
    """deltaT, max Courant number and clock time per step (all sessions)."""
    if not Path(path).exists():
        return {}
    s = Path(path).read_text(errors="replace")
    dt = np.array(re.findall(r"^deltaT = ([\d.eE+-]+)", s, re.M), float)
    co = np.array(re.findall(r"^Courant Number mean: [\d.eE+-]+ max: ([\d.eE+-]+)", s, re.M), float)
    tt = np.array(re.findall(r"^Time = ([\d.eE+-]+)", s, re.M), float)
    return dict(dt=dt, co=co, time=tt, omega_bounded=len(re.findall(r"^bounding omega", s, re.M)))


def summarize(case, window_conv=None):
    case = Path(case)
    P = json.loads((case / "case.json").read_text())
    U, c, tc = P["Uinf"], P["cRef"], P["convTime"]
    nav = window_conv if window_conv else P["nAvg"]
    pp = case / "postProcessing"
    out = dict(name=case.name, alpha_deg=P["alphaDeg"], U_ms=U, Re_c=P["ReChord"], model=P["model"],
               level=P["level"], Tu_body_pct=P["TuBodyPercent"], Tu_inlet_pct=P["TuInletPercent"],
               maxCo=P["maxCo"], nOuter=P["nOuterCorrectors"])
    mi = case / "mesh_info.json"
    if mi.exists():
        out["n_cells"] = json.loads(mi.read_text())["n_cells"]
    names, fc = read_table(pp / "forceCoeffs1", "coefficient.dat")
    if fc.shape[0] == 0:
        raise RuntimeError(f"no forceCoeffs data in {pp}")
    col = {n: i for i, n in enumerate(names)}
    t = fc[:, 0]
    t_end = t[-1]
    t0 = max(t[0], t_end - nav * tc)
    w = t >= t0
    tw = t[w]
    Cd, Cl = fc[w, col["Cd"]], fc[w, col["Cl"]]
    Cm = -fc[w, col["CmPitch"]]
    half = tw < 0.5 * (tw[0] + tw[-1])
    out.update(t_end_conv=t_end / tc, avg_from_conv=t0 / tc, avg_to_conv=t_end / tc,
               Cd_mean=float(Cd.mean()), Cd_std=float(Cd.std()), Cl_mean=float(Cl.mean()), Cl_std=float(Cl.std()),
               Cm_mean=float(Cm.mean()), Cm_std=float(Cm.std()),
               Cd_drift=float(Cd[~half].mean() - Cd[half].mean()) if half.any() and (~half).any() else float("nan"),
               Cl_drift=float(Cl[~half].mean() - Cl[half].mean()) if half.any() and (~half).any() else float("nan"))
    St, frac = strouhal(tw, Cl, c, U)
    out.update(St=float(St), St_peak_frac=frac,
               n_cycles_avg=float(St * (tw[-1] - tw[0]) * U / c) if np.isfinite(St) else float("nan"))
    # pressure / viscous split from forces1
    fn, ff = read_table(pp / "forces1", "force.dat")
    if ff.shape[0]:
        fcol = {n: i for i, n in enumerate(fn)}
        m = ff[:, 0] >= t0
        d = np.array(P["dragDir"][:2])
        q = 0.5 * P["rhoInf"] * U ** 2 * P["Aref"]
        for part in ("pressure", "viscous"):
            F = ff[m][:, [fcol[f"{part}_x"], fcol[f"{part}_y"]]]
            out[f"Cd_{part}_mean"] = float((F @ d).mean() / q)
    # y+
    ytxt = []   # rows: time, patch, min, max, average
    for _, d in _num_dirs(pp / "yPlus1"):
        f = session_file(d, "yPlus.dat")
        if f is not None:
            for line in f.read_text().splitlines():
                if not line.startswith("#") and line.strip():
                    s = line.split()
                    ytxt.append((float(s[0]), float(s[2]), float(s[3]), float(s[4])))
    if ytxt:
        y = np.array(sorted(set(ytxt)))
        m = y[:, 0] >= t0
        if not m.any():
            m = np.ones(len(y), bool)
        out.update(yplus_max_mean=float(y[m, 2].mean()), yplus_max_max=float(y[m, 2].max()),
                   yplus_mean_mean=float(y[m, 3].mean()))
    else:
        out.update(yplus_max_mean=float("nan"), yplus_max_max=float("nan"), yplus_mean_mean=float("nan"))
    # free-stream Tu at the upstream probe (last probe), from k
    kn, kp = read_table(pp / "probes1", "k")
    if kp.shape[0]:
        m = kp[:, 0] >= t0
        out["Tu_upstream_probe_pct"] = float(100 * np.sqrt(2 / 3 * kp[m, -1].mean()) / U)
    # cost
    L = parse_log(case / "log.pimpleFoam")
    if L and L["dt"].size:
        n = L["dt"].size
        tail = slice(n // 2, None)
        out.update(n_steps=int(n), dt_mean_s=float(L["dt"].mean()), dt_last_half_mean_s=float(L["dt"][tail].mean()),
                   Co_max_mean=float(L["co"].mean()) if L["co"].size else float("nan"),
                   omega_bounded_steps=L["omega_bounded"])
    tj = case / "timing.json"
    if tj.exists():
        S = json.loads(tj.read_text())
        out["wall_time_s"] = float(sum(s["wall_s"] for s in S))            # elapsed, includes any sleep
        out["run_time_s"] = float(sum(s.get("awake_s", s["wall_s"]) for s in S))   # machine awake
        out["sessions"] = len(S)
        if out.get("n_steps"):
            out["s_per_step"] = out["run_time_s"] / out["n_steps"]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case")
    ap.add_argument("--window", type=float, help="averaging window in c/U (default: nAvg of the case)")
    a = ap.parse_args()
    print(json.dumps(summarize(a.case, a.window), indent=1))


if __name__ == "__main__":
    sys.exit(main())
