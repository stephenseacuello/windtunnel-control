import numpy as np, pandas as pd
A=np.load('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/X.npy')
t=A[:,0]; X=A[:,1:]; N=len(t)
S=pd.read_csv('/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/inputs/jeong_lab/2026-07-27_no_texture_baseline/Summary_Table.csv')
V=4*X[:,0]; I=2*(X[:,1]-2.5); P=V*I; c3=X[:,2]
L=N//17; print('N',N,'L',L, 'N/17', N/17, 'L/4',L/4, '3L/4', 3*L/4)
def recipe(a,b,thr=0.1):
    s=slice(a,b+1)
    cnt=int(np.sum(np.diff(c3[s])>thr))
    D=t[b]-t[a]
    return 60*cnt/D, V[s].max(), I[s].max(), P[s].max(), cnt, D
res=[]
for k in range(16):
    a=k*L+1870; b=k*L+5611
    r=recipe(a,b)
    res.append(r)
R=np.array([r[:4] for r in res])
tab=S[['Measured_RPM','Vdc_max','Idc_max','Pdc_max']].to_numpy()
rel=np.abs(R/tab-1)
print('max rel err per col', rel.max(0))
# implied counts
D=np.array([r[5] for r in res]); cnt=np.array([r[4] for r in res])
implied=S.Measured_RPM.to_numpy()*D/60
print('implied counts', np.round(implied,6)); print('my counts', cnt)
# threshold sensitivity
for thr in (0.02,0.05,0.08,0.1,0.15,0.2,0.3,0.5,0.8,1.0,1.2):
    c=[int(np.sum(np.diff(c3[k*L+1870:k*L+5612])>thr)) for k in range(16)]
    print(thr, 'matches', int(np.sum(np.array(c)==np.round(implied))), c)
