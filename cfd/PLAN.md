# CFD plan (OpenFOAM): drafted 7 Oct 2026, not started

## Why
Prof. Jahangiri (meeting of 7 Oct) asked for three things:
- lift and drag of the blade section, measured and from theory;
- an OpenFOAM model;
- a test of the hypothesis that fuzzy-skin roughness raises power by tripping the boundary layer
  (see `reports/roughness_2026-09/MEETING_2026-10-07_Jahangiri.md`).

## Environment (checked 7 Oct)

**Software**
- OpenFOAM v2606 (ESI, openfoam.com) as the native macOS arm64 app (`/Applications/OpenFOAM-v2606.app`).
- Invoke from zsh with `openfoam2606 <app> -case <dir>` or `openfoam2606 -c '<commands>'`. Do not
  source `etc/bashrc` from zsh.
- ParaView 6.2 is installed.

**Machine**
- Apple M2: 8 cores (4 performance, 4 efficiency) and 24 GB of RAM.
- Use `mpirun -np 4`, and prefix long runs with `caffeinate -i`.

**Available**
- Solvers: pimpleFoam, simpleFoam, overPimpleDyMFoam.
- Meshing: blockMesh, snappyHexMesh, extrudeMesh.
- Function objects: forceCoeffs, forces, yPlus, wallShearStress.
- Mesh motion: cyclicAMI and solidBody rotation.

**Transition and roughness models**
- Transition: kOmegaSSTLM (γ–Reθ) and kkLOmega.
- Rough walls: nutkRoughWallFunction and nutURoughWallFunction.
- Missing: a roughness-induced transition model.

**Paths:** keep every path free of spaces. OpenFOAM breaks on them.

## Stages
| Stage | Goal | Method | Effort |
|---|---|---|---|
| 0 | Toolchain check and repo layout | Run the T3A transition tutorial against its validation data. Generate the section from the analytic geometry, checked against a slice of `blades/v1.stl`. Benchmark the run time. | 0.5–1 day |
| 1 | 2D smooth section ("airfoil slice"): Cd, Cl, Cm, Strouhal number and separation angle against α from 0 to 180° at 10, 23 and 38 m/s | blockMesh O-grid with y+ < 1, unsteady pimpleFoam, kOmegaSST (tripped) and kOmegaSSTLM (free transition, Tu bracketed at 0.5, 1 and 3%) | 3–4 days setup; 3–5 h per run |
| 2 | Roughness bounds | Free against forced transition. Fully turbulent rough wall with nutkRoughWallFunction, ks = 0–400 µm. Optionally, the texture resolved in 2D. | about 1 week |
| 3a | 2D static rotor: torque against azimuth | snappyHexMesh or merged O-grids | 2–4 days plus compute |
| 3b | 2D rotating rotor: C_P against λ, smooth and rough | pimpleFoam with AMI, prescribed Ω; compare shapes and ratios with the rig's C_P,el against λ | about 1 week plus 4–12 h per point |
| 4 | Blockage and 3D checks | Tunnel walls in 2D; a spanwise-periodic 3D slice with DDES | 1–2 weeks; a full 3D rotor needs HPC |

## Validation without a load cell
- **Published drag of semicircular shells:** about 2.3 with the concave side to the wind and about
  1.2 with the convex side. These are not measurements of this blade.
- **Shedding frequency:** a Nano 33 BLE Sense accelerometer on a cantilevered printed section. The
  expected frequency is 30–160 Hz, so the IMU must sample at 400 Hz or faster.
- **Pressure taps** on a printed section, read by cheap differential sensors. Pressure drag
  dominates on this shape, so the taps give nearly all of Cd.
- **Rig data:** λ at peak power, the zero-torque λ, and the Plain-to-FS ratios
  (`build/tacho/derived/`).
- **A cheap bar load cell with an HX711 board** (about $10–15) would give direct section forces.

## Missing inputs
1. **Rotor assembly** (blocks stage 3): which point of the section sits at R = 0.1016 m, the blade
   angle to the radius, the rotation sense, the hub and end plates. These are not in the repo or in
   `turbine.STEP`.
2. **Tunnel test-section dimensions** (for blockage and wall modelling) and the freestream
   turbulence intensity (an input to the transition model).
3. **Wall thickness check:** `rotor_geometry.json` says 1.79 mm, but the blade mesh gives about
   1.85 mm (cap area divided by midline length). Resolve this before meshing.

## Risks
- 2D URANS overstates shedding and drag, so compare relative changes, not absolute values.
- kOmegaSSTLM is calibrated for attached boundary layers. This flow separates massively at
  Re 3×10⁴ to 1.2×10⁵, and the tunnel turbulence intensity is unknown.
- Rough-wall functions model a rough turbulent boundary layer, not tripping.
- The square edges fix separation on the concave side, so roughness can act mainly on the convex
  side. A small or null effect is a legitimate result.
