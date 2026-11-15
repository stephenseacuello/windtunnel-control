#!/usr/bin/env python3
"""Pressure and wall shear on each rotor blade through the rotation, from the surface samples of a cfd/rotor2d
case run with surface sampling (surf=1 or 2; cfd/rotor2d/README.md "Surface sampling"): Cp and signed Cf against
blade azimuth and arc length along the wall, in 10-deg azimuth bins over the averaged revolutions.

    python3 cfd/post/rotor_surface.py cfd/rotor2d/runs/<case>             # finished or running case
    python3 cfd/post/rotor_surface.py <case> --revs 0:1                    # revolutions 0..0 instead of the window
    python3 cfd/post/rotor_surface.py <case> --no-plot                     # CSV and JSON only (no matplotlib)

Why
  Prof. Jahangiri's question J3 (1 Nov): changes in flow separation, pressure distribution, lift, drag and torque
  throughout the blade rotation. The production rotor runs save per-blade forces only (binned by
  cfd/analysis/2026-11-15/src/rotor_phase_force.py) and fields at half-revolution writes, so the pressure and wall
  shear on a turning blade need the samples that surf=1 adds.

Reads (read only)
  <case>/case.json        Trev, omegaZ, sense, Uinf, rhoInf, dz, thetaDeg, nRev, nAvgRev, surfInterval
  <case>/mesh_info.json   pose_full: the blade pose of the mesh (cfd/rotor2d/rotor_geometry.py)
  <case>/postProcessing/surfacesBlades/<t>/{p,wallShearStress}_blade{1,2,3}.raw   (run_case.py
                          write_surface_functions: face centre, value, face area vector, model frame at time t)
  <case>/postProcessing/forcesBlade{1,2,3}/<t0>/force.dat   checks only (rotor_summary.read_vector_dat)
  cfd/rotor2d/rotor_geometry.py   imported, not edited: blade section (cfd/geometry/section_v1.json), its corners
                          and area centroid, the model-frame placement of each blade
Writes (into the case folder)
  surface_phase.csv       blade (1, 2, 3, mean) x 36 bins x wall faces: n_rev, Cp, Cf, each with 2u; for the
                          mean also the between-blade 2u
  surface_phase.png       s-theta carpets of Cp (top) and Cf (bottom): blades 1, 2, 3 and their mean
  surface_phase.json      samples, revolutions, bins filled, and the checks below

Conventions
  Frame and azimuth (cfd/rotor2d/README.md; cfd/analysis/2026-10-15/src/rotor_analysis.py phase_bins). Blade k
  sits at theta_1 + 120 (k - 1), theta_1 = Omega t + thetaDeg (thetaDeg 0 in every rotating case); theta 0: the
  blade's radial line points upwind, 90: advancing (moving downwind), 180: downwind, 270: returning. The mesh
  turns by omegaZ t (omegaZ = sense Omega), so a sample written at time t is mapped back to t = 0 by turning it by
  -omegaZ t, and into the blade's CAD frame by the inverse of rotor_geometry.to_model at theta 0.
  Bins (phase_bins' rule): 36 bins of 10 deg, [10 m, 10 m + 10). In revolution r (counted on blade 1, from t = 0)
  blade k is in bin m from r T + mod(10 m - 120 (k - 1), 360)/360 T for T/36. Its value for a face is the time
  mean of the sampled series over that interval: the cumulative trapezoid of the samples, interpolated at the bin
  edges, using the times written. With samples on the 5-deg grid (writeControl runTime puts them within half a
  time step of it) this is y(10 m)/4 + y(10 m + 5)/2 + y(10 m + 10)/4. A bin is missing in a revolution if the
  samples do not span it or lie more than 1.5 sampling intervals apart inside it; at the first and last sample it
  may reach 0.05 intervals beyond (the end value held), as runTime can place those half a step off the grid.
  Revolutions: the case's averaging window, nRev - nAvgRev to nRev - 1 (that of the force means), or --revs.
  Faces and s (as cfd/analysis/2026-11-15/src/surface_extract.py for the sections): convex (outer surface, corner
  A_outer to B_outer), endB (B_outer to B_inner), concave (inner, A_inner to B_inner), endA (A_outer to A_inner).
  s/c: arc length along each face from its first corner (tip A for convex and concave, the outer corner for the
  ends) to the face centre, along the wall polyline (face length = |S|/dz), over c = 48 mm. loop/c: one coordinate
  round the wall, A_outer -> convex -> B_outer -> endB -> B_inner -> concave -> A_inner -> endA -> A_outer. Faces
  are placed by projecting their t = 0 centres onto the section outline (rotor_geometry.Section). 'mean' uses blade
  1's faces; the three blades' faces coincide on the meshes checked (else the others are interpolated; JSON flag).
  Cp = p / (0.5 U^2): kinematic p, p_inf = 0 (outlet and far-field sides). Not the relative-wind stagnation value:
  at lambda 0.10 the geometric relative wind |W|/U at the blade centroid is 0.90-1.10 (check 'stagnation').
  Cf = -(tau_w . t_s) / (0.5 U^2): tau_w is the wallShearStress function object's vector ((-n) . R_eff, the stress
  of the wall on the fluid, so it points against the near-wall flow) and t_s the unit tangent along +s. Cf > 0
  where the near-wall flow relative to the blade runs along +s: on both long faces from tip A toward tip B. The
  sign rule of surface_extract.py (owner-cell velocity along +s), taken from the shear itself. The figure's black
  line is Cf = 0 of the loop-direction value (+1 x Cf on convex and endB, -1 x Cf on concave and endA), so it does
  not jump at the corners where the faces' +s changes direction.
  Uncertainty (the 15 Oct rule): 2u = 2 s / sqrt(n), s the standard deviation (n - 1) of the n revolution values of
  the bin (per face); none below n = 2. 'mean' = the three blades averaged within each revolution, then the same
  statistics. Between-blade 2u (mean rows): 2 sd / sqrt(3), sd of the three blades' means over the same
  revolutions (as rotor_phase_force.py; the blades differ by more than their revolution scatter there). Neither
  covers the mesh, the time step or the turbulence model.
  Restarts: a run killed between field writes restarts from the last write and samples again. Samples less than
  half an interval apart are taken as one sample written twice: the most recently written is kept (JSON
  'duplicates_dropped'). Sample folders with a missing or short file (a running case) are skipped.

Checks (surface_phase.json; printed)
  geometry: every face centre, mapped back to t = 0 and into the CAD frame, lies on its blade's wall (distance
    from the section outline; chord-to-arc offsets are below 0.02 mm); the faces tile the wall (sum of face
    lengths per face against the section's lengths); the loop tangent from the area vector runs along the outline.
  forces: at every sample time with a forcesBlade<k> row at that time, rho sum(p S) against its pressure force
    and -rho sum(tau_w |S|) against its viscous force (both function objects read the same boundary values, so
    agreement is to the written precision; a mismatch flags a wrong mapping or stale wall shear).
  stagnation: the largest Cp on each blade at each sample, against the quasi-steady (|W|/U)^2 at the blade
    centroid, W = U e_x - omegaZ e_z x r_c (cfd/analysis/2026-11-15/src/rotor_phase_force.py).
No OpenFOAM install is needed.
"""
import argparse
import csv
import json
import math
import sys
import time
import warnings
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True          # importing rotor_geometry leaves no __pycache__ in cfd/rotor2d
HERE = Path(__file__).resolve().parent  # cfd/post
CFD = HERE.parent
# cfd/rotor2d at the END of sys.path, for rotor_geometry only: its queue.py would shadow the standard 'queue'
sys.path.append(str(CFD / "rotor2d"))
if str(HERE) not in sys.path:           # rotor_summary when this file is imported rather than run
    sys.path.insert(0, str(HERE))
