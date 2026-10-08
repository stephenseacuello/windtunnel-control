# section2d: Stage 1, smooth 2D blade section

Status, 8 Oct 2026: **the production queue is running.** Started 2026-10-08 07:33:03 (`queue.py
--detach` on priority 1–3, 31 unique cases), pid 19767, log `results/queue_20261008_073303.log`.
Meshes, case template, run and queue scripts done; smoke test run; reviewer fixes applied and
tested (free-stream decay control, bounded γ, `maxLambdaIter`, post-case hook; §3, §4, §5).
Plan: [`../PLAN.md`](../PLAN.md); run log: [`../docs/RUN_JOURNAL.md`](../docs/RUN_JOURNAL.md).

Provenance labels used below: *measured* (read from a run or a log), *calculated* (derived from
measured values or geometry), *assumed* (an input chosen without data), *estimated* (an
extrapolation).

## 1. Conventions

```
                          y_body (along the outer-tip chord, tip A -> tip B)
                            ^
               tip B  .-----|--.
                     (_.    |   `-.
                        `.  |      `.          convex (outer) surface faces +x
                          : |        \
     U, alpha = 0         : |         |
   ------------------->   : C---------|-------> x_body (normal to the chord,
   ("cup into the wind")  : |         |                 towards the convex side)
                          : |        /
                          : |      .'          concave (inner) surface faces -x
                         .' |    .'
                        /   |  .'
               tip A   '----|-'                C = section centroid = origin = CofR
                            |                  ':' = outer-tip chord line (x_body = -12.37 mm)
