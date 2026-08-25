# acs550_pmc_v4 — fan speed out to the DAQ

**v4 only adds.** The Modbus loop, both watchdogs, the control-word handshake,
RD/WR and every existing telemetry field are byte-identical to v3. Earlier
sketches are untouched at `firmware/acs550_pmc/` (v2) and
`firmware/acs550_pmc_v3/` (v3).

## Why

Jeong's DAQ already records **rotor** rpm from a proximity sensor on the rig.
It does not record **fan** rpm, which exists only inside the PMC. So the two
halves of every experiment live in two files with no common clock, and lining
them up afterwards is guesswork.

One wire fixes it.

## Wiring

```
PMC  O0    (first of the four ANALOG OUT screw terminals)  ──▶  DAQ AI+
PMC  GND   (the one beside that block)                     ──▶  DAQ AGND
```

Twisted pair, ferrules both ends. Route away from the motor leads — they are
the noisiest thing in the room and this is a millivolt-resolution signal. Land
the ground on the DAQ's **analog** ground, not chassis.

## The scale — live zero

```
volts = 0.5 + rpm / 300        a valid reading
volts = 0.000                  INVALID — do not trust this segment
```

| rpm | volts |
|---:|---:|
| 0 | 0.50 |
| 600 | 2.50 |
| 1200 | 4.50 |
| 2435 (par 1105 max) | 8.62 |

The 0.5 V offset is the trick 4–20 mA uses. Without it a stopped fan, a pulled
wire, a dead PMC and a failed Modbus read all produce 0 V and are
indistinguishable in the file. With it, **0 V means exactly one thing**.

That distinction is the point. Everything on this rig that has ever gone wrong
produced plausible numbers first; a stale fan speed held through a comm dropout
would look like a perfectly good run.

**The scale is recorded in `data/tunnel.json`.** Change it in firmware and you
must change it there in the same commit — the DAQ records volts and nothing
else.

## Where the rpm comes from

Par **0102 SPEED**, read directly — one extra FC3 per 100 ms cycle, about 10 ms
of bus time, and **no drive parameter change**.

Not derived from output frequency. Frequency cannot give rpm without knowing
slip, and assuming it can is the error that made feedback read 295 where the
drive was holding 300.

A failed 0102 read does **not** trip `COMM_LOST`. The control path is a
separate transaction and may be perfectly healthy; only the DAQ signal is
affected, and it says so itself by going to 0 V. Ramping down a running tunnel
because one telemetry read failed would be far worse than a gap in a log.

## New commands

```
AO?           OK AO 4.500 1200 valid scale=0.50+rpm/300
AOTEST <v>    force the output for 30 s — calibration only, refused while running
```

`AOTEST` is refused with the fan running: forcing the line mid-sweep would
write a lie into the DAQ record of a live experiment.

## Telemetry

Two fields **appended**, so a host written for v2/v3 truncates rather than
misparses:

```
T,…,<errs>,<act_rpm>,<ao_v>
```

`act_rpm` is `nan` when par 0102 could not be read.

## Build

```bash
arduino-cli compile --fqbn arduino:mbed_portenta:envie_m7 firmware/acs550_pmc_v4/
arduino-cli upload  --fqbn arduino:mbed_portenta:envie_m7 -p <port> firmware/acs550_pmc_v4/
```

Verified compiling against `Arduino_PortentaMachineControl` 1.0.5. Note the
older `Arduino_MachineControl` library spells the same calls
`analog_out.write()` / `period_ms()` — v4 uses the newer API, matching v3.

## Commissioning — before trusting a single DAQ file

1. `AO?` with the fan stopped → expect **0.50 V**, `valid`.
2. Meter across O0/GND. Reads 0.50 V? The wire and ferrules are good.
3. `AOTEST 4.5` → meter says 4.50 V, DAQ channel says 4.50 V. Both ends agree.
4. Run the fan to 1200 rpm → **4.50 V**, and `AO?` says `valid`.
5. Pull the PMC USB. The line must fall to **0.00 V**, not hold 4.50.

Step 5 is the one worth doing. It is the only proof the invalid path works, and
it is the path that protects every file you capture afterwards.
