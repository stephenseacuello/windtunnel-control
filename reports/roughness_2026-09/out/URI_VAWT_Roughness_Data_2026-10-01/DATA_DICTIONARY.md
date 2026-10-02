# Data dictionary

Units are SI throughout (V, A, W, m/s). Fan and rotor speeds are in rpm.

---

## 1_rig_sweeps/: automated sweeps (raw)

One folder per test date. Run names are `v1_<label>` for the first run of a rotor and
`v1_<label>[_repeat]_20261001` for the 1 Oct runs (`_repeat` = second run, same mounting). Each file
starts with `#` header lines (`key,value`) followed by an ordinary CSV table; read it with, for
example, `pandas.read_csv(path, comment="#")`.

### Header lines

| key | in | meaning |
|---|---|---|
| `blade` | all | Run name. The 20 Aug run was first logged as `v2_Ra20` and relabelled `v1_Ra20` on 25 Aug to match the geometry tested; only the label and line endings changed. |
| `notes` | all | Free text typed by the operator. **Not reliable for print settings.** "PETG", "0.2mm layer" and "0.2mm nozzle" conflict with the slicer file (PLA, 0.10 mm layers, 0.2 mm nozzle) and the printer's account (0.4 mm nozzle); "0.2mm" is not the fuzzy-skin thickness. Measured layer periods are in `4_derived/surface_roughness.csv`. |
| `fan_rpm`, `wind_mps` | all | The first set point of the run (500 rpm). Not a run-wide value; ignore. |
| `instrument` | all | Electronic-load identity string (Chroma 63004-150-60, serial, firmware). |
| `protocol` | all | Fingerprint of every setting that changes what a number means. **`94bed28333f7` in every run.** |
| `protocol_detail` | all | The settings behind the fingerprint: step scaling, step at 1800 rpm, dwell, cut-out voltage, current range. |
| `clock`, `clock_unix` | all but 20 Aug | Host wall clock when the header was written, **at the end of the run** (about 8 s after the last dwell). The `_clock_note` saying "run start" is wrong. Use the per-row `t_unix`. |
| `protocol_extra`, `protocol_full` | 1 Sep, 1 Oct | Ladder and settle settings, with a second fingerprint. |
| `instrument_check` | 1 Sep, 1 Oct | Pre-run check of the load's identity (`ok`). |
| `air` | 1 Oct | `not recorded — no tunnel node connected`. |
| `air_temp_c`, `air_pressure_pa`, `air_density_kg_m3`, `air_temp_drift_c`, `air_density_end` | 1 Sep | Ambient air from the tunnel node. The temperature sensor self-heats and its offset was not calibrated, so it reads high. |
| `drive_actual_signals` | 1 Sep, 1 Oct | The drive's Modbus register mapping. **It does not describe `fan_rpm_actual`**, which from 25 Aug is the drive's speed estimate (par 0102). |
| `_clock_note`, `_air_note`, `air_temp_offset` | some | Notes written by the software. |

### `sweep_<run>_summary.csv`: one row per fan set point

| column | meaning |
|---|---|
| `fan_rpm_cmd` | Fan speed commanded: 500, 600 … 1800 rpm. |
| `fan_rpm_actual` | Fan speed reported by the drive once settled. 20 Aug: output frequency × 29.5, which reads 4–21 rpm low. Later runs: the drive's speed estimate, within 1 rpm of the command. |
| `wind_mps` | Tunnel calibration `0.02132 × fan_rpm_actual − 0.424`. Use `4_derived/…wind_mps_nominal` instead. |
| `blade` | Run name. |
| `p_max_w`, `i_at_pmax_a` | *(20 Aug only)* Raw arg max: largest single 1 s dwell power (W) and its current (A). |
| `p_max_raw_w`, `i_at_pmax_raw_a` | Raw arg max (W, A). |
| `p_max_fit_w`, `i_at_pmax_fit_a` | Peak of a parabola through the arg max ± 2 dwells (W, A). |
| `v_at_pmax_v` | Terminal voltage at the raw arg max (V). |
| `i_last_a` | Largest current reached on the ladder (A). |
| `limited_by`, `clean`, `stopped_by` | Why the ladder stopped. `power-rolloff` (`clean = 1`): power fell below 80% of its maximum. `load-cutout` (`clean = 0`, two rows on 1 Oct): terminal voltage fell below the load's floor after the peak. |
| `steps` | Number of dwells in the ladder. |
| `turbine_rpm_at_pmax`, `tsr_at_pmax` | Reed-switch rotor speed and tip-speed ratio. **Unusable** on 1 Sep (switch bounce); empty on 1 Oct. |