import rotor_geometry as rg  # noqa: E402
from rotor_summary import read_vector_dat  # noqa: E402  (forces over restarts, later start wins)

FO = "surfacesBlades"                   # run_case.py write_surface_functions
FIELDS = ("p", "wallShearStress")
NB = 36                                 # 10-deg bins: rotor_analysis.py phase_bins(nb=36)
C_REF = 0.048                           # m, section reference chord (cfd/section2d/README.md section 1; surface_extract.py)
FACES = ("convex", "endB", "concave", "endA")
LOOP_DIR = {"convex": +1, "endB": +1, "concave": -1, "endA": -1}   # face +s relative to the loop (surface_extract.py)
GAP_MAX = 1.5                           # largest sample spacing inside a bin, in sampling intervals
EDGE = 0.05                             # a bin may reach this far (sampling intervals) past the first or last sample:
                                        # runTime samples lie up to half a step (0.003-0.005 intervals) off the grid
DIST_MAX = 1.0e-4                       # m, face centre to section outline; more stops the analysis (wrong mapping)
MATCH_TOL = 1.0e-6                      # m, the same face at two sample times (after turning back)


def _num(s):
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------- reading
def read_raw(path):
    """Columns and rows of an OpenFOAM raw surface file: '# <field>  FACE_DATA <n>', '# x y z <field...> area_x ...'."""
    head, body = [], []
    with open(path) as fh:
        for ln in fh:
            (head if ln.startswith("#") else body).append(ln)
    cols = head[-1][1:].split()
    n = int(head[0].split()[-1])
    a = np.array(" ".join(body).split(), float)
    if len(body) != n or a.size != n * len(cols):
        raise ValueError(f"{path}: {len(body)} rows of {n}, {a.size} values for {len(cols)} columns")
    return cols, a.reshape(n, len(cols))


