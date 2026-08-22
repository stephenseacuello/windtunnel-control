# Wind Tunnel Playbook

Front to back. Do the phases in order — several of them exist specifically to
catch a failure before it can move a 15 HP fan.

**Drive:** ABB ACS550-U1-046A-2 · 15 HP · 208–240 V 3PH · S/N 2121803289 · fw 3.13

| Phase | What | Time |
|---|---|---|
| 0 | Buy the parts | 5 min + shipping |
| 1 | Record the existing config — **while powered** | 15 min |
| 2 | Power down safely | 10 min |
| 3 | Open the drive | 5 min |
| 4 | Land the cable | 20 min |
| 5 | Close up, restore power | 10 min |
| 6 | Set drive parameters | 15 min |
| 7 | Set up the Pi | 20 min |
| 8 | Prove comms — read-only | 5 min |
| 9 | Self-test — read-only | 5 min |
| 10 | Hand over control | 10 min |
| 10B | Keep the Aerolab panel working — **recommended** | 45 min |
| 11 | First motion + watchdog test | 15 min |
| 12 | Verify the calibration | 10 min |
| 12B | Rebuild it from a new table — only if you have one | 15 min |
| 13 | Characterize — measure τ | 15 min |
| 14 | Tune the ramps | 30 min |
| 15 | Run experiments | — |

Phases 1–9 cannot move the fan. Phase 10 is where that changes.

---

# PHASE 0 — Buy

| Item | Part | ~Cost |
|---|---|---|
| USB-RS485 cable | FTDI **USB-RS485-WE-1800-BT** | $40 |
| Host | Raspberry Pi 4/5 + SD + PSU | $80 |
| Ferrules | 22–24 AWG bootlace + crimper | $20 |
| Screwdriver | 2.5 mm flat blade, insulated | — |
| Multimeter | Rated for 240 V service | — |
| LOTO | Lock + tag | — |

**No Belden cable.** The FTDI cable's six leads land directly in X1. Separate
cable only matters if you switch to a terminal-block adapter later.

☐ Parts on hand

---

# PHASE 1 — Record the existing config (drive still powered)

This is your rollback. If anything goes wrong you can put the tunnel back
exactly as Aerolab shipped it.

Keypad → MENU → PARAMETERS. Write down **and photograph** each:

☐ `9902` APPLIC MACRO
☐ `1001` EXT1 COMMANDS
☐ `1002` EXT2 COMMANDS
☐ `1102` EXT1/EXT2 SEL
☐ `1103` REF1 SELECT
☐ `1105` REF1 MAX ← **the number everything scales from**
☐ `1106` REF2 SELECT
☐ `1601` RUN ENABLE
☐ `1608` START ENABLE 1
☐ `2202` / `2203` ACCEL / DECEL TIME
☐ `2008` MAX FREQ
☐ `3018` / `3019` COMM FAULT FUNC / TIME
☐ `9802` COMM PROT SEL
☐ `5302` `5303` `5304` `5305` `5310` `5311`

☐ Photograph the normal running screen, so you know what "correct" looks like

---

# PHASE 2 — Power down safely

☐ Find the disconnect feeding the tunnel drive. Confirm it's the right one.
☐ Verify your meter works on a known live circuit
☐ Open the disconnect
☐ **Apply lock and tag**
☐ **Wait 5 minutes minimum.** The DC bus capacitors hold a lethal charge after
  the supply is removed. This is not conservative advice — it's why the manual
  has a warning page.
☐ Verify dead at U1/V1/W1
☐ Re-verify your meter on the known live source

**Also:** relay terminals 19–27 can carry voltage from an external source even
with the drive completely dead. If Aerolab wired anything there, treat it as
live until traced.

---

# PHASE 3 — Open the drive

Per ABB quick start 3AUA0000001558, frames R1–R4:

☐ Remove the control panel (keypad) — press its retaining catch, tilt free.
  Set it somewhere safe; you need it back for Phase 6.
☐ **Loosen the captive screw at the top** of the front cover. It stays in the
  cover — it won't drop into the drive.
☐ **Pull near the top** to unhook, then lift the cover away. Don't lever from
  the bottom.
☐ Locate **X1** — one row of 32 terminals across the control board
☐ **Photograph X1 as-found**, close enough to read every wire and number
☐ Note what Aerolab occupies.

**Verified from photographs, 18 Aug 2026: X1 is completely empty.** No analog,
digital or relay wiring is landed anywhere on the block. The Aerolab panel does
not use the drive's control terminals at all — tunnel speed is set from the
**keypad**, in LOC mode.

