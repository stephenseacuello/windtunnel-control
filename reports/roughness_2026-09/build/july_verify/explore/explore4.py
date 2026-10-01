import numpy as np, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from scipy import signal
A=np.load('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/X.npy')
t=A[:,0]; X=A[:,1:]; fs=360.
V=4*X[:,0]; I=2*(X[:,1]-2.5)
def mm(x,n=360):
    k=np.ones(n)/n; return np.convolve(x,k,'same')
rI=I-mm(I); rV=V-mm(V)
segs={'start0-55':(2,55),'mid 150-165':(150,165),'late 300-315':(300,315),'loadoff 332-352':(332,352)}
fig,ax=plt.subplots(2,1,figsize=(14,9))
for name,(a,b) in segs.items():
    m=(t>=a)&(t<b)
    f,p=signal.welch(rI[m],fs,nperseg=2048); ax[0].semilogy(f,p,lw=.7,label=name)
    f,p2=signal.welch(rV[m],fs,nperseg=2048); ax[1].semilogy(f,p2,lw=.7,label=name)
    ac=[np.corrcoef(rI[m][:-L],rI[m][L:])[0,1] for L in (1,2,3,6)]
    print(f'{name}: sd I resid {rI[m].std()*1000:.2f} mA, sd V resid {rV[m].std()*1000:.1f} mV, meanI {I[m].mean()*1000:.2f} mA, corr(rV,rI) {np.corrcoef(rV[m],rI[m])[0,1]:.3f}, acf I lag1,2,3,6 {np.round(ac,3)}')
ax[0].legend(); ax[0].set_title('I residual PSD'); ax[1].set_title('V residual PSD'); ax[1].legend()
plt.tight_layout(); plt.savefig('psd_explore.png',dpi=65)
fig,ax=plt.subplots(2,1,figsize=(14,7),sharex=True)
m=(t>=300)&(t<301)
ax[0].plot(t[m],V[m],'.-',ms=2,lw=.5); ax[1].plot(t[m],I[m],'.-',ms=2,lw=.5)
plt.savefig('zoom_VI.png',dpi=65)
