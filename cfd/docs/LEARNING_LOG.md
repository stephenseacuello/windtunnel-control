# Learning log: CFD of the blade section and rotor

A working guide for an engineering graduate student new to CFD, built on this project's own cases.
Every figure except the T3A plot (section 3) is from a case record (`cfd/*/results/records/`, see
[RECORDS.md](RECORDS.md)) or from the analysis of the first 150 finished cases (13 Oct,
[RESULTS.md](../analysis/2026-10-13/RESULTS.md)), so the pictures are of our blade, our meshes and
our mistakes. Some flow figures still come from the **test records of 7 Oct** (folder names
starting with `_`): start-up flow 0.3-1.1 c/U after an impulsive start, made with the free-stream
set-up used before decay control (section 3). They are kept where the point is the start-up or a
failure (sections 5, 6 and 7), and in section 3, whose production record ran on Unity: the
repository holds the summaries of the Unity records, while their images stay on the Mac. Sections
marked **[pending]** wait for evidence the 13 Oct analysis did not produce: it read the result
tables, not the field images.

Provenance labels, as in the project reports: *literature-established*, *measured* (read from a run
or a log), *calculated* (derived from measured values or geometry), *computed* (from the result
tables by the 13 Oct analysis scripts, `cfd/analysis/2026-10-13/src/`), *assumed* (an input chosen
without data), *inferred*, *uncertain*. Numbers without a label are definitions.

Background on the cases: `cfd/PLAN.md` (stages), `cfd/section2d/README.md` (section model),
`cfd/rotor2d/rotor_geometry.py` (rotor assembly hypotheses A and B).

