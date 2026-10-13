"""Recompute every number quoted in TEAM_SUMMARY.md from the merged tables and the report build.

Written 13 Oct 2026 for the adversarial review of TEAM_SUMMARY.md and RESULTS.md. It shares no
code with the analysis or verify scripts. Each line prints the quoted value, the value
recomputed here and OK (equal after rounding to the quoted precision) or CHECK. Rerun it after
the tables in data/ are refreshed: any CHECK line is a number to re-read in TEAM_SUMMARY.md.

Inputs (read only): data/section_polars.csv, data/stage2_polars.csv, data/rotor_static.csv,
data/rotor_cp.csv; reports/roughness_2026-09/build/numbers.json, build/derived/comparisons.csv,
build/derived/rotor_by_wind_speed.csv, build/derived/surface_roughness.csv,
build/derived/run_summary.csv, build/tacho/numbers.tex and
build/tacho/derived/rotor_speed_by_dwell.csv. Writes nothing.

    nice -n 10 python3 cfd/analysis/2026-10-13/src/team_summary_check.py
"""
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parents[1]                 # cfd/analysis/2026-10-13
REPO = HERE.parents[2]
BUILD = REPO / "reports" / "roughness_2026-09" / "build"

S1 = pd.read_csv(HERE / "data" / "section_polars.csv")
S2 = pd.read_csv(HERE / "data" / "stage2_polars.csv")
RS = pd.read_csv(HERE / "data" / "rotor_static.csv")
RC = pd.read_csv(HERE / "data" / "rotor_cp.csv")
NUM = json.loads((BUILD / "numbers.json").read_text())
COMP = pd.read_csv(BUILD / "derived" / "comparisons.csv")
BYU = pd.read_csv(BUILD / "derived" / "rotor_by_wind_speed.csv")
SURF = pd.read_csv(BUILD / "derived" / "surface_roughness.csv")
DWELL = pd.read_csv(BUILD / "tacho" / "derived" / "rotor_speed_by_dwell.csv")
RUNS = pd.read_csv(BUILD / "derived" / "run_summary.csv")

n_bad = 0


def show(label, quoted, value, nd=None):
    """Print one check. quoted: the text in TEAM_SUMMARY.md; value: number or tuple of numbers."""
    global n_bad
    vals = value if isinstance(value, (tuple, list)) else (value,)
    qs = [q.strip() for q in str(quoted).replace(" to ", "|").replace("–", "|").replace(",", "|")
          .replace("/", "|").split("|")]
    ok = True
    if nd is not None and len(qs) == len(vals):
        for q, v in zip(qs, vals):
            try:
                ok &= abs(float(q.replace("+", "").replace("−", "-")) - round(float(v), nd)) < 0.6 * 10 ** -nd
            except ValueError:
                ok = False
    elif nd is not None:
        ok = False
    txt = ", ".join(f"{float(v):.{(nd if nd is not None else 4) + 1}f}" for v in vals)
    flag = "OK   " if (nd is None or ok) else "CHECK"
    n_bad += flag == "CHECK"
    print(f"{flag} {label:62s} quoted {quoted:>22s} | recomputed {txt}")


def pct(a, b):
    return 100 * (a - b) / b


# ------------------------------------------------------------------------------ case counts
print("== case counts")
show("cases: section / stage 2 / static / rotating", "51/43/16/40",
     (len(S1), len(S2), len(RS), len(RC)), 0)
show("cases in all", "150", len(S1) + len(S2) + len(RS) + len(RC), 0)
mac = sum((d.ran_on == "mac").sum() for d in (S1, S2, RS, RC))
show("cases run on the Mac", "10", mac, 0)
show("stage 2: wall function / texture", "27/16", ((S2.wall == "wf").sum(), (S2.wall == "tex").sum()), 0)

# ------------------------------------------------------------------------------ Stage 1 health
print("== Stage 1 health (proxy u_Co/U = maxCo dx_corner / (dt U) > 5)")
DX = {"coarse": 64e-6, "medium": 45e-6, "fine": 32e-6}       # cfd/section2d/README.md section 2
S1["proxy"] = S1.maxCo * S1.level.map(DX) / (S1.dt_mean_s * S1.U_ms)
S1["flag"] = S1.proxy > 5
fl, hl = S1[S1.flag], S1[~S1.flag]
show("flagged / healthy", "23/28", (len(fl), len(hl)), 0)
show("flagged that are medium mesh at maxCo 5 / all such runs", "23/39",
     (((fl.level == "medium") & (fl.maxCo == 5)).sum(), ((S1.level == "medium") & (S1.maxCo == 5)).sum()), 0)
