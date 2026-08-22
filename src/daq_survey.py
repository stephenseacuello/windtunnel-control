#!/usr/bin/env python3
"""
daq_survey.py — first-look analysis of a multichannel DAQ export.

    python daq_survey.py 03162026_sec_backup.xlsx

Answers the questions you need settled before trusting a dataset:

  · What is the sample rate and duration, really?
  · What ADC range and resolution is each channel on, and is anything
    near clipping?
  · How fast does each sensor actually respond?
  · Is any channel a scaled duplicate of another?
  · How much mains interference is present?
  · Where are the steady plateaus, and what is the mean in each?

═══════════════════════════════════════════════════════════════════════════
THE DETRENDING TRAP
═══════════════════════════════════════════════════════════════════════════
Lag-1 autocorrelation is the usual way to estimate a sensor's response time
and the effective sample size. It is also extremely easy to get wrong: if the
signal drifts at all across the window — a slow ramp, a spin-up transient, a
setpoint change — rho goes to ~1 regardless of the sensor's actual bandwidth,
because the trend dominates.

The consequence is not subtle. rho = 0.998 gives N_eff = 14 from 14,400
samples; rho = 0.26 gives N_eff = 8,457. That is a 24x difference in
confidence interval width, purely from whether the window was detrended.

This script therefore computes rho *within detected steady plateaus only*,
and reports both the raw and plateau figures so the gap is visible.
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd
from scipy import signal


def load(path, time_col=0):
    df = pd.read_excel(path) if str(path).endswith((".xlsx", ".xlsm")) \
        else pd.read_csv(path)
    t = df.iloc[:, time_col].values.astype(float)
    num = df.select_dtypes(include=[np.number])
    chans = {c: num[c].values.astype(float) for c in num.columns
             if not np.allclose(num[c].values, t)}
    return t, chans


def find_plateaus(x, fs, min_len_s=8.0, smooth_s=2.0):
    """
    Segment a stepped signal into steady regions.

    Median-smooth, find the largest jumps, and treat the spans between them as
    plateaus — trimming a settling margin off each end so a step's transient
    does not contaminate the statistics of the level that follows it.
    """
    w = max(3, int(smooth_s * fs))
    sm = pd.Series(x).rolling(w, center=True, min_periods=1).median().values
    d = np.abs(np.diff(sm))
    if not len(d):
        return []
    edges = np.where(d > np.percentile(d, 99.5))[0]

    groups, last = [], -10 ** 9
    for e in edges:
        if e - last > int(min_len_s * fs):
            groups.append(e)
        last = e

    bounds = [0] + groups + [len(x) - 1]
    out = []
    margin = int(3 * fs)
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b - a > min_len_s * fs:
            out.append((a + margin, b - int(fs)))
    return out


def channel_report(name, x, t, fs):
    r = {"channel": name, "mean": float(x.mean()), "std": float(x.std()),
         "min": float(x.min()), "max": float(x.max())}

    # ADC resolution from the smallest observed increment. Assumes a 12-bit
    # converter, which is what these exports have shown.
    u = np.unique(x)
    d = np.diff(u)
    lsb = float(d[d > 1e-12].min()) if len(d) and (d > 1e-12).any() else np.nan
    r["lsb"] = lsb
    r["range_v"] = lsb * 2048 / 2 if lsb == lsb else np.nan
    r["pct_of_range"] = (100 * np.abs(x).max() / r["range_v"]
                         if r["range_v"] == r["range_v"] and r["range_v"] > 0
                         else np.nan)

    # Raw vs plateau autocorrelation — see the module docstring.
    rho_raw = float(np.corrcoef(x[:-1], x[1:])[0, 1])
    r["rho_raw"] = rho_raw
    r["tau_raw"] = (1 / fs) / (1 - rho_raw) if rho_raw < 1 else np.inf

    plats = find_plateaus(x, fs)
    rhos = []
    for a, b in plats:
        seg = x[a:b]
        if len(seg) > 100:
            seg = seg - seg.mean()
            rhos.append(float(np.corrcoef(seg[:-1], seg[1:])[0, 1]))
    if rhos:
        rho_p = float(np.median(rhos))
        r["rho_plateau"] = rho_p
        r["tau_plateau"] = (1 / fs) / (1 - rho_p) if rho_p < 1 else np.inf
        r["bandwidth_hz"] = 1 / (2 * np.pi * r["tau_plateau"])
        n = len(x) / max(1, len(plats))
        r["n_eff_raw"] = n * (1 - rho_raw) / (1 + rho_raw)
        r["n_eff_plateau"] = n * (1 - rho_p) / (1 + rho_p)
    r["n_plateaus"] = len(plats)

    # Mains interference as a fraction of variance.
    xc = x - x.mean()
    if len(xc) > 8192:
        f, P = signal.welch(xc, fs, nperseg=8192)
        tot = np.trapezoid(P, f)
        for lo, hi, key in [(58, 62, "pct_60hz"), (48, 52, "pct_50hz")]:
            m = (f > lo) & (f < hi)
            r[key] = 100 * np.trapezoid(P[m], f[m]) / tot if tot > 0 else 0.0
        band = (f > 0.5) & (f < fs / 2 * 0.9)
        r["peak_hz"] = float(f[band][np.argmax(P[band])]) if band.any() else np.nan
    return r


def find_duplicates(chans, thresh=0.95):
    """Flag channels that are scaled copies of each other."""
    names = list(chans)
    dups = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            x, y = chans[a], chans[b]
            if x.std() == 0 or y.std() == 0:
                continue
            r = float(np.corrcoef(x, y)[0, 1])
            if abs(r) > thresh:
                k = np.polyfit(x, y, 1)
                resid = y - np.polyval(k, x)
                dups.append({"a": a, "b": b, "r": r, "gain": float(k[0]),
                             "offset": float(k[1]),
                             "unexplained_pct": 100 * resid.std() / y.std()})
    return dups


def main():
    p = argparse.ArgumentParser(description="survey a multichannel DAQ export")
    p.add_argument("file")
    p.add_argument("--time-col", type=int, default=0)
    a = p.parse_args()

    t, chans = load(a.file, a.time_col)
    dt = float(np.median(np.diff(t)))
    fs = 1 / dt

    print(f"{a.file}")
    print(f"  {len(t):,} samples · {fs:.1f} Hz · {t[-1] - t[0]:.1f} s "
          f"({(t[-1] - t[0]) / 60:.2f} min) · {len(chans)} channels\n")

    reports = [channel_report(n, x, t, fs) for n, x in chans.items()]

    print(f"{'ch':<8}{'mean':>9}{'std':>9}{'range':>8}{'%FS':>7}"
          f"{'peak Hz':>9}{'bw Hz':>8}{'60Hz%':>7}")
    print("─" * 65)
    for r in reports:
        print(f"{r['channel'][:7]:<8}{r['mean']:>9.4f}{r['std']:>9.4f}"
              f"{r.get('range_v', np.nan):>7.2f}V{r.get('pct_of_range', np.nan):>6.0f}%"
              f"{r.get('peak_hz', np.nan):>9.2f}{r.get('bandwidth_hz', np.nan):>8.1f}"
              f"{r.get('pct_60hz', 0):>7.2f}")

    print("\nFINDINGS")
    for r in reports:
        c = r["channel"]
        if r.get("pct_of_range", 0) > 90:
            print(f"  ! {c}: {r['pct_of_range']:.0f}% of ADC range — will clip "
                  f"if conditions get stronger. Drop the gain or raise the range.")
        if r.get("pct_60hz", 0) > 2:
            print(f"  ! {c}: {r['pct_60hz']:.1f}% of variance at 60 Hz — mains "
                  f"pickup. Check grounding, or notch it before analysis.")
        if "rho_plateau" in r and r["rho_raw"] > 0.9 and r["rho_plateau"] < 0.6:
            print(f"  ! {c}: rho is {r['rho_raw']:.3f} raw but "
                  f"{r['rho_plateau']:.3f} within plateaus. The raw figure is "
                  f"trend, not sensor lag. N_eff {r['n_eff_raw']:.0f} → "
                  f"{r['n_eff_plateau']:.0f}; CIs computed from the raw rho are "
                  f"~{np.sqrt(r['n_eff_plateau'] / max(r['n_eff_raw'], 1e-9)):.0f}x "
                  f"too wide.")

    for d in find_duplicates(chans):
        print(f"  ! {d['b']} ≈ {d['gain']:.3f}·{d['a']} {d['offset']:+.4f} "
              f"(r={d['r']:.3f}, {d['unexplained_pct']:.0f}% unexplained) — "
              f"deliberate dual-range, or a wiring duplicate?")

    # Plateau table for the slowest-varying channel — usually the setpoint proxy
    slow = max(reports, key=lambda r: r.get("n_plateaus", 0))
    x = chans[slow["channel"]]
    plats = find_plateaus(x, fs)
    if len(plats) > 1:
        print(f"\nSETPOINT PLATEAUS (from {slow['channel']})")
        print(f"  {'window':>16}{'mean':>10}{'std':>9}")
        for aa, bb in plats:
            seg = x[aa:bb]
            print(f"  {t[aa]:6.0f}–{t[bb]:6.0f}s{seg.mean():>10.4f}{seg.std():>9.4f}")


if __name__ == "__main__":
    main()
