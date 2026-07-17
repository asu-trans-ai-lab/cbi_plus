# -*- coding:utf-8 -*-
"""QVDF turn-key — calibration quality measures & gates.

Produces three tables per corridor (the paper's MAE/MAPE + QVDF-E-style gates + new measures):
  Quality_calibration.csv  per period: D/C->P fit R2, P->magnitude fit R2, and model-vs-observed
                           MAE/MAPE for P, V_t2, t0, t3 (the QVDF paper accuracy metrics).
  Quality_timeseries.csv   per link: smoothed-vs-raw avg-weekday R2/RMSE, and day-to-day variation
                           (each weekday day vs the smoothed average weekday: RMSE / R2 / CV).
  quality_gates.csv        per period: PASS/FAIL against thresholds (QVDF-E aligned + new).
"""
import numpy as np
import pandas as pd
import config as C
import qvdf_core as Q

# gate thresholds (QVDF-E: qc 0.85, valid>=5, fd_r2 0.70; plus calibration-fit / accuracy gates)
GATES = dict(min_n_links=5, min_step1_R2=0.50, min_step2_R2=0.30,
             max_P_MAPE=30.0, max_vt2_MAPE=30.0, min_vt2_within_tol=70.0,
             min_smooth_R2=0.90, min_fd_R2=0.70)


def _r2(obs, pred):
    obs = np.asarray(obs, float); pred = np.asarray(pred, float)
    m = np.isfinite(obs) & np.isfinite(pred); obs, pred = obs[m], pred[m]
    if len(obs) < 2:
        return np.nan
    sst = np.sum((obs - obs.mean()) ** 2)
    return float(1 - np.sum((obs - pred) ** 2) / sst) if sst > 0 else np.nan


def _mae(o, p):
    o = np.asarray(o, float); p = np.asarray(p, float); m = np.isfinite(o) & np.isfinite(p)
    return float(np.mean(np.abs(o[m] - p[m]))) if m.any() else np.nan


def _mape(o, p):
    o = np.asarray(o, float); p = np.asarray(p, float)
    m = np.isfinite(o) & np.isfinite(p) & (np.abs(o) > 1e-6)
    return float(np.mean(np.abs((o[m] - p[m]) / o[m])) * 100) if m.any() else np.nan


def _rmse(o, p):
    o = np.asarray(o, float); p = np.asarray(p, float); m = np.isfinite(o) & np.isfinite(p)
    return float(np.sqrt(np.mean((o[m] - p[m]) ** 2))) if m.any() else np.nan


def _clip_r2(x):
    return float(np.clip(x, -1.0, 1.0)) if x == x else np.nan   # floor at -1 ("worse than mean")


def calibration_quality(ep, params_by_period, fdp, cfg):
    """D/C->P and P->magnitude fit R2, and model-vs-observed MAE/MAPE for P, V_t2, t0, t3.
    R2 is the across-links fit for corridor (avg_weekday) mode, or the MEDIAN per-link R2 for
    per_dow mode (so one badly-fit link does not dominate)."""
    corridor = cfg.get("wd_mode") == "avg_weekday"
    rows = []
    for per in C.PERIODS:
        pp = params_by_period.get(per, {})
        g = ep[(ep.period == per) & (ep.P > 0) & (ep.DC < C.DOC_MAX - 0.01)].copy()
        g = g[g.link_id.isin(pp.keys())]
        if len(g) < 3:
            continue
        cut = g.link_id.map(lambda l: C.CUTOFF_RATIO * fdp[l]["vf"]).to_numpy()
        fd = g.link_id.map(lambda l: pp[l]["f_d"]).to_numpy(); nn = g.link_id.map(lambda l: pp[l]["n"]).to_numpy()
        fp = g.link_id.map(lambda l: pp[l]["f_p"]).to_numpy(); ss = g.link_id.map(lambda l: pp[l]["s"]).to_numpy()
        P = g.P.to_numpy(); DC = g.DC.to_numpy(); vt2 = g.v_t2.to_numpy()
        predP = fd * DC ** nn
        obs_mag = cut / vt2 - 1.0; pred_mag = fp * P ** ss
        predvt2 = cut / (1.0 + fp * P ** ss)
        predt0 = g.t2.to_numpy() - 0.5 * predP; predt3 = g.t2.to_numpy() + 0.5 * predP
        if corridor:
            r1, r2m = _r2(P, predP), _r2(obs_mag, pred_mag)
        else:                                              # median of per-link R2
            r1s, r2s = [], []
            for lid, idx in g.groupby("link_id").groups.items():
                ii = g.index.get_indexer(idx)
                if len(ii) >= 3:
                    r1s.append(_r2(P[ii], predP[ii])); r2s.append(_r2(obs_mag[ii], pred_mag[ii]))
            r1 = float(np.nanmedian(r1s)) if r1s else np.nan
            r2m = float(np.nanmedian(r2s)) if r2s else np.nan
        within = np.abs(vt2 - predvt2) <= C.VT2_TOL_MPH               # V_t2 gate: model within tol
        rows.append(dict(period=per, n_episodes=len(g), n_links=int(g.link_id.nunique()),
                         step1_DC_P_R2=round(_clip_r2(r1), 3), step2_P_mag_R2=round(_clip_r2(r2m), 3),
                         P_MAE_h=round(_mae(P, predP), 2), P_MAPE_pct=round(_mape(P, predP), 1),
                         vt2_MAE_mph=round(_mae(vt2, predvt2), 1), vt2_MAPE_pct=round(_mape(vt2, predvt2), 1),
                         vt2_within_tol_pct=round(float(np.mean(within)) * 100, 1),
                         t0_MAE_min=round(_mae(g.t0, predt0) * 60, 1),
                         t3_MAE_min=round(_mae(g.t3, predt3) * 60, 1)))
    return pd.DataFrame(rows)


