"""B1 rotor pairs (priorityF_verify.txt): the Ks-400 change in C_Q on the coarse and fine meshes and at maxCo 2,
next to the October medium pair, with the October uncertainty rule.

Reads (read only):
  cfd/rotor2d/runs/<case>/case.json, postProcessing/forcesRotor/0/moment.dat   (git-ignored run folders)
  cfd/rotor2d/results/rotor_cp.csv                                              (CQ_mean of each run, as 15 Oct)
  cfd/analysis/2026-10-15/out/rotor_roughness.csv                               (the October pair, for the check)
  cfd/analysis/2026-10-15/src/rotor_analysis.py   imported, not edited: rev_history (revolution means of C_Q)
Writes:
  cfd/analysis/2026-11-15/out/b1_rotor_pairs.csv   one row per pair and window
  cfd/analysis/2026-11-15/out/b1_rotor_pairs_check.csv

Rule (as rotor_analysis.py, 15 Oct): d = CQ_mean(Ks400) - CQ_mean(Ks0) from rotor_cp.csv (the runs' own
averages; over another window, the difference of the revolution means, dCQ_revs);
2u = 2 hypot(s_a/sqrt(n), s_b/sqrt(n)) with s the scatter of the revolution means (u_iid). Also given:
2u_batch from batch means of 5 revolutions (allows for revolution-to-revolution correlation), and whether d is
still resolved with 2u doubled (README: the 2u is probably 1.6-2 x too narrow). The fine runs average 55
revolutions (6-60); they are also evaluated over revolutions 6-50, the window of the 45-revolution runs.
"""
import sys

sys.dont_write_bytecode = True          # the imported 15 Oct module gets no __pycache__ from this run

import csv  # noqa: E402
import importlib.util  # noqa: E402
import math  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

BASE = Path(__file__).resolve().parents[1]
REPO = BASE.parents[2]
OUT = BASE / "out"
spec = importlib.util.spec_from_file_location("rotor_analysis", REPO / "cfd/analysis/2026-10-15/src/rotor_analysis.py")
ra = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ra)

P = "A_rot_U23.0_lam0.100_SST_"
PAIRS = [  # label, Ks0 case, Ks400 case, revolutions averaged, mesh, maxCo
    ("medium_oct", P + "medium_Ks0_senseCCW_rev50a45", P + "medium_Ks400_senseCCW_rev50a45", 45, "medium", 4.0),
    ("coarse", P + "coarse_Ks0_senseCCW_rev50a45", P + "coarse_Ks400_senseCCW_rev50a45", 45, "coarse", 4.0),
    ("medium_co2", P + "medium_Ks0_senseCCW_Co2n2_rev50a45", P + "medium_Ks400_senseCCW_Co2n2_rev50a45", 45, "medium", 2.0),
    ("fine", P + "fine_Ks0_senseCCW_rev60a55", P + "fine_Ks400_senseCCW_rev60a55", 55, "fine", 4.0),
]
BATCH = 5


def have(case):
    return (ra.RUNS / case / "postProcessing/forcesRotor/0/moment.dat").exists() and (ra.RUNS / case / "case.json").exists()


def lag1(w):
    x = w - w.mean()
    return float(np.sum(x[:-1] * x[1:]) / np.sum(x * x))


def stats(wa, wb, d_table=None):
    n = len(wa)
    d_revs = float(wa.mean() - wb.mean())
    d = d_revs if d_table is None else d_table
    u = math.hypot(wa.std(ddof=1) / math.sqrt(n), wb.std(ddof=1) / math.sqrt(n))
    nb = n // BATCH
    ba = wa[n - nb * BATCH:].reshape(nb, BATCH).mean(axis=1)
    bb = wb[n - nb * BATCH:].reshape(nb, BATCH).mean(axis=1)
    ub = math.hypot(ba.std(ddof=1) / math.sqrt(nb), bb.std(ddof=1) / math.sqrt(nb))
    dp = wa - wb
    h = n // 2
    return dict(n_avg=n, CQ_Ks0=float(wb.mean()), CQ_Ks400=float(wa.mean()), dCQ=d, dCQ_revs=d_revs, two_u=2 * u,
                resolved_2u=abs(d) > 2 * u, two_u_batch5=2 * ub, resolved_2u_batch5=abs(d) > 2 * ub,
                resolved_2x_2u=abs(d) > 4 * u, rel_change_pct=100 * d / float(wb.mean()),
                lag1_Ks0=lag1(wb), lag1_Ks400=lag1(wa), d_first_half=float(dp[:h].mean()),
                d_second_half=float(dp[-h:].mean()))


def main():
    OUT.mkdir(exist_ok=True)
    cp = {r["name"]: r for r in csv.DictReader(open(REPO / "cfd/rotor2d/results/rotor_cp.csv"))}
    rows, missing = [], []
    for lab, b, a, nav, lvl, co in PAIRS:
        gone = [c for c in (b, a) if not have(c)]
        if gone:
            missing += gone
            continue
        ha, hb = ra.rev_history(a), ra.rev_history(b)
        wins = [(f"last{nav}", slice(-nav, None))]
        if nav != 45:
            wins.append(("rev6-50", slice(5, 50)))
        for wl, sl in wins:
            d_tab = None
            if wl.startswith("last"):
                if a not in cp or b not in cp:
                    raise SystemExit(f"{lab}: not in rotor_cp.csv yet (run pull_results.py)")
                d_tab = float(cp[a]["CQ_mean"]) - float(cp[b]["CQ_mean"])
            r = dict(pair=lab, window=wl, level=lvl, maxCo=co, case_Ks0=b, case_Ks400=a,
                     n_rev_Ks0=hb["nr"], n_rev_Ks400=ha["nr"])
            r.update(stats(ha["rev"][sl], hb["rev"][sl], d_tab))
            rows.append(r)
    with open(OUT / "b1_rotor_pairs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.6g}" if isinstance(v, float) else v) for k, v in r.items()})
    # check: the October pair reproduces rotor_roughness.csv (15 Oct) to 6 digits
    oct_ = next(r for r in csv.DictReader(open(REPO / "cfd/analysis/2026-10-15/out/rotor_roughness.csv"))
                if r["lam"] == "0.1" and r["a"] == "Ks400" and r["b"] == "Ks0")
    mine = next(r for r in rows if r["pair"] == "medium_oct")
    chk = []
    for k in ("dCQ", "two_u"):
        ok = abs(mine[k] - float(oct_[k])) <= 5e-6 * abs(float(oct_[k]))
        chk.append(dict(check=f"medium_oct {k} = 15 Oct rotor_roughness.csv", value=f"{mine[k]:.6g}",
                        reference=oct_[k], passed=ok))
    with open(OUT / "b1_rotor_pairs_check.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(chk[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(chk)
    for r in rows:
        print(f"{r['pair']:11s} {r['window']:8s} n={r['n_avg']:2d} d={r['dCQ']:+.5f} 2u={r['two_u']:.5f} "
              f"2u_b5={r['two_u_batch5']:.5f} res={r['resolved_2u']}/{r['resolved_2u_batch5']}/{r['resolved_2x_2u']} "
              f"{r['rel_change_pct']:+.1f}% halves {r['d_first_half']:+.5f} {r['d_second_half']:+.5f}")
    if missing:
        print("not on disk (skipped): " + ", ".join(missing))
    if not all(c["passed"] for c in chk):
        raise SystemExit("check failed: the October pair is not reproduced")
    print(f"{len(chk)} of {len(chk)} checks pass")


if __name__ == "__main__":
    main()
