# Open Questions — data, not code

Things the rig cannot currently answer, and what would settle each. These are
measurements, not features; none is blocked on software.

---

## 1 · Rotor speed is not yet trustworthy

The magnet-and-reed sensor counts, but each magnet pass registers **2–3 times
and the number varies** — 23 counts over 10 hand revolutions at a 5.5 ms
debounce (1 Sept 2026). `check_rotor` on `sweep_v1_Ra40` returns K rising
**+91.5%** with 206% spread: missing counts at speed, on top of extra counts
at rest.

### These are TWO faults, and only one of them is the sensor

**Fault A — the input floats. Fixable, and it is the one to fix first.**
The VJ12-D10K is a **2-wire dry contact**: it shorts or it opens, with no
output drive. There is **no pull-up on `Z0`**. v5.3 tried to set one in
firmware, hung the board, and it was removed — while the boot banner went on
printing `INPUT_PULLUP` until 1 Sept. So an open contact leaves a CMOS input
floating beside a 15 HP motor and a VFD.

That is what the hand test measures. Ten turns by hand is **1–2 Hz, twenty
times below this reed's own 20 Hz rating**, so bandwidth cannot produce extra
counts there; and contact bounce settles in 1–5 ms, so a 5.5 ms debounce would
have absorbed it. Extra edges spread over tens of milliseconds are noise on a
floating line, and no firmware debounce removes them — past the Schmitt
trigger they are indistinguishable from signal.

> **Fit 4.7 kΩ from `Z0` to 3V3 and 10 nF from `Z0` to `GND`, run in shielded
> twisted pair.** The firmware has recommended exactly this since v5.0 and it
> has never been fitted. No reflash needed — this is two components.

**Fault B — the reed cannot follow the rotor. Not fixable.**
Jeong's DAQ measured **18,500 rpm at fan 1800 = 308 Hz**. A mechanical reed
rated 20 Hz is 15× short, and signal conditioning does not change that. Fixing
Fault A should give clean counts at the bottom of the wind range and nothing
above roughly fan 800.

**What actually settles it:** a Hall-effect or optical sensor (308 Hz is
trivial for either), or the two contact-free methods in §1a below, both of
which work today.

### 1a · Two ways to get ω without any new sensor

**The generator is a tachometer.** V_oc ∝ rotor speed, and Jeong's DAQ anchors
the constant: `K = V_oc(1800)/18,500 = 1.316 mV/rpm`. Light-load λ from the
Ra 40 sweep comes out **2.36 → 5.19, smooth and monotonic** — against the
reed's 0.28–8.6 scatter. For λ at the *peak* the winding resistance is needed:
`ω = (V + I·R_w)/K`. At fan 1700 that gives λ 2.93 / 4.54 / 6.14 for R_w of
10 / 30 / 50 Ω, so **`R_w` must be measured with a meter, not assumed** — and
NOT taken from the fitted `R_int`, which falls 88→36 Ω with wind because it is
absorbing rotor droop.

**The IMU sees it.** The tunnel node bursts accel at 989 Hz, Nyquist 494 Hz,
and the rotor 1× line at 308 Hz is resolved across the whole range. A burst
per wind speed gives ω with no contact and no bandwidth ceiling.

**Why it matters:** without ω there is no λ and no Cp. Every blade comparison
so far is electrical power, which cannot separate rotor aerodynamics from
generator matching — a blade that captures more energy but spins slower reads
*lower*.

---

## 2 · No mount-to-mount error bar

Every result comes from **one mounting of each rotor**. Ra 80 measures +13.73%
over Ra 20 with a 95% CI of [+11.21, +16.26], but remounting could move a
result by several percent and nothing yet bounds that.

**What settles it:** re-run `v1_Ra20` after physically remounting the rotor,
same protocol `94bed28333f7`, then `compare_blades.py v1_Ra20 v1_Ra20_repeat`.
Whatever that returns *is* the error bar. ~10 minutes of tunnel time.

---

## 3 · Source impedance is fitted, never measured

`src/generator_model.py` fits `R_int = 595.5·v^-0.791` (88.4 Ω at 10.2 m/s to
36.5 at 38.0) at r² ≥ 0.986. But that is the **whole source** — generator
winding, rectifier, wiring and the series sense IC together.

**What settles it:** ohm the winding phase-to-phase, cold and hot. Thirty
seconds with a meter, and it separates the generator from everything else.

---

## 4 · The two files disagree about wind speed

`sweep_v1_Ra20_summary.csv` and `..._points.csv` differ by **1.1–1.2%** at the
same fan set point (1700 rpm: 35.43 vs 35.82 m/s). At P ∝ v^3.77 that is **4.5% in power**
— larger than most effects being chased. Which is right is not established.
Do not average them.

**But it is bounded where it matters.** Fitting the power law against each in
turn gives an exponent of 3.769 or 3.763 — a 0.16% difference. Whichever file
is right, the exponent stands; it is absolute power at a stated wind speed
that carries the 4.5%.

---

## 5 · The anemometer calibration form

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

---

## 6 · Was the Ra 80 print otherwise identical?

`--notes` for `v1_Ra80` records a **0.2 mm nozzle**. The `v1_Ra20` notes record
no nozzle at all. If the two prints used different nozzles then nozzle *and*
roughness changed together and the comparison is not clean.

**What settles it:** read both slicer profiles.
