# Today — 26 Aug · load connected 14:30

Print this. Ordered so nothing waits on anything later.

**The whole session hinges on two things: the slicer recipe written down, and
cut-in measured on both rotors before any sweep runs.** Everything else is
recoverable afterwards; those two are not.

---

## Before 14:30 — desk, no rig needed

☐ **Write down the Ra 80 print recipe.** ⛔ **BLOCKING**
  Fuzzy skin on/off + amplitude · layer height · nozzle · orientation ·
  temps · speeds. Into `blades/v1.json` and into `--notes`.
  → Without it the experiment has no independent variable. You will have two
    curves and no defensible statement about what differs between them.

☐ **Make the fan-rpm cable** — twisted pair, ferrules both ends.
  `PMC O0` → DAQ AI+ · `PMC GND` → DAQ **analog** ground.
  Route away from the motor leads.

☐ ~~Flash firmware v4~~ — **not today.** Do it *after* the sweeps.
  The last reflash tripped the drive on `SERIAL 1 ERR`. Reflashing the
  controller 30 minutes before a timed experiment trades a real risk for a
  measurement you can take next week.

---

## 14:30 — at the rig, before any sweep  (~30 min)

☐ **Test section clear. Hand on the E-stop.**
☐ Load ON before wind UP. Wind DOWN before load OFF. Every time.

☐ **Cut-in speed, BOTH rotors.** ⛔ **BLOCKING**
  Ramp the fan from zero in ~50 rpm steps. Record breakaway and sustain.
  → **cut-in Ra 20 = ______ m/s     Ra 80 = ______ m/s**
  → **If they differ by more than 0.1 m/s the comparison is dead** — a 0.25
    m/s difference alone manufactures a 3.1σ "result". Roughness cannot change
    cut-in; bearings, balance and preset pitch can. Five minutes, two numbers.

☐ **Caliper both rotors.** Wall at 3 stations (baseline **1.79 mm**), edge
  width, blade mass (~39 g each). Moved > 2 %? You changed the part, not the
  finish.

☐ **Which DAQ channel is the proximity sensor, and its pulses per rev?**
  → **channel ____   PPR ____**   (1 per rev? per blade? per magnet?)
  → Wrong PPR is a clean integer error in λ and it will not look wrong.

☐ **Air temperature ____ °C   ·   pressure ____**
  10 °C is 3.4 % in power — the same size as the effect you are hunting.

☐ **Photos:** each blade root at the mount against a reference edge · both
  surfaces at grazing light with a scale · each rotor from directly above.

---

## ~15:00 — the sweep  (~60 min)

**Run ABBA, remounting between each:**

```
Ra20  →  Ra80  →  Ra80  →  Ra20
```

```bash
python src/blade_sweep.py --blade v1_Ra20 --notes "<recipe>" --step-amps 0.02 --dwell 1.0
python src/blade_sweep.py --blade v1_Ra80 --notes "<recipe>" --step-amps 0.02 --dwell 1.0
```

☐ Fingerprint reads **`94bed28333f7`** on all four. Different = not comparable.
☐ All 14 points say `power-rolloff`.
☐ **DAQ recording throughout.**

**Why ABBA and not A then B:** generator warm-up alone produces Δn = −0.063 —
"behind at high wind, exponent drops" — from zero aerodynamics. Block ordering
aliases that straight into the answer with the sign you would want to believe.
ABBA cancels it.

The repeated Ra 20 gives you **the first mount-to-mount error bar this rig has
ever had.**

> If |Ra20(1) − Ra20(2)| ≥ |Ra20 − Ra80| the experiment is null **and you have
> proven it** — a real engineering answer: print finish can be chosen for cost.

**Short on time?** Drop to **A-B-A** (3 sweeps). You still get the repeat and
the error bar. Never drop to A-B.

### What to expect

**No resolvable difference is the most likely outcome (~55 %).** Expect n in
**3.65–3.90** — the same range re-running Ra 20 alone would give.

Do **not** expect a crossover, and do not expect n to fall toward 3.0. The
blade is a thin cambered plate with square edges, so separation is pinned by
geometry; Braslow–Knox needs Re_k ≈ 600 to trip and Ra 80 gives 16–120.

**Report the level, not the exponent.** A uniform 5 % power change gives
Δn = 0.000 exactly.

---

## While the cover is off

☐ **VSense to the rectifier output**, not the load's binding posts — otherwise
  the wiring and sense IC sit *inside* every measurement.
☐ **Ohm the generator winding** phase-to-phase, cold and hot. R_int is
  inferred from a fit and has never been measured, yet it gates everything.
☐ **Count the generator magnet poles** — 30 s, cross-checks the proximity
  channel.
☐ Drop the gain on DAQ ch3/4/6 — at 98 % of range they will clip.
☐ Trace the D-sub on the Chroma's back panel.

---

## After the sweeps — only if the rig is free

☐ Flash `firmware/acs550_pmc_v4/`, then its 5-step commissioning check.
  **Step 5 matters most:** pull the PMC USB, the line must fall to 0.00 V.
  It is the only proof the invalid path works.

---

## Bring home

- [ ] Cut-in and breakaway for both rotors
- [ ] The Ra 80 recipe, written down
- [ ] Proximity channel + PPR · pole count · winding resistance
- [ ] Air temp and pressure
- [ ] Four sweep CSVs, fingerprints matching
- [ ] Photos

**Everything on this rig that has ever gone wrong produced plausible numbers
first.** If something looks fine, that is not evidence.
