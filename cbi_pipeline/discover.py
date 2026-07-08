# -*- coding: utf-8 -*-
"""discover — find every CBI+-compatible dataset under a root, by file signature.

The tool should locate its own inputs. Walks a directory tree (skipping VCS,
caches, archives) and classifies candidates:

  inrix_folder   TMC_Identification.csv + Readings.csv side by side
                 -> ready for  corridor_workflow --source inrix --inrix-folder
  ritis_export   RITIS speed CSV (tmc_code + measurement_tstamp header) with a
                 TMC_Identification*.csv nearby (same dir or parent)
                 -> ready after pointing load_inrix at the pair
  pems_json      compact PeMS JSON ({sensor: {t0, dt, n, f, s, d}})
                 -> ready for  corridor_workflow --source pems --pems-path
  tfb_release    TrafficFlowBench train_detector_states.parquet
                 -> ready via  tfb_adapter.py
  trajectory     NGSIM-format trajectory data (Lane/Local_Y/Velocity columns)
                 -> tensor_tools cube experiments (not the corridor workflow)

Each hit is probed lightly (header sniff / first rows only — never a full load)
for sensor counts, date range, and a readiness verdict.

CLI:
    python -m cbi_pipeline.discover C:/source_codes [--csv out.csv] [--max-depth 7]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
from pathlib import Path

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "env",
             ".idea", ".vscode", "site-packages", "dist", "build", ".claude",
             "outputs", "tile_cache", "snapshots"}
MAX_SNIFF_BYTES = 65536


def _sniff_header(path: Path) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            line = f.readline(4096)
        return [c.strip().lower() for c in line.split(",")]
    except OSError:
        return []


def _csv_probe(path: Path) -> dict:
    """Rows (from size heuristic), first+approx-last timestamp, without full read."""
    info = {"size_mb": round(path.stat().st_size / 1e6, 1)}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            head = [f.readline() for _ in range(3)]
            f.seek(max(0, path.stat().st_size - MAX_SNIFF_BYTES))
            tail = f.read().splitlines()
        cols = [c.strip().lower() for c in head[0].split(",")]
        def ts_of(line):
            for cell in line.split(","):
                cell = cell.strip().strip('"')
                if len(cell) >= 10 and cell[:4].isdigit() and cell[4] in "-/":
                    return cell[:16]
            return None
        info["t_first"] = next((ts_of(l) for l in head[1:] if l), None)
        info["t_last"] = next((ts_of(l) for l in reversed(tail[1:]) if l), None)
        info["n_cols"] = len(cols)
    except OSError:
        pass
    return info


def _inrix_probe(folder: Path) -> dict:
    tmc = folder / "TMC_Identification.csv"
    rd = folder / "Readings.csv"
    out = {"n_tmcs": None}
    try:
        with open(tmc, encoding="utf-8", errors="ignore") as f:
            out["n_tmcs"] = sum(1 for _ in f) - 1
        hdr = _sniff_header(tmc)
        out["has_road_order"] = "road_order" in hdr
        out.update({f"readings_{k}": v for k, v in _csv_probe(rd).items()})
        r_hdr = _sniff_header(rd)
        out["readings_ok"] = bool({"tmc_code", "measurement_tstamp", "speed"} & set(r_hdr)) \
            or bool({"tmc", "speed"} & set(r_hdr))
    except OSError:
        pass
    return out


def _pems_json_probe(path: Path) -> dict | None:
    """Accept only compact-format JSON: {id: {t0, n, s...}} — sniff first 4KB."""
    try:
        head = open(path, encoding="utf-8", errors="ignore").read(4096)
        if '"t0"' not in head or ('"s"' not in head and '"f"' not in head):
            return None
        blob = json.load(open(path, encoding="utf-8", errors="ignore"))
        if not isinstance(blob, dict) or not blob:
            return None
        first = next(iter(blob.values()))
        if not (isinstance(first, dict) and "t0" in first and "n" in first):
            return None
        return {"n_sensors": len(blob), "t0": str(first.get("t0"))[:16],
                "n_bins": first.get("n"),
                "size_mb": round(path.stat().st_size / 1e6, 1)}
    except (OSError, json.JSONDecodeError, StopIteration):
        return None


def scan(root: Path, max_depth: int = 7) -> list[dict]:
    hits, seen_dirs = [], set()
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        rel_depth = len(d.relative_to(root).parts)
        if rel_depth > max_depth:
            dirnames[:] = []
            continue
        dirnames[:] = [x for x in dirnames if x not in SKIP_DIRS and not x.endswith(".zip")]
        fset = {f.lower(): f for f in filenames}

        # 1) canonical INRIX folder
        if "tmc_identification.csv" in fset and "readings.csv" in fset:
            hits.append({"type": "inrix_folder", "path": str(d),
                         **_inrix_probe(d)})
            seen_dirs.add(str(d))
            continue

        # 2) TrafficFlowBench release
        if "train_detector_states.parquet" in fset:
            p = d / fset["train_detector_states.parquet"]
            hits.append({"type": "tfb_release", "path": str(d),
                         "corridor": d.name,
                         "size_mb": round(p.stat().st_size / 1e6, 1),
                         "has_abnormal": "abnormal_cells.parquet" in fset})
            continue

        for f in filenames:
            fl = f.lower()
            p = d / f
            # 3) compact PeMS JSON
            if fl.endswith(".json") and ("link_performance" in fl or "pems" in fl
                                         or "tfb_" in fl):
                pr = _pems_json_probe(p)
                if pr:
                    hits.append({"type": "pems_json", "path": str(p), **pr})
            # 4) loose RITIS export (speed csv without Readings.csv name)
            elif fl.endswith(".csv") and any(k in fl for k in
                                             ("reading", "speed", "5min", "tmc")) \
                    and "identification" not in fl and str(d) not in seen_dirs:
                hdr = set(_sniff_header(p))
                if {"tmc_code", "measurement_tstamp"} <= hdr:
                    near = list(d.glob("TMC_Identification*.csv")) or \
                        list(d.parent.glob("TMC_Identification*.csv"))
                    hits.append({"type": "ritis_export", "path": str(p),
                                 "tmc_id_nearby": str(near[0]) if near else None,
                                 **_csv_probe(p)})
            # 5) NGSIM-style trajectories (tensor cube input)
            elif fl.endswith((".txt", ".csv")) and ("trajector" in fl or "ngsim" in fl):
                hdr = set(_sniff_header(p))
                if hdr & {"lane_identification", "lane num", "local_y", "vehicle id",
                          "vehicle_id"}:
                    hits.append({"type": "trajectory", "path": str(p),
                                 "size_mb": round(p.stat().st_size / 1e6, 1)})
    return hits


def readiness(h: dict) -> str:
    t = h["type"]
    if t == "inrix_folder":
        if h.get("readings_ok") and h.get("has_road_order"):
            return "READY: --source inrix --inrix-folder <path>"
        if h.get("readings_ok"):
            return "NEEDS road_order in TMC_Identification (add or map from miles)"
        return "CHECK Readings.csv schema"
    if t == "tfb_release":
        return "READY: tfb_adapter.py <corridor>"
    if t == "pems_json":
        return "READY: --source pems --pems-path <path> (+ sensor_information.csv)"
    if t == "ritis_export":
        return ("READY: load_inrix(readings, tmc_id)" if h.get("tmc_id_nearby")
                else "NEEDS TMC_Identification.csv (found none nearby)")
    if t == "trajectory":
        return "tensor_tools: space_time_lane_tensor / cube completion"
    return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--max-depth", type=int, default=7)
    a = ap.parse_args()
    hits = scan(Path(a.root), a.max_depth)
    for h in hits:
        h["readiness"] = readiness(h)
    by = {}
    for h in hits:
        by.setdefault(h["type"], []).append(h)
    # duplicate-copy awareness: many bundles mirror the same dataset — group
    # tfb_release by corridor name so 18 copies read as 6 corridors
    tfb = by.get("tfb_release", [])
    if tfb:
        uniq = sorted({h.get("corridor") for h in tfb})
        print(f"[note] tfb_release: {len(tfb)} copies of {len(uniq)} corridors: {uniq}")
    print(f"\n=== CBI+ dataset discovery under {a.root} — {len(hits)} hits ===")
    for t, rows in sorted(by.items()):
        print(f"\n-- {t} ({len(rows)}) --")
        for h in rows:
            extra = {k: v for k, v in h.items()
                     if k not in ("type", "path", "readiness") and v is not None}
            print(f"  {h['path']}")
            print(f"     {extra}")
            print(f"     -> {h['readiness']}")
    if a.csv:
        keys = sorted({k for h in hits for k in h})
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(hits)
        print(f"\nwrote {a.csv}")


if __name__ == "__main__":
    main()
