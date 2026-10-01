## Rig-run audit: v1 Ra20 / Ra40 / Ra80 (protocol 94bed28333f7)

Everything below comes from scripts in `/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/build/rig_audit/`. `run_all.sh` rebuilds all outputs using the system python3; the repo's `generator_model.py` was run through the repo venv. Nothing in logs/, src/, docs/, data/ or inputs/ was modified.

### 1. Headers and columns

The points header is byte-identical to the summary header in every run (Ra20 7 lines, Ra80 10, Ra40 21). The Ra40 trace header is identical to its summary header.

| key | Ra20 | Ra80 | Ra40 |
|---|---|---|---|
| blade | v1_Ra20 (the file was `v2_Ra20` until commit 9cae976; data unchanged apart from the label and CRLF line endings) | v1_Ra80 | v1_Ra40 |
| notes | PETG, 0.2mm, Ra 20 | PETG, 0.2mm layer, 0.2mm nozzle, Ra 80 | PETG, 0.2mm layer, Ra 40 |
| fan_rpm / wind_mps | 500 / 10.24 (first set point only) | same | same |
| instrument | Chroma,63004-150-60,630041501113,2.01 | same | same |
| protocol / protocol_detail | 94bed28333f7 / scaling=v2;step=0.02000;frac=0;dwell=1.00;voff=0.500;range=low;floor=0;operate=80.0;collapse=0.700;confirm=2 | same | same |
| clock, clock_unix, _clock_note | absent | 2026-08-26T15:32:09-0400 | 2026-09-01T15:12:54-0400 |
| protocol_extra / protocol_full | absent | absent | min_step_amps=0.002;stop_rpm=1800;... / b5ac081ac5c0 |
| instrument_check | absent | absent | ok |
| air_temp_c / pressure / density | absent | absent | 24.63 C / 101043 Pa / 1.1821 (offset NOT SET) |
| drive_actual_signals | absent | absent | 5310=103;5311=104 |
| air_temp_drift_c / air_density_end | absent | absent | +0.12 / 1.1817 |

| column | Ra20 summ | Ra20 pts | Ra80 summ | Ra80 pts | Ra40 summ | Ra40 pts | Ra40 trace |
|---|---|---|---|---|---|---|---|
| fan_rpm_cmd / fan_rpm | x / - | - / x | x / - | - / x | x / - | - / x | - |
| fan_rpm_actual, wind_mps, blade | x | x | x | x | x | x | actual only |
| p_max_w, i_at_pmax_a (raw) | x | | | | | | |
| p_max_fit_w, i_at_pmax_fit_a, p_max_raw_w, i_at_pmax_raw_a | | | x | | x | | |
| v_at_pmax_v, i_last_a, limited_by, clean, steps, stopped_by | x | | x | | x | | |
| turbine_rpm_at_pmax, tsr_at_pmax | | | | | x | | |
| demand_a, held_a, volts, amps, watts, tracking, note, motor_amps | | x | | x | | x | motor_amps |
| t_unix, t_local | | | | x | | x | t_unix, t_rel_s |
| turbine_rpm | | | | | | x | rpm_pulses, rpm_last_us |

Summary wind_mps = f(actual rpm at the end of settle). Points wind_mps = f(commanded rpm). In Ra20 and Ra80, the points fan_rpm_actual and motor_amps hold one end-of-ramp snapshot per set point; Ra40 has a value per dwell.

### 2. P_max rule and recompute

**Source.** `src/peak_finder.py`, unchanged since 7d4dba4 (22 Aug), called from `sweep_core.measure_point` with operate_frac=0.

- **RAW** is the argmax of V·I over ramp dwells. The first (floor) dwell is excluded, and so is any bad dwell (collapsed, lost tracking, or under v_floor). A later sample must be strictly greater to replace the peak.
- **FIT** (`refine(span=2)`) uses the tracking dwells with I>0, including the floor dwell. It finds the first max-watts index k and fits an ordinary least-squares quadratic W(I) in measured current, solved by Cramer's rule, through pts[k-2..k+2]. i_fit = -a1/2a2 and p_fit = W(i_fit).
- **Fallback to raw** happens if there are fewer than 5 points, the window has fewer than 3, |det| < 1e-18, a2 >= 0, or the vertex lies outside [window[0].I, window[-1].I].
- `compare_blades.py` uses the fit only when both runs have it, so every Ra20 comparison so far has been raw.

