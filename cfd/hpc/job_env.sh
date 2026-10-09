# Sourced by every Slurm job script of cfd/hpc/ (submit.py, test_job.sh). Unity only.
# Sets how run_case.py calls OpenFOAM (cfd/post/foam_launch.py) and which Python runs it.
#   ROOT   /work/pi_sodhi_uri_edu/seacuello/windtunnel-cfd   (override: CFD_HPC_ROOT)
#   RCFD   $ROOT/repo/cfd   (the mirror written by sync_up.sh)
#   PY     $ROOT/venv/bin/python   (Python 3.12, numpy, scipy, matplotlib; no OpenFOAM)
ROOT=${CFD_HPC_ROOT:-/work/pi_sodhi_uri_edu/seacuello/windtunnel-cfd}
RCFD=$ROOT/repo/cfd
PY=$ROOT/venv/bin/python
export CFD_HPC_ROOT=$ROOT
# OpenFOAM v2606 (same source commit 481094f as the Mac app) in the opencfd image, through apptainer
export CFD_FOAM_LAUNCH=container
export CFD_FOAM_IMAGE=${CFD_FOAM_IMAGE:-$ROOT/containers/openfoam-run_2606.sif}
export CFD_FOAM_BASHRC=/usr/lib/openfoam/openfoam2606/etc/bashrc
export APPTAINER_CACHEDIR=$ROOT/cache/apptainer
export OMP_NUM_THREADS=1
export MPLBACKEND=Agg
export PYTHONUNBUFFERED=1
umask 0022

job_banner() {
    echo "== $(date '+%Y-%m-%d %H:%M:%S %Z') job ${SLURM_JOB_ID:-none} '${SLURM_JOB_NAME:-}' on $(hostname)," \
         "tasks ${SLURM_NTASKS:-?}, cpus on node ${SLURM_CPUS_ON_NODE:-?}, partition ${SLURM_JOB_PARTITION:-?}"
    echo "   cpu: $(lscpu 2>/dev/null | sed -n 's/^Model name: *//p' | head -1)"
    echo "   image: $CFD_FOAM_IMAGE"
    [ -s "$CFD_FOAM_IMAGE" ] || { echo "job_env.sh: image missing"; return 1; }
    [ -x "$PY" ] || { echo "job_env.sh: $PY missing"; return 1; }
    return 0
}
