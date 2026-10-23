# section_balance — two-axis force balance for the blade-section test

Firmware for an Arduino Nano 33 BLE Sense that reads two HX711 load-cell
amplifiers (drag and lift) and the on-board accelerometer. On the host,
`scripts/section_balance_logger.py` records sessions and
`scripts/section_balance_analyze.py` turns them into Cd and Cl.

**What it is for.** Prof. Jahangiri's request of 7 Oct (lift and drag
coefficients of a blade slice, measured and theoretical) and step 2 of
`cfd/analysis/2026-10-15/TEAM_SUMMARY.md`: Cd and Cl at alpha 0, 90 and 180
for Plain against FS, and whether the convex side sheds vortices (CFD: St
0.22, about 107 Hz at 23 m/s).

**Status, 22 Oct 2026.** Compiles for `arduino:mbed_nano:nano33ble` (core
4.6.0): 131 kB flash (13 %), 87 kB RAM (33 %). Logger and analysis tested
against a simulated board (`tests/test_section_balance.py`). **Not yet run on
a board.**

---

## Safety

- The board connects to the host by USB and to its two HX711 modules, nothing
  else. It cannot command the fan, the drive or the load, and it changes no
  interlock. The logger never opens the drive's port (it excludes
  `transport.port` and the tunnel node's port, and listens before it writes).
- Run the fan as for any test, per `FIELD_CARD.md`. The test runs with the
  rotor removed (`docs/12_section_force_test.md` §7); if a rotor is ever in
  the test section, the load interlock applies exactly as for a sweep.
- The Nano, the HX711 modules and their cables mount outside the test section
  and are tied down: nothing of this assembly may be able to travel into the
  fan. The mechanical retention of the slice is part of the mount design.
- Calibration string, pulley and masses come out before the fan starts. After
  any `cal` dwell the logger refuses wind dwells until `cleared` is typed. That
  is a reminder, not an interlock: the fan is controlled elsewhere.
- HX711 modules on **3V3, never 5 V**: the nRF52840's pins are not 5 V
  tolerant, and on the common module DOUT swings to VCC.

## Wiring

| HX711 | VCC | GND | DT (DOUT) | SCK |
|---|---|---|---|---|
| drag | 3V3 | GND | D2 | D3 |
| lift | 3V3 | GND | D4 | D5 |

