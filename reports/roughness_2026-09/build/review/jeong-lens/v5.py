import numpy as np, pandas as pd
raw = pd.read_csv('../../../inputs/jeong_lab/2026-07-27_no_texture_baseline/0727windturbine.csv')
t = raw.iloc[:,0].values; ch = raw.iloc[:,3:8].values
V=4*ch[:,0]
m=(t>345)&(t<353)
p=np.polyfit(t[m],np.log(V[m]),1); print('tau after rotor stop', -1/p[0])
m=(t>331)&(t<341)
p=np.polyfit(t[m],np.log(V[m]),1); print('tau 331-341 (rotor spinning down)', -1/p[0])
# load-off time
I=2*(ch[:,1]-2.4963)
Im=np.convolve(I,np.ones(36)/36,'same')
i=np.where((t>320)&(Im<0.05))[0][0]; print('load off ~', t[i], 'Vmax after', V[(t>329)&(t<332)].max())
# last ch3 pulse
d=np.diff(ch[:,2]); e=np.where(d>0.1)[0]; print('last pulse t', t[e[-1]])
