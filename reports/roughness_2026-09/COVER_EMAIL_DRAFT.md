# Drafts. Not sent. Edit freely.

Attachments for the group email:
- `out/URI_VAWT_Texture_Data_2026-10-01/URI_VAWT_Texture_Report_2026-10-01.pdf` (the report,
  18 pages);
- `out/URI_VAWT_Texture_Data_2026-10-01.zip` (10.5 MB; it also contains the PDF).

---

## 1. To everyone

**To:** vahid.jahangiri@uri.edu, yjeong@uri.edu, sodhi@uri.edu, taegu.kang@uri.edu
**Subject:** Peak power of the small VAWT with 3D-printed textured blades, wind-tunnel report and data (1 October tests)

Dear Professors, and Taegu,

Attached are Taegu's and my report on Thursday's wind-tunnel session and the complete data package.

We compared four blade sets of the same rotor, printed without fuzzy skin and with fuzzy skin of
0.05, 0.10 and 0.20 mm (the sets previously labelled Ra 20, Ra 40 and Ra 80). Each rotor was swept
twice through 14 wind speeds from 10 to 38 m/s. Taegu's tachometer gave the rotor speed at light
load.

**Results**
- **Peak power.** The 0.10 and 0.20 mm rotors produced 12.8% and 16.2% more peak electrical
  power than the plain rotor (Tukey 95% intervals 10.1 to 15.5% and 13.5 to 19.0%). The 0.05 mm
  rotor's 1.8% was not resolved.
- **Wind speed.** The gains depended on wind speed and were largest at 21–25 m/s.
- **Source of the gain.** Averaged over wind speed, the gains came with a higher extrapolated
  open-circuit voltage and no resolved change in source resistance; where they were largest, a lower
  source resistance also contributed. At light load the 0.10 and 0.20 mm rotors turned 6.6% and
  9.1% faster than the plain rotor, with no resolved difference in voltage per rpm. We infer that
  the gain arises in the rotor, not in the generator.
- **Surface roughness.** Measured Ra and Pa did not rank the rotors by power. The 0.05 and 0.10 mm
  sets have similar roughness but differ by 10.8% in power. One scan field per set does not
  confirm that their realised texture differs.

**Limits**
- Each texture level was one print, mounted once, and the rotors ran in order of increasing texture.
  The plain set also has a coarser layer period (0.20 against 0.10 mm).
- The 0.10 and 0.20 mm differences survive a linear-drift fit and would survive mounting variation
  up to 2.0–2.6%. Attributing them to fuzzy skin requires replicate prints, remounting and an
  interleaved run order (Section 10).
- Rotor speed is known at light load only, one value per wind speed. C_P(λ) along each load ladder
  needs Taegu's per-sample tachometer records joined on time.

**Your requests**
- Blade identity and print records are in Table 1. The College of Engineering's I²(s) Print Lab
  printed all four sets.
- An outline of the fault-testing plan is in Section 10.1. Could we find a time to agree on it
  before any fault blades are printed?

One script in the zip (7_code/build_report.py) regenerates every result, table and data figure
in the report from the raw files.

Best regards,
Stephen

---

## 2. Optional: to Taegu, for the per-sample tachometer files

Send to his Gmail (the address he sent the data from).
**Subject:** Re: Wind Tunnel Testing @ Thu Oct 1

Hi Taegu,

Thank you for the RPM summaries and RPM.m. They are in the report (Sections 3.3 and 6.5), and the
generator voltage tracks your speeds at every set point from 600 rpm.

The nine Drive links ask me to sign in. Could you share the `*_RPM.csv` files with
seacuello@uri.edu, or attach them? With them I can line your speed up with each 1 s load step and
add C_P(λ).

Thanks,
Stephen
