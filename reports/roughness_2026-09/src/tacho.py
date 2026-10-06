"""T. Kang's per-sample tachometer records, aligned to the rig's load dwells.

Each raw file (360 Hz) has a Relative Time column, a UTC wall-clock stamp, five voltage channels
and an event column. Findings that the code relies on (checked 6 Oct 2026):

* Relative Time is real time. The UTC stamp column advances about 8% faster within a file (a
  logging artefact), so it is used only at the first sample of each recording segment.
* Recording was sometimes paused; a "Resume" event starts a new segment, and Relative Time skips
  the pause. Each segment is anchored at its own first stamp.
* Channel 1 tracks the rig's terminal voltage (about 0.25 V/V); it aligns the clocks without any
  speed or generator model.
* Channel 3 (the sixth column) is the tachometer: a proximity sensor triggered by a magnet glued
  to one blade, re-glued for each blade set; one pulse per revolution, rising through -0.75 V
  (as in RPM.m).

The clock offset and drift between the DAQ and the rig host are fitted per run from channel 1
alone. At that alignment, V = k*n - R*I + b gives the generator constant k and the electrical
source resistance R, free of the rotor slowing that inflates the Thevenin R_int. The speed-model
alignment (the offset that best fits that equation) is kept as a cross-check.
"""
import numpy as np
import pandas as pd

import data as D

RAW_DIR = (D.RPM_DIR / "raw") if D.PACKAGED else (D.RPM_DIR.parent / "raw")
THRESHOLD_V = -0.75          # RPM.m's pulse threshold
MIN_SEGMENT_S = 30.0         # drop stray segments (a few seconds after a late resume)
WINDOW_S = 0.6               # speed window ending at the dwell's measurement stamp
EARLY_S = (1.0, 0.6)         # the early part of the same dwell, for the settling check


def raw_path(stem):
    hits = [RAW_DIR / f"sweep_{stem}{s}.csv.gz" for s in ("_RPM", "")]
    hits = [h for h in hits if h.is_file()]
    if len(hits) != 1:
        raise FileNotFoundError(f"{stem}: {len(hits)} raw tachometer files in {RAW_DIR}")
    return hits[0]


def load_raw(stem):
    """Time base (unix s, DAQ clock) and tachometer channel, stray segments removed."""
    d = pd.read_csv(raw_path(stem), low_memory=False)
    d.columns = ["rel", "date", "ts", "c1", "c2", "c3", "c4", "c5", "ev"]
    wall = pd.to_datetime(d.date + " " + d.ts, format="%m/%d/%Y %I:%M:%S %p")
    wall = wall.values.astype("datetime64[s]").astype("int64")
    rel = d.rel.to_numpy(float)
    starts = [0] + d.index[d.ev.astype(str).str.contains("Resume")].tolist()
    t = np.full(len(rel), np.nan)
    for a, b in zip(starts, starts[1:] + [len(rel)]):
        if rel[b - 1] - rel[a] >= MIN_SEGMENT_S:
            t[a:b] = wall[a] + (rel[a:b] - rel[a])
    keep = ~np.isnan(t)
    return dict(t=t[keep], tach=d.c3.to_numpy(float)[keep], v_daq=d.c1.to_numpy(float)[keep],
                fs=1 / np.median(np.diff(rel[:1000])))


