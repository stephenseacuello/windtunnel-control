#!/usr/bin/env python3
"""T3A check: skin friction and free-stream turbulence decay against the
ERCOFTAC T3A data shipped with the tutorial (validation/exptData/T3A.dat).

Replaces the tutorial's gnuplot script (validation/plot) and uses the same
conversions: plate leading edge at x = 0.04 m, U = 5.4 m/s, cf = -tau_x/(0.5 U^2),
Re_x with nu = 1.5e-5 (simulation) and 1.51e-5 (experiment), u' = sqrt(2k/3)/U.

Reads the latest time of this case: the plate-face wall shear stress (needs
'postProcess -func writeCellCentres -latestTime', which run.sh does) and the
tutorial's two sampled lines. Writes result.png, result.md, cf_plate.csv and
metrics.json here.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "post"))
from foamio import latest_time, read_patch_field, read_xy  # noqa: E402

U, X_LE, NU_SIM, NU_EXP = 5.4, 0.04, 1.5e-5, 1.51e-5
Y_FLAT = 0.00075            # the plate's flat face; faces below it are the rounded nose


def parabola_vertex(x, y, i):
    """Vertex of the parabola through points i-1, i, i+1 (equal spacing)."""
    h = x[i + 1] - x[i]
    den = y[i - 1] - 2 * y[i] + y[i + 1]
    return x[i] - h * (y[i + 1] - y[i - 1]) / (2 * den)


def crossing(x, y, level):
    j = np.where((y[:-1] < level) & (y[1:] >= level))[0][0]
    return x[j] + (level - y[j]) * (x[j + 1] - x[j]) / (y[j + 1] - y[j])


def transition(x, cf):
    """onset = cf minimum, peak = cf maximum after it, mid = 50 % rise between them."""
    lo = (x > 0.05) & (x < 1.5)
    i0 = np.flatnonzero(lo)[np.argmin(cf[lo])]
    i1 = i0 + np.argmax(cf[i0:np.flatnonzero(x < 1.5)[-1]])
    mid = crossing(x[i0:i1 + 1], cf[i0:i1 + 1], 0.5 * (cf[i0] + cf[i1]))
    return {"onset_x_m": float(x[i0]), "onset_cf": float(cf[i0]), "peak_x_m": float(x[i1]),
            "peak_cf": float(cf[i1]), "mid_x_m": float(mid)}


def plate_cf(case):
    """cf on the flat plate faces at the latest time of `case`."""
    t = latest_time(case)
    C = read_patch_field(case, t, "C", "plate")
    tau = read_patch_field(case, t, "wallShearStress", "plate")
    flat = C[:, 1] > Y_FLAT - 1e-7
    x = C[flat, 0] - X_LE
    o = np.argsort(x)
    return t, x[o], (-tau[flat, 0] / (0.5 * U**2))[o]


def solver_log(case):
    log = (Path(case) / "log.simpleFoam").read_text()
    et = re.findall(r"ExecutionTime = ([\d.]+) s\s+ClockTime = ([\d.]+) s", log)
    np_ = re.search(r"nProcs\s*:\s*(\d+)", log)
    conv = re.search(r"converged in (\d+) iterations", log)
    return {"iterations": len(re.findall(r"^Time = ", log, re.M)),
            "converged_by_residualControl": bool(conv),
            "execution_time_s": float(et[-1][0]), "clock_time_s": float(et[-1][1]),
            "mpi_ranks": int(np_.group(1)) if np_ else 1}


CHECKS = {"T3A_np4": "same case, 4 MPI ranks (scotch)",
          "T3A_tight": "residualControl 1e-12: all 1000 iterations"}


def main():
    t, xs, cfs = plate_cf(HERE)
    np.savetxt(HERE / "cf_plate.csv", np.c_[xs, xs * U / NU_SIM, cfs], delimiter=",",
               fmt="%.6e", header=f"x_from_LE_m,Re_x,cf  (plate faces, time {t})", comments="")

    line = read_xy(HERE / "postProcessing" / "wallShearStressGraph" / t / "line_wallShearStress.xy")
    xl, cfl = line[:, 0] - X_LE, -line[:, 1] / (0.5 * U**2)
    kline = read_xy(HERE / "postProcessing" / "kGraph" / t / "line_k.xy")

    ex = read_xy(HERE / "validation" / "exptData" / "T3A.dat")
    xe, cfe, tue = ex[:, 0] / 1000, ex[:, 1], ex[:, 2] / 100

    # transition positions
    sim = transition(xs, cfs)
    sim_line = transition(xl, cfl)
    i_min = int(np.argmin(cfe[(xe < 1.0)]))
    i_max = i_min + int(np.argmax(cfe[i_min:]))
    exp = {"onset_x_m_station": float(xe[i_min]), "onset_x_m_parabola": float(parabola_vertex(xe, cfe, i_min)),
           "onset_cf": float(cfe[i_min]),
           "peak_x_m_station": float(xe[i_max]), "peak_x_m_parabola": float(parabola_vertex(xe, cfe, i_max)),
           "peak_cf": float(cfe[i_max]),
           "mid_x_m": float(crossing(xe[i_min:i_max + 1], cfe[i_min:i_max + 1], 0.5 * (cfe[i_min] + cfe[i_max]))),
           "station_spacing_m": 0.1}
    d_on = sim["onset_x_m"] - exp["onset_x_m_parabola"]
    d_mid = sim["mid_x_m"] - exp["mid_x_m"]
    d_pk = sim["peak_x_m"] - exp["peak_x_m_parabola"]

    # cf at the measurement stations
    cf_at = np.interp(xe, xs, cfs)
    rel = cf_at / cfe - 1
    lam, turb = xe < 0.40, xe > 0.90
    tu_at = np.interp(xe, kline[:, 0] - X_LE, np.sqrt(2 / 3 * kline[:, 1]) / U)

    tol = 0.05   # half the station spacing
    match_on, match_mid = abs(d_on) <= tol, abs(d_mid) <= tol
    verdict = "MATCHES" if (match_on and match_mid) else "DOES NOT MATCH"

    metrics = {"time": t, "n_plate_faces_used": int(len(xs)), "simulation": sim,
               "simulation_tutorial_sample_line": sim_line, "experiment": exp,
               "delta_m": {"onset": d_on, "mid": d_mid, "peak": d_pk},
               "Re_x": {"sim_onset": sim["onset_x_m"] * U / NU_SIM, "exp_onset": exp["onset_x_m_parabola"] * U / NU_EXP,
                        "sim_mid": sim["mid_x_m"] * U / NU_SIM, "exp_mid": exp["mid_x_m"] * U / NU_EXP},
               "cf_rel_error_at_stations": {"x_m": xe.tolist(), "rel": rel.tolist(),
                                            "laminar_x_lt_0.4_max_abs": float(np.abs(rel[lam]).max()),
                                            "turbulent_x_gt_0.9_max_abs": float(np.abs(rel[turb]).max()),
                                            "turbulent_x_gt_0.9_mean": float(rel[turb].mean())},
               "Tu_rel_error_at_stations_max_abs": float(np.abs(tu_at / tue - 1).max()),
               "criterion": "onset (cf minimum) and 50 % point of the cf rise both within +-0.05 m "
                            "(half the 0.1 m station spacing) of the experiment",
               "verdict": verdict,
               "run": solver_log(HERE), "checks": {}}
    for name, what in CHECKS.items():
        case = HERE.parents[1] / "runs" / name
        try:
            tc, xc, cfc = plate_cf(case)
        except (FileNotFoundError, KeyError, ValueError):
            continue
        cfc_i = np.interp(xs, xc, cfc)
        metrics["checks"][name] = {"what": what, "time": tc, "transition": transition(xc, cfc),
                                   "max_rel_cf_change_vs_serial": float(np.abs(cfc_i / cfs - 1).max()),
                                   "run": solver_log(case)}
    (HERE / "metrics.json").write_text(json.dumps(metrics, indent=1) + "\n")
    plot(xs, cfs, xl, cfl, kline, xe, cfe, tue, sim, exp)
    write_md(metrics)
    print(json.dumps({k: metrics[k] for k in ("simulation", "experiment", "delta_m", "verdict")}, indent=1))


def plot(xs, cfs, xl, cfl, kline, xe, cfe, tue, sim, exp):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    BLUE, INK, INK2, GRID, SURF, GREY = "#2a78d6", "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb", "#9a9890"
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                         "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True,
                         "grid.color": GRID, "grid.linewidth": 0.6, "figure.facecolor": SURF,
                         "axes.facecolor": SURF, "legend.frameon": False})
    fig, (a, b) = plt.subplots(1, 2, figsize=(12, 4.6), gridspec_kw={"width_ratios": [1.35, 1]})
    Rs, Re = xs * U / NU_SIM, xe * U / NU_EXP
    r = np.linspace(2e3, 6e5, 400)
    a.plot(r, 0.664 / np.sqrt(r), "--", color=GREY, lw=1.0, label="laminar, Blasius 0.664 Re$_x^{-1/2}$")
    a.plot(r, 0.0592 * r**-0.2, ":", color=GREY, lw=1.2, label="turbulent, 0.0592 Re$_x^{-1/5}$")
    a.plot(Rs, cfs, color=BLUE, lw=2.0, label="kOmegaSSTLM, plate faces (this run)")
    a.plot(Re, cfe, "o", ms=6, mfc=SURF, mec=INK, mew=1.4, label="experiment (ERCOFTAC T3A)")
    a.annotate(f"sim onset x = {sim['onset_x_m']*1e3:.0f} mm", (sim["onset_x_m"] * U / NU_SIM, sim["onset_cf"]),
               xytext=(0, -26), textcoords="offset points", ha="center", fontsize=7.5, color=INK2,
               arrowprops=dict(arrowstyle="-", color=INK2, lw=0.6))
    a.annotate(f"expt min x = {exp['onset_x_m_parabola']*1e3:.0f} mm\n(parabola through stations)",
               (exp["onset_x_m_parabola"] * U / NU_EXP, exp["onset_cf"]), xytext=(18, -40),
               textcoords="offset points", ha="left", fontsize=7.5, color=INK2,
               arrowprops=dict(arrowstyle="-", color=INK2, lw=0.6))
    a.set_xlim(0, 6e5)
    a.set_ylim(0, 0.01)
    a.set_xlabel("Re$_x$")
    a.set_ylabel("c$_f$")
    a.set_title("(a) Skin friction along the plate", loc="left", fontsize=10, color=INK)
    a.legend(loc="upper right", fontsize=7.5)

    b.plot(kline[:, 0] - X_LE, np.sqrt(2 / 3 * kline[:, 1]) / U * 100, color=BLUE, lw=2.0,
           label="kOmegaSSTLM, y = 0.05 m")
    b.plot(xe, tue * 100, "o", ms=6, mfc=SURF, mec=INK, mew=1.4, label="experiment")
    b.set_xlim(0, 1.5)
    b.set_ylim(0, 5)
    b.set_xlabel("x from leading edge, m")
    b.set_ylabel("Tu = u'/U, %")
    b.set_title("(b) Free-stream turbulence decay", loc="left", fontsize=10, color=INK)
    b.legend(loc="upper right", fontsize=7.5)
    fig.tight_layout()
    fig.savefig(HERE / "result.png", dpi=150)
    plt.close(fig)


def write_md(m):
    s, e, d = m["simulation"], m["experiment"], m["delta_m"]
    timing = ("\n".join("- " + ln for ln in (HERE / "timing.txt").read_text().strip().splitlines())
              if (HERE / "timing.txt").exists() else "- timing not recorded (run run.sh)")
    cfr = m["cf_rel_error_at_stations"]
    checks, conv = "", ""
    if m["checks"]:
        mx = max(c["max_rel_cf_change_vs_serial"] for c in m["checks"].values())
        dx = max(abs(c["transition"][k] - s[k]) for c in m["checks"].values()
                 for k in ("onset_x_m", "mid_x_m", "peak_x_m"))
        conv = (f"\nThe offset is not a convergence or parallel artefact: running all 1000 iterations with "
                f"residualControl 1e-12, or on 4 MPI ranks, moves c_f by at most {mx*100:.2f} % and the "
                f"transition positions by at most {dx*1e3:.2f} mm (table below).\n")
    if m["checks"]:
        checks = ("\nChecks (cfd/runs/, from run_checks.sh):\n\n| Case | Ranks | Iterations | Solver clock time | Onset / 50 % / end, mm | Max c_f change vs serial |\n"
                  "|---|---|---|---|---|---|\n")
        r = m["run"]
        checks += (f"| serial (this case) | {r['mpi_ranks']} | {r['iterations']} | {r['clock_time_s']:.0f} s "
                   f"(ExecutionTime {r['execution_time_s']:.1f} s) | {s['onset_x_m']*1e3:.0f} / {s['mid_x_m']*1e3:.0f} / {s['peak_x_m']*1e3:.0f} | - |\n")
        for name, c in m["checks"].items():
            r, tr = c["run"], c["transition"]
            checks += (f"| {name}: {c['what']} | {r['mpi_ranks']} | {r['iterations']} | {r['clock_time_s']:.0f} s "
                       f"(ExecutionTime {r['execution_time_s']:.1f} s) | {tr['onset_x_m']*1e3:.0f} / {tr['mid_x_m']*1e3:.0f} / {tr['peak_x_m']*1e3:.0f} "
                       f"| {c['max_rel_cf_change_vs_serial']*100:.2f} % |\n")
    txt = f"""# T3A transition check (Stage 0)

