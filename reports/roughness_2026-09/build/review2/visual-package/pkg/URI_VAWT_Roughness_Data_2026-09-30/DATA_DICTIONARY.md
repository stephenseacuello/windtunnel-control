# Data dictionary

Units are SI throughout (V, A, W, m/s). Fan and rotor speeds are in rpm.

---

## 1_rig_sweeps/: automated sweeps (raw)

Each file starts with `#` header lines (`key,value`) followed by an ordinary CSV table. Read
it with, for example, `pandas.read_csv(path, comment="#")`.

### Header lines

| key | in | meaning |
|---|---|---|
| `blade` | all | Rotor name, `<geometry>_Ra<label>`. |
| `notes` | all | Free text typed by the operator. **Not reliable for print settings.** The "0.2mm layer" / "0.2mm nozzle" entries record intent (only 0.4 mm nozzles were available; 0.08 mm layers were reported). "0.2mm" is not the fuzzy-skin thickness (0.050 / 0.101 / 0.202 mm). See report §2. |
| `fan_rpm`, `wind_mps` | all | The first set point of the run (500 rpm). Not a run-wide value; ignore. |
| `instrument` | all | Electronic-load identity string (Chroma 63004-150-60, serial number, firmware). |
| `protocol` | all | Fingerprint of every setting that changes what a number means. **`94bed28333f7` in every run.** |
| `protocol_detail` | all | The settings behind the fingerprint: step scaling, step size at 1800 rpm, dwell, cut-out voltage, current range, and so on. |
| `clock`, `clock_unix` | Ra40, Ra80 | Host wall clock when the header was written, **at the end of the run** (about 8 s after the last dwell). The `_clock_note` text saying "run start" is wrong. Use the per-row `t_unix`. |
| `protocol_extra`, `protocol_full` | Ra40 | Ladder and settle settings, with a second fingerprint (later software). |
| `instrument_check` | Ra40 | Result of the pre-run check of the load's identity (`ok`). |
| `air_temp_c`, `air_pressure_pa`, `air_density_kg_m3` | Ra40 | Ambient air at the start, from the tunnel node. The temperature sensor self-heats and its offset was not calibrated (`air_temp_offset`), so the temperature reads high. |
| `air_temp_drift_c`, `air_density_end` | Ra40 | Change over the run, and density at the end. |
| `drive_actual_signals` | Ra40 | The drive's Modbus register mapping (par 5310/5311: signals 103 OUTPUT FREQ, 104 CURRENT). **It does not describe this run's `fan_rpm_actual`.** From 25 Aug the software read the drive's speed estimate (par 0102) directly. The output-frequency path is what the Ra20 readback used. |
| `_clock_note`, `_air_note`, `air_temp_offset` | Ra40, Ra80 | Explanatory notes written by the software. |

### `sweep_<rotor>_summary.csv`: one row per fan set point

| column | meaning |
|---|---|
| `fan_rpm_cmd` | Fan speed commanded: 500, 600 … 1800 rpm. |
| `fan_rpm_actual` | Fan speed reported by the drive once settled. Ra20: output frequency × 29.5, which reads 4–21 rpm below the command. Ra40, Ra80: the drive's speed estimate, within 1 rpm of the command. |
| `wind_mps` | `0.02132 × fan_rpm_actual − 0.424`: the tunnel calibration applied to the reported speed. For Ra20 this reads 0.7–1.2% low; use `3_derived/…wind_mps_nominal`. |
| `blade` | Rotor name. |
| `p_max_w`, `i_at_pmax_a` | *(Ra20 only)* Raw arg max: the largest single 1 s dwell power (W) and its current (A). |
| `p_max_fit_w`, `i_at_pmax_fit_a` | *(Ra40, Ra80)* Peak from a parabola through the arg max ± 2 dwells (W, A). |
| `p_max_raw_w`, `i_at_pmax_raw_a` | *(Ra40, Ra80)* Raw arg max (W, A). |
| `v_at_pmax_v` | Terminal voltage at the raw arg max (V). |
| `i_last_a` | Largest sustained current reached on the ladder (A). |
| `limited_by`, `clean`, `stopped_by` | Why the ladder stopped. Every row here is `power-rolloff`, `clean = 1`, stopped past the peak. |
| `steps` | Number of dwells in the ladder. |
| `turbine_rpm_at_pmax`, `tsr_at_pmax` | *(Ra40 only)* Reed-switch rotor speed at the peak, and the implied tip-speed ratio. **Unusable** (the switch bounces). |

### `sweep_<rotor>_points.csv`: one row per 1 s dwell