def sample_dirs(case, interval):
    """Sample folders [(t, path)] in time order, each complete (6 files that parse) and once. Returns them with the
    counts of duplicates dropped and incomplete folders skipped."""
    root = Path(case) / "postProcessing" / FO
    if not root.is_dir():
        raise SystemExit(f"{root}: no surface samples (was the case run with surf=1 or 2?)")
    found = sorted(((_num(d.name), d) for d in root.iterdir() if d.is_dir() and _num(d.name) is not None),
                   key=lambda x: x[0])
    files = [f"{f}_blade{k}.raw" for k in (1, 2, 3) for f in FIELDS]
    ok, skipped = [], []
    for i, (t, d) in enumerate(found):
        good = all((d / f).is_file() and (d / f).stat().st_size > 0 for f in files)
        if good and i == len(found) - 1:     # the newest folder may still be being written (running case)
            try:
                for f in files:
                    read_raw(d / f)
            except (ValueError, IndexError):
                good = False
        if good:
            ok.append((t, d))
        else:
            skipped.append(d.name)
    out, dropped = [], 0
    for t, d in ok:                      # samples closer than EDGE intervals: one written twice (a restart);
        if out and t - out[-1][0] < EDGE * interval:   # true re-samples are at most about a step apart
            dropped += 1
            if d.stat().st_mtime >= out[-1][1].stat().st_mtime:
                out[-1] = (t, d)
            continue
        out.append((t, d))
    return out, dropped, skipped


def turn(xy, ang):
    """2-vectors (..., 2) turned counter-clockwise by ang (rad; scalar or broadcastable)."""
    c, s = np.cos(ang), np.sin(ang)
    return np.stack([c * xy[..., 0] - s * xy[..., 1], s * xy[..., 0] + c * xy[..., 1]], -1)


# ---------------------------------------------------------------- wall geometry
def project(sec, pts):
    """Arc length s (rotor_geometry.Section: A_out -> outer -> B_out -> end B -> B_in -> inner -> A_in -> end A) of the
    nearest outline point, the distance to it and the outline's unit tangent there, for CAD points (n, 2)."""
    o = sec.outline
    so = np.linspace(0.0, sec.L, len(o) + 1)
    b = np.roll(o, -1, axis=0)
    seg = b - o
    l2 = np.sum(seg ** 2, axis=1)
    d = pts[:, None, :] - o[None, :, :]
    f = np.clip(np.sum(d * seg[None], axis=2) / l2[None], 0.0, 1.0)
    dist = np.linalg.norm(d - f[..., None] * seg[None], axis=2)
    j = np.argmin(dist, axis=1)
    i = np.arange(len(pts))
    s = so[j] + f[i, j] * (so[j + 1] - so[j])
    tng = seg[j] / np.sqrt(l2[j])[:, None]
    return s, dist[i, j], tng


