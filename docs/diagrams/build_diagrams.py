#!/usr/bin/env python3
"""
build_diagrams.py — the two figures the slide deck and poster reference.

    python docs/diagrams/build_diagrams.py

Writes system_overview.svg / .png and sweep_protocol.svg / .png.

The repo vendors no plotting or drawing library, so these are hand-written SVG
and converted with rsvg-convert. That keeps them in version control as text: a
diagram that drifts from the rig shows up in a diff.

═══════════════════════════════════════════════════════════════════════════
THREE THINGS THESE GET RIGHT THAT AN EARLIER PAIR DID NOT
═══════════════════════════════════════════════════════════════════════════
· The rotor is a VAWT. It is an H-rotor on a vertical shaft, not a
  horizontal-axis propeller. The whole Cp calculation depends on it — swept
  area is 2RH, a cylinder, and using pi*R^2 overstates Cp by 1.54x.

· Each watchdog is attributed to the right box. The DRIVE stops the fan if the
  PMC goes quiet (par 3018/3019, 3.0 s). The PMC stops the fan if the HOST
  goes quiet (5.0 s). The nesting is the design; getting it backwards makes
  the safety argument meaningless.

· The DAQ link is drawn as it is, not as it was planned. Rotor rpm is ALREADY
  recorded from a proximity sensor. Fan rpm is the new one.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent

NAVY, DARK = "#002147", "#001228"
KEANEY, MID, PALE = "#2277b3", "#30557e", "#c0ddf2"
GOLD, GOLDDK = "#b5985a", "#8a7038"
INK, DIM = "#0d2338", "#5b7288"
PAPER, WASH, WASH2, LINE = "#ffffff", "#f5f8fb", "#eaf1f8", "#d3e0eb"
OK, WARN, FAULT = "#1f7a52", "#b26a00", "#b3261e"
FONT = "Inter, Helvetica Neue, Arial, sans-serif"
MONO = "SF Mono, Menlo, Consolas, monospace"


def esc(t):
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def wrap(text, width):
    """Break on spaces, never mid-word. The character-chunked version of this
    produced 'the instrument's c / ut-off first', which is worse than any
    line-length problem it was solving."""
    out, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if len(trial) > width and line:
            out.append(line); line = word
        else:
            line = trial
    if line:
        out.append(line)
    return out


def txt(x, y, s, size=15, w=400, fill=INK, anchor="start", font=FONT, ls="0"):
    return (f'<text x="{x}" y="{y}" font-family="{font}" font-size="{size}" '
            f'font-weight="{w}" fill="{fill}" text-anchor="{anchor}" '
            f'letter-spacing="{ls}">{esc(s)}</text>')


def box(x, y, w, h, fill=PAPER, stroke=LINE, sw=1.6, r=6):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')


def arrow(x1, y1, x2, y2, col=KEANEY, sw=2.6, dash=None, head="end"):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    m = ' marker-end="url(#ah)"' if head == "end" else ""
    return (f'<path d="M{x1},{y1} L{x2},{y2}" fill="none" stroke="{col}" '
            f'stroke-width="{sw}"{d}{m}/>')


def head(W, H, defs_extra=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
            f'width="{W}" height="{H}">'
            f'<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{KEANEY}"/></marker>'
            f'<marker id="ahr" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{GOLDDK}"/></marker>'
            f'{defs_extra}</defs>'
            f'<rect width="{W}" height="{H}" fill="{WASH}"/>')


def node(x, y, w, h, title, sub=None, fill=PAPER, stroke=LINE, tcol=NAVY,
         sw=1.8):
    """A labelled block. Returns svg string."""
    o = [box(x, y, w, h, fill, stroke, sw)]
    cy = y + (h / 2 if not sub else h / 2 - 9)
    o.append(txt(x + w / 2, cy + 5, title, 16, 700, tcol, "middle"))
    if sub:
        for i, line in enumerate(sub if isinstance(sub, list) else [sub]):
            o.append(txt(x + w / 2, cy + 26 + i * 15, line, 11.5, 400, DIM,
                         "middle"))
    return "".join(o)


def vawt(cx, cy, R=74, halfH=92, blade=GOLDDK):
    """
    An H-rotor seen from the side — vertical shaft, two end plates, three
    straight blades. NOT a propeller.

    Blades sit at 90/210/330 degrees; the projected x is cx + R*cos(theta) and
    the front blade (90) is drawn last so it overlaps the plates correctly.
    """
    import math
    o = [f'<line x1="{cx}" y1="{cy-halfH-16}" x2="{cx}" y2="{cy+halfH+16}" '
         f'stroke="{MID}" stroke-width="5"/>']
    ry = 17
    for dy in (-halfH, halfH):
        o.append(f'<ellipse cx="{cx}" cy="{cy+dy}" rx="{R}" ry="{ry}" '
                 f'fill="none" stroke="{MID}" stroke-width="3.2"/>')
    order = sorted([90, 210, 330], key=lambda t: math.sin(math.radians(t)))
    for th in order:
        bx = cx + R * math.cos(math.radians(th))
        oy = ry * math.sin(math.radians(th))
        # a cambered plate: two arcs closed into a thin crescent
        bow = 20 if abs(math.sin(math.radians(th))) > 0.9 else 14
        o.append(f'<path d="M{bx-bow:.1f},{cy-halfH+oy:.1f} '
                 f'C{bx+bow*0.9:.1f},{cy-halfH/2+oy:.1f} {bx+bow*0.9:.1f},'
                 f'{cy+halfH/2+oy:.1f} {bx-bow:.1f},{cy+halfH+oy:.1f} '
                 f'L{bx-bow+13:.1f},{cy+halfH+oy:.1f} '
                 f'C{bx+bow*0.9+13:.1f},{cy+halfH/2+oy:.1f} '
                 f'{bx+bow*0.9+13:.1f},{cy-halfH/2+oy:.1f} '
                 f'{bx-bow+13:.1f},{cy-halfH+oy:.1f} Z" '
                 f'fill="{blade}" stroke="{GOLDDK}" stroke-width="1.4" '
                 f'opacity="0.95"/>')
    return "".join(o)


# ══════════════════════════════════════════════════ SYSTEM OVERVIEW ══
def system_overview():
    W, H = 1760, 1120
    o = [head(W, H)]
    o.append(txt(44, 46, "URI WIND TUNNEL — MEASUREMENT AND CONTROL CHAIN",
                 20, 700, NAVY, ls="0.5"))
    o.append(f'<line x1="44" y1="60" x2="{W-44}" y2="60" stroke="{GOLD}" '
             f'stroke-width="2.5"/>')

    # legend
    lg = [("control / digital", KEANEY, None),
          ("electrical power", GOLDDK, None),
          ("measurement to DAQ", OK, "7 5")]
    lx = W - 44
    for label, col, dash in reversed(lg):
        wpx = len(label) * 7.0 + 46
        lx -= wpx
        d = f' stroke-dasharray="{dash}"' if dash else ""
        o.append(f'<line x1="{lx}" y1="41" x2="{lx+30}" y2="41" '
                 f'stroke="{col}" stroke-width="3.4"{d}/>')
        o.append(txt(lx + 38, 46, label, 12.5, 500, DIM))

    # ── row 1: control chain ──
    y1 = 100
    o.append(node(44, y1, 220, 104, "Host laptop",
                  ["Python orchestration + logging", "NOT trusted with safety"]))
    o.append(node(330, y1, 250, 104, "Portenta Machine Control",
                  ["sole Modbus master · owns BOTH watchdogs",
                   "Modbus RTU 19200 8E1 · station 1"],
                  WASH2, OK, NAVY, 3.0))
    o.append(node(646, y1, 226, 104, "ABB ACS550 VFD",
                  ["15 HP · 208–240 V 3φ", "commands rpm, max 2435"]))
    o.append(node(938, y1, 180, 104, "Fan motor", ["15 HP induction"]))

    o.append(arrow(264, y1 + 52, 328, y1 + 52))
    o.append(txt(296, y1 + 42, "USB", 11.5, 600, DIM, "middle"))
    o.append(arrow(580, y1 + 52, 644, y1 + 52))
    o.append(txt(612, y1 + 42, "RS-485", 11.5, 600, DIM, "middle"))
    o.append(arrow(872, y1 + 52, 936, y1 + 52, GOLDDK, 2.8))
    o.append(txt(904, y1 + 42, "3φ", 11.5, 600, GOLDDK, "middle"))

    # ── test section + VAWT ──
    tsx, tsy, tsw, tsh = 1180, 76, 400, 386
    o.append(box(tsx, tsy, tsw, tsh, PAPER, KEANEY, 2.4, 10))
    o.append(txt(tsx + tsw / 2, tsy + 30, "TEST SECTION", 13.5, 700, KEANEY,
                 "middle", ls="1"))
    o.append(txt(tsx + tsw / 2, tsy + 50, "wind 10.1 – 37.5 m/s", 11.5, 500,
                 DIM, "middle"))
    for i in range(5):
        wy = tsy + 150 + i * 46
        o.append(f'<path d="M{tsx+16},{wy} L{tsx+92},{wy}" stroke="{PALE}" '
                 f'stroke-width="4" stroke-linecap="round"/>')
    o.append(arrow(1120, y1 + 52, 1178, y1 + 52, KEANEY, 2.8))
    o.append(txt(1149, y1 + 42, "wind", 11.5, 600, DIM, "middle"))
    o.append(txt(tsx + tsw / 2, tsy + 78, "VAWT H-rotor · 3 blades", 14, 700,
                 NAVY, "middle"))
    o.append(txt(tsx + tsw / 2, tsy + 97, "R = 101.6 mm · span 245 mm  ·  "
                                          "swept area 2RH = 0.0498 m²", 11,
                 400, DIM, "middle"))
    o.append(txt(tsx + tsw / 2, tsy + 112, "a cylinder, not a disc", 11, 600,
                 GOLDDK, "middle"))
    o.append(vawt(tsx + 244, tsy + 236))

    # ── row 2: electrical chain, right to left ──
    y2 = 470
    chain = [(1300, "Generator", ["3-phase, on the rotor shaft"]),
             (1044, "Rectifier", ["3φ bridge → DC"]),
             (800, "V / I sense IC", ["series, 5 V supply"]),
             (470, "Chroma 63004-150-60", ["150 V / 60 A / 400 W",
                                           "sets the operating point"])]
    for i, (x, t, sub) in enumerate(chain):
        w = 280 if i == 3 else 216
        o.append(node(x, y2, w, 92, t, sub, PAPER,
                      GOLD if i == 3 else LINE, NAVY, 2.4 if i == 3 else 1.8))
    o.append(f'<path d="M{tsx+244},{tsy+346} L{tsx+244},{y2-34} '
             f'L{1408},{y2-34} L{1408},{y2-2}" fill="none" stroke="{GOLDDK}" '
             f'stroke-width="2.8" marker-end="url(#ahr)"/>')
    for x1, x2 in ((1298, 1262), (1042, 1018), (798, 752)):
        o.append(arrow(x1, y2 + 46, x2, y2 + 46, GOLDDK, 2.8))
    o.append(arrow(468, y2 + 46, 300, y2 + 46, KEANEY, 2.6))
    o.append(txt(384, y2 + 36, "USB-TMC (VISA)", 11.5, 600, DIM, "middle"))
    o.append(f'<path d="M{330+125},{y1+106} L{330+125},{y2+46} L{300},{y2+46}" '
             f'fill="none" stroke="none"/>')
    o.append(node(120, y2, 180, 92, "Host laptop", ["the SAME laptop",
                                                    "SCPI over VISA"],
                  WASH2, LINE))

    # ── row 3: the DAQ ──
    y3 = 660
    o.append(node(1180, y3, 400, 118, "Jeong Lab DAQ",
                  ["one time base for both speeds"], WASH2, OK, NAVY, 3.0))
    o.append(f'<path d="M{tsx+120},{tsy+tsh} L{tsx+120},{610} L{1280},{610} '
             f'L{1280},{y3-2}" fill="none" stroke="{OK}" stroke-width="2.8" '
             f'stroke-dasharray="7 5" marker-end="url(#ah)"/>')
    o.append(txt(1258, 600, "rotor rpm — proximity sensor, ALREADY RECORDED",
                 12, 700, OK, "end"))
    o.append(f'<path d="M{455},{y1+104} L{455},{y3+58} L{1178},{y3+58}" '
             f'fill="none" stroke="{OK}" stroke-width="2.8" '
             f'stroke-dasharray="7 5" marker-end="url(#ah)"/>')
    o.append(txt(470, y3 + 48, "fan rpm — PMC analog out O0,  0.5 V + rpm/300 "
                               "(firmware v4)", 12, 700, OK))

    # ── watchdogs ──
    y4 = 828
    o.append(box(44, y4, 830, 128, PAPER, KEANEY, 2.4, 8))
    o.append(txt(66, y4 + 30, "TWO INDEPENDENT WATCHDOGS", 14, 700, KEANEY,
                 ls="0.8"))
    o.append(txt(66, y4 + 60, "The DRIVE stops the fan if the PMC goes quiet",
                 14.5, 700, NAVY))
    o.append(txt(66, y4 + 79, "par 3018 / 3019  ·  3.0 s", 12, 400, DIM,
                 font=MONO))
    o.append(txt(470, y4 + 60, "The PMC stops the fan if the HOST goes quiet",
                 14.5, 700, NAVY))
    o.append(txt(470, y4 + 79, "5.0 s", 12, 400, DIM, font=MONO))
    o.append(txt(66, y4 + 106, "Neither depends on the layer above it being "
                               "correct. One Modbus master only — the PMC.",
                 12.5, 400, INK))

    o.append(box(908, y4, 672, 128, PAPER, GOLD, 2.4, 8))
    o.append(txt(930, y4 + 30, "TURBINE INTERLOCK", 14, 700, GOLDDK, ls="0.8"))
    o.append(txt(930, y4 + 62, "load ON → wind UP → test → wind DOWN → "
                               "load OFF", 16, 700, NAVY, font=MONO))
    o.append(txt(930, y4 + 92, "An unloaded rotor in moving air accelerates. "
                               "If the fan cannot be", 12.5, 400, INK))
    o.append(txt(930, y4 + 109, "confirmed stopped, the load stays on.",
                 12.5, 400, INK))

    # ── safety chain ──
    y5 = 990
    o.append(box(44, y5, 1536, 84, "#fdf0ee", FAULT, 2.8, 8))
    o.append(f'<circle cx="96" cy="{y5+42}" r="21" fill="{FAULT}"/>')
    o.append(f'<circle cx="96" cy="{y5+42}" r="12" fill="#fdf0ee"/>')
    o.append(txt(140, y5 + 36, "HARDWIRED E-STOP → contactor circuit", 17, 700,
                 FAULT))
    o.append(txt(140, y5 + 60, "This is the safety device. No software is in "
                               "this chain — everything above only reduces how "
                               "often it is needed.", 13, 400, INK))
    o.append("</svg>")
    return W, H, "".join(o)


# ══════════════════════════════════════════════════ SWEEP PROTOCOL ══
def sweep_protocol():
    W, H = 1680, 1160
    o = [head(W, H)]
    o.append(txt(44, 46, "BLADE SWEEP PROTOCOL", 20, 700, NAVY, ls="0.5"))
    o.append(f'<line x1="44" y1="60" x2="{W-44}" y2="60" stroke="{GOLD}" '
             f'stroke-width="2.5"/>')
    o.append(txt(W - 44, 46, "~10 minutes per rotor, unattended", 13, 500, DIM,
                 "end"))

    # ── setup ──
    o.append(box(44, 84, 1592, 74, "#fdf0ee", FAULT, 2.4, 8))
    o.append(txt(70, 118, "SETUP (ONCE)", 12.5, 700, FAULT, ls="0.8"))
    o.append(txt(240, 116, "Load ON at floor current", 17, 700, NAVY))
    o.append(txt(560, 116, "— load before wind, always: an unloaded rotor in "
                           "moving air runs away", 13.5, 400, INK))

    # ── outer loop frame ──
    ox, oy, ow, oh = 200, 186, 1436, 742
    o.append(box(ox, oy, ow, oh, PAPER, KEANEY, 2.8, 10))
    o.append(txt(ox + 26, oy + 40, "OUTER LOOP — wind speed", 19, 700, NAVY))
    o.append(txt(ox + 380, oy + 30, "500 → 1800 rpm fan in 100 rpm steps",
                 13, 500, DIM))
    o.append(txt(ox + 380, oy + 48, "14 points  ·  10.1 → 37.5 m/s", 13, 500,
                 DIM))
    o.append(txt(ox + 700, oy + 30, "rpm = FAN speed", 12, 600, GOLDDK))
    o.append(txt(ox + 700, oy + 48, "m/s = WIND speed", 12, 600, GOLDDK))

    st = [("1", "Command fan speed via the PMC", 250),
          ("2", "Wait for the drive to reach it", 620),
          ("3", "Wait for terminal voltage to settle", 990)]
    sy = oy + 72
    for i, (n, label, x) in enumerate(st):
        o.append(box(x, sy, 336, 62, WASH2, PALE, 1.8, 8))
        o.append(f'<circle cx="{x+30}" cy="{sy+31}" r="16" fill="{NAVY}"/>')
        o.append(txt(x + 30, sy + 36, n, 15, 700, PAPER, "middle"))
        o.append(txt(x + 56, sy + 37, label, 14, 500, INK))
        if i < 2:
            o.append(arrow(x + 336, sy + 31, x + 366, sy + 31))
    o.append(txt(250, sy + 84, "0.000 V is perfectly stable — speed must be "
                               "confirmed first, not voltage", 12, 400, DIM))

    # ── inner loop ──
    ix, iy, iw, ih = 250, sy + 104, 700, 396
    o.append(box(ix, iy, iw, ih, "#f2f8f4", OK, 2.4, 10))
    o.append(txt(ix + 22, iy + 36, "INNER LOOP — load current ramp", 17, 700,
                 OK))
    rows = [("1", "Set constant-current demand",
             "20 mA at 1800 rpm, scaled as v² at lower wind"),
            ("2", "Dwell 1.0 – 1.5 s", None),
            ("3", "Measure V and I,  compute P = V·I", None)]
    ry = iy + 54
    for n, label, sub in rows:
        hgt = 60 if sub else 46
        o.append(box(ix + 22, ry, iw - 44, hgt, PAPER, PALE, 1.6, 6))
        o.append(f'<circle cx="{ix+50}" cy="{ry+ (24 if sub else 23)}" r="14" '
                 f'fill="{OK}"/>')
        o.append(txt(ix + 50, ry + (29 if sub else 28), n, 13.5, 700, PAPER,
                     "middle"))
        o.append(txt(ix + 74, ry + (28 if sub else 28), label, 14.5, 600, INK))
        if sub:
            o.append(txt(ix + 74, ry + 47, sub, 11.5, 400, DIM))
        ry += hgt + 12

    dy = ry + 6
    o.append(f'<path d="M{ix+350},{dy} L{ix+560},{dy+40} L{ix+350},{dy+80} '
             f'L{ix+140},{dy+40} Z" fill="{PAPER}" stroke="{NAVY}" '
             f'stroke-width="2.2"/>')
    o.append(txt(ix + 350, dy + 36, "has power fallen to", 13, 500, INK,
                 "middle"))
    o.append(txt(ix + 350, dy + 54, "80% of its peak?", 13.5, 700, NAVY,
                 "middle"))
    o.append(f'<path d="M{ix+140},{dy+40} L{ix+40},{dy+40} L{ix+40},{iy+80} '
             f'L{ix+22},{iy+80}" fill="none" stroke="{OK}" stroke-width="2.4" '
             f'marker-end="url(#ah)"/>')
    o.append(txt(ix + 96, dy + 30, "No", 13, 700, OK, "middle"))
    o.append(txt(ix + 350, dy + 100, "Yes", 13, 700, NAVY, "middle"))

    # ── exits ──
    ex = 1010
    exits = [("rotor stall", "current stopped tracking demand", WARN),
             ("load cut-out", "terminal voltage fell below the instrument's "
                              "cut-off first — this is the LOAD's limit, not "
                              "the rotor's; record as a lower bound", WARN),
             ("ceiling reached", "never rolled off — the peak may not have "
                                 "been reached", FAULT)]
    ey = iy + 30
    for t, sub, col in exits:
        lines = wrap(sub, 52)
        hgt = 46 + 15 * len(lines)
        o.append(box(ex, ey, 570, hgt, "#fdf6ec", col, 2.0, 8))
        o.append(f'<circle cx="{ex+28}" cy="{ey+28}" r="13" fill="{col}"/>')
        o.append(txt(ex + 28, ey + 33, "!", 15, 700, PAPER, "middle"))
        o.append(txt(ex + 52, ey + 33, t, 15.5, 700, col))
        for i, ln in enumerate(lines):
            o.append(txt(ex + 52, ey + 54 + i * 15, ln, 11.5, 400, INK))
        o.append(arrow(950, iy + 200, ex - 2, ey + hgt / 2, col, 2.0))
        ey += hgt + 16

    # ── after the ramp ──
    ay = iy + ih + 20
    o.append(box(250, ay, 700, 66, WASH2, PALE, 1.8, 8))
    o.append(f'<circle cx="284" cy="{ay+33}" r="16" fill="{NAVY}"/>')
    o.append(txt(284, ay + 38, "4", 15, 700, PAPER, "middle"))
    o.append(txt(310, ay + 30, "Fit a parabola to the points around the "
                               "maximum", 14.5, 600, INK))
    o.append(txt(310, ay + 50, "the top of P(I) is flat — the single highest "
                               "sample is biased high, and the bias grows with "
                               "sample count", 11, 400, DIM))
    o.append(box(1010, ay, 300, 66, WASH2, PALE, 1.8, 8))
    o.append(f'<circle cx="1044" cy="{ay+33}" r="16" fill="{NAVY}"/>')
    o.append(txt(1044, ay + 38, "5", 15, 700, PAPER, "middle"))
    o.append(txt(1070, ay + 39, "Unload to 0 A", 15, 600, INK))
    o.append(arrow(950, ay + 33, 1008, ay + 33))

    # loop-back
    lb, riser = ay + 116, 226
    o.append(f'<path d="M{1310},{ay+33} L{1580},{ay+33} L{1580},{lb} '
             f'L{riser},{lb} L{riser},{sy+31} L{ix-2},{sy+31}" fill="none" '
             f'stroke="{KEANEY}" stroke-width="2.6" marker-end="url(#ah)"/>')
    o.append(f'<rect x="820" y="{lb-13}" width="260" height="26" fill="{WASH}"/>')
    o.append(txt(950, lb + 5, "next wind speed", 14, 700, KEANEY, "middle"))

    # ── watchdog tick, left rail ──
    o.append(box(44, 300, 132, 300, PAPER, OK, 2.4, 8))
    o.append(txt(110, 336, "WATCHDOG", 12, 700, OK, "middle", ls="0.6"))
    o.append(txt(110, 354, "TICK", 12, 700, OK, "middle", ls="0.6"))
    o.append(txt(110, 392, "every", 12.5, 400, INK, "middle"))
    o.append(txt(110, 414, "1.0 s", 19, 700, NAVY, "middle", font=MONO))
    o.append(txt(110, 452, "the PMC stops", 11, 400, DIM, "middle"))
    o.append(txt(110, 467, "the fan if the", 11, 400, DIM, "middle"))
    o.append(txt(110, 482, "host goes quiet", 11, 400, DIM, "middle"))
    o.append(txt(110, 497, "for 5.0 s", 11, 700, NAVY, "middle"))
    o.append(txt(110, 534, "the DRIVE stops", 11, 400, DIM, "middle"))
    o.append(txt(110, 549, "the fan if the", 11, 400, DIM, "middle"))
    o.append(txt(110, 564, "PMC goes quiet", 11, 400, DIM, "middle"))
    o.append(txt(110, 579, "for 3.0 s", 11, 700, NAVY, "middle"))
    o.append(f'<path d="M176,450 L{ox-2},450" fill="none" stroke="{OK}" '
             f'stroke-width="2.2" stroke-dasharray="6 4"/>')

    # ── shutdown ──
    shy = oy + oh + 22
    o.append(box(44, shy, 1592, 96, DARK, DARK, 2, 8))
    o.append(txt(74, shy + 40, "SHUTDOWN", 17, 700, PAPER, ls="1"))
    steps = [("1", "Wind DOWN", 260), ("2", "Load OFF", 560),
             ("3", "Write points + summary CSV with protocol fingerprint", 840)]
    for n, label, x in steps:
        o.append(f'<circle cx="{x}" cy="{shy+36}" r="15" fill="{GOLD}"/>')
        o.append(txt(x, shy + 41, n, 14, 700, DARK, "middle"))
        o.append(txt(x + 24, shy + 41, label, 15, 600, PAPER))
    o.append(txt(74, shy + 74, "Strictly this order. If the fan cannot be "
                               "confirmed stopped, the load stays on.  ·  Only "
                               "runs with matching fingerprints are comparable.",
                 12.5, 400, PALE))
    o.append("</svg>")
    return W, H, "".join(o)


# ═══════════════════════════════════════════════════ CHAIN STRIP ══
def chain_strip():
    """
    A wide, low variant of the system overview for the poster.

    The full diagram is roughly 1.6:1. The poster's System Architecture slot is
    2.97:1, so fitting the full one there shrinks it to about 6 in on a 48 in
    sheet — every label illegible from reading distance. This carries the same
    chain with a quarter of the elements and four times the type size.
    """
    W, H = 1860, 620
    o = [head(W, H)]
    bw, bh = 244, 96

    def chip(x, y, t, sub, fill=PAPER, stroke=LINE, sw=2.2, w=bw):
        r = [box(x, y, w, bh, fill, stroke, sw, 8),
             txt(x + w / 2, y + (40 if sub else 56), t, 22, 700, NAVY, "middle")]
        if sub:
            r.append(txt(x + w / 2, y + 66, sub, 15, 400, DIM, "middle"))
        return "".join(r)

    # control chain
    y1 = 60
    o.append(txt(30, y1 + 22, "CONTROL", 15, 700, KEANEY, ls="1"))
    xs = [150, 470, 838, 1158]
    o.append(chip(xs[0], y1, "Host laptop", "not safety-trusted"))
    o.append(chip(xs[1], y1, "PMC", "sole Modbus master · both watchdogs",
                  WASH2, OK, 3.4, 290))
    o.append(chip(xs[2], y1, "ACS550 VFD", "15 HP · commands rpm"))
    o.append(chip(xs[3], y1, "Fan motor", "15 HP"))
    for a, b, lab, col in ((394, 466, "USB", KEANEY),
                           (762, 834, "RS-485", KEANEY),
                           (1084, 1154, "3φ", GOLDDK)):
        o.append(arrow(a, y1 + bh / 2, b, y1 + bh / 2, col, 3.4))
        o.append(txt((a + b) / 2, y1 + bh / 2 - 14, lab, 14, 600, DIM, "middle"))

    # the rotor, spanning both rows
    rx = 1440
    o.append(box(rx, 34, 390, 300, PAPER, KEANEY, 3.0, 10))
    o.append(txt(rx + 195, 66, "TEST SECTION", 16, 700, KEANEY, "middle", ls="1"))
    o.append(vawt(rx + 195, 196, R=58, halfH=68))
    o.append(txt(rx + 195, 306, "VAWT H-rotor · 3 blades · A = 2RH", 15, 700,
                 NAVY, "middle"))
    o.append(arrow(1404, y1 + bh / 2, rx - 4, y1 + bh / 2, KEANEY, 3.4))
    o.append(txt(1421, y1 + bh / 2 - 14, "wind", 14, 600, DIM, "middle"))

    # measurement chain
    y2 = 372
    o.append(txt(30, y2 + 22, "MEASURE", 15, 700, GOLDDK, ls="1"))
    o.append(chip(1160, y2, "Generator", "3-phase"))
    o.append(chip(840, y2, "Rectifier", "3φ → DC"))
    o.append(chip(520, y2, "V / I sense", "series"))
    o.append(chip(150, y2, "Chroma load", "sets the operating point",
                  PAPER, GOLD, 3.0, 290))
    o.append(f'<path d="M{rx+195},{334} L{rx+195},{y2+bh/2} L{1408},'
             f'{y2+bh/2}" fill="none" stroke="{GOLDDK}" stroke-width="3.4" '
             f'marker-end="url(#ahr)"/>')
    for a, b in ((1158, 1088), (838, 768), (518, 444)):
        o.append(arrow(a, y2 + bh / 2, b, y2 + bh / 2, GOLDDK, 3.4))

    # DAQ
    o.append(box(150, 500, 1680, 82, WASH2, OK, 3.0, 8))
    o.append(txt(178, 534, "JEONG LAB DAQ", 17, 700, OK, ls="0.8"))
    o.append(txt(178, 562, "rotor rpm — proximity sensor, already recorded"
                           "      ·      fan rpm — PMC analog out O0, "
                           "0.5 V + rpm/300", 15, 500, INK))
    o.append(txt(1806, 545, "one time base", 15, 700, NAVY, "end"))
    o.append("</svg>")
    return W, H, "".join(o)


if __name__ == "__main__":
    for name, fn in (("system_overview", system_overview),
                     ("sweep_protocol", sweep_protocol),
                     ("chain_strip", chain_strip)):
        W, H, svg = fn()
        sp = HERE / f"{name}.svg"
        sp.write_text(svg)
        pp = HERE / f"{name}.png"
        subprocess.run(["rsvg-convert", "-w", str(W * 2), "-o", str(pp),
                        str(sp)], check=True)
        print(f"  {name}.svg + .png   {W}×{H}  "
              f"({pp.stat().st_size/1024:.0f} KB)")
