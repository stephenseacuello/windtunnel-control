# Fuzzy-skin texture report — handoff (updated 2 Oct 2026)

## Scope (Stephen, 2 Oct)
- **1 October 2026 session only.** No June–July lab data, no Aug–Sep rig runs.
- `v1_unk` excluded: one neutral sentence in the report, and none of its files ship.
- Rotor speed and tip-speed ratio are out until T. Kang sends his rotor-RPM record. That record is
  the only thing he has that we lack.
- Wind speed comes from the adopted fan-rpm calibration (Test 1, 13 Feb 2026). The report discloses
  that only 0–700 rpm was measured.
- Rotors are named by fuzzy-skin thickness: Plain, FS 0.05, FS 0.10, FS 0.20 (formerly
  smooth/Ra20/Ra40/Ra80).

## Status
- **Report:** `report/report.pdf`, 14 pages. Every number is a macro in `build/numbers.tex`.
- **Pipeline:**
  - `src/data.py`: loading, peak power, Thévenin fits, calibration fitted from the CSV, geometry
    from `inputs/rotor_geometry.json`;
  - `src/analysis.py`: Tukey HSD, nested ANOVA and interaction tests, exact permutation test,
    mounting tipping points, drift model;
  - `src/build_report.py`: macros, tables, derived CSVs;
  - `src/figures.py`, `src/keyence.py` (surface), `src/slicer.py` (.3mf summary).
- **Package:** `out/URI_VAWT_Texture_Data_2026-10-01.zip`, about 10 MB, 1 Oct data only. The build
  re-runs the shipped code and fails unless `3_derived/` and `numbers.tex` reproduce exactly.
- **Emails:** `COVER_EMAIL_DRAFT.md` holds the group email and an optional rotor-RPM request to
  Taegu. The earlier Gmail draft to Taegu no longer exists; do not recreate it unasked.

## Headline (Tukey simultaneous 95%, run-to-run on one mounting)
| rotor | change vs Plain | drift-adjusted | mounting tipping point |
|---|---|---|---|
| FS 0.05 | +1.8% [−0.6, +4.2] (not resolved) | +0.9% [−2.3, +4.2] | — |
| FS 0.10 | +12.8% [+10.1, +15.5] | +11.5% [+7.0, +16.1] | 2.0% |
| FS 0.20 | +16.2% [+13.5, +19.0] | +14.5% [+8.9, +20.4] | 2.6% |

- FS 0.20 vs FS 0.10: +3.0% [+0.6, +5.5], marginal. With the fit estimator the lower limit is
  +0.03%, and the tipping point is 0.3%. Tipping points use the same Tukey criterion as "resolved".
- Rotor × wind-speed interaction: F(39,52) = 9.2. FS 0.10 and FS 0.20 rise more steeply, and at
  lower wind speed, than Plain. The gains are largest at 21–25 m/s; FS 0.05 overlaps Plain.
- The gain is in the extrapolated V_oc (+6.4% and +8.5%). R_int shows no change on average, but is
  below Plain at 15–25 m/s and above it from 27 m/s.

## Rebuild
```bash
python3 src/slicer.py inputs/slicer/turbine_default.3mf   # only if the .3mf changes
python3 src/build_report.py                               # numbers, tables, figures, derived CSVs
cd report && latexmk -pdf report.tex                      # 14 pp
python3 src/build_package.py                              # zip; self-checks reproduction
```

## Review log
- **1 Oct:** two independent verification rounds on the earlier (Aug–Sep based) versions.
- **2 Oct, round 1:** a workflow with 2 verifiers, 5 reviewers and an adjudicator. No numerical
  errors were found; 28 confirmed wording, statistics and package fixes were applied, and 21
  findings were rejected.
- **2 Oct, round 2:** three agents re-verified every new number; adjudicated by hand after the
  adjudicator hit a session limit. Changes:
  - tipping points switched to the Tukey criterion;
  - corrected a false Ra-spread sentence;
  - steepest rise stated to set-point resolution;
  - ramp dynamics and linear-drift caveats added;
  - R_int sign pattern and share added;
  - realised texture of FS 0.05/FS 0.10 not confirmed by the scans;
  - filter transmission, settling-rule wording and reference order fixed.

  One finding was rejected: a Reynolds-transition hypothesis, which is speculation. Round 1 full
  list:
  `/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/review2/adjudication.md`
  (scratch).

## Open items for Stephen
1. Send the group email (`COVER_EMAIL_DRAFT.md` §1). When Taegu's rotor-RPM record arrives, join it
   on `t_unix` and add λ and C_P,el(λ).
2. Print records: the 0.050 mm and Plain print settings are unknown. Ask whoever printed them.
3. Next round: replicate prints, including Plain at 0.1 mm layers; remount between runs; use an
   interleaved order with the Plain reference re-run after every third rotor; connect the tunnel
   node (ambient air); document the test-section size.
4. Optional: the earlier Keyence thread suggests Juan Lopez Olivan helped with the profilometer.
   Add him to the acknowledgement if so.

## Notes
- The header `clock` is written at the END of a run. Start and end times come from the dwell
  timestamps.
- Build interpreter: system `python3` (the repo venv lacks matplotlib).