**Recompute vs logged:**

| run | p_raw | i_raw | v_raw | p_fit | i_fit | steps, i_last | stop text | fallbacks |
|---|---|---|---|---|---|---|---|---|
| Ra20 | 0 | 0 | 0 | not logged | not logged | 0 | 14/14 | 700 (vertex outside window) |
| Ra40 | 0 | 0 | 0 | max 0.00006 W (0.137%, 1500) | 0.0002 A (1.28%, 500) | 0 | 14/14 | 600 (not concave), matches logged |
| Ra80 | 0 | 0 | 0 | max 0.00006 W (0.063%, 1800) | 0.00007 A (0.38%, 500) | 0 | 14/14 | none |

The demand ladders are identical across runs. Measured amps equal demand to 0.0000 A in all 1040 dwells, with no tracking=0 rows and no notes.

| fan | Ra20 raw | **Ra20 fit (new)** | Ra40 raw | Ra40 fit | Ra80 raw | Ra80 fit |
|---|---|---|---|---|---|---|
| 500 | 0.0297 | 0.0296 | 0.0298 | 0.0293 | 0.0330 | 0.0316 |
| 600 | 0.0604 | 0.0591 | 0.0658 | 0.0658* | 0.0660 | 0.0657 |
| 700 | 0.1047 | 0.1047* | 0.1210 | 0.1186 | 0.1180 | 0.1158 |
| 800 | 0.1769 | 0.1762 | 0.1920 | 0.1851 | 0.1925 | 0.1877 |
| 900 | 0.2732 | 0.2743 | 0.2974 | 0.2965 | 0.3079 | 0.3023 |
| 1000 | 0.4227 | 0.4088 | 0.4642 | 0.4532 | 0.5265 | 0.5248 |
| 1100 | 0.6433 | 0.6320 | 0.7510 | 0.7500 | 0.8044 | 0.7990 |
| 1200 | 0.9592 | 0.9542 | 1.0407 | 1.0375 | 1.1009 | 1.0917 |
| 1300 | 1.3286 | 1.3208 | 1.4007 | 1.3820 | 1.4455 | 1.4395 |
| 1400 | 1.6653 | 1.6225 | 1.7740 | 1.7710 | 1.8391 | 1.8170 |
| 1500 | 2.0806 | 2.0454 | 2.1940 | 2.1953 | 2.2569 | 2.2446 |
| 1600 | 2.5188 | 2.4795 | 2.6547 | 2.6427 | 2.8299 | 2.7846 |
| 1700 | 3.0329 | 2.9966 | 3.3576 | 3.3248 | 3.5290 | 3.5181 |
| 1800 | 3.7935 | 3.7217 | 4.0961 | 4.1018 | 4.4981 | 4.4317 |

\* marks a fallback to raw. Rounding uncertainty on the Ra20 fit, by Monte Carlo on 4-dp watts: 95% half-width 0.13% at 500 and 0.07% at 600, under 0.05% above that. On average the fit sits below raw by 1.25% (Ra20), 0.95% (Ra40) and 1.31% (Ra80).

**Pairwise LEVEL.** Geometric-mean ratio over 14 set points matched on commanded rpm, with a t(13) 95% CI on the mean log ratio.

| pair | raw | fit (all recomputed) | fit (logged Ra40/80, Ra20 recomputed) | fit, excluding 600/700 (n=12) |
|---|---|---|---|---|
| Ra40/Ra20 | +8.41% [+6.05, +10.82] 14/14 | +8.74% [+6.11, +11.44] 13/14 | +8.75% [+6.13, +11.43] | +8.16% [+5.20, +11.19] 11/12 |
| Ra80/Ra20 | +13.73% [+10.67, +16.88] 14/14 | +13.67% [+9.95, +17.52] 14/14 | +13.66% [+9.94, +17.51] | +14.13% [+9.75, +18.70] 12/12 |
| Ra80/Ra40 | +4.91% [+2.44, +7.45] 13/14 | +4.53% [+2.06, +7.06] 12/14 | +4.52% [+2.05, +7.05] | +5.53% [+3.12, +7.99] 12/12 |

The compare_blades CIs quoted earlier ([+6.33, +10.49] etc.) use 1.96 times the detrended residual SE, which is a different construction. Per-set-point ratios are in `ratios_by_setpoint.csv`; for example Ra40/Ra20 on the fit basis is -1.28% at 500 and +18.67% at 1100.

