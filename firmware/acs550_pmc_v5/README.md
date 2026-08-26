# acs550_pmc_v5 — rotor rpm from a magnet and a reed switch

**v5 only adds.** The Modbus loop, both watchdogs, the control-word handshake,
RD/WR and every existing telemetry field are byte-identical to v3, which is
untouched at `firmware/acs550_pmc_v3/`.

**Numbered 5, not 4.** `acs550_pmc_v4/` published *fan* rpm to a separate DAQ
and is abandoned now that rotor rpm comes in here instead. It was never
flashed — but a version number is a promise. If a board ever answers `ID` with
`4.0`, that must mean exactly one thing forever.

## Wiring — two wires, and there is no wrong way round

Sensor: **DIGITEN VJ12-D10K**, a 2-wire **dry contact** (reed switch). One
magnet on one blade, so **one pulse per revolution**. No supply, no polarity.

```
reed wire A  ────────▶  PMC   ENC0 A   (PJ_8, on the encoder connector)
reed wire B  ────────▶  PMC   GND
```

The pin is `INPUT_PULLUP`; the contact just shorts it to ground.

### Not AI0

| rotor rpm | magnet in front of the sensor for |
|---:|---:|
| 1200 | 783 µs |
| 2400 | **392 µs** |
| 3600 | **261 µs** |

The analog inputs are an **ADC behind SPI** — one `read()` is a blocking
transaction of order a millisecond. Polling that would drop pulses, worst at
high speed, which biases rotor rpm **low exactly where the rotor makes most
power**. And it would fail silently.

`PJ_8` is a real MCU pin (`pins_mc.h`, `MC_ENC_0A_PIN`), so a hardware
interrupt catches the edge regardless of what the Modbus loop is doing.

The eight "digital inputs" are no good either — `ProgrammableDINClass` extends
`ArduinoIOExpanderClass`, so they sit behind an I²C expander.

### Worth adding, not required

A **4.7 kΩ pull-up to 3V3** and **10 nF to GND** at the PMC end, with the run
in shielded twisted pair. The internal pull-up is ~40 kΩ — a high-impedance
node next to a 15 HP motor and a VFD. The firmware debounces either way; the
resistor just means fewer rejected edges to explain later.

## Prove the wiring by hand, before the tunnel

```
RPM?  →  OK RPM <pulses> <last_us> <rpm> <pin> <rejected>
```

`pin` is the **live input level**. With the tunnel off, pass the magnet across
the sensor and watch it read `1` → `0`. That proves the whole path — sensor,
cable, connector, pin config — with nothing spinning.

Then spin the rotor by hand: `pulses` must advance by exactly one per
revolution. If it jumps by two or three, the reed is bouncing past the 2 ms
debounce and `rejected` will be climbing.

## What this sensor may not be able to do

The ZX-5H counter it ships with is rated **"20 Hz, or 20 times/s"** — at one
pulse per revolution, **1200 rpm**. We bypass that counter, but the reed's own
limit is undocumented and 20 Hz is the only number in the box.

The rotor is expected to reach **50–75 Hz** at the top of the wind range. That
is inside what a healthy reed manages and outside what its packaging claims.
**It must be validated, not assumed.**

The validation is free and exact. Open-circuit voltage is proportional to rotor
speed through the generator constant, so

```
K = rotor_rpm / V_oc
```

must be **constant** across the wind range. If the reed starts missing pulses
at speed, K droops at high wind while V_oc keeps climbing. A drooping K is the
signature of a sensor running out of bandwidth and cannot be mistaken for
anything aerodynamic.

Bounce is the opposite failure — a reed rings for a few hundred microseconds
on closing, which would count several times per pass and read **high**.
`RPM_MIN_GAP_US` rejects edges closer than 2 ms (a 30,000 rpm ceiling: far
above anything real, far below the bounce). Rejected edges are counted and
reported, so a chattering sensor says so instead of inflating the answer.

## Telemetry

Three fields **appended**, so a v2/v3 host truncates rather than misparses:

```
T,…,<errs>,<rpm_pulses>,<rpm_last_us>,<rotor_rpm>
```

`rpm_pulses` and `rpm_last_us` are **the record**. `rotor_rpm` is the PMC's own
single-interval estimate — jittery at one pulse per revolution, for a human
watching a terminal.

Anything recorded differences the other two:

```
rotor_rpm = 60e6 × (pulses₂ − pulses₁) / (last_us₂ − last_us₁)
```

That is exactly that many whole revolutions over exactly the time they took,
timed by the PMC rather than the host's scheduler. Both are unsigned and wrap
correctly through the 71-minute `micros()` rollover.

## ⚠️ 5.0 faulted the drive. 5.1 is the fix — verify it before trusting it.

Flashing 5.0 made the ACS550 trip repeatedly; reflashing v3 cleared it. That
was this firmware's fault, not the drive's, and there were two causes:

**`mbed::InterruptIn` was a global.** On an mbed core a global peripheral
object runs its constructor during static init, before the RTOS is up, and
`InterruptIn` touches GPIO and the NVIC. The board hung, the Modbus loop
stopped, and the drive's comm watchdog tripped it 3 s later **exactly as
designed**. The symptom pointed at the drive and had nothing to do with it.
5.1 constructs it inside `setup()`.

**A floating input next to a VFD is an antenna.** With nothing wired, PJ_8
sits on a ~40 kΩ internal pull-up beside a 15 HP motor. An edge storm re-enters
the ISR faster than the main loop can run and starves the Modbus poll — the
same silence, the same fault, a different cause. 5.1 counts its own edge rate
and **detaches the interrupt above 500/s** (30,000 rpm — far above anything
real). `RPM?` then reports `STORM-DETACHED`. Detaching is recoverable and
visible; a starved Modbus loop is neither.

Also removed: `__disable_irq()` around the counter read. Masking every
interrupt on a board whose real job is a half-duplex serial link is a bad
trade for four words of consistency — it can only cost a UART byte, and enough
CRC failures is a comm fault. The read is now lock-free.

### Verify 5.1 with the fan stopped

Nothing below turns anything.

1. **Wire the reed first.** A connected dry contact holds the pin at a defined
   level; an unwired pin is the antenna described above.
2. Flash 5.1, then poll for a couple of minutes with the drive powered but
   **not running**:

   ```bash
   python src/wait_for_pmc.py
   ```

   `ID` must answer `acs550-pmc 5.1 RD/WR RPM` every time. If replies stop, or
   `RPM?` says `STORM-DETACHED`, the input is still noisy — add the 4.7 kΩ
   pull-up and the 10 nF, and check the shield is landed at one end only.
3. Watch the drive keypad for two minutes. **No fault means the Modbus loop is
   being serviced.** That is the whole test.
4. Only then start the fan.

## Build and flash

```bash
arduino-cli compile --fqbn arduino:mbed_portenta:envie_m7 firmware/acs550_pmc_v5/
arduino-cli upload  --fqbn arduino:mbed_portenta:envie_m7 -p <port> firmware/acs550_pmc_v5/
```

Verified compiling against `Arduino_PortentaMachineControl` 1.0.5 — a 208,932
byte binary.

**Stop the dashboard first.** It holds the serial port, and only one process
can.
