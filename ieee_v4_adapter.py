#!/usr/bin/env python3
"""ieee_v4_adapter — consume the TrafficFlowBench v4 competition release.

The v4 release (clean_release_v4/release: I405N, I405S, I5N, I5S) scores
NON-path, NON-OD criteria: a physical gate first, then the state score
(S_state = 0.40·all-cells + 0.60·congested-cells; OD-consistency is weight-0
informational). That is exactly cbi_plus territory: QC → episodes → FD → μ →
QVDF → CBI ranking, plus the physics bands the gate encodes.

v4 improves on earlier releases: `network/detector_chain_fd.csv` ships the
corridor contract directly (station→link, milepost, x_km, LANES, capacity,
k_jam, v_cut) — no lane inference needed, and `is_observed` marks imputation.

Usage:
    python ieee_v4_adapter.py I405N [t0 t1] [--v4-root <path>] [--run]
    python ieee_v4_adapter.py --make-samples          # 3-day extract of ALL corridors

Env: IEEE_V4_ROOT overrides the default release path.
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

V4_ROOT = Path(os.environ.get(
    "IEEE_V4_ROOT",
    "C:/source_codes/0_source_code_new/IEEE_Simulate_Players/"
    "version_07_07_2026/clean_release_v4/release"))
OUT_ROOT = Path(__file__).resolve().parent / "outputs" / "ieee_v4"
CORRIDORS = ("I405N", "I405S", "I5N", "I5S")


def load_corridor(corr: str, t0: str | None = None, t1: str | None = None) -> tuple:
    root = V4_ROOT / corr
    df = pd.read_csv(root / "train" / "train_detector_states.csv")
    if t0:
        df = df[(df["date"] >= t0) & (df["date"] <= (t1 or t0))]
    # respect the imputation mask (lesson: priors are not measurements)
    df.loc[~df["is_observed"].astype(bool),
           ["speed", "flow", "occupancy", "density"]] = np.nan
    chain = pd.read_csv(root / "network" / "detector_chain_fd.csv")
    return df, chain


def to_compact_json(df: pd.DataFrame, chain: pd.DataFrame, corr: str,
                    work: Path) -> tuple[Path, Path]:
    """v4 CSV -> the pipeline's compact JSON + sensor_information.csv.
    Lanes/capacity come from the SHIPPED chain_fd — no inference."""
    meta = chain.set_index("station_id")
    df = df.copy()
    df["datetime"] = pd.to_datetime(df["timestamp"].str.replace("Z", ""))
    blob, info = {}, []
    fwy = "".join(ch for ch in corr if ch.isdigit())
    drc = corr[-1]
    for sid, g in df.groupby("station_id"):
        if sid not in meta.index:
            continue
        lanes = int(meta.at[sid, "lanes"])
        g = g.sort_values("datetime")
        grid = pd.date_range(g["datetime"].min().normalize(),
                             g["datetime"].max().normalize() + pd.Timedelta("23h55min"),
                             freq="5min")
        g = g.set_index("datetime").reindex(grid)
        blob[str(sid)] = {
            "meta": {"corridor": corr, "lanes": lanes,
                     "milepost_mi": float(meta.at[sid, "milepost"]),
                     "capacity_vph": float(meta.at[sid, "capacity_vph"]),
                     "v_cut_kmh": float(meta.at[sid, "v_cut"])},
            "t0": grid[0].isoformat(), "dt": "5min", "n": len(grid),
            "s": [round(float(v), 2) if np.isfinite(v) else None for v in g["speed"]],
            "f": [round(float(v) / lanes, 1) if np.isfinite(v) else None for v in g["flow"]],
            "d": [round(float(v) / lanes * 1.609, 2) if np.isfinite(v) else None
                  for v in g["density"]],
        }
        info.append({"sensor_id": sid, "Fwy": fwy, "Dir": drc, "Lanes": lanes,
                     "Length": float(meta.at[sid, "length_km"]) / 1.609,
                     "Abs_PM": float(meta.at[sid, "milepost"])})
    work.mkdir(parents=True, exist_ok=True)
    jp = work / f"v4_{corr}.json"
    ip = work / "sensor_information.csv"
    jp.write_text(json.dumps(blob))
    pd.DataFrame(info).sort_values("Abs_PM").to_csv(ip, index=False)
    print(f"[v4] {corr}: {len(blob)} stations -> {jp.name}")
    return jp, ip


def make_samples():
    """3-day extracts of ALL FOUR corridors -> benchmarks/ieee_v4_samples/.
    Small (a few MB), format-complete: states + chain_fd + profiles head +
    test-format head + sample_submission head."""
    out = Path(__file__).resolve().parent / "benchmarks" / "ieee_v4_samples"
    for corr in CORRIDORS:
        root = V4_ROOT / corr
        d = out / corr
        d.mkdir(parents=True, exist_ok=True)
        st = pd.read_csv(root / "train" / "train_detector_states.csv")
        days = sorted(st["date"].unique())
        wk = [x for x in days if pd.Timestamp(x).dayofweek < 5]
        pick = [wk[1], wk[2], wk[len(wk) // 2]] if len(wk) > 4 else days[:3]
        st[st["date"].isin(pick)].to_csv(d / "train_detector_states_3days.csv", index=False)
        for src, dst, nrows in [("network/detector_chain_fd.csv", "detector_chain_fd.csv", None),
                                ("network/link.csv", "link.csv", None),
                                ("train/historical_profiles.csv", "historical_profiles_head.csv", 500),
                                ("test/test_detector_states_public.csv", "test_format_head.csv", 300),
                                ("test/sample_submission.csv", "sample_submission_head.csv", 300)]:
            p = root / src
            if p.exists():
                (pd.read_csv(p, nrows=nrows) if nrows else pd.read_csv(p)).to_csv(d / dst, index=False)
        print(f"[samples] {corr}: days {pick} + network + format heads -> {d}")
    (out / "README.md").write_text(
        "# IEEE TrafficFlowBench v4 — corridor samples (all 4 corridors)\n\n"
        "3 weekday extracts per corridor + the complete network/chain_fd tables +\n"
        "format heads for test/submission. Full release: set `IEEE_V4_ROOT` and use\n"
        "`ieee_v4_adapter.py <CORR> --run`. Evaluation focus (non-path, non-OD):\n"
        "physical gate first, then S_state = 0.40*all + 0.60*congested cells.\n\n"
        "Engines callable on these samples: see docs/ENGINE_SHOWCASE.md.\n",
        encoding="utf-8")
    print("[samples] wrote", out / "README.md")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corridor", nargs="?", choices=CORRIDORS)
    ap.add_argument("t0", nargs="?")
    ap.add_argument("t1", nargs="?")
    ap.add_argument("--make-samples", action="store_true")
    ap.add_argument("--run", action="store_true", help="run the full workflow after adapting")
    a = ap.parse_args()
    if a.make_samples:
        make_samples()
        return
    if not a.corridor:
        ap.error("corridor required (or --make-samples)")
    df, chain = load_corridor(a.corridor, a.t0, a.t1)
    work = OUT_ROOT / "_inputs" / a.corridor
    jp, ip = to_compact_json(df, chain, a.corridor, work)
    if a.run:
        from cbi_pipeline import io_unified, corridor_workflow
        orig = io_unified._attach_pems_metadata
        io_unified._attach_pems_metadata = lambda d2, info_csv=ip: orig(d2, info_csv)
        v_cut_mph = float(chain["v_cut"].median()) / 1.609
        vf_mph = float(chain["free_speed_kmh"].median()) / 1.609
        corr_label = f"{''.join(ch for ch in a.corridor if ch.isdigit())}-{a.corridor[-1]}"
        corridor_workflow.run_corridor(
            corridor=corr_label, source="pems", pems_path=jp,
            s3_prior="ca_pems_freeway",
            v_c_mph=round(v_cut_mph, 1), v_f_mph=round(vf_mph, 1),
            n_boot=30, out_root=OUT_ROOT)


if __name__ == "__main__":
    main()
