# Data dictionary

Units are SI throughout (V, A, W, m/s). Fan speeds are in rpm.

Rotor names follow the report: Plain, FS 0.05, FS 0.10 and FS 0.20. Their fuzzy-skin thickness,
`fuzzy_skin_mm`, is 0 (none), 0.05, 0.101 and 0.202 mm.

---

## 1_rig_sweeps/: automated sweeps (raw)

File names are `sweep_v1_<label>[_repeat]_20261001_<kind>.csv`:
- `<label>` is `smooth`, `Ra20`, `Ra40` or `Ra80` (Plain, FS 0.05, FS 0.10, FS 0.20);
- `_repeat` marks run 2 on the same mounting.

Each file starts with `#` header lines (`key,value`) followed by an ordinary CSV table. Read it
with, for example, `pandas.read_csv(path, comment="#")`.

### Header lines

| key | meaning |
|---|---|
| `blade` | Run name, except `v1_smooth` for Plain run 1. |
| `notes` | Free text typed by the operator. Textured runs record the earlier label and the fuzzy-skin thickness, e.g. "Ra20, fuzzy 0.050 mm, 1 Oct mount 1". "mount 1"/"mount 2" mean run 1/run 2 on one mounting. Plain runs read "no fuzzy skin (baseline)". No other print settings are recorded. |
| `fan_rpm`, `wind_mps` | The first set point of the run (500 rpm); not a run-wide value. |
| `instrument` | Electronic-load identity (Chroma 63004-150-60, serial, firmware). |
| `protocol`, `protocol_detail` | Identifier `94bed28333f7` and the settings behind it: step scaling (`v2`), step at 1800 rpm (`step`, A), dwell (s), voltage floor (`voff`, V), current range, stop threshold (`operate`, % of the running maximum) and confirmation count (`confirm`, consecutive dwells). |
| `protocol_extra`, `protocol_full` | Ladder and settle settings and a second identifier: minimum step (A), fan tolerance (`rpm_tol_abs`, `rpm_tol_frac`), voltage-settling tolerance (`settle_tol`), poll interval (s), confirmations, and minimum/maximum settle time (s). `unload_amps` (0) is the load current while the fan settles; before the first set point the load is set to half the 1800 rpm step (10 mA), so the 500 rpm settle is at 10 mA. |
| `clock`, `clock_unix` | Host clock when the header was written, **at the end of the run** (about 8 s after the last dwell). The `_clock_note` saying "run start" is wrong. |
| `instrument_check` | Pre-run check of the load's identity (`ok`). |
| `air` | `not recorded — no tunnel node connected`. |
| `drive_actual_signals` | Drive Modbus register mapping. It is not the source of `fan_rpm_actual`, which is the drive's speed estimate. |

### `sweep_<run>_summary.csv`: one row per fan set point

| column | meaning |
|---|---|
| `fan_rpm_cmd` | Commanded fan speed: 500, 600 … 1800. |
| `fan_rpm_actual` | Drive's speed estimate once settled, within 1 rpm of the command. |
| `wind_mps` | Calibration applied to `fan_rpm_actual`. The report uses the commanded speed instead. |
| `blade` | As in the header. |
| `p_max_raw_w`, `i_at_pmax_raw_a` | Largest single 1 s dwell power (W) and its current (A). This is the report's P_max. |
| `p_max_fit_w`, `i_at_pmax_fit_a` | Vertex of a parabola through the maximum ± 2 dwells (W, A), or the maximum if the fit fails. |
| `v_at_pmax_v` | Terminal voltage at the largest dwell (V). |
| `i_last_a` | Current of the last dwell above the load's voltage floor (A); after a roll-off stop, the largest current reached. |
| `limited_by`, `clean`, `stopped_by` | Why the ladder stopped. `power-rolloff` (`clean` = 1): two consecutive dwells at or below 80% of the running maximum. `load-cutout` (`clean` = 0): after the peak, the terminal voltage fell below the voltage floor (`voff`, 0.5 V) on two consecutive dwells while the current still followed the demand; the host stopped the ladder there. |
| `steps` | Dwells in the ladder. |
| `turbine_rpm_at_pmax`, `tsr_at_pmax` | Empty: the rig did not log rotor speed (see `2_rotor_speed/`). |

### `sweep_<run>_points.csv`: one row per 1 s dwell

