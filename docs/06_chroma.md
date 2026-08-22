# Chroma 63004-150-60 — Connecting It

**Chroma 63004-150-60**, S/N 630041501113. 150 V, 60 A.

## What this unit actually has

From the rear panel:

| Connector | State |
|---|---|
| **USB Type B, "Device"** | present, unused — **the only digital interface** |
| GPIB / LAN | **blanking plate — option not fitted** |
| I Mon. (BNC) | present, analog current monitor |
| D-sub | present, something already plugged in — identify before disturbing |
| AC input | 100–240 V, 80 VA |

There is no Ethernet and no GPIB on this instrument. SCPI over TCP is not
available, whatever the driver supports.

**You need a USB A-to-B cable** — the printer-cable shape. A charge-only cable
will power nothing and enumerate nothing; if the probe finds no device, that is
the first thing to rule out.

## Which kind of USB

Instruments present USB as one of two entirely different things, and they need
different code:

| | Appears as | Needs |
|---|---|---|
| **USB-TMC** | `/dev/usbtmc0` | nothing, or pyvisa |
| **USB-CDC** | `/dev/ttyACM0` | pyserial |

Find out rather than guessing:

```bash
python src/probe_load.py --verify
```

It scans usbtmc nodes, serial ports and VISA resources, reports what answered
`*IDN?`, and prints the config block to paste into `tunnel.json`.

Before running it, on the instrument: **Config/Mode → interface → USB**, and
make sure it is not in Local lockout (`Shift + 1` = Local toggles it).

### Linux permissions

USB-TMC devices come up root-only by default:

