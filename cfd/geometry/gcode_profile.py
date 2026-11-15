#!/usr/bin/env python3
"""Fuzzy-skin texture of the printed blades, read from their own slices (Stage 2e).

    python3 cfd/geometry/gcode_profile.py                          # Ra10, Ra20, Ra40, Ra80 at z 122.6, 61.3, 183.8 mm
    python3 cfd/geometry/gcode_profile.py --sets Ra40 Ra80 --z 122.6
    python3 cfd/geometry/gcode_profile.py --plot profiles.png      # also a figure of the profiles
    python3 cfd/geometry/gcode_profile.py --no-write               # stats only

Input: blades/as_printed/gcode/<set>Turbine.gcode (git-ignored; SHA256SUMS_gcode.txt is checked).
Bambu Studio 02.08.02.61, P1S, 0.2 mm nozzle, 0.10 mm layers (2451), 4 walls, outer wall
line width 0.22 mm, arc fitting on (enable_arc_fitting = 1), resolution 0.012 mm. Fuzzy skin is
painted on the two curved faces: the config block of every file says 'fuzzy_skin = none' and
'fuzzy_skin_thickness = 0.3' (the plate default); the thickness of each set is in the slicer
project (Ra10 0.025, Ra40 0.101, Ra80 0.202 mm: reports/roughness_2026-09/inputs/
print_lab_20261012/README.md); point distance 0.2 mm, mode 'displacement', noise 'classic'.
The Ra20 file has no fuzzy skin (blades/as_printed/README.md); its profile is the null check.

Method, for one layer (the slicer's '; Z_HEIGHT: <z>' nearest the asked z):
  1. Outer-wall path: the extruding moves under '; FEATURE: Outer wall' (and 'Overhang wall',
     the same loop printed slower) up to the next '; CHANGE_LAYER'; G2/G3 arcs (XY plane,
     centre = start + (I, J)) sampled so that each chord misses its arc by less than 0.5 um.
  2. Reference: the same layer of BaselineTurbine.gcode (no fuzzy skin). A 2D rigid transform
     (rotation and translation, least squares) puts its outer wall at a signed distance of
     -inset from the CAD outline of section_v1.json, in the body frame of
     cfd/stage2/mesh/make_mesh.py (Section): inset = 0.11 mm (half the line width: the path is the
     nozzle centre line), and again with the inset as a fourth unknown; the second fit is used.
  3. Layer alignment: the textured layer's inner walls (fuzzy skin is applied to the outer wall
     only) are fitted rigidly to the reference layer's inner walls; the textured outer wall does
     not enter this fit, so the texture cannot bias it. Check: a fit of the textured outer wall
     to the CAD section.
  4. delta(s) = d_tex(s) + inset: signed distance (+ into the fluid) of the textured outer wall
     from the reference wall, the CAD outline offset inward by the reference layer's inset,
     against the arc length s of the foot point, per painted face as make_mesh.Texture uses it
     (outer = convex face from corner A to B, inner = concave face from corner B to A). Each
     point belongs to the face of its nearest CAD point; points nearer an end face (not painted)
     are not used. The reference wall is taken from the CAD and not from the reference path
     itself: that path is 15 arcs (slicer arc fitting) and departs from the CAD offset by
     about 7 um rms, up to 12 um, the same in every layer; measured from it, delta would carry
     that error (layer-to-layer correlation 0.2-0.3 for Ra10, against 0.03-0.07 from the CAD).
     delta from the reference path itself is reported as a check (stats vs_reference_path).
The mesher (make_mesh.py --tex-profile) multiplies delta by its corner taper (0 at each corner,
full from 0.8 mm), so the values within 0.8 mm of a corner are kept here but not used as given.

Spanwise statistics: the blade scans (surface_roughness.csv) are spanwise profiles, across the
layers. For N_SPAN consecutive layers around z (moved off the bolt holes of section_v1.json),
delta at fixed s (every 50 um) gives the programmed spanwise profile, a step per 0.1 mm layer;
its Ra about the mean and after the scans' Gaussian filter (lambda_c 0.25 mm) are reported with
the scans' values (FS 0.10 for Ra40, FS 0.20 for Ra80; the Ra10 level was never tested).

Output (the sets with fuzzy skin; Ra20 is printed in the table only, as the null check: from the
CAD its delta is the smooth slice's own arc-fitting error, about 6 um Ra, and from the reference
path it is about 0): cfd/geometry/gcode_profiles/<set>_z<z in 0.1 mm>.json, e.g. Ra40_z1226.json: per face
s_mm and delta_mm (knots: the path's vertices and arc samples, linear in between), the
alignment, and stats over the core of each face (0.8 mm from the corners): mean, Ra, Rq,
max |delta|, Ra after the Gaussian filter (ISO 16610-21), facet slopes, spacing of the slicer's
points along s, the spanwise statistics, and the correlation with the other layers written in
the same run. Needs numpy and scipy (system python3).
"""
import argparse
import csv
import datetime
import hashlib
import importlib.util
import json
import math
import re
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import least_squares
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent              # cfd/geometry
REPO = HERE.parent.parent
GCODE = REPO / "blades" / "as_printed" / "gcode"
SHA_FILE = REPO / "blades" / "as_printed" / "SHA256SUMS_gcode.txt"
OUT = HERE / "gcode_profiles"
MAKE_MESH = HERE.parent / "stage2" / "mesh" / "make_mesh.py"
SCANS = (REPO / "reports" / "roughness_2026-09" / "out" / "URI_VAWT_Texture_Data_2026-10-01_rev2" / "4_derived"
         / "surface_roughness.csv")