m5_180 = S1[(S1.level == "medium") & (S1.maxCo == 5) & (S1.alpha_deg == 180)]
show("alpha-180 medium maxCo-5 runs flagged / all", "8/8", (m5_180.flag.sum(), len(m5_180)), 0)
show("flagged runs with negative mean drag", "9", (fl.Cd_mean < 0).sum(), 0)
sym = (fl.Cd_mean < 0) | (fl.Cd_std > fl.Cd_mean.abs()) | (fl.Cl_mean.abs() > 3) | (fl.yplus_max_mean > 2)
force = (fl.Cd_mean < 0) | (fl.Cd_std > fl.Cd_mean.abs()) | (fl.Cl_mean.abs() > 3)
show("flagged runs with >= 1 further symptom (incl. y+ > 2)", "23", sym.sum(), 0)
show("flagged runs with a force symptom (Cd<0, std>|mean|, |Cl|>3)", "21", force.sum(), 0)
print("      flagged with only the y+ symptom:", list(fl[~force].name))
med5_ok = hl[(hl.level == "medium") & (hl.maxCo == 5)]
dtc = lambda d: d.dt_mean_s * d.U_ms / 0.048
show("flagged dt shorter than healthy medium-maxCo-5 median by (x)", "1.9–9.6",
     (dtc(med5_ok).median() / dtc(fl).max(), dtc(med5_ok).median() / dtc(fl).min()), 1)
vshare = 100 * hl.Cd_viscous_mean / hl.Cd_mean
show("pressure share of Cd in healthy runs, minimum (%)", "98.5", 100 - vshare.max(), 1)

# ------------------------------------------------------------------------------ alpha-0 states
print("== Stage 1, alpha 0")
a0 = hl[hl.alpha_deg == 0]
hi, lo = a0[a0.Cd_mean > 2.5], a0[a0.Cd_mean <= 2.5]
show("high-drag state Cd range (n 7)", "2.97–3.22", (hi.Cd_mean.min(), hi.Cd_mean.max()), 2)
show("low-drag state Cd range (n 5)", "1.75–2.01", (lo.Cd_mean.min(), lo.Cd_mean.max()), 2)
pair = {}
for lev in ("coarse", "medium"):
    g = S1[(S1.alpha_deg == 0) & (S1.U_ms == 23) & (S1.model == "SST") & (S1.level == lev)]
    c5, c25 = g[g.maxCo == 5].iloc[0], g[g.maxCo == 2.5].iloc[0]
    pair[lev] = pct(c25.Cd_mean, c5.Cd_mean)
    print(f"      {lev}: maxCo 5 on {c5.ran_on}, maxCo 2.5 on {c25.ran_on}")
show("maxCo 5 -> 2.5, coarse / medium (%)", "−43/−45", (pair["coarse"], pair["medium"]), 0)
w0 = 48.763                                                  # frontal width at 0 and 180 (mm)
show("shell value 2.3 on c_ref (lies between the states)", "2.34", 2.3 * w0 / 48.0, 2)

print("== Stage 1 grid (SST, 23 m/s, maxCo 2.5)")
for a, q in ((0, "9.0"), (180, "11.5")):
    g = S1[(S1.alpha_deg == a) & (S1.U_ms == 23) & (S1.model == "SST") & (S1.maxCo == 2.5)].set_index("level")
    show(f"alpha {a}: spread of coarse/medium/fine as % of fine", q,
         100 * (g.Cd_mean.max() - g.Cd_mean.min()) / g.Cd_mean["fine"], 1)
g = S1[(S1.alpha_deg == 180) & (S1.U_ms == 23) & (S1.model == "SST") & (S1.maxCo == 2.5)]
show("alpha 180 Cd range, maxCo 2.5 (3 meshes)", "1.48–1.67", (g.Cd_mean.min(), g.Cd_mean.max()), 2)
show("... on the frontal width, above the shell value 1.2 (%)", "21–37",
     (pct(g.Cd_mean.min() * 48 / w0, 1.2), pct(g.Cd_mean.max() * 48 / w0, 1.2)), 0)

