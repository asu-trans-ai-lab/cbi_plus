# -*- coding:utf-8 -*-
"""QVDF turn-key pipeline — core model (S3 / PAQ / QVDF) + robust IO adapters."""
import os, json
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
import config as C

COMMON_COLS = ["link_id", "date", "t_min", "weekday", "speed", "flow_pl", "lanes", "length"]


# ============================ S3 fundamental diagram ========================
def s3_speed(k, vf, kc, m):
    return vf / np.power(1 + np.power(k / kc, m), 2.0 / m)


def inverse_s3_flow(v, vf, kc, m):
    v = np.clip(v, 1.0, 0.99 * vf)
    ratio = np.maximum(np.power(vf / v, m / 2.0) - 1.0, 1e-8)
    return np.minimum(kc * np.power(ratio, 1.0 / m) * v, kc * vf)


def fit_s3(g, vf_fixed, capacity_prior, log):
    """Outer-layer S3 fit with v_f fixed; returns FD dict or a prior-based fallback.
    Never raises — on any failure it logs and returns the prior FD."""
    def _prior(reason):
        m = 4.0; uc = vf_fixed / 2 ** (2 / m)
        log.debug(f"    S3 fallback to prior ({reason}): cap={capacity_prior}")
        return dict(vf=vf_fixed, kc=capacity_prior / uc, m=m, uc=uc, cap=capacity_prior, source="prior")
    try:
        g = g[(g.speed > 0) & (g.flow_pl > 0)].copy()
        g["density"] = g.flow_pl / g.speed
        g = g[(g.density >= 1.0) & (g.density < 220)]
        if len(g) < 30:
            return _prior("few points")
        X, Y = [], []
        step = max(1, int((g.speed.max() - g.speed.min()) / 20))
        for lo in range(0, int(np.ceil(g.speed.max())) + step, step):
            seg = g[(g.speed >= lo) & (g.speed < lo + step)]
            if len(seg) == 0:
                continue
            Y.append(seg.speed.mean())
            thr = seg.density.quantile(C.OUTER_Q)
            hi = seg[seg.density >= thr].density
            X.append(hi.mean() if len(hi) else seg.density.mean())
        X, Y = np.array(X), np.array(Y)
        if len(X) < 4:
            return _prior("few bins")
        f2 = lambda k, kc, m: s3_speed(k, vf_fixed, kc, m)
        (kc, m), _ = curve_fit(f2, X, Y, p0=[min(max(g.density.max() * 0.3, 10), 100), 5],
                               bounds=([10, 1.0], [100, 12]), maxfev=6000)
        uc = vf_fixed / 2 ** (2 / m)
        cap = uc * kc
        # sanity gate: reject implausible capacity / speed-at-capacity
        if not (700 < cap < 2800 and 25 < uc < vf_fixed):
            return _prior(f"implausible cap={cap:.0f} uc={uc:.0f}")
        return dict(vf=vf_fixed, kc=kc, m=m, uc=uc, cap=cap, source="fit")
    except Exception as e:
        return _prior(f"exc {type(e).__name__}")


# ============================ PAQ per (link, date, period) ==================
def smooth_speed(spd_raw):
    """centered rolling-mean smoothing used for t0/t2/t3 identification."""
    return pd.Series(spd_raw).rolling(C.VT2_SMOOTH, center=True, min_periods=1).mean().to_numpy()


def _interp_cross(tm, spd, ia, ib, cutoff):
    """time (minutes) where the smoothed speed crosses the cut-off between indices ia, ib."""
    sa, sb = spd[ia], spd[ib]
    if sb == sa:
        return float(tm[ib])
    frac = float(np.clip((cutoff - sa) / (sb - sa), 0.0, 1.0))
    return float(tm[ia] + frac * (tm[ib] - tm[ia]))


def _assign_period(t2_hour):
    for per, (lo, hi) in C.PERIODS.items():
        if lo / 60.0 <= t2_hour < hi / 60.0:
            return per
    return None


