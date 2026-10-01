#!/usr/bin/env python3
"""
verify_july.py - INDEPENDENT adversarial check of the first-pass decode of the
Jeong-lab 27 Jul 2026 DAQ export (build/daq_july/FINDINGS.md, claims C1..C9).

Written without importing or reading build/daq_july/analyze_july.py.
Inputs (read-only):
  inputs/jeong_lab/2026-07-27_no_texture_baseline/0727windturbine.csv
  inputs/jeong_lab/2026-07-27_no_texture_baseline/Summary_Table.csv
  inputs/jeong_lab/2026-06-05_initial_reference/Summary_Table_Part1_MAX.csv
  logs/sweep_v1_Ra{20,40,80}_summary.csv   (rig, for C8 only)
Outputs (this directory):
  verify_numbers.json, verify_lab_windows.csv, verify_settings.csv,
  verify_plateaus.csv, verify_power_vs_rig.csv, verify_log.txt,
  verify_segmentation.png, verify_noise.png

Run:  python3 verify_july.py      (system python3; numpy, scipy, pandas, matplotlib)
"""
import json, os, sys, io
import numpy as np
import pandas as pd
from scipy import signal
from scipy.ndimage import median_filter, uniform_filter1d
from scipy.signal import find_peaks
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = "/Users/stepheneacuello/Projects/windtunnel-control"
RPT = f"{REPO}/reports/roughness_2026-09"
OUT = f"{RPT}/build/july_verify"
JUL = f"{RPT}/inputs/jeong_lab/2026-07-27_no_texture_baseline"
JUN = f"{RPT}/inputs/jeong_lab/2026-06-05_initial_reference"

LOG = io.StringIO()
def say(*a):
    s = " ".join(str(x) for x in a)
    print(s); LOG.write(s + "\n")

NUM = {}
def rec(key, val):
    NUM[key] = val
    return val

# ═════════════════════════════════════════════════════════════════════════
# 0. LOAD
# ═════════════════════════════════════════════════════════════════════════
df = pd.read_csv(f"{JUL}/0727windturbine.csv")
t = df.iloc[:, 0].to_numpy(float)
X = df.iloc[:, 3:8].to_numpy(float)
ch1, ch2, ch3, ch4, ch5 = X.T
N = len(t)
fs = 1.0 / np.median(np.diff(t))
Q = 5.0 / 4096                     # observed code step (checked below)
S = pd.read_csv(f"{JUL}/Summary_Table.csv")
J = pd.read_csv(f"{JUN}/Summary_Table_Part1_MAX.csv")
say(f"# verify_july.py  N={N}  fs={fs:.3f} Hz  duration={t[-1]:.3f} s")
rec("N", N); rec("fs_hz", round(fs, 4)); rec("duration_s", t[-1])

# ADC step: every channel an integer multiple of Q?
for j, x in enumerate(X.T, 1):
    u = np.unique(x)
    rec(f"ch{j}_min_step_over_Q", float(np.min(np.diff(u)) / Q))
    rec(f"ch{j}_max_dev_from_code_grid", float(np.max(np.abs(x / Q - np.round(x / Q)))))
say("ADC grid:", {k: v for k, v in NUM.items() if "step_over_Q" in k})

# Lab scaling (as claimed, C1) - used ONLY to reproduce the lab's numbers
V = 4.0 * ch1
I_lab = 2.0 * (ch2 - 2.5)
P_lab = V * I_lab

def mmean(x, n):
    """centered moving mean, length n, same length as x (edges shrink)."""
    c = np.cumsum(np.insert(x, 0, 0.0))
    h = n // 2
    lo = np.clip(np.arange(len(x)) - h, 0, len(x))
    hi = np.clip(np.arange(len(x)) - h + n, 0, len(x))
    return (c[hi] - c[lo]) / (hi - lo)

# ═════════════════════════════════════════════════════════════════════════
# 1. TACH PULSES (own detector: level crossing with refractory period)
# ═════════════════════════════════════════════════════════════════════════
LEV = -0.6
up = np.where((ch3[1:] >= LEV) & (ch3[:-1] < LEV))[0] + 1
keep = [up[0]]
for u in up[1:]:
    if u - keep[-1] >= int(0.02 * fs):
        keep.append(u)
pk = np.array(keep)
tp = t[pk]
dtp = np.diff(tp)
medI = median_filter(dtp, 9, mode="nearest")
nrev = np.maximum(1, np.round(dtp / medI)).astype(int)
skipped_idx = np.where(nrev > 1)[0]
rec("n_pulses_detected", int(len(pk)))
rec("n_intervals_with_missing_pulses", int(len(skipped_idx)))
rec("missing_pulses_total", int(np.sum(nrev - 1)))
rec("missing_pulse_times_s", [round(float(tp[i]), 2) for i in skipped_idx])
# are gaps truly empty? max ch3 inside each long gap (excluding the edges)
gapmax = []
for i in skipped_idx:
    a, b = pk[i] + int(0.12 * fs), pk[i + 1] - 3
    gapmax.append(float(ch3[a:b].max()) if b > a else np.nan)
rec("max_ch3_inside_gaps_V", round(float(np.nanmax(gapmax)), 4) if gapmax else None)
# pulse width in samples (time above -0.6 V after edge) vs rate
wid = []
for p in pk[:-1]:
    w = 0
    while p + w < N and ch3[p + w] >= LEV:
        w += 1
    wid.append(w)
wid = np.array(wid)
rate = 1 / dtp
rec("pulse_width_samples_above_-0.6V_at_<2Hz", float(np.median(wid[rate < 2])))
rec("pulse_width_samples_above_-0.6V_at_>10Hz", float(np.median(wid[rate > 10])) if np.any(rate > 10) else None)
rec("last_pulse_t_s", float(tp[-1]))
say(f"pulses {len(pk)}, intervals missing pulses {len(skipped_idx)} "
    f"(total {int(np.sum(nrev-1))}), max ch3 in gaps {NUM['max_ch3_inside_gaps_V']} V")

# instantaneous rotor rate (ch3 pulses/s, skip-corrected)
finst = nrev / dtp
tmid = (tp[1:] + tp[:-1]) / 2

# ═════════════════════════════════════════════════════════════════════════
# 2. C1  CHANNEL MAP
# ═════════════════════════════════════════════════════════════════════════
say("\n## C1 channel map")
# 2a. table values on the scaled code grid?
v_codes = S.Vdc_max / (4 * Q)
i_codes = (S.Idc_max / 2 + 2.5) / Q
rec("C1_Vdc_max_offgrid_max", float(np.max(np.abs(v_codes - np.round(v_codes)))))
rec("C1_Idc_max_offgrid_max", float(np.max(np.abs(i_codes - np.round(i_codes)))))
say("table Vdc_max/(4Q) max off-grid", NUM["C1_Vdc_max_offgrid_max"],
    "; (Idc/2+2.5)/Q max off-grid", NUM["C1_Idc_max_offgrid_max"])

# 2b. load-off event
Ib = mmean(I_lab, 90)
cand = np.where((t > 320) & (Ib < 0.1))[0]
i_off = int(cand[0])
# refine: last sample before first sample of a 0.25 s run with I below 0.1 A
t_off = float(t[i_off])
rec("t_load_off_s", round(t_off, 3))
pre = (t > t_off - 3) & (t < t_off - 1)
post = (t > t_off + 0.2) & (t < t_off + 1.2)
rec("V_before_loadoff_V", round(float(V[pre].mean()), 3))
rec("V_after_loadoff_1s_V", round(float(V[post].mean()), 3))
# zero of ch2: load-off and start-of-run (500 setting, before any current)
z_off = float(ch2[(t > t_off + 2) & (t < t[-1])].mean())
z_start = float(ch2[(t > 0.5) & (t < 20)].mean())
n_off = int(np.sum((t > t_off + 2) & (t < t[-1])))
rec("ch2_zero_loadoff_V", round(z_off, 5))
rec("ch2_zero_start_0.5-20s_V", round(z_start, 5))
rec("lab_current_offset_at_zero_mA", round(2 * (z_off - 2.5) * 1000, 2))
say(f"load off at {t_off:.2f} s; V {NUM['V_before_loadoff_V']} -> {NUM['V_after_loadoff_1s_V']} V; "
    f"ch2 zero load-off {z_off:.5f} V, start {z_start:.5f} V -> lab offset {2*(z_off-2.5)*1000:.2f} mA")

