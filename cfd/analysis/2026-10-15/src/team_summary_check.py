#!/usr/bin/env python3
"""Independent check of every number in cfd/analysis/2026-10-15/TEAM_SUMMARY.md (19 Oct 2026 review),
plus the UPDATE.md numbers that the review relied on or corrected.

    nice -n 10 python3 cfd/analysis/2026-10-15/src/team_summary_check.py --logs   # first run: parses the
                                                                                  # 49 GB of section solver logs
    nice -n 10 python3 cfd/analysis/2026-10-15/src/team_summary_check.py          # later runs: log cache (~1 min)

Shares no code with the analysis scripts or the other check scripts: it imports nothing from src/ or
cfd/post/ and reads only raw inputs (read only):
  cfd/section2d/results/section_polars.csv, cfd/stage2/results/stage2_polars.csv,
  cfd/rotor2d/results/rotor_cp.csv, rotor_static.csv               the result tables
  cfd/section2d/runs/<case>/{case.json, results.json, mesh_info.json, log.pimpleFoam,
      postProcessing/forceCoeffs1/<t>/coefficient.dat}           (also the Unity repeat and the restarts)
  cfd/stage2/runs/<case>/{case.json, postProcessing/forceCoeffs1/<t>/coefficient.dat}
  cfd/rotor2d/runs/<case>/{case.json, mesh_info.json, postProcessing/forces{Rotor,Blade1..3}/0/*.dat}
  cfd/analysis/2026-10-13/data/*.csv                             the 13 Oct tables (which cases are new)
  reports/roughness_2026-09/build/derived/{comparisons,rotor_by_wind_speed}.csv,
      build/tacho/derived/rotor_speed_by_dwell.csv                measured gains, rotor speed, light-load lambda
  cfd/docs/ROUGHNESS_KS.md                                        the Ks mappings (quoted text)
Writes only ../out/team_summary_check_logs.csv (cache of the log pass).

Output, one line per number: OK (reproduced at the quoted precision), CHECK (not reproduced; the review
fixed the document or explains why not), INFO (used by the review, not quoted as such).

Definitions, re-implemented from the documents (TEAM_SUMMARY.md, UPDATE.md 'New terms', 13 Oct RESULTS.md
section 1.3, rotor2d/README.md 'Conventions'), not from the analysis code:
  section: t* = t U/c, c = 48 mm; window 50-150 c/U (Stage 2 at maxCo 5: 30-80); drift = mean of the second
  half of the window minus the first; noise of a change = sum of |drift| of the runs involved; jump = |dCd|
  > 0.5 between consecutive samples, whose 1-c/U interval is left out of the 'without jumps' values; usable =
  at least half the window c/U free of jumps; resolved = |change| > noise with and without the jump
  intervals, both runs usable; residual signature = more than half of the window's time steps start their
  first pressure solve with an initial residual above 0.05.
  13 Oct flag: u_Co/U = maxCo ds_corner / (dt_mean U) > 5, ds_corner from each case's mesh_info.json; Stage 2:
  mean dt (in c/U) at least 1.9 times below its family median together with a 13 Oct symptom.
  rotor: C_Q = s M_z / dz / (0.5 rho U^2 2R R); revolution k = [k, k+1) T_rev; u = s_rev / sqrt(n); 2u of a
  difference = 2 sqrt(u_a^2 + u_b^2); blade k sits at theta = Omega t + 120 (k - 1) deg (0 = upwind).
"""
import argparse
import glob
import json
import math
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                       # cfd/analysis/2026-10-15
REPO = ROOT.parents[2]                   # windtunnel-control
CFD = REPO / "cfd"
S1, S2, RO = CFD / "section2d", CFD / "stage2", CFD / "rotor2d"
OLD = CFD / "analysis" / "2026-10-13" / "data"
REP = REPO / "reports" / "roughness_2026-09" / "build"
LOG_CACHE = ROOT / "out" / "team_summary_check_logs.csv"
C = 0.048
COUNT = {"OK": 0, "CHECK": 0, "INFO": 0}
UNITY_REPEAT = "_unity_a000.0_U23.0_SST_medium_Tu1.0"
RESTART_A, RESTART_B = "_hyst_Co5to2p5_a000", "_hyst_Co2p5to5_a000"


# ============================================================================================ printing
def emit(tag, label, quoted, got):
    COUNT[tag] += 1
    print(f"{tag:5s}  {label}: quoted {quoted}; computed {got}")


def near(label, quoted, got, tol, fmt="{:.4g}"):
    """OK when |got - quoted| <= tol (normally half a unit of the quoted last digit)."""
    ok = got is not None and not (isinstance(got, float) and math.isnan(got)) and abs(got - quoted) <= tol + 1e-12
    emit("OK" if ok else "CHECK", label, quoted, fmt.format(got))
    return ok


def rng(label, quoted, lo, hi, tol, fmt="{:.4g}"):
    """A quoted range lo-hi (quoted is a 2-tuple)."""
    ok = abs(lo - quoted[0]) <= tol + 1e-12 and abs(hi - quoted[1]) <= tol + 1e-12
    emit("OK" if ok else "CHECK", label, f"{quoted[0]}-{quoted[1]}", f"{fmt.format(lo)}-{fmt.format(hi)}")
    return ok


def same(label, quoted, got):
    emit("OK" if quoted == got else "CHECK", label, quoted, got)
    return quoted == got


def info(label, got):
    emit("INFO", label, "-", got)


def pct(a, b):
    return 100.0 * (a - b) / abs(b)


def find_key(d, key):
    if isinstance(d, dict):
        if key in d:
            return d[key]
        for v in d.values():
            r = find_key(v, key)
            if r is not None:
                return r
    return None


# ============================================================================================ section-type histories
def coeff_history(run_dir):
    """(t*, Cd, Cl) from forceCoeffs1/<t>/coefficient.dat; restarts joined (a later start time wins)."""
    cj = json.loads((run_dir / "case.json").read_text())
    U = float(cj["Uinf"])
    files = sorted(glob.glob(str(run_dir / "postProcessing" / "forceCoeffs1" / "*" / "coefficient.dat")),
                   key=lambda p: float(Path(p).parent.name))
    blocks = []
    for f in files:
        with open(f) as fh:
            hdr = [ln for ln in fh if ln.startswith("# Time")][0][1:].split()
        a = np.loadtxt(f, comments="#")
        a = a.reshape(-1, len(hdr)) if a.ndim == 1 else a
        blocks.append(a[:, [hdr.index("Time"), hdr.index("Cd"), hdr.index("Cl")]])
    keep = []
    for i, b in enumerate(blocks):
        if i + 1 < len(blocks):
            b = b[b[:, 0] < blocks[i + 1][0, 0] - 1e-12]
        keep.append(b)
    a = np.vstack(keep)
    return a[:, 0] * U / C, a[:, 1], a[:, 2]


def jump_intervals(t, cd, w0, w1, lim=0.5):
    """1-c/U intervals [k, k+1) inside the window that hold a jump (the interval of the later sample)."""
    d = np.abs(np.diff(cd))
    ks = np.floor(t[1:][d > lim] + 1e-9).astype(int)
    return {int(k) for k in ks if w0 - 1e-9 <= k < w1 - 1e-9}


def window_stats(t, cd, cl, w0, w1, drop=()):
    m = (t >= w0 - 1e-6) & (t <= w1 + 1e-6)
    if drop:
        k = np.floor(t + 1e-9).astype(int)
        k[np.isclose(t, w1, atol=1e-6)] = int(round(w1)) - 1
        m &= ~np.isin(k, sorted(drop))
    mid = 0.5 * (w0 + w1)
    h1, h2 = m & (t < mid), m & (t >= mid)

    def mean(y, k):
        return float(y[k].mean()) if k.any() else float("nan")      # all samples dropped: flagged runs only
    return dict(Cd=mean(cd, m), drift=mean(cd, h2) - mean(cd, h1), Cl=mean(cl, m), Cl_drift=mean(cl, h2) - mean(cl, h1))


class Runs:
    """Window values of section-type runs (Stage 1 and Stage 2), with and without jump intervals."""

    def __init__(self, root, tab, logs=None):
        self.root, self.tab, self.logs, self.cache = root, tab.set_index("name"), logs or {}, {}

    def hist(self, nm):
        if nm not in self.cache:
            self.cache[nm] = coeff_history(self.root / nm)
        return self.cache[nm]

    def win(self, nm):
        r = self.tab.loc[nm]
        return float(r.avg_from_conv), float(r.avg_to_conv)

    def run(self, nm, w=None):
        t, cd, cl = self.hist(nm)
        w0, w1 = w or self.win(nm)
        jb = jump_intervals(t, cd, w0, w1)
        a = window_stats(t, cd, cl, w0, w1)
        b = window_stats(t, cd, cl, w0, w1, drop=jb) if jb else a
        return dict(all=a, nj=b, jumps=len(jb), usable=len(jb) <= 0.5 * (w1 - w0),
                    pres=self.logs.get(nm, float("nan")), name=nm)


def lift_cycles(t, cl, dt=0.02, min_p2p=0.003):
    """(time, peak-to-peak) of each cycle of a 1-c/U running mean of Cl (maximum to the next minimum)."""
    tu = np.arange(t[0], t[-1], dt)
    y = np.interp(tu, t, cl)
    n = int(round(1.0 / dt))
    c = np.concatenate([[0.0], np.cumsum(y)])
    rm = (c[n:] - c[:-n]) / n
    tm = tu[:len(rm)] + (n - 1) * dt / 2
    imax = np.where((rm[1:-1] > rm[:-2]) & (rm[1:-1] >= rm[2:]))[0] + 1
    imin = np.where((rm[1:-1] < rm[:-2]) & (rm[1:-1] <= rm[2:]))[0] + 1
    out = []
    for i in imax:
        nx = imin[imin > i]
        if nx.size and rm[i] - rm[nx[0]] >= min_p2p:
            out.append((float(tm[i]), float(rm[i] - rm[nx[0]])))
    return out