### 3. Fan speed and wind

| cmd | Ra20 summ act-cmd | Ra20 pts | Ra20 wind summ | wind from cmd | Ra20 summ vs cmd | Ra20 output Hz (act/29.5) | Ra20 sync-cmd | Ra40 summ / pts | Ra80 summ / pts |
|---|---|---|---|---|---|---|---|---|---|
| 500 | -4 | -4 | 10.14 | 10.24 | -0.938% | 16.81 | +4.4 | 0 / -1,0,+1 | 0 / 0 |
| 600 | -7 | -7 | 12.22 | 12.37 | -1.197% | 20.10 | +3.1 | 0 / 0 | 0 / 0 |
| 700 | -7 | -7 | 14.36 | 14.50 | -0.966% | 23.49 | +4.7 | 0 / 0 | 0 / 0 |
| 800 | -6 | -6 | 16.50 | 16.63 | -0.794% | 26.92 | +7.5 | 0 / 0 | 0 / 0 |
| 900 | -6 | -6 | 18.63 | 18.76 | -0.714% | 30.30 | +9.2 | 0 / 0,+1 | 0 / 0 |
| 1000 | -9 | -9 | 20.71 | 20.90 | -0.890% | 33.59 | +7.8 | 0 / -1,0,+1 | 0 / 0 |
| 1100 | -11 | -8 | 22.78 | 23.03 | -1.077% | 36.92 | +7.5 | 0 / 0,+1 | +1 / 0 |
| 1200 | -11 | -11 | 24.92 | 25.16 | -0.954% | 40.30 | +9.2 | 0 / 0,+1 | 0 / 0 |
| 1300 | -14 | -14 | 27.00 | 27.29 | -1.070% | 43.59 | +7.8 | 0 / 0,+1 | 0 / 0 |
| 1400 | -16 | -14 | 29.07 | 29.42 | -1.203% | 46.92 | +7.5 | 0 / 0,+1 | +1 / 0 |
| 1500 | -16 | -16 | 31.21 | 31.56 | -1.096% | 50.30 | +9.2 | 0 / -1,0,+1 | 0 / +1 |
| 1600 | -19 | -19 | 33.29 | 33.69 | -1.181% | 53.59 | +7.8 | +1 / 0,+1 | 0 / 0 |
| 1700 | -18 | -18 | 35.43 | 35.82 | -1.089% | 57.02 | +10.5 | +1 / 0,+1 | +1 / 0 |
| 1800 | -21 | -21 | 37.50 | 37.95 | -1.191% | 60.30 | +9.2 | 0 / -1,0,+1 | 0 / 0 |

**Why Ra20 shows slip and the later runs do not:**
- **Ra20 (20 Aug, PMC 2.x, pre-git code).** fan_rpm_actual = f2·295, where f2 is register 40005 (par 0103 OUTPUT FREQ) divided by 100, so it is output frequency in 0.1 Hz steps times 29.5 rpm/Hz. All 14 values lie on that 2.95-rpm grid (chance 2.6e-7). The 29.5 = 1770/60 nameplate ratio subtracts rated slip (sync/60 = 8.4 rpm at 500, 30 rpm at 1800) from every reading. The implied synchronous speed is 3-10.5 rpm above the command, i.e. ordinary slip with the shaft at the set point: 9904 = 1 (VECTOR:SPEED) in the 25 Aug snapshot.
- **Ra80 (26 Aug) and Ra40 (1 Sep).** Since commit 465f286 (25 Aug 14:01), PMCTransport serves ACT1 from par 0102 SPEED via RD, which is the drive's regulated speed estimate. It reads the set point: 0/+1 rpm in the summaries, -2..+1 in the Ra40 trace (mean deviation within ±0.23 rpm per set point).
- **5310 did not change.** It was 103 in the 25 Aug 13:31 snapshot and in the Ra40 header, so the header documents register 40005, not the column's source.
- **Motor current agrees.** Ra20 minus Ra80 is within ±0.1 A at all 14 set points. A real 16-21 rpm deficit at 1600-1800 would predict 0.16-0.19 A less current, since the within-run slope is about 0.009 A/rpm.