# 2c. decay after the last tach pulse: exponential fit of V
m = t > tp[-1] + 1.0
tt, vv = t[m] - t[m][0], V[m]
coef = np.polyfit(tt, np.log(np.clip(vv, 1e-3, None)), 1)
rec("V_decay_tau_after_last_pulse_s", round(-1 / coef[0], 2))
m2 = (t > t_off + 0.5) & (t < tp[-1])
coef2 = np.polyfit(t[m2] - t[m2][0], np.log(V[m2]), 1)
rec("V_decay_tau_while_rotor_turning_s", round(-1 / coef2[0], 2))
say("V decay tau after last pulse", NUM["V_decay_tau_after_last_pulse_s"],
    "s; while rotor still turning", NUM["V_decay_tau_while_rotor_turning_s"], "s")

# 2d. ch1 max, near rails?
imax = int(np.argmax(ch1))
rec("ch1_max_V", float(ch1[imax])); rec("ch1_max_code", int(round(ch1[imax] / Q)))
rec("ch1_samples_above_4.9V", int(np.sum(ch1 > 4.9)))
rec("ch1_neighbours_of_max", [round(float(x), 4) for x in ch1[imax - 3:imax + 4]])
rec("min_value_any_channel_V", float(X.min()))
say("ch1 max", ch1[imax], "code", NUM["ch1_max_code"], "neighbours", NUM["ch1_neighbours_of_max"],
    "; n>4.9 V:", NUM["ch1_samples_above_4.9V"], "; min of any channel", X.min())

# 2e. ch4, ch5 vs ch3
mm_ = t < tp[-1]
for nm, y in (("ch4", ch4), ("ch5", ch5)):
    sl, ic = np.polyfit(ch3[mm_], y[mm_], 1)
    r = np.corrcoef(ch3[mm_], y[mm_])[0, 1]
    resid = y[mm_] - (sl * ch3[mm_] + ic)
    rec(f"{nm}_vs_ch3_slope", round(float(sl), 4)); rec(f"{nm}_vs_ch3_r", round(float(r), 4))
    rec(f"{nm}_vs_ch3_resid_rms_over_signal_rms",
        round(float(resid.std() / y[mm_].std()), 3))
    # edge coincidence: upward crossings at mid level
    lvl = (y[mm_].max() + np.median(y[mm_])) / 2
    e = np.where((y[1:] >= lvl) & (y[:-1] < lvl))[0] + 1
    e = e[t[e] < tp[-1]]
    d = np.array([np.min(np.abs(pk - x)) for x in e])
    rec(f"{nm}_edges_within_2_samples_of_ch3_frac", round(float(np.mean(d <= 2)), 4))
say("ch4/ch5 vs ch3:", {k: v for k, v in NUM.items() if k.startswith(("ch4_vs", "ch5_vs", "ch4_edges", "ch5_edges"))})

# 2f. is ch3 once per revolution? order-tracked V spectrum
def order_amp(t0, t1, nper=64):
    mk = (tp >= t0) & (tp <= t1); p = tp[mk]
    d = np.diff(p)
    if len(p) < 20 or np.any(d > 1.5 * np.median(d)):
        return None
    ang = np.arange(len(p))
    ta = np.interp(np.arange(0, len(p) - 1, 1 / nper), ang, p)
    va = np.interp(ta, t, V); va = va - np.polyval(np.polyfit(ta, va, 2), ta)
    F = np.abs(np.fft.rfft(va * np.hanning(len(va))))
    o = np.fft.rfftfreq(len(va), 1 / nper)
    base = np.median(F[(o > 0.1) & (o < 6)])
    def a(x):
        i = np.argmin(np.abs(o - x)); return float(F[max(i - 1, 0):i + 2].max() / base)
    return {f"{x:.3g}": round(a(x), 1) for x in (1/3, 1/2, 2/3, 1, 2, 3, 4, 5, 6)}, len(p) - 1
orders = {}
for (a_, b_) in [(1, 22), (30, 42), (47, 58), (108, 125), (147, 160), (238, 254), (276, 292), (296, 312)]:
    r = order_amp(a_, b_)
    if r: orders[f"{a_}-{b_}s"] = {"cycles": r[1], **r[0]}
rec("C1_order_spectrum_V_rel_median", orders)
say("order-tracked V spectrum (amplitude / median, order = multiples of ch3 rate):")
for k, v in orders.items(): say("  ", k, v)

# ═════════════════════════════════════════════════════════════════════════
# 3. C2  RECIPE REPRODUCTION + UNIQUENESS
# ═════════════════════════════════════════════════════════════════════════
say("\n## C2 recipe")
L = N // 17
rec("L", L)
W0, W1 = 1870, 5611
wins = [(k * L + W0, k * L + W1) for k in range(16)]
def recipe(a, b, thr=0.1, Iarr=I_lab):
    s = slice(a, b + 1)
    cnt = int(np.sum(np.diff(ch3[s]) > thr))
    D = t[b] - t[a]
    Pw = V[s] * Iarr[s]
    return dict(rpm=60 * cnt / D, vmax=float(V[s].max()), imax=float(Iarr[s].max()),
                pmax=float(Pw.max()), cnt=cnt, D=D, i_pmax=a + int(np.argmax(Pw)))
R = [recipe(a, b) for a, b in wins]
tab = S[["Measured_RPM", "Vdc_max", "Idc_max", "Pdc_max"]].to_numpy()
mine = np.array([[r["rpm"], r["vmax"], r["imax"], r["pmax"]] for r in R])
relerr = np.abs(mine / tab - 1)
rec("C2_max_rel_err_by_col", dict(zip(["Measured_RPM", "Vdc_max", "Idc_max", "Pdc_max"],
                                      [float(x) for x in relerr.max(0)])))
say("max rel err", NUM["C2_max_rel_err_by_col"])
# threshold range that reproduces all 16 counts
implied = np.round(S.Measured_RPM.to_numpy() * np.array([r["D"] for r in R]) / 60).astype(int)
thr_ok = []
for thr in np.round(np.arange(0.01, 1.3, 0.01), 3):
    c = [int(np.sum(np.diff(ch3[a:b + 1]) > thr)) for a, b in wins]
    if np.all(np.array(c) == implied): thr_ok.append(float(thr))
rec("C2_threshold_range_reproducing_all_counts_V", [min(thr_ok), max(thr_ok)] if thr_ok else None)
# joint start shift
def all_match(sh, ln=W1 - W0):
    n = 0
    for k in range(16):
        a = k * L + W0 + sh; b = a + ln
        r = recipe(a, b)
        n += int(np.sum(np.abs(np.array([r["rpm"], r["vmax"], r["imax"], r["pmax"]]) / tab[k] - 1) < 1e-12))
    return n
shifts = [sh for sh in range(-300, 301) if all_match(sh) == 64]
rec("C2_joint_start_shifts_reproducing_64of64", shifts)
rec("C2_length_pm1_rpm_matches", [all_match(0, W1 - W0 + d) for d in (-1, 1)])
say("threshold range", NUM["C2_threshold_range_reproducing_all_counts_V"], "; joint shifts", shifts,
    "; length +-1 matches(of 64)", NUM["C2_length_pm1_rpm_matches"])