def timeseries_quality(a, awk, fdp):
    """Per link: smoothed-vs-raw avg-weekday R2/RMSE, and day-to-day variation around the
    smoothed average weekday (RMSE / R2 / coefficient of variation)."""
    rows = []
    lo, hi = C.WIDE_WINDOW
    for lid, g in awk.groupby("link_id"):
        if lid not in fdp:
            continue
        g = g[(g.t_min >= lo) & (g.t_min < hi)].sort_values("t_min")
        if len(g) < 8:
            continue
        raw = g.speed.to_numpy(); sm = Q.smooth_speed(raw)
        avg_map = dict(zip(g.t_min.to_numpy(), sm))
        sub = a[(a.link_id == lid) & (a.weekday < 5) & (a.t_min >= lo) & (a.t_min < hi)]
        piv = sub.pivot_table(index="t_min", columns="date", values="speed")
        day_rmse, day_r2 = [], []
        for date in piv.columns:
            d = piv[date].dropna()
            base = np.array([avg_map.get(t, np.nan) for t in d.index])
            day_rmse.append(_rmse(d.to_numpy(), base)); day_r2.append(_r2(d.to_numpy(), base))
        cv = float((piv.std(axis=1) / piv.mean(axis=1).clip(lower=1)).mean()) if piv.shape[1] > 1 else np.nan
        rows.append(dict(link_id=lid, n_weekdays=int(piv.shape[1]),
                         smooth_vs_raw_R2=round(_r2(raw, sm), 3),
                         smooth_vs_raw_RMSE=round(_rmse(raw, sm), 2),
                         day2day_RMSE_mph=round(float(np.nanmean(day_rmse)), 2) if day_rmse else np.nan,
                         day2day_R2=round(float(np.nanmean(day_r2)), 3) if day_r2 else np.nan,
                         day2day_CV=round(cv, 3)))
    return pd.DataFrame(rows)


def fd_fit_r2(a, fdp, mode):
    """S3 fundamental-diagram fit R2 (speed vs S3-predicted speed at observed density); PeMS only."""
    if mode != "measured":
        return {}
    out = {}
    for lid, g in a.groupby("link_id"):
        if lid not in fdp or "flow_pl" not in g.columns:
            continue
        gg = g[(g.speed > 0) & (g.flow_pl > 0)].copy(); gg["k"] = gg.flow_pl / gg.speed
        gg = gg[(gg.k >= 1) & (gg.k < 220)]
        if len(gg) < 30:
            continue
        p = fdp[lid]; pred = Q.s3_speed(gg.k.to_numpy(), p["vf"], p["kc"], p["m"])
        out[lid] = _r2(gg.speed.to_numpy(), pred)
    return out


def gates(cal_q, ts_q, fd_r2, mode):
    rows = []
    smooth_med = float(ts_q.smooth_vs_raw_R2.median()) if len(ts_q) else np.nan
    fd_med = float(np.nanmedian(list(fd_r2.values()))) if fd_r2 else np.nan
    for _, r in cal_q.iterrows():
        checks = [
            ("n_links_fitted",          r.n_links,        GATES["min_n_links"],   r.n_links >= GATES["min_n_links"], ">="),
            ("step1_DC_P_R2",           r.step1_DC_P_R2,  GATES["min_step1_R2"],  r.step1_DC_P_R2 >= GATES["min_step1_R2"], ">="),
            ("step2_P_mag_R2",          r.step2_P_mag_R2, GATES["min_step2_R2"],  r.step2_P_mag_R2 >= GATES["min_step2_R2"], ">="),
            ("P_MAPE_pct",              r.P_MAPE_pct,     GATES["max_P_MAPE"],    r.P_MAPE_pct <= GATES["max_P_MAPE"], "<="),
            ("vt2_MAPE_pct",            r.vt2_MAPE_pct,   GATES["max_vt2_MAPE"],  r.vt2_MAPE_pct <= GATES["max_vt2_MAPE"], "<="),
            ("vt2_within_tol_pct",      r.vt2_within_tol_pct, GATES["min_vt2_within_tol"], r.vt2_within_tol_pct >= GATES["min_vt2_within_tol"], ">="),
            ("smooth_vs_raw_R2_median", round(smooth_med, 3), GATES["min_smooth_R2"], smooth_med >= GATES["min_smooth_R2"], ">="),
        ]
        if mode == "measured" and fd_r2:
            checks.append(("fd_fit_R2_median", round(fd_med, 3), GATES["min_fd_R2"],
                           fd_med >= GATES["min_fd_R2"], ">="))
        for name, val, thr, ok, op in checks:
            rows.append([r.period, name, val, f"{op} {thr}", "PASS" if ok else "FAIL"])
    return pd.DataFrame(rows, columns=["period", "gate", "value", "threshold", "status"])