**Result: {m['verdict'].lower()}.** The model puts transition {-d['onset']*1e3:.0f} mm (onset) to {-d['mid']*1e3:.0f} mm (50 % point) {'upstream' if d['mid'] < 0 else 'downstream'} of the measurement. Criterion: {m['criterion']}.
{conv}
The tutorial ships the experimental data but no reference simulation, so whether ESI's own run shows the same offset is not known.

| | Simulation | Experiment | Difference |
|---|---|---|---|
| Transition onset (c_f minimum), x | {s['onset_x_m']*1e3:.0f} mm | {e['onset_x_m_parabola']*1e3:.0f} mm (station minimum {e['onset_x_m_station']*1e3:.0f} mm) | {d['onset']*1e3:+.0f} mm |
| 50 % of the c_f rise, x | {s['mid_x_m']*1e3:.0f} mm | {e['mid_x_m']*1e3:.0f} mm | {d['mid']*1e3:+.0f} mm |
| End (c_f maximum), x | {s['peak_x_m']*1e3:.0f} mm | {e['peak_x_m_parabola']*1e3:.0f} mm (station maximum {e['peak_x_m_station']*1e3:.0f} mm) | {d['peak']*1e3:+.0f} mm |
| Onset Re_x | {m['Re_x']['sim_onset']:.3g} | {m['Re_x']['exp_onset']:.3g} | |
| c_f at onset / peak | {s['onset_cf']:.5f} / {s['peak_cf']:.5f} | {e['onset_cf']:.5f} / {e['peak_cf']:.5f} | |

