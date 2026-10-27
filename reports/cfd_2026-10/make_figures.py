"""Figures for the CFD summary (cfd_summary.tex), from the verified analysis tables.

    python3 reports/cfd_2026-10/make_figures.py

Inputs (all computed on 19 Oct 2026, cfd/analysis/2026-10-15):
- cfd/stage2/results/stage2_polars.csv: single-blade forces, SST with rough wall functions,
  23 m/s, maxCo 2.5, Ks 0 / 100 / 400 um, alpha 0 / 90 / 180.
- cfd/analysis/2026-10-15/out/rotor_roughness.csv and rotor_roughness_sectors.csv: rotor torque,
  assembly A, 23 m/s, revolutions 6-50 averaged, Ks 0 / 100 / 400 um (same rough wall function).
"""
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAVY, GOLD, GREY, INK2 = "#002147", "#B8860B", "#9A9890", "#52514E"
plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
                     "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.edgecolor": INK2, "axes.labelcolor": "#0B0B0B", "xtick.color": INK2,
                     "ytick.color": INK2, "axes.titleweight": "bold", "axes.titlesize": 10.5})


def save(fig, name):
    for ext in ("pdf", "png"):
        fig.savefig(HERE / f"{name}.{ext}", dpi=220, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- figure 1: single blade
rows = {r["name"]: r for r in csv.DictReader(open(REPO / "cfd/stage2/results/stage2_polars.csv"))}
orient = [("000.0", "Cup facing\nthe wind (0°)"), ("090.0", "Edge-on\n(90°)"), ("180.0", "Back facing\nthe wind (180°)")]
def val(a, ks, col):
    return float(rows[f"a{a}_U23.0_SST_wf_Ks{ks}_Tu1.0_Co2.5n2"][col])
drag = {ks: [100 * (val(a, ks, "Cd_mean") / val(a, "0", "Cd_mean") - 1) for a, _ in orient] for ks in ("100", "400")}
lift = {ks: [100 * (abs(val(a, ks, "Cl_mean")) / abs(val(a, "0", "Cl_mean")) - 1) for a, _ in orient] for ks in ("100", "400")}

fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.9), sharey=True)
x = range(len(orient))
for ax, data, title in ((axes[0], drag, "Drag"), (axes[1], lift, "Lift (size)")):
    w = 0.36
    b1 = ax.bar([i - w / 2 for i in x], data["100"], w, color=GREY, label="100 µm")
    b2 = ax.bar([i + w / 2 for i in x], data["400"], w, color=NAVY, label="400 µm")
    for bars in (b1, b2):
        for b in bars:
            h = b.get_height()
            ax.annotate(f"{h:+.0f}%", (b.get_x() + b.get_width() / 2, h), xytext=(0, 3 if h >= 0 else -11),
                        textcoords="offset points", ha="center", fontsize=8, color=INK2)
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_xticks(list(x), [o[1] for o in orient], fontsize=8.5)
    ax.set_title(title, loc="left")
    ax.set_ylim(-38, 80)
axes[0].set_ylabel("Change from smooth (%)")
axes[1].legend(frameon=False, fontsize=8.5, loc="upper right")
fig.tight_layout()
save(fig, "fig1_single_blade")

# ---------------------------------------------------------------- figure 2: rotor torque
rr = list(csv.DictReader(open(REPO / "cfd/analysis/2026-10-15/out/rotor_roughness.csv")))
def pair(lam, a):
    return next(r for r in rr if abs(float(r["lam"]) - lam) < 1e-9 and r["a"] == a and r["b"] == "Ks0")
fig, ax = plt.subplots(figsize=(5.2, 3.0))
w = 0.26
for j, lam in enumerate((0.10, 0.12)):
    smooth = float(pair(lam, "Ks100")["CQ_b"])
    vals = [smooth, float(pair(lam, "Ks100")["CQ_a"]), float(pair(lam, "Ks400")["CQ_a"])]
    errs = [None, float(pair(lam, "Ks100")["two_u"]), float(pair(lam, "Ks400")["two_u"])]
    for k, (v, c, lab) in enumerate(zip(vals, (GREY, "#C9C8C2", NAVY), ("Smooth", "100 µm", "400 µm"))):
        xpos = j + (k - 1) * w
        ax.bar(xpos, v, w, color=c, edgecolor=INK2 if k == 1 else c, lw=0.6, label=lab if j == 0 else None)
        if k:
            pct = 100 * (v / smooth - 1)
            ax.errorbar(xpos, v, yerr=errs[k], color="#0B0B0B", lw=0.9, capsize=3)
            ax.annotate(f"{pct:+.0f}%", (xpos, v + errs[k]), xytext=(0, 3), textcoords="offset points",
                        ha="center", fontsize=8.5, color=INK2 if k == 1 else NAVY, fontweight="bold" if k == 2 else None)
ax.set_xticks([0, 1], ["Tip-speed ratio 0.10", "Tip-speed ratio 0.12"])
ax.set_ylabel("Rotor torque coefficient")
ax.set_ylim(0, 0.03)
ax.legend(frameon=False, fontsize=8.5, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.13))
fig.tight_layout()
save(fig, "fig2_rotor_torque")

# ---------------------------------------------------------------- figure 3: where the gain comes from
ss = [r for r in csv.DictReader(open(REPO / "cfd/analysis/2026-10-15/out/rotor_roughness_sectors.csv"))
      if abs(float(r["lam"]) - 0.10) < 1e-9 and r["a"] == "Ks400" and r["b"] == "Ks0"]
label = {"advancing, edge-on (tip A first)": "Edge-on, moving with the wind",
         "downwind, cup to the wind": "Cup facing the wind",
         "upwind, convex side to the wind": "Back facing the wind",
         "returning, edge-on (curl first)": "Edge-on, moving against the wind",
         "the four 30° gaps between": "Positions in between"}
order = ["advancing, edge-on (tip A first)", "downwind, cup to the wind", "upwind, convex side to the wind",
         "returning, edge-on (curl first)", "the four 30° gaps between"]
smooth010 = float(pair(0.10, "Ks400")["CQ_b"])      # smooth rotor torque at lambda 0.10
d = {r["sector"]: (100 * float(r["d"]) / smooth010, 100 * float(r["two_u"]) / smooth010) for r in ss}
fig, ax = plt.subplots(figsize=(6.0, 2.6))
ys = list(range(len(order)))[::-1]
for y, key in zip(ys, order):
    v, e = d[key]
    ax.barh(y, v, color=NAVY if v > 0 else GREY, height=0.6)
    ax.errorbar(v, y, xerr=e, color="#0B0B0B", lw=0.9, capsize=3)
ax.set_yticks(ys, [label[k] for k in order])
ax.axvline(0, color=INK2, lw=0.8)
net = sum(v for v, _ in d.values())
ax.set_xlabel(f"Change in torque, 400 µm against smooth, as % of the smooth rotor's torque (sum {net:+.0f}%)")
ax.set_xlim(-62, 62)
for y, key in zip(ys, order):
    v, e = d[key]
    ax.annotate(f"{v:+.0f}%", (v + (e if v > 0 else -e), y), xytext=(4 if v > 0 else -4, 0), textcoords="offset points",
                ha="left" if v > 0 else "right", va="center", fontsize=8.5, color=INK2)
fig.tight_layout()
save(fig, "fig3_where_in_the_turn")

print("drag %", {k: [round(v, 1) for v in vs] for k, vs in drag.items()})
print("lift %", {k: [round(v, 1) for v in vs] for k, vs in lift.items()})
print("sectors %", {label[k]: round(d[k][0], 1) for k in order}, "sum", round(net, 1))
