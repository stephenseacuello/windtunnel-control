# cfd/analysis/2026-10-15: analysis of all 263 CFD cases (113 new since 13 Oct)

This folder analyses the 113 cases finished on Unity after 13 Oct 2026, together with the 150 of
13 Oct, and revises the 13 Oct findings. Where to start:
- [TEAM_SUMMARY.md](TEAM_SUMMARY.md): the faculty summary (revises `../2026-10-13/TEAM_SUMMARY.md`).
- [UPDATE.md](UPDATE.md): the teaching account, question by question, with what changed from 13 Oct.
- `../2026-10-13/`: the 13 Oct analysis (README, RESULTS.md, scripts); not edited here.

The scripts read the live result tables, the downloaded case folders and the records, read only;
they write only into `out/` and `fig/` of this folder. Unlike 13 Oct, no copy of the tables is kept:
`data/` is empty. `src/section_lib.py` stops if the SHA-256 of `section_polars.csv` changes, and
`out/rotor_numbers.json` records the SHA-256 of the rotor tables, so a rebuilt table is noticed
before a number moves. The folder is about 6 MB.

## Contents

| Path | Contents |
|---|---|
| `TEAM_SUMMARY.md` | Headline results, case table, key figures, established against preliminary, bearing on the gains, next steps, limits |
| `UPDATE.md` | Per question: what was run, the key figure and how to read it, the result with provenance and strength, what changed from 13 Oct, physics and meaning for the gains; next steps |
| `src/` | Analysis, figure and independent check scripts (below) |
| `out/` | Tables, JSON and log caches written by the scripts |
| `fig/` | 19 figures, PNG, 200 dpi, 3.4–4.0 in wide (half a page) |
| `data/` | Empty (the tables are read in place) |

### Inputs (read only)

| Input | Contents | Read by |
|---|---|---|
| `cfd/section2d/results/section_polars.csv` | 125 rows: the 51 of 13 Oct (values unchanged) and 74 new | `section_*`; `roughness_analysis.py` (medium-mesh rows at 23 m/s) |
| `cfd/stage2/results/stage2_polars.csv` | 69 rows: the 43 of 13 Oct (values unchanged) and 26 new | `roughness_*`; `rotor_analysis.py` (wall-function rows at α 90 and 180) |
| `cfd/rotor2d/results/rotor_cp.csv`, `rotor_static.csv` | 53 rows (40 + 13 new) and 16 rows (unchanged) | `rotor_*` |
| `cfd/*/runs/<case>/` | `case.json`, force and moment histories (`postProcessing`), solver logs (`log.pimpleFoam`), `hpc_jobs.jsonl`; for the Stage 2 texture runs also the mesh and final time-mean fields | histories, rotor and check scripts |
| `cfd/section2d/runs/_unity_a000.0_U23.0_SST_medium_Tu1.0`, `_hyst_Co5to2p5_a000`, `_hyst_Co2p5to5_a000` | The Unity repeat of the Mac's α-0 run and the two restarts (not in the tables) | `section_histories.py`, section checks |
| `cfd/section2d/results/records/<case>/fields/surface_mean.csv` | Time-mean wall Cp and Cf | `section_analysis.py`, section checks |
| `cfd/rotor2d/layout/poses_A_B.json` | Blade geometry of assembly A | `rotor_analysis.py` |
| `reports/roughness_2026-09/build/` | Measured gains and rotor speed (`numbers.json`, `derived/*.csv`, `tacho/derived/rotor_speed_by_dwell.csv`) | `roughness_*`, `rotor_*` |
| `cfd/analysis/2026-10-13/data/`, `out/` | The 13 Oct tables and numbers, for identity checks and comparisons | all stages |

### src/

Stage 1, smooth section:

| Script | Reads | Writes |
|---|---|---|
| `section_lib.py` | shared loader (SHA-256 check), the 13 Oct health flag (unchanged), figure style | nothing |
| `section_histories.py` | force histories and solver logs of the 125 runs, the repeat and the restarts | `out/section_jumps.csv`, `section_log_residuals.csv` (log cache), `section_timestep_blocks.csv`, `section_histories.json`; `fig/section_timestep_histories.png`. Stops unless the 51 old runs reproduce the 13 Oct `section_force_jumps.csv` |
| `section_analysis.py` | the table, the outputs above, the records' `surface_mean.csv` | `out/section_case_quality.csv`, `section_timestep.csv`, `section_timestep_changes.csv`, `section_polar_LM23.csv`, `section_transition_{pairs,tu,speed,surface}.csv`, `section_summary.json` |
| `section_figures.py` | the table and `out/section_*` | the other six `fig/section_*.png` |
| `section_verify.py` | independent check (own readers of forces, logs and wall data) | prints only |
| `section_review_check.py` | first review's independent check | prints; cache `out/section_review_residuals.csv` |
| `section_review2_check.py` | second review's independent check (also reads `out/rotor_lambda0.csv`) | prints; cache `out/section_review2_logs.csv` |

