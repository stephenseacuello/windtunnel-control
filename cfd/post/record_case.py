#!/usr/bin/env python3
"""Write a permanent, git-trackable record of one CFD case: settings, logs, plots, field images.

    python3 cfd/post/record_case.py cfd/section2d/runs/<case>             # record + ParaView renders
    python3 cfd/post/record_case.py cfd/rotor2d/runs/<case> --kind rotor
    python3 cfd/post/record_case.py <case> --no-render                    # numbers and plots only (seconds)
    python3 cfd/post/record_case.py <case> --out /tmp/rec                 # somewhere else

Output: cfd/<stage>/results/records/<case name>/  (stage = section2d or rotor2d), about 2-5 MB:
  README.md            what each plot shows and how to read it, with this case's numbers
  summary.json         key numbers (status, run length, means, St, y+, cost, mesh quality)
  case.json            the case parameters (copy); results.json (copy) if the queue wrote it
  settings.txt         controlDict, caseParameters, fvSchemes, fvSolution, turbulence and
                       transport properties, mesh-motion dictionary, 0/ boundary conditions
  mesh_info.json, checkMesh.log, mesh_generator.png (if the case has one)
  log_excerpt.txt      solver sessions (CPU vs clock time), header, warnings, last 50 lines
  residuals.png/.csv   first initial residual per time step for each solved field
  timestep.png         deltaT, max Courant number, and CPU vs clock time (shows sleep stalls)
  coefficients.png/.csv  section: Cd, Cl, Cm vs t U/c;  rotor: C_Q, C_P (or C_x, C_y)
                       vs revolutions or t U/D; averaging window shaded, mean +/- std
  spectrum.png         lift (section) or torque (rotor) spectrum, Strouhal number marked
  phase_CQ.png         rotating rotor: single-blade C_Q against azimuth
  yplus.png            y+ min / mean / max on the walls against time (yPlus function object)
  fields/              ParaView images (render_fields.py): mesh, |U|, vorticity, Cp, nu_t/nu,
                       LIC, streamlines, gammaInt; wall Cp / Cf / y+ distributions
CSV files are decimated to at most 5000 rows; PNGs are 150 dpi.

Safety: the case is only read. Field images come from a temporary folder of symlinks
(record_lib.make_shadow), never from writing into the case. A RUNNING case (marker file,
a log written in the last 3 minutes, or a live solver process) gets a partial record
without field images, flagged 'running' in summary.json.
"""
import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path[:] = [p for p in sys.path if p not in ("", ".")]
sys.path.insert(0, str(HERE))
import record_lib as rl  # noqa: E402

MAXROWS = 5000
DPI = 150
RECORD_VERSION = 1
RES_FIELDS = ("Ux", "Uy", "p", "k", "omega", "gammaInt", "ReThetat", "nuTilda", "epsilon")
KEEP = ("NOTES.md",)          # hand-written files in a record folder survive a re-record


# --------------------------------------------------------------------------- readers
def read_fo(case, fo, fname):
    """Concatenate postProcessing/<fo>/<t>/<fname> over restarts (a later start wins).
    Returns (header tokens, rows as list of token lists)."""
    root = Path(case) / "postProcessing" / fo
    dirs = rl.time_dirs(root)
    segs, header = [], []
    for _, name in dirs:
        f = root / name / fname
        if not f.exists():
            continue
        rows = []
        with open(f, errors="replace") as fh:
            for ln in fh:
                if ln.startswith("#"):
                    h = ln[1:].split()
                    if h and h[0] == "Time":
                        header = h
                    continue
                tok = ln.replace("(", " ").replace(")", " ").split()
                if tok and rl.is_number(tok[0]):
                    rows.append(tok)
        if rows:
            segs.append(rows)
    out = []
    for i, rows in enumerate(segs):
        t_next = float(segs[i + 1][0][0]) if i + 1 < len(segs) else math.inf
        out += [r for r in rows if float(r[0]) < t_next]
    return header, out


def numeric(rows, ncol=None):
    if not rows:
        return np.zeros((0, ncol or 1))
    n = ncol or min(len(r) for r in rows)
    a = np.array([[float(x) for x in r[:n]] for r in rows])
    _, idx = np.unique(a[:, 0], return_index=True)
    return a[np.sort(idx)]


def parse_log(path):
    """Stream the solver log once. Returns a dict of numpy arrays and text excerpts."""
    steps_t, steps_dt, steps_co, steps_com, steps_ex, steps_cl, steps_sess = [], [], [], [], [], [], []
    res = {f: ([], []) for f in RES_FIELDS}
    other_res = {}
    sessions = []
    warn = OrderedDict()
    header, in_header = [], False
    pend_dt = pend_co = pend_com = None
    t = None
    seen = set()
    rx_res = re.compile(r"Solving for (\w+), Initial residual = ([-+0-9.eE]+)")
    rx_co = re.compile(r"^Courant Number mean: ([-+0-9.eE]+) max: ([-+0-9.eE]+)")
    rx_ex = re.compile(r"^ExecutionTime = ([-+0-9.eE]+) s\s+ClockTime = ([-+0-9.eE]+) s")
    rx_num = re.compile(r"[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?")
    rx_warn = re.compile(r"(FOAM Warning|FOAM FATAL|[Ww]arning|^bounding |\bnan\b|Floating point exception)")
    ctx = 0
    last_warn_key = None
    with open(path, errors="replace") as fh:
        for ln in fh:
            s = ln.rstrip("\n")
            if s.startswith("Exec   :"):
                sessions.append(dict(exec_cmd=s.split(":", 1)[1].strip(), date="", time="", host="", nprocs=1,
                                     first_t=None, last_t=None, exec_s=0.0, clock_s=0.0, n_steps=0))
                if not header:
                    in_header = True
                continue
            if sessions and s.startswith("Date   :"):
                sessions[-1]["date"] = s.split(":", 1)[1].strip()
            elif sessions and s.startswith("Time   :"):
                sessions[-1]["time"] = s.split(":", 1)[1].strip()
            elif sessions and s.startswith("Host   :"):
                sessions[-1]["host"] = s.split(":", 1)[1].strip()
            elif sessions and s.startswith("nProcs :"):
                sessions[-1]["nprocs"] = int(s.split(":", 1)[1])
            if in_header:
                header.append(s)
                if s.startswith("Starting time loop") or s.startswith("Courant Number") or len(header) > 200:
                    in_header = False
            m = rx_co.match(s)
            if m:
                pend_com, pend_co = float(m.group(1)), float(m.group(2))
                continue
            if s.startswith("deltaT = "):
                try:
                    pend_dt = float(s.split("=", 1)[1])
                except ValueError:
                    pass
                continue
            if s.startswith("Time = ") and rl.is_number(s[7:].strip().rstrip("s").strip()):
                t = float(s[7:].strip().rstrip("s").strip())
                steps_t.append(t)
                steps_dt.append(pend_dt if pend_dt is not None else np.nan)
                steps_co.append(pend_co if pend_co is not None else np.nan)
                steps_com.append(pend_com if pend_com is not None else np.nan)
                steps_ex.append(np.nan)
                steps_cl.append(np.nan)
                steps_sess.append(len(sessions) - 1)
                pend_dt = pend_co = pend_com = None
                seen = set()
                if sessions:
                    S = sessions[-1]
                    S["first_t"] = t if S["first_t"] is None else S["first_t"]
                    S["last_t"] = t
                    S["n_steps"] += 1
                continue
            m = rx_res.search(s)
            if m and t is not None:
                f = m.group(1)
                if f not in seen:
                    seen.add(f)
                    if f in res:
                        res[f][0].append(t)
                        res[f][1].append(float(m.group(2)))
                    else:
                        other_res.setdefault(f, ([], []))
                        other_res[f][0].append(t)
                        other_res[f][1].append(float(m.group(2)))
                continue
            m = rx_ex.match(s)
            if m:
                if steps_ex:
                    steps_ex[-1], steps_cl[-1] = float(m.group(1)), float(m.group(2))
                if sessions:
                    sessions[-1]["exec_s"], sessions[-1]["clock_s"] = float(m.group(1)), float(m.group(2))
                continue
            if ctx > 0 and last_warn_key is not None:
                w = warn[last_warn_key]
                if len(w["context"]) < 4 and s.strip():
                    w["context"].append(s.strip())
                ctx -= 1
            if rx_warn.search(s) and not s.startswith("trapFpe:"):
                key = rx_num.sub("#", s.strip())[:160]
                w = warn.get(key)
                if w is None:
                    w = warn[key] = dict(first=s.strip()[:300], count=0, t_first=t, t_last=t, context=[])
                    ctx = 3 if "FOAM" in s else 0
                    last_warn_key = key
                w["count"] += 1
                w["t_last"] = t
    for f, v in other_res.items():
        res[f] = v
    arr = lambda x: np.array(x, float)  # noqa: E731
    return dict(t=arr(steps_t), dt=arr(steps_dt), co=arr(steps_co), co_mean=arr(steps_com), ex=arr(steps_ex),
                cl=arr(steps_cl), sess=np.array(steps_sess, int),
                res={f: (arr(a), arr(b)) for f, (a, b) in res.items() if a},
                sessions=sessions, warnings=warn, header=header)


