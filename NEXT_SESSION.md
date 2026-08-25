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
- Drive captured: `data/profiles/aerolab.json`, 383 params, 0 differ
- **The 10× is fixed** — commanded 10 rpm now reads 10 rpm at par 0102

---

## 1 · The two numbers still blocking Cp(λ)

☐ **Generator pole count** — nameplate, or count the magnets.
  → The ONE number between the DAQ data you already have and rotor rpm. It
  converts every past capture retroactively.
  → **poles = ________** (magnetic poles, not pole pairs)

☐ **Are ch3/4/6 still landed on Jeong's DAQ?**
  → In the March capture they are the generator's three phases (mutual
  correlation −0.50 = cos 120°). If still connected, rotor speed needs **no
  new sensor and no new wiring**.
  → Ask Taegu what `encoder_disc.stl` was for **before** anyone builds it.

*Photograph the generator nameplate while you are there.*

Then, with no further tunnel time:

```bash
python src/cp_lambda.py --sweep logs/sweep_v2_Ra20_summary.csv \
       --radius 0.1016 --height 0.2451 --poles <N> \
       --daq reference/data/03162026_sec_backup.xlsx
```

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