# ═════════════════════════════════════════════════════════════════════════
# 4. SEGMENTATION (C6): fan steps = rotor rises at ~constant current
# ═════════════════════════════════════════════════════════════════════════
say("\n## C6 segmentation")
g = np.arange(0.5, t_off - 0.5, 0.25)
fg = np.interp(g, tmid, finst)
fgs = uniform_filter1d(fg, 8)                     # 2 s
Ig = np.interp(g, t, mmean(I_lab, 360))
Vg = np.interp(g, t, mmean(V, 360))
h = 12                                           # +-3 s
dF = np.full_like(g, np.nan); dI = np.full_like(g, np.nan); dV = np.full_like(g, np.nan)
dF[h:-h] = fgs[2 * h:] - fgs[:-2 * h]; dI[h:-h] = Ig[2 * h:] - Ig[:-2 * h]; dV[h:-h] = Vg[2 * h:] - Vg[:-2 * h]
rel = np.nan_to_num(dF / np.maximum(fgs, 0.5))
pks, _ = find_peaks(rel, height=0.03, distance=16)
steps, ambiguous = [], []
for p in pks:
    ev = dict(t=float(g[p]), rel_rise=float(rel[p]), dI_mA=float(dI[p] * 1000), dV=float(dV[p]))
    (steps if (rel[p] > 0.08 and dV[p] > 0.8 and abs(dI[p]) < 0.02) else ambiguous).append(ev)
for ev in steps:
    p = int(np.searchsorted(g, ev["t"]))
    lo = max(0, p - 20); hi = min(len(g) - 1, p + 20)
    ev["onset"] = float(g[lo + int(np.argmin(fgs[lo:p + 1]))])
    ev["rise_end"] = float(g[p + int(np.argmax(fgs[p:hi + 1]))])
rec("C6_n_clear_fan_steps", len(steps))
rec("C6_fan_steps", [{k: round(v, 3) for k, v in e.items()} for e in steps])
rec("C6_ambiguous_rises", [{k: round(v, 3) for k, v in e.items()} for e in ambiguous])
say(f"{len(steps)} clear fan steps; ambiguous: " +
    "; ".join(f"{e['t']:.1f}s rel {e['rel_rise']*100:+.1f}% dI {e['dI_mA']:+.1f} mA" for e in ambiguous))

settings = list(range(500, 2001, 100))
bounds = [0.0] + [e["onset"] for e in steps] + [t_off]
stable_from = [0.0] + [e["rise_end"] for e in steps]
if len(steps) != 15:
    say("WARNING: expected 15 fan steps, got", len(steps))
seg = []
for j, sp in enumerate(settings):
    seg.append(dict(setting=sp, start=bounds[j], stable_from=stable_from[j], end=bounds[j + 1],
                    dwell_s=bounds[j + 1] - bounds[j]))
segdf = pd.DataFrame(seg)
dw = segdf.dwell_s.to_numpy()
rec("C6_dwell_s_by_setting", dict(zip(map(str, settings), np.round(dw, 2).tolist())))
rec("C6_dwell_range_excl_first_s", [round(float(dw[1:].min()), 2), round(float(dw[1:].max()), 2)])
say("dwells (onset to onset):", dict(zip(settings, np.round(dw, 1))))

# overlap of lab windows with actual settings
ov_rows = []
for k, (a, b) in enumerate(wins):
    ta_, tb_ = t[a], t[b]
    row = dict(lab_setting=settings[k], win_start=round(ta_, 3), win_end=round(tb_, 3))
    fr = {}
    for j, sp in enumerate(settings):
        o = max(0.0, min(tb_, bounds[j + 1]) - max(ta_, bounds[j]))
        if o > 0: fr[sp] = o / (tb_ - ta_)
    tail = max(0.0, tb_ - t_off)
    if tail > 0: fr["after_load_off"] = tail / (tb_ - ta_)
    # time within any fan-rise transition (onset..rise_end)
    tr = sum(max(0.0, min(tb_, e["rise_end"]) - max(ta_, e["onset"])) for e in steps)
    row["frac_own_setting"] = round(fr.get(settings[k], 0.0), 3)
    row["frac_other_settings"] = round(1 - fr.get(settings[k], 0.0), 3)
    row["composition"] = "; ".join(f"{kk}:{vv:.2f}" for kk, vv in fr.items())
    row["frac_in_fan_rise_transients"] = round(tr / (tb_ - ta_), 3)
    ov_rows.append(row)
ov = pd.DataFrame(ov_rows)
# the boundary between settings is ambiguous by the 7-10 s rotor spin-up: report the
# fraction of each lab window lying on the WRONG side of the boundary under two definitions
for defn, key in (("onset", "onset"), ("midpoint", "t")):
    bb = [0.0] + [e[key] for e in steps] + [t_off]
    fr_other = []
    for k, (a, b) in enumerate(wins):
        ta_, tb_ = t[a], t[b]
        own = max(0.0, min(tb_, bb[k + 1]) - max(ta_, bb[k]))
        fr_other.append(round(1 - own / (tb_ - ta_), 3))
    ov[f"frac_not_own_by_{defn}"] = fr_other
rec("C6_window_frac_not_own_setting_by_onset", dict(zip(map(str, settings), ov.frac_not_own_by_onset.tolist())))
rec("C6_window_frac_not_own_setting_by_midpoint", dict(zip(map(str, settings), ov.frac_not_own_by_midpoint.tolist())))
rec("C6_rise_duration_s_range", [round(min(e["rise_end"] - e["onset"] for e in steps), 2),
                                 round(max(e["rise_end"] - e["onset"] for e in steps), 2)])
say(ov[["lab_setting", "win_start", "win_end", "frac_own_setting", "composition", "frac_in_fan_rise_transients",
        "frac_not_own_by_onset", "frac_not_own_by_midpoint"]].to_string(index=False))

# CC test at fan steps: the fan changes V by 15-30 %; a resistor would change I by the same fraction
cc = []
for e in steps:
    pre_ = (t > e["onset"] - 2.0) & (t < e["onset"])
    post_ = (t > e["rise_end"]) & (t < e["rise_end"] + 2.0)
    I0, I1_ = I_lab[pre_].mean() - 2 * (z_off - 2.5), I_lab[post_].mean() - 2 * (z_off - 2.5)
    V0, V1_ = V[pre_].mean(), V[post_].mean()
    if I0 > 0.02:
        cc.append(((I1_ / I0 - 1) / (V1_ / V0 - 1), (V1_ / V0 - 1) * 100, (I1_ - I0) * 1000))
cc = np.array(cc)
rec("C5_fan_step_(dI/I)/(dV/V)_median_and_range", [round(float(np.median(cc[:, 0])), 3),
                                                  round(float(cc[:, 0].min()), 3), round(float(cc[:, 0].max()), 3)])
rec("C5_fan_step_dV_pct_range", [round(float(cc[:, 1].min()), 1), round(float(cc[:, 1].max()), 1)])
rec("C5_fan_step_dI_mA_range", [round(float(cc[:, 2].min()), 1), round(float(cc[:, 2].max()), 1)])
rec("C5_fan_step_n", int(len(cc)))
rec("C5_fan_step_ratios_all", [dict(ratio=round(float(r_[0]), 3), dV_pct=round(float(r_[1]), 1), dI_mA=round(float(r_[2]), 1)) for r_ in cc])
untouched = cc[np.abs(cc[:, 2]) < 6.0]
rec("C5_fan_step_ratio_range_when_load_untouched(|dI|<6mA)", [round(float(untouched[:, 0].min()), 3),
                                                             round(float(untouched[:, 0].max()), 3), int(len(untouched))])
