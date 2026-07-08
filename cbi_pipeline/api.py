"""cbi_pipeline.api — the stable public API of the pip-installed package.

Everything a notebook, script, or downstream tool should need lives behind
these names; the stage modules underneath may reorganize, this facade will
not. Input contract for the long-format states frame (one row per sensor
per 5-minute bin):

    sensor_uid        str    detector / TMC id
    datetime          datetime64
    speed_mph_clean   float  (QC output; `run_qc` produces it from speed_mph)
    qc_pass           int    1 = usable (run_qc produces it)
    flow_vph          float  optional — veh/h PER LANE (never totals)
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
from .cbi_tokens import (compile_tokens, compare_tokens, benefit_tokens,
                         write_tokens)
from .issue_graph import (build_issue_graph, mismatch_issues,
                          write_issue_graph, planner_review, approved_issues)
from .pm3_reliability import compute_pm3, pm3_issues
from .corridor_workflow import run_corridor
from . import fd_model_zoo

__all__ = [
    # loaders (PeMS compact JSON / INRIX RITIS exports / IEEE v4 states)
    "load_pems", "load_inrix", "load_inrix_folder", "load_sensor_timeseries",
    "load_ieee_v4", "load_dataset", "read_dataset_meta", "synthesize_volume_s3",
    # stage building blocks
    "run_qc", "run_episodes", "classify_day", "discharge_window",
    "fit_fd_huber", "bootstrap_fd", "run_fd",
    "fit_qvdf_P", "fit_qvdf_v_t2", "fit_qvdf_v_avg", "run_qvdf", "predict_qvdf",
    "run_ranking", "fd_model_zoo", "fd_models",
    # planner-facing token compiler (CBI state machine)
    "compile_tokens", "compare_tokens", "benefit_tokens", "write_tokens",
    # Reader/Planner/Writer architecture: CBI is the READER — it emits an
    # Issue Graph and never edits a network; Writers act on approved issues
    "build_issue_graph", "mismatch_issues", "write_issue_graph",
    "planner_review", "approved_issues",
    # federal PM3 reliability layer (POL-1): LOTTR + TTTR
    "compute_pm3", "pm3_issues",
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
    dt_h = dt_min / 60.0
    t = np.arange(bins_per_day) * dt_h                   # hours 0..24
    # trapezoidal AM demand bump (6:00-9:45) on a low base
    base = 0.35
    ramp = np.clip((t - 6.0) / 0.75, 0, 1) * np.clip((9.75 - t) / 0.75, 0, 1)
    demand_shape = base + (peak_demand_ratio - base) * np.clip(ramp, 0, 1)
    mu_over_C = 0.92                                     # capacity drop while queued
    spacing_mi = 0.8
    k_storage = 60.0                                     # extra queued vehicles stored per mi per lane
    v_queue_worst = 18.0                                 # speed at the deepest point of the queue

    rows = []
    start = pd.Timestamp("2026-03-02")                   # a Monday
    for day in range(days):
        date0 = start + pd.Timedelta(days=day + (2 if (start.dayofweek + day) % 7 >= 5 else 0))
        day_jit = float(np.clip(1 + rng.normal(0, 0.03), 0.94, 1.06))
        demand = demand_shape * day_jit                  # in units of C (per lane)

        # --- bottleneck queue balance: arrivals vs (C before breakdown, mu after)
        # flow reaches ~C at breakdown, DROPS to mu while the queue drains,
        # and recovers when the deficit is repaid (Newell cumulative curves).
        q_veh = np.zeros(bins_per_day)                   # queued veh per lane
        served = np.zeros(bins_per_day)                  # bottleneck outflow, units of C
        q = 0.0
        for i in range(bins_per_day):
            cap = mu_over_C if q > 1e-9 else 1.0
            out = min(demand[i] + q / (capacity_vphpl * dt_h), cap)
            q = max(0.0, q + (demand[i] - out) * capacity_vphpl * dt_h)
            served[i] = out
            q_veh[i] = q
        q_max = q_veh.max()
        # physical queue tail position (miles upstream of the bottleneck)
        q_len_mi = q_veh / (k_storage)                   # per-lane storage density

        times = date0 + pd.to_timedelta(np.arange(bins_per_day) * dt_min, unit="m")
        for s in range(n_sensors):
            dist_up = (bottleneck_sensor - s) * spacing_mi   # >0 upstream
            if s > bottleneck_sensor:
                # DOWNSTREAM: conservation — you receive what the bottleneck
                # serves (metered to mu during the queue), at free-flow speed
                speed = np.full(bins_per_day, v_f, float)
                flow_pl = served.copy()
            elif s == bottleneck_sensor:
                queued = q_veh > 1e-9
                speed = np.where(queued,
                                 v_queue_worst + (v_f - v_queue_worst) * 0.55
                                 * (1 - q_veh / max(q_max, 1e-9)),
                                 v_f)
                flow_pl = served.copy()
            else:
                # UPSTREAM: inside the queue only while the tail reaches you;
                # onset later, clearance earlier than at the bottleneck (the
                # tail grows then recedes), with a natural taper — no cutoff
                queued = q_len_mi >= dist_up
                # the tail of a queue moves faster than its head: floor rises
                # with distance upstream of the bottleneck
                v_floor = v_queue_worst + 6.0 + 1.5 * dist_up
                speed = np.where(queued,
                                 v_floor + (v_f - v_floor) * 0.45
                                 * (1 - q_veh / max(q_max, 1e-9)),
                                 v_f)
                # within the queue vehicles advance at the discharge rate;
                # otherwise you carry the (unmetered) demand
                flow_pl = np.where(queued, mu_over_C, np.minimum(demand, 1.0))
            # package-wide contract: flow_vph is PER LANE (veh/h/ln)
            flow = flow_pl * capacity_vphpl
            speed = np.clip(speed + rng.normal(0, 1.5, bins_per_day), 5, v_f + 8)
            rows.append(pd.DataFrame({
                "sensor_uid": f"SIM{s:02d}",
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
# IEEE TrafficFlowBench v4 convenience loader
# ---------------------------------------------------------------------------
def load_ieee_v4(states_csv, chain_csv=None, corridor: str = "IEEE_V4",
                 lanes: int = 4, length_mi: float = 0.5) -> pd.DataFrame:
    """Load an IEEE v4 competition detector-states CSV into the package
    contract, handling the traps every participant hits:

    - v4 speeds are **km/h** → converted to mph here
    - v4 flow is **total across lanes** → converted to per-lane here
    - ``is_observed == 0`` cells are imputation → dropped (a prior must
      never calibrate a model)
    - southbound/westbound corridors: milepost DEcreases downstream, so
      pass ``chain_csv`` (the corridor's ``detector_chain_fd.csv``) —
      its row order defines upstream→downstream ordering; without it,
      milepost-ascending order is used (fine for N/E corridors).
    - lane counts: **derived from the data** (per-station p99 total flow
      / 1900), because map/chain lane tags are unreliable (this repo's
      hardest-learned lesson: a "2-lane" tag on a 12,000 veh/h station);
      ``lanes`` is only the fallback for stations with no flow.

    Works on the in-repo samples
    (``benchmarks/ieee_v4_samples/*/train_detector_states_3days[.csv|.csv.gz]``)
    and the full release files with the same columns.
    """
    import warnings
    raw = pd.read_csv(states_csv)
    required = {"station_id", "timestamp", "speed", "flow", "milepost", "is_observed"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"not a v4 detector-states file — missing columns: {sorted(missing)}")
    n_before = len(raw)
    raw = raw[raw["is_observed"] == 1]
    if not len(raw):
        raise ValueError(
            f"every one of the {n_before} rows has is_observed == 0 (all "
            "imputed) — there is nothing measured to calibrate on in this file.")

    def _norm_id(s: pd.Series) -> pd.Series:
        # ids must survive float-parsing (NaN in the column turns '101'
        # into '101.0') and vendor prefixes — normalize both sides
        out = s.astype(str).str.strip()
        return out.str.replace(r"\.0$", "", regex=True)
    raw = raw[raw["station_id"].notna()]

    sid = _norm_id(raw["station_id"])
    if chain_csv is not None:
        chain = pd.read_csv(chain_csv)
        sid_col = ("station_id" if "station_id" in chain.columns
                   else chain.columns[0])
        order = {s: i for i, s in enumerate(_norm_id(chain[sid_col]))}
    else:
        ranks = (pd.DataFrame({"sid": sid, "milepost": raw["milepost"]})
                 .drop_duplicates("sid").sort_values("milepost"))
        order = {s: i for i, s in enumerate(ranks["sid"])}

    unmatched = sorted(set(sid.unique()) - set(order))
    if unmatched:
        if len(unmatched) == sid.nunique():
            raise ValueError(
                "no station id matched the ordering source — chain and "
                f"states ids look incompatible (states e.g. {unmatched[:3]}, "
                f"ordering keys e.g. {list(order)[:3]})")
        warnings.warn(
            f"{len(unmatched)} station id(s) missing from the ordering "
            f"source get road_order=-1 (topology degraded): {unmatched[:5]}",
            UserWarning, stacklevel=2)
    # effective lanes from the data itself (p99 flow / 1900 veh/h/ln)
    p99 = raw.groupby(sid)["flow"].transform(lambda s: s.quantile(0.99))
    ln = (p99 / 1900.0).round().clip(1, 8).fillna(lanes)
    direction = (str(raw["direction"].iloc[0]) if "direction" in raw.columns
                 and len(raw) else "?")
    df = pd.DataFrame({
        "sensor_uid": sid,
        "corridor": corridor,
        "datetime": pd.to_datetime(raw["timestamp"]).dt.tz_localize(None),
        "speed_mph": pd.to_numeric(raw["speed"], errors="coerce") / 1.609,
        "flow_vph": pd.to_numeric(raw["flow"], errors="coerce") / ln,  # per lane
        "road_order": sid.map(order).fillna(-1).astype(int),
        "direction": direction, "has_volume": True, "length_mi": length_mi,
        "source_format": "ieee_v4",
        "lanes": ln if not np.isscalar(ln) else float(ln),
    }).dropna(subset=["speed_mph"])
    return df.reset_index(drop=True)


def fd_models() -> list:
    """Names accepted by :func:`fit_fd_huber` (case-insensitive)."""
    from .stage3_fd_robust import MODELS
    return sorted(MODELS)


# ---------------------------------------------------------------------------
# dataset_meta.json — the standard units/semantics sidecar
# ---------------------------------------------------------------------------
def read_dataset_meta(folder) -> dict:
    """Read and sanity-check a dataset's ``dataset_meta.json`` sidecar.

    The sidecar declares units and semantics machine-readably (speed mph vs
    km/h, flow per-lane vs total, imputation flags, ordering conventions) so
    loaders convert from DECLARED facts. Schema:
    ``schemas/dataset_meta.schema.json``. Born from the km/h-as-mph and
    per-lane-vs-total incidents (ISSUE_REGISTER SIM-M1 / SIM-T1).
    """
    import json
    folder = Path(folder)
    p = folder / "dataset_meta.json" if folder.is_dir() else folder
    if not p.exists():
        raise FileNotFoundError(
            f"no dataset_meta.json in {folder} — every dataset needs the "
            "units sidecar (see schemas/dataset_meta.schema.json)")
    meta = json.loads(p.read_text(encoding="utf8"))
    for req in ("meta_version", "name", "units", "loader", "files"):
        if req not in meta:
            raise ValueError(f"dataset_meta.json missing required key {req!r} ({p})")
    if "flow_scope" not in meta["units"]:
        raise ValueError(f"dataset_meta.json units must declare flow_scope ({p})")
    meta["_folder"] = str(p.parent)
    return meta


def load_dataset(folder, **kwargs) -> pd.DataFrame:
    """Load a dataset by its ``dataset_meta.json`` — units applied from the
    declaration, never from tribal knowledge.

    Dispatches on ``meta["loader"]``: ``ieee_v4`` | ``pems_compact_json`` |
    ``inrix_folder`` | ``contract_csv`` (already in the package contract).
    ``custom_script`` datasets (paper workbooks, engine inputs) raise with a
    pointer to their reproduce script.
    """
    meta = read_dataset_meta(folder)
    root = Path(meta["_folder"])
    loader = meta["loader"]
    files = meta.get("files", {})
    if loader == "ieee_v4":
        chain = files.get("chain")
        return load_ieee_v4(root / files["states"],
                            chain_csv=(root / chain) if chain else None,
                            corridor=meta["name"], **kwargs)
    if loader == "pems_compact_json":
        return load_pems(path=root / files["states"], **kwargs)
    if loader == "inrix_folder":
        return load_inrix_folder(root, **kwargs)
    if loader == "contract_csv":
        df = pd.read_csv(root / files["states"], **kwargs)
        if meta["units"].get("speed") == "kmh":
            for c in ("speed_mph", "speed"):
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce") / 1.609
        return df
    raise ValueError(
        f"dataset '{meta['name']}' uses loader='{loader}' — load it via its "
        f"reproduce script (see {files.get('notes', 'the benchmark folder')})")


# ---------------------------------------------------------------------------
# One-call diagnosis on an in-memory frame
# ---------------------------------------------------------------------------
def diagnose(df: pd.DataFrame,
             v_c_mph: float = 50.0,
             by_period: bool = True,
             n_boot: int = 30,
             speed_units: str = "mph",
             out_dir: Optional[Path] = None) -> dict:
    """QC → episodes → FD → QVDF → CBI ranking on a long-format frame.

    Accepts raw frames with ``speed_mph`` (runs QC first) or QC'd frames
    that already carry ``speed_mph_clean``/``qc_pass``. Pass
    ``speed_units="kmh"`` for km/h feeds (IEEE v4 / TFB). Returns a dict:
    ``qc`` (frame), ``episodes`` (frame — with ``t0_time/t2_time/t3_time``
    clock columns), ``fd`` (per-sensor dict or None), ``fd_summary``
    (frame or None, with a ``fit_ok`` physics flag), ``qvdf`` (dict or
    None), ``ranking`` (frame), ``summary`` (dict). Purely in-memory
    unless ``out_dir`` is given. FD/QVDF failures degrade to None with a
    warning — they never change the return types.

    Column-name map vs the README's symbols: T0/T2/T3 → ``t0_index/
    t2_index/t3_index`` (period-relative 5-min bins) + ``t*_time``
    timestamps; P → ``P_min`` (minutes); v_t2 → ``min_speed_mph``.
    """
    import warnings
    df = df.copy()

    # ---- upfront validation: one message listing EVERY missing column
    hard = {"sensor_uid": "detector id (str)",
            "datetime": "5-min timestamps (naive local time)",
            "road_order": "int, upstream -> downstream"}
    if "speed_mph_clean" not in df.columns:
        hard["speed_mph"] = "speed in mph (pass speed_units='kmh' for km/h feeds)"
    missing = [f"{c} — {why}" for c, why in hard.items() if c not in df.columns]
    if missing:
        raise ValueError("diagnose() input is missing required columns:\n  "
                         + "\n  ".join(missing)
                         + "\nSee docs/PACKAGE_GUIDE.md for the full contract.")
    # soft columns get sensible defaults instead of deep KeyErrors
    soft = {"corridor": "CORRIDOR", "direction": "?", "lanes": np.nan,
            "has_volume": bool("flow_vph" in df.columns),
            "length_mi": 0.5, "source_format": "user"}
    for c, v in soft.items():
        if c not in df.columns:
            df[c] = v

    # tz-aware timestamps would silently shift every AM/MD/PM label
    dtc = pd.to_datetime(df["datetime"])
    if getattr(dtc.dt, "tz", None) is not None:
        raise ValueError(
            "datetime is timezone-aware; AM/MD/PM windows are LOCAL clock "
            "hours. Convert first: df['datetime'] = df['datetime']"
            ".dt.tz_convert('<local tz>').dt.tz_localize(None)")
    df["datetime"] = dtc

    corridor = str(df["corridor"].iloc[0]) if len(df) else "CORRIDOR"

    # ---- units guards
    declared_kmh = speed_units.lower() in ("kmh", "km/h", "kph")
    if declared_kmh:
        # convert EVERY speed column present — pre-cleaned frames carry
        # speed_mph_clean only (coder review finding 5, CONFIRMED)
        for c in ("speed_mph", "speed_mph_clean"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce") / 1.609
    spd_col = "speed_mph" if "speed_mph" in df.columns else "speed_mph_clean"
    med = float(pd.to_numeric(df[spd_col], errors="coerce").median())
    if med > 90 and not declared_kmh:
        warnings.warn(
            f"median {spd_col} = {med:.0f} — this looks like km/h, not mph. "
            "Pass speed_units='kmh' (or use load_ieee_v4); diagnosing km/h "
            "as mph silently produces garbage.", UserWarning, stacklevel=2)
    if "flow_vph" in df.columns:
        p95 = float(pd.to_numeric(df["flow_vph"], errors="coerce").quantile(0.95))
        if p95 > 3200:
            warnings.warn(
                f"p95 flow_vph = {p95:.0f} — flow_vph must be PER LANE "
                "(veh/h/ln, physically <= ~2600). You appear to have passed "
                "total across lanes; divide by the lane count.",
                UserWarning, stacklevel=2)

    if "speed_mph_clean" not in df.columns:
        df_qc, qc_summary = run_qc(df)
    else:
        df_qc, qc_summary = df, {"note": "pre-cleaned input"}

    # FD needs density; k = q/v is the standard derivation when absent
    if "flow_vph" in df_qc.columns and "density_vpm" not in df_qc.columns:
        from .io_unified import synthesize_density_from_flow_speed
        df_qc["density_vpm"] = synthesize_density_from_flow_speed(
            df_qc["flow_vph"].to_numpy(),
            df_qc["speed_mph_clean"].to_numpy()
            if "speed_mph_clean" in df_qc.columns else df_qc["speed_mph"].to_numpy())

    episodes, reliability, ep_summary = run_episodes(
        df_qc, default_v_c_mph=v_c_mph, by_period=by_period)

    # clock-time versions of the group-relative bin indices. The indices are
    # POSITIONAL within each (sensor, date, period) group, so they must be
    # mapped through the group's actual timestamps — arithmetic from the
    # period start silently drifts across data gaps (coder review finding 3,
    # CONFIRMED: a missing hour shifted every reported time by the gap).
    if len(episodes) and "t0_index" in episodes.columns:
        from .stage2_episodes import _period_for_timestamp
        tmp = df_qc[["sensor_uid", "datetime"]].copy()
        tmp["date"] = tmp["datetime"].dt.date.astype(str)
        tmp["period"] = tmp["datetime"].map(_period_for_timestamp)
        lut: dict = {}
        for key, g in tmp.groupby(["sensor_uid", "date", "period"], sort=False):
            lut[key] = np.sort(g["datetime"].to_numpy())

        def _clock(row, which):
            i = row[f"{which}_index"]
            if pd.isna(i):
                return pd.NaT
            periods = ([row["period"]] if row["period"] not in ("MDPM", "all_day")
                       else (["MD", "PM"] if row["period"] == "MDPM"
                             else ["AM", "MD", "PM", "NT"]))
            arrs = [lut.get((row["sensor_uid"], str(row["date"]), p))
                    for p in periods]
            arrs = [a for a in arrs if a is not None]
            if not arrs:
                return pd.NaT
            arr = np.sort(np.concatenate(arrs))
            i = int(i)
            return pd.Timestamp(arr[i]) if 0 <= i < len(arr) else pd.NaT

        for c in ("t0", "t2", "t3"):
            episodes[f"{c}_time"] = episodes.apply(lambda r, c=c: _clock(r, c), axis=1)

    fd, fd_summary = None, None
    if "flow_vph" in df_qc.columns:
        try:
            fd = run_fd(df_qc, n_boot=n_boot)
            # one degenerate sensor must not discard everyone else's fits
            # (coder review finding 4, CONFIRMED) — NaN-fill, don't crash
            rows = []
            for sid, p in fd.items():
                fdd = p.get("fd") or {}
                cap = fdd.get("capacity_vphpl")
                vfk = fdd.get("free_flow_speed_kph")
                rows.append({
                    "sensor_uid": sid,
                    "capacity_vphpl": float(cap) if cap is not None else np.nan,
                    "v_f_mph": float(vfk) / 1.609 if vfk is not None else np.nan,
                    "r_squared": (float(fdd["r_squared"])
                                  if fdd.get("r_squared") is not None else np.nan),
                })
            fd_summary = pd.DataFrame(rows)
            # physics gate: never hand back impossible fits unflagged
            fd_summary["fit_ok"] = (
                (fd_summary["r_squared"] > 0)
                & fd_summary["capacity_vphpl"].between(1200, 2600)
                & fd_summary["v_f_mph"].between(40, 90))
            n_bad = int((~fd_summary["fit_ok"]).sum())
            if n_bad:
                warnings.warn(
                    f"{n_bad}/{len(fd_summary)} FD fits fail physics checks "
                    "(r_squared <= 0, capacity outside 1200-2600 vphpl, or "
                    "v_f outside 40-90 mph) — see fd_summary['fit_ok']. "
                    "Common causes: total instead of per-lane flow, km/h "
                    "speeds, or a detector that never reaches congestion.",
                    UserWarning, stacklevel=2)
        except Exception as exc:            # FD is optional for speed-only feeds
            warnings.warn(f"FD stage failed ({type(exc).__name__}: {exc}); "
                          "fd/fd_summary set to None", UserWarning, stacklevel=2)
            fd, fd_summary = None, None

    qvdf = None
    valid = (episodes[episodes["is_valid_for_mu"]]
             if "is_valid_for_mu" in episodes.columns else episodes)
    if fd_summary is not None and len(valid) >= 3:
        try:
            qvdf = run_qvdf(episodes, fd_summary)
        except Exception as exc:
            warnings.warn(f"QVDF stage failed ({type(exc).__name__}: {exc}); "
                          "qvdf set to None", UserWarning, stacklevel=2)
            qvdf = None

    # topology MUST come from road_order — run_ranking's alphabetical
    # fallback scrambles bottleneck classes on real station ids (coder
    # review finding 1, CONFIRMED: planted bottleneck flipped classes
    # under a sensor rename)
    ro = df_qc.groupby("sensor_uid")["road_order"].first().astype(int).to_dict()
    # provenance stamp: measured counts vs S3-synthesized vs speed-only
    vsrc = {}
    for sid, g in df_qc.groupby("sensor_uid"):
        if "flow_vph" not in g.columns or g["flow_vph"].isna().all():
            vsrc[sid] = "speed_only"
        elif "flow_synthetic" in g.columns and bool(g["flow_synthetic"].any()):
            vsrc[sid] = "synthetic"
        else:
            vsrc[sid] = "measured"
    ranking = run_ranking(
        episodes, corridor, road_order=ro, volume_source=vsrc,
        out_dir=(Path(out_dir) / "stage6_cbi") if out_dir is not None else None)
    if len(ranking):
        ranking = ranking.sort_values("CBI_score", ascending=False)

    # planner-facing state tokens: every valid episode becomes a named,
    # evidenced congestion state with a plain-English message
    try:
        tokens = compile_tokens(df_qc, episodes, corridor=corridor,
                                ranking=ranking)
    except Exception as exc:
        warnings.warn(f"token compiler failed ({type(exc).__name__}: {exc}); "
                      "tokens set to []", UserWarning, stacklevel=2)
        tokens = []
    if out_dir is not None and tokens:
        write_tokens(tokens, Path(out_dir) / "cbi_tokens")

    return {"qc": df_qc, "episodes": episodes, "reliability": reliability,
            "fd": fd, "fd_summary": fd_summary, "qvdf": qvdf,
            "ranking": ranking, "tokens": tokens, "out_dir": out_dir,
            "summary": {"qc": qc_summary, "episodes": ep_summary}}


def verify_installation(verbose: bool = True) -> bool:
    """Data-free smoke test: simulate corridors, diagnose them, check physics.

    This is an install/CI smoke test (recovering a planted signal from
    self-generated data), NOT scientific evidence — the evidence lives in
    the benchmark reproductions. The invariant must hold across several
    seeds: the planted bottleneck ranks #1 and a discharge window (hence a
    measurable μ) exists at the bottleneck.
    """
    ok = True
    for seed in (0, 7, 42):
        out = diagnose(simulate_corridor(days=5, seed=seed))
        ep = out["episodes"]
        valid = ep[ep["is_valid_for_mu"]] if len(ep) else ep
        top = out["ranking"].iloc[0] if len(out["ranking"]) else None
        seed_ok = (len(valid) >= 3 and top is not None
                   and str(top["sensor_uid"]) == "SIM03")
        if verbose and top is not None:
            print(f"seed {seed}: top={top['sensor_uid']} (expected SIM03) "
                  f"CBI_score={top['CBI_score']:.3f} class={top['bottleneck_class']} "
                  f"-> {'ok' if seed_ok else 'FAIL'}")
        ok &= seed_ok
    if verbose:
        print("verify_installation:", "PASS" if ok else "FAIL")
    return bool(ok)