| column | meaning |
|---|---|
| `t_unix`, `t_local` | End of the dwell. |
| `fan_rpm` | Commanded fan speed for this ladder. |
| `wind_mps` | Calibration applied to the commanded speed. |
| `blade` | As in the header. |
| `demand_a`, `held_a` | Current demand sent to the load, and the current it reported holding (A). |
| `volts`, `amps`, `watts` | **The primary measurements:** terminal voltage (V), current (A) and their product (W) at the end of the dwell. |
| `tracking` | 1 if the load current tracked the demand; 1 in every row of these runs. |
| `note` | `under v_floor` marks dwells at or below the voltage floor (`voff`), after the peak. |
| `fan_rpm_actual`, `motor_amps` | Drive's speed estimate, and fan motor current (0.1 A resolution) at the dwell. |
| `turbine_rpm` | Empty. |

### `sweep_<run>_trace.csv`: fan telemetry, irregular sampling (median interval 56 ms, about 18 Hz)

| column | meaning |
|---|---|
| `t_unix`, `t_rel_s` | Host time, and seconds from the start of the trace. |
| `fan_rpm_actual`, `motor_amps` | Drive's speed estimate and motor current. |
| `rpm_pulses`, `rpm_last_us` | Rotor-pulse counter; constant in every run (no rotor-speed signal). |

---

## 2_rotor_speed/: T. Kang's rotor-speed summaries (raw, as received)

T. Kang recorded rotor speed during the session on his own acquisition: a tachometer, one pulse
per revolution, sampled at 359.97 Hz. The rig did not log rotor speed. These are the summaries he
sent, byte for byte. His per-sample records are not included.

| file | content |
|---|---|
| `sweep_v1_<label>[_repeat]_20261001_RPM_summary.csv` | One per run, named after the rig's run. |
| `sweep_v1_smooth_repeat_20261001_summary.csv` | Plain run 2; same format, named without `_RPM` as received. |
| `RPM.m` | His MATLAB script that made them (comments in Korean). |

| column | meaning |
|---|---|
| `Setting_RPM` | Fan set point (rpm); matches `fan_rpm_cmd` of the rig files. |
| `Measured_RPM` | Most frequent per-revolution rotor speed over the set point (settle and load ladder), rounded to 1 rpm. From 600 rpm the load is at 0 A while the fan settles and the rotor is then steadiest, so the report takes this as the light-load speed; V1/n0 (31.5 mV/rpm, coefficient of variation 1.7%) supports it. At 500 rpm the fan settles with the load at 10 mA, and the report does not use that value. |
| `Pulse_Count` | Tachometer pulses (revolutions) assigned to the set point. The 1800 rpm set point ends at the fastest 5 s window, so its count is small. |

How `RPM.m` gets there:
1. A pulse is a rise through −0.75 V on the tachometer channel.
2. Pulses are counted in 5 s windows, from the first window above 40 rpm to the fastest one.
3. The windows are split into the 14 set points at the 13 largest rises of more than 40 rpm.
4. Each pulse interval gives a speed, 60 / (interval in s); values outside 20–1000 rpm are dropped,
   and the rest are rounded to 1 rpm.
5. `Measured_RPM` is the most frequent of those values.

A pulse interval is a whole number k of samples, so `Measured_RPM` can only take the values
60 × 359.97 / k (… 720, 745, 771, 800, 831, 864 rpm), and the 1 rpm rounding is coarser below
about 147 rpm. The resolution is the larger of 1 rpm and n²/(60 × 359.97): 1.1% at 90 rpm, 0.7%
near 147 rpm and 4.0% at 864 rpm.

---

## 3_surface_scans/: Keyence VR-6000 height maps (raw)

| file | blade set |
|---|---|
| `baseline_Height.csv`, `baseline.png` | Plain |
| `20 1_Height.csv`, `20.png` | FS 0.05 |
| `40 1_Height.csv`, `40.png` | FS 0.10 |
| `801_Height.csv`, `80 1.png`; `80 2_Height.csv`, `80 2.png` | FS 0.20, two fields |

Each CSV begins with quoted `key,value` lines, including:
- `Measured date` (1 October, before the runs);
- `Measurement unit model` (VR-6100);
- `Magnification` (160);
- `XY Calibration` (1.853 µm per pixel);
- `Horizontal` × `Vertical` image size (1053–1100 × 769–773 pixels);
- `Unit` (mm).

A line `"Height"` follows, then the height map: one row per image row, heights in **mm** (1 µm
resolution), blank where the instrument had no return. Image rows run chordwise along the layer
lines, so image columns are spanwise profiles. The PNGs are the instrument's screenshots of the
same fields.

---

## 4_derived/: generated for the report

`rotor` is the report name. `run` is 1 or 2, and `run_name` is the file stem. A change "vs Plain"
is relative to the geometric mean of the two Plain runs at the same set point.

### `comparisons.csv`: every pair of rotors (report Table 3 and the changes in Table 4)

