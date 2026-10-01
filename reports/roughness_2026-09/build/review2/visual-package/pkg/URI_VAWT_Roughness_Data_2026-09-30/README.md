# URI VAWT surface-texture tests: data package

This package accompanies the report **"Printed surface texture and the electrical output of a
small vertical-axis wind turbine rotor"** (S. Eacuello, 30 Sep 2026). The report is included as
`URI_VAWT_Roughness_Report_2026-09-30.pdf`. The package holds every file the report uses.

- Raw files in `1_rig_sweeps/` and `2_jeong_lab/` are copies of the originals.
- Everything in `3_derived/` is generated from them by the code in `6_code/`.

## Start here

- **Just the results.** Open `3_derived/peak_power_all_rotors.csv`: one row per rotor and wind
  speed, with peak electrical power by both estimators.
- **The comparisons.** `3_derived/paired_comparisons.csv` is report Table 4.
- **Every load step.** See `1_rig_sweeps/<rotor>_<date>/sweep_<rotor>_points.csv`.
- **Column meanings.** See `DATA_DICTIONARY.md`.

## What was tested

| rotor | fuzzy-skin thickness | Ra label* | tested | where | set points |
|---|---|---|---|---|---|
| `v1_Ra20` | 0.050 mm | 20 µm | 20 Aug 2026 | automated rig | 14 / 14 clean |
| `v1_Ra80` | 0.202 mm | 80 µm | 26 Aug 2026 | automated rig | 14 / 14 clean |
| `v1_Ra40` | 0.101 mm | 40 µm | 1 Sep 2026 | automated rig | 14 / 14 clean |
| no texture | none | — | 27 Jul 2026 | Jeong-lab DAQ | 16 fan settings |
| initial reference | — | — | 5 Jun 2026 | Jeong-lab DAQ | 13 fan settings |

\***The Ra values are labels, not measurements.**

- Ra 20 and Ra 40 are the targets an AI assistant suggested (4 Aug) for the 0.050 and
  0.101 mm settings.
- Ra 80 was never in that table; it continues the doubling.
- A second estimate put the two printed settings at 10–15 and 20–35 µm.
- No surface was measured. Use **fuzzy-skin thickness** as the texture variable.
- **No Ra10 test exists.** It was planned; the 1 Sep session ran Ra40 instead.

All three rig runs share:

- the same rotor geometry (`v1`);
- the same automated protocol (fingerprint `94bed28333f7` in every file header);
- the same instruments.

The rotor is a 3-blade VAWT: R = 0.1016 m (axis to blade attachment), span 0.2451 m, swept
area 2RH = 0.0498 m². See `4_reference/rotor_geometry.json`.

## Layout

```
URI_VAWT_Roughness_Report_2026-09-30.pdf
README.md, DATA_DICTIONARY.md, MANIFEST.csv
1_rig_sweeps/     raw — one folder per rotor run, named <rotor>_<date>
2_jeong_lab/      raw — the lab's tables, raw 360 Hz export and plots, as e-mailed
3_derived/        generated — analysis-ready tables used in the report
4_reference/      rotor geometry (JSON) and the blade mesh (one blade, STL, metres)
5_figures/        report figures (PNG), listed below
6_code/           the analysis code (Python 3 with numpy, scipy, pandas, matplotlib)
```

| figure file | report figure |
|---|---|
| `fig_ratio.png` | Change in peak power vs Ra 20 at each set point |
| `fig_pmax.png` | Peak power against wind speed |
| `fig_trend.png` | Peak power against fuzzy-skin thickness |
| `fig_thevenin.png` | Open-circuit voltage and source resistance |
| `fig_pi.png` | Power–current ladders at three wind speeds |
| `fig_jeong_context.png` | Jeong-lab tests relative to the rig |
| `fig_jeong_processing.png` | 27 Jul table as reported vs reprocessed (Appendix C) |

## Read before comparing numbers

1. **One mounting per rotor.** The report's confidence intervals describe scatter across wind
   speeds within one mounting, not mount-to-mount variation.
2. **Use commanded fan speed as the common axis.** The fan-speed readback changed convention
   between runs; the fan itself ran the same.
   - Ra20 logged the drive's output frequency, which reads 4–21 rpm low.
   - From 25 Aug the software read the drive's speed estimate.
   - Each summary file's `wind_mps` comes from its own readback. `3_derived/` gives
     `wind_mps_nominal`, calculated from the commanded speed.
3. **Two peak-power estimators.** `p_max_raw_w` is the largest single 1 s dwell;
   `p_max_fit_w` is a parabola through the peak. The Ra20 file has only the raw one, named
   `p_max_w`. `3_derived/` recomputes both for every run with the rig's own rule.
4. **The two Jeong-lab tables were processed differently from each other and from the rig.**
   - **27 Jul (`Summary_Table.csv`):** the columns are maxima of raw 360 Hz samples, which
     include noise on the current channel. At 500–700 rpm the load was off.
   - **5 Jun (`Summary_Table_Part1_MAX.csv`):** the values appear to be maxima of 50-sample
     averages.
   - Report §6 and Appendix C give the recipe that reproduces the July table from its raw
     export, and a reprocessing on the rig's basis.
5. **Unusable columns.** `turbine_rpm` and `tsr_at_pmax` in the Ra40 files are not usable,
   because the reed switch bounces. `Measured_RPM` in the July table is usable only up to
   1900 rpm.
6. **The print details typed into the run notes are not reliable.** Entries such as "0.2mm
   layer" and "0.2mm nozzle" record intent: only 0.4 mm nozzles were available. "0.2mm" is
   not the fuzzy-skin thickness. See report §2.
7. **The Ra20 run was relabelled.** It was first logged as `v2_Ra20` and renamed `v1_Ra20` on
   25 Aug to match the geometry actually tested. Three things changed: the label in the header,
   the label in the `blade` column, and the line endings. Every numeric value is unchanged.

## Integrity and reproducibility

- **Checksums.** `MANIFEST.csv` lists every file with its size, data-row count and SHA-256
  checksum.
- **Raw files.** The files in `1_rig_sweeps/` are byte-for-byte copies of the rig's log
  files, and those in `2_jeong_lab/` of the e-mailed attachments.
- **Regenerating the results.** Every result number, table and data figure in the report can
  be regenerated from this folder. The run writes `rebuilt/` next to `6_code/`, including
  `rebuilt/derived/`, which should match `3_derived/`, and `rebuilt/numbers.tex`, which holds
  every number the report quotes.

  ```bash
  python3 6_code/build_report.py
  ```

## Contact

Stephen Eacuello (seacuello@uri.edu), University of Rhode Island.
