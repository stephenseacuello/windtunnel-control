import numpy as np, pandas as pd
from scipy import stats
T='/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/build/tables/'
P={b:pd.read_csv(T+f'pmax_v1_{b}.csv') for b in ('Ra20','Ra40','Ra80')}
H={b:pd.read_csv(T+f'thevenin_v1_{b}.csv') for b in ('Ra20','Ra40','Ra80')}
v=H['Ra20'].wind_mps_nominal.values; lv=np.log(v)
# share decomposition and uncertainty
for c in ('Ra40','Ra80'):
    dv=np.log(H[c].v_oc/H['Ra20'].v_oc).values; dr=np.log(H[c].r_int/H['Ra20'].r_int).values
    dp=np.log(P[c].p_raw/P['Ra20'].p_raw).values
    t=stats.t.ppf(.975,13)
    print(c,'mean dlnP %.4f  2dv %.4f  -dr %.4f  2dv-dr %.4f share(model) %.2f  2dv/dlnP %.2f'%(dp.mean(),2*dv.mean(),-dr.mean(),2*dv.mean()-dr.mean(),2*dv.mean()/(2*dv.mean()-dr.mean()),2*dv.mean()/dp.mean()))
    # per-set-point share distribution / bootstrap
    rng=np.random.default_rng(0); sh=[]
    for _ in range(20000):
        i=rng.integers(0,14,14); sh.append(2*dv[i].mean()/(2*dv[i].mean()-dr[i].mean()))
    print('   bootstrap share 95%%: %.2f-%.2f'%tuple(np.percentile(sh,[2.5,97.5])))
    rlo=dr.mean()-t*dr.std(ddof=1)/np.sqrt(14); rhi=dr.mean()+t*dr.std(ddof=1)/np.sqrt(14)
    print('   share at R CI ends: %.2f  %.2f'%(2*dv.mean()/(2*dv.mean()-rlo),2*dv.mean()/(2*dv.mean()-rhi)))
    print('   per-sp Voc ratio %',np.round(100*np.expm1(dv),1))
    print('   per-sp R ratio %',np.round(100*np.expm1(dr),1))
    print('   corr(dv,dr) %.2f'%np.corrcoef(dv,dr)[0,1])
# wind-offset test with LOCAL slopes of Ra20 curves
a=H['Ra20']
lvoc=np.log(a.v_oc.values); lr=np.log(a.r_int.values)
# global fits
print('global Voc exp %.3f  R exp %.3f'%(np.polyfit(lv,lvoc,1)[0],np.polyfit(lv,lr,1)[0]))
# local slopes via central differences on a smoothed quadratic fit in log-log
cv=np.polyfit(lv,lvoc,2); cr=np.polyfit(lv,lr,2)
sv=np.polyval(np.polyder(cv),lv); sr=np.polyval(np.polyder(cr),lv)
print('local Voc slope',np.round(sv,2)); print('local R slope',np.round(sr,2))
# also R exponent over top half vs bottom half
print('R exp 500-1100 %.2f ; 1200-1800 %.2f'%(np.polyfit(lv[:7],lr[:7],1)[0],np.polyfit(lv[7:],lr[7:],1)[0]))
print('Voc exp 500-1100 %.2f ; 1200-1800 %.2f'%(np.polyfit(lv[:7],lvoc[:7],1)[0],np.polyfit(lv[7:],lvoc[7:],1)[0]))
for c in ('Ra40','Ra80'):
    dv=np.log(H[c].v_oc/a.v_oc).values; dr=np.log(H[c].r_int/a.r_int).values
    delta=dv/sv   # implied per-sp wind offset (log)
    pred=sr*delta
    print(c,'predicted mean dR (local) %.1f%%  vs global %.1f%%; observed %.1f%%'%(100*np.expm1(pred.mean()),100*np.expm1(-0.791/1.497*dv.mean()),100*np.expm1(dr.mean())))
    # test: residual dr - pred
    res=dr-pred; t=stats.t.ppf(.975,13)
    print('   dr - pred mean %.2f%% CI [%.2f, %.2f]'%(100*res.mean(),100*(res.mean()-t*res.std(ddof=1)/np.sqrt(14)),100*(res.mean()+t*res.std(ddof=1)/np.sqrt(14))))
    # use high-wind half only
    print('   high-wind (1200-1800) pred %.1f%% obs %.1f%%'%(100*pred[7:].mean(),100*dr[7:].mean()))
