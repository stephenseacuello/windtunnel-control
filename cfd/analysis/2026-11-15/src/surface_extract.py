#!/usr/bin/env python3
"""Wall distributions around the single blade, 15 Nov 2026 (2D URANS sections, time means): Cp and signed Cf
along the whole wall, the stagnation point, every separation and reattachment, suction peaks, base pressure,
and pressure drag and lift by face, for every complete Stage 2 run and the smooth Stage 1 SST runs.

    nice -n 10 python3 cfd/analysis/2026-11-15/src/surface_extract.py                 # about 20 s, 4 processes
    nice -n 10 python3 cfd/analysis/2026-11-15/src/surface_extract.py --only tex0.200 --no-write   # a subset

Why
  Dr. Jahangiri's 1 Nov questions J3 (separation, pressure distribution, lift and drag) and J4 (why the gain
  appears at Ks 400 um). The 15 Oct script (cfd/analysis/2026-10-15/src/roughness_surface.py) read only the 11
  alpha-180 texture runs at maxCo 2.5 and located separation on the convex face only; the records' surface
  tables cover part of the wall (render_fields.py walks one closed loop per patch, cfd/stage2/README.md
  section 8). This script reads all 69 Stage 2 runs (wall-function and texture meshes, alpha 0, 90, 180) and
  the 5 smooth Stage 1 runs (medium mesh, SST, 23 m/s, alpha 0/90/180, maxCo 2.5 and 1.25), orders the whole
  wall into one loop in both layouts (Stage 2: patches 'blade' + 'bladeEnds'; Stage 1: one closed 'blade'
  patch, split at the four corners), and on textured walls judges flow reversal from the time-mean velocity
  above the texture, not from the facet-scale wall shear. Existing runs only: the verification runs submitted
  on 15 Nov (B1) have not finished, so the mesh and time-step errors of these numbers are still open.

Reads (read only)
  cfd/stage2/runs/<case>/ (every 'a*' folder whose results.json says complete) and
  cfd/section2d/runs/a{000,090,180}.0_U23.0_SST_medium_Tu1.0_Co{2.5,1.25}n2/:
      constant/polyMesh/{points,faces,owner,boundary}; <final time>/{pMean,wallShearStressMean,UMean}
      (fieldAverage means from averageStart: the window of the results table); case.json, mesh_info.json
      (frame: the four corners), results.json (complete flag; force means, checks only)
  cfd/analysis/2026-10-15/src/roughness_surface.py   imported, not edited: binary readers, face_geometry,
      first_reversed, SEP_MIN
  cfd/analysis/2026-10-15/out/roughness_surface_summary.csv   15 Oct numbers, checks only
Writes
  ../out/surface_summary.csv           one row per case (74): force check, pressure drag and lift by face,
                                       stagnation point, suction peaks, base and face-mean pressure, separation
                                       (15 Oct definition and every branch), the reversal basis
  ../out/surface_profiles.csv          one wall face per 0.5 mm of arc (the first face in each 0.5-mm bin):
                                       face, s/c, loop/c, Cp, Cf and their 1-mm means; texture meshes also u/U
                                       at 0.25 mm (u025_1mm) and, on textured walls, the reversal basis u_d
                                       (ud_1mm); the figure uses every face
  ../out/surface_reversal.csv          every persistent sign change (S, R) and the stagnation point (A): face,
                                       s/c, loop/c, distance from the stagnation point, branch
  ../out/surface_reversal_heights.csv  texture meshes only: the first separation on each branch and the number
                                       of changes when reversal is judged from u at d = 0 (Cf, t = 0 only) and
                                       at d = 0.10-0.40 mm (t = 0) or t + 0.05, t + 0.10, t + 0.20 mm (t > 0)
  ../out/surface_check.csv             every check: reference and its source, recomputed value, tolerance,
                                       pass; kind 'validation' (the script exits 1 if one fails) or 'diagnostic'
  ../fig/surface_cp_cf.png             Cp, Cf and the textured-wall reversal basis around the blade at alpha 0,
                                       90, 180 (SST, 23 m/s, maxCo 2.5): Ks 0 and 400 um (wall functions),
                                       t 0 and 0.20 mm (texture mesh)

Conventions
  Body frame of the mesh (mesh_info.json 'frame'); free stream along dragDir (case.json). alpha 0: cup (concave
  face) to the wind; 180: convex face to the wind; 90: edge-on, tip A upstream (cfd/section2d/README.md).
  Faces: convex (outer surface, corner A_outer to B_outer), concave (inner, A_inner to B_inner), endA (A_outer to
  A_inner), endB (B_outer to B_inner). Stage 2: convex + concave = patch 'blade' (painted), the ends = patch
  'bladeEnds' (checked for every case); Stage 1: patch 'blade' split at the corners, which are mesh vertices
  (found within 1e-9 m).
  s/c: arc length along each face from its first corner (tip A for convex and concave, the outer corner for
  the ends) to the face centre, along the wall polyline, over c = 48 mm. Texture meshes (t > 0) use the smooth
  t = 0 mesh of the same alpha, seed and nseg: the same faces in the same order, centres within t + 2 um
  (checked, every case). loop/c: one coordinate round the wall, A_outer -> convex -> B_outer -> endB ->
  B_inner -> concave -> A_inner -> endA -> A_outer (face lengths 1.492, 0.039, 1.364, 0.039 c; 2.933 c in all).
  Cp = pMean / (0.5 U^2), kinematic, p_inf = 0 (the far-field value, cfd/docs/RECORDS.md). The time-mean
  stagnation Cp is 0.996-1.084 (alpha 90: 1.00-1.01; 180: 1.02-1.03; 0, in the cup: 1.04-1.08;
  surface_summary.csv Cp_stag_1mm), and the total pressure above the windward boundary layer 1.01-1.06 q
  (bl_stations.csv P0_over_q), so Cp = 1 is not the stagnation value of these runs.
  Cf = |tau_w . t| / (0.5 U^2) with t the smooth-wall tangent along +s, signed + where the owner-cell UMean runs
  along +s (the 15 Oct convention).
  1-mm means: the length-weighted mean over the faces within +-0.5 mm of arc, within one face (not across a
  corner). On the texture meshes (faces 40 um long) this is the 15 Oct 25-face running mean.
  Stagnation point: the maximum of the 1-mm Cp over the whole wall, where the near-wall flow diverges within 1 mm of
  it (53 runs). In the cup at alpha 0 the maximum is flat (the 1-mm Cp within 0.01 of it over 0.97-1.06 c of wall,
  against 0.02-0.07 c at alpha 90 and 180; Cp_flat_max_over_c) and in 21 runs the flow does not diverge at its
  arbitrary peak: there the stagnation point is the divergence point of the reversal basis inside that flat region
  with the highest Cp (stag_rule; Cp_max_* keep the peak; the two lie 0.03 c apart on the low-Re meshes and up to
  0.45 c on the wall-function meshes). Branches A and B run from it round the loop toward tip A and tip B to the
  point half-way round (for a stagnation point on an end face, A runs onto the concave and B onto the convex face;
  none occurs). Attached = near-wall flow away from the stagnation point.
  Reversal basis: smooth walls (wall-function, Stage 1, texture t = 0): the signed Cf. Textured walls (t > 0):
  u_d, the tangential UMean at d = t + 0.05 mm from the smooth wall along its normal, above every crest
  (|delta| <= t); linear interpolation in a Delaunay triangulation of the cell centres (exact 2D centroids)
  within 3 mm of the wall and the wall-face centres (U = 0). The textured wall's shear is not used: it reverses
  in the valleys at the facet scale (15 Oct: the 1-mm mean reverses at the same two ridge groups in every
  t-0.20 run, 0.192 and 0.146 c from the stagnation point; recomputed here as a diagnostic, sepCf_*).
  Sign changes: walking a branch from the stagnation point, the first stretch of at least 0.5 mm (SEP_MIN) with
  the opposite sign of the 1-mm basis is a separation (S) if it reverses attached flow and a reattachment (R) if
  it restores it; the first 1 mm is skipped (roughness_surface.first_reversed, extended to every change and past
  the corners). Beyond the first S the labels give the near-wall flow direction relative to the stagnation
  point; in a wake they do not imply a boundary layer.
  sep_{A,B}_from_stag_over_c: the 15 Oct definition, the first S on the stagnation face before its tip
  (first_reversed on that face), NaN if none; first_S_{A,B}_*: the first S on the branch, on any face.
  Suction peaks: the minimum of the 1-mm Cp on each face, and between the stagnation point and each tip.
  Base pressure: the length-weighted mean Cp of the leeward long face, the one whose area-mean normal into the
  fluid points most downstream (cosine with dragDir above 0.3; none at alpha 90). Every face's mean is listed.
  Pressure drag and lift: Cd_p = sum(p Sf . dragDir) / (0.5 U^2 Aref), Cl_p with liftDir, Sf out of the fluid (as
  the forces function object), Aref = c dz; the stagnation face is split at the stagnation point, its own face
  shared half and half. Checks: the sum over the four faces against results.json Cd_pressure_mean (same window), and
  pressure + viscous (-tau_w |Sf|) against Cd_mean and Cl_mean. The table's means come from the force history
  written every 0.02 c/U, the fields' from every time step; Cd_pressure differs by at most 0.07 %
  (a180.0_U23.0_SST_medium_Tu1.0_Co2.5n2), except 0.13 % in the strongly shedding
  a000.0_U23.0_LM_tex0.000_s1_Tu1.0_Co2.5n2 (the one alpha-0 texture run in the high-drag state, Cd 2.81). The 15
  Oct comparison uses the 6-digit rounding of that CSV as tolerance, except for two documented definition changes
  (stagnation-face halves: 5e-4; s from the corner: 4e-4 c).
"""
import argparse
import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parents[2]
S2_RUNS = REPO / "cfd" / "stage2" / "runs"
S1_RUNS = REPO / "cfd" / "section2d" / "runs"
OUT, FIG = ROOT / "out", ROOT / "fig"
OCT15 = REPO / "cfd" / "analysis" / "2026-10-15"
sys.dont_write_bytecode = True        # import the 15 Oct modules without writing into their folder
sys.path.insert(0, str(OCT15 / "src"))
import roughness_surface as RS  # noqa: E402  (readers and the 15 Oct separation rule; read only)

