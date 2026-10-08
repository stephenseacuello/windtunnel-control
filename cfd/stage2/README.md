# stage2: roughness bounds for the 2D blade section (PLAN.md Stage 2)

Status, 8 Oct 2026: **set up and tested; no production case run.** Mesher, case template,
`run_case.py`, `queue.py`, queues, comparison scripts and post-case hook written; short solver
tests on 2 ranks on the efficiency cores (section 7). The Stage 1 queue (`../section2d/`) and the
static rotor queue (`../rotor2d/`) were running throughout and were not touched: nothing under
`../section2d/`, `../rotor2d/` or `../post/` was edited (section 8, hook).

Independent review, 8 Oct 2026 (section 7, tests R1-R5): fixed a mesher bug that left the outer
face smooth from tip A to its middle on every texture mesh (`Texture.delta` did not wrap the loop
arc length), so tests 2, 2b and 3 below ran on a partly textured wall and the section 4 table is
re-measured; all tex cases now share one set of numerics (section 4); omega wall-function blending
corrected (binomial, not stepwise; section 3).

Provenance labels: *measured* (read from a run or a log), *calculated* (from measured values or
geometry), *assumed*, *estimated* (an extrapolation), *literature-established*, *uncertain*.
Conventions (body frame, alpha, coefficients on c_ref = 48 mm per unit span): as Stage 1,
[`../section2d/README.md`](../section2d/README.md) section 1. Mapping of the measured roughness to
ks: [`../docs/ROUGHNESS_KS.md`](../docs/ROUGHNESS_KS.md).

## 1. What Stage 2 computes, and why

Question (meeting of 7 Oct): does fuzzy-skin roughness raise rotor power by tripping the blade
boundary layer? OpenFOAM v2606 has no roughness-induced transition model (PLAN.md), so Stage 2
bounds the effect from three sides:

| Part | Question | Method | Cases | Where |
|---|---|---|---|---|
| 2a | The most that tripping can change | kOmegaSST (turbulent from the leading edge, "tripped") against kOmegaSSTLM (free transition), same mesh and free stream | Stage 1 queue priority 2: alpha 0 and 180 x 10.2 / 23 / 38 m/s x SST and LM (medium, Tu 1 %); priorities 1 and 3 add alpha 90 | already running in `../section2d/`; `compare_transition.py` reads the results |
| 2b | Skin-friction and form-drag penalty of a turbulent rough wall | kOmegaSST + `nutkRoughWallFunction` on a wall-function mesh, Ks = 0-400 um | 21 (S2a 15, S2b 6) | `queues/S2a_ks_U23.txt`, `queues/S2b_speeds.txt` |
| 2e | Geometric effect of the fuzzy texture itself, including tripping by it | the nominal texture meshed into the wall (low-Re, y+ < 1), SST and LM | 16 (S2c) | `queues/S2c_texture.txt` |

How the parts fit (*inferred*, to be tested by the runs): 2a gives the size of the tripping
effect that the hypothesis needs; 2b gives the penalty that roughness adds once the layer is
turbulent; 2e shows whether resolved ridges trip the LM layer in this model. If the 2a difference
is small next to the measured power changes, tripping of the section in 2D URANS cannot explain
them; if 2b's penalty exceeds 2a's gain, a rough tripped wall loses. A small or null effect is a
legitimate result (PLAN.md risks).

## 2. Stage 2a: transition bracket (Stage 1 cases)

No new cases. Stage 1 priority 2 runs every alpha 0 / 180 x 10.2 / 23 / 38 m/s case with both
models on the medium mesh, Tu 1 % (12 cases); priority 1 (SST) and priority 3 (LM) add the alpha 90
pair at 23 m/s. When those rows are in `../section2d/results/section_polars.csv`:

```zsh
python3 cfd/stage2/compare_transition.py            # -> results/transition_bracket.csv/.md/.png
python3 cfd/stage2/compare_transition.py --stage2   # also SST-LM pairs of the 2e texture cases
```

A pair is two complete cases whose names differ only in the model token, so mesh, Tu, run length
and time step match. Output per pair: dX = X_SST - X_LM for Cd, Cd_pressure, Cd_viscous, Cl, Cm,
St, and dCd in %. `resolved` compares |dCd| with the sum of the two cases' Cd drifts (second half of
the averaging window minus the first); 'no' bounds the difference, it does not show equality.
On 8 Oct the CSV did not exist yet (case 1 of 31 running); the script was tested on a synthetic CSV.

