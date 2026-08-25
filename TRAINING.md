# Training Guide — Aerolab Wind Tunnel

For someone who has not run this rig before. Work through it in order; the
whole thing is about three hours, and the first hour needs no hardware at all.

By the end you should be able to run a blade characterisation unsupervised and
explain why each safety rule exists — which matters more than knowing the
commands, because the commands are in `FIELD_CARD.md` and the reasons are not.

---

## 0 · The four rules

Learn these before touching anything. Everything else in this document is
detail.

**1. The hardwired E-stop is the safety device.** Nothing in this software is
part of the safety chain. If something is wrong, hit the E-stop — do not go
looking for a keyboard.

**2. With the load off, the turbine runs away.** An unloaded rotor in moving
air accelerates until something mechanical stops it — on a printed rotor, that
is a blade leaving the hub. The order is always:

```
    load ON  →  wind UP  →  test  →  wind DOWN  →  load OFF
```

Never the reverse at either end. If the fan cannot be confirmed stopped, **the
load stays on.** An energised load is a nuisance; a spinning open-circuit rotor
is broken hardware and possibly a projectile.

**3. The drive commands rpm, not Hz.** Full scale is 2435 rpm, soft limit 2400.
Some code and config keys still say `hz`; the values are rpm. If you ever find
yourself converting between them, stop and ask.

**4. Two watchdogs, and they are load-bearing.** The drive stops the fan if the
PMC goes quiet. The PMC stops the fan if the host goes quiet. Do not disable
either to make testing easier, and **do not put the host on a UPS** — if it
loses power you want it to die hard so the watchdog trips.

---

## 1 · What the rig is (20 min, no hardware)

```
Browser/CLI ──► Mac ──USB──► PMC ──RS-485──► ACS550 ──► fan ──► wind
                  │                                             │
                  └──USB-TMC──► Chroma 63004 ◄──power── turbine ◄┘
                                                          │
                                                    DAQ ◄─┘  rotor RPM
```

| Box | Owns | Trusted with safety? |
|---|---|---|
| Mac | orchestration, logging | no |
| **PMC** (Portenta Machine Control) | the Modbus loop, both watchdogs | **yes** |
| ACS550 drive | tunnel wind speed | yes — its own comm watchdog |
| Chroma load | turbine operating point, best V/I measurement | no |
| DAQ (Jeong lab) | rotor RPM | no |

**Why the PMC is in the middle.** Modbus RTU has exactly one master. If a
direct USB-RS485 cable and the PMC were both landed on the drive's terminals
there would be two, and the failure is not merely CRC errors — it is two
processes commanding a 15 HP fan, neither aware of the other, and neither log
showing what the other did. The PMC also runs a real-time loop that a Linux or
macOS host cannot promise, and it adds the second watchdog layer.

**Only one device gets the drive's RS-485 terminals.** That is a physical fact
you enforce with your hands, not a software setting. The terminal numbers and
the landing procedure live in `PLAYBOOK.md` and `docs/05_integration.md` — and
only there, so there is one place to correct if it ever changes.

Read: `docs/01_architecture.md`, then `docs/05_integration.md`.

---

## 2 · Drive it with nothing plugged in (40 min)

Everything here runs on a laptop with no tunnel, no instrument, no rotor.

```bash
pip install -r requirements.txt
```

### Watch a gust that cannot hurt anything

```bash
python examples/gust_demo.py --tau 0.63
```

τ is the tunnel's time constant — how fast wind speed follows a change in fan
speed. Measured at **0.63 ± 0.12 s**. Try `--tau 3.0` and watch the same gust
get rounded off: that is what a slower tunnel would do to your profile, and it
is why `docs/03_gusts.md` exists.

### Run the whole blade campaign against a modelled rotor

```bash
python src/blade_sweep.py --blade demo --simulate
```

Fourteen wind speeds, load ramped at each, the same code that runs on the real
rig. Watch the `limited_by` column — every point should say `power-rolloff`.

Now break it on purpose:

```bash
python src/load_ramp.py --simulate --fan-rpm 500 --max-amps 0.08 --dwell 0 --volt-off 3.0
```

That prints a **CENSORED** warning. The load stops sinking below its cut-out
voltage, so at low wind it quits before the rotor does and the number recorded
is the instrument's limit wearing the turbine's name. Understanding that
warning is most of understanding the measurement.

### The dashboard

```bash
cd webapp && python app.py --dry-run          # → http://127.0.0.1:5000
```

### Tests

```bash
cd tests && python -m pytest -q
```

108 tests, ~45 seconds. Read a few in `tests/test_peak_finder.py` — they are
written as statements about what must never happen, and they are a faster way
to learn the rig's failure modes than any prose.

---

## 3 · Read-only on the real tunnel (30 min)

Nothing here can move the fan.

```bash
python src/run.py --port /dev/cu.usbmodem1101 --config data/tunnel.json monitor
```

If it cannot reach the PMC, work through `docs/04_troubleshooting.md` rather
than changing settings hopefully.

```bash
python src/run.py --port /dev/cu.usbmodem1101 --config data/tunnel.json table
```

Prints RPM → m/s from the shipped calibration. Sanity-check it against the
table in `README.md`; they are generated from the same numbers and a test
enforces that they agree.

### Check the load answers

```bash
python src/probe_load.py --verify --skip /dev/cu.usbmodem1101
```

