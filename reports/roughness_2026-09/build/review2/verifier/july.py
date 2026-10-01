import numpy as np, pandas as pd
B='/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/inputs/jeong_lab/2026-07-27_no_texture_baseline/'
raw=pd.read_csv(B+'0727windturbine.csv'); raw.columns=['t','d','ts','c1','c2','c3','c4','c5','ev']
lab=pd.read_csv(B+'Summary_Table.csv')
t=raw.t.values; V=4*raw.c1.values; c2=raw.c2.values
print('rows',len(raw),'fs',1/np.median(np.diff(t[:1000])))
L=len(raw)//17
Ilab=2*(c2-2.5)
off=(t>=331.0)&(t<=341.4)
z=np.median(c2[off]); print('zero',z)
I=2*(c2-z)
P1=pd.Series(V*I).rolling(360,center=True).mean().values
import sys
sys.path.insert(0,'.')
rig=pd.read_csv('/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/build/tables/pmax_v1_Ra20.csv').set_index('fan_rpm_cmd')
rows=[]
for k in range(16):
    i0=k*L+1870; i1=k*L+5611+1
    w=slice(i0,i1)
    s=lab.Setting_RPM[k]
    pl=(V[w]*Ilab[w]).max()
    rows.append(dict(s=s,lab=lab.Pdc_max[k],repro=pl,relerr=pl/lab.Pdc_max[k]-1,p1=np.nanmax(P1[w]),imean=1000*I[w].mean(),vmean=V[w].mean(),
                     vmed=np.median(V[w]),vfirst=V[w][:360].mean(),vlast=V[w][-360:].mean(),t0=t[i0],t1=t[i1-1],
                     rig=rig.p_raw.get(s,np.nan)))
J=pd.DataFrame(rows); J['ratio']=J.p1/J.rig
pd.set_option('display.width',250)
print(J.round(4).to_string())
print('max relerr',J.relerr.abs().max())
u=J[(J.s>=900)&(J.s<=1800)&(J.s!=1300)]
print('usable n',len(u),'below',(u.ratio<1).sum(),'ratio range',u.ratio.min().round(3),u.ratio.max().round(3))
h=u[u.s>=1400]; print('1400-1800 shortfall %',(100*(1-h.ratio.max())).round(1),(100*(1-h.ratio.min())).round(1))
# null test
print('null P max', (V[off]*Ilab[off]).max(), 'bus V range off', V[off].min(), V[off].max())
