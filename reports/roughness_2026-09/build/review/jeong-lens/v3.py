import numpy as np, pandas as pd
raw = pd.read_csv('../../../inputs/jeong_lab/2026-07-27_no_texture_baseline/0727windturbine.csv')
t = raw.iloc[:,0].values; ch = raw.iloc[:,3:8].values
N=len(raw); L=N//17
st = pd.read_csv('../../../inputs/jeong_lab/2026-07-27_no_texture_baseline/Summary_Table.csv')
c3=ch[:,2]
for k in range(16):
    a=k*L+1870;b=k*L+5611
    seg=c3[a:b+1]; d=np.diff(seg); e=np.where(d>0.1)[0]
    rpm=60*len(e)/(t[b]-t[a])
    per=np.diff(t[a:b+1][e+1])
    med=np.median(per)
    n_short=(per<0.6*med).sum(); n_long=(per>1.5*med).sum()
    print(st.Setting_RPM[k], len(e), round(rpm,2), round(st.Measured_RPM[k],2), 'med-period rpm', round(60/med,1), 'short',n_short,'long',n_long, 'min/max per', round(per.min(),3), round(per.max(),3))