def pulses(raw, repair=True):
    """Pulse times, one per revolution. With repair, a missed pulse (interval about twice the
    local median) is filled at evenly spaced times and a spurious one (two short intervals that
    together make a normal one) is dropped. Returns the times and the number of repairs."""
    x, t = raw["tach"], raw["t"]
    up = np.where((x[:-1] < THRESHOLD_V) & (x[1:] >= THRESHOLD_V))[0] + 1
    tp = t[up]
    tp = tp[np.r_[True, np.diff(tp) > 60 / 2000]]          # double triggers faster than 2000 rpm
    if not repair:
        return tp, 0
    fixes = 0
    for _ in range(3):
        dt = np.diff(tp)
        med = pd.Series(dt).rolling(9, center=True, min_periods=3).median().to_numpy()
        short = np.where(dt < 0.6 * med)[0]
        drop = [i + 1 for i in short if i + 1 < len(dt) and dt[i] + dt[i + 1] < 1.4 * med[i]]
        out = []
        for i in range(len(dt)):
            k = int(round(dt[i] / med[i]))
            if dt[i] > 1.6 * med[i] and 2 <= k <= 4:
                out.append(tp[i] + dt[i] * np.arange(1, k) / k)
        if not drop and not out:
            break
        fixes += len(drop) + sum(len(o) for o in out)
        tp = np.sort(np.r_[np.delete(tp, drop), np.concatenate(out) if out else []])
    return tp, fixes


def speed_at(tp, ends, w):
    """Mean speed (rpm) over (end - w, end]: revolutions counted by interpolating the cumulative
    pulse count, so a window shorter than one revolution still gets a speed."""
    k = np.arange(len(tp), dtype=float)
    def count(x):
        return np.interp(x, tp, k, left=np.nan, right=np.nan)
    return 60 * (count(ends) - count(ends - w)) / w


def dwells(points):
    """Load dwells usable for alignment and analysis: tracked, positive current."""
    p = points[(points.tracking == 1) & (points.amps > 0)].copy()
    return p.reset_index(drop=True)


def rig_to_daq(t_rig, fit):
    """Map rig host time to DAQ time: offset plus a small clock-rate difference."""
    return fit["t0"] + (t_rig - fit["t0"]) * (1 + fit["drift"]) + fit["offset"]


def _score(tp, ends, V, I):
    """Robust fit of V = k n - R I + b: one refit without residuals beyond 5x the median
    absolute residual (stretches of missed pulses). Returns rms of the kept dwells."""
    n = speed_at(tp, ends, WINDOW_S)
    m = ~np.isnan(n)
    if m.sum() < 0.9 * len(n):
        return None
    X = np.c_[n, -I, np.ones(len(n))]
    c, *_ = np.linalg.lstsq(X[m], V[m], rcond=None)
    r = np.abs(V - X @ c)
    keep = m & (r <= 5 * np.median(r[m]))
    c, *_ = np.linalg.lstsq(X[keep], V[keep], rcond=None)
    return float(np.sqrt(((V[keep] - X[keep] @ c) ** 2).mean())), c, int(keep.sum())


def fit_offset(tp, p):
    """Clock offset (s) and drift (fraction) mapping rig time to DAQ time that best fit
    V = k n - R I + b over the dwells at fan > 500 rpm. Coarse grid, then a fine grid."""
    q = p[p.fan_rpm > 500]
    t_rig = q.t_unix.to_numpy(float)
    V, I = q.volts.to_numpy(float), q.amps.to_numpy(float)
    t0 = float(t_rig[0])
    best = None
    for stage in ("coarse", "fine"):
        if stage == "coarse":
            drifts, offs = np.arange(-0.02, 0.02001, 0.001), np.arange(-10, 10.001, 0.25)
        else:
            drifts = best["drift"] + np.arange(-0.001, 0.00101, 0.0001)
            offs = best["offset"] + np.arange(-0.5, 0.501, 0.02)
        for e in drifts:
            for o in offs:
                r = _score(tp, t0 + (t_rig - t0) * (1 + e) + o, V, I)
                if r and (best is None or r[0] < best["rms"]):
                    best = dict(t0=t0, drift=float(e), offset=float(o), rms=r[0], k=float(r[1][0]),
                                R=float(r[1][1]), b=float(r[1][2]), n_fit=r[2], n_dwells=len(V))
    return best


V_WINDOW_S = 0.3             # DAQ voltage window ending at the rig's measurement stamp


