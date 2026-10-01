# Drafts. Not sent. Edit freely.

---

## 1. To Taegu first (before the full distribution)

**To:** taegu.kang@uri.edu
**Subject:** Your 27 July data in the roughness write-up. Could you check one section?

Hi Taegu,

Before I send the roughness write-up to the professors, could you look over Section 6 and
Appendix C? They use the raw export from our 27 July test. Thank you for sharing the full
file; without it none of this would have been possible.

To put the July numbers on the same basis as the rig, I rebuilt `Summary_Table.csv` from
`0727windturbine.csv`. The recipe in Appendix C reproduces all 64 values exactly. Some of it
is inferred, though, and you would know better:

1. **Channels.** Is the map right? I have ch1 = DC voltage through a 4:1 divider, ch2 =
   current (2 A/V), and ch3 = a once-per-revolution pulse.
2. **Current sensor.** What is the part number, range and zero?
3. **Pulse.** How is the rotor pulse generated? It tracked cleanly up to 1900 rpm, which is
   better than the reed switch on the rig.
4. **June table.** Did the 5 June table use 50-sample averages?

If you're free during tomorrow's session, it would be great to run the DAQ in parallel with the
Chroma load on one sweep. That would calibrate the current channel directly and give the rig
the rotor speed it's missing.

Thanks,
Stephen

---

## 2. To everyone (after the 1 Oct runs are folded in)

**To:** vahid.jahangiri@uri.edu, yjeong@uri.edu, sodhi@uri.edu, taegu.kang@uri.edu
**Subject:** Wind tunnel surface-texture results: report and data

Dear Professors, and Taegu,

Attached are the write-up of the surface-texture wind-tunnel tests and the complete data
package.

**What we found.** On one mounting each, rotors printed with 0.10 mm and 0.20 mm of fuzzy-skin
texture produced about 8% and 14% more peak electrical power than the 0.05 mm rotor. This
held at every wind speed from 10 to 38 m/s. The extra power comes with the rotor turning faster
in the same wind; it does not come from the electrical side. [After 1 Oct: one sentence on what
the remounts showed.]

**What it does not yet show.** It does not show that texture, rather than mounting or print
differences, is the cause. The Ra labels (20/40/80) were never measured; the report uses
fuzzy-skin thickness as the variable. The rig measures electrical power, not the power
coefficient, because it does not yet record rotor speed.

**Your open requests.**
- *Dr. Jeong (comparison with the initial test):* §6.1. The 5 June values sit within the range
  of the three textured rotors.
- *Dr. Jahangiri (which blade exactly):* §2.2 lists what is known and what is inferred.
- *Fault-testing plan:* §9.1 proposes a starting point. Could we find a time to agree it before
  printing any fault blades?

**Attached.**
- `URI_VAWT_Roughness_Report_2026-09-30.pdf`
- `URI_VAWT_Roughness_Data_2026-09-30.zip`: every raw file, unmodified, with a data dictionary,
  checksums and the analysis code. Running one script regenerates every number in the report.

Slides will follow once we've discussed the results.

Best regards,
Stephen
