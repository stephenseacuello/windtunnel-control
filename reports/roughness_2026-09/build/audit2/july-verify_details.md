## Method
- **Script:** `build/july_verify/verify_july.py`, run with system python3 in about 2 s. It reads only the lab CSVs and, for C8, the rig summary and points logs.
- **Independence:** I wrote my own pulse detector, fan-step detector, plateau finder, noise and bias estimates, and June grid test. I opened `analyze_july.py` and `key_numbers.json` only after reaching my own answers, then diffed.
- **Outputs:** `verify_numbers.json`, `verify_lab_windows.csv`, `verify_settings.csv`, `verify_plateaus.csv`, `verify_power_vs_rig.csv`, `verify_scale_vs_rig.csv`, `verify_log.txt`, `verify_segmentation.png`, `verify_noise.png`.
- **Exploration:** my exploratory scripts and plots are in `explore/`.

## Verdicts
| claim | verdict | my numbers |
|---|---|---|
| C1 channel map | **PARTLY**: identification confirmed; I scale untestable | V/I table values on the 4-code and 2-code grids (off-grid ≤4.1e-7). Zero-current V at 500/600/700 is 3.03/4.13/5.33 V against rig 2.85/4.47/5.62 V. ch1 capacitor tau 18.4 s. ch2 zero 2.49607 V. ch3 order-1 V line 6.6-58× the median, 3/rev line present, no order-½ or order-⅓ line of comparable size. ch4/ch5 slopes 0.481/0.217, r 0.998/0.993, edges coincide, decays differ (residual 6%/11%). |
| C2 recipe | **CONFIRMED** | Max relative error 3.1e-15. Joint shift 0 is the only 64/64 match in ±300 samples. Length ±1 breaks all RPM values. Threshold 0.06-0.13 V. |
| C3 noise and bias | **CONFIRMED** | σ = 31.25 mA at 0 A, white (flatness 0.96), r(V,I) between -0.045 and 0.029. Spikes 0.0946-0.1442 A (3.0-4.6σ). Bias 0.110 A (first pass), 0.1116 A (mine, same definition), 0.1175 A (at-sample). Extra 6-16 mA rms under load. |
| C4 500-700 at 0 A | **CONFIRMED** | Window means -0.84, +0.62, +0.08 mA (±0.5). First loading at 63.05 s. Null window gives 1.50 W (0.89-1.69 W by placement). |
| C5 CC, cumulative, no sweep | **CONFIRMED** (lower-bound consequence only at 900-1300) | Untouched fan steps: ratio -0.06 to +0.07. Wind cut: 0.043. Maximum current drop 2.3 mA. 0-3 current levels per setting. P fell with the last I increase at 1400 (-1.0%) and 1500 (-3.8%). |
| C6 dwells and misattribution | **PARTLY** | Dwells 12.25-38.0 s. Fractions depend on where in the 7-10 s spin-up the boundary sits (table below). The hidden step near 197 s is unresolved. |
| C7 June processing | **PARTLY** | n=50 fingerprint and non-2.5 V zero confirmed. June-style July at 500 gives 0.0391 W. June's 500 point differs (1.86 V at 75 rpm vs 3.2 V at 104 rpm), so the match with June is coincidental. |
| C8 reprocessed vs rig | **CONFIRMED** numerically; interpretation needs caveats | 1 s max 0.665-0.916× Ra20. Plateau mean 0.622-0.890×. At 1700: 2.695 W. Lab I is 0.56-0.71 of the rig's current at P_max at 900-1300 and 0.88-1.21 at 1400-1800. |
| C9 Measured_RPM | **CONFIRMED** | +3.95% (900), +2.73% (1300), -10.81% (2000; true 666.8 rpm). 14 missed pulses, all at 2000. |

## Window composition (fraction of each lab window outside its own setting)
Boundaries measured two ways: from the start of each rotor rise, and from its midpoint.

| lab window | span [s] | from rise start | from mid-rise | share of window inside a spin-up |
|---|---|---|---|---|
| 800 | 67.5-77.9 | 0.00 | 0.43 | 0.91 |
| 1200 | 150.7-161.1 | 0.37 | 0.00 | 0.37 |
| 1300 | 171.5-181.9 | 0.66 | 0.37 | 0.66 |
| 1500 | 213.0-223.4 | 0.00 | 0.29 | 0.77 |
| 1600 | 233.8-244.2 | 0.00 | 0.31 | 0.76 |
| 1700 | 254.6-265.0 | 0.00 | 0.11 | 0.42 |

