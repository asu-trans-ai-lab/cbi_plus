# -*- coding: utf-8 -*-
"""stage6_cbi_ranking — the CBI deliverable: bottleneck score & ranking.

The pipeline's earlier stages produce queue objects; a CBI (Congestion
Bottleneck Identification) TOOL must end with a ranked answer to "which
bottlenecks should the agency fix first?". This stage turns the audited
episodes into exactly that, with explicit aggregation levels (per the review:
every number labels whether it is per-episode, per sensor-period, or corridor).

Score (per sensor x period, then corridor rank):

    CBI_score = frequency x duration x severity
              = (n_valid_episodes / n_active_days)
                x median(P_hours)
                x median(1 - v_t2 / v_c)

  - frequency  : how often this location breaks down (episodes per active day)
  - duration   : how long a breakdown lasts (median P, hours)
  - severity   : how deep speed falls (1 - v_t2/v_c, 0 = touches v_c, ->1 = stopped)

  The product is a delay-like intensity in "severity-weighted queue-hours per
  day" — monotone in each physical dimension and unit-transparent, so ranks are
  explainable to an agency. (delay_proxy_veh_h adds mu-weighting when volume
  exists: score x mu x lanes... kept separate, not in the rank, to stay
  comparable between measured-volume and synthesized-volume corridors.)

Bottleneck class (per episode, majority-voted to the sensor-period):
  active_bottleneck : downstream neighbor NOT congested during this episode
                      (this sensor is the queue head — discharge is here)
  queued_passive    : downstream neighbor congested at overlapping times
                      (this sensor sits INSIDE another queue — do not "fix" it)
  spillback_source  : active AND upstream neighbor congested (its queue reaches
                      the neighbor — highest-priority class)
  isolated_uncertain: no neighbor information (corridor edge / sparse)
  incident_related  : stage-2 flagged this episode's day as an EVENT (per-
                      (sensor, period) z-score outlier) — the day is anomalous,
                      so the topology class is overridden: dispatch-type
                      response, not infrastructure fix (CONTRACTS.md section 4)

Outputs (per corridor run dir):
  stage6_cbi/benchmark_bottleneck_ranking.csv     one row per (sensor, period), ranked
  stage6_cbi/benchmark_CBI_corridor_summary.csv   one row per (corridor, period)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .schemas import PERIOD_SLICE_BOUNDS


# --------------------------------------------------------------------------- classes
def _classify_episodes(eps: pd.DataFrame, order: dict) -> pd.Series:
    """Per-episode bottleneck class from neighbor time-overlap (see module doc).

    order: sensor_uid -> corridor position (0 = most upstream)."""
    eps = eps.assign(pos_=eps["sensor_uid"].map(order))
    by_pos_date = {}
    for (pos, date), g in eps.groupby(["pos_", "date"]):
        by_pos_date[(pos, date)] = list(zip(g["t0_abs"], g["t3_abs"]))

    def overlaps(pos, date, t0, t3):
        for (a, b) in by_pos_date.get((pos, date), []):
            if not (t3 < a or b < t0):
                return True
        return False

    positions_with_data = {p for p, _ in by_pos_date}
    out = []
    for r in eps.itertuples():
        down, up = r.pos_ + 1, r.pos_ - 1
        if down not in positions_with_data and up not in positions_with_data:
            out.append("isolated_uncertain")
            continue
        if overlaps(down, r.date, r.t0_abs, r.t3_abs):
            out.append("queued_passive")        # inside someone else's queue
        elif overlaps(up, r.date, r.t0_abs, r.t3_abs):
            out.append("spillback_source")      # queue head reaching upstream
        else:
            out.append("active_bottleneck")     # queue head, contained
    return pd.Series(out, index=eps.index)


# --------------------------------------------------------------------------- main
def run_ranking(episodes_df: pd.DataFrame,
                corridor: str,
                out_dir: Path | None = None,
                road_order: dict | None = None,
                verbose: bool = True) -> pd.DataFrame:
    """Build the CBI score/ranking tables from stage-2 episodes (valid only).

    out_dir=None runs purely in memory (no CSVs written)."""
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

    eps = episodes_df[episodes_df["is_valid_for_mu"]].copy()
    if eps.empty:
        print("   [stage6] no valid episodes — ranking skipped")
        return pd.DataFrame()

    # absolute minutes for overlap tests (period-relative idx -> minutes-of-day)
    p0 = eps["period"].map(lambda p: PERIOD_SLICE_BOUNDS.get(p, (0, 24))[0] * 60)
    eps["t0_abs"] = p0 + eps["t0_index"] * 5
    eps["t3_abs"] = p0 + eps["t3_index"] * 5

    if road_order is None:
        road_order = {s: i for i, s in enumerate(sorted(eps["sensor_uid"].unique()))}
    else:
        # sensors absent from the info table get appended positionally — a partial
        # map must never crash the ranking (found on the I-10 2018 benchmark)
        missing = sorted(set(eps["sensor_uid"].unique()) - set(road_order))
        nxt = (max(road_order.values()) + 1) if road_order else 0
        road_order = {**road_order, **{s: nxt + i for i, s in enumerate(missing)}}
    eps["bottleneck_class"] = _classify_episodes(eps, road_order)
    # Fuse the stage-2 EVENT regime (per-(sensor, period) z-score outlier day)
    # into the diagnosis: an anomalous day is incident_related regardless of
    # its queue topology — a dispatch problem, not an infrastructure ranking
    # signal. Recurring/severe/mild regimes keep their topology class.
    if "regime" in eps.columns:
        eps.loc[eps["regime"] == "event", "bottleneck_class"] = "incident_related"

    n_days = eps["date"].nunique()
    rows = []
    for (sid, period), g in eps.groupby(["sensor_uid", "period"]):
        v_c = float(g["v_c_mph"].median())
        sev = float((1 - g["min_speed_mph"] / v_c).clip(lower=0).median())
        freq = len(g) / max(n_days, 1)
        dur_h = float(g["P_min"].median()) / 60.0
        cls = g["bottleneck_class"].mode().iloc[0]
        rows.append({
            "corridor": corridor, "sensor_uid": sid, "period": period,
            "road_order": road_order.get(sid),
            "n_valid_episodes": len(g), "n_days_window": n_days,
            "freq_episodes_per_day": round(freq, 3),
            "median_P_hours": round(dur_h, 2),
            "median_v_t2_mph": round(float(g["min_speed_mph"].median()), 1),
            "severity_1_minus_vt2_over_vc": round(sev, 3),
            "CBI_score": round(freq * dur_h * sev, 4),
            "bottleneck_class": cls,
            "aggregation_level": "sensor_period_median_over_valid_episodes",
        })
    rank = pd.DataFrame(rows).sort_values("CBI_score", ascending=False).reset_index(drop=True)
    rank["rank_in_corridor"] = np.arange(1, len(rank) + 1)
    if out_dir is not None:
        rank.to_csv(out_dir / "benchmark_bottleneck_ranking.csv", index=False)

    summ = (rank.groupby(["corridor", "period"])
                .agg(n_ranked_sensor_periods=("CBI_score", "size"),
                     total_CBI_score=("CBI_score", "sum"),
                     top_sensor=("sensor_uid", "first"),
                     top_score=("CBI_score", "first"),
                     n_active=("bottleneck_class",
                               lambda s: int((s == "active_bottleneck").sum())),
                     n_spillback=("bottleneck_class",
                                  lambda s: int((s == "spillback_source").sum())),
                     n_passive=("bottleneck_class",
                                lambda s: int((s == "queued_passive").sum())),
                     n_incident=("bottleneck_class",
                                 lambda s: int((s == "incident_related").sum())))
                .reset_index())
    summ["aggregation_level"] = "corridor_period_sum_over_sensor_periods"
    if out_dir is not None:
        summ.to_csv(out_dir / "benchmark_CBI_corridor_summary.csv", index=False)

    if verbose:
        top = rank.head(5)[["rank_in_corridor", "sensor_uid", "period",
                            "CBI_score", "bottleneck_class"]]
        print(f"   [stage6] CBI ranking: {len(rank)} sensor-periods; top-5:")
        for r in top.itertuples(index=False):
            print(f"      #{r.rank_in_corridor:<2} {r.sensor_uid:<22} {r.period:<5} "
                  f"score={r.CBI_score:<8} {r.bottleneck_class}")
    return rank
