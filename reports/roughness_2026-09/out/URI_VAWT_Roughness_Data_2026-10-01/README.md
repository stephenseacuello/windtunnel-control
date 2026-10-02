# URI VAWT surface-texture tests: data package

This package accompanies the report **"Printed surface texture and the electrical output of a
small vertical-axis wind turbine rotor"** (S. Eacuello, 1 Oct 2026), included as
`URI_VAWT_Roughness_Report_2026-10-01.pdf`. It holds every file the report uses.

- Raw files (`1_rig_sweeps/`, `2_jeong_lab/`, `3_surface_scans/`) are byte-for-byte copies of
  the originals.
- Everything in `4_derived/` is generated from them by the code in `7_code/`.

## Start here

- **The result.** `4_derived/oct1_vs_no_texture.csv`: each textured rotor against the
  un-textured rotor, same day, two mountings each (report Table 1).
- **Every mounting.** `4_derived/oct1_by_mounting.csv` (report Fig. 3).
- **Surface roughness.** `4_derived/surface_roughness.csv` (report Section 1.1).
- **Peak power per wind speed, every run.** `4_derived/peak_power_all_rotors.csv`.
- **Every load step.** `1_rig_sweeps/<date>/sweep_<run>_points.csv`.
- **Column meanings.** `DATA_DICTIONARY.md`.

## What was tested

| rotor | fuzzy-skin thickness | tested | where | runs |
|---|---|---|---|---|
| `v1_smooth` (no texture) | none | 1 Oct 2026 | rig | 2 mountings |
| `v1_Ra20` | 0.050 mm | 20 Aug, 1 Oct 2026 | rig | 1 + 2 mountings |
| `v1_Ra40` | 0.101 mm | 1 Sep, 1 Oct 2026 | rig | 1 + 2 mountings |
| `v1_Ra80` | 0.202 mm | 26 Aug, 1 Oct 2026 | rig | 1 + 2 mountings |
| no texture | none | 27 Jul 2026 | Jeong-lab DAQ | 16 fan settings |
| initial reference | — | 5 Jun 2026 | Jeong-lab DAQ | 13 fan settings |

- **The Ra values are names, not measurements.** Use fuzzy-skin thickness as the texture
  variable. The measured Pa and Ra are in `4_derived/surface_roughness.csv`.
- A fifth blade set run on 1 Oct is not included: its print settings could not be confirmed.

Every rig run uses the same rotor geometry (`v1`), the same instruments and the same automated
protocol (fingerprint `94bed28333f7` in every file header). The rotor has 3 blades,
R = 0.1016 m (axis to blade attachment), span 0.2451 m, swept area 2RH = 0.0498 m²
(`5_reference/rotor_geometry.json`).

## Layout

```
URI_VAWT_Roughness_Report_2026-10-01.pdf
README.md, DATA_DICTIONARY.md, MANIFEST.csv
1_rig_sweeps/      raw: one folder per test date
2_jeong_lab/       raw: the lab's tables, raw 360 Hz export and plots, as e-mailed
3_surface_scans/   raw: Keyence VR-6000 height maps (CSV) and screenshots (PNG), 1 Oct
4_derived/         generated: analysis-ready tables used in the report
5_reference/       rotor geometry (JSON) and the blade mesh (one blade, STL, metres)
6_figures/         report figures (PNG)
7_code/            the analysis code (Python 3 with numpy, scipy, pandas, matplotlib)
```

| figure file | report figure |
|---|---|
| `fig_surface.png` | Fig. 1, Keyence height maps |
| `fig_day.png` | Fig. 3, every 1 Oct mounting against the un-textured rotor |
| `fig_day_curves.png` | Fig. 4, peak power against wind speed |
| `fig_day_thevenin.png` | Fig. 5, open-circuit voltage and source resistance |
| `fig_jeong_context.png` | Fig. 6, Jeong-lab tests relative to the rig |

## Read before comparing numbers

1. **Use commanded fan speed as the common axis.** The Ra20 file (20 Aug) logged the drive's
   output frequency, which reads 4–21 rpm below the command. Later files read the drive's
   speed estimate. The fan ran the same in every run. `4_derived/` gives `wind_mps_nominal`,
   calculated from the commanded speed.
2. **Two peak-power estimators.** `p_max_raw_w` is the largest single 1 s dwell (the report's
   basis); `p_max_fit_w` is a parabola through the peak. The 20 Aug file has only the raw one,
   named `p_max_w`. `4_derived/` recomputes both for every run with the rig's own rule.
3. **The header `clock` is written at the end of a run**, despite its note. Use the per-row
   `t_unix` or `t_local`.
4. **Two 1 Oct set points ended on the voltage-floor cut-out** (`limited_by = load-cutout`):
   `v1_smooth_20261001` at 500 rpm and `v1_Ra20_repeat_20261001` at 600 rpm. Power had already
   fallen to about half its peak, so the peak is valid.
5. **The Jeong-lab tables were processed differently from each other and from the rig.**
   Report Section 4 and Appendix C give the recipe that reproduces the July table from its raw
   export, and a reprocessing on the rig's basis.
6. **Unusable columns.** `turbine_rpm` and `tsr_at_pmax`: the reed switch bounced on 1 Sep, and
   the columns are empty on 1 Oct. `Measured_RPM` in the July table is usable only up to
   1900 rpm.
7. **Run notes are not reliable for print settings.** See `DATA_DICTIONARY.md`.

## Integrity and reproducibility

- `MANIFEST.csv` lists every file with its size, data-row count and SHA-256 checksum.
- Every number, table and data figure in the report regenerates from this folder:

  ```bash
  python3 7_code/build_report.py
  ```

  The run writes `rebuilt/` next to `7_code/`. `rebuilt/derived/` should match `4_derived/`,
  and `rebuilt/numbers.tex` holds every number the report quotes.

## Contact

Stephen Eacuello (seacuello@uri.edu), University of Rhode Island.
