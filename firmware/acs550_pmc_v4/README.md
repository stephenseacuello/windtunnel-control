# ⛔ acs550_pmc_v4 — ABANDONED. DO NOT FLASH.

**This sketch is superseded by [`../acs550_pmc_v5/`](../acs550_pmc_v5/) and
must not be built onto the PMC.** There is deliberately no upload command on
this page.

It was written to publish **fan** rpm to Jeong's DAQ so the two labs' records
would share a clock. That problem no longer exists: the DAQ was removed and the
rotor's own speed sensor comes directly into the PMC instead.

It was never flashed. The version number is retired permanently — if a board
ever answers `ID` with `4.0`, that must mean exactly one thing forever.

> **Why this warning is at the top.** It used to be at line 113, under 110
> lines that read as live build-and-commission instructions including a working
> `arduino-cli upload`. Anyone skimming would have flashed it. A retraction
> that arrives after the instructions is not a retraction.

---

## What is worth keeping from it

Two pieces of reasoning, recorded here so they are not rediscovered:

**The live-zero scale.** Fan rpm was published as `volts = 0.5 + rpm/300`, with
**0.000 V meaning INVALID** rather than zero rpm. Without that offset a stopped
fan, a pulled wire, a dead PMC and a failed Modbus read all produce 0 V and are
indistinguishable in the file. This is the same trick 4–20 mA uses, and it is
worth reusing on any future analog link out of this rig.

**A telemetry field is not a measurement.** v4 reported par 0102 read directly
rather than derived from output frequency, because frequency cannot give rpm
without knowing slip — the assumption that made feedback read 295 where the
drive held 300.

## If a DAQ link is ever wanted again

Start from v5 and port these ideas forward. Do **not** resurrect this sketch:
it predates the discovery that `MachineControl_Encoders` is a library global
which already claims the encoder pins, and it carries none of the v5 fixes.