**Use `--skip`.** Discovery writes `*IDN?` at every serial port it finds, and
one of them is the PMC.

This proves the instrument *parses* every command the driver sends. It does not
prove the load works — every check runs with the load OFF and cannot draw a
milliamp. Knowing the difference between "it answers" and "it works" is the
habit this rig most rewards.

---

## 4 · First motion (30 min, supervised)

**Somebody experienced should be present the first time.**

Test section clear. Everyone told. Hand on the E-stop.

```bash
python src/run.py --port /dev/cu.usbmodem1101 --config data/tunnel.json jog 500 --seconds 30
```

500 rpm is 10.2 m/s — the bottom of the working range. Watch the motor current
in the telemetry: it will be high while accelerating and settle to roughly 4–5 A.

Then, deliberately: **pull the USB cable mid-run.** The fan must ramp down
within a few seconds. That is the host watchdog, and it is the reason a laptop
is allowed to command a 15 HP fan at all. If it does not stop, something is
wrong with `3018`/`3019` or the PMC's `WD` setting and nothing should run
unattended until it is fixed.

---

## 5 · Your first blade run (45 min)

Follow **`docs/07_blade_campaign.md`**. In outline:

```bash
python src/blade_sweep.py --blade <name> --notes "<material, layers, finish>" \
       --step-amps 0.02 --dwell 1.0
```

Then look at what came out:

- Did all 14 points say `power-rolloff`?
- Does `p_max_fit_w` rise smoothly with wind speed?
- Does the fingerprint match the reference sweep (`94bed28333f7`)?

If any point says `ceiling`, the ramp never reached the peak — raise
`--max-amps`. If any says `load-cutout`, the load quit before the rotor did;
the peak power is still good but the threshold is a lower bound.

---

## 5b · The tools you have not met yet

Worth ten minutes each, all runnable now.

**The dashboard's Turbine and Blades tabs.** The interlock indicator, the live
load, a blade-sweep runner, and a digital twin that spins your actual rotor
geometry. The twin's rotor speed is **inferred from terminal voltage, not
measured** — the panel says so, and it shows `no data` rather than a confident
zero when telemetry stops.

**Drive parameters.** `src/drive_profile.py` and the dashboard's Parameters
tab. Snapshot what the drive holds, diff it against a profile, restore a
saved one. Needs PMC firmware 3.0; the refusal list lives in that firmware,
not the host, because a host config file can be copied and edited in a hurry.

```bash
python src/drive_profile.py snapshot --name baseline --note "as found"
python src/drive_profile.py diff --profile windturbine_rs485
```

**The twin residual.** `src/twin_residual.py` fits the source model to every
measured wind speed and reports the gap. This is the part that makes a twin a
twin rather than a render — and it already earned its keep: the residual was
one-sided at all fourteen wind speeds, which said the model was missing a
term, and it was.

```bash
python src/twin_residual.py --sweep logs/sweep_v1_Ra20_points.csv
```

**Cp(λ).** `src/cp_lambda.py` is ready for the moment rotor speed exists. It
refuses to run without it, deliberately — without rotor speed you have
P_max(v), not Cp(λ).

---

## 6 · Habits worth having

**Label everything, immediately.** `--blade` and `--notes` are how a curve stays
meaningful three months later. One run in this project's history was recorded
as `PLA, 0.1mm` when it was PETG 0.2 mm, and only luck meant that run produced
no usable data.

**Never compare across fingerprints.** If two runs used different step sizes or
dwells, they are not two data points. The fingerprint exists because this
mistake is invisible afterwards.

**Distrust a number that agrees with you.** The load-cutout censoring, the
argmax bias, the PMC's ×10 scaling error, the sweep that outran the wind — every
one of those produced perfectly plausible numbers. The rig has no way to tell
you it is lying; the checks in the code are there because someone was fooled
once.

**Write down what the instrument says, not what the config says.** The Chroma's
cut-out voltage drifted from 3.00 V to 0.50 V with nobody recording why. Read
it at the start of each session.

**Restore the load facts after anyone copies a config.**

```bash
python src/merge_load_facts.py --check
```

---

## 7 · Where to look when something is wrong

| Symptom | Look at |
|---|---|
| Cannot reach the drive | `docs/04_troubleshooting.md` |
| Cannot find the Chroma | `docs/06_chroma.md` |
| Fan stops mid-run for no reason | host watchdog — is something ticking the PMC? |
| Every point reads 0.000 V | no wind, or the fan is not actually turning — check the `fan N rpm` column |
| Peak power looks wrong | `limited_by` column first, then the fingerprint |
| Speeds off by exactly 10× | somebody reintroduced an Hz↔rpm conversion |
| Config lost the load settings | `python src/merge_load_facts.py` |

---

## 8 · What you should be able to explain

If you can answer these without looking, you are ready to run the rig alone.

1. Why does the load go on before the wind comes up?
2. What happens if the host process is killed mid-sweep? What stops the fan?
3. Why is the ladder step smaller at 500 rpm than at 1800?
4. Why is `p_max_fit_w` preferred over `p_max_raw_w`?
5. What does `limited_by: load-cutout` mean, and is that point usable?
6. Why can two blades with identical P_max(v) still be aerodynamically
   different?
7. What is the protocol fingerprint for, and what does it deliberately exclude?