Stage 2, roughness on the section:

| Script | Reads | Writes |
|---|---|---|
| `roughness_histories.py` | force histories of the 69 runs; logs of the 16 texture runs at maxCo 2.5 | `out/roughness_histories_runs.csv`, `roughness_histories_blocks.csv`, `roughness_log_blocks.csv`, `roughness_histories.json`; `fig/roughness_texture_histories.png` |
| `roughness_surface.py` | meshes and final time-mean fields of the α-180 texture runs (the records cover only part of the blade) | `out/roughness_surface_summary.csv`, `roughness_surface_profiles.csv`; `fig/roughness_surface_a180.png` |
| `roughness_analysis.py` | the Stage 2 table, section rows, `out/roughness_histories_runs.csv`, report build files | the other `out/roughness_*.csv`, `roughness_numbers.json`; five `fig/roughness_*.png` |
| `roughness_verify.py` | independent check | prints only |
| `roughness_review_check.py` | review's independent check | prints; cache `out/roughness_review_logblocks.csv` |

Stage 3, rotor:

| Script | Reads | Writes |
|---|---|---|
| `rotor_analysis.py` | rotor tables, force and moment histories of every rotating case, geometry, Stage 2 rows, rig CSVs | `out/rotor_{health,per_rev,noise,roughness,roughness_phase,roughness_sectors,grid,lambda0}.csv`, `rotor_numbers.json`; `fig/rotor_*.png` (5) |
| `rotor_verify.py` | independent check (pandas reader, resampled revolutions) | prints only |
| `rotor_review_check.py` | second independent check (exact interpolant integrals, blade forces) | prints only |

Final review (19 Oct), all stages:

| Script | Reads | Writes |
|---|---|---|
| `team_summary_check.py` | the four tables, the section, Stage 2 and rotor case folders (forces, moments, logs, `mesh_info.json`), the Unity repeat and the restarts, the 13 Oct tables, the report build files, `cfd/docs/ROUGHNESS_KS.md` | prints; cache `out/team_summary_check_logs.csv` (first-pressure residuals of the 126 section logs) |

The `*_verify.py`, `*_review_check.py`, `section_review2_check.py` and `team_summary_check.py`
scripts share no code with the analysis scripts or with one another. Their `CHECK` lines in the
reviews are the corrections that UPDATE.md and TEAM_SUMMARY.md use; `team_summary_check.py`
recomputes every number of TEAM_SUMMARY.md and the UPDATE.md numbers that the final review
corrected.

### out/ (main files)

