#!/usr/bin/env python3
"""Move cases that stopped part-way on this Mac to Unity, to finish there (cfd/hpc/README.md).

    python3 cfd/hpc/migrate.py            # list the local partial cases of the production queues
    python3 cfd/hpc/migrate.py --go       # move them (then sync_up.sh and submit.py as usual)

A local partial case is one with processor*/ time folders past 0 and no complete results.json.
For each one, with --go:
  1. refuse if a solver may still be writing it (RUNNING marker with a log written in the last
     10 min): pause the local queue first with '<stage>/queue.py --pause';
  2. 'reconstructPar -latestTime' here (OpenFOAM on the Mac), so the latest time, including its
     uniform/ averaging state, exists undecomposed in the case folder;
  3. upload the case without processor*/ and RUNNING; refuse if Unity already has that case folder;
  4. write the MIGRATED marker on Unity. run_case.py (cfd/post/foam_launch.py) then decomposes
     that time for the job's rank count and continues to the same end time, appending to the
     same log.pimpleFoam; the force and probe files restart in a new time folder, which the
     summaries already handle for any resumed run;
  5. write MOVED_TO_UNITY in the local folder. The local copy is left as it was otherwise; do not
     resume it here as well (pull_results.py later replaces it with the finished case).
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hpc_common as H  # noqa: E402


def times(d):
    out = []
    for q in Path(d).iterdir() if Path(d).is_dir() else []:
        try:
            out.append((float(q.name), q.name))
        except ValueError:
            pass
    return sorted(out)


def partial_cases():
    rows = []
    for st in H.STAGES:
        rc = H.load_queue(st).run_case
        for name, c, f in H.cases(st):
            d = rc.RUNS / name
            res = d / "results.json"
            if not d.is_dir() or (res.is_file() and json.loads(res.read_text()).get("complete")):
                continue
            pt = times(d / "processor0")
            if not pt or pt[-1][0] <= 0:
                continue
            cj = json.loads((d / "case.json").read_text()) if (d / "case.json").is_file() else {}
            rows.append(dict(stage=st, name=name, dir=d, t=pt[-1], end=cj.get("endTime"),
                             moved=(d / "MOVED_TO_UNITY").is_file()))
    return rows


def busy(d):
    lg = d / "log.pimpleFoam"
    return (d / "RUNNING").exists() and lg.exists() and time.time() - lg.stat().st_mtime < 600


def migrate(r):
    st, name, d = r["stage"], r["name"], r["dir"]
    rc = H.load_queue(st).run_case
    if busy(d):
        raise RuntimeError(f"{name}: a solver may still be writing it; pause the local queue first")
    t, tname = r["t"]
    if not (d / tname).is_dir():
        print(f"  reconstructPar -latestTime ({tname})", flush=True)
        if rc.foam(d, "reconstructPar -latestTime", "log.reconstructPar.migrate"):
            raise RuntimeError(f"{name}: reconstructPar failed, see {d / 'log.reconstructPar.migrate'}")
    if not (d / tname / "U").is_file():
        raise RuntimeError(f"{name}: no reconstructed {tname}/U")
    rdir = f"{H.RCFD}/{st}/runs/{name}"
    exists = H.remote(f"[ -e {rdir} ] && echo yes || echo no").strip()
    if exists != "no":
        raise RuntimeError(f"{name}: Unity already has {rdir}; not overwritten")
    # only the reconstructed latest time and 0/ among the time folders
    excl = ["--exclude=/processor*/", "--exclude=/RUNNING", "--exclude=/MOVED_TO_UNITY"]
    excl += [f"--exclude=/{n}/" for v, n in times(d) if 0 < v < t]
    print(f"  upload to {H.SSH_HOST}:{rdir}", flush=True)
    subprocess.run(["rsync", "-az", *excl, f"{d}/", f"{H.SSH_HOST}:{rdir}/"], check=True)
    info = dict(source="mac", time=tname, migrated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                nprocs_before=json.loads((d / "case.json").read_text()).get("nProcs"))
    H.remote(f"cat > {rdir}/MIGRATED <<'EOF'\n{json.dumps(info, indent=1)}\nEOF\n")
    (d / "MOVED_TO_UNITY").write_text(json.dumps(info, indent=1) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--go", action="store_true", help="move them (default: list only)")
    a = ap.parse_args()
    rows = partial_cases()
    for r in rows:
        pct = f"{100 * r['t'][0] / r['end']:.0f}%" if r["end"] else "?"
        print(f"{r['stage']:9s} {r['name']:52s} t = {r['t'][1]} ({pct}){'  already moved' if r['moved'] else ''}")
    if not rows:
        print("no partial local cases")
    if not a.go:
        return
    bad = 0
    for r in rows:
        if r["moved"]:
            continue
        print(f"[migrate] {r['stage']}/{r['name']}", flush=True)
        try:
            migrate(r)
            print("  done", flush=True)
        except Exception as e:  # noqa: BLE001
            bad += 1
            print(f"  FAILED: {e}", flush=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
