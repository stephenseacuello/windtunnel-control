"""Statistics for the 1 October 2026 comparison of four blade sets.

Design: 4 rotors x 2 runs x 14 fan set points. Each rotor was mounted once and
swept twice; the two runs of a rotor share its print and its mounting. The
response is ln(P_max), so differences are ratios.

Model (balanced, nested):  y_rjs = mu + a_r + b_s + (ab)_rs + u_rj + e_rjs
  r rotor (fixed), s set point (fixed), u_rj run offset within rotor, e_rjs residual.
  - Rotor effect: F = MS_R / MS_run(R), i.e. a one-way ANOVA on the run means.
    Checked with an exact permutation test on the eight run means.
  - Rotor x set point interaction: F = MS_RS / MS_E (residual = run x set point
    within rotor). The residual variance differs between set points, so this F
    test is approximate; it is repeated without the two noisiest set points.
Pairwise comparisons use Tukey's HSD on the run means (all six pairs, family-wise
95%). Run-to-run variation is the only replication, so mounting and
print-to-print variation are NOT in these intervals; tipping_point() reports how
much mounting variation each difference could absorb, and drift_model() refits
the run means with a linear time term.

speed() treats T. Kang's light-load rotor speed (one value per set point) the
same way, and checks it against the rig's own record: if it is the light-load
speed and the set points are matched, the terminal voltage at the first load
step divided by it is the generator constant, the same everywhere.
"""
import itertools
import math

import numpy as np
from scipy import stats

import data as D

ALPHA = 0.05


def cube(frames, stems, col, sp):
    """Array [rotor, run, set point] of ln(col) in report order."""
    return np.array([[np.log(frames[k].set_index("fan_rpm_cmd")[col].reindex(sp).values)
                      for k in stems[r]] for r in D.ORDER])


def tukey(yrj):
    """Tukey HSD on run means. yrj: (R, J) array of logs. Returns the pooled
    run-to-run SD (log units), dof, q, half-width and every ordered pair (a, b)
    as b relative to a."""
    R, J = yrj.shape
    m = yrj.mean(axis=1)
    dof = R * (J - 1)
    sigma = math.sqrt(((yrj - m[:, None]) ** 2).sum() / dof)
    q = stats.studentized_range.ppf(1 - ALPHA, R, dof)
    se = sigma / math.sqrt(J)                       # Tukey's SE for equal n
    hw = q * se
    pairs = {}
    for a in range(R):
        for b in range(R):
            if a != b:
                d = m[b] - m[a]
                pairs[(a, b)] = dict(level=math.expm1(d), lo=math.expm1(d - hw), hi=math.expm1(d + hw),
                                     p=float(stats.studentized_range.sf(abs(d) / se, R, dof)),
                                     resolved=bool(abs(d) > hw), d=d)
    return dict(sigma=sigma, dof=dof, q=q, hw=hw, mean=m, pairs=pairs)


def oneway_F(yrj):
    R, J = yrj.shape
    m, g = yrj.mean(axis=1), yrj.mean()
    ss_b = J * ((m - g) ** 2).sum()
    ss_w = ((yrj - m[:, None]) ** 2).sum()
    return (ss_b / (R - 1)) / (ss_w / (R * (J - 1)))


def oneway(yrj):
    R, J = yrj.shape
    F = oneway_F(yrj)
    return dict(F=F, df1=R - 1, df2=R * (J - 1), p=float(stats.f.sf(F, R - 1, R * (J - 1))))


def permutation(yrj):
    """Exact permutation test of the rotor effect: every assignment of the run
    means to rotors, two per rotor; p = share with F at least the observed."""
    R, J = yrj.shape
    vals = yrj.ravel()
    F0 = oneway_F(yrj)
    n_ge = n = 0
    for perm in itertools.permutations(range(R * J)):
        if any(perm[i * J + j] > perm[i * J + j + 1] for i in range(R) for j in range(J - 1)):
            continue                                 # one ordering within each rotor
        n += 1
        n_ge += oneway_F(vals[list(perm)].reshape(R, J)) >= F0 - 1e-12
    return dict(p=n_ge / n, n_ge=n_ge, n=n)


