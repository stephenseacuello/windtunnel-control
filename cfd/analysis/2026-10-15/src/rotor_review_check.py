#!/usr/bin/env python3
"""Second independent check of the 15 Oct rotor findings (verifier 2, 19 Oct 2026).

    nice -n 10 python3 cfd/analysis/2026-10-15/src/rotor_review_check.py

Shares no code with rotor_analysis.py or rotor_verify.py. Reads only the table
cfd/rotor2d/results/rotor_cp.csv, the case folders cfd/rotor2d/runs/<case>/ (case.json and
postProcessing/forces{Rotor,Blade1,Blade2,Blade3}/0/{moment,force}.dat; read only) and
cfd/stage2/results/stage2_polars.csv. Prints one line per quoted number: the value quoted in the
corrected findings, the recomputed value and OK or CHECK; the count of CHECK lines comes last.

Methods (chosen to differ from the analysis script):
- force files parsed line by line in Python;
- every mean is the exact integral of the piecewise-linear interpolant of the samples, with the
  window and revolution boundaries inserted by interpolation (not a cumulative trapezoid);
- sector contributions from a 7,200-point-per-revolution midpoint resample of each blade's C_Q;
- uncertainties: 2u = 2 s/sqrt(n) from the revolution means (s with n - 1); a difference of two
  runs adds the two u in quadrature; the drift is the mean of the last minus the first
  floor(3n/2) blade-passing periods (T/3) of the window (the 15 Oct definition).
New numbers checked here and not in rotor_analysis.py: the Ks-400 minus Ks-100 difference, the
resolution of the C_x and C_Q-std changes, the blade's streamwise force at the advancing
(theta 80-100 deg) and returning (theta 260-280 deg) edge-on positions, and the mesh check with
the medium mesh at maxCo 2.
"""
import json
import math
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[4]
RUNS = REPO / "cfd/rotor2d/runs"
S2 = REPO / "cfd/stage2/results/stage2_polars.csv"
C_REF = 0.048
NCHECK, NOK = [0], [0]


def say(label, quoted, value, tol):
    ok = abs(value - quoted) <= tol
    (NOK if ok else NCHECK)[0] += 1
    print(f"{'OK   ' if ok else 'CHECK'} {label}: quoted {quoted:+.5g} | recomputed {value:+.6g}")


def read_dat(path):
    rows = []
    with open(path) as fh:
        for ln in fh:
            if ln[0] == "#":
                continue
            p = ln.replace("(", " ").replace(")", " ").split()
            if len(p) >= 10:
                rows.append([float(x) for x in p[:10]])
    a = np.array(rows)
    _, i = np.unique(a[:, 0], return_index=True)
    return a[np.sort(i)]


def integral(t, y, a, b):
    ya, yb = np.interp([a, b], t, y)
    m = (t > a) & (t < b)
    tt = np.concatenate([[a], t[m], [b]])
    yy = np.concatenate([[ya], y[m], [yb]])
    return float(np.sum(0.5 * (yy[1:] + yy[:-1]) * np.diff(tt)))


