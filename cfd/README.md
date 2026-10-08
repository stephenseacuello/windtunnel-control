# cfd/: OpenFOAM model of the blade section and rotor

Plan and stage definitions: [PLAN.md](PLAN.md). Status on 7 Oct 2026: Stage 0 done; Stage 1 set up and smoke-tested, production queue not started.

## Environment

| Item | Value |
|---|---|
| OpenFOAM | v2606 (ESI), native macOS arm64 app `/Applications/OpenFOAM-v2606.app`; it mounts `/Volumes/OpenFOAM-v2606` on first use. `$FOAM_TUTORIALS` = `/Volumes/OpenFOAM-v2606/tutorials`. Build: darwin64ClangDPInt32Opt. |
| MPI | Open MPI 5.0.11, inside the app |
| Machine | Apple M2, 4 performance + 4 efficiency cores, 24 GB. Use at most 4 MPI ranks. |
| Python | System `python3` (3.14) with numpy 2.5.3, scipy 1.17.0, matplotlib, trimesh 4.11.5. The Stage 1 mesher needs gmsh, which is in the venv `cfd/.venv` (Python 3.14.8, gmsh 4.15.2, numpy, scipy, matplotlib); never install into the system python. |
| gnuplot | Not installed, so tutorial plot scripts that call it fail. Plotting is done in Python. |

Keep every path free of spaces; OpenFOAM breaks on them.

## Invoking OpenFOAM

From zsh, through the launcher only (do not source `etc/bashrc` from zsh):

```zsh
openfoam2606 blockMesh -case cfd/runs/mycase
openfoam2606 -c "cd $PWD/cfd/runs/mycase && . \$WM_PROJECT_DIR/bin/tools/RunFunctions && runApplication simpleFoam"
caffeinate -i openfoam2606 -c "cd <case> && decomposePar && mpirun -np 4 pimpleFoam -parallel > log.pimpleFoam 2>&1"
```

`-c` runs bash with the OpenFOAM environment loaded. Inside double quotes, escape `\$` for
variables that bash, not zsh, must expand. Prefix anything longer than a few minutes with
`caffeinate -i`. Parallel cases need `system/decomposeParDict` (scotch, 4 subdomains); see
`validation/T3A/run_checks.sh`.

## Layout

| Path | Contents |
|---|---|
| `PLAN.md` | Stages, risks, missing inputs |
| `geometry/` | `make_section.py` and its outputs: the blade v1 section (`section_v1.json`, `.csv`, `.png`) |
| `templates/` | Shared include files: `transportProperties` (nu), `flowConstants` (rho, nu, Stage 1 speeds) |
| `validation/T3A/` | Stage 0 toolchain check: the T3A tutorial, `run.sh`, `compare.py`, `result.md`, `result.png` |
| `section2d/` | Stage 1: mesh generator, case template, `run_case.py`, `queue.py`, queues, results ([section2d/README.md](section2d/README.md)) |
| `post/` | Shared post-processing; `foamio.py` reads OpenFOAM `.xy`, `.dat` and patch fields |
| `runs/` | Generated working cases; git ignores it |
| `MEASUREMENTS_NEEDED.md`, `measurements/` | Guide to measuring the missing inputs (a separate task) |

Git ignores `runs/`, `processor*/`, time directories, `postProcessing/` and `constant/polyMesh/`
inside the tracked cases, `log.*`, `*.foam` and `.venv/` (see `.gitignore`). Small results
(`result.md`, `result.png`, `metrics.json`, CSVs, `timing.txt`) are tracked.

## Stage 0 (done 7 Oct)

### Blade section: `geometry/make_section.py`

```zsh
python3 cfd/geometry/make_section.py                 # about 35 s
python3 cfd/geometry/make_section.py --tol 5e-6      # finer CSV outline
```

It slices `blades/v1.stl` at mid-span, fits the outer (convex) surface with a cubic B-spline
to the STL vertices, takes the inner (concave) surface as a constant-thickness offset, and
cross-checks against the SolidWorks STEP master (`~/Downloads/turbine.STEP`, outside the repo;
skipped if missing). The STL is the authority. All values below are calculated from the STL
unless marked.

- **Not a circular arc.** The outer surface is a spline whose radius of curvature runs from
  11.6 mm (tight curl) to 77 mm (long, flatter leg); the STEP defines it as a cubic B-spline
  with 8 control points (radius 11.9–75.9 mm). The best single circular-arc model (concentric,
  constant wall) misses the STL by up to 6.6 mm (RMS 1.33 mm), so `rotor_geometry.json`'s
  "circular-arc section ... close to a semicircular cup" does not describe this blade.
- **Wall 1.854 mm** (0.0730 in), constant to within 1.8526–1.8554 mm along the section;
  the STEP's two surfaces are 1.8542 mm apart (0.07300 in). `rotor_geometry.json` states
  1.79 mm. That value is 2V/A over the whole mesh (1.786 mm here), which counts the two end
  caps and the two end faces as wall area; without them, 2V/A gives 1.848 mm.
- **End faces:** flat, 1.854 mm long, square to the surfaces to within 0.1 deg.
- **Chord.** Outer tip to outer tip: 46.16 mm. `rotor_geometry.json` states 48.0 mm, which
  equals the bounding-box y-extent in the CAD frame (48.02 mm), not a tip-to-tip distance.
  Other definitions: end-face midpoints 44.61 mm, inner tips 43.09 mm, extent along the
  outer-tip chord 48.78 mm. The outer-tip chord lies at 85.24 deg to the CAD x-axis.
