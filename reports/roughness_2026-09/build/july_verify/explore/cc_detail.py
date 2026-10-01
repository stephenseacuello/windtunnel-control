import numpy as np, json
A=np.load('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/X.npy')
t=A[:,0]; X=A[:,1:]; V=4*X[:,0]; z=2.49607; I=2*(X[:,1]-z)
d=json.load(open('verify_numbers.json'))
for e in d['C6_fan_steps']:
    pre=(t>e['onset']-2)&(t<e['onset']); post=(t>e['rise_end'])&(t<e['rise_end']+2)
    I0,I1=I[pre].mean(),I[post].mean(); V0,V1=V[pre].mean(),V[post].mean()
    # current change within the rise itself
    mid=(t>e['onset'])&(t<e['rise_end'])
    print(f"step {e['t']:6.1f}: I {I0*1000:6.1f}->{I1*1000:6.1f} mA  V {V0:5.2f}->{V1:5.2f} ({(V1/V0-1)*100:+.1f}%)  ratio {((I1/I0-1)/(V1/V0-1)) if I0>0.02 else float('nan'):+.3f}")
# wind cut -> load-off window
pk=np.load('/private/tmp/claude-503/-Users-stepheneacuello-Projects-windtunnel-control/6a3806a4-9014-460a-a0dd-c69522320797/scratchpad/pulses.npy'); tp=t[pk]
fr=1/np.diff(tp); tm=(tp[1:]+tp[:-1])/2
for tt in np.arange(324.0,329.8,0.5):
    m=(t>tt-0.25)&(t<tt+0.25)
    print(f't={tt:6.2f} f={np.interp(tt,tm,fr):5.2f} Hz  V={V[m].mean():6.2f}  I={I[m].mean()*1000:6.1f} mA')
m=(t>326.5)&(t<329.5)
bI=I[m][:len(I[m])//90*90].reshape(-1,90).mean(1); bV=V[m][:len(V[m])//90*90].reshape(-1,90).mean(1)
sl=np.polyfit(bV,bI,1)[0]
print('wind-cut window 326.5-329.5 s: dI/dV',round(sl,5),'A/V; normalized (dI/I)/(dV/V)',round(sl*bV.mean()/bI.mean(),3),' V range',round(bV.min(),2),round(bV.max(),2),' I mean/sd mA',round(bI.mean()*1000,1),round(bI.std()*1000,2))