The first pass's boundaries (24.1, 41.4, 69.7, 81.7, 103.3, 123.4, 144.4, 160.4, 175.0, 216.0, 236.6, 255.4, 270.8, 293.1, 311.4 s) do not use one convention. Some sit at the start of a rise (175.0), others at mid-rise (216.0, 236.6, 255.4).

## Power comparison (W; lab current zero-corrected on the 2 A/V scale; rig values are raw argmax)
| setting | lab Pdc_max | lab 1 s max, own span | plateau mean | Ra20 | ratio (1 s max / Ra20) | lab I / Ra20 I at P_max |
|---|---|---|---|---|---|---|
| 900 | 0.768 | 0.195 | 0.180 | 0.273 | 0.713 | 0.558 |
| 1100 | 1.016 | 0.452 | 0.420 | 0.643 | 0.703 | 0.707 |
| 1300 | 1.825 | 0.918 | 0.884 | 1.329 | 0.691 | 0.685 |
| 1400 | 2.253 | 1.519 | 1.416 | 1.665 | 0.912 | 0.934 |
| 1500 | 2.611 | 1.906 | 1.852 | 2.081 | 0.916 | 0.881 |
| 1700 | 3.818 | 2.695 | 2.591 | 3.033 | 0.889 | 1.209 |
| 1800 | 4.304 | 3.129 | 3.053 | 3.794 | 0.825 | 0.993 |

## Diff against the first pass
| item | first pass | mine |
|---|---|---|
| σ_I at 0 A | 31.27 mA | 31.25 / 31.27 mA |
| ch2 zero | 2.49611 V | 2.49607 V |
| bias coefficient | 0.110 A | 0.1116 (same definition) / 0.1175 A |
| 1700 1 s power | 2.694 W | 2.695 W |
| RPM errors (900, 1300, 2000) | +3.6, +2.8, -10.9% | +3.95, +2.73, -10.81% |
| EMF slope | 0.03342 (with the post-disconnect point) | 0.03145 (low-speed only); the post-disconnect point is valid (V peak 19.79 V at 600 rpm) |
| R_int | 26.8 Ω | 24.0 Ω with the low-speed line |
| dwell range | 12-41 s | 12.25-38.0 s |

## Alternative explanations considered
- **Could ch2 scaling differ?** Yes. The file only proves the lab applied 2 A/V. Against the rig's V-I curves the lab's voltage is 1.1 V lower at the same labelled current. The rig would need 1.10-1.60× the current, and the factor is not constant, so a scale error alone cannot explain it.
- **Did the lab intend instantaneous maxima?** The recipe is exactly that. It is a legitimate definition, but 24-97% of the value is noise, and Vdc_max and Idc_max occur at different instants (Pdc/(Vmax·Imax) = 0.83-0.98).
- **Is the "noise" real rectifier ripple?** No for the 31 mA floor. It is identical at 0 A with the load off, it is white, and it is uncorrelated with V. Real current of 31 mA rms through a ~24 Ω source would produce about 0.75 V rms of anticorrelated voltage ripple, whereas the voltage residual is 0.08-0.14 V and uncorrelated. The 6-16 mA excess under load may be partly real.
- **Is a 1 s mean fair?** Yes for suppressing sensor noise (to 1.6 mA). But the rig's value is a single settled Chroma reading after a 1 s dwell. The maximum of a 1 s moving mean is 2-11% above the settled plateau means, so quote both.

## Suggested wording to the lab
We were able to reproduce every entry in the 27 July Summary_Table exactly from the raw DAQ export. That let us see how each number is formed: the largest single 360 Hz sample of V, of I and of V·I in the middle half of each of 16 equal slices of the record. We think these peak values mostly reflect the current channel's broadband noise rather than the turbine. That noise is about 31 mA rms on your 2 A/V scale, and it is the same with no current flowing. As a result, Pdc_max sits about 0.11 A × Vdc above the power averaged over one second. That is roughly a quarter of the value at the highest settings. At 500-700 rpm, where the load current was at zero, it is essentially all of the value. Averaged over 1 s, the reading near 36 m/s becomes 2.7 W rather than 3.8 W. That is 8-38% below our rig's readings at the same fan settings, depending on setting and averaging choice. We do not read that gap as a rotor or roughness effect. At 900-1300 rpm the load stayed below the maximum-power current. We are also unsure of the current-sensor scale (we assumed 2 A/V about a 2.5 V zero) and of the DAQ input range, and we may have misread other parts of your setup. It would help us to know the sensor part and calibration, the input range, and how the tachometer pulse is produced; we saw it miss about one pulse in eight at the top speed. A future run that steps the load past the power peak and records the mean of each dwell would let the two setups be compared directly. We would be glad to share our scripts.