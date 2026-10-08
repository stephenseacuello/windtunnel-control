# Record: `_smoke_a000_U23_SST_medium_Co5n2`

Recorded 2026-10-08T07:46:47 by `cfd/post/record_case.py` from `cfd/section2d/runs/_smoke_a000_U23_SST_medium_Co5n2`. Status when recorded: **stopped** (solver log does not end with End (stopped, timed out or failed)).

> **Test record.** The folder name starts with `_`: a smoke, pipeline or scheme test, not a production case. Its numbers describe the test, not the blade; see `cfd/docs/RECORDS.md` (test records).

> This case had not finished when it was recorded, so averages and spectra describe only the part that ran. Treat every number below as provisional.

> The averaging window holds 4.1 shedding cycles; about 10 or more are needed before means and St are converged (cfd/docs/LEARNING_LOG.md section 6).

> case.json names this case `a000.0_U23.0_SST_medium_Tu1.0`; the folder was renamed (a test copy).

> The averaging window is incomplete: 0.02009 to 1.073 t U / c was available against an intended 100 t U / c. Means and the Strouhal number are not converged.

## Key numbers

| Quantity | Value |
|---|---|
| Angle of attack | 0 deg |
| Free stream | 23 m/s |
| Re (c = 48 mm) | 7.28e+04 |
| Turbulence model | kOmegaSST |
| Tu at the section | 1 % |
| Free-stream turbulence | no decay control (7 Oct set-up): far-field Tu 1.89 % decays to the section value; nu_t/nu 38.5 far field, 34.7 at the section; length scale 2 mm |
| Time-step control | maxCo 5, 2 outer correctors |
| Mesh | medium, 131061 cells, first cell 4.5 um, checkMesh OK |
| Simulated | 0.00225 s = 1.078 t U / c (0.7 % of endTime) |
| Time steps | 1387, deltaT mean 1.62e-06 s, max Co mean 4.95 |
| Cost | CPU 0.2 h, clock 2.63 h, 0.519 s CPU per step |
| Cd (mean +/- std) | 2.129 +/- 0.292 |
| Cl (mean +/- std) | 0.731 +/- 0.393 |
| Cm (mean +/- std) | 0.4285 +/- 0.144 |
| Cd pressure / viscous | 2.141 / -0.0121 |
| Strouhal number (Cl) | 3.92 (1879 Hz), 4.08 cycles in the window |
| Averaging window | 0.02009 to 1.073 t U / c (incomplete) |

## Plots and how to read them

### Force coefficients against time

![Force coefficients against time](coefficients.png)

The loads on the blade, made dimensionless: Cd = drag/(q c), Cl = lift/(q c), Cm = moment/(q c^2) per unit span, with q = 0.5 rho U^2. Time is in convective units t U/c: one unit is the time the free stream takes to travel one chord. The start is a transient (the flow is impulsively started from uniform flow) and must be discarded. The orange band is the averaging window; the red line and band are the window mean and +/- one standard deviation. A converged URANS run shows a statistically steady signal in the window: the oscillation (vortex shedding) repeats with constant amplitude and the mean does not drift. Compare the two halves of the window (the `*_drift` entries in summary.json) to check this.

### Spectrum and Strouhal number

![Spectrum and Strouhal number](spectrum.png)

The power spectrum of Cl (and Cd) over the averaging window, against the Strouhal number St = f c/U. The tallest peak of Cl is the vortex-shedding frequency; drag oscillates at twice that frequency because each shed vortex (upper and lower) pulls the body back once. A sharp, isolated peak means periodic shedding; a broad hump means irregular shedding or too short a window. The title gives the frequency resolution 1/T_window: peaks closer than that cannot be told apart, and fewer than about 10 cycles in the window make St uncertain by more than 10 %.

### Residuals

![Residuals](residuals.png)

For each solved field (Ux, Uy, p, k, omega, and gammaInt, ReThetat for the transition model) the initial residual of the first solve in each time step: the normalised imbalance of the discretised equation before the linear solver works on it. In a transient (PIMPLE) run residuals do not fall to machine zero; they settle to a band whose level depends on the time step and on how unsteady the flow is. Watch for a rising trend (divergence), sudden spikes (a bad cell, or the time step jumping), or the pressure residual not dropping within a step.

### Time step, Courant number and cost

![Time step, Courant number and cost](timestep.png)

Top: the adaptive time step deltaT. Middle: the largest Courant number Co = U deltaT / dx in the mesh, which the solver holds at or below maxCo by shrinking deltaT; the smallest, fastest cells (here the blade corners) set the time step for the whole mesh. Bottom: cumulative CPU time (ExecutionTime) against wall-clock time (ClockTime) over the time steps. On a healthy run the two lines rise together; when the clock line runs away from the CPU line the solver was not running, for example because the Mac slept (7 Oct, one session: ClockTime 8886 s against ExecutionTime 282 s). Dotted lines mark restarts.

## Field images (ParaView, `fields/`)

Rendered by `cfd/post/render_fields.py`. Fields at t = 0.001238 s, read from the reconstructed case. Colour ranges are fixed per quantity so records of different cases can be compared side by side. The grey shape is the blade (a hole in the mesh).

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