class Run:
    def __init__(self, name, blades=True):
        self.name = name
        P = json.loads((RUNS / name / "case.json").read_text())
        self.P = P
        q = 0.5 * P["rhoInf"] * P["Uinf"] ** 2
        kq = P["sense"] / (P["dz"] * q * 2 * P["R"] * P["R"])
        pp = RUNS / name / "postProcessing"
        m = read_dat(pp / "forcesRotor/0/moment.dat")
        f = read_dat(pp / "forcesRotor/0/force.dat")
        self.t = m[:, 0]
        self.cq, self.cqp, self.cqv = kq * m[:, 3], kq * m[:, 6], kq * m[:, 9]
        self.cx = f[:, 1] / (P["dz"] * q * 2 * P["R"])
        self.T, self.nav = P["Trev"], int(P["nAvgRev"])
        self.t1 = self.t[-1]
        self.t0 = self.t1 - self.nav * self.T
        if blades:
            self.bq, self.bfx = [], []
            for k in (1, 2, 3):
                mb = read_dat(pp / f"forcesBlade{k}/0/moment.dat")
                fb = read_dat(pp / f"forcesBlade{k}/0/force.dat")
                assert len(mb) == len(self.t) and len(fb) == len(self.t)
                self.bq.append(kq * mb[:, 3])
                self.bfx.append(fb[:, 1] / (P["dz"] * q * C_REF))

    def mean(self, y):
        return integral(self.t, y, self.t0, self.t1) / (self.t1 - self.t0)

    def revs(self, y):
        """Means of the nav revolutions of the window."""
        e = self.t0 + self.T * np.arange(self.nav + 1)
        e[-1] = self.t1
        return np.array([integral(self.t, y, a, b) / (b - a) for a, b in zip(e[:-1], e[1:])])

    def drift(self, y):
        n = (3 * self.nav) // 2
        h = n * self.T / 3
        return integral(self.t, y, self.t1 - h, self.t1) / h - integral(self.t, y, self.t0, self.t0 + h) / h

    def blade_resample(self):
        n = self.nav * 7200
        tt = self.t0 + (np.arange(n) + 0.5) * (self.t1 - self.t0) / n
        rev = np.minimum(((tt - self.t0) / self.T).astype(int), self.nav - 1)
        th0 = np.degrees(self.P["Omega"] * tt) + self.P.get("thetaDeg", 0.0)
        out = []
        for k in range(3):
            out.append((np.mod(th0 + 120.0 * k, 360.0), np.interp(tt, self.t, self.bq[k]),
                        np.interp(tt, self.t, self.bfx[k])))
        return rev, out


def two_u(x):
    return 2 * float(np.std(x, ddof=1)) / math.sqrt(len(x))


def sector(run, lo, hi):
    """Per-revolution contribution of blade azimuths [lo, hi) to the rotor C_Q."""
    rev, bl = run.blade_resample()
    acc = np.zeros(run.nav)
    for th, q, _ in bl:
        m = ((th >= lo) | (th < hi)) if lo > hi else ((th >= lo) & (th < hi))
        acc += np.bincount(rev[m], weights=q[m], minlength=run.nav) / 7200
    return acc


def edge_force(run, lo, hi):
    """Per-revolution mean streamwise force coefficient (c_ref, free-stream q) of a blade in [lo, hi)."""
    rev, bl = run.blade_resample()
    s, c = np.zeros(run.nav), np.zeros(run.nav)
    for th, _, fx in bl:
        m = (th >= lo) & (th < hi)
        s += np.bincount(rev[m], weights=fx[m], minlength=run.nav)
        c += np.bincount(rev[m], minlength=run.nav)
    return s / c


