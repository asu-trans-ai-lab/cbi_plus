"""
stage1_qc.py — speed-data quality control (Layer 1).

Five checks, each adding a flag column:
    hard_physical_range       — v < 0 or v > min(1.25 v_f, 90 mph)
    temporal_jump_check       — |dv/dt| > threshold
    hampel_filter             — rolling-median MAD outlier
    spatial_consistency       — adjacent-sensor median deviation
    speed_wave_direction_check — drop-time ordering vs corridor LRS

A row's `qc_pass` is the AND of all five. `speed_mph_clean` is the
Hampel-cleaned series with unrecoverable points set to NaN.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .schemas import QC_FLAG_COLUMNS


# ---------------------------------------------------------------------------
# Per-sensor 1-D checks
# ---------------------------------------------------------------------------
def hard_physical_range(speed: np.ndarray,
                        v_f_mph: float = 75.0,
                        v_max_factor: float = 1.25,
                        v_max_abs: float = 90.0) -> np.ndarray:
    """Return mask of 1=OK, 0=flagged."""
    upper = min(v_max_factor * v_f_mph, v_max_abs)
    return ((speed >= 0) & (speed <= upper) & np.isfinite(speed)).astype(np.int8)


def temporal_jump_check(speed: np.ndarray, dv_max: float = 30.0) -> np.ndarray:
    """Flag points whose absolute first-difference exceeds dv_max (mph)."""
    diffs = np.abs(np.diff(speed, prepend=speed[:1]))
    return (diffs <= dv_max).astype(np.int8)


def hampel_filter(speed: np.ndarray,
                  window: int = 11,
                  n_sigma: float = 3.0) -> tuple[np.ndarray, np.ndarray]:
    """
    Rolling-median MAD outlier detector.

    Returns (cleaned_speed, mask) where mask = 1 if point passed.
    Flagged points are replaced with the rolling median in cleaned_speed.
    """
    speed = np.asarray(speed, dtype=float)
    n = len(speed)
    if n == 0:
        return speed, np.ones(0, dtype=np.int8)

    s = pd.Series(speed)
    med = s.rolling(window=window, center=True, min_periods=1).median()
    abs_dev = (s - med).abs()
    mad = abs_dev.rolling(window=window, center=True, min_periods=1).median()
    scaled_mad = 1.4826 * mad
    scaled_mad = scaled_mad.replace(0.0, np.nan).fillna(scaled_mad.median()).fillna(1.0)
    thresh = n_sigma * scaled_mad
    mask = (abs_dev <= thresh).astype(np.int8).to_numpy()
    cleaned = np.where(mask == 1, speed, med.to_numpy())
    return cleaned, mask


# ---------------------------------------------------------------------------
# Spatial / direction checks (operate on the corridor panel)
# ---------------------------------------------------------------------------
def spatial_consistency(speed_field: np.ndarray,
                        max_gap_mph: float = 20.0) -> np.ndarray:
    """
    For each interior sensor, flag (sensor, time) cells where its speed differs
    by more than `max_gap_mph` from the median of itself and immediate neighbors.

    speed_field shape: [T, N]. Returns mask [T, N] of 1=OK / 0=flag.
    Edge sensors (i=0, i=N-1) are always OK (no two-sided neighbors).
    """
    T, N = speed_field.shape
    mask = np.ones_like(speed_field, dtype=np.int8)
    if N < 3:
        return mask
    for i in range(1, N - 1):
        neighbor_median = np.nanmedian(
            np.vstack([speed_field[:, i - 1], speed_field[:, i], speed_field[:, i + 1]]),
            axis=0,
        )
        diff = np.abs(speed_field[:, i] - neighbor_median)
        mask[:, i] = np.where((diff <= max_gap_mph) | ~np.isfinite(diff), 1, 0).astype(np.int8)
    return mask


def _first_drop_time(speed_series: np.ndarray, v_c: float) -> Optional[int]:
    """Return earliest index t where speed < v_c, or None."""
    below = np.where(speed_series < v_c)[0]
    return int(below[0]) if below.size else None


def _bottleneck_candidates(fd: np.ndarray, min_separation: int = 5) -> list[int]:
    """Local minima of the first-drop profile = independent bottleneck heads.

    A sensor is a candidate if its first-drop time is the minimum within
    ±min_separation sensors. Long corridors (40 mi, 80+ detectors) routinely
    carry several structural bottlenecks; a single global minimum is not a
    valid model of such a corridor."""
    cands = []
    for i in range(len(fd)):
        if np.isnan(fd[i]):
            continue
        lo, hi = max(0, i - min_separation), min(len(fd), i + min_separation + 1)
        seg = fd[lo:hi]
        if np.all(np.isnan(seg)) or fd[i] > np.nanmin(seg):
            continue
        if not cands or i - cands[-1] > min_separation:
            cands.append(i)
    return cands or ([int(np.nanargmin(fd))] if np.isfinite(fd).any() else [])


def _wave_check_one_day(fd: np.ndarray) -> tuple[int, int, list[int], Optional[int]]:
    """Segment-aware upstream-propagation test on ONE day's first-drop profile.

    For each bottleneck candidate, walk upstream only to the midpoint toward the
    next upstream candidate (each bottleneck owns its own catchment); inside a
    segment the first-drop times must be non-decreasing walking upstream.
    Returns (n_ok, n_checked, reversed_sensors, primary_bottleneck_idx)."""
    cands = _bottleneck_candidates(fd)
    if not cands:
        return 0, 0, [], None
    primary = int(min(cands, key=lambda i: fd[i]))
    n_ok = n_checked = 0
    reversed_sensors: list[int] = []
    for ci, b in enumerate(cands):
        seg_start = 0 if ci == 0 else (cands[ci - 1] + b) // 2 + 1
        last_t = fd[b]
        for j in range(b - 1, seg_start - 1, -1):
            if np.isnan(fd[j]):
                continue
            n_checked += 1
            if fd[j] >= last_t - 1:            # allow ±1 tick tolerance
                n_ok += 1
                last_t = fd[j]
            else:
                reversed_sensors.append(int(j))
    return n_ok, n_checked, reversed_sensors, primary


def speed_wave_direction_check(speed_field: np.ndarray,
                               v_c_mph: float = 50.0,
                               min_drop_count: int = 3,
                               bins_per_day: int = 288) -> dict:
    """
    Verify that congestion forms at bottleneck sensors and propagates upstream
    along the LRS (road_order). Returns a dict with:
        direction_confidence : float ∈ [0, 1]
        bottleneck_sensor_idx : int or None (modal primary bottleneck)
        reversed_sensors      : list of indices whose drop ordering is reversed
        first_drop_times      : np.ndarray of first-drop indices (NaN if none)

    Sensors are assumed ordered along travel direction (small road_order = upstream).

    v2.1 (multi-day / multi-bottleneck aware): the field is evaluated PER DAY —
    "first drop over a month" mixes waves from different days — and per day the
    test is SEGMENT-aware: every local minimum of the first-drop profile is its
    own bottleneck with its own upstream catchment. The single-global-minimum
    test systematically fails long multi-bottleneck corridors (I-210E June 2026:
    16 distinct daily first-drop winners; old check = 0.375 confidence on a
    physically healthy corridor).
    """
    T, N = speed_field.shape
    n_days = max(1, T // bins_per_day)

    day_conf: list[float] = []
    all_reversed: set[int] = set()
    primaries: list[int] = []
    for d in range(n_days):
        sl = speed_field[d * bins_per_day:(d + 1) * bins_per_day, :]
        fd = np.array([np.nan if (x := _first_drop_time(sl[:, i], v_c_mph)) is None
                       else float(x) for i in range(N)], dtype=float)
        if np.isfinite(fd).sum() < min_drop_count:
            continue
        n_ok, n_checked, rev, primary = _wave_check_one_day(fd)
        if n_checked > 0:
            day_conf.append(n_ok / n_checked)
            all_reversed.update(rev)
        else:
            # Blind spot guard: if nothing upstream of the head ever dropped, the
            # catchment test is empty — but a contiguous FORWARD-moving wave
            # (first-drop time increasing downstream) is anti-physical (queues
            # grow upstream) and is the classic reversed-map signature. Score it.
            fin = np.isfinite(fd)
            if fin.sum() >= min_drop_count:
                slope = float(np.polyfit(np.where(fin)[0], fd[fin], 1)[0])
                if slope > 1.0:               # > 1 bin per sensor, moving downstream
                    day_conf.append(0.0)
        if primary is not None:
            primaries.append(primary)

    # whole-window profile kept for reporting/back-compat
    first_drops_num = np.array(
        [np.nan if (x := _first_drop_time(speed_field[:, i], v_c_mph)) is None
         else float(x) for i in range(N)], dtype=float)

    if not day_conf:
        return dict(
            direction_confidence=float("nan"),
            bottleneck_sensor_idx=None,
            reversed_sensors=[],
            first_drop_times=first_drops_num,
        )

    modal_primary = int(pd.Series(primaries).mode().iloc[0]) if primaries else None
    return dict(
        direction_confidence=float(np.median(day_conf)),
        bottleneck_sensor_idx=modal_primary,
        reversed_sensors=sorted(all_reversed),
        first_drop_times=first_drops_num,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def run_qc(df_long: pd.DataFrame,
           v_c_mph: float = 50.0,
           v_f_mph: float = 75.0,
           dv_max: float = 30.0,
           hampel_window: int = 11,
           hampel_sigma: float = 3.0,
           max_spatial_gap_mph: float = 20.0) -> tuple[pd.DataFrame, dict]:
    """
    Apply all five QC checks to a long-form DataFrame produced by io_unified.

    Returns (df_with_qc_columns, summary_dict).
    """
    df = df_long.sort_values(["sensor_uid", "datetime"]).reset_index(drop=True).copy()

    # Initialise flag columns
    for col in QC_FLAG_COLUMNS:
        df[col] = 1 if col != "speed_mph_clean" else df["speed_mph"]

    # 1, 2, 3: per-sensor 1-D checks (vectorised by group)
    cleaned_chunks = []
    for sid, grp in df.groupby("sensor_uid", sort=False):
        v = grp["speed_mph"].to_numpy()
        m_range = hard_physical_range(v, v_f_mph=v_f_mph)
        m_jump = temporal_jump_check(v, dv_max=dv_max)
        v_clean, m_hampel = hampel_filter(v, window=hampel_window, n_sigma=hampel_sigma)
        cleaned_chunks.append(pd.DataFrame({
            "_idx": grp.index,
            "qc_hard_range": m_range,
            "qc_jump": m_jump,
            "qc_hampel": m_hampel,
            "speed_mph_clean": v_clean,
        }))
    if cleaned_chunks:
        cc = pd.concat(cleaned_chunks, ignore_index=True).set_index("_idx")
        df.loc[cc.index, ["qc_hard_range", "qc_jump", "qc_hampel", "speed_mph_clean"]] = cc.values

    # 4: spatial — needs corridor panel
    spatial_mask_long = np.ones(len(df), dtype=np.int8)
    direction_info_by_corridor = {}
    for corr, grp in df.groupby("corridor", sort=False):
        from .io_unified import build_corridor_panel
        panel = build_corridor_panel(grp)
        sf = panel["speed_field"]
        if sf.size == 0:
            continue
        m_spatial = spatial_consistency(sf, max_gap_mph=max_spatial_gap_mph)

        # Map back: each (t, sensor) cell -> rows in grp
        sensor_ids = panel["sensor_ids"]
        time_axis = panel["time_axis"]
        sensor_idx = {sid: i for i, sid in enumerate(sensor_ids)}
        time_idx = {pd.Timestamp(t): i for i, t in enumerate(time_axis)}

        for row_idx, (sid, ts) in zip(
            grp.index,
            zip(grp["sensor_uid"], grp["datetime"])):
            si = sensor_idx.get(sid)
            ti = time_idx.get(pd.Timestamp(ts))
            if si is None or ti is None:
                continue
            spatial_mask_long[row_idx] = m_spatial[ti, si]

        # 5: direction check (corridor-level, broadcast to all rows of this corridor)
        dir_info = speed_wave_direction_check(sf, v_c_mph=v_c_mph)
        direction_info_by_corridor[corr] = dir_info

    df["qc_spatial"] = spatial_mask_long

    # Direction flag — a corridor with confidence < 0.5 marks all its rows 0
    df["qc_direction"] = 1
    for corr, info in direction_info_by_corridor.items():
        conf = info["direction_confidence"]
        if conf == conf and conf < 0.5:                # not-NaN AND below threshold
            df.loc[df["corridor"] == corr, "qc_direction"] = 0

    # Aggregate
    # qc_direction is a CORRIDOR-LEVEL diagnostic (already surfaced separately as
    # the min_direction_confidence quality gate). It must not zero out every row's
    # per-row data-validity QC: on a multi-day stacked INRIX panel the wave-
    # propagation statistic is computed over the whole month, so a single low value
    # would discard all otherwise-clean rows. Keep it reported, exclude it from the
    # per-row pass flag.
    flag_cols = ["qc_hard_range", "qc_jump", "qc_hampel", "qc_spatial"]
    df["qc_pass"] = df[flag_cols].min(axis=1)

    # Summary
    summary = dict(
        n_rows=int(len(df)),
        n_sensors=int(df["sensor_uid"].nunique()),
        qc_pass_rate=float(df["qc_pass"].mean()) if len(df) else float("nan"),
        per_check_pass_rate={c: float(df[c].mean()) for c in flag_cols},
        direction_by_corridor={
            c: {k: (v.tolist() if isinstance(v, np.ndarray) else v)
                for k, v in info.items()}
            for c, info in direction_info_by_corridor.items()
        },
    )
    return df, summary


def write_stage1(df_qc: pd.DataFrame, summary: dict, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_dir = out_dir / "per_sensor"
    parquet_dir.mkdir(exist_ok=True)
    for sid, grp in df_qc.groupby("sensor_uid"):
        safe = sid.replace(":", "_").replace("/", "_")
        grp.to_parquet(parquet_dir / f"{safe}.parquet", index=False)
    pass_by_sensor = (df_qc.groupby("sensor_uid")["qc_pass"].mean()
                          .rename("qc_pass_rate").reset_index())
    pass_by_sensor.to_csv(out_dir / "stage1_qc_summary.csv", index=False)
    with open(out_dir / "stage1_qc_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=float)