# ------------------------------------------------------------------------------ wall functions
print("== Stage 2, rough wall functions, 23 m/s")
wf = S2[(S2.wall == "wf") & (S2.U_ms == 23)]
w180 = wf[wf.alpha_deg == 180].set_index("Ks_um")
w0c = wf[(wf.alpha_deg == 0) & (wf.maxCo == 2.5)].set_index("Ks_um")
ch180, z180 = [], []
for ks in (100, 200, 400):
    d = w180.Cd_mean[ks] - w180.Cd_mean[0]
    ch180.append(100 * d / w180.Cd_mean[0])
    z180.append(d / (abs(w180.Cd_drift[ks]) + abs(w180.Cd_drift[0])))
show("alpha 180 Cd change at Ks 100/200/400 (%)", "1.1/2.4/5.8", ch180, 1)
show("... in units of the drift-rule noise (min, max)", "33–153", (min(z180), max(z180)), 0)
print(f"      alpha 180 Ks 0 ran on {w180.ran_on[0]}, the others on {set(w180.ran_on[[50, 100, 200, 400]])}")
D = w0c.Cd_mean - w180.Cd_mean
show("D = Cd(0, maxCo 2.5) - Cd(180, maxCo 5): change at Ks 400 (%)", "−19.3", pct(D[400], D[0]), 1)
share = (w0c.Cd_mean[0] - w0c.Cd_mean[400]) / (D[0] - D[400])
show("share of that change from the alpha-0 fall (%)", "66", 100 * share, 0)
z0 = (w0c.Cd_mean[0] - w0c.Cd_mean[400]) / (abs(w0c.Cd_drift[0]) + abs(w0c.Cd_drift[400]))
show("alpha-0 fall at Ks 400 in units of its noise", "1.2", z0, 1)


def lam0(c0, c180):
    k = math.sqrt(c0 / c180)
    return (k - 1) / (k + 1)


show("two-position zero-drive lambda, Ks 0 / Ks 400", "0.158/0.129",
     (lam0(w0c.Cd_mean[0], w180.Cd_mean[0]), lam0(w0c.Cd_mean[400], w180.Cd_mean[400])), 3)

# ------------------------------------------------------------------------------ texture
print("== Stage 2, resolved texture, 23 m/s, maxCo 5")
tx = S2[S2.wall == "tex"].set_index(["model", "alpha_deg", "tex_t_mm"]).sort_index()
r = tx.loc[("SST", 180)]
show("SST alpha 180 Cd change at t 0.10 / 0.20 (%)", "7.1/13.7",
     (pct(r.Cd_mean[0.1], r.Cd_mean[0.0]), pct(r.Cd_mean[0.2], r.Cd_mean[0.0])), 1)
chg, noise = [], []
for a in (0, 180):
    r = tx.loc[("LM", a)]
    for t in (0.05, 0.1, 0.2):
        chg.append(pct(r.Cd_mean[t], r.Cd_mean[0.0]))
        noise.append(100 * (abs(r.Cd_drift[t]) + abs(r.Cd_drift[0.0])) / r.Cd_mean[0.0])
show("LM Cd changes, all t and both angles (min, max, %)", "−2.8 to +2.6", (min(chg), max(chg)), 1)
show("LM drift-rule noise as % of Cd (min, max)", "4.5–8.4", (min(noise), max(noise)), 1)
d_sst = tx.loc[("SST", 0)].Cd_mean[0.0] - tx.loc[("SST", 180)].Cd_mean[0.0]
d_lm = tx.loc[("LM", 0)].Cd_mean[0.0] - tx.loc[("LM", 180)].Cd_mean[0.0]
nz = sum(abs(tx.loc[(m, a)].Cd_drift[0.0]) for m in ("SST", "LM") for a in (0, 180))
show("D(SST) - D(LM) on the t 0 mesh, % of D(LM)", "+18.6", 100 * (d_sst - d_lm) / d_lm, 1)
show("... difference in Cd", "0.1155", d_sst - d_lm, 4)
show("... its drift-rule noise in Cd", "0.162", nz, 3)
dt0 = S2[(S2.wall == "tex") & (S2.alpha_deg == 0)].dt_mean_s
dt180 = S2[(S2.wall == "tex") & (S2.alpha_deg == 180)].dt_mean_s
show("texture time step alpha 180 / alpha 0 (us)", "1.50–1.57/2.38–2.70",
     (1e6 * dt180.min(), 1e6 * dt180.max(), 1e6 * dt0.min(), 1e6 * dt0.max()), 2)
