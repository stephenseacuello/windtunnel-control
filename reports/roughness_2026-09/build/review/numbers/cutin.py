import numpy as np
from scipy import stats, optimize
raw = np.load('raw.npy'); A = raw[0]
rpms = np.arange(500, 1900, 100); v = 0.02132*rpms - 0.424
def f(p):
    la, vc, m = p
    return np.log(A) - (la + m*np.log(v - vc))
best = None
for vc0 in (0, 2, 4, 6, 8):
    r = optimize.least_squares(f, [np.log(1e-5), vc0, 3.0], bounds=([-50, -20, 0.5], [10, 10.0, 10]))
    if best is None or r.cost < best.cost: best = r
la, vc, m = best.x; print('fit vc', vc, 'm', m, 'cost', best.cost)
P0 = np.exp(la)*(v-vc)**m
n0 = stats.linregress(np.log(v), np.log(P0)).slope
for sh in (-0.25, -0.5):
    P1 = np.exp(la)*(v-vc-sh)**m
    n1 = stats.linregress(np.log(v), np.log(P1)).slope
    print(sh, 'level %', round((np.exp(np.mean(np.log(P1/P0)))-1)*100, 1), 'dn', round(n1-n0, 3))
# alternative: constant torque/power offset model P = a v^n - c tuned to 15% level
from scipy.optimize import brentq
n = stats.linregress(np.log(v), np.log(A)).slope
a = np.exp(stats.linregress(np.log(v), np.log(A)).intercept)
for lvl in (0.137, 0.154):
    # P_b = a v^n + c (constant power offset)
    c = brentq(lambda c: np.exp(np.mean(np.log((a*v**n + c)/(a*v**n)))) - 1 - lvl, 0, 5)
    Pb = a*v**n + c
    print('const power offset', lvl, 'c', round(c, 4), 'dn', round(stats.linregress(np.log(v), np.log(Pb)).slope - n, 3))
