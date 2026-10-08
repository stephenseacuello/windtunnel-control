#!/usr/bin/env python3
"""Summarise one cfd/rotor2d case (rotating or static) from its postProcessing/ and log.

    python3 cfd/post/rotor_summary.py <caseDir> [<caseDir> ...]     # prints JSON; works on partial runs

Definitions (per unit span; case.json holds R, dz, sense, qRef = 0.5 rho U^2, Aref = 2R):
  Q'  = sense * M_z / dz;  C_Q = Q' / (qRef Aref R);  C_P = lambda C_Q (rotating)
  C_x, C_y = F_x/dz / (qRef Aref), F_y/dz / (qRef Aref)  (rotor force on swept width 2R)
Rotating: means over the last nAvgRev revolutions (or whatever exists, flagged), per-
revolution means, and the single-blade C_Q against blade azimuth (all three blades
phase-averaged, 5 deg bins) written to <case>/phase_CQ.csv.
Static: means and standard deviation over the last nAvgConv D/U, standard error of
the mean C_Q (batch means, CQ_sem), Strouhal number (D-based) of C_Q.
Free stream: Tu_upstream_probe_pct = 100 sqrt(2/3 k)/U from the mean k at the upstream
probe (-2 D) over the averaging window (cases set up from 8 Oct probe k); freestream_decay
('control' or 'precompensate') and lt_m from case.json.
No OpenFOAM install is needed.
"""
import json
import math
import re
import sys
from pathlib import Path

import numpy as np


def _num(s):
    try:
        return float(s)
    except ValueError:
        return None


def read_fo_table(case, fo, fname):
    """Concatenate postProcessing/<fo>/<t>/<fname>* over restarts (later start wins).
    Returns (header list, rows as list of token lists)."""
    root = Path(case) / "postProcessing" / fo
    if not root.exists():
        return [], []
    dirs = sorted((d for d in root.iterdir() if d.is_dir() and _num(d.name) is not None), key=lambda d: float(d.name))
    segs, header = [], []
    for d in dirs:
        for f in sorted(d.glob(fname.replace(".dat", "*.dat"))):
            rows = []
            for ln in f.read_text().splitlines():
                if ln.startswith("#"):
                    h = ln[1:].split()
                    if h and h[0] == "Time":
                        header = h
                    continue
                tok = ln.split()
                if tok and _num(tok[0]) is not None:
                    rows.append(tok)
            if rows:
                segs.append(rows)
    out = []
    for i, rows in enumerate(segs):
        t_next = float(segs[i + 1][0][0]) if i + 1 < len(segs) else math.inf
        out += [r for r in rows if float(r[0]) < t_next]
    return header, out


def read_vector_dat(case, fo, fname):
    """forces .dat -> array (n, 10): t, total xyz, pressure xyz, viscous xyz."""
    _, rows = read_fo_table(case, fo, fname)
    if not rows:
        return np.zeros((0, 10))
    a = np.array([[float(x.strip("()")) for x in r[:10]] for r in rows])
    _, idx = np.unique(a[:, 0], return_index=True)
    return a[np.sort(idx)]


