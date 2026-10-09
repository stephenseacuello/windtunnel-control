"""Shared settings and helpers for cfd/hpc/ (Unity HPC). See cfd/hpc/README.md.

Everything that knows where things live on Unity, how to reach it, how each stage names its
cases and meshes, and how long a case takes, is here, so submit.py, status.py, premesh.py,
pull_results.py and migrate.py agree.
"""
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

HPC = Path(__file__).resolve().parent              # cfd/hpc
CFD = HPC.parent                                    # cfd
REPO = CFD.parent

# ------------------------------------------------------------------ Unity layout
SSH_HOST = os.environ.get("CFD_HPC_HOST", "unity")
ROOT = os.environ.get("CFD_HPC_ROOT", "/work/pi_sodhi_uri_edu/seacuello/windtunnel-cfd")
RREPO = f"{ROOT}/repo"                 # mirror of this repository's cfd/ tree (sync_up.sh)
RCFD = f"{RREPO}/cfd"
RJOBS = f"{ROOT}/jobs"                 # generated sbatch scripts, submission log
IMAGE = f"{ROOT}/containers/openfoam-run_2606.sif"
RPY = f"{ROOT}/venv/bin/python"        # Python 3.12 + numpy/scipy on Unity (run_case.py, summaries)
ACCOUNT = "pi_sodhi_uri_edu"

STAGING = HPC / "mesh_cache"           # meshes made by premesh.py (git-ignored), <stage>/<key>/
JOBS = HPC / "jobs"                    # local copies of the generated sbatch scripts (git-ignored)

STAGES = {
    # default queue files: everything that is (or will be) queued for production
    "section2d": dict(queue_mod="hpc_q_section2d", queues=["queues/priority1.txt", "queues/priority2.txt",
                                                            "queues/priority3.txt", "queues/priority4.txt"]),
    "rotor2d": dict(queue_mod="hpc_q_rotor2d", queues=["queues/priority0.txt", "queues/priorityA.txt",
                                                        "queues/priorityC.txt"]),
    "stage2": dict(queue_mod="hpc_q_stage2", queues=["queues/S2a_ks_U23.txt", "queues/S2b_speeds.txt",
                                                      "queues/S2c_texture.txt"]),
}

_LOADED = {}


def on_unity():
    """True when this process runs on Unity itself (then 'remote' commands run here)."""
    return Path(ROOT).is_dir() and not Path("/Applications").is_dir()


