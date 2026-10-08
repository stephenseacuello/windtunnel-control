#!/bin/sh
# after_case.sh <case_dir> [--bg]
#
# Record one CFD case after a queue has finished it: settings, logs, plots and ParaView
# images into cfd/<stage>/results/records/<case>/ (cfd/post/record_case.py). Never fails
# the caller: it always exits 0, and problems go to the log below.
#
#   cfd/post/after_case.sh cfd/section2d/runs/a090.0_U23.0_SST_medium_Tu1.0
#   cfd/post/after_case.sh cfd/rotor2d/runs/A_rot_U23.0_lam0.150_SST_medium --bg   # return at once
#
# Log: cfd/<stage>/results/records/after_case.log (one block per call).
#
# Callers: cfd/section2d/queue.py and cfd/rotor2d/queue.py run this after every completed
# case (run_after_case_hook: only if this file is executable; its process group is killed
# after 30 min; a failure never stops the queue). The stage and record_case.py's --kind
# (section or rotor) follow from the case path. Cases finished outside a queue:
#     python3 cfd/post/record_all.py
# records every finished case that has no up-to-date record. One call takes about
# 20-120 s at nice 10 in one process; add "--bg" to return at once.
#
# Python: cfd/.venv/bin/python (numpy, matplotlib) if it exists, else python3 on PATH.

case_dir=$1
here=$(cd "$(dirname "$0")" && pwd)
cfd=$(dirname "$here")

if [ -z "$case_dir" ] || [ ! -d "$case_dir" ]; then
    echo "after_case.sh: no case folder '$case_dir'" >&2
    exit 0
fi
case_abs=$(cd "$case_dir" && pwd)
case "$case_abs" in
    */rotor2d/*) stage=rotor2d; kind=rotor ;;
    *) stage=section2d; kind=section ;;
esac
logdir="$cfd/$stage/results/records"
mkdir -p "$logdir"
log="$logdir/after_case.log"
py="$cfd/.venv/bin/python"
[ -x "$py" ] || py=python3

run() {
    {
        echo "=== $(date '+%Y-%m-%d %H:%M:%S') after_case $case_abs"
        nice -n 10 "$py" "$here/record_case.py" "$case_abs" --kind "$kind" || echo "after_case: record_case.py exited with $?"
        echo
    } >> "$log" 2>&1
}

if [ "$2" = "--bg" ]; then
    run &
else
    run
fi
exit 0
