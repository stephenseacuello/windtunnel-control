#!/usr/bin/env python3
"""Stage 3 rotor: CFD C_P(lambda) against the rig, and static C_Q(theta).

    python3 cfd/post/plot_rotor_cp.py                       # U = 23 m/s, Plain rotor, writes cfd/rotor2d/results/
    python3 cfd/post/plot_rotor_cp.py --U 10.2 --rotor "FS 0.10"

Inputs
  CFD : cfd/rotor2d/results/rotor_cp.csv and rotor_static.csv (cfd/rotor2d/queue.py --csv)
  Rig : reports/roughness_2026-09/build/tacho/derived/rotor_speed_by_dwell.csv (lambda and
        cp_el at every load step; cp_gen_in recomputed from p_gen_in_w = EMF x current) and
        reports/roughness_2026-09/build/derived/rotor_speed_by_run.csv (light-load lambda).
The rig values are electrical (C_P,el) or generator-input (C_P,gen-in, still excluding
bearing friction), so the CFD's aerodynamic C_P is compared for shape and lambda
locations (peak and zero torque), not magnitude: panel (a) uses two axes, panel (b)
normalises each curve by its own maximum.
Outputs: rotor_cp_vs_rig_U<U>.png, rotor_static_CQ_U<U>.png and rotor_cp_compare_U<U>.json
(lambda at peak C_P and zero-torque lambda for CFD and rig).
"""
import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np

CFD = Path(__file__).resolve().parents[1]
REPO = CFD.parent
RES = CFD / "rotor2d" / "results"
DWELL = REPO / "reports/roughness_2026-09/build/tacho/derived/rotor_speed_by_dwell.csv"
BYRUN = REPO / "reports/roughness_2026-09/build/derived/rotor_speed_by_run.csv"
RHO_STD = 1.204
AREA = 2 * 0.1016 * 0.2451          # 2RH, the reports' swept area (m^2)


# Production settings (cfd/rotor2d/run_case.py DEFAULTS and LT_DEFAULTS). A case that differs in
# any of them is a variant (e.g. priorityC.txt's maxco=2 time-step check at 23 m/s, lambda 0.15).
TU_DEFAULT, MAXCO_DEFAULT, NOUTER_DEFAULT = 1.0, 4.0, 2
LT_DEFAULTS = {"control": 1.0e-3, "precompensate": 0.01}


def _float(r, k):
    try:
        return float(r.get(k))
    except (TypeError, ValueError):
        return None


def variant_tag(r):
    """() for a production case (decay control, Tu 1 % at the rotor, the decay mode's default length
    scale, maxCo 4, 2 outer correctors), else what differs, e.g. ('precompensate',) or ('Co2n2',):
    a variant gets its own curve and static mean and never enters a production one (a second point at
    the same lambda would also corrupt the parabola fit for the peak). An empty freestream_decay
    column (results.json from before 8 Oct) had no decay control."""
    d = r.get("freestream_decay") or "precompensate"
    tag = () if d == "control" else (d,)
    tu = _float(r, "Tu_rotor_pct")
    if tu is not None and abs(tu - TU_DEFAULT) > 1e-6:
        tag += (f"Tu{tu:g}",)
    lt = _float(r, "lt_m")
    if lt is not None and d in LT_DEFAULTS and abs(lt - LT_DEFAULTS[d]) > 1e-9:
        tag += (f"lt{lt:g}",)
    co, no = _float(r, "maxCo"), _float(r, "nOuter")
    if (co is not None and abs(co - MAXCO_DEFAULT) > 1e-9) or (no is not None and abs(no - NOUTER_DEFAULT) > 1e-9):
        tag += (f"Co{co:g}n{no:g}",)
    return tag


def read_csv(p):
    if not Path(p).exists():
        return []
    with open(p) as fh:
        return list(csv.DictReader(fh))


def rig_curves(U, rotor):
    rows = [r for r in read_csv(DWELL) if r["rotor"] == rotor and r["speed_ok"] == "True"]
    if not rows:
        return {}, None
    winds = sorted({float(r["wind_mps"]) for r in rows})
    w = min(winds, key=lambda v: abs(v - U))
    out = {}
    for r in rows:
        if abs(float(r["wind_mps"]) - w) > 1e-6:
            continue
        lam = float(r["tip_speed_ratio"])
        v = float(r["wind_mps"])
        cpg = float(r["p_gen_in_w"]) / (0.5 * RHO_STD * AREA * v ** 3)
        out.setdefault(r["run"], []).append((lam, float(r["cp_el"]), cpg))
    for k in out:
        out[k] = np.array(sorted(out[k]))
    return out, w


