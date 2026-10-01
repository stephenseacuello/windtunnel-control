import numpy as np
from scipy import signal
A=np.load('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/X.npy')
t=A[:,0]; X=A[:,1:]; fs=360.
V=4*X[:,0]
pk=np.load('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/pulses.npy'); tp=t[pk]
# order tracking: resample V onto rotor angle using pulse times as rev marks (assume 1 pulse = 1 cycle of ch3)
def order_spectrum(t0,t1,nper=64):
    m=(tp>=t0)&(tp<=t1); p=tp[m]
    d=np.diff(p); med=np.median(d)
    if np.any(d>1.5*med): return None
    ang=np.arange(len(p))  # cycles
    ta=np.interp(np.arange(0,len(p)-1,1/nper),ang,p)
    va=np.interp(ta,t,V); va=va-va.mean()
    F=np.abs(np.fft.rfft(va*np.hanning(len(va))))
    orders=np.fft.rfftfreq(len(va),1/nper)
    return orders,F,len(p)-1
for (t0,t1) in [(1,22),(30,42),(47,58),(108,125),(147,160),(238,254),(276,292),(296,312)]:
    r=order_spectrum(t0,t1)
    if r is None: print(t0,t1,'gap'); continue
    o,F,n=r
    def amp(ordv):
        i=np.argmin(np.abs(o-ordv)); return F[max(i-1,0):i+2].max()
    base=np.median(F[(o>0.1)&(o<6)])
    print(f'{t0:5.0f}-{t1:5.0f}s ({n} cycles) amplitude/median at orders 1/3,2/3,1,2,3,4,5,6:',
          ' '.join(f'{amp(x)/base:6.1f}' for x in (1/3,2/3,1,2,3,4,5,6)))
