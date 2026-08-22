"""
analyze.py — pull the tunnel's dynamic response out of a run log.

The claim made throughout this package is that the gap between commanded and
measured is data rather than error. This is the tool that cashes that in: point
it at any log from any run and it estimates the time constant, the lag, and how
much of the commanded amplitude actually survived.

    python analyze.py logs/20260812_143022_1mc.csv
    python analyze.py logs/*.csv --summary

No dedicated identification experiment needed. Every gust you run is also a
measurement of the tunnel that ran it.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np


def load(path):
    """Read a player log plus its metadata sidecar if present."""
    t, cmd, meas, amps = [], [], [], []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            t.append(float(row["t_s"]))
            cmd.append(float(row["cmd_hz"]))
            meas.append(float(row["meas_hz"]))
            amps.append(float(row["meas_a"]))

    meta = {}
    side = Path(path).with_suffix(".json")
    if side.exists():
        meta = json.loads(side.read_text())

    return (np.array(t), np.array(cmd), np.array(meas),
            np.array(amps), meta)


def estimate_tau(t, cmd, meas, tau_grid=None):
    """
    Fit the time constant by brute force: filter the command through a
    first-order lag for each candidate tau and keep the one that best matches
    the measurement.

    Brute force rather than an analytic fit because it works on *any* input —
    gust, turbulence, sweep — not just a clean step. That is the whole point:
    you get tau from whatever you happened to run.

    Returns (tau, r2, predicted).
    """
    if tau_grid is None:
        tau_grid = np.linspace(0.2, 20.0, 200)

    dt = float(np.median(np.diff(t)))
    n = len(cmd)
    good = ~np.isnan(meas)
    if good.sum() < 20:
        return float("nan"), 0.0, None

    freqs = np.fft.rfftfreq(n, dt)
    spec = np.fft.rfft(cmd - cmd.mean())
    offset = meas[good].mean() - cmd.mean()

    best = (float("nan"), -np.inf, None)
    for tau in tau_grid:
        H = 1.0 / (1.0 + 1j * 2 * np.pi * freqs * tau)
        pred = np.fft.irfft(spec * H, n=n) + cmd.mean() + offset
        resid = meas[good] - pred[good]
        var = np.var(meas[good])
        r2 = 1 - np.var(resid) / var if var > 0 else 0.0
        if r2 > best[1]:
            best = (float(tau), float(r2), pred)
    return best


def analyze(path, verbose=True):
    """
    Fit the tunnel's response from a run log.

    Returns tau, retained amplitude, lag and peak current. Also detects runs
    that began before the flow settled -- those produce impossible statistics
    (retention above 100%), so the transient is trimmed and flagged rather
    than quietly skewing the fit.
    """
    t, cmd, meas, amps, meta = load(path)
    good = ~np.isnan(meas)

    out = {"file": str(path), "samples": len(t),
           "duration_s": float(t[-1]) if len(t) else 0.0}
    if meta:
        out["mode"] = meta.get("mode")
        out["complete"] = meta.get("run", {}).get("complete")

    # Did the run start settled? If the flow was still climbing toward the
    # baseline when the profile began, every amplitude statistic below is
    # contaminated by the spin-up — and the numbers come out impossible
    # (retention above 100%) rather than merely wrong, which at least makes
    # the problem visible. Detect it, exclude the transient, and say so.
    start_gap = abs(float(meas[0]) - float(cmd[0])) if good[0] else 0.0
    span = float(cmd.max() - cmd.min())
    unsettled = start_gap > max(0.5 * span, 1.0)
    out["start_gap_hz"] = start_gap
    out["unsettled_start"] = bool(unsettled)

    if unsettled:
        # Trim until the measurement first comes within 10% of the command.
        tol = max(0.1 * span, 0.5)
        close = np.where(np.abs(meas - cmd) < tol)[0]
        skip = int(close[0]) if len(close) else len(t) // 4
        out["trimmed_samples"] = skip
        t, cmd, meas, amps = t[skip:], cmd[skip:], meas[skip:], amps[skip:]
        good = ~np.isnan(meas)

    cmd_pp = float(cmd.max() - cmd.min())
    meas_pp = float(meas[good].max() - meas[good].min()) if good.any() else 0.0
    out["cmd_peak_to_peak"] = cmd_pp
    out["meas_peak_to_peak"] = meas_pp
    out["amplitude_retained"] = meas_pp / cmd_pp if cmd_pp > 0 else float("nan")
    out["peak_current_a"] = float(np.nanmax(amps)) if len(amps) else float("nan")

    tau, r2, pred = estimate_tau(t, cmd, meas)
    out["tau_s"] = tau
    out["fit_r2"] = r2
    out["f_corner_hz"] = 1 / (2 * np.pi * tau) if tau == tau and tau > 0 else float("nan")

    # Lag via cross-correlation of the fluctuating parts.
    if good.sum() > 20 and cmd_pp > 0:
        a = cmd - cmd.mean()
        b = np.where(good, meas - np.nanmean(meas[good]), 0.0)
        xc = np.correlate(b, a, mode="full")
        lag_samples = int(np.argmax(xc) - (len(a) - 1))
        out["lag_s"] = float(lag_samples * np.median(np.diff(t)))

    if verbose:
        print(f"\n{Path(path).name}")
        if meta.get("mode"):
            desc = meta.get("shape") or meta.get("model") or ""
            print(f"  {meta['mode']} {desc}"
                  + (f"  seed {meta['seed']}" if meta.get("seed") else ""))
        if out.get("complete") is False:
            reason = meta.get("run", {}).get("aborted_reason", "")
            print(f"  INCOMPLETE — {reason}")
        print(f"  {out['duration_s']:.0f} s, {out['samples']} samples")
        if out.get("unsettled_start"):
            print(f"  ! RUN STARTED UNSETTLED — flow was {out['start_gap_hz']:.1f} Hz "
                  f"from the commanded baseline at t=0.")
            print(f"    The settle time was too short for this tunnel's time "
                  f"constant. Trimmed {out['trimmed_samples']} samples; "
                  f"increase --settle to at least 4τ next time.")
        print(f"  commanded p-p {cmd_pp:.2f} Hz → measured {meas_pp:.2f} Hz "
              f"({out['amplitude_retained']:.0%} retained)")
        if tau == tau:
            print(f"  fitted τ = {tau:.2f} s  (R² = {r2:.3f}) → corner "
                  f"{out['f_corner_hz']:.3f} Hz")
            if r2 < 0.7:
                print(f"    NOTE  poor fit. A single first-order lag may not "
                      f"describe this run — check for a mid-run fault, or a "
                      f"profile with too little excitation to identify from.")
        if "lag_s" in out:
            print(f"  lag ≈ {out['lag_s']:.2f} s")
        print(f"  peak current {out['peak_current_a']:.1f} A")

        # Compare against what was predicted before the run, if recorded.
        pre = meta.get("diagnostics", {}).get("amplitude_retained")
        if pre is not None:
            err = out["amplitude_retained"] - pre
            print(f"  predicted {pre:.0%} before the run, measured "
                  f"{out['amplitude_retained']:.0%} ({err:+.0%})")
            if abs(err) > 0.15:
                print(f"    the tunnel model is off — re-run `characterize` "
                      f"and update τ in the config")

    return out


def plot(path, out_png=None, tau=None):
    """
    Overlay commanded vs measured, with the fitted model. This is the figure
    that goes in the paper — the numbers alone never convince anyone that the
    gap between command and flow is physics rather than a bug.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  matplotlib not installed — pip install matplotlib")
        return None

    t, cmd, meas, amps, meta = load(path)
    good = ~np.isnan(meas)
    tau_fit, r2, pred = estimate_tau(t, cmd, meas)

    fig, ax = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                           gridspec_kw={"height_ratios": [3, 1]})

    ax[0].plot(t, cmd, lw=1.6, label="commanded", color="#1f77b4")
    ax[0].plot(t[good], meas[good], lw=1.4, label="measured (drive)",
               color="#d62728")
    if pred is not None:
        ax[0].plot(t, pred, lw=1.0, ls="--", color="#2ca02c",
                   label=f"first-order fit, τ={tau_fit:.2f} s (R²={r2:.3f})")
    ax[0].set_ylabel("frequency (Hz)")
    ax[0].legend(loc="best", fontsize=9)
    ax[0].grid(alpha=0.3)

    title = Path(path).name
    if meta.get("mode"):
        bits = [meta["mode"], meta.get("shape") or meta.get("model") or ""]
        if meta.get("seed") is not None:
            bits.append(f"seed {meta['seed']}")
        title += "   " + " · ".join(b for b in bits if b)
    if meta.get("run", {}).get("complete") is False:
        title += "   [INCOMPLETE]"
    ax[0].set_title(title, fontsize=10, loc="left")

    ax[1].plot(t[good], amps[good], lw=1.0, color="#7f7f7f")
    ax[1].set_ylabel("current (A)")
    ax[1].set_xlabel("time (s)")
    ax[1].grid(alpha=0.3)

    fig.tight_layout()
    out_png = out_png or str(Path(path).with_suffix(".png"))
    fig.savefig(out_png, dpi=130)
    plt.close(fig)
    print(f"  wrote {out_png}")
    return out_png