C_REF = 0.048
NU = 1.516e-5
WIN = 1.0e-3                  # m, the running-mean window (+-0.5 mm)
SEP_MIN = RS.SEP_MIN          # 0.5 mm persistence
STAG_SKIP = 1.0e-3            # as RS.first_reversed
ABOVE_CREST = 0.05e-3         # m: textured walls, u_d at d = t + 0.05 mm
HEIGHTS_T0 = (0.10e-3, 0.15e-3, 0.20e-3, 0.25e-3, 0.30e-3, 0.40e-3)
HEIGHTS_TEX = (0.05e-3, 0.10e-3, 0.20e-3)       # added to t
COMMON_H = 0.25e-3            # m: u/U at one height on every texture mesh (above every t <= 0.20 crest)
SAMPLE_BAND = 3.0e-3          # m, cells within this distance of the wall enter the triangulation
PROFILE_DS = 0.5e-3           # m, profile decimation (two points per 1-mm window)
FACES = ("convex", "endB", "concave", "endA")
LOOP_DIR = {"convex": +1, "endB": +1, "concave": -1, "endA": -1}   # face +s relative to the loop direction
CORNERS = ("A_outer", "B_outer", "B_inner", "A_inner")
S1_PATTERN = re.compile(r"a(000|090|180)\.0_U23\.0_SST_medium_Tu1\.0_Co(2\.5|1\.25)n2")


# ------------------------------------------------------------------ cases
def discover():
    """All complete Stage 2 runs (wf and tex walls, alpha 0, 90, 180) and the 5 Stage 1 runs."""
    cases = []
    for d in sorted(S2_RUNS.iterdir()):
        if not (d.is_dir() and d.name.startswith("a") and (d / "results.json").exists()):
            continue
        R = json.loads((d / "results.json").read_text())
        P = json.loads((d / "case.json").read_text())
        if R.get("complete") is True and P.get("wall") in ("wf", "tex") and round(P["alphaDeg"]) in (0, 90, 180):
            cases.append(dict(name=d.name, dir=str(d), stage=2))
    for d in sorted(S1_RUNS.iterdir()):
        if S1_PATTERN.fullmatch(d.name) and json.loads((d / "results.json").read_text()).get("complete") is True:
            cases.append(dict(name=d.name, dir=str(d), stage=1))
    # texture meshes: the reference geometry is the t = 0 mesh of the same alpha, seed and nseg
    refs = {}
    for c in cases:
        P = json.loads((Path(c["dir"]) / "case.json").read_text())
        c["key"] = (P.get("wall"), round(P["alphaDeg"]), P.get("texSeed"), P.get("texNseg"))
        if P.get("wall") == "tex" and P["texT"] == 0:
            refs.setdefault(c["key"], c["dir"])
    for c in cases:
        c["ref"] = refs[c["key"]] if c["key"][0] == "tex" else c["dir"]
    return cases


