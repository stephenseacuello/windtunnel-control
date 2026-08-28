# Aerolab Wind Tunnel — Programmable Control

Python control of the tunnel's fan drive over Modbus RTU, and of the electronic
load that brakes the turbine: scripted speed sweeps, gust simulation, automated
blade characterisation, and a web dashboard.

**Drive** ABB ACS550-U1-046A-2 · 15 HP · 208–240 V 3PH · fw 3.13 · S/N 2121803289
**Load** Chroma 63004-150-60 · 150 V / 60 A / 400 W · S/N 630041501113
**Host** Mac or Raspberry Pi → Portenta Machine Control → RS-485 → drive
**Project** URI · Sodhi lab, with Jeong lab on acquisition

---

## Where do I start?

| I want to… | Read |
|---|---|
| **Learn the rig from scratch** | **`TRAINING.md`** — start here if you are new |
| **Run a blade test today** | **`docs/07_blade_campaign.md`** — the user guide |
| **Going to the tunnel** | **`NEXT_SESSION.md`** — print it |
| **See what the rig has measured** | **`docs/09_results.md`** |
| **Know what is still unanswered** | `docs/11_open_questions.md` |
| **Just spin the fan** | `scripts/rpm.py` — one file, type an RPM |
| **Wire up a NEW rig** | `docs/10_commissioning.md` — done once, in Aug 2026 |
| **Compare two blades** | `python src/compare_blades.py <a> <b>` |
| **Take something to the tunnel** | **`FIELD_CARD.md`** — one page, print it |
| **Understand how it fits together** | `docs/01_architecture.md` |
| **Modify the code** | `docs/02_code.md` |
| **Know what gusts are achievable** | `docs/03_gusts.md` |
| **Fix something that's broken** | `docs/04_troubleshooting.md` |
| **Wire in the PMC or the load** | `docs/05_integration.md` |
| **Connect the Chroma load** | `docs/06_chroma.md` |
| **Identify the DAQ channels** | `docs/08_march_daq.md` |
| **Read or write drive parameters** | `firmware/acs550_pmc_v3/README.md` |
| **Present this to somebody** | `docs/slides/` — `build_slides.py` generates both decks |
| **Use the dashboard** | `webapp/README.md` |
| **See where the calibration came from** | `reference/README.md` |
| **Check I haven't broken anything** | `tests/README.md` |

Diagrams live in `docs/diagrams/`: **wiring**, **architecture**, and the
**commissioning flow**.

---

## Four things that decide whether this project succeeds

None of them are code.

**1. The drive commands rpm, not Hz.**
Parameter 1105 REF1 MAX is **2435 rpm**, corroborated by 2002 MAXIMUM SPEED and
9908 MOTOR NOM SPEED. There is no Hz→RPM conversion anywhere in this chain and
one must not be reintroduced. Some code and config keys still carry `hz` in
their names — legacy; **the values are rpm**. Mixing the two makes every
commanded speed wrong by a factor nobody notices.

**2. The hardwired E-stop is the safety device.**
Nothing in this repository is part of the safety chain, and nothing in it
should ever become part of it.

**3. Two watchdogs, and neither is optional.**
Drive parameters `3018`/`3019` stop the fan if the **PMC** goes quiet. The PMC
stops the fan if the **host** goes quiet. Any host-side loop that runs longer
than `transport.host_watchdog_ms` without talking to the PMC must tick it —
`PMCTransport.keepalive_tick()` exists for exactly this, and forgetting it
silently stopped a fan mid-sweep once already.

**4. With the load off, the turbine runs away.**
An unloaded rotor in moving air accelerates until something mechanical stops
it. The order is **load ON → wind UP → test → wind DOWN → load OFF**, never the
reverse at either end. `TurbineInterlock` enforces it.

---

## Wind speed

**v (m/s) = 0.02132 × RPM − 0.424**

| RPM | m/s | mph |
|---:|---:|---:|
| 200 | 3.8 | 8.6 |
| 600 | 12.4 | 27.7 |
| 1000 | 20.9 | 46.7 |
| 1400 | 29.4 | 65.8 |
| 1800 | 38.0 | 84.9 |
| 2400 | 50.7 | 113.5 |

Measured Feb 13, R² = 0.9996. Soft limit **2400 rpm**; full scale 2435 rpm
≈ 51.5 m/s.

Above ~1800 rpm the fan runs well past the motor's base speed, where available
torque falls as 1/N while fan torque rises as N². Watch motor current — the
drive is rated 46.2 A.

---

## Bandwidth — better than originally feared

**τ = 0.60 ± 0.14 s**, from four unclipped 1-cosine gust runs on 20 Aug 2026
(0.80/0.50/0.60/0.50). A fifth is excluded — it commanded 238% of the drive's
ramp limit, so the drive clipped it and the response is not first order.
Reproduce with `python src/analyze.py logs/20260820_14*_1mc.csv --summary`.
Corner frequency ≈ **0.25 Hz**.

Earlier planning assumed τ ≈ 3 s and a 0.05 Hz corner, and scoped gust work
around that pessimism. The measurement is roughly five times better, so gusts
down to a few seconds are achievable where they previously looked impossible.

Two caveats on that number:

- **Measure τ from a gust, not a step.** A step saturates the drive's ramp
  generator, so what you fit is parameter 2202, not the tunnel. A 1-cosine
  does not.
- **It is drive-and-fan, not air, and certainly not rotor.** Rotor inertia is
  downstream of all of it and is not in that 0.60 s at all.

---

## Quick start

### No hardware at all

