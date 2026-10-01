# At the rig — Tue 1 Sept 2026

Print this. Ordered so that **nothing has to be done twice**.

> **The one sequencing decision that matters:** the reed fix and the node
> offset both happen at the bench, with no wind, and both change what every
> later sweep *records*. Do them first. A sweep run before the reed works has
> no rotor speed in it and cannot be repaired afterwards — that is exactly why
> Ra 20 and Ra 80 both need re-running now.

---

## Before you touch anything

☐ **Test section clear.** Anyone nearby told.
☐ **Hand on the E-stop** for anything that turns.
☐ Load ON before wind UP. Wind DOWN before load OFF. Every time.

### ⚠️ First landmine of the day

`data/tunnel.json` → `transport.port` currently reads **`/dev/cu.usbmodem1401`,
which is the tunnel node, not the PMC.** It was pointed there for node testing
on the 19th. Plug the PMC in and fix it before anything else:

```bash
ls /dev/cu.usbmodem*                 # both boards, lowest number is usually first plugged
python src/run.py status             # must answer from the DRIVE
python src/tunnel_node.py id         # must answer 'tunnel-node'
```

`status` returning garbage or hanging means the port is still pointed at the
node. Nothing downstream will work and the failure will not say so clearly —
the node answers serial writes with `ERR unknown command`, not silence, so it
looks like a live link that is merely confused.

**Fix it by editing `data/tunnel.json`, and set BOTH keys:**

```jsonc
"transport":   { "port": "/dev/cu.usbmodemXXXX" },   // the PMC
"tunnel_node": { "port": "/dev/cu.usbmodemYYYY" }    // the node
```

Do **not** just pass `--port` on every command instead. `tunnel_node`
autodetects by *excluding* `transport.port` — so if that key is left pointing
at the node, the node excludes itself and is never found, however many
`--port` flags you type at `run.py`. Naming both ports removes the guessing
entirely.

---

# Bench work — no wind needed (~55 min)

## 0 · Verify par 5310 / 5311 on the keypad ⏱ 3 min ⚠️ NEW

**Read these two off the drive keypad and write them down.**

| par | must read | what it is |
|---|---|---|
| **5310** | **103** | OUTPUT FREQ → Modbus actual 1 |
| **5311** | **104** | CURRENT → Modbus actual 2 |

**Why this is now step zero.** These decide what `fan_rpm_actual` *means*, and
they are **not among the 383 parameters the profile captures** — so nothing in
this repo restores them and they are whatever the drive happens to hold.

That is not hypothetical, it already happened:

| run | slip below setpoint | distinct values |
|---|---|---|
| `v1_Ra20` | −4 to −21 rpm | **10** — a real measurement |
| `v1_Ra80` | 0 to +1 rpm | **2** — the setpoint echoed back |

Same code, same rig, two different meanings. It moves the wind column by 1.2%,
which is **4.6% in power** at P ∝ v^3.77 — a third of the entire +13.73% Ra
result. If 5310 has drifted again, today's blade is not comparable to either
banked run and you will not find that out from the numbers.

☐ If **5310 ≠ 103**, set it to 103 before sweeping, and note that Ra 80's
  wind column was recorded under a different convention.

Every sweep from now on records this in its own header
(`# drive_actual_signals,5310=…;5311=…`) and flags it when it is not 103, so
this becomes answerable later instead of forensic.

---

## 1 · Node temperature offset ⏱ 5 min

The node reads **42.5 °C** sitting on the bench in a room that is nowhere near
that. The LPS22HB is on a powered board and self-heats about +20 °C.

**Why this is not cosmetic:** ρ = P/RT, and Cp goes as 1/ρ. A 20 °C error is
**6.5% in every Cp you will ever compute** — half the size of the entire
Ra 20-vs-Ra 80 result. It biases every blade the same way, so it will never
show up as an inconsistency. It will just be wrong.

☐ Put a reference thermometer next to the node. Phone weather is not one.
☐ Read the true room temperature, then:

```bash
python src/tunnel_node.py calibrate 21.5      # ← your actual reading
```

Expect roughly:

```
  board reads    42.49 °C  (uncorrected)
  you say        21.50 °C
  offset        -20.99 °C  — recorded in data/tunnel.json
  now reads      21.50 °C

  density now 1.2018 kg/m³, -0.2% vs standard
```

☐ Confirm the offset landed in `data/tunnel.json` under `tunnel_node`.

**The firmware forgets this on every reboot, and it reboots whenever a host
opens the port** — so it is stored host-side and `tunnel_node.connect()`
re-applies it every session. You set it once, today, and never again. If you
had only typed `OFFSET -21` at the serial monitor it would have been gone by
the next sweep, silently.

