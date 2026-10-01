"""Build every number, table and figure in the roughness report from raw data.

    python3 src/build_report.py            (from reports/roughness_2026-09)

Nothing in report/report.tex is typed by hand: numbers come from
build/numbers.tex (LaTeX macros), tables from build/tables/*.tex and figures
from build/fig/*.pdf. Re-running after a new sweep lands in ../../logs updates
all three, so the text cannot drift from the files.

New runs are picked up automatically if they carry protocol 94bed28333f7:
  sweep_v1_Ra20_repeat_*   a remount of an existing rotor -> the error bar
  sweep_v1_Ra10_*, sweep_v1_smooth_*   a new roughness level (see SPECIMENS)

Inputs are read, never written:
  ../../logs/sweep_<rotor>_{summary,points}.csv
  inputs/jeong_lab/...
"""
import json
import math
import re
import sys
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import style  # noqa: E402,F401

ROOT = HERE.parent
REPO = ROOT.parent.parent
LOGS = REPO / "logs"
BUILD = ROOT / "build"
JL = ROOT / "inputs" / "jeong_lab"
import os
if os.environ.get("ROUGHNESS_LOGS"):   # testing hook: read sweeps from elsewhere
    LOGS = Path(os.environ["ROUGHNESS_LOGS"])
PACKAGED = (ROOT / "1_rig_sweeps").is_dir()
if PACKAGED:            # running from the unzipped data package (6_code/)
    LOGS = ROOT / "1_rig_sweeps"
    JL = ROOT / "2_jeong_lab"
    BUILD = ROOT / "rebuilt"
FIG = BUILD / "fig"
TAB = BUILD / "tables"
for d in (FIG, TAB):
    d.mkdir(parents=True, exist_ok=True)

PROTOCOL = "94bed28333f7"
CAL_A, CAL_B = 0.02132, -0.424          # tunnel calibration v = a*rpm + b

# Every specimen the campaign has defined. Fuzzy-skin thickness confirmed by
# S. Eacuello on 30 Sep 2026 for Ra20/40/80; Ra10 is the 0.025 mm row of the
# 4 Aug settings table. Ra labels are targets from that table, not measured.
SPECIMENS = {
    "v1_smooth": dict(label="No texture", fuzz_mm=0.0, ra=None),
    "v1_Ra10":   dict(label="Ra 10", fuzz_mm=0.025, ra=10),
    "v1_Ra20":   dict(label="Ra 20", fuzz_mm=0.050, ra=20),
    "v1_Ra40":   dict(label="Ra 40", fuzz_mm=0.101, ra=40),
    "v1_Ra80":   dict(label="Ra 80", fuzz_mm=0.202, ra=80),
}
BASE = "v1_Ra20"
CORE = ["v1_Ra20", "v1_Ra40", "v1_Ra80"]


def v_nominal(rpm_cmd):
    """Wind speed from the COMMANDED fan speed: the one definition valid for
    every run (the drive readback changed convention between runs)."""
    return CAL_A * np.asarray(rpm_cmd, float) + CAL_B


# ---------------------------------------------------------------- loading --

def read_sweep(path):
    meta, body = {}, []
    for line in open(path):
        if line.startswith("#"):
            k, _, v = line[1:].strip().partition(",")
            meta[k.strip()] = v.strip().strip('"')
        else:
            body.append(line)
    return meta, pd.read_csv(StringIO("".join(body)))


def discover():
    """Level runs (one per specimen) and repeat runs (<specimen>_repeat[N])."""
    levels, repeats, skipped = {}, {}, []
    for f in sorted(LOGS.rglob("sweep_v1_*_summary.csv")):
        name = f.name[len("sweep_"):-len("_summary.csv")]
        meta, _ = read_sweep(f)
        if meta.get("protocol") != PROTOCOL:
            skipped.append((name, meta.get("protocol")))
            continue
        m = re.fullmatch(r"(v1_[A-Za-z0-9]+?)_(repeat\d*|r\d+)", name)
        if m and m.group(1) in SPECIMENS:
            repeats[name] = m.group(1)
        elif name in SPECIMENS:
            levels[name] = SPECIMENS[name]
        else:
            skipped.append((name, "unknown specimen"))
    order = [k for k in SPECIMENS if k in levels]
    return order, repeats, skipped


def _find(fname):
    hits = sorted(LOGS.rglob(fname))
    assert len(hits) == 1, f"expected one {fname} under {LOGS}, found {len(hits)}"
    return hits[0]


