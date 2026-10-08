#!/usr/bin/env python3
"""Run Stage 3 rotor cases one after another, resume-safe.

    python3 cfd/rotor2d/queue.py queues/priorityA.txt [queues/priorityB.txt ...]     # foreground
    python3 cfd/rotor2d/queue.py --detach queues/priorityA.txt queues/priorityB.txt  # background, own session
    python3 cfd/rotor2d/queue.py --status queues/priority*.txt                       # done / running / partial / pending
    python3 cfd/rotor2d/queue.py --pause      # running case writes and stops; the queue exits after it
    python3 cfd/rotor2d/queue.py --csv        # rebuild results/rotor_cp.csv and results/rotor_static.csv only

Queue files (paths relative to cfd/rotor2d/ or absolute): one case per line,
    rot  HYP  U_ms  lambda  MODEL  LEVEL  [key=value ...]      rotating (3b)
    sta  HYP  U_ms  theta   MODEL  LEVEL  [key=value ...]      static (3a)
HYP A, B or measured; MODEL SST or LM; LEVEL coarse, medium or fine. Keys (run_case.py
options): wall, np, nrev, navg, nconv, navgconv, maxco, nouter, tu, decay
(control|precompensate), lt, sense, beta, yplus, walls (y_lo,y_hi), side_bc, wdist.
'#' starts a comment.

Behaviour
  * a case whose results.json says complete is skipped;
  * a case with written time directories resumes from its last write (an
    interruption costs at most half a revolution, or nconv/10 D/U for static cases);
  * a failed case is logged and the queue moves on (re-running retries it);
  * after every completed case results/rotor_cp.csv (rotating) and
    results/rotor_static.csv (static) are rebuilt from all runs/*/results.json, one
    row per case, so rows never duplicate (folders starting with '_', i.e. _mesh and
    _test_* / _smoke_* tests, are left out);
  * then, if cfd/post/after_case.sh exists and is executable, it runs as
    'after_case.sh <case dir>' (records, plots, field images; output into this log,
    30 min limit, its process group killed at the limit); a missing, failing or
    timed-out hook is logged and never stops the queue (as cfd/section2d/queue.py);
  * the file queues/STOP (made by --pause) stops the queue before the next case;
  * a lock file (queues/LOCK, holding the pid) prevents two queues at once.
  * a case whose RUNNING marker is present and whose log was written in the last
    2 min (a solver left from an earlier launch) is not started; the queue stops.
--detach forks into a new session, holds a caffeinate -i assertion while it runs and
logs to results/queue_<date>.log (same scheme as cfd/section2d/queue.py).
"""
import argparse
import csv
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# This file is named queue.py, which shadows the standard-library module 'queue' while
# its folder is on sys.path (python3 puts the script's folder first). Keep the folder off
# sys.path so library code that imports 'queue' gets the real one; load run_case.py by its
# path (as cfd/section2d/queue.py). run_case.py puts cfd/rotor2d back at the end of
# sys.path for rotor_geometry; the standard library is found before it.
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != HERE]
_spec = importlib.util.spec_from_file_location("run_case", HERE / "run_case.py")
run_case = importlib.util.module_from_spec(_spec)
sys.modules["run_case"] = run_case
_spec.loader.exec_module(run_case)

RESULTS = HERE / "results"
CSV_CP = RESULTS / "rotor_cp.csv"
CSV_ST = RESULTS / "rotor_static.csv"
STOP = HERE / "queues" / "STOP"
LOCK = HERE / "queues" / "LOCK"
COMMON = ["name", "hypothesis", "U_ms", "model", "level", "wall", "n_cells", "h0_m", "sense", "R_m", "r_max_m",
          "Tu_rotor_pct", "freestream_decay", "lt_m", "Tu_upstream_probe_pct", "maxCo", "nOuter", "nProcs"]
TAIL = ["Cx_mean", "Cy_mean", "yplus_mean", "yplus_max", "ami_weight_min", "ami_weight_max", "dt_mean_s",
        "Co_max_mean", "n_steps", "wall_time_s", "s_per_step", "omega_bounded_steps"]
COLS_CP = COMMON + ["lam", "Omega", "rpm", "n_rev_done", "n_avg_rev", "avg_window_complete", "CP_mean", "CQ_mean",
                    "CQ_std", "CQ_min", "CQ_max", "CQ_pressure_mean", "CQ_drift_last_two_rev"] + TAIL
COLS_ST = COMMON + ["theta_deg", "t_end_conv", "avg_window_conv", "avg_window_complete", "CQ_mean", "CQ_std",
                    "CQ_sem", "CQ_pressure_mean", "Cx_std", "Cy_std", "St_D"] + TAIL
