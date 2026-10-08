"""
Blade-section facts from the CAD mesh, for cfd/MEASUREMENTS_NEEDED.md.

Reads blades/v1.stl (metres; same frame as ~/Downloads/turbine.STEP, which is in
inches) and writes, next to this file:
  blade_section_cad.json   every number the guide quotes
  blade_section_cad.png    the section with tip A, tip B, the bolt holes and the chord

Frame (the CAD's own): z along the span, x along the bolt-hole axis, y across.
Tip A = square edge at the end of the long, flatter leg; tip B = square edge at
the end of the tight curl.

Run:  python3 cfd/measurements/blade_section_cad.py
Needs numpy, scipy, matplotlib, trimesh (system python3 has them).
"""
import json
from pathlib import Path

import numpy as np
import trimesh
from scipy.optimize import least_squares

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
R_ATTACH_MM = 101.6          # data/tunnel.json turbine.radius_m, measured 25 Aug 2026


def section(m, z_mm):
    s = m.section(plane_origin=[0, 0, m.bounds[0, 2] + z_mm / 1000],
                  plane_normal=[0, 0, 1])
    return [d[:-1, :2] * 1000 for d in s.discrete] if s is not None else []


def densify(P, step=0.05):
    out = []
    for a, b in zip(P, np.roll(P, -1, 0)):
        k = max(1, int(np.linalg.norm(b - a) / step))
        out.append(a + np.outer(np.arange(k) / k, b - a))
    return np.vstack(out)


def resample(F, n=600):
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(F, axis=0), axis=1))]
    t = np.linspace(0, s[-1], n)
    return np.c_[np.interp(t, s, F[:, 0]), np.interp(t, s, F[:, 1])]


def fit_circle(pts):
    c = pts.mean(0)
    r = least_squares(lambda p: np.hypot(pts[:, 0] - p[0], pts[:, 1] - p[1]) - p[2],
                      [c[0], c[1], 20.0])
    return r.x, float(np.sqrt(np.mean(r.fun ** 2)))


