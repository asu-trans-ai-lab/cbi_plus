"""
Teaching case 03 — CA PeMS I-405 South (20 sensors, March 2018).

What you learn here:
  - How chronic-congestion corridors (I-405-S is one of the worst in the
    country) produce DIFFERENT diagnostics than freer corridors:
        * valid_episode_pct will be very high (most weekdays are congested)
        * the mu_R2 gap may be SMALL or even negative because the all_days
          and valid_only sets are nearly identical. THIS IS A FINDING,
          not a bug -- write it up.
  - How the round-by-round QVDF audit (Stage 5 verification) handles long P
    episodes with high D/C ratios.
  - How Stage 2b flags real outliers (incident days, sensor jams) on a
    high-volume corridor where they actually occur.

Run from the package root:
    python teaching_cases/case_03_ca_pems_i405.py
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
    out_root = PACKAGE_ROOT / "outputs" / "case_03_I-405"
    summary = corridor_workflow.run_corridor(
        corridor="405-S",
        source="pems",
        pems_path=PACKAGE_ROOT / "benchmarks" / "I-405" / "link_performance.json",
        pems_representative=False,
        v_c_mph=45.0,
        v_f_mph=65.0,
        n_boot=30,
        out_root=out_root,
    )
    print("\n" + "=" * 60)
    print(f"CASE 03 done. Outputs at: {out_root}/405-S/")
    print(f"  status = {summary['status']}")
    print(f"  valid_episodes = {summary['n_valid_episodes']}")
    r2_gap = (summary['mu_compare']['valid_only_r2']
              - summary['mu_compare']['all_days_r2'])
    print(f"  mu_R2 gap = {r2_gap:+.3f}")
    print("On I-405-S, a small or negative gap is NORMAL: chronic congestion")
    print("means the all-days sample IS the valid sample, so there's no")
    print("structural bias to expose. The finding is the lack of a gap.")
    return summary


if __name__ == "__main__":
    main()
