# Running a Blade Campaign — User Guide

How to characterise a rotor, and how to compare rotors to each other without
fooling yourself. This is the day-to-day document; `TRAINING.md` is the one to
read first if you have never run the rig.

---

## What the measurement is

At each of fourteen wind speeds, the electronic load is ramped upward in
constant-current steps while terminal voltage and current are recorded. The
product V·I rises to a maximum and falls away. That maximum is the rotor's
**peak electrical power at that wind speed**, and the fourteen of them are the
blade's curve.

```
    at 500 rpm fan:
        load 0.01, 0.02, 0.03 ... A
        stop once power has fallen to 80% of its peak
        unload
    +100 rpm, repeat, up to 1800 rpm
```

**It is P_max(v), not Cp.** Cp needs rotor speed, which comes from Jeong's DAQ
and is not yet wired in. Two blades can produce identical electrical power for
opposite reasons — one aerodynamically better, one whose runaway speed happens
to sit closer to the generator's sweet spot — and P_max(v) cannot tell them
apart. It is still a real comparison; it is just not the aerodynamic one.

---

## The command

```bash
python src/blade_sweep.py --blade v2_Ra20 --notes "PETG, 0.2mm, Ra 20" \
       --step-amps 0.02 --dwell 1.0
```

`--blade` is required. A curve with no rotor name attached is not a
measurement, and a campaign that ranks blades cannot afford one unlabelled run.

It drives the fan itself through the PMC — no second terminal, no `jog`
timing to coordinate. About **ten minutes** of continuous tunnel time.

### Before you press enter

☐ Rotor mounted and the test section clear
☐ Load leads landed at the rectifier, **VSense at the rectifier output** — not
  on the load's own binding posts
☐ Nobody standing near the test section
☐ `--blade` and `--notes` describe *this* rotor, not the last one

### What you will see

```
── 8/14  fan 1200 rpm = 25.16 m/s ──────────────────
   settled: 13.295 V at 0.0000 A   (fan 1189 rpm, 9.0 A)
   step 8.8 mA (v² scaling of 20 mA)
   peak  0.9542 W at 0.152 A (fit)   raw 0.9592 W at 0.158 A   [25 steps, clean]
```

`clean` means it stopped on the power roll-off, which is what you want. Any
other word in that slot is worth reading about below.

At the end you get two files and a fingerprint:

```
logs/sweep_<blade>_points.csv     every dwell
logs/sweep_<blade>_summary.csv    P_max per wind speed
protocol fingerprint: 94bed28333f7
```

---

## Comparing blades — the part that goes wrong quietly

**Only compare runs whose protocol fingerprints match.**

The fingerprint hashes the settings that change what a curve *means*: step
size, step-scaling rule, dwell, cut-out voltage, CC range, floor current, the
roll-off fraction. It deliberately excludes `--max-amps`, which changes how far
a run got rather than what its numbers mean.

Two blades measured under different settings are not two data points. Across a
dozen rotors that is very easy to do by accident and nearly impossible to spot
afterwards — the numbers stay perfectly plausible.

**Freeze the protocol before the campaign, not during it.**

### Use `p_max_fit_w`, not `p_max_raw_w`

Both are in the summary CSV. The raw one is the largest single measurement; the
fit one is a parabola through the points around the maximum.

The top of P(I) is flat. At 1700 rpm on the reference sweep, every point from
0.21 to 0.30 A sat within 4% of the same power. Over a plateau like that the
raw maximum

- jitters in **position** by ±20% run to run, and
- is biased **high** in value, because the maximum of N noisy samples exceeds
  the true maximum by more as N grows.

The second is the campaign problem. A blade that happened to get more dwells
near its peak carries a larger upward bias, and part of the difference between
two blades becomes an artefact of how many points each got. On the reference
sweep the bias was +1.3% mean, positive in 13 of 14 points.

---

## Reading the `limited_by` column

| value | meaning | trust it? |
|---|---|---|
| `power-rolloff` | stopped cleanly past the peak | ✅ yes |
| `load-cutout` | current still tracked demand; terminal voltage fell under `CONF:VOLT:OFF` first | peak power is fine, the *threshold* is a lower bound |
| `rotor` | the rotor actually let go | fine, but you went further than the protocol needs |
| `ceiling` | hit `--max-amps` without ever rolling off | ⚠️ the peak may not have been reached — raise the ceiling |

