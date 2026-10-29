# As-printed blades: slicer G-code and reconstructed STLs

Added 29 Oct 2026 (moved from S. Eacuello's Downloads). The large files are **not in git** because they are
11–309 MB each, over GitHub's limits (see `.gitignore`). They exist only on this Mac, so keep a copy
elsewhere (e.g. Drive). Checksums: `SHA256SUMS_gcode.txt`, `SHA256SUMS_reconstructed_stl.txt`.

## `gcode/`: the Print Lab's sliced files

Bambu Studio, Bambu Lab P1S, 0.2 mm nozzle, 0.10 mm layers, 4 walls, Bambu PLA Basic. The slicer's own
estimates, read from each file:

| File | Model printing time | Filament | Motion commands (G0–G3) |
|---|---|---|---|
| `BaselineTurbine.gcode` | 5 h 09 m 47 s | 38.42 g | 271,093 |
| `Ra10Turbine.gcode` | 5 h 57 m 16 s | 38.46 g | 806,748 |
| `Ra20Turbine.gcode` | 5 h 09 m 47 s | 38.42 g | 271,057 |
| `Ra40Turbine.gcode` | 7 h 31 m 43 s | 39.08 g | — |
| `Ra80Turbine.gcode` | 8 h 32 m 36 s | 40.63 g | — |

**The "Ra20" file contains no fuzzy skin.**
- Its print time and filament match the Baseline exactly.
- Its toolpath has the same number of moves as the Baseline (within 0.01 %); even the finest texture,
  Ra10, has three times as many.
- Its coordinates differ from the Baseline only because the part sits elsewhere on the build plate.

The reconstruction agrees: the Ra20 STL has fewer triangles than the Baseline.

Whether the FS 0.05 ("Ra 20") blades tested on 1 Oct were printed from this file is **not confirmed**;
ask the Print Lab. The Ra10/Ra40/Ra80 times match the Print Lab's 12 Oct slicing screenshots
(`reports/roughness_2026-09/inputs/print_lab_20261012/`), so these are the Print Lab's slices.

## `reconstructed_stl/`: blade surfaces rebuilt from the G-code (S. Eacuello, 28 Oct 2026)

Two resolutions, six specimens each: Baseline, Ra10, Ra20, Ra40, Ra80 and Ra320 ("320" = FS 0.80,
from `turbine_320.3mf`).

| Folder | XY step | Z step | Size |
|---|---|---|---|
| `Turbine_CFD_All6_Compact_220umXY_240umZ/` | 0.22 mm | 0.24 mm | 639 MB |
| `Turbine_CFD_All6_HighDetail_160umXY_240umZ/` | 0.16 mm | 0.24 mm | 964 MB |

From each folder's `README_CFD_Reconstruction.txt` (kept in git) and `manifest.json`:
- **Approximations.** They are rebuilt from the programmed outer-wall toolpaths, not from scans of
  the printed blades.
- **Ra labels.** They are nominal names, not measured roughness.
- **Layers.** Ra320 used 0.12 mm layers; the other five used 0.10 mm.
- **Build positions.** These differ between files, so align the geometries before comparing them in
  CFD.
- **Mesh checks.** Edge checks were done; a CFD meshing check is still needed.
