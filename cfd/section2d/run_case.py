#!/usr/bin/env python3
"""Create and run one Stage 1 section case (2D URANS, pimpleFoam, 4 MPI ranks).

    python3 cfd/section2d/run_case.py --alpha 0 --U 23 --model SST --level medium
    python3 cfd/section2d/run_case.py --alpha 90 --U 23 --model LM --level medium --tu 1.0
    python3 cfd/section2d/run_case.py ... --setup-only        # create the case, do not run
    python3 cfd/section2d/run_case.py ... --wall-limit 600    # stop the solver after 600 s (smoke test)
    python3 cfd/section2d/run_case.py ... --np 2 --name _test_x   # test: 2 ranks, folder runs/_test_x

Free-stream turbulence (--decay, README section 3):
  control        (default) kOmegaSST decayControl: the far-field k and omega are the target
                 values (Tu = --tu, length scale --lt, default 1 mm) and kInf/omegaInf hold
                 them, so Tu at the section equals the target from t = 0 and nu_t/nu stays small.
  precompensate  the 7 Oct smoke-test set-up: no decay control; far-field Tu raised so that
                 the SST decay over the 1.27 m to the section leaves the target (--lt default
                 2 mm). Case names get '_precomp'.

The case goes to cfd/section2d/runs/<name>/, name = a<alpha>_U<U>_<model>_<level>_Tu<Tu>,
e.g. a000.0_U23.0_SST_medium_Tu1.0. Re-running the same command:
  * skips the case if results.json says it is complete (use --force to redo it);
  * otherwise resumes from the last write time in processor*/ (controlDict has
    startFrom latestTime), so an interrupted case loses at most one write
    interval (nconv/15 c/U: 10 c/U for the default 150).
When the solver reaches endTime the script reconstructs the last time, writes
results.json (cfd/post/section_summary.py) and deletes processor*/ unless
--keep-processors.

While the solver runs, runs/<name>/RUNNING holds this script's pid. It is removed when the
solve ends, also on an error or a stop signal, and stays only if the script is killed
outright (SIGKILL, crash, power loss). queue.py --status and cfd/post/record_all.py report
such a marker as 'stale' once no solver process names the case and log.pimpleFoam has not
been written for 10 min (cfd/post/record_lib.py marker_state).

Meshes are cached in runs/_mesh/<level>_a<alpha>/ (the wake band follows the free
stream, so each alpha has its own mesh); each passes checkMesh before use.

OpenFOAM is called only through the launcher: openfoam2606 -c "cd <case> && ...".
The mesh generator runs in cfd/.venv (gmsh). Everything else is the system python3.
"""
import argparse
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent              # cfd/section2d
# keep cfd/section2d off sys.path: its queue.py would shadow the standard-library 'queue'
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != HERE]
CFD = HERE.parent
RUNS = HERE / "runs"
MESHES = RUNS / "_mesh"
TEMPLATE = HERE / "case_template"
VENV_PY = CFD / ".venv" / "bin" / "python"
MAKE_MESH = HERE / "mesh" / "make_mesh.py"
sys.path.insert(0, str(CFD / "post"))
import foam_launch  # noqa: E402  cfd/post/foam_launch.py: CFD_FOAM_LAUNCH (Unity container), migrated cases

NU = 1.516e-5           # m^2/s, cfd/templates/transportProperties
RHO = 1.204             # kg/m^3, cfd/templates/flowConstants
C_REF = 0.048           # m, reference chord (make_mesh.C_REF)
DZ = 1.0e-3             # m, cell depth (make_mesh.DZ)
R_FF = 27.0 * C_REF     # m, far-field radius (make_mesh.R_FF_CHORDS)
BETA, BETA_STAR = 0.0828, 0.09    # SST k-epsilon-branch constants: free-stream decay
MODELS = {"SST": "kOmegaSST", "LM": "kOmegaSSTLM"}
LEVELS = ("coarse", "medium", "fine")
WAKE_PROBES = [(1, 0), (1, 0.5), (1, -0.5), (2, 0), (2, 0.5), (2, -0.5), (4, 0), (4, 0.5), (4, -0.5)]
UPSTREAM_PROBE = (-2, 0)          # chords, free-stream frame: Tu reaching the section
NP = int(os.environ.get("SLURM_NTASKS") or 4)   # MPI ranks for production (--np; tests use at most 2);
                                                # a Slurm job's task count on Unity (cfd/hpc/)
