# rotor2d: Stage 3, the 2D rotor (static torque and prescribed rotation)

Stages 3a and 3b of [../PLAN.md](../PLAN.md). Built 7 Oct 2026. Status: case generator,
meshes, queues and post-processing done; smoke tests run (below). 8 Oct: free stream switched
to decay control as in Stage 1 (below, "Free-stream turbulence"), post-case hook added to the
queue, both tested. **No production run launched.** The rotor assembly is not measured, so
everything runs for two hypotheses until `cfd/inputs/rig_geometry.json` exists.

Provenance labels: *measured* (read from a run or a log), *calculated* (derived from measured
values or geometry), *assumed* (an input chosen without data), *estimated* (an extrapolation).

## Files

| Path | Contents |
|---|---|
| `rotor_geometry.py` | Blade section (CAD frame), assembly hypotheses A, B and `measured`, rotation-sense rule, model-frame placement, layout plot |
| `layout/layouts_A_B.png`, `layout/poses_A_B.json` | Both layouts at theta = 0 with rotation sense, cup-opening direction and AMI circle; all pose numbers |
| `mesh/make_mesh.py` | 2D mesh generator (gmsh fill + structured near-wall ring, polyMesh written directly); runs in `../.venv` |
| `mesh/logs/` | checkMesh log and mesh summary of every mesh built (`checkMesh_<key>.log`, `mesh_info_<key>.json`) |
| `case_template/` | `system/` (controlDict, function objects, schemes, solution, decomposition) and `constant/` (transport, turbulence, `dynamicMeshDict.rotating`) |
| `run_case.py` | Create and run one case (static or rotating); resume-safe |
| `queue.py` | Sequential, resume-safe queue; writes `results/rotor_cp.csv` and `results/rotor_static.csv`; runs `../post/after_case.sh` after each completed case |
| `queues/priority{0,A,B,C}.txt` | Production queues (not launched); run order 0, A, C (B is contained in 0) |
| `results/` | CSVs, queue logs, smoke-test summaries (`results/smoke/`), comparison plots |
| `../post/rotor_summary.py` | Loads, C_Q, C_P, AMI weights, y+, upstream-probe Tu, timing from one case (works on partial runs) |
| `../post/after_case.sh` | Post-case hook: record of one case (`../post/record_case.py --kind rotor`) in `results/records/<case>/` |
| `../post/plot_rotor_cp.py` | C_P against lambda, CFD against the rig; static C_Q(theta) |
| `../post/plot_rotor_case.py` | Time history of one case (rotor and per-blade C_Q, C_x, C_y, time step) |
| `mesh/check_variants.py` | Rebuilds and checkMeshes the 16 mesh variants; `mesh/logs/variants_summary.json` |
| `runs/` | Generated cases and the mesh cache `runs/_mesh/` (git-ignored) |

## Conventions

**Section.** The true v1 section from `../geometry/section_v1.json` (clamped cubic B-spline outer
surface, constant 1.8542 mm wall, square ends), kept in its CAD frame: x along the bolt-hole axis,
y across, z along the span from the far end (z = 0) toward the near end (the end nearer the holes).
Tip A ends the long leg, tip B ends the curl; "tip" = end-face midpoint, as in
`../MEASUREMENTS_NEEDED.md`. Chord tip A to tip B 44.61 mm.

**Model frame.** Shaft axis at the origin, wind along +x, z = CAD +z, viewed from +z. If the near
end is at the top on the rig, the model is the view from above; if it is at the bottom, the model
is the mirror image and the physical rotation sense is the opposite of the model's.

**Rotation sense** s = +1 (CCW about +z) or -1 (CW). Default rule (`sense auto`): the cup opens
against the direction of motion, so the blade moving downwind meets the wind with its concave
face (drag rotor). The cup-opening direction is the mean fluid-side normal of the concave face,
which is the inner-tip chord turned by +90 deg. Override with `--sense CCW|CW`.

**Azimuth.** theta = 0 when blade 1's radial line (shaft to attachment point) points upwind (-x);
theta increases in the direction of rotation; blade k is at theta + 120(k - 1). In a rotating case
blade 1 is at theta = Omega t.

**Torque and coefficients** (per unit span; A' = 2R per unit span, the reports' A = 2RH;
R = 101.6 mm, not the outer radius):

    Q'  = s * M_z / dz                       (positive drives the rotor in its sense)
    C_Q = Q' / (0.5 rho U^2 (2R) R)
    C_P = Q' Omega / (0.5 rho (2R) U^3) = lambda C_Q,   lambda = Omega R / U
    C_x, C_y = (F_x, F_y)/dz / (0.5 rho U^2 (2R))

