# cfd/analysis/2026-10-13: analysis of the 150 finished CFD cases

This folder analyses the result tables of all 150 finished cases (13 Oct 2026). Where to start:
- [TEAM_SUMMARY.md](TEAM_SUMMARY.md): the faculty summary, two pages.
- [RESULTS.md](RESULTS.md): the full, teaching-oriented account.

The scripts read only the tables in `data/` and a few read-only files elsewhere in the repo (below).
No case folder under `cfd/*/runs/` or `cfd/*/results/` is read or written. The folder is 2.5 MB.

## Contents

| Path | Contents |
|---|---|
| `TEAM_SUMMARY.md` | Headline results, case table, key figures, established against preliminary, next steps |
| `RESULTS.md` | Per stage: what was run and why, how to read each figure, findings with provenance and strength, physics, link to the wind-tunnel results; numerical quality, 2D-URANS limits, conclusions, next steps |
| `data/` | Input tables (do not edit) |
| `src/` | Analysis, figure and verification scripts |
| `out/` | Tables and JSON written by the scripts |
| `fig/` | 18 figures, PNG, 200 dpi |

### data/

| File | Cases | Unity / Mac | Stage |
|---|---|---|---|
| `section_polars.csv` | 51 | 47 / 4 | 1, smooth blade section |
| `stage2_polars.csv` | 43 | 42 / 1 | 2, roughness (rough wall functions and resolved texture) |
| `rotor_static.csv` | 16 | 11 / 5 | 3a, static rotor |
| `rotor_cp.csv` | 40 | 40 / 0 | 3b, rotating rotor |

**Provenance.**
- **Unity rows.** These are Unity's result CSVs as copied on 13 Oct 2026 at 17:33 EDT. They were
  rebuilt on Unity after each case.
- **Mac rows.** The 10 cases that finished on the Mac before the move to Unity:
  - section `a000.0_U23.0_SST_coarse_Tu1.0`, `a000.0_U23.0_SST_medium_Tu1.0`,
    `a090.0_U23.0_SST_coarse_Tu1.0` and `a180.0_U23.0_SST_coarse_Tu1.0`;
  - rotor static `A_sta_U23.0_th{000,030,060}.0_SST_medium` and `B_sta_U23.0_th{000,060}.0_SST_medium`;
  - Stage 2 `a180.0_U23.0_SST_wf_Ks0_Tu1.0`.
- **The `ran_on` column** (`mac`/`unity`) was added in the merge, and the scripts read it. The three
  cases moved from the Mac to Unity mid-run are labelled `unity` (RESULTS.md §1.2).

### src/

| Script | Reads | Writes |
|---|---|---|
| `section_lib.py` | shared loading, health flag, figure style for Stage 1 | nothing |
| `section_analysis.py` | `data/section_polars.csv`, `cfd/geometry/section_v1.csv` | `out/section_*.csv` (7), `out/section_summary.json`; stops if the health-flag split fails its checks |
| `section_figures.py` | `data/section_polars.csv` through `section_lib.py` | `fig/section_*.png` (5) |
| `section_verify.py` | `data/section_polars.csv`, `cfd/geometry/section_v1.{csv,json}` | prints only |
| `rotor_analysis.py` | `data/rotor_static.csv`, `data/rotor_cp.csv`, rig CSVs (below) | `fig/rotor_*.png` (6), `out/rotor_numbers.json` |
| `rotor_verify.py` | the same rotor tables, rig `rotor_speed_by_dwell.csv` | `out/rotor_verify.json` |
| `roughness_analysis.py` | `data/stage2_polars.csv`, `data/section_polars.csv`, report build files (below) | `out/roughness_*.csv` (14), `out/roughness_numbers.json`, `fig/roughness_*.png` (7) |
| `roughness_verify.py` | the same inputs | prints only |
| `team_summary_check.py` | the four tables, report build files (below) | prints only: every number in TEAM_SUMMARY.md, quoted against recomputed, `OK` or `CHECK` |

