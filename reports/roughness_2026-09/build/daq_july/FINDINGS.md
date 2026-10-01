# Jeong lab, 27 Jul 2026, no-texture baseline — the DAQ export reverse-engineered

> **Status: UNVERIFIED first pass** (single analyst, 30 Sep 2026). An independent
> verification is scheduled before any of this goes into the report. Regenerate
> with `python3 analyze_july.py` (about 20 s).

Source: `inputs/jeong_lab/2026-07-27_no_texture_baseline/0727windturbine.csv` (127,208 rows)
and the lab's `Summary_Table.csv`. Numbers are in `key_numbers.json`, `july_segments.csv`,
`july_pi_points.csv` and `july_timeseries_decimated.csv`.

## Bottom line
1. **All four measured Summary_Table columns are reproduced exactly.** The maximum relative
   error is 3.1e-15 across 16 settings × 4 columns. The recipe is in §4.
2. **Pdc_max is dominated by current-sensor noise, not power.** It is the maximum of 3,742
   instantaneous 360 Hz V·I samples, and the current channel carries σ = 31 mA of white
   noise. At the Pmax sample the current is always 0.095–0.144 A above its 1 s mean. The bias
   is ΔP ≈ 0.110 A × Vdc, from +0.32 W at 500 rpm to +1.34 W at 2000 rpm.
3. **At 500–700 the load was at 0 A, so the 0.333 W at 9.8 m/s is entirely noise.** The same
   recipe applied to a 10.4 s window with the load physically disconnected returns
   Pdc_max = 1.50 W and Idc_max = 0.112 A with no current flowing.
4. **Near 36 m/s, 3.82 W becomes 2.69 W** with 1 s averaging, the rig's convention. That is
   below, not above, the rig's textured prints (Ra20 3.03, Ra40 3.36, Ra80 3.53 W).
5. **Do not compare Summary_Table's Pdc_max with the rig.** Use the reprocessed 1 s powers
   (§8), with the caveats listed there.

## 1. File and clock
| item | finding | evidence |
|---|---|---|
| Sample rate | **360 Hz**, as `Relative Time` says | Mains line on ch3/4/5 at rest at 60.01–60.15 Hz at 360 Hz (would be 55.6 Hz at 333 Hz) |
| `Time Stamp UTC` | synthetic, exactly `floor(n × 3 ms)` | the model reproduces all 381 second boundaries |
| Record length | **353.35 s**, not the 381 s the stamps span | true end about 14:51:27 |
| ADC step | 1.2207 mV = 5/4096 V on all channels | unique-value spacing |

## 2. Channel map
| ch | what it is | scale (lab) | evidence |
|---|---|---|---|
| **ch1** | **DC bus voltage** (after the rectifier and a capacitor) through a **4:1 divider** | Vdc = 4·ch1 | Vdc_max are exact multiples of 4 LSB. Jumps to 19.7 V (open circuit) when the load switches off at 329.64 s. After the rotor stops it decays with **τ = 18.4 s**, a capacitor discharge. The 4.9976 V maximum is a single-sample spike, not clipping, but open circuit at 2000 (~21.8 V → ch1 ≈ 5.45 V) would exceed a 0–5 V range. |
| **ch2** | **Hall-effect DC current sensor**, mid-rail zero | Idc = 2·(ch2 − 2.5), i.e. 500 mV/A | Idc_max are exact multiples of 2 LSB. Load-off output is **2.4961 V**, so the lab's current has a **−7.8 mA** offset. Noise σ = 31 mA, white, the same loaded and unloaded. |
| **ch3** | **Once-per-revolution rotor pulse** | 1 pulse = 1 rev | 1.7 Hz at 500 to 11.1 Hz at 2000. **Skips revolutions above about 10 Hz** (14 skipped in the 2000 window). |
| ch4, ch5 | same pulse train at 0.481× and 0.217× | – | r = 0.998 / 0.993 |

There is no wind-speed channel. Wind_Speed_ms is a lookup by fan setting, identical in the
June and July tables.

## 3. Run protocol and segmentation
- **Segmentation.** The lab cut the record into 17 equal slices of 7482 samples (20.78 s)
  and took the middle half (3742 samples, 10.39 s) of each of the first 16; the 17th
  (spin-down) is discarded.
- **Actual dwells.** Detected from rotor step-ups, the dwells were hand-timed at 12–41 s, so
  fixed slices misattribute data:
  - the "1300" window is two-thirds 1400 data;
  - 1500 and 1600 are about 30% previous-setting data;
  - the 41 s "1400" dwell may hide a fan step at about 197 s (unresolved).
- **Load: constant current, raised by hand, cumulatively.**
  - 0 A at 500–700;
  - 0.013–0.016 A at 800;
  - rising to 0.35 A at 2000.