def compare(A, B):
    """Change of run A against run B (dicts from Runs.run), the 'resolved' rule of UPDATE.md."""
    d = A["all"]["Cd"] - B["all"]["Cd"]
    nz = abs(A["all"]["drift"]) + abs(B["all"]["drift"])
    dn = A["nj"]["Cd"] - B["nj"]["Cd"]
    nzn = abs(A["nj"]["drift"]) + abs(B["nj"]["drift"])
    res = abs(d) > nz and abs(dn) > nzn and A["usable"] and B["usable"]
    return dict(d=d, pct=pct(A["all"]["Cd"], B["all"]["Cd"]), noise=nz, ratio=abs(d) / nz, d_nj=dn, noise_nj=nzn,
                resolved=res, jumps_or_sig=(A["jumps"] > 0 or B["jumps"] > 0 or A["pres"] > 0.5 or B["pres"] > 0.5))


# ============================================================================================ logs
def log_pass(tab, build):
    names = list(tab["name"]) + [UNITY_REPEAT]
    if LOG_CACHE.exists() and not build:
        c = pd.read_csv(LOG_CACHE)
        return c
    rows = []
    for i, nm in enumerate(names):
        d = S1 / "runs" / nm
        U = float(json.loads((d / "case.json").read_text())["Uinf"])
        cmd = (f"LC_ALL=C grep -E '^(Time = |GAMG:  Solving for p)' '{d / 'log.pimpleFoam'}' | LC_ALL=C awk "
               "'/^Time = /{t=$3; f=1; next} f==1 {i=index($0,\"Initial residual = \"); s=substr($0,i+19); "
               "j=index(s,\",\"); print t, substr(s,1,j-1); f=0}'")
        txt = subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout
        a = np.array([ln.split() for ln in txt.splitlines() if ln.strip()], float)
        ts = a[:, 0] * U / C
        m = (ts >= 50 - 1e-6) & (ts <= 150 + 1e-6)
        rows.append(dict(name=nm, steps=len(a), win_steps=int(m.sum()),
                         pres_share=float(np.mean(a[m, 1] > 0.05)) if m.any() else float("nan"),
                         pres_median=float(np.median(a[m, 1])) if m.any() else float("nan")))
        print(f"  log {i + 1}/{len(names)} {nm}: {len(a)} steps, share {rows[-1]['pres_share']:.3f}", flush=True)
    c = pd.DataFrame(rows)
    c.to_csv(LOG_CACHE, index=False, float_format="%.6g")
    return c


# ============================================================================================ rotor
class Rotor:
    def __init__(self):
        self.tab = pd.read_csv(RO / "results" / "rotor_cp.csv").set_index("name")
        self.cache = {}

    def case(self, nm):
        return json.loads((RO / "runs" / nm / "case.json").read_text())

    def load(self, nm):
        if nm in self.cache:
            return self.cache[nm]
        cj = self.case(nm)
        s, U, R, dz, rho = float(cj["sense"]), cj["Uinf"], cj["R"], cj["dz"], cj["rhoInf"]
        q = 0.5 * rho * U * U * 2 * R
        pp = RO / "runs" / nm / "postProcessing"
        m = np.loadtxt(pp / "forcesRotor" / "0" / "moment.dat", comments="#")
        t = m[:, 0]
        out = dict(t=t, cq=s * m[:, 3] / dz / (q * R), T=cj["Trev"], Om=cj["Omega"], nrev=int(cj["nRev"]),
                   navg=int(cj["nAvgRev"]), theta0=float(cj.get("thetaDeg", 0.0)), blades=[])
        for k in (1, 2, 3):
            mb = np.loadtxt(pp / f"forcesBlade{k}" / "0" / "moment.dat", comments="#")
            fb = np.loadtxt(pp / f"forcesBlade{k}" / "0" / "force.dat", comments="#")
            if len(mb) != len(t) or not np.allclose(mb[:, 0], t):
                raise SystemExit(f"{nm}: blade {k} samples differ from the rotor's")
            out["blades"].append(dict(cq=s * mb[:, 3] / dz / (q * R), cx=fb[:, 1] / dz / q,
                                      th=(np.degrees(cj["Omega"] * t) + out["theta0"] + 120.0 * (k - 1)) % 360.0))
        out["rev"] = np.floor(t / out["T"] + 1e-9).astype(int)
        self.cache[nm] = out
        return out

    def wmean_by_rev(self, d, y):
        """exact mean of the piecewise-linear interpolant of y over each averaged revolution."""
        t, T = d["t"], d["T"]
        out = []
        for k in range(d["nrev"] - d["navg"], d["nrev"]):
            a, b = k * T, min((k + 1) * T, t[-1])
            m = (t > a) & (t < b)
            tt = np.concatenate([[a], t[m], [b]])
            yy = np.concatenate([[np.interp(a, t, y)], y[m], [np.interp(b, t, y)]])
            out.append(np.sum(0.5 * (yy[1:] + yy[:-1]) * np.diff(tt)) / (b - a))
        return np.array(out)

    def fine(self, d, per_rev=3600):
        """uniform midpoint resampling of the averaged revolutions: (rev index, theta and series per blade)."""
        if "fine" not in d:
            k0 = d["nrev"] - d["navg"]
            n = d["navg"] * per_rev
            tt = k0 * d["T"] + (np.arange(n) + 0.5) * d["T"] / per_rev
            rev = np.arange(n) // per_rev
            bl = []
            for k, b in enumerate(d["blades"]):
                th = (np.degrees(d["Om"] * tt) + d["theta0"] + 120.0 * k) % 360.0
                bl.append(dict(th=th, cq=np.interp(tt, d["t"], b["cq"]), cx=np.interp(tt, d["t"], b["cx"])))
            d["fine"] = (rev, bl, per_rev)
        return d["fine"]

    def revs(self, nm):
        d = self.load(nm)
        return self.wmean_by_rev(d, d["cq"])

    def stat(self, nm):
        r = self.revs(nm)
        return dict(CQ=r.mean(), s=r.std(ddof=1), n=len(r), u=r.std(ddof=1) / math.sqrt(len(r)))

    def sector_per_rev(self, nm, lo, hi, what="cq"):
        """per averaged revolution: time mean of sum over blades of (what) while the blade is in [lo, hi)."""
        rev, bl, per = self.fine(self.load(nm))
        acc = np.zeros(self.load(nm)["navg"])
        for b in bl:
            th = b["th"]
            m = ((th >= lo) | (th < hi)) if lo > hi else ((th >= lo) & (th < hi))
            acc += np.bincount(rev[m], weights=b[what][m], minlength=len(acc)) / per
        return acc

    def force_in_band(self, nm, lo, hi):
        """per averaged revolution: mean streamwise blade force coefficient while a blade is in [lo, hi)."""
        rev, bl, per = self.fine(self.load(nm))
        n = self.load(nm)["navg"]
        sy, sn = np.zeros(n), np.zeros(n)
        for b in bl:
            m = (b["th"] >= lo) & (b["th"] < hi)
            sy += np.bincount(rev[m], weights=b["cx"][m], minlength=n)
            sn += np.bincount(rev[m], minlength=n)
        return sy / sn


def diff2u(a, b):
    return a.mean() - b.mean(), 2 * math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))


def pooled_sigma(R, names):
    ss, dof = 0.0, 0
    for nm in names:
        r = R.revs(nm)
        ss += ((r - r.mean()) ** 2).sum()
        dof += len(r) - 1
    return math.sqrt(ss / dof), dof


def lam0(lams, cqs, us):
    """zero crossing by linear interpolation between the last positive and the next point; 2u by propagation."""
    for i in range(len(lams) - 1):
        if cqs[i] > 0 >= cqs[i + 1]:
            la, lb, qa, qb, ua, ub = lams[i], lams[i + 1], cqs[i], cqs[i + 1], us[i], us[i + 1]
            x = la + (lb - la) * qa / (qa - qb)
            da = (lb - la) * (-qb) / (qa - qb) ** 2
            db = (lb - la) * qa / (qa - qb) ** 2
            return x, 2 * math.sqrt((da * ua) ** 2 + (db * ub) ** 2)
    return float("nan"), float("nan")


# ============================================================================================ checks
def check_counts():
    print("\n== Scope and case counts (TEAM_SUMMARY 'Scope', 'What was run')")
    s1 = pd.read_csv(S1 / "results" / "section_polars.csv")
    s2 = pd.read_csv(S2 / "results" / "stage2_polars.csv")
    rc = pd.read_csv(RO / "results" / "rotor_cp.csv")
    rs = pd.read_csv(RO / "results" / "rotor_static.csv")
    o1, o2 = (set(pd.read_csv(OLD / f)["name"]) for f in ("section_polars.csv", "stage2_polars.csv"))
    orc, ors = (set(pd.read_csv(OLD / f)["name"]) for f in ("rotor_cp.csv", "rotor_static.csv"))
    n1, n2 = (~s1.name.isin(o1)).sum(), (~s2.name.isin(o2)).sum()
    nr = (~rc.name.isin(orc)).sum() + (~rs.name.isin(ors)).sum()
    same("cases in total", 263, len(s1) + len(s2) + len(rc) + len(rs))
    same("cases of 13 Oct", 150, len(o1) + len(o2) + len(orc) + len(ors))
    same("new cases", 113, int(n1 + n2 + nr))
    same("Stage 1: 125 (51 + 74)", (125, 51, 74), (len(s1), len(s1) - int(n1), int(n1)))
    same("Stage 2: 69 (43 + 26)", (69, 43, 26), (len(s2), len(s2) - int(n2), int(n2)))
    same("Stage 3: 69 (56 + 13)", (69, 56, 13), (len(rc) + len(rs), len(rc) + len(rs) - int(nr), int(nr)))
    return s1, s2


