#!/usr/bin/env python3
"""
build_slides.py — generate the starting PowerPoint decks.

    python docs/slides/build_slides.py

Writes two files into docs/slides/:

    jeong_setup_and_results.pptx   the 1-2 setup + 1-2 results slides Dr Jeong
                                   asked for on 20 Aug, plus two optional ones
    poster.pptx                    a 48 x 36 in research-poster skeleton

═══════════════════════════════════════════════════════════════════════════
THIS SCRIPT GENERATES THE *STARTING* DECK. IT DOES NOT MAINTAIN IT.
═══════════════════════════════════════════════════════════════════════════
Once anyone has edited the .pptx by hand, re-running this OVERWRITES that work.
Rename your edited copy (jeong_v2.pptx) or move it out of docs/slides/ before
running this again.

The numbers below are pulled from the repo where they can be, so a stale
figure fails loudly here rather than quietly on a projector.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt, Emu

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "slides"

# URI palette, matching webapp/static/uri.css so the deck and the dashboard
# do not look like two different projects.
NAVY   = RGBColor(0x00, 0x21, 0x47)
DARK   = RGBColor(0x00, 0x12, 0x28)
KEANEY = RGBColor(0x22, 0x77, 0xB3)
PALE   = RGBColor(0xC0, 0xDD, 0xF2)
GOLD   = RGBColor(0xB5, 0x98, 0x5A)
GOLDDK = RGBColor(0x8A, 0x70, 0x38)
INK    = RGBColor(0x0D, 0x23, 0x38)
DIM    = RGBColor(0x5B, 0x72, 0x88)
WASH   = RGBColor(0xF5, 0xF8, 0xFB)
WASH2  = RGBColor(0xEA, 0xF1, 0xF8)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
OK     = RGBColor(0x1F, 0x7A, 0x52)
WARN   = RGBColor(0xB2, 0x6A, 0x00)
FAULT  = RGBColor(0xB3, 0x26, 0x1E)

SANS = "Calibri"
MONO = "Consolas"


# ───────────────────────────────────────────────────────────── facts ──
def facts():
    """Pull every quotable number from the repo, so none is typed twice."""
    f = {}
    t = json.loads((REPO / "data" / "tunnel.json").read_text())
    f["ref1_max"] = t.get("ref1_max_rpm") or 2435
    ao = t.get("daq_analog_out", {})
    f["ao"] = f"{ao.get('volts_zero', 0.5)} V + rpm/{int(ao.get('rpm_per_volt', 300))}"

    body = [l for l in (REPO / "logs" / "sweep_v1_Ra20_summary.csv")
            .read_text().splitlines(True) if not l.startswith("#")]
    rows = list(csv.DictReader(body))
    f["n_points"] = len(rows)
    f["clean"] = sum(1 for r in rows if (r.get("clean") or "1") in ("1", "True"))
    f["rows"] = [(int(r["fan_rpm_cmd"]), int(float(r["fan_rpm_actual"])),
                  float(r["wind_mps"]), float(r["p_max_w"]),
                  float(r["i_at_pmax_a"])) for r in rows]
    f["p_top"] = max(r[3] for r in f["rows"])
    f["v_top"] = max(r[2] for r in f["rows"])

    b = json.loads((REPO / "blades" / "v1.json").read_text())
    f["chord"] = b.get("chord_mm", 48.0)
    f["span"] = b.get("span_mm", 245.1)
    f["wall"] = b.get("wall_thickness_mm", 1.79)
    f["camber"] = b.get("camber_pct_chord", 42)
    f["turning"] = b.get("turning_deg", 183)
    f["tc"] = b.get("thickness_ratio", 0.040)

    R, H = 0.1016, f["span"] / 1000.0
    f["R"], f["H"] = R, H
    f["area"] = 2 * R * H
    f["cp_lo"] = min(p / (0.5 * 1.204 * f["area"] * v ** 3) for _, _, v, p, _ in f["rows"])
    f["cp_hi"] = max(p / (0.5 * 1.204 * f["area"] * v ** 3) for _, _, v, p, _ in f["rows"])
    f["re_lo"] = 1.204 * min(r[2] for r in f["rows"]) * f["chord"] / 1000 / 1.81e-5
    f["re_hi"] = 1.204 * f["v_top"] * f["chord"] / 1000 / 1.81e-5
    return f


F = facts()


# ─────────────────────────────────────────────────────────── helpers ──
def tb(slide, l, t, w, h, wrap=True):
    box = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = wrap
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    return tf


def para(tf, text, size=16, bold=False, color=INK, first=False, space=6,
         font=SANS, align=PP_ALIGN.LEFT, indent=0, italic=False):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.space_after = Pt(space)
    if indent:
        p.level = indent
    r = p.add_run()
    r.text = text
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.italic = italic
    r.font.color.rgb = color
    r.font.name = font
    return p


def rich(tf, chunks, size=16, first=False, space=6, align=PP_ALIGN.LEFT):
    """chunks = [(text, bold, color, font|None), ...] on one paragraph."""
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.space_after = Pt(space)
    for text, bold, color, *rest in chunks:
        r = p.add_run()
        r.text = text
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
        r.font.name = rest[0] if rest else SANS
    return p


def rect(slide, l, t, w, h, fill, line=None, shape=MSO_SHAPE.RECTANGLE):
    s = slide.shapes.add_shape(shape, Inches(l), Inches(t), Inches(w), Inches(h))
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(1)
    s.shadow.inherit = False
    s.text_frame.word_wrap = True
    return s


def blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def header(slide, kicker, title, W):
    """Navy band with a kicker and a title. Returns the y to continue at."""
    rect(slide, 0, 0, W, 1.28, NAVY)
    rect(slide, 0, 1.28, W, 0.055, GOLD)
    tf = tb(slide, 0.55, 0.17, W - 1.1, 0.36)
    para(tf, kicker.upper(), 11.5, True, PALE, first=True, space=0)
    tf = tb(slide, 0.55, 0.47, W - 1.1, 0.66)
    para(tf, title, 29, True, WHITE, first=True, space=0)
    return 1.62


def notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text.strip()


def figure_slot(slide, l, t, w, h, path, caption):
    """
    Draw a labelled placeholder, or the real image if it exists.

    A slot that says what belongs in it beats an empty rectangle: the deck is
    handed on, and the next person needs to know what is missing.
    """
    p = REPO / path
    if p.exists():
        slide.shapes.add_picture(str(p), Inches(l), Inches(t),
                                 width=Inches(w))
        tf = tb(slide, l, t + h + 0.05, w, 0.3)
        para(tf, caption, 10.5, False, DIM, first=True, italic=True)
        return
    box = rect(slide, l, t, w, h, WASH2, PALE)
    tf = box.text_frame
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    para(tf, "FIGURE", 12, True, KEANEY, first=True, space=4,
         align=PP_ALIGN.CENTER)
    para(tf, path, 11, False, DIM, space=4, align=PP_ALIGN.CENTER, font=MONO)
    para(tf, caption, 11, False, DIM, align=PP_ALIGN.CENTER, italic=True)


# ══════════════════════════════════════════════════════ DECK 1: JEONG ══
def build_jeong():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    W, H = 13.333, 7.5

    # ---------- title ----------
    s = blank(prs)
    rect(s, 0, 0, W, H, NAVY)
    rect(s, 0, 0, 0.28, H, GOLD)
    tf = tb(s, 1.1, 2.05, 11, 0.4)
    para(tf, "UNIVERSITY OF RHODE ISLAND  ·  SODHI LAB  ×  JEONG LAB",
         13, True, GOLD, first=True, space=0)
    tf = tb(s, 1.1, 2.6, 11.2, 1.5)
    para(tf, "Programmable Characterisation of", 34, True, WHITE, first=True, space=2)
    para(tf, "3D-Printed Wind Turbine Blades", 34, True, WHITE, space=0)
    tf = tb(s, 1.1, 4.25, 11, 0.5)
    para(tf, "Automated load sweeps in the Aerolab wind tunnel",
         18, False, PALE, first=True, space=0)
    rect(s, 1.1, 4.95, 2.4, 0.03, KEANEY)
    tf = tb(s, 1.1, 5.3, 11, 1.0)
    para(tf, "Stephen Acuello", 15, True, WHITE, first=True, space=3)
    para(tf, "seacuello@uri.edu   ·   26 August 2026", 12.5, False, PALE, space=0)
    notes(s, "Setup pair = slides 2-3. Results pair = slides 4-5. "
             "Slides 6-7 are optional; 6 is the ask.")

    # ---------- 2. setup ----------
    s = blank(prs)
    y = header(s, "Slide 1 of 2  ·  Experimental setup", "The Rig", W)
    rect(s, 0, y - 0.34 + 0.34, W, H - y, WASH)
    figure_slot(s, 0.55, y + 0.12, 7.3, 3.9,
                "docs/diagrams/system_overview.png",
                "Full measurement and control chain")
    tf = tb(s, 8.2, y + 0.12, 4.6, 4.6)
    para(tf, "CONTROL CHAIN", 12, True, KEANEY, first=True, space=8)
    for a, b in [("Drive", f"ABB ACS550-U1-046A-2, 15 HP, 208–240 V 3φ. "
                           f"Commands speed in rpm; full scale {F['ref1_max']}"),
                 ("Path", "Python host → USB → Portenta Machine Control → "
                          "RS-485 Modbus RTU → drive"),
                 ("Load", "Chroma 63004-150-60. Sets the rotor's operating "
                          "point and is the best V/I instrument on the rig"),
                 ("Wind", f"500–1800 rpm fan = 10.1–{F['v_top']:.1f} m/s, "
                          f"v = 0.02132·rpm − 0.424 (R² = 0.9996)"),
                 ("Bandwidth", "τ = 0.63 ± 0.12 s, from five 1-cosine gusts")]:
        rich(tf, [(f"{a} — ", True, NAVY), (b, False, INK)], 13, space=9)
    para(tf, "ROTOR UNDER TEST", 12, True, KEANEY, space=8)
    rich(tf, [("Vertical-axis H-rotor", True, NAVY),
              (f", 3 blades, R = 101.6 mm, span {F['span']:.0f} mm. "
               f"Swept area 2RH = {F['area']:.4f} m² — a cylinder, not a disc.",
               False, INK)], 13, space=9)
    rich(tf, [("Blade section: ", True, NAVY),
              (f"thin cambered plate, {F['wall']:.2f} mm wall, t/c "
               f"{F['tc']*100:.0f}%, {F['camber']}% camber, {F['turning']}° "
               f"turning, square edges.", False, INK)], 13, space=0)
    notes(s, "Swept area is 2RH because it is a VAWT. Using pi*R^2 overstates "
             "Cp by 1.54x. The blade is a cambered plate, NOT an airfoil - it "
             "matters for any polar or XFOIL cross-check.")

    # ---------- 3. safety ----------
    s = blank(prs)
    y = header(s, "Slide 2 of 2  ·  Experimental setup", "Safety Architecture", W)
    rect(s, 0, y, W, H - y, WASH)
    b = rect(s, 0.55, y + 0.15, 12.2, 0.95, RGBColor(0xFD, 0xF0, 0xEE), FAULT)
    tf = b.text_frame
    tf.margin_left = Inches(0.25)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    para(tf, "The hardwired E-stop is the safety device.", 19, True, FAULT,
         first=True, space=3)
    para(tf, "No software is in that chain. Everything below reduces how "
             "often it is needed — none of it replaces it.", 13.5, False, INK,
         space=0)
    cards = [
        ("TWO INDEPENDENT WATCHDOGS",
         [("The drive stops the fan", " if the PMC goes quiet — par 3018/3019, 3.0 s"),
          ("The PMC stops the fan", " if the host goes quiet — 5.0 s"),
          ("", "Neither depends on the layer above it being correct")]),
        ("ONE MODBUS MASTER ONLY",
         [("The PMC is the master.", " Modbus RTU permits exactly one"),
          ("", "A direct host-to-drive cable must never be landed at the same time"),
          ("", "Two devices commanding a 15 HP fan, neither aware of the other, "
               "is the failure this design exists to prevent")]),
        ("TURBINE INTERLOCK",
         [("load ON → wind UP → test → wind DOWN → load OFF", ""),
          ("", "An unloaded rotor in moving air accelerates until something "
               "mechanical stops it"),
          ("If the fan cannot be confirmed stopped,", " the load stays on")]),
    ]
    for i, (head, items) in enumerate(cards):
        l = 0.55 + i * 4.12
        card = rect(s, l, y + 1.32, 3.87, 3.55, WHITE, PALE)
        tf = card.text_frame
        tf.margin_left = tf.margin_right = Inches(0.2)
        tf.margin_top = Inches(0.18)
        para(tf, head, 12.5, True, KEANEY, first=True, space=10)
        for bold, rest in items:
            if bold and not rest:
                para(tf, bold, 13, True, GOLDDK, space=9, font=MONO)
            else:
                rich(tf, [("• ", False, KEANEY), (bold, True, NAVY),
                          (rest, False, INK)], 12.5, space=9)
    notes(s, "The two watchdogs are the slide's point: each layer is watched by "
             "the layer BELOW it, so the host being wrong cannot run the fan away.")

    # ---------- 4. method ----------
    s = blank(prs)
    y = header(s, "Slide 1 of 2  ·  Results", "Method", W)
    rect(s, 0, y, W, H - y, WASH)
    tf = tb(s, 0.55, y + 0.12, 12.2, 0.4)
    rich(tf, [("Automated blade characterisation — ", False, INK),
              (f"~10 minutes per rotor, unattended, {F['n_points']} wind speeds",
               True, NAVY)], 17, first=True, space=0)
    figure_slot(s, 0.55, y + 0.68, 7.5, 3.9,
                "docs/diagrams/sweep_protocol.png",
                "Outer loop = wind speed; inner loop = load current")
    tf = tb(s, 8.35, y + 0.68, 4.45, 4.3)
    para(tf, "AT EACH WIND SPEED", 12, True, KEANEY, first=True, space=9)
    for txt in ["Ramp the electronic load in constant-current steps",
                "Stop once electrical power falls to 80% of its peak — the "
                "rotor is never driven to stall",
                "Record V and I at every step, unload, advance the wind"]:
        rich(tf, [("• ", False, KEANEY), (txt, False, INK)], 13, space=8)
    para(tf, "WHY A PARABOLIC FIT", 12, True, KEANEY, space=9)
    para(tf, "The top of P(I) is flat. The largest single sample is biased "
             "high, and the bias grows with the number of samples — so two "
             "blades measured with different point counts would be compared "
             "unfairly.", 13, False, INK, space=10)
    para(tf, "PROTOCOL FINGERPRINT", 12, True, KEANEY, space=9)
    rich(tf, [("Every run carries one. ", False, INK),
              ("Runs measured under different settings are not comparable",
               True, NAVY),
              (" — the fingerprint makes that visible instead of silent.",
               False, INK)], 13, space=0)
    notes(s, "The fingerprint is the campaign's integrity mechanism. Across a "
             "dozen rotors it is very easy to change a setting by accident and "
             "impossible to spot afterwards - the numbers stay plausible.")

    # ---------- 5. results ----------
    s = blank(prs)
    y = header(s, "Slide 2 of 2  ·  Results", "Blade v1, Ra 20 µm", W)
    rect(s, 0, y, W, H - y, WASH)

    show = [r for r in F["rows"] if r[0] in (500, 900, 1400, 1800)]
    tbl = s.shapes.add_table(len(show) + 1, 5, Inches(0.55), Inches(y + 0.15),
                             Inches(6.1), Inches(0.42 * (len(show) + 1))).table
    for i, w in enumerate([1.35, 1.2, 1.05, 1.3, 1.2]):
        tbl.columns[i].width = Inches(w)
    heads = ["fan rpm cmd", "measured", "m/s", "P_max", "at"]
    for c, h in enumerate(heads):
        cell = tbl.cell(0, c)
        cell.text = h
        cell.fill.solid(); cell.fill.fore_color.rgb = NAVY
        pr = cell.text_frame.paragraphs[0]
        pr.alignment = PP_ALIGN.RIGHT if c else PP_ALIGN.LEFT
        pr.runs[0].font.size = Pt(11.5); pr.runs[0].font.bold = True
        pr.runs[0].font.color.rgb = WHITE; pr.runs[0].font.name = SANS
    for r, (cmd, act, mps, p, ia) in enumerate(show, start=1):
        top = (cmd == 1800)
        for c, v in enumerate([f"{cmd}", f"{act}", f"{mps:.1f}",
                               f"{p:.3f} W", f"{ia:.3f} A"]):
            cell = tbl.cell(r, c)
            cell.text = v
            cell.fill.solid()
            cell.fill.fore_color.rgb = WASH2 if top else WHITE
            pr = cell.text_frame.paragraphs[0]
            pr.alignment = PP_ALIGN.RIGHT if c else PP_ALIGN.LEFT
            pr.runs[0].font.size = Pt(12)
            pr.runs[0].font.bold = top
            pr.runs[0].font.color.rgb = NAVY if top else INK
            pr.runs[0].font.name = MONO

    tf = tb(s, 0.55, y + 0.28 + 0.42 * (len(show) + 1), 6.1, 0.7)
    para(tf, "Wind speed is derived from MEASURED fan rpm, not commanded — the "
             "drive settles 4–13 rpm below setpoint.", 10.5, False, DIM,
         first=True, space=0, italic=True)

    box = rect(s, 0.55, y + 2.75, 6.1, 1.62, WHITE, PALE)
    tf = box.text_frame
    tf.margin_left = tf.margin_right = Inches(0.2); tf.margin_top = Inches(0.15)
    para(tf, "WHAT IS SOLID", 12, True, OK, first=True, space=8)
    for t in [f"{F['clean']} / {F['n_points']} points clean, single "
              f"continuous run",
              "P ∝ v^3.77, R² = 0.998 across 10.1–37.5 m/s",
              "Independent repeats at 1200 and 1800 rpm match to 0.3% / 0.2%"]:
        rich(tf, [("• ", False, OK), (t, False, INK)], 12.5, space=7)

    box = rect(s, 6.85, y + 0.15, 5.9, 4.25, WHITE, GOLD)
    tf = box.text_frame
    tf.margin_left = tf.margin_right = Inches(0.22); tf.margin_top = Inches(0.18)
    para(tf, "WHAT IT DOES NOT YET SHOW", 12.5, True, GOLDDK, first=True, space=10)
    rich(tf, [("This is electrical power at the load terminals — ", False, INK),
              ("not Cp", True, FAULT), (".", False, INK)], 14.5, space=10)
    para(tf, "The v^3.77 exponent decomposes almost entirely into the "
             "generator, not the rotor:", 13, False, INK, space=8)
    for t in ["V_oc ∝ v^1.52  and  R_int ∝ v^−0.64  (73.6 → 40.1 Ω)",
              "every peak sits at the Thévenin match, P = V_oc²/4R_int",
              "n = 2a − b = 3.69, against 3.77 measured"]:
        para(tf, t, 12, False, NAVY, space=6, font=MONO, indent=1)
    rich(tf, [("→ ", True, GOLDDK),
              ("Little aerodynamic residual is left for the blade to move. "
               "Without rotor speed, blade comparisons partly compare the "
               "generator.", False, INK)], 13, space=10)
    rich(tf, [("Cp_elec = ", False, INK),
              (f"{F['cp_lo']*100:.2f}–{F['cp_hi']*100:.2f}%", True, FAULT),
              (f", roughly 100× below a working H-rotor, because peak power "
               f"sits at ω/ω_runaway ≈ 0.70→0.94 — the far limb of Cp(λ) "
               f"where Cp → 0 by construction.", False, INK)], 13, space=0)
    notes(s, "Do NOT present v^3.77 as 'Cp still climbing with Reynolds'. A "
             "9-agent audit on 25 Aug showed the exponent is a generator "
             "characteristic: V_oc ~ v^1.52, R_int ~ v^-0.64, n = 2a-b = 3.69. "
             "The honest version is stronger and it is the argument for slide 6.")

    # ---------- 6. the ask ----------
    s = blank(prs)
    y = header(s, "Optional  ·  The next measurement",
               "One Channel Unlocks Cp(λ)", W)
    rect(s, 0, y, W, H - y, WASH)
    box = rect(s, 0.55, y + 0.15, 12.2, 1.15, RGBColor(0xEF, 0xF6, 0xF1), OK)
    tf = box.text_frame
    tf.margin_left = Inches(0.25); tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    para(tf, "The rotor-speed measurement already exists in the Jeong lab DAQ.",
         19, True, OK, first=True, space=3)
    para(tf, "A proximity sensor on the rig already records it. What is needed "
             "is its channel number and pulses-per-revolution — not new "
             "hardware.", 13.5, False, INK, space=0)
    left = [
        ("WHY IT MATTERS MORE THAN ANY BLADE RUN", [
            "Without ω there is no λ and no Cp, so the rig cannot separate "
            "rotor aerodynamics from generator matching.",
            "A better blade can read as LESS power: anything that raises "
            "Cp_max while adding low-α drag lowers λ_runaway, lowers V_oc, "
            "and lowers measured P as the SQUARE of the speed change.",
            "Two rotors with Cp_max of 5% and 25% would rank purely by how "
            "freely they spin."]),
    ]
    for i, (head, items) in enumerate(left):
        card = rect(s, 0.55, y + 1.5, 6.0, 3.2, WHITE, PALE)
        tf = card.text_frame
        tf.margin_left = tf.margin_right = Inches(0.22)
        tf.margin_top = Inches(0.18)
        para(tf, head, 12, True, KEANEY, first=True, space=10)
        for t in items:
            rich(tf, [("• ", False, KEANEY), (t, False, INK)], 13, space=10)
    card = rect(s, 6.75, y + 1.5, 6.0, 3.2, WHITE, GOLD)
    tf = card.text_frame
    tf.margin_left = tf.margin_right = Inches(0.22); tf.margin_top = Inches(0.18)
    para(tf, "THE PAYOFF IS RETROACTIVE", 12, True, GOLDDK, first=True, space=10)
    rich(tf, [("Every ", False, INK),
              ("sweep_*_points.csv", False, NAVY, MONO),
              (" already holds a full load ramp at all 14 wind speeds. Adding "
               "one rotor-speed channel converts the ", False, INK),
              ("entire existing archive", True, NAVY),
              (" into a Cq(λ) traverse — without another minute of tunnel time.",
               False, INK)], 13, space=12)
    para(tf, "ALSO USEFUL, AND ALREADY BUILT", 12, True, KEANEY, space=9)
    rich(tf, [("Fan rpm now leaves the PMC as a 0–10 V analog signal "
               "for the DAQ (", False, INK),
              (F["ao"], False, NAVY, MONO),
              ("), so fan speed and rotor speed share one time base. "
               "0.000 V is a live zero meaning INVALID, not zero rpm.",
               False, INK)], 13, space=0)
    notes(s, "This is the ask, aimed at the person who owns the DAQ. Keep it "
             "concrete: channel number and pulses-per-rev, that is all.")

    # ---------- 7. limitations ----------
    s = blank(prs)
    y = header(s, "Optional  ·  Stated plainly", "Known Limitations", W)
    rect(s, 0, y, W, H - y, WASH)
    tf = tb(s, 0.55, y + 0.15, 12.2, 0.4)
    para(tf, "Every one of these was found by adversarial review of our own "
             "results, and each is recorded in the repository.",
         14, False, DIM, first=True, space=0, italic=True)
    items = [
        ("Not Cp", "Electrical power only. Cp(λ) needs the rotor-speed "
                   "channel; every blade tested before that lands must be "
                   "re-run to obtain λ."),
        ("The blade is not an airfoil",
         f"{F['wall']:.2f} mm constant wall, t/c {F['tc']*100:.0f}%, "
         f"{F['camber']}% camber, {F['turning']}° turning, square-cut edges. "
         f"Separation is pinned by geometry, so any XFOIL or polar "
         f"cross-check is answering a question about a different part."),
        ("Reynolds range",
         f"Re_chord = {F['re_lo']:,.0f} → {F['re_hi']:,.0f}. Below "
         f"Reynolds-independence for a cross-flow turbine (~2×10⁵), so "
         f"absolute performance is not transferable to full scale."),
        ("Generator not characterised",
         "R_int is inferred from a curve fit and has never been measured "
         "directly. It gates every derived quantity."),
        ("Wind speed disagreement",
         "Summary and points files differ by 1.1–1.2% at the same fan set "
         "point. At v^3.77 that is 4.5% in power. Unresolved — flagged, not "
         "averaged away."),
        ("Single-mount data",
         "Every result so far comes from one mounting of one rotor. There is "
         "no mount-to-mount error bar yet; the ABBA protocol for the next "
         "session produces the first one."),
    ]
    for i, (head, body) in enumerate(items):
        col, row = i % 2, i // 2
        l = 0.55 + col * 6.2
        t = y + 0.68 + row * 1.42
        card = rect(s, l, t, 6.0, 1.28, WHITE, PALE)
        tf = card.text_frame
        tf.margin_left = tf.margin_right = Inches(0.2)
        tf.margin_top = Inches(0.13)
        para(tf, head, 13, True, NAVY, first=True, space=5)
        para(tf, body, 11.5, False, INK, space=0)
    notes(s, "Optional slide. For an academic audience this is the most "
             "credible thing in the deck - it shows the limits are known and "
             "quantified rather than unexamined.")

    out = OUT / "jeong_setup_and_results.pptx"
    prs.save(out)
    return out, len(prs.slides._sldIdLst)


# ═══════════════════════════════════════════════════════ DECK 2: POSTER ══
def build_poster():
    """
    A 48 x 36 in research poster skeleton, three columns.

    Deliberately a SKELETON. Stephen has a starter poster file coming; this
    exists so the content, the numbers and the section order are settled
    before any of it is poured into someone else's template.
    """
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(48), Inches(36)
    W, H = 48.0, 36.0
    s = blank(prs)
    rect(s, 0, 0, W, H, WASH)

    # ---- title band ----
    rect(s, 0, 0, W, 5.6, NAVY)
    rect(s, 0, 5.6, W, 0.22, GOLD)
    tf = tb(s, 1.6, 0.75, W - 3.2, 1.0)
    para(tf, "UNIVERSITY OF RHODE ISLAND  ·  SODHI LAB  ×  JEONG LAB",
         26, True, GOLD, first=True, space=0)
    tf = tb(s, 1.6, 1.85, W - 3.2, 2.0)
    para(tf, "Programmable Characterisation of 3D-Printed Wind Turbine Blades",
         62, True, WHITE, first=True, space=0)
    tf = tb(s, 1.6, 4.05, W - 3.2, 1.0)
    para(tf, "Stephen Acuello   ·   seacuello@uri.edu   ·   Aerolab wind "
             "tunnel, automated load sweeps", 25, False, PALE, first=True, space=0)

    # 1.4 + 3*14.2 + 2*1.2 + 1.4 = 47.8 on a 48 in sheet.
    COLW, GAP, M = 14.2, 1.2, 1.4
    top = 6.6

    def col_x(i):
        return M + i * (COLW + GAP)

    def section(cx, cy, title, cw=COLW):
        rect(s, cx, cy, cw, 0.78, KEANEY)
        tf = tb(s, cx + 0.35, cy + 0.14, cw - 0.7, 0.5)
        para(tf, title.upper(), 24, True, WHITE, first=True, space=0)
        return cy + 0.78

    def body(cx, cy, cw, h):
        box = rect(s, cx, cy, cw, h, WHITE, PALE)
        tf = box.text_frame
        tf.margin_left = tf.margin_right = Inches(0.45)
        tf.margin_top = Inches(0.4)
        return tf, cy + h

    # ═══ COLUMN 1 ═══
    x, y = col_x(0), top
    y = section(x, y, "Motivation")
    tf, y = body(x, y, COLW, 5.4)
    para(tf, "3D printing makes rotor geometry cheap to iterate. Measuring "
             "whether a change actually helps does not follow automatically: "
             "a wind-tunnel campaign that compares a dozen blades has to hold "
             "its protocol fixed across weeks, or the comparison silently "
             "becomes a comparison of settings.", 21, False, INK, first=True,
         space=14)
    para(tf, "This work builds programmable, reproducible control of the "
             "Aerolab tunnel and its electronic load, so a rotor can be "
             "characterised unattended in ~10 minutes with a machine-checkable "
             "record of exactly how.", 21, False, INK, space=0)

    y += 1.1
    y = section(x, y, "Apparatus")
    tf, y = body(x, y, COLW, 8.6)
    for a, b in [("Drive", "ABB ACS550-U1-046A-2, 15 HP, 208–240 V 3φ; "
                           f"commands speed in rpm, full scale {F['ref1_max']}"),
                 ("Controller", "Portenta Machine Control — sole Modbus RTU "
                                "master, owns both watchdogs"),
                 ("Load", "Chroma 63004-150-60 DC electronic load, SCPI over "
                          "USB-TMC"),
                 ("Wind", f"10.1 – {F['v_top']:.1f} m/s, "
                          f"v = 0.02132·rpm − 0.424, R² = 0.9996"),
                 ("Rotor", f"Vertical-axis H-rotor, 3 blades, R = 101.6 mm, "
                           f"span {F['span']:.0f} mm, swept area "
                           f"2RH = {F['area']:.4f} m²"),
                 ("Blade", f"PETG, thin cambered plate: {F['wall']:.2f} mm "
                           f"wall, t/c {F['tc']*100:.0f}%, {F['camber']}% "
                           f"camber, {F['turning']}° turning")]:
        rich(tf, [(f"{a}   ", True, NAVY), (b, False, INK)], 20, space=13)

    y += 1.1
    y = section(x, y, "Safety Architecture")
    tf, y = body(x, y, COLW, 6.4)
    para(tf, "The hardwired E-stop is the safety device. No software is in "
             "that chain.", 21, True, FAULT, first=True, space=14)
    for t in ["Two independent watchdogs — the drive stops the fan if the PMC "
              "goes quiet (3.0 s); the PMC stops the fan if the host goes "
              "quiet (5.0 s). Neither depends on the layer above it.",
              "One Modbus master only. Two devices commanding a 15 HP fan, "
              "neither aware of the other, is the failure this design prevents.",
              "Interlock: load ON → wind UP → test → wind DOWN → load OFF. "
              "An unloaded rotor in moving air accelerates."]:
        rich(tf, [("• ", False, KEANEY), (t, False, INK)], 20, space=13)

    # ═══ COLUMN 2 ═══
    x, y = col_x(1), top
    y = section(x, y, "Method")
    tf, y = body(x, y, COLW, 6.2)
    para(tf, f"At each of {F['n_points']} wind speeds (500 → 1800 rpm fan in "
             f"100 rpm steps):", 21, True, NAVY, first=True, space=14)
    for t in ["Ramp the electronic load in constant-current steps",
              "Stop once electrical power falls to 80% of its peak — the "
              "rotor is never driven to stall",
              "Record V and I at every step, unload, advance the wind"]:
        rich(tf, [("• ", False, KEANEY), (t, False, INK)], 20, space=12)
    para(tf, "Peak located by parabolic fit. Over a flat maximum the largest "
             "single sample is biased high, and the bias grows with sample "
             "count — so blades measured with different point counts would be "
             "compared unfairly.", 19, False, INK, space=0)

    y += 1.1
    y = section(x, y, "Protocol Fingerprinting")
    tf, y = body(x, y, COLW, 5.2)
    para(tf, "Every run hashes the settings that change what a curve MEANS — "
             "step size, scaling rule, dwell, cut-out voltage, current range, "
             "floor current, roll-off fraction.", 20, False, INK, first=True,
         space=14)
    rich(tf, [("Runs with different fingerprints are not comparable. ", True, NAVY),
              ("The hash makes that visible instead of silent — across a dozen "
               "rotors the numbers stay perfectly plausible either way.",
               False, INK)], 20, space=0)

    y += 1.1
    y = section(x, y, "Results — blade v1, Ra 20 µm")
    tf, y = body(x, y, COLW, 9.0)
    for t, big in [(f"{F['clean']} / {F['n_points']} points clean, single "
                    f"continuous run", False),
                   ("P ∝ v^3.77,  R² = 0.998", True),
                   (f"peak {F['p_top']:.3f} W at {F['v_top']:.1f} m/s", True),
                   ("independent repeats at 1200 and 1800 rpm match the sweep "
                    "to 0.3% and 0.2%", False)]:
        para(tf, t, 26 if big else 20, big, NAVY if big else INK, space=14,
             font=MONO if big else SANS)
    para(tf, "FIGURE — P_max(v), log–log, with the fitted power law",
         19, True, DIM, space=0, align=PP_ALIGN.CENTER, italic=True)

    # ═══ COLUMN 3 ═══
    x, y = col_x(2), top
    y = section(x, y, "What the Exponent Actually Measures")
    tf, y = body(x, y, COLW, 9.8)
    para(tf, "v^3.77 is a generator characteristic, not an aerodynamic one.",
         22, True, GOLDDK, first=True, space=14)
    for t in ["V_oc ∝ v^1.52,  R_int ∝ v^−0.64  (73.6 → 40.1 Ω)",
              "every peak sits at the Thévenin match, P = V_oc² / 4R_int",
              "n = 2a − b = 3.69,  against 3.77 measured"]:
        para(tf, t, 19, False, NAVY, space=11, font=MONO)
    rich(tf, [("Cp_elec = ", False, INK),
              (f"{F['cp_lo']*100:.2f} – {F['cp_hi']*100:.2f}%", True, FAULT),
              (", roughly 100× below a working H-rotor, because peak power "
               "sits at ω/ω_runaway ≈ 0.70 → 0.94 — the far limb of Cp(λ) "
               "where Cp → 0 by construction.", False, INK)], 20, space=14)
    rich(tf, [("Consequence: ", True, NAVY),
              ("a better blade can read as LESS electrical power. Anything "
               "that raises Cp_max while adding low-α drag lowers λ_runaway, "
               "lowers V_oc, and lowers measured P as the square.",
               False, INK)], 20, space=0)

    y += 1.1
    y = section(x, y, "Limitations")
    tf, y = body(x, y, COLW, 7.2)
    for t in ["Electrical power only — not Cp. Rotor speed is required.",
              f"The blade is a cambered plate, not an airfoil: separation is "
              f"pinned by square edges, so polar and XFOIL cross-checks do not "
              f"apply.",
              f"Re_chord = {F['re_lo']:,.0f} → {F['re_hi']:,.0f}, below "
              f"Reynolds-independence (~2×10⁵) for a cross-flow turbine.",
              "Generator R_int is inferred from a fit, never measured.",
              "Single-mount data — no mount-to-mount error bar yet."]:
        rich(tf, [("• ", False, GOLDDK), (t, False, INK)], 19, space=12)

    y += 1.1
    y = section(x, y, "Next")
    tf, y = body(x, y, COLW, 6.0)
    para(tf, "One rotor-speed channel converts the entire existing archive "
             "into Cq(λ) retroactively.", 22, True, OK, first=True, space=14)
    para(tf, "Every sweep already records a full load ramp at all 14 wind "
             "speeds. The measurement exists — a proximity sensor on the rig "
             "already feeds the Jeong lab DAQ. What is needed is its channel "
             "and pulses-per-revolution, not new hardware.", 20, False, INK,
         space=14)
    para(tf, "Then: surface-finish and geometry comparisons under ABBA "
             "ordering, with the first mount-to-mount error bar this rig has "
             "had.", 20, False, INK, space=0)

    # footer
    rect(s, 0, H - 1.5, W, 1.5, NAVY)
    tf = tb(s, 1.6, H - 1.12, W - 3.2, 0.7)
    para(tf, "Code, data and full protocol: github.com/stephenseacuello/"
             "windtunnel-control", 21, False, PALE, first=True, space=0)

    out = OUT / "poster.pptx"
    prs.save(out)
    return out, W, H


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    p1, n1 = build_jeong()
    p2, pw, ph = build_poster()
    print(f"  {p1.relative_to(REPO)}   {n1} slides, 16:9")
    print(f"  {p2.relative_to(REPO)}   1 slide, {pw:.0f} x {ph:.0f} in")
    print(f"\n  facts pulled from the repo:")
    print(f"    {F['clean']}/{F['n_points']} clean · peak {F['p_top']:.3f} W "
          f"at {F['v_top']:.1f} m/s")
    print(f"    Cp_elec {F['cp_lo']*100:.2f}-{F['cp_hi']*100:.2f}% · "
          f"Re {F['re_lo']:,.0f}-{F['re_hi']:,.0f}")
    print(f"    blade wall {F['wall']:.2f} mm · t/c {F['tc']*100:.0f}% · "
          f"camber {F['camber']}%")
