"""Field images of one OpenFOAM case (section or rotor), rendered with ParaView offscreen.

    PV=/Applications/ParaView-6.2.0.app/Contents/bin/pvbatch
    $PV --force-offscreen-rendering cfd/post/render_fields.py <case_dir> --out <dir>
    $PV --force-offscreen-rendering cfd/post/render_fields.py cfd/section2d/runs/_mesh/medium_a000.0 --out /tmp/m
        (a mesh folder with no fields: mesh images only)
    options: --time latest|<value>   field time to render (default: latest)
             --no-anim               skip the vorticity animation / frame strip
             --kind section|rotor    override the automatic choice
             --size 1200x800         image size in pixels
             --allow-running         render even if the case looks busy (read-only anyway)

Safe on any case: it reads the case through a temporary folder of symlinks plus an
empty case.foam (record_lib.make_shadow), so nothing in the case is written, and
decomposed cases are read directly from processor*/ (no reconstructPar needed). By
default it refuses a case that is RUNNING (marker file, a log written in the last 3
minutes, or a live solver process), because processor folders may be half-written.

Images (PNG, palette-quantised to keep records small), all viewed down the z axis of
the 2D slab, sliced at mid-depth:
  mesh_domain, mesh_near           whole domain; 3-4 chords (section) or the rotor
  mesh_cornerA_6mm, _0p8mm, _0p1mm square corner of the blade end, three zooms, so the
                                   wall-normal layers (first cell height h0) are visible
  mesh_ami (rotor)                 the sliding interface between rotor and stator zones
  velocity_<view>                  |U| / U_inf, 0 to 1.6
  vorticity_<view>                 omega_z L / U_inf, -20 to 20 (L = c_ref = 48 mm for the
                                   section, D for the rotor); red = counter-clockwise
  cp_<view>                        Cp = (p - p_inf) / (0.5 U_inf^2), -3 to 1 (kinematic p;
                                   p_inf = 0, the far-field value, for the section; the
                                   inlet-patch mean for the rotor)
  nut_ratio_<view>                 nu_t / nu, log scale 1 to 1000
  lic_near, streamlines_near       line-integral convolution and streamlines of U (of the
                                   time-mean UMean when fieldAverage wrote it)
  gammaInt_near                    intermittency (kOmegaSSTLM runs only), 0 to 1
  *_mean_*                         the same for UMean / pMean when they exist
  surface_<time>.csv / .png        Cp, Cf and y+ along the blade wall (ordered loop, s/c)
  vorticity_anim.gif or vorticity_frames.png
                                   vorticity at every saved write time (only if two or
                                   more exist); labelled with the frame spacing against
                                   the shedding period so aliasing is visible
The colour ranges are fixed per quantity, so images of different cases compare directly.
Values outside a range take the end colour of the bar (e.g. Cp > 1 in an impulsive start).
Surfaces are drawn unlit, so a pixel has exactly the colour-bar colour of its value, and the
palette quantisation keeps 128 entries sampled along the colour map(s) on screen. Every field
image states its view height (the length scale).
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import record_lib as rl  # noqa: E402

import numpy as np  # noqa: E402
from paraview import servermanager as sm  # noqa: E402
from paraview.simple import (Calculator, ColorBy, CreateView, ExtractBlock, GetColorTransferFunction,  # noqa: E402
                             GetScalarBar, Gradient, Hide, OpenFOAMReader, Render, SaveScreenshot, Show,
                             Slice, StreamTracer, Text)
from vtkmodules.numpy_interface import dataset_adapter as dsa  # noqa: E402
from vtkmodules.vtkCommonDataModel import vtkStaticPointLocator  # noqa: E402
from vtkmodules.vtkFiltersCore import vtkAppendFilter, vtkCellCenters  # noqa: E402

# fixed colour ranges, so cases are comparable
RANGES = dict(Umag=(0.0, 1.6), vort=(-20.0, 20.0), Cp=(-3.0, 1.0), nutr=(1.0, 1000.0), gamma=(0.0, 1.0))
PRESETS = dict(Umag=("Viridis", "Viridis (matplotlib)"), vort=("Cool to Warm",), Cp=("Turbo", "Jet"),
               nutr=("Inferno", "Inferno (matplotlib)"), gamma=("Viridis", "Viridis (matplotlib)"))
TITLES = dict(Umag="|U| / U_inf", vort="omega_z L / U_inf", Cp="Cp = (p - p_inf) / (0.5 U_inf^2)",
              nutr="nu_t / nu  (log scale)", gamma="intermittency gammaInt")
BG = [0.42, 0.42, 0.45]          # grey: the blade (a hole in the mesh) shows as a grey solid


def _try(obj, prop, val):
    """Set a ParaView property if this version has it (names vary between releases)."""
    try:
        setattr(obj, prop, val)
        return True
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- case info
def case_info(case, kind):
    P = rl.load_json(case / "case.json", {}) or {}
    M = rl.load_json(case / "mesh_info.json", {}) or {}
    info = dict(name=case.name, kind=kind, P=P, M=M)
    if kind == "section":
        c = P.get("cRef", M.get("c_ref_m", 0.048))
        info.update(L=c, Lname="c", dz=P.get("dz", M.get("dz_m", 1e-3)), U=P.get("Uinf"),
                    nu=P.get("nu", 1.516e-5), alpha=P.get("alphaDeg", M.get("alpha_deg_wake", 0.0)),
                    model=P.get("turbulenceModel", ""), level=P.get("level", M.get("level", "")),
                    t_ref=P.get("convTime"), t_lab="c/U", c_s=c, patches=["blade"])
    else:
        D = P.get("D", M.get("D_rotor_m", 0.2128))
        info.update(L=D, Lname="D", dz=P.get("dz", M.get("dz_m", 0.01)), U=P.get("Uinf"),
                    nu=P.get("nu", 1.516e-5), alpha=0.0, model=P.get("turbulenceModel", ""),
                    level=M.get("level", ""), c_s=0.048, patches=["blade1", "blade2", "blade3"])
        if P.get("mode") == "rotating":
            info.update(t_ref=P["Trev"], t_lab="rev")
        else:
            info.update(t_ref=P.get("convTime"), t_lab="D/U")
    return info


def corners(info):
    """Corner points (x, y) of the blade end faces for the close-ups."""
    M = info["M"]
    if info["kind"] == "section":
        cb = (M.get("frame") or {}).get("corners_body_m")
        if cb:
            return {k: tuple(v) for k, v in cb.items()}
    return None


# --------------------------------------------------------------------------- pipeline
class Scene:
    def __init__(self, info, shadow, size):
        self.info, self.size = info, size
        self.r = OpenFOAMReader(FileName=str(shadow["path"] / "case.foam"))
        self.r.CaseType = "Decomposed Case" if shadow["case_type"] == "decomposed" else "Reconstructed Case"
        self.r.SkipZeroTime = 0
        self.r.Createcelltopointfiltereddata = 1
        try:
            self.r.Refresh()            # re-scan so the 0/ fields are listed when 0 is the only time
        except Exception:  # noqa: BLE001
            pass
        self.r.UpdatePipelineInformation()
        avail = list(self.r.GetProperty("MeshRegions").Available)
        self.patches = [p for p in info["patches"] if f"patch/{p}" in avail]
        regions = ["internalMesh"] + [f"patch/{p}" for p in self.patches]
        if "patch/inlet" in avail:
            regions.append("patch/inlet")
        self.ami = None
        if "patch/AMI1" in avail:
            regions.append("patch/AMI1")
        self.r.MeshRegions = regions
        self.cell_arrays = list(self.r.GetProperty("CellArrays").Available)
        keep = [a for a in self.cell_arrays if a in ("U", "p", "nut", "k", "omega", "gammaInt", "ReThetat",
                                                     "wallShearStress", "UMean", "pMean", "wallShearStressMean")]
        self.r.CellArrays = keep
        self.arrays = keep
        self.times = list(self.r.TimestepValues) if self.r.TimestepValues else []
        if isinstance(self.r.TimestepValues, float):
            self.times = [self.r.TimestepValues]
        self.internal = ExtractBlock(Input=self.r, Selectors=["/Root/internalMesh"])
        self.fields = bool({"U", "p"} & set(keep))
        self.has_mean = "UMean" in keep and "pMean" in keep
        src = self.internal
        U = info["U"] or 1.0
        nu = info["nu"]
        q = 0.5 * U * U
        self.calcs = []
        self.pinf = 0.0
        if self.fields:
            exprs = []
            if "U" in keep:
                exprs.append(("Umag", f"mag(U)/{U!r}"))
            if "p" in keep:
                exprs.append(("Cp", f"(p-PINF)/{q!r}"))
            if "nut" in keep:
                exprs.append(("nutr", f"nut/{nu!r}+1e-3"))     # +1e-3 keeps the log scale defined at walls
            if "UMean" in keep:
                exprs.append(("Umag_mean", f"mag(UMean)/{U!r}"))
            if "pMean" in keep:
                exprs.append(("Cp_mean", f"(pMean-PINF)/{q!r}"))
            for name, ex in exprs:
                src = Calculator(Input=src, AttributeType="Point Data", ResultArrayName=name, Function=ex)
                self.calcs.append((src, ex))
            if "U" in keep:
                src = Gradient(Input=src, ScalarArray=["POINTS", "U"], ComputeVorticity=1, ComputeGradient=0,
                               VorticityArrayName="Vorticity")
                src = Calculator(Input=src, AttributeType="Point Data", ResultArrayName="vort",
                                 Function=f"Vorticity_Z*{info['L']!r}/{U!r}")
        self.sl = Slice(Input=src)
        self.sl.SliceType = "Plane"
        self.sl.SliceType.Origin = [0.0, 0.0, 0.5 * info["dz"]]
        self.sl.SliceType.Normal = [0.0, 0.0, 1.0]
        self.sl.Triangulatetheslice = 0
        if "patch/AMI1" in regions:
            self.ami = Slice(Input=ExtractBlock(Input=self.r, Selectors=["/Root/boundary/AMI1"]))
            self.ami.SliceType = "Plane"
            self.ami.SliceType.Origin = [0.0, 0.0, 0.5 * info["dz"]]
            self.ami.SliceType.Normal = [0.0, 0.0, 1.0]
        self.view = CreateView("RenderView")
        v = self.view
        v.ViewSize = list(size)
        v.OrientationAxesVisibility = 0
        for prop, val in (("UseColorPaletteForBackground", 0), ("BackgroundColorMode", "Single Color")):
            _try(v, prop, val)
        v.Background = BG
        v.CameraParallelProjection = 1
        self.reps = []
        self.luts = []              # (lut, lo, hi, log) of the colour maps on screen, for quantise()
        self.text = Text(Text="")
        self.trep = Show(self.text, v)
        self.trep.WindowLocation = "Upper Left Corner"
        self.trep.FontSize = 15
        self.trep.Color = [0.0, 0.0, 0.0]
        for prop, val in (("BackgroundColor", [1.0, 1.0, 1.0, 0.85]), ("BackgroundOpacity", 0.85),
                          ("ShowBorder", "Always")):
            _try(self.trep, prop, val)
        self.first = True

    def set_time(self, t):
        self.t = t
        self.view.ViewTime = t
        if self.fields and self.info["kind"] == "rotor" and self.calcs:
            self.pinf = self.inlet_pressure(t)
        for c, ex in self.calcs:
            c.Function = ex.replace("PINF", repr(self.pinf))
        self.sl.UpdatePipeline(t)

    def inlet_pressure(self, t):
        try:
            b = ExtractBlock(Input=self.r, Selectors=["/Root/boundary/inlet"])
            b.UpdatePipeline(t)
            d = sm.Fetch(b)
            arr = None
            it = d.NewIterator()
            it.InitTraversal()
            while not it.IsDoneWithTraversal():
                blk = it.GetCurrentDataObject()
                if blk.GetCellData().GetArray("p") is not None:
                    arr = dsa.WrapDataObject(blk).CellData["p"]
                it.GoToNextItem()
            return float(np.mean(arr)) if arr is not None else 0.0
        except Exception:  # noqa: BLE001
            return 0.0

    # ---- display helpers
    def clear(self):
        for r in self.reps:
            Hide(r[0], self.view)
        self.reps = []
        self.luts = []
        for name in RANGES:
            try:
                GetScalarBar(GetColorTransferFunction(name), self.view).Visibility = 0
            except Exception:  # noqa: BLE001
                pass

    def show(self, src, rep_type="Surface", color=None, array=None, key=None, line_width=1.0, opacity=1.0,
             bar=True):
        d = Show(src, self.view)
        d.SetRepresentationType(rep_type)
        d.Opacity = opacity
        d.LineWidth = line_width
        # unlit: with the default light kit the slab is drawn about 25 % darker than its colour bar
        # (measured on the 7 Oct records), so values read off the bar were biased low
        for prop, val in (("Ambient", 1.0), ("Diffuse", 0.0), ("Specular", 0.0)):
            _try(d, prop, val)
        if array is None:
            try:
                ColorBy(d, None)
            except RuntimeError:
                d.ColorArrayName = ["POINTS", ""]
            d.AmbientColor = d.DiffuseColor = color or [1.0, 1.0, 1.0]
        else:
            ColorBy(d, ("POINTS", array))
            lut = GetColorTransferFunction(array)
            k = key or array
            if k == "Cp":
                # diverging about Cp = 0: blue suction, white free stream, red stagnation
                lut.ColorSpace = "Lab"
                lut.RGBPoints = [-3.0, 0.02, 0.06, 0.32, -1.5, 0.15, 0.35, 0.80, -0.5, 0.62, 0.78, 0.96,
                                 0.0, 0.97, 0.97, 0.97, 0.5, 0.96, 0.62, 0.45, 1.0, 0.62, 0.02, 0.12]
            else:
                for preset in PRESETS[k]:
                    try:
                        lut.ApplyPreset(preset, True)
                        break
                    except RuntimeError:
                        continue
            lut.AutomaticRescaleRangeMode = "Never"
            lo, hi = RANGES[k]
            lut.RescaleTransferFunction(lo, hi)
            if k == "nutr":
                lut.MapControlPointsToLogSpace()
                lut.UseLogScale = 1
            else:
                lut.UseLogScale = 0
            self.luts.append((lut, lo, hi, k == "nutr"))
            sb = GetScalarBar(lut, self.view)
            sb.Title = TITLES[k]
            sb.ComponentTitle = ""
            sb.Orientation = "Horizontal"
            sb.WindowLocation = "Lower Center"
            sb.ScalarBarLength = 0.45
            sb.TitleColor = sb.LabelColor = [0.0, 0.0, 0.0]
            sb.TitleFontSize = 15
            sb.LabelFontSize = 13
            _try(sb, "RangeLabelFormat", "{:.3g}")
            for prop, val in (("DrawScalarBarOutline", 0), ("UseCustomLabels", 0), ("DrawBackground", 1),
                              ("BackgroundColor", [1, 1, 1, 0.85]), ("BackgroundPadding", 4.0)):
                _try(sb, prop, val)
            sb.Visibility = 1 if bar else 0
        self.reps.append((src, d))
        return d

    def camera(self, cx, cy, half_h):
        v = self.view
        if self.first:
            Render(v)
            self.first = False
        v.CameraPosition = [cx, cy, 1.0]
        v.CameraFocalPoint = [cx, cy, 0.0]
        v.CameraViewUp = [0.0, 1.0, 0.0]
        v.CameraParallelScale = half_h

    def save(self, path, lines, colors=256):
        self.text.Text = "\n".join(lines)
        Render(self.view)
        SaveScreenshot(str(path), self.view, ImageResolution=list(self.size))
        quantise(path, colors, self.lut_colours(colors // 2))
        print(f"  {Path(path).name}", flush=True)

    def lut_colours(self, n_total):
        """About n_total colours sampled evenly along the colour maps on screen (log-spaced for a
        log map). quantise() reserves palette entries for them, so the full colour range survives."""
        if not self.luts:
            return []
        n = max(16, n_total // len(self.luts))
        out = []
        try:
            for lut, lo, hi, log in self.luts:
                ctf = lut.GetClientSideObject()
                for i in range(n):
                    f = i / (n - 1)
                    rgb = [0.0, 0.0, 0.0]
                    ctf.GetColor(lo * (hi / lo) ** f if log else lo + f * (hi - lo), rgb)
                    out.append(tuple(int(round(255 * min(1.0, max(0.0, c)))) for c in rgb))
        except Exception as e:  # noqa: BLE001
            print(f"  (colour-map sampling failed, adaptive palette only: {e})")
            return []
        return out


def quantise(path, colors=256, fixed=None):
    """Palette-quantise a PNG (3-4x smaller). With `fixed` (colour-map samples), those colours
    are kept as palette entries and the rest of the palette is adaptive (median cut). Median cut
    alone gives most entries to the commonest colour (the free stream) and merges the rarer
    colour-map colours into a few bands: on the 7 Oct records |U|/U_inf 1.4 to 1.6 came out as
    one colour, and the LIC colour bar as six bands."""
    try:
        from PIL import Image
        im = Image.open(path).convert("RGB")
        if fixed:
            fixed = list(dict.fromkeys(fixed))[: colors // 2]
            n_ad = colors - len(fixed)
            ad = im.quantize(colors=n_ad, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
            flat = [c for rgb in fixed for c in rgb] + (ad.getpalette() or [])[: 3 * n_ad]
            flat = (flat + [0] * 768)[:768]
            pal = Image.new("P", (1, 1))
            pal.putpalette(flat)
            q = im.quantize(palette=pal, dither=Image.Dither.NONE)
        else:
            q = im.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        q.save(path, optimize=True)
    except Exception as e:  # noqa: BLE001
        print(f"  (no quantisation: {e})")


# --------------------------------------------------------------------------- views
def views(info, S):
    """name -> (cx, cy, half height) in metres."""
    a = math.radians(info["alpha"])
    ca, sa = math.cos(a), math.sin(a)
    if info["kind"] == "section":
        c = info["L"]
        R = (info["M"].get("r_farfield_m") or 27 * c)
        v = dict(domain=(0.0, 0.0, 1.08 * R), near=(0.25 * c * ca, 0.25 * c * sa, 1.25 * c),
                 wake=(3.8 * c * ca, 3.8 * c * sa, 3.4 * c))
    else:
        D = info["L"]
        dom = info["M"].get("domain") or {}
        x0, x1 = dom.get("x_in", -12 * D), dom.get("x_out", 30 * D)
        y0, y1 = dom.get("y_lo", -18 * D), dom.get("y_hi", 18 * D)
        v = dict(domain=(0.5 * (x0 + x1), 0.5 * (y0 + y1), 0.55 * max(y1 - y0, (x1 - x0) / 1.5)),
                 near=(0.0, 0.0, 0.75 * D), wake=(2.0 * D, 0.0, 1.6 * D))
    return v


def wall_loops(S, t):
    """Ordered wall loops per blade patch at time t: list of dicts with arrays."""
    info = S.info
    d_int = sm.Fetch(S.internal)
    ug = None
    it = d_int.NewIterator()
    it.InitTraversal()
    while not it.IsDoneWithTraversal():
        ug = it.GetCurrentDataObject()
        it.GoToNextItem()
    cc = vtkCellCenters()
    cc.SetInputData(ug)
    cc.Update()
    cpts = dsa.WrapDataObject(cc.GetOutput()).Points
    loc = vtkStaticPointLocator()
    loc.SetDataSet(cc.GetOutput())
    loc.BuildLocator()
    W = dsa.WrapDataObject(ug)
    loops = []
    for patch in S.patches:
        b = ExtractBlock(Input=S.r, Selectors=[f"/Root/boundary/{patch}"])
        b.UpdatePipeline(t)
        dp = sm.Fetch(b)
        app = vtkAppendFilter()
        it = dp.NewIterator()
        it.InitTraversal()
        while not it.IsDoneWithTraversal():
            app.AddInputData(it.GetCurrentDataObject())
            it.GoToNextItem()
        app.SetMergePoints(True)
        app.Update()
        pd = app.GetOutput()
        n = pd.GetNumberOfCells()
        if n == 0:
            continue
        pts = dsa.WrapDataObject(pd).Points
        zmid = float(np.median(pts[:, 2]))
        edge = []
        for i in range(n):
            ids = pd.GetCell(i).GetPointIds()
            low = [ids.GetId(j) for j in range(ids.GetNumberOfIds()) if pts[ids.GetId(j), 2] < zmid]
            edge.append(tuple(low[:2]) if len(low) >= 2 else None)
        # merge coincident low points (append filter merges exact duplicates only)
        key = {}
        for e in edge:
            if e:
                for pid in e:
                    k = (round(float(pts[pid, 0]), 9), round(float(pts[pid, 1]), 9))
                    key.setdefault(k, []).append(pid)
        canon = {}
        for ids in key.values():
            for pid in ids:
                canon[pid] = ids[0]
        p2c = {}
        for i, e in enumerate(edge):
            if e:
                for pid in e:
                    p2c.setdefault(canon[pid], []).append(i)
        order, seen = [], set()
        start = next(i for i, e in enumerate(edge) if e)
        cur, via = start, canon[edge[start][1]]
        while cur is not None and cur not in seen:
            seen.add(cur)
            order.append(cur)
            nxt = [c for c in p2c.get(via, []) if c != cur and c not in seen]
            if not nxt:
                break
            cur = nxt[0]
            a_, b_ = (canon[x] for x in edge[cur])
            via = b_ if a_ == via else a_
        order = np.array(order)
        fc = vtkCellCenters()
        fc.SetInputData(pd)
        fc.Update()
        fcent = dsa.WrapDataObject(fc.GetOutput()).Points[order]
        xy = fcent[:, :2]
        area = 0.5 * np.sum(xy[:, 0] * np.roll(xy[:, 1], -1) - np.roll(xy[:, 0], -1) * xy[:, 1])
        if area < 0:
            order, fcent, xy = order[::-1], fcent[::-1], xy[::-1]
        P = dsa.WrapDataObject(pd).CellData
        nb = np.array([loc.FindClosestPoint(fcent[i]) for i in range(len(order))])
        loops.append(dict(patch=patch, order=order, xy=xy, fcent=fcent, nb=nb, cpts=cpts,
                          face={k: np.asarray(P[k])[order] for k in P.keys()},
                          cell={k: np.asarray(W.CellData[k])[nb] for k in W.CellData.keys()
                                if k in ("U", "UMean", "nut")}))
    return loops


def surface_table(S, loops, mean=False):
    """Per-face table along each wall loop: s/c, x, y, Cp, Cf, y+, first-cell distance."""
    info = S.info
    U, nu = info["U"], info["nu"]
    q = 0.5 * U * U
    rows = []
    for L in loops:
        xy = L["xy"]
        n = len(xy)
        tng = np.roll(xy, -1, 0) - np.roll(xy, 1, 0)
        tng /= np.linalg.norm(tng, axis=1)[:, None]
        nrm = np.column_stack([-tng[:, 1], tng[:, 0]])
        dvec = L["cpts"][L["nb"], :2] - xy
        d = np.abs(np.sum(dvec * nrm, axis=1))
        seg = np.linalg.norm(np.diff(np.vstack([xy, xy[:1]]), axis=0), axis=1)
        s = np.concatenate([[0.0], np.cumsum(seg[:-1])])
        Uk, pk, tk = ("UMean", "pMean", "wallShearStressMean") if mean else ("U", "p", "wallShearStress")
        F, C = L["face"], L["cell"]
        if Uk not in C or pk not in F:
            continue
        Uw = F.get(Uk, np.zeros((n, 3)))
        Urel = C[Uk][:, :2] - Uw[:, :2]
        sign = np.sign(np.sum(Urel * tng, axis=1))
        if tk in F:
            tau = np.linalg.norm(F[tk], axis=1)
            src = tk
        else:
            nut_w = F.get("nut", np.zeros(n))
            tau = (nu + nut_w) * np.linalg.norm(Urel, axis=1) / np.maximum(d, 1e-12)
            src = "(nu + nut_wall) |U_cell - U_wall| / d"
        yplus = np.sqrt(tau) * d / nu
        Cp = (F[pk] - S.pinf) / q
        Cf = sign * tau / q
        for i in range(n):
            rows.append((L["patch"], s[i] / info["c_s"], xy[i, 0], xy[i, 1], Cp[i], Cf[i], yplus[i], d[i]))
    return rows, (src if loops else "")


def rotate_start(loops, info):
    """Section: start each loop at the A_outer corner so s/c = 0 there."""
    cn = corners(info)
    if not cn or info["kind"] != "section":
        return loops
    a = np.array(cn["A_outer"])
    for L in loops:
        k = int(np.argmin(np.linalg.norm(L["xy"] - a, axis=1)))
        for key in ("order", "xy", "fcent", "nb"):
            L[key] = np.roll(L[key], -k, axis=0)
        for grp in ("face", "cell"):
            L[grp] = {kk: np.roll(v, -k, axis=0) for kk, v in L[grp].items()}
    return loops


def sharp_corners(xy, n=4):
    """Indices of the n sharpest turns of a closed polyline (square corners)."""
    a = np.roll(xy, 1, 0) - xy
    b = np.roll(xy, -1, 0) - xy
    ang = np.degrees(np.arccos(np.clip(np.sum(a * b, 1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1)),
                                       -1, 1)))
    turn = 180 - ang
    idx = []
    for i in np.argsort(-turn):
        if all(min(abs(i - j), len(xy) - abs(i - j)) > 3 for j in idx):
            idx.append(int(i))
        if len(idx) == n:
            break
    return sorted(idx), turn


def plot_surface(rows, info, out_png, title, src, corner_s=None):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:  # noqa: BLE001
        print(f"  (no matplotlib in pvbatch: {e})")
        return
    patches = sorted(set(r[0] for r in rows))
    fig = plt.figure(figsize=(9.0, 8.0))
    gs = fig.add_gridspec(3, 4)
    axs = [fig.add_subplot(gs[i, :3]) for i in range(3)]
    axo = fig.add_subplot(gs[0, 3])
    for p in patches:
        R = np.array([r[1:] for r in rows if r[0] == p], float)
        lab = p if len(patches) > 1 else None
        axs[0].plot(R[:, 0], R[:, 3], lw=1.2, label=lab)
        axs[1].plot(R[:, 0], R[:, 4], lw=1.2)
        axs[2].semilogy(R[:, 0], np.maximum(R[:, 5], 1e-3), lw=1.2)
        axo.plot(R[:, 1] * 1e3, R[:, 2] * 1e3, lw=1.0)
        axo.plot(R[0, 1] * 1e3, R[0, 2] * 1e3, "ko", ms=4)
        k = max(1, len(R) // 12)
        axo.annotate("", xy=(R[k, 1] * 1e3, R[k, 2] * 1e3), xytext=(R[0, 1] * 1e3, R[0, 2] * 1e3),
                     arrowprops=dict(arrowstyle="->", color="k", lw=1))
    allR = np.array([r[1:] for r in rows], float)
    for ax, col in ((axs[0], 3), (axs[1], 4)):
        lo, hi = np.percentile(allR[:, col], [1.5, 98.5])
        pad = 0.15 * (hi - lo + 1e-9)
        if allR[:, col].min() < lo - pad or allR[:, col].max() > hi + pad:
            ax.set_ylim(lo - pad, hi + pad)
            ax.text(0.995, 0.03, "corner spikes clipped", transform=ax.transAxes, ha="right", fontsize=7, color="0.4")
    axs[0].invert_yaxis()
    axs[0].set_ylabel("Cp (axis inverted)")
    axs[1].set_ylabel("Cf (sign: near-wall flow\nalong +s is positive)")
    axs[1].axhline(0, color="k", lw=0.6)
    axs[2].set_ylabel("y+ of first cell")
    axs[2].axhline(1, color="0.5", ls=":", lw=1)
    axs[2].set_xlabel(f"wall distance s / c (c = {info['c_s'] * 1e3:.0f} mm), counter-clockwise")
    cs = dict(corner_s or [])
    s_end = max(r[1] for r in rows)
    named = all(k in cs for k in ("A outer", "B outer", "B inner", "A inner"))
    for ax in axs:
        ax.grid(alpha=0.3)
        if named:
            ax.axvspan(cs["B outer"], cs["B inner"], color="0.85", lw=0)
            ax.axvspan(cs["A inner"], s_end, color="0.85", lw=0)
        elif corner_s:
            for nm, sv in corner_s:
                ax.axvline(sv, color="0.6", lw=0.7, ls="--")
    if named:
        tr = axs[0].get_xaxis_transform()
        for x, txt in ((0.5 * cs["B outer"], "convex (outer) side"),
                       (0.5 * (cs["B inner"] + cs["A inner"]), "concave (inner) side"),
                       (cs["B outer"], "tip B"), (cs["A inner"], "tip A")):
            axs[0].text(x, 1.02, txt, transform=tr, fontsize=8, ha="center", va="bottom", color="0.25")
    if len(patches) > 1:
        axs[0].legend(fontsize=7)
    axo.set_aspect("equal")
    axo.set_title("s = 0 (dot), direction", fontsize=8)
    axo.tick_params(labelsize=6)
    axo.set_xlabel("x (mm)", fontsize=7)
    axo.set_ylabel("y (mm)", fontsize=7)
    fig.suptitle(title, fontsize=10)
    fig.text(0.01, 0.005, f"tau_w from {src}; y+ = sqrt(tau_w) d / nu, d = first-cell-centre wall distance",
             fontsize=7, color="0.3")
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    fig.savefig(out_png, dpi=150)
    plt.close(fig)
    quantise(out_png)
    print(f"  {Path(out_png).name}", flush=True)


# --------------------------------------------------------------------------- main
def header(info, S, t, what):
    P = info["P"]
    parts = [f"{info['name']}"]
    if t is not None and info.get("t_ref"):
        parts.append(f"t = {t:.6g} s = {t / info['t_ref']:.2f} {info['t_lab']}   ({what})")
    elif t is not None:
        parts.append(f"t = {t:.6g} s   ({what})")
    else:
        parts.append(what)
    meta = []
    if info["U"]:
        meta.append(f"U_inf = {info['U']:g} m/s")
    if info["kind"] == "section":
        meta.append(f"alpha = {info['alpha']:g} deg")
    else:
        if P.get("mode") == "rotating":
            meta.append(f"lambda = {P.get('lam', 0):g}, {P.get('rpm', 0):.0f} rpm")
        elif "thetaDeg" in P:
            meta.append(f"static, theta = {P['thetaDeg']:g} deg")
        meta.append(f"hypothesis {P.get('hypothesis', '?')}")
    if info["model"]:
        meta.append(info["model"])
    if info["level"]:
        meta.append(f"{info['level']} mesh")
    if meta:
        parts.append(", ".join(meta))
    return parts


def render_mesh(S, info, out, V):
    print("mesh images", flush=True)
    M = info["M"]
    ncell = M.get("n_cells", "?")
    h0 = (M.get("ring") or {}).get("first_cell_m") or M.get("h0_m")
    base = [f"{info['name']}: mesh", f"{ncell} cells" + (f", first cell h0 = {h0 * 1e6:.1f} um" if h0 else "")]
    S.clear()
    S.show(S.sl, "Surface With Edges", color=[1.0, 1.0, 1.0], line_width=1.0)
    S.reps[-1][1].EdgeColor = [0.1, 0.1, 0.25]
    for nm in ("domain", "near"):
        cx, cy, h = V[nm]
        S.camera(cx, cy, h)
        S.save(out / f"mesh_{nm}.png", base + [f"view height {2 * h * 1e3:.0f} mm"], colors=32)
    # corner close-ups
    mid = corner = None
    cn = corners(info)
    if cn:
        mid = 0.5 * (np.array(cn["A_outer"]) + np.array(cn["A_inner"]))
        corner = np.array(cn["A_outer"])
        lab = "blade tip A"
    elif S.loops:
        xy = S.loops[0]["xy"]
        idx, turn = sharp_corners(xy, 4)
        i0 = max(idx, key=lambda i: turn[i])                      # sharpest corner
        i1 = min((i for i in idx if i != i0), key=lambda i: np.linalg.norm(xy[i] - xy[i0]))   # its end-face partner
        mid, corner = 0.5 * (xy[i0] + xy[i1]), xy[i0]
        lab = f"sharpest corner of {S.loops[0]['patch']}"
    if mid is not None:
        for hh, tag, ctr, what in ((3e-3, "6mm", mid, "end face and both corners"),
                                   (4e-4, "0p8mm", corner, "outer corner"),
                                   (5e-5, "0p1mm", corner, "outer corner: the first wall cells")):
            S.camera(float(ctr[0]), float(ctr[1]), hh)
            S.save(out / f"mesh_cornerA_{tag}.png", base + [f"{lab}, {what}; view height {2 * hh * 1e3:.2g} mm"],
                   colors=32)
    if info["kind"] == "rotor" and M.get("r_ami_m"):
        r = M["r_ami_m"]
        if S.ami is not None:
            S.show(S.ami, "Surface", color=[0.85, 0.1, 0.1], line_width=3.0, bar=False)
        S.camera(0.0, r, 0.02)
        S.save(out / "mesh_ami.png", base + [f"sliding interface (AMI, red) at r = {r * 1e3:.0f} mm; view height 40 mm"],
               colors=32)


def render_fields_at(S, info, out, V, t, mean=False, suffix=""):
    what = "time-mean (fieldAverage)" if mean else "instantaneous"
    hdr = header(info, S, t, what)
    tag = "_mean" if mean else ""
    jobs = []
    A = set(S.arrays)
    um, cp = ("Umag_mean", "Cp_mean") if mean else ("Umag", "Cp")
    if ("UMean" if mean else "U") in A:
        jobs += [(f"velocity{tag}_near", um, "Umag", "near"), (f"velocity{tag}_wake", um, "Umag", "wake")]
    if not mean and "U" in A:
        jobs += [("vorticity_near", "vort", "vort", "near"), ("vorticity_wake", "vort", "vort", "wake")]
    if ("pMean" if mean else "p") in A:
        jobs += [(f"cp{tag}_near", cp, "Cp", "near")]
    if not mean and "nut" in A:
        jobs += [("nut_ratio_near", "nutr", "nutr", "near"), ("nut_ratio_wake", "nutr", "nutr", "wake")]
    if not mean and "gammaInt" in A and "LM" in (info["model"] or "") + info["name"]:
        jobs += [("gammaInt_near", "gammaInt", "gamma", "near")]
    if any(j[0] == "gammaInt_near" for j in jobs) and S.loops:
        xy = S.loops[0]["xy"]
        p = xy[len(xy) // 4]                 # a quarter of the way round: mid convex side for the section
        V["wall"] = (float(p[0]), float(p[1]), 0.0025)
        jobs.append(("gammaInt_wall", "gammaInt", "gamma", "wall"))
    for fname, arr, key, vw in jobs:
        S.clear()
        S.show(S.sl, "Surface", array=arr, key=key)
        cx, cy, h = V[vw]
        S.camera(cx, cy, h)
        extra = f"view height {2 * h * 1e3:.3g} mm"         # the length scale of the image
        if key == "Cp":
            extra += f"; p_inf = {S.pinf:.4g} m^2/s^2 (" + ("far-field value" if info["kind"] == "section"
                                                           else "inlet-patch mean") + ")"
        if key == "vort":
            extra += f"; L = {info['Lname']} = {info['L'] * 1e3:.1f} mm; red = counter-clockwise"
        S.save(out / f"{fname}{suffix}.png", hdr + [extra])
    # LIC and streamlines of the (mean) velocity
    vec = "UMean" if mean else "U"
    if vec in A:
        cx, cy, h = V["near"]
        S.clear()
        try:
            d = S.show(S.sl, "Surface LIC", array=um, key="Umag")
            d.SelectInputVectors = ["POINTS", vec]
            for prop, val in (("EnhanceContrast", "LIC only"), ("ColorMode", "Blend"), ("LICIntensity", 0.55),
                              ("NormalizeVectors", 1)):
                _try(d, prop, val)
            S.camera(cx, cy, h)
            S.save(out / f"lic{tag}_near{suffix}.png",
                   hdr + [f"line-integral convolution of {vec}; view height {2 * h * 1e3:.3g} mm"], colors=128)
        except Exception as e:  # noqa: BLE001
            print(f"  (no LIC: {e})")
        S.clear()
        S.show(S.sl, "Surface", array=um, key="Umag", opacity=0.55)
        a = math.radians(info["alpha"])
        ca, sa = math.cos(a), math.sin(a)
        L = info["L"] if info["kind"] == "section" else 0.5 * info["L"]
        z = 0.5 * info["dz"]

        def rot(x, y):
            return [x * ca - y * sa, x * sa + y * ca, z]
        seeds = [(rot(-1.2 * L, -1.1 * L), rot(-1.2 * L, 1.1 * L), 44),
                 (rot(0.7 * L, -0.8 * L), rot(0.7 * L, 0.8 * L), 16)]
        for p1, p2, nres in seeds:
            st = StreamTracer(Input=S.sl, SeedType="Line")
            st.Vectors = ["POINTS", vec]
            st.SurfaceStreamlines = 1
            st.IntegrationDirection = "BOTH"
            st.MaximumStreamlineLength = 40 * info["L"]
            st.SeedType.Point1 = p1
            st.SeedType.Point2 = p2
            st.SeedType.Resolution = nres
            st.UpdatePipeline(t)
            S.show(st, "Surface", color=[0.05, 0.05, 0.05], line_width=1.0, bar=False)
        S.camera(cx, cy, h)
        S.save(out / f"streamlines{tag}_near{suffix}.png",
               hdr + [f"streamlines of {vec} (seeded upstream and across the near wake); view height {2 * h * 1e3:.3g} mm"])


def animation(S, info, out, V, times, st_guess):
    """Vorticity at every saved time: GIF via ffmpeg, else a frame strip."""
    tmp = Path(tempfile.mkdtemp(prefix="anim_"))
    frames = []
    for i, t in enumerate(times):
        S.set_time(t)
        S.clear()
        S.show(S.sl, "Surface", array="vort", key="vort")
        cx, cy, h = V["wake"]
        S.camera(cx, cy, h)
        f = tmp / f"f{i:04d}.png"
        S.save(f, header(info, S, t, f"frame {i + 1}/{len(times)}"))
        frames.append(f)
    note = ""
    if len(times) > 1 and info.get("t_ref"):
        dtf = float(np.median(np.diff(times))) / info["t_ref"]
        note = f"frame spacing {dtf:.3g} {info['t_lab']}"
        if st_guess and info["kind"] == "section":
            Tshed = 1.0 / st_guess
            note += f"; shedding period 1/St = {Tshed:.3g} c/U"
            note += " (resolved)" if dtf < Tshed / 6 else " (NOT resolved: frames alias the shedding)"
    ff = None if os.environ.get("RENDER_NO_FFMPEG") else (
        shutil.which("ffmpeg") or ("/opt/homebrew/bin/ffmpeg" if Path("/opt/homebrew/bin/ffmpeg").exists() else None))
    made = None
    if ff and len(frames) >= 2:
        gif = out / "vorticity_anim.gif"
        fps = 4 if len(frames) < 12 else 12
        cmd = [ff, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(tmp / "f%04d.png"), "-vf",
               "scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=none",
               str(gif)]
        if subprocess.run(cmd).returncode == 0:
            made = gif
    if made is None and frames:
        from PIL import Image
        ims = [Image.open(f).convert("RGB") for f in frames[:6]]
        w, h = ims[0].size
        sc = 0.5
        strip = Image.new("RGB", (int(w * sc) * min(3, len(ims)), int(h * sc) * math.ceil(len(ims) / 3)), "white")
        for k, im in enumerate(ims):
            strip.paste(im.resize((int(w * sc), int(h * sc))), ((k % 3) * int(w * sc), (k // 3) * int(h * sc)))
        made = out / "vorticity_frames.png"
        strip.save(made)
        quantise(made, 256, S.lut_colours(128))
    shutil.rmtree(tmp, ignore_errors=True)
    if made:
        print(f"  {made.name}: {len(frames)} frames; {note}", flush=True)
    return made, note


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case")
    ap.add_argument("--out", required=True)
    ap.add_argument("--time", default="latest")
    ap.add_argument("--kind", choices=["section", "rotor"])
    ap.add_argument("--no-anim", action="store_true")
    ap.add_argument("--size", default="1200x800")
    ap.add_argument("--allow-running", action="store_true")
    ap.add_argument("--st", type=float, help="Strouhal number (for the animation note)")
    a = ap.parse_args(argv)
    case = Path(a.case).resolve()
    kind = a.kind or rl.kind_of(case)
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    running, why = rl.case_running(case)
    if running and not a.allow_running:
        print(f"render_fields: {case.name} looks RUNNING ({why}); not rendering. Use --allow-running to override.")
        return 2
    info = case_info(case, kind)
    size = tuple(int(x) for x in a.size.lower().split("x"))
    tmp = Path(tempfile.mkdtemp(prefix="render_"))
    manifest = dict(case=str(case), kind=kind, images=[], notes=[])
    try:
        sh = rl.make_shadow(case, tmp)
        manifest["read_as"] = sh["case_type"]
        S = Scene(info, sh, size)
        times = [t for t in S.times]
        field_times = [t for t in times if t > 0] if S.fields else []
        if a.time == "latest":
            t = field_times[-1] if field_times else (times[-1] if times else 0.0)
        else:
            t = min(times, key=lambda x: abs(x - float(a.time)))
        S.set_time(t)
        manifest["time"] = t
        manifest["times_available"] = times
        V = views(info, S)
        S.loops = []
        try:
            S.loops = rotate_start(wall_loops(S, t), info)
        except Exception as e:  # noqa: BLE001
            manifest["notes"].append(f"wall loop extraction failed: {e}")
        render_mesh(S, info, out, V)
        if S.fields and field_times:
            print(f"fields at t = {t:.6g} s", flush=True)
            render_fields_at(S, info, out, V, t)
            if S.has_mean:
                render_fields_at(S, info, out, V, t, mean=True)
            # surface distributions
            corner_s = None
            cn = corners(info)
            if cn and S.loops:
                xy = S.loops[0]["xy"]
                seg = np.linalg.norm(np.diff(np.vstack([xy, xy[:1]]), axis=0), axis=1)
                s = np.concatenate([[0.0], np.cumsum(seg[:-1])]) / info["c_s"]
                corner_s = [(k.replace("_", " "), float(s[int(np.argmin(np.linalg.norm(xy - np.array(v), axis=1)))]))
                            for k, v in cn.items()]
            for mean in ((False, True) if S.has_mean else (False,)):
                rows, src = surface_table(S, S.loops, mean)
                if not rows:
                    continue
                tag = "mean" if mean else "inst"
                csvp = out / f"surface_{tag}.csv"
                with open(csvp, "w") as fh:
                    fh.write(f"# {info['name']} t={t:.8g} s ({tag}); s/c with c={info['c_s']} m; Cp=(p-p_inf)/(0.5U^2), "
                             f"p_inf={S.pinf:.6g}; Cf signed by near-wall flow direction; tau_w from {src}\n")
                    fh.write("patch,s_over_c,x_m,y_m,Cp,Cf,yplus,d_first_m\n")
                    for r in rows:
                        fh.write(f"{r[0]},{r[1]:.6f},{r[2]:.7g},{r[3]:.7g},{r[4]:.6g},{r[5]:.6g},{r[6]:.5g},{r[7]:.5g}\n")
                print(f"  {csvp.name}", flush=True)
                plot_surface(rows, info, out / f"surface_{tag}.png",
                             f"{info['name']}: wall distributions, {'time-mean' if mean else 'instantaneous'}, "
                             f"t = {t:.5g} s", src, corner_s)
                yp = np.array([r[6] for r in rows])
                manifest[f"yplus_{tag}"] = dict(min=float(yp.min()), mean=float(yp.mean()), max=float(yp.max()),
                                                p95=float(np.percentile(yp, 95)))
            if not a.no_anim and len(field_times) >= 2:
                st = a.st
                if st is None:
                    R = rl.load_json(case / "results.json", {}) or {}
                    st = R.get("St")
                made, note = animation(S, info, out, V, field_times, st)
                if made:
                    manifest["notes"].append(f"{made.name}: {note}")
            elif len(field_times) < 2:
                manifest["notes"].append(f"no animation: {len(field_times)} saved field time(s) "
                                         "(purgeWrite keeps the last 3; finished cases keep only the last)")
        else:
            manifest["notes"].append("no field data: mesh images only")
        manifest["images"] = sorted(p.name for p in out.glob("*.png")) + sorted(p.name for p in out.glob("*.gif"))
        (out / "render_manifest.json").write_text(json.dumps(manifest, indent=1))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"render_fields: {len(manifest['images'])} images in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