The `*_verify.py` scripts are independent recomputations. They share no code with the analysis
scripts, and they were used to check every number quoted in RESULTS.md and TEAM_SUMMARY.md.
`team_summary_check.py` (review of 13 Oct) shares no code with either and recomputes every
TEAM_SUMMARY.md number; it ends with the count of `CHECK` lines (0 on 13 Oct).

**Read-only inputs outside this folder:**
- `cfd/geometry/section_v1.csv` and `section_v1.json`;
- `reports/roughness_2026-09/build/numbers.json`;
- `reports/roughness_2026-09/build/tacho/numbers.tex`, `per_dwell.csv` and
  `derived/rotor_speed_by_dwell.csv`;
- `reports/roughness_2026-09/build/derived/comparisons.csv`, `rotor_by_wind_speed.csv`,
  `surface_roughness.csv`, `rotor_speed_by_run.csv` and `run_summary.csv` (the last read only by
  `team_summary_check.py`).

### out/

| File | Contents |
|---|---|
| `section_case_quality.csv` | One row per section case: health indicators (time-step proxy, symptoms) and flag. The column `corrupted` marks a flagged run |
| `section_polar_LM23.csv` | The LM polar at 23 m/s, with flags and frontal widths |
| `section_ratio.csv` | Cd(α 0)/Cd(α 180) on matched pairs, the two-position λ0, the literature ratio |
| `section_speed_tu.csv` | α 0 and 180 against wind speed and Tu (medium, maxCo 5) |
| `section_sst_vs_lm.csv` | Matched SST–LM pairs |
| `section_timestep.csv` | maxCo 5 against 2.5 on the same mesh |
| `section_grid.csv` | Grid study at maxCo 2.5 (Celik et al. 2008): order, extrapolated value, GCI or spread |
| `section_summary.json` | The numbers quoted for Stage 1 |
| `rotor_numbers.json` | Every number in the rotor findings: static means, curves, the drive/common split, time-step check, rig landmarks, resolution |
| `rotor_verify.json` | The independent rotor recomputation |
| `roughness_wf_effects.csv`, `roughness_trends.csv` | Rough-wall-function changes against Ks 0 (drift rule), and trend fits |
| `roughness_tex_effects.csv`, `roughness_tex_sst_minus_lm.csv`, `roughness_tex_D_sst_minus_lm.csv` | Resolved-texture changes, and SST against LM |
| `roughness_drag_difference.csv` | D = Cd(α 0) − Cd(α 180) by Ks and t, with the two-position drive change |
| `roughness_timestep_pairs.csv`, `roughness_timestep_effects.csv` | maxCo 5 against 2.5 (wall function, α 0) |
| `roughness_ksplus_collapse.csv` | α-0 changes against blade-mean Ks+ |
| `roughness_ks_mapping.csv` | Measured surfaces mapped to Ks under four assumed rules |
| `roughness_required_section_change.csv` | Section-drag change needed for each measured gain (two-position model) |
| `roughness_alpha0_states.csv` | Every α-0 case at 23 m/s with its flow state |
| `roughness_measured.csv`, `roughness_measured_by_speed.csv` | Measured peak-power changes (from the report build) |
| `roughness_numbers.json` | Other Stage 2 numbers and quality checks |

### fig/