def read_log(case):
    log = Path(case) / "log.pimpleFoam"
    out = dict(n_steps=0)
    if not log.exists():
        return out
    txt = log.read_text(errors="replace")
    dt = [float(x) for x in re.findall(r"^deltaT = (\S+)", txt, re.M)]
    co = [float(x) for x in re.findall(r"^Courant Number mean: \S+ max: (\S+)", txt, re.M)]
    ex = re.findall(r"^ExecutionTime = (\S+) s\s+ClockTime = (\S+) s", txt, re.M)
    ts = [float(x) for x in re.findall(r"^Time = (\S+)", txt, re.M)]
    bnd = len(re.findall(r"bounding omega", txt))
    out.update(n_steps=len(ts), t_first=ts[0] if ts else None, t_last=ts[-1] if ts else None)
    if dt:
        d = np.array(dt)
        tail = d[len(d) // 2:]
        out.update(dt_mean_s=float(d.mean()), dt_last_half_mean_s=float(tail.mean()), dt_min_s=float(d.min()),
                   dt_max_s=float(d.max()))
    if co:
        c = np.array(co)
        out.update(Co_max_mean=float(c[len(c) // 2:].mean()), Co_max_max=float(c.max()))
    if ex:
        clock = np.array([float(b) for _, b in ex])
        # restarts reset ClockTime: sum the per-session final values
        sess = np.split(clock, np.flatnonzero(np.diff(clock) < 0) + 1)
        out["clock_s"] = float(sum(s[-1] - s[0] for s in sess if len(s)))
        n = len(clock)
        if n > 20:
            k = max(5, n // 5)
            seg = clock[-k:]
            if np.all(np.diff(seg) >= 0):
                out["s_per_step_recent"] = float((seg[-1] - seg[0]) / (k - 1))
        out["s_per_step"] = out["clock_s"] / max(1, n - len(sess))
    out["omega_bounded_steps"] = bnd
    sums = re.findall(r"^AMI: Patch (source|target) sum\(weights\) min:(\S+) max:(\S+) average:(\S+)", txt, re.M)
    if sums:
        lo = [float(a) for _, a, _, _ in sums]
        hi = [float(b) for _, _, b, _ in sums]
        out.update(ami_log_sum_min=min(lo), ami_log_sum_max=max(hi), ami_log_n=len(sums))
    return out


def read_ami(case):
    hdr, rows = read_fo_table(case, "AMIWeights1", "AMIWeights.dat")
    if not rows:
        return {}
    cols = hdr[1:]
    res = {}
    for r in rows:
        d = dict(zip(cols, r[1:]))
        p = d.get("Patch")
        if p is None:
            continue
        e = res.setdefault(p, dict(src_min=1e9, src_max=-1e9, tgt_min=1e9, tgt_max=-1e9, src_avg=[], tgt_avg=[], n=0))
        e["src_min"] = min(e["src_min"], float(d["src_min_weight"]))
        e["src_max"] = max(e["src_max"], float(d["src_max_weight"]))
        e["tgt_min"] = min(e["tgt_min"], float(d["tgt_min_weight"]))
        e["tgt_max"] = max(e["tgt_max"], float(d["tgt_max_weight"]))
        e["src_avg"].append(float(d["src_average_weight"]))
        e["tgt_avg"].append(float(d["tgt_average_weight"]))
        e["n"] += 1
    for e in res.values():
        e["src_avg"] = float(np.mean(e["src_avg"]))
        e["tgt_avg"] = float(np.mean(e["tgt_avg"]))
    return res


def read_yplus(case, t0=-math.inf):
    hdr, rows = read_fo_table(case, "yPlus1", "yPlus.dat")
    out = {}
    for r in rows:
        if float(r[0]) < t0 or len(r) < 5:
            continue
        e = out.setdefault(r[1], dict(min=[], max=[], avg=[]))
        e["min"].append(float(r[2]))
        e["max"].append(float(r[3]))
        e["avg"].append(float(r[4]))
    return {p: dict(min=float(np.min(e["min"])), max=float(np.max(e["max"])), mean_of_avg=float(np.mean(e["avg"])),
                    n=len(e["avg"])) for p, e in out.items()}


def read_probe_tu(case, P, t0=-math.inf):
    """Tu (%) from the mean k at the most upstream probe (-2 D on the axis), over t >= t0
    (all samples if none). None if the case has no k probes (set up before 8 Oct)."""
    _, rows = read_fo_table(case, "probes1", "k")
    locs = P.get("probeLocations") or []
    if not rows or not locs:
        return None
    i = 1 + min(range(len(locs)), key=lambda j: locs[j][0])
    k = [float(r[i]) for r in rows if len(r) > i and float(r[0]) >= t0] or \
        [float(r[i]) for r in rows if len(r) > i]
    if not k:
        return None
    return float(100 * math.sqrt(2 / 3 * float(np.mean(k))) / P["Uinf"])


def tmean(t, y):
    if len(t) < 2:
        return float(y[0]) if len(y) else float("nan")
    return float(np.trapezoid(y, t) / (t[-1] - t[0]))


def batch_sem(t, y, nb=5):
    """Standard error of the time mean of y by batch means: nb equal-time batches
    (static: 25 D/U / 5 = 5 D/U each, about one shedding period of the rotor),
    s.d. of the batch means / sqrt(nb). None if the window is too short."""
    if len(t) < 10 * nb:
        return None
    edges = np.linspace(t[0], t[-1], nb + 1)
    means = []
    for a, b in zip(edges[:-1], edges[1:]):
        w = (t >= a) & (t <= b)
        if w.sum() < 2:
            return None
        means.append(tmean(t[w], y[w]))
    return float(np.std(means, ddof=1) / math.sqrt(nb))


def summarize(case):
    case = Path(case)
    P = json.loads((case / "case.json").read_text())
    s, dz, q, A, R = P["sense"], P["dz"], P["qRef"], P["Aref"], P["R"]
    m = read_vector_dat(case, "forcesRotor", "moment.dat")
    f = read_vector_dat(case, "forcesRotor", "force.dat")
    lg = read_log(case)
    tim = json.loads((case / "timing.json").read_text()) if (case / "timing.json").exists() else []
    mi = json.loads((case / "mesh_info.json").read_text()) if (case / "mesh_info.json").exists() else {}
    out = dict(name=P["caseName"], mode=P["mode"], hypothesis=P["hypothesis"], U_ms=P["Uinf"],
               model=P["turbulenceModel"], level=mi.get("level"), wall=P["wall"], n_cells=mi.get("n_cells"),
               h0_m=mi.get("h0_m"), sense="CCW" if s > 0 else "CW", R_m=R, r_max_m=P["rMax"], dz_m=dz,
               Tu_rotor_pct=P["TuRotorPercent"], Tu_inlet_pct=P.get("TuInletPercent"),
               # cases set up before 8 Oct have no freestreamDecay key: they had no decay control
               freestream_decay=P.get("freestreamDecay", "precompensate"), lt_m=P.get("turbulenceLengthScale"),
               maxCo=P["maxCo"], nOuter=P["nOuterCorrectors"], nProcs=P["nProcs"],
               wall_time_s=float(sum(x["wall_s"] for x in tim)), **{k: v for k, v in lg.items() if k != "ami_log_excerpt"})
    out["ami"] = read_ami(case)
    if out["ami"]:
        out["ami_weight_min"] = min(min(e["src_min"], e["tgt_min"]) for e in out["ami"].values())
        out["ami_weight_max"] = max(max(e["src_max"], e["tgt_max"]) for e in out["ami"].values())
    if len(m) < 2:
        out["note"] = "no load history yet"
        out["Tu_upstream_probe_pct"] = read_probe_tu(case, P)
        return out
    t = m[:, 0]
    Qp = s * m[:, 3] / dz
    CQ = Qp / (q * A * R)
    Cx = f[:, 1] / dz / (q * A) if len(f) == len(m) else np.full_like(t, np.nan)
    Cy = f[:, 2] / dz / (q * A) if len(f) == len(m) else np.full_like(t, np.nan)
    CQp = s * m[:, 6] / dz / (q * A * R)          # pressure part
    blades = []
    for k in (1, 2, 3):
        mb = read_vector_dat(case, f"forcesBlade{k}", "moment.dat")
        if len(mb) == len(m):
            blades.append(s * mb[:, 3] / dz / (q * A * R))
    out.update(t_end=float(t[-1]), n_samples=int(len(t)))
    if P["mode"] == "rotating":
        T, lam, Om = P["Trev"], P["lam"], P["Omega"]
        nav = P["nAvgRev"]
        t0 = max(t[0], t[-1] - nav * T)
        w = t >= t0
        n_rev_done = t[-1] / T
        CQm = tmean(t[w], CQ[w])
        per_rev = []
        for r in range(int(math.floor(n_rev_done + 1e-9))):
            ww = (t >= r * T) & (t <= (r + 1) * T)
            if ww.sum() > 10:
                per_rev.append(tmean(t[ww], CQ[ww]))
        out.update(lam=lam, Omega=Om, rpm=P["rpm"], Trev_s=T, n_rev_done=float(n_rev_done), n_rev_target=P["nRev"],
                   n_avg_rev=float((t[-1] - t0) / T), avg_window_complete=bool(t[-1] - t0 >= nav * T * (1 - 1e-6)),
                   CQ_mean=CQm, CP_mean=lam * CQm, CQ_std=float(np.std(CQ[w])), CQ_min=float(CQ[w].min()),
                   CQ_max=float(CQ[w].max()), CQ_pressure_mean=tmean(t[w], CQp[w]),
                   Cx_mean=tmean(t[w], Cx[w]), Cy_mean=tmean(t[w], Cy[w]),
                   CQ_per_rev=per_rev, CP_per_rev=[lam * v for v in per_rev],
                   CQ_drift_last_two_rev=(per_rev[-1] - per_rev[-2]) if len(per_rev) >= 2 else None)
        if blades:
            out["CQ_blade_mean"] = [tmean(t[w], b[w]) for b in blades]
            th = np.degrees(Om * t)
            rows = []
            edges = np.arange(0, 361, 5.0)
            acc = np.zeros(len(edges) - 1)
            cnt = np.zeros(len(edges) - 1)
            for k, b in enumerate(blades):
                thk = np.mod(P.get("thetaDeg", 0.0) + th[w] + 120.0 * k, 360.0)
                idx = np.clip(np.digitize(thk, edges) - 1, 0, len(acc) - 1)
                np.add.at(acc, idx, b[w])
                np.add.at(cnt, idx, 1)
            for i in range(len(acc)):
                rows.append((0.5 * (edges[i] + edges[i + 1]), acc[i] / cnt[i] if cnt[i] else float("nan"), int(cnt[i])))
            with open(case / "phase_CQ.csv", "w") as fh:
                fh.write("theta_blade_deg,CQ_single_blade,n\n")
                fh.writelines(f"{a:.1f},{b:.6g},{c}\n" for a, b, c in rows)
        out["yplus"] = read_yplus(case, t0)
    else:
        tc = P["convTime"]
        t0 = max(t[0], t[-1] - P["nAvgConv"] * tc)
        w = t >= t0
        out.update(theta_deg=P["thetaDeg"], convTime_s=tc, t_end_conv=float(t[-1] / tc),
                   avg_window_conv=float((t[-1] - t0) / tc),
                   avg_window_complete=bool(t[-1] - t0 >= P["nAvgConv"] * tc * (1 - 1e-6)),
                   CQ_mean=tmean(t[w], CQ[w]), CQ_std=float(np.std(CQ[w])), CQ_sem=batch_sem(t[w], CQ[w]),
                   CQ_pressure_mean=tmean(t[w], CQp[w]),
                   Cx_mean=tmean(t[w], Cx[w]), Cx_std=float(np.std(Cx[w])), Cy_mean=tmean(t[w], Cy[w]),
                   Cy_std=float(np.std(Cy[w])))
        if blades:
            out["CQ_blade_mean"] = [tmean(t[w], b[w]) for b in blades]
        # Strouhal from C_Q (uniform resample over the window)
        if w.sum() > 64:
            tu = np.linspace(t[w][0], t[w][-1], 4096)
            y = np.interp(tu, t[w], CQ[w])
            y = y - y.mean()
            F = np.abs(np.fft.rfft(y * np.hanning(len(y))))
            fr = np.fft.rfftfreq(len(y), tu[1] - tu[0])
            k = int(np.argmax(F[1:]) + 1)
            out["f_peak_Hz"] = float(fr[k])
            out["St_D"] = float(fr[k] * P["D"] / P["Uinf"])
        out["yplus"] = read_yplus(case, t0)
    out["Tu_upstream_probe_pct"] = read_probe_tu(case, P, t0)      # over the averaging window
    if out.get("yplus"):
        out["yplus_mean"] = float(np.mean([e["mean_of_avg"] for k, e in out["yplus"].items() if k.startswith("blade")]))
        out["yplus_max"] = float(np.max([e["max"] for k, e in out["yplus"].items() if k.startswith("blade")]))
    return out


if __name__ == "__main__":
    for c in sys.argv[1:]:
        print(json.dumps(summarize(c), indent=1))
