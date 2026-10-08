#!/bin/sh
# after_case.sh <case_dir> [--bg]     (Stage 2 post-case hook; run by cfd/stage2/queue.py)
#
# Same job as cfd/post/after_case.sh: the permanent record of one finished case (settings, logs,
# plots, ParaView images) by cfd/post/record_case.py --kind section, but written to
# cfd/stage2/results/records/<case>/ and logged to cfd/stage2/results/records/after_case.log.
# Why a wrapper: cfd/post/after_case.sh sends every case outside cfd/rotor2d/ to
# cfd/section2d/results/records/, and cfd/section2d/ and cfd/post/ were not to be edited while
# the Stage 1 and rotor queues run (8 Oct 2026). Once after_case.sh routes */stage2/* itself, run
# the queue with --hook cfd/post/after_case.sh, or delete this file's body and exec it.
# Never fails the caller: always exits 0.
#
# Known defect: cfd/post/render_fields.py orders the wall of patch 'blade' as one closed loop.
# Stage 2 splits the wall into blade (painted faces, two disconnected pieces) and bladeEnds, so the
# wall-distribution plots (fields/surface_*: Cp, Cf, y+) follow only one connected run of 'blade'.
# Forces, coefficients and the other images are not affected (README section 8).

case_dir=$1
here=$(cd "$(dirname "$0")" && pwd)
cfd=$(dirname "$here")

if [ -z "$case_dir" ] || [ ! -d "$case_dir" ]; then
    echo "after_case.sh: no case folder '$case_dir'" >&2
    exit 0
fi
case_abs=$(cd "$case_dir" && pwd)
name=$(basename "$case_abs")
logdir="$here/results/records"
mkdir -p "$logdir"
log="$logdir/after_case.log"
py="$cfd/.venv/bin/python"
[ -x "$py" ] || py=python3

run() {
    {
        echo "=== $(date '+%Y-%m-%d %H:%M:%S') stage2 after_case $case_abs"
        nice -n 10 "$py" "$cfd/post/record_case.py" "$case_abs" --kind section --out "$logdir/$name" \
            || echo "after_case: record_case.py exited with $?"
        echo
    } >> "$log" 2>&1
}

if [ "$2" = "--bg" ]; then
    run &
else
    run
fi
exit 0