def find_episodes(spd, tm, fpl, cutoff):
    """Detect ALL congestion episodes over the wide search window using a sustained +-30 min
    crossing (hysteresis): an episode is a below-cut-off run that is NOT ended by an above-cut-off
    blip shorter than HYST_MIN; t0/t3 are the linearly-interpolated cut-off intersections (so the
    window is never clipped by a period boundary). Returns a list of (t0,t3,imin,i_start,i_end)."""
    n = len(spd)
    hyst = max(1, int(round(C.HYST_MIN / C.DT_MIN)))
    eps = []
    i = 0
    while i < n:
        if spd[i] < cutoff:
            start = i
            j = i
            while j < n - 1:                               # extend until sustained recovery
                if spd[j + 1] >= cutoff and np.all(spd[j + 1:min(j + 1 + hyst, n)] >= cutoff):
                    break
                j += 1
            end = j
            t0 = _interp_cross(tm, spd, start - 1, start, cutoff) if start > 0 else float(tm[0])
            t3 = _interp_cross(tm, spd, end, end + 1, cutoff) if end < n - 1 else float(tm[-1])
            imin = start + int(np.argmin(spd[start:end + 1]))
            eps.append((t0, t3, imin, start, end))
            i = end + 1
        else:
            i += 1
    return eps


def paq_episodes(g, fd, cutoff, _period_window=None):
    """One link's per-interval data -> PAQ episode rows over the WIDE window, each tagged with the
    period its trough t2 falls in. Returns list of dict rows (>=1 per congested day, e.g. AM+PM)."""
    cap, uc, vf = fd["cap"], fd["uc"], fd["vf"]
    lo, hi = C.WIDE_WINDOW
    rows = []
    gp = g[(g.t_min >= lo) & (g.t_min < hi)]
    for date, gd in gp.groupby("date"):
        gd = gd.sort_values("t_min")
        spd_raw = gd.speed.to_numpy(); tm = gd.t_min.to_numpy(); fpl = gd.flow_pl.to_numpy()
        if len(spd_raw) < 8:
            continue
        spd = smooth_speed(spd_raw)
        totD = float((fpl * (C.DT_MIN / 60.0)).sum())
        base = dict(link_id=gd.link_id.iloc[0], date=str(date), weekday=int(gd.weekday.iloc[0]),
                    cutoff=cutoff, cap=cap, uc=uc, vf=vf, length=gd.length.iloc[0])
        eps = find_episodes(spd, tm, fpl, cutoff)
        # keep only episodes whose trough falls in a defined period and that are long enough
        kept = []
        for (t0, t3, imin, i0, i3) in eps:
            t2 = tm[imin] / 60.0; per = _assign_period(t2)
            if per is None or (t3 - t0) / 60.0 < C.MIN_EPISODE_H:
                continue
            mask = (tm >= t0) & (tm <= t3)               # t0,t3 are in MINUTES (from find_episodes)
            D = float((fpl[mask] * (C.DT_MIN / 60.0)).sum())
            vt2 = float(spd[imin]); P = (t3 - t0) / 60.0
            kept.append(dict(base, period=per, P=P, demand=D, DC=min(D / cap, C.DOC_MAX),
                             v_t2=vt2, t2=t2, t0=t0 / 60.0, t3=t3 / 60.0,
                             qdf=(D / totD) if totD > 0 else 0.0,
                             cd_mean_speed=float(spd[mask].mean()) if mask.any() else vt2,
                             magnitude=(cutoff / vt2 - 1) if vt2 > 0 else 0.0,
                             m=(t2 - t0 / 60.0) / P if P > 0 else 0.5))
        if kept:
            rows += kept
        else:
            # uncongested day: emit one P=0 row per defined period so Table 6 day-counts are right
            for per in C.PERIODS:
                rows.append(dict(base, period=per, P=0.0, demand=totD, DC=min(totD / cap, C.DOC_MAX),
                                 v_t2=float(spd.min()), t2=float(tm[int(np.argmin(spd))] / 60.0),
                                 t0=0.0, t3=0.0, qdf=1.0, cd_mean_speed=float(spd.mean()),
                                 magnitude=0.0, m=np.nan))
    return rows


# ============================ paper-aligned calibration =====================
def _pw(x, a, b):
    return a * np.power(x, b)


