import numpy as np, pandas as pd
A=np.load('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/X.npy')
t=A[:,0]; X=A[:,1:]; N=len(t)
S=pd.read_csv('/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/inputs/jeong_lab/2026-07-27_no_texture_baseline/Summary_Table.csv')
V=4*X[:,0]; I=2*(X[:,1]-2.5); P=V*I; c3=X[:,2]; L=7482
tab=S[['Measured_RPM','Vdc_max','Idc_max','Pdc_max']].to_numpy()
def vals(a,b):
    s=slice(a,b+1); cnt=np.sum(np.diff(c3[s])>0.1)
    return np.array([60*cnt/(t[b]-t[a]),V[s].max(),I[s].max(),P[s].max()])
# joint shift of start, keeping length
ok=[]
for sh in range(-400,401):
    m=0
    for k in range(16):
        a=k*L+1870+sh; b=a+3741
        m+=int(np.sum(np.abs(vals(a,b)/tab[k]-1)<1e-12))
    ok.append((sh,m))
ok=np.array(ok); full=ok[ok[:,1]==64,0]
print('joint shifts giving 64/64:', full.min() if len(full) else None, full.max() if len(full) else None, len(full))
# per-window: range of start a (length fixed) giving 4/4
for k in range(16):
    good=[sh for sh in range(-400,401) if np.all(np.abs(vals(k*L+1870+sh,k*L+1870+sh+3741)/tab[k]-1)<1e-12)]
    print(k, 'per-window start shift range for 4/4:', (min(good),max(good)) if good else None)
# duration via (b-a)/360 instead of relative time column
k=0;a=1870;b=5611
print('D from column',t[b]-t[a],'D from n/360',(b-a)/360.)
# length alternatives: vary length by +-1, keep start
for dl in (-2,-1,1,2):
    m=sum(int(np.abs(vals(k*L+1870,k*L+1870+3741+dl)[0]/tab[k,0]-1)<1e-12) for k in range(16))
    print('length change',dl,'RPM matches',m)
