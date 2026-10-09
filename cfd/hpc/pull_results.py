#!/usr/bin/env python3
"""Download the cases finished on Unity and make their records here (cfd/hpc/README.md).

    python3 cfd/hpc/pull_results.py               # every stage: download, records, CSVs
    python3 cfd/hpc/pull_results.py --no-records  # download and CSVs only
    python3 cfd/hpc/pull_results.py --list        # what would be downloaded

A case is downloaded when Unity's results.json says complete and the local one does not (or
differs). The whole case folder comes down except processor*/ (a finished case has none): 0/,
constant/, system/, the final time with its mean fields, postProcessing/, logs, case.json,
results.json, timing.json and hpc_jobs.jsonl. That is what the summaries, record_case.py and
render_fields.py read, so records are made exactly as for a case run here: the stage's own
after-case hook (post/after_case.sh, stage2/after_case.sh), one case at a time at nice 10. Then
each stage's results CSV is rebuilt. Local processor*/ folders of a case moved with migrate.py
are moved to <stage>/runs/_pre_unity/<case>/ first, so the folder holds only the finished run.
The Slurm logs (<stage>/runs/_slurm/) come down too.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hpc_common as H  # noqa: E402


def local_results(d):
    try:
        return json.loads((d / "results.json").read_text())
    except (OSError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", action="append", choices=list(H.STAGES))
    ap.add_argument("--no-records", action="store_true", help="skip the after-case hook (records, renders)")
    ap.add_argument("--list", action="store_true", help="only list what would be downloaded")
    a = ap.parse_args()
    stages = a.stage or list(H.STAGES)
    st = H.remote_status({s: {} for s in stages}, squeue=False)
    if st.get("missing_repo"):
        sys.exit(f"no {H.RCFD} on Unity")
    todo = []
    for s in stages:
        runs = H.load_queue(s).run_case.RUNS
        for name, info in sorted(st["cases"].get(s, {}).items()):
            if info.get("state") != "complete" or name.startswith("_"):
                continue
            loc = local_results(runs / name)
            if loc and loc.get("complete") and all(loc.get(k) == v for k, v in (info.get("results") or {}).items()):
                continue
            todo.append((s, name))
    for s, name in todo:
        print(f"{s:9s} {name}")
    print(f"{len(todo)} finished cases to download")
    if a.list:
        return
    done = {s: [] for s in stages}
    for s, name in todo:
        H.case_safe(name)
        q = H.load_queue(s)
        d = q.run_case.RUNS / name
        procs = [p for p in d.glob("processor*") if p.is_dir()] if d.is_dir() else []
        if procs:
            keep = d.parent / "_pre_unity" / name
            keep.mkdir(parents=True, exist_ok=True)
            for p in procs:
                shutil.move(str(p), str(keep / p.name))
        d.mkdir(parents=True, exist_ok=True)
        print(f"[pull] {s}/{name}", flush=True)
        r = subprocess.run(["rsync", "-az", "--exclude=/processor*/", "--exclude=/RUNNING",
                            f"{H.SSH_HOST}:{H.RCFD}/{s}/runs/{name}/", f"{d}/"])
        if r.returncode:
            print(f"  rsync failed (rc {r.returncode})", flush=True)
            continue
        (d / "MOVED_TO_UNITY").unlink(missing_ok=True)
        done[s].append(d)
    for s in stages:
        runs = H.load_queue(s).run_case.RUNS
        (runs / "_slurm").mkdir(parents=True, exist_ok=True)
        subprocess.run(["rsync", "-az", f"{H.SSH_HOST}:{H.RCFD}/{s}/runs/_slurm/", f"{runs / '_slurm'}/"])
    for s in stages:
        q = H.load_queue(s)
        if not a.no_records:
            for d in done[s]:
                q.run_after_case_hook(d)
        if done[s]:
            print(f"{s}: {q.rebuild_csv()} complete cases in the results CSV", flush=True)


if __name__ == "__main__":
    main()