```

- **Body frame.** Origin at the centroid of the section area. +x_body is normal to the outer-tip
  chord and points to the convex side; +y_body runs along the chord from tip A (CAD lower) to
  tip B (the curled tip); +z is the span. The section has no symmetry axis (tip B curls, tip A does
  not), so x_body is the reference axis for alpha. Mapping (calculated, `make_mesh.py --frame`):
  x_body = R (x_CAD − c), c = (17.620, 31.507) mm; +x_body points at −4.76 deg and +y_body at
  85.24 deg in the CAD frame of `blades/v1.stl`.
- **Angle of attack.** U∞ = |U| (cos α, sin α, 0) in the body frame, α counter-clockwise from
  +x_body. α = 0: flow along +x_body into the concave side ("cup into the wind"). α = 90: flow
  from tip A towards tip B. α = 180: convex side into the wind. In the CAD frame the flow
  direction is α − 4.76 deg.
- **Coefficients.** q = ½ρU², c_ref = 48.0 mm, A_ref = c_ref × dz, dz = 1 mm (cell depth), so
  all coefficients are per unit span. Cd is along U∞ (dragDir = (cos α, sin α, 0)); Cl is along
  liftDir = z × dragDir = (−sin α, cos α, 0), 90 deg counter-clockwise from U∞. Cm is about +z
  through the centroid, counter-clockwise positive. forceCoeffs' pitch axis is
  liftDir × dragDir = −z (checked in the `coefficient.dat` header), so Cm = −CmPitch; the
  summaries do this conversion.
- **Reference chord.** 48.0 mm is the value in `rotor_geometry.json` and the reports (it equals
  the CAD bounding-box height). The outer tip-to-tip chord of the STL is 46.159 mm, so
  coefficients on that chord would be 3.99 % larger (calculated). Wall thickness: 1.8542 mm from
  the STL (`../geometry/section_v1.json`), not the 1.79 mm in `rotor_geometry.json`.

## 2. Mesh: `mesh/make_mesh.py`

```zsh
cfd/.venv/bin/python cfd/section2d/mesh/make_mesh.py --level medium --alpha 0 --out <dir> --plot <png>
```

`run_case.py` calls it, then `renumberMesh -overwrite` and `checkMesh`, and caches each mesh in
`runs/_mesh/<level>_a<alpha>/` only if checkMesh prints "Mesh OK". It copies every checkMesh log
and `mesh_info.json` to `mesh/logs/`. The venv (`cfd/.venv`, Python 3.14.8) holds gmsh 4.15.2,
numpy, scipy and matplotlib.

**Method.** One parametrised generator, three levels, one cell thick (front and back `empty`).
- *Near-wall ring* (structured quads, generated in Python): layer k lies exactly at distance d_k
  from the wall (offset curves of the section, rounded at the four square corners), so the
  first-cell height and growth ratio hold at every wall node, corners included. Wall nodes near a
  corner fan out over the corner arc gradually with distance from the wall, so no cell is
  degenerate.
- *Outer region* (gmsh, quad-dominant: Frontal-Delaunay for quads with Blossom recombination)
  from the ring edge to a circular far field of radius 27 c_ref = 1.296 m. Size field: a
  near-body zone within 6 mm of the ring, a wake band from −0.6 c to 4 c (half-width 0.75 c) and a
  coarser band to 8 c (half-width 1.5 c), both aligned with U∞, so each α has its own mesh.
- *Writer*: the 2D cells are extruded and written directly as `constant/polyMesh` (patches
  `blade` wall, `farfield` patch, `frontAndBack` empty); no gmshToFoam or extrudeMesh step.

**Why this mesher.** blockMesh would need many hand-placed blocks to wrap both surfaces, both
1.85 mm end faces and the tip curl of a 190 deg-turning spline. snappyHexMesh layers tend to
collapse at square convex corners. gmsh's own boundary-layer field gives less control of the
corner fans. The ring generator guarantees h0 and growth everywhere, and gmsh fills the rest.

**Levels** (calculated by the generator; checkMesh measured, α = 0 / 90 / 180 each):

| Level | Cells (α 0 / 90 / 180) | Ring layers × wall nodes | h0 | Ring growth | Wall spacing at corners / max | Wake cell size (band 1 / 2) | Max non-orth. | Max skewness | Max aspect | checkMesh |
|---|---|---|---|---|---|---|---|---|---|---|
| coarse | 68,500 / 68,617 / 69,135 | 23 × 702 | 4.5 µm | 1.20 | 64 / 210 µm | 0.85 / 1.7 mm | 44.6 deg | 2.46 | 46.5 | Mesh OK (3/3) |
| medium | 131,061 / 131,638 / 131,997 | 27 × 973 | 4.5 µm | 1.15 | 45 / 150 µm | 0.60 / 1.2 mm | 39.6 deg | 2.43 | 31.9 | Mesh OK (3/3) |
| fine | 254,015 / 254,903 / 255,952 | 35 × 1381 | 4.5 µm | 1.10 | 32 / 105 µm | 0.42 / 0.85 mm | 39.5 deg | 2.40 | 23.1 | Mesh OK (3/3) |

The ring quads have interior angles of 45.9–138.4 deg (coarse), 46.4–135.1 (medium) and 47.0–135.1 (fine). The mesh wall nodes lie within 0.048 mm of
`section_v1.csv` (the CSV's own chord error). Generation takes 11–32 s per mesh (measured).
Images: `mesh/mesh_medium_a000.0.png` (far field, near body and wake, section, the tip-B corners),
`mesh/mesh_medium_a090.0.png` (wake band rotated with α), `mesh/mesh_{coarse,fine}_a000.0.png`.

**y+** (target ≤ 1 at 38 m/s, first-cell centre). Measured at 23 m/s, medium, 0.59 c/U (start-up
flow): mean 0.196, max 1.48. 4 of 973 wall faces exceed 1, all within 0.075 mm of a square
corner (B outer, A inner, B inner); more than 1 mm from any corner the maximum is 0.55. Scaled to
38 m/s with u_τ ∝ U^0.9 (calculated): mean 0.31, max 0.87 away from the corners, about 2.3 on the
corner faces. The corner peak is a property of a sharp edge, not of h0 alone. The developed-flow
values come with every case (`yplus_*` in the CSV).

## 3. Case template: `case_template/`

`run_case.py` writes `system/caseParameters` for each case; controlDict, fvSolution,
decomposeParDict, turbulenceProperties and the `0/` fields include it. The template copy is an example
(α 0, 23 m/s, SST, medium).

| Item | Setting |
|---|---|
| Solver | pimpleFoam (incompressible URANS); ν = 1.516e-5 m²/s, ρ = 1.204 kg/m³ (forces only) |
| Turbulence | `kOmegaSST` (fully turbulent) or `kOmegaSSTLM` (γ–Re_θt transition), `--model SST/LM`; free-stream decay control on (`decayControl yes`, kInf, omegaInf; below); LM `maxLambdaIter 50` |
| Far field | U `freestreamVelocity`, p `freestreamPressure`; k, ω, Re_θt, γ `inletOutlet`; ν_t `calculated` |
| Wall `blade` | U `noSlip`; k = 0; ω `omegaWallFunction` (blends to the viscous-sublayer value at y+ < 1, as T3A); ν_t `nutLowReWallFunction`; p, Re_θt, γ zero gradient |
| Free stream | U∞ rotated by α (§1); dragDir and liftDir rotate with it |
| Schemes | `backward` in time, except γ `Euler`; U `linearUpwind` with a cell-limited gradient; k, ω `upwind`; Re_θt `linearUpwind`; γ `limitedLinear01 1`; Laplacian `limited corrected 0.5` (γ choices: §5, tests 6–7) |
| PIMPLE | 2 outer correctors, 2 pressure correctors, momentum predictor; GAMG for p (1e-6, relTol 0.01; final 1e-7) |
| Time step | `adjustTimeStep`, maxCo 5, maxDeltaT c/(20U), first step 1e-5 c/U |
| Run length | 150 c/U by default; averages over the last 100 c/U (`--nconv`, `--navg`) |
| Writes | fields every nconv/15 c/U (10 c/U by default), binary, last 3 kept; histories in `postProcessing/` |
| Parallel | 4 MPI ranks (`--np`), scotch |

**Free-stream turbulence: decay control (default, `--decay control`).** The far field is 1.272 m
(26.5 c) upstream of the body. Without production the SST free stream decays on the way
(k = k₀(1 + βω₀t)^(−β*/β), ω = ω₀/(1 + βω₀t), β = 0.0828, t = L/U). The cases therefore switch on
the model's decay control (Spalart and Rumsey 2007): `decayControl yes; kInf ...; omegaInf ...;`
in `kOmegaSSTCoeffs` (`constant/turbulenceProperties`). Checked in the v2606 source
(`src/TurbulenceModels/turbulenceModels/Base/kOmegaSST/kOmegaSSTBase.C`): the three keywords are
read from the model's coefficient dictionary, `<model>Coeffs`; kInf and omegaInf are used only
when `decayControl` is on (zeroed otherwise), and the solver log then prints "Employing decay
control with kInf ... and omegaInf ...". The model adds β*ω∞k∞ to the k equation and βω∞² to
the ω equation, which cancel the free-stream destruction at k = k∞, ω = ω∞. kOmegaSSTLM derives from kOmegaSST and
reads the same entries from `kOmegaSSTLMCoeffs`, which the template fills from `kOmegaSSTCoeffs`.

`run_case.py` sets the far-field k and ω from the target Tu directly, with no
pre-compensation: k = 1.5(Tu U)², ω = √k/(C_μ^¼ ℓ). It sets kInf and omegaInf to the same
values. Tu at the body then equals the target from t = 0, and everywhere upstream
ν_t/ν = √(3/2) C_μ^¼ Tu U ℓ/ν (calculated). The length scale is fixed at ℓ = 1 mm (assumed;
`--lt`), not the viscosity ratio, so a change of U changes only U, as in the tunnel, where the
screens set ℓ. At the 23 m/s, Tu 1 % baseline this gives ν_t/ν = 10.2 (the T3A tutorial inlet:
12, with ℓ = 1.5 mm). The far-field Re_θt follows Langtry and Menter (2009) for the target Tu.
Calculated values (far field = body):

| U (m/s) | Tu (far field = body) | ν_t/ν | k (m²/s²) | ω (1/s) | Re_θt |
|---|---|---|---|---|---|
| 10.2 | 0.5 / 1 / 3 % | 2.3 / 4.5 / 13.5 | 0.0039 / 0.0156 / 0.140 | 114 / 228 / 684 | 880 / 584 / 182 |
| 23.0 | 0.5 / 1 / 3 % | 5.1 / 10.2 / 30.5 | 0.0198 / 0.0794 / 0.714 | 257 / 514 / 1543 | 880 / 584 / 182 |
| 38.0 | 0.5 / 1 / 3 % | 8.4 / 16.8 / 50.4 | 0.0542 / 0.217 / 1.95 | 425 / 850 / 2549 | 880 / 584 / 182 |

Measured in §5 tests 5 and 6 (coarse, 0.5 c/U, target 1.000 %), the upstream probe (2 c upstream,
`Tu_upstream_probe_pct`) read 1.0015 % (SST, α 0, 23 m/s) and 1.0002 % (LM, α 90, 38 m/s). In
every cell more than 2 c upstream, Tu was 1.0000–1.0013 %, and ν_t/ν was 10.18 (23 m/s) and
16.81 (38 m/s). Without decay control, the same 0.5 c/U would have lowered the probe value to
0.977 % (calculated), so the test tells the two set-ups apart. Between 2 c and 0.5 c ahead of
the body, on the stagnation line, the SST strain production raises Tu to at most 1.29 % (test 5).

**The 7 Oct set-up (`--decay precompensate`).** Kept so the smoke tests (§5, tests 1–4) can be
reproduced; its case names end in `_precomp`. There is no decay control, and the far-field Tu is
raised so that the decay leaves the target at the body, with ℓ = 2 mm. The decay over 1.27 m sets
a floor on ν_t/ν at the body, 1.5 Tu² U β L/ν (calculated), whatever ℓ is:

| U (m/s) | Tu at body | Far-field Tu (ℓ = 2 mm) | ν_t/ν at body | Floor |
|---|---|---|---|---|
| 10.2 | 0.5 / 1 / 3 % | 0.69 / 1.89 / 14.4 % | 6 / 15 / 101 | 3 / 11 / 96 |
| 23.0 | 0.5 / 1 / 3 % | 0.69 / 1.89 / 14.4 % | 13 / 35 / 228 | 6 / 24 / 216 |
| 38.0 | 0.5 / 1 / 3 % | 0.69 / 1.89 / 14.4 % | 22 / 57 / 377 | 10 / 40 / 356 |

It was replaced for three reasons. ν_t/ν at the body is about 3.4 times the decay-control value
at Tu 1 %. The decayed free stream reaches the body only after L/U = 26 c/U; until then the body
sees up to the far-field Tu (1.81 % at 1.08 c/U in test 1, for a 1 % target). The far-field
Re_θt follows the far-field Tu (275 instead of 584 at a 1 % target).

The tunnel's Tu and length scale are not measured (`../MEASUREMENTS_NEEDED.md`); Tu = 1 % and
ℓ = 1 mm are assumed.

**Time step (maxCo 5).** In the smoke test the maximum Courant number sat in about 100 cells
within 0.2 mm of the corners B-outer and A-inner, where the separating shear layer crosses thin
near-wall cells at 20–60 m/s (measured at 0.59 c/U: 99 cells with Co > 2, 512 with Co > 1, of
131,061). In the wake box (x 30–200 mm, |y| < 36 mm) Co ≤ 0.34, mean 0.08, so a shedding period
(about 10 ms at St 0.2) takes about 5,000 steps. maxCo 10 with 2 outer correctors diverged
(§5), so 5 is the default; queue 1 ends with a maxCo 2.5 case to check time-step independence.

**Function objects.**

| Name | Output | Interval |
|---|---|---|
| `forceCoeffs1` | Cd, Cl, CmPitch (and front/rear, side, roll, yaw) | c/(50U) |
| `forces1` | pressure and viscous force and moment, N per 1 mm span | c/(50U) |
| `yPlus1` | min, max, mean y+ on the blade | 1 c/U |
| `wallShearStress1` | field, every step (feeds the average) | written at write times |
| `fieldAverage1` | UMean, UPrime2Mean, pMean, pPrime2Mean, wallShearStressMean over the last 100 c/U | written at write times |
| `probes1` | U, p, k at 1, 2, 4 c downstream (on the wake axis and ±0.5 c) and 2 c upstream | c/(50U) |

The solver log's "fieldAverage fieldAverage1: ... starting averaging at time 0" is printed when the
function object is constructed; averaging starts at `timeStart` (50 c/U by default).

**Disk** (measured): one medium time directory 16 MB without averages, a coarse one with averages
14 MB; the copied mesh is 11–13 MB (coarse), 20–21 MB (medium), 38–39 MB (fine). A finished
medium case keeps the mesh, one reconstructed time and `postProcessing/`, about 50 MB
(estimated); `processor*/` is deleted after reconstruction.

## 4. Running

```zsh
# one case (creates runs/<name>/, runs on 4 ranks, resumes if interrupted)
python3 cfd/section2d/run_case.py --alpha 0 --U 23 --model SST --level medium
python3 cfd/section2d/run_case.py --alpha 90 --U 23 --model LM --level medium --tu 1.0
python3 cfd/section2d/run_case.py ... --setup-only          # create the case only
python3 cfd/section2d/run_case.py ... --wall-limit 600      # kill the solver after 600 s
python3 cfd/section2d/run_case.py ... --np 2 --name _test_x # test: 2 ranks, folder runs/_test_x
python3 cfd/section2d/run_case.py ... --decay precompensate # the 7 Oct free stream (§3)

