# Rig records: next tunnel visit

22 Oct 2026 · about 2 h with a helper (estimate). Print with the record table in
`cfd/MEASUREMENTS_NEEDED.md` §5 ("row" below) and write values there. Mount the Plain rotor first.

**Safety.** ☐ Measure with the fan stopped (keypad in LOC, E-stop pressed). ☐ The one fan run
(item 2) keeps the order: load ON at 10 mA → wind up → wind down → load OFF after the fan stops;
nobody in the section or diffuser. ☐ Before it and on leaving: rotor seated, nothing loose in the
section; mark blades with a marker, not tape. ☐ Magnet firmly glued (let new glue set first).
☐ No people in photos (public repo).

**Kit:** phone, 5 m tape, 300 mm rule, calipers, plumb line, marker, kitchen scale, T. Kang's
tachometer DAQ (1 Oct set-up). **Saving:** photos as `cfd/inputs/photos/YYYYMMDD_<code>.jpg` (rule
in frame, camera square); values into `cfd/inputs/rig_geometry.json` (§5 JSON block).

**1 · How the blades attach to the arms ☐**
- *Why:* the rotor CFD assumes the arm bolts to the cup (concave) face, from the CAD; if not, redo it.
- *How:* name the blades B1–B3 (B1: magnet); dot tip A (end of the long leg) and tip B (end of the
  curl) on the end faces. Photos **R1** (from above, rule across) and **R4** (arm joint, both
  sides). Note the face the arm touches, bolt direction, screw size, and whether the near end
  (nearest hole 110.0 mm from it, against 125.2 mm from the far end) is up. Tip A to the next tip A,
  3 pairs (CAD, bolts radial: 147.3 mm with the arm on the concave face, 217.5 mm on the convex).
- *Save:* R1, R4; rows 1.4, 1.5, 1.8, 1.10.

**2 · Which way the rotor turns, seen from above ☐**
- *Why:* the rotor CFD assumes the curled tip leads (the only case shown to self-start); if not,
  redo it.
- *How:* fan 500 rpm (10.2 m/s) for 20 s (E-stop released, keypad in REM, this run only; then LOC
  and E-stop again), filmed in slow motion through a window. Near-side blades moving to your
  **right = CCW** from above, **left = CW**. Mark wind and rotation on a print of R1; rows 1.2
  (leading tip) and 1.3 (on the blade moving downwind, the face or edge the wind meets) follow.
- *Save:* a still, or the marked R1, as `YYYYMMDD_rotation.jpg` (video off the repo); rows 1.1–1.3.

**3 · Test section ☐**
- *Why:* sets the blockage (a correction above about 5 %), the walls in the CFD and the balance size.
- *How:* type (closed walls, open jet, slotted); doors, windows, holes where a balance could mount.
  Inside width and height at entrance, rotor axis and exit (3 readings each, ±2 mm); length,
  contraction exit to diffuser (±10 mm); plumb line from the hub centre to entrance, exit and side
  walls (±5 mm); floor to blade bottom, blade top to ceiling. Photos **S1** (from the entrance, tape
  across), **S2** (side view).
- *Save:* S1, S2; rows 2.1–2.4 and 1.17.

**4 · Wind-off coast-down, Plain rotor ☐**
- *Why:* the friction turns the light-load speed from a bound on the CFD's zero-torque λ into an
  estimate.
- *How:* fan stopped, load OFF (no current, as at light load). Record the tachometer; spin the rotor
  by hand, let it stop; three spins, clock times noted. Use the pulses, not the generator voltage
  (capacitor-held); no DAQ: film at 240 fps. Optional: item 2's stop, if the DAQ was recording;
  only the part after the fan reads 0 rpm and the load is OFF counts. Inertia: weigh the rotor and
  a spare blade; photo **R2**.
- *Save:* DAQ files as recorded in `cfd/inputs/coastdown/` (gzip if large), with a `README.md`:
  date, rotor, load state, how spun, clock times, sampling rate, masses.

**If time allows.** ☐ **S3** contraction, honeycomb, screens; **S4** fan: they narrow the likely
turbulence intensity (rows 2.6–2.8). ☐ **S5**, **S6** obstructions in the flow, size and position
(row 2.9). ☐ Rotor out: socket and spigot diameters (±0.02 mm), engagement length, **R5**: the
clearance sets the wobble (row 1.14).
