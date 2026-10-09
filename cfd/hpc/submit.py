#!/usr/bin/env python3
"""Submit queue cases to Unity, one Slurm job per case (cfd/hpc/README.md).

    python3 cfd/hpc/submit.py --dry-run                       # every production queue: plan and scripts
    python3 cfd/hpc/submit.py                                 # submit what is not complete or queued
    python3 cfd/hpc/submit.py --stage rotor2d --sense-variants
    python3 cfd/hpc/submit.py --stage section2d cfd/section2d/queues/priority1.txt --only 'a090'

For each case it asks Unity for the case folder's state and this user's queued jobs, then
  complete on Unity           -> skipped
  a job of that name queued   -> skipped (no double submission)
  partial / migrated / absent -> one sbatch script, submitted: run_case.py resumes from the
                                 latest written time, or sets the case up from the uploaded mesh.
Each job runs cfd/hpc/run_one.py with the case dict that the stage's queue.py parses from the
queue line, so the case is exactly the one the local queue would run. Run sync_up.sh first.

Also skipped: cases complete in this Mac's runs/ folder, and cases whose mesh is not on Unity
yet (run sync_up.sh; a mesh made inside a job could race with another job needing it).

Ranks per job: DEFAULT_NTASKS in hpc_common.py (8 for medium meshes: the better use of cores;
16 for fine and resolved-texture meshes), or --ntasks. The time limit is the estimate from the
cost model times --time-factor, plus 30 min, at least 2 h. Slurm sends SIGTERM 15 min before
the limit; the solver stops and a later submit.py resumes the case from its last write.

Lanes keep the lab's share of uri-cpu free for others: the jobs are dealt into --lanes8 lanes
(8-rank jobs) and --lanes16 lanes (16-rank jobs), each job waiting for the one before it in its
lane (Slurm --dependency=afterany), so at most 8 x lanes8 + 16 x lanes16 cores are in use
(default 26 and 19: 512 of the lab's 768, with the 19 large jobs all running at once). Jobs
are dealt in priority order (ORDER) to the lane that frees first by the cost model.
--lanes8 0 --lanes16 0 submits everything at once.
"""
import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hpc_common as H  # noqa: E402
import premesh  # noqa: E402

PARTITION = "uri-cpu"           # URI nodes, not preemptible, 30-day limit (README, "Unity")
MEM_PER_TASK_G = 2
SUBMIT_SH = r"""q=$(squeue -u "$USER" -h -o %j)
declare -A last
while read -r f lane; do
  jn=$(sed -n 's/^#SBATCH --job-name=//p' "$f")
  if grep -qxF "$jn" <<<"$q"; then echo "QUEUED $jn"; continue; fi
  dep=()
  if [ "$lane" != "-" ] && [ -n "${last[$lane]:-}" ]; then dep=(--dependency=afterany:${last[$lane]}); fi
  if id=$(sbatch --parsable "${dep[@]}" "$f" 2>&1); then
    id=${id%%;*}; echo "OK $jn $id lane $lane"; [ "$lane" != "-" ] && last[$lane]=$id
  else echo "FAIL $jn $id"; fi
done < ORDER
"""

# extra time-limit factor for kinds whose Unity speed is not yet measured (the limit only caps a
# runaway job; a short one would leave a case stopped until someone resubmits it)
EXTRA_FACTOR = {"stage2_tex": 2.0, "section_fine": 1.5, "rotor_rot": 1.5}

ORDER = {"rotor_static": 0, "section_coarse": 1, "section_medium": 2, "stage2_wf": 3, "rotor_rot": 4,
         "section_fine": 5, "stage2_tex": 6}


def job_name(stage, name):
    return f"cfd.{stage}.{name}"


