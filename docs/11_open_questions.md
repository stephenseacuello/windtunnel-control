# Open Questions — data, not code

Things the rig cannot currently answer, and what would settle each. These are
measurements, not features; none is blocked on software.

---

## 1 · Rotor speed is not yet trustworthy

The magnet-and-reed sensor counts, but each magnet pass registers **2–3 times
and the number varies** — 28 raw counts over 10 hand revolutions. A fixed
ratio would be correctable; a varying one is not, so rotor rpm carries roughly
±20% scatter against a blade effect of 13.7%.

**What settles it:** a capacitor from `Z0` to `GND` (start 0.1 µF, tune until
10 revolutions read 10 counts), or a Hall-effect sensor, which has no contacts
to bounce. The VJ12-D10K is rated **20 Hz by its own packaging** and this rotor
needs 50–70 Hz.

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

## 5 · ### The anemometer calibration form

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
