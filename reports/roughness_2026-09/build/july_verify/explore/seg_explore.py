import numpy as np, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
A=np.load('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/X.npy')
t=A[:,0]; X=A[:,1:]; N=len(t); fs=360.
V=4*X[:,0]; I=2*(X[:,1]-2.5); c3=X[:,2]; L=7482
# pulse detection: upward crossing of -0.6 V, refractory 20 ms
lev=-0.6
up=np.where((c3[1:]>=lev)&(c3[:-1]<lev))[0]+1
keep=[up[0]]
for u in up[1:]:
    if u-keep[-1]>=int(0.02*fs): keep.append(u)
pk=np.array(keep); tp=t[pk]
dtp=np.diff(tp)
print('n pulses',len(pk),'min interval',dtp.min(),'last pulse t',tp[-1])
# local median interval over 9 intervals
from scipy.ndimage import median_filter
med=median_filter(dtp,size=9,mode='nearest')
ratio=dtp/med
print('intervals >1.5x local median:',np.sum(ratio>1.5),' <0.6x:',np.sum(ratio<0.6))
bad=np.where(ratio>1.5)[0]
print('times of long gaps', np.round(tp[bad],2), np.round(ratio[bad],2))
np.save('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/pulses.npy',pk)
f=1/dtp; tm=(tp[1:]+tp[:-1])/2
def bm(x,n=360):
    m=len(x)//n; return x[:m*n].reshape(m,n).mean(1)
tb=bm(t); Ib=bm(I); Vb=bm(V)
fig,ax=plt.subplots(3,1,figsize=(18,12),sharex=True)
ax[0].plot(tm,f,'.',ms=2); ax[0].set_ylabel('pulse rate Hz'); ax[0].set_ylim(0,13)
ax[1].plot(tb,Ib,'.-',ms=3); ax[1].set_ylabel('I 1s mean')
ax[2].plot(tb,Vb,'.-',ms=3); ax[2].set_ylabel('V 1s mean')
for a in ax:
    a.grid(alpha=.3)
    for k in range(16):
        a.axvspan(t[k*L+1870],t[k*L+5611],color='orange',alpha=.15)
        a.text(t[k*L+1870],a.get_ylim()[1]*0.95,str(500+100*k),fontsize=8)
ax[2].set_xticks(np.arange(0,360,5)); plt.setp(ax[2].get_xticklabels(),fontsize=7,rotation=90)
plt.tight_layout(); plt.savefig('seg_explore.png',dpi=60)
