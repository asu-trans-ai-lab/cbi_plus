# -*- coding: utf-8 -*-
"""flow_tensor — the Flow-Through-Tensor engine (docs/FLOW_TENSOR_MATH.md).

Implements the corridor-state tensor view: HOSVD mode spectra + physical mode
interpretation (spatial bottleneck modes, daily rhythm modes, day-type modes),
Tucker reconstruction price-of-rank, and the OD-FREE flow-through residual
along the sorted chain. NO dynamic OD estimation anywhere — network operators
are used forward-only, and the OD-consistency number is informational.

Usage:
    python -m cbi_pipeline.flow_tensor --json <compact.json> \
        [--out benchmarks/flow_tensor_demo]

Outputs: mode_spectra.csv, tucker_price_of_rank.csv, flow_through_residual.csv,
figures/flow_tensor_modes.png, figures/price_of_rank.png
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
# figure emission must not clobber a notebook's interactive/inline backend
if not str(matplotlib.get_backend()).lower().startswith(
        ("inline", "module://matplotlib_inline", "nbagg", "ipympl", "widget", "module://ipympl")):
    matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load_tensors(blob_path: Path):
    blob = json.loads(Path(blob_path).read_text())
    sensors = sorted(blob, key=lambda s: blob[s]["meta"].get("milepost_mi", 0))
    mp = [blob[s]["meta"].get("milepost_mi", i) for i, s in enumerate(sensors)]
    lanes = [blob[s]["meta"].get("lanes", 3) for s in sensors]
    nd = blob[sensors[0]]["n"] // 288

    def cube(key):
        X = np.full((len(sensors), 288, nd), np.nan)
        for i, s in enumerate(sensors):
            a = np.array([np.nan if v is None else v for v in blob[s][key]], float)
            X[i] = a[:nd * 288].reshape(nd, 288).T
        return X
    return cube("s"), cube("f"), sensors, np.array(mp), np.array(lanes)


def _fill(X):
    prof = np.nanmean(X, axis=2, keepdims=True)
    prof = np.where(np.isnan(prof), np.nanmean(X), prof)
    return np.where(np.isnan(X), np.repeat(prof, X.shape[2], axis=2), X)


def unfold(X, n):
    return np.moveaxis(X, n, 0).reshape(X.shape[n], -1)


def mode_spectra(X) -> tuple[pd.DataFrame, dict, list]:
    """singular spectra + effective rank per mode; returns leading vectors."""
    rows, leads = [], []
    eff = {}
    names = ["space (sensors)", "time-of-day", "days"]
    for n in range(3):
        M = unfold(X, n)
        U, s, _ = np.linalg.svd(M - M.mean(), full_matrices=False)
        e = s**2
        expl = np.cumsum(e) / e.sum()
        eff[names[n]] = round(float(e.sum()**2 / np.sum(e**2)), 2)
        k90 = int(np.searchsorted(expl, 0.90) + 1)
        rows += [dict(mode=names[n], k=i + 1, sigma=round(float(s[i]), 2),
                      cum_explained=round(float(expl[i]), 4))
                 for i in range(min(10, len(s)))]
        leads.append(U[:, :3])
        print(f"  mode {names[n]:<16} eff_rank={eff[names[n]]:>5}  K90={k90}")
    return pd.DataFrame(rows), eff, leads


def tucker_reconstruct(X, r):
    """HOSVD truncation at rank tuple r (numpy-only Tucker)."""
    Xc = X - X.mean()
    Us = []
    for n in range(3):
        U, _, _ = np.linalg.svd(unfold(Xc, n), full_matrices=False)
        Us.append(U[:, :r[n]])
    G = Xc.copy()
    for n in range(3):
        G = np.moveaxis(np.tensordot(Us[n].T, np.moveaxis(G, n, 0), axes=1), 0, n)
    R = G
    for n in range(3):
        R = np.moveaxis(np.tensordot(Us[n], np.moveaxis(R, n, 0), axes=1), 0, n)
    return R + X.mean()


def flow_through_residual(Qf, lanes) -> pd.DataFrame:
    """OD-free conservation view along the sorted chain: the station-to-station
    total-flow difference per time bin = net ramp exchange + noise. Reported as
    information (large persistent |r| between two stations = unmetered ramps or
    a detector bias), never inverted into demand."""
    tot = Qf * lanes[:, None, None]                      # per-lane -> total veh/h
    day_mean = np.nanmean(tot, axis=2)                   # sensors x tod
    r = np.diff(day_mean, axis=0)                        # station-to-station
    return pd.DataFrame({
        "between_stations": [f"{i}->{i+1}" for i in range(r.shape[0])],
        "mean_exchange_vph": np.round(np.nanmean(r, axis=1), 1),
        "p95_abs_exchange_vph": np.round(np.nanpercentile(np.abs(r), 95, axis=1), 1),
    })


def run(blob_path: Path, out_dir: Path):
    out_dir = Path(out_dir)
    (out_dir / "figures").mkdir(parents=True, exist_ok=True)
    Xs, Qf, sensors, mp, lanes = load_tensors(blob_path)
    X = _fill(Xs)

    spec, eff, leads = mode_spectra(X)
    spec.to_csv(out_dir / "mode_spectra.csv", index=False)

    # price of rank
    rows = []
    base = float(np.nanmean(np.abs(Xs - np.nanmean(Xs))))
    for r in [(1, 1, 1), (2, 2, 1), (3, 4, 2), (5, 6, 3), (8, 10, 4)]:
        R = tucker_reconstruct(X, r)
        mae = float(np.nanmean(np.abs(R - Xs)))
        rows.append(dict(rank=str(r), mae_kmh=round(mae, 2),
                         vs_mean_baseline=round(mae / base, 3)))
        print(f"  Tucker rank {str(r):<12} MAE={mae:5.2f} km/h")
    pr = pd.DataFrame(rows)
    pr.to_csv(out_dir / "tucker_price_of_rank.csv", index=False)

    ft = flow_through_residual(Qf, lanes)
    ft.to_csv(out_dir / "flow_through_residual.csv", index=False)

    # figures: spatial modes vs milepost + rhythm modes + price-of-rank
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.4))
    for j in range(3):
        ax[0].plot(mp, leads[0][:, j], marker="o", ms=3, label=f"mode {j+1}")
    ax[0].set_xlabel("milepost"); ax[0].set_title("spatial modes — bottleneck fingerprints")
    tod = np.arange(288) / 12
    for j in range(3):
        ax[1].plot(tod, leads[1][:, j], label=f"mode {j+1}")
    ax[1].set_xlabel("hour of day"); ax[1].set_title("time-of-day rhythm modes")
    for a in ax[:2]:
        a.legend(fontsize=8)
    ax[2].plot(range(len(pr)), pr["mae_kmh"], marker="s")
    ax[2].set_xticks(range(len(pr))); ax[2].set_xticklabels(pr["rank"], rotation=20)
    ax[2].set_ylabel("reconstruction MAE (km/h)"); ax[2].set_title("Tucker price of rank")
    fig.suptitle(f"Flow-Through-Tensor view — {Path(blob_path).name} "
                 f"(eff. ranks: {eff})", fontsize=10)
    fig.tight_layout()
    fig.savefig(out_dir / "figures" / "flow_tensor_modes.png", dpi=140)
    print(f"[flow_tensor] -> {out_dir} (mode_spectra, price_of_rank, "
          f"flow_through_residual, figures)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--out", default="benchmarks/flow_tensor_demo")
    a = ap.parse_args()
    run(Path(a.json), Path(a.out))


if __name__ == "__main__":
    main()
