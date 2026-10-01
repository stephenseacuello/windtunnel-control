import numpy as np, pandas as pd
from scipy import stats
T='/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/build/tables/'
H={b:pd.read_csv(T+f'thevenin_v1_{b}.csv') for b in ('Ra20','Ra40','Ra80')}
P={b:pd.read_csv(T+f'pmax_v1_{b}.csv') for b in ('Ra20','Ra40','Ra80')}
v=H['Ra20'].wind_mps_nominal.values; lv=np.log(v)
for c,b in (('Ra40','Ra20'),('Ra80','Ra20'),('Ra80','Ra40')):
    dv=np.log(H[c].v_oc/H[b].v_oc).values
    r=stats.linregress(lv,dv); t=stats.t.ppf(.975,12)
    print(c,b,'Voc log-ratio slope %.3f +- %.3f (p=%.3f)'%(r.slope,t*r.stderr,r.pvalue))
    # rank corr
    print('   spearman vs v: %.2f p=%.3f'%stats.spearmanr(v,dv))
    dvl=np.log(P[c].v_light/P[b].v_light).values
    r2=stats.linregress(lv,dvl); print('   Vlight slope %.3f +- %.3f p=%.3f'%(r2.slope,t*r2.stderr,r2.pvalue))
    dp=np.log(P[c].p_raw/P[b].p_raw).values
    print('   power spearman %.2f p=%.3f'%stats.spearmanr(v,dp))
# friction model: what V_oc ratio pattern would a Coulomb friction reduction give? relative ~ v^-2 approx
# AR(1)-adjusted CI for Ra80 vs Ra20
for c in ('Ra40','Ra80'):
    d=np.log(P[c].p_raw/P['Ra20'].p_raw).values
    rho=np.corrcoef(d[:-1],d[1:])[0,1]; n=14
    neff=n*(1-rho)/(1+rho)
    se=d.std(ddof=1)/np.sqrt(neff); t=stats.t.ppf(.975,max(neff-1,1))
    print(c,'rho %.2f neff %.1f  AR1-adjusted CI [%.1f, %.1f]'%(rho,neff,100*np.expm1(d.mean()-t*se),100*np.expm1(d.mean()+t*se)))
# beta trend: rotor-level view; 3 rotor means
f={'Ra20':0.050,'Ra40':0.101,'Ra80':0.202}
m={b:np.mean(np.log(P[b].p_raw.values)) for b in P}
x=np.log([f[b] for b in P]); y=np.array([m[b] for b in P])
r=stats.linregress(x,y); print('rotor-level beta %.3f se %.3f (1 dof) 95%% half %.3f'%(r.slope,r.stderr,stats.t.ppf(.975,1)*r.stderr))
# sensitivity: if Ra20 mounting offset of +-3%, +-5%
for off in (-0.05,-0.03,0.03,0.05):
    y2=y.copy(); y2[0]+=np.log1p(off); print(' Ra20 offset %+.0f%% -> beta %.3f'%(100*off,stats.linregress(x,y2).slope))