def script(stage, name, c, ntasks, limit_s, partition, qos):
    out = f"{H.RCFD}/{stage}/runs/_slurm/%x.%j.out"
    lines = [
        "#!/bin/bash",
        f"#SBATCH --job-name={job_name(stage, name)}",
        f"#SBATCH --account={H.ACCOUNT}",
        f"#SBATCH --partition={partition}",
        *([f"#SBATCH --qos={qos}"] if qos else []),
        "#SBATCH --nodes=1",
        f"#SBATCH --ntasks={ntasks}",
        "#SBATCH --cpus-per-task=1",
        f"#SBATCH --mem={max(8, MEM_PER_TASK_G * ntasks)}G",
        f"#SBATCH --time={H.slurm_time(limit_s)}",
        "#SBATCH --signal=B:TERM@900",
        "#SBATCH --no-requeue",
        f"#SBATCH --output={out}",
        "set -uo pipefail",
        f"source {H.RCFD}/hpc/job_env.sh",
        "job_banner || exit 1",
        f"cd {H.RCFD}",
        f"exec \"$PY\" hpc/run_one.py --stage {stage} --name {shlex.quote(name)} --case {shlex.quote(json.dumps(c))}",
        "",
    ]
    return "\n".join(lines)


def local_complete(stage, name):
    res = H.load_queue(stage).run_case.RUNS / name / "results.json"
    try:
        return bool(json.loads(res.read_text()).get("complete"))
    except (OSError, ValueError):
        return False


def deal(todo, lanes8, lanes16):
    """Assign each job a lane ('8-3', '16-0', ...), in list order, to the lane that frees first."""
    if not lanes8 and not lanes16:
        return None
    free = {8: [0.0] * max(lanes8, 1), 16: [0.0] * max(lanes16, 1)}
    for r in todo:
        g = 8 if r["ntasks"] <= 8 else 16
        i = min(range(len(free[g])), key=lambda k: free[g][k])
        r["lane"] = f"{g}-{i}"
        free[g][i] += r["est_left_s"]
    return max(max(v) for v in free.values())


