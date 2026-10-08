# Case records: how they are made and used

Every CFD case should leave a small, git-tracked record: the settings that defined it, what the
solver did, plots of the numbers, and ParaView images of the flow. The run folders themselves
(`cfd/*/runs/`) are git-ignored and get deleted or overwritten, so the record is the permanent copy.

| Tool | Does |
|---|---|
| `cfd/post/record_case.py <case>` | Writes one record (20-60 s; about 3 MB) |
| `cfd/post/render_fields.py` | The ParaView part (pvbatch); `record_case.py` calls it |
| `cfd/post/record_all.py` | Records every finished case that has no up-to-date record (idempotent); skips `runs/_*` test folders unless `--include-tests` |
| `cfd/post/after_case.sh <case>` | Hook that `cfd/section2d/queue.py` runs after each completed case; never fails the queue |
| `cfd/post/record_lib.py` | Shared helpers (status, paths, read-only "shadow" of a case) |

Records go to `cfd/section2d/results/records/<case>/` and `cfd/rotor2d/results/records/<case>/`;
mesh-only records to `.../records/_mesh/<mesh>/`.

## Commands

```zsh
python3 cfd/post/record_case.py cfd/section2d/runs/<case>          # one case, with images
python3 cfd/post/record_case.py cfd/rotor2d/runs/<case> --no-render  # numbers and plots only
python3 cfd/post/record_all.py --dry-run                            # what would be recorded
python3 cfd/post/record_all.py                                      # record all new finished cases
python3 cfd/post/record_all.py --include-stopped                    # also timed-out / failed cases
python3 cfd/post/record_all.py --include-tests                      # also runs/_smoke_*, runs/_test_*
python3 cfd/post/record_all.py --meshes '*a000*'                    # mesh images of runs/_mesh/*a000*
cfd/post/after_case.sh cfd/section2d/runs/<case> [--bg]             # what a queue calls

PV=/Applications/ParaView-6.2.0.app/Contents/bin/pvbatch            # images only, anywhere
$PV --force-offscreen-rendering cfd/post/render_fields.py <case> --out /tmp/imgs
```

A hand-written `NOTES.md` inside a record folder survives re-recording; everything else is
regenerated. With `--no-render` the existing `fields/` images are kept and relisted, so the
numbers and README can be refreshed in seconds. `record_all.py` treats a record as up to date
when its solver log is unchanged; use `--force` to re-render.

## What a record contains

| File | Content |
|---|---|
| `README.md` | Key-number table, then every plot and image with a paragraph on how to read it |
| `summary.json` | Status, run length, cost per session, means and spread, St, y+, mesh quality |
| `case.json`, `results.json` | Copies: case parameters; the queue's own summary when it exists |
| `settings.txt` | controlDict, caseParameters, functions, fvSchemes, fvSolution, turbulence and transport properties, dynamicMeshDict, `0/` boundary conditions |
| `checkMesh.log`, `mesh_info.json` | Mesh quality and generator parameters |
| `log_excerpt.txt` | Solver sessions (CPU against clock time), grouped warnings, header, last 50 lines |
| `residuals.png/.csv` | Initial residual of the first solve per time step |
| `timestep.png` | deltaT, max Courant number, cumulative CPU and clock time |
| `coefficients.png/.csv` | Cd, Cl, Cm (section) or C_Q, C_P, C_x, C_y (rotor); window shaded, mean +/- std |
| `spectrum.png` | Lift or torque spectrum; St marked |
| `phase_CQ.png` | Rotating rotor: one blade's C_Q against azimuth |
| `yplus.png` | y+ min / mean / max on the walls against time |
| `fields/*.png` | Mesh (domain, near, three corner zooms, AMI), \|U\|, vorticity, Cp, nu_t/nu, LIC, streamlines, gammaInt, time-means |
| `fields/surface_*.csv/.png` | Cp, Cf and y+ along the blade wall |
| `fields/vorticity_anim.gif` | Only when two or more field times are saved (see below) |

