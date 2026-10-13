# CFD of the fuzzy-skin VAWT blade: results of the first 150 cases

13 October 2026 · S. Eacuello · for Profs Sodhi, Jahangiri and Jeong, and T. Kang

**Scope.** 150 finished 2D URANS simulations (OpenFOAM v2606) of the v1 blade section and the
3-blade rotor, addressing the requests of 7 Oct: section lift and drag, an OpenFOAM model, and a test
of whether fuzzy-skin roughness raises power by tripping the boundary layer. Every CFD number is
computed from the result tables and was recomputed by independent scripts (`src/*_verify.py`,
`src/team_summary_check.py`); measured numbers come from the 1 Oct report. Claims carry their
provenance (computed, measured, literature, inferred, estimated) and strength (established,
indicative, unresolved); "not resolved" bounds a difference and does not mean "equal". A section
change is resolved when it exceeds its *noise*, the sum of the two runs' drifts over the averaging
window; rotor values carry ± 2u, twice the averaging uncertainty. A *flagged* run is one whose
numbers are corrupted; a *healthy* run is one that is not flagged, which does not mean converged.
Full account: [RESULTS.md](RESULTS.md). Files and reruns: [README.md](README.md).

## Headline results

1. **In the fully turbulent models, roughness works against a drag rotor** (computed; the sign is
   established for the rough wall functions within these 2D models; the link to power is inferred).
   - Rough wall functions (SST, 23 m/s) raise the convex-side drag by 1.1, 2.4 and 5.8 % at Ks 100,
     200 and 400 µm (each 33–153 times its noise). They lower the concave-minus-convex drag difference
     by 19.3 % at 400 µm. Two-thirds of that is a fall of the concave-side drag, which exceeds its
     noise only at 400 µm (1.2 times) and is seen only in the high-drag state (point 3).
   - The 0.20 mm texture meshed into the wall raises the convex-side drag by 13.7 % (SST; indicative:
     these α-180 runs at maxCo 5 have no time-step check, and their time step is 0.6 times that at α 0).
   - On a quasi-steady drag-rotor model these changes reduce power. The tunnel measured +12.8 %
     [+10.1, +15.5] (FS 0.10) and +16.2 % [+13.5, +19.0] (FS 0.20) peak electrical power (geometric
     mean over 10.2–38 m/s, Tukey simultaneous 95 %).
2. **The tripping hypothesis is not yet tested** (computed; unresolved).
   - The transition model (LM) shows no texture effect larger than its noise at 23 m/s: Cd changes of
     −2.8 to +2.6 %, against noise of 4.5–8.4 % of Cd. The quasi-steady model says the measured gains
     need only about a 2 % change in section drag (inferred).
   - The only result with the sign tripping needs, fully turbulent minus transitional drag difference
     on the smooth texture mesh (+18.6 %), is within its noise.
3. **Numerical quality limits absolute values** (computed; established).
   - 23 of 51 smooth-section runs are flagged, all on the medium mesh at maxCo 5 (23 of the 39 such
     runs), including all 8 at α 180. The other 28 are healthy.
   - With the cup into the wind (α 0), the healthy runs settle in a high-drag state (Cd 2.97–3.22) or
     a low-drag state (1.75–2.01). At 23 m/s, SST is high-drag at maxCo 5 (Mac) and low-drag at
     maxCo 2.5 (Unity) on both meshes tested (−43 to −45 %): the time step is the likely trigger, not a
     proven one (inferred: the SST maxCo-5 runs on Unity at 10.2 and 38 m/s are also high-drag). The
     published shell value, 2.3 (literature), lies between; which state, if either, is physical is
     unresolved.
   - Coarse, medium and fine meshes (SST, maxCo 2.5) differ by 9.0 % (α 0) and 11.5 % (α 180) in drag
     without converging.
