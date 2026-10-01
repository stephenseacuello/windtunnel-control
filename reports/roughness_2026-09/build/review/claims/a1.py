import numpy as np, pandas as pd
from scipy import stats
T='/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/build/tables/'
P={b:pd.read_csv(T+f'pmax_v1_{b}.csv') for b in ('Ra20','Ra40','Ra80')}
H={b:pd.read_csv(T+f'thevenin_v1_{b}.csv') for b in ('Ra20','Ra40','Ra80')}
v=P['Ra20'].wind_mps_nominal.values; rpm=P['Ra20'].fan_rpm_cmd.values
def lr(a,b,col='p_raw'): return np.log(P[a][col].values/P[b][col].values)
for a,b in (('Ra40','Ra20'),('Ra80','Ra20'),('Ra80','Ra40')):
    d=lr(a,b)
    print(a,b,'ratios%',np.round(100*np.expm1(d),1))
    r1=np.corrcoef(d[:-1],d[1:])[0,1]
    # detrended lag1
    res=d-np.polyval(np.polyfit(np.log(v),d,1),np.log(v))
    print('  lag1 autocorr raw %.2f detrended %.2f'%(r1,np.corrcoef(res[:-1],res[1:])[0,1]))
    # top 3 vs rest
    print('  mean top3 (1600-1800) %.1f%%, 500-900 %.1f%%, 1200-1500 %.1f%%'%(100*np.expm1(d[-3:].mean()),100*np.expm1(d[:5].mean()),100*np.expm1(d[7:11].mean())))
    # delta n CI implication
    reg=stats.linregress(np.log(v),d); t2=stats.t.ppf(.975,12)
    hi=reg.slope+t2*reg.stderr; lo=reg.slope-t2*reg.stderr
    span=np.log(v[-1]/v[0])
    print('  dn %.3f [%.3f,%.3f]; ratio change across range at CI ends: %.1f%% / %.1f%%'%(reg.slope,lo,hi,100*np.expm1(lo*span),100*np.expm1(hi*span)))
    # Wilcoxon & sign
    print('  sign p',stats.binomtest(int((d>0).sum()),14).pvalue)
# thevenin: p_match vs pmax
for b in P:
    m=P[b].merge(H[b],on='fan_rpm_cmd')
    print(b,'p_match/p_raw',np.round(m.p_match/m.p_raw,3))
    print(b,'r2',np.round(m.r2,3).tolist())
    print(b,'i_light',m.i_light.tolist()[:3],'v_light/voc',np.round(m.v_light/m.v_oc,3).tolist())
