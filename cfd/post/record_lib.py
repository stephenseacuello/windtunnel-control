"""Shared helpers for the per-case records (record_case.py, render_fields.py, record_all.py).

Standard library only, so the system python3 and ParaView's pvbatch can both import it.

    kind_of(case)              'section' or 'rotor' (from the path, then case.json)
    records_dir(case)          cfd/<stage>/results/records/<case name>/
    solver_finished(case)      log.pimpleFoam ends with 'End' / 'Finalising parallel run'
    marker_state(case)         ('none' | 'running' | 'stale', reason) for the RUNNING marker that
                               run_case.py keeps while its solver runs
    case_running(case)         (True, reason) if a live RUNNING marker, a recent log write or a
                               live process mentions the case (a stale marker does not count)
    make_shadow(case, tmp)     read-only view of a case for ParaView: a temp folder of
                               symlinks to constant/, system/, processor*/ and the time
                               folders, plus an empty case.foam. Nothing in the case is
                               written, so this is safe even for a stopped, unfinished case.
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

CFD = Path(__file__).resolve().parents[1]
STAGES = {"section": "section2d", "rotor": "rotor2d"}
PVBATCH = Path("/Applications/ParaView-6.2.0.app/Contents/bin/pvbatch")
RECENT_LOG_S = 180          # a log written in the last 3 minutes means the solver may be running
STALE_MARKER_S = 600        # RUNNING marker, no solver process, no log write for 10 min: stale


def is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def time_dirs(path):
    """Numeric sub-folders of path as [(value, name)], sorted by value."""
    p = Path(path)
    if not p.is_dir():
        return []
    out = [(float(q.name), q.name) for q in p.iterdir() if q.is_dir() and is_number(q.name)]
    return sorted(out)


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def kind_of(case):
    case = Path(case).resolve()
    parts = case.parts
    if "rotor2d" in parts:
        return "rotor"
    if "section2d" in parts:
        return "section"
    P = load_json(case / "case.json", {}) or {}
    if "mode" in P or "Trev" in P or "hypothesis" in P:
        return "rotor"
    return "section"


def stage_dir(kind):
    return CFD / STAGES[kind]


def records_dir(case, kind=None):
    kind = kind or kind_of(case)
    return stage_dir(kind) / "results" / "records" / Path(case).resolve().name


def log_tail(path, nbytes=4096):
    p = Path(path)
    if not p.exists():
        return ""
    with open(p, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - nbytes))
        return f.read().decode("utf-8", "replace")


def solver_log(case):
    """The solver log: log.pimpleFoam, else the newest log.*Foam."""
    case = Path(case)
    p = case / "log.pimpleFoam"
    if p.exists():
        return p
    logs = sorted(case.glob("log.*Foam"), key=lambda q: q.stat().st_mtime)
    return logs[-1] if logs else None


def solver_finished(case):
    lg = solver_log(case)
    if lg is None:
        return False
    tail = log_tail(lg, 2048)
    lines = [ln.strip() for ln in tail.splitlines() if ln.strip()]
    return bool(lines) and (lines[-1] in ("End", "Finalising parallel run")
                            or (len(lines) > 1 and lines[-2] == "End"))


def _process_mentions(case, on_error=False):
    """True if a live process's command line names the case folder (on_error if ps fails)."""
    try:
        out = subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return on_error
    pat = re.compile(re.escape(str(Path(case).resolve())) + r"(?=$|[\s/'\";&)])")
    me = str(os.getpid())
    for line in out.splitlines():
        if pat.search(line) and ("Foam" in line or "mpirun" in line or "run_case" in line) \
                and "record_case" not in line and "render_fields" not in line and me not in line:
            return True
    return False


def fmt_age(s):
    """Seconds as '42 s', '17 min' or '3.4 h'."""
    return f"{s:.0f} s" if s < 120 else f"{s / 60:.0f} min" if s < 7200 else f"{s / 3600:.1f} h"


