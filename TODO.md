# TODO

Ordered by what blocks what. Everything in **Path A** must happen before any
gust work; **Path B** runs in parallel and is independent.

---

## AT THE TUNNEL — next session

Everything here needs you physically at the rig. Roughly two hours, and the
first two items block the science.

### 1 · The two numbers that block Cp  ⚠ do these first

- [ ] **Rotor tip radius**, measured from the AXIS OF ROTATION — not blade
      length. `turbine.radius_m` is still null and `hub_radius_m` is 0.0.
      The blade STL gives 245 mm of SPAN; tip radius is hub + root offset +
      span, and the hub is not in that file. λ scales linearly with it and Cp
      as 1/r², so it cannot be guessed. **A ruler and two minutes.**
- [ ] **Rotor RPM from Jeong's DAQ** — which channel, what sensor, what
      scaling (V→rpm or pulses/rev), and what sample rate. Ask Taegu about
      `encoder_disc.stl` (40 × 40 × 8 mm, drawn 31 Jul) first — the sensor may
      already be designed. Without this you have P_max(v), not Cp(λ), and
      **every blade tested beforehand must be re-run.**

### 2 · One more blade  — the campaign's real test

- [ ] Run a second rotor with the identical command. ~10 minutes.

          python src/blade_sweep.py --blade <name> --notes "<material, layers, finish>" \
                 --step-amps 0.02 --dwell 1.0

      Confirm the protocol fingerprint matches `94bed28333f7`. This is the
      first evidence that the protocol actually **discriminates between
      rotors**, which is what the whole campaign rests on and has never been
      shown.

### 3 · Two keypad readings, one minute

- [ ] **Par 9904 MOTOR CTRL MODE.** Decides whether "actual speed" is a
      slip-compensated estimate or just frequency with a fixed assumption.
- [ ] **Par 2202 ACCEL TIME.** `run.py` reports *"ramp time unreadable over
      this transport — the slew check is OFF."* Read it once and pass
      `--max-slew` to restore the check.

### 4 · The watchdog test — if it has never been done

- [ ] **Pull the USB mid-run, deliberately.** The fan must ramp down within a
      few seconds. That watchdog is the entire reason a laptop is allowed to
      command a 15 HP fan, and nothing should run unattended until it has
      been seen to work.

### 5 · Wiring, while you are in there

- [ ] **VSense leads to the rectifier output**, not the load's own binding
      posts. Otherwise the wiring and the series sense IC sit inside your
      measurement and every power figure is low by I²R.
- [ ] **Trace the D-sub cable** already plugged into the Chroma's back panel.
      If something drives the load through analog programming, that is a
      second controller competing with SCPI.
- [ ] **Drive analog output → DAQ**, so fan rpm and rotor rpm share one time
      base. Six group-15 parameters, a 249 Ω resistor, two wires to X1-7/9.
      See `docs/05_integration.md`.
- [ ] Free and optional: **I Mon. BNC → a spare DAQ channel** for a continuous
      analog current record alongside the polled SCPI readings.

---

## DONE — 19-22 Aug 2026

- PMC landed and commissioned; drive commands rpm (par 1105 = 2435)
- First motion, then jog at 500 / 1200 / 1800 rpm
- **τ = 0.63 ± 0.12 s** from five 1-cosine gusts (use a gust, not a step —
  a step saturates the ramp generator and you fit par 2202 instead)
- Chroma proven to sink current: 25 consecutive setpoints tracking to 0.1 mA
- Load ranges measured off the instrument: CC 2 / 6 / 60 A, CR 250 / 1250 /
  2500 Ω. No programmable OVP/OCP/OPP on this firmware.
- `blade_sweep.py` built — 14 wind speeds unattended in ~10 minutes
- **Reference sweep: v2_Ra20, 14/14 clean, P ∝ v^3.77, R² = 0.998**
- Dashboard: PMC transport, turbine control, blade library, digital twin
- **V_oc measured** at every wind speed, taken from the light-load dwells of
  the sweep rather than a separate open-circuit run — 5.8 V at 15 m/s,
  23.9 V at 38 m/s. TODO B3's second item, answered without ever deliberately
  open-circuiting a spinning rotor.

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

- [ ] **One clean sweep settles it** — though the March analysis now gives
      independent support for the linear form: anemometer vs rotor
      frequency is R² = 0.997 against a straight line, and a
      pressure-sensor form would put curvature there.
      Single session, one DAQ configuration,
      logging anemometer voltage and a trusted velocity reference together.
      Ten points, 10–55 Hz. Then `fit_sensor.py logs/<sweep>_points.csv`.

### The March 16 DAQ capture  ✅ resolved 2026-08-24

Analysed off the rig — see **`docs/08_march_daq.md`**.

- [x] **What is each channel?** ch1 anemometer · ch2 unconnected (2.5 V mid-rail)
      · **ch3/4/6 are the generator's three phases** (mutual correlation −0.50,
      = cos 120°) · ch5 is a half-scale copy of ch4 (r = 0.98, ratio 0.495).
- [x] **ch5 — dual-range or duplicate?** A duplicate. It carries no
      information ch4 does not.
- [x] **The "factor of 8" anomaly.** An artefact, not physics. ch1 has a
      −0.194 V offset, so its max/min ratio is meaningless; the offset-free
      test is the correlation, and ch1 vs rotor frequency is **r = 0.998,
      R² = 0.997**. A freewheeling rotor at roughly constant λ, as expected.
- [ ] **ch3/4/6 sit at 98% of ADC range — drop the gain** before the next
      session. Clipping corrupts the Clarke angle, which is what makes rotor
      speed recoverable at all.
- [ ] **ch2 is an unconnected input.** A free channel — fan rpm from the
      drive's analog output would be a good use of it.
- [ ] **Get the generator's pole count.** Nameplate or a magnet count. It is
      the ONLY thing between these three channels and rotor rpm, and it
      converts every past capture retroactively.

---

## SOFTWARE — remaining, none blocking

- [x] Dashboard: load state, turbine power ✅ — the live Cp(λ) plot
      still needs rotor speed
- [x] PMC protocol extension for parameter reads ✅ — `RD`/`WR`/`UNLOCK`
      in `firmware/acs550_pmc_v3/`, with the refusal list in firmware
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
