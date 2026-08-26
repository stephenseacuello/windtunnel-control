# docs/slides/

```bash
python docs/slides/build_slides.py
```

| file | what |
|---|---|
| `jeong_setup_and_results.pptx` | 7 slides, 16:9 — the setup pair and results pair Dr Jeong asked for, plus three optional |
| `poster.pptx` | one 48 × 36 in slide, three columns — a skeleton to pour into the real template |

## ⚠️ The script generates. It does not maintain.

Re-running **overwrites** hand edits. Rename your working copy
(`jeong_v2.pptx`) or move it out of this folder first.

Every quotable number is read from the repo at build time — `data/tunnel.json`,
`logs/sweep_v1_Ra20_summary.csv`, `blades/v1.json` — so a stale figure fails
loudly here rather than quietly on a projector.

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
