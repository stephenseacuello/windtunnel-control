"""How run_case.py calls OpenFOAM, chosen by environment variables (default: the local Mac).

The three run_case.py files (cfd/section2d, cfd/rotor2d, cfd/stage2) build each OpenFOAM call
as the macOS launcher command
    [caffeinate -is] openfoam2606 -c "cd <case> && <cmd> > <log> 2>&1"
and pass it through adapt(). With no environment variable set, adapt() returns it unchanged,
so the local behaviour is exactly what it was before this module existed.

    CFD_FOAM_LAUNCH   native (default)  the command as built; caffeinate is dropped only where
                                        it does not exist (Linux)
                      container         apptainer exec $CFD_FOAM_IMAGE bash -c
                                        "source $CFD_FOAM_BASHRC && cd <case> && ..."; no caffeinate
                                        (Unity HPC, cfd/hpc/README.md)
                      bashrc            bash -c "source $CFD_FOAM_BASHRC && ..." (an OpenFOAM v2606
                                        installed on the host)
    CFD_FOAM_IMAGE    the .sif image (container mode; required)
    CFD_FOAM_BASHRC   default /usr/lib/openfoam/openfoam2606/etc/bashrc (the opencfd image)
    CFD_APPTAINER_ARGS  extra 'apptainer exec' options, e.g. "--cleanenv" (default none)

Also here: migrated() and redecompose(), the resume path for a case moved from another machine
by cfd/hpc/migrate.py (reconstructed latest time, no processor*/ folders, a MIGRATED marker):
the case is decomposed again for the new rank count and continued from that time. run_case.py
uses it only when the MIGRATED marker exists, so cases without one behave as before.
"""
import json
import os
import re
import shlex
import shutil
from pathlib import Path

DEFAULT_BASHRC = "/usr/lib/openfoam/openfoam2606/etc/bashrc"


def mode():
    return (os.environ.get("CFD_FOAM_LAUNCH") or "native").strip().lower()


def hpc_mode():
    """True when running under a batch system or a non-native launcher (Unity jobs)."""
    return mode() != "native" or bool(os.environ.get("SLURM_JOB_ID"))


def adapt(full):
    """full: the argv run_case.py built, [caffeinate, opts..., ] openfoam2606 -c <inner>.
    Returns the argv to run. Native mode on a machine with caffeinate: unchanged."""
    m = mode()
    if m == "native":
        if full and full[0] == "caffeinate" and shutil.which("caffeinate") is None:
            return _strip_caffeinate(full)
        return full
    inner = _strip_caffeinate(full)
    if len(inner) != 3 or inner[0] != "openfoam2606" or inner[1] != "-c":
        raise ValueError(f"foam_launch.adapt: unexpected command {full!r}")
    bashrc = os.environ.get("CFD_FOAM_BASHRC") or DEFAULT_BASHRC
    script = f"source {shlex.quote(bashrc)} && {inner[2]}"
    if m == "container":
        img = os.environ.get("CFD_FOAM_IMAGE")
        if not img or not Path(img).is_file():
            raise RuntimeError(f"CFD_FOAM_LAUNCH=container needs CFD_FOAM_IMAGE (an existing .sif); got {img!r}")
        extra = shlex.split(os.environ.get("CFD_APPTAINER_ARGS", ""))
        return ["apptainer", "exec", *extra, img, "bash", "-c", script]
    if m == "bashrc":
        return ["bash", "-c", script]
    raise ValueError(f"CFD_FOAM_LAUNCH must be native, container or bashrc, not {m!r}")


def _strip_caffeinate(full):
    if full and full[0] == "caffeinate":
        i = 1
        while i < len(full) and full[i].startswith("-"):
            i += 1
        return full[i:]
    return full


# --------------------------------------------------------------------------- migrated cases
MARKER = "MIGRATED"


def _times(path):
    out = []
    for q in Path(path).iterdir() if Path(path).is_dir() else []:
        try:
            out.append((float(q.name), q.name))
        except ValueError:
            pass
    return sorted(out)


def migrated(case):
    """True for a case uploaded by cfd/hpc/migrate.py that has not been decomposed here yet:
    MIGRATED marker, no processor*/ folder, a reconstructed time > 0 and case.json."""
    case = Path(case)
    if not (case / MARKER).is_file() or not (case / "case.json").is_file():
        return False
    if any(q.is_dir() for q in case.glob("processor[0-9]*")):
        return False
    t = _times(case)
    return bool(t) and t[-1][0] > 0


def redecompose(case, np, foam, say=print):
    """Decompose the reconstructed latest time of a migrated case for np ranks.
    foam: the run_case.foam function (same launcher). Sets nProcs in system/caseParameters
    and case.json, runs 'decomposePar -force -latestTime', checks processor0/<t>.
    Returns the start time (float). Raises RuntimeError on failure."""
    case = Path(case)
    t, tname = _times(case)[-1]
    cp = case / "system" / "caseParameters"
    s = cp.read_text()
    s2, n = re.subn(r"^nProcs(\s+)\d+;", lambda m: f"nProcs{m.group(1)}{int(np)};", s, flags=re.M)
    if n != 1:
        raise RuntimeError(f"{cp}: no single 'nProcs' entry to set")
    cp.write_text(s2)
    cj = case / "case.json"
    d = json.loads(cj.read_text())
    if "nProcs" in d and d["nProcs"] != int(np):
        d["nProcs_before_migration"] = d.get("nProcs_before_migration", d["nProcs"])
        d["nProcs"] = int(np)
        cj.write_text(json.dumps(d, indent=1))
    say(f"[migrated] {case.name}: decomposing the reconstructed time {tname} for {np} ranks")
    rc = foam(case, "decomposePar -force -latestTime", "log.decomposePar.migrated")
    if rc or not (case / "processor0" / tname).is_dir():
        raise RuntimeError(f"{case.name}: decomposePar of the migrated time {tname} failed "
                           f"(rc {rc}), see {case / 'log.decomposePar.migrated'}")
    m = case / MARKER
    try:
        info = json.loads(m.read_text())
    except ValueError:
        info = {}
    info.setdefault("redecomposed", []).append(dict(time=tname, nprocs=int(np), job=os.environ.get("SLURM_JOB_ID")))
    m.write_text(json.dumps(info, indent=1))
    return t
