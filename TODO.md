# TODO

Ordered by what blocks what. Everything in **Path A** must happen before any
gust work; **Path B** runs in parallel and is independent.

---

## PATH A — get the tunnel under control

Nothing gust-related works until this is done. Roughly one afternoon.

### A1 · Land the PMC  ⚠ decision already made

- [ ] **PMC on X1-29/30/31. The FTDI cable does not get landed.**
      One Modbus master only — two is two things commanding a 15 HP fan with
      neither aware of the other. Keep the FTDI on the bench for
      commissioning if the PMC misbehaves, but never both wired.
- [ ] **RS-485 termination DIP → ON.** Photographed OFF. Red 2-position block
      immediately left of terminal 28.
- [ ] X1 was photographed **empty** — confirm that's still true before landing
      anything. No Aerolab wiring to work around.
- [ ] Set `5304` = **8E1 (even)** — matches the PMC firmware. A drive
      parameter is three keypad presses; reflashing in the field is not.
- [ ] Set `9802`, `5302`, `5303`, `5305`, `5310`, `5311`, `3018`, `3019`
      per `PLAYBOOK.md` phase 6
- [ ] **Power-cycle the drive.** Group 53 is read at boot only.

### A2 · Prove it

- [ ] `run.py monitor` — read-only, fan cannot move
- [ ] `run.py selftest` — **confirm par 1105 against the keypad when it asks.**
      A wrong guess there makes every commanded speed off by exactly 10×,
      silently.
- [ ] Hand over control: `1103` = 8, `1001` = 10
- [ ] `run.py jog 10` — first motion
- [ ] **Pull the USB mid-run on purpose.** The drive must fault and stop within
      ~3 s. If it doesn't, `3018`/`3019` are wrong — fix before anything runs
      unattended.

### A3 · The two measurements everything depends on

- [x] ~~`RPM_PER_HZ`~~ — **obsolete.** The drive commands speed, not frequency
      (par 1105 = 2435 rpm), so there is no Hz→RPM link left to verify. The
      calibration is rpm→velocity directly, measured Feb 13 at R² = 0.9996.
- [ ] One anemometer reading at a known rpm would still confirm the
      rpm→velocity half against a second instrument. `run.py verify` does it.
- [x] **τ measured: 0.63 ± 0.12 s**, five 1-cosine gust runs, 20 Aug 2026.
      Corner ≈ 0.25 Hz — about five times faster than the 3 s that planning
      assumed. `tunnel.json` carries 0.80 / 0.80 s as a conservative value.
      **Use a gust, not a step**: a step saturates the drive's ramp generator,
      so what you fit is parameter 2202 rather than the tunnel.

---

## PATH B — get the load under control

Independent of Path A. Can be done while waiting on tunnel time.

### B1 · Connect it  ✅ done 2026-08-19

- [x] USB A-to-B cable. USB Type B "Device" is the only digital interface.
- [x] Instrument on USB, not in Local lockout.
- [x] It is USB-TMC, reached through VISA (`pip install pyvisa pyvisa-py
      pyusb`, plus `brew install libusb`). macOS has no kernel usbtmc driver,
      so nothing appears in `/dev` at all — this is expected, not a fault.
- [x] All 20 SCPI commands accepted. Ranges measured off the instrument and
      recorded in `tunnel.json`: **CC 2 / 6 / 60 A**, CR 250 / 1250 / 2500 Ω.
- [x] Fixed: the resource string `probe_load.py` prints could not be opened.
      The Chroma pads its serial with NULs, the probe strips them for JSON,
      and the stripped string matches no device. `VisaTransport._resolve()`
      now matches on the stripped form. See `docs/06_chroma.md`.

**This proves the load listens. It does not prove it works** — every check
above ran with LOAD OFF and could not draw a milliamp.

### B1a · Prove it actually sinks current  ← the real one

- [ ] **Bench supply, ~24 V, current limit ≥ 2 A, onto the load terminals.**
      Then:

      python src/load_ramp.py --peak-amps 1.5 --percent 80 --steps 9 \
                              --csv logs/load_proof.csv

      Ramps 0 → 80% and checks every step three ways: error queue, setpoint
      readback, measured current. It refuses to start into an open circuit.
      Bench only — it starts at 0 A and ends with the load off, both of which
      are wrong with a turbine attached.
- [ ] Set `load.proven.sinks_current` in `tunnel.json` once it passes.

### B1c · The stall-threshold protocol  — detector built, unproven on hardware

Built and regression-tested against a modelled rotor (`src/peak_finder.py`,
`src/load_sim.py`, `tests/test_peak_finder.py`, 16 tests). Never run against
anything real.

- [ ] **Decide `CONF:VOLT:OFF` before the first run.** At the shipped 3.00 V
      the simulation under-reads the threshold by **30% at 500 rpm** — the
      load quits before the rotor does, and the recorded number is the
      instrument's limit. `--volt-off 0.5` recovers it.
- [ ] **Find `--dwell` empirically.** The simulator has no rotor inertia, so
      it cannot tell you this. Too short and every point measures a transient.
      Start at 5 s, halve it until the threshold moves, then double back.
