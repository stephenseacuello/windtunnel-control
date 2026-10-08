#!/usr/bin/env python3
"""Run Stage 2 (roughness) cases one after another, resume-safe (adapted from cfd/section2d/queue.py).

    python3 cfd/stage2/queue.py queues/S2a_ks_U23.txt [queues/S2b_speeds.txt ...]   # foreground
    python3 cfd/stage2/queue.py --detach queues/S2a_ks_U23.txt queues/S2b_speeds.txt
    taskpolicy -c background python3 cfd/stage2/queue.py --detach --np 2 queues/S2a_ks_U23.txt   # efficiency cores
    python3 cfd/stage2/queue.py --status cfd/stage2/queues/S2*.txt
    python3 cfd/stage2/queue.py --pause          # running case writes and stops; queue exits after it
    python3 cfd/stage2/queue.py --csv            # rebuild results/stage2_polars.csv only

Queue files (paths relative to cfd/stage2/ or absolute): one case per line,
    alpha_deg  U_ms  model  wall  [key=value ...]
model SST or LM, wall wf or tex; keys ks, ksends (um), cs, t (mm), seed, nseg, tu (%),
maxco, nouter, nconv, navg, lt (m), decay (run_case.py options). '#' starts a comment.

Behaviour (as Stage 1)
  * a case whose results.json says complete is skipped; a partial case resumes from its last
    write; a failed case is logged and the queue moves on (re-running retries it);
  * after every completed case results/stage2_polars.csv is rebuilt from all runs/*/results.json
    (folders starting with '_' are left out), then the post-case hook runs (default
    cfd/stage2/after_case.sh: the case record via cfd/post/record_case.py into
    cfd/stage2/results/records/<case>/; --hook <path> for another, e.g. cfd/post/after_case.sh
    once it routes cfd/stage2 cases, see README); 30 min limit; a hook failure never stops the queue;
  * queues/STOP (made by --pause) stops the queue before the next case; queues/LOCK holds the
    pid of a running queue, and a second queue refuses to start while that pid is alive;
  * on battery power the queue waits for AC power (--allow-battery overrides);
  * --np sets the MPI ranks of every case (default 4; 2 on the efficiency cores).
--detach forks into the background at the current priority (under 'taskpolicy -c background'
every child inherits the efficiency-core clamp), holds caffeinate -is and logs to
results/queue_<date>.log.
"""
import argparse
import csv
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != HERE]
_spec = importlib.util.spec_from_file_location("stage2_run_case", HERE / "run_case.py")
run_case = importlib.util.module_from_spec(_spec)
sys.modules["stage2_run_case"] = run_case
_spec.loader.exec_module(run_case)

RESULTS = HERE / "results"
CSV = RESULTS / "stage2_polars.csv"
STOP = HERE / "queues" / "STOP"
LOCK = HERE / "queues" / "LOCK"
COLUMNS = ["name", "wall", "alpha_deg", "U_ms", "Re_c", "model", "Ks_um", "KsEnds_um", "Cs", "tex_t_mm", "tex_seed",
           "Tu_body_pct", "Tu_upstream_probe_pct", "maxCo", "nOuter", "n_cells", "h0_m", "yP_m", "Ks_over_yP",
           "mesh_check", "nonOrthLimit", "t_end_conv", "avg_from_conv", "avg_to_conv",
           "Cd_mean", "Cd_std", "Cl_mean", "Cl_std", "Cm_mean", "Cm_std", "Cd_pressure_mean", "Cd_viscous_mean",
           "St", "St_peak_frac", "n_cycles_avg", "Cd_drift", "Cl_drift",
           "yplus_blade_mean", "yplus_blade_max", "yplus_bladeEnds_mean", "yplus_bladeEnds_max",
           "ksplus_blade_mean", "ksplus_blade_max",
           "dt_mean_s", "Co_max_mean", "n_steps", "wall_time_s", "run_time_s", "s_per_step", "omega_bounded_steps"]
KEYS = {"ks": float, "ksends": float, "cs": float, "t": float, "seed": int, "nseg": int, "tu": float,
        "maxco": float, "nouter": int, "nconv": float, "navg": float, "lt": float, "decay": str}
KEYMAP = {"ksends": "ks_ends"}
HOOK = HERE / "after_case.sh"
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
        if len(f) < 4:
            raise ValueError(f"{p}:{ln}: need 'alpha U model wall [key=value ...]'")
        c = dict(alpha=float(f[0]), U=float(f[1]), model=f[2], wall=f[3])
        for kv in f[4:]:
            k, v = kv.split("=", 1)
            if k not in KEYS:
                raise ValueError(f"{p}:{ln}: unknown key '{k}' (known: {', '.join(KEYS)})")
            c[KEYMAP.get(k, k)] = KEYS[k](v)
        try:
            run_case.normalise(c)
        except ValueError as e:
            raise ValueError(f"{p}:{ln}: {e}") from None
        cases.append(c)
    return cases


