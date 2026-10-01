# Data dictionary

Units are SI throughout: V, A, W, m/s. Fan and rotor speeds are in rpm.

---

## 1_rig_sweeps/ — automated sweeps (verbatim)

Every file starts with `#` header lines (`key,value`) and then an ordinary CSV table. Read it
with, for example, `pandas.read_csv(path, comment="#")`.

### Header lines

| key | meaning |
|---|---|
| `blade` | rotor name, `<geometry>_Ra<nominal roughness>` |
| `notes` | free text entered at the start of the run |
| `instrument` | electronic-load identity string (Chroma 63004-150-60, serial, firmware) |
| `protocol` | fingerprint of every setting that changes what a number means. **All three runs: `94bed28333f7`** |
| `protocol_detail` | the settings behind the fingerprint: step scaling, step size at 1800 rpm, dwell, cut-out voltage, current range, and so on |
| `clock`, `clock_unix` | host wall clock at the start of the run (Ra40, Ra80) |
| `protocol_extra`, `protocol_full` | the ladder and settle settings, with a second fingerprint (Ra40 only; later software) |
| `air_temp_c`, `air_pressure_pa`, `air_density_kg_m3` | ambient air from the tunnel node (Ra40 only). **The temperature sensor self-heats and its offset was not calibrated**, so treat the temperature as reading high |
| `drive_actual_signals` | which drive parameters feed `fan_rpm_actual` (Ra40: `5310=103;5311=104`) |

### `sweep_<rotor>_summary.csv` — one row per fan set point

| column | meaning |
|---|---|
| `fan_rpm_cmd` | fan speed commanded (rpm): 500, 600 … 1800 |
| `fan_rpm_actual` | fan speed reported by the drive once settled. **The convention differs:** Ra20 reads 4–21 rpm below the command, while Ra40 and Ra80 read within 1 rpm of it (report §4) |
| `wind_mps` | `0.02132 × fan_rpm_actual − 0.424`, the tunnel calibration applied to the *reported* fan speed |
| `blade` | rotor name |
| `p_max_w` | *(Ra20 only)* raw arg max: the largest single 1 s dwell power (W) |
| `i_at_pmax_a` | *(Ra20 only)* current at that dwell (A) |
| `p_max_fit_w`, `i_at_pmax_fit_a` | *(Ra40, Ra80)* peak power (W) and current (A) from a parabola through the arg max ± 2 dwells |
| `p_max_raw_w`, `i_at_pmax_raw_a` | *(Ra40, Ra80)* raw arg max power (W) and its current (A) |
| `v_at_pmax_v` | terminal voltage at the raw arg max (V) |
| `i_last_a` | largest sustained current reached on the ladder (A) |
| `limited_by` | why the ladder stopped. `power-rolloff` (every row here) means it stopped cleanly past the power peak |
| `clean` | 1 if the ladder stopped on the power roll-off |
| `steps` | number of dwells in the ladder |
| `stopped_by` | human-readable stop reason, for example "power fell to 58% of its peak" |
| `turbine_rpm_at_pmax`, `tsr_at_pmax` | *(Ra40 only)* reed-switch rotor speed at the peak and the implied tip-speed ratio. **Unreliable** (the switch bounces); do not use |

### `sweep_<rotor>_points.csv` — one row per 1 s dwell

| column | meaning |
|---|---|
| `t_unix`, `t_local` | end of the dwell (Ra40, Ra80 only; Ra20 predates timestamps) |
| `fan_rpm` | commanded fan speed for this ladder (rpm) |
| `wind_mps` | `0.02132 × fan_rpm − 0.424`, the calibration applied to the *commanded* speed. This is why it differs from the summary's `wind_mps` by 0–1.2% for Ra20 |
| `blade` | rotor name |
| `demand_a` | constant-current demand sent to the load (A) |
| `held_a` | current the load reported holding (A) |
| `volts`, `amps`, `watts` | measured terminal voltage (V), current (A) and their product (W) for the dwell. **These are the primary measurements** |
| `tracking` | 1 if the load's current tracked the demand. Only tracking dwells are used for peak power |
| `note` | per-dwell annotation (usually empty) |
| `fan_rpm_actual` | drive-reported fan speed during the dwell (same convention caveat as above) |
| `motor_amps` | fan motor current (A) |
| `turbine_rpm` | *(Ra40 only)* reed-switch rotor speed over the dwell. **Unreliable** |

