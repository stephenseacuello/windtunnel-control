import numpy as np
A=np.load('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/X.npy')
t=A[:,0]; V=4*A[:,1]
pk=np.load('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/pulses.npy'); tp=t[pk]
m=(tp>328.5)&(tp<332.5)
for a,b in zip(tp[m][:-1],tp[m][1:]):
    mm=(t>=a)&(t<b)
    print(f'{a:8.3f}-{b:8.3f}  f={1/(b-a):6.2f} Hz rpm={60/(b-a):6.1f}  V mean {V[mm].mean():6.2f}  V max {V[mm].max():6.2f}')
