"""Speed at every load dwell from T. Kang's per-sample records: candidate results for a revision.

Writes build/tacho/ (figures, tables, numbers.tex for the report). Run after build_report.py.
    python3 src/build_tacho.py      (in the data package: python3 7_code/build_tacho.py)
"""
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import data as D
import style
import tacho

style.apply()
W = style.TEXT_W_IN
OUT = D.BUILD / "tacho"
SHOW = (700, 1200, 1800)            # the wind speeds of the report's ladder figure


def label(spec):
    return style.SERIES[spec]["label"]


def tag(ax, s):
    ax.set_title(s, loc="left", fontsize=10, fontweight="bold", color=style.INK, pad=6)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    runs, _ = D.discover()
    tables, fits = [], []
    for spec in D.ORDER:
        for j, stem in enumerate(runs[spec]):
            p, f = tacho.run_table(stem)
            p["rotor"], p["run"] = label(spec), j + 1
            f.update(stem=stem, rotor=label(spec), run=j + 1, flagged=int((~p.speed_ok).sum()))
            tables.append(p)
            fits.append(f)
    P = pd.concat(tables, ignore_index=True)
    F = pd.DataFrame(fits)

    # generator: k (V/rpm) -> torque constant (N m/A); EMF and the power delivered into the generator
    k_mean, R_mean, b_mean = F.k.mean(), F.R.mean(), F.b.mean()
    kT = k_mean * 60 / (2 * math.pi)
    P["torque_gen_nm"] = kT * P.amps                                    # electromagnetic torque
    P["p_gen_in_w"] = P.watts + P.amps ** 2 * R_mean - b_mean * P.amps   # EMF x current
    v = P.wind_mps
    P["cp_gen_in"] = P.p_gen_in_w / (0.5 * D.RHO_STD * D.AREA_M2 * v ** 3)
    P["settle_pct"] = 100 * (P.rotor_rpm / P.rotor_rpm_early - 1)

    # per run and set point: the peak-power dwell
    pk = P.loc[P.groupby(["stem", "fan_rpm"]).watts.idxmax()].copy()
    S = (pk.groupby(["rotor", "fan_rpm"])
           .agg(wind_mps=("wind_mps", "first"), p_max_w=("watts", "mean"), cp_el=("cp_el", "mean"),
                tsr_at_pmax=("tsr", "mean"), rpm_at_pmax=("rotor_rpm", "mean"),
                p_gen_in_max_w=("p_gen_in_w", "max"), torque_at_pmax=("torque_gen_nm", "mean"))
           .reset_index())

    # generator constant against run start time (drift over the session, e.g. magnets warming)
    starts = {stem: float(D.load(stem)["points"].t_unix.iloc[0]) for stem in F.stem}
    F["start_h"] = [(starts[s_] - min(starts.values())) / 3600 for s_ in F.stem]
    X = np.c_[np.ones(len(F)), F.start_h]
    coef, res, *_ = np.linalg.lstsq(X, 1000 * F.k, rcond=None)
    dof = len(F) - 2
    s2 = float(((1000 * F.k - X @ coef) ** 2).sum()) / dof
    se = math.sqrt(s2 * np.linalg.inv(X.T @ X)[1, 1])
    from scipy import stats
    tq = stats.t.ppf(0.975, dof)
    kdrift = dict(slope=coef[1], lo=coef[1] - tq * se, hi=coef[1] + tq * se, k0=coef[0])

    P.to_csv(OUT / "per_dwell.csv", index=False)
    # tidy tables for the data package (4_derived/)
    (OUT / "derived").mkdir(exist_ok=True)
    tidy = P.rename(columns={"stem": "run_name", "fan_rpm": "fan_rpm_cmd", "tsr": "tip_speed_ratio"})[
        ["rotor", "run", "run_name", "fan_rpm_cmd", "wind_mps", "t_unix", "demand_a", "volts", "amps",
         "watts", "rotor_rpm", "rotor_rpm_early", "speed_ok", "tip_speed_ratio", "cp_el",
         "torque_gen_nm", "p_gen_in_w"]]
    tidy.to_csv(OUT / "derived" / "rotor_speed_by_dwell.csv", index=False, float_format="%.6g")
    gen = F.rename(columns={"stem": "run_name", "offset": "clock_offset_s",
                            "offset_speed_model": "clock_offset_speed_model_s",
                            "drift_speed_model": "clock_drift_speed_model", "k": "k_v_per_rpm",
                            "R": "r_ohm", "b": "b_v", "rms": "fit_rms_v"})[
        ["rotor", "run", "run_name", "clock_offset_s", "clock_offset_speed_model_s",
         "clock_drift_speed_model", "r_voltage", "k_v_per_rpm", "r_ohm", "b_v", "fit_rms_v", "n_fit",
         "n_dwells", "pulse_repairs", "flagged", "start_h"]]
    gen.to_csv(OUT / "derived" / "generator_by_run.csv", index=False, float_format="%.6g")
    F.drop(columns=["t0"]).to_csv(OUT / "run_fits.csv", index=False)
    pd.DataFrame([kdrift]).to_csv(OUT / "generator_drift.csv", index=False)
    S.to_csv(OUT / "peak_by_setpoint.csv", index=False)

    # ---- figures
    fig, grid = plt.subplots(2, 2, figsize=(W, 5.4), constrained_layout=True)
    for i, (ax, cmd) in enumerate(zip(grid.ravel(), SHOW)):
        for spec in D.ORDER:
            for j in (1, 2):
                q = P[(P.rotor == label(spec)) & (P.run == j) & (P.fan_rpm == cmd) & P.speed_ok]
                ax.plot(q.tsr, 100 * q.cp_el, markersize=3.8, linewidth=1.1,
                        linestyle="-" if j == 1 else (0, (3, 2)),
                        **style.kw(spec, run=j, label=label(spec) if j == 1 else "_nolegend_"))
        ax.set_xlabel("Tip-speed ratio $\\lambda$ (on $R$)"); ax.set_ylabel("$C_{P,\\mathrm{el}}$ (%)")
        tag(ax, f"({'abc'[i]}) {float(D.wind(cmd)):.1f} m/s"); ax.set_ylim(0, None)
    ax = grid[1, 1]
    for spec in D.ORDER:
        q = S[S.rotor == label(spec)]
        ax.plot(q.wind_mps, q.tsr_at_pmax, **style.kw(spec, linewidth=1.5))
    ax.set_xlabel("Wind speed (m/s)"); ax.set_ylabel("$\\lambda$ at $P_{\\max}$")
    ax.legend(loc="lower right"); tag(ax, "(d) Tip-speed ratio at peak power")
    fig.savefig(OUT / "fig_cp_tsr.png", dpi=200); fig.savefig(OUT / "fig_cp_tsr.pdf"); plt.close(fig)

    fig, grid = plt.subplots(2, 2, figsize=(W, 5.4), constrained_layout=True)
    for i, (ax, cmd) in enumerate(zip(grid.ravel(), SHOW)):
        for spec in D.ORDER:
            for j in (1, 2):
                q = P[(P.rotor == label(spec)) & (P.run == j) & (P.fan_rpm == cmd) & P.speed_ok]
                ax.plot(q.rotor_rpm, 1000 * q.torque_gen_nm, markersize=3.8, linewidth=1.1,
                        linestyle="-" if j == 1 else (0, (3, 2)),
                        **style.kw(spec, run=j, label=label(spec) if j == 1 else "_nolegend_"))
        ax.set_xlabel("Rotor speed (rpm)"); ax.set_ylabel("Generator torque (mN m)")
        tag(ax, f"({'abc'[i]}) {float(D.wind(cmd)):.1f} m/s"); ax.set_ylim(0, None)
    ax = grid[1, 1]
    q = P[P.speed_ok & (P.fan_rpm > 500)]
    ax.hist(q.settle_pct.clip(-10, 10), bins=60, color=style.INK_3)
    ax.set_xlabel("Speed change within a dwell (%)"); ax.set_ylabel("Dwells")
    tag(ax, "(d) Settling within each 1 s dwell")
    grid[0, 0].legend(loc="upper right")
    fig.savefig(OUT / "fig_torque_speed.png", dpi=200); fig.savefig(OUT / "fig_torque_speed.pdf"); plt.close(fig)

    # ---- one-page supplement figure: C_P,el vs lambda and torque vs speed at two wind speeds
    fig, grid = plt.subplots(2, 2, figsize=(W, 4.4), constrained_layout=True)
    for col, cmd in enumerate((1200, 1800)):
        for row, (x, y, xl, yl, sc) in enumerate((
                ("tsr", "cp_el", "Tip-speed ratio $\\lambda$ (on $R$)", "$C_{P,\\mathrm{el}}$ (%)", 100),
                ("rotor_rpm", "torque_gen_nm", "Rotor speed (rpm)", "Generator torque (mN m)", 1000))):
            ax = grid[row, col]
            for spec in D.ORDER:
                for j in (1, 2):
                    q = P[(P.rotor == label(spec)) & (P.run == j) & (P.fan_rpm == cmd) & P.speed_ok]
                    ax.plot(q[x], sc * q[y], markersize=3.8, linewidth=1.1,
                            linestyle="-" if j == 1 else (0, (3, 2)),
                            **style.kw(spec, run=j, label=label(spec) if j == 1 else "_nolegend_"))
            ax.set_xlabel(xl); ax.set_ylabel(yl); ax.set_ylim(0, None)
            tag(ax, f"({'abcd'[2 * row + col]}) {float(D.wind(cmd)):.1f} m/s")
    grid[1, 0].legend(loc="upper right")
    fig.savefig(OUT / "fig_supplement.png", dpi=200); fig.savefig(OUT / "fig_supplement.pdf"); plt.close(fig)

    # ---- macros for the meeting supplement
    q = P[P.speed_ok & (P.fan_rpm > 500)]
    span_h = F.start_h.max()
    M = {
        "tkOffLo": f"{-F.offset.max():.1f}", "tkOffHi": f"{-F.offset.min():.1f}",
        "tkOffAgree": f"{(F.offset - F.offset_speed_model).abs().max():.1f}",
        "tkDriftMax": f"{100 * F.drift_speed_model.abs().max():.1f}",
        "tkKLo": f"{1000 * F.k.min():.1f}", "tkKHi": f"{1000 * F.k.max():.1f}",
        "tkRLo": f"{F.R.min():.1f}", "tkRHi": f"{F.R.max():.1f}",
        "tkRmsLo": f"{F.rms.min():.2f}", "tkRmsHi": f"{F.rms.max():.2f}",
        "tkRepairs": str(int(F.pulse_repairs.sum())), "tkFlagged": str(int(F.flagged.sum())),
        "tkRepairsPA": str(int(F[F.rotor.isin(["Plain", "FS 0.05"])].pulse_repairs.sum()
                               + F[F.rotor.isin(["Plain", "FS 0.05"])].flagged.sum())),
        "tkRepairsAll": str(int(F.pulse_repairs.sum() + F.flagged.sum())),
        "tkDwells": str(int(len(P))),
        "tkSettleMed": f"{-q.settle_pct.median():.1f}", "tkSettleTwo": f"{100 * (q.settle_pct.abs() > 2).mean():.0f}",
        "tkKDriftPct": f"{-100 * kdrift['slope'] * span_h / kdrift['k0']:.1f}", "tkSpanH": f"{span_h:.1f}",
        "tkKT": f"{kT:.2f}", "tkVmid": f"{float(D.wind(1200)):.1f}",
        "tkKDrift": f"{-kdrift['slope']:.2f}", "tkKDriftLo": f"{-kdrift['hi']:.2f}", "tkKDriftHi": f"{-kdrift['lo']:.2f}",
    }
    for r, key in (("Plain", "P"), ("FS 0.05", "A"), ("FS 0.10", "B"), ("FS 0.20", "C")):
        M[f"tkTsr{key}"] = f"{S[S.rotor == r].tsr_at_pmax.mean():.3f}"
    ref = S[S.rotor == "Plain"].set_index("fan_rpm")
    for r, key in (("FS 0.05", "A"), ("FS 0.10", "B"), ("FS 0.20", "C")):
        s_ = S[S.rotor == r].set_index("fan_rpm")
        M[f"tkGenGain{key}"] = f"{100 * (np.exp(np.log(s_.p_gen_in_max_w / ref.p_gen_in_max_w).mean()) - 1):+.1f}"
    with open(OUT / "numbers.tex", "w") as fh:
        fh.write("% generated by build_tacho.py - do not edit\n")
        for k_, v_ in sorted(M.items()):
            fh.write(f"\\newcommand{{\\{k_}}}{{{v_}}}\n")

    # ---- summary numbers
    print(F[["stem", "pulse_repairs", "flagged", "offset", "offset_speed_model", "drift", "r_voltage",
             "k", "R", "b", "rms", "n_fit", "n_dwells"]].round(4).to_string(index=False))
    print(f"generator constant drift: {kdrift['slope']:+.3f} mV/rpm per hour"
          f" [{kdrift['lo']:+.3f}, {kdrift['hi']:+.3f}] (95%, {dof} dof); k at first run {kdrift['k0']:.2f}")
    print(f"\nk = {1000*k_mean:.2f} mV/rpm (runs {1000*F.k.min():.2f}-{1000*F.k.max():.2f});"
          f" kT = {kT:.4f} N m/A; R = {R_mean:.2f} ohm ({F.R.min():.2f}-{F.R.max():.2f}); b = {b_mean:+.2f} V")
    q = P[P.speed_ok & (P.fan_rpm > 500)]
    print(f"settling: |change| > 1% in {100*(q.settle_pct.abs() > 1).mean():.1f}% of dwells,"
          f" > 2% in {100*(q.settle_pct.abs() > 2).mean():.1f}%; median {q.settle_pct.median():+.2f}%")
    t = S.groupby("rotor").agg(tsr=("tsr_at_pmax", "mean"), tsr_lo=("tsr_at_pmax", "min"),
                               tsr_hi=("tsr_at_pmax", "max"))
    print("\nlambda at P_max (mean, min, max over set points):\n", t.round(3).to_string())
    # gain in P_max vs gain in generator input power (copper loss accounted)
    ref = S[S.rotor == "Plain"].set_index("fan_rpm")
    for r in ("FS 0.05", "FS 0.10", "FS 0.20"):
        s = S[S.rotor == r].set_index("fan_rpm")
        g1 = np.exp(np.log(s.p_max_w / ref.p_max_w).mean()) - 1
        g2 = np.exp(np.log(s.p_gen_in_max_w / ref.p_gen_in_max_w).mean()) - 1
        print(f"{r}: P_max gain {100*g1:+.1f}%   generator-input-power gain {100*g2:+.1f}%")


if __name__ == "__main__":
    main()
