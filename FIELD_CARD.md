# FIELD CARD — Aerolab Wind Tunnel

*Print this. Take it to the tunnel. Everything else lives on a screen.*

ACS550-U1-046A-2 · 15 HP · 208–240 V 3PH · S/N 2121803289

---

## BEFORE THE COVER COMES OFF

```
☐  Disconnect open, LOCKED and TAGGED
☐  Wait 5 MINUTES — DC bus capacitors hold a lethal charge
☐  Verify dead at U1/V1/W1 with a meter proven on a live source
☐  Terminals 19–27 can be live from an external source even with the drive dead
```

**Cover:** loosen the captive screw at the **top**, pull near the top. Keypad
comes off first.

---

## RS-485 → X1   (PMC or FTDI — **never both**)

| Wire | Combine | Terminal |
|---|---|---|
| **Orange** Data+ | with **Green** (Term 2) | one ferrule → **29** |
| **Yellow** Data− | with **Brown** (Term 1) | one ferrule → **30** |
| **Black** GND | — | **31** |
| **Red** +5 V | — | **TAPE OFF** |

```
☐  RS485 BUS TERMINATION DIP → ON  (red block left of terminal 28;
     photographed OFF as found)
☐  28 and 32 stay EMPTY
☐  Own knockout, ≥8 in from power/motor, cross at 90°
☐  Tug-test everything · no stray strands
```

**No answer later? Swap 29 and 30 first.**

**X1 was photographed EMPTY** — no Aerolab wiring to work around. Manual control
is the keypad, via LOC/REM, and it keeps working.

---

## BEFORE RE-ENERGIZING

```
☐  No tools, screws or offcuts inside
☐  Cover on, captive screw tight, keypad in, gland box closed
☐  AEROLAB START SWITCH OFF ← the drive auto-starts if a run command is present
```

---

## PARAMETERS

| Par | Set to | | Par | Set to |
|---|---|---|---|---|
| `9802` | 1 STD MODBUS | | `5310` | 103 |
| `5302` | 1 | | `5311` | 104 |
| `5303` | 19.2 | | `3018` | 1 FAULT |
| `5304` | **8E1** | | `3019` | 3.0 s |
| `5305` | 0 | | | |

```
☐  POWER-CYCLE THE DRIVE  ← group 53 reads at boot only
```

**Only after `monitor` and `selftest` pass:**

```
☐  1103 = 8   (REF1 SELECT = COMM)
☐  1001 = 10  (EXT1 COMMANDS = COMM)
☐  Sign on the tunnel — the local pot and start button are now dead
```

---

## COMMANDS

```bash
python run.py --port /dev/ttyVFD monitor      # read-only, fan cannot move
python run.py --port /dev/ttyVFD selftest     # read-only, checks assumptions
python run.py --port /dev/ttyVFD jog 10       # first motion
python run.py --port /dev/ttyVFD verify --hz 30
python run.py --port /dev/ttyVFD characterize --base 20 --step 10
python run.py --port /dev/ttyVFD table        # Hz → RPM → m/s
python run.py --port /dev/ttyVFD calibrate t.csv --rpm --nameplate-rpm 1750

python scripts/rpm.py                         # just spin it
```

---

## WIND SPEED  ·  v = 0.02132 × RPM − 0.424

| Hz | RPM | m/s | | Hz | RPM | m/s |
|---:|---:|---:|---|---:|---:|---:|
| 200 | 3.8 | | 1400 | 29.4 |
| 600 | 12.4 | | 1800 | 38.0 |
| 1000 | 20.9 | | 2400 | 50.7 |

*±10% until `verify` is run once. The shape is right; only the scale is open.*

---

## IF THE BUS IS SILENT

```
1.  Swap X1-29 / X1-30
2.  --unit --baud --parity vs par 5302 / 5303 / 5304
3.  Did you power-cycle?
4.  Keypad counters:
      5306 climbing → frames OK, problem is PC side
      5307 climbing → noise / termination / baud
      5308 climbing → parity / framing
      all zero      → nothing arriving, back to 1
```

---

## THE TEST THAT MATTERS

```
☐  Start the fan, then PULL THE USB CABLE
☐  The drive must fault and stop within ~3 s
```

If it doesn't, `3018`/`3019` are wrong. Fix that before anything runs
unattended — that watchdog is the entire reason it's acceptable to command a
15 HP fan from a Pi.

---

## STANDING RULES

- **The hardwired E-stop is the safety device.** Nothing in software is, and
  nothing in software should ever become one.
- Comm watchdog `3018`/`3019` stays enabled.
- **No UPS on the Pi.** If it loses power you want it to die hard, so the
  watchdog stops the fan.
- Nobody in the test section or diffuser during an automated run — a script
  stepping setpoints gives no warning before it ramps.
- Parameter writes are persistent. Same as the keypad. No undo.
- Don't loop on fault reset. Read `0401` and find out why.

---

## PARAMETER ACCESS  (PMC firmware 3.0+)

    RD 1105                 read any parameter
    WR 2202 300             write one — needs UNLOCK first
    UNLOCK                  enables writes for 120 s, lapses on RUN

    python src/drive_profile.py snapshot --name baseline
    python src/drive_profile.py diff --profile windturbine_rs485

REFUSED BY FIRMWARE, ALWAYS — set these on the keypad:
    group 53 (5302-5399)    serial config of the link you are talking over
    3018 / 3019             the comm-loss watchdog
    group 99                the motor model
    groups 01-04            read-only

---

## EVERY SESSION

```
☐  Session: operator · test-section configuration · notes
☐  Ambient: temperature and pressure  ← cannot be reconstructed later
☐  --settle at least 4τ
☐  Record the seed for turbulence
```