def name_of(c):
    return run_case.name_of(c)


def marker_state(d):
    try:
        import record_lib       # cfd/post is on sys.path through run_case.py
    except Exception as e:  # noqa: BLE001
        return "running", f"stale check unavailable ({e!r})"
    st, why = record_lib.marker_state(d)
    return ("stale", why) if st == "stale" else ("running", why)


def status_of(c):
    d = run_case.RUNS / name_of(c)
    r = d / "results.json"
    if r.exists() and json.loads(r.read_text()).get("complete"):
        return "done", None, ""
    if (d / "RUNNING").exists():
        st, why = marker_state(d)
        return st, run_case.latest_proc_time(d), why
    t = run_case.latest_proc_time(d) if d.exists() else None
    if t:
        return "partial", t, ""
    return "pending", None, ""


_TIME = re.compile(r"^Time = ([-+0-9.eE]+)\s*$")
_CLOCK = re.compile(r"^ExecutionTime = ([-+0-9.eE]+) s\s+ClockTime = ([-+0-9.eE]+) s")


def log_progress(case_dir, n_steps=200):
    """(Stage 1 code) progress of a running case from the tail of log.pimpleFoam."""
    lg = Path(case_dir) / "log.pimpleFoam"
    try:
        size, mtime = lg.stat().st_size, lg.stat().st_mtime
    except OSError:
        return None
    nbytes = 1 << 20
    while True:
        with open(lg, "rb") as f:
            f.seek(max(0, size - nbytes))
            lines = f.read(nbytes).decode("utf-8", "replace").splitlines()
        if size > nbytes:
            lines = lines[1:]
        t_last, t_cur, steps, prev_clock = None, None, [], None
        for ln in lines:
            if ln.startswith("Exec "):
                steps, prev_clock = [], None
                continue
            m = _TIME.match(ln)
            if m:
                t_cur = t_last = float(m.group(1))
                continue
            m = _CLOCK.match(ln)
            if m and t_cur is not None:
                clock = float(m.group(2))
                if prev_clock is not None and clock < prev_clock:
                    steps = []
                steps.append((t_cur, clock))
                prev_clock = clock
        if len(steps) > n_steps or nbytes >= size or nbytes >= 64 << 20:
            break
        nbytes *= 4
    if t_last is None:
        return None
    out = dict(t=t_last, n=0, s_per_step=None, s_per_time=None, age=time.time() - mtime)
    n = min(n_steps, len(steps) - 1)
    if n >= 1:
        (ta, ca), (tb, cb) = steps[-1 - n], steps[-1]
        out.update(n=n, s_per_step=(cb - ca) / n, s_per_time=(cb - ca) / (tb - ta) if tb > ta else None)
    return out


