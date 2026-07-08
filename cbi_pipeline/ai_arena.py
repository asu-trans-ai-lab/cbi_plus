# -*- coding: utf-8 -*-
"""ai_arena — the AI/ML families compete on masked-cell state reconstruction.

The competition's actual non-path task: cells of the corridor speed field are
masked; each engine reconstructs them; scoring mirrors S_state (all masked
cells AND congested cells separately). Engines wired (numpy-only core, so
every tester can run it):

    persistence        last observed value at the sensor (naive baseline)
    tod_profile        time-of-day mean over training days (recurring baseline)
    matrix_completion  Soft-Impute low-rank (tensor_tools.low_rank_complete)
    tensor_cube        3-D completion sensor x tod x day (tensor_tools.tensor_complete)
    rpca_lowrank       RPCA L-component as the recurrent reconstruction
    pinn_tse           REGISTERED but NOT YET COUPLED to the corridor
                       contract — always reported SKIPPED regardless of
                       whether torch imports (the vendored MobileCentury
                       PINN has its own I/O; wiring is stage-1 pending).
                       (Independent review, Jinxi Wu 2026-07-08, finding #5:
                       the old docstring implied torch presence enabled it.)

Usage:
    python -m cbi_pipeline.ai_arena --json <compact.json> [--mask 0.3] [--seed 7]
        [--out benchmarks/engine_comparison]

Emits ai_arena_results.csv (+ per-engine metrics) for the comparison page.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .tensor_tools import low_rank_complete, tensor_complete, rpca

V_CONG_KMH = 72.0            # congested cell: below ~45 mph (S_state's focus)


def load_cube(blob_path: Path) -> tuple[np.ndarray, list]:
    blob = json.loads(Path(blob_path).read_text())
    sensors = sorted(blob, key=lambda s: blob[s]["meta"].get("milepost_mi", 0))
    n_days = blob[sensors[0]]["n"] // 288
    cube = np.full((len(sensors), 288, n_days), np.nan)
    for i, s in enumerate(sensors):
        a = np.array([np.nan if v is None else v for v in blob[s]["s"]], float)
        cube[i] = a[:n_days * 288].reshape(n_days, 288).T
    return cube, sensors


def engines(cube_tr: np.ndarray, mask_known: np.ndarray) -> dict:
    """Each engine returns a full reconstruction of the cube."""
    ns, nt, nd = cube_tr.shape
    out = {}

    # persistence: forward-fill along time within each sensor-day
    p = cube_tr.copy()
    for d in range(nd):
        for i in range(ns):
            v = p[i, :, d]
            idx = np.where(np.isfinite(v))[0]
            if idx.size:
                v_ff = np.interp(np.arange(nt), idx, v[idx])
                p[i, :, d] = v_ff
    out["persistence"] = np.nan_to_num(p, nan=np.nanmean(cube_tr))

    # time-of-day profile per sensor (mean over days of known cells)
    prof = np.nanmean(np.where(mask_known, cube_tr, np.nan), axis=2, keepdims=True)
    prof = np.where(np.isnan(prof), np.nanmean(cube_tr), prof)
    out["tod_profile"] = np.repeat(prof, nd, axis=2)

    # matrix completion on the (sensor*tod) x day unfolding
    M = cube_tr.reshape(ns * nt, nd)
    Mm = mask_known.reshape(ns * nt, nd)
    out["matrix_completion"] = low_rank_complete(
        np.nan_to_num(M, nan=0.0), Mm, rank=6).reshape(ns, nt, nd)

    # 3-D tensor completion
    out["tensor_cube"] = tensor_complete(
        np.nan_to_num(cube_tr, nan=0.0), mask_known)

    # RPCA low-rank component (on the day-unfolding, known cells mean-filled)
    filled = np.where(mask_known, np.nan_to_num(cube_tr, nan=0.0),
                      np.repeat(prof, nd, axis=2))
    L, S, _ = rpca(filled.reshape(ns * nt, nd))
    out["rpca_lowrank"] = L.reshape(ns, nt, nd)

    # PINN (optional — torch)
    try:
        import torch  # noqa: F401
        out["pinn_tse"] = None      # registered; coupling via corridor contract pending
    except ImportError:
        pass
    return out


def score(recon: np.ndarray, truth: np.ndarray, eval_mask: np.ndarray) -> dict:
    err = np.abs(recon - truth)[eval_mask]
    cong = eval_mask & (truth < V_CONG_KMH)
    err_c = np.abs(recon - truth)[cong]
    return dict(mae_all_kmh=round(float(np.nanmean(err)), 2),
                rmse_all_kmh=round(float(np.sqrt(np.nanmean(err**2))), 2),
                mae_congested_kmh=round(float(np.nanmean(err_c)), 2) if err_c.size else None,
                n_cells=int(eval_mask.sum()), n_congested=int(cong.sum()))


def make_holdout(known: np.ndarray, mask_frac: float, mode: str, rng) -> np.ndarray:
    """cells: random cells (easy — neighbors known, interpolation wins).
    blocks: contiguous 2-hour blocks per sensor-day (the competition's dark-
    sensor reality — completion families must borrow strength across days)."""
    if mode == "cells":
        return known & (rng.random(known.shape) < mask_frac)
    ns, nt, nd = known.shape
    hold = np.zeros_like(known)
    blk = 24                                   # 2 h of 5-min bins
    n_blocks_total = int(mask_frac * ns * nd * nt / blk)
    for _ in range(n_blocks_total):
        i, d = rng.integers(ns), rng.integers(nd)
        t0 = rng.integers(0, nt - blk)
        hold[i, t0:t0 + blk, d] = True
    return hold & known


def run(blob_path: Path, mask_frac: float = 0.3, seed: int = 7,
        out_dir: Path | None = None, mode: str = "blocks") -> pd.DataFrame:
    cube, sensors = load_cube(blob_path)
    known = np.isfinite(cube)
    rng = np.random.default_rng(seed)
    holdout = make_holdout(known, mask_frac, mode, rng)
    train_mask = known & ~holdout
    cube_tr = np.where(train_mask, cube, np.nan)

    rows = []
    for name, recon in engines(cube_tr, train_mask).items():
        if recon is None:
            rows.append(dict(engine=name,
                             status="SKIPPED (coupling pending, regardless of torch)"))
            continue
        rows.append(dict(engine=name, status="ok",
                         **score(recon, cube, holdout)))
        print(f"  {name:<18} {rows[-1].get('mae_all_kmh', '—'):>7} km/h all "
              f"| {rows[-1].get('mae_congested_kmh', '—')} km/h congested")
    df = pd.DataFrame(rows).sort_values("mae_congested_kmh", na_position="last")
    df.insert(0, "source", Path(blob_path).name)
    df.insert(1, "mask_frac", mask_frac)
    df.insert(2, "mask_mode", mode)
    if out_dir:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_dir / "ai_arena_results.csv", index=False)
        print(f"[ai_arena] -> {out_dir/'ai_arena_results.csv'}")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--mask", type=float, default=0.3)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--mode", choices=["cells", "blocks"], default="blocks")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    run(Path(a.json), a.mask, a.seed, Path(a.out) if a.out else None, a.mode)


if __name__ == "__main__":
    main()