CMU25 = 0.09 ** 0.25
DECAY_MODES = ("control", "precompensate")
DECAY_DEFAULT = "control"
# m, free-stream turbulence length scale l = sqrt(k)/(Cmu^0.25 omega) (assumed; the tunnel
# value is not measured). T3A tutorial: 1.5 mm.
#  control: 1 mm gives nu_t/nu = sqrt(3/2) Cmu^0.25 Tu U l / nu = 10.2 at 23 m/s and Tu 1 %
#    (the T3A inlet ratio is 12) and 2-50 over 10.2-38 m/s and Tu 0.5-3 % (README table).
#    A fixed l, not a fixed ratio, so a speed change changes only U (as in the tunnel).
#  precompensate: 2 mm, the 7 Oct smoke-test value (kept for reproducibility).
LT_DEFAULTS = {"control": 1.0e-3, "precompensate": 2.0e-3}
LT_DEFAULT = LT_DEFAULTS[DECAY_DEFAULT]       # kept for callers of the old name


def lt_default(decay=DECAY_DEFAULT):
    return LT_DEFAULTS[decay]


# --------------------------------------------------------------------------- inputs
MAXCO_DEFAULT = 5.0
NOUTER_DEFAULT = 2
NCONV_DEFAULT = 150.0
NAVG_DEFAULT = 100.0


def case_name(alpha, U, model, level, tu, maxco=MAXCO_DEFAULT, nouter=NOUTER_DEFAULT,
              nconv=NCONV_DEFAULT, navg=NAVG_DEFAULT, lt=None, decay=DECAY_DEFAULT):
    """a<alpha>_U<U>_<model>_<level>_Tu<Tu>, plus suffixes for every setting that differs
    from the default, so a test or sensitivity case never shares a folder (and a
    'complete' flag) with a production case:
      _Co<maxco>n<nouter>   time-step settings
      _N<nconv>A<navg>      run length and averaging window, in c/U
      _lt<mm>               free-stream turbulence length scale, mm (if not the mode's default)
      _precomp              --decay precompensate (the 7 Oct smoke-test free stream)"""
    s = f"a{alpha:05.1f}_U{U:04.1f}_{model}_{level}_Tu{tu:.1f}"
    if maxco != MAXCO_DEFAULT or nouter != NOUTER_DEFAULT:
        s += f"_Co{maxco:g}n{nouter}"
    if nconv != NCONV_DEFAULT or navg != NAVG_DEFAULT:
        s += f"_N{nconv:g}A{navg:g}"
    if lt is not None and abs(lt - lt_default(decay)) > 1e-12:
        s += f"_lt{lt * 1e3:g}"
    if decay != DECAY_DEFAULT:
        s += "_precomp"
    return s


def rethetat_from_tu(tu_pct):
    """Free-stream transition-onset Re_theta, Langtry & Menter (2009), zero pressure gradient."""
    tu = max(tu_pct, 0.027)
    if tu <= 1.3:
        r = 1173.51 - 589.428 * tu + 0.2196 / tu ** 2
    else:
        r = 331.50 * (tu - 0.5658) ** -0.671
    return max(r, 20.0)