Contents
1. [What a mesh is, and why y+ matters](#1-what-a-mesh-is-and-why-y-matters)
2. [RANS, URANS and LES](#2-rans-urans-and-les)
3. [k-omega SST and the gamma-ReTheta transition model](#3-k-omega-sst-and-the-gamma-retheta-transition-model)
4. [Boundary conditions for external flow](#4-boundary-conditions-for-external-flow)
5. [Courant number and time step](#5-courant-number-and-time-step)
6. [Convergence and averaging windows](#6-convergence-and-averaging-windows)
7. [Forces, coefficients and the Strouhal number](#7-forces-coefficients-and-the-strouhal-number)
8. [Mesh independence and the GCI](#8-mesh-independence-and-the-gci)
9. [Roughness: sand-grain ks against Ra](#9-roughness-sand-grain-ks-against-ra)
10. [Rotating meshes with AMI](#10-rotating-meshes-with-ami)
11. [Validating without a load cell](#11-validating-without-a-load-cell)
12. [Running on a cluster (Unity)](#12-running-on-a-cluster-unity)
13. [References](#13-references)

---

## 1. What a mesh is, and why y+ matters

**The finite-volume idea.** OpenFOAM splits the fluid into cells and stores one value of each
unknown (velocity U, pressure p, turbulence k and omega) per cell. It balances fluxes of mass and
momentum through the cell faces, so every equation becomes "what flows in minus what flows out
equals the change inside". Accuracy depends on how well the cells resolve the gradients: fine
where the flow changes quickly (walls, shear layers, the wake), coarse where it does not.

**Our 2D section mesh.** The case is one cell thick in z, with `empty` front and back faces, so
OpenFOAM solves a 2D problem. Around the blade sits a structured ring of thin cells that follow the
wall (27 layers on the medium mesh, first cell h0 = 4.5 um, growth 1.15 per layer, total 1.28 mm;
calculated by the generator, `mesh_info.json`). Outside the ring, gmsh fills the domain with
quad-dominant cells, refined along the wake, out to a circular far field 27 chords away.

![medium mesh near the blade](../section2d/results/records/_mesh/medium_a000.0/mesh_near.png)

The blade has square end faces 1.85 mm long. The ring wraps them with a fan of cells at each
corner, so the first-cell height holds even there:

| 6 mm view of tip A | 0.8 mm: the layers at the outer corner | 0.1 mm: the first cells |
|---|---|---|
| ![](../section2d/results/records/_mesh/medium_a000.0/mesh_cornerA_6mm.png) | ![](../section2d/results/records/_mesh/medium_a000.0/mesh_cornerA_0p8mm.png) | ![](../section2d/results/records/_mesh/medium_a000.0/mesh_cornerA_0p1mm.png) |

**y+.** Near a wall the velocity rises from zero through a thin viscous sublayer into the
logarithmic layer. The natural length unit there is nu/u_tau, where u_tau = sqrt(tau_w/rho) is the
friction velocity. The height of the first cell centre in those units is

    y+ = u_tau y / nu.

- *Literature-established:* the viscous sublayer reaches to about y+ = 5 and the log layer starts
  at about y+ = 30.
- A *low-Reynolds-number* treatment resolves the sublayer and needs y+ of about 1 or less at the
  first cell. The transition model (section 3) needs it too, because it must see the laminar
  boundary layer.
- *Wall functions* skip the sublayer: they put the first cell in the log layer (y+ about 30-300)
  and impose the log law there. They are cheaper, but cannot represent laminar flow or transition.

The section uses the low-Re treatment. The rotor's production mesh uses wall functions
(h0 = 0.87 mm, y+ target 40, `rotor2d/.../_mesh/A_medium_wf_U23.0_th000.0/mesh_info.json`), because
a 3-blade rotor resolved to y+ = 1 would cost too much on this laptop; its transition runs need the
`lowRe` mesh variant (h0 = 12.1 um, *calculated* by the generator). The same blade tip on both rotor
meshes, 6 mm and 0.8 mm views:

| Wall-function mesh (h0 0.87 mm), 6 mm | Low-Re mesh (h0 12.1 um), 6 mm | Low-Re mesh, 0.8 mm |
|---|---|---|
| ![](../rotor2d/results/records/_mesh/A_medium_wf_U23.0_th000.0/mesh_cornerA_6mm.png) | ![](../rotor2d/results/records/_mesh/A_medium_lowRe_U23.0_th000.0/mesh_cornerA_6mm.png) | ![](../rotor2d/results/records/_mesh/A_medium_lowRe_U23.0_th000.0/mesh_cornerA_0p8mm.png) |

**Our y+** (*measured*, first production case `a000.0_U23.0_SST_medium_Tu1.0`: alpha 0, 23 m/s,
maxCo 5; time mean over 50-150 c/U):

![wall distributions](../section2d/results/records/a000.0_U23.0_SST_medium_Tu1.0/fields/surface_mean.png)

- The bottom panel is y+ along the wall, computed in ParaView from the time-mean wall shear stress:
  mean 0.12, maximum 1.16 on a corner face of tip A, at most 0.30 more than 0.05 c from the end
  faces (`fields/surface_mean.csv`). OpenFOAM's yPlus function object, which uses the instantaneous
  shear, gives over the same window a blade mean of 0.16 and a maximum of 1.12 on average, 1.23 at
  its largest (`results.json`). The ParaView calculation was checked against the function object
  on the 7 Oct pipeline test: same minimum, mean within 0.5 %, maximum within 6.5 % (RECORDS.md,
  Limits).
- The peaks sit on the end faces and corners (grey bands), where the flow turns 90 degrees around
  a sharp edge and accelerates.
- *Computed* over the 28 healthy Stage 1 runs (section 5): the time-mean maximum y+ is 0.56-1.68,
  highest at 38 m/s (1.67-1.68); the blade mean is 0.073-0.24; single samples (one per c/U) reach
  6.45. The 7 Oct estimate for 38 m/s, about 2.3 on the corner faces (*calculated* from start-up
  flow with u_tau proportional to U^0.9, `section2d/README.md` section 2), was conservative for the
  time mean. A sharp edge always produces this peak; refining h0 further would cost time steps
  (section 5) for four cells.

**What to check in every record:** `yplus.png` (max and mean against time), and the y+ panel of
`fields/surface_mean.png` (where on the wall the maximum sits).

## 2. RANS, URANS and LES

Turbulent flow has eddies from the blade size (centimetres) down to fractions of a millimetre.
Three ways to deal with them:

| Approach | What is solved | What is modelled | Cost here |
|---|---|---|---|
| RANS (steady) | the time-mean flow | all turbulence, through an eddy viscosity nu_t | minutes; but a bluff body's wake is not steady, so it often does not converge |
| URANS (unsteady RANS) | the mean flow plus slow, large-scale unsteadiness (vortex shedding) | the small-scale turbulence, through nu_t | hours per case in 2D (section 5) |
| LES / DDES | the large eddies themselves, in 3D | only the small eddies | needs 3D and weeks on this laptop (HPC, Stage 4) |

We run **2D URANS** (`pimpleFoam`). It captures the von Karman vortex street behind the blade,
which drives the oscillating lift and drag.

**The limitation to keep in mind** (*literature-established*): a 2D simulation forces every vortex
to be perfectly coherent along the span. Real shedding loses coherence over a few diameters, so 2D
URANS tends to overstate the shedding strength and the drag of bluff bodies. Use it for relative
changes (angle against angle, smooth against tripped, rotor A against rotor B), and treat absolute
Cd as an upper-leaning estimate until checked (section 11).

The eddy viscosity shows where the model is adding mixing. In the production cases the free stream
carries nu_t/nu = 10.2 at 23 m/s (Tu 1 %, length scale 1 mm), the same at the far field and at the
blade, because decay control holds it there (*calculated*, `case.json`; section 3). The image is the
first production case at its last step (SST, alpha 0, 23 m/s, 150 c/U, instantaneous):

![nu_t/nu](../section2d/results/records/a000.0_U23.0_SST_medium_Tu1.0/fields/nut_ratio_near.png)

- The free stream is purple, nu_t/nu about 10, as set.
- The shear layers separating from both tips, and the wake, are orange to yellow, a few hundred
  to at least 1000, the top of the colour bar (read from it): this is where the model mixes.
- The dark lobes just outside both tips, where the flow accelerates round the corners, are
  *inferred* to be the SST stress limiter (nu_t = a1 k / max(a1 omega, S F2)), which lowers nu_t
  where the strain rate S is high.
- SST makes the boundary layer turbulent from the leading edge. In a transition (LM) run the
  attached boundary layer should stay close to laminar (dark) until it transitions (section 3).

The 7 Oct test records predate decay control: their free stream carried nu_t/nu of about 38 at the
far field and 35 at the blade (*calculated*, their `case.json`), so their backgrounds are redder.

### Two flow states with the cup into the wind

*Computed* (RESULTS.md section 2.3): the 12 healthy alpha-0 runs of Stage 1 fall into two separate
clusters, which differ by a factor of 1.76-1.82 in Cd on matched pairs.

| | High-drag state (7 runs) | Low-drag state (5 runs) |
|---|---|---|
| Cd | 2.97-3.22 | 1.75-2.01 |
| Mean Cl | -0.70 to -0.27 | +0.02 to +0.18 |
| Cl_std | 0.81-1.49 | 0.003-0.45 (3 runs at 0.13 or less) |
| St | 0.118-0.144 | 0.124-0.157 |

The roughness runs land in the same two clusters (RESULTS.md section 3.7). The figure shows every
alpha-0 case at 23 m/s: the 8 wall-function runs (squares) are high-drag, as are the other 9 at
10.2 and 38 m/s (not plotted); the 8 texture runs (circles) are low-drag; the Stage 1 runs
(triangles) fall in either:

![alpha-0 states](../analysis/2026-10-13/fig/roughness_alpha0_states.png)

**What selects the state** (*computed*): no single setting. SST at 23 m/s is high-drag at maxCo 5
and low-drag at maxCo 2.5 on both meshes tested (Cd 3.17 to 1.80 coarse, 3.19 to 1.75 medium), but
the maxCo-5 runs ran on the Mac and the maxCo-2.5 runs on Unity. The SST maxCo-5 runs on Unity at
10.2 and 38 m/s are high-drag too, which points to the time step, not the machine (*inferred*). LM
at maxCo 5 is low-drag at Tu 1 % (10.2 and 23 m/s) and high-drag at Tu 0.5 and 3 % and at 38 m/s.
The mesh matters as well: at maxCo 5, smooth SST is low-drag on the texture mesh (Cd 1.84) and
high-drag on the Stage 1 medium mesh (3.19); those two runs also differ in machine and run length.

**Why 2D URANS can do this** (*inferred*; the fields were not examined):
- URANS solves deterministic equations for the averaged flow, and the shedding it resolves is a
  self-sustained oscillation. A nonlinear system can have more than one stable state for the same
  inputs; which one a run reaches depends on how it gets there. Each run starts impulsively, and
  the time step, mesh and Tu shape that start-up, like a ball settling into one of two valleys.
- The forces suggest two wake patterns: an asymmetric shedding wake with a large mean lift and a
  strong lift oscillation (high drag), and a nearly symmetric wake with almost no mean lift and, in
  3 of its 5 runs, a weak or no lift oscillation (low drag).
- 2D makes each pattern harder to leave: every vortex is coherent along the span (above), so the
  flow cannot drift between patterns through spanwise variation. A real 3D wake loses that
  coherence and may switch, or sit between the two.

**What it means:**
- Compare runs only within one state. Across states, a parameter "effect" can be a state switch:
  LM Cd 3.14, 1.96 and 3.22 at Tu 0.5, 1 and 3 % is the state switching, not a smooth Tu trend
  (*inferred*).
- A run that switches during its window mixes both states; the two noisiest low-drag runs (Cd_std
  1.02 and 1.05) may do so.
- Which state, if either, the real blade is in is unresolved. The shell value 2.3 (*literature*, not
  this blade) lies between them. The high-drag state overpredicts it by 27-38 % on the frontal
  width, in the direction 2D URANS usually errs (above); the low-drag state underpredicts it by
  14-25 %. A tunnel measurement of the section's alpha-0 drag would settle it. In the CFD, a restart
  of one state from the other state's field tests for hysteresis, and the Mac's maxCo-5 case
  repeated on Unity (submitted 13 Oct) separates time step from machine.

## 3. k-omega SST and the gamma-ReTheta transition model

**k-omega SST** (Menter 1994) solves two transport equations, for the turbulent kinetic energy k
and the specific dissipation rate omega, and sets nu_t from them. It blends a k-omega form near
walls (good in adverse pressure gradients) with a k-epsilon form away from them (insensitive to
the free-stream omega), and limits the shear stress so that separation is not delayed too much.
The coefficients it uses are printed at the top of every solver log (`log_excerpt.txt`, solver
header: alphaK1 0.85, beta1 0.075, a1 0.31, and so on).

SST alone treats the boundary layer as **turbulent from the leading edge** ("fully turbulent").
At our chord Reynolds numbers, Re_c = U c/nu = 3.2e4 (10.2 m/s), 7.3e4 (23 m/s) and 1.2e5 (38 m/s)
(*calculated*, c = 48 mm), the real boundary layer starts laminar and may separate or transition
partway along the blade. That is why the meeting of 7 Oct asked for a transition-capable model.

**gamma-ReTheta (`kOmegaSSTLM`)** (Langtry and Menter 2009) adds two equations:
- *intermittency* gamma (`gammaInt`): near 0 where the boundary layer is laminar (about 0.02,
  where the model's relaminarisation term holds it; *measured* minimum 0.020 in a coarse LM check,
  `section2d/README.md` section 5), 1 where it is turbulent; its effective value scales the
  production of k, so a laminar layer produces almost no turbulence;
- *transition-onset momentum-thickness Reynolds number* ReTheta_t: carries the free-stream
  turbulence level into the boundary layer, through empirical correlations.

Transition starts where the local boundary-layer Reynolds number exceeds a critical value set by
ReTheta_t, which falls as the free-stream turbulence intensity Tu rises. **Tu is therefore an
input**, and the tunnel's Tu is not measured (`cfd/MEASUREMENTS_NEEDED.md`). The section runs
assume Tu = 1 % at the blade and bracket 0.5 and 3 % (queue priority 4).

The intermittency next to the wall at 0.3 c/U (coarse LM test of 7 Oct; view height 5 mm, centred
on the convex wall a quarter of the way round from tip A, so the concave side is left of the grey
wall and the convex side right). The free stream is 1 by its boundary condition; the dark layer
next to the wall is laminar:

![gammaInt at the wall](../section2d/results/records/_test_pipeline_coarse_LM_N0.3/fields/gammaInt_wall.png)

**[pending]** The developed transition pattern: `fields/gammaInt_near.png` and
`fields/surface_mean.png` (Cf sign changes = separation and reattachment) of a healthy LM production
case, for example `section2d/results/records/a000.0_U23.0_LM_medium_Tu1.0/` (low-drag state;
section 2). That record ran on Unity, so its images are on the Mac only; they have not been examined
yet.

**What the LM production runs showed** (*computed*, RESULTS.md sections 2.2 and 2.8). Healthy LM
runs exist at 23 m/s only at alpha 315, 345, 0-60 and 270 degrees, and at alpha 0 for every speed
and Tu; every LM run at alpha 75-255, 285, 300 and 330 degrees was corrupted (section 5). The one
SST/LM pair in the same flow state (alpha 0, 38 m/s, both high-drag) differs by -0.13 % in Cd,
against 2 combined standard errors of about 13 %: no transition-model effect is resolved at
alpha 0, where the flow is *inferred* to separate at the square tips whatever the boundary layer
does. The convex side, where transition should matter, is the open test (section 9).

### Free-stream turbulence and decay control

In the free stream k and omega have no production, only destruction, so the standard SST
equations let the inflow turbulence decay on its way from the far-field boundary (26.5 chords
upstream of the blade) to the blade. With t = distance / U and the far-field constants
beta = 0.0828, beta* = 0.09:

    k = k0 (1 + beta omega0 t)^(-beta*/beta),    omega = omega0 / (1 + beta omega0 t).

**Stage 1 uses decay control** (Spalart and Rumsey 2007; `section2d/README.md` section 3):
`decayControl yes; kInf ...; omegaInf ...;` in `kOmegaSSTCoeffs` (`constant/turbulenceProperties`,
copied into every record's `settings.txt`). The model then adds beta* omegaInf kInf to the k
equation and beta omegaInf^2 to the omega equation. These cancel the destruction exactly when
k = kInf and omega = omegaInf, so the free stream keeps its inflow values, while turbulence that
the body produces (k far above kInf) still decays almost as before. The solver log confirms the
switch in its header, "Employing decay control with kInf ... and omegaInf ..." (`log_excerpt.txt`;
*measured* in `a000.0_U23.0_SST_medium_Tu1.0`: kInf 0.07935 m^2/s^2, omegaInf 514.3 1/s).

`run_case.py` sets the far-field k and omega, and kInf and omegaInf, from the target Tu and a
length scale l = 1 mm (*assumed*; the tunnel's value is unmeasured): k = 1.5 (Tu U)^2,
omega = sqrt(k) / (C_mu^(1/4) l). At 23 m/s and Tu = 1 % that gives nu_t/nu = 10.2 at the far
field and at the blade, and a far-field ReTheta_t of 584 from the Langtry-Menter correlation
(*calculated*, `case.json`). A coarse 0.5 c/U check read Tu = 1.0015 % at the probe 2 chords
upstream (*measured*, `section2d/README.md` section 3). Decay control does not stop the strain
production just ahead of the body: there Tu rose to at most 1.29 % in the same check (*measured*).

**The 7 Oct set-up (no decay control).** The test records used in this log predate decay control.
Their far field started at Tu 1.89 %, raised so that the decay left 1 % at the blade, with
l = 2 mm: nu_t/nu 38 at the far field and 35 at the blade, far-field ReTheta_t 274.6
(*calculated*, their `case.json`; each record's key-number table names its set-up). It was replaced
because the blade saw the undecayed, higher Tu until the free stream had travelled the 26 chords
(26 c/U), because nu_t/nu at the blade was about 3.4 times the decay-control value, and because the
far-field ReTheta_t followed the far-field Tu instead of the target. The rotor cases
(`rotor2d/run_case.py`) still pre-compensate in this way.

### Why the T3A check came out early

Before trusting the transition model on the blade, Stage 0 ran OpenFOAM's T3A flat-plate tutorial
against the ERCOFTAC measurements (`cfd/validation/T3A/result.md`).

![T3A](../validation/T3A/result.png)

*Measured* (simulation against experiment):
- transition onset (c_f minimum) at x = 322 mm against 406 mm: 84 mm early;
- the 50 % point of the c_f rise at 538 mm against 666 mm: 128 mm early;
- onset Re_x 1.16e5 against 1.45e5, a factor 0.80 (*calculated*).

*Measured* checks ruled out numerical causes: all 1000 iterations with residualControl 1e-12, or 4
MPI ranks, moved the transition positions by at most 0.1 mm. The free-stream Tu decay matches the
data within 8 % at every station, and the turbulent c_f (x > 0.9 m) within 6 %.

*Uncertain:* why the model transitions early. Open alternatives, none tested:
- the correlations of the v2606 implementation (onset and transition-length functions) differ
  from the calibration that matches T3A;
- the local Tu at the leading edge differs from the station values in a way the 8 % agreement
  hides (the onset correlation is steep at low Tu);
- the length-scale (omega) choice of the tutorial inlet, which sets the decay near the leading edge;
- the experiment's own uncertainty in onset, which the 100 mm station spacing limits to about
  +-50 mm.
The tutorial ships no reference simulation, so whether ESI's own run shows the same offset is not
known.

*Inferred* consequence for this project: LM transition positions may sit upstream of reality by an
amount of order 20 % in Re_x. Use LM against SST as **bounds** (free against forced transition)
and compare changes, not absolute transition points.

## 4. Boundary conditions for external flow

A boundary condition tells the solver the value (Dirichlet) or the gradient (Neumann) of each field
on each boundary patch. Every record lists them in `settings.txt` (the `0/` files). The section:

| Patch | U | p | k, omega, ReTheta_t, gammaInt | nu_t |
|---|---|---|---|---|
| `farfield` (circle, 27 c) | `freestreamVelocity` | `freestreamPressure` | `inletOutlet` | `calculated` |
| `blade` (wall) | `noSlip` | `zeroGradient` | k = 0; omega `omegaWallFunction`; gamma, ReTheta_t `zeroGradient` | `nutLowReWallFunction` |
| `frontAndBack` | `empty` (2D) | `empty` | `empty` | `empty` |

- `freestreamVelocity` blends, face by face, between the fixed free-stream value where the free
  stream points into the domain and zero gradient where it points out. `freestreamPressure` does
  the opposite: zero gradient on inflow faces and the fixed free-stream value on outflow faces, so
  U and p are never both fixed on the same face. Both blend continuously with the angle between
  the free-stream velocity and the face normal, so one circular boundary serves as inlet and outlet
  at any angle of attack (v2606 source, `freestreamVelocityFvPatchVectorField.H`,
  `freestreamPressureFvPatchScalarField.H`). The rotor's fixed inlet velocity and fixed outlet
  pressure follow the same rule.
- `inletOutlet` switches on the sign of the face flux: the fixed inflow value where flow enters,
  zero gradient where it leaves.
- On the wall, k = 0 and omega takes its viscous-sublayer value (the wall function blends to it
  at y+ below 1).

The rotor domain is a rectangle: `inlet` (fixed U), `outlet` (fixed p = 0), `sides` (free stream),
and two `cyclicAMI` patches between the rotating and fixed zones (section 10). The blades use
wall functions (`kqRWallFunction`, `omegaWallFunction`, `nutUSpaldingWallFunction`) on the `wf`
mesh.

**Blockage.** The far field must be far enough not to squeeze the flow. Neither model includes the
tunnel walls yet: the section's far field is 27 chords away, the rotor domain 8.75 m by 7.5 m. The
tunnel test-section size is unmeasured (`MEASUREMENTS_NEEDED.md`), so blockage corrections and a
walled run (`--walls` in `rotor2d/run_case.py`) wait for it.

## 5. Courant number and time step

The Courant number of a cell is

    Co = |U| deltaT / dx,

the number of cells a fluid particle crosses in one time step. OpenFOAM evaluates it per cell as
Co = 0.5 deltaT sum_faces |phi_f| / V (phi_f the volume flux through a face, V the cell volume);
for a quad of length l along a wall and height h, with velocity u along and v across the wall,
that is deltaT (|u|/l + |v|/h). OpenFOAM's `adjustTimeStep` shrinks deltaT so that the largest Co
anywhere stays at or below `maxCo`.

- An *explicit* time scheme for advection is stable only up to Co of about 1.
- `pimpleFoam` integrates *implicitly* in time, which stays stable above Co = 1. With one outer
  corrector it is the PISO algorithm, whose pressure-velocity coupling is accurate only up to Co
  of about 1; the outer correctors (`nOuterCorrectors`, 2 here) repeat the coupling within each
  step, which is what allows larger steps. Accuracy and stability still degrade as Co grows, so
  maxCo is a setting to test, not to push.

**The smallest, fastest cells set the step for the whole mesh.** In our section those are the
thin near-wall cells within 0.2 mm of the corners B-outer and A-inner (h0 = 4.5 um, growing by
1.15 per layer), which the shear layer separating from the square corner crosses at 20-60 m/s,
so the |v|/h term dominates (*inferred* from where the high-Co cells sit; *measured*, smoke test
at 0.59 c/U: 99 of 131,061 cells had Co > 2, `section2d/README.md` section 3). At maxCo 5 that gives deltaT of about 2 us (*measured*: 2.13 us at 1.08 c/U; for orientation,
*calculated*, 5 x 20 um / 40 m/s = 2.5 us). One convective time c/U = 2.09 ms at 23 m/s, so at
2.13 us a c/U takes about 980 steps and 150 c/U about 147,000 steps (*calculated*). The first
production case had reached deltaT = 3.37 us at 4.5 c/U (*measured*, 8 Oct log), about 620 steps
per c/U; it finished with 115,280 steps, 769 per c/U at a mean deltaT of 2.72 us (*measured*, its
record). Over all healthy medium-mesh runs: 624-955 steps per c/U at maxCo 5 and 959-1,208 at
maxCo 2.5 (*measured*; cost in `section2d/README.md` section 6). In the wake, Co stays at or below
0.34 (*measured*): the step there is limited by the corners, not by the physics.

![time step, Courant, cost](../section2d/results/records/_smoke_a000_U23_SST_medium_Co5n2/timestep.png)

Top: deltaT grows as the start-up transient fades. Middle: Co max sits at 5. Bottom: cumulative CPU
time against wall-clock time.

**Pushing maxCo to 10 diverged** (*measured*, record `_smoke_a000_U23_SST_medium_Co10n2`): the
pressure residual rose from 0.012 to about 0.8 in 0.08 c/U, k reached 2e7 m^2/s^2 and deltaT
collapsed. The residual plot shows the warning signs: a rising p residual, then every field
jumping at once.

![Co 10 residuals](../section2d/results/records/_smoke_a000_U23_SST_medium_Co10n2/residuals.png)

**maxCo 5 is not time-step independent either** (*computed*, RESULTS.md section 2.4). Halving it to
2.5 (SST, 23 m/s) switched the alpha-0 flow state (section 2), stopped the alpha-90 shedding (Cl_std
from 0.121 to 1.0e-4 on the coarse mesh, from 0.139 to 2.8e-5 on the medium), and turned the
corrupted medium-mesh alpha-180 run healthy (below). Except in that alpha-180 pair, the maxCo-5 runs
ran wholly or mostly on the Mac and the maxCo-2.5 runs on Unity, so the machine changed too. maxCo
2.5 is the minimum for further low-Re section work; a maxCo-1.25 check was submitted on 13 Oct.

**The 7 Oct sleep stall.** The bottom panel of the time-step figure is the cheapest diagnostic of a
run. A stalled run shows a vertical jump in clock time with flat CPU time. On 7 Oct the medium
case's second session logged ClockTime 8886 s against ExecutionTime 282 s, a ratio of 31
(*measured*, `log_excerpt.txt`; earlier in the same session 8785 s against 186 s). The Mac was
asleep (battery at 1 %, pmset log) and resumed on AC. The record's session table catches this
automatically (`clock/CPU` column); a healthy session runs at 1.0-1.3.

### Silent corruption: the numerical-health flag

maxCo 10 failed loudly, and so did 8 runs at maxCo 5 (RUN_JOURNAL.md, 12 Oct: deltaT fell to
1e-34 s or less, then a floating-point exception). Worse is a run that finishes and writes
plausible-looking numbers. The 13 Oct analysis flags 23 of the 51 Stage 1 runs as corrupted, all on
the medium mesh at maxCo 5 (23 of 39 such runs; 0 of the 12 coarse, fine and maxCo-2.5 runs), among
them every medium-mesh alpha-180 run at maxCo 5 (*computed*, RESULTS.md section 2.2):

![Section run health](../analysis/2026-10-13/fig/section_health.png)

- **The flag** is a time-step proxy, u_Co/U = maxCo dx_corner / (dt_mean U): the speed, in units of
  U, that would set the run's mean time step in a corner-sized cell (dx_corner = 64, 45, 32 um on
  the coarse, medium and fine meshes). It is a proxy, not a measured velocity. Runs above 5 are
  flagged. The 51 runs split into 2.25-4.48 and 6.27-32.3, with nothing between; in units of c/U,
  a flagged run's mean time step is 1.9-9.6 times shorter than the median of the healthy runs on
  the medium mesh at maxCo 5.
- **Why a short time step is a symptom.** adjustTimeStep sets deltaT from the face fluxes alone
  (the Co formula above; checked in the v2606 source, RESULTS.md section 2.2). A step several times
  shorter means that somewhere next to the wall the solution moves several times faster than in any
  healthy run of the same flow. *Inferred* cause: a spurious oscillation near the square corners
  (the fields were not examined).
- **Why negative mean drag proves it.** A fixed body in a steady stream cannot have negative mean
  drag: drag times wind speed is the rate at which the body takes energy from the flow, and the body
  has no energy to give (*literature-established*, momentum and energy balance). 9 flagged runs have
  Cd_mean below 0, down to -1.93.
- **The other symptoms.** Every flagged run has at least one, and no healthy run has any:
  Cd_std > |Cd_mean| (19 runs), |Cl_mean| > 3 (5), a time-mean maximum y+ above 2 (21).
- **A wrong diagnosis it corrected.** On 12 Oct the 12 LM runs stopped by the time limit were
  blamed on the transition model's stiffness. Healthy LM runs step as fast as healthy SST runs on
  the medium mesh at maxCo 5 (median deltaT U/c 1.40e-3 against 1.36e-3), and all 12 slow runs are
  flagged: they were slow because they were corrupted (RUN_JOURNAL.md, 12 Oct, correction). The
  likely fix is a smaller maxCo, not a longer time limit: the medium-mesh alpha-180 SST run is
  corrupted at maxCo 5 and healthy at 2.5, both on Unity. The LM re-runs at maxCo 2.5, submitted
  13 Oct, test it for LM.
- **The cost.** The corrupted runs used 3,750 of the 5,016 core-hours that the solver sessions of
  the 51 finished Stage 1 runs took on Unity (75 %; *calculated* from the session tables in each
  record's `log_excerpt.txt`, clock time times ranks; diverged runs are not included).
- **Check every run:** its mean time step against healthy runs with the same mesh and maxCo, and the
  four symptoms. A run that "finished" is not yet a result.

## 6. Convergence and averaging windows

Three meanings of "converged", which are easy to confuse:

1. **Within a time step.** The linear solvers and PIMPLE outer correctors reduce the equation
   imbalance (the residual) in each step. In a transient run the *initial* residual does not fall
   to machine zero; it settles into a band set by the time step and the unsteadiness.
   `residuals.png` shows that band.
2. **Statistically stationary.** The start-up transient has died away and the shedding repeats
   with steady amplitude. Check the coefficient history: does the mean drift? The record reports
   `Cd_drift` and `Cl_drift`, the mean of the second half of the window minus the first half.
3. **Window long enough.** The mean of an oscillating signal over a finite window has a sampling
   error. It shrinks with the number of shedding cycles in the window (`n_cycles_window` in
   `summary.json`). The spectrum's frequency resolution is 1/T_window, so 10 cycles resolve St to
   about 10 %.

Our runs start impulsively from uniform flow, discard the first 50 c/U and average over the last
100 c/U (defaults in `run_case.py`). At St of about 0.2 (*assumed* for orientation), 100 c/U holds
about 20 cycles.

The pipeline test (0.3 c/U) shows what an unconverged history looks like: the coefficients are
still in the start-up transient, the shaded window is a fraction of one cycle, and no spectrum can
be computed.

![start-up history](../section2d/results/records/_test_pipeline_coarse_N0.3/coefficients.png)

**A developed history** (*measured*, the first production record,
`section2d/results/records/a000.0_U23.0_SST_medium_Tu1.0/`: alpha 0, 23 m/s, maxCo 5, high-drag
state):

![developed history](../section2d/results/records/a000.0_U23.0_SST_medium_Tu1.0/coefficients.png)

![spectrum](../section2d/results/records/a000.0_U23.0_SST_medium_Tu1.0/spectrum.png)

- The lift oscillation grows for about 40 c/U after the start. The first cycles of the window still
  have higher drag peaks, about 3.8-4.0 against about 3.6 later (read from the plot), which the
  drift measures.
- Drift, second half of the window minus the first: Cd -0.107 (3.4 % of the mean), Cl +0.052. The
  sampling error of the mean, taking one independent sample per shedding cycle, is
  Cd_std/sqrt(cycles) = 0.399/sqrt(12.2) = 0.114 (*calculated*): the drift is within it.
- 12.2 shedding cycles in the 100 c/U window; frequency resolution 1/T_window = 0.01 in St.
- The Cl peak is sharp: 94 % of the Cl variance lies within +-15 % of St 0.122 (58.3 Hz,
  `St_peak_frac`). Drag has its largest peak at 2 St and a second one at St (read from the
  spectrum), as expected for an asymmetric section (section 7).
- Healthy is not converged: this run is not time-step independent (at maxCo 2.5 the same case
  settles in the low-drag state, section 2).

Over the 24 healthy unsteady Stage 1 runs (*computed*, RESULTS.md section 5;
`../analysis/2026-10-13/out/section_case_quality.csv`): the windows held 11.8-17.5 shedding cycles
at alpha 0 and the other LM angles except alpha 15, 22.3-23.2 at alpha 180 and 50.0-50.7 at
alpha 90 and 270. 19 runs drift by less than 2 standard errors. Two lessons:
- A near-steady run has a tiny standard error, so even a small drift fails the test. Three of the
  five failures are of this kind: the low-drag SST runs at alpha 0 (maxCo 2.5, coarse and medium;
  Cd_std 0.010 and 0.017) and LM at alpha 345 (Cd_std 0.010) drift by 0.7, 1.3 and 0.8 % of Cd.
  The other two, LM at alpha 0 with Tu 0.5 and 3 % (high-drag state), drift by 11.9 % of Cd,
  which is 1.00 and 1.05 times 2 standard errors.
- Passing the test is not enough when the window holds few cycles: alpha 15 (LM) holds 2.1 cycles
  of a slow oscillation and its Cd drifts by 35 % of the mean, yet stays within 2 standard errors.
  Its mean is not converged.

## 7. Forces, coefficients and the Strouhal number

The `forceCoeffs` function object integrates pressure and viscous stress over the blade and divides
by q A_ref, with q = 0.5 rho U^2 and A_ref = c dz (chord times the 1 mm cell depth). The results
are coefficients **per unit span**:
- Cd along the free stream;
- Cl perpendicular to it, 90 degrees counter-clockwise;
- Cm about the section centroid, counter-clockwise positive (the conventions, and the sign flip
  from OpenFOAM's CmPitch, are in `section2d/README.md` section 1).

**Pressure against viscous drag.** `forces1` splits the force. On this bluff shape pressure drag
dominates (*measured*, Co 5 smoke run after 0.8 c/U: Cd_pressure 2.45 against Cd_viscous -0.015;
`section2d/README.md` section 5). The production runs confirm it: viscous drag is -0.53 to +1.47 %
of Cd in all 28 healthy runs (*computed*, RESULTS.md section 2.8).
Pressure taps on a printed section would therefore capture nearly all of Cd (section 11).

The pressure field behind that number (mean Cp of the LM pipeline test over 0.1-0.3 c/U; red =
stagnation in the cup, blue = suction around the tips):

![mean Cp](../section2d/results/records/_test_pipeline_coarse_LM_N0.3/fields/cp_mean_near.png)

The cup is a uniform dark red because its Cp is above the top of the colour range: about 1.4 on
the concave wall (*measured*, `fields/surface_mean.csv`: 1.39 in this test, 1.41 in the SST
pipeline test; 1.29 instantaneous at 0.59 c/U in the Co 5 smoke run). In a steady incompressible
flow Cp cannot exceed 1, because the total pressure cannot rise above its free-stream value
anywhere. In this start-up flow it can: the unsteady Bernoulli equation
has an extra term, rho dphi/dt, from the vortices growing at the tips (*inferred*).

In the developed production runs the time-mean Cp still peaks slightly above 1 (*measured*,
`fields/surface_mean.csv` of the 28 healthy records, leaving out the end faces and the wall within
0.35 mm of a corner, where the values spike; top panel of the figure in section 1): 1.009-1.014
in the four steady runs (alpha 60, and alpha 90 at maxCo 2.5), 1.005-1.040 in the other runs away
from alpha 0, 1.04-1.05 in the cup in the low-drag state and 1.06-1.09 in the high-drag state.

Most of the excess is the reference (*measured* on 14 Oct: the time-mean p, `pMean`, on the
far-field patch in the final time folder of each of these runs). p_inf = 0 is held only on the far
field's outflow faces; on its inflow faces U is fixed at U_inf and p floats (section 4). On the most
upstream face (most negative flux phi) p sits 0.008-0.011 q above p_inf in the four steady runs,
0.041-0.043 q in the low-drag state and 0.060-0.081 q in the high-drag state, so the oncoming total
pressure exceeds p_inf + q by as much. Referenced to that upstream pressure, the peaks of the steady
and alpha-0 runs lie 0.001-0.006 above 1; this remainder is not explained (*uncertain*).
- The offset grows with the drag: it is 0.018-0.027 times Cd in these runs (*calculated*). The
  reason is *inferred*: 27 chords out, the far field still feels the wake. Whether the offset also
  biases the forces is not checked.
- Before comparing CFD Cp with pressure taps, reference it to the upstream static pressure.
- The turbulence term is not a cause. OpenFOAM's p includes 2k/3, because only the deviatoric part
  of the Reynolds stress enters the momentum equation (v2606 `linearViscousStress.C`), but k = 0 on
  the wall.

**Strouhal number.** Shedding vortices alternately from each tip makes the lift oscillate at the
shedding frequency f. The dimensionless form is

    St = f c / U.

*Literature-established:* St is about 0.2 for a circular cylinder over a wide Re range. Bluff bodies
of other shapes sit in a similar band, which is why St is a robust check. The record finds f as the
largest peak of the Cl spectrum (Hann window, zero padding, parabolic peak fit). On a body symmetric
about the flow direction, drag oscillates at 2f, because each vortex pulls the body back once. This
section is not symmetric (tip B curls), so expect a drag component at f as well. *Calculated* for orientation: St = 0.15-0.2
gives 32-43 Hz at 10.2 m/s, 72-96 Hz at 23 m/s and 119-158 Hz at 38 m/s.

**The rotor's coefficients.** These are per unit span, with swept width 2R:
- C_Q = Q'/(q 2R R), from the moment about the shaft;
- C_P = lambda C_Q, with tip-speed ratio lambda = Omega R/U.
The rig measures electrical C_P,el, which includes generator and bearing losses, so CFD and rig
are compared in shape (lambda at peak, zero-torque lambda), not magnitude
(`cfd/post/plot_rotor_cp.py`).

**St against angle of attack** (*computed*, RESULTS.md section 2.7): healthy medium-mesh runs at
23 m/s and Tu 1 % whose lift spectrum has a peak; labels give f at 23 m/s.

![St against alpha](../analysis/2026-10-13/fig/section_strouhal.png)

| alpha | St = f c/U | St on the frontal width | f at 23 m/s | Caveat |
|---|---|---|---|---|
| 0 | 0.118-0.157 (all speeds, Tu, meshes; 0.122-0.147 at 23 m/s) | 0.12-0.16 | 58-70 Hz | two flow states (section 2) |
| 180 | 0.223-0.232 (SST, maxCo 2.5, three meshes) | 0.227-0.236 | 107-111 Hz | the only value checked against the time step |
| 90, 270 | 0.500-0.507 | 0.227-0.230 | 240-243 Hz | maxCo 5 only: steady at maxCo 2.5 on all three meshes |

The other healthy LM angles give 0.130-0.175 (alpha 30, 45, 315, 345; broadband except at 345);
alpha 15 is not stationary and alpha 60 is steady.

- On the chord, St varies by a factor of 4.3 (0.118 to 0.507). On the frontal width (48.76 mm at
  alpha 0 and 180, 21.77 mm at 90 and 270, *calculated* from the outline), alpha 90, 180 and 270
  collapse to 0.227-0.236. Bluff bodies shed at a similar St when it is based on the width of their
  wake (*literature-established* rule of thumb, applied here as an inference); alpha 0 sheds more
  slowly, which fits the cup turning the flow outward at the tips into a wider wake (*inferred*).
- The orientation range above (St 0.15-0.2) overlaps alpha 0 at its upper end; edge-on, St is 2.5
  times its top.
- For the accelerometer test (section 11): 400 Hz sampling covers alpha 0 and 180 up to 38 m/s (at
  most 184 Hz, *calculated* at constant St). Edge-on shedding, if real, needs at least 490 Hz at
  23 m/s and 810 Hz at 38 m/s (Nyquist).

**[pending]** A rotor `phase_CQ.png` (one blade's torque around a revolution): see section 10.

## 8. Mesh independence and the GCI

A result is useful only if refining the mesh further would not change it much. The standard
procedure (Roache 1994; Celik et al. 2008) needs three systematically refined meshes:

| Level | Cells (alpha 0) | h0 | Wall spacing at corners / max |
|---|---|---|---|
| coarse | 68,500 | 4.5 um | 64 / 210 um |
| medium | 131,061 | 4.5 um | 45 / 150 um |
| fine | 254,015 | 4.5 um | 32 / 105 um |

(*calculated* by the generator, `section2d/README.md`; images in
`section2d/results/records/_mesh/{coarse,medium,fine}_a000.0/`.)

The steps, for a quantity phi (Cd, St, ...) with phi_1 fine, phi_2 medium, phi_3 coarse:
1. Representative cell size h = (A/N)^(1/2) in 2D. Refinement ratios
   r_21 = h_2/h_1 = (N_1/N_2)^(1/2) = 1.392 and r_32 = 1.383 (*calculated*). Celik et al.
   recommend r > 1.3.
2. Apparent order p from the three values: solve
   p = |ln|eps_32/eps_21| + q(p)| / ln r_21, with eps_32 = phi_3 - phi_2, eps_21 = phi_2 - phi_1,
   q(p) = ln((r_21^p - s)/(r_32^p - s)) and s = sign(eps_32/eps_21), by fixed-point iteration.
3. Extrapolated value phi_ext = (r_21^p phi_1 - phi_2)/(r_21^p - 1).
4. Fine-grid convergence index GCI_fine = 1.25 |(phi_1 - phi_2)/phi_1| / (r_21^p - 1). It is an
   uncertainty band on phi_1 (safety factor 1.25 for three grids).

Three cautions for these cases:
- Each phi is a time mean with its own sampling error (section 6). A mesh difference smaller than
  the run-to-run spread is not resolved.
- If eps_32/eps_21 < 0 (oscillatory convergence), p is not meaningful; report the range instead.
- The three levels keep h0 = 4.5 um and change the growth ratio and the wall spacing, so the
  refinement is not geometrically similar next to the wall, which the method assumes. The apparent
  order p may then differ from the formal order of the schemes (2); a p far from 2 is a warning,
  not a result.

**The study** (*computed*, `../analysis/2026-10-13/out/section_grid.csv`; SST, 23 m/s, Tu 1 %,
maxCo 2.5; the three fine runs at maxCo 5 diverged). p, phi_ext and GCI exist only where the three
values converge monotonically:

| Quantity | coarse | medium | fine | Behaviour | p | phi_ext | GCI_fine |
|---|---|---|---|---|---|---|---|
| Cd, alpha 0 | 1.795 | 1.751 | 1.925 | oscillatory; spread 9.0 % of fine | - | - | - |
| St, alpha 0 | 0.124 | 0.131 | 0.143 | not usable: fine-mesh spectrum broadband (peak share 0.25) | - | - | - |
| Cd, alpha 90 | 0.3459 | 0.3748 | 0.3919 | monotonic | 1.64 | 0.416 | 7.6 % |
| Cm, alpha 90 | -0.2754 | -0.2807 | -0.2857 | monotonic | 0.27 | -0.340 | 23.7 % |
| Cl, alpha 90 | 0.999 | 0.933 | 0.804 | diverging: the change grows with refinement | - | - | - |
| Cd, alpha 180 | 1.669 | 1.479 | 1.653 | oscillatory; spread 11.5 % of fine | - | - | - |
| St, alpha 180 | 0.2308 | 0.2232 | 0.2324 | oscillatory; spread 4.0 % of fine | - | - | - |

![grid study](../analysis/2026-10-13/fig/section_grid.png)

What it teaches (*computed*, RESULTS.md section 2.4; the reading is *inferred*):
- Only the steady case converges: alpha 90, which stops shedding at maxCo 2.5. There Cd = 0.392
  +- 7.6 % (GCI_fine, +-0.030) with p = 1.64, against a formal order of 2. Cm converges too, but
  with p = 0.27: by the third caution, a warning, not an order.
- At alpha 0 and 180 the differences change sign, so no order exists; the spread (9.0 % and 11.5 %
  of the fine value) is the honest band. The unsteady runs are where the first caution bites: the
  fine alpha-0 run fluctuates strongly (Cd_std 1.02) and may mix the two flow states (section 2),
  and the medium alpha-180 run is the outlier (St peak share 0.65; instantaneous y+ up to 4.94, the
  largest of any maxCo-2.5 run).
- Cl diverges at alpha 0 (0.021, 0.044, 0.093) and at alpha 90. Cm at alpha 0, and Cl and Cm at
  alpha 180, oscillate (spreads 15.4, 26.3 and 35.2 % of the fine value).
- Consequence: a CFD difference smaller than about 10 % cannot be resolved across meshes. Within
  one mesh, as in every roughness comparison, it holds only if the grid error cancels between the
  two runs, which is untested.

## 9. Roughness: sand-grain ks against Ra

**ks is not a measurement.** CFD rough-wall models use the *equivalent sand-grain roughness* ks:
the grain size of Nikuradse's (1933) closely packed sand that produces the same drag increase in
fully rough flow. It is a hydrodynamic property of a surface, not a geometric one.

**Ra is a geometric measurement.** Ra is the arithmetic mean deviation of the roughness profile;
Pa is the same quantity for the primary profile, before the cut-off filter (lambda_c) separates
roughness from waviness. The project's surfaces (*measured*, roughness report table):

| Rotor | Fuzzy skin (mm) | Pa (um) | Ra (um) | Peak power change vs Plain |
|---|---|---|---|---|
| Plain | none | 19.0 | 12.7 | reference |
| FS 0.05 | 0.050 | 13.9 | 9.4 | +1.8 % [-0.6, +4.2] |
| FS 0.10 | 0.101 | 13.2 | 8.2 | +12.8 % [+10.1, +15.5] |
| FS 0.20 | 0.202 | 28.7 | 10.3 | +16.2 % [+13.5, +19.0] |

Neither Pa nor Ra ranks the rotors by power. There is no universal ks-Ra conversion
(*literature-established*). In the fully rough regime, Flack and Schultz (2010) found that ks
correlates best with the rms height and the skewness of the height distribution (their
correlation is reported as ks = 4.43 k_rms (1 + Sk)^1.37; check the paper before quoting it).
Our textures are not in that regime (below).

**Roughness Reynolds number.** What matters to the flow is the roughness height in wall units,
ks+ = u_tau ks/nu (*literature-established* regimes):
- hydraulically smooth below about 5;
- transitionally rough between about 5 and 70;
- fully rough above about 70.

*Calculated, rough:* the smoke test's y+ (mean 0.2, corner maximum 1.5, first cell centre at
2.25 um, 23 m/s, start-up flow) gives u_tau of about 1.3 m/s on most of the wall and about
10 m/s at the corners. Taking ks equal to the scan height k of the meeting notes (38 um for Plain,
FS 0.05 and FS 0.10; 84-97 um for FS 0.20; an *assumption*, since ks is not k), ks+ is about 3 on
most of the wall and up to 25 at the corners for 38 um, and about 8 to 60 for 90 um. So the
surfaces are *smooth to transitionally rough*, not fully rough. The production wall-function runs
agree (*computed*, RESULTS.md section 3.6): blade-mean Ks+ 2.55-3.55 at Ks 50 um, just above
2.25, below which `nutkRoughWallFunction` switches the roughness off, and up to 37.4 at
100-400 um; local maxima exceed the model's fully rough limit, 90, only in three Ks-400 runs
(106.2 at most; limits from the v2606 source, `nutkRoughWallFunctionFvPatchScalarField.C`).

What this means for the plan (Stage 2):
- `nutkRoughWallFunction` (OpenFOAM's rough wall function, inputs Ks and Cs) shifts the log law.
  It needs a wall-function mesh, with the first cell centre above the roughness, and it does not
  model roughness-induced transition.
- OpenFOAM v2606 has no roughness-induced transition model (`cfd/PLAN.md`).
- The hypothesis from the meeting is that the fuzzy skin trips the boundary layer. The section
  model brackets it with free transition (LM) against forced transition (SST, turbulent from the
  leading edge). Rough-wall SST cases (ks 0-400 um) add the skin-friction penalty on top.
- The roughness Reynolds number based on the boundary-layer velocity at height k (Re_k = u_k k/nu;
  meeting notes of 7 Oct, after Wilcox et al. 2017) is the transition criterion. The ks+ above is
  the drag criterion. Keep the two apart.

### Why the fully turbulent result opposes the tunnel

![Drag difference and measured power](../analysis/2026-10-13/fig/roughness_drag_difference.png)

**What Stage 2 found** (*computed*, RESULTS.md sections 3.2-3.3; SST with rough wall functions,
23 m/s):
- Convex side to the wind (alpha 180): Cd +1.1, +2.4 and +5.8 % at Ks 100, 200 and 400 um, each
  33-153 times its noise; 89 % of the rise is pressure drag.
- Cup to the wind (alpha 0): Cd -6.0 % at Ks 400 um, the only level resolved (all these runs are in
  the high-drag state, section 2).
- Both shrink the drag difference D = Cd(alpha 0) - Cd(alpha 180) that drives a drag rotor: -19.3 %
  at Ks 400 um (panel a). In the two-position model of RESULTS.md, drive
  N = Cd(alpha 0)(1 - lambda)^2 - Cd(alpha 180)(1 + lambda)^2, that is less power at every lambda
  from 0 to 0.25, and the zero-torque lambda falls from 0.158 to 0.129 (*inferred*). The tunnel
  measured +12.8 % (FS 0.10) and +16.2 % (FS 0.20) peak power (geometric mean over 10.2-38 m/s;
  panel c) and a light-load rotor speed 6.6 and 9.1 % higher (geometric mean over 12.4-38 m/s)
  (*measured*, roughness report).

**Why a fully turbulent model gives this sign** (*inferred*):
- SST makes the smooth blade's boundary layer turbulent from the leading edge, so the smooth
  reference is already "tripped" and roughness cannot trip it again. It acts only as a rough
  turbulent wall: less momentum near the wall, earlier separation on the curved convex back, a
  wider wake, more friction (alpha 180). At alpha 0 the flow separates at the square tips whatever
  the wall, so there roughness changes only the wake pressure (RESULTS.md section 3.2).
- Pressure drag is at least 98.5 % of Cd in every healthy smooth run (*computed*), so friction alone
  cannot give 13-16 %; a gain has to come through separation and the wake.
- `nutkRoughWallFunction` has no laminar branch, so it cannot show a benefit of tripping.

**What the tripping hypothesis needs** (*inferred*, from RESULTS.md sections 3.8, 3.9 and 8.4):
- *The mechanism.* On the smooth printed blade the convex-side boundary layer starts laminar and
  may separate early (on a circular cylinder a laminar layer separates near 80 degrees and a
  turbulent one near 120 degrees; *literature*, e.g. Achenbach 1968, not re-checked). Roughness that
  trips the layer before that point would delay separation, narrow the wake, lower Cd(alpha 180) and
  raise D. The sign of a roughness effect therefore depends on the state of the smooth reference,
  which only a transition model can represent.
- *A healthy transitional reference on the convex side.* Stage 1 has no healthy LM run at alpha
  75-255 degrees (section 5). LM and SST at alpha 150-210 degrees and 10.2, 23 and 38 m/s, LM also
  at Tu 0.5 and 3 %, all at maxCo 2.5, were submitted on 13 Oct.
- *Roughness the transition model can feel.* v2606 has no roughness-induced transition, so the
  texture must be meshed into the wall (Stage 2e). Its 2D ridges trip at a lower Re_k than the
  printed 3D texture, and LM is not calibrated for geometric ridges: a positive result would be an
  upper bound.
- *Resolution.* In the two-position model a section change of about 2 % explains the gains: for
  FS 0.10, Cd(alpha 180) -1.85 to -2.04 % or Cd(alpha 0) +1.62 to +1.76 % at lambda 0.125. The LM
  texture runs at 23 m/s changed Cd by -2.8 to +2.6 %, against noise of 4.5-8.4 % of Cd: not
  resolved. Runs of 150 c/U, averaged over the last 100, were submitted on 13 Oct.
- *The speed trend.* The 7 Oct prediction is that the onset of the gain moves to lower wind speed as
  roughness grows. That needs LM texture runs at several speeds (alpha 180 at 18.8, 20.9 and
  25.2 m/s, submitted 13 Oct) and the tunnel's Tu, an input to LM that is not measured.
- *So far.* The only result with the sign tripping needs: on the smooth texture mesh D is 18.6 %
  larger with SST than with LM, within its noise (unresolved).

## 10. Rotating meshes with AMI

A rotor needs part of the mesh to turn. The rotor mesh has two zones:
- a disc `rotor` (cellZone) containing the blades, which turns as a rigid body
  (`dynamicMeshDict`: `solidBody`, `rotatingMotion`, omega = lambda U/R);
- the fixed outer domain.
Their shared circle (r = 128 mm) is split into two patches, `AMI1` and `AMI2`, whose faces do not
match once the disc turns. The *arbitrary mesh interface* (`cyclicAMI`) interpolates fluxes across
them, using the overlap area of each face pair as weights.

![AMI interface](../rotor2d/results/records/_mesh/A_medium_wf_U23.0_th000.0/mesh_ami.png)

![rotor mesh](../rotor2d/results/records/_mesh/A_medium_wf_U23.0_th000.0/mesh_near.png)

Checks:
- **AMI weights.** Each face's weights should sum to 1 (full overlap). The `AMIWeights1` function
  object logs min and max. The coarse smoke run shows 1.00002-1.00003 (*measured*); values far
  from 1 mean a gap or overlap in the interface and lost conservation. The record copies them to
  `summary.json` (`ami_weight_min`, `ami_weight_max`).
- **Time step.** The blades move through the fixed mesh. maxDeltaT is T/720 (0.5 degrees per
  step), and Co still applies.
- **Start-up.** C_Q needs several revolutions to become periodic. The default is 8 revolutions,
  averaging the last 3; `CQ_drift_last_two_rev` in the queue's summary measures the remaining
  drift.

Static rotor cases (stage 3a) freeze the blades at an azimuth theta on the same mesh and give the
static torque against theta. They are cheaper and test the assembly hypotheses A and B before the
rotating runs.

**What the 40 rotating cases showed** (*computed*, RESULTS.md sections 4 and 5;
`../analysis/2026-10-13/out/rotor_numbers.json`):
- AMI weights stayed between 1 and 1.00002 in every case, and omega was bounded in 0 steps.
- The Courant limit (maxCo 4, and 2 in the two repeats) set the step: 0.015-0.094 degrees of
  rotation per step, far below the 0.5-degree cap.
- Runs of 4, 6 or 8 revolutions averaged the last 2 or 3 (fewer at low lambda, where a revolution
  takes longer). The revolution-to-revolution scatter of C_Q, sigma_rev, was 0.0059 for A at
  23 m/s, 0.0092 at 10.2 m/s, 0.0153 at 38 m/s, and 0.0115 for B at 23 m/s. The uncertainty of a
  mean of n revolutions is u = sigma_rev/sqrt(n), so a 3-revolution mean of A at 23 m/s carries
  2u = 0.0068.
- The mean is a small difference of large swings: for A with the curled tip leading at lambda
  0.10, 23 m/s, the instantaneous C_Q runs from -0.449 to +0.370 around a mean of +0.016. The
  viscous part of the mean torque is at most 0.0006 in C_Q for this configuration (RESULTS.md
  section 4.6).
- The largest drift between the last two revolutions, 0.049, is in
  `A_rot_U38.0_lam0.300_SST_medium_senseCCW`; a 16-revolution repeat was submitted on 13 Oct.

The torque against lambda at 23 m/s (bars: 2u; diamonds: the static runs at lambda 0, whose bars
are the half-difference of the two 30-degree subsets):

![C_Q against lambda](../analysis/2026-10-13/fig/rotor_cq_lambda_U23.png)

**[pending]** The per-case `coefficients.png` and `phase_CQ.png` (one blade's torque around a
revolution), for example of `rotor2d/results/records/A_rot_U23.0_lam0.100_SST_medium_senseCCW_rev6/`
(A, curled tip leading, lambda 0.10, 23 m/s). Every rotating case ran on Unity, so these images are
on the Mac only; the 13 Oct analysis did not use them.

## 11. Validating without a load cell

The rig measures electrical power, not blade forces. Options from `cfd/PLAN.md`, with the record
output each one checks:

| Check | Measurement | Record output to compare | Status (13 Oct) |
|---|---|---|---|
| Bluff-body drag | Published drag of semicircular shells: about 2.3 concave side to the wind, 1.2 convex (literature; not this blade) | `Cd_mean` at alpha 0 and 180 | compared (*computed*, on the frontal width): alpha 180 (SST, maxCo 2.5, three meshes) 21-37 % above 1.2; alpha 0 27-38 % above or 14-25 % below 2.3, by flow state (section 2) |
| Shedding frequency | Accelerometer (Nano 33 BLE Sense, >= 400 Hz) on a cantilevered printed section | `St`, `f_shed_Hz`, `spectrum.png` | needs the test; 400 Hz covers alpha 0 and 180 up to 38 m/s, edge-on needs at least 810 Hz (section 7) |
| Pressure distribution | Taps on a printed section, cheap differential sensors | `fields/surface_mean.csv` (Cp along the wall) | needs the test |
| Rotor curve shape | Rig lambda at peak C_P,el (0.120-0.122 at 23 m/s) and light-load lambda (0.158-0.160), `rotor2d/results/rotor_cp_compare_U23.json` | `CP_mean` against lambda; zero-torque lambda | compared (*computed*): hypothesis A with the curled tip leading reaches zero torque at lambda 0.159 +- 0.008, at the rig's light-load lambda at 23 m/s (a lower bound), but 0.051 below it at 38 m/s |
| Direct section forces | Bar load cell and HX711 (about $10-15) | `Cd_mean`, `Cl_mean` | needs a mount; Cd at alpha 0 (about 1.75 or 3.2) would show which flow state is real |

Pressure drag dominates (at least 98.5 % of Cd in every healthy run, *computed*; section 7), so taps
on the mean-Cp positions of `surface_mean.csv` would give nearly all of Cd. They also show whether
the model's separation points (Cf sign changes) are right.

## 12. Running on a cluster (Unity)

**Why.** On the laptop the cases ran one at a time per queue: at the 8 Oct pace the Stage 1 queue
alone would have finished on 22-23 Oct (*calculated* from the measured 9.4 h per medium case),
and the Mac had to stay awake and plugged in. A cluster runs many cases at once, each on more
and faster cores. The cases, meshes and OpenFOAM version stay the same; only the machine
changes. How to use it: `cfd/hpc/README.md`.

**The parts of a cluster.**
- *Login node.* Where `ssh unity` lands. It is shared by everyone and capped at about 2 cores
  and 8 GB per user (*measured*, 9 Oct). Use it to copy files and submit jobs, never to run a
  solver.
- *Compute nodes.* Where jobs run. The URI partition `uri-cpu` has 49 nodes of 64 Xeon cores
  each (*measured*, `sinfo`).
- *Slurm, the scheduler.* A job script starts with `#SBATCH` lines that ask for resources:
  account, partition, number of MPI tasks, memory, time limit. Slurm starts the job when a
  node has them free and stops it at the time limit. Useful commands: `squeue --me` (my jobs),
  `scancel <id>`, `sacct -j <id>` (what a finished job used).
- *Account and limits.* The lab account `pi_sodhi_uri_edu` may use up to 768 cores on
  `uri-cpu` at once (*measured*, the QOS limit). `submit.py` keeps us to 512 so labmates keep a
  share.
- *Container.* Unity has no OpenFOAM v2606 module, so the official OpenFOAM image runs through
  Apptainer: a whole Linux system with OpenFOAM in one file (`openfoam-run_2606.sif`). It is
  built from the same source commit as the Mac app. Only the compiler differs, so results
  should agree to round-off (*inferred*).

**Parallel runs are the same on both machines.** `decomposePar` cuts the mesh into N pieces,
`mpirun -np N pimpleFoam -parallel` gives each piece to one core, and neighbouring pieces swap
boundary values every step. More ranks mean less work per core, but more of the time goes to
communication. Doubling the ranks therefore never quite halves the run time.

| Run (Stage 1 medium mesh, 131k cells) | Rate | Relative |
|---|---|---|
| Unity, 16 ranks | 16.2 steps/s | about 5× the Mac (*measured*, 9 Oct benchmark job) |
| Mac, 4 ranks (three queues sharing it) | 3.6–4.1 steps/s | (*measured*) |

So `submit.py` uses 8 ranks for medium meshes, which spends fewer core-hours per case, and 16
only for the large fine and texture meshes. In production (*measured*, 8-13 Oct;
`section2d/README.md` section 6) a medium-mesh SST case ran at 0.0875-0.0893 s per step on 8 ranks
of a Xeon 6730P node, against 0.294 on the Mac's 4 ranks (with the other two queues running): a
150 c/U case took 2.6-3.1 h at maxCo 5 on Unity, 9.4 h on the Mac.

**Time limits and resuming.**
- Every job has a time limit. Slurm sends a stop signal 15 min before it; the solver stops, and
  the case keeps its last written time.
- The next submission resumes from that time, the same mechanism as `queue.py --pause` on the
  Mac.

**Moving a half-finished case between machines** (`cfd/hpc/migrate.py`, used on 9 Oct for three
Mac cases):
1. `reconstructPar -latestTime` joins the latest time of the 2 or 4 pieces back into one field
   set. This includes `uniform/`, where the averaging function objects keep their running sums.
2. That time is uploaded.
3. `decomposePar` cuts it again for the job's 8 ranks, and the solver continues to the same end
   time.

A restart writes the force and probe files into a new time folder. The summaries already join
these.

## 13. References

- Celik, I. B., Ghia, U., Roache, P. J., Freitas, C. J., Coleman, H., and Raad, P. E. (2008).
  Procedure for estimation and reporting of uncertainty due to discretization in CFD applications.
  *J. Fluids Eng.* 130(7), 078001. doi:10.1115/1.2960953
- Flack, K. A., and Schultz, M. P. (2010). Review of hydraulic roughness scales in the fully rough
  regime. *J. Fluids Eng.* 132(4), 041203. doi:10.1115/1.4001492
- Langtry, R. B., and Menter, F. R. (2009). Correlation-based transition modeling for unstructured
  parallelized computational fluid dynamics codes. *AIAA J.* 47(12), 2894-2906. doi:10.2514/1.42362
- Menter, F. R. (1994). Two-equation eddy-viscosity turbulence models for engineering applications.
  *AIAA J.* 32(8), 1598-1605. doi:10.2514/3.12149
- Nikuradse, J. (1933). Stromungsgesetze in rauhen Rohren. VDI-Forschungsheft 361 (English: NACA
  TM 1292, 1950).
- Roache, P. J. (1994). Perspective: a method for uniform reporting of grid refinement studies.
  *J. Fluids Eng.* 116(3), 405-413. doi:10.1115/1.2910291
- Savill, A. M. (1993, 1996). ERCOFTAC T3A transition test case (data in the OpenFOAM tutorial).
- Spalart, P. R., and Rumsey, C. L. (2007). Effective inflow conditions for turbulence models in
  aerodynamic calculations. *AIAA J.* 45(10), 2544-2553. doi:10.2514/1.29373
- Wilcox, B. J., White, E. B., and Maniaci, D. C. (2017). Roughness sensitivity comparisons of wind
  turbine blade sections. SAND2017-11288. doi:10.2172/1404826

Verify each reference against the source before citing it in a report; the DOIs above were not
re-checked for this log.
