# -*- coding:utf-8 -*-
"""QVDF turn-key pipeline — configuration (corridors, periods, model constants)."""
import os

# Package-relative / env-driven paths (no hardcoded absolute paths — this ships in cbi-plus).
# ROOT only matters for the optional raw-data corridors (not run in the self-demo). OUT_ROOT is where
# self-demo outputs are written; defaults to ./cbi_selfdemo_outputs under the current directory.
ROOT = os.environ.get("CBI_DATA_ROOT", os.path.dirname(os.path.abspath(__file__)))
OUT_ROOT = os.environ.get("CBI_SELFDEMO_OUT", os.path.join(os.getcwd(), "cbi_selfdemo_outputs"))
os.makedirs(OUT_ROOT, exist_ok=True)

# ---- model constants (from the QVDF paper) --------------------------------
DT_MIN = 15                 # analysis time interval (minutes)
CUTOFF_RATIO = 0.70         # congestion cut-off speed = 0.70 * free-flow speed
OUTER_Q = 0.90              # S3 outer-layer (oversaturated envelope) quantile
VT2_SMOOTH = 3              # centered intervals for speed smoothing (~45 min) before t0/t2/t3 detection
HYST_MIN = 30              # sustained-crossing hysteresis: speed must stay across the cut-off for
                           # this many minutes (+-30 min) to confirm a clean t0 / t3 intersection
# QVDF is calibrated on WEEKDAY-AVERAGE profiles (one smooth profile per day-of-week), NOT
# day-by-day, so the unit of analysis is the day-of-week (<=7 points per link x period).
USE_WEEKDAY_AVG = True
MIN_CONG_DAYS = 3           # min congested day-of-week profiles to attempt a calibration
HIGH_REL_DAYS = 5           # >= this many congested day-of-week profiles -> "high" reliability
SHRINK_K0 = 2.0             # James-Stein style shrinkage strength toward corridor median
DOC_MIN, DOC_MAX = 0.1, 6.0 # feasible D/C range
PARAM_BOUNDS = (0.0, 10.0)  # curve_fit bounds for f_d, n, f_p, s
# transferred default used when a corridor/period has congestion but cannot self-calibrate
# (e.g. a uniformly-gridlocked corridor with no D/C-P variation). Flagged reliability="default".
DEFAULT_QVDF = dict(f_d=1.30, n=1.00, f_p=0.20, s=1.30)
VT2_TOL_MPH = 10.0          # a link is "QVDF-modelable" if |model V_t2 - observed| <= this AND D/C
                            # not censored; else it is an all-day-saturated link the single-peak QVDF
                            # cannot fit -> flagged, not drawn with a misleading deep model trough.

# ---- assignment periods (minutes since midnight). NT skipped (uncongested). -
# An episode is ASSIGNED to a period by where its trough t2 falls (so the congestion window
# itself is never clipped by a period boundary).
PERIODS = {
    "AM": (5 * 60, 10 * 60),
    "MD": (10 * 60, 14 * 60),
    "PM": (14 * 60, 20 * 60),
}
# wide search window for episode detection (t0/t3 may extend past a period boundary)
WIDE_WINDOW = (5 * 60, 22 * 60)
MIN_EPISODE_H = 0.5         # discard congestion episodes shorter than this (noise)

WEEKDAY_NAME = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
                4: "Friday", 5: "Saturday", 6: "Sunday"}

