"""
stage4_verification.py — step-by-step audit at Stage 4 (mu validation).

For every valid episode, list and plot each upstream quantity that feeds mu,
so a human can verify the inputs before trusting the output:

    Step A. v_cut_off (V_c)
              - prior:        the user-supplied / S3-default speed-at-capacity
              - calibrated:   v_c implied by the FD fit (PeMS) or the CBI prior (TMC)
              - source:       'fitted_from_data' or 'user_prior'

    Step B. Capacity
              - prior:        what we entered with (s3_prior preset or user value)
              - calibrated:   capacity from the FD fit (PeMS) or = lane_capacity prior (TMC)
              - source:       'fitted_from_data' or 'cbi_inverse_prior'

    Step C. P (congestion duration)
              - P_min_observed:  from CBI detector (t3 - t0) * dt
              - t0/t2/t3 indices and wallclock times

    Step D. V_t2 (minimum speed in episode)
              - v_t2_observed:   min(v) over (t0, t3]

    Step E. v(t) trace
              - the full speed series within (t0, t3]
              - the discharge-window subset (used for mu)

    Step F. Discharge window
              - (d_start, d_end): the queue-dissipating interval used for mu
              - n_intervals:      how many 5-min points entered the median

    Step G. mu derivation (the output)
              - mu_obs_vphpl  = median q over discharge window
              - mu_check_vphpl = inverse-S3(mean v over discharge) for cross-check
              - consistency  = |mu_obs - mu_check| / mu_obs   (should be small)

Each episode also gets a 4-panel verification figure so a human can eyeball
the v(t) trace with the v_c line, t0/t2/t3 verticals, and discharge-window
shading. This is the per-corridor quality-gate audit artifact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt           # noqa: E402

from .io_unified import synthesize_volume_s3
from .schemas import DEFAULT_S3_PARAMS, PERIOD_SLICE_BOUNDS, period_hour_mask


# ---------------------------------------------------------------------------
# Per-episode audit row
# ---------------------------------------------------------------------------
def _episode_window(qc_df_sensor_date: pd.DataFrame,
                    t0: int, t3: int) -> pd.DataFrame:
    """Return the qc_df slice (t0, t3] for one sensor-date, sorted by datetime."""
    s = qc_df_sensor_date.sort_values("datetime").reset_index(drop=True)
    t0 = max(0, int(t0))
    t3 = min(len(s) - 1, int(t3))
    if t3 <= t0:
        return s.iloc[0:0]
    return s.iloc[t0:t3 + 1].copy()


def verify_episode(episode_row: pd.Series,
                   qc_df: pd.DataFrame,
                   fd_payload: dict,
                   s3_prior: dict = None) -> dict:
    """
    Step-by-step audit of one episode. Returns a verification dict ready to
    serialize as a CSV row and to plot.

    Parameters
    ----------
    episode_row : one row of episodes_per_link_day.csv
    qc_df       : full Stage-1 QC table (filtered to one sensor-date inside)
    fd_payload  : full sensor payload from stage3_fd/<sensor>.json — must contain
                  both `fd` and `meta` blocks (the latter has `flow_synthetic`)
    s3_prior    : dict of {vf_mph, k_critical_vpm, s3_m, lane_capacity_vphpl}
                  — used for the inverse-S3 consistency check
    """
    if s3_prior is None:
        s3_prior = DEFAULT_S3_PARAMS

    sid = episode_row["sensor_uid"]
    date = str(episode_row["date"])
    period = episode_row.get("period", "all_day")

    sensor_date_df = qc_df[
        (qc_df["sensor_uid"] == sid)
        & (pd.to_datetime(qc_df["datetime"]).dt.date.astype(str) == date)
    ].sort_values("datetime").reset_index(drop=True)
    # Episode indices are PERIOD-relative (stage2 groups by sensor/date/period),
    # so slice the day down to the same period before any iloc lookup.
    if period in PERIOD_SLICE_BOUNDS:
        hours = pd.to_datetime(sensor_date_df["datetime"]).dt.hour
        sensor_date_df = sensor_date_df[period_hour_mask(hours, period)].reset_index(drop=True)

    t0 = int(episode_row["t0_index"])
    t2 = int(episode_row["t2_index"])
    t3 = int(episode_row["t3_index"])

    win = _episode_window(sensor_date_df, t0, t3)

    fd_block = (fd_payload or {}).get("fd", {}) or {}
    fd_meta = (fd_payload or {}).get("meta", {}) or {}
    flow_synthetic = bool(fd_meta.get("flow_synthetic", False))

    # ---- Step A. V_cut_off ------------------------------------------------
    v_c_prior = float(episode_row.get("v_c_mph", float("nan")))
    v_c_kph_fitted = fd_block.get("speed_at_capacity_kph")
    v_c_calibrated = (float(v_c_kph_fitted) / 1.609
                      if v_c_kph_fitted is not None else float("nan"))
    # PeMS (real flow) -> fitted_from_data; INRIX (synthesized flow) -> CBI prior.
    v_c_source = "user_prior_or_cbi_inverse" if flow_synthetic else "fitted_from_data"

    # ---- Step B. Capacity -------------------------------------------------
    capacity_prior = float(s3_prior.get("lane_capacity_vphpl", float("nan")))
    capacity_fitted = float(fd_block.get("capacity_vphpl", float("nan")))
    capacity_source = "cbi_inverse_prior" if flow_synthetic else "fitted_from_data"

    # ---- Step C. P --------------------------------------------------------
    P_min = float(episode_row.get("P_min", float("nan")))
    t0_time = win["datetime"].iloc[0] if len(win) else None
    t3_time = win["datetime"].iloc[-1] if len(win) else None
    t2_offset = max(0, min(t2 - t0, len(win) - 1)) if len(win) else 0
    t2_time = win["datetime"].iloc[t2_offset] if len(win) else None

    # ---- Step D. V_t2 -----------------------------------------------------
    v_t2 = float(episode_row.get("min_speed_mph", float("nan")))

    # ---- Step E + F. v(t) and discharge window ----------------------------
    d_start = episode_row.get("discharge_start_idx")
    d_end = episode_row.get("discharge_end_idx")
    has_d_win = pd.notna(d_start) and pd.notna(d_end)
    d_start = int(d_start) if has_d_win else None
    d_end = int(d_end) if has_d_win else None

    discharge_df = pd.DataFrame()
    if has_d_win and d_start <= d_end and d_end < len(sensor_date_df):
        discharge_df = sensor_date_df.iloc[d_start:d_end + 1].copy()

    # ---- Step G. mu derivation -------------------------------------------
    mu_obs = float("nan")
    mu_check = float("nan")
    consistency = float("nan")
    if len(discharge_df):
        if "flow_vph" in discharge_df.columns and discharge_df["flow_vph"].notna().any():
            mu_obs = float(np.nanmedian(discharge_df["flow_vph"]))
        # consistency check: inverse-S3 from the mean discharge-window speed
        v_mean = float(np.nanmean(discharge_df["speed_mph_clean"]
                                  if "speed_mph_clean" in discharge_df.columns
                                  else discharge_df["speed_mph"]))
        q_back = synthesize_volume_s3(
            np.array([v_mean]),
            vf_mph=s3_prior.get("vf_mph", 70.0),
            k_critical_vpm=s3_prior.get("k_critical_vpm", 45.0),
            s3_m=s3_prior.get("s3_m", 4.0),
            lane_capacity_vphpl=s3_prior.get("lane_capacity_vphpl", 2200.0),
        )
        mu_check = float(q_back[0]) if np.isfinite(q_back[0]) else float("nan")
        if np.isfinite(mu_obs) and mu_obs > 0:
            consistency = float(abs(mu_obs - mu_check) / mu_obs)

    return dict(
        sensor_uid=sid, date=date, period=period,
        # Step A
        v_c_prior_mph=v_c_prior,
        v_c_calibrated_mph=v_c_calibrated,
        v_c_source=v_c_source,
        # Step B
        capacity_prior_vphpl=capacity_prior,
        capacity_calibrated_vphpl=capacity_fitted,
        capacity_source=capacity_source,
        # Step C
        P_min=P_min,
        t0_idx=t0, t2_idx=t2, t3_idx=t3,
        t0_time=str(t0_time) if t0_time is not None else "",
        t2_time=str(t2_time) if t2_time is not None else "",
        t3_time=str(t3_time) if t3_time is not None else "",
        # Step D
        v_t2_mph=v_t2,
        # Step F
        discharge_start_idx=d_start, discharge_end_idx=d_end,
        discharge_n_intervals=int(len(discharge_df)),
        discharge_duration_min=float(len(discharge_df) * 5.0),
        # Step G
        mu_obs_vphpl=mu_obs,
        mu_check_inverse_s3_vphpl=mu_check,
        mu_consistency=consistency,
        # Bookkeeping for the plotter
        _sensor_date_df=sensor_date_df,
        _win=win,
        _discharge_df=discharge_df,
    )


# ---------------------------------------------------------------------------
# 4-panel verification plot
# ---------------------------------------------------------------------------
def plot_episode_verification(verif: dict, save_path: Path,
                              s3_prior: dict = None) -> None:
    """4 panels: v(t), q(t), k(t) (if available), mu derivation."""
    if s3_prior is None:
        s3_prior = DEFAULT_S3_PARAMS
    sdf = verif["_sensor_date_df"]
    win = verif["_win"]
    ddf = verif["_discharge_df"]
    if sdf.empty:
        return

    t = pd.to_datetime(sdf["datetime"])
    minute_of_day = t.dt.hour * 60 + t.dt.minute
    v = (sdf["speed_mph_clean"] if "speed_mph_clean" in sdf.columns
         else sdf["speed_mph"]).to_numpy()
    q = sdf["flow_vph"].to_numpy() if "flow_vph" in sdf.columns else np.full_like(v, np.nan)
    k_arr = sdf["density_vpm"].to_numpy() if "density_vpm" in sdf.columns else np.full_like(v, np.nan)

    fig, axes = plt.subplots(2, 2, figsize=(13, 8), sharex=False)

    # ---- Panel 1: v(t) with v_c line + t0/t2/t3 verticals ----------------
    ax = axes[0, 0]
    ax.plot(minute_of_day, v, color="#1f77b4", linewidth=0.9, label="v(t)")
    if not win.empty:
        mod_win = pd.to_datetime(win["datetime"])
        mod_w = mod_win.dt.hour * 60 + mod_win.dt.minute
        ax.fill_between(mod_w, 0, 90, alpha=0.08, color="orange",
                        label="congestion window (t0,t3]")
    if not ddf.empty:
        mod_d = pd.to_datetime(ddf["datetime"])
        mod_d = mod_d.dt.hour * 60 + mod_d.dt.minute
        ax.fill_between(mod_d, 0, 90, alpha=0.18, color="red",
                        label="discharge window D_e")
    ax.axhline(verif["v_c_prior_mph"], color="red", linestyle="--", alpha=0.7,
               label=f"v_cut_off prior = {verif['v_c_prior_mph']:.1f}")
    if np.isfinite(verif["v_c_calibrated_mph"]):
        ax.axhline(verif["v_c_calibrated_mph"], color="purple", linestyle=":", alpha=0.7,
                   label=f"v_cut_off calib = {verif['v_c_calibrated_mph']:.1f}")
    ax.axhline(verif["v_t2_mph"], color="black", linestyle="-.", alpha=0.5,
               label=f"V_t2 = {verif['v_t2_mph']:.1f} mph")
    ax.set_xlabel("minute of day")
    ax.set_ylabel("speed (mph)")
    ax.set_title(f"Step C/D/E: v(t)  |  P={verif['P_min']:.0f} min  V_t2={verif['v_t2_mph']:.1f} mph")
    ax.set_ylim(0, 90)
    ax.legend(fontsize=7, loc="lower right")
    ax.grid(True, alpha=0.3)

    # ---- Panel 2: q(t) with capacity line --------------------------------
    ax = axes[0, 1]
    if np.any(np.isfinite(q)):
        ax.plot(minute_of_day, q, color="#2ca02c", linewidth=0.9, label="q(t)")
        if not ddf.empty:
            mod_d = pd.to_datetime(ddf["datetime"]).dt.hour * 60 + pd.to_datetime(ddf["datetime"]).dt.minute
            ax.scatter(mod_d, ddf["flow_vph"], s=8, color="red",
                       label="q in discharge window", zorder=3)
        cap_p = verif["capacity_prior_vphpl"]
        cap_c = verif["capacity_calibrated_vphpl"]
        if np.isfinite(cap_p):
            ax.axhline(cap_p, color="red", linestyle="--", alpha=0.7,
                       label=f"Capacity prior = {cap_p:.0f}")
        if np.isfinite(cap_c) and abs(cap_c - cap_p) > 1.0:
            ax.axhline(cap_c, color="purple", linestyle=":", alpha=0.7,
                       label=f"Capacity calib = {cap_c:.0f}")
        if np.isfinite(verif["mu_obs_vphpl"]):
            ax.axhline(verif["mu_obs_vphpl"], color="black", linestyle="-",
                       linewidth=1.2, alpha=0.6,
                       label=f"mu_obs = median q = {verif['mu_obs_vphpl']:.0f}")
        ax.legend(fontsize=7, loc="lower right")
    else:
        ax.text(0.5, 0.5, "no flow data on this sensor",
                ha="center", va="center", transform=ax.transAxes)
    ax.set_xlabel("minute of day")
    ax.set_ylabel("flow (vph/lane)")
    ax.set_title("Step B: Capacity  +  Step G: mu derivation")
    ax.grid(True, alpha=0.3)

    # ---- Panel 3: k(t) ---------------------------------------------------
    ax = axes[1, 0]
    if np.any(np.isfinite(k_arr)):
        ax.plot(minute_of_day, k_arr, color="#d62728", linewidth=0.9, label="k(t)")
    ax.set_xlabel("minute of day")
    ax.set_ylabel("density (veh/mile/lane)")
    ax.set_title("density k(t)")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=7)

    # ---- Panel 4: verification table -------------------------------------
    ax = axes[1, 1]
    ax.axis("off")
    consistency_pct = (f"{verif['mu_consistency']*100:.1f}%"
                       if np.isfinite(verif["mu_consistency"]) else "n/a")
    table_text = (
        f"VERIFICATION  ({verif['sensor_uid']}  {verif['date']}  {verif['period']})\n"
        f"\n"
        f"Step A  V_cut_off\n"
        f"   prior        : {verif['v_c_prior_mph']:.2f} mph\n"
        f"   calibrated   : {verif['v_c_calibrated_mph']:.2f} mph\n"
        f"   source       : {verif['v_c_source']}\n"
        f"\n"
        f"Step B  Capacity\n"
        f"   prior        : {verif['capacity_prior_vphpl']:.0f} vphpl\n"
        f"   calibrated   : {verif['capacity_calibrated_vphpl']:.0f} vphpl\n"
        f"   source       : {verif['capacity_source']}\n"
        f"\n"
        f"Step C  P  = {verif['P_min']:.0f} min   "
        f"(t0={verif['t0_time'][11:16]}, t2={verif['t2_time'][11:16]}, t3={verif['t3_time'][11:16]})\n"
        f"Step D  V_t2 = {verif['v_t2_mph']:.2f} mph\n"
        f"Step F  Discharge window:  {verif['discharge_n_intervals']} x 5 min "
        f"= {verif['discharge_duration_min']:.0f} min\n"
        f"\n"
        f"Step G  mu_obs    = {verif['mu_obs_vphpl']:.0f}  vphpl\n"
        f"        mu_check  = {verif['mu_check_inverse_s3_vphpl']:.0f}  (inverse-S3 of mean v_discharge)\n"
        f"        |gap| / mu_obs = {consistency_pct}\n"
    )
    ax.text(0.0, 1.0, table_text, va="top", ha="left",
            fontfamily="monospace", fontsize=9,
            transform=ax.transAxes)

    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Orchestrator — one CSV + N panels per corridor
# ---------------------------------------------------------------------------
def run_verification(episodes_df: pd.DataFrame,
                     qc_df: pd.DataFrame,
                     fd_by_sensor: dict,
                     out_dir: Path,
                     s3_prior: dict = None,
                     max_panels: int = 24,
                     only_valid: bool = True) -> pd.DataFrame:
    """
    Iterate every (valid) episode, build the verification row, and emit the
    4-panel figure for up to `max_panels` episodes (ranked by P_min).

    Returns the verification DataFrame.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    panels_dir = out_dir / "panels"
    panels_dir.mkdir(exist_ok=True)

    eps = episodes_df.copy()
    if only_valid:
        eps = eps[eps["is_valid_for_mu"]].copy()
    # Interleave periods (each period's episodes still ranked by P_min desc).
    # A plain P_min sort sent every panel to the longest-period bucket (all 24
    # panels were MD; PM — most of the valid set — had zero visual coverage).
    eps = eps.sort_values("P_min", ascending=False)
    eps["__rank_in_period__"] = eps.groupby("period").cumcount()
    eps = (eps.sort_values(["__rank_in_period__", "P_min"], ascending=[True, False])
              .drop(columns="__rank_in_period__").reset_index(drop=True))

    rows = []
    plotted = 0
    for i, ep in eps.iterrows():
        fd_sensor_payload = fd_by_sensor.get(ep["sensor_uid"], {})
        v = verify_episode(ep, qc_df, fd_sensor_payload, s3_prior=s3_prior)
        if plotted < max_panels:
            safe_sid = ep["sensor_uid"].replace(":", "_").replace("/", "_")
            fname = f"verify__{safe_sid}__{ep['date']}__{ep['period']}.png"
            plot_episode_verification(v, panels_dir / fname, s3_prior=s3_prior)
            plotted += 1
        v.pop("_sensor_date_df", None)
        v.pop("_win", None)
        v.pop("_discharge_df", None)
        rows.append(v)

    df_out = pd.DataFrame(rows)
    df_out["aggregation_level"] = "per_episode_audited"   # CONTRACTS.md section 3
    df_out.to_csv(out_dir / "stage4_verification.csv", index=False)

    # Summary statistics
    summary = dict(
        n_episodes_verified=int(len(df_out)),
        v_c_calibrated_median=float(df_out["v_c_calibrated_mph"].median())
            if len(df_out) else float("nan"),
        capacity_calibrated_median=float(df_out["capacity_calibrated_vphpl"].median())
            if len(df_out) else float("nan"),
        P_min_median=float(df_out["P_min"].median()) if len(df_out) else float("nan"),
        v_t2_median_mph=float(df_out["v_t2_mph"].median()) if len(df_out) else float("nan"),
        mu_obs_median_vphpl=float(df_out["mu_obs_vphpl"].median()) if len(df_out) else float("nan"),
        mu_consistency_median=float(df_out["mu_consistency"].median()) if len(df_out) else float("nan"),
        n_panels_plotted=plotted,
    )
    with open(out_dir / "stage4_verification_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=float)
    return df_out
