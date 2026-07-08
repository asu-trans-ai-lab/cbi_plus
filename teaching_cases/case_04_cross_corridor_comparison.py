"""
Teaching case 04 — cross-corridor comparison (after running cases 01-03).

Reads `quality_gates.json` and `link_qvdf_corridor.csv` from all three
corridor outputs and produces a side-by-side comparison:

    - Gate status matrix    (corridor x gate)
    - QVDF parameters       (corridor / period x Q_n, Q_s, Q_cd, Q_cp)
    - Reliability ladder    (n_episodes, n_sensors, source)

This is the case to use when sanity-checking whether your priors are
consistent across very different facility types (rural INRIX vs urban
PeMS vs chronically-congested PeMS).

Run from the package root AFTER cases 01-03:
    python teaching_cases/case_04_cross_corridor_comparison.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
PACKAGE_ROOT = HERE.parent
OUTPUTS_ROOT = PACKAGE_ROOT / "outputs"

# The (case_dir, corridor_subdir) pairs we'll harvest from
CASES = [
    ("case_01_I-17",   "I-17"),
    ("case_02_I-10",   "10-E"),
    ("case_03_I-405",  "405-S"),
]


def _read_gate(case_root: Path, corridor: str) -> dict:
    f = case_root / corridor / "quality_gates.json"
    if not f.exists():
        return {}
    return json.loads(f.read_text())


def _read_agg(case_root: Path, corridor: str) -> pd.DataFrame:
    f = case_root / corridor / "stage5b_corridor" / "link_qvdf_corridor.csv"
    if not f.exists():
        return pd.DataFrame()
    df = pd.read_csv(f)
    df["case"] = case_root.name
    return df


def main():
    if not OUTPUTS_ROOT.exists():
        print(f"No outputs directory yet at {OUTPUTS_ROOT}.")
        print("Run cases 01-03 first.")
        sys.exit(1)

    print("=" * 78)
    print("CROSS-CORRIDOR QUALITY-GATE MATRIX")
    print("=" * 78)
    rows = []
    for case_dir, corr in CASES:
        gates = _read_gate(OUTPUTS_ROOT / case_dir, corr)
        if not gates:
            print(f"  [{corr:6s}] no quality_gates.json found (skip)")
            continue
        overall = gates.pop("__overall__", None)
        rows.append({"corridor": corr, "overall": overall,
                     **{g: gates[g]["status"] for g in gates}})
    if rows:
        gate_df = pd.DataFrame(rows).set_index("corridor")
        print(gate_df.to_string())

    print("\n" + "=" * 78)
    print("CROSS-CORRIDOR QVDF PARAMETERS (shrunk values, period x corridor)")
    print("=" * 78)
    aggs = []
    for case_dir, corr in CASES:
        agg = _read_agg(OUTPUTS_ROOT / case_dir, corr)
        if agg.empty:
            continue
        aggs.append(agg)
    if aggs:
        df = pd.concat(aggs, ignore_index=True)
        cols = ["corridor", "period", "n_episodes_used",
                "n_distinct_sensors", "reliability_class",
                "Q_n_shrunk", "Q_s_shrunk", "Q_cd_shrunk", "Q_cp_shrunk",
                "Q_alpha_shrunk", "Q_beta_shrunk",
                "Q_n_source", "Q_cp_source"]
        cols = [c for c in cols if c in df.columns]
        print(df[cols].to_string(index=False))

        out_csv = OUTPUTS_ROOT / "cross_corridor_comparison.csv"
        df.to_csv(out_csv, index=False)
        print(f"\n[wrote] {out_csv}")

    print("\n" + "=" * 78)
    print("Interpretation notes:")
    print("  * I-17 (rural INRIX, vf=74 mph autocal) is expected to have")
    print("    higher Q_n than urban interstates because rural recovery is")
    print("    faster (less spillback).")
    print("  * I-405-S (chronic urban) will have wide CIs on Q_cp because")
    print("    every day's bottleneck operates at slightly different geometry.")
    print("  * If shrunk values differ from medians by > 50%, the corridor")
    print("    has a 'thin sample' problem - report the prior-anchored value")
    print("    and flag in the paper.")


if __name__ == "__main__":
    main()
