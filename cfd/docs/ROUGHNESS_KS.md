# From measured roughness to sand-grain ks (Stage 2)

Written 8 Oct 2026 for `cfd/stage2/` (Stage 2b sweep Ks = 0-400 um, Stage 2e resolved texture).
Provenance labels as in the project reports: *literature-established*, *measured*, *calculated*,
*assumed*, *inferred*, *uncertain*. Literature values below were written from memory, not
re-checked against the sources on 8 Oct: verify each before citing it in a report.

## 1. What ks is, and why no measurement gives it directly

- **ks** (equivalent sand-grain roughness) is the grain size of Nikuradse's closely packed sand
  that gives the same downward shift of the log-law velocity profile as the surface under test,
  in fully rough flow (*literature-established*; Nikuradse 1933, Schlichting). It is a
  hydrodynamic property; it is found by measuring drag, not by scanning the surface.
- **What a rough wall function does with it.** OpenFOAM's `nutkRoughWallFunction` (v2606 source,
  `nutkRoughWallFunctionFvPatchScalarField.C`, read 8 Oct) forms Ks+ = u* Ks/nu with
  u* = Cmu^0.25 sqrt(k_P) and divides the log-law constant E by a roughness function
  fn(Ks+, Cs): 1 below Ks+ = 2.25, a transitional form up to Ks+ = 90, 1 + Cs Ks+ above. The
  source header gives only the range Cs = 0.5-1.0; that 0.5 reproduces Nikuradse's uniform sand
  is the usual reading in the literature (*uncertain*, from memory: verify before citing).
- **Regimes** (*literature-established*): hydraulically smooth below Ks+ of about 5 (the
  OpenFOAM function switches at 2.25), transitionally rough to about 70-90, fully rough above.

## 2. What was measured on the blades

| Quantity | Plain | FS 0.05 | FS 0.10 | FS 0.20 | Source |
|---|---|---|---|---|---|
| Fuzzy-skin setting t (mm) | none | 0.050 | 0.101 | 0.202 | slicer (roughness report) |
| Pa (um), primary profile | 19.0 | 13.9 | 13.2 | 28.7 | *measured*, roughness report table |
| Ra (um), roughness profile | 12.7 | 9.4 | 8.2 | 10.3 | *measured*, roughness report table |
| k (um), half the 1-99 % height range of a scan | about 38 | about 38 | about 38 | 84-97 | *measured*, meeting notes of 7 Oct |
| Peak power change vs Plain | reference | +1.8 % [-0.6, +4.2] | +12.8 % [+10.1, +15.5] | +16.2 % [+13.5, +19.0] | *measured*, roughness report |

The fuzzy skin displaces each outer-wall point by up to +-t at a point distance of 0.2 mm (slicer
definition as used in this project; *uncertain* whether the offsets are uniformly distributed). In
the PrusaSlicer fuzzy-skin code, from which Bambu Studio derives, the offsets are uniform in
[-t, t] and the spacing of the points is itself random, 0.75-1.25 times the point distance
(*uncertain*: from memory, not checked against the Bambu Studio source); the Stage 2e mesher uses a
fixed 0.2 mm. The printed bead (0.2 mm nozzle specified) then rounds the polyline. Fuzzy skin was
painted on 96.5 % of the blade surface; the unpainted area outside the spanwise end caps,
955.5 mm^2 (*measured*, slicer project summary of the roughness report, `turbine_default_summary.json`),
is close to the two square tip faces, 2 x 1.854 mm x 245 mm = 909 mm^2 (*calculated*), so the tip
faces are taken as unpainted (*inferred*; Stage 2 patch `bladeEnds`).
The blades were printed upright, so the displacement lies in the section plane and changes
from layer to layer: in 3D the texture is random along the span with a correlation length of
about one layer height (*inferred* from the print orientation).

Neither Ra nor Pa ranks the four surfaces as t does (Ra: Plain highest), and k is the same for
Plain, FS 0.05 and FS 0.10. The scans therefore do not resolve the fuzzy texture as the slicer
specifies it (*inferred*). Open alternatives, none tested: the printed displacement is much smaller
than t (the bead and the extrusion smooth it); the scan direction or the cut-off filter misses
it; the scans are too few (report recommendation 5).

## 3. Rules of thumb, and the ks they give

