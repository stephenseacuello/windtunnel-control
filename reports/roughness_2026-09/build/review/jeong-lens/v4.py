import numpy as np, pandas as pd
raw = pd.read_csv('../../../inputs/jeong_lab/2026-07-27_no_texture_baseline/0727windturbine.csv')
t = raw.iloc[:,0].values; ch = raw.iloc[:,3:8].values
N=len(raw); L=N//17
c3=ch[:,2]
for k in (4,8,15):
    a=k*L+1870;b=k*L+5611
    seg=c3[a:b+1]; d=np.diff(seg); e=np.where(d>0.1)[0]
    per=np.diff(e)
    idx=np.where(per<5)[0]
    for j in idx:
        i0=a+e[j]
        print(k, 'at t', round(t[i0],3), 'samples', e[j], e[j+1], 'vals', np.round(c3[i0-1:i0+4],3), 'diffs', np.round(d[e[j]-1:e[j]+3],3))