**Consequence.** Ra20's summary wind is 0.71-1.20% low (mean 1.03%). At n=3.77 that is +2.7 to +4.7% in power at matched wind (1.2% of wind = 4.66% of power). On a wind axis with Ra20's summary wind, the matched-wind Ra40/Ra20 gap is +4.51% instead of +8.44%, and Ra80/Ra20 is +9.26% instead of +13.37% (13 common set points, raw). Pairing on commanded rpm is unaffected.

**Recommendation.** Use one definition in both plots and tables: v = 0.02132·fan_rpm_cmd - 0.424, which is the points files' wind_mps. The calibration (Test 1, 13 Feb) was fitted against set-point rpm.

### 4. Light-load voltage and Thevenin fit

My fit mirrors generator_model.fit and matches the repo tool's printed values at 42/42 set points; the tool outputs are in `generator_model_Ra*_repo.txt`. In the table, V_light is the voltage at the floor dwell; I_light is the same in all runs (1.0 mA at 500 to 10.0 mA at 1800).

| fan | Ra20 V_light / Voc / R | Ra40 V_light / Voc / R | Ra80 V_light / Voc / R |
|---|---|---|---|
| 500 | 2.848 / 3.181 / 88.4 | 2.988 / 3.389 / 94.2 | 2.938 / 3.326 / 88.8 |
| 600 | 4.466 / 4.517 / 87.1 | 4.585 / 4.677 / 84.0 | 4.629 / 4.716 / 85.2 |
| 700 | 5.623 / 5.623 / 73.6 | 5.788 / 5.882 / 74.6 | 5.668 / 5.790 / 72.8 |
| 800 | 6.744 / 6.857 / 67.5 | 6.962 / 6.991 / 63.7 | 6.923 / 7.006 / 64.7 |
| 900 | 7.863 / 7.942 / 58.3 | 8.139 / 8.247 / 59.7 | 8.461 / 8.454 / 60.3 |
| 1000 | 9.194 / 9.332 / 54.9 | 9.943 / 9.779 / 54.2 | 10.339 / 10.314 / 52.2 |
| 1100 | 10.977 / 10.969 / 49.3 | 11.734 / 11.620 / 47.3 | 12.067 / 12.063 / 46.8 |
| 1200 | 12.851 / 12.753 / 44.4 | 13.487 / 13.416 / 44.2 | 13.757 / 13.804 / 44.3 |
| 1300 | 14.566 / 14.536 / 41.4 | 15.212 / 15.043 / 41.3 | 15.413 / 15.310 / 41.6 |
| 1400 | 16.406 / 16.082 / 39.6 | 16.766 / 16.470 / 38.4 | 17.380 / 16.794 / 38.5 |
| 1500 | 18.114 / 17.497 / 36.8 | 18.565 / 18.298 / 37.7 | 19.202 / 18.784 / 38.4 |
| 1600 | 20.094 / 19.416 / 36.6 | 20.900 / 20.216 / 37.2 | 21.249 / 20.760 / 37.9 |
| 1700 | 21.708 / 21.255 / 36.2 | 22.337 / 22.162 / 36.6 | 23.327 / 22.853 / 37.1 |
| 1800 | 23.917 / 23.502 / 36.5 | 24.345 / 23.973 / 34.4 | 26.420 / 25.681 / 36.9 |

Per-set-point differences (%):

