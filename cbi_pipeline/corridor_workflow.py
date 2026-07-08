"""
corridor_workflow.py — single-corridor orchestrator.

For one corridor (PeMS sensor cluster or INRIX TMC corridor), run:

    Stage 1   speed-data QC + corridor direction check
    Stage 2   episode + day classification (per AM/MD/PM period)
    Stage 3   FD calibration   (PeMS = data-fit, TMC = assumed S3 prior)
    Stage 4   discharge-window mu + group shrinkage
    Stage 5   QVDF + shape forward model   (per AM/MD/PM, weekday & difficult filters)

Emits the FIXED-layout diagnostic figures as per-corridor quality-checking
gates so a human can flag bad TMC matches, weak FD fits, or thin episode
samples before any paper figure is regenerated.

CLI:
    python -m cbi_pipeline.corridor_workflow --corridor I-17 --source inrix \\
        --inrix-folder ../01_input_data/I-17/I-17 --s3-prior az_tmc_i17

    python -m cbi_pipeline.corridor_workflow --corridor 5-N --source pems
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from . import io_unified
from . import stage1_qc
from . import stage2_episodes
from . import stage3_fd_robust
from . import stage4_mu_validation
from . import stage4_verification
from . import stage5_qvdf
from . import stage5_verification
from . import stage2b_measured_diagnostics
from . import stage5b_corridor_aggregate
from . import diagnostics as diag
from .schemas import (PERIOD_DEFINITIONS, period_label_for_filename,
                      DAY_FILTERS, QUALITY_GATES, resolve_s3_prior)


DEFAULT_OUT_ROOT = (Path(__file__).resolve().parents[2]
                    / "03_calibration_outputs" / "large_sample_150sensors"
                    / "cbi_v2_corridors")


# ---------------------------------------------------------------------------
# Quality gates — emit a PASS/FAIL row per (corridor, period)
# ---------------------------------------------------------------------------
def evaluate_gates(stage1_summary: dict,
                   stage2_summary: dict,
                   fd_summary: pd.DataFrame,
                   mu_compare: dict,
                   qvdf_summary: dict,
                   has_volume: bool) -> dict:
    gates = QUALITY_GATES
    r2_all = mu_compare.get("all_days", {}).get("r2", float("nan"))
    r2_valid = mu_compare.get("valid_only", {}).get("r2", float("nan"))
    r2_gap = (r2_valid - r2_all) if np.isfinite(r2_valid) and np.isfinite(r2_all) else float("nan")

    fd_r2_median = float(fd_summary["r_squared"].median()) if len(fd_summary) else float("nan")

    direction_conf = next(iter(stage1_summary.get("direction_by_corridor", {}).values()), {}) \
                        .get("direction_confidence", float("nan"))

    valid_pct = (stage2_summary.get("n_valid", 0) /
                 max(stage2_summary.get("n_episodes", 1), 1))

    checks = {
        "qc_pass_rate":       (stage1_summary["qc_pass_rate"], gates["min_qc_pass_rate"]),
        "direction_confidence": (direction_conf, gates["min_direction_confidence"]),
        "valid_episode_pct":   (valid_pct, 0.05),  # at least 5% of episodes valid
        "fd_R2 (PeMS only)":   (fd_r2_median if has_volume else None,
                                gates["min_fd_r2"] if has_volume else None),
        "mu_R2_gap_valid_vs_all": (r2_gap, gates["min_mu_R2_gap_valid_vs_all"]),
        "qvdf_n_fitted":       (qvdf_summary.get("n_fitted_sensor_period", 0),
                                gates["min_qvdf_n_points"]),
    }
    results = {}
    for name, (val, thresh) in checks.items():
        if val is None:
            results[name] = dict(value=None, threshold=None, status="N/A")
        elif not np.isfinite(val) if isinstance(val, float) else False:
            results[name] = dict(value=val, threshold=thresh, status="UNKNOWN")
        else:
            ok = val >= thresh if thresh is not None else True
            results[name] = dict(value=float(val), threshold=float(thresh) if thresh is not None else None,
                                 status="PASS" if ok else "FAIL")
    # Overall status: PASS only if no FAIL. UNKNOWN/N/A do NOT downgrade to FAIL --
    # they just mean the gate could not be evaluated (e.g. single-sensor corridor
    # for direction_confidence). They propagate to "INCONCLUSIVE" only if no PASS exists.
    statuses = [r["status"] for r in results.values()]
    if "FAIL" in statuses:
        overall = "FAIL"
    elif "PASS" in statuses:
        overall = "PASS"
    else:
        overall = "INCONCLUSIVE"
    results["__overall__"] = overall
    return results


# ---------------------------------------------------------------------------
# Diagnostic-figure emitter (FIXED-layout file naming)
# ---------------------------------------------------------------------------
def emit_figures(qvdf_result: dict,
                 mu_per_link: pd.DataFrame,
                 df_qc: pd.DataFrame,
                 fd_summary: pd.DataFrame,
                 out_dir: Path,
                 corridor: str,
                 day_filter: str) -> None:
    """
    Emit FIXED-layout PNGs for one (corridor, day_filter). Mirrors:
        {day_filter}__variation_{1_daily|2_period_aggregated}__{plot}.png
        {day_filter}__variation_2_period_aggregated__sensor_{X}__{HHMM_HHMM}__td_speed.png
    """
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    preds = qvdf_result["predictions"]
    # Attach capacity for distribution plot
    if "capacity_vphpl" not in preds.columns:
        preds = preds.merge(fd_summary[["sensor_uid", "capacity_vphpl"]],
                            on="sensor_uid", how="left")
    title = f"[{corridor} / {day_filter}] "

    # ---------------- variation_1_daily (sensor × date) ----------------
    v1 = f"{day_filter}__variation_1_daily"
    diag.plot_P_pred_vs_obs(preds, fig_dir / f"{v1}__P_pred_vs_obs.png",
                            title_prefix=title)
    diag.plot_mu_pred_vs_obs_stage5(preds, mu_per_link,
                                    fig_dir / f"{v1}__mu_pred_vs_obs.png",
                                    title_prefix=title)
    diag.plot_observed_distributions(preds, fig_dir / f"{v1}__observed_distributions.png",
                                     title_prefix=title)
    diag.plot_qvdf_vs_shape(preds, fig_dir / f"{v1}__qvdf_speed_vs_shape_speed.png",
                            which="speed", title_prefix=title)
    diag.plot_qvdf_vs_shape(preds, fig_dir / f"{v1}__qvdf_avg_speed_vs_shape_avg_speed.png",
                            which="avg_speed", title_prefix=title)
    diag.plot_qvdf_vs_shape(preds, fig_dir / f"{v1}__qvdf_min_speed_vs_shape_min_speed.png",
                            which="min_speed", title_prefix=title)

    # ---------------- variation_2_period_aggregated (sensor × period) ----------------
    v2 = f"{day_filter}__variation_2_period_aggregated"
    diag.plot_P_pred_vs_obs(preds, fig_dir / f"{v2}__P_pred_vs_obs.png",
                            title_prefix=title)
    diag.plot_mu_pred_vs_obs_stage5(preds, mu_per_link,
                                    fig_dir / f"{v2}__mu_pred_vs_obs.png",
                                    title_prefix=title)
    diag.plot_qvdf_vs_shape(preds, fig_dir / f"{v2}__qvdf_speed_vs_shape_speed.png",
                            which="speed", title_prefix=title)
    diag.plot_qvdf_vs_shape(preds, fig_dir / f"{v2}__qvdf_avg_speed_vs_shape_avg_speed.png",
                            which="avg_speed", title_prefix=title)
    diag.plot_qvdf_vs_shape(preds, fig_dir / f"{v2}__qvdf_min_speed_vs_shape_min_speed.png",
                            which="min_speed", title_prefix=title)
    diag.plot_P_heatmap(preds, fig_dir / f"{v2}__P_obs_heatmap.png",
                        value_col="P_min", title_prefix=title)
    preds["P_pred_min"] = preds["P_pred_hours"] * 60.0
    diag.plot_P_heatmap(preds, fig_dir / f"{v2}__P_pred_heatmap.png",
                        value_col="P_pred_min", title_prefix=title)
    preds["P_error_min"] = preds["P_pred_min"] - preds["P_min"]
    diag.plot_P_heatmap(preds, fig_dir / f"{v2}__P_error_heatmap.png",
                        value_col="P_error_min", title_prefix=title)

    # ---------------- td_speed per sensor x period (cap at 4 sensors x 3 periods) ----------------
    top_sensors = (preds.groupby("sensor_uid")["P_min"].sum()
                        .sort_values(ascending=False).head(4).index.tolist())
    for sid in top_sensors:
        for period_lab in ["AM", "MD", "PM"]:
            safe_sid = sid.replace(":", "_").replace("/", "_")
            file_period = period_label_for_filename(period_lab)
            fname = f"{v2}__sensor_{safe_sid}__{file_period}__td_speed.png"
            # Filter qc_df to just the relevant period
            ts = pd.to_datetime(df_qc["datetime"])
            h0, h1 = PERIOD_DEFINITIONS[period_lab]
            mask = ((df_qc["sensor_uid"] == sid)
                    & (ts.dt.hour >= h0) & (ts.dt.hour < h1))
            sub_qc = df_qc[mask]
            if not sub_qc.empty:
                diag.plot_td_speed(sub_qc, sid, period_lab,
                                   fig_dir / fname,
                                   v_c_mph=50.0, v_f_mph=70.0)


# ---------------------------------------------------------------------------
# One-corridor end-to-end
# ---------------------------------------------------------------------------
def run_corridor(corridor: str,
                 source: str,
                 inrix_folder: Optional[Path] = None,
                 pems_path: Optional[Path] = None,
                 pems_representative: bool = True,
                 s3_prior: str = "cbi_default",
                 auto_calibrate_vf: bool = True,
                 rederive_kc_and_m: bool = False,
                 v_c_mph: float = 50.0,
                 v_f_mph: float = 70.0,
                 n_boot: int = 50,
                 out_root: Path = DEFAULT_OUT_ROOT,
                 max_sensors: Optional[int] = None) -> dict:
    """End-to-end on a single corridor. Returns a summary dict."""
    out_dir = Path(out_root) / corridor.replace("/", "_")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Stage 0 — load
    print(f"[{corridor}] Stage 0: load {source}")
    if source == "inrix":
        df_raw = io_unified.load_inrix_folder(
            inrix_folder, s3_prior=s3_prior,
            auto_calibrate_vf=auto_calibrate_vf,
            rederive_kc_and_m=rederive_kc_and_m,
        )
    else:
        df_raw = io_unified.load_pems(path=pems_path, representative=pems_representative)
        df_raw = df_raw[df_raw["corridor"] == corridor]
        if df_raw.empty:
            print(f"   [{corridor}] no PeMS sensors match — skipping.")
            return dict(corridor=corridor, status="EMPTY")

    if max_sensors:
        keep_sensors = df_raw["sensor_uid"].unique()[:max_sensors]
        df_raw = df_raw[df_raw["sensor_uid"].isin(keep_sensors)].copy()

    print(f"   {len(df_raw):,} rows / {df_raw['sensor_uid'].nunique()} sensors")
    has_volume = bool(df_raw["has_volume"].iloc[0])

    # Stage 1 — QC
    print(f"[{corridor}] Stage 1: QC")
    df_qc, qc_summary = stage1_qc.run_qc(df_raw, v_c_mph=v_c_mph, v_f_mph=v_f_mph)
    stage1_qc.write_stage1(df_qc, qc_summary, out_dir / "stage1_qc")

    # Stage 2 — episodes (period-split)
    print(f"[{corridor}] Stage 2: episodes (per period)")
    eps, rel, ep_summary = stage2_episodes.run_episodes(df_qc, default_v_c_mph=v_c_mph)
    stage2_episodes.write_stage2(eps, rel, ep_summary, out_dir / "stage2_episodes")

    # Stage 3 — FD
    print(f"[{corridor}] Stage 3: FD ({'data-fit' if has_volume else 'CBI prior'})")
    fd = stage3_fd_robust.run_fd(df_qc, n_boot=n_boot)
    stage3_fd_robust.write_stage3(fd, out_dir / "stage3_fd")
    fd_summary = pd.read_csv(out_dir / "stage3_fd" / "stage3_fd_summary.csv")
    fd_summary = fd_summary.rename(columns={"r_squared": "r_squared"})

    # Stage 2b — EARLY outlier screen on measured D/C vs P vs mu vs V_t2.
    # Fires BEFORE mu and QVDF so flagged episodes can be dropped from aggregation.
    print(f"[{corridor}] Stage 2b: early outlier screen on measured episodes")
    stage2b_result = stage2b_measured_diagnostics.run_stage2b(
        eps, df_qc, fd_summary,
        out_dir=out_dir / "stage2b_measured",
    )
    out_pct = stage2b_result["summary"]["outlier_pct"]
    n_out = stage2b_result["summary"]["n_outliers"]
    print(f"   {n_out} of {stage2b_result['summary']['n_episodes']} episodes flagged "
          f"as outliers ({out_pct:.1f}%)")
    top_reasons = sorted(stage2b_result["summary"]["reasons_count"].items(),
                          key=lambda kv: -kv[1])[:5]
    for code, cnt in top_reasons:
        if cnt > 0:
            print(f"     {code:32s} {cnt}")

    # Stage 4 — mu
    print(f"[{corridor}] Stage 4: mu validation")
    mu_res = stage4_mu_validation.run_mu(eps, rel, df_qc, fd_summary)
    stage4_mu_validation.write_stage4(mu_res, out_dir / "stage4_mu")
    mu_compare = dict(all_days=mu_res["compare_all_days"],
                      valid_only=mu_res["compare_valid_only"])

    # Stage 4 verification — step-by-step audit of every valid episode
    print(f"[{corridor}] Stage 4 verification: per-episode v_c / Capacity / P / V_t2 / v(t) audit")
    s3_prior_resolved = resolve_s3_prior(s3_prior) if source == "inrix" else {
        "vf_mph": v_f_mph, "k_critical_vpm": 45.0,
        "s3_m": 4.0, "lane_capacity_vphpl": 2200.0,
        "provenance": "PeMS — capacity from FD fit",
    }
    verify_df = stage4_verification.run_verification(
        eps, df_qc, fd,
        out_dir=out_dir / "stage4_verification",
        s3_prior=s3_prior_resolved,
        max_panels=24,
        only_valid=True,
    )
    print(f"   {len(verify_df)} valid episodes audited; "
          f"{min(24, len(verify_df))} verification panels emitted")
    if len(verify_df):
        print(f"   median P = {verify_df['P_min'].median():.0f} min, "
              f"median V_t2 = {verify_df['v_t2_mph'].median():.1f} mph, "
              f"median mu_obs = {verify_df['mu_obs_vphpl'].median():.0f} vphpl")
        cons = verify_df['mu_consistency'].dropna()
        if len(cons):
            print(f"   mu consistency (|obs - inverse_S3_check|/obs): "
                  f"median = {cons.median()*100:.1f}%, p90 = {cons.quantile(0.9)*100:.1f}%")

    # Stage 5 — QVDF (two day filters)
    qvdf_summaries = {}
    fd_summary_for_qvdf = fd_summary.copy()
    if "v_f_mph" not in fd_summary_for_qvdf.columns and "v_f_kph" in fd_summary_for_qvdf.columns:
        fd_summary_for_qvdf["v_f_mph"] = fd_summary_for_qvdf["v_f_kph"] / 1.609

    for day_filter in ("weekday", "difficult"):
        print(f"[{corridor}] Stage 5: QVDF ({day_filter})")
        qres = stage5_qvdf.run_qvdf(eps, fd_summary_for_qvdf, day_filter=day_filter)
        stage5_qvdf.write_stage5(qres, out_dir / "stage5_qvdf")
        qvdf_summaries[day_filter] = dict(n_fitted_sensor_period=qres["n_fitted"])
        emit_figures(qres, mu_res["per_link"], df_qc, fd_summary_for_qvdf,
                     out_dir, corridor, day_filter)

    # Stage 5 verification — round-by-round QVDF audit per episode (mirrors C++)
    print(f"[{corridor}] Stage 5 verification: round-by-round QVDF per-episode audit")
    qvdf_verify_df = stage5_verification.run_qvdf_verification(
        eps, df_qc, fd,
        out_dir=out_dir / "stage5_verification",
        max_panels=24, only_valid=True,
    )
    if len(qvdf_verify_df):
        print(f"   {len(qvdf_verify_df)} episodes audited; "
              f"{min(24, len(qvdf_verify_df))} panels emitted")
        print(f"   median P_err = {qvdf_verify_df['P_err_pct'].median():+.1f}%   "
              f"vt2_err = {qvdf_verify_df['vt2_err_pct'].median():+.1f}%   "
              f"v(t) MAPE = {qvdf_verify_df['v_t_MAPE_pct'].median():.1f}%")
        print(f"   median Q_n={qvdf_verify_df['Q_n'].median():.2f}  "
              f"Q_s={qvdf_verify_df['Q_s'].median():.2f}  "
              f"Q_cd={qvdf_verify_df['Q_cd'].median():.2f}  "
              f"Q_cp={qvdf_verify_df['Q_cp'].median():.2f}  "
              f"Q_alpha={qvdf_verify_df['Q_alpha'].median():.2f}  "
              f"Q_beta={qvdf_verify_df['Q_beta'].median():.2f}")

    # Stage 5b — corridor-level aggregation with bootstrap CIs and shrinkage.
    print(f"[{corridor}] Stage 5b: corridor x period aggregation "
          f"(bootstrap CI + prior-weighted shrinkage)")
    # Attach corridor column to qvdf_verify_df from the episode dataframe
    qv = qvdf_verify_df.copy()
    if "corridor" not in qv.columns:
        corr_lookup = eps.set_index(["sensor_uid", "date", "period"])["corridor"].to_dict()
        qv["corridor"] = qv.apply(
            lambda r: corr_lookup.get((r["sensor_uid"], r["date"], r["period"]), corridor),
            axis=1,
        )
    agg = stage5b_corridor_aggregate.aggregate_corridor(
        qv, outlier_df=stage2b_result["scored"],
    )
    stage5b_corridor_aggregate.write_stage5b(agg, out_dir / "stage5b_corridor")
    fig_dir = out_dir / "stage5b_corridor" / "figures"
    stage5b_corridor_aggregate.plot_corridor_ladder(
        agg, fig_dir / "corridor_param_ladder.png",
    )
    print(f"   {len(agg)} (corridor, period) rows aggregated")
    if len(agg):
        for _, r in agg.iterrows():
            print(f"     {r['corridor']} / {r['period']:3s}  "
                  f"n_eps={r['n_episodes_used']:3d}  "
                  f"reliability={r['reliability_class']:>12s}  "
                  f"Q_n_shrunk={r['Q_n_shrunk']:.2f} "
                  f"Q_cd_shrunk={r['Q_cd_shrunk']:.2f} "
                  f"Q_cp_shrunk={r['Q_cp_shrunk']:.2f}  "
                  f"(self/shrunk/prior: {r['Q_n_source']})")

    # Quality gates (use weekday filter)
    gates = evaluate_gates(qc_summary, ep_summary, fd_summary, mu_compare,
                           qvdf_summaries["weekday"], has_volume)
    with open(out_dir / "quality_gates.json", "w") as f:
        json.dump(gates, f, indent=2, default=float)
    overall = gates.pop("__overall__")
    print(f"[{corridor}] Quality gates: {overall}")
    for name, info in gates.items():
        v_str = f"{info['value']:.3f}" if isinstance(info.get("value"), (int, float)) and info["value"] is not None else str(info.get("value"))
        t_str = f"{info['threshold']:.3f}" if isinstance(info.get("threshold"), (int, float)) and info["threshold"] is not None else str(info.get("threshold"))
        print(f"   {info['status']:5s}  {name:35s} value={v_str:>8s}  threshold={t_str}")

    return dict(
        corridor=corridor,
        out_dir=str(out_dir),
        status=overall,
        has_volume=has_volume,
        n_sensors=int(df_qc["sensor_uid"].nunique()),
        n_episodes=int(len(eps)),
        n_valid_episodes=int(eps["is_valid_for_mu"].sum()),
        gates=gates,
        mu_compare=dict(
            all_days_r2=mu_compare["all_days"].get("r2"),
            valid_only_r2=mu_compare["valid_only"].get("r2"),
        ),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    from .schemas import S3_PRIOR_PRESETS
    p = argparse.ArgumentParser(description="Per-corridor CBI/FD/QVDF workflow")
    p.add_argument("--corridor", required=True,
                   help="Corridor key (PeMS: '5-N', '405-S'; INRIX: 'I-17')")
    p.add_argument("--source", choices=["pems", "inrix"], required=True)
    p.add_argument("--inrix-folder", type=str, default=None)
    p.add_argument("--pems-path", type=str, default=None)
    p.add_argument("--pems-all-sensors", action="store_true")
    p.add_argument("--s3-prior", choices=list(S3_PRIOR_PRESETS.keys()),
                   default="cbi_default")
    p.add_argument("--no-auto-vf", action="store_true")
    p.add_argument("--rederive-kc-and-m", action="store_true")
    p.add_argument("--v-c", type=float, default=50.0)
    p.add_argument("--v-f", type=float, default=70.0)
    p.add_argument("--n-boot", type=int, default=50)
    p.add_argument("--max-sensors", type=int, default=None,
                   help="Truncate to first N sensors for quick smoke tests.")
    p.add_argument("--out-root", type=str, default=str(DEFAULT_OUT_ROOT))
    args = p.parse_args(argv)

    summary = run_corridor(
        corridor=args.corridor, source=args.source,
        inrix_folder=args.inrix_folder, pems_path=args.pems_path,
        pems_representative=not args.pems_all_sensors,
        s3_prior=args.s3_prior,
        auto_calibrate_vf=not args.no_auto_vf,
        rederive_kc_and_m=args.rederive_kc_and_m,
        v_c_mph=args.v_c, v_f_mph=args.v_f,
        n_boot=args.n_boot, max_sensors=args.max_sensors,
        out_root=Path(args.out_root),
    )
    print(f"[done] {summary['corridor']}: {summary['status']}")
    print(json.dumps(summary, indent=2, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
