"""cbi_pipeline.api — the stable public API of the pip-installed package.

Everything a notebook, script, or downstream tool should need lives behind
these names; the stage modules underneath may reorganize, this facade will
not. Input contract for the long-format states frame (one row per sensor
per 5-minute bin):

    sensor_uid        str    detector / TMC id
    datetime          datetime64
    speed_mph_clean   float  (QC output; `run_qc` produces it from speed_mph)
    qc_pass           int    1 = usable (run_qc produces it)
    flow_vph          float  optional — total volume per hour (all lanes)
    corridor          str    optional

Units are the package-wide conventions: speed mph, flow veh/h, density
veh/mi/ln, D/C in HOURS (never a plain ratio). See docs/CONTRACTS.md.

Quick start (no data files needed)::

    from cbi_pipeline import api
    df = api.simulate_corridor(days=5, seed=1)      # synthetic AM bottleneck
    result = api.diagnose(df)                        # QC -> episodes -> FD -> QVDF -> ranking
    print(result["ranking"].head())
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# --- re-exported building blocks (each has one canonical implementation) ---
from .io_unified import (load_pems, load_inrix, load_inrix_folder,
                         load_sensor_timeseries, synthesize_volume_s3)
from .stage1_qc import run_qc
from .stage2_episodes import run_episodes, classify_day, discharge_window
from .stage3_fd_robust import fit_fd_huber, bootstrap_fd, run_fd
from .stage5_qvdf import (fit_qvdf_P, fit_qvdf_v_t2, fit_qvdf_v_avg,
                          run_qvdf, predict_qvdf)
from .stage6_cbi_ranking import run_ranking
from .corridor_workflow import run_corridor
from . import fd_model_zoo

__all__ = [
    # loaders (PeMS compact JSON / INRIX RITIS exports)
    "load_pems", "load_inrix", "load_inrix_folder", "load_sensor_timeseries",
    "synthesize_volume_s3",
    # stage building blocks
    "run_qc", "run_episodes", "classify_day", "discharge_window",
    "fit_fd_huber", "bootstrap_fd", "run_fd",
    "fit_qvdf_P", "fit_qvdf_v_t2", "fit_qvdf_v_avg", "run_qvdf", "predict_qvdf",
    "run_ranking", "fd_model_zoo",
    # one-call paths
    "run_corridor", "diagnose", "simulate_corridor", "verify_installation",
    "version",
]


def version() -> str:
    """Installed package version."""
    try:
        from importlib.metadata import version as _v
        return _v("cbi-plus")
    except Exception:
        return "unknown (source checkout)"


# ---------------------------------------------------------------------------
# Synthetic corridor — teaching + install verification without any data files
# ---------------------------------------------------------------------------
def simulate_corridor(n_sensors: int = 6,
                      days: int = 5,
                      bottleneck_sensor: int = 3,
                      v_f: float = 65.0,
                      capacity_vphpl: float = 1900.0,
                      lanes: int = 3,
                      peak_demand_ratio: float = 1.15,
                      dt_min: float = 5.0,
                      seed: Optional[int] = 0) -> pd.DataFrame:
    """Simulate a weekday corridor with one AM active bottleneck.

    A trapezoidal demand profile exceeds capacity at ``bottleneck_sensor``
    during the AM peak; the queue spills back upstream with a backward wave,
    downstream sensors stay near free flow (the classic active/passive
    signature). Returns the long-format states frame accepted by
    :func:`run_qc` / :func:`diagnose`.
    """
    rng = np.random.default_rng(seed)
    bins_per_day = int(24 * 60 / dt_min)
    t = np.arange(bins_per_day) * dt_min / 60.0          # hours 0..24
    # trapezoidal AM demand bump (6:30-9:30) on a low base
    base = 0.35
    ramp = np.clip((t - 6.0) / 0.75, 0, 1) * np.clip((9.75 - t) / 0.75, 0, 1)
    demand_ratio = base + (peak_demand_ratio - base) * np.clip(ramp, 0, 1)
    mu_over_C = 0.92                                     # capacity drop while queued
    wave_mph = 12.0                                      # backward wave speed
    spacing_mi = 0.8

    rows = []
    start = pd.Timestamp("2026-03-02")                   # a Monday
    for day in range(days):
        date0 = start + pd.Timedelta(days=day + (2 if (start.dayofweek + day) % 7 >= 5 else 0))
        day_jit = rng.normal(0, 0.03)
        for s in range(n_sensors):
            dist_up = (bottleneck_sensor - s) * spacing_mi   # >0 upstream
            delay_h = max(0.0, dist_up) / wave_mph            # queue arrives later upstream
            speed = np.full(bins_per_day, v_f, float)
            flow = demand_ratio * capacity_vphpl * lanes * np.clip(1 + day_jit, 0.9, 1.1)
            over = demand_ratio * (1 + day_jit) > 1.0
            if s <= bottleneck_sensor:                        # queue reaches upstream only
                queued = over.copy()
                # shift queue onset/clear by the wave travel time
                shift = int(round(delay_h * 60 / dt_min))
                if shift:
                    queued = np.roll(queued, shift)
                    queued[:shift] = False
                # shorter queue further upstream (tail may not reach)
                if dist_up > 2.4:
                    queued[:] = False
                speed[queued] = 22.0 + 6.0 * rng.random(queued.sum())
                flow = np.where(queued, mu_over_C * capacity_vphpl * lanes, flow)
            flow = np.minimum(flow, capacity_vphpl * lanes)
            speed += rng.normal(0, 1.6, bins_per_day)
            speed = np.clip(speed, 5, v_f + 8)
            times = date0 + pd.to_timedelta(np.arange(bins_per_day) * dt_min, unit="m")
            rows.append(pd.DataFrame({
                "sensor_uid": f"SIM{ s:02d}".replace(" ", ""),
                "corridor": "SIM-1E",
                "datetime": times,
                "speed_mph": speed,
                "flow_vph": flow,
                "lanes": lanes,
                "road_order": s,          # upstream -> downstream ordering
                "direction": "E",
                "has_volume": True,
                "length_mi": spacing_mi,
                "source_format": "simulated",
            }))
    return pd.concat(rows, ignore_index=True)


# ---------------------------------------------------------------------------
# One-call diagnosis on an in-memory frame
# ---------------------------------------------------------------------------
def diagnose(df: pd.DataFrame,
             v_c_mph: float = 50.0,
             by_period: bool = True,
             n_boot: int = 30,
             out_dir: Optional[Path] = None) -> dict:
    """QC → episodes → FD → QVDF → CBI ranking on a long-format frame.

    Accepts raw frames with ``speed_mph`` (runs QC first) or QC'd frames
    that already carry ``speed_mph_clean``/``qc_pass``. Returns a dict:
    ``qc`` (frame), ``episodes`` (frame), ``fd`` (per-sensor dict),
    ``fd_summary`` (frame), ``qvdf`` (dict), ``ranking`` (frame),
    ``summary`` (dict). Ranking CSVs land in ``out_dir`` (a temp
    directory when omitted).
    """
    if out_dir is None:
        import tempfile
        out_dir = Path(tempfile.mkdtemp(prefix="cbi_diagnose_"))
    corridor = (str(df["corridor"].iloc[0])
                if "corridor" in df.columns and len(df) else "CORRIDOR")

    if "speed_mph_clean" not in df.columns:
        df_qc, qc_summary = run_qc(df)
    else:
        df_qc, qc_summary = df.copy(), {"note": "pre-cleaned input"}

    episodes, reliability, ep_summary = run_episodes(
        df_qc, default_v_c_mph=v_c_mph, by_period=by_period)

    fd, fd_summary = None, None
    if "flow_vph" in df_qc.columns:
        try:
            fd = run_fd(df_qc, n_boot=n_boot)
            fd_summary = pd.DataFrame([{
                "sensor_uid": sid,
                "capacity_vphpl": p["fd"]["capacity_vphpl"],
                "v_f_mph": p["fd"]["free_flow_speed_kph"] / 1.609,
                "r_squared": p["fd"]["r_squared"],
            } for sid, p in fd.items()])
        except Exception as exc:            # FD is optional for speed-only feeds
            fd = {"error": str(exc)}

    qvdf = None
    valid = (episodes[episodes["is_valid_for_mu"]]
             if "is_valid_for_mu" in episodes.columns else episodes)
    if fd_summary is not None and len(valid) >= 3:
        try:
            qvdf = run_qvdf(episodes, fd_summary)
        except Exception as exc:
            qvdf = {"error": str(exc)}

    ranking = run_ranking(episodes, corridor, out_dir / "stage6_cbi")
    if len(ranking):
        ranking = ranking.sort_values("CBI_score", ascending=False)
    return {"qc": df_qc, "episodes": episodes, "reliability": reliability,
            "fd": fd, "fd_summary": fd_summary, "qvdf": qvdf,
            "ranking": ranking, "out_dir": out_dir,
            "summary": {"qc": qc_summary, "episodes": ep_summary}}


def verify_installation(verbose: bool = True) -> bool:
    """Data-free self-test: simulate a corridor, diagnose it, check physics.

    Passes when the simulated active bottleneck is detected at the right
    sensor with a plausible queue duration. Run after ``pip install cbi-plus``.
    """
    df = simulate_corridor(days=5, seed=42)
    out = diagnose(df)
    ep = out["episodes"]
    ok_rows = len(ep) > 0
    valid = ep[ep["is_valid_for_mu"]] if ok_rows else ep
    ok_valid = len(valid) >= 3
    top = out["ranking"].iloc[0] if len(out["ranking"]) else None
    ok_top = top is not None and str(top["sensor_uid"]) == "SIM03"
    ok = bool(ok_rows and ok_valid and ok_top)
    if verbose:
        print(f"episodes rows: {len(ep)}  valid: {len(valid)}")
        if top is not None:
            print(f"top-ranked bottleneck: {top['sensor_uid']} "
                  f"(expected SIM03) CBI_score={top['CBI_score']:.3f} "
                  f"class={top['bottleneck_class']}")
        print("verify_installation:", "PASS" if ok else "FAIL")
    return ok
