#!/usr/bin/env python3
"""Create and run one Stage 3 2D rotor case (pimpleFoam URANS, cyclicAMI).

Rotating (3b): prescribed Omega = lambda U / R, solidBody rotatingMotion of the
cellZone 'rotor', N revolutions (default 8), averages over the last 3.
Static (3a): blades frozen at azimuth theta, same mesh layout (AMI kept, not moving).

    python3 cfd/rotor2d/run_case.py --hyp A --U 23 --lam 0.15                 # rotating, kOmegaSST, medium, 4 ranks
    python3 cfd/rotor2d/run_case.py --hyp B --U 23 --theta 30                 # static
    python3 cfd/rotor2d/run_case.py --hyp A --U 23 --lam 0.15 --np 2 --level coarse --wall-limit 600   # smoke test
    python3 cfd/rotor2d/run_case.py ... --setup-only      # mesh + case, no solver
    python3 cfd/rotor2d/run_case.py ... --force           # delete and redo
    python3 cfd/rotor2d/run_case.py ... --np 2 --name _test_x   # test: 2 ranks, folder runs/_test_x
    python3 cfd/rotor2d/run_case.py ... --decay precompensate    # the 7 Oct smoke-test free stream

Free-stream turbulence (--decay, README "Free-stream turbulence"; as cfd/section2d):
  control        (default) kOmegaSST decayControl: inlet k and omega are the target values
                 (Tu = --tu, length scale --lt, default 1 mm) and kInf/omegaInf hold them, so Tu
                 at the rotor equals the target from t = 0.
  precompensate  no decay control; inlet Tu raised so that the SST decay over the inlet-to-rotor
                 distance leaves the target (--lt default 10 mm). Case names get '_precomp'.

Options that change the physics or numerics appear in the case name, e.g.
  A_rot_U23.0_lam0.150_SST_medium            (defaults: wf walls, Tu 1 %, decay control, lt 1 mm,
                                              auto sense, nrev 8)
  B_sta_U23.0_th030.0_SST_medium
  A_rot_U23.0_lam0.150_LM_medium_lowRe_Tu3.0_senseCW_beta79_Co1n3
  A_sta_U23.0_th000.0_SST_medium_precomp     (--decay precompensate)
Cases go to cfd/rotor2d/runs/<name>/ (git-ignored). Re-running the same command
skips a complete case (results.json complete) and otherwise resumes from the last
write in processor*/ (startFrom latestTime): an interruption loses at most half a
revolution (rotating) or nconv/10 D/U (static).

Meshes are cached in runs/_mesh/<key>/ and must pass checkMesh ('Mesh OK') before
use; logs are copied to mesh/logs/. Geometry: rotor_geometry.py (hypotheses A, B,
or 'measured' from cfd/inputs/rig_geometry.json).

Coefficients (per unit span, swept area A' = 2R, R = attachment radius, as the
reports' C_P = P/(0.5 rho A v^3) with A = 2RH):
  Q'  = sense * M_z / dz            torque per unit span driving the rotor (N m/m)
  C_Q = Q' / (0.5 rho U^2 (2R) R)
  C_P = Q' Omega / (0.5 rho (2R) U^3) = lambda C_Q

OpenFOAM is called only through the launcher (openfoam2606 -c "cd <case> && ...").
The mesh generator runs in cfd/.venv (gmsh); everything else is the system python3.
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

HERE = Path(__file__).resolve().parent              # cfd/rotor2d
CFD = HERE.parent
RUNS = HERE / "runs"
MESHES = RUNS / "_mesh"
TEMPLATE = HERE / "case_template"
VENV_PY = CFD / ".venv" / "bin" / "python"
MAKE_MESH = HERE / "mesh" / "make_mesh.py"
# cfd/rotor2d goes at the END of sys.path (for rotor_geometry): first, its queue.py would
# shadow the standard-library module 'queue' for any library that imports it.
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != HERE]
sys.path.append(str(HERE))
sys.path.insert(0, str(CFD / "post"))
import rotor_geometry as rg  # noqa: E402

NU = 1.516e-5           # m^2/s, cfd/templates/transportProperties
RHO = 1.204             # kg/m^3, cfd/templates/flowConstants
DZ = 0.01               # m, slab depth (mesh/make_mesh.py DZ)
MODELS = {"SST": "kOmegaSST", "LM": "kOmegaSSTLM"}
LEVELS = ("coarse", "medium", "fine")
WALLS = ("wf", "lowRe")
BETA, BETA_STAR = 0.0828, 0.09      # SST k-epsilon-branch constants (free-stream decay)
CMU25 = 0.09 ** 0.25
# Free-stream turbulence (README "Free-stream turbulence"; same scheme as cfd/section2d/run_case.py):
#  control        (default) kOmegaSST decayControl with kInf = k_inlet, omegaInf = omega_inlet:
#                 no decay from the inlet to the rotor, Tu at the rotor = target from t = 0.
#  precompensate  the 7 Oct smoke-test set-up: no decay control, inlet Tu raised so that the
#                 SST decay over the inlet-to-rotor distance leaves the target. Names get '_precomp'.
DECAY_MODES = ("control", "precompensate")
DECAY_DEFAULT = "control"
# Length scale l = sqrt(k)/(Cmu^0.25 omega), m (assumed; the tunnel's is not measured).
#  control: 1 mm, as Stage 1: the free-stream turbulence is the tunnel's (screens), the same for
#    the section and the rotor; nu_t/nu = sqrt(3/2) Cmu^0.25 Tu U l / nu = 10.2 at 23 m/s, Tu 1 %.
#  precompensate: 10 mm, the 7 Oct smoke-test value (kept for reproducibility).
LT_DEFAULTS = {"control": 1.0e-3, "precompensate": 0.01}
DEFAULTS = dict(level="medium", model="SST", wall="wf", tu=1.0, decay=DECAY_DEFAULT, lt=None, nrev=8, navg=3,
                nconv=40, navgconv=25, maxco=4.0, nouter=2, sense="auto", beta=None, np=4, yplus=None, walls=None,
                side_bc="slip", wdist=1, name=None)


def lt_default(decay=DECAY_DEFAULT):
    return LT_DEFAULTS[decay]
PROBES_D = [(1, 0), (1, 0.5), (1, -0.5), (2, 0), (2, 0.5), (2, -0.5), (4, 0), (-2, 0), (0, 0)]   # rotor diameters


# --------------------------------------------------------------------------- naming
def _g(v):
    return f"{v:g}"


def case_name(c):
    """c: normalised dict (hyp, U, lam or theta, and the DEFAULTS keys). Every non-default
    option is a suffix, so a test or variant never shares a folder (or a 'complete' flag)
    with a production case."""
    if c.get("lam") is not None:
        s = f"{c['hyp']}_rot_U{c['U']:04.1f}_lam{c['lam']:.3f}"
    else:
        s = f"{c['hyp']}_sta_U{c['U']:04.1f}_th{c['theta']:05.1f}"
    s += f"_{c['model']}_{c['level']}"
    if c["wall"] != "wf":
        s += f"_{c['wall']}"
    if c["tu"] != DEFAULTS["tu"]:
        s += f"_Tu{c['tu']:.1f}"
    if c["sense"] != "auto":
        s += f"_sense{c['sense']}"
    if c.get("beta") is not None:
        s += f"_beta{_g(c['beta'])}"
    if c.get("yplus") is not None:
        s += f"_yp{_g(c['yplus'])}"
    if c.get("walls"):
        s += "_walls" + "_".join(_g(v) for v in c["walls"]) + f"_{c['side_bc']}"
    if abs(c["lt"] - lt_default(c["decay"])) > 1e-12:
        s += f"_lt{_g(c['lt'])}"            # m; only if not the decay mode's default
    if c["decay"] != DECAY_DEFAULT:
        s += "_precomp"                       # --decay precompensate (7 Oct smoke-test free stream)
    if c["maxco"] != DEFAULTS["maxco"] or c["nouter"] != DEFAULTS["nouter"]:
        s += f"_Co{_g(c['maxco'])}n{c['nouter']}"
    if c["wdist"] != DEFAULTS["wdist"]:
        s += f"_wd{c['wdist']}"
    # Run length and averaging window are in the name when not the default, so a queue
    # line with nconv/navgconv/navg set is a separate case, not the default one renamed.
    if c.get("lam") is not None:
        if c["nrev"] != DEFAULTS["nrev"]:
            s += f"_rev{c['nrev']}"
        if c["navg"] != DEFAULTS["navg"]:
            s += f"a{c['navg']}" if c["nrev"] != DEFAULTS["nrev"] else f"_rev{c['nrev']}a{c['navg']}"
    elif c["nconv"] != DEFAULTS["nconv"] or c["navgconv"] != DEFAULTS["navgconv"]:
        s += f"_conv{c['nconv']}a{c['navgconv']}"
    return s


def mesh_key(c):
    U_mesh = c["U"]
    s = f"{c['hyp']}_{c['level']}_{c['wall']}_U{U_mesh:04.1f}_th{(c.get('theta') or 0.0):05.1f}"
    if c["sense"] != "auto":
        s += f"_sense{c['sense']}"
    if c.get("beta") is not None:
        s += f"_beta{_g(c['beta'])}"
    if c.get("yplus") is not None:
        s += f"_yp{_g(c['yplus'])}"
    if c.get("walls"):
        s += "_walls" + "_".join(_g(v) for v in c["walls"])
    return s


# --------------------------------------------------------------------------- inflow turbulence
def rethetat_from_tu(tu_pct):
    """Free-stream transition-onset Re_theta, Langtry & Menter (2009), zero pressure gradient."""
    tu = max(tu_pct, 0.027)
    r = 1173.51 - 589.428 * tu + 0.2196 / tu ** 2 if tu <= 1.3 else 331.50 * (tu - 0.5658) ** -0.671
    return max(r, 20.0)


def inlet_turbulence(U, tu_target_pct, lt, L, decay=DECAY_DEFAULT):
    """Inlet k, omega (and the decay-control kInf, omegaInf) for a target Tu at the rotor.

    decay = 'control' (cfd/section2d/run_case.py inlet_turbulence, same method): kOmegaSST
      decayControl (Spalart and Rumsey 2007; v2606 kOmegaSSTBase.C) adds betaStar omegaInf kInf
      to the k equation and beta omegaInf^2 to the omega equation, which cancel the free-stream
      destruction at k = kInf, omega = omegaInf. With kInf = k_inlet and omegaInf = omega_inlet
      the free stream does not decay: Tu at the rotor is the target from t = 0, and
      nu_t/nu = sqrt(3/2) Cmu^0.25 Tu U lt / nu everywhere upstream.
      k = 1.5 (Tu U)^2, omega = sqrt(k)/(Cmu^0.25 lt).
    decay = 'precompensate': inlet_turbulence_precompensate (no decay control)."""
    if decay == "precompensate":
        return inlet_turbulence_precompensate(U, tu_target_pct, lt, L)
    if decay != "control":
        raise ValueError(f"decay must be one of {DECAY_MODES}, not {decay!r}")
    k = 1.5 * (tu_target_pct / 100 * U) ** 2
    w = math.sqrt(k) / (CMU25 * lt)
    return dict(Tu_inlet_pct=tu_target_pct, Tu_rotor_pct=tu_target_pct, k=k, omega=w, nut=k / w,
                vr_inlet=k / w / NU, vr_rotor=k / w / NU, length_scale_m=lt, decay_distance_m=L,
                ReThetat=rethetat_from_tu(tu_target_pct), decayControl=True, kInf=k, omegaInf=w)


def inlet_turbulence_precompensate(U, tu_target_pct, lt, L):
    """Inlet k, omega such that SST free-stream decay over distance L leaves Tu = target
    at the rotor (the 7 Oct smoke tests, lt = 10 mm; no decay control).
    Decay without production: k = k0 (1 + beta w0 t)^(-beta*/beta), w = w0/(1 + beta w0 t), t = L/U."""
    cmu25 = CMU25
    t = L / U

    def at(tu0):
        k0 = 1.5 * (tu0 * U) ** 2
        w0 = math.sqrt(k0) / (cmu25 * lt)
        f = 1 + BETA * w0 * t
        return math.sqrt(2 / 3 * k0 * f ** (-BETA_STAR / BETA)) / U, k0, w0, f

    lo, hi = 1e-6, 1.0
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        lo, hi = (mid, hi) if at(mid)[0] < tu_target_pct / 100 else (lo, mid)
    tu0 = 0.5 * (lo + hi)
    tb, k0, w0, f = at(tu0)
    return dict(Tu_inlet_pct=100 * tu0, Tu_rotor_pct=100 * tb, k=k0, omega=w0, nut=k0 / w0,
                vr_inlet=k0 / w0 / NU, vr_rotor=(k0 * f ** (-BETA_STAR / BETA)) / (w0 / f) / NU,
                length_scale_m=lt, decay_distance_m=L, ReThetat=rethetat_from_tu(100 * tu0),
                decayControl=False, kInf=0.0, omegaInf=0.0)


# --------------------------------------------------------------------------- parameters
def case_parameters(c, mesh_info):
    pose = mesh_info["pose_full"]
    R = pose["R_m"]
    s = pose["sense"]
    U = c["U"]
    D = 2 * pose["r_max_m"]
    dom = mesh_info["domain"]
    turb = inlet_turbulence(U, c["tu"], c["lt"], -dom["x_in"] - mesh_info["r_ami_m"], c["decay"])
    rotating = c.get("lam") is not None
    P = dict(caseName=c.get("name") or case_name(c), mode="rotating" if rotating else "static", hypothesis=c["hyp"],
             Uinf=U, rhoInf=RHO, nu=NU, dz=DZ, R=R, D=D, rMax=pose["r_max_m"], sense=s,
             turbulenceModel=MODELS[c["model"]], wall=c["wall"], nOuterCorrectors=c["nouter"], maxCo=c["maxco"],
             nProcs=c["np"], wallDistInterval=c["wdist"],
             TuRotorPercent=turb["Tu_rotor_pct"], TuInletPercent=turb["Tu_inlet_pct"], kInlet=turb["k"],
             omegaInlet=turb["omega"], nutInlet=turb["nut"], ReThetatInlet=turb["ReThetat"],
             # free-stream decay (constant/turbulenceProperties: decayControl, kInf, omegaInf)
             freestreamDecay=c["decay"], freestreamDecayControl="yes" if turb["decayControl"] else "no",
             kAmbient=turb["kInf"], omegaAmbient=turb["omegaInf"], decayDistance=turb["decay_distance_m"],
             turbulenceLengthScale=c["lt"], viscosityRatioInlet=turb["vr_inlet"],
             viscosityRatioRotor=turb["vr_rotor"], ReChordTip=U * 0.04461 / NU, qRef=0.5 * RHO * U ** 2,
             Aref=2 * R)
    if rotating:
        lam = c["lam"]
        Om = lam * U / R
        T = 2 * math.pi / Om
        P.update(lam=lam, Omega=Om, omegaZ=s * Om, Trev=T, rpm=Om * 60 / (2 * math.pi), nRev=c["nrev"], nAvgRev=c["navg"],
                 endTime=c["nrev"] * T, averageStart=(c["nrev"] - c["navg"]) * T, writeInterval=T / 2,
                 sampleInterval=T / 720, amiInterval=T / 72, yplusInterval=T / 8,
                 deltaT0=min(1e-6, T / 1e5), maxDeltaT=T / 720, thetaDeg=0.0)
    else:
        tc = D / U
        P.update(thetaDeg=c["theta"], convTime=tc, nConv=c["nconv"], nAvgConv=c["navgconv"],
                 endTime=c["nconv"] * tc, averageStart=(c["nconv"] - c["navgconv"]) * tc,
                 writeInterval=c["nconv"] * tc / 10, sampleInterval=tc / 50, amiInterval=tc,
                 yplusInterval=tc, deltaT0=1e-6, maxDeltaT=tc / 50, Omega=0.0, omegaZ=0.0)
    P["probeLocations"] = [(x * D, y * D, 0.5 * DZ) for x, y in PROBES_D]
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
    lines = ["/*--- written by cfd/rotor2d/run_case.py; edit run_case.py, not this file ---*/",
             "FoamFile\n{\n    version     2.0;\n    format      ascii;\n    class       dictionary;\n"
             "    object      caseParameters;\n}\n"]
    for k, v in P.items():
        lines.append(f"{k:<24}{_fmt(v)};")
    Path(path).write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- fields
def _field(cls, obj, dims, internal, bcs):
    out = ["/*--- written by cfd/rotor2d/run_case.py ---*/",
           f"FoamFile\n{{\n    version     2.0;\n    format      ascii;\n    class       {cls};\n    object      {obj};\n}}\n",
           f"dimensions      {dims};\n", f"internalField   {internal};\n", "boundaryField\n{"]
    for name, body in bcs.items():
        out.append(f"    {name}\n    {{\n" + "".join(f"        {ln}\n" for ln in body) + "    }")
    out.append("}\n")
    return "\n".join(out)


def write_fields(case, c, P):
    U = P["Uinf"]
    Uv = f"uniform ({U:.10g} 0 0)"
    k, w, nut = P["kInlet"], P["omegaInlet"], P["nutInlet"]
    walls = bool(c.get("walls"))
    wf = c["wall"] == "wf"
    sb = c["side_bc"]
    ami = {"AMI1": ["type            cyclicAMI;"], "AMI2": ["type            cyclicAMI;"]}
    empty = {"frontAndBack": ["type            empty;"]}
    blades = '"blade.*"'

    def side(open_bc, slip_bc, noslip_bc):
        if not walls:
            return {"sides": open_bc}
        return {"sides": slip_bc if sb == "slip" else noslip_bc}

    f = {}
    f["U"] = ("volVectorField", "[0 1 -1 0 0 0 0]", Uv, {
        "inlet": ["type            fixedValue;", f"value           {Uv};"],
        "outlet": ["type            inletOutlet;", "inletValue      uniform (0 0 0);", f"value           {Uv};"],
        **side(["type            freestreamVelocity;", f"freestreamValue {Uv};", f"value           {Uv};"],
               ["type            slip;"], ["type            noSlip;"]),
        blades: ["type            movingWallVelocity;", "value           uniform (0 0 0);"], **ami, **empty})
    f["p"] = ("volScalarField", "[0 2 -2 0 0 0 0]", "uniform 0", {
        "inlet": ["type            zeroGradient;"],
        "outlet": ["type            fixedValue;", "value           uniform 0;"],
        **side(["type            freestreamPressure;", "freestreamValue uniform 0;", "value           uniform 0;"],
               ["type            zeroGradient;"], ["type            zeroGradient;"]),
        blades: ["type            zeroGradient;"], **ami, **empty})

    def turb(name, val, wall_bc, dims):
        io = ["type            inletOutlet;", f"inletValue      uniform {val:.10g};", f"value           uniform {val:.10g};"]
        return ("volScalarField", dims, f"uniform {val:.10g}", {
            "inlet": ["type            fixedValue;", f"value           uniform {val:.10g};"],
            "outlet": io, **side(io, ["type            zeroGradient;"], wall_bc), blades: wall_bc, **ami, **empty})

    kw = ["type            kqRWallFunction;", f"value           uniform {k:.10g};"] if wf else \
        ["type            fixedValue;", "value           uniform 1e-12;"]
    f["k"] = turb("k", k, kw, "[0 2 -2 0 0 0 0]")
    f["omega"] = turb("omega", w, ["type            omegaWallFunction;", f"value           uniform {w:.10g};"],
                      "[0 0 -1 0 0 0 0]")
    nw = ["type            nutUSpaldingWallFunction;", "value           uniform 0;"] if wf else \
        ["type            nutLowReWallFunction;", "value           uniform 0;"]
    calc = ["type            calculated;", f"value           uniform {nut:.10g};"]
    f["nut"] = ("volScalarField", "[0 2 -1 0 0 0 0]", f"uniform {nut:.10g}", {
        "inlet": calc, "outlet": calc, **side(calc, calc, nw), blades: nw, **ami, **empty})
    if c["model"] == "LM":
        zg = ["type            zeroGradient;"]
        f["gammaInt"] = turb("gammaInt", 1.0, zg, "[0 0 0 0 0 0 0]")
        f["ReThetat"] = turb("ReThetat", P["ReThetatInlet"], zg, "[0 0 0 0 0 0 0]")
    d = Path(case) / "0"
    d.mkdir(exist_ok=True)
    for name, (cls, dims, internal, bcs) in f.items():
        (d / name).write_text(_field(cls, name, dims, internal, bcs))


# --------------------------------------------------------------------------- OpenFOAM calls
_CHILD = []


def foam(case, cmd, log, append=False, caffeinate=False, timeout=None):
    redir = ">>" if append else ">"
    full = ["openfoam2606", "-c", f"cd {case} && {cmd} {redir} {log} 2>&1"]
    if caffeinate:
        full = ["caffeinate", "-i"] + full
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
def ensure_mesh(c, quiet=False):
    d = MESHES / mesh_key(c)
    if (d / "MESH_OK").exists():
        return d
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    (d / "system").mkdir()
    (d / "system" / "controlDict").write_text(
        "FoamFile\n{\n    version     2.0;\n    format      ascii;\n    class       dictionary;\n"
        "    object      controlDict;\n}\napplication     checkMesh;\nstartFrom       startTime;\nstartTime       0;\n"
        "stopAt          endTime;\nendTime         1;\ndeltaT          1;\nwriteControl    timeStep;\n"
        "writeInterval   1;\nwriteFormat     ascii;\nwritePrecision  12;\ntimeFormat      general;\n")
    for f in ("fvSchemes", "fvSolution"):
        shutil.copy(TEMPLATE / "system" / f, d / "system" / f)
    write_case_parameters(d / "system" / "caseParameters", dict(nProcs=c["np"], wallDistInterval=1, nOuterCorrectors=2))
    cmd = [str(VENV_PY), str(MAKE_MESH), "--hyp", c["hyp"], "--level", c["level"], "--wall", c["wall"],
           "--U", f"{c['U']:g}", "--theta", f"{(c.get('theta') or 0.0):g}", "--sense", c["sense"],
           "--out", str(d), "--plot", str(d / "mesh.png")]
    if c.get("beta") is not None:
        cmd += ["--beta", f"{c['beta']:g}"]
    if c.get("yplus") is not None:
        cmd += ["--yplus", f"{c['yplus']:g}"]
    if c.get("walls"):
        cmd += ["--walls", ",".join(_g(v) for v in c["walls"])]
    if not quiet:
        print(f"[mesh] {d.name}", flush=True)
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    (d / "log.make_mesh").write_text(r.stdout + r.stderr)
    if r.returncode:
        raise RuntimeError(f"make_mesh failed, see {d / 'log.make_mesh'}")
    if foam(d, "renumberMesh -overwrite", "log.renumberMesh"):
        raise RuntimeError(f"renumberMesh failed, see {d / 'log.renumberMesh'}")
    foam(d, "checkMesh", "log.checkMesh")
    log = (d / "log.checkMesh").read_text()
    logs = HERE / "mesh" / "logs"
    logs.mkdir(exist_ok=True)
    shutil.copy(d / "log.checkMesh", logs / f"checkMesh_{d.name}.log")
    info = json.loads((d / "mesh_info.json").read_text())
    info["checkMesh_ok"] = "Mesh OK." in log
    info["mesh_seconds_total"] = round(time.time() - t0, 1)
    (d / "mesh_info.json").write_text(json.dumps(info, indent=1))
    slim = {k: v for k, v in info.items() if k != "pose_full"}
    (logs / f"mesh_info_{d.name}.json").write_text(json.dumps(slim, indent=1))
    if "Mesh OK." not in log:
        raise RuntimeError(f"checkMesh did not report 'Mesh OK', see {d / 'log.checkMesh'}")
    (d / "MESH_OK").write_text(time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")
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


def latest_time(case, np_):
    t = time_dirs(Path(case) / "processor0") if np_ > 1 else time_dirs(case)
    return t[-1][0] if t else None


def set_stop_at(case, value):
    cd = Path(case) / "system" / "controlDict"
    s = cd.read_text()
    cd.write_text(re.sub(r"^stopAt\s+\w+;", f"stopAt          {value};", s, flags=re.M))


def create_case(case, c, md, P):
    if case.exists():
        shutil.rmtree(case)
    case.mkdir(parents=True)
    shutil.copytree(TEMPLATE / "system", case / "system")
    (case / "constant").mkdir()
    for f in ("transportProperties", "turbulenceProperties"):
        shutil.copy(TEMPLATE / "constant" / f, case / "constant" / f)
    if P["mode"] == "rotating":
        shutil.copy(TEMPLATE / "constant" / "dynamicMeshDict.rotating", case / "constant" / "dynamicMeshDict")
    shutil.copytree(md / "constant" / "polyMesh", case / "constant" / "polyMesh")
    for f in ("mesh_info.json", "log.checkMesh", "mesh.png"):
        if (md / f).exists():
            shutil.copy(md / f, case / f)
    write_case_parameters(case / "system" / "caseParameters", P)
    write_fields(case, c, P)
    (case / "case.json").write_text(json.dumps(dict(P, inputs=c, mesh=md.name), indent=1))
    (case / "case.foam").touch()


def normalise(c):
    out = dict(DEFAULTS)
    out.update({k: v for k, v in c.items() if v is not None or k in ("lam", "theta")})
    if (out.get("lam") is None) == (out.get("theta") is None):
        raise ValueError("give exactly one of lam (rotating) or theta (static)")
    if out["model"] == "LM" and out["wall"] != "lowRe":
        raise ValueError("kOmegaSSTLM needs the low-Re mesh (wall=lowRe): its transport equations assume y+ ~ 1")
    if out.get("walls") and isinstance(out["walls"], str):
        out["walls"] = tuple(float(v) for v in out["walls"].split(","))
    if out["decay"] not in DECAY_MODES:
        raise ValueError(f"decay must be one of {', '.join(DECAY_MODES)}, not {out['decay']!r}")
    if out["lt"] is None:
        out["lt"] = lt_default(out["decay"])
    out["lt"] = float(out["lt"])
    if out["lt"] <= 0:
        raise ValueError("lt must be positive (m)")
    return out


def run(c, setup_only=False, force=False, wall_limit=None, keep_processors=False, quiet=False):
    """c: dict (see DEFAULTS; hyp, U and lam or theta required).
    Returns 'complete', 'skipped', 'setup', 'stopped', 'timeout', 'busy' or 'failed'."""
    say = (lambda *a: None) if quiet else (lambda *a: print(*a, flush=True))
    c = normalise(c)
    name = c.get("name") or case_name(c)
    case = RUNS / name
    res = case / "results.json"
    np_ = int(c["np"])
    if res.exists() and not force and json.loads(res.read_text()).get("complete"):
        say(f"[skip] {name}: complete")
        return "skipped"
    # A RUNNING marker with a log still being written means a solver from an earlier launch
    # is alive there (e.g. its queue was killed with SIGKILL); a second solver in the same
    # directory would corrupt both. Refuse; the queue stops on 'busy'.
    lg = case / "log.pimpleFoam"
    if (case / "RUNNING").exists() and lg.exists() and time.time() - lg.stat().st_mtime < 120:
        say(f"[busy] {name}: RUNNING marker and log.pimpleFoam written {time.time() - lg.stat().st_mtime:.0f} s ago; "
            f"a solver may still be running in {case}. Stop it (or wait 2 min if it has died) and re-launch.")
        return "busy"
    t_last = latest_time(case, np_) if case.exists() else None
    resume = (not force) and t_last is not None and t_last > 0 and (case / "case.json").exists()
    if resume:
        old = json.loads((case / "case.json").read_text())
        if old["nProcs"] != np_:
            raise RuntimeError(f"{name}: decomposed for {old['nProcs']} ranks; run with --np {old['nProcs']} or --force")
        # Never resume a case set up with other physics under the same name (e.g. a free stream
        # without decay control, set up before 8 Oct): compare with what this command would write.
        # kAmbient/omegaAmbient are absent in cases set up before decay control (= no decay control).
        # Omega and the mesh key (hypothesis, level, wall, U, theta, sense, beta, y+, walls) matter
        # with --name, where the folder name no longer carries them.
        if (case / "mesh_info.json").exists():
            new = case_parameters(c, json.loads((case / "mesh_info.json").read_text()))
            diff = [k for k in ("Uinf", "kInlet", "omegaInlet", "kAmbient", "omegaAmbient", "endTime", "Omega")
                    if abs(float(old.get(k, 0.0)) - float(new[k])) > 1e-9 * max(1.0, abs(float(new[k])))]
            diff += [k for k in ("turbulenceModel", "mode") if old.get(k) != new[k]]
            if old.get("mesh") and old["mesh"] != mesh_key(c):
                diff.append(f"mesh ({old['mesh']}, command: {mesh_key(c)})")
            if diff:
                raise RuntimeError(f"{name}: existing case has different {', '.join(diff)}; use --force to restart it")
        P = {k: v for k, v in old.items() if k not in ("inputs", "mesh")}
        say(f"[resume] {name} from t = {t_last:.6g} s")
        set_stop_at(case, "endTime")
    else:
        md = ensure_mesh(c, quiet)
        P = case_parameters(c, json.loads((md / "mesh_info.json").read_text()))
        say(f"[setup] {name}")
        create_case(case, c, md, P)
        if setup_only:
            return "setup"
        if np_ > 1 and foam(case, "decomposePar -force", "log.decomposePar"):
            say(f"[fail] {name}: decomposePar, see {case / 'log.decomposePar'}")
            return "failed"
    if setup_only:
        return "setup"
    (case / "RUNNING").write_text(f"{os.getpid()}\n")
    t0 = time.time()
    solver = f"mpirun -np {np_} pimpleFoam -parallel" if np_ > 1 else "pimpleFoam"
    say(f"[run] {name}: {solver}, end {P['endTime']:.6g} s, log {case / 'log.pimpleFoam'}")
    # cyclicAMIPolyPatch prints 6 lines per step on a moving mesh (unconditional Info);
    # keep the two sum(weights) lines per step, drop the rest.
    cmd = (f"set -o pipefail; {solver} 2>&1 | grep --line-buffered -v -E "
           f"'^AMI: (Creating AMI|Patch (source|target) faces|distributed)'")
    rc = foam(case, cmd, "log.pimpleFoam", append=resume, caffeinate=True, timeout=wall_limit)
    t1 = time.time()
    (case / "RUNNING").unlink(missing_ok=True)
    tim = case / "timing.json"
    sessions = json.loads(tim.read_text()) if tim.exists() else []
    sessions.append(dict(start=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0)), wall_s=round(t1 - t0, 1),
                         t_start=t_last or 0.0, t_end=latest_time(case, np_), rc=str(rc), np=np_))
    tim.write_text(json.dumps(sessions, indent=1))
    t_end = latest_time(case, np_) or 0.0
    if rc == "timeout":
        say(f"[timeout] {name}: stopped after {wall_limit} s; last write t = {t_end:.6g} s")
        return "timeout"
    if t_end < P["endTime"] * (1 - 1e-6):
        if re.search(r"^stopAt\s+writeNow;", (case / "system" / "controlDict").read_text(), re.M):
            say(f"[paused] {name} at t = {t_end:.6g} s; re-run to resume")
            return "stopped"
        say(f"[fail] {name}: solver exited (rc {rc}) at t = {t_end:.6g} s, see {case / 'log.pimpleFoam'}")
        return "failed"
    if np_ > 1 and foam(case, "reconstructPar -latestTime", "log.reconstructPar"):
        say(f"[fail] {name}: reconstructPar")
        return "failed"
    import rotor_summary
    summ = rotor_summary.summarize(case)
    summ["complete"] = True
    res.write_text(json.dumps(summ, indent=1))
    if np_ > 1 and not keep_processors:
        for q in case.glob("processor*"):
            shutil.rmtree(q)
    if P["mode"] == "rotating":
        say(f"[done] {name}: C_P {summ['CP_mean']:.4f}, C_Q {summ['CQ_mean']:.4f} (last {summ['n_avg_rev']} rev), "
            f"wall {summ['wall_time_s'] / 3600:.2f} h")
    else:
        say(f"[done] {name}: C_Q {summ['CQ_mean']:.4f} +- {summ['CQ_std']:.4f}, wall {summ['wall_time_s'] / 3600:.2f} h")
    return "complete"


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hyp", required=True, choices=["A", "B", "measured"], help="assembly hypothesis (rotor_geometry.py)")
    ap.add_argument("--U", type=float, required=True, help="free-stream speed, m/s")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--lam", type=float, help="tip-speed ratio on R (rotating case)")
    g.add_argument("--theta", type=float, help="frozen azimuth of blade 1, deg (static case)")
    ap.add_argument("--model", choices=MODELS, default=DEFAULTS["model"], help="SST = kOmegaSST, LM = kOmegaSSTLM (lowRe only)")
    ap.add_argument("--level", choices=LEVELS, default=DEFAULTS["level"])
    ap.add_argument("--wall", choices=WALLS, default=DEFAULTS["wall"], help="wf = wall functions (y+ 30-60), lowRe = y+ ~ 1")
    ap.add_argument("--np", type=int, default=DEFAULTS["np"], help="MPI ranks (production 4; smoke tests at most 2)")
    ap.add_argument("--nrev", type=int, default=DEFAULTS["nrev"], help="revolutions (rotating)")
    ap.add_argument("--navg", type=int, default=DEFAULTS["navg"], help="averaged revolutions at the end (rotating)")
    ap.add_argument("--nconv", type=int, default=DEFAULTS["nconv"], help="run length in D/U (static)")
    ap.add_argument("--navgconv", type=int, default=DEFAULTS["navgconv"], help="averaging window in D/U (static)")
    ap.add_argument("--maxco", type=float, default=DEFAULTS["maxco"])
    ap.add_argument("--nouter", type=int, default=DEFAULTS["nouter"])
    ap.add_argument("--tu", type=float, default=DEFAULTS["tu"], help="Tu reaching the rotor, %%")
    ap.add_argument("--decay", choices=DECAY_MODES, default=DECAY_DEFAULT,
                    help="free-stream turbulence: 'control' = kOmegaSST decayControl, inlet at the target Tu "
                         "(default); 'precompensate' = the 7 Oct smoke-test set-up (README)")
    ap.add_argument("--lt", type=float, default=None,
                    help="free-stream turbulence length scale, m (default %g with --decay control, %g with "
                         "precompensate)" % (LT_DEFAULTS["control"], LT_DEFAULTS["precompensate"]))
    ap.add_argument("--sense", default=DEFAULTS["sense"], choices=["auto", "CCW", "CW"],
                    help="rotation sense in the model frame (auto = drag rule)")
    ap.add_argument("--beta", type=float, help="chord-to-radius angle override, deg")
    ap.add_argument("--yplus", type=float, help="first-cell y+ target override")
    ap.add_argument("--walls", help="tunnel side walls 'y_lo,y_hi' in m (model frame); default open domain")
    ap.add_argument("--side-bc", choices=["slip", "noSlip"], default=DEFAULTS["side_bc"], help="tunnel-wall BC with --walls")
    ap.add_argument("--wdist", type=int, default=DEFAULTS["wdist"], help="wall-distance update interval (steps)")
    ap.add_argument("--setup-only", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--wall-limit", type=float, help="kill the solver after this many seconds (smoke tests)")
    ap.add_argument("--keep-processors", action="store_true")
    ap.add_argument("--name", help="case folder name instead of the automatic one (tests: start it with '_' "
                                   "so the queue's CSVs leave it out)")
    return ap


def args_to_case(a):
    return dict(hyp=a.hyp, U=a.U, lam=a.lam, theta=a.theta, model=a.model, level=a.level, wall=a.wall, np=a.np,
                nrev=a.nrev, navg=a.navg, nconv=a.nconv, navgconv=a.navgconv, maxco=a.maxco, nouter=a.nouter,
                tu=a.tu, decay=a.decay, lt=a.lt, sense=a.sense, beta=a.beta, yplus=a.yplus, walls=a.walls,
                side_bc=a.side_bc, wdist=a.wdist, name=a.name)


def main():
    a = build_parser().parse_args()
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, _on_signal)
    st = run(args_to_case(a), a.setup_only, a.force, a.wall_limit, a.keep_processors)
    sys.exit(0 if st in ("complete", "skipped", "setup", "timeout") else 1)


if __name__ == "__main__":
    main()