Caveats: LM transitions early in our T3A check (onset Re_x 0.80 of the measured value,
`../docs/LEARNING_LOG.md` section 3), is calibrated for attached layers, and responds to the
assumed Tu (1 %). SST-LM is therefore a model bracket, not a measurement of tripping.

## 3. Stage 2b: rough turbulent wall (wall functions)

### Mesh: level `wf` (`mesh/make_mesh.py`)

Stage 1's generator (copied) with a two-layer wall-function ring:

| Item | Value |
|---|---|
| First cell h0 | from a flat-plate u_tau at the case speed (Schlichting cf = 0.0592 Re_x^-0.2, x = 22.3 mm) for a first-cell-centre y+ of 40, but at least 2 x 1.1 x 400 um (so y_P = h0/2 >= 1.1 x the largest Ks) and at most 1.3 mm (wall and end faces 1.854 mm) |
| h0 / y_P / flat-plate y+ (*calculated*) | 10.2 m/s: 1.30 mm / 650 um / 28.8; 23 m/s: 0.88 mm / 440 um / 40.5; 38 m/s: 0.88 mm / 440 um / 63.6 |
| Ring | 2 layers, growth 1.15 (1.89 mm at 23 m/s); wall spacing 0.20 mm at the corners to 0.30 mm; end faces 8 cells each |
| Outer region | Stage 1 medium sizes (near body 0.30 mm, wake 0.60 / 1.2 mm, far field 27 c) |
| Cells, checkMesh (*measured*, 23 m/s, alpha 0) | 102,251; max non-orthogonality 40.4 deg, skewness 2.06, aspect 4.1: Mesh OK |
| Patches | `blade` (outer + inner surface: the fuzzy-skin "painted" faces, 459 faces), `bladeEnds` (two square end faces, 16 faces), `farfield`, `frontAndBack`; walls in group `bladeWall` |

One h0 per speed for every Ks, so each Ks is compared with Ks = 0 on the same mesh. The 400 um
floor sets h0 at 23 and 38 m/s; at 10.2 m/s the cap does.

**Measured y+ (start-up flow, Ks 100 um, 23 m/s, 0.3-0.5 c/U after the impulsive start).** Two
definitions: y+ from the wall shear stress (the `yPlus1` function object, `useWallFunction false` as
Stage 1; this is what the CSV reports) and the wall function's own y* = Cmu^0.25 sqrt(k_P) y_P/nu
(`pimpleFoam -postProcess -func yPlus`).

| | y+ (wall shear), painted faces: mean / max | y*, painted faces: mean / median / 10-90 % / max | y* below 11.53 / above 30 | y*, convex face / concave face (mean) | y+ end faces (mean) |
|---|---|---|---|---|---|
| alpha 0 | 17.2-21.2 / 55-76 (0.15-0.45 c/U) | 17.2 / 12.7 / 6.8-42.3 / 54.9 (0.50 c/U) | 44 % / 16 % | 22.9 / 10.9 | 42-47 |
| alpha 180 | 23.3-23.6 / 53-59 (0.15-0.45 c/U) | 15.7 / 14.9 / 7.5-26.0 / 34.8 (0.40 c/U) | 34 % / 5 % | 19.5 / 11.5 | 25-36 |

So the flat-plate sizing (y+ 40.5) gives a measured mean of 16-24 on the painted faces, about half
the design value: at alpha 0 the cup is stagnant and the convex side lies in the separated wake, and
at alpha 180 the cup is in the wake. The developed flow will differ from these start-up values.
h0 was not raised: the turbulent boundary layer at these Reynolds numbers is thin (flat plate
at x = 22 mm: delta = 0.37 x Re_x^-0.2 = 1.03 mm, delta+ = 94 at 23 m/s; 1.21 mm / 53 at 10.2 m/s;
0.93 mm / 134 at 38 m/s, *calculated*), so the 0.44 mm first-cell centre already sits at about 40 %
of delta, and the 1.3 mm cap would put it at 60 %. Wall functions are marginal on this section at
any h0; this is a limitation of the method here (section 9), not of the sizing alone.

### Case set-up (`case_template/`, `run_case.py --wall wf`)

