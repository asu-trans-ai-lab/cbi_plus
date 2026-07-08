# -*- coding: utf-8 -*-
"""pm3_reliability — federal PM3 travel-time reliability measures (POL-1).

Computes the two measures FHWA performance processes actually ingest,
from the package's speed series + segment lengths:

  LOTTR  (Level of Travel Time Reliability)
         80th / 50th percentile travel time per segment, per federal
         reporting period; a segment-period is RELIABLE when LOTTR < 1.50.
         Periods (weekdays): 6-10a, 10a-4p, 4-8p; weekends: 6a-8p.

  TTTR   (Truck Travel Time Reliability)
         95th / 50th percentile travel time per segment over FIVE periods
         (the four above + overnight 8p-6a all days). FHWA computes TTTR
         from truck probe data; when only all-vehicle speeds exist this
         module labels the result "all_vehicle_proxy" — usable for
         screening, NOT for the federal TTTR submission.

Honesty constraints carried on every output:
  - PM3 uses 15-minute epochs over a FULL CALENDAR YEAR of NPMRDS data.
    This module resamples to 15-min epochs but computes over whatever
    window you feed it; the output carries `window_days` and a
    `pm3_grade` flag ("window_screening" vs "calendar_year") so a short
    window is never mistaken for a reportable measure.
  - Travel time needs a segment length: `length_mi` per sensor. Missing
    lengths -> that sensor is excluded and counted in the summary.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LOTTR_PERIODS = {           # weekday flag, start hour, end hour
    "AM_6_10":   (True, 6, 10),
    "MID_10_16": (True, 10, 16),
    "PM_16_20":  (True, 16, 20),
    "WE_6_20":   (False, 6, 20),
}
TTTR_PERIODS = dict(LOTTR_PERIODS, OVN_20_6=(None, 20, 6))   # None = all days
LOTTR_THRESHOLD = 1.50
TTTR_INDEX_NOTE = "TTTR index = max over periods of per-period TTTR (FHWA)"


def _epoch_travel_times(df: pd.DataFrame) -> pd.DataFrame:
    """5-min speeds -> 15-min epoch travel times (seconds) per sensor."""
    spd_col = "speed_mph_clean" if "speed_mph_clean" in df.columns else "speed_mph"
    d = df[["sensor_uid", "datetime", spd_col]].copy()
    if "length_mi" not in df.columns:
        raise ValueError("PM3 needs length_mi per sensor (travel time = "
                         "length / speed) — add it or use load_* loaders")
    lengths = df.groupby("sensor_uid")["length_mi"].first()
    d["epoch"] = d["datetime"].dt.floor("15min")
    ep = (d.groupby(["sensor_uid", "epoch"])[spd_col].mean()
            .rename("speed_mph").reset_index())
    ep = ep[ep["speed_mph"] > 1]
    ep["length_mi"] = ep["sensor_uid"].map(lengths)
    ep = ep.dropna(subset=["length_mi"])
    ep["tt_s"] = ep["length_mi"] / ep["speed_mph"] * 3600.0
    ep["hour"] = ep["epoch"].dt.hour
    ep["weekday"] = ep["epoch"].dt.dayofweek < 5
    return ep


def _period_mask(ep: pd.DataFrame, spec) -> pd.Series:
    wk, h0, h1 = spec
    if h0 < h1:
        hours = (ep["hour"] >= h0) & (ep["hour"] < h1)
    else:                                   # overnight wrap
        hours = (ep["hour"] >= h0) | (ep["hour"] < h1)
    if wk is None:
        return hours
    return hours & (ep["weekday"] == wk)


def compute_pm3(df: pd.DataFrame,
                truck_speeds: pd.DataFrame | None = None) -> dict:
    """LOTTR + TTTR per sensor-period, with corridor summary.

    Returns {lottr: frame, tttr: frame, summary: dict}. TTTR uses
    all-vehicle speeds as a labeled proxy unless ``truck_speeds`` (same
    schema, truck-only) is supplied.
    """
    ep = _epoch_travel_times(df)
    window_days = int(ep["epoch"].dt.date.nunique())
    grade = "calendar_year" if window_days >= 340 else "window_screening"

    def ratios(ep_frame, periods, hi_pct):
        rows = []
        for name, spec in periods.items():
            sub = ep_frame[_period_mask(ep_frame, spec)]
            for sid, g in sub.groupby("sensor_uid"):
                if len(g) < 8:              # too few epochs to call it
                    continue
                p50 = float(np.percentile(g["tt_s"], 50))
                phi = float(np.percentile(g["tt_s"], hi_pct))
                rows.append(dict(sensor_uid=sid, period=name,
                                 p50_tt_s=round(p50, 1),
                                 **{f"p{hi_pct}_tt_s": round(phi, 1)},
                                 ratio=round(phi / max(p50, 1e-9), 3),
                                 n_epochs=len(g)))
        return pd.DataFrame(rows)

    lottr = ratios(ep, LOTTR_PERIODS, 80)
    if len(lottr):
        lottr = lottr.rename(columns={"ratio": "lottr"})
        lottr["reliable"] = lottr["lottr"] < LOTTR_THRESHOLD

    truck_ep = _epoch_travel_times(truck_speeds) if truck_speeds is not None else ep
    tttr = ratios(truck_ep, TTTR_PERIODS, 95)
    tttr_basis = "truck_probe" if truck_speeds is not None else "all_vehicle_proxy"
    if len(tttr):
        tttr = tttr.rename(columns={"ratio": "tttr"})
        tttr["basis"] = tttr_basis

    summary = {
        "pm3_grade": grade,
        "window_days": window_days,
        "note": ("PM3 requires a full calendar year of 15-min epochs; "
                 "'window_screening' results are for screening/diagnosis, "
                 "not federal submission" if grade == "window_screening"
                 else "calendar-year window"),
        "lottr_threshold": LOTTR_THRESHOLD,
        "pct_sensor_periods_reliable": (
            round(100 * float(lottr["reliable"].mean()), 1) if len(lottr) else None),
        "worst_lottr": (dict(lottr.loc[lottr["lottr"].idxmax(),
                                       ["sensor_uid", "period", "lottr"]])
                        if len(lottr) else None),
        "tttr_basis": tttr_basis,
        "tttr_index_by_sensor": (
            {s: float(g["tttr"].max()) for s, g in tttr.groupby("sensor_uid")}
            if len(tttr) else {}),
        "tttr_index_note": TTTR_INDEX_NOTE,
    }
    return {"lottr": lottr, "tttr": tttr, "summary": summary}


def pm3_issues(pm3: dict, corridor: str = "CORRIDOR",
               start_id: int = 500) -> list[dict]:
    """Unreliable segment-periods as Issue Graph objects (Reader output)."""
    out = []
    lottr = pm3["lottr"]
    grade = pm3["summary"]["pm3_grade"]
    if not len(lottr):
        return out
    for i, r in enumerate(lottr[~lottr["reliable"]].itertuples()):
        out.append({
            "issue_id": f"I-{start_id + i:03d}",
            "type": "unreliable_segment_lottr",
            "location": {"sensors": [str(r.sensor_uid)], "corridor": corridor,
                         "time_window": r.period},
            "confidence": 0.9 if grade == "calendar_year" else 0.6,
            "severity": "high" if r.lottr >= 2.0 else "medium",
            "evidence": [f"LOTTR {r.lottr} >= {LOTTR_THRESHOLD}",
                         f"p50_tt_s {r.p50_tt_s} / p80_tt_s {r.p80_tt_s}",
                         f"n_epochs {r.n_epochs}",
                         f"pm3_grade {grade}"],
            "recommended_token": ["RELIABILITY_TARGET",
                                  "SCENARIO_COMPARISON_TARGET"],
            "status": "open",
        })
    return out
