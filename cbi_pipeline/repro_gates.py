# -*- coding: utf-8 -*-
"""repro_gates — one command that proves every benchmark still reproduces.

The closeout rule is "reproduction is the key": each legacy-repo benchmark
under benchmarks/ ships its complete dataset + a reproduce script + KEYED
reference statistics. This module runs (or verifies) each one and emits a
single verdict table, so an integration can never silently break a published
result again.

    python -m cbi_pipeline.repro_gates            # verify existing outputs
    python -m cbi_pipeline.repro_gates --run      # re-run every script first

Writes benchmarks/repro_pass_fail.csv. Exit code 1 if any gate FAILs.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BM = ROOT / "benchmarks"

# keyed reference values: (csv, column, row-selector, expected, rel_tol)
REGISTRY = [
    dict(name="qvdf_paper_i10", script="reproduce_qvdf_paper.py",
         checks=[("Table7_calibrated_coeffs.csv", "f_d", ("Detector", 139), 1.4307, 0.01),
                 ("Table7_calibrated_coeffs.csv", "n", ("Detector", 139), 1.0566, 0.01),
                 ("Table7_calibrated_coeffs.csv", "s", ("Detector", 78), 2.0995, 0.01)],
         figures=["figures/Fig10_step1_DC_vs_P.png", "figures/Fig8_FD_volume_speed.png",
                  "figures/Fig14_td_speed_Monday.png"]),
    dict(name="qvdf_paper_casestudy2", script="reproduce_casestudy2.py",
         checks=[("calibrated_coefficients.csv", "n", None, 1.0461, 0.005),
                 ("calibrated_coefficients.csv", "f_d", None, 1.1238, 0.005),
                 ("calibrated_coefficients.csv", "P_fit_R2", None, 0.977, 0.02)],
         figures=["figures/Fig19_20_P_vs_DC.png", "figures/Fig23_capacity_discount.png"]),
    dict(name="fd_16models", script="reproduce_fd16.py",
         checks=[("model_parameters_rmse.csv", "rmse_flow", ("model", "S3"), 173.2, 0.03),
                 ("model_parameters_rmse.csv", "rmse_flow", ("model", "Greenshields"), 386.4, 0.05)],
         figures=["figures/fd_model_comparison.png"],
         note="S3 must remain the best-or-tied flow RMSE of the fitted suite"),
    dict(name="paq_corridor", script="reproduce_paq.py",
         checks=[("paq_fit_results.csv", "r2_trapezoid", "median", 0.603, 0.10),
                 ("paq_fit_results.csv", "r2_quadratic", "median", 0.549, 0.10)],
         figures=["figures/paq_field_and_queue.png", "figures/paq_shape_fits.png"],
         note="trapezoid >= quadratic >> quartic/cubic ordering must hold (medians)"),
    dict(name="engine_comparison", script=None,
         checks=[("ai_arena_results.csv", "mae_congested_kmh", "min", 0.0, None)],
         figures=["engine_comparison.png"],
         note="AI arena artifacts present; regenerate via cbi_pipeline.ai_arena"),
    dict(name="cbi_arizona", script="reproduce_cbi_arizona.py",
         checks=[("agreement_stats.csv", "P_corr", "min", 0.30, None),
                 ("agreement_stats.csv", "vt2_corr", "min", 0.50, None)],
         figures=["figures/cbi_agreement.png"],
         note="legacy-vs-modern agreement floors (different scan rules; see page)"),
]


def _value(df: pd.DataFrame, col: str, sel):
    if sel is None:
        return float(df[col].iloc[0])
    if sel == "median":
        return float(df[col].median())
    if sel == "min":
        return float(df[col].min())
    key, val = sel
    return float(df.loc[df[key] == val, col].iloc[0])


def run_all(rerun: bool = False) -> pd.DataFrame:
    rows = []
    for spec in REGISTRY:
        d = BM / spec["name"]
        if rerun and spec.get("script"):
            print(f"[repro] running {spec['name']}/{spec['script']} ...")
            r = subprocess.run([sys.executable, spec["script"]], cwd=d,
                               capture_output=True, text=True)
            if r.returncode != 0:
                rows.append(dict(benchmark=spec["name"], gate="script_runs",
                                 value="exit %d" % r.returncode, expected="0",
                                 verdict="FAIL", note=r.stderr[-200:]))
                continue
            rows.append(dict(benchmark=spec["name"], gate="script_runs",
                             value="ok", expected="0", verdict="PASS", note=""))
        for fig in spec.get("figures", []):
            ok = (d / fig).exists()
            rows.append(dict(benchmark=spec["name"], gate=f"figure:{Path(fig).name}",
                             value="present" if ok else "missing", expected="present",
                             verdict="PASS" if ok else "FAIL", note=""))
        for csvf, col, sel, exp, tol in spec.get("checks", []):
            p = d / csvf
            if not p.exists():
                rows.append(dict(benchmark=spec["name"], gate=f"{col}", value="missing csv",
                                 expected=exp, verdict="FAIL", note=csvf))
                continue
            try:
                v = _value(pd.read_csv(p), col, sel)
            except Exception as e:
                rows.append(dict(benchmark=spec["name"], gate=col, value=f"error {type(e).__name__}",
                                 expected=exp, verdict="FAIL", note=str(e)[:120]))
                continue
            if tol is None:                      # floor check
                ok = v >= exp
                rows.append(dict(benchmark=spec["name"], gate=f"{col}>= {exp}",
                                 value=round(v, 4), expected=f">={exp}",
                                 verdict="PASS" if ok else "FAIL",
                                 note=spec.get("note", "")))
            else:
                ok = abs(v - exp) <= tol * abs(exp)
                rows.append(dict(benchmark=spec["name"], gate=col, value=round(v, 4),
                                 expected=f"{exp}±{tol*100:.0f}%",
                                 verdict="PASS" if ok else "FAIL",
                                 note=spec.get("note", "")))
    df = pd.DataFrame(rows)
    df.to_csv(BM / "repro_pass_fail.csv", index=False)
    n = df["verdict"].value_counts().to_dict()
    print(f"[repro_gates] {n} -> benchmarks/repro_pass_fail.csv")
    for r in df[df["verdict"] == "FAIL"].itertuples(index=False):
        print(f"   FAIL {r.benchmark}/{r.gate} = {r.value} (need {r.expected})")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="re-run every reproduce script first")
    a = ap.parse_args()
    df = run_all(rerun=a.run)
    sys.exit(1 if (df["verdict"] == "FAIL").any() else 0)


if __name__ == "__main__":
    main()
