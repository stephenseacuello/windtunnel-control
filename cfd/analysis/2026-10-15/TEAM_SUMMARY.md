# CFD of the fuzzy-skin VAWT blade: results of all 263 cases

19 October 2026 · S. Eacuello · for Profs Sodhi, Jahangiri and Jeong, and T. Kang · revises the
[13 Oct summary](../2026-10-13/TEAM_SUMMARY.md)

**Scope.** 263 finished 2D URANS simulations (OpenFOAM v2606) of the v1 blade section and the
3-blade rotor: the 150 of 13 Oct and 113 run since (table below). Every CFD number is computed from
the result tables and force histories and was recomputed by independent scripts (this summary's:
`src/team_summary_check.py`); measured numbers come from the 1 Oct report. Claims carry provenance
and strength (established, indicative, unresolved) as on 13 Oct; "not resolved" bounds a difference
and does not mean "equal". A section change is resolved when it exceeds its *noise* (the sum of the
two runs' drifts over the averaging window), with and without intermittent force jumps; rotor values
carry ±2u, twice the averaging uncertainty. A *flagged* run has corrupted numbers; a *healthy* run
is not flagged, which does not mean converged. Details: [UPDATE.md](UPDATE.md); the first 150 cases:
[RESULTS.md](../2026-10-13/RESULTS.md); files and reruns: [README.md](README.md).

## Headline results

1. **In the 2D rotor, rough blades raise the torque at Ks 400 µm** (computed; indicative).
   - Assembly A, curled tip leading, 23 m/s, SST with a rough wall function, last 45 of 50
     revolutions averaged. Against Ks 0 with the same wall function, Ks 400 µm raises C_Q by
     +0.0051 ± 0.0028 at λ 0.10 (+27 %) and +0.0058 ± 0.0028 at λ 0.12 (+38 %). Ks 100 µm, near
     FS 0.20's scan height under Ks = k, gives no resolved change (+0.0014 ± 0.0027, −0.0029 ±
     0.0032); at λ 0.12 its interval ends at +0.0002, below every rig-implied change (≥ +0.0020).
   - The sign is that of the measured gains (FS 0.10, FS 0.20: +12.8 % [+10.1, +15.5] and +16.2 %
     [+13.5, +19.0] over 10.2–38 m/s, Tukey 95 %; +21.2 % and +36.2 % at 23 m/s; measured); the size
     is 2.0–2.8 times the change these imply over 10.2–38 m/s and 0.9–1.7 times that at 23 m/s
     (mapping assumed).
   - The gain comes from the advancing blade while edge-on (blade azimuth θ 60–120°, moving downwind,
     tip A first): its sector adds +0.0092 and +0.0085, and its streamwise force at θ 80–100° rises
     48–50 % (section drag at α 90: +45 % with the same wall function). The returning edge-on sector
     (θ 240–300°) brakes more (−0.0048 ± 0.0022, −0.0024 ± 0.0021), though its streamwise force at
     θ 260–280° does not change resolvably.
   - Mesh differences of C_Q (up to 0.019) exceed the effect, and the 13 Oct time-step check (maxCo 2,
     λ 0.15) cannot exclude an error of the same size; both are assumed, not shown, to cancel between
     rough and smooth runs.
2. **The section results stand, but the model that turned them into a power loss does not describe
   this rotor** (section signs computed, established within these 2D models; rotor link inferred).
   - Of 52 fair section comparisons (wall functions and texture; SST and LM; two time steps), all 21
     resolved ones have the sign of a loss on the two-position (α 0/180 drag) model; none of the 8
     with the opposite sign is resolved. With fair pairs, Ks 400 µm lowers the concave-minus-convex
     drag difference by 18.6 % (13 Oct: 19.3 %), and the 0.20 mm texture raises the convex-side drag
     by 13.6 % (SST; sign established) and 8.6 % (LM; indicative).
   - In A, the drag of the upwind blade (θ 0, convex side to the wind) and of the downwind blade
     (θ 180, cup to the wind) acts across their motion: the upwind blade drives through the crosswind
     force, and the returning edge-on blade is the main brake (computed torque budget). The
     two-position model omits the edge-on positions that carry the roughness response, so the 13 Oct
     inference of a power loss is overturned for this 2D rotor at Ks 400 µm (indicative).