| column | meaning |
|---|---|
| `t_unix`, `t_local` | End of the dwell *(Ra40, Ra80; Ra20 predates timestamps)*. |
| `fan_rpm` | Commanded fan speed for this ladder (rpm). |
| `wind_mps` | `0.02132 × fan_rpm − 0.424`, i.e. from the **commanded** speed. |
| `blade` | Rotor name. |
| `demand_a` | Constant-current demand sent to the load (A). |
| `held_a` | Current the load reported holding (A). |
| `volts`, `amps`, `watts` | **The primary measurements:** terminal voltage (V), current (A) and their product (W) at the end of the dwell. |
| `tracking` | 1 if the load's current tracked the demand. Only tracking dwells are used. |
| `note` | Per-dwell annotation (empty in these runs). |
| `fan_rpm_actual`, `motor_amps` | Drive-reported fan speed and fan motor current. Ra20 and Ra80: one settled reading, repeated for the whole ladder. Ra40: the drive state at each dwell. |
| `turbine_rpm` | *(Ra40 only)* Reed-switch rotor speed over the dwell. **Unusable.** |

### `sweep_v1_Ra40_trace.csv`: continuous telemetry (about 16 Hz)

| column | meaning |
|---|---|
| `t_unix`, `t_rel_s` | Host time, and seconds from the start of the trace. |
| `fan_rpm_actual`, `motor_amps` | Drive-reported fan speed and motor current. |
| `rpm_pulses` | Cumulative reed-switch pulse count (bounces included). |
| `rpm_last_us` | The controller's `micros()` timestamp at the last accepted pulse. Difference consecutive rows for pulse intervals. |

---

## 2_jeong_lab/: Jeong-lab tests (raw, as e-mailed)

### `2026-07-27_no_texture_baseline/Summary_Table.csv`

The recipe that reproduces every value from the raw export is in report Appendix C.

| column | meaning |
|---|---|
| `Setting_RPM` | Fan set point (rpm). |
| `Measured_RPM` | Rotor speed from a once-per-revolution pulse, counted over the window. Double counts give about +4% and +3% at 900 and 1300 rpm, and missed pulses give −10.9% at 2000 rpm (true ≈ 667 rpm). Clean at 1900 rpm and below otherwise. |
| `Wind_Speed_ms` | Looked up from the fan setting. The lab calibration differs from the rig's by up to 4.4%. |
| `Vdc_max`, `Idc_max`, `Pdc_max` | Separate maxima, over a 10.4 s window, of the raw 360 Hz samples of V, I and V·I. **At 500–700 rpm no load current was drawn**, so the power there reflects channel noise. |

### `2026-06-05_initial_reference/Summary_Table_Part1_MAX.csv`

Same column names as the July table, processed differently. The values fall on the grid that
maxima of **50-sample averages** produce, with a calibrated current zero; T. Kang can confirm.
Load current was drawn at every setting. The raw export is not in this package.

### `2026-07-27_no_texture_baseline/0727windturbine.csv`: raw DAQ export, 360 Hz