def check_section(s1, logs, R1):
    print("\n== Stage 1: health, jumps, residual signature (headline 4; UPDATE 1)")
    s1 = s1.copy()
    old = set(pd.read_csv(OLD / "section_polars.csv")["name"])
    s1["new"] = ~s1.name.isin(old)
    s1["ds"] = [find_key(json.loads((S1 / "runs" / n / "mesh_info.json").read_text()), "ds_corner") for n in s1.name]
    s1["proxy"] = s1.maxCo * s1.ds / (s1.dt_mean_s * s1.U_ms)
    s1["flag"] = s1.proxy > 5
    new, fl = s1[s1.new], s1[s1.flag]
    same("new section runs flagged", 0, int(new.flag.sum()))
    rng("proxy of the new runs", (1.10, 4.46), new.proxy.min(), new.proxy.max(), 0.005, "{:.3f}")
    rng("proxy of the flagged runs", (6.27, 32.3), fl.proxy.min(), fl.proxy.max(), 0.05, "{:.3f}")
    same("flagged runs (all of 13 Oct)", (23, False), (len(fl), bool(fl.new.any())))
    sym = (s1.Cd_mean < 0) | (s1.Cd_std > s1.Cd_mean.abs()) | (s1.Cl_mean.abs() > 3) | (s1.yplus_max_mean > 2)
    s1["sym"] = sym
    key = ["alpha_deg", "U_ms", "model", "level", "Tu_body_pct"]
    cover, n_new_rerun = 0, 0
    for _, f in fl.iterrows():
        m = np.ones(len(s1), bool)
        for k in key:
            m &= (s1[k] == f[k]).to_numpy()
        h = s1[m & (s1.maxCo == 2.5) & ~s1.flag & ~s1.sym]
        cover += len(h) >= 1
        n_new_rerun += int(h.new.any())
    same("flagged configurations with a healthy maxCo-2.5 run without a 13 Oct symptom", 23, cover)
    same("... of which re-run since 13 Oct (review fix: 'What was run' said 23)", 22, n_new_rerun)
    hs = s1[~s1.flag]
    four = hs[hs.new & (hs.Cd_std > hs.Cd_mean.abs())]
    same("new healthy runs with Cd_std > |Cd_mean| (UPDATE 1)", 4, len(four))
    same("... all at 10.2 m/s, alpha 195-210", True,
         bool((four.U_ms == 10.2).all() and four.alpha_deg.between(195, 210).all()))
    # jumps
    J = {n: R1.run(n) for n in s1.name}
    s1["jumps"] = s1.name.map(lambda n: J[n]["jumps"])
    hs = s1[~s1.flag]
    same("healthy runs with jumps in the window (35 of 102)", (35, 102), (int((hs.jumps > 0).sum()), len(hs)))
    same("new runs with jumps (UPDATE: 25 of 74)", 25, int((s1.new & (s1.jumps > 0)).sum()))
    same("13 Oct healthy runs with jumps (10 of 28)", (10, 28),
         (int((~s1.new & ~s1.flag & (s1.jumps > 0)).sum()), int((~s1.new & ~s1.flag).sum())))
    nu = s1[s1.new & ~s1.name.map(lambda n: J[n]["usable"])]
    same("new runs not usable = LM Tu 0.5 %, 10.2 m/s, alpha 165-210 (UPDATE 1)",
         [(165, 10.2, "LM", 0.5), (180, 10.2, "LM", 0.5), (195, 10.2, "LM", 0.5), (210, 10.2, "LM", 0.5)],
         sorted(zip(nu.alpha_deg, nu.U_ms, nu.model, nu.Tu_body_pct)))
    # residual signature
    s1["pres"] = s1.name.map(lambda n: logs.get(n, float("nan")))
    sig_new = s1[s1.new & (s1.pres > 0.5)]
    same("new runs with the residual signature (UPDATE 1)", 15, len(sig_new))
    same("... all at 10.2-23 m/s and Tu <= 1 %", True,
         bool(sig_new.U_ms.le(23).all() and sig_new.Tu_body_pct.le(1).all()))
    same("flagged runs with the signature (UPDATE 'New terms': 22 of 23)", 22, int((fl.name.map(logs) > 0.5).sum()))
    return s1, J


