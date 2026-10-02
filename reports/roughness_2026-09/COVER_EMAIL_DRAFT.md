# Drafts. Not sent. Edit freely.

Attachments: `report/report.pdf` (send as `URI_VAWT_Roughness_Report_2026-10-01.pdf`) and, for
the group, `out/URI_VAWT_Roughness_Data_2026-10-01.zip` (12.4 MB; already contains the PDF).
Draft 1 is also saved in Gmail Drafts, without the attachment.

---

## 1. To Taegu first (before the full distribution)

**To:** taegu.kang@uri.edu
**Subject:** Roughness write-up: your July data (Section 4, Appendix C) and a few questions

Hi Taegu,

Thanks again for bringing the Chroma load down on Thursday. Before the roughness write-up goes to
Professors Jahangiri, Jeong and Sodhi, I'd like you to check the part that uses your data. The
full report is attached; your part is Section 4 and Appendix C.

**What the report says about the lab tests**

1. I rebuilt `Summary_Table.csv` from `0727windturbine.csv`, and all 64 values reproduce exactly:
   - The record is cut into 17 equal slices, and the middle half of each of the first 16 is used
     (3,742 samples, 10.4 s).
   - V = 4 × ch1 and I = 2 × (ch2 − 2.5).
   - Vdc_max, Idc_max and Pdc_max are the separate maxima of V, I and V·I over that window.
2. Because Pdc_max is a maximum of raw 360 Hz samples, it picks up current-sensor noise (about
   31 mA rms), which adds roughly 0.11 A × V. At 500–700 rpm the load was off, so the power
   tabulated there is noise.
3. I reprocessed the July data on the rig's basis: a 1 s mean, with the current zero taken after
   load-off.
   - On that basis the July values are 5–33% below the rig's un-textured rotor from Thursday.
   - The report says plainly that this is not a rotor difference. Your load was held below the
     power peak, so those values are lower bounds, and the current scale can't be checked from the
     file.
   - The free-running voltages, which need no current calibration, agree within 15%.
4. The 5 June values differ from the rig's un-textured rotor by −5% to +35% (geometric mean
   +9%). The report treats that as a consistency check only.

**What I need from you**

1. **Channel map.** Is ch1 the DC bus through a 4:1 divider, ch2 a Hall current sensor at 2 A/V
   about a 2.5 V zero, and ch3 a once-per-revolution pulse? What is ch1's input range?
2. **Current sensor.** What are its part number and range, and how is its zero set? This is the
   one number that decides whether the July gap is real.
3. **Rotor pulse.** What generates it? It tracked cleanly to 1900 rpm, better than our reed
   switch, and drops about one revolution in nine at 2000 rpm.
4. **Processing.** Did the 5 June table use 50-sample averages? Could you share the 5 June raw
   export, and your processing script if that's easy, so I can put June on the same basis?
5. **Rotors.**
   - Was the 27 July no-texture rotor the same blade set we ran on Thursday as the baseline?
   - Do you know who printed it, and with what settings? Our scans show 0.2 mm layers on it,
     against about 0.1 mm on the Ra 20 and Ra 40 sets.
   - Was the 5 June rotor the original, pre-replica rotor?
6. **Next session.** Could we run your DAQ in parallel with the Chroma for one sweep? That would
   calibrate your current channel against the Chroma and give the rig the rotor speed it is
   missing. I'd also like to rerun with each rotor remounted between runs and test a reprinted
   no-texture set, so we would need the Chroma again.

Please correct anything I have inferred wrongly. I'd rather fix it before it goes out.

Thanks,
Stephen

---

## 2. To everyone

**To:** vahid.jahangiri@uri.edu, yjeong@uri.edu, sodhi@uri.edu, taegu.kang@uri.edu
**Subject:** Wind-tunnel surface-texture results: report and data

Dear Professors, and Taegu,

Attached are the write-up of the surface-texture wind-tunnel tests and the complete data package.

**Result.** On 1 October we ran all four blade sets on the same day, each swept twice.

- Against the un-textured rotor, the 0.101 mm and 0.202 mm fuzzy-skin rotors produced 12.8% and
  16.2% more peak electrical power over 10–38 m/s.
- Allowing for mounting variation, estimated from the August–September runs, the 95% intervals are
  +5 to +21% and +9 to +24%. Both gains are resolved; the 0.050 mm rotor's 1.8% is not.
- The gain sits in the open-circuit voltage. That is consistent with the rotor turning faster in
  the same wind, but rotor speed was not measured.

**Surface measurement.** Keyence scans show that measured Ra does not follow the labels or the
power:
- Ra is 8–10 µm on all three textured sets.
- It is highest (13 µm) on the un-textured set, whose 0.2 mm layer lines are a regular texture of
  their own.

In the point estimates, power rises with fuzzy-skin thickness, not with measured Ra (only one of
the three steps in thickness is statistically resolved).

**Caveats.**
- Each rotor was mounted once on 1 October, and the rotors were run in order of increasing
  texture. Section 3.4 gives the evidence against drift.
- The un-textured set was printed with 0.2 mm layers, against about 0.1 mm for the Ra 20 and
  Ra 40 sets, so it differs in more than texture.
- There is one print per texture level.
- The rig measures electrical power, not the aerodynamic power coefficient.

**Your open requests.**
- *Dr. Jeong, comparison with the initial test:* Section 4. The 5 June values fall inside the
  band of the textured rotors at half the set points (5 of 10). The rotor and processing differ, so
  this is a consistency check.
- *Dr. Jahangiri, which blade exactly:* Table 2 lists what is recorded and measured for each set.
  The slicer file holds one blade per plate for the 0.101 and 0.202 mm sets (0.2 mm nozzle,
  0.10 mm layers, PLA); it conflicts with the run notes on material.
- *Fault-testing plan:* Section 6.1 proposes a starting point. Could we find a time to agree on it
  before any fault blades are printed?

**Attached.**
- `URI_VAWT_Roughness_Report_2026-10-01.pdf` (12 pages)
- `URI_VAWT_Roughness_Data_2026-10-01.zip`: every raw file, the surface scans, a data dictionary,
  checksums and the analysis code. One script regenerates every result in the report.

Slides will follow once we have discussed the results.

Best regards,
Stephen
