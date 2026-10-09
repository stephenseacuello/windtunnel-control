#!/usr/bin/env python3
"""State of case folders on Unity, as JSON (run on a Unity login node by status.py, submit.py,
pull_results.py; standard library only, reads files, no OpenFOAM).

    echo '{"root": "<repo>/cfd", "stages": {"section2d": {"<case>": "<mesh key>"}, "rotor2d": {}}}' \
        | python3 cfd/hpc/remote_status.py [--squeue]

An empty dict for a stage lists every case folder in <stage>/runs/ (not _mesh, _slurm).
Prints one line '@@JSON@@{...}': cases[stage][name] = state, times, progress from the tail of
log.pimpleFoam, slurm logs; jobs = this user's squeue rows (with --squeue).
"""
import getpass
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

_TIME = re.compile(rb"^Time = ([-+0-9.eE]+)\s*$")
_CLOCK = re.compile(rb"^ExecutionTime = ([-+0-9.eE]+) s\s+ClockTime = ([-+0-9.eE]+) s")


def times(path):
    out = []
    try:
        for q in os.scandir(path):
            try:
                out.append((float(q.name), q.name))
            except ValueError:
                pass
    except OSError:
        pass
    return sorted(out)


def log_progress(lg, nbytes=1 << 19, n_steps=200):
    try:
        st = os.stat(lg)
    except OSError:
        return None
    with open(lg, "rb") as f:
        f.seek(max(0, st.st_size - nbytes))
        lines = f.read().splitlines()[1:]
    t_cur, steps = None, []
    for ln in lines:
        if ln.startswith(b"Exec "):
            steps = []
            continue
        m = _TIME.match(ln)
        if m:
            t_cur = float(m.group(1))
            continue
        m = _CLOCK.match(ln)
        if m and t_cur is not None:
            clock = float(m.group(2))
            if steps and clock < steps[-1][1]:
                steps = []
            steps.append((t_cur, clock))
    if t_cur is None:
        return dict(age_s=round(time.time() - st.st_mtime), bytes=st.st_size)
    out = dict(t=t_cur, age_s=round(time.time() - st.st_mtime), bytes=st.st_size)
    n = min(n_steps, len(steps) - 1)
    if n >= 1:
        (ta, ca), (tb, cb) = steps[-1 - n], steps[-1]
        out.update(n=n, s_per_step=(cb - ca) / n, s_per_simtime=(cb - ca) / (tb - ta) if tb > ta else None)
    return out


def case_info(d, mesh_key=None, mesh_root=None):
    info = dict(exists=d.is_dir())
    if mesh_key:
        info["mesh_ok"] = (mesh_root / mesh_key / "MESH_OK").is_file()
    if not info["exists"]:
        info["state"] = "absent"
        return info
    try:
        res = json.loads((d / "results.json").read_text())
    except (OSError, ValueError):
        res = None
    try:
        cj = json.loads((d / "case.json").read_text())
    except (OSError, ValueError):
        cj = {}
    procs = sorted(p.name for p in d.glob("processor[0-9]*") if p.is_dir())
    pt = times(d / "processor0") if procs else []
    rt = [t for t in times(d) if t[0] > 0]
    info.update(n_proc=len(procs), proc_latest=pt[-1][1] if pt else None,
                root_latest=rt[-1][1] if rt else None, endTime=cj.get("endTime"),
                convTime=cj.get("convTime") or cj.get("Trev"), mode=cj.get("mode"),
                running_marker=(d / "RUNNING").is_file(), migrated=(d / "MIGRATED").is_file(),
                slurm_logs=sorted(p.name for p in d.glob("slurm-*.out")))
    if res and res.get("complete"):
        info["state"] = "complete"
        info["results"] = {k: res.get(k) for k in ("Cd_mean", "Cl_mean", "St", "CQ_mean", "CP_mean", "n_steps",
                                                   "s_per_step", "wall_time_s", "dt_mean_s") if k in res}
    elif pt and pt[-1][0] > 0:
        info["state"] = "partial"
    elif info["migrated"] and rt:
        info["state"] = "migrated"
    elif cj:
        info["state"] = "setup"
    else:
        info["state"] = "empty"
    lg = d / "log.pimpleFoam"
    if lg.exists():
        info["log"] = log_progress(lg)
    try:
        info["hpc_jobs"] = [json.loads(x) for x in (d / "hpc_jobs.jsonl").read_text().splitlines()[-3:]]
    except (OSError, ValueError):
        pass
    return info


def main():
    req = json.loads(sys.stdin.read() or "{}")
    root = Path(req.get("root", "."))
    out = dict(host=os.uname().nodename, now=time.strftime("%Y-%m-%dT%H:%M:%S"), cases={})
    for stage, names in (req.get("stages") or {}).items():
        runs = root / stage / "runs"
        mroot = runs / "_mesh"
        if not names:
            names = {p.name: None for p in runs.iterdir() if p.is_dir() and p.name not in ("_mesh", "_slurm")} \
                if runs.is_dir() else {}
        out["cases"][stage] = {n: case_info(runs / n, k, mroot) for n, k in names.items()}
        sl = runs / "_slurm"
        if sl.is_dir():
            out.setdefault("slurm_dir", {})[stage] = sorted(p.name for p in sl.iterdir())[-500:]
    if "--squeue" in sys.argv:
        fmt = "%i|%j|%T|%M|%l|%D|%C|%P|%q|%r|%E|%S|%N"
        try:
            r = subprocess.run(["squeue", "-u", getpass.getuser(), "-h", "-o", fmt], capture_output=True,
                               text=True, timeout=60)
            keys = ["id", "name", "state", "elapsed", "limit", "nodes", "cpus", "partition", "qos", "reason",
                    "dependency", "start", "nodelist"]
            out["jobs"] = [dict(zip(keys, ln.split("|"))) for ln in r.stdout.splitlines() if ln.strip()]
        except Exception as e:  # noqa: BLE001
            out["jobs_error"] = repr(e)
    print("@@JSON@@" + json.dumps(out))


if __name__ == "__main__":
    main()
