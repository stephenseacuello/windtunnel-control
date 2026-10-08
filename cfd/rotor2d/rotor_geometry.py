#!/usr/bin/env python3
"""Rotor assembly for the Stage 3 2D rotor model (cfd/PLAN.md stages 3a, 3b).

The blade section is the true v1 section (cfd/geometry/section_v1.json: clamped
cubic B-spline outer surface, constant 1.8542 mm wall, square ends), kept in its
CAD frame (x along the bolt-hole axis, y across, metres). Nothing here is
measured on the rig: the assembly is a hypothesis until cfd/inputs/rig_geometry.json
is filled in (cfd/MEASUREMENTS_NEEDED.md section 1).

Hypotheses (cfd/measurements/blade_section_cad.json, bolts radial):
  A  arm on the concave face: the cup opens toward the shaft; R = 101.6 mm from
     the shaft axis to the concave face where the bolt axis crosses it.
  B  arm on the convex face: the cup opens away from the shaft; R to the convex face.
  In both the bolt axis (CAD x) is radial, so the chord (tip-A to tip-B end-face
  midpoints) is at beta = 84.0 deg to the radius.
  measured  read cfd/inputs/rig_geometry.json (see pose_from_rig()).

Model frame (2D, metres): shaft axis at the origin, wind along +x, z = CAD +z
(span, from the far end toward the near end, the end nearer the holes). The model
is viewed from +z. If the near end is at the top on the rig, "viewed from +z" is
"viewed from above"; if it is at the bottom, the model is the mirror image and the
physical rotation sense is the opposite of the model's.

Rotation sense s: +1 = counter-clockwise about +z, -1 = clockwise. Default rule
("drag"): the cup must open against the direction of motion, so the blade moving
downwind meets the wind with its concave face. The cup-opening direction is the
mean fluid-side normal of the concave face, which is the inner-tip chord turned by
+90 deg. With bolts radial it is only 7.4 deg off the radial line (tangential
component 0.129), so the rule rests on that 7.4 deg; the mean static torque
(stage 3a, queues/priority0.txt) is the real test.

Azimuth theta (deg): blade 1's radial line (shaft -> attachment point) points
upwind (-x) at theta = 0; theta increases in the direction of rotation; blade k
sits at theta + 120 (k - 1). Torque Q is positive when it drives the rotor in its
rotation sense s, i.e. Q = s * M_z.

Usage:
    python3 cfd/rotor2d/rotor_geometry.py                 # summary of A and B, writes layout/
    python3 cfd/rotor2d/rotor_geometry.py --hyp measured  # once cfd/inputs/rig_geometry.json exists
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy.interpolate import BSpline
from scipy.optimize import brentq

HERE = Path(__file__).resolve().parent            # cfd/rotor2d
CFD = HERE.parent
SECTION_JSON = CFD / "geometry" / "section_v1.json"
CAD_JSON = CFD / "measurements" / "blade_section_cad.json"
RIG_JSON = CFD / "inputs" / "rig_geometry.json"
LAYOUT = HERE / "layout"

R_ATTACH = 0.1016        # m, shaft centre to where the blade meets the arm (data/tunnel.json, measured 25 Aug 2026)
SPAN = 0.2451            # m, blades/v1.json (CAD)
N_BLADES = 3


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def rot(v, a):
    """Rotate 2-vectors (..., 2) by angle a (rad), counter-clockwise."""
    v = np.asarray(v, float)
    c, s = math.cos(a), math.sin(a)
    return np.stack([c * v[..., 0] - s * v[..., 1], s * v[..., 0] + c * v[..., 1]], -1)


def rot90(v):
    v = np.asarray(v, float)
    return np.stack([-v[..., 1], v[..., 0]], -1)


# --------------------------------------------------------------------------- section (CAD frame)
class Section:
    """The v1 section in its CAD frame (metres). The wall is a closed loop
    parametrised by arc length s, counter-clockwise (solid on the left, fluid on
    the right): outer (convex) surface A->B, end face B, inner (concave) surface
    B->A, end face A. Built as cfd/section2d/mesh/make_mesh.py builds it (same
    spline, same constant-wall offset), but without moving to a body frame."""

    def __init__(self, path=SECTION_JSON):
        d = json.loads(Path(path).read_text())
        m = d["model"]
        self.source = str(Path(path).relative_to(CFD.parent))
        knots = np.array(m["outer_surface"]["knots"])
        ctrl = np.array(m["outer_surface"]["ctrl_xy_m"])
        self.wall = float(m["wall_m"])
        self.spl = BSpline(knots, ctrl, 3)
        self.dspl = self.spl.derivative()
        self.holes_y = float(np.mean([h["y_centre_m"] for h in d["holes"]["found"]]))
        n = 200001
        t = np.linspace(0, 1, n)
        P = self.spl(t)
        T = unit(self.dspl(t))
        Q = P + self.wall * rot90(T)                   # inner surface: left offset (into the cup)
        self._t = t
        self._so = np.r_[0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
        self._si = np.r_[0, np.cumsum(np.linalg.norm(np.diff(Q, axis=0), axis=1))]
        self.L_o, self.L_i = self._so[-1], self._si[-1]
        self.A_out, self.B_out = self.spl(0.0), self.spl(1.0)
        TA, TB = unit(self.dspl(0.0)), unit(self.dspl(1.0))
        self.A_in = self.A_out + self.wall * rot90(TA)
        self.B_in = self.B_out + self.wall * rot90(TB)
        self.L_eB = float(np.linalg.norm(self.B_in - self.B_out))
        self.L_eA = float(np.linalg.norm(self.A_out - self.A_in))
        self.L = self.L_o + self.L_eB + self.L_i + self.L_eA
        self.s_corner = np.array([self.L_o, self.L_o + self.L_eB, self.L_o + self.L_eB + self.L_i, self.L])
        self.P_corner = np.array([self.B_out, self.B_in, self.A_in, self.A_out])
        self.tipA = 0.5 * (self.A_out + self.A_in)     # end-face midpoints (MEASUREMENTS_NEEDED "tip A/B")
        self.tipB = 0.5 * (self.B_out + self.B_in)
        # dense closed outline (CCW) for areas, radii and plots
        self.outline = self.point(np.linspace(0, self.L, 4001)[:-1])[0]
        x, y = self.outline[:, 0], self.outline[:, 1]
        cr = x * np.roll(y, -1) - np.roll(x, -1) * y
        self.area = 0.5 * cr.sum()
        self.centroid = np.array([((x + np.roll(x, -1)) * cr).sum(), ((y + np.roll(y, -1)) * cr).sum()]) / (6 * self.area)
        # cup opening: integral of the concave face's fluid-side normal = rot90(B_in - A_in)
        self.n_cup = unit(rot90(self.B_in - self.A_in))
        self.chord_dir = unit(self.tipB - self.tipA)

    # ---- points and fluid-side normals on the wall (same layout as section2d)
    def _outer(self, s):
        t = np.interp(s, self._so, self._t)
        T = unit(self.dspl(t))
        return self.spl(t), np.stack([T[:, 1], -T[:, 0]], -1)

    def _inner(self, s_from_B):
        t = np.interp(self.L_i - s_from_B, self._si, self._t)
        T = unit(self.dspl(t))
        nl = rot90(T)
        return self.spl(t) + self.wall * nl, nl

    def point(self, s):
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

    def face_x_at_y(self, y, face):
        """x where the line y = const crosses the outer ('convex') or inner ('concave') surface
        on the back of the section (the bolt-hole region)."""
        def outer_y(t):
            return float(self.spl(t)[1]) - y

        def inner_y(t):
            T = unit(self.dspl(t))
            return float(self.spl(t)[1] + self.wall * rot90(T)[1]) - y

        f = outer_y if face == "convex" else inner_y
        tt = np.linspace(0, 1, 2001)
        v = np.array([f(t) for t in tt])
        k = np.flatnonzero(np.sign(v[:-1]) != np.sign(v[1:]))
        if k.size != 1:
            raise RuntimeError(f"line y = {y} crosses the {face} face {k.size} times")
        t0 = brentq(f, tt[k[0]], tt[k[0] + 1], xtol=1e-14)
        if face == "convex":
            return float(self.spl(t0)[0])
        T = unit(self.dspl(t0))
        return float(self.spl(t0)[0] + self.wall * rot90(T)[0])


# --------------------------------------------------------------------------- pose
def _acute_angle_deg(u, v):
    a = math.degrees(math.acos(min(1.0, abs(float(np.dot(unit(u), unit(v)))))))
    return a


def make_pose(sec, name, arm_face, P_att, e_r, sense="auto", source="", R=None, S=None):
    """Pose of blade 1 in the CAD frame. P_att: attachment point on the arm face;
    e_r: unit radial direction (shaft -> blade) in CAD; R: shaft-to-P_att distance.
    S (shaft axis in CAD) defaults to P_att - R e_r."""
    e_r = unit(e_r)
    if S is None:
        S = P_att - R * e_r
    R = float(np.linalg.norm(P_att - S))
    e_t = rot90(e_r)                               # counter-clockwise tangent (model frame +theta for s = +1)
    c_r = float(sec.n_cup @ e_r)
    c_t = float(sec.n_cup @ e_t)
    if sense == "auto":
        s = -1 if c_t > 0 else 1                   # cup opens against the motion (drag rule)
        rule = "drag rule: concave face meets the wind on the downwind-moving blade"
    else:
        s = {"CCW": 1, "CW": -1, "+1": 1, "-1": -1, 1: 1, -1: -1}[sense]
        rule = f"given ({sense})"
    r_out = np.linalg.norm(sec.outline - S, axis=1)
    rel = lambda P: (float((P - S) @ e_r), float((P - S) @ e_t))     # noqa: E731
    tA, tB = rel(sec.tipA), rel(sec.tipB)
    lead = "A" if s * tA[1] > s * tB[1] else "B"
    beta = _acute_angle_deg(sec.chord_dir, e_r)
    return dict(
        name=name, arm_face=arm_face, source=source,
        R_m=R, beta_deg=beta, sense=s, sense_rule=rule,
        S_cad=[float(v) for v in S], e_r_cad=[float(v) for v in e_r], P_att_cad=[float(v) for v in P_att],
        r_tipA_m=float(np.linalg.norm(sec.tipA - S)), r_tipB_m=float(np.linalg.norm(sec.tipB - S)),
        r_min_m=float(r_out.min()), r_max_m=float(r_out.max()),
        r_centroid_m=float(np.linalg.norm(sec.centroid - S)),
        cup_opening_radial=c_r, cup_opening_tangential_ccw=c_t,
        cup_opens="toward the shaft" if c_r < 0 else "away from the shaft",
        leading_tip=lead,
        tipA_rt_m=tA, tipB_rt_m=tB,
        tipA_to_next_tipA_m=float(math.sqrt(3) * np.linalg.norm(sec.tipA - S)),
    )


def pose_hypothesis(sec, hyp, R=R_ATTACH, beta_deg=None, sense="auto"):
    """A: arm on the concave face; B: arm on the convex face. Bolts radial (CAD x)
    unless beta_deg is given: then the radial line is turned about the attachment
    point so the chord makes beta_deg with it (sensitivity, MEASUREMENTS_NEEDED 1)."""
    y = sec.holes_y
    if hyp == "A":
        P = np.array([sec.face_x_at_y(y, "concave"), y])
        e_r = np.array([1.0, 0.0])
        face = "concave"
    elif hyp == "B":
        P = np.array([sec.face_x_at_y(y, "convex"), y])
        e_r = np.array([-1.0, 0.0])
        face = "convex"
    else:
        raise ValueError(hyp)
    beta_cad = _acute_angle_deg(sec.chord_dir, e_r)
    if beta_deg is not None:
        e_r = rot(e_r, -math.radians(beta_deg - beta_cad))
    src = f"cfd/measurements/blade_section_cad.json hypothesis {hyp} (bolts radial, CAD), R = {R * 1e3:.1f} mm"
    if beta_deg is not None:
        src += f", beta set to {beta_deg:g} deg"
    return make_pose(sec, hyp, face, P, e_r, sense, src, R=R)


def pose_from_rig(sec, path=RIG_JSON, sense=None):
    """Pose from cfd/inputs/rig_geometry.json (MEASUREMENTS_NEEDED.md section 5).
    * r_tipA_mm and r_tipB_mm given (means of the non-null blades): the shaft axis is
      the intersection of the two circles about the tips, on the concave side of the
      chord if arm_face is concave, else on the convex side. R and beta then follow.
    * otherwise: hypothesis A or B by arm_face, with attachment_radius_mm and
      setting_angle_deg if given.
    Rotation sense: rotation_sense_from_above with near_end (top: model = physical;
    bottom: mirrored), else the drag rule."""
    d = json.loads(Path(path).read_text())["rotor"]
    face = d.get("arm_face")
    if face not in ("concave", "convex"):
        raise ValueError(f"{path}: rotor.arm_face must be 'concave' or 'convex' (is {face!r})")
    R = (d.get("attachment_radius_mm") or R_ATTACH * 1e3) / 1e3
    if sense is None:
        sab, ne = d.get("rotation_sense_from_above"), d.get("near_end")
        if sab in ("CW", "CCW") and ne in ("top", "bottom"):
            s = (1 if sab == "CCW" else -1) * (1 if ne == "top" else -1)
            sense = "CCW" if s > 0 else "CW"
        else:
            sense = "auto"
    mean = lambda v: float(np.mean([x for x in v if x is not None])) / 1e3 if v and any(x is not None for x in v) else None  # noqa: E731
    rA, rB = mean(d.get("r_tipA_mm")), mean(d.get("r_tipB_mm"))
    y = sec.holes_y
    P = np.array([sec.face_x_at_y(y, face), y])
    if rA and rB:
        a, b = sec.tipA, sec.tipB
        dab = np.linalg.norm(b - a)
        x = (rA ** 2 - rB ** 2 + dab ** 2) / (2 * dab)
        h2 = rA ** 2 - x ** 2
        if h2 <= 0:
            raise ValueError(f"r_tipA {rA} and r_tipB {rB} are inconsistent with the {dab * 1e3:.2f} mm tip distance")
        u = (b - a) / dab
        nrm = rot90(u)
        cands = [a + x * u + math.sqrt(h2) * nrm, a + x * u - math.sqrt(h2) * nrm]
        want_concave = face == "concave"
        S = [c for c in cands if ((c - a) @ sec.n_cup > 0) == want_concave][0]
        e_r = unit(P - S)
        return make_pose(sec, "measured", face, P, e_r, sense,
                         f"{path.name}: tip radii r_A {rA * 1e3:.1f}, r_B {rB * 1e3:.1f} mm; arm on {face} face", S=S)
    beta = d.get("setting_angle_deg")
    p = pose_hypothesis(sec, "A" if face == "concave" else "B", R, beta, sense)
    p["name"] = "measured"
    p["source"] = f"{path.name}: arm on {face} face, R {R * 1e3:.1f} mm, beta {beta if beta is not None else 'CAD 84'}"
    return p


def get_pose(hyp, sec=None, R=R_ATTACH, beta_deg=None, sense="auto"):
    sec = sec or Section()
    if hyp == "measured":
        return pose_from_rig(sec, sense=None if sense == "auto" else sense)
    return pose_hypothesis(sec, hyp, R, beta_deg, sense)


# --------------------------------------------------------------------------- model frame
def blade_transform(pose, theta_deg, k):
    """(Rm, S): model point p = Rm @ (P_cad - S) for blade k (1..3) at rotor azimuth theta."""
    s = pose["sense"]
    phi = math.pi + s * math.radians(theta_deg + 120.0 * (k - 1))
    er = np.array(pose["e_r_cad"])
    a = phi - math.atan2(er[1], er[0])
    c, sn = math.cos(a), math.sin(a)
    return np.array([[c, -sn], [sn, c]]), np.array(pose["S_cad"])


def to_model(pose, P_cad, theta_deg, k):
    Rm, S = blade_transform(pose, theta_deg, k)
    return (np.atleast_2d(np.asarray(P_cad, float)) - S) @ Rm.T


def summary_row(p):
    mm = lambda v: round(v * 1e3, 2)  # noqa: E731
    return {"hypothesis": p["name"], "arm_face": p["arm_face"], "R_mm": mm(p["R_m"]), "beta_deg": round(p["beta_deg"], 2),
            "r_tipA_mm": mm(p["r_tipA_m"]), "r_tipB_mm": mm(p["r_tipB_m"]), "r_min_mm": mm(p["r_min_m"]),
            "r_max_mm": mm(p["r_max_m"]), "r_centroid_mm": mm(p["r_centroid_m"]),
            "tipA_to_next_tipA_mm": mm(p["tipA_to_next_tipA_m"]), "cup_opens": p["cup_opens"],
            "cup_opening_dir_radial_tangential": [round(p["cup_opening_radial"], 4), round(p["cup_opening_tangential_ccw"], 4)],
            "rotation_sense_model": "CCW" if p["sense"] > 0 else "CW", "sense_rule": p["sense_rule"],
            "leading_tip": p["leading_tip"]}


# --------------------------------------------------------------------------- plot
def plot_layouts(poses, path, r_ami=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, FancyArrowPatch
    sec = Section()
    fig, axs = plt.subplots(1, len(poses), figsize=(6.4 * len(poses), 7.2))
    axs = np.atleast_1d(axs)
    for ax, p in zip(axs, poses):
        ra = (r_ami[p["name"]] if isinstance(r_ami, dict) else r_ami) if r_ami else p["r_max_m"]
        lim = 1e3 * max(0.16, 1.12 * ra)
        for k in (1, 2, 3):
            P = to_model(p, sec.outline, 0.0, k) * 1e3
            ax.fill(P[:, 0], P[:, 1], color="0.55" if k > 1 else "C3", ec="k", lw=0.6, zorder=3)
            att = to_model(p, np.array(p["P_att_cad"]), 0.0, k)[0] * 1e3
            ax.plot([0, att[0]], [0, att[1]], color="0.35", lw=2.2, solid_capstyle="butt", zorder=2)
            for tip, lab in ((sec.tipA, "A"), (sec.tipB, "B")):
                q = to_model(p, tip, 0.0, k)[0] * 1e3
                d = q / np.linalg.norm(q)
                ax.annotate(lab, q, q + 9 * d * (1 if lab == "B" else 1), fontsize=7, ha="center", va="center", zorder=4)
            c0 = to_model(p, sec.centroid, 0.0, k)[0] * 1e3
            n = (to_model(p, sec.centroid + 0.012 * sec.n_cup, 0.0, k)[0] * 1e3) - c0
            ax.add_patch(FancyArrowPatch(c0, c0 + n, arrowstyle="->", mutation_scale=8, color="C0", lw=1, zorder=5))
            ax.text(*(att * 0.55), f"{k}", fontsize=8, color="0.2", ha="center", va="center",
                    bbox=dict(boxstyle="circle,pad=0.15", fc="w", ec="0.5", lw=0.5), zorder=4)
        for r, st, lab in ((p["R_m"], ":", "R"), (p["r_max_m"], "--", "r_max")):
            ax.add_patch(Circle((0, 0), r * 1e3, fill=False, ls=st, lw=0.7, ec="0.4"))
        if r_ami:
            ra = r_ami[p["name"]] if isinstance(r_ami, dict) else r_ami
            ax.add_patch(Circle((0, 0), ra * 1e3, fill=False, ls="-", lw=0.7, ec="C2"))
            ax.text(0, -ra * 1e3 - 6, "AMI", color="C2", fontsize=7, ha="center", va="top")
        ax.plot(0, 0, "k+", ms=8)
        # wind
        ax.add_patch(FancyArrowPatch((-0.98 * lim, 0.82 * lim), (-0.62 * lim, 0.82 * lim), arrowstyle="-|>",
                                     mutation_scale=14, color="k"))
        ax.text(-0.8 * lim, 0.86 * lim, "wind", ha="center", fontsize=9)
        # rotation sense
        s = p["sense"]
        a0, a1 = (math.radians(30), math.radians(70))
        rr = 0.35 * lim
        if s < 0:
            a0, a1 = a1, a0
        arc = FancyArrowPatch((rr * math.cos(a0), rr * math.sin(a0)), (rr * math.cos(a1), rr * math.sin(a1)),
                              connectionstyle=f"arc3,rad={0.25 * s}", arrowstyle="-|>", mutation_scale=12, color="C1", lw=1.4)
        ax.add_patch(arc)
        ax.text(0.42 * lim * math.cos(math.radians(50)), 0.42 * lim * math.sin(math.radians(50)),
                "CCW" if s > 0 else "CW", color="C1", fontsize=9)
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-lim, lim)
        ax.set_aspect("equal")
        ax.grid(True, lw=0.3)
        ax.set_xlabel("x (mm), wind direction")
        ax.set_ylabel("y (mm)")
        ax.set_title(f"Hypothesis {p['name']}: arm on the {p['arm_face']} face\n"
                     f"R {p['R_m'] * 1e3:.1f} mm, beta {p['beta_deg']:.1f} deg, r {p['r_min_m'] * 1e3:.1f}-{p['r_max_m'] * 1e3:.1f} mm, "
                     f"{'CCW' if s > 0 else 'CW'} (viewed from CAD +z), leading tip {p['leading_tip']}", fontsize=9)
    fig.suptitle("2D rotor layouts at theta = 0 (blade 1 red, upwind). Grey bars: arm along the bolt axis to the "
                 "attachment point.\nBlue arrows: cup-opening direction (mean normal of the concave face). "
                 "Inferred from CAD; not measured.", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hyp", nargs="+", default=["A", "B"], help="A, B and/or measured")
    ap.add_argument("--beta", type=float, help="override the chord-to-radius angle (deg) for A/B")
    ap.add_argument("--R", type=float, default=R_ATTACH, help="attachment radius, m")
    ap.add_argument("--ami-margin", type=float, default=0.022, help="AMI radius minus r_max (mesh/make_mesh.py), m")
    ap.add_argument("--no-plot", action="store_true")
    a = ap.parse_args()
    sec = Section()
    poses = [get_pose(h, sec, a.R, a.beta) for h in a.hyp]
    out = {"section": dict(source=sec.source, wall_m=sec.wall, area_m2=float(sec.area), holes_y_m=sec.holes_y,
                           tipA_cad_m=sec.tipA.tolist(), tipB_cad_m=sec.tipB.tolist(),
                           chord_tip_to_tip_m=float(np.linalg.norm(sec.tipB - sec.tipA)),
                           cup_opening_dir_cad=sec.n_cup.tolist()),
           "conventions": __doc__.split("Model frame")[1].split("Usage:")[0].strip(),
           "poses": poses, "summary": [summary_row(p) for p in poses]}
    cad = json.loads(CAD_JSON.read_text())
    chk = {}
    for p in poses:
        key = {"A": "if_bolts_radial_R_to_concave_face", "B": "if_bolts_radial_R_to_convex_face"}.get(p["name"])
        if key and a.beta is None and abs(a.R - R_ATTACH) < 1e-12:
            ref = cad[key]
            chk[p["name"]] = {k: [ref[k + "_mm"], round(p[k + "_m"] * 1e3, 2)] for k in ("r_tipA", "r_tipB", "r_min", "r_max", "r_centroid")}
    out["check_vs_blade_section_cad_json"] = chk
    LAYOUT.mkdir(exist_ok=True)
    tag = "_".join(a.hyp) + (f"_beta{a.beta:g}" if a.beta is not None else "")
    (LAYOUT / f"poses_{tag}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({"summary": out["summary"], "check (CAD json, this)": chk}, indent=1))
    if not a.no_plot:
        plot_layouts(poses, LAYOUT / f"layouts_{tag}.png", {p["name"]: p["r_max_m"] + a.ami_margin for p in poses})
        print(f"wrote {LAYOUT / f'layouts_{tag}.png'}")


if __name__ == "__main__":
    main()