- **Not a sweep through the maximum power point.** Each setting traces only a short fragment
  of its P–I curve.

## 4. The recipe (reproduces Summary_Table)
    L   = floor(N/17) = 7482;  win_k = samples [k*L+1870, k*L+5611]  (3742 samples), k = 0..15
    Vdc = 4*ch1 ;  Idc = 2*(ch2 - 2.5)
    Vdc_max, Idc_max, Pdc_max = independent maxima of Vdc, Idc and Vdc.*Idc over win_k (raw 360 Hz)
    Measured_RPM = 60 * (# upward jumps in ch3 > thr) / (t[end]-t[start]), 1 pulse/rev
    Wind_Speed_ms = lookup by setting

Max |relative error|: Measured_RPM 2.7e-15, Vdc_max 0, Idc_max 5.7e-16, Pdc_max 3.1e-15.

**Measured_RPM errors:**
- +3.6% at 900 and +2.8% at 1300 (double counts);
- −10.9% at 2000 (skipped revolutions: true 667 rpm vs 594.7 reported).

## 5. The averaging bias
The table compares the lab's Pdc_max with the maximum 1 s mean power, current zero-corrected.

| setting | lab Pdc_max [W] | max 1 s mean P [W] | ratio |
|---|---|---|---|
| 500 | 0.333 | 0.009 | 35× (load at 0 A) |
| 900 | 0.768 | 0.194 | 3.9× |
| 1300 | 1.825 | 1.101 | 1.7× |
| 1700 | 3.818 | 2.694 | 1.42× |
| 2000 | 5.602 | 4.267 | 1.31× |

- **ΔP ≈ 0.110 A × Vdc.** It is sensor noise, not rectifier ripple: voltage and current noise
  are uncorrelated (r = −0.02).
- **Null test.** With the load disconnected the recipe still returns Pdc_max = 1.50 W.
- **June was processed differently.** June's table carries the quantisation fingerprint of
  50-sample moving averages and a calibrated zero.
- **June-style processing of July** gives 0.039 W at 500 (June: 0.046 W), so June → July at
  9.8 m/s is a processing change, not a rotor change.

## 6. Generator consistency
- **EMF line** from zero-current data: Voc = 0.03342·rpm − 0.448 V.
- **Constant-speed internal resistance:** median 26.8 Ω (IQR 26.2–28.0), on the lab's current
  scale.
- **Valid fixed-wind apparent Thevenin fits:**
  - 700: 96 Ω, MPP 0.076 W;
  - 900: 82 Ω, MPP 0.189 W;
  - 1100: 65 Ω, MPP 0.429 W.

## 7. Like-for-like vs the rig
The table compares the lab's 1 s max over the actual setting (zero-corrected) with the rig's
dwell-mean MPP.

| setting | lab 1 s max [W] | rig Ra20 | Ra40 | Ra80 | lab ÷ Ra20 |
|---|---|---|---|---|---|
| 900 | 0.194 | 0.273 | 0.297 | 0.308 | 0.71 |
| 1100 | 0.452 | 0.643 | 0.751 | 0.804 | 0.70 |
| 1300 | 0.918 | 1.329 | 1.401 | 1.446 | 0.69 |
| 1500 | 1.906 | 2.081 | 2.194 | 2.257 | 0.92 |
| 1700 | 2.665 | 3.033 | 3.358 | 3.529 | 0.88 |
| 1800 | 3.224 | 3.794 | 4.096 | 4.498 | 0.85 |

**Caveats on this comparison:**
- the lab's load current was mostly *below* the MPP current, so these values are lower bounds
  on its maximum power;
- the current-sensor scale (×2 = 500 mV/A) matches no common part and is unverified; a
  25–45% under-read would fit the source-resistance comparison;
- wind calibrations differ by up to 4.4%.

**Bottom line:** the no-texture run cannot resolve a roughness effect at this precision.

## 8. Recommendation
**Do not:**
- plot or ratio Summary_Table's Pdc_max, Idc_max or Vdc_max against the rig;
- quote July power at 500–700;
- compare the June and July tables with each other;
- use Measured_RPM for tip-speed ratio.

**If the run is used:**
- use the reprocessed 1 s zero-corrected power (`july_segments.csv`, `seg_P_1s_movmax_zc`)
  for 800–2000 only;
- label it "at the lab's CC setpoint, not maximum power";
- state each wind calibration;
- carry a +0/+45% current-scale systematic.

**Ask the lab for:**
1. a CC sweep past the power peak with ≥ 1 s dwells;
2. dwell means rather than raw maxima;
3. the current-sensor part and its zero calibration;
4. a tach that does not skip revolutions;
5. confirmation of the ch1 input range.