REFERENCE = "Baseline"                  # BaselineTurbine.gcode, no fuzzy skin
SETS = ("Ra10", "Ra20", "Ra40", "Ra80")
T_NOMINAL_MM = {"Ra10": 0.025, "Ra20": None, "Ra40": 0.101, "Ra80": 0.202}   # slicer project (docstring)
SCAN_ROTOR = {"Ra20": "FS 0.05", "Ra40": "FS 0.10", "Ra80": "FS 0.20"}       # tested sets (Ra20: unconfirmed)
Z_DEFAULT = (122.6, 61.3, 183.8)        # mm: mid-span of the 245.1 mm print, quarter spans
LAYER_H = 0.1                           # mm
HALF_WIDTH = 0.11e-3                    # m, half the outer-wall line width (0.22 mm)
ARC_SAG = 0.5e-6                        # m, largest gap between an arc and its sampling chords
DS_CAD = 2e-6                           # m, vertex spacing of the dense CAD polyline
DS_REF = 5e-6                           # m, sample spacing of the reference path and the inner walls
DS_FIT = 20e-6                          # m, sample spacing of the paths in the rigid fits
LAMBDA_C = 0.25e-3                      # m, Gaussian cut-off of the blade scans (surface_roughness.csv)
DS_GRID = 1e-6                          # m, uniform grid for the profile statistics
N_SPAN = 31                             # layers in the spanwise window (3.1 mm; scans: 1.43 mm columns)
DS_COL = 50e-6                          # m, spacing of the spanwise columns along s
DZ_SPAN = 10e-6                         # m, sampling of the spanwise step profiles
SPACING_BAND = (0.15e-3, 0.25e-3)       # m, 0.75-1.25 x the 0.2 mm point distance (PrusaSlicer rule)
_WORD = re.compile(r"([A-Z])([-+]?(?:\d+\.?\d*|\.\d+))")