def rig_light_load(U, rotor):
    lams = [float(r["tip_speed_ratio"]) for r in read_csv(BYRUN)
            if r["rotor"] == rotor and r["light_load"] == "1" and r["tip_speed_ratio"] and abs(float(r["wind_mps"]) - U) < 1.1]
    return lams


def peak_of(lam, cp):
    i = int(np.argmax(cp))
    if 0 < i < len(lam) - 1:                     # parabola through the top three points
        a, b, c = np.polyfit(lam[i - 1:i + 2], cp[i - 1:i + 2], 2)
        if a < 0:
            return float(-b / (2 * a)), float(c - b * b / (4 * a))
    return float(lam[i]), float(cp[i])


def zero_torque(lam, cq):
    s = np.flatnonzero(np.sign(cq[:-1]) != np.sign(cq[1:]))
    if not s.size:
        return None
    i = s[-1]
    return float(lam[i] - cq[i] * (lam[i + 1] - lam[i]) / (cq[i + 1] - cq[i]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--U", type=float, default=23.0)
    ap.add_argument("--rotor", default="Plain", help="rig rotor: Plain, 'FS 0.05', 'FS 0.10', 'FS 0.20'")
    ap.add_argument("--level", default="medium")
    a = ap.parse_args()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cfd = [r for r in read_csv(RES / "rotor_cp.csv") if abs(float(r["U_ms"]) - a.U) < 0.05 and r["level"] == a.level]
    rig, w = rig_curves(a.U, a.rotor)
    summary = dict(U_cfd=a.U, U_rig=w, rotor=a.rotor, level=a.level, cfd={}, rig={})
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(12, 4.8))
    ax2 = ax.twinx()
    for j, (k, d) in enumerate(sorted(rig.items())):
        ax2.plot(d[:, 0], d[:, 1], "o", ms=3, color="0.45", mfc="none", label="rig C_P,el (both runs)" if j == 0 else None)
        ax2.plot(d[:, 0], d[:, 2], "s", ms=2.5, color="0.7", label="rig C_P,gen-in" if j == 0 else None)
        lp, cp = peak_of(d[:, 0], d[:, 1])
        lg, cg = peak_of(d[:, 0], d[:, 2])
        summary["rig"][f"run{k}"] = dict(lam_peak_cp_el=lp, cp_el_peak=cp, lam_peak_cp_gen_in=lg, cp_gen_in_peak=cg,
                                         lam_min_loaded=float(d[:, 0].min()), lam_max_loaded=float(d[:, 0].max()))
        bx.plot(d[:, 0], d[:, 1] / d[:, 1].max(), "o", ms=3, color="0.45", mfc="none",
                label="rig C_P,el / max" if j == 0 else None)
    ll = rig_light_load(w or a.U, a.rotor)
    if ll:
        summary["rig"]["lam_light_load"] = ll
        for x in ll:
            bx.axvline(x, color="0.6", ls=":", lw=1)
    groups = {}
    for r in cfd:
        groups.setdefault((r["hypothesis"], r["model"], r["wall"], r["sense"]) + variant_tag(r), []).append(r)
    for i, (key, rows) in enumerate(sorted(groups.items())):
        rows.sort(key=lambda r: float(r["lam"]))
        lam = np.array([float(r["lam"]) for r in rows])
        cp = np.array([float(r["CP_mean"]) for r in rows])
        cq = np.array([float(r["CQ_mean"]) for r in rows])
        lab = f"CFD hyp {key[0]} ({', '.join(key[1:])})"
        ax.plot(lam, cp, "-o", color=f"C{i}", label=lab)
        if cp.max() > 0:
            bx.plot(lam, cp / cp.max(), "-o", color=f"C{i}", label=lab + " / max")
        lp, cpp = peak_of(lam, cp) if len(lam) >= 3 else (float(lam[np.argmax(cp)]), float(cp.max()))
        summary["cfd"][" ".join(key)] = dict(lam=lam.tolist(), CP=cp.tolist(), CQ=cq.tolist(), lam_peak=lp, CP_peak=cpp,
                                            lam_zero_torque=zero_torque(lam, cq),
                                            complete_windows=[r["avg_window_complete"] for r in rows])
    ax.axhline(0, color="k", lw=0.5)
    ax.set_xlabel("tip-speed ratio lambda (on R = 101.6 mm)")
    ax.set_ylabel("CFD C_P (2D, aerodynamic, per unit span on 2R)")
    ax2.set_ylabel("rig C_P (electrical / generator input)")
    ax.set_title(f"(a) C_P against lambda, CFD {a.U:g} m/s, rig {a.rotor} {w if w else float('nan'):.1f} m/s", fontsize=9)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=7, loc="upper right")
    bx.axhline(0, color="k", lw=0.5)
    bx.set_ylim(-0.6, 1.15)
    bx.set_xlabel("lambda")
    bx.set_ylabel("C_P / own maximum")
    bx.set_title("(b) shapes; dotted: rig light-load lambda (near zero electrical torque)", fontsize=9)
    bx.legend(fontsize=7)
    for x in (ax, bx):
        x.grid(True, lw=0.3)
    fig.tight_layout()
    RES.mkdir(parents=True, exist_ok=True)
    fig.savefig(RES / f"rotor_cp_vs_rig_U{a.U:g}.png", dpi=140)
    plt.close(fig)

    st = [r for r in read_csv(RES / "rotor_static.csv") if abs(float(r["U_ms"]) - a.U) < 0.05]
    if st:
        fig, ax = plt.subplots(figsize=(6.5, 4.2))
        gs = {}
        for r in st:
            gs.setdefault((r["hypothesis"], r["model"], r["level"], r["sense"]) + variant_tag(r), []).append(r)
        for i, (key, rows) in enumerate(sorted(gs.items())):
            rows.sort(key=lambda r: float(r["theta_deg"]))
            th = np.array([float(r["theta_deg"]) for r in rows])
            cq = np.array([float(r["CQ_mean"]) for r in rows])
            sd = np.array([float(r["CQ_std"]) for r in rows])
            ax.errorbar(th, cq, yerr=sd, fmt="-o", ms=3, color=f"C{i}", capsize=2, label=f"hyp {key[0]} ({', '.join(key[1:])})")
            # 3-fold periodic mean (trapezoid on 0..120 with 120 = 0; on a uniform grid this
            # is the plain mean of the azimuths). Its standard error from the per-case batch-
            # means errors (CQ_sem), treating the azimuths as independent. The sign gives the
            # self-starting direction: the azimuth grid is the same set of blade positions in
            # either sense, so the mean in the opposite sense is the negative of this one.
            if th.size >= 3:
                thc = np.r_[th, 120.0] if th[0] == 0 and th[-1] < 120 else th
                cqc = np.r_[cq, cq[0]] if thc.size > th.size else cq
                mean = float(np.trapezoid(cqc, thc) / (thc[-1] - thc[0]))
                sems = [float(r["CQ_sem"]) for r in rows if r.get("CQ_sem") not in (None, "")]
                sem = float(np.sqrt(np.sum(np.square(sems))) / len(rows)) if len(sems) == len(rows) else None
                if sem is None:
                    verdict = "no standard error (rebuild the CSV with queue.py --csv)"
                elif mean > 2 * sem:
                    verdict = f"positive: starts in the assumed sense ({key[3]})"
                elif mean < -2 * sem:
                    verdict = f"negative: starts against the assumed sense ({key[3]}); rerun rotating cases with sense reversed"
                else:
                    verdict = "within 2 standard errors of zero: sense not determined by the static torque"
                summary.setdefault("static", {})[" ".join(key)] = dict(
                    theta=th.tolist(), CQ=cq.tolist(), CQ_mean_over_theta=mean, CQ_mean_over_theta_sem=sem,
                    n_theta=int(th.size), self_start=verdict)
        ax.axhline(0, color="k", lw=0.5)
        ax.set_xlabel("azimuth theta of blade 1 (deg; 0 = upwind, increasing with rotation)")
        ax.set_ylabel("static C_Q (positive drives the assumed sense)")
        ax.set_title(f"Static torque, {a.U:g} m/s (error bars: unsteady s.d.)", fontsize=9)
        ax.grid(True, lw=0.3)
        ax.legend(fontsize=7)
        fig.tight_layout()
        fig.savefig(RES / f"rotor_static_CQ_U{a.U:g}.png", dpi=140)
        plt.close(fig)
    (RES / f"rotor_cp_compare_U{a.U:g}.json").write_text(json.dumps(summary, indent=1, default=float))
    print(json.dumps(summary, indent=1, default=float)[:3000])


if __name__ == "__main__":
    main()