CSVs are decimated to at most 5000 rows; PNGs are 150 dpi and palette-quantised. Measured sizes
(8 Oct): 2.2-2.7 MB for a case with fields, 1.2 MB without, 0.7-1.2 MB for a mesh-only record.

Colour ranges are fixed so records compare directly: |U|/U_inf 0-1.6; omega_z L/U_inf -20 to 20
(L = 48 mm chord, or rotor D); Cp -3 to 1 (blue suction, white Cp = 0, red stagnation);
nu_t/nu 1-1000 on a log scale; gammaInt 0-1. Values outside a range take the end colour (for
example Cp of about 1.4 in the cup during an impulsive start, LEARNING_LOG section 7). Every field
image states its view height.

**Rendering change, 8 Oct.** Surfaces are now drawn unlit, so a pixel has exactly the colour-bar
colour of its value, and the palette keeps 128 colours sampled along the colour map. Before, the
default lighting drew the fields about 25 % darker than their colour bars (measured: free stream
|U|/U_inf = 1 drawn as (28, 131, 97) against (47, 178, 124) on the bar), and median-cut
quantisation merged rare colours (|U|/U_inf 1.4 to 1.6 as one colour, the LIC colour bar as six
bands). The kept test records were re-rendered on 8 Oct; the mesh-only records were not (no colour
map; their cell faces are beige instead of white).

## Safety: the case is only read

- `render_fields.py` reads the case through a temporary folder of symlinks plus an empty
  `case.foam` (`record_lib.make_shadow`). Decomposed cases are read straight from `processor*/`, so
  no `reconstructPar` is run and nothing is written into the case.
- A case counts as running if it has a live `RUNNING` marker, its log was written in the last
  3 minutes without ending in `End`, or a live solver process names it. A marker left by a killed
  `run_case.py` (no solver process names the case, no log write for 10 min) is `stale`, not running
  (`record_lib.marker_state`, 8 Oct); `record_all.py` handles such a case as stopped (recorded only
  with `--include-stopped`). A running case gets a record
  without images, flagged `running`, from `record_case.py`; `record_all.py` skips it and writes
  nothing for it. Checked on 8 Oct 07:47 with the production case `a000.0_U23.0_SST_medium_Tu1.0`
  running: `record_all.py` reported "running (RUNNING marker present); not touched", created no
  record folder and left the run folder's listing unchanged; the four solver ranks kept running.
- Rendering runs as one process at `nice 10`; the solvers keep the performance cores.

## Queue hook

`cfd/section2d/queue.py` runs `cfd/post/after_case.sh <case dir>` after every completed case
(`run_after_case_hook`: only if the file is executable; killed after 30 min; a failure or timeout is
logged and the queue goes on). The record scripts never edit a queue. `after_case.sh` runs
`record_case.py` at `nice 10` with `cfd/.venv/bin/python` (else `python3` on PATH) and appends to
`cfd/<stage>/results/records/after_case.log`; tested on 8 Oct with the queue's PATH: 17 s for a
coarse case, exit 0.

`cfd/rotor2d/queue.py` has no hook. Either the rotor queue owner adds, in `run_queue()` right after
`st = run_case.run(...)`,

```python
if st == "complete":
    subprocess.run([str(Path(__file__).resolve().parents[1] / "post" / "after_case.sh"),
                    str(run_case.RUNS / n)], check=False)
```

or a periodic sweep records the rotor cases:

```zsh
while true; do python3 cfd/post/record_all.py --quiet; sleep 900; done
```

`record_all.py` holds a lock, so overlapping sweeps do not collide. It re-records a case whose
solver log changed (extended or re-run). It skips run folders whose name starts with `_`, so a
deleted test record is not re-created.

## Limits

