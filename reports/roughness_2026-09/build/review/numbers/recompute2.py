import numpy as np, pandas as pd
from scipy import stats
L = '/Users/stepheneacuello/Projects/windtunnel-control/logs/'
raw = np.load('/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/build/review/numbers/raw.npy')
rpms = np.arange(500, 1900, 100)
v = 0.02132 * rpms - 0.424
A, B, C = raw
# run minutes
for r in ('Ra40', 'Ra80'):
    p = pd.read_csv(L + f'sweep_v1_{r}_points.csv', comment='#')
    print(r, 'minutes first->last dwell', round((p.t_unix.max() - p.t_unix.min()) / 60, 2))
tr = pd.read_csv(L + 'sweep_v1_Ra40_trace.csv', comment='#')
print(tr.columns.tolist()[:10], len(tr))
tcol = [c for c in tr.columns if 't_unix' in c or c == 't']
if tcol:
    print('trace span min', (tr[tcol[0]].max() - tr[tcol[0]].min()) / 60)

# slip sensitivity
s20 = pd.read_csv(L + 'sweep_v1_Ra20_summary.csv', comment='#')
vact = 0.02132 * s20.fan_rpm_actual.values - 0.424
print('logged wind vs recomputed', np.round(s20.wind_mps.values - vact, 3))
n20 = stats.linregress(np.log(v), np.log(A)).slope
def paired(b, c):
    d = np.log(c / b); n = len(d); m = d.mean(); s = d.std(ddof=1); t = stats.t.ppf(0.975, n - 1)
    return round((np.exp(m) - 1) * 100, 2), round((np.exp(m - t * s / np.sqrt(n)) - 1) * 100, 2), round((np.exp(m + t * s / np.sqrt(n)) - 1) * 100, 2), int((d > 0).sum())
for expo in (n20, 3.0):
    corr = (v / vact) ** expo
    Ac = A * corr
    print('expo', round(expo, 3), 'maxcorr %', round((corr.max() - 1) * 100, 2), 'B', paired(Ac, B), 'C', paired(Ac, C))
# with wind_mps logged column
corr = (v / s20.wind_mps.values) ** n20
print('logged col', paired(A * corr, B), paired(A * corr, C), round((corr.max() - 1) * 100, 2))

# ratios per set point
print('B/A %', np.round((B / A - 1) * 100, 1))
print('C/A %', np.round((C / A - 1) * 100, 1))
print('C/B %', np.round((C / B - 1) * 100, 1))

# cut-in model: P = a (v - vc)^m ; shift vc by 0.5
for vc0 in (0.0, 2.0, 4.0):
    # choose m so apparent n ~3.76
    for m in (3.0, 3.5, 3.76):
        P0 = (v - vc0) ** m; P1 = (v - vc0 - 0.5) ** m
        n0 = stats.linregress(np.log(v), np.log(P0)).slope; n1 = stats.linregress(np.log(v), np.log(P1)).slope
        lvl = (np.exp(np.mean(np.log(P0 / P1))) - 1) * 100
        print('vc0', vc0, 'm', m, 'n0', round(n0, 3), 'dn', round(n0 - n1, 3), 'level %', round(lvl, 1),
              'range', round((P0[0] / P1[0] - 1) * 100, 1), round((P0[-1] / P1[-1] - 1) * 100, 1))
# friction model: P_el ∝ (T_aero - T_f) * omega ; alternative: P = a v^n - c
# Re
for nu in (1.5e-5, 1.516e-5, 1.54e-5, 1.56e-5):
    print('nu', nu, 'Re', round(v[0] * 0.048 / nu), round(v[-1] * 0.048 / nu))
print('ratio report', 119735 / 32376, 'v ratio', v[-1] / v[0])
print('t/c', 1.79 / 48)
print('fold', v[-1] / v[0])
