import numpy as np, pandas as pd
raw = pd.read_csv('../../../inputs/jeong_lab/2026-07-27_no_texture_baseline/0727windturbine.csv')
print(raw.shape, list(raw.columns)); print(raw.iloc[:,8].isna().all())
t = raw.iloc[:,0].values; ch = raw.iloc[:,3:8].values
print('dt', np.median(np.diff(t)), 'fs', 1/np.median(np.diff(t)), 'dur', t[-1])
N=len(raw); L=N//17; print('N',N,'L',L)
st = pd.read_csv('../../../inputs/jeong_lab/2026-07-27_no_texture_baseline/Summary_Table.csv')
V=4*ch[:,0]; I=2*(ch[:,1]-2.5); P=V*I
rows=[]
for k in range(16):
    a=k*L+1870; b=k*L+5611
    s=slice(a,b+1)
    pk=np.argmax(P[s])+a
    # 1s mean around pk
    Imean1=I[max(0,pk-180):pk+180].mean()
    rows.append((st.Setting_RPM[k], V[s].max(), I[s].max(), P[s].max(), I[s].mean()*1000, I[pk]-Imean1, t[a], t[b], b-a+1))
df=pd.DataFrame(rows,columns=['set','Vmax','Imax','Pmax','Imean_mA','spike','t0','t1','n'])
df['relP']=df.Pmax/st.Pdc_max-1; df['relV']=df.Vmax/st.Vdc_max-1; df['relI']=df.Imax/st.Idc_max-1
pd.set_option('display.width',200); print(df)
# noise at zero current: 500-700 windows
for k in range(3):
    a=k*L+1870;b=k*L+5611
    print('win',k,'std I mA',I[a:b+1].std()*1000, 'mean', I[a:b+1].mean()*1000)
# zero
m=(t>=331.0)&(t<=341.4)
print('ch2 median 331-341.4', np.median(ch[m,1]), 'mean', ch[m,1].mean(), 'V mean', V[m].mean(), V[m].min(), V[m].max())
z=np.median(ch[m,1])
Iz=2*(ch[:,1]-z); Pz=V*Iz
k1=360
Pm=np.convolve(Pz,np.ones(k1)/k1,mode='same')
Im=np.convolve(Iz,np.ones(k1)/k1,mode='same')
for k in range(16):
    a=k*L+1870;b=k*L+5611
    print(st.Setting_RPM[k], round(Pm[a:b+1].max(),4), round(Iz[a:b+1].mean()*1000,1), round(I[a:b+1].mean()*1000,1))
# null window: recipe on stretch with no current
m2 = (t>=331.0)&(t<=341.4)
print('null recipe Pmax', P[m2].max(), 'Imax', I[m2].max(), 'n', m2.sum())
np.save('P.npy',P)
