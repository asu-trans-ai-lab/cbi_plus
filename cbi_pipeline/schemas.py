"""
schemas.py — JSON / CSV column contracts for the cbi_pipeline.

These are the only schema definitions the rest of the package may rely on.
If a downstream consumer (Parts 2-5) expects different keys, they go here
and nowhere else.
"""

from typing import Final


# Stage 0 — unified time-series row schema (every loader emits this)
TIMESERIES_COLUMNS: Final = [
    "sensor_uid",          # str — globally unique, prefixed by source
    "datetime",            # pd.Timestamp (5-min cadence after resampling)
    "speed_mph",           # float
    "flow_vph",            # float per-lane (NaN if neither measured nor synthesized)
    "density_vpm",         # float per-lane (NaN if neither measured nor synthesized)
    "has_volume",          # bool — TRUE only if flow_vph came from a measurement
    "flow_synthetic",      # bool — TRUE if flow_vph was synthesized via CBI inverse-S3
    "source_format",       # str — {"pems_json", "inrix_tmc"}
    "lanes",               # int (NaN if unknown)
    "length_mi",           # float
    "road_order",          # float — INRIX road_order or PeMS Abs_PM
    "direction",           # str — {"N","S","E","W","NORTHBOUND",...}
    "corridor",            # str — e.g. "I-17", "I-5-N"
]


# =============================================================================
# CBI inverse-S3 PRIORS — these are assumptions, NOT measurements.
# =============================================================================
# When flow is synthesized from speed via the S3 inverse (CBI-main/DTA.py:661),
# the result inherits whatever (vf, k_critical, s3_m, capacity) you assume.
# Pick the preset that matches your facility, OR pass a custom dict, OR let
# `io_unified.calibrate_s3_priors_from_data` adjust vf from the speed sample.
#
# The "cbi_default" preset is the urban-Phoenix calibration shipped with the
# original CBI codebase. It is *not* a universal truth — rural / interstate /
# congested-urban facilities all want different numbers.
#
# How to choose:
#   - vf_mph             ≈ 95th-percentile observed free-flow speed.
#                          Posted limit + 5 mph is a decent fallback.
#   - lane_capacity_vphpl  urban ~ 2200; rural ~ 1900; arterial ~ 1500.
#   - k_critical_vpm     = lane_capacity / v_critical  (v_critical ≈ 0.7 vf).
#   - s3_m               = 2 ln(2) / ln(vf / v_critical)   (≈ 4 when v_c=0.5 vf).
# -----------------------------------------------------------------------------
S3_PRIOR_PRESETS: Final = {
    # Phoenix urban freeway (CBI legacy default — DTA.py:489-517, VDF.py:19).
    "cbi_default": {
        "vf_mph": 70.0, "k_critical_vpm": 45.0,
        "s3_m": 4.0,    "lane_capacity_vphpl": 2200.0,
        "provenance": "CBI-main/src/python/DTA.py default - urban Phoenix",
    },
    # Generic urban interstate (e.g. CA SR-101, I-5 LA, I-405) — denser, lower vf.
    "urban_freeway": {
        "vf_mph": 65.0, "k_critical_vpm": 50.0,
        "s3_m": 4.0,    "lane_capacity_vphpl": 2200.0,
        "provenance": "Urban interstate prior (CA/IL HCM-2010 style)",
    },
    # Rural / inter-city freeway: posted ~75 mph, lighter density, lower per-lane cap.
    # I-17 Phoenix→Flagstaff fits here (the AZ INRIX sample in 01_input_data/I-17).
    "rural_freeway": {
        "vf_mph": 75.0, "k_critical_vpm": 32.0,
        "s3_m": 4.0,    "lane_capacity_vphpl": 1900.0,
        "provenance": "Rural interstate, 75 mph posted (e.g. AZ I-17 north of Phoenix)",
    },
    # AZ INRIX I-17 specifically (this is the sample at 01_input_data/I-17/I-17).
    # Identical to rural_freeway for now — refine after seeing actual capacity.
    "az_tmc_i17": {
        "vf_mph": 75.0, "k_critical_vpm": 32.0,
        "s3_m": 4.0,    "lane_capacity_vphpl": 1900.0,
        "provenance": "AZ INRIX I-17 (Phoenix-Flagstaff rural corridor)",
    },
    # CA PeMS LA basin freeways — same as urban_freeway for now.
    "ca_pems_freeway": {
        "vf_mph": 65.0, "k_critical_vpm": 50.0,
        "s3_m": 4.0,    "lane_capacity_vphpl": 2200.0,
        "provenance": "California PeMS urban (LA District 7)",
    },
    # Arterial / signalized — much lower free-flow and capacity.
    "arterial": {
        "vf_mph": 45.0, "k_critical_vpm": 35.0,
        "s3_m": 4.0,    "lane_capacity_vphpl": 1500.0,
        "provenance": "Signalized arterial",
    },
}

