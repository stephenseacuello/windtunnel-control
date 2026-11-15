# CFD set-up review guide, November 2026

15 Nov 2026 · for R. Cassin · prepared by S. Eacuello

On 1 Nov Dr. Jahangiri asked for mesh and time-step sensitivity, and for the turbulence and
roughness modelling to be examined, before more simulations. This guide is for an independent
check of the set-up behind the 263 finished 2D runs and behind the 25 verification jobs (B1)
submitted to Unity on 15 Nov. The B1 results are not available yet (the jobs take 1–4 days).

- Every setting links to the line that sets it. The links are relative, so they open on GitHub.
  Link text is a path relative to `cfd/`; inside sections 2–5 it is relative to the family's
  folder, named above each table (so `../post/...` is `cfd/post/...`).
- Numbers cite their source. Labels: *measured* (read from a run, log or checkMesh), *calculated*,
  *assumed* (an input chosen without data), *inferred*, *computed* (by the analysis scripts in
  [`analysis/2026-10-15/`](../analysis/2026-10-15/README.md)).
- Please reply by question number (section 8), or name the row and line you think is wrong.

## 1. The four model families

| | (a) Smooth section | (b) Rough wall functions | (c) Resolved texture | (d) Rotor |
|---|---|---|---|---|
| Code | `section2d/` | `stage2/`, `--wall wf` | `stage2/`, `--wall tex` | `rotor2d/` |
| Finished runs (263 in all) | 125 | 37 | 32 | 69 (53 rotating, 16 static) |
| Geometry | v1 blade section; 2D slab 1 mm deep | as (a) | as (a), fuzzy skin meshed into the wall | 3 blades at R = 101.6 mm; slab 10 mm deep |
| Turbulence model (runs) | SST (35), LM (90) | SST | SST (12), LM (20) | SST |
| Wall treatment | low-Re, y+ < 1 | rough log law | low-Re, y+ < 1 | wall functions |
| maxCo (runs) | 5 (42), 2.5 (79), 1.25 (4) | 5 (16), 2.5 (21) | 5 (16), 2.5 (16) | 4 (67), 2 (2) |
| B1 jobs, 15 Nov | 9, plus 2 restarts | none | 8 | 6 |