def nested_anova(Y):
    """Balanced rotor x set point design with runs nested in rotors. Y[r, j, s]."""
    R, J, S = Y.shape
    g = Y.mean()
    m_r, m_s = Y.mean(axis=(1, 2)), Y.mean(axis=(0, 1))
    m_rs, m_rj = Y.mean(axis=1), Y.mean(axis=2)
    resid = Y - m_rs[:, None, :] - m_rj[:, :, None] + m_r[:, None, None]
    ss = dict(R=J * S * ((m_r - g) ** 2).sum(), S=R * J * ((m_s - g) ** 2).sum(),
              RS=J * ((m_rs - m_r[:, None] - m_s[None, :] + g) ** 2).sum(),
              J=S * ((m_rj - m_r[:, None]) ** 2).sum(), E=(resid ** 2).sum())
    df = dict(R=R - 1, S=S - 1, RS=(R - 1) * (S - 1), J=R * (J - 1), E=R * (J - 1) * (S - 1))
    ms = {k: ss[k] / df[k] for k in ss}
    against = dict(R="J", S="E", RS="E", J="E")
    out = {}
    for k in ss:
        row = dict(ss=ss[k], df=df[k], ms=ms[k])
        if k in against:
            den = against[k]
            row.update(F=ms[k] / ms[den], df_den=df[den], p=float(stats.f.sf(ms[k] / ms[den], df[k], df[den])))
        out[k] = row
    out["sigma_e"] = math.sqrt(ms["E"])                     # per-point residual SD (log)
    out["sd_by_setpoint"] = np.sqrt((resid ** 2).sum(axis=(0, 1)) / (R * (J - 1)))
    return out


def tipping_point(d, sigma, crit):
    """Largest mounting SD tau (log units) for which a difference d of two rotor
    means stays resolved by the same criterion as the Tukey intervals: with one
    independent mounting offset per rotor, Var(difference) = sigma^2 + 2 tau^2,
    and the difference stays resolved while |d| > crit * sqrt(sigma^2 + 2 tau^2),
    crit = q_{0.05;R,dof} / sqrt(2)."""
    x = (abs(d) / crit) ** 2 - sigma ** 2
    return math.sqrt(x / 2) if x > 0 else float("nan")


def drift_model(yrj, t_h):
    """y_rj = a_r + beta * t_rj by least squares (t in hours). Returns beta and the
    drift-adjusted change of each rotor relative to the first, with t intervals."""
    R, J = yrj.shape
    X = np.zeros((R * J, R + 1))
    for r in range(R):
        X[r * J:(r + 1) * J, r] = 1
    X[:, R] = t_h.ravel()
    y = yrj.ravel()
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    dof = R * J - (R + 1)
    s2 = ((y - X @ coef) ** 2).sum() / dof
    cov = s2 * np.linalg.inv(X.T @ X)
    t = stats.t.ppf(0.975, dof)
    out = dict(dof=dof, beta=coef[R], beta_lo=coef[R] - t * math.sqrt(cov[R, R]),
               beta_hi=coef[R] + t * math.sqrt(cov[R, R]), change={})
    for b in range(1, R):
        c = np.zeros(R + 1); c[b], c[0] = 1, -1
        est, se = c @ coef, math.sqrt(c @ cov @ c)
        out["change"][b] = dict(level=math.expm1(est), lo=math.expm1(est - t * se), hi=math.expm1(est + t * se))
    return out