| fan | Ra40/Ra20 V_light / Voc / R / P_fit | Ra80/Ra20 V_light / Voc / R / P_fit | Ra80/Ra40 V_light / Voc / R / P_fit |
|---|---|---|---|
| 500 | +4.93 / +6.53 / +6.65 / -1.28 | +3.16 / +4.54 / +0.45 / +6.55 | -1.69 / -1.87 / -5.81 / +7.93 |
| 600 | +2.66 / +3.54 / -3.53 / +11.41 | +3.65 / +4.40 / -2.20 / +11.28 | +0.96 / +0.83 / +1.38 / -0.12 |
| 700 | +2.93 / +4.61 / +1.34 / +13.24 | +0.80 / +2.96 / -1.09 / +10.55 | -2.07 / -1.57 / -2.40 / -2.37 |
| 800 | +3.23 / +1.96 / -5.68 / +5.08 | +2.65 / +2.17 / -4.14 / +6.58 | -0.56 / +0.21 / +1.64 / +1.43 |
| 900 | +3.51 / +3.84 / +2.36 / +8.07 | +7.60 / +6.44 / +3.30 / +10.21 | +3.96 / +2.50 / +0.92 / +1.98 |
| 1000 | +8.14 / +4.79 / -1.33 / +10.87 | +12.45 / +10.53 / -4.82 / +28.38 | +3.99 / +5.47 / -3.54 / +15.79 |
| 1100 | +6.90 / +5.94 / -4.14 / +18.67 | +9.93 / +9.97 / -5.15 / +26.42 | +2.84 / +3.81 / -1.05 / +6.53 |
| 1200 | +4.95 / +5.19 / -0.36 / +8.73 | +7.05 / +8.24 / -0.15 / +14.41 | +2.01 / +2.89 / +0.21 / +5.23 |
| 1300 | +4.44 / +3.49 / -0.37 / +4.63 | +5.82 / +5.33 / +0.52 / +8.98 | +1.33 / +1.78 / +0.89 / +4.15 |
| 1400 | +2.19 / +2.41 / -2.89 / +9.15 | +5.94 / +4.43 / -2.64 / +11.99 | +3.67 / +1.97 / +0.26 / +2.60 |
| 1500 | +2.49 / +4.58 / +2.57 / +7.33 | +6.00 / +7.36 / +4.54 / +9.74 | +3.43 / +2.66 / +1.92 / +2.25 |
| 1600 | +4.01 / +4.12 / +1.52 / +6.58 | +5.75 / +6.92 / +3.49 / +12.30 | +1.67 / +2.69 / +1.94 / +5.37 |
| 1700 | +2.90 / +4.26 / +1.01 / +10.95 | +7.46 / +7.52 / +2.25 / +17.40 | +4.43 / +3.12 / +1.22 / +5.82 |
| 1800 | +1.79 / +2.00 / -5.62 / +10.21 | +10.47 / +9.27 / +1.34 / +19.08 | +8.52 / +7.12 / +7.37 / +8.04 |

Summary (geometric mean, t 95% CI, set points higher):

| quantity | Ra40/Ra20 | Ra80/Ra20 | Ra80/Ra40 |
|---|---|---|---|
| V_light | +3.92% [+2.88,+4.96] 14/14 | +6.29% [+4.46,+8.15] 14/14 | +2.29% [+0.71,+3.88] 11/14 |
| Voc (all points) | +4.08% [+3.30,+4.87] 14/14 | +6.40% [+4.93,+7.90] 14/14 | +2.23% [+0.84,+3.64] 12/14 |
| R_int (all points) | -0.66% [-2.66,+1.38] 6/14 | -0.35% [-2.16,+1.49] 7/14 | +0.31% [-1.44,+2.09] 10/14 |
| Voc / R (pre-peak points only) | +4.25% / +0.36% | +6.56% / +0.55% | +2.22% / +0.19% |
| dlnP_fit = 2dlnVoc + (-dlnR), log-% | 8.38 = 8.00 + 0.66 | 12.81 = 12.42 + 0.36 | 4.43 = 4.41 - 0.31 |

**Model check.** Voc²/4R reproduces p_fit to a mean of -0.45%, -0.16% and -0.52% by run, and to within ±4.8% at every set point.

**What drives the difference.** It comes through Voc, not R: 92% (Ra40/Ra20) and 97% (Ra80/Ra20) of the log-power gain. At 1-10 mA the I·R drop is 1.5-3% of V and the same across blades. With the same generator, a higher V_light means the rougher rotors turned about 3.9% (Ra40) and 6.3% (Ra80) faster at light load at the same commanded fan speed. Apparent R includes rotor droop (docs/11), so an unchanged R means the combined electrical-plus-droop slope did not change.

**Alternative: a stronger wind on later days.** This cannot be excluded, because no run measured wind independently. Density differences alone would move P_max but, to first order, not light-load speed. A model-dependent check uses the within-run R ~ v^-0.791. Under that model, the wind offset implied by Voc predicts dlnR of -2.11% for Ra40/Ra20; the observed -0.66% [-2.70, +1.37] does not decide. For Ra80/Ra20 it predicts -3.28%, and the observed -0.36% [-2.19, +1.48] excludes that.

### 5. Run facts and test order

