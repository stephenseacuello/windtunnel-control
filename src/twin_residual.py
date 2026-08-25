#!/usr/bin/env python3
"""
twin_residual.py — run the model beside the measurement and plot the gap.

    python src/twin_residual.py --sweep logs/sweep_v1_Ra20_points.csv
    python src/twin_residual.py --sweep logs/sweep_v1_Ra20_points.csv --svg docs/diagrams/residual.svg

═══════════════════════════════════════════════════════════════════════════
WHAT MAKES A TWIN A TWIN
═══════════════════════════════════════════════════════════════════════════
A spinning 3D rotor is visualisation. A digital twin is a model that runs
alongside reality and tells you **when the two disagree**, because the
disagreement is the only part that carries information.

This fits `load_sim.SimulatedTurbine` to each measured wind speed and reports
the residual. The model is deliberately simple:

    V(I) = V_oc · sqrt(1 - I/I_stall)

so a small residual means the rotor behaves like a source with a soft limit,
and a large or structured residual means it does not — and the SHAPE of the
disagreement says which way.

Every bug this project actually hit would have shown here first:

  · the sweep that outran the wind — the model tracks, then the tail
    collapses while the model keeps rising
  · the load that never sank current — measured flat at zero, model fine
  · the fan that never reached speed — every point low by the same ratio
  · a blade degrading between runs — residual drifts one way over a session

None of those announce themselves in a raw P(I) curve. All of them are
obvious in a residual.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))


def read_points(path):
    """Group a *_points.csv by fan rpm."""
    with open(path) as f:
        body = [l for l in f if not l.startswith("#")]
    by = defaultdict(list)
    for r in csv.DictReader(body):
        try:
            if r.get("tracking") not in (None, "", "1", "True", "true"):
                continue
            rpm = int(float(r.get("fan_rpm") or 0))
            by[rpm].append((float(r["amps"]), float(r["volts"]),
                            float(r["watts"]), float(r.get("wind_mps") or 0)))
        except (TypeError, ValueError, KeyError):
            continue
    return by


def fit_source(I, V):
    """
    Fit V = V_oc*sqrt(1 - I/I_stall) by linearising on V².

    V² = V_oc² - (V_oc²/I_stall)·I is a straight line in I, so the fit is a
    single least-squares solve with no starting guess to get wrong.
    """
    I, V = np.asarray(I, float), np.asarray(V, float)
    m = V > 0
    if m.sum() < 3:
        return None
    a, b = np.polyfit(I[m], V[m] ** 2, 1)
    if b <= 0 or a >= 0:
        return None
    return {"v_oc": math.sqrt(b), "i_stall": b / -a}


def model_v(I, v_oc, i_stall):
    x = np.clip(np.asarray(I, float) / i_stall, 0, 1)
    return v_oc * np.sqrt(1.0 - x)


def analyse(by_rpm):
    out = []
    for rpm in sorted(by_rpm):
        pts = by_rpm[rpm]
        I = np.array([p[0] for p in pts]); V = np.array([p[1] for p in pts])
        P = np.array([p[2] for p in pts]); mps = pts[0][3]
        fit = fit_source(I, V)
        if not fit:
            continue
        Vm = model_v(I, fit["v_oc"], fit["i_stall"])
        res = V - Vm
        denom = max(V.max(), 1e-9)
        rmse = float(np.sqrt(np.mean(res ** 2)))
        # A residual that is mostly one sign is structure, not noise.
        bias = float(np.mean(res))
        out.append({
            "rpm": rpm, "mps": mps, "n": len(I),
            "v_oc": fit["v_oc"], "i_stall": fit["i_stall"],
            "rmse": rmse, "rmse_pct": 100 * rmse / denom,
            "bias_pct": 100 * bias / denom,
            "p_max": float(P.max()),
            "I": I, "V": V, "Vm": Vm, "res": res})
    return out


def svg(rows, path):
    """A residual plot, hand-drawn — the repo vendors no plotting library."""
    W, H, pad = 1000, 520, 64
    xs = np.concatenate([r["I"] * 1000 for r in rows])
    ys = np.concatenate([r["res"] for r in rows])
    x0, x1 = 0, float(xs.max()) * 1.05
    lim = float(np.abs(ys).max()) * 1.15 or 1
    X = lambda v: pad + (v - x0) / (x1 - x0) * (W - 2 * pad)
    Y = lambda v: H / 2 - v / lim * (H / 2 - pad)
    cols = ["#0b6fb4", "#00a3a1", "#8a7038", "#b03030", "#5b7288",
            "#7a4fa3", "#2e7d32"]
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
         f'width="{W}" height="{H}" font-family="Inter, Arial, sans-serif">',
         f'<rect width="{W}" height="{H}" fill="#fbfcfd"/>',
         f'<text x="{pad}" y="34" font-size="17" font-weight="700" '
         f'fill="#0d2338">Digital twin residual — measured minus model</text>',
         f'<text x="{pad}" y="54" font-size="11.5" fill="#5b7288">'
         f'V(I) = V_oc·√(1 − I/I_stall) fitted per wind speed. '
         f'Structure here is physics the model is missing.</text>',
         f'<line x1="{pad}" y1="{Y(0)}" x2="{W-pad}" y2="{Y(0)}" '
         f'stroke="#0d2338" stroke-width="1.2"/>']
    for i, r in enumerate(rows):
        c = cols[i % len(cols)]
        d = " ".join(f"{'M' if k == 0 else 'L'}{X(a*1000):.1f},{Y(v):.1f}"
                     for k, (a, v) in enumerate(zip(r["I"], r["res"])))
        p.append(f'<path d="{d}" fill="none" stroke="{c}" stroke-width="1.6" '
                 f'opacity="0.85"/>')
        p.append(f'<text x="{W-pad+6}" y="{Y(r["res"][-1]):.1f}" font-size="9.5" '
                 f'fill="{c}">{r["rpm"]}</text>')
    for frac in (0, .25, .5, .75, 1.0):
        v = x0 + frac * (x1 - x0)
        p.append(f'<text x="{X(v):.0f}" y="{H-24}" font-size="10" fill="#5b7288" '
                 f'text-anchor="middle">{v:.0f}</text>')
    p.append(f'<text x="{W/2}" y="{H-8}" font-size="11" fill="#5b7288" '
             f'text-anchor="middle">load current (mA)</text>')
    p.append(f'<text x="{pad-10}" y="{Y(lim*0.85):.0f}" font-size="10" '
             f'fill="#5b7288" text-anchor="end">+{lim:.2f} V</text>')
    p.append(f'<text x="{pad-10}" y="{Y(-lim*0.85):.0f}" font-size="10" '
             f'fill="#5b7288" text-anchor="end">−{lim:.2f} V</text>')
    p.append("</svg>")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(p))


def main():
    a = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    a.add_argument("--sweep", required=True, help="a *_points.csv")
    a.add_argument("--svg", default=None, help="write a residual plot here")
    a.add_argument("--warn-pct", type=float, default=8.0,
                   help="flag a wind speed whose RMSE exceeds this %% of V_oc")
    args = a.parse_args()

    rows = analyse(read_points(args.sweep))
    if not rows:
        raise SystemExit(f"no fittable wind speeds in {args.sweep}")

    print(f"\n  model:  V(I) = V_oc · sqrt(1 − I/I_stall), fitted per wind speed\n")
    print(f"  {'fan rpm':>8} {'m/s':>6} {'n':>4} {'V_oc':>7} {'I_stall':>8} "
          f"{'RMSE':>8} {'RMSE %':>7} {'bias %':>7}")
    print(f"  {'-'*8} {'-'*6} {'-'*4} {'-'*7} {'-'*8} {'-'*8} {'-'*7} {'-'*7}")
    bad = []
    for r in rows:
        flag = " ←" if r["rmse_pct"] > args.warn_pct else ""
        if flag:
            bad.append(r)
        print(f"  {r['rpm']:>8} {r['mps']:>6.1f} {r['n']:>4} {r['v_oc']:>7.2f} "
              f"{r['i_stall']:>8.4f} {r['rmse']:>8.4f} {r['rmse_pct']:>7.2f} "
              f"{r['bias_pct']:>+7.2f}{flag}")

    med = float(np.median([r["rmse_pct"] for r in rows]))
    print(f"\n  median residual {med:.2f}% of open-circuit volts across "
          f"{len(rows)} wind speeds")
    if med < 4:
        print(f"  The rotor behaves like a source with a soft limit, at every "
              f"wind speed tested.")
    if bad:
        print(f"\n  ⚠ {len(bad)} wind speed(s) above {args.warn_pct}%: "
              f"{', '.join(str(r['rpm']) for r in bad)} rpm")
        print(f"    A residual that is large OR one-sided is structure, not "
              f"noise. Check the\n    bias column — a consistent sign means "
              f"the model is missing a term, not\n    that the data is noisy.")

    v = np.array([r["mps"] for r in rows]); vo = np.array([r["v_oc"] for r in rows])
    n, _ = np.polyfit(np.log(v), np.log(vo), 1)
    print(f"\n  V_oc ∝ v^{n:.2f}  (v^1.0 if runaway tip-speed ratio were "
          f"constant)")
    if n > 1.15:
        print(f"    Rising faster than v means the rotor spins RELATIVELY "
              f"faster as wind\n    rises — Cp still climbing with Reynolds "
              f"across the test range.")

    if args.svg:
        svg(rows, args.svg)
        print(f"\n  wrote {args.svg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