def steepest_segment(Y, v):
    """Per run: midpoint wind speed and slope of the steepest segment of ln P
    against ln v. Resolution is one set-point spacing."""
    lv = np.log(v)
    slope = np.diff(Y, axis=2) / np.diff(lv)
    k = slope.argmax(axis=2)
    return (v[k] + v[k + 1]) / 2, slope.max(axis=2)            # each [rotor, run]


def analyse(P, T, stems, sp, t_start_h):
    """P, T: per-run peak and Thevenin frames keyed by stem. stems: {specimen: [run1, run2]}.
    t_start_h: [rotor, run] start time of each run in hours."""
    v = D.wind(sp)
    A = {}

    # peak power: rotor comparison on run means
    Y = cube(P, stems, "p_max_w", sp)
    ref = Y[0].mean(axis=0)                                  # Plain, geometric mean of runs
    yrj = (Y - ref).mean(axis=2)
    A["Y"], A["yrj"] = Y, yrj
    A["tk"] = tukey(yrj)
    A["oneway"] = oneway(yrj)
    A["perm"] = permutation(yrj)
    crit = A["tk"]["q"] / math.sqrt(2)
    A["tau"] = {pair: tipping_point(c["d"], A["tk"]["sigma"], crit) for pair, c in A["tk"]["pairs"].items()}
    A["drift"] = drift_model(yrj, t_start_h)
    Yf = cube(P, stems, "p_fit_w", sp)
    A["tk_fit"] = tukey((Yf - Yf[0].mean(axis=0)).mean(axis=2))

    # dependence on wind speed
    A["anova"] = nested_anova(Y)
    A["anova_tex"] = nested_anova(Y[1:])                     # textured rotors only
    noisy = np.argsort(A["anova"]["sd_by_setpoint"])[-2:]
    keep = [i for i in range(len(sp)) if i not in noisy]
    A["trim_dropped"] = sorted(sp[i] for i in noisy)
    A["anova_trim"] = nested_anova(Y[:, :, keep])
    A["gain_run"] = np.expm1(Y - ref)                        # [r, j, s]
    A["gain"] = np.expm1(Y.mean(axis=1) - ref)               # [r, s]
    A["curve"] = np.exp(Y.mean(axis=1))                      # geometric-mean P_max [r, s]
    # pointwise 95% half-width for a rotor-vs-Plain difference at one set point,
    # from the within-rotor run-to-run SD at that set point (4 dof)
    sd_run_s = np.sqrt(((Y - Y.mean(axis=1, keepdims=True)) ** 2).sum(axis=(0, 1)) / (Y.shape[0] * (Y.shape[1] - 1)))
    A["band_hw"] = stats.t.ppf(0.975, Y.shape[0] * (Y.shape[1] - 1)) * sd_run_s     # log units
    A["step_v"], A["step_slope"] = steepest_segment(Y, v)
    A["cp"] = A["curve"] / (0.5 * D.RHO_STD * D.AREA_M2 * v ** 3)

    # Thevenin source: V_oc and R_int
    for col, key in (("v_oc_v", "voc"), ("r_int_ohm", "rint")):
        X = cube(T, stems, col, sp)
        xr = X[0].mean(axis=0)
        A[key + "_rj"] = (X - xr).mean(axis=2)
        A["tk_" + key] = tukey(A[key + "_rj"])
        A[key + "_gain"] = np.expm1(X.mean(axis=1) - xr)
        A[key + "_curve"] = np.exp(X.mean(axis=1))
        A["anova_" + key] = nested_anova(X)
    A["thev_r2_min"] = min(float(T[k].r2.min()) for ks in stems.values() for k in ks)
    ratio = [T[k].set_index("fan_rpm_cmd").p_matched_w.reindex(sp).values /
             P[k].set_index("fan_rpm_cmd").p_max_w.reindex(sp).values for ks in stems.values() for k in ks]
    A["match_lo"], A["match_hi"] = float(np.min(ratio)), float(np.max(ratio))

    # session checks
    A["plain_pair"] = math.expm1(yrj[0, 1] - yrj[0, 0])
    fan = np.array([[P[k].set_index("fan_rpm_cmd").fan_motor_a.reindex(sp).values for k in stems[r]]
                    for r in D.ORDER]).reshape(-1, len(sp))
    A["fan_range_a"] = float((fan.max(axis=0) - fan.min(axis=0)).max())
    A["fan_top_a"] = float(np.median(fan[:, -1]))
    return A


