import numpy as np, pandas as pd
F='/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/inputs/jeong_lab/2026-07-27_no_texture_baseline/0727windturbine.csv'
df=pd.read_csv(F)
print(df.columns.tolist())
t=df.iloc[:,0].to_numpy(float)
X=df.iloc[:,3:8].to_numpy(float)
N=len(t); print('N',N,'t0',t[0],'tend',t[-1])
dt=np.diff(t); print('dt stats',dt.min(),dt.max(),np.median(dt), 'fs',1/np.median(dt))
print('event col nonnull', df.iloc[:,8].notna().sum())
for j in range(5):
    x=X[:,j]; u=np.unique(x); d=np.diff(u)
    print(f'ch{j+1} min {x.min():.4f} max {x.max():.4f} mean {x.mean():.4f} nuniq {len(u)} min step {d.min():.6g} step/(5/4096) {d.min()/(5/4096):.4f}')
# LSB check: are values integer multiples of some q with an offset?
q=5/4096
for j in range(5):
    x=X[:,j]; r=x/q; print(f'ch{j+1} frac(x/q) max dev', np.max(np.abs(r-np.round(r))))
# time stamps
ts=df.iloc[:,2]; print(ts.iloc[0], ts.iloc[-1], ts.nunique())
np.save('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/X.npy', np.column_stack([t,X]))
