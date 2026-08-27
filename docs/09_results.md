# Results — what this rig has actually measured

The campaign's findings, with their limits stated. Numbers here are checked
against the data files by `tests/test_docs.py`; if a CSV changes and this page
does not, the suite fails.

For *how* to run a sweep see [`07_blade_campaign.md`](07_blade_campaign.md).
For what is still unknown see [`11_open_questions.md`](11_open_questions.md).

---

## The headline

**Blade `v1_Ra80` produces 13.73% more electrical power than `v1_Ra20`.**

```
LEVEL   +13.73%   95% CI [+11.21%, +16.26%]
Δn      +0.024 ± 0.064
```

Higher at **all 14 wind speeds**, both runs on protocol `94bed28333f7`, paired
analysis at matched fan set points. Same geometry, same mount design, same
mesh — the only intended difference is printed surface finish, Ra 20 µm against
Ra 80 µm.

Reproduce with:

```bash
python src/compare_blades.py v1_Ra20 v1_Ra80
```

### Why the flat Δn is what makes it credible

The obvious alternative explanation is that the two rotors differ in **cut-in
speed** — bearing friction, balance, preset pitch — rather than in
aerodynamics. That would be indistinguishable from a roughness effect in the
level alone.

But it is not indistinguishable in the exponent. A cut-in shift large enough
to fake +13.7% would also drag the power-law exponent down by about 0.24:

| cut-in shift | level | Δn |
|---:|---:|---:|
| −0.25 m/s | +7.4% | −0.141 |
| −0.50 m/s | +15.4% | −0.267 |

**Measured Δn is +0.024 ± 0.064 — 4.1σ from the −0.24 that artefact requires.**
Generator warm-up is excluded the same way: it predicts Δn ≈ −0.063 *and* a
deficit, not a gain.

What survives is a **uniform multiplicative gain across a 3.7× wind range**,
which neither artefact produces.

---

## The baseline: `v1_Ra20`

14 of 14 points clean, single continuous run, 20 Aug 2026.

| fan rpm | measured | m/s | P_max | at |
|---:|---:|---:|---:|---:|
| 500 | 496 | 10.1 | 0.030 W | 0.018 A |
| 900 | 894 | 18.6 | 0.273 W | 0.068 A |
| 1400 | 1384 | 29.1 | 1.665 W | 0.240 A |
| 1800 | 1779 | 37.5 | **3.793 W** | 0.320 A |

**P ∝ v^3.77, R² = 0.998** across 10.1–37.5 m/s.

⚠️ Those powers are the **raw argmax**. `sweep_v1_Ra20_summary.csv` carries
`p_max_w` only, verified equal to the largest single dwell in the points file
at 14 of 14. Runs after 22 Aug carry both `p_max_fit_w` and `p_max_raw_w`; the
argmax is biased high by ~1.3% over a flat maximum, so comparisons must use
like for like. `compare_blades.py` enforces this and refuses to cross them.

---

## The exponent is the generator, not the blade

`src/generator_model.py` fits the rig as a Thévenin source at every wind speed:

```
V_oc  = 0.101 · v^1.497
R_int = 595.5 · v^-0.791        88.4 Ω at 10.2 m/s  →  36.5 Ω at 38.0
```

r² ≥ 0.986 at all fourteen — the linear form is not an approximation here, it
is what the rig does. Every peak sits at the Thévenin match, so
`P_max = V_oc²/4R_int` and the power exponent follows:

```
n = 2a − b = 3.79     against 3.77 measured directly
```

**Neither fit was tuned to produce that.** Almost no aerodynamic residual is
left for the blade to move.

> An earlier reading of `P ∝ v^3.77` as *"Cp is still climbing with Reynolds"*
> was wrong and propagated into six documents. The blade is a thin cambered
> plate with square edges — the Reynolds-**insensitive** class.

---

## What the rig cannot yet say

**Cp_elec is 0.10–0.24%**, roughly 100× below a working H-rotor. Peak power
sits at ω/ω_runaway ≈ 0.70 → 0.94, the far limb of Cp(λ) where Cp → 0 by
construction.

**This is electrical power, not Cp.** The consequence is not academic: a blade
that captures more energy but spins slower produces less voltage and therefore
reads **lower**. Two rotors five times apart in aerodynamic efficiency could
rank purely by how freely they spin.

Rotor speed is the missing measurement. See
[`11_open_questions.md`](11_open_questions.md).

---

## The rotor

Vertical-axis H-rotor, 3 blades. **Swept area is 2·R·H — a cylinder, not a
disc.** Using π·R² overstates Cp by 1.54×.

| | |
|---|---|
| Radius R | 0.1016 m (4″), axis to blade attachment |
| Span H | 0.2451 m |
| Swept area | 2RH = **0.0498 m²** |
| Chord | 48 mm |
| Re_chord | **32,376 → 119,735** across the wind range |

**The blade is not an airfoil.** From `blades/v1.stl`: 1.79 mm constant wall
(2V/A over 27,056 triangles), t/c 4%, 42% camber, 183° of turning, square-cut
edges, **zero twist** — the section is prismatic to ±0.02%. XFOIL and polar
cross-checks answer a question about a different part.

---

## The tunnel

| | |
|---|---|
| Wind speed | v = 0.02132 × fan rpm − 0.424, R² = 0.9996 |
| Range | 10.1 – 37.5 m/s over 500 – 1800 rpm |
| Bandwidth | **τ = 0.60 ± 0.11 s**, five 1-cosine gust runs |
| Corner | f = 1/(2πτ) ≈ 0.27 Hz |

τ reproduces with
`python src/analyze.py logs/20260820_14*_1mc.csv --summary`.

---

## Confidence, honestly

| finding | strength |
|---|---|
| P ∝ v^3.77, R² = 0.998 | **strong** — 14 points, independent single-point repeats to 0.3%/0.2% |
| Thévenin fit, n = 2a−b = 3.79 vs 3.77 | **strong** — an independent cross-check the fits were not tuned for |
| Ra 80 is +13.73% | **good** — resolved, artefact excluded at 4.1σ, but see below |
| The cause is surface roughness | **weak** — see below |

**Both runs are a single mounting of a single rotor.** There is no
mount-to-mount error bar, so remounting could move a result by an unknown
amount. And `v1_Ra80`'s notes record a 0.2 mm nozzle while `v1_Ra20`'s record
none — if the prints differed in more than finish, the comparison is not clean.

The **remount repeat** in [`../NEXT_SESSION.md`](../NEXT_SESSION.md) is what
turns the third row from *good* into *strong*. It costs ten minutes.
