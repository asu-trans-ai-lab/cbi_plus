"""
stage4_mu_validation.py — discharge-window μ + group shrinkage (Layer 4).

Headline deliverable: μ is computed ONLY on valid congested episodes, over the
discharge window D_e (not the full congested period). Low-reliability links
borrow strength from corridor peers via James-Stein-style shrinkage.

Also runs the predicted-vs-observed μ comparison in two modes
(all_days, valid_only) so the structural-bias finding becomes visible.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.linear_model import HuberRegressor

from .schemas import MU_COLUMNS, PERIOD_SLICE_BOUNDS, period_hour_mask


# ---------------------------------------------------------------------------
# Per-episode μ
# ---------------------------------------------------------------------------
def mu_episode(episode_row: pd.Series,
               qc_df: pd.DataFrame,
               min_intervals: int = 6) -> float:
    """
    μ_e = MEDIAN of flow_vph over discharge window D_e = (d_start, d_end].

    Returns NaN if window is too short or all flow is NaN (speed-only data).
    """
    if not bool(episode_row.get("is_valid_for_mu", False)):
        return float("nan")
    ds = episode_row.get("discharge_start_idx")
    de = episode_row.get("discharge_end_idx")
    if pd.isna(ds) or pd.isna(de):
        return float("nan")
    ds, de = int(ds), int(de)

    sid = episode_row["sensor_uid"]
    date = episode_row["date"]
    grp = qc_df[(qc_df["sensor_uid"] == sid)
                & (qc_df["date"].astype(str) == str(date))].sort_values("datetime")
    # Episode indices are PERIOD-relative (stage2 groups by sensor/date/period),
    # so slice the day down to the same period before any iloc lookup.
    period = episode_row.get("period")
    if period in PERIOD_SLICE_BOUNDS:
        hours = pd.to_datetime(grp["datetime"]).dt.hour
        grp = grp[period_hour_mask(hours, period)]
    grp = grp.reset_index(drop=True)
    if "flow_vph" not in grp.columns or grp["flow_vph"].isna().all():
        return float("nan")
    if de < ds or de >= len(grp):
        return float("nan")
    window = grp.iloc[ds:de + 1]
    valid = window["flow_vph"].dropna()
    if len(valid) < min_intervals:
        return float("nan")
    return float(np.nanmedian(valid))


def mu_per_episode(episodes_df: pd.DataFrame,
                   qc_df: pd.DataFrame) -> pd.DataFrame:
    """Append a 'mu_obs_vphpl' column to episodes_df."""
    qc_df = qc_df.copy()
    qc_df["date"] = pd.to_datetime(qc_df["datetime"]).dt.date.astype(str)

    mus = [mu_episode(row, qc_df) for _, row in episodes_df.iterrows()]
    out = episodes_df.copy()
    out["mu_obs_vphpl"] = mus
    return out


# ---------------------------------------------------------------------------
# Per-link μ + reliability
# ---------------------------------------------------------------------------
def mu_per_link(episodes_with_mu: pd.DataFrame,
                reliability_df: pd.DataFrame) -> pd.DataFrame:
    """Median + IQR of mu over valid episodes."""
    rel_lookup = (reliability_df.set_index("sensor_uid")["reliability_class"].to_dict()
                  if "reliability_class" in reliability_df.columns else {})
    rows = []
    for sid, grp in episodes_with_mu.groupby("sensor_uid"):
        mus = grp.loc[grp["is_valid_for_mu"], "mu_obs_vphpl"].dropna()
        rel_class = rel_lookup.get(sid, "not_reliable")
        corridor = (grp["corridor"].iloc[0] if "corridor" in grp.columns
                    else "UNKNOWN")

        if len(mus) > 0:
            med = float(np.median(mus))
            iqr = float(np.percentile(mus, 75) - np.percentile(mus, 25))
        else:
            med, iqr = float("nan"), float("nan")

        rows.append({
            "sensor_uid": sid,
            "corridor": corridor,
            "n_episodes_total": int(len(grp)),
            "n_episodes_valid": int(grp["is_valid_for_mu"].sum()),
            "mu_obs_median_vphpl": med,
            "mu_obs_iqr_vphpl": iqr,
            "reliability_class": rel_class,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Group-shrinkage
# ---------------------------------------------------------------------------
def mu_group_shrinkage(mu_links: pd.DataFrame,
                       group_key: str = "corridor") -> pd.DataFrame:
    """
    James-Stein-style:  μ_i = α_i · μ_obs_i + (1 - α_i) · μ_group.
    α_i = n_valid_i / (n_valid_i + k0),  k0 = median n_valid across reliable links.

    Reliable links (high/medium) keep their own μ. Low / not_reliable links
    are shrunk toward the group median (computed over reliable links only).
    """
    out = mu_links.copy()

    reliable_mask = out["reliability_class"].isin(["high", "medium"])
    n_reliable = reliable_mask.sum()

    if n_reliable == 0:
        # Pathological: no reliable anchors. Skip shrinkage; flag as group_only=NaN.
        out["mu_group_median_vphpl"] = float("nan")
        out["alpha_shrinkage"] = float("nan")
        out["mu_shrunk_vphpl"] = out["mu_obs_median_vphpl"]
        out["mu_source"] = np.where(out["mu_obs_median_vphpl"].notna(),
                                    "self", "group_only")
        return out[MU_COLUMNS]

    k0 = max(float(np.median(out.loc[reliable_mask, "n_episodes_valid"])), 1.0)

    group_medians = (out.loc[reliable_mask]
                        .groupby(group_key)["mu_obs_median_vphpl"]
                        .median()
                        .to_dict())
    overall_median = float(out.loc[reliable_mask, "mu_obs_median_vphpl"].median())

    def _group_for(row):
        g = row[group_key]
        return group_medians.get(g, overall_median)

    out["mu_group_median_vphpl"] = out.apply(_group_for, axis=1)
    out["alpha_shrinkage"] = out["n_episodes_valid"] / (out["n_episodes_valid"] + k0)
    out["alpha_shrinkage"] = out["alpha_shrinkage"].clip(0.0, 1.0)

    needs_shrink = out["reliability_class"].isin(["low", "not_reliable"])
    has_self = out["mu_obs_median_vphpl"].notna()

    out["mu_shrunk_vphpl"] = out["mu_obs_median_vphpl"]
    src = np.array(["self"] * len(out), dtype=object)

    for idx in out.index[needs_shrink & has_self]:
        a = out.at[idx, "alpha_shrinkage"]
        out.at[idx, "mu_shrunk_vphpl"] = (
            a * out.at[idx, "mu_obs_median_vphpl"]
            + (1.0 - a) * out.at[idx, "mu_group_median_vphpl"]
        )
        src[out.index.get_loc(idx)] = "shrunk"

    for idx in out.index[~has_self]:
        out.at[idx, "mu_shrunk_vphpl"] = out.at[idx, "mu_group_median_vphpl"]
        src[out.index.get_loc(idx)] = "group_only"

    out["mu_source"] = src
    return out[MU_COLUMNS]


# ---------------------------------------------------------------------------
# Predicted-vs-observed comparison (all days vs valid only)
# ---------------------------------------------------------------------------
def _huber_fit(X: np.ndarray, y: np.ndarray) -> dict:
    mask = np.isfinite(X).all(axis=1) & np.isfinite(y)
    if mask.sum() < 10:
        return dict(r2=float("nan"), slope=float("nan"), n=int(mask.sum()))
    Xc = X[mask]
    yc = y[mask]
    try:
        h = HuberRegressor(max_iter=500).fit(Xc, yc)
        y_hat = h.predict(Xc)
        ss_res = float(np.sum((yc - y_hat) ** 2))
        ss_tot = float(np.sum((yc - np.mean(yc)) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
        return dict(r2=float(r2),
                    coefs=h.coef_.tolist(),
                    intercept=float(h.intercept_),
                    n=int(mask.sum()),
                    y_obs=yc.tolist(), y_pred=y_hat.tolist())
    except Exception:
        return dict(r2=float("nan"), n=int(mask.sum()))


def predicted_vs_observed(episodes_with_mu: pd.DataFrame,
                          fd_summary: pd.DataFrame,
                          mode: str = "valid_only") -> dict:
    """
    Predicted μ uses BPR-style: μ_hat = capacity * f(D/C, P).
    Observed μ is mu_obs_vphpl (NaN where invalid).

    mode:
      - all_days:    include uncongested/event rows (μ_obs = NaN treated as 0)
      - valid_only:  restrict to is_valid_for_mu rows

    Returns a dict with R², residuals, and the paired y_obs / y_pred arrays
    for the headline scatter.
    """
    df = episodes_with_mu.merge(
        fd_summary[["sensor_uid", "capacity_vphpl"]],
        on="sensor_uid", how="left",
    )

    if mode == "valid_only":
        df = df[df["is_valid_for_mu"]].copy()
    else:
        df["mu_obs_vphpl"] = df["mu_obs_vphpl"].fillna(0.0)

    if df.empty:
        return dict(mode=mode, r2=float("nan"), n=0,
                    y_obs=[], y_pred=[])

    # Features: D/C, P/60
    df["D_over_C"] = df["demand_veh"] / df["capacity_vphpl"].replace(0, np.nan)
    df["P_hours"] = df["P_min"] / 60.0
    X = df[["D_over_C", "P_hours"]].to_numpy(dtype=float)
    y = df["mu_obs_vphpl"].to_numpy(dtype=float)
    fit = _huber_fit(X, y)
    fit["mode"] = mode
    fit["sensor_uids"] = df["sensor_uid"].tolist()
    fit["features"] = ["D_over_C", "P_hours"]
    return fit


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def run_mu(episodes_df: pd.DataFrame,
           reliability_df: pd.DataFrame,
           qc_df: pd.DataFrame,
           fd_summary: pd.DataFrame,
           group_key: str = "corridor") -> dict:
    """End-to-end Stage 4."""
    eps_with_mu = mu_per_episode(episodes_df, qc_df)
    per_link = mu_per_link(eps_with_mu, reliability_df)
    per_link = mu_group_shrinkage(per_link, group_key=group_key)

    cmp_all = predicted_vs_observed(eps_with_mu, fd_summary, mode="all_days")
    cmp_valid = predicted_vs_observed(eps_with_mu, fd_summary, mode="valid_only")

    return dict(
        episodes_with_mu=eps_with_mu,
        per_link=per_link,
        compare_all_days=cmp_all,
        compare_valid_only=cmp_valid,
    )


def write_stage4(result: dict, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # CONTRACTS.md section 3: every output declares its aggregation level
    ep = result["episodes_with_mu"].copy()
    ep["aggregation_level"] = "per_episode"
    ep.to_csv(out_dir / "episodes_with_mu.csv", index=False)
    pl = result["per_link"].copy()
    pl["aggregation_level"] = "sensor_link_median_over_valid_episodes"
    pl.to_csv(out_dir / "mu_per_link.csv", index=False)
    cmp = dict(
        all_days={k: v for k, v in result["compare_all_days"].items()
                  if k not in ("y_obs", "y_pred", "sensor_uids")},
        valid_only={k: v for k, v in result["compare_valid_only"].items()
                    if k not in ("y_obs", "y_pred", "sensor_uids")},
    )
    with open(out_dir / "mu_comparison_summary.json", "w") as f:
        json.dump(cmp, f, indent=2, default=float)
    # Pairs for scatter (stored separately to keep summary JSON small)
    for label, key in [("all_days", "compare_all_days"),
                       ("valid_only", "compare_valid_only")]:
        c = result[key]
        if c.get("y_obs"):
            pd.DataFrame({
                "sensor_uid": c.get("sensor_uids", []),
                "y_obs": c["y_obs"], "y_pred": c["y_pred"],
            }).to_csv(out_dir / f"mu_scatter_{label}.csv", index=False)
