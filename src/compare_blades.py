#!/usr/bin/env python3
"""
compare_blades.py — compare two rotors without fooling yourself.

    python src/compare_blades.py v1_Ra20 v1_Ra80
    python src/compare_blades.py v1_Ra20 v1_Ra80 --svg docs/diagrams/compare.svg

═══════════════════════════════════════════════════════════════════════════
THE THREE WAYS THIS COMPARISON GOES WRONG QUIETLY
═══════════════════════════════════════════════════════════════════════════

1. DIFFERENT PROTOCOLS. Two blades measured under different settings are not
   two data points. Every sweep records a fingerprint; this refuses to compare
   across a mismatch rather than producing a plausible number.

2. COMPARING A FIT AGAINST AN ARGMAX. The summary format changed on 22 Aug.
   Runs before it carry a single `p_max_w`; runs after carry `p_max_fit_w` AND
   `p_max_raw_w`.

   `p_max_w` is the RAW argmax — established empirically, not assumed: it
   matches the largest single dwell in sweep_v1_Ra20_points.csv at 14 of 14
   points, exactly.

   The argmax is biased HIGH over a flat maximum, by ~1.3% on the reference
   sweep. Comparing one blade's fit against another's argmax would inject that
   bias straight into the difference, and it is the same size as the effect a
   roughness comparison is looking for. This picks like for like and says
   which it used.

3. READING THE EXPONENT INSTEAD OF THE LEVEL. A uniform power change gives
   Δn = 0.000 exactly — the exponent is blind to the most likely outcome. The
   headline here is the LEVEL, with a confidence interval, computed PAIRED at
   matched set points so wind-calibration error and the rig's structured
   residual cancel.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

import numpy as np

LOGS = Path(__file__).resolve().parents[1] / "logs"


def load(name):
    """A sweep summary plus its recorded protocol."""
    p = name if Path(name).exists() else LOGS / f"sweep_{name}_summary.csv"
    p = Path(p)
    if not p.exists():
        raise SystemExit(f"no sweep found for {name!r} (looked at {p})")
    meta, body = {}, []
    for line in p.read_text().splitlines(True):
        if line.startswith("#"):
            k, _, v = line[1:].strip().partition(",")
            meta[k.strip()] = v.strip().strip('"')
        else:
            body.append(line)
    return {"name": name, "path": p, "meta": meta,
            "rows": list(csv.DictReader(body))}


def pick_column(a, b):
    """
    The power column to use, identical in meaning on both sides.

    Prefers the parabolic fit when BOTH have it — it is the better estimator.
    Falls back to raw when either side predates the fit columns, because a fit
    against an argmax is not a comparison.
    """
    ca, cb = set(a["rows"][0]), set(b["rows"][0])
    if "p_max_fit_w" in ca and "p_max_fit_w" in cb:
        return "p_max_fit_w", "p_max_fit_w", "parabolic fit (both runs)"
    def raw(c):
        return ("p_max_raw_w" if "p_max_raw_w" in c else
                "p_max_w" if "p_max_w" in c else None)
    ra, rb = raw(ca), raw(cb)
    if ra and rb:
        why = ("raw argmax — one run predates the fit columns, and a fit "
               "against an argmax is not a comparison")
        return ra, rb, why
    raise SystemExit("no power column common to both runs")


def paired(a, b, col_a, col_b):
    """Match on commanded fan rpm; ratio at each matched point."""
    ia = {int(float(r["fan_rpm_cmd"])): r for r in a["rows"]}
    ib = {int(float(r["fan_rpm_cmd"])): r for r in b["rows"]}
    out = []
    for rpm in sorted(set(ia) & set(ib)):
        ra, rb = ia[rpm], ib[rpm]
        pa, pb = float(ra[col_a]), float(rb[col_b])
        if pa <= 0 or pb <= 0:
            continue
        v = 0.5 * (float(ra["wind_mps"]) + float(rb["wind_mps"]))
        clean = ((ra.get("clean") or "1") in ("1", "True", "true") and
                 (rb.get("clean") or "1") in ("1", "True", "true"))
        out.append({"rpm": rpm, "v": v, "pa": pa, "pb": pb,
                    "ratio": pb / pa, "clean": clean})
    return out


def analyse(pts):
    """
    Regress ln(P_b/P_a) on ln v.

    Intercept is the LEVEL difference, slope is Δn. Both come with a standard
    error from the residual scatter, which is the only honest way to say
    whether a few percent means anything.
    """
    v = np.array([p["v"] for p in pts])
    lr = np.log(np.array([p["ratio"] for p in pts]))
    x = np.log(v)
    n = len(v)
    slope, icept = np.polyfit(x, lr, 1)
    resid = lr - (icept + slope * x)
    dof = max(1, n - 2)
    s = math.sqrt(float((resid ** 2).sum()) / dof)
    sxx = float(((x - x.mean()) ** 2).sum())
    se_slope = s / math.sqrt(sxx) if sxx > 0 else float("inf")
    se_level = s / math.sqrt(n)
    level = float(np.exp(lr.mean()) - 1.0)      # mean ratio, not the intercept
    return {"n": n, "level": level, "se_level": float(se_level),
            "dn": float(slope), "se_dn": float(se_slope),
            "resid_pct": float(100 * s), "ratios": lr}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("baseline")
    ap.add_argument("candidate")
    ap.add_argument("--force", action="store_true",
                    help="compare across a fingerprint mismatch anyway")
    a = ap.parse_args()

    A, B = load(a.baseline), load(a.candidate)
    fa = A["meta"].get("protocol", "?")
    fb = B["meta"].get("protocol", "?")

    print(f"\n  baseline   {A['name']:<14} {fa}   {A['meta'].get('notes','')}")
    print(f"  candidate  {B['name']:<14} {fb}   {B['meta'].get('notes','')}")

    if fa != fb:
        print(f"\n  ✗ PROTOCOL MISMATCH — these runs are not comparable.")
        print(f"      {A['name']}: {A['meta'].get('protocol_detail','?')}")
        print(f"      {B['name']}: {B['meta'].get('protocol_detail','?')}")
        if not a.force:
            print(f"\n  Refusing. Two blades measured under different settings "
                  f"are not two\n  data points. Re-run one of them, or pass "
                  f"--force and label the result\n  as not comparable "
                  f"wherever it appears.\n")
            return 2
        print(f"  --force given: continuing, and the result is NOT a blade "
              f"comparison.\n")

    col_a, col_b, why = pick_column(A, B)
    print(f"  power column: {col_a} vs {col_b}  —  {why}")

    pts = paired(A, B, col_a, col_b)
    if len(pts) < 4:
        raise SystemExit(f"only {len(pts)} matched points — nothing to say")
    dirty = [p for p in pts if not p["clean"]]

    print(f"\n  {'fan rpm':>8} {'m/s':>7} {A['name']:>11} {B['name']:>11} "
          f"{'change':>9}")
    print(f"  {'-'*8} {'-'*7} {'-'*11} {'-'*11} {'-'*9}")
    for p in pts:
        flag = "" if p["clean"] else "  ⚠"
        print(f"  {p['rpm']:>8} {p['v']:>7.1f} {p['pa']:>11.4f} "
              f"{p['pb']:>11.4f} {100*(p['ratio']-1):>+8.1f}%{flag}")

    r = analyse(pts)
    lo = 100 * (r["level"] - 1.96 * r["se_level"])
    hi = 100 * (r["level"] + 1.96 * r["se_level"])
    sig = lo > 0 or hi < 0

    print(f"\n  ── paired analysis, {r['n']} matched points ──\n")
    print(f"  LEVEL   {100*r['level']:+.2f}%   95% CI [{lo:+.2f}%, {hi:+.2f}%]"
          f"   {'← resolved' if sig else '← NOT resolved'}")
    print(f"  Δn      {r['dn']:+.3f}    ± {1.96*r['se_dn']:.3f}")
    print(f"  scatter {r['resid_pct']:.2f}% about the fit")

    print(f"\n  The LEVEL is the headline. A uniform power change gives "
          f"Δn = 0.000\n  exactly, so the exponent is blind to the most likely "
          f"outcome.")
    if not sig:
        print(f"\n  No resolvable difference. That is a real engineering "
              f"result — it says\n  the variable under test does not move this "
              f"measurement by more than\n  ±{max(abs(lo),abs(hi)):.1f}% on "
              f"this rig.")
    if dirty:
        print(f"\n  ⚠ {len(dirty)} point(s) not clean: "
              f"{', '.join(str(p['rpm']) for p in dirty)} rpm — treat as "
              f"lower bounds")
    print(f"\n  Remember what this cannot separate: without rotor speed this "
          f"is\n  electrical power, so a blade that captures more energy but "
          f"spins slower\n  can read LOWER. See docs/07_blade_campaign.md.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