☐ Sanity check the sign: if the offset is bigger than ±30 °C the tool warns
  you, and it is almost certainly the reference reading that is wrong.

---

## 2 · Reed bounce ⛔ this gates Cp ⏱ 20 min, not 40

**Try the software knob before the soldering iron.** The firmware already has
a runtime debounce, `RPMGAP`, in microseconds. No reflash, no parts, instant:

```bash
python src/run.py raw "RPMGAP 5500"
python src/run.py raw "RPMZERO"
#  turn the rotor EXACTLY 10 revolutions by hand, steadily
python src/run.py raw "RPM?"          # the pulse field must read 10
```

The reed rings **3–5 ms** per contact and the default gap is 5000 µs — right
on the edge, so the tail of a 5 ms ring still lands outside the window and
counts as a revolution. 5500 clears it.

### The part worth knowing before you spend the morning on it

A debounce gap has to sit **above the ring** and **below the magnet period**.
Rotor speed at the *lightest* ladder step follows from the one measured anchor
in the firmware (`~66 rev/s true at fan 500`) and V_oc ∝ rotor speed:

| fan | m/s | rev/s | magnet period | gap window (ring ≈ 5 ms) |
|---:|---:|---:|---:|---|
| 500 | 10.2 | 66 | 15.2 ms | 5.0 – 15.2 ms |
| 700 | 14.5 | 130 | 7.7 ms | 5.0 – 7.7 ms |
| **800** | **16.6** | **156** | **6.4 ms** | **5.0 – 6.4 ms — last comfortable one** |
| 900 | 18.8 | 182 | 5.5 ms | 5.0 – 5.5 ms — marginal |
| 1000 | 20.9 | 213 | 4.7 ms | **none — ring ≥ period** |
| 1800 | 38.0 | 554 | 1.8 ms | **none** |

**`RPMGAP 5500` covers fan 500–800** and nothing above ~900 works at the
lightest steps. Not a longer gap, not a bigger capacitor, not a different
filter — at fan 1800 the contacts are still ringing when the next magnet
arrives, and there is nothing there to separate.

> **This table is the runaway case, and it is deliberately the pessimistic
> one.** Under load the rotor slows and the periods lengthen, so more wind
> speeds may work than four. By **how much** it slows is *not known* — rotor
> speed has never been measured on this rig, which is the entire problem this
> sensor exists to solve. An earlier version of this page assumed 45% droop
> and promised 8 of 14; that number had nothing behind it. Trying to derive
> the droop from the banked sweeps gives ω/ω_runaway above 1.0 at five wind
> speeds, which is impossible, so the method is invalid rather than merely
> imprecise. Take four as the floor and let the run tell you the rest.

So: **do not spend the day chasing capacitor values.** ☐ **Order a
Hall-effect sensor today** — the VJ12-D10K is rated 20 Hz on its own
packaging and the top of this range needs **554**. That is a 28× shortfall,
not a tuning problem.

☐ **Expect at least the bottom 4 wind speeds** to carry usable rotor speed,
  possibly more. That is a real partial result: it validates the whole chain
  end to end and gives a genuine Cp(λ) over 10–17 m/s.

☐ **check_rotor should confirm this and name the break.** Predicted: K
  constant at the bottom of the range, then **K RISES** (missing counts)
  somewhere between fan 900 and 1300. If the break lands far from there, the
  66 rev/s anchor is wrong and this whole table moves with it.

### ⚠️ The 10-turn count is the ONLY thing that fixes the scale

`check_rotor` tests whether K is **constant**. It cannot tell you whether K is
**right**. If the debounce settles at exactly two counts per pass, rotor speed
reads 2× high at every wind speed, K comes out constant at half its true
value, and the check goes green — while every λ you report is doubled.

Nothing in the data can catch that. Only the hand count can. Do it, and do it
after any `RPMGAP` change.

### If the reed does NOT get fixed today

Everything below still runs and is still worth the tunnel time. You get
**P_max(v)**, which is what both banked results already are. You do not get
**Cp(λ)**. Do not let a failed reed cancel the day.

---

# Tunnel work ⏱ ~15 min per sweep

Each sweep is ~10 min of continuous tunnel time plus mount and settle. Budget
**15 min wall clock each**, and mount time on top for a blade change.

## 3 · `v1_Ra20_repeat` — the error bar that does not exist yet

**Do this before the new blade.** Every number in this project comes from **one
mounting of each rotor**. Without a repeat you cannot separate a roughness
effect from a remounting effect.