def wall_frame(sec, pose, k, xy0, S0, dz):
    """Faces of blade k from its t = 0 face centres xy0 (n, 2) and area vectors S0 (n, 2), model frame. Returns
    loop order, face name, s/c, loop/c, length (m), loop tangent (model frame, t = 0) and the checks."""
    Rm, Sc = rg.blade_transform(pose, 0.0, k)
    cad = xy0 @ Rm + Sc                              # inverse of rotor_geometry.to_model: p = Rm (P - S)
    s, dist, tng_cad = project(sec, cad)
    order = np.argsort(s)
    s, dist, tng_cad = s[order], dist[order], tng_cad[order]
    S0 = S0[order]
    ln = np.linalg.norm(S0, axis=1) / dz
    t_loop = np.stack([S0[:, 1], -S0[:, 0]], -1) / np.linalg.norm(S0, axis=1)[:, None]   # solid on the left
    edges = np.r_[0.0, sec.s_corner]                 # A_out, B_out, B_in, A_in, A_out
    face = np.array(FACES)[np.clip(np.searchsorted(edges, s, side="right") - 1, 0, 3)]
    sp = np.cumsum(ln) - ln / 2                      # polyline arc length from A_out to the face centres
    L = {f: float(ln[face == f].sum()) for f in FACES}
    cum = np.cumsum([0.0] + [L[f] for f in FACES])   # polyline position of each face's start along the loop
    s_face = np.empty_like(sp)
    for i, f in enumerate(FACES):
        m = face == f
        s_face[m] = sp[m] - cum[i] if LOOP_DIR[f] > 0 else cum[i + 1] - sp[m]
    ref = {"convex": sec.L_o, "endB": sec.L_eB, "concave": sec.L_i, "endA": sec.L_eA}
    along = np.sum((t_loop @ Rm) * tng_cad, axis=1)  # loop tangent against the outline's, CAD frame
    chk = dict(max_dist_to_wall_m=float(dist.max()), faces={f: int(np.sum(face == f)) for f in FACES},
               length_rel_err={f: L[f] / ref[f] - 1.0 for f in FACES}, min_tangent_alignment=float(along.min()))
    if dist.max() > DIST_MAX or along.min() < 0.99 or min(chk["faces"].values()) == 0:
        raise ValueError(f"blade{k}: faces do not map onto the section ({chk}); check omegaZ, thetaDeg and the "
                         f"mesh pose in mesh_info.json")
    return dict(order=order, face=face, s_over_c=s_face / C_REF, loop_over_c=sp / C_REF, len=ln, t_loop=t_loop,
                xy0=xy0[order], chk=chk)


# ---------------------------------------------------------------- samples
def load_samples(case, P, dirs, sec, pose):
    """Per blade: times, Cp and Cf (n_samples, n_faces) in loop order, the wall frame, and per-sample forces and
    stagnation values for the checks."""
    U, q = P["Uinf"], 0.5 * P["Uinf"] ** 2
    omz, dz, rho = P["omegaZ"], P["dz"], P["rhoInf"]
    out = {}
    for k in (1, 2, 3):
        frame = None
        t, cp, cf, fp, fv, cpmax, wq, remap = [], [], [], [], [], [], [], 0
        c0 = rg.to_model(pose, sec.centroid, 0.0, k)[0]
        for tj, d in dirs:
            cp_cols, a = read_raw(d / f"p_blade{k}.raw")
            tw_cols, b = read_raw(d / f"wallShearStress_blade{k}.raw")
            ia = [cp_cols.index(c) for c in ("x", "y", "p", "area_x", "area_y")]
            ib = [tw_cols.index(c) for c in ("x", "y", "wallShearStress_x", "wallShearStress_y")]
            if a.shape[0] != b.shape[0] or not np.allclose(a[:, ia[:2]], b[:, ib[:2]], rtol=0, atol=1e-12):
                raise ValueError(f"{d}: p and wallShearStress rows of blade{k} do not match")
            ang = -omz * tj                              # back to t = 0
            xy0 = turn(a[:, ia[:2]], ang)
            if frame is None:
                frame = wall_frame(sec, pose, k, xy0, turn(a[:, ia[3:5]], ang), dz)
                ref = frame["xy0"]
                t_s = np.array([LOOP_DIR[f] for f in frame["face"]])[:, None] * frame["t_loop"]   # +s, t = 0 frame
            # rows -> the reference faces: same row order (serial, same decomposition) or nearest centre
            cand = frame["order"]
            if len(xy0) != len(ref) or np.max(np.linalg.norm(xy0[cand] - ref, axis=1)) > MATCH_TOL:
                dd = np.linalg.norm(xy0[None, :, :] - ref[:, None, :], axis=2)
                cand = np.argmin(dd, axis=1)
                if len(set(cand.tolist())) != len(ref) or np.max(dd[np.arange(len(ref)), cand]) > MATCH_TOL:
                    raise ValueError(f"{d}: blade{k} faces do not match those of the first sample")
                remap += 1
            pv = a[cand, ia[2]]
            tau = turn(b[cand][:, ib[2:4]], ang)          # wall shear in the t = 0 frame
            t.append(tj)
            cp.append(pv / q)
            cf.append(-np.sum(tau * t_s, axis=1) / q)
            Sxy = a[cand][:, ia[3:5]]                    # model frame at t
            fp.append(rho * np.sum(pv[:, None] * Sxy, axis=0))
            fv.append(-rho * np.sum(b[cand][:, ib[2:4]] * np.linalg.norm(Sxy, axis=1)[:, None], axis=0))
            rc = turn(c0, omz * tj)
            W = np.array([U + omz * rc[1], -omz * rc[0]])
            cpmax.append(float(np.max(pv / q)))
            wq.append(float(W @ W) / U ** 2)
        out[k] = dict(t=np.array(t), Cp=np.array(cp), Cf=np.array(cf), frame=frame, Fp=np.array(fp), Fv=np.array(fv),
                      Cp_max=np.array(cpmax), W2=np.array(wq), remapped=remap)
    return out


