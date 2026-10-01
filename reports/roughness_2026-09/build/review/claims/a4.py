import numpy as np, pandas as pd, io
from scipy import stats
L='/Users/stepheneacuello/Projects/windtunnel-control/logs/'
def rd(p):
    return pd.read_csv(io.StringIO(''.join(l for l in open(p) if not l.startswith('#'))))
T='/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/build/tables/'
H={b:pd.read_csv(T+f'thevenin_v1_{b}.csv') for b in ('Ra20','Ra40','Ra80')}
mc={}
for b in ('Ra20','Ra40','Ra80'):
    p=rd(L+f'sweep_v1_{b}_points.csv')
    g=p.groupby('fan_rpm').motor_amps
    mc[b]=g.median()
    s=rd(L+f'sweep_v1_{b}_summary.csv')
    print(b,'slip',(s.fan_rpm_actual-s.fan_rpm_cmd).tolist())
    print(b,'motor amps median',g.median().round(2).tolist())
    print(b,'motor amps unique vals', sorted(p.motor_amps.unique())[:8],'...')
m=pd.DataFrame(mc); print(m.round(2))
d=np.diff(m.Ra40.values)/100
print('dI/drpm per rpm (Ra40):',np.round(d,4))
print('implied change for 4..21 rpm at each sp, A:',np.round(d*21,3))
# pairwise diffs
print('Ra20-Ra40',(m.Ra20-m.Ra40).round(2).tolist()); print('Ra20-Ra80',(m.Ra20-m.Ra80).round(2).tolist())
# lambda estimate using July EMF line Voc = 0.03342 rpm - 0.448
for b in H:
    rpm=(H[b].v_oc+0.448)/0.03342
    lam=rpm*2*np.pi/60*0.1016/H[b].wind_mps_nominal
    print(b,'free-running rotor rpm (EMF line)',rpm.round(0).tolist()); print('   lambda_free',lam.round(3).tolist())