Run counts and maxCo: [`section2d/results/section_polars.csv`](../section2d/results/section_polars.csv),
[`stage2/results/stage2_polars.csv`](../stage2/results/stage2_polars.csv) (column `wall`),
[`rotor2d/results/rotor_cp.csv`](../rotor2d/results/rotor_cp.csv),
[`rotor2d/results/rotor_static.csv`](../rotor2d/results/rotor_static.csv);
[`analysis/2026-10-15/TEAM_SUMMARY.md:81-85`](../analysis/2026-10-15/TEAM_SUMMARY.md?plain=1#L81-L85).
SST is `kOmegaSST`; LM is `kOmegaSSTLM` (γ–Re_θt transition).

Common to all 263 runs:
- **Code.** OpenFOAM v2606 (ESI), `pimpleFoam`, incompressible URANS. Unity runs the
  `opencfd/openfoam-run:2606` image, built from the same source commit as the Mac app
  ([`hpc/README.md:12`](../hpc/README.md?plain=1#L12)).
- **Fluid.** ν = 1.516e-5 m²/s; ρ = 1.204 kg/m³, used for forces only
  ([`section2d/case_template/constant/transportProperties:17`](../section2d/case_template/constant/transportProperties#L17);
  [`section2d/run_case.py:64-65`](../section2d/run_case.py#L64-L65)).
- **Free stream.** Tu 1 % (also 0.5 and 3 % in 34 LM section runs) and ℓ = 1 mm, held by SST
  decay control (*measured* on 15 Nov in all 194 section and Stage 2 `case.json` files and in the
  69 rotor table rows).
- **PIMPLE.** 2 outer correctors (*measured*: column `nOuter` of the four tables).

## 2. (a) Stage 1: smooth section (`section2d/`)

Link text in this table is relative to `cfd/section2d/`.

| Item | Setting | Where |
|---|---|---|
| Mesh method | Structured near-wall ring of offset curves at exact distances from the wall, so h0 and the growth ratio hold at every wall node; wall nodes fan out over the rounded square corners. Then a gmsh quad-dominant fill (Frontal-Delaunay for quads, Blossom recombination) to a circular far field at 27 c_ref = 1.296 m. Size field: near-body zone within 6 mm of the ring, wake bands from −0.6 c to 4 c (half-width 0.75 c) and to 8 c (1.5 c), aligned with U∞, so each α has its own mesh. One cell deep (dz = 1 mm). Patches `blade` (wall), `farfield` (patch), `frontAndBack` (empty). polyMesh written directly, then `renumberMesh` and `checkMesh` | [mesh/make_mesh.py:4-18](../section2d/mesh/make_mesh.py#L4-L18), [:57-69](../section2d/mesh/make_mesh.py#L57-L69), [:495-502](../section2d/mesh/make_mesh.py#L495-L502); [README.md:65-81](../section2d/README.md?plain=1#L65-L81) |
| Cells, α 0 / 90 / 180 | coarse 68,500 / 68,617 / 69,135; medium 131,061 / 131,638 / 131,997; fine 254,015 / 254,903 / 255,952 | [README.md:85-89](../section2d/README.md?plain=1#L85-L89); e.g. [mesh/logs/checkMesh_medium_a180.0.log:44](../section2d/mesh/logs/checkMesh_medium_a180.0.log#L44) |
| First cell, ring | h0 = 4.5 µm on all levels; ring growth 1.20 / 1.15 / 1.10; 23 / 27 / 35 layers | [mesh/make_mesh.py:58-66](../section2d/mesh/make_mesh.py#L58-L66); [README.md:87-89](../section2d/README.md?plain=1#L87-L89) |
| Wall spacing, corner / max | 64 / 210, 45 / 150, 32 / 105 µm (coarse, medium, fine); 702 / 973 / 1,381 wall nodes | as above |
| y+ (first-cell centre; target ≤ 1 at 38 m/s) | 102 healthy runs (*measured*): blade mean 0.06–0.37; window mean of the blade maximum 0.20–1.68; largest single sample 8.49. In the smoke test every face above 1 lay within 0.075 mm of a square corner | `yplus_*` columns of `results/section_polars.csv`; health: `corrupted` in [`../analysis/2026-10-15/out/section_case_quality.csv`](../analysis/2026-10-15/out/section_case_quality.csv); [README.md:96-101](../section2d/README.md?plain=1#L96-L101) |
| Far field | U `freestreamVelocity` (U∞ rotated by α); p `freestreamPressure` (0); k, ω, Re_θt, γ `inletOutlet`; ν_t `calculated` | [0.orig/U:22-28](../section2d/case_template/0.orig/U#L22-L28), [p:22-27](../section2d/case_template/0.orig/p#L22-L27), [k:22-27](../section2d/case_template/0.orig/k#L22-L27), [omega:22-27](../section2d/case_template/0.orig/omega#L22-L27), [nut:22-26](../section2d/case_template/0.orig/nut#L22-L26), [ReThetat:23-28](../section2d/case_template/0.orig/ReThetat#L23-L28), [gammaInt:23-28](../section2d/case_template/0.orig/gammaInt#L23-L28) |
| Free-stream turbulence | k = 1.5 (Tu U)², ω = √k / (C_μ^¼ ℓ), ℓ = 1 mm (*assumed*; the tunnel's Tu and ℓ are not measured). At 23 m/s and Tu 1 %: k 0.0794 m²/s², ω 514 s⁻¹, ν_t/ν 10.2 (*calculated*). Decay control on, with kInf = k and ωInf = ω, so Tu does not decay between far field and body. Upstream probe, 2 c ahead: Tu 1.0014–1.0171 % in the 70 healthy Tu-1 % runs (*measured*). Precompensation (`--decay precompensate`: no decay control, ℓ 2 mm) was used only in the 7 Oct smoke tests | [run_case.py:85](../section2d/run_case.py#L85), [:131-151](../section2d/run_case.py#L131-L151); [constant/turbulenceProperties:28-38](../section2d/case_template/constant/turbulenceProperties#L28-L38); [README.md:123-174](../section2d/README.md?plain=1#L123-L174) |
| Turbulence model | `kOmegaSST` or `kOmegaSSTLM` (γ–Re_θt); LM `maxLambdaIter 50`. Far-field Re_θt from Langtry and Menter (2009): 584 at Tu 1 % | [constant/turbulenceProperties:21](../section2d/case_template/constant/turbulenceProperties#L21), [:40-48](../section2d/case_template/constant/turbulenceProperties#L40-L48); [run_case.py:121-128](../section2d/run_case.py#L121-L128) |
| Wall `blade` | U `noSlip`; k `fixedValue` 0; ω `omegaWallFunction` (viscous-sublayer value at y+ < 1); ν_t `nutLowReWallFunction` (0); p, Re_θt, γ `zeroGradient` | [0.orig/U:29-32](../section2d/case_template/0.orig/U#L29-L32), [k:28-33](../section2d/case_template/0.orig/k#L28-L33), [omega:28-33](../section2d/case_template/0.orig/omega#L28-L33), [nut:27-32](../section2d/case_template/0.orig/nut#L27-L32) |
| Schemes | ddt `backward` (γ: `Euler`); grad `Gauss linear`; U `linearUpwind` with `cellLimited Gauss linear 1`; k, ω `upwind`; Re_θt `linearUpwind`; γ `limitedLinear01 1`; Laplacian `Gauss linear limited corrected 0.5`; snGrad `limited corrected 0.5`; wall distance `meshWave` | [system/fvSchemes:14-72](../section2d/case_template/system/fvSchemes#L14-L72) |
| Linear solvers | p: GAMG (DICGaussSeidel), 1e-6, relTol 0.01; pFinal: 1e-7, relTol 0. U, k, ω, Re_θt, γ: smoothSolver (symGaussSeidel), 1e-8, relTol 0.1 (Final: relTol 0) | [system/fvSolution:16-46](../section2d/case_template/system/fvSolution#L16-L46) |
| PIMPLE | `nOuterCorrectors 2`, `nCorrectors 2`, `nNonOrthogonalCorrectors 0`, momentum predictor on, `turbOnFinalIterOnly true`; equation relaxation factors 1, no field relaxation set. No `residualControl`, so every step runs exactly 2 outer iterations | [system/fvSolution:48-67](../section2d/case_template/system/fvSolution#L48-L67); [run_case.py:95](../section2d/run_case.py#L95) |
| Time step | `adjustTimeStep`. maxCo is 5 by default; 79 runs used 2.5 and 4 used 1.25. `maxDeltaT` c/(20U); first step 1e-5 c/U. Every run is Courant-limited: time-mean maximum Co 0.991–1.000 × maxCo in all 125 runs (*measured*) | [system/controlDict:27-30](../section2d/case_template/system/controlDict#L27-L30); [run_case.py:94](../section2d/run_case.py#L94), [:213-214](../section2d/run_case.py#L213-L214); `Co_max_mean` in `results/section_polars.csv`; [`../analysis/2026-10-13/RESULTS.md:226-228`](../analysis/2026-10-13/RESULTS.md?plain=1#L226-L228) |
| Run length, averaging | 150 c/U. Force statistics and `fieldAverage` cover the last 100 c/U, from 50 c/U. Drift is the mean of the window's second half minus that of its first half. Fields every 10 c/U, binary, last 3 kept | [run_case.py:96-97](../section2d/run_case.py#L96-L97), [:213](../section2d/run_case.py#L213); [system/controlDict:35-38](../section2d/case_template/system/controlDict#L35-L38), [:113-143](../section2d/case_template/system/controlDict#L113-L143); [`../post/section_summary.py:13-22`](../post/section_summary.py#L13-L22) |
| Forces, coefficients | `forceCoeffs1` and `forces1` on `blade`, every c/(50U). q = ½ρU² with ρ = rhoInf; lRef = c_ref = 0.048 m; Aref = c_ref × dz = 4.8e-5 m² (dz = 1 mm), so coefficients are per unit span. CofR is the section centroid. Cd is along U∞ (dragDir = (cos α, sin α, 0)); Cl is along liftDir = z × dragDir. Cm is about +z, counter-clockwise positive, = −CmPitch. c_ref is the reports' 48.0 mm; the STL tip-to-tip chord is 46.159 mm, which would raise every coefficient by 3.99 % | [system/controlDict:51-82](../section2d/case_template/system/controlDict#L51-L82); [run_case.py:66-67](../section2d/run_case.py#L66-L67), [:204-206](../section2d/run_case.py#L204-L206); [README.md:43-52](../section2d/README.md?plain=1#L43-L52); [`../post/section_summary.py:154`](../post/section_summary.py#L154) |
| Other function objects | `yPlus1` (`useWallFunction false`), once per c/U; `wallShearStress1`, every step; `probes1`: U, p, k at 1, 2 and 4 c downstream (wake axis and ±0.5 c) and 2 c upstream | [system/controlDict:85-110](../section2d/case_template/system/controlDict#L85-L110), [:147-157](../section2d/case_template/system/controlDict#L147-L157); [run_case.py:72-73](../section2d/run_case.py#L72-L73) |
| Mesh acceptance | checkMesh must print "Mesh OK.". All 9 level × α meshes above pass, with maximum non-orthogonality 39.5–44.6° and maximum skewness 2.40–2.46 | [run_case.py:302-310](../section2d/run_case.py#L302-L310); `mesh/logs/` |

## 3. (b) Stage 2: rough wall functions (`stage2/`, `--wall wf`)

The 37 runs:
- 23 m/s at α 0, 90 and 180, Ks 0–400 µm;
- α 0 at 10.2 and 38 m/s, Ks 0, 100 and 200 µm.

Stage 2 has its own copy of the Stage 1 template. Items not listed below are as (a)
([`stage2/README.md:102`](../stage2/README.md?plain=1#L102)). Link text in this table is relative to
`cfd/stage2/`.

| Item | Setting | Where |
|---|---|---|
| Mesh method | Stage 1 generator (copied), with a two-layer wall-function ring (growth 1.15); outer region as Stage 1 medium. The wall is split into `blade` (the two painted faces, outer and inner) and `bladeEnds` (the two square end faces) | [mesh/make_mesh.py:9-15](../stage2/mesh/make_mesh.py#L9-L15), [:32-34](../stage2/mesh/make_mesh.py#L32-L34), [:78-81](../stage2/mesh/make_mesh.py#L78-L81); [README.md:65-74](../stage2/README.md?plain=1#L65-L74) |
| Cells, α 0 / 90 / 180 | 102,251 / 102,851 / 103,300 at 23 m/s; 102,127 at 10.2 m/s, α 0; 102,251 at 38 m/s, α 0 | [mesh/logs/checkMesh_wf_U23.0_a180.0.log:44](../stage2/mesh/logs/checkMesh_wf_U23.0_a180.0.log#L44) and the other `checkMesh_wf_*` logs |
| First cell | h0 is set for a flat-plate first-cell-centre y+ of 40 (Schlichting cf = 0.0592 Re_x^−0.2 at x = 22.3 mm). It is at least 2 × 1.1 × 400 µm, so that y_P = h0/2 lies above the largest Ks, and at most 1.3 mm. Result: 0.88 mm at 23 and 38 m/s (the 400-µm floor binds), 1.30 mm at 10.2 m/s (the cap binds); y_P = h0/2 | [mesh/make_mesh.py:91-96](../stage2/mesh/make_mesh.py#L91-L96), [:345-352](../stage2/mesh/make_mesh.py#L345-L352); [README.md:69-77](../stage2/README.md?plain=1#L69-L77) |
| Wall spacing | 0.20 mm at the corners to 0.30 mm; 8 cells on each end face | [mesh/make_mesh.py:79](../stage2/mesh/make_mesh.py#L79); [README.md:71-74](../stage2/README.md?plain=1#L71-L74) |
| y+ | `yPlus1` runs with `useWallFunction false`, so this is the wall-shear y+, not the wall function's y*. Blade mean (*measured*): 17.2–19.1 at 10.2 m/s, 22.3–41.5 at 23 m/s, 37.5–48.6 at 38 m/s; end faces 27.8–55.8. At start-up the wall function's own y* was below 11.53 on 34–44 % of the painted faces | `yplus_*` columns of `results/stage2_polars.csv`; [stage2_summary.py:9-14](../stage2/stage2_summary.py#L9-L14); [README.md:79-96](../stage2/README.md?plain=1#L79-L96) |
| Ks validity | Ks/y_P ≤ 0.91 (400 µm at 23 m/s); blade-mean Ks+ up to 37.7 (*measured*, `ksplus_blade_mean`) | `Ks_over_yP`, `ksplus_*` in `results/stage2_polars.csv`; [README.md:114-117](../stage2/README.md?plain=1#L114-L117) |
| Turbulence model | `kOmegaSST` only: `run_case.py` refuses LM on this mesh | [run_case.py:409-410](../stage2/run_case.py#L409-L410) |
| Wall `blade` | U `noSlip`; k `kqRWallFunction`; ω `omegaWallFunction` (v2606 default blending `binomial`, n 2); ν_t `nutkRoughWallFunction` with Ks = `--ks` and Cs = 0.5 | [case_template/0.orig/k:29-34](../stage2/case_template/0.orig/k#L29-L34), [omega:28-40](../stage2/case_template/0.orig/omega#L28-L40), [nut:28-40](../stage2/case_template/0.orig/nut#L28-L40); [README.md:103](../stage2/README.md?plain=1#L103) |
| Wall `bladeEnds` | As `blade`, but Ks = 0: the end faces are taken as unpainted (*inferred* from the slicer project) | [case_template/0.orig/nut:41-48](../stage2/case_template/0.orig/nut#L41-L48); [README.md:104](../stage2/README.md?plain=1#L104) |
| Smooth reference | The same `nutkRoughWallFunction` with Ks 0, not `nutkWallFunction`, which differs below y+ 11.53. The rough condition has no viscous branch there: where its log law turns negative, a limiter (0.5–2 times the previous value) keeps ν_t,w at 0.5 ν or above | [README.md:105-112](../stage2/README.md?plain=1#L105-L112) |
| Schemes, PIMPLE | As (a): `limited corrected 0.5` and no non-orthogonal corrector. `run_case.py` would switch to 0.33 and one corrector for a mesh above 60°; the wf meshes reach 40.4–47.7° | [case_template/system/fvSchemes:54-71](../stage2/case_template/system/fvSchemes#L54-L71), [fvSolution:48-59](../stage2/case_template/system/fvSolution#L48-L59); [run_case.py:91](../stage2/run_case.py#L91), [:197](../stage2/run_case.py#L197), [:218](../stage2/run_case.py#L218) |
| Time step, run length | maxCo 5 (16 runs) or 2.5 (21); 150 c/U, the last 100 averaged | [run_case.py:82-85](../stage2/run_case.py#L82-L85); `results/stage2_polars.csv` |
| Forces | As (a), summed over `blade` and `bladeEnds` | [case_template/system/controlDict:51-82](../stage2/case_template/system/controlDict#L51-L82) |
| Mesh acceptance | "Mesh OK." required (no relaxation for wf). The meshes reach non-orthogonality 40.4° and skewness 2.06 at 23 m/s | [run_case.py:296-305](../stage2/run_case.py#L296-L305), [:345](../stage2/run_case.py#L345) |

## 4. (c) Stage 2: resolved texture (`stage2/`, `--wall tex`)

The 32 runs:
- 23 m/s at α 0 and 180, in two sets:
  - maxCo 5: SST and LM at t 0, 0.05, 0.10 and 0.20 mm;
  - maxCo 2.5: SST at t 0 and 0.20; LM at t 0, 0.10 and 0.20.
- LM at α 180, t 0 and 0.20, at 18.8, 20.9 and 25.2 m/s.

Items not listed below are as (a). Link text in this table is relative to `cfd/stage2/`.

| Item | Setting | Where |
|---|---|---|
| Texture | The painted faces are displaced along the smooth-wall normal by δ(s) = t u(s): u uniform in [−1, 1] at points every 0.2 mm of arc length (0.2001 and 0.2002 mm), linear in between, 0 at the corners, with the amplitude ramped over 0.8 mm from each corner. One seed (1) draws u once, so every t is the same pattern scaled. The end faces are not displaced. Ra = 0.397 t and Rq = 0.471 t (*calculated*) | [mesh/make_mesh.py:16-30](../stage2/mesh/make_mesh.py#L16-L30), [:98-102](../stage2/mesh/make_mesh.py#L98-L102), [:260-262](../stage2/mesh/make_mesh.py#L260-L262); [README.md:136-137](../stage2/README.md?plain=1#L136-L137) |
| Mesh method | Stage 1 ring at h0 4.5 µm. Layers grow by 1.15 to 60 µm, then stay constant to max(0.6 mm, D). The displacement fades through the ring as w = 1 − smoothstep(d/D), D = 2.5 t + 0.1 mm, so the first cells keep h0 and the ring edge, where gmsh starts, is not moved. Outer region as Stage 1 medium | [mesh/make_mesh.py:82-85](../stage2/mesh/make_mesh.py#L82-L85), [:406-422](../stage2/mesh/make_mesh.py#L406-L422); [README.md:138-141](../stage2/README.md?plain=1#L138-L141) |
| Cells | nseg 5 (all 32 runs): 215,550 / 216,603 / 217,025 at α 0 / 90 / 180. nseg 10 (B1 only): 331,114 at α 180. At t 0.20 the ring has 23 layers and is 0.637 mm thick | [mesh/logs/checkMesh_tex0.200_s1_n5_a180.0.log:44](../stage2/mesh/logs/checkMesh_tex0.200_s1_n5_a180.0.log#L44), [checkMesh_tex0.200_s1_n10_a180.0.log:44](../stage2/mesh/logs/checkMesh_tex0.200_s1_n10_a180.0.log#L44); [mesh/logs/mesh_info_tex0.200_s1_n5_a180.0.json](../stage2/mesh/logs/mesh_info_tex0.200_s1_n5_a180.0.json) |
| Wall spacing | 0.2 mm / nseg: 40 µm (nseg 5) or 20 µm (nseg 10) on the painted faces | [mesh/make_mesh.py:99-100](../stage2/mesh/make_mesh.py#L99-L100); [run_case.py:88](../stage2/run_case.py#L88) |
| y+ | Blade mean 0.047–0.182; window mean of the blade maximum 0.33–1.17 (*measured*) | `yplus_blade_*` in `results/stage2_polars.csv` |
| Wall | Low-Re as (a), on `blade` and `bladeEnds`: k = 0, ν_t `nutLowReWallFunction`, ω `omegaWallFunction`. For every texture case `run_case.py` overwrites the case's `0/k` and `0/nut` (copied from `0.orig/`) with the `0.lowRe/` versions | [case_template/0.lowRe/k:29-38](../stage2/case_template/0.lowRe/k#L29-L38), [0.lowRe/nut:28-37](../stage2/case_template/0.lowRe/nut#L28-L37); [run_case.py:381-383](../stage2/run_case.py#L381-L383) |
| Schemes, PIMPLE | Laplacian and snGrad `limited corrected 0.33` and one non-orthogonal corrector, for every texture case (t 0 included, so each t and its reference share the numerics). With Stage 1's 0.5 and no corrector, the t 0.20 case diverged after 40 steps | [run_case.py:197](../stage2/run_case.py#L197), [:218](../stage2/run_case.py#L218); [case_template/system/fvSchemes:54-71](../stage2/case_template/system/fvSchemes#L54-L71), [fvSolution:56](../stage2/case_template/system/fvSolution#L56); [README.md:163-170](../stage2/README.md?plain=1#L163-L170) |
| Time step, run length | maxCo 5 set: 80 c/U, the last 50 averaged. maxCo 2.5 set: 150 c/U, the last 100 averaged | `results/stage2_polars.csv` (`t_end_conv`, `avg_from_conv`) |
| Mesh acceptance (relaxed) | A texture mesh passes if skewness is its only failed check, with maximum skewness ≤ 8 and maximum non-orthogonality ≤ 85°. The result is recorded in `case.json` and in the CSV column `mesh_check`. t 0.20, nseg 5: skewness 4.48 (20 faces above 4) and 63.2°, accepted under this rule (11 runs). t 0.20, nseg 10: 4.47 (12 faces) and 63.3°. t 0 passes outright (38.6° with nseg 5, 52.9° with nseg 10). t ≥ 0.40 mm cannot be meshed | [run_case.py:89-90](../stage2/run_case.py#L89-L90), [:296-315](../stage2/run_case.py#L296-L315); [mesh/logs/checkMesh_tex0.200_s1_n5_a180.0.log:96-103](../stage2/mesh/logs/checkMesh_tex0.200_s1_n5_a180.0.log#L96-L103), [checkMesh_tex0.200_s1_n10_a180.0.log:96-103](../stage2/mesh/logs/checkMesh_tex0.200_s1_n10_a180.0.log#L96-L103); [README.md:146-153](../stage2/README.md?plain=1#L146-L153) |

## 5. (d) Rotor (`rotor2d/`)

The 69 runs:
- 53 rotating:
  - hypothesis A at 10.2, 23 and 38 m/s;
  - hypothesis B at 23 m/s;
  - λ 0.05–0.30, both rotation senses.
- 16 static: A and B, θ 0–105°.

All B1 runs use A, curled tip leading (`sense=CCW`), 23 m/s and λ 0.10. Link text in this table is
relative to `cfd/rotor2d/`.

| Item | Setting | Where |
|---|---|---|
| Geometry | The true v1 section. Three blades with the chord at 84° to the radius, R = 101.6 mm to the face the arm touches. The assembly is inferred from the CAD, not measured: hypothesis A, arm on the concave face, cups open toward the shaft, r 84.5–106.4 mm | [README.md:37-41](../rotor2d/README.md?plain=1#L37-L41), [:67-95](../rotor2d/README.md?plain=1#L67-L95) |
| Domain | Box: x from −2.5 to 6.25 m, y ±3.75 m (10, 25 and 15 D_ref, D_ref = 0.25 m); no tunnel walls. Rotating disk r < r_max + 22 mm (128.4 mm for A). Slab dz = 0.01 m | [mesh/make_mesh.py:61](../rotor2d/mesh/make_mesh.py#L61), [:81-83](../rotor2d/mesh/make_mesh.py#L81-L83), [:256](../rotor2d/mesh/make_mesh.py#L256), [:279](../rotor2d/mesh/make_mesh.py#L279); [README.md:113-117](../rotor2d/README.md?plain=1#L113-L117) |
| Mesh method | The section2d ring scheme, re-implemented for three blades, plus a gmsh fill. Rotor (cellZone `rotor`, patches `blade1..3`, `AMI1`) and stator (`AMI2`, `inlet`, `outlet`, `sides`) are joined only through cyclicAMI, so checkMesh reports 2 regions, as expected | [mesh/make_mesh.py:1-23](../rotor2d/mesh/make_mesh.py#L1-L23); [README.md:99-111](../rotor2d/README.md?plain=1#L99-L111) |
| Cells (A, CCW, 23 m/s) | coarse 32,815, medium 61,910, fine 118,634; rotor zone 9,986 / 18,015 / 35,105 | [mesh/logs/mesh_info_A_medium_wf_U23.0_th000.0_senseCCW.json](../rotor2d/mesh/logs/mesh_info_A_medium_wf_U23.0_th000.0_senseCCW.json) and the coarse and fine files |
| First cell, ring | h0 = 2 y+ ν / u_τ, with a flat-plate u_τ at x = c_tip/2 and y+ 40. That gives 0.870 mm at 23 m/s on every level (0.55 mm at 38 m/s; capped at 1.5 mm at 10.2 m/s). Ring 3 / 4 / 4 layers, growth 1.20 / 1.15 / 1.12, at most 5 mm thick | [mesh/make_mesh.py:67-80](../rotor2d/mesh/make_mesh.py#L67-L80), [:87-95](../rotor2d/mesh/make_mesh.py#L87-L95), [:264-271](../rotor2d/mesh/make_mesh.py#L264-L271); [README.md:119-126](../rotor2d/README.md?plain=1#L119-L126) |
| Wall spacing, max / corner | 1.0 / 0.30, 0.70 / 0.20, 0.50 / 0.14 mm; 157 / 224 / 312 faces per blade | [mesh/make_mesh.py:68-76](../rotor2d/mesh/make_mesh.py#L68-L76); mesh_info `patch_faces` |
| y+ (the ν_t condition's own definition) | Rotating runs: blade mean 20.4–36.3, largest sample 68.1–137.8. Static runs: 19.7–29.7 and 76.5–101.2 (*measured*). Spalding gives u_τ y/ν and nutkRough the k-based y*, so smooth and rough values are not like for like | `yplus_*` in `results/rotor_cp.csv`, `rotor_static.csv`; [README.md:356-360](../rotor2d/README.md?plain=1#L356-L360) |
| Boundary conditions | `inlet`: U, k, ω `fixedValue`; p `zeroGradient`. `outlet`: U `inletOutlet` (0 on inflow), p `fixedValue` 0, k, ω `inletOutlet`. `sides`: U `freestreamVelocity`, p `freestreamPressure`, k, ω `inletOutlet`. ν_t `calculated` on all three. `AMI1`/`AMI2`: `cyclicAMI`. Blades: U `movingWallVelocity`, p `zeroGradient` | [run_case.py:334-351](../rotor2d/run_case.py#L334-L351), [:366-368](../rotor2d/run_case.py#L366-L368) |
| Free-stream turbulence | As (a): Tu 1 %, ℓ = 1 mm, decay control. The inlet is 2.37 m upstream of the AMI circle for A. Upstream probe at −2 D: Tu 1.0000–1.0002 % in all 69 runs (*measured*) | [run_case.py:104](../rotor2d/run_case.py#L104), [:192-211](../rotor2d/run_case.py#L192-L211); [case_template/constant/turbulenceProperties:27-37](../rotor2d/case_template/constant/turbulenceProperties#L27-L37); [README.md:180-204](../rotor2d/README.md?plain=1#L180-L204) |
| Turbulence model | `kOmegaSST`. LM is allowed only on the `lowRe` mesh, which no queue uses | [run_case.py:88](../rotor2d/run_case.py#L88), [:517-518](../rotor2d/run_case.py#L517-L518) |
| Wall functions | k `kqRWallFunction`, ω `omegaWallFunction`. Smooth blades: ν_t `nutUSpaldingWallFunction`. Rough blades: `nutkRoughWallFunction` with Ks and Cs 0.5; the rough runs' reference is the same function at Ks 0 (`ks=0 nutwf=kRough`, suffix `_Ks0`), not Spalding. At 400 µm, Ks/y_P = 0.92 | [run_case.py:353-368](../rotor2d/run_case.py#L353-L368); [README.md:319-343](../rotor2d/README.md?plain=1#L319-L343) |
| Motion | `dynamicMotionSolverFvMesh`: solidBody `rotatingMotion` of cellZone `rotor` about +z at Ω = s λ U / R. `correctPhi yes`, `moveMeshOuterCorrectors no`, `checkMeshCourantNo no`. Wall distance recomputed every step | [case_template/constant/dynamicMeshDict.rotating:17-26](../rotor2d/case_template/constant/dynamicMeshDict.rotating#L17-L26); [system/fvSolution:60-63](../rotor2d/case_template/system/fvSolution#L60-L63); [system/fvSchemes:55-62](../rotor2d/case_template/system/fvSchemes#L55-L62); [run_case.py:110-112](../rotor2d/run_case.py#L110-L112) |
| AMI | `faceAreaWeightAMI`, `matchTolerance 0.0001`, `transform noOrdering`; 272 / 368 / 512 faces per side (coarse, medium, fine). Sum of weights 1.0000000–1.0000300 over the 53 rotating runs (*measured*) | [mesh/make_mesh.py:489-493](../rotor2d/mesh/make_mesh.py#L489-L493); `ami_weight_*` in `results/rotor_cp.csv` |
| Schemes | ddt `backward`; U `linearUpwind` (cell-limited gradient); k, ω `upwind`; Laplacian and snGrad `limited corrected 0.5` | [system/fvSchemes:16-53](../rotor2d/case_template/system/fvSchemes#L16-L53) |
| PIMPLE, solvers | As (a), plus `pcorr` GAMG (GaussSeidel) to 1e-3; no `residualControl` | [system/fvSolution:16-64](../rotor2d/case_template/system/fvSolution#L16-L64) |
| Time step | maxCo 4 by default (2 in two λ-0.15 checks). `maxDeltaT` T/720, i.e. 0.5° of rotation, does not bind: at λ 0.10 T/720 = 385 µs against a mean dt of 14.9–38.0 µs (*calculated*; `dt_mean_s`), and the time-mean maximum Co is 0.9995–1.0003 × maxCo in all 69 runs (*measured*, `Co_max_mean`). First step min(1e-6 s, T/1e5) | [run_case.py:110-111](../rotor2d/run_case.py#L110-L111), [:265-268](../rotor2d/run_case.py#L265-L268); [system/controlDict:23-26](../rotor2d/case_template/system/controlDict#L23-L26) |
| Run length, averaging | Rotating: 8 revolutions with the last 3 averaged by default. The production queues used 4–8 (λ 0.05: 4 with the last 2; λ 0.10: 6 with the last 3), the rough-blade set 50 with the last 45, and one 38 m/s, λ-0.30 run 16 with the last 8. Static: 40 D/U with the last 25 averaged, D = 2 r_max. Loads every T/720, AMI weights every T/72, y+ every T/8, fields every T/2 | [run_case.py:110-111](../rotor2d/run_case.py#L110-L111), [:261-274](../rotor2d/run_case.py#L261-L274); queue files in `queues/` |
| Forces, coefficients | `forces` (not `forceCoeffs`) on all blades and on each blade, CofR = shaft axis. Q' = s M_z / dz; C_Q = Q' / (½ρU² · 2R · R); C_P = λ C_Q; C_x = (F_x/dz) / (½ρU² · 2R). R = 101.6 mm, dz = 0.01 m. Single-blade C_Q against azimuth: three blades phase-averaged in 5° bins (`phase_CQ.csv`) | [system/functions:9-35](../rotor2d/case_template/system/functions#L9-L35); [run_case.py:259-260](../rotor2d/run_case.py#L259-L260); [`../post/rotor_summary.py:6-11`](../post/rotor_summary.py#L6-L11); [README.md:56-65](../rotor2d/README.md?plain=1#L56-L65) |
| Mesh acceptance | "Mesh OK." required. A, CCW, 23 m/s: maximum non-orthogonality 51.5 / 57.1 / 57.1°, skewness 1.83 / 2.05 / 2.17 | [run_case.py:453-465](../rotor2d/run_case.py#L453-L465); [mesh/logs/checkMesh_A_medium_wf_U23.0_th000.0_senseCCW.log:106-112](../rotor2d/mesh/logs/checkMesh_A_medium_wf_U23.0_th000.0_senseCCW.log#L106-L112) |

## 6. Known issues

In this table `UPDATE.md` is [`analysis/2026-10-15/UPDATE.md`](../analysis/2026-10-15/UPDATE.md).

| # | Issue | Evidence | Source | Tested in B1 by |
|---|---|---|---|---|
| 1 | The texture mesh's smooth Cd(180) is 39 % below the medium mesh's | SST, α 180, 23 m/s, maxCo 2.5: 0.903 (texture mesh, t 0) against 1.479 (medium). The two runs' mean dt differ: 0.64 µs against 2.18 µs. At a matched mean dt the gap is −9.2 % (*calculated*): texture mesh at maxCo 5 (1.51 µs, Cd 1.108, window 30–80 c/U) against medium at maxCo 1.25 (1.52 µs, Cd 1.220, window 50–150 c/U), so the windows differ. At α 0 the two meshes agree within 0.5 % | [`analysis/2026-10-15/UPDATE.md:229-231`](../analysis/2026-10-15/UPDATE.md?plain=1#L229-L231); rows in `stage2/results/stage2_polars.csv` and `section2d/results/section_polars.csv`; [`section2d/queues/priority7_verify.txt:8-10`](../section2d/queues/priority7_verify.txt#L8-L10) | S1, T1, T2a |
| 2 | α 0 has two flow states | SST, medium, 23 m/s. maxCo 5: Cd 3.19, Cl −0.69 (high drag). maxCo 2.5: Cd 1.75, Cl 0.04 (low drag). maxCo 1.25: shedding at Cd 2.77–3.20 until about 100 c/U, then decay to 1.822 over the last 10 c/U, still falling. In two 60-c/U restarts at the other maxCo each state kept its drag (the low-drag restart's lift oscillation grew 11-fold). A Unity repeat of the Mac run gave Cd 3.1894 against 3.1905, which excludes the machine | [`UPDATE.md:120-140`](../analysis/2026-10-15/UPDATE.md?plain=1#L120-L140); `section2d/results/section_polars.csv` | S2 and the two restarts |
| 3 | The α-180 drag is not converged at maxCo 2.5; the 2.5 grid study is not monotonic | maxCo 2.5 to 1.25: Cd −17.5 % (SST, 1.4793 to 1.2204) and −14.8 % (LM); the shedding decays. Grid at maxCo 2.5: at α 0 and 180 the three meshes zig-zag (spread 9.0 % and 11.5 %); at α 90 Cd converges (GCI 7.6 %) while Cl diverges. At fixed maxCo the step shrinks with the mesh, so mesh and time step are mixed | [`UPDATE.md:89-93`](../analysis/2026-10-15/UPDATE.md?plain=1#L89-L93); [`analysis/2026-10-13/out/section_grid.csv`](../analysis/2026-10-13/out/section_grid.csv); [`section2d/queues/priority7_verify.txt:4-8`](../section2d/queues/priority7_verify.txt#L4-L8) | S1, E90 |
| 4 | LM effects are not converged in the time step | LM texture effect at α 180: +15.3 % (t 0.10) and +8.6 % (t 0.20) at maxCo 2.5, against −1.3 % and +0.4 % at maxCo 5. Most of the change is in the smooth reference (−13.8 %). The LM low-drag α-0 Cd falls 13.6 % from maxCo 5 to 1.25 | [`UPDATE.md:131-133`](../analysis/2026-10-15/UPDATE.md?plain=1#L131-L133), [`:217-220`](../analysis/2026-10-15/UPDATE.md?plain=1#L217-L220) | Not tested: the LM lines (T3) are commented out ([`stage2/queues/S2f_verify.txt:36-39`](../stage2/queues/S2f_verify.txt#L36-L39)) |
| 5 | The texture is a synthetic stand-in | One seed. Nominal amplitude: Ra 20 / 40 / 80 µm for t 0.05 / 0.10 / 0.20 mm (*calculated*), against a measured Ra of 8–13 µm, 2–8 times smaller. In 2D the texture becomes spanwise-uniform ridges, which trip a laminar layer at lower Re_k than 3D roughness (meeting notes), so the texture runs overstate tripping. t ≥ 0.40 mm cannot be meshed | [`stage2/README.md:185-195`](../stage2/README.md?plain=1#L185-L195), [`:172-177`](../stage2/README.md?plain=1#L172-L177); [`docs/ROUGHNESS_KS.md:25-31`](ROUGHNESS_KS.md?plain=1#L25-L31), [`:61`](ROUGHNESS_KS.md?plain=1#L61) | Wall spacing only (T2a) |
| 6 | Rotor: the mesh differences exceed the roughness effect at λ 0.10 | C_Q 0.0138 / 0.0160 / 0.0254 (coarse, medium, fine; maxCo 4; 6 revolutions, last 3 averaged). Fine − coarse = 0.0116 (2u 0.011), against a Ks-400 effect of +0.0051 ± 0.0028 (medium only, last 45 of 50 revolutions). The mean dt also differs (38.0 / 23.7 / 14.9 µs), so mesh and step are mixed. The time step was checked only at λ 0.15 | [`analysis/2026-10-15/out/rotor_grid.csv`](../analysis/2026-10-15/out/rotor_grid.csv); [`UPDATE.md:256-259`](../analysis/2026-10-15/UPDATE.md?plain=1#L256-L259), [`:313-318`](../analysis/2026-10-15/UPDATE.md?plain=1#L313-L318); [`rotor2d/queues/priorityF_verify.txt:4-8`](../rotor2d/queues/priorityF_verify.txt#L4-L8) | R1 (all 6 jobs) |
| 7 | Pressure is not converged within the step in some section runs | The "residual signature": in over half the window's steps, the first pressure solve starts with an initial residual above 0.05. It appears in 15 of the 74 runs added after 13 Oct, all at 10.2–23 m/s and Tu ≤ 1 %, with median first residuals of 0.058–0.418 (0.00015–0.014 in runs without it). Force jumps appear in 35 of the 102 healthy runs. 23 medium-mesh maxCo-5 runs were flagged as corrupted (for example, negative mean drag); each of the 23 configurations now has a healthy maxCo-2.5 run. All 3 fine-mesh maxCo-5 runs diverged | [`UPDATE.md:17-19`](../analysis/2026-10-15/UPDATE.md?plain=1#L17-L19), [`:60-67`](../analysis/2026-10-15/UPDATE.md?plain=1#L60-L67), [`:74-76`](../analysis/2026-10-15/UPDATE.md?plain=1#L74-L76); [`analysis/2026-10-13/RESULTS.md:197-211`](../analysis/2026-10-13/RESULTS.md?plain=1#L197-L211) | Smaller maxCo only; no PIMPLE change |
| 8 | The wall functions are marginal | The first-cell centre sits at about 40 % of the flat-plate δ (1.03 mm at 23 m/s). At start-up the wall function's y* was below 11.53 on 34–44 % of the painted faces, where `nutkRoughWallFunction` has no viscous branch. Ks/y_P reaches 0.91 (section) and 0.92 (rotor). Spalding against kRough at Ks 0 shifts torque between the rotor's edge-on sectors by about 0.007 (net change not resolved) | [`stage2/README.md:89-96`](../stage2/README.md?plain=1#L89-L96), [`:319-324`](../stage2/README.md?plain=1#L319-L324); [`UPDATE.md:265-266`](../analysis/2026-10-15/UPDATE.md?plain=1#L265-L266) | Rotor only; family (b) has no B1 run |
| 9 | Records only, not the solver | The surface tables and plots of the Stage 2 records cover 896 of 3,425 texture blade faces and 121 of 459 wf faces. `rotor_summary.py` drops the last revolution from `CQ_per_rev` in 6 cases. The analysis scripts read the raw fields and histories instead | [`analysis/2026-10-15/README.md:187-194`](../analysis/2026-10-15/README.md?plain=1#L187-L194) | – |

## 7. B1 verification runs (submitted 15 Nov; no results yet)

25 jobs: 23 queue lines and two restarts. Case names below were generated with each stage's
own queue parser (`name_of`).

### 7.1 Smooth section: [`section2d/queues/priority7_verify.txt`](../section2d/queues/priority7_verify.txt)

| Group | Cases | Purpose (header, [lines 12-21](../section2d/queues/priority7_verify.txt#L12-L21)) |
|---|---|---|
| S1 | `a180.0_U23.0_SST_medium_Tu1.0_Co0.625n2`; `a180.0_U23.0_SST_{coarse,fine}_Tu1.0_Co1.25n2` | α 180: "maxCo 0.625 on medium (does Cd keep falling?), and coarse and fine at 1.25 (a grid study at one smaller step)" |
| E90 | `a090.0_U23.0_SST_{coarse,medium,fine}_Tu1.0_Co1.25n2` | α 90: "its step was never tested; Cl diverges" |
| S2 | `a000.0_U23.0_SST_medium_Tu1.0_Co0.625n2_N300A100`; `a000.0_U23.0_SST_{coarse,fine}_Tu1.0_Co1.25n2_N300A100` | α 0, the two flow states: 300 c/U, the last 100 averaged |
| Restart | `section2d/runs/_cont_Co1p25to1p25_a000` | The medium maxCo-1.25 α-0 case continued from 150 to 300 c/U at maxCo 1.25: the medium partner of S2 |
| Restart | `section2d/runs/_hyst_Co5to1p25_a000` | The maxCo-5 high-drag case continued from 150 to 300 c/U at maxCo 1.25: "does that state decay?" |

Both restarts were made with [`hpc/hysteresis_restart.py`](../hpc/hysteresis_restart.py#L1-L58).
Their mean fields average the restart only (`restartOnRestart true`), they write no
`results.json`, and they are analysed from the force histories.

**Acceptance.** The header states no numeric acceptance rule (question 11).

### 7.2 Resolved texture: [`stage2/queues/S2f_verify.txt`](../stage2/queues/S2f_verify.txt)

| Group | Cases | Purpose (header, [lines 11-14](../stage2/queues/S2f_verify.txt#L11-L14)) |
|---|---|---|
| T1 | `a180.0_U23.0_SST_tex{0.000,0.200}_s1_Tu1.0_Co1.25n2` | Time step: maxCo 1.25, compared with the maxCo-2.5 pair |
| T2a | `a180.0_U23.0_SST_tex{0.000,0.200}_s1_n10_Tu1.0_Co2.5n2` | Wall spacing 20 µm (nseg 10), about 1.5 times the cells |
| E90 | `a090.0_U23.0_SST_tex{0.000,0.200}_s1_Tu1.0_Co2.5n2`, and the same with `_Co1.25n2` | α 90 was never run with texture: the effect at maxCo 2.5 and its time step |

All 8 run 150 c/U with the last 100 averaged (SST, 23 m/s, seed 1). Optional T3 (LM, α 180,
maxCo 1.25) is commented out, so it was not submitted.

**Acceptance** ([lines 16-19](../stage2/queues/S2f_verify.txt#L16-L19)), quoted:

> Acceptance (judged with R. Cassin before Stage 2 production): keep nseg 5 / maxCo 2.5 if the
> smooth Cd(180) moves <= 5 % and the t 0.20 effect stays within +-5 points of +13.6 % with the
> same sign of the lift change and the same dominant shedding pattern; otherwise adopt the finer
> setting (texture cost x 1.4-3.1).

### 7.3 Rotor: [`rotor2d/queues/priorityF_verify.txt`](../rotor2d/queues/priorityF_verify.txt)

| Group | Cases | Window |
|---|---|---|
| Fine | `A_rot_U23.0_lam0.100_SST_fine_{Ks0,Ks400}_senseCCW_rev60a55` | 60 revolutions, the last 55 averaged; also evaluated over revolutions 5–50 |
| Medium, maxCo 2 | `A_rot_U23.0_lam0.100_SST_medium_{Ks0,Ks400}_senseCCW_Co2n2_rev50a45` | 50, last 45 |
| Coarse | `A_rot_U23.0_lam0.100_SST_coarse_{Ks0,Ks400}_senseCCW_rev50a45` | 50, last 45 |

All six compare against the existing medium maxCo-4 pair `A_rot_U23.0_lam0.100_SST_medium_{Ks0,Ks400}_senseCCW_rev50a45`
(C_Q 0.0186 and 0.0237). The optional λ-0.12 fine pair is commented out, so it was not submitted.

**Acceptance** ([lines 19-21](../rotor2d/queues/priorityF_verify.txt#L19-L21)), quoted:

> Acceptance: the effect is robust if Ks 400 - Ks 0 is resolved (> 2u) on the fine mesh and at
> maxCo 2 and lies within +-0.004 of +0.0051; otherwise the rotor gain is reported as
> mesh-dependent and no further rotor roughness runs are made.

### 7.4 Not covered by B1

- The wall-function section family (b): no B1 queue file contains a `wf` line. All its runs use one
  mesh level per speed, and no run varies its mesh or its first-cell height (0.88 mm at 23 m/s).
- LM, in any family.
- The texture at α 270.

## 8. Questions for R. Cassin

1. **Boundary conditions and free-stream decay.**
   - All runs fix the far-field k and ω from Tu 1 % and ℓ = 1 mm, both assumed. Decay control,
     with kInf and ωInf equal to those values, keeps the turbulence from decaying on the way to the
     body (sections 2 and 5).
   - Is that acceptable for a separating bluff section? Or would you let the free stream decay, use
     another ℓ, or test Tu and ℓ for SST as well as for LM?
   - Are the circular far field (27 c; `freestreamVelocity`, `freestreamPressure`, `inletOutlet`)
     and the rotor's open box (fixed inlet, p = 0 outlet, free-stream sides, no tunnel walls)
     adequate?
2. **Schemes.**
   - U uses `linearUpwind` with a cell-limited gradient. k and ω use first-order `upwind`: with
     `limitedLinear 1`, ω went negative in 217 of 224 steps
     ([`section2d/README.md:288`](../section2d/README.md?plain=1#L288)).
   - Is first-order k–ω convection acceptable in the separated shear layers? Would you change
     `limited corrected 0.5` (0.33 on the texture) or `backward`?
3. **PIMPLE without residual control.**
   - Each step runs exactly 2 outer × 2 pressure correctors. Turbulence is solved on the final outer
     iteration only, and nothing is under-relaxed.
   - Given the residual signature (issue 7), would you add outer-loop residual control, add outer
     correctors, or rely on a smaller maxCo? What per-step evidence would you accept?
4. **Wall treatment and y+.**
   - (a) and (c): low-Re wall at h0 = 4.5 µm.
   - (b) and (d): wall functions at a first cell of 0.87–0.88 mm (issue 8).
   - Are the wall-function meshes defensible on a 48 mm blade whose turbulent layer is about 1 mm
     thick?
   - Is the rough wall function at Ks 0 the right smooth reference?
   - Should the low-Re corner peaks (y+ samples up to 8.5) be refined?
5. **Relaxed checkMesh.**
   - Texture meshes pass with skewness ≤ 8 and non-orthogonality ≤ 85° (actual: 4.48 on 20 faces,
     63.2°). Every texture run uses `limited corrected 0.33` and one non-orthogonal corrector
     (section 4).
   - Would you tighten the limits, or change the corrector count or the limiter?
6. **AMI weights.**
   - The set-up: `faceAreaWeightAMI`, `matchTolerance 0.0001`, `correctPhi yes`, wall distance
     every step. Weight sums are 1.0000000–1.0000300 (section 5).
   - Is that adequate? What else would you check at the interface?
7. **Averaging windows.**
   - Section: the last 100 of 150 c/U (α-0 B1: the last 100 of 300). Texture maxCo-5 set: the last
     50 of 80. Rotor: the last 45 of 50 revolutions (fine B1: the last 55 of 60). Drift is the mean
     of the window's second half minus that of its first.
   - Is the 50-c/U start-up discard long enough, given that α-0 runs still drift at 150 c/U?
8. **2D URANS.** Is 2D URANS adequate for this separated, shedding flow? Its shedding is
   spanwise-coherent, so we read differences between runs rather than levels
   ([`section2d/README.md:393-396`](../section2d/README.md?plain=1#L393-L396)). What would make a
   difference between two 2D runs credible to you?
9. **LM.** Is `kOmegaSSTLM` meaningful here?
   - Separation is fixed at square edges, and the model is calibrated for attached layers.
   - It transitioned 84 mm early in our T3A check
     ([`validation/T3A/result.md:3`](../validation/T3A/result.md?plain=1#L3)).
   - It responds to the assumed Tu.
   - Should the SST–LM pair still bound the effect of tripping, or should LM be dropped?
10. **Roughness.**
    - We use (b) a rough wall function, with Ks as a sensitivity parameter (0–400 µm, Cs 0.5), and
      (c) the nominal texture meshed as 2D ridges.
    - OpenFOAM v2606 has no roughness-induced transition model
      ([`stage2/README.md:24`](../stage2/README.md?plain=1#L24)). The measured surfaces map to Ks of
      about 25–420 µm depending on the rule ([`docs/ROUGHNESS_KS.md:64-68`](ROUGHNESS_KS.md?plain=1#L64-L68)).
    - How would you represent the printed fuzzy skin?
11. **Acceptance for the smooth-section B1 runs.** The texture and rotor headers set numeric rules;
    the smooth-section header does not (section 7.1). What rule would you apply to S1, E90 and S2?
12. **Family (b) has no mesh check.** Is one needed before more wall-function runs are used to map
    Ks to the printed blades?

## 9. How to get a case folder

The run folders (`cfd/*/runs/`) are git-ignored ([`.gitignore:5`](../.gitignore#L5)). GitHub
holds the templates, scripts, queue files, checkMesh logs (`*/mesh/logs/`) and result tables, but
not the cases. The finished cases are on S. Eacuello's Mac, downloaded from Unity with
`hpc/pull_results.py`.

One representative case per family. Cases (a), (c) and (d) are the existing runs that B1 lines are
compared with; family (b) has no B1 run. Sizes are from `du -sh` on 15 Nov (MiB, GiB):

| Family | Case folder (relative to `cfd/`) | Why this one | Size | of which `log.pimpleFoam` |
|---|---|---|---|---|
| (a) | `section2d/runs/a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2` | maxCo-2.5 reference of S1 | 302 MiB | 246 MiB |
| (b) | `stage2/runs/a090.0_U23.0_SST_wf_Ks400_Tu1.0_Co2.5n2` | α 90, Ks 400 µm: section drag +45 %, the counterpart of the rotor's edge-on gain | 109 MiB | 63 MiB |
| (c) | `stage2/runs/a180.0_U23.0_SST_tex0.200_s1_Tu1.0_Co2.5n2` | t 0.20 run of the +13.6 % texture effect (T1, T2a) | 977 MiB | 890 MiB |
| (d) | `rotor2d/runs/A_rot_U23.0_lam0.100_SST_medium_Ks400_senseCCW_rev50a45` | medium partner of the B1 rotor pairs | 1.2 GiB | 1.1 GiB |
| | Total | | 2.6 GiB | 2.3 GiB |

Each folder already holds only `0/` and its final time (`0.3130434783` = 150 c/U at 23 m/s for the
sections, `13.87764407` = 50 revolutions for the rotor), and no `processor*/` folders (checked 15 Nov).
The command below lists those items explicitly, so the archive cannot pick up anything else. It has
not been run; run it from the repository root:

```zsh
cd cfd
tar -czf ~/cfd_setup_review_2026-11.tar.gz --exclude='processor*' \
  section2d/runs/a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2/{0,0.3130434783,constant,system,postProcessing,case.json,case.foam,mesh_info.json,results.json,timing.json,log.checkMesh,log.pimpleFoam} \
  stage2/runs/a090.0_U23.0_SST_wf_Ks400_Tu1.0_Co2.5n2/{0,0.3130434783,constant,system,postProcessing,case.json,case.foam,mesh_info.json,results.json,timing.json,log.checkMesh,log.pimpleFoam} \
  stage2/runs/a180.0_U23.0_SST_tex0.200_s1_Tu1.0_Co2.5n2/{0,0.3130434783,constant,system,postProcessing,case.json,case.foam,mesh_info.json,results.json,timing.json,log.checkMesh,log.pimpleFoam} \
  rotor2d/runs/A_rot_U23.0_lam0.100_SST_medium_Ks400_senseCCW_rev50a45/{0,13.87764407,constant,system,postProcessing,case.json,case.foam,mesh_info.json,results.json,timing.json,phase_CQ.csv,log.checkMesh,log.pimpleFoam}
```

**Expected archive size** (*estimated*): about 0.5 GB with the solver logs, and about 0.19 GB
without them. To leave the logs out, delete `,log.pimpleFoam` from the four brace lists. The logs
carry the residuals and Courant numbers that questions 3 and 7 need. The estimate comes from
streaming each folder, without its log, through gzip, and from 64-MB samples of three logs, which
compress 7.3–7.9 times; no archive was written.

**What to open first:**
- `system/caseParameters`: every number of the case;
- `system/` and `constant/`: the dictionaries;
- `0/`: the fields as set up;
- the final time folder: the fields and boundary values as the solver wrote them, with `UMean`,
  `pMean` and `wallShearStressMean` in the section cases;
- `constant/polyMesh` and `log.checkMesh`: the mesh;
- `postProcessing/`: forces, y+ and probes;
- `log.pimpleFoam`: the solver output.

**Without the bundle.** `--setup-only` rebuilds the same set-up from the repository. It needs
gmsh in `cfd/.venv` and an OpenFOAM v2606 launcher `openfoam2606` (or the container,
[`hpc/README.md:13`](../hpc/README.md?plain=1#L13)). It writes into `runs/`, and for a mesh that
is not yet cached it also copies the checkMesh log into `mesh/logs/`. These commands give the
four folders above:

```zsh
python3 cfd/section2d/run_case.py --alpha 180 --U 23 --model SST --level medium --maxco 2.5 --setup-only
python3 cfd/stage2/run_case.py --alpha 90 --U 23 --wall wf --ks 400 --maxco 2.5 --setup-only
python3 cfd/stage2/run_case.py --alpha 180 --U 23 --wall tex --tex 0.2 --maxco 2.5 --setup-only
python3 cfd/rotor2d/run_case.py --hyp A --U 23 --lam 0.10 --level medium --sense CCW --nrev 50 --navg 45 --ks 400 --setup-only
```