def load(name):
    m, s = read_sweep(_find(f"sweep_{name}_summary.csv"))
    _, p = read_sweep(_find(f"sweep_{name}_points.csv"))
    return dict(meta=m, summary=s, points=p)


# ------------------------------------------------------- P_max, both ways --

def refine(amps, watts, span=2):
    """Port of peak_finder.PeakResult.refine: least-squares parabola through
    the arg max and `span` dwells either side; the arg max itself if there
    are too few points, the fit is not concave, or the vertex falls outside."""
    k = int(np.argmax(watts))
    raw = (float(watts[k]), float(amps[k]))
    if len(amps) < 2 * span + 1:
        return raw + (0,)
    lo, hi = max(0, k - span), min(len(amps), k + span + 1)
    x, y = amps[lo:hi], watts[lo:hi]
    if len(x) < 3:
        return raw + (0,)
    a2, a1, a0 = np.polyfit(x, y, 2)
    if a2 >= 0:
        return raw + (0,)
    i_hat = -a1 / (2 * a2)
    if not (x[0] <= i_hat <= x[-1]):
        return raw + (0,)
    return float(a2 * i_hat ** 2 + a1 * i_hat + a0), float(i_hat), len(x)


def recompute(run):
    s, p = run["summary"], run["points"]
    rows = []
    for _, srow in s.iterrows():
        cmd = int(srow.fan_rpm_cmd)
        pts = p[(p.fan_rpm == cmd) & (p.tracking == 1) & (p.amps > 0)]
        a, w, v = pts.amps.values, pts.watts.values, pts.volts.values
        k = int(np.argmax(w))
        p_fit, i_fit, nfit = refine(a, w)
        allpts = p[p.fan_rpm == cmd]
        rows.append(dict(
            fan_rpm_cmd=cmd,
            fan_rpm_actual=int(srow.fan_rpm_actual),
            wind_mps_logged=float(srow.wind_mps),
            wind_mps_nominal=float(v_nominal(cmd)),
            p_raw=float(w[k]), i_raw=float(a[k]), v_raw=float(v[k]),
            p_fit=p_fit, i_fit=i_fit, fit_points=nfit,
            v_light=float(allpts.volts.values[0]), i_light=float(allpts.amps.values[0]),
            n_steps=int(len(allpts)),
            limited_by=srow.limited_by, clean=int(srow.clean),
            logged_p_raw=float(srow.get("p_max_raw_w", srow.get("p_max_w"))),
            logged_p_fit=float(srow["p_max_fit_w"]) if "p_max_fit_w" in s else np.nan,
        ))
    return pd.DataFrame(rows)


# ------------------------------------------------------------- statistics --

def paired(base, cand, col):
    """Geometric-mean ratio at matched fan set points, t-based 95% CI, plus
    the change in power-law exponent from the slope of the log-ratio."""
    m = base.merge(cand, on="fan_rpm_cmd", suffixes=("_b", "_c"))
    d = np.log(m[f"{col}_c"].values / m[f"{col}_b"].values)
    n = len(d)
    se = d.std(ddof=1) / math.sqrt(n)
    t = stats.t.ppf(0.975, n - 1)
    higher = int((d > 0).sum())
    reg = stats.linregress(np.log(m.wind_mps_nominal_b.values), d)
    t2 = stats.t.ppf(0.975, n - 2)
    return dict(n=n, level=math.expm1(d.mean()), lo=math.expm1(d.mean() - t * se),
                hi=math.expm1(d.mean() + t * se), sd_pct=100 * d.std(ddof=1),
                higher=higher, sign_p=float(stats.binomtest(higher, n, 0.5).pvalue),
                ratios=np.expm1(d), rpm=m.fan_rpm_cmd.values, v=m.wind_mps_nominal_b.values,
                dn=reg.slope, dn_half=t2 * reg.stderr)


def powerlaw(df, col):
    x, y = np.log(df.wind_mps_nominal.values), np.log(df[col].values)
    res = stats.linregress(x, y)
    t = stats.t.ppf(0.975, len(x) - 2)
    pred = np.exp(res.intercept) * df.wind_mps_nominal.values ** res.slope
    ss = ((df[col] - df[col].mean()) ** 2).sum()
    return dict(n=res.slope, se=res.stderr, lo=res.slope - t * res.stderr,
                hi=res.slope + t * res.stderr, a=math.exp(res.intercept),
                r2_log=res.rvalue ** 2, r2_lin=1 - ((df[col] - pred) ** 2).sum() / ss)