# clean CC test: wind cut before load-off (nobody touches the load; V collapses as the rotor slows)
mw = (t > 326.5) & (t < t_off - 0.2)
nbw = mw.sum() // 90
bI_ = (I_lab[mw][:nbw * 90] - 2 * (z_off - 2.5)).reshape(nbw, 90).mean(1); bV_ = V[mw][:nbw * 90].reshape(nbw, 90).mean(1)
slw = float(np.polyfit(bV_, bI_, 1)[0])
rec("C5_windcut_326.5s_to_loadoff", dict(dI_dV_A_per_V=round(slw, 5), normalised=round(slw * bV_.mean() / bI_.mean(), 3),
                                          V_range=[round(float(bV_.min()), 2), round(float(bV_.max()), 2)],
                                          I_mean_mA=round(float(bI_.mean()) * 1000, 1), I_sd_mA=round(float(bI_.std()) * 1000, 2)))
say("wind-cut CC test:", NUM["C5_windcut_326.5s_to_loadoff"], "; untouched fan steps:", NUM["C5_fan_step_ratio_range_when_load_untouched(|dI|<6mA)"])
say("fan-step CC test (CR=1, CC=0, CP=-1):", NUM["C5_fan_step_(dI/I)/(dV/V)_median_and_range"],
    "dV%", NUM["C5_fan_step_dV_pct_range"], "dI mA", NUM["C5_fan_step_dI_mA_range"])

# ═════════════════════════════════════════════════════════════════════════
# 5. C3  CURRENT NOISE, SPIKE AT Pmax, BIAS
# ═════════════════════════════════════════════════════════════════════════
say("\n## C3 noise")
I1 = mmean(I_lab, 360)             # centered 1 s mean
V1 = mmean(V, 360)
rI = I_lab - I1
rV = V - V1
def sig(mask): return float(rI[mask].std())
m_start = (t > 1) & (t < 20)
m_off = (t > t_off + 2) & (t < t[-1] - 1)
rec("C3_sigma_I_start_mA", round(sig(m_start) * 1000, 2))
rec("C3_sigma_I_loadoff_mA", round(sig(m_off) * 1000, 2))
win_sig, win_dI, win_dP, win_Vat, win_excess = [], [], [], [], []
for k, (a, b) in enumerate(wins):
    s = slice(a, b + 1)
    win_sig.append(float(rI[s].std()))
    ip = R[k]["i_pmax"]
    win_dI.append(float(I_lab[ip] - I1[ip]))
    win_Vat.append(float(V[ip]))
    win_dP.append(float(P_lab[ip] - V[ip] * I1[ip]))
win_sig = np.array(win_sig); win_dI = np.array(win_dI); win_dP = np.array(win_dP); win_Vat = np.array(win_Vat)
sig0 = NUM["C3_sigma_I_loadoff_mA"] / 1000
rec("C3_sigma_I_by_window_mA", dict(zip(map(str, settings), np.round(win_sig * 1000, 1).tolist())))
rec("C3_sigma_I_windows_range_mA", [round(win_sig.min() * 1000, 1), round(win_sig.max() * 1000, 1)])
rec("C3_excess_rms_over_zero_current_noise_mA",
    dict(zip(map(str, settings), np.round(np.sqrt(np.clip(win_sig**2 - sig0**2, 0, None)) * 1000, 1).tolist())))
rec("C3_I_minus_1s_mean_at_Pmax_A", dict(zip(map(str, settings), np.round(win_dI, 4).tolist())))
rec("C3_I_minus_1s_mean_at_Pmax_range_A", [round(win_dI.min(), 4), round(win_dI.max(), 4)])
rec("C3_I_minus_1s_mean_at_Pmax_in_sigma0", [round(win_dI.min() / sig0, 2), round(win_dI.max() / sig0, 2)])
# dP vs V (through origin)
slope = float(np.sum(win_dP * win_Vat) / np.sum(win_Vat**2))
rec("C3_dP_over_V_fit_A", round(slope, 4))
# alternative definition: (lab Pdc_max - max of 1 s moving-mean lab-scale power in the same window) / window mean V
P1_lab = mmean(P_lab, 360)
alt = np.array([(S.Pdc_max[k] - P1_lab[a:b + 1].max()) / V[a:b + 1].mean() for k, (a, b) in enumerate(wins)])
rec("C3_alt_bias_(Pdc_max-max1s)/meanV_A_by_window", dict(zip(map(str, settings), np.round(alt, 4).tolist())))
rec("C3_alt_bias_median_A", round(float(np.median(alt)), 4))
rec("C3_dP_range_W", [round(win_dP.min(), 3), round(win_dP.max(), 3)])
# whiteness & V-I independence
ac1 = [float(np.corrcoef(rI[m][:-1], rI[m][1:])[0, 1]) for m in (m_start, m_off)]
rec("C3_lag1_autocorr_start_loadoff", [round(x, 3) for x in ac1])
rho = [float(np.corrcoef(rI[slice(a, b + 1)], rV[slice(a, b + 1)])[0, 1]) for a, b in wins]
rec("C3_corr_Iresid_Vresid_by_window_range", [round(min(rho), 3), round(max(rho), 3)])
sVw = [float(rV[slice(a, b + 1)].std()) for a, b in wins]
rec("C3_sigma_V_resid_by_window_range_V", [round(min(sVw), 3), round(max(sVw), 3)])
# what V ripple would 31 mA of REAL current produce across a ~27 ohm source? (source R estimated below)
# spectral flatness of I residual at zero current
f_, p_ = signal.welch(rI[m_off], fs, nperseg=1024)
band = (f_ > 1) & (f_ < 175)
rec("C3_spectral_flatness_I_loadoff", round(float(np.exp(np.mean(np.log(p_[band]))) / np.mean(p_[band])), 3))
f_2, p_2 = signal.welch(rI[(t > 296) & (t < 312)], fs, nperseg=1024)
rec("C3_spectral_flatness_I_1900", round(float(np.exp(np.mean(np.log(p_2[band]))) / np.mean(p_2[band])), 3))
# expected max of 3742 draws of the zero-current residual (bootstrap)
rng = np.random.default_rng(1)
pool = rI[m_off]
mx = [pool[rng.integers(0, len(pool), 3742)].max() for _ in range(2000)]
rec("C3_bootstrap_max_of_3742_zero_current_noise_A", [round(float(np.percentile(mx, q)), 4) for q in (5, 50, 95)])
say({k: v for k, v in NUM.items() if k.startswith("C3_")})

# ═════════════════════════════════════════════════════════════════════════
# 6. C4  500-700 AT ZERO CURRENT; NULL TEST
# ═════════════════════════════════════════════════════════════════════════
say("\n## C4 zero current at 500-700 and null test")
I_zc = 2.0 * (ch2 - z_off)          # zero-corrected on the lab's 2 A/V scale
P_zc = V * I_zc
c4 = {}
for k in range(3):
    a, b = wins[k]; s = slice(a, b + 1)
    m_ = float(I_zc[s].mean()); se = float(I_zc[s].std() / np.sqrt(b - a + 1))
    c4[str(settings[k])] = dict(mean_I_zc_mA=round(m_ * 1000, 2), se_mA=round(se * 1000, 2),
                                mean_V=round(float(V[s].mean()), 3),
                                lab_Pdc_max=float(S.Pdc_max[k]),
                                mean_P_zc_W=round(float(P_zc[s].mean()), 4))
# whole actual span of 500-700
for j in range(3):
    mk = (t >= segdf.start[j]) & (t < segdf.end[j])
    c4[f"span_{settings[j]}"] = dict(mean_I_zc_mA=round(float(I_zc[mk].mean()) * 1000, 2),
                                    se_mA=round(float(I_zc[mk].std() / np.sqrt(mk.sum())) * 1000, 2))
