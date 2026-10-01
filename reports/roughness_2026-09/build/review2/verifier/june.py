import numpy as np, pandas as pd
B='/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/'
jn=pd.read_csv(B+'inputs/jeong_lab/2026-06-05_initial_reference/Summary_Table_Part1_MAX.csv').set_index('Setting_RPM').Pdc_max
rig={r:pd.read_csv(B+f'build/tables/pmax_v1_{r}.csv').set_index('fan_rpm_cmd').p_raw for r in ['Ra20','Ra40','Ra80']}
s=jn.index
df=pd.DataFrame({'june':jn,'Ra20':rig['Ra20'][s],'Ra40':rig['Ra40'][s],'Ra80':rig['Ra80'][s]})
for r in ['Ra20','Ra40','Ra80']: df['vs'+r]=100*(df.june/df[r]-1)
df['band_lo']=100*(df[['Ra20','Ra40','Ra80']].min(axis=1)/df.Ra20-1)
df['band_hi']=100*(df[['Ra20','Ra40','Ra80']].max(axis=1)/df.Ra20-1)
df['inband']=(df.vsRa20>=df.band_lo)&(df.vsRa20<=df.band_hi)
print(df.round(3).to_string())
mid=(s>=800)&(s<=1700)
for r in ['Ra20','Ra40','Ra80']:
    lr=np.log(df.june/df[r])
    print(r,'all gm',round(100*np.expm1(lr.mean()),1),'mid gm',round(100*np.expm1(lr[mid].mean()),1),'mid range',round(100*np.expm1(lr[mid].min()),1),round(100*np.expm1(lr[mid].max()),1),
          'low range',round(100*np.expm1(lr[~mid].min()),1),round(100*np.expm1(lr[~mid].max()),1),'above',(lr>0).sum(),'n',len(lr))
print('in band (all):',df.inband.sum(),'of',len(df),' in band mid:',df.inband[mid].sum(),'of',mid.sum())
# Ra80 vs Ra20 over 800-1700
lr=np.log(df.Ra80/df.Ra20); print('Ra80 vs Ra20 800-1700 gm',round(100*np.expm1(lr[mid].mean()),1))