def main():
    long = {}
    for lam in ("0.100", "0.120"):
        for tag, suf in (("Sp", ""), ("Ks0", "_Ks0"), ("Ks100", "_Ks100"), ("Ks400", "_Ks400")):
            long[(lam, tag)] = Run(f"A_rot_U23.0_lam{lam}_SST_medium{suf}_senseCCW_rev50a45")
    R = {k: dict(m=r.mean(r.cq), rv=r.revs(r.cq), dr=r.drift(r.cq), mp=r.mean(r.cqp), mv=r.mean(r.cqv),
                 cx=r.revs(r.cx), sd=np.sqrt(r.revs(r.cq ** 2) - r.revs(r.cq) ** 2)) for k, r in long.items()}

    print("== R1 / R3: 45-revolution means and 2u (C_Q)")
    q = {("0.100", "Sp"): (0.01704, 0.00211), ("0.100", "Ks0"): (0.01861, 0.00205),
         ("0.100", "Ks100"): (0.02001, 0.00182), ("0.100", "Ks400"): (0.02371, 0.00185),
         ("0.120", "Sp"): (0.01310, 0.00206), ("0.120", "Ks0"): (0.01531, 0.00224),
         ("0.120", "Ks100"): (0.01240, 0.00223), ("0.120", "Ks400"): (0.02107, 0.00176)}
    for k, (cq, tu) in q.items():
        say(f"C_Q {k}", cq, R[k]["m"], 1e-5)   # table: sample trapezoid; here: exact interpolant
        say(f"2u {k}", tu, two_u(R[k]["rv"]), 6e-6)

    print("\n== differences: dC_Q, 2u, batch 2u, drift-rule noise, 22-revolution halves")
    quoted = {("0.100", "Ks400", "Ks0"): (0.00510, 0.00276, 0.00267, 0.00104, 0.0052, 0.0056),
              ("0.120", "Ks400", "Ks0"): (0.00576, 0.00284, 0.00342, 0.00669, 0.0043, 0.0070),
              ("0.100", "Ks100", "Ks0"): (0.00141, 0.00274, 0.00278, 0.00133, 0.0010, 0.0020),
              ("0.120", "Ks100", "Ks0"): (-0.00291, 0.00316, 0.00414, 0.00639, -0.0047, -0.0016),
              ("0.100", "Ks0", "Sp"): (0.00157, 0.00294, 0.00308, 0.00300, 0.0008, 0.0020),
              ("0.120", "Ks0", "Sp"): (0.00222, 0.00304, 0.00364, 0.00593, 0.0041, 0.0007),
              ("0.100", "Ks400", "Sp"): (0.00667, 0.00281, 0.00275, 0.00224, 0.0060, 0.0076),
              ("0.120", "Ks400", "Sp"): (0.00798, 0.00271, 0.00282, 0.00296, 0.0084, 0.0076),
              ("0.100", "Ks100", "Sp"): (0.00298, 0.00279, 0.00285, 0.00253, 0.0018, 0.0040),
              ("0.100", "Ks400", "Ks100"): (0.00369, 0.00260, 0.00241, 0.00056, 0.0041, 0.0036),
              ("0.120", "Ks400", "Ks100"): (0.00867, 0.00284, 0.00343, 0.00341, 0.0090, 0.0086)}
    for (lam, a, b), (d, tu, tub, dsum, h1, h2) in quoted.items():
        A, B = R[(lam, a)], R[(lam, b)]
        bm = lambda x: x.reshape(9, 5).mean(axis=1)
        say(f"dC_Q {lam} {a}-{b}", d, A["m"] - B["m"], 6e-6)
        say(f"  2u", tu, math.hypot(two_u(A["rv"]), two_u(B["rv"])), 6e-6)
        say(f"  2u batch 9x5", tub, math.hypot(two_u(bm(A["rv"])), two_u(bm(B["rv"]))), 6e-6)
        say(f"  drift-rule noise |drift_a|+|drift_b|", dsum, abs(A["dr"]) + abs(B["dr"]), 6e-6)
        say(f"  first 22 revolutions", h1, A["rv"][:22].mean() - B["rv"][:22].mean(), 6e-5)
        say(f"  last 22 revolutions", h2, A["rv"][23:].mean() - B["rv"][23:].mean(), 6e-5)
    say("drift of Ks0, lambda 0.12", -0.00483, R[("0.120", "Ks0")]["dr"], 6e-6)

    print("\n== R1 physics: pressure / viscous parts, C_x and C_Q std of Ks400 - Ks0 (with 2u)")
    for lam, dp, dv, dcx, tcx, dsd, tsd in (("0.100", 0.00543, -0.00033, 0.0128, 0.0079, -0.0149, 0.0019),
                                            ("0.120", 0.00614, -0.00038, 0.0089, 0.0110, -0.0143, 0.0024)):
        A, B = R[(lam, "Ks400")], R[(lam, "Ks0")]
        say(f"dC_Q pressure {lam}", dp, A["mp"] - B["mp"], 6e-6)
        say(f"dC_Q viscous {lam}", dv, A["mv"] - B["mv"], 6e-6)
        say(f"dC_x {lam}", dcx, A["cx"].mean() - B["cx"].mean(), 6e-5)
        say(f"  2u", tcx, math.hypot(two_u(A["cx"]), two_u(B["cx"])), 6e-5)
        say(f"d std(C_Q) within revolutions {lam}", dsd, A["sd"].mean() - B["sd"].mean(), 6e-5)
        say(f"  2u", tsd, math.hypot(two_u(A["sd"]), two_u(B["sd"])), 6e-5)

    print("\n== R2 / R3: sector contributions (rotor C_Q), differences and 2u")
    sect = {"upwind": (330, 30), "advancing": (60, 120), "downwind": (150, 210), "returning": (240, 300)}
    S = {}
    for k, r in long.items():
        S[k] = {s: sector(r, *lh) for s, lh in sect.items()}
        S[k]["sum"] = sum(S[k].values()) + sector(r, 30, 60) + sector(r, 120, 150) + sector(r, 210, 240) \
            + sector(r, 300, 330)
        say(f"sectors + gaps = window mean {k}", R[k]["m"], S[k]["sum"].mean(), 2e-6)
    qs = {("0.100", "Ks400", "Ks0"): dict(advancing=(0.0092, 0.0006), returning=(-0.0048, 0.0022),
                                          upwind=(-0.0015, 0.0006), downwind=(0.0032, 0.0011)),
          ("0.120", "Ks400", "Ks0"): dict(advancing=(0.0085, 0.0005), returning=(-0.0024, 0.0021),
                                          upwind=(-0.0021, 0.0007), downwind=(0.0018, 0.0017)),
          ("0.100", "Ks0", "Sp"): dict(advancing=(-0.0072, 0.0005), returning=(0.0069, 0.0026),
                                       upwind=(0.0025, 0.0006)),
          ("0.120", "Ks0", "Sp"): dict(advancing=(-0.0046, 0.0004), returning=(0.0043, 0.0022),
                                       upwind=(0.0038, 0.0008)),
          ("0.100", "Ks400", "Sp"): dict(advancing=(0.0020, 0.0006)),
          ("0.120", "Ks400", "Sp"): dict(advancing=(0.0039, 0.0005)),
          ("0.100", "Ks100", "Ks0"): dict(advancing=(0.0011, 0.0004)),
          ("0.120", "Ks100", "Ks0"): dict(advancing=(0.0009, 0.0005))}
    for (lam, a, b), dd in qs.items():
        for s, (d, tu) in dd.items():
            x, y = S[(lam, a)][s], S[(lam, b)][s]
            say(f"{s} {lam} {a}-{b}", d, x.mean() - y.mean(), 6e-5)
            say(f"  2u", tu, math.hypot(two_u(x), two_u(y)), 6e-5)
    for s, v in (("upwind", 0.0670), ("advancing", 0.0216), ("downwind", -0.0116), ("returning", -0.0489)):
        say(f"Spalding lambda 0.10 sector {s}", v, S[("0.100", "Sp")][s].mean(), 6e-5)

    print("\n== R2 mechanism: blade streamwise force at the edge-on positions (relative change, %, and 2u)")
    for lam, lo, hi, a, rel, tu in (("0.100", 80, 100, "Ks400", 50.0, 1.3), ("0.120", 80, 100, "Ks400", 47.7, 1.7),
                                    ("0.100", 80, 100, "Ks100", 7.5, 1.6), ("0.120", 80, 100, "Ks100", 3.7, 2.0),
                                    ("0.100", 260, 280, "Ks400", 0.7, 3.8), ("0.120", 260, 280, "Ks400", 1.9, 3.7),
                                    ("0.100", 80, 100, "Sp", 20.3, 1.7), ("0.100", 260, 280, "Sp", 15.4, 5.3)):
        x, y = edge_force(long[(lam, a)], lo, hi), edge_force(long[(lam, "Ks0")], lo, hi)
        say(f"blade C_x, theta {lo}-{hi}, {lam}, {a} vs Ks0 (%)", rel, 100 * (x.mean() / y.mean() - 1), 0.06)
        say(f"  2u (%)", tu, 100 * math.hypot(two_u(x), two_u(y)) / y.mean(), 0.06)
    s2 = {}
    with open(S2) as fh:
        hdr = fh.readline().strip().split(",")
        for ln in fh:
            p = ln.strip().split(",")
            s2[p[0]] = dict(zip(hdr, p))
    cd = {k: float(s2[f"a090.0_U23.0_SST_wf_Ks{k}_Tu1.0_Co2.5n2"]["Cd_mean"]) for k in (0, 100, 400)}
    say("Stage 2 alpha 90 Cd, Ks 400 vs Ks 0 (%)", 45.4, 100 * (cd[400] / cd[0] - 1), 0.06)
    say("Stage 2 alpha 90 Cd, Ks 100 vs Ks 0 (%)", 4.8, 100 * (cd[100] / cd[0] - 1), 0.06)

    print("\n== mesh check and zero-torque lambda, 23 m/s (3-revolution windows; sigma_rev 0.006745 pooled)")
    sig = 0.006745
    tab = {}
    with open(REPO / "cfd/rotor2d/results/rotor_cp.csv") as fh:
        hdr = fh.readline().strip().split(",")
        for ln in fh:
            p = ln.strip().split(",")
            tab[p[0]] = dict(zip(hdr, p))
    cq = lambda n: float(tab[n]["CQ_mean"])
    c10 = {l: cq(f"A_rot_U23.0_lam0.100_SST_{l}_senseCCW_rev6") for l in ("coarse", "medium", "fine")}
    c15 = {l: cq(f"A_rot_U23.0_lam0.150_SST_{l}_senseCCW") for l in ("coarse", "medium", "fine")}
    co2 = cq("A_rot_U23.0_lam0.150_SST_medium_senseCCW_Co2n2")
    tud = 2 * sig * math.sqrt(2 / 3)
    say("2u of a 3-revolution difference", 0.0110, tud, 6e-5)
    say("lambda 0.10 fine - medium", 0.0095, c10["fine"] - c10["medium"], 6e-5)
    say("lambda 0.10 medium - coarse", 0.0021, c10["medium"] - c10["coarse"], 6e-5)
    say("lambda 0.10 fine - coarse", 0.0116, c10["fine"] - c10["coarse"], 6e-5)
    say("lambda 0.15 medium - coarse", 0.0187, c15["medium"] - c15["coarse"], 6e-5)
    say("lambda 0.15 medium - fine", 0.0150, c15["medium"] - c15["fine"], 6e-5)
    say("lambda 0.15 medium maxCo 2 - fine", 0.0083, co2 - c15["fine"], 6e-5)
    say("lambda 0.15 medium maxCo 2 - coarse", 0.0119, co2 - c15["coarse"], 6e-5)

    def lam0(l1, q1, l2, q2, u):
        x = l1 + q1 * (l2 - l1) / (q1 - q2)
        return x, 2 * u * (l2 - l1) * math.hypot(q2, q1) / (q1 - q2) ** 2
    u3 = sig / math.sqrt(3)
    for lvl, v, tu in (("coarse", 0.1265, 0.0106), ("fine", 0.1374, 0.0090)):
        x, t2 = lam0(0.10, c10[lvl], 0.15, c15[lvl], u3)
        say(f"zero-torque lambda {lvl}", v, x, 6e-5)
        say(f"  2u", tu, t2, 6e-5)
        say(f"  shortfall below the rig band (0.1582) beyond 2u", 0.0, max(0.0, x + t2 - 0.1582), 0.0)
    x, t2 = lam0(0.15, c15["medium"], 0.20, cq("A_rot_U23.0_lam0.200_SST_medium_senseCCW"), u3)
    say("zero-torque lambda medium", 0.1585, x, 6e-5)
    say("  2u", 0.0087, t2, 6e-5)
    print(f"\n{NOK[0]} OK, {NCHECK[0]} CHECK")


if __name__ == "__main__":
    main()
