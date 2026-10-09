#!/usr/bin/env python3
"""Create and run one Stage 2 (roughness) section case: 2D URANS, pimpleFoam, 4 MPI ranks.

    # 2b rough wall: wall-function mesh, kOmegaSST + nutkRoughWallFunction, Ks in micrometres
    python3 cfd/stage2/run_case.py --alpha 0 --U 23 --wall wf --ks 100
    python3 cfd/stage2/run_case.py --alpha 0 --U 23 --wall wf --ks 0          # smooth reference, same mesh
    # 2e resolved texture: low-Re mesh with the fuzzy-skin displacement t (mm), SST or LM
    python3 cfd/stage2/run_case.py --alpha 0 --U 23 --wall tex --tex 0.2 --model LM
    python3 cfd/stage2/run_case.py ... --setup-only | --wall-limit 600 | --np 2 --name _test_x

Copied from cfd/section2d/run_case.py (8 Oct 2026) and extended; the Stage 1 files are not
touched. Free stream, schemes, solver settings, run length (150 c/U, average over the last
100), function objects, resume and stop behaviour are those of Stage 1
(cfd/section2d/README.md sections 3-4), with three differences:
  * walls: patch blade (outer and inner surface, fuzzy-skin painted) and bladeEnds (square
    end faces); forces sum both;
  * wall wf: k kqRWallFunction, nut nutkRoughWallFunction (Ks on blade = --ks, on bladeEnds
    = --ks-ends, default 0; Cs = --cs, default 0.5), omega omegaWallFunction; SST only
    (the transition model needs the low-Re wall);
  * wall tex: as Stage 1 (k = 0, nutLowReWallFunction, omegaWallFunction), SST or LM; every
    tex case (t = 0 included, so each t is compared with t = 0 under the same numerics) runs
    with 'limited corrected 0.33' and one non-orthogonal corrector (Stage 1: 0.5 and 0), which
    the steep facets of t = 0.2 mm need. A wf mesh above 60 deg would get them too.

Case folder cfd/stage2/runs/<name>/:
  wf   a<alpha>_U<U>_SST_wf_Ks<um>_Tu<Tu>          e.g. a000.0_U23.0_SST_wf_Ks100_Tu1.0
  tex  a<alpha>_U<U>_<model>_tex<t mm>_s<seed>_Tu<Tu>  e.g. a180.0_U23.0_LM_tex0.200_s1_Tu1.0
plus Stage 1's suffixes (_Co, _N, _lt, _precomp) and _KsE<um> (--ks-ends not 0), _Cs<Cs>
(--cs not 0.5), _n<nseg> (texture wall cells per 0.2 mm, not 5). Meshes are cached in
runs/_mesh/wf_U<U>_a<alpha>/ and runs/_mesh/tex<t>_s<seed>_n<nseg>_a<alpha>/ and pass a
checkMesh test first (wf: 'Mesh OK'; tex: 'Mesh OK', or only the skewness check failing with
max skewness <= TEX_MAX_SKEW and max non-orthogonality <= TEX_MAX_NONORTH, recorded as
'relaxed' in case.json and the CSV).

Resume-safe as Stage 1: a complete case (results.json) is skipped; a partial one restarts from
its last write; it refuses to resume, without --force, if U, the free stream, the end time, the
model, Ks, Cs or the texture differ. runs/<name>/RUNNING exists while the solver runs.

OpenFOAM only through the launcher: openfoam2606 -c "cd <case> && ...". The mesh generator
runs in cfd/.venv (gmsh); everything else in the system python3.
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

HERE = Path(__file__).resolve().parent              # cfd/stage2
# keep cfd/stage2 off sys.path: its queue.py would shadow the standard-library 'queue'
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != HERE]
CFD = HERE.parent
RUNS = HERE / "runs"
MESHES = RUNS / "_mesh"
TEMPLATE = HERE / "case_template"
VENV_PY = CFD / ".venv" / "bin" / "python"
MAKE_MESH = HERE / "mesh" / "make_mesh.py"
MESH_LOGS = HERE / "mesh" / "logs"
sys.path.insert(0, str(CFD / "post"))
import foam_launch  # noqa: E402  cfd/post/foam_launch.py: CFD_FOAM_LAUNCH (Unity container), migrated cases

NU = 1.516e-5           # m^2/s, cfd/templates/transportProperties
RHO = 1.204             # kg/m^3, cfd/templates/flowConstants
C_REF = 0.048           # m, reference chord
DZ = 1.0e-3             # m, cell depth
R_FF = 27.0 * C_REF     # m, far-field radius
BETA, BETA_STAR = 0.0828, 0.09
MODELS = {"SST": "kOmegaSST", "LM": "kOmegaSSTLM"}
WALLS = ("wf", "tex")
WAKE_PROBES = [(1, 0), (1, 0.5), (1, -0.5), (2, 0), (2, 0.5), (2, -0.5), (4, 0), (4, 0.5), (4, -0.5)]
UPSTREAM_PROBE = (-2, 0)
NP = int(os.environ.get("SLURM_NTASKS") or 4)   # a Slurm job's task count on Unity (cfd/hpc/)
CMU25 = 0.09 ** 0.25
DECAY_MODES = ("control", "precompensate")
DECAY_DEFAULT = "control"
LT_DEFAULTS = {"control": 1.0e-3, "precompensate": 2.0e-3}
MAXCO_DEFAULT = 5.0
NOUTER_DEFAULT = 2
NCONV_DEFAULT = 150.0
NAVG_DEFAULT = 100.0
CS_DEFAULT = 0.5
SEED_DEFAULT = 1
NSEG_DEFAULT = 5
TEX_MAX_SKEW = 8.0          # tex meshes: largest accepted checkMesh skewness (OpenFOAM flags > 4)
TEX_MAX_NONORTH = 85.0      # deg, largest accepted checkMesh non-orthogonality (tex meshes)
NONORTH_SWITCH = 60.0       # deg; above it: limited corrected 0.33 + 1 non-orthogonal corrector
                            # (tex: always, so that t and its t = 0 reference share the numerics)


def lt_default(decay=DECAY_DEFAULT):
    return LT_DEFAULTS[decay]


# --------------------------------------------------------------------------- names
def case_name(alpha, U, model, wall, tu=1.0, ks=0.0, ks_ends=0.0, cs=CS_DEFAULT, t=0.0, seed=SEED_DEFAULT,
              nseg=NSEG_DEFAULT, maxco=MAXCO_DEFAULT, nouter=NOUTER_DEFAULT, nconv=NCONV_DEFAULT,
              navg=NAVG_DEFAULT, lt=None, decay=DECAY_DEFAULT):
    """ks, ks_ends in micrometres; t in millimetres."""
    s = f"a{alpha:05.1f}_U{U:04.1f}_{model}_"
    if wall == "wf":
        s += f"wf_Ks{ks:g}"
        if ks_ends:
            s += f"_KsE{ks_ends:g}"
        if cs != CS_DEFAULT:
            s += f"_Cs{cs:g}"
    else:
        s += f"tex{t:.3f}_s{seed}"
        if nseg != NSEG_DEFAULT:
            s += f"_n{nseg}"
    s += f"_Tu{tu:.1f}"
    if maxco != MAXCO_DEFAULT or nouter != NOUTER_DEFAULT:
        s += f"_Co{maxco:g}n{nouter}"
    if nconv != NCONV_DEFAULT or navg != NAVG_DEFAULT:
        s += f"_N{nconv:g}A{navg:g}"
    if lt is not None and abs(lt - lt_default(decay)) > 1e-12:
        s += f"_lt{lt * 1e3:g}"
    if decay != DECAY_DEFAULT:
        s += "_precomp"
    return s


def mesh_dir(wall, alpha, U=None, t=0.0, seed=SEED_DEFAULT, nseg=NSEG_DEFAULT):
    if wall == "wf":
        return MESHES / f"wf_U{U:04.1f}_a{alpha:05.1f}"
    return MESHES / f"tex{t:.3f}_s{seed}_n{nseg}_a{alpha:05.1f}"


# --------------------------------------------------------------------------- free stream (Stage 1)
def rethetat_from_tu(tu_pct):
    """Free-stream transition-onset Re_theta, Langtry & Menter (2009), zero pressure gradient."""
    tu = max(tu_pct, 0.027)
    if tu <= 1.3:
        r = 1173.51 - 589.428 * tu + 0.2196 / tu ** 2
    else:
        r = 331.50 * (tu - 0.5658) ** -0.671
    return max(r, 20.0)


def inlet_turbulence(U, tu_body_pct, lt, L, decay=DECAY_DEFAULT):
    """Stage 1 free stream (cfd/section2d/run_case.py): decay control holds the far-field
    k = 1.5 (Tu U)^2, omega = sqrt(k)/(Cmu^0.25 lt) up to the section."""
    if decay == "precompensate":
        return inlet_turbulence_precompensate(U, tu_body_pct, lt, L)
    tu = tu_body_pct / 100
    k = 1.5 * (tu * U) ** 2
    w = math.sqrt(k) / (CMU25 * lt)
    return dict(Tu_inlet_pct=tu_body_pct, Tu_body_pct=tu_body_pct, k=k, omega=w, nut=k / w,
                vr_far=k / w / NU, vr_body=k / w / NU, length_scale_m=lt, decay_distance_m=L,
                ReThetat=rethetat_from_tu(tu_body_pct), decayControl=True, kInf=k, omegaInf=w)


def inlet_turbulence_precompensate(U, tu_body_pct, lt, L):
    t = L / U

    def at_body(tu0):
        k0 = 1.5 * (tu0 * U) ** 2
        w0 = math.sqrt(k0) / (CMU25 * lt)
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


# --------------------------------------------------------------------------- parameters
def case_parameters(c, name, nprocs, mesh_info=None, nonorth_max=None):
    """c: dict(alpha, U, model, wall, tu, ks, ks_ends, cs, t, seed, nseg, nconv, navg, maxco,
    nouter, lt, decay). Lengths in caseParameters are SI (Ks in m)."""
    lt = lt_default(c["decay"]) if c["lt"] is None else c["lt"]
    U, alpha = c["U"], c["alpha"]
    a = math.radians(alpha)
    ux, uy = math.cos(a), math.sin(a)
    tc = C_REF / U
    turb = inlet_turbulence(U, c["tu"], lt, R_FF - 0.5 * C_REF, c["decay"])
    probes = []
    for xc, yc in WAKE_PROBES + [UPSTREAM_PROBE]:
        probes.append(((xc * ux - yc * uy) * C_REF, (xc * uy + yc * ux) * C_REF, 0.5 * DZ))
    nconv, navg = c["nconv"], c["navg"]
    steep = c["wall"] == "tex" or (nonorth_max is not None and nonorth_max > NONORTH_SWITCH)
    P = dict(
        caseName=name, alphaDeg=alpha, Uinf=U, Ux=U * ux, Uy=U * uy,
        dragDir=(ux, uy, 0.0), liftDir=(-uy, ux, 0.0), turbulenceModel=MODELS[c["model"]],
        nOuterCorrectors=c["nouter"], nProcs=nprocs, rhoInf=RHO, nu=NU, cRef=C_REF, dz=DZ, Aref=C_REF * DZ,
        CofR=(0.0, 0.0, 0.0),
        TuBodyPercent=turb["Tu_body_pct"], TuInletPercent=turb["Tu_inlet_pct"], kInlet=turb["k"],
        omegaInlet=turb["omega"], nutInlet=turb["nut"], ReThetatInlet=turb["ReThetat"],
        freestreamDecay=c["decay"], freestreamDecayControl="yes" if turb["decayControl"] else "no",
        kAmbient=turb["kInf"], omegaAmbient=turb["omegaInf"],
        turbulenceLengthScale=lt, viscosityRatioFarField=turb["vr_far"], viscosityRatioBody=turb["vr_body"],
        convTime=tc, yPlusInterval=min(1.0, nconv / 10) * tc, endTime=nconv * tc,
        averageStart=(nconv - navg) * tc, writeInterval=nconv / 15 * tc,
        sampleInterval=tc / 50, deltaT0=1e-5 * tc, maxDeltaT=tc / 20, maxCo=c["maxco"],
        nConv=nconv, nAvg=navg, level=c["wall"], model=c["model"], ReChord=U * C_REF / NU,
        # Stage 2
        stage=2, wall=c["wall"],
        KsBlade=c["ks"] * 1e-6 if c["wall"] == "wf" else 0.0,
        KsEnds=c["ks_ends"] * 1e-6 if c["wall"] == "wf" else 0.0,
        Cs=c["cs"], texT=c["t"] * 1e-3 if c["wall"] == "tex" else 0.0,
        texSeed=c["seed"], texNseg=c["nseg"],
        nonOrthLimit=0.33 if steep else 0.5, nNonOrthCorr=1 if steep else 0,
        probeLocations=probes,
    )
    if mesh_info:
        P["h0"] = mesh_info.get("h0_m", 0.0)
        P["yP"] = 0.5 * P["h0"]
        if c["wall"] == "wf":
            P["KsOverYp"] = P["KsBlade"] / P["yP"] if P["yP"] else float("nan")
        P["nCells"] = mesh_info.get("n_cells", 0)
    if nonorth_max is not None:
        P["meshNonOrthMax"] = nonorth_max
    return P


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
    lines = ["/*--- written by cfd/stage2/run_case.py; edit run_case.py, not this file ---*/",
             "FoamFile\n{\n    version     2.0;\n    format      ascii;\n    class       dictionary;\n"
             "    object      caseParameters;\n}\n"]
    for k, v in P.items():
        if isinstance(v, (dict,)) or v is None:
            continue
        lines.append(f"{k:<24}{_fmt(v)};")
    Path(path).write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- OpenFOAM calls
_CHILD = []


def foam(case, cmd, log, append=False, caffeinate=False, timeout=None):
    """Run a command in the OpenFOAM environment (launcher), output to case/log."""
    redir = ">>" if append else ">"
    full = ["openfoam2606", "-c", f"cd {case} && {cmd} {redir} {log} 2>&1"]
    if caffeinate:
        full = ["caffeinate", "-is"] + full
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
def check_mesh_log(log, relaxed):
    """('OK' | 'relaxed: ...', max non-orthogonality) or raise. relaxed (tex meshes): accept a
    failure of the skewness check alone if max skewness <= TEX_MAX_SKEW and the maximum
    non-orthogonality <= TEX_MAX_NONORTH."""
    m = re.search(r"Mesh non-orthogonality Max: ([\d.eE+-]+)", log)
    nonorth = float(m.group(1)) if m else float("nan")
    if "Mesh OK." in log:
        return "OK", nonorth
    if not relaxed:
        raise RuntimeError("checkMesh did not report 'Mesh OK'")
    fails = [ln.strip() for ln in log.splitlines() if ln.strip().startswith("***")]
    m = re.search(r"Max skewness = ([\d.eE+-]+)", log)
    skew = float(m.group(1)) if m else float("inf")
    nfail = re.search(r"Failed (\d+) mesh checks", log)
    only_skew = fails and all("skewness" in f for f in fails) and nfail and int(nfail.group(1)) == 1
    if only_skew and skew <= TEX_MAX_SKEW and nonorth <= TEX_MAX_NONORTH:
        n = re.search(r"Max skewness = [\d.eE+-]+, (\d+) highly skew", log)
        return (f"relaxed: max skewness {skew:.3g} ({n.group(1) if n else '?'} faces > 4), "
                f"max non-orthogonality {nonorth:.1f} deg"), nonorth
    raise RuntimeError(f"checkMesh failed beyond the relaxed texture criteria: {fails}")


def ensure_mesh(c):
    d = mesh_dir(c["wall"], c["alpha"], c["U"], c["t"], c["seed"], c["nseg"])
    ok = d / "MESH_OK"
    if ok.exists():
        st = json.loads(ok.read_text())
        return d, st
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    shutil.copytree(TEMPLATE / "system", d / "system")
    cmd = [str(VENV_PY), str(MAKE_MESH), "--level", c["wall"], "--alpha", f"{c['alpha']:g}", "--out", str(d),
           "--plot", str(d / "mesh.png")]
    if c["wall"] == "wf":
        cmd += ["--U", f"{c['U']:g}"]
    else:
        cmd += ["--tex", f"{c['t'] * 1e-3:.9g}", "--seed", str(c["seed"]), "--nseg", str(c["nseg"])]
    r = subprocess.run(cmd, capture_output=True, text=True)
    (d / "log.make_mesh").write_text(r.stdout + r.stderr)
    if r.returncode:
        raise RuntimeError(f"make_mesh failed, see {d / 'log.make_mesh'}")
    if foam(d, "renumberMesh -overwrite", "log.renumberMesh"):
        raise RuntimeError(f"renumberMesh failed, see {d / 'log.renumberMesh'}")
    foam(d, "checkMesh", "log.checkMesh")
    log = (d / "log.checkMesh").read_text()
    MESH_LOGS.mkdir(parents=True, exist_ok=True)
    shutil.copy(d / "log.checkMesh", MESH_LOGS / f"checkMesh_{d.name}.log")
    shutil.copy(d / "mesh_info.json", MESH_LOGS / f"mesh_info_{d.name}.json")
    status, nonorth = check_mesh_log(log, relaxed=(c["wall"] == "tex"))
    st = dict(time=time.strftime("%Y-%m-%dT%H:%M:%S"), check=status, nonorth_max=nonorth)
    ok.write_text(json.dumps(st) + "\n")
    return d, st


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


def create_case(case, P, md, mesh_status):
    if case.exists():
        shutil.rmtree(case)
    case.mkdir(parents=True)
    shutil.copytree(TEMPLATE / "constant", case / "constant")
    shutil.copytree(TEMPLATE / "system", case / "system")
    shutil.copytree(TEMPLATE / "0.orig", case / "0")
    if P["wall"] == "tex":
        for f in (TEMPLATE / "0.lowRe").iterdir():
            shutil.copy(f, case / "0" / f.name)
    shutil.copytree(md / "constant" / "polyMesh", case / "constant" / "polyMesh")
    for f in ("mesh_info.json", "log.checkMesh", "mesh.png"):
        if (md / f).exists():
            shutil.copy(md / f, case / f)
    write_case_parameters(case / "system" / "caseParameters", P)
    P = dict(P, meshDir=str(md.relative_to(HERE)), meshCheck=mesh_status["check"])
    (case / "case.json").write_text(json.dumps(P, indent=1))
    (case / "case.foam").touch()


def n_processor_dirs(case):
    return len([q for q in Path(case).glob("processor[0-9]*") if q.is_dir()])


DEFAULTS = dict(model="SST", tu=1.0, ks=0.0, ks_ends=0.0, cs=CS_DEFAULT, t=0.0, seed=SEED_DEFAULT,
                nseg=NSEG_DEFAULT, nconv=NCONV_DEFAULT, navg=NAVG_DEFAULT, maxco=MAXCO_DEFAULT,
                nouter=NOUTER_DEFAULT, lt=None, decay=DECAY_DEFAULT)


def normalise(c):
    c = dict(DEFAULTS, **{k: v for k, v in c.items() if v is not None or k == "lt"})
    if c["wall"] not in WALLS:
        raise ValueError(f"wall must be one of {WALLS}")
    if c["model"] not in MODELS:
        raise ValueError(f"model must be one of {tuple(MODELS)}")
    if c["wall"] == "wf" and c["model"] != "SST":
        raise ValueError("wall wf runs kOmegaSST only: the transition model needs the low-Re wall (wall tex)")
    if c["wall"] == "wf":
        c.update(t=0.0)
    else:
        c.update(ks=0.0, ks_ends=0.0)
    if c["decay"] not in DECAY_MODES:
        raise ValueError(f"decay must be one of {DECAY_MODES}")
    if c["lt"] is None:
        c["lt"] = lt_default(c["decay"])
    return c


def name_of(c):
    c = normalise(c)
    return case_name(c["alpha"], c["U"], c["model"], c["wall"], c["tu"], c["ks"], c["ks_ends"], c["cs"],
                     c["t"], c["seed"], c["nseg"], c["maxco"], c["nouter"], c["nconv"], c["navg"], c["lt"],
                     c["decay"])


def run(c, setup_only=False, force=False, wall_limit=None, keep_processors=False, quiet=False, np=NP, name=None):
    """c: case dict (alpha, U, wall and the optional keys of DEFAULTS). Returns 'complete',
    'skipped', 'setup', 'stopped', 'timeout' or 'failed'."""
    say = (lambda *a: None) if quiet else (lambda *a: print(*a, flush=True))
    c = normalise(c)
    name = name or name_of(c)
    case = RUNS / name
    res = case / "results.json"
    if res.exists() and not force:
        if json.loads(res.read_text()).get("complete"):
            say(f"[skip] {name}: complete")
            return "skipped"
    if not force and foam_launch.migrated(case):
        # moved from another machine (cfd/hpc/migrate.py): reconstructed time, no processor*/
        foam_launch.redecompose(case, np, foam, say)
    t_last = latest_proc_time(case) if case.exists() else None
    resume = (not force) and t_last is not None and t_last > 0 and (case / "case.json").exists()
    if resume:
        old = json.loads((case / "case.json").read_text())
        P = case_parameters(c, name, np, nonorth_max=old.get("meshNonOrthMax"))
        keys = ("Ux", "Uy", "kInlet", "omegaInlet", "kAmbient", "omegaAmbient", "endTime", "KsBlade", "KsEnds",
                "Cs", "texT")
        if any(abs(float(old.get(k, 0.0)) - float(P[k])) > 1e-9 * max(1.0, abs(float(P[k]))) for k in keys) \
                or old["turbulenceModel"] != P["turbulenceModel"] or old.get("wall") != P["wall"] \
                or int(old.get("texSeed", SEED_DEFAULT)) != P["texSeed"]:
            raise RuntimeError(f"{name}: existing case has different parameters; use --force to restart it")
        n_old = n_processor_dirs(case)
        if n_old != np:
            say(f"[resume] {name} is decomposed for {n_old} ranks; running on {n_old}, not {np}")
            np = n_old
        say(f"[resume] {name} from t = {t_last:g} s ({t_last / P['convTime']:.1f} c/U)")
        set_stop_at(case, "endTime")
        P = old
    else:
        say(f"[setup] {name}")
        md, mst = ensure_mesh(c)
        mi = json.loads((md / "mesh_info.json").read_text())
        P = case_parameters(c, name, np, mesh_info=mi, nonorth_max=mst.get("nonorth_max"))
        if c["wall"] == "wf" and P.get("KsOverYp", 0) > 1:
            say(f"[warn] {name}: Ks {c['ks']:g} um exceeds the first-cell-centre height {P['yP'] * 1e6:.0f} um "
                f"(nutkRoughWallFunction outside its validity)")
        create_case(case, P, md, mst)
        if setup_only:
            return "setup"
        rc = foam(case, "decomposePar -force", "log.decomposePar")
        if rc:
            say(f"[fail] {name}: decomposePar, see {case / 'log.decomposePar'}")
            return "failed"
    if setup_only:
        return "setup"
    (case / "RUNNING").write_text(f"{os.getpid()}\n")
    try:
        t0, m0 = time.time(), time.monotonic()
        say(f"[run] {name}: pimpleFoam on {np} ranks, end {P['endTime']:.6g} s ({P['nConv']} c/U), "
            f"log {case / 'log.pimpleFoam'}")
        rc = foam(case, f"mpirun -np {np} pimpleFoam -parallel", "log.pimpleFoam", append=resume,
                  caffeinate=True, timeout=wall_limit)
        t1, m1 = time.time(), time.monotonic()
    finally:
        (case / "RUNNING").unlink(missing_ok=True)
    tim = case / "timing.json"
    sessions = json.loads(tim.read_text()) if tim.exists() else []
    sessions.append(dict(start=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0)), wall_s=round(t1 - t0, 1),
                         awake_s=round(m1 - m0, 1), t_start=t_last or 0.0, t_end=latest_proc_time(case),
                         rc=str(rc), np=np))
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
    sys.path.insert(0, str(HERE))
    import stage2_summary
    summ = stage2_summary.summarize(case)
    summ["complete"] = True
    res.write_text(json.dumps(summ, indent=1))
    if not keep_processors:
        for q in case.glob("processor*"):
            shutil.rmtree(q)
    say(f"[done] {name}: Cd {summ['Cd_mean']:.3f} +- {summ['Cd_std']:.3f}, Cl {summ['Cl_mean']:.3f}, "
        f"St {summ['St']:.3f}, wall {summ.get('wall_time_s', 0) / 3600:.2f} h")
    return "complete"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alpha", type=float, required=True, help="deg; 0 = cup into the wind (Stage 1 README)")
    ap.add_argument("--U", type=float, required=True, help="free-stream speed, m/s")
    ap.add_argument("--wall", choices=WALLS, required=True,
                    help="wf = wall functions + nutkRoughWallFunction (SST); tex = resolved texture, low-Re")
    ap.add_argument("--model", choices=MODELS, default="SST", help="SST (default) or LM (tex only)")
    ap.add_argument("--ks", type=float, default=0.0, help="wf: sand-grain height Ks on the painted faces, um")
    ap.add_argument("--ks-ends", type=float, default=0.0, help="wf: Ks on the end faces, um (default 0)")
    ap.add_argument("--cs", type=float, default=CS_DEFAULT, help="wf: roughness constant Cs (default 0.5)")
    ap.add_argument("--tex", type=float, default=0.0, help="tex: fuzzy-skin amplitude t, mm (0 = smooth)")
    ap.add_argument("--seed", type=int, default=SEED_DEFAULT, help="tex: random seed (default 1)")
    ap.add_argument("--nseg", type=int, default=NSEG_DEFAULT, help="tex: wall cells per 0.2 mm (default 5)")
    ap.add_argument("--tu", type=float, default=1.0, help="Tu reaching the section, %% (default 1)")
    ap.add_argument("--decay", choices=DECAY_MODES, default=DECAY_DEFAULT)
    ap.add_argument("--lt", type=float, default=None, help="free-stream length scale, m (default 1 mm)")
    ap.add_argument("--nconv", type=float, default=NCONV_DEFAULT, help="end time in c/U (default %(default)g)")
    ap.add_argument("--navg", type=float, default=NAVG_DEFAULT, help="averaging window, c/U (default %(default)g)")
    ap.add_argument("--maxco", type=float, default=MAXCO_DEFAULT)
    ap.add_argument("--nouter", type=int, default=NOUTER_DEFAULT)
    ap.add_argument("--setup-only", action="store_true")
    ap.add_argument("--force", action="store_true", help="delete and redo the case")
    ap.add_argument("--wall-limit", type=float, help="kill the solver after this many seconds")
    ap.add_argument("--keep-processors", action="store_true")
    ap.add_argument("--np", type=int, default=NP, help="MPI ranks (default %(default)d; tests at most 2)")
    ap.add_argument("--name", help="case folder name (tests: start it with '_' so the CSV leaves it out)")
    a = ap.parse_args()
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, _on_signal)
    c = dict(alpha=a.alpha, U=a.U, wall=a.wall, model=a.model, ks=a.ks, ks_ends=a.ks_ends, cs=a.cs, t=a.tex,
             seed=a.seed, nseg=a.nseg, tu=a.tu, decay=a.decay, lt=a.lt, nconv=a.nconv, navg=a.navg,
             maxco=a.maxco, nouter=a.nouter)
    st = run(c, a.setup_only, a.force, a.wall_limit, a.keep_processors, np=a.np, name=a.name)
    sys.exit(0 if st in ("complete", "skipped", "setup", "timeout", "stopped") else 1)


if __name__ == "__main__":
    main()
