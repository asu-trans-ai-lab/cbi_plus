"""
Teaching case 02 — CA PeMS I-10 East (16 sensors, March 2018).

What you learn here:
  - How PeMS speed + measured volume drives a real S3 FD fit
    (vs the INRIX inverse-S3 synthesis in Case 01).
  - How a 30-day window across many sensors produces a strong
    structural-bias finding (mu_R2 gap > 0.10).
  - How the corridor aggregation in Stage 5b reaches HIGH reliability
    on the PM period when you have multiple sensors and 22 weekdays.

Run from the package root:
    python teaching_cases/case_02_ca_pems_i10.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE_ROOT = HERE.parent                         # .../clean_handoff_v2/
CODE_ROOT = PACKAGE_ROOT / "codes"
sys.path.insert(0, str(CODE_ROOT))

from cbi_pipeline import corridor_workflow      # noqa: E402


def main():
    out_root = PACKAGE_ROOT / "outputs" / "case_02_I-10"
    summary = corridor_workflow.run_corridor(
        corridor="10-E",
        source="pems",
        pems_path=PACKAGE_ROOT / "benchmarks" / "I-10" / "link_performance.json",
        pems_representative=False,             # the demo JSON IS the full set
        v_c_mph=45.0,                          # urban interstate v_c
        v_f_mph=65.0,
        n_boot=30,
        out_root=out_root,
    )
    print("\n" + "=" * 60)
    print(f"CASE 02 done. Outputs at: {out_root}/10-E/")
    print(f"  status = {summary['status']}")
    print(f"  valid_episodes = {summary['n_valid_episodes']}")
    r2_gap = (summary['mu_compare']['valid_only_r2']
              - summary['mu_compare']['all_days_r2'])
    print(f"  mu_R2 gap = {r2_gap:+.3f}  (positive = structural bias from "
          f"uncongested days; expected for urban interstates)")
    return summary


if __name__ == "__main__":
    main()