def main():
    m = trimesh.load(REPO / "blades" / "v1.stl")
    span = float(m.extents[2] * 1000)
    P = section(m, 50.0)[0]                       # away from the holes
    n = len(P)

    # the four square corners: turning angle near 90 deg
    v1, v2 = P - np.roll(P, 1, 0), np.roll(P, -1, 0) - P
    turn = np.degrees(np.arctan2(v1[:, 0] * v2[:, 1] - v1[:, 1] * v2[:, 0],
                                 (v1 * v2).sum(1)))
    c = sorted(np.argsort(-np.abs(turn))[:4])
    # pair corners that are adjacent around the polygon (each edge face is one segment)
    pairs, used = [], set()
    for i in c:
        if i in used:
            continue
        j = min((k for k in c if k != i and k not in used),
                key=lambda k: min(abs(k - i), n - abs(k - i)))
        pairs.append((i, j)); used |= {i, j}
    mids = [(P[i] + P[j]) / 2 for i, j in pairs]
    edge_faces = [float(np.linalg.norm(P[i] - P[j])) for i, j in pairs]
    tipA, tipB = sorted(mids, key=lambda p: p[1])  # A has the smaller y in this frame

    # two faces from tip A to tip B, midline by nearest-point pairing.
    # Each edge face runs forward from one corner to the other (one or more segments).
    def oriented(i, j):
        return (i, j) if (j - i) % n < n // 2 else (j, i)
    pa, pb = sorted(pairs, key=lambda p: P[p[0], 1])           # pa at tip A
    (a_start, a_end), (b_start, b_end) = oriented(*pa), oriented(*pb)
    walk = lambda i0, i1: P[[(i0 + t) % n for t in range((i1 - i0) % n + 1)]]
    f1 = walk(a_end, b_start)                                  # tip A -> tip B
    f2 = walk(b_end, a_start)[::-1]                            # reversed: tip A -> tip B
    A, B = resample(f1), resample(f2)
    # midline: both faces resampled by normalised arc length and averaged (thin wall)
    M = (A + B) / 2
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(M, axis=0), axis=1))]
    len_faces = [float(np.sum(np.linalg.norm(np.diff(F, axis=0), axis=1))) for F in (f1, f2)]
    L_mid = sum(len_faces) / 2                     # exact for a constant-wall offset band
    # turning: the square edges are normal to the wall, so the wall direction at each
    # tip is the edge-face normal; measure the angle swept from tip A to tip B
    def wall_dir(pair, inward_to):
        e = P[pair[1]] - P[pair[0]]
        nvec = np.array([-e[1], e[0]]) / np.linalg.norm(e)
        mid = (P[pair[0]] + P[pair[1]]) / 2
        return nvec if (inward_to - mid) @ nvec > 0 else -nvec
    dA = wall_dir(pa, M[len(M) // 10])             # leaving tip A, into the blade
    dB = -wall_dir(pb, M[-len(M) // 10])           # arriving at tip B, out of the blade
    T = np.gradient(M, axis=0)
    th = np.unwrap(np.arctan2(T[:, 1], T[:, 0]))
    sense = np.sign(th[-1] - th[0])
    turn_deg = float(np.degrees(np.arctan2(dA[0] * dB[1] - dA[1] * dB[0], dA @ dB)))
    if np.sign(turn_deg) != sense:
        turn_deg += 360 * sense
    leg, _ = fit_circle(M[(s / s[-1] >= 0.05) & (s / s[-1] <= 0.40)])
    curl, _ = fit_circle(M[(s / s[-1] >= 0.60) & (s / s[-1] <= 0.95)])
    whole, whole_rms = fit_circle(M)

    chord_v = tipB - tipA
    chord = float(np.linalg.norm(chord_v)); u = chord_v / chord
    nrm = np.array([-u[1], u[0]])
    D = densify(P)
    dep = (D - tipA) @ nrm
    k = int(np.argmax(np.abs(dep)))
    x, y = P[:, 0], P[:, 1]
    cr = x * np.roll(y, -1) - np.roll(x, -1) * y
    area = cr.sum() / 2
    cen = np.array([((x + np.roll(x, -1)) * cr).sum(), ((y + np.roll(y, -1)) * cr).sum()]) / (6 * area)

    # bolt holes: z ranges where the slice splits into two loops
    zs = np.arange(0.5, span - 0.5, 0.05)
    split = np.array([len(section(m, z)) == 2 for z in zs])
    edges = np.flatnonzero(np.diff(split.astype(int)))
    holes = []
    for a, b in zip(edges[::2], edges[1::2]):
        z0, z1 = zs[a + 1], zs[b]
        zc = (z0 + z1) / 2
        loops = section(m, zc)
        # gap between the two loops, along y, on the bolt axis
        ys = sorted([lp[:, 1].max() if lp[:, 1].mean() < cen[1] else lp[:, 1].min()
                     for lp in loops])
        holes.append({"z_from_far_end_mm": round(zc, 2), "z_from_near_end_mm": round(span - zc, 2),
                      "diameter_mm": round(z1 - z0, 2), "y_axis_mm": round((ys[0] + ys[1]) / 2, 2)})
    y_h = float(np.mean([h["y_axis_mm"] for h in holes]))
    # where the bolt axis (line y = y_h, along x) crosses the two faces
    xs = []
    for i in range(n):
        p, q = P[i], P[(i + 1) % n]
        if (p[1] - y_h) * (q[1] - y_h) < 0:
            xs.append(p[0] + (y_h - p[1]) / (q[1] - p[1]) * (q[0] - p[0]))
    x_concave, x_convex = sorted(xs)[:2]

    def hypothesis(S):
        r = np.linalg.norm(D - S, axis=1)
        return {"shaft_axis_xy_mm": [round(float(S[0]), 1), round(float(S[1]), 1)],
                "r_tipA_mm": round(float(np.linalg.norm(tipA - S)), 1),
                "r_tipB_mm": round(float(np.linalg.norm(tipB - S)), 1),
                "r_min_mm": round(float(r.min()), 1), "r_max_mm": round(float(r.max()), 1),
                "r_centroid_mm": round(float(np.linalg.norm(cen - S)), 1),
                "tipA_to_adjacent_tipA_mm": round(float(np.sqrt(3) * np.linalg.norm(tipA - S)), 1)}

    out = {
        "_source": "blades/v1.stl, sliced; frame as in ~/Downloads/turbine.STEP (inches). Calculated, not measured.",
        "_frame": "z along span (z=0 is the end farther from the holes); x along the bolt-hole axis; y across.",
        "bbox_mm": [round(float(e * 1000), 2) for e in m.extents],
        "span_mm": round(span, 2),
        "wall_at_square_edges_mm": [round(e, 3) for e in edge_faces],
        "wall_area_over_midline_mm": round(float(abs(area) / L_mid), 3),
        "face_lengths_mm": [round(v, 2) for v in len_faces],
        "section_area_mm2": round(float(abs(area)), 1),
        "centroid_xy_mm": [round(float(v), 2) for v in cen],
        "tipA_xy_mm": [round(float(v), 2) for v in tipA],
        "tipB_xy_mm": [round(float(v), 2) for v in tipB],
        "chord_tip_to_tip_mm": round(chord, 2),
        "chord_angle_to_bolt_axis_deg": round(float(np.degrees(np.arctan2(u[1], u[0]))), 1),
        "depth_chord_to_outer_face_mm": round(float(abs(dep[k])), 2),
        "depth_position_fraction_of_chord_from_tipA": round(float(((D[k] - tipA) @ u) / chord), 2),
        "midline_length_mm": round(L_mid, 2),
        "turning_deg_from_edge_normals": round(abs(turn_deg), 1),
        "single_circle_fit": {"radius_mm": round(float(whole[2]), 2), "rms_mm": round(whole_rms, 2)},
        "leg_radius_mm_s0.05-0.40": round(float(leg[2]), 1),
        "curl_radius_mm_s0.60-0.95": round(float(curl[2]), 1),
        "holes": holes,
        "hole_axis": "parallel to CAD x (STEP: two CYLINDRICAL_SURFACE, r = 0.100 in, direction (1,0,0))",
        "bolt_axis_crosses_concave_face_x_mm": round(float(x_concave), 2),
        "bolt_axis_crosses_convex_face_x_mm": round(float(x_convex), 2),
        "if_bolts_radial_R_to_concave_face": hypothesis(np.array([x_concave - R_ATTACH_MM, y_h])),
        "if_bolts_radial_R_to_convex_face": hypothesis(np.array([x_convex + R_ATTACH_MM, y_h])),
    }
    (HERE / "blade_section_cad.json").write_text(json.dumps(out, indent=1) + "\n")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(5.2, 7.2))
    Pc = np.vstack([P, P[:1]])
    ax.fill(Pc[:, 0], Pc[:, 1], color="0.75", ec="k", lw=0.8)
    ax.plot(M[:, 0], M[:, 1], "k:", lw=0.6)
    ax.plot([tipA[0], tipB[0]], [tipA[1], tipB[1]], "C0--", lw=1)
    ax.text((tipA[0] + tipB[0]) / 2 - 1, (tipA[1] + tipB[1]) / 2, f"chord {chord:.1f} mm",
            color="C0", ha="right", rotation=84, va="center", fontsize=8)
    arrow = dict(arrowstyle="-", lw=0.6)
    ax.plot(*tipA, "C3o", ms=4)
    ax.annotate("tip A (end of leg)", tipA, (8, 2), fontsize=8, color="C3", arrowprops=arrow)
    ax.plot(*tipB, "C3o", ms=4)
    ax.annotate("tip B (end of curl)", tipB, (0, 56), fontsize=8, color="C3", arrowprops=arrow)
    ax.axhline(y_h, color="C2", lw=0.8)
    ax.annotate("bolt-hole axis, y = %.1f mm\n2 holes, \u00d85.08 mm (0.200 in)" % y_h,
                (x_convex, y_h), (26.5, y_h - 6.5), fontsize=8, color="C2", arrowprops=arrow)
    ax.text(11, 22, "concave\nside", ha="center", fontsize=8)
    ax.text(32, 44, "convex\nside", ha="center", fontsize=8)
    ax.plot(*cen, "k+", ms=8)
    ax.annotate("centroid", cen, (cen[0] - 4, cen[1] + 6), fontsize=8, arrowprops=arrow)
    ax.set_xlim(-2, 42); ax.set_ylim(0, 58)
    ax.set_aspect("equal"); ax.grid(True, lw=0.3)
    ax.set_xlabel("x (mm, CAD frame, along bolt axis)"); ax.set_ylabel("y (mm, CAD frame)")
    ax.set_title("v1 blade section from blades/v1.stl (CAD, calculated)", fontsize=9)
    fig.tight_layout()
    fig.savefig(HERE / "blade_section_cad.png", dpi=150)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
