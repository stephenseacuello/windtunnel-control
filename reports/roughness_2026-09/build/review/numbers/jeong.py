import numpy as np, pandas as pd
d = '/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/inputs/jeong_lab/2026-07-27_no_texture_baseline/'
raw = pd.read_csv(d + '0727windturbine.csv')
raw.columns = ['t','date','ts','c1','c2','c3','c4','c5','ev']
lab = pd.read_csv(d + 'Summary_Table.csv')
t = raw.t.values; N = len(raw); print('N', N, 'fs', 1/np.median(np.diff(t)), 'dur', t[-1])
L = N // 17; print('L', L)
V = 4*raw.c1.values; Ilab = 2*(raw.c2.values - 2.5)
off = (t >= 331.0) & (t <= 341.4)
z0 = np.median(raw.c2.values[off]); print('z0', z0, 'n off', off.sum())
I = 2*(raw.c2.values - z0)
P1s = pd.Series(V*I).rolling(360, center=True).mean().values
I1s = pd.Series(I).rolling(360, center=True).mean().values
Ilab1s = pd.Series(Ilab).rolling(360, center=True).mean().values
rig20 = dict(zip(range(500,1900,100), [0.0297,0.0604,0.1047,0.1769,0.2732,0.4227,0.6433,0.9592,1.3286,1.6653,2.0806,2.5188,3.0329,3.7935]))
rows=[]
for k in range(16):
    i0, i1 = k*L+1870, k*L+5611+1
    w = slice(i0, i1)
    Pl = V[w]*Ilab[w]
    j = np.argmax(Pl)
    rpm = int(lab.Setting_RPM[k])
    rows.append(dict(rpm=rpm, lab=lab.Pdc_max[k], rep=Pl.max(), Vmax=V[w].max(), Imax=Ilab[w].max(),
        spike=I[w][j]-I1s[w][j], spike_lab=Ilab[w][j]-Ilab1s[w][j], p1s=np.nanmax(P1s[w]), imean=np.mean(I[w])*1000,
        t0=t[i0], t1=t[i1-1], nsamp=i1-i0, ratio=np.nanmax(P1s[w])/rig20.get(rpm, np.nan)))
J = pd.DataFrame(rows)
pd.set_option('display.width', 200)
print(J.round(4))
print('max rel err P', (J.rep/J.lab-1).abs().max(), 'V', (J.Vmax/lab.Vdc_max-1).abs().max(), 'I', (J.Imax/lab.Idc_max-1).abs().max())
print('spike range', J.spike.min(), J.spike.max(), 'lab-zero spike', J.spike_lab.min(), J.spike_lab.max())
print('ratio 900-1800', J[(J.rpm>=900)&(J.rpm<=1800)].ratio.min(), J[(J.rpm>=900)&(J.rpm<=1800)].ratio.max())
print('unloaded 500-700 imean', J[J.rpm<=700].imean.values)
resid = (I - I1s)[off]; print('noise sd A', np.nanstd(resid))
print('null p lab recipe on off', (V[off]*Ilab[off]).max(), 'null i', Ilab[off].max())
print('window dur', 3742/360)
# ch1 time constant after load off
print(J[['rpm','lab','p1s','imean','ratio','spike']].round(4).to_string())
# null P: what does the lab recipe give on the off stretch -- with V*I where V is ~20 V bus? check V in off
print('V in off', V[off].min(), V[off].max(), 'Ilab mean off', Ilab[off].mean())
# July P1s at rig Ra40/Ra80 ratio
