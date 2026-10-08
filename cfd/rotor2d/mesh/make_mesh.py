#!/usr/bin/env python3
"""2D rotor mesh (Stage 3, cfd/PLAN.md 3a/3b): three v1 blades in a rotating disk,
joined to a stationary box by cyclicAMI. One cell thick, front/back 'empty'.

Mesher: gmsh (cfd/.venv) for the unstructured fill, plus a structured near-wall
ring generated here, then a polyMesh written directly (no gmshToFoam). Why not
snappyHexMesh: the wall is 1.854 mm thick with square ends, and the near-wall
layers must be exact (first-cell height sets y+ for the wall functions) on both
faces and round the four corners of every blade; snappy's layer addition on a
one-cell slab collapses layers at such thin, sharp edges, while the offset-curve
ring below gives the exact first-cell height everywhere by construction (the
approach of cfd/section2d/mesh/make_mesh.py, re-implemented here for three blades,
the CAD frame and wall-function spacing). gmsh then needs only fixed boundary
nodes, which also makes the two sides of the AMI circle conformal at theta = 0.

Regions and patches
  rotor   (cellZone 'rotor'): disk r < r_ami minus the blades. Patches blade1,
          blade2, blade3 (wall, group 'blades') and AMI1 (cyclicAMI).
  stator  box minus the disk. Patches AMI2 (cyclicAMI), inlet (x = x_in),
          outlet (x = x_out), sides (y = y_lo, y_hi; 'patch' for the open domain,
          'wall' when --walls gives tunnel walls), frontAndBack (empty).
The rotor and stator are separate regions (duplicated nodes on the circle);
checkMesh reports 2 regions, which is expected for an AMI mesh.

Wall treatment
  wf     first cell height h0 = 2 y+ nu / u_tau with u_tau from a flat-plate
         estimate at the free-stream speed U (Schlichting cf = 0.0592 Re_x^-0.2 at
         x = c/2): --yplus 40 (target 30-60 at the cell centre) -> h0 ~ 0.87 mm at
         23 m/s. A few layers (growth r_bl), tangential spacing ~ h0.
  lowRe  y+ ~ 1 for a low-Re wall / kOmegaSSTLM: h0 from --yplus (default 0.8)
         with u_tau at 1.5 U; layers grow to the tangential spacing.

Frames: see ../rotor_geometry.py (model frame: shaft at origin, wind +x, z = CAD z).
The blades are placed at rotor azimuth --theta (static cases: the frozen azimuth;
rotating cases: 0).

Usage (venv python, which has gmsh):
  cfd/.venv/bin/python cfd/rotor2d/mesh/make_mesh.py --hyp A --level medium --U 23 --out <dir> [--plot m.png]
  ... --theta 30                      static case at azimuth 30 deg
  ... --wall lowRe                    low-Re variant
  ... --walls -0.4,0.4 --x-in -1.2 --x-out 3.0    tunnel side walls (m, model y), for blockage runs
Writes <dir>/constant/polyMesh/{points,faces,owner,neighbour,boundary,cellZones} and <dir>/mesh_info.json.
"""
import argparse
import json
import math
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
ROTOR2D = HERE.parent
sys.path.insert(0, str(ROTOR2D))
import rotor_geometry as rg  # noqa: E402

NU = 1.516e-5            # m^2/s (cfd/templates/transportProperties)
DZ = 0.01                # m, slab thickness (forces are divided by it to give per-unit-span values)
LAMBDA_FAN = 2.0         # corner fan blend width, in units of the layer distance (as section2d)
C_TIP = 0.04461          # m, tip-to-tip chord (end-face midpoints), for sizing only