def calibrate_link(dd, cutoff, log):
    """Paper recipe: trim P<=mean+std, pivot by P, curve_fit on the means. Returns dict or None."""
    try:
        # STAGE 1 (f_d, n: P = f_d*(D/C)^n) needs a reliable D/C -> exclude D/C-CENSORED episodes
        # (D/C pinned at the cap = an all-day saturated bottleneck whose demand is unobservable).
        s1 = dd[(dd.P > 0) & (dd.DC < C.DOC_MAX - 0.01) & (dd.P <= 8.0)].copy()
        if len(s1) < C.MIN_CONG_DAYS:                      # thin/saturated corridor fallback
            s1 = dd[(dd.P > 0) & (dd.P <= 12.0)].copy()
        # STAGE 2 (f_p, s: magnitude = f_p*P^s) is fit on the SAME clean (non-censored, short-P)
        # links -- including the all-day-saturated long-P links here inverts the P<->magnitude
        # relationship (long P but MILD dip) and drives a degenerate fit (f_p->0 or s at a bound).
        # Those saturated links are FLAGGED in the figures instead (V_t2 gate), not modeled.
        ncong = len(s1)
        if ncong < C.MIN_CONG_DAYS:
            return None
        s1 = s1[s1.P <= s1.P.mean() + s1.P.std()]          # paper trim
        p0 = s1.groupby(s1.P.round(4)).DC.mean()
        p1 = s1.groupby(s1.P.round(4)).magnitude.mean().clip(lower=0)
        if len(p0) < 3 or len(p1) < 3:
            return None
        lb, ub = C.PARAM_BOUNDS
        f_d, n = curve_fit(_pw, p0.values, p0.index.values, bounds=([lb, lb], [ub, ub]), maxfev=6000)[0]
        f_p, s = curve_fit(_pw, p1.index.values, p1.values, bounds=([lb, lb], [ub, ub]), maxfev=6000)[0]
        alpha = (8.0 / 15.0) * f_p * f_d ** s
        beta = n * s
        at_bound = any(abs(v - ub) < 0.05 or v < 0.02 for v in (f_d, n, f_p, s))
        rel = ("high" if ncong >= C.HIGH_REL_DAYS and not at_bound
               else ("low" if ncong < C.MIN_CONG_DAYS + 4 or at_bound else "medium"))
        return dict(f_d=f_d, n=n, f_p=f_p, s=s, alpha=alpha, beta=beta,
                    n_cong=ncong, reliability=rel, at_bound=at_bound)
    except Exception as e:
        log.debug(f"    calibrate fail: {type(e).__name__} {e}")
        return None


def shrink_params(params_by_link, log):
    """James-Stein style shrink of low/medium-reliability links toward the corridor median."""
    if not params_by_link:
        return params_by_link
    keys = ["f_d", "n", "f_p", "s"]
    med = {k: float(np.median([p[k] for p in params_by_link.values()])) for k in keys}
    for lid, p in params_by_link.items():
        a = p["n_cong"] / (p["n_cong"] + C.SHRINK_K0)
        if p["reliability"] != "high":
            for k in keys:
                p[k + "_raw"] = p[k]
                p[k] = a * p[k] + (1 - a) * med[k]
            p["alpha"] = (8.0 / 15.0) * p["f_p"] * p["f_d"] ** p["s"]
            p["beta"] = p["n"] * p["s"]
            p["shrunk"] = True
        else:
            p["shrunk"] = False
    log.info(f"    corridor median f_d={med['f_d']:.2f} n={med['n']:.2f} "
             f"f_p={med['f_p']:.2f} s={med['s']:.2f} (shrink applied to non-high links)")
    return params_by_link


# ============================ QVDF gamma + td speed =========================
def gamma_of(p, dc, mu, length, uc):
    P = p["f_d"] * dc ** p["n"]
    return 64.0 * mu * (length / uc) * p["f_p"] * np.power(max(P, 1e-3), p["s"] - 4.0)


def predict_vt2(cutoff, f_p, s, P):
    """QVDF predicted lowest speed V_t2 = v_co / (1 + f_p * P^s). By the step-2 calibration of
    (f_p, s) this matches the OBSERVED lowest speed -- that is the design of the boxing of f_p/s."""
    return float(np.clip(cutoff / (1.0 + f_p * max(P, 1e-3) ** s), 1.0, cutoff))