# the production queue, detached, with caffeinate and a log (results/queue_<date>.log)
cd cfd/section2d && python3 queue.py --detach queues/priority1.txt queues/priority2.txt queues/priority3.txt
python3 queue.py --status queues/priority*.txt     # done / running / stale / partial / pending
python3 queue.py --pause                           # running case writes now and stops; queue exits
rm queues/STOP && python3 queue.py --detach queues/priority1.txt ...   # resume after a pause
python3 queue.py --csv                             # rebuild results/section_polars.csv
python3 ../post/plot_section.py                    # results/section_polars.png (Cd, Cl, Cm, St vs alpha)
```

Case names: `a<alpha>_U<U>_<model>_<level>_Tu<Tu>`, plus `_Co<maxco>n<nouter>`, `_N<nconv>A<navg>`,
`_lt<mm>` (ℓ other than the mode's default: 1 mm, or 2 mm with precompensate) or `_precomp`
(`--decay precompensate`) for any non-default setting, so a test case never shares a folder with a
production case. Default cases keep the names they had before decay control; none had been run
then (only `_smoke_*` and `_test_*` folders existed). `--name` overrides the name. Folders starting with `_`
(`_mesh`, `_smoke_*`, `_test_*`) are not production cases and are left out of the CSV.

- **Resume-safe.** A case with `results.json` marked complete is skipped. A case with processor
  time directories restarts from its last write (`startFrom latestTime`), losing at most one write
  interval, on as many ranks as it was decomposed for. It refuses to resume, without `--force`, if
  U, the far-field or decay-control k and ω, the end time or the model differ. A failed case is
  logged and the queue moves on; re-running retries it.
- **Status.** `--status` counts a case listed in several queue files once. A running case shows
  its progress from `log.pimpleFoam` (last `Time =` in c/U of the end time, and s/step over the
  last 200 steps), since `processor*/` is written only every 10 c/U. `runs/<case>/RUNNING` exists
  while the solver runs and is removed when the solve ends, also on an error or a stop signal; it
  stays only if `run_case.py` is killed outright (SIGKILL, crash, power loss). Such a marker is
  reported as `stale`, not running, once no solver process names the case and the log has not
  been written for 10 min (`--status`, `record_all.py`; `cfd/post/record_lib.py`).
- **Post-case hook.** After a case completes (`results.json` written, CSV rebuilt) the queue runs
  `../post/after_case.sh <case dir>` if that file exists and is executable (records, plots;
  `cfd/post/`). Its output goes to `results/records/after_case.log`; the queue log gets only the
  `hook:` start and end lines. It is killed after 30 min (`HOOK_TIMEOUT_S`).
  A missing hook, a non-zero exit or a timeout is logged, and the queue goes on.
- **Power.** Run on AC power with the lid open (or in clamshell mode with an external display).
  The queue waits for AC power before each case (`--allow-battery` overrides) and holds
  `caffeinate -is`, which blocks idle sleep and, on AC, system sleep. Closing the lid still
  sleeps the laptop. On battery the smoke test slowed by a factor of about 5 and the laptop slept
  at 1 % charge (§5).
- **Other jobs.** Another 4-rank OpenFOAM job (for example `cfd/rotor2d/`) on the same 4
  performance cores slows both; run the queues one at a time. A job held on the efficiency cores
  with `taskpolicy -c background` slowed Stage 1 by no detectable amount in a 5-min test (8 Oct;
  `../rotor2d/README.md`, `../docs/RUN_JOURNAL.md`); this fanless laptop may still throttle under
  hours of 8-core load, so recheck Stage 1's speed after 1-2 h.

**Queues** (`queues/*.txt`; columns `alpha U model level Tu [key=value ...]`, keys `maxco`,
`nouter`, `nconv`, `navg`, `lt`, `decay`; repeated cases are run once):

| File | Cases | Contents (PLAN.md priority order) |
|---|---|---|
| `priority1.txt` | 10 | Mesh study: α 0 / 90 / 180, 23 m/s, SST, coarse / medium / fine; then α 0 medium at maxCo 2.5 |
| `priority2.txt` | 12 (10 new) | α 0 and 180 × 10.2 / 23.0 / 38.0 m/s × SST and LM, medium |
| `priority3.txt` | 13 (11 new) | α 0–180 in 15 deg steps, 23 m/s, LM, medium |
| `priority4.txt` | 15 (optional) | α 195–345 (the section is not symmetric), and Tu 0.5 and 3 % at α 0 and 180 |

**Summary per case** (`results.json`, one CSV row in `results/section_polars.csv`): mean and
standard deviation of Cd, Cl and Cm over the last 100 c/U; Cd split into pressure and viscous
parts; St = f c/U of the largest peak of the Cl spectrum (Hann window, zero padding, parabolic
peak fit) and the share of Cl variance within ±15 % of it; drift of Cd and Cl between the two
halves of the window; y+ (mean of the max, max of the max, mean); Tu at the upstream probe; mean
dt and Co; steps; wall time (`wall_time_s` includes any sleep, `run_time_s` does not) and seconds
per step. `../post/section_summary.py <case>` prints the same for any case.

## 5. Smoke test (7 Oct 2026)

Machine: Apple M2 MacBook Air (4 performance + 4 efficiency cores, 24 GB). Tests 1–4 ran on
4 MPI ranks with the set-up before the reviewer fixes: `--decay precompensate`, γ `linearUpwind`
and `backward`, `maxLambdaIter` 10. Tests 5–8 ran with the current template on the coarse mesh,
2 ranks, while a 2-rank `rotor2d` job was running.

| # | What ran | Result (measured) |
|---|---|---|
| 1 | Medium, α 0, 23 m/s, SST, Tu 1 %, maxCo 5, from t = 0. 875 steps in 566 s to 0.593 c/U, stopped with `writeNow`. | Steps 0–348: 0.17–0.21 s/step. Steps 348–875: 0.39–1.2 s/step; the laptop was on battery and draining. |
| 1b | Case 1 resumed from 0.593 c/U by `run_case.py` (resume path); 511 steps to 1.077 c/U, then killed by `--wall-limit` (timeout path). | The laptop slept at 1 % battery from 19:44 to 22:04 (pmset log) and resumed on AC power. On AC with background load: 0.29–0.37 s/step. No orphaned processes after the kill. |
| 2 | Case 1 state at 0.593 c/U, maxCo 10, 2 outer correctors. | Diverged: the p initial residual rose from 0.015 to 0.3 in 30 steps; at step 50 k reached 2.3e3 and then 2e7 m²/s², and dt fell from 3.8e-6 to 1e-8 s. |
| 3 | Pipeline, coarse, α 0, 23 m/s, SST and LM, 0.3 c/U each, through `queue.py --detach` (SST) and `run_case.py` (LM). | Both reached endTime, reconstructed, wrote `results.json`, the CSV row and the plot; the average fields were written. 0.185 s/step (SST) and 0.193 s/step (LM) with another 2-rank job running. |
| 4 | Scheme check: as 3 (SST), 0.15 c/U, k and ω with `limitedLinear 1`. | ω went negative in 217 of 224 steps; with `upwind`, in 0 of 1,386 (case 1) and 0 of 377 (case 3) steps. |
| 5 | Coarse, α 0, 23 m/s, SST, Tu 1 %, 0.5 c/U (`--nconv 0.5 --navg 0.3 --np 2`), through `run_case.py` to `results.json`. | 536 steps, 0.22 s/step. Log: "Employing decay control". Upstream probe Tu 1.0015 %; more than 2 c upstream, Tu 1.0000–1.0013 % and ν_t/ν 10.18. ω bounding in 0 steps. |
| 6 | As 5, LM, α 90, 38 m/s. | 356 steps, 0.27 s/step. Probe Tu 1.0002 %; ν_t/ν 16.81 upstream. γ, ω and Re_θt bounding in 0 steps; γ 0.020–1.00002 at the end; lambda warning in 0 steps. A first run with `backward` for γ: γ bounding in steps 3–5 (min −0.077), none in the 351 steps after. |
| 7 | γ at the impulsive start: as 6 to 0.02 c/U (63 steps), with (a) `bounded Gauss limitedLinear01 1` and `backward`; (b) `limitedLinear01 1` and `ddt(gammaInt) Euler` (the template). | (a) γ bounding in steps 3–5 (min −0.076), max 1.013 at the end; (b) no bounding, max 1.0004. The start-up undershoot therefore comes from `backward`. Test 3 (LM, `linearUpwind`, `backward`) had it in 8 of 380 steps, at steps 2–4 and 23–75 (min −0.068); with `limitedLinear01`, none came after step 5 (test 6, first run; a different case). |
| 8 | As 6 with the default `maxLambdaIter 10`. | The lambda warning in 356 of 356 steps (with 50: in 0). Cd and Cl within 2e-4 of test 6 (relative). The two runs were decomposed differently, so they are not bit-identical. In v2606 the iteration runs to `lambdaErr` whatever `maxLambdaIter` is, which only sets when the warning is printed. |

Case 1 numbers (measured):
- **dt at maxCo 5:** 1.86 µs at 0.59 c/U and 2.13 µs at 1.08 c/U, still rising (980 steps per
  c/U at 1.08 c/U).
- **Forces** (start-up, not converged): Cd 1.70 (0–0.1 c/U) rising to 2.52 (1.0–1.1 c/U), almost
  all pressure drag (Cd_p 2.45, Cd_v −0.015 after 0.8 c/U); Cl from 0.10 to 1.32 and Cm from 0.56
  to 0.19 over the same span. Cd is of order 1–3 as expected; the semicircular-shell value with
  the concave side to the wind is about 2.3 (PLAN.md, literature, not this blade).
- **y+:** see §2. **Upstream Tu:** 1.81 % at 1.08 c/U; the decayed free stream reaches the body
  after L/U = 26 c/U.
- **Stability at maxCo 5:** the first-corrector p residual fell from 0.035 (steps 60–120) to 0.011
  (steps 840–875); no ω bounding. The k "bounding" message appears every step, as in T3A, because
  `min(k)` includes the k = 0 wall value.

The run folders of tests 1–4 are kept, git-ignored, in `runs/_smoke_*` and `runs/_test_*`; those of
tests 5–8 were deleted after the checks.

## 6. Cost per case (estimated)

Wall time for 150 c/U on 4 ranks. Inputs: 0.17–0.21 s/step for medium SST on an otherwise idle
machine (measured, case 1); dt between 2.13 µs (measured at 1.08 c/U) and an assumed 3.0 µs once
the start-up transient has passed. Other levels are scaled, not measured: cost per step with the
cell count, and dt with the corner wall spacing (64 / 45 / 32 µm; the coarse test's dt was
1.4 times medium's at the same flow time, matching 64/45). LM is taken as 1.05–1.2 times SST per
step (1.05 in test 3). Steps per c/U do not depend on U while dt is Courant-limited.

| Level | SST, idle | LM, idle | SST, with background load (0.29–0.37 s/step) |
|---|---|---|---|
| coarse | 1.8–3.2 h | 1.9–3.8 h | 3.1–5.6 h |
| medium | 4.9–8.6 h | 5.2–10.3 h | 8.4–15.1 h |
| fine | 13.4–23.4 h | 14.1–28.0 h | 22.9–41.2 h |

Queue totals, idle machine: priority 1 70–122 h (the 3 fine cases are 40–70 h of it), priority 2
51–96 h, priority 3 57–113 h; 1–3 together 178–332 h (7.4–13.8 days). The first queue case
reports the real seconds per step and dt in its `results.json`; update these estimates from it.
Ways to cut the cost if needed: fewer convective times (`nconv=100 navg=60` in a queue line saves
a third), or dropping α 90 from the fine level.

## 7. Limitations

- 2D URANS overstates the coherence of shedding and usually the drag; compare relative changes
  between cases, not absolute values (PLAN.md).
- kOmegaSSTLM is calibrated for attached boundary layers; this flow separates at the square
  edges. The Tu and length scale at the body are assumed (§3). Decay control holds the free
  stream at the target Tu, but the SST strain production still raises Tu ahead of the body (to
  1.29 % between 2 c and 0.5 c upstream in test 5), and the LM model responds to that local value.
- The far field is unbounded (no tunnel walls); blockage is Stage 4.
- Time-step independence is not yet shown (queue 1, last case). Mesh independence is the purpose
  of queue 1.
