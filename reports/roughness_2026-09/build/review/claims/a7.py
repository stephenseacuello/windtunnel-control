import numpy as np
from scipy import stats
v=0.02132*np.arange(500,1801,100)-0.424; lv=np.log(v)
for vc in (0,1,2,3,4,5,6):
    # choose m so that power-law fit exponent of (v-vc)^m equals 3.77
    s=stats.linregress(lv,np.log(v-vc)).slope; m=3.77/s
    d=m*np.log((v-vc+0.5)/(v-vc)); r=stats.linregress(lv,d)
    # residual R2 of power law
    print('vc=%.0f m=%.2f  -0.5 shift: level %+.1f%% dn %+.3f'%(vc,m,100*np.expm1(d.mean()),r.slope))
