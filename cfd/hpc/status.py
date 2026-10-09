#!/usr/bin/env python3
"""Progress of the queued cases on Unity (cfd/hpc/README.md).

    python3 cfd/hpc/status.py                    # every production queue (+ reversed-sense rotor cases)
    python3 cfd/hpc/status.py --stage section2d  # one stage
    python3 cfd/hpc/status.py --jobs             # only this user's Slurm jobs

One ssh call: case folders read by remote_status.py on the login node, plus squeue.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hpc_common as H  # noqa: E402
import submit  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", action="append", choices=list(H.STAGES))
    ap.add_argument("--jobs", action="store_true", help="only list the Slurm jobs")
    a = ap.parse_args()
    stages = a.stage or list(H.STAGES)
    rows = submit.plan(stages, {}, True, None, None, 3.0)
    st = H.remote_status({s: {r["name"]: r["mesh"] for r in rows if r["stage"] == s} for s in stages}, squeue=True)
    if st.get("missing_repo"):
        sys.exit(f"no {H.RCFD} on Unity: run cfd/hpc/sync_up.sh first")
    jobs = {j["name"]: j for j in st.get("jobs", [])}
    if a.jobs:
        for j in st.get("jobs", []):
            print(f"{j['id']:>9s} {j['state']:9s} {j['elapsed']:>11s} / {j['limit']:<11s} {j['cpus']:>3s} "
                  f"{j['nodelist'] or j['reason']:14s} {j['name']}")
        return
    counts = {}
    print(f"{'stage':9s} {'case':52s} {'state':9s} {'done':>5s} {'s/step':>7s} {'log age':>8s}  job")
    for r in rows:
        info = st["cases"][r["stage"]][r["name"]]
        j = jobs.get(submit.job_name(r["stage"], r["name"]))
        state = info.get("state", "?")
        if state != "complete" and submit.local_complete(r["stage"], r["name"]):
            state = "complete"
            info = dict(info, log=None)
        if j:
            state = "running" if j["state"] == "RUNNING" else j["state"].lower()
        counts[state] = counts.get(state, 0) + 1
        lg = info.get("log") or {}
        done = ""
        if state == "complete":
            done = "100%"
        elif lg.get("t") is not None and info.get("endTime"):
            done = f"{100 * lg['t'] / float(info['endTime']):.0f}%"
        sps = f"{lg['s_per_step']:.3f}" if lg.get("s_per_step") else ""
        age = f"{lg['age_s'] // 60} min" if "age_s" in lg else ""
        jtxt = f"{j['id']} {j['elapsed']}/{j['limit']} {j['nodelist'] or j['reason']}" if j else ""
        print(f"{r['stage']:9s} {r['name'][:52]:52s} {state:9s} {done:>5s} {sps:>7s} {age:>8s}  {jtxt}")
    print("\n" + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + f"   (Unity time {st.get('now')})")


if __name__ == "__main__":
    main()