def inlet_turbulence(U, tu_body_pct, lt, L, decay=DECAY_DEFAULT):
    """Far-field k, omega (and the decay-control k_inf, omega_inf) for a target Tu at the section.

    decay = 'control': kOmegaSST decayControl (Spalart and Rumsey 2007; v2606
      src/TurbulenceModels/turbulenceModels/Base/kOmegaSST/kOmegaSSTBase.C) adds
      betaStar omegaInf kInf to the k equation and beta omegaInf^2 to the omega equation,
      which cancel the free-stream destruction at k = kInf, omega = omegaInf. With
      kInf = k_far and omegaInf = omega_far the free stream does not decay: Tu at the
      section is the target, and nu_t/nu = sqrt(3/2) Cmu^0.25 Tu U lt / nu everywhere
      upstream. k = 1.5 (Tu U)^2, omega = sqrt(k)/(Cmu^0.25 lt).
    decay = 'precompensate': see inlet_turbulence_precompensate."""
    if decay == "precompensate":
        return inlet_turbulence_precompensate(U, tu_body_pct, lt, L)
    if decay != "control":
        raise ValueError(f"decay must be one of {DECAY_MODES}, not {decay!r}")
    tu = tu_body_pct / 100
    k = 1.5 * (tu * U) ** 2
    w = math.sqrt(k) / (CMU25 * lt)
    return dict(Tu_inlet_pct=tu_body_pct, Tu_body_pct=tu_body_pct, k=k, omega=w, nut=k / w,
                vr_far=k / w / NU, vr_body=k / w / NU, length_scale_m=lt, decay_distance_m=L,
                ReThetat=rethetat_from_tu(tu_body_pct), decayControl=True, kInf=k, omegaInf=w)


def inlet_turbulence_precompensate(U, tu_body_pct, lt, L):
    """k, omega at the far field such that the free-stream decay of the SST model
    over the distance L (far field to section) leaves Tu = tu_body at the section
    (the T3A tutorial's approach: inlet values chosen for the decayed level).
    Decay without production: k = k0 (1 + beta w0 t)^(-beta*/beta), w = w0/(1 + beta w0 t),
    t = L/U. The far-field length scale lt fixes omega: w0 = sqrt(k0)/(Cmu^0.25 lt).
    Then beta w0 t depends only on Tu0 and L/lt, so the decay is the same at every
    speed and any target is reachable (Tu_body rises monotonically with Tu0).
    The 7 Oct smoke tests used this (with lt = 2 mm); no decay control."""
    cmu25 = CMU25
    t = L / U

    def at_body(tu0):
        k0 = 1.5 * (tu0 * U) ** 2
        w0 = math.sqrt(k0) / (cmu25 * lt)
        f = 1 + BETA * w0 * t
        return math.sqrt(2 / 3 * k0 * f ** (-BETA_STAR / BETA)) / U, k0, w0, f

    target = tu_body_pct / 100
    lo, hi = 1e-6, 1.0
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        if at_body(mid)[0] < target:
            lo = mid
        else:
            hi = mid
    tu0 = 0.5 * (lo + hi)
    tb, k0, w0, f = at_body(tu0)
    kb, wb = k0 * f ** (-BETA_STAR / BETA), w0 / f
    return dict(Tu_inlet_pct=100 * tu0, Tu_body_pct=100 * tb, k=k0, omega=w0, nut=k0 / w0,
                vr_far=k0 / w0 / NU, vr_body=kb / wb / NU, length_scale_m=lt,
                decay_distance_m=L, ReThetat=rethetat_from_tu(100 * tu0),
                decayControl=False, kInf=0.0, omegaInf=0.0)


