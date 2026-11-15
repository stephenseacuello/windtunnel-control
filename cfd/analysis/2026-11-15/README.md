# Analysis of 15 Nov 2026: wall data, boundary layers and per-blade rotor forces

Dr. Jahangiri asked on 1 Nov for the changes in separation, pressure distribution, lift, drag and torque
through the rotation (J3), and for why the gains appear only at high roughness (J4). These scripts take that
from the October runs already on disk; no new runs. Their tables feed the new report
`reports/cfd_verification_2026-12/`. Every result carries the mesh and time-step uncertainty that the
B1 runs (submitted 15 Nov) are checking.

```
nice -n 10 python3 cfd/analysis/2026-11-15/src/surface_extract.py      # about 20 s
nice -n 10 python3 cfd/analysis/2026-11-15/src/bl_ks_tables.py         # about 15 s
nice -n 10 python3 cfd/analysis/2026-11-15/src/rotor_phase_force.py    # about 6 s
```

| Script | Reads (read only) | Writes |
|---|---|---|
| `surface_extract.py` | the 69 complete Stage 2 runs (rough wall and texture, α 0/90/180) and 5 Stage 1 medium SST runs: mesh, `pMean`, `wallShearStressMean`, `UMean` | `out/surface_summary.csv` (one row per run), `out/surface_profiles.csv` (every 0.5 mm of wall), `out/surface_reversal*.csv`, `out/surface_check.csv`, `fig/surface_cp_cf.png` |
| `bl_ks_tables.py` | the smooth wall-resolved runs (Stage 1 medium SST; Stage 2 texture t 0) | `out/bl_stations.csv` (δ99, δ*, θ, H, Re_θ, u_τ by station), `out/bl_ks_tables.csv` (Ks+, Ks/δ99, t/δ99, Re_k), `out/bl_utau_check.csv`, `fig/bl_ks_tables.png` |
| `rotor_phase_force.py` | the 8 long rough-set rotor runs (`priorityE_rough.txt`): `forcesBlade{1,2,3}` histories | `out/rotor_phase_force.csv`, `out/rotor_phase_force_diff.csv` (Ks 400 and 100 minus Ks 0, same wall function), `out/rotor_phase_force_sectors.csv`, `out/rotor_phase_force_check.csv`, `fig/rotor_phase_force*.png` |

The conventions are in each script's docstring: Cp and Cf, the s/c origin at tip A, the azimuth θ as in
`../2026-10-15/src/rotor_analysis.py`, and lift and drag about the relative wind.

## Checks
- **`surface_check.csv`.** 500 of 500 checks pass:
  - the 15 Oct numbers (`../2026-10-15/out/roughness_surface_summary.csv`) are reproduced to 6 digits;
  - the pressure drag from the wall data matches each run's `Cd_pressure_mean` within 0.14%
    (74 runs; worst `a000.0_U23.0_LM_tex0.000_s1_Tu1.0_Co2.5n2`).
- **`bl_utau_check.csv`.** All 25 checks pass (u_τ against the runs' y+ and Ks+ columns).
- **`rotor_phase_force_check.csv`.** All 288 validation checks pass: the sector sums reproduce
  `../2026-10-15/out/rotor_roughness_sectors.csv` and `rotor_roughness_phase.csv`.

## A finding: the rotor's 2u may be too narrow
The 12 flagged rows of `rotor_phase_force_check.csv` are diagnostics, not failures.
- **What they show.** In 32–38% of the (azimuth bin, blade pair) comparisons, the three blades differ by
  more than 2u. About 5% would be expected if the blades were statistically identical, as they should be in
  a uniform free stream.
- **Why it points at the intervals.** The blade-deviation patterns do not repeat from run to run (median
  correlation −0.06 to 0.19), so the differences look random rather than built into the geometry. The likely
  reason is that successive revolutions are not independent, which makes the revolution-to-revolution 2u too
  small, by a factor of about 1.6–2.0 (between-blade 2u over the 2u of the mean, medians).
- **What it means.**
  - Treat every rotor ±2u from these runs, and from `../2026-10-15/`, as a lower bound.
  - The Ks-100 advancing-sector change (+0.00112 ± 0.00039 at λ 0.10) is then only marginally resolved.
  - The report says so (§3 and §4).
