#!/bin/zsh
# Stage 0 toolchain check: the ERCOFTAC T3A flat-plate transition tutorial,
# copied unchanged from $FOAM_TUTORIALS/incompressible/simpleFoam/T3A (v2606).
#
# Runs what the tutorial's Allrun runs (restore0Dir, blockMesh, simpleFoam), serial
# on 1 core as shipped, then writes the face centres (writeCellCentres) so the
# wall shear stress can be read on every plate face. The tutorial's last step,
# validation/plot, needs gnuplot, which is not installed, so compare.py does the
# comparison instead with the system python3.
#
# Usage:  cfd/validation/T3A/run.sh             about 20 s on the M2
#         cfd/validation/T3A/run_checks.sh      optional: 4-rank and fully converged runs
#         openfoam2606 -c "cd <this dir> && ./Allclean"   reset
set -e
here=${0:A:h}
now() { python3 -c 'import time; print(time.time())'; }

t0=$(now)
caffeinate -i openfoam2606 -c "cd $here && . \$WM_PROJECT_DIR/bin/tools/RunFunctions && restore0Dir && runApplication blockMesh && runApplication simpleFoam"
t1=$(now)
openfoam2606 -c "cd $here && postProcess -func writeCellCentres -latestTime > log.writeCellCentres 2>&1"

{
  printf 'Wall time %.1f s (restore0Dir + blockMesh + simpleFoam, 1 core, %s).\n' $(( t1 - t0 )) "$(date '+%Y-%m-%d %H:%M')"
  grep -E '^ExecutionTime' $here/log.simpleFoam | tail -1 | sed 's/^/simpleFoam alone: /'
  grep -E 'converged in' $here/log.simpleFoam | sed 's/^ *//'
} | tee $here/timing.txt

python3 $here/compare.py
