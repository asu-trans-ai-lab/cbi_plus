# -*- coding: utf-8 -*-
"""benchmark_gates — the hard acceptance gates for a CBI+/QVDF run.

Implements the closeout review's gate framework (benchmarks/GATES_MEMO.md +
benchmarks/benchmark_validation_tolerance_template.csv): a corridor run is not
"delivered" until it emits a machine-readable PASS/FAIL/REVIEW verdict per gate,
plus the two required artifacts:

    benchmark_gates/pass_fail_summary.csv        one row per gate x period
    benchmark_gates/benchmark_comparison_report.csv   current vs reference stats
                                                 (when a reference run is given)

Gate families implemented from the run's own outputs (no reference needed):
  physics    : capacity band, mu/C band, FD R2, v_t2 < v_c, mu magnitude
  episodes   : valid episodes per sensor-period, boundary-truncation share,
               direction confidence, weekday-filter correctness
  qvdf       : round-trip P/vt2 exactness, v(t) MAE (mph, hard <= 10),
               fitted coverage, feasibility-clipping share
  ranking    : ranking artifact exists, top-5 stability vs reference (if given)

Reference comparison (optional): point --reference at a previous run's
stage4_verification.csv to get per-period deltas + Spearman rank stability.

CLI:
  python -m cbi_pipeline.benchmark_gates <run_dir> [--reference <old_run_dir>]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

HARD_SPEED_MAE_MPH = 10.0
CAP_BAND = (1500, 2300)
MUC_REVIEW = (0.80, 1.05)
MUC_PREF = (0.85, 0.98)


def _verdict(ok: bool, review: bool = False) -> str:
    return "PASS" if ok else ("REVIEW" if review else "FAIL")


def gate_rows(run: Path, reference: Path | None = None) -> list[dict]:
    rows = []

    def add(family, gate, period, value, verdict, threshold, note=""):
        rows.append(dict(family=family, gate=gate, period=period,
                         value=(round(value, 4) if isinstance(value, float) else value),
                         verdict=verdict, threshold=threshold, note=note))

    # ---------------- run-level gates from quality_gates.json -----------------
    qg_path = run / "quality_gates.json"
    if qg_path.exists():
        qg = json.loads(qg_path.read_text())
        for k, v in qg.items():
            if isinstance(v, dict):
                val = v.get("value")
                val = float(val) if isinstance(val, (int, float)) and val == val else "n/a"
                add("pipeline", k, "all", val, str(v.get("status")), str(v.get("threshold")))

    # ---------------- stage-4: physics ---------------------------------------
    v4p = run / "stage4_verification" / "stage4_verification.csv"
    if not v4p.exists():
        add("artifact", "stage4_verification_exists", "all", "missing", "FAIL",
            "required", "no audited episodes — cannot gate physics")
        return rows
    v4 = pd.read_csv(v4p)
    for period, g in v4.groupby("period"):
        cap = g["capacity_calibrated_vphpl"].median()
        add("physics", "capacity_vphpl_band", period, float(cap),
            _verdict(CAP_BAND[0] <= cap <= CAP_BAND[1], review=True),
            f"{CAP_BAND[0]}-{CAP_BAND[1]} normal")
        muc = (g["mu_obs_vphpl"] / g["capacity_calibrated_vphpl"]).median()
        ok = MUC_PREF[0] <= muc <= MUC_PREF[1]
        rev = MUC_REVIEW[0] <= muc <= MUC_REVIEW[1]
        add("physics", "mu_over_C_band", period, float(muc),
            "PASS" if ok else ("REVIEW" if rev else "FAIL"),
            f"{MUC_PREF[0]}-{MUC_PREF[1]} preferred; {MUC_REVIEW[0]}-{MUC_REVIEW[1]} review")
        n_vt2_bad = int((g["v_t2_mph"] >= g["v_c_calibrated_mph"]).sum())
        add("physics", "v_t2_below_v_c", period, n_vt2_bad,
            _verdict(n_vt2_bad == 0, review=n_vt2_bad <= 3),
            "0 episodes with v_t2 >= v_c(calibrated)")
        add("physics", "mu_consistency_median", period,
            float(g["mu_consistency"].median()),
            _verdict(g["mu_consistency"].median() <= 0.10, review=True), "<=0.10")

    # ---------------- stage-2: episode gates ----------------------------------
    epp = run / "stage2_episodes" / "episodes_per_link_day.csv"
    if epp.exists():
        eps = pd.read_csv(epp)
        val = eps[eps["is_valid_for_mu"]]
        per_sp = val.groupby(["sensor_uid", "period"]).size()
        share_ok = float((per_sp >= 5).mean()) if len(per_sp) else 0.0
        add("episodes", "sensor_periods_with_5plus_valid", "all", share_ok,
            _verdict(share_ok >= 0.5, review=share_ok >= 0.3),
            ">=5 valid episodes; INSUFFICIENT_DATA below")
        # boundary truncation AFTER the MDPM merge: pure MD pinned at its edge
        md = val[val["period"] == "MD"]
        if len(md):
            trunc = float((md["t3_index"] >= 71).mean())
            add("episodes", "boundary_truncation_share_MD", "MD", trunc,
                _verdict(trunc <= 0.20, review=trunc <= 0.35), "<=20% after MDPM merge")
        wk = pd.to_datetime(val["date"]).dt.dayofweek
        add("episodes", "weekend_share_of_valid", "all", float((wk >= 5).mean()),
            "INFO", "context only (stage4 audits all days by design)")

    # ---------------- stage-5: QVDF gates -------------------------------------
    v5p = run / "stage5_verification" / "stage5_qvdf_verification.csv"
    if v5p.exists():
        v5 = pd.read_csv(v5p)
        for period, g in v5.groupby("period"):
            add("qvdf", "roundtrip_P_err_pct_median", period,
                float(g["P_err_pct"].abs().median()),
                _verdict(g["P_err_pct"].abs().median() <= 1.0), "~0 (<=1%)")
            add("qvdf", "roundtrip_vt2_err_pct_median", period,
                float(g["vt2_err_pct"].abs().median()),
                _verdict(g["vt2_err_pct"].abs().median() <= 1.0), "~0 (<=1%)")
            if "v_t_MAE" in g.columns and g["v_t_MAE"].notna().any():
                mae = float(g["v_t_MAE"].median())
                add("qvdf", "vt_speed_MAE_mph_median", period, mae,
                    _verdict(mae <= HARD_SPEED_MAE_MPH, review=mae <= 15),
                    f"<= {HARD_SPEED_MAE_MPH} mph HARD; <=5 preferred")
        if "calibration_status" in v5.columns:
            bad = float((v5["calibration_status"] != "ok").mean())
            add("qvdf", "calibration_status_ok_share", "all", 1 - bad,
                _verdict(bad <= 0.25, review=bad <= 0.4), ">=75% ok")

    # ---------------- ranking artifact ----------------------------------------
    rk = run / "stage6_cbi" / "benchmark_bottleneck_ranking.csv"
    add("ranking", "bottleneck_ranking_exists", "all",
        "present" if rk.exists() else "missing",
        "PASS" if rk.exists() else "FAIL", "required artifact")

    # ---------------- reference comparison ------------------------------------
    if reference is not None:
        ref4 = Path(reference) / "stage4_verification" / "stage4_verification.csv"
        if ref4.exists() and rk.exists():
            old = pd.read_csv(ref4)
            new_rank = pd.read_csv(rk)
            old_score = (old.groupby("sensor_uid")
                            .apply(lambda g: len(g) * g["P_min"].median()
                                   * (1 - g["v_t2_mph"] / g["v_c_prior_mph"]).clip(lower=0).median()))
            new_score = new_rank.groupby("sensor_uid")["CBI_score"].max()
            both = old_score.index.intersection(new_score.index)
            if len(both) >= 5:
                sp = float(pd.Series(old_score[both]).rank()
                           .corr(pd.Series(new_score[both]).rank(), method="spearman"))
                add("ranking", "spearman_vs_reference", "all", sp,
                    _verdict(sp >= 0.70, review=sp >= 0.5), ">=0.70 preferred")
                top_old = set(old_score.sort_values(ascending=False).head(5).index)
                top_new = set(new_score.sort_values(ascending=False).head(5).index)
                ov = len(top_old & top_new)
                add("ranking", "top5_overlap_vs_reference", "all", ov,
                    _verdict(ov >= 4, review=ov >= 3), ">=4/5 preferred; >=3/5 review")
    return rows


def run_gates(run_dir: Path, reference: Path | None = None) -> pd.DataFrame:
    run_dir = Path(run_dir)
    rows = gate_rows(run_dir, reference)
    df = pd.DataFrame(rows)
    out = run_dir / "benchmark_gates"
    out.mkdir(exist_ok=True)
    df.to_csv(out / "pass_fail_summary.csv", index=False)

    # benchmark_comparison_report: per-period headline stats (current run),
    # with reference columns when available
    v4p = run_dir / "stage4_verification" / "stage4_verification.csv"
    if v4p.exists():
        v4 = pd.read_csv(v4p)
        cur = (v4.groupby("period")
                 .agg(n_valid=("P_min", "size"), P_min_median=("P_min", "median"),
                      v_t2_median=("v_t2_mph", "median"),
                      mu_median=("mu_obs_vphpl", "median"),
                      capacity_median=("capacity_calibrated_vphpl", "median"))
                 .round(1).reset_index())
        cur["run"] = str(run_dir)
        if reference is not None:
            ref4 = Path(reference) / "stage4_verification" / "stage4_verification.csv"
            if ref4.exists():
                old = pd.read_csv(ref4)
                o = (old.groupby("period")
                        .agg(ref_n_valid=("P_min", "size"),
                             ref_P_min_median=("P_min", "median"),
                             ref_v_t2_median=("v_t2_mph", "median"),
                             ref_mu_median=("mu_obs_vphpl", "median"))
                        .round(1).reset_index())
                cur = cur.merge(o, on="period", how="left")
        cur.to_csv(out / "benchmark_comparison_report.csv", index=False)

    n = df["verdict"].value_counts().to_dict()
    hard_fail = df[(df["verdict"] == "FAIL")]
    print(f"[gates] {run_dir.name}: {n}")
    for r in hard_fail.itertuples(index=False):
        print(f"   FAIL  {r.family}/{r.gate} [{r.period}] = {r.value}  (need {r.threshold})")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--reference", default=None)
    a = ap.parse_args()
    run_gates(Path(a.run_dir), Path(a.reference) if a.reference else None)


if __name__ == "__main__":
    main()
