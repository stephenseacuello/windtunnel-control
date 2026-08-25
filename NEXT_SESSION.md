# Next session at the rig

Print this. Ordered so nothing waits on something later. **~2 hours**, and the
first twenty minutes decide whether the rest of the campaign is Cp or just
watts.

Everything here needs the tunnel. All the desk work is done.

---

## Before you touch anything

☐ **Test section clear.** Anyone nearby told.
☐ **Hand on the E-stop** for anything that turns.
☐ Load ON before wind UP. Wind DOWN before load OFF. Every time.

---

## ✅ Done 25 Aug — do not repeat

- Rotor is a **VAWT** (H-rotor), **R = 4″ = 0.1016 m**, blade height 245 mm,
  swept area **2·R·H = 0.0498 m²** (a cylinder, not a disc)
- **9904 = VECTOR:SPEED**, **2202/2203 = 6.0 s**
- PMC flashed to **3.0 RD/WR**; watchdog proved itself when the drive tripped
  on `SERIAL 1 ERR` during the reflash
- Drive captured: `data/profiles/windturbine_rs485.json`, 383 params, 0 differ
- **The 10× is fixed** — commanded 10 rpm now reads 10 rpm at par 0102

---

## 1 · Rotor speed — mostly already solved

**The DAQ already records rotor rpm from a proximity sensor on the rig.** The
pole count and the Clarke transform were a workaround for a problem that does
not exist. What remains is bookkeeping:

☐ **Confirm which DAQ channel is the proximity sensor**, and its pulses per
  revolution (1 per rev? per blade? per magnet?). Wrong PPR is a clean integer
  error in λ and it will not look wrong.
☐ **Count the generator magnet poles anyway** — 30 s, and it cross-checks the
  proximity channel against the electrical frequency.
☐ Record the DAQ through every sweep tomorrow.

**This is the highest-value item in the session.** Without ω there is no λ and
no Cp, and the rig is currently measuring runaway speed squared through a ~40 Ω
winding — at peak power the rotor sits at ω/ω_runaway ≈ 0.70 rising to 0.94,
i.e. the far limb of Cp(λ) where Cp → 0 by construction. That is why
**Cp_elec is 0.0009–0.0024**, roughly 100× below a working H-rotor.

It also means **a better blade can read as less power**: anything that raises
Cp_max while adding low-α drag lowers λ_runaway, lowers V_oc, and lowers
measured P as the *square*. Two rotors with Cp_max of 5% and 25% would rank
purely by how freely they spin.

Every `sweep_*_points.csv` already holds a full load ramp at all 14 wind
speeds, so **one rotor-speed channel converts the whole archive to Cq(λ)
retroactively** — including tomorrow's Ra 80 run. That channel is worth more
than the Ra 80 sweep itself.

---

## 2 · v1 at Ra 80 — read this before you mount anything

**My earlier prediction was wrong and I have withdrawn it.** A nine-agent
audit refuted it 3/3. Do not expect a crossover, and do not expect the
exponent to fall toward 3.0. What follows replaces it.

### Why it was wrong

The blade is **not an airfoil**. Parsed from the STL: a **1.79 mm** constant
wall, 4% thickness ratio, 42% camber, **183° of turning**, square-cut edges
with no leading-edge radius, and **zero twist**. It is a thin cambered scoop.

- Separation is **pinned by the square edges**, not by boundary-layer state.
- Thin cambered plates are the Reynolds-**insensitive** class (Laitone, *Exp
  Fluids* 23:405, 1997) — the opposite of the airfoil case I argued from.
- The roughness cannot trip the boundary layer anyway. Braslow–Knox needs
  Re_k ≈ 600; Ra 80 gives **16 at 10 m/s and 120 at 38 m/s**. You would need
  ~490 µm.
- **v^3.75 is a generator characteristic, not an aerodynamic one.** V_oc ∝
  v^1.52 and R_int ∝ v^−0.64 (73.6 → 40.1 Ω), every peak sits at the Thévenin
  match, and n = 2a − b = 3.69 against 3.77 measured. There is almost no
  aerodynamic residual left for roughness to move.

**Expect n in 3.65–3.90** — the same range you would get re-running Ra 20
itself. Most likely outcome (~55%) is **no resolvable difference**.

### ☐ Before the tunnel — 20 minutes, and step 3 is blocking

☐ **Write down the Ra 80 slicer recipe.** Fuzzy skin on/off + amplitude, layer
  height, nozzle, orientation, temps, speeds → into `blades/v1.json` and
  `--notes`. **Without this the experiment has no independent variable.**
☐ **Caliper both rotors.** Wall at 3 stations (baseline **1.79 mm**), edge
  width, blade mass (≈39 g each). Moved >2%? You changed the part, not the
  finish.
☐ **Cut-in speed, both rotors.** Ramp from zero in ~50 rpm steps, record
  breakaway. **If they differ by >0.1 m/s the exponent comparison is dead.**
  A 0.25 m/s difference alone fakes a 3.1σ result — and roughness cannot
  change cut-in, bearings and balance can.
☐ **Static breakaway torque**, both rotors — string, pulley, weights.
☐ **Photograph** each blade root at the mount against a reference edge, both
  surfaces at grazing light with a scale, and each rotor from directly above.
