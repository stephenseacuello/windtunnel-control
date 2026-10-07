# URI VAWT fuzzy-skin texture test, 1 October 2026: data package

This package accompanies the report **"Peak electrical power of a small vertical-axis wind turbine
with 3D-printed textured blades"**, Revision 2 (S. Eacuello and T. Kang, 7 Oct 2026; first issued
5 Oct 2026), included as `URI_VAWT_Texture_Report_2026-10-01_rev2.pdf`. It holds every file the
report uses. Revision 2 adds T. Kang's per-sample tachometer records (`2_rotor_speed/raw/`) and the
rotor speed at every load dwell (`4_derived/rotor_speed_by_dwell.csv`).

- `1_rig_sweeps/`, `2_rotor_speed/` and `3_surface_scans/` are byte-for-byte copies of the raw
  files.
- `4_derived/` is generated from them by the code in `7_code/`.

## What was tested

One rotor geometry (3 straight blades attached at R = 0.1016 m, span 0.2451 m, swept area
2RH = 0.0498 m²), with four blade sets that differ in fuzzy-skin thickness:

| rotor (report) | fuzzy skin | earlier label | run files |
|---|---|---|---|
| Plain | none | smooth (scans: baseline) | `v1_smooth_20261001`, `v1_smooth_repeat_20261001` |
| FS 0.05 | 0.050 mm | Ra 20 | `v1_Ra20_20261001`, `v1_Ra20_repeat_20261001` |
| FS 0.10 | 0.101 mm | Ra 40 | `v1_Ra40_20261001`, `v1_Ra40_repeat_20261001` |
| FS 0.20 | 0.202 mm | Ra 80 | `v1_Ra80_20261001`, `v1_Ra80_repeat_20261001` |

- The earlier labels (Ra 20/40/80) are names, not measured values. The measured Pa and Ra are in
  `4_derived/surface_roughness.csv`.
- All blade sets were printed by the URI College of Engineering I²(s) Print Lab.
- Each rotor was mounted once and swept twice without being removed (`_repeat` = run 2).
- Each sweep covers 14 fan set points, 500–1800 rpm (10.2–38.0 m/s).
- Every run uses the same automated protocol: identifier `94bed28333f7` in every file header.
- T. Kang recorded rotor speed on his own acquisition (`2_rotor_speed/`); the rig did not.
- A fifth blade set was also run that day. Its print settings could not be confirmed, so it is not
  included.

## Start here

- **The result:** `4_derived/comparisons.csv` (report Tables 3 and 4).
- **One row per run:** `4_derived/run_summary.csv`.
- **Rotor speed and tip-speed ratio:** `4_derived/rotor_speed_by_run.csv` (light load, per set
  point) and `4_derived/rotor_speed_by_dwell.csv` (every load dwell).
- **Generator constants per run:** `4_derived/generator_by_run.csv`.
- **Every load step:** `1_rig_sweeps/sweep_<run>_points.csv`.
- **Column meanings:** `DATA_DICTIONARY.md`.

## Layout

```
URI_VAWT_Texture_Report_2026-10-01.pdf
README.md, DATA_DICTIONARY.md, MANIFEST.csv
1_rig_sweeps/      raw: 8 runs x (summary, points, trace)
2_rotor_speed/     raw: T. Kang's rotor-speed summaries (8 runs), his script RPM.m, and in raw/
                   his per-sample records (8 runs, gzip)
3_surface_scans/   raw: Keyence VR-6000 height maps (CSV) and screenshots (PNG)
4_derived/         generated: the analysis-ready tables behind the report
5_reference/       rotor geometry, blade mesh, wind-speed calibration points, slicer summary
6_figures/         the report's data figures, Figs 2–9 (PNG)
7_code/            analysis code (Python 3 with numpy, scipy, pandas, matplotlib)
```

## Read before using the numbers

1. **Wind speed** is the tunnel calibration applied to the commanded fan speed:
   v = 0.02132 N − 0.424 (m/s, N in rpm). This is the least-squares line through
   `5_reference/tunnel_calibration_test1.csv`.
   - Only the points up to 700 rpm were measured.
   - The 1400–2400 rpm entries are marked "possible trendline read".
   - Rotor comparisons are made at identical fan speed and do not depend on the calibration.
2. **Rotor speed.** `2_rotor_speed/` holds T. Kang's summaries, one value per set point (the most
   frequent per-revolution speed), and his per-sample records in `raw/`.
   - The mode is taken over the whole set point (settle and load ladder). From 600 rpm the load
     is at 0 A while the fan settles and the rotor is then steadiest, so the report takes it as the
     light-load speed; the rig's first-step voltage supports this.
   - At 500 rpm the fan settles with the load at 10 mA; the report does not use those values
     (`light_load` = 0 in `4_derived/rotor_speed_by_run.csv`).
   - The resolution is the larger of 1 rpm and n²/(60 × 359.97 Hz): 0.7–4.0% of the speed.
   - The summaries have no time stamps; his script assigns its 14 segments to the set points in
     order.
   - Speed at every dwell (`4_derived/rotor_speed_by_dwell.csv`) comes from the raw records,
     aligned to the rig's dwells with his voltage channel (clocks 0.9–1.9 s apart, no drift). The
     `Time Stamp UTC` column in the raw records runs about 8% fast within a file and is used only at
     the start of each recording segment; `Relative Time` is real time.
   - The tachometer is a proximity sensor triggered by a magnet glued to one blade, re-glued for
     each set. Missed pulses (mostly Plain and FS 0.05, at the highest speeds) are repaired;
     dwells where a run of misses halves the apparent speed have `speed_ok` = False.
3. **Air temperature and pressure were not recorded.** The power coefficient assumes standard air
   (1.204 kg/m³).
4. **The header `clock` is written at the end of a run**, despite its note. Use the per-row
   `t_unix` or `t_local`.
5. **Two ladders stopped on the voltage floor**, after the peak: the terminal voltage fell below
   0.5 V on two consecutive dwells while the current still followed the demand
   (`limited_by = load-cutout`). These are `v1_smooth_20261001` at 500 rpm and
   `v1_Ra20_repeat_20261001` at 600 rpm.

## Integrity and reproducibility

- `MANIFEST.csv` lists every file with its size, data-row count and SHA-256 checksum.
- Running `python3 7_code/build_report.py` and then `python3 7_code/build_tacho.py` regenerates
  every result, table and data figure in the report into `rebuilt/`.
  - `rebuilt/derived/` and `rebuilt/tacho/derived/` equal `4_derived/`.
  - `rebuilt/numbers.tex` and `rebuilt/tacho/numbers.tex` hold every number the report quotes.
  - This was checked when the package was built.
- Tested with Python 3.14 (numpy 2.5, scipy 1.17, pandas 3.0, matplotlib 3.11). The derived tables
  also reproduce with numpy 1.26, scipy 1.12, pandas 2.2 and matplotlib 3.8.

## Contact

Stephen Eacuello (seacuello@uri.edu), University of Rhode Island.