# ---------------------------------------------------------------- binning
def cumint(t, y):
    """Cumulative trapezoid along axis 0 (rotor_analysis.py cumint, for arrays (n, ...))."""
    dt = np.diff(t).reshape((-1,) + (1,) * (y.ndim - 1))
    return np.concatenate([np.zeros((1,) + y.shape[1:]), np.cumsum(0.5 * (y[1:] + y[:-1]) * dt, axis=0)])


def at(t, cum, Y, x):
    """The cumulative integral at time x: linear between samples, the end value held beyond the first or last."""
    if x <= t[0]:
        return cum[0] - Y[0] * (t[0] - x)
    if x >= t[-1]:
        return cum[-1] + Y[-1] * (x - t[-1])
    j = int(np.searchsorted(t, x, side="right") - 1)
    w = (x - t[j]) / (t[j + 1] - t[j])
    return cum[j] + w * (cum[j + 1] - cum[j])


def bin_blade(t, Y, T, k, revs, interval):
    """Per-revolution bin means of one blade: (len(revs), NB, ...) with NaN where the samples do not cover the bin."""
    out = np.full((len(revs), NB) + Y.shape[1:], np.nan)
    if len(t) < 2:
        return out
    cum, dt, tol = cumint(t, Y), np.diff(t), EDGE * interval
    for a, r in enumerate(revs):
        for m in range(NB):
            ta = r * T + ((360.0 * m / NB - 120.0 * (k - 1)) % 360.0) / 360.0 * T
            tb = ta + T / NB
            if ta < t[0] - tol or tb > t[-1] + tol:
                continue
            ja = max(0, int(np.searchsorted(t, ta + tol, side="right")) - 1)
            jb = min(len(t) - 1, int(np.searchsorted(t, tb - tol, side="left")))
            if jb > ja and dt[ja:jb].max() > GAP_MAX * interval:
                continue
            out[a, m] = (at(t, cum, Y, tb) - at(t, cum, Y, ta)) / (tb - ta)
    return out