| Rule | Basis | ks for Plain / FS 0.05 / FS 0.10 | ks for FS 0.20 | Status |
|---|---|---|---|---|
| ks = k | roughness height taken as the sand height | about 38 um | 84-97 um | *assumed*; crude, ignores shape and density |
| ks = 3-6 Ra | engineering rules for machined and random surfaces (for example Adams et al. 2012 give ks = 5.86 Ra) | 25-76 um (Ra 8.2-12.7) | 31-62 um (Ra 10.3) | *uncertain*: AM surfaces in the literature span ks/Ra of several-fold (for example Stimpson et al. 2016) |
| ks = 3-6 Pa | as above, with the unfiltered profile (includes waviness) | 40-114 um (Pa 13.2-19.0) | 86-172 um (Pa 28.7) | *uncertain*; waviness is not roughness in the sand-grain sense |
| ks = 4.43 Rq (1 + Sk)^1.37, Sk = 0 | Flack and Schultz (2010), fully rough regime | from the nominal texture (row below) | | *literature-established* correlation; our surfaces are not fully rough (section 4) |
| Nominal texture: uniform +-t at 0.2 mm, linear between | Rq of that profile = 0.471 t, Ra = 0.397 t (*calculated*, 2e6-sample Monte Carlo); with the row above, ks = 2.09 t | 0 / 104 / 211 um | 422 um | upper estimate: the measured Ra (8-13 um) is 2-8 times smaller than the nominal Ra (20, 40, 80 um) |
| Planned FS 0.40 / FS 0.80 (nominal texture) | as above | 835 um / 1.68 mm | | far beyond the wall-function mesh (section 5) |

**Result.** The plausible ks of the tested surfaces spans about 25-420 um, an order of magnitude
of uncertainty: 25-170 um from the scans, 38-97 um from k, up to about 420 um for FS 0.20 from the
nominal texture. The Stage 2b sweep (0, 50, 100, 200, 400 um) covers that span. No rule above
reproduces the measured order of power gains (FS 0.10 +12.8 % with the same k and a lower Ra than
Plain); ks is a sensitivity parameter here, not a value derived for each rotor.

## 4. Roughness Reynolds numbers in our flow

Ks+ = u* Ks/nu. With the flat-plate u* used to size the wall-function mesh (0.67 / 1.39 / 2.19 m/s
at 10.2 / 23 / 38 m/s; Schlichting cf at x = 22 mm; *calculated*, `cfd/stage2/mesh/make_mesh.py`):

| Ks (um) | 10.2 m/s | 23 m/s | 38 m/s |
|---|---|---|---|
| 50 | 2.2 | 4.6 | 7.2 |
| 100 | 4.4 | 9.2 | 14.5 |
| 200 | 8.9 | 18.4 | 28.9 |
| 400 | 17.7 | 36.8 | 57.8 |

(*calculated*; the developed-flow Ks+ of every Stage 2b case is in its CSV row, `ksplus_blade_*`,
estimated as y+ Ks/y_P.) Away from the corners the surfaces are therefore smooth to transitionally
rough; near the square corners u* is several times larger (Stage 1 smoke test: u* about 10 m/s at
the corners, `section2d/README.md` section 2). This matches the conclusion of
`LEARNING_LOG.md` section 9 from the low-Re y+.

Keep apart the two roughness Reynolds numbers: Ks+ (drag of a turbulent rough wall, what the
wall function models) and Re_k = u_k k/nu (roughness-induced transition of a laminar layer, the
meeting-notes criterion after Wilcox et al. 2017). The wall function cannot represent the second.

## 5. Consequences for the Stage 2 cases

- **2b rough wall function.** A cell-centre height y_P below Ks puts the first cell inside the
  roughness, where the rough log law does not apply. The wall-function mesh therefore keeps
  y_P >= 1.1 x 400 um (h0 = 0.88 mm at 23 and 38 m/s, 1.30 mm at 10.2 m/s). ks of 0.8-1.7 mm (the
  nominal FS 0.40 and FS 0.80 textures) would need h0 of 2-4 mm on a 1.85 mm wall with
  1.85 mm end faces: outside what this 2D wall-function model can represent.
- **2b models a turbulent rough wall, not tripping.** The sweep gives the skin-friction and
  form-drag change of a fully turbulent layer with roughness; the transition effect is bracketed
  separately (Stage 2a: SST against LM).
- **2e resolved texture** meshes the nominal texture itself (uniform +-t at 0.2 mm, linear), so it
  uses the upper end of the mapping above. In 2D the texture becomes spanwise-uniform ridges,
  which trip a laminar layer at lower Re_k than the 3D random texture of the print (meeting
  notes: Re_k about 40-260 for 2D roughness against 600-900 (k/d)^0.4 for isolated 3D roughness),
  so 2e overstates tripping.

## References (verify before citing)

- Adams, T., Grant, C., and Watson, H. (2012). A simple algorithm to relate measured surface
  roughness to equivalent sand-grain roughness. *Int. J. Mech. Eng. Mechatronics* 1(1), 66-71.
- Flack, K. A., and Schultz, M. P. (2010). Review of hydraulic roughness scales in the fully rough
  regime. *J. Fluids Eng.* 132(4), 041203. doi:10.1115/1.4001492
- Nikuradse, J. (1933). Stromungsgesetze in rauhen Rohren. VDI-Forschungsheft 361 (NACA TM 1292).
- Stimpson, C. K., Snyder, J. C., Thole, K. A., and Mongillo, D. (2016). Roughness effects on flow
  and heat transfer for additively manufactured channels. *J. Turbomach.* 138(5), 051008.
  doi:10.1115/1.4032167
- Wilcox, B. J., White, E. B., and Maniaci, D. C. (2017). Roughness sensitivity comparisons of wind
  turbine blade sections. SAND2017-11288. doi:10.2172/1404826