def rebuild_csv():
    rows = []
    for r in sorted(run_case.RUNS.glob("*/results.json")):
        if r.parent.name.startswith("_"):
            continue
        d = json.loads(r.read_text())
        if d.get("complete"):
            rows.append(d)
    RESULTS.mkdir(exist_ok=True)
    with open(CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for d in rows:
            w.writerow({k: (f"{v:.6g}" if isinstance(v, float) else v) for k, v in d.items() if k in COLUMNS})
    return len(rows)


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S ") + msg, flush=True)


def on_ac_power():
    try:
        out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return True
    return "Battery Power" not in out


def wait_for_ac(allow_battery):
    if allow_battery or on_ac_power():
        return
    log("queue: on battery power; waiting for AC power before the next case (--allow-battery skips this)")
    while not on_ac_power():
        if STOP.exists():
            return
        time.sleep(60)
    log("queue: AC power back")


def run_after_case_hook(case_dir, hook=None, timeout=None):
    """'<hook> <case_dir>' after a completed case; never fatal (Stage 1 behaviour)."""
    hook = Path(hook) if hook else HOOK
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
    except Exception as e:  # noqa: BLE001
        log(f"hook: error {e!r}; the queue goes on")
        return "error"


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def lock_holder():
    """pid of a live Stage 2 queue holding queues/LOCK, or None."""
    try:
        pid = int(LOCK.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return pid if pid > 0 and pid != os.getpid() and _pid_alive(pid) else None


def take_lock():
    LOCK.parent.mkdir(exist_ok=True)
    pid = lock_holder()
    if pid:
        raise SystemExit(f"{LOCK}: another Stage 2 queue (pid {pid}) is running")
    LOCK.write_text(f"{os.getpid()} {time.strftime('%Y-%m-%dT%H:%M:%S')}\n")


def release_lock():
    try:
        if LOCK.exists() and LOCK.read_text().split()[0] == str(os.getpid()):
            LOCK.unlink()
    except OSError:
        pass


def run_queue(files, allow_battery=False, np=run_case.NP, hook=None):
    take_lock()
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
        log(f"queue: {len(todo)} unique cases from {', '.join(map(str, files))}; {np} ranks; pid {os.getpid()}")
        counts = {}
        for i, c in enumerate(todo, 1):
            if STOP.exists():
                log(f"queue: {STOP} present, stopping before case {i}/{len(todo)}")
                break
            wait_for_ac(allow_battery)
            if STOP.exists():
                log(f"queue: {STOP} present, stopping before case {i}/{len(todo)}")
                break
            n = name_of(c)
            log(f"case {i}/{len(todo)}: {n}")
            try:
                st = run_case.run(c, np=np)
            except Exception as e:  # noqa: BLE001
                st = "failed"
                log(f"case {n}: exception {e!r}")
            counts[st] = counts.get(st, 0) + 1
            if st == "complete":
                try:
                    log(f"csv: {rebuild_csv()} complete cases in {CSV}")
                except Exception as e:  # noqa: BLE001
                    log(f"csv: rebuild failed {e!r}")
                run_after_case_hook(run_case.RUNS / n, hook)
            if st == "stopped":
                log("queue: case paused by --pause; stopping")
                break
        log(f"queue finished: {counts}")
        rebuild_csv()
    finally:
        release_lock()


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


def _age(s):
    return f"{s:.0f} s" if s < 120 else f"{s / 60:.0f} min" if s < 7200 else f"{s / 3600:.1f} h"


def show_status(files):
    tot = {"done": 0, "running": 0, "stale": 0, "partial": 0, "pending": 0}
    seen = {}
    for f in files:
        print(f"== {f}")
        for c in parse_queue(f):
            n = name_of(c)
            if n in seen:
                print(f"  {seen[n][1]:8s} {n} (also in {seen[n][0]}; counted once)")
                continue
            st, t, why = status_of(c)
            seen[n] = (f, st)
            tot[st] += 1
            d = run_case.RUNS / n
            try:
                P = json.loads((d / "case.json").read_text())
            except (OSError, ValueError):
                P = {}
            tc = P.get("convTime")
            extra = f" at {t / tc:.1f} c/U (last write)" if t and tc else ""
            if st == "running" and tc:
                g = log_progress(d)
                if g:
                    end = P.get("endTime", 0.0)
                    extra = f" at {g['t'] / tc:.1f} of {end / tc:.0f} c/U ({100 * g['t'] / end:.1f} %)" if end \
                        else f" at {g['t'] / tc:.1f} c/U"
                    if g["s_per_step"] is not None:
                        extra += f", {g['s_per_step']:.3f} s/step over the last {g['n']} steps"
                        if g["s_per_time"] and end > g["t"]:
                            extra += f", about {_age(g['s_per_time'] * (end - g['t']))} left at that rate"
                    extra += f"; log written {_age(g['age'])} ago"
            if st == "stale":
                extra += f"; {why}"
            print(f"  {st:8s} {n}{extra}")
    print(f"{len(seen)} unique cases: {tot}")


def detach(files, allow_battery=False, np=run_case.NP, hook=None):
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
    subprocess.Popen(["caffeinate", "-is", "-w", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, run_case._on_signal)
    try:
        run_queue(files, allow_battery, np, hook)
    finally:
        os._exit(0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--detach", action="store_true", help="run in the background (see above)")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--pause", action="store_true")
    ap.add_argument("--csv", action="store_true")
    ap.add_argument("--np", type=int, default=run_case.NP, help="MPI ranks per case (default %(default)d)")
    ap.add_argument("--hook", help=f"post-case hook (default {HOOK})")
    ap.add_argument("--allow-battery", action="store_true",
                    help="start cases on battery power too (default: wait for AC power)")
    a = ap.parse_args()
    if a.pause:
        return pause()
    if a.csv:
        print(f"{rebuild_csv()} complete cases -> {CSV}")
        return
    if not a.files:
        ap.error("give at least one queue file")
    for f in a.files:
        parse_queue(f)
    if a.status:
        return show_status(a.files)
    if STOP.exists():
        sys.exit(f"{STOP} exists (queue paused); delete it to run the queue")
    if lock_holder():
        sys.exit(f"{LOCK}: another Stage 2 queue (pid {lock_holder()}) is running")
    if a.detach:
        return detach(a.files, a.allow_battery, a.np, a.hook)
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, run_case._on_signal)
    run_queue(a.files, a.allow_battery, a.np, a.hook)


if __name__ == "__main__":
    main()
