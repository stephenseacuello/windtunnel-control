import numpy as np, pandas as pd
from scipy import stats
L = '/Users/stepheneacuello/Projects/windtunnel-control/logs/'
runs = {'A': 'Ra20', 'B': 'Ra40', 'C': 'Ra80'}
tf = {'A': 0.050, 'B': 0.101, 'C': 0.202}
pts = {k: pd.read_csv(L + f'sweep_v1_{v}_points.csv', comment='#') for k, v in runs.items()}
summ = {k: pd.read_csv(L + f'sweep_v1_{v}_summary.csv', comment='#') for k, v in runs.items()}

def refine(pp, span=2):
    k = max(range(len(pp)), key=lambda j: pp[j][1])
    raw = pp[k][1]
    if len(pp) < 2 * span + 1:
        return raw
    lo, hi = max(0, k - span), min(len(pp), k + span + 1)
    w = pp[lo:hi]
    if len(w) < 3:
        return raw
    x = np.array([a for a, _ in w]); y = np.array([b for _, b in w])
    A = np.vstack([x**2, x, np.ones_like(x)]).T
    a2, a1, a0 = np.linalg.lstsq(A, y, rcond=None)[0]
    if a2 >= 0:
        return raw
    ih = -a1 / (2 * a2)
    if not (w[0][0] <= ih <= w[-1][0]):
        return raw
    return a2 * ih**2 + a1 * ih + a0

rpms = list(range(500, 1900, 100))
raw = {}; fit = {}; voc = {}; rint = {}; r2th = {}; vlight = {}; motor = {}; slip = {}; rolloff = {}
for k, df in pts.items():
    raw[k] = []; fit[k] = []; voc[k] = []; rint[k] = []; r2th[k] = []; vlight[k] = []; motor[k] = []; slip[k] = []; rolloff[k] = []
    for r in rpms:
        d = df[(df.fan_rpm == r)]
        t = d[(d.tracking == 1) & (d.amps > 0)]
        pp = list(zip(t.amps, t.watts))
        raw[k].append(max(w for _, w in pp)); fit[k].append(refine(pp))
        tv = d[(d.tracking == 1) & (d.amps > 0) & (d.volts > 0)]
        sl, ic, rr, _, _ = stats.linregress(tv.amps, tv.volts)
        voc[k].append(ic); rint[k].append(-sl); r2th[k].append(rr**2)
        vlight[k].append(t.volts.iloc[0])
        motor[k].append(d.motor_amps.values)
        slip[k].append((r - d.fan_rpm_actual).values)
        rolloff[k].append(t.watts.iloc[-1] / t.watts.max())
    raw[k] = np.array(raw[k]); fit[k] = np.array(fit[k]); voc[k] = np.array(voc[k]); rint[k] = np.array(rint[k])
    vlight[k] = np.array(vlight[k])

v = 0.02132 * np.array(rpms) - 0.424
print('v', np.round(v, 2))
for k in 'ABC':
    print(k, 'raw', np.round(raw[k], 4))
    print(k, 'fit', np.round(fit[k], 4))
    s = summ[k]
    col = 'p_max_w' if 'p_max_w' in s else 'p_max_raw_w'
    print(k, 'raw==logged', np.allclose(raw[k], s[col].values, atol=5e-5))
    if 'p_max_fit_w' in s:
        rel = (fit[k] - s.p_max_fit_w.values) / s.p_max_fit_w.values * 100
        print(k, 'fit vs logged max rel %', np.round(np.abs(rel).max(), 3), np.round(rel, 3))

def paired(b, c):
    d = np.log(c / b); n = len(d); m = d.mean(); s = d.std(ddof=1)
    t = stats.t.ppf(0.975, n - 1)
    lv = np.log(v)
    res = stats.linregress(lv, d)
    tn = stats.t.ppf(0.975, n - 2)
    ns = (d > 0).sum()
    p = stats.binomtest(int(ns), n, 0.5).pvalue
    return dict(lvl=(np.exp(m) - 1) * 100, lo=(np.exp(m - t * s / np.sqrt(n)) - 1) * 100,
                hi=(np.exp(m + t * s / np.sqrt(n)) - 1) * 100, hi_n=ns, sd=s * 100,
                minr=(np.exp(d.min()) - 1) * 100, maxr=(np.exp(d.max()) - 1) * 100,
                dn=res.slope, dnh=tn * res.stderr, p=p)