# ------------------------------------------------------------------ mesh
def load_mesh(d):
    pm = Path(d) / "constant" / "polyMesh"
    return dict(pts=RS.read_list(pm / "points", "<f8", 3), faces=RS.read_faces(pm / "faces"),
                owner=RS.read_list(pm / "owner", "<i4"), bnd=RS.read_boundary(pm / "boundary"))


def wall_loop(M, corners):
    """Order the wall faces (patches 'blade' and 'bladeEnds' where present) into one closed loop and split it at
    the four corners. Returns {face: dict(patch, pidx, g, P0, P1)} with the faces in walk order from the face's
    first corner; P0, P1 are the 2D end points of each wall face along the walk."""
    pts, (off, lab), bnd = M["pts"], M["faces"], M["bnd"]
    zmid = np.median(pts[:, 2])
    patches = [p for p in ("blade", "bladeEnds") if p in bnd]
    g = np.concatenate([np.arange(bnd[p][0], bnd[p][0] + bnd[p][1]) for p in patches])
    pname = np.concatenate([np.full(bnd[p][1], p) for p in patches])
    pidx = np.concatenate([np.arange(bnd[p][1]) for p in patches])
    segs = np.zeros((len(g), 2), np.int64)
    for i, f in enumerate(g):
        fp = lab[off[f]:off[f + 1]]
        low = fp[pts[fp, 2] < zmid]
        if len(low) != 2:
            raise RuntimeError("a wall face without exactly two low-z points")
        segs[i] = low
    key, canon = {}, {}
    for p in np.unique(segs):
        canon[p] = key.setdefault((round(float(pts[p, 0]), 10), round(float(pts[p, 1]), 10)), p)
    segs = np.vectorize(canon.get)(segs)
    p2f = {}
    for i, (a, b) in enumerate(segs):
        p2f.setdefault(a, []).append(i)
        p2f.setdefault(b, []).append(i)
    if any(len(v) != 2 for v in p2f.values()):
        raise RuntimeError("the wall is not one closed loop")
    wp = np.array(list(p2f))
    cpt = {}
    for k in CORNERS:
        dd = np.linalg.norm(pts[wp, :2] - np.asarray(corners[k]), axis=1)
        j = int(np.argmin(dd))
        if dd[j] > 1e-9:
            raise RuntimeError(f"corner {k} is not a wall vertex ({dd[j]:.2e} m)")
        cpt[k] = int(wp[j])
    corner_of = {v: k for k, v in cpt.items()}

    def walk(start, first):
        order, verts, cur, via = [], [start], first, start
        while True:
            order.append(cur)
            a, b = segs[cur]
            via = b if a == via else a
            verts.append(via)
            if via in corner_of:
                return np.array(order), np.array(verts), corner_of[via]
            cur = next(f for f in p2f[via] if f != cur)

    want = {("A_outer", "B_outer"): "convex", ("A_outer", "A_inner"): "endA",
            ("B_outer", "B_inner"): "endB", ("A_inner", "B_inner"): "concave"}
    out = {}
    for start in ("A_outer", "B_outer", "A_inner"):
        for f0 in p2f[cpt[start]]:
            order, verts, end = walk(cpt[start], f0)
            face = want.get((start, end))
            if face:
                out[face] = dict(patch=pname[order], pidx=pidx[order], g=g[order],
                                 P0=pts[verts[:-1], :2], P1=pts[verts[1:], :2])
    if set(out) != set(FACES) or sum(len(v["g"]) for v in out.values()) != len(g):
        raise RuntimeError(f"loop split failed: {sorted(out)}")
    if "bladeEnds" in bnd:          # Stage 2: the split must agree with the patches
        for f, v in out.items():
            if set(v["patch"]) != {"bladeEnds" if f.startswith("end") else "blade"}:
                raise RuntimeError(f"face {f} mixes patches")
    return out


def face_frames(M, W):
    """Per face: centres, area vectors (out of the fluid), lengths, arc length to the face centres, unit tangent
    along +s and unit normal into the fluid."""
    pts, (off, lab) = M["pts"], M["faces"]
    G = {}
    for f, v in W.items():
        _, Sf, cen = RS.face_geometry(pts, off, lab, v["g"])
        d = v["P1"] - v["P0"]
        ln = np.linalg.norm(d, axis=1)
        G[f] = dict(cen=cen[:, :2], Sf=Sf[:, :2], ln=ln, s=np.cumsum(ln) - ln / 2, L=float(ln.sum()),
                    tng=d / ln[:, None], nin=-Sf[:, :2] / np.linalg.norm(Sf[:, :2], axis=1)[:, None])
    return G


def cell_centres(M):
    """Exact 2D cell centroids: the polygon centroid of each cell's low-z face on the empty patch."""
    pts, (off, lab), owner, bnd = M["pts"], M["faces"], M["owner"], M["bnd"]
    patch = next(p for p in bnd if p.lower().startswith("frontandback"))
    s0, nf = bnd[patch]
    f = np.arange(s0, s0 + nf)
    nv = off[f + 1] - off[f]
    zmid = np.median(pts[:, 2])
    C = np.full((int(owner.max()) + 1, 2), np.nan)
    for k in np.unique(nv):
        ff = f[nv == k]
        Pk = pts[lab[off[ff][:, None] + np.arange(k)[None, :]]]
        low = Pk[:, 0, 2] < zmid
        Pk, ff = Pk[low], ff[low]
        x, y = Pk[..., 0], Pk[..., 1]
        x1, y1 = np.roll(x, -1, axis=1), np.roll(y, -1, axis=1)
        cr = x * y1 - x1 * y
        A = 0.5 * cr.sum(1)
        C[owner[ff]] = np.c_[((x + x1) * cr).sum(1) / (6 * A), ((y + y1) * cr).sum(1) / (6 * A)]
    if np.isnan(C).any():
        raise RuntimeError("cells without a low-z face")
    return C


def wall_sampler(C, values, G, wall_values=None, band=SAMPLE_BAND):
    """Linear interpolator of cell values near the wall: Delaunay triangulation of the cell centres within
    'band' of a wall-face centre plus the wall-face centres themselves (value wall_values, default 0)."""
    from scipy.interpolate import LinearNDInterpolator
    from scipy.spatial import Delaunay, cKDTree
    wall = np.vstack([G[f]["cen"] for f in FACES])
    keep = cKDTree(wall).query(C, k=1)[0] < band
    wv = np.zeros((len(wall), values.shape[1])) if wall_values is None else wall_values
    return LinearNDInterpolator(Delaunay(np.r_[C[keep], wall]), np.r_[values[keep], wv])


