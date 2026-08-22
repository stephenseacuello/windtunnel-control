# Reference — Source Material

Everything the calibration and the drive configuration were derived from. Kept
with the code because a calibration whose source data has gone missing is a
number you have to take on faith.

```
reference/
├── photos/     nameplate and keypad, as found
├── reports/    the March 2 characterization report
└── data/       raw DAQ capture, March 16
```

---

## photos/

| File | What it establishes |
|---|---|
| `drive_nameplate.jpeg` | ACS550-U1-046A-2 · 15 HP / 11 kW · input 3PH 208–240 V, 46.2 A · output 3PH 0–500 Hz, 46.2 A · fw 3.13 · mfd 03-May-2012 · S/N 2121803289 |
| `serial_label.jpeg` | Model and serial confirmation on the heatsink |
| `keypad_io_settings.jpeg` | The assistant panel in I/O SETTINGS — confirms an ACS-CP-A panel and a working keypad, which matters because it is the fallback when Modbus is unavailable |

The nameplate is why `hz_limit` is 58 and why the drive is assumed capable of
the full band: 46.2 A output at 15 HP.

**Not** on the nameplate, and still unverified: the motor's loaded speed and
whether the fan is belt-driven. That is the one assumption in the whole chain
(`RPM_PER_HZ = 29.17`) and one anemometer reading settles it — see
`verify` in the playbook.

---

## reports/WindTunnel_Report_20250302.pdf

Eacuello & Connelly, March 2 2026. Anemometer characterization across 17 RPM
conditions, 224,194 samples.

**Used for:** the cross-calibration pairs in `src/fit_sensor.py`
(`MARCH_PAIRS`) — Test 2's measured voltages against Test 1's measured
velocities at six overlapping RPM conditions.

**Findings from re-analysis, recorded so they are not lost:**

- The Feb 13 table (Table 2) looks like an ideal calibration set and is not.
  Its voltage column was back-calculated as m/s ÷ 14, so voltage and velocity
  are the same numbers twice. `fit_sensor.py` refuses data with that
  signature.
- The quadratic voltage-vs-RPM finding **strengthens** when the two invalid
  points are removed (p 0.029 → 0.0014), so the curvature is real, not an
  artifact of the 500 RPM duplicate.
- The report names the sensor three ways: cup (summary), hot-wire (§3), cup
  (Issue 3). Fitting says linear-output — cup or vane — beating the
  pressure-sensor form by ΔAIC 17. §3's label is wrong.
- The report's physical justification for the curvature (dynamic pressure ∝ u²)
  is a pressure-sensor argument and does not apply to a linear sensor. The
  calibration *form* is right; the reasoning offered for it is not.
- The ρ₁ = 0.998 autocorrelation, and therefore the N_eff = 14 and
  "CIs 15–35× too narrow" conclusion, appear to be **trend contamination
  rather than sensor lag** — see the March 16 data below.
- The 1400 RPM agreement described as validating the cross-calibration is
  circular: 1400 was one of the six points used to fit it.

Reproduce: `python src/fit_sensor.py --march-report`

---

## data/03162026_sec_backup.xlsx

March 16 2026, 16:55–16:59. Six analog channels, 300 Hz, 83,200 samples,
4.6 minutes. Collected with Dr. Jeong.

**What it settled:** the March 2 report's autocorrelation figure. Computed
*within steady plateaus* rather than across the whole run, ρ₁ is 0.08–0.39, not
0.998 — giving τ ≈ 4–7 ms and a sensor bandwidth of 24–44 Hz. A sensor cannot
simultaneously resolve 40 Hz and have a 2-second time constant, and the
plateau figure is the trustworthy one because it controls for drift.

That matters twice over: the report's uncertainty conclusion is inverted (N_eff
≈ 8,400, not 14), and the sensor is comfortably fast enough to measure the
gusts this project generates.

**Channel notes, unresolved:**

- ch1 — steps through six setpoints; the anemometer. 6.6% of variance at 60 Hz
  (mains pickup).
- ch3, ch4, ch6 — mutual correlation ≈ −0.5, the cos(120°) signature of three
  sensors spaced evenly around something rotating. Shared fundamental sweeps
  7.0 → 14.7 Hz with tunnel speed. **Running at 98% of ADC range — will clip
  if conditions get stronger.**
- ch5 ≈ 0.485 × ch4, 20% unexplained. Deliberate dual-range, or a wiring
  duplicate?
- ch2 — 2.5 V, white noise, no structure. Likely a reference or an unconnected
  channel.

**Open:** across the run ch1 rises 16.6× while the rotation frequency rises
only 2.08×. For a freewheeling rotor at constant tip-speed ratio, or vortex
shedding at constant Strouhal number, those should track. They are off by a
factor of eight, so something in that chain is not what it appears.

Reproduce: `python src/daq_survey.py reference/data/03162026_sec_backup.xlsx`

---

## What would close the remaining questions

One stepped sweep, single session, one DAQ configuration, logging anemometer
voltage and a trusted velocity reference together:

```bash
python src/run.py --port /dev/ttyVFD --velocity nidaq sweep 10 55 5
python src/fit_sensor.py logs/<sweep>_points.csv
```

That removes the between-session gain question, settles linear-vs-quadratic
velocity-vs-RPM, and confirms or corrects `RPM_PER_HZ` in one afternoon.
