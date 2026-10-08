#!/usr/bin/env python3
"""2D meshes around the blade v1 section for Stage 2 (roughness; cfd/PLAN.md).

Copied from cfd/section2d/mesh/make_mesh.py (Stage 1, 8 Oct 2026) and extended; the Stage 1
file is not touched (its production queue builds meshes with it on the fly). The levels
coarse / medium / fine reproduce the Stage 1 meshes node for node; only the wall patch is
split (below). New here:

  wf    wall-function ring for nutkRoughWallFunction (Stage 2b). First cell height h0 from a
        flat-plate u_tau at the case speed U for a first-cell-centre y+ of about 40, but at
        least 2 x 1.1 x KS_MAX (KS_MAX = 400 um), so that the first cell centre y_p = h0/2
        lies above the largest sand-grain height of the sweep (y_p > ks; the rough log law
        does not describe a cell centre inside the roughness), and at most 1.3 mm (the wall
        is 1.854 mm thick and the end faces 1.854 mm long). Two layers (growth 1.15), wall
        spacing 0.20-0.30 mm, outer region as Stage 1 medium.
  tex   resolved fuzzy-skin texture (Stage 2e), low-Re ring (h0 = 4.5 um as Stage 1). The
        wall nodes of the two painted faces (outer = convex, inner = concave surface; not
        the square end faces) are displaced along the smooth-wall normal by
            delta(s) = t * u(s),
        u = uniform random in [-1, 1] at points every ~0.2 mm of arc length (each face's
        length divided into an integer number of equal intervals: 0.2001 and 0.2002 mm), linear
        in between, u = 0 at the four corners; one fixed seed (default 1) draws u once
        (outer face A -> B, then inner face B -> A), so every t has the same pattern scaled
        by t. The amplitude ramps from 0 at each corner to full 0.8 mm from it (smoothstep;
        without it the texture and the corner fans of the ring overlap and fold cells at
        t = 0.2 mm). Wall spacing 0.2 mm / TEX_NSEG on the painted faces (40 um for 5). The
        displacement fades out through the ring as w(d) = 1 - smoothstep(d / D),
        D = 2.5 t + 0.1 mm, so the first cells keep h0 and no cell inverts
        (cell heights change by at most 1.5 t / D < 60 %); the ring is at least
        max(0.6 mm, D) thick and its edge, where gmsh starts, is not displaced.

Patches: blade (wall: outer and inner surfaces, the fuzzy-skin "painted" faces),
bladeEnds (wall: the two square end faces, not painted), farfield (patch), frontAndBack
(empty). Both walls are in the patch group bladeWall. Forces need both patches.

Coordinates and frame: as Stage 1 (cfd/section2d/README.md section 1): body frame, metres,
origin at the section centroid, alpha = 0 is "cup into the wind".

Usage (venv python, which has gmsh):
    cfd/.venv/bin/python cfd/stage2/mesh/make_mesh.py --level wf --U 23 --alpha 0 --out <caseDir> [--plot p.png]
    cfd/.venv/bin/python cfd/stage2/mesh/make_mesh.py --level tex --tex 0.2e-3 --seed 1 --alpha 0 --out <caseDir>
    cfd/.venv/bin/python cfd/stage2/mesh/make_mesh.py --level medium --alpha 0 --out <caseDir>   # Stage 1 mesh, split walls
Writes <caseDir>/constant/polyMesh/* and <caseDir>/mesh_info.json.
"""
import argparse
import json
import math
import shutil
import time
from pathlib import Path

import numpy as np
from scipy.interpolate import BSpline
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
CFD = HERE.parent.parent
SECTION_JSON = CFD / "geometry" / "section_v1.json"
SECTION_CSV = CFD / "geometry" / "section_v1.csv"

C_REF = 0.048          # m, reference chord (reports' value; coefficients use it)
DZ = 1.0e-3            # m, cell depth (span of the 2D slab)
NU = 1.516e-5          # m^2/s (cfd/templates/transportProperties)

# --------------------------------------------------------------------------- levels
# Lengths in metres. h0 is the first cell height; ds_* are wall spacings (ds_end_max: cap on
# the end faces); s_* are outer-region sizes; g_* growth ratios. coarse/medium/fine: Stage 1.
LEVELS = {
    "coarse": dict(h0=4.5e-6, r_bl=1.20, ds_max=0.21e-3, ds_corner=64e-6, g_t=1.15,
                   s_near=0.42e-3, d_near=6e-3, s_wake=0.85e-3, s_wake2=1.7e-3,
                   g_out=0.12, s_far=0.10),
    "medium": dict(h0=4.5e-6, r_bl=1.15, ds_max=0.15e-3, ds_corner=45e-6, g_t=1.12,
                   s_near=0.30e-3, d_near=6e-3, s_wake=0.60e-3, s_wake2=1.2e-3,
                   g_out=0.10, s_far=0.08),
    "fine":   dict(h0=4.5e-6, r_bl=1.10, ds_max=0.105e-3, ds_corner=32e-6, g_t=1.10,
                   s_near=0.21e-3, d_near=6e-3, s_wake=0.42e-3, s_wake2=0.85e-3,
                   g_out=0.08, s_far=0.06),
    # wall functions: h0 from U (wf_first_cell); 2 layers; outer region as medium
    "wf":     dict(h0=None, r_bl=1.15, n_layers=2, ds_max=0.30e-3, ds_corner=0.20e-3, ds_end_max=0.25e-3,
                   g_t=1.12, s_near=0.30e-3, d_near=6e-3, s_wake=0.60e-3, s_wake2=1.2e-3,
                   g_out=0.10, s_far=0.08),
    # resolved texture: low-Re ring; layers grow to dn_max, then constant to the ring thickness
    "tex":    dict(h0=4.5e-6, r_bl=1.15, dn_max=60e-6, ring_min=0.6e-3, ds_end_max=0.12e-3, g_t=1.12,
                   s_near=0.30e-3, d_near=6e-3, s_wake=0.60e-3, s_wake2=1.2e-3,
                   g_out=0.10, s_far=0.08),
}
R_FF_CHORDS = 27.0     # far-field radius in reference chords (1.296 m)
WAKE = dict(x_up=-0.6, x1=4.0, x2=8.0, w1=0.75, w2=1.5)   # in chords, free-stream frame
LAMBDA_FAN = 2.0       # width of the corner fan blend, in units of the layer distance

