# URI VAWT surface-texture tests: data package

This package accompanies the report **"Printed surface texture and the electrical output of a
small vertical-axis wind turbine rotor"** (S. Eacuello, 30 Sep 2026). It holds every file the
report uses. Raw files are exactly as recorded; the derived tables are generated from them by
the code included here.

## Start here

- **Just the results.** Open `3_derived/peak_power_all_rotors.csv`: one row per rotor and wind
  speed, with peak electrical power by both estimators.
- **The comparisons.** `3_derived/paired_comparisons.csv` is Table 4 of the report.
- **Every load step.** See `1_rig_sweeps/<rotor>/sweep_<rotor>_points.csv`.
- **Column meanings.** See `DATA_DICTIONARY.md`.

## What was tested

| rotor | fuzzy-skin thickness | nominal Ra* | tested | source | set points |
|---|---|---|---|---|---|
| `v1_Ra20` | 0.050 mm | 20 µm | 20 Aug 2026 | automated rig | 14 / 14 clean |
| `v1_Ra80` | 0.202 mm | 80 µm | 26 Aug 2026 | automated rig | 14 / 14 clean |
| `v1_Ra40` | 0.101 mm | 40 µm | 1 Sep 2026 | automated rig | 14 / 14 clean |
| no texture | none | — | 27 Jul 2026 | Jeong-lab DAQ | 16 fan settings |
| initial reference | — | — | 5 Jun 2026 | Jeong-lab DAQ | 13 fan settings |

\*The Ra values are the roughness targets used to choose the print settings. They were
**not measured**, and a second estimate put them at about half these values. Treat the
fuzzy-skin thickness as the texture variable. **No Ra10 test exists**: it was planned, but
the 1 Sep session ran Ra40 instead.

All three rig runs use the same rotor geometry (`v1`), the same automated protocol
(fingerprint `94bed28333f7` in every file header) and the same instruments. The rotor is a
3-blade H-type VAWT: R = 0.1016 m, span 0.2451 m, swept area 2RH = 0.0498 m².

## Layout

```
README.md, DATA_DICTIONARY.md, MANIFEST.csv
1_rig_sweeps/     raw, verbatim — one folder per rotor run
2_jeong_lab/      raw, verbatim — the lab's tables, raw 360 Hz export and plots, as e-mailed
3_derived/        generated — analysis-ready tables used in the report
4_reference/      blade geometry (one blade: notes and STL mesh, in metres)
5_figures/        report figures (PNG)
6_code/           the analysis code (Python 3, numpy/scipy/pandas/matplotlib)
```

## Read before comparing numbers

1. **One mounting per rotor.** The confidence intervals in the report describe scatter
   across wind speeds within one mounting. They do not include mount-to-mount variation.
   A remount repeat is scheduled.
2. **Use commanded fan speed as the common axis.** The fan-speed readback changed convention
   between runs. Ra20 logged the drive's output frequency, which reads 4–21 rpm low; Ra40 and
   Ra80 logged the drive's speed estimate. The fan itself ran the same; the motor current
   agrees across runs. Each summary file's `wind_mps` comes from its own readback, so the
   Ra20 summary's wind column reads 0.7–1.2% low. `3_derived/` gives
   `wind_mps_nominal` from the command.
3. **Peak power has two estimators.** `p_max_raw_w` is the largest single 1 s dwell;
   `p_max_fit_w` is a parabola through the peak. The Ra20 file has only the raw one (as
   `p_max_w`). `3_derived/` recomputes both for all three runs with the rig's own rule.
4. **The Jeong-lab tables are not directly comparable to the rig.** Their `Pdc_max` is the
   maximum of raw 360 Hz samples, which includes current-sensor noise, and at 500–700 rpm
   no load current was drawn. Report §6 and Appendix C give the exact recipe that reproduces
   the lab's table from the raw export, and a reprocessing on a comparable basis.
5. **The rotor-speed columns (`turbine_rpm`, `tsr_at_pmax`) in the Ra40 files are not
   usable.** The reed switch bounces.
6. **The Ra20 run was first logged as `v2_Ra20`** and relabelled `v1_Ra20` on 25 Aug to match
   the geometry actually tested. Only the label changed; the data rows are identical.

## Integrity and reproducibility

- **Checksums.** `MANIFEST.csv` lists every file with its size, data-row count and SHA-256
  checksum. Files in `1_rig_sweeps/` and `2_jeong_lab/` are byte-for-byte copies of the
  originals.
- **Regenerating the numbers.** Every number, table and figure in the report can be
  regenerated from this folder:

  ```bash
  python3 6_code/build_report.py        # writes rebuilt/ next to 6_code/
  ```

  `rebuilt/numbers.tex` then contains every number the report quotes.

## Contact

Stephen Eacuello (seacuello@uri.edu), Sodhi Lab, University of Rhode Island.