`forces` function objects (`forcesRotor`, `forcesBlade1..3`) use CofR = (0 0 0), the shaft axis,
rho = rhoInf = 1.204 kg/m^3; nu = 1.516e-5 m^2/s; dz = 0.01 m.

## Assembly hypotheses (inferred from CAD; not measured)

Bolts radial (the CAD hole axis is radial), chord at 84.0 deg to the radius, R = 101.6 mm from
the shaft axis to the face the arm touches, on the bolt axis.

| | A: arm on the concave face | B: arm on the convex face |
|---|---|---|
| Cup opens | toward the shaft | away from the shaft |
| r_tipA, r_tipB (mm) | 85.0, 89.1 | 125.6, 120.6 |
| r_min, r_max (mm) | 84.5, 106.4 | 99.7, 125.8 |
| Cup-opening direction (radial, tangential CCW) | (-0.992, +0.129) | (+0.992, -0.129) |
| Rotation sense (drag rule, model frame) | CW | CCW |
| Leading tip | A | A |
| AMI radius (r_max + 22 mm) | 128.4 mm | 147.8 mm |

These reproduce `../measurements/blade_section_cad.json` to 0.1 mm (r_min of B: 99.72 here against
99.8 there, from that script's coarser polyline). Figure: `layout/layouts_A_B.png`.

**Caution on the rotation sense.** With the bolts radial the cup opens almost radially: its
opening direction is only 7.4 deg (tangential component 0.129) off the radial line, so the drag
rule rests on that 7.4 deg. The chord is also only 6 deg off tangential (beta = 84 deg), so the
blades at theta = 90 and 270 deg meet the wind edge-on, one leg-first (tip A) and one curl-first
(tip B); that drag asymmetry, which the rule does not see, may set the sense (inference, not
computed). The impulsive start-up torque of both smoke tests at lambda 0.15 opposed the assumed
sense. The mean of the static C_Q over theta is the starting torque, so the static sweep for
both hypotheses (`queues/priority0.txt`) runs first; if a mean is negative beyond 2 standard
errors (`CQ_mean_over_theta_sem`, `self_start` in `results/rotor_cp_compare_U23.json`), that
hypothesis's rotating cases run with the sense reversed (`sense=` key). The azimuth grid is the
same set of blade positions in either sense, so one sense per hypothesis is enough.

## Mesh (`mesh/make_mesh.py`)

**Why gmsh plus a generated ring, not snappyHexMesh.** The wall is 1.854 mm thick with square
ends, and the first-cell height must be exact on both faces and round the four corners of every
blade (it sets y+ for the wall functions). snappyHexMesh's layer addition on a one-cell slab
collapses layers at thin, sharp edges. The near-wall ring here is a set of offset curves of the
section at exact distances, rounded at the corners with the wall nodes fanned over the corner arcs
(the scheme of `../section2d/mesh/make_mesh.py`, re-implemented for three blades in the CAD frame).
gmsh (quad-dominant, Frontal-Delaunay for quads with Blossom recombination) fills the rest with
fixed boundary nodes, which also makes the two AMI sides conformal at theta = 0.

**Regions and patches.** Rotor: disk r < r_ami minus the blades, cellZone `rotor`, patches
`blade1..3` (wall, group `blades`) and `AMI1`. Stator: box minus the disk, patches `AMI2`, `inlet`,
`outlet`, `sides`, `frontAndBack` (empty). AMI1/AMI2: cyclicAMI, faceAreaWeightAMI, no caching.
The two regions are joined only through the AMI, so checkMesh reports 2 regions; that is expected.

**Domain.** Open box: inlet 10 D_ref upstream, outlet 25 D_ref downstream, sides +-15 D_ref,
D_ref = 0.25 m (about 2 r_max of B), so 35 x 30 rotor diameters. Sides use freestream
velocity/pressure conditions (no confinement). `--walls y_lo,y_hi` (with `--x-in`, `--x-out`)
puts tunnel side walls at given model-frame y (slip by default, `--side-bc noSlip` for no-slip with
wall functions) for blockage runs once the test section is measured.

**Wall treatment.**
* `wf` (production): first-cell height h0 = 2 y+ nu / u_tau, u_tau from a flat-plate estimate
  (cf = 0.0592 Re_x^-0.2 at x = c/2) at the free-stream speed, target y+ 40 at the cell centre:
  h0 = 0.87 mm at 23 m/s, 0.55 mm at 38 m/s; at 10.2 m/s the 1.81 mm it would need is capped at
  1.5 mm (flat-plate y+ about 33) and the ring at 5 mm (the curl's inner radius of curvature is
  9.8 mm). Wall functions: nutUSpaldingWallFunction (valid at any y+), kqRWallFunction,
  omegaWallFunction. The mesh is regenerated per speed.
* `lowRe` (optional, needed for kOmegaSSTLM): h0 for y+ 0.8 with u_tau at 1.5 U (12 um at 23 m/s),
  layers growing at 1.15 to the 0.3 mm wall spacing; nutLowReWallFunction, k = 0 at the wall. About
  10x smaller time steps than `wf`; not in any queue.

**Levels** (wall-function ring layers, growth, wall spacing max/corner, fill sizes):

| Level | Ring | Wall spacing | Rotor fill near / max / AMI | Wake bands | Cells A / B (23 m/s) |
|---|---|---|---|---|---|
| coarse | 3 layers, 1.20 | 1.0 / 0.30 mm | 1.4 / 3.2 / 3.0 mm | 5 / 10 mm | 32,815 / 41,868 |
| medium | 4 layers, 1.15 | 0.7 / 0.20 mm | 1.0 / 2.3 / 2.2 mm | 3.5 / 7 mm | 61,910 / 79,756 |
| fine | 5 layers, 1.12 (4 after the 5 mm cap) | 0.5 / 0.14 mm | 0.7 / 1.6 / 1.6 mm | 2.5 / 5 mm | 118,651 / 153,870 |

The rotor zone holds 16-35 % of the cells (medium: 18,015 for A, 21,350 for B); AMI faces per
side: 272-584 (medium 368 for A, 424 for B). Meshes are cached by hypothesis, level, wall
treatment, speed and theta (`runs/_mesh/<key>/`); delete the cached directory after editing
`mesh/make_mesh.py`, or the old mesh is reused.

checkMesh results: see "Meshes checked" below and `mesh/logs/`.

## Cases

Common: pimpleFoam, incompressible URANS, kOmegaSST (default) or kOmegaSSTLM (`--model LM`, only
with `--wall lowRe`); backward in time; linearUpwind (limited) for U, upwind for k and omega
(Stage 1 found omega going negative at the square corners with higher-order schemes); PIMPLE 2
outer and 2 pressure correctors; adjustable time step at maxCo 4 (the maxCo 2 smoke test gave
the same torque history within 0.014 in C_Q, see below; priority C repeats one case at maxCo 2).
Inlet: uniform U, k and omega at the target Tu (1 %) with free-stream decay control, as Stage 1
(next section). Function objects: `forcesRotor`, `forcesBlade1..3`, `AMIWeights1`, `yPlus1`,
`probes1` (U, p, k; wake at 1, 2, 4 D; upstream at -2 D; shaft).

* **Static (3a)**, `--theta`: blades frozen at azimuth theta (the mesh is generated at theta), no
  dynamicMeshDict. 40 rotor convective times D/U (D = 2 r_max), averages over the last 25; loads
  every (D/U)/50. C_Q is reported in the hypothesis's rotation sense, with the standard error of
  its mean (`CQ_sem`, batch means over 5 batches of 5 D/U). Run theta over 0-105 deg in 15-deg
  steps (3-fold symmetry).
* **Rotating (3b)**, `--lam`: `dynamicMotionSolverFvMesh`, `solidBody` `rotatingMotion` of cellZone
  `rotor` about +z at omega = s lambda U / R. Default 8 revolutions, averages over the last 3
  (`--nrev`, `--navg`); loads every 0.5 deg, AMI weights every 5 deg, y+ every 45 deg, fields every
  half revolution (last 3 kept); max time step T/720 (0.5 deg). maxCo 4 governs: the smoke-test
  step at lambda 0.15 was 1.7-2.0e-5 s, 0.033-0.040 deg per step (about 10,000 steps per
  revolution), so the T/720 cap does not bind at any queued lambda. The wall distance is
  recomputed every step (`--wdist N` to do it every N steps).

Case names carry every option that is not the default (`_Tu`, `_sense`, `_beta`, `_yp`, `_walls`,
`_lt<m>` (length scale other than the decay mode's default), `_precomp` (`--decay precompensate`),
`_Co..n..`, `_wd`, `_rev<nrev>` and `a<navg>` for rotating, `_conv<nconv>a<navgconv>` for
static), so a queue line with a changed run length or free stream is a separate case. `--name`
overrides the folder name (tests: start it with `_`; the CSVs leave `_*` folders out).

Outputs per case: `results.json` (from `../post/rotor_summary.py`), `phase_CQ.csv` (single-blade C_Q
against blade azimuth, three blades phase-averaged, 5-deg bins), `timing.json`, logs.

## Free-stream turbulence (decay control; 8 Oct 2026)

Default `--decay control`, the Stage 1 method (`../section2d/README.md` §3). The inlet is 2.37 m
(A) or 2.35 m (B) upstream of the AMI circle (calculated: x_in = -2.5 m, less r_ami). Without
production the SST free stream decays on the way (k = k0 (1 + beta omega0 t)^(-beta*/beta),
omega = omega0/(1 + beta omega0 t), beta = 0.0828, t = L/U). The cases therefore switch on the
model's decay control (Spalart and Rumsey 2007): `decayControl yes; kInf ...; omegaInf ...;` in
`kOmegaSSTCoeffs` (`case_template/constant/turbulenceProperties`); `kOmegaSSTLMCoeffs` inherits
them (`$kOmegaSSTCoeffs`) and sets `maxLambdaIter 50`. The model adds beta* omegaInf kInf to the
k equation and beta omegaInf^2 to the omega equation, which cancel the free-stream destruction
at k = kInf, omega = omegaInf.

`run_case.py` sets the inlet and initial k = 1.5 (Tu U)^2 and omega = sqrt(k)/(Cmu^0.25 l), and
kInf, omegaInf to the same values, so Tu at the rotor equals the target from t = 0. The inlet
Re_thetat (LM only) follows Langtry and Menter (2009) for the target Tu.

**Length scale l = 1 mm (assumed; `--lt`, in m), as Stage 1.** Tu and l describe the tunnel's
free-stream turbulence, which its screens set, not the model in the test section. The section
(Stage 1) and the rotor sit in the same tunnel, so both use the same Tu and l, and the two
stages differ only in geometry. The 7 Oct value, 10 mm, belonged to pre-compensation: a larger
l means a smaller omega and less decay over the 2.4 m from the inlet. With decay control nothing
decays, so that reason no longer applies. l = 1 mm gives nu_t/nu = sqrt(3/2) Cmu^0.25 Tu U l/nu =
10.2 at 23 m/s and Tu 1 % (calculated; the T3A tutorial inlet: 12). l is fixed rather than
nu_t/nu, so a change of U changes only U, as in the tunnel. Neither the tunnel's Tu nor its
length scale is measured (`../MEASUREMENTS_NEEDED.md`).

Calculated values at Tu 1 % at the rotor (hypothesis A; B differs only in the fourth digit):

| U (m/s) | `--decay` (l) | Inlet Tu | nu_t/nu inlet / rotor | k inlet (m^2/s^2) | omega inlet (1/s) | Inlet Re_thetat |
|---|---|---|---|---|---|---|
| 10.2 | control (1 mm) | 1.000 % | 4.5 / 4.5 | 0.0156 | 228 | 584 |
| 23.0 | control (1 mm) | 1.000 % | 10.2 / 10.2 | 0.0794 | 514 | 584 |
| 38.0 | control (1 mm) | 1.000 % | 16.8 / 16.8 | 0.217 | 850 | 584 |
| 10.2 | precompensate (10 mm) | 1.27 % | 57 / 55 | 0.0253 | 29.0 | 423 |
| 23.0 | precompensate (10 mm) | 1.27 % | 130 / 125 | 0.129 | 65.5 | 423 |
| 38.0 | precompensate (10 mm) | 1.27 % | 214 / 206 | 0.351 | 108 | 423 |

The 7 Oct set-up was replaced for three reasons (calculated): nu_t/nu at the rotor was about
12 times the decay-control value (125 against 10.2 at 23 m/s); the decayed free stream reaches
the rotor only after L/U = 0.10 s at 23 m/s (11 D/U, or 0.56 revolution at lambda 0.15), and
until then the rotor sees Tu between 1.27 % and 1 %; and the inlet Re_thetat followed the inlet
Tu (423 instead of 584).

**`--decay precompensate`** keeps the 7 Oct set-up (no decay control: `decayControl no`, kInf and
omegaInf written as 0 and not read; inlet Tu raised so that the decay leaves the target; l
default 10 mm) so that the smoke tests below can be reproduced. Its case names end in
`_precomp`. Default case names did not change; no default-named case had been run (on 8 Oct
`runs/` held only `_mesh/`). `run_case.py` refuses to resume a case whose U, inlet k or omega,
kInf, omegaInf, end time, model, mode, rotation rate or mesh (hypothesis, level, wall treatment,
azimuth and the other mesh options; this matters with `--name`) differ from what the command
would set up (`--force` restarts it), so a case set up under the other free stream is never
continued.

**Test** (8 Oct, measured): static A, theta 0, 23 m/s, medium, 2 ranks under
`taskpolicy -c background` while Stage 1 ran 4 ranks on the performance cores; 240 s wall
limit, 406 steps to 1.04 D/U, 0.58 s/step. The log prints "Employing decay control with kInf
... 0.07935 and omegaInf ... 514.29563". k and omega bounding in 0 steps. Upstream probe (-2 D):
Tu 1.0000-1.0001 % throughout (`Tu_upstream_probe_pct` 1.00002 %); probes 2 D and 4 D
downstream: 1.0000-1.0009 %. Without decay control the same 1.04 D/U would have lowered the
upstream probe to 0.83 % (calculated; beta omega0 t = 0.41), so the test tells the two set-ups
apart. The test folder and its record were deleted afterwards.

## Running

```zsh
# one case (4 ranks by default; smoke tests: --np 2 --wall-limit 600)
python3 cfd/rotor2d/run_case.py --hyp A --U 23 --lam 0.15
python3 cfd/rotor2d/run_case.py --hyp B --U 23 --theta 30
python3 cfd/rotor2d/run_case.py ... --np 2 --name _test_x      # test: 2 ranks, folder runs/_test_x
python3 cfd/rotor2d/run_case.py ... --decay precompensate      # the 7 Oct free stream (smoke tests)
python3 cfd/rotor2d/rotor_geometry.py               # layouts and pose numbers
cfd/.venv/bin/python cfd/rotor2d/mesh/make_mesh.py --hyp A --level medium --U 23 --out /tmp/m --plot /tmp/m.png
```

**Order: priority 0, then A, then C.** Priority 0 (static, A and B, 16 cases) first: it decides
the rotation sense. Then priority A (rotating, 23 m/s), with `sense=` added for any hypothesis
whose mean static C_Q is negative; then priority C (set HYP to the hypothesis that matches the
rig). Priority B is contained in priority 0 (same case names), so it is not run separately.

**Alongside Stage 1, on the efficiency cores** (measured 8 Oct 2026; Apple M2, 4 performance +
4 efficiency cores). Stage 1 runs 4 ranks on the performance cores. A static rotor case (A,
theta 0, medium, 4 ranks) under `taskpolicy -c background` ran at scheduling priority 4 in every
process (queue, caffeinate, mpirun, pimpleFoam inherit the clamp), which keeps it on the
efficiency cores: 0.56 s/step (wall; 0.45 s CPU), about 5x the estimated 0.11 s/step on the
performance cores. Stage 1's cost per step over the 280 s of overlap changed by -2.9 +- 3.7 %
(regression on its solver iterations per step, which rose from 24 to 36 p-iterations as its
flow developed; +0.6 % against a linear time trend): no detectable slowdown. `-c utility` is
not enough (priority 20, may use the performance cores). At that speed priority 0 takes about
2 days on the efficiency cores (A 2.3 h, B 4.2 h per case; +-40 %), the first 8 cases (a 30-deg
mean for both hypotheses) about 1 day. The 8 Oct decay-control test (same case, 2 ranks, also
under `taskpolicy -c background`) ran at 0.58 s/step, and Stage 1's cost per step over its
4 min was 0.308 s against 0.317 s in the 4 min before (measured). So 4 ranks gave no measurable
gain over 2 on the efficiency cores in these two short samples (not a controlled comparison).
The machine is a fanless MacBook Air: a 5-min test cannot show heat-soak throttling, so check
Stage 1's seconds per step after 1-2 h and pause the rotor queue if it has risen by more than
about 15 %.

```zsh
cd /Users/stepheneacuello/Projects/windtunnel-control
# check first: all 16 'pending', no cfd/rotor2d/queues/STOP or LOCK
python3 cfd/rotor2d/queue.py --status cfd/rotor2d/queues/priority0.txt
# alongside Stage 1: efficiency cores only (QoS clamp inherited by every child, the post-case
# hook included); --detach gives its own session, its own caffeinate -i and results/queue_<date>.log
taskpolicy -c background python3 cfd/rotor2d/queue.py --detach cfd/rotor2d/queues/priority0.txt
# once Stage 1 has finished: pause, then re-launch without taskpolicy (resumes from the last write)
python3 cfd/rotor2d/queue.py --pause     # running case writes and stops; the queue then exits
# when its log says 'queue finished' (no LOCK in cfd/rotor2d/queues/):
rm cfd/rotor2d/queues/STOP
python3 cfd/rotor2d/queue.py --detach cfd/rotor2d/queues/priority0.txt
# after priority 0: python3 cfd/rotor2d/queue.py --csv; python3 cfd/post/plot_rotor_cp.py --U 23;
# edit sense= in priorityA.txt / priorityC.txt as the static means say, then
python3 cfd/rotor2d/queue.py --detach cfd/rotor2d/queues/priorityA.txt cfd/rotor2d/queues/priorityC.txt
python3 cfd/rotor2d/queue.py --status cfd/rotor2d/queues/priority*.txt
python3 cfd/rotor2d/queue.py --pause          # running case writes and stops; re-launch resumes
python3 cfd/post/plot_rotor_cp.py --U 23      # after cases complete
```

The queue skips complete cases, resumes partial ones from their last write and rebuilds
`results/rotor_cp.csv` / `results/rotor_static.csv` after each case (folders starting with `_`
are left out). A lock file stops a second queue; a case whose solver from an earlier launch is
still writing is not started (the queue stops). Note that zsh lowers `nohup ... &` jobs to
nice 5 (BG_NICE); `--detach` does not.

**Post-case hook** (8 Oct; same code as `../section2d/queue.py`). After a case completes
(`results.json` written, CSVs rebuilt) the queue runs `../post/after_case.sh <case dir>` if that
file exists and is executable. It writes the case record (`../post/record_case.py --kind rotor`:
settings, log excerpt, residual, time-step, C_Q and y+ plots, ParaView field images) to
`results/records/<case>/` and its own log to `results/records/after_case.log`; its console
output goes to the queue log. It runs in its own process group, which is killed after 30 min
(`HOOK_TIMEOUT_S`). A missing hook, a non-zero exit, a timeout or any error is logged and the
queue goes on. Under `taskpolicy -c background` the hook inherits the clamp, so its renders
also stay on the efficiency cores. Tested 8 Oct: the hook function with stub hooks (success,
exit code 3, timeout with the grandchild killed, missing, not executable, no `results.json`), the
queue loop with a stubbed solver, and `after_case.sh` on the decay-control test case (record
with `kind` rotor, written in 5 s; ParaView renders of a rotor case: pvbatch exit 0 in 21 s;
the test records were then deleted).

## Comparison with the rig (`../post/plot_rotor_cp.py`)

Rig data (read only): `reports/roughness_2026-09/build/tacho/derived/rotor_speed_by_dwell.csv`
(lambda and C_P,el at every load step; C_P,gen-in recomputed from `p_gen_in_w`, EMF x current,
which adds back the generator's I^2 R but not bearing friction), `generator_by_run.csv`, and
`reports/roughness_2026-09/build/derived/rotor_speed_by_run.csv` (light-load lambda). At 23 m/s
(Plain): lambda at peak C_P,el 0.120 and 0.122 (C_P,el 0.0017), highest loaded lambda 0.158-0.160,
light-load lambda 0.158 (`results/rotor_cp_compare_U23.json`). C_P,gen-in, closer to shaft power,
still rises down to the lowest loaded lambda (0.090; about 0.0027 there against 0.0023 at 0.12):
the electrical peak at 0.12 is set by the generator's I^2 R loss, and the aerodynamic peak is
probably at lambda 0.09 or below, outside the loaded range.

The rig's C_P is electrical and includes generator and bearing losses, and the CFD is 2D (no tip
or arm losses), so magnitudes will not agree. The comparison uses:
1. lambda at peak C_P (parabola through the top three points);
2. the zero-torque lambda (interpolated sign change of C_Q), which should sit at or above the rig's
   light-load lambda, since friction makes the rig stop short of zero aerodynamic torque;
3. the curve shape, each curve normalised by its own maximum (panel b of
   `results/rotor_cp_vs_rig_U<U>.png`).
A case that differs from production in free stream (`_precomp`), Tu, length scale, maxCo or
outer correctors (e.g. priority C's maxCo 2 check at lambda 0.15) gets its own curve and static
mean, tagged with the difference, and never enters a production curve.
The hypothesis whose lambda locations match the rig at 23 m/s goes forward to priorities B and C;
at 10.2 and 38 m/s the rig's peak moves from lambda 0.08 to 0.16-0.19, a trend the CFD should
reproduce. The static mean C_Q over theta (priority B) checks the rotation sense.

```zsh
python3 cfd/rotor2d/queue.py --csv               # rebuild the CSVs from completed cases
python3 cfd/post/plot_rotor_cp.py --U 23         # also --U 10.2, --U 38; --rotor "FS 0.10" etc.
python3 cfd/post/plot_rotor_case.py cfd/rotor2d/runs/<case>   # time history of one case
```

## Swapping in measured geometry

1. Fill `cfd/inputs/rig_geometry.json` from `../MEASUREMENTS_NEEDED.md` section 5.
2. Run with `--hyp measured` (queue column HYP = `measured`). `rotor_geometry.pose_from_rig()` uses:
   * `rotor.arm_face` (required: concave or convex);
   * if `r_tipA_mm` and `r_tipB_mm` are given (mean of the non-null blades): the shaft axis is the
     intersection of the circles about the two tips, on the concave side of the chord for an arm on
     the concave face; R and beta then follow and are printed for comparison with the measured R;
   * otherwise `attachment_radius_mm` and `setting_angle_deg` (beta) on the A/B construction;
   * `rotation_sense_from_above` with `near_end` (top: model = physical; bottom: mirrored), else the
     drag rule.
3. Check `python3 cfd/rotor2d/rotor_geometry.py --hyp measured` against photo R1 before meshing.
4. Tunnel walls: `--walls y_lo,y_hi --x-in .. --x-out ..` in model-frame metres from the test-section
   width and the rotor position (`to_left_wall`, `to_right_wall`; left looking downstream is +y if
   the near end is at the top). Tu: `--tu` from `inflow.points`.
5. Sensitivity without measurements: `--beta 79` / `--beta 89` (84 +- 5 deg), `--sense CW|CCW`.

## Assumptions and limits

* 2D slice: no arms, hub, shaft, end plates or tip losses; the slice represents a section away from
  the arms (holes at mid-span). 2D URANS overstates coherent shedding and drag (PLAN.md risks), so
  compare shapes and lambda locations, not magnitudes.
* Bolts radial, beta = 84 deg, R to the face the arm touches (CAD inference).
* Prescribed Omega (no rotor dynamics); the rig's light-load lambda includes bearing friction, so the
  CFD zero-torque lambda should be at or above it.
* Fully turbulent kOmegaSST with wall functions; Tu 1 % and length scale 1 mm (assumed, not
  measured), held from the inlet to the rotor by decay control. The SST strain production can
  still raise Tu ahead of the blades (Stage 1: to 1.29 % between 2 and 0.5 chords ahead of the
  section).
* Open domain, no blockage; the rig reports apply no blockage correction either.
* Rig comparison: the rig's C_P is electrical (or generator input with I^2 R added back), both below
  the aerodynamic C_P by the generator and bearing losses.

## Smoke tests (7 Oct 2026; 2 ranks; killed at the wall limit)

These ran with the 7 Oct free stream (no decay control, inlet Tu raised for the decay, length
scale 10 mm); `--decay precompensate` reproduces it. The 8 Oct decay-control test is under
"Free-stream turbulence".

Machine shared with the Stage 1 work (its 4-rank run during the static tests, its intermittent
2-rank tests later), so times per step are upper bounds with some scatter. Summaries, time
histories and per-case JSON: `results/smoke/` (`smoke_summary.json`). All at U = 23 m/s,
kOmegaSST, wall-function mesh.

| Case | Cells | maxCo | Wall time | Steps | s/step | dt (s) | Reached | C_Q in window |
|---|---|---|---|---|---|---|---|---|
| A static, theta 0, coarse | 32,815 | 2 | 240 s | 730 | 0.27-0.31 | 1.7e-5 | 1.3 D/U | -0.06 +- 0.11 |
| A static, theta 0, medium | 61,910 | 2 | 420 s | 2,443 | 0.17-0.18 | 1.2e-5 | 3.1 D/U | -0.05 +- 0.15 |
| B static, theta 0, medium | 79,756 | 2 | 420 s | 2,154 | 0.18-0.19 | 1.0-1.1e-5 | 2.0 D/U | -0.14 +- 0.19 |
| A rotating, lambda 0.15, coarse | 32,815 | 2 | 90 s | 403 | 0.21-0.23 | 1.8e-5 | 0.04 rev | (start-up) |
| A rotating, lambda 0.15, medium | 61,910 | 2 | 600 s | 2,297 | 0.26-0.28 | 1.0e-5 mean, falling to 7e-6 | 0.125 rev | -0.20 +- 0.13 |
| B rotating, lambda 0.15, medium | 79,756 | 2 | 600 s | 1,644 | 0.36-0.50 | 1.1-1.4e-5 | 0.097 rev | -0.13 +- 0.18 |
| A rotating, lambda 0.15, medium | 61,910 | 4 | 300 s | 1,102 | 0.27-0.30 | 2.0e-5 mean, 1.7e-5 late | 0.121 rev | -0.20 +- 0.13 |

* **Stability:** Co held at the target throughout; no omega bounding in any case.
* **AMI weights** (sum per face, both sides): exactly 1 on the static meshes (conformal at
  theta); 1.0000004-1.000018 while rotating (AMIWeights function object), 1.0-1.000033 in the
  per-step log lines.
* **y+** (wall-function value at the first cell centre; mean and maximum over each blade):
  static A 24-33 and 81-94, static B 18-38 and 58-93, rotating A at 1/8 revolution 23-37 and
  60-79. The attached, accelerating parts of the blades sit at 30-90; separated parts lower.
  nutUSpaldingWallFunction is valid across that range.
* **Time step:** maxCo 4 against 2 on the rotating A case: over the common 0.011-0.121 rev the
  C_Q histories differ by 0.006 rms (signal rms 0.133, maximum difference 0.014; window means
  -0.190 and -0.188), with twice the time step.
* **Torque sign and magnitude:** only the impulsive start-up was simulated (at most 1/8
  revolution or 3 D/U), so the signs are not yet the periodic answer. Start-up C_Q is negative
  (opposes the assumed sense) for both hypotheses at lambda 0.15, |C_Q| up to 0.46 (A) and 0.56
  (B); per-blade values change sign with position; rotor drag C_x 0.6-1.4 on 2R. For scale, the
  rig's C_Q at peak electrical power at 23 m/s is about 0.014 (C_P,el 0.0017 at lambda 0.12).
  The torque sign convention is by construction (Q' = s M_z / dz with M_z about the shaft axis).
* **Other variants:** a 60 s start with tunnel side walls (slip, y = +-0.6 m) and a 90 s start of
  kOmegaSSTLM on the low-Re mesh both ran cleanly; LM on the low-Re mesh needs dt 1.3-1.5e-6 s
  (13x more steps) at 0.46 s/step on 2 ranks (108,881 cells).

## Runtime estimates (4 ranks, maxCo 4, medium; not measured at 4 ranks)

Assumptions: 4-rank s/step = 0.6 x the 2-rank value (A rotating 0.17 s, B rotating 0.24 s,
static 0.11 s); dt at maxCo 4 = 1.3e-5 s (A) and 1.6e-5 s (B) at 23 m/s, scaled by 23/U at other
speeds (dt was still falling at 1/8 revolution in the maxCo 2 test). Uncertainty about +-40 %.

| Queue | Cases | Physical time | Steps | Estimate |
|---|---|---|---|---|
| 0 (static, 8 azimuths, A and B) | 16 | 0.37 s (A), 0.44 s (B) each | 15 k (A), 21 k (B) each | 9 h; on the efficiency cores about 53 h (measured 0.56 s/step for A, 8 Oct; B scaled by cells) |
| A (rotating, A and B, 23 m/s, lambda 0.05-0.25) | 10 | 7.36 s per hypothesis | 566 k (A) + 460 k (B) | 57 h: per case 3-8 h (A), 4-9 h (B); lambda 0.05 longest |
| B (static, 8 azimuths, hypothesis A) | 8 | 0.37 s each (40 D/U) | 15 k each | 4 h (5 h for hypothesis B) |
| C (A at 10.2 and 38 m/s, 9 cases, plus a maxCo 2 check) | 10 | 14.9 s (10.2), 3.6 s (38), 1.5 s (check) | 508 k + 452 k + 228 k | 56 h |

With the default 8 revolutions at every lambda, priority A would take 10.1 s per hypothesis,
about 80 h; the queue shortens lambda 0.05 and 0.10 to 4 and 6 revolutions (still at least
150 D/U each, see the queue file).

## Meshes checked (checkMesh 'Mesh OK.' on all 16; `mesh/logs/variants_summary.json`)

| Variant | Cells A / B | h0 | Ring | Max non-orth. | Max skewness |
|---|---|---|---|---|---|
| coarse, 23 m/s | 32,815 / 41,868 | 0.87 mm | 3 layers, 3.2 mm | 51.5 | 1.83 |
| medium, 23 m/s | 61,910 / 79,756 | 0.87 mm | 4 layers, 4.3 mm | 57.1 | 2.05 |
| fine, 23 m/s | 118,651 / 153,870 | 0.87 mm | 4 layers, 4.2 mm | 57.1 | 2.17 |
| medium lowRe, 23 m/s | 108,881 / 126,948 | 12 um | 24 layers, 2.2 mm | 54.9 / 53.1 | 2.36 |
| medium, 10.2 m/s | 60,648 / 78,445 | 1.5 mm (cap) | 2 layers, 3.2 mm | 50.5 / 55.2 | 2.84 |
| medium, 38 m/s | 62,120 / 79,844 | 0.55 mm | 4 layers, 2.8 mm | 58.0 / 52.1 | 1.76 |
| medium, static theta 60 | 61,889 / 79,815 | 0.87 mm | 4 layers | 60.9 / 57.1 | 2.05 |
| medium, side walls at y = +-0.6 m | 59,905 / 77,568 | 0.87 mm | 4 layers | 57.1 | 2.05 |

Every mesh has 2 regions (rotor and stator, joined only by the AMI), as an AMI mesh must.
`mesh/check_variants.py` rebuilds and re-checks the set.