4. **For one assembly, the 2D rotor reaches the rig's light-load λ at 23 m/s, but not the rig's speed
   trend** (computed; indicative).
   - Only assembly hypothesis A (arms on the concave face), turning with the curled tip leading, is
     shown to have positive torque from rest into the rig's operating range: static C_Q +0.064 (41 SEM
     of time averaging; the two interleaved 30° azimuth subsets give +0.059 and +0.069), positive
     through λ 0.10. B in its drag-rule sense is unresolved (static +0.018, subsets of opposite sign).
   - A's zero torque is at λ 0.159 ± 0.008, at the rig's light-load λ at 23 m/s (0.158–0.160, a
     lower bound on the rig's zero-torque λ because of friction). At 38 m/s it is 0.156 ± 0.033,
     0.051 below the rig's 0.207 (3.1u).
5. **The present runs cannot resolve an effect of the measured size** (computed noise; the implied
   signal is estimated). The rig's gains imply a rotor torque change ΔC_Q of 0.0020–0.0026, against
   0.0096 (2u) averaging noise for a rough-minus-smooth difference and 0.005–0.007 from the time step.
   Resolving it needs about 42–66 averaged revolutions per run (3 now), about 11–20 h each on 8 ranks
   (estimated).

## What was run

| Stage | Cases | Purpose |
|---|---|---|
| 1. Smooth section | 51 (28 healthy) | Cd, Cl, Cm, St against α (LM, 23 m/s); α 0 and 180 at 10.2/23/38 m/s and Tu 0.5/1/3 %; SST against LM; grid (3 meshes) and time step (maxCo 5, 2.5) |
| 2. Roughness on the section | 43 | Rough wall functions, Ks 0–400 µm, SST, α 0/90/180 at 23 m/s, α 0 also at 10.2 and 38 m/s (27); fuzzy texture meshed into the wall, t 0–0.20 mm, SST and LM, α 0 and 180, 23 m/s (16) |
| 3. Rotor (2D, 3 blades) | 56 | Static torque against azimuth, assembly hypotheses A and B (16); C_P against λ, A at 10.2/23/38 m/s and B at 23 m/s, both rotation senses, 2 time-step checks (40) |

Tu 1 % and a 1 mm length scale are assumed (the tunnel's Tu is not measured). The rotor runs use
SST with wall functions on one mesh, and the rotor assembly is inferred from the CAD.

## Key figures

1. [fig/roughness_drag_difference.png](fig/roughness_drag_difference.png): roughness lowers the
   concave-minus-convex drag difference in the fully turbulent models (a; b, SST), while measured
   peak power rose (c).
2. [fig/roughness_texture.png](fig/roughness_texture.png): with the texture meshed into the wall, SST
   raises the convex-side drag (+7.1 %, +13.7 %; no time-step check); the LM changes stay within noise.
3. [fig/roughness_alpha0_states.png](fig/roughness_alpha0_states.png): cup into the wind at 23 m/s,
   every case in both tables falls in a high-drag or a low-drag state; the state goes with mesh
   family, maxCo and Tu, not with roughness.
4. [fig/section_health.png](fig/section_health.png): 23 of 51 section runs are flagged. Each has a mean
   time step 1.9–9.6 times shorter than the median healthy run with the same mesh and maxCo, and at
   least one further symptom (negative mean drag in 9; Cd_std > |Cd_mean|, |Cl| > 3 or a time-mean
   maximum y+ above 2 in the others).
5. [fig/rotor_cp_lambda_U23.png](fig/rotor_cp_lambda_U23.png): rotor C_P against λ at 23 m/s for both
   hypotheses and senses, with the rig's Plain data.
6. [fig/rotor_lambda_vs_U.png](fig/rotor_lambda_vs_U.png): CFD zero-torque λ against the rig's λ
   landmarks: above the rig's light-load λ at 10.2 m/s, at it at 23 m/s, 0.051 below it at 38 m/s.

## Established and preliminary

- **Established** (computed, within 2D URANS): which 23 section runs are flagged (the cause is
  inferred); the two α-0 flow states; maxCo 5 is not time-step independent on the low-Re section
  meshes; the sign of the rough-wall-function effects; the rotor's sign pattern at 23 m/s, except B
  in its drag-rule sense; the noise floor of the present runs.
- **Indicative:** the texture's +13.7 % at α 180 (SST); the time step as the trigger of the α-0 state;
  the zero-torque λ agreement at 23 m/s and shortfall at 38 m/s; the smooth convex-side drag (Cd
  1.48–1.67, 21–37 % above the shell value); the drag-ratio and leverage arguments from the
  quasi-steady model.
- **Unresolved:** which α-0 state is physical; any transition effect of the texture; the
  Reynolds-number and Tu dependence of the section; the starting direction of hypothesis B.

## Bearing on the wind-tunnel gains

- **No support for a turbulent-wall mechanism.** Every resolved roughness change of the drag
  difference has the opposite sign to the measured gains (computed sign; the link to power is
  inferred).
- **A second sign conflict.** The quasi-steady model predicts that roughness lowers the zero-torque
  λ, from 0.158 to 0.129 at Ks 400 µm (inferred). The rig instead turned faster at light load: +6.6 %
  [+5.1, +8.1] (FS 0.10) and +9.1 % [+7.6, +10.6] (FS 0.20) (measured; geometric mean over 12.4–38 m/s,
  Tukey 95 %). The report notes that less resisting torque (mounting, balance) could also cause this.
- **Transition not yet tested.** Stage 1 has no healthy LM run at α 75–255°. The only LM runs at
  α 180 without corruption symptoms are four 80-c/U texture-mesh runs at 23 m/s, and their noise
  exceeds the change of about 2 % that would be needed.
- **The measured speed pattern is consistent with the prediction but does not establish it**
  (measured; report). Power rose most steeply at 22 m/s (FS 0.10) and 20 m/s (FS 0.20), below both
  Plain runs (24–26 m/s); FS 0.05 (22–24 m/s) overlaps Plain. But set points are 2.1 m/s apart, the
  two Plain runs an hour apart already differ by one step (26.2, 24.1 m/s), and across the eight runs
  this speed never rose with run order, which followed thickness. The 7 Oct prediction was written
  after these data; each level is also one print and one mounting, and Plain has coarser layers.
- **Open alternatives:** transition on the 3D blade; 3D or rotating-flow effects; a change of wake
  state; print, mounting or run-order effects.

## Next steps

1. **Rig.** Record the rotor assembly and rotation sense (the CFD predicts the curled tip leads if
   the arms sit on the concave face); a wind-off coast-down for bearing friction; the test-section
   size and Tu.
2. **Blade-section test.** Printed Plain and FS sections on a load cell or with pressure taps
   (pressure drag is at least 98.5 % of Cd in every healthy smooth-section run). Cd at α 0 and 180
   shows which α-0 state, if either, matches the real blade, and the drag ratio (the rig needs about
   1.9). Accelerometer sampling at 810 Hz or more covers every shedding frequency of the healthy runs
   scaled to 38 m/s (the highest, edge-on, exists only at maxCo 5); between α 75 and 255° only 90 and
   180° have healthy runs.
3. **FS 0.40 / FS 0.80 round.** Add a matched Plain at 0.1 mm layers and repeats of FS 0.10 and
   FS 0.20 in the same job; two prints per level; interleaved run order; remounting. This tests
   whether the onset speed falls and the gain levels off. The current CFD methods cannot represent
   these two textures.
4. **CFD.** Re-run the 23 flagged cases at maxCo 2.5 (estimated 4.5–7.3 h each for SST and roughly
   4–11 h for the 20 LM cases, on Unity) and check maxCo 1.25; repeat the α-0 medium maxCo-5 case on
   Unity to separate time step from machine. Compare LM against SST at maxCo 2.5 at α 150–210° over
   10.2–38 m/s (the main CFD test of the transition idea, within LM's limits). Run longer
   smooth-texture cases to resolve the +18.6 % difference, LM texture runs at 18.8–25.2 m/s, a
   maxCo-2.5 check of the α-180 texture runs, and a rotor mesh check.

## Limits

2D URANS forces spanwise-coherent shedding and usually overstates drag, so results are read as
changes, and even changes can depend on the flow state (the α-0 wall-function effect exists only in
the high-drag state). There are no tunnel walls (the rig data are not blockage-corrected either). LM
is calibrated for attached boundary layers and transitioned early in the project's T3A check; Tu and
length scale are assumed. Rough wall functions are marginal on a 48 mm blade (blade-mean y+ 17–49)
and contain no transition. The texture is the nominal slicer displacement as 2D spanwise ridges,
which overstate tripping against the printed 3D texture (measured Ra 2–8 times smaller). maxCo 2.5
itself is untested (no maxCo-1.25 run), and the texture and the α-90/180 wall-function runs have no
time-step check. The rotor is a 2D slice with prescribed rotation and no arms, hub, end plates or tip
losses, run on one mesh, fully turbulent, with the assembly inferred, so its power levels are not
compared with the rig's. The shell values (2.3, 1.2) are for a thin 180° shell (`cfd/PLAN.md`, not
re-checked), not this blade.