def _make_mesh():
    spec = importlib.util.spec_from_file_location("stage2_make_mesh", MAKE_MESH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MM = _make_mesh()                       # Section, smoothstep01, TEX_CORNER_TAPER, SECTION_JSON


# --------------------------------------------------------------------------- G-code
def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def gcode_file(name):
    p = GCODE / f"{name}Turbine.gcode"
    if not p.is_file():
        raise SystemExit(f"{p} not found (the G-code is not in git: blades/as_printed/README.md)")
    return p


def check_sha(path):
    want = {ln.split()[1]: ln.split()[0] for ln in SHA_FILE.read_text().splitlines() if ln.strip()}
    got = sha256(path)
    if want.get(path.name) != got:
        raise SystemExit(f"{path.name}: sha256 {got} does not match {SHA_FILE.name}")
    return got


class GcodeFile:
    """Lines of one G-code file, its slicer version and the index of its '; Z_HEIGHT' lines."""

    def __init__(self, path):
        self.path = Path(path)
        self.sha256 = check_sha(self.path)
        self.lines = self.path.read_text().split("\n")
        self.z = [(i, float(ln[11:])) for i, ln in enumerate(self.lines) if ln.startswith("; Z_HEIGHT:")]
        head = next((ln for ln in self.lines[:5] if ln.startswith("; BambuStudio")), "")
        self.slicer = head[2:].strip()
        self.config = {}
        for ln in self.lines[:2000]:
            m = re.match(r"; (fuzzy_skin[a-z_]*|outer_wall_line_width|layer_height|nozzle_diameter|"
                         r"enable_arc_fitting|resolution|wall_loops) = (.*)$", ln)
            if m:
                self.config[m.group(1)] = m.group(2).strip()

    def layer(self, z_mm):
        """Extruding moves of the layer whose Z_HEIGHT is nearest z_mm: dict(z_mm, layer, moves).
        moves: dict(kind G1|G2|G3, feature, width_mm, p0, p1 (m, bed frame), c (arc centre or
        None), line). Positions are tracked from the previous layer, so the first arc is known."""
        k = min(range(len(self.z)), key=lambda q: abs(self.z[q][1] - z_mm))
        i_z, z = self.z[k]
        i0 = self.z[k - 1][0] if k else 0
        i1 = next((i for i in range(i_z + 1, len(self.lines)) if self.lines[i].startswith("; CHANGE_LAYER")),
                  len(self.lines))
        pos, feat, width, layer_no, moves = None, None, None, None, []
        for i in range(i0, i1):
            ln = self.lines[i]
            if ln.startswith(";"):
                if ln.startswith("; FEATURE:"):
                    feat = ln[10:].strip()
                elif ln.startswith("; LINE_WIDTH:"):
                    width = float(ln[13:])
                elif ln.startswith("; WIPE_START"):
                    feat = "wipe"
                elif ln.startswith("; layer num/total_layer_count:") and i > i_z:
                    layer_no = int(ln.split(":")[1].split("/")[0])
                continue
            code = ln.split(";", 1)[0].strip()
            if not code:
                continue
            head = code.split(None, 1)[0]
            if head == "G91":
                raise RuntimeError(f"{self.path.name}:{i + 1}: relative positioning inside a layer")
            if head not in ("G0", "G1", "G2", "G3"):
                continue
            w = {a: float(b) for a, b in _WORD.findall(code[len(head):])}
            if pos is None:
                if "X" in w and "Y" in w:
                    pos = (w["X"], w["Y"])
                continue
            p1 = (w.get("X", pos[0]), w.get("Y", pos[1]))
            arc = head in ("G2", "G3")
            if i > i_z and w.get("E", 0.0) > 0 and (p1 != pos or arc):
                c = (pos[0] + w.get("I", 0.0), pos[1] + w.get("J", 0.0)) if arc else None
                moves.append(dict(kind=head, feature=feat, width_mm=width, p0=pos, p1=p1, c=c, line=i + 1))
            pos = p1
        for m in moves:                                     # mm -> m
            m["p0"], m["p1"] = np.array(m["p0"]) * 1e-3, np.array(m["p1"]) * 1e-3
            if m["c"] is not None:
                m["c"] = np.array(m["c"]) * 1e-3
        return dict(z_mm=z, layer=layer_no, moves=moves)


def chains(moves, features, tol=2e-6):
    """Runs of consecutive moves of the given features, each starting where the previous one ended."""
    out, prev = [], None
    for m in moves:
        if m["feature"] not in features:
            prev = None
            continue
        if prev is not None and np.linalg.norm(m["p0"] - prev["p1"]) < tol:
            out[-1].append(m)
        else:
            out.append([m])
        prev = m
    return out


def arc_points(m, n=None, sag=ARC_SAG, ds=None):
    """Points on a G2 (clockwise) or G3 (counter-clockwise) arc after its start: n or enough for
    the sagitta and spacing limits. The radius goes linearly from |p0 - c| to |p1 - c| (the two
    differ by the G-code's 1 um rounding); p0 == p1 is a full circle."""
    c, p0, p1 = m["c"], m["p0"], m["p1"]
    r0, r1 = np.linalg.norm(p0 - c), np.linalg.norm(p1 - c)
    a0 = math.atan2(p0[1] - c[1], p0[0] - c[0])
    a1 = math.atan2(p1[1] - c[1], p1[0] - c[0])
    if m["kind"] == "G3":
        da = (a1 - a0) % (2 * math.pi) or 2 * math.pi
    else:
        da = -((a0 - a1) % (2 * math.pi) or 2 * math.pi)
    r = max(r0, r1)
    if n is None:
        step = 2 * math.acos(max(-1.0, 1 - sag / r)) if r > sag else math.pi
        n = max(1, math.ceil(abs(da) / step))
        if ds:
            n = max(n, math.ceil(abs(da) * r / ds))
    f = np.arange(1, n + 1) / n
    a = a0 + f * da
    rr = r0 + f * (r1 - r0)
    P = c + rr[:, None] * np.c_[np.cos(a), np.sin(a)]
    P[-1] = p1
    return P, abs(da) * 0.5 * (r0 + r1)


def sample(chain, ds=None):
    """(points, vertex flag, length in arcs, total length) along a chain of moves: every move's end
    point, points inside the arcs (chord within ARC_SAG of the arc), and with ds, points every ds
    or closer on lines and arcs."""
    pts, vert = [chain[0]["p0"][None, :]], [True]
    l_arc = l_all = 0.0
    for m in chain:
        if m["kind"] == "G1":
            L = float(np.linalg.norm(m["p1"] - m["p0"]))
            n = max(1, math.ceil(L / ds)) if ds else 1
            f = np.arange(1, n + 1) / n
            P = m["p0"] + f[:, None] * (m["p1"] - m["p0"])
        else:
            P, L = arc_points(m, ds=ds)
            l_arc += L
        l_all += L
        pts.append(P)
        vert += [False] * (len(P) - 1) + [True]
    return np.vstack(pts), np.array(vert), l_arc, l_all


def outer_loop(lay, name):
    """The layer's outer-wall loop (the longest chain of outer-wall moves) and a summary."""
    ch = chains(lay["moves"], ("Outer wall", "Overhang wall"))
    if not ch:
        raise RuntimeError(f"{name} z {lay['z_mm']}: no outer wall")
    lens = [sum(np.linalg.norm(m["p1"] - m["p0"]) for m in c) for c in ch]
    main = ch[int(np.argmax(lens))]
    return main, dict(n_moves=len(main), n_arcs=sum(m["kind"] != "G1" for m in main), n_chains=len(ch),
                      other_chain_lengths_mm=[float(v * 1e3) for v in sorted(lens)[:-1]],
                      seam_gap_mm=float(np.linalg.norm(main[-1]["p1"] - main[0]["p0"]) * 1e3),
                      features=sorted({m["feature"] for m in main}),
                      line_width_mm=sorted({m["width_mm"] for m in main}))


# --------------------------------------------------------------------------- geometry
def rigid(x, P):
    """Rotate by x[0] (rad) and translate by (x[1], x[2])."""
    c, s = math.cos(x[0]), math.sin(x[0])
    return np.c_[c * P[:, 0] - s * P[:, 1] + x[1], s * P[:, 0] + c * P[:, 1] + x[2]]


class Curves:
    """Polylines for nearest-point queries. project(Q) -> (d, s, at_end): d the distance to the
    nearest segment, signed + on the right of the direction of travel (for the section loop, which
    runs counter-clockwise with the body on the left: + into the fluid); s the arc length of the foot
    (from the given vertex values s, else the cumulative length); at_end: the foot is an open end."""

    def __init__(self, polylines, closed, s=None):
        P, nxt, prv, sv, off = [], [], [], [], 0
        for k, C in enumerate(polylines):
            C = np.asarray(C, float)
            n = len(C)
            i = off + np.arange(n)
            nx, pv = i + 1, i - 1
            nx[-1], pv[0] = (off, off + n - 1) if closed else (-1, -1)
            if s is not None:
                sv.append(np.asarray(s[k], float))
            else:
                sv.append(np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(C, axis=0), axis=1))])
            P.append(C)
            nxt.append(nx)
            prv.append(pv)
            off += n
        self.P, self.nxt, self.prv, self.s = np.vstack(P), np.concatenate(nxt), np.concatenate(prv), np.concatenate(sv)
        self.closed = closed
        self.tree = cKDTree(self.P)

    def project(self, Q):
        _, i = self.tree.query(Q)
        best = np.full(len(Q), np.inf)
        d, s, end = np.zeros(len(Q)), np.zeros(len(Q)), np.zeros(len(Q), bool)
        for a, b in ((self.prv[i], i), (i, self.nxt[i])):
            ok = (a >= 0) & (b >= 0)
            aa, bb = np.where(ok, a, 0), np.where(ok, b, 0)
            A, AB = self.P[aa], self.P[bb] - self.P[aa]
            L2 = np.einsum("ij,ij->i", AB, AB)
            t = np.clip(np.einsum("ij,ij->i", Q - A, AB) / np.where(L2 > 0, L2, 1.0), 0.0, 1.0)
            F = A + t[:, None] * AB
            dist = np.linalg.norm(Q - F, axis=1)
            side = np.sign(np.einsum("ij,ij->i", Q - F, np.c_[AB[:, 1], -AB[:, 0]]))
            sb = self.s[bb]
            if self.closed:                      # closing segment: its far end is at the loop length
                sb = np.where(bb < aa, self.s[aa] + np.sqrt(L2), sb)
            sv = self.s[aa] + t * (sb - self.s[aa])
            e = ((t <= 0) & (self.prv[aa] < 0)) | ((t >= 1) & (self.nxt[bb] < 0))
            u = ok & (dist < best)
            best[u], d[u], s[u], end[u] = dist[u], (side * dist)[u], sv[u], e[u]
        return d, s, end


