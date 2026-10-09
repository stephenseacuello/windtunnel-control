# Record: `B_sta_U23.0_th000.0_SST_medium`

Recorded 2026-10-08T16:09:46 by `cfd/post/record_case.py` from `cfd/rotor2d/runs/B_sta_U23.0_th000.0_SST_medium`. Status when recorded: **finished** (solver log ends with End).

## Key numbers

| Quantity | Value |
|---|---|
| Mode | static |
| Hypothesis | B |
| Free stream | 23 m/s |
| Turbulence model | kOmegaSST |
| Wall treatment | wf |
| Frozen azimuth | 0 deg |
| Free-stream turbulence | decay control on (kInf, omegaInf): Tu 1 % from the inlet to the rotor, nu_t/nu 10.2, length scale 1 mm |
| Time-step control | maxCo 4, 2 outer correctors |
| Mesh | medium, 79756 cells, first cell 870 um, checkMesh OK |
| Simulated | 0.4375 s = 40 t U / D (100.0 % of endTime) |
| Time steps | 19106, deltaT mean 2.29e-05 s, max Co mean 4 |
| Cost | CPU 4.41 h, clock 5.17 h, 0.832 s CPU per step |
| C_Q (mean +/- std) | 0.07892 +/- 0.318 |
| Averaging window | 15 to 40 t U / D (complete) |
| y+ (function object) | blade1: mean 23.7, max 97.1; blade2: mean 26.5, max 87.3; blade3: mean 28.4, max 86.3 |

## Plots and how to read them

### Force coefficients against time

![Force coefficients against time](coefficients.png)

Torque coefficient C_Q = Q'/(q 2R R) and power coefficient C_P = lambda C_Q per unit span (q = 0.5 rho U^2, swept width 2R) against revolutions (rotating) or t U/D (static), plus the in-plane force coefficients. The first revolutions are a start-up transient; the shaded band is the averaging window (the last revolutions), the red line and band the window mean and +/- one standard deviation. Three blades produce a torque ripple at three times the rotation frequency.

### Spectrum and Strouhal number

![Spectrum and Strouhal number](spectrum.png)

The torque spectrum over the window. For a rotating rotor the axis is frequency divided by the rotation frequency, so blade passing appears at 3; for a static rotor the axis is St_D = f D/U, the shedding frequency of the whole rotor.

### Residuals

![Residuals](residuals.png)

For each solved field (Ux, Uy, p, k, omega, and gammaInt, ReThetat for the transition model) the initial residual of the first solve in each time step: the normalised imbalance of the discretised equation before the linear solver works on it. In a transient (PIMPLE) run residuals do not fall to machine zero; they settle to a band whose level depends on the time step and on how unsteady the flow is. Watch for a rising trend (divergence), sudden spikes (a bad cell, or the time step jumping), or the pressure residual not dropping within a step.

### Time step, Courant number and cost

![Time step, Courant number and cost](timestep.png)

Top: the adaptive time step deltaT. Middle: the largest Courant number Co = U deltaT / dx in the mesh, which the solver holds at or below maxCo by shrinking deltaT; the smallest, fastest cells (here the blade corners) set the time step for the whole mesh. Bottom: cumulative CPU time (ExecutionTime) against wall-clock time (ClockTime) over the time steps. On a healthy run the two lines rise together; when the clock line runs away from the CPU line the solver was not running, for example because the Mac slept (7 Oct, one session: ClockTime 8886 s against ExecutionTime 282 s). Dotted lines mark restarts.

### y+ against time

![y+ against time](yplus.png)

y+ = u_tau y / nu is the height of the first cell centre in wall units (u_tau = sqrt(tau_w/rho) is the friction velocity). The low-Reynolds-number treatment used for the section (and for kOmegaSSTLM) needs y+ of about 1 or less everywhere on the wall; wall functions need about 30-300. The band is the min-max over the wall, the line the wall average, sampled by the yPlus function object. The maximum sits at the sharp corners, where the flow accelerates around the end faces.

## Field images (ParaView, `fields/`)

