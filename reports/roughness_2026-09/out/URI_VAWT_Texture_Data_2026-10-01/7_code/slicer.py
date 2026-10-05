"""Summarise a Bambu Studio project (.3mf) into a small JSON the report can cite.

    python3 src/slicer.py inputs/slicer/turbine_default.3mf

Writes inputs/slicer/<stem>_summary.json next to the project. The .3mf itself
(60 MB) stays out of the data package; the summary ships in 5_reference/.

What it records, per plate: plate name, the object on it, that object's
fuzzy-skin thickness, its bounding box (to tell a blade from a rotor), its
triangle count, and the share of triangles and of surface area painted with
fuzzy skin (unpainted area split into end caps and the rest). Globally:
printer profile, nozzle, layer height, material, fuzzy-skin point distance.
Plates whose thickness is not a reported specimen are listed only as a count.
"""
import json
import re
import sys
import zipfile
from pathlib import Path

import numpy as np

REPORTED_MM = {0.050, 0.101, 0.202}


def summarise(path):
    path = Path(path)
    z = zipfile.ZipFile(path)
    ps = json.loads(z.read("Metadata/project_settings.config"))
    ms = z.read("Metadata/model_settings.config").decode()
    # object id -> fuzzy thickness; part id -> object id; plate name -> object id
    objs = {}
    for m in re.finditer(r'<object id="(\d+)">(.*?)</object>', ms, re.S):
        th = re.search(r'key="fuzzy_skin_thickness" value="([0-9.]+)"', m.group(2))
        part = re.search(r'<part id="(\d+)"', m.group(2))
        objs[m.group(1)] = dict(fuzz_mm=float(th.group(1)) if th else None,
                                mesh=part.group(1) if part else None)
    plates = []
    for m in re.finditer(r"<plate>(.*?)</plate>", ms, re.S):
        name = re.search(r'key="plater_name" value="([^"]*)"', m.group(1)).group(1)
        oid = re.search(r'key="object_id" value="(\d+)"', m.group(1)).group(1)
        plates.append(dict(plate=name, object=oid, **objs[oid]))
    # stream the mesh once: per mesh object, vertices and triangles (with paint flag)
    verts, tris, cur = {}, {}, None
    with z.open("3D/3dmodel.model") as f:
        for raw in f:
            line = raw.decode("utf-8", "replace")
            m = re.search(r'<object id="(\d+)"', line)
            if m:
                cur = m.group(1)
                verts.setdefault(cur, []); tris.setdefault(cur, [])
            if cur is None:
                continue
            if "<vertex " in line:
                verts[cur].append([float(x) for x in re.findall(r'[xyz]="([-0-9.e]+)"', line)])
            elif "<triangle " in line:
                v = [int(x) for x in re.findall(r'v[123]="(\d+)"', line)]
                tris[cur].append(v + [1 if 'paint_fuzzy_skin="' in line else 0])
    for p in plates:
        V = np.array(verts[p["mesh"]]); T = np.array(tris[p["mesh"]])
        a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
        cr = np.cross(b - a, c - a)
        area = 0.5 * np.linalg.norm(cr, axis=1)
        painted = T[:, 3] == 1
        cap = np.abs(cr[:, 2]) / np.maximum(2 * area, 1e-12) > 0.9      # faces normal to the span
        p["size_mm"] = [round(float(x), 2) for x in V.max(axis=0) - V.min(axis=0)]
        p["triangles"] = int(len(T))
        p["painted_triangle_fraction"] = round(float(painted.mean()), 4)
        p["painted_area_fraction"] = round(float(area[painted].sum() / area.sum()), 4)
        p["unpainted_area_mm2"] = dict(end_caps=round(float(area[~painted & cap].sum()), 1),
                                       other=round(float(area[~painted & ~cap].sum()), 1))
    reported = [p for p in plates if p["fuzz_mm"] in REPORTED_MM]
    first = lambda k: ps[k][0] if isinstance(ps[k], list) else ps[k]
    return dict(
        file=path.name,
        saved="%04d-%02d-%02d" % z.getinfo("Metadata/project_settings.config").date_time[:3],
        application=re.search(r'X-BBL-Client-Version" value="([^"]+)"',
                              z.read("Metadata/slice_info.config").decode()).group(1),
        printer_profile=first("printer_settings_id"), print_profile=first("print_settings_id"),
        nozzle_mm=float(first("nozzle_diameter")), layer_height_mm=float(first("layer_height")),
        material=first("filament_type"), filament_profile=first("filament_settings_id"),
        fuzzy_skin_global=first("fuzzy_skin"), fuzzy_skin_mode=first("fuzzy_skin_mode"),
        fuzzy_point_distance_mm=float(first("fuzzy_skin_point_distance")),
        wall_loops=int(first("wall_loops")),
        plates_total=len(plates), plates_not_reported=len(plates) - len(reported),
        plates=[{k: p[k] for k in ("plate", "fuzz_mm", "size_mm", "triangles", "painted_triangle_fraction",
                                   "painted_area_fraction", "unpainted_area_mm2")}
                for p in reported],
    )


if __name__ == "__main__":
    src = Path(sys.argv[1] if len(sys.argv) > 1 else
               Path(__file__).resolve().parent.parent / "inputs/slicer/turbine_default.3mf")
    out = src.with_name(src.stem + "_summary.json")
    out.write_text(json.dumps(summarise(src), indent=2) + "\n")
    print(out.read_text())
