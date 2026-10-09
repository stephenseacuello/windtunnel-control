#!/bin/bash
# Short end-to-end test of the Unity path (cfd/hpc/README.md): run_one.py -> run_case.py ->
# foam_launch (container) for each stage, and the migration path (reconstruct, drop processor*/,
# MIGRATED, resume on another rank count). Test folders start with '_' (never in the CSVs).
#   ssh unity sbatch /work/pi_sodhi_uri_edu/seacuello/windtunnel-cfd/repo/cfd/hpc/test_job.sh
#SBATCH --job-name=cfd.test
#SBATCH --account=pi_sodhi_uri_edu
#SBATCH --partition=uri-cpu
#SBATCH --qos=short
#SBATCH --nodes=1
#SBATCH --ntasks=16
#SBATCH --mem=32G
#SBATCH --time=00:45:00
#SBATCH --output=/work/pi_sodhi_uri_edu/seacuello/windtunnel-cfd/repo/cfd/hpc/test_%j.out
set -uo pipefail
source /work/pi_sodhi_uri_edu/seacuello/windtunnel-cfd/repo/cfd/hpc/job_env.sh
job_banner || exit 1
cd "$RCFD"
rm -rf section2d/runs/_hpc_test_s rotor2d/runs/_hpc_test_r stage2/runs/_hpc_test_w
foam() { apptainer exec "$CFD_FOAM_IMAGE" bash -c "source $CFD_FOAM_BASHRC && $1"; }

echo "== 1. section2d coarse a000, 8 ranks, 240 s"
"$PY" hpc/run_one.py --stage section2d --name a000.0_U23.0_SST_coarse_Tu1.0 \
    --case '{"alpha": 0.0, "U": 23.0, "model": "SST", "level": "coarse", "tu": 1.0}' \
    --np 8 --folder _hpc_test_s --wall-limit 240; echo "rc $?"
grep -m1 -i "decay" section2d/runs/_hpc_test_s/log.pimpleFoam; grep -c "^Time = " section2d/runs/_hpc_test_s/log.pimpleFoam
ls section2d/runs/_hpc_test_s/processor0 section2d/runs/_hpc_test_s/postProcessing

echo "== 2. migration path: reconstruct, drop processor*, MIGRATED, resume on 4 ranks for 120 s"
C=section2d/runs/_hpc_test_s
foam "cd $C && reconstructPar -latestTime > log.reconstructPar.test 2>&1"; echo "reconstruct rc $?"
ls $C
rm -rf $C/processor*; echo '{"source": "test"}' > $C/MIGRATED
"$PY" hpc/run_one.py --stage section2d --name a000.0_U23.0_SST_coarse_Tu1.0 \
    --case '{"alpha": 0.0, "U": 23.0, "model": "SST", "level": "coarse", "tu": 1.0}' \
    --np 4 --folder _hpc_test_s --wall-limit 120; echo "rc $?"
ls $C/processor0; cat $C/MIGRATED; grep -E "^(Time|Starting time) " $C/log.pimpleFoam | sed -n '1p;$p'

echo "== 3. rotor2d static B theta 90, 8 ranks, 240 s"
"$PY" hpc/run_one.py --stage rotor2d --name B_sta_U23.0_th090.0_SST_medium \
    --case '{"hyp": "B", "U": 23.0, "model": "SST", "level": "medium", "theta": 90.0, "np": 2}' \
    --np 8 --folder _hpc_test_r --wall-limit 240; echo "rc $?"
grep -c "^Time = " rotor2d/runs/_hpc_test_r/log.pimpleFoam; ls rotor2d/runs/_hpc_test_r/postProcessing

echo "== 4. stage2 wf a000 Ks100, 8 ranks, 240 s"
"$PY" hpc/run_one.py --stage stage2 --name a000.0_U23.0_SST_wf_Ks100_Tu1.0 \
    --case '{"alpha": 0.0, "U": 23.0, "model": "SST", "wall": "wf", "ks": 100.0}' \
    --np 8 --folder _hpc_test_w --wall-limit 240; echo "rc $?"
grep -c "^Time = " stage2/runs/_hpc_test_w/log.pimpleFoam; grep -m2 -i "rough\|Ks" stage2/runs/_hpc_test_w/0/nut | head -3

echo "== 5. gmsh on Unity against the Mac: one section mesh into a scratch cache"
"$PY" - <<'EOF'
import sys, hashlib
from pathlib import Path
sys.path.insert(0, "hpc")
import hpc_common as H
rc = H.load_queue("section2d").run_case
rc.MESHES = Path("/work/pi_sodhi_uri_edu/seacuello/windtunnel-cfd/tmp/meshtest")
d = rc.ensure_mesh("coarse", 0.0)
for f in ("points", "faces", "owner", "neighbour"):
    a = hashlib.md5((d / "constant/polyMesh" / f).read_bytes()).hexdigest()
    b = hashlib.md5((Path("section2d/runs/_mesh/coarse_a000.0/constant/polyMesh") / f).read_bytes()).hexdigest()
    print(f, "identical" if a == b else f"DIFFERENT {a} {b}")
EOF
echo "== test done $(date)"