def plan(stages, files, sense, only, ntasks_override, factor):
    rows = []
    for st in stages:
        todo = H.cases(st, files.get(st))
        if sense:
            todo += premesh.sense_variants(st, todo)
        for name, c, f in todo:
            H.case_safe(name)
            if only and not re.search(only, name):
                continue
            kind = H.kind_of(st, c)
            n = ntasks_override or H.DEFAULT_NTASKS[kind]
            rows.append(dict(stage=st, name=name, case=c, kind=kind, ntasks=n, mesh=H.mesh_key(st, c),
                             queue=str(Path(f).name), est_s=H.est_seconds(st, c, n)))
    rows.sort(key=lambda r: (ORDER[r["kind"]], r["stage"], r["queue"]))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="queue files (default: the production queues in hpc_common.STAGES)")
    ap.add_argument("--stage", action="append", choices=list(H.STAGES), help="stage(s); default all")
    ap.add_argument("--sense-variants", action="store_true",
                    help="rotor2d: also the rotating cases with the rotation sense reversed (sense=CW/CCW)")
    ap.add_argument("--only", help="regular expression on case names")
    ap.add_argument("--ntasks", type=int, help="MPI ranks per job (default by mesh kind)")
    ap.add_argument("--time-factor", type=float, default=3.0, help="time limit = estimate x this + 30 min (default 3)")
    ap.add_argument("--partition", default=PARTITION)
    ap.add_argument("--qos", default="", help="Slurm QOS (default: the account's default, normal)")
    ap.add_argument("--max-jobs", type=int, default=0, help="submit at most this many (0 = no limit)")
    ap.add_argument("--lanes8", type=int, default=26, help="lanes for jobs of up to 8 ranks (default 26)")
    ap.add_argument("--lanes16", type=int, default=19, help="lanes for jobs of more than 8 ranks (default 19)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and write the scripts; submit nothing")
    a = ap.parse_args()
    stages = a.stage or list(H.STAGES)
    if a.files and len(stages) != 1:
        ap.error("queue files need exactly one --stage")
    rows = plan(stages, {stages[0]: a.files} if a.files else {}, a.sense_variants, a.only, a.ntasks, a.time_factor)

    st = H.remote_status({s: {r["name"]: r["mesh"] for r in rows if r["stage"] == s} for s in stages}, squeue=True)
    if st.get("missing_repo"):
        sys.exit(f"no {H.RCFD} on Unity: run cfd/hpc/sync_up.sh first")
    queued = {j["name"] for j in st.get("jobs", [])}
    todo, cores, core_h = [], 0, 0.0
    print(f"{'stage':9s} {'case':52s} {'state':9s} {'mesh':4s} {'np':>3s} {'estimate':>9s} {'limit':>11s}  action")
    for r in rows:
        info = st["cases"][r["stage"]][r["name"]]
        state = info.get("state", "?")
        frac = 1.0
        t = (info.get("log") or {}).get("t") or (float(info["proc_latest"]) if info.get("proc_latest") else None)
        if state in ("partial", "migrated") and t and info.get("endTime"):
            frac = max(0.05, 1 - t / float(info["endTime"]))
        est = r["est_s"] * frac
        limit = min(13 * 86400, max(2 * 3600, est * a.time_factor * EXTRA_FACTOR.get(r["kind"], 1.0) + 1800))
        if state == "complete":
            act = "skip: complete"
        elif local_complete(r["stage"], r["name"]):
            act = "skip: complete on the Mac"
        elif job_name(r["stage"], r["name"]) in queued:
            act = "skip: queued"
        elif not info.get("mesh_ok") and state not in ("partial", "migrated"):
            act = "HOLD: mesh not on Unity (sync_up.sh)"
        else:
            act = "SUBMIT"
        if act.startswith("SUBMIT"):
            if a.max_jobs and len(todo) >= a.max_jobs:
                act = "held (--max-jobs)"
            else:
                r.update(limit_s=limit, est_left_s=est)
                todo.append(r)
                cores += r["ntasks"]
                core_h += r["ntasks"] * est / 3600
        print(f"{r['stage']:9s} {r['name'][:52]:52s} {state:9s} {'ok' if info.get('mesh_ok') else 'no':4s} "
              f"{r['ntasks']:3d} {H.fmt_h(est):>9s} {H.slurm_time(limit):>11s}  {act}")
    print(f"\n{len(todo)} jobs, {cores} cores if all ran at once (lab cap on {a.partition}: 768), "
          f"about {core_h:.0f} core-hours by the cost model")
    if not todo:
        return
    span = deal(todo, a.lanes8, a.lanes16)
    if span is not None:
        print(f"lanes: {a.lanes8} x 8 ranks + {a.lanes16} x 16 ranks = at most {8 * a.lanes8 + 16 * a.lanes16} cores; "
              f"all done in about {H.fmt_h(span)} by the cost model, once the jobs start")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    H.JOBS.mkdir(parents=True, exist_ok=True)
    batch = H.JOBS / stamp
    batch.mkdir()
    for r in todo:
        r["script"] = f"{r['stage']}__{r['name']}.sbatch"
        (batch / r["script"]).write_text(script(r["stage"], r["name"], r["case"], r["ntasks"], r["limit_s"],
                                               a.partition, a.qos))
    (batch / "ORDER").write_text("".join(f"{r['script']} {r.get('lane', '-')}\n" for r in todo))
    print(f"scripts: {batch}")
    if a.dry_run:
        print("dry run: nothing submitted")
        return
    subprocess.run(["rsync", "-az", f"{batch}/", f"{H.SSH_HOST}:{H.RJOBS}/{stamp}/"], check=True)
    out = H.remote(f"cd {H.RJOBS}/{stamp} || exit 1\n" + SUBMIT_SH, timeout=1800)
    log = H.JOBS / "submitted.log"
    with open(log, "a") as fh:
        for ln in out.splitlines():
            if ln.split(" ", 1)[0] in ("OK", "FAIL", "QUEUED"):
                fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {stamp} {ln}\n")
    ok = sum(ln.startswith("OK ") for ln in out.splitlines())
    bad = [ln for ln in out.splitlines() if ln.startswith("FAIL ")]
    print(f"submitted {ok} of {len(todo)} jobs (log {log})")
    for ln in bad:
        print(ln)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