def final_time(d, P):
    tdirs = [p for p in Path(d).iterdir() if re.fullmatch(r"[0-9.]+", p.name) and float(p.name) > 0]
    T = max(tdirs, key=lambda p: float(p.name))
    if abs(float(T.name) - P["endTime"]) > 1e-6 * P["endTime"]:
        raise RuntimeError(f"{d}: final time {T.name} is not endTime {P['endTime']}")
    return T


# ------------------------------------------------------------------ 1-D helpers
def arc_mean(y, s, w, win=WIN):
    """Length-weighted running mean over +-win/2 of arc (y on faces at arc positions s with lengths w)."""
    cw = np.r_[0.0, np.cumsum(w)]
    cy = np.r_[0.0, np.cumsum(w * y)]
    lo = np.searchsorted(s, s - win / 2 - 1e-12, side="left")
    hi = np.searchsorted(s, s + win / 2 + 1e-12, side="right")
    return (cy[hi] - cy[lo]) / (cw[hi] - cw[lo])


def scan(dist, v, skip=STAG_SKIP, min_len=SEP_MIN):
    """Persistent sign changes along a walk from the stagnation point; v > 0 is attached (flow away from the
    stagnation point). Returns [(index, 'S' or 'R')]: the first index of each stretch of at least min_len
    whose sign is opposite to the current state (stretch length from its first point to the first point after
    it, or to the last point: roughness_surface.first_reversed)."""
    sg = np.sign(v)
    ok = dist > skip
    out, state, k, n = [], 1.0, 0, len(v)
    while k < n:
        if ok[k] and sg[k] == -state:
            j = k
            while j < n and ok[j] and sg[j] == -state:
                j += 1
            if dist[min(j, n - 1)] - dist[k] >= min_len:
                out.append((k, "S" if state > 0 else "R"))
                state = -state
            k = j
            continue
        k += 1
    return out


def divergences(lpos, v, Ltot, min_len=SEP_MIN):
    """Loop indices where the near-wall flow diverges: a stretch of v < 0 (flow against the loop direction) followed
    along the loop by a stretch of v >= 0, both at least min_len long (the loop is closed)."""
    sg = np.where(v >= 0, 1, -1)
    n = len(sg)
    st = np.where(sg != np.roll(sg, 1))[0]
    if len(st) == 0:
        return []
    en = np.r_[st[1:], st[0] + n]

    def length(a, b):
        return (lpos[b % n] - lpos[a]) % Ltot

    return [int(a) for i, a in enumerate(st)
            if sg[a] > 0 and length(a, en[i]) >= min_len and length(st[i - 1], a) >= min_len]


def flat_max(Cp_loop, kmax, tol=0.01):
    """Mask of the contiguous loop stretch round kmax where the 1-mm Cp is within tol of its maximum."""
    n = len(Cp_loop)
    hi = Cp_loop >= Cp_loop[kmax] - tol
    m = np.zeros(n, bool)
    m[kmax] = True
    for step in (1, -1):
        k = (kmax + step) % n
        while hi[k] and not m[k]:
            m[k] = True
            k = (k + step) % n
    return m


def decimate(s, ds=PROFILE_DS):
    b = np.floor(s / ds).astype(int)
    return np.r_[True, b[1:] != b[:-1]]