### `sweep_<run>_points.csv`: one row per 1 s dwell

| column | meaning |
|---|---|
| `t_unix`, `t_local` | End of the dwell (not in the 20 Aug file). |
| `fan_rpm` | Commanded fan speed for this ladder (rpm). |
| `wind_mps` | Calibration applied to the **commanded** speed. |
| `blade` | Run name. |
| `demand_a`, `held_a` | Constant-current demand sent to the load, and the current it reported holding (A). |
| `volts`, `amps`, `watts` | **The primary measurements:** terminal voltage (V), current (A) and their product (W) at the end of the dwell. |
| `tracking` | 1 if the load's current tracked the demand. Only tracking dwells are used. |
| `note` | Per-dwell annotation; `under v_floor` marks the dwells that triggered a `load-cutout`. |
| `fan_rpm_actual`, `motor_amps` | Drive-reported fan speed and fan motor current (0.1 A resolution). 20 and 26 Aug: one settled reading repeated for the ladder. Later: read at each dwell. |
| `turbine_rpm` | Reed-switch rotor speed. Unusable or empty. |

### `sweep_<run>_trace.csv`: continuous telemetry (about 16–19 Hz; 1 Sep and 1 Oct)

| column | meaning |
|---|---|
| `t_unix`, `t_rel_s` | Host time, and seconds from the start of the trace. |
| `fan_rpm_actual`, `motor_amps` | Drive-reported fan speed and motor current. |
| `rpm_pulses`, `rpm_last_us` | Reed-switch pulse count and the controller's `micros()` at the last pulse. Not usable. |

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

## 3_surface_scans/: Keyence VR-6000 height maps (raw, 1 Oct)

| file | blade set |
|---|---|
| `baseline_Height.csv`, `baseline.png` | `v1_smooth` (no texture) |
| `20 1_Height.csv`, `20.png` | `v1_Ra20` |
| `40 1_Height.csv`, `40.png` | `v1_Ra40` |
| `801_Height.csv`, `80 1.png`; `80 2_Height.csv`, `80 2.png` | `v1_Ra80`, two fields |

Each CSV starts with quoted `key,value` lines (instrument, magnification, `XY Calibration`
= 1.853 µm per pixel, image size 1053 × 769, `Unit` = mm), then a line `"Height"`, then the
height map: one CSV row per image row, heights in **mm** (1 µm resolution), blank where the
instrument had no return. Image rows run spanwise on the blade, across the layer lines. The
PNGs are the instrument's screenshots of the same fields. `7_code/keyence.py` reads the CSVs.

---

## 4_derived/: generated for the report

Regenerated by `7_code/build_report.py` into `rebuilt/derived/`. Run names as in
`1_rig_sweeps/`. `run_on_date` is 1 or 2 within a test date; on 1 Oct both runs share one
mounting.

### `oct1_vs_no_texture.csv`: the result (report Table 1)

| column | meaning |
|---|---|
| `rotor`, `runs` | Textured rotor, and its number of 1 Oct runs. |
| `change_vs_no_texture_pct` | Mean over 14 set points of ln(P_max / P_ref), averaged over the rotor's runs, as a percentage change. P_ref is the geometric mean of the two no-texture runs at that set point. |
| `ci95_with_mounting_lo_pct`, `ci95_with_mounting_hi_pct` | **The headline 95% interval**: includes mounting variation estimated from the Aug/Sep runs (t, 3 dof; report Appendix B). |
| `ci95_run_to_run_lo_pct`, `ci95_run_to_run_hi_pct` | 95% interval from run-to-run repeatability only (pooled SD, t, 4 dof). |
| `p_max_1800rpm_w` | P_max at 1800 rpm, geometric mean of the runs (W). |

### `oct1_by_run.csv`: every 1 Oct run (report Fig. 3)