Two consequences, both good:

- **X1-29/30/31 are free.** Nothing to work around, nothing to preserve.
- **The keypad is the manual fallback**, and it works via LOC/REM regardless of
  what 1001/1103 are set to. Phase 10B becomes optional rather than
  recommended.

Confirm it is still true before landing anything — but expect an empty block.

☐ **Check the RS-485 termination DIP switch.** Photographed **OFF** as found.
  Small red 2-position block immediately left of terminals 28–32, labelled
  `RS485 BUS TERMINATION`, `ON` printed along the top edge. It must go ON.

```
        ┌──────┬──────┬──────┬──────┬──────┐
        │  28  │  29  │  30  │  31  │  32  │
        │ SCR  │  B   │  A   │ AGND │ SCR  │
        └──────┴──────┴──────┴──────┴──────┘
                  (+)    (−)   common
        [J2] DIP switch adjacent = 120 Ω terminator
```

---

# PHASE 4 — Land the cable

☐ Open a knockout in the **gland box** at the bottom (its cover is one screw).
  Use its **own** knockout, not shared with power or motor conduit.
☐ Route the FTDI cable through, fit a cable clamp

Then crimp and land:

| Wire | Combine with | Terminal |
|---|---|---|
| **Orange** (Data+) | **Green** (Term 2) | one ferrule → **X1-29** |
| **Yellow** (Data−) | **Brown** (Term 1) | one ferrule → **X1-30** |
| **Black** (GND) | — | **X1-31** |
| **Red** (+5 V) | — | **cut back and tape off** |

```
  FTDI CABLE                                ACS550 X1
  ┌──────────────────┐                      ┌──────────────┐
  │ ORANGE  Data+ ───┼──┐                   │              │
  │ GREEN   Term2 ───┼──┴─ one ferrule ────►│  29  B (+)   │
  │ YELLOW  Data− ───┼──┐                   │              │
  │ BROWN   Term1 ───┼──┴─ one ferrule ────►│  30  A (−)   │
  │ BLACK   GND   ───┼──────────────────────►│  31  AGND   │
  │ RED     +5V   ─╳ │  taped off           │              │
  └──────────────────┘                      └──────────────┘
```

Bridging Term1/Term2 across the pair is what engages the cable's internal
120 Ω resistor — it ships unconnected.

☐ Set **J2 termination ON**
☐ X1-28 and X1-32 stay empty (no separate shield with this cable)
☐ Keep the cable ≥8 in from power and motor conductors; cross at 90°
☐ Don't zip-tie it alongside the motor leads inside the enclosure
☐ Tug-test every conductor
☐ No stray strands bridging terminals

If the drive won't answer in Phase 8, **swapping the two ferrules between 29
and 30 is the first thing to try.**

---

# PHASE 5 — Close up and restore power

☐ **No tools, screws, or wire offcuts left inside.** Check twice — a loose
  conductor in a VFD is a short waiting for the next power-up.
☐ Align the front cover, slide it on
☐ Tighten the captive screw
☐ Reinstall the keypad
☐ Refit the gland box cover (1 screw)

☐ **Confirm the Aerolab start switch is OFF.** ABB's own warning: the ACS550
  starts automatically at power-up if a run command is already present. If
  someone left the panel switch on, the fan spins the instant you close the
  disconnect.

☐ Remove lock and tag
☐ Close the disconnect
☐ Drive boots normally
☐ **Verify the Aerolab panel still works** — pot and start button, briefly, at
  low speed. Confirm you broke nothing before adding anything.

---

# PHASE 6 — Set drive parameters

| Param | Name | Set to |
|---|---|---|
| `9802` | COMM PROT SEL | `1` (STD MODBUS) |
| `5302` | EFB STATION ID | `1` |
| `5303` | EFB BAUD RATE | `19.2` |
| `5304` | EFB PARITY | **8E1 (even)** — matches the PMC firmware |
| `5305` | EFB CTRL PROFILE | `0` (ABB DRV LIM) |
| `5310` | EFB PAR 10 | `103` → output freq at 40005 |
| `5311` | EFB PAR 11 | `104` → motor current at 40006 |
| `3018` | COMM FAULT FUNC | `1` (FAULT) |
| `3019` | COMM FAULT TIME | `3.0` s |

**On parity:** the PMC sketch assumes even parity. Set the drive to match the
firmware rather than the other way round — a drive parameter is three keypad
presses; reflashing in the field is not. If you commission over the direct
transport instead, pass `--parity E`.