rec("C4_zero_current_check", c4)
# when did current first leave zero? (1 s mean of zero-corrected current > 5 mA for 3 s)
Izc1 = mmean(I_zc, 360)
above = Izc1 > 0.005
run = np.convolve(above.astype(int), np.ones(1080, int), "valid")
i_first = int(np.argmax(run == 1080))
rec("C4_first_time_I_zc_above_5mA_for_3s_s", round(float(t[i_first]), 2))
# null test: recipe on 3742-sample windows entirely after load-off
nulls = []
for a in range(i_off + int(0.3 * fs), N - 3742, 360):
    s = slice(a, a + 3742)
    nulls.append((float(t[a]), float(P_lab[s].max()), float(I_lab[s].max()), float(V[s].mean())))
nulls = np.array(nulls)
rec("C4_null_first_window_start_s", round(nulls[0, 0], 2))
rec("C4_null_first_window_Pdc_max_W", round(nulls[0, 1], 3))
rec("C4_null_first_window_Idc_max_A", round(nulls[0, 2], 4))
rec("C4_null_all_windows_Pdc_max_range_W", [round(nulls[:, 1].min(), 3), round(nulls[:, 1].max(), 3)])
rec("C4_null_all_windows_Idc_max_range_A", [round(nulls[:, 2].min(), 4), round(nulls[:, 2].max(), 4)])
say(json.dumps(c4)); say("first loaded", NUM["C4_first_time_I_zc_above_5mA_for_3s_s"], "s; null windows",
                         NUM["C4_null_all_windows_Pdc_max_range_W"], "W, Idc", NUM["C4_null_all_windows_Idc_max_range_A"])

# ═════════════════════════════════════════════════════════════════════════
# 7. C5  LOAD MODE, CUMULATIVE, PLATEAUS, MPP
# ═════════════════════════════════════════════════════════════════════════
say("\n## C5 load mode")
nb = int(t_off * fs) // 360
Ib1 = I_zc[:nb * 360].reshape(nb, 360).mean(1)
Vb1 = V[:nb * 360].reshape(nb, 360).mean(1)
Pb1 = P_zc[:nb * 360].reshape(nb, 360).mean(1)
tb1 = t[:nb * 360].reshape(nb, 360).mean(1)
# change flags: |I[n+1]-I[n-1]| > 6 mA
chg = np.zeros(nb, bool)
chg[1:-1] = np.abs(Ib1[2:] - Ib1[:-2]) > 0.006
# also break plateaus across every fan-step rise, so a plateau never spans two settings
for e in steps:
    chg |= (tb1 > e["onset"] - 0.5) & (tb1 < e["rise_end"] + 0.5)
# plateaus = runs of >=3 unflagged blocks
plats, i0 = [], None
for n in range(nb + 1):
    flag = chg[n] if n < nb else True
    if not flag and i0 is None: i0 = n
    if flag and i0 is not None:
        if n - i0 >= 3: plats.append((i0, n))
        i0 = None
prow = []
for (a, b) in plats:
    tm_ = tb1[a:b].mean()
    j = int(np.searchsorted(bounds, tm_, side="right") - 1)
    prow.append(dict(setting=settings[min(j, 15)], t0=round(tb1[a] - 0.5, 1), t1=round(tb1[b - 1] + 0.5, 1),
                     n_s=b - a, I_mA=round(Ib1[a:b].mean() * 1000, 1), I_sd_mA=round(Ib1[a:b].std() * 1000, 2),
                     V=round(Vb1[a:b].mean(), 3), V_sd=round(Vb1[a:b].std(), 3),
                     V_first=round(Vb1[a], 3), V_last=round(Vb1[b - 1], 3),
                     P_W=round(Pb1[a:b].mean(), 4), P_last2s_W=round(Pb1[max(a, b - 2):b].mean(), 4),
                     f_rot_hz=round(float(np.interp(tm_, tmid, finst)), 3)))
pl = pd.DataFrame(prow)
loaded = pl[pl.I_mA > 20]
cvI = (loaded.I_sd_mA / loaded.I_mA).to_numpy(); cvV = (loaded.V_sd / loaded.V).to_numpy()
rec("C5_n_plateaus", int(len(pl)))
rec("C5_loaded_plateaus_median_CV_I", round(float(np.median(cvI)), 4))
rec("C5_loaded_plateaus_median_CV_V", round(float(np.median(cvV)), 4))
# CR test: under a fixed resistor, I/V would be constant within a plateau; regress 1 s I on 1 s V within plateaus
slopes = []
for (a, b) in plats:
    if Ib1[a:b].mean() > 0.02 and (b - a) >= 5 and Vb1[a:b].std() > 0.05:
        sl = np.polyfit(Vb1[a:b], Ib1[a:b], 1)[0]
        slopes.append((sl, Ib1[a:b].mean() / Vb1[a:b].mean()))
slopes = np.array(slopes)
rec("C5_within_plateau_dI_dV_over_I_V_median", round(float(np.median(slopes[:, 0] / slopes[:, 1])), 3) if len(slopes) else None)
rec("C5_within_plateau_dI_dV_over_I_V_n", int(len(slopes)))
# cumulative / monotone
I5 = uniform_filter1d(Ib1, 5)
drops = I5[:-1] - np.maximum.accumulate(I5)[:-1]
rec("C5_max_drop_of_5s_current_below_running_max_mA", round(float(-drops.min()) * 1000, 1))
# current at the end of each setting and 3 s into the next
cum = []
for j in range(15):
    e = segdf.end[j]
    b_ = (tb1 > e - 3) & (tb1 < e); a_ = (tb1 > e) & (tb1 < e + 3)
    cum.append((settings[j], round(Ib1[b_].mean() * 1000, 1), round(Ib1[a_].mean() * 1000, 1)))
rec("C5_I_mA_end_of_setting_vs_start_of_next", cum)
# P versus I within each setting: consecutive plateaus
mpp = []
for sp, grp in pl.groupby("setting"):
    grp = grp[grp.I_mA > 5]
    if len(grp) >= 2:
        dIs = np.diff(grp.I_mA.to_numpy()); dPs = np.diff(grp.P_last2s_W.to_numpy())
        mpp.append(dict(setting=int(sp), n_levels=len(grp), I_levels_mA=grp.I_mA.tolist(),
                        P_last2s_W=grp.P_last2s_W.tolist(),
                        dP_sign_on_I_increase=["+" if (dp > 0) else "-" for di, dp in zip(dIs, dPs) if di > 0]))
    else:
        mpp.append(dict(setting=int(sp), n_levels=len(grp), I_levels_mA=grp.I_mA.tolist(),
                        P_last2s_W=grp.P_last2s_W.tolist(), dP_sign_on_I_increase=[]))
rec("C5_per_setting_levels", mpp)
# V drift at constant current (rotor sliding down torque curve?)
drift = pl[(pl.I_mA > 20) & (pl.n_s >= 5)].copy()
drift["dV_pct"] = (drift.V_last / drift.V_first - 1) * 100
rec("C5_V_drift_on_loaded_plateaus_pct_range", [round(drift.dV_pct.min(), 1), round(drift.dV_pct.max(), 1)])
say(pl.to_string(index=False))
say({k: v for k, v in NUM.items() if k.startswith("C5_") and k != "C5_per_setting_levels"})
for r_ in mpp: say("  ", r_)