# Lengths in metres. ds_*: wall-tangential spacing; s_*: fill sizes; g_*: size growth per unit
# distance (0.1 = 10 %); n_layers: ring layers (wf); d_near: distance over which s_near holds.
LEVELS = {
    "coarse": dict(r_bl=1.20, n_layers=3, ds_max=1.0e-3, ds_corner=0.30e-3, g_t=1.20,
                   s_near=1.4e-3, d_near=4e-3, s_rot=3.2e-3, s_ami=3.0e-3, g_in=0.12,
                   s_wake1=5.0e-3, s_wake2=10e-3, g_out=0.12, s_far=0.25),
    "medium": dict(r_bl=1.15, n_layers=4, ds_max=0.70e-3, ds_corner=0.20e-3, g_t=1.15,
                   s_near=1.0e-3, d_near=5e-3, s_rot=2.3e-3, s_ami=2.2e-3, g_in=0.10,
                   s_wake1=3.5e-3, s_wake2=7e-3, g_out=0.10, s_far=0.20),
    "fine":   dict(r_bl=1.12, n_layers=5, ds_max=0.50e-3, ds_corner=0.14e-3, g_t=1.12,
                   s_near=0.7e-3, d_near=6e-3, s_rot=1.6e-3, s_ami=1.6e-3, g_in=0.08,
                   s_wake1=2.5e-3, s_wake2=5e-3, g_out=0.08, s_far=0.15),
}
LOWRE = dict(r_bl=1.15, ds_max=0.30e-3, ds_corner=0.06e-3, g_t=1.12)   # replaces the wall part of a level
H0_MAX = 1.5e-3          # m, wall-function first cell at most 1.5 mm (U < ~19 m/s gets y+ < 40)
T_RING_MAX = 5.0e-3      # m, wall-function ring at most 5 mm thick (curl inner radius of curvature 9.8 mm)
D_REF = 0.25             # m, rotor diameter used for the domain (2 r_max of hypothesis B = 0.2516 m)
DOMAIN = dict(x_in=-10 * D_REF, x_out=25 * D_REF, y_half=15 * D_REF)   # open domain
WAKE = dict(x_up=-0.6, x1=3.0, w1=0.8, x2=8.0, w2=1.3)                # in rotor diameters 2 r_max


# --------------------------------------------------------------------------- wall spacing
def u_tau_flat_plate(U, x=0.5 * C_TIP):
    Re = max(U, 1e-6) * x / NU
    cf = 0.0592 * Re ** -0.2
    return U * math.sqrt(0.5 * cf)


def first_cell(U, yplus, wall):
    u_ref = U * (1.5 if wall == "lowRe" else 1.0)
    return 2.0 * yplus * NU / u_tau_flat_plate(u_ref)


def distribute(L, s0, s1, g, smax):
    """Node positions on [0, L], spacing s0 at 0 and s1 at L, growing by about g per cell, capped at smax."""
    x = np.linspace(0, L, 20001)
    sp = np.minimum(np.minimum(smax, s0 + (g - 1) * x), s1 + (g - 1) * (L - x))
    I = np.r_[0, np.cumsum(0.5 * (1 / sp[1:] + 1 / sp[:-1]) * np.diff(x))]
    n = max(2, int(round(I[-1])))
    return np.interp(np.linspace(0, I[-1], n + 1), I, x)


def wall_nodes(sec, p):
    dc, g, dmax = p["ds_corner"], p["g_t"], p["ds_max"]
    e_max = min(dmax, 0.4e-3)                          # end faces (1.854 mm): at least ~5 cells
    pieces = [distribute(sec.L_o, dc, dc, g, dmax),
              sec.s_corner[0] + distribute(sec.L_eB, dc, dc, g, e_max),
              sec.s_corner[1] + distribute(sec.L_i, dc, dc, g, dmax),
              sec.s_corner[2] + distribute(sec.L_eA, dc, dc, g, e_max)]
    s = np.concatenate([q[:-1] for q in pieces])
    s0 = 0.5 * sec.L_o
    s_shift = np.mod(s - s0, sec.L)
    return np.sort(s_shift), s0


