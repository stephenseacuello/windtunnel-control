# acs550-pmc 3.0 — parameter access

**The original sketch is untouched at `firmware/acs550_pmc/`.** This is a
separate sketch; flash whichever you want and the other is still there.

## What changed from 2.0

Four verbs, and nothing else. The Modbus loop, both watchdogs, the control
word handshake and the telemetry format are byte-for-byte the original.

```
RD <par>              read any parameter        -> OK RD 1105 2435
WR <par> <value>      write one                 -> OK WR 2202 300 -> 300
UNLOCK                enable writes for 120 s   -> OK UNLOCK ...
LOCK                  disable them now
```

## Why the refusals live here and not in the host

A host-side allowlist can be copied, edited in a hurry, and applied by
somebody who did not read it. Firmware cannot be talked out of a refusal.

Three groups are refused at any time, with no override:

| Refused | Why |
|---|---|
| **group 53** (5302–5399) | The serial settings of the very link the command arrives on. Write parity wrong and the link dies mid-write — and group 53 is read at boot only, so it surfaces at the next power cycle on a drive that can then only be reached by keypad. |
| **3018 / 3019** | The comm-loss watchdog. This is the mechanism that makes a laptop commanding a 15 HP fan acceptable, and it is exactly what somebody disables "just for testing". |
| **group 99** (9900–9999) | The motor model. A wrong nominal current disables the drive's thermal protection: hardware damage, not bad data. |
| **groups 01–04** | Read-only operating data and fault history. |

Set those from the keypad, deliberately, with the manual open.

Everything else needs `UNLOCK` first. The unlock lapses after 120 s **and on
any RUN** — arming and firing should not be the same session. Writes are also
refused outright while the fan is turning.

## Every write is read back

A drive clamps an out-of-range value silently and refuses some parameters
while running; both look like success on the wire. `WR` therefore reports
`before -> after` from the drive itself, and prints a `# WARNING` line if
what it holds is not what you asked for.

## Flashing

Arduino IDE, board = Portenta H7 / Machine Control. Same libraries as 2.0:
`Arduino_PortentaMachineControl`, `ArduinoRS485`, `ArduinoModbus`.

Confirm afterwards:

```
ID          -> OK ID acs550-pmc 3.0 RD/WR
RD 1105     -> OK RD 1105 2435
```

**Then re-run the watchdog test** — pull the USB mid-run and confirm the fan
ramps down. Any change to this firmware invalidates that evidence.

## Host side

`PMCTransport` probes for RD at connect and falls back to the 2.0 behaviour
if it is absent, so an un-flashed PMC keeps working. See
`src/drive_profile.py` for snapshot / diff / apply.


## Capturing an existing configuration

`RD` is what makes a baseline possible. Two ways to take one:

```bash
# 31 parameters this package reasons about — a second
python src/drive_profile.py snapshot --name baseline --note "as found"

# every parameter that exists on the drive — ~2,200 round trips, minutes
python src/drive_profile.py scan --name aerolab_asfound
python src/drive_profile.py scan --all          # every group, not just ours
```

A scan asks for each candidate in turn and keeps whatever answers, because a
drive errors on parameters its build does not have. That is slower than a
curated list and it is the only way to capture a configuration **you did not
write** — which is exactly what somebody else's commissioning is.

Then turn it into a reusable profile:

```bash
python src/drive_profile.py promote --snapshot 20260824_..._aerolab_asfound.json \
       --name aerolab --description "Aerolab's original configuration"
python src/drive_profile.py diff --profile aerolab
```

`promote` drops the parameters the firmware will never write, so a diff
against the result does not fill with rows that could never be actioned.
Pass `--include-refused` to keep them for the record.

All of this is in the dashboard too, under **Parameters**.