**On parity:** the PMC sketch assumes even parity. Set the drive to match the
firmware rather than the reverse — a drive parameter is three keypad presses,
reflashing in the field is not. Commissioning over the direct transport instead?
Pass `--parity E`.

☐ **Power-cycle the drive.**

Not optional. `9802` and everything in group 53 are only read at boot. Skipping
this is the single most common reason a first attempt gets total silence, and
it sends you chasing wiring faults that don't exist.

**Do NOT set 1001/1103 yet.** Those come in Phase 10, after comms are proven.

---

# PHASE 7 — Set up the Pi

Mount it in its own small box near the drive — **not inside the VFD enclosure**
(heat and EMI in there are worse than anywhere else in the room).

☐ **Do not put the Pi on a UPS.** If it loses power you want it to die hard, so
  the drive's comm watchdog stops the fan. Battery-backing the controller
  defeats the safety property you set up in Phase 6.

```bash
unzip windtunnel-control.zip
cd windtunnel-control
./setup_pi.sh
```

☐ Log out and back in (the `dialout` group change needs a new session)

The script adds you to `dialout`, disables **ModemManager** (which otherwise
sees a new serial device, assumes it's a cellular modem, and starts firing AT
commands at your VFD), creates a `/dev/ttyVFD` symlink keyed to the cable's
serial number, and builds a venv.

☐ `ls -l /dev/ttyVFD` shows the symlink

---

# PHASE 8 — Prove comms (read-only, fan cannot move)

`1001` and `1103` still point at the Aerolab panel, so the drive **cannot**
accept a run command over Modbus. Nothing here can move the fan.

```bash
source ~/tunnel/bin/activate
cd src
python run.py --port /dev/ttyVFD monitor --seconds 20
```

☐ You get a status word, a plausible REF1 MAX, and an output frequency

### If you get nothing

1. **Swap the two ferrules between X1-29 and X1-30.** Most likely cause.
2. Confirm port name, and that `--baud`/`--parity`/`--unit` match `5303`/`5304`/`5302`
3. Confirm you power-cycled after Phase 6
4. Read the drive's own counters on the keypad — they work when Modbus doesn't:

| Param | Climbing means |
|---|---|
| `5306` OK MESSAGES | Frames arriving and parsing → problem is PC-side |
| `5307` CRC ERRORS | Noise, termination, or baud mismatch |
| `5308` UART ERRORS | Parity or framing — check `5304` |
| all three at zero | Nothing physically arriving → back to step 1 |

---

# PHASE 9 — Self-test (read-only)

```bash
python run.py --port /dev/ttyVFD selftest
```

Checks, against your actual drive, the four things the code assumes rather than
knows: parameter address offset, the par 1105 scaling, where 5310/5311 point,
and the pymodbus keyword.

☐ **It will ask you to confirm 1105 against the keypad. Do it.** A wrong guess
  there makes every commanded speed off by exactly 10×, silently, and every
  dataset you take would be wrong in a way that looks plausible.

☐ Zero failures before continuing

---

# PHASE 10 — Hand over control

**This is where the fan becomes commandable.**

☐ Test section clear, nothing loose in the flow path
☐ **Test the E-stop.** Press it, confirm the drive drops out, reset it. Do this
  now, not when you need it.
☐ Tell anyone else in the lab
☐ Set `1103` REF1 SELECT = `8` (COMM)
☐ Set `1001` EXT1 COMMANDS = `10` (COMM)
☐ **Put a sign on the tunnel** saying it is under remote control

Because X1 is empty, there is no Aerolab pot or start button to disable — the
manual control was always the keypad, and **the keypad still works.** Anyone
can press LOC/REM and take the tunnel back at any time.

That cuts both ways: it is a good fallback, and it is also how a colleague
takes your script offline without telling you. Status bit 9 REMOTE going clear
is the signal, and both `selftest` and the profile player watch for it.

Phase 10B is therefore **optional** on this rig rather than recommended.

---

# PHASE 10B — A local/remote selector switch (optional on this rig)

**Not needed unless you want one.** X1 is empty, so there is no Aerolab panel
wiring to preserve, and the keypad already provides manual control via LOC/REM.
This phase is worth doing only if you want a physical selector rather than a
keypad button — for teaching use, say, where a labelled toggle is clearer than
a two-function key.

Phase 10 as written makes the tunnel a scripted-only machine. That is fine for
a dedicated rig and wrong for a shared teaching tunnel.

The ACS550 supports **two independent control locations**, EXT1 and EXT2,
selected by a digital input. Wire a switch and the tunnel works both ways.

### Wire the selector