def case_parameters(alpha, U, model, level, tu, nconv, navg, maxco, nouter, lt=None, decay=DECAY_DEFAULT,
                    name=None, nprocs=NP):
    lt = lt_default(decay) if lt is None else lt
    a = math.radians(alpha)
    ux, uy = math.cos(a), math.sin(a)
    tc = C_REF / U
    turb = inlet_turbulence(U, tu, lt, R_FF - 0.5 * C_REF, decay)
    probes = []
    for xc, yc in WAKE_PROBES + [UPSTREAM_PROBE]:
        x = (xc * ux - yc * uy) * C_REF
        y = (xc * uy + yc * ux) * C_REF
        probes.append((x, y, 0.5 * DZ))
    return dict(
        caseName=name or case_name(alpha, U, model, level, tu, maxco, nouter, nconv, navg, lt, decay),
        alphaDeg=alpha, Uinf=U, Ux=U * ux, Uy=U * uy,
        dragDir=(ux, uy, 0.0), liftDir=(-uy, ux, 0.0), turbulenceModel=MODELS[model],
        nOuterCorrectors=nouter, nProcs=nprocs, rhoInf=RHO, nu=NU, cRef=C_REF, dz=DZ, Aref=C_REF * DZ,
        CofR=(0.0, 0.0, 0.0),
        TuBodyPercent=turb["Tu_body_pct"], TuInletPercent=turb["Tu_inlet_pct"], kInlet=turb["k"],
        omegaInlet=turb["omega"], nutInlet=turb["nut"], ReThetatInlet=turb["ReThetat"],
        # free-stream decay (constant/turbulenceProperties: decayControl, kInf, omegaInf)
        freestreamDecay=decay, freestreamDecayControl="yes" if turb["decayControl"] else "no",
        kAmbient=turb["kInf"], omegaAmbient=turb["omegaInf"],
        turbulenceLengthScale=lt, viscosityRatioFarField=turb["vr_far"], viscosityRatioBody=turb["vr_body"],
        convTime=tc, yPlusInterval=min(1.0, nconv / 10) * tc, endTime=nconv * tc, averageStart=(nconv - navg) * tc, writeInterval=nconv / 15 * tc,
        sampleInterval=tc / 50, deltaT0=1e-5 * tc, maxDeltaT=tc / 20, maxCo=maxco,
        nConv=nconv, nAvg=navg, level=level, model=model, ReChord=U * C_REF / NU,
        probeLocations=probes,
    )


def _fmt(v):
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)) and v and isinstance(v[0], (list, tuple)):
        return "\n(\n" + "\n".join("    (" + " ".join(f"{x:.10g}" for x in p) + ")" for p in v) + "\n)"
    if isinstance(v, (list, tuple)):
        return "(" + " ".join(f"{x:.10g}" for x in v) + ")"
    if isinstance(v, float):
        return f"{v:.10g}"
    return str(v)


def write_case_parameters(path, P):
    lines = ["/*--- written by cfd/section2d/run_case.py; edit run_case.py, not this file ---*/",
             "FoamFile\n{\n    version     2.0;\n    format      ascii;\n    class       dictionary;\n"
             "    object      caseParameters;\n}\n"]
    for k, v in P.items():
        lines.append(f"{k:<24}{_fmt(v)};")
    Path(path).write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- OpenFOAM calls
def foam(case, cmd, log, append=False, caffeinate=False, timeout=None):
    """Run a command in the OpenFOAM environment (launcher), output to case/log."""
    redir = ">>" if append else ">"
    full = ["openfoam2606", "-c", f"cd {case} && {cmd} {redir} {log} 2>&1"]
    if caffeinate:
        full = ["caffeinate", "-is"] + full     # no idle sleep; no system sleep while on AC power
    full = foam_launch.adapt(full)              # unchanged unless CFD_FOAM_LAUNCH is set (cfd/hpc/README.md)
    p = subprocess.Popen(full, start_new_session=True)
    _CHILD.append(p)
    try:
        rc = p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill(p)
        rc = "timeout"
    finally:
        _CHILD.remove(p)
    return rc


_CHILD = []


def _kill(p):
    try:
        os.killpg(p.pid, signal.SIGTERM)
        p.wait(timeout=30)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _on_signal(signum, frame):
    for p in list(_CHILD):
        _kill(p)
    raise SystemExit(f"run_case.py: stopped by signal {signum}")


