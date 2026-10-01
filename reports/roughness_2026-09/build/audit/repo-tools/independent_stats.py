#!/usr/bin/env python3
"""
Independent re-derivation of the roughness statistics (repo-tools audit).

Reads the three rig summaries verbatim from logs/ (read-only) and recomputes,
in plain numpy/scipy, what src/compare_blades.py reports, plus:
  - t-based paired LEVEL CI (n-1 dof, back-transformed from log space)
  - per-run power-law fit log P = log a + n log v with SE(n)
  - 3-level monotonic trend count per set point
  - fixed-effects fit log P = c_v + beta log Ra (set-point fixed effects)

Run with the SYSTEM python3 (needs numpy, scipy, pandas).
Writes CSVs next to this script. Changes nothing outside build/.
"""
from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path

import numpy as np
from scipy import stats

REPO = Path("/Users/stepheneacuello/Projects/windtunnel-control")
LOGS = REPO / "logs"
OUT = Path(__file__).resolve().parent
RUNS = {"Ra20": 20.0, "Ra40": 40.0, "Ra80": 80.0}


def read_summary(tag):
    p = LOGS / f"sweep_v1_{tag}_summary.csv"
    meta, body = {}, []
    for line in p.read_text().splitlines(True):
        if line.startswith("#"):
            k, _, v = line[1:].strip().partition(",")
            meta[k.strip()] = v.strip().strip('"')
        else:
            body.append(line)
    rows = list(csv.DictReader(io.StringIO("".join(body))))
    out = {}
    for r in rows:
        rpm = int(float(r["fan_rpm_cmd"]))
        raw = float(r.get("p_max_raw_w") or r.get("p_max_w"))
        fit = float(r["p_max_fit_w"]) if r.get("p_max_fit_w") else None
        out[rpm] = {
            "rpm_cmd": rpm,
            "rpm_act": float(r["fan_rpm_actual"]),
            "wind_summary": float(r["wind_mps"]),
            "raw": raw,
            "fit": fit,
            "clean": r.get("clean"),
        }
    return meta, out


def v_nominal(rpm):
    """docs/09: v = 0.02132 * fan_rpm - 0.424 (tunnel calibration)."""
    return 0.02132 * rpm - 0.424


def ci_t(x, conf=0.95):
    x = np.asarray(x, float)
    n = len(x)
    m = x.mean()
    sd = x.std(ddof=1)
    se = sd / math.sqrt(n)
    t = stats.t.ppf(0.5 + conf / 2, n - 1)
    return m, sd, se, t, (m - t * se, m + t * se)


def compare_blades_replica(pa, pb, va, vb):
    """Exact replica of compare_blades.analyse() + its CI line."""
    v = 0.5 * (np.asarray(va) + np.asarray(vb))
    lr = np.log(np.asarray(pb) / np.asarray(pa))
    x = np.log(v)
    n = len(v)
    slope, icept = np.polyfit(x, lr, 1)
    resid = lr - (icept + slope * x)
    s = math.sqrt(float((resid ** 2).sum()) / max(1, n - 2))
    sxx = float(((x - x.mean()) ** 2).sum())
    se_slope = s / math.sqrt(sxx)
    se_level = s / math.sqrt(n)
    level = float(np.exp(lr.mean()) - 1)
    return {
        "level_pct": 100 * level,
        "ci_lo_pct": 100 * (level - 1.96 * se_level),
        "ci_hi_pct": 100 * (level + 1.96 * se_level),
        "dn": slope, "dn_halfwidth": 1.96 * se_slope, "se_dn": se_slope,
        "scatter_pct": 100 * s,
    }