☐ **Dismount and remount the Ra 20 rotor.** The remount is the entire point —
  re-running without touching it measures nothing.

```bash
python src/blade_sweep.py --blade v1_Ra20_repeat \
       --notes "PETG, 0.2mm layer, Ra 20 — remount repeat, rotor rpm live" \
       --step-amps 0.02 --dwell 1.0
```

☐ Fingerprint must print **`94bed28333f7`**. If it does not, stop — something
  changed the protocol and the run is not comparable to anything.

```bash
python src/compare_blades.py v1_Ra20 v1_Ra20_repeat
```

**Whatever that returns is your error bar.** Concretely:

| repeat differs by | then |
|---|---|
| **< 3%** | the +13.73% Ra result is comfortably real — quote it |
| **3–7%** | still real, but the CI must widen to include it |
| **> 10%** | ⚠️ mounting dominates roughness. The Ra result is not yet a result, and every future blade needs two mountings |

That last row is the one worth being honest about in advance, so it is not a
disappointment if it happens.

## 4 · The new blade — Ra 10 or Ra 40

☐ **Before it goes in the tunnel**, write down from the slicer: fuzzy-skin
  setting, layer height, **nozzle diameter**, material, print orientation.
  Ra 80's notes say "0.2 mm nozzle". If this one used a different nozzle then
  nozzle and roughness both changed and the comparison is not clean — and you
  cannot recover that fact a week later.

```bash
python src/blade_sweep.py --blade v1_Ra10 \
       --notes "PETG, 0.2mm layer, 0.4mm nozzle, Ra 10 — fuzzy skin off" \
       --step-amps 0.02 --dwell 1.0
```

☐ Fingerprint **`94bed28333f7`** again.

☐ Then the three-point picture:

```bash
python src/compare_blades.py v1_Ra20 v1_Ra10      # two at a time —
python src/compare_blades.py v1_Ra20 v1_Ra80      # it takes exactly two
```

Baseline first. Ra 20 is the baseline in both, so the two percentages share a
reference and can be read against each other.

**What to look for:** with Ra 10, 20 and 80 you have three points on a
roughness axis for the first time, and the *shape* is the finding. Monotonic
rising says roughness helps across the range. A peak in the middle says there
is an optimum. Ra 10 ≈ Ra 20 with only Ra 80 lifted says the effect has a
threshold. All three are publishable; a two-point line was not.

## 5 · Re-run `v1_Ra80` — only if the reed works ⏱ 15 min

☐ Skip this entirely if step 2 failed.

**Why re-run something already measured:** neither banked run carries rotor
speed. `sweep_v1_Ra20_summary.csv` has 12 columns, `sweep_v1_Ra80_summary.csv`
has 14, and **neither has `turbine_rpm`** — verified, not assumed. Cp(λ) needs
rotor speed at each point, so it cannot be computed from either file no matter
what analysis you write. Re-running is the only path.

☐ Ra 20 is already covered by the repeat in step 3, so Ra 80 is the only
  banked run that still needs it.

```bash
python src/blade_sweep.py --blade v1_Ra80_rpm \
       --notes "PETG, 0.2mm layer, Ra 80 — repeat with rotor rpm" \
       --step-amps 0.02 --dwell 1.0
```

☐ One more reason: `sweep_v1_Ra20_points.csv` **has no `t_unix` column** — it
  predates the timestamping. Node ambient and rotor windows cannot be aligned
  to it by time at all. New runs carry both.

## 6 · The payoff — Cp(λ), if the reed came good

This is the only reason the reed matters. Cp(λ) is the curve that makes the
work comparable to published rotors; P_max(v) is specific to this generator.

```bash
python src/cp_lambda.py --sweep logs/sweep_v1_Ra20_repeat_points.csv \
       --radius 0.1016 --rotor vawt --height 0.2451 \
       --temp 21.5 --pressure 101819
```

☐ **Swept area is 2·R·H = 0.0498 m²**, not πR². `--rotor vawt --height` gets
  this right; leaving `--height` off does not. A VAWT sweeps a *cylinder*.
☐ **Pass `--temp` and `--pressure` from the node**, now that it is calibrated —
  `python src/tunnel_node.py read`. Default ρ is 1.204; the room will not be.
