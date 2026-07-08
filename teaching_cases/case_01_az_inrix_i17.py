"""
Teaching case 01 — AZ I-17 (INRIX TMC speed-only, 1-min, 1-week sample).

What you learn here:
  - How INRIX TMC speed data gets loaded with the CBI inverse-S3 to
    SYNTHESIZE flow from speed (the rural_freeway / az_tmc_i17 prior).
  - How auto-calibration of vf from the 95th-percentile speed adjusts
    the S3 assumptions to this corridor's reality.
  - How Stage 2b's early outlier screen behaves on a clean week of data
    (expect: 0 outliers because Mar 24-30 2025 was real congestion).
  - How Stage 5b's shrinkage handles a thin AM period (n=7 episodes,
    2 sensors) vs a high-confidence PM period (n=32, 12 sensors).

Run from the package root:
    python teaching_cases/case_01_az_inrix_i17.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Locate the cbi_pipeline package (self-contained inside clean_handoff_v2/codes/)
HERE = Path(__file__).resolve().parent
PACKAGE_ROOT = HERE.parent                         # .../clean_handoff_v2/
CODE_ROOT = PACKAGE_ROOT / "codes"
sys.path.insert(0, str(CODE_ROOT))

from cbi_pipeline import corridor_workflow              # noqa: E402


def main():
    out_root = PACKAGE_ROOT / "outputs" / "case_01_I-17"
    summary = corridor_workflow.run_corridor(
        corridor="I-17",
        source="inrix",
        inrix_folder=PACKAGE_ROOT / "datasets" / "I-17",
        s3_prior="az_tmc_i17",                # rural AZ prior (vf=75, kc=32, C=1900)
        auto_calibrate_vf=True,               # adjust vf from observed p95 speed
        rederive_kc_and_m=True,               # re-derive k_c and m from CBI closed-form
        v_c_mph=50.0,
        v_f_mph=75.0,
        n_boot=10,
        max_sensors=20,                       # 20 NB TMCs is plenty for the demo
        out_root=out_root,
    )
    print("\n" + "=" * 60)
    print(f"CASE 01 done. Outputs at: {out_root}/I-17/")
    print(f"  status = {summary['status']}")
    print(f"  valid_episodes = {summary['n_valid_episodes']}")
    print(f"  mu_R2 gap (valid - all_days) = "
          f"{summary['mu_compare']['valid_only_r2'] - summary['mu_compare']['all_days_r2']:.3f}")
    print("Open the per-corridor folder for the FIXED-layout figures and "
          "the round-by-round QVDF audit panels.")
    return summary


if __name__ == "__main__":
    main()