def marker_state(case, stale_s=STALE_MARKER_S):
    """State of the RUNNING marker: ('none', ''), ('running', reason) or ('stale', reason).

    run_case.py writes RUNNING (its pid) before the solve and removes it when the solve ends,
    also on an error or a stop signal; it stays behind only if run_case.py itself was killed
    outright (SIGKILL, crash, power loss). The marker is stale when no live process names the
    case (an unreadable process list counts as live) and neither the solver log nor the marker
    was written in the last stale_s seconds. A sleeping Mac keeps its solver processes, so a
    long sleep does not make a marker stale."""
    case = Path(case)
    try:
        t_last, what = (case / "RUNNING").stat().st_mtime, "the marker"
    except OSError:
        return "none", ""
    lg = solver_log(case)
    if lg is not None:
        try:
            if lg.stat().st_mtime >= t_last:
                t_last, what = lg.stat().st_mtime, lg.name
        except OSError:
            pass
    age = time.time() - t_last
    if age <= stale_s:
        return "running", f"RUNNING marker present, {what} written {fmt_age(age)} ago"
    if _process_mentions(case, on_error=True):
        return "running", f"RUNNING marker present, a solver process names this case ({what} written {fmt_age(age)} ago)"
    return "stale", f"stale RUNNING marker: no solver process names this case, {what} last written {fmt_age(age)} ago"


def case_running(case, recent_s=RECENT_LOG_S):
    """(running, reason). Conservative: any sign of activity counts as running. A stale
    RUNNING marker (marker_state) does not; the result is then (False, <stale reason>)."""
    case = Path(case)
    state, why = marker_state(case)
    if state == "running":
        return True, why
    if state == "stale":        # no process names the case and no log write for STALE_MARKER_S
        return False, why
    lg = solver_log(case)
    if lg is not None:
        age = time.time() - lg.stat().st_mtime
        if age < recent_s and not solver_finished(case):
            return True, f"{lg.name} written {age:.0f} s ago and does not end with 'End'"
    if _process_mentions(case):
        return True, "a solver process names this case"
    return False, ""


def case_status(case):
    """'running', 'finished', 'not run', 'stale' (a stale RUNNING marker and a solver log
    that does not end with End: the run was killed; record_all treats it as stopped) or
    'stopped', with a reason."""
    run, why = case_running(case)
    if run:
        return "running", why
    if solver_finished(case):
        return "finished", "solver log ends with End" + (f"; {why}" if why else "")
    if solver_log(case) is None:
        return "not run", "no solver log" + (f"; {why}" if why else "")
    if why:
        return "stale", f"{why}; solver log does not end with End (the run was killed)"
    return "stopped", "solver log does not end with End (stopped, timed out or failed)"


def make_shadow(case, tmp):
    """Build a read-only view of `case` inside the folder `tmp` and return a dict:
        path        the shadow case folder (contains case.foam)
        case_type   'reconstructed' or 'decomposed' (which copy holds the newest fields)
        times       field times available in that copy (floats, 0 excluded unless alone)
    Folders are symlinked, never copied or written, so the real case is not touched."""
    case = Path(case).resolve()
    sh = Path(tmp) / case.name
    sh.mkdir(parents=True, exist_ok=True)
    for name in ("constant", "system"):
        if (case / name).exists():
            (sh / name).symlink_to(case / name)
    top = time_dirs(case)
    for _, name in top:
        (sh / name).symlink_to(case / name)
    procs = sorted(case.glob("processor[0-9]*"))
    for q in procs:
        (sh / q.name).symlink_to(q)
    (sh / "case.foam").touch()
    proc_t = time_dirs(case / "processor0") if procs else []
    top_v = [v for v, _ in top]
    proc_v = [v for v, _ in proc_t]
    if proc_v and (not top_v or max(proc_v) > max(top_v)):
        case_type, times = "decomposed", proc_v
    else:
        case_type, times = "reconstructed", top_v
    nonzero = [t for t in times if t > 0]
    return dict(path=sh, case_type=case_type, times=nonzero if nonzero else times)


def convective_scale(P, kind):
    """(t_ref, label) used to make time dimensionless: c/U for the section, the revolution
    period for a rotating rotor, D/U for a static rotor."""
    if not P:
        return 1.0, "t (s)"
    if kind == "section":
        return P.get("convTime", P.get("cRef", 0.048) / P.get("Uinf", 1.0)), "t U / c"
    if P.get("mode") == "rotating":
        return P["Trev"], "revolutions"
    return P.get("convTime", P.get("D", 0.2) / P.get("Uinf", 1.0)), "t U / D"
