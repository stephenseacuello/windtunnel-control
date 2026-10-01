import numpy as np, pandas as pd
d = '/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/inputs/jeong_lab/2026-07-27_no_texture_baseline/'
raw = pd.read_csv(d + '0727windturbine.csv'); raw.columns = ['t','date','ts','c1','c2','c3','c4','c5','ev']
lab = pd.read_csv(d + 'Summary_Table.csv')
t = raw.t.values; c3 = raw.c3.values; L = len(raw)//17
for thr in (0.1,):
    for k in range(16):
        i0, i1 = k*L+1870, k*L+5611+1
        dc = np.diff(c3[i0:i1])
        n = (dc > thr).sum()
        dur_a = 3742/360; dur_b = t[i1-1]-t[i0]
        rpm_a = 60*n/dur_a; rpm_b = 60*n/dur_b
        # true: period from rising-edge intervals (debounced)
        up = np.where(dc > thr)[0]
        # debounce: merge edges within 5 samples
        if len(up):
            keep = [up[0]] + [u for p,u in zip(up[:-1], up[1:]) if u - p > 5]
        else: keep=[]
        per = np.median(np.diff(keep))/360 if len(keep)>2 else np.nan
        print(lab.Setting_RPM[k], 'lab', round(lab.Measured_RPM[k],3), 'n', n, 'rpm_a', round(rpm_a,3), 'rpm_b', round(rpm_b,3), 'debounced n', len(keep), 'median-period rpm', round(60/per,1) if per==per else None)