def speed(S, P, stems, sp, T):
    """S: T. Kang's per-run rotor speed frames keyed by stem; P: the peak frames
    (for the first-step voltage V1). The protocol releases the load (0 A) while the
    fan settles, except at the first set point, which settles with the load armed:
    n0 there is not a light-load speed, so the analysis uses sp[1:]. Light-load
    speed n0 is compared between rotors as P_max is; lam is the light-load
    tip-speed ratio; ke = V1/n0 (V per rpm)."""
    A = {}
    N_all = np.exp(cube(S, stems, "rotor_rpm", sp))           # every set point, for tables
    V1_all = np.exp(cube(P, stems, "v_first_v", sp))
    A["n_all"], A["v1_all"] = N_all, V1_all
    use = sp[1:]
    A["sp"], v = use, D.wind(use)
    Y = np.log(N_all[:, :, 1:])
    ref = Y[0].mean(axis=0)
    A["Y"], A["yrj"] = Y, (Y - ref).mean(axis=2)
    A["tk"] = tukey(A["yrj"])
    A["oneway"] = oneway(A["yrj"])
    A["perm"] = permutation(A["yrj"])
    A["anova"] = nested_anova(Y)
    A["gain_run"] = np.expm1(Y - ref)                        # [r, j, s]
    A["gain"] = np.expm1(Y.mean(axis=1) - ref)               # [r, s]
    A["n"], A["curve"] = np.exp(Y), np.exp(Y.mean(axis=1))   # rpm; geometric mean of runs
    omega_r = lambda n: 2 * math.pi * n / 60 * D.R_M        # blade speed at R (m/s)
    A["lam"], A["lam_curve"] = omega_r(A["n"]) / v, omega_r(A["curve"]) / v
    A["lam_all"] = omega_r(N_all) / D.wind(sp)
    V1 = V1_all[:, :, 1:]
    A["v1"], A["ke"] = V1, V1 / A["n"]
    lk = np.log(A["ke"])
    A["tk_ke"] = tukey((lk - lk[0].mean(axis=0)).mean(axis=2))     # does V1/n0 differ between rotors?
    # V_oc on the same set points: its change, V_oc/n0 between rotors, and V_oc against V1
    Voc = np.exp(cube(T, stems, "v_oc_v", use))
    A["tk_voc"] = tukey((np.log(Voc) - np.log(Voc[0]).mean(axis=0)).mean(axis=2))
    lv = np.log(Voc / A["n"])
    A["tk_vocn"] = tukey((lv - lv[0].mean(axis=0)).mean(axis=2))
    A["voc_below_v1"] = 1 - Voc / V1                                  # [r, j, s]
    # V1 is continuous, so it is the check on calls that the quantised n0 makes
    A["tk_v1"] = tukey((np.log(V1) - np.log(V1[0]).mean(axis=0)).mean(axis=2))
    # repeat runs that give the same quantised n0 share its quantisation error
    A["n_same"] = int((np.abs(Y[:, 0] - Y[:, 1]) < 1e-12).sum())
    A["n_pairs"] = int(Y.shape[0] * Y.shape[2])
    x, y = A["n"].ravel(), V1.ravel()
    slope, icept = np.polyfit(x, y, 1)
    A["fit"] = dict(slope=slope, icept=icept)
    # first set point: n0 against the speed V1 implies on that line
    A["first_gap"] = (V1_all[:, :, 0] - icept) / slope / N_all[:, :, 0] - 1     # [r, j]
    return A