def align_by_voltage(raw, p):
    """Clock offset and drift from the DAQ voltage channel alone: the mapping of rig time to DAQ
    time that maximises the correlation between the DAQ voltage (mean over V_WINDOW_S) and the
    rig's measured terminal voltage over all dwells. Uses no speed or generator model."""
    t, v = raw["t"], raw["v_daq"]
    cs = np.r_[0.0, np.cumsum(v)]
    t_rig = p.t_unix.to_numpy(float)
    V = p.volts.to_numpy(float)
    t0 = float(t_rig[0])
    best = None
    for stage in ("coarse", "fine"):
        # drift fixed at zero: the voltage correlation is too flat to separate a drift from an
        # offset, and the speed-model alignment finds |drift| <= 0.2% on every run
        drifts = [0.0]
        if stage == "coarse":
            offs = np.arange(-10, 10.001, 0.1)
        else:
            offs = best["offset"] + np.arange(-0.2, 0.2001, 0.01)
        for e in drifts:
            for o in offs:
                ends = t0 + (t_rig - t0) * (1 + e) + o
                i1 = np.searchsorted(t, ends)
                i0 = np.searchsorted(t, ends - V_WINDOW_S)
                ok = (i1 > i0) & (i1 < len(t))
                if ok.sum() < 0.9 * len(ends):
                    continue
                m = (cs[i1] - cs[i0])[ok] / (i1 - i0)[ok]
                r = float(np.corrcoef(m, V[ok])[0, 1])
                if best is None or r > best["r_voltage"]:
                    best = dict(t0=t0, drift=float(e), offset=float(o), r_voltage=r)
    return best


def generator_fit(tp, p, fit):
    """k, R, b of V = k n - R I + b at fan > 500 rpm, at a given alignment (robust, as _score)."""
    q = p[p.fan_rpm > 500]
    r = _score(tp, rig_to_daq(q.t_unix.to_numpy(float), fit), q.volts.to_numpy(float),
               q.amps.to_numpy(float))
    rms, c, n = r
    return dict(k=float(c[0]), R=float(c[1]), b=float(c[2]), rms=rms, n_fit=n, n_dwells=len(q))


def run_table(stem):
    """Per-dwell table for one run: rig measurements plus tachometer speed."""
    run = D.load(stem)
    p = dwells(run["points"])
    raw = load_raw(stem)
    tp, fixes = pulses(raw)
    fit = align_by_voltage(raw, p)                      # primary: model-free
    fit.update(generator_fit(tp, p, fit))
    check = fit_offset(tp, p)                           # cross-check: speed-model alignment
    fit.update(pulse_repairs=fixes, offset_speed_model=check["offset"],
               drift_speed_model=check["drift"])
    ends = rig_to_daq(p.t_unix.to_numpy(float), fit)
    p["rotor_rpm"] = speed_at(tp, ends, WINDOW_S)
    p["rotor_rpm_early"] = speed_at(tp, ends - EARLY_S[1], EARLY_S[0] - EARLY_S[1])
    # a stretch of missed pulses halves the apparent speed for a dwell or two; at a fixed fan
    # speed the rotor cannot do that between neighbouring dwells, so such dwells are flagged
    ref = p.groupby("fan_rpm").rotor_rpm.transform(
        lambda x: x.rolling(5, center=True, min_periods=3).median())
    p["speed_ok"] = (np.abs(p.rotor_rpm / ref - 1) <= 0.2) & p.rotor_rpm.notna()
    p.loc[~p.speed_ok, ["rotor_rpm", "rotor_rpm_early"]] = np.nan
    # the early window can catch the same dropouts; a dwell cannot change speed by 20%
    bad_early = np.abs(p.rotor_rpm_early / p.rotor_rpm - 1) > 0.2
    p.loc[bad_early, "rotor_rpm_early"] = np.nan
    v = D.wind(p.fan_rpm.to_numpy(float))
    omega = 2 * np.pi * p.rotor_rpm / 60
    p["wind_mps"] = v
    p["tsr"] = omega * D.R_M / v
    p["cp_el"] = p.watts / (0.5 * D.RHO_STD * D.AREA_M2 * v ** 3)
    p["torque_el_nm"] = p.watts / omega
    p["stem"] = stem
    return p, fit
