"""Surface parameters from the Keyence VR-6000 height maps (1 Oct 2026).

Profiles run down the image columns, which cross the FDM layer lines and lie
along the blade span, where the blade is straight. Each profile is levelled
with a least-squares line. Then:

    Pa      arithmetic mean deviation of the levelled (primary) profile
    Ra      the same after an ISO 16610-21 Gaussian high-pass, lambda_c = 0.25 mm,
            discarding lambda_c/2 at each end
    pitch   dominant wavelength of the primary profile between 60 and 320 um

Profiles are cut to the length of the shortest valid one and re-centred;
values are means over all valid profiles in a scan (about 1000 per scan).
ISO 4288 picks lambda_c = 0.25 mm for periodic profiles with 0.04-0.13 mm
spacing (the ~0.1 mm layer period of Ra20 and Ra40); the 0.2 mm period of the
no-texture set would call for 0.8 mm and the non-periodic Ra80 surface for
2.5 mm, both too long for the 1.43 mm field. Ra here therefore describes
texture finer than 0.25 mm for every set, and Pa everything up to the field
length.
"""
import csv
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d

ALPHA = np.sqrt(np.log(2) / np.pi)               # 0.4697, ISO 16610-21
SIG_FACTOR = ALPHA / np.sqrt(2 * np.pi)          # Gaussian sigma = SIG_FACTOR * lambda_c
LC_UM = 250.0

# scan file -> rotor (sets in the report only).
SCANS = {
    "baseline_Height.csv": "v1_smooth",
    "20 1_Height.csv": "v1_Ra20",
    "40 1_Height.csv": "v1_Ra40",
    "801_Height.csv": "v1_Ra80",
    "80 2_Height.csv": "v1_Ra80",
}


def load(path):
    meta, start = {}, None
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    for i, ln in enumerate(lines):
        row = next(csv.reader([ln]))
        if row and row[0] == "Height":
            start = i + 1
            break
        if len(row) >= 2:
            meta[row[0]] = row[1:]
    rows = [[np.nan if c.strip() == "" else float(c) for c in next(csv.reader([ln]))]
            for ln in lines[start:]]
    grid = np.full((len(rows), max(len(r) for r in rows)), np.nan)
    for i, r in enumerate(rows):
        grid[i, :len(r)] = r
    assert meta["XY Calibration"][1].lower() == "um" and meta["Unit"][0] == "mm"
    return grid * 1000.0, float(meta["XY Calibration"][0]), meta     # heights in um


def level(prof):
    """Drop edge gaps, fill short interior gaps, remove a least-squares line."""
    ok = np.isfinite(prof)
    if ok.sum() < 0.90 * prof.size:
        return None
    i0, i1 = np.argmax(ok), len(ok) - np.argmax(ok[::-1])
    seg = prof[i0:i1].copy()
    m = np.isfinite(seg)
    if m.sum() < 0.98 * seg.size:
        return None
    if not m.all():
        idx = np.arange(seg.size)
        seg[~m] = np.interp(idx[~m], idx[m], seg[m])
    x = np.arange(seg.size, dtype=float)
    a, b = np.polyfit(x, seg, 1)
    return seg - (a * x + b)


def analyse(path):
    grid, dx, meta = load(path)
    profs = [p for p in (level(grid[:, j]) for j in range(grid.shape[1])) if p is not None]
    n = min(len(p) for p in profs)
    P = np.array([p[:n] for p in profs])
    mean_line = gaussian_filter1d(P, SIG_FACTOR * LC_UM / dx, axis=1, mode="nearest", truncate=4.0)
    trim = int(round(0.5 * LC_UM / dx))
    R = (P - mean_line)[:, trim:n - trim]
    Pc = P - P.mean(axis=1, keepdims=True)
    Rc = R - R.mean(axis=1, keepdims=True)
    Pa = np.abs(Pc).mean(axis=1)
    Ra = np.abs(Rc).mean(axis=1)
    psd = (np.abs(np.fft.rfft(Pc * np.hanning(n), axis=1)) ** 2).mean(axis=0)
    f = np.fft.rfftfreq(n, d=dx)
    lam = np.full_like(f, np.inf)
    lam[1:] = 1 / f[1:]
    band = (lam > 60) & (lam < 320)
    return dict(file=Path(path).name, name=meta["Measurement data name"][0],
                date=meta["Measured date"][0], dx_um=dx, n_profiles=len(profs),
                field_um=(grid.shape[1] * dx, grid.shape[0] * dx),
                length_um=n * dx, Pa=float(Pa.mean()), Pa_sd=float(Pa.std(ddof=1)),
                Ra=float(Ra.mean()), Ra_sd=float(Ra.std(ddof=1)),
                pitch_um=float(lam[band][np.argmax(psd[band])]))


def display_map(path, clip_um=60.0):
    """Height map for a figure: each column levelled as in the analysis (so the
    picture shows what was measured), then clipped to +/- clip_um."""
    grid, dx, _ = load(path)
    out = np.full_like(grid, np.nan)
    for j in range(grid.shape[1]):
        col = grid[:, j]
        ok = np.isfinite(col)
        if ok.sum() < 10:
            continue
        x = np.arange(col.size, dtype=float)
        a, b = np.polyfit(x[ok], col[ok], 1)
        out[:, j] = col - (a * x + b)
    out -= np.nanmean(out)
    return np.clip(out, -clip_um, clip_um), dx


def by_rotor(folder):
    """One row per rotor; rotors with several scans are averaged, and the
    scan-to-scan difference is kept as the repeatability measure."""
    folder = Path(folder)
    scans = {fn: analyse(folder / fn) for fn in SCANS if (folder / fn).exists()}
    rows = {}
    for fn, r in scans.items():
        rows.setdefault(SCANS[fn], []).append(r)
    out = {}
    for rotor, rs in rows.items():
        out[rotor] = dict(
            n_scans=len(rs), n_profiles=sum(r["n_profiles"] for r in rs),
            Pa=float(np.mean([r["Pa"] for r in rs])), Ra=float(np.mean([r["Ra"] for r in rs])),
            pitch_um=float(np.mean([r["pitch_um"] for r in rs])),
            Pa_spread=float(np.ptp([r["Pa"] for r in rs])) if len(rs) > 1 else None,
            Ra_spread=float(np.ptp([r["Ra"] for r in rs])) if len(rs) > 1 else None,
            scans=rs)
    return out