```bash
echo 'SUBSYSTEM=="usbmisc", KERNEL=="usbtmc*", MODE="0666", GROUP="dialout"' \
  | sudo tee /etc/udev/rules.d/99-usbtmc.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

For the CDC case you are already covered by the `dialout` membership
`setup_pi.sh` adds.

## Verify the SCPI commands before trusting a sweep

```bash
python src/probe_load.py --verify
```

This matters more than it sounds. The driver's mnemonics follow Chroma
63000-series conventions, but they vary across models and firmware. **A load
that silently ignores `MODE CRH` sits in whatever mode it was already in while
your log faithfully records the resistance you thought you set.** That is an
afternoon of data that looks correct and is not — and unlike a connection
failure, nothing announces it.

`verify_commands()` sends each command with the load OFF and reads the error
queue after every one. Anything rejected needs the right mnemonic from the
programming manual for this model, and a one-line change in `chroma_load.py`.

## What the instrument actually said — 2026-08-19

Everything below was read off the unit, not from a datasheet. Load OFF
throughout; nothing was energised.

```
Chroma,63004-150-60,630041501113,2.01     over VISA, pyvisa-py backend
```

### The ranges are measured, not a decade convention

Found by demanding a value that is certainly too large and bisecting what the
instrument refused:

| Mode | Full scale |
|---|---|
| `CCL` | **2 A** |
| `CCM` | **6 A** |
| `CCH` | **60 A** |
| `CRL` | 250 Ω |
| `CRM` | 1250 Ω |
| `CRH` | 2500 Ω |

The low current range stops at **2 A, not 6**. It is not a tenth of anything,
which is why guessing it would have been wrong. Voltage range reads `Middle` —
this unit has three (`Low`/`Middle`/`High`), not two.

Pick the smallest range that covers the demand. A turbine making 1.5 A measured
on the 60 A range is being read with resolution it does not deserve, and that
error goes straight into Cp. `load_ramp.py --range auto` does this for you.

### Out-of-range is refused, not clamped

A demand above the active range comes back `2,"Data Range Error"`. That is
better than the silent clamping this package's docs previously assumed — the
error queue really is a guard here.

**But the setpoint then keeps its previous value.** The instrument is now
holding a number nobody asked for, and nothing announces it. That is why
`set_mode_cc`/`set_mode_cr` read the setpoint back (`CURR:STAT:L1?`,
`RES:STAT:L1?` — both confirmed working) rather than trusting an empty queue.

### There is no programmable protection on this model

Every one of these was rejected with `3,"Command Error"`:

```
VOLT:PROT:HIGH   CURR:PROT:HIGH   POW:PROT:HIGH
CURR:PROT:LEV    CURR:PROT        CURR:PROT:STAT?
CONF:CURR:PROT   SOUR:CURR:PROT   CONF:VOLT:PROT
VOLT:PROT:LEV    POW:PROT:LEV     CONF:VOLT:PROT:LEV
```

There is no OVP, OCP or OPP over SCPI here. **The 400 W envelope has to be
enforced by whatever is driving the load.** `load_ramp.py` checks V×I against
it before every step and stops; `CpSweep` should be held to the same standard
before it runs unattended.

What you do get:

| Setting | As found |
|---|---|
| `CONF:VOLT:ON` | 0.00 V |
| `CONF:VOLT:OFF` | **3.00 V** — below this the load stops sinking |
| `CONF:VOLT:LATC` | OFF |
| `SPEC:TEST` | OFF |

`CONF:VOLT:OFF` is the one genuinely protective setting that is programmable,
and on a turbine it is the difference between a load that lets go as the rotor
slows and one that holds a current demand into a collapsing source.

### The resource string in the config is not the one VISA reports

The Chroma pads its serial-number field with NULs:

```
VISA reports :  'USB0::2665::2176::630041501113\x00\x00::0::INSTR'
tunnel.json  :  'USB0::2665::2176::630041501113::0::INSTR'
```

`probe_load.py` strips them so the string survives JSON — and the stripped
string then **matches no device**, because the padding is part of the
identifier. Recording exactly what the probe printed produced a config that
could not open the instrument it had just been talking to. `open_resource()`
on it raises `ValueError: No device found.`

`VisaTransport._resolve()` now matches on the NUL-stripped form and falls back
to matching on the serial number alone, so the config opens as written. Do not
"fix" the config by pasting the NULs back in.

## Two things on the back panel worth using

**I Mon. (BNC)** is an analog voltage proportional to load current. Run it into
a spare DAQ channel and you get an independent, continuously-sampled current
record alongside the SCPI readings — useful for catching transients between
polls, and as a sanity check on the digital path. Free measurement.

**The D-sub already has a cable in it.** Identify where that goes before
changing anything. On these units it is typically the analog programming /
external control connector, and if someone is already driving the load through
it, that is a second controller competing with SCPI — the same class of problem
as two Modbus masters.

## How do you know it is working?

Three different claims, and they need three different tests. Only the third is
proof.

| Claim | Test | Status |
|---|---|---|
| It is on the bus | it enumerates; `*IDN?` answers | ✅ 2026-08-19 |
| It understands the driver | `probe_load.py --verify` — 20 commands, error queue read after each | ✅ 2026-08-19, all accepted |
| **It sinks the current it is told to** | `load_ramp.py` against a source | ❌ **never done** |

The first two both run with **LOAD OFF**. They cannot draw a milliamp, so they
cannot tell you the load works — only that it is listening. An instrument that
answers every command and sinks nothing passes both.

The third one needs a source on the terminals:

```bash
# bench supply at ~24 V, current limit at least 2 A
python src/load_ramp.py --peak-amps 1.5 --percent 80 --steps 9 \
                        --csv logs/load_proof.csv
```

It ramps 0 → 80% of the peak you name and checks every step three ways — the
error queue, the setpoint readback, and the measured current. It refuses to
start if the terminals are open, because every step would read 0.000 A and
tell you nothing.

`--plan-only` prints the ladder and the envelope check without connecting to
anything.

**Bench only.** It starts at zero amps — open circuit as far as a spinning
turbine is concerned — and switches the load off at the end. The turbine path
is `turbine.CpSweep`, which sweeps resistance, holds the interlock, and watches
RPM.

### "80% of peak" — of what?

`--peak-amps` is required and has no default, because the question is
ambiguous and the three answers are far apart:

| Reading | Value | Verdict |
|---|---|---|
| 80% of the 60 A rating | 48 A | inside the current rating, **6× outside the 400 W one** at any turbine voltage |
| 80% of the 400 W rating | 320 W | that is CP mode, which this package deliberately does not expose |
| 80% of the low range | 1.6 A | fine for a bench proof |
| **80% of what the turbine can deliver** | **not known** | the only one that means anything for a Cp sweep |

The ratings are corners of an envelope, not a box you can sit anywhere inside:
60 A is available only below ~6.7 V, 150 V only below ~2.7 A, and 400 W binds
everywhere in between.

The number that matters is unmeasured — `turbine.v_open_circuit_at_15mps` is
still `null` in `tunnel.json`. That is TODO B3, and it is one brief measurement
at low wind.

## The stall-threshold protocol

At each fan speed, walk the constant-current demand up until the rotor lets
go, then settle at 80% of that. `src/peak_finder.py` does the inner loop;
`load_ramp.py --mode peak` drives it for one wind speed.

```bash
# no hardware, no rotor — proves the detector
python src/load_ramp.py --simulate --fan-rpm 1800 --max-amps 0.8 --dwell 0

