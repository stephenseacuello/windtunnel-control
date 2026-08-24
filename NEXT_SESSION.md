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

## 1 · Three questions, twenty minutes, no tools but a ruler and a phone

These block Cp(λ). Nothing else on this list matters as much.

☐ **Rotor tip radius** — from the **axis of rotation**, not blade length.
  The STL gives 245 mm of *span*; tip radius is hub + root offset + span, and
  the hub is not in that file.
  → λ scales linearly with it, Cp as 1/R². A 10 % error in R is 21 % in Cp.
  → write it here: **R = ________ m**   hub = ________ m

☐ **Generator pole count** — nameplate, or count the magnets.
  → This is the ONE number between the DAQ data you already have and rotor
  rpm. It converts every past capture retroactively.
  → **poles = ________** (magnetic poles, not pole pairs)

☐ **Are ch3/4/6 still landed on Jeong's DAQ?**
  → In the March capture they are the generator's three phases (mutual
  correlation −0.50 = cos 120°). If they are still connected, the rotor-speed
  measurement needs **no new sensor and no new wiring**.
  → Ask Taegu what `encoder_disc.stl` (40 × 40 × 8 mm, drawn 31 Jul) was for
  **before** anyone builds it. It may be solving a solved problem.

*Photograph the generator nameplate while you are there.*

---

## 2 · Two keypad readings, one minute

☐ **9904 MOTOR CTRL MODE** = ________
  → decides whether "actual speed" is a slip-compensated estimate or just
  frequency with a fixed assumption

☐ **2202 ACCEL TIME** = ________
  → `run.py` prints *"ramp time unreadable — the slew check is OFF"*. Read it
  once and pass `--max-slew` to restore the check.

---

## 3 · Flash the PMC, then re-earn the trust

☐ **Flash `firmware/acs550_pmc_v3/`.**
  Arduino IDE → Portenta H7 / Machine Control. Same libraries as 2.0.
  *The original sketch is untouched at `firmware/acs550_pmc/`.*

☐ Confirm:  `ID` → `OK ID acs550-pmc 3.0 RD/WR`
            `RD 1105` → `OK RD 1105 2435`

☐ **Re-run the watchdog test. Pull the USB mid-run, deliberately.**
  The fan must ramp down within a few seconds.
  → **Any firmware change invalidates the previous evidence.** That watchdog
  is the entire reason a laptop may command a 15 HP fan.
  → passed? ☐

---

## 4 · Capture the drive before anything writes to it

☐ **Snapshot as-found**, then a full scan:

```bash
python src/drive_profile.py snapshot --name baseline --note "as found $(date +%F)"
python src/drive_profile.py scan --name aerolab_asfound
```

☐ **Promote the scan to the AeroLab profile:**

```bash
python src/drive_profile.py promote --snapshot <file>.json \
       --name aerolab --description "Aerolab's original configuration"
python src/drive_profile.py diff --profile windtunnel
```

☐ **`git add data/snapshots data/profiles && git commit`**
  → A snapshot nobody can diff against is a file, not a record.

*The scan is read-only and cannot change anything. Group 53, 3018/3019 and
group 99 are refused by the firmware — set those on the keypad if you need to.*

---

## 5 · A second blade — the campaign's real test

☐ Mount the second rotor.

```bash
python src/blade_sweep.py --blade <name> --notes "<material, layers, finish>" \
       --step-amps 0.02 --dwell 1.0
```

☐ All 14 points say `power-rolloff`? ☐
☐ Fingerprint matches **`94bed28333f7`**? ☐
  → If it differs, the two blades are **not comparable**. Stop and find out why.

**This is the first evidence the protocol discriminates between rotors**,
which is what the whole campaign rests on and has never been shown.

Reference to beat: `v2_Ra20` — **3.79 W at 37.5 m/s, P ∝ v^3.77, R² = 0.998**.

---

## 6 · Wiring, while the cover is off

☐ **VSense to the rectifier output**, not the load's binding posts.
  → Otherwise the wiring and the series sense IC sit *inside* every
  measurement and each power figure is low by I²R.

☐ **Drop the gain on DAQ ch3/4/6.** They sit at 98 % of ADC range and will
  clip — and a clipped phase corrupts the Clarke angle, which is the thing
  that makes rotor speed recoverable at all.

☐ **Trace the D-sub** already plugged into the Chroma's back panel.
  → If something drives the load through analog programming, that is a second
  controller competing with SCPI.

☐ *Optional:* **drive analog output → DAQ ch2** (which is unconnected, sitting
  at mid-rail). Fan rpm and rotor rpm then share one time base.
  → par 1501 = 102, 1502 = 0, 1503 = 2435, 1504 = 4 mA, 1505 = 20 mA,
  1506 = 0.1 s · 249 Ω at the DAQ end · X1-7 / X1-9 · verify terminals on the
  silkscreen.

---

## 7 · If you get time

☐ **Find `--dwell` empirically.** The simulator has no rotor inertia, so it
  cannot tell you this. Start at 5 s and halve until the reported threshold
  starts moving, then double back.

☐ **One anemometer reading at a known rpm.** Confirms the rpm→velocity half
  against a second instrument. `run.py verify`.

---

## Bring home

- [ ] R, hub radius, pole count
- [ ] Photos: generator nameplate, the D-sub cable's other end
- [ ] `data/snapshots/*.json` committed
- [ ] The second blade's sweep CSVs
- [ ] 9904 and 2202
- [ ] Whether ch3/4/6 are still landed

**With R and the pole count, `cp_lambda.py` turns every sweep you already have
into Cp(λ) without another minute of tunnel time.**

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
| Config lost the load settings | `python src/merge_load_facts.py` |

**Everything on this rig that has ever gone wrong produced plausible numbers
first.** If something looks fine, that is not evidence.
