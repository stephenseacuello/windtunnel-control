# Drafts. Not sent. Edit freely.

Attachments for email 1:
- `out/URI_VAWT_Texture_Data_2026-10-01/URI_VAWT_Texture_Report_2026-10-01.pdf` (the report,
  18 pages, 0.9 MB);
- `out/URI_VAWT_Texture_Data_2026-10-01.zip` (10.5 MB): the 1 October raw files, derived tables and
  code. It also contains the PDF.

---

## 1. To Profs Sodhi and Jahangiri

**To:** sodhi@uri.edu, vahid.jahangiri@uri.edu
**Cc:** taegu.kang@uri.edu
**Subject:** Wind-tunnel report: peak power of the small VAWT with fuzzy-skin blades (1 October tests)

Dear Dr. Sodhi and Dr. Jahangiri,

Ahead of our meeting on Wednesday at 2:00 pm, I've attached the report that Taegu and I wrote on
the 1 October wind-tunnel tests, with a zip of the data.

We tested one small vertical-axis rotor with four blade sets. One was printed without fuzzy skin
and three with fuzzy-skin thicknesses of 0.05, 0.10 and 0.20 mm. Each set was swept twice through
14 wind speeds from 10 to 38 m/s.

**Main results**
- **Peak power.** The 0.10 and 0.20 mm sets gave 12.8% and 16.2% more peak electrical power than
  the plain set (95% intervals 10.1–15.5% and 13.5–19.0%). The 0.05 mm difference (1.8%) was not
  resolved.
- **Wind speed.** The gains depended on wind speed and were largest at 21–25 m/s.
- **Source of the gain.** At light load the 0.10 and 0.20 mm rotors turned 6.6% and 9.1% faster.
  The generator's voltage per rpm showed no resolved difference between rotors, so we infer that
  the gain arises in the rotor, not in the generator.
- **Surface roughness.** Measured roughness (Ra, Pa) did not rank the sets by power.

**Limits.** Each thickness was one print, mounted once, and the sets were run in order of
increasing thickness. The plain set also has coarser layers (0.2 against 0.1 mm). Attributing the
gains to fuzzy skin needs replicate prints, remounting and an interleaved run order (Section 10).

**How the surfaces were printed.** The College of Engineering's I²(s) Print Lab printed all four
sets.
- The Print Lab's Bambu Studio project specifies PLA on a Bambu Lab P1S with a 0.2 mm nozzle and
  0.1 mm layers.
- Fuzzy skin is painted on both faces of each blade. Only the fuzzy-skin thickness changes between
  sets.
- Of these settings, only the layer height could be confirmed on the printed blades.
- Details are in Section 2.2 and Table 1.

The zip holds the raw rig, rotor-speed and surface-scan files from 1 October, the derived tables
and the analysis code. One script (`7_code/build_report.py`) regenerates every number in the
report from the raw files.

Best regards,
Stephen

---

## 2. To Taegu, for the per-sample tachometer files

Reply in his thread "Accepted: Wind Tunnel Testing @ Thu Oct 1", sent to his Gmail (the address he
sent the data from).

Hi Taegu,

Thank you again for the RPM summaries and RPM.m. They are in the report, and you are listed as
co-author.

One more request, when you have time. The Drive links in your 2 October email ask me to sign in.
Could you share these eight files with seacuello@uri.edu, or attach them as a zip?

- sweep_v1_smooth_20261001_RPM.csv
- sweep_v1_smooth_repeat_20261001.csv
- sweep_v1_Ra20_20261001_RPM.csv
- sweep_v1_Ra20_repeat_20261001_RPM.csv
- sweep_v1_Ra40_20261001_RPM.csv
- sweep_v1_Ra40_repeat_20261001_RPM.csv
- sweep_v1_Ra80_20261001_RPM.csv
- sweep_v1_Ra80_repeat_20261001_RPM.csv

The unk file is not needed.

With these I can match your rotor speed to each 1-second load step and add the power coefficient
against tip-speed ratio. Two questions so I can line the files up with the rig's records:
1. Does each file record clock time (time of day), or only time from the start of the recording?
   If only elapsed time, roughly when did you start each recording?
2. What sensor gave the tachometer signal, and how many pulses does it give per revolution? RPM.m
   assumes one.

Thanks,
Stephen
