import numpy as np, pandas as pd
B='/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/inputs/jeong_lab/2026-07-27_no_texture_baseline/'
raw=pd.read_csv(B+'0727windturbine.csv'); raw.columns=['t','d','ts','c1','c2','c3','c4','c5','ev']
t=raw.t.values; V=4*raw.c1.values; c3=raw.c3.values
# 1-s means of V and pulse rate from 0 to 70 s
edges=np.where(np.diff(c3)>0.1)[0]   # crude rising-edge
for s in range(0,72,2):
    m=(t>=s)&(t<s+2)
    ne=((edges>=np.searchsorted(t,s))&(edges<np.searchsorted(t,s+2))).sum()
    print(f'{s:3d}-{s+2:3d}s  V={V[m].mean():6.3f}  pulses/2s={ne:3d} rpm~{30*ne:5.0f}')