def stats(X):
    """Mean over revolutions (axis 0; NaN = missing), count, and 2u = 2 s / sqrt(n) (s with n - 1; NaN below n = 2)."""
    n = np.sum(np.isfinite(X), axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        mean = np.nanmean(X, axis=0)
        s = np.nanstd(X, axis=0, ddof=1)
    return mean, n, np.where(n >= 2, 2.0 * s / np.sqrt(np.maximum(n, 1)), np.nan)


def on_reference(blade, ref):
    """Blade values (..., faces) on the reference blade's faces: the same faces, or periodic interpolation in loop/c."""
    xr, xb = ref["frame"]["loop_over_c"], blade["frame"]["loop_over_c"]
    if len(xr) == len(xb) and np.max(np.abs(xr - xb)) < 1e-6 / C_REF:
        return lambda Y: Y, True
    per = (ref["frame"]["len"].sum()) / C_REF

    def f(Y):
        xx = np.r_[xb - per, xb, xb + per]
        return np.apply_along_axis(lambda y: np.interp(xr, xx, np.r_[y, y, y]), -1, Y)
    return f, False


# ---------------------------------------------------------------- figure
def carpets(path, frame, res, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
                         "font.size": 7.5, "axes.titlesize": 7.5, "axes.labelsize": 7.5, "xtick.labelsize": 7,
                         "ytick.labelsize": 7, "axes.linewidth": 0.6, "axes.edgecolor": "#333333",
                         "savefig.dpi": 200, "savefig.bbox": "tight", "savefig.pad_inches": 0.03})
    grey = "#f0efec"                                  # neutral midpoint of both diverging scales
    cm_p = LinearSegmentedColormap.from_list("cp", ["#1f4e8c", "#7da7d9", grey, "#e39a8c", "#a3231f"])
    cm_f = LinearSegmentedColormap.from_list("cf", ["#5b3a8e", "#a991cc", grey, "#e7a868", "#a9590b"])
    ln = frame["len"] / C_REF
    xe = np.r_[0.0, np.cumsum(ln)]
    ye = np.linspace(0, 360, NB + 1)
    xc, yc = frame["loop_over_c"], 0.5 * (ye[1:] + ye[:-1])
    corners = [xe[np.flatnonzero(frame["face"] == f)[-1] + 1] for f in FACES[:-1]]
    sgn = np.array([LOOP_DIR[f] for f in frame["face"]])
    cols = [("blade 1", 1), ("blade 2", 2), ("blade 3", 3), ("three-blade mean", "mean")]

    def lim(q, sym):
        v = np.concatenate([res[b][q][0][np.isfinite(res[b][q][0])] for _, b in cols])
        if not v.size:
            return -1.0, 1.0
        lo, hi = np.percentile(v, [1, 99])
        if sym:
            a = max(abs(lo), abs(hi), 1e-6)
            return -a, a
        return min(lo, -1e-6), max(hi, 1e-6)
    rows = (("Cp", cm_p, TwoSlopeNorm(0.0, *lim("Cp", False)), r"$C_p = p\,/\,(U^2/2)$"),
            ("Cf", cm_f, TwoSlopeNorm(0.0, *lim("Cf", True)), r"$C_f$  (+: near-wall flow toward tip B)"))
    fig, axs = plt.subplots(2, 4, figsize=(7.4, 5.0), sharex=True, sharey=True, constrained_layout=True)
    for i, (q, cmap, norm, clab) in enumerate(rows):
        for j, (lab, b) in enumerate(cols):
            ax = axs[i, j]
            ax.patch.set_facecolor("white")
            ax.patch.set_hatch("/////")
            ax.patch.set_edgecolor("#d4d4d4")                    # hatched: no complete bin
            Z = res[b][q][0]
            im = ax.pcolormesh(xe, ye, np.ma.masked_invalid(Z), cmap=cmap, norm=norm, shading="flat",
                               rasterized=True)
            if q == "Cf" and np.isfinite(Z).sum() > 3:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    ax.contour(xc, yc, np.ma.masked_invalid(Z * sgn[None, :]), levels=[0.0], colors="k",
                               linewidths=0.5)
            for x in corners:
                ax.axvline(x, color="#555555", lw=0.4, ls=":")
            for y in (90, 180, 270):
                ax.axhline(y, color="#777777", lw=0.3)
            if i == 0:
                ax.set_title(lab, loc="left")
                top = ax.secondary_xaxis("top")
                top.set_xticks([0.5 * corners[0], 0.5 * (corners[1] + corners[2])], labels=["convex", "concave"])
                top.tick_params(length=0, labelsize=6.3, labelcolor="#444444")
            if i == 1:
                ax.set_xlabel("loop/c from tip A")
            if j == 0:
                ax.set_ylabel(r"blade azimuth $\theta$ (deg)")
                ax.set_yticks([0, 90, 180, 270, 360],
                              labels=["0 upwind", "90 advancing", "180 downwind", "270 returning", "360"])
            ax.set_xlim(xe[0], xe[-1])
            ax.set_ylim(0, 360)
        fig.colorbar(im, ax=axs[i, :], shrink=0.92, pad=0.01, label=clab)
    fig.suptitle(title, fontsize=7.2, x=0.01, ha="left")
    fig.savefig(path)
    plt.close(fig)


# ---------------------------------------------------------------- main
def fmt(v):
    if isinstance(v, (float, np.floating)):
        return "" if not np.isfinite(v) else f"{v:.6g}"
    return str(v)


