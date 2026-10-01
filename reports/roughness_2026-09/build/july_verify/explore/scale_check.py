import numpy as np, pandas as pd
REPO='/Users/stepheneacuello/Projects/windtunnel-control'
pl=pd.read_csv('verify_plateaus.csv')
pl=pl[pl.I_mA>20]
rows=[]
for tag in ('Ra20','Ra40','Ra80'):
    pts=pd.read_csv(f'{REPO}/logs/sweep_v1_{tag}_points.csv',comment='#')
    for _,r in pl.iterrows():
        d=pts[pts.fan_rpm==r.setting].sort_values('amps')
        if len(d)<3: continue
        I=d.amps.to_numpy(); Vr=d.volts.to_numpy()
        il=r.I_mA/1000
        v_at=np.interp(il,I,Vr) if il<=I.max() else np.nan
        # I at lab V on monotone envelope (running min of V vs I)
        Vm=np.minimum.accumulate(Vr)
        i_at=np.interp(r.V,Vm[::-1],I[::-1]) if (r.V<=Vm[0] and r.V>=Vm[-1]) else np.nan
        rows.append(dict(blade=tag,setting=r.setting,I_lab_mA=r.I_mA,V_lab=r.V,V_rig_at_I_lab=round(v_at,3),
                         I_rig_at_V_lab_mA=round(i_at*1000,1),ratio_Irig_over_Ilab=round(i_at*1000/r.I_mA,3)))
R=pd.DataFrame(rows)
print(R.to_string(index=False))
for tag,g in R.groupby('blade'):
    x=g.ratio_Irig_over_Ilab.dropna()
    print(tag,'ratio I_rig(V_lab)/I_lab median %.3f IQR %.3f-%.3f n=%d'%(x.median(),x.quantile(.25),x.quantile(.75),len(x)),
          '| V_lab - V_rig(I_lab) median %.3f V'%((g.V_lab-g.V_rig_at_I_lab).median()))
R.to_csv('verify_scale_vs_rig.csv',index=False)
