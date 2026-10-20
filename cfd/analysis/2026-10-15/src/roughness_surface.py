#!/usr/bin/env python3
"""Time-mean wall distributions (Cp, Cf, near-wall intermittency) of the alpha-180 texture runs at maxCo 2.5,
read directly from the final fields (analysis of 15 Oct 2026, roughness stage).

    nice -n 10 python3 cfd/analysis/2026-10-15/src/roughness_surface.py      # about 5 s

Why: the records' surface tables (cfd/stage2/results/records/<case>/fields/surface_mean.csv) cover only
896 of the 3425 blade faces (texture meshes; 121 of 459 on the wall-function meshes): the walk in
cfd/post/render_fields.py assumes one closed loop per wall patch, but the Stage 2 'blade' patch is two
open chains (convex and concave faces; the end faces are the separate patch 'bladeEnds'). This script
reads the binary OpenFOAM files itself.

Reads, read only (cfd/stage2/runs/<case>/):
  constant/polyMesh/{points,faces,owner,boundary}; <t_end>/{pMean,wallShearStressMean,UMean} (time means over
  the averaging window, fieldAverage from averageStart), <t_end>/gammaInt (LM only; instantaneous, final time);
  case.json, results.json.
Writes:
  ../out/roughness_surface_summary.csv   one row per case: force check against the table, pressure drag by face
                                         (convex, its two halves A and B, concave, ends), base pressure, suction
                                         peaks, separation (smooth faces), near-wall gamma statistics (LM)
  ../out/roughness_surface_profiles.csv  every fifth wall face (0.2 mm): face, s/c from tip A along the smooth
                                         face, Cp, Cf (signed), gamma, and their 1-mm running means
  ../fig/roughness_surface_a180.png      Cp along the convex face (23 m/s, SST and LM; LM at 18.8 and 25.2 m/s)
                                         and the convex-face pressure drag against U

Conventions:
  Body frame of the mesh (x_body, y_body, mesh_info.json); free stream along dragDir. At alpha 180 the convex
  (outer) face meets the wind; its stagnation point is the maximum of Cp on that face.
  s/c: arc length along each face from tip A (corner A_outer or A_inner), over c = 48 mm, measured on the smooth
  mesh: the texture meshes have the same blade faces in the same order (centres within t of the smooth ones,
  checked for every case), so every case uses the smooth face's arc length.
  Cp = p/(0.5 U^2) with kinematic p and p_inf = 0 (the far-field value; docs/RECORDS.md).
  Cf = |tau_w . t| / (0.5 U^2), signed + where the near-wall time-mean flow (owner-cell UMean) runs along +s.
  Pressure drag check: Cd_p = sum(p Sf . dragDir)/(0.5 U^2 Aref) over blade and bladeEnds (Sf out of the
  fluid, as the forces function object), compared with the table's Cd_pressure_mean (a time mean of the
  same window). Split by face: convex (outer), concave (inner), ends.
  Separation on the convex face (smooth runs only): the first point downstream of the stagnation point,
  going toward each tip, where the signed Cf (1-mm running mean) is reversed over at least 0.5 mm.
  Near-wall intermittency (LM): gammaInt in the wall cells (y+ about 0.1), final instantaneous field (the LM
  runs are near-steady at the end). It is reported (median, 1-mm maximum) but not used to locate transition:
  in the Langtry-Menter model the wall-cell value need not reach 1 in a turbulent layer (inferred), so a
  transition position would need the profile across the layer, which is not extracted here.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parents[2]
RUNS = REPO / "cfd" / "stage2" / "runs"
FIG, OUT = ROOT / "fig", ROOT / "out"

CASES = [
    "a180.0_U23.0_SST_tex0.000_s1_Tu1.0_Co2.5n2", "a180.0_U23.0_SST_tex0.200_s1_Tu1.0_Co2.5n2",
    "a180.0_U18.8_LM_tex0.000_s1_Tu1.0_Co2.5n2", "a180.0_U18.8_LM_tex0.200_s1_Tu1.0_Co2.5n2",
    "a180.0_U20.9_LM_tex0.000_s1_Tu1.0_Co2.5n2", "a180.0_U20.9_LM_tex0.200_s1_Tu1.0_Co2.5n2",
    "a180.0_U23.0_LM_tex0.000_s1_Tu1.0_Co2.5n2", "a180.0_U23.0_LM_tex0.100_s1_Tu1.0_Co2.5n2",
    "a180.0_U23.0_LM_tex0.200_s1_Tu1.0_Co2.5n2",
    "a180.0_U25.2_LM_tex0.000_s1_Tu1.0_Co2.5n2", "a180.0_U25.2_LM_tex0.200_s1_Tu1.0_Co2.5n2",
]
SEP_MIN = 0.5e-3        # m, a reversed-flow stretch shorter than this is not counted as separation
GAMMA_TR = 0.5


# ------------------------------------------------------------------ binary OpenFOAM readers
def _blocks(buf, start=0):
    """Yield (n, offset of the first byte after '(') for every 'N\\n(' binary list from start on."""
    for m in re.finditer(rb"\n(\d+)\n\(", buf[start:]):
        yield int(m.group(1)), start + m.end()


def read_list(path, dtype, ncomp=1, key=None):
    buf = Path(path).read_bytes()
    start = 0
    if key is not None:
        start = buf.index(key)
    n, off = next(_blocks(buf, start))
    a = np.frombuffer(buf, dtype=dtype, count=n * ncomp, offset=off)
    return a.reshape(n, ncomp) if ncomp > 1 else a


def read_faces(path):
    buf = Path(path).read_bytes()
    it = _blocks(buf)
    n1, o1 = next(it)
    offsets = np.frombuffer(buf, dtype="<i4", count=n1, offset=o1)
    n2, o2 = next(_blocks(buf, o1 + 4 * n1))
    labels = np.frombuffer(buf, dtype="<i4", count=n2, offset=o2)
    return offsets, labels


def read_boundary(path):
    txt = Path(path).read_text(errors="replace")
    out = {}
    for name, body in re.findall(r"\n\s*(\w+)\s*\n\s*\{([^}]*)\}", txt):
        nf = re.search(r"nFaces\s+(\d+);", body)
        sf = re.search(r"startFace\s+(\d+);", body)
        if nf and sf:
            out[name] = (int(sf.group(1)), int(nf.group(1)))
    return out


def patch_values(path, patch, ncomp):
    """The 'value nonuniform List<...>' of one boundary patch of a binary field file."""
    buf = Path(path).read_bytes()
    i = buf.index(b"boundaryField")
    j = buf.index(b"\n    " + patch.encode() + b"\n", i)
    k = buf.index(b"value", j)
    n, off = next(_blocks(buf, k))
    a = np.frombuffer(buf, dtype="<f8", count=n * ncomp, offset=off)
    return a.reshape(n, ncomp) if ncomp > 1 else a


def internal_values(path, ncomp):
    return read_list(path, "<f8", ncomp, key=b"internalField")


# ------------------------------------------------------------------ geometry
def chains(face_pts, pts):
    """Order the faces of a 2D wall patch into chains. Each face's two low-z points form a segment; segments
    sharing a point are neighbours. Returns a list of face-index arrays, each ordered along its chain."""
    zmid = np.median(pts[:, 2])
    segs = []
    for fp in face_pts:
        low = [p for p in fp if pts[p, 2] < zmid]
        segs.append(tuple(low[:2]))
    key = {}
    canon = {}
    for s in segs:
        for p in s:
            k = (round(float(pts[p, 0]), 10), round(float(pts[p, 1]), 10))
            canon[p] = key.setdefault(k, p)
    p2f = {}
    for i, s in enumerate(segs):
        for p in s:
            p2f.setdefault(canon[p], []).append(i)
    ends = [p for p, fs in p2f.items() if len(fs) == 1]
    out, used = [], set()
    for e in ends:
        if p2f[e][0] in used:
            continue
        order, cur, via = [], p2f[e][0], e
        while cur is not None:
            used.add(cur)
            order.append(cur)
            a, b = (canon[p] for p in segs[cur])
            via = b if a == via else a
            nxt = [f for f in p2f[via] if f != cur and f not in used]
            cur = nxt[0] if nxt else None
        out.append(np.array(order))
    return out, segs, canon


REF_T0 = "a180.0_U23.0_LM_tex0.000_s1_Tu1.0_Co2.5n2"   # smooth alpha-180 texture mesh: reference geometry
SMOOTH_FACES = 25        # 1 mm of wall (faces 40 um apart): running mean over the texture's facets


def mesh_blade(case_dir):
    pm = case_dir / "constant" / "polyMesh"
    pts = read_list(pm / "points", "<f8", 3)
    offsets, labels = read_faces(pm / "faces")
    owner = read_list(pm / "owner", "<i4")
    bnd = read_boundary(pm / "boundary")
    return pts, offsets, labels, owner, bnd


def face_geometry(pts, offsets, labels, fidx):
    face_pts = [labels[offsets[f]:offsets[f + 1]] for f in fidx]
    Sf = np.zeros((len(fidx), 3))
    cen = np.zeros((len(fidx), 3))
    for i, fp in enumerate(face_pts):
        xyz = pts[fp]
        cen[i] = xyz.mean(axis=0)
        v = np.zeros(3)
        for k in range(len(fp)):
            v += np.cross(xyz[k] - cen[i], xyz[(k + 1) % len(fp)] - cen[i])
        Sf[i] = 0.5 * v
    return face_pts, Sf, cen


_REF = {}


def reference_chains():
    """Chains of the smooth alpha-180 mesh, oriented from tip A, labelled convex/concave, with arc length (m).
    The texture meshes have the same blade faces in the same order (checked: centres within t of the smooth ones)."""
    if _REF:
        return _REF
    d = RUNS / REF_T0
    pts, offsets, labels, owner, bnd = mesh_blade(d)
    s0, nf = bnd["blade"]
    fidx = np.arange(s0, s0 + nf)
    face_pts, Sf, cen = face_geometry(pts, offsets, labels, fidx)
    ch, _, _ = chains(face_pts, pts)
    fr = json.loads((d / "mesh_info.json").read_text())["frame"]["corners_body_m"]
    for c in ch:
        xy = cen[c, :2]
        if xy[0, 1] > xy[-1, 1]:
            c, xy = c[::-1], xy[::-1]
        dA = {k: np.linalg.norm(xy[0] - np.array(v)) for k, v in fr.items()}
        face = "convex" if min(dA, key=dA.get) == "A_outer" else "concave"
        seg = np.linalg.norm(np.diff(xy, axis=0), axis=1)
        s = np.concatenate([[0.0], np.cumsum(seg)])
        tng = np.gradient(xy, axis=0)
        tng /= np.linalg.norm(tng, axis=1)[:, None]
        _REF[face] = dict(c=c, s=s, xy=xy, tng=tng, seg=np.r_[seg, seg[-1:]])
    _REF["centres"] = cen
    return _REF


def runmean(y, n=SMOOTH_FACES):
    return pd.Series(y).rolling(n, center=True, min_periods=1).mean().to_numpy()


def first_reversed(Cf_s, s, attached_sign, cref):
    """Distance (over c) from the start of the arrays to the first stretch of >= SEP_MIN where the smoothed signed
    Cf has the reversed sign; nan if none. Arrays run from the stagnation point toward a tip."""
    rev = np.sign(Cf_s) == -attached_sign
    rev &= np.abs(s - s[0]) > 1e-3                       # skip the stagnation region itself
    k = 0
    while k < len(rev):
        if rev[k]:
            j = k
            while j < len(rev) and rev[j]:
                j += 1
            if abs(s[min(j, len(s) - 1)] - s[k]) >= SEP_MIN:
                return abs(s[k] - s[0]) / cref
            k = j
        k += 1
    return float("nan")


def analyse_case(name):
    d = RUNS / name
    P = json.loads((d / "case.json").read_text())
    R = json.loads((d / "results.json").read_text())
    tdirs = sorted([p for p in d.iterdir() if re.fullmatch(r"[0-9.]+", p.name) and float(p.name) > 0],
                   key=lambda p: float(p.name))
    T = tdirs[-1]
    pts, offsets, labels, owner, bnd = mesh_blade(d)
    ref = reference_chains()
    q = 0.5 * P["Uinf"] ** 2
    drag = np.array(P["dragDir"][:2])
    Aref, cref = P["Aref"], P["cRef"]
    res = dict(name=name, model=P["model"], U=P["Uinf"], t_mm=round(P["texT"] * 1e3, 3), t_field=float(T.name),
               avg_from_c_U=float(R["avg_from_conv"]))
    Um = internal_values(T / "UMean", 3)
    gam = internal_values(T / "gammaInt", 1) if P["model"] == "LM" else None
    Fp, Fv, prof = np.zeros(2), np.zeros(2), []
    for patch in ("blade", "bladeEnds"):
        s0, nf = bnd[patch]
        fidx = np.arange(s0, s0 + nf)
        face_pts, Sf, cen = face_geometry(pts, offsets, labels, fidx)
        p = patch_values(T / "pMean", patch, 1)
        tau = patch_values(T / "wallShearStressMean", patch, 3)
        fp_face = p[:, None] * Sf[:, :2]
        Fp += fp_face.sum(axis=0)
        Fv -= (tau[:, :2] * np.linalg.norm(Sf, axis=1)[:, None]).sum(axis=0)   # wallShearStress acts on the fluid
        if patch == "bladeEnds":
            res["Cd_p_ends"] = float(fp_face.sum(axis=0) @ drag / (q * Aref))
            continue
        if not np.allclose(ref["centres"][:, :2], cen[:, :2], atol=P["texT"] + 2e-6):
            raise RuntimeError(f"{name}: blade faces do not match the reference mesh")
        for face in ("convex", "concave"):
            c, s, tng = ref[face]["c"], ref[face]["s"], ref[face]["tng"]
            own = owner[fidx[c]]
            sign = np.sign(np.sum(Um[own, :2] * tng, axis=1))
            Cp = p[c] / q
            Cf = sign * np.abs(np.sum(tau[c, :2] * tng, axis=1)) / q
            g = gam[own] if gam is not None else np.full(len(c), np.nan)
            res[f"Cd_p_{face}"] = float(fp_face[c].sum(axis=0) @ drag / (q * Aref))
            Cp_s, Cf_s, g_s = runmean(Cp), runmean(Cf), runmean(g)
            for i in range(len(c)):
                prof.append(dict(name=name, face=face, s_ref_over_c=s[i] / cref, Cp=Cp[i], Cf=Cf[i], gamma=g[i],
                                 Cp_1mm=Cp_s[i], Cf_1mm=Cf_s[i], gamma_1mm=g_s[i]))
            if face == "concave":
                res["Cp_base_mean"] = float(np.average(Cp, weights=ref[face]["seg"]))
                continue
            ist = int(np.argmax(Cp_s))
            res.update(stag_s_ref_over_c=s[ist] / cref, convex_len_ref_over_c=s[-1] / cref)
            half = {"A": np.arange(ist, -1, -1), "B": np.arange(ist, len(c))}
            for side, idx in half.items():
                attached = -1 if side == "A" else 1
                ss = s[idx]
                res[f"dist_{side}_to_tip_over_c"] = abs(ss[-1] - ss[0]) / cref
                res[f"Cp_min_{side}_1mm"] = float(Cp_s[idx].min())
                res[f"Cp_min_{side}_at_over_c"] = abs(ss[int(np.argmin(Cp_s[idx]))] - ss[0]) / cref
                # separation is located on the smooth faces only: on the textured faces the facet-scale wall shear
                # reverses in the valleys, and the 1-mm mean still reverses at the same two ridge groups in every
                # t-0.20 case whatever the model and speed (0.192 and 0.146 c from the stagnation point), i.e. at
                # geometric features, not at a separation of the boundary layer
                res[f"sep_{side}_from_stag_over_c"] = (first_reversed(Cf_s[idx], ss, attached, cref)
                                                       if P["texT"] == 0 else float("nan"))
                fp_side = fp_face[c][idx]
                res[f"Cd_p_convex_{side}"] = float(fp_side.sum(axis=0) @ drag / (q * Aref))
                if gam is not None:
                    inner = (np.abs(ss - ss[0]) > 2e-3) & (np.abs(ss - ss[-1]) > 1e-3)
                    res[f"gamma_{side}_median"] = float(np.median(g[idx][inner]))
                    res[f"gamma_{side}_max_1mm"] = float(g_s[idx][inner].max())
                    hit = np.where((g_s[idx] > GAMMA_TR) & inner)[0]
                    res[f"trans_{side}_from_stag_over_c"] = abs(ss[hit[0]] - ss[0]) / cref if hit.size else float("nan")
    res["Cd_p_fields"] = float(Fp @ drag / (q * Aref))
    res["Cd_p_table"] = float(R["Cd_pressure_mean"])
    res["Cd_v_fields"] = float(Fv @ drag / (q * Aref))
    res["Cd_v_table"] = float(R["Cd_viscous_mean"])
    res["Cd_table"] = float(R["Cd_mean"])
    res["Cl_table"] = float(R["Cl_mean"])
    return res, pd.DataFrame(prof)


def figure(S, Pr):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    sys.path.insert(0, str(HERE))
    import roughness_analysis as RA
    RA.style()
    INK2 = "#52514e"
    Si = S.set_index("name")
    fig, axes = plt.subplots(3, 1, figsize=(3.6, 8.1), constrained_layout=True,
                             gridspec_kw=dict(height_ratios=[1.1, 1.1, 1.0]))
    ax, bx, cx = axes

    def conv(name):
        p = Pr[(Pr.name == name) & (Pr.face == "convex")]
        return p.s_ref_over_c - Si.loc[name, "stag_s_ref_over_c"], p.Cp_1mm

    for name, col, ls, lab in (("a180.0_U23.0_SST_tex0.000_s1_Tu1.0_Co2.5n2", RA.BLACK, "--", "SST, smooth"),
                               ("a180.0_U23.0_SST_tex0.200_s1_Tu1.0_Co2.5n2", RA.RAMP[400], "--", "SST, t 0.20 mm"),
                               ("a180.0_U23.0_LM_tex0.000_s1_Tu1.0_Co2.5n2", RA.BLACK, "-", "LM, smooth"),
                               ("a180.0_U23.0_LM_tex0.200_s1_Tu1.0_Co2.5n2", RA.RAMP[400], "-", "LM, t 0.20 mm")):
        x, y = conv(name)
        ax.plot(x, y, color=col, ls=ls, lw=1.0, label=lab)
    for name, col, lw, lab in (("a180.0_U18.8_LM_tex0.000_s1_Tu1.0_Co2.5n2", RA.BLACK, 0.7, "smooth, 18.8 m/s"),
                               ("a180.0_U25.2_LM_tex0.000_s1_Tu1.0_Co2.5n2", RA.BLACK, 1.5, "smooth, 25.2 m/s"),
                               ("a180.0_U18.8_LM_tex0.200_s1_Tu1.0_Co2.5n2", RA.RAMP[400], 0.7, "t 0.20 mm, 18.8 m/s"),
                               ("a180.0_U25.2_LM_tex0.200_s1_Tu1.0_Co2.5n2", RA.RAMP[400], 1.5, "t 0.20 mm, 25.2 m/s")):
        x, y = conv(name)
        bx.plot(x, y, color=col, lw=lw, label=lab)
    for a_, t_ in ((ax, "(a) 23 m/s: SST and LM, smooth and t 0.20 mm"), (bx, "(b) LM at 18.8 and 25.2 m/s")):
        a_.invert_yaxis()
        a_.set_xlim(-0.8, 0.85)
        a_.set_ylabel("$C_p$, convex face (axis inverted)")
        a_.set_title(t_, loc="left")
        a_.text(-0.78, 0.92, "tip A", fontsize=6.2, color=INK2, va="bottom")
        a_.text(0.83, 0.92, "tip B", fontsize=6.2, color=INK2, va="bottom", ha="right")
        a_.legend(loc="upper left", fontsize=6.0, ncol=1, handlelength=2.2)
    bx.set_xlabel("s/c from the stagnation point (smooth convex face)")
    ax.set_xlabel("s/c from the stagnation point (smooth convex face)")
    # (c) convex-face pressure drag against U (LM), with SST at 23 m/s
    lm = S[S.model == "LM"].copy()
    for t_mm, col in ((0.0, RA.BLACK), (0.2, RA.RAMP[400])):
        g = lm[lm.t_mm == t_mm].sort_values("U")
        cx.plot(g.U, g.Cd_p_convex, color=col, marker="o", ms=4.5, lw=1.0, mfc=col, mec=col)
        r = S[(S.model == "SST") & (S.t_mm == t_mm)].iloc[0]
        cx.plot(23.25, r.Cd_p_convex, marker="s", ms=4.5, mfc=col, mec=col, ls="none")
    cc = {t: S[(S.model == "LM") & (S.t_mm == t)].Cd_p_concave for t in (0.0, 0.2)}
    ss = {t: S[(S.model == "SST") & (S.t_mm == t)].Cd_p_concave.iloc[0] for t in (0.0, 0.2)}
    cx.text(18.45, 0.352, f"concave face (base), for comparison: LM smooth {cc[0.0].min():.3f}\u2013{cc[0.0].max():.3f},\n"
            f"LM t 0.20 {cc[0.2].min():.3f}\u2013{cc[0.2].max():.3f}; SST {ss[0.0]:.3f} (smooth), {ss[0.2]:.3f} (t 0.20)",
            fontsize=5.8, color=INK2, ha="left", va="top")
    cx.set_xticks([18.8, 20.9, 23.0, 25.2])
    cx.set_xlim(18.3, 25.7)
    cx.set_ylim(0.06, 0.36)
    cx.set_xlabel("Wind speed U (m/s)")
    cx.set_ylabel("Convex-face pressure drag (\u2013)")
    cx.set_title("(c) Pressure drag on the convex face (its part of $C_d$)", loc="left")   # verifier: was "share"
    h = [Line2D([], [], color=RA.BLACK, marker="o", ms=4.5, lw=1.0, label="LM, smooth"),
         Line2D([], [], color=RA.RAMP[400], marker="o", ms=4.5, lw=1.0, label="LM, t 0.20 mm"),
         Line2D([], [], color=INK2, marker="s", ms=4.5, ls="none", label="SST, 23 m/s")]
    cx.legend(handles=h, loc="lower left", fontsize=6.0)
    fig.suptitle("\u03b1 = 180\u00b0, texture mesh, maxCo 2.5: time means over 50\u2013150 c/U;\n"
                 "$C_p$ smoothed over 1 mm of wall (25 faces)", fontsize=6.4, x=0.02, ha="left", color=INK2)
    out = FIG / "roughness_surface_a180.png"
    fig.savefig(out, dpi=200, facecolor="white")
    plt.close(fig)
    return out


def main():
    rows, profs = [], []
    for n in CASES:
        r, p = analyse_case(n)
        rows.append(r)
        profs.append(p)
        print(f"{n:45s} Cd_p {r['Cd_p_fields']:.4f} (table {r['Cd_p_table']:.4f}) Cd_v {r['Cd_v_fields']:+.4f} "
              f"(table {r['Cd_v_table']:+.4f}) | convex {r['Cd_p_convex']:+.4f} [A {r['Cd_p_convex_A']:+.4f} "
              f"B {r['Cd_p_convex_B']:+.4f}] concave {r['Cd_p_concave']:+.4f} ends {r['Cd_p_ends']:+.4f} | "
              f"base Cp {r['Cp_base_mean']:+.4f} | CpminA {r['Cp_min_A_1mm']:+.3f} CpminB {r['Cp_min_B_1mm']:+.3f} | "
              f"sepA {r['sep_A_from_stag_over_c']:.3f}/{r['dist_A_to_tip_over_c']:.3f} "
              f"sepB {r['sep_B_from_stag_over_c']:.3f}/{r['dist_B_to_tip_over_c']:.3f}"
              + (f" | gamma med A {r['gamma_A_median']:.3f} B {r['gamma_B_median']:.3f} max1mm A {r['gamma_A_max_1mm']:.2f}"
                 f" B {r['gamma_B_max_1mm']:.2f} trB {r['trans_B_from_stag_over_c']:.3f}" if r["model"] == "LM" else ""))
    S = pd.DataFrame(rows)
    Pr = pd.concat(profs)
    worst_p = float((S.Cd_p_fields - S.Cd_p_table).abs().max())
    worst_v = float((S.Cd_v_fields - S.Cd_v_table).abs().max())
    print(f"force check: max |Cd_p fields - table| {worst_p:.2e}, max |Cd_v fields - table| {worst_v:.2e}")
    assert worst_p < 2e-3 and worst_v < 2e-3, (worst_p, worst_v)
    OUT.mkdir(exist_ok=True)
    S.to_csv(OUT / "roughness_surface_summary.csv", index=False, float_format="%.6g")
    # written every fifth wall face (0.2 mm), which keeps the file small; the figure and the summary use every face
    k = Pr.groupby(["name", "face"]).cumcount()
    Pr[(k % 5) == 0].to_csv(OUT / "roughness_surface_profiles.csv", index=False, float_format="%.5g")
    print("wrote", figure(S, Pr))


if __name__ == "__main__":
    main()
