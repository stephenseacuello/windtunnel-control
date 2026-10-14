#!/usr/bin/env python3
"""Prepare a hysteresis restart of a finished Stage 1 section case, with its Slurm script for Unity.

A hysteresis restart continues a finished case from its final fields at a different time-step limit
(maxCo). It tests whether the alpha-0 flow state that the case settled into persists or switches
(cfd/analysis/2026-10-13/RESULTS.md, section 8.4 item 6 and the addendum "force histories").

    python3 cfd/hpc/hysteresis_restart.py SRC NAME --maxco M [--nconv 60] [--ntasks 8] [--dry-run]

    # (a) the Mac's maxCo-5 high-drag case, continued at maxCo 2.5 (prepare on the Mac, then upload)
    python3 cfd/hpc/hysteresis_restart.py cfd/section2d/runs/a000.0_U23.0_SST_medium_Tu1.0 \
        _hyst_Co5to2p5_a000 --maxco 2.5
    # (b) the Unity maxCo-2.5 low-drag case, continued at maxCo 5 (prepare on Unity, in repo/)
    python3 cfd/hpc/hysteresis_restart.py cfd/section2d/runs/a000.0_U23.0_SST_medium_Tu1.0_Co2.5n2 \
        _hyst_Co2p5to5_a000 --maxco 5

The source folder is only read. The restart folder is <SRC's parent>/NAME (--dst-root to change
the parent), and NAME must not exist yet. Steps:
  1. copy 0/, constant/, system/, case.json, mesh_info.json and the source's final time folder,
     with uniform/ (time index, deltaT, function-object state), so the solver starts from the final
     fields (controlDict: startFrom latestTime);
  2. system/caseParameters: maxCo, endTime = t_final + nconv c/U, nProcs = --ntasks,
     caseName = NAME, nConv = the source's nConv + nconv (total c/U from t = 0);
  3. system/controlDict: stopAt endTime; fieldAverage1 restartOnRestart true, so the mean fields
     (UMean, pMean, ...) average the restart only. The force, y+, probe and wall-shear function
     objects are unchanged; their histories start in postProcessing/<fo>/<t_final>/;
  4. check that the end time is a write time (cfd/post/foam_launch.align_final_write);
  5. case.json: the same values, plus a "restart" record (source, t_final, maxCo before and after);
  6. NAME/run_hysteresis.sbatch for Unity: --ntasks ranks on one node, partition uri-cpu,cpu,
     account pi_sodhi_uri_edu, the container of cfd/hpc/job_env.sh, and
       decomposePar -force -latestTime && mpirun -np <ntasks> pimpleFoam -parallel
       && reconstructPar -latestTime
     (logs: log.decomposePar, log.pimpleFoam, log.reconstructPar; one line in hpc_jobs.jsonl;
     Slurm log in section2d/runs/_slurm/). The job refuses to start when the case has a RUNNING
     marker or processor*/ folders, i.e. when it has run before: decomposePar -force would delete
     that progress.

Time limit = --time-factor (3) x estimate + 30 min, at least 2 h, as in submit.py. Estimate =
steps x s/step:
  steps   = nconv c/U / dt_new, dt_new = the source's mean dt over the last half of its steps
            (results.json dt_last_half_mean_s) x maxCo_new / maxCo_source. The step is
            Courant-limited, so dt scales with maxCo; a change of flow state changes dt as well
            (the high-drag state steps about 1.5 times shorter at the same maxCo), which the factor
            3 covers.
  s/step  = the source's measured s/step (results.json s_per_step), x source ranks / --ntasks when
            the two differ (ideal scaling, as hpc_common.s_per_step). A source run on the Mac
            (4 ranks, three queues sharing the machine) is slower per step than Unity, so its
            estimate is conservative. --s-per-step overrides it.
If the limit is reached, the force histories up to that time are still in postProcessing/.

No results.json is written. Analyse a restart from its force histories (postProcessing/forceCoeffs1/
<t_final>/coefficient.dat, joined to the source's) or with
    python3 cfd/post/section_summary.py <restart folder> --window <c/U>
pull_results.py skips folders whose names start with '_'; download a finished restart with
    rsync -az --exclude='/processor*/' unity:<RCFD>/section2d/runs/NAME/ cfd/section2d/runs/NAME/
Only Stage 1 section cases (cfd/section2d) have been tested. Standard library only (Unity login
node: python3).
"""
import argparse
import json
import math
import re
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent          # cfd/hpc
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "post"))
import foam_launch  # noqa: E402  cfd/post/foam_launch.py: align_final_write
import hpc_common as H  # noqa: E402  Unity paths, account, slurm_time

