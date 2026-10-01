#!/usr/bin/env python3
"""
analyze_july.py - reverse-engineer Jeong lab's 27 Jul 2026 DAQ export and
reproduce Summary_Table.csv from it.  Writes everything into this directory.

    python3 analyze_july.py

Inputs (read-only):  ../../inputs/jeong_lab/2026-07-27_no_texture_baseline/
                     ../../inputs/jeong_lab/2026-06-05_initial_reference/
                     ../../../../logs/sweep_v1_Ra{20,40,80}_summary.csv
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.ndimage import uniform_filter1d, median_filter
from scipy.signal import find_peaks

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]                      # reports/roughness_2026-09
REPO = ROOT.parents[1]                      # windtunnel-control
IN7 = ROOT / "inputs/jeong_lab/2026-07-27_no_texture_baseline"
IN6 = ROOT / "inputs/jeong_lab/2026-06-05_initial_reference"
LSB = 5 / 4096                              # 1.2207 mV, observed code spacing
FS = 360.0                                  # confirmed by 60.0 Hz mains line
OUT = {}

# ----------------------------------------------------------------- load
raw = pd.read_csv(IN7 / "0727windturbine.csv")
raw.columns = ["t", "date", "stamp", "ch1", "ch2", "ch3", "ch4", "ch5", "ev"]
t = raw.t.values
N = len(t)
ch1, ch2, ch3 = raw.ch1.values, raw.ch2.values, raw.ch3.values
lab = pd.read_csv(IN7 / "Summary_Table.csv")
june = pd.read_csv(IN6 / "Summary_Table_Part1_MAX.csv")

# ----------------------------------------------------------------- clock
# wall stamp == floor(n * 3 ms): the exporter rounded 1/360 s to 3 ms.
n = np.arange(N)
chg = np.where(raw.stamp.values[1:] != raw.stamp.values[:-1])[0] + 1
chg3 = np.where(np.floor((n[1:]) * 0.003) != np.floor((n[:-1]) * 0.003))[0] + 1
OUT["wallstamp_is_n_times_3ms"] = bool(len(chg) == len(chg3) and np.all(chg == chg3))
seg = ch4 = raw.ch4.values[t > 346]
x = (seg - seg.mean()) * np.hanning(len(seg))
X = np.abs(np.fft.rfft(x, 2**20)); f = np.fft.rfftfreq(2**20, 1.0)
k = np.argmax(X * ((f > 0.1) & (f < 0.2)))
OUT["hum_cycles_per_sample"] = float(f[k])
OUT["hum_Hz_if_360"] = float(f[k] * 360)
OUT["hum_Hz_if_333"] = float(f[k] * 1000 / 3)

# ----------------------------------------------------------------- units
V = 4.0 * ch1                       # lab: Vdc = 4 * ch1
I = 2.0 * (ch2 - 2.5)               # lab: Idc = (ch2 - 2.5 V) / 0.5 V/A
P = V * I                           # lab: instantaneous product
rest = t > 331.0                    # load disconnected at 329.6 s
Z0 = ch2[rest].mean()               # measured zero-current output
Z0_start = ch2[t < 25].mean()
Ic = 2.0 * (ch2 - Z0)               # zero-corrected current (same gain)
Pc = V * Ic
OUT["ch2_zero_after_disconnect_V"] = float(Z0)
OUT["ch2_zero_first25s_V"] = float(Z0_start)
OUT["I_offset_lab_convention_A"] = float(2 * (Z0 - 2.5))
OUT["I_noise_sigma_rest_A"] = float(I[rest].std())
OUT["I_max_rest_A_lab"] = float(I[rest].max())

# ----------------------------------------------------------------- lab windows
L = N // 17                         # 7482 samples = 20.783 s
mround = lambda v: int(np.floor(v + 0.5))          # MATLAB round (half away from 0)
Q0 = mround(0.25 * L) - 1           # 1-based 1871 -> 0-based 1870
W = mround(0.75 * L) - mround(0.25 * L) + 1        # 1871:5612 -> 3742 samples
wins = [(k * L + Q0, k * L + Q0 + W) for k in range(16)]      # [a, b)
OUT["slice_len_samples"] = L
OUT["win_offset_samples"] = Q0
OUT["win_len_samples"] = W

# ----------------------------------------------------------------- pulses
dx = np.diff(ch3)
lab_pulse_idx = np.where(dx > 0.10)[0] + 1        # lab-equivalent counter
edges = np.where((ch3[:-1] < -0.77) & (ch3[1:] >= -0.77))[0] + 1   # 1 per pulse
per = np.diff(edges).astype(float)
med = median_filter(per, size=15, mode="nearest")
mult = np.clip(np.round(per / med), 1, 4)
per_c = per / mult
t_p = t[edges[1:]]
rpm_p = 60 * FS / per_c                           # repaired, 1 pulse / rev
runs = np.split(lab_pulse_idx, np.where(np.diff(lab_pulse_idx) > 1)[0] + 1)
double_idx = np.array([r[1] for r in runs if len(r) > 1])
thr_ok = []
for thr in np.arange(0.02, 0.40, 0.005):
    idx = np.where(dx > thr)[0] + 1
    c = [np.sum((idx >= a) & (idx < b)) for a, b in wins]
    kt = np.round(lab.Measured_RPM.values * (W - 1) / FS / 60).astype(int)
    if np.all(np.array(c) == kt):
        thr_ok.append(round(float(thr), 3))
OUT["diff_threshold_range_reproducing_all_16"] = [thr_ok[0], thr_ok[-1]]
OUT["pulses_total"] = int(len(edges))
OUT["pulses_double_counted_by_diff"] = int(len(double_idx))
OUT["missed_revs_repaired"] = int((mult - 1).sum())

rpm_grid_t = np.arange(0, t[-1], 0.1)
rpm_grid = np.interp(rpm_grid_t, t_p, rpm_p, right=np.nan)
rpm_grid[rpm_grid_t > t_p[-1]] = np.nan
rpm_s = uniform_filter1d(np.nan_to_num(rpm_grid), 20)
drdt = np.gradient(rpm_s, 0.1)
rpm_at = lambda tt: np.interp(tt, t_p, rpm_p, left=np.nan, right=np.nan)

# ----------------------------------------------------------------- transitions
pk, _ = find_peaks(drdt, height=3, distance=80)   # merge humps within 8 s
pk = pk[rpm_grid_t[pk] < 326]
amp = np.array([rpm_s[min(p + 50, len(rpm_s) - 1)] - rpm_s[max(p - 50, 0)] for p in pk])
sel = np.sort(pk[np.argsort(amp)[::-1][:15]])
rej = sorted(set(pk) - set(sel))
onsets = []
for p in sel:
    q = p
    while q > 0 and drdt[q] > 0.15 * drdt[p]:
        q -= 1
    onsets.append(rpm_grid_t[q])
# fan off: first strong deceleration after the last onset
q = np.where((rpm_grid_t > onsets[-1] + 5) & (drdt < -15))[0][0]
while q > 0 and drdt[q] < -1.5:
    q -= 1
t_fan_off = rpm_grid_t[q]
t_disconnect = t[np.where((t > 329) & (uniform_filter1d(I, 36) < 0.17))[0][0]]
bounds = [0.0] + onsets + [t_fan_off]
segs = [(bounds[k], bounds[k + 1]) for k in range(16)]
OUT["transition_onsets_s"] = [round(float(o), 1) for o in onsets]
OUT["accel_events_rejected"] = [(round(float(rpm_grid_t[p]), 1),
                                 round(float(amp[list(pk).index(p)]), 1)) for p in rej]
OUT["accel_events_selected_amp_rpm"] = [round(float(amp[list(pk).index(p)]), 1) for p in sel]
OUT["t_fan_off_s"] = round(float(t_fan_off), 1)
OUT["t_load_disconnect_s"] = round(float(t_disconnect), 2)

# CC-mode test during the wind cut, before disconnect
m = (t >= t_fan_off - 1) & (t < t_disconnect - 0.05)
Vb = uniform_filter1d(V, 90)[m]; Ib = uniform_filter1d(I, 90)[m]
OUT["cc_test_dI_dV_A_per_V"] = float(np.polyfit(Vb, Ib, 1)[0])
OUT["cc_test_V_range"] = [float(Vb.min()), float(Vb.max())]
OUT["cc_test_I_mean_std"] = [float(Ib.mean()), float(Ib.std())]

# ----------------------------------------------------------------- helpers
def mov(a, w=360):
    """centred moving mean, only full windows"""
    c = np.cumsum(np.insert(a, 0, 0.0))
    return (c[w:] - c[:-w]) / w

def blocks(a, i0, i1, w=360):
    nb = (i1 - i0) // w
    return a[i0:i0 + nb * w].reshape(nb, w).mean(1)

MA50 = lambda a: uniform_filter1d(a, 50)
Vj, Ij = 4 * MA50(ch1), 2 * (MA50(ch2) - Z0)          # June-style processing
Pj = Vj * Ij

rig = {}
for ra in ["Ra20", "Ra40", "Ra80"]:
    d = pd.read_csv(REPO / f"logs/sweep_v1_{ra}_summary.csv", comment="#")
    pcol = "p_max_w" if "p_max_w" in d else "p_max_raw_w"
    icol = "i_at_pmax_a" if "i_at_pmax_a" in d else "i_at_pmax_raw_a"
    rig[ra] = d.set_index("fan_rpm_cmd")[[pcol, "wind_mps", icol, "v_at_pmax_v"]].rename(
        columns={pcol: "p", icol: "i", "v_at_pmax_v": "v"})

# ----------------------------------------------------------------- generator EMF line
# Open-circuit points only (no R involved): the zero-current start (load at 0 A,
# t < 62 s) and the 0.6 s after the load was switched off at 329.6 s.
t_blk = blocks(t, 0, N)
V_blk, I_blk = blocks(V, 0, N), blocks(Ic, 0, N)
R_blk = rpm_at(t_blk)
z = (t_blk > 1) & (t_blk < 62) & (np.abs(I_blk) < 0.006) & np.isfinite(R_blk)
oc = (t > t_disconnect + 0.55) & (t < t_disconnect + 1.35)
n_oc, v_oc = float(np.nanmean(rpm_at(t[oc][::36]))), float(V[oc].mean())
nn = np.r_[R_blk[z], n_oc]; vv = np.r_[V_blk[z], v_oc]
ww = np.r_[np.ones(z.sum()), z.sum() / 3.0]
emf = np.polyfit(nn, vv, 1, w=np.sqrt(ww))
emf_lo = np.polyfit(R_blk[z], V_blk[z], 1)
OUT["emf_line"] = dict(ke_V_per_rpm=float(emf[0]), c_V=float(emf[1]), n_zero_current_blocks=int(z.sum()),
                       rpm_range=[float(nn.min()), float(nn.max())],
                       oc_after_disconnect=dict(V=v_oc, rpm=n_oc),
                       low_speed_only_fit=[float(emf_lo[0]), float(emf_lo[1])],
                       low_speed_fit_pred_at_oc=float(np.polyval(emf_lo, n_oc)))
Voc_n = lambda rpm: np.polyval(emf, rpm)
act = (t_blk > 5) & (t_blk < t_fan_off - 1) & (I_blk > 0.03) & np.isfinite(R_blk)
Rint = (Voc_n(R_blk[act]) - V_blk[act]) / I_blk[act]
OUT["R_int_constant_speed_ohm"] = dict(median=float(np.median(Rint)),
                                       iqr=[float(np.percentile(Rint, 25)), float(np.percentile(Rint, 75))],
                                       n_blocks=int(act.sum()))
st = t < 24
OUT["start_open_circuit"] = dict(V=float(V[st].mean()), rpm=float(np.nanmean(rpm_at(t[st][::36]))),
                                 I_zc=float(Ic[st].mean()))
imx = int(np.argmax(ch1))
OUT["ch1_max"] = dict(V=float(ch1[imx]), t=float(t[imx]), neighbours=[float(v) for v in ch1[imx - 4:imx + 5]])
Jv = june.Vdc_max.values / LSB * 12.5
Ji = (june.Idc_max.values / LSB * 25) % 1
OUT["june_quantisation"] = dict(V_over_LSB_x12p5_max_frac=float(np.abs(Jv - np.round(Jv)).max()),
                                I_over_LSB_x25_frac_parts=[round(float(v), 5) for v in Ji])
Lv = lab.Vdc_max.values / LSB / 4; Li = lab.Idc_max.values / LSB / 2
OUT["july_quantisation"] = dict(V_over_4LSB_max_frac=float(np.abs(Lv - np.round(Lv)).max()),
                                I_over_2LSB_max_frac=float(np.abs(Li - np.round(Li)).max()))

# ----------------------------------------------------------------- per setting
rows, pts = [], []
for k in range(16):
    s = int(lab.Setting_RPM[k])
    a, b = wins[k]
    ta, tb = t[a], t[b - 1]
    T = t[b - 1] - t[a]
    nlab = int(np.sum((lab_pulse_idx >= a) & (lab_pulse_idx < b)))
    nclean = int(np.sum((edges >= a) & (edges < b)))
    r = dict(setting_rpm=s, wind_ms_lab=lab.Wind_Speed_ms[k])
    # detected segment
    sa, sb = segs[k]
    r.update(seg_start_s=round(sa, 1), seg_end_s=round(sb, 1), seg_dur_s=round(sb - sa, 1))
    r.update(labwin_start_s=round(ta, 3), labwin_end_s=round(tb, 3))
    ov = max(0, min(tb, sb) - max(ta, sa)) / (tb - ta)
    r["labwin_frac_inside_own_setting"] = round(ov, 3)
    # reproduction
    rep = dict(Measured_RPM=60 * nlab / T, Vdc_max=V[a:b].max(), Idc_max=I[a:b].max(),
               Pdc_max=P[a:b].max())
    for c in rep:
        r[f"lab_{c}"] = lab[c][k]
        r[f"repro_{c}"] = rep[c]
        r[f"relerr_{c}"] = (rep[c] - lab[c][k]) / lab[c][k]
    ip = a + int(np.argmax(P[a:b]))
    r["lab_Pmax_sample_t_s"] = t[ip]
    r["lab_Pmax_sample_in_setting"] = next((500 + 100 * j for j, (u, v) in enumerate(segs) if u <= t[ip] < v), -1)
    r["lab_Pmax_sample_V"] = V[ip]; r["lab_Pmax_sample_I"] = I[ip]
    r["lab_Pmax_sample_I_minus_1s_mean"] = I[ip] - Ic[max(ip - 180, 0):ip + 180].mean() - 2 * (Z0 - 2.5)
    # rpm truth
    r["pulses_lab_counter"] = nlab
    r["pulses_clean_edges"] = nclean
    r["pulses_double_counted"] = int(np.sum((double_idx >= a) & (double_idx < b)))
    mm = (t_p >= ta) & (t_p <= tb)
    r["missed_revs_in_labwin"] = int((mult[mm] - 1).sum())
    r["rotor_rpm_true_labwin_mean"] = float(np.mean(rpm_at(t[a:b:36])))
    # averaging bias inside the lab window
    P1 = mov(P[a:b]); Pc1 = mov(Pc[a:b])
    r.update(
        labwin_V_mean=V[a:b].mean(), labwin_I_mean_lab=I[a:b].mean(), labwin_I_mean_zc=Ic[a:b].mean(),
        labwin_I_max_minus_mean=I[a:b].max() - I[a:b].mean(),
        labwin_P_inst_max=P[a:b].max(), labwin_P_1s_movmax=P1.max(),
        labwin_P_1s_blockmax=blocks(P, a, b).max(), labwin_P_mean=P[a:b].mean(),
        labwin_P_1s_movmax_zc=Pc1.max(), labwin_P_mean_zc=Pc[a:b].mean(),
        labwin_P_june_style_max=Pj[a:b].max(),
        labwin_V_1s_max=mov(V[a:b]).max(), labwin_I_1s_max_zc=mov(Ic[a:b]).max(),
        labwin_P_1s_prodofmeans_max_zc=(mov(V[a:b]) * mov(Ic[a:b])).max(),
    )
    r["bias_inst_over_1s"] = r["labwin_P_inst_max"] / r["labwin_P_1s_movmax"]
    r["bias_inst_minus_1s_W"] = r["labwin_P_inst_max"] - r["labwin_P_1s_movmax"]
    r["bias_inst_minus_1s_zc_W"] = r["labwin_P_inst_max"] - r["labwin_P_1s_movmax_zc"]
    # detected segment, settled part (skip 6 s spin-up)
    ia, ib = np.searchsorted(t, sa + 6.0), np.searchsorted(t, sb)
    if k == 0:
        ia = np.searchsorted(t, 1.0)
    Pc1s = mov(Pc[ia:ib])
    tb_, Vb_, Ib_, Pb_ = blocks(t, ia, ib), blocks(V, ia, ib), blocks(Ic, ia, ib), blocks(Pc, ia, ib)
    Rb_ = rpm_at(tb_)
    for j in range(len(tb_)):
        pts.append(dict(setting_rpm=s, t_s=round(tb_[j], 2), s_into_setting=round(tb_[j] - sa, 2),
                        vdc_v=Vb_[j], idc_a_zc=Ib_[j], pdc_w_zc=Pb_[j], rotor_rpm=Rb_[j]))
    r.update(seg_V_mean=Vb_.mean(), seg_I_zc_mean=Ib_.mean(), seg_I_zc_min=Ib_.min(), seg_I_zc_max=Ib_.max(),
             seg_P_1s_movmax_zc=Pc1s.max(), seg_P_inst_max=P[ia:ib].max(),
             seg_rotor_rpm_mean=float(np.nanmean(Rb_)))
    # Thevenin: V at lowest current, EMF-line Voc, constant-speed R, fixed-wind fit
    jmin = np.argmin(Ib_)
    r["I_lowest_A"] = Ib_[jmin]
    r["voc_at_lowest_I_V"] = Vb_[jmin]
    r["rotor_rpm_at_lowest_I"] = Rb_[jmin]
    r["voc_emf_at_that_rpm_V"] = Voc_n(Rb_[jmin])
    okb = (Ib_ > 0.03) & np.isfinite(Rb_)
    r["R_int_median_ohm"] = float(np.median((Voc_n(Rb_[okb]) - Vb_[okb]) / Ib_[okb])) if okb.sum() else np.nan
    if Ib_.max() - Ib_.min() >= 0.015:
        p = np.polyfit(Ib_, Vb_, 1)
        fit = np.polyval(p, Ib_)
        r2 = 1 - np.var(Vb_ - fit) / np.var(Vb_)
        r.update(thev_voc_fit_V=p[1], thev_Rapp_ohm=-p[0], thev_r2=r2, thev_n=len(Ib_))
        r["mpp_est_W"] = p[1] ** 2 / (4 * -p[0]) if -p[0] > 0 else np.nan
        r["mpp_est_I_A"] = p[1] / (2 * -p[0]) if -p[0] > 0 else np.nan
    else:
        r.update(thev_voc_fit_V=np.nan, thev_Rapp_ohm=np.nan, thev_r2=np.nan, thev_n=len(Ib_),
                 mpp_est_W=np.nan, mpp_est_I_A=np.nan)
    # a fixed-wind fit is only physical if R_app exceeds the constant-speed R_int
    # (the rotor slows under load) and the line explains the scatter
    rint_ref = r["R_int_median_ohm"] if np.isfinite(r["R_int_median_ohm"]) else OUT["R_int_constant_speed_ohm"]["median"]
    r["thev_valid"] = int(np.isfinite(r["thev_Rapp_ohm"]) and r["thev_Rapp_ohm"] > rint_ref and r["thev_r2"] >= 0.9)
    for ra in rig:
        r[f"rig_{ra}_pmax_W"] = rig[ra].p.get(s, np.nan)
        r[f"rig_{ra}_wind_ms"] = rig[ra].wind_mps.get(s, np.nan)
        r[f"rig_{ra}_I_at_pmax_A"] = rig[ra].i.get(s, np.nan)
        r[f"rig_{ra}_V_at_pmax_V"] = rig[ra].v.get(s, np.nan)
    rows.append(r)

S = pd.DataFrame(rows)
PTS = pd.DataFrame(pts)
S.to_csv(HERE / "july_segments.csv", index=False, float_format="%.6g")
PTS.to_csv(HERE / "july_pi_points.csv", index=False, float_format="%.5g")

# ----------------------------------------------------------------- noise-only null
a0 = np.searchsorted(t, 331.0)
b0 = a0 + W
OUT["null_window_after_disconnect"] = dict(t=[float(t[a0]), float(t[b0 - 1])],
                                           V_mean=float(V[a0:b0].mean()),
                                           I_true_mean_zc=float(Ic[a0:b0].mean()),
                                           Idc_max_lab=float(I[a0:b0].max()),
                                           Pdc_max_lab=float(P[a0:b0].max()),
                                           P_1s_movmax=float(mov(P[a0:b0]).max()))

# ----------------------------------------------------------------- decimated series (36 Hz)
D = 10
nb = N // D
tt = t[:nb * D].reshape(nb, D).mean(1)
dec = pd.DataFrame(dict(
    t_s=tt,
    vdc_v=V[:nb * D].reshape(nb, D).mean(1),
    idc_a_lab=I[:nb * D].reshape(nb, D).mean(1),
    idc_a_zero_corr=Ic[:nb * D].reshape(nb, D).mean(1),
    pdc_w_lab=P[:nb * D].reshape(nb, D).mean(1),
    pdc_w_zero_corr=Pc[:nb * D].reshape(nb, D).mean(1),
    rotor_rpm=rpm_at(tt),
))
fs_ = np.full(nb, np.nan)
lw_ = np.full(nb, np.nan)
for k in range(16):
    fs_[(tt >= segs[k][0]) & (tt < segs[k][1])] = 500 + 100 * k
    lw_[(tt >= t[wins[k][0]]) & (tt <= t[wins[k][1] - 1])] = 500 + 100 * k
dec.insert(1, "fan_setting_rpm", fs_)
dec.insert(2, "lab_window_setting_rpm", lw_)
dec["load_connected"] = (tt < t_disconnect).astype(int)
dec.to_csv(HERE / "july_timeseries_decimated.csv", index=False, float_format="%.5g")

# ----------------------------------------------------------------- figures
cols = plt.cm.viridis(np.linspace(0, 0.95, 16))
fig, ax = plt.subplots(4, 1, figsize=(18, 13), sharex=True)
tb1 = blocks(t, 0, N); Rb1 = rpm_at(tb1)
series = [(Rb1, "rotor rpm (1 s, 1 ppr, repaired)"), (blocks(V, 0, N), "Vdc = 4 ch1 [V]"),
          (blocks(Ic, 0, N), "Idc zero-corr. [A]"), (blocks(Pc, 0, N), "P 1 s mean [W]")]
for axx, (y, lab_) in zip(ax, series):
    axx.plot(tb1, y, ".-", ms=3, lw=0.8, color="k")
    axx.set_ylabel(lab_); axx.grid(alpha=0.3)
    for k in range(16):
        axx.axvspan(*segs[k], color=cols[k], alpha=0.18, lw=0)
        axx.axvspan(t[wins[k][0]], t[wins[k][1] - 1], ymin=0, ymax=0.06, color="red", alpha=0.7, lw=0)
    for o in onsets:
        axx.axvline(o, color="b", lw=0.6, ls="--")
    axx.axvline(t_fan_off, color="r", lw=0.8); axx.axvline(t_disconnect, color="m", lw=0.8)
for k in range(16):
    ax[0].text(np.mean(segs[k]), 690, str(500 + 100 * k), ha="center", fontsize=8)
ax[0].set_title("Coloured bands: detected fan settings.  Red ticks at bottom: the lab's 10.39 s analysis windows "
                "(middle half of N/17 slices).  Red line: fan off; magenta: load disconnected.")
ax[-1].set_xlabel("time [s] (360 Hz time base)")
ax[-1].set_xticks(np.arange(0, 360, 10))
plt.tight_layout(); plt.savefig(HERE / "segmentation.png", dpi=72); plt.close()

fig, ax = plt.subplots(1, 2, figsize=(16, 6.5))
for k in range(16):
    d = PTS[PTS.setting_rpm == 500 + 100 * k]
    ax[0].plot(d.idc_a_zc, d.pdc_w_zc, "o", ms=3.5, color=cols[k], label=str(500 + 100 * k))
    ax[1].plot(d.idc_a_zc, d.vdc_v, "o", ms=3.5, color=cols[k])
    rr = S.iloc[k]
    if np.isfinite(rr.thev_Rapp_ohm) and rr.thev_Rapp_ohm > 0:
        ii = np.linspace(0, d.idc_a_zc.max() * 1.05, 20)
        ax[1].plot(ii, rr.thev_voc_fit_V - rr.thev_Rapp_ohm * ii, "-", color=cols[k], lw=0.8)
ax[0].set_xlabel("Idc zero-corrected [A]"); ax[0].set_ylabel("P [W], 1 s block means")
ax[1].set_xlabel("Idc zero-corrected [A]"); ax[1].set_ylabel("Vdc [V], 1 s block means")
ax[0].legend(ncol=2, fontsize=7, title="fan setting"); [a.grid(alpha=0.3) for a in ax]
ax[0].set_title("Operating points visited per setting (settled part, 1 s blocks)")
ax[1].set_title("V-I per setting with apparent fixed-wind Thevenin fits where I range >= 15 mA")
plt.tight_layout(); plt.savefig(HERE / "pi_curves.png", dpi=80); plt.close()

fig, ax = plt.subplots(1, 2, figsize=(17, 6.5))
w = S.wind_ms_lab
ax[0].plot(w, S.labwin_P_inst_max, "s-", label="lab Pdc_max (360 Hz instantaneous max)")
ax[0].plot(w, S.labwin_P_1s_movmax_zc, "o--", label="1 s moving max, zero-corrected current")
ax[0].plot(w, S.labwin_P_june_style_max, "^-", label="June-style (50-sample MA, zero-corr.) max")
ax[0].plot(w, S.seg_P_1s_movmax_zc, "d:", label="1 s max over the actual (detected) setting, zero-corr.")
for ra, mk in [("Ra20", "x"), ("Ra40", "+"), ("Ra80", "1")]:
    ax[0].plot(S[f"rig_{ra}_wind_ms"], S[f"rig_{ra}_pmax_W"], mk + "-", ms=9, lw=0.8, label=f"rig {ra} p_max (dwell-mean MPP)")
ax[0].set_xlabel("wind speed [m/s] (each source's own calibration)"); ax[0].set_ylabel("power [W]")
ax[0].legend(fontsize=7.5); ax[0].grid(alpha=0.3)
kfit = float(np.sum(S.bias_inst_minus_1s_zc_W * S.labwin_V_mean) / np.sum(S.labwin_V_mean ** 2))
OUT["bias_dP_over_V_A"] = kfit
ax[1].plot(S.labwin_V_mean, S.bias_inst_minus_1s_zc_W, "s", label="lab Pdc_max - 1 s max (zero-corr.)")
vv_ = np.linspace(0, 13, 10)
ax[1].plot(vv_, kfit * vv_, "k--", lw=0.8, label=f"dP = {kfit:.3f} A x Vdc  (~3.5 sigma_I)")
for _, rr in S.iterrows():
    ax[1].annotate(str(int(rr.setting_rpm)), (rr.labwin_V_mean, rr.bias_inst_minus_1s_zc_W), fontsize=7,
                   xytext=(3, -8), textcoords="offset points")
ax[1].set_xlabel("mean Vdc in lab window [V]"); ax[1].set_ylabel("instantaneous-max bias [W]")
ax[1].grid(alpha=0.3); ax[1].legend(fontsize=8)
ax[1].set_title("Bias of the lab's Pdc_max is current-noise x voltage")
plt.tight_layout(); plt.savefig(HERE / "averaging_bias.png", dpi=80); plt.close()

fig, ax = plt.subplots(figsize=(10, 6))
ax.plot(S.setting_rpm, S.lab_Measured_RPM, "s-", label="lab Measured_RPM (pulse count / 10.39 s)")
ax.plot(S.setting_rpm, S.rotor_rpm_true_labwin_mean, "o-", label="rotor rpm, period-based, missed pulses repaired")
ax.set_xlabel("fan setting [rpm]"); ax.set_ylabel("rotor rpm (1 pulse/rev)"); ax.grid(alpha=0.3); ax.legend()
plt.tight_layout(); plt.savefig(HERE / "rpm_check.png", dpi=80); plt.close()

# evidence figures ----------------------------------------------------------
from scipy.signal import welch, spectrogram as _spg
fig, ax = plt.subplots(5, 1, figsize=(16, 14), sharex=True)
for i, c in enumerate(["ch1", "ch2", "ch3", "ch4", "ch5"]):
    xx = raw[c].values; m_ = len(xx) // 36
    xr = xx[:m_ * 36].reshape(m_, 36); tt_ = t[:m_ * 36:36]
    ax[i].fill_between(tt_, xr.min(1), xr.max(1), color="0.8", lw=0)
    ax[i].plot(tt_, xr.mean(1), lw=0.6); ax[i].set_ylabel(c + " [V]"); ax[i].grid(alpha=0.3)
ax[-1].set_xlabel("time [s] (grey: min/max per 0.1 s; blue: 0.1 s mean)")
plt.tight_layout(); plt.savefig(HERE / "raw_channels_overview.png", dpi=80); plt.close()

fig, ax = plt.subplots(5, 3, figsize=(18, 12))
for j, (t0, w_) in enumerate([(5, 1.0), (150, 0.5), (330, 0.3)]):
    mm = (t >= t0) & (t < t0 + w_)
    for i, c in enumerate(["ch1", "ch2", "ch3", "ch4", "ch5"]):
        ax[i, j].plot(t[mm], raw[c].values[mm], ".-", ms=2, lw=0.5); ax[i, j].set_ylabel(c); ax[i, j].grid(alpha=0.3)
    ax[0, j].set_title(f"t = {t0} .. {t0 + w_} s")
plt.tight_layout(); plt.savefig(HERE / "raw_channels_zoom.png", dpi=70); plt.close()

fig, ax = plt.subplots(5, 1, figsize=(14, 14))
for i, c in enumerate(["ch1", "ch2", "ch3", "ch4", "ch5"]):
    for lab_, mm in [("rest t>346 s", t > 346), ("run 0-25 s", t < 25), ("run 300-326 s", (t > 300) & (t < 326))]:
        xx = raw[c].values[mm]; ff, pp = welch(xx - xx.mean(), fs=FS, nperseg=min(4096, len(xx)))
        ax[i].semilogy(ff, pp, lw=0.7, label=lab_)
    ax[i].axvline(60, color="k", lw=0.5, ls=":"); ax[i].set_ylabel(c); ax[i].legend(fontsize=7); ax[i].grid(alpha=0.3)
ax[-1].set_xlabel("Hz at fs = 360 (dotted: 60 Hz mains)")
plt.tight_layout(); plt.savefig(HERE / "spectra.png", dpi=70); plt.close()

fig, ax = plt.subplots(3, 1, figsize=(18, 11), sharex=True)
for a_, c in zip(ax, ["ch2", "ch1", "ch5"]):
    xx = raw[c].values
    ff, tt_, Sx = _spg(xx - xx.mean(), fs=FS, nperseg=2048, noverlap=1536)
    L10 = 10 * np.log10(Sx + 1e-15)
    a_.pcolormesh(tt_, ff, L10, shading="auto", vmin=np.percentile(L10, 5), vmax=np.percentile(L10, 99.7))
    a_.set_ylabel(c + " [Hz]")
ax[-1].set_xlabel("time [s]")
plt.tight_layout(); plt.savefig(HERE / "spectrogram.png", dpi=65); plt.close()

fig, ax = plt.subplots(4, 1, figsize=(14, 10), sharex=True)
mm = (t > 324) & (t < 336)
ax[0].plot(t[mm], V[mm], lw=0.6); ax[0].set_ylabel("Vdc [V]")
ax[1].plot(t[mm], I[mm], lw=0.4); ax[1].set_ylabel("Idc lab [A]")
ax[2].plot(t[mm], ch3[mm], lw=0.4); ax[2].set_ylabel("ch3 [V]")
mp = (t_p > 324) & (t_p < 336)
ax[3].plot(t_p[mp], 60 * FS / per[mp], ".", label="raw edge periods")
ax[3].plot(t_p[mp], rpm_p[mp], ".", ms=3, label="missed pulses repaired"); ax[3].set_ylabel("rotor rpm"); ax[3].legend()
for a_ in ax:
    a_.grid(alpha=0.3); a_.axvline(t_fan_off, color="r", lw=0.8); a_.axvline(t_disconnect, color="m", lw=0.8)
ax[-1].set_xlim(324, 336); ax[-1].set_xlabel("time [s] (red: fan off, magenta: load off)")
plt.tight_layout(); plt.savefig(HERE / "disconnect_event.png", dpi=70); plt.close()

fig, ax = plt.subplots(3, 2, figsize=(18, 10))
for j, (t0, t1) in enumerate([(55, 95), (170, 225)]):
    mm = (dec.t_s >= t0) & (dec.t_s < t1)
    for i, (c, lab_) in enumerate([("rotor_rpm", "rotor rpm"), ("vdc_v", "Vdc [V]"), ("idc_a_zero_corr", "Idc zc [A]")]):
        y = dec[c][mm].values
        ax[i, j].plot(dec.t_s[mm], y, lw=0.4, color="0.6"); ax[i, j].plot(dec.t_s[mm], uniform_filter1d(y, 36), lw=1.2)
        ax[i, j].set_ylabel(lab_); ax[i, j].grid(alpha=0.3)
        for o in onsets:
            if t0 < o < t1: ax[i, j].axvline(o, color="b", ls="--", lw=0.7)
plt.tight_layout(); plt.savefig(HERE / "zoom_load_steps.png", dpi=70); plt.close()

json.dump(OUT, open(HERE / "key_numbers.json", "w"), indent=1, default=float)
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 60)
print(json.dumps(OUT, indent=1, default=float))
print(S[["setting_rpm", "seg_start_s", "seg_end_s", "seg_dur_s", "labwin_start_s", "labwin_end_s",
         "labwin_frac_inside_own_setting"]].to_string())
print(S[[c for c in S if c.startswith("relerr")]].abs().max())