# ═════════════════════════════════════════════════════════════════════════
# 8. C9  MEASURED_RPM vs TRUE REV COUNT
# ═════════════════════════════════════════════════════════════════════════
say("\n## C9 rpm")
c9 = []
d_all = np.diff(ch3)
for k, (a, b) in enumerate(wins):
    D = t[b] - t[a]
    inwin = (pk >= a) & (pk <= b)
    n_edges = int(inwin.sum())
    # missing revs inside window: intervals fully inside with nrev>1
    iv = np.where((pk[:-1] >= a) & (pk[1:] <= b))[0]
    missing = int(np.sum(nrev[iv] - 1))
    # true rpm from mean interval between first and last pulse in window (skip-corrected)
    if len(iv) > 0:
        revs = np.sum(nrev[iv]); span = tp[iv[-1] + 1] - tp[iv[0]]
        rpm_true = 60 * revs / span
    else:
        rpm_true = np.nan
    lab_cnt = R[k]["cnt"]
    # lab double counts: edges where >1 consecutive diff exceeds 0.1 V
    s = d_all[a:b] > 0.1
    runs = np.sum(s[1:] & s[:-1])
    c9.append(dict(setting=settings[k], lab_rpm=float(S.Measured_RPM[k]), lab_count=lab_cnt,
                   my_edges=n_edges, missing_in_window=missing, lab_multi_sample_edges=int(runs),
                   rpm_true_interval=round(float(rpm_true), 2),
                   err_lab_vs_true_pct=round((float(S.Measured_RPM[k]) / rpm_true - 1) * 100, 2)))
c9 = pd.DataFrame(c9)
say(c9.to_string(index=False))
rec("C9_table", c9.to_dict(orient="records"))
# the quantisation of the lab's own method: +-1 count in D ~10.39 s
rec("C9_one_count_equals_rpm", round(60 / (W1 - W0) * fs, 3))

# ═════════════════════════════════════════════════════════════════════════
# 9. C7  JUNE TABLE FINGERPRINT + JUNE-STYLE PROCESSING OF JULY
# ═════════════════════════════════════════════════════════════════════════
say("\n## C7 June fingerprint")
def grid_ok(vals, unit, tol=1e-4):
    r = vals / unit
    return np.max(np.abs(r - np.round(r)))
fp = {}
for n in (1, 2, 5, 10, 20, 25, 40, 49, 50, 51, 60, 75, 100, 150, 200):
    ov_ = grid_ok(J.Vdc_max.to_numpy(), 4 * Q / n)
    fi = (J.Idc_max.to_numpy() / (2 * Q / n)) % 1.0
    spread = float(np.max(np.minimum(np.abs(fi - fi[0]), 1 - np.abs(fi - fi[0]))))
    fp[n] = dict(V_offgrid=round(float(ov_), 6), I_frac_spread=round(spread, 6), I_frac=round(float(fi[0]), 6))
rec("C7_june_grid_test", fp)
say("n: V off-grid (units of 4Q/n), I fractional-part spread (units of 2Q/n)")
for n, v in fp.items(): say(f"  n={n:4d}  {v}")
# smallest n consistent
cons = [n for n in range(1, 401) if grid_ok(J.Vdc_max.to_numpy(), 4 * Q / n) < 1e-4 and
        np.max(np.minimum(np.abs(((J.Idc_max.to_numpy() / (2 * Q / n)) % 1) - ((J.Idc_max[0] / (2 * Q / n)) % 1)),
                          1 - np.abs(((J.Idc_max.to_numpy() / (2 * Q / n)) % 1) - ((J.Idc_max[0] / (2 * Q / n)) % 1)))) < 1e-4]
rec("C7_n_values_1_400_consistent_with_both_grids", cons[:20])
# implied zero: Idc = 2*(S*Q/50 - z)  -> z = S*Q/50 - Idc/2 ; z mod (Q/50)
n = 50
zmod = (-(J.Idc_max.to_numpy() / 2)) % (Q / n)
rec("C7_implied_zero_mod_Q_over_50_V", [round(float(zmod.min()), 9), round(float(zmod.max()), 9)])
rec("C7_Q_over_50_V", Q / 50)
# a zero of exactly 2.5 V would give zero fractional part:
rec("C7_frac_if_zero_2.5", float((2.5 * n / Q) % 1))
# June Pdc vs product of maxima
rec("C7_june_P_over_VmaxImax", [round(float(x), 3) for x in (J.Pdc_max / (J.Vdc_max * J.Idc_max))])
rec("C7_july_P_over_VmaxImax", [round(float(x), 3) for x in (S.Pdc_max / (S.Vdc_max * S.Idc_max))])
# June-style processing of July (50-sample moving average of V and I), lab window 500..700
jst = {}
for zname, z in (("z=2.5", 2.5), ("z=loadoff", z_off)):
    Ia = mmean(2 * (ch2 - z), 50); Va = mmean(V, 50)
    Pa = Va * Ia; Pm = mmean(V * 2 * (ch2 - z), 50)
    for k in range(3):
        a, b = wins[k]; s = slice(a, b + 1)
        jst[f"{settings[k]}_{zname}"] = dict(P_prod_of_avgs=round(float(Pa[s].max()), 4),
                                            P_avg_of_prod=round(float(Pm[s].max()), 4),
                                            I_max=round(float(Ia[s].max()), 4), V_max=round(float(Va[s].max()), 3))
rec("C7_june_style_on_july", jst)
# operating point at 500: June vs July (does June look unloaded like July?)
rec("C7_500_june_vs_july", dict(june_Vdc_max=float(J.Vdc_max[0]), june_Measured_RPM=float(J.Measured_RPM[0]),
                                june_Idc_max=float(J.Idc_max[0]), june_Pdc_max=float(J.Pdc_max[0]),
                                july_V50_max=jst["500_z=loadoff"]["V_max"], july_Measured_RPM=float(S.Measured_RPM[0]),
                                july_I50_max_noise_only=jst["500_z=loadoff"]["I_max"]))
say(json.dumps(jst, indent=0))

# ═════════════════════════════════════════════════════════════════════════
# 10. C8  REPROCESSED POWER vs RIG
# ═════════════════════════════════════════════════════════════════════════
say("\n## C8 power vs rig")
P1 = mmean(P_zc, 360)
def rig(tag):
    d = pd.read_csv(f"{REPO}/logs/sweep_v1_{tag}_summary.csv", comment="#")
    return d.set_index("fan_rpm_cmd")
rigs = {tg: rig(tg) for tg in ("Ra20", "Ra40", "Ra80")}
c8 = []
for j, sp in enumerate(settings):
    mk = (t >= segdf.start[j]) & (t < segdf.end[j])
    mk_st = (t >= segdf.stable_from[j]) & (t < segdf.end[j])
    a, b = wins[j]
    grp = pl[(pl.setting == sp) & (pl.I_mA > 5)]
    row = dict(setting=sp, lab_wind=float(S.Wind_Speed_ms[j]), lab_Pdc_max=float(S.Pdc_max[j]),
               lab_window_1s_max=round(float(P1[a:b + 1].max()), 4),
               lab_window_1s_max_t=round(float(t[a + int(np.argmax(P1[a:b + 1]))]), 2),
               lab_window_Pmax_sample_t=round(float(t[R[j]["i_pmax"]]), 2),
               span_1s_max=round(float(P1[mk].max()), 4),
               stable_1s_max=round(float(P1[mk_st].max()), 4) if mk_st.sum() > 360 else np.nan,
               plateau_max_mean=round(float(grp.P_W.max()), 4) if len(grp) else np.nan,
               lab_I_max_plateau_mA=round(float(grp.I_mA.max()), 1) if len(grp) else np.nan)
    for tg, d in rigs.items():
        if sp in d.index:
            # RAW argmax on every run (Ra20 has only p_max_w, which is the raw argmax)
            pc = "p_max_w" if "p_max_w" in d.columns else "p_max_raw_w"
            ic = "i_at_pmax_a" if "i_at_pmax_a" in d.columns else "i_at_pmax_raw_a"
            row[f"rig_{tg}_P"] = float(d.loc[sp, pc]); row[f"rig_{tg}_I"] = float(d.loc[sp, ic])
            row[f"rig_{tg}_wind"] = float(d.loc[sp, "wind_mps"])
    c8.append(row)
