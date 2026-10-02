"""Build every number, table and figure in the roughness report from raw data.

    python3 src/build_report.py            (from reports/roughness_2026-09)

Nothing in report/report.tex is typed by hand: numbers come from
build/numbers.tex (LaTeX macros), tables from build/tables/*.tex and figures
from build/fig/*.pdf. Re-running after a new sweep lands in ../../logs updates
all three, so the text cannot drift from the files.

New runs are picked up automatically if they carry protocol 94bed28333f7 and
name a specimen in SPECIMENS: sweep_v1_<label>[_repeat][_YYYYMMDD]_*.

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
if PACKAGED:            # running from the unzipped data package (7_code/)
    LOGS = ROOT / "1_rig_sweeps"
    JL = ROOT / "2_jeong_lab"
    KEYENCE_PKG = ROOT / "3_surface_scans"
    BUILD = ROOT / "rebuilt"
FIG = BUILD / "fig"
TAB = BUILD / "tables"
for d in (FIG, TAB):
    d.mkdir(parents=True, exist_ok=True)

PROTOCOL = "94bed28333f7"
CAL_A, CAL_B = 0.02132, -0.424          # tunnel calibration v = a*rpm + b

# Every specimen the campaign has defined. Fuzzy-skin thickness confirmed by
# S. Eacuello on 30 Sep 2026. Ra labels are names from the planning table, not
# measurements (measured Pa and Ra come from keyence.py).
SPECIMENS = {
    "v1_smooth": dict(label="No texture", fuzz_mm=0.0, ra=None, confirmed=True),
    "v1_unk":    dict(label="Unconfirmed set", fuzz_mm=float("nan"), ra=None, confirmed=False),
    "v1_Ra20":   dict(label="Ra 20", fuzz_mm=0.050, ra=20, confirmed=True),
    "v1_Ra40":   dict(label="Ra 40", fuzz_mm=0.101, ra=40, confirmed=True),
    "v1_Ra80":   dict(label="Ra 80", fuzz_mm=0.202, ra=80, confirmed=True),
}
# Sets run but not reported: print settings could not be confirmed.
EXCLUDED = {"v1_unk": "print settings unconfirmed; not reported"}
KEYENCE_DIR = REPO / "keyence readings 20261001"
ALIASES = {"v1_Ra0": "v1_smooth", "v1_notexture": "v1_smooth"}   # other names for the same specimen
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


NAME_RE = re.compile(r"(v1_[A-Za-z0-9]+?)(?:_(repeat\d*|r\d+))?(?:_(\d{8}))?")
FILES = {}          # run key -> file stem name (without sweep_ / _summary.csv)


def parse_name(name):
    """'v1_Ra20' | 'v1_Ra20_repeat' | 'v1_smooth_20261001' | 'v1_smooth_repeat_20261001'
    -> (specimen, is_repeat, yyyymmdd or '')."""
    m = NAME_RE.fullmatch(name)
    if not m or m.group(1) not in SPECIMENS:
        return None
    return m.group(1), bool(m.group(2)), m.group(3) or ""


def discover():
    """One PRIMARY run per specimen (the oldest that is not marked repeat) and every
    other run of that specimen as an additional MOUNTING. Primary runs are keyed by
    the specimen name (v1_Ra20); mountings by their own file name."""
    found, skipped = {}, []
    for f in sorted(LOGS.rglob("sweep_v1_*_summary.csv")):
        name = f.name[len("sweep_"):-len("_summary.csv")]
        for a, canon in ALIASES.items():
            if name == a or name.startswith(a + "_"):
                raise SystemExit(f"rename sweep_{name}_* to use '{canon}' (the report keys on that name)")
        meta, _ = read_sweep(f)
        if meta.get("protocol") != PROTOCOL:
            skipped.append((name, meta.get("protocol")))
            continue
        pn = parse_name(name)
        if pn is None:
            skipped.append((name, "unknown specimen"))
            continue
        spec, is_rep, date = pn
        if spec in EXCLUDED:
            skipped.append((name, EXCLUDED[spec]))
            continue
        date = date or (meta.get("clock", "")[:10].replace("-", "")) or "20260820"
        found.setdefault(spec, []).append((is_rep, date, name))
    names, repeats = [], {}
    for spec in SPECIMENS:
        if spec not in found:
            continue
        runs_ = sorted(found[spec], key=lambda r: (r[0], r[1], r[2]))   # non-repeat, oldest first
        primary = runs_[0][2]
        FILES[spec] = primary
        names.append(spec)
        for _, _, nm in runs_[1:]:
            FILES[nm] = nm
            repeats[nm] = spec
    return names, repeats, skipped


def _find(fname):
    hits = sorted(LOGS.rglob(fname))
    assert len(hits) == 1, f"expected one {fname} under {LOGS}, found {len(hits)}"
    return hits[0]


def load(key):
    stem = FILES.get(key, key)
    m, s = read_sweep(_find(f"sweep_{stem}_summary.csv"))
    _, p = read_sweep(_find(f"sweep_{stem}_points.csv"))
    d = parse_name(stem)
    date = (d[2] if d and d[2] else m.get("clock", "")[:10].replace("-", "")) or "20260820"
    return dict(meta=m, summary=s, points=p, stem=stem, date=date)


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
    # Adjacent set points are not independent (a run-long offset or a local bump
    # moves neighbours together). AR(1) effective sample size widens the interval.
    dc = d - d.mean()
    r1 = float(np.sum(dc[1:] * dc[:-1]) / np.sum(dc * dc))
    n_eff = max(2.0, n * (1 - max(r1, 0)) / (1 + max(r1, 0)))
    se_ar = d.std(ddof=1) / math.sqrt(n_eff)
    t_ar = stats.t.ppf(0.975, n_eff - 1)
    return dict(r1=r1, n_eff=n_eff, lo_ar=math.expm1(d.mean() - t_ar * se_ar),
                hi_ar=math.expm1(d.mean() + t_ar * se_ar),
                n=n, level=math.expm1(d.mean()), lo=math.expm1(d.mean() - t * se),
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
    tex = [b for b in names if SPECIMENS[b]["fuzz_mm"] > 0 and SPECIMENS[b]["confirmed"]]
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
    mono = sum(all(piv[tex[i]].get(s, np.nan) < piv[tex[i + 1]].get(s, np.nan) for i in range(len(tex) - 1))
               for s in levels)
    return dict(beta=b, lo=b - t * se, hi=b + t * se, dof=dof, mono=mono, n_sp=len(levels),
                n_levels=len(tex), doubling=2 ** b - 1, doubling_lo=2 ** (b - t * se) - 1,
                doubling_hi=2 ** (b + t * se) - 1)


def mount_analysis(rec, names, repeats, col="p_raw", only=None):
    """Each MOUNTING is one observation, so uncertainty includes mount-to-mount
    variation. y_run = mean over the set points common to every run considered of
    ln(P_run / P_ref), ref = the first Ra20 mounting in the set. sigma_mount is the
    pooled within-specimen SD of y (dof = sum of (mountings - 1)). `only` restricts
    to a subset of run keys (e.g. one day's runs)."""
    groups = {b: [b] + [rp for rp, par in repeats.items() if par == b] for b in names}
    if only is not None:
        groups = {b: [r for r in g if r in only] for b, g in groups.items()}
    groups = {b: g for b, g in groups.items() if g}
    if BASE not in groups:
        return None
    allruns = [r for g in groups.values() for r in g]
    common = sorted(set.intersection(*[set(rec[r].fan_rpm_cmd) for r in allruns]))
    ref = rec[groups[BASE][0]].set_index("fan_rpm_cmd")[col].reindex(common)
    y = {r: float(np.mean(np.log(rec[r].set_index("fan_rpm_cmd")[col].reindex(common) / ref)))
         for r in allruns}
    Y = {b: [y[r] for r in g] for b, g in groups.items()}
    ss = sum(sum((v - np.mean(vs)) ** 2 for v in vs) for vs in Y.values())
    dof = sum(len(vs) - 1 for vs in Y.values())
    if dof == 0:
        return None
    sig = math.sqrt(ss / dof)
    t = stats.t.ppf(0.975, dof)
    out = dict(k=dof, sigma=sig, Y=Y, groups=groups, n_common=len(common),
               n_mounts={b: len(v) for b, v in Y.items()}, cmp={},
               diffs={r: y[r] - y[groups[b][0]] for b, g in groups.items() for r in g[1:]})
    for c in groups:
        if c == BASE:
            continue
        d = np.mean(Y[c]) - np.mean(Y[BASE])
        se = sig * math.sqrt(1 / len(Y[c]) + 1 / len(Y[BASE]))
        out["cmp"][c] = dict(level=math.expm1(d), lo=math.expm1(d - t * se), hi=math.expm1(d + t * se),
                             survives=bool(d - t * se > 0 or d + t * se < 0), se=se)
    xs, ys = [], []
    for b in groups:
        f = SPECIMENS[b]["fuzz_mm"]
        if f == f and f > 0 and SPECIMENS[b]["confirmed"]:
            for v in Y[b]:
                xs.append(math.log(f)); ys.append(v)
    if len(set(xs)) >= 2 and len(xs) >= 3:
        res = stats.linregress(xs, ys)
        tt = stats.t.ppf(0.975, len(xs) - 2) if len(xs) > 2 else float("nan")
        out["trend"] = dict(beta=res.slope, lo=res.slope - tt * res.stderr, hi=res.slope + tt * res.stderr,
                            n=len(xs), doubling=2 ** res.slope - 1)
    return out


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
    tr = stats.linregress(np.log(m.wind_mps_nominal_b.values), dv)
    lowv = m.wind_mps_nominal_b.values <= 17
    highv = m.wind_mps_nominal_b.values >= 31
    return dict(voc_slope=tr.slope, voc_slope_p=tr.pvalue,
                voc_low=math.expm1(dv[lowv].mean()), voc_high=math.expm1(dv[highv].mean()),
                voc=math.expm1(dv.mean()), voc_half=100 * t * dv.std(ddof=1) / math.sqrt(len(m)),
                voc_lo=math.expm1(dv.mean() - t * dv.std(ddof=1) / math.sqrt(len(m))),
                voc_hi=math.expm1(dv.mean() + t * dv.std(ddof=1) / math.sqrt(len(m))),
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


def day_extras(rec, runs, G, DC, J, JUNE, N):
    """Quantities quoted in the 1 Oct sections that are not comparisons of power."""
    import day as _day
    keys = [k for ks in G.values() for k in ks]
    X = {}
    # set points that did not end on the roll-off rule, and how far power had fallen by then
    cut = []
    for r, ks in G.items():
        for i, k in enumerate(ks):
            for _, row in rec[k][rec[k].clean == 0].iterrows():
                c = int(row.fan_rpm_cmd)
                p = runs[k]["points"]
                p = p[(p.fan_rpm == c) & (p.tracking == 1)].reset_index(drop=True)
                fl = p.note.astype(str).str.contains("v_floor")
                last = p.watts[: fl.idxmax()].iloc[-1] if fl.any() else p.watts.iloc[-1]
                cut.append(dict(rotor=r, mounting=i + 1, rpm=c, frac=float(last / p.watts.max())))
    X["cut"] = cut
    X["n_clean"] = int(sum(rec[k].clean.sum() for k in keys))
    X["n_total"] = int(sum(len(rec[k]) for k in keys))
    X["minutes"] = float(np.median([N[f"minutes_{k}"] for k in keys if f"minutes_{k}" in N]))
    # fan motor current at matched command across all runs of the day
    mc = pd.DataFrame({k: runs[k]["points"].groupby("fan_rpm").motor_amps.median() for k in keys})
    rng = mc.max(axis=1) - mc.min(axis=1)
    X["motor_range_a"] = float(rng.max())
    X["motor_1800_a"] = float(mc.loc[1800].median())
    X["motor_1800_pct"] = float(100 * rng[1800] / mc.loc[1800].median())
    # where each textured rotor's gain is largest, and its range over set points
    v = np.array([float(v_nominal(c)) for c in DC["sp"]])
    X["gain"] = {r: dict(peak=float(rc.max()), v_peak=float(v[int(np.argmax(rc))]),
                         v_low=float(v[int(np.argmin(rc))]),
                         lo=float(rc.min()), hi=float(rc.max()), pos=int((rc > 0).sum()))
                 for r, rc in DC["ratio_curve"].items() if r != _day.REF}
    # Jeong lab against the rig's no-texture rotor (mean of its two mountings)
    base = pd.Series(DC["curve"][_day.REF], index=DC["sp"])
    jn = JUNE.set_index("Setting_RPM").Pdc_max
    mid = [c for c in jn.index if 800 <= c <= 1700 and c in base.index]
    lr = np.log(jn[mid].values / base[mid].values)
    X["june"] = dict(mid=math.expm1(lr.mean()), lo=math.expm1(lr.min()), hi=math.expm1(lr.max()))
    # where the June values sit against the band the textured rotors span on 1 Oct
    band = np.array([[DC["ratio_curve"][r][DC["sp"].index(c)] for r in DC["ratio_curve"] if r != _day.REF]
                     for c in mid])
    jr_ = np.expm1(lr)
    X["june"].update(n=len(mid), below=int((jr_ < band.min(axis=1)).sum()),
                     above=int((jr_ > band.max(axis=1)).sum()))
    ok = J[(J.setting_rpm >= 900) & (J.setting_rpm <= 1800) & (J.setting_rpm != 1300)]
    jr = ok.p_1s_max_zc_w.values / base[ok.setting_rpm].values
    X["july"] = dict(n=len(jr), below=int((jr < 1).sum()), lo=float(jr.min() - 1), hi=float(jr.max() - 1),
                     mid=float(np.exp(np.mean(np.log(jr))) - 1))
    jj = J.set_index("setting_rpm")
    vl = {c: float(np.mean([rec[k].set_index("fan_rpm_cmd").v_light[c] for k in G[_day.REF]]))
          for c in (500, 600, 700)}
    X["vfree"] = {c: dict(lab=float(jj.v_mean_v[c]), rig=vl[c]) for c in vl}
    X["vfree_maxdiff"] = max(abs(d["lab"] / d["rig"] - 1) for d in X["vfree"].values())
    return X


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
        fr = [int(m.group(1)) for x in runs[b]["summary"].stopped_by
              if (m := re.search(r"fell to (\d+)%", str(x)))]          # load-cutout rows have no %
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
    import day as _day
    import keyence as _key
    G = _day.groups(runs, repeats)
    DC = _day.compare(rec, G) if _day.REF in G else None
    DCf = _day.compare(rec, G, col="p_fit") if DC else None       # robustness: the other estimator
    DTc, DT = _day.thevenin_compare(TH, G) if DC else (None, None)
    XD = _day.cross_day(rec, G) if DC else {}
    kdir = globals().get("KEYENCE_PKG") if PACKAGED else KEYENCE_DIR
    SURF = _key.by_rotor(kdir) if kdir and Path(kdir).exists() else {}
    DAYX = dict(G=G, DC=DC, DCf=DCf, DTc=DTc, DT=DT, XD=XD, SURF=SURF,
                # first and last dwell, local time (the header clock is written at the END of a run)
                times={k: str(runs[k]["points"].t_local.min())[11:16] for ks in G.values() for k in ks},
                ends={k: str(runs[k]["points"].t_local.max())[11:16] for ks in G.values() for k in ks})
    if "v1_Ra40" in TH and "v1_Ra80" in TH:
        TC_BC = thev_compare(TH["v1_Ra40"], TH["v1_Ra80"])
        N["voc_slope_BC"], N["voc_slope_p_BC"] = TC_BC["voc_slope"], TC_BC["voc_slope_p"]
    # smallest absolute P difference between Ra40 and Ra20 (resolution check)
    dd = (rec["v1_Ra40"].set_index("fan_rpm_cmd").p_raw - rec[BASE].set_index("fan_rpm_cmd").p_raw)
    N["ra40_tie_rpm"] = int(dd.abs().idxmin()); N["ra40_tie_mw"] = float(1000 * dd.abs().min())
    MA = mount_analysis(rec, names, repeats)
    last = max(runs[r]["date"] for r in runs)
    day = [r for r in runs if runs[r]["date"] == last]
    MD = mount_analysis(rec, names, repeats, only=set(day)) if len({(repeats.get(r, r)) for r in day}) >= 2 else None
    N["sameday_date"] = last

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
    JUNE = jeong_june()

    # cut-in artefact model: P = a (v - vc)^m fitted to Ra20; what shift of vc would
    # reproduce each observed gain, and what exponent change would it bring?
    v20 = rec[BASE].wind_mps_nominal.values
    p20 = rec[BASE].p_raw.values
    best = None
    for vc in np.linspace(0, 8, 801):
        x = np.log(v20 - vc)
        mm, cc = np.polyfit(x, np.log(p20), 1)
        sse = np.sum((np.log(p20) - (cc + mm * x)) ** 2)
        if best is None or sse < best[0]:
            best = (sse, vc, mm, cc)
    _, vc0, m0, c0 = best
    CUT = {"vc": vc0, "m": m0}
    for c in ("v1_Ra40", "v1_Ra80"):
        target = math.log1p(P[(BASE, c, "p_raw")]["level"])
        lo_, hi_ = 0.0, min(v20) - vc0 - 0.01
        for _ in range(60):                       # bisection on the shift dv (vc -> vc - dv)
            mid = 0.5 * (lo_ + hi_)
            g = np.mean(m0 * np.log((v20 - vc0 + mid) / (v20 - vc0)))
            lo_, hi_ = (mid, hi_) if g < target else (lo_, mid)
        dv = 0.5 * (lo_ + hi_)
        d = m0 * np.log((v20 - vc0 + dv) / (v20 - vc0))
        dn = stats.linregress(np.log(v20), d).slope
        CUT[c] = dict(dv=dv, dn=dn)

    # June initial reference vs rig, by fan set point
    jn = JUNE.set_index("Setting_RPM").Pdc_max
    JR = {}
    for c in CORE:
        rr = rec[c].set_index("fan_rpm_cmd").p_raw
        common = [s_ for s_ in jn.index if s_ in rr.index]
        lr = np.log(jn[common].values / rr[common].values)
        mid = [i for i, s_ in enumerate(common) if 800 <= s_ <= 1700]
        JR[c] = dict(all=math.expm1(lr.mean()), mid=math.expm1(lr[mid].mean()),
                     lo=math.expm1(lr[mid].min()), hi=math.expm1(lr[mid].max()),
                     above=int((lr > 0).sum()), n=len(lr),
                     lowlo=math.expm1(lr[[i for i, s_ in enumerate(common) if s_ < 800]].min()),
                     lowhi=math.expm1(lr[[i for i, s_ in enumerate(common) if s_ < 800]].max()))

    # July: free-running voltage (load off, 500-700) vs rig Ra20 at the same fan setting,
    # which needs no current calibration; and tip-speed ratio from the lab's rotor pulse.
    jj = J.set_index("setting_rpm")
    r20i = rec[BASE].set_index("fan_rpm_cmd")
    th20 = TH[BASE].set_index("fan_rpm_cmd")
    VOC = {s_: dict(lab=float(jj.v_mean_v[s_]), rig_first=float(r20i.v_light[s_]),
                    rig_voc=float(th20.v_oc[s_])) for s_ in (500, 600, 700)}
    lab_tab = pd.read_csv(JL / "2026-07-27_no_texture_baseline" / "Summary_Table.csv").set_index("Setting_RPM")
    R_ROT = 0.1016
    lam = {s_: (lab_tab.Measured_RPM[s_] * 2 * math.pi / 60) * R_ROT / lab_tab.Wind_Speed_ms[s_]
           for s_ in range(900, 2000, 100)}           # loaded settings; 2000 skips pulses
    # generator constant from the unloaded windows: V = k*rpm + b
    kk, bb = np.polyfit([lab_tab.Measured_RPM[s_] for s_ in (500, 600, 700)],
                        [jj.v_mean_v[s_] for s_ in (500, 600, 700)], 1)
    lam_free = [((th20.v_oc[s_] - bb) / kk * 2 * math.pi / 60) * R_ROT / float(v_nominal(s_))
                for s_ in th20.index]
    LAM = dict(loaded_lo=min(lam.values()), loaded_hi=max(lam.values()),
               free_lo=min(lam_free), free_hi=max(lam_free), k=kk, b=bb)

    # July flags for the derived table
    J["usable_for_rig_comparison"] = ((J.setting_rpm >= 900) & (J.setting_rpm != 1300)).astype(int)
    J["window_note"] = np.where(J.setting_rpm <= 700, "load at 0 A",
                        np.where(J.setting_rpm == 800, "load 13-16 mA; mostly below the power peak",
                        np.where(J.setting_rpm == 1300, "window contains the step to 1400 rpm", "")))
    J.loc[J.setting_rpm < 900, "ratio_1s_to_Ra20"] = np.nan
    J.to_csv(BUILD / "july_final.csv", index=False, float_format="%.6g")
    loaded = J[J.usable_for_rig_comparison == 1].dropna(subset=["ratio_1s_to_Ra20"])
    hi_pts = loaded[loaded.setting_rpm >= 1400]
    EXTRA = dict(cut=CUT, june=JR, voc=VOC, lam=LAM,
                 jl_below=int((loaded.ratio_1s_to_Ra20 < 1).sum()), jl_n=len(loaded),
                 jl_hi_short_lo=float(1 - hi_pts.ratio_1s_to_Ra20.max()),
                 jl_hi_short_hi=float(1 - hi_pts.ratio_1s_to_Ra20.min()))

    # 1 Oct: what the report says about the day, everything against the no-texture rotor
    if DC:
        DAYX["EXT"] = day_extras(rec, runs, G, DC, J, JUNE, N)
        nt = pd.Series(DC["curve"][_day.REF], index=DC["sp"])
        J["rig_no_texture_1oct_p_raw_w"] = J.setting_rpm.map(nt)
        J["ratio_1s_to_no_texture"] = np.where(J.usable_for_rig_comparison == 1,
                                               J.p_1s_max_zc_w / J.rig_no_texture_1oct_p_raw_w, np.nan)

    out = {"N": N,
           "pairs": {f"{b}|{c}|{col}": {k: (v.tolist() if isinstance(v, np.ndarray) else v)
                                        for k, v in r.items()} for (b, c, col), r in P.items()},
           "powerlaw": {f"{b}|{col}": r for (b, col), r in PL.items()},
           "trend": TR, "thevenin_vs_Ra20": TC, "jeong": JN, "extra": EXTRA,
           "slip_sensitivity": {c: {k: (v.tolist() if isinstance(v, np.ndarray) else v)
                                    for k, v in r.items()} for c, r in SENS.items()}}
    json.dump(out, open(BUILD / "numbers.json", "w"), indent=1, default=float)
    write_derived(rec, P, PL, TH, J, runs, names, repeats, DAYX)


    write_macros(N, P, PL, TR, TC, rec, SENS, J, JN, names, repeats, MA, EXTRA, MD, DAYX)
    write_tables(rec, P, PL, TH, names, J, DAYX)
    import figures
    figures.make_all(rec, P, PL, TR, TH, runs, names, repeats, J, JUNE, MA, DAYX)
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
    return s.replace("-", "\\ensuremath{-}")


# macro keys: A = Ra20, B = Ra40, C = Ra80, S = no texture, T = unconfirmed set, R = Ra20 remount
SHORT = {"v1_Ra20": "A", "v1_Ra40": "B", "v1_Ra80": "C", "v1_smooth": "S", "v1_unk": "T",
         "v1_Ra20_repeat": "R", "v1_Ra40_repeat": "RB", "v1_Ra80_repeat": "RC",
         "v1_smooth_repeat": "RS", "v1_unk_repeat": "RT"}


def short(b):
    return SHORT.get(b, _name(b))


def write_macros(N, P, PL, TR, TC, rec, SENS, J, JN, names, repeats, MA=None, EX=None, MD=None, DX=None):
    M = {}
    if DX and DX["DC"]:
        DC, DT, XD, SURF, G = DX["DC"], DX["DT"], DX["XD"], DX["SURF"], DX["G"]
        M["dsigma"] = f"{100 * DC['sigma']:.1f}"
        M["ddof"] = f"{DC['dof']}"
        M["dnsp"] = f"{len(DC['sp'])}"
        M["dsplo"] = f"{DC['sp'][0]}"; M["dsphi"] = f"{DC['sp'][-1]}"
        M["dmaxpair"] = f"{100 * DC['max_pair_diff']:.1f}"
        for r, ys in DC["Y"].items():
            k = short(r)
            for i, v in enumerate(ys):
                M[f"dmount{k}{['one', 'two', 'three'][i]}"] = pct(math.expm1(v))
            M[f"dptop{k}"] = f"{DC['p_top'][r]:.2f}"
        for r, c in DC["vs_ref"].items():
            k = short(r)
            M[f"dlvl{k}"] = pct(c["level"]); M[f"dlo{k}"] = pct(c["lo"]); M[f"dhi{k}"] = pct(c["hi"])
        for key, c in DC["steps"].items():
            a, b = key.split("|")
            k = short(a) + short(b)
            M[f"dstep{k}"] = pct(c["level"]); M[f"dsteplo{k}"] = pct(c["lo"]); M[f"dstephi{k}"] = pct(c["hi"])
        DCf = DX.get("DCf")
        if DCf:
            M["dsigmafit"] = f"{100 * DCf['sigma']:.1f}"
            for r, c in DCf["vs_ref"].items():
                k = short(r)
                M[f"dlvlfit{k}"] = pct(c["level"]); M[f"dlofit{k}"] = pct(c["lo"]); M[f"dhifit{k}"] = pct(c["hi"])
        for r, c in DT.items():
            k = short(r)
            M[f"dvocsq{k}"] = pct((1 + c["voc"]) ** 2 - 1)        # power change if R_int is unchanged
            M[f"dvoc{k}"] = pct(c["voc"]); M[f"dvochalf{k}"] = f"{c['voc_half']:.1f}"
            M[f"drint{k}"] = pct(c["r"]); M[f"drinthalf{k}"] = f"{c['r_half']:.1f}"
            M[f"dvochigher{k}"] = f"{c['voc_higher']}"; M[f"dvocn{k}"] = f"{c['n']}"
        for r, v in XD.items():
            M[f"xd{short(r)}"] = pct(v)
        if XD:
            M["dxdlo"] = f"{100 * min(abs(v) for v in XD.values()):.0f}"
            M["dxdhi"] = f"{100 * max(abs(v) for v in XD.values()):.0f}"
        for r, v in SURF.items():
            k = short(r)
            M[f"sPa{k}"] = f"{v['Pa']:.1f}"; M[f"sRa{k}"] = f"{v['Ra']:.1f}"
            M[f"spitch{k}"] = f"{v['pitch_um']:.0f}"; M[f"snprof{k}"] = f"{v['n_profiles']}"
            if v["Pa_spread"] is not None:
                M[f"sPaspread{k}"] = f"{v['Pa_spread']:.1f}"; M[f"sRaspread{k}"] = f"{v['Ra_spread']:.1f}"
                M[f"sPaspreadpct{k}"] = f"{100 * v['Pa_spread'] / v['Pa']:.0f}"
        X = DX.get("EXT", {})
        if X:
            M["dclean"] = f"{X['n_clean']}"; M["dtotal"] = f"{X['n_total']}"
            M["dminutes"] = f"{X['minutes']:.0f}"
            M["dcutlist"] = " and ".join(
                f"{'the no-texture rotor' if c['rotor'] == 'v1_smooth' else latex_label(c['rotor'])}"
                f" mounting~{c['mounting']} at {c['rpm']} rpm "
                f"({100 * c['frac']:.0f}\\%)" for c in X["cut"]) or "none"
            M["dmotorrange"] = f"{X['motor_range_a']:.2f}"
            M["dmotorhi"] = f"{X['motor_1800_a']:.1f}"
            M["dmotorpct"] = f"{X['motor_1800_pct']:.1f}"
            for r, g in X["gain"].items():
                k = short(r)
                M[f"dpk{k}"] = pct(g["peak"]); M[f"dpkv{k}"] = f"{g['v_peak']:.0f}"
                M[f"dlov{k}"] = f"{g['v_low']:.0f}"
                M[f"drlo{k}"] = pct(g["lo"]); M[f"drhi{k}"] = pct(g["hi"]); M[f"dpos{k}"] = f"{g['pos']}"
            M["djunmid"] = pct(X["june"]["mid"]); M["djunlo"] = pct(X["june"]["lo"]); M["djunhi"] = pct(X["june"]["hi"])
            M["djunn"] = f"{X['june']['n']}"; M["djunbelow"] = f"{X['june']['below']}"
            M["djunabove"] = f"{X['june']['above']}"
            M["djunin"] = f"{X['june']['n'] - X['june']['below'] - X['june']['above']}"
            M["dvfreemax"] = f"{100 * X['vfree_maxdiff']:.0f}"
            M["djuln"] = f"{X['july']['n']}"; M["djulbelow"] = f"{X['july']['below']}"
            M["djullo"] = pct(X["july"]["lo"]); M["djulhi"] = pct(X["july"]["hi"]); M["djulmid"] = pct(X["july"]["mid"])
            for c, d in X["vfree"].items():
                k = _name(str(c))
                M[f"dvlab{k}"] = f"{d['lab']:.2f}"; M[f"dvrig{k}"] = f"{d['rig']:.2f}"
        if SURF:
            sc = next(iter(SURF.values()))["scans"][0]
            M["sfieldx"] = f"{sc['field_um'][0] / 1000:.2f}"; M["sfieldy"] = f"{sc['field_um'][1] / 1000:.2f}"
            M["sdx"] = f"{sc['dx_um']:.2f}"
            M["snscans"] = f"{sum(v['n_scans'] for v in SURF.values())}"
        t = DX["times"]
        first = [t[k] for k in G["v1_smooth"]]
        M["dtfirst"] = min(t.values()); M["dtlast"] = max(DX["ends"].values())
        sm = G["v1_smooth"]
        if len(sm) > 1:
            M["dsmoothgap"] = f"{(int(t[sm[1]][:2]) * 60 + int(t[sm[1]][3:])) - (int(t[sm[0]][:2]) * 60 + int(t[sm[0]][3:]))}"
            M["dsmoothdiff"] = pct(math.expm1(DC["Y"]["v1_smooth"][1] - DC["Y"]["v1_smooth"][0]))
            mins = lambda hhmm: int(hhmm[:2]) * 60 + int(hhmm[3:])
            span = mins(M["dtlast"]) - mins(M["dtfirst"])
            M["dspan"] = f"{span}"
            # the reference pair's difference, extrapolated linearly over the whole session
            M["ddrift"] = f"{abs(100 * math.expm1(DC['Y']['v1_smooth'][1] - DC['Y']['v1_smooth'][0])) * span / int(M['dsmoothgap']):.1f}"
            a, b = (rec[k].set_index("fan_rpm_cmd").p_raw[DC["sp"][-1]] for k in sm)
            M["dbreak"] = f"{100 * abs(b / a - 1):.1f}"
    if EX:
        M["cutvc"] = f"{EX['cut']['vc']:.1f}"
        M["cutm"] = f"{EX['cut']['m']:.2f}"
        for c in ("v1_Ra40", "v1_Ra80"):
            k = short(c)
            M[f"cutdv{k}"] = f"{EX['cut'][c]['dv']:.2f}"
            M[f"cutdn{k}"] = f"{EX['cut'][c]['dn']:+.2f}".replace("-", "\\ensuremath{-}")
        for c in CORE:
            k = short(c)
            r = EX["june"][c]
            M[f"jun{k}all"] = pct(r["all"]); M[f"jun{k}mid"] = pct(r["mid"])
            M[f"jun{k}lo"] = pct(r["lo"]); M[f"jun{k}hi"] = pct(r["hi"])
            M[f"jun{k}above"] = f"{r['above']}"; M[f"jun{k}n"] = f"{r['n']}"
            M[f"jun{k}lowlo"] = pct(r["lowlo"]); M[f"jun{k}lowhi"] = pct(r["lowhi"])
        for s_, v in EX["voc"].items():
            k = _name(str(s_))
            M[f"vlab{k}"] = f"{v['lab']:.2f}"; M[f"vrig{k}"] = f"{v['rig_first']:.2f}"
            M[f"vocrig{k}"] = f"{v['rig_voc']:.2f}"
        L = EX["lam"]
        M["lamloadlo"] = f"{L['loaded_lo']:.2f}"; M["lamloadhi"] = f"{L['loaded_hi']:.2f}"
        M["lamfreelo"] = f"{L['free_lo']:.2f}"; M["lamfreehi"] = f"{L['free_hi']:.2f}"
        M["jlbelow"] = f"{EX['jl_below']}"; M["jln"] = f"{EX['jl_n']}"
        M["jlshortlo"] = f"{100 * EX['jl_hi_short_lo']:.0f}"; M["jlshorthi"] = f"{100 * EX['jl_hi_short_hi']:.0f}"
    # the two set points with the largest Ra80 excess, for the text
    for s_ in (1000, 1100):
        k = _name(str(s_))
        for c in ("v1_Ra40", "v1_Ra80"):
            r = P[(BASE, c, "p_raw")]
            M[f"ex{short(c)}{k}"] = pct(r["ratios"][list(r["rpm"]).index(s_)])
        r = P[("v1_Ra40", "v1_Ra80", "p_raw")]
        M[f"exBC{k}"] = pct(r["ratios"][list(r["rpm"]).index(s_)])
    for (b, c, col), r in P.items():
        k = f"{short(b)}{short(c)}{'raw' if col == 'p_raw' else 'fit'}"
        M[f"lvl{k}"] = pct(r["level"])
        M[f"lvl{k}lo"] = pct(r["lo"])
        M[f"lvl{k}hi"] = pct(r["hi"])
        M[f"lvl{k}loar"] = pct(r["lo_ar"])
        M[f"lvl{k}hiar"] = pct(r["hi_ar"])
        M[f"rone{k}"] = f"{r['r1']:.2f}".replace("-", "\\ensuremath{-}")
        M[f"hi{k}"] = f"{r['higher']}"
        M[f"n{k}"] = f"{r['n']}"
        M[f"sd{k}"] = f"{r['sd_pct']:.1f}"
        M[f"signp{k}"] = sci(r["sign_p"])
        M[f"dn{k}"] = f"{r['dn']:+.3f}".replace("-", "\\ensuremath{-}")
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
        M[f"voclo{k}"] = pct(r["voc_lo"]); M[f"vochi{k}"] = pct(r["voc_hi"])
        M[f"rint{k}"] = pct(r["r"])
        M[f"rinthalf{k}"] = f"{r['r_half']:.1f}"
        M[f"rintlo{k}"] = pct(r["r_lo"])
        M[f"rinthi{k}"] = pct(r["r_hi"])
        M[f"vocshare{k}"] = f"{100 * r['voc_share']:.0f}"
        M[f"vochigher{k}"] = f"{r['voc_higher']}"
        M[f"rifwind{k}"] = pct(r["r_if_wind"])
        M[f"vocslope{k}"] = f"{r['voc_slope']:+.3f}".replace("-", "\\ensuremath{-}")
        M[f"vocslopep{k}"] = f"{r['voc_slope_p']:.3f}" if r["voc_slope_p"] >= 0.001 else "<0.001"
        M[f"voclow{k}"] = pct(r["voc_low"]); M[f"vochigh{k}"] = pct(r["voc_high"])
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
    nu = 1.5033e-5                                   # air at 20 C, m^2/s
    M["relo"] = f"{v_nominal(500) * 0.048 / nu / 1e4:.1f}"
    M["rehi"] = f"{v_nominal(1800) * 0.048 / nu / 1e5:.1f}"
    fb = [(b, int(c)) for b in names for c, k in zip(rec[b].fan_rpm_cmd, rec[b].fit_points) if k == 0]
    M["fallbacklist"] = " and ".join(f"{latex_label(b)} at {c} rpm" for b, c in fb) or "none"
    M["nfallback"] = f"{len(fb)}"
    if "voc_slope_BC" in N:
        M["vocslopeBC"] = f"{N['voc_slope_BC']:+.3f}".replace("-", "\\ensuremath{-}")
        M["vocslopepBC"] = f"{N['voc_slope_p_BC']:.3f}"
    M["tierpm"] = f"{N['ra40_tie_rpm']}"
    M["tiemw"] = f"{N['ra40_tie_mw']:.1f}"
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
        M[f"jlimean{k}"] = f"{1000 * j.i_mean_zc_a[s]:.1f}".replace("-", "\\ensuremath{-}")
    M["jlrigAseventeen"] = f"{j.rig_v1_Ra20_p_raw_w[1700]:.3f}"
    loaded = J[(J.setting_rpm >= 900) & (J.setting_rpm <= 1800) & (J.setting_rpm != 1300)]
    M["jlratiolo"] = f"{loaded.ratio_1s_to_Ra20.min():.2f}"
    M["jlratiohi"] = f"{loaded.ratio_1s_to_Ra20.max():.2f}"
    M["jlspikelo"] = f"{J.i_spike_at_pmax_a.min():.3f}"
    M["jlspikehi"] = f"{J.i_spike_at_pmax_a.max():.3f}"
    M["jlunloadedmax"] = f"{1000 * J[J.setting_rpm <= 700].i_mean_zc_a.abs().max():.1f}"
    flags = {"HaveRepeat": bool(repeats), "HaveRaTwentyRepeat": "v1_Ra20_repeat" in repeats,
             "HaveRaTen": "v1_unk" in names, "HaveSmooth": "v1_smooth" in names,
             "RaTenConfirmed": SPECIMENS["v1_unk"]["confirmed"],
             "HaveMountTrend": bool(MA and "trend" in MA),
             "AllRemounted": all(any(p == b for p in repeats.values()) for b in CORE)}
    for k in ("A", "B", "C", "S", "T"):          # always defined, so LaTeX can skip them safely
        flags[f"MountSurvives{k}"] = False
        flags[f"DaySurvives{k}"] = False
    flags["HaveSameDay"] = bool(MD)
    if MD:
        M["sdsigma"] = f"{100 * MD['sigma']:.1f}"
        M["sddof"] = f"{MD['k']}"
        M["sdncommon"] = f"{MD['n_common']}"
        M["sdcmplist"] = "; ".join(f"{latex_label(c)} ${pct(r['level'])}\\%$ (95\\% CI $[{pct(r['lo'])},\\ {pct(r['hi'])}]$)"
                                   for c, r in MD["cmp"].items())
        for c, r in MD["cmp"].items():
            flags[f"DaySurvives{short(c)}"] = r["survives"]
    if MA:
        lab = lambda b: latex_label(b)
        M["mountdifflist"] = "; ".join(f"{lab(rp)} {pct(math.expm1(d))}\\%" for rp, d in MA["diffs"].items())
        M["macmplist"] = "; ".join(f"{lab(c)} ${pct(r['level'])}\\%$ (95\\% CI $[{pct(r['lo'])},\\ {pct(r['hi'])}]$)"
                                   for c, r in MA["cmp"].items())
        M["nremounts"] = f"{MA['k']}"
        M["sigmamount"] = f"{100 * MA['sigma']:.1f}"
        for rp, d in MA["diffs"].items():
            M[f"mountdiff{short(rp)}"] = pct(math.expm1(d))
        for c, r in MA["cmp"].items():
            k = short(c)
            M[f"ma{k}"] = pct(r["level"]); M[f"ma{k}lo"] = pct(r["lo"]); M[f"ma{k}hi"] = pct(r["hi"])
            flags[f"MountSurvives{k}"] = r["survives"]
        if "trend" in MA:
            M["mabeta"] = f"{MA['trend']['beta']:.3f}"
            M["mabetalo"] = f"{MA['trend']['lo']:.3f}"
            M["mabetahi"] = f"{MA['trend']['hi']:.3f}"
            M["mabetan"] = f"{MA['trend']['n']}"
            M["madbl"] = pct(MA["trend"]["doubling"])
        parents = [latex_label(par) for par in dict.fromkeys(repeats.values())]
        joined = parents[0] if len(parents) == 1 else ", ".join(parents[:-1]) + " and " + parents[-1]
        M["remountlist"] = f"the {joined} rotor" + ("s" if len(parents) > 1 else "")
    with open(BUILD / "numbers.tex", "w") as f:
        f.write("% generated by src/build_report.py — do not edit\n")
        for k, v in flags.items():
            f.write(f"\\newif\\if{k}\\{k}{'true' if v else 'false'}\n")
        for k, v in sorted(M.items()):
            f.write(f"\\newcommand{{\\{_name(k)}}}{{{v}}}\n")


def write_derived(rec, P, PL, TH, J, runs, names, repeats, DX=None):
    """The analysis-ready tables shipped in the data package (4_derived/). Written here,
    not by the packager, so running this script from the package regenerates them."""
    D = BUILD / "derived"
    D.mkdir(exist_ok=True)
    spec = lambda b: SPECIMENS[repeats.get(b, b)]
    date = lambda b: runs[b]["meta"].get("clock", "")[:10] or {"v1_Ra20": "2026-08-20"}.get(b, "")
    iso = lambda b: f"{runs[b]['date'][:4]}-{runs[b]['date'][4:6]}-{runs[b]['date'][6:]}"
    # mounting number within the run's own test date (1 Oct: 1 and 2; Aug/Sep: 1)
    order = sorted(rec, key=lambda b: (repeats.get(b, b), runs[b]["date"], runs[b]["meta"].get("clock", "")))
    mnt, seen = {}, {}
    for b in order:
        key = (repeats.get(b, b), runs[b]["date"])
        seen[key] = seen.get(key, 0) + 1
        mnt[b] = seen[key]
    frames = []
    for b in rec:
        t = rec[b].copy()
        t.insert(0, "mounting", mnt[b])
        t.insert(0, "test_date", iso(b))
        t.insert(0, "fuzzy_skin_mm", spec(b)["fuzz_mm"])
        t.insert(0, "ra_label_um", spec(b)["ra"])
        t.insert(0, "rotor", runs[b]["stem"])
        frames.append(t)
    pk = pd.concat(frames)[[
        "rotor", "ra_label_um", "fuzzy_skin_mm", "test_date", "mounting", "fan_rpm_cmd",
        "fan_rpm_actual", "wind_mps_nominal", "wind_mps_logged", "p_raw", "i_raw", "v_raw",
        "p_fit", "i_fit", "fit_points", "v_light", "i_light", "n_steps", "limited_by", "clean"]]
    pk.rename(columns={"fan_rpm_actual": "fan_rpm_logged", "p_raw": "p_max_raw_w",
                       "i_raw": "i_at_p_max_raw_a", "v_raw": "v_at_p_max_raw_v",
                       "p_fit": "p_max_fit_w", "i_fit": "i_at_p_max_fit_a",
                       "v_light": "v_first_step_v", "i_light": "i_first_step_a"}).to_csv(
        D / "peak_power_all_rotors.csv", index=False, float_format="%.6g")
    th = []
    for b in rec:
        t = TH[b].copy()
        t.insert(0, "fuzzy_skin_mm", spec(b)["fuzz_mm"])
        t.insert(0, "mounting", mnt[b])
        t.insert(0, "test_date", iso(b))
        t.insert(0, "rotor", runs[b]["stem"])
        th.append(t)
    pd.concat(th).rename(columns={"v_oc": "v_oc_v", "r_int": "r_int_ohm",
                                  "p_match": "p_thevenin_match_w", "n": "n_steps_fitted"}).to_csv(
        D / "thevenin_by_setpoint.csv", index=False, float_format="%.6g")
    rows = []
    for (b, c, col), r in P.items():
        rows.append(dict(baseline=b, candidate=c,
                         basis={"p_raw": "raw_argmax", "p_fit": "parabolic_fit"}[col],
                         n_setpoints=r["n"], change_pct=100 * r["level"],
                         ci95_lo_pct=100 * r["lo"], ci95_hi_pct=100 * r["hi"],
                         ci95_ar1_lo_pct=100 * r["lo_ar"], ci95_ar1_hi_pct=100 * r["hi_ar"],
                         lag1_autocorr=r["r1"], setpoints_higher=r["higher"],
                         delta_n=r["dn"], delta_n_ci95_half=r["dn_half"]))
    pd.DataFrame(rows).to_csv(D / "paired_comparisons.csv", index=False, float_format="%.6g")
    rows = []
    for (b, col), r in PL.items():
        rows.append(dict(rotor=b, fuzzy_skin_mm=spec(b)["fuzz_mm"],
                         basis={"p_raw": "raw_argmax", "p_fit": "parabolic_fit"}[col],
                         exponent_n=r["n"], exponent_ci95_lo=r["lo"], exponent_ci95_hi=r["hi"],
                         coefficient_a=r["a"], r2_log=r["r2_log"], r2_linear=r["r2_lin"]))
    pd.DataFrame(rows).to_csv(D / "power_law_fits.csv", index=False, float_format="%.6g")
    J.to_csv(D / "jeong_0727_reprocessed_by_setting.csv", index=False, float_format="%.6g")
    if DX and DX["DC"]:
        DC, SURF = DX["DC"], DX["SURF"]
        rows = []
        for r, ks in DX["G"].items():
            for i, k in enumerate(ks):
                rows.append(dict(rotor=r, fuzzy_skin_mm=SPECIMENS[r]["fuzz_mm"], run=runs[k]["stem"],
                                 mounting=i + 1, run_start=DX["times"][k], run_end=DX["ends"][k],
                                 change_vs_no_texture_pct=100 * math.expm1(DC["y"][k])))
        pd.DataFrame(rows).to_csv(D / "oct1_by_mounting.csv", index=False, float_format="%.4g")
        rows = [dict(rotor=r, mountings=len(DC["Y"][r]),
                     change_vs_no_texture_pct=100 * c["level"], ci95_lo_pct=100 * c["lo"], ci95_hi_pct=100 * c["hi"],
                     p_max_1800rpm_w=DC["p_top"][r]) for r, c in DC["vs_ref"].items()]
        pd.DataFrame(rows).to_csv(D / "oct1_vs_no_texture.csv", index=False, float_format="%.4g")
        if SURF:
            pd.DataFrame([dict(rotor=r, fuzzy_skin_mm=SPECIMENS[r]["fuzz_mm"], scans=v["n_scans"],
                               profiles=v["n_profiles"], Pa_um=v["Pa"], Ra_lc025_um=v["Ra"],
                               dominant_wavelength_um=v["pitch_um"],
                               Pa_scan_spread_um=v["Pa_spread"], Ra_scan_spread_um=v["Ra_spread"])
                          for r, v in SURF.items()]).to_csv(D / "surface_roughness.csv", index=False, float_format="%.4g")


def latex_label(b):
    sp = SPECIMENS.get(b)
    if sp:
        return f"\\Ra{{{sp['ra']}}}" if sp["ra"] else sp["label"]
    pn = parse_name(b)
    if pn:
        spec, is_rep, date = pn
        tag = f"{int(date[6:])} {['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][int(date[4:6]) - 1]}" if date else ""
        return latex_label(spec) + (" repeat" if is_rep else " remount") + (f" ({tag})" if tag else "")
    return b.replace("_", r"\_")

def write_tables(rec, P, PL, TH, names, J, DX=None):
    cols = list(names)
    head = lambda sub: ("Fan & $v$ & " + " & ".join(f"\\multicolumn{{2}}{{c}}{{{latex_label(b)}}}" for b in cols)
                        + r" \\" + "\n" + "".join(f"\\cmidrule(lr){{{3 + 2 * i}-{4 + 2 * i}}}" for i in range(len(cols)))
                        + "\nrpm & m/s & " + " & ".join(sub for _ in cols) + r" \\" + "\n")

    lines = []
    allsp = sorted(set().union(*[set(rec[b].fan_rpm_cmd) for b in cols]))
    for cmd in allsp:
        cells = [f"{cmd}", f"{v_nominal(cmd):.1f}"]
        for b in cols:
            rb = rec[b].set_index("fan_rpm_cmd")
            if cmd in rb.index:
                cells += [f"{rb.p_raw[cmd]:.4f}", f"{rb.p_fit[cmd]:.4f}"]
            else:
                cells += ["—", "—"]
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
            f"$[{pct(r['lo_ar'])},\\ {pct(r['hi_ar'])}]$",
            f"{r['higher']}/{r['n']}",
            f"${pct(r['ratios'].min())}$ to ${pct(r['ratios'].max())}$",
            f"${r['dn']:+.3f} \\pm {r['dn_half']:.3f}$".replace("-", "\\ensuremath{-}"),
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
    for cmd in sorted(set().union(*[set(th[b].index) for b in cols])):
        cells = [f"{cmd}", f"{v_nominal(cmd):.1f}"]
        for b in cols:
            if cmd in th[b].index:
                r = th[b].loc[cmd]
                cells += [f"{r.v_oc:.2f}", f"{r.r_int:.1f}"]
            else:
                cells += ["—", "—"]
        lines.append(" & ".join(cells) + r" \\")
    (TAB / "thevenin_rows.tex").write_text("\n".join(lines) + "\n")
    (TAB / "thevenin_table.tex").write_text(
        f"\\begin{{tabular}}{{@{{}}{'rr' + ' rr' * len(cols)}@{{}}}}\n\\toprule\n" + head("$V_{oc}$ & $R_{int}$")
        + "\\midrule\n" + "\n".join(lines) + "\n\\bottomrule\n\\end{tabular}\n")

    lines = []
    nt = None
    if DX and DX["DC"]:
        nt = pd.Series(DX["DC"]["curve"]["v1_smooth"], index=DX["DC"]["sp"])
    for _, r in J.iterrows():
        s = int(r.setting_rpm)
        rig = (nt.get(s, np.nan) if nt is not None else r.rig_v1_Ra20_p_raw_w)
        cells = [f"{s}" + (r"$^{\dagger}$" if s == 1300 else ""),
                 f"{r.lab_pdc_max_w:.3f}", f"{r.p_1s_max_zc_w:.3f}",
                 f"{int(round(1000 * r.i_mean_zc_a)) + 0:d}".replace("-", "\\ensuremath{-}"),
                 "—" if np.isnan(rig) else f"{rig:.3f}",
                 f"{r.p_1s_max_zc_w / rig:.2f}" if (not np.isnan(rig) and s >= 900) else "—"]
        lines.append(" & ".join(cells) + r" \\")
    (TAB / "jeong_rows.tex").write_text("\n".join(lines) + "\n")
    if DX and DX["DC"]:
        DC, SURF = DX["DC"], DX["SURF"]
        lines = []
        for r in DX["G"]:
            sp = SPECIMENS[r]
            thick = "none" if sp["fuzz_mm"] == 0 else f"\\SI{{{sp['fuzz_mm']:.3f}}}{{mm}}"
            su = SURF.get(r, {})
            pa = f"{su['Pa']:.1f}" if su else "—"
            ra = f"{su['Ra']:.1f}" if su else "—"
            ys = DC["Y"][r]
            mounts = " / ".join(pct(math.expm1(v)) for v in ys)
            if r == "v1_smooth":
                chg = "reference"
            else:
                c = DC["vs_ref"][r]
                chg = f"${pct(c['level'])}$ $[{pct(c['lo'])},\\ {pct(c['hi'])}]$"
            lines.append(" & ".join([latex_label(r), thick, pa, ra, mounts, chg,
                                     f"{DC['p_top'][r]:.2f}"]) + r" \\")
        (TAB / "day_rows.tex").write_text("\n".join(lines) + "\n")
        # appendix: every 1 Oct run, raw arg max per set point
        G = DX["G"]
        keys = [(r, k) for r, ks in G.items() for k in ks]
        allsp = sorted(set().union(*[set(rec[k].fan_rpm_cmd) for _, k in keys]))
        head = ("Fan & $v$ & " + " & ".join(f"\\multicolumn{{2}}{{c}}{{{latex_label(r)}}}" for r in G) + r" \\" + "\n"
                + "".join(f"\\cmidrule(lr){{{3 + 2 * i}-{4 + 2 * i}}}" for i in range(len(G))) + "\n"
                + "rpm & m/s & " + " & ".join("1 & 2" for _ in G) + r" \\" + "\n")
        body = []
        for c in allsp:
            cells = [f"{c}", f"{v_nominal(c):.1f}"]
            for _, k in keys:
                rb = rec[k].set_index("fan_rpm_cmd")
                cells.append(f"{rb.p_raw[c]:.4f}" if c in rb.index else "—")
            body.append(" & ".join(cells) + r" \\")
        (TAB / "day_pmax_table.tex").write_text(
            f"\\begin{{tabular}}{{@{{}}{'rr' + ' rr' * len(G)}@{{}}}}\n\\toprule\n" + head + "\\midrule\n"
            + "\n".join(body) + "\n\\bottomrule\n\\end{tabular}\n")


if __name__ == "__main__":
    main()