| Figure | Shows | RESULTS.md |
|---|---|---|
| `section_health.png` | Time-step proxy and force symptoms: 23 flagged runs | §2.2 |
| `section_speed_tu.png` | Cd at α 0 and 180 against wind speed and Tu | §2.3 |
| `section_grid.png` | Grid study (maxCo 2.5) and time-step check (maxCo 5), Cd and St | §2.4 |
| `section_polar.png` | Cd, Cl, Cm against α (LM polar, 23 m/s), SST points, literature | §2.6 |
| `section_strouhal.png` | St against α, with frequencies at 23 m/s | §2.7 |
| `roughness_cd_vs_ks.png` | Cd against Ks at α 0, 90 and 180 (rough wall functions) | §3.2 |
| `roughness_cl_vs_ks.png` | Mean Cl against Ks, same layout | §3.2 |
| `roughness_drag_difference.png` | D against Ks and t, and the measured power change | §3.3 |
| `roughness_texture.png` | Cd against texture amplitude, SST and LM, α 0 and 180 | §3.4 |
| `roughness_speed_sweep.png` | α-0 roughness effect against speed and Ks+ | §3.5 |
| `roughness_ksplus_validity.png` | Ks+ validity, and the measured surfaces mapped to Ks | §3.6 |
| `roughness_alpha0_states.png` | Cd against Cl for every α-0 case: the two flow states | §3.7 |
| `rotor_static_CQ_theta.png` | Static C_Q against azimuth, hypotheses A and B | §4.2 |
| `rotor_cp_lambda_U23.png` | C_P against λ at 23 m/s, with the rig's Plain data | §4.3 |
| `rotor_cq_lambda_U23.png` | C_Q against λ at 23 m/s; drive and common part | §4.3 |
| `rotor_cp_lambda_by_speed.png` | C_P against λ for A at 10.2, 23 and 38 m/s | §4.4 |
| `rotor_lambda_vs_U.png` | λ landmarks against wind speed, CFD and rig | §4.4 |
| `rotor_resolution.png` | Noise of a rough-minus-smooth comparison against the implied signal | §4.6 |

Encoding:
- Smooth blade or Plain: black; roughness: a blue ramp; rig: orange.
- SST: squares with dashed lines; LM: circles with solid lines.
- maxCo 2.5: filled markers; maxCo 5: open markers; a flagged run: a grey ×.

## How to rerun

From the repository root:

```zsh
cd /Users/stepheneacuello/Projects/windtunnel-control
nice -n 10 python3 cfd/analysis/2026-10-13/src/section_analysis.py
nice -n 10 python3 cfd/analysis/2026-10-13/src/section_figures.py
nice -n 10 python3 cfd/analysis/2026-10-13/src/section_verify.py
nice -n 10 python3 cfd/analysis/2026-10-13/src/rotor_analysis.py
nice -n 10 python3 cfd/analysis/2026-10-13/src/rotor_verify.py
nice -n 10 python3 cfd/analysis/2026-10-13/src/roughness_analysis.py
nice -n 10 python3 cfd/analysis/2026-10-13/src/roughness_verify.py
nice -n 10 python3 cfd/analysis/2026-10-13/src/team_summary_check.py
```

- **Requirements.** Python 3 with numpy, pandas and matplotlib. They were checked on 13 Oct with
  `/opt/homebrew/bin/python3`: Python 3.14.8, numpy 2.5.4, pandas 3.0.1, matplotlib 3.11.2.
- **Run time.** Each script takes under 2 s, and all eight together under 8 s. Paths resolve from
  each script's own location, so the scripts can be started from any directory.
- **Reproducibility.** On 13 Oct all seven analysis and verify scripts were rerun. Every file in
  `out/` and `fig/` came out byte-identical to the version before the rerun (checked with `shasum`).
  In the review the same day, three figure labels were aligned with the text: "light-load λ" in
  `rotor_cp_lambda_U23.png` and `rotor_lambda_vs_U.png` (was "highest loaded λ"), and "high-drag
  state" / "low-drag state" in `section_speed_tu.png`. Only those three PNGs changed; every file in
  `out/` stayed byte-identical.
- **Expected warning.** `rotor_verify.py` prints a numpy `RankWarning` from a parabola fit to the
  rig's 35.8 m/s run 1. That fit is not used in any finding.
- **Order.** `section_figures.py` and `section_analysis.py` both use `section_lib.py`. Otherwise the
  scripts are independent of one another.

## After the download

The download into `cfd/*/runs/` and `cfd/*/results/` started on 13 Oct.
- **Refreshing the tables.** After `cfd/hpc/pull_results.py` has rebuilt the stage CSVs, they should
  hold the same 150 cases. To refresh `data/`:
  - copy them in;
  - add the `ran_on` column, `mac` for the 10 cases listed above;
  - rerun the eight scripts;
  - compare `out/` with the present version. Any changed number must be re-checked in RESULTS.md and
    TEAM_SUMMARY.md; `team_summary_check.py` flags each TEAM_SUMMARY.md number that moved.
- **New evidence.** The time histories and fields that the download brings are not used here. The
  checks they enable are listed in RESULTS.md §8.4, item 6.
