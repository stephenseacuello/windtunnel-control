#!/usr/bin/env python3
"""Make, on this Mac, every mesh the queued cases need, so Unity never runs gmsh.

    python3 cfd/hpc/premesh.py                    # all stages, the default queue files (hpc_common.STAGES)
    python3 cfd/hpc/premesh.py --stage section2d cfd/section2d/queues/priority4.txt
    python3 cfd/hpc/premesh.py --list             # needed meshes and where each is (no work)
    python3 cfd/hpc/premesh.py --sense-variants   # also the rotating-rotor meshes with the rotation
                                                  # sense reversed (sense=CW/CCW lines, see README)

Each needed mesh is looked up first in the stage's own cache, <stage>/runs/_mesh/<key>/ (only
read), then in the staging cache cfd/hpc/mesh_cache/<stage>/<key>/. A missing one is made by the
stage's own run_case.ensure_mesh() (its generator in cfd/.venv, renumberMesh, checkMesh, the
same acceptance rules, the checkMesh log copied to <stage>/mesh/logs/), with the cache root
pointed at the staging folder, so nothing is written under any runs/ folder while the local
queues run. One mesh at a time, at nice 10 (os.nice at start; the children inherit it).
sync_up.sh uploads both caches to <stage>/runs/_mesh/ on Unity.
"""
import argparse
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hpc_common as H  # noqa: E402


def sense_variants(stage, todo):
    """Rotating rotor cases with sense auto -> the same case with the opposite sense given
    explicitly (the line a queue gets when the static sweep reverses the assumed sense)."""
    if stage != "rotor2d":
        return []
    rc = H.load_queue(stage).run_case
    rg = rc.rg
    out = []
    for name, c, f in todo:
        n = rc.normalise(dict(c))
        if n.get("lam") is None or n["sense"] != "auto" or n["hyp"] not in ("A", "B"):
            continue
        s_auto = rg.get_pose(n["hyp"], beta_deg=n.get("beta"), sense="auto")["sense"]
        d = dict(c, sense="CW" if s_auto > 0 else "CCW")
        out.append((rc.case_name(rc.normalise(d)), d, f))
    return out


def needed(stages, files, with_sense):
    rows, seen = [], set()
    for st in stages:
        todo = H.cases(st, files.get(st))
        if with_sense:
            todo += sense_variants(st, todo)
        for name, c, f in todo:
            key = H.mesh_key(st, c)
            if (st, key) in seen:
                continue
            seen.add((st, key))
            rows.append((st, key, c, name))
    return rows


def make(stage, key, c):
    """Generate one mesh into the staging cache with the stage's own ensure_mesh."""
    q = H.load_queue(stage)
    rc = q.run_case
    base = H.STAGING / stage
    base.mkdir(parents=True, exist_ok=True)
    old = rc.MESHES
    rc.MESHES = base                    # every stage's mesh_dir()/ensure_mesh() reads this global
    try:
        if stage == "section2d":
            d = rc.ensure_mesh(c["level"], c["alpha"])
        elif stage == "rotor2d":
            d = rc.ensure_mesh(rc.normalise(dict(c)), quiet=True)
        else:
            d, _ = rc.ensure_mesh(rc.normalise(dict(c)))
    finally:
        rc.MESHES = old
    if Path(d).name != key:
        raise RuntimeError(f"made {d}, expected key {key}")
    return Path(d)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="queue files (default: the stage's production queues)")
    ap.add_argument("--stage", action="append", choices=list(H.STAGES), help="stage(s); default all")
    ap.add_argument("--list", action="store_true", help="only list the needed meshes and their source")
    ap.add_argument("--paths", action="store_true", help="with --list: print 'stage<TAB>key<TAB>dir' for found meshes")
    ap.add_argument("--sense-variants", action="store_true",
                    help="also meshes for the rotating rotor cases with the rotation sense given explicitly")
    a = ap.parse_args()
    stages = a.stage or list(H.STAGES)
    if a.files and len(stages) != 1:
        ap.error("queue files need exactly one --stage")
    files = {stages[0]: a.files} if a.files else {}
    rows = needed(stages, files, a.sense_variants)
    missing = []
    for st, key, c, name in rows:
        d, where = H.local_mesh(st, key)
        if a.paths:
            if d:
                print(f"{st}\t{key}\t{d}")
            continue
        if d is None:
            missing.append((st, key, c, name))
        if a.list:
            print(f"{st:10s} {key:45s} {where or 'MISSING'}")
    if a.paths:
        return
    print(f"{len(rows)} meshes needed, {len(rows) - len(missing)} present, {len(missing)} to make", flush=True)
    if a.list or not missing:
        return
    os.nice(10)
    fails = 0
    for i, (st, key, c, name) in enumerate(missing, 1):
        t0 = time.time()
        print(f"[{i}/{len(missing)}] {st} {key} (for {name}) ...", flush=True)
        try:
            d = make(st, key, c)
            print(f"    done in {time.time() - t0:.0f} s -> {d}", flush=True)
        except Exception as e:  # noqa: BLE001 - go on with the other meshes
            fails += 1
            print(f"    FAILED after {time.time() - t0:.0f} s: {e!r}", flush=True)
            traceback.print_exc()
    print(f"premesh finished: {len(missing) - fails} made, {fails} failed", flush=True)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
