# URI VAWT fuzzy-skin texture test, 1 October 2026: data package

This package accompanies the report **"Fuzzy-skin texture and the peak electrical output of a
small vertical-axis wind turbine rotor"** (S. Eacuello, 2 Oct 2026), included as
`URI_VAWT_Texture_Report_2026-10-01.pdf`. It holds every file the report uses.

- `1_rig_sweeps/` and `2_surface_scans/` are byte-for-byte copies of the raw files.
- `3_derived/` is generated from them by the code in `6_code/`.

## What was tested

One rotor geometry (3 straight blades attached at R = 0.1016 m, span 0.2451 m, swept area
2RH = 0.0498 m²), with four blade sets that differ in fuzzy-skin thickness:

| rotor (report) | fuzzy skin | earlier label | run files |
|---|---|---|---|
| Plain | none | baseline | `v1_smooth_20261001`, `v1_smooth_repeat_20261001` |
| FS 0.05 | 0.050 mm | Ra 20 | `v1_Ra20_20261001`, `v1_Ra20_repeat_20261001` |
| FS 0.10 | 0.101 mm | Ra 40 | `v1_Ra40_20261001`, `v1_Ra40_repeat_20261001` |
| FS 0.20 | 0.202 mm | Ra 80 | `v1_Ra80_20261001`, `v1_Ra80_repeat_20261001` |

- The earlier labels (Ra 20/40/80) are names, not measured values. The measured Pa and Ra are in
  `3_derived/surface_roughness.csv`.
- Each rotor was mounted once and swept twice without being removed (`_repeat` = run 2).
- Each sweep covers 14 fan set points, 500–1800 rpm (10.2–38.0 m/s).
- Every run uses the same automated protocol: identifier `94bed28333f7` in every file header.
- A fifth blade set was also run that day. Its print settings could not be confirmed, so it is not
  included.

## Start here

- **The result:** `3_derived/comparisons.csv` (report Table 4).
- **One row per run:** `3_derived/run_summary.csv`.
- **Every load step:** `1_rig_sweeps/sweep_<run>_points.csv`.
- **Column meanings:** `DATA_DICTIONARY.md`.

## Layout

```
URI_VAWT_Texture_Report_2026-10-01.pdf
README.md, DATA_DICTIONARY.md, MANIFEST.csv
1_rig_sweeps/      raw: 8 runs x (summary, points, trace)
2_surface_scans/   raw: Keyence VR-6000 height maps (CSV) and screenshots (PNG)
3_derived/         generated: the analysis-ready tables behind the report
4_reference/       rotor geometry, blade mesh, wind-speed calibration points, slicer summary
5_figures/         report figures (PNG)
6_code/            analysis code (Python 3 with numpy, scipy, pandas, matplotlib)
```

## Read before using the numbers

1. **Wind speed** is the tunnel calibration applied to the commanded fan speed:
   v = 0.02132 N − 0.424 (m/s, N in rpm). This is the least-squares line through
   `4_reference/tunnel_calibration_test1.csv`.
   - Only the points up to 700 rpm were measured.
   - The 1400–2400 rpm entries are marked "possible trendline read".
   - Rotor comparisons are made at identical fan speed and do not depend on the calibration.
2. **The rig did not log rotor speed.** T. Kang recorded it separately. It will be added and joined
   on the per-dwell `t_unix` time stamps.
3. **Air temperature and pressure were not recorded.** The power coefficient assumes standard air
   (1.204 kg/m³).
4. **The header `clock` is written at the end of a run**, despite its note. Use the per-row
   `t_unix` or `t_local`.
5. **Two ladders ended on the voltage-floor cut-out**, after the peak (`limited_by = load-cutout`):
   `v1_smooth_20261001` at 500 rpm and `v1_Ra20_repeat_20261001` at 600 rpm.

## Integrity and reproducibility

- `MANIFEST.csv` lists every file with its size, data-row count and SHA-256 checksum.
- Running `python3 6_code/build_report.py` regenerates every result, table and data figure in the
  report into `rebuilt/`.
  - `rebuilt/derived/` equals `3_derived/`.
  - `rebuilt/numbers.tex` holds every number the report quotes.
  - This was checked when the package was built.
- Tested with Python 3.14 (numpy 2.5, scipy 1.17, pandas 3.0, matplotlib 3.11). The derived tables
  also reproduce with numpy 1.26, scipy 1.12, pandas 2.2 and matplotlib 3.8.

## Contact

Stephen Eacuello (seacuello@uri.edu), University of Rhode Island.
