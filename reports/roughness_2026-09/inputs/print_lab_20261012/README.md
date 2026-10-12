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

## The two project files (received 12 Oct; not committed: 80.6 MB and 20.2 MB)

Checksums are in `SHA256SUMS_3mf.txt`. The settings below were read from
`Metadata/project_settings.config` and `model_settings.config`.

**`turbine_p2mm.3mf`** (Bambu Studio 02.08.02.61). The settings are the same as
`../slicer/turbine_default.3mf`:
- printer and process: P1S 0.2 nozzle, "0.10mm Standard"; 0.1 mm layers (first layer 0.1 mm);
- walls and lines: 4 wall loops, 0.22 mm line width, outer wall at 120 mm/s;
- fuzzy skin: displacement mode, 0.2 mm point distance;
- infill and shells: 15 % sparse infill, 7 top and 5 bottom layers;
- material and plate: Bambu PLA Basic at 220 °C, Textured PEI plate, 5 mm auto brim.

The plates are:

| Plate | Fuzzy-skin thickness |
|---|---|
| "10 RA" | 0.025 mm |
| "40 RA" | 0.101 mm |
| "80 RA" | 0.202 mm |
| plate 4, unnamed | 0.805 mm |

Differences from the default file: filament cost $19.99/kg (was $24.99), and plate 4. Neither
file has a plate for Plain or for FS 0.05 (0.050 mm).

**`turbine_320.3mf`** (the planned "Ra 320" set). Changes against the tested sets:

| Setting | Tested sets | Ra 320 plan |
|---|---|---|
| Nozzle | 0.2 mm | 0.4 mm |
| Process profile | 0.10mm Standard | 0.12mm High Quality |
| Layer height (first layer) | 0.1 mm (0.1 mm) | 0.12 mm (0.2 mm) |
| Wall loops | 4 | 2 |
| Line width | 0.22 mm | 0.42 mm |
| Outer wall speed | 120 mm/s | 60 mm/s |
| Fuzzy skin | as above | 0.805 mm thickness, 0.2 mm point distance (object overrides) |
| Brim | 5 mm, auto | 20 mm, outer only |

The slicing result (`320RA.png`) gives 71.6 g per blade, against about 39 g for the tested sets.
22.5 % of the print time is "overhang wall", from the outward displacement.