def checkmesh_summary(path):
    if not Path(path).exists():
        return {}
    s = Path(path).read_text(errors="replace")
    out = {}
    for key, rx in (("cells", r"^\s*cells:\s+(\d+)"), ("points", r"^\s*points:\s+(\d+)"),
                    ("max_aspect_ratio", r"Max aspect ratio = ([\d.eE+-]+)"),
                    ("max_non_orthogonality_deg", r"non-orthogonality Max: ([\d.eE+-]+)"),
                    ("avg_non_orthogonality_deg", r"non-orthogonality Max: [\d.eE+-]+ average: ([\d.eE+-]+)"),
                    ("max_skewness", r"Max skewness = ([\d.eE+-]+)"),
                    ("min_volume_m3", r"Min volume = ([\d.eE+-]+)")):
        m = re.search(rx, s, re.M)
        if m:
            v = m.group(1).rstrip(".")
            try:
                out[key] = int(v) if re.fullmatch(r"\d+", v) else float(v)
            except ValueError:
                pass
    out["mesh_ok"] = "Mesh OK." in s       # absent key = no checkMesh log
    m = re.search(r"Failed (\d+) mesh checks", s)
    if m:
        out["failed_checks"] = int(m.group(1))
    return out


def effective_parameters(case, P):
    """Numbers from system/caseParameters override case.json (a test case may have been edited
    after case.json was written, e.g. maxCo raised for a Courant test). Returns (P, changed)."""
    f = Path(case) / "system" / "caseParameters"
    changed = {}
    if not f.exists():
        return P, changed
    P = dict(P)
    for ln in f.read_text(errors="replace").splitlines():
        m = re.match(r"^(\w+)\s+([-+0-9.eE]+);\s*$", ln.strip())
        if m and m.group(1) in P and isinstance(P[m.group(1)], (int, float)):
            v = float(m.group(2))
            if abs(v - float(P[m.group(1)])) > 1e-9 * max(1.0, abs(v)):
                changed[m.group(1)] = dict(case_json=P[m.group(1)], caseParameters=v)
                P[m.group(1)] = v
    return P, changed


# --------------------------------------------------------------------------- numerics
def decimate_rows(a, nmax=MAXROWS):
    if len(a) <= nmax:
        return a
    idx = np.unique(np.linspace(0, len(a) - 1, nmax).round().astype(int))
    return a[idx]


def write_csv(path, header, cols, comment=""):
    a = np.column_stack(cols) if cols else np.zeros((0, len(header)))
    a = decimate_rows(a)
    with open(path, "w") as fh:
        if comment:
            for line in comment.splitlines():
                fh.write(f"# {line}\n")
        fh.write(",".join(header) + "\n")
        for row in a:
            fh.write(",".join(f"{v:.8g}" for v in row) + "\n")
    return len(a)


def spectrum(t, y):
    """One-sided power spectrum of y(t) after uniform resampling and a Hann window.
    Returns f, P, f_peak (parabolic refinement), peak fraction (power within +-15 %)."""
    if len(t) < 32:
        return None
    dt = float(np.median(np.diff(t)))
    tu = np.arange(t[0], t[-1], dt)
    if len(tu) < 32:
        return None
    yu = np.interp(tu, t, y)
    yu = yu - yu.mean()
    if not np.any(yu):
        return None
    nfft = 8 * int(2 ** np.ceil(np.log2(len(yu))))
    P = np.abs(np.fft.rfft(yu * np.hanning(len(yu)), nfft)) ** 2
    f = np.fft.rfftfreq(nfft, dt)
    fmin = 2.0 / (tu[-1] - tu[0])
    m = f > fmin
    if not m.any():
        return dict(f=f, P=P, fp=float("nan"), frac=float("nan"), T=tu[-1] - tu[0])
    i = int(np.argmax(np.where(m, P, 0)))
    di = 0.0
    if 0 < i < len(P) - 1:
        a_, b_, c_ = (np.log(P[j] + 1e-300) for j in (i - 1, i, i + 1))
        den = a_ - 2 * b_ + c_
        di = 0.5 * (a_ - c_) / den if den != 0 else 0.0
    fp = (i + di) * (f[1] - f[0])
    band = (f > 0.85 * fp) & (f < 1.15 * fp)
    frac = float(P[band].sum() / P[f > 0].sum())
    return dict(f=f, P=P, fp=float(fp), frac=frac, T=tu[-1] - tu[0])


def tmean(t, y):
    if len(t) < 2:
        return float(np.mean(y)) if len(y) else float("nan")
    return float(np.trapezoid(y, t) / (t[-1] - t[0]))


