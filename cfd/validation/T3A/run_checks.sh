#!/bin/zsh
# Two checks on the T3A result, run in cfd/runs/ (git-ignored); needs run.sh first.
#   T3A_np4    the same case on 4 MPI ranks (scotch): MPI works, result unchanged, speed-up
#   T3A_tight  residualControl 1e-12, so all 1000 iterations run: is the transition converged?
# compare.py picks both up and adds them to result.md and metrics.json.
set -e
here=${0:A:h}
runs=${here:h:h}/runs
mkdir -p $runs
for d in T3A_np4 T3A_tight; do
  rm -rf $runs/$d && mkdir $runs/$d
  cp -R $here/0.orig $here/constant $here/system $runs/$d/
  rm -rf $runs/$d/constant/polyMesh
done

cat > $runs/T3A_np4/system/decomposeParDict <<'EOF'
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      decomposeParDict;
}

numberOfSubdomains 4;

method          scotch;
EOF

python3 - $runs/T3A_tight/system/fvSolution <<'EOF'
import re, sys
p = sys.argv[1]
s = open(p).read()
block = re.search(r"residualControl\s*\{[^}]*\}", s).group(0)
s = s.replace(block, re.sub(r"\b\d+(\.\d+)?e-\d+;", "1e-12;", block))
open(p, "w").write(s)
EOF

caffeinate -i openfoam2606 -c "cd $runs/T3A_np4 && . \$WM_PROJECT_DIR/bin/tools/RunFunctions && restore0Dir && runApplication blockMesh && runApplication decomposePar && runParallel simpleFoam && runApplication reconstructPar -latestTime && runApplication postProcess -func writeCellCentres -latestTime"
caffeinate -i openfoam2606 -c "cd $runs/T3A_tight && . \$WM_PROJECT_DIR/bin/tools/RunFunctions && restore0Dir && runApplication blockMesh && runApplication simpleFoam && runApplication postProcess -func writeCellCentres -latestTime"

python3 $here/compare.py