def load_queue(stage):
    """The stage's queue.py as a module (it loads that stage's run_case.py)."""
    if stage not in STAGES:
        raise SystemExit(f"unknown stage {stage!r}; one of {', '.join(STAGES)}")
    if stage not in _LOADED:
        path = CFD / stage / "queue.py"
        spec = importlib.util.spec_from_file_location(STAGES[stage]["queue_mod"], path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        _LOADED[stage] = mod
    return _LOADED[stage]


def queue_path(stage, f):
    p = Path(f)
    if p.is_absolute() or p.exists():
        return p.resolve()
    return (CFD / stage / f).resolve()


def cases(stage, files=None):
    """[(name, case dict, queue file)] in queue order, each case once."""
    q = load_queue(stage)
    files = files or STAGES[stage]["queues"]
    out, seen = [], set()
    for f in files:
        p = queue_path(stage, f)
        for c in q.parse_queue(p):
            n = q.name_of(c)
            if n not in seen:
                seen.add(n)
                out.append((n, c, p))
    return out


def norm(stage, c):
    """The case dict as run_case.py sees it (defaults filled in)."""
    rc = load_queue(stage).run_case
    if stage == "section2d":
        d = dict(c)
        d.setdefault("nconv", rc.NCONV_DEFAULT)
        d.setdefault("navg", rc.NAVG_DEFAULT)
        d.setdefault("maxco", rc.MAXCO_DEFAULT)
        d.setdefault("nouter", rc.NOUTER_DEFAULT)
        d.setdefault("decay", rc.DECAY_DEFAULT)
        return d
    return rc.normalise(dict(c))


def mesh_key(stage, c):
    """Name of the case's mesh folder in <stage>/runs/_mesh/."""
    rc = load_queue(stage).run_case
    if stage == "section2d":
        return rc.mesh_dir(c["level"], c["alpha"]).name
    n = rc.normalise(dict(c))
    if stage == "rotor2d":
        return rc.mesh_key(n)
    return rc.mesh_dir(n["wall"], n["alpha"], n["U"], n["t"], n["seed"], n["nseg"]).name


def local_mesh(stage, key):
    """(path, where) of a finished local mesh: the stage's runs/_mesh cache (read only here)
    or the staging cache of premesh.py; (None, None) if neither has it."""
    for where, base in (("runs", CFD / stage / "runs" / "_mesh"), ("staging", STAGING / stage)):
        d = base / key
        if (d / "MESH_OK").is_file() and (d / "constant" / "polyMesh").is_dir():
            return d, where
    return None, None


# ------------------------------------------------------------------ remote execution
def remote(script, input_text=None, check=True, timeout=600):
    """Run a bash script on Unity (through ssh, or here when on Unity). Returns stdout."""
    if on_unity():
        argv = ["bash", "-l", "-s"]
    else:
        argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=30", "-o", "ServerAliveInterval=30",
                SSH_HOST, "bash", "-l", "-s"]
    full = script if input_text is None else script.replace("@@STDIN@@", shlex.quote(input_text))
    r = subprocess.run(argv, input=full, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f"remote command failed (rc {r.returncode}):\n{r.stderr[-3000:]}\n{r.stdout[-2000:]}")
    return r.stdout


def remote_json(script, payload=None, timeout=600):
    """Run a remote script that prints one line '@@JSON@@<json>'; return the parsed object."""
    out = remote(script, None if payload is None else json.dumps(payload), timeout=timeout)
    for ln in out.splitlines():
        if ln.startswith("@@JSON@@"):
            return json.loads(ln[8:])
    raise RuntimeError(f"no JSON in remote output:\n{out[-3000:]}")


def remote_status(stage_names, squeue=True):
    """{'cases': {stage: {name: info}}, 'jobs': [...]} from cfd/hpc/remote_status.py on Unity.
    stage_names: {stage: {name: mesh_key or None}}; an empty dict per stage lists every case folder."""
    script = (f"cd {shlex.quote(RCFD)} 2>/dev/null || {{ echo '@@JSON@@{{\"missing_repo\": true}}'; exit 0; }}\n"
              f"echo @@STDIN@@ | python3 hpc/remote_status.py {'--squeue' if squeue else ''}\n")
    return remote_json(script, dict(root=RCFD, stages=stage_names))


def squeue_jobs():
    return remote_status({}, squeue=True).get("jobs", [])


# ------------------------------------------------------------------ cost model
# Measured inputs (cfd/hpc/README.md, "Speed"):
#   Mac (results.json of finished cases): steps per case; Unity: seconds per step.
# Steps per convective time: section medium 769 (a000 SST medium, 115,280 steps / 150 c/U),
# coarse 411-559 (61,590-83,814 / 150); fine scaled by the corner wall spacing 45/32 (estimate).
# Stage 2 wf 191 (28,702 / 150). Rotor static medium 313-478 per D/U (12,506-19,106 / 40).
STEPS_PER_CONV = {"coarse": 560, "medium": 800, "fine": 1130}
STEPS_PER_CONV_STAGE2 = {"wf": 200, "tex": 1750}       # tex: README section 6 upper estimate (139k / 80)
STEPS_PER_DU_ROTOR_STATIC = 480
STEPS_PER_REV_ROTOR_015 = 10000                         # smoke test at lambda 0.15 (README); scales with 0.15/lambda