rat = []
for key, g in hl.groupby(["level", "model", "maxCo", "U_ms", "Tu_body_pct"]):
    if {0, 180} <= set(g.alpha_deg):
        rat.append(g[g.alpha_deg == 180].dt_mean_s.iloc[0] / g[g.alpha_deg == 0].dt_mean_s.iloc[0])
show("healthy Stage 1 pairs: dt(alpha 180) / dt(alpha 0)", "0.97–1.26", (min(rat), max(rat)), 2)
show("stage 2: runs with Cd < 0, Cd_std > |Cd| or |Cl| > 3", "0",
     ((S2.Cd_mean < 0) | (S2.Cd_std > S2.Cd_mean.abs()) | (S2.Cl_mean.abs() > 3)).sum(), 0)
show("stage 2 texture: max Cd_std / Cd (%), max y+ (blade max)", "3/1.04",
     (100 * (S2[S2.wall == "tex"].Cd_std / S2[S2.wall == "tex"].Cd_mean).max(),
      S2[S2.wall == "tex"].yplus_blade_max.max()), None)

# ------------------------------------------------------------------------------ quasi-steady leverage
print("== two-position model: section change for each measured gain at lambda 0.125")
lam = 0.125
for name, c0, c180 in (("CFD wall function Ks 0", w0c.Cd_mean[0], w180.Cd_mean[0]), ("shells", 2.3, 1.2)):
    N = c0 * (1 - lam) ** 2 - c180 * (1 + lam) ** 2
    for g in (0.128, 0.162):
        d0 = 100 * g * N / (c0 * (1 - lam) ** 2)
        d180 = -100 * g * N / (c180 * (1 + lam) ** 2)
        print(f"      {name}: gain {100 * g:.1f} %: Cd(0) {d0:+.2f} % or Cd(180) {d180:+.2f} %")
print("      quoted: 'about 2 %' (1.6-2.6 % in magnitude)")

# ------------------------------------------------------------------------------ rotor
print("== Stage 3, rotor")
st = RS[RS.hypothesis == "A"].sort_values("theta_deg")
m = st.CQ_mean.mean()
sem = math.sqrt((st.CQ_sem ** 2).sum()) / len(st)
show("A static theta-mean, reversed sense", "+0.064", -m, 3)
show("... in time-averaging SEM", "41", -m / sem, 0)
sub = (st[st.theta_deg % 30 == 0].CQ_mean.mean(), st[st.theta_deg % 30 == 15].CQ_mean.mean())
show("... the two interleaved 30-degree subsets (reversed sense)", "0.059/0.069", (-sub[0], -sub[1]), 3)
stB = RS[RS.hypothesis == "B"]
show("B static theta-mean, drag-rule sense", "0.018", stB.CQ_mean.mean(), 3)
show("... in time-averaging SEM", "3.5", stB.CQ_mean.mean() / (math.sqrt((stB.CQ_sem ** 2).sum()) / len(stB)), 1)
subB = (stB[stB.theta_deg % 30 == 0].CQ_mean.mean(), stB[stB.theta_deg % 30 == 15].CQ_mean.mean())
show("... the two interleaved 30-degree subsets", "0.052/−0.015", subB, 3)

prod = RC[RC.maxCo == 4]


def sig_rev(h, U):
    d = prod[(prod.hypothesis == h) & (prod.U_ms == U)].CQ_drift_last_two_rev
    return math.sqrt((d ** 2).mean() / 2)


