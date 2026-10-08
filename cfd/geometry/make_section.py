#!/usr/bin/env python3
"""Blade v1 2D section for the CFD work, measured from blades/v1.stl.

The STL (one blade, metres, prismatic along z) is the authority. The script

  1. slices it at mid-span and splits the outline into its four sides: the
     convex (outer) surface, the concave (inner) surface and two flat end faces;
  2. fits the outer surface with a least-squares cubic B-spline to the STL
     vertices (tessellation vertices lie on the CAD surface; the chords between
     them do not), and the inner surface as a constant-thickness offset of it;
  3. also fits the single circular-arc model the reports assume (concentric
     arcs, constant wall) and reports how far the STL departs from it;
  4. compares the result with reports/roughness_2026-09/inputs/rotor_geometry.json
     (read only; never edited);
  5. optionally cross-checks against the SolidWorks STEP master (--step), which
     is not in the repo;
  6. writes section_v1.json, section_v1.csv (closed outline, metres, counter-
     clockwise, max chord error <= --tol) and section_v1.png next to itself.

Usage:
    python3 cfd/geometry/make_section.py
    python3 cfd/geometry/make_section.py --step ~/Downloads/turbine.STEP --tol 5e-5

Needs numpy, scipy, matplotlib and trimesh (system python3 has them).
"""
import argparse
import datetime
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
import scipy
import trimesh
from scipy.interpolate import BSpline, make_lsq_spline
from scipy.optimize import least_squares
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
STL_DEFAULT = REPO / "blades" / "v1.stl"
GEO_JSON = REPO / "reports" / "roughness_2026-09" / "inputs" / "rotor_geometry.json"
STEP_DEFAULT = Path.home() / "Downloads" / "turbine.STEP"
INCH = 0.0254

FIT_TOL = 2e-6          # m, target max residual of the spline fit to the STL vertices
HOLE_MARGIN = 0.5e-3    # m, vertices this close (in z) to a hole are left out of the fit


# --------------------------------------------------------------------------- helpers
def stitch(segs, ndp=9):
    """Join slice segments (n,2,2) into closed loops of points."""
    key = lambda p: (round(p[0] * 10**ndp), round(p[1] * 10**ndp))
    adj = defaultdict(list)
    for i, (a, b) in enumerate(segs):
        adj[key(a)].append(i)
        adj[key(b)].append(i)
    used = np.zeros(len(segs), bool)
    loops = []
    for start in range(len(segs)):
        if used[start]:
            continue
        used[start] = True
        loop = [segs[start][0], segs[start][1]]
        cur = key(segs[start][1])
        while True:
            nxt = [i for i in adj[cur] if not used[i]]
            if not nxt:
                break
            i = nxt[0]
            used[i] = True
            p = segs[i][1] if key(segs[i][0]) == cur else segs[i][0]
            loop.append(p)
            cur = key(p)
        loops.append(np.array(loop))
    return loops


def signed_area(P):
    x, y = P[:, 0], P[:, 1]
    return 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)


def project_to_polyline(poly, pts):
    """Distance from pts to an open polyline, and the arc length of the foot point."""
    a, b = poly[:-1], poly[1:]
    ab = b - a
    L = np.linalg.norm(ab, axis=1)
    cum = np.r_[0.0, np.cumsum(L)]
    best = np.full(len(pts), np.inf)
    s = np.zeros(len(pts))
    for i in range(len(a)):
        t = np.clip(((pts - a[i]) @ ab[i]) / L[i] ** 2, 0.0, 1.0)
        d = np.linalg.norm(pts - (a[i] + t[:, None] * ab[i]), axis=1)
        upd = d < best
        best[upd] = d[upd]
        s[upd] = cum[i] + t[upd] * L[i]
    return best, s


def dist_to_polyline(poly, pts, closed=False):
    if closed:
        poly = np.vstack([poly, poly[:1]])
    return project_to_polyline(poly, pts)[0]


def dense(spl, n=200001):
    u = np.linspace(0.0, 1.0, n)
    return u, spl(u)


def foot_param(spl, pts, n=200001):
    u, C = dense(spl, n)
    d, i = cKDTree(C).query(pts)
    return u[i], d


def fit_bspline(pts, u0, n_int, w=None):
    """Least-squares clamped cubic B-spline through pts(u0), with foot-point
    re-parameterisation (3 passes). Returns the spline and geometric residuals."""
    u = (u0 - u0.min()) / (u0.max() - u0.min())
    t = np.r_[[0.0] * 4, np.linspace(0, 1, n_int + 2)[1:-1], [1.0] * 4]
    for _ in range(3):
        o = np.argsort(u, kind="stable")
        uu, PP = u[o], pts[o]
        keep = np.r_[True, np.diff(uu) > 1e-12]
        ww = None if w is None else w[o][keep]
        spl = make_lsq_spline(uu[keep], PP[keep], t, k=3, w=ww)
        u, d = foot_param(spl, pts)
    return spl, d


def unit(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def curve_frame(spl, u):
    d1 = spl.derivative(1)(u)
    d2 = spl.derivative(2)(u)
    sp = np.linalg.norm(d1, axis=1)
    kappa = (d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / sp**3
    tang = d1 / sp[:, None]
    return tang, kappa


def arclen(C):
    return np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(C, axis=0), axis=1))]