for basis, P in (('raw', raw), ('fit', fit)):
    for a, b in (('A', 'B'), ('A', 'C'), ('B', 'C')):
        r = paired(P[a], P[b])
        print(basis, a + b, {kk: round(float(vv), 4) for kk, vv in r.items()})
    mono = ((P['A'] < P['B']) & (P['B'] < P['C'])).sum()
    print(basis, 'monotone', mono)
    # trend
    y = []; X = []
    for i in range(14):
        for k in 'ABC':
            row = np.zeros(15); row[i] = 1; row[14] = np.log(tf[k]); X.append(row); y.append(np.log(P[k][i]))
    X = np.array(X); y = np.array(y)
    beta, res, rk, sv = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta; dof = len(y) - 15
    s2 = resid @ resid / dof
    cov = s2 * np.linalg.inv(X.T @ X)
    se = np.sqrt(cov[14, 14]); tt = stats.t.ppf(0.975, dof)
    b = beta[14]
    print(basis, 'beta', round(b, 4), 'CI', round(b - tt * se, 4), round(b + tt * se, 4), 'dof', dof,
          'per doubling', round((2**b - 1) * 100, 2), round((2**(b - tt * se) - 1) * 100, 2), round((2**(b + tt * se) - 1) * 100, 2))
    # power law
    for k in 'ABC':
        res = stats.linregress(np.log(v), np.log(P[k]))
        tn = stats.t.ppf(0.975, 12)
        a = np.exp(res.intercept)
        pred = a * v**res.slope
        r2lin = 1 - ((P[k] - pred)**2).sum() / ((P[k] - P[k].mean())**2).sum()
        print(basis, k, 'n', round(res.slope, 4), 'CI', round(res.slope - tn * res.stderr, 3), round(res.slope + tn * res.stderr, 3),
              'a uW', round(a * 1e6, 3), 'R2log', round(res.rvalue**2, 4), 'R2lin', round(r2lin, 4))
    # log share of Ra40
    dAB = np.log(P['B'] / P['A']).mean(); dAC = np.log(P['C'] / P['A']).mean()
    print(basis, 'logshare40', round(dAB / dAC * 100, 1))
    i7 = rpms.index(700)
    print(basis, '700 gap B vs C %', round((P['B'][i7] / P['C'][i7] - 1) * 100, 2))

print('thevenin min r2', min(min(r2th[k]) for k in 'ABC'))
for k in 'ABC':
    print(k, 'Voc', np.round(voc[k], 2)); print(k, 'Rint', np.round(rint[k], 1))
for k in 'BC':
    r = paired(voc['A'], voc[k]); print('Voc', k, round(r['lvl'], 2), 'half', round((r['hi'] - r['lo']) / 2, 2), r['lo'], r['hi'], 'higher', r['hi_n'])
    r = paired(rint['A'], rint[k]); print('Rint', k, round(r['lvl'], 2), round(r['lo'], 2), round(r['hi'], 2))
    r = paired(vlight['A'], vlight[k]); print('Vlight', k, round(r['lvl'], 2), 'higher', r['hi_n'])
    dv = np.log(voc[k] / voc['A']).mean(); dP = np.log(raw[k] / raw['A']).mean()
    dr = np.log(rint[k] / rint['A']).mean()
    print('Voc share', k, round(2 * dv / dP * 100, 1), 'check 2dv - dr vs dP', 2 * dv - dr, dP)
# generator exponents
for k in 'ABC':
    sv = stats.linregress(np.log(v), np.log(voc[k])); sr = stats.linregress(np.log(v), np.log(rint[k]))
    print(k, 'Voc exp', round(sv.slope, 3), 'Rint exp', round(sr.slope, 3), 'pred n', round(2 * sv.slope - sr.slope, 3))
    # wind prediction: if Voc up x% from wind, Rint changes by (sr/sv)*x
    print(k, 'ratio', sr.slope / sv.slope)
for k in 'BC':
    dv = np.log(voc[k] / voc['A']).mean()
    sv = stats.linregress(np.log(v), np.log(voc['A'])); sr = stats.linregress(np.log(v), np.log(rint['A']))
    print('rifwind', k, round((np.exp(dv * sr.slope / sv.slope) - 1) * 100, 2))
# slip
for k in 'ABC':
    allslip = np.concatenate(slip[k]); print(k, 'slip range', allslip.min(), allslip.max())
    print(k, 'rolloff range %', round(min(rolloff[k]) * 100, 1), round(max(rolloff[k]) * 100, 1))
# motor current
for i, r in enumerate(rpms):
    m = [np.median(motor[k][i]) for k in 'ABC']; mm = [motor[k][i].mean() for k in 'ABC']
    print(r, 'motor med', m, 'mean', np.round(mm, 3), 'spread', round(max(mm) - min(mm), 3))
# Cp_el
for k in 'ABC':
    cp = raw[k] / (0.5 * 1.204 * 0.0498 * v**3) * 100
    print(k, 'Cp_el %', np.round(cp, 3))
np.save('/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/build/review/numbers/raw.npy', np.array([raw[k] for k in 'ABC']))
