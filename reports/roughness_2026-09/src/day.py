"""The 1 October campaign: every rotor mounted twice on one day, compared with
the un-textured rotor. Called by build_report.main().

Each MOUNTING is one observation. For run j, y_j = mean over the set points
common to every run of ln(P_j / P_ref), where P_ref is the per-set-point
geometric mean of the reference rotor's mountings. The mount-to-mount SD is
pooled within rotors; intervals use t with its degrees of freedom.
"""
import math

import numpy as np
from scipy import stats

DAY = "20261001"
REF = "v1_smooth"
ORDER = ["v1_smooth", "v1_Ra20", "v1_Ra40", "v1_Ra80"]


def groups(runs, repeats, day=DAY):
    """rotor -> its runs on `day`, oldest first."""
    g = {}
    for key, r in runs.items():
        if r["date"] != day:
            continue
        rotor = repeats.get(key, key)
        g.setdefault(rotor, []).append(key)
    for rotor in g:
        g[rotor].sort(key=lambda k: runs[k]["meta"].get("clock", ""))
    return {r: g[r] for r in ORDER if r in g}


def _sp(rec, keys, col):
    return sorted(set.intersection(*[set(rec[k].fan_rpm_cmd) for k in keys]))


def compare(rec, G, col="p_raw"):
    keys = [k for ks in G.values() for k in ks]
    sp = _sp(rec, keys, col)
    lg = {k: np.log(rec[k].set_index("fan_rpm_cmd")[col].reindex(sp).values) for k in keys}
    ref = np.mean([lg[k] for k in G[REF]], axis=0)
    y = {k: float(np.mean(lg[k] - ref)) for k in keys}
    Y = {r: [y[k] for k in ks] for r, ks in G.items()}
    ss = sum(sum((v - np.mean(vs)) ** 2 for v in vs) for vs in Y.values())
    dof = sum(len(vs) - 1 for vs in Y.values())
    sig = math.sqrt(ss / dof)
    t = stats.t.ppf(0.975, dof)

    def ci(a, b):
        d = np.mean(Y[a]) - np.mean(Y[b])
        se = sig * math.sqrt(1 / len(Y[a]) + 1 / len(Y[b]))
        return dict(level=math.expm1(d), lo=math.expm1(d - t * se), hi=math.expm1(d + t * se),
                    resolved=bool(d - t * se > 0 or d + t * se < 0))

    out = dict(sp=sp, sigma=sig, dof=dof, y=y, Y=Y,
               vs_ref={r: ci(r, REF) for r in G if r != REF},
               steps={f"{a}|{b}": ci(b, a) for a, b in zip(ORDER, ORDER[1:]) if a in G and b in G})
    if "v1_Ra20" in G and "v1_Ra80" in G:                  # the span of the textured rotors
        out["steps"]["v1_Ra20|v1_Ra80"] = ci("v1_Ra80", "v1_Ra20")
    # per-set-point mean power per rotor (geometric mean of its mountings)
    out["curve"] = {r: np.exp(np.mean([lg[k] for k in ks], axis=0)) for r, ks in G.items()}
    out["ratio_curve"] = {r: np.exp(np.mean([lg[k] for k in ks], axis=0) - ref) - 1 for r, ks in G.items()}
    out["p_top"] = {r: float(out["curve"][r][-1]) for r in G}
    # mountings that agree with each other: largest within-rotor difference
    out["max_pair_diff"] = max(abs(math.expm1(vs[1] - vs[0])) for vs in Y.values() if len(vs) > 1)
    return out


def thevenin_compare(TH, G):
    """V_oc and R_int of each rotor (mean of its mountings) relative to the
    reference, averaged over set points; plus the per-set-point curves."""
    def mean_curve(keys, col):
        frames = [TH[k].set_index("fan_rpm_cmd")[col] for k in keys]
        sp = sorted(set.intersection(*[set(f.index) for f in frames]))
        return sp, np.exp(np.mean([np.log(f.reindex(sp).values) for f in frames], axis=0))
    out = {}
    for r, ks in G.items():
        sp_r, voc = mean_curve(ks, "v_oc")
        _, rint = mean_curve(ks, "r_int")
        out[r] = dict(sp=sp_r, voc=voc, rint=rint)
    ref = out[REF]
    res = {}
    for r in G:
        if r == REF:
            continue
        sp = sorted(set(out[r]["sp"]) & set(ref["sp"]))
        a = dict(zip(out[r]["sp"], out[r]["voc"])); b = dict(zip(ref["sp"], ref["voc"]))
        c = dict(zip(out[r]["sp"], out[r]["rint"])); d = dict(zip(ref["sp"], ref["rint"]))
        dv = np.log([a[s] / b[s] for s in sp]); dr = np.log([c[s] / d[s] for s in sp])
        t = stats.t.ppf(0.975, len(sp) - 1)
        res[r] = dict(voc=math.expm1(dv.mean()), voc_half=100 * t * dv.std(ddof=1) / math.sqrt(len(sp)),
                      r=math.expm1(dr.mean()), r_half=100 * t * dr.std(ddof=1) / math.sqrt(len(sp)),
                      voc_higher=int((dv > 0).sum()), n=len(sp),
                      curve_sp=sp, curve_voc=np.expm1(dv), curve_r=np.expm1(dr))
    return out, res


def cross_day(rec, G, col="p_raw"):
    """Each textured rotor's first (Aug/Sep) run against its mean on 1 Oct."""
    out = {}
    for r in ("v1_Ra20", "v1_Ra40", "v1_Ra80"):
        if r not in rec or r not in G:
            continue
        sp = _sp(rec, [r] + G[r], col)
        first = np.log(rec[r].set_index("fan_rpm_cmd")[col].reindex(sp).values)
        today = np.mean([np.log(rec[k].set_index("fan_rpm_cmd")[col].reindex(sp).values) for k in G[r]], axis=0)
        out[r] = math.expm1(float(np.mean(today - first)))
    return out
