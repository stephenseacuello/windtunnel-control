#!/usr/bin/env python3
"""Record every finished CFD case that has no up-to-date record yet (idempotent).

    python3 cfd/post/record_all.py                    # record + render new finished cases
    python3 cfd/post/record_all.py --dry-run          # list what would be done
    python3 cfd/post/record_all.py --stage section    # only cfd/section2d/runs (or: rotor)
    python3 cfd/post/record_all.py --include-stopped  # also stopped / timed-out / stale cases (flagged partial)
    python3 cfd/post/record_all.py --include-tests    # also runs/_* folders (_smoke_*, _test_*)
    python3 cfd/post/record_all.py --force            # redo every record
    python3 cfd/post/record_all.py --no-render        # numbers and plots only
    python3 cfd/post/record_all.py --meshes           # also mesh images of runs/_mesh/* (once each)
    python3 cfd/post/record_all.py --meshes '*a000*'  # only the meshes matching a glob

A case is finished when its solver log ends with 'End' / 'Finalising parallel run' and
nothing suggests it is running (record_lib.case_running). A RUNNING marker left by a killed
run_case.py does not count once it is stale (no solver process names the case and no log
write for 10 min, record_lib.marker_state): such a case is 'stale' and handled as stopped.
Run folders whose name starts with '_' (_mesh, _smoke_*, _test_*) are not production cases and are skipped unless
--include-tests is given, so a deleted test record is not re-created by the next sweep. A record is up to date when
records/<case>/summary.json says 'finished' and names the same solver-log size and
modification time; a case that was extended or re-run is recorded again.

Records: cfd/section2d/results/records/<case>/ and cfd/rotor2d/results/records/<case>/;
mesh-only records: .../records/_mesh/<mesh>/. Only one record_all runs at a time (a lock
in the temp folder); a second one exits at once. Runs at low priority (nice 10), one
process, so it does not slow the solvers. Safe to call from cron, a loop or a queue:

    while true; do python3 cfd/post/record_all.py --quiet; sleep 900; done
"""
import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:] = [p for p in sys.path if p not in ("", ".")]
sys.path.insert(0, str(HERE))
import record_lib as rl  # noqa: E402


def candidates(stages, tests=False):
    for kind in stages:
        runs = rl.stage_dir(kind) / "runs"
        if not runs.is_dir():
            continue
        for d in sorted(runs.iterdir()):
            if d.is_dir() and d.name != "_mesh" and (tests or not d.name.startswith("_")) \
                    and (d / "case.json").exists():
                yield kind, d


def up_to_date(case, kind):
    S = rl.load_json(rl.records_dir(case, kind) / "summary.json")
    if not S or S.get("status") != "finished":
        return False
    lg = rl.solver_log(case)
    if lg is None:
        return True
    src = S.get("source_log") or {}
    st = lg.stat()
    return src.get("bytes") == st.st_size and src.get("mtime") == time.strftime("%Y-%m-%dT%H:%M:%S",
                                                                                time.localtime(st.st_mtime))


