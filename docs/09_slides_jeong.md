# Slide content — for Dr Jeong

Requested 20 Aug: *"1–2 slides summarising the experimental setup and another
1–2 summarising the key data and results"*, to keep as a record.

Paste-ready. Figures referenced are in `docs/diagrams/`.

---

## Slide 1 — Experimental Setup

**Aerolab wind tunnel · programmable turbine characterisation**

> **Figure:** `docs/diagrams/architecture.svg`

- **Tunnel drive** — ABB ACS550-U1-046A-2, 15 HP, 208–240 V 3φ. Commands
  rotor **speed in rpm**, full scale 2435
- **Wind range** — 500–1800 rpm fan = **10.1–37.5 m/s**
- **Calibration** — v = 0.02132 × RPM − 0.424 (measured Feb 2026, R² = 0.9996)
- **Turbine load** — Chroma 63004-150-60 DC electronic load. Sets the rotor's
  operating point *and* is the best V/I instrument on the rig
- **Control chain** — Python host → USB → Portenta Machine Control → RS-485
  Modbus → drive
- **Tunnel bandwidth** — τ = **0.63 ± 0.12 s**, measured from five 1-cosine
  gusts

---

## Slide 2 — Safety Architecture

- **Hardwired E-stop** is the safety device. No software is in that chain
- **Two independent watchdogs** — the drive stops if the PMC goes quiet; the
  PMC stops if the host goes quiet
- **One Modbus master only.** Two devices commanding a 15 HP fan, neither
  aware of the other, is the failure this design exists to prevent
- **Turbine interlock** — an unloaded rotor in moving air accelerates until
  something mechanical stops it, so the order is enforced in software on
  every path that can move the fan:

  > **load ON → wind UP → test → wind DOWN → load OFF**

- If the fan cannot be confirmed stopped, **the load stays on**

---

## Slide 3 — Method

**Automated blade characterisation — ~10 minutes per rotor, unattended**

- At each of **14 wind speeds** (500 → 1800 rpm in 100 rpm steps):
  - Ramp the electronic load in constant-current steps
  - Stop once electrical power falls to **80 % of its peak** — the rotor is
    never driven to stall
  - Record V and I at every step, unload, advance the wind
- **Peak located by parabolic fit**, not by taking the largest sample. Over a
  flat maximum the largest sample is biased high, and the bias grows with the
  number of samples — so two blades measured with different point counts
  would be compared unfairly
- Every run carries a **protocol fingerprint**. Runs measured under different
  settings are not comparable, and the fingerprint makes that visible instead
  of silent

---

## Slide 4 — Results: blade v1_Ra20 (PETG, 0.2 mm, Ra 20)

| fan rpm<br>commanded | measured | m/s | P_max | at |
|---:|---:|---:|---:|---:|
| 500 | 496 | 10.1 | 0.030 W | 0.018 A |
| 900 | 894 | 18.6 | 0.273 W | 0.068 A |
| 1400 | 1384 | 29.1 | 1.665 W | 0.240 A |
| 1800 | 1779 | 37.5 | **3.793 W** | 0.320 A |

*Wind speed is derived from **measured** fan rpm, not commanded — the drive settles 4–13 rpm below setpoint, and quoting the command beside a measured velocity would be inconsistent.*

- **14 / 14 points clean**, single continuous run
- **P ∝ v^3.77, R² = 0.998** across the full 10.1–37.5 m/s range
- **Reproducibility** — independent single-point runs at 1200 and 1800 rpm
  match the sweep to **0.3 % and 0.2 %**

### The finding is the exponent, not the wattage

- Constant Cp would give **v³**. We measure **v^3.77**
- Open-circuit voltage says the same thing independently: **V_oc ∝ v^1.50**,
  where a constant runaway tip-speed ratio would give v^1.0
- → **Cp is still climbing with Reynolds at 37.5 m/s.** This rotor never
  reaches its design regime anywhere in the tunnel
- → **Blade rankings may be speed-dependent.** A blade that wins at 10 m/s
  may not win at 38

### Stated plainly

This is **electrical power at the load terminals — not Cp**. It cannot
separate rotor aerodynamics from generator matching. Cp(λ) requires rotor
speed, and every blade tested before that lands must be re-run to obtain λ.

---

## Slide 5 (optional) — Next: rotor speed → Cp(λ)

> **Figure:** `docs/diagrams/twin_residual.svg`

**The measurement may already exist in the Jeong lab data.**

- In the 16 Mar capture, **ch3/ch4/ch6 correlate mutually at −0.50**.
  cos(120°) = −0.5 exactly: they are the generator's three phases
- A Clarke transform on those three gives the electrical angle directly, so
  its derivative is rotation frequency — 5.75 → 16.07 Hz across that run
- **The only missing number is the generator's pole count.** A nameplate
  reading converts every past capture into rotor rpm retroactively

**And the model already tells us what it is missing.** Fitting the aerodynamic
source form V = V_oc·√(1 − I/I_stall) to all 14 wind speeds leaves a residual
that is **positive at every one** — one-sided, so structure rather than noise.
A linear Thévenin form V = V_oc − I·R fits better at **14 of 14** wind speeds,
by a factor of 2–6 in RMSE.

→ The rig's electrical behaviour is dominated by **generator winding
resistance plus wiring**, not by rotor aerodynamics. That is measurable and
correctable, and it is why per-point rotor speed matters: without it, blade
comparisons are partly comparing the generator.

---

## Notes for building the deck

**Slides 1–2 are the setup pair Dr Jeong asked for; 3–4 are the results pair.**
Slide 5 is optional and makes the case for the DAQ channel directly to the
person who owns the DAQ.

If Taegu is covering the mechanical rig and rotor fabrication, keep slide 1
to the control and measurement chain to avoid overlap.

The limitation bullet on slide 4 is the most valuable line in the deck for
this audience. It is honest, and it is the argument for the next measurement.