A `censored` flag is set when the power peak sits above 85% of the last
sustained current, which means the ramp stopped before it had properly cleared
the maximum. Treat those points as lower bounds.

---

## Settings that matter, and why

| flag | default | notes |
|---|---|---|
| `--step-amps` | 0.01 | ladder increment **at `--stop-rpm`** |
| `--step-scaling` | `v2` | scales the step down as v² at lower wind |
| `--dwell` | 1.5 | seconds per step |
| `--stop-power-frac` | 0.80 | stop once power falls to this fraction of peak |
| `--unload-amps` | 0.0 | held between wind speeds |
| `--volt-off` | 0.5 | the load's cut-out voltage |
| `--max-amps` | 0.8 | backstop ceiling at `--stop-rpm`, scaled v² below |

**Why the step scales.** Peak current goes as v². A fixed 10 mA step gives ~35
dwells to the peak at 1800 rpm and **three** at 500 — and three points either
side of a maximum overshoots into stall before the roll-off can be confirmed.
That is not a preference; it showed up as four failed points out of fourteen
the first time the loop ran. `v2` keeps your chosen step at the top of the
range and scales it down below, one rule applied identically to every blade, so
comparability holds. The rule is in the fingerprint.

**Why 0 A between wind speeds is worth thinking about.** Zero amps in constant
current is an open circuit to a spinning rotor, and unloaded rotors accelerate.
On this rig it is a smaller change than it sounds — at 1800 rpm the 5 mA floor
already sat at 22.0 V against roughly 23 V open circuit — but if a future rotor
proves less tolerant, `--unload-amps 0.02` gives it a genuinely loaded idle.

**Time.** Roughly `(max_amps / step_amps) × dwell` seconds per point:

| settings | dwells | time |
|---|---:|---:|
| 10 mA, 1.5 s | ~700 | 23 min |
| 10 mA, 1.0 s | ~700 | 17 min |
| 20 mA, 1.0 s | ~350 | **~10 min** |

You do not need fifty points to locate a maximum; twenty resolves it
comfortably. But whatever you pick, pick it once.

---

## One wind speed at a time

For debugging or a single point, `load_ramp.py` does the same ramp without the
drive:

```bash
python src/load_ramp.py --mode peak --fan-rpm 1200 --max-amps 0.3 \
       --blade v2_Ra20 --volt-off 0.5 --wait-for-source 120 \
       --csv logs/peak_1200.csv
```

`--wait-for-source` turns the load on at the floor and then waits for terminal
voltage to appear, so you can raise the wind *after* starting it — which is the
order the interlock requires. Bring the fan up in another terminal with
`run.py jog`.

---

## With no hardware at all

```bash
python src/blade_sweep.py --blade demo --simulate
```

Runs the entire loop against a modelled rotor — no tunnel, no instrument, no
rotor. Use it to check a protocol change before spending tunnel time on it.

It models steady state only, with no rotor inertia, so it proves the logic and
the arithmetic and says **nothing** about whether `--dwell` is long enough.
Only the real rotor answers that.

---

## Config that must not be lost

`data/tunnel.json` is shared with the drive side and has been replaced
wholesale more than once, each time dropping the load-side measurements. Those
live in `data/load_facts.json`, which nothing else writes:

```bash
python src/merge_load_facts.py            # restore them
python src/merge_load_facts.py --check    # report drift, change nothing
```

Run it after anyone copies a new `tunnel.json` in.

---

## The reference result

Blade `v2_Ra20`, PETG 0.2 mm, Ra 20 — 20 Aug 2026, protocol `94bed28333f7`,
14/14 points clean.

| fan rpm | m/s | P_max (fit) | at |
|---:|---:|---:|---:|
| 500 | 10.2 | 0.0296 W | 0.017 A |
| 1000 | 20.9 | 0.4088 W | 0.073 A |
| 1400 | 29.4 | 1.6225 W | 0.228 A |
| 1800 | 38.0 | 3.7217 W | 0.328 A |

**P ∝ v^3.754, R² = 0.998** across the whole range. Independent single-point
runs at 1200 and 1800 rpm reproduce it to 0.3% and 0.2%.

The exponent is the finding. Constant Cp would give 3.0; 3.75 means Cp is still
climbing with Reynolds at 38 m/s, so this rotor has not reached its design
regime anywhere in this tunnel. Open-circuit voltage tells the same story from
the electrical side: V_oc ∝ v^1.39 where constant runaway λ would give v^1.0.