- **Depth** from the outer-tip chord: 20.94 mm. The stated 24.46 mm equals the bounding-box
  x-extent (24.46 mm).
- **Turning** of the surface tangent from tip to tip: 190.4 deg (stated 183 deg).
- **Bolt holes:** two, diameter 5.080 mm (0.200 in), axis along CAD x at y = 29.20 mm,
  z = 125.22 and 135.13 mm. They are not in the 2D section. The mid-span slice
  (z = 122.555 mm) passes 0.13 mm below the lower hole. That they locate the blade on the hub
  is inferred, not confirmed.
- **Prismatic:** every STL vertex away from the holes lies within 1.7 µm of the 2D model; no twist.

Outputs: `section_v1.json` (spline knots and control points, wall, end faces, dimensions,
single-arc fit, holes, spanwise check, STEP cross-check, comparison with
`rotor_geometry.json`); `section_v1.csv` (closed outline in the CAD frame, metres,
counter-clockwise, first point not repeated, 49 points, maximum chord error 0.048 mm);
`section_v1.png`. `rotor_geometry.json` and the reports are unchanged and still use
48.0 mm and 1.79 mm.

### Toolchain check: T3A transition tutorial

```zsh
cfd/validation/T3A/run.sh          # about 20 s: blockMesh, simpleFoam (1 core), compare.py
cfd/validation/T3A/run_checks.sh   # about 1 min: the same case on 4 ranks, and run to 1000 iterations
```

The case is `$FOAM_TUTORIALS/incompressible/simpleFoam/T3A`, unchanged (kOmegaSSTLM, 26,820
cells). `compare.py` replaces the tutorial's gnuplot script with the same conversions.

- **Result: does not match** the shipped ERCOFTAC T3A data to the criterion set (onset and
  50 % point of the c_f rise within ±50 mm, half the station spacing). Simulated transition is
  upstream by 84 mm at onset (322 mm against 406 mm), 128 mm at the 50 % point and 87 mm at
  the c_f peak. The turbulent c_f (x > 0.9 m) is within 6 % of the data and the free-stream
  Tu decay within 8 %.
- Running all 1000 iterations with residualControl 1e-12, or on 4 MPI ranks, moves c_f by at
  most 0.56 % and the transition positions by at most 0.1 mm, so the offset is not a
  convergence or decomposition artefact. Details: `validation/T3A/result.md`.

**Timing (measured, 7 Oct).** Serial: 15.8 s wall for restore0Dir + blockMesh + simpleFoam;
simpleFoam 14.6 s for 269 iterations, about 2.0 µs per cell per iteration (calculated). On 4
MPI ranks the solver took 4.5 s and 7.2 s in two runs (speed-up 2.0–3.2). Transient PIMPLE
cases with several outer correctors will cost more per step than this steady case.

## Stage 1 (set up 7 Oct; production queue not started)

Details, conventions (with a sketch), smoke test and cost estimates: [section2d/README.md](section2d/README.md).

- Reference chord 48.0 mm (as the reports; the STL tip-to-tip chord is 46.159 mm). α is measured
  from the normal to the outer-tip chord; α = 0 is the concave side facing the wind.
- Meshes: structured near-wall ring plus gmsh quad-dominant outer region, far field at 27 chords,
  first cell 4.5 µm; coarse / medium / fine about 69k / 131k / 255k cells, all "Mesh OK".
- pimpleFoam URANS, kOmegaSST or kOmegaSSTLM, maxCo 5, 150 convective times per case.
- Free stream: kOmegaSST decay control (`decayControl`, kInf, omegaInf) holds the far-field Tu up
  to the body; ℓ = 1 mm gives ν_t/ν 4.5 / 10.2 / 16.8 at 10.2 / 23 / 38 m/s and Tu 1 % (calculated).
  Tested 7 Oct (coarse, 0.5 c/U): upstream probe Tu 1.0015 % and 1.0002 % for a 1 % target.
- Smoke test (measured): medium case 0.17–0.21 s per step on an idle machine, dt 2.1 µs at
  1.1 c/U; estimated 4.9–8.6 h per medium SST case. maxCo 10 diverged.
- Launch: `cd cfd/section2d && python3 queue.py --detach queues/priority1.txt queues/priority2.txt queues/priority3.txt`
  (on AC power; see the README for status, pause and resume).

## Provenance of inputs

| Input | Value | Source |
|---|---|---|
| Kinematic viscosity | 1.516e-5 m²/s | `reports/roughness_2026-09/src/data.py` `NU_STD` (air, 20 °C) |
| Density | 1.204 kg/m³ | same file, `RHO_STD` |
| Blade geometry | `blades/v1.stl`, sha256 `f51518aa…cabcae6` | One blade in metres, converted from `~/Downloads/turbine_meters.stl`, exported from `~/Downloads/turbine.STEP` (`blades/v1.json`) |
| STEP master (cross-check only) | `~/Downloads/turbine.STEP`, sha256 `470bb6a8…f076526b` | SolidWorks 2024, AP214, inches, 1 Jul 2026; not in the repo |
| Stated section dimensions | chord 48.0 mm, depth 24.46 mm, wall 1.79 mm, arc 183 deg | `reports/roughness_2026-09/inputs/rotor_geometry.json` (read only) |
| Stage 1 speeds | 10, 23, 38 m/s | `PLAN.md` |
| T3A case and data | tutorial and `validation/exptData/T3A.dat` | OpenFOAM v2606 tutorials; ERCOFTAC T3A (Savill 1993, 1996) |