# Backward-compat alias used elsewhere in the package.
DEFAULT_S3_PARAMS: Final = {k: v for k, v in S3_PRIOR_PRESETS["cbi_default"].items()
                            if k != "provenance"}


def resolve_s3_prior(prior) -> dict:
    """
    Accept a preset name, a full param dict, or None. Always return a dict
    with the four numeric fields plus a 'provenance' string.
    """
    if prior is None:
        prior = "cbi_default"
    if isinstance(prior, str):
        if prior not in S3_PRIOR_PRESETS:
            raise ValueError(
                f"Unknown S3 prior preset: {prior!r}. "
                f"Choose from: {sorted(S3_PRIOR_PRESETS)} or pass a dict."
            )
        return dict(S3_PRIOR_PRESETS[prior])
    if isinstance(prior, dict):
        out = dict(S3_PRIOR_PRESETS["cbi_default"])
        out.update(prior)
        out.setdefault("provenance", "user-supplied dict")
        return out
    raise TypeError(f"s3_prior must be str | dict | None, got {type(prior).__name__}")

# Stage 1 — QC flags appended to every row
QC_FLAG_COLUMNS: Final = [
    "qc_hard_range",        # 1 = OK, 0 = flagged
    "qc_jump",
    "qc_hampel",
    "qc_spatial",
    "qc_direction",
    "qc_pass",              # AND of the above
    "speed_mph_clean",      # Hampel-cleaned speed (NaN where unrecoverable)
]

# Stage 2 — episode row schema (one row per link-day)
EPISODE_COLUMNS: Final = [
    "sensor_uid",
    "corridor",
    "date",
    "period",               # AM / MD / PM / NT, or "all_day"
    "regime",               # uncongested / mild / recurring / severe / event
    "t0_index", "t2_index", "t3_index",
    "P_min",                # congestion duration in minutes
    "min_speed_mph",
    "v_c_mph",              # speed at capacity from FD prior
    "demand_veh",
    "episode_id",           # f"{sensor_uid}__{date}__{period}"
    "dc_existence",         # bool: passes DC_existence_test
    "is_valid_for_mu",      # bool: P_min ≥ 30 AND min_speed < v_c AND dc_existence
    "discharge_start_idx",  # int or NaN
    "discharge_end_idx",    # int or NaN
]

# Stage 3 — drop-in superset FD JSON
def stage3_fd_json_skeleton(sensor_uid: str, source_format: str) -> dict:
    return {
        "sensor_uid": sensor_uid,
        "source_format": source_format,
        # Backward-compatible block (matches part1_fd_congestion_output.json)
        "fd": {
            "model": None,                # e.g. "S3"
            "free_flow_speed_kph": None,
            "speed_at_capacity_kph": None,
            "critical_density_vpk": None,
            "capacity_vphpl": None,
            "m_exponent": None,
            "r_squared": None,
        },
        # Additive — new robust block
        "fd_robust": {
            "huber_eps": 1.35,
            "n_bootstrap": 0,
            "regimes": {
                # filled by stage3:  {"free_flow": {...}, "near_capacity": {...}, "congested": {...}}
            },
            "bootstrap_band": {
                # filled by stage3:  {"capacity_vphpl": [p5, p50, p95], ...}
            },
            "best_model_overall": None,
            "best_model_per_regime": {},
        },
        "meta": {
            "qc_pass_rate": None,
            "n_obs": 0,
            "n_obs_qc_passed": 0,
            "has_volume": True,
        },
    }


# Stage 4 — mu output per link
MU_COLUMNS: Final = [
    "sensor_uid",
    "corridor",
    "n_episodes_total",
    "n_episodes_valid",            # passed is_valid_for_mu
    "mu_obs_median_vphpl",         # median over valid episodes' discharge windows
    "mu_obs_iqr_vphpl",
    "mu_shrunk_vphpl",             # James-Stein-style group shrinkage
    "mu_group_median_vphpl",       # corridor median over reliable links
    "reliability_class",           # high / medium / low / not_reliable
    "mu_source",                   # self / shrunk / group_only
    "alpha_shrinkage",             # 0..1
]