PARTITION = "uri-cpu,cpu"          # as submit.py: URI nodes first, else the general cpu partition
MEM_PER_TASK_G = 2                 # as submit.py
SBATCH = "run_hysteresis.sbatch"
COPY_DIRS = ("0", "constant", "system")
COPY_FILES = ("case.json", "mesh_info.json")
FIELDS = ("U", "p", "phi", "k", "omega", "nut")
FIELDS_LM = ("ReThetat", "gammaInt")


def time_dirs(path):
    """[(value, name)] of the numeric folders in path, sorted by value."""
    out = []
    for q in Path(path).iterdir():
        if q.is_dir():
            try:
                out.append((float(q.name), q.name))
            except ValueError:
                pass
    return sorted(out)


def set_entry(text, key, value, where):
    """Replace the value of a top-level 'key value;' line (exactly one such line)."""
    pat = re.compile(rf"^({re.escape(key)})(\s+)([^;\n]*);", re.M)
    if len(pat.findall(text)) != 1:
        raise SystemExit(f"{where}: expected exactly one '{key}' entry")
    return pat.sub(lambda m: f"{m.group(1)}{m.group(2)}{value};", text)


def source_state(src):
    """Read and check the source case; return what the restart needs."""
    P = json.loads((src / "case.json").read_text())
    for k in ("convTime", "maxCo", "nProcs", "nConv", "endTime", "writeInterval", "turbulenceModel"):
        if k not in P:
            raise SystemExit(f"{src}/case.json has no '{k}': not a section case")
    res_p = src / "results.json"
    R = json.loads(res_p.read_text()) if res_p.is_file() else {}
    if not R.get("complete"):
        raise SystemExit(f"{src}: results.json does not say complete; restart only finished cases")
    if any(q.is_dir() for q in src.glob("processor[0-9]*")):
        print(f"note: {src.name} has processor*/ folders; the reconstructed final time is used")
    times = [t for t in time_dirs(src) if t[0] > 0]
    if not times:
        raise SystemExit(f"{src}: no reconstructed time folder > 0")
    t_final, t_name = times[-1]
    if abs(t_final - float(P["endTime"])) > 1e-6 * float(P["endTime"]):
        raise SystemExit(f"{src}: latest time {t_name} is not the end time {P['endTime']:.10g}")
    need = FIELDS + (FIELDS_LM if P["turbulenceModel"] == "kOmegaSSTLM" else ())
    missing = [f for f in need if not (src / t_name / f).is_file()]
    if missing or not (src / t_name / "uniform" / "time").is_file():
        raise SystemExit(f"{src}/{t_name}: missing {missing or ['uniform/time']}")
    for d in COPY_DIRS:
        if not (src / d).is_dir():
            raise SystemExit(f"{src}: no {d}/")
    for f in COPY_FILES:
        if not (src / f).is_file():
            raise SystemExit(f"{src}: no {f}")
    cd = (src / "system" / "controlDict").read_text()
    if len(re.findall(r"^\s*restartOnRestart\s+\w+;", cd, re.M)) != 1:
        raise SystemExit(f"{src}/system/controlDict: expected one fieldAverage restartOnRestart entry")
    return P, R, t_final, t_name


def estimate(P, R, maxco, nconv, ntasks, s_per_step=None):
    """(steps, s/step, seconds, explanation) for the restart."""
    dt_src = R.get("dt_last_half_mean_s") or R.get("dt_mean_s")
    if not dt_src:
        raise SystemExit("source results.json has no dt_last_half_mean_s or dt_mean_s")
    dt_new = float(dt_src) * maxco / float(P["maxCo"])
    steps = nconv * float(P["convTime"]) / dt_new
    if s_per_step:
        sps, how = float(s_per_step), "--s-per-step"
    else:
        if not R.get("s_per_step"):
            raise SystemExit("source results.json has no s_per_step; give --s-per-step")
        sps = float(R["s_per_step"]) * int(P["nProcs"]) / ntasks
        how = (f"source measured {float(R['s_per_step']):.4g} s/step on {int(P['nProcs'])} ranks"
               + (f", x {int(P['nProcs'])}/{ntasks} (ideal scaling)" if int(P["nProcs"]) != ntasks else ""))
    return steps, sps, steps * sps, f"dt {float(dt_src):.4g} s x {maxco:g}/{float(P['maxCo']):g}; {how}"