| column | meaning |
|---|---|
| `rotor`, `fuzzy_skin_mm`, `run`, `repeat` | Rotor, texture, run name, run number (1 or 2, same mounting). |
| `run_start`, `run_end` | Local time of the first and last dwell. |
| `change_vs_no_texture_pct` | That run's mean change against P_ref, as above. |

### `surface_roughness.csv` (report Section 1.1)

| column | meaning |
|---|---|
| `rotor`, `fuzzy_skin_mm`, `scans`, `profiles` | Blade set, texture, fields scanned, profiles analysed. |
| `Pa_um` | Mean absolute deviation of each levelled spanwise profile, averaged over profiles (µm). |
| `Ra_lc025_um` | The same after an ISO 16610-21 Gaussian filter, λc = 0.25 mm (µm). Describes texture finer than 0.25 mm only; ISO 4288 would choose longer cut-offs for the no-texture and Ra80 surfaces than the 1.43 mm field allows. |
| `dominant_wavelength_um` | Peak of the mean profile spectrum between 60 and 320 µm: the layer period where one is visible. **Ra80 has no distinct period**; its value is the mean of two fields' spectral maxima and is not a layer period. |
| `Pa_scan_spread_um`, `Ra_scan_spread_um` | Difference between the two Ra80 fields. |

### `peak_power_all_rotors.csv`: one row per run and fan set point

| column | meaning |
|---|---|
| `rotor`, `test_date`, `run_on_date` | Run name, date, run number on that date. |
| `ra_label_um` | Ra label (µm). **A name, not a measurement.** |
| `fuzzy_skin_mm` | Fuzzy-skin thickness: **the texture variable**. |
| `fan_rpm_cmd`, `fan_rpm_logged` | Commanded and drive-reported fan speed (rpm). |
| `wind_mps_nominal` | Calibration applied to the **commanded** speed; the report's wind axis. |
| `wind_mps_logged` | The summary file's own `wind_mps`. |
| `p_max_raw_w`, `i_at_p_max_raw_a`, `v_at_p_max_raw_v` | Raw arg max power (W), with its current (A) and voltage (V). |
| `p_max_fit_w`, `i_at_p_max_fit_a` | Parabolic-fit peak (W) and its current (A), by the rig's rule. |
| `fit_points` | Dwells used in the fit; 0 means the fit fell back to the arg max. |
| `v_first_step_v`, `i_first_step_a` | Voltage (V) and current (A) at the first, lightest dwell. |
| `n_steps`, `limited_by`, `clean` | Ladder length and stop reason. |

### `thevenin_by_setpoint.csv`

Per run and set point, V = V_oc − I·R_int fitted by least squares over the tracking dwells.

| column | meaning |
|---|---|
| `rotor`, `test_date`, `run_on_date`, `fuzzy_skin_mm`, `fan_rpm_cmd`, `wind_mps_nominal` | As above. |
| `v_oc_v` | Zero-current intercept (V). It tracks rotor speed at light load. |
| `r_int_ohm` | Apparent source resistance (Ω): winding, rectifier, wiring and rotor slowing under load. |
| `r2`, `n_steps_fitted` | Fit quality, and the number of dwells fitted. |
| `p_thevenin_match_w` | V_oc² / 4R_int (W). |

### `jeong_0727_reprocessed_by_setting.csv`

The 27 Jul test reprocessed in the lab's own windows (report Section 4 and Appendix C). **Use only
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
| `rig_v1_Ra*_p_raw_w` | The rig's raw arg max at the same fan set point (first run of each textured rotor). |
| `ratio_1s_to_Ra20` | `p_1s_max_zc_w` divided by the rig's Ra20 value. Blank below 900 rpm. |
| `rig_no_texture_1oct_p_raw_w` | The rig's un-textured rotor on 1 Oct: geometric mean of its two runs (W). |
| `ratio_1s_to_no_texture` | `p_1s_max_zc_w` divided by that. The report's comparison (Table 5). Blank where not usable. |
| `usable_for_rig_comparison` | 0 for 500–800 rpm (load off, or mostly spin-up) and for 1300 rpm (window contains the step to 1400 rpm); otherwise 1. |
| `window_note` | Why a row is flagged. |

These values are **derived**, not the lab's own numbers. The lab's current scale (2 A/V) is
unverified, and every lab power scales with it.
