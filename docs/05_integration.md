# Integrating the PMC and the Electrical Load

Three design threads produced this rig in separate conversations, and they do
not entirely agree. This document reconciles them and records what still has to
be decided.

## The rig

```
Browser ──HTTP──► Pi ──USB──► PMC ──RS-485──► ACS550 ──► fan ──► wind
                   │                                              │
                   └──USB/LAN──► Chroma 63004 ◄──power── turbine ◄┘
                                                        │
                                                  DAQ ◄─┘  RPM, aero
```

| Box | Owns | Trusted with safety? |
|---|---|---|
| **Pi** | orchestration, Flask, logging | no |
| **PMC** | the Modbus loop, both watchdogs | **yes** |
| **ACS550** | wind speed | yes — its own comm watchdog |
| **Chroma** | the turbine's operating point, and the best V/I measurement | no |
| **DAQ** | turbine RPM, aero | no |

---

## Conflict 1 — two Modbus masters  ⚠ SAFETY

This package was written assuming an FTDI USB-RS485 cable from the host,
landed on X1-29/30/31, with pymodbus as the master. The PMC thread lands the
**Portenta** on those same three terminals with its own master.

Modbus RTU has exactly one master. Both wired is not a degraded mode — it is
two independent processes commanding a 15 HP fan, neither aware of the other,
and neither log showing what the other did.

**Only one device gets X1-29/30/31.**

`src/transport.py` makes this a configuration choice rather than a rewrite:

```json
"transport": {"kind": "pmc",    "port": "/dev/ttyACM0"}
"transport": {"kind": "direct", "port": "/dev/ttyVFD", "parity": "N"}
```

Everything above the transport — gusts, profiles, sweeps, the dashboard — works
over either.

**Recommendation: PMC for the real rig, direct for commissioning.** The PMC's
Modbus loop is real-time and a Linux host's is not; under load the Pi can stall
long enough to miss keep-alives. It also adds a second watchdog layer — the
drive stops if the PMC goes quiet, and the PMC stops the fan if the *host* goes
quiet. The direct path has only the first. But direct has one less thing
between you and the drive when you are working out why it will not answer,
which is what phases 8–14 of the playbook are for.

---

## Conflict 2 — parity

| Source | Says |
|---|---|
| PMC sketch | 19200, **even** parity, 1 stop |
| This package (`10_commissioning.md` phase 6, CLI default) | 19200, **8N1** |

Follow both and you get silence with `5308` UART errors climbing. Either works.
They have to agree, and right now the two documents do not.

**Decide, set parameter `5304` to match, and record it in `tunnel.json`** so the
next person does not rediscover it from first principles.

---

## Conflict 3 — where the watchdog lives

This package runs a host keep-alive thread feeding the drive's `3018`/`3019`.
The PMC design has the PMC doing that, plus its own host watchdog.

Over the PMC transport, `ACS550.start_keepalive()` is a **no-op**. Running both
means two things writing the control word — the same class of problem as two
masters, in software rather than on the wire.

The PMC's host watchdog (`WD <ms>`) replaces it. The host still has to talk,
just at its own pace rather than to a hard deadline.

---

## Conflict 4 — the interlock nobody owned

**With the load off, the turbine sees an open circuit and runs away.**

A Chroma in the off state presents hundreds of kΩ. An unloaded turbine in
moving air accelerates until something mechanical stops it — a bearing, a blade
root, or the blade leaving the hub. On a printed SLA rotor that is an outcome,
not a hypothetical.

```
        load ON  →  wind UP  →  test  →  wind DOWN  →  load OFF
```

Never the reverse at either end. Neither the drive code nor the load code can
enforce this alone — neither can see the other — so it lives in
`src/chroma_load.py::TurbineInterlock`:

- `wind_up()` refuses if the load is off
- `set_hz()` refuses if the load went off mid-run
- `safe_shutdown()` unwinds fan-then-load even from an exception
- **if the fan cannot be confirmed stopped, the load stays on.** Leaving a load
  energised is a nuisance; leaving a spinning turbine open-circuit breaks
  hardware.

`verify_loaded()` checks measured current against a floor rather than trusting
`LOAD ON`. A load enabled at zero amps is electrically almost the same as off,
and the instrument will happily report itself enabled either way.

---

## What this changes about the experiment

The tunnel work so far assumed a 1-D sweep: step wind speed, measure. The
turbine work is **2-D** — wind speed × electrical load — and the output is a
Cp(λ) surface, not a velocity series.

```
    for each wind speed V:
        for each load setpoint:
            settle, measure V_turbine, I, RPM
            λ  = ωR / V
            Cp = P_elec / (½ ρ A V³)
```

Two consequences worth deciding before writing the sweep:

**CC or CR? — decided: CR.** Not because CC is unstable in general, but
because of *where* it is unstable. Above peak λ, CC is fine: slowing moves the
rotor toward the Cp peak, aero torque rises, it recovers. Below peak λ the sign
flips — slowing moves away from the peak, aero torque falls, and with the
current pinned there is nothing to arrest the collapse. A Cp sweep has to go
below peak λ, because that is where the peak and the far side of the curve are.
CR is self-correcting on both sides, and it is what a physical resistor bank
does anyway.

Constant *power* is never used: commanding fixed power from a source whose
available power you are measuring is the CC failure with the accelerator held
down.

**Whose V and I?** The Chroma's, with remote sense at the rectifier output. Its
readings beat the DAQ's, and in CR mode the load *regulates* on sense, so bad
sense means it controls to the wrong thing rather than merely reporting wrong.
Keep the DAQ channels as a cross-check, not as the primary.

---

## Still to build

- [ ] **turbine.py** (not yet written) — the 2-D Cp(λ) sweep, using the interlock
- [ ] PMC protocol extension for parameter reads, or accept that commissioning
      happens over the direct transport
- [ ] Decide CC vs CR, and the stall-detection rule that ends a load sweep
- [ ] Dashboard: load state, turbine power, live Cp(λ)