3. **Transition test: at 10.2–23 m/s a full trip raises the convex-side drag** (computed; indicative).
   - LM's Cd at α 150–210° lies below SST's in all 10 pairs at 10.2 and 23 m/s (−10.7 to −51.1 %;
     9 resolved, each with force jumps or the flagged runs' solver-residual signature in at least one
     run). At α 180 the gap closes with speed (−20.3, −11.5 and −0.45 % at 10.2, 23 and 38 m/s) and
     is −8.6 % at maxCo 1.25 (23 m/s).
   - A trip changes the α-180 lift more than the drag (|Cl| +81 %, Cd +13.0 % at 23 m/s). As A is
     driven by the crosswind force, the rotor-level sign of a trip is untested (no LM rotor run).
   - The 0.20 mm texture raises LM's convex-side drag by 7.3–8.6 % at 20.9–25.2 m/s but not
     resolvably at 18.8 m/s (+0.04 %, noise 4.3 %): an onset where FS 0.20's measured gain jumps
     (+12.6 ± 11.1 % at 18.8 m/s to +31.5 ± 4.3 % at 20.9 m/s, pointwise 95 %), but with the
     drag-raising sign.
4. **Numerical limits are now measured** (computed; established unless marked).
   - No new run is flagged (0 of 113); all 23 flagged section configurations now have healthy
     maxCo-2.5 runs (22 re-run, one from 13 Oct), but healthy runs can carry intermittent force jumps
     (35 of 102).
   - maxCo 2.5 is not time-step converged at α 180: at maxCo 1.25 the drag falls 17.5 % (SST) and
     14.8 % (LM) and the shedding stops. Whether 1.25 is converged is untested.
   - The α-0 state does not depend on the machine (Unity repeat of the Mac run: Cd 3.1894 against
     3.1905); for SST the time step and the start-up select it (indicative). Both models end in the
     low-drag state at maxCo 1.25, still drifting at 150 c/U.
   - The rotor torque at maxCo 4 changes with the mesh (C_Q 0.0138, 0.0160 and 0.0254 at λ 0.10,
     coarse to fine), confounded with the time step. The 23 m/s zero-torque λ spans 0.127–0.159
     across meshes, so the 13 Oct match with the rig (0.158–0.160) holds on the medium mesh only
     (indicative); at 38 m/s it stays 0.051 below the rig.
5. **Resolution** (computed noise; implied signal estimated). With 45 revolutions, 2u of a
   rough-minus-smooth ΔC_Q is 0.0027–0.0032. The change implied by the gains over 10.2–38 m/s
   (0.0020–0.0026) needs 55–89 averaged revolutions per run (13 Oct: 42–66, from a revolution
   scatter 15 % below the one now measured); that implied by the 23 m/s gains (0.0034–0.0058)
   needs 11–33.

## What was run

| Stage | Cases (13 Oct + new) | New since 13 Oct |
|---|---|---|
| 1. Smooth section | 125 (51 + 74) | 22 of the 23 flagged cases at maxCo 2.5 (the 23rd, SST α 180 at 23 m/s, ran on 13 Oct); maxCo 1.25 at α 0 and 180 (SST, LM); LM against SST at α 150–210° and 10.2/23/38 m/s, LM also at Tu 0.5 and 3 % |
| 2. Roughness on the section | 69 (43 + 26) | Rough-wall sweeps (Ks 0–400 µm) at α 90 and 180, and meshed texture (SST, LM; α 0 and 180), at maxCo 2.5 over 150 c/U; LM texture at α 180 at 18.8–25.2 m/s |
| 3. Rotor (2D, 3 blades) | 69 (56 + 13) | Rough blades (A, 23 m/s, λ 0.10 and 0.12, Ks 0/100/400 µm and smooth, 50 revolutions); coarse and fine meshes at λ 0.10 and 0.15; 38 m/s, λ 0.30 over 16 revolutions |

Also three diagnostic runs: the Mac's α-0 maxCo-5 case repeated on Unity, and two restarts that
exchange the time steps of the two α-0 states. Tu 1 % and a 1 mm length scale are assumed. The
new rotor runs use SST with wall functions at maxCo 4 and assembly hypothesis A with the curled tip
leading, the only combination shown on 13 Oct to deliver power from rest (the assembly is inferred
from the CAD).

## Key figures

1. [fig/rotor_roughness_dCQ.png](fig/rotor_roughness_dCQ.png): 2D rotor torque change with Ks 100
   and 400 µm (±2u), against the change implied by the rig's gains.
2. [fig/rotor_roughness_phase.png](fig/rotor_roughness_phase.png): the Ks-400 torque change by blade
   azimuth; the advancing edge-on blade carries it.
3. [fig/roughness_bottom_line.png](fig/roughness_bottom_line.png): forest plot of 29 of the 52 fair
   section roughness comparisons, including all 8 with the sign the gains need; no resolved change
   lies in that direction.
4. [fig/section_transition_lm_sst.png](fig/section_transition_lm_sst.png): LM against SST at
   α 150–210° and 10.2, 23 and 38 m/s; LM's drag lies below SST's at 10.2–23 m/s.
5. [fig/section_timestep.png](fig/section_timestep.png): Cd, Cl and St against maxCo (5, 2.5, 1.25)
   at α 0 and 180; maxCo 2.5 is not converged at α 180.
6. [fig/rotor_grid.png](fig/rotor_grid.png): rotor C_Q and zero-torque λ on three meshes, against the
   rig's light-load λ at 23 m/s.

