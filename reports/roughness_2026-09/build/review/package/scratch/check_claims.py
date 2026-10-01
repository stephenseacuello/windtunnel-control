import pandas as pd, numpy as np, io, glob, os
P="/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/build/review/package/unzipped/URI_VAWT_Roughness_Data_2026-09-30/1_rig_sweeps"
def rd(f): return pd.read_csv(f, comment="#")
for r in ["Ra20","Ra40","Ra80"]:
    s=rd(glob.glob(f"{P}/*{r}*/sweep_v1_{r}_summary.csv")[0]); p=rd(glob.glob(f"{P}/*{r}*/sweep_v1_{r}_points.csv")[0])
    print("=====",r, "summary rows",len(s),"points rows",len(p))
    slip=s.fan_rpm_actual-s.fan_rpm_cmd
    print(" slip summary:",slip.min(),slip.max(), list(slip))
    vn=0.02132*s.fan_rpm_cmd-0.424
    vl=0.02132*s.fan_rpm_actual-0.424
    print(" wind_mps == cal(actual)? maxabs", (s.wind_mps-vl).abs().max(), " vs cal(cmd) maxabs", (s.wind_mps-vn).abs().max())
    rel=100*(s.wind_mps/vn-1)
    print(" summary wind vs nominal %:", rel.round(2).tolist())
    # points wind vs cal(cmd)
    pv=0.02132*p.fan_rpm-0.424
    print(" points wind == cal(cmd) maxabs", (p.wind_mps-pv).abs().max())
    # points wind vs summary wind per setpoint
    pw=p.groupby("fan_rpm").wind_mps.first()
    d=100*(1-s.set_index("fan_rpm_cmd").wind_mps/pw)
    print(" points vs summary wind diff % (points-summary)/points:", d.round(2).tolist())
    print(" limited_by:", s.limited_by.unique(), "clean:", s.clean.unique())
    n=p.groupby("fan_rpm").size()
    print(" steps match n points:", (s.set_index("fan_rpm_cmd").steps==n).all(), list(zip(s.steps, n.values)) if not (s.set_index("fan_rpm_cmd").steps==n).all() else "")
    # tracking
    print(" tracking values:", p.tracking.value_counts().to_dict(), " note nonempty:", p.note.notna().sum(), p.note.dropna().unique()[:5])
    # v_at_pmax check, i_last
    rawcol = "p_max_raw_w" if "p_max_raw_w" in s else "p_max_w"
    icol = "i_at_pmax_raw_a" if "i_at_pmax_raw_a" in s else "i_at_pmax_a"
    bad=[]; badl=[]
    for _,row in s.iterrows():
        g=p[(p.fan_rpm==row.fan_rpm_cmd)]
        gt=g[(g.tracking==1)&(g.amps>0)]
        k=gt.watts.idxmax()
        if abs(gt.watts[k]-row[rawcol])>1e-4 or abs(gt.volts[k]-row.v_at_pmax_v)>1e-4 or abs(gt.amps[k]-row[icol])>1e-4: bad.append((row.fan_rpm_cmd, gt.watts[k], row[rawcol], gt.volts[k], row.v_at_pmax_v, gt.amps[k], row[icol]))
        last=g.iloc[-1]
        if abs(last.demand_a-row.i_last_a)>1e-4 and abs(last.amps-row.i_last_a)>1e-4 : badl.append((row.fan_rpm_cmd,row.i_last_a,last.demand_a,last.amps, g.amps.max(), g.demand_a.max()))
        if abs(g.amps.max()-row.i_last_a)>1e-4: badl.append(("max",row.fan_rpm_cmd,row.i_last_a,g.amps.max(), g.demand_a.max()))
    print(" v/p/i at pmax mismatches:", bad)
    print(" i_last mismatches:", badl)
    print(" points fan_rpm_actual slip:", (p.fan_rpm_actual-p.fan_rpm).min(), (p.fan_rpm_actual-p.fan_rpm).max())
    print(" motor_amps by setpoint:", p.groupby("fan_rpm").motor_amps.median().round(2).tolist())
    print(" held vs demand maxabs:", (p.held_a-p.demand_a).abs().max(), " amps vs held maxabs:", (p.amps-p.held_a).abs().max())
    print(" watts vs v*a maxrel:", ((p.watts-p.volts*p.amps).abs()).max())
    if "t_unix" in p:
        print(" t_unix span min:", (p.t_unix.max()-p.t_unix.min())/60, " first", p.t_local.iloc[0], "last", p.t_local.iloc[-1])
        dt=np.diff(p.t_unix.values); print(" dt within ladder median:", np.median(dt))
    print(" NaNs points:", p.isna().sum()[p.isna().sum()>0].to_dict())
    print(" NaNs summary:", s.isna().sum()[s.isna().sum()>0].to_dict())
