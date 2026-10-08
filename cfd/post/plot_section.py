#!/usr/bin/env python3
"""Plot Stage 1 section polars from cfd/section2d/results/section_polars.csv.

    python3 cfd/post/plot_section.py                      # -> cfd/section2d/results/section_polars.png
    python3 cfd/post/plot_section.py --level medium --out polars_medium.png
    python3 cfd/post/plot_section.py --csv other.csv

Cd, Cl and Cm (about the section centroid, counter-clockwise positive) against
alpha, one line per (U, model, level, Tu, time-step setting), with +-1 standard
deviation over the averaging window as error bars, and the Strouhal number where
the lift spectrum has a clear peak (St_peak_frac >= 0.3). alpha = 0 is the
concave side facing the wind (cfd/section2d/README.md). Reference values for a
semicircular shell (about 2.3 concave side to the wind, 1.2 convex side) are
marked for orientation only: they are not measurements of this blade.
"""
import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
CSV = HERE.parent / "section2d" / "results" / "section_polars.csv"


def load(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=str(CSV))
    ap.add_argument("--out")
    ap.add_argument("--level", help="only this mesh level")
    ap.add_argument("--model", help="only this model (SST or LM)")
    a = ap.parse_args()
    rows = load(a.csv)
    if a.level:
        rows = [r for r in rows if r["level"] == a.level]
    if a.model:
        rows = [r for r in rows if r["model"] == a.model]
    if not rows:
        raise SystemExit(f"no rows to plot in {a.csv}")
    groups = defaultdict(list)
    for r in rows:
        key = (float(r["U_ms"]), r["model"], r["level"], float(r["Tu_body_pct"]), r["maxCo"], r["nOuter"])
        groups[key].append(r)
    fig, axs = plt.subplots(2, 2, figsize=(11, 8), sharex=True)
    ax_cd, ax_cl, ax_cm, ax_st = axs.flat
    for key in sorted(groups):
        g = sorted(groups[key], key=lambda r: float(r["alpha_deg"]))
        al = np.array([float(r["alpha_deg"]) for r in g])
        lab = f"{key[0]:g} m/s {key[1]} {key[2]} Tu {key[3]:g}%" + ("" if float(key[4]) == 5 else f" Co{float(key[4]):g}")
        style = dict(marker="o", ms=4, capsize=2, lw=1.2, label=lab)
        for ax, m, s in ((ax_cd, "Cd_mean", "Cd_std"), (ax_cl, "Cl_mean", "Cl_std"), (ax_cm, "Cm_mean", "Cm_std")):
            ax.errorbar(al, [float(r[m]) for r in g], yerr=[float(r[s]) for r in g], **style)
        st = np.array([float(r["St"]) if float(r["St_peak_frac"] or 0) >= 0.3 else np.nan for r in g])
        ax_st.plot(al, st, marker="o", ms=4, lw=1.2, label=lab)
    ax_cd.axhline(2.3, color="0.6", ls=":", lw=1)
    ax_cd.axhline(1.2, color="0.6", ls=":", lw=1)
    ax_cd.text(2, 2.33, "semicircular shell, concave to wind (lit.)", fontsize=7, color="0.4")
    ax_cd.text(2, 1.23, "convex to wind (lit.)", fontsize=7, color="0.4")
    for ax, t in ((ax_cd, "Cd (mean, +-1 std)"), (ax_cl, "Cl (mean, +-1 std)"),
                  (ax_cm, "Cm about centroid, CCW + (mean, +-1 std)"), (ax_st, "St = f c / U from Cl")):
        ax.set_title(t, fontsize=10)
        ax.grid(alpha=0.3)
        ax.axhline(0, color="k", lw=0.5)
    al_all = [float(r["alpha_deg"]) for r in rows]
    hi = 180 if max(al_all) <= 180 else 360
    for ax in (ax_cm, ax_st):
        ax.set_xlabel("alpha (deg); 0 = concave side to the wind")
        ax.set_xticks(np.arange(0, hi + 1, 15 if hi == 180 else 30))
        ax.set_xlim(-5, hi + 5)
    ax_cd.legend(fontsize=7)
    fig.suptitle("Blade v1 section, 2D URANS (c_ref = 48 mm, coefficients per unit span)", fontsize=11)
    fig.tight_layout()
    out = Path(a.out) if a.out else Path(a.csv).with_suffix(".png")
    fig.savefig(out, dpi=130)
    print(out)


if __name__ == "__main__":
    main()