# wall-function first cell (level wf)
WF_YPLUS = 40.0        # target first-cell-centre y+ (flat-plate u_tau at x = X_FP)
WF_KS_MAX = 400e-6     # m, largest sand-grain height of the Stage 2b sweep
WF_YP_OVER_KS = 1.1    # first cell centre at least 1.1 KS_MAX above the wall
WF_H0_MAX = 1.3e-3     # m, cap (wall and end faces are 1.854 mm)
X_FP = 0.5 * 0.04461   # m, half the end-face-midpoint chord (as cfd/rotor2d/mesh/make_mesh.py)

# resolved texture (level tex)
TEX_DL = 0.2e-3        # m, fuzzy-skin point distance (resampling interval of the random field)
TEX_NSEG = 5           # wall cells per resampling interval (40 um)
TEX_BLEND = (2.5, 0.1e-3)   # D = 2.5 t + 0.1 mm: fade-out distance of the displacement
TEX_CORNER_TAPER = 0.8e-3   # m, texture amplitude ramps from 0 at each corner to full at 0.8 mm


# --------------------------------------------------------------------------- geometry
def unit(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def rot(v, a):
    c, s = np.cos(a), np.sin(a)
    return np.stack([c * v[..., 0] - s * v[..., 1], s * v[..., 0] + c * v[..., 1]], -1)


class Section:
    """Wall of the section in the body frame, as a closed loop parametrised by
    arc length s, counter-clockwise (body on the left, fluid on the right):
    outer surface A->B, end face B, inner surface B->A, end face A."""

    def __init__(self, path=SECTION_JSON):
        d = json.loads(Path(path).read_text())
        m = d["model"]
        self.json = d
        knots = np.array(m["outer_surface"]["knots"])
        ctrl = np.array(m["outer_surface"]["ctrl_xy_m"])
        self.wall = float(m["wall_m"])
        spl_cad = BSpline(knots, ctrl, 3)
        A, B = spl_cad(0.0), spl_cad(1.0)
        t_hat = unit(B - A)
        n_hat = np.array([t_hat[1], -t_hat[0]])             # right normal: convex side
        self.chord_dir_deg = math.degrees(math.atan2(t_hat[1], t_hat[0]))
        self.normal_dir_deg = math.degrees(math.atan2(n_hat[1], n_hat[0]))
        tt = np.linspace(0, 1, 40001)
        Po = spl_cad(tt)
        To = unit(spl_cad.derivative()(tt))
        Pi = Po + self.wall * np.stack([-To[:, 1], To[:, 0]], -1)
        loop = np.vstack([Po, Pi[::-1]])
        x, y = loop[:, 0], loop[:, 1]
        xn, yn = np.roll(x, -1), np.roll(y, -1)
        cr = x * yn - xn * y
        area = 0.5 * cr.sum()
        cx = ((x + xn) * cr).sum() / (6 * area)
        cy = ((y + yn) * cr).sum() / (6 * area)
        self.area = area
        self.centroid_cad = np.array([cx, cy])
        self.R_cad2body = np.array([n_hat, t_hat])           # rows: body x, body y
        ctrl_b = (ctrl - self.centroid_cad) @ self.R_cad2body.T
        self.spl = BSpline(knots, ctrl_b, 3)
        self.dspl = self.spl.derivative()
        n = 200001
        t = np.linspace(0, 1, n)
        P = self.spl(t)
        T = unit(self.dspl(t))
        Q = P + self.wall * np.stack([-T[:, 1], T[:, 0]], -1)  # inner surface (left offset)
        self._t = t
        self._so = np.r_[0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
        self._si = np.r_[0, np.cumsum(np.linalg.norm(np.diff(Q, axis=0), axis=1))]
        self.L_o = self._so[-1]
        self.L_i = self._si[-1]
        self.A_out, self.B_out = self.spl(0.0), self.spl(1.0)
        TA, TB = unit(self.dspl(0.0)), unit(self.dspl(1.0))
        self.A_in = self.A_out + self.wall * np.array([-TA[1], TA[0]])
        self.B_in = self.B_out + self.wall * np.array([-TB[1], TB[0]])
        self.L_eB = np.linalg.norm(self.B_in - self.B_out)
        self.L_eA = np.linalg.norm(self.A_out - self.A_in)
        self.L = self.L_o + self.L_eB + self.L_i + self.L_eA
        # corners (s of the loop), in order: outer B, inner B, inner A, outer A (= s 0 / L)
        self.s_corner = np.array([self.L_o, self.L_o + self.L_eB,
                                  self.L_o + self.L_eB + self.L_i, self.L])
        self.P_corner = np.array([self.B_out, self.B_in, self.A_in, self.A_out])

    def _outer(self, s):
        t = np.interp(s, self._so, self._t)
        P = self.spl(t)
        T = unit(self.dspl(t))
        return P, np.stack([T[:, 1], -T[:, 0]], -1)

    def _inner(self, s_from_B):
        s_t = self.L_i - s_from_B
        t = np.interp(s_t, self._si, self._t)
        P = self.spl(t)
        T = unit(self.dspl(t))
        nl = np.stack([-T[:, 1], T[:, 0]], -1)
        return P + self.wall * nl, nl

    def point(self, s):
        """Wall point and fluid-side unit normal at loop arc length s (any real, wrapped)."""
        s = np.mod(np.atleast_1d(np.asarray(s, float)), self.L)
        P = np.zeros((s.size, 2))
        N = np.zeros((s.size, 2))
        c = self.s_corner
        m = s <= c[0]
        if m.any():
            P[m], N[m] = self._outer(s[m])
        m = (s > c[0]) & (s <= c[1])
        if m.any():
            f = (s[m] - c[0]) / self.L_eB
            P[m] = self.B_out + f[:, None] * (self.B_in - self.B_out)
            e = unit(self.B_in - self.B_out)
            N[m] = np.array([e[1], -e[0]])
        m = (s > c[1]) & (s <= c[2])
        if m.any():
            P[m], N[m] = self._inner(s[m] - c[1])
        m = s > c[2]
        if m.any():
            f = (s[m] - c[2]) / self.L_eA
            P[m] = self.A_in + f[:, None] * (self.A_out - self.A_in)
            e = unit(self.A_out - self.A_in)
            N[m] = np.array([e[1], -e[0]])
        return P, N

    def corner_normals(self):
        eps = 1e-9
        _, Nb = self.point(self.s_corner - eps)
        _, Na = self.point(self.s_corner + eps)
        return Nb, Na

    def end_segments(self):
        return [(self.B_out, self.B_in), (self.A_in, self.A_out)]


# --------------------------------------------------------------------------- 1D spacing
def distribute(L, s0, s1, g, smax):
    """Node positions on [0, L] (both ends included): spacing s0 at 0 and s1 at L,
    growing geometrically by about g per cell, capped at smax."""
    x = np.linspace(0, L, 20001)
    sp = np.minimum(np.minimum(smax, s0 + (g - 1) * x), s1 + (g - 1) * (L - x))
    I = np.r_[0, np.cumsum(0.5 * (1 / sp[1:] + 1 / sp[:-1]) * np.diff(x))]
    n = max(2, int(round(I[-1])))
    return np.interp(np.linspace(0, I[-1], n + 1), I, x)


def _end_cap(p):
    if "ds_end_max" in p:
        return p["ds_end_max"]
    dmax = p["ds_max"]
    return min(dmax, 0.12e-3 if dmax > 0.12e-3 else dmax)     # Stage 1 rule


def wall_nodes(sec, p):
    """Loop arc-length positions of the wall nodes (Stage 1 scheme), starting at the middle of
    the outer surface, each corner exactly a node."""
    dc, g, dmax = p["ds_corner"], p["g_t"], p["ds_max"]
    e_max = _end_cap(p)
    pieces = [
        distribute(sec.L_o, dc, dc, g, dmax),
        sec.s_corner[0] + distribute(sec.L_eB, dc, dc, g, e_max),
        sec.s_corner[1] + distribute(sec.L_i, dc, dc, g, dmax),
        sec.s_corner[2] + distribute(sec.L_eA, dc, dc, g, e_max),
    ]
    s = np.concatenate([q[:-1] for q in pieces])
    s0 = 0.5 * sec.L_o
    s_shift = np.mod(s - s0, sec.L)
    order = np.argsort(s_shift)
    return s_shift[order], s0


# --------------------------------------------------------------------------- texture
class Texture:
    """Fuzzy-skin displacement delta(s) = t u(s) on the painted faces (outer, inner).
    u: uniform in [-1, 1] at n + 1 equally spaced points per face (n = round(L / TEX_DL)),
    0 at both ends (the corners), linear in between. Drawn once from default_rng(seed):
    outer face (A -> B), then inner face (B -> A)."""

    def __init__(self, sec, t, seed=1, dl=TEX_DL):
        self.t, self.seed, self.dl_nominal = float(t), int(seed), float(dl)
        self.L = float(sec.L)
        rng = np.random.default_rng(self.seed)
        self.faces = []
        for name, s_start, L in (("outer", 0.0, sec.L_o), ("inner", sec.s_corner[1], sec.L_i)):
            n = max(1, int(round(L / dl)))
            u = rng.uniform(-1.0, 1.0, n + 1)
            u[0] = u[-1] = 0.0
            self.faces.append(dict(name=name, s0=float(s_start), L=float(L), n=n, dl=L / n, u=u))

    def nodes(self, nseg):
        """Loop arc-length wall nodes of the two painted faces (nseg per interval), each face
        including both corners."""
        return [f["s0"] + np.linspace(0.0, f["L"], f["n"] * nseg + 1) for f in self.faces]

    def delta(self, s_loop, taper=True):
        """Displacement (m, + into the fluid) at loop arc length s (0 on the end faces). With
        taper, multiplied by smoothstep(distance to the nearest corner / TEX_CORNER_TAPER):
        0 at the corner, full from 0.8 mm on (keeps the texture out of the corner fans).
        s is wrapped into [0, L): the ring passes s' + s0, which runs past L on the outer face
        from corner A to its middle (fixed 8 Oct review: without the wrap that half of the
        outer face was left smooth)."""
        s_loop = np.mod(np.asarray(s_loop, float), self.L)
        out = np.zeros_like(s_loop)
        for f in self.faces:
            m = (s_loop >= f["s0"] - 1e-12) & (s_loop <= f["s0"] + f["L"] + 1e-12)
            x = np.linspace(0.0, f["L"], f["n"] + 1)
            sf = s_loop[m] - f["s0"]
            a = smoothstep01(np.minimum(sf, f["L"] - sf) / TEX_CORNER_TAPER) if taper else 1.0
            out[m] = self.t * np.interp(sf, x, f["u"]) * a
        return out

    def stats(self):
        u = np.concatenate([f["u"][1:-1] for f in self.faces])
        slopes = np.concatenate([np.abs(np.diff(f["u"])) * self.t / f["dl"] for f in self.faces])
        return dict(t_m=self.t, seed=self.seed, dl_nominal_m=self.dl_nominal,
                    dl_m=[f["dl"] for f in self.faces], n_intervals=[f["n"] for f in self.faces],
                    delta_rms_m=float(self.t * np.sqrt(np.mean(u ** 2))),
                    delta_absmax_m=float(self.t * np.abs(u).max()),
                    Ra_m=float(self.t * np.mean(np.abs(u))),
                    facet_slope_max=float(slopes.max()), facet_slope_mean=float(slopes.mean()),
                    facet_tilt_max_deg=float(np.degrees(np.arctan(slopes.max()))),
                    facet_tilt_p99_deg=float(np.degrees(np.arctan(np.percentile(slopes, 99)))) if slopes.size else 0.0,
                    note="Ra_m, delta_rms_m: of the sample values (the linear profile between samples "
                         "has smaller moments: for independent uniform samples Ra of the profile "
                         "is about 0.8 x this; see README)")


def tex_wall_nodes(sec, p, tex, nseg):
    """Wall nodes for the tex level: painted faces on the resampling grid (nseg per interval),
    end faces graded from the same spacing. Returns (s' shifted to start mid outer face, s0)."""
    po, pi = tex.nodes(nseg)
    dc = TEX_DL / nseg
    e_max = _end_cap(p)
    pieces = [po,
              sec.s_corner[0] + distribute(sec.L_eB, dc, dc, p["g_t"], e_max),
              pi,
              sec.s_corner[2] + distribute(sec.L_eA, dc, dc, p["g_t"], e_max)]
    s = np.concatenate([q[:-1] for q in pieces])
    s0 = 0.5 * sec.L_o
    s_shift = np.mod(s - s0, sec.L)
    order = np.argsort(s_shift)
    s_shift = s_shift[order]
    if np.diff(s_shift).min() <= 0:
        raise RuntimeError("tex wall nodes not strictly increasing")
    return s_shift, s0


# --------------------------------------------------------------------------- ring
def smoothstep(x):
    t = np.clip(0.5 * (x + 1.0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def smoothstep01(x):
    t = np.clip(x, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def wf_first_cell(U, yplus=WF_YPLUS, ks_max=WF_KS_MAX):
    """(h0, u_tau_fp, yplus_fp): flat-plate u_tau (Schlichting cf = 0.0592 Re_x^-0.2 at
    x = X_FP), h0 = 2 y+ nu / u_tau, then max(h0, 2 * 1.1 * ks_max) and min(h0, 1.3 mm)."""
    Re = max(U, 1e-6) * X_FP / NU
    u_tau = U * math.sqrt(0.5 * 0.0592 * Re ** -0.2)
    h_y = 2.0 * yplus * NU / u_tau
    h0 = min(max(h_y, 2.0 * WF_YP_OVER_KS * ks_max), WF_H0_MAX)
    return h0, u_tau, 0.5 * h0 * u_tau / NU


def layer_distances(p, h0, ring_thickness=None):
    """d[k], k = 0 .. K (d[0] = 0 at the wall)."""
    r = p["r_bl"]
    if p.get("n_layers"):
        K = int(p["n_layers"])
        return np.r_[0.0, h0 * (r ** np.arange(1, K + 1) - 1) / (r - 1)]
    if p.get("dn_max"):                      # tex: grow to dn_max, then constant to ring_thickness
        d, h = [0.0], h0
        while d[-1] < ring_thickness - 1e-12:
            d.append(d[-1] + h)
            h = min(h * r, p["dn_max"])
        return np.array(d)
    K = int(math.ceil(math.log(p["ds_max"] / h0) / math.log(r))) + 1
    return np.r_[0.0, h0 * (r ** np.arange(1, K + 1) - 1) / (r - 1)]


def ring_layers(sec, d, sw, s0):
    """Structured near-wall layers (Stage 1 scheme): X[k, i, 2] with k = 0 the wall, for the
    shifted wall nodes sw (s' = s - s0) and layer distances d."""
    sc = np.mod(sec.s_corner - s0, sec.L)
    oc = np.argsort(sc)
    sc = sc[oc]
    Pc = sec.P_corner[oc]
    Nb, Na = sec.corner_normals()
    Nb, Na = Nb[oc], Na[oc]
    K = len(d) - 1
    X = np.zeros((K + 1, sw.size, 2))
    X[0], _ = sec.point(sw + s0)
    q = 0.5 * math.pi
    for k in range(1, K + 1):
        dk = d[k]
        H = smoothstep((sw[:, None] - sc[None, :]) / (LAMBDA_FAN * dk))
        sstar = sw + q * dk * H.sum(1)
        arc_start = sc + q * dk * np.arange(4)
        arc_end = arc_start + q * dk
        P = np.zeros((sw.size, 2))
        on_arc = np.zeros(sw.size, bool)
        for c in range(4):
            m = (sstar >= arc_start[c]) & (sstar <= arc_end[c])
            phi = (sstar[m] - arc_start[c]) / dk
            P[m] = Pc[c] + dk * rot(np.broadcast_to(Nb[c], (m.sum(), 2)), phi)
            on_arc |= m
        m = ~on_arc
        n_before = (sstar[m, None] > arc_end[None, :]).sum(1)
        s_wall = sstar[m] - q * dk * n_before
        Pw, Nw = sec.point(s_wall + s0)
        P[m] = Pw + dk * Nw
        X[k] = P
    return X


def apply_texture(X, d, sec, s_loop, tex):
    """Displace the ring by delta(s) w(d_k) along the smooth-wall normal at each wall node;
    w = 1 - smoothstep(d / D), D = 2.5 t + 0.1 mm. Returns D. (Tested 8 Oct: moving the layer
    nodes along their own grid lines instead, which bend in the corner fans, gave inverted
    cells near the corners at t = 0.2 mm; the corner taper in Texture.delta removes the
    fan-texture overlap instead.)"""
    D = TEX_BLEND[0] * tex.t + TEX_BLEND[1]
    if d[-1] < D - 1e-12:
        raise RuntimeError(f"ring ({d[-1]:.3g} m) thinner than the texture fade-out distance {D:.3g} m")
    delta = tex.delta(s_loop)
    _, N = sec.point(s_loop)
    for k in range(len(d)):
        w = 1.0 - smoothstep01(d[k] / D)
        if w <= 0:
            continue
        X[k] += (delta * w)[:, None] * N
    return D


def quad_quality(X):
    """Cell areas, interior angles and aspect ratios of the ring quads."""
    a = X[:-1, :]
    b = np.roll(X[:-1], -1, axis=1)
    c = np.roll(X[1:], -1, axis=1)
    dd = X[1:]
    v = np.stack([a, dd, c, b], axis=2)
    area = 0.5 * np.sum(v[..., 0] * np.roll(v[..., 1], -1, 2) - np.roll(v[..., 0], -1, 2) * v[..., 1], axis=2)
    e1 = np.roll(v, -1, 2) - v
    e0 = v - np.roll(v, 1, 2)
    cosang = np.sum(-e0 * e1, -1) / (np.linalg.norm(e0, axis=-1) * np.linalg.norm(e1, axis=-1))
    ang = np.degrees(np.arccos(np.clip(cosang, -1, 1)))
    L = np.linalg.norm(e1, axis=-1)
    return area, ang, L.max(2) / L.min(2)


# --------------------------------------------------------------------------- outer region (gmsh)
def outer_region(ring_edge, p, alpha_deg, r_ff, verbose=False):
    """Quad-dominant mesh between the ring edge (closed polyline, CCW, nodes fixed) and a
    circle of radius r_ff about the origin (Stage 1 code)."""
    import gmsh
    c = C_REF
    gmsh.initialize(["-noenv"])
    gmsh.option.setNumber("General.Terminal", 1 if verbose else 0)
    gmsh.option.setNumber("General.NumThreads", 4)
    gmsh.model.add("outer")
    geo = gmsh.model.geo
    M = ring_edge.shape[0]
    pt = [geo.addPoint(x, y, 0.0) for x, y in ring_edge]
    ln = [geo.addLine(pt[j], pt[(j + 1) % M]) for j in range(M)]
    loop_in = geo.addCurveLoop(ln)
    pc = geo.addPoint(0, 0, 0)
    q = [geo.addPoint(r_ff * math.cos(t), r_ff * math.sin(t), 0) for t in (0, 0.5 * math.pi, math.pi, 1.5 * math.pi)]
    arcs = [geo.addCircleArc(q[j], pc, q[(j + 1) % 4]) for j in range(4)]
    loop_out = geo.addCurveLoop(arcs)
    surf = geo.addPlaneSurface([loop_out, loop_in])
    geo.synchronize()
    for l in ln:
        gmsh.model.mesh.setTransfiniteCurve(l, 2)
    n_arc = max(8, int(round(0.5 * math.pi * r_ff / p["s_far"])))
    for a in arcs:
        gmsh.model.mesh.setTransfiniteCurve(a, n_arc + 1)
    edge = np.linalg.norm(np.roll(ring_edge, -1, 0) - ring_edge, axis=1)
    s_ring = float(np.median(edge))
    fd = gmsh.model.mesh.field
    f_dist = fd.add("Distance")
    fd.setNumbers(f_dist, "PointsList", pt)
    ca, sa = math.cos(math.radians(alpha_deg)), math.sin(math.radians(alpha_deg))
    xr = f"(x*({ca:.12g})+y*({sa:.12g}))"
    yr = f"abs(y*({ca:.12g})-x*({sa:.12g}))"
    g = p["g_out"]
    F = f"F{f_dist}"
    near = (f"max(min({s_ring:.6g}+{g}*{F},{p['s_near']:.6g}),"
            f"{p['s_near']:.6g}+{g}*({F}-{p['d_near']:.6g}))")

    def band(x0, x1, w, s):
        dx = f"max(max({xr}-{x1 * c:.6g},{x0 * c:.6g}-{xr}),0)"
        dy = f"max({yr}-{w * c:.6g},0)"
        return f"({s:.6g}+{g}*sqrt({dx}*{dx}+{dy}*{dy}))"

    w1 = band(WAKE["x_up"], WAKE["x1"], WAKE["w1"], p["s_wake"])
    w2 = band(WAKE["x_up"], WAKE["x2"], WAKE["w2"], p["s_wake2"])
    expr = f"min(min(min({near},{w1}),{w2}),{p['s_far']:.6g})"
    f_all = fd.add("MathEval")
    fd.setString(f_all, "F", expr)
    fd.setAsBackgroundMesh(f_all)
    for k, v in {"Mesh.MeshSizeExtendFromBoundary": 0, "Mesh.MeshSizeFromPoints": 0,
                 "Mesh.MeshSizeFromCurvature": 0, "Mesh.Algorithm": 8,
                 "Mesh.RecombineAll": 1, "Mesh.RecombinationAlgorithm": 1,
                 "Mesh.Smoothing": 10}.items():
        gmsh.option.setNumber(k, v)
    gmsh.model.mesh.generate(2)
    tags, xyz, _ = gmsh.model.mesh.getNodes()
    xyz = xyz.reshape(-1, 3)[:, :2]
    idx = {int(t): i for i, t in enumerate(tags)}
    cells = []
    types, _, conn = gmsh.model.mesh.getElements(2, surf)
    for et, cn in zip(types, conn):
        nv = {2: 3, 3: 4}[int(et)]
        a = np.vectorize(idx.get)(cn.reshape(-1, nv).astype(np.int64))
        cells.extend(list(a))
    gmsh.finalize()
    tree = cKDTree(xyz)
    dist, ring_map = tree.query(ring_edge)
    if dist.max() > 1e-12:
        raise RuntimeError(f"ring edge nodes not found in gmsh mesh (max miss {dist.max():.3e} m)")
    return xyz, cells, ring_map, s_ring


# --------------------------------------------------------------------------- assembly
def assemble(X, outer_xyz, outer_cells, ring_map):
    """2D nodes and cells (CCW index arrays) of the whole mesh (Stage 1 code)."""
    K1, N = X.shape[0], X.shape[1]
    ring_nodes = X.reshape(-1, 2)
    n_ring = ring_nodes.shape[0]
    is_edge = np.zeros(outer_xyz.shape[0], bool)
    is_edge[ring_map] = True
    new = np.full(outer_xyz.shape[0], -1, np.int64)
    new[ring_map] = (K1 - 1) * N + np.arange(N)
    rest = np.where(~is_edge)[0]
    new[rest] = n_ring + np.arange(rest.size)
    nodes = np.vstack([ring_nodes, outer_xyz[rest]])
    cells = []
    i = np.arange(N)
    ip = (i + 1) % N
    for k in range(K1 - 1):
        cells.extend(np.stack([k * N + i, (k + 1) * N + i, (k + 1) * N + ip, k * N + ip], 1))
    for cc in outer_cells:
        cells.append(new[np.asarray(cc)])
    used = np.zeros(nodes.shape[0], bool)
    for cc in cells:
        used[cc] = True
    remap = np.cumsum(used) - 1
    nodes = nodes[used]
    out = []
    for cc in cells:
        cc = remap[np.asarray(cc)]
        P = nodes[cc]
        a = 0.5 * np.sum(P[:, 0] * np.roll(P[:, 1], -1) - np.roll(P[:, 0], -1) * P[:, 1])
        if a == 0:
            raise RuntimeError("degenerate 2D cell")
        out.append(cc if a > 0 else cc[::-1])
    if not used[: K1 * N].all():
        raise RuntimeError("ring node unused")
    return nodes, out


# --------------------------------------------------------------------------- polyMesh writer
def _header(cls, obj, note=None):
    s = ("FoamFile\n{\n    version     2.0;\n    format      ascii;\n"
         f"    class       {cls};\n")
    if note:
        s += f'    note        "{note}";\n'
    s += f"    location    \"constant/polyMesh\";\n    object      {obj};\n}}\n\n"
    return "/*--- written by cfd/stage2/mesh/make_mesh.py ---*/\n" + s


def _seg_dist(P, a, b):
    ab = b - a
    t = np.clip(((P - a) @ ab) / (ab @ ab), 0, 1)
    return np.linalg.norm(P - (a + t[:, None] * ab), axis=1)


def write_polymesh(case, nodes, cells, r_wall_max, end_segments, dz=DZ):
    """Extrude the 2D mesh by one cell (z = 0 .. dz) and write constant/polyMesh. Wall edges
    whose midpoint lies on an end-face segment (within 1e-9 m) go to bladeEnds, the other wall
    edges to blade."""
    N = nodes.shape[0]
    nc = len(cells)
    ea, eb, ec = [], [], []
    for ci, cc in enumerate(cells):
        cc = np.asarray(cc)
        ea.append(cc)
        eb.append(np.roll(cc, -1))
        ec.append(np.full(cc.size, ci))
    ea, eb, ec = np.concatenate(ea), np.concatenate(eb), np.concatenate(ec)
    key = np.minimum(ea, eb) * (N + 1) + np.maximum(ea, eb)
    order = np.argsort(key, kind="stable")
    ks = key[order]
    first = np.r_[True, ks[1:] != ks[:-1]]
    grp = np.cumsum(first) - 1
    counts = np.bincount(grp)
    if counts.max() > 2:
        raise RuntimeError("non-manifold edge in 2D mesh")
    pair_start = np.where(first)[0]
    internal = counts[grp[pair_start]] == 2
    i1 = order[pair_start[internal]]
    i2 = order[pair_start[internal] + 1]
    c1, c2 = ec[i1], ec[i2]
    own_is1 = c1 < c2
    io = np.where(own_is1, i1, i2)
    own = np.minimum(c1, c2)
    nei = np.maximum(c1, c2)
    s = np.lexsort((nei, own))
    io, own, nei = io[s], own[s], nei[s]
    int_faces = np.stack([ea[io], eb[io], eb[io] + N, ea[io] + N], 1)
    ib = order[pair_start[~internal]]
    mid = 0.5 * (nodes[ea[ib]] + nodes[eb[ib]])
    rad = np.linalg.norm(mid, axis=1)
    is_wall = rad < r_wall_max
    on_end = np.zeros(ib.size, bool)
    for a, b in end_segments:
        on_end |= _seg_dist(mid, np.asarray(a), np.asarray(b)) < 1e-9
    on_end &= is_wall
    patches = []
    for name, m in (("blade", is_wall & ~on_end), ("bladeEnds", on_end), ("farfield", ~is_wall)):
        e = ib[m]
        e = e[np.argsort(ec[e], kind="stable")]
        patches.append((name, np.stack([ea[e], eb[e], eb[e] + N, ea[e] + N], 1), ec[e]))
    fb_faces, fb_own = [], []
    for ci, cc in enumerate(cells):
        fb_faces.append(np.asarray(cc)[::-1])
        fb_own.append(ci)
    for ci, cc in enumerate(cells):
        fb_faces.append(np.asarray(cc) + N)
        fb_own.append(ci)
    pm = Path(case) / "constant" / "polyMesh"
    if pm.exists():
        shutil.rmtree(pm)
    pm.mkdir(parents=True)
    pts = np.vstack([np.c_[nodes, np.zeros(N)], np.c_[nodes, np.full(N, dz)]])
    n_int = int_faces.shape[0]
    n_faces = n_int + sum(q[1].shape[0] for q in patches) + len(fb_faces)
    note = f"nPoints:{2 * N} nCells:{nc} nFaces:{n_faces} nInternalFaces:{n_int}"
    with open(pm / "points", "w") as f:
        f.write(_header("vectorField", "points"))
        f.write(f"{pts.shape[0]}\n(\n")
        f.write("\n".join(f"({x:.12g} {y:.12g} {z:.12g})" for x, y, z in pts))
        f.write("\n)\n")
    with open(pm / "faces", "w") as f:
        f.write(_header("faceList", "faces"))
        f.write(f"{n_faces}\n(\n")
        lines = [f"4({a} {b} {c_} {d})" for a, b, c_, d in int_faces]
        for _, F, _ in patches:
            lines += [f"4({a} {b} {c_} {d})" for a, b, c_, d in F]
        lines += [f"{len(F)}(" + " ".join(map(str, F)) + ")" for F in fb_faces]
        f.write("\n".join(lines))
        f.write("\n)\n")
    owner = np.concatenate([own] + [q[2] for q in patches] + [np.array(fb_own)])
    with open(pm / "owner", "w") as f:
        f.write(_header("labelList", "owner", note))
        f.write(f"{owner.size}\n(\n" + "\n".join(map(str, owner)) + "\n)\n")
    with open(pm / "neighbour", "w") as f:
        f.write(_header("labelList", "neighbour", note))
        f.write(f"{nei.size}\n(\n" + "\n".join(map(str, nei)) + "\n)\n")
    start = n_int
    with open(pm / "boundary", "w") as f:
        f.write(_header("polyBoundaryMesh", "boundary"))
        f.write("4\n(\n")
        for name, F, _ in patches:
            typ = "patch" if name == "farfield" else "wall"
            grp = "\n        inGroups        2(wall bladeWall);" if typ == "wall" else ""
            f.write(f"    {name}\n    {{\n        type            {typ};{grp}\n"
                    f"        nFaces          {F.shape[0]};\n        startFace       {start};\n    }}\n")
            start += F.shape[0]
        f.write(f"    frontAndBack\n    {{\n        type            empty;\n        inGroups        1(empty);\n"
                f"        nFaces          {len(fb_faces)};\n        startFace       {start};\n    }}\n)\n")
    return dict(n_points=int(2 * N), n_cells=int(nc), n_faces=int(n_faces), n_internal_faces=int(n_int),
                n_wall_faces=int(patches[0][1].shape[0] + patches[1][1].shape[0]),
                n_blade_faces=int(patches[0][1].shape[0]), n_bladeEnds_faces=int(patches[1][1].shape[0]),
                n_farfield_faces=int(patches[2][1].shape[0]))


# --------------------------------------------------------------------------- checks and plot
def csv_check(sec, wall_xy):
    """Max distance of wall nodes from the section_v1.csv outline (CAD frame polyline)."""
    P = np.loadtxt(SECTION_CSV, delimiter=",", skiprows=1)
    cad = wall_xy @ sec.R_cad2body + sec.centroid_cad
    Q = np.vstack([P, P[:1]])
    a, b = Q[:-1], Q[1:]
    ab = b - a
    t = np.clip(np.einsum("nij,ij->ni", cad[:, None, :] - a[None], ab) / np.sum(ab * ab, 1), 0, 1)
    d = np.linalg.norm(cad[:, None, :] - (a[None] + t[..., None] * ab[None]), axis=2).min(1)
    return float(d.max())


def plot_mesh(path, nodes, cells, sec, alpha_deg, title, tex_view=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    polys = [nodes[c] * 1e3 for c in cells]
    c = sec.P_corner * 1e3
    views = [((0, 0), 1500, "far field (mm)"), ((60, 0), 160, "near body and wake"),
             ((0, 0), 32, "section"), (tuple(c[0:2].mean(0)), 1.6, "tip B (end face, square corners)")]
    if tex_view is not None:
        views += [(tuple(tex_view * 1e3), 0.6, "texture, outer face (1.2 mm window)"),
                  (tuple(tex_view * 1e3), 0.12, "texture, near wall (0.24 mm window)")]
    nr = 2 if len(views) == 4 else 3
    fig, axs = plt.subplots(nr, 2, figsize=(13, 6.5 * nr))
    ca, sa = math.cos(math.radians(alpha_deg)), math.sin(math.radians(alpha_deg))
    cen = np.array([P.mean(0) for P in polys])
    for ax, (cc, w, t) in zip(axs.flat, views):
        if t == "near body and wake":
            cc = (cc[0] * ca, cc[0] * sa)
        m = (np.abs(cen[:, 0] - cc[0]) < 1.2 * w) & (np.abs(cen[:, 1] - cc[1]) < 1.2 * w)
        sel = [polys[i] for i in np.where(m)[0]]
        ax.add_collection(PolyCollection(sel, facecolors="none", edgecolors="k", linewidths=0.25))
        ax.set_xlim(cc[0] - w, cc[0] + w)
        ax.set_ylim(cc[1] - w, cc[1] + w)
        ax.set_aspect("equal")
        ax.set_title(t, fontsize=10)
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


# --------------------------------------------------------------------------- main
def build(level, alpha_deg, out, plot=None, verbose=False, U=None, tex_t=None, seed=1, nseg=TEX_NSEG):
    t0 = time.time()
    p = dict(LEVELS[level])
    sec = Section()
    extra = {}
    tex = None
    if level == "wf":
        if U is None:
            raise ValueError("--U is required for level wf")
        h0, u_tau, yp_fp = wf_first_cell(U)
        p["h0"] = h0
        extra["wall_function"] = dict(U_design=U, h0_m=h0, y_p_m=0.5 * h0, u_tau_flat_plate=u_tau,
                                      yplus_flat_plate=yp_fp, yplus_target=WF_YPLUS, ks_max_m=WF_KS_MAX,
                                      yp_over_ks_min=WF_YP_OVER_KS, h0_max_m=WF_H0_MAX, x_flat_plate_m=X_FP,
                                      ks_valid_max_m=0.5 * h0,
                                      note="nutkRoughWallFunction: keep Ks below y_p (first cell centre)")
    if level == "tex":
        if tex_t is None:
            raise ValueError("--tex is required for level tex (0 for the smooth reference)")
        tex = Texture(sec, tex_t, seed)
        D = TEX_BLEND[0] * tex.t + TEX_BLEND[1]
        ring_thk = max(p["ring_min"], D)
        sw, s0 = tex_wall_nodes(sec, p, tex, nseg)
        d = layer_distances(p, p["h0"], ring_thk)
    else:
        sw, s0 = wall_nodes(sec, p)
        d = layer_distances(p, p["h0"])
    X = ring_layers(sec, d, sw, s0)
    wall_smooth = X[0].copy()
    if tex is not None:
        D = apply_texture(X, d, sec, sw + s0, tex)
        extra["texture"] = dict(tex.stats(), nseg=nseg, wall_spacing_m=TEX_DL / nseg, fade_out_D_m=D,
                                fade_rule="w(d) = 1 - smoothstep(d/D), D = 2.5 t + 0.1 mm",
                                max_relative_height_change=float(1.5 * tex.t / D))
    area, ang, ar = quad_quality(X)
    if (area <= 0).any():
        raise RuntimeError(f"ring has {(area <= 0).sum()} non-positive cells")
    r_ff = R_FF_CHORDS * C_REF
    oxy, ocells, rmap, s_ring = outer_region(X[-1], p, alpha_deg, r_ff, verbose)
    nodes, cells = assemble(X, oxy, ocells, rmap)
    info = write_polymesh(out, nodes, cells, r_wall_max=0.1 * r_ff, end_segments=sec.end_segments())
    n_tri = sum(1 for c in ocells if len(c) == 3)
    edge = np.linalg.norm(np.roll(X[-1], -1, 0) - X[-1], axis=1)
    info.update(
        level=level, alpha_deg_wake=alpha_deg, params={k: v for k, v in p.items()}, lambda_fan=LAMBDA_FAN,
        r_farfield_m=r_ff, c_ref_m=C_REF, dz_m=DZ, wake_chords=WAKE, h0_m=float(d[1]),
        ring=dict(n_layers=int(len(d) - 1), n_wall_nodes=int(X.shape[1]), thickness_m=float(d[-1]),
                  first_cell_m=float(d[1]), last_layer_m=float(d[-1] - d[-2]),
                  edge_spacing_m=dict(min=float(edge.min()), median=float(np.median(edge)), max=float(edge.max())),
                  quad_angle_deg=[float(ang.min()), float(ang.max())], aspect_max=float(ar.max()),
                  min_cell_area_m2=float(area.min())),
        outer=dict(n_cells=len(ocells), n_tri=int(n_tri), n_quad=int(len(ocells) - n_tri)),
        wall_vs_csv_max_m=csv_check(sec, wall_smooth),
        frame=dict(centroid_cad_m=sec.centroid_cad.tolist(), body_x_dir_deg_in_cad=sec.normal_dir_deg,
                   body_y_dir_deg_in_cad=sec.chord_dir_deg, wall_m=sec.wall, area_m2=float(sec.area),
                   corners_body_m=dict(zip(["B_outer", "B_inner", "A_inner", "A_outer"], sec.P_corner.tolist())),
                   note="x_body = R (x_cad - centroid); R rows = (body x, body y) unit vectors in CAD"),
        patches=dict(blade="outer + inner surface (painted, fuzzy skin)", bladeEnds="two square end faces (not painted)"),
        generator="cfd/stage2/mesh/make_mesh.py",
        **extra,
    )
    info["seconds"] = round(time.time() - t0, 1)
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "mesh_info.json").write_text(json.dumps(info, indent=1))
    if plot:
        tv = None
        if tex is not None:
            tv, _ = sec.point(np.array([0.5 * sec.L_o]))
            tv = tv[0]
        if level == "wf":
            lab = f"wall functions, h0 {d[1] * 1e3:.3f} mm (U {U:g} m/s)"
        elif level == "tex":
            lab = f"texture t {tex_t * 1e3:.3f} mm seed {seed}, h0 {d[1] * 1e6:.1f} um"
        else:
            lab = f"h0 {d[1] * 1e6:.1f} um"
        plot_mesh(plot, nodes, cells, sec, alpha_deg,
                  f"{level}: {info['n_cells']} cells, ring {info['ring']['n_layers']} layers, {lab}, "
                  f"wake at alpha {alpha_deg:g} deg", tex_view=tv)
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--level", choices=LEVELS, default="wf")
    ap.add_argument("--alpha", type=float, default=0.0, help="free-stream angle (deg): orients the wake band")
    ap.add_argument("--U", type=float, help="case speed, m/s (level wf: sets h0)")
    ap.add_argument("--tex", type=float, help="level tex: fuzzy-skin amplitude t, m (0 = smooth reference)")
    ap.add_argument("--seed", type=int, default=1, help="level tex: random seed (default 1)")
    ap.add_argument("--nseg", type=int, default=TEX_NSEG, help="level tex: wall cells per 0.2 mm (default %(default)d)")
    ap.add_argument("--out", help="case directory to write constant/polyMesh into")
    ap.add_argument("--plot", help="PNG of the mesh")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    if not a.out:
        ap.error("--out is required")
    info = build(a.level, a.alpha, a.out, a.plot, a.verbose, U=a.U, tex_t=a.tex, seed=a.seed, nseg=a.nseg)
    keys = ("level", "n_cells", "n_points", "h0_m", "ring", "outer", "n_blade_faces", "n_bladeEnds_faces",
            "wall_vs_csv_max_m", "wall_function", "texture", "seconds")
    print(json.dumps({k: info[k] for k in keys if k in info}, indent=1))


if __name__ == "__main__":
    main()