| File | Contents |
|---|---|
| `section_case_quality.csv` | One row per section case (125): health flag (`corrupted` = flagged), 13 Oct symptoms, jumps, residual share |
| `section_jumps.csv`, `section_log_residuals.csv` | Jumps at limits 0.5/0.2/0.1, window means and drifts without jump intervals, last-50 and last-10 c/U means; share of window steps whose first pressure solve starts above 0.05 |
| `section_timestep.csv`, `section_timestep_changes.csv`, `section_timestep_blocks.csv` | α 0 and 180 at maxCo 5/2.5/1.25; the changes with their noise; 10-c/U blocks, including the restarts |
| `section_polar_LM23.csv` | LM polar at 23 m/s from healthy runs, maxCo per point |
| `section_transition_*.csv` | LM against SST pairs; Tu and speed effects; wall data (separation, Cf peak, base Cp) |
| `section_summary.json`, `section_histories.json` | Every Stage 1 number quoted |
| `roughness_health.csv` | Stage 2 health status and comparison use per run |
| `roughness_wf_effects.csv`, `roughness_timestep_{pairs,effects}.csv`, `roughness_trends.csv` | Rough-wall changes against Ks 0, maxCo 5 against 2.5 |
| `roughness_tex_*.csv` | Texture changes per window, time-step pairs, SST minus LM |
| `roughness_drag_difference.csv` | D = Cd(α 0) − Cd(α 180) by Ks and t, fair sets marked |
| `roughness_lm_speed.csv`, `roughness_surface_*.csv` | LM speed bracket; wall pressure by face |
| `roughness_bottom_line.csv` | The 52 fair comparisons with noise, resolution and sign |
| `roughness_measured.csv`, `roughness_required_section_change.csv`, `roughness_section_timestep_context.csv` | Measured gains; the section change they need (two-position model); Stage 1 context rows |
| `roughness_numbers.json`, `roughness_histories.json` | Other Stage 2 numbers |
| `rotor_health.csv` | All 69 rotor runs: time-step proxy, ω and AMI checks, symptoms |
| `rotor_per_rev.csv`, `rotor_noise.csv` | Revolution means; scatter, autocorrelation, batch means, drift |
| `rotor_roughness.csv`, `rotor_roughness_phase.csv`, `rotor_roughness_sectors.csv` | Rough-minus-reference ΔC_Q with 2u, drift rule and halves; blade C_Q by azimuth; sector budget |
| `rotor_grid.csv`, `rotor_lambda0.csv` | Mesh check; zero-torque λ by speed, mesh and window |
| `rotor_numbers.json` | Every rotor number quoted, with the table SHA-256 |
| `team_summary_check_logs.csv` | Cache of `team_summary_check.py`: per section log, steps parsed, window share and median of the first pressure solve's initial residual |

### fig/

| Figure | Shows | UPDATE.md |
|---|---|---|
| `section_health.png` | The 13 Oct flag on all 125 section runs: proxy, force symptom, jumps | §1 |
| `section_timestep.png` | Cd, Cl, St against maxCo 5/2.5/1.25 at α 0 and 180 | §2 |
| `section_timestep_histories.png` | Cd(t), Cl(t) of the time-step runs and the two restarts | §2, §3 |
| `section_polar.png` | LM polar at 23 m/s, healthy runs, maxCo per point | §4 |
| `section_transition_lm_sst.png` | LM against SST, Cd and Cl at α 150–210° and three speeds | §5 |
| `section_transition_tu.png` | LM at Tu 0.5/1/3 % against SST | §5 |
| `section_transition_a180.png` | α 180: Cd, tip-B separation and base Cp against speed | §5 |
| `roughness_timestep_sweeps.png` | Rough-wall sweeps at α 90 and 180, maxCo 5 against 2.5 | §2 |
| `roughness_drag_difference.png` | D against Ks and t (fair pairs), and the measured power change | §6 |
| `roughness_texture_windows.png` | Cd against texture amplitude, both windows and time steps | §6 |
| `roughness_texture_histories.png` | Running-mean Cd(t) of the 23 m/s texture runs | §3, §6 |
| `roughness_lm_speed.png` | LM texture effect on Cd(180) against speed, with the measured gains | §6 |
| `roughness_surface_a180.png` | Convex-face Cp at α 180, smooth and textured | §6 |
| `roughness_bottom_line.png` | Forest plot of the fair roughness comparisons | §6 |
| `rotor_roughness_dCQ.png` | Rough-blade rotor ΔC_Q with 2u and the rig-implied band | §7 |
| `rotor_roughness_phase.png` | Blade torque and its roughness change by azimuth; sector budget | §7 |
| `rotor_histories.png` | Revolution means of the long runs and of the 38 m/s case | §8 |
| `rotor_grid.png` | C_Q and zero-torque λ on three meshes at 23 m/s | §8 |
| `rotor_lambda_vs_U.png` | Zero-torque λ against wind speed, CFD and rig | §8 |

Encoding (13 Oct, extended): smooth blade or Plain black; roughness a blue ramp; rig orange; SST
squares with dashed lines, LM circles with solid lines; maxCo 5 open, 2.5 filled, 1.25 half-filled;
flagged run grey ×; LM at Tu 0.5/1/3 % a violet ramp, light to dark, with dotted/solid/dash-dot
lines; grey ring = residual signature; open circle with × = jumps in more than half of the window.

## How to rerun

From the repository root, stage by stage, in this order:

```zsh
cd /Users/stepheneacuello/Projects/windtunnel-control
# Stage 1
nice -n 10 python3 cfd/analysis/2026-10-15/src/section_histories.py           # ~10 min (49 GB of logs); --no-logs ~50 s
nice -n 10 python3 cfd/analysis/2026-10-15/src/section_analysis.py
nice -n 10 python3 cfd/analysis/2026-10-15/src/section_figures.py
nice -n 10 python3 cfd/analysis/2026-10-15/src/section_verify.py             # ~1 min cold
nice -n 10 python3 cfd/analysis/2026-10-15/src/section_review_check.py       # ~3 s with cache; --logs ~15 min
# Stage 2
nice -n 10 python3 cfd/analysis/2026-10-15/src/roughness_histories.py        # ~4 min (16 logs); --no-logs ~20 s
nice -n 10 python3 cfd/analysis/2026-10-15/src/roughness_surface.py          # ~5 s
nice -n 10 python3 cfd/analysis/2026-10-15/src/roughness_analysis.py
nice -n 10 python3 cfd/analysis/2026-10-15/src/roughness_verify.py           # ~1.5 min
nice -n 10 python3 cfd/analysis/2026-10-15/src/roughness_review_check.py     # ~2 s with cache; --logs ~10 min
# Stage 3
nice -n 10 python3 cfd/analysis/2026-10-15/src/rotor_analysis.py             # ~4 s
nice -n 10 python3 cfd/analysis/2026-10-15/src/rotor_verify.py               # ~7 s
nice -n 10 python3 cfd/analysis/2026-10-15/src/rotor_review_check.py         # ~6 s
# after Stage 3 (reads out/rotor_lambda0.csv)
nice -n 10 python3 cfd/analysis/2026-10-15/src/section_review2_check.py      # ~2 s with cache; --logs ~4 min
# final review of TEAM_SUMMARY.md (reads only raw inputs)
nice -n 10 python3 cfd/analysis/2026-10-15/src/team_summary_check.py         # ~1 min cold, 5 s warm; --logs ~6 min
```

- **Requirements.** Python 3 with numpy, pandas, matplotlib and scipy (scipy for the section
  checks), checked on 19 Oct with `/opt/homebrew/bin/python3`: Python 3.14.8, numpy 2.5.4,
  pandas 3.0.1, matplotlib 3.11.2, scipy 1.17.0. Paths resolve from each script's location.
- **Expected check results** (19 Oct): `section_verify.py` 0 `CHECK`; `roughness_verify.py`
  123 checks, 0 `CHECK`; `rotor_verify.py` 287 OK, 0 `CHECK`; `rotor_review_check.py` 177 OK,
  0 `CHECK`. The review scripts print their corrections as `CHECK` lines:
  `section_review_check.py` 8, `section_review2_check.py` 14 (with 31 OK and 9 `NEW`, findings the
  analysis had missed), `roughness_review_check.py` 8 of 93. UPDATE.md and TEAM_SUMMARY.md use the
  corrected values and wording. `team_summary_check.py`: 231 OK, 0 `CHECK`, 20 `INFO` against the
  corrected documents; its labels name the final review's fixes (two numbers: 22, not 23, flagged
  cases re-run; the wall function alone moves the edge-on force by 11–23 %, not 15–23 %; the rest
  are wording, fairness and completeness).
- **Reproducibility.** Reruns on 19 Oct gave byte-identical `out/` files and figures (`shasum`),
  apart from the reviews' deliberate changes: figure labels, markers and rows in all three stages;
  `t_quiet` added to `out/section_histories.json`; and one definition, the rotor drift-rule halves,
  which now span whole blade-passing periods (drift columns of `out/rotor_noise.csv`,
  `rotor_roughness.csv` and `rotor_numbers.json`).
- **Order.** `section_analysis.py` needs `section_histories.py`; `section_figures.py` needs both;
  `roughness_analysis.py` needs `roughness_histories.py`. The `--no-logs` options reuse the log
  caches in `out/`.

## Known defects outside this folder (not edited here)

- `cfd/post/rotor_summary.py` drops the last revolution from `CQ_per_rev` (and so corrupts
  `CQ_drift_last_two_rev`) in 6 cases where t_end/T falls short of an integer by more than 1e-9.
  Window means are unaffected; `rotor_analysis.py` computes its own revolution means.
- `cfd/post/render_fields.py` assumes one closed loop per wall patch, so the Stage 2 records'
  surface tables and plots cover only 896 of 3,425 blade faces (texture meshes) and 121 of 459
  (wall-function meshes); `roughness_surface.py` reads the binary fields instead.