# ------------------------------------------------------------------ one case
def analyse(case):
    d = Path(case["dir"])
    name = case["name"]
    P = json.loads((d / "case.json").read_text())
    R = json.loads((d / "results.json").read_text())
    corners = json.loads((d / "mesh_info.json").read_text())["frame"]["corners_body_m"]
    T = final_time(d, P)
    U, q = P["Uinf"], 0.5 * P["Uinf"] ** 2
    drag, lift = np.array(P["dragDir"][:2]), np.array(P["liftDir"][:2])
    Aref = P["Aref"]
    t_tex = float(P.get("texT", 0.0)) if P.get("wall") == "tex" else 0.0
    M = load_mesh(d)
    W = wall_loop(M, corners)
    G = face_frames(M, W)                                   # this mesh: forces
    if case["ref"] != case["dir"]:
        Mr = load_mesh(case["ref"])
        Gr = face_frames(Mr, wall_loop(Mr, corners))        # smooth reference: s, t, n, lengths
    else:
        Gr = G
    off_max = 0.0
    for f in FACES:
        if len(Gr[f]["s"]) != len(G[f]["s"]):
            raise RuntimeError(f"{name}: face {f} has {len(G[f]['s'])} faces, reference {len(Gr[f]['s'])}")
        off_max = max(off_max, float(np.abs(G[f]["cen"] - Gr[f]["cen"]).max()))
    if off_max > t_tex + 2e-6:
        raise RuntimeError(f"{name}: wall faces do not match the reference mesh ({off_max:.2e} m)")
    family = "stage1" if case["stage"] == 1 else P["wall"]
    row = dict(name=name, stage=case["stage"], family=family, model=P.get("model", "SST"), alpha_deg=P["alphaDeg"],
               U=U, maxCo=P["maxCo"], nconv=P["nConv"], navg=P["nAvg"], Ks_um=round(P.get("KsBlade", 0.0) * 1e6, 3),
               t_mm=round(t_tex * 1e3, 3), t_field_s=float(T.name), avg_from_c_U=float(R["avg_from_conv"]),
               avg_to_c_U=float(R["avg_to_conv"]), ref_case=Path(case["ref"]).name, wall_offset_max_um=off_max * 1e6)
    for f in FACES:
        row[f"len_{f}_over_c"] = Gr[f]["L"] / C_REF
        row[f"n_faces_{f}"] = len(G[f]["s"])

    # fields
    Um = RS.internal_values(T / "UMean", 3)[:, :2]
    pat = {pa: (RS.patch_values(T / "pMean", pa, 1), RS.patch_values(T / "wallShearStressMean", pa, 3)[:, :2])
           for pa in {p for f in FACES for p in W[f]["patch"]}}
    D = {}
    Fp, Fv = np.zeros(2), np.zeros(2)
    for f in FACES:
        p = np.array([pat[pa][0][i] for pa, i in zip(W[f]["patch"], W[f]["pidx"])])
        tau = np.array([pat[pa][1][i] for pa, i in zip(W[f]["patch"], W[f]["pidx"])])
        own = M["owner"][W[f]["g"]]
        tng, s, ln = Gr[f]["tng"], Gr[f]["s"], Gr[f]["ln"]
        sign = np.sign(np.sum(Um[own] * tng, axis=1))
        Cp = p / q
        Cf = sign * np.abs(np.sum(tau * tng, axis=1)) / q
        fp = p[:, None] * G[f]["Sf"]
        fv = -tau * np.linalg.norm(G[f]["Sf"], axis=1)[:, None]
        Fp += fp.sum(0)
        Fv += fv.sum(0)
        D[f] = dict(s=s, ln=ln, Cp=Cp, Cf=Cf, fp=fp, Cp_1mm=arc_mean(Cp, s, ln), Cf_1mm=arc_mean(Cf, s, ln))
        row[f"Cd_p_{f}"] = float(fp.sum(0) @ drag / (q * Aref))
        row[f"Cl_p_{f}"] = float(fp.sum(0) @ lift / (q * Aref))
        row[f"Cp_mean_{f}"] = float(np.average(Cp, weights=ln))
    row.update(Cd_p_fields=float(Fp @ drag / (q * Aref)), Cd_p_table=float(R["Cd_pressure_mean"]),
               Cd_v_fields=float(Fv @ drag / (q * Aref)), Cd_v_table=float(R["Cd_viscous_mean"]),
               Cd_fields=float((Fp + Fv) @ drag / (q * Aref)), Cd_table=float(R["Cd_mean"]),
               Cl_fields=float((Fp + Fv) @ lift / (q * Aref)), Cl_table=float(R["Cl_mean"]))
    row["Cd_p_rel_err"] = row["Cd_p_fields"] / row["Cd_p_table"] - 1

    # reversal basis: Cf on smooth walls; u_d above the texture on textured walls
    heights = []
    samp = None
    if family == "tex":
        C = cell_centres(M)
        samp = wall_sampler(C, Um, Gr)
        heights = list(HEIGHTS_T0) if t_tex == 0 else [t_tex + h for h in HEIGHTS_TEX]

    def u_at(f, h):
        X = Gr[f]["cen"] + h * Gr[f]["nin"]
        u = samp(X)
        if np.isnan(u).any():
            raise RuntimeError(f"{name}: sample points outside the triangulation ({f}, d {h * 1e3:.3f} mm)")
        return np.sum(u * Gr[f]["tng"], axis=1) / U

    basis_h = t_tex + ABOVE_CREST if t_tex > 0 else 0.0
    for f in FACES:
        D[f]["rev_1mm"] = (arc_mean(u_at(f, basis_h), D[f]["s"], D[f]["ln"]) if t_tex > 0 else D[f]["Cf_1mm"])
        D[f]["u025_1mm"] = (arc_mean(u_at(f, COMMON_H), D[f]["s"], D[f]["ln"]) if family == "tex"
                            else np.full(len(D[f]["s"]), np.nan))
    row["reversal_basis"] = f"u at {basis_h * 1e3:.2f} mm" if t_tex > 0 else "Cf"

    # loop arrays
    offs, acc = {}, 0.0
    for f in FACES:
        offs[f] = acc
        acc += Gr[f]["L"]
    Ltot = acc
    lf, li, lpos = [], [], []
    for f in FACES:
        n = len(D[f]["s"])
        idx = np.arange(n) if LOOP_DIR[f] > 0 else np.arange(n)[::-1]
        lf += [f] * n
        li.append(idx)
        lpos.append(offs[f] + (D[f]["s"][idx] if LOOP_DIR[f] > 0 else Gr[f]["L"] - D[f]["s"][idx]))
        D[f]["loop"] = offs[f] + (D[f]["s"] if LOOP_DIR[f] > 0 else Gr[f]["L"] - D[f]["s"])
    lf, li, lpos = np.array(lf), np.concatenate(li), np.concatenate(lpos)

    def loop_vals(key, signed):
        return np.array([D[f][key][i] * (LOOP_DIR[f] if signed else 1) for f, i in zip(lf, li)])

    # stagnation point: the maximum of the 1-mm Cp, unless the near-wall flow does not diverge within 1 mm of it
    Cp_loop = loop_vals("Cp_1mm", False)
    kmax = int(np.argmax(Cp_loop))
    div = divergences(lpos, loop_vals("rev_1mm", True), Ltot)
    plateau = flat_max(Cp_loop, kmax)
    if any(min(abs(lpos[k] - lpos[kmax]), Ltot - abs(lpos[k] - lpos[kmax])) <= STAG_SKIP for k in div):
        k0, rule = kmax, "max Cp"
    elif any(plateau[k] for k in div):
        k0 = max((k for k in div if plateau[k]), key=lambda k: Cp_loop[k])
        rule = "flow divergence in the flat Cp maximum"
    else:
        k0, rule = kmax, "max Cp (no flow divergence near it)"
    fs, is_ = str(lf[k0]), int(li[k0])
    row.update(stag_face=fs, stag_s_over_c=D[fs]["s"][is_] / C_REF, stag_loop_over_c=lpos[k0] / C_REF,
               Cp_stag_1mm=float(Cp_loop[k0]), stag_rule=rule, Cp_max_1mm=float(Cp_loop[kmax]),
               Cp_max_face=str(lf[kmax]), Cp_max_s_over_c=D[lf[kmax]]["s"][li[kmax]] / C_REF,
               Cp_flat_max_over_c=float(np.sum(np.r_[np.diff(lpos), Ltot - lpos[-1] + lpos[0]][plateau]) / C_REF),
               n_divergences=len(div), Cp_max_raw=float(max(D[f]["Cp"].max() for f in FACES)))
    # branches: '+' follows the loop direction
    plus_is = {"convex": "B", "endB": "B", "concave": "A", "endA": "B"}[fs]

    def branch(sign):
        dist = ((lpos - lpos[k0]) * sign) % Ltot
        order = np.argsort(dist, kind="stable")
        order = order[dist[order] <= Ltot / 2]
        return order, dist[order]

    events = [dict(name=name, face=fs, s_over_c=D[fs]["s"][is_] / C_REF, loop_over_c=lpos[k0] / C_REF,
                   from_stag_over_c=0.0, branch="", type="A")]

    def walk_events(key, extra=None):
        ev, first = [], {}
        for sign in (+1, -1):
            br = plus_is if sign > 0 else ("A" if plus_is == "B" else "B")
            order, dist = branch(sign)
            v = loop_vals(key, True)[order] * sign
            for k, typ in scan(dist, v):
                j = order[k]
                e = dict(name=name, face=str(lf[j]), s_over_c=D[lf[j]]["s"][li[j]] / C_REF,
                         loop_over_c=lpos[j] / C_REF, from_stag_over_c=dist[k] / C_REF, branch=br, type=typ)
                if extra:
                    e.update(extra)
                ev.append(e)
                if typ == "S" and br not in first:
                    first[br] = e
        return ev, first

    ev, first = walk_events("rev_1mm")
    events += ev
    for br in ("A", "B"):
        e = first.get(br)
        row[f"first_S_{br}_face"] = e["face"] if e else ""
        row[f"first_S_{br}_s_over_c"] = e["s_over_c"] if e else np.nan
        row[f"first_S_{br}_loop_over_c"] = e["loop_over_c"] if e else np.nan
        row[f"first_S_{br}_from_stag_over_c"] = e["from_stag_over_c"] if e else np.nan
    for f in ("convex", "concave"):
        mine = [e for e in ev if e["face"] == f]
        row[f"n_S_{f}"] = sum(e["type"] == "S" for e in mine)
        row[f"n_R_{f}"] = sum(e["type"] == "R" for e in mine)
        row[f"changes_{f}"] = ";".join(f"{e['type']}{e['s_over_c']:.3f}"
                                       for e in sorted(mine + [x for x in events[:1] if x["face"] == f],
                                                       key=lambda e: e["s_over_c"]))
    row["changes_ends"] = ";".join(f"{e['face']}:{e['type']}{e['s_over_c']:.3f}"
                                   for e in ev if e["face"].startswith("end"))

    # 15 Oct definitions on the stagnation face (convex or concave)
    if fs in ("convex", "concave"):
        s, n = D[fs]["s"], len(D[fs]["s"])
        half = {"A": np.arange(is_, -1, -1), "B": np.arange(is_, n)}
        for side, idx in half.items():
            att = -1 if side == "A" else 1
            ss = s[idx]
            row[f"dist_{side}_to_tip_over_c"] = (s[is_] if side == "A" else Gr[fs]["L"] - s[is_]) / C_REF
            row[f"Cp_min_{side}_1mm"] = float(D[fs]["Cp_1mm"][idx].min())
            row[f"Cp_min_{side}_from_stag_over_c"] = abs(ss[int(np.argmin(D[fs]["Cp_1mm"][idx]))] - ss[0]) / C_REF
            row[f"sep_{side}_from_stag_over_c"] = RS.first_reversed(D[fs]["rev_1mm"][idx], ss, att, C_REF)
            row[f"sepCf_{side}_from_stag_over_c"] = RS.first_reversed(D[fs]["Cf_1mm"][idx], ss, att, C_REF)
            fp = D[fs]["fp"]
            part = fp[idx[1:]].sum(0) + 0.5 * fp[is_]
            row[f"Cd_p_stagface_{side}"] = float(part @ drag / (q * Aref))
    for f in ("convex", "concave"):
        k = int(np.argmin(D[f]["Cp_1mm"]))
        row[f"Cp_min_{f}_1mm"] = float(D[f]["Cp_1mm"][k])
        row[f"Cp_min_{f}_s_over_c"] = D[f]["s"][k] / C_REF
    # base face
    cosd = {}
    for f in ("convex", "concave"):
        nm = (G[f]["nin"] * np.linalg.norm(G[f]["Sf"], axis=1)[:, None]).sum(0)
        cosd[f] = float(nm @ drag / np.linalg.norm(nm))
    fb = max(cosd, key=cosd.get)
    row["base_face"] = fb if cosd[fb] > 0.3 else ""
    row["base_face_cos"] = cosd[fb]
    row["Cp_base_mean"] = row[f"Cp_mean_{fb}"] if cosd[fb] > 0.3 else np.nan

    # textured walls and their references: reversal judged at several heights
    hrows = []
    if family == "tex":
        bases = ([(0.0, "Cf")] if t_tex == 0 else []) + [(h, f"u at {h * 1e3:.2f} mm") for h in heights]
        for h, lab in bases:
            if h > 0:
                for f in FACES:
                    D[f]["_h"] = arc_mean(u_at(f, h), D[f]["s"], D[f]["ln"])
                ev_h, first_h = walk_events("_h")
            else:
                ev_h, first_h = walk_events("Cf_1mm")
            hr = dict(name=name, model=row["model"], alpha_deg=row["alpha_deg"], U=U, maxCo=row["maxCo"],
                      nconv=row["nconv"], t_mm=row["t_mm"], d_mm=round(h * 1e3, 3),
                      d_minus_t_mm=round((h - t_tex) * 1e3, 3), basis=lab, primary=bool(abs(h - basis_h) < 1e-9))
            for br in ("A", "B"):
                e = first_h.get(br)
                hr[f"first_S_{br}_face"] = e["face"] if e else ""
                hr[f"first_S_{br}_s_over_c"] = e["s_over_c"] if e else np.nan
                hr[f"first_S_{br}_from_stag_over_c"] = e["from_stag_over_c"] if e else np.nan
            hr["n_changes"] = len(ev_h)
            hr["changes"] = ";".join(f"{e['face']}:{e['type']}{e['s_over_c']:.3f}" for e in ev_h)
            hrows.append(hr)

    # profiles at every face (decimated when written)
    prof = []
    for f in FACES:
        prof.append(pd.DataFrame(dict(name=name, face=f, s_over_c=D[f]["s"] / C_REF, loop_over_c=D[f]["loop"] / C_REF,
                                      Cp=D[f]["Cp"], Cf=D[f]["Cf"], Cp_1mm=D[f]["Cp_1mm"], Cf_1mm=D[f]["Cf_1mm"],
                                      ud_1mm=D[f]["rev_1mm"] if t_tex > 0 else np.nan, u025_1mm=D[f]["u025_1mm"],
                                      keep=decimate(D[f]["s"]))))
    return row, pd.concat(prof, ignore_index=True), events, hrows


