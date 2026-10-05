# Fuzzy-skin texture report — handoff (updated 5 Oct 2026)

## Scope (Stephen, 2 and 4 Oct)
- **1 October 2026 session only.** No June–July lab data, no Aug–Sep rig runs.
- `v1_unk` excluded: one neutral sentence in the report, and none of its files ship.
- Wind speed comes from the adopted fan-rpm calibration (Test 1, 13 Feb 2026). The report discloses
  that only 0–700 rpm was measured.
- Rotors are named by fuzzy-skin thickness: Plain, FS 0.05, FS 0.10, FS 0.20 (formerly
  smooth/Ra20/Ra40/Ra80).
- **Rotor speed (4 Oct):** T. Kang's 1 Oct RPM summaries are in. They are filed in
  `inputs/taegu_rpm_20261001/`; that folder's README covers provenance, checksums and what
  `RPM.m` does.
  - Each summary gives one value per set point: the most frequent per-revolution speed, which is
    the light-load speed from 600 rpm.
  - At 500 rpm the fan settles with the load at 10 mA (the interlock arms the load before the fan
    starts). That value isn't light-load and isn't used.
  - The summaries have no time stamps; his script assigns segments to set points in order.
- **Prints (4 Oct):** all four sets were printed by the College of Engineering's I²(s) Print Lab
  (coe3d@etal.uri.edu), from T. Richards's CAD model. A. Muszynski helped with the fuzzy-skin
  settings. The slicer file is the Print Lab's `turbine_default.3mf`.
- No acknowledgement of J. Lopez Olivan (Stephen, 4 Oct).
- **Title and authors (Stephen, 5 Oct):** "Peak electrical power of a small vertical-axis wind
  turbine with 3D-printed textured blades". The title must say power.
  - Subtitle: "Wind-tunnel tests of one plain and three fuzzy-skin blade sets, with rotor speed and
    surface roughness". The previous "four fuzzy-skin blade sets" was incorrect (Plain has none).
    It was corrected on 5 Oct and flagged to Stephen.
  - Prepared by Stephen Eacuello **and Taegu Kang**; Taegu is off the "For" line and out of the
    acknowledgement.
- **Writing (Stephen, 5 Oct):** the report follows his master framework (v3; memory
  `feedback-scientific-writing-rules`). Substantive edits are logged in `EDIT_LOG.md`.
  - The Introduction states four research questions, each traced to a method, a Results section and
    a numbered conclusion.
  - The Abstract replaces the Summary.
  - The Introduction cites verified literature (Prusa fuzzy skin, Wilcox et al. SAND2017-11288,
    Achenbach 1971, Akwa et al. 2012).
  - Results are observed and derived only; interpretation sits in the new Discussion (§7).

## Status
- **Report:** `report/report.pdf`, 18 pages. Every number is a macro in `build/numbers.tex` (381).
- **Pipeline:**
  - `src/data.py`: loading, peak power, Thévenin fits, calibration fitted from the CSV, geometry,
    and `rotor_speed()` / `tacho_fs()` for T. Kang's files;
  - `src/analysis.py`: Tukey HSD, nested ANOVA, permutation test, mounting tipping points, drift
    model, and `speed()` for the rotor-speed analysis;
  - `src/build_report.py`: macros, tables, derived CSVs and integrity checks. The rotor-speed
    checks are:
    - set points match the runs;
    - every speed is 60·Fs/k for a whole number of samples k;
    - V1/n0 varies by less than 5% (alignment) and shows no resolved difference between rotors;
    - V1 (continuous) makes the same Tukey calls as the quantised n0.
  - `src/figures.py` (adds `fig_speed`), `src/keyence.py` (surface), `src/slicer.py` (.3mf
    summary).
- **Package:** `out/URI_VAWT_Texture_Data_2026-10-01.zip`, 75 files (74 listed in MANIFEST.csv plus
  itself), about 10.5 MB, 1 Oct data only.
  - Layout: `1_rig_sweeps`, `2_rotor_speed`, `3_surface_scans`, `4_derived`, `5_reference`,
    `6_figures`, `7_code`.
  - The build re-runs the shipped code and fails unless `4_derived/` and `numbers.tex` reproduce
    exactly. They also reproduce byte for byte with numpy 1.26, scipy 1.12, pandas 2.2 and
    matplotlib 3.8.
- **Emails:** `COVER_EMAIL_DRAFT.md` holds the group email and an optional note to Taegu asking for
  the per-sample tachometer files.