KEYS = {"wall": str, "np": int, "nrev": int, "navg": int, "nconv": int, "navgconv": int, "maxco": float,
        "nouter": int, "tu": float, "decay": str, "lt": float, "sense": str, "beta": float, "yplus": float,
        "walls": str, "side_bc": str, "wdist": int}
# post-case hook (records, plots): run after each completed case if present and executable
AFTER_CASE = HERE.parent / "post" / "after_case.sh"
HOOK_TIMEOUT_S = 1800


def parse_queue(path):
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        p = HERE / p
    cases = []
    for ln, line in enumerate(p.read_text().splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        f = line.split()
        if len(f) < 6 or f[0] not in ("rot", "sta"):
            raise ValueError(f"{p}:{ln}: need 'rot|sta HYP U lambda|theta MODEL LEVEL [key=value ...]'")
        c = dict(hyp=f[1], U=float(f[2]), model=f[4], level=f[5])
        c["lam" if f[0] == "rot" else "theta"] = float(f[3])
        if c["hyp"] not in ("A", "B", "measured") or c["model"] not in run_case.MODELS or c["level"] not in run_case.LEVELS:
            raise ValueError(f"{p}:{ln}: unknown hypothesis, model or level")
        for kv in f[6:]:
            k, v = kv.split("=", 1)
            if k not in KEYS:
                raise ValueError(f"{p}:{ln}: unknown key {k}")
            c[k] = KEYS[k](v)
        run_case.normalise(c)               # validates (e.g. LM needs wall=lowRe)
        cases.append(c)
    return cases


def name_of(c):
    return run_case.case_name(run_case.normalise(c))


def status_of(c):
    cn = run_case.normalise(c)
    d = run_case.RUNS / run_case.case_name(cn)
    r = d / "results.json"
    if r.exists() and json.loads(r.read_text()).get("complete"):
        return "done", None
    t = run_case.latest_time(d, int(cn["np"])) if d.exists() else None
    if (d / "RUNNING").exists():
        return "running", t
    if t:
        return "partial", t
    return "pending", None


def rebuild_csv():
    rot, sta = [], []
    for r in sorted(run_case.RUNS.glob("*/results.json")):
        if r.parent.name.startswith("_"):        # _mesh, _test_*, _smoke_*: not production cases
            continue
        d = json.loads(r.read_text())
        if d.get("complete"):
            (rot if d.get("mode") == "rotating" else sta).append(d)
    RESULTS.mkdir(exist_ok=True)
    for path, cols, rows in ((CSV_CP, COLS_CP, rot), (CSV_ST, COLS_ST, sta)):
        rows.sort(key=lambda d: (d["hypothesis"], d["U_ms"], d.get("lam", d.get("theta_deg", 0)), d["name"]))
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for d in rows:
                w.writerow({k: (f"{v:.6g}" if isinstance(v, float) else v) for k, v in d.items() if k in cols})
    return len(rot), len(sta)


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S ") + msg, flush=True)


def _lock():
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text().split()[0])
            os.kill(pid, 0)
            sys.exit(f"another queue is running (pid {pid}, {LOCK}); stop it or delete the lock if stale")
        except (ProcessLookupError, ValueError):
            pass
    LOCK.parent.mkdir(exist_ok=True)
    LOCK.write_text(f"{os.getpid()}\n")


def run_after_case_hook(case_dir, hook=None, timeout=None):
    """Run '<hook> <case_dir>' (default cfd/post/after_case.sh) after a completed case.
    Same as cfd/section2d/queue.py run_after_case_hook.

    Non-fatal: a missing or non-executable hook is skipped, a non-zero exit, a timeout
    (the hook's process group is killed) or any error is logged and the queue goes on.
    Only a stop signal to the queue (SIGTERM/SIGINT) propagates; it also kills the hook.
    The hook inherits this process's stdout, with stderr merged into it, so under
    --detach its output is appended to results/queue_<date>.log; it also inherits the
    queue's scheduling clamp (taskpolicy -c background keeps it on the efficiency cores).
    Returns the exit code, 'timeout', 'missing', 'skipped' or 'error'."""
    hook = Path(hook) if hook else AFTER_CASE
    timeout = HOOK_TIMEOUT_S if timeout is None else timeout
    try:
        if not (Path(case_dir) / "results.json").is_file():
            log(f"hook: no results.json in {case_dir}; not run")
            return "skipped"
        if not hook.is_file() or not os.access(hook, os.X_OK):
            log(f"hook: {hook} {'is not executable' if hook.is_file() else 'not found'}; skipped")
            return "missing"
        log(f"hook: {hook} {case_dir} (limit {timeout:g} s)")
        sys.stdout.flush()
        sys.stderr.flush()
        t0 = time.monotonic()
        p = subprocess.Popen([str(hook), str(case_dir)], stdin=subprocess.DEVNULL, stdout=None,
                             stderr=subprocess.STDOUT, start_new_session=True)
        run_case._CHILD.append(p)
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            run_case._kill(p)
            rc = "timeout"
        finally:
            if p in run_case._CHILD:
                run_case._CHILD.remove(p)
        dt = time.monotonic() - t0
        if rc == 0:
            log(f"hook: done in {dt:.0f} s")
        elif rc == "timeout":
            log(f"hook: killed after {timeout:g} s; the queue goes on")
        else:
            log(f"hook: exit code {rc} after {dt:.0f} s; the queue goes on")
        return rc
    except Exception as e:  # noqa: BLE001 - a hook must never stop the queue
        log(f"hook: error {e!r}; the queue goes on")
        return "error"