def roughness_trend(rec, names, col):
    """ln P[r,s] = alpha_s + beta*ln(fuzz thickness_r): set-point intercepts,
    one slope. Only textured specimens (thickness > 0) enter."""
    tex = [b for b in names if SPECIMENS[b]["fuzz_mm"] > 0]
    rows = []
    for b in tex:
        for _, r in rec[b].iterrows():
            rows.append((int(r.fan_rpm_cmd), math.log(SPECIMENS[b]["fuzz_mm"]), math.log(r[col])))
    sp, lt, lp = map(np.array, zip(*rows))
    levels = sorted(set(sp))
    X = np.column_stack([(sp == s).astype(float) for s in levels] + [lt])
    beta, *_ = np.linalg.lstsq(X, lp, rcond=None)
    resid = lp - X @ beta
    dof = len(lp) - X.shape[1]
    cov = (resid @ resid / dof) * np.linalg.inv(X.T @ X)
    t = stats.t.ppf(0.975, dof)
    b, se = beta[-1], math.sqrt(cov[-1, -1])
    piv = {b_: rec[b_].set_index("fan_rpm_cmd")[col] for b_ in tex}
    mono = sum(all(piv[tex[i]][s] < piv[tex[i + 1]][s] for i in range(len(tex) - 1)) for s in levels)
    return dict(beta=b, lo=b - t * se, hi=b + t * se, dof=dof, mono=mono, n_sp=len(levels),
                n_levels=len(tex), doubling=2 ** b - 1, doubling_lo=2 ** (b - t * se) - 1,
                doubling_hi=2 ** (b + t * se) - 1)


def thevenin(run):
    """Per set point, V = V_oc - I*R over tracking dwells with V, I > 0
    (the same selection as src/generator_model.py)."""
    p = run["points"]
    out = []
    for cmd, g in p[p.tracking == 1].groupby("fan_rpm"):
        g = g[(g.volts > 0) & (g.amps > 0)]
        if len(g) < 4:
            continue
        slope, icept = np.polyfit(g.amps, g.volts, 1)
        pred = icept + slope * g.amps
        r2 = 1 - ((g.volts - pred) ** 2).sum() / ((g.volts - g.volts.mean()) ** 2).sum()
        out.append(dict(fan_rpm_cmd=int(cmd), wind_mps_nominal=float(v_nominal(cmd)),
                        v_oc=icept, r_int=-slope, r2=r2, n=len(g),
                        p_match=icept ** 2 / (-4 * slope)))
    return pd.DataFrame(out)


def thev_compare(tb, tc):
    m = tb.merge(tc, on="fan_rpm_cmd", suffixes=("_b", "_c"))
    dv = np.log(m.v_oc_c / m.v_oc_b)
    dr = np.log(m.r_int_c / m.r_int_b)
    t = stats.t.ppf(0.975, len(m) - 1)
    return dict(voc=math.expm1(dv.mean()), voc_half=100 * t * dv.std(ddof=1) / math.sqrt(len(m)),
                r=math.expm1(dr.mean()), r_half=100 * t * dr.std(ddof=1) / math.sqrt(len(m)),
                r_lo=math.expm1(dr.mean() - t * dr.std(ddof=1) / math.sqrt(len(m))),
                r_hi=math.expm1(dr.mean() + t * dr.std(ddof=1) / math.sqrt(len(m))),
                voc_share=2 * dv.mean() / (2 * dv.mean() - dr.mean()),
                voc_higher=int((dv > 0).sum()), n=len(m),
                # A pure wind offset raising V_oc by dv would also lower R by
                # (0.791/1.497)*dv, from this rig's generator scaling (docs/09).
                r_if_wind=math.expm1(-0.791 / 1.497 * dv.mean()))


# ----------------------------------------------------- Jeong-lab, 27 July --