## Headline (Tukey simultaneous 95%, run-to-run on one mounting)
| rotor | peak power vs Plain | drift-adjusted | light-load speed vs Plain |
|---|---|---|---|
| FS 0.05 | +1.8% [−0.6, +4.2] (not resolved) | +0.9% [−2.3, +4.2] | +1.5% [+0.1, +2.9] (barely resolved) |
| FS 0.10 | +12.8% [+10.1, +15.5] | +11.5% [+7.0, +16.1] | +6.6% [+5.1, +8.1] |
| FS 0.20 | +16.2% [+13.5, +19.0] | +14.5% [+8.9, +20.4] | +9.1% [+7.6, +10.6] |

Speed is at 600–1800 rpm.

- FS 0.20 vs FS 0.10: power +3.0% [+0.6, +5.5]. It stays resolved with the fit estimator, but
  only just (lower limit +0.03%), and up to a mounting variation of only 0.3%. Speed +2.4%
  [+1.0, +3.8].
- **Source of the gain.**
  - Averaged over wind speed, the power gain is in the extrapolated V_oc (+6.4% and +8.5%), with
    no resolved change in R_int. Where the gains are largest, a lower R_int supplies up to 43%. The
    speed changes match V_oc and V1 within 0.7 percentage points.
  - V1 = 32.1 mV/rpm × n0 − 0.22 V. V1/n0 is 31.5 mV/rpm (CV 1.7%) and shows no resolved
    difference between rotors (largest +0.7% [−0.7, +2.1]).
  - We infer that the higher voltage comes from rotor speed, not from a generator change. Whether
    the speed comes from aerodynamic or resisting torque is not determined.
- **Tip-speed ratio** at light load (on the attachment radius R): 0.13–0.14 at 12.4 m/s,
  rising to 0.21–0.24 at 38.0 m/s (61–81%). A drag rotor without resisting torque, whose torque
  coefficient depends on λ alone, would hold it constant.
- **Dependence on wind speed:**
  - power, rotor × wind-speed interaction F(39,52) = 9.2, gains largest at 21–25 m/s;
  - speed, F(36,48) = 6.7: FS 0.20 is 1–6% faster up to 18.8 m/s and
    9–16% from 20.9 m/s.

## Rebuild
```bash
python3 src/slicer.py inputs/slicer/turbine_default.3mf   # only if the .3mf changes
python3 src/build_report.py                               # numbers, tables, figures, derived CSVs
cd report && latexmk -pdf report.tex                      # 18 pp
python3 src/build_package.py                              # zip; self-checks reproduction
```

## Review log
- **1 Oct:** two independent verification rounds on the earlier (Aug–Sep based) versions.
- **2 Oct, round 1:** a workflow with 2 verifiers, 5 reviewers and an adjudicator. No numerical
  errors were found; 28 confirmed wording, statistics and package fixes were applied, and 21
  findings were rejected.
- **2 Oct, round 2:** three agents re-verified every new number; adjudicated by hand.
- **5 Oct (writing, v3):** the second audit's 114 findings were adjudicated by hand, because its
  verifiers hit the session limit. The valid ones were applied (`EDIT_LOG.md` entries 15–27).
  - New macros: `vOff`, `vocBelowMeanLo/Hi`, `akwaLo/Hi`, `keBound`, `PaDiffAB` and `RaDiffAB`.
    The last two have a build check.
  - The previous package's own code was re-run: all 356 of its macros have the same values now,
    and `4_derived/` is byte-identical.
- **4 Oct (rotor speed and prints):** three independent agents checked the update:
  - recomputation of every rotor-speed number from the raw files;
  - print records and package docs against the 3mf, `RPM.m` and the emails;
  - a professor-style critical read.

  Every pre-existing macro and table was unchanged by the update (checked against a snapshot of
  the 2 Oct build).

## Open items for Stephen
1. Before sending, rebuild in order (build_report → latexmk → build_package) and check that
   the PDF inside the zip has the current title and authors. Then send the group email
   (`COVER_EMAIL_DRAFT.md` §1).
2. Optional: ask Taegu to share the nine per-sample `*_RPM.csv` files (§2). His Drive links need
   his sharing, and neither the Drive connector nor a direct download could open them. With them,
   join on time to get speed at every dwell, C_P,el(λ) and the generator's internal resistance.
3. Next round:
   - replicate prints in one job from one project file, including Plain at 0.1 mm layers, at the
     Print Lab or in house once the 0.2 mm nozzle arrives;
   - remount between runs, with an interleaved order and the Plain reference re-run after every
     third rotor;
   - connect a once-per-revolution sensor to the rig's pulse input;
   - connect the tunnel node (ambient air) and document the test-section size.

## Notes
- The header `clock` is written at the END of a run. Start and end times come from the dwell
  timestamps.
- Build interpreter: system `python3` (the repo venv lacks pandas and matplotlib).
- T. Kang's files use CRLF line endings; the repo has no `.gitattributes`, so git keeps them byte
  for byte. Keep it that way, because the package checksums depend on it.