def check_timestep(R1, J):
    print("\n== Stage 1: maxCo 2.5 -> 1.25 at alpha 180, alpha-0 states, machine (headline 4; UPDATE 2-3)")
    for model, q, qn in (("SST", -17.5, 5.6), ("LM", -14.8, 5.3)):
        a = J[f"a180.0_U23.0_{model}_medium_Tu1.0_Co1.25n2"]
        b = J[f"a180.0_U23.0_{model}_medium_Tu1.0_Co2.5n2"]
        c = compare(a, b)
        ta, tb = R1.tab.loc[a["name"]], R1.tab.loc[b["name"]]
        near(f"alpha 180 {model}: drag change maxCo 2.5 -> 1.25 (%)", q, c["pct"], 0.05, "{:.2f}")
        near(f"alpha 180 {model}: times its noise, table drifts (UPDATE)", qn,
             abs(ta.Cd_mean - tb.Cd_mean) / (abs(ta.Cd_drift) + abs(tb.Cd_drift)), 0.05, "{:.3f}")
        same(f"alpha 180 {model}: resolved", True, c["resolved"])
        t, cd, cl = R1.hist(a["name"])
        lastblocks = [cl[(t >= x) & (t < x + 10)].std() for x in range(0, 150, 10)]
        steady_from = next(x for x in range(0, 150, 10) if all(s < 1e-3 for s in lastblocks[x // 10:]))
        same(f"alpha 180 {model} maxCo 1.25: lift std < 0.001 from (c/U) (UPDATE: SST 90, LM 100)",
             90 if model == "SST" else 100, steady_from)
    for model, q in (("SST", 1.822), ("LM", 1.676)):
        t, cd, cl = R1.hist(f"a000.0_U23.0_{model}_medium_Tu1.0_Co1.25n2")
        l10 = cd[t >= t[-1] - 10 - 1e-9].mean()
        p10 = cd[(t >= t[-1] - 20 - 1e-9) & (t < t[-1] - 10 - 1e-9)].mean()
        near(f"alpha 0 {model} maxCo 1.25: Cd over the last 10 c/U (UPDATE)", q, l10, 0.0005, "{:.4f}")
        same("... low-drag (< 2.5) and still falling", True, bool(l10 < 2.5 and l10 < p10))
    t5, cd5, _ = R1.hist("a000.0_U23.0_LM_medium_Tu1.0")
    t1, cd1, _ = R1.hist("a000.0_U23.0_LM_medium_Tu1.0_Co1.25n2")
    l5, l1 = cd5[t5 >= t5[-1] - 10 - 1e-9].mean(), cd1[t1 >= t1[-1] - 10 - 1e-9].mean()
    near("LM alpha-0 low-drag value, maxCo 5 -> 1.25, last 10 c/U (UPDATE 3: -13.6 %)", -13.6, pct(l1, l5), 0.05,
         "{:.2f}")
    # Unity repeat
    rep = json.loads((S1 / "runs" / UNITY_REPEAT / "results.json").read_text())
    mac = R1.tab.loc["a000.0_U23.0_SST_medium_Tu1.0"]
    near("Unity repeat Cd (results.json)", 3.1894, rep["Cd_mean"], 5e-5, "{:.5f}")
    near("Mac run Cd (table)", 3.1905, float(mac.Cd_mean), 5e-5, "{:.5f}")
    tu, cdu, _ = coeff_history(S1 / "runs" / UNITY_REPEAT)
    tm, cdm, _ = R1.hist("a000.0_U23.0_SST_medium_Tu1.0")
    n = min(len(tu), len(tm))
    same("repeat and Mac sampled at the same times (within 0.002 c/U)", True,
         bool(len(tu) == len(tm) and np.allclose(tu, tm, atol=2e-3)))
    near("largest |dCd| repeat - Mac, sample by sample (UPDATE 3)", 0.038, float(np.abs(cdu[:n] - cdm[:n]).max()),
         0.0005, "{:.4f}")
    # restarts: Cd change against the parent's last 50 c/U
    for nm, parent, q in ((RESTART_A, "a000.0_U23.0_SST_medium_Tu1.0", 1.08),
                          (RESTART_B, "a000.0_U23.0_SST_medium_Tu1.0_Co2.5n2", 0.81)):
        tr, cdr, clr = coeff_history(S1 / "runs" / nm)
        tp, cdp, _ = R1.hist(parent)
        p50 = cdp[tp >= 100 - 1e-6].mean()
        got = {f"{w0}-210": pct(cdr[tr >= w0 - 1e-6].mean(), p50) for w0 in (150, 160, 180)}
        info(f"restart {nm}: Cd change against the parent's last 50 c/U (%) by restart window (UPDATE: {q:+.2f})",
             ", ".join(f"{k}: {v:+.2f}" for k, v in got.items()))
    tr, cdr, clr = coeff_history(S1 / "runs" / RESTART_B)
    cyc = lift_cycles(tr, clr)
    near("restart (b): lift-cycle amplitude, last over first cycle (UPDATE 3: 11-fold)", 11, cyc[-1][1] / cyc[0][1],
         0.5, "{:.1f}")
    h = len(cyc) // 2
    ef = [1 / np.polyfit([c[0] for c in part], np.log([c[1] for c in part]), 1)[0] for part in (cyc[:h + 1], cyc[h:])]
    info("restart (b): e-folding time of the lift-cycle amplitude, first and second half of the cycles (UPDATE 3: "
         "11, then 38 c/U)", f"{ef[0]:.0f}, {ef[1]:.0f} ({len(cyc)} cycles)")
    tr, cdr, clr = coeff_history(S1 / "runs" / RESTART_A)
    info("restart (a): Cd over 180-210 c/U (figure label 3.171) and Cl std over the last 10 c/U",
         f"{cdr[tr >= 180 - 1e-6].mean():.3f}, {clr[tr >= 200 - 1e-6].std():.3f}")


def check_transition(R1, J):
    print("\n== Stage 1: transition test (headline 3; UPDATE 5)")
    rows = []
    for U in (10.2, 23.0, 38.0):
        for a in (150, 165, 180, 195, 210):
            lm = J[f"a{a:05.1f}_U{U}_LM_medium_Tu1.0_Co2.5n2"]
            sst = J[f"a{a:05.1f}_U{U}_SST_medium_Tu1.0_Co2.5n2"]
            c = compare(lm, sst)
            rows.append(dict(U=U, a=a, **c))
    d = pd.DataFrame(rows)
    lo = d[d.U < 30]
    same("10.2 and 23 m/s: LM below SST in all 10 pairs", (10, 10), (int((lo.d < 0).sum()), len(lo)))
    rng("... changes (%)", (-10.7, -51.1), lo.pct.max(), lo.pct.min(), 0.05, "{:.2f}")
    same("... resolved (rule: with and without jumps, usable)", 9, int(lo.resolved.sum()))
    same("... each resolved pair with jumps or the signature in at least one run", True,
         bool(lo[lo.resolved].jumps_or_sig.all()))
    info("pairs at 10.2/23 m/s, % (ratio to noise, resolved)",
         "; ".join(f"{r.U:g}/{r.a}: {r.pct:+.1f} ({r.ratio:.1f}, {'R' if r.resolved else '-'})"
                   for r in lo.itertuples()))
    hi = d[d.U > 30]
    info("38 m/s pairs, % (resolved): 'the sign is mixed'",
         "; ".join(f"{r.a}: {r.pct:+.1f} ({'R' if r.resolved else '-'})" for r in hi.itertuples()))
    a180 = d[d.a == 180].set_index("U")
    for U, q in ((10.2, -20.3), (23.0, -11.5), (38.0, -0.45)):
        near(f"alpha 180, {U:g} m/s: LM against SST (%)", q, a180.loc[U, "pct"], 0.05 if U < 30 else 0.005, "{:.3f}")
    near("alpha 180, 38 m/s: change over its drift noise (UPDATE: 1.6)", 1.6, a180.loc[38.0, "ratio"], 0.05, "{:.2f}")
    c = compare(J["a180.0_U23.0_LM_medium_Tu1.0_Co1.25n2"], J["a180.0_U23.0_SST_medium_Tu1.0_Co1.25n2"])
    near("alpha 180, maxCo 1.25, 23 m/s: LM against SST (%)", -8.6, c["pct"], 0.05, "{:.2f}")
    tab = R1.tab
    for U, qcl in ((10.2, 112), (23.0, 81), (38.0, 4)):
        l, s = tab.loc[f"a180.0_U{U}_LM_medium_Tu1.0_Co2.5n2"], tab.loc[f"a180.0_U{U}_SST_medium_Tu1.0_Co2.5n2"]
        near(f"alpha 180 {U:g} m/s: |Cl| LM -> SST (%)", qcl, pct(abs(s.Cl_mean), abs(l.Cl_mean)), 0.5, "{:.1f}")
        near(f"alpha 180 {U:g} m/s: Cd LM -> SST, 'a trip raises' (%) (UPDATE: 25.5 / 13.0 / 0.45)",
             {10.2: 25.5, 23.0: 13.0, 38.0: 0.45}[U], pct(s.Cd_mean, l.Cd_mean), 0.05 if U < 30 else 0.005, "{:.3f}")
    l, s = tab.loc["a180.0_U23.0_LM_medium_Tu1.0_Co1.25n2"], tab.loc["a180.0_U23.0_SST_medium_Tu1.0_Co1.25n2"]
    near("alpha 180 maxCo 1.25: |Cl| LM -> SST (UPDATE: 36 %)", 36, pct(abs(s.Cl_mean), abs(l.Cl_mean)), 0.5, "{:.1f}")
    near("alpha 180 maxCo 1.25: Cd LM -> SST (UPDATE: 9.4 %)", 9.4, pct(s.Cd_mean, l.Cd_mean), 0.05, "{:.2f}")
    lm = {(U, tu): tab.loc[f"a180.0_U{U}_LM_medium_Tu{tu}_Co2.5n2"].Cd_mean for U in (10.2, 23.0, 38.0)
          for tu in (0.5, 1.0, 3.0)}
    near("LM alpha 180: Cd 23 -> 38 m/s (UPDATE: +20.5 %)", 20.5, pct(lm[(38.0, 1.0)], lm[(23.0, 1.0)]), 0.05, "{:.2f}")
    near("LM alpha 180, 23 m/s: Tu 1 -> 3 % (UPDATE: -17.0 %)", -17.0, pct(lm[(23.0, 3.0)], lm[(23.0, 1.0)]), 0.05,
         "{:.2f}")
    same("LM alpha 180: Cd falls with Tu at every speed (UPDATE)", True,
         all(lm[(U, 0.5)] > lm[(U, 1.0)] > lm[(U, 3.0)] for U in (10.2, 23.0, 38.0)))
    lmp = tab[(tab.model == "LM") & (tab.U_ms == 23.0) & (tab.Tu_body_pct == 1.0) & (tab.level == "medium")]
    lmp = lmp[lmp.maxCo.isin([2.5, 5.0])]
    best = {}
    for _, r in lmp.iterrows():
        prox = r.maxCo * 45e-6 / (r.dt_mean_s * r.U_ms)
        if prox > 5:
            continue
        best[int(r.alpha_deg)] = r
    same("LM polar 23 m/s Tu 1 %: healthy angles (UPDATE 4: all 24)", 24, len(best))
    co25 = sorted(a for a, r in best.items() if r.maxCo == 2.5)
    same("LM polar angles at maxCo 2.5 (UPDATE 4, review fix: 75-255, 285, 300, 330)",
         list(range(75, 256, 15)) + [285, 300, 330], co25)
    near("LM polar: convex-side drag peak at 165 (UPDATE 4: 1.590)", 1.590, float(best[165].Cd_mean), 0.0005, "{:.4f}")
    pr = min(float(r.Cd_pressure_mean / r.Cd_mean) for r in best.values())
    near("LM polar: pressure share of Cd, minimum (UPDATE 4: 95.3 %)", 95.3, 100 * pr, 0.05, "{:.2f}")
    h = tab[[(r.maxCo * find_key(json.loads((S1 / "runs" / n / "mesh_info.json").read_text()), "ds_corner")
              / (r.dt_mean_s * r.U_ms)) <= 5 for n, r in tab.iterrows()]]
    near("all healthy runs: pressure share of Cd, minimum (UPDATE 4: 95.3 %)", 95.3,
         100 * float((h.Cd_pressure_mean / h.Cd_mean).min()), 0.05, "{:.2f}")
    h018 = h[h.alpha_deg.isin([0, 180])]
    near("all healthy runs at alpha 0 and 180: pressure share, minimum (UPDATE 4: 98.8 %)", 98.8,
         100 * float((h018.Cd_pressure_mean / h018.Cd_mean).min()), 0.05, "{:.2f}")
    o13 = pd.read_csv(OLD / "section_polars.csv")
    o13 = o13[[(r.maxCo * {"coarse": 64e-6, "medium": 45e-6, "fine": 32e-6}[r.level] / (r.dt_mean_s * r.U_ms)) <= 5
               for r in o13.itertuples()]]
    near("13 Oct healthy runs (28): pressure share, minimum (13 Oct: 98.5 %)", 98.5,
         100 * float((o13.Cd_pressure_mean / o13.Cd_mean).min()), 0.05, "{:.2f}")
    same("... over 28 runs", 28, len(o13))
    near("LM polar at alpha 0 and 180: pressure share, minimum", 99.3,
         100 * min(float(best[a].Cd_pressure_mean / best[a].Cd_mean) for a in (0, 180)), 0.05, "{:.2f}")


def check_stage2(s1tab, logs):
    print("\n== Stage 2: drag difference, texture, fair comparisons (headlines 2-3; UPDATE 2, 6)")
    s2 = pd.read_csv(S2 / "results" / "stage2_polars.csv")
    old = set(pd.read_csv(OLD / "stage2_polars.csv")["name"])
    s2["new"] = ~s2.name.isin(old)
    R2 = Runs(S2 / "runs", s2)
    # health: family = wall, alpha, maxCo (and speed on the wf meshes); dt in c/U
    s2["dtc"] = s2.dt_mean_s * s2.U_ms / C
    fam = s2.wall + "|" + s2.alpha_deg.astype(str) + "|" + s2.maxCo.astype(str) + "|" + \
        np.where(s2.wall == "wf", s2.U_ms.astype(str), "")
    s2["ratio"] = s2.groupby(fam).dtc.transform("median") / s2.dtc
    ymax = s2[["yplus_blade_max", "yplus_bladeEnds_max"]].max(axis=1)
    sym = (s2.Cd_mean < 0) | (s2.Cd_std > s2.Cd_mean.abs()) | (s2.Cl_mean.abs() > 3) | ((s2.wall == "tex") & (ymax > 2))
    same("new Stage 2 runs flagged (dt anomaly with a symptom)", 0, int((s2.new & (s2.ratio >= 1.9) & sym).sum()))
    info("new Stage 2 runs: largest family-median/dt ratio; any symptom",
         f"{s2[s2.new].ratio.max():.2f}; {bool(sym[s2.new].any())}")
    jumpy = [n for n in s2.name if R2.run(n)["jumps"] > 0]
    info("Stage 2 runs with jumps in the window (UPDATE 1: only the smooth LM alpha-0 texture run at maxCo 2.5)",
         jumpy)
    # the 52 fair comparisons, rebuilt from the rules
    T = s2.set_index("name")

    def nm_wf(a, U, ks, co):
        return f"a{a:05.1f}_U{U}_SST_wf_Ks{ks}_Tu1.0" + ("_Co2.5n2" if co == 2.5 else "")

    def nm_tx(a, U, model, t, co):
        return f"a{a:05.1f}_U{U}_{model}_tex{t:.3f}_s1_Tu1.0" + ("_Co2.5n2" if co == 2.5 else "_N80A50")

    use_hist = [False]

    def val(nm):
        """table window mean and drift (the documents' source); histories for jumps (or, as a cross-check,
        for the means and drifts too)."""
        r = R2.run(nm)
        if use_hist[0]:
            return r["all"]["Cd"], r["all"]["drift"], r
        return float(T.loc[nm].Cd_mean), float(T.loc[nm].Cd_drift), r

    comps = []

    def add(fam_, q, a_names, b_names, sign):
        """q in Cd0, Cd180, D; a = case (list of 1 or 2 names), b = reference."""
        if not all(n in T.index for n in a_names + b_names):
            return
        va = [val(n) for n in a_names]
        vb = [val(n) for n in b_names]
        if q == "D":
            ca, cb = va[0][0] - va[1][0], vb[0][0] - vb[1][0]
        else:
            ca, cb = va[0][0], vb[0][0]
        noise = sum(abs(v[1]) for v in va + vb)
        jumps = any(v[2]["jumps"] > 0 for v in va + vb)
        ch = ca - cb
        comps.append(dict(fam=fam_, q=q, a=a_names[0], d=ch, pct=pct(ca, cb), noise=noise, res=abs(ch) > noise,
                          needed=(np.sign(ch) == sign), jumps=jumps))

    def build():
        comps.clear()
        for U, co, refs in ((10.2, 2.5, 0), (23.0, 2.5, 0), (23.0, 5.0, 50), (38.0, 2.5, 0), (38.0, 5.0, 0)):
            for ks in (50, 100, 200, 400):
                if ks > refs:
                    add("wf", "Cd0", [nm_wf(0, U, ks, co)], [nm_wf(0, U, refs, co)], +1)
        for co in (2.5, 5.0):
            for ks in (50, 100, 200, 400):
                add("wf", "Cd180", [nm_wf(180, 23.0, ks, co)], [nm_wf(180, 23.0, 0, co)], -1)
        for co, ref in ((2.5, 0), (5.0, 50)):
            for ks in (50, 100, 200, 400):
                if ks > ref:
                    add("wf", "D", [nm_wf(0, 23.0, ks, co), nm_wf(180, 23.0, ks, co)],
                        [nm_wf(0, 23.0, ref, co), nm_wf(180, 23.0, ref, co)], +1)
        for model in ("SST", "LM"):
            for co in (5.0, 2.5):
                for t in (0.05, 0.10, 0.20):
                    if co == 2.5 and model == "LM":
                        continue                          # its smooth alpha-0 run changes state in the window
                    add("tex", "D", [nm_tx(0, 23.0, model, t, co), nm_tx(180, 23.0, model, t, co)],
                        [nm_tx(0, 23.0, model, 0, co), nm_tx(180, 23.0, model, 0, co)], +1)
                    add("tex", "Cd0", [nm_tx(0, 23.0, model, t, co)], [nm_tx(0, 23.0, model, 0, co)], +1)
                for t in (0.05, 0.10, 0.20):
                    add("tex", "Cd180", [nm_tx(180, 23.0, model, t, co)], [nm_tx(180, 23.0, model, 0, co)], -1)
        for U in (18.8, 20.9, 25.2):
            add("tex", "Cd180", [nm_tx(180, U, "LM", 0.2, 2.5)], [nm_tx(180, U, "LM", 0, 2.5)], -1)
        return pd.DataFrame(list(comps))

    use_hist[0] = True
    BH = build()
    info("the same 52 from the force histories (0.02-c/U samples): resolved; needed sign; resolved with it",
         f"{int(BH.res.sum())}; {int(BH.needed.sum())}; {int((BH.res & BH.needed).sum())}")
    use_hist[0] = False
    B = build()
    same("fair comparisons", 52, len(B))
    same("resolved", 21, int(B.res.sum()))
    same("with the sign the gains need", 8, int(B.needed.sum()))
    same("resolved with the needed sign", 0, int((B.res & B.needed).sum()))
    same("comparisons with a jump in any run", 0, int(B.jumps.sum()))
    # quoted values
    def one(fam_, q, a):
        r = B[(B.fam == fam_) & (B.q == q) & (B.a == a)]
        return r.iloc[0]
    d400 = one("wf", "D", nm_wf(0, 23.0, 400, 2.5))
    d200 = one("wf", "D", nm_wf(0, 23.0, 200, 2.5))
    near("D, both angles maxCo 2.5, Ks 400 um (%)", -18.6, d400.pct, 0.05, "{:.3f}")
    near("... times its noise (UPDATE: 1.76)", 1.76, abs(d400.d) / d400.noise, 0.005, "{:.3f}")
    near("D, Ks 200 um (UPDATE: -8.61 %)", -8.61, d200.pct, 0.005, "{:.3f}")
    near("... times its noise (UPDATE: 1.01)", 1.01, abs(d200.d) / d200.noise, 0.005, "{:.3f}")
    Tt = s2.set_index("name")
    d13 = (Tt.loc[nm_wf(0, 23.0, 400, 2.5)].Cd_mean - Tt.loc[nm_wf(180, 23.0, 400, 5.0)].Cd_mean)
    d13r = (Tt.loc[nm_wf(0, 23.0, 0, 2.5)].Cd_mean - Tt.loc[nm_wf(180, 23.0, 0, 5.0)].Cd_mean)
    near("13 Oct mixed set (alpha 0 maxCo 2.5, alpha 180 maxCo 5): D at Ks 400 (%)", -19.3, pct(d13, d13r), 0.05,
         "{:.3f}")
    sst = one("tex", "Cd180", nm_tx(180, 23.0, "SST", 0.2, 2.5))
    lm = one("tex", "Cd180", nm_tx(180, 23.0, "LM", 0.2, 2.5))
    near("SST texture t 0.20, alpha 180, maxCo 2.5 (%)", 13.6, sst.pct, 0.05, "{:.3f}")
    same("... resolved", True, bool(sst.res))
    near("LM texture t 0.20, alpha 180, maxCo 2.5 (%)", 8.6, lm.pct, 0.05, "{:.3f}")
    lm1 = one("tex", "Cd180", nm_tx(180, 23.0, "LM", 0.1, 2.5))
    near("LM texture t 0.10, alpha 180, maxCo 2.5 (UPDATE: +15.28 %)", 15.28, lm1.pct, 0.005, "{:.3f}")
    s5 = one("tex", "Cd180", nm_tx(180, 23.0, "SST", 0.2, 5.0))
    near("SST texture t 0.20, alpha 180, maxCo 5 (UPDATE: +13.68 %)", 13.68, s5.pct, 0.005, "{:.3f}")
    # the same at maxCo 2.5 over the maxCo-5 window 30-80 c/U (fair cross-time-step comparison)
    a = R2.run(nm_tx(180, 23.0, "SST", 0.2, 2.5), (30.0, 80.0))["all"]["Cd"]
    b = R2.run(nm_tx(180, 23.0, "SST", 0, 2.5), (30.0, 80.0))["all"]["Cd"]
    near("SST texture effect at maxCo 2.5 over 30-80 c/U, the maxCo-5 window (UPDATE 2, review fix)", 15.48,
         pct(a, b), 0.005, "{:.3f}")
    for t_, nmm, qv in ((0, "smooth", -17.5), (0.2, "t 0.20", -16.2)):
        x5 = Tt.loc[nm_tx(180, 23.0, "SST", t_, 5.0)].Cd_mean
        x25 = R2.run(nm_tx(180, 23.0, "SST", t_, 2.5), (30.0, 80.0))["all"]["Cd"]
        x25o = Tt.loc[nm_tx(180, 23.0, "SST", t_, 2.5)].Cd_mean
        near(f"SST alpha 180 {nmm}: maxCo 5 -> 2.5 over 30-80 c/U (UPDATE 2, review fix; was 'about 18.6 %', "
             f"own windows {pct(x25o, x5):+.2f} %)", qv, pct(x25, x5), 0.05, "{:.2f}")
    for t_, qv in ((0.1, 14.83), (0.2, 9.22)):
        a = R2.run(nm_tx(180, 23.0, "LM", t_, 2.5), (30.0, 80.0))["all"]["Cd"]
        b = R2.run(nm_tx(180, 23.0, "LM", 0, 2.5), (30.0, 80.0))["all"]["Cd"]
        near(f"LM texture t {t_}, maxCo 2.5, over 30-80 c/U (UPDATE 6, review addition)", qv, pct(a, b), 0.005,
             "{:.3f}")
    same_w, own_w = [], []
    for model, t_ in (("LM", 0.1), ("LM", 0.2), ("SST", 0.2)):     # SST t 0 at maxCo 2.5 is high-drag to 35 c/U
        x5 = Tt.loc[nm_tx(0, 23.0, model, t_, 5.0)].Cd_mean
        same_w.append(pct(R2.run(nm_tx(0, 23.0, model, t_, 2.5), (30.0, 80.0))["all"]["Cd"], x5))
        own_w.append(pct(Tt.loc[nm_tx(0, 23.0, model, t_, 2.5)].Cd_mean, x5))
    rng("low-drag alpha-0 texture levels, maxCo 5 -> 2.5, fall over 30-80 c/U (UPDATE 2, review fix)", (1.0, 5.6),
        -max(same_w), -min(same_w), 0.05, "{:.2f}")
    rng("... and comparing each run's own window (UPDATE 2: 6.3-9.1 %)", (6.3, 9.1), -max(own_w), -min(own_w), 0.05,
        "{:.2f}")
    x5 = Tt.loc[nm_tx(180, 23.0, "LM", 0, 5.0)].Cd_mean
    x25 = R2.run(nm_tx(180, 23.0, "LM", 0, 2.5), (30.0, 80.0))["all"]["Cd"]
    near("smooth LM alpha 180, maxCo 5 -> 2.5 over 30-80 c/U (UPDATE: -13.84 %)", -13.84, pct(x25, x5), 0.005, "{:.3f}")
    spd = {U: one("tex", "Cd180", nm_tx(180, U, "LM", 0.2, 2.5)) for U in (18.8, 20.9, 25.2)}
    spd[23.0] = lm
    near("LM speed bracket, 18.8 m/s (%)", 0.04, spd[18.8].pct, 0.005, "{:.3f}")
    same("... 18.8 m/s not resolved, 20.9/23/25.2 resolved", (False, True, True, True),
         tuple(bool(spd[U].res) for U in (18.8, 20.9, 23.0, 25.2)))
    rng("LM speed bracket, 20.9-25.2 m/s (%)", (7.3, 8.6), min(spd[U].pct for U in (20.9, 23.0, 25.2)),
        max(spd[U].pct for U in (20.9, 23.0, 25.2)), 0.05, "{:.3f}")
    s0 = {U: Tt.loc[nm_tx(180, U, "LM", 0, 2.5)].Cd_mean for U in (18.8, 20.9, 23.0, 25.2)}
    s2_ = {U: Tt.loc[nm_tx(180, U, "LM", 0.2, 2.5)].Cd_mean for U in (18.8, 20.9, 23.0, 25.2)}
    near("smooth LM alpha 180: 18.8 -> 20.9 m/s (UPDATE: -6.50 %)", -6.50, pct(s0[20.9], s0[18.8]), 0.005, "{:.3f}")
    near("textured LM alpha 180: spread over 18.8-25.2 m/s (UPDATE: 1.60 %)", 1.60,
         100 * (max(s2_.values()) / min(s2_.values()) - 1), 0.005, "{:.3f}")
    # mesh comparison, Ks/y_P, y+
    tex0 = Tt.loc[nm_tx(180, 23.0, "SST", 0, 2.5)].Cd_mean
    med = s1tab.set_index("name").loc["a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2"].Cd_mean
    near("texture mesh smooth Cd(180) against the medium mesh, SST maxCo 2.5 (%)", -39, pct(tex0, med), 0.5, "{:.2f}")
    near("... SST 0.903", 0.903, tex0, 0.0005, "{:.4f}")
    near("... medium 1.479", 1.479, med, 0.0005, "{:.4f}")
    tex00 = Tt.loc[nm_tx(0, 23.0, "SST", 0, 2.5)].Cd_mean
    med0 = s1tab.set_index("name").loc["a000.0_U23.0_SST_medium_Tu1.0_Co2.5n2"].Cd_mean
    info("alpha 0, texture mesh against medium, SST maxCo 2.5 (UPDATE 6: 'within 0.5 %')", f"{pct(tex00, med0):+.3f} %")
    wf = s2[s2.wall == "wf"]
    rng("blade-mean y+ of the wall-function runs", (17, 49), wf.yplus_blade_mean.min(), wf.yplus_blade_mean.max(), 0.5,
        "{:.2f}")
    near("Stage 2 Ks/y_P maximum (the rotor's: below)", 0.92, float(s2.Ks_over_yP.max()), 0.015, "{:.3f}")
    # LM drift noise at alpha 180 (texture, maxCo 2.5): noise of each t-vs-0 pair in % of the reference
    lm25 = B[(B.fam == "tex") & (B.q == "Cd180") & B.a.str.contains("_LM_") & B.a.str.contains("Co2.5")]
    lmn = [100 * r.noise / Tt.loc[nm_tx(180, float(r.a.split("_U")[1].split("_")[0]), "LM", 0, 2.5)].Cd_mean
           for r in lm25.itertuples()]
    rng("LM alpha-180 drift noise, maxCo 2.5 (UPDATE 6: 3.9-5.1 % of Cd)", (3.9, 5.1), min(lmn), max(lmn), 0.05,
        "{:.2f}")
    # wall-function time-step check (UPDATE 2)
    eff = []
    for a in (90, 180):
        for ks in (50, 100, 200, 400):
            for q in ("Cd_mean", "Cl_mean"):
                e5 = pct(abs(Tt.loc[nm_wf(a, 23.0, ks, 5.0)][q]), abs(Tt.loc[nm_wf(a, 23.0, 0, 5.0)][q]))
                e25 = pct(abs(Tt.loc[nm_wf(a, 23.0, ks, 2.5)][q]), abs(Tt.loc[nm_wf(a, 23.0, 0, 2.5)][q]))
                eff.append((a, ks, q, e5, e25))
    E = pd.DataFrame(eff, columns=["a", "ks", "q", "e5", "e25"])
    same("alpha 90/180 wall functions: every effect keeps its sign at maxCo 2.5", True,
         bool((np.sign(E.e5) == np.sign(E.e25)).all()))
    Ed = E[E.q == "Cd_mean"]
    near("... Cd effects move by at most (pp) (UPDATE 2: 1.02)", 1.02, float((Ed.e25 - Ed.e5).abs().max()), 0.005,
         "{:.3f}")
    El = E[E.q == "Cl_mean"]
    near("... |Cl| effects move by at most (pp) (UPDATE 2, review addition: 2.87, alpha 90, Ks 400)", 2.87,
         float((El.e25 - El.e5).abs().max()), 0.005, "{:.3f}")
    same("... that maximum is at alpha 90, Ks 400", (90, 400),
         tuple(int(x) for x in El.loc[(El.e25 - El.e5).abs().idxmax(), ["a", "ks"]]))
    r90 = E[(E.a == 90) & (E.ks == 400) & (E.q == "Cd_mean")].iloc[0]
    near("alpha 90 wall function Ks 400 vs 0, maxCo 2.5 (headline 1: +45 %; UPDATE: +45.4 %)", 45.4, r90.e25, 0.05,
         "{:.2f}")
    r180 = E[(E.a == 180) & (E.ks == 400) & (E.q == "Cd_mean")].iloc[0]
    info("alpha 180 Ks 400: maxCo 5 -> 2.5 (UPDATE 2: +5.81 % to +5.50 %)", f"{r180.e5:+.2f} -> {r180.e25:+.2f}")
    return B


def check_rotor():
    print("\n== Stage 3: rough blades, torque budget, mesh, noise (headlines 1, 4, 5; UPDATE 7-8)")
    R = Rotor()
    tab = R.tab
    long = lambda lam, tag: f"A_rot_U23.0_lam{lam:.3f}_SST_medium{tag}_senseCCW_rev50a45"
    for lam in (0.10, 0.12):
        for tag in ("_Ks0", "_Ks100", "_Ks400", ""):
            nm = long(lam, tag)
            same(f"{nm}: 50 revolutions, last 45 averaged, 16 ranks",
                 (50, 45, 16), (int(tab.loc[nm].n_rev_done), int(tab.loc[nm].n_avg_rev), int(tab.loc[nm].nProcs)))
    st = {(lam, tag): R.stat(long(lam, tag)) for lam in (0.10, 0.12) for tag in ("_Ks0", "_Ks100", "_Ks400", "")}
    for lam in (0.10, 0.12):
        for tag in ("_Ks0", "_Ks100", "_Ks400", ""):
            nm = long(lam, tag)
            if abs(st[(lam, tag)]["CQ"] - tab.loc[nm].CQ_mean) > 2e-5:
                emit("CHECK", f"{nm}: revolution means reproduce the table C_Q", tab.loc[nm].CQ_mean,
                     st[(lam, tag)]["CQ"])
    q = {(0.10, "_Ks400"): (0.0051, 0.0028, 27), (0.12, "_Ks400"): (0.0058, 0.0028, 38),
         (0.10, "_Ks100"): (0.0014, 0.0027, None), (0.12, "_Ks100"): (-0.0029, 0.0032, None)}
    two_us = []
    for (lam, tag), (qd, qu, qp) in q.items():
        a, b = R.revs(long(lam, tag)), R.revs(long(lam, "_Ks0"))
        d, tu = diff2u(a, b)
        near(f"lambda {lam:.2f}: {tag[1:]} - Ks0, dC_Q", qd, d, 0.00005, "{:+.5f}")
        near(f"lambda {lam:.2f}: {tag[1:]} - Ks0, 2u", qu, tu, 0.00005, "{:.5f}")
        same(f"lambda {lam:.2f}: {tag[1:]} - Ks0 resolved at 2u", tag == "_Ks400", abs(d) > tu)
        if qp:
            near(f"lambda {lam:.2f}: {tag[1:]} - Ks0 (%)", qp, pct(a.mean(), b.mean()), 0.5, "{:.1f}")
            near(f"lambda {lam:.2f}: z = dC_Q / u (UPDATE: 3.7 / 4.1)", {0.10: 3.7, 0.12: 4.1}[lam], 2 * d / tu, 0.05,
                 "{:.2f}")
    for lam in (0.10, 0.12):
        for x, y in (("_Ks100", "_Ks0"), ("_Ks400", "_Ks0"), ("_Ks0", ""), ("_Ks100", ""), ("_Ks400", ""),
                     ("_Ks400", "_Ks100")):
            d, tu = diff2u(R.revs(long(lam, x)), R.revs(long(lam, y)))
            if y != "_Ks100":
                two_us.append(tu)
            if (x, y) == ("_Ks400", "_Ks100"):
                same(f"lambda {lam:.2f}: Ks400 - Ks100 resolved (UPDATE 7)", True, abs(d) > tu)
            if (x, y) == ("_Ks0", ""):
                same(f"lambda {lam:.2f}: Ks0 - Spalding not resolved (UPDATE 7)", False, abs(d) > tu)
    rng("2u of the rough-minus-smooth differences (10)", (0.0027, 0.0032), min(two_us), max(two_us), 0.00005, "{:.5f}")
    # rig-implied change
    cmp_ = pd.read_csv(REP / "derived" / "comparisons.csv")
    byU = pd.read_csv(REP / "derived" / "rotor_by_wind_speed.csv")
    g = {r.rotor: r for r in cmp_[cmp_.relative_to == "Plain"].itertuples()}
    g23 = {r.rotor: r.p_max_change_vs_plain_pct for r in byU[np.isclose(byU.wind_mps, 23.0293)].itertuples()}
    base = float(tab.loc["A_rot_U23.0_lam0.100_SST_medium_senseCCW_rev6"].CQ_mean)
    imp = [g["FS 0.10"].change_pct / 100 * base, g["FS 0.20"].change_pct / 100 * base]
    imp23 = [g23["FS 0.10"] / 100 * base, g23["FS 0.20"] / 100 * base]
    rng("implied by the gains over 10.2-38 m/s (x C_Q 0.0160 at lambda 0.10)", (0.0020, 0.0026), *imp, 0.00005,
        "{:.5f}")
    rng("implied by the 23 m/s gains", (0.0034, 0.0058), *imp23, 0.00005, "{:.5f}")
    e = [diff2u(R.revs(long(lam, "_Ks400")), R.revs(long(lam, "_Ks0")))[0] for lam in (0.10, 0.12)]
    for lam in (0.10, 0.12):
        d, tu = diff2u(R.revs(long(lam, "_Ks100")), R.revs(long(lam, "_Ks0")))
        b0 = R.revs(long(lam, "_Ks0")).mean()
        own = [g["FS 0.10"].change_pct / 100 * b0, g["FS 0.20"].change_pct / 100 * b0]
        own23 = [g23["FS 0.10"] / 100 * b0, g23["FS 0.20"] / 100 * b0]
        if lam == 0.12:
            near("lambda 0.12: Ks100 - Ks0, upper end of the 2u interval (review addition)", 0.0002, d + tu, 0.00005,
                 "{:+.5f}")
            near("... lowest rig-implied change on any base ('>= +0.0020')", 0.0020, min(imp + own), 0.00005, "{:.5f}")
            same("... the change lies below the lowest implied one by more than 2u", True, min(imp + own) - d > tu)
        info(f"lambda {lam:.2f}: Ks100 - Ks0 interval (2u) against the implied change (on the 0.0160 base; on its own "
             "Ks-0 base, speed-averaged / 23 m/s)",
             f"[{d - tu:+.4f}, {d + tu:+.4f}] against {imp[0]:.4f}-{imp[1]:.4f} ({own[0]:.4f}-{own[1]:.4f} / "
             f"{own23[0]:.4f}-{own23[1]:.4f}); upper end below the lowest implied: {d + tu < min(imp + own)}")
    rng("Ks-400 change / speed-averaged implied", (2.0, 2.8), min(e) / max(imp), max(e) / min(imp), 0.05, "{:.2f}")
    rng("Ks-400 change / 23-m/s implied", (0.9, 1.7), min(e) / max(imp23), max(e) / min(imp23), 0.05, "{:.2f}")
    # noise model and revolutions needed
    smooth23 = [n for n in tab.index if n.startswith("A_rot_U23.0") and "_medium" in n and "_Ks" not in n
                and tab.loc[n].maxCo == 4 and tab.loc[n].n_avg_rev >= 2]
    sig, dof = pooled_sigma(R, smooth23)
    near("sigma_rev, pooled over the smooth A 23 m/s runs (UPDATE 8: 0.00674)", 0.00674, sig, 0.000005, "{:.6f}")
    info("... runs, dof", f"{len(smooth23)}, {dof}")
    near("... against the 13 Oct estimate 0.00586 (UPDATE: 15 % more)", 15, pct(sig, 0.00586), 0.5, "{:.1f}")
    sig8, _ = pooled_sigma(R, [long(lam, t) for lam in (0.10, 0.12) for t in ("_Ks0", "_Ks100", "_Ks400", "")])
    near("sigma_rev pooled over the 8 long runs, used for the revolutions needed (UPDATE 8: 0.00678)", 0.00678, sig8,
         0.000005, "{:.6f}")
    for sg, lab in ((sig8, "8 long runs"), (sig, "12 smooth runs")):
        n = [math.ceil(8 * sg ** 2 / x ** 2) for x in imp]
        n23 = [math.ceil(8 * sg ** 2 / x ** 2) for x in imp23]
        txt = f"{min(n)}-{max(n)} and {min(n23)}-{max(n23)}"
        if lab == "8 long runs":
            same(f"revolutions per run needed, sigma of the {lab} (55-89; 11-33)", "55-89 and 11-33", txt)
        else:
            info(f"revolutions per run needed with the sigma of the {lab}", txt)
    wt = [float(tab.loc[long(lam, t)].wall_time_s) / 3600 for lam in (0.10, 0.12)
          for t in ("_Ks0", "_Ks100", "_Ks400", "")]
    rng("50 revolutions on 16 ranks (h)", (7.4, 14.6), min(wt), max(wt), 0.05, "{:.2f}")
    # torque budget by sector, single-blade azimuth bands
    sectors = [("upwind", 330, 30), ("advancing", 60, 120), ("downwind", 150, 210), ("returning", 240, 300)]
    gaps = [(30, 60), (120, 150), (210, 240), (300, 330)]

    def budget(nm):
        out = {s: R.sector_per_rev(nm, lo, hi) for s, lo, hi in sectors}
        out["gaps"] = sum(R.sector_per_rev(nm, lo, hi) for lo, hi in gaps)
        return out
    b = budget(long(0.10, ""))
    for s, qv in (("upwind", 0.0670), ("advancing", 0.0216), ("downwind", -0.0116), ("returning", -0.0489),
                  ("gaps", -0.0110)):
        near(f"Spalding lambda 0.10 budget: {s}", qv, b[s].mean(), 0.00005, "{:+.5f}")
    near("Spalding lambda 0.10 budget: net", 0.0170, sum(v.mean() for v in b.values()), 0.00005, "{:+.5f}")
    qd = {"advancing": (0.0092, 0.0085), "downwind": (0.0032, 0.0018), "returning": (-0.0048, -0.0024),
          "upwind": (-0.0015, -0.0021)}
    q2u = {"advancing": (0.0006, 0.0005), "downwind": (0.0011, 0.0017), "returning": (0.0022, 0.0021),
           "upwind": (0.0006, 0.0007)}
    sect = {}
    for i, lam in enumerate((0.10, 0.12)):
        b4, b0 = budget(long(lam, "_Ks400")), budget(long(lam, "_Ks0"))
        for s, v in qd.items():
            d, tu = diff2u(b4[s], b0[s])
            near(f"lambda {lam:.2f} Ks400 - Ks0 budget: {s}", v[i], d, 0.00005, "{:+.5f}")
            near(f"... {s}: 2u (UPDATE 7)", q2u[s][i], tu, 0.00005, "{:.5f}")
            same(f"... {s}: resolved at 2u", True, bool(abs(d) > tu))
            sect[(lam, s)] = d
    rr = [-sect[(lam, "returning")] / sect[(lam, "advancing")] for lam in (0.10, 0.12)]
    near("returning extra braking / advancing gain, lambda 0.10 ('about half')", 0.5, rr[0], 0.05, "{:.2f}")
    near("returning extra braking / advancing gain, lambda 0.12 ('a quarter')", 0.25, rr[1], 0.05, "{:.2f}")
    # streamwise blade force, edge-on bands
    wfa = []
    for i, lam in enumerate((0.10, 0.12)):
        for (lo, hi), qv, qu in (((80, 100), (50.0, 47.7)[i], None), ((260, 280), (0.7, 1.9)[i], (3.8, 3.7)[i])):
            a, r0 = R.force_in_band(long(lam, "_Ks400"), lo, hi), R.force_in_band(long(lam, "_Ks0"), lo, hi)
            d, tu = diff2u(a, r0)
            p, pu = 100 * d / abs(r0.mean()), 100 * tu / abs(r0.mean())
            near(f"lambda {lam:.2f}: streamwise force theta {lo}-{hi}, Ks400 vs Ks0 (%)", qv, p, 0.05, "{:+.2f}")
            if qu:
                near("... 2u (%)", qu, pu, 0.05, "{:.2f}")
                same("... not resolved", False, abs(d) > tu)
        for lo, hi in ((80, 100), (260, 280)):
            a, r0 = R.force_in_band(long(lam, ""), lo, hi), R.force_in_band(long(lam, "_Ks0"), lo, hi)
            wfa.append(pct(a.mean(), r0.mean()))
    rng("wall function alone: Spalding against Ks 0, streamwise force at theta 80-100 and 260-280, both lambda "
        "(UPDATE 7; review fix: was 15-23 %)", (11, 23), min(wfa), max(wfa), 0.5, "{:.1f}")
    # mesh check
    lvl = {}
    for lev in ("coarse", "medium", "fine"):
        for lam in (0.10, 0.15):
            tag = "_rev6" if lam == 0.10 else ""
            lvl[(lev, lam)] = float(tab.loc[f"A_rot_U23.0_lam{lam:.3f}_SST_{lev}_senseCCW{tag}"].CQ_mean)
    for lev, qv in (("coarse", 0.0138), ("medium", 0.0160), ("fine", 0.0254)):
        near(f"lambda 0.10 C_Q, {lev}", qv, lvl[(lev, 0.10)], 0.00005, "{:.5f}")
    for lev, qv in (("coarse", -0.0122), ("medium", 0.0065), ("fine", -0.0086)):
        near(f"lambda 0.15 C_Q, {lev} (UPDATE)", qv, lvl[(lev, 0.15)], 0.00005, "{:.5f}")
    dm = max(abs(lvl[(a, l)] - lvl[(b_, l)]) for l in (0.10, 0.15) for a in ("coarse", "medium", "fine")
             for b_ in ("coarse", "medium", "fine"))
    near("largest mesh difference of C_Q", 0.019, dm, 0.0005, "{:.4f}")
    levels = ("coarse", "medium", "fine")
    dmin = min(max(abs(lvl[(a, l)] - lvl[(b_, l)]) for a in levels for b_ in levels) for l in (0.10, 0.15))
    info("largest mesh difference at each lambda (UPDATE 8: 0.012-0.019)", f"{dmin:.4f}-{dm:.4f}")
    rng("mesh differences / Ks-400 effect (UPDATE 8: 2.0-3.7)", (2.0, 3.7), dmin / max(e), dm / min(e), 0.05, "{:.2f}")
    lam0s = {}
    for lev in ("coarse", "medium", "fine"):
        if lev == "medium":
            lams = [0.05, 0.10, 0.15, 0.20, 0.25]
            names = ["A_rot_U23.0_lam0.050_SST_medium_senseCCW_rev4a2", "A_rot_U23.0_lam0.100_SST_medium_senseCCW_rev6",
                     "A_rot_U23.0_lam0.150_SST_medium_senseCCW", "A_rot_U23.0_lam0.200_SST_medium_senseCCW",
                     "A_rot_U23.0_lam0.250_SST_medium_senseCCW"]
        else:
            lams = [0.10, 0.15]
            names = [f"A_rot_U23.0_lam0.100_SST_{lev}_senseCCW_rev6", f"A_rot_U23.0_lam0.150_SST_{lev}_senseCCW"]
        cqs = [float(tab.loc[n].CQ_mean) for n in names]
        us = [sig / math.sqrt(int(tab.loc[n].n_avg_rev)) for n in names]
        lam0s[lev] = lam0(lams, cqs, us)
    for lev, (qv, qu) in (("coarse", (0.127, 0.011)), ("medium", (0.159, 0.009)), ("fine", (0.137, 0.009))):
        near(f"zero-torque lambda, 23 m/s, {lev}", qv, lam0s[lev][0], 0.0005, "{:.4f}")
        near("... 2u", qu, lam0s[lev][1], 0.0005, "{:.4f}")
    rng("zero-torque lambda across meshes", (0.127, 0.159), min(v[0] for v in lam0s.values()),
        max(v[0] for v in lam0s.values()), 0.0005, "{:.4f}")
    # rig light-load lambda
    dw = pd.read_csv(REP / "tacho" / "derived" / "rotor_speed_by_dwell.csv")
    pl = dw[(dw.rotor == "Plain") & dw.speed_ok]
    ll23 = pl[np.isclose(pl.wind_mps, 23.0293)].groupby("run").tip_speed_ratio.max()
    ll38 = pl[np.isclose(pl.wind_mps, 37.9542)].groupby("run").tip_speed_ratio.max()
    rng("rig light-load lambda, 23 m/s (runs)", (0.158, 0.160), ll23.min(), ll23.max(), 0.0005, "{:.4f}")
    same("coarse and fine below the rig beyond 2u", True,
         all(lam0s[l][0] + lam0s[l][1] < ll23.min() for l in ("coarse", "fine")))
    # 38 m/s
    u38 = [n for n in tab.index if n.startswith("A_rot_U38.0") and "_medium" in n and tab.loc[n].maxCo == 4]
    s38, dof38 = pooled_sigma(R, u38)
    info("sigma_rev pooled, A 38 m/s (runs, dof)", f"{s38:.5f} ({len(u38)}, {dof38})")
    lams = [0.10, 0.15, 0.20, 0.25, 0.30]
    names = [f"A_rot_U38.0_lam{l:.3f}_SST_medium_senseCCW" + ("_rev6" if l == 0.10 else "") for l in lams]
    x, xu = lam0(lams, [float(tab.loc[n].CQ_mean) for n in names],
                 [s38 / math.sqrt(int(tab.loc[n].n_avg_rev)) for n in names])
    near("zero-torque lambda, 38 m/s", 0.156, x, 0.0005, "{:.4f}")
    near("... 2u", 0.030, xu, 0.0005, "{:.4f}")
    ll38v = float(ll38.max())
    near("rig light-load lambda, 38 m/s", 0.207, ll38v, 0.0005, "{:.4f}")
    near("CFD below the rig at 38 m/s", 0.051, ll38v - x, 0.0005, "{:.4f}")
    a8 = R.revs("A_rot_U38.0_lam0.300_SST_medium_senseCCW")
    a16 = R.revs("A_rot_U38.0_lam0.300_SST_medium_senseCCW_rev16a8")
    near("38 m/s lambda 0.30: 16 revolutions (last 8)", -0.0588, a16.mean(), 0.00005, "{:.5f}")
    near("... 8 revolutions (last 3)", -0.0549, a8.mean(), 0.00005, "{:.5f}")
    near("... difference", -0.0039, a16.mean() - a8.mean(), 0.00005, "{:+.5f}")
    near("... 2u with the pooled sigma", 0.0189, 2 * math.sqrt(s38 ** 2 / len(a16) + s38 ** 2 / len(a8)), 0.00005,
         "{:.5f}")
    rv8 = R.load("A_rot_U38.0_lam0.300_SST_medium_senseCCW")
    rv8 = dict(rv8, navg=rv8["nrev"])
    all8 = R.wmean_by_rev(rv8, rv8["cq"])
    info("8-revolution run: last two revolutions differ by (13 Oct: 0.049)", f"{all8[-1] - all8[-2]:+.4f}")
    # zero-torque shift for a persisting gain (inferred): dC_Q / slope of the medium curve
    q15, q20, q10 = (float(tab.loc[n].CQ_mean) for n in ("A_rot_U23.0_lam0.150_SST_medium_senseCCW",
                                                          "A_rot_U23.0_lam0.200_SST_medium_senseCCW",
                                                          "A_rot_U23.0_lam0.100_SST_medium_senseCCW_rev6"))
    s1_, s2_ = (q20 - q15) / 0.05, (q20 - q10) / 0.10
    rng("zero-torque lambda shift for +0.005 (slopes 0.15-0.20 and 0.10-0.20)", (0.007, 0.011),
        0.005 / abs(s1_), 0.005 / abs(s2_), 0.0005, "{:.4f}")
    # health of the new rotor runs
    old = set(pd.read_csv(OLD / "rotor_cp.csv")["name"])
    newr = [n for n in tab.index if n not in old]
    prox = []
    for n in newr:
        ds = find_key(json.loads((RO / "runs" / n / "mesh_info.json").read_text()), "ds_corner")
        r = tab.loc[n]
        prox.append(r.maxCo * ds / (r.dt_mean_s * r.U_ms))
    same("new rotor runs flagged (proxy > 5)", 0, int(sum(p > 5 for p in prox)))
    info("new rotor runs: proxy range", f"{min(prox):.3f}-{max(prox):.3f}")
    near("rotor Ks/y_P at Ks 400 um (Limits: up to 0.92)", 0.92, float(tab.Ks_over_yP.max()), 0.005, "{:.3f}")
    return e


def check_measured():
    print("\n== Measured (1 Oct report build files)")
    cmp_ = pd.read_csv(REP / "derived" / "comparisons.csv")
    g = {r.rotor: r for r in cmp_[cmp_.relative_to == "Plain"].itertuples()}
    for rot, qv in (("FS 0.10", (12.8, 10.1, 15.5)), ("FS 0.20", (16.2, 13.5, 19.0))):
        r = g[rot]
        same(f"{rot} peak power, Tukey 95 %", qv, (round(r.change_pct, 1), round(r.tukey95_lo_pct, 1),
                                                     round(r.tukey95_hi_pct, 1)))
    for rot, qv in (("FS 0.10", (6.6, 5.1, 8.1)), ("FS 0.20", (9.1, 7.6, 10.6))):
        r = g[rot]
        same(f"{rot} light-load rotor speed, Tukey 95 %", qv, (round(r.rotor_rpm_change_pct, 1),
                                                                round(r.rotor_rpm_tukey95_lo_pct, 1),
                                                                round(r.rotor_rpm_tukey95_hi_pct, 1)))
    byU = pd.read_csv(REP / "derived" / "rotor_by_wind_speed.csv")
    f2 = byU[byU.rotor == "FS 0.20"].set_index("fan_rpm_cmd")
    for rpm, U, qv in ((900, 18.8, (12.6, 11.1)), (1000, 20.9, (31.5, 4.3))):
        r = f2.loc[rpm]
        same(f"FS 0.20 at {U} m/s, pointwise 95 %", qv,
             (round(float(r.p_max_change_vs_plain_pct), 1), round(float(r.pointwise95_halfwidth_pct), 1)))
    g23 = byU[np.isclose(byU.wind_mps, 23.0293)].set_index("rotor").p_max_change_vs_plain_pct
    same("FS 0.10 and FS 0.20 at 23 m/s (headline 1)", (21.2, 36.2),
         (round(float(g23["FS 0.10"]), 1), round(float(g23["FS 0.20"]), 1)))
    same("set points 18.8 and 20.9 m/s", (18.8, 20.9),
         (round(float(f2.loc[900].wind_mps), 1), round(float(f2.loc[1000].wind_mps), 1)))
    ks = (CFD / "docs" / "ROUGHNESS_KS.md").read_text()
    same("ROUGHNESS_KS.md: Ks = k gives about 38 um (Plain, FS 0.05, FS 0.10) and 84-97 um (FS 0.20)", True,
         "about 38 um | 84-97 um" in ks)
    same("ROUGHNESS_KS.md: nominal texture 211 um (FS 0.10) and 422 um (FS 0.20)", True,
         "0 / 104 / 211 um | 422 um" in ks)
    near("f = St U / c for St 0.2232 at 23 m/s (Hz)", 107, 0.2232 * 23.0 / C, 0.5, "{:.1f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", action="store_true", help="parse the section solver logs (else read the cache)")
    args = ap.parse_args()
    s1, s2 = check_counts()
    L = log_pass(s1, args.logs)
    logs = dict(zip(L["name"], L["pres_share"]))
    R1 = Runs(S1 / "runs", s1, logs)
    s1x, J = check_section(s1, logs, R1)
    sig = L[L.name.isin(s1x[~s1x.flag].name) & (L.pres_share > 0.5)].pres_median
    nos = L[L.name.isin(s1x[~s1x.flag].name) & (L.pres_share <= 0.5)].pres_median
    newn = s1x[s1x.new].name
    sg = L[L.name.isin(newn) & (L.pres_share > 0.5)].pres_median
    ns = L[L.name.isin(newn) & (L.pres_share <= 0.5)].pres_median
    rng("new runs: median first-pressure residual with the signature (UPDATE 1)", (0.058, 0.418), sg.min(), sg.max(),
        0.0005, "{:.4f}")
    rng("new runs: ... without it (UPDATE 1)", (0.00015, 0.014), ns.min(), ns.max(), 0.0005, "{:.5f}")
    info("the same over all 102 healthy runs, with / without", f"{sig.min():.4g}-{sig.max():.4g} / "
         f"{nos.min():.2g}-{nos.max():.2g}")
    check_timestep(R1, J)
    check_transition(R1, J)
    check_stage2(s1, logs)
    check_rotor()
    check_measured()
    print(f"\n{COUNT['OK']} OK, {COUNT['CHECK']} CHECK, {COUNT['INFO']} INFO")