def record_meshes(stages, dry, say, pattern="*", force=False):
    n = 0
    for kind in stages:
        mroot = rl.stage_dir(kind) / "runs" / "_mesh"
        if not mroot.is_dir():
            continue
        for d in sorted(mroot.glob(pattern)):
            if not d.is_dir() or not (d / "MESH_OK").exists():
                continue
            out = rl.stage_dir(kind) / "results" / "records" / "_mesh" / d.name
            if (out / "render_manifest.json").exists() and not force:
                continue
            say(f"[mesh] {kind}: {d.name} -> {out}")
            n += 1
            if dry:
                continue
            out.mkdir(parents=True, exist_ok=True)
            for f in ("mesh_info.json", "log.checkMesh"):
                if (d / f).exists():
                    shutil.copy(d / f, out / ("checkMesh.log" if f == "log.checkMesh" else f))
            r = subprocess.run(["nice", "-n", "10", str(rl.PVBATCH), "--force-offscreen-rendering",
                                str(HERE / "render_fields.py"), str(d), "--out", str(out), "--kind", kind],
                               capture_output=True, text=True, timeout=1800)
            (out / "render_log.txt").write_text(r.stdout[-10000:] + "\n" + r.stderr[-10000:])
            M = rl.load_json(d / "mesh_info.json", {}) or {}
            imgs = sorted(p.name for p in out.glob("*.png"))
            lines = [f"# Mesh record: `{d.name}`", "",
                     f"Mesh images of `{d.relative_to(rl.CFD.parent)}` (no flow solution), rendered by "
                     f"`cfd/post/render_fields.py` on {time.strftime('%Y-%m-%d')}. {M.get('n_cells', '?')} cells; "
                     f"first cell height {((M.get('ring') or {}).get('first_cell_m') or M.get('h0_m') or float('nan')) * 1e6:.3g} um. "
                     "Quality: `checkMesh.log`; generator parameters: `mesh_info.json`.", ""]
            for im in imgs:
                lines += [f"![{im}]({im})", ""]
            (out / "README.md").write_text("\n".join(lines))
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=["section", "rotor"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--include-stopped", action="store_true")
    ap.add_argument("--include-tests", action="store_true", help="also record runs/_* test folders")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--meshes", nargs="?", const="*", metavar="GLOB",
                    help="also render mesh folders runs/_mesh/<GLOB> (default all) once each")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    say = (lambda *x: None) if a.quiet else (lambda *x: print(*x, flush=True))
    stages = [a.stage] if a.stage else ["section", "rotor"]
    lock_path = Path(tempfile.gettempdir()) / "windtunnel_cfd_record_all.lock"
    lock = open(lock_path, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        say(f"record_all: another record_all holds {lock_path}; exiting")
        return 0
    try:
        os.nice(10)
    except OSError:
        pass
    todo, skipped = [], []
    for kind, case in candidates(stages, a.include_tests):
        status, why = rl.case_status(case)
        if status == "running":
            skipped.append((case.name, f"running ({why}); not touched"))
            continue
        if status != "finished" and not (a.include_stopped and status in ("stopped", "stale")):
            skipped.append((case.name, f"stale ({why})" if status == "stale" else status))
            continue
        if not a.force and status == "finished" and up_to_date(case, kind):
            skipped.append((case.name, "record up to date"))
            continue
        if not a.force and status in ("stopped", "stale") and (rl.records_dir(case, kind) / "summary.json").exists():
            S = rl.load_json(rl.records_dir(case, kind) / "summary.json", {}) or {}
            lg = rl.solver_log(case)
            if lg is not None and (S.get("source_log") or {}).get("bytes") == lg.stat().st_size:
                skipped.append((case.name, "stopped, record up to date"))
                continue
        todo.append((kind, case, status))
    if not a.include_tests:
        for kind in stages:
            runs = rl.stage_dir(kind) / "runs"
            for d in (sorted(runs.iterdir()) if runs.is_dir() else []):
                if d.is_dir() and d.name.startswith("_") and d.name != "_mesh" and (d / "case.json").exists():
                    skipped.append((d.name, "test folder (name starts with '_'; --include-tests)"))
    for name, why in skipped:
        say(f"  skip {name}: {why}")
    import record_case
    done = 0
    for kind, case, status in todo:
        say(f"{'would record' if a.dry_run else 'record'} {kind}: {case.name} ({status})")
        if a.dry_run:
            continue
        try:
            record_case.record(case, kind, render=not a.no_render, quiet=a.quiet)
            done += 1
        except Exception as e:  # noqa: BLE001 - one bad case must not stop the others
            say(f"  failed {case.name}: {e!r}")
    nm = record_meshes(stages, a.dry_run, say, a.meshes, a.force) if a.meshes else 0
    say(f"record_all: {done} case record(s) written, {nm} mesh record(s), {len(skipped)} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
