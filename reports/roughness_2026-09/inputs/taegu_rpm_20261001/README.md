# Rotor speed, 1 October 2026 session (T. Kang)

T. Kang recorded rotor speed during the 1 October 2026 tunnel session on his own data
acquisition. The rig did not log rotor speed. This folder holds what he sent.

## `processed/`: received by email, 2 October 2026, 21:51 EDT

Saved byte for byte from the attachments of his message "I finished processing the data."

| file | content |
|---|---|
| `RPM.m` | His MATLAB script that produced the summaries (comments in Korean; summarised below). |
| `sweep_v1_<run>_20261001_RPM_summary.csv` | One per run. Columns `Setting_RPM`, `Measured_RPM`, `Pulse_Count`. |
| `sweep_v1_smooth_repeat_20261001_summary.csv` | Plain run 2. Same format, named without `_RPM` as received. |

- The file stems match the rig's run names (`logs/sweep_<run>_*.csv`).
- `v1_unk` is the fifth blade set, which the report excludes. Its summary is kept here for
  completeness; the analysis does not read it.

| SHA-256 | file |
|---|---|
| `1c6cb1c344d826474bb3c22491cb3a545765e1410b5779330c3fdf98944bb6c5` | `RPM.m` |
| `ebc160ff3e81aa135a6ab9395232f7297c72a3b73505516eab55f2f29ebb1ef6` | `sweep_v1_Ra20_20261001_RPM_summary.csv` |
| `81ad0742bb5e5f90b95e62fe6a640bd48eeba3f7312f445750996db89f117a51` | `sweep_v1_Ra20_repeat_20261001_RPM_summary.csv` |
| `af95aa0e737fbb56628c508dc34e3ea2c155cfdfae2187c56173d93d3161ec93` | `sweep_v1_Ra40_20261001_RPM_summary.csv` |
| `63f2f4f22f560ba44ba58ea78307fdbd7ea3000b0414736a2b4333388240b377` | `sweep_v1_Ra40_repeat_20261001_RPM_summary.csv` |
| `d546278a9574a6e99aaa49f6822f1920c38da11939db574d931b6f45d0bcf06f` | `sweep_v1_Ra80_20261001_RPM_summary.csv` |
| `7f1f90f165da70943aae47eb4f33aec8a9a86ad4e1b05e3038f6ac4e6537eee9` | `sweep_v1_Ra80_repeat_20261001_RPM_summary.csv` |
| `1b1cfb62668d913348a40a173ed3d097748453fa40db93b79949cfec74777abf` | `sweep_v1_smooth_20261001_RPM_summary.csv` |
| `10279a4641b3d35061212a4f46da3c11a971915322d3880bffed7e43832b75d9` | `sweep_v1_smooth_repeat_20261001_summary.csv` |
| `372adeb1ae8a25533414e19ba5659976b1eeedb858ccd49398141643b3c0d295` | `sweep_v1_unk_20261001_RPM_summary.csv` |

## `raw/`: the per-sample records, shared 6 October 2026

He shared these as Google Drive links on 2 October; access was granted to S. Eacuello on
6 October, and the files were downloaded that day. They are stored gzip-compressed (`gzip -9 -n`)
under their original names. `SHA256SUMS_uncompressed.txt` holds the checksums of the files as
downloaded, and `SHA256SUMS_gz.txt` those of the stored copies. Every file decompresses to its
original checksum.

| file | run | size (MB) |
|---|---|---|
| `sweep_v1_smooth_20261001_RPM.csv.gz` | Plain, run 1 | 39.5 |
| `sweep_v1_smooth_repeat_20261001.csv.gz` | Plain, run 2 (named without `_RPM`) | 17.5 |
| `sweep_v1_Ra20_20261001_RPM.csv.gz` | FS 0.05, run 1 | 16.8 |
| `sweep_v1_Ra20_repeat_20261001_RPM.csv.gz` | FS 0.05, run 2 | 16.9 |
| `sweep_v1_Ra40_20261001_RPM.csv.gz` | FS 0.10, run 1 | 17.4 |
| `sweep_v1_Ra40_repeat_20261001_RPM.csv.gz` | FS 0.10, run 2 | 17.6 |
| `sweep_v1_Ra80_20261001_RPM.csv.gz` | FS 0.20, run 1 | 18.3 |
| `sweep_v1_Ra80_repeat_20261001_RPM.csv.gz` | FS 0.20, run 2 | 18.5 |