def main():
    p = argparse.ArgumentParser(description="analyze wind tunnel run logs")
    p.add_argument("files", nargs="+")
    p.add_argument("--summary", action="store_true",
                   help="one line per file plus an aggregate τ")
    p.add_argument("--json", action="store_true", help="emit JSON")
    p.add_argument("--plot", action="store_true",
                   help="write a PNG next to each log")
    a = p.parse_args()

    results = [analyze(f, verbose=not (a.summary or a.json)) for f in a.files]
    if a.plot:
        for f in a.files:
            plot(f)

    if a.json:
        print(json.dumps(results, indent=2))
        return

    if a.summary:
        print(f"{'file':<38} {'τ':>7} {'R²':>6} {'retained':>9}")
        print("─" * 64)
        for r in results:
            print(f"{Path(r['file']).name:<38} {r['tau_s']:>7.2f} "
                  f"{r['fit_r2']:>6.3f} {r['amplitude_retained']:>8.0%}")
        taus = [r["tau_s"] for r in results
                if r["tau_s"] == r["tau_s"] and r["fit_r2"] > 0.7]
        if len(taus) > 1:
            print(f"\n  τ across {len(taus)} good fits: "
                  f"{np.mean(taus):.2f} ± {np.std(taus):.2f} s")
            if np.std(taus) > 0.25 * np.mean(taus):
                print("  spread is wide — τ may vary with operating point, "
                      "which a single first-order model cannot capture. Worth "
                      "characterizing at more than one baseline speed.")


if __name__ == "__main__":
    main()
