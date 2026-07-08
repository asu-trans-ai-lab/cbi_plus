"""
stage5_qvdf.py — QVDF + shape forward model (per sensor x period).

Fits two competing forward models on the post-CBI episode panel:

  (1) QVDF (Queueing-based Volume-Delay Function) — Zhou et al.
        P_pred(D/C)      = f_d * (D/C - 1)^n                    when D > C
        v_t2_pred(D/C)   = vf / (1 + alpha (D/C)^beta)          (BPR speed kernel)
        v_avg_pred(D/C)  = vf * f_p * (D/C)^(-s)                (period-mean speed)

  (2) Shape model — normalized speed profile around the minimum:
        v(t) = v_t2 + (vf - v_t2) * phi(tau)
        where tau = (t - t2) / (P/2), phi is a fixed shape (quartic_symmetric
        by default), and phi_mean = mean of phi over [-1, +1].

Outlier mitigation:
  - Hampel + qc_pass already applied upstream (Stage 1).
  - At fit time, drop points outside [Q1 - K * IQR, Q3 + K * IQR] per
    (sensor, period) bucket (default K=3) on each fitted variable.
  - Require >= MIN_POINTS_FOR_FIT valid days per (sensor, period).

Day filters:
  - 'weekday'   = all Mon-Fri days that passed QC.
  - 'difficult' = worst-decile by P within each (sensor, period). Lets us
                  re-fit on the chronically-congested subset (matches the
                  legacy FIXED-figure variation).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

from .schemas import OUTLIER_THRESHOLDS, PERIOD_DEFINITIONS, period_label_for_filename


# ---------------------------------------------------------------------------
# Shape library (matches qvdf_shape_utils.py preset names)
# ---------------------------------------------------------------------------
def _phi_quartic_symmetric(tau):
    return np.clip(1.0 - tau ** 4, 0.0, 1.0)


def _phi_quadratic_symmetric(tau):
    return np.clip(1.0 - tau ** 2, 0.0, 1.0)


def _phi_quartic_early(tau):
    # Asymmetric: dip shifted earlier
    return np.clip(1.0 - ((tau + 0.3) / 1.3) ** 4, 0.0, 1.0)


SHAPE_LIBRARY = {
    "quartic_symmetric": _phi_quartic_symmetric,
    "quadratic_symmetric": _phi_quadratic_symmetric,
    "quartic_early": _phi_quartic_early,
}


# ---------------------------------------------------------------------------
# Outlier mitigation
# ---------------------------------------------------------------------------
def iqr_filter(series: pd.Series, k: float = None) -> pd.Series:
    """Return boolean mask: True where value is inside [Q1 - k IQR, Q3 + k IQR]."""
    if k is None:
        k = OUTLIER_THRESHOLDS["iqr_factor"]
    s = series.dropna()
    if len(s) < 4:
        return pd.Series(True, index=series.index)
    q1, q3 = np.percentile(s, [25, 75])
    iqr = q3 - q1
    lo, hi = q1 - k * iqr, q3 + k * iqr
    return series.between(lo, hi) | series.isna()


def apply_outlier_mitigation(df: pd.DataFrame,
                             on_cols: list,
                             group_keys: list = None) -> pd.DataFrame:
    """Drop rows where any `on_col` is an IQR outlier within its group."""
    if df.empty:
        return df
    if group_keys is None:
        group_keys = ["sensor_uid", "period"]
    keep = pd.Series(True, index=df.index)
    for grp_vals, sub in df.groupby(group_keys, sort=False):
        for col in on_cols:
            if col in sub.columns:
                col_mask = iqr_filter(sub[col])
                keep.loc[sub.index] = keep.loc[sub.index] & col_mask
    return df[keep].copy()


def apply_day_filter(episodes: pd.DataFrame, day_filter: str) -> pd.DataFrame:
    """`weekday` (all weekdays) or `difficult` (worst-decile P per sensor x period)."""
    if day_filter == "weekday":
        episodes = episodes.copy()
        episodes["dow"] = pd.to_datetime(episodes["date"]).dt.dayofweek
        return episodes[episodes["dow"] < 5].drop(columns="dow")
    if day_filter == "difficult":
        rows = []
        for (sid, period), grp in episodes.groupby(["sensor_uid", "period"], sort=False):
            if len(grp) < 3:
                continue
            cutoff = grp["P_min"].quantile(0.90)
            rows.append(grp[grp["P_min"] >= cutoff])
        return pd.concat(rows, ignore_index=True) if rows else episodes.iloc[:0]
    raise ValueError(f"Unknown day_filter: {day_filter!r}")


# ---------------------------------------------------------------------------
# QVDF fits
# ---------------------------------------------------------------------------
def _safe_log(x):
    return np.log(np.maximum(np.asarray(x, dtype=float), 1e-9))


def fit_qvdf_P(D_over_C: np.ndarray, P_hours: np.ndarray) -> dict:
    """
    P = f_d * (D/C - 1)^n   for D/C > 1.   Fit on log-log:
        log(P) = log(f_d) + n * log(D/C - 1)

    Returns dict with f_d, n, R^2, n_points.
    """
    doc = np.asarray(D_over_C, dtype=float)
    P = np.asarray(P_hours, dtype=float)
    mask = np.isfinite(doc) & np.isfinite(P) & (doc > 1.05) & (P > 0)
    if mask.sum() < OUTLIER_THRESHOLDS["min_points_for_fit"]:
        return dict(f_d=None, n=None, r2=float("nan"), n_points=int(mask.sum()))
    x = _safe_log(doc[mask] - 1.0)
    y = _safe_log(P[mask])
    A = np.vstack([np.ones_like(x), x]).T
    sol, _, _, _ = np.linalg.lstsq(A, y, rcond=None)
    log_fd, n_exp = sol
    y_pred = log_fd + n_exp * x
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return dict(f_d=float(np.exp(log_fd)), n=float(n_exp),
                r2=float(r2), n_points=int(mask.sum()))


def fit_qvdf_v_t2(D_over_C: np.ndarray, v_t2: np.ndarray, vf: float) -> dict:
    """
    BPR-style:  v_t2 = vf / (1 + alpha * (D/C)^beta).
    Solve  (vf / v_t2 - 1) = alpha * (D/C)^beta   on log-log.
    """
    doc = np.asarray(D_over_C, dtype=float)
    v = np.asarray(v_t2, dtype=float)
    mask = (np.isfinite(doc) & np.isfinite(v) & (doc > 0) & (v > 0)
            & (v < vf * 1.05))
    if mask.sum() < OUTLIER_THRESHOLDS["min_points_for_fit"]:
        return dict(alpha=None, beta=None, vf=float(vf), r2=float("nan"),
                    n_points=int(mask.sum()))
    ratio = (vf / np.maximum(v[mask], 1.0)) - 1.0
    ratio = np.maximum(ratio, 1e-6)
    x = _safe_log(doc[mask])
    y = _safe_log(ratio)
    A = np.vstack([np.ones_like(x), x]).T
    sol, _, _, _ = np.linalg.lstsq(A, y, rcond=None)
    log_alpha, beta = sol
    y_pred = log_alpha + beta * x
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return dict(alpha=float(np.exp(log_alpha)), beta=float(beta), vf=float(vf),
                r2=float(r2), n_points=int(mask.sum()))


def fit_qvdf_v_avg(D_over_C: np.ndarray, v_avg: np.ndarray, vf: float) -> dict:
    """v_avg = vf * f_p * (D/C)^(-s) → log-log fit."""
    doc = np.asarray(D_over_C, dtype=float)
    v = np.asarray(v_avg, dtype=float)
    mask = (np.isfinite(doc) & np.isfinite(v) & (doc > 0) & (v > 0)
            & (v < vf * 1.05))
    if mask.sum() < OUTLIER_THRESHOLDS["min_points_for_fit"]:
        return dict(f_p=None, s=None, vf=float(vf), r2=float("nan"),
                    n_points=int(mask.sum()))
    x = _safe_log(doc[mask])
    y = _safe_log(v[mask] / vf)
    A = np.vstack([np.ones_like(x), x]).T
    sol, _, _, _ = np.linalg.lstsq(A, y, rcond=None)
    log_fp, s_neg = sol
    y_pred = log_fp + s_neg * x
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return dict(f_p=float(np.exp(log_fp)), s=float(-s_neg), vf=float(vf),
                r2=float(r2), n_points=int(mask.sum()))


# ---------------------------------------------------------------------------
# Shape model
# ---------------------------------------------------------------------------
def fit_shape_model(v_t2: float, vf: float,
                    shape_name: str = "quartic_symmetric") -> dict:
    """
    Shape model predicts the speed profile around t2 given v_t2 and vf.
    phi_mean = integral of phi over [-1, 1] / 2 — used to derive v_avg.
    """
    phi = SHAPE_LIBRARY[shape_name]
    tau = np.linspace(-1, 1, 201)
    # np.trapezoid (numpy>=2.0) was np.trapz in numpy<2.0 — the fallback must
    # be lazy: getattr's default argument is evaluated eagerly, so
    # getattr(np, "trapezoid", getattr(np, "trapz")) raises on numpy>=2.4
    _trapz = getattr(np, "trapezoid", None)
    if _trapz is None:
        _trapz = np.trapz
    phi_mean = float(_trapz(phi(tau), tau) / 2.0)
    v_avg_pred = float(v_t2 + (vf - v_t2) * phi_mean)
    v_min_pred = float(v_t2)         # by definition
    return dict(shape=shape_name, phi_mean=phi_mean,
                v_avg_pred=v_avg_pred, v_min_pred=v_min_pred)


# ---------------------------------------------------------------------------
# Per (sensor, period) orchestration
# ---------------------------------------------------------------------------
def _enrich_episodes(episodes: pd.DataFrame,
                     fd_summary: pd.DataFrame,
                     dt_min: float = 5.0) -> pd.DataFrame:
    """Attach capacity + D/C + avg-speed proxy to every episode row."""
    df = episodes.merge(fd_summary[["sensor_uid", "capacity_vphpl", "v_f_mph"]
                                   if "v_f_mph" in fd_summary.columns
                                   else ["sensor_uid", "capacity_vphpl"]],
                        on="sensor_uid", how="left")
    if "v_f_mph" not in df.columns:
        df["v_f_mph"] = 70.0
    df["P_hours"] = df["P_min"] / 60.0
    # D/C in HOURS — the scan_congestion_duration convention used everywhere else
    # in this package: demand_veh is per-lane vehicles ACCUMULATED over the
    # congested window and capacity_vphpl is per-lane per-hour, so the ratio has
    # units of hours (~= P at capacity, 1-5 h when congested). The previous
    # denominator (capacity x P_hours x lanes) (a) double-counted lanes — demand
    # is already per-lane — and (b) collapsed D/C to the rate mu/C <= 1, so the
    # duration fit's own `doc > 1.05` guard rejected EVERY episode and the P
    # model came out NaN in 100% of rows (independent result review, F1).
    df["D_over_C"] = df["demand_veh"] / np.maximum(df["capacity_vphpl"], 1.0)
    # Avg speed proxy: use mean of speed within congested window (already in episode)
    if "cong_mean_speed" not in df.columns:
        # Approximate: v_avg ~ (v_f + v_t2) / 2 — replaced by Stage-4 if available
        df["cong_mean_speed"] = (df["v_f_mph"] + df["min_speed_mph"]) / 2.0
    return df


def fit_qvdf_per_sensor_period(episodes_enriched: pd.DataFrame,
                               day_filter: str = "weekday",
                               outlier_mitigate: bool = True) -> pd.DataFrame:
    """
    Fit QVDF (P, v_t2, v_avg) for each (sensor, period). Returns a wide table.
    """
    df = apply_day_filter(episodes_enriched, day_filter)
    if outlier_mitigate:
        df = apply_outlier_mitigation(
            df, on_cols=["P_min", "min_speed_mph", "D_over_C"],
            group_keys=["sensor_uid", "period"],
        )
    rows = []
    for (sid, period), grp in df.groupby(["sensor_uid", "period"], sort=False):
        if len(grp) < OUTLIER_THRESHOLDS["min_points_for_fit"]:
            continue
        vf = float(grp["v_f_mph"].iloc[0])
        p_fit = fit_qvdf_P(grp["D_over_C"].to_numpy(),
                            grp["P_hours"].to_numpy())
        v_t2_fit = fit_qvdf_v_t2(grp["D_over_C"].to_numpy(),
                                  grp["min_speed_mph"].to_numpy(), vf)
        v_avg_fit = fit_qvdf_v_avg(grp["D_over_C"].to_numpy(),
                                    grp["cong_mean_speed"].to_numpy(), vf)
        rows.append({
            "sensor_uid": sid,
            "period": period,
            "n_days": int(len(grp)),
            "vf_mph": vf,
            "f_d": p_fit["f_d"], "n_exp": p_fit["n"], "P_r2": p_fit["r2"],
            "alpha": v_t2_fit["alpha"], "beta": v_t2_fit["beta"], "v_t2_r2": v_t2_fit["r2"],
            "f_p": v_avg_fit["f_p"], "s_exp": v_avg_fit["s"], "v_avg_r2": v_avg_fit["r2"],
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Forward predict
# ---------------------------------------------------------------------------
def predict_qvdf(episodes_enriched: pd.DataFrame,
                 qvdf_params: pd.DataFrame) -> pd.DataFrame:
    """Apply fitted QVDF params back to each episode and return paired obs/pred."""
    pm = qvdf_params.set_index(["sensor_uid", "period"])
    out = episodes_enriched.copy()
    out["P_pred_hours"] = np.nan
    out["v_t2_pred_mph"] = np.nan
    out["v_avg_pred_mph"] = np.nan
    out["v_avg_shape_mph"] = np.nan

    for idx, row in out.iterrows():
        key = (row["sensor_uid"], row["period"])
        if key not in pm.index:
            continue
        p = pm.loc[key]
        doc = row["D_over_C"]
        vf = row["v_f_mph"]
        # QVDF P
        if p.get("f_d") is not None and p.get("n_exp") is not None and doc > 1:
            out.at[idx, "P_pred_hours"] = (
                p["f_d"] * np.maximum(doc - 1.0, 0.0) ** p["n_exp"]
            )
        # QVDF v_t2 (BPR speed kernel)
        if p.get("alpha") is not None and p.get("beta") is not None:
            out.at[idx, "v_t2_pred_mph"] = vf / (1.0 + p["alpha"] * doc ** p["beta"])
        # QVDF v_avg
        if p.get("f_p") is not None and p.get("s_exp") is not None:
            out.at[idx, "v_avg_pred_mph"] = vf * p["f_p"] * doc ** (-p["s_exp"])
        # Shape model — fed by v_t2 prediction
        v_t2_hat = out.at[idx, "v_t2_pred_mph"]
        if np.isfinite(v_t2_hat):
            sm = fit_shape_model(v_t2_hat, vf)
            out.at[idx, "v_avg_shape_mph"] = sm["v_avg_pred"]
    return out


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def run_qvdf(episodes_df: pd.DataFrame,
             fd_summary: pd.DataFrame,
             day_filter: str = "weekday",
             outlier_mitigate: bool = True) -> dict:
    """
    End-to-end Stage 5: enrich, fit, forward predict.
    Returns {params, predictions, day_filter, n_fitted}.
    """
    enriched = _enrich_episodes(episodes_df, fd_summary)
    params = fit_qvdf_per_sensor_period(enriched, day_filter=day_filter,
                                        outlier_mitigate=outlier_mitigate)
    predictions = predict_qvdf(enriched, params)
    return dict(
        params=params,
        predictions=predictions,
        day_filter=day_filter,
        n_fitted=int(len(params)),
    )


def write_stage5(result: dict, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result["params"].to_csv(out_dir / f"qvdf_params__{result['day_filter']}.csv", index=False)
    result["predictions"].to_csv(out_dir / f"qvdf_predictions__{result['day_filter']}.csv", index=False)
    summary = dict(
        day_filter=result["day_filter"],
        n_fitted_sensor_period=result["n_fitted"],
        median_P_r2=float(result["params"]["P_r2"].median()) if len(result["params"]) else float("nan"),
        median_v_t2_r2=float(result["params"]["v_t2_r2"].median()) if len(result["params"]) else float("nan"),
        median_v_avg_r2=float(result["params"]["v_avg_r2"].median()) if len(result["params"]) else float("nan"),
    )
    with open(out_dir / f"qvdf_summary__{result['day_filter']}.json", "w") as f:
        json.dump(summary, f, indent=2, default=float)