Rendered by `cfd/post/render_fields.py`. Fields at t = 0.4375 s, read from the reconstructed case. Colour ranges are fixed per quantity so records of different cases can be compared side by side. The grey shape is the blade (a hole in the mesh).

**mesh_domain**: Whole computational domain. The far-field boundary is many chords away so that it does not disturb the flow near the blade.

![mesh_domain](fields/mesh_domain.png)

**mesh_near**: The mesh within a few chords: a body-fitted layer of thin cells around the blade, a refined band where the wake goes, and coarser cells further out.

![mesh_near](fields/mesh_near.png)

**mesh_cornerA_6mm**: Close-up of one blade tip: the 1.85 mm end face and its two square corners.

![mesh_cornerA_6mm](fields/mesh_cornerA_6mm.png)

**mesh_cornerA_0p8mm**: Closer: the wall-normal cell layers growing away from the wall at a geometric rate.

![mesh_cornerA_0p8mm](fields/mesh_cornerA_0p8mm.png)

**mesh_cornerA_0p1mm**: Closest: the first cells at the corner. Their height (first cell h0) sets y+; compare with the y+ plots.

![mesh_cornerA_0p1mm](fields/mesh_cornerA_0p1mm.png)

**mesh_ami**: The sliding interface (AMI) between the rotating disc and the fixed outer mesh; the two sides do not share nodes, and the AMI interpolates fluxes across it.

![mesh_ami](fields/mesh_ami.png)

**velocity_near**: Velocity magnitude |U|/U_inf near the blade (0 to 1.6). Dark: slow, separated flow; bright: flow accelerated around the tips.

![velocity_near](fields/velocity_near.png)

**velocity_wake**: |U|/U_inf over about 9 chords of wake: the velocity deficit and the shed vortices.

![velocity_wake](fields/velocity_wake.png)

**vorticity_near**: Spanwise vorticity omega_z c/U_inf (red counter-clockwise, blue clockwise): the shear layers leaving the sharp tips and rolling up into vortices.

![vorticity_near](fields/vorticity_near.png)

**vorticity_wake**: omega_z c/U_inf in the wake: the von Karman street of alternating vortices.

![vorticity_wake](fields/vorticity_wake.png)

**cp_near**: Pressure coefficient Cp = (p - p_inf)/(0.5 U_inf^2): Cp = 1 at a stagnation point, negative where the flow is fast or in vortex cores. Pressure drag comes from high Cp on the front and low Cp on the back.

![cp_near](fields/cp_near.png)

**nut_ratio_near**: Turbulent viscosity ratio nu_t/nu (log scale): where the turbulence model adds mixing. High in separated shear layers and wakes; it should be small (order 1-10s) in the attached boundary layer of a transitional run.

![nut_ratio_near](fields/nut_ratio_near.png)

**nut_ratio_wake**: nu_t/nu in the wake.

![nut_ratio_wake](fields/nut_ratio_wake.png)

**lic_near**: Line-integral convolution: a texture smeared along the velocity direction, coloured by |U|/U_inf. It shows the flow topology (separation, vortices, saddle points) at every point.

![lic_near](fields/lic_near.png)

**streamlines_near**: Streamlines of the velocity: lines everywhere tangent to U.

![streamlines_near](fields/streamlines_near.png)

**surface_inst**: Wall distributions along the blade (s/c from tip A's outer corner, counter-clockwise): Cp (axis inverted, as is customary), skin friction Cf (sign = near-wall flow direction; a sign change marks separation or reattachment) and y+ of the first cell.

![surface_inst](fields/surface_inst.png)

- Note: no animation: 1 saved field time(s) (purgeWrite keeps the last 3; finished cases keep only the last)

## Other files

- `summary.json`: the numbers above and more (sessions, warnings, y+ statistics).
- `settings.txt`: every dictionary that defines the run, and the boundary conditions.
- `log_excerpt.txt`: solver sessions (CPU against clock time), warnings, header, last 50 lines.
- `coefficients.csv`, `residuals.csv`: decimated histories (at most 5000 rows) for re-plotting.
- `checkMesh.log`, `mesh_info.json`: mesh quality and generator parameters.

Background for every plot: `cfd/docs/LEARNING_LOG.md`.
