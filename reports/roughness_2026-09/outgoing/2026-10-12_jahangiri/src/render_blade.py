"""Shaded render of one blade (blades/v1.stl) for the 12 Oct 2026 reply to Prof. Jahangiri."""
from pathlib import Path
import numpy as np
import trimesh
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

REPO = Path(__file__).resolve().parents[5]
m = trimesh.load(REPO / "blades" / "v1.stl")
m.apply_scale(1000.0)                                   # m -> mm
m.apply_translation(-m.bounds.mean(axis=0))
ext = m.extents                                         # x, y (section), z (span)
tri = m.vertices[m.faces]
light = np.array([0.4, -0.6, 0.7]); light /= np.linalg.norm(light)
shade = 0.35 + 0.65 * np.clip(np.abs(m.face_normals @ light), 0, 1)
cols = np.c_[np.repeat(shade[:, None], 3, axis=1) * np.array([0.80, 0.82, 0.86]), np.ones(len(shade))]

fig = plt.figure(figsize=(7.2, 4.6), dpi=300)
ax = fig.add_subplot(1, 2, 1, projection="3d")
ax.add_collection3d(Poly3DCollection(tri, facecolors=cols, edgecolor="none"))
r = ext.max() / 2
ax.set_xlim(-r / 4, r / 4); ax.set_ylim(-r / 4, r / 4); ax.set_zlim(-r, r)
ax.set_box_aspect((1, 1, 4))
ax.view_init(elev=22, azim=-58)
ax.set_axis_off()
ax.set_title(f"Blade, span {ext[2]:.0f} mm", fontsize=9)

ax2 = fig.add_subplot(1, 2, 2)
sec = m.section(plane_origin=[0, 0, 0], plane_normal=[0, 0, 1])
pts = sec.discrete
for p in pts:
    ax2.fill(p[:, 0], p[:, 1], color="0.55", lw=0.6, ec="0.2")
ax2.set_aspect("equal")
ax2.set_xlabel("mm", fontsize=8); ax2.set_ylabel("mm", fontsize=8)
ax2.tick_params(labelsize=7)
ax2.grid(alpha=0.3, lw=0.4)
ax2.set_title(f"Cross-section at mid-span\nbounding box {ext[0]:.1f} x {ext[1]:.1f} mm", fontsize=9)
fig.tight_layout()
out = Path(__file__).resolve().parents[1] / "fig_blade_render.png"
fig.savefig(out, facecolor="white")
print(out, ext)