def run_queue(files):
    _lock()
    try:
        cases = []
        for f in files:
            cases += parse_queue(f)
        seen, todo = set(), []
        for c in cases:
            n = name_of(c)
            if n not in seen:
                seen.add(n)
                todo.append(c)
        log(f"queue: {len(todo)} unique cases from {', '.join(map(str, files))}; pid {os.getpid()}")
        counts = {}
        for i, c in enumerate(todo, 1):
            if STOP.exists():
                log(f"queue: {STOP} present, stopping before case {i}/{len(todo)}")
                break
            n = name_of(c)
            log(f"case {i}/{len(todo)}: {n}")
            try:
                st = run_case.run(c)
            except Exception as e:  # noqa: BLE001 - keep the queue going
                st = "failed"
                log(f"case {n}: exception {e!r}")
            counts[st] = counts.get(st, 0) + 1
            if st == "complete":
                try:
                    nr, ns = rebuild_csv()
                    log(f"csv: {nr} rotating -> {CSV_CP}, {ns} static -> {CSV_ST}")
                except Exception as e:  # noqa: BLE001 - keep the queue going; --csv rebuilds it later
                    log(f"csv: rebuild failed {e!r}")
                run_after_case_hook(run_case.RUNS / n)
            if st == "stopped":
                log("queue: case paused by --pause; stopping")
                break
            if st == "busy":
                log("queue: a solver from an earlier launch is still writing this case; stopping")
                break
        log(f"queue finished: {counts}")
        rebuild_csv()
    finally:
        LOCK.unlink(missing_ok=True)


def pause():
    STOP.parent.mkdir(exist_ok=True)
    STOP.write_text(time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")
    n = 0
    for r in run_case.RUNS.glob("*/RUNNING"):
        run_case.set_stop_at(r.parent, "writeNow")
        print(f"stopAt writeNow set in {r.parent}")
        n += 1
    print(f"{STOP} created; {n} running case(s) will write and stop at the next time step. "
          f"Delete {STOP} and re-launch to resume.")


def show_status(files):
    tot = {"done": 0, "running": 0, "partial": 0, "pending": 0}
    for f in files:
        print(f"== {f}")
        for c in parse_queue(f):
            st, t = status_of(c)
            tot[st] += 1
            extra = ""
            if t:
                P = run_case.RUNS / name_of(c) / "case.json"
                if P.exists():
                    d = json.loads(P.read_text())
                    extra = (f" at {t / d['Trev']:.2f} of {d['nRev']} rev" if d["mode"] == "rotating"
                             else f" at {t / d['convTime']:.1f} of {d['nConv']} D/U")
            print(f"  {st:8s} {name_of(c)}{extra}")
    print(tot)


def detach(files):
    RESULTS.mkdir(exist_ok=True)
    logf = RESULTS / time.strftime("queue_%Y%m%d_%H%M%S.log")
    if os.fork():
        time.sleep(1.0)
        print(f"queue started in the background; log: {logf}")
        print(f"status: python3 {HERE / 'queue.py'} --status {' '.join(files)}")
        print(f"pause:  python3 {HERE / 'queue.py'} --pause")
        return
    os.setsid()
    if os.fork():
        os._exit(0)
    fd = os.open(logf, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    nul = os.open(os.devnull, os.O_RDONLY)
    os.dup2(nul, 0)
    subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, run_case._on_signal)
    try:
        run_queue(files)
    finally:
        os._exit(0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--detach", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--pause", action="store_true")
    ap.add_argument("--csv", action="store_true")
    a = ap.parse_args()
    if a.pause:
        return pause()
    if a.csv:
        nr, ns = rebuild_csv()
        print(f"{nr} rotating -> {CSV_CP}; {ns} static -> {CSV_ST}")
        return
    if not a.files:
        ap.error("give at least one queue file")
    for f in a.files:
        parse_queue(f)
    if a.status:
        return show_status(a.files)
    if STOP.exists():
        sys.exit(f"{STOP} exists (queue paused); delete it to run the queue")
    if a.detach:
        return detach(a.files)
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, run_case._on_signal)
    run_queue(a.files)


if __name__ == "__main__":
    main()
