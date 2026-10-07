# Meeting with Prof. Jahangiri, 7 October 2026

## Notes, as taken (S. Eacuello)

```
WindTunnel 20261007 w/ Jahangiri

Air Foil Slice of turbine blade into tunnel
Determine drag and lift coefficient (experimentally and theoretically)
CFD Model as well (OpenFOAM)

Cost per blade?
Time and money per blade?
Shrink height of the blade if needed?

One more test with a higher roughness
2X or 3X higher to see if it still goes higher (or lower)
We will make a 320micrometer Ra sample using a 0.805mm FS thickness

What is the sweet spot of surface roughness? Optimal?

Read the Sandia report that Muszynski found and understand what it says about roughness and what
it predicts for our experiments
```

## Action items

| # | Item | Notes |
|---|---|---|
| 1 | **Blade-section ("airfoil slice") test** | Lift and drag against angle of attack, measured and from theory. |
| 2 | **CFD in OpenFOAM** | Validate against item 1. |
| 3 | **Cost and time per blade** | Material is known; print time needs a sliced file. |
| 4 | **Higher-roughness test** | 2× and 3–4× the FS 0.20 thickness. |
| 5 | **Find the optimum roughness** | Needs more levels, replicated. |
| 6 | **Sandia report** | Summary and predictions below. |

### 1. Blade-section test
- Print a 2D section of the blade profile, spanning the test section or fitted with end plates.
- Measure lift and drag against angle of attack.
- What it needs:
  - a force balance or load cells and a mount;
  - the test-section dimensions, which are also needed for a blockage correction.
- Theory: the blade is a thin curved plate (183° arc, 48 mm chord), not an airfoil, so thin-airfoil
  theory applies only loosely. Bluff-body drag data for curved plates may be the closer reference.

### 2. CFD in OpenFOAM
- Start with the smooth 2D section, then the rotor.
- The chord Reynolds numbers, 3×10⁴ to 1.2×10⁵, are transitional, so a transition-capable model is
  needed (for example k-ω SST with γ–Reθ).
- Roughness would enter through an equivalent sand-grain height or rough-wall functions. Resolving
  the fuzzy texture geometrically is impractical.
- Validate against item 1 before using it to predict.

