"""
stage2_episodes.py — episode detection + day classification (Layer 2).

Each (sensor, date) is classified into one of:
    uncongested / mild / recurring / severe / event

Discharge window D_e is identified for valid episodes — μ in Stage 4 is
computed only over D_e, never over the full congested period.

The student's existing congestion detector
(Part1_fd_calibration.detect_congestion_daily) is reused as-is.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .schemas import (
    EPISODE_COLUMNS,
    RELIABILITY_THRESHOLDS,
    TAXONOMY_THRESHOLDS,
    DISCHARGE_WINDOW_MIN_INTERVALS,
    PERIOD_DEFINITIONS,
)


# ---------------------------------------------------------------------------
# Reuse student's detector
# ---------------------------------------------------------------------------
_DETECTOR_ANNOUNCED = False


def _import_student_detector():
    """Import detect_congestion_daily from codes/Part1_fd_calibration.py."""
    global _DETECTOR_ANNOUNCED
    codes_dir = Path(__file__).resolve().parents[1]
    if str(codes_dir) not in sys.path:
        sys.path.insert(0, str(codes_dir))
    try:
        from Part1_fd_calibration import detect_congestion_daily      # noqa: F401
    except Exception:
        # Local fallback (mirrors Part1 line 372) — used if the student's file moves.
        # PROVENANCE: say so once — a silent detector swap is an audit hazard.
        if not _DETECTOR_ANNOUNCED:
            print("   [stage2] detector: built-in fallback (Part1_fd_calibration.py "
                  "not found) — NaN-gap guard + 2-bin persistence active")
            _DETECTOR_ANNOUNCED = True
        return _fallback_detector
    if not _DETECTOR_ANNOUNCED:
        print("   [stage2] detector: Part1_fd_calibration.detect_congestion_daily")
        _DETECTOR_ANNOUNCED = True
    return detect_congestion_daily


def _fallback_detector(speed_array, vol_interval_array, hvol_array,
                       speed_at_capacity, dt_min):
    sp = np.asarray(speed_array, dtype=float)
    nb = len(sp)
    if nb == 0 or np.all(~np.isfinite(sp)):
        return dict(t0_index=0, t2_index=0, t3_index=0,
                    congestion_duration_hours=0.0, PSTW_hours=0.0,
                    demand=0.0, avg_discharge_rate=float("nan"),
                    cong_mean_speed=float("nan"), min_speed=float("nan"),
                    method="VBM")
    min_idx = int(np.nanargmin(sp))
    min_speed = float(sp[min_idx])
    if min_speed <= speed_at_capacity:
        # Boundary rule (fallback hardening):
        #  - a sample ends the episode only if it is BOTH finite and > v_c for
        #    PERSIST consecutive bins (single 5-min blips do not split an episode);
        #  - a run of >= GAP_NAN consecutive NaN samples also ends it (a data gap
        #    is unknown, not congested — do not extend an episode through it).
        PERSIST, GAP_NAN = 2, 3

        def _boundary(idx_range):
            above = gap = 0
            last_in = min_idx
            for j in idx_range:
                v = sp[j]
                if np.isfinite(v):
                    gap = 0
                    if v > speed_at_capacity:
                        above += 1
                        if above >= PERSIST:
                            return last_in
                    else:
                        above = 0
                        last_in = j
                else:
                    above = 0
                    gap += 1
                    if gap >= GAP_NAN:
                        return last_in
            return last_in

        t0 = _boundary(range(min_idx, -1, -1))
        t3 = _boundary(range(min_idx, nb))
        cong_hours = (t3 - t0 + 1) * (dt_min / 60.0)
        method = "SBM"
    else:
        t0, t3, cong_hours = 0, 0, 0.0
        method = "VBM"
    avg_discharge = (float(np.nanmean(hvol_array[max(t0, 0):min(t3 + 1, nb)]))
                     if hvol_array is not None and len(hvol_array) > 0 else float("nan"))
    return dict(t0_index=int(t0), t2_index=int(min_idx), t3_index=int(t3),
                congestion_duration_hours=float(cong_hours),
                PSTW_hours=float(cong_hours),
                demand=float(np.nansum(vol_interval_array[t0:t3 + 1])
                             if vol_interval_array is not None else 0.0),
                avg_discharge_rate=float(avg_discharge),
                cong_mean_speed=float(np.nanmean(sp[t0:t3 + 1])
                                      if t3 > t0 else min_speed),
                min_speed=min_speed, method=method)


# ---------------------------------------------------------------------------
# Day classification
# ---------------------------------------------------------------------------
def _regime_label(P_min: float, min_v: float, v_c: float,
                  z_score: float = 0.0) -> str:
    T = TAXONOMY_THRESHOLDS
    if not np.isfinite(P_min) or not np.isfinite(min_v):
        return "uncongested"
    if P_min < T["uncongested_max_P_min"] or min_v >= v_c:
        return "uncongested"
    if abs(z_score) > T["event_z_threshold"]:
        return "event"
    if P_min >= T["severe_min_P_min"] and min_v < T["severe_min_speed_ratio"] * v_c:
        return "severe"
    if P_min >= T["recurring_min_P_min"]:
        return "recurring"
    if (P_min < T["mild_max_P_min"]
            and T["mild_speed_ratio_lo"] * v_c <= min_v < v_c):
        return "mild"
    return "mild"


def classify_day(speed_series: np.ndarray,
                 flow_series: Optional[np.ndarray],
                 v_c_mph: float,
                 dt_min: float = 5.0) -> dict:
    """Classify a single day of one sensor."""
    detect = _import_student_detector()

    vol_interval = (np.asarray(flow_series, dtype=float) * (dt_min / 60.0)
                    if flow_series is not None else np.zeros_like(speed_series))
    hvol = np.asarray(flow_series, dtype=float) if flow_series is not None else np.full_like(speed_series, np.nan)
    res = detect(speed_series, vol_interval, hvol, v_c_mph, dt_min)

    P_min = float(res["congestion_duration_hours"] * 60.0)
    min_v = float(res["min_speed"])
    # z_score=0 unless caller supplies a link-history baseline (computed in run_episodes).
    regime = _regime_label(P_min, min_v, v_c_mph, z_score=0.0)

    return dict(
        t0_index=int(res["t0_index"]),
        t2_index=int(res["t2_index"]),
        t3_index=int(res["t3_index"]),
        P_min=P_min,
        min_speed_mph=min_v,
        v_c_mph=float(v_c_mph),
        demand_veh=float(res.get("demand", 0.0)),
        regime=regime,
        method=str(res.get("method", "VBM")),
        avg_discharge_rate=float(res.get("avg_discharge_rate", float("nan"))),
    )


# ---------------------------------------------------------------------------
# Discharge window
# ---------------------------------------------------------------------------
def discharge_window(speed: np.ndarray,
                     flow: Optional[np.ndarray],
                     t0: int, t2: int, t3: int,
                     v_c_mph: float,
                     min_intervals: int = DISCHARGE_WINDOW_MIN_INTERVALS) -> Optional[tuple[int, int]]:
    """
    Discharge window D_e = {t in (t2, t3] : v_t < v_c AND Δq/Δt ≤ 0}.

    Returns (start_idx, end_idx) or None if the window is too short.
    Flow may be None for speed-only data — in that case the Δq guard is relaxed
    and we use the (t2, t3] interval where v < v_c.
    """
    if t3 <= t2 + 1:
        return None
    t = np.arange(t2 + 1, t3 + 1)
    if len(t) < min_intervals:
        return None

    below_vc = speed[t] < v_c_mph
    if flow is not None and np.any(np.isfinite(flow[t])):
        dq = np.diff(flow[t], prepend=flow[t[0]])
        dissipating = dq <= 0
        keep = below_vc & dissipating
    else:
        keep = below_vc

    if keep.sum() < min_intervals:
        return None

    valid = t[keep]
    return int(valid[0]), int(valid[-1])


# ---------------------------------------------------------------------------
# Link reliability
# ---------------------------------------------------------------------------
def classify_link_reliability(n_valid_congested_days: int) -> str:
    T = RELIABILITY_THRESHOLDS
    if n_valid_congested_days >= T["high"]:
        return "high"
    if n_valid_congested_days >= T["medium"]:
        return "medium"
    if n_valid_congested_days >= T["low"]:
        return "low"
    return "not_reliable"


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def _period_for_timestamp(ts: pd.Timestamp) -> str:
    """Return period label (AM/MD/PM/NT) for one timestamp."""
    h = ts.hour
    for label, (h0, h1) in PERIOD_DEFINITIONS.items():
        if h0 <= h1:                            # normal range
            if h0 <= h < h1:
                return label
        else:                                   # overnight wrap (NT)
            if h >= h0 or h < h1:
                return label
    return "NT"


def run_episodes(df_qc: pd.DataFrame,
                 v_c_by_sensor: Optional[dict] = None,
                 default_v_c_mph: float = 50.0,
                 dt_min: float = 5.0,
                 by_period: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Iterate over (sensor_uid, date) groups, classify each day, identify
    the discharge window, mark validity.

    v_c_by_sensor: optional {sensor_uid: speed_at_capacity_mph} from a prior FD.
                   When missing, default_v_c_mph is used.

    Returns:
        episodes_df    — one row per (sensor, date, period)
        reliability_df — one row per sensor_uid
        summary        — dict for the stage2 JSON
    """
    df_qc = df_qc.copy()
    df_qc["date"] = pd.to_datetime(df_qc["datetime"]).dt.date
    if by_period:
        df_qc["__period__"] = df_qc["datetime"].apply(_period_for_timestamp)
    else:
        df_qc["__period__"] = "all_day"

    corridor_by_sensor = (df_qc.groupby("sensor_uid")["corridor"].first().to_dict()
                          if "corridor" in df_qc.columns else {})

    rows = []
    group_keys = ["sensor_uid", "date", "__period__"] if by_period else ["sensor_uid", "date"]
    for keys, grp in df_qc.groupby(group_keys, sort=False):
        if by_period:
            sid, date, period_lab = keys
        else:
            sid, date = keys
            period_lab = "all_day"
        if period_lab == "NT":           # skip overnight — uncongested by definition
            continue
        grp = grp.sort_values("datetime").reset_index(drop=True)
        if len(grp) < 6:
            continue
        # QC-mask the speed: unusable points become NaN
        v = np.where(grp["qc_pass"].to_numpy() == 1,
                     grp["speed_mph_clean"].to_numpy(),
                     np.nan)
        q = grp["flow_vph"].to_numpy() if "flow_vph" in grp.columns else None
        v_c = (v_c_by_sensor or {}).get(sid, default_v_c_mph)

        cl = classify_day(v, q, v_c_mph=v_c, dt_min=dt_min)
        d_win = discharge_window(v, q, cl["t0_index"], cl["t2_index"],
                                 cl["t3_index"], v_c_mph=v_c)
        is_valid = (
            cl["P_min"] >= TAXONOMY_THRESHOLDS["uncongested_max_P_min"]
            and cl["min_speed_mph"] < v_c
            and d_win is not None
        )

        rows.append({
            "sensor_uid": sid,
            "corridor": corridor_by_sensor.get(sid, "UNKNOWN"),
            "date": str(date),
            "period": period_lab,
            "regime": cl["regime"],
            "t0_index": cl["t0_index"],
            "t2_index": cl["t2_index"],
            "t3_index": cl["t3_index"],
            "P_min": cl["P_min"],
            "min_speed_mph": cl["min_speed_mph"],
            "v_c_mph": cl["v_c_mph"],
            "demand_veh": cl["demand_veh"],
            "episode_id": f"{sid}__{date}__{period_lab}",
            "dc_existence": cl["method"] == "SBM",
            "is_valid_for_mu": is_valid,
            "discharge_start_idx": d_win[0] if d_win else np.nan,
            "discharge_end_idx": d_win[1] if d_win else np.nan,
        })

    episodes_df = pd.DataFrame(rows, columns=EPISODE_COLUMNS) if rows else pd.DataFrame(columns=EPISODE_COLUMNS)

    # Boundary-merge pass: when a queue CROSSES the 16:00 MD->PM edge (MD episode
    # pinned at its last index AND PM episode pinned at its first), the MD "P" is
    # right-truncated, the PM "P" left-truncated, and the MD "discharge window"
    # is mid-queue flow — not discharge. Re-evaluate the stitched 10:00-20:00
    # window as ONE episode labelled MDPM; the two constituents stay in the CSV
    # for audit but are dropped from mu/QVDF (is_valid_for_mu=False).
    # (Motivating data: I-210E 2026-06, 84% of valid MD episodes boundary-pinned,
    # 95% of PM episodes started congested.)
    if by_period and len(episodes_df) > 0:
        md_len = (PERIOD_DEFINITIONS["MD"][1] - PERIOD_DEFINITIONS["MD"][0]) * int(60 / dt_min)
        by_key = {(r.sensor_uid, r.date, r.period): i
                  for i, r in episodes_df.iterrows()}
        merged_rows, superseded = [], []
        for (sid, date), _ in episodes_df.groupby(["sensor_uid", "date"], sort=False):
            i_md = by_key.get((sid, date, "MD"))
            i_pm = by_key.get((sid, date, "PM"))
            if i_md is None or i_pm is None:
                continue
            md, pm = episodes_df.loc[i_md], episodes_df.loc[i_pm]
            if not (md["dc_existence"] and pm["dc_existence"]
                    and int(md["t3_index"]) >= md_len - 1
                    and int(pm["t0_index"]) == 0):
                continue
            grp = df_qc[(df_qc["sensor_uid"] == sid)
                        & (df_qc["date"].astype(str) == str(date))]
            hrs = pd.to_datetime(grp["datetime"]).dt.hour
            grp = grp[(hrs >= PERIOD_DEFINITIONS["MD"][0])
                      & (hrs < PERIOD_DEFINITIONS["PM"][1])].sort_values("datetime").reset_index(drop=True)
            if len(grp) < 6:
                continue
            v = np.where(grp["qc_pass"].to_numpy() == 1,
                         grp["speed_mph_clean"].to_numpy(), np.nan)
            q = grp["flow_vph"].to_numpy() if "flow_vph" in grp.columns else None
            v_c = (v_c_by_sensor or {}).get(sid, default_v_c_mph)
            cl = classify_day(v, q, v_c_mph=v_c, dt_min=dt_min)
            d_win = discharge_window(v, q, cl["t0_index"], cl["t2_index"],
                                     cl["t3_index"], v_c_mph=v_c)
            is_valid = (cl["P_min"] >= TAXONOMY_THRESHOLDS["uncongested_max_P_min"]
                        and cl["min_speed_mph"] < v_c and d_win is not None)
            merged_rows.append({
                "sensor_uid": sid,
                "corridor": md["corridor"], "date": str(date), "period": "MDPM",
                "regime": cl["regime"],
                "t0_index": cl["t0_index"], "t2_index": cl["t2_index"],
                "t3_index": cl["t3_index"], "P_min": cl["P_min"],
                "min_speed_mph": cl["min_speed_mph"], "v_c_mph": cl["v_c_mph"],
                "demand_veh": cl["demand_veh"],
                "episode_id": f"{sid}__{date}__MDPM",
                "dc_existence": cl["method"] == "SBM",
                "is_valid_for_mu": is_valid,
                "discharge_start_idx": d_win[0] if d_win else np.nan,
                "discharge_end_idx": d_win[1] if d_win else np.nan,
            })
            superseded.extend([i_md, i_pm])
        if merged_rows:
            episodes_df.loc[superseded, "is_valid_for_mu"] = False
            episodes_df = pd.concat(
                [episodes_df, pd.DataFrame(merged_rows, columns=EPISODE_COLUMNS)],
                ignore_index=True)
            print(f"   [stage2] boundary-merge: stitched {len(merged_rows)} MD+PM "
                  f"episode pairs into MDPM (constituents kept, de-validated)")

    # Second pass: per-link z-score → event-day flag (overrides regime for outliers).
    # Baseline is per (sensor, PERIOD): AM/MD/PM have structurally different P, so a
    # sensor-only baseline mixes them and both inflates the MAD and biases the median
    # (every PM day reads as +z, every AM day as -z). Same period-awareness rule as
    # the episode indices themselves.
    if len(episodes_df) > 0:
        ev_z = TAXONOMY_THRESHOLDS["event_z_threshold"]
        for (sid, _per), grp in episodes_df.groupby(["sensor_uid", "period"]):
            if len(grp) < 5:                # need a baseline; skip on short windows
                continue
            P_med = grp["P_min"].median()
            P_mad = (grp["P_min"] - P_med).abs().median() * 1.4826
            if not np.isfinite(P_mad) or P_mad <= 0:
                continue
            z = (grp["P_min"] - P_med) / P_mad
            event_mask = z.abs() > ev_z
            for idx in grp.index[event_mask]:
                # Only override if currently classified as severe/recurring (true outliers
                # within a congested regime); don't reclassify uncongested days as events.
                if episodes_df.at[idx, "regime"] in ("severe", "recurring"):
                    episodes_df.at[idx, "regime"] = "event"

    # Reliability per sensor
    by_sensor = (episodes_df.groupby("sensor_uid")
                            .agg(n_episodes_total=("episode_id", "count"),
                                 n_episodes_valid=("is_valid_for_mu", "sum"),
                                 regime_counts=("regime",
                                                lambda s: s.value_counts().to_dict()))
                            .reset_index())
    by_sensor["reliability_class"] = by_sensor["n_episodes_valid"].apply(classify_link_reliability)

    regime_dist = episodes_df["regime"].value_counts(dropna=False).to_dict() if len(episodes_df) else {}
    summary = dict(
        n_episodes=int(len(episodes_df)),
        n_valid=int(episodes_df["is_valid_for_mu"].sum()) if len(episodes_df) else 0,
        n_sensors=int(by_sensor["sensor_uid"].nunique()) if len(by_sensor) else 0,
        regime_distribution=regime_dist,
        reliability_distribution=by_sensor["reliability_class"].value_counts().to_dict()
            if len(by_sensor) else {},
    )
    return episodes_df, by_sensor, summary


def write_stage2(episodes_df: pd.DataFrame,
                 reliability_df: pd.DataFrame,
                 summary: dict,
                 out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    episodes_df.to_csv(out_dir / "episodes_per_link_day.csv", index=False)
    # regime_counts column holds dicts — drop it for the CSV view
    rel_view = reliability_df.drop(columns=["regime_counts"], errors="ignore")
    rel_view.to_csv(out_dir / "link_reliability.csv", index=False)
    with open(out_dir / "episodes_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=float)
