# -*- coding: utf-8 -*-
"""engine_arena — queue-shape engines compete on the same audited episodes.

v0 of the multi-engine arena (see docs/ENGINES.md): for every valid episode of
a processed corridor run, four shape engines fit the same speed-deficit queue
proxy, and the arena scores them per episode and per corridor:

    newell_quadratic   a * (t-T0)(T3-t)                (PAQ ancestor)
    paq_cubic          a * (t-T0)(T3-t)(cT3-t)         (skewed cubic)
    qvdf_quartic       a * 1/4 (t-T0)^2 (t-T3)^2       (the C++ canonical)
    trapezoid          rise-plateau-fall (25/50/25)    (oversaturation shape)

Usage:
    python -m cbi_pipeline.engine_arena <run_dir> --json <adapter_or_pems_json>
        [--out engine_arena_results.csv]

The run_dir supplies audited episodes (stage4_verification.csv); the compact
JSON supplies the speed fields. Emits per-episode winners + a scoreboard.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .schemas import PERIOD_SLICE_BOUNDS

PSTART = {p: h[0] for p, h in PERIOD_SLICE_BOUNDS.items()}


def shapes_for(n: int) -> dict:
    t = np.arange(n, dtype=float)
    T = float(n - 1)
    trap = np.clip(np.minimum(np.minimum(t / max(0.25 * T, 1), 1.0),
                              (T - t) / max(0.25 * T, 1)), 0, None)
    return {
        "newell_quadratic": t * (T - t),
        "paq_cubic": t * (T - t) * (0.85 * T - t),
        "qvdf_quartic": 0.25 * t**2 * (t - T)**2,
        "trapezoid": trap,
    }


def fit_all(deficit: np.ndarray) -> dict:
    m = np.isfinite(deficit)
    d = deficit[m]
    if len(d) < 6:
        return {}
    ss = float(((d - d.mean())**2).sum())
    out = {}
    for name, F in shapes_for(len(deficit)).items():
        Fm = F[m]
        den = float(Fm @ Fm)
        if den <= 0:
            continue
        a = float(d @ Fm) / den
        r = d - a * Fm
        out[name] = round(1 - float(r @ r) / ss, 4) if ss > 0 else np.nan
    return out


def run_arena(run_dir: Path, blob_path: Path, out_csv: Path | None = None) -> pd.DataFrame:
    v4 = pd.read_csv(run_dir / "stage4_verification" / "stage4_verification.csv")
    blob = json.loads(Path(blob_path).read_text())
    t0_ts = pd.Timestamp(next(iter(blob.values()))["t0"])

    rows = []
    for r in v4.itertuples():
        sid = r.sensor_uid.split("::")[-1]
        if sid not in blob:
            continue
        date = str(r.date)
        off = int((pd.Timestamp(date) - t0_ts).days) * 288
        arr = blob[sid]["s"][off:off + 288]
        v = np.array([np.nan if x is None else x / 1.609 for x in arr], float)
        p0 = PSTART.get(r.period, 0) * 12
        a, b = p0 + int(r.t0_idx), p0 + int(r.t3_idx)
        if b - a < 6 or b >= len(v):
            continue
        vc = float(r.v_c_prior_mph)
        deficit = np.clip(vc - v[a:b + 1], 0, None)
        scores = fit_all(deficit)
        if not scores:
            continue
        winner = max(scores, key=lambda k: scores.get(k, -9e9))
        rows.append(dict(sensor=sid, date=date, period=r.period,
                         P_min=round(float(r.P_min)), **scores, winner=winner))

    df = pd.DataFrame(rows)
    if out_csv is None:
        out_csv = run_dir / "engine_arena_results.csv"
    df.to_csv(out_csv, index=False)

    board = (df.groupby("winner").size().sort_values(ascending=False)
               .rename("episodes_won").reset_index())
    med = df[[c for c in df.columns if c.startswith(("newell", "paq", "qvdf", "trap"))]].median().round(3)
    print(f"[arena] {len(df)} episodes scored -> {out_csv}")
    print("[arena] scoreboard (episodes won):")
    for r in board.itertuples(index=False):
        print(f"   {r.winner:<18} {r.episodes_won}")
    print("[arena] median R2:", med.to_dict())
    # the physical split: long episodes -> trapezoid?
    long_ = df[df["P_min"] >= 240]
    if len(long_) > 10:
        lw = long_["winner"].value_counts()
        print(f"[arena] episodes >= 4h ({len(long_)}): winner mix {lw.to_dict()}")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--json", required=True, help="compact JSON with per-sensor speed arrays")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    run_arena(Path(a.run_dir), Path(a.json), Path(a.out) if a.out else None)


if __name__ == "__main__":
    main()
