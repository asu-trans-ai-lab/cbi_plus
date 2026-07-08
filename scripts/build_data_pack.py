# -*- coding: utf-8 -*-
"""build_data_pack — samples, Parquet, GeoJSON and format docs for every
dataset shipped in the repo.

For notebook/analytics users: each benchmark/engine dataset gets, under
benchmarks/_datapack/:

    <name>_sample.csv      first 60 rows — see the schema at a glance
    <name>.parquet         full table, zstd — pd.read_parquet and go
                           (tracked in git when <= 10 MB, else regenerate here)
    <name>.geojson         spatial layer where the data has geometry
    DATA_FORMATS.md        every schema, column by column

Run:  python scripts/build_data_pack.py       (from dev/ root, ~2 min)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BM = ROOT / "benchmarks"
OUT = BM / "_datapack"
OUT.mkdir(exist_ok=True)

TRACK_LIMIT_MB = 10.0
_doc: list[str] = []


def emit(name: str, df: pd.DataFrame, desc: str, unit_notes: dict | None = None):
    df.head(60).to_csv(OUT / f"{name}_sample.csv", index=False)
    pq = OUT / f"{name}.parquet"
    df.to_parquet(pq, compression="zstd", index=False)
    mb = pq.stat().st_size / 1e6
    tracked = mb <= TRACK_LIMIT_MB
    _doc.append(f"\n## `{name}`  ({len(df):,} rows · parquet {mb:.1f} MB"
                f"{' · parquet tracked' if tracked else ' · parquet REGENERATE-LOCALLY (over size gate)'})\n\n{desc}\n")
    _doc.append("| column | dtype | example | note |\n|---|---|---|---|")
    ex = df.iloc[0] if len(df) else {}
    for c in df.columns:
        note = (unit_notes or {}).get(c, "")
        _doc.append(f"| `{c}` | {df[c].dtype} | {str(ex.get(c, ''))[:28]} | {note} |")
    print(f"  {name:<28} {len(df):>9,} rows  parquet {mb:6.1f} MB  {'tracked' if tracked else 'LOCAL-ONLY'}")
    if not tracked:
        pq.rename(pq.with_suffix(".parquet.localonly"))


def geojson_points(name, df, lon, lat, props):
    feats = [{"type": "Feature",
              "geometry": {"type": "Point", "coordinates": [round(float(r[lon]), 6), round(float(r[lat]), 6)]},
              "properties": {p: (None if pd.isna(r[p]) else (float(r[p]) if isinstance(r[p], (int, float, np.floating)) else str(r[p]))) for p in props}}
             for _, r in df.iterrows() if np.isfinite(r[lon]) and np.isfinite(r[lat])]
    (OUT / f"{name}.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "features": feats}))
    print(f"  {name}.geojson  ({len(feats)} points)")


def geojson_lines(name, df, x1, y1, x2, y2, props):
    feats = []
    for _, r in df.iterrows():
        if not all(np.isfinite(r[c]) for c in (x1, y1, x2, y2)):
            continue
        feats.append({"type": "Feature",
                      "geometry": {"type": "LineString",
                                   "coordinates": [[round(float(r[x1]), 6), round(float(r[y1]), 6)],
                                                   [round(float(r[x2]), 6), round(float(r[y2]), 6)]]},
                      "properties": {p: (None if pd.isna(r[p]) else str(r[p])) for p in props}})
    (OUT / f"{name}.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "features": feats}))
    print(f"  {name}.geojson  ({len(feats)} lines)")


def compact_json_to_long(path: Path) -> pd.DataFrame:
    blob = json.loads(path.read_text())
    frames = []
    for sid, p in blob.items():
        n = int(p.get("n", 0))
        if not n:
            continue
        t = pd.date_range(p["t0"], periods=n, freq=p.get("dt", "5min"))
        frames.append(pd.DataFrame({
            "sensor_id": sid, "datetime": t,
            "speed_kmh": pd.array(p.get("s", [None] * n), dtype="Float64"),
            "flow_vphpl": pd.array(p.get("f", [None] * n), dtype="Float64"),
            "density": pd.array(p.get("d", [None] * n), dtype="Float64")}))
    return pd.concat(frames, ignore_index=True)


def main():
    print("building data pack ->", OUT)

    # 1) PeMS compact JSON benchmarks (I-10, I-405 Mar-2018)
    for corr in ("I-10", "I-405"):
        emit(f"pems_{corr.replace('-', '').lower()}_2018_states",
             compact_json_to_long(BM / corr / "link_performance.json"),
             f"CA PeMS {corr} (March 2018) detector states from the compact JSON "
             f"(`benchmarks/{corr}/link_performance.json`). Long format, 5-min.",
             {"speed_kmh": "km/h (legacy 's' field)", "flow_vphpl": "per-lane veh/h",
              "density": "per-lane density (legacy units)"})
        si = pd.read_csv(BM / corr / "sensor_information.csv")
        emit(f"pems_{corr.replace('-', '').lower()}_2018_sensors", si,
             f"Sensor metadata for {corr} (PeMS): location, lanes, milepost.")
        geojson_points(f"pems_{corr.replace('-', '').lower()}_2018_sensors", si,
                       "Longitude", "Latitude", ["sensor_id", "Fwy", "Dir", "Lanes", "Abs_PM"])

    # 2) QVDF paper case 1 (I-10 Phoenix 2016)
    raw = pd.read_csv(BM / "qvdf_paper_i10" / "data" / "corridor_measurement_I10.csv.gz")
    emit("qvdf_paper_i10_measurements", raw,
         "QVDF paper Case-Study-1 raw corridor measurements (I-10 Phoenix WB, "
         "4 ADOT detectors, 15-min, all of 2016). From the paper's public repo.",
         {"volume_per_lane_per_interval": "veh per 15-min per lane", "speed": "mph"})

    # 3) QVDF paper case 2 (I-405 4-month workbook)
    dcp = pd.read_excel(BM / "qvdf_paper_casestudy2" / "data" / "02-I405_Summary_4month.xlsx",
                        sheet_name="DC-P ")
    day = dcp[["Day", "D/C", "P", "D", "µ = D/P", "Obs_µ/C", "Capacity"]].dropna(subset=["D/C", "P"])
    day.columns = ["day_index", "dc_ratio", "P_hours", "demand_veh_per_lane",
                   "mu_vphpl", "mu_over_C", "capacity_vphpl"]
    day = day[pd.to_numeric(day["day_index"], errors="coerce").notna()].copy()
    day["day_index"] = day["day_index"].astype(int)
    emit("qvdf_paper_casestudy2_perday", day,
         "QVDF paper Case-Study-2 per-day observations (I-405 NB single "
         "bottleneck, 4 months, 253 days) from the paper's own workbook.")

    # 4) CBI Arizona INRIX
    rd = pd.read_csv(BM / "cbi_arizona" / "data" / "Reading.csv.gz")
    emit("cbi_arizona_inrix_readings", rd,
         "Legacy CBI tool's Arizona sample: INRIX/RITIS probe speeds, 432 TMCs, "
         "Jan 2019, 5-min.", {"speed": "mph", "measurement_tstamp": "local time"})
    tmc = pd.read_csv(BM / "cbi_arizona" / "data" / "TMC_Identification.csv")
    emit("cbi_arizona_tmc_identification", tmc,
         "TMC segment metadata (RITIS): geometry endpoints, miles, road_order.")
    geojson_lines("cbi_arizona_tmc_segments", tmc,
                  "start_longitude", "start_latitude", "end_longitude", "end_latitude",
                  ["tmc", "road", "direction", "miles", "road_order"])

    # 5) PAQ corridor (xlsx days -> one long table)
    frames = []
    for f in sorted((BM / "paq_corridor" / "data" / "Dataset 1" / "Speed").glob("Speed_*.xlsx")):
        d = pd.read_excel(f).rename(columns={"Postmile (Abs)": "postmile_abs",
                                             "AggSpeed": "speed_mph", "Time": "time"})
        d["day"] = f.stem.split("_")[1]
        frames.append(d[["day", "time", "postmile_abs", "VDS", "speed_mph"]])
    emit("paq_corridor_speeds", pd.concat(frames, ignore_index=True),
         "PAQ repo Dataset 1: 22-detector corridor 5-min speeds, 22 April days "
         "(long format, one row per detector-interval).")

    # 6) FD suite input
    emit("fd_16models_input", pd.read_csv(BM / "fd_16models" / "data" / "input_data.csv"),
         "Traffic-Flow-FD repo scatter: per-interval Flow/Speed/Density triples "
         "used to fit the 16-model suite.")

    # 7) engines: CTM + PINN natives
    emit("ctm_demand", pd.read_csv(ROOT / "engines" / "ctm_python" / "demand.csv"),
         "CTM-Python native demand input (see engines/ctm_python).")
    emit("ctm_supply", pd.read_csv(ROOT / "engines" / "ctm_python" / "supply.csv"),
         "CTM-Python native supply/capacity input.")
    emit("pinn_mobilecentury_loop",
         pd.read_csv(ROOT / "engines" / "pinn_tse" / "data" / "MobileCentury" / "loop.csv"),
         "PINN TSE native loop-detector input (MobileCentury experiment).")

    header = ("# DATA_FORMATS — every dataset in this repo, for notebooks\n\n"
              "Generated by `python scripts/build_data_pack.py`. Each dataset has a\n"
              "60-row `_sample.csv`, a zstd `.parquet` (tracked when <= 10 MB —\n"
              "`.parquet.localonly` means rerun the script to regenerate), and a\n"
              "`.geojson` where the data carries geometry. Load pattern:\n\n"
              "```python\nimport pandas as pd\n"
              "df = pd.read_parquet('benchmarks/_datapack/pems_i10_2018_states.parquet')\n```\n")
    (OUT / "DATA_FORMATS.md").write_text(header + "\n".join(_doc), encoding="utf-8")
    print("wrote DATA_FORMATS.md")


if __name__ == "__main__":
    main()
