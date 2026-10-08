#!/usr/bin/env python3
"""Time history of one cfd/rotor2d case: rotor and per-blade C_Q, C_x, C_y, time step.

    python3 cfd/post/plot_rotor_case.py <caseDir> [--out file.png]

Rotating cases are plotted against revolutions (blade-1 azimuth / 360), static cases
against rotor convective times D/U. Works on partial runs. Default output:
<caseDir>/history.png.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rotor_summary as rs  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case")
    ap.add_argument("--out")
    a = ap.parse_args()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    case = Path(a.case)
    P = json.loads((case / "case.json").read_text())
    s, dz, q, A, R = P["sense"], P["dz"], P["qRef"], P["Aref"], P["R"]
    m = rs.read_vector_dat(case, "forcesRotor", "moment.dat")
    f = rs.read_vector_dat(case, "forcesRotor", "force.dat")
    rot = P["mode"] == "rotating"
    scale = P["Trev"] if rot else P["convTime"]
    xl = "revolutions" if rot else "t U / D"
    t = m[:, 0] / scale
    fig, axs = plt.subplots(3, 1, figsize=(9, 8.5), sharex=True)
    axs[0].plot(t, s * m[:, 3] / dz / (q * A * R), "k", lw=1, label="rotor")
    for k in (1, 2, 3):
        mb = rs.read_vector_dat(case, f"forcesBlade{k}", "moment.dat")
        if len(mb):
            axs[0].plot(mb[:, 0] / scale, s * mb[:, 3] / dz / (q * A * R), lw=0.6, label=f"blade {k}")
    axs[0].axhline(0, color="0.5", lw=0.5)
    axs[0].set_ylabel("C_Q (+ drives the rotor)")
    axs[0].legend(fontsize=7, ncol=4)
    if len(f) == len(m):
        axs[1].plot(t, f[:, 1] / dz / (q * A), label="C_x")
        axs[1].plot(t, f[:, 2] / dz / (q * A), label="C_y")
        axs[1].legend(fontsize=7)
    axs[1].set_ylabel("force coefficient (on 2R)")
    log = case / "log.pimpleFoam"
    if log.exists():
        txt = log.read_text(errors="replace")
        ts = np.array([float(x) for x in re.findall(r"^Time = (\S+)", txt, re.M)])
        dt = np.array([float(x) for x in re.findall(r"^deltaT = (\S+)", txt, re.M)])
        n = min(len(ts), len(dt))
        axs[2].semilogy(ts[:n] / scale, dt[:n], lw=0.8)
    axs[2].set_ylabel("time step (s)")
    axs[2].set_xlabel(xl)
    for x in axs:
        x.grid(True, lw=0.3)
    title = P["caseName"] + (f": lambda {P['lam']:g}, {P['rpm']:.0f} rpm" if rot else f": theta {P['thetaDeg']:g} deg")
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    out = Path(a.out) if a.out else case / "history.png"
    fig.savefig(out, dpi=120)
    print(out)


if __name__ == "__main__":
    main()
