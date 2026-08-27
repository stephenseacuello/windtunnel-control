# Next session at the rig

Print this. One page, ordered so nothing waits on anything later.

**One thing blocks the science: the rotor-speed sensor bounces.** Everything
else is measured, banked, or optional.

---

## Before you touch anything

☐ **Test section clear.** Anyone nearby told.
☐ **Hand on the E-stop** for anything that turns.
☐ Load ON before wind UP. Wind DOWN before load OFF. Every time.

---

## 1 · Fix the reed bounce ⛔ blocking

The sensor works. It just counts each magnet pass **2–3 times, variably** —
28 raw counts over 10 hand revolutions. A fixed ratio would be correctable; a
varying one is not, so rotor rpm carries ~±20% scatter against a blade effect
of 13.7%.

☐ **Fit a capacitor from `Z0` to `GND`.** Start **0.1 µF**, then 0.22, then
  0.47. Stop when the test below reads 10.

  ⚠️ **1 µF is probably too slow.** If Z0's pull-up is ~10 kΩ that is a 10 ms
  time constant, and at ~60 rev/s the magnet period is only 15 ms — passes
  would smear together. Fine for hand-spinning, not at speed.

☐ **The 30-second test**, after each value:

```bash
python src/run.py raw "RPMZERO"    # zero the counter
#  turn the rotor EXACTLY 10 revolutions by hand
python src/run.py raw "RPM?"       # raw count should read 10
```

☐ **If no capacitor value works**, the reed is the wrong part. The VJ12-D10K
  is rated **20 Hz by its own packaging** and this rotor needs 50–70 Hz. A
  Hall-effect sensor has no contacts to bounce.

### Then confirm it at speed

☐ Run the fan at 500 rpm and check **K = rotor_rpm / V_oc is constant** across
  the wind range. A K that droops at high wind is the sensor running out of
  bandwidth — nothing aerodynamic imitates that.

---

## 2 · The repeat that gives you an error bar

☐ **Re-run `v1_Ra20`, remounting the rotor first.**

```bash
python src/blade_sweep.py --blade v1_Ra20_repeat \
       --notes "PETG, 0.2mm layer, Ra 20 — remount repeat" \
       --step-amps 0.02 --dwell 1.0
```

☐ Fingerprint must read **`94bed28333f7`**.

Every result so far comes from **one mounting of each rotor**. Without this
you cannot tell a roughness effect from a remounting effect — the difference
between *"Ra 80 is 13.7% better"* and *"Ra 80 is 13.7% better, and remounting
moves it 5%"*.

```bash
python src/compare_blades.py v1_Ra20 v1_Ra20_repeat
```

Whatever that returns **is your error bar**.

---

## 3 · While the cover is off

☐ **Ohm the generator winding**, phase-to-phase, cold and hot. `R_int` is
  fitted from the curve and has never been measured, yet it gates every
  derived quantity. It is also the whole source — winding, rectifier, wiring
  and sense IC together — and measuring the winding separates them.
☐ **VSense at the rectifier output**, not the load's binding posts, or the
  wiring and sense IC sit *inside* every power figure.
☐ **Confirm the Ra 80 print recipe** — fuzzy skin setting, layer height,
  nozzle. `--notes` recorded "0.2 mm nozzle"; if Ra 20 used a different one
  then nozzle and roughness both changed and the comparison is not clean.

---

## Known-good state

| | |
|---|---|
| PMC firmware | **5.7** — `RD/WR`, rotor rpm on ENC0 index (Z0), `RPMGAP`, `RPMZERO` |
| Drive profile | `data/profiles/windturbine_rs485.json`, 383 params, 0 differ |
| Protocol | `94bed28333f7` — Ra 20 and Ra 80 both on it |
| Result | **Ra 80 +13.73%**, 95% CI [+11.21, +16.26], higher at all 14 points |

**Do not repeat:** 9904 = VECTOR:SPEED · 2202/2203 = 6.0 s · the 10× reference
bug is fixed · rotor is a VAWT, R = 0.1016 m, span 245 mm, swept area 2RH.

---

## If something is wrong

| Symptom | Look at |
|---|---|
| Cannot reach the drive | `docs/04_troubleshooting.md` |
| Cannot find the Chroma | `python src/probe_load.py` |
| `No DFU capable USB device` when flashing | double-tap the Portenta's RESET |
| Drive faults right after a PMC flash | expected — DFU silences Modbus past par 3019. Clear at the keypad |
| Fan stops mid-run for no reason | the PMC host watchdog — something must talk to it every few seconds |
| Every point reads 0.000 V | no wind, or the rotor is not turning — check `fan_rpm_actual` |
| Peak power looks wrong | `limited_by` column first, then the fingerprint |
| Speeds off by exactly 10× | somebody reintroduced an Hz↔rpm conversion |

**Everything on this rig that has ever gone wrong produced plausible numbers
first.** If something looks fine, that is not evidence.
