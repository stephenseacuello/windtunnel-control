#!/usr/bin/env python3
"""Summary of one Stage 2 case (cfd/stage2/runs/<name>/): the Stage 1 summary
(cfd/post/section_summary.py, unchanged) plus the Stage 2 fields.

    python3 cfd/stage2/stage2_summary.py cfd/stage2/runs/<name> [--window 20]

Added fields
  wall, Ks_um, KsEnds_um, Cs, tex_t_mm, tex_seed, h0_m, yP_m, Ks_over_yP, mesh_check, nonOrthLimit
  yplus_<patch>_{mean,max}   first-cell-centre y+ per wall patch (blade, bladeEnds), window means
                             of the patch mean and patch max. The yPlus function object runs with
                             useWallFunction false (as Stage 1), so y+ = y_P u_tau/nu with
                             u_tau = sqrt(nu_eff |dU/dn|) at the wall (the wall shear stress, which on
                             a wall-function patch includes nut_w); it is not the k-based
                             y* = Cmu^0.25 sqrt(k_P) y_P/nu that the wall function uses internally
  ksplus_blade_{mean,max}    wf: Ks+ = u_tau Ks / nu = y+ Ks / y_P on the painted faces, from the
                             two y+ values above (estimated: y_P = h0/2 holds away from the corners)
The Stage 1 y+ fields (yplus_max_mean, ...) pool both wall patches.
No OpenFOAM install is needed.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != HERE]
sys.path.insert(0, str(HERE.parent / "post"))
import section_summary  # noqa: E402


def yplus_by_patch(case, t0):
    """{patch: (mean of patch-mean y+, mean of patch-max y+)} over times >= t0 (all if none)."""
    rows = {}
    for _, d in section_summary._num_dirs(Path(case) / "postProcessing" / "yPlus1"):
        f = section_summary.session_file(d, "yPlus.dat")
        if f is None:
            continue
        for line in f.read_text().splitlines():
            if line.startswith("#") or not line.strip():
                continue
            s = line.split()
            rows.setdefault(s[1], set()).add((float(s[0]), float(s[3]), float(s[4])))   # t, max, mean
    out = {}
    for patch, r in rows.items():
        a = np.array(sorted(r))
        m = a[:, 0] >= t0
        if not m.any():
            m = np.ones(len(a), bool)
        out[patch] = (float(a[m, 2].mean()), float(a[m, 1].mean()))
    return out


def summarize(case, window_conv=None):
    case = Path(case)
    out = section_summary.summarize(case, window_conv)
    P = json.loads((case / "case.json").read_text())
    tc = P["convTime"]
    t0 = out["avg_from_conv"] * tc
    out.update(wall=P.get("wall"), Ks_um=round(P.get("KsBlade", 0.0) * 1e6, 6),
               KsEnds_um=round(P.get("KsEnds", 0.0) * 1e6, 6),
               Cs=P.get("Cs"), tex_t_mm=round(P.get("texT", 0.0) * 1e3, 9), tex_seed=P.get("texSeed"),
               h0_m=P.get("h0"), yP_m=P.get("yP"), Ks_over_yP=P.get("KsOverYp"),
               mesh_check=P.get("meshCheck"), nonOrthLimit=P.get("nonOrthLimit"))
    yp = yplus_by_patch(case, t0)
    for patch, (mean, mx) in yp.items():
        out[f"yplus_{patch}_mean"] = mean
        out[f"yplus_{patch}_max"] = mx
    if P.get("wall") == "wf" and "blade" in yp and P.get("yP"):
        r = P.get("KsBlade", 0.0) / P["yP"]
        out["ksplus_blade_mean"] = yp["blade"][0] * r
        out["ksplus_blade_max"] = yp["blade"][1] * r
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case")
    ap.add_argument("--window", type=float, help="averaging window in c/U (default: nAvg of the case)")
    a = ap.parse_args()
    print(json.dumps(summarize(a.case, a.window), indent=1))


if __name__ == "__main__":
    sys.exit(main())
