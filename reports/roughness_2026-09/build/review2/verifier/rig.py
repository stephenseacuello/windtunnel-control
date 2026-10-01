import numpy as np, pandas as pd, io
from scipy import stats
L = '/Users/stepheneacuello/Projects/windtunnel-control/logs/'
def load(r):
    txt = [l for l in open(L+f'sweep_v1_{r}_points.csv') if not l.startswith('#')]
    return pd.read_csv(io.StringIO(''.join(txt)))
D = {r: load(r) for r in ['Ra20','Ra40','Ra80']}
fans = np.arange(500,1900,100)
v = 0.02132*fans - 0.424
def ladder(df, f):
    d = df[(df.fan_rpm==f)&(df.tracking==1)&(df.amps>0)]
    return d
P = {}; VOC = {}; RINT = {}; R2 = {}; V1 = {}; MA={}
for r, df in D.items():
    P[r] = np.array([ladder(df,f).watts.max() for f in fans])
    voc=[]; rint=[]; r2=[]; v1=[]; ma=[]
    for f in fans:
        d = ladder(df,f); d = d[(d.volts>0)]
        s = stats.linregress(d.amps, d.volts)
        voc.append(s.intercept); rint.append(-s.slope); r2.append(s.rvalue**2)
        v1.append(d.volts.iloc[0]); ma.append(d.motor_amps.mean())
    VOC[r]=np.array(voc); RINT[r]=np.array(rint); R2[r]=np.array(r2); V1[r]=np.array(v1); MA[r]=np.array(ma)
print('Pmax', {r: np.round(P[r],4) for r in P})
print('min r2', {r: R2[r].min().round(4) for r in R2})
print('Voc', {r: np.round(VOC[r],2) for r in VOC}); print('Rint', {r: np.round(RINT[r],1) for r in RINT})
print('first-step V Ra20 500-700', V1['Ra20'][:3])
print('motor amps diff max', max(np.abs(MA['Ra20']-MA['Ra40']).max(), np.abs(MA['Ra20']-MA['Ra80']).max(), np.abs(MA['Ra40']-MA['Ra80']).max()))
def paired(b,c,x=None):
    d = np.log(x[c]/x[b]); n=len(d); m=d.mean(); sd=d.std(ddof=1)
    t=stats.t.ppf(.975,n-1)
    ci=np.exp([m-t*sd/np.sqrt(n), m+t*sd/np.sqrt(n)])-1
    r1 = np.corrcoef(d[:-1],d[1:])[0,1]
    dd=d-m; r1b = (dd[:-1]*dd[1:]).sum()/(dd*dd).sum()
    out = dict(chg=100*(np.exp(m)-1), ci=100*ci, r1=r1, r1b=r1b, hi=(d>0).sum(), rng=100*(np.exp([d.min(),d.max()])-1), sd=100*sd)
    for lab,rr in [('pearson',r1),('acf',r1b)]:
        neff = n*(1-rr)/(1+rr) if rr>0 else n
        for dof in [n-1, neff-1]:
            tt=stats.t.ppf(.975,dof)
            out[f'ar_{lab}_dof{dof:.1f}'] = 100*(np.exp([m-tt*sd/np.sqrt(neff), m+tt*sd/np.sqrt(neff)])-1)
    s = stats.linregress(np.log(v), d)
    out['dn']=s.slope; out['dnhalf']=stats.t.ppf(.975,n-2)*s.stderr; out['dn_p']=s.pvalue
    return out
for b,c in [('Ra20','Ra40'),('Ra20','Ra80'),('Ra40','Ra80')]:
    o=paired(b,c,P); print(c,'vs',b, {k:(np.round(val,3) if not isinstance(val,(int,np.integer)) else val) for k,val in o.items()})
for r in P:
    s=stats.linregress(np.log(v), np.log(P[r])); print(r,'n=',round(s.slope,3),'a(uW)=',round(np.exp(s.intercept)*1e6,3))