- [ ] Run one wind speed on hardware (1800 rpm, highest signal) before
      attempting the sweep.
- [ ] **The outer loop is not built.** Fan rpm 500→1800 in 100 rpm steps needs
      the drive, `TurbineInterlock`, and rotor RPM for λ. That belongs in
      `turbine.py` with the drive side, not in `load_ramp.py`.

### B1b · No programmable protection — decide what covers it

- [ ] **This model has no OVP/OCP/OPP over SCPI.** Every `:PROT:` mnemonic is
      rejected with `3,"Command Error"`; twelve variants were tried. The 400 W
      envelope is enforced only by whatever is driving the load.
      `load_ramp.py` checks V×I before every step. **`CpSweep` does not yet.**
- [ ] Add the same envelope check to `CpSweep._hold_point` before it runs
      unattended, or set `CONF:VOLT:OFF` deliberately for the turbine rather
      than leaving it at the shipped 3.00 V.

### B2 · Trace what's already connected

- [ ] **A cable is already in the D-sub on the load's back panel.** Find out
      where it goes. If something is driving the load through analog
      programming, that's a second controller competing with SCPI.
- [ ] Land the **VSense** leads at the rectifier output, not on the load's own
      binding posts. In CR mode the load *regulates* on sense — bad sense means
      it controls to the wrong resistance, not just reports wrong.
- [ ] Optional, free: **I Mon. BNC → a spare DAQ channel.** Continuous analog
      current record alongside the polled SCPI readings.

### B3 · Three numbers I need before the first Cp sweep

- [ ] **Rotor tip radius**, from the axis of rotation — not blade length.
      λ scales linearly with it and Cp inversely with its square.
- [ ] **Open-circuit DC voltage at a moderate wind speed** (~15 m/s). Sets the
      resistance ladder. Measure it *briefly* and at low wind — open circuit is
      the condition the interlock exists to prevent.
- [ ] **Where turbine RPM comes from** — which DAQ channel, or a separate
      sensor, and what the code should call to read it.

---

## PATH C — then the actual science

- [ ] First Cp(λ) sweep. Load on → wind up → resistance ladder high to low →
      wind down → load off. `TurbineInterlock` enforces the order.
- [ ] Check peak λ is consistent across wind speeds. It should be — peak λ is a
      property of the rotor, not of wind speed. **That consistency is the best
      evidence the measurement is sound.**
- [ ] Report as `Cp_elec`, not Cp. It is Cp_aero × η_gen × η_rect — **do not
      compare it to the Betz limit.**

---

## OPEN QUESTIONS — data, not code

### The anemometer calibration form

Fitting says the sensor is **linear-output (cup or vane)**, beating the
pressure-sensor form by ΔAIC 17 — decisive. So the March report's §3 "hot-wire"
label is wrong and its dynamic-pressure justification for the curvature doesn't
apply.

But the quadratic voltage-vs-RPM still contradicts fan affinity laws and Test 1.
Cup friction at low speed was tested as an explanation and **ruled out** — the
curvature is spread across the range, not concentrated at the bottom. An
RPM-dependent gain difference between the two sessions remains live.

- [ ] **One clean sweep settles it:** single session, one DAQ configuration,
      logging anemometer voltage and a trusted velocity reference together.
      Ten points, 10–55 Hz. Then `fit_sensor.py logs/<sweep>_points.csv`.

### The March 16 DAQ capture

- [ ] **What is each channel?** ch1 looks like the anemometer; ch3/4/6 correlate
      at −0.5 (three sensors at 120° around something rotating); ch5 ≈ 0.485 ×
      ch4; ch2 sits at 2.5 V of white noise.
- [ ] **ch5 — deliberate dual-range, or a wiring duplicate?** 20% unexplained
      residual says it isn't a pure electrical copy.
- [ ] **ch3/4/6 are at 98% of ADC range.** They will clip the moment conditions
      get stronger. Drop the gain before the next session.
- [ ] **ch2 reads 205% of its range** — either on a different range than the
      others, or railed.
- [ ] Unresolved: across the run ch1 rises 16.6× while the rotation frequency
      rises only 2.08×. For a freewheeling rotor at constant λ, or vortex
      shedding at constant Strouhal, those should track. Off by a factor of 8.

---

## SOFTWARE — remaining, none blocking

- [ ] Dashboard: load state, turbine power, live Cp(λ) plot
- [ ] PMC protocol extension for parameter reads — or accept that commissioning
      happens over the direct transport
- [ ] Decide the resistance ladder endpoints once B3 is known

---

## DONE

- Modbus driver, gust generation, feedforward, closed-loop velocity, dashboard
- 77 tests, no hardware needed
- Transport abstraction — direct or PMC, same code above it
- Chroma driver with USB/serial/VISA/TCP and the turbine interlock
- Cp(λ) sweep with the stall guard
- Calibration: **v = 0.02132 × RPM − 0.424** (rpm domain; the drive
  commands speed, not frequency)
- Playbook, field card, troubleshooting, architecture and commissioning diagrams
- Source documents bundled in `reference/` with a provenance index
