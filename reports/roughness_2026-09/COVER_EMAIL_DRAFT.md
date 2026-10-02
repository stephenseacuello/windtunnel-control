# Drafts. Not sent. Edit freely.

Attachments for the group email:
- `out/URI_VAWT_Texture_Data_2026-10-01/URI_VAWT_Texture_Report_2026-10-01.pdf` (the report,
  14 pages);
- `out/URI_VAWT_Texture_Data_2026-10-01.zip` (10 MB; it also contains the PDF).

---

## 1. To everyone

**To:** vahid.jahangiri@uri.edu, yjeong@uri.edu, sodhi@uri.edu, taegu.kang@uri.edu
**Subject:** Wind-tunnel fuzzy-skin texture test (1 October): report and data

Dear Professors, and Taegu,

Attached are the report on Thursday's wind-tunnel session and the complete data package.

We compared four blade sets of the same rotor: no fuzzy skin, and fuzzy skin of 0.05, 0.10 and
0.20 mm (the sets previously labelled Ra 20, Ra 40 and Ra 80). Each rotor was swept twice through
14 wind speeds from 10 to 38 m/s.

**Results**
- **Peak power.** Against the plain rotor, the 0.10 mm and 0.20 mm rotors produced 12.8% and
  16.2% more peak electrical power (Tukey 95% intervals +10 to +16% and +13 to +19%). The 0.05 mm
  rotor's 1.8% is not resolved.
- **Wind speed.** The advantage depends on wind speed. The power coefficient of the 0.10 and
  0.20 mm rotors rises more steeply, and at lower wind speed, than the plain rotor's, so the gains
  are largest at 21–25 m/s.
- **Source of the gain.** It appears in the generator's open-circuit voltage, which indicates that
  the textured rotors turn faster at light load.
- **Surface roughness.** Measured Ra does not rank the rotors by power. The 0.05 and 0.10 mm sets
  have similar roughness but differ by 11% in power. From one scan field per set, we can't confirm
  that their realised texture differs.

**Limits**
- Each texture level is one print, mounted once, and the rotors were run in order of increasing
  texture.
- The 0.10 and 0.20 mm differences survive a linear-drift fit and would survive mounting
  variation up to about 2–3%. Mounting variation was not measured, so attributing them to texture
  still needs replicate prints and remounting; Section 9 proposes that next round.
- Tip-speed ratio and C_P(λ) will be added once Taegu's rotor-speed record is joined to the data.

**Your requests**
- Blade identity: Table 2.
- Fault-testing plan: Section 9.1. Could we find a time to agree on it before any fault blades are
  printed?

One script in the zip (6_code/build_report.py) regenerates every result, table and data figure
in the report from the raw files.

Best regards,
Stephen

---

## 2. Optional: to Taegu, for the rotor speed

**To:** taegu.kang@uri.edu
**Subject:** Rotor RPM from Thursday's wind-tunnel session

Hi Taegu,

Thanks again for bringing the Chroma load on Thursday. Could you send me your rotor RPM record
from the session, with time stamps if possible? I'd line it up with our eight runs (15:50–18:24 on
our laptop clock) and add tip-speed ratio to the report.

Thanks,
Stephen