def jeong_july():
    """Reprocess the lab's raw 360 Hz export in the LAB'S OWN WINDOWS
    (17 equal slices, middle half of each of the first 16 - this reproduces
    Summary_Table exactly), then with the current zero measured at load-off
    and a 1 s moving mean in place of the raw-sample maximum."""
    d = JL / "2026-07-27_no_texture_baseline"
    raw = pd.read_csv(d / "0727windturbine.csv")
    raw.columns = ["t", "date", "ts", "c1", "c2", "c3", "c4", "c5", "ev"]
    lab = pd.read_csv(d / "Summary_Table.csv")
    t = raw.t.values
    V = 4 * raw.c1.values
    I_lab = 2 * (raw.c2.values - 2.5)
    off = (t >= 331.0) & (t <= 341.4)          # load off, rotor still turning
    z0 = float(np.median(raw.c2.values[off]))
    I_zc = 2 * (raw.c2.values - z0)
    n1 = 360
    P_zc_1s = pd.Series(V * I_zc).rolling(n1, center=True).mean().values
    I_zc_1s = pd.Series(I_zc).rolling(n1, center=True).mean().values
    resid = (I_zc - I_zc_1s)[off]
    L = len(raw) // 17
    rows = []
    for k in range(16):
        i0, i1 = k * L + 1870, k * L + 5611 + 1
        w = slice(i0, i1)
        P_lab = V[w] * I_lab[w]
        j = int(np.nanargmax(P_lab))
        rows.append(dict(
            setting_rpm=int(lab.Setting_RPM[k]),
            lab_wind_mps=float(lab.Wind_Speed_ms[k]),
            lab_pdc_max_w=float(lab.Pdc_max[k]),
            repro_pdc_max_w=float(P_lab.max()),
            repro_vdc_max_v=float(V[w].max()), repro_idc_max_a=float(I_lab[w].max()),
            i_spike_at_pmax_a=float(I_zc[w][j] - I_zc_1s[w][j]),
            p_1s_max_zc_w=float(np.nanmax(P_zc_1s[w])),
            p_mean_zc_w=float(np.mean(V[w] * I_zc[w])),
            i_mean_zc_a=float(np.mean(I_zc[w])),
            v_mean_v=float(np.mean(V[w])),
            t_start_s=float(t[i0]), t_end_s=float(t[i1 - 1]),
        ))
    J = pd.DataFrame(rows)
    rel = np.abs(J.repro_pdc_max_w / J.lab_pdc_max_w - 1)
    assert rel.max() < 1e-9, f"lab recipe no longer reproduces Summary_Table: {rel.max()}"
    return J, dict(z0=z0, noise_a=float(np.std(resid[~np.isnan(resid)])),
                   null_p=float((V[off] * I_lab[off]).max()),
                   null_i=float(I_lab[off].max()), max_relerr=float(rel.max()),
                   fs=float(1 / np.median(np.diff(t[:1000]))))


def jeong_june():
    return pd.read_csv(JL / "2026-06-05_initial_reference" / "Summary_Table_Part1_MAX.csv")


# ------------------------------------------------------------------ main --

