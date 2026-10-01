"""Independent check of the specimen numbers quoted in blades/v1.json and docs/09_results.md.
Reads blades/v1.stl (binary STL, metres). Read-only."""
import numpy as np, struct
REPO = '/Users/stepheneacuello/Projects/windtunnel-control'
b = open(f'{REPO}/blades/v1.stl', 'rb').read()
n = struct.unpack('<I', b[80:84])[0]
t = np.frombuffer(b, dtype=np.dtype([('n', '<3f4'), ('v', '<9f4'), ('a', '<u2')]), count=n, offset=84)
v = t['v'].reshape(-1, 3, 3).astype(float) * 1000.0        # mm
ext = np.sort(v.reshape(-1, 3).max(0) - v.reshape(-1, 3).min(0))
A = 0.5 * np.linalg.norm(np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), axis=1).sum()
V = abs(np.einsum('ij,ij->i', v[:, 0], np.cross(v[:, 1], v[:, 2])).sum() / 6)
print(f'triangles {n}; bbox sorted mm {np.round(ext, 2)} (camber depth, chord, span)')
print(f'area {A:.0f} mm2, volume {V:.0f} mm3, wall 2V/A = {2*V/A:.3f} mm, t/c = {2*V/A/ext[1]:.3f}')
R, H, c = 0.1016, 0.2451, 0.048
print(f'swept area 2RH = {2*R*H:.5f} m2 (pi R^2 = {np.pi*R*R:.5f}; ratio {2*R*H/(np.pi*R*R):.3f})')
nu = c * 10.14 / 32376
print(f'docs Re range 32,376-119,735 implies nu = {nu:.4e} m2/s over v = 10.14-37.50 m/s '
      f'-> {c*10.14/nu:.0f} .. {c*37.50/nu:.0f}')
for T in (20.0, 24.63):   # 24.63 C = node reading at Ra40 run start (uncalibrated, reads high)
    mu = 1.716e-5 * ((T + 273.15) / 273.15) ** 1.5 * (273.15 + 110.4) / (T + 273.15 + 110.4)
    rho = 101325 / (287.05 * (T + 273.15))
    print(f'  at {T} C, 101325 Pa (Sutherland): nu = {mu/rho:.4e}, Re = {c*10.14*rho/mu:.0f} .. {c*37.50*rho/mu:.0f}')