☐ Power down, LOTO, 5 min, verify dead (Phase 2 again)
☐ Fit a SPST toggle switch on the panel
☐ Land it on a spare digital input — **DI3, X1-15** — wired the same way the
  existing DIs are. Check whether Aerolab used sinking or sourcing (whether the
  existing DI commons go to `DCOM` X1-12 or `+24V` X1-10) and match it.
☐ Close up, restore power

### Set the parameters

| Param | Set to | Meaning |
|---|---|---|
| `1102` | `3` (DI3) | the switch chooses the control location |
| `1001` | *your Phase 1 value* | **EXT1 = Aerolab panel**, restored |
| `1103` | *your Phase 1 value* | EXT1 reference = the pot |
| `1002` | `10` (COMM) | **EXT2 = Modbus** |
| `1106` | `8` (COMM) | EXT2 reference = Modbus |

```
   switch OPEN   →  EXT1  →  Aerolab pot + start button   (manual)
   switch CLOSED →  EXT2  →  Modbus reference + commands  (scripted)
```

Open = manual is deliberate. If the switch fails, the wire breaks, or someone
disconnects it, the tunnel **falls back to manual control**, not to computer
control.

☐ Label the switch: MANUAL / COMPUTER
☐ Test both positions before trusting it
☐ Re-run `selftest` — it now reports the selector as a manual fallback

### What each mode gives you

| | MANUAL (EXT1) | COMPUTER (EXT2) |
|---|---|---|
| Aerolab pot + start button | works | inactive |
| Python control | ignored | works |
| Keypad readout | works | works |
| E-stop | works | works |
| Comm watchdog | n/a | active |

---

# The keypad is always a fallback

Independent of any of this: pressing **LOC/REM** on the drive's keypad takes
local control and ignores both the panel and the fieldbus. Someone can always
run the tunnel from the keypad arrows.

That cuts both ways — it is also how a colleague can take your script offline
without telling you. The code detects it: status word bit 9 REMOTE goes clear,
`selftest` reports it, and `player.py` refuses to start a profile rather than
running for five minutes against a drive that was never listening.

---

# PHASE 11 — First motion

```bash
python run.py --port /dev/ttyVFD jog 10 --seconds 20
```

☐ Fan ramps up, holds ~10 Hz, ramps down
☐ Reported frequency tracks the keypad display
☐ Ctrl-C mid-run → fan ramps down

Then the test that matters:

☐ **Pull the USB cable mid-run, on purpose.** The drive must fault and stop
  within ~3 s. If it doesn't, `3018`/`3019` are wrong — fix them before running
  anything unattended.

---

# PHASE 12 — Verify the calibration

The velocity-vs-RPM half is measured from your Feb 13 data. The Hz→RPM half
assumes a 4-pole 1750 rpm/60 Hz direct drive. One reading settles it — you don't
need the nameplate.

```bash
python run.py --port /dev/ttyVFD verify --hz 30
```

Runs 30 Hz, settles, holds 30 s while you read the anemometer. Then:

```bash
python run.py --port /dev/ttyVFD verify --hz 30 --measured 18.4
```

- Within 5% → assumption confirmed, done
- Off by a factor → solves for the true rpm-per-Hz, reports the implied pulley
  ratio, rewrites `tunnel.json`

☐ Calibration status reads VERIFIED

```bash
python run.py --port /dev/ttyVFD table      # your Hz → RPM → m/s reference
```

---

# PHASE 12B — Rebuild the calibration from new data (when needed)

Phase 12 corrects the Hz→RPM link from one reading. If you instead collect a
**whole new RPM → velocity table** — which is what the clean sweep in
`reference/README.md` produces — rebuild the calibration from it rather than
patching the old one:

```bash
python run.py --port /dev/ttyVFD calibrate rpm_vs_velocity.csv \
    --rpm --nameplate-rpm 1750 --nameplate-hz 60
```

The CSV needs an `rpm` (or `hz`) column and a `velocity` column. An RPM table
also needs the nameplate values so slip can be corrected — use the **loaded**
speed, e.g. 1750 rpm at 60 Hz, not the 1800 rpm synchronous figure. Using 1800
bakes a systematic 3% error into every velocity you ever command.

☐ Fit reports R² above 0.998 — below that suspect settling time, a blocked
  probe, or a transcription error rather than real physics
☐ Saved to `tunnel.json`; `run.py table` reflects the new numbers

Fitting is linear by default, which is what fan affinity laws predict. Only
raise `--order` if the residuals genuinely demand it — see
`src/fit_sensor.py` for why the functional form matters more than the
coefficients.

---

# PHASE 13 — Characterize (measure τ)