def td_speed_shape(t0, t2, t3, vt2, cutoff, vf, window):
    """QVDF queue curve: v(t0)=v(t3)=cut-off, dipping to the MODEL V_t2 (= v_co/(1+f_p P^s), passed in
    by the caller) at the OBSERVED trough TIME t2 (asymmetric -- the trough sits at the actual
    lowest-speed time, not the symmetric midpoint), with free-flow ramps outside. The depth is the
    calibrated prediction; only the trough TIME is taken from observation."""
    lo, hi = window[0] / 60.0, window[1] / 60.0
    ts = np.arange(window[0], window[1], C.DT_MIN) / 60.0
    vt2 = float(np.clip(vt2, 1.0, cutoff))
    t2 = min(max(t2, t0 + 1e-3), t3 - 1e-3)               # keep the trough strictly inside [t0,t3]
    out = []
    for t in ts:
        if t0 <= t <= t3:
            x = (t - t0) / (t2 - t0) if t <= t2 else (t3 - t) / (t3 - t2)
            x = min(max(x, 0.0), 1.0)
            v = cutoff - (cutoff - vt2) * (x * x * (3.0 - 2.0 * x))   # smoothstep: flat at t0/t3 & trough
        elif t < t0:
            v = vf - (vf - cutoff) * ((t - lo) / max(0.01, t0 - lo))
        else:
            v = cutoff + (vf - cutoff) * ((t - t3) / max(0.01, hi - t3))
        out.append(max(0.0, min(v, vf)))
    return ts, np.array(out)


# ============================ per-period QVDF full-day reconstruction =======
# On a corridor that stays below the cut-off all day, a SINGLE whole-day queue (td_speed_shape over one
# wide episode) merges AM+MD+PM into one trough and misses the morning dip. These build the full-day
# model PER PERIOD -- calibrate f_p/s within each period, place each period's trough at its observed
# local-min time with the QVDF depth predict_vt2 (depth is model-predicted, NOT observed), and stitch
# the periods, anchored at the boundaries to the observed shoulder (capped at observed free-flow).
def period_windows(t0_min, t1_min):
    """contiguous AM/MD/PM partition of [t0_min, t1_min] using the config.PERIODS boundaries (only the
    outer edges are clipped to the analysis window)."""
    pers = list(C.PERIODS.items())
    out = []
    for i, (per, (lo, hi)) in enumerate(pers):
        ws = t0_min if i == 0 else lo
        we = t1_min if i == len(pers) - 1 else hi
        out.append((per, int(ws), int(we)))
    return out


def _smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def calibrate_perperiod(profiles, windows, default=None, min_links=4):
    """Fit the QVDF Stage-2 relationship magnitude = f_p * P^s WITHIN each period across links -- the
    same power-law form (_pw), bounds (PARAM_BOUNDS) and magnitude definition (cutoff/V_t2 - 1) as
    calibrate_link, restricted to a single period window. `profiles` is a list of (tm, smoothed_speed,
    cutoff) per link. A period with < min_links congested links falls back to `default` (a dict with
    f_p, s; defaults to config.DEFAULT_QVDF -- pass the facility-type x area-type default for general
    cases). Returns {per: (f_p, s)}."""
    d = default or C.DEFAULT_QVDF
    lb, ub = C.PARAM_BOUNDS
    params = {}
    for per, ws, we in windows:
        Ps, mags = [], []
        for tm, sm, cut in profiles:
            m = (tm >= ws) & (tm < we)
            v = np.asarray(sm, float)[m]
            v = v[np.isfinite(v)]
            if len(v) < 3 or not (v < cut).any():
                continue
            P = float((v < cut).sum()) * (C.DT_MIN / 60.0)
            vt2 = float(v.min())
            if vt2 <= 0 or P <= 0:
                continue
            Ps.append(P); mags.append(max(cut / vt2 - 1.0, 0.0))
        if len(Ps) >= min_links:
            try:
                (fp, s), _ = curve_fit(_pw, np.array(Ps), np.array(mags),
                                       bounds=([lb, lb], [ub, ub]), maxfev=8000)
                params[per] = (float(fp), float(s)); continue
            except Exception:
                pass
        params[per] = (float(d["f_p"]), float(d["s"]))
    return params