class SectionCurves:
    """The CAD section (section_v1.json) as make_mesh.Section sees it, body frame, metres: the
    closed loop, vertices every DS_CAD with every corner a vertex; s is the loop arc length of
    make_mesh (outer face from corner A, inner face from corner B)."""

    def __init__(self):
        sec = MM.Section()
        self.sec = sec
        c = sec.s_corner
        s = np.unique(np.r_[np.arange(0.0, sec.L, DS_CAD), c[:3]])
        P, _ = sec.point(s)
        self.loop = Curves([P], closed=True, s=[s])
        self.L = sec.L
        self.centroid = P.mean(0)
        self.coarse = cKDTree(P[::10])          # 20 um vertices, for the coarse pose search
        self.face_L = {"outer": float(sec.L_o), "inner": float(sec.L_i)}
        self.face_s0 = {"outer": 0.0, "inner": float(c[1])}
        self.holes_z_mm = [[v * 1e3 for v in h["z_range_m"]] for h in sec.json["holes"]["found"]]

    def on_faces(self, Q):
        """(face 0 outer / 1 inner / -1 end face, s from the face's first corner, signed distance)
        of the nearest point of the loop. A path point on an end face is nearer that face than the
        painted one, so it is not mistaken for a painted-face point (a projection onto the painted
        face alone would put the whole end-face run of the path 0.11 mm from the corner)."""
        d, s, _ = self.loop.project(Q)
        c = self.sec.s_corner
        f = np.where(s <= c[0], 0, np.where((s >= c[1]) & (s <= c[2]), 1, -1))
        return f, np.where(f == 1, s - c[1], s), d