# --------------------------------------------------------------------------- plots
def savefig(fig, path):
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def plot_residuals(L, tref, tlab, path, title):
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    n = 0
    for f, (t, r) in L["res"].items():
        if len(t) == 0:
            continue
        k = max(1, len(t) // 20000)
        ax.semilogy(t[::k] / tref, np.maximum(r[::k], 1e-16), lw=0.8, label=f)
        n += 1
    ax.set_xlabel(tlab)
    ax.set_ylabel("initial residual (first solve of each time step)")
    ax.grid(alpha=0.3)
    if n:
        ax.legend(fontsize=8, ncol=min(n, 5))
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    savefig(fig, path)


def plot_timestep(L, tref, tlab, maxco, path, title):
    t = L["t"] / tref
    fig, axs = plt.subplots(3, 1, figsize=(8.5, 8.0), sharex=False)
    k = max(1, len(t) // 20000)
    axs[0].semilogy(t[::k], L["dt"][::k], lw=0.8, color="C0")
    axs[0].set_ylabel("deltaT (s)")
    axs[0].set_xlabel(tlab)
    axs[1].plot(t[::k], L["co"][::k], lw=0.8, color="C1", label="max Courant number")
    if maxco:
        axs[1].axhline(maxco, color="k", ls="--", lw=0.8, label=f"maxCo = {maxco:g} (controlDict)")
    axs[1].set_ylabel("Co max")
    axs[1].set_xlabel(tlab)
    axs[1].legend(fontsize=8)
    # CPU vs clock time, cumulative over sessions
    ex, cl, ss = L["ex"], L["cl"], L["sess"]
    cum_ex, cum_cl = np.full_like(ex, np.nan), np.full_like(cl, np.nan)
    off_e = off_c = 0.0
    for s in np.unique(ss):
        m = ss == s
        e, c = ex[m], cl[m]
        good = np.isfinite(e)
        if good.any():
            cum_ex[m] = off_e + e
            cum_cl[m] = off_c + c
            off_e += np.nanmax(e)
            off_c += np.nanmax(c)
    idx = np.arange(len(ex))
    axs[2].plot(idx[::k], cum_cl[::k] / 3600, lw=1.2, color="C3", label="ClockTime (wall clock)")
    axs[2].plot(idx[::k], cum_ex[::k] / 3600, lw=1.2, color="C2", label="ExecutionTime (CPU, rank 0)")
    for s in np.unique(ss)[1:]:
        axs[2].axvline(np.argmax(ss == s), color="0.5", ls=":", lw=0.8)
    axs[2].set_xlabel("time step number (dotted lines: restarts)")
    axs[2].set_ylabel("hours, cumulative")
    axs[2].legend(fontsize=8)
    for ax in axs:
        ax.grid(alpha=0.3)
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    savefig(fig, path)


def plot_history(t_nd, series, window, path, title, xlab):
    """series: list of (label, y). window: (t0_nd, t1_nd) or None."""
    fig, axs = plt.subplots(len(series), 1, figsize=(8.5, 2.3 * len(series) + 0.8), sharex=True)
    axs = np.atleast_1d(axs)
    for ax, (lab, y) in zip(axs, series):
        ax.plot(t_nd, y, lw=0.8, color="C0")
        if window:
            m = (t_nd >= window[0]) & (t_nd <= window[1])
            ax.axvspan(window[0], window[1], color="C1", alpha=0.12, lw=0)
            if m.sum() > 1:
                mu, sd = float(np.mean(y[m])), float(np.std(y[m]))
                ax.plot(window, [mu, mu], color="C3", lw=1.2)
                ax.fill_between(window, mu - sd, mu + sd, color="C3", alpha=0.15, lw=0)
                ax.text(0.99, 0.95, f"mean {mu:.4g}, std {sd:.3g}", transform=ax.transAxes, ha="right", va="top",
                        fontsize=8, bbox=dict(fc="white", ec="0.7", alpha=0.85))
        ax.set_ylabel(lab)
        ax.grid(alpha=0.3)
    axs[-1].set_xlabel(xlab)
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    savefig(fig, path)


def plot_spectrum(sp, xscale, xlab, marks, path, title, sp2=None, lab1="", lab2=""):
    fig, ax = plt.subplots(figsize=(8.0, 4.2))
    f = sp["f"][1:] * xscale
    ax.semilogy(f, sp["P"][1:] / sp["P"][1:].max(), lw=1.0, label=lab1 or None)
    if sp2 is not None:
        ax.semilogy(sp2["f"][1:] * xscale, sp2["P"][1:] / sp2["P"][1:].max(), lw=0.9, alpha=0.7, label=lab2 or None)
    merged = []
    for x, txt in marks:                      # one line and label per distinct frequency
        if not np.isfinite(x):
            continue
        for m in merged:
            if abs(m[0] - x) <= 0.03 * max(abs(x), 1e-12):
                m[1] += f"; {txt}"
                break
        else:
            merged.append([x, txt])
    for i, (x, txt) in enumerate(merged):
        ax.axvline(x, color="C3", ls="--", lw=0.9)
        ax.text(x, 0.55 if i % 2 == 0 else 0.15, txt, rotation=90, fontsize=8, color="C3", ha="right",
                va="center", transform=ax.get_xaxis_transform())
    top = 4 * max([m[0] for m in marks if np.isfinite(m[0])] or [1.0])
    ax.set_xlim(0, max(top, 10 * xscale / sp["T"]))
    ax.set_ylim(1e-6, 2)
    ax.set_xlabel(xlab)
    ax.set_ylabel("power (normalised to its peak)")
    ax.grid(alpha=0.3, which="both")
    if lab1 or lab2:
        ax.legend(fontsize=8)
    res = xscale / sp["T"]
    ax.set_title(title + f"\nfrequency resolution 1/T_window = {res:.3g} in these units", fontsize=9)
    fig.tight_layout()
    savefig(fig, path)


def plot_yplus(yp, tref, tlab, path, title):
    fig, ax = plt.subplots(figsize=(8.0, 4.0))
    for i, (patch, a) in enumerate(sorted(yp.items())):
        c = f"C{i}"
        ax.plot(a[:, 0] / tref, a[:, 3], color=c, lw=1.2, label=f"{patch} mean")
        ax.fill_between(a[:, 0] / tref, a[:, 1], a[:, 2], color=c, alpha=0.15, label=f"{patch} min-max")
    ax.set_yscale("log")
    ax.axhline(1, color="k", ls=":", lw=0.8)
    ax.set_xlabel(tlab)
    ax.set_ylabel("y+ (first cell centre)")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=8, ncol=2)
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    savefig(fig, path)


# --------------------------------------------------------------------------- settings
def strip_banner(text):
    text = re.sub(r"/\*-+\*- C\+\+ -\*-+\*\\.*?\\\*-+\*/\s*", "", text, count=1, flags=re.S)
    text = re.sub(r"^/\*-{5,}.*?\*/\s*", "", text, count=1, flags=re.S)
    return text.strip()


def field_bc(path):
    raw = Path(path).read_bytes()
    if len(raw) > 2_000_000:
        return "(file larger than 2 MB: not copied)"
    s = raw.decode("utf-8", "replace")
    s = re.sub(r"nonuniform\s+List<\w+>\s*\d+\s*\(.*?\)\s*;", "nonuniform List (values omitted);", s, flags=re.S)
    i = s.find("dimensions")
    return s[i:].strip() if i >= 0 else strip_banner(s)


def write_settings(case, path):
    case = Path(case)
    parts = []
    for rel in ("system/controlDict", "system/caseParameters", "system/functions", "system/fvSchemes",
                "system/fvSolution", "system/decomposeParDict", "constant/turbulenceProperties",
                "constant/momentumTransport", "constant/transportProperties", "constant/physicalProperties",
                "constant/dynamicMeshDict"):
        f = case / rel
        if f.exists():
            parts.append(f"{'=' * 78}\n== {rel}\n{'=' * 78}\n{strip_banner(f.read_text(errors='replace'))}\n")
    zero = case / "0" if (case / "0").is_dir() else case / "0.orig"
    if zero.is_dir():
        for f in sorted(zero.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                parts.append(f"{'=' * 78}\n== {zero.name}/{f.name} (initial and boundary conditions)\n{'=' * 78}\n"
                             f"{field_bc(f)}\n")
    Path(path).write_text("\n".join(parts) if parts else "(no dictionaries found)\n")
    return len(parts)


def write_log_excerpt(L, logpath, path):
    out = ["SOLVER SESSIONS (each restart of the solver is one session)",
           "ExecutionTime is CPU time of rank 0; ClockTime is elapsed wall time. A clock/CPU ratio far above 1",
           "means the solver was waiting (machine asleep or throttled, or oversubscribed cores).", ""]
    out.append(f"{'#':>2} {'date':12} {'start':9} {'ranks':>5} {'steps':>8} {'t_first (s)':>13} {'t_last (s)':>13}"
               f" {'CPU (s)':>10} {'clock (s)':>10} {'clock/CPU':>9}")
    for i, S in enumerate(L["sessions"]):
        ratio = S["clock_s"] / S["exec_s"] if S["exec_s"] else float("nan")
        out.append(f"{i:>2} {S['date']:12} {S['time']:9} {S['nprocs']:>5} {S['n_steps']:>8} "
                   f"{(S['first_t'] or 0):>13.6g} {(S['last_t'] or 0):>13.6g} {S['exec_s']:>10.1f} "
                   f"{S['clock_s']:>10.1f} {ratio:>9.2f}")
    out += ["", "WARNINGS (grouped; numbers replaced by #)", ""]
    if not L["warnings"]:
        out.append("(none)")
    for k, w in L["warnings"].items():
        out.append(f"[{w['count']}x, t {w['t_first']} .. {w['t_last']}] {w['first']}")
        for c in w["context"]:
            out.append(f"      {c}")
    out += ["", "SOLVER HEADER (first session)", ""] + L["header"][:160]
    tail = rl.log_tail(logpath, 16384).splitlines()[-50:]
    out += ["", "LAST 50 LINES", ""] + tail
    Path(path).write_text("\n".join(out) + "\n")


# --------------------------------------------------------------------------- record
def record(case, kind=None, out=None, render=True, quiet=False):
    say = (lambda *a: None) if quiet else (lambda *a: print(*a, flush=True))
    case = Path(case).resolve()
    kind = kind or rl.kind_of(case)
    out = Path(out).resolve() if out else rl.records_dir(case, kind)
    status, why = rl.case_status(case)
    say(f"[record] {case.name} ({kind}, {status}) -> {out}")
    keep = set(KEEP) | (set() if render else {"fields"})     # --no-render keeps earlier images
    if out.exists() and any(out.iterdir()) and not ((out / "summary.json").exists() or (out / "settings.txt").exists()):
        # the folder is emptied below; never do that to a folder that is not a record (e.g. --out ~/Desktop)
        raise RuntimeError(f"{out} is not empty and holds no record (no summary.json or settings.txt); "
                           "refusing to clear it. Give an empty or new --out folder.")
    if out.exists():
        for q in out.iterdir():
            if q.name in keep:
                continue
            shutil.rmtree(q) if q.is_dir() else q.unlink()
    out.mkdir(parents=True, exist_ok=True)
    P = rl.load_json(case / "case.json", {}) or {}
    P, changed = effective_parameters(case, P)
    M = rl.load_json(case / "mesh_info.json", {}) or {}
    tref, tlab = rl.convective_scale(P, kind)
    S = OrderedDict(case=case.name, kind=kind, stage=rl.STAGES[kind], status=status, status_reason=why,
                    recorded_at=time.strftime("%Y-%m-%dT%H:%M:%S"), record_version=RECORD_VERSION,
                    source=str(case.relative_to(rl.CFD.parent)) if rl.CFD.parent in case.parents else str(case))
    if changed:
        S["caseParameters_differ_from_case_json"] = changed
    if P.get("caseName") and P["caseName"] != case.name:
        S["case_json_caseName"] = P["caseName"]
    lg = rl.solver_log(case)
    if lg is not None:
        st = lg.stat()
        S["source_log"] = dict(name=lg.name, bytes=st.st_size, mtime=time.strftime("%Y-%m-%dT%H:%M:%S",
                                                                                  time.localtime(st.st_mtime)))
    files = []
    for name in ("case.json", "results.json", "mesh_info.json", "timing.json"):
        if (case / name).exists():
            shutil.copy(case / name, out / name)
            files.append(name)
    if (case / "log.checkMesh").exists():
        shutil.copy(case / "log.checkMesh", out / "checkMesh.log")
        files.append("checkMesh.log")
    if (case / "mesh.png").exists() and (case / "mesh.png").stat().st_size < 800_000:
        shutil.copy(case / "mesh.png", out / "mesh_generator.png")
        files.append("mesh_generator.png")
    write_settings(case, out / "settings.txt")
    files.append("settings.txt")
    S["mesh"] = dict(n_cells=M.get("n_cells"), first_cell_m=(M.get("ring") or {}).get("first_cell_m") or M.get("h0_m"),
                     level=M.get("level", P.get("level")), **checkmesh_summary(case / "log.checkMesh"))
    plots = {}
    title0 = case.name

    # ---- log
    L = None
    if lg is not None:
        L = parse_log(lg)
        write_log_excerpt(L, lg, out / "log_excerpt.txt")
        files.append("log_excerpt.txt")
        if len(L["t"]):
            plot_residuals(L, tref, tlab, out / "residuals.png", f"{title0}: residuals")
            plots["residuals"] = "residuals.png"
            cols, hdr = [L["t"]], ["t_s"]
            for f, (t, r) in L["res"].items():
                cols.append(np.interp(L["t"], t, r, left=np.nan, right=np.nan) if len(t) > 1 else
                            np.full_like(L["t"], np.nan))
                hdr.append(f"{f}_initial")
            write_csv(out / "residuals.csv", hdr, cols, "first initial residual per time step; decimated")
            files.append("residuals.csv")
            plot_timestep(L, tref, tlab, P.get("maxCo"), out / "timestep.png", f"{title0}: time step, Courant, cost")
            plots["timestep"] = "timestep.png"
            dt = L["dt"][np.isfinite(L["dt"])]
            co = L["co"][np.isfinite(L["co"])]
            ses = []
            for x in L["sessions"]:
                ses.append(dict(date=x["date"], start=x["time"], nprocs=x["nprocs"], n_steps=x["n_steps"],
                                t_first=x["first_t"], t_last=x["last_t"], cpu_s=x["exec_s"], clock_s=x["clock_s"],
                                clock_over_cpu=round(x["clock_s"] / x["exec_s"], 2) if x["exec_s"] else None))
            S["run"] = dict(n_steps=int(len(L["t"])), t_first_s=float(L["t"][0]), t_last_s=float(L["t"][-1]),
                            t_last_nd=float(L["t"][-1] / tref), nd_unit=tlab,
                            dt_mean_s=float(dt.mean()) if len(dt) else None,
                            dt_min_s=float(dt.min()) if len(dt) else None,
                            dt_last_s=float(dt[-1]) if len(dt) else None,
                            Co_max_mean=float(co.mean()) if len(co) else None,
                            Co_max_max=float(co.max()) if len(co) else None,
                            cpu_s=float(sum(x["exec_s"] for x in L["sessions"])),
                            clock_s=float(sum(x["clock_s"] for x in L["sessions"])),
                            s_per_step_cpu=float(sum(x["exec_s"] for x in L["sessions"]) / max(1, len(L["t"]))),
                            sessions=ses,
                            warnings={w["first"][:120]: w["count"] for w in list(L["warnings"].values())[:15]})
            if P.get("endTime"):
                S["run"]["endTime_s"] = P["endTime"]
                S["run"]["fraction_of_endTime"] = float(L["t"][-1] / P["endTime"])

    # ---- loads
    if kind == "section":
        loads_section(case, P, out, S, plots, files, tref, tlab, title0)
    else:
        loads_rotor(case, P, out, S, plots, files, tref, tlab, title0)

    # ---- y+
    _, rows = read_fo(case, "yPlus1", "yPlus.dat")
    yp = {}
    for r in rows:
        if len(r) >= 5 and rl.is_number(r[2]):
            yp.setdefault(r[1], []).append([float(r[0]), float(r[2]), float(r[3]), float(r[4])])
    yp = {k: np.array(sorted(v)) for k, v in yp.items()}
    if yp:
        plot_yplus(yp, tref, tlab, out / "yplus.png", f"{title0}: y+ on the walls (yPlus function object)")
        plots["yplus"] = "yplus.png"
        t0 = S.get("window", {}).get("t0_s", -math.inf)
        stats = {}
        for k, a in yp.items():
            m = a[:, 0] >= t0
            m = m if m.any() else np.ones(len(a), bool)
            stats[k] = dict(min=float(a[m, 1].min()), max=float(a[m, 2].max()), mean=float(a[m, 3].mean()),
                            n_samples=int(m.sum()))
        S["yplus_function_object"] = stats

    # ---- field images
    if render:
        if status == "running":
            S["renders"] = dict(skipped="case is running; field images are made only from stopped or finished cases")
        elif not rl.PVBATCH.exists():
            S["renders"] = dict(skipped=f"pvbatch not found at {rl.PVBATCH}")
        else:
            fdir = out / "fields"
            cmd = ["nice", "-n", "10", str(rl.PVBATCH), "--force-offscreen-rendering", str(HERE / "render_fields.py"),
                   str(case), "--out", str(fdir), "--kind", kind]
            if S.get("St"):
                cmd += ["--st", f"{S['St']:.6g}"]
            say(f"[render] pvbatch render_fields.py ({fdir})")
            t0 = time.time()
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            (fdir).mkdir(exist_ok=True)
            (fdir / "render_log.txt").write_text(r.stdout[-20000:] + "\n" + r.stderr[-20000:])
            man = rl.load_json(fdir / "render_manifest.json", {}) or {}
            S["renders"] = dict(rc=r.returncode, seconds=round(time.time() - t0, 1), images=man.get("images", []),
                                time_s=man.get("time"), read_as=man.get("read_as"), notes=man.get("notes", []),
                                yplus_inst=man.get("yplus_inst"), yplus_mean=man.get("yplus_mean"))
            if r.returncode:
                say(f"[render] failed (rc {r.returncode}); see {fdir / 'render_log.txt'}")
    else:
        man = rl.load_json(out / "fields" / "render_manifest.json")
        if man:
            S["renders"] = dict(kept="images from an earlier render (--no-render)", images=man.get("images", []),
                                time_s=man.get("time"), read_as=man.get("read_as"), notes=man.get("notes", []),
                                yplus_inst=man.get("yplus_inst"), yplus_mean=man.get("yplus_mean"))
        else:
            S["renders"] = dict(skipped="--no-render")
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    S["record_bytes"] = int(size)
    S["files"] = sorted(str(f.relative_to(out)) for f in out.rglob("*") if f.is_file())
    (out / "summary.json").write_text(json.dumps(S, indent=1, default=float))
    write_readme(out, S, P, plots, kind, tlab)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    say(f"[record] {out} : {size / 1e6:.2f} MB, {len(list(out.rglob('*')))} files")
    if size > 6e6:
        say("[record] warning: record larger than 6 MB")
    return out, S


def loads_section(case, P, out, S, plots, files, tref, tlab, title0):
    hdr, rows = read_fo(case, "forceCoeffs1", "coefficient.dat")
    if not rows or not hdr:
        S["loads"] = "no forceCoeffs1 output"
        return
    col = {n: i for i, n in enumerate(hdr)}
    a = numeric(rows, len(hdr))
    t = a[:, 0]
    Cd, Cl = a[:, col["Cd"]], a[:, col["Cl"]]
    Cm = -a[:, col["CmPitch"]] if "CmPitch" in col else np.zeros_like(t)
    U, c = P.get("Uinf", 1.0), P.get("cRef", 0.048)
    nav = P.get("nAvg", 0) * tref
    t_end = t[-1]
    t0 = max(t[0], t_end - nav) if nav else t[0] + 0.5 * (t_end - t[0])
    complete = bool(nav and t_end - t[0] >= nav * (1 - 1e-6) and P.get("endTime") and t_end >= P["endTime"] * 0.999)
    w = t >= t0
    S["window"] = dict(t0_s=float(t0), t1_s=float(t_end), t0_nd=float(t0 / tref), t1_nd=float(t_end / tref),
                       intended_nd=P.get("nAvg"), complete=complete, unit=tlab)
    half = t[w] < 0.5 * (t[w][0] + t[w][-1])
    for nm, y in (("Cd", Cd), ("Cl", Cl), ("Cm", Cm)):
        S[f"{nm}_mean"] = float(y[w].mean())
        S[f"{nm}_std"] = float(y[w].std())
        if half.any() and (~half).any():
            S[f"{nm}_drift"] = float(y[w][~half].mean() - y[w][half].mean())
    # pressure / viscous split
    fh, frows = read_fo(case, "forces1", "force.dat")
    cdp = cdv = None
    if frows:
        F = numeric(frows, 10)
        d = np.array(P.get("dragDir", [1, 0, 0])[:2])
        q = 0.5 * P.get("rhoInf", 1.204) * U * U * P.get("Aref", c * P.get("dz", 1e-3))
        cdp_t = F[:, 4:6] @ d / q
        cdv_t = F[:, 7:9] @ d / q
        m = F[:, 0] >= t0
        if m.any():
            S["Cd_pressure_mean"] = float(cdp_t[m].mean())
            S["Cd_viscous_mean"] = float(cdv_t[m].mean())
        cdp = np.interp(t, F[:, 0], cdp_t)
        cdv = np.interp(t, F[:, 0], cdv_t)
    cols = [t, t / tref, Cd, Cl, Cm] + ([cdp, cdv] if cdp is not None else [])
    hdrs = ["t_s", "t_U_over_c", "Cd", "Cl", "Cm_z_ccw"] + (["Cd_pressure", "Cd_viscous"] if cdp is not None else [])
    n = write_csv(out / "coefficients.csv", hdrs, cols,
                  f"{case.name}: section coefficients, q = 0.5 U^2, A = c dz, c = {c} m; Cm about the centroid, CCW +\n"
                  f"averaging window t U/c = {t0 / tref:.4g} .. {t_end / tref:.4g}; decimated")
    files.append("coefficients.csv")
    S["coefficients_csv_rows"] = n
    plot_history(t / tref, [("Cd", Cd), ("Cl", Cl), ("Cm (centroid, CCW +)", Cm)],
                 (t0 / tref, t_end / tref), out / "coefficients.png",
                 f"{title0}: force coefficients (shaded: averaging window)", tlab)
    plots["coefficients"] = "coefficients.png"
    sp = spectrum(t[w], Cl[w])
    if sp is None:
        S["spectrum_note"] = f"no spectrum: {int(w.sum())} samples in the averaging window (32 needed)"
    if sp is not None:
        St = sp["fp"] * c / U
        S.update(St=float(St), St_peak_frac=sp["frac"], f_shed_Hz=sp["fp"],
                 n_cycles_window=float(sp["fp"] * sp["T"]) if np.isfinite(sp["fp"]) else None)
        sp2 = spectrum(t[w], Cd[w])
        plot_spectrum(sp, c / U, "Strouhal number St = f c / U", [(St, f"St = {St:.3g} ({sp['fp']:.0f} Hz)"),
                                                                  (2 * St, "2 St (drag)")],
                      out / "spectrum.png", f"{title0}: spectra over the averaging window", sp2, "Cl", "Cd")
        plots["spectrum"] = "spectrum.png"


def loads_rotor(case, P, out, S, plots, files, tref, tlab, title0):
    _, mrows = read_fo(case, "forcesRotor", "moment.dat")
    _, frows = read_fo(case, "forcesRotor", "force.dat")
    if not mrows:
        S["loads"] = "no forcesRotor output"
        return
    m = numeric(mrows, 10)
    f = numeric(frows, 10) if frows else np.zeros((0, 10))
    s, dz, q, A, R = P["sense"], P["dz"], P["qRef"], P["Aref"], P["R"]
    t = m[:, 0]
    CQ = s * m[:, 3] / dz / (q * A * R)
    Cx = np.interp(t, f[:, 0], f[:, 1]) / dz / (q * A) if len(f) > 1 else np.full_like(t, np.nan)
    Cy = np.interp(t, f[:, 0], f[:, 2]) / dz / (q * A) if len(f) > 1 else np.full_like(t, np.nan)
    blades = []
    for k in (1, 2, 3):
        _, br = read_fo(case, f"forcesBlade{k}", "moment.dat")
        if br:
            b = numeric(br, 10)
            blades.append(np.interp(t, b[:, 0], s * b[:, 3] / dz / (q * A * R)))
    rotating = P.get("mode") == "rotating"
    t_end = t[-1]
    if rotating:
        nav = P["nAvgRev"] * P["Trev"]
        lam = P["lam"]
    else:
        nav = P.get("nAvgConv", 0) * tref
        lam = 0.0
    t0 = max(t[0], t_end - nav)
    complete = bool(t_end - t[0] >= nav * (1 - 1e-6) and t_end >= P.get("endTime", math.inf) * 0.999)
    w = t >= t0
    S["window"] = dict(t0_s=float(t0), t1_s=float(t_end), t0_nd=float(t0 / tref), t1_nd=float(t_end / tref),
                       intended_nd=P.get("nAvgRev") if rotating else P.get("nAvgConv"), complete=complete, unit=tlab)
    S["CQ_mean"] = tmean(t[w], CQ[w])
    S["CQ_std"] = float(np.std(CQ[w]))
    if rotating:
        S["CP_mean"] = lam * S["CQ_mean"]
        S["lam"] = lam
    S["Cx_mean"], S["Cy_mean"] = tmean(t[w], Cx[w]), tmean(t[w], Cy[w])
    if blades:
        S["CQ_blade_mean"] = [tmean(t[w], b[w]) for b in blades]
    cols = [t, t / tref, CQ] + ([lam * CQ] if rotating else []) + [Cx, Cy] + blades
    hdrs = ["t_s", "revolutions" if rotating else "t_U_over_D", "CQ"] + (["CP"] if rotating else []) + \
        ["Cx", "Cy"] + [f"CQ_blade{k + 1}" for k in range(len(blades))]
    if rotating:
        az = np.mod(np.degrees(P["Omega"] * t) + P.get("thetaDeg", 0.0), 360.0)
        cols.insert(2, az)
        hdrs.insert(2, "azimuth_blade1_deg")
    n = write_csv(out / "coefficients.csv", hdrs, cols,
                  f"{case.name}: rotor, per unit span; C_Q = Q'/(q 2R R), C_P = lambda C_Q, C_x,y = F'/(q 2R)\n"
                  f"averaging window {t0 / tref:.4g} .. {t_end / tref:.4g} {tlab}; decimated")
    files.append("coefficients.csv")
    S["coefficients_csv_rows"] = n
    series = [("C_Q", CQ)] + ([("C_P", lam * CQ)] if rotating else []) + [("C_x (drag)", Cx), ("C_y", Cy)]
    plot_history(t / tref, series, (t0 / tref, t_end / tref), out / "coefficients.png",
                 f"{title0}: rotor coefficients (shaded: averaging window)", tlab)
    plots["coefficients"] = "coefficients.png"
    if rotating and blades and len(t[w]) > 10:
        edges = np.arange(0, 361, 5.0)
        acc, cnt = np.zeros(72), np.zeros(72)
        th = np.degrees(P["Omega"] * t)
        for k, b in enumerate(blades):
            thk = np.mod(P.get("thetaDeg", 0.0) + th[w] + 120.0 * k, 360.0)
            idx = np.clip(np.digitize(thk, edges) - 1, 0, 71)
            np.add.at(acc, idx, b[w])
            np.add.at(cnt, idx, 1)
        mid = 0.5 * (edges[1:] + edges[:-1])
        ph = np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan)
        fig, ax = plt.subplots(figsize=(8.0, 4.0))
        ax.plot(mid, ph, "o-", ms=3, lw=1)
        ax.axhline(0, color="k", lw=0.6)
        ax.set_xlabel("blade azimuth (deg)")
        ax.set_ylabel("single-blade C_Q")
        ax.set_xticks(np.arange(0, 361, 45))
        ax.grid(alpha=0.3)
        ax.set_title(f"{title0}: torque of one blade against its azimuth\n(three blades phase-averaged over the window)",
                     fontsize=9)
        fig.tight_layout()
        savefig(fig, out / "phase_CQ.png")
        plots["phase"] = "phase_CQ.png"
    sp = spectrum(t[w], CQ[w])
    if sp is None:
        S["spectrum_note"] = f"no spectrum: {int(w.sum())} samples in the averaging window (32 needed)"
    if sp is not None:
        if rotating:
            frot = P["Omega"] / (2 * math.pi)
            plot_spectrum(sp, 1 / frot, "frequency / rotation frequency", [(3.0, "3 per rev (blade passing)"),
                                                                            (sp["fp"] / frot, "peak")],
                          out / "spectrum.png", f"{title0}: torque spectrum over the window", lab1="C_Q")
            S["f_peak_over_frot"] = float(sp["fp"] / frot)
        else:
            D = P["D"]
            St = sp["fp"] * D / P["Uinf"]
            S["St_D"] = float(St)
            plot_spectrum(sp, D / P["Uinf"], "St_D = f D / U", [(St, f"St_D = {St:.3g}")], out / "spectrum.png",
                          f"{title0}: torque spectrum over the window", lab1="C_Q")
        plots["spectrum"] = "spectrum.png"
    _, arows = read_fo(case, "AMIWeights1", "AMIWeights.dat")
    if arows:
        try:
            v = np.array([[float(r[4]), float(r[5]), float(r[10]), float(r[11])] for r in arows])
            S["ami_weight_min"] = float(v[:, [0, 2]].min())
            S["ami_weight_max"] = float(v[:, [1, 3]].max())
        except (IndexError, ValueError):
            pass


# --------------------------------------------------------------------------- README
def fmt(v, nd=4):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        if not math.isfinite(v):
            return "n/a"
        return f"{v:.{nd}g}"
    return str(v)


def write_readme(out, S, P, plots, kind, tlab):
    run = S.get("run", {})
    win = S.get("window", {})
    R = S.get("renders", {})
    lines = [f"# Record: `{S['case']}`", ""]
    lines.append(f"Recorded {S['recorded_at']} by `cfd/post/record_case.py` from `{S['source']}`. "
                 f"Status when recorded: **{S['status']}** ({S['status_reason']}).")
    lines.append("")
    if S["case"].startswith("_"):
        lines += ["> **Test record.** The folder name starts with `_`: a smoke, pipeline or scheme test, not a "
                  "production case. Its numbers describe the test, not the blade; see `cfd/docs/RECORDS.md` "
                  "(test records).", ""]
    if S["status"] != "finished":
        lines += ["> This case had not finished when it was recorded, so averages and spectra describe only the part "
                  "that ran. Treat every number below as provisional.", ""]
    ncyc = S.get("n_cycles_window")
    if S.get("spectrum_note") or (ncyc is not None and ncyc < 10):
        lines += [("> The averaging window holds " + f"{ncyc:.1f} shedding cycles; about 10 or more"
                   if ncyc is not None else
                   "> The averaging window is too short for a spectrum (under 32 samples); about 10 or more "
                   "shedding cycles") + " are needed before means and St are converged "
                  "(cfd/docs/LEARNING_LOG.md section 6).", ""]
    if S.get("caseParameters_differ_from_case_json"):
        d = S["caseParameters_differ_from_case_json"]
        lines += ["> system/caseParameters differs from case.json for " + ", ".join(
            f"{k} ({v['case_json']} in case.json, {v['caseParameters']:g} used)" for k, v in d.items())
            + "; the values used by the solver are reported here.", ""]
    if S.get("case_json_caseName"):
        lines += [f"> case.json names this case `{S['case_json_caseName']}`; the folder was renamed (a test copy).", ""]
    if win and not win.get("complete"):
        lines += [f"> The averaging window is incomplete: {fmt(win.get('t0_nd'))} to {fmt(win.get('t1_nd'))} {tlab} "
                  f"was available against an intended {fmt(win.get('intended_nd'))} {tlab}. Means and the Strouhal "
                  "number are not converged.", ""]
    # key numbers
    lines += ["## Key numbers", "", "| Quantity | Value |", "|---|---|"]
    rows = []
    if kind == "section":
        rows += [("Angle of attack", f"{fmt(P.get('alphaDeg'))} deg"), ("Free stream", f"{fmt(P.get('Uinf'))} m/s"),
                 ("Re (c = 48 mm)", fmt(P.get("ReChord"), 3)), ("Turbulence model", P.get("turbulenceModel", "")),
                 ("Tu at the section", f"{fmt(P.get('TuBodyPercent'), 2)} %")]
        if P.get("TuInletPercent") is not None:
            ell = f"length scale {fmt((P.get('turbulenceLengthScale') or float('nan')) * 1e3, 3)} mm"
            if P.get("freestreamDecayControl") == "yes":
                ft = (f"decay control on (kInf, omegaInf): Tu {fmt(P['TuInletPercent'], 3)} % from the far field "
                      f"to the section, nu_t/nu {fmt(P.get('viscosityRatioBody'), 3)}, {ell}")
            else:
                ft = (f"no decay control ({'--decay precompensate' if P.get('freestreamDecay') else '7 Oct set-up'}):"
                      f" far-field Tu {fmt(P['TuInletPercent'], 3)} % decays to the section value; nu_t/nu "
                      f"{fmt(P.get('viscosityRatioFarField'), 3)} far field, {fmt(P.get('viscosityRatioBody'), 3)} "
                      f"at the section; {ell}")
            rows += [("Free-stream turbulence", ft)]
    else:
        rows += [("Mode", P.get("mode", "")), ("Hypothesis", P.get("hypothesis", "")),
                 ("Free stream", f"{fmt(P.get('Uinf'))} m/s"), ("Turbulence model", P.get("turbulenceModel", "")),
                 ("Wall treatment", P.get("wall", ""))]
        if P.get("mode") == "rotating":
            rows += [("Tip-speed ratio lambda", fmt(P.get("lam"))), ("Rotor speed", f"{fmt(P.get('rpm'), 4)} rpm")]
        else:
            rows += [("Frozen azimuth", f"{fmt(P.get('thetaDeg'))} deg")]
        if P.get("TuRotorPercent") is not None:
            ell = f"length scale {fmt((P.get('turbulenceLengthScale') or float('nan')) * 1e3, 3)} mm"
            if P.get("freestreamDecayControl") == "yes":
                ft = (f"decay control on (kInf, omegaInf): Tu {fmt(P['TuRotorPercent'], 3)} % from the inlet "
                      f"to the rotor, nu_t/nu {fmt(P.get('viscosityRatioRotor'), 3)}, {ell}")
            else:
                ft = (f"no decay control ({'--decay precompensate' if P.get('freestreamDecay') else '7 Oct set-up'}):"
                      f" inlet Tu {fmt(P.get('TuInletPercent'), 3)} % decays to {fmt(P['TuRotorPercent'], 3)} % at "
                      f"the rotor; nu_t/nu {fmt(P.get('viscosityRatioInlet'), 3)} inlet, "
                      f"{fmt(P.get('viscosityRatioRotor'), 3)} at the rotor; {ell}")
            rows += [("Free-stream turbulence", ft)]
    if P.get("maxCo") is not None:
        rows += [("Time-step control", f"maxCo {fmt(P.get('maxCo'))}, {P.get('nOuterCorrectors', '?')} outer correctors")]
    mesh = S.get("mesh", {})
    rows += [("Mesh", f"{mesh.get('level', '')}, {fmt(mesh.get('n_cells'))} cells, first cell "
                      f"{fmt((mesh.get('first_cell_m') or float('nan')) * 1e6, 3)} um, checkMesh "
                      + ("OK" if mesh.get("mesh_ok") else ("log not in the case" if "mesh_ok" not in mesh
                                                            else "FAILED (see checkMesh.log)")))]
    if run:
        rows += [("Simulated", f"{fmt(run.get('t_last_s'))} s = {fmt(run.get('t_last_nd'))} {tlab}"
                  + (f" ({100 * run['fraction_of_endTime']:.1f} % of endTime)" if run.get("fraction_of_endTime") else "")),
                 ("Time steps", f"{run.get('n_steps')}, deltaT mean {fmt(run.get('dt_mean_s'), 3)} s, "
                                f"max Co mean {fmt(run.get('Co_max_mean'), 3)}"),
                 ("Cost", f"CPU {fmt(run.get('cpu_s') / 3600, 3)} h, clock {fmt(run.get('clock_s') / 3600, 3)} h, "
                          f"{fmt(run.get('s_per_step_cpu'), 3)} s CPU per step")]
    if kind == "section" and "Cd_mean" in S:
        rows += [("Cd (mean +/- std)", f"{fmt(S['Cd_mean'])} +/- {fmt(S['Cd_std'], 3)}"),
                 ("Cl (mean +/- std)", f"{fmt(S['Cl_mean'])} +/- {fmt(S['Cl_std'], 3)}"),
                 ("Cm (mean +/- std)", f"{fmt(S['Cm_mean'])} +/- {fmt(S['Cm_std'], 3)}")]
        if "Cd_pressure_mean" in S:
            rows += [("Cd pressure / viscous", f"{fmt(S['Cd_pressure_mean'])} / {fmt(S['Cd_viscous_mean'], 3)}")]
        if "St" in S:
            rows += [("Strouhal number (Cl)", f"{fmt(S['St'], 3)} ({fmt(S.get('f_shed_Hz'), 4)} Hz), "
                                              f"{fmt(S.get('n_cycles_window'), 3)} cycles in the window")]
    if kind == "rotor" and "CQ_mean" in S:
        rows += [("C_Q (mean +/- std)", f"{fmt(S['CQ_mean'])} +/- {fmt(S['CQ_std'], 3)}")]
        if "CP_mean" in S:
            rows += [("C_P = lambda C_Q", fmt(S["CP_mean"]))]
    if win:
        rows += [("Averaging window", f"{fmt(win.get('t0_nd'))} to {fmt(win.get('t1_nd'))} {tlab}"
                  f" ({'complete' if win.get('complete') else 'incomplete'})")]
    ypf = S.get("yplus_function_object")
    if ypf:
        rows += [("y+ (function object)", "; ".join(f"{k}: mean {fmt(v['mean'], 3)}, max {fmt(v['max'], 3)}"
                                                    for k, v in ypf.items()))]
    for k, v in rows:
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines += ["## Plots and how to read them", ""]
    P_ = {
        "coefficients": (
            "Force coefficients against time",
            ("The loads on the blade, made dimensionless: Cd = drag/(q c), Cl = lift/(q c), Cm = moment/(q c^2) per "
             "unit span, with q = 0.5 rho U^2. Time is in convective units t U/c: one unit is the time the free "
             "stream takes to travel one chord. The start is a transient (the flow is impulsively started from "
             "uniform flow) and must be discarded. The orange band is the averaging window; the red line and band "
             "are the window mean and +/- one standard deviation. A converged URANS run shows a statistically "
             "steady signal in the window: the oscillation (vortex shedding) repeats with constant amplitude and "
             "the mean does not drift. Compare the two halves of the window (the `*_drift` entries in "
             "summary.json) to check this.") if kind == "section" else
            ("Torque coefficient C_Q = Q'/(q 2R R) and power coefficient C_P = lambda C_Q per unit span (q = 0.5 rho "
             "U^2, swept width 2R) against revolutions (rotating) or t U/D (static), plus the in-plane force "
             "coefficients. The first revolutions are a start-up transient; the shaded band is the averaging "
             "window (the last revolutions), the red line and band the window mean and +/- one standard deviation. "
             "Three blades produce a torque ripple at three times the rotation frequency.")),
        "spectrum": (
            "Spectrum and Strouhal number",
            ("The power spectrum of Cl (and Cd) over the averaging window, against the Strouhal number St = f c/U. "
             "The tallest peak of Cl is the vortex-shedding frequency; drag oscillates at twice that frequency "
             "because each shed vortex (upper and lower) pulls the body back once. A sharp, isolated peak means "
             "periodic shedding; a broad hump means irregular shedding or too short a window. The title gives the "
             "frequency resolution 1/T_window: peaks closer than that cannot be told apart, and fewer than about "
             "10 cycles in the window make St uncertain by more than 10 %.") if kind == "section" else
            ("The torque spectrum over the window. For a rotating rotor the axis is frequency divided by the "
             "rotation frequency, so blade passing appears at 3; for a static rotor the axis is St_D = f D/U, the "
             "shedding frequency of the whole rotor.")),
        "phase": ("Single-blade torque against azimuth",
                  "The torque of one blade, phase-averaged over the three blades and the averaging window, against "
                  "its azimuth (5-degree bins). Positive values drive the rotor. A drag-type rotor gets most of its "
                  "torque over the half-turn where the concave side meets the wind and loses some on the return."),
        "residuals": ("Residuals",
                      "For each solved field (Ux, Uy, p, k, omega, and gammaInt, ReThetat for the transition model) "
                      "the initial residual of the first solve in each time step: the normalised imbalance of the "
                      "discretised equation before the linear solver works on it. In a transient (PIMPLE) run "
                      "residuals do not fall to machine zero; they settle to a band whose level depends on the time "
                      "step and on how unsteady the flow is. Watch for a rising trend (divergence), sudden spikes "
                      "(a bad cell, or the time step jumping), or the pressure residual not dropping within a step."),
        "timestep": ("Time step, Courant number and cost",
                     "Top: the adaptive time step deltaT. Middle: the largest Courant number Co = U deltaT / dx in "
                     "the mesh, which the solver holds at or below maxCo by shrinking deltaT; the smallest, fastest "
                     "cells (here the blade corners) set the time step for the whole mesh. Bottom: cumulative CPU "
                     "time (ExecutionTime) against wall-clock time (ClockTime) over the time steps. On a healthy "
                     "run the two lines rise together; when the clock line runs away from the CPU line the solver "
                     "was not running, for example because the Mac slept (7 Oct, one session: ClockTime 8886 s "
                     "against ExecutionTime 282 s). Dotted lines mark restarts."),
        "yplus": ("y+ against time",
                  "y+ = u_tau y / nu is the height of the first cell centre in wall units (u_tau = sqrt(tau_w/rho) "
                  "is the friction velocity). The low-Reynolds-number treatment used for the section (and for "
                  "kOmegaSSTLM) needs y+ of about 1 or less everywhere on the wall; wall functions need about "
                  "30-300. The band is the min-max over the wall, the line the wall average, sampled by the yPlus "
                  "function object. The maximum sits at the sharp corners, where the flow accelerates around "
                  "the end faces."),
    }
    for key in ("coefficients", "spectrum", "phase", "residuals", "timestep", "yplus"):
        if key in plots:
            t, txt = P_[key]
            lines += [f"### {t}", "", f"![{t}]({plots[key]})", "", txt, ""]
    if S.get("spectrum_note"):
        lines += [f"(No spectrum plot: {S['spectrum_note'][len('no spectrum: '):]}.)", ""]
    imgs = R.get("images") or []
    if imgs:
        mesh_only = any("mesh images only" in n for n in (R.get("notes") or []))
        when = ("Mesh only: the case kept no flow fields after t = 0 (finished cases keep the last write; test "
                "copies may keep none)." if mesh_only else
                f"Fields at t = {fmt(R.get('time_s'))} s, read from the {R.get('read_as', '')} case.")
        lines += ["## Field images (ParaView, `fields/`)", "",
                  f"Rendered by `cfd/post/render_fields.py`. {when} Colour ranges are fixed per quantity so records "
                  "of different cases can be compared side by side. The grey shape is the blade (a hole in the "
                  "mesh).", ""]
        desc = [
            ("mesh_domain", "Whole computational domain. The far-field boundary is many chords away so that it "
                            "does not disturb the flow near the blade."),
            ("mesh_near", "The mesh within a few chords: a body-fitted layer of thin cells around the blade, a "
                          "refined band where the wake goes, and coarser cells further out."),
            ("mesh_cornerA_6mm", "Close-up of one blade tip: the 1.85 mm end face and its two square corners."),
            ("mesh_cornerA_0p8mm", "Closer: the wall-normal cell layers growing away from the wall at a geometric "
                                   "rate."),
            ("mesh_cornerA_0p1mm", "Closest: the first cells at the corner. Their height (first cell h0) sets y+; "
                                   "compare with the y+ plots."),
            ("mesh_ami", "The sliding interface (AMI) between the rotating disc and the fixed outer mesh; the two "
                         "sides do not share nodes, and the AMI interpolates fluxes across it."),
            ("velocity_near", "Velocity magnitude |U|/U_inf near the blade (0 to 1.6). Dark: slow, separated flow; "
                              "bright: flow accelerated around the tips."),
            ("velocity_wake", "|U|/U_inf over about 9 chords of wake: the velocity deficit and the shed vortices."),
            ("velocity_mean_near", "Time-mean |UMean|/U_inf: the recirculation region behind the blade."),
            ("velocity_mean_wake", "Time-mean |UMean|/U_inf in the wake."),
            ("vorticity_near", "Spanwise vorticity omega_z c/U_inf (red counter-clockwise, blue clockwise): the "
                               "shear layers leaving the sharp tips and rolling up into vortices."),
            ("vorticity_wake", "omega_z c/U_inf in the wake: the von Karman street of alternating vortices."),
            ("cp_near", "Pressure coefficient Cp = (p - p_inf)/(0.5 U_inf^2): Cp = 1 at a stagnation point, "
                        "negative where the flow is fast or in vortex cores. Pressure drag comes from high Cp on the "
                        "front and low Cp on the back."),
            ("cp_mean_near", "Time-mean Cp."),
            ("nut_ratio_near", "Turbulent viscosity ratio nu_t/nu (log scale): where the turbulence model adds "
                               "mixing. High in separated shear layers and wakes; it should be small (order 1-10s) in "
                               "the attached boundary layer of a transitional run."),
            ("nut_ratio_wake", "nu_t/nu in the wake."),
            ("lic_near", "Line-integral convolution: a texture smeared along the velocity direction, coloured by "
                         "|U|/U_inf. It shows the flow topology (separation, vortices, saddle points) at every point."),
            ("lic_mean_near", "LIC of the time-mean velocity: the mean recirculation bubbles."),
            ("streamlines_near", "Streamlines of the velocity: lines everywhere tangent to U."),
            ("streamlines_mean_near", "Streamlines of the time-mean velocity: closed loops are mean recirculation "
                                      "bubbles."),
            ("gammaInt_near", "Intermittency gammaInt of the transition model: 0 where the boundary layer is "
                              "laminar, 1 where it is turbulent (and in the free stream, by its boundary condition)."),
            ("gammaInt_wall", "gammaInt in a 5 mm window on the wall a quarter of the way round the blade: the "
                              "thin laminar (dark) layer next to the wall, and where it turns turbulent."),
            ("surface_inst", "Wall distributions along the blade (s/c from tip A's outer corner, counter-clockwise): "
                             "Cp (axis inverted, as is customary), skin friction Cf (sign = near-wall flow "
                             "direction; a sign change marks separation or reattachment) and y+ of the first cell."),
            ("surface_mean", "The same from the time-mean fields."),
            ("vorticity_anim", "Vorticity at every saved write time (see the note on frame spacing)."),
            ("vorticity_frames", "Vorticity at every saved write time, as a strip."),
        ]
        for stem, txt in desc:
            hit = [i for i in imgs if Path(i).stem == stem]
            if hit:
                lines += [f"**{stem}**: {txt}", "", f"![{stem}](fields/{hit[0]})", ""]
        for nt in R.get("notes") or []:
            lines.append(f"- Note: {nt}")
        lines.append("")
    elif R.get("skipped"):
        lines += ["## Field images", "", f"Not rendered: {R['skipped']}.", ""]
    elif R.get("rc"):
        lines += ["## Field images", "", "Rendering failed; see `fields/render_log.txt`.", ""]
    lines += ["## Other files", "",
              "- `summary.json`: the numbers above and more (sessions, warnings, y+ statistics).",
              "- `settings.txt`: every dictionary that defines the run, and the boundary conditions.",
              "- `log_excerpt.txt`: solver sessions (CPU against clock time), warnings, header, last 50 lines.",
              "- `coefficients.csv`, `residuals.csv`: decimated histories (at most 5000 rows) for re-plotting.",
              "- `checkMesh.log`, `mesh_info.json`: mesh quality and generator parameters.",
              "", "Background for every plot: `cfd/docs/LEARNING_LOG.md`.", ""]
    (out / "README.md").write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case")
    ap.add_argument("--kind", choices=["section", "rotor"])
    ap.add_argument("--out")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    case = Path(a.case)
    if not case.is_dir():
        sys.exit(f"record_case: no such case folder {case}")
    record(case, a.kind, a.out, render=not a.no_render, quiet=a.quiet)


if __name__ == "__main__":
    main()
