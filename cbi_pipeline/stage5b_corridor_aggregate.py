"""
stage5b_corridor_aggregate.py — corridor-level aggregation of QVDF parameters.

Mirrors the C++ flow:

    g_vdf_type_map[vdf_code].record_qvdf_data(...)
    g_vdf_type_map[vdf_code].computer_avg_parameter(tau)

but adds three things the C++ does not provide:

  1. Bootstrap reliability bounds  (5 / 50 / 95 percentile per parameter)
  2. Prior-weighted shrinkage      (when n_episodes is thin, blend toward
                                    the CBI default - exactly the same
                                    "be very careful" intent the user asked for)
  3. Outlier filter                (drops episodes flagged in Stage 2b
                                    before aggregating)

Aggregation key:  (corridor, period).  Inputs: stage5_qvdf_verification.csv
plus the optional outlier panel from Stage 2b.

Output: link_qvdf_corridor.csv with one row per (corridor, period):

    Q_n_median, Q_n_p5, Q_n_p95, Q_n_iqr, Q_n_n_episodes,
    Q_n_shrunk, Q_n_alpha_shrinkage, Q_n_source,
    ... (same for Q_s, Q_cd, Q_cp, Q_alpha, Q_beta)
    reliability_class            high  / medium / low / not_reliable
    flag_low_sample              n_episodes < min_episodes_for_self
    flag_wide_ci                 (p95 - p5) / median > 0.5
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .stage5_verification import FEASIBLE, _clip


# ---------------------------------------------------------------------------
# Priors (C++ feasibility defaults — the "be very careful" anchors)
# ---------------------------------------------------------------------------
PRIORS = {name: float(spec["default"])
          for name, spec in FEASIBLE.items()
          if name in ("Q_n", "Q_s", "Q_cd", "Q_cp", "Q_alpha", "Q_beta")}

QVDF_PARAMS = ("Q_n", "Q_s", "Q_cd", "Q_cp", "Q_alpha", "Q_beta")


# ---------------------------------------------------------------------------
# Reliability classes (per-corridor-period sample-size tiers)
# ---------------------------------------------------------------------------
RELIABILITY = {
    "high":         20,    # >= 20 valid episodes
    "medium":       10,
    "low":           5,
    "not_reliable":  0,
}


def _reliability_class(n: int) -> str:
    if n >= RELIABILITY["high"]:
        return "high"
    if n >= RELIABILITY["medium"]:
        return "medium"
    if n >= RELIABILITY["low"]:
        return "low"
    return "not_reliable"


# ---------------------------------------------------------------------------
# Bootstrap median CI
# ---------------------------------------------------------------------------
def _bootstrap_median_ci(values: np.ndarray, n_boot: int = 500,
                         alpha: float = 0.10, seed: int = 42) -> tuple:
    """Return (p5, p50, p95) of bootstrap median estimates."""
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) < 3:
        m = float(np.nanmedian(v)) if len(v) else float("nan")
        return (m, m, m)
    rng = np.random.default_rng(seed)
    boot = np.empty(n_boot)
    for i in range(n_boot):
        sample = rng.choice(v, size=len(v), replace=True)
        boot[i] = np.median(sample)
    p5 = float(np.percentile(boot, 100 * alpha / 2))
    p50 = float(np.median(v))
    p95 = float(np.percentile(boot, 100 * (1 - alpha / 2)))
    return (p5, p50, p95)


# ---------------------------------------------------------------------------
# Per-parameter aggregation with shrinkage
# ---------------------------------------------------------------------------
def aggregate_one_param(values: pd.Series,
                        param: str,
                        prior: float,
                        n_boot: int = 500,
                        k0: float = 5.0) -> dict:
    """
    Bootstrap median + shrinkage toward `prior` when n_episodes is thin.

    alpha = n / (n + k0):
       n >> k0  -> alpha -> 1 (trust the data)
       n  << k0 -> alpha -> 0 (trust the prior)
    """
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    n = int(len(v))
    p5, p50, p95 = _bootstrap_median_ci(v, n_boot=n_boot)
    iqr = (float(np.percentile(v, 75) - np.percentile(v, 25))
           if n >= 4 else float("nan"))
    alpha = n / (n + k0) if (n + k0) > 0 else 0.0
    shrunk = alpha * p50 + (1.0 - alpha) * prior if np.isfinite(p50) else prior
    shrunk_clipped = _clip(param, shrunk)
    source = ("self" if alpha >= 0.7
              else "shrunk" if alpha > 0
              else "prior_only")
    return {
        f"{param}_median": p50,
        f"{param}_p5": p5,
        f"{param}_p95": p95,
        f"{param}_iqr": iqr,
        f"{param}_n_episodes": n,
        f"{param}_alpha_shrinkage": float(alpha),
        f"{param}_shrunk": float(shrunk_clipped),
        f"{param}_source": source,
        f"{param}_prior": prior,
    }


# ---------------------------------------------------------------------------
# Corridor x period aggregation
# ---------------------------------------------------------------------------
def aggregate_corridor(qvdf_verify_df: pd.DataFrame,
                       outlier_df: Optional[pd.DataFrame] = None,
                       n_boot: int = 500,
                       k0: float = 5.0,
                       only_status_ok: bool = True) -> pd.DataFrame:
    """
    Aggregate per-episode QVDF params to (corridor, period) rows.

    Parameters
    ----------
    qvdf_verify_df : output of stage5_verification.run_qvdf_verification
    outlier_df     : output of stage2b_measured_diagnostics.run_stage2b['scored']
                     (optional; if provided, flagged episodes are dropped)
    only_status_ok : drop episodes with calibration_status != 'ok' before aggregating
    """
    df = qvdf_verify_df.copy()

    if "corridor" not in df.columns:
        # Derive corridor from sensor_uid if not present (inrix::* belongs to INRIX corridor)
        df["corridor"] = "UNKNOWN"
        # The orchestrator should attach corridor; here we just keep a placeholder.

    if only_status_ok and "calibration_status" in df.columns:
        df = df[df["calibration_status"] == "ok"]

    if outlier_df is not None and not outlier_df.empty:
        keys = (outlier_df[outlier_df["is_outlier"]][["sensor_uid", "date", "period"]]
                .apply(lambda r: f"{r['sensor_uid']}|{r['date']}|{r['period']}", axis=1)
                .tolist())
        df_keys = df.apply(lambda r: f"{r['sensor_uid']}|{r['date']}|{r['period']}", axis=1)
        df = df[~df_keys.isin(keys)]

    rows = []
    for (corridor, period), grp in df.groupby(["corridor", "period"], sort=False):
        n_eps = len(grp)
        row = {
            "corridor": corridor,
            "period": period,
            "n_episodes_used": int(n_eps),
            "n_distinct_sensors": int(grp["sensor_uid"].nunique()),
            "n_distinct_dates":   int(grp["date"].nunique()),
            "reliability_class": _reliability_class(n_eps),
        }
        for param in QVDF_PARAMS:
            row.update(aggregate_one_param(grp[param], param,
                                           prior=PRIORS[param],
                                           n_boot=n_boot, k0=k0))
        # Flags
        med = row["Q_n_median"]
        p95 = row["Q_n_p95"]; p5 = row["Q_n_p5"]
        row["flag_low_sample"] = n_eps < RELIABILITY["low"]
        row["flag_wide_ci_Q_n"] = (np.isfinite(med) and med > 0
                                   and (p95 - p5) / med > 0.5)
        rows.append(row)

    return pd.DataFrame(rows)


def write_stage5b(agg_df: pd.DataFrame, out_dir: Path,
                  also_emit_per_corridor_summary: bool = True) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    agg_df.to_csv(out_dir / "link_qvdf_corridor.csv", index=False)

    summary = dict(
        n_corridor_period=int(len(agg_df)),
        priors_used=PRIORS,
        reliability_classes=RELIABILITY,
        bootstrap_n=500,
        shrinkage_k0=5.0,
        param_median_summary={
            param: {
                "median": float(agg_df[f"{param}_median"].median())
                          if len(agg_df) else float("nan"),
                "shrunk_median": float(agg_df[f"{param}_shrunk"].median())
                                 if len(agg_df) else float("nan"),
            }
            for param in QVDF_PARAMS
        },
    )
    with open(out_dir / "link_qvdf_corridor_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=float)


# ---------------------------------------------------------------------------
# Convenience plot — corridor-period parameter ladder with CI bands
# ---------------------------------------------------------------------------
def plot_corridor_ladder(agg_df: pd.DataFrame, save_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if agg_df.empty:
        return
    params = QVDF_PARAMS
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    for ax, p in zip(axes.flat, params):
        med = agg_df[f"{p}_median"].to_numpy()
        p5 = agg_df[f"{p}_p5"].to_numpy()
        p95 = agg_df[f"{p}_p95"].to_numpy()
        shrunk = agg_df[f"{p}_shrunk"].to_numpy()
        prior = PRIORS[p]
        labels = (agg_df["corridor"].astype(str) + " / "
                  + agg_df["period"].astype(str)).to_list()
        x = np.arange(len(med))
        for i, (xi, m, lo, hi, sh) in enumerate(zip(x, med, p5, p95, shrunk)):
            if np.isfinite(lo) and np.isfinite(hi):
                ax.plot([xi, xi], [lo, hi], color="gray", alpha=0.5, linewidth=1.2)
        ax.scatter(x, med, s=24, color="#1f77b4", label="median", zorder=3)
        ax.scatter(x, shrunk, s=20, color="red", marker="x",
                   label="shrunk", zorder=3)
        ax.axhline(prior, color="purple", linestyle="--", alpha=0.5,
                   label=f"prior = {prior:.2f}")
        ax.set_xticks(x); ax.set_xticklabels(labels, rotation=30, fontsize=7)
        ax.set_ylabel(p)
        ax.set_title(f"{p}  (corridor x period, bootstrap CI gray)")
        ax.legend(fontsize=7); ax.grid(True, alpha=0.3)
    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120)
    plt.close(fig)