def powerlaw(v, p):
    x, y = np.log(v), np.log(p)
    res = stats.linregress(x, y)
    n = len(x)
    t = stats.t.ppf(0.975, n - 2)
    yhat = res.intercept + res.slope * x
    r2_lin = 1 - ((p - np.exp(yhat)) ** 2).sum() / ((p - p.mean()) ** 2).sum()
    return {
        "n_exp": res.slope, "se_n": res.stderr,
        "ci_n": (res.slope - t * res.stderr, res.slope + t * res.stderr),
        "a": math.exp(res.intercept), "se_log_a": res.intercept_stderr,
        "r2_log": res.rvalue ** 2, "r2_linear_space": r2_lin,
        "resid_sd_log": math.sqrt(((y - yhat) ** 2).sum() / (n - 2)),
    }


def main():
    data, meta = {}, {}
    for tag in RUNS:
        meta[tag], data[tag] = read_summary(tag)
    rpms = sorted(set.intersection(*(set(d) for d in data.values())))
    res = {"rpms": rpms, "n_setpoints": len(rpms)}

    # ── 0. protocol check ────────────────────────────────────────────
    res["protocols"] = {t: meta[t].get("protocol") for t in RUNS}
    res["protocol_full"] = {t: meta[t].get("protocol_full") for t in RUNS}
    res["clean_all"] = {t: all(data[t][r]["clean"] == "1" for r in rpms)
                        for t in RUNS}

    # ── 1. pairwise paired LEVEL ────────────────────────────────────
    pairs = [("Ra20", "Ra40"), ("Ra20", "Ra80"), ("Ra40", "Ra80")]
    pair_rows = []
    res["pairs"] = {}
    for a, b in pairs:
        for col in ("raw", "fit"):
            if col == "fit" and (data[a][rpms[0]]["fit"] is None
                                 or data[b][rpms[0]]["fit"] is None):
                continue
            pa = np.array([data[a][r][col] for r in rpms])
            pb = np.array([data[b][r][col] for r in rpms])
            va = np.array([data[a][r]["wind_summary"] for r in rpms])
            vb = np.array([data[b][r]["wind_summary"] for r in rpms])
            lr = np.log(pb / pa)
            m, sd, se, t, (lo, hi) = ci_t(lr)
            # also a percent-space t CI on the simple ratio (for reference)
            pct = 100 * (pb / pa - 1)
            pm, psd, pse, pt, (plo, phi) = ci_t(pct)
            wil = stats.wilcoxon(lr)
            n_pos = int((lr > 0).sum())
            sign_p = stats.binomtest(n_pos, len(lr), 0.5).pvalue
            rep = compare_blades_replica(pa, pb, va, vb)
            # dn with nominal (commanded-rpm) wind, common basis for all runs
            x_nom = np.log(v_nominal(np.array(rpms, float)))
            lin = stats.linregress(x_nom, lr)
            key = f"{a}_vs_{b}_{col}"
            d = {
                "n": len(lr),
                "mean_log_ratio": m, "sd_log_ratio": sd, "se_log_ratio": se,
                "t_crit": t,
                "level_pct_geo": 100 * (math.exp(m) - 1),
                "ci95_t_lo_pct": 100 * (math.exp(lo) - 1),
                "ci95_t_hi_pct": 100 * (math.exp(hi) - 1),
                "mean_pct_arith": pm, "ci95_arith_lo": plo, "ci95_arith_hi": phi,
                "n_positive": n_pos, "sign_test_p": sign_p,
                "wilcoxon_p": wil.pvalue,
                "min_pct": float(pct.min()), "max_pct": float(pct.max()),
                "median_pct": float(np.median(pct)),
                "replica": rep,
                "dn_nominal_wind": lin.slope, "se_dn_nominal_wind": lin.stderr,
                "per_setpoint_pct": dict(zip(rpms, pct.round(3).tolist())),
            }
            res["pairs"][key] = d
            pair_rows.append([a, b, col, len(lr), f"{d['level_pct_geo']:.3f}",
                              f"{d['ci95_t_lo_pct']:.3f}", f"{d['ci95_t_hi_pct']:.3f}",
                              f"{rep['level_pct']:.3f}", f"{rep['ci_lo_pct']:.3f}",
                              f"{rep['ci_hi_pct']:.3f}", f"{rep['dn']:.4f}",
                              f"{rep['dn_halfwidth']:.4f}", n_pos,
                              f"{sign_p:.3g}", f"{wil.pvalue:.3g}"])
    with open(OUT / "pairwise_level.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["baseline", "candidate", "power_col", "n",
                    "level_pct_geomean", "ci95_t_lo_pct", "ci95_t_hi_pct",
                    "compare_blades_level_pct", "compare_blades_ci_lo_pct",
                    "compare_blades_ci_hi_pct", "compare_blades_dn",
                    "compare_blades_dn_halfwidth95", "n_setpoints_candidate_higher",
                    "sign_test_p", "wilcoxon_p"])
        w.writerows(pair_rows)

    # ── 2. per-run power law ────────────────────────────────────────
    res["powerlaw"] = {}
    pl_rows = []
    for tag in RUNS:
        for col in ("raw", "fit"):
            if data[tag][rpms[0]][col] is None:
                continue
            p = np.array([data[tag][r][col] for r in rpms])
            for wbasis in ("summary", "nominal_cmd"):
                v = (np.array([data[tag][r]["wind_summary"] for r in rpms])
                     if wbasis == "summary" else v_nominal(np.array(rpms, float)))
                f_ = powerlaw(v, p)
                res["powerlaw"][f"{tag}_{col}_{wbasis}"] = f_
                pl_rows.append([tag, col, wbasis, f"{f_['n_exp']:.4f}",
                                f"{f_['se_n']:.4f}", f"{f_['ci_n'][0]:.4f}",
                                f"{f_['ci_n'][1]:.4f}", f"{f_['a']:.6g}",
                                f"{f_['r2_log']:.5f}", f"{f_['r2_linear_space']:.5f}",
                                f"{100*f_['resid_sd_log']:.3f}"])
    with open(OUT / "powerlaw_per_run.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run", "power_col", "wind_basis", "n_exponent", "se_n",
                    "ci95_lo", "ci95_hi", "a_coeff", "r2_log", "r2_linear",
                    "resid_sd_log_pct"])
        w.writerows(pl_rows)

    # ── 3. monotonic trend ──────────────────────────────────────────
    trend_rows = []
    res["trend"] = {}
    for label, cols in (("raw_all", ("raw", "raw", "raw")),
                        ("Ra20raw_Ra40fit_Ra80fit", ("raw", "fit", "fit"))):
        mono_inc, mono_dec, detail = 0, 0, []
        for r in rpms:
            p20 = data["Ra20"][r][cols[0]]
            p40 = data["Ra40"][r][cols[1]]
            p80 = data["Ra80"][r][cols[2]]
            inc = p20 < p40 < p80
            dec = p20 > p40 > p80
            mono_inc += inc
            mono_dec += dec
            order = "".join(k for k, _ in sorted(
                (("20", p20), ("40", p40), ("80", p80)), key=lambda z: z[1]))
            detail.append((r, p20, p40, p80, inc, order))
            trend_rows.append([label, r, p20, p40, p80, int(inc), order])
        # chance of >= mono_inc increasing orderings among 14 if each of the
        # 6 orderings were equally likely (a crude null, not independent-safe)
        p_null = stats.binomtest(mono_inc, len(rpms), 1 / 6,
                                 alternative="greater").pvalue
        res["trend"][label] = {"n_increasing": mono_inc,
                               "n_decreasing": mono_dec,
                               "n": len(rpms), "p_binom_vs_1of6": p_null,
                               "orders": [d[5] for d in detail]}
    with open(OUT / "trend_by_setpoint.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["power_basis", "fan_rpm_cmd", "P_Ra20_W", "P_Ra40_W",
                    "P_Ra80_W", "monotonic_increasing", "order_low_to_high"])
        w.writerows(trend_rows)

    # ── 4. fixed-effects fit log P = c_v + beta log Ra ─────────────
    res["fe"] = {}
    for label, cols in (("raw_all", ("raw", "raw", "raw")),
                        ("Ra20raw_Ra40fit_Ra80fit", ("raw", "fit", "fit"))):
        y, X = [], []
        tags = list(RUNS)
        for j, tag in enumerate(tags):
            for i, r in enumerate(rpms):
                y.append(math.log(data[tag][r][cols[j]]))
                row = [0.0] * len(rpms)
                row[i] = 1.0
                X.append(row + [math.log(RUNS[tag])])
        y, X = np.array(y), np.array(X)
        beta_hat, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ beta_hat
        n_obs, k = X.shape
        dof = n_obs - k
        s2 = (resid ** 2).sum() / dof
        cov = s2 * np.linalg.inv(X.T @ X)
        b, se_b = beta_hat[-1], math.sqrt(cov[-1, -1])
        t = stats.t.ppf(0.975, dof)
        # run-level (honest) version: the per-run mean log level after
        # removing set-point means, regressed on log Ra: 3 points, 1 dof
        lvl = []
        for j, tag in enumerate(tags):
            lvl.append(np.mean([math.log(data[tag][r][cols[j]]) for r in rpms]))
        lvl = np.array(lvl)
        xr = np.log(np.array([RUNS[t_] for t_ in tags]))
        lr_ = stats.linregress(xr, lvl)
        t1 = stats.t.ppf(0.975, 1)
        # cluster-robust (by run) SE, CR0, only 3 clusters: illustrative only
        XtX_inv = np.linalg.inv(X.T @ X)
        meat = np.zeros((k, k))
        for j in range(3):
            idx = slice(j * len(rpms), (j + 1) * len(rpms))
            g = X[idx].T @ resid[idx]
            meat += np.outer(g, g)
        cov_cl = XtX_inv @ meat @ XtX_inv
        se_cl = math.sqrt(cov_cl[-1, -1])
        res["fe"][label] = {
            "beta": b, "se_beta_ols": se_b, "dof": dof, "t_crit": t,
            "ci95_ols": (b - t * se_b, b + t * se_b),
            "pct_per_doubling_Ra": 100 * (2 ** b - 1),
            "pct_per_doubling_ci_ols": (100 * (2 ** (b - t * se_b) - 1),
                                        100 * (2 ** (b + t * se_b) - 1)),
            "resid_sd_log_pct": 100 * math.sqrt(s2),
            "run_level_beta": lr_.slope, "run_level_se": lr_.stderr,
            "run_level_ci95_t1": (lr_.slope - t1 * lr_.stderr,
                                  lr_.slope + t1 * lr_.stderr),
            "run_level_r2": lr_.rvalue ** 2,
            "run_level_means_log": lvl.tolist(),
            "se_beta_cluster_CR0_3clusters": se_cl,
        }

    # ── 5. fan actual vs commanded (drive-signal convention) ───────
    res["fan_slip"] = {}
    for tag in RUNS:
        d = np.array([data[tag][r]["rpm_act"] - r for r in rpms])
        vs = np.array([data[tag][r]["wind_summary"] for r in rpms])
        vn = v_nominal(np.array(rpms, float))
        res["fan_slip"][tag] = {
            "min_rpm_diff": float(d.min()), "max_rpm_diff": float(d.max()),
            "n_distinct_diffs": int(len(set(d.tolist()))),
            "wind_summary_over_nominal_min_pct": float(100 * (vs / vn - 1).min()),
            "wind_summary_over_nominal_max_pct": float(100 * (vs / vn - 1).max()),
        }

    (OUT / "independent_stats.json").write_text(
        json.dumps(res, indent=2, default=lambda o: o if not isinstance(o, np.generic) else o.item()))
    print(json.dumps(res, indent=2, default=float))


if __name__ == "__main__":
    main()
