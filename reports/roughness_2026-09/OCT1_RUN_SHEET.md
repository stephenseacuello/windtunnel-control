# Tunnel session: Thu 1 Oct, 3–4 pm (with Taegu)

The plan is to **run every rotor again** (a fresh mounting of each), plus Ra10 and the
no-texture rotor if time allows. Each sweep takes about 8 min of tunnel time plus about
5 min to mount, so budget **13–15 min per rotor**. Five rotors will not fit in one hour, so
the runs are listed in priority order.

**Why this order:** 20 → 80 → 40 is not in texture order, so any drift across the afternoon
(generator warming up, ambient) cannot line up with texture. The three remounts come first:
together they turn "one mounting per rotor" from the report's biggest caveat into a
measured error bar.

## Before the first sweep (5 min)

- [ ] `python src/run.py status` answers from the drive, and `python src/tunnel_node.py id`
      answers `tunnel-node`.
- [ ] Load leads are at the rectifier.
- [ ] Test section is clear, and a hand is on the E-stop.
- [ ] Load ON before wind UP; wind DOWN before load OFF.
- [ ] Every run must print protocol **`94bed28333f7`**. If it does not, stop and check the
      flags.

## The runs

**Take the rotor off and put it back before each remount**; that is what is being
measured. Use exactly these `--blade` names, because the report picks runs up by name.

| # | rotor | command |
|---|---|---|
| 1 ⭐ | Ra20 remount | `python src/blade_sweep.py --blade v1_Ra20_repeat --notes "Ra20 remount 1 Oct; fuzzy 0.050 mm" --step-amps 0.02 --dwell 1.0` |
| 2 ⭐ | Ra80 remount | `python src/blade_sweep.py --blade v1_Ra80_repeat --notes "Ra80 remount 1 Oct; fuzzy 0.202 mm" --step-amps 0.02 --dwell 1.0` |
| 3 ⭐ | Ra40 remount | `python src/blade_sweep.py --blade v1_Ra40_repeat --notes "Ra40 remount 1 Oct; fuzzy 0.101 mm" --step-amps 0.02 --dwell 1.0` |
| 4 | Ra10 (identity unconfirmed) | `python src/blade_sweep.py --blade v1_Ra10 --notes "believed fuzzy 0.025 mm; identity unconfirmed" --step-amps 0.02 --dwell 1.0` |
| 5 | no texture | `python src/blade_sweep.py --blade v1_smooth --notes "no fuzzy skin; printed v1 replica (27 Jul blades)" --step-amps 0.02 --dwell 1.0` |

If time is short, do 1–3. They are worth more than 4 and 5 together.

For the no-texture rotor use the name `v1_smooth`, not `v1_Ra0`; the build rejects `v1_Ra0`.

## Is "Ra10" really Ra10? (5 min, no wind, do it before or after)

Until one of these checks is done, the report shows Ra10 as **identity unconfirmed**: it is
plotted, but kept out of every trend fit.

1. **Calipers: a ratio test that needs no absolute numbers.** Fuzzy skin thickens the wall at
   its peaks in proportion to the fuzzy setting.
   - Measure the peak wall thickness of three sets, taking 5 readings each at the same
     spanwise spots and averaging them:
     - the **no-texture** set, giving w0;
     - the **Ra20** set, giving w20;
     - the **"Ra10"** set, giving wX.
   - Compute **(wX − w0) / (w20 − w0)**.
     - About **0.5** means it is Ra10 (0.025 mm).
     - About **1** means it is really an Ra20-level print.
     - About **2** means it is an Ra40-level print.
   - The differences are only a few hundredths of a mm, so average the readings and use the
     same caliper and the same spots on every set.
2. **Macro photo under raking light**, with the Ra10 and Ra20 sets side by side and a ruler in
   frame.
3. **The `.3mf` files** (see below) record which fuzzy settings went on which plate. That is
   the definitive answer.

## While blades are off (2 min per set)

- [ ] **Weigh each blade set** (all three blades together) and write the masses down.
- [ ] **Note which print each set came from**: Andrew's garage Bambu, or the Print Lab.

## After the session (at the desk)

```bash
cd reports/roughness_2026-09
python3 src/build_report.py          # picks up every new sweep automatically
cd report && latexmk -pdf -outdir=../out report.tex
python3 ../src/build_package.py      # rebuilds the zip
```

Then tell Claude "the Oct 1 runs are in", along with the caliper readings and masses. There
are two things left to finish:

- **The remount paragraph.** The report adds a section with a new figure automatically, but
  its interpretation paragraph is marked TODO for review.
- **Ra10's status.** It is flipped to "confirmed" only once a check above supports it (one
  line in `src/build_report.py`).

## Still outstanding

**Download the three Bambu `.3mf` files** from Drive to `~/Downloads`:

- `turbines_threeFuzzySettings_06mm.3mf`
- `turbines_threeFuzzySettings_06mm_plate_2.gcode.3mf`
- `turbine_default.3mf`
