import numpy as np, pandas as pd
raw = pd.read_csv('../../../inputs/jeong_lab/2026-07-27_no_texture_baseline/0727windturbine.csv')
t = raw.iloc[:,0].values; ch = raw.iloc[:,3:8].values
V=4*ch[:,0]; z=2.496337891; I=2*(ch[:,1]-z)
d=np.diff(ch[:,2]); e=np.where(d>0.1)[0]; te=t[e+1]
def rpm(a,b):
    m=(te>=a)&(te<b); x=te[m]
    return 60*(len(x)-1)/(x[-1]-x[0]) if len(x)>2 else np.nan
for a in np.arange(82,170,1.0):
    m=(t>=a)&(t<a+1)
    print(f"{a:5.0f} V={V[m].mean():5.2f} I={I[m].mean()*1000:6.1f} P={np.mean(V[m]*I[m]):.3f} rpm={rpm(a-1,a+2):5.0f}")