def zero_cross(h, U, sense):
    g = prod[(prod.hypothesis == h) & (prod.U_ms == U) & (prod.sense == sense)].sort_values("lam")
    s = sig_rev(h, U)
    x, y = g.lam.to_numpy(), g.CQ_mean.to_numpy()
    u = s / np.sqrt(g.n_avg_rev.to_numpy())
    for i in range(len(x) - 1):
        if y[i] > 0 >= y[i + 1]:
            l0 = x[i] + (x[i + 1] - x[i]) * y[i] / (y[i] - y[i + 1])
            dl = x[i + 1] - x[i]
            den = (y[i] - y[i + 1]) ** 2
            ul = math.hypot(dl * (-y[i + 1]) / den * u[i], dl * y[i] / den * u[i + 1])
            return l0, 2 * ul
    return None, None


l23, u23 = zero_cross("A", 23, "CCW")
l38, u38 = zero_cross("A", 38, "CCW")
show("A reversed zero-torque lambda at 23 m/s, +- 2u", "0.159/0.008", (l23, u23), 3)
show("A reversed zero-torque lambda at 38 m/s, +- 2u", "0.156/0.033", (l38, u38), 3)
dw = DWELL[(DWELL.rotor == "Plain") & (DWELL.speed_ok)]
ll = dw.groupby(["fan_rpm_cmd", "run"]).tip_speed_ratio.max()
show("rig light-load lambda, Plain, 23.03 m/s, runs 1/2", "0.160/0.158", (ll[1100][1], ll[1100][2]), 3)
show("rig light-load lambda, Plain, 37.95 m/s (both runs)", "0.207", ll[1800].max(), 3)
show("shortfall at 38 m/s", "0.051", ll[1800].min() - l38, 3)
cq10 = prod[(prod.hypothesis == "A") & (prod.U_ms == 23) & (prod.sense == "CCW") & (prod.lam == 0.1)].CQ_mean.iloc[0]
show("implied dC_Q, 12.8 % and 16.2 % of C_Q(A rev, lambda 0.10, 23)", "0.0020/0.0026",
     (0.128 * cq10, 0.162 * cq10), 4)
s23 = sig_rev("A", 23)
show("2u of a rough-minus-smooth difference of 3-rev means", "0.0096", 2 * math.sqrt(2) * s23 / math.sqrt(3), 4)
co2 = RC[RC.maxCo == 2]
dts = []
for sense in ("CW", "CCW"):
    a = prod[(prod.hypothesis == "A") & (prod.U_ms == 23) & (prod.lam == 0.15) & (prod.sense == sense)]
    b = co2[co2.sense == sense]
    dts.append(abs(b.CQ_mean.iloc[0] - a.CQ_mean.iloc[0]))
show("|C_Q(maxCo 2) - C_Q(maxCo 4)| at lambda 0.15, CW / CCW", "0.005–0.007", (min(dts), max(dts)), 3)
nrev = [math.ceil((2 * math.sqrt(2) * s23 / (g * cq10)) ** 2) for g in (0.162, 0.128)]
show("averaged revolutions needed (FS 0.20, FS 0.10)", "42–66", nrev, 0)
g10 = prod[(prod.hypothesis == "A") & (prod.U_ms == 23) & (prod.lam == 0.1)]
spr = (g10.wall_time_s / g10.n_rev_done)
trans = int((g10.n_rev_done - g10.n_avg_rev).iloc[0])
hrs = [(n + trans) * s / 3600 for n in nrev for s in (spr.min(), spr.max())]
show(f"hours per run on 8 ranks, incl. {trans} start-up revs: 42 / 66 revs", "11–13/17–20",
     (hrs[0], hrs[1], hrs[2], hrs[3]), 0)

# ------------------------------------------------------------------------------ re-run cost
print("== re-run cost of the 23 flagged section cases at maxCo 2.5 (Unity, 8 ranks)")
m25 = hl[(hl.level == "medium") & (hl.maxCo == 2.5)]
show("SST medium maxCo 2.5: steps (k) and hours", "144–181/4.5–7.3",
     (m25.n_steps.min() / 1e3, m25.n_steps.max() / 1e3, m25.wall_time_s.min() / 3600,
      m25.wall_time_s.max() / 3600), 0)
lm5 = hl[(hl.model == "LM") & (hl.level == "medium") & (hl.maxCo == 5) & (hl.ran_on == "unity")]
sst = S1[(S1.model == "SST") & (S1.level == "medium") & (S1.U_ms == 23) & (S1.alpha_deg.isin([0, 90]))]
ratio = [sst[(sst.alpha_deg == a) & (sst.maxCo == 2.5)].n_steps.iloc[0] /
         sst[(sst.alpha_deg == a) & (sst.maxCo == 5)].n_steps.iloc[0] for a in (0, 90)]