| | Ra20 | Ra80 | Ra40 |
|---|---|---|---|
| date (docs / t_unix) | 20 Aug 2026 (docs 07/09) | 26 Aug | 1 Sep |
| first to last dwell | not recorded | 15:24:10-15:32:01 (471.0 s) | 15:04:49-15:12:46 (477.5 s); trace 15:04:25-15:12:50 |
| header clock | none | 15:32:09 (+8.0 s after last dwell) | 15:12:54 (+8.0 s) |
| dwells | 336 | 352 | 352 |
| clean / limited_by | 14×1 / power-rolloff | same | same |
| tracking=0 rows / notes | 0 / 0 | 0 / 0 | 0 / 0 |
| motor_amps | 4.6-13.6 | 4.5-13.6 | 4.4-13.8 |

- Dwell period: median 1.055 s (range 1.049-1.199). Gap between set points: 7.4-11.8 s.
- Motor current per set point: Ra20 minus Ra80 is -0.1..+0.1 A, and Ra20 minus Ra40 is -0.1..+0.1 A.
- **Order check.** Raw power follows Ra20<Ra40<Ra80 at 13/14 set points (not at 700) and follows test-date order (Ra20<Ra80<Ra40) at 1/14. Mean ranks in date order: 1.00, 2.93, 2.07. The fit basis gives 11/14 and 2/14. So there is no monotonic drift with date.
- **Confounds for Ra20.** It is the first run and the only one before PMC 3.0/v4/v5 and the 25 Aug drive-profile restore and readback change. It was written by pre-git code.
- **Confound for Ra40.** It is the only run with rotor pulses on record, so a magnet was on a blade.
- **Mountings.** Each blade was mounted once. The Ra80 vs Ra40 contrast (+4.91% raw / +4.53% fit) is the cleanest.

### 6. Ra40 turbine_rpm

| fan | median | min | max | CV % | Spearman(rpm, I) | p | V_light / rpm (mV/rpm) | summary TSR@Pmax |
|---|---|---|---|---|---|---|---|---|
| 500 | 7717 | 213 | 12102 | 51.6 | -0.12 | 0.65 | 0.314 | 8.60 |
| 600 | 6272 | 438 | 12765 | 46.8 | -0.37 | 0.09 | 0.692 | 5.85 |
| 700 | 7282 | 2573 | 14071 | 42.8 | +0.03 | 0.89 | 0.494 | 5.24 |
| 800 | 6721 | 2082 | 11999 | 39.1 | 0.00 | 1.00 | 0.814 | 4.69 |
| 900 | 7184 | 2030 | 11900 | 35.4 | +0.16 | 0.46 | 2.728 | 3.04 |
| 1000 | 8323 | 1658 | 13631 | 31.9 | -0.34 | 0.11 | 1.014 | 6.90 |
| 1100 | 8635 | 357 | 12058 | 41.3 | -0.10 | 0.62 | 1.086 | 0.28 |
| 1200 | 8392 | 4845 | 12799 | 23.2 | -0.14 | 0.48 | 1.617 | 3.13 |
| 1300 | 9241 | 443 | 13658 | 28.2 | -0.41 | 0.03 | 1.513 | 2.73 |
| 1400 | 9442 | 4813 | 13882 | 21.8 | -0.36 | 0.05 | 1.279 | 3.52 |
| 1500 | 10023 | 2513 | 15844 | 28.6 | -0.05 | 0.82 | 2.558 | 3.88 |
| 1600 | 10436 | 4962 | 16543 | 25.5 | -0.11 | 0.57 | 2.258 | 4.14 |
| 1700 | 10360 | 909 | 13690 | 24.8 | -0.20 | 0.32 | 2.091 | 2.74 |
| 1800 | 8199 | 42 | 11474 | 61.3 | -0.54 | 0.003 | 3.187 | 1.18 |

- **Scatter.** Adjacent-dwell |dln rpm| has a median of 26% and a 90th percentile of 104%. There are 2 blank values at 1800.
- **Trace pulse rate.** 95-172 counts/s over each ramp, and 70-90% of ticks see no new pulse.
- **Why the reading is wrong.** A generator constant should be flat, but V/rpm varies 10.1x. Rotor speed should fall with load, but it does so significantly at only 2/14 set points. The pattern is consistent with docs/11: extra counts from bounce or a floating input at low speed, and a reed rated 20 Hz that cannot follow the rotor at high speed.
- **Verdict.** Unusable for per-dwell speed, TSR or Cp(λ). Use light-load voltage as the relative rotor-speed proxy.