### 3. Cost and time per blade
- **Material:** about **$1 per blade, $3 per set of three**. The blade model is 31.0 cm³, which is
  39 g of PLA at 1.26 g/cm³ and $24.99/kg (the slicer project's settings). A 1.79 mm wall printed
  with 4 wall loops is essentially solid.
- **Print time:** unknown. The slicer project was saved unsliced. Muszynski's file of 12 Aug
  (`turbines_threeFuzzySettings_06mm_plate_2.gcode.3mf`) is sliced and carries Bambu Studio's
  time estimate. The Print Lab's rate is also unknown.
- **Shrinking the span** reduces time and material in proportion. It changes the rotor (swept area,
  aspect ratio, Reynolds numbers stay the same), so it would need its own Plain reference.

### 4. Higher-roughness test
- **Naming.** "Ra 320" follows the old label pattern (Ra 20/40/80 for 0.05/0.10/0.20 mm). It is
  not a measured value: FS 0.20 measured Ra 10.3 µm and Pa 28.7 µm. A 0.805 mm print will not have
  Ra 320 µm. Call it **FS 0.80**, and measure it.
- **Levels.** Print **FS 0.40 as well as FS 0.80**. With only FS 0.80, a lower result could not be
  told apart from a peak between 0.20 and 0.80.
- **Printability.** A displacement of up to ±0.8 mm on a 1.79 mm wall:
  - check the slicer preview and Bambu Studio's limit on fuzzy-skin thickness;
  - check the wall loops, since inward displacement thins the wall to about 1 mm;
  - the outer shape then deviates from the CAD model by up to 0.8 mm (1.7% of chord, 3% of
    depth), so geometry becomes a larger confound.
- **Matched reference.** In the same print job, include a new Plain at 0.1 mm layers and repeats of
  FS 0.10 and FS 0.20. That fixes the v1 confounds of layer height, print batch and run order.

### 5. Finding the optimum roughness
- At least five levels (0, 0.05, 0.10, 0.20, 0.40, 0.80 mm), with two prints each, run in random
  order.
- Fit power gain against fuzzy-skin thickness, and against measured roughness once the surface
  scans are adequate (report recommendation 5).

## The Sandia report: what it says and what it predicts for us

Wilcox, White & Maniaci, *Roughness Sensitivity Comparisons of Wind Turbine Blade Sections*,
SAND2017-11288 (2017), doi:10.2172/1404826. Shared by A. Muszynski; sent to Profs Jahangiri and
Jeong on 5 Aug 2026.

**What they did.**
- Insect roughness was simulated with vinyl decals: 100–200 µm high, 3–15% coverage, placed where
  an impingement code predicts insects strike.
- Tested on an NREL S814 airfoil (24% thick) at chord Reynolds numbers of 1.6–4.0×10⁶.
- Lift and drag came from pressure taps and transition location from infrared imaging.
- Losses were turned into annual-energy losses with blade-element momentum for the NREL 5 MW
  turbine.

**What they found.**
- Roughness lowers maximum lift, lift-curve slope and lift-to-drag ratio, and raises drag:
  maximum L/D falls 38% with 200 µm roughness.
- Height matters more than density.
- More height, density or Reynolds number moves bypass transition forward, consistent with
  critical roughness Reynolds numbers.
- Energy losses of 4.9–6.8% with 200 µm roughness.

**Why the sign need not carry over to our rotor.**
- They studied lift-driven airfoils at Re ≈ 10⁶, where roughness only costs performance.
- Our rotor is drag-driven: tip-speed ratio 0.08–0.18 at peak power, thin curved plates at
  Re 3×10⁴ to 1.2×10⁵.
- On drag-driven bluff bodies, roughness can reduce drag by triggering transition and delaying
  separation, as on a circular cylinder (Achenbach 1971, cited in the report).
- Our gains are consistent with that mechanism, not with Sandia's losses. Sandia does not predict
  gains for us; it does not forbid them either.

**The tool we can borrow: the roughness Reynolds number Re_k = u_k k / ν.**
- u_k is the boundary-layer velocity at the roughness height k.
- Transition begins to move forward for 2D roughness at Re_k ≈ 40–260.
- For isolated 3D roughness the critical value is about 600–900 × (k/d)^0.4.

**Our numbers (rough).**
- Roughness height k, taken as half the 1–99% height range of each scan:
  - about 38 µm for Plain, FS 0.05 and FS 0.10;
  - 84–97 µm for FS 0.20.
- Upper bound on Re_k, taking u_k = U, over 12–38 m/s:
  - 30–100 for the first three;
  - 70–240 for FS 0.20.
- So FS 0.20 sits inside the onset range at the higher wind speeds, and the others sit at or below
  it.
- If k grows about fourfold for FS 0.80, its Re_k would be roughly 300–900: past onset at every
  test speed.
- Caveat: the same k (38 µm) for Plain, FS 0.05 and FS 0.10 cannot explain FS 0.10's +12.8%. This
  height measure does not rank power either.

**A testable prediction for the FS 0.40 and FS 0.80 round.** If the gains come from
roughness-triggered transition:
- the effect should start at lower wind speeds as roughness grows;
- the band of largest gains should move down;
- once transition is forced at every speed, more roughness only adds skin friction, so the gain
  should level off or fall. That point is the optimum.

If FS 0.80 shows no shift, the transition explanation weakens, and mechanical causes such as
mounting, balance and the magnet gain weight.

## Carried forward

These come from the v1 report and the supplement:
- replicate prints and an interleaved run order;
- the redesigned base plate with a longer shaft;
- the Nano 33 BLE Sense for air temperature, pressure and vibration;
- a balanced tachometer target;
- longer load steps;
- a spin-down test;
- more surface scans.

Still open:
- ask T. Kang what his three undocumented channels are;
- Revision 2 of the report is drafted and waits for the professors' comments.

## Follow-up (7 Oct, after the meeting)

**Naming.** Stephen confirms "Ra 320" is the label for FS 0.805 mm, following the label pattern;
it is not a measured Ra.

**Email to Cam drafted.** A Gmail draft to Cam Amaral, I²(s) Print Lab, via coe3d@etal.uri.edu. It
asks:
- which nozzle, printer and spool were used for each tested set;
- the source of the "Ra 20" (0.050 mm) set;
- the plain set's settings;
- the August "40 µm" reprints;
- the sliced files;
- time and cost per blade, and whether a shorter span helps;
- whether "Ra 320" (0.805 mm) and "Ra 160" (0.40 mm) are feasible;
- a quote for 12 sets (two per level).

**From the email history**
- Stephen's 1 Oct note to Prof. Sodhi raised doubts about layer heights and labels on the printed
  blades.
- Andrew Muszynski's August blades were printed without a 0.2 mm nozzle (0.08 mm layers).
- The ISE printer never received a 0.2 mm nozzle; 0.4 mm nozzles were delivered instead.
- The slicer project specifies a 0.2 mm nozzle, but no email confirms which nozzle was mounted for
  each tested set.
- Tim Richards relayed in July that a blade takes about 2 h to print.
- Prof. Sodhi wrote in July that 0.5–0.8 mm fuzzy skin gives a texture "you can really feel".

**From the slicer file**
- The unused third plate is "10 RA" at 0.025 mm. The label pattern is Ra ≈ 400 × thickness, with
  Ra in µm and thickness in mm.
- The blade mesh gives a wall of about 1.85 mm against 1.79 mm in `rotor_geometry.json`. Check
  which is right before Revision 2 and before the CFD.

**Nano 33 BLE Sense.** It can measure vibration and wobble, and shedding frequency at 400 Hz or
faster. It cannot measure lift or drag; a cheap bar load cell with an HX711 board could.

**CFD.** Planned in `cfd/PLAN.md` (OpenFOAM v2606 is installed). Not started.