Load cell to HX711: E+ red, E− black, A− white, A+ green (the common code;
check the cell's sheet). A4/A5 stay free for a pitot sensor
(`cfd/MEASUREMENTS_NEEDED.md` section 3), D0/D1 for Serial1.

The HX711 runs at 10 Hz with RATE tied low (the usual module) and 80 Hz with
RATE high. The firmware cannot set it; `RATE?` reports what it measures.

Route the load-cell and HX711 leads away from the drive's motor and mains
cables, as for any signal wiring, and keep them short: the bridge signal is
millivolts.

## Build and flash

```bash
arduino-cli lib install "HX711 Arduino Library@0.7.5"
arduino-cli compile --fqbn arduino:mbed_nano:nano33ble firmware/section_balance/
arduino-cli upload  --fqbn arduino:mbed_nano:nano33ble -p <port> firmware/section_balance/
```

Also used: Arduino_LPS22HB 1.0.2, and Arduino_BMI270_BMM150 1.2.3 on a Rev2
board. Flashing the tunnel node's board replaces `tunnel_node`; re-flash
`firmware/tunnel_node/` before the next turbine run.

The board is detected at boot: Rev1 (LSM9DS1, accelerometer at 952 Hz) or
Rev2 (BMI270, 1600 Hz). The banner and `RATE?` give the sample rate the
board achieves, measured, not the configured one. The Rev2 path has not been
on a board; its axis remap is the Arduino library's.

## Bench check, no wind

Over a serial monitor at 115200 baud, or the logger's `live`:

1. `ID` answers `drag=ok lift=ok`. `none` means DOUT stays high: check 3V3,
   GND and DT.
2. `RAW?` a few times with nothing touching the cells: the counts move by
   noise only, not by thousands.
3. Press each cell by hand while `START` streams: its own column moves most.
   `flags` reads 3 (both channels fresh). 1 or 2 alone: one channel stopped
   converting. 4 or 8 added (7, 11): that channel is saturated, overloaded or
   with its load cell disconnected.
4. `BURST 4000` (about 4 s) while tapping the mount: the accelerations show
   the taps.

## Conventions

Alpha and lift follow the CFD (`cfd/section2d/README.md` section 1).
Draw the section with the convex side facing right and the curled tip B at
the top; that view looks along −z_body.

- alpha 0: the cup (concave side) into the wind. alpha 90: wind along the
  chord from tip A to tip B. alpha 180: convex side into the wind.
- Raising alpha turns the slice clockwise in that view.
- Positive lift is 90° counter-clockwise from the wind in that view. At
  alpha 90 it points from the convex face toward the open side of the cup.
  `lift_sign` in the rig sheet says whether the balance's +lift axis points
  that way (+1) or the other (−1).
- c_ref = 48.0 mm (the CFD's reference chord, the bounding-box extent);
  S = c_ref × span.

## A session

```bash
python scripts/section_balance_logger.py --set Plain --session a_sweep
python scripts/section_balance_logger.py --simulate --realtime     # rehearsal, no hardware
python scripts/section_balance_analyze.py --write-rig-template rig.yaml
python scripts/section_balance_analyze.py logs/section_balance/<session> --rig rig.yaml
```

The logger never sets the wind. Set the fan over the PMC with `src/run.py jog`
or the dashboard, then label it: `rpm 1100` records the set point and the
wind speed the fan calibration gives. Not `scripts/rpm.py`: it needs the FTDI
link, which is not landed while the PMC is, and it stops at 1700 rpm.

| fan rpm | m/s |
|---:|---:|
| 500 | 10.2 |
| 1100 | 23.0 |
| 1800 | 38.0 |

Those speeds come from v = 0.02132 × RPM − 0.424, measured to 700 rpm
only (Test 1, 13 Feb 2026) and extrapolated above. A pitot reading, when
there is one, goes in with `umeas <m/s>` (recorded as `U_meas_ms`), or as a
`q_pa` column added to the run sheet.

Order, in one session:

```text
air 21.5                        reference thermometer, °C (pressure from the board)
cal d 0 / cal d 500 + / ...     calibration loads on each axis, both directions,
cal l 500 - / ... / fit         up to the largest expected force; then `cleared`
set support                     slice removed: zero, `support` at each speed, zero
set Plain                       slice mounted
mount
alpha 0
zero                            FAN STOPPED and the air still
rpm 500 / wind / rpm 1100 / wind / rpm 1800 / wind
zero                            fan stopped again: closes the block
alpha 90 ...                    the same at each alpha, then the next set
burst 4000                      accelerometer, at a wind point and with the wind off
                                (`rpm 0` first, or the wind-off burst is labelled with wind)
```

Each block of wind dwells sits between two wind-off zeros at the same alpha.
The zero can move with alpha (the slice's weight acts at a different arm), so
the analysis uses a zero only at its own alpha and mount, interpolated in time
between the two. The logger warns when a block is left open.

Files: `logs/section_balance/<date>_<time>_<session>/` holds `trace.csv`
(every row; raw counts are the record), `runsheet.csv` (one row per dwell;
set `use` to 0 to drop one), `session.json`, `calibration_fit.json` and
`bursts/`. The analysis writes `analysis/` beside them.

## Calibration

Hang masses on a string over a pulley, horizontal and along one axis,
attached at the slice's mid-span, where the aerodynamic load acts. The
cross-talk and the cells' sensitivity to where the load sits are part of what
is calibrated. The mass is weights plus hanger plus string below the pulley.
A `cal d <g> +` load pulls the slice downstream (the analysis has no drag
sign); a `cal l <g> +` load defines the balance's +lift axis, which
`lift_sign` maps onto the CFD's.

`fit` solves counts = a + d·t + K·F by least squares (offset, drift, and the
2 × 2 sensitivity matrix K with its cross-talk), sends K to the board for the
live readout and records it in `data/section_balance.json`, which the logger
re-sends on every connect: the firmware keeps K in RAM only. The analysis
refits K from the calibration dwells, with its uncertainty, and does not use
the recorded copy.

Force range for the mount of `docs/12_section_force_test.md` (an existing
blade, 120.1 mm exposed; calculated from the CFD's smooth-blade values, its
§3): up to 16.1 N mean drag at alpha 0 and 38 m/s (Cd 3.22) and 13.4 N mean
lift at any alpha (23 m/s polar, assumed to hold at 38 m/s), down to 0.12 N
drag at alpha 90 and 10.2 m/s. Calibrate to at least the largest (§5.1 of
that document: to 2000 g on drag, 1500 g on lift).

## What the test-section size changes

The size is not recorded yet (`cfd/MEASUREMENTS_NEEDED.md` section 2). Until it is,
the analysis applies no blockage correction and `summary.txt` says what the
correction would be for 0.25, 0.5 and 1.0 m².

The correction is Maskell-type, q_c / q = 1 + θ (D / q) / C, each dwell with
its own measured drag. For the end-plated 120.1 mm piece, θ lies between 0.96
(2D wake) and 2.40 (free tip); the analysis takes 1.68 ± 0.41 by default, and
`docs/12_section_force_test.md` §5.4 tabulates the correction against the
section size (literature fit; calculated). With θ 1.68, Cd at alpha 0 (3.22)
falls by 11 %, 6 % and 3 % for C = 0.25, 0.5 and 1.0 m², and at alpha 90 by
under 2 % (calculated).

Once W and H are measured: `test_section: {width_m, height_m}` in the rig
sheet, or `--section-wh W H`.

## Uncertainty

Monte Carlo through the whole chain, reported as a systematic part (shared:
K, the fan calibration, density, span, θ) and a random part (per dwell: noise
by batch means, zeros, set-point repeatability). Differences between sets are
taken draw by draw, so what both share cancels as far as it really does.
Defaults that are assumptions are labelled so in the rig template; the
largest is the fan calibration (5 % in U assumed, so 10 % in every absolute
Cd), which cancels in Plain-against-FS differences at the same set point.

Not propagated, and listed in `summary.txt`: the alpha setting, support
interference, finite span and end effects (the CFD is 2D), streamline
curvature, and which 2D flow state the slice takes at alpha 0 (CFD: Cd about
1.75 or 3.2). Repeats with the slice remounted and alpha re-set capture the
first; dwells flagged `unsteady` are where to look for the last.
