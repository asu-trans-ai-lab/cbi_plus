"""
run_pipeline.py — CLI for the cbi_pipeline package.

Examples:
    python -m cbi_pipeline.run_pipeline --stage qc       --source inrix --inrix-folder ../01_input_data/I-17/I-17
    python -m cbi_pipeline.run_pipeline --stage episodes
    python -m cbi_pipeline.run_pipeline --stage fd
    python -m cbi_pipeline.run_pipeline --stage mu       --mode valid_only
    python -m cbi_pipeline.run_pipeline --stage all      --source pems

Each stage reads its inputs from disk (from prior stages' outputs) and writes
to disk, so stages can be rerun independently.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import io_unified
from . import stage1_qc
from . import stage2_episodes
from . import stage3_fd_robust
from . import stage4_mu_validation
from . import diagnostics as diag


DEFAULT_OUT_ROOT = (Path(__file__).resolve().parents[2]
                    / "03_calibration_outputs" / "large_sample_150sensors" / "cbi_v2")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_source(args) -> pd.DataFrame:
    """Load Stage-0 timeseries from the chosen source."""
    if args.source == "inrix":
        if not args.inrix_folder:
            raise SystemExit("--inrix-folder is required for --source inrix")
        return io_unified.load_inrix_folder(
            args.inrix_folder,
            t_start=args.t_start, t_end=args.t_end,
            s3_prior=args.s3_prior,
            auto_calibrate_vf=not args.no_auto_vf,
            rederive_kc_and_m=args.rederive_kc_and_m,
            synthesize_flow=not args.no_synthesize_flow,
        )
    if args.source == "pems":
        return io_unified.load_pems(t_start=args.t_start, t_end=args.t_end,
                                    path=args.pems_path,
                                    representative=not args.pems_all_sensors)
    raise SystemExit(f"Unknown source: {args.source!r}")


def _read_stage1(out_root: Path) -> pd.DataFrame:
    parquet_dir = out_root / "stage1_qc" / "per_sensor"
    if not parquet_dir.exists():
        raise SystemExit(f"Stage 1 outputs not found at {parquet_dir}. "
                         "Run --stage qc first.")
    pieces = [pd.read_parquet(p) for p in sorted(parquet_dir.glob("*.parquet"))]
    return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()


def _read_stage2(out_root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    eps = pd.read_csv(out_root / "stage2_episodes" / "episodes_per_link_day.csv")
    rel = pd.read_csv(out_root / "stage2_episodes" / "link_reliability.csv")
    return eps, rel


def _read_stage3(out_root: Path) -> pd.DataFrame:
    return pd.read_csv(out_root / "stage3_fd" / "stage3_fd_summary.csv")


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------
def run_stage_qc(args, out_root: Path) -> pd.DataFrame:
    print("-> Stage 1: speed-data QC")
    raw = _load_source(args)
    print(f"   loaded {len(raw):,} rows, {raw['sensor_uid'].nunique()} sensors")
    df_qc, summary = stage1_qc.run_qc(
        raw, v_c_mph=args.v_c, v_f_mph=args.v_f,
        dv_max=args.dv_max,
        hampel_window=args.hampel_window,
        hampel_sigma=args.hampel_sigma,
        max_spatial_gap_mph=args.spatial_gap,
    )
    stage1_qc.write_stage1(df_qc, summary, out_root / "stage1_qc")
    print(f"   qc_pass_rate = {summary['qc_pass_rate']:.3f}")

    diag_dir = out_root / "diagnostics" / "stage1"
    diag_dir.mkdir(parents=True, exist_ok=True)
    # one QC panel per sensor (cap at 12 to keep folder tidy)
    for i, (sid, grp) in enumerate(df_qc.groupby("sensor_uid")):
        if i >= 12:
            break
        flags = grp[[c for c in grp.columns if c.startswith("qc_")]]
        safe = sid.replace(":", "_").replace("/", "_")
        diag.plot_qc_panel(grp["speed_mph"].to_numpy(),
                           grp["speed_mph_clean"].to_numpy(),
                           flags, sid,
                           diag_dir / f"qc_{safe}.png")

    # corridor-level direction panel
    for corr, grp in df_qc.groupby("corridor"):
        panel = io_unified.build_corridor_panel(grp)
        sf = panel["speed_field"]
        if sf.size == 0:
            continue
        dir_info = stage1_qc.speed_wave_direction_check(sf, v_c_mph=args.v_c)
        diag.plot_speed_wave_direction(
            sf, dir_info["first_drop_times"], panel["sensor_ids"],
            dir_info["bottleneck_sensor_idx"],
            diag_dir / f"direction_{corr}.png",
        )
        diag.plot_time_space_heatmap(sf, panel["sensor_ids"],
                                     panel["time_axis"],
                                     diag_dir / f"timespace_{corr}.png")
    return df_qc


def run_stage_episodes(args, out_root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    print("-> Stage 2: episodes + day classification")
    df_qc = _read_stage1(out_root)
    eps_df, rel_df, summary = stage2_episodes.run_episodes(
        df_qc, default_v_c_mph=args.v_c, dt_min=args.dt_min,
    )
    stage2_episodes.write_stage2(eps_df, rel_df, summary,
                                 out_root / "stage2_episodes")
    print(f"   {summary['n_episodes']} episodes, "
          f"{summary['n_valid']} valid; reliability = {summary['reliability_distribution']}")

    diag_dir = out_root / "diagnostics" / "stage2"
    diag.plot_episode_taxonomy(eps_df, diag_dir / "episode_taxonomy.png")
    diag.plot_coverage_table(eps_df, diag_dir / "coverage_table.png")
    diag.plot_reliability_ladder(rel_df, diag_dir / "reliability_ladder.png")
    return eps_df, rel_df


def run_stage_fd(args, out_root: Path) -> dict:
    print("-> Stage 3: robust regime-separated FD")
    df_qc = _read_stage1(out_root)
    fd_by_sensor = stage3_fd_robust.run_fd(
        df_qc, n_boot=args.n_boot, huber_eps=args.huber_eps,
        corridor_C_prior_vphpl=args.corridor_capacity_prior,
    )
    stage3_fd_robust.write_stage3(fd_by_sensor, out_root / "stage3_fd")
    print(f"   wrote {len(fd_by_sensor)} FD JSONs")

    diag_dir = out_root / "diagnostics" / "stage3"
    for sid, grp in df_qc.groupby("sensor_uid"):
        payload = fd_by_sensor.get(sid)
        if payload is None:
            continue
        safe = sid.replace(":", "_").replace("/", "_")
        diag.plot_robust_fd(grp, payload, diag_dir / f"fd_{safe}.png")
    return fd_by_sensor


def run_stage_mu(args, out_root: Path) -> dict:
    print("-> Stage 4: mu validation")
    df_qc = _read_stage1(out_root)
    eps_df, rel_df = _read_stage2(out_root)
    fd_summary = _read_stage3(out_root)
    res = stage4_mu_validation.run_mu(eps_df, rel_df, df_qc, fd_summary)
    stage4_mu_validation.write_stage4(res, out_root / "stage4_mu")
    print(f"   all_days   R2 = {res['compare_all_days'].get('r2', float('nan')):.3f}, n = {res['compare_all_days'].get('n')}")
    print(f"   valid_only R2 = {res['compare_valid_only'].get('r2', float('nan')):.3f}, n = {res['compare_valid_only'].get('n')}")

    diag_dir = out_root / "diagnostics" / "stage4"
    diag.plot_observed_mu_vs_features(res["episodes_with_mu"], fd_summary,
                                      diag_dir / "mu_vs_features.png")
    diag.plot_predicted_vs_observed_mu(res["compare_all_days"],
                                       res["compare_valid_only"],
                                       diag_dir / "pred_vs_obs_mu.png")
    diag.plot_shrinkage_ladder(res["per_link"], diag_dir / "shrinkage_ladder.png")
    return res


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CBI / FD / QVDF revised pipeline")
    p.add_argument("--stage", choices=["qc", "episodes", "fd", "mu", "all"],
                   required=True)
    p.add_argument("--source", choices=["pems", "inrix"], default="pems")
    p.add_argument("--inrix-folder", type=str, default=None)
    p.add_argument("--pems-path", type=str, default=None)
    p.add_argument("--pems-all-sensors", action="store_true",
                   help="Load link_performance_all_sensors.json instead of representative.")
    p.add_argument("--t-start", type=str, default=None)
    p.add_argument("--t-end", type=str, default=None)
    p.add_argument("--out-root", type=str, default=str(DEFAULT_OUT_ROOT))

    # Calibration knobs
    p.add_argument("--v-c", type=float, default=50.0, help="speed at capacity (mph)")
    p.add_argument("--v-f", type=float, default=75.0, help="free-flow speed prior (mph)")
    p.add_argument("--dt-min", type=float, default=5.0, help="time interval (min)")
    p.add_argument("--dv-max", type=float, default=30.0, help="max |Δv| per step")
    p.add_argument("--hampel-window", type=int, default=11)
    p.add_argument("--hampel-sigma", type=float, default=3.0)
    p.add_argument("--spatial-gap", type=float, default=20.0)
    p.add_argument("--huber-eps", type=float, default=1.35)
    p.add_argument("--n-boot", type=int, default=200)
    p.add_argument("--corridor-capacity-prior", type=float, default=2000.0)
    p.add_argument("--mode", choices=["all_days", "valid_only"], default="valid_only",
                   help="Stage 4 reporting mode (both are always written; this is informational).")

    # ---- S3 prior (used only when source=inrix and flow is synthesized) ----
    from .schemas import S3_PRIOR_PRESETS
    p.add_argument(
        "--s3-prior",
        choices=list(S3_PRIOR_PRESETS.keys()),
        default="cbi_default",
        help=("Named S3 prior for synthesizing INRIX flow from speed. "
              "cbi_default = Phoenix urban (vf=70, kc=45). "
              "rural_freeway / az_tmc_i17 = AZ I-17 style (vf=75, kc=32). "
              "These are ASSUMPTIONS — pick the one closest to your facility."),
    )
    p.add_argument("--no-auto-vf", action="store_true",
                   help="Disable auto-calibration of vf from the 95th-percentile speed.")
    p.add_argument("--rederive-kc-and-m", action="store_true",
                   help="Re-derive k_critical and s3_m from the (calibrated) vf "
                        "via v_critical = 0.7 vf (CBI closed-form).")
    p.add_argument("--no-synthesize-flow", action="store_true",
                   help="Skip CBI inverse-S3 synthesis (INRIX rows keep NaN flow).")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    if args.stage in ("qc", "all"):
        run_stage_qc(args, out_root)
    if args.stage in ("episodes", "all"):
        run_stage_episodes(args, out_root)
    if args.stage in ("fd", "all"):
        run_stage_fd(args, out_root)
    if args.stage in ("mu", "all"):
        run_stage_mu(args, out_root)

    print(f"[done] outputs at {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
