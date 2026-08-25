# Blade library

Drop rotor geometry here, named to match the `--blade` argument you sweep with:

```
blades/
  v1_Ra20.stl          ← matches:  blade_sweep.py --blade v1_Ra20
  v1_Ra20.json         ← optional metadata (see below)
  v3_smooth.stl
```

The dashboard's **Blades** tab pairs each file with that rotor's measured
curve from `logs/sweep_<name>_summary.csv`, so geometry and result sit on one
page. The name is the join key — a mismatch means the tab shows geometry with
no curve, or a curve with no geometry, and says which.

## STL, not STEP

STL is a triangle soup and the dashboard renders it directly with no
dependencies. STEP is a boundary-representation format that needs
OpenCASCADE-class tessellation to display at all — not something worth
vendoring into a Flask app that currently has none. Keep STEP as your CAD
master if you like; **export an STL beside it** for the record and the viewer.

Binary and ASCII STL both work. Meshes above ~60k triangles are subsampled for
display only — the file is untouched.

## Optional metadata

`<name>.json` beside the STL, any subset of:

```json
{
  "material": "PETG",
  "layer_height_mm": 0.2,
  "surface": "Ra 20",
  "tip_radius_m": null,
  "n_blades": 3,
  "printed": "2026-08-18",
  "notes": "anything you would want to know six months from now"
}
```

`tip_radius_m` is the one that matters most and is still unmeasured — λ scales
linearly with it and Cp as 1/r². Measure from the axis of rotation, not blade
length.
