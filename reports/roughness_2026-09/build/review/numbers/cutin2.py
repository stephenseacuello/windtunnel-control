import numpy as np
from scipy import stats
from scipy.optimize import brentq
rpms = np.arange(500, 1900, 100); v = 0.02132*rpms - 0.424
sl = lambda P: stats.linregress(np.log(v), np.log(P)).slope
for vc in (0, 1, 2, 3, 4, 5, 6, 7, 8):
    m = brentq(lambda m: sl((v-vc)**m) - 3.76, 0.3, 10)
    P0 = (v-vc)**m; P1 = (v-vc+0.5)**m
    print('vc', vc, 'm', round(m,3), 'level', round((np.exp(np.mean(np.log(P1/P0)))-1)*100,1), 'dn', round(sl(P1)-sl(P0),3))
# fixed m=3.76 (no refit), vc such that level 15.4
for m in (3.0, 3.76):
    for vc in (2,4,6,8):
        P0=(v-vc)**m; P1=(v-vc+0.5)**m
        print('m',m,'vc',vc,'n0',round(sl(P0),2),'level', round((np.exp(np.mean(np.log(P1/P0)))-1)*100,1), 'dn', round(sl(P1)-sl(P0),3))