☐ **Expect Cp_elec around 0.001–0.0024** — that is **0.10–0.24%**, and it is
  what `docs/09_results.md` already records for this rig, roughly 100× below a
  working H-rotor. Do not expect a textbook 0.05–0.15: an earlier version of
  this page said exactly that, and against the real ~0.002 an operator would
  read a 25–75× shortfall and go hunting a swept-area or rotor-speed bug that
  is not there.

  The gap is real but it is not aerodynamic. Peak power sits far out on the
  limb of Cp(λ) where Cp → 0 by construction, and this is *electrical* Cp —
  measured after the generator and the rectifier, so it carries η_gen × η_rect
  as well. **Anything above 0.05 is the surprise worth chasing**, not anything
  below it.
☐ **λ at the peak is the headline number.** An H-rotor peaks around λ = 2–3.
  A peak at λ < 1 or > 6 means the rotor-speed scale is wrong, not that the
  rotor is unusual — and remember `check_rotor` cannot see a constant scale
  error, so the 10-turn hand count is what settles it.

`cp_lambda.py` reads `turbine_rpm` directly — that name was added today, and
before it the tool would have silently ignored the sweep's own rotor column
and fallen back to `--assume-lambda`.

---

# While the cover is off

☐ **Ohm the generator winding**, phase-to-phase, **cold and again hot**.
  `R_int` is fitted from the curve and has never been measured, yet it gates
  every derived quantity — `P_max = V_oc²/4R_int` is the whole result. The fit
  says 88.4 Ω at low wind falling to 36.5 Ω at high. A winding does not change
  resistance by 2.4× with load, so most of that swing is **not** the winding,
  and measuring it cold tells you how much.
☐ **VSense at the rectifier output**, not the load's binding posts. Otherwise
  the wiring and the sense IC sit *inside* every power figure you report.
☐ **Air temperature and pressure** from the node at the start and end of the
  session — `python src/tunnel_node.py read`. If the room drifts 3 °C over the
  day that is 1% in ρ between the first and last blade.

---

## Order of operations, condensed

```
  PMC in → set BOTH ports in tunnel.json → run.py status answers
     ↓
  read par 5310 / 5311 on the keypad   3 min  ← must be 103 / 104
     ↓
  node calibrate 21.5              5 min   ← never has to be done again
     ↓
  RPMGAP 5500 → RPM? reads 10      20 min  ← software knob, no parts
     ↓                                        (gates Cp only; order the
                                               Hall sensor either way)
     ↓
  v1_Ra20_repeat  (REMOUNT first)  15 min  ← the error bar
     ↓
  v1_Ra10 or Ra40                  25 min  ← the new science
     ↓
  v1_Ra80_rpm       if reed works  15 min  ← retrofits Cp onto Ra 80
```

Bench first, then tunnel. If the day gets cut short, the repeat run is worth
more than the new blade — a third roughness point with no error bar on any of
them is weaker than two points with one.

---

## Known-good state

| | |
|---|---|
| PMC firmware | **5.7** — `RD/WR`, rotor rpm on ENC0 index (Z0), `RPMGAP`, `RPMZERO` |
| Drive profile | `data/profiles/windturbine_rs485.json`, 383 params, 0 differ |
| Protocol | `94bed28333f7` — Ra 20 and Ra 80 both on it |
| Result | **Ra 80 +13.73%**, 95% CI [+11.21, +16.26], higher at all 14 points |
| Comparison basis | raw-vs-raw. Ra 20 has no fit column, so `compare_blades` drops both to `p_max_raw_w` — verified, not assumed |
| Tests | 210 passing |

**Do not repeat:** 9904 = VECTOR:SPEED · 2202/2203 = 6.0 s · the 10× reference
bug is fixed · rotor is a VAWT, R = 0.1016 m, span 245 mm, **swept area 2RH**,
not πR².

---

## If something is wrong

| Symptom | Look at |
|---|---|
| `run.py status` returns garbage | `transport.port` is pointed at the node — see the top of this page |
| Cannot reach the drive | `docs/04_troubleshooting.md` |
| Cannot find the Chroma | `python src/probe_load.py` |
| Node not found | it is excluded from autodetect if it equals `transport.port` — pass `--port` explicitly |
| `No DFU capable USB device` when flashing | double-tap the Portenta's RESET |
| Drive faults right after a PMC flash | expected — DFU silences Modbus past par 3019. Clear at the keypad |
| Fan stops mid-run for no reason | the PMC host watchdog — something must talk to it every few seconds |
| Every point reads 0.000 V | no wind, or the rotor is not turning — check `fan_rpm_actual` |
| Peak power looks wrong | `limited_by` column first, then the fingerprint |
| Speeds off by exactly 10× | somebody reintroduced an Hz↔rpm conversion |

**Everything on this rig that has ever gone wrong produced plausible numbers
first.** If something looks fine, that is not evidence.
