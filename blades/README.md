# blades/

One mesh per **geometry**. Surface finish is a variable *of* a geometry, not a
different rotor.

```
blades/v1.stl          the printed shape
blades/v1.json         chord, span, profile notes

logs/sweep_v1_Ra20_*   that shape at Ra 20 um
logs/sweep_v1_Ra80_*   the same shape at Ra 80 um
```

Both runs resolve to `v1.stl`. Keeping a copy per finish would create files
that must stay byte-identical for the comparison to mean anything — and across
a campaign they would not.

## Naming

    <geometry>_Ra<roughness>

`v1_Ra20` and `v1_Ra80` are a **controlled pair**: same geometry, one variable.
`v2_Ra20` asserts a different mesh, so only use it when the mesh really changed.
The dashboard splits on the `_Ra<N>` suffix, shows the finish as a badge, and
looks the mesh up by the geometry half.

An exact-name STL still wins if one exists, so a genuinely different mesh can
override the geometry default.

## Adding a rotor

Drop `<geometry>.stl` in here, in **metres**. Sweep with
`--blade <geometry>_Ra<N>`. The dashboard pairs them itself.

A sweep with no mesh still lists and plots; a mesh with no sweep lists as not
yet swept. Neither is an error.

## Do NOT bake roughness into the mesh

Ra 20 vs 80 um is a *print* parameter (fuzzy skin, layer height, nozzle), not
geometry. A mesh with 80 um texture displaced onto it would be hundreds of MB,
would not render, and would not describe what the printer actually did anyway.
Record the slicer settings in `<geometry>.json` and in `--notes` instead — those
are what make the print reproducible.
