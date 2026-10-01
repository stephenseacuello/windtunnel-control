#!/usr/bin/env python3
"""
openfoam.py — drive OpenFOAM cases from the dashboard, and read what they say.

    python src/openfoam.py check                      # is it installed?
    python src/openfoam.py cases                      # what can be run
    python src/openfoam.py run pitzDaily blockMesh simpleFoam

═══════════════════════════════════════════════════════════════════════════
WHY THIS EXISTS IN A TUNNEL CONTROL REPO
═══════════════════════════════════════════════════════════════════════════
The rig measures P_max(v), and soon Cp(λ). A CFD case predicts the same
quantities from geometry alone. Neither is the answer on its own:

  · the rig is the truth, but it cannot say WHY a blade performs as it does
  · the simulation says why, but only if it agrees with the rig first

So the useful product is not a pretty velocity field. It is the **residual
between the two** — the same argument `twin_residual.py` makes about the
lumped generator model, one level up. A simulation that has never been
checked against this tunnel is a hypothesis with good graphics.

═══════════════════════════════════════════════════════════════════════════
SECURITY: A WHITELIST, NOT A SHELL
═══════════════════════════════════════════════════════════════════════════
The dashboard is a web app. Handing it `subprocess(shell=True)` with a
user-supplied string turns a local instrument panel into remote code
execution the moment somebody binds it to 0.0.0.0 — which `--host` already
allows, for the tunnel PC.

So: commands are checked against `ALLOWED` below, case directories must
resolve inside `CASES_ROOT`, and nothing is passed through a shell. Adding a
solver means adding its name here, deliberately.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Where cases live. Anything outside this is refused.
CASES_ROOT = Path(os.environ.get("WT_FOAM_CASES",
                                 Path.home() / "OpenFOAM" / "run"))

# Solvers and utilities the dashboard may invoke. Deliberately short.
ALLOWED = {
    # meshing
    "blockMesh", "snappyHexMesh", "surfaceFeatureExtract", "extrudeMesh",
    "checkMesh", "renumberMesh", "transformPoints", "topoSet",
    "createPatch", "decomposePar", "reconstructPar",
    # incompressible solvers — what a wind tunnel needs
    "simpleFoam", "pimpleFoam", "pisoFoam", "potentialFoam",
    # post
    "postProcess", "foamToVTK", "foamLog",
}

# `Solving for Ux, Initial residual = 1, Final residual = 0.05, No Iterations 1`
_RES = re.compile(
    r"Solving for (\S+?),\s*Initial residual = ([0-9.eE+-]+),"
    r"\s*Final residual = ([0-9.eE+-]+)")
_TIME = re.compile(r"^Time = ([0-9.eE+-]+)\s*$")
_CONV = re.compile(r"SIMPLE solution converged in (\d+) iterations")
_EXEC = re.compile(r"^ExecutionTime = ([0-9.]+) s")


class FoamError(RuntimeError):
    pass


# ── discovery ─────────────────────────────────────────────────────────────

def wrapper():
    """Path to the `openfoam` launcher, or None."""
    return shutil.which("openfoam") or shutil.which("openfoam2606")


def discover(timeout=60):
    """
    {'ok', 'version', 'wrapper', 'cases_root', 'note'} — never raises.

    The gerlero macOS build is a disk image: the first call MOUNTS it, which
    takes a few seconds and prints to stderr. That is why this has a generous
    timeout and why the dashboard calls it off the request thread.
    """
    w = wrapper()
    if not w:
        return {"ok": False, "version": None, "wrapper": None,
                "cases_root": str(CASES_ROOT),
                "note": "no `openfoam` on PATH. "
                        "brew install gerlero/openfoam/openfoam"}
    try:
        r = subprocess.run([w, "-c", "echo $WM_PROJECT_VERSION"],
                           capture_output=True, text=True, timeout=timeout)
        v = (r.stdout or "").strip().splitlines()
        v = v[-1].strip() if v else ""
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"ok": False, "version": None, "wrapper": w,
                "cases_root": str(CASES_ROOT),
                "note": f"`openfoam` did not answer: {e}"}
    if not v:
        return {"ok": False, "version": None, "wrapper": w,
                "cases_root": str(CASES_ROOT),
                "note": "`openfoam` ran but reported no WM_PROJECT_VERSION"}
    return {"ok": True, "version": v, "wrapper": w,
            "cases_root": str(CASES_ROOT), "note": ""}


# ── cases ─────────────────────────────────────────────────────────────────

def is_case(p):
    """An OpenFOAM case is a directory with system/controlDict."""
    return (Path(p) / "system" / "controlDict").is_file()


def resolve_case(name):
    """
    A case directory inside CASES_ROOT, or raise.

    Resolved and then checked for containment, so `../../etc` and a symlink
    out of the tree are both refused rather than merely discouraged.
    """
    root = CASES_ROOT.resolve()
    p = (root / name).resolve()
    if not (p == root or root in p.parents):
        raise FoamError(f"case {name!r} resolves outside {root}")
    if not p.is_dir():
        raise FoamError(f"no such case directory: {p}")
    if not is_case(p):
        raise FoamError(f"{p} has no system/controlDict — not an OpenFOAM case")
    return p


def list_cases():
    """Every case under CASES_ROOT, newest first, with its last write time."""
    root = CASES_ROOT
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.rglob("system/controlDict")):
        case = p.parent.parent
        try:
            rel = case.relative_to(root)
        except ValueError:
            continue
        times = sorted(
            (d.name for d in case.iterdir()
             if d.is_dir() and re.fullmatch(r"[0-9]+(\.[0-9]+)?", d.name)),
            key=float)
        out.append({
            "name": str(rel),
            "mtime": case.stat().st_mtime,
            "times": times[-6:],
            "latest_time": times[-1] if times else None,
            "n_times": len(times),
        })
    return sorted(out, key=lambda c: -c["mtime"])


# ── running ───────────────────────────────────────────────────────────────

def parse_line(line, state):
    """
    Fold one line of solver output into `state`. Returns True if it mattered.

    `state` accumulates {'time', 'residuals': {field: [(t, r0), ...]},
    'converged', 'exec_s'}.
    """
    m = _TIME.match(line)
    if m:
        state["time"] = float(m.group(1))
        return True
    m = _RES.search(line)
    if m:
        field, r0 = m.group(1), float(m.group(2))
        # `Initial` residual, not `Final`: the initial residual of step N is
        # the honest measure of how wrong the solution still was going in.
        # Final residual only says the linear solver hit its own tolerance,
        # which it does every iteration whether or not the run is converging.
        state.setdefault("residuals", {}).setdefault(field, []).append(
            (state.get("time", 0.0), r0))
        return True
    m = _CONV.search(line)
    if m:
        state["converged"] = int(m.group(1))
        return True
    m = _EXEC.match(line)
    if m:
        state["exec_s"] = float(m.group(1))
        return True
    return False


def run(case, commands, on_line=None, stop=None, timeout=None, env=None):
    """
    Run `commands` in `case` inside the OpenFOAM environment.

    `commands` is a list of argv lists, e.g. [["blockMesh"], ["simpleFoam"]].
    Each is whitelisted. `on_line(line)` is called for every output line.
    `stop()` returning True aborts between commands and terminates the
    running one.

    Returns {'ok', 'ran', 'failed', 'state'}.
    """
    w = wrapper()
    if not w:
        raise FoamError("OpenFOAM is not installed")
    cdir = resolve_case(case)

    for argv in commands:
        if not argv or argv[0] not in ALLOWED:
            raise FoamError(
                f"{(argv or ['?'])[0]!r} is not in the allowed list. "
                f"Allowed: {', '.join(sorted(ALLOWED))}")
        for a in argv[1:]:
            if not re.fullmatch(r"[-A-Za-z0-9_.,=/]*", a):
                raise FoamError(f"argument {a!r} has characters that are not "
                                f"allowed in a case invocation")

    state, ran = {"residuals": {}}, []
    t0 = time.monotonic()
    for argv in commands:
        if stop and stop():
            return {"ok": False, "ran": ran, "failed": None,
                    "state": state, "aborted": True}
        # No shell. The wrapper takes the binary and its arguments directly,
        # and -case keeps the working directory out of the equation.
        cmd = [w, argv[0], "-case", str(cdir)] + list(argv[1:])
        if on_line:
            on_line(f"$ {' '.join(argv)}  (in {cdir.name})")
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True,
                             bufsize=1, env=env)
        try:
            for line in p.stdout:
                line = line.rstrip("\n")
                parse_line(line, state)
                if on_line:
                    on_line(line)
                if stop and stop():
                    p.terminate()
                    break
                if timeout and time.monotonic() - t0 > timeout:
                    p.terminate()
                    if on_line:
                        on_line(f"# timed out after {timeout:.0f}s")
                    break
        finally:
            p.wait()
        ran.append(argv[0])
        if p.returncode not in (0, -15):     # -15 = our own terminate
            return {"ok": False, "ran": ran, "failed": argv[0],
                    "returncode": p.returncode, "state": state}
    return {"ok": True, "ran": ran, "failed": None, "state": state}


def residual_series(state, max_points=400):
    """Residual history reduced for a plot: {field: {'t': [...], 'r': [...]}}."""
    out = {}
    for field, pts in (state.get("residuals") or {}).items():
        step = max(1, len(pts) // max_points)
        sel = pts[::step]
        out[field] = {"t": [p[0] for p in sel], "r": [p[1] for p in sel]}
    return out


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("mode", choices=["check", "cases", "run"])
    ap.add_argument("case", nargs="?")
    ap.add_argument("commands", nargs="*")
    a = ap.parse_args()

    if a.mode == "check":
        d = discover()
        print(f"\n  openfoam : {d['wrapper'] or 'NOT FOUND'}")
        print(f"  version  : {d['version'] or '—'}")
        print(f"  cases    : {d['cases_root']}")
        if d["note"]:
            print(f"  note     : {d['note']}")
        print()
        return 0 if d["ok"] else 1

    if a.mode == "cases":
        cs = list_cases()
        if not cs:
            print(f"\n  no cases under {CASES_ROOT}\n")
            return 1
        print(f"\n  {len(cs)} case(s) under {CASES_ROOT}\n")
        for c in cs:
            print(f"    {c['name']:<40} {c['n_times']:>4} time dirs"
                  f"   latest {c['latest_time'] or '—'}")
        print()
        return 0

    if not a.case or not a.commands:
        raise SystemExit("\n  run needs a case and at least one command\n")
    r = run(a.case, [[c] for c in a.commands], on_line=print)
    st = r["state"]
    print(f"\n  ran: {', '.join(r['ran'])}")
    if st.get("converged"):
        print(f"  CONVERGED in {st['converged']} iterations")
    elif st.get("time"):
        print(f"  stopped at time {st['time']:g} without converging")
    for f, pts in (st.get("residuals") or {}).items():
        if pts:
            print(f"    {f:<10} {pts[0][1]:.3e} -> {pts[-1][1]:.3e}")
    return 0 if r["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