```bash
pip install -r requirements.txt
python examples/gust_demo.py --tau 0.60
python src/blade_sweep.py --blade demo --simulate      # the full campaign loop
cd webapp && python app.py --dry-run                   # → http://127.0.0.1:5000
```

### On the real tunnel

```bash
./setup_pi.sh                                          # once
python src/run.py --port /dev/cu.usbmodem1101 --config data/tunnel.json monitor
python src/run.py --port /dev/cu.usbmodem1101 --config data/tunnel.json table
```

`monitor` writes nothing to the drive and the fan cannot move.

### A blade test

```bash
python src/blade_sweep.py --blade v1_Ra20 --notes "PETG, 0.2mm, Ra 20" \
       --step-amps 0.02 --dwell 1.0
```

Fourteen wind speeds, 500 → 1800 rpm, load ramped to the power roll-off at
each. ~10 minutes of continuous tunnel time. See
**`docs/07_blade_campaign.md`**.

---

## Layout

```
windtunnel-control/
├── README.md                you are here
├── TRAINING.md              new here? start with this
├── NEXT_SESSION.md          the next visit, in order — print it
├── FIELD_CARD.md            one page, printable, lives at the rig
├── CHANGELOG.md             what changed and why
│
├── scripts/rpm.py           standalone: type an RPM, fan goes there
│
├── src/
│   │  ── the tunnel ──
│   ├── acs550.py            drive driver — control words, registers
│   ├── transport.py         direct Modbus OR the PMC line protocol
│   ├── simulator.py         drive model for dry runs and tests
│   ├── calibration.py       RPM ↔ velocity
│   ├── config.py            persistent tunnel.json
│   ├── gusts.py             profile generators (no hardware needed)
│   ├── feedforward.py       recover bandwidth in software
│   ├── player.py            real-time streaming + logging
│   ├── characterize.py      system identification
│   ├── velocity_source.py   live wind speed in
│   ├── velocity_loop.py     closed loop on measured velocity
│   ├── preflight.py         checks before a long run
│   ├── analyze.py           pull τ out of any run log
│   ├── fit_sensor.py        which calibration form the data supports
│   ├── daq_survey.py        first look at a multichannel DAQ export
│   ├── archive_logs.py      move old runs off the Pi
│   └── run.py               CLI
│   │
│   │  ── the load and the turbine ──
│   ├── chroma_load.py       SCPI driver + TurbineInterlock
│   ├── probe_load.py        find the instrument, verify every command
│   ├── peak_finder.py       ramp the load to the power roll-off
│   ├── load_ramp.py         one wind speed, by hand
│   ├── blade_sweep.py       the whole campaign, 500 → 1800 rpm
│   ├── load_sim.py          a modelled rotor, for testing with no rig
│   ├── turbine.py           Cp(λ) sweep, stall guard
│   ├── cp_lambda.py         P_max(v) → Cp(λ), once rotor speed exists
│   ├── twin_residual.py     model vs measurement — the digital twin
│   ├── drive_profile.py     snapshot / diff / apply drive parameters
│   └── merge_load_facts.py  restore load-side config after an overwrite
│
├── firmware/
│   ├── acs550_pmc/          the original PMC sketch — untouched
│   └── acs550_pmc_v3/       adds RD/WR parameter access
│
├── blades/                  rotor geometry, named to match --blade
├── data/profiles/           drive parameter sets
├── data/snapshots/          timestamped records of what the drive held
│
├── webapp/                  Flask dashboard (URI palette)
├── tests/                   108 tests, no hardware needed
├── examples/                offline demos, DAQ integration patterns
├── docs/                    architecture, code, gusts, load, campaign
└── reference/               nameplate photos, reports, raw data
```

---

## Tests

```bash
cd tests && python -m pytest -q
```

108 tests, ~45 seconds, entirely against simulators. Weighted toward the
properties that hurt on real hardware — over-limit profiles refused rather than
clipped, mid-run faults aborting, every exit path stopping the fan, and no path
that unloads a spinning rotor. Run them after any change.

Five of them need `scipy`, which is optional: `pip install scipy`.

---

## Where the project actually is

**Working end to end.** The PMC talks to the drive, the drive turns the fan,
the Chroma sinks current, and `blade_sweep.py` runs a full 14-point blade
characterisation unattended in about ten minutes.

**Reference result** — blade `v1_Ra20` (PETG, 0.2 mm, Ra 20), 20 Aug 2026:
electrical power **P ∝ v^3.754**, R² = 0.998 across 10.2–38.0 m/s, peaking at
**3.72 W at 38 m/s**. Independent single-point runs reproduce the sweep to
0.2–0.3%.

That exponent is itself a result: 3.75 rather than 3.0 means **Cp is still
climbing with Reynolds across the entire tunnel range**, so a blade ranked at
10 m/s may not rank the same at 38.

## Still open

- **Rotor RPM from Jeong's DAQ.** The one missing channel. Without it you have
  P_max(v) per blade — a real comparison, but one that cannot separate rotor
  aerodynamics from generator matching. Every blade run before it lands has to
  be re-run to get λ, so the cost of waiting grows with each rotor tested.
- **Rotor tip radius.** Still `null`. A ruler. λ scales linearly with it, Cp as
  1/r², and nothing downstream works without it.
- **Sending fan rpm to the DAQ** so both rigs share one time base. Drive
  analog output X1-7/9 is the recommended route; see `docs/05_integration.md`.
- **The anemometer calibration form.** Fitting says linear-output (cup or
  vane), decisively — but a quadratic voltage-vs-RPM finding still contradicts
  fan affinity laws. One clean sweep settles it; see `reference/README.md`.