def main():
    names, repeats, skipped = discover()
    runs = {b: load(b) for b in list(names) + list(repeats)}
    rec = {b: recompute(runs[b]) for b in runs}
    N = {"levels": names, "repeats": repeats, "skipped": skipped}

    for b in runs:
        r = rec[b]
        N[f"maxdev_raw_{b}"] = float(np.max(np.abs(r.p_raw - r.logged_p_raw)))
        if r.logged_p_fit.notna().all():
            N[f"maxdev_fit_{b}"] = float(np.max(np.abs(r.p_fit - r.logged_p_fit) / r.logged_p_fit))
        N[f"clean_{b}"] = int(r.clean.sum())
        N[f"steps_{b}"] = int(r.n_steps.sum())
        N[f"slip_min_{b}"] = int((r.fan_rpm_actual - r.fan_rpm_cmd).min())
        N[f"slip_max_{b}"] = int((r.fan_rpm_actual - r.fan_rpm_cmd).max())
        fr = [int(re.search(r"fell to (\d+)%", x).group(1)) for x in runs[b]["summary"].stopped_by]
        N[f"rolloff_min_{b}"], N[f"rolloff_max_{b}"] = min(fr), max(fr)
        p = runs[b]["points"]
        if "t_unix" in p:
            N[f"minutes_{b}"] = float((p.t_unix.max() - p.t_unix.min()) / 60)
        r.to_csv(TAB / f"pmax_{b}.csv", index=False)

    # pairwise: every other level and every repeat against Ra20, plus Ra80 vs Ra40
    P = {}
    others = [b for b in names if b != BASE] + list(repeats)
    for col in ("p_raw", "p_fit"):
        for c in others:
            P[(BASE, c, col)] = paired(rec[BASE], rec[c], col)
        if "v1_Ra40" in rec and "v1_Ra80" in rec:
            P[("v1_Ra40", "v1_Ra80", col)] = paired(rec["v1_Ra40"], rec["v1_Ra80"], col)
        for rp, parent in repeats.items():
            if parent != BASE:
                P[(parent, rp, col)] = paired(rec[parent], rec[rp], col)
    PL = {(b, col): powerlaw(rec[b], col) for b in runs for col in ("p_raw", "p_fit")}
    TR = {col: roughness_trend(rec, names, col) for col in ("p_raw", "p_fit")}
    TH = {b: thevenin(runs[b]) for b in runs}
    for b in runs:
        TH[b].to_csv(TAB / f"thevenin_{b}.csv", index=False)
    N["thev_min_r2"] = float(min(TH[b].r2.min() for b in runs))
    TC = {c: thev_compare(TH[BASE], TH[c]) for c in others}

    for c in others:
        m = rec[BASE].merge(rec[c], on="fan_rpm_cmd", suffixes=("_b", "_c"))
        d = np.log(m.v_light_c / m.v_light_b)
        N[f"vlight_{c}"] = float(100 * np.expm1(d.mean()))
        N[f"vlight_higher_{c}"] = int((d > 0).sum())

    # Ra20's fan readback is output frequency x 29.5 rpm/Hz in 0.1 Hz steps
    r20 = rec[BASE]
    q = r20.fan_rpm_actual / 2.95
    N["ra20_on_grid"] = int((np.abs(q - np.round(q)) < 0.2).sum())
    # worst case, if that readback were a real air-speed deficit
    n20 = PL[(BASE, "p_raw")]["n"]
    r20c = r20.copy()
    corr = (r20c.wind_mps_nominal / r20c.wind_mps_logged) ** n20
    r20c["p_raw"] = r20c.p_raw * corr
    SENS = {c: paired(r20c, rec[c], "p_raw") for c in ("v1_Ra40", "v1_Ra80") if c in rec}
    N["slipcorr_max_pct"] = float(100 * (corr.max() - 1))
    # fan motor current at matched command (a slower Ra20 fan would draw less)
    mc = {b: runs[b]["points"].groupby("fan_rpm").motor_amps.median() for b in CORE}
    N["motor_amps_maxdiff"] = float(max(np.abs(mc[BASE] - mc[c]).max() for c in CORE if c != BASE))

    J, JN = jeong_july()
    for b in CORE:
        J[f"rig_{b}_p_raw_w"] = J.setting_rpm.map(rec[b].set_index("fan_rpm_cmd").p_raw)
    J["ratio_1s_to_Ra20"] = J.p_1s_max_zc_w / J[f"rig_{BASE}_p_raw_w"]
    J.to_csv(BUILD / "july_final.csv", index=False)
    JUNE = jeong_june()

    out = {"N": N,
           "pairs": {f"{b}|{c}|{col}": {k: (v.tolist() if isinstance(v, np.ndarray) else v)
                                        for k, v in r.items()} for (b, c, col), r in P.items()},
           "powerlaw": {f"{b}|{col}": r for (b, col), r in PL.items()},
           "trend": TR, "thevenin_vs_Ra20": TC, "jeong": JN,
           "slip_sensitivity": {c: {k: (v.tolist() if isinstance(v, np.ndarray) else v)
                                    for k, v in r.items()} for c, r in SENS.items()}}
    json.dump(out, open(BUILD / "numbers.json", "w"), indent=1, default=float)

    write_macros(N, P, PL, TR, TC, rec, SENS, J, JN, names, repeats)
    write_tables(rec, P, PL, TH, names, J)
    import figures
    figures.make_all(rec, P, PL, TR, TH, runs, names, repeats, J, JUNE)
    print("levels:", names, "repeats:", repeats, "skipped:", skipped)
    print("built:", BUILD)


# ------------------------------------------------------------- LaTeX out --

WORDS = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"]


def _name(s):
    """LaTeX macro names are letters only."""
    for d, w in zip("0123456789", WORDS):
        s = s.replace(d, w)
    return "".join(ch for ch in s if ch.isalpha())


def sci(x, nd=1):
    """1.2e-04 -> 1.2\\times10^{-4} (for use inside $...$)."""
    m, e = f"{x:.{nd}e}".split("e")
    return f"{m}\\times10^{{{int(e)}}}"


