import numpy as np, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
A=np.load('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/X.npy')
t=A[:,0]; X=A[:,1:]
fig,ax=plt.subplots(4,1,figsize=(16,12))
for a,(t0,t1) in zip(ax,[(10,12),(200,201),(318,319),(325,327)]):
    m=(t>=t0)&(t<t1)
    for j in (2,3,4): a.plot(t[m],X[m,j],'.-',ms=3,lw=.6,label=f'ch{j+1}')
    a.legend(); a.grid(alpha=.3)
plt.tight_layout(); plt.savefig('zoom_ch3.png',dpi=65)
# print raw ch3 values around a few pulses at low and high speed
x=X[:,2]
for t0 in (10.0, 318.0):
    i0=np.searchsorted(t,t0)
    seg=x[i0:i0+120]
    idx=np.where(seg>-1.3)[0]
    print(t0, 'samples above -1.3:', idx[:40])
    print(np.round(seg[max(idx[0]-3,0):idx[0]+10],3))
