# Troubleshooting

Organised by **what you observe**, not by what's broken — because when you're
standing at the tunnel you know the symptom and not the cause.

---


## Flashing the PMC

| Symptom | Cause | Fix |
|---|---|---|
| `No DFU capable USB device available` | A hung sketch cannot perform the 1200-baud touch reset itself | **Double-tap the Portenta's RESET** — green LED fades slowly in and out — then upload again |
| Board vanishes from USB entirely: no serial port, no DFU device | The touch reset fired but `dfu-util` missed the bootloader window | Unplug USB, wait 5 s, replug. Flash is untouched — the transfer never began. `python src/wait_for_pmc.py` reports what is actually on the board |
| **The drive faults right after a PMC flash** | Expected. A DFU reset silences Modbus for longer than par 3019, so the comm-loss watchdog fires — doing exactly its job | Clear at the ACS550 keypad. **Modbus cannot clear a fault about the Modbus link** |
| Port name changed after flashing | macOS derives it from USB topology and re-enumeration moves it. It has been 1101, 14401, 1202 and 1201 in one week | Python tools autodetect via `transport.resolve_port()`. `arduino-cli` needs the real name — `ls /dev/cu.usbmodem*` |

## The fan stops mid-run for no reason

The PMC's **host watchdog**. It ramps the fan down if nothing talks to it for
`watchdogMs` — this is the mechanism that makes commanding a 15 HP fan from a
laptop acceptable, and it is not optional.

Anything holding the fan at speed must send *something* every couple of
seconds. `blade_sweep.py` does this with `DriveWatch`; an ad-hoc script must do
it too, and a bare `time.sleep(3)` in a poll loop is enough to trip it.

## Every point reads 0.000 V

No wind, or the rotor is not turning. **Check the `fan_rpm_actual` column
before suspecting the load** — 0.000 V is perfectly stable, so a settle
routine watching voltage will declare a stopped tunnel settled and record
fourteen empty points without complaint.


## The drive doesn't answer at all

`monitor` times out. No status word, no readback.

Work through in this order. The first item fixes it most of the time.

**1. Swap the two ferrules between X1-29 and X1-30.**
A/B labelling is genuinely inconsistent across adapter manufacturers. This is
the single most common cause and costs thirty seconds to rule out.

**2. Confirm the settings match the drive.**

| Your flag | Drive parameter |
|---|---|
| `--unit` | `5302` EFB STATION ID |
| `--baud` | `5303` EFB BAUD RATE |
| `--parity` | `5304` EFB PARITY |

**3. Did you power-cycle after setting group 53?**
Parameters `9802` and everything in group 53 are read **only at boot**. This is
the second most common cause, and it sends people chasing wiring faults that
don't exist.

**4. Read the drive's own counters from the keypad.**
They work when Modbus doesn't, and they tell you which side of the cable the
problem is on — which halves the search space immediately.

| Parameter | Climbing means |
|---|---|
| `5306` EFB OK MESSAGES | Frames arriving and parsing. The problem is on the PC side — port name, permissions, driver. |
| `5307` EFB CRC ERRORS | Noise, missing termination, or a baud mismatch. Check J2 is ON and the cable isn't run alongside the motor leads. |
| `5308` EFB UART ERRORS | Parity or framing mismatch. Check `5304` against `--parity`. |
| all three frozen at zero | Nothing is physically arriving. Back to step 1. |

**5. On a Pi: is ModemManager eating the port?**
It sees a new USB serial device, assumes it's a cellular modem, and starts
firing AT commands at your VFD.

```bash
sudo systemctl disable --now ModemManager
```

**6. Permissions.**
`ls -l /dev/ttyVFD`, and confirm you're in `dialout`. The group change needs a
new login session to take effect — logging out and back in is not optional.

---

## Comms work, but the fan won't start

Writes succeed. Nothing turns.

**Check the status word first** — `selftest` decodes it, or watch `monitor`.

| Bit | Means |
|---|---|
| `TRIPPED` | Active fault. Read parameter `0401` and find out why **before** resetting. |
| `SWC_ON_INHIB` | Start inhibited. The drive wants to see OFF1 cycle low→high. `start()` handles this by passing through `0x047E`; if you're writing raw control words, that's your bug. |
| `REMOTE` clear | The drive is in **LOCAL keypad mode** and is ignoring the fieldbus — while your writes still report success. Press LOC/REM on the keypad. |

**Then check the control source.**

```
1001 EXT1 COMMANDS  must be 10 (COMM)
1103 REF1 SELECT    must be 8  (COMM)
```

If those still point at the Aerolab panel, the drive is working exactly as
configured — Modbus has no authority. That's phase 10 of the playbook, and
it's deliberately the last step.

**Also worth checking:** `1601` RUN ENABLE and `1608` START ENABLE 1. If
Aerolab wired an interlock into one of those digital inputs, the drive won't
run until it's made.