- **Animation.** The cases keep only the last three writes (`purgeWrite 3`), 10 c/U apart, and
  a finished case keeps only the last one. A vorticity animation over one shedding cycle needs
  writes closer than about a twelfth of a period. For a period of about 5-7 c/U (St 0.15-0.2,
  assumed), that is writes every 0.5 c/U, kept, for one period: a separate short continuation run.
  The record labels frames closer than a sixth of the period "resolved" and wider spacing as
  aliasing the shedding.
- **y+ along the wall** (`surface_*.png`) is computed in ParaView as sqrt(tau_w) d / nu, with d
  the wall-normal distance to the first cell centre. On `_test_pipeline_coarse_N0.3` at its last
  time it matched OpenFOAM's yPlus function object exactly in the minimum (0.00681), to 0.5 % in
  the mean (0.2009 against 0.2000) and to 6.5 % in the maximum (1.55 against 1.46, at a corner
  face) (measured, 7 Oct). The rotor cases write no wallShearStress field, so their tau_w there
  is (nu + nu_t,wall) |U_cell - U_wall| / d.
- **p_inf** in Cp is 0 for the section (the far-field value) and the inlet-patch mean for the
  rotor.

## Test records (7 Oct 2026)

Made from the cases that existed on 7 Oct, before any production case had finished. All of them
use the free-stream set-up before decay control (far-field Tu 1.89 % decaying to 1 % at the blade,
l = 2 mm, nu_t/nu 35 at the blade; LEARNING_LOG section 3) and show start-up flow only. Each README
opens with a "Test record" banner and names the set-up in its key-number table. They are kept
because the learning log uses their figures; replace those figures with production records as
they appear, then delete these. Re-rendered on 8 Oct.

| Record | Case status | Kept for |
|---|---|---|
| `section2d/results/records/_test_pipeline_coarse_N0.3/` | finished (0.3 c/U) | LEARNING_LOG sections 1 and 6 (wall y+, start-up history); full record, SST, coarse, fields and time-means |
| `section2d/results/records/_test_pipeline_coarse_LM_N0.3/` | finished (0.3 c/U) | LEARNING_LOG sections 2, 3 and 7 (nu_t/nu, gammaInt, mean Cp); kOmegaSSTLM |
| `section2d/results/records/_smoke_a000_U23_SST_medium_Co5n2/` | stopped (timeout) | The sleep stall: clock 8886 s against CPU 282 s in session 2 (`timestep.png`); LEARNING_LOG section 5 |
| `section2d/results/records/_smoke_a000_U23_SST_medium_Co10n2/` | finished, diverged, no fields kept | maxCo 10 divergence (`residuals.png`); LEARNING_LOG section 5 |
| `section2d/results/records/_mesh/{coarse,medium,fine}_a000.0/` | mesh | Mesh levels for the mesh study |
| `rotor2d/results/records/_mesh/` (6 meshes: A coarse/medium/fine wall-function, A medium low-Re, A medium at 10.2 m/s, B medium) | mesh | Rotor meshes, AMI interface; wall-function against low-Re first cells |

Removed: `_test_decay_SST_a000_U23` (deleted with its run folder after the decay-control checks,
`section2d/README.md` section 5) and `_test_schemes_LL` (8 Oct; not used by any document; while
`section2d/runs/_test_schemes_LL` exists it can be re-made with `record_case.py`). The scheme
result it held (omega negative in 217 of 224 steps with `limitedLinear`) is in
`section2d/README.md` section 5 and RUN_JOURNAL.md.

No rotor case had finished, so the rotor path was tested into a scratch folder, not into the
records: on a stopped smoke run (`A_rot_U23.0_lam0.150_SST_coarse`, 0.04 revolutions, since
deleted by its owner), and on synthetic load histories with known answers (C_Q 0.25 with a
3-per-revolution ripple; static St_D 0.20), which the record returned as C_Q 0.2500, peak at
3.000 times the rotation frequency, and St_D 0.2000.