# ------------------------------------------------------------------ checks
def g6(x):
    """Half a unit in the 6th significant digit: the rounding of a CSV written with %.6g."""
    x = float(x)
    return 0.0 if not np.isfinite(x) or x == 0 else 0.5 * 10 ** (np.floor(np.log10(abs(x))) - 5)


def checks(S):
    rows = []

    def add(check, case, ref, source, value, tol, kind="validation", note=""):
        both_nan = bool(np.isnan(ref) and np.isnan(value))
        ok = both_nan or bool(np.isfinite(ref) and np.isfinite(value) and abs(value - ref) <= tol)
        rows.append(dict(check=check, case=case, reference=ref, source=source, value=value, tolerance=tol,
                         passed=ok, kind=kind, note=note))

    for r in S.itertuples():
        add("Cd_pressure: fields against the table (1 %)", r.name, r.Cd_p_table, "results.json Cd_pressure_mean",
            r.Cd_p_fields, 0.01 * abs(r.Cd_p_table))
        add("Cd: pressure + viscous against the table (1 % or 2e-3)", r.name, r.Cd_table, "results.json Cd_mean",
            r.Cd_fields, max(0.01 * abs(r.Cd_table), 2e-3))
        add("Cl: pressure + viscous against the table (1 % or 2e-3)", r.name, r.Cl_table, "results.json Cl_mean",
            r.Cl_fields, max(0.01 * abs(r.Cl_table), 2e-3))
        add("sum of the face pressure drags = the total", r.name, r.Cd_p_fields, "this script",
            r.Cd_p_convex + r.Cd_p_concave + r.Cd_p_endA + r.Cd_p_endB, 1e-9)
        if r.stag_face in ("convex", "concave"):
            add("stagnation-face halves sum to the face", r.name, getattr(r, f"Cd_p_{r.stag_face}"), "this script",
                r.Cd_p_stagface_A + r.Cd_p_stagface_B, 1e-9)
    # the 15 Oct numbers (same runs, same fields, same window)
    old = pd.read_csv(OCT15 / "out" / "roughness_surface_summary.csv").set_index("name")
    src = "2026-10-15/out/roughness_surface_summary.csv"
    Si = S.set_index("name")
    for n, o in old.iterrows():
        if n not in Si.index:
            add("15 Oct case present", n, 1.0, src, 0.0, 0.0)
            continue
        r = Si.loc[n]
        for col, mine, tol, note in (
                ("Cd_p_convex", "Cd_p_convex", 1e-6, ""), ("Cd_p_concave", "Cd_p_concave", 1e-6, ""),
                ("Cd_p_ends", None, 1e-6, "endA + endB"), ("Cd_p_fields", "Cd_p_fields", 1e-6, ""),
                ("Cp_min_A_1mm", "Cp_min_A_1mm", 1e-4, "1-mm mean, stagnation to tip A"),
                ("Cp_min_B_1mm", "Cp_min_B_1mm", 1e-4, "1-mm mean, stagnation to tip B"),
                ("Cp_base_mean", "Cp_base_mean", 2e-4, "weights: face lengths here, centre spacing on 15 Oct"),
                ("sep_A_from_stag_over_c", "sep_A_from_stag_over_c", 1e-6, "NaN = none (smooth) or not judged (t > 0)"),
                ("Cd_p_convex_A", "Cd_p_stagface_A", 2e-3, "15 Oct counts the stagnation face in both halves"),
                ("Cd_p_convex_B", "Cd_p_stagface_B", 2e-3, "15 Oct counts the stagnation face in both halves"),
                ("stag_s_ref_over_c", "stag_s_over_c", 1e-3,
                 "s from the corner here, from the first face centre on 15 Oct")):
            v = r["Cd_p_endA"] + r["Cd_p_endB"] if mine is None else r[mine]
            if col == "sep_A_from_stag_over_c" and o["t_mm"] > 0:
                continue                    # 15 Oct did not judge textured walls; here u_d does (below)
            add(f"15 Oct {col}", n, float(o[col]), src, float(v), max(tol, g6(o[col])), note=note)
        if o["t_mm"] == 0:
            add("15 Oct sep_B_from_stag_over_c", n, float(o["sep_B_from_stag_over_c"]), src,
                float(r["sep_B_from_stag_over_c"]), max(1e-6, g6(o["sep_B_from_stag_over_c"])),
                note="smooth walls: the same Cf rule")
        else:
            for side, ref in (("A", 0.192), ("B", 0.146)):
                if o["t_mm"] == 0.2:
                    add(f"15 Oct note: Cf-based reversal on the t-0.20 wall, branch {side}", n, ref,
                        "roughness_surface.py comment (0.192 and 0.146 c)", float(r[f"sepCf_{side}_from_stag_over_c"]),
                        0.0015, kind="diagnostic", note="facet-scale artefact; not used")
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ figure
def figure(S, Pr):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    import roughness_analysis as RA          # 15 Oct style (read only)
    RA.style()
    INK2, GRID, SHADE = "#52514e", "#8c8c8c", "#ececec"
    BLUE, ORANGE = "#2a78d6", "#eb6834"      # validated pair (dataviz validator: CVD dE 24.7, normal-vision 33.6)
    Si = S.set_index("name")
    L = {f: float(S[f"len_{f}_over_c"].iloc[0]) for f in FACES}
    edges = np.cumsum([0.0] + [L[f] for f in FACES])
    corner_band = 1e-3 / C_REF
    alphas = (0, 90, 180)
    rows = [("wf", "Cp_1mm", (("wf_Ks0", INK2, "Ks 0"), ("wf_Ks400", BLUE, "Ks 400 µm"))),
            ("wf", "Cf_1mm", (("wf_Ks0", INK2, "Ks 0"), ("wf_Ks400", BLUE, "Ks 400 µm"))),
            ("tex", "Cp_1mm", (("tex0.000_s1", INK2, "t 0"), ("tex0.200_s1", ORANGE, "t 0.20 mm"))),
            ("tex", "Cf_1mm", (("tex0.000_s1", INK2, "t 0"), ("tex0.200_s1", ORANGE, "t 0.20 mm"))),
            ("tex", "u025_1mm", (("tex0.000_s1", INK2, "t 0"), ("tex0.200_s1", ORANGE, "t 0.20 mm")))]
    ylab = {"Cp_1mm": "$C_p$ (axis inverted)", "Cf_1mm": "$C_f$, + along the loop",
            "u025_1mm": "u/U at 0.25 mm,\n+ along the loop"}
    fig, axes = plt.subplots(len(rows), 3, figsize=(7.2, 9.4), sharex=True, constrained_layout=True,
                             gridspec_kw=dict(height_ratios=[1.15, 0.9, 1.15, 0.9, 0.9]))
    for j, a in enumerate(alphas):
        for i, (fam, col, lines) in enumerate(rows):
            ax = axes[i, j]
            names = [(f"a{a:05.1f}_U23.0_SST_{tag}_Tu1.0_Co2.5n2", colr, lab) for tag, colr, lab in lines]
            names = [x for x in names if x[0] in Si.index]
            if not names:
                ax.axis("off")
                ax.text(0.5, 0.5, "no texture run at 90°", transform=ax.transAxes, ha="center", va="center",
                        fontsize=6.5, color=INK2)
                continue
            for k in (1, 3):
                ax.axvspan(edges[k], edges[k + 1], color=SHADE, lw=0, zorder=0)
            ax.axhline(0, color=GRID, lw=0.5, zorder=0)
            inner = []
            for n, colr, lab in names:
                r = Si.loc[n]
                for f in FACES:
                    p = Pr[(Pr.name == n) & (Pr.face == f)].sort_values("loop_over_c")
                    ax.plot(p.loop_over_c, p[col], color=colr, lw=1.0, label=lab if f == "convex" else None)
                    far = (p.s_over_c > corner_band) & (p.s_over_c < L[f] - corner_band)
                    inner.append(p.loc[far, col].to_numpy())
                own = (col == "Cf_1mm" and r.t_mm == 0) or (col == "u025_1mm" and r.t_mm == 0.2)
                if own:                       # first separation on each branch, on the case's own reversal basis
                    for br in ("A", "B"):
                        x = r[f"first_S_{br}_loop_over_c"]
                        if np.isfinite(x):
                            ax.plot(x, 0, marker="v", ms=4.5, color=colr, mec="white", mew=0.6, zorder=5, ls="none")
            if col != "Cp_1mm":
                v = np.concatenate(inner)
                lim = 1.12 * np.nanmax(np.abs(v[np.isfinite(v)]))
                ax.set_ylim(-lim, lim)
            else:
                ax.invert_yaxis()
            if j == 0:
                ax.set_ylabel(ylab[col] + ("\nwall-function mesh" if fam == "wf" else "\ntexture mesh"), fontsize=7)
            if j == 2 and i in (0, 2):
                ax.legend(loc="lower right", fontsize=6.2, handlelength=1.6)
        axes[0, j].set_title(f"α = {a}°", loc="left", fontsize=8)
    for ax in axes[-1]:
        ax.set_xlim(0, edges[-1])
        ax.set_xticks([0, (edges[0] + edges[1]) / 2, edges[1] + L["endB"] / 2, (edges[2] + edges[3]) / 2, edges[-1]])
        ax.set_xticklabels(["tip A", "convex", "tip B", "concave", "tip A"], fontsize=6.5)
        ax.set_xlabel(f"round the wall, loop/c 0–{edges[-1]:.2f} (end faces shaded)", fontsize=6.8)
    for j in range(3):                       # the lowest drawn panel of each column carries the x labels
        ax = [a for a in axes[:, j] if a.axison][-1]
        ax.tick_params(labelbottom=True)
        ax.set_xlabel(f"round the wall, loop/c 0–{edges[-1]:.2f} (end faces shaded)", fontsize=6.8)
    h = [Line2D([], [], color=INK2, lw=1.0, label="smooth (Ks 0, or t 0)"),
         Line2D([], [], color=BLUE, lw=1.0, label="Ks 400 µm, rough wall function"),
         Line2D([], [], color=ORANGE, lw=1.0, label="t 0.20 mm, texture in the mesh"),
         Line2D([], [], color=INK2, marker="v", ms=4.5, ls="none", label="first separation on each branch")]
    fig.legend(handles=h, loc="lower center", ncol=4, fontsize=6.3, bbox_to_anchor=(0.5, -0.025))
    fig.suptitle("Static blade section, SST, 23 m/s, maxCo 2.5: time means, 1-mm running means along the wall. "
                 "u/U at 0.25 mm: tangential mean velocity 0.25 mm\nfrom the smooth wall, above the t-0.20 crests "
                 "(the reversal basis there). Cf and u axes scaled to the wall more than 1 mm from a corner "
                 "(corner peaks run off the axes).", fontsize=6.4, x=0.01, ha="left", color=INK2)
    out = FIG / "surface_cp_cf.png"
    fig.savefig(out, dpi=200, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return out


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="substring of the case names to run (no files written unless all run)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()
    cases = discover()
    if args.only:
        sel = [c for c in cases if args.only in c["name"]]
        cases = sel
    n2 = sum(c["stage"] == 2 for c in cases)
    print(f"{len(cases)} cases ({n2} Stage 2, {len(cases) - n2} Stage 1)")
    with ProcessPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        res = list(ex.map(analyse, cases))
    S = pd.DataFrame([r[0] for r in res])
    Pr = pd.concat([r[1] for r in res], ignore_index=True)
    E = pd.DataFrame([e for r in res for e in r[2]])
    H = pd.DataFrame([h for r in res for h in r[3]])
    for r in S.itertuples():
        print(f"{r.name:46s} Cd_p {r.Cd_p_fields:.4f}/{r.Cd_p_table:.4f} ({100 * r.Cd_p_rel_err:+.3f} %) "
              f"cvx {r.Cd_p_convex:+.3f} ccv {r.Cd_p_concave:+.3f} ends {r.Cd_p_endA + r.Cd_p_endB:+.3f} | "
              f"stag {r.stag_face} {r.stag_s_over_c:.3f} Cp {r.Cp_stag_1mm:.3f} | "
              f"S_A {r.first_S_A_face} {r.first_S_A_from_stag_over_c:.3f} "
              f"S_B {r.first_S_B_face} {r.first_S_B_from_stag_over_c:.3f} "
              f"| {r.reversal_basis}")
    C = checks(S) if not args.only else pd.DataFrame()
    if len(C):
        bad = C[(C.kind == "validation") & ~C.passed]
        print(f"checks: {int((C.kind == 'validation').sum())} validation, {len(bad)} failed; "
              f"max |Cd_p rel err| {100 * S.Cd_p_rel_err.abs().max():.4f} %")
        for b in bad.itertuples():
            print("  FAILED", b.check, b.case, b.reference, b.value, b.tolerance)
    if args.no_write or args.only:
        return 0
    OUT.mkdir(exist_ok=True)
    FIG.mkdir(exist_ok=True)
    S.to_csv(OUT / "surface_summary.csv", index=False, float_format="%.6g")
    Pr[Pr.keep].drop(columns=["keep"]).to_csv(OUT / "surface_profiles.csv", index=False, float_format="%.5g")
    E.to_csv(OUT / "surface_reversal.csv", index=False, float_format="%.5g")
    H.to_csv(OUT / "surface_reversal_heights.csv", index=False, float_format="%.5g")
    C.to_csv(OUT / "surface_check.csv", index=False, float_format="%.6g")
    print("wrote", figure(S, Pr))
    return 1 if len(C) and ((C.kind == "validation") & ~C.passed).any() else 0


if __name__ == "__main__":
    sys.exit(main())