---

## The fan starts but goes to the wrong speed

**Off by exactly 10×** → parameter `1105` scaling. The code infers tenths from
the raw register value; if that guess is wrong, every commanded speed is wrong
by a factor of ten and *nothing errors*. Run `selftest` and confirm 1105
against the keypad.

**Off by a consistent percentage** → check that nothing has reintroduced an
Hz↔rpm conversion. The drive commands speed (par 1105 = 2435 rpm) and the
calibration is rpm→velocity directly. A stray conversion is the classic
cause of a consistent scale error, and it is silent.

**Speed is capped lower than expected** → check `hz_limit` in `tunnel.json`
(default **2400 rpm** — the key name is legacy, the value is rpm) and
parameter `2002` MAXIMUM SPEED.

---

## A run aborted partway

The log and its sidecar are on disk — the player flushes every sample, so
whatever completed survived. The sidecar's `aborted_reason` says why.

| Reason | What happened |
|---|---|
| `drive faulted at sample N` | A trip mid-run. Parameter `0401` has the code. |
| `lost comms at sample N` | The bus died. The run stopped rather than writing into the void. |
| `profile peaks at X Hz, above the limit` | Refused before starting — nothing ran. |
| `drive is in LOCAL keypad mode` | Someone pressed LOC/REM. |
| `aborted from the dashboard` | Someone hit Abort. |

---

## The gust came out smaller than I drew it

Almost always expected, and the tooling should have warned you.

The tunnel is a low-pass filter with a corner around 0.05 Hz. A 20-second
1-cosine retains ~86% of its amplitude; a 2-second one retains ~26%. Run the
preview — `check_realizable()` predicts this before you spend a session on it.

**To get more:**

1. **Lengthen the gust.** Free, and always works.
2. **Shorten parameter `2202`.** If `characterize` says the drive ramp
   dominates (accel ≫ 3τ), this buys more than the feedforward maths does.
3. **`--feedforward`.** Pre-distorts the command so the tunnel's lag smooths it
   into the shape you wanted. Below about 6 seconds it starts making tracking
   *worse* — trust the RMS number it prints, not the amplitude number.

**If you need real bandwidth**, the answer isn't the fan. Oscillating vanes
downstream give 1–20 Hz. See `docs/03_gusts.md` §5.

---

## `analyze.py` reports impossible numbers

**"Amplitude retained > 100%"** or a very poor fit → the run started before the
flow settled, so the record contains the tail of the spin-up. The tool detects
this, trims the transient, and tells you. Use `--settle` of at least **4τ**.

**"Poor fit, R² < 0.7"** → either a mid-run fault, or a profile with too little
excitation to identify from. A steady hold can't tell you τ.

---

## Closed-loop velocity behaves oddly

**"No healthy velocity source"** → a manual reading has gone stale (2 minutes),
or the DAQ/serial source is erroring. The loop refuses rather than integrating
against a frozen value, because a controller doing that winds the fan up until
something stops it while the reading looks plausible throughout.

**"NOT CONVERGED"** → the loop ended mid-approach. **Do not read the correction
as a calibration error** — it's a snapshot of an approach, not a measurement.
Run longer, or raise `ki`.

**It oscillates** → gains too aggressive for the plant. The default from
`suggest_gains` is deliberately slow: a controller tuned faster than a tunnel
with a several-second time constant doesn't make it faster, it makes it hunt.

---

## Dashboard problems

**"STREAM LOST"** → the server died or the network dropped. The browser
reconnects every 3 s. Check `journalctl -u windtunnel -f`.

**Can't reach it from another machine** → it binds to `127.0.0.1` on purpose.
Use an SSH tunnel:

```bash
ssh -L 5000:localhost:5000 pi@tunnel-pi
```

**τ is stale after running `characterize` from the CLI** → the dashboard loads
config once at startup. Hit **Reload config** in the rail. A stale τ silently
disables the bandwidth check on every profile built afterwards.

**Pre-flight blocks a run you want anyway** → the failure dialog offers an
explicit override. Warnings never block; only failures do.

---

## Disk full mid-run

The player flushes every sample by design so a crash at minute four doesn't
lose the first four minutes. The cost is that a full filesystem fails
*mid-profile*.

```bash
python src/archive_logs.py --older-than 30 --to ~/tunnel-archive --delete
```

It moves runs as complete sets and refuses to delete anything missing its
provenance sidecar.

---

## Rollback — putting the tunnel back as it was

Restore the values recorded in playbook phase 1, chiefly:

```
1001  EXT1 COMMANDS
1103  REF1 SELECT
1002  EXT2 COMMANDS
1106  REF2 SELECT
1102  EXT1/EXT2 SEL
9802  COMM PROT SEL
```

The physical RS-485 wiring can stay landed. It does nothing unless `9802`
selects Modbus.
