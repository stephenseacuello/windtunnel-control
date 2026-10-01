import numpy as np, pandas as pd
from scipy import stats, optimize
T='/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/build/tables/'
P=pd.read_csv(T+'pmax_v1_Ra20.csv'); v=P.wind_mps_nominal.values; p=P.p_raw.values
f=lambda v,a,v0,m: a*np.clip(v-v0,1e-6,None)**m
for v0g in (0,3,5):
    try:
        pr,_=optimize.curve_fit(lambda v,la,v0,m: la+m*np.log(np.clip(v-v0,1e-6,None)),v,np.log(p),p0=(np.log(1e-5),v0g,3.5),maxfev=20000)
        la,v0,m=pr; print('fit ln a=%.2f v0=%.2f m=%.2f'%(la,v0,m))
    except Exception as e: print(e)
for v0,m in ((0,3.763),(v0,m)):
    for sh in (-0.25,-0.5):
        d=m*np.log((v-v0-sh)/(v-v0))
        r=stats.linregress(np.log(v),d)
        print(' v0=%.2f m=%.2f shift %.2f: level %+.1f%%, dn %+.3f; ratio at 10.2 %+.1f%%, at 38 %+.1f%%'%(v0,m,sh,100*np.expm1(d.mean()),r.slope,100*np.expm1(d[0]),100*np.expm1(d[-1])))