def sbatch_text(name, unity_case, ntasks, limit_s, partition, header):
    rcfd = H.RCFD
    solve = (f"source $CFD_FOAM_BASHRC && cd {unity_case} && "
             f"decomposePar -force -latestTime > log.decomposePar 2>&1 && "
             f"mpirun -np {ntasks} pimpleFoam -parallel > log.pimpleFoam 2>&1 && "
             f"reconstructPar -latestTime > log.reconstructPar 2>&1")
    lines = [
        "#!/bin/bash",
        *[f"# {h}" for h in header],
        f"#SBATCH --job-name=cfd.section2d.{name}",
        f"#SBATCH --account={H.ACCOUNT}",
        f"#SBATCH --partition={partition}",
        "#SBATCH --nodes=1",
        f"#SBATCH --ntasks={ntasks}",
        "#SBATCH --cpus-per-task=1",
        f"#SBATCH --mem={max(8, MEM_PER_TASK_G * ntasks)}G",
        f"#SBATCH --time={H.slurm_time(limit_s)}",
        "#SBATCH --no-requeue",
        f"#SBATCH --output={rcfd}/section2d/runs/_slurm/%x.%j.out",
        "set -uo pipefail",
        f"source {rcfd}/hpc/job_env.sh",
        "job_banner || exit 1",
        f"CASE={unity_case}",
        'cd "$CASE" || { echo "hysteresis job: no folder $CASE"; exit 1; }',
        "# a case that has run before is not decomposed again: decomposePar -force would delete its progress",
        'if [ -e RUNNING ]; then echo "hysteresis job: RUNNING marker present (another or a killed job); not started"; exit 4; fi',
        'if ls -d processor[0-9]* >/dev/null 2>&1; then echo "hysteresis job: processor folders exist (run before); not started"; exit 4; fi',
        'echo "${SLURM_JOB_ID:-none}" > RUNNING',
        "start=$(date +%s); stamp=$(date +%Y-%m-%dT%H:%M:%S)",
        f'apptainer exec "$CFD_FOAM_IMAGE" bash -c "{solve}"',
        "rc=$?",
        "rm -f RUNNING",
        'if [ "$rc" -eq 0 ]; then status=complete; else status=failed; fi',
        "wall=$(( $(date +%s) - start ))",
        (f"printf '{{\"stage\": \"section2d\", \"name\": \"%s\", \"status\": \"%s\", \"rc\": %d, "
         f"\"job\": \"%s\", \"host\": \"%s\", \"ntasks\": %d, \"start\": \"%s\", \"wall_s\": %d}}\\n' "
         f"\"{name}\" \"$status\" \"$rc\" \"${{SLURM_JOB_ID:-}}\" \"$(hostname)\" {ntasks} \"$stamp\" \"$wall\" "
         f">> hpc_jobs.jsonl"),
        'echo "hysteresis job: $status (rc $rc) after $wall s"',
        'exit "$rc"',
        "",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="finished source case folder (cfd/section2d/runs/<case>)")
    ap.add_argument("name", help="restart folder name; start it with '_' (kept out of the CSV and pull_results)")
    ap.add_argument("--maxco", type=float, required=True, help="maxCo of the restart")
    ap.add_argument("--nconv", type=float, default=60.0, help="convective times c/U to add (default 60)")
    ap.add_argument("--ntasks", type=int, default=8, help="MPI ranks of the Unity job (default 8)")
    ap.add_argument("--s-per-step", type=float, help="seconds per step for the time limit (default: measured, see above)")
    ap.add_argument("--time-factor", type=float, default=3.0, help="time limit = estimate x this + 30 min (default 3)")
    ap.add_argument("--partition", default=PARTITION)
    ap.add_argument("--dst-root", help="parent folder of the restart (default: the source's parent)")
    ap.add_argument("--unity-case", help="case path on Unity for the sbatch (default <RCFD>/section2d/runs/NAME)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; write nothing")
    a = ap.parse_args()

    src = Path(a.src).resolve()
    H.case_safe(a.name)
    if not a.name.startswith("_"):
        ap.error("NAME must start with '_' so that the CSV rebuild and pull_results.py leave it out")
    if a.maxco <= 0 or a.nconv <= 0 or a.ntasks < 1:
        ap.error("--maxco, --nconv and --ntasks must be positive")
    dst = (Path(a.dst_root).resolve() if a.dst_root else src.parent) / a.name
    if dst.exists():
        raise SystemExit(f"{dst} exists; choose another NAME or remove it by hand")
    unity_case = a.unity_case or f"{H.RCFD}/section2d/runs/{a.name}"

    P, R, t_final, t_name = source_state(src)
    tc = float(P["convTime"])
    end_time = t_final + a.nconv * tc
    nconv_total = float(P["nConv"]) + a.nconv
    steps, sps, est_s, how = estimate(P, R, a.maxco, a.nconv, a.ntasks, a.s_per_step)
    limit_s = max(2 * 3600, est_s * a.time_factor + 1800)
    print(f"source   {src.name}: maxCo {float(P['maxCo']):g}, final time {t_name} s ({t_final / tc:.2f} c/U), "
          f"{int(P['nProcs'])} ranks")
    print(f"restart  {dst}: maxCo {a.maxco:g}, end time {end_time:.12g} s ({end_time / tc:.2f} c/U, +{a.nconv:g} c/U)")
    print(f"estimate {steps:,.0f} steps x {sps:.4g} s/step = {est_s / 3600:.2f} h ({how})")
    print(f"limit    {H.slurm_time(limit_s)} = {a.time_factor:g} x estimate + 30 min (at least 2 h); "
          f"{a.ntasks} ranks, partition {a.partition}")
    if a.dry_run:
        print("dry run: nothing written")
        return

    dst.mkdir(parents=True)
    for d in COPY_DIRS:
        shutil.copytree(src / d, dst / d)
    for f in COPY_FILES:
        shutil.copy2(src / f, dst / f)
    shutil.copytree(src / t_name, dst / t_name)
    (dst / "case.foam").touch()

    note = (f"// hysteresis restart of {src.name} from t = {t_name} s: maxCo {float(P['maxCo']):g} -> {a.maxco:g}, "
            f"+{a.nconv:g} c/U (cfd/hpc/hysteresis_restart.py)")
    cp = dst / "system" / "caseParameters"
    s = cp.read_text()
    s = set_entry(s, "caseName", a.name, cp)
    s = set_entry(s, "maxCo", f"{a.maxco:g}", cp)
    s = set_entry(s, "endTime", f"{end_time:.12g}", cp)
    s = set_entry(s, "nProcs", str(a.ntasks), cp)
    s = set_entry(s, "nConv", f"{nconv_total:g}", cp)
    first, rest = s.split("\n", 1)
    cp.write_text(f"{first}\n{note}\n{rest}")

    cdp = dst / "system" / "controlDict"
    c = cdp.read_text()
    c, n_stop = re.subn(r"^stopAt\s+\w+;", "stopAt          endTime;", c, flags=re.M)
    c, n_avg = re.subn(r"^(\s*restartOnRestart\s+)\w+;",
                       r"\g<1>true;    // hysteresis restart: the means cover the restart only", c, flags=re.M)
    if n_stop != 1 or n_avg != 1:
        raise SystemExit(f"{cdp}: stopAt ({n_stop}) or restartOnRestart ({n_avg}) not found exactly once")
    cdp.write_text(c)
    wi = float(re.search(r"^writeInterval\s+([^;\s]+);", s, re.M).group(1))
    foam_launch.align_final_write(dst, t_final, end_time, wi, say=print)

    Pn = dict(P)
    Pn.update(caseName=a.name, maxCo=a.maxco, endTime=end_time, nProcs=a.ntasks, nConv=nconv_total)
    Pn["restart"] = dict(
        source=src.name, source_maxCo=float(P["maxCo"]), source_nProcs=int(P["nProcs"]),
        t_restart_s=t_final, t_restart_name=t_name, t_restart_conv=t_final / tc, added_conv=a.nconv,
        maxCo=a.maxco, fieldAverage="restartOnRestart true: mean fields average the restart only",
        estimate_steps=round(steps), estimate_s_per_step=sps, time_limit=H.slurm_time(limit_s),
        prepared=time.strftime("%Y-%m-%dT%H:%M:%S"), script="cfd/hpc/hysteresis_restart.py")
    (dst / "case.json").write_text(json.dumps(Pn, indent=1))

    header = [
        f"Hysteresis restart {a.name} (cfd/hpc/hysteresis_restart.py, {time.strftime('%Y-%m-%d %H:%M')}):",
        f"  {src.name} at t = {t_name} s ({t_final / tc:.2f} c/U), maxCo {float(P['maxCo']):g} -> {a.maxco:g},",
        f"  +{a.nconv:g} c/U to {end_time:.10g} s ({end_time / tc:.2f} c/U).",
        f"  Estimate {steps:,.0f} steps x {sps:.4g} s/step = {est_s / 3600:.2f} h; limit {a.time_factor:g} x estimate + 30 min.",
        f"  Submit on Unity: sbatch {unity_case}/{SBATCH}",
    ]
    (dst / SBATCH).write_text(sbatch_text(a.name, unity_case, a.ntasks, limit_s, a.partition, header))

    # read back what the solver will see
    s2, c2 = cp.read_text(), cdp.read_text()
    got = {k: re.search(rf"^{k}\s+([^;\n]*);", s2, re.M).group(1) for k in ("maxCo", "endTime", "nProcs", "caseName")}
    got["stopAt"] = re.search(r"^stopAt\s+(\w+);", c2, re.M).group(1)
    got["restartOnRestart"] = re.search(r"^\s*restartOnRestart\s+(\w+);", c2, re.M).group(1)
    got["writeInterval line"] = re.search(r"^writeInterval\s+([^\n]*)$", c2, re.M).group(1).strip()
    got["start time folder"] = t_name
    print("written  " + ", ".join(f"{k} {v}" for k, v in got.items()))
    print(f"sbatch   {dst / SBATCH} (runs in {unity_case})")


if __name__ == "__main__":
    main()