def chord_error(P, C):
    """Max distance from dense curve C to polyline P (both ordered along the curve)."""
    return dist_to_polyline(P, C).max()


def resample_equal_error(C, kappa_abs, tol):
    """Pick points on dense curve C so every chord deviates <= tol. Spacing follows
    equal increments of integral(sqrt|kappa| ds), which equalises the sagitta."""
    s = arclen(C)
    g = np.r_[0.0, np.cumsum(np.sqrt(np.maximum(0.5 * (kappa_abs[1:] + kappa_abs[:-1]), 1e-9))
                             * np.diff(s))]
    n = max(2, int(np.ceil(g[-1] / np.sqrt(8 * tol))))
    while True:
        idx = np.unique(np.searchsorted(g, np.linspace(0, g[-1], n + 1)).clip(0, len(C) - 1))
        P = C[idx]
        err = chord_error(P, C)
        if err <= tol:
            return P, err
        n += 1


# --------------------------------------------------------------------------- STEP
def read_step_bsplines(path):
    """Section curves (z = 0 row of control points) of every cubic-by-linear
    B_SPLINE_SURFACE_WITH_KNOTS in an AP214 STEP file. Units from the file."""
    txt = Path(path).read_text(errors="replace")
    unit_inch = "CONVERSION_BASED_UNIT ( 'INCH'" in txt
    scale = INCH if unit_inch else 1e-3
    data = txt.split("DATA;", 1)[1]
    ents = {int(m.group(1)): " ".join(m.group(2).split())
            for m in re.finditer(r"#(\d+)\s*=\s*(.*?);\s*\n(?=#|ENDSEC)", data, re.S)}

    def pt(i):
        g = re.search(r"\(\s*([-\d.Ee+]+)\s*,\s*([-\d.Ee+]+)\s*,\s*([-\d.Ee+]+)\s*\)", ents[i])
        return np.array([float(v) for v in g.groups()])

    out = []
    for i, s in ents.items():
        if not s.startswith("B_SPLINE_SURFACE_WITH_KNOTS ( 'NONE', 3, 1,"):
            continue
        grid = re.search(r"3, 1, \((.*?)\), \.UNSPEC", s).group(1)
        rows = re.findall(r"\(\s*#(\d+)\s*,\s*#(\d+)\s*\)", grid)
        A = np.array([pt(int(a)) for a, b in rows])
        B = np.array([pt(int(b)) for a, b in rows])
        P = A if A[0, 2] <= B[0, 2] else B
        nums = re.findall(r"\(\s*([-\d.Ee+,\s]+?)\s*\)", s.split(".F., .F., .F.,")[1])
        mult = [int(x) for x in nums[0].split(",")]
        kn = [float(x) for x in nums[2].split(",")]
        out.append({"entity": f"#{i}", "n_ctrl": len(P), "knots": kn, "mult": mult,
                    "ctrl_file_units": P[:, :2].tolist(), "unit": "inch" if unit_inch else "mm",
                    "spline": BSpline(np.repeat(kn, mult), P[:, :2] * scale, 3)})
    return out


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stl", default=str(STL_DEFAULT))
    ap.add_argument("--step", default=str(STEP_DEFAULT),
                    help="optional STEP master for a cross-check (skipped if missing)")
    ap.add_argument("--tol", type=float, default=5e-5, help="max chord error of the CSV outline, m")
    ap.add_argument("--out", default=str(HERE))
    a = ap.parse_args()
    out = Path(a.out)
    stl = Path(a.stl)

    mesh = trimesh.load(stl, force="mesh")
    sha = hashlib.sha256(stl.read_bytes()).hexdigest()
    ext = mesh.extents
    if int(np.argmax(ext)) != 2:
        raise SystemExit(f"expected the span along z; extents {ext}")
    if ext.max() > 1.0:
        raise SystemExit("STL does not look like metres")
    zmin, zmax = mesh.bounds[:, 2]
    span = zmax - zmin

    # ---- non-prismatic features (bolt holes): faces tilted out of the z-direction
    n = mesh.face_normals
    c = mesh.triangles_center
    endcap = (np.abs(n[:, 2]) > 0.99) & ((np.abs(c[:, 2] - zmin) < 1e-6) | (np.abs(c[:, 2] - zmax) < 1e-6))
    feat = (np.abs(n[:, 2]) > 0.1) & ~endcap
    fv = np.unique(mesh.faces[feat].ravel())
    zs = np.sort(mesh.vertices[fv, 2])
    bands, n_slivers = [], 0
    if len(zs):
        cuts = np.where(np.diff(zs) > 1e-3)[0]
        for lo, hi in zip(np.r_[0, cuts + 1], np.r_[cuts, len(zs) - 1]):
            nf = int((feat & (c[:, 2] >= zs[lo] - 1e-9) & (c[:, 2] <= zs[hi] + 1e-9)).sum())
            if nf >= 20 and zs[hi] - zs[lo] > 1e-3:
                bands.append((zs[lo], zs[hi]))
            else:
                n_slivers += nf      # isolated sliver triangles of the tessellation
    holes = []
    for lo, hi in bands:
        sel_f = feat & (c[:, 2] >= lo - 1e-9) & (c[:, 2] <= hi + 1e-9)
        # the hole wall: faces whose normal is far from z AND from the section plane
        wall_f = sel_f & (np.abs(n[:, 2]) < 0.99)
        axis = np.linalg.svd(n[wall_f], full_matrices=False)[2][-1]
        axis = axis * np.sign(axis[np.argmax(np.abs(axis))])
        vv = mesh.vertices[np.unique(mesh.faces[sel_f].ravel())]
        holes.append({"z_range_m": [float(lo), float(hi)], "z_centre_m": float(0.5 * (lo + hi)),
                      "diameter_from_z_extent_m": float(hi - lo),
                      "y_centre_m": float(0.5 * (vv[:, 1].min() + vv[:, 1].max())),
                      "xy_extent_m": [vv[:, :2].min(0).tolist(), vv[:, :2].max(0).tolist()],
                      "axis_unit_vector": np.round(axis, 4).tolist()})

    # ---- mid-span slice
    z_cut = 0.5 * (zmin + zmax)
    clear = min([z_cut - hi if z_cut > hi else lo - z_cut if z_cut < lo else -1.0
                 for lo, hi in bands] or [np.inf])
    if clear <= 0:
        raise SystemExit("mid-span slice cuts a hole; choose another station")
    segs = trimesh.intersections.mesh_plane(mesh, [0, 0, 1], [0, 0, z_cut])[:, :, :2]
    loops = stitch(segs)
    if len(loops) != 1 or np.linalg.norm(loops[0][0] - loops[0][-1]) > 1e-9:
        raise SystemExit(f"mid-span slice is not one closed loop ({len(loops)} loops)")
    S = loops[0][:-1]
    if signed_area(S) < 0:
        S = S[::-1]
    slice_area = signed_area(S)
    slice_perim = arclen(np.vstack([S, S[:1]]))[-1]

    # ---- the four corners: largest turning angles of the outline
    d1 = S - np.roll(S, 1, 0)
    d2 = np.roll(S, -1, 0) - S
    turn = np.degrees(np.arctan2(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0], (d1 * d2).sum(1)))
    corners = np.sort(np.argsort(-np.abs(turn))[:4])
    chains = []
    for k in range(4):
        i0, i1 = corners[k], corners[(k + 1) % 4]
        idx = np.arange(i0, i1 + 1) if i1 > i0 else np.r_[np.arange(i0, len(S)), np.arange(0, i1 + 1)]
        chains.append(S[idx])
    lens = [arclen(ch)[-1] for ch in chains]
    order = np.argsort(lens)
    end_chains = [chains[i] for i in order[:2]]
    outer_chain, inner_chain = chains[order[3]], chains[order[2]]

    # ---- vertex cloud (prismatic part only), classified onto the two surfaces
    V = mesh.vertices
    okz = np.ones(len(V), bool)
    for lo, hi in bands:
        okz &= (V[:, 2] < lo - HOLE_MARGIN) | (V[:, 2] > hi + HOLE_MARGIN)
    XY = np.unique(np.round(V[okz, :2], 10), axis=0)
    dO, sO = project_to_polyline(outer_chain, XY)
    dI, sI = project_to_polyline(inner_chain, XY)
    on_o = dO <= dI
    if np.minimum(dO, dI).max() > 0.2e-3:
        raise SystemExit("a vertex lies > 0.2 mm off the slice outline: not prismatic?")
    PO, uO = XY[on_o], sO[on_o]
    PI = XY[~on_o]

    # ---- outer surface: least-squares cubic B-spline, fewest uniform knots meeting FIT_TOL
    wO = np.ones(len(PO))
    for tip in (outer_chain[0], outer_chain[-1]):
        wO[np.argmin(np.linalg.norm(PO - tip, axis=1))] = 1e3
    for n_int in (4, 6, 8, 10, 12, 14, 16, 20, 24, 28, 32, 40):
        splO, resO = fit_bspline(PO, uO, n_int, wO)
        if resO.max() < FIT_TOL:
            break
    # orient: parameter 0 at the end nearer the slice chain start
    uD, CO = dense(splO)
    tO, kO = curve_frame(splO, uD)
    # inward normal: towards the inner surface
    nrm = np.c_[-tO[:, 1], tO[:, 0]]
    mid = len(uD) // 2
    _, j = cKDTree(PI).query(CO[mid])
    if np.dot(PI[j] - CO[mid], nrm[mid]) < 0:
        nrm = -nrm
    # sign of curvature so that positive = concave towards the inner side
    kO = kO * np.sign(np.dot(nrm[mid], np.array([-tO[mid, 1], tO[mid, 0]])))

    # ---- wall: distance of every inner vertex from the outer curve
    wall_d, wall_i = cKDTree(CO).query(PI)
    s_dense = arclen(CO)
    s_of_inner = s_dense[wall_i]
    core = (s_of_inner > 2e-3) & (s_of_inner < s_dense[-1] - 2e-3)
    t_wall = float(np.median(wall_d))
    CI = CO + t_wall * nrm                      # inner surface = constant-thickness offset
    CM = CO + 0.5 * t_wall * nrm                # midline
    resI = cKDTree(CI).query(PI)[0]
    kI = np.gradient(np.unwrap(np.arctan2(*np.gradient(CI, axis=0).T[::-1])), arclen(CI))

    # ---- corners and end faces (STL slice corners vs model ends)
    oc = [CO[0], CO[-1]]
    ic_model = [CI[0], CI[-1]]
    ends = []
    for k in (0, -1):
        ch = min(end_chains, key=lambda e: min(np.linalg.norm(e[0] - CO[k]), np.linalg.norm(e[-1] - CO[k])))
        a_, b_ = (ch[0], ch[-1]) if np.linalg.norm(ch[0] - CO[k]) < np.linalg.norm(ch[-1] - CO[k]) else (ch[-1], ch[0])
        face = b_ - a_
        ang = np.degrees(np.arccos(abs(np.dot(unit(face), nrm[k]))))
        # straightness of the end face in the slice
        dev = dist_to_polyline(np.array([a_, b_]), ch).max() if len(ch) > 2 else 0.0
        ends.append({"outer_corner_m": a_.tolist(), "inner_corner_m": b_.tolist(),
                     "length_m": float(np.linalg.norm(face)),
                     "angle_to_surface_normal_deg": float(ang),
                     "max_deviation_from_straight_m": float(dev),
                     "model_inner_corner_minus_stl_m": float(np.linalg.norm(ic_model[k] - b_))})

    # ---- single circular-arc model (what rotor_geometry.json describes)
    def res_arc(p):
        return np.r_[np.hypot(*(PO - p[:2]).T) - p[2], np.hypot(*(PI - p[:2]).T) - p[3]]
    c0 = np.r_[CO.mean(0), 0.022, 0.020]
    arc = least_squares(res_arc, c0)
    ra = arc.fun
    cx, cy, Ro, Ri = arc.x
    angO = np.unwrap(np.arctan2(CO[:, 1] - cy, CO[:, 0] - cx))
    arc_model = {
        "centre_m": [float(cx), float(cy)], "R_outer_m": float(Ro), "R_inner_m": float(Ri),
        "wall_m": float(Ro - Ri), "arc_angle_deg": float(abs(np.degrees(angO[-1] - angO[0]))),
        "residual_rms_m": float(np.sqrt(np.mean(ra**2))), "residual_max_m": float(np.abs(ra).max()),
        "verdict": "rejected: the STL is not a circular arc",
    }

    # ---- derived dimensions
    A_tip, B_tip = (CO[0], CO[-1]) if CO[0][1] < CO[-1][1] else (CO[-1], CO[0])
    chord_vec = B_tip - A_tip
    chord = float(np.linalg.norm(chord_vec))
    ch_u = chord_vec / chord
    ch_n = np.array([ch_u[1], -ch_u[0]])
    outline_dense = np.vstack([CO, CI[::-1]])
    proj_n = (outline_dense - A_tip) @ ch_n
    proj_t = (outline_dense - A_tip) @ ch_u
    depth_outer = float(np.abs((CO - A_tip) @ ch_n).max())
    tang_ang = np.unwrap(np.arctan2(tO[:, 1], tO[:, 0]))
    turning = float(abs(np.degrees(tang_ang[-1] - tang_ang[0])))
    bb_min, bb_max = outline_dense.min(0), outline_dense.max(0)
    area_model = abs(signed_area(outline_dense))
    L_mid = arclen(CM)[-1]
    Rk = 1.0 / np.maximum(np.abs(kO), 1e-12)
    imin, imax = int(np.argmin(Rk)), int(np.argmax(Rk))
    inflections = int(np.sum(np.diff(np.sign(kO)) != 0))

    # whole-mesh wall estimates (the 1.79 mm in the reports is 2V/A)
    V_mesh, A_mesh = float(mesh.volume), float(mesh.area)
    A_caps = float(mesh.area_faces[endcap].sum())
    A_endfaces = sum(e["length_m"] for e in ends) * span
    wall_2VA = 2 * V_mesh / A_mesh
    wall_2VA_sides = 2 * V_mesh / (A_mesh - A_caps - A_endfaces)

    # spanwise (prismatic) check: residual of every prismatic vertex by span decile
    Vall = V[okz]
    dall = np.minimum(cKDTree(CO).query(Vall[:, :2])[0], cKDTree(CI).query(Vall[:, :2])[0])
    on_end = np.zeros(len(Vall), bool)
    for e in ends:
        seg = np.array([e["outer_corner_m"], e["inner_corner_m"]])
        on_end |= dist_to_polyline(seg, Vall[:, :2]) < 1e-6
    dall = np.where(on_end, 0.0, dall)
    span_check = []
    for k in range(10):
        lo, hi = zmin + k * span / 10, zmin + (k + 1) * span / 10
        sel = (Vall[:, 2] >= lo) & (Vall[:, 2] <= hi)
        span_check.append({"z_m": [float(lo), float(hi)], "n_vertices": int(sel.sum()),
                           "max_residual_m": float(dall[sel].max()) if sel.any() else None})

    # ---- outline polyline (counter-clockwise), max chord error <= tol
    PO_s, errO = resample_equal_error(CO, np.abs(kO), a.tol)
    PI_s, errI = resample_equal_error(CI, np.abs(kI), a.tol)
    outline = np.vstack([PO_s, PI_s[::-1]])
    if signed_area(outline) < 0:
        outline = outline[::-1]
    # checks against the model and against the STL vertices
    err_model = max(dist_to_polyline(outline, CO, closed=True).max(),
                    dist_to_polyline(outline, CI, closed=True).max())
    err_stl = float(dist_to_polyline(outline, np.vstack([PO, PI]), closed=True).max())
    np.savetxt(out / "section_v1.csv", outline, delimiter=",", fmt="%.9f",
               header="x_m,y_m", comments="")

    # ---- STEP cross-check (optional)
    step, step_R = None, None
    if a.step and Path(a.step).expanduser().exists():
        sp = Path(a.step).expanduser()
        surfs = read_step_bsplines(sp)
        step = {"file": str(sp), "sha256": hashlib.sha256(sp.read_bytes()).hexdigest(),
                "note": "SolidWorks master, outside the repo; used only as a cross-check",
                "surfaces": []}
        for s_ in surfs:
            u = np.linspace(0, 1, 200001)
            C = s_["spline"](u)
            dO_ = cKDTree(C).query(CO)[0].max()
            dI_ = cKDTree(C).query(CI)[0].max()
            role = "outer (convex)" if dO_ < dI_ else "inner (concave)"
            if dO_ < dI_:
                _, kS = curve_frame(s_["spline"], u)
                sS = arclen(C)
                if np.linalg.norm(C[0] - CO[0]) > np.linalg.norm(C[-1] - CO[0]):
                    sS, kS = sS[-1] - sS[::-1], kS[::-1]
                RS = 1.0 / np.maximum(np.abs(kS), 1e-12)
                step_R = (sS, RS)
                step["outer_radius_of_curvature_m"] = {"min": float(RS.min()), "max": float(RS.max())}
            step["surfaces"].append({
                "entity": s_["entity"], "role": role, "n_ctrl": s_["n_ctrl"],
                "knots": s_["knots"], "multiplicities": s_["mult"],
                "ctrl_xy_" + s_["unit"]: s_["ctrl_file_units"] if s_["n_ctrl"] <= 12 else "omitted (offset surface)",
                "max_dist_model_to_step_m": float(min(dO_, dI_)),
                "max_dist_stl_vertices_to_step_m": float(cKDTree(C).query(PO if dO_ < dI_ else PI)[0].max())})
        o_ = [s_ for s_ in surfs if s_["n_ctrl"] <= 12]
        if o_ and len(surfs) == 2:
            u = np.linspace(0, 1, 200001)
            C1, C2 = surfs[0]["spline"](u), surfs[1]["spline"](u)
            dd = cKDTree(C1).query(C2[200:-200])[0]
            step["wall_between_step_surfaces_m"] = {"min": float(dd.min()), "max": float(dd.max()),
                                                    "mean": float(dd.mean()),
                                                    "mean_inch": float(dd.mean() / INCH)}

    # ---- comparison with rotor_geometry.json
    geo = json.loads(GEO_JSON.read_text())["blade_section"]
    cmp = {
        "file": str(GEO_JSON.relative_to(REPO)),
        "chord_mm": {"stated": geo["chord_mm"],
                     "stl_outer_tip_to_outer_tip": round(chord * 1e3, 3),
                     "stl_bbox_y_extent_cad_frame": round((bb_max - bb_min)[1] * 1e3, 3),
                     "note": "48.0 matches the bounding-box y-extent in the CAD frame, "
                             "not the distance between the tips"},
        "depth_mm": {"stated": geo["depth_mm"],
                     "stl_max_distance_from_outer_tip_chord": round(depth_outer * 1e3, 3),
                     "stl_bbox_x_extent_cad_frame": round((bb_max - bb_min)[0] * 1e3, 3),
                     "note": "24.46 matches the bounding-box x-extent in the CAD frame"},
        "wall_mm": {"stated": geo["wall_mm"], "stl_measured": round(t_wall * 1e3, 4),
                    "difference_mm": round(t_wall * 1e3 - geo["wall_mm"], 4),
                    "difference_pct_of_stated": round(100 * (t_wall * 1e3 / geo["wall_mm"] - 1), 2),
                    "stated_value_reproduced_by_2V_over_A_mm": round(wall_2VA * 1e3, 4),
                    "2V_over_A_without_caps_and_end_faces_mm": round(wall_2VA_sides * 1e3, 4),
                    "note": "2V/A counts the two end caps and the two end faces as wall area, "
                            "so it reads low; the inner-to-outer surface distance is the wall"},
        "arc_deg": {"stated": geo["arc_deg"], "stl_tangent_turning_tip_to_tip": round(turning, 2),
                    "best_single_arc_angle": round(arc_model["arc_angle_deg"], 2)},
        "description": {"stated": geo["description"],
                        "stl": "cubic B-spline outer surface with radius of curvature "
                               f"{Rk[imin]*1e3:.1f}-{Rk[imax]*1e3:.0f} mm, constant wall; best "
                               f"single arc misses the STL by up to {arc_model['residual_max_m']*1e3:.2f} mm"},
    }

    res = {
        "_what": "Blade v1 2D section measured from blades/v1.stl (the authority). "
                 "Outer = convex surface, inner = concave surface. CAD frame: the STL's own x, y "
                 "(metres); z is the span. Generated by cfd/geometry/make_section.py; do not edit.",
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": {"stl": str(stl.relative_to(REPO)) if stl.is_relative_to(REPO) else str(stl),
                   "stl_sha256": sha, "n_faces": int(len(mesh.faces)),
                   "extents_m": ext.tolist(), "span_m": float(span),
                   "slice_z_m": float(z_cut), "slice_clearance_to_nearest_hole_m": float(clear),
                   "versions": {"numpy": np.__version__, "scipy": scipy.__version__,
                                "trimesh": trimesh.__version__}},
        "model": {
            "outer_surface": {"type": "clamped cubic B-spline, least-squares fit to STL vertices",
                              "knots": splO.t.tolist(), "ctrl_xy_m": splO.c.tolist(),
                              "n_vertices_fitted": int(len(PO)),
                              "residual_max_m": float(resO.max()),
                              "residual_rms_m": float(np.sqrt(np.mean(resO**2)))},
            "inner_surface": {"type": "offset of the outer surface by wall_m along its inward normal",
                              "n_vertices_checked": int(len(PI)),
                              "residual_max_m": float(resI.max()),
                              "residual_rms_m": float(np.sqrt(np.mean(resI**2)))},
            "wall_m": t_wall,
            "wall_stats_m": {"median": t_wall, "mean": float(wall_d[core].mean()),
                             "min": float(wall_d[core].min()), "max": float(wall_d[core].max()),
                             "std": float(wall_d[core].std()),
                             "note": "inner-vertex distance to the outer surface, 2 mm from each tip excluded",
                             "inch": t_wall / INCH},
            "end_faces": {"type": "flat, square to the surfaces", "faces": ends},
        },
        "dimensions": {
            "outer_tips_m": {"A_lower": A_tip.tolist(), "B_upper": B_tip.tolist()},
            "chord_outer_tip_to_tip_m": chord,
            "chord_other_definitions_m": {
                "midline_tip_to_tip (end-face midpoints)": float(np.linalg.norm(CM[-1] - CM[0])),
                "inner_tip_to_tip": float(np.linalg.norm(CI[-1] - CI[0])),
                "max_extent_along_outer_tip_chord": float(proj_t.max() - proj_t.min())},
            "chord_direction_deg_from_x": float(np.degrees(np.arctan2(ch_u[1], ch_u[0]))),
            "depth_from_chord_m": depth_outer,
            "section_extent_along_chord_m": [float(proj_t.min()), float(proj_t.max())],
            "section_extent_normal_to_chord_m": [float(proj_n.min()), float(proj_n.max())],
            "bbox_cad_frame_m": {"min": bb_min.tolist(), "max": bb_max.tolist(),
                                 "extent": (bb_max - bb_min).tolist()},
            "tangent_turning_tip_to_tip_deg": turning,
            "arc_length_m": {"outer": float(s_dense[-1]), "inner": float(arclen(CI)[-1]),
                             "midline": float(L_mid)},
            "area_m2": float(area_model), "area_over_midline_m": float(area_model / L_mid),
            "perimeter_m": float(s_dense[-1] + arclen(CI)[-1] + sum(e["length_m"] for e in ends)),
            "stl_slice_area_m2": float(slice_area), "stl_slice_perimeter_m": float(slice_perim),
            "outer_radius_of_curvature_m": {
                "min": float(Rk[imin]), "at_xy": CO[imin].tolist(),
                "max": float(Rk[imax]), "at_xy_max": CO[imax].tolist(),
                "inflection_points": inflections},
        },
        "single_arc_model": arc_model,
        "holes": {"n_sliver_faces_ignored": n_slivers, "note": "through-holes in the wall (not in the 2D section); likely the hub "
                          "attachment, unconfirmed", "found": holes},
        "spanwise_check": {"note": "max distance of STL vertices (holes excluded) from the 2D model, "
                                   "per tenth of span", "deciles": span_check,
                           "max_m": float(max(s["max_residual_m"] for s in span_check))},
        "outline_csv": {"file": "section_v1.csv", "columns": "x_m,y_m", "frame": "CAD (STL x, y)",
                        "orientation": "counter-clockwise; closed (last point joins the first, "
                                       "first point not repeated)",
                        "n_points": int(len(outline)), "tol_m": a.tol,
                        "max_chord_error_vs_model_m": float(err_model),
                        "max_distance_stl_vertices_to_polyline_m": err_stl},
        "step_crosscheck": step,
        "comparison_with_rotor_geometry_json": cmp,
    }
    (out / "section_v1.json").write_text(json.dumps(res, indent=1) + "\n")

    plot(out / "section_v1.png", S, PO, PI, CO, CI, outline, arc_model, A_tip, B_tip,
         s_dense, Rk, wall_d, s_of_inner, resO, uO, resI, res, holes, bb_min, bb_max, step_R)
    report(res)


