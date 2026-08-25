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
python src/cp_lambda.py --sweep logs/sweep_v1_Ra20_summary.csv \
       --radius 0.1016 --height 0.2451 --poles <N> \
       --daq reference/data/03162026_sec_backup.xlsx
```

---

## 5 · v1 at Ra 80 — a controlled roughness experiment

Same blade, same geometry, same mount. **Only the printed surface texture
differs**, Ra 20 → 80 µm. That is a far stronger experiment than a second
blade, because nothing else changes: any difference in the curve is caused by
roughness, and there is no geometry confound to argue about.

☐ Mount the Ra 80 rotor.

```bash
python src/blade_sweep.py --blade v1_Ra80 --notes "PETG, 0.2mm, Ra 80" \
       --step-amps 0.02 --dwell 1.0
```

☐ Fingerprint must read **`94bed28333f7`** — identical to Ra 20.
  → Different fingerprint = not comparable. Stop and find out why.
☐ All 14 points `power-rolloff`.

### What to expect, and what would be interesting

Chord is 48 mm, so **Re runs 32,000 at 10 m/s to 121,000 at 38 m/s**. That is
squarely the regime where a laminar boundary layer separates before it can do
useful work, and where roughness is known to *help* by tripping it turbulent —
the same reason golf balls have dimples and low-Re gliders have turbulator
tape.

Two effects compete, and they pull in opposite directions across your range:

| | mechanism | strongest where |
|---|---|---|
| **helps** | trips the boundary layer, delays laminar separation | **low** wind (Re ≈ 32k) |
| **hurts** | adds skin friction once the roughness stops being hydraulically smooth | **high** wind |

Ra 20 stays hydraulically smooth across the whole range (k⁺ ≲ 2.5). **Ra 80
crosses into transitionally rough near the top** (k⁺ ≈ 10 at 38 m/s). So the
sharp prediction is a **crossover**: Ra 80 ahead at low wind, behind at high
wind — which shows up as a **lower exponent**.

    Ra 20 measured:   P ∝ v^3.75
    Ra 80 predicted:  P ∝ v^n  with  n < 3.75, toward 3.0

That exponent is one number, it falls straight out of the summary CSV, and it
is falsifiable. Three outcomes, all publishable:

- **n < 3.75 with a crossover** — roughness trips the boundary layer. The
  rotor is separation-limited, and surface finish is a design variable.
- **n ≈ 3.75, curve shifted down** — roughness is pure parasitic drag, no
  transition effect. Print smooth.
- **no difference at all** — the rotor is not separation-limited here, and
  print finish can be chosen for cost and speed. Also worth knowing.

```bash
python src/blade_sweep.py --compare v1_Ra20 v1_Ra80   # after the run
```

Reference to beat: `v1_Ra20` — **3.79 W at 37.5 m/s, P ∝ v^3.77, R² = 0.998**.

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
