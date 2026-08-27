# acs550_pmc_v5 — rotor rpm from a magnet and a reed

**Current version: 5.7.** Adds rotor-speed counting to v3. The Modbus loop,
both watchdogs, the control-word handshake and RD/WR are unchanged; v2 and v3
remain byte-identical at `../acs550_pmc/` and `../acs550_pmc_v3/`.

Numbered 5, not 4 — [`../acs550_pmc_v4/`](../acs550_pmc_v4/) is abandoned and
its number is retired.

---

## ⚠️ Status: counts reliably, but the reed bounces

**Measured 26 Aug.** Counter zeroed, rotor turned **exactly 10 revolutions
slowly by hand**:

```
raw counts   0  3  5  8  10  13  15  18  21  24  27  28
increments      3  2  3  2   3   2   3   3   3   3   1
                          28 counts / 10 revolutions = 2.8
```

**The count per pass varies between 2 and 3.** A fixed ratio would be
correctable; a varying one is not. Rotor rpm carries roughly ±20% scatter
against a blade effect of 13.7% — the noise would exceed the signal.

It is not a speed problem: the rotor was turned *slowly, by hand*.

**Until this is fixed, `turbine_rpm` is not trustworthy.** Everything else on
this page works.

### The fix

**A capacitor from `Z0` to `GND`.** Start **0.1 µF**, then 0.22, then 0.47.
Re-run the ten-revolution test after each and stop when it reads 10.

⚠️ **1 µF is likely too slow** — if Z0's pull-up is ~10 kΩ that is a 10 ms time
constant against a 15 ms magnet period at 60 rev/s. Passes would smear.

If no value works, the VJ12-D10K is the wrong part: it is a mechanical reed
rated **20 Hz by its own packaging**, and this rotor needs 50–70 Hz. A
Hall-effect sensor has no contacts to bounce.

---

## Wiring — two wires, no polarity

Sensor: **DIGITEN VJ12-D10K**, a 2-wire dry contact. One magnet on one blade,
so **one pulse per revolution**. No supply. Blue and brown are interchangeable.

```
sensor  ────▶  PMC  ENC0  Z0     (encoder 0 INDEX, on the ENCODERS block)
sensor  ────▶  PMC  ENC0  GND
```

**That is the whole wiring.** No pull-up resistor, no strap — verified: `RPM?`
reports `st=3` at rest, meaning the PMC biases both encoder inputs high
internally. An earlier version of this page demanded a 4.7 kΩ pull-up and a
strap on B; the board says otherwise.

### Not `A0`, and not `AI0`

**`A0` cannot work.** `QEI::setEncoding()` attaches the channel-A interrupt but
never assigns `encoding_`, so it keeps its constructor default of
`X2_ENCODING`. X2 only counts transitions `0x3↔0x0` and `0x2↔0x1` — both
channels moving together, a real quadrature pair. A single reed with B high
gives `0x3 → 0x1 → 0x3`, matching neither, so `getPulses()` can never move
however A0 is wired. An hour was spent chasing a wiring fault that did not
exist.

The index channel has no such logic. `QEI::index()` is one line —
`revolutions_++` — attached unconditionally in the constructor.

**`AI0` cannot work either.** The analog inputs are an ADC behind SPI, one
blocking read of order a millisecond, and the magnet is in front of the sensor
for 392 µs at 2400 rpm. Dropped pulses would bias rpm low worst at high speed,
silently.

---

## Commands

```
RPM?              OK RPM <pulses> <last_us> <rpm> <raw> st=<n> <rejected> <reversals>
RPMGAP <us>       debounce window, 200–50000, default 5000 (12,000 rpm ceiling)
RPMZERO           zero the counter and the encoder
```

`st` is QEI's 2-bit view of the pins, `(A<<1)|B`:

| st | A | B | |
|---:|---:|---:|---|
| **3** | 1 | 1 | ✅ expected at rest |
| 1 | 0 | 1 | A held low — reed closed, or shorted |
| 0 | 0 | 0 | neither biased; nothing can be detected |

### Prove the wiring with the tunnel off

```bash
python src/run.py raw RPMZERO
#  turn the rotor by hand
python src/run.py raw RPM?
```

`pulses` must advance. `reversals` must stay 0.

---

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

Exactly that many whole revolutions over exactly the time they took, on the
PMC's clock rather than the host's scheduler. Both unsigned, and they wrap
correctly through the 71-minute `micros()` rollover.

---

## Why the debounce cannot be fixed in firmware

`rpmSample()` polls `getRevolutions()` from `loop()`, because QEI owns the
interrupt and hooking it directly is the double-claim that hung 5.0 and 5.1. So
the debounce can only gate observed **changes**, never individual edges — when
several bounces land between two polls they arrive as one increment of several.

Sweeping `RPMGAP` from 2 ms to 25 ms confirmed it: accepted rate wandered
48–89/s with no plateau, while the raw rate sat stable at ~148/s. **That is why
the fix is a capacitor and not a constant.**

---

## Version history — three ways to hang this board

| | |
|---|---|
| **5.0** | `mbed::InterruptIn` at **global scope**. On an mbed core that constructor runs during static init, before the RTOS, while touching GPIO and the NVIC. Board hung → Modbus stopped → drive tripped on par 3018/3019 after 3 s. Read as "the VFD keeps faulting" and was nothing to do with the drive. |
| **5.1** | Moved it into `setup()`, added an edge-storm guard, dropped `__disable_irq`. All real improvements, none of them the cause. Hung identically. |
| **5.2** | Root cause: `Arduino_PortentaMachineControl.h` declares `extern EncoderClass MachineControl_Encoders`, a **global whose QEI constructor already claims PJ_8, PH_12 and PH_11**. It is present in v3 too — which is why v3 works: v3 never touches those pins. Fixed by using the encoder instead of fighting it. |
| **5.3** | Tried `pin_mode()` on a QEI-owned pin to spare two external components. Hung the board again. **Any access to those pins beyond `getRevolutions()` is fatal.** |
| **5.4** | 5.2's logic restored. Verified alive: 15/15 replies over 45 s, `comm_errs=0`. |
| **5.5** | Added `st=` so the pins can be read without a meter. |
| **5.6** | Switched `getPulses` → `getRevolutions` after finding the `setEncoding` bug. **Counted immediately.** |
| **5.7** | `RPMGAP` and `RPMZERO`, so the debounce can be tuned and the counter cleared without a reflash. |

**Every reflash trips the drive.** A DFU reset silences Modbus for longer than
par 3019, so the comm watchdog fires. Expect it, and clear it at the keypad —
Modbus cannot clear a fault about the Modbus link.

---

## Build and flash

```bash
arduino-cli compile --fqbn arduino:mbed_portenta:envie_m7 firmware/acs550_pmc_v5/
arduino-cli upload  --fqbn arduino:mbed_portenta:envie_m7 -p <port> firmware/acs550_pmc_v5/
```

Built against `Arduino_PortentaMachineControl` 1.0.5.

**Stop the dashboard first** — it holds the serial port, and only one process
can. If upload reports `No DFU capable USB device`, **double-tap the Portenta's
RESET** (the green LED fades slowly in and out) and run it again; a hung sketch
cannot perform the 1200-baud touch reset itself.

### After flashing, before running the fan

```bash
python src/wait_for_pmc.py
```

`ID` must answer `acs550-pmc 5.7 RD/WR RPM`. Then **watch the drive keypad for
two minutes.** No fault means the Modbus loop is being serviced. That is the
whole test, it costs no tunnel time, and three revisions of this firmware would
have been caught by it.
