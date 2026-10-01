import numpy as np, pandas as pd
d = '/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/inputs/jeong_lab/2026-07-27_no_texture_baseline/'
raw = pd.read_csv(d + '0727windturbine.csv'); raw.columns = ['t','date','ts','c1','c2','c3','c4','c5','ev']
t = raw.t.values; c3 = raw.c3.values; L = len(raw)//17
for k in (4, 8, 15):
    i0, i1 = k*L+1870, k*L+5611+1
    dc = np.diff(c3[i0:i1]); up = np.where(dc > 0.1)[0]
    gaps = np.diff(up)
    print(k, 'gaps', sorted(gaps)[:6], '...', sorted(gaps)[-6:], 'median', np.median(gaps))
    if k == 15:
        med = np.median(gaps[gaps > 5])
        # estimate revs: sum of round(gap/med)
        revs = np.sum(np.round(gaps[gaps>5]/med))
        span = (up[-1]-up[0])/360
        print('median gap', med, 'rpm from median', 60*360/med, 'revs', revs, 'rpm from revs/span', 60*revs/span)
        print('gap hist', np.unique(gaps, return_counts=True))
