import numpy as np, pandas as pd
raw = pd.read_csv('../../../inputs/jeong_lab/2026-07-27_no_texture_baseline/0727windturbine.csv')
t = raw.iloc[:,0].values; ch = raw.iloc[:,3:8].values
N=len(raw); L=N//17
V=4*ch[:,0]; I=2*(ch[:,1]-2.5); P=V*I
sp=[]
for k in range(16):
    a=k*L+1870; b=k*L+5611
    s=slice(a,b+1); pk=np.argmax(P[s])+a
    sp.append(I[pk]-I[max(0,pk-180):pk+180].mean())
print('spike range', min(sp), max(sp))
# rotor pulses ch3 upward jumps > 0.1
d=np.diff(ch[:,2]); e=np.where(d>0.1)[0]
te=t[e+1]
# rpm in 2-s bins
bins=np.arange(0,354,2.0)
cnt,_=np.histogram(te,bins)
# print rpm timeline with I mean and V mean per 2 s
z=2.496337891; Iz=2*(ch[:,1]-z)
for i in range(len(bins)-1):
    m=(t>=bins[i])&(t<bins[i+1])
    print(f"{bins[i]:6.0f} rpm~{cnt[i]*30:5.0f} V={V[m].mean():6.2f} I={Iz[m].mean()*1000:6.1f}mA")