def stitch_fullday_model(tm, sm, cutoff, ff, params, windows):
    """One link's full-day model: a QVDF trough per period (trough TIME = deepest within-window episode
    from find_episodes; DEPTH = predict_vt2 with the within-period f_p/s and P), stitched with the
    boundaries anchored to the observed shoulder speed (capped at observed free-flow ff). Returns a
    model-speed array aligned to tm."""
    tm = np.asarray(tm, float); sm = np.asarray(sm, float)
    ff = float(ff) if np.isfinite(ff) else float(np.nanmax(sm))
    anchors = [(float(tm[0]), min(float(sm[0]), ff))]
    for per, ws, we in windows:
        m = (tm >= ws) & (tm < we)
        if not m.any():
            continue
        st, sv = tm[m], sm[m]
        if float(np.nanmin(sv)) < cutoff:
            eps = find_episodes(sv, st, np.zeros_like(sv), cutoff)
            if eps:
                imin = min(eps, key=lambda e: sv[e[2]])[2]      # deepest within-window episode
            else:
                imin = int(np.nanargmin(sv))
            t2 = float(st[imin])
            P = float((sv < cutoff).sum()) * (C.DT_MIN / 60.0)
            fp, s = params.get(per, (C.DEFAULT_QVDF["f_p"], C.DEFAULT_QVDF["s"]))
            anchors.append((t2, predict_vt2(cutoff, fp, s, P)))
        anchors.append((min(float(we), float(tm[-1])), min(float(sv[-1]), ff)))
    anchors.append((float(tm[-1]), min(float(sm[-1]), ff)))
    seen, uni = set(), []
    for t, v in sorted(anchors):
        r = int(round(t))
        if r not in seen:
            seen.add(r); uni.append((float(r), v))
    model = np.interp(tm, [a[0] for a in uni], [a[1] for a in uni])
    for (ta, va), (tb, vb) in zip(uni[:-1], uni[1:]):
        seg = (tm >= ta) & (tm <= tb)
        if seg.any() and tb > ta:
            model[seg] = va + (vb - va) * _smoothstep((tm[seg] - ta) / (tb - ta))
    return np.clip(model, 1.0, ff)


def td_speed_profile(t0, t3, dc, f_d, n, f_p, s, cutoff, uf, L, cap, window):
    """QVDF time-dependent speed v(t), ported from the original VDF.calculate_travel_time_based_on
    _QVDF so the modeled trough EQUALS the calibrated V_t2 (= cut-off/(1+f_p*P^s)) at the window
    midpoint -- i.e. modeled lowest speed = observed lowest speed by construction:
        P    = t3 - t0                                        (observed congestion duration)
        V_t2 = cut-off / (1 + f_p * P^s)                      (= observed by f_p/s calibration)
        RTT  = L / cut-off ;  mu = min(cap, D/P)
        wt2  = L/V_t2 - RTT ;  gamma = 64 * wt2 * mu / P^4    (derived to hit V_t2, NOT uc)
        inside [t0,t3]:  q(t) = 0.25 gamma (t-t0)^2 (t-t3)^2 ; v(t) = L / (q/mu + RTT)
        outside:  linear ramp uf <-> cut-off.
    v(t0)=v(t3)=cut-off and v(midpoint)=V_t2 exactly. t0/t3 in HOURS, window in MINUTES."""
    lo, hi = window[0] / 60.0, window[1] / 60.0
    ts = np.arange(window[0], window[1], C.DT_MIN) / 60.0
    P = max(t3 - t0, 0.1)
    vt2 = predict_vt2(cutoff, f_p, s, P)
    RTT = L / cutoff
    mu = max(min(cap, dc * cap / P), 1e-3)
    wt2 = max(L / vt2 - RTT, 0.0)
    gamma = 64.0 * wt2 * mu / P ** 4
    out = []
    for t in ts:
        if t0 <= t <= t3:
            q = 0.25 * gamma * (t - t0) ** 2 * (t - t3) ** 2
            v = L / (q / mu + RTT)
        elif t < t0:
            v = uf - (uf - cutoff) * ((t - lo) / max(0.01, t0 - lo))
        else:
            v = cutoff + (uf - cutoff) * ((t - t3) / max(0.01, hi - t3))
        out.append(max(0.0, min(v, uf)))
    return ts, np.array(out)


# ===================== time-dependent volume + D-conservation ===============
def td_volume_from_speed(v_t, fd):
    """Back-compute per-lane time-dependent flow q(t) (veh/h/lane) from the QVDF
    time-dependent speed v(t) using the S3 inverse FD. No conservation yet."""
    return inverse_s3_flow(np.asarray(v_t, dtype=float), fd["vf"], fd["kc"], fd["m"])