# --------------------------------------------------------------------------- fits
def fit_to_section(P, sc, inset=HALF_WIDTH, mirror=False):
    """Rigid transform (theta, tx, ty) of path points P (bed frame) onto the CAD loop offset inward by
    inset: least squares of d + inset. Coarse search over theta (1 deg steps, centroids matched;
    unsigned distance to the 20 um vertices, capped at 2 mm), then the best start refined.
    Returns (x, residuals in m, coarse rms of the best and of the next-best start 10 deg away)."""
    if mirror:
        P = P * np.array([-1.0, 1.0])
    sub = P[:: max(1, len(P) // 1500)]
    cP = P.mean(0)
    tries = []
    for th in np.radians(np.arange(0.0, 360.0, 1.0)):
        c, s = math.cos(th), math.sin(th)
        x = np.array([th, *(sc.centroid - np.array([c * cP[0] - s * cP[1], s * cP[0] + c * cP[1]]))])
        dist, _ = sc.coarse.query(rigid(x, sub), distance_upper_bound=2e-3)
        r = np.minimum(dist, 2e-3) - inset
        tries.append((float(np.sqrt(np.mean(r ** 2))), x))
    tries.sort(key=lambda q: q[0])
    th0 = tries[0][1][0]
    other = next(q[0] for q in tries if abs((q[1][0] - th0 + math.pi) % (2 * math.pi) - math.pi) > math.radians(10))
    r = least_squares(lambda x: sc.loop.project(rigid(x, P))[0] + inset, tries[0][1], method="lm")
    return r.x, r.fun, (tries[0][0], other)


def fit_free_inset(P, sc, x0):
    """As fit_to_section from x0, with the inset as a fourth unknown. Returns (x, residuals)."""
    r = least_squares(lambda x: sc.loop.project(rigid(x[:3], P))[0] + x[3], np.r_[x0, HALF_WIDTH], method="lm")
    return r.x, r.fun


def fit_to_curves(P, cur, x0):
    """Rigid transform of points P (bed frame) onto reference polylines (body frame): least squares of
    the signed distance, soft-L1 beyond 5 um (the loops' seam gaps). Returns (x, residuals)."""
    r = least_squares(lambda x: cur.project(rigid(x, P))[0], x0, method="trf", loss="soft_l1", f_scale=5e-6,
                      x_scale="jac")
    return r.x, cur.project(rigid(r.x, P))[0]


def fit_reference(lay, sc):
    """The reference layer (no fuzzy skin) on the CAD section: the pose x and inset of the free-inset
    fit (used), the fit at 0.11 mm and the mirrored fit (reported), and its outer wall (samples every
    DS_REF) and inner walls in the body frame."""
    ref, info = outer_loop(lay, REFERENCE)
    P = sample(ref, ds=DS_FIT)[0]
    x0, r0, coarse = fit_to_section(P, sc)
    _, r_m, _ = fit_to_section(P, sc, mirror=True)
    x4, r4 = fit_free_inset(P, sc, x0)
    x = x4[:3]
    inner = Curves([rigid(x, sample(c, ds=DS_REF)[0]) for c in chains(lay["moves"], ("Inner wall",))], closed=False)
    return dict(layer=lay, info=info, x=x, inset=float(x4[3]), res=r4, x_fixed=x0, res_fixed=r0, coarse=coarse,
                res_mirror=r_m, inner=inner, Q=rigid(x, sample(ref, ds=DS_REF)[0]))


def res_stats(r):
    a = np.abs(r)
    return dict(rms_mm=float(np.sqrt(np.mean(r ** 2)) * 1e3), mean_mm=float(np.mean(r) * 1e3),
                p99_abs_mm=float(np.percentile(a, 99) * 1e3), max_abs_mm=float(a.max() * 1e3), n=int(r.size))


def pose(x):
    return dict(theta_deg=float(math.degrees(x[0]) % 360.0), t_mm=[float(x[1] * 1e3), float(x[2] * 1e3)])


# --------------------------------------------------------------------------- statistics
def gaussian_mean_line(z, dx, lc=LAMBDA_C):
    """ISO 16610-21 Gaussian mean line of a profile sampled every dx (alpha = sqrt(ln 2 / pi))."""
    al = math.sqrt(math.log(2) / math.pi)
    x = np.arange(-int(1.5 * lc / dx), int(1.5 * lc / dx) + 1) * dx
    w = np.exp(-math.pi * (x / (al * lc)) ** 2)
    return np.convolve(z, w / w.sum(), mode="same")


def spacing_stats(sp):
    if sp.size == 0:
        return dict(n=0)
    q = np.percentile(sp, [5, 25, 50, 75, 95])
    return dict(n=int(sp.size), mean=float(sp.mean() * 1e3), p5=float(q[0] * 1e3), p25=float(q[1] * 1e3),
                p50=float(q[2] * 1e3), p75=float(q[3] * 1e3), p95=float(q[4] * 1e3), max=float(sp.max() * 1e3),
                frac_in_0p15_0p25=float(np.mean((sp >= SPACING_BAND[0]) & (sp <= SPACING_BAND[1]))))


def face_stats(s, v, vs, L, taper=MM.TEX_CORNER_TAPER):
    """Statistics of one face's profile (knots s, v; slicer-point positions vs) over its core,
    taper to L - taper; m. Returns (dict, (core grid, delta on it), point spacings in the core)."""
    g = np.arange(taper, L - taper, DS_GRID)
    z = np.interp(g, s, v)
    zc = z - z.mean()
    rough = (z - gaussian_mean_line(z, DS_GRID))[int(LAMBDA_C / DS_GRID):-int(LAMBDA_C / DS_GRID)]
    sl = np.abs(np.diff(v) / np.diff(s))[(s[1:] > taper) & (s[:-1] < L - taper)]
    sp = np.diff(vs[(vs > taper) & (vs < L - taper)])
    sg = np.arange(0.0, L, DS_GRID)
    applied = np.abs(np.interp(sg, s, v) * MM.smoothstep01(np.minimum(sg, L - sg) / taper))
    return dict(core_mm=[float(taper * 1e3), float((L - taper) * 1e3)], mean_mm=float(z.mean() * 1e3),
                Ra_mm=float(np.mean(np.abs(zc)) * 1e3), Rq_mm=float(np.sqrt(np.mean(zc ** 2)) * 1e3),
                max_abs_mm=float(np.abs(z).max() * 1e3), p99_abs_mm=float(np.percentile(np.abs(z), 99) * 1e3),
                range_mm=[float(z.min() * 1e3), float(z.max() * 1e3)],
                Ra_lc025_mm=float(np.mean(np.abs(rough - rough.mean())) * 1e3),
                max_abs_applied_mm=float(applied.max() * 1e3),
                slope_p50=float(np.median(sl)) if sl.size else 0.0,
                slope_p99=float(np.percentile(sl, 99)) if sl.size else 0.0,
                facet_tilt_max_deg=float(np.degrees(np.arctan(sl.max()))) if sl.size else 0.0,
                spacing_mm=spacing_stats(sp)), (g, z), sp


def both_faces(fstats, grids, spacings):
    """The two faces' cores together: Ra, Rq about the common mean on the joined grids; means and
    Ra_lc025 weighted by core length; maxima."""
    g = np.concatenate([grids["outer"][1], grids["inner"][1]])
    w = np.array([grids["outer"][1].size, grids["inner"][1].size], float)
    w /= w.sum()
    gc = g - g.mean()
    return dict(mean_mm=float(g.mean() * 1e3), Ra_mm=float(np.mean(np.abs(gc)) * 1e3),
                Rq_mm=float(np.sqrt(np.mean(gc ** 2)) * 1e3), max_abs_mm=float(np.abs(g).max() * 1e3),
                p99_abs_mm=float(np.percentile(np.abs(g), 99) * 1e3),
                Ra_lc025_mm=float(sum(wi * f["Ra_lc025_mm"] for wi, f in zip(w, fstats))),
                max_abs_applied_mm=float(max(f["max_abs_applied_mm"] for f in fstats)),
                facet_tilt_max_deg=float(max(f["facet_tilt_max_deg"] for f in fstats)),
                spacing_mm=spacing_stats(np.concatenate(spacings)) if spacings else None)


def span_window(z, sc, n=N_SPAN):
    """n consecutive layer heights (mm), centred on z where possible, whose slice planes (mid-layer,
    z - 0.05 mm) keep 0.05 mm off the bolt holes (print z = STL z); the window moves away from a
    hole one layer at a time."""
    for k in sorted(range(-3 * n, 3 * n + 1), key=abs):
        zs = np.round(z + LAYER_H * (np.arange(n) - n // 2 + k), 1)
        zp = zs - 0.5 * LAYER_H
        if all(zp[-1] < h0 - 0.05 or zp[0] > h1 + 0.05 for h0, h1 in sc.holes_z_mm):
            return zs
    raise RuntimeError(f"no {n}-layer window near z {z} clear of the holes")


def spanwise(gfile, name, z, x_t, inset, sc, n=N_SPAN):
    """Programmed spanwise profiles: delta at fixed s (columns every DS_COL in each face's core)
    over n consecutive layers, each layer a step of 0.1 mm; Ra about each column's mean and Ra of
    the roughness profile (Gaussian mean line, lambda_c 0.25 mm) over the window less 0.25 mm at
    each end, averaged over the columns. Same pose for every layer (the part does not move)."""
    zs = span_window(z, sc, n)
    rows = []
    for zk in zs:
        lay = gfile.layer(zk)
        if abs(lay["z_mm"] - zk) > 1e-6:
            raise RuntimeError(f"{name}: no layer at z {zk}")
        tex, info = outer_loop(lay, name)
        if info["other_chain_lengths_mm"] and max(info["other_chain_lengths_mm"]) > 1.0:
            raise RuntimeError(f"{name} z {zk}: more than one outer-wall loop")
        f, s, d = sc.on_faces(rigid(x_t, sample(tex)[0]))
        row = []
        for k, fname in enumerate(("outer", "inner")):
            L = sc.face_L[fname]
            m = f == k
            o = np.argsort(s[m])
            row.append(np.interp(np.arange(MM.TEX_CORNER_TAPER, L - MM.TEX_CORNER_TAPER, DS_COL), s[m][o],
                                 d[m][o] + inset))
        rows.append(np.concatenate(row))
    M = np.array(rows)                                      # layers x columns, m
    reps = int(round(LAYER_H * 1e-3 / DZ_SPAN))
    P = np.repeat(M, reps, axis=0)
    sig = math.sqrt(math.log(2) / math.pi) * LAMBDA_C / math.sqrt(2 * math.pi) / DZ_SPAN
    rough = P - gaussian_filter1d(P, sig, axis=0, mode="nearest", truncate=4.0)
    cut = int(LAMBDA_C / DZ_SPAN)
    P, rough = P[cut:-cut], rough[cut:-cut]
    r_adj = [np.corrcoef(M[i], M[i + 1])[0, 1] for i in range(len(M) - 1)]
    return dict(z_window_mm=[float(zs[0]), float(zs[-1])], n_layers=int(n), n_columns=int(M.shape[1]),
                evaluated_mm=float(P.shape[0] * DZ_SPAN * 1e3),
                Ra_mm=float(np.mean(np.abs(P - P.mean(0))) * 1e3),
                Ra_lc025_mm=float(np.mean(np.abs(rough - rough.mean(0))) * 1e3),
                adjacent_layer_r_mean=float(np.mean(r_adj)), adjacent_layer_r_absmax=float(np.max(np.abs(r_adj))))


def scans():
    """Measured roughness of the tested sets (surface_roughness.csv), um."""
    try:
        with open(SCANS, newline="") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        return {}
    return {r["rotor"]: dict(Ra_lc025_um=float(r["Ra_lc025_um"]), Pa_um=float(r["Pa_um"]),
                             fuzzy_skin_mm=float(r["fuzzy_skin_mm"])) for r in rows}


# --------------------------------------------------------------------------- profile
def profile(name, lay_t, R, sc, gfile, rfile, meas):
    """Profile of layer lay_t of set `name` against the reference layer's fit R (fit_reference).
    Returns the JSON dict and, per face, the core grids of delta and of delta from the reference path."""
    tex, tex_info = outer_loop(lay_t, name)
    inset = R["inset"]
    # layer alignment: inner walls of the textured layer onto those of the reference layer
    iw_t = np.vstack([sample(c, ds=DS_FIT)[0] for c in chains(lay_t["moves"], ("Inner wall",))])
    Pt_fit = sample(tex, ds=DS_FIT)[0]
    x_tc, r_tc, _ = fit_to_section(Pt_fit, sc)              # the check, and the start of the inner-wall fit
    x_t, r_t = fit_to_curves(iw_t, R["inner"], x_tc)
    dx_check = rigid(x_tc, Pt_fit) - rigid(x_t, Pt_fit)
    # textured knots (vertices and arc samples) and dense reference path, on the painted faces
    Pt, vt, l_arc, l_all = sample(tex)
    ft, st, dt = sc.on_faces(rigid(x_t, Pt))
    fr, sr, dr = sc.on_faces(R["Q"])
    # end faces (not painted): textured minus reference path, 0.3 mm from the corners
    dl_t, sl_t, _ = sc.loop.project(rigid(x_t, sample(tex, ds=DS_REF)[0]))
    dl_r, sl_r, _ = sc.loop.project(R["Q"])
    o = np.argsort(sl_r)
    d_end = dl_t - np.interp(sl_t, sl_r[o], dl_r[o], period=sc.L)
    cs = sc.sec.s_corner
    on_end = (((sl_t > cs[0] + 0.3e-3) & (sl_t < cs[1] - 0.3e-3)) |
              ((sl_t > cs[2] + 0.3e-3) & (sl_t < cs[3] - 0.3e-3)))
    faces, fstats, pstats, grids, pgrids, spacings = {}, [], [], {}, {}, []
    for k, fname in enumerate(("outer", "inner")):
        L = sc.face_L[fname]
        mt, mr = ft == k, fr == k
        o = np.argsort(sr[mr])
        s_k, d_k, v_k = st[mt], dt[mt], vt[mt]
        delta = d_k + inset                                     # from the reference wall
        delta_p = d_k - np.interp(s_k, sr[mr][o], dr[mr][o])    # from the reference path (check)
        ds_path = np.diff(s_k)                                  # path order: s should run one way
        main_dir = np.sign(np.median(ds_path)) if ds_path.size else 1.0
        reversals = int(np.sum((np.sign(ds_path) == -main_dir) & (np.abs(ds_path) < 1e-3)))
        o = np.argsort(s_k, kind="stable")
        s_k, delta, delta_p, v_k = s_k[o], delta[o], delta_p[o], v_k[o]
        keep = np.r_[True, np.diff(s_k) > 1e-9]                 # drop knots repeated in s (seam)
        s_k, delta, delta_p, v_k = s_k[keep], delta[keep], delta_p[keep], v_k[keep]
        st_k, grids[fname], sp = face_stats(s_k, delta, s_k[v_k], L)
        st_p, pgrids[fname], _ = face_stats(s_k, delta_p, s_k[v_k], L)
        st_k.update(n_knots=int(s_k.size), path_reversals_in_s=reversals,
                    s_covered_mm=[float(s_k[0] * 1e3), float(s_k[-1] * 1e3)])
        fstats.append(st_k)
        pstats.append(st_p)
        spacings.append(sp)
        faces[fname] = dict(from_corner="A" if fname == "outer" else "B", L_mm=round(L * 1e3, 6),
                            s0_loop_mm=round(sc.face_s0[fname] * 1e3, 6),
                            s_mm=[round(float(q), 4) for q in s_k * 1e3],
                            delta_mm=[round(float(q), 4) for q in delta * 1e3])
    both = both_faces(fstats, grids, spacings)
    vs_path = {k: v for k, v in both_faces(pstats, pgrids, []).items() if k != "spacing_mm"}
    t_nom = T_NOMINAL_MM.get(name)
    rotor = SCAN_ROTOR.get(name)
    d = dict(
        name=f"{name}_z{round(lay_t['z_mm'] * 10)}",
        what=("Fuzzy-skin displacement of the printed blade's outer wall, read from its slice: delta(s) = signed "
              "normal distance (+ into the fluid) of the textured outer-wall path from the reference wall (the CAD "
              "outline offset inward by the inset of the same layer of the file without fuzzy skin), against the CAD "
              "arc length s of each painted face (cfd/stage2/mesh/make_mesh.py, Texture); linear between knots"),
        generated=datetime.datetime.now().isoformat(timespec="seconds"),
        generator="cfd/geometry/gcode_profile.py",
        source=dict(gcode=str(gfile.path.relative_to(REPO)), sha256=gfile.sha256, slicer=gfile.slicer,
                    layer=lay_t["layer"], z_mm=lay_t["z_mm"], reference_gcode=str(rfile.path.relative_to(REPO)),
                    reference_sha256=rfile.sha256, reference_layer=R["layer"]["layer"],
                    section="cfd/geometry/section_v1.json", fuzzy_skin_thickness_mm_nominal=t_nom,
                    fuzzy_skin_config_block={k: v for k, v in gfile.config.items() if k.startswith("fuzzy")},
                    note=("the config block's fuzzy_skin = none / thickness 0.3 is the plate default; the painted "
                          "faces' thickness is in the slicer project (Print Lab README)")),
        path=dict(textured=tex_info, reference=R["info"], arc_share_of_length=l_arc / l_all if l_all else 0.0),
        alignment=dict(
            frame="body frame of cfd/stage2/mesh/make_mesh.py (Section), from the bed frame by x_body = R(theta) x_bed + t",
            reference=dict(pose(R["x"]), inset_mm=R["inset"] * 1e3, residual=res_stats(R["res"]),
                           fixed_inset=dict(pose(R["x_fixed"]), inset_mm=HALF_WIDTH * 1e3,
                                            residual=res_stats(R["res_fixed"])),
                           coarse_rms_mm=dict(best=R["coarse"][0] * 1e3, next_start_10deg_away=R["coarse"][1] * 1e3),
                           mirrored=dict(residual=res_stats(R["res_mirror"])),
                           note="residual: the reference path's distance from the CAD outline offset by the inset"),
            textured=dict(pose(x_t), method="inner walls onto the reference layer's inner walls (soft-L1)",
                          residual=res_stats(r_t),
                          check_outer_wall_to_section=dict(pose(x_tc), residual=res_stats(r_tc),
                                                           max_shift_of_outer_wall_mm=float(
                                                               np.linalg.norm(dx_check, axis=1).max() * 1e3)))),
        end_faces=dict(note="not painted: textured minus reference path on the end faces, 0.3 mm from the corners",
                       n=int(on_end.sum()), mean_mm=float(d_end[on_end].mean() * 1e3) if on_end.any() else None,
                       max_abs_mm=float(np.abs(d_end[on_end]).max() * 1e3) if on_end.any() else None),
        faces=faces,
        stats=dict(note=("core of each face (0.8 mm from the corners, the mesher's taper), uniform 1 um grid; Ra, Rq "
                         "about the mean; Ra_lc025 after the ISO 16610-21 Gaussian filter, lambda_c 0.25 mm (as "
                         "Ra_lc025_um of the blade scans), here along s (chordwise); max_abs_applied with the corner "
                         "taper, whole face; slopes |d delta/ds| between knots; spacing: of the slicer's points "
                         "(G-code vertices) along s; spanwise: across the layers, as the scans"),
                   both=both, outer=fstats[0], inner=fstats[1], vs_reference_path=vs_path,
                   spanwise=spanwise(gfile, name, lay_t["z_mm"], x_t, inset, sc),
                   synthetic=(dict(t_mm=t_nom, Ra_mm=0.397 * t_nom, Rq_mm=0.471 * t_nom,
                                   note="nominal texture of make_mesh.Texture, t u(s), u uniform at 0.2 mm (README)")
                              if t_nom else None),
                   scans=dict(rotor=rotor, **meas.get(rotor, {}), plain=meas.get("Plain"),
                              source=str(SCANS.relative_to(REPO)),
                              note="spanwise image columns, levelled; Ra after lambda_c 0.25 mm")
                   if rotor else None),
    )
    return d, grids, pgrids


# --------------------------------------------------------------------------- output
def table(rows):
    print(f"{'profile':11s} {'layer':>5s} {'ref rms':>7s} {'inset':>6s} {'tex rms':>7s} {'check':>6s} {'mean':>6s} "
          f"{'Ra':>6s} {'Rq':>6s} {'max':>5s} {'Ra/t':>5s} {'Ra.25':>6s} {'span':>6s} {'sp.25':>6s} {'r adj':>6s} "
          f"{'path Ra':>7s} {'p50 sp':>6s} {'band':>5s} {'arcs':>5s} {'tilt':>5s} {'end':>5s}")
    for d in rows:
        a, b, sw = d["alignment"], d["stats"]["both"], d["stats"]["spanwise"]
        t = d["source"]["fuzzy_skin_thickness_mm_nominal"]
        print(f"{d['name']:11s} {d['source']['layer']:5d} {a['reference']['residual']['rms_mm'] * 1e3:6.1f}u "
              f"{a['reference']['inset_mm']:6.3f} {a['textured']['residual']['rms_mm'] * 1e3:6.2f}u "
              f"{a['textured']['check_outer_wall_to_section']['max_shift_of_outer_wall_mm'] * 1e3:5.1f}u "
              f"{b['mean_mm'] * 1e3:5.1f}u {b['Ra_mm'] * 1e3:5.1f}u {b['Rq_mm'] * 1e3:5.1f}u "
              f"{b['max_abs_mm'] * 1e3:4.0f}u {(b['Ra_mm'] / t if t else float('nan')):5.3f} "
              f"{b['Ra_lc025_mm'] * 1e3:5.1f}u {sw['Ra_mm'] * 1e3:5.1f}u {sw['Ra_lc025_mm'] * 1e3:5.1f}u "
              f"{sw['adjacent_layer_r_mean']:6.3f} {d['stats']['vs_reference_path']['Ra_mm'] * 1e3:6.1f}u "
              f"{b['spacing_mm'].get('p50', float('nan')):6.3f} {b['spacing_mm'].get('frac_in_0p15_0p25', float('nan')):5.2f} "
              f"{d['path']['arc_share_of_length']:5.2f} {b['facet_tilt_max_deg']:5.1f} "
              f"{(d['end_faces']['max_abs_mm'] or 0) * 1e3:4.1f}u")


def plot(path, rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    COL = {"Ra10": "#1baf7a", "Ra20": "#9a9890", "Ra40": "#2a78d6", "Ra80": "#eb6834"}
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
                         "ytick.color": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
                         "figure.facecolor": SURF, "axes.facecolor": SURF, "legend.frameon": False})
    fig, ax = plt.subplots(3, 1, figsize=(11, 9))
    mid = [d for d in rows if d["name"].endswith("_z1226")] or rows
    for d in mid:
        st = d["name"].split("_")[0]
        f = d["faces"]["outer"]
        s, v = np.array(f["s_mm"]), np.array(f["delta_mm"])
        m = (s > 30) & (s < 36)
        ax[0].plot(s[m], v[m] * 1e3, lw=0.9, color=COL.get(st, INK), label=d["name"])
        t = d["source"]["fuzzy_skin_thickness_mm_nominal"]
        if t:
            for sg in (-1, 1):
                ax[0].axhline(sg * t * 1e3, color=COL[st], lw=0.6, ls="--")
            g = np.arange(0.8, f["L_mm"] - 0.8, 0.001)
            ax[1].hist(np.interp(g, s, v) / t, bins=np.linspace(-1.6, 1.6, 161), histtype="step",
                       color=COL[st], density=True, label=d["name"])
    rng = np.random.default_rng(0)
    a, b, w = rng.uniform(-1, 1, 400000), rng.uniform(-1, 1, 400000), rng.uniform(0, 1, 400000)
    ax[1].hist((1 - w) * a + w * b, bins=np.linspace(-1.6, 1.6, 161), histtype="step", color=INK2, lw=1.2,
               density=True, label="synthetic (linear between uniform samples)")
    ax[0].set_xlabel("s along the outer (convex) face from corner A, mm")
    ax[0].set_ylabel("delta, um")
    ax[0].set_title("(a) Outer-wall displacement at mid-span from the G-code (dashed: +-t)", loc="left",
                    fontsize=10, color=INK)
    ax[0].legend(loc="upper right", fontsize=7.5, ncol=4)
    ax[1].set_xlabel("delta / t, core of the outer face")
    ax[1].set_ylabel("density")
    ax[1].set_title("(b) Distribution of delta in units of the nominal t", loc="left", fontsize=10, color=INK)
    ax[1].legend(loc="upper right", fontsize=7.5)
    names = [d["name"] for d in rows]
    x = np.arange(len(rows))
    syn = [(d["stats"]["synthetic"] or {}).get("Ra_mm", 0) * 1e3 for d in rows]
    ra = [d["stats"]["both"]["Ra_mm"] * 1e3 for d in rows]
    sp = [d["stats"]["spanwise"]["Ra_lc025_mm"] * 1e3 for d in rows]
    ax[2].bar(x - 0.27, syn, 0.27, color="#c9c7c0", label="synthetic 0.397 t")
    ax[2].bar(x, ra, 0.27, color="#2a78d6", label="G-code Ra (along s)")
    ax[2].bar(x + 0.27, sp, 0.27, color="#1baf7a", label="G-code Ra, spanwise, lambda_c 0.25 mm")
    lab = "scan Ra, lambda_c 0.25 mm (FS 0.05 / 0.10 / 0.20)"
    for i, d in enumerate(rows):
        sc_ = d["stats"]["scans"]
        if sc_ and "Ra_lc025_um" in sc_:
            ax[2].plot([i + 0.27], [sc_["Ra_lc025_um"]], "D", color="#eb6834", ms=5, label=lab)
            lab = None
    ax[2].axhline(12.74, color="#eb6834", lw=0.8, ls=":", label="scan Ra, Plain (12.7 um)")
    ax[2].set_xticks(x, names, rotation=30, ha="right", fontsize=7.5)
    ax[2].set_ylabel("Ra, um")
    ax[2].set_title("(c) Ra of the programmed texture against the synthetic texture and the scans", loc="left",
                    fontsize=10, color=INK)
    ax[2].legend(loc="upper left", fontsize=7.5, ncol=2)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sets", nargs="+", default=list(SETS), choices=SETS)
    ap.add_argument("--z", nargs="+", type=float, default=list(Z_DEFAULT), help="layer heights, mm (nearest layer)")
    ap.add_argument("--out", default=str(OUT), help="output folder (default %(default)s)")
    ap.add_argument("--plot", help="PNG of the mid-span profiles and the Ra comparison")
    ap.add_argument("--no-write", action="store_true", help="print the stats only")
    a = ap.parse_args()
    sc = SectionCurves()
    meas = scans()
    rfile = GcodeFile(gcode_file(REFERENCE))
    refs = {z: fit_reference(rfile.layer(z), sc) for z in a.z}
    rows = []
    for name in a.sets:
        gfile = GcodeFile(gcode_file(name))
        res = []
        for z in a.z:
            lay = gfile.layer(z)
            if abs(lay["z_mm"] - refs[z]["layer"]["z_mm"]) > 1e-6:
                raise RuntimeError(f"{name}: layer z {lay['z_mm']} against reference z {refs[z]['layer']['z_mm']}")
            res.append(profile(name, lay, refs[z], sc, gfile, rfile, meas))
        for d, grids, pgrids in res:             # layer to layer: correlation of the core profiles
            cor, cor_p = {}, {}
            for d2, g2, p2 in res:
                if d2 is not d:
                    cor[d2["name"]] = [float(np.corrcoef(grids[f][1], g2[f][1])[0, 1]) for f in ("outer", "inner")]
                    cor_p[d2["name"]] = [float(np.corrcoef(pgrids[f][1], p2[f][1])[0, 1]) for f in ("outer", "inner")]
            d["stats"]["correlation_with_other_layers"] = dict(
                note="Pearson r of delta on the common 1 um grid, [outer face, inner face]", **cor)
            d["stats"]["vs_reference_path"]["correlation_with_other_layers"] = cor_p
        for d, _, _ in res:
            rows.append(d)
            if not a.no_write and T_NOMINAL_MM.get(name):    # Ra20 (no fuzzy skin): the table only
                Path(a.out).mkdir(parents=True, exist_ok=True)
                p = Path(a.out) / f"{d['name']}.json"
                p.write_text(json.dumps(d, separators=(",", ":")) + "\n")
                print(f"wrote {p} ({p.stat().st_size / 1024:.0f} kB)")
    table(rows)
    if a.plot:
        plot(a.plot, rows)


if __name__ == "__main__":
    main()