# Voc comparisons
for b,c in [('Ra20','Ra40'),('Ra20','Ra80'),('Ra40','Ra80')]:
    d=np.log(VOC[c]/VOC[b]); s=stats.linregress(np.log(v),d)
    lo = v<17; hi = v>31
    print('Voc',c,'vs',b,'chg',round(100*(np.exp(d.mean())-1),2),'higher',(d>0).sum(),'slope',round(s.slope,4),'p',round(s.pvalue,4),
          'low<17',round(100*(np.exp(d[lo].mean())-1),2),'high>31',round(100*(np.exp(d[hi].mean())-1),2), 'lo set', fans[lo], 'hi set', fans[hi])
    dr=np.log(RINT[c]/RINT[b]); print('   Rint chg',round(100*(np.exp(dr.mean())-1),2))
    dv=np.log(V1[c]/V1[b]); print('   V1 chg',round(100*(np.exp(dv.mean())-1),2),'higher',(dv>0).sum())
for r in VOC:
    print(r,'Voc~v^',round(stats.linregress(np.log(v),np.log(VOC[r])).slope,3),'Rint~v^',round(stats.linregress(np.log(v),np.log(RINT[r])).slope,3))
# cut-in model fit to Ra20
best=None
for vc in np.arange(-3,8,0.01):
    x=np.log(v-vc); s=stats.linregress(x,np.log(P['Ra20'])); sse=((np.log(P['Ra20'])-(s.intercept+s.slope*x))**2).sum()
    if best is None or sse<best[0]: best=(sse,vc,s.slope,s.intercept)
sse,vc,m,la=best; print('cut-in fit vc',round(vc,2),'m',round(m,3))
nA = stats.linregress(np.log(v),np.log(P['Ra20'])).slope
for c,obs in [('Ra40',np.exp(np.log(P['Ra40']/P['Ra20']).mean())-1),('Ra80',np.exp(np.log(P['Ra80']/P['Ra20']).mean())-1)]:
    for dv in np.arange(0,2,0.001):
        pm = np.exp(la)*(v-vc+dv)**m
        g = np.exp(np.log(pm/np.exp(la)/(v-vc)**m).mean())-1
        if g>=obs: break
    dn = stats.linregress(np.log(v), np.log(pm)).slope - stats.linregress(np.log(v), np.log(np.exp(la)*(v-vc)**m)).slope
    print(c,'obs gain',round(100*obs,2),'shift',round(dv,3),'dn',round(dn,3))
# Cp_el
A=2*0.1016*0.2451
for r in P: cp=P[r]/(0.5*1.225*A*v**3); print(r,'cp range %',round(100*cp.min(),3),round(100*cp.max(),3))
np.save('/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/build/review2/verifier/voc.npy', np.array([VOC['Ra20'],VOC['Ra40'],VOC['Ra80']]))
# slip bound: fan_rpm_actual in Ra20
a20 = np.array([D['Ra20'][D['Ra20'].fan_rpm==f].fan_rpm_actual.iloc[0] for f in fans])
print('Ra20 actual', a20, 'deficit', fans-a20)
print('---- slip bound')
vact = 0.02132*a20 - 0.424
for c in ['Ra40','Ra80']:
    for n in [nA, 3.0]:
        d = np.log(P[c]/P['Ra20']) - n*np.log(v/vact)
        print(c, 'n',round(n,2), 'corrected gain', round(100*(np.exp(d.mean())-1),2))
# residual autocorr for Voc slope
for b,c in [('Ra20','Ra80'),('Ra40','Ra80')]:
    d=np.log(VOC[c]/VOC[b]); x=np.log(v); s=stats.linregress(x,d); res=d-(s.intercept+s.slope*x)
    r1=(res[:-1]*res[1:]).sum()/(res*res).sum()
    neff=14*(1-r1)/(1+r1) if r1>0 else 14
    tstat=s.slope/s.stderr; 
    # crude inflation of SE
    se2=s.stderr*np.sqrt((14-2)/(max(neff,3)-2)); p2=2*stats.t.sf(abs(s.slope/se2), max(neff,3)-2)
    print('Voc slope',c,b,'r1 resid',round(r1,3),'neff',round(neff,2),'p naive',round(s.pvalue,4),'p AR-adj approx',round(p2,4))
    # leave-one-out
    ps=[]
    for i in range(14):
        m=np.ones(14,bool); m[i]=False; ss=stats.linregress(x[m],d[m]); ps.append((fans[i],round(ss.slope,3),round(ss.pvalue,4)))
    print('  LOO', ps)
    # Spearman
    print('  spearman', stats.spearmanr(x,d))
