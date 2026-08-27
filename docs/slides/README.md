# docs/slides/

```bash
python docs/slides/build_slides.py
```

| file | what |
|---|---|
| `jeong_setup_and_results.pptx` | 7 slides, 16:9 — the setup pair and results pair Dr Jeong asked for, plus three optional |
| `poster.pptx` | one 48 × 36 in slide, built **from your CYPHER poster as the template** |

## ⚠️ The script generates. It does not maintain.

Re-running **overwrites** hand edits. Rename your working copy
(`jeong_v2.pptx`) or move it out of this folder first.

Every quotable number is read from the repo at build time — `data/tunnel.json`,
`logs/sweep_v1_Ra20_summary.csv`, `blades/v1.json` — so a stale figure fails
loudly here rather than quietly on a projector.

## The poster clones your CYPHER file

`build_poster()` opens `2026_CYPHER_IPT_Poster_Eacuello.pptx`, strips its
shapes, and rebuilds the content in place — it does **not** style a blank deck
to look similar. Cloning inherits the theme, fonts, navy `#002147` background
and slide size exactly, so the two posters are the same object with different
words.

Style measured off your file and reproduced:

| element | |
|---|---|
| background | `#002147` URI navy |
| panels | white fill, `#C79316` gold rule at **13.3 pt** |
| title bar | rounded rect, gold rule at **15.3 pt** |
| section labels | **72 pt bold navy**, seated inside the panel's top edge |
| body | 28–32 pt |
| footer | Arial 29.33 pt bold |

Logos and the QR are extracted to `assets/` and re-placed at the same
coordinates. The five-panel grid is the CYPHER grid, with one change: your left
column is 0.2 in out of alignment with the panel below it, and that is squared
up rather than copied.

**No funding line.** The CYPHER poster's ONR grant belongs to a different
project, so it is not carried across. The footer is the venue plus
`Sodhi Lab × Jeong Lab`. If this work is genuinely under an award, add it at
`VENUE` / `AFFIL` in the script.

## Figures

Two slots are wired up and currently render as labelled placeholders. Drop
either file in and the next build uses it automatically, no code change:

```
docs/diagrams/system_overview.png     slide 2  — the full rig
docs/diagrams/sweep_protocol.png      slide 4  — outer/inner loop flowchart
```

## Slide map

| # | slide | for |
|---:|---|---|
| 1 | Title | |
| 2 | The Rig | **setup 1 of 2** |
| 3 | Safety Architecture | **setup 2 of 2** |
| 4 | Method | **results 1 of 2** |
| 5 | Blade v1, Ra 20 µm | **results 2 of 2** |
| 6 | One Channel Unlocks Cp(λ) | optional — *the ask* |
| 7 | Known Limitations | optional |

Slide 6 is aimed at the person who owns the DAQ, and the request is deliberately
small: **a channel number and a pulses-per-revolution figure.**

Slide 7 is the most credible thing in the deck for an academic audience — the
limits are quantified rather than unexamined.

## One thing not to undo

Slide 5 does **not** say "Cp is still climbing with Reynolds." An earlier draft
did. A nine-agent adversarial audit on 25 Aug showed **v^3.77 is a generator
characteristic**: V_oc ∝ v^1.52, R_int ∝ v^−0.64, every peak at the Thévenin
match, and n = 2a − b = 3.69 against 3.77 measured.

The honest version is the stronger one, and it is what makes slide 6 an
argument rather than a wish.


---

## Which slides are for whom

**Slides 1–2 are the setup pair Dr Jeong asked for; 3–4 are the results pair.**
Slide 5 is optional and makes the case for the DAQ channel directly to the
person who owns the DAQ.

If Taegu is covering the mechanical rig and rotor fabrication, keep slide 1
to the control and measurement chain to avoid overlap.

The limitation bullet on slide 4 is the most valuable line in the deck for
this audience. It is honest, and it is the argument for the next measurement.

*(Moved here from the old slides note, which was deleted. Every quotable
number in that file was a hand-typed second copy of what `build_slides.py`
generates from the data — a guaranteed drift source. The judgement about who
each slide addresses is the part worth keeping.)*
