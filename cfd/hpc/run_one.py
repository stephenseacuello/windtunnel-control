#!/usr/bin/env python3
"""Run one queue case inside a Slurm job on Unity (called by the sbatch scripts of submit.py).

    run_one.py --stage section2d --name a015.0_U23.0_LM_medium_Tu1.0 --case '{"alpha": 15.0, ...}'
    run_one.py ... --np 8 --folder _hpc_test_x --wall-limit 300      # tests

The case dict is exactly what the stage's queue.py parse_queue() returns for the queue line, so
the case runs as the local queue would run it: same run_case.run() call, same defaults, same
case name (checked). Ranks: --np, else $SLURM_NTASKS, else the stage default. OpenFOAM runs
through cfd/post/foam_launch.py (CFD_FOAM_LAUNCH=container, CFD_FOAM_IMAGE set by the job).

Exit codes: 0 complete or already complete; 3 stopped (stopAt writeNow, e.g. before the time
limit) or timeout (--wall-limit); 4 busy (another solver is writing this case); 1 failed;
2 bad arguments.
"""
import argparse
import json
import os
import signal
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hpc_common as H  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True, choices=list(H.STAGES))
    ap.add_argument("--name", required=True, help="expected case name (checked against the case dict)")
    ap.add_argument("--case", required=True, help="case dict as JSON (queue.py parse_queue)")
    ap.add_argument("--np", type=int, help="MPI ranks (default $SLURM_NTASKS)")
    ap.add_argument("--folder", help="run in runs/<folder> instead of runs/<name> (tests; start with '_')")
    ap.add_argument("--wall-limit", type=float, help="kill the solver after this many seconds (tests)")
    a = ap.parse_args()
    q = H.load_queue(a.stage)
    rc = q.run_case
    c = json.loads(a.case)
    name = q.name_of(c)
    if name != a.name:
        print(f"run_one: case dict gives name {name}, not {a.name}", flush=True)
        sys.exit(2)
    np = a.np or int(os.environ.get("SLURM_NTASKS") or 0) or None
    folder = a.folder or name
    case_dir = rc.RUNS / folder
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, rc._on_signal)
    # a second job on the same case (double submission) would corrupt both: refuse while the
    # case has a RUNNING marker and its solver log was written in the last 2 min
    lg = case_dir / "log.pimpleFoam"
    if (case_dir / "RUNNING").exists() and lg.exists() and time.time() - lg.stat().st_mtime < 120:
        print(f"run_one: {folder} is busy (RUNNING marker, log written "
              f"{time.time() - lg.stat().st_mtime:.0f} s ago); not started", flush=True)
        sys.exit(4)
    print(f"run_one: {a.stage}/{folder} on {np} ranks, host {socket.gethostname()}, "
          f"job {os.environ.get('SLURM_JOB_ID', '-')}, launch {os.environ.get('CFD_FOAM_LAUNCH', 'native')}", flush=True)
    t0 = time.time()
    try:
        if a.stage == "section2d":
            kw = {k: c[k] for k in q.KEYS if k in c}
            if np:
                kw["np"] = np
            if a.folder:
                kw["name"] = a.folder
            st = rc.run(c["alpha"], c["U"], c["model"], c["level"], c["tu"], wall_limit=a.wall_limit, **kw)
        elif a.stage == "rotor2d":
            d = dict(c)
            if np:
                d["np"] = np
            if a.folder:
                d["name"] = a.folder
            st = rc.run(d, wall_limit=a.wall_limit)
        else:
            kw = {}
            if np:
                kw["np"] = np
            st = rc.run(c, wall_limit=a.wall_limit, name=a.folder, **kw)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"run_one: exception {e!r}", flush=True)
        st = "failed"
    rec = dict(stage=a.stage, name=folder, status=st, job=os.environ.get("SLURM_JOB_ID"), host=socket.gethostname(),
               ntasks=np, start=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0)), wall_s=round(time.time() - t0, 1))
    if case_dir.is_dir():
        with open(case_dir / "hpc_jobs.jsonl", "a") as f:
            f.write(json.dumps(rec) + "\n")
    print(f"run_one: {folder}: {st} after {rec['wall_s']:.0f} s", flush=True)
    sys.exit(0 if st in ("complete", "skipped", "setup") else 3 if st in ("stopped", "timeout")
             else 4 if st == "busy" else 1)


if __name__ == "__main__":
    main()
