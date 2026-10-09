#!/usr/bin/env bash
# Upload to Unity what the jobs need (cfd/hpc/README.md):
#   1. the cfd/ code tree (scripts, templates, geometry, queue files), no runs/ or results/;
#   2. every mesh the queued cases need, from <stage>/runs/_mesh/ or cfd/hpc/mesh_cache/ (premesh.py),
#      into <stage>/runs/_mesh/<key>/ on Unity; meshes already there are left alone.
# Never deletes anything on Unity. Usage:  bash cfd/hpc/sync_up.sh [--code-only]
set -euo pipefail
HPC=$(cd "$(dirname "$0")" && pwd)
CFD=$(dirname "$HPC")
HOST=${CFD_HPC_HOST:-unity}
ROOT=${CFD_HPC_ROOT:-/work/pi_sodhi_uri_edu/seacuello/windtunnel-cfd}
RCFD=$ROOT/repo/cfd
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=30)

"${SSH[@]}" "$HOST" "mkdir -p $RCFD $ROOT/jobs && for s in section2d rotor2d stage2; do mkdir -p $RCFD/\$s/runs/_mesh $RCFD/\$s/runs/_slurm $RCFD/\$s/results; done
  # run_case.py makes a missing mesh with cfd/.venv/bin/python: point it at the Unity venv
  [ -e $RCFD/.venv ] || ln -s $ROOT/venv $RCFD/.venv"

echo "== code"
rsync -az --exclude='/runs/' --exclude='/*/runs/' --exclude='/*/results/' --exclude='/validation/' \
      --exclude='/hpc/mesh_cache/' --exclude='/hpc/jobs/' --exclude='/.venv/' --exclude='__pycache__/' \
      --exclude='.DS_Store' --exclude='/*/queues/STOP' --exclude='/*/queues/LOCK' \
      "$CFD/" "$HOST:$RCFD/"

[ "${1:-}" = "--code-only" ] && exit 0

echo "== meshes"
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/cfd_meshes.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT
have=$("${SSH[@]}" "$HOST" "cd $RCFD && ls -d */runs/_mesh/*/MESH_OK 2>/dev/null | sed 's#/MESH_OK##'" || true)
n=0
while IFS=$'\t' read -r stage key dir; do
    [ -n "$dir" ] || continue
    if grep -qx "$stage/runs/_mesh/$key" <<<"$have"; then continue; fi
    mkdir -p "$STAGE/$stage/runs/_mesh"
    ln -s "$dir" "$STAGE/$stage/runs/_mesh/$key"
    n=$((n + 1))
done < <(cd "$CFD/.." && nice -n 10 python3 cfd/hpc/premesh.py --list --paths --sense-variants 2>/dev/null \
         | awk -F'\t' 'NF == 3')
echo "$n meshes to upload"
if [ "$n" -gt 0 ]; then
    # -L copies the linked mesh folders; MESH_OK goes last so a half-copied mesh is never "ok"
    rsync -azL --exclude='MESH_OK' "$STAGE/" "$HOST:$RCFD/"
    rsync -azL --include='*/' --include='MESH_OK' --exclude='*' "$STAGE/" "$HOST:$RCFD/"
fi
echo "sync_up done"