def conserve_td_volume(v_t, fd, D_per_lane, dt_hr, cap=None, max_iter=80, tol=1e-6):
    """Enforce demand conservation on the S3-back-computed time-dependent volume.

    The per-5/15-min model speed v(t) over the congestion duration gives, via the
    S3 inverse, a per-lane flow q0(t). Independently inverting each interval does
    NOT guarantee the cumulative count equals the demand discharged in the queue,
    D = mu * P. We restore that with a Lagrangian multiplier lambda on the single
    equality constraint  sum_t q(t)*dt = D , keeping q(t) closest (L2) to q0(t)
    inside the physical box [0, capacity]:

        min_q  0.5 * sum (q(t) - q0(t))^2     s.t.  sum_t q(t)*dt = D , 0<=q<=cap
        =>     q(t) = clip( q0(t) + lambda , 0 , cap )

    The dual variable lambda is found by dual ascent (bisection: the clipped sum
    is monotone non-decreasing in lambda). Returns (q_adj, lambda, achieved_D).
    This is the iterative Lagrangian step that makes the time-dependent profile
    consistent with the total incoming demand D within the congestion duration."""
    q0 = inverse_s3_flow(np.asarray(v_t, dtype=float), fd["vf"], fd["kc"], fd["m"])
    qcap = float(cap if cap is not None else fd.get("cap", fd["kc"] * fd["vf"]))
    target_sum = D_per_lane / max(dt_hr, 1e-9)        # sum_t q(t) must equal this
    if len(q0) == 0:
        return q0, 0.0, 0.0
    lo, hi = -qcap, qcap
    lam = 0.0
    for _ in range(max_iter):
        lam = 0.5 * (lo + hi)
        s = float(np.clip(q0 + lam, 0.0, qcap).sum())
        if abs(s - target_sum) <= tol * max(target_sum, 1.0):
            break
        if s < target_sum:
            lo = lam
        else:
            hi = lam
    q_adj = np.clip(q0 + lam, 0.0, qcap)
    return q_adj, lam, float(q_adj.sum() * dt_hr)


# ============== demand-conserving flow-speed function q(t)=theta*g(v(t)) =====
def fd_shape(v, vf, m=6.0, form="s3"):
    """Separable FD SHAPE g(v): the speed-dependent factor of flow, q(v)=theta*g(v).
       Greenshields: g(v)=v*(1-v/vf)            (theta = jam density k_j)
       S3:           g(v)=v*((vf/v)^(m/2)-1)^(1/m) (theta = density-at-capacity k_c)
    g(v)>=0 on [0,vf] and g(vf)=0, so a single positive scale theta keeps q>=0."""
    v = np.clip(np.asarray(v, dtype=float), 1e-6, vf)
    if form == "greenshields":
        return v * (1.0 - v / vf)
    return v * np.power(np.maximum((vf / v) ** (m / 2.0) - 1.0, 0.0), 1.0 / m)  # s3


def flow_from_speed_conserving(v_t, vf, D, dt_hr, m=6.0, form="s3"):
    """Time-dependent per-lane flow q(t) from speed v(t) that ALWAYS satisfies the
    conservation constraint sum_t q(t)*dt = D, by construction:

        q(t) = theta * g(v(t)) ,   theta = D / (dt * sum_t g(v(t)))

    The FD shape g(v) (Greenshields or S3) fixes the PROFILE from the speed; the
    single density-scale theta (= k_j / k_c, the calibrated density level, i.e. the
    implied capacity) is solved in closed form to meet total demand D. No iteration,
    no clipping -- the equality sum q*dt = D is an identity. Returns (q, theta,
    capacity_implied). capacity_implied = theta * max_v g(v) is the FD capacity that
    this demand level implies (a useful by-product / calibration check)."""
    g = fd_shape(v_t, vf, m, form)
    G = float(g.sum())
    if G <= 0:
        return np.zeros_like(g), 0.0, 0.0
    theta = D / (dt_hr * G)                      # closed-form conservation scale
    q = theta * g
    # implied capacity = peak of theta*g(v) over feasible v (Greenshields: at vf/2; S3: at u_c)
    vgrid = np.linspace(1e-6, vf, 400)
    cap_implied = float(theta * fd_shape(vgrid, vf, m, form).max())
    return q, theta, cap_implied