```bash
python run.py --port /dev/ttyVFD characterize --base 20 --step 10
```

☐ Records τ to `tunnel.json` automatically
☐ **Write down τ and the corner frequency.** These two numbers determine what
  the whole project can promise.

Then measure the falling constant, which is the one that actually limits a
symmetric gust:

```bash
python run.py --port /dev/ttyVFD characterize --base 30 --step -10
```

☐ Add it as `tau_down` in `tunnel.json`

Optional but worth it:

```bash
python run.py --port /dev/ttyVFD freqresp
```

☐ Record the −3 dB bandwidth

---

# PHASE 14 — Tune the ramps

If `characterize` says the drive ramp dominates (accel ≫ 3τ), shortening it
buys real bandwidth — more than the feedforward math does.

Halve `2202`, re-run `characterize`, watch peak current in the log. Repeat
until current approaches the drive's 46.2 A rating, then back off.

**Deceleration is harder.** A slowing fan is a generator; without a brake
chopper its energy goes into the DC bus until the drive trips on overvoltage.
Par `2005` OVERVOLT CTRL will silently stretch your ramp to avoid tripping — so
a commanded fast decel may simply not happen, with no error anywhere.

☐ `2202` / `2203` recorded in `tunnel.json`
☐ Soft `hz_limit` set (default **2400 rpm** — the key is legacy, the
  value is rpm; full scale is 2435)

---

# PHASE 15 — Run experiments

### Every session

```bash
python run.py --port /dev/ttyVFD ambient --temperature 21.5 --pressure 101100
```

Density scales dynamic pressure and every force with it. It cannot be
reconstructed afterwards.

### Rehearse before committing a session

```bash
python run.py --port SIM --dry-run gust 1mc --mean 15 --amp 5 --length 25 --units mps
```

Real timing, no hardware. Find the typo on the bench.

### Interactive

```bash
python run.py --port /dev/ttyVFD live --units mps
```

```
tunnel> 12       armed at 20.0 Hz · 583 rpm · 12.0 m/s
tunnel> go
tunnel> 18       → 29.7 Hz · 866 rpm · 18.0 m/s
tunnel> +2
tunnel> ?        measured 31.4 Hz · 916 rpm · 19.1 m/s · 22.3 A
tunnel> stop
tunnel> quit
```

### Preprogrammed plan

```csv
time_s,mps
0,10
30,10
40,20
90,20
100,12
```

```bash
python run.py --port /dev/ttyVFD csv myplan.csv --repeat 3
```

Column may be `hz`, `rpm`, `mps`, or `mph`. Interpolation between breakpoints
is **linear** — for a smooth gust use `gust 1mc` instead.

### Gusts

```bash
python run.py --port /dev/ttyVFD gust 1mc --mean 15 --amp 5 --length 25 --units mps --repeat 3
python run.py --port /dev/ttyVFD gust 1mc --mean 30 --amp 8 --length 10 --feedforward
```

**Set `--settle` to at least 4τ.** Shorter and the profile starts mid-spin-up,
which produces impossible statistics and wastes the run.

Feedforward pre-compensates for the tunnel lag. Below ~6 s it starts degrading
tracking — trust the RMS number it prints, not the amplitude number.

### Turbulence

```bash
python run.py --port /dev/ttyVFD turbulence --mean 15 --sigma 2 --duration 180 --seed 42 --units mps
```

☐ **Record the seed.** Same seed = same realization, which is what makes runs
  comparable and lets Tim drive his CFD with the identical input.

### Sweeps

```bash
python run.py --port /dev/ttyVFD sweep 10 55 5 --settle 25 --dwell 15
```

### Afterwards

```bash
python analyze.py logs/*.csv --plot
python analyze.py logs/*.csv --summary
```

Fits τ from every run and overlays commanded vs measured as a PNG. Flags runs
that started unsettled.

---

# Standing rules

- **The E-stop stays hardwired.** Nothing in this package is in the safety
  chain, and nothing in it should ever become part of one.
- The comm watchdog (`3018`/`3019`) stays enabled.
- Nobody in the test section or diffuser during an automated run. A script
  stepping setpoints gives no audible warning before it ramps.
- `write_param()` is persistent — same as editing on the keypad, no undo.
- Don't loop on `reset_fault()`. A drive that faults repeatedly is protecting
  itself from something real. Read par `0401` and find out what.

# Rollback

Restore the Phase 1 values — chiefly `1001`, `1103`, `1002`, `1106`, `1102` —
and set `9802` back. The physical wiring can stay; it does nothing unless
`9802` selects Modbus.