☐ **Air temperature and pressure.** 10 °C is 3.4% in P — the same size as the
  effect, and pure level shift.

### ☐ Run ABBA, not A then B

```
Ra20 → Ra80 → Ra80 → Ra20      dismount and remount between each
```

**This is the single most valuable change.** ABBA cancels linear thermal drift
exactly; block ordering aliases it into the answer *with the predicted sign*.
Generator warm-up alone produces Δn = −0.063 — "behind at high wind, exponent
drops" — from zero aerodynamics.

The repeated Ra 20 gives you **the first mount-to-mount error bar this rig has
ever had**. ~4 sweeps × 10 min.

> If |Ra20(1) − Ra20(2)| ≥ |Ra20 − Ra80|, the experiment is null **and you have
> proven it** — which is a real engineering answer: print finish can be chosen
> for cost and speed.

☐ Fingerprint **`94bed28333f7`** on all four.

⚠️ The "0.2%/0.3% repeatability" in `docs/07` is **not this measurement's**.
Those runs carry a different fingerprint. The one near-comparable repeat,
`peak_500.csv`, is **−4.04%** — at exactly the wind speed where I predicted the
crossover.

### ☐ Analyse paired, and report the LEVEL not the exponent

Regress `ln(P_Ra80/P_Ra20)` on `ln v` at matched set points. Wind-calibration
and the rig's structured 6.5% residual are common-mode and cancel in the ratio.

| | Δn detectable | level detectable |
|---|---:|---:|
| paired | 0.019 | 0.75% |
| unpaired | 0.12 | — |

**A uniform 5% power change gives Δn = 0.000.** The exponent is the wrong
statistic. Report *"Ra 80 is X% ± Y% below Ra 20, uniformly"* or *"no resolvable
difference; mount-to-mount reproducibility = Z%"*.

☐ **Ohm the generator winding** phase-to-phase, cold and hot. R_int is
  currently *inferred from a fit and never measured*, yet it gates everything.

---

## 3 · Wiring, while the cover is off

☐ **Make up the fan-rpm → DAQ cable.** *(new — firmware v4 is written and
  compiles)*
  → **Twisted pair, ferrules on both ends.** Route away from the motor leads.
  → `PMC O0` → DAQ AI+ · `PMC GND` → DAQ **analog** ground (not chassis)
  → Scale is **0.5 V + rpm/300**, so 1200 rpm = **4.50 V**. It is recorded in
    `data/tunnel.json`; the DAQ only ever sees volts.
  → **0.00 V means INVALID**, not zero rpm — live zero, so a pulled wire and a
    stopped fan are not the same reading.
  → Flash `firmware/acs550_pmc_v4/`, then run the 5-step commissioning check in
    its README. **Step 5 (pull the USB, line must fall to 0.00 V) is the one
    that matters** — it is the only proof the invalid path works.

☐ **VSense to the rectifier output**, not the load's binding posts.
  → Otherwise the wiring and the series sense IC sit *inside* every
  measurement and each power figure is low by I²R.

☐ **Count the generator magnet poles** — 30 seconds, and see §7.

☐ **Drop the gain on DAQ ch3/4/6.** They sit at 98 % of ADC range and will
  clip.

☐ **Trace the D-sub** already plugged into the Chroma's back panel.
  → If something drives the load through analog programming, that is a second
  controller competing with SCPI.

## 4 · If you get time

☐ **Find `--dwell` empirically.** The simulator has no rotor inertia, so it
  cannot tell you this. Start at 5 s and halve until the reported threshold
  starts moving, then double back.

☐ **One anemometer reading at a known rpm.** Confirms the rpm→velocity half
  against a second instrument. `run.py verify`.

---

## Bring home

- [ ] Which DAQ channel is the proximity sensor, and its pulses/rev
- [ ] Generator pole count, and winding resistance cold + hot
- [ ] Cut-in speed and breakaway torque for BOTH rotors
- [ ] The Ra 80 slicer recipe, written down
- [ ] Air temperature and pressure
- [ ] Photos: generator nameplate, the D-sub cable's other end
- [ ] `data/snapshots/*.json` committed
- [ ] The second blade's sweep CSVs
- [ ] 9904 and 2202
- [ ] Whether ch3/4/6 are still landed

**One rotor-speed channel turns every sweep you already have into Cq(λ)
without another minute of tunnel time.** It is worth more than any single
blade run.

---

## If something is wrong

| Symptom | Look at |
|---|---|
| Cannot reach the drive | `docs/04_troubleshooting.md` |
| Cannot find the Chroma | `docs/06_chroma.md` |
| Fan stops mid-run for no reason | host watchdog — is something ticking the PMC? |
| Every point reads 0.000 V | no wind, or the fan is not turning — check the `fan N rpm` column |
| Peak power looks wrong | `limited_by` column first, then the fingerprint |
| Speeds off by exactly 10× | somebody reintroduced an Hz↔rpm conversion |
| DAQ fan-rpm channel reads 0.00 V | that is INVALID, not zero — PMC, wire or par 0102 |
| DAQ fan-rpm channel looks plausible but wrong | check the scale in `data/tunnel.json` matches the flashed firmware |
| Config lost the load settings | `python src/merge_load_facts.py` |

**Everything on this rig that has ever gone wrong produced plausible numbers
first.** If something looks fine, that is not evidence.