The five channel columns are all headed `Volt`. The mapping below is **inferred from the data**
(it reproduces the lab's table exactly) and should be confirmed against the lab's wiring.

| column (position) | inferred meaning | scale |
|---|---|---|
| `Relative Time` | Seconds from the start; sample interval 1/360 s. | – |
| `Date`, `Time Stamp UTC` | Wall-clock stamps, quantised in 3 ms steps; use `Relative Time`. | – |
| 1st `Volt` | DC bus voltage through a 4:1 divider. | V_dc = 4 × ch1 |
| 2nd `Volt` | DC current channel (Hall sensor, mid-rail zero). | I_dc = 2 × (ch2 − 2.5) as processed by the lab. Zero measured after load-off: 2.4963 V (median). |
| 3rd `Volt` | Once-per-revolution rotor pulse. | 1 pulse = 1 revolution |
| 4th, 5th `Volt` | The same pulse train at lower gain. | – |
| `Chn 1 Events` | Empty. | – |

---

## 3_derived/: generated for the report

These tables are regenerated by `6_code/build_report.py` into `rebuilt/derived/`.

### `peak_power_all_rotors.csv`: one row per rotor and fan set point

| column | meaning |
|---|---|
| `rotor` | Rotor name. |
| `ra_label_um` | Ra label (µm). **Not measured.** |
| `fuzzy_skin_mm` | Fuzzy-skin thickness: **the texture variable**. |
| `test_date`, `mounting` | Date of the run; `original` or `remount`. |
| `fan_rpm_cmd`, `fan_rpm_logged` | Commanded and drive-reported fan speed (rpm). |
| `wind_mps_nominal` | Calibration applied to the **commanded** speed; the report's wind axis. |
| `wind_mps_logged` | The summary file's own `wind_mps`. |
| `p_max_raw_w`, `i_at_p_max_raw_a`, `v_at_p_max_raw_v` | Raw arg max power (W), with its current (A) and voltage (V). |
| `p_max_fit_w`, `i_at_p_max_fit_a` | Parabolic-fit peak (W) and its current (A), by the rig's rule applied to every run. |
| `fit_points` | Dwells used in the fit. 0 means the fit fell back to the arg max (Ra20 at 700, Ra40 at 600). |
| `v_first_step_v`, `i_first_step_a` | Voltage (V) and current (A) at the first, lightest dwell. |
| `n_steps`, `limited_by`, `clean` | Ladder length and stop reason. |

### `thevenin_by_setpoint.csv`

Per rotor and set point, V = V_oc − I·R_int is fitted by least squares over the tracking
dwells.

| column | meaning |
|---|---|
| `rotor`, `fuzzy_skin_mm`, `fan_rpm_cmd`, `wind_mps_nominal` | As above. |
| `v_oc_v` | Zero-current intercept (V). It tracks rotor speed at light load. |
| `r_int_ohm` | Apparent source resistance (Ω): winding, rectifier, wiring and rotor slowing under load. |
| `r2`, `n_steps_fitted` | Fit quality, and the number of dwells fitted. |
| `p_thevenin_match_w` | V_oc² / 4R_int (W). |

### `paired_comparisons.csv`

One row per comparison at the 14 matched set points.

| column | meaning |
|---|---|
| `baseline`, `candidate`, `basis` | Rotors compared, and the P_max estimator (`raw_argmax` or `parabolic_fit`). |
| `n_setpoints` | Matched set points (14). |
| `change_pct` | 100·(exp(mean ln(P_cand/P_base)) − 1): the geometric-mean change. |
| `ci95_lo_pct`, `ci95_hi_pct` | 95% interval assuming independent set points (t, 13 dof). |
| `ci95_ar1_lo_pct`, `ci95_ar1_hi_pct` | 95% interval allowing for lag-1 autocorrelation between neighbouring set points. |
| `lag1_autocorr` | Lag-1 autocorrelation of the log-ratios, ordered by set point. |
| `setpoints_higher` | Set points where the candidate is higher. These are not independent replications. |
| `delta_n`, `delta_n_ci95_half` | Slope of the log-ratio against ln v (the change in power-law exponent), and its 95% half-width. |

None of these intervals includes mount-to-mount variation.

### `power_law_fits.csv`

P_max = a·vⁿ, fitted to log P_max against log of the nominal wind speed.

| column | meaning |
|---|---|
| `rotor`, `fuzzy_skin_mm`, `basis` | As above. |
| `exponent_n`, `exponent_ci95_lo`, `exponent_ci95_hi` | Exponent n and its 95% interval. |
| `coefficient_a` | a, in W/(m/s)ⁿ. |
| `r2_log`, `r2_linear` | R² in log space and in linear space. |

### `jeong_0727_reprocessed_by_setting.csv`

The 27 Jul test reprocessed in the lab's own windows (report §6 and Appendix C). **Use only
rows with `usable_for_rig_comparison` = 1.**

| column | meaning |
|---|---|
| `setting_rpm`, `lab_wind_mps` | Fan setting, and the lab's wind speed for it. |
| `lab_pdc_max_w` | The lab's tabulated `Pdc_max`. |
| `repro_pdc_max_w`, `repro_vdc_max_v`, `repro_idc_max_a` | The lab's recipe re-run. These equal the table to floating-point precision. |
| `i_spike_at_pmax_a` | Current at the lab's `Pdc_max` sample, minus its 1 s mean: the noise the maximum picked up (A). |
| `p_1s_max_zc_w` | **Reprocessed power:** maximum of the 1 s moving mean of V·I, with the current zeroed at 2.4963 V (W). |
| `p_mean_zc_w`, `i_mean_zc_a`, `v_mean_v` | Window means of power, zeroed current and voltage. |
| `t_start_s`, `t_end_s` | Window bounds, in `Relative Time` seconds. |
| `rig_v1_Ra*_p_raw_w` | The rig's raw arg max at the same fan set point. |
| `ratio_1s_to_Ra20` | `p_1s_max_zc_w` divided by the rig's Ra20 value. Blank below 900 rpm. |
| `usable_for_rig_comparison` | 0 for 500–800 rpm (load off, or mostly spin-up) and for 1300 rpm (window contains the step to 1400 rpm); otherwise 1. |
| `window_note` | Why a row is flagged. |

These values are **derived**, not the lab's own numbers. The lab's current scale (2 A/V) is
unverified, and every lab power scales with it.