- c_f at the stations: laminar part (x < 0.4 m) within {cfr['laminar_x_lt_0.4_max_abs']*100:.0f} %; turbulent part (x > 0.9 m) within {cfr['turbulent_x_gt_0.9_max_abs']*100:.0f} % (mean {cfr['turbulent_x_gt_0.9_mean']*100:+.0f} %).
- Free-stream Tu decay: within {m['Tu_rel_error_at_stations_max_abs']*100:.0f} % of the measured Tu at every station.
- Simulation values are from the {m['n_plate_faces_used']} flat plate faces at time {m['time']}. The tutorial's own sampled line gives onset {m['simulation_tutorial_sample_line']['onset_x_m']*1e3:.0f} mm and 50 % point {m['simulation_tutorial_sample_line']['mid_x_m']*1e3:.0f} mm (30 mm sample spacing).
- Experiment positions are interpolated between stations 100 mm apart (parabola through the three stations around the extremum; linear for the 50 % point); that spacing is why the criterion is +-50 mm.

Run: the tutorial unchanged (kOmegaSSTLM, simpleFoam, 26,820 cells), serial, {m['run']['iterations']} iterations.

{timing}
{checks}
Files: `result.png` (plot), `metrics.json` (all numbers), `cf_plate.csv` (c_f along the plate). Re-run with `./run.sh`.
"""
    (HERE / "result.md").write_text(txt)


if __name__ == "__main__":
    main()