# Unity seconds per step at 16 ranks for each kind (developed flow); filled from the test job.
# Each entry: {ntasks: s_per_step}. Missing ntasks are scaled with the nearest entry (ideal scaling).
S_PER_STEP = {
    "section_medium": {8: 0.135, 16: 0.085},
    "section_coarse": {8: 0.075, 16: 0.055},
    "section_fine": {16: 0.17, 32: 0.10},
    "stage2_wf": {8: 0.12, 16: 0.075},
    "stage2_tex": {16: 0.20, 32: 0.12},
    "rotor_static": {8: 0.09, 16: 0.07},
    "rotor_rot": {8: 0.12, 16: 0.09},
}
LM_FACTOR = 1.15            # kOmegaSSTLM per-step cost against kOmegaSST (README: 1.05-1.2)
# 8 ranks for the medium meshes: about 25% fewer core-hours per case than 16 (S_PER_STEP), and
# more cases run at once under the lab's 768-core cap on uri-cpu
DEFAULT_NTASKS = {"section_coarse": 8, "section_medium": 8, "section_fine": 16, "stage2_wf": 8,
                  "stage2_tex": 16, "rotor_static": 8, "rotor_rot": 8}


def kind_of(stage, c):
    n = norm(stage, c)
    if stage == "section2d":
        return f"section_{n['level']}"
    if stage == "stage2":
        return f"stage2_{n['wall']}"
    return "rotor_rot" if n.get("lam") is not None else "rotor_static"


def est_steps(stage, c):
    n = norm(stage, c)
    if stage == "section2d":
        return STEPS_PER_CONV[n["level"]] * float(n["nconv"])
    if stage == "stage2":
        return STEPS_PER_CONV_STAGE2[n["wall"]] * float(n["nconv"])
    if n.get("lam") is None:
        return STEPS_PER_DU_ROTOR_STATIC * float(n["nconv"])
    f = 1.3 if n["U"] > 30 else 1.0          # thinner first cell at 38 m/s (h0 0.55 mm against 0.87 mm)
    return STEPS_PER_REV_ROTOR_015 * float(n["nrev"]) * 0.15 / float(n["lam"]) * f


def s_per_step(kind, ntasks, model="SST"):
    tab = S_PER_STEP[kind]
    if ntasks in tab:
        s = tab[ntasks]
    else:
        k = min(tab, key=lambda x: abs(x - ntasks))
        s = tab[k] * k / ntasks if ntasks > k else tab[k] * k / ntasks
    return s * (LM_FACTOR if model == "LM" else 1.0)


def est_seconds(stage, c, ntasks, frac_left=1.0):
    n = norm(stage, c)
    return est_steps(stage, c) * s_per_step(kind_of(stage, c), ntasks, n.get("model", "SST")) * frac_left


def fmt_h(s):
    if s is None:
        return "-"
    return f"{s / 60:.0f} min" if s < 5400 else f"{s / 3600:.1f} h" if s < 72 * 3600 else f"{s / 86400:.1f} d"


def slurm_time(seconds):
    """Slurm time string D-HH:MM:SS."""
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{d}-{h:02d}:{m:02d}:{s:02d}" if d else f"{h:02d}:{m:02d}:{s:02d}"


def parse_slurm_time(t):
    """'1-02:03:04', '02:03:04', '03:04', 'UNLIMITED' -> seconds (None if unknown)."""
    if not t or t in ("UNLIMITED", "INVALID", "N/A"):
        return None
    d = 0
    if "-" in t:
        dd, t = t.split("-", 1)
        d = int(dd)
    parts = [int(x) for x in t.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts[-3:]
    return d * 86400 + h * 3600 + m * 60 + s


def case_safe(name):
    if not re.fullmatch(r"[A-Za-z0-9_.+-]+", name):
        raise ValueError(f"unsafe case name {name!r}")
    return name