def flow_from_speed_corridor(speeds, demands, vf, dt_hr, m=6.0, form="s3", caps=None):
    """CORRIDOR-regularized demand-conserving flow.

    The FD density scale theta (= k_c / k_j, hence capacity) is a property of the
    road TYPE, so it must NOT be a free per-link knob. We therefore use a SINGLE
    corridor scale theta_bar for every link (zero parameter deviation), and restore
    EXACT per-link conservation  sum_t q_i(t)*dt = D_i  with a small additive slack
    lambda_i that is NOT an FD parameter (just a local count correction):

        theta_bar = sum_i D_i / (dt * sum_i sum_t g(v_i(t)))     # conserves corridor TOTAL
        q_i(t)    = clip( theta_bar * g(v_i(t)) + lambda_i , 0, cap_i ),  lambda_i: sum q_i*dt = D_i

    Because theta_bar conserves the corridor total, sum_i lambda_i ~ 0 and each
    lambda_i is small; a LARGE |lambda_i| flags a link whose speed-implied flow is
    inconsistent with the corridor FD at its demand. Inputs: speeds = list of v(t)
    arrays (one per link/episode), demands = per-lane D_i. Returns (results, theta_bar)
    where results[i] = dict(q, lam, theta, cap_implied, resid, dev_frac)."""
    # vf may be a scalar (corridor free-flow) or a per-link list/array. theta (k_c)
    # is the parameter kept corridor-uniform; vf (posted free-flow) is a known
    # per-link FD attribute and may legitimately vary by road class.
    vfs = list(vf) if (hasattr(vf, "__len__") and not isinstance(vf, str)) else [vf] * len(speeds)
    shapes = [fd_shape(np.asarray(v, float), vfi, m, form) for v, vfi in zip(speeds, vfs)]
    Gtot = sum(float(s.sum()) for s in shapes)
    Dtot = float(sum(demands))
    theta_bar = Dtot / max(dt_hr * Gtot, 1e-9)
    out = []
    for i, (s, D, vfi) in enumerate(zip(shapes, demands, vfs)):
        vgrid = np.linspace(1e-6, vfi, 400)
        cap_link = theta_bar * float(fd_shape(vgrid, vfi, m, form).max())  # implied cap at this link's vf
        cap = float(caps[i]) if caps is not None else cap_link
        q0 = theta_bar * s
        target = D / max(dt_hr, 1e-9)
        lo, hi, lam = -cap, cap, 0.0
        for _ in range(80):
            lam = 0.5 * (lo + hi)
            ss = float(np.clip(q0 + lam, 0.0, cap).sum())
            if abs(ss - target) <= 1e-6 * max(target, 1.0):
                break
            if ss < target: lo = lam
            else: hi = lam
        q = np.clip(q0 + lam, 0.0, cap)
        # how far the per-link unconstrained scale WOULD have to move = lam relative to mean flow
        dev = abs(lam) / max(q0.mean(), 1e-6)
        out.append(dict(q=q, lam=lam, theta=theta_bar, cap_implied=cap_link,
                        resid=float(q.sum() * dt_hr - D), dev_frac=dev))
    return out, theta_bar


# ============================ IO adapters (robust) ==========================
def load_corridor(cfg, log):
    """Dispatch to the right loader; returns (df[COMMON_COLS], mode). Raises on fatal IO."""
    src = cfg["source"]
    if src == "i10_csv":
        return _load_i10(cfg["path"], log)
    if src == "pems_json":
        return _load_pems(cfg["path"], log)
    if src == "inrix_folder":
        return _load_inrix(cfg["path"], log)
    if src == "avgweekday_csv":
        return _load_avgweekday(cfg["path"], cfg.get("data_mode", "measured"), log)
    raise ValueError(f"unknown source {src}")