# --------------------------------------------------------------------------- mesh cache
def mesh_dir(level, alpha):
    return MESHES / f"{level}_a{alpha:05.1f}"


def ensure_mesh(level, alpha):
    d = mesh_dir(level, alpha)
    ok = d / "MESH_OK"
    if ok.exists():
        return d
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    shutil.copytree(TEMPLATE / "system", d / "system")
    r = subprocess.run([str(VENV_PY), str(MAKE_MESH), "--level", level, "--alpha", f"{alpha:g}", "--out", str(d),
                        "--plot", str(d / "mesh.png")], capture_output=True, text=True)
    (d / "log.make_mesh").write_text(r.stdout + r.stderr)
    if r.returncode:
        raise RuntimeError(f"make_mesh failed, see {d / 'log.make_mesh'}")
    if foam(d, "renumberMesh -overwrite", "log.renumberMesh"):
        raise RuntimeError(f"renumberMesh failed, see {d / 'log.renumberMesh'}")
    foam(d, "checkMesh", "log.checkMesh")
    log = (d / "log.checkMesh").read_text()
    # keep a tracked copy of every mesh's checkMesh log and mesh_info (mesh/logs/)
    logs = HERE / "mesh" / "logs"
    logs.mkdir(exist_ok=True)
    shutil.copy(d / "log.checkMesh", logs / f"checkMesh_{d.name}.log")
    shutil.copy(d / "mesh_info.json", logs / f"mesh_info_{d.name}.json")
    if "Mesh OK." not in log:
        raise RuntimeError(f"checkMesh did not report 'Mesh OK', see {d / 'log.checkMesh'}")
    ok.write_text(time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")
    return d


# --------------------------------------------------------------------------- case
def time_dirs(path):
    out = []
    for q in Path(path).iterdir() if Path(path).exists() else []:
        try:
            out.append((float(q.name), q.name))
        except ValueError:
            pass
    return sorted(out)


def latest_proc_time(case):
    t = time_dirs(Path(case) / "processor0")
    return t[-1][0] if t else None


def set_stop_at(case, value):
    cd = Path(case) / "system" / "controlDict"
    s = cd.read_text()
    s = re.sub(r"^stopAt\s+\w+;", f"stopAt          {value};", s, flags=re.M)
    cd.write_text(s)


def create_case(case, P, level, alpha):
    md = ensure_mesh(level, alpha)
    if case.exists():
        shutil.rmtree(case)
    case.mkdir(parents=True)
    shutil.copytree(TEMPLATE / "constant", case / "constant")
    shutil.copytree(TEMPLATE / "system", case / "system")
    shutil.copytree(TEMPLATE / "0.orig", case / "0")
    shutil.copytree(md / "constant" / "polyMesh", case / "constant" / "polyMesh")
    shutil.copy(md / "mesh_info.json", case / "mesh_info.json")
    shutil.copy(md / "log.checkMesh", case / "log.checkMesh")
    write_case_parameters(case / "system" / "caseParameters", P)
    (case / "case.json").write_text(json.dumps(P, indent=1))
    (case / "case.foam").touch()


def n_processor_dirs(case):
    return len([q for q in Path(case).glob("processor[0-9]*") if q.is_dir()])


def run(alpha, U, model, level, tu=1.0, nconv=NCONV_DEFAULT, navg=NAVG_DEFAULT, maxco=MAXCO_DEFAULT,
        nouter=NOUTER_DEFAULT, lt=None, decay=DECAY_DEFAULT,
        setup_only=False, force=False, wall_limit=None, keep_processors=False, quiet=False,
        np=NP, name=None):
    """Returns 'complete', 'skipped', 'setup', 'stopped', 'timeout' or 'failed'.
    lt None = the default of the decay mode; name overrides the case folder name
    (tests: names starting with '_' are left out of the CSV)."""
    say = (lambda *a: None) if quiet else (lambda *a: print(*a, flush=True))
    lt = lt_default(decay) if lt is None else lt
    name = name or case_name(alpha, U, model, level, tu, maxco, nouter, nconv, navg, lt, decay)
    case = RUNS / name
    res = case / "results.json"
    if res.exists() and not force:
        if json.loads(res.read_text()).get("complete"):
            say(f"[skip] {name}: complete")
            return "skipped"
    P = case_parameters(alpha, U, model, level, tu, nconv, navg, maxco, nouter, lt, decay, name, np)
    if not force and foam_launch.migrated(case):
        # moved from another machine (cfd/hpc/migrate.py): reconstructed time, no processor*/
        foam_launch.redecompose(case, np, foam, say)
    t_last = latest_proc_time(case) if case.exists() else None
    resume = (not force) and t_last is not None and t_last > 0 and (case / "case.json").exists()
    if resume:
        old = json.loads((case / "case.json").read_text())
        # kAmbient/omegaAmbient: absent in cases set up before decay control (= no decay control)
        if any(abs(float(old.get(k, 0.0)) - float(P[k])) > 1e-9 * max(1.0, abs(float(P[k])))
               for k in ("Ux", "Uy", "kInlet", "omegaInlet", "kAmbient", "omegaAmbient", "endTime")) \
                or old["turbulenceModel"] != P["turbulenceModel"]:
            raise RuntimeError(f"{name}: existing case has different parameters; use --force to restart it")
        n_old = n_processor_dirs(case)
        if n_old != np:
            say(f"[resume] {name} is decomposed for {n_old} ranks; running on {n_old}, not {np}")
            np = n_old
        say(f"[resume] {name} from t = {t_last:g} s ({t_last / P['convTime']:.1f} c/U)")
        set_stop_at(case, "endTime")
    else:
        say(f"[setup] {name}")
        create_case(case, P, level, alpha)
        if setup_only:
            return "setup"
        rc = foam(case, "decomposePar -force", "log.decomposePar")
        if rc:
            say(f"[fail] {name}: decomposePar, see {case / 'log.decomposePar'}")
            return "failed"
    if setup_only:
        return "setup"
    # solve. RUNNING (this pid) exists only while the solver runs: the finally removes it on a
    # normal return, an exception or a stop signal (_on_signal raises SystemExit). It stays only
    # if this process is killed outright (SIGKILL, crash, power loss); queue.py --status and
    # record_lib then call it stale once no solver process names the case and the log has not
    # been written for 10 min (record_lib.marker_state).
    (case / "RUNNING").write_text(f"{os.getpid()}\n")
    try:
        t0, m0 = time.time(), time.monotonic()
        say(f"[run] {name}: pimpleFoam on {np} ranks, end {P['endTime']:.6g} s ({nconv} c/U), log {case / 'log.pimpleFoam'}")
        rc = foam(case, f"mpirun -np {np} pimpleFoam -parallel", "log.pimpleFoam", append=resume,
                  caffeinate=True, timeout=wall_limit)
        t1, m1 = time.time(), time.monotonic()
    finally:
        (case / "RUNNING").unlink(missing_ok=True)
    tim = case / "timing.json"
    sessions = json.loads(tim.read_text()) if tim.exists() else []
    # wall_s is elapsed clock time; awake_s excludes system sleep (macOS monotonic clock)
    sessions.append(dict(start=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0)), wall_s=round(t1 - t0, 1),
                         awake_s=round(m1 - m0, 1),
                         t_start=t_last or 0.0, t_end=latest_proc_time(case), rc=str(rc)))
    tim.write_text(json.dumps(sessions, indent=1))
    t_end = latest_proc_time(case) or 0.0
    if rc == "timeout":
        say(f"[timeout] {name}: stopped after {wall_limit} s at t = {t_end:g} s")
        return "timeout"
    done = t_end >= P["endTime"] * (1 - 1e-6)
    if not done:
        stopped = re.search(r"^stopAt\s+writeNow;", (case / "system" / "controlDict").read_text(), re.M)
        if stopped:
            say(f"[paused] {name} at t = {t_end:g} s; re-run to resume")
            return "stopped"
        say(f"[fail] {name}: solver exited (rc {rc}) at t = {t_end:g} s, see {case / 'log.pimpleFoam'}")
        return "failed"
    rc = foam(case, "reconstructPar -latestTime", "log.reconstructPar")
    if rc:
        say(f"[fail] {name}: reconstructPar")
        return "failed"
    import section_summary
    summ = section_summary.summarize(case)
    summ["complete"] = True
    res.write_text(json.dumps(summ, indent=1))
    if not keep_processors:
        for q in case.glob("processor*"):
            shutil.rmtree(q)
    say(f"[done] {name}: Cd {summ['Cd_mean']:.3f} +- {summ['Cd_std']:.3f}, Cl {summ['Cl_mean']:.3f}, "
        f"St {summ['St']:.3f}, y+max {summ['yplus_max_mean']:.2f}, wall {summ['wall_time_s'] / 3600:.2f} h")
    return "complete"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alpha", type=float, required=True, help="deg; 0 = cup into the wind (README)")
    ap.add_argument("--U", type=float, required=True, help="free-stream speed, m/s")
    ap.add_argument("--model", choices=MODELS, required=True, help="SST = kOmegaSST, LM = kOmegaSSTLM")
    ap.add_argument("--level", choices=LEVELS, default="medium")
    ap.add_argument("--tu", type=float, default=1.0, help="Tu reaching the section, %% (default 1)")
    ap.add_argument("--decay", choices=DECAY_MODES, default=DECAY_DEFAULT,
                    help="free-stream turbulence: 'control' = kOmegaSST decayControl, far field at the "
                         "target Tu (default); 'precompensate' = the 7 Oct smoke-test set-up (README)")
    ap.add_argument("--lt", type=float, default=None,
                    help="free-stream turbulence length scale, m (default %g with --decay control, "
                         "%g with precompensate)" % (LT_DEFAULTS["control"], LT_DEFAULTS["precompensate"]))
    ap.add_argument("--nconv", type=float, default=NCONV_DEFAULT,
                    help="end time in convective times c/U (default %(default)g)")
    ap.add_argument("--navg", type=float, default=NAVG_DEFAULT,
                    help="averaging window, last N c/U (default %(default)g)")
    ap.add_argument("--maxco", type=float, default=MAXCO_DEFAULT, help="max Courant number (default %(default)g)")
    ap.add_argument("--nouter", type=int, default=NOUTER_DEFAULT, help="PIMPLE outer correctors (default %(default)d)")
    ap.add_argument("--setup-only", action="store_true")
    ap.add_argument("--force", action="store_true", help="delete and redo the case")
    ap.add_argument("--wall-limit", type=float, help="kill the solver after this many seconds")
    ap.add_argument("--keep-processors", action="store_true")
    ap.add_argument("--np", type=int, default=NP, help="MPI ranks (default %(default)d; tests at most 2)")
    ap.add_argument("--name", help="case folder name instead of the automatic one (tests: start it "
                                   "with '_' so the CSV leaves it out)")
    a = ap.parse_args()
    if a.np < 1:
        ap.error("--np must be at least 1")
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, _on_signal)
    st = run(a.alpha, a.U, a.model, a.level, a.tu, a.nconv, a.navg, a.maxco, a.nouter, a.lt, a.decay,
             a.setup_only, a.force, a.wall_limit, a.keep_processors, np=a.np, name=a.name)
    sys.exit(0 if st in ("complete", "skipped", "setup", "timeout", "stopped") else 1)


if __name__ == "__main__":
    main()