def analyse(case, revs=None, plot=True, quiet=False):
    case = Path(case).resolve()
    P = json.loads((case / "case.json").read_text())
    mi = json.loads((case / "mesh_info.json").read_text())
    if P.get("mode") != "rotating":
        raise SystemExit(f"{case.name}: not a rotating case")
    if abs(P.get("thetaDeg", 0.0)) > 1e-12:
        raise SystemExit(f"{case.name}: thetaDeg {P['thetaDeg']} != 0 (phase_bins' convention assumes 0)")
    T = P["Trev"]
    interval = P.get("surfInterval") or T / 72
    if revs is None:
        revs = range(int(P["nRev"]) - int(P["nAvgRev"]), int(P["nRev"]))
    if not len(revs):
        raise SystemExit("no revolutions to bin (--revs FIRST:END with END > FIRST)")
    dirs, dropped, skipped = sample_dirs(case, interval)
    if not dirs:
        raise SystemExit(f"{case.name}: no complete surface samples yet")
    sec = rg.Section()
    pose = mi["pose_full"]
    D = load_samples(case, P, dirs, sec, pose)
    ref = D[1]
    res, X = {}, {}
    for k in (1, 2, 3):
        to_ref, same = on_reference(D[k], ref)
        D[k]["aligned"] = same
        for q in ("Cp", "Cf"):
            X[(k, q)] = to_ref(bin_blade(D[k]["t"], D[k][q], T, k, revs, interval))
        res[k] = {q: stats(X[(k, q)]) for q in ("Cp", "Cf")}
    res["mean"] = {}
    for q in ("Cp", "Cf"):
        Xm = np.mean(np.stack([X[(k, q)] for k in (1, 2, 3)]), axis=0)        # NaN unless all three blades
        mean, n, u2 = stats(Xm)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            bm = np.stack([np.nanmean(np.where(np.isfinite(Xm), X[(k, q)], np.nan), axis=0) for k in (1, 2, 3)])
            ub = 2.0 * np.std(bm, axis=0, ddof=1) / math.sqrt(3.0)
        res["mean"][q] = (mean, n, u2, ub)

    # ---- CSV
    fr = ref["frame"]
    edges = np.linspace(0, 360, NB + 1)
    rows = 0
    with open(case / "surface_phase.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["blade", "theta_lo_deg", "theta_mid_deg", "face_index", "face", "s_over_c", "loop_over_c",
                    "n_rev", "Cp", "Cp_2u", "Cf", "Cf_2u", "Cp_2u_blades", "Cf_2u_blades"])
        for b in (1, 2, 3, "mean"):
            cpm, n, cpu = res[b]["Cp"][:3]
            cfm, _, cfu = res[b]["Cf"][:3]
            ubp = res[b]["Cp"][3] if b == "mean" else None
            ubf = res[b]["Cf"][3] if b == "mean" else None
            for m in range(NB):
                for i in range(len(fr["face"])):
                    w.writerow([b, f"{edges[m]:g}", f"{edges[m] + 5:g}", i, fr["face"][i], fmt(fr["s_over_c"][i]),
                                fmt(fr["loop_over_c"][i]), int(n[m, i]), fmt(cpm[m, i]), fmt(cpu[m, i]),
                                fmt(cfm[m, i]), fmt(cfu[m, i]), fmt(ubp[m, i]) if ubp is not None else "",
                                fmt(ubf[m, i]) if ubf is not None else ""])
                    rows += 1

    # ---- checks
    fo_rows = {}
    for k in (1, 2, 3):
        f = read_vector_dat(case, f"forcesBlade{k}", "force.dat")
        tf = f[:, 0] if len(f) else np.zeros(0)
        dp, dv, nmatch = [], [], 0
        for j, tj in enumerate(D[k]["t"]):
            i = int(np.searchsorted(tf, tj))
            near = [x for x in (i - 1, i) if 0 <= x < len(tf)]
            if not near:
                continue
            i = min(near, key=lambda x: abs(tf[x] - tj))
            if abs(tf[i] - tj) > 1e-9 * T:
                continue
            nmatch += 1
            Fp, Fv = f[i, 4:6], f[i, 7:9]
            dp.append(float(np.linalg.norm(D[k]["Fp"][j] - Fp) / np.linalg.norm(Fp)))
            dv.append(float(np.linalg.norm(D[k]["Fv"][j] - Fv) / np.linalg.norm(Fv)))
        fo_rows[f"blade{k}"] = dict(samples=int(len(D[k]["t"])), with_force_row=nmatch,
                                    pressure_rel_diff_max=max(dp) if dp else None,
                                    viscous_rel_diff_max=max(dv) if dv else None)
    stag = {}
    for k in (1, 2, 3):
        r = D[k]["Cp_max"] / D[k]["W2"]
        stag[f"blade{k}"] = dict(Cp_max_min=float(D[k]["Cp_max"].min()), Cp_max_max=float(D[k]["Cp_max"].max()),
                                 W2_min=float(D[k]["W2"].min()), W2_max=float(D[k]["W2"].max()),
                                 ratio_min=float(r.min()), ratio_median=float(np.median(r)), ratio_max=float(r.max()))
    t_all = D[1]["t"]
    summary = dict(
        case=case.name, made=time.strftime("%Y-%m-%dT%H:%M:%S"), script="cfd/post/rotor_surface.py",
        samples=dict(n=int(len(t_all)), t_first_s=float(t_all[0]), t_last_s=float(t_all[-1]),
                     theta1_first_deg=float(np.degrees(P["Omega"] * t_all[0])),
                     theta1_last_deg=float(np.degrees(P["Omega"] * t_all[-1])),
                     interval_s=interval, interval_deg=360.0 * interval / T,
                     spacing_deg_min=float(np.degrees(P["Omega"] * np.diff(t_all).min())) if len(t_all) > 1 else None,
                     spacing_deg_max=float(np.degrees(P["Omega"] * np.diff(t_all).max())) if len(t_all) > 1 else None,
                     grid_offset_deg_max=float(np.max(np.abs((t_all / interval + 0.5) % 1.0 - 0.5)) * 360.0 * interval / T),
                     duplicates_dropped=dropped, incomplete_skipped=skipped,
                     rows_remapped={f"blade{k}": D[k]["remapped"] for k in (1, 2, 3)}),
        faces_per_blade={f"blade{k}": int(len(D[k]["frame"]["face"])) for k in (1, 2, 3)},
        faces_aligned_with_blade1={f"blade{k}": bool(D[k]["aligned"]) for k in (2, 3)},
        revolutions=[int(revs[0]), int(revs[-1])] if len(revs) else [],
        bins_filled={str(b): int(np.sum(res[b]["Cp"][1][:, 0] > 0)) for b in (1, 2, 3, "mean")},
        checks=dict(geometry={f"blade{k}": D[k]["frame"]["chk"] for k in (1, 2, 3)}, forces=fo_rows,
                    stagnation=stag),
        outputs=["surface_phase.csv", "surface_phase.json"] + (["surface_phase.png"] if plot else []),
        csv_rows=rows)
    if plot:
        rr = f"revolution{'s' if len(revs) > 1 else ''} {revs[0]}" + (f"-{revs[-1]}" if len(revs) > 1 else "")
        carpets(case / "surface_phase.png", fr, res,
                f"{case.name}\n{rr} (counted from t = 0), 10-deg bins, {len(t_all)} samples every "
                f"{360 * interval / T:.3g} deg; hatched: no complete bin; black line: Cf = 0")
    (case / "surface_phase.json").write_text(json.dumps(summary, indent=1))
    if not quiet:
        g = summary["checks"]["geometry"]
        print(f"{case.name}: {len(t_all)} samples, t {t_all[0]:.6g}-{t_all[-1]:.6g} s "
              f"(theta_1 {summary['samples']['theta1_first_deg']:.2f}-{summary['samples']['theta1_last_deg']:.2f} deg), "
              f"{dropped} duplicates dropped, {len(skipped)} incomplete skipped")
        print(f"  faces per blade {summary['faces_per_blade']}, aligned {summary['faces_aligned_with_blade1']}; "
              f"max distance to wall {max(v['max_dist_to_wall_m'] for v in g.values()) * 1e6:.2f} um")
        print(f"  revolutions {summary['revolutions']}, bins filled {summary['bins_filled']}")
        for k in (1, 2, 3):
            fo, st = fo_rows[f"blade{k}"], stag[f"blade{k}"]
            print(f"  blade{k}: forces at {fo['with_force_row']}/{fo['samples']} samples, rel. diff pressure "
                  f"{fmt(fo['pressure_rel_diff_max'])}, viscous {fmt(fo['viscous_rel_diff_max'])}; Cp_max "
                  f"{st['Cp_max_min']:.3f}-{st['Cp_max_max']:.3f}, (|W|/U)^2 {st['W2_min']:.3f}-{st['W2_max']:.3f}")
        print(f"  wrote {', '.join(summary['outputs'])} in {case}")
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case", help="cfd/rotor2d/runs/<case> (run with surf=1 or 2)")
    ap.add_argument("--revs", help="revolutions to bin, FIRST:END (END excluded; counted on blade 1 from t = 0); "
                                   "default: the case's averaging window")
    ap.add_argument("--no-plot", action="store_true", help="no figure (no matplotlib needed)")
    a = ap.parse_args()
    revs = None
    if a.revs:
        r0, r1 = (int(x) for x in a.revs.split(":"))
        revs = range(r0, r1)
    analyse(a.case, revs, plot=not a.no_plot)


if __name__ == "__main__":
    main()
