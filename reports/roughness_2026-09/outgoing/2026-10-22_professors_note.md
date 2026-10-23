# Note to the professors, 22 Oct 2026

Draft, not sent. Replace [RESULTS LINK] before sending.

**To:** Prof. Sodhi, Prof. Jahangiri, Prof. Jeong
**Cc:** Taegu Kang
**Subject:** Fuzzy-skin VAWT blades: CFD results and proposed next tests

---

Dear Professors Sodhi, Jahangiri and Jeong,

The 263 CFD simulations (2D, OpenFOAM) are summarised at [RESULTS LINK]:

1. In the rotor model, a fully turbulent wall with 400 µm sand-grain roughness raises torque at
   23 m/s by 27–38 %, the sign of the measured gains, via the blade moving downwind edge-on
   (indicative); 100 µm, near FS 0.20's measured roughness height, gives no resolved change.
2. On the section, every resolved roughness effect implies a loss if only the cup-facing and
   convex-facing drag is counted (established within the 2D models); that count leaves out the
   edge-on positions of point 1.
3. A full boundary-layer trip raises the section's convex-side drag at 10.2–23 m/s (indicative);
   its rotor effect is untested.
4. In the rotor, mesh differences exceed the roughness effect, and the printed skin's sand-grain
   height is unknown: the simulations do not show the mechanism and need measurements.

Next steps:
- rig records: blade attachment and rotation sense (so far assumed), a coast-down and the
  test-section dimensions;
- a blade-section force test, Plain against FS, on a small load-cell balance: drag and lift with the
  cup, edge or convex side to the wind (Prof. Jahangiri's "airfoil slice" request);
- one print round with one set of print settings, the first of two per level: FS 0.40 and FS 0.80,
  plus new Plain, FS 0.10 and FS 0.20 sets.

Could we meet for 30 minutes next week to agree on these?

Best regards,
Stephen Eacuello

---

Sources (not part of the email), all `cfd/analysis/2026-10-15/TEAM_SUMMARY.md` unless named:
- Point 1: headline 1 (computed; indicative, the gain and its edge-on origin): +27 % at λ 0.10 and
  +38 % at λ 0.12, assembly A, 23 m/s; "measured roughness height" is FS 0.20's scan height,
  k = 84–97 µm (Ks 100 µm is near it under Ks = k); "Unresolved": any rotor effect at Ks 100 µm.
- Point 2: headline 2 (all 21 resolved of the 52 fair section comparisons; section signs
  established within these 2D models; "the two-position model omits the edge-on positions that
  carry the roughness response").
- Point 3: headline 3 ("a full trip"; computed; indicative; "the rotor-level sign of a trip is
  untested").
- Point 4: headline 1 (mesh differences of C_Q, up to 0.019, exceed the effect), "Established and
  preliminary" (the Ks of a printed skin is unresolved) and "Bearing on the wind-tunnel gains"
  (the mechanism is not shown).
- Next steps: "Next steps" 1–3, and `../MEETING_2026-10-07_Jahangiri.md` action items 1, 4 and 5.
  "New" sets, not "reprinted": the round would use one set of settings for all five (see the Cam
  request), which need not be those of the 1 Oct prints. Details:
  `docs/checklists/rig_records_next_visit.md` and `2026-10-22_print_request_cam.md`.
- Body: 242 words (whitespace-separated, greeting and sign-off included).
