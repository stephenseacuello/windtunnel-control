#!/usr/bin/env python3
"""Build every mesh variant through run_case.ensure_mesh (the queue's cache) and
collect the checkMesh verdicts into mesh/logs/variants_summary.json.

    python3 cfd/rotor2d/mesh/check_variants.py            # all variants below
    python3 cfd/rotor2d/mesh/check_variants.py --only A_fine

A variant that fails checkMesh is reported, not fatal.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import run_case  # noqa: E402

VARIANTS = []
for h in ("A", "B"):
    VARIANTS += [
        dict(tag=f"{h}_coarse", hyp=h, U=23.0, theta=0.0, level="coarse"),
        dict(tag=f"{h}_medium", hyp=h, U=23.0, theta=0.0, level="medium"),
        dict(tag=f"{h}_fine", hyp=h, U=23.0, theta=0.0, level="fine"),
        dict(tag=f"{h}_medium_lowRe", hyp=h, U=23.0, theta=0.0, level="medium", wall="lowRe"),
        dict(tag=f"{h}_medium_U10.2", hyp=h, U=10.2, theta=0.0, level="medium"),
        dict(tag=f"{h}_medium_U38", hyp=h, U=38.0, theta=0.0, level="medium"),
        dict(tag=f"{h}_medium_th60", hyp=h, U=23.0, theta=60.0, level="medium"),
        dict(tag=f"{h}_medium_walls", hyp=h, U=23.0, theta=0.0, level="medium", walls="-0.6,0.6"),
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    out_path = HERE / "logs" / "variants_summary.json"
    summ = json.loads(out_path.read_text()) if out_path.exists() else {}
    for v in VARIANTS:
        if a.only and v["tag"] not in a.only:
            continue
        c = run_case.normalise({k: x for k, x in v.items() if k != "tag"})
        t0 = time.time()
        try:
            d = run_case.ensure_mesh(c)
            ok = True
        except Exception as e:  # noqa: BLE001
            d, ok = run_case.MESHES / run_case.mesh_key(c), False
            print(f"[fail] {v['tag']}: {e}", flush=True)
        log = (d / "log.checkMesh").read_text() if (d / "log.checkMesh").exists() else ""
        info = json.loads((d / "mesh_info.json").read_text()) if (d / "mesh_info.json").exists() else {}
        g = lambda pat: (re.search(pat, log).group(1) if re.search(pat, log) else None)  # noqa: E731
        summ[v["tag"]] = dict(
            mesh_key=d.name, mesh_ok=ok and "Mesh OK." in log, n_cells=info.get("n_cells"),
            n_cells_rotor=info.get("n_cells_rotor"), h0_m=info.get("h0_m"),
            yplus_flat_plate=info.get("yplus_flat_plate_estimate"), ring_layers=info.get("ring", {}).get("n_layers"),
            ring_thickness_m=info.get("ring", {}).get("thickness_m"), n_ami_faces=info.get("n_ami_faces"),
            r_ami_m=info.get("r_ami_m"), max_non_orth=g(r"non-orthogonality Max: (\S+)"),
            max_aspect=g(r"Max aspect ratio = (\S+)"), max_skew=g(r"Max skewness = (\S+)"),
            regions=g(r"Number of regions: (\d+)"), seconds=round(time.time() - t0, 1))
        print(v["tag"], json.dumps(summ[v["tag"]]), flush=True)
        out_path.write_text(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
