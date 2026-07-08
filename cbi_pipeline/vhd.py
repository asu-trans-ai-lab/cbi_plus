# -*- coding: utf-8 -*-
"""vhd — honest vehicle-hours of delay (POL-6).

The monetization base the policy panel demanded, built the only honest way:

    VHD = sum over epochs of  (per-lane flow x lanes x dt) x max(0, TT - TT_ref)

with three hard gates:
  1. volume must be MEASURED — synthesized (inverse-S3) or speed-only
     corridors raise, because modeled volume must never become dollars;
  2. lanes and length_mi must be present per sensor (excluded otherwise,
     and counted in the summary);
  3. dollars appear ONLY when the caller supplies a value of time — and
     the result carries the no-double-counting guardrail.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_vhd(df: pd.DataFrame,
                ref_speed: str | float = "free_flow",
                vot_usd_per_veh_h: float | None = None) -> dict:
    """Vehicle-hours of delay per sensor-day, with corridor totals.

    ref_speed: "free_flow" (per-sensor p95 speed) or a numeric mph
    threshold (agency-policy reference, PHED-style).
    """
    spd_col = "speed_mph_clean" if "speed_mph_clean" in df.columns else "speed_mph"
    need = {"flow_vph", "lanes", "length_mi", spd_col, "sensor_uid", "datetime"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"compute_vhd needs columns {sorted(missing)}")

    # gate 1: measured volume only
    if "flow_synthetic" in df.columns and bool(df["flow_synthetic"].any()):
        raise ValueError(
            "VHD refused: flow is SYNTHESIZED on at least one sensor. "
            "Modeled volume must never be monetized — supply counted volume "
            "(volume_source == 'measured') or do not compute VHD.")
    if "has_volume" in df.columns and not bool(df["has_volume"].any()):
        raise ValueError("VHD refused: no measured volume in this frame.")

    d = df[["sensor_uid", "datetime", spd_col, "flow_vph",
            "lanes", "length_mi"]].dropna(subset=[spd_col, "flow_vph"]).copy()
    # gate 2: geometry present
    geom_ok = d["lanes"].notna() & d["length_mi"].notna()
    n_excluded = int(d.loc[~geom_ok, "sensor_uid"].nunique())
    d = d[geom_ok]
    if not len(d):
        raise ValueError("VHD refused: no sensor carries both lanes and length_mi.")

    if ref_speed == "free_flow":
        vref = d.groupby("sensor_uid")[spd_col].transform(
            lambda s: s.quantile(0.95))
        ref_note = "per-sensor p95 free flow"
    else:
        vref = float(ref_speed)
        ref_note = f"fixed threshold {float(ref_speed):.0f} mph"

    dt_h = 5.0 / 60.0
    v = d[spd_col].clip(lower=3.0)
    tt = d["length_mi"] / v                     # hours per vehicle
    tt_ref = d["length_mi"] / np.maximum(vref, 1.0)
    veh = d["flow_vph"] * d["lanes"] * dt_h     # vehicles this epoch (per-lane x lanes)
    d["vhd"] = veh * np.clip(tt - tt_ref, 0, None)
    d["date"] = d["datetime"].dt.date.astype(str)

    per_sensor_day = (d.groupby(["sensor_uid", "date"])["vhd"].sum()
                        .round(1).reset_index())
    per_day = per_sensor_day.groupby("date")["vhd"].sum().round(1)
    out = {
        "per_sensor_day": per_sensor_day,
        "corridor_veh_h_per_day": {k: float(v) for k, v in per_day.items()},
        "median_corridor_veh_h_per_day": float(per_day.median()),
        "reference_speed": ref_note,
        "volume_basis": "measured",
        "n_sensors_excluded_missing_geometry": n_excluded,
        "guardrail": ("VHD already contains duration and severity — never ALSO "
                      "monetize duration/deficit/stability tokens on top of it "
                      "(double counting). Before/after VHD holds demand fixed; "
                      "net induced-demand rebound before claiming savings."),
    }
    if vot_usd_per_veh_h is not None:
        out["usd_per_day_median"] = round(
            out["median_corridor_veh_h_per_day"] * float(vot_usd_per_veh_h), 0)
        out["vot_usd_per_veh_h"] = float(vot_usd_per_veh_h)
        out["monetization_note"] = ("dollars valid only with the guardrail above; "
                                    "VOT is caller-supplied policy, not measured")
    return out
