# T3A transition check (Stage 0)

**Result: does not match.** The model puts transition 84 mm (onset) to 128 mm (50 % point) upstream of the measurement. Criterion: onset (cf minimum) and 50 % point of the cf rise both within +-0.05 m (half the 0.1 m station spacing) of the experiment.

The offset is not a convergence or parallel artefact: running all 1000 iterations with residualControl 1e-12, or on 4 MPI ranks, moves c_f by at most 0.56 % and the transition positions by at most 0.10 mm (table below).

The tutorial ships the experimental data but no reference simulation, so whether ESI's own run shows the same offset is not known.

| | Simulation | Experiment | Difference |
|---|---|---|---|
| Transition onset (c_f minimum), x | 322 mm | 406 mm (station minimum 395 mm) | -84 mm |
| 50 % of the c_f rise, x | 538 mm | 666 mm | -128 mm |
| End (c_f maximum), x | 766 mm | 853 mm (station maximum 895 mm) | -87 mm |
| Onset Re_x | 1.16e+05 | 1.45e+05 | |
| c_f at onset / peak | 0.00244 / 0.00460 | 0.00210 / 0.00486 | |

- c_f at the stations: laminar part (x < 0.4 m) within 21 %; turbulent part (x > 0.9 m) within 6 % (mean -2 %).
- Free-stream Tu decay: within 8 % of the measured Tu at every station.
- Simulation values are from the 300 flat plate faces at time 269. The tutorial's own sampled line gives onset 304 mm and 50 % point 538 mm (30 mm sample spacing).
- Experiment positions are interpolated between stations 100 mm apart (parabola through the three stations around the extremum; linear for the 50 % point); that spacing is why the criterion is +-50 mm.

Run: the tutorial unchanged (kOmegaSSTLM, simpleFoam, 26,820 cells), serial, 269 iterations.

- Wall time 15.8 s (restore0Dir + blockMesh + simpleFoam, 1 core, 2026-10-07 16:04).
- simpleFoam alone: ExecutionTime = 14.55 s  ClockTime = 15 s
- SIMPLE solution converged in 269 iterations

Checks (cfd/runs/, from run_checks.sh):

| Case | Ranks | Iterations | Solver clock time | Onset / 50 % / end, mm | Max c_f change vs serial |
|---|---|---|---|---|---|
| serial (this case) | 1 | 269 | 15 s (ExecutionTime 14.6 s) | 322 / 538 / 766 | - |
| T3A_np4: same case, 4 MPI ranks (scotch) | 4 | 269 | 7 s (ExecutionTime 7.2 s) | 322 / 538 / 766 | 0.01 % |
| T3A_tight: residualControl 1e-12: all 1000 iterations | 1 | 1000 | 40 s (ExecutionTime 39.9 s) | 322 / 538 / 766 | 0.56 % |

Files: `result.png` (plot), `metrics.json` (all numbers), `cf_plate.csv` (c_f along the plate). Re-run with `./run.sh`.
