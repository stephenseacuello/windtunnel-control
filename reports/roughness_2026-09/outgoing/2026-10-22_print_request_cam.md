# Print request to Cam (I²(s) Print Lab), 22 Oct 2026

Draft, not sent. A request for estimates, not an order.

**To:** Cam, I²(s) Print Lab
**Subject:** Estimate request: one print round of VAWT blades with the 0.4 mm nozzle

---

Hi Cam,

Thank you for the project files and slicing screenshots on 12 October.

Could you give me a slice estimate (print time, filament and cost per blade, with your formula) for
one combined round, all printed with the settings of turbine_320.3mf: 0.4 mm nozzle, 0.12 mm
layers, 2 walls with a 0.42 mm outer-wall line width, and a fuzzy-skin point distance of 0.2 mm?
Only the fuzzy-skin thickness would change:

| Set | Fuzzy-skin thickness | Blades |
|---|---|---|
| Plain | none | 3 |
| FS 0.10 (your 40 RA) | 0.101 mm | 3 |
| FS 0.20 (80 RA) | 0.202 mm | 3 |
| FS 0.40 (new) | 0.40 mm | 3 |
| FS 0.80 (320 RA) | 0.805 mm | 3 |

If possible, all 15 on the same printer and filament, so the sets differ only in texture.

For FS 0.80, your 320 RA slice already gives 15 h 54 min and 71.59 g, which comes to $9.38 per
blade by your formula. Does FS 0.80 print reliably with 2 walls? Its 0.805 mm fuzzy-skin thickness
is almost twice the 0.42 mm outer-wall line width. If it needs a different setting, I would rather
use that setting for all five sets, so they stay comparable.

If this round works, I would later ask for a second print of each level, so that each has two.

This is a request for estimates, not an order yet: I will confirm after meeting the professors next
week.

Thanks again,
Stephen

---

Sources (not part of the email): settings, plate names, thicknesses and the 320 RA slice are from
`../inputs/print_lab_20261012/README.md`; the settings were re-read on 22 Oct from
`turbine_320.3mf` (SHA-256 `f1259971…`, as in `SHA256SUMS_3mf.txt`; fuzzy skin painted on
1,303,934 of 1,305,578 triangles, 0.805 mm and 0.2 mm as object overrides; line width 0.42 mm for
the outer wall, 0.45 mm for the inner). FS 0.40 = 0.40 mm is the value in the 7 Oct email
(`../MEETING_2026-10-07_Jahangiri.md`, follow-up). Cost, calculated:
0.5 × 15.9 h + (71.59 g / 1000) × $19.99/kg = $9.38. 0.805 / 0.42 = 1.92.