## Established and preliminary

- **Established** (computed, within 2D URANS): which runs are flagged (none new); maxCo 2.5 not
  converged at α 180 (medium mesh, 23 m/s); the machine does not select the α-0 state; the signs of
  the rough-wall effects and of the SST texture effect at α 180, which survive halving the time
  step, and the absence of any resolved section change with the sign the gains need; the mesh
  dependence of the rotor torque at maxCo 4; the noise model of the long rotor runs.
- **Indicative:** the rotor torque gain at Ks 400 µm and its edge-on origin; the LM–SST convex-side
  differences and their speed and Tu trends (maxCo 2.5, one mesh); the LM texture onset between 18.8
  and 20.9 m/s; the time step and start-up as selectors of the α-0 state; the zero-torque λ
  comparisons at 23 and 38 m/s; the sizes of the texture effects.
- **Unresolved:** which α-0 state, if either, is physical; whether maxCo 1.25 is converged; any rotor
  effect at Ks 100 µm; the rotor-level sign of a trip; the Ks that represents a printed skin.

## Bearing on the wind-tunnel gains

- **The 13 Oct "no support for a turbulent-wall mechanism" no longer holds; the mechanism is not
  shown either.** A fully turbulent rough wall raises the 2D rotor's torque at Ks 400 µm by 0.9–2.8
  times the change the measured gains imply (computed change, estimated implied change; indicative);
  at Ks 100 µm nothing is resolved, and at λ 0.12 the change stays below the implied one by more
  than 2u. The Ks of a printed skin is assumed: Ks = k gives 84–97 µm for FS 0.20 and about 38 µm
  for Plain, FS 0.05 and FS 0.10 alike, so under it a sand-grain mechanism could not separate FS 0.10
  from Plain; the nominal texture gives 211 µm (FS 0.10) and 422 µm (FS 0.20), an upper estimate.
- **Transition remains open:** at 10.2–23 m/s a trip raises the section's convex-side drag; on the
  rotor its effect is untested.
- **The 13 Oct "second sign conflict" lapses.** The predicted fall of the zero-torque λ (0.158 to
  0.129) is not borne out at λ 0.10–0.12. A gain persisting to zero torque would raise it by about
  0.007–0.011 (inferred, untested), the sign of the rig's faster light-load rotation (+6.6 %
  [+5.1, +8.1] FS 0.10, +9.1 % [+7.6, +10.6] FS 0.20; measured, geometric mean over 12.4–38 m/s,
  Tukey 95 %).
- **Open alternatives:** transition on the 3D printed texture; 3D or rotating-flow effects; print,
  mounting or run-order effects (one print and one mounting per level).

## Next steps

1. **Rig.** Rotor assembly and rotation sense (all rotor CFD assumes A, curled tip leading); a
   wind-off coast-down for bearing friction; test-section size and Tu.
2. **Blade-section test, Plain against FS.** Cd and Cl at α 0, 90 and 180: α 90 carries the rotor's
   roughness response in the CFD, Cl at 180 its drive, Cd at 0 and 180 the α-0 state. An
   accelerometer (≥ 810 Hz) shows whether the convex side sheds (St 0.22, about 107 Hz at 23 m/s,
   at maxCo 2.5) or not (maxCo 1.25).
3. **FS 0.40/0.80 round** with a matched Plain, two prints per level and an interleaved run order,
   as planned on 13 Oct.
4. **Rotor CFD.** Separate mesh and time step, then a Ks 0/400 pair on the fine mesh (55–89
   averaged revolutions), Ks 200 µm and λ ≥ 0.15. An LM rotor case, the only direct test of a trip on
   the rotor, would take roughly 10–20 days on 8 ranks (13 Oct estimate) and needs a decision.
5. **Section CFD.** maxCo 0.625 at α 180; the α-0 maxCo-1.25 runs extended to 300 c/U; the decisive
   transition points at maxCo 1.25; a mesh study at α 180 (the texture mesh's smooth Cd(180) is 39 %
   below the medium mesh's).

## Limits

2D URANS forces spanwise-coherent shedding; results are read as changes, and even changes depend on
the flow state, the mesh and the time step. There are no tunnel walls (the rig data are not
blockage-corrected either). LM is calibrated for attached boundary layers and transitioned early in
the project's T3A check; Tu and length scale are assumed. Rough wall functions sit in the buffer
layer on a 48 mm blade (blade-mean y+ 17–49; Ks/y_P up to 0.92) and contain no transition. The
texture is the nominal slicer displacement as 2D ridges from one seed (measured Ra 2–8 times
smaller). The rotor is a 2D slice with prescribed rotation and no arms, hub, end plates or tip
losses, run fully turbulent at maxCo 4 (time step checked only at λ 0.15) with the assembly
inferred; its mesh differences exceed the roughness effect.
