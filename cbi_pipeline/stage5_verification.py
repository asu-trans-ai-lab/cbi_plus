"""
stage5_verification.py — round-by-round QVDF audit (one episode at a time).

Mirrors the canonical C++ flow in
    CBI-main/.../scan_congestion_duration   (CBI on observed data)
    CBI-main/.../calculate_travel_time_based_on_QVDF   (QVDF forward)

For each valid episode we run the FULL round-trip:

    Round 1  Read observed inputs from Stage 2:
                t0, t2, t3, P_obs, V_t2_obs, V, D, vc, vf, L (= period length)

    Round 2  Back-calibrate the four QVDF parameters (Q_cd anchored to 1,
             Q_s anchored to 4 — exactly as in the C++ defaults):
                Q_n      from   log(P)  = log(Q_cd) + Q_n * log(D/C)
                Q_cp     from   Q_cp    = (vc/V_t2 - 1) / P^Q_s
             Clip each to its feasibility range. If Q_n < 1.001 then default
             Q_n = 1.124 and back-derive Q_cd from P / (D/C)^Q_n.

    Round 3  Derive the BPR-form parameters:
                Q_alpha  = 8/15 * Q_cp * Q_cd^Q_s         (range [0.01, 1],   def 0.27)
                Q_beta   = Q_n * Q_s                       (range [0.5,  5 ],  def 1.14)

    Round 4  Forward-predict P, vt2 from D/C using the calibrated params:
                P_hat    = Q_cd * (D/C)^Q_n
                vt2_hat  = vc / (Q_cp * P_hat^Q_s + 1)
             Compare P_obs <-> P_hat  and  V_t2_obs <-> vt2_hat.

    Round 5  Build td_speed(t) over the full period via the C++ fourth-order
             queue profile:
                t0 = t2 - 0.5 * P_hat
                t3 = t2 + 0.5 * P_hat
                Q_mu     = min(C, D / P_hat)
                Q_gamma  = (1/vt2_hat - 1/vc) * 64 * Q_mu / P_hat^4
                td_queue(t) = 0.25 * Q_gamma * (t - t0)^2 * (t - t3)^2   if t0 <= t <= t3
                td_speed(t) = link_length / (td_queue(t)/Q_mu + 1/vc)    on congested branch
                              linear interp to vf outside the congestion window
             Compare td_speed(t) <-> observed v(t)   --> MAE / MAPE / RMSE.

The verification artifact per corridor is:
    stage5_verification/
        stage5_qvdf_verification.csv          # one row per episode, all 5 rounds
        stage5_qvdf_verification_summary.json
        panels/<sensor>__<date>__<period>.png # 6-panel round-by-round figure
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

from .schemas import PERIOD_DEFINITIONS, PERIOD_SLICE_BOUNDS, period_hour_mask


# ---------------------------------------------------------------------------
# Feasibility ranges (verbatim from the C++ scan_congestion_duration)
# ---------------------------------------------------------------------------
FEASIBLE = dict(
    Q_n       = dict(default=1.24,  lo=1.0,   hi=1.5),
    Q_s       = dict(default=1.0,   lo=0.5,   hi=4.0),
    Q_cd      = dict(default=1.0,   lo=0.5,   hi=2.0),
    Q_cp      = dict(default=0.2,   lo=0.0,   hi=2.0),
    Q_alpha   = dict(default=0.27,  lo=0.01,  hi=1.0),
    Q_beta    = dict(default=1.14,  lo=0.5,   hi=5.0),
    plf       = dict(default=1.0,   lo=0.0,   hi=1.0),
    DOC       = dict(default=0.5,   lo=0.0,   hi=10.0),
    P_hours   = dict(default=0.0,   lo=0.0,   hi=10.0),
    t2_speed  = dict(default=None,  lo=0.0,   hi=200.0),     # default = FD_vcutoff (set at call)
)

# C++ anchors before solving (the calibration FIXES these, then back-derives the others)
Q_S_FIXED = 4.0          # C++ initializes Q_s = 4 in scan_congestion_duration
Q_CD_FIXED = 1.0         # C++ initializes Q_cd = 1 and only back-derives if Q_n < 1.001


def _clip(name: str, value: float, default_override: Optional[float] = None) -> float:
    f = FEASIBLE[name]
    if value is None or not np.isfinite(value):
        return float(default_override if default_override is not None
                     else (f["default"] if f["default"] is not None else 0.0))
    if f["lo"] <= value <= f["hi"]:
        return float(value)
    return float(default_override if default_override is not None
                 else (f["default"] if f["default"] is not None else f["lo"]))


# ---------------------------------------------------------------------------
# Round 2 + Round 3: per-episode calibration
# ---------------------------------------------------------------------------
def calibrate_qvdf_episode(P_hours: float,
                           D_over_C: float,
                           v_c: float,
                           v_t2: float,
                           Q_cd_anchor: float = Q_CD_FIXED,
                           Q_s_anchor: float = Q_S_FIXED) -> dict:
    """
    Translate the C++ calibration block (scan_congestion_duration lines:
        Q_n = part1 / part2;  if Q_n < 1.001 -> default and back-derive Q_cd
        Q_cp = (FD_vcutoff/t2_speed - 1) / pow(P, Q_s)
    ) into Python.

    Returns the six QVDF parameters with feasibility-clipped values plus the
    `_raw_*` values pre-clipping for the audit trail.
    """
    out = dict(
        # Round 2 raw
        Q_n_raw=float("nan"), Q_cd_raw=Q_cd_anchor, Q_cp_raw=float("nan"),
        Q_s_raw=Q_s_anchor,
        # Round 2/3 final (after clipping)
        Q_n=FEASIBLE["Q_n"]["default"],
        Q_s=FEASIBLE["Q_s"]["default"],
        Q_cd=FEASIBLE["Q_cd"]["default"],
        Q_cp=FEASIBLE["Q_cp"]["default"],
        Q_alpha=FEASIBLE["Q_alpha"]["default"],
        Q_beta=FEASIBLE["Q_beta"]["default"],
        calibration_status="ok",
    )

    # Step A — Q_n from log(P) = log(Q_cd) + Q_n * log(D/C)
    if (P_hours is None or D_over_C is None
            or P_hours <= 0 or D_over_C <= 0):
        out["calibration_status"] = "missing_inputs"
        return out

    part1 = np.log(P_hours) - np.log(max(Q_cd_anchor, 1e-9))
    part2 = np.log(D_over_C)
    if abs(part2) < 1e-6:
        part2 = 1e-5 if part2 >= 0 else -1e-5
    Q_n_raw = part1 / part2
    Q_cd_raw = Q_cd_anchor
    out["Q_n_raw"] = float(Q_n_raw)
    out["Q_cd_raw"] = float(Q_cd_raw)

    # Step B — if Q_n < 1.001, default and back-derive Q_cd (C++ fallback)
    if Q_n_raw < 1.001:
        Q_n_eff = 1.124           # C++ exact default
        Q_cd_raw = P_hours / max(D_over_C ** Q_n_eff, 1e-9)
        out["Q_n_raw"] = float(Q_n_eff)
        out["Q_cd_raw"] = float(Q_cd_raw)
        out["calibration_status"] = "Q_n_below_1: defaulted + back-derived Q_cd"

    # Step C — Q_cp from (vc/V_t2 - 1) / P^Q_s
    if v_t2 is None or v_t2 <= 0 or v_c is None or v_c <= 0:
        out["Q_cp_raw"] = FEASIBLE["Q_cp"]["default"]
        out["calibration_status"] += " | v_t2 missing - Q_cp defaulted"
    else:
        Q_cp_raw = (v_c / max(v_t2, 1e-4) - 1.0) / max(P_hours ** Q_s_anchor, 1e-5)
        out["Q_cp_raw"] = float(Q_cp_raw)

    # Step D — Feasibility clip
    out["Q_n"]   = _clip("Q_n",   out["Q_n_raw"])
    out["Q_s"]   = _clip("Q_s",   Q_s_anchor)
    out["Q_cd"]  = _clip("Q_cd",  out["Q_cd_raw"])
    out["Q_cp"]  = _clip("Q_cp",  out["Q_cp_raw"])

    # Round 3 — derive BPR-form (Q_alpha, Q_beta) and clip
    out["Q_alpha_raw"] = float(8.0 / 15.0 * out["Q_cp"] * out["Q_cd"] ** out["Q_s"])
    out["Q_beta_raw"]  = float(out["Q_n"] * out["Q_s"])
    out["Q_alpha"] = _clip("Q_alpha", out["Q_alpha_raw"])
    out["Q_beta"]  = _clip("Q_beta",  out["Q_beta_raw"])

    return out


# ---------------------------------------------------------------------------
# Round 4 + Round 5: forward predict and td_speed profile
# ---------------------------------------------------------------------------
def forward_qvdf_episode(qvdf: dict,
                         D_over_C: float,
                         v_c_mph: float,
                         v_f_mph: float,
                         t2_hour: float,
                         L_hours: float,
                         lane_capacity_vphpl: float,
                         lane_based_D: float,
                         link_length_mi: float = 1.0,
                         starting_hour: Optional[float] = None,
                         ending_hour: Optional[float] = None,
                         dt_min: float = 5.0) -> dict:
    """
    Apply calibrated (Q_n, Q_s, Q_cd, Q_cp) forward.

    Returns:
        P_hat_hours, vt2_hat_mph, Q_mu_vphpl, Q_gamma, t0_hat, t3_hat,
        time_axis_hour (np.ndarray), td_speed_mph (np.ndarray),
        td_queue_veh (np.ndarray)
    """
    Q_n = qvdf["Q_n"]; Q_s = qvdf["Q_s"]; Q_cd = qvdf["Q_cd"]; Q_cp = qvdf["Q_cp"]
    Q_alpha = qvdf["Q_alpha"]; Q_beta = qvdf["Q_beta"]

    # Round 4 — point predictions
    P_hat = Q_cd * (max(D_over_C, 0.0) ** Q_n)
    P_hat = _clip("P_hours", P_hat)
    base = Q_cp * (P_hat ** Q_s) + 1.0
    vt2_hat = v_c_mph / max(base, 1e-3)

    # Round 5 — td_speed profile
    if starting_hour is None:
        starting_hour = max(0.0, t2_hour - max(L_hours, P_hat) * 0.6)
    if ending_hour is None:
        ending_hour = min(24.0, t2_hour + max(L_hours, P_hat) * 0.6)

    n_steps = max(1, int(round((ending_hour - starting_hour) * 60.0 / dt_min)))
    time_axis = np.linspace(starting_hour, ending_hour, n_steps + 1)
    td_speed = np.full_like(time_axis, v_f_mph, dtype=float)
    td_queue = np.zeros_like(time_axis, dtype=float)

    t0_hat = t2_hour - 0.5 * P_hat
    t3_hat = t2_hour + 0.5 * P_hat

    RTT = link_length_mi / max(v_c_mph, 1e-3)    # hour
    Q_mu = min(lane_capacity_vphpl, lane_based_D / max(P_hat, 0.01)) if P_hat > 0.15 else lane_capacity_vphpl
    if P_hat > 0.15:
        wt2 = link_length_mi / max(vt2_hat, 1e-3) - RTT      # hour
        Q_gamma = wt2 * 64.0 * Q_mu / max(P_hat, 1e-3) ** 4
    else:
        Q_gamma = 0.0

    avg_queue_speed = v_c_mph / (1.0 + Q_alpha * (max(D_over_C, 0.0) ** Q_beta))

    for i, t in enumerate(time_axis):
        if t0_hat <= t <= t3_hat and P_hat > 0.15:
            q = 0.25 * Q_gamma * (t - t0_hat) ** 2 * (t - t3_hat) ** 2
            w = q / max(Q_mu, 1e-3)
            td_speed[i] = link_length_mi / max(w + RTT, 1e-6)
            td_queue[i] = q
        elif t < t0_hat:
            factor = ((t - starting_hour)
                      / max(1e-3, t0_hat - starting_hour))
            factor = float(np.clip(factor, 0.0, 1.0))
            td_speed[i] = (1.0 - factor) * v_f_mph + factor * max(v_c_mph, avg_queue_speed)
        else:                                  # t > t3_hat
            factor = ((t - t3_hat)
                      / max(1e-3, ending_hour - t3_hat))
            factor = float(np.clip(factor, 0.0, 1.0))
            td_speed[i] = (1.0 - factor) * max(v_c_mph, avg_queue_speed) + factor * v_f_mph

    return dict(
        P_hat_hours=float(P_hat),
        vt2_hat_mph=float(vt2_hat),
        Q_mu_vphpl=float(Q_mu),
        Q_gamma=float(Q_gamma),
        t0_hat_hour=float(t0_hat),
        t3_hat_hour=float(t3_hat),
        avg_queue_speed_mph=float(avg_queue_speed),
        time_axis_hour=time_axis,
        td_speed_mph=td_speed,
        td_queue_veh=td_queue,
        starting_hour=float(starting_hour),
        ending_hour=float(ending_hour),
    )


# ---------------------------------------------------------------------------
# Error metrics between predicted and observed v(t)
# ---------------------------------------------------------------------------
def _resample_observed_v(qc_sensor_date: pd.DataFrame,
                         time_axis_hour: np.ndarray) -> np.ndarray:
    """Pick the observed v at each time_axis hour (nearest 5-min sample)."""
    if qc_sensor_date.empty:
        return np.full_like(time_axis_hour, np.nan, dtype=float)
    ts = pd.to_datetime(qc_sensor_date["datetime"])
    obs_hour = ts.dt.hour + ts.dt.minute / 60.0
    obs_v = (qc_sensor_date["speed_mph_clean"] if "speed_mph_clean" in qc_sensor_date.columns
             else qc_sensor_date["speed_mph"]).to_numpy()
    out = np.full_like(time_axis_hour, np.nan, dtype=float)
    obs_hour_arr = obs_hour.to_numpy()
    for i, h in enumerate(time_axis_hour):
        idx = int(np.argmin(np.abs(obs_hour_arr - h)))
        if abs(obs_hour_arr[idx] - h) <= 5.0 / 60.0 + 1e-6:
            out[i] = obs_v[idx]
    return out


def speed_errors(td_speed: np.ndarray, obs_v: np.ndarray) -> dict:
    mask = np.isfinite(td_speed) & np.isfinite(obs_v) & (obs_v > 1.0)
    if mask.sum() < 3:
        return dict(MAE=float("nan"), MAPE=float("nan"), RMSE=float("nan"),
                    n=int(mask.sum()))
    err = td_speed[mask] - obs_v[mask]
    return dict(
        MAE=float(np.mean(np.abs(err))),
        MAPE=float(np.mean(np.abs(err) / np.maximum(obs_v[mask], 1.0)) * 100.0),
        RMSE=float(np.sqrt(np.mean(err ** 2))),
        n=int(mask.sum()),
    )


# ---------------------------------------------------------------------------
# Per-episode verification (rounds 1-5)
# ---------------------------------------------------------------------------
def verify_qvdf_episode(episode_row: pd.Series,
                        qc_df: pd.DataFrame,
                        fd_payload: dict,
                        period_hour_bounds: Optional[tuple] = None,
                        link_length_mi: Optional[float] = None) -> dict:
    """One full round-by-round audit for one episode."""
    sid = episode_row["sensor_uid"]
    date = str(episode_row["date"])
    period = episode_row.get("period", "all_day")

    fd = (fd_payload or {}).get("fd", {}) or {}
    meta = (fd_payload or {}).get("meta", {}) or {}
    vf_mph = float(fd.get("free_flow_speed_kph") or 70.0 * 1.609) / 1.609
    vc_mph = float(fd.get("speed_at_capacity_kph") or 50.0 * 1.609) / 1.609
    capacity_vphpl = float(fd.get("capacity_vphpl") or 2000.0)

    # ---- Round 1 — read observed inputs ---------------------------------
    P_obs_min = float(episode_row.get("P_min", float("nan")))
    P_obs_hours = P_obs_min / 60.0
    V_t2_obs = float(episode_row.get("min_speed_mph", float("nan")))
    D_period = float(episode_row.get("demand_veh", float("nan")))

    # L = period length in hours (AM=4, MD=6, PM=4 with our defs)
    if period_hour_bounds is not None:
        h0, h1 = period_hour_bounds
        L_hours = float(h1 - h0)
        starting_hour, ending_hour = float(h0), float(h1)
    else:
        L_hours = 4.0
        starting_hour, ending_hour = None, None

    # D/C with C++ scan_congestion_duration convention: D is per-lane vehicles
    # ACCUMULATED across the congested window; capacity is per-hour, so D/C has
    # units of hours and is ~ P at-capacity. flow_vph in our schema is already
    # per-lane, so demand_veh from Stage 2 is per-lane already — DO NOT divide
    # by lanes or L here. (See C++ scan_congestion_duration around DOC_ratio.)
    lanes = episode_row.get("lanes", np.nan)
    if not (isinstance(lanes, (int, float)) and np.isfinite(lanes) and lanes >= 1):
        lanes = 2.0
    plf = 1.0
    D_over_C = D_period / max(capacity_vphpl, 1e-3)
    D_over_C = _clip("DOC", D_over_C)
    # lane_based_D is the AVERAGE per-lane discharge rate during the
    # congested window (used for Q_mu = D / P), again matching C++.
    lane_based_D = D_period / max(P_obs_hours, 0.01)

    # t2_hour: derive from the sensor-date dataframe
    sensor_date_df = qc_df[
        (qc_df["sensor_uid"] == sid)
        & (pd.to_datetime(qc_df["datetime"]).dt.date.astype(str) == date)
    ].sort_values("datetime").reset_index(drop=True)
    # Episode indices are PERIOD-relative (stage2 groups by sensor/date/period),
    # so slice the day down to the same period before any iloc lookup.
    if period in PERIOD_SLICE_BOUNDS:
        hours = pd.to_datetime(sensor_date_df["datetime"]).dt.hour
        sensor_date_df = sensor_date_df[period_hour_mask(hours, period)].reset_index(drop=True)
    t2_idx = int(episode_row["t2_index"])
    if 0 <= t2_idx < len(sensor_date_df):
        t2_ts = pd.to_datetime(sensor_date_df["datetime"].iloc[t2_idx])
        t2_hour = float(t2_ts.hour + t2_ts.minute / 60.0)
    else:
        t2_hour = (starting_hour + ending_hour) / 2.0 if starting_hour else 8.0

    round1 = dict(
        P_obs_min=P_obs_min, P_obs_hours=P_obs_hours,
        V_t2_obs_mph=V_t2_obs,
        D_period=D_period,
        lane_based_D_vphpl=float(lane_based_D),
        D_over_C=float(D_over_C),
        L_hours=L_hours,
        t2_hour=t2_hour,
        vf_mph=vf_mph, vc_mph=vc_mph, capacity_vphpl=capacity_vphpl,
        lanes=float(lanes), plf=plf,
    )

    # ---- Round 2 + 3 — calibrate ---------------------------------------
    qvdf = calibrate_qvdf_episode(P_obs_hours, D_over_C, vc_mph, V_t2_obs)
    round23 = qvdf

    # ---- Round 4 + 5 — forward predict + td_speed ----------------------
    fwd = forward_qvdf_episode(
        qvdf=qvdf, D_over_C=D_over_C, v_c_mph=vc_mph, v_f_mph=vf_mph,
        t2_hour=t2_hour, L_hours=L_hours,
        lane_capacity_vphpl=capacity_vphpl, lane_based_D=lane_based_D,
        link_length_mi=(link_length_mi if link_length_mi is not None else 1.0),
        starting_hour=starting_hour, ending_hour=ending_hour,
    )

    # ---- Errors: P, vt2, v(t) -----------------------------------------
    P_err_hours = fwd["P_hat_hours"] - P_obs_hours
    P_err_pct = (P_err_hours / P_obs_hours * 100.0
                 if P_obs_hours > 0 else float("nan"))
    vt2_err = fwd["vt2_hat_mph"] - V_t2_obs
    vt2_err_pct = (vt2_err / max(V_t2_obs, 1.0) * 100.0
                   if V_t2_obs > 0 else float("nan"))
    obs_v = _resample_observed_v(sensor_date_df, fwd["time_axis_hour"])
    v_errs = speed_errors(fwd["td_speed_mph"], obs_v)

    return dict(
        sensor_uid=sid, date=date, period=period,
        # Round 1
        **{f"R1_{k}": v for k, v in round1.items()},
        # Round 2 + 3
        Q_n_raw=round23.get("Q_n_raw"),
        Q_cp_raw=round23.get("Q_cp_raw"),
        Q_cd_raw=round23.get("Q_cd_raw"),
        Q_alpha_raw=round23.get("Q_alpha_raw"),
        Q_beta_raw=round23.get("Q_beta_raw"),
        Q_n=round23["Q_n"], Q_s=round23["Q_s"],
        Q_cd=round23["Q_cd"], Q_cp=round23["Q_cp"],
        Q_alpha=round23["Q_alpha"], Q_beta=round23["Q_beta"],
        calibration_status=round23["calibration_status"],
        # Round 4
        P_hat_hours=fwd["P_hat_hours"], P_hat_min=fwd["P_hat_hours"] * 60.0,
        P_err_hours=float(P_err_hours), P_err_pct=float(P_err_pct),
        vt2_hat_mph=fwd["vt2_hat_mph"],
        vt2_err_mph=float(vt2_err), vt2_err_pct=float(vt2_err_pct),
        # Round 5
        Q_mu_vphpl=fwd["Q_mu_vphpl"], Q_gamma=fwd["Q_gamma"],
        t0_hat_hour=fwd["t0_hat_hour"], t3_hat_hour=fwd["t3_hat_hour"],
        avg_queue_speed_mph=fwd["avg_queue_speed_mph"],
        v_t_MAE=v_errs["MAE"], v_t_MAPE_pct=v_errs["MAPE"],
        v_t_RMSE=v_errs["RMSE"], v_t_n=v_errs["n"],
        # Carried for the plotter
        _time_axis=fwd["time_axis_hour"],
        _td_speed=fwd["td_speed_mph"],
        _td_queue=fwd["td_queue_veh"],
        _obs_v=obs_v,
        _sensor_date_df=sensor_date_df,
    )


# ---------------------------------------------------------------------------
# Six-panel round-by-round figure
# ---------------------------------------------------------------------------
def plot_qvdf_episode_verification(v: dict, save_path: Path) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    sdf = v["_sensor_date_df"]
    ts_all = pd.to_datetime(sdf["datetime"]) if not sdf.empty else None
    mod_all = (ts_all.dt.hour * 60 + ts_all.dt.minute) if ts_all is not None else None
    obs_v_all = (sdf["speed_mph_clean"] if "speed_mph_clean" in sdf.columns
                 else sdf.get("speed_mph", pd.Series([]))) if not sdf.empty else None

    # ---- Panel 1: v(t) observed vs predicted td_speed -------------------
    ax = axes[0, 0]
    if obs_v_all is not None:
        ax.plot(mod_all / 60.0, obs_v_all, color="#1f77b4",
                linewidth=0.9, alpha=0.7, label="v(t) observed")
    ax.plot(v["_time_axis"], v["_td_speed"], color="red", linewidth=1.6,
            label="td_speed predicted")
    ax.axhline(v["R1_vc_mph"], color="purple", linestyle="--", alpha=0.5,
               label=f"v_c = {v['R1_vc_mph']:.1f}")
    ax.axhline(v["vt2_hat_mph"], color="orange", linestyle=":", alpha=0.7,
               label=f"vt2_hat = {v['vt2_hat_mph']:.1f}")
    ax.axhline(v["R1_V_t2_obs_mph"], color="black", linestyle="-.", alpha=0.5,
               label=f"V_t2_obs = {v['R1_V_t2_obs_mph']:.1f}")
    ax.axvline(v["t0_hat_hour"], color="green", linestyle=":", alpha=0.5)
    ax.axvline(v["t3_hat_hour"], color="green", linestyle=":", alpha=0.5,
               label=f"t0_hat..t3_hat (P_hat={v['P_hat_hours']*60:.0f} min)")
    ax.set_xlabel("hour")
    ax.set_ylabel("speed (mph)")
    ax.set_ylim(0, max(80.0, v["R1_vf_mph"] * 1.05))
    ax.set_title(f"Round 5: v(t) round-trip "
                 f"MAPE={v['v_t_MAPE_pct']:.1f}%  n={v['v_t_n']}")
    ax.legend(fontsize=7, loc="lower right")
    ax.grid(True, alpha=0.3)

    # ---- Panel 2: td_queue(t) -----------------------------------------
    ax = axes[0, 1]
    ax.plot(v["_time_axis"], v["_td_queue"], color="#d62728", linewidth=1.4)
    ax.axvline(v["t0_hat_hour"], color="green", linestyle=":", alpha=0.5)
    ax.axvline(v["t3_hat_hour"], color="green", linestyle=":", alpha=0.5)
    ax.set_xlabel("hour")
    ax.set_ylabel("td_queue (veh)")
    ax.set_title(f"Round 5: queue profile  Q_gamma={v['Q_gamma']:.2f}  "
                 f"Q_mu={v['Q_mu_vphpl']:.0f}")
    ax.grid(True, alpha=0.3)

    # ---- Panel 3: P_obs vs P_hat scatter (single point + bounds) -------
    ax = axes[0, 2]
    P_obs_min = v["R1_P_obs_min"]; P_hat_min = v["P_hat_min"]
    ax.bar([0, 1], [P_obs_min, P_hat_min],
           color=["#1f77b4", "red"], alpha=0.7)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["P_obs", "P_hat"])
    ax.set_ylabel("congestion duration (min)")
    ax.set_title(f"Round 4: P  obs={P_obs_min:.0f}  hat={P_hat_min:.0f}  "
                 f"err={v['P_err_pct']:+.1f}%")
    ax.grid(True, alpha=0.3)

    # ---- Panel 4: V_t2 obs vs hat -------------------------------------
    ax = axes[1, 0]
    ax.bar([0, 1], [v["R1_V_t2_obs_mph"], v["vt2_hat_mph"]],
           color=["#1f77b4", "red"], alpha=0.7)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["V_t2 obs", "vt2 hat"])
    ax.set_ylabel("minimum speed (mph)")
    ax.set_title(f"Round 4: V_t2  obs={v['R1_V_t2_obs_mph']:.1f}  hat={v['vt2_hat_mph']:.1f}  "
                 f"err={v['vt2_err_pct']:+.1f}%")
    ax.grid(True, alpha=0.3)

    # ---- Panel 5: Calibrated parameters (raw vs clipped) ---------------
    ax = axes[1, 1]
    labels = ["Q_n", "Q_s", "Q_cd", "Q_cp", "Q_alpha", "Q_beta"]
    raw = [v.get(f"{k}_raw", v[k]) for k in labels]
    clipped = [v[k] for k in labels]
    xs = np.arange(len(labels))
    width = 0.35
    ax.bar(xs - width / 2,
           [r if r is not None and np.isfinite(r) else 0 for r in raw],
           width, label="raw (Round 2)", color="#1f77b4", alpha=0.7)
    ax.bar(xs + width / 2, clipped, width,
           label="clipped (Round 3)", color="red", alpha=0.7)
    ax.set_xticks(xs); ax.set_xticklabels(labels, fontsize=8, rotation=15)
    ax.set_title("Rounds 2 + 3: calibrated params (raw -> feasibility)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    # ---- Panel 6: round-by-round audit text ---------------------------
    ax = axes[1, 2]
    ax.axis("off")
    txt = (
        f"QVDF VERIFICATION  ({v['sensor_uid']}  {v['date']}  {v['period']})\n"
        f"\n"
        f"Round 1  observed inputs\n"
        f"  vf={v['R1_vf_mph']:.1f}  vc={v['R1_vc_mph']:.1f}  C={v['R1_capacity_vphpl']:.0f}\n"
        f"  P_obs={v['R1_P_obs_min']:.0f} min   V_t2_obs={v['R1_V_t2_obs_mph']:.1f} mph\n"
        f"  D_period={v['R1_D_period']:.0f} veh  laneD={v['R1_lane_based_D_vphpl']:.0f} vphpl\n"
        f"  L={v['R1_L_hours']:.1f} h  D/C={v['R1_D_over_C']:.3f}  lanes={v['R1_lanes']:.0f}\n"
        f"\n"
        f"Round 2/3  calibrated  ({v['calibration_status']})\n"
        f"  Q_n  ={v['Q_n']:.3f}  (raw {v.get('Q_n_raw', float('nan')):.3f})\n"
        f"  Q_s  ={v['Q_s']:.3f}\n"
        f"  Q_cd ={v['Q_cd']:.3f}  (raw {v.get('Q_cd_raw', float('nan')):.3f})\n"
        f"  Q_cp ={v['Q_cp']:.3f}  (raw {v.get('Q_cp_raw', float('nan')):.3f})\n"
        f"  -> Q_alpha={v['Q_alpha']:.3f}  Q_beta={v['Q_beta']:.3f}\n"
        f"\n"
        f"Round 4  forward predict\n"
        f"  P_hat = Q_cd * (D/C)^Q_n = {v['P_hat_hours']*60:.0f} min   err {v['P_err_pct']:+.1f}%\n"
        f"  vt2_hat = vc / (Q_cp P^Q_s + 1) = {v['vt2_hat_mph']:.1f} mph   err {v['vt2_err_pct']:+.1f}%\n"
        f"\n"
        f"Round 5  td_speed profile\n"
        f"  Q_mu={v['Q_mu_vphpl']:.0f}  Q_gamma={v['Q_gamma']:.3f}\n"
        f"  t0_hat={v['t0_hat_hour']:.2f} h  t3_hat={v['t3_hat_hour']:.2f} h\n"
        f"  v(t) MAE={v['v_t_MAE']:.2f}  MAPE={v['v_t_MAPE_pct']:.1f}%  RMSE={v['v_t_RMSE']:.2f}\n"
    )
    ax.text(0.0, 1.0, txt, va="top", ha="left",
            fontfamily="monospace", fontsize=9, transform=ax.transAxes)

    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def run_qvdf_verification(episodes_df: pd.DataFrame,
                          qc_df: pd.DataFrame,
                          fd_by_sensor: dict,
                          out_dir: Path,
                          period_hour_bounds: dict = None,
                          max_panels: int = 24,
                          only_valid: bool = True) -> pd.DataFrame:
    """Run rounds 1-5 on every valid episode; emit CSV + up to max_panels PNGs."""
    if period_hour_bounds is None:
        # slice-bounds superset so merged MDPM episodes get their true 10-hour window
        period_hour_bounds = {k: v for k, v in PERIOD_SLICE_BOUNDS.items() if k != "NT"}

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    panels_dir = out_dir / "panels"
    panels_dir.mkdir(exist_ok=True)

    eps = episodes_df.copy()
    if only_valid:
        eps = eps[eps["is_valid_for_mu"]].copy()
    # Interleave periods so panel coverage spans AM/MD/PM (see stage4 note).
    eps = eps.sort_values("P_min", ascending=False)
    eps["__rank_in_period__"] = eps.groupby("period").cumcount()
    eps = (eps.sort_values(["__rank_in_period__", "P_min"], ascending=[True, False])
              .drop(columns="__rank_in_period__").reset_index(drop=True))

    rows = []
    plotted = 0
    for i, ep in eps.iterrows():
        fd_payload = fd_by_sensor.get(ep["sensor_uid"], {})
        hour_bounds = period_hour_bounds.get(ep.get("period", "MD"), (10, 16))
        v = verify_qvdf_episode(ep, qc_df, fd_payload,
                                period_hour_bounds=hour_bounds)
        if plotted < max_panels:
            safe = ep["sensor_uid"].replace(":", "_").replace("/", "_")
            fname = f"qvdf_verify__{safe}__{ep['date']}__{ep['period']}.png"
            plot_qvdf_episode_verification(v, panels_dir / fname)
            plotted += 1
        for k in ("_time_axis", "_td_speed", "_td_queue", "_obs_v", "_sensor_date_df"):
            v.pop(k, None)
        rows.append(v)

    df_out = pd.DataFrame(rows)
    df_out["aggregation_level"] = "per_episode_roundtrip"   # CONTRACTS.md section 3
    df_out.to_csv(out_dir / "stage5_qvdf_verification.csv", index=False)

    summary = dict(
        n_episodes_verified=int(len(df_out)),
        P_err_pct_median=float(df_out["P_err_pct"].median()) if len(df_out) else float("nan"),
        vt2_err_pct_median=float(df_out["vt2_err_pct"].median()) if len(df_out) else float("nan"),
        v_t_MAPE_pct_median=float(df_out["v_t_MAPE_pct"].median()) if len(df_out) else float("nan"),
        Q_n_median=float(df_out["Q_n"].median()) if len(df_out) else float("nan"),
        Q_s_median=float(df_out["Q_s"].median()) if len(df_out) else float("nan"),
        Q_cd_median=float(df_out["Q_cd"].median()) if len(df_out) else float("nan"),
        Q_cp_median=float(df_out["Q_cp"].median()) if len(df_out) else float("nan"),
        Q_alpha_median=float(df_out["Q_alpha"].median()) if len(df_out) else float("nan"),
        Q_beta_median=float(df_out["Q_beta"].median()) if len(df_out) else float("nan"),
        n_panels_plotted=plotted,
    )
    with open(out_dir / "stage5_qvdf_verification_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=float)
    return df_out