# Reliability thresholds (spec)
RELIABILITY_THRESHOLDS: Final = {
    "high":          20,  # ≥ 20 valid congested days
    "medium":        10,  # 10–19
    "low":            5,  # 5–9
    "not_reliable":   0,  # < 5
}

# Day-classification thresholds (spec)
TAXONOMY_THRESHOLDS: Final = {
    "uncongested_max_P_min": 30.0,
    "mild_max_P_min": 60.0,
    "recurring_min_P_min": 60.0,
    "severe_min_P_min": 120.0,
    "severe_min_speed_ratio": 0.5,   # min_v < 0.5 * v_c
    "mild_speed_ratio_lo": 0.7,      # min_v ∈ [0.7 v_c, v_c)
    "event_z_threshold": 2.5,
}


# Discharge-window guards
DISCHARGE_WINDOW_MIN_INTERVALS: Final = 6   # ≥ 6 valid 5-min intervals = 30 min


# =============================================================================
# Period definitions (time-of-day windows for QVDF fitting).
# Mirrors the FIXED figure folder naming: 0600_1000 / 1000_1600 / 1600_2000.
# =============================================================================
PERIOD_DEFINITIONS: Final = {
    "AM": (6,  10),   # 06:00 - 10:00
    "MD": (10, 16),   # 10:00 - 16:00
    "PM": (16, 20),   # 16:00 - 20:00
    "NT": (20, 6),    # 20:00 - 06:00 (overnight) — usually skipped
}

# Hour bounds for INDEX SLICING (superset of the labeling table above).
# "MDPM" is the stitched label produced by the stage-2 boundary-merge pass when a
# queue crosses the 16:00 MD->PM edge (on chronic corridors this is the NORM: on
# I-210E June 2026, 84% of valid MD episodes ended pinned at the boundary and 95%
# of PM episodes started congested). Labeling (_period_for_timestamp) still uses
# PERIOD_DEFINITIONS only — MDPM exists solely as an episode label + slice range.
PERIOD_SLICE_BOUNDS: Final = {**PERIOD_DEFINITIONS, "MDPM": (10, 20)}


def period_hour_mask(hours, period: str):
    """Boolean mask: which hour-of-day values fall inside `period`'s slice range.

    `hours` is any numpy/pandas array of integer hours. Handles the overnight
    wrap (NT). Use this — not label equality — wherever period-relative episode
    indices are applied to a timestamped frame, so merged labels (MDPM) slice
    correctly too."""
    h0, h1 = PERIOD_SLICE_BOUNDS[period]
    if h0 <= h1:
        return (hours >= h0) & (hours < h1)
    return (hours >= h0) | (hours < h1)


def period_label_for_filename(period: str) -> str:
    """Map AM/MD/PM/NT to the FIXED-figure folder convention."""
    if period not in PERIOD_DEFINITIONS:
        return period
    h0, h1 = PERIOD_DEFINITIONS[period]
    return f"{h0:02d}00_{h1:02d}00"


# =============================================================================
# Day-filter selectors (matches student's existing variation-1/2 logic).
# =============================================================================
DAY_FILTERS: Final = {
    "weekday":    "All Monday-Friday days that pass QC.",
    "difficult":  "Worst-decile by congestion duration P within each (sensor, period).",
}


# =============================================================================
# Outlier mitigation thresholds (applied at QVDF fitting).
# =============================================================================
OUTLIER_THRESHOLDS: Final = {
    "iqr_factor":         3.0,    # drop points outside [Q1 - 3 IQR, Q3 + 3 IQR]
    "min_points_for_fit": 5,      # require ≥ 5 valid days per (sensor, period)
    "min_doc_for_qvdf":   0.50,   # ignore extreme low-demand days (D/C < 0.5)
    "max_doc_for_qvdf":   3.0,    # cap absurd D/C
    "min_P_min_for_qvdf": 30.0,   # only fit on actually-congested days
}


# =============================================================================
# Quality gates (per corridor × period — "reliability check" gates).
# =============================================================================
QUALITY_GATES: Final = {
    "min_qc_pass_rate":            0.85,   # Stage 1
    "min_direction_confidence":    0.50,   # Stage 1
    "min_valid_episodes_per_sensor": 5,    # Stage 2 (low reliability threshold)
    "min_fd_r2":                   0.70,   # Stage 3 (PeMS only)
    "min_mu_R2_gap_valid_vs_all":  0.10,   # Stage 4 — structural-bias finding
    "min_qvdf_n_points":           5,      # Stage 5
}