def _load_avgweekday(path, mode, log):
    """Bundled SMALL representative dataset: one average-weekday profile per link (the space-saving
    self-demo input). Presents it to the pipeline as a single weekday (Mon)."""
    rd = pd.read_csv(path)
    ren = {"avg_weekday_speed_mph": "speed", "avg_weekday_flow_veh_per_hr_lane": "flow_pl",
           "length_mi": "length"}
    rd = rd.rename(columns={k: v for k, v in ren.items() if k in rd.columns})
    if "lanes" not in rd.columns:
        rd["lanes"] = 1
    if "length" not in rd.columns:
        rd["length"] = 0.5
    rd["date"] = "Weekday"; rd["weekday"] = 0                # a single representative weekday
    keep = [c for c in COMMON_COLS if c in rd.columns]
    log.info(f"  loaded avg-weekday profile: {rd.link_id.nunique()} links x "
             f"{rd.t_min.nunique()} time bins ({mode})")
    return rd[keep], ("measured" if ("flow_pl" in rd.columns and mode == "measured") else "speed_only")


def _load_i10(path, log):
    d = pd.read_csv(path)
    df = pd.DataFrame(dict(link_id=d.link_id, date=d.date.astype(str), t_min=d.time_minutes,
                           weekday=d.weekday, speed=d.speed, flow_pl=d.hourly_volume_per_lane,
                           lanes=d.lanes, length=d.length))
    log.info(f"  loaded I-10 csv: {len(df):,} rows, {df.link_id.nunique()} links")
    return df, "measured"


def _load_pems(folder, log):
    # accept either link_performance.json or link_performance_all_sensors.json
    jpath = os.path.join(folder, "link_performance.json")
    if not os.path.exists(jpath):
        jpath = os.path.join(folder, "link_performance_all_sensors.json")
    js = json.load(open(jpath))
    # sensor_information.csv is optional (QVDF-E LA corridors carry lanes in meta)
    ipath = os.path.join(folder, "sensor_information.csv")
    if os.path.exists(ipath):
        info = pd.read_csv(ipath); info["sensor_id"] = info["sensor_id"].astype(str)
        lane_map = dict(zip(info.sensor_id, info.Lanes)); len_map = dict(zip(info.sensor_id, info.Length))
    else:
        lane_map, len_map = {}, {}
    recs, skipped = [], 0
    for sid, rec in js.items():
        try:
            base = pd.Timestamp(rec["t0"]); dt_min = int(str(rec.get("dt", "5min")).replace("min", "")) or 5
            s = rec.get("s", []); f = rec.get("f", [])
            lanes = lane_map.get(sid, rec.get("meta", {}).get("lanes", 4)) or 4
            length = len_map.get(sid, 0.5) or 0.5
            for i in range(len(s)):
                if s[i] is None or (isinstance(s[i], float) and np.isnan(s[i])):
                    continue
                ts = base + pd.Timedelta(minutes=i * dt_min)
                fl = f[i] if i < len(f) and f[i] is not None else np.nan
                recs.append((int(sid) if sid.isdigit() else sid, str(ts.date()),
                             ts.hour * 60 + ts.minute, ts.weekday(), float(s[i]), float(fl), lanes, length))
        except Exception as e:
            skipped += 1; log.warning(f"  PeMS sensor {sid} skipped: {type(e).__name__} {e}")
    df = pd.DataFrame(recs, columns=COMMON_COLS)
    log.info(f"  loaded PeMS: {len(df):,} rows, {df.link_id.nunique()} sensors ({skipped} skipped)")
    return df, "measured"


def _load_inrix(folder, log):
    rd = pd.read_csv(os.path.join(folder, "Readings.csv"), usecols=["tmc_code", "measurement_tstamp", "speed"])
    ts = pd.to_datetime(rd.measurement_tstamp, errors="coerce")
    meta = pd.read_csv(os.path.join(folder, "TMC_Identification.csv"), encoding="utf-8-sig")
    lm = dict(zip(meta.tmc.astype(str), meta.miles))
    intmap = {t: i + 1 for i, t in enumerate(meta.tmc.astype(str))}
    df = pd.DataFrame(dict(link_id=rd.tmc_code.astype(str).map(intmap), date=ts.dt.date.astype(str),
                           t_min=ts.dt.hour * 60 + ts.dt.minute, weekday=ts.dt.weekday, speed=rd.speed,
                           length=rd.tmc_code.astype(str).map(lm)))
    df["lanes"] = 1
    df = df.dropna(subset=["link_id", "speed", "date"])
    df["link_id"] = df["link_id"].astype(int)
    log.info(f"  loaded INRIX: {len(df):,} rows, {df.link_id.nunique()} TMCs")
    return df, "speed_only"