# real, one wind speed
python src/load_ramp.py --mode peak --fan-rpm 1800 --max-amps 0.8 \
                        --volt-off 0.5 --dwell 4 --csv logs/peak_1800.csv
```

### Three things it enforces, and why

**It never commands zero.** Zero amps in constant current is an open circuit
as far as a spinning rotor is concerned — the runaway condition. It holds
`--floor-amps` between phases and re-loads the rotor after every stall. A
caller stepping wind speed should do the same: raise the wind with the load
still on, never unload between points.

**The step is a fraction, not a fixed 10 mA.** Threshold current goes as v².
Over 500 → 1800 rpm (10.2 → 38.0 m/s) that is a factor of 14, so a fixed
10 mA step gives ~33 points at the top and **two** at the bottom.
`step = max(min_step, step_frac × largest current so far)` gives about
1/step_frac points to the threshold at every wind speed. Setpoint resolution
is 0.1 mA measured, so the hardware is not the constraint.

**It reports peak power and peak current as different things.** Cp/λ peaks at
a lower λ than Cp, so peak current sits deeper into stall than peak power. In
the model the power peak is at **⅔ of the stall current** — so *80% of the
stall threshold is past the power peak, on the falling side*. That is fine as
an operating point; it is not "80% of peak power" and should not be described
as one.

### CONF:VOLT:OFF censors the measurement at low wind

The load stops sinking below `CONF:VOLT:OFF`. As the rotor is loaded toward
stall its voltage falls, so at low wind the load quits **before** the rotor
does, and the number recorded is the instrument's limit wearing the turbine's
name.

Simulated, 500 → 1800 rpm, comparing detected threshold to the model's true
stall current:

| Voff | 500 rpm | 900 rpm | 1400 rpm | 1800 rpm |
|---|---|---|---|---|
| 3.00 V (as shipped) | **0.70** | 0.90 | 0.93 | 0.96 |
| 0.50 V | 0.99 | 0.96 | 0.98 | 0.96 |

A 30% under-read at the bottom of the sweep, with nothing to announce it.

`find_peak` detects it from the **shape**, not the voltage. Torque peaks well
past power, so a ramp that actually reached the rotor's limit puts the power
peak near **67%** of the threshold. If it sits up against the threshold
instead, the ramp stopped short and the result is reported as a **lower
bound**:

```
1800 rpm:  power peak sits at 64% of the threshold    healthy
 500 rpm:  power peak sits at 95% of the threshold    truncated
```

Two earlier attempts at this were wrong and are worth recording. Comparing the
final dwell's voltage to the previous one cannot work — a rotor stall and a
load drop-out end identically, with current at zero and voltage risen to open
circuit. Comparing the last sustained voltage against `CONF:VOLT:OFF` fails the
other way: it flagged a 96%-accurate run at 1800 rpm as censored, which is how
a warning that matters at 500 rpm gets ignored.

### The simulator

`src/load_sim.py` models V(I) = V_oc·√(1 − I/I_stall) with V_oc ∝ v and
I_stall ∝ v², anchored on the only two numbers available: **4 W at 1800 rpm**
and an assumed **12 V** there. It presents the `ChromaLoad` interface, so the
code under test is the code that runs on the bench.

It models no rotor inertia — every reading is a steady state. So it proves the
detector's logic and arithmetic, and says **nothing** about whether `--dwell`
is long enough. Only the rotor answers that.

## Wiring to the turbine

- Main terminals to the rectifier output. Mind polarity; 150 V CAT I.
- **Use the VSense terminals.** In CR mode the load *regulates* on the sense
  input, so bad sense means it controls to the wrong resistance rather than
  merely reporting wrong. Land the sense leads at the rectifier output, not on
  the load's own binding posts, or you measure your own lead drop.

## The interlock, restated

With the load OFF the turbine sees hundreds of kΩ — effectively open circuit —
and accelerates until something mechanical stops it.

```
load ON → wind UP → test → wind DOWN → load OFF
```

`TurbineInterlock` enforces this and refuses the reverse at either end. If the
fan cannot be confirmed stopped, **the load stays on** — an energised load is a
nuisance, a spinning open-circuit rotor is broken hardware.
