import numpy as np, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
Z=np.load('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/grid.npz')
g,f,fs_,Ig,Vg=Z['g'],Z['f'],Z['fs_'],Z['Ig'],Z['Vg']
L=7482; t=lambda n:n/360.
wins=[(t(k*L+1870),t(k*L+5611)) for k in range(16)]
fig,ax=plt.subplots(3,3,figsize=(20,12))
for a,(t0,t1) in zip(ax.flat,[(155,190),(185,220),(205,245),(60,90),(120,135),(250,262),(265,280),(288,300),(308,332)]):
    m=(g>=t0)&(g<=t1)
    a.plot(g[m],f[m]/f[m].max(),label='f/max'); a.plot(g[m],Vg[m]/Vg[m].max(),label='V/max')
    a2=a.twinx(); a2.plot(g[m],Ig[m]*1000,'k',lw=.8,label='I mA')
    for k,(w0,w1) in enumerate(wins):
        if w1>t0 and w0<t1: a.axvspan(max(w0,t0),min(w1,t1),color='orange',alpha=.15); a.text(max(w0,t0),0.55,str(500+100*k))
    a.set_xlim(t0,t1); a.grid(alpha=.3); a.legend(loc='lower left',fontsize=7)
plt.tight_layout(); plt.savefig('seg3.png',dpi=55)
