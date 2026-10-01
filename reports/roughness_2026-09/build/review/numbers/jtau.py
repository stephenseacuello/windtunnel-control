import numpy as np, pandas as pd
from scipy.optimize import curve_fit
d = '/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/inputs/jeong_lab/2026-07-27_no_texture_baseline/'
raw = pd.read_csv(d + '0727windturbine.csv'); raw.columns = ['t','date','ts','c1','c2','c3','c4','c5','ev']
t = raw.t.values; V = 4*raw.c1.values
V1 = pd.Series(V).rolling(36, center=True).mean().values
for a in np.arange(320, 354, 2):
    m = (t >= a) & (t < a+2); print(a, round(np.nanmean(V1[m]),2), 'I', round(np.mean(2*(raw.c2.values[m]-2.4963)),4))
m = (t > 331) & (t < 353)
f = lambda x, A, tau, C: A*np.exp(-(x-331)/tau) + C
p, _ = curve_fit(f, t[m], V[m], p0=[10, 18, 5]); print('fit A tau C', p)
f2 = lambda x, A, tau: A*np.exp(-(x-331)/tau)
p2, _ = curve_fit(f2, t[m], V[m], p0=[20, 18]); print('fit no offset', p2)