The `unk` record was not shared and is not needed.

**Format.** Columns:
- `Relative Time` (s, from the start of recording);
- `Date`, `Time Stamp UTC`;
- five channels in volts;
- `Chn 1 Events`.

The sampling rate is 359.97 Hz.

**Channels.** Five voltage channels, called c1–c5 here.

| channel | identity |
|---|---|
| c3 (sixth column) | The tachometer read by `RPM.m`: a proximity sensor triggered by a magnet glued to one blade of each rotor, one pulse per revolution. |
| c1 | Tracks the rig's terminal voltage (r ≥ 0.995, about 0.25 × V). A divided generator voltage, inferred, not documented. |
| c2, c4, c5 | Not documented. They correlate with voltage and speed (r 0.74–0.91). To be confirmed with T. Kang. |

**Time base** (checked 6 Oct against the rig's per-dwell `t_unix`):
- `Relative Time` is real time. Fitting the rig's dwell voltages with
  V = k·n − R·I + b gives a clock drift within ±0.5%.
- The `Time Stamp UTC` column advances about 8% faster than real time within a file. This is a
  logging artefact; it gains 91 s over the 19-minute Plain run-1 file. Use it only at the first
  sample of each recording segment.
- Recording was paused and resumed in some files (`Resume` in `Chn 1 Events`). `Relative Time`
  skips the pause, so each segment is anchored at its own first time stamp.
- With that anchoring, the DAQ clock agrees with the rig clock within 1–4 s per run.
- RPM.m's speeds use `Relative Time`, so the summaries are unaffected by the time-stamp drift.

## What `RPM.m` does

1. Reads column F, the tachometer, of a per-run record sampled at 359.97 Hz. A pulse is a rise
   through −0.75 V (baseline about −1.5 V, pulse about 0 V), and one pulse is one revolution. The
   sensor is a proximity sensor triggered by a magnet glued to one blade of each rotor
   (S. Eacuello, 5 Oct).
2. Counts pulses in 5 s windows. It keeps the windows from the first one above 40 rpm to the
   fastest one.
3. Splits those windows into the 14 fan set points (500–1800 rpm) at rises of more than 40 rpm
   between windows. Rises within two windows count as one, and the 13 largest are kept.
4. For each set point:
   - converts every pulse interval to a speed, 60 / (interval in s);
   - keeps 20–1000 rpm and rounds to 1 rpm;
   - reports the most frequent value (`Measured_RPM`) and the pulse count (`Pulse_Count`).

## Notes for use

- **Resolution.** A pulse interval is a whole number k of samples, so a per-revolution speed is
  60 × 359.97 / k (… 720, 745, 771, 800, 831, 864 rpm), and `RPM.m` rounds it to 1 rpm.
  - `Measured_RPM` is therefore resolved to the larger of 1 rpm and n² / (60 × 359.97).
  - That is 1.1% at 90 rpm, 0.7% near 147 rpm and 4.0% at 864 rpm.
- **What the value means.** The mode is taken over the whole set point (settle and load
  ladder). From 600 rpm the protocol holds the load at 0 A while the fan settles. The rotor is
  fastest and steadiest then, so the report takes the most frequent speed as the light-load speed.
  - The rig's terminal voltage at the first load step, divided by `Measured_RPM`, is
    31.5 mV/rpm over the 104 run and set-point values from 600 rpm (8 runs × 13 set points;
    coefficient of variation 1.7%).
  - The ratio does not differ between rotors (largest difference +0.7%
    [−0.7, +2.1], Tukey).
  - This supports both the light-load reading and the matching of set points between the two
    records.
- **The first set point.** At 500 rpm the fan starts and settles with the load at 10 mA, not 0 A.
  The first-step voltage there implies a speed 3–12% above `Measured_RPM`, so the report does
  not use the 500 rpm values.
- **The last set point.** The 1800 rpm set point ends at the fastest 5 s window, so its
  `Pulse_Count` is small.

## Where it is used

- `src/data.py` (`rotor_speed()`) reads these files.
- The report uses them for light-load speed and tip-speed ratio.
- The data package ships them in `2_rotor_speed/`, without `v1_unk`.
