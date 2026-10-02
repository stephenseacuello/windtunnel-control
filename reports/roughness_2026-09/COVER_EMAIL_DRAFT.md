# Drafts. Not sent. Edit freely.

Attachments for both: `report/report.pdf` (ship as `URI_VAWT_Roughness_Report_2026-10-01.pdf`)
and `out/URI_VAWT_Roughness_Data_2026-10-01.zip` (12.4 MB; already contains the PDF).

---

## 1. To Taegu first (before the full distribution)

**To:** taegu.kang@uri.edu
**Subject:** Your 27 July data in the roughness write-up. Could you check one section?

Hi Taegu,

Thanks again for bringing the Chroma load down for yesterday's session. Before I send the
roughness write-up to the professors, could you look over Section 4 and Appendix C? They use the
raw export from our 27 July test, and I would rather you correct anything I have inferred than
have it go out wrong.

To put the July numbers on the same basis as the rig, I rebuilt `Summary_Table.csv` from
`0727windturbine.csv`. The recipe in Appendix C reproduces all 64 values exactly, but parts of it
are inferred:

1. **Channels.** Is the map right? I have ch1 = DC voltage through a 4:1 divider, ch2 = current
   (2 A/V), and ch3 = a once-per-revolution pulse.
2. **Current sensor.** What are the part number, range and zero?
3. **Pulse.** How is the rotor pulse generated? It tracked cleanly up to 1900 rpm, which is better
   than the reed switch on the rig.
4. **June table.** Did the 5 June table use 50-sample averages?

The report now compares July with the rig's un-textured rotor from yesterday. The reprocessed
July values come out 5–33% lower, and I say plainly that this can't be read as a rotor
difference: the load was below the power peak and the current scale can't be checked from the
file. If you have time at the next session, running your DAQ in parallel with the Chroma on one
sweep would settle the current scale and give the rig the rotor speed it is missing.

Thanks,
Stephen

---

## 2. To everyone

**To:** vahid.jahangiri@uri.edu, yjeong@uri.edu, sodhi@uri.edu, taegu.kang@uri.edu
**Subject:** Wind-tunnel surface-texture results: report and data

Dear Professors, and Taegu,

Attached are the write-up of the surface-texture wind-tunnel tests and the complete data package.

**Result.** On 1 October we ran all four blade sets on the same day, mounting each one twice.
Against the un-textured rotor, the 0.101 mm and 0.202 mm fuzzy-skin rotors produced 12.8% and
16.2% more peak electrical power over 10–38 m/s. The two mountings of each rotor agreed to within
1%, so both gains are well resolved. The 0.050 mm rotor's gain, 1.8%, is marginal. The gain sits in
the open-circuit voltage, consistent with the rotor turning faster in the same wind (rotor speed
was not measured). The August–September single runs reproduce to within 1–3%.

**Surface measurement.** Keyence scans show that measured Ra does not follow the labels or the
power. Ra is 8–10 µm on all three textured sets, and highest (13 µm) on the un-textured set,
whose 0.2 mm layer lines are a regular texture of their own. Fuzzy-skin thickness is the variable
that orders the power.

**Caveats.** The rotors were run in order of increasing texture; Section 3.4 gives the evidence
against drift. The un-textured set was printed with 0.2 mm layers against about 0.1 mm for the
Ra 20 and Ra 40 sets, so it differs in more than texture. There is one print per texture level. The rig measures
electrical power, not the aerodynamic power coefficient.

**Your open requests.**
- *Dr. Jeong, comparison with the initial test:* Section 4. The 5 June values sit mostly within
  the band of the textured rotors; the rotor and processing differ, so it is a consistency check.
- *Dr. Jahangiri, which blade exactly:* Table 2 lists what is recorded and measured for each set.
- *Fault-testing plan:* Section 6.1 proposes a starting point. Could we find a time to agree it
  before any fault blades are printed?

**Attached.**
- `URI_VAWT_Roughness_Report_2026-10-01.pdf` (11 pages)
- `URI_VAWT_Roughness_Data_2026-10-01.zip`: every raw file unmodified, the surface scans, a data
  dictionary, checksums and the analysis code. One script regenerates every number in the report.

Slides will follow once we have discussed the results.

Best regards,
Stephen