show("SST medium steps ratio maxCo 2.5 / 5 (alpha 0, 90)", "1.6–1.8", (min(ratio), max(ratio)), 1)
show("healthy LM medium maxCo-5 hours on Unity (min, max)", "2.7–6.2",
     (lm5.wall_time_s.min() / 3600, lm5.wall_time_s.max() / 3600), 1)
show("LM at maxCo 2.5, estimated hours (x the step ratio)", "4–11",
     (lm5.wall_time_s.min() / 3600 * min(ratio), lm5.wall_time_s.max() / 3600 * max(ratio)), 0)

# ------------------------------------------------------------------------------ rig numbers
print("== wind tunnel (report build)")
cp = COMP[COMP.relative_to == "Plain"].set_index("rotor")
for rot, q in (("FS 0.05", "1.8/−0.6/4.2"), ("FS 0.10", "12.8/10.1/15.5"), ("FS 0.20", "16.2/13.5/19.0")):
    r = cp.loc[rot]
    show(f"peak power change {rot} [Tukey 95 %]", q, (r.change_pct, r.tukey95_lo_pct, r.tukey95_hi_pct), 1)
for rot, q in (("FS 0.10", "6.6/5.1/8.1"), ("FS 0.20", "9.1/7.6/10.6")):
    r = cp.loc[rot]
    show(f"light-load rotor speed change {rot} [Tukey 95 %]", q,
         (r.rotor_rpm_change_pct, r.rotor_rpm_tukey95_lo_pct, r.rotor_rpm_tukey95_hi_pct), 1)
print("      steepest power rise (report numbers.json, midpoints of the two runs, m/s):",
      {k: NUM[k] for k in ("stepVP", "stepVA", "stepVB", "stepVC")})
ro = RUNS.sort_values("start_h")
show("steepest-rise speed per run, in run order (m/s)", "26.2/24.1/24.1/22.0/22.0/22.0/19.8/19.8",
     list(ro.steepest_rise_mps), 1)
print("      run order:", list(ro.rotor + " r" + ro.run.astype(str)),
      "| never rises with run order:", bool((np.diff(ro.steepest_rise_mps.to_numpy()) <= 1e-9).all()))
tex = (BUILD / "tacho" / "numbers.tex").read_text()
tsr = [float(re.search(r"\\newcommand\{\\tkTsr" + k + r"\}\{([0-9.]+)\}", tex).group(1)) for k in "PABC"]
show("peak-power lambda P / FS 0.05 / FS 0.10 / FS 0.20 (report)", "0.122/0.123/0.130/0.131", tsr, 3)
nominal_ra = {0.05: 0.397 * 50, 0.101: 0.397 * 101, 0.202: 0.397 * 202}
ratios = [nominal_ra[t] / SURF.set_index("fuzzy_skin_mm").Ra_lc025_um[t] for t in (0.05, 0.101, 0.202)]
show("nominal Ra (0.397 t) over measured Ra", "2–8", (min(ratios), max(ratios)), 0)
wfall = S2[S2.wall == "wf"]
show("wall-function blade-mean y+ range", "17–49", (wfall.yplus_blade_mean.min(), wfall.yplus_blade_mean.max()), 0)

# ------------------------------------------------------------------------------ sampling
print("== shedding frequencies of healthy runs (St from the tables, f = St U / c)")
peak = hl[(hl.St_peak_frac >= 0.2) & (hl.Cl_std >= 1e-3)]
for a in sorted(peak.alpha_deg.unique()):
    g = peak[peak.alpha_deg == a]
    print(f"      alpha {a:5.0f}: St {g.St.min():.3f}-{g.St.max():.3f}  -> at 38 m/s "
          f"{g.St.max() * 38 / 0.048:.0f} Hz (Nyquist {2 * g.St.max() * 38 / 0.048:.0f} Hz); "
          f"maxCo {sorted(set(g.maxCo))}")
print("      alpha with a healthy run:", sorted(hl.alpha_deg.unique()))

print(f"\n{n_bad} CHECK line(s)")