def pct(x, nd=1, sign=True):
    v = 100 * x
    s = f"{v:+.{nd}f}" if sign else f"{v:.{nd}f}"
    return s.replace("-", "\\textminus{}")


# macro keys: A = Ra20, B = Ra40, C = Ra80, S = no texture, T = Ra10, R = Ra20 remount
SHORT = {"v1_Ra20": "A", "v1_Ra40": "B", "v1_Ra80": "C", "v1_smooth": "S", "v1_Ra10": "T",
         "v1_Ra20_repeat": "R"}


def short(b):
    return SHORT.get(b, _name(b))


def write_macros(N, P, PL, TR, TC, rec, SENS, J, JN, names, repeats):
    M = {}
    for (b, c, col), r in P.items():
        k = f"{short(b)}{short(c)}{'raw' if col == 'p_raw' else 'fit'}"
        M[f"lvl{k}"] = pct(r["level"])
        M[f"lvl{k}lo"] = pct(r["lo"])
        M[f"lvl{k}hi"] = pct(r["hi"])
        M[f"hi{k}"] = f"{r['higher']}"
        M[f"n{k}"] = f"{r['n']}"
        M[f"sd{k}"] = f"{r['sd_pct']:.1f}"
        M[f"signp{k}"] = sci(r["sign_p"])
        M[f"dn{k}"] = f"{r['dn']:+.3f}".replace("-", "\\textminus{}")
        M[f"dnhalf{k}"] = f"{r['dn_half']:.3f}"
        M[f"minr{k}"] = pct(r["ratios"].min())
        M[f"maxr{k}"] = pct(r["ratios"].max())
    for (b, col), r in PL.items():
        k = f"{short(b)}{'raw' if col == 'p_raw' else 'fit'}"
        M[f"n{k}exp"] = f"{r['n']:.2f}"
        M[f"n{k}lo"] = f"{r['lo']:.2f}"
        M[f"n{k}hi"] = f"{r['hi']:.2f}"
        M[f"rtwo{k}"] = f"{r['r2_log']:.4f}"
    for col, r in TR.items():
        k = "raw" if col == "p_raw" else "fit"
        M[f"beta{k}"] = f"{r['beta']:.3f}"
        M[f"beta{k}lo"] = f"{r['lo']:.3f}"
        M[f"beta{k}hi"] = f"{r['hi']:.3f}"
        M[f"dbl{k}"] = pct(r["doubling"])
        M[f"dbl{k}lo"] = pct(r["doubling_lo"])
        M[f"dbl{k}hi"] = pct(r["doubling_hi"])
        M[f"mono{k}"] = f"{r['mono']}"
        M[f"nlevels{k}"] = f"{r['n_levels']}"
    for c, r in TC.items():
        k = short(c)
        M[f"voc{k}"] = pct(r["voc"])
        M[f"vochalf{k}"] = f"{r['voc_half']:.1f}"
        M[f"rint{k}"] = pct(r["r"])
        M[f"rinthalf{k}"] = f"{r['r_half']:.1f}"
        M[f"rintlo{k}"] = pct(r["r_lo"])
        M[f"rinthi{k}"] = pct(r["r_hi"])
        M[f"vocshare{k}"] = f"{100 * r['voc_share']:.0f}"
        M[f"vochigher{k}"] = f"{r['voc_higher']}"
        M[f"rifwind{k}"] = pct(r["r_if_wind"])
        M[f"vlight{k}"] = pct(N[f"vlight_{c}"] / 100)
        M[f"vlighthigher{k}"] = f"{N[f'vlight_higher_{c}']}"
    for c, r in SENS.items():
        k = short(c)
        M[f"sens{k}"] = pct(r["level"])
        M[f"sens{k}lo"] = pct(r["lo"])
        M[f"sens{k}hi"] = pct(r["hi"])
        M[f"senshi{k}"] = f"{r['higher']}"
    for b in rec:
        k = short(b)
        M[f"clean{k}"] = f"{N[f'clean_{b}']}"
        M[f"steps{k}"] = f"{N[f'steps_{b}']}"
        lo, hi = sorted((abs(N[f'slip_min_{b}']), abs(N[f'slip_max_{b}'])))
        M[f"slipabs{k}"] = f"{lo}--{hi}" if lo != hi else f"{lo}"
        M[f"pmaxtop{k}"] = f"{rec[b].p_raw.iloc[-1]:.2f}"
        if f"minutes_{b}" in N:
            M[f"minutes{k}"] = f"{N[f'minutes_{b}']:.1f}"
    M["rolloffmin"] = f"{min(N[f'rolloff_min_{b}'] for b in rec)}"
    M["rolloffmax"] = f"{max(N[f'rolloff_max_{b}'] for b in rec)}"
    M["slipcorrmax"] = f"{N['slipcorr_max_pct']:.1f}"
    M["ragrid"] = f"{N['ra20_on_grid']}"
    M["motorampsdiff"] = f"{N['motor_amps_maxdiff']:.1f}"
    M["thevminrtwo"] = f"{N['thev_min_r2']:.3f}"
    M["vlo"] = f"{v_nominal(500):.1f}"
    M["vhi"] = f"{v_nominal(1800):.1f}"
    M["nruns"] = f"{len(rec)}"
    A, rho = 2 * 0.1016 * 0.2451, 1.204        # swept area 2RH, standard density
    cps = [p / (0.5 * rho * A * v ** 3) for b in names
           for p, v in zip(rec[b].p_raw, rec[b].wind_mps_nominal)]
    M["cpelmin"] = f"{100 * min(cps):.2f}"
    M["cpelmax"] = f"{100 * max(cps):.2f}"
    if ("v1_Ra20", "v1_Ra40", "p_raw") in P and ("v1_Ra20", "v1_Ra80", "p_raw") in P:
        g40 = math.log1p(P[("v1_Ra20", "v1_Ra40", "p_raw")]["level"])
        g80 = math.log1p(P[("v1_Ra20", "v1_Ra80", "p_raw")]["level"])
        M["logshareforty"] = f"{100 * g40 / g80:.0f}"
        r40 = rec["v1_Ra40"].set_index("fan_rpm_cmd").p_raw
        r80 = rec["v1_Ra80"].set_index("fan_rpm_cmd").p_raw
        M["gapsevenhundred"] = f"{100 * abs(r40[700] / r80[700] - 1):.1f}"
    # Jeong lab
    M["jlzero"] = f"{JN['z0']:.4f}"
    M["jlnoise"] = f"{1000 * JN['noise_a']:.0f}"
    M["jlnullp"] = f"{JN['null_p']:.2f}"
    M["jlnulli"] = f"{JN['null_i']:.3f}"
    M["jlfs"] = f"{JN['fs']:.0f}"
    j = J.set_index("setting_rpm")
    for s in (500, 1700):
        k = _name(str(s))
        M[f"jllab{k}"] = f"{j.lab_pdc_max_w[s]:.3f}"
        M[f"jlone{k}"] = f"{j.p_1s_max_zc_w[s]:.3f}"
        M[f"jlimean{k}"] = f"{1000 * j.i_mean_zc_a[s]:.1f}".replace("-", "\\textminus{}")
    M["jlrigAseventeen"] = f"{j.rig_v1_Ra20_p_raw_w[1700]:.3f}"
    loaded = J[(J.setting_rpm >= 900) & (J.setting_rpm <= 1800) & (J.setting_rpm != 1300)]
    M["jlratiolo"] = f"{loaded.ratio_1s_to_Ra20.min():.2f}"
    M["jlratiohi"] = f"{loaded.ratio_1s_to_Ra20.max():.2f}"
    M["jlspikelo"] = f"{J.i_spike_at_pmax_a.min():.3f}"
    M["jlspikehi"] = f"{J.i_spike_at_pmax_a.max():.3f}"
    M["jlunloadedmax"] = f"{1000 * J[J.setting_rpm <= 700].i_mean_zc_a.abs().max():.1f}"
    flags = {"HaveRepeat": "v1_Ra20_repeat" in repeats, "HaveRaTen": "v1_Ra10" in names,
             "HaveSmooth": "v1_smooth" in names}
    with open(BUILD / "numbers.tex", "w") as f:
        f.write("% generated by src/build_report.py — do not edit\n")
        for k, v in flags.items():
            f.write(f"\\newif\\if{k}\\{k}{'true' if v else 'false'}\n")
        for k, v in sorted(M.items()):
            f.write(f"\\newcommand{{\\{_name(k)}}}{{{v}}}\n")