| column | meaning |
|---|---|
| `rotor`, `relative_to` | The comparison: `rotor` relative to `relative_to`. |
| `change_pct` | Geometric mean over the 14 set points of the ratio of P_max, as a percentage change. |
| `tukey95_lo_pct`, `tukey95_hi_pct`, `p_tukey` | Tukey simultaneous 95% interval (all six pairs) and adjusted p-value, from run-to-run repeatability on one mounting. |
| `fit_change_pct`, `fit_tukey95_lo_pct`, `fit_tukey95_hi_pct`, `p_tukey_fit` | The same using the parabolic-fit estimator. |
| `tipping_point_mounting_sd_pct` | For resolved pairs, the largest mounting-to-mounting SD of a rotor's mean power for which the difference stays resolved by the same Tukey criterion. |
| `v_oc_change_pct`, `v_oc_tukey95_lo_pct`, `v_oc_tukey95_hi_pct` | The same comparison for the Thévenin open-circuit voltage. |
| `r_int_change_pct`, `r_int_tukey95_lo_pct`, `r_int_tukey95_hi_pct` | The same for the apparent source resistance. |
| `rotor_rpm_change_pct`, `rotor_rpm_tukey95_lo_pct`, `rotor_rpm_tukey95_hi_pct`, `p_tukey_rotor_rpm` | The same for light-load rotor speed, 600–1800 rpm (`rotor_speed_by_run.csv`). |

### `drift_model.csv`: run means refitted with a linear time term (report Section 8)

| column | meaning |
|---|---|
| `term` | `drift per hour`, or a rotor's drift-adjusted change vs Plain. |
| `estimate_pct`, `ci95_lo_pct`, `ci95_hi_pct`, `dof` | Estimate, 95% t interval and residual degrees of freedom. |

### `run_summary.csv`: one row per run

| column | meaning |
|---|---|
| `first_dwell`, `last_dwell`, `start_h` | Local time of the run's first and last dwell, and its start in hours after the session's first dwell. |
| `p_max_change_vs_plain_pct` | Mean over set points of ln(P_max / P_ref), as a percentage change. |
| `v_oc_change_vs_plain_pct`, `r_int_change_vs_plain_pct` | The same for the Thévenin open-circuit voltage and source resistance. |
| `rotor_rpm_change_vs_plain_pct` | The same for light-load rotor speed, over fan set points 600–1800 rpm. |
| `steepest_rise_mps` | Midpoint wind speed of the steepest segment of ln P_max against ln v (resolution one set-point spacing, 2.1 m/s). |

### `peak_power_by_run.csv`: one row per run and set point (report Appendix A)

| column | meaning |
|---|---|
| `fan_rpm_cmd`, `wind_mps` | Commanded fan speed and the calibrated wind speed. |
| `p_max_w`, `i_at_p_max_a`, `v_at_p_max_v` | Largest dwell power (W), with its current (A) and voltage (V). Recomputed from the points file; equals the logged `p_max_raw_w`. |
| `p_fit_w`, `i_at_p_fit_a`, `fit_points` | Parabolic-fit peak (W, A) and the dwells used (0 = fell back to the maximum). |
| `v_first_v`, `i_first_a` | Voltage and current at the first, lightest dwell. |
| `dwells`, `stop`, `clean` | Ladder length and stop reason (as in the summary file). |
| `fan_motor_a` | Median fan motor current over the ladder (A). |

### `thevenin_by_run.csv`: one row per run and set point

V = V_oc − I·R_int is fitted by least squares over the tracking dwells with V, I > 0. Dwells
flagged `under v_floor` are excluded.

| column | meaning |
|---|---|
| `fan_rpm_cmd`, `wind_mps` | Fan set point and the calibrated wind speed. |
| `v_oc_v` | Zero-current intercept (V), an extrapolated open-circuit voltage, not a measured one. V_oc/n0 shows no resolved difference between rotors (largest −0.4%; report Section 6.5). |
| `r_int_ohm` | Apparent source resistance (Ω): winding, rectifier (incl. commutation and diode incremental resistance), wiring, and the rotor slowing as load rises (report Section 5). |
| `r2`, `dwells_fitted` | Fit quality, and the number of dwells fitted. |
| `p_matched_w` | V_oc² / 4R_int (W). |

### `rotor_speed_by_run.csv`: one row per run and set point (report Sections 3.3 and 6.5, Appendix A)

