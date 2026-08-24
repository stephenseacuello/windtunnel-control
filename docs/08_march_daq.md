# The March 16 DAQ Capture — Channels Identified

`reference/data/03162026_sec_backup.xlsx` — 16:55–16:59 on 16 Mar 2026, six
analog channels, 300 Hz, 83,200 samples, 4.6 minutes. Collected with Dr Jeong.

Analysed 24 Aug 2026, entirely off the rig. Every number below is reproducible
from the file.

---

## What the channels are

| ch | mean | std | identification |
|---|---:|---:|---|
| **1** | 0.105 V | 0.093 | **anemometer** — tracks rotor speed at r = 0.998 |
| **2** | 2.498 V | 0.016 | **sitting at mid-rail** — an unconnected input or a reference, not a measurement |
| **3** | −0.001 V | 0.498 | **generator phase A** |
| **4** | −0.003 V | 0.499 | **generator phase B** |
| **5** | −0.003 V | 0.247 | **half-scale copy of ch4** — r = 0.98, amplitude exactly 0.5× |
| **6** | −0.002 V | 0.496 | **generator phase C** |

### The three-phase identification is not a guess

ch3, ch4 and ch6 correlate with one another at **−0.50, −0.51, −0.51**.
cos(120°) = −0.5 exactly. Three signals mutually 120° apart, equal amplitude,
zero mean, is a three-phase set and nothing else.

### ch5 answered

The open question was *"deliberate dual-range, or a wiring duplicate?"*. It
correlates with ch4 at **0.98** with an amplitude ratio of **0.495**. That is a
duplicate on a different range or through a divider, not an independent
measurement. Whatever the 20% unexplained residual in the earlier look was, at
this resolution ch5 carries no information ch4 does not.

---

## Rotor speed is already in this file

Applying a Clarke transform to the three phases gives a rotating vector whose
angle is the electrical angle, so its derivative is the rotation frequency
directly — no zero-crossing detection, no peak picking, and it uses all three
channels rather than one.

    alpha = (2*ch3 - ch4 - ch6) / 3
    beta  = (ch4 - ch6) / sqrt(3)
    f_elec = d/dt unwrap(atan2(beta, alpha)) / 2*pi

Over the run (excluding the first 30 s of start-up) the electrical frequency
runs **5.75 → 16.07 Hz**. Rotor rpm follows once the pole count is known:

| pole count | rotor rpm at 5.75 Hz | at 16.07 Hz |
|---|---:|---:|
| 2 | 345 | 964 |
| 4 | 173 | 482 |
| 8 | 86 | 241 |
| 12 | 58 | 161 |

**The pole count is the only thing missing.** It is a nameplate reading or a
magnet count, and it converts every one of these captures into rotor rpm
retroactively.

---

## The "factor of 8" anomaly was an artefact

`TODO.md` carried this open item:

> across the run ch1 rises 16.6× while the rotation frequency rises only
> 2.08×. For a freewheeling rotor at constant λ, or vortex shedding at
> constant Strouhal, those should track. Off by a factor of 8.

There is no anomaly. Fitting ch1 against rotation frequency:

    ch1 = 0.03039 * f_rot - 0.1943      R2 = 0.9970,  r = 0.998

**A fold-change is meaningless when a signal's baseline sits near zero.** ch1
has a −0.194 V offset, so its minimum lands near 0.000 V and max/min explodes
to whatever the noise floor happens to be — 16.6×, 300 million×, any number
you like. f_rot has no such offset, so its fold-change is modest and physical.
Comparing the two ratios compares an artefact against a real quantity.

The offset-free test is the correlation, and it is **0.998**. The anemometer
and the rotor track each other essentially perfectly: a freewheeling rotor at
roughly constant tip-speed ratio, exactly as expected.

That also independently supports the linear-output anemometer finding in
`reference/README.md` — a pressure-sensor form would put curvature into this
fit, and R² = 0.997 against a straight line leaves no room for it.

---

## What this means for the rig

**The rotor-RPM channel may already exist.** If ch3/4/6 are still landed on
Jeong's DAQ, rotor speed needs no new sensor and no new wiring — only the
generator's pole count and the Clarke transform above.

Worth checking before anyone builds anything, including `encoder_disc.stl`
(40 × 40 × 8 mm, drawn 31 Jul), which may be solving a problem that is
already solved.

### Two acquisition faults to fix before the next session

- **ch3/4/6 sit at 98% of ADC range.** They will clip the moment conditions
  get stronger, and a clipped phase corrupts the Clarke angle — the very
  thing that makes rotor speed recoverable. **Drop the gain.**
- **ch2 is doing nothing.** At 2.498 ± 0.016 V it is an unconnected input.
  That is a free channel, and fan rpm from the drive's analog output would be
  a good use of it — see `docs/05_integration.md`.

Reproduce: `python src/daq_survey.py reference/data/03162026_sec_backup.xlsx`