### `sweep_v1_Ra40_trace.csv` — continuous telemetry through the run

| column | meaning |
|---|---|
| `t_unix` | host time (s since 1970) |
| `t_rel_s` | seconds from the start of the trace |
| `fan_rpm_actual` | drive-reported fan speed (rpm) |
| `motor_amps` | fan motor current (A) |
| `rpm_pulses` | cumulative reed-switch pulse count (bounces included) |
| `rpm_last_us` | microseconds between the last two pulses |

---

## 2_jeong_lab/ — Jeong-lab tests (verbatim as e-mailed)

### `2026-06-05_initial_reference/Summary_Table_Part1_MAX.csv` and `2026-07-27_no_texture_baseline/Summary_Table.csv`

| column | meaning |
|---|---|
| `Setting_RPM` | fan set point (rpm) |
| `Measured_RPM` | rotor speed counted from a once-per-revolution pulse (rpm) |
| `Wind_Speed_ms` | wind speed looked up from the fan set point (m/s). The lab's calibration differs from the rig's by up to 4.4% |
| `Vdc_max`, `Idc_max`, `Pdc_max` | maxima over a window of the DC voltage (V), current (A) and power (W). **How they were computed matters:** see report §6 before comparing them with the rig |

### `2026-07-27_no_texture_baseline/0727windturbine.csv` — raw DAQ export, 360 Hz

The five channel columns are all labelled `Volt`. The mapping below was **inferred from the
data** by reproducing the lab's Summary_Table exactly (report §6). Please confirm it against
the lab's wiring.

| column (position) | inferred meaning | scale |
|---|---|---|
| `Relative Time` | seconds from the start; sample interval 1/360 s | – |
| `Date`, `Time Stamp UTC` | wall-clock stamps (quantised; use `Relative Time`) | – |
| 1st `Volt` | DC bus voltage through a 4:1 divider | V_dc = 4 × ch1 |
| 2nd `Volt` | Hall-effect DC current sensor with a mid-rail zero | I_dc = 2 × (ch2 − 2.5) as processed by the lab. The measured zero is 2.4961 V |
| 3rd `Volt` | once-per-revolution rotor pulse | 1 pulse = 1 revolution |
| 4th, 5th `Volt` | the same pulse train at lower gain | – |
| `Chn 1 Events` | empty | – |

---

## 3_derived/ — generated for the report (reproducible from 6_code/)

### `peak_power_all_rotors.csv` — one row per rotor and fan set point

| column | meaning |
|---|---|
| `rotor`, `ra_nominal_um`, `test_date` | rotor name, nominal roughness label (µm; not measured), test date |
| `fan_rpm_cmd`, `fan_rpm_logged` | commanded and drive-reported fan speed (rpm) |
| `wind_mps_nominal` | calibration applied to the **commanded** speed. This is the report's wind axis |
| `wind_mps_logged` | the summary file's own `wind_mps` |
| `p_max_raw_w`, `i_at_p_max_raw_a`, `v_at_p_max_raw_v` | raw arg max power and its current and voltage |
| `p_max_fit_w`, `i_at_p_max_fit_a` | parabolic-fit peak (the rig's rule, applied uniformly to all three runs) |
| `fit_points` | dwells used in the fit. 0 means the fit fell back to the arg max |
| `v_first_step_v`, `i_first_step_a` | voltage and current at the first (lightest) dwell |
| `n_steps`, `limited_by`, `clean` | ladder length and stop reason |

### `thevenin_by_setpoint.csv`

V = V_oc − I·R_int fitted by least squares over each ladder's tracking dwells.

| column | meaning |
|---|---|
| `v_oc_v` | open-circuit voltage (V), which is proportional to free-running rotor speed |
| `r_int_ohm` | apparent source resistance (Ω) |
| `r2` | fit quality |
| `p_thevenin_match_w` | V_oc² / 4R_int, the power at the matched load |

### Other derived tables

- **`paired_comparisons.csv`:** change in peak power between rotors at matched set points,
  with a t-based 95% CI, a sign-test p-value, and Δn (the change in the power-law exponent).
- **`power_law_fits.csv`:** P_max = a·vⁿ fitted per rotor.
- **`jeong_0727_reprocessed_by_setting.csv`:** the July run reprocessed from its raw DAQ
  export (report §6). Present only once the reprocessing has been verified.
