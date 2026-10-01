import numpy as np, pandas as pd, json
from scipy import signal
A=np.load('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/X.npy')
t=A[:,0]; X=A[:,1:]; fs=360.
V=4*X[:,0]; ch2=X[:,1]
# 1. mains line: search 50-70 Hz in ch3/4/5 at rest (after rotor stops) and between pulses
for nm,j in (('ch3',2),('ch4',3),('ch5',4),('ch1',0)):
    m=(t>345)&(t<353.3)
    x=X[m,j]-X[m,j].mean()
    f,p=signal.periodogram(x*np.hanning(len(x)),fs,nfft=2**18)
    band=(f>40)&(f<80); i=np.argmax(p[band]); 
    print(nm,'rest peak in 40-80 Hz at',round(f[band][i],3),'Hz; peak/median',round(p[band][i]/np.median(p[band]),1))
# time stamps
df=pd.read_csv('/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/inputs/jeong_lab/2026-07-27_no_texture_baseline/0727windturbine.csv',usecols=[2])
ts=df.iloc[:,0]
chg=np.where(ts.values[1:]!=ts.values[:-1])[0]+1
print('n stamp changes',len(chg),'mean samples/sec-stamp',np.diff(chg).mean(), ' first changes',chg[:5])
n=np.arange(len(ts)); 
# model: second index = floor(n*0.003 + phase)
for ph in np.arange(0,1,0.001):
    s=np.floor(n*0.003+ph); c2=np.where(np.diff(s)>0)[0]+1
    if len(c2)==len(chg) and np.all(c2==chg): print('stamps = floor(n*3ms + %.3f)'%ph); break
# 2. spin-down: V vs EMF from ch3 rate
pk=np.load('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/pulses.npy'); tp=t[pk]
fr=1/np.diff(tp); tm=(tp[1:]+tp[:-1])/2
for tt in (330.5,332,334,336,338,340,342,343.5):
    f_=np.interp(tt,tm,fr); v_=V[(t>tt-0.25)&(t<tt+0.25)].mean()
    print(f't={tt}: ch3 rate {f_:.2f} Hz ({60*f_:.0f} rpm), V {v_:.2f} V, EMF(my fit 0.03145*rpm-0.20) {0.03145*60*f_-0.2:.2f}, EMF(first-pass 0.03342*rpm-0.448) {0.03342*60*f_-0.448:.2f}')
# 3. ch1 near rail
print('ch1>=4.99:',int(np.sum(X[:,0]>=4.99)),' ch1>=4.95:',int(np.sum(X[:,0]>=4.95)), ' max code',round(X[:,0].max()/(5/4096)))
