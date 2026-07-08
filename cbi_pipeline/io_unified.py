"""
io_unified.py — Stage 0.

Loads PeMS (speed + volume, 5-min) and INRIX TMC (speed-only, 1-min) inputs
into the common schema declared in schemas.TIMESERIES_COLUMNS.

Two public entry points:

    load_sensor_timeseries(sensor_record, t_start=None, t_end=None) -> DataFrame
    build_corridor_panel(corridor_name, source, **kwargs)            -> dict
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .schemas import (TIMESERIES_COLUMNS, DEFAULT_S3_PARAMS,
                      S3_PRIOR_PRESETS, resolve_s3_prior)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BUNDLE_ROOT = Path(__file__).resolve().parents[2]          # .../clean_handoff_v1
INPUT_DIR = BUNDLE_ROOT / "01_input_data"


# ===========================================================================
# CBI inverse-S3 synthesizer  (speed -> volume when flow is not measured)
# ===========================================================================
def synthesize_volume_s3(speed_mph,
                         vf_mph: float = DEFAULT_S3_PARAMS["vf_mph"],
                         k_critical_vpm: float = DEFAULT_S3_PARAMS["k_critical_vpm"],
                         s3_m: float = DEFAULT_S3_PARAMS["s3_m"],
                         lane_capacity_vphpl: Optional[float] = DEFAULT_S3_PARAMS["lane_capacity_vphpl"]):
    """
    Inverse S3 fundamental diagram: per-lane flow from per-lane speed.

    Reference implementation:
        CBI-main/src/python/DTA.py:661  (get_volume_from_speed)
        CBI-main/src/python/VDF.py:134  (also get_volume_from_speed)
        CBI-main/src/cpp/VDF.h          (C++ equivalent)

    Units: speed in mph, k_critical in veh/mile/lane => returns vph/lane.
    """
    s = np.asarray(speed_mph, dtype=float)
    if lane_capacity_vphpl is None:
        lane_capacity_vphpl = float(k_critical_vpm * vf_mph / (2.0 ** (2.0 / s3_m)))

    out = np.full_like(s, np.nan, dtype=float)
    finite = np.isfinite(s) & (s >= 0)
    s_clipped = np.minimum(s, vf_mph * 0.99)
    ratio = vf_mph / np.maximum(1.0, s_clipped)
    ratio = np.maximum(ratio, 1.00001)
    rd = np.power(ratio, s3_m / 2.0) - 1.0
    rd = np.maximum(rd, 1e-8)
    vol = s_clipped * k_critical_vpm * np.power(rd, 1.0 / s3_m)
    vol = np.minimum(vol, lane_capacity_vphpl)
    out[finite] = vol[finite]
    return out


def synthesize_density_from_flow_speed(flow_vph, speed_mph):
    """k = q / v; safe against zero/negative speed."""
    q = np.asarray(flow_vph, dtype=float)
    v = np.asarray(speed_mph, dtype=float)
    v_safe = np.where(v > 1.0, v, np.nan)
    return q / v_safe


def estimate_vf_from_speed(speed_mph, percentile: float = 95.0,
                           min_samples: int = 200) -> Optional[float]:
    """Robust vf estimate from observed speeds (the (percentile)-th quantile)."""
    s = np.asarray(speed_mph, dtype=float)
    s = s[np.isfinite(s) & (s > 0)]
    if len(s) < min_samples:
        return None
    return float(np.percentile(s, percentile))


def calibrate_s3_priors_from_data(speed_mph,
                                  base_prior="cbi_default",
                                  adjust_vf: bool = True,
                                  vf_percentile: float = 95.0,
                                  rederive_kc_and_m: bool = False,
                                  v_critical_ratio: float = 0.70) -> dict:
    """
    Adjust the S3 prior given a sample of speeds.

    By default ONLY vf is calibrated (it is identifiable from speed alone).
    k_critical and s3_m can be re-derived from the assumed v_critical_ratio
    if `rederive_kc_and_m=True`, using the closed-form CBI relations:

        v_critical    = v_critical_ratio * vf
        s3_m          = 2 * ln(2) / ln(vf / v_critical)
        k_critical    = lane_capacity / v_critical

    The provenance string in the returned dict records every adjustment made.
    """
    params = resolve_s3_prior(base_prior)
    log = [params.get("provenance", "")]

    if adjust_vf:
        vf_hat = estimate_vf_from_speed(speed_mph, percentile=vf_percentile)
        if vf_hat is not None:
            log.append(f"vf calibrated to p{vf_percentile} of observed speeds = {vf_hat:.2f} mph")
            params["vf_mph"] = vf_hat

    if rederive_kc_and_m:
        vf = params["vf_mph"]
        v_c = v_critical_ratio * vf
        cap = params["lane_capacity_vphpl"]
        if vf > 1.0 and v_c > 1.0 and vf > v_c:
            params["s3_m"] = float(2.0 * np.log(2.0) / np.log(vf / v_c))
            params["k_critical_vpm"] = float(cap / v_c)
            log.append(f"k_c and s3_m rederived: v_c={v_c:.2f} mph, "
                       f"k_c={params['k_critical_vpm']:.2f}, s3_m={params['s3_m']:.3f}")

    params["provenance"] = " | ".join(p for p in log if p)
    return params
PEMS_JSON_REPRESENTATIVE = INPUT_DIR / "link_performance_representative.json"
PEMS_JSON_ALL = INPUT_DIR / "link_performance_all_sensors.json"
SENSOR_INFO_CSV = INPUT_DIR / "sensor_information.csv"


# ===========================================================================
# PeMS loader
# ===========================================================================
def _load_pems_compact_json(path: Path) -> pd.DataFrame:
    """
    Read the compact JSON used by the existing Part1 pipeline.

    Schema (per sensor):  meta, t0 (ISO start), dt (e.g. "5min"), n,
                          f (flows vph), s (speeds — actually km/h in this dataset),
                          d (densities veh/km).
    """
    with open(path, "r") as f:
        blob = json.load(f)

    rows = []
    for sensor_id, payload in blob.items():
        n = int(payload.get("n", 0))
        if n == 0:
            continue
        t0 = pd.Timestamp(payload["t0"])
        dt = pd.Timedelta(payload.get("dt", "5min"))
        times = pd.date_range(start=t0, periods=n, freq=dt)
        # NOTE: 's' is stored as km/h despite the legacy 'speed_mph' name downstream.
        # Convert to mph for the unified schema.
        speeds_kph = np.asarray(payload.get("s", []), dtype=float)
        speeds_mph = speeds_kph / 1.609 if speeds_kph.size else speeds_kph
        flows = np.asarray(payload.get("f", []), dtype=float)
        densities = np.asarray(payload.get("d", []), dtype=float)
        rows.append(pd.DataFrame({
            "sensor_uid": [f"pems::{sensor_id}"] * n,
            "datetime": times,
            "speed_mph": speeds_mph,
            "flow_vph": flows,
            "density_vpm": densities,
        }))
    df = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    return df


def _attach_pems_metadata(df: pd.DataFrame, info_csv: Path = SENSOR_INFO_CSV) -> pd.DataFrame:
    info = pd.read_csv(info_csv)
    info["sensor_uid"] = "pems::" + info["sensor_id"].astype(str)
    info["corridor"] = info["Fwy"].astype(str) + "-" + info["Dir"].astype(str)
    info_subset = info[["sensor_uid", "Lanes", "Length", "Abs_PM", "Dir", "corridor"]].rename(
        columns={"Lanes": "lanes", "Length": "length_mi",
                 "Abs_PM": "road_order", "Dir": "direction"})
    out = df.merge(info_subset, on="sensor_uid", how="left")
    out["has_volume"] = True
    out["flow_synthetic"] = False
    out["source_format"] = "pems_json"
    return out


def load_pems(t_start: Optional[str] = None, t_end: Optional[str] = None,
              path: Optional[Path] = None, representative: bool = True) -> pd.DataFrame:
    """Load PeMS data into the common timeseries schema."""
    if path is None:
        path = PEMS_JSON_REPRESENTATIVE if representative else PEMS_JSON_ALL
    df = _load_pems_compact_json(Path(path))
    if df.empty:
        return df
    df = _attach_pems_metadata(df)
    if t_start is not None:
        df = df[df["datetime"] >= pd.Timestamp(t_start)]
    if t_end is not None:
        df = df[df["datetime"] <= pd.Timestamp(t_end)]
    for col in TIMESERIES_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    return df[TIMESERIES_COLUMNS].reset_index(drop=True)


# ===========================================================================
# INRIX TMC loader
# ===========================================================================
def _resample_inrix_5min(df1min: pd.DataFrame) -> pd.DataFrame:
    """Resample 1-minute INRIX speeds to 5-minute median."""
    df1min = df1min.set_index("datetime").sort_index()
    out = (df1min.groupby("tmc_code")["speed"]
           .resample("5min").median()
           .reset_index()
           .rename(columns={"speed": "speed_mph"}))
    return out


def load_inrix(readings_csv: Path,
               tmc_id_csv: Path,
               corridor_name: Optional[str] = None,
               t_start: Optional[str] = None,
               t_end: Optional[str] = None,
               synthesize_flow: bool = True,
               s3_prior="cbi_default",
               s3_params: Optional[dict] = None,
               auto_calibrate_vf: bool = True,
               rederive_kc_and_m: bool = False) -> pd.DataFrame:
    """Load an INRIX export (Readings.csv + TMC_Identification.csv) into the common schema."""
    readings_csv = Path(readings_csv)
    tmc_id_csv = Path(tmc_id_csv)

    # TMC geometry
    meta = pd.read_csv(tmc_id_csv)
    meta = meta.rename(columns={
        "tmc": "tmc_code",
        "miles": "length_mi",
        "direction": "direction",
    })
    keep_cols = ["tmc_code", "road", "direction", "length_mi", "road_order"]
    meta = meta[[c for c in keep_cols if c in meta.columns]]
    if corridor_name is None:
        if "road" in meta.columns:
            corridor_name = str(meta["road"].iloc[0])
        else:
            corridor_name = "INRIX"
    meta["corridor"] = corridor_name

    # Speed readings — 1-min cadence
    readings = pd.read_csv(readings_csv,
                           usecols=["tmc_code", "measurement_tstamp", "speed"])
    readings["datetime"] = pd.to_datetime(readings["measurement_tstamp"],
                                          format="%Y-%m-%d %H:%M:%S",
                                          errors="coerce")
    readings = readings.dropna(subset=["datetime", "speed"])
    readings["speed"] = readings["speed"].astype(float)

    if t_start is not None:
        readings = readings[readings["datetime"] >= pd.Timestamp(t_start)]
    if t_end is not None:
        readings = readings[readings["datetime"] <= pd.Timestamp(t_end)]

    rs5 = _resample_inrix_5min(readings[["tmc_code", "datetime", "speed"]])
    rs5["sensor_uid"] = "inrix::" + rs5["tmc_code"].astype(str)

    out = rs5.merge(meta, on="tmc_code", how="left")
    out["lanes"] = np.nan       # INRIX doesn't report lane count
    out["has_volume"] = False   # never a real measurement on INRIX
    out["source_format"] = "inrix_tmc"

    if synthesize_flow:
        # 1) Start from a named preset (or 'cbi_default').
        params = resolve_s3_prior(s3_prior)
        # 2) Optionally adjust vf (and re-derive k_c, m) from the speed sample itself.
        if auto_calibrate_vf or rederive_kc_and_m:
            params = calibrate_s3_priors_from_data(
                out["speed_mph"].to_numpy(),
                base_prior=params,
                adjust_vf=auto_calibrate_vf,
                rederive_kc_and_m=rederive_kc_and_m,
            )
        # 3) Hard-override with any explicit s3_params (wins over everything).
        if s3_params:
            params.update(s3_params)
            params["provenance"] = (params.get("provenance", "")
                                    + f" | user override: {s3_params}")

        print(f"[load_inrix] S3 prior in use: vf={params['vf_mph']:.1f} mph, "
              f"k_c={params['k_critical_vpm']:.1f} vpm, m={params['s3_m']:.2f}, "
              f"C={params['lane_capacity_vphpl']:.0f} vphpl")
        print(f"             provenance: {params['provenance']}")

        synth_kwargs = {k: params[k] for k in
                        ("vf_mph", "k_critical_vpm", "s3_m", "lane_capacity_vphpl")}
        out["flow_vph"] = synthesize_volume_s3(out["speed_mph"].to_numpy(), **synth_kwargs)
        out["density_vpm"] = synthesize_density_from_flow_speed(
            out["flow_vph"].to_numpy(), out["speed_mph"].to_numpy())
        out["flow_synthetic"] = True
        # Stamp the provenance on the DataFrame as an attribute (survives pickling
        # but not parquet) — and also as a column for the safest case.
        out.attrs["s3_prior"] = params
        out["s3_prior_label"] = params.get("provenance", "")
    else:
        out["flow_vph"] = np.nan
        out["density_vpm"] = np.nan
        out["flow_synthetic"] = False
        out["s3_prior_label"] = "speed_only_no_synthesis"

    for col in TIMESERIES_COLUMNS:
        if col not in out.columns:
            out[col] = np.nan

    return out[TIMESERIES_COLUMNS].reset_index(drop=True)


def load_inrix_folder(folder: Path,
                      t_start: Optional[str] = None,
                      t_end: Optional[str] = None,
                      s3_prior="cbi_default",
                      s3_params: Optional[dict] = None,
                      auto_calibrate_vf: bool = True,
                      rederive_kc_and_m: bool = False,
                      synthesize_flow: bool = True) -> pd.DataFrame:
    """Convenience: load an INRIX export folder (Readings.csv + TMC_Identification.csv)."""
    folder = Path(folder)
    readings = folder / "Readings.csv"
    tmc_id = folder / "TMC_Identification.csv"
    if not readings.exists() or not tmc_id.exists():
        raise FileNotFoundError(f"Expected Readings.csv and TMC_Identification.csv in {folder}")
    return load_inrix(readings, tmc_id, t_start=t_start, t_end=t_end,
                      synthesize_flow=synthesize_flow,
                      s3_prior=s3_prior, s3_params=s3_params,
                      auto_calibrate_vf=auto_calibrate_vf,
                      rederive_kc_and_m=rederive_kc_and_m)


# ===========================================================================
# Unified entry points
# ===========================================================================
def load_sensor_timeseries(source: str, **kwargs) -> pd.DataFrame:
    """Dispatch loader by source label."""
    source = source.lower()
    if source in ("pems", "pems_json"):
        return load_pems(**kwargs)
    if source in ("inrix", "inrix_tmc"):
        if "folder" in kwargs:
            return load_inrix_folder(**kwargs)
        return load_inrix(**kwargs)
    raise ValueError(f"Unknown source: {source!r}")


def build_corridor_panel(df: pd.DataFrame) -> dict:
    """
    Reshape a long DataFrame (from load_sensor_timeseries) into a corridor panel:
        {speed_field [T x N], time_axis, sensor_ids, road_order, direction, source_format}
    Sensors are ordered along the corridor by `road_order`.
    """
    if df.empty:
        return dict(speed_field=np.zeros((0, 0)), time_axis=[], sensor_ids=[],
                    road_order=[], direction=[], source_format=None)

    ro = (df.groupby("sensor_uid")["road_order"].first()
            .sort_values(kind="mergesort"))
    sensor_ids = ro.index.tolist()

    pivot = (df.pivot_table(index="datetime", columns="sensor_uid",
                            values="speed_mph", aggfunc="first")
                .reindex(columns=sensor_ids))

    flow_pivot = (df.pivot_table(index="datetime", columns="sensor_uid",
                                 values="flow_vph", aggfunc="first")
                    .reindex(columns=sensor_ids))

    meta = (df.groupby("sensor_uid")
              .agg(direction=("direction", "first"),
                   lanes=("lanes", "first"),
                   length_mi=("length_mi", "first"),
                   road_order=("road_order", "first"),
                   has_volume=("has_volume", "first"),
                   corridor=("corridor", "first"),
                   source_format=("source_format", "first"))
              .reindex(sensor_ids))

    return dict(
        speed_field=pivot.to_numpy(dtype=float),
        flow_field=flow_pivot.to_numpy(dtype=float),
        time_axis=pivot.index.to_numpy(),
        sensor_ids=sensor_ids,
        road_order=meta["road_order"].to_numpy(dtype=float),
        direction=meta["direction"].to_list(),
        lanes=meta["lanes"].to_numpy(dtype=float),
        length_mi=meta["length_mi"].to_numpy(dtype=float),
        has_volume=bool(meta["has_volume"].iloc[0]),
        corridor=str(meta["corridor"].iloc[0]) if len(meta) else None,
        source_format=str(meta["source_format"].iloc[0]) if len(meta) else None,
    )


# ===========================================================================
# Public smoke test
# ===========================================================================
def _smoke_test_i17():
    folder = INPUT_DIR / "I-17" / "I-17"
    df = load_inrix_folder(folder)
    panel = build_corridor_panel(df)
    print(f"INRIX I-17 loader: {len(df):,} rows, "
          f"{df['sensor_uid'].nunique()} TMCs, "
          f"speed_field shape {panel['speed_field'].shape}")
    return df, panel


if __name__ == "__main__":
    _smoke_test_i17()
