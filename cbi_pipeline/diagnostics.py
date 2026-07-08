"""
diagnostics.py — Section-9 plots, single module owns every figure.

Every stage's `run_*` calls into here; notebooks render via these helpers and
never draw inline. All functions take pandas / numpy arrays and a save path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt           # noqa: E402


# ---------------------------------------------------------------------------
# Stage 1 — QC
# ---------------------------------------------------------------------------
def plot_qc_panel(speed_raw: np.ndarray, speed_clean: np.ndarray,
                  qc_flags: pd.DataFrame, sensor_uid: str,
                  save_path: Path) -> None:
    """Before/after Hampel plus per-check pass rates."""
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=False)
    t = np.arange(len(speed_raw))
    axes[0].plot(t, speed_raw, alpha=0.4, label="raw", linewidth=0.7)
    axes[0].plot(t, speed_clean, label="Hampel-cleaned", linewidth=0.7)
    axes[0].set_title(f"{sensor_uid} — speed (raw vs Hampel)")
    axes[0].set_ylabel("mph")
    axes[0].legend(fontsize=8)
    axes[0].grid(True, alpha=0.3)

    pass_rates = qc_flags[[c for c in qc_flags.columns if c.startswith("qc_")
                           and c != "qc_pass"]].mean()
    axes[1].bar(range(len(pass_rates)), pass_rates.values)
    axes[1].set_xticks(range(len(pass_rates)))
    axes[1].set_xticklabels(pass_rates.index, rotation=30, fontsize=8)
    axes[1].set_ylim(0, 1.05)
    axes[1].set_ylabel("pass rate")
    axes[1].set_title("per-check pass rate")
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def plot_speed_wave_direction(speed_field: np.ndarray,
                              first_drop_times: np.ndarray,
                              sensor_ids: list,
                              bottleneck_idx: Optional[int],
                              save_path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    im = axes[0].imshow(speed_field.T, aspect="auto", origin="lower",
                        cmap="RdYlGn", vmin=0, vmax=80)
    axes[0].set_xlabel("time index")
    axes[0].set_ylabel("sensor (road order ↑)")
    axes[0].set_title("speed_field (mph)")
    fig.colorbar(im, ax=axes[0], shrink=0.8)

    valid = np.isfinite(first_drop_times)
    axes[1].scatter(np.arange(len(first_drop_times))[valid],
                    first_drop_times[valid], s=20)
    if bottleneck_idx is not None:
        axes[1].axvline(bottleneck_idx, color="red", linestyle="--",
                        label=f"b̂={bottleneck_idx}")
    axes[1].set_xlabel("sensor index (road order)")
    axes[1].set_ylabel("first-drop time index")
    axes[1].set_title("congestion-wave timing")
    axes[1].legend(fontsize=8)
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Stage 2 — Episodes
# ---------------------------------------------------------------------------
def plot_episode_taxonomy(episodes_df: pd.DataFrame, save_path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    regime_counts = episodes_df["regime"].value_counts()
    axes[0].bar(regime_counts.index, regime_counts.values)
    axes[0].set_title("episodes by regime")
    axes[0].set_ylabel("# (link × day)")
    axes[0].tick_params(axis="x", rotation=30)
    axes[0].grid(True, alpha=0.3)

    P = episodes_df["P_min"].dropna()
    axes[1].hist(P, bins=60)
    axes[1].axvline(30, color="red", linestyle="--", label="P=30 min (valid threshold)")
    axes[1].set_title("congestion duration P (min) — bimodal check")
    axes[1].set_xlabel("P (min)")
    axes[1].legend(fontsize=8)
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def plot_coverage_table(episodes_df: pd.DataFrame, save_path: Path) -> None:
    pivot = (episodes_df.groupby(["sensor_uid", "regime"]).size()
                       .unstack(fill_value=0))
    fig, ax = plt.subplots(figsize=(6, max(3, 0.18 * len(pivot))))
    im = ax.imshow(pivot.values, aspect="auto", cmap="viridis")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns, rotation=30, fontsize=8)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index, fontsize=6)
    ax.set_title("coverage: # episodes by sensor × regime")
    fig.colorbar(im, ax=ax, shrink=0.7)
    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def plot_reliability_ladder(reliability_df: pd.DataFrame, save_path: Path) -> None:
    order = ["high", "medium", "low", "not_reliable"]
    counts = reliability_df["reliability_class"].value_counts().reindex(order).fillna(0)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(counts.index, counts.values)
    ax.set_ylabel("# sensors")
    ax.set_title("link reliability classification")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def plot_time_space_heatmap(speed_field: np.ndarray,
                            sensor_ids: list,
                            time_axis: np.ndarray,
                            save_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    im = ax.imshow(speed_field.T, aspect="auto", origin="lower",
                   cmap="RdYlGn", vmin=0, vmax=80,
                   extent=[0, speed_field.shape[0],
                           0, speed_field.shape[1]])
    ax.set_xlabel("time index")
    ax.set_ylabel("sensor (road order ↑)")
    ax.set_title("time-space speed heatmap")
    fig.colorbar(im, ax=ax, shrink=0.8, label="mph")
    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Stage 3 — FD
# ---------------------------------------------------------------------------
def plot_robust_fd(df_sensor: pd.DataFrame,
                   fd_payload: dict,
                   save_path: Path) -> None:
    """Regime-coloured speed-flow scatter with model overlay + capacity line."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    k = df_sensor["density_vpm"].to_numpy()
    q = df_sensor["flow_vph"].to_numpy()
    v = df_sensor["speed_mph"].to_numpy()
    capacity = fd_payload["fd"].get("capacity_vphpl")
    v_c = (fd_payload["fd"].get("speed_at_capacity_kph") or 0) / 1.609

    axes[0].scatter(k, q, s=3, alpha=0.3)
    if capacity is not None and np.isfinite(capacity):
        axes[0].axhline(capacity, color="red", linestyle="--",
                        label=f"capacity = {capacity:.0f}")
    axes[0].set_xlabel("density (vpm)")
    axes[0].set_ylabel("flow (vph)")
    axes[0].set_title(f"{fd_payload['sensor_uid']} — q-k")
    axes[0].legend(fontsize=8)
    axes[0].grid(True, alpha=0.3)

    axes[1].scatter(v, q, s=3, alpha=0.3)
    if v_c > 0:
        axes[1].axvline(v_c, color="red", linestyle="--",
                        label=f"v_c = {v_c:.1f} mph")
    axes[1].set_xlabel("speed (mph)")
    axes[1].set_ylabel("flow (vph)")
    axes[1].set_title(f"R²={fd_payload['fd'].get('r_squared', float('nan')):.3f}  "
                      f"model={fd_payload['fd'].get('model')}")
    axes[1].legend(fontsize=8)
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Stage 4 — μ
# ---------------------------------------------------------------------------
def plot_observed_mu_vs_features(episodes_with_mu: pd.DataFrame,
                                 fd_summary: pd.DataFrame,
                                 save_path: Path) -> None:
    """Six-panel: μ_obs vs P, vs C, vs D/C, vs VT², vs D, plus P vs D."""
    df = episodes_with_mu.merge(
        fd_summary[["sensor_uid", "capacity_vphpl"]], on="sensor_uid", how="left",
    )
    df = df[df["mu_obs_vphpl"].notna()].copy()
    if df.empty:
        return

    df["D_over_C"] = df["demand_veh"] / df["capacity_vphpl"].replace(0, np.nan)
    df["VT2_proxy"] = df["P_min"] * (1.0 / df["min_speed_mph"].replace(0, np.nan))

    panels = [
        ("P_min", "μ_obs", "P (min)", "mu_obs_vphpl"),
        ("capacity_vphpl", "μ_obs", "capacity (vphpl)", "mu_obs_vphpl"),
        ("D_over_C", "μ_obs", "D/C", "mu_obs_vphpl"),
        ("VT2_proxy", "μ_obs", "VT² proxy", "mu_obs_vphpl"),
        ("demand_veh", "μ_obs", "demand D (veh)", "mu_obs_vphpl"),
        ("P_min", "demand_veh", "P (min)", "demand_veh"),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    for ax, (xk, _, xl, yk) in zip(axes.flat, panels):
        ax.scatter(df[xk], df[yk], s=8, alpha=0.5)
        ax.set_xlabel(xl)
        ax.set_ylabel(yk)
        ax.grid(True, alpha=0.3)
    fig.suptitle("Observed μ vs congestion features (valid episodes only)")
    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def plot_predicted_vs_observed_mu(compare_all: dict,
                                  compare_valid: dict,
                                  save_path: Path) -> None:
    """Side-by-side: 'all days' | 'valid congested only'.  THE headline plot."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharex=True, sharey=True)
    for ax, c, label in [(axes[0], compare_all, "all days"),
                          (axes[1], compare_valid, "valid congested only")]:
        y_obs = np.asarray(c.get("y_obs", []), dtype=float)
        y_pred = np.asarray(c.get("y_pred", []), dtype=float)
        if len(y_obs):
            ax.scatter(y_obs, y_pred, s=10, alpha=0.5)
            lo = float(np.nanmin([y_obs.min(), y_pred.min()]))
            hi = float(np.nanmax([y_obs.max(), y_pred.max()]))
            ax.plot([lo, hi], [lo, hi], "k--", linewidth=0.8, alpha=0.6)
        ax.set_xlabel("observed μ (vphpl)")
        ax.set_ylabel("predicted μ (vphpl)")
        ax.set_title(f"{label} — R² = {c.get('r2', float('nan')):.3f}, n = {c.get('n', 0)}")
        ax.grid(True, alpha=0.3)
    fig.suptitle("Predicted vs Observed μ — side-by-side mode comparison")
    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Stage 5 — QVDF + Shape (FIXED-layout figures)
# ---------------------------------------------------------------------------
def _scatter_xy(ax, x, y, label, lim=None):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    ax.scatter(x[mask], y[mask], s=10, alpha=0.55)
    if mask.any():
        if lim is None:
            lo = float(np.nanmin([x[mask].min(), y[mask].min()]))
            hi = float(np.nanmax([x[mask].max(), y[mask].max()]))
        else:
            lo, hi = lim
        ax.plot([lo, hi], [lo, hi], "k--", linewidth=0.8, alpha=0.5)
        if mask.sum() >= 3:
            r = float(np.corrcoef(x[mask], y[mask])[0, 1])
            ax.set_title(f"{label}  r={r:.3f}  n={int(mask.sum())}")
        else:
            ax.set_title(f"{label}  n={int(mask.sum())}")
    else:
        ax.set_title(f"{label}  (empty)")
    ax.grid(True, alpha=0.3)


def plot_P_pred_vs_obs(predictions: pd.DataFrame, save_path: Path,
                       title_prefix: str = "") -> None:
    fig, ax = plt.subplots(figsize=(6, 5))
    _scatter_xy(ax,
                predictions["P_hours"].to_numpy() * 60.0,
                predictions["P_pred_hours"].to_numpy() * 60.0,
                f"{title_prefix}P_pred vs P_obs (min)")
    ax.set_xlabel("P observed (min)")
    ax.set_ylabel("P predicted (min)")
    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def plot_mu_pred_vs_obs_stage5(predictions: pd.DataFrame,
                               mu_per_link: pd.DataFrame,
                               save_path: Path,
                               title_prefix: str = "") -> None:
    """μ_pred from QVDF capacity, μ_obs from per-link Stage-4 medians."""
    df = predictions.merge(mu_per_link[["sensor_uid", "mu_obs_median_vphpl"]],
                           on="sensor_uid", how="left")
    # μ_pred is a derived saturation flow during congestion; approximate as capacity
    # * (vf - v_t2_pred) / vf — falls back to capacity if v_t2 unavailable.
    cap = df.get("capacity_vphpl")
    if cap is not None:
        df["mu_pred_vphpl"] = cap.fillna(2000.0) * 0.95
    else:
        df["mu_pred_vphpl"] = 2000.0

    fig, ax = plt.subplots(figsize=(6, 5))
    _scatter_xy(ax,
                df["mu_obs_median_vphpl"].to_numpy(),
                df["mu_pred_vphpl"].to_numpy(),
                f"{title_prefix}mu_pred vs mu_obs")
    ax.set_xlabel("mu observed (vphpl)")
    ax.set_ylabel("mu predicted (vphpl)")
    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def plot_observed_distributions(predictions: pd.DataFrame, save_path: Path,
                                title_prefix: str = "") -> None:
    fig, axes = plt.subplots(2, 3, figsize=(13, 7))
    cols = [("P_min", "P (min)"),
            ("min_speed_mph", "min speed (mph)"),
            ("D_over_C", "D/C"),
            ("demand_veh", "demand D (veh)"),
            ("v_c_mph", "speed at capacity (mph)"),
            ("capacity_vphpl", "capacity (vphpl)")]
    for ax, (col, lab) in zip(axes.flat, cols):
        if col in predictions.columns:
            s = predictions[col].dropna()
            if len(s):
                ax.hist(s, bins=40)
            ax.set_xlabel(lab)
            ax.grid(True, alpha=0.3)
    fig.suptitle(f"{title_prefix}observed distributions")
    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def plot_qvdf_vs_shape(predictions: pd.DataFrame, save_path: Path,
                       which: str = "avg_speed",
                       title_prefix: str = "") -> None:
    """which ∈ {min_speed, avg_speed, speed}"""
    if which == "min_speed":
        x, y = predictions["v_t2_pred_mph"], predictions["min_speed_mph"]
        label = "v_t2 (QVDF vs obs)"
    elif which == "avg_speed":
        x, y = predictions["v_avg_pred_mph"], predictions["v_avg_shape_mph"]
        label = "v_avg (QVDF vs shape)"
    else:
        x, y = predictions["v_t2_pred_mph"], predictions["v_avg_shape_mph"]
        label = "v_t2 (QVDF) vs v_avg (shape)"
    fig, ax = plt.subplots(figsize=(6, 5))
    _scatter_xy(ax, x.to_numpy(), y.to_numpy(), f"{title_prefix}{label}")
    ax.set_xlabel("QVDF predicted (mph)")
    ax.set_ylabel("shape or observed (mph)")
    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def plot_P_heatmap(predictions: pd.DataFrame, save_path: Path,
                   value_col: str = "P_min",
                   title_prefix: str = "") -> None:
    """Sensor × period heatmap (mean over days)."""
    if value_col not in predictions.columns or predictions.empty:
        return
    piv = (predictions.groupby(["sensor_uid", "period"])[value_col]
                      .mean().unstack(fill_value=np.nan))
    if piv.empty:
        return
    fig, ax = plt.subplots(figsize=(7, max(3, 0.18 * len(piv))))
    im = ax.imshow(piv.values, aspect="auto", cmap="magma")
    ax.set_xticks(range(len(piv.columns)))
    ax.set_xticklabels(piv.columns)
    ax.set_yticks(range(len(piv.index)))
    ax.set_yticklabels(piv.index, fontsize=6)
    ax.set_title(f"{title_prefix}{value_col} heatmap (sensor × period)")
    fig.colorbar(im, ax=ax, shrink=0.7)
    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def plot_td_speed(qc_df: pd.DataFrame,
                  sensor_uid: str,
                  period_label: str,
                  save_path: Path,
                  v_c_mph: float = 50.0,
                  v_f_mph: float = 70.0) -> None:
    """
    Time-domain speed plot for one sensor × period, overlaid for all dates.
    Mirrors out_integrated_qvdf_shape_FIXED's `td_speed` panel layout.
    """
    sub = qc_df[(qc_df["sensor_uid"] == sensor_uid)]
    if sub.empty or "datetime" not in sub.columns:
        return
    sub = sub.copy()
    sub["hour"] = pd.to_datetime(sub["datetime"]).dt.hour
    sub["date"] = pd.to_datetime(sub["datetime"]).dt.date
    sub["minute_of_day"] = (pd.to_datetime(sub["datetime"]).dt.hour * 60
                            + pd.to_datetime(sub["datetime"]).dt.minute)

    fig, ax = plt.subplots(figsize=(9, 5))
    for d, grp in sub.groupby("date"):
        ax.plot(grp["minute_of_day"], grp["speed_mph_clean"],
                alpha=0.35, linewidth=0.7)
    ax.axhline(v_c_mph, color="red", linestyle="--", alpha=0.6,
               label=f"v_c={v_c_mph:.0f} mph")
    ax.axhline(v_f_mph, color="green", linestyle="--", alpha=0.6,
               label=f"v_f={v_f_mph:.0f} mph")
    ax.set_xlabel("minute of day")
    ax.set_ylabel("speed (mph)")
    ax.set_title(f"{sensor_uid}  {period_label}  td_speed (all dates)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def plot_shrinkage_ladder(mu_per_link: pd.DataFrame, save_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    df = mu_per_link.copy()
    df = df.sort_values("n_episodes_valid")
    x = np.arange(len(df))
    ax.scatter(x, df["mu_obs_median_vphpl"], s=12, label="μ_obs", alpha=0.6)
    ax.scatter(x, df["mu_shrunk_vphpl"], s=12, label="μ_shrunk", alpha=0.6)
    ax.scatter(x, df["mu_group_median_vphpl"], s=8, label="μ_group", alpha=0.4,
               marker="x")
    ax.set_xlabel("link (sorted by n_episodes_valid)")
    ax.set_ylabel("μ (vphpl)")
    ax.set_title("group-shrinkage ladder")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120)
    plt.close(fig)