| Item | Setting |
|---|---|
| Model | `kOmegaSST` only (the transition model needs the low-Re wall); free stream, decay control, schemes, PIMPLE, maxCo 5, run length 150 c/U and averaging over the last 100: exactly Stage 1 (`../section2d/README.md` section 3) |
| `blade` | U noSlip; k `kqRWallFunction`; omega `omegaWallFunction` with the v2606 default blending `binomial`, n = 2 (omega_P = sqrt(omega_vis^2 + omega_log^2), production G from the log law at every y*; *measured*: the running Stage 1 case writes `blending binomial; n 2;`), as Stage 1; nut `nutkRoughWallFunction`, Ks = `--ks` (um), Cs 0.5 |
| `bladeEnds` | as `blade`, but Ks = `--ks-ends` (default 0: the end faces are not painted; *inferred* from the slicer project, `../docs/ROUGHNESS_KS.md` section 2) |
| Ks = 0 | the same condition with Ks 0 (smooth reference); not `nutkWallFunction`, which differs below y+ 11.53 (next paragraph) |
| Forces | both wall patches |

What `nutkRoughWallFunction` does (v2606 source, read 8 Oct): u* = Cmu^0.25 sqrt(k_P), Ks+ = u* Ks/nu,
E is divided by a roughness function for Ks+ > 2.25, and nu_t,w = nu (y+ kappa / ln(E' y+) - 1), limited
to 0.5-2 times its previous value. It has no laminar (y+ < 11.53) branch: where the log law gives
a negative value, the limiter holds nu_t,w at 0.5 nu or above. The smooth reference therefore uses
the same condition with Ks = 0, so that only Ks changes between cases.

**Validity.** y_P must exceed Ks (first cell centre above the roughness): Ks/y_P = 0.11-0.91 at
23 m/s, 0.23-0.45 at 38 m/s and 0.15-0.31 at 10.2 m/s for the queued values (*calculated*; `Ks_over_yP` in each CSV
row). Ks+ at the flat-plate u*: 4.6-37 at 23 m/s for 50-400 um (`../docs/ROUGHNESS_KS.md` section 4),
transitionally rough; each case reports its own `ksplus_blade_*`.

### Sweep (queues)

| Queue | Cases |
|---|---|
| `S2a_ks_U23.txt` | 23 m/s, Ks 0 / 50 / 100 / 200 / 400 um at alpha 180, then 0, then 90 (15). alpha 180 first: the convex side faces the wind, its layer can separate before the tips, so wall shear can move separation; at alpha 0 the square tips fix it. |
| `S2b_speeds.txt` | alpha 0, Ks 0 / 100 / 200 um at 10.2 and 38 m/s (6); one mesh per speed |

Mapping of the measured surfaces to Ks (`../docs/ROUGHNESS_KS.md`): plausible ks 25-420 um (scans
25-170 um, scan height k 38-97 um, nominal FS 0.20 texture about 420 um); the sweep covers it. ks is
a sensitivity parameter here, not a value derived for each rotor.

## 4. Stage 2e: resolved fuzzy-skin texture

### Mesh: level `tex`

| Item | Value |
|---|---|
| Texture | painted faces (outer and inner surface) displaced along the smooth-wall normal by delta(s) = t u(s): u uniform in [-1, 1] at points every 0.2 mm of arc length (0.2001-0.2002 mm: each face's length divided into whole intervals), linear in between, 0 at the corners; amplitude ramped from 0 at each corner to full 0.8 mm from it (smoothstep); end faces not displaced. One seed (1) draws u once, so every t has the same pattern scaled by t. |
| Profile statistics (*calculated*) | Ra = 0.397 t, Rq = 0.471 t (Monte Carlo of the linear profile); facet slopes up to 2t / 0.2 mm |
| Near-wall cells | h0 4.5 um (as Stage 1; low-Re, y+ < 1), 5 cells per 0.2 mm interval (40 um); ring layers grow by 1.15 to 60 um, then constant, to max(0.6 mm, D) |
| Fade-out | the displacement decays through the ring as 1 - smoothstep(d/D), D = 2.5 t + 0.1 mm: the first cells keep h0, cell heights change by at most 1.5 t/D (33 % at t = 0.05 mm to 57 % at 0.805 mm), and the ring edge where gmsh starts is not displaced |
| Outer region | Stage 1 medium sizes |
| `t = 0` | the same mesh without displacement: the reference for each t |

Mesh quality (*measured*, checkMesh, alpha 0, seed 1, texture on the whole of both painted faces,
review of 8 Oct; generation 2.0-2.4 min each on an efficiency core):

| t (mm) | Cells | Ring layers | Max facet tilt (deg) | Max non-orthogonality (deg) | Max skewness | checkMesh | Usable |
|---|---|---|---|---|---|---|---|
| 0 | 215,550 | 23 | 0 | 38.6 | 2.42 | Mesh OK | yes (reference) |
| 0.05 | 215,550 | 23 | 26.1 | 38.6 | 2.42 | Mesh OK | yes |
| 0.10 | 215,550 | 23 | 44.4 | 44.6 | 2.42 | Mesh OK | yes |
| 0.20 | 215,550 | 23 | 63.0 | 63.2 | 4.48 (20 faces > 4) | failed 1 check (skewness) | yes, relaxed rule below |
| 0.40 | 243,650 | 31 | 75.7 | 77.0 (5410 faces > 70) | 8.66 (1019 faces > 4) | failed 1 check | no |
| 0.805 | - | 48 | 82.8 | - | - | generator stops: 65 inverted ring cells | no |

The t = 0.40 and 0.805 rows are from the partly textured meshes made before the fix (not re-run;
the full texture can only add steep facets, so they stay unusable). For t <= 0.2 the ring is
0.6 mm thick at every t, and the t = 0 and t = 0.2 meshes have the same points in the same order
apart from 157,458 ring points moved by at most 0.200 mm, and the same faces (*measured*: a few
outer cells are numbered differently by gmsh, which `renumberMesh` reorders anyway). The skew
faces at t = 0.2 (located before the fix; their count and maximum are unchanged by it) sit 0.1-0.3 mm off the wall above a single-sample spike (consecutive samples near
-t, +t, -t: a 0.4 mm-wide peak with 63 deg flanks) and a narrow V-valley, where the layers converge.

**Relaxed acceptance (tex only).** `run_case.py` accepts a texture mesh whose only failed
checkMesh test is skewness, with max skewness <= 8 and max non-orthogonality <= 85 deg, and
records it in `case.json` and the CSV (`mesh_check`). Every tex case, t = 0 included, runs with
`limited corrected 0.33` and one non-orthogonal corrector (Stage 1: 0.5, 0): without them the
t = 0.2 case diverged after 40 steps (section 7, test 2), and applying them to all t keeps each t
and its t = 0 reference on the same numerics (until the 8 Oct review they were switched on per
mesh, above 60 deg, which would have mixed a scheme change into the t = 0.2 comparison). A wf mesh
above 60 deg would get them too (none is: 40-48 deg).

**t = 0.40 and 0.805 (planned FS 0.40 / FS 0.80).** The nominal linear texture at 0.2 mm has facets
of 76 and 83 deg and V-valleys a few degrees wide; a layered body-fitted ring cannot follow them at
y+ < 1. They are listed, commented out, in `S2c_texture.txt`. Options (none implemented): a
bead-width model of the printed surface (which still keeps steep valley walls), an unstructured
boundary-layer mesher (gmsh BoundaryLayer field or snappyHexMesh), or measuring the printed
texture first and meshing that.

### Cases (`S2c_texture.txt`)

23 m/s, SST and LM, low-Re wall as Stage 1 (k = 0, `nutLowReWallFunction`, `omegaWallFunction`),
t = 0 / 0.20 / 0.10 / 0.05 mm, alpha 180 then 0, LM before SST; 80 c/U, averaged over the last 50
(cost, section 6). Compare each t with t = 0 of the same model and alpha (`compare_roughness.py`).

**Caveats.**
- 2D makes the texture spanwise-uniform ridges. Printed upright, the real displacement changes
  from layer to layer (3D random texture). Ridges trip a laminar layer at lower roughness Reynolds
  numbers than 3D roughness (meeting notes: Re_k about 40-260 for 2D against 600-900 (k/d)^0.4 for
  isolated 3D roughness), so 2e overstates tripping.
- The texture is the nominal slicer displacement; the scans measured Ra 8-13 um, 2-8 times
  below the nominal Ra (0.397 t), so the printed texture may be smaller (`../docs/ROUGHNESS_KS.md`
  section 2).
- 40 um wall spacing gives 5 cells per facet; no resolution check was run (`nseg=10` in a queue
  line doubles it).
- LM's response to geometric ridges is outside its calibration.

## 5. Running

```zsh
cd /Users/stepheneacuello/Projects/windtunnel-control
# one case (4 ranks by default; tests: --np 2 --name _test_x --wall-limit 300)
python3 cfd/stage2/run_case.py --alpha 180 --U 23 --wall wf --ks 100
python3 cfd/stage2/run_case.py --alpha 180 --U 23 --wall tex --tex 0.2 --model LM --nconv 80 --navg 50
python3 cfd/stage2/run_case.py ... --setup-only                      # mesh + case only

# queues (resume-safe; status, pause, CSV as Stage 1)
python3 cfd/stage2/queue.py --status cfd/stage2/queues/S2*.txt
python3 cfd/stage2/queue.py --detach queues/S2a_ks_U23.txt queues/S2b_speeds.txt queues/S2c_texture.txt
python3 cfd/stage2/queue.py --pause
python3 cfd/stage2/queue.py --csv                                     # results/stage2_polars.csv
python3 cfd/stage2/compare_roughness.py                               # results/roughness_effects.csv/.md

# alongside Stage 1: efficiency cores only, 2 ranks (slow: section 6)
taskpolicy -c background python3 cfd/stage2/queue.py --detach --np 2 queues/S2a_ks_U23.txt
```

Do not start a Stage 2 queue on the performance cores while Stage 1 runs there; the rotor queue
already holds 2 of the 4 efficiency cores (8 Oct). Paths: `runs/<case>/` (git-ignored), meshes cached
in `runs/_mesh/` (wf per speed and alpha, tex per t, seed, nseg and alpha), checkMesh logs and
`mesh_info` copies in `mesh/logs/`, results in `results/`.

Queue lines: `alpha U model wall [key=value ...]`, keys `ks`, `ksends` (um), `cs`, `t` (mm),
`seed`, `nseg`, `tu`, `maxco`, `nouter`, `nconv`, `navg`, `lt`, `decay`. Case names:
`a180.0_U23.0_SST_wf_Ks100_Tu1.0`, `a180.0_U23.0_LM_tex0.200_s1_Tu1.0_N80A50`, plus Stage 1's suffixes
for non-default settings; folders starting with `_` are tests and stay out of the CSV.

The queue behaves as Stage 1's (`../section2d/README.md` section 4): skips complete cases, resumes
partial ones from the last write, refuses to resume a case whose parameters changed, waits for AC
power, writes `runs/<case>/RUNNING` while the solver runs, rebuilds the CSV after each case. Added:
`queues/LOCK` (one Stage 2 queue at a time) and `--np`.

## 6. Cost per case (estimated from the tests of section 7)

Inputs: seconds per step *measured* at start-up on 2 efficiency-core ranks (with the rotor queue's
2 ranks on the other two); seconds per pressure iteration for 4 performance-core ranks *calculated*
from Stage 1 medium (7.1-8.9 ms per p-iteration for 131k cells, `../docs/RUN_JOURNAL.md` and the
running case's log), scaled by cell count; pressure iterations per step from start-up up to 1.4
times (Stage 1 rose from 21 to 31-40 as its flow developed); developed time steps *estimated*
(below).

| | wf (102k cells, 150 c/U) | tex (216k cells, 80 c/U) |
|---|---|---|
| s/step, 2 efficiency cores | 1.29-1.47 measured (28-33 p-it.) -> 1.3-1.8 | 3.2 measured (35-37 p-it., with the non-orth. corrector) -> 3.2-4.5 |
| s/step, 4 performance cores | 0.15-0.29 | 0.41-0.76 |
| dt | measured 6.2-10.4 us over 0.05-0.67 c/U (alpha 0 and 180), set by start-up tip vortices in 0.13-0.21 mm outer cells (Co 5); developed 5-8 us assumed (Stage 1 fell 25 % from its 5 c/U peak) | measured 0.52 us at 0.01 c/U, against Stage 1's 0.68 us at the same time; developed 1.2-2.4 us assumed (0.5-1.0 x Stage 1's 2.4 us at 20-27 c/U) |
| Steps | 39k-63k | 70k-139k |
| Per case, 4 performance cores | 1.6-5.1 h | 8-29 h |
| Per case, 2 efficiency cores | 14-32 h | 62-174 h |

| Queue | 4 performance cores | 2 efficiency cores |
|---|---|---|
| S2a (15 wf) | 24-77 h | 210-480 h |
| S2b (6 wf) | 10-31 h | 84-190 h |
| S2c (16 tex) | 130-460 h | not practical |

Order of use: S2a and S2b on the performance cores once Stage 1 has finished (or S2a on the
efficiency cores now, at about 9-20 days); S2c afterwards, starting with its four alpha 180 LM
cases (32-116 h). The first case of each kind reports its real s/step and dt in `results.json`;
update this table from it.

## 7. Tests (8 Oct 2026, measured)

All on 2 MPI ranks under `taskpolicy -c background` (efficiency cores) while Stage 1 ran 4 ranks on
the performance cores and the rotor queue 2 ranks on the efficiency cores; test folders deleted
afterwards.

| # | Test | Result |
|---|---|---|
| 1 | wf mesh, 23 m/s, alpha 0, through `run_case.py` (generation, renumberMesh, checkMesh) | 102,251 cells, Mesh OK; 89 s in all |
| 1b | wf, Ks 100 um, alpha 0, 23 m/s, SST, 290 s wall limit | 215 steps to 0.67 c/U; 1.29 s/step (1.14 s CPU), 28-30 p-iterations per step; dt 6.8-8.4 us after 0.09 c/U at Co 5; no bounding; log: "Employing decay control with kInf 0.07935 and omegaInf 514.29563"; Cd 2.8 at 0.65 c/U (start-up). Clean stop at the limit, no processes left. |
| 1c | as 1b, --nconv 1.5 (writes every 0.1 c/U), 240 s | 176 steps to 0.55 c/U, 1.31 s/step; y+ (section 3); max Co cells (section 6) |
| 2 | tex mesh t = 0.2 mm through `run_case.py`; then SST, alpha 0, 23 m/s, 120 s | mesh 215,550 cells, accepted by the relaxed rule (skewness 4.48, 20 faces); solver **diverged** with Stage 1 numerics (limited 0.5, no non-orthogonal corrector): p residual 0.09 -> 0.95 over the last 5 of 42 steps, Co max 5 -> 10.3 -> 13.6, dt -> 0.09 us |
| 2b | as 2 with limited 0.33 and 1 non-orthogonal corrector (now used for every tex case), 180 s | 53 steps to 0.0095 c/U, p residual falling (0.029 -> 0.024), Co 5.0, dt 0.52 us; 3.2 s/step (2.9 s CPU), 35-37 p-iterations per step; k "bounding" every step as in Stage 1 (k = 0 at the wall) |
| 3 | tex meshes t = 0.05, 0.1, 0.4 (+ checkMesh), ring-only check for 0.805 | table in section 4 |
| 4 | wf, Ks 100 um, alpha 180, 23 m/s, --nconv 1.5, 200 s | mesh 103,300 cells, Mesh OK (non-orth. 40.4, skewness 2.06); 143 steps to 0.47 c/U, 1.33 s/step (1.47 over the second half, 29-33 p-iterations); dt 6.2-10.4 us after 0.05 c/U; y+ (section 3); max Co again in the start-up tip vortices 2.6-8.4 mm from the wall |
| 5 | `compare_transition.py`, `compare_roughness.py`, `queue.py --status` on synthetic CSVs and the queue files | outputs as specified; no pairs yet in the real Stage 1 CSV |
| R1 | review: wf mesh 10.2 m/s, alpha 0 (generator + checkMesh, no renumberMesh) | 102,127 cells, h0 1.30 mm, flat-plate y+ 28.8; max non-orth. 47.7, skewness 2.49, aspect 5.7: Mesh OK |
| R2 | review: tex meshes t = 0, 0.05, 0.1, 0.2 with the texture fix (generator + checkMesh) | section 4 table; t = 0 and t = 0.2 compared point by point (section 4) |
| R3 | review: tex t = 0.2 (fixed mesh) through `run_case.py`, SST, alpha 0, 23 m/s, uniform tex numerics (0.33, 1 corrector), 115 s | mesh accepted by the relaxed rule (63.2 deg, skewness 4.48); 35 steps to 0.0052 c/U, 3.1 s/step, Co 5.0, dt 0.52 us, p initial residual of the first corrector falling 0.048 -> 0.035; k bounding as in 2b; clean stop, no processes left. Too short to show stability past the 40 steps where test 2 diverged; the first production tex case is the real check |
| R4 | review: `compare_roughness.py`, `compare_transition.py --stage2` on a synthetic CSV built from the three queues | groups and references as specified (wf per alpha and U against Ks 0; tex per alpha and model against t 0) |
| R5 | review: queue lock helpers on a scratch lock file (live pid refused, dead pid replaced, own lock released) | as specified; `--detach` now refuses before forking when another Stage 2 queue holds `queues/LOCK` |

Tests 2, 2b and 3 used texture meshes whose outer face carried no texture from tip A to its middle
(the bug fixed in the review); their timings stand (same cell count), their mesh quality is
superseded by R2.

## 8. Files

| Path | Contents |
|---|---|
| `mesh/make_mesh.py` | Stage 1 mesher (copy) + levels `wf`, `tex`; wall split into `blade` / `bladeEnds` |
| `mesh/mesh_wf_U23.0_a000.0.png`, `mesh/mesh_tex0.200_s1_a000.0.png`; `mesh/logs/` | generator images and checkMesh logs of the tested meshes (wf 23 m/s alpha 0 and 180, wf 10.2 m/s alpha 0; tex t = 0, 0.05, 0.1, 0.2 alpha 0 with the texture fix; the tex t = 0.2 image is the fixed mesh) |
| `case_template/` | Stage 1 template (copy); walls `blade` + `bladeEnds`; `0.orig/{nut,k}` wall-function versions, `0.lowRe/{nut,k}` low-Re versions; `nonOrthLimit`, `nNonOrthCorr` from `caseParameters` |
| `run_case.py` | one case (wf or tex); mesh cache, relaxed tex acceptance, resume, wall limit |
| `queue.py` | resume-safe queue; CSV `results/stage2_polars.csv`; LOCK; `--np`; post-case hook |
| `stage2_summary.py` | Stage 1 summary (`../post/section_summary.py`) + Ks, t, y+ per patch, Ks+ |
| `compare_transition.py` | 2a bracket from the Stage 1 CSV |
| `compare_roughness.py` | 2b / 2e changes against the smooth reference, next to the 2a bracket |
| `after_case.sh` | post-case hook: `../post/record_case.py --kind section --out results/records/<case>` |
| `queues/S2a_ks_U23.txt`, `S2b_speeds.txt`, `S2c_texture.txt` | the queues |

**Hook.** `../post/after_case.sh` sends every case outside `rotor2d/` to
`../section2d/results/records/`, which would write Stage 2 records into Stage 1's folder; it and
`../post/record_lib.py` (`STAGES`) were not edited because the running queues call them. Stage 2
therefore uses its own `after_case.sh`, which calls the same `record_case.py` with `--out`. Once
`after_case.sh` routes `*/stage2/*` to `cfd/stage2/results/records/`, run the queue with
`--hook cfd/post/after_case.sh`. Tested 8 Oct on the alpha 180 test case: record written in 44 s
(33 files, ParaView images included). **Known defect:** `render_fields.py` orders the wall of patch
`blade` as one closed loop; with the end faces split off, `blade` is two disconnected pieces and the
wall-distribution plots (`fields/surface_*.png/.csv`: Cp, Cf, y+ along the wall) follow only one
connected run (in the test, half of the convex face). Forces, coefficients, the CSV and the other
images are not affected. Fix (in `cfd/post/`, when no queue depends on it): read the patches
`blade` and `bladeEnds` together and order them as one loop.

## 9. Limitations

- 2D URANS overstates shedding coherence and drag; compare changes between cases, not absolute
  values (as Stage 1).
- 2b models a fully turbulent rough wall: no roughness-induced transition. Wall functions are
  marginal here: the turbulent layer is about 1 mm thick (delta+ 53-134), the first cell centre
  sits at about 40 % of it, and the wall function's y* is below 11.53 on 34-44 % of the painted
  faces (start-up flow), where `nutkRoughWallFunction` applies its log law without a laminar
  branch. Read 2b as the sign and rough size of the turbulent rough-wall penalty, not as a
  resolved boundary layer.
- ks is not measured; the sweep brackets the plausible range (`../docs/ROUGHNESS_KS.md`).
- 2e meshes the nominal texture as 2D ridges (over-trips) and cannot mesh t >= 0.4 mm.
- The cost estimates rest on start-up steps (0.01-0.67 c/U); developed-flow time steps are
  assumed from Stage 1's history.
