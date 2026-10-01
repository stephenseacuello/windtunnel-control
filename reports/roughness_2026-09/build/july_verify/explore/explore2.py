import numpy as np, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
A=np.load('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/X.npy')
t=A[:,0]; X=A[:,1:]
fs=360
def boxmean(x,n):
    m=len(x)//n; return x[:m*n].reshape(m,n).mean(1)
n=360
tb=boxmean(t,n)
fig,ax=plt.subplots(5,1,figsize=(16,14),sharex=True)
for j in range(5):
    ax[j].plot(t[::4],X[::4,j],lw=0.2,color='0.7')
    ax[j].plot(tb,boxmean(X[:,j],n),lw=1,color='C0')
    ax[j].set_ylabel(f'ch{j+1}')
    ax[j].grid(alpha=.3)
    for k in range(18): ax[j].axvline(k*7482/360,color='r',lw=0.5)
ax[-1].set_xticks(np.arange(0,360,10))
plt.tight_layout(); plt.savefig('overview.png',dpi=70)