def latex_label(b):
    s = SPECIMENS.get(b)
    if s:
        return f"\\Ra{{{s['ra']}}}" if s["ra"] else s["label"]
    m = re.fullmatch(r"(v1_[A-Za-z0-9]+?)_(repeat\d*|r\d+)", b)
    if m and m.group(1) in SPECIMENS:
        return latex_label(m.group(1)) + " remount"
    return b.replace("_", r"\_")


def write_tables(rec, P, PL, TH, names, J):
    cols = list(names)
    head = lambda sub: ("Fan & $v$ & " + " & ".join(f"\\multicolumn{{2}}{{c}}{{{latex_label(b)}}}" for b in cols)
                        + r" \\" + "\n" + "".join(f"\\cmidrule(lr){{{3 + 2 * i}-{4 + 2 * i}}}" for i in range(len(cols)))
                        + "\nrpm & m/s & " + " & ".join(sub for _ in cols) + r" \\" + "\n")

    lines = []
    for i, cmd in enumerate(rec[BASE].fan_rpm_cmd):
        cells = [f"{cmd}", f"{v_nominal(cmd):.1f}"]
        for b in cols:
            r = rec[b].iloc[i]
            cells += [f"{r.p_raw:.4f}", f"{r.p_fit:.4f}"]
        lines.append(" & ".join(cells) + r" \\")
    (TAB / "pmax_rows.tex").write_text("\n".join(lines) + "\n")
    (TAB / "pmax_table.tex").write_text(
        f"\\begin{{tabular}}{{@{{}}{'rr' + ' rr' * len(cols)}@{{}}}}\n\\toprule\n" + head("raw & fit")
        + "\\midrule\n" + "\n".join(lines) + "\n\\bottomrule\n\\end{tabular}\n")

    lines = []
    for (b, c, col), r in P.items():
        lines.append(" & ".join([
            f"{latex_label(c)} vs {latex_label(b)}",
            "raw arg\\,max" if col == "p_raw" else "parabolic fit",
            f"${pct(r['level'])}$", f"$[{pct(r['lo'])},\\ {pct(r['hi'])}]$",
            f"{r['higher']}/{r['n']}",
            f"${pct(r['ratios'].min())}$ to ${pct(r['ratios'].max())}$",
            f"${r['dn']:+.3f} \\pm {r['dn_half']:.3f}$".replace("-", "\\textminus{}"),
        ]) + r" \\")
    (TAB / "pairwise_rows.tex").write_text("\n".join(lines) + "\n")

    lines = []
    for b in rec:
        for col in ("p_raw", "p_fit"):
            r = PL[(b, col)]
            lines.append(" & ".join([
                latex_label(b), "raw arg\\,max" if col == "p_raw" else "parabolic fit",
                f"{r['n']:.3f}", f"[{r['lo']:.3f}, {r['hi']:.3f}]",
                f"{r['a'] * 1e6:.3f}", f"{r['r2_log']:.4f}", f"{r['r2_lin']:.4f}"]) + r" \\")
    (TAB / "powerlaw_rows.tex").write_text("\n".join(lines) + "\n")

    lines = []
    th = {b: TH[b].set_index("fan_rpm_cmd") for b in cols}
    for cmd in th[BASE].index:
        cells = [f"{cmd}", f"{v_nominal(cmd):.1f}"]
        for b in cols:
            r = th[b].loc[cmd]
            cells += [f"{r.v_oc:.2f}", f"{r.r_int:.1f}"]
        lines.append(" & ".join(cells) + r" \\")
    (TAB / "thevenin_rows.tex").write_text("\n".join(lines) + "\n")
    (TAB / "thevenin_table.tex").write_text(
        f"\\begin{{tabular}}{{@{{}}{'rr' + ' rr' * len(cols)}@{{}}}}\n\\toprule\n" + head("$V_{oc}$ & $R_{int}$")
        + "\\midrule\n" + "\n".join(lines) + "\n\\bottomrule\n\\end{tabular}\n")

    lines = []
    for _, r in J.iterrows():
        s = int(r.setting_rpm)
        rig = r.rig_v1_Ra20_p_raw_w
        cells = [f"{s}" + (r"$^{\dagger}$" if s == 1300 else ""),
                 f"{r.lab_pdc_max_w:.3f}", f"{r.p_1s_max_zc_w:.3f}",
                 f"{int(round(1000 * r.i_mean_zc_a)) + 0:d}".replace("-", "\\textminus{}"),
                 "—" if np.isnan(rig) else f"{rig:.3f}",
                 f"{r.ratio_1s_to_Ra20:.2f}" if (not np.isnan(rig) and s >= 900) else "—"]
        lines.append(" & ".join(cells) + r" \\")
    (TAB / "jeong_rows.tex").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
