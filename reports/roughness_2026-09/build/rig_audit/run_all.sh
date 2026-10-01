#!/bin/sh
# Rebuild every rig_audit output from logs/ (system python3; numpy/pandas/scipy). Order matters.
set -e
cd "$(dirname "$0")"
python3 headers.py        > headers_stdout.txt 2>/dev/null
python3 recompute_pmax.py > recompute_pmax_stdout.txt
python3 fan_speed.py      > fan_speed_stdout.txt
python3 thevenin.py       > thevenin_stdout.txt
python3 run_timeline.py   > run_timeline_stdout.txt
python3 turbine_rpm.py    > turbine_rpm_stdout.txt
python3 sensitivity.py    > sensitivity_stdout.txt
REPO=/Users/stepheneacuello/Projects/windtunnel-control
for r in Ra20 Ra40 Ra80; do (cd "$REPO" && ./venv/bin/python src/generator_model.py --sweep logs/sweep_v1_${r}_points.csv) > generator_model_${r}_repo.txt; done
echo done
