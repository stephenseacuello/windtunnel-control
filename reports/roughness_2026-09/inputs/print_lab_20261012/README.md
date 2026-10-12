# Print Lab slicing results, 12 October 2026

Source: reply from the I²(s) Print Lab (Cam), 12 Oct 2026, to the 8 Oct settings-check email. It
contained these four Bambu Studio "Slicing Result" screenshots and the statement: "All turbine blades
so far have been printed out of PLA with a 0.2mm nozzle ... the RA 320 blades will be printed with a
0.4mm nozzle." Its cost formula is 0.5 × hours + material/1000 × ($/kg).

The project files linked in that email (`turbine_p2mm.3mf`, `turbine_320.3mf`) are not yet in the
repo. The plate names are the nominal "RA" labels; the measured Ra is in the report.

All four screenshots show one blade per plate, on a Textured PEI plate, with a brim.

| Plate | Fuzzy skin | Nozzle | Print time (total) | Filament | Material cost |
|---|---|---|---|---|---|
| 10 RA | 0.025 mm; never tested | 0.2 mm | 6 h 04 min | 12.69 m, 38.46 g | $0.77 |
| 40 RA | 0.101 mm (FS 0.10) | 0.2 mm | 7 h 40 min | 12.89 m, 39.08 g | $0.78 |
| 80 RA | 0.202 mm (FS 0.20) | 0.2 mm | 8 h 41 min | 13.41 m, 40.63 g | $0.81 |
| 320 RA | 0.805 mm; planned | 0.4 mm | 15 h 54 min | 23.62 m, 71.59 g | $1.43 |

**Fuzzy-skin thickness.** The values for the first three plates come from the slicer project
`../slicer/turbine_default_summary.json`. The 320 RA value, 0.805 mm, is the agreed setting
(meeting of 7 Oct).

**Material cost.** It is about $20/kg in these screenshots (38.46 g gives $0.77), against
$24.99/kg in `turbine_default.3mf`.

**Points to confirm with the Print Lab:**
- **Plain set.** The Plain set's layer period measures 0.2 mm (report, Table 1). The project's
  P1S 0.2-nozzle profile allows at most 0.14 mm layers (`max_layer_height`). An untextured blade
  was quoted at about 2 h in July (Cam via T. Richards, 8 Jul), against 6 h or more for any
  0.2 mm-nozzle slice here. So "all blades with a 0.2 mm nozzle" probably does not hold for Plain
  (*inferred*).
- **FS 0.05.** No slice is shown for the tested FS 0.05 ("Ra 20") set.
- **Estimates only.** These are slicer estimates, not logged print times.
