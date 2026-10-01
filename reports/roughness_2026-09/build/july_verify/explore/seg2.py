import numpy as np, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from scipy.ndimage import median_filter, uniform_filter1d
from scipy.signal import find_peaks
A=np.load('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/X.npy')
t=A[:,0]; X=A[:,1:]; N=len(t); fs=360.
V=4*X[:,0]; I=2*(X[:,1]-2.5); L=7482
pk=np.load('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/pulses.npy')
tp=t[pk]; dtp=np.diff(tp); med=median_filter(dtp,9,mode='nearest'); nrev=np.maximum(1,np.round(dtp/med))
finst=nrev/dtp; tm=(tp[1:]+tp[:-1])/2
g=np.arange(0.5,329.5,0.25)
f=np.interp(g,tm,finst)
fs_=uniform_filter1d(f,8)  # 2 s
Ig=np.interp(g,t,uniform_filter1d(I,360))
Vg=np.interp(g,t,uniform_filter1d(V,360))
h=12 # 3 s each side
df=np.full_like(g,np.nan); dI=np.full_like(g,np.nan); dV=np.full_like(g,np.nan)
df[h:-h]=fs_[2*h:]-fs_[:-2*h]; dI[h:-h]=Ig[2*h:]-Ig[:-2*h]; dV[h:-h]=Vg[2*h:]-Vg[:-2*h]
np.savez('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/grid.npz',g=g,f=f,fs_=fs_,Ig=Ig,Vg=Vg,df=df,dI=dI,dV=dV)
pks,pr=find_peaks(np.nan_to_num(df/np.maximum(fs_,0.5)),height=0.02,distance=16)
for p in pks: print(f't={g[p]:6.2f}  df={df[p]:+.3f} Hz ({df[p]/fs_[p]*100:+.1f}%)  dI={dI[p]*1000:+.1f} mA dV={dV[p]:+.2f}')
fig,ax=plt.subplots(3,1,figsize=(18,10),sharex=True)
ax[0].plot(g,df/np.maximum(fs_,.5)); ax[0].plot(g[pks],(df/np.maximum(fs_,.5))[pks],'rx'); ax[0].set_ylabel('rel df over 6 s')
ax[1].plot(g,dI*1000); ax[1].set_ylabel('dI mA over 6 s')
ax[2].plot(g,fs_); ax[2].set_ylabel('f Hz')
for a in ax: a.grid(alpha=.3)
ax[2].set_xticks(np.arange(0,335,5)); plt.setp(ax[2].get_xticklabels(),fontsize=7,rotation=90)
plt.tight_layout(); plt.savefig('seg2.png',dpi=60)