| column | meaning |
|---|---|
| `fan_rpm_cmd`, `wind_mps` | Fan set point and the calibrated wind speed. |
| `rotor_rpm`, `pulses` | `Measured_RPM` and `Pulse_Count` from `2_rotor_speed/`: light-load rotor speed n0 (rpm). |
| `light_load` | 1 from 600 rpm. 0 at 500 rpm, where the fan settles with the load at 10 mA; the report does not use those rows. |
| `tip_speed_ratio` | λ0 = 2π n0 R / (60 v), with R = 0.1016 m, the attachment radius (the outer radius is larger). |
| `v_first_v`, `i_first_a` | Terminal voltage and current at the first load step (1–10 mA), from the rig. |
| `v_first_per_rpm_mv` | v_first_v / rotor_rpm (mV/rpm), terminal voltage per rpm at light load. Over the 104 rows with `light_load` = 1 it is 31.5 mV/rpm (coefficient of variation 1.7%) and shows no resolved difference between rotors (largest +0.7%; report Section 6.5). |

### `rotor_by_wind_speed.csv`: one row per rotor and set point (report Figs 4, 6, 7 and 8)

| column | meaning |
|---|---|
| `fan_rpm_cmd`, `wind_mps` | Fan set point and the calibrated wind speed. |
| `p_max_geomean_w`, `v_oc_geomean_v`, `r_int_geomean_ohm`, `rotor_rpm_geomean` | Geometric means of the two runs. The rotor-speed columns are empty at 500 rpm. |
| `tip_speed_ratio` | Light-load tip-speed ratio from `rotor_rpm_geomean`. |
| `cp_el` | Electrical power coefficient P_max / (½ρAv³), with ρ = 1.204 kg/m³ and A = 0.0498 m². |
| `p_max_change_vs_plain_pct` | Change of `p_max_geomean_w` relative to Plain (textured rotors only). |
| `run1_change_pct`, `run2_change_pct` | The same for each run. |
| `pointwise95_halfwidth_pct` | 95% half-width of a single-set-point difference from Plain, from the within-rotor run-to-run SD at that set point. |
| `v_oc_change_vs_plain_pct`, `r_int_change_vs_plain_pct` | Thévenin changes relative to Plain. |
| `rotor_rpm_change_vs_plain_pct` | Change of light-load rotor speed relative to Plain. |

### `anova.csv`: analyses of variance (report Appendix B)

The table has six blocks, identified by `analysis`:
1. ln P_max, all rotors;
2. ln P_max, textured rotors only;
3. ln P_max, without the two noisiest set points;
4. ln R_int;
5. ln V_oc;
6. ln n_0, light-load rotor speed, 600–1800 rpm.

| column | meaning |
|---|---|
| `source` | rotor, set point, rotor x set point, run within rotor, residual. |
| `df`, `ss`, `ms` | Degrees of freedom, sum of squares, mean square. |
| `F`, `df_den`, `p` | F ratio, denominator degrees of freedom and p-value. The rotor is tested against run within rotor; the other sources against the residual. |

### `surface_roughness.csv`: report Sections 2.3 and 6.6, Table 5

| column | meaning |
|---|---|
| `scans`, `columns`, `profiles` | Fields scanned, image columns, and columns kept as profiles (a column is dropped if more than 10% of its points are missing, or more than 2% between its first and last valid points). |
| `Pa_um` | Mean absolute deviation of each levelled profile, averaged over profiles (µm). |
| `Ra_lc025_um` | The same for the roughness profile: the levelled profile minus its ISO 16610-21 Gaussian mean line, λc = 0.25 mm (µm). |
| `layer_period_um` | Peak of the mean profile spectrum between 60 and 320 µm; empty for FS 0.20: it was printed with 0.10 mm layers, but its texture leaves no spectral peak. |
| `Pa_scan_spread_um`, `Ra_scan_spread_um` | Difference between the two FS 0.20 fields. |

---

## 5_reference/

- `rotor_geometry.json`: rotor and blade dimensions. The code reads these values.
- `blade_v1.stl`: one blade, metres, in its own coordinates.
- `tunnel_calibration_test1.csv`: the tunnel calibration from Test 1 (13 Feb 2026). The code fits
  the wind-speed line to it.
  - Columns are `rpm`, `velocity` (m/s) and `source`.
  - `source` is `measured` (0–700 rpm) or `possible trendline read` (1400–2400 rpm).
- `turbine_default_summary.json`: summary of the I²(s) Print Lab's slicer project
  `turbine_default.3mf` (Bambu Studio, saved 17 Aug 2026), written by `7_code/slicer.py`. The
  project itself (60 MB) is not shipped. The summary gives:
  - the profiles;
  - nozzle (0.2 mm), layer height (0.10 mm) and material (PLA);
  - the fuzzy-skin settings;
  - per reported plate: the object size (one blade), and the shares of triangles and of surface
    area painted with fuzzy skin.

  It covers the FS 0.10 and FS 0.20 settings only (the project has no FS 0.05 plate; its third plate
  is not reported) and does not record which prints were made from it.