c8 = pd.DataFrame(c8)
for col in ("span_1s_max", "plateau_max_mean", "lab_window_1s_max"):
    c8[f"{col}_over_Ra20"] = (c8[col] / c8.rig_Ra20_P).round(3)
c8["lab_Pdc_max_over_Ra20"] = (c8.lab_Pdc_max / c8.rig_Ra20_P).round(3)
say(c8.to_string(index=False))
sel = c8[(c8.setting >= 900) & (c8.setting <= 1800)]
rec("C8_span_1s_max_over_Ra20_range_900_1800", [float(sel.span_1s_max_over_Ra20.min()), float(sel.span_1s_max_over_Ra20.max())])
rec("C8_plateau_mean_over_Ra20_range_900_1800", [float(sel.plateau_max_mean_over_Ra20.min()), float(sel.plateau_max_mean_over_Ra20.max())])
rec("C8_lab_window_1s_over_Ra20_range_900_1800", [float(sel.lab_window_1s_max_over_Ra20.min()), float(sel.lab_window_1s_max_over_Ra20.max())])
rec("C8_lab_Pdc_max_over_Ra20_range_900_1800", [float(sel.lab_Pdc_max_over_Ra20.min()), float(sel.lab_Pdc_max_over_Ra20.max())])
r17 = c8[c8.setting == 1700].iloc[0]
rec("C8_1700", {k: (float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in r17.items()})
# lab current vs rig current at P_max
c8["noise_share_of_lab_Pdc_max"] = ((c8.lab_Pdc_max - c8.lab_window_1s_max) / c8.lab_Pdc_max).round(3)
c8["lab_Imax_over_rig_Ra20_Impp"] = (c8.lab_I_max_plateau_mA / 1000 / c8.rig_Ra20_I).round(3)
c8["plateau_over_span1s"] = (c8.plateau_max_mean / c8.span_1s_max).round(3)
rec("C8_noise_share_of_lab_Pdc_max", dict(zip(map(str, c8.setting), c8.noise_share_of_lab_Pdc_max.tolist())))
rec("C8_lab_Imax_over_rig_Ra20_Impp", dict(zip(map(str, c8.setting), c8.lab_Imax_over_rig_Ra20_Impp.tolist())))
rec("C8_plateau_mean_over_span_1s_max", dict(zip(map(str, c8.setting), c8.plateau_over_span1s.tolist())))
say("noise share:", NUM["C8_noise_share_of_lab_Pdc_max"]); say("lab I / rig Ra20 I_pmax:", NUM["C8_lab_Imax_over_rig_Ra20_Impp"])
say("plateau mean / 1 s max:", NUM["C8_plateau_mean_over_span_1s_max"])
cmpI = c8[(c8.setting >= 800) & (c8.setting <= 1800)][["setting", "lab_I_max_plateau_mA", "rig_Ra20_I", "rig_Ra40_I", "rig_Ra80_I"]]
rec("C8_lab_Imax_vs_rig_Impp", cmpI.to_dict(orient="records"))
# near-zero-current voltage: lab 500-700 vs rig first dwell
vv = []
for j in range(3):
    mk = (t >= segdf.stable_from[j] + (0 if j == 0 else 0)) & (t < min(segdf.end[j], NUM["C4_first_time_I_zc_above_5mA_for_3s_s"]))
    pts = pd.read_csv(f"{REPO}/logs/sweep_v1_Ra20_points.csv", comment="#")
    first = pts[pts.fan_rpm == settings[j]].iloc[0]
    vv.append(dict(setting=settings[j], lab_V_zero_I_mean=round(float(V[mk].mean()), 3),
                   lab_f_rot_hz=round(float(np.mean(finst[(tmid >= t[mk][0]) & (tmid < t[mk][-1])])), 3),
                   rig_Ra20_V_at_first_dwell=float(first.volts), rig_first_dwell_I=float(first.amps)))
rec("C8_open_circuit_voltage_lab_vs_rig", vv)
say(json.dumps(vv))

# ═════════════════════════════════════════════════════════════════════════
# 11. EMF constant and constant-speed source resistance (scale sanity)
# ═════════════════════════════════════════════════════════════════════════
# EMF: zero-current 1 s blocks (start 500-700 and after load-off while turning)
fb = np.interp(tb1, tmid, finst)
z0 = (Ib1 < 0.004) & (tb1 < NUM["C4_first_time_I_zc_above_5mA_for_3s_s"])
k_emf = np.polyfit(fb[z0] * 60, Vb1[z0], 1)
rec("EMF_fit_V_per_ch3rpm_and_offset_zero_current_blocks", [round(float(k_emf[0]), 5), round(float(k_emf[1]), 3)])
# loaded: Rs = (Voc(f) - V)/I
Voc_b = np.polyval(k_emf, fb * 60)
ld = Ib1 > 0.03
Rs = (Voc_b[ld] - Vb1[ld]) / Ib1[ld]
rec("source_R_ohm_median_IQR_lab_scale", [round(float(np.percentile(Rs, q)), 1) for q in (25, 50, 75)])
say("EMF", NUM["EMF_fit_V_per_ch3rpm_and_offset_zero_current_blocks"], "source R (IQR,median)", NUM["source_R_ohm_median_IQR_lab_scale"])
# physics: tip-speed ratio implied by 1 pulse/rev at 2000 and at the '18,500 rpm' claim
Rrot = 0.1016
f2000 = float(np.median(finst[(tmid > segdf.stable_from[15]) & (tmid < t_off)]))
f1800 = float(np.median(finst[(tmid > segdf.stable_from[13]) & (tmid < segdf.end[13])]))
rec("f_ch3_2000_hz", round(f2000, 3)); rec("f_ch3_1800_hz", round(f1800, 3))

# ── sample-rate check: mains line at rest (after the rotor stops) ──
mr = (t > 345) & (t < t[-1])
hum = {}
for j, x in enumerate(X.T, 1):
    xx = (x[mr] - x[mr].mean()) * np.hanning(mr.sum())
    ff, pp = signal.periodogram(xx, fs, nfft=2**18)
    bd = (ff > 40) & (ff < 80); i_ = int(np.argmax(pp[bd]))
    hum[f"ch{j}"] = [round(float(ff[bd][i_]), 3), round(float(pp[bd][i_] / np.median(pp[bd])), 1)]
rec("mains_line_at_rest_Hz_and_peak_over_median_if_fs360", hum)
ts = df.iloc[:, 2].to_numpy()
sc = np.where(ts[1:] != ts[:-1])[0] + 1
model = np.where(np.diff(np.floor(np.arange(N) * 0.003)) > 0)[0] + 1
rec("utc_stamp_changes_equal_floor_n_x_3ms", bool(len(sc) == len(model) and np.all(sc == model)))
say("mains line at rest:", hum, "; UTC stamps = floor(n*3 ms):", NUM["utc_stamp_changes_equal_floor_n_x_3ms"])

# ── spin-down: is the bus voltage following the EMF or a capacitor decay? ──
sd = []
for tt in (330.5, 331.0, 332.0, 334.0, 336.0, 338.0, 340.0, 342.0):
    f_ = float(np.interp(tt, tmid, finst)); v_ = float(V[(t > tt - 0.25) & (t < tt + 0.25)].mean())
    sd.append(dict(t=tt, rpm=round(60 * f_, 1), V=round(v_, 3), V_over_f=round(v_ / f_, 3),
                   emf_lowspeed_fit=round(float(np.polyval(k_emf, 60 * f_)), 3)))
rec("spin_down_V_vs_EMF", sd)
say("spin-down:", sd)
# per revolution just after load-off: rotor re-accelerates and the bus charges to the EMF peak
pr = []
for a_, b_ in zip(tp[:-1], tp[1:]):
    if t_off - 0.5 < a_ < t_off + 1.6:
        mk = (t >= a_) & (t < b_)
        pr.append((round(float(a_), 3), round(60 / (b_ - a_), 1), round(float(V[mk].mean()), 2)))
rec("post_loadoff_per_rev_(t,rpm,Vmean)", pr)
ipk = int(np.argmax([p_[2] for p_ in pr]))
rec("post_loadoff_V_peak_rev", dict(t=pr[ipk][0], rpm=pr[ipk][1], V=pr[ipk][2],
                                    lowspeed_emf_at_that_rpm=round(float(np.polyval(k_emf, pr[ipk][1])), 2)))
say("post-load-off V peak:", NUM["post_loadoff_V_peak_rev"])

# ── current-scale consistency vs the rig's own V-I curves at the same fan setting ──
sc_rows = []
for tg in ("Ra20", "Ra40", "Ra80"):
    pts = pd.read_csv(f"{REPO}/logs/sweep_v1_{tg}_points.csv", comment="#")
    for _, r_ in pl[pl.I_mA > 20].iterrows():
        d_ = pts[pts.fan_rpm == r_.setting].sort_values("amps")
        if len(d_) < 3: continue
        Ir, Vr = d_.amps.to_numpy(), d_.volts.to_numpy()
        Vm = np.minimum.accumulate(Vr)
        v_at = float(np.interp(r_.I_mA / 1000, Ir, Vr)) if r_.I_mA / 1000 <= Ir.max() else np.nan
        i_at = float(np.interp(r_.V, Vm[::-1], Ir[::-1])) if Vm[-1] <= r_.V <= Vm[0] else np.nan
        sc_rows.append(dict(blade=tg, setting=int(r_.setting), I_lab_mA=r_.I_mA, V_lab=r_.V,
                            V_rig_at_I_lab=round(v_at, 3), I_rig_at_V_lab_mA=round(i_at * 1000, 1),
                            ratio_Irig_over_Ilab=round(i_at * 1000 / r_.I_mA, 3)))
scdf = pd.DataFrame(sc_rows)
scdf.to_csv(f"{OUT}/verify_scale_vs_rig.csv", index=False)
sc_sum = {}
for tg, g_ in scdf.groupby("blade"):
    x_ = g_.ratio_Irig_over_Ilab.dropna()
    sc_sum[tg] = dict(ratio_median=round(float(x_.median()), 3), ratio_min=round(float(x_.min()), 3),
                      ratio_max=round(float(x_.max()), 3),
                      ratio_median_900_1300=round(float(g_[g_.setting <= 1300].ratio_Irig_over_Ilab.median()), 3),
                      ratio_median_1400_1800=round(float(g_[g_.setting >= 1400].ratio_Irig_over_Ilab.median()), 3),
                      dV_lab_minus_rig_median=round(float((g_.V_lab - g_.V_rig_at_I_lab).median()), 3), n=int(len(x_)))
rec("scale_check_Irig_at_Vlab_over_Ilab", sc_sum)
say("scale check:", sc_sum)
rec("lambda_2000_if_1ppr", round(2 * np.pi * f2000 * Rrot / float(S.Wind_Speed_ms[15]), 3))
rec("ratio_308Hz_to_f_ch3_1800", round(308 / f1800, 2))
rec("tip_speed_mps_at_18500rpm", round(18500 / 60 * 2 * np.pi * Rrot, 1))

# ═════════════════════════════════════════════════════════════════════════
# FIGURES
# ═════════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(3, 1, figsize=(16, 10), sharex=True)
ax[0].plot(tmid, finst, ".", ms=1.5, color="C0"); ax[0].set_ylabel("ch3 rate [Hz]"); ax[0].set_ylim(0, 12.5)
ax[1].plot(tb1, Ib1 * 1000, ".-", ms=2, lw=.6, color="C1"); ax[1].set_ylabel("I zero-corr, 1 s [mA]")
ax[2].plot(tb1, Vb1, ".-", ms=2, lw=.6, color="C2"); ax[2].set_ylabel("V 1 s [V]")
for a_ in ax:
    for k, (a, b) in enumerate(wins):
        a_.axvspan(t[a], t[b], color="orange", alpha=.13)
    for e in steps:
        a_.axvspan(e["onset"], e["rise_end"], color="0.5", alpha=.25)
    for e in ambiguous:
        a_.axvline(e["t"], color="r", lw=.6, ls="--")
    a_.grid(alpha=.3)
for k, (a, b) in enumerate(wins):
    ax[0].text(t[a], 11.8, str(settings[k]), fontsize=7)
ax[2].set_xlabel("time [s]  (orange = lab windows; grey = detected fan-step rises; red dashed = ambiguous rises)")
plt.tight_layout(); plt.savefig(f"{OUT}/verify_segmentation.png", dpi=90); plt.close()

fig, ax = plt.subplots(1, 2, figsize=(14, 4.5))
ax[0].plot(settings, win_sig * 1000, "o-", label="I residual sd in lab window")
ax[0].axhline(sig0 * 1000, color="k", ls="--", label="zero current (load off)")
ax[0].set_xlabel("lab setting"); ax[0].set_ylabel("mA"); ax[0].legend(); ax[0].grid(alpha=.3)
ax[1].plot(win_Vat, win_dP, "o", label="Pdc_max - V*I_1s at that sample")
xx = np.linspace(0, win_Vat.max() * 1.05, 10); ax[1].plot(xx, slope * xx, "k--", label=f"{slope:.3f} A x V")
ax[1].set_xlabel("V at Pdc_max sample"); ax[1].set_ylabel("W"); ax[1].legend(); ax[1].grid(alpha=.3)
plt.tight_layout(); plt.savefig(f"{OUT}/verify_noise.png", dpi=90); plt.close()

# ═════════════════════════════════════════════════════════════════════════
# WRITE
# ═════════════════════════════════════════════════════════════════════════
lw = ov.copy()
lw["lab_Pdc_max"] = S.Pdc_max; lw["recipe_Pdc_max"] = mine[:, 3]
lw["sigma_I_mA"] = np.round(win_sig * 1000, 2); lw["I_minus_1s_mean_at_Pmax_A"] = np.round(win_dI, 4)
lw["dP_at_Pmax_W"] = np.round(win_dP, 4); lw["V_at_Pmax"] = np.round(win_Vat, 3)
lw = lw.merge(c9, left_on="lab_setting", right_on="setting").drop(columns="setting")
lw.to_csv(f"{OUT}/verify_lab_windows.csv", index=False)
segdf.round(3).to_csv(f"{OUT}/verify_settings.csv", index=False)
pl.to_csv(f"{OUT}/verify_plateaus.csv", index=False)
c8.to_csv(f"{OUT}/verify_power_vs_rig.csv", index=False)

def clean(o):
    if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if isinstance(o, (np.floating,)): return float(o)
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, float) and np.isnan(o): return None
    return o
with open(f"{OUT}/verify_numbers.json", "w") as fh:
    json.dump(clean(NUM), fh, indent=1)
with open(f"{OUT}/verify_log.txt", "w") as fh:
    fh.write(LOG.getvalue())
say("\nwrote verify_numbers.json, verify_lab_windows.csv, verify_settings.csv, verify_plateaus.csv, "
    "verify_power_vs_rig.csv, verify_log.txt, verify_segmentation.png, verify_noise.png")
