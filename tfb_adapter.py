#!/usr/bin/env python3
"""TrafficFlowBench -> cbi_pipeline adapter + runner.

Bridges the IEEE TrafficFlowBench PeMS-LA release (parquet detector states +
GMNS link lanes) into the compact-JSON + sensor_information.csv pair the
cbi_pipeline PeMS loader expects, then runs the full corridor workflow.

Usage (from clean_handoff_v2/codes/):
    python tfb_adapter.py I-210E 2026-06-01 2026-06-28

Units bridged:
    speed   km/h  -> stored as 's' (loader divides by 1.609 -> mph)
    flow    total veh/h -> per-lane vph ('f')
    density total veh/km -> per-lane veh/mi ('d' = density/lanes*1.609)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

TFB_ROOT = Path("C:/source_codes/0_source_code_new/IEEE_Simulate_Players/"
                "ASU_Internal_Version_DLSIM_IEEE/02_data_PeMS_LA")
OUT_ROOT = Path(__file__).resolve().parent / "outputs" / "trafficflowbench"


def build_inputs(corridor: str, t0: str, t1: str, work: Path) -> tuple[Path, Path]:
    """Emit compact JSON + sensor_information.csv for one corridor/window."""
    rel = TFB_ROOT / "release" / corridor
    df = pd.read_parquet(rel / "train_detector_states.parquet")
    df = df[(df["date"] >= t0) & (df["date"] <= t1)].copy()
    if df.empty:
        sys.exit(f"no rows for {corridor} in [{t0}, {t1}]")
    # The release IMPUTES missing stations by copying neighbors (is_observed=False).
    # Feeding imputed series to the FD fit produces duplicate fits across sensors
    # and impossible capacities (found by the independent result review: 11 sensors
    # with byte-identical FD params, capacities of 840 and 9,443 vphpl). Blank the
    # imputed cells and drop stations that are mostly imputation.
    if "is_observed" in df.columns:
        obs_frac = df.groupby("station_id")["is_observed"].mean()
        keep = obs_frac[obs_frac >= 0.60].index
        n_drop = df["station_id"].nunique() - len(keep)
        df = df[df["station_id"].isin(keep)].copy()
        df.loc[~df["is_observed"].astype(bool),
               ["speed", "flow", "occupancy", "density"]] = np.nan
        print(f"[adapter] observed-data filter: dropped {n_drop} mostly-imputed "
              f"stations; blanked imputed cells on the rest")
    df["datetime"] = pd.to_datetime(df["timestamp"].str.replace("Z", ""))

    links = pd.read_csv(TFB_ROOT / "corridors" / corridor / "train_gmns_link.csv")
    lanes_by_link = links.set_index("link_id")["lanes"].to_dict()

    fwy = "".join(ch for ch in corridor if ch.isdigit())        # I-210E -> 210
    drc = corridor[-1]                                          # -> E

    blob, info_rows = {}, []
    for sid, g in df.groupby("station_id"):
        g = g.sort_values("datetime")
        # regular 5-min grid over the window (fill gaps with NaN)
        grid = pd.date_range(g["datetime"].min().normalize(),
                             g["datetime"].max().normalize() + pd.Timedelta("23h55min"),
                             freq="5min")
        g = g.set_index("datetime").reindex(grid)
        # Effective lanes from the data, not OSM: GMNS/OSM lane tags are unreliable
        # here (e.g. lanes=2 on a section flowing 5,100+ veh/h). Anchor on ~2,000
        # vphpl at the p99 5-min flow — self-consistent with freeway capacity.
        p99 = float(np.nanpercentile(g["flow"].dropna(), 99)) if g["flow"].notna().any() else 6000.0
        lanes = int(np.clip(round(p99 / 2000.0), 2, 6))
        gmns_lanes = int(lanes_by_link.get(g["link_id"].dropna().iloc[0], 0) or 0)
        mp = float(g["milepost"].dropna().iloc[0])
        blob[str(sid)] = {
            "meta": {"corridor": corridor, "lanes": lanes,
                     "gmns_lanes": gmns_lanes, "milepost_mi": mp},
            "t0": grid[0].isoformat(),
            "dt": "5min",
            "n": len(grid),
            # speeds stay km/h — the loader converts (documented legacy quirk)
            "s": [round(float(v), 2) if np.isfinite(v) else None for v in g["speed"]],
            "f": [round(float(v) / lanes, 1) if np.isfinite(v) else None for v in g["flow"]],
            "d": [round(float(v) / lanes * 1.609, 2) if np.isfinite(v) else None
                  for v in g["density"]],
        }
        info_rows.append({"sensor_id": sid, "Fwy": fwy, "Dir": drc,
                          "Lanes": lanes, "Length": 1.0, "Abs_PM": mp})

    work.mkdir(parents=True, exist_ok=True)
    jpath = work / f"tfb_{corridor}_{t0}_{t1}.json"
    ipath = work / f"tfb_{corridor}_sensor_information.csv"
    jpath.write_text(json.dumps(blob))
    pd.DataFrame(info_rows).sort_values("Abs_PM").to_csv(ipath, index=False)
    print(f"[adapter] {len(blob)} sensors -> {jpath.name}, {ipath.name}")
    return jpath, ipath


def main():
    corridor = sys.argv[1] if len(sys.argv) > 1 else "I-210E"
    t0 = sys.argv[2] if len(sys.argv) > 2 else "2026-06-01"
    t1 = sys.argv[3] if len(sys.argv) > 3 else "2026-06-28"
    max_sensors = int(sys.argv[4]) if len(sys.argv) > 4 else None

    work = OUT_ROOT / "_inputs"
    jpath, ipath = build_inputs(corridor, t0, t1, work)

    from cbi_pipeline import io_unified, corridor_workflow
    io_unified.SENSOR_INFO_CSV = ipath                     # metadata override
    # loader signature reads the module-level default at call time via kwarg default
    orig = io_unified._attach_pems_metadata
    io_unified._attach_pems_metadata = lambda df, info_csv=ipath: orig(df, info_csv)

    fwy = "".join(ch for ch in corridor if ch.isdigit())
    cbi_corr = f"{fwy}-{corridor[-1]}"                     # 210-E
    summary = corridor_workflow.run_corridor(
        corridor=cbi_corr, source="pems", pems_path=jpath,
        s3_prior="ca_pems_freeway",
        v_c_mph=45.0, v_f_mph=65.0, n_boot=30,
        out_root=OUT_ROOT, max_sensors=max_sensors,
    )
    print(json.dumps({k: str(v) for k, v in summary.items()}, indent=1))


if __name__ == "__main__":
    main()