# ---- corridor registry ----------------------------------------------------
# source: "i10_csv" | "pems_json" | "inrix_folder"
# free_flow: posted free-flow speed (mph); FD fit holds v_f at this value.
# capacity_prior: per-lane capacity used as the FD fallback when an S3 fit is rejected.
# wd_mode:
#   "per_dow"      -> one profile per day-of-week; QVDF calibrated PER LINK across the 7 dow
#                     (PeMS full-year sets, the paper convention; each link gets its own f_d/n/f_p/s).
#   "avg_weekday"  -> ONE average-weekday profile per link (Mon-Fri averaged, no day-by-day);
#                     QVDF calibrated at the CORRIDOR level across links (spatial D/C range).
CORRIDORS = {
    "I10": dict(name="I-10 (AZ, paper case 1)", source="i10_csv",
                path=r"C:/source_codes/QVDF-E/QVDF-main/QVDF-main/Python_code/Python_data_preparation_and_QVDF_calibration/corridor_measurement_I10.csv",
                free_flow=70.0, capacity_prior=1800.0, wd_mode="per_dow"),
    "I405": dict(name="I-405 (CA PeMS, paper case 2)", source="pems_json",
                 path=os.path.join(ROOT, "AI4TMFfit_v2", "input_data", "I-405"),
                 free_flow=65.0, capacity_prior=2000.0, wd_mode="per_dow"),
    "I17": dict(name="I-17 (AZ INRIX)", source="inrix_folder",
                path=os.path.join(ROOT, "AI4TMFfit_v2", "input_data", "I-17"),
                free_flow=65.0, capacity_prior=2000.0, wd_mode="avg_weekday"),
    "NVTA_NB": dict(name="I-395 NB (NoVA INRIX)", source="inrix_folder",
                    path=os.path.join(ROOT, "I395_qvdfe_input", "I-395_NB"),
                    free_flow=70.0, capacity_prior=2200.0, wd_mode="avg_weekday"),
    "NVTA_SB": dict(name="I-395 SB (NoVA INRIX)", source="inrix_folder",
                    path=os.path.join(ROOT, "I395_qvdfe_input", "I-395_SB"),
                    free_flow=70.0, capacity_prior=2200.0, wd_mode="avg_weekday"),
}

# ---- other NVTA freeway corridors (INRIX, NOVA RITIS) — the slides-50-60 priorities ----
_NVTA_FWY = os.path.join(ROOT, "nvta_freeway_input")
for _k, _dir in [("I66_EB", "I-66_EB"), ("I66_WB", "I-66_WB"),
                 ("I495_CW", "I-495_CW"), ("I495_CCW", "I-495_CCW")]:
    CORRIDORS[f"NVTA_{_k}"] = dict(name=f"{_k.replace('_',' ')} (NoVA INRIX)", source="inrix_folder",
                                   path=os.path.join(_NVTA_FWY, _dir),
                                   free_flow=70.0, capacity_prior=2200.0, wd_mode="avg_weekday")
for _k, _dir in [("I95_NB", "I-95_NB"), ("I95_SB", "I-95_SB")]:
    CORRIDORS[f"NVTA_{_k}"] = dict(name=f"I-95 {_k.split('_')[1]} (NoVA INRIX)", source="inrix_folder",
                                   path=os.path.join(ROOT, "I95_qvdfe_input", _dir),
                                   free_flow=70.0, capacity_prior=2200.0, wd_mode="avg_weekday")
# HOV / express-lane corridors (managed lanes analyzed on their own reduced network)
for _k, _dir, _nm in [("I395HOV_NB", "I-395HOV_NB", "I-395 HOV NB"), ("I395HOV_SB", "I-395HOV_SB", "I-395 HOV SB"),
                      ("I95HOV_NB", "I-95HOV_NB", "I-95 HOV NB"), ("I95HOV_SB", "I-95HOV_SB", "I-95 HOV SB")]:
    CORRIDORS[f"NVTA_{_k}"] = dict(name=f"{_nm} (NoVA INRIX)", source="inrix_folder",
                                   path=os.path.join(_NVTA_FWY, _dir),
                                   free_flow=65.0, capacity_prior=1800.0, wd_mode="avg_weekday")

# NOTE: arterials (US-1, VA-7, US-29, US-50, ...) are intentionally OUT OF SCOPE -- they are
# signal-controlled and the QVDF is a freeway (uninterrupted-flow) model; without signal-timing data
# their congestion is all-day saturation, not a peak queue. Freeways + HOV/express only.

# ---- California PeMS LA corridors (QVDF-E) — auto-registered ----------------
_PEMS_LA = r"C:/source_codes/QVDF-E/clean_handoff_v1/02_calibration_scripts/out_cbi_benchmarks/work"
for _c in ["I10E", "I10W", "I110N", "I110S", "I210E", "I210W", "I405N", "I405S", "I5N", "I5S"]:
    CORRIDORS[f"CA_{_c}"] = dict(
        name=f"CA PeMS LA {_c}", source="pems_json",
        path=os.path.join(_PEMS_LA, f"PeMS_LA_{_c}"),
        free_flow=65.0, capacity_prior=2000.0, wd_mode="avg_weekday")