# --------------------------------------------------------------------------- plot
def plot(path, S, PO, PI, CO, CI, outline, arcm, A, B, s_dense, Rk, wall_d, s_in,
         resO, uO, resI, res, holes, bb_min, bb_max, step_R=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
    INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                         "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True,
                         "grid.color": GRID, "grid.linewidth": 0.6, "figure.facecolor": SURF,
                         "axes.facecolor": SURF, "legend.frameon": False})
    fig = plt.figure(figsize=(12, 8.6))
    gs = GridSpec(3, 2, width_ratios=[1.05, 1.25], hspace=0.42, wspace=0.22, figure=fig)
    ax = fig.add_subplot(gs[:, 0])
    mm = 1e3
    loop = np.vstack([S, S[:1]])
    ax.plot(loop[:, 0] * mm, loop[:, 1] * mm, color="#9a9890", lw=3.2, solid_capstyle="round",
            label="STL slice at mid-span")
    ax.plot(*(np.vstack([PO, PI])[::15] * mm).T, ".", ms=1.6, color=INK2,
            label="STL vertices (every 15th)")
    ol = np.vstack([outline, outline[:1]])
    ax.plot(ol[:, 0] * mm, ol[:, 1] * mm, color=BLUE, lw=1.2,
            label=f"fitted section (CSV, {len(outline)} pts)")
    th = np.linspace(0, 2 * np.pi, 400)
    for R in (arcm["R_outer_m"], arcm["R_inner_m"]):
        ax.plot((arcm["centre_m"][0] + R * np.cos(th)) * mm, (arcm["centre_m"][1] + R * np.sin(th)) * mm,
                "--", color=ORANGE, lw=1.0, label="best single circular arc" if R == arcm["R_outer_m"] else None)
    ax.plot([A[0] * mm, B[0] * mm], [A[1] * mm, B[1] * mm], ":", color=INK, lw=1.0)
    d = res["dimensions"]
    ax.text(-3.6, 36, f"outer-tip\nchord\n{d['chord_outer_tip_to_tip_m']*mm:.2f} mm",
            fontsize=7.5, color=INK, ha="left", va="center")
    for h in holes:
        ax.axhline(h["y_centre_m"] * mm, color=AQUA, lw=0.8, xmin=0.3, xmax=1.0)
    if holes:
        zlist = ", ".join(f"{h['z_centre_m'] * mm:.1f}" for h in holes)
        ax.text(18.5, holes[0]["y_centre_m"] * mm - 0.5,
                f"bolt-hole axis\n{len(holes)} holes, d {holes[0]['diameter_from_z_extent_m']*mm:.2f} mm\n"
                f"z = {zlist} mm",
                fontsize=7.5, color=INK2, ha="right", va="top")
    ax.add_patch(plt.Rectangle(bb_min * mm, *((bb_max - bb_min) * mm), fill=False, ec=INK2,
                               lw=0.6, ls=(0, (2, 3))))
    ax.text(bb_max[0] * mm, bb_min[1] * mm - 1.2,
            f"bounding box {(bb_max-bb_min)[0]*mm:.2f} x {(bb_max-bb_min)[1]*mm:.2f} mm",
            fontsize=7.5, color=INK2, ha="right", va="top")
    ax.set_aspect("equal")
    ax.set_xlim(-4, 31)
    ax.set_ylim(1, 58)
    ax.set_xlabel("x, mm (STL frame)")
    ax.set_ylabel("y, mm (STL frame)")
    ax.set_title("(a) Blade v1 section, STL against fitted model", loc="left", fontsize=10, color=INK)
    ax.legend(loc="lower right", fontsize=7.5, bbox_to_anchor=(1.0, 0.06))

    b = fig.add_subplot(gs[0, 1])
    if step_R is not None:
        b.semilogy(step_R[0] * mm, step_R[1] * mm, color="#9a9890", lw=3.2, label="STEP design spline")
    b.semilogy(s_dense * mm, Rk * mm, color=BLUE, lw=1.4, label="fit to STL vertices")
    from matplotlib.ticker import FixedLocator, NullLocator, ScalarFormatter
    b.yaxis.set_major_locator(FixedLocator([10, 15, 20, 30, 50, 80]))
    b.yaxis.set_minor_locator(NullLocator())
    b.yaxis.set_major_formatter(ScalarFormatter())
    b.set_ylim(9, 100)
    b.legend(loc="upper right", fontsize=7.5)
    b.axhline(arcm["R_outer_m"] * mm, ls="--", color=ORANGE, lw=1.0)
    b.text(s_dense[-1] * mm, arcm["R_outer_m"] * mm * 1.08, f"best single arc R = {arcm['R_outer_m']*mm:.1f} mm",
           ha="right", fontsize=7.5, color=INK2)
    b.set_ylabel("radius of curvature, mm")
    b.set_title("(b) Outer surface curvature along its length", loc="left", fontsize=10, color=INK)
    b.set_xlim(0, s_dense[-1] * mm)

    c = fig.add_subplot(gs[1, 1], sharex=b)
    c.plot(s_in * mm, wall_d * mm, ".", ms=1.5, color=BLUE)
    c.axhline(res["comparison_with_rotor_geometry_json"]["wall_mm"]["stated"], ls="--", color=ORANGE, lw=1.0)
    c.text(s_dense[-1] * mm, res["comparison_with_rotor_geometry_json"]["wall_mm"]["stated"] + 0.004,
           "rotor_geometry.json: 1.79 mm", ha="right", fontsize=7.5, color=INK2)
    c.text(1, res["model"]["wall_m"] * mm + 0.006, f"STL: {res['model']['wall_m']*mm:.3f} mm",
           fontsize=7.5, color=INK2)
    c.set_ylim(1.77, 1.88)
    c.set_ylabel("wall, mm")
    c.set_title("(c) Wall: inner-surface vertices to outer surface", loc="left", fontsize=10, color=INK)

    e = fig.add_subplot(gs[2, 1], sharex=b)
    so_dense = np.interp(cKDTree(CO).query(PO)[1], np.arange(len(CO)), s_dense)
    e.plot(so_dense * mm, resO * 1e6, ".", ms=1.5, color=BLUE, label="outer vertices")
    si_dense = s_dense[cKDTree(CI).query(PI)[1]]
    e.plot(si_dense * mm, resI * 1e6, ".", ms=1.5, color=AQUA, label="inner vertices")
    e.set_ylabel("distance to model, µm")
    e.set_xlabel("arc length along the outer surface from its lower tip, mm" if CO[0][1] < CO[-1][1]
                 else "arc length along the outer surface from its upper tip, mm")
    e.set_title(f"(d) Fit residuals (single arc: up to {arcm['residual_max_m']*1e3:.1f} mm)",
                loc="left", fontsize=10, color=INK)
    e.legend(loc="upper right", fontsize=7.5, markerscale=5, ncol=2)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def report(r):
    d, m, cmp = r["dimensions"], r["model"], r["comparison_with_rotor_geometry_json"]
    mm = 1e3
    print(f"STL {r['source']['stl']}  sha256 {r['source']['stl_sha256'][:12]}  slice z = {r['source']['slice_z_m']*mm:.3f} mm")
    print(f"outer spline: {len(m['outer_surface']['ctrl_xy_m'])} ctrl pts, residual max "
          f"{m['outer_surface']['residual_max_m']*1e6:.2f} um rms {m['outer_surface']['residual_rms_m']*1e6:.2f} um")
    print(f"inner = offset by wall {m['wall_m']*mm:.4f} mm ({m['wall_stats_m']['inch']:.4f} in); "
          f"residual max {m['inner_surface']['residual_max_m']*1e6:.2f} um; wall range "
          f"{m['wall_stats_m']['min']*mm:.4f}-{m['wall_stats_m']['max']*mm:.4f} mm")
    for i, e in enumerate(m["end_faces"]["faces"]):
        print(f"end face {i}: length {e['length_m']*mm:.4f} mm, {e['angle_to_surface_normal_deg']:.2f} deg off the surface normal")
    print(f"outer-tip chord {d['chord_outer_tip_to_tip_m']*mm:.3f} mm at {d['chord_direction_deg_from_x']:.2f} deg; "
          f"depth from chord {d['depth_from_chord_m']*mm:.3f} mm; bbox {d['bbox_cad_frame_m']['extent'][0]*mm:.3f} x "
          f"{d['bbox_cad_frame_m']['extent'][1]*mm:.3f} mm")
    print(f"turning tip to tip {d['tangent_turning_tip_to_tip_deg']:.2f} deg; outer R of curvature "
          f"{d['outer_radius_of_curvature_m']['min']*mm:.2f}-{d['outer_radius_of_curvature_m']['max']*mm:.1f} mm")
    a = r["single_arc_model"]
    print(f"single arc: Ro {a['R_outer_m']*mm:.3f} Ri {a['R_inner_m']*mm:.3f} mm, arc {a['arc_angle_deg']:.1f} deg, "
          f"residual rms {a['residual_rms_m']*mm:.3f} max {a['residual_max_m']*mm:.3f} mm -> {a['verdict']}")
    for h in r["holes"]["found"]:
        print(f"hole: z {h['z_centre_m']*mm:.2f} mm, d {h['diameter_from_z_extent_m']*mm:.3f} mm, y {h['y_centre_m']*mm:.3f} mm, axis {h['axis_unit_vector']}")
    print(f"spanwise max residual {r['spanwise_check']['max_m']*1e6:.2f} um")
    o = r["outline_csv"]
    print(f"CSV: {o['n_points']} pts, chord error {o['max_chord_error_vs_model_m']*mm:.4f} mm vs model, "
          f"{o['max_distance_stl_vertices_to_polyline_m']*mm:.4f} mm max STL-vertex distance")
    if r["step_crosscheck"]:
        for s in r["step_crosscheck"]["surfaces"]:
            print(f"STEP {s['entity']} {s['role']}: {s['n_ctrl']} ctrl, model-to-STEP max "
                  f"{s['max_dist_model_to_step_m']*1e6:.2f} um, STL-vertices-to-STEP max {s['max_dist_stl_vertices_to_step_m']*1e6:.2f} um")
        w = r["step_crosscheck"].get("wall_between_step_surfaces_m")
        if w:
            print(f"STEP wall {w['mean']*mm:.4f} mm = {w['mean_inch']:.5f} in")
    print("vs rotor_geometry.json:")
    for k in ("chord_mm", "depth_mm", "wall_mm", "arc_deg"):
        print(f"  {k}: {json.dumps({kk: vv for kk, vv in cmp[k].items() if kk != 'note'})}")


if __name__ == "__main__":
    main()
