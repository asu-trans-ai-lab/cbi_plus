"""
stage2b_measured_diagnostics.py — early outlier identification on MEASURED
quantities only, before any QVDF or BPR model touches them.

Three observed-vs-observed scatter plots flag episodes that violate basic
physics or fall far outside the corridor's distribution. The point is to
catch bad episodes BEFORE they poison Stage 4 (mu) and Stage 5 (QVDF):

    Panel A.   measured D/C  vs  measured P
                  expectation:  P approx (D/C)^n, n in [1.0, 1.5]
                  physical violation:  D/C > 1 but P = 0
                                       D/C < 0.5 but P > 30 min  (rare, queue spillover from other periods)

    Panel B.   measured D/C  vs  measured mu_obs
                  expectation:  mu_obs stays under capacity; weakly inverse with D/C
                                in the oversaturated regime
                  physical violation:  mu_obs > capacity
                                       mu_obs < 0.3 * capacity AND D/C > 1.5 (queue is starving)

    Panel C.   measured P  vs  measured V_t2
                  expectation:  longer P -> lower V_t2 (more elasticity)
                  physical violation:  V_t2 >= v_c (episode shouldn't be valid)
                                       V_t2 << 5 mph (sensor jam or stopped traffic)

For each scatter we run a robust Huber fit and flag points with
|residual| > k * MAD (k=3 by default). Combined with the physical-violation
filters, each episode gets a list of outlier reason codes.

Outputs:
    stage2b_measured/
        measured_episodes.csv         # one row per valid episode + outlier flags
        outliers.csv                  # only flagged episodes + reasons
        outlier_summary.json
        figures/
            A__doc_vs_P.png
            B__doc_vs_mu.png
            C__P_vs_vt2.png
            outlier_overview.png
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib

# figure emission must not clobber a notebook's interactive/inline backend
if not str(matplotlib.get_backend()).lower().startswith(
        ("inline", "module://matplotlib_inline", "nbagg", "ipympl", "widget", "module://ipympl")):
    matplotlib.use("Agg")
import matplotlib.pyplot as plt           # noqa: E402

from sklearn.linear_model import HuberRegressor


# ---------------------------------------------------------------------------
# Outlier rule definitions
# ---------------------------------------------------------------------------
OUTLIER_RULES = {
    "doc_high_P_zero":      "D/C > 1 hr  but  P < 15 min   (oversaturated without congestion - sensor mismatch)",
    "doc_low_P_high":       "D/C < 0.5 hr  but  P > 60 min  (long P with low demand - upstream spillback)",
    "mu_above_capacity":    "mu_obs > 1.05 * capacity        (impossible discharge - synth/measurement error)",
    "mu_starved":           "D/C > 1.5 hr AND mu_obs < 0.3 * capacity  (queue starvation - bottleneck downstream)",
    "vt2_above_vc":         "V_t2 >= v_c       (episode should not have been is_valid_for_mu)",
    "vt2_too_low":          "V_t2 < 5 mph      (sensor jam / stopped traffic - check QC)",
    "huber_resid_doc_P":    "Huber residual on log(P) vs log(D/C) exceeds 3 MAD",
    "huber_resid_doc_mu":   "Huber residual on mu vs D/C exceeds 3 MAD",
    "huber_resid_P_vt2":    "Huber residual on log(V_t2) vs log(P) exceeds 3 MAD",
}


# ---------------------------------------------------------------------------
# Per-episode measured triple
# ---------------------------------------------------------------------------
def build_measured_panel(episodes_df: pd.DataFrame,
                         qc_df: pd.DataFrame,
                         fd_summary: pd.DataFrame) -> pd.DataFrame:
    """
    Attach measured D/C (in HOURS — C++ convention), measured mu_obs (median q
    over discharge window), and measured V_t2 to every valid episode.
    Returns a long DataFrame ready for outlier scoring.
    """
    eps = episodes_df[episodes_df["is_valid_for_mu"]].copy()
    if eps.empty:
        return pd.DataFrame()

    # Merge capacity from FD summary
    eps = eps.merge(
        fd_summary[["sensor_uid", "capacity_vphpl"]],
        on="sensor_uid", how="left",
    )
    eps["D_over_C_hours"] = eps["demand_veh"] / np.maximum(eps["capacity_vphpl"], 1e-3)
    eps["P_hours"] = eps["P_min"] / 60.0

    # mu_obs = median q over the discharge window. Delegate to stage4's
    # mu_episode — the ONE canonical implementation (period-aware slicing).
    # This loop previously re-implemented it against the full-day frame, so its
    # indices landed hours off and its "mu" was uncorrelated with stage 4's
    # (independent result review: ratio ~4.3x, corr -0.01, and a 78%
    # "mu_starved" outlier rate that was pure artifact).
    from .stage4_mu_validation import mu_episode
    qc_df = qc_df.copy()
    qc_df["date"] = pd.to_datetime(qc_df["datetime"]).dt.date.astype(str)
    eps["mu_obs_vphpl"] = [mu_episode(ep, qc_df) for _, ep in eps.iterrows()]
    return eps[[
        "sensor_uid", "corridor", "date", "period",
        "P_min", "P_hours", "min_speed_mph", "v_c_mph",
        "demand_veh", "capacity_vphpl",
        "D_over_C_hours", "mu_obs_vphpl",
    ]].rename(columns={"min_speed_mph": "V_t2_mph"})


# ---------------------------------------------------------------------------
# Robust residual flagging
# ---------------------------------------------------------------------------
def _huber_residual_outliers(x: np.ndarray, y: np.ndarray,
                             log_x: bool = False, log_y: bool = False,
                             k_mad: float = 3.0) -> np.ndarray:
    """Flag points whose Huber-fit residual exceeds k_mad * MAD."""
    if log_x:
        x_in = np.log(np.maximum(x, 1e-6))
    else:
        x_in = x
    if log_y:
        y_in = np.log(np.maximum(y, 1e-6))
    else:
        y_in = y
    mask = np.isfinite(x_in) & np.isfinite(y_in)
    flag = np.zeros(len(x), dtype=bool)
    if mask.sum() < 8:
        return flag
    try:
        h = HuberRegressor(max_iter=400).fit(x_in[mask].reshape(-1, 1), y_in[mask])
        y_hat = h.predict(x_in[mask].reshape(-1, 1))
        resid = y_in[mask] - y_hat
        mad = float(np.median(np.abs(resid - np.median(resid)))) * 1.4826
        if mad <= 0:
            return flag
        is_out = np.abs(resid) > k_mad * mad
        flag_idx = np.where(mask)[0][is_out]
        flag[flag_idx] = True
    except Exception:
        pass
    return flag


def score_outliers(panel: pd.DataFrame, k_mad: float = 3.0) -> pd.DataFrame:
    """Apply all outlier rules; return panel + per-rule boolean columns + reason string."""
    out = panel.copy()
    if out.empty:
        return out

    cap = out["capacity_vphpl"].fillna(2000.0)
    vc = out["v_c_mph"].fillna(50.0)

    # Physical-violation rules
    out["flag_doc_high_P_zero"] = (out["D_over_C_hours"] > 1.0) & (out["P_min"] < 15.0)
    out["flag_doc_low_P_high"]  = (out["D_over_C_hours"] < 0.5) & (out["P_min"] > 60.0)
    out["flag_mu_above_capacity"] = out["mu_obs_vphpl"] > (1.05 * cap)
    out["flag_mu_starved"] = ((out["D_over_C_hours"] > 1.5)
                              & (out["mu_obs_vphpl"] < 0.3 * cap))
    out["flag_vt2_above_vc"] = out["V_t2_mph"] >= vc
    out["flag_vt2_too_low"] = out["V_t2_mph"] < 5.0

    # Robust-residual rules
    x_doc = out["D_over_C_hours"].to_numpy()
    y_P   = out["P_hours"].to_numpy()
    y_mu  = out["mu_obs_vphpl"].to_numpy()
    y_vt2 = out["V_t2_mph"].to_numpy()
    x_P   = out["P_hours"].to_numpy()

    out["flag_huber_resid_doc_P"]  = _huber_residual_outliers(x_doc, y_P,
                                                              log_x=True, log_y=True,
                                                              k_mad=k_mad)
    out["flag_huber_resid_doc_mu"] = _huber_residual_outliers(x_doc, y_mu,
                                                              log_x=False, log_y=False,
                                                              k_mad=k_mad)
    out["flag_huber_resid_P_vt2"]  = _huber_residual_outliers(x_P, y_vt2,
                                                              log_x=True, log_y=True,
                                                              k_mad=k_mad)

    # Aggregate
    flag_cols = [c for c in out.columns if c.startswith("flag_")]
    out["is_outlier"] = out[flag_cols].any(axis=1)
    out["outlier_n_flags"] = out[flag_cols].sum(axis=1)
    out["outlier_reasons"] = out.apply(
        lambda r: ";".join([c.replace("flag_", "") for c in flag_cols if r[c]]),
        axis=1,
    )
    return out


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------
def _scatter_with_outliers(ax, x, y, mask_out, xlabel, ylabel, title,
                           log_x=False, log_y=False):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask_in = np.isfinite(x) & np.isfinite(y) & ~mask_out
    mask_o  = np.isfinite(x) & np.isfinite(y) & mask_out
    ax.scatter(x[mask_in], y[mask_in], s=14, alpha=0.55, color="#1f77b4",
               label=f"clean ({mask_in.sum()})")
    ax.scatter(x[mask_o], y[mask_o], s=18, alpha=0.9, color="red",
               marker="x", label=f"outlier ({mask_o.sum()})")
    if log_x:
        ax.set_xscale("log")
    if log_y:
        ax.set_yscale("log")
    ax.set_xlabel(xlabel); ax.set_ylabel(ylabel); ax.set_title(title)
    ax.legend(fontsize=8); ax.grid(True, alpha=0.3)


def emit_figures(scored: pd.DataFrame, out_dir: Path) -> None:
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    if scored.empty:
        return

    mask_out = scored["is_outlier"].to_numpy()

    # Panel A — D/C vs P (log-log)
    fig, ax = plt.subplots(figsize=(7, 5))
    _scatter_with_outliers(ax, scored["D_over_C_hours"], scored["P_hours"],
                           mask_out, "measured D/C (hours)", "measured P (hours)",
                           "Panel A: D/C vs P (early outlier screen)",
                           log_x=True, log_y=True)
    fig.tight_layout(); fig.savefig(fig_dir / "A__doc_vs_P.png", dpi=120); plt.close(fig)

    # Panel B — D/C vs mu_obs
    fig, ax = plt.subplots(figsize=(7, 5))
    _scatter_with_outliers(ax, scored["D_over_C_hours"], scored["mu_obs_vphpl"],
                           mask_out, "measured D/C (hours)",
                           "measured mu_obs (vphpl)",
                           "Panel B: D/C vs measured mu (early outlier screen)")
    cap_med = scored["capacity_vphpl"].median()
    if np.isfinite(cap_med):
        ax.axhline(cap_med, color="purple", linestyle="--", alpha=0.6,
                   label=f"median capacity = {cap_med:.0f}")
        ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(fig_dir / "B__doc_vs_mu.png", dpi=120); plt.close(fig)

    # Panel C — P vs V_t2
    fig, ax = plt.subplots(figsize=(7, 5))
    _scatter_with_outliers(ax, scored["P_hours"], scored["V_t2_mph"],
                           mask_out, "measured P (hours)", "measured V_t2 (mph)",
                           "Panel C: P vs V_t2 (early outlier screen)",
                           log_x=True)
    vc_med = scored["v_c_mph"].median()
    if np.isfinite(vc_med):
        ax.axhline(vc_med, color="purple", linestyle="--", alpha=0.6,
                   label=f"median v_c = {vc_med:.0f}")
        ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(fig_dir / "C__P_vs_vt2.png", dpi=120); plt.close(fig)

    # Overview: 3 panels + reason histogram
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    _scatter_with_outliers(axes[0, 0], scored["D_over_C_hours"], scored["P_hours"],
                           mask_out, "D/C (hours)", "P (hours)", "A: D/C vs P",
                           log_x=True, log_y=True)
    _scatter_with_outliers(axes[0, 1], scored["D_over_C_hours"], scored["mu_obs_vphpl"],
                           mask_out, "D/C (hours)", "mu_obs (vphpl)",
                           "B: D/C vs mu")
    _scatter_with_outliers(axes[1, 0], scored["P_hours"], scored["V_t2_mph"],
                           mask_out, "P (hours)", "V_t2 (mph)", "C: P vs V_t2",
                           log_x=True)
    # Reason-count bar
    ax = axes[1, 1]
    reason_counts = {}
    for r in scored["outlier_reasons"]:
        if not r:
            continue
        for code in r.split(";"):
            reason_counts[code] = reason_counts.get(code, 0) + 1
    if reason_counts:
        names = list(reason_counts.keys())
        vals = [reason_counts[n] for n in names]
        ax.barh(names, vals, color="red", alpha=0.6)
        ax.set_xlabel("# episodes")
        ax.set_title(f"outlier reasons  ({mask_out.sum()} / {len(scored)} flagged)")
    else:
        ax.text(0.5, 0.5, "no outliers found", ha="center", va="center",
                transform=ax.transAxes)
        ax.set_title("outlier reasons")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(fig_dir / "outlier_overview.png", dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def run_stage2b(episodes_df: pd.DataFrame,
                qc_df: pd.DataFrame,
                fd_summary: pd.DataFrame,
                out_dir: Path,
                k_mad: float = 3.0) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    panel = build_measured_panel(episodes_df, qc_df, fd_summary)
    scored = score_outliers(panel, k_mad=k_mad)
    scored.to_csv(out_dir / "measured_episodes.csv", index=False)
    outliers_only = scored[scored["is_outlier"]]
    outliers_only.to_csv(out_dir / "outliers.csv", index=False)

    summary = dict(
        n_episodes=int(len(scored)),
        n_outliers=int(outliers_only["sensor_uid"].count() if not outliers_only.empty else 0),
        outlier_pct=float(outliers_only["sensor_uid"].count() / max(len(scored), 1) * 100)
                    if not scored.empty else 0.0,
        reasons_count={c.replace("flag_", ""): int(scored[c].sum())
                       for c in scored.columns if c.startswith("flag_")},
        rule_descriptions=OUTLIER_RULES,
    )
    with open(out_dir / "outlier_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=float)

    emit_figures(scored, out_dir)
    return dict(scored=scored, summary=summary)
