import numpy as np, pandas as pd
from scipy import stats, optimize
T='/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/build/tables/'
H={b:pd.read_csv(T+f'thevenin_v1_{b}.csv') for b in ('Ra20','Ra40','Ra80')}
v=H['Ra20'].wind_mps_nominal.values; lv=np.log(v)
for base in ('Ra20','pooled'):
    if base=='Ra20':
        R=H['Ra20'].r_int.values; vv=v
    else:
        R=np.concatenate([H[b].r_int.values for b in H]); vv=np.tile(v,3)
    f=lambda x,R0,c,m: R0+c*x**(-m)
    p,_=optimize.curve_fit(f,vv,R,p0=(30,500,1.5),maxfev=20000)
    print(base,'floor model R0=%.1f c=%.1f m=%.2f'%tuple(p))
    Rm=f(v,*p); loc=-p[1]*p[2]*v**(-p[2])/Rm   # dlnR/dlnv
    print('  local dlnR/dlnv',np.round(loc,2))
    for c in ('Ra40','Ra80'):
        dv=np.log(H[c].v_oc/H['Ra20'].v_oc).values; dr=np.log(H[c].r_int/H['Ra20'].r_int).values
        delta=dv/1.497
        pred=loc*delta
        res=dr-pred; t=stats.t.ppf(.975,13); se=res.std(ddof=1)/np.sqrt(14)
        print('  %s pred mean dR %.1f%%, obs %.1f%%, obs-pred %.2f%% CI[%.2f,%.2f]'%(c,100*pred.mean(),100*dr.mean(),100*res.mean(),100*(res.mean()-t*se),100*(res.mean()+t*se)))
# raw per set point R of Ra20 local slopes (finite difference)
R=H['Ra20'].r_int.values
print('finite-diff dlnR/dlnv Ra20',np.round(np.diff(np.log(R))/np.diff(lv),2))
Rp=np.mean([np.log(H[b].r_int.values) for b in H],axis=0)
print('finite-diff dlnR/dlnv pooled',np.round(np.diff(Rp)/np.diff(lv),2))