def smoothstep(x):
    t = np.clip(0.5 * (x + 1.0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def ring_layers(sec, p, h0):
    """Structured near-wall layers in the CAD frame: X[k, i, 2] (k = 0 is the wall), d[k].
    Layer k is the offset curve of the section at distance d_k, rounded at the four
    corners; wall nodes near a corner fan out over the corner arc (section2d's scheme)."""
    sw, s0 = wall_nodes(sec, p)
    sc = np.mod(sec.s_corner - s0, sec.L)
    oc = np.argsort(sc)
    sc, Pc = sc[oc], sec.P_corner[oc]
    Nb, _ = sec.corner_normals()
    Nb = Nb[oc]
    r = p["r_bl"]
    if p.get("n_layers"):
        K = int(p["n_layers"])
    else:
        K = int(math.ceil(math.log(p["ds_max"] / h0) / math.log(r))) + 1
    d = np.r_[0.0, h0 * (r ** np.arange(1, K + 1) - 1) / (r - 1)]
    while K > 1 and d[K] > p.get("t_ring_max", np.inf):      # keep the ring clear of the curl's centre
        K -= 1
        d = d[:K + 1]
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
            P[m] = Pc[c] + dk * np.stack([np.cos(phi) * Nb[c][0] - np.sin(phi) * Nb[c][1],
                                          np.sin(phi) * Nb[c][0] + np.cos(phi) * Nb[c][1]], -1)
            on_arc |= m
        m = ~on_arc
        n_before = (sstar[m, None] > arc_end[None, :]).sum(1)
        Pw, Nw = sec.point(sstar[m] - q * dk * n_before + s0)
        P[m] = Pw + dk * Nw
        X[k] = P
    return X, d


def quad_quality(X):
    a, b = X[:-1], np.roll(X[:-1], -1, axis=1)
    c, dd = np.roll(X[1:], -1, axis=1), X[1:]
    v = np.stack([a, dd, c, b], axis=2)
    area = 0.5 * np.sum(v[..., 0] * np.roll(v[..., 1], -1, 2) - np.roll(v[..., 0], -1, 2) * v[..., 1], axis=2)
    e1 = np.roll(v, -1, 2) - v
    e0 = v - np.roll(v, 1, 2)
    cosang = np.sum(-e0 * e1, -1) / (np.linalg.norm(e0, axis=-1) * np.linalg.norm(e1, axis=-1))
    ang = np.degrees(np.arccos(np.clip(cosang, -1, 1)))
    L = np.linalg.norm(e1, axis=-1)
    return area, ang, L.max(2) / L.min(2)


# --------------------------------------------------------------------------- gmsh fill
def gmsh_fill(outer, holes, size_expr, verbose=False, threads=2):
    """Quad-dominant mesh of the polygon `outer` (closed polyline, CCW, nodes fixed; or
    a dict box=(x0, x1, y0, y1)) minus the closed polylines `holes` (nodes fixed).
    size_expr(F_tag_or_None) -> MathEval string. Returns nodes[n, 2], cells list."""
    import gmsh
    gmsh.initialize(["-noenv"])
    try:
        gmsh.option.setNumber("General.Terminal", 1 if verbose else 0)
        gmsh.option.setNumber("General.NumThreads", threads)
        gmsh.model.add("fill")
        geo = gmsh.model.geo
        fixed_lines, fixed_pts, loops = [], [], []

        def poly(P):
            pt = [geo.addPoint(x, y, 0.0) for x, y in P]
            ln = [geo.addLine(pt[j], pt[(j + 1) % len(pt)]) for j in range(len(pt))]
            fixed_lines.extend(ln)
            fixed_pts.extend(pt)
            return geo.addCurveLoop(ln)

        if isinstance(outer, dict):
            x0, x1, y0, y1 = outer["box"]
            c = [geo.addPoint(x0, y0, 0), geo.addPoint(x1, y0, 0), geo.addPoint(x1, y1, 0), geo.addPoint(x0, y1, 0)]
            ln = [geo.addLine(c[j], c[(j + 1) % 4]) for j in range(4)]
            loops.append(geo.addCurveLoop(ln))
        else:
            loops.append(poly(outer))
        hole_pts = []
        for H in holes:
            n0 = len(fixed_pts)
            loops.append(poly(H))
            hole_pts.extend(fixed_pts[n0:])
        surf = geo.addPlaneSurface(loops)
        geo.synchronize()
        for l in fixed_lines:
            gmsh.model.mesh.setTransfiniteCurve(l, 2)
        fd = gmsh.model.mesh.field
        F = None
        if hole_pts:
            F = fd.add("Distance")
            fd.setNumbers(F, "PointsList", hole_pts)
        f_all = fd.add("MathEval")
        fd.setString(f_all, "F", size_expr(F))
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
            cells.extend(list(np.vectorize(idx.get)(cn.reshape(-1, nv).astype(np.int64))))
    finally:
        gmsh.finalize()
    used = np.zeros(len(xyz), bool)
    for c in cells:
        used[c] = True
    remap = np.cumsum(used) - 1
    return xyz[used], [remap[np.asarray(c)] for c in cells]


def mathex_num(v):
    return f"({v:.10g})"


# --------------------------------------------------------------------------- build
def build(hyp="A", level="medium", U=23.0, wall="wf", yplus=None, theta=0.0, out=None, plot=None,
          ami_margin=0.022, walls=None, x_in=None, x_out=None, beta=None, sense="auto", verbose=False):
    t0 = time.time()
    p = dict(LEVELS[level])
    if wall == "lowRe":
        p.update(LOWRE)
        p["n_layers"] = None
        p["s_near"] = min(p["s_near"], 0.6e-3)
    if yplus is None:
        yplus = 40.0 if wall == "wf" else 0.8
    h0 = first_cell(U, yplus, wall)
    yplus_eff = yplus
    if wall == "wf":
        p["t_ring_max"] = T_RING_MAX
        if h0 > H0_MAX:                                     # low speeds: cap (Spalding wall function, any y+)
            yplus_eff = yplus * H0_MAX / h0
            h0 = H0_MAX
    sec = rg.Section()
    pose = rg.get_pose(hyp, sec, beta_deg=beta, sense=sense)
    X, d = ring_layers(sec, p, h0)
    area, ang, ar = quad_quality(X)
    if (area <= 0).any():
        raise RuntimeError(f"ring has {int((area <= 0).sum())} non-positive cells (h0 {h0:.3g} m, {len(d) - 1} layers)")
    K1, Nw = X.shape[0], X.shape[1]
    r_ami = pose["r_max_m"] + ami_margin
    D = 2 * pose["r_max_m"]
    # ---- blades in the model frame
    rings = [np.stack([rg.to_model(pose, X[k], theta, j) for k in range(K1)]) for j in (1, 2, 3)]
    rmin_ring = min(np.linalg.norm(R[-1], axis=1).min() for R in rings)
    rmax_ring = max(np.linalg.norm(R[-1], axis=1).max() for R in rings)
    if rmax_ring > r_ami - 2 * p["s_ami"]:
        raise RuntimeError(f"ring edge reaches r = {rmax_ring:.4f} m, too close to the AMI at {r_ami:.4f} m")
    # ---- AMI circle (CCW), the same nodes on both sides
    n_ami = int(math.ceil(2 * math.pi * r_ami / p["s_ami"] / 8.0)) * 8
    ph = 2 * math.pi * np.arange(n_ami) / n_ami
    circle = r_ami * np.c_[np.cos(ph), np.sin(ph)]
    # ---- rotor fill
    edges = [R[-1] for R in rings]
    s_ring = float(np.median(np.concatenate([np.linalg.norm(np.roll(e, -1, 0) - e, axis=1) for e in edges])))
    g, gi = p["g_in"], p["g_in"]

    def rotor_size(F):
        Fs = f"F{F}"
        near = (f"max(min({s_ring:.6g}+{g}*{Fs},{p['s_near']:.6g}),"
                f"{p['s_near']:.6g}+{g}*({Fs}-{p['d_near']:.6g}))")
        rr = "sqrt(x*x+y*y)"
        ami = f"{p['s_ami']:.6g}+{gi}*max({r_ami:.10g}-{rr},0)"
        return f"min(min({near},{p['s_rot']:.6g}),{ami})"

    rxy, rcells = gmsh_fill(circle, edges, rotor_size, verbose)
    # ---- stator fill
    if walls:
        y_lo, y_hi = walls
    else:
        y_lo, y_hi = -DOMAIN["y_half"], DOMAIN["y_half"]
    xi = DOMAIN["x_in"] if x_in is None else x_in
    xo = DOMAIN["x_out"] if x_out is None else x_out
    go = p["g_out"]

    def stator_size(F):
        rr = "sqrt(x*x+y*y)"

        def band(x0, x1, w, s):
            dx = f"max(max(x-{x1 * D:.6g},{x0 * D:.6g}-x),0)"
            dy = f"max(abs(y)-{w * D:.6g},0)"
            return f"({s:.6g}+{go}*sqrt({dx}*{dx}+{dy}*{dy}))"
        ami = f"({p['s_ami']:.6g}+{go}*max({rr}-{r_ami:.10g},0))"
        w1 = band(WAKE["x_up"], WAKE["x1"], WAKE["w1"], p["s_wake1"])
        w2 = band(WAKE["x_up"], WAKE["x2"], WAKE["w2"], p["s_wake2"])
        return f"min(min(min({ami},{w1}),{w2}),{p['s_far']:.6g})"

    sxy, scells = gmsh_fill({"box": (xi, xo, y_lo, y_hi)}, [circle[::-1]], stator_size, verbose)
    # ---- assemble: ring nodes, rotor fill nodes (minus ring edges), stator nodes
    ring_nodes = np.concatenate([R.reshape(-1, 2) for R in rings])            # blade j layer k node i
    ring_off = [j * K1 * Nw for j in range(3)]
    tree = cKDTree(rxy)
    edge_all = np.concatenate(edges)
    dist, hit = tree.query(edge_all)
    if dist.max() > 1e-12:
        raise RuntimeError(f"ring-edge nodes missing from the rotor fill (max miss {dist.max():.3e} m)")
    new = np.full(len(rxy), -1, np.int64)
    edge_ids = np.concatenate([ring_off[j] + (K1 - 1) * Nw + np.arange(Nw) for j in range(3)])
    new[hit] = edge_ids
    rest = np.flatnonzero(new < 0)
    n_ring = len(ring_nodes)
    new[rest] = n_ring + np.arange(rest.size)
    rot_nodes = np.vstack([ring_nodes, rxy[rest]])
    cells = []
    i = np.arange(Nw)
    ip = (i + 1) % Nw
    for j in range(3):
        o = ring_off[j]
        for k in range(K1 - 1):
            cells.extend(np.stack([o + k * Nw + i, o + (k + 1) * Nw + i, o + (k + 1) * Nw + ip, o + k * Nw + ip], 1))
    for c in rcells:
        cells.append(new[c])
    n_rot_cells = len(cells)
    n_rot_nodes = len(rot_nodes)
    for c in scells:
        cells.append(np.asarray(c) + n_rot_nodes)
    nodes = np.vstack([rot_nodes, sxy])
    # orient CCW, check
    out_cells = []
    for c in cells:
        P = nodes[c]
        a = 0.5 * np.sum(P[:, 0] * np.roll(P[:, 1], -1) - np.roll(P[:, 0], -1) * P[:, 1])
        if a == 0:
            raise RuntimeError("degenerate 2D cell")
        out_cells.append(np.asarray(c) if a > 0 else np.asarray(c)[::-1])
    wall_sets = [(ring_off[j], ring_off[j] + Nw) for j in range(3)]
    geom = dict(r_ami=r_ami, x_in=xi, x_out=xo, y_lo=y_lo, y_hi=y_hi, n_rot_cells=n_rot_cells,
                n_rot_nodes=n_rot_nodes, wall_sets=wall_sets, side_type="wall" if walls else "patch")
    info = {}
    if out:
        info = write_polymesh(out, nodes, out_cells, geom)
    n_tri = sum(1 for c in out_cells if len(c) == 3)
    edge_len = np.linalg.norm(np.roll(X[-1], -1, 0) - X[-1], axis=1)
    info.update(
        hypothesis=hyp, level=level, wall=wall, U_design=U, yplus_target=yplus, yplus_flat_plate_estimate=yplus_eff,
        h0_m=h0, theta_deg=theta,
        params=p, dz_m=DZ, r_ami_m=r_ami, n_ami_faces=n_ami, ami_margin_m=ami_margin, D_rotor_m=D,
        domain=dict(x_in=xi, x_out=xo, y_lo=y_lo, y_hi=y_hi, sides=geom["side_type"], D_ref=D_REF),
        ring=dict(n_layers=int(len(d) - 1), n_wall_nodes=int(Nw), thickness_m=float(d[-1]), first_cell_m=float(d[1]),
                  last_layer_m=float(d[-1] - d[-2]), edge_spacing_m=[float(edge_len.min()), float(np.median(edge_len)),
                                                                     float(edge_len.max())],
                  quad_angle_deg=[float(ang.min()), float(ang.max())], aspect_max=float(ar.max()),
                  r_edge_m=[float(rmin_ring), float(rmax_ring)]),
        n_cells_rotor=int(n_rot_cells), n_cells_stator=int(len(out_cells) - n_rot_cells), n_tri=int(n_tri),
        pose=rg.summary_row(pose), pose_full=pose, seconds=round(time.time() - t0, 1),
    )
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / "mesh_info.json").write_text(json.dumps(info, indent=1))
    if plot:
        focus = rg.to_model(pose, sec.tipB, theta, 1)[0]
        plot_mesh(plot, nodes, out_cells, rings, info, focus)
    return info


# --------------------------------------------------------------------------- polyMesh writer
def _header(cls, obj, note=None):
    s = ("FoamFile\n{\n    version     2.0;\n    format      ascii;\n"
         f"    class       {cls};\n")
    if note:
        s += f'    note        "{note}";\n'
    s += f"    location    \"constant/polyMesh\";\n    object      {obj};\n}}\n\n"
    return "/*--- written by cfd/rotor2d/mesh/make_mesh.py ---*/\n" + s


def write_polymesh(case, nodes, cells, G, dz=DZ):
    N = nodes.shape[0]
    nc = len(cells)
    ea = np.concatenate([np.asarray(c) for c in cells])
    eb = np.concatenate([np.roll(np.asarray(c), -1) for c in cells])
    ec = np.concatenate([np.full(len(c), ci) for ci, c in enumerate(cells)])
    key = np.minimum(ea, eb) * (N + 1) + np.maximum(ea, eb)
    order = np.argsort(key, kind="stable")
    ks = key[order]
    first = np.r_[True, ks[1:] != ks[:-1]]
    grp = np.cumsum(first) - 1
    counts = np.bincount(grp)
    if counts.max() > 2:
        raise RuntimeError("non-manifold edge in the 2D mesh")
    ps = np.where(first)[0]
    internal = counts[grp[ps]] == 2
    i1, i2 = order[ps[internal]], order[ps[internal] + 1]
    c1, c2 = ec[i1], ec[i2]
    io = np.where(c1 < c2, i1, i2)
    own, nei = np.minimum(c1, c2), np.maximum(c1, c2)
    s = np.lexsort((nei, own))
    io, own, nei = io[s], own[s], nei[s]
    int_faces = np.stack([ea[io], eb[io], eb[io] + N, ea[io] + N], 1)
    # boundary edges -> patches
    ib = order[ps[~internal]]
    a_, b_ = ea[ib], eb[ib]
    mid = 0.5 * (nodes[a_] + nodes[b_])
    rad = np.linalg.norm(mid, axis=1)
    in_rot = ec[ib] < G["n_rot_cells"]
    tol = 1e-9
    names = ["blade1", "blade2", "blade3", "AMI1", "AMI2", "inlet", "outlet", "sides"]
    masks = {}
    for j, (lo, hi) in enumerate(G["wall_sets"]):
        masks[f"blade{j + 1}"] = in_rot & (a_ >= lo) & (a_ < hi) & (b_ >= lo) & (b_ < hi)
    on_circle = np.abs(np.linalg.norm(nodes[a_], axis=1) - G["r_ami"]) < 1e-9 * max(1, G["r_ami"]) + 1e-12
    on_circle &= np.abs(np.linalg.norm(nodes[b_], axis=1) - G["r_ami"]) < 1e-9 * max(1, G["r_ami"]) + 1e-12
    masks["AMI1"] = in_rot & on_circle
    masks["AMI2"] = ~in_rot & on_circle
    masks["inlet"] = ~in_rot & (np.abs(mid[:, 0] - G["x_in"]) < tol)
    masks["outlet"] = ~in_rot & (np.abs(mid[:, 0] - G["x_out"]) < tol)
    masks["sides"] = ~in_rot & ((np.abs(mid[:, 1] - G["y_lo"]) < tol) | (np.abs(mid[:, 1] - G["y_hi"]) < tol))
    tot = np.zeros(len(ib), int)
    for m in masks.values():
        tot += m
    if (tot != 1).any():
        bad = mid[tot != 1][:5]
        raise RuntimeError(f"{int((tot != 1).sum())} boundary edges not in exactly one patch, e.g. {bad.tolist()} r {rad[tot != 1][:5]}")
    patches = []
    for nm in names:
        e = ib[masks[nm]]
        e = e[np.argsort(ec[e], kind="stable")]
        patches.append((nm, np.stack([ea[e], eb[e], eb[e] + N, ea[e] + N], 1), ec[e]))
    fb_faces = [np.asarray(c)[::-1] for c in cells] + [np.asarray(c) + N for c in cells]
    fb_own = list(range(nc)) + list(range(nc))
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
        f.write(f"{pts.shape[0]}\n(\n" + "\n".join(f"({x:.12g} {y:.12g} {z:.12g})" for x, y, z in pts) + "\n)\n")
    with open(pm / "faces", "w") as f:
        f.write(_header("faceList", "faces"))
        lines = [f"4({a} {b} {c} {d})" for a, b, c, d in int_faces]
        for _, F, _ in patches:
            lines += [f"4({a} {b} {c} {d})" for a, b, c, d in F]
        lines += [f"{len(F)}(" + " ".join(map(str, F)) + ")" for F in fb_faces]
        f.write(f"{n_faces}\n(\n" + "\n".join(lines) + "\n)\n")
    owner = np.concatenate([own] + [q[2] for q in patches] + [np.array(fb_own)])
    with open(pm / "owner", "w") as f:
        f.write(_header("labelList", "owner", note))
        f.write(f"{owner.size}\n(\n" + "\n".join(map(str, owner)) + "\n)\n")
    with open(pm / "neighbour", "w") as f:
        f.write(_header("labelList", "neighbour", note))
        f.write(f"{nei.size}\n(\n" + "\n".join(map(str, nei)) + "\n)\n")
    start = n_int
    body = []
    for nm, F, _ in patches:
        nF = F.shape[0]
        if nm.startswith("blade"):
            extra = "        type            wall;\n        inGroups        2(wall blades);\n"
        elif nm.startswith("AMI"):
            nb = "AMI2" if nm == "AMI1" else "AMI1"
            extra = ("        type            cyclicAMI;\n        inGroups        1(cyclicAMI);\n"
                     "        matchTolerance  0.0001;\n        transform       noOrdering;\n"
                     f"        neighbourPatch  {nb};\n        AMIMethod       faceAreaWeightAMI;\n")
        elif nm == "sides" and G["side_type"] == "wall":
            extra = "        type            wall;\n        inGroups        1(wall);\n"
        else:
            extra = "        type            patch;\n"
        body.append(f"    {nm}\n    {{\n{extra}        nFaces          {nF};\n        startFace       {start};\n    }}\n")
        start += nF
    body.append(f"    frontAndBack\n    {{\n        type            empty;\n        inGroups        1(empty);\n"
                f"        nFaces          {len(fb_faces)};\n        startFace       {start};\n    }}\n")
    with open(pm / "boundary", "w") as f:
        f.write(_header("polyBoundaryMesh", "boundary"))
        f.write(f"{len(body)}\n(\n" + "".join(body) + ")\n")
    with open(pm / "cellZones", "w") as f:
        f.write(_header("regIOobject", "cellZones"))
        f.write("1\n(\nrotor\n{\n    type cellZone;\ncellLabels      List<label> "
                f"{G['n_rot_cells']}\n(\n" + "\n".join(map(str, range(G["n_rot_cells"]))) + "\n)\n;\n}\n)\n")
    return dict(n_points=int(2 * N), n_cells=int(nc), n_faces=int(n_faces), n_internal_faces=int(n_int),
                patch_faces={nm: int(F.shape[0]) for nm, F, _ in patches})


# --------------------------------------------------------------------------- plot
def plot_mesh(path, nodes, cells, rings, info, focus):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    polys = [nodes[c] for c in cells]
    cen = np.array([P.mean(0) for P in polys])
    r_ami = info["r_ami_m"]
    views = [((1.0, 0.0), 2.2, "domain near field (m)"), ((0.0, 0.0), 1.15 * r_ami, "rotor zone and AMI"),
             (tuple(rings[0][0].mean(0)), 0.035, "blade 1"), (tuple(focus), 0.006, "blade 1, tip B (end of the curl)")]
    fig, axs = plt.subplots(2, 2, figsize=(13, 13))
    for ax, (cc, w, t) in zip(axs.flat, views):
        sel = [P for P, c in zip(polys, cen) if abs(c[0] - cc[0]) < 1.3 * w and abs(c[1] - cc[1]) < 1.3 * w]
        ax.add_collection(PolyCollection(sel, facecolors="none", edgecolors="k", linewidths=0.2))
        ax.set_xlim(cc[0] - w, cc[0] + w)
        ax.set_ylim(cc[1] - w, cc[1] + w)
        ax.set_aspect("equal")
        ax.set_title(t, fontsize=10)
    fig.suptitle(f"hypothesis {info['hypothesis']}, {info['level']} {info['wall']}: {info['n_cells']} cells "
                 f"(rotor {info['n_cells_rotor']}), h0 {info['h0_m'] * 1e3:.3f} mm, {info['ring']['n_layers']} layers, "
                 f"theta {info['theta_deg']:g} deg", fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hyp", default="A", choices=["A", "B", "measured"])
    ap.add_argument("--level", default="medium", choices=list(LEVELS))
    ap.add_argument("--wall", default="wf", choices=["wf", "lowRe"])
    ap.add_argument("--U", type=float, default=23.0, help="design free-stream speed for the first-cell height, m/s")
    ap.add_argument("--yplus", type=float, help="target first-cell-centre y+ (default 40 wf, 0.8 lowRe)")
    ap.add_argument("--theta", type=float, default=0.0, help="rotor azimuth of blade 1, deg (rotor_geometry.py)")
    ap.add_argument("--beta", type=float, help="chord-to-radius angle override, deg")
    ap.add_argument("--sense", default="auto", help="auto (drag rule), CCW or CW (model frame)")
    ap.add_argument("--ami-margin", type=float, default=0.022, help="r_ami - r_max, m")
    ap.add_argument("--walls", help="tunnel side walls 'y_lo,y_hi' (m, model frame); default open box")
    ap.add_argument("--x-in", type=float)
    ap.add_argument("--x-out", type=float)
    ap.add_argument("--out", required=True)
    ap.add_argument("--plot")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    walls = tuple(float(v) for v in a.walls.split(",")) if a.walls else None
    info = build(a.hyp, a.level, a.U, a.wall, a.yplus, a.theta, a.out, a.plot, a.ami_margin, walls,
                 a.x_in, a.x_out, a.beta, a.sense, a.verbose)
    print(json.dumps({k: info[k] for k in ("hypothesis", "level", "wall", "h0_m", "n_cells", "n_cells_rotor",
                                           "n_cells_stator", "n_tri", "r_ami_m", "n_ami_faces", "ring", "patch_faces",
                                           "seconds")}, indent=1))


if __name__ == "__main__":
    main()